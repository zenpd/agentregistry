"""Keeps an agent's record filled in from what the registry can see for itself.

`maintain_agent` gathers the evidence (real usage, traces, the app's own API
document), asks governance/autofill.py what may be updated, applies it, and
writes down every change: an audit row, and an AgentFieldUpdate row holding the
old value so a person can undo it. A model is called only to draft a
description or capabilities for a record that has none.

The rules about WHAT may change live in governance/autofill.py. This module
only fetches, applies and records."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from db.base import get_db_session
from db.models import (
    Agent, AgentBudget, AgentFieldUpdate, AgentRecordCheck, AgentTokenUsage, AuditLog, GovernanceReview, PhoenixConfig,
)
from governance import autofill as rules
from governance import reuse
from services.usage_repo import load_aliases
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("services.autofill")

ACTOR = "ai:record-keeper"
USAGE_DAYS = 30
_USER = {"user_id": ACTOR, "role": "viewer"}
RECALCULATE = ("cost_rollup", "risk_scan", "governance_checks")
# How long a check stays good. The daily job renews it; a page asks for a new one only after this.
RECHECK_AFTER = timedelta(hours=26)
RETRY_AFTER = timedelta(hours=1)          # when a source could not be read last time
TRACES, APP = "its traces", "the app's own API description"


_QUANTITY = re.compile(r"\d|\b(?:hundreds?|thousands?|millions?|billions?|dozens?)\b", re.I)


def link_signature(agent: Agent) -> str:
    """The sources a check read. When either changes, the record is looked at again."""
    return f"{(agent.phoenix_project or '').strip()}|{(agent.api_endpoint or '').strip()}"[:800]


def has_source(agent: Agent) -> bool:
    """Is there anything the registry could read about this agent by itself?"""
    if agent.deprecated_at is not None or agent.lifecycle_stage == "Deprecated":
        return False                                          # a retired agent's record is left as it is
    return bool((agent.phoenix_project or "").strip()) or \
        (agent.api_endpoint or "").strip().lower().startswith(("http://", "https://"))


def _wrap(value: Any) -> dict:
    return {"v": value}


def _unwrap(value: Any) -> Any:
    return value.get("v") if isinstance(value, dict) else value


def _history(rows: list[AgentFieldUpdate]) -> list[rules.Past]:
    return [rules.Past(field=r.field, old=_unwrap(r.old_value), new=_unwrap(r.new_value), reverted=r.reverted_at is not None)
            for r in rows]


def _record(agent: Agent) -> dict:
    return {field: getattr(agent, field) for field in rules.FIELD_LABELS}


async def _load(agent_id: str) -> tuple[Agent | None, list[AgentFieldUpdate]]:
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        rows = list((await db.execute(
            select(AgentFieldUpdate).where(AgentFieldUpdate.agent_id == agent_id).order_by(AgentFieldUpdate.applied_at.desc())
        )).scalars())
    return agent, rows


async def _usage_models(agent_id: str) -> tuple[list[tuple[str, int]], dict]:
    since = datetime.now(timezone.utc) - timedelta(days=USAGE_DAYS)
    async with get_db_session() as db:
        rows = (await db.execute(
            select(AgentTokenUsage.model_name, func.sum(AgentTokenUsage.invocation_count))
            .where(AgentTokenUsage.agent_id == agent_id, AgentTokenUsage.source.in_(("phoenix", "langfuse")), AgentTokenUsage.bucket >= since)
            .group_by(AgentTokenUsage.model_name)
        )).all()
        aliases = await load_aliases(db)
    return [(name, int(calls or 0)) for name, calls in rows], aliases


async def _observed(agent: Agent) -> tuple[list[dict], int, bool]:
    """(dependencies seen in traces but not on the record, traces read, whether the traces could be read)."""
    if not (agent.phoenix_project or "").strip():
        return [], 0, True
    from api.routers.ops import diagram
    try:
        deps = await diagram.dependencies(agent.id, refresh=False, _=_USER)
    except Exception:
        log.warning("autofill.dependencies_unavailable", agent_id=agent.id)
        return [], 0, False
    if deps.get("status") != "ok":
        return [], 0, deps.get("status") != "phoenix_unreachable"
    return list(deps["comparison"].get("observed_only") or []), int(deps.get("traceCount") or 0), True


def _host_base(url: str) -> str:
    return (reuse.backend_sibling(url) or reuse.origin(url) or "").lower()


async def _shared_with_another_app(agent: Agent, endpoint: str) -> bool:
    """Does another live agent record the same host without being the same app? Two registrations of
    one app (the same tracing project) may share its description; unrelated agents behind a shared
    gateway may not."""
    base, project = _host_base(endpoint), (agent.phoenix_project or "").strip()
    async with get_db_session() as db:
        others = (await db.execute(select(Agent.api_endpoint, Agent.phoenix_project).where(
            Agent.id != agent.id, Agent.deprecated_at.is_(None), Agent.api_endpoint.isnot(None)))).all()
    for other_endpoint, other_project in others:
        text = (other_endpoint or "").strip()
        if not text.lower().startswith(("http://", "https://")) or _host_base(text) != base:
            continue
        if not project or (other_project or "").strip() != project:
            return True
    return False


async def _app(agent: Agent, record: dict, history: list[rules.Past]) -> tuple[dict | None, bool]:
    """(what the app says about itself, whether it could be read). The app is asked only when a
    field it could fill is empty and not left empty by a person."""
    wanted = [f for f in ("description", "capabilities", "inputs", "outputs", "api_endpoint")
              if rules.blank(record.get(f)) and not rules.owned_by_person(f, record.get(f), history)]
    if not wanted:
        return None, True
    from api.routers.ops import discovery
    endpoint = (agent.api_endpoint or "").strip()
    candidates: list[tuple[str, str]] = []
    if endpoint.lower().startswith(("http://", "https://")):
        if await _shared_with_another_app(agent, endpoint):
            return None, True            # one address, several different agents: what it publishes describes none of them
        candidates.append((endpoint, "endpoint"))
    elif not endpoint and (agent.phoenix_project or "").strip():
        async with get_db_session() as db:
            config = (await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == "org-default"))).scalar_one_or_none()
        template = (config.app_url_template if config else None) or ""
        # Only the address built from the exact project name. The looser guesses (a word dropped from
        # the name) can belong to another app, and its description must not land on this record.
        candidates += [(url, "pattern") for url in discovery.address_candidates(template, agent.phoenix_project.strip())[:1]]
    for url, via in candidates:
        try:
            read = await discovery._read_app(url)
        except (reuse.TryItBlocked, OSError, ValueError):
            continue
        if not (read["openapi"]["found"] or read["card"]["found"]):
            continue
        fields = read.get("fields") or {}
        return {"via": via, "url": read["base"], "description": fields.get("description"),
                "capabilities": fields.get("capabilities"), "inputs": fields.get("inputs"), "outputs": fields.get("outputs")}, True
    # An address guessed from the pattern that nothing answers at is not a failed read: there may be no such app.
    return None, not any(via == "endpoint" for _, via in candidates)


async def _draft(agent: Agent) -> dict | None:
    """A description and capabilities drafted by the record-draft agent from the traces. Each has to
    cite the steps it rests on (the runtime drops a finding that cites nothing), and a description
    containing a figure the tools did not return is refused."""
    from agents.insights.runtime import run_insight
    from agents.insights.specs import SPECS
    result = await run_insight(SPECS["record_draft"], agent_id=agent.id,
                               request=f"The agent is registered as '{agent.name}' (id {agent.id}).",
                               interactive=False, actor="ai:record-keeper")
    if result["status"] != "ok" or not result["output"]:
        return None
    findings = result["output"]["findings"]
    # A draft describes what the steps do. Any quantity in it ("9 million customers", "9k") was not in the traces.
    def sober(text: str) -> bool:
        return not _QUANTITY.search(text)
    described = next((f for f in findings if f["tag"] == "description" and not f["unverifiedFigures"] and sober(f["detail"])), None)
    return {"description": described["detail"] if described else None,
            "capabilities": [f["title"] for f in findings if f["tag"] == "capability" and sober(f["title"])]}


async def _hints(agent: Agent) -> dict:
    """Values of the trace-attribute convention (agent.owner, agent.department, agent.version)
    found on this agent's project by the last discovery scan."""
    if not agent.phoenix_project:
        return {}
    from db.models import PhoenixProject

    async with get_db_session() as db:
        row = (await db.execute(select(PhoenixProject).where(PhoenixProject.name == agent.phoenix_project))).scalars().first()
    return dict(row.hints or {}) if row else {}


