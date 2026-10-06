"""Phoenix discovery: finds the projects Phoenix knows about and records what
each one is doing, so projects that no agent is linked to can be offered for
registration.

Read-only and metadata-only. For each project it reads a bounded, recent
sample of spans and keeps names and counts: models, tools, MCP servers, agent
names, span kinds and the NAMES of a few identity attributes. Prompt and
answer text is never read into the result. It never creates or changes an
agent — a person registers a project from the Discovered page.
"""
from __future__ import annotations

import asyncio
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import delete, select

from db.base import get_db_session
from db.models import PhoenixProject
from discovery.phoenix_client import PhoenixClient, PhoenixError
from shared.config import get_settings
from shared.logger import get_logger
from telemetry.phoenix_usage import MODEL_KEYS, _parse_time

log = get_logger("orchestrations.phoenix_discovery")

ORG_ID = "org-default"
MAX_LIST = 12          # names kept per list
MAX_PROJECTS = 500
TOOL_KEYS = ("tool.name", "gen_ai.tool.name")
MCP_KEYS = ("mcp.server",)
AGENT_KEYS = ("agent.name", "gen_ai.agent.name")
MODEL_KEYS_ALL = (*MODEL_KEYS, "gen_ai.request.model", "gen_ai.response.model")
KIND = "openinference.span.kind"
# Attribute NAMES worth showing (never values): they tell an admin whether a
# team already sends owner / department / service identity with its traces.
_IDENTITY_PREFIXES = ("service.", "deployment.", "agent.", "gen_ai.agent", "metadata.", "k8s.", "cloud.", "host.")
_PLUMBING = ("next_agent", "langgraph", "__start__", "__end__")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _top(counter: Counter, n: int = MAX_LIST) -> list[str]:
    return [name for name, _ in counter.most_common(n)]


def summarize_spans(spans: Iterable[Mapping]) -> dict:
    """What a project's spans say it does. Pure: takes span dicts, returns
    names and counts only."""
    models: Counter = Counter()
    tools: Counter = Counter()
    mcp: Counter = Counter()
    agents: Counter = Counter()
    retrievers: Counter = Counter()
    kinds: Counter = Counter()
    keys: set[str] = set()
    last_seen: datetime | None = None
    count = 0
    for span in spans:
        count += 1
        attributes = span.get("attributes") or {}
        kind = str(span.get("span_kind") or attributes.get(KIND) or "").upper()
        if kind:
            kinds[kind] += 1
        started = _parse_time(span.get("start_time"))
        if started and (last_seen is None or started > last_seen):
            last_seen = started
        for key in MODEL_KEYS_ALL:
            if _text(attributes.get(key)):
                models[_text(attributes[key])] += 1
                break
        for key in TOOL_KEYS:
            if _text(attributes.get(key)):
                tools[_text(attributes[key])] += 1
                break
        else:
            if kind == "TOOL" and _text(span.get("name")):
                tools[_text(span["name"])] += 1
        if kind == "RETRIEVER" and _text(span.get("name")):
            retrievers[_text(span["name"])] += 1
        for key in MCP_KEYS:
            if _text(attributes.get(key)):
                mcp[_text(attributes[key])] += 1
        for key in AGENT_KEYS:
            name = _text(attributes.get(key))
            if name and name.lower() not in _PLUMBING and not name.startswith("_"):
                agents[name] += 1
        for key in attributes:
            if isinstance(key, str) and key.startswith(_IDENTITY_PREFIXES):
                keys.add(key)
    return {
        "span_count": count, "last_seen": last_seen, "models": _top(models), "tools": _top(tools),
        "mcp_servers": _top(mcp), "agent_names": _top(agents), "retrievers": _top(retrievers), "span_kinds": _top(kinds),
        "attribute_keys": sorted(keys)[:30],
    }


PARALLEL_PROJECTS = 6


_KEPT_ATTRIBUTES = frozenset((*MODEL_KEYS_ALL, *TOOL_KEYS, *MCP_KEYS, *AGENT_KEYS, KIND))


def _slim(span: Mapping) -> dict:
    """Only what the summary reads, dropped as each span arrives so prompt and
    answer text is never held while a project is read."""
    attributes = span.get("attributes") or {}
    return {
        "name": span.get("name"), "span_kind": span.get("span_kind"), "start_time": span.get("start_time"),
        "attributes": {k: v for k, v in attributes.items()
                       if isinstance(k, str) and (k in _KEPT_ATTRIBUTES or k.startswith(_IDENTITY_PREFIXES))},
    }


async def _read_project(client: PhoenixClient, name: str, since: datetime, pages: int) -> dict:
    spans = []
    async for span in client.spans(name, max_pages=pages, start_time=since.isoformat()):
        spans.append(_slim(span))
    summary = summarize_spans(spans)
    if summary["span_count"] == 0:
        # Nothing in the window: read the newest span ever, so "quiet" and "stale" show a real date.
        # If that extra read fails, the project is still reported (without a date).
        try:
            async for span in client.spans(name, limit=1, max_pages=1):
                summary["last_seen"] = _parse_time(span.get("start_time"))
        except PhoenixError:
            pass
    return summary


