"""Portfolio-wide signals that need no new data: lifecycle attention (silent,
retired but still called) from the usage the registry already stores."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.auth import require_read
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage
from governance import attention, costing
from orchestrations.risk_scan import as_utc

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Portfolio"])


async def attention_facts(db) -> dict:
    agents = (await db.execute(select(Agent))).scalars().all()
    last = dict((await db.execute(
        select(AgentTokenUsage.agent_id, func.max(AgentTokenUsage.bucket))
        .where(AgentTokenUsage.source.in_(costing.TRACED_SOURCES), AgentTokenUsage.invocation_count > 0)
        .group_by(AgentTokenUsage.agent_id))).all())
    rows = [{"id": a.id, "name": a.name, "stage": a.lifecycle_stage, "linked": bool(a.phoenix_project), "calls": a.calls or [],
             "deprecatedOn": as_utc(a.deprecated_at).date().isoformat() if a.deprecated_at else None} for a in agents]
    since: dict[str, int] = {}
    for a in agents:
        if a.lifecycle_stage == "Deprecated" and a.deprecated_at:
            since[a.id] = int((await db.execute(select(func.coalesce(func.sum(AgentTokenUsage.invocation_count), 0)).where(
                AgentTokenUsage.agent_id == a.id, AgentTokenUsage.source.in_(("phoenix", "langfuse")),
                AgentTokenUsage.bucket > a.deprecated_at))).scalar() or 0)
    return {"rows": rows, "last": {k: as_utc(v).date() if v else None for k, v in last.items()}, "since": since}


async def stalled_agents(db) -> list[dict]:
    from governance import lifecycle
    from governance import templates as tpl
    from orchestrations.governance_checks import stage_since

    limits = await tpl.stall_weeks()
    now = datetime.now(timezone.utc)
    out = []
    for a in (await db.execute(select(Agent).where(Agent.lifecycle_stage.in_(tuple(limits))))).scalars().all():
        weeks = lifecycle.weeks_in_stage(await stage_since(db, a), now)
        if lifecycle.stalled(a.lifecycle_stage, weeks, limits):
            out.append({"agentId": a.id, "name": a.name, "stage": a.lifecycle_stage, "weeks": weeks, "limit": limits[a.lifecycle_stage],
                        "text": f"In {a.lifecycle_stage} for {weeks} weeks (the limit is {limits[a.lifecycle_stage]})."})
    return sorted(out, key=lambda x: -x["weeks"])


@router.get("/portfolio/attention")
async def portfolio_attention(_=Depends(require_read)):
    today = datetime.now(timezone.utc).date()
    async with get_db_session() as db:
        f = await attention_facts(db)
        stalled = await stalled_agents(db)
        from services.ownership import orphans
        ownerless = await orphans(db)
        from db.models import Incident
        stop_waiting = [{"agentId": a.id, "name": a.name, "text": f"Asked to stop on {as_utc(i.stop_requested_at).date().isoformat()}: {i.stop_reason}"}
                        for i, a in (await db.execute(select(Incident, Agent).join(Agent, Agent.id == Incident.agent_id)
                                                      .where(Incident.stop_requested_at.is_not(None), Incident.stop_acknowledged_at.is_(None)))).all()]
    return {
        "stalled": stalled,
        "ownerless": ownerless,
        "stopWaiting": stop_waiting,
        "silent": attention.silent(f["rows"], f["last"], today),
        "runningAfterRetirement": attention.running_after_retirement(f["rows"], f["since"]),
        "callsRetired": attention.calls_retired(f["rows"]),
        "silentDays": attention.SILENT_DAYS,
    }
