"""Reuse: who really uses an agent (approved, seen in traces or both), reuse figures,
programme health, searches that found nothing, starting a registration from a
certified agent, and the split of a shared agent's cost across the teams that call it."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import (Agent, AgentAccessRequest, AuditLog, Department, ExternalFinding, GovernanceReview, ObservedConsumer,
                       PhoenixProject, SearchLog, User)
from governance import reuse_metrics as rm
from orchestrations.risk_scan import as_utc
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Reuse"])

ATTRIBUTE = "consumer.team"


def _iso(v) -> str | None:
    return as_utc(v).isoformat() if v else None


async def _observed(db, agent_id: str | None = None) -> list[ObservedConsumer]:
    q = select(ObservedConsumer)
    if agent_id:
        q = q.where(ObservedConsumer.agent_id == agent_id)
    return list((await db.execute(q)).scalars())


async def _grants(db, agent_id: str | None = None) -> list[AgentAccessRequest]:
    q = select(AgentAccessRequest).where(AgentAccessRequest.status == "approved")
    if agent_id:
        q = q.where(AgentAccessRequest.agent_id == agent_id)
    return list((await db.execute(q)).scalars())


@router.get("/agents/{agent_id}/consumers")
async def consumers(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        grants = await _grants(db, agent_id)
        observed = await _observed(db, agent_id)
        started = await db.get(Agent, agent.started_from_agent_id) if agent.started_from_agent_id else None
    view = rm.consumer_view(
        [{"team": g.team, "approvedAt": _iso(g.decided_at)} for g in grants], agent.consumers or [],
        [{"caller": o.caller, "kind": o.kind, "calls": o.calls, "firstSeen": _iso(o.first_seen), "lastSeen": _iso(o.last_seen),
          "callerAgentId": o.caller_agent_id} for o in observed])
    first = {rm._key(o.caller): o.first_seen for o in observed if o.kind == "team"}
    days = [d for g in grants if (d := rm.days_to_first_call(g.decided_at, first.get(rm._key(g.team)))) is not None]
    updated = max((o.updated_at for o in observed if o.updated_at), default=None)
    return {**view, "attribute": ATTRIBUTE, "linked": bool(agent.phoenix_project), "observedAt": _iso(updated),
            "buildsAvoided": len(grants), "medianDaysToFirstCall": sorted(days)[len(days) // 2] if days else None,
            "startedFrom": {"id": started.id, "name": started.name} if started else None}


@router.post("/agents/{agent_id}/consumers/observe")
async def observe_now(agent_id: str, _=Depends(require_update)):
    from orchestrations.job_runner import run_job
    return await run_job("consumer_observation", agent_id=agent_id, trigger="manual")


async def _figures(db) -> dict:
    agents = (await db.execute(select(Agent))).scalars().all()
    units = dict((await db.execute(select(Department.id, Department.name))).all())
    grants = await _grants(db)
    observed = await _observed(db)
    return rm.reuse_figures(
        [{"id": a.id, "name": a.name, "unit": units.get(a.dept_id, a.dept_id), "stage": a.lifecycle_stage} for a in agents],
        [{"agentId": g.agent_id, "team": g.team, "approvedAt": g.decided_at} for g in grants],
        [{"agentId": o.agent_id, "caller": o.caller, "kind": o.kind, "firstSeen": o.first_seen} for o in observed])


@router.get("/portfolio/reuse")
async def reuse(_=Depends(require_read)):
    async with get_db_session() as db:
        return await _figures(db)


async def search_gaps(db, days: int = 90) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(select(SearchLog).where(SearchLog.at >= since, SearchLog.results == 0))).scalars().all()
    terms: dict[str, dict] = {}
    for r in rows:
        k = rm._key(r.query)
        t = terms.setdefault(k, {"term": r.query.strip(), "times": 0, "people": set(), "lastAt": None})
        t["times"] += 1
        t["people"].add(r.user_id)
        t["lastAt"] = max(filter(None, (t["lastAt"], as_utc(r.at))))
    out = [{"term": t["term"], "times": t["times"], "people": len(t["people"]), "lastAt": t["lastAt"].isoformat()} for t in terms.values()]
    return sorted(out, key=lambda x: (-x["people"], -x["times"], x["term"]))


@router.get("/portfolio/search-gaps")
async def get_search_gaps(days: int = Query(90, ge=1, le=365), _=Depends(require_read)):
    async with get_db_session() as db:
        return {"days": days, "gaps": await search_gaps(db, days)}


async def log_search(user_id: str | None, query: str, results: int) -> None:
    """Called by the agent search: keeps searches that found nothing. Typing on (the same
    person within a minute, one text extending the other) updates the earlier row."""
    import secrets

    query = " ".join(query.split())[:255]
    if len(query) < 3:
        return
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        prev = (await db.execute(select(SearchLog).where(SearchLog.user_id == user_id).order_by(SearchLog.at.desc()).limit(1))).scalar_one_or_none()
        since = (now - as_utc(prev.at)).total_seconds() if prev else None
        if prev and rm.coalesce_search({"query": prev.query}, query, since):
            if results == 0:
                prev.query, prev.results, prev.at = query, 0, now
            else:
                await db.delete(prev)          # the person found it after all
            return
        if results == 0:
            db.add(SearchLog(id=secrets.token_hex(8), user_id=user_id, query=query, results=0, at=now))


async def _approval_pairs(db, since: datetime) -> list[dict]:
    rows = (await db.execute(select(AuditLog.entity_id, AuditLog.created_at, AuditLog.changes)
                             .where(AuditLog.action == "gate_update").order_by(AuditLog.id))).all()
    submitted: dict[tuple, datetime] = {}
    pairs = []
    for agent_id, at, ch in rows:
        ch = ch or {}
        gate, after = ch.get("gate"), (ch.get("after") or {}).get("status")
        if after == "In Review":
            submitted[(agent_id, gate)] = at
        elif after in ("Approved", "Approved with Conditions", "Changes Requested") and (agent_id, gate) in submitted:
            if as_utc(at) >= since:
                pairs.append({"submittedAt": as_utc(submitted.pop((agent_id, gate))), "decidedAt": as_utc(at),
                              "agentId": agent_id, "gate": gate, "decision": after})
    return pairs


@router.get("/portfolio/health")
async def programme_health(_=Depends(require_read)):
    now = datetime.now(timezone.utc)
    sla = get_settings().review_sla_days
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).where(Agent.lifecycle_stage != "Deprecated"))).scalars().all()
        users = {u.id: u for u in (await db.execute(select(User))).scalars()}
        linked = {a.phoenix_project for a in (await db.execute(select(Agent))).scalars() if a.phoenix_project}
        projects = (await db.execute(select(PhoenixProject).where(PhoenixProject.state == "new"))).scalars().all()
        findings = (await db.execute(select(func.count()).select_from(ExternalFinding).where(ExternalFinding.state == "new"))).scalar() or 0
        waiting = (await db.execute(select(GovernanceReview, Agent).join(Agent, Agent.id == GovernanceReview.agent_id)
                                    .where(GovernanceReview.status == "In Review", Agent.lifecycle_stage != "Deprecated"))).all()
        pairs = await _approval_pairs(db, now - timedelta(days=90))
        figures = await _figures(db)
        gaps = await search_gaps(db)
    from services.ai_meter import get_setting
    build_cost = await get_setting("value.build_cost_cents")
    unregistered = len([p for p in projects if p.name not in linked]) + findings
    with_person = [a for a in agents if a.owner_user_id and users.get(a.owner_user_id) and users[a.owner_user_id].is_active]
    named_only = [a for a in agents if a not in with_person and (a.owner or "").strip() and a.owner.strip().lower() != "unassigned"]
    overdue = [{"agentId": a.id, "agentName": a.name, "gate": g.gate,
                "days": (now.date() - as_utc(g.updated_at).date()).days} for g, a in waiting
               if g.updated_at and (now.date() - as_utc(g.updated_at).date()).days > sla]
    speed = rm.approval_speed(pairs)
    names = {a.id: a.name for a in agents}
    gate_names = {"arb": "Architecture Review Board", "security": "Security Review", "dp": "Data Protection Review"}
    line = lambda a: {"agentId": a.id, "name": a.name, "owner": (a.owner or "").strip() or None}  # noqa: E731
    return {
        # The rows each score is counted from.
        "behind": {
            "notRegistered": {"phoenixProjects": sorted(p.name for p in projects if p.name not in linked)[:100], "connectorFindings": findings},
            "ownerPerson": [{**line(a), "owner": users[a.owner_user_id].name, "backup": bool(a.backup_owner_user_id)} for a in with_person],
            "ownerNameOnly": [line(a) for a in named_only],
            "ownerNone": [line(a) for a in agents if a not in with_person and a not in named_only],
            "decisions": sorted(({"agentId": p["agentId"], "name": names.get(p["agentId"], "An agent that has since been deleted or retired"), "review": gate_names.get(p["gate"], p["gate"]),
                                  "decision": p["decision"], "submitted": p["submittedAt"].date().isoformat(), "decided": p["decidedAt"].date().isoformat(),
                                  "days": (p["decidedAt"].date() - p["submittedAt"].date()).days} for p in pairs), key=lambda x: -x["days"]),
            "productionAgents": [{"agentId": x["agentId"], "name": x["name"], "teams": x["buildsAvoided"]}
                                 for x in figures["agents"] if x.get("stage") == "Production"],
        },
        "known": {"registered": len(agents), "foundNotRegistered": unregistered,
                  "share": round(100 * len(agents) / (len(agents) + unregistered)) if agents or unregistered else None,
                  "text": "Registered agents, against Phoenix projects and connector findings that are not registered yet."},
        "owners": {"total": len(agents), "person": len(with_person), "nameOnly": len(named_only),
                   "none": len(agents) - len(with_person) - len(named_only),
                   "withBackup": len([a for a in with_person if a.backup_owner_user_id]),
                   "share": round(100 * len(with_person) / len(agents)) if agents else None},
        "approvalSpeed": {**speed, "days": 90, "text": "Median days from submitting a review to its decision, over the last 90 days."},
        "overdueReviews": {"count": len(overdue), "slaDays": sla, "items": sorted(overdue, key=lambda x: -x["days"])},
        "reuse": figures["total"], "reuseByUnit": figures["byUnit"],
        "reuseSavings": {"buildCostCents": build_cost, "cents": figures["total"]["buildsAvoided"] * build_cost if build_cost else None,
                         "text": "Builds avoided times the agreed cost of building an agent (Settings)."},
        "searchGaps": gaps[:20],
    }


# ── Start from a certified agent ─────────────────────────────────────────────

TEMPLATE_FIELDS = ("ai_type", "capabilities", "inputs", "outputs", "sla", "rate_limit", "tags", "model_name", "mcp_servers",
                   "knowledge_bases", "databases", "enterprise_systems")


@router.get("/agents/{agent_id}/template")
async def template(agent_id: str, _=Depends(require_read)):
    """The contract of a certified agent, as a starting point for a new registration.
    Names, owner, endpoint, tracing and reviews are never copied."""
    from services import reuse_repo

    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews)))).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        cert = (await reuse_repo.certifications(db, [agent]))[agent.id]
    if not cert.get("certified"):
        raise HTTPException(status_code=409, detail=f"{agent.name} is not certified for reuse, so it cannot be a starting point.")
    return {"agentId": agent.id, "name": agent.name, "fields": {k: getattr(agent, k) for k in TEMPLATE_FIELDS if getattr(agent, k, None)}}


# ── Chargeback ───────────────────────────────────────────────────────────────

def _month(month: str | None) -> tuple[date, date, str]:
    today = datetime.now(timezone.utc).date()
    try:
        start = datetime.strptime(month, "%Y-%m").date() if month else today.replace(day=1)
    except ValueError:
        raise HTTPException(status_code=422, detail="month must look like 2026-10")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end, start.strftime("%Y-%m")


async def _agent_chargeback(db, agent: Agent, start: date, end: date, units: dict) -> dict:
    from services.usage_repo import priced_usage

    usage = await priced_usage(db, agent.id, since=start)
    cents = sum(r["cost_cents"] for r in usage["rows"] if start <= r["day"] <= end and r.get("priced"))
    grants = await _grants(db, agent.id)
    observed = [o for o in await _observed(db, agent.id) if o.kind == "team"]
    owner_unit = units.get(agent.dept_id, agent.dept_id) or "Owner's unit"
    split = rm.chargeback(cents, owner_unit, [g.team for g in grants], {rm._key(o.caller): o.calls or 0 for o in observed})
    return {"agentId": agent.id, "agentName": agent.name, "ownerUnit": owner_unit, "costCents": round(cents),
            "costSource": usage["source"], "unpriced": usage["unpriced"], **split}


@router.get("/agents/{agent_id}/chargeback")
async def agent_chargeback(agent_id: str, month: str | None = None, _=Depends(require_read)):
    start, end, label = _month(month)
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        units = dict((await db.execute(select(Department.id, Department.name))).all())
        return {"month": label, **await _agent_chargeback(db, agent, start, end, units)}


@router.get("/portfolio/chargeback")
async def portfolio_chargeback(month: str | None = None, format: str = "json", _=Depends(require_read)):
    start, end, label = _month(month)
    async with get_db_session() as db:
        units = dict((await db.execute(select(Department.id, Department.name))).all())
        agents = (await db.execute(select(Agent))).scalars().all()
        rows = [r for a in agents if (r := await _agent_chargeback(db, a, start, end, units))["costCents"] > 0]
    payers: dict[str, int] = {}
    for r in rows:
        for s in r["shares"]:
            payers[s["payer"]] = payers.get(s["payer"], 0) + s["cents"]
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["month", "agent", "owner unit", "agent cost (USD)", "payer", "share (%)", "amount (USD)", "basis", "cost source"])
        for r in rows:
            for s in r["shares"]:
                w.writerow([label, r["agentName"], r["ownerUnit"], f"{r['costCents'] / 100:.2f}", s["payer"], s["share"],
                            f"{s['cents'] / 100:.2f}", r["basis"], r["costSource"]])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"content-disposition": f'attachment; filename="chargeback-{label}.csv"'})
    return {"month": label, "agents": rows,
            "payers": sorted(({"payer": p, "cents": c} for p, c in payers.items()), key=lambda x: -x["cents"])}