async def gather_evidence(agent: Agent, history: list[rules.Past], *, use_model: bool) -> dict:
    record = _record(agent)
    usage_models, aliases = await _usage_models(agent.id)
    observed_only, traces, traces_read = await _observed(agent)
    app, app_read = await _app(agent, record, history)
    evidence: dict[str, Any] = {"usage_models": usage_models, "usage_days": USAGE_DAYS, "aliases": aliases,
                                "observed_only": observed_only, "traces": traces, "app": app, "draft": None,
                                "hints": await _hints(agent),
                                "unread": [label for label, ok in ((TRACES, traces_read), (APP, app_read)) if not ok]}
    settings = get_settings()
    if (use_model and traces and settings.azure_openai_endpoint and settings.azure_openai_api_key
            and rules.needs_draft(record, evidence, history)):
        try:
            evidence["draft"] = await _draft(agent)
        except Exception:                       # a model that cannot be reached must not stop the factual updates
            log.warning("autofill.draft_unavailable", agent_id=agent.id)
    return evidence


def update_to_dict(row: AgentFieldUpdate, current: Any) -> dict:
    old, new = _unwrap(row.old_value), _unwrap(row.new_value)
    is_list = row.field in rules.LIST_FIELDS
    before = {rules._norm(x) for x in (old or [])} if is_list else set()
    possible, _, why_not = (False, None, "Already undone.") if row.reverted_at else rules.undo_value(row.field, current, old, new)
    return {
        "id": row.id, "field": row.field, "label": rules.FIELD_LABELS.get(row.field, row.field), "isList": is_list,
        "from": rules.display(row.field, old), "to": rules.display(row.field, new),
        "added": [x for x in (new or []) if rules._norm(x) not in before] if is_list else [],
        "source": row.source, "sourceLabel": rules.SOURCE_LABELS.get(row.source, row.source), "reason": row.reason,
        "appliedAt": row.applied_at.replace(tzinfo=row.applied_at.tzinfo or timezone.utc).isoformat() if row.applied_at else None,
        "undone": row.reverted_at is not None, "canUndo": possible, "undoBlockedReason": why_not,
    }


