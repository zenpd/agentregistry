"""Reads LLM spans from Phoenix and stores daily usage per agent × model.

Only whitelisted span fields are kept (telemetry.phoenix_usage.slim_span);
prompt and output text never leave this function. Re-running replaces the
stored values of every day it re-reads, so it is safe to run repeatedly.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from api.routers.registry import _resolve_phoenix_endpoint
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage
from discovery.phoenix_client import PhoenixClient, PhoenixError
from governance.costing import normalize_model, token_cost_cents
from services.usage_repo import load_aliases, load_prices
from shared.config import get_settings
from shared.logger import get_logger
from telemetry.phoenix_usage import aggregate_llm_spans, slim_span

log = get_logger("orchestrations.usage_ingestion")

PAGE_LIMIT = 1000
MAX_PAGES = 50
INCREMENTAL_DAYS = 2
PHOENIX_TIMEOUT_SECONDS = 60.0

_FAILED = {"unreachable", "auth_failed", "not_configured", "error"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(dt: datetime) -> datetime:
    # SQLite hands back naive datetimes; compare everything as naive UTC.
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _phoenix_failure(exc: PhoenixError, project: str) -> tuple[str, str]:
    if exc.status == 0:
        return "unreachable", "Phoenix did not answer (VPN down or host unreachable)."
    if exc.status in (401, 403):
        return "auth_failed", f"Phoenix rejected the API key (HTTP {exc.status})."
    if exc.status == 404:
        return "error", f"Phoenix has no project named '{project}'."
    return "error", f"Phoenix returned HTTP {exc.status}."


def overall_status(statuses: list[str]) -> str:
    if not statuses:
        return "skipped"
    if not any(s in _FAILED for s in statuses) and "partial" not in statuses:
        return "ok"
    if all(s in _FAILED for s in statuses):
        return "error"
    return "partial"


async def _fetch_spans(base_url: str, api_key: str | None, project: str, start: datetime, end: datetime) -> tuple[list[dict], bool]:
    """(slim LLM spans, truncated). Spans arrive newest first."""
    spans: list[dict] = []
    async with PhoenixClient(base_url, api_key=api_key, timeout=PHOENIX_TIMEOUT_SECONDS) as client:
        async for span in client.spans(
            project, limit=PAGE_LIMIT, max_pages=MAX_PAGES,
            start_time=start.isoformat(), end_time=end.isoformat(), span_kind="LLM",
        ):
            spans.append(slim_span(span))
    return spans, len(spans) >= PAGE_LIMIT * MAX_PAGES


async def _store(agent_id: str, rows: list[dict], prices: dict, now: datetime) -> int:
    """Replace this agent's stored values for every day present in `rows`.
    Days with no spans in this read are left untouched, so a Phoenix
    retention purge never erases history already collected."""
    days = {r["day"] for r in rows}
    async with get_db_session() as db:
        existing = (await db.execute(select(AgentTokenUsage).where(AgentTokenUsage.agent_id == agent_id))).scalars().all()
        by_key = {(_naive_utc(u.bucket), u.model_name): u for u in existing}
        touched = set()
        for r in rows:
            bucket = datetime.combine(r["day"], time.min, tzinfo=timezone.utc)
            key = (_naive_utc(bucket), r["model"])
            price = prices.get(r["model"])
            cost = round(token_cost_cents(r["input_tokens"], r["output_tokens"], r["cached_tokens"], price)) if price else 0
            values = dict(
                invocation_count=r["calls"], input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                cached_tokens=r["cached_tokens"], cost_cents=cost, error_count=r["errors"],
                latency_avg_ms=round(r["latency_avg_ms"]) if r["latency_avg_ms"] is not None else None,
                source="phoenix", run_count=r["runs"], raw_model_names=r["raw_model_names"], ingested_at=now,
            )
            row = by_key.get(key)
            if row is None:
                db.add(AgentTokenUsage(agent_id=agent_id, bucket=bucket, model_name=r["model"], **values))
            else:
                for field, value in values.items():
                    setattr(row, field, value)
            touched.add(key)
        for key, row in by_key.items():
            # A model no longer seen on a re-read day (e.g. after an alias change) is stale.
            if key not in touched and row.source == "phoenix" and key[0].date() in days:
                await db.delete(row)
    return len(rows)


async def _ingest_agent(agent: dict, aliases: dict, prices: dict, now: datetime) -> dict:
    window_days = agent["days"]
    start = datetime.combine(now.date() - timedelta(days=window_days - 1), time.min, tzinfo=timezone.utc)
    result = {"agent_id": agent["id"], "project": agent["project"], "days": window_days,
              "rows": 0, "calls": 0, "status": "ok", "reason": None, "truncated": False}
    if not agent["base_url"]:
        return {**result, "status": "not_configured", "reason": "No Phoenix endpoint is configured."}
    try:
        spans, truncated = await _fetch_spans(agent["base_url"], agent["api_key"], agent["project"], start, now)
    except PhoenixError as exc:
        status, reason = _phoenix_failure(exc, agent["project"])
        log.warning("usage_ingestion.phoenix_failed", agent_id=agent["id"], status=status, http_status=exc.status)
        return {**result, "status": status, "reason": reason}

    rows = aggregate_llm_spans(spans, normalize=lambda raw: normalize_model(raw, aliases))
    if truncated and rows:
        # Newest first: the oldest day read is only partly covered, so keep its stored values.
        partial_day = min(r["day"] for r in rows)
        rows = [r for r in rows if r["day"] != partial_day]
        result.update(status="partial", truncated=True,
                      reason=f"Stopped after {MAX_PAGES} pages of {PAGE_LIMIT} spans; {partial_day.isoformat()} and earlier were not updated.")
    result["rows"] = await _store(agent["id"], rows, prices, now)
    result["calls"] = sum(r["calls"] for r in rows)
    result["spans_read"] = len(spans)
    result["unpriced_models"] = sorted({r["model"] for r in rows if r["model"] not in prices})
    if not spans:
        result["reason"] = f"No LLM spans in the last {window_days} days."
    return result


class _NothingToIngest(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


async def _load_targets(agent_id: str | None, days: int | None) -> tuple[list[dict], dict, dict]:
    settings = get_settings()
    async with get_db_session() as db:
        stmt = select(Agent).where(Agent.id == agent_id) if agent_id else select(Agent).where(Agent.phoenix_project.isnot(None))
        agents = list((await db.execute(stmt)).scalars().all())
        if agent_id and not agents:
            raise _NothingToIngest("error", f"Agent '{agent_id}' not found.")
        agents = [a for a in agents if (a.phoenix_project or "").strip()]
        if not agents:
            raise _NothingToIngest("skipped", "No Phoenix project linked." if agent_id else "No agent has a Phoenix project linked.")
        with_rows = set((await db.execute(
            select(AgentTokenUsage.agent_id).where(
                AgentTokenUsage.source == "phoenix", AgentTokenUsage.agent_id.in_([a.id for a in agents]),
            ).distinct()
        )).scalars().all())
        targets = []
        for a in agents:
            base_url, api_key = await _resolve_phoenix_endpoint(db, a)
            window = days or (INCREMENTAL_DAYS if a.id in with_rows else settings.usage_backfill_days)
            targets.append({"id": a.id, "project": a.phoenix_project.strip(), "base_url": base_url,
                            "api_key": api_key, "days": max(1, window)})
        return targets, await load_aliases(db), await load_prices(db)


async def ingest_usage(agent_id: str | None = None, trigger: str = "manual", days: int | None = None) -> dict:
    """Ingest Phoenix LLM usage for one agent, or every agent with a linked
    project. Never raises for a Phoenix failure: each agent reports its own
    status (ok | partial | unreachable | auth_failed | not_configured | error)."""
    try:
        targets, aliases, prices = await _load_targets(agent_id, days)
    except _NothingToIngest as nothing:
        return {"status": nothing.status, "trigger": trigger, "reason": nothing.reason, "agents": [], "rows": 0, "calls": 0}
    now = _utcnow()
    results = []
    for target in targets:
        try:
            results.append(await _ingest_agent(target, aliases, prices, now))
        except Exception as exc:  # one agent's failure must not stop the others
            log.exception("usage_ingestion.agent_failed", agent_id=target["id"])
            results.append({"agent_id": target["id"], "project": target["project"], "days": target["days"],
                            "rows": 0, "calls": 0, "status": "error", "truncated": False,
                            "reason": f"Ingestion failed ({type(exc).__name__})."})
    return {
        "status": overall_status([r["status"] for r in results]),
        "trigger": trigger,
        "window_end": now.isoformat(),
        "rows": sum(r["rows"] for r in results),
        "calls": sum(r["calls"] for r in results),
        "agents": results,
    }