async def discover_phoenix(agent_id: str | None = None, trigger: str = "manual", **_: Any) -> dict:
    """Scan every Phoenix project and refresh the discovery table. Never
    raises for a Phoenix failure: it reports not_configured / unreachable."""
    from api.routers.registry import _resolve_phoenix_endpoint

    settings = get_settings()
    async with get_db_session() as db:
        base_url, api_key = await _resolve_phoenix_endpoint(db, agent=None)
    base = {"trigger": trigger, "projects": 0, "new": 0, "linked": 0, "stale": 0, "failed": 0}
    if not base_url:
        return {**base, "status": "not_configured", "reason": "No Phoenix endpoint is configured (Settings → Phoenix)."}

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, settings.discovery_window_days))
    summaries: dict[str, dict] = {}
    errors: dict[str, str] = {}
    try:
        async with PhoenixClient(base_url, api_key=api_key, timeout=30.0) as client:
            projects = (await client.all_projects())[:MAX_PROJECTS]
            gate = asyncio.Semaphore(PARALLEL_PROJECTS)

            async def read(name: str) -> None:
                async with gate:
                    try:
                        summaries[name] = await _read_project(client, name, since, max(1, settings.discovery_span_pages))
                    except PhoenixError as exc:
                        errors[name] = (f"Phoenix answered HTTP {exc.status}" if exc.status
                                        else "Phoenix did not answer in time")
                    except Exception:  # one project's odd data must not stop the others
                        log.exception("phoenix_discovery.project_failed")
                        errors[name] = "Its traces could not be read"

            await asyncio.gather(*(read(p["name"]) for p in projects))
    except PhoenixError as exc:
        if exc.status in (401, 403):
            reason = "Phoenix rejected the key (HTTP %s). Check the API key in Settings → Phoenix." % exc.status
        elif exc.status == 0:
            reason = ("Phoenix did not answer. If it was idle it may still be waking up, so try again in a minute; "
                      "if it is on a private network, check the VPN.")
        else:
            reason = f"Phoenix answered HTTP {exc.status}."
        log.warning("phoenix_discovery.unreachable", http_status=exc.status)
        return {**base, "status": "unreachable", "reason": reason}

    names = [p["name"][:255].replace("\x00", "") for p in projects]
    async with get_db_session() as db:
        # The endpoint may have been changed while this scan ran. What was read belongs to the old
        # Phoenix, so it is not written over the list the change just cleared.
        now_url, _key = await _resolve_phoenix_endpoint(db, agent=None)
        if (now_url or "") != base_url:
            return {**base, "status": "skipped", "reason": "The Phoenix address was changed during the scan; scan again."}
        rows = {r.name: r for r in (await db.execute(select(PhoenixProject).where(PhoenixProject.org_id == ORG_ID))).scalars()}
        for name in names:
            row = rows.get(name)
            if row is None:
                row = PhoenixProject(id=secrets.token_hex(8), org_id=ORG_ID, name=name, state="new")
                db.add(row)
            row.scanned_at = now
            row.window_days = settings.discovery_window_days
            if name in summaries:
                s = summaries[name]
                row.span_count, row.last_seen = s["span_count"], s["last_seen"] or row.last_seen
                row.models, row.tools, row.mcp_servers = s["models"], s["tools"], s["mcp_servers"]
                row.agent_names, row.span_kinds, row.attribute_keys = s["agent_names"], s["span_kinds"], s["attribute_keys"]
                row.retrievers = s["retrievers"]
                row.scan_error = None
            else:
                row.scan_error = errors.get(name, "Not read")
        # A project Phoenix no longer lists is dropped, unless a person dismissed it.
        gone = [r.id for n, r in rows.items() if n not in set(names) and r.state != "dismissed"]
        if gone:
            await db.execute(delete(PhoenixProject).where(PhoenixProject.id.in_(gone)))
        from db.models import Agent
        linked = {a for a in (await db.execute(select(Agent.phoenix_project).where(Agent.phoenix_project.isnot(None)))).scalars() if a}
    stale_cut = now - timedelta(days=settings.discovery_stale_days)
    new = [n for n in names if n not in linked and (rows.get(n) is None or rows[n].state != "dismissed")]
    stale = [n for n in names if (summaries.get(n) or {}).get("last_seen") and summaries[n]["last_seen"] < stale_cut]
    result = {
        **base, "status": "partial" if errors else "ok", "projects": len(names), "new": len(new),
        "linked": len([n for n in names if n in linked]), "stale": len(stale), "failed": len(errors),
        "reason": f"{len(errors)} project(s) could not be read." if errors else None,
    }
    log.info("phoenix_discovery.done", **{k: v for k, v in result.items() if isinstance(v, (int, str)) and k != "reason"})
    return result