async def active_updates(agent_id: str) -> list[dict]:
    """Automatic updates that still stand (not undone), newest first."""
    agent, rows = await _load(agent_id)
    if agent is None:
        return []
    out = []
    for r in rows:
        if r.reverted_at is not None:
            continue
        item = update_to_dict(r, getattr(agent, r.field, None))
        if item["canUndo"]:                                   # a value a person has since replaced is theirs, not "filled in"
            out.append(item)
    return out


async def auto_filled_fields(db, agent: Agent) -> dict[str, str]:
    """{field: where it came from} for fields whose present value was put there by the registry and
    not confirmed or changed by a person. Reviewers are shown this next to the checks it affects."""
    rows = list((await db.execute(
        select(AgentFieldUpdate).where(AgentFieldUpdate.agent_id == agent.id, AgentFieldUpdate.reverted_at.is_(None))
        .order_by(AgentFieldUpdate.applied_at.desc())
    )).scalars())
    out: dict[str, str] = {}
    for row in rows:
        if row.field in out:
            continue
        current, new = getattr(agent, row.field, None), _unwrap(row.new_value)
        if row.field in rules.LIST_FIELDS:
            old = {rules._norm(x) for x in (_unwrap(row.old_value) or [])}
            added = {rules._norm(x) for x in (new or [])} - old
            still = added & {rules._norm(x) for x in (current or [])}
            if still:
                out[row.field] = rules.SOURCE_LABELS.get(row.source, row.source)
        elif rules.same(current, new):
            out[row.field] = rules.SOURCE_LABELS.get(row.source, row.source)
    return out


