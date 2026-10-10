"""Discovery: the Phoenix inbox and the paste-a-URL prefill.

The Phoenix inbox lists Phoenix projects that no registered agent is linked
to, with what each one is doing (models, tools, MCP servers, last activity).
A person registers one from it, or dismisses it with a reason. Nothing here
creates an agent: registration still goes through POST /agents, prefilled.

The URL prefill reads a few well-known paths on a host the user names (agent
card, openapi.json, health) with the same address checks as Try it."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_read, require_update
from api.routers.ops import integrate
from db.base import get_db_session
from db.models import Agent, PhoenixConfig, PhoenixProject, User
from governance import identity, reuse
from orchestrations import job_runner
from orchestrations.phoenix_discovery import ORG_ID
from orchestrations.risk_scan import as_utc
from services.audit import log_audit_event
from shared.config import get_settings
from shared.logger import get_logger

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Discovery"])
log = get_logger("api.discovery")

CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")
PROBE_TIMEOUT = 12.0
MAX_CARD_BYTES = 200_000
ALLOWED_PORTS = (80, 443)


# ── Phoenix inbox ────────────────────────────────────────────────────────────

def _activity(last_seen: datetime | None, window_days: int, stale_days: int, now: datetime) -> str:
    """active: calls inside the scan window · quiet: seen before, none lately ·
    stale: not seen for stale_days · none: never seen with calls."""
    if last_seen is None:
        return "none"
    age = now - as_utc(last_seen)
    if age <= timedelta(days=window_days):
        return "active"
    return "stale" if age >= timedelta(days=stale_days) else "quiet"


def _row(r: PhoenixProject, activity: str) -> dict:
    spans = r.span_count or 0
    return {
        "errorCount": r.error_count or 0, "serviceNames": r.service_names or [], "hints": r.hints or {},
        "errorShare": round((r.error_count or 0) / spans, 3) if spans else None,
        "assigneeUserId": r.assignee_user_id, "dueDate": r.due_date.isoformat() if r.due_date else None,
        "triageNote": r.triage_note,
        "name": r.name, "state": r.state, "activity": activity,
        "lastSeen": as_utc(r.last_seen).isoformat() if r.last_seen else None,
        "spanCount": r.span_count or 0, "windowDays": r.window_days,
        "models": r.models or [], "tools": r.tools or [], "mcpServers": r.mcp_servers or [],
        "agentNames": r.agent_names or [], "spanKinds": r.span_kinds or [],
        "attributeKeys": r.attribute_keys or [],
        "scanError": r.scan_error, "dismissReason": r.dismiss_reason,
        "scannedAt": as_utc(r.scanned_at).isoformat() if r.scanned_at else None,
    }


@router.get("/discovery/phoenix")
async def phoenix_inbox(_=Depends(require_read)):
    """Unlinked Phoenix projects (the inbox), dismissed ones, and registered
    agents' activity. Reads the table the discovery job fills; it does not
    call Phoenix itself."""
    from api.routers.registry import _resolve_phoenix_endpoint

    settings = get_settings()
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        base_url, _key = await _resolve_phoenix_endpoint(db, agent=None)
        rows = list((await db.execute(select(PhoenixProject).where(PhoenixProject.org_id == ORG_ID))).scalars())
        agents = list((await db.execute(select(Agent).where(Agent.phoenix_project.isnot(None)))).scalars())
        latest = (await job_runner.latest_runs(db, any_scope=True)).get("phoenix_discovery")
    last_scan = job_runner.run_to_dict(latest) if latest else None
    by_project: dict[str, list[Agent]] = {}
    for a in agents:
        if (a.phoenix_project or "").strip():
            by_project.setdefault(a.phoenix_project.strip(), []).append(a)

    async with get_db_session() as db:
        every = list((await db.execute(select(Agent))).scalars())
        people = dict((await db.execute(select(User.id, User.name))).all())
    candidates = [{"id": a.id, "slug": a.slug, "name": a.name, "owner": a.owner, "apiEndpoint": a.api_endpoint,
                   "phoenixProject": a.phoenix_project, "modelName": a.model_name, "mcpServers": a.mcp_servers or []}
                  for a in every]
    today = now.date()
    inbox, dismissed, registered, evaluation = [], [], [], []
    for r in sorted(rows, key=lambda x: (as_utc(x.last_seen) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
        act = _activity(r.last_seen, settings.discovery_window_days, settings.discovery_stale_days, now)
        row = _row(r, act)
        if r.name in by_project:
            linked = by_project[r.name]
            for a in linked:
                registered.append({**row, "agentId": a.id, "agentName": a.name, "stage": a.lifecycle_stage,
                                   # A demo agent shows a real project's traces on purpose, so it is left out on both sides.
                                   "sharedWith": [] if a.is_demo else [{"id": o.id, "name": o.name} for o in linked
                                                                       if o.id != a.id and not o.is_demo]})
        elif identity.is_evaluation_project(r.name):
            evaluation.append(row)
        elif r.state == "dismissed":
            dismissed.append(row)
        else:
            found = identity.matches(row, [c for c in candidates if c["phoenixProject"] != r.name])
            hygiene = identity.hygiene(row)
            if r.name == settings.phoenix_project_name:
                hygiene.insert(0, {"code": "registry_itself", "text": "These are the registry's own traces (its insight agents). "
                                                                      "Register it only if you want the registry listed as an agent; otherwise dismiss it."})
            inbox.append({**row, "matches": found, "ownerGuess": identity.owner_guess(row, found[0] if found else None),
                          "hygiene": hygiene,
                          "assigneeName": people.get(r.assignee_user_id) if r.assignee_user_id else None,
                          "overdue": bool(r.due_date and r.due_date < today)})
    return {
        "configured": bool(base_url),
        "scanning": _scan_running() or (last_scan is not None and last_scan["status"] == "running"),
        # Nothing read from the current Phoenix yet: first use, or the endpoint was changed in Settings.
        "needsScan": bool(base_url) and not any(r.scanned_at for r in rows),
        "lastScan": last_scan,
        "windowDays": settings.discovery_window_days, "staleDays": settings.discovery_stale_days,
        "summary": {
            "new": len(inbox), "dismissed": len(dismissed), "registered": len(registered), "evaluation": len(evaluation),
            "assigned": len([x for x in inbox if x["assigneeUserId"]]), "overdue": len([x for x in inbox if x["overdue"]]),
            "newActive": len([x for x in inbox if x["activity"] == "active"]),
            "quiet": len([x for x in registered if x["activity"] != "active"]),
        },
        "sampleCap": settings.discovery_span_pages * 100,
        "inbox": inbox, "dismissed": dismissed, "registered": registered, "evaluation": evaluation,
    }


# The scan runs in the background, so the page is not held open (or cut off by a proxy) while
# Phoenix is read. The page polls the inbox, which reports `scanning` until the run ends.
_scan_task: "asyncio.Task | None" = None


def _scan_running() -> bool:
    return _scan_task is not None and not _scan_task.done()


@router.post("/discovery/phoenix/scan", status_code=202)
async def phoenix_scan(user=Depends(require_update)):
    """Starts a scan and returns at once. A scan already running is not started twice."""
    global _scan_task
    if _scan_running():
        return {"started": False, "scanning": True}

    async def run() -> None:
        try:
            result = await job_runner.run_job("phoenix_discovery", agent_id=None, trigger="manual")
            await log_audit_event(
                actor=user["user_id"], action="job.run", entity_type="job", entity_id="phoenix_discovery",
                changes={"runId": result["runId"], "status": result["status"]},
            )
        except Exception:
            log.exception("phoenix_scan.failed")

    _scan_task = asyncio.get_running_loop().create_task(run(), name="phoenix-scan")
    return {"started": True, "scanning": True}


class DismissBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    reason: Optional[str] = Field(default=None, max_length=500)


async def _project_or_404(db, name: str) -> PhoenixProject:
    row = (await db.execute(select(PhoenixProject).where(PhoenixProject.org_id == ORG_ID, PhoenixProject.name == name))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="That Phoenix project has not been discovered yet. Run a scan first.")
    return row


@router.post("/discovery/phoenix/dismiss")
async def phoenix_dismiss(body: DismissBody, user=Depends(require_update)):
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Say why (for example: test run, not an agent, duplicate)")
    async with get_db_session() as db:
        row = await _project_or_404(db, body.name)
        row.state, row.dismiss_reason, row.dismissed_by = "dismissed", reason, user.get("user_id")
    await log_audit_event(actor=user["user_id"], action="discovery.dismiss", entity_type="phoenix_project",
                          entity_id=body.name, changes={"reason": reason})
    return {"status": "dismissed"}


@router.post("/discovery/phoenix/restore")
async def phoenix_restore(body: DismissBody, user=Depends(require_update)):
    async with get_db_session() as db:
        row = await _project_or_404(db, body.name)
        row.state, row.dismiss_reason, row.dismissed_by = "new", None, None
    await log_audit_event(actor=user["user_id"], action="discovery.restore", entity_type="phoenix_project",
                          entity_id=body.name, changes={})
    return {"status": "restored"}


def _humanise(name: str) -> str:
    words = [w for w in name.replace("_", " ").replace("-", " ").split() if w]
    return " ".join(w if any(c.isupper() for c in w) else w.capitalize() for w in words) or name


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


@router.get("/discovery/phoenix/prefill")
async def phoenix_prefill(name: str, _=Depends(require_read)):
    """The registration form's starting values for one Phoenix project, each
    with where it came from. Only what the traces actually say: owner,
    department and version come only from the trace-attribute convention
    (agent.owner, agent.department, agent.version) when the team set them."""
    async with get_db_session() as db:
        row = await _project_or_404(db, name)
        agents = list((await db.execute(select(Agent.id, Agent.name, Agent.slug))).all())
        config = (await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == ORG_ID))).scalar_one_or_none()
    cap = get_settings().discovery_span_pages * 100
    evidence = f"Phoenix: {row.span_count or 0}{'+' if (row.span_count or 0) >= cap else ''} spans in the last {row.window_days} days"
    fields: dict[str, Any] = {"name": _humanise(row.name), "phoenix_project": row.name}
    sources = {"name": "Phoenix project name", "phoenix_project": "Phoenix project"}
    if row.models:
        fields["model_name"], sources["model_name"] = row.models[0], f"{evidence} (most used model)"
    watched = list(dict.fromkeys([*(row.mcp_servers or []), *(row.tools or [])]))
    if watched:
        fields["mcp_servers"], sources["mcp_servers"] = watched, f"{evidence} (tool and MCP server names)"
    if row.retrievers:
        fields["knowledge_bases"], sources["knowledge_bases"] = row.retrievers, f"{evidence} (retrievers used)"
    # An agent name seen in the traces that is a registered agent is one this app calls.
    by_name = {}
    for a in agents:
        by_name[_norm(a.name)] = a.id
        by_name[_norm(a.slug or a.id)] = a.id
    called = list(dict.fromkeys(by_name[_norm(n)] for n in (row.agent_names or []) if _norm(n) in by_name))
    if called:
        fields["calls"], sources["calls"] = called, f"{evidence} (registered agents seen in its traces)"
    kinds = set(row.span_kinds or [])
    if "AGENT" in kinds or row.agent_names:
        fields["ai_type"], sources["ai_type"] = "Autonomous Agent", f"{evidence} (agent spans present)"
    hints = row.hints or {}
    missing = ["owner", "department", "business outcome", "value"]
    if hints.get("agent.owner"):
        fields["owner"], sources["owner"] = hints["agent.owner"], f"{evidence} (agent.owner on the spans)"
        missing.remove("owner")
    if hints.get("agent.department"):
        async with get_db_session() as db:
            from db.models import Department
            depts = {d.name.lower(): d.id for d in (await db.execute(select(Department))).scalars()}
        dept = depts.get(hints["agent.department"].strip().lower())
        if dept:
            fields["dept"], sources["dept"] = dept, f"{evidence} (agent.department on the spans)"
            missing.remove("department")
    if hints.get("agent.version"):
        fields["version"], sources["version"] = hints["agent.version"], f"{evidence} (agent.version on the spans)"
    return {"project": row.name, "fields": fields, "sources": sources,
            "missing": missing,
            "attributeKeys": row.attribute_keys or [],
            "canFindApp": bool(config and config.app_url_template)}


# ── Paste-a-URL prefill ──────────────────────────────────────────────────────

class PrefillUrlBody(BaseModel):
    url: str = Field(min_length=1, max_length=500)


def card_check(card: Any) -> dict:
    """Is this JSON a usable A2A agent card? Reports problems instead of a
    bare yes/no: most published cards are partly wrong."""
    if not isinstance(card, dict):
        return {"conformant": False, "problems": ["The card is not a JSON object"]}
    problems = []
    for key in ("name", "description"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            problems.append(f"Missing {key}")
    if not (isinstance(card.get("url"), str) or isinstance(card.get("supportedInterfaces"), list)):
        problems.append("Missing url or supportedInterfaces")
    if not isinstance(card.get("skills"), list):
        problems.append("Missing skills list")
    return {"conformant": not problems, "problems": problems}


def pinned_request(url: str, ip: str | None) -> tuple[str, dict[str, str], dict[str, Any]]:
    """(url, headers, extensions) that connect to `ip` — the address that passed the check — while
    still sending the real host name (Host header and TLS name). Without it the name would be
    looked up again for each request, and could answer with a different address the second time."""
    headers = {"Accept": "application/json", "X-Registry-Try-It": "true"}
    if not ip:
        return url, headers, {}
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc_ip = f"[{ip}]" if ":" in ip else ip
    headers["Host"] = f"{host}{port}"
    return parsed._replace(netloc=f"{netloc_ip}{port}").geturl(), headers, {"sni_hostname": host}


async def _probe(client: httpx.AsyncClient, url: str, limit: int, ip: str | None = None) -> dict:
    target, headers, extensions = pinned_request(url, ip)
    try:
        async with client.stream("GET", target, headers=headers, extensions=extensions) as resp:
            raw, truncated = await integrate._read_capped(resp, limit)
    except httpx.TimeoutException:
        return {"url": url, "status": None, "error": "No response in time"}
    except httpx.HTTPError as exc:
        return {"url": url, "status": None, "error": type(exc).__name__}
    return {"url": url, "status": resp.status_code, "ok": resp.is_success, "raw": raw, "truncated": truncated,
            "redirect": resp.headers.get("location") if resp.is_redirect else None}


def _json_of(probe: dict) -> Any:
    if not probe.get("ok") or probe.get("truncated"):
        return None
    try:
        return json.loads(probe["raw"].decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):
        return None


# Words teams add to a project name that are not part of the app's host name.
_GENERIC_SUFFIXES = ("assistant", "agent", "agents", "bot", "service", "app", "api")


def address_candidates(template: str, project: str) -> list[str]:
    """Addresses to try for a project, most likely first: the project name as
    it is, then without one generic last word (digital-onboarding-assistant ->
    digital-onboarding). Empty when the name cannot be a host name."""
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")
    if not slug or "{project}" not in template:
        return []
    names = [slug]
    head, _, last = slug.rpartition("-")
    if head and last in _GENERIC_SUFFIXES:
        names.append(head)
    return [template.replace("{project}", n) for n in names if len(n) <= 63]


async def _read_app(raw_url: str) -> dict:
    """What an app publishes about itself at raw_url: agent card, OpenAPI
    document, health. Raises TryItBlocked for an address that may not be
    called and OSError when the name does not resolve."""
    settings = get_settings()
    base = reuse.backend_sibling(raw_url) or reuse.origin(raw_url)
    try:
        host, port = urlparse(base).hostname, urlparse(base).port or (443 if base.startswith("https") else 80)
    except ValueError:
        raise reuse.TryItBlocked("That web address has an invalid port")
    if port not in ALLOWED_PORTS and settings.app_env != "development":
        raise reuse.TryItBlocked("Only the standard web ports (80 and 443) can be read")
    result: dict[str, Any] = {"ok": False, "url": raw_url, "base": base, "usedSibling": base != reuse.origin(raw_url),
                              "card": {"found": False}, "openapi": {"found": False}, "health": {"ok": False}}
    addresses = await integrate._resolve(host, port)
    reuse.check_addresses(addresses, settings.app_env == "development")
    ip = addresses[0]                                              # every request below goes to this checked address

    async with integrate._http_client(PROBE_TIMEOUT) as quick, integrate._http_client(settings.api_discovery_timeout_seconds) as slow:
        # OpenAPI first, with the long timeout: an app that scales to zero wakes up on this request,
        # so the quick probes after it are answered instead of timing out on a cold start.
        spec = await _probe(slow, base + "/openapi.json", integrate.MAX_SPEC_BYTES, ip)
        *card_probes, health = await asyncio.gather(
            *[_probe(quick, base + p, MAX_CARD_BYTES, ip) for p in CARD_PATHS], _probe(quick, base + "/health", 20_000, ip))
    fields: dict[str, Any] = {"api_endpoint": raw_url}
    sources: dict[str, str] = {"api_endpoint": "The address you entered"}

    for path, probe in zip(CARD_PATHS, card_probes):
        card = _json_of(probe)
        if card is not None:
            check = card_check(card)
            result["card"] = {"found": True, "path": path, "legacyPath": path.endswith("agent.json"), **check}
            if isinstance(card, dict):
                if isinstance(card.get("name"), str):
                    fields["name"], sources["name"] = card["name"].strip()[:255], f"Agent card ({path})"
                if isinstance(card.get("description"), str):
                    fields["description"], sources["description"] = card["description"].strip()[:2000], f"Agent card ({path})"
                skills = [s.get("name") or s.get("id") for s in card.get("skills") or [] if isinstance(s, dict)]
                skills = [str(s) for s in skills if s][:12]
                if skills:
                    fields["capabilities"], sources["capabilities"] = skills, f"Agent card skills ({path})"
            break

    doc = _json_of(spec)
    if isinstance(doc, dict) and isinstance(doc.get("paths"), dict):
        try:
            found = reuse.openapi_operations(doc)
            io = reuse.openapi_io(doc)
        except (ValueError, TypeError, AttributeError, RecursionError):
            found, io = None, {"inputs": [], "outputs": []}
        if found:
            info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
            result["openapi"] = {"found": True, "title": found["title"], "operations": len(found["operations"]),
                                 "otherMethods": found["otherMethods"]}
            if found["title"] and "name" not in fields:
                fields["name"], sources["name"] = str(found["title"])[:255], "OpenAPI title"
            if isinstance(info.get("description"), str) and info["description"].strip() and "description" not in fields:
                fields["description"], sources["description"] = info["description"].strip()[:2000], "OpenAPI description"
            if "capabilities" not in fields:
                caps = [o["summary"] for o in found["operations"] if o["summary"] and not reuse.is_plumbing(o["summary"])][:8]
                if caps:
                    fields["capabilities"], sources["capabilities"] = caps, "OpenAPI operations"
            if io["inputs"]:
                fields["inputs"], sources["inputs"] = io["inputs"], "OpenAPI request fields"
            if io["outputs"]:
                fields["outputs"], sources["outputs"] = io["outputs"], "OpenAPI response fields"
    elif spec.get("status") and not spec.get("ok"):
        result["openapi"] = {"found": False, "status": spec["status"]}

    result["health"] = {"ok": bool(health.get("ok")), "status": health.get("status")}
    result.update(ok=True, fields=fields, sources=sources)
    return result


@router.post("/agents/prefill-url")
async def prefill_from_url(body: PrefillUrlBody, user=Depends(require_update)):
    """Reads an app's agent card, OpenAPI document and health path and returns
    starting values for the registration form, each with its source. Read-only:
    no agent is created."""
    settings = get_settings()
    actor = user.get("user_id", "unknown")
    if not integrate._within_rate_limit(actor, "prefill-url", settings.try_it_calls_per_minute):
        raise HTTPException(status_code=429, detail=f"At most {settings.try_it_calls_per_minute} lookups per minute")
    raw_url = body.url.strip()
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Enter a full web address such as https://my-agent-be.example.com")
    await log_audit_event(actor=actor, action="discovery.read_app", entity_type="url",
                          entity_id=reuse.origin(raw_url)[:200], changes={"via": "address"})
    try:
        return await _read_app(raw_url)
    except reuse.TryItBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (OSError, ValueError) as exc:
        base = reuse.backend_sibling(raw_url) or reuse.origin(raw_url)
        return {"ok": False, "url": raw_url, "base": base, "usedSibling": base != reuse.origin(raw_url),
                "card": {"found": False}, "openapi": {"found": False}, "health": {"ok": False},
                "error": f"Could not resolve {urlparse(base).hostname}.", "hint": integrate._RESOLVE_HINT}


class FindAppBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.post("/discovery/phoenix/find-app")
async def find_app(body: FindAppBody, user=Depends(require_update)):
    """Looks for a Phoenix project's app at the address pattern saved in
    Settings and, when one answers with an OpenAPI document or agent card,
    returns the same starting values as the address lookup. The address is a
    guess from the project name, and is labelled as one."""
    settings = get_settings()
    async with get_db_session() as db:
        row = await _project_or_404(db, body.name)
        config = (await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == ORG_ID))).scalar_one_or_none()
    template = (config.app_url_template if config else None) or ""
    if not template:
        return {"ok": False, "found": False, "reason": "no_template", "tried": []}
    if not integrate._within_rate_limit(user.get("user_id", "unknown"), "prefill-url", settings.try_it_calls_per_minute):
        raise HTTPException(status_code=429, detail=f"At most {settings.try_it_calls_per_minute} lookups per minute")
    await log_audit_event(actor=user.get("user_id", "unknown"), action="discovery.find_app", entity_type="phoenix_project",
                          entity_id=row.name[:200], changes={"via": "address pattern"})
    tried = []
    for url in address_candidates(template, row.name):
        tried.append(url)
        try:
            result = await _read_app(url)
        except (reuse.TryItBlocked, OSError, ValueError):
            continue
        if result["openapi"]["found"] or result["card"]["found"]:
            note = "Address guessed from the project name — check it"
            result["sources"]["api_endpoint"] = note
            return {**result, "found": True, "guessed": True, "tried": tried}
    return {"ok": False, "found": False, "reason": "no_answer", "tried": tried}



# ── Candidate triage: assign, merge into a record, split from a record ─────

class TriageBody(BaseModel):
    assigneeUserId: Optional[str] = Field(None, max_length=64)
    dueDate: Optional[date] = None
    note: Optional[str] = Field(None, max_length=1000)


@router.put("/discovery/phoenix/{name}/triage")
async def triage_project(name: str, body: TriageBody, user=Depends(require_update)):
    """Who looks at this candidate and by when. Unset fields stay as they are; an empty assignee clears it."""
    updates = body.model_dump(exclude_unset=True)
    async with get_db_session() as db:
        row = await _project_or_404(db, name)
        if "assigneeUserId" in updates:
            uid = updates["assigneeUserId"] or None
            if uid and (await db.get(User, uid)) is None:
                raise HTTPException(status_code=422, detail="Unknown person")
            row.assignee_user_id = uid
        if "dueDate" in updates:
            row.due_date = updates["dueDate"]
        if "note" in updates:
            row.triage_note = (updates["note"] or "").strip() or None
        result = {"name": name, "assigneeUserId": row.assignee_user_id,
                  "dueDate": row.due_date.isoformat() if row.due_date else None, "note": row.triage_note}
    await log_audit_event(actor=user["user_id"], action="discovery.triage", entity_type="phoenix_project",
                          entity_id=name[:64], changes={k: str(v) for k, v in updates.items()})
    return result


class MergeBody(BaseModel):
    agentId: str = Field(..., max_length=64)


@router.post("/discovery/phoenix/{name}/merge")
async def merge_project(name: str, body: MergeBody, user=Depends(require_update)):
    """This project is that registered agent: link them. The record's other fields do not change;
    the next refresh fills in what the traces show."""
    async with get_db_session() as db:
        await _project_or_404(db, name)
        agent = await db.get(Agent, body.agentId)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent.phoenix_project and agent.phoenix_project != name:
            raise HTTPException(status_code=409, detail=(
                f"{agent.name} is already linked to the project {agent.phoenix_project}. "
                "Split it from that project first, or register this one as its own agent."))
        agent.phoenix_project = name
        agent_name = agent.name
    await log_audit_event(actor=user["user_id"], action="discovery.merge", entity_type="agent", entity_id=body.agentId,
                          changes={"phoenixProject": name})
    return {"agentId": body.agentId, "agentName": agent_name, "phoenixProject": name}


@router.post("/agents/{agent_id}/phoenix/split")
async def split_project(agent_id: str, user=Depends(require_update)):
    """This agent is not that project after all: unlink it. The project goes back to the Discovered inbox."""
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        project = agent.phoenix_project
        if not project:
            raise HTTPException(status_code=409, detail="This agent is not linked to a project.")
        agent.phoenix_project = None
    await log_audit_event(actor=user["user_id"], action="discovery.split", entity_type="agent", entity_id=agent_id,
                          changes={"phoenixProject": project})
    return {"agentId": agent_id, "unlinkedProject": project}


@router.get("/discovery/phoenix/{name}/links")
async def project_links(name: str, exclude: str = "", _=Depends(require_read)):
    """Registered agents already linked to this project (the registration form warns when there are any)."""
    async with get_db_session() as db:
        rows = (await db.execute(select(Agent.id, Agent.name, Agent.lifecycle_stage).where(Agent.phoenix_project == name))).all()
    return {"project": name, "agents": [{"id": i, "name": n, "stage": st} for i, n, st in rows if i != exclude]}
