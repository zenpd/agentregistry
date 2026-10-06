"""Record auto-fill: for every agent the registry can read something about (a
linked tracing project, or a web address), fills in and corrects the fields it
can see for itself: the model in real usage, tools and knowledge sources seen
in traces, the contract from the app's own API, a drafted description where
there is none.

It runs after usage has been read and before cost, risk and governance are
worked out, so those are calculated on the corrected record. When it changes a
record it also redoes those three for that agent straight away: a run that
catches up later in the day comes after them, and must not leave their
figures describing the old record until tomorrow. Every change is written to
the audit log and can be undone on the agent's page. It never sets an owner, a
value, a review decision or a stage."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db.base import get_db_session
from db.models import Agent, AgentRecordCheck
from services import autofill
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("orchestrations.record_autofill")


async def autofill_records(agent_id: str | None = None, trigger: str = "manual", recalculate: bool = True, **_: Any) -> dict:
    """recalculate: redo cost, risk and governance for an agent whose record changed. Off only when
    the caller does that itself straight afterwards (the one-agent refresh)."""
    async with get_db_session() as db:
        if agent_id:
            ids = [agent_id]
        else:
            agents = [a for a in (await db.execute(select(Agent).order_by(Agent.created_at))).scalars() if autofill.has_source(a)]
            checked = dict((await db.execute(select(AgentRecordCheck.agent_id, AgentRecordCheck.checked_at))).all())
            # Never checked first, then the longest unchecked, so a registry larger than the cap is still covered in turn.
            agents.sort(key=lambda a: (a.id in checked, str(checked.get(a.id) or "")))
            ids = [a.id for a in agents][: get_settings().insight_job_max_agents]
    if not ids:
        return {"status": "skipped", "trigger": trigger, "agents": 0, "updated": 0, "fields": 0,
                "reason": "No agent has a tracing project or a web address, so there is nothing to fill records from."}
    items, failed = [], 0
    for one in ids:
        try:
            result = await autofill.maintain_agent(one, trigger=trigger, recalculate=recalculate)
        except Exception:
            log.exception("record_autofill.failed", agent_id=one)
            failed += 1
            continue
        items.append({"agent_id": one, "name": result.get("name"), "updated": [a["label"] for a in result["applied"]],
                      "evidence": result.get("evidence")})
    changed = [i for i in items if i["updated"]]
    return {
        "status": "partial" if failed else "ok", "trigger": trigger, "agents": len(ids), "updated": len(changed),
        "fields": sum(len(i["updated"]) for i in items), "failed": failed, "items": items,
        "reason": f"{failed} agent(s) could not be read." if failed else None,
    }