async def _recalculate(agent_id: str, trigger: str) -> None:
    """Cost, risks and governance are worked out from the record, so they are redone after it changes."""
    from orchestrations import job_runner
    for job in RECALCULATE:
        try:
            await job_runner.run_job(job, agent_id=agent_id, trigger=trigger)
        except Exception:
            log.warning("autofill.recalculate_failed", agent_id=agent_id, job=job)


async def maintain_agent(agent_id: str, *, trigger: str = "manual", use_model: bool = True, recalculate: bool = True) -> dict:
    """Fills in and corrects what the evidence supports for one agent. Returns
    {status, agentId, name, applied: [...], evidence: {...}}. Never raises for missing evidence."""
    agent, rows = await _load(agent_id)
    if agent is None:
        return {"status": "error", "agentId": agent_id, "reason": "Agent not found", "applied": []}
    if agent.deprecated_at is not None or agent.lifecycle_stage == "Deprecated":
        return {"status": "ok", "agentId": agent_id, "name": agent.name, "applied": [], "evidence": None}
    history = _history(rows)
    evidence = await gather_evidence(agent, history, use_model=use_model)
    planned = rules.plan_updates(_record(agent), evidence, history)

    applied: list[dict] = []
    if planned:
        async with get_db_session() as db:
            fresh = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
            for u in planned:
                current = getattr(fresh, u["field"])
                if not rules.same(current, u["old"]):
                    continue                                  # someone changed it while the evidence was being read
                setattr(fresh, u["field"], list(u["new"]) if isinstance(u["new"], list) else u["new"])
                row = AgentFieldUpdate(
                    id=secrets.token_hex(10), org_id="org-default", agent_id=agent_id, field=u["field"],
                    old_value=_wrap(u["old"]), new_value=_wrap(u["new"]), source=u["source"], reason=u["reason"],
                    applied_by=ACTOR, applied_at=datetime.now(timezone.utc),
                )
                db.add(row)
                # Shaped like a person's edit, so the recertification rules see a change to a material field.
                db.add(AuditLog(org_id="org-default", actor=ACTOR, action="ai.autofill", entity_type="agent", entity_id=agent_id,
                                changes={"after": {u["field"]: u["new"]}, "before": {u["field"]: u["old"]},
                                         "source": u["source"], "reason": u["reason"], "updateId": row.id}))
                applied.append(update_to_dict(row, u["new"]))
        if applied:
            from discovery.graph_cache import graph_cache
            graph_cache.invalidate(agent_id)
            if recalculate:
                await _recalculate(agent_id, trigger)
            log.info("autofill.applied", agent_id=agent_id, fields=[a["field"] for a in applied])

    used = [(m, c) for m, c in evidence["usage_models"] if c]
    read = {"realCalls": sum(c for _, c in used), "tracesRead": evidence["traces"], "appRead": evidence["app"] is not None,
            "draftUsed": bool(evidence["draft"]), "unread": list(evidence.get("unread") or [])}
    async with get_db_session() as db:
        latest = await db.get(Agent, agent_id)               # as it is now, after any address this run filled in
        check = await db.get(AgentRecordCheck, agent_id)
        if check is None:
            check = AgentRecordCheck(agent_id=agent_id, org_id="org-default")
            db.add(check)
        check.checked_at, check.link = datetime.now(timezone.utc), link_signature(latest or agent)
        check.complete, check.evidence = not read["unread"], read
    return {"status": "ok", "agentId": agent_id, "name": agent.name, "applied": applied, "evidence": read}


async def person_gaps(agent: Agent) -> list[dict]:
    """What only a person can give and this record still lacks (governance/autofill.missing_from_person)."""
    async with get_db_session() as db:
        budget = await db.get(AgentBudget, agent.id)
        reviews = (await db.execute(select(GovernanceReview.gate, GovernanceReview.status)
                                    .where(GovernanceReview.agent_id == agent.id))).all()
        from db.models import Department
        depts = {d.name.lower(): {"id": d.id, "name": d.name} for d in (await db.execute(select(Department))).scalars()}
    hints = await _hints(agent)
    return rules.missing_from_person({
        "hints": hints, "hint_dept": depts.get(str(hints.get("agent.department") or "").strip().lower()),
        "owner": agent.owner, "dept_id": agent.dept_id, "business_outcome": agent.business_outcome,
        "value_amount": agent.value_amount, "hours_saved_monthly": agent.hours_saved_monthly, "sla": agent.sla,
        "has_budget": bool(budget and (budget.monthly_budget_cents or 0) > 0),
        "reviews": {gate: status for gate, status in reviews},
    })


async def last_check(agent_id: str) -> dict | None:
    """What the latest check of this agent read: {checkedAt, realCalls, tracesRead, appRead, draftUsed, unread}."""
    async with get_db_session() as db:
        check = await db.get(AgentRecordCheck, agent_id)
    if check is None:
        return None
    at = check.checked_at.replace(tzinfo=check.checked_at.tzinfo or timezone.utc)
    return {**(check.evidence or {}), "checkedAt": at.isoformat()}


async def check_state(agent: Agent) -> dict:
    """When this agent's evidence was last read, what was read, and whether it is time to look again."""
    async with get_db_session() as db:
        check = await db.get(AgentRecordCheck, agent.id)
    checked_at = None
    due = has_source(agent)
    if check is not None:
        checked_at = check.checked_at.replace(tzinfo=check.checked_at.tzinfo or timezone.utc)
        age = datetime.now(timezone.utc) - checked_at
        due = due and (check.link != link_signature(agent) or age > (RECHECK_AFTER if check.complete else RETRY_AFTER))
    return {"due": due, "checkedAt": checked_at.isoformat() if checked_at else None,
            "evidence": dict(check.evidence or {}) if check is not None else None}


async def undo_update(agent_id: str, update_id: str, actor: str) -> dict:
    """Puts back what was there before one automatic update, and leaves that field to people from now on.
    Raises LookupError when there is no such update and ValueError when it can no longer be undone."""
    async with get_db_session() as db:
        row = (await db.execute(select(AgentFieldUpdate).where(
            AgentFieldUpdate.id == update_id, AgentFieldUpdate.agent_id == agent_id))).scalar_one_or_none()
        if row is None:
            raise LookupError("No such automatic update")
        if row.reverted_at is not None:
            raise ValueError("This automatic update was already undone.")
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        current = getattr(agent, row.field)
        possible, restored, why_not = rules.undo_value(row.field, current, _unwrap(row.old_value), _unwrap(row.new_value))
        if not possible:
            raise ValueError(why_not or "This can no longer be undone.")
        if row.field == "description" and restored is None:
            restored = ""                                     # the column does not take a null
        setattr(agent, row.field, restored)
        row.reverted_at, row.reverted_by = datetime.now(timezone.utc), actor
        db.add(AuditLog(org_id="org-default", actor=actor, action="ai.autofill.undo", entity_type="agent", entity_id=agent_id,
                        changes={"after": {row.field: restored}, "before": {row.field: current}, "updateId": row.id}))
        label = rules.FIELD_LABELS.get(row.field, row.field)
    from discovery.graph_cache import graph_cache
    graph_cache.invalidate(agent_id)
    await _recalculate(agent_id, "manual")
    return {"status": "undone", "field": label}
