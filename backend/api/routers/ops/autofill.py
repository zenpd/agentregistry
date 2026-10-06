"""Automatic updates to an agent's record: what the registry filled in or
corrected by itself, and undoing one.

The rules (which fields, on what evidence, never over a person's entry) are in
governance/autofill.py. Nothing here lets a caller choose a field or a value:
an undo restores what was there. The check itself runs in the daily job and in
the one-agent refresh (POST /agents/{id}/refresh)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import Agent, JobRun
from governance import autofill as rules
from orchestrations import job_runner
from services import autofill

ASK_AGAIN_AFTER = timedelta(minutes=10)
router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Automatic updates"])


async def _agent_or_404(agent_id: str) -> Agent:
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def state_for(agent: Agent) -> dict:
    """What stands filled in on this record, when its evidence was last read, and whether it is
    time to read it again (`due`) or that is happening now (`running`)."""
    check = await autofill.check_state(agent)
    async with get_db_session() as db:
        running = (await job_runner.is_running(db, job_runner.REFRESH_LOCK, agent.id)
                   or await job_runner.is_running(db, "record_autofill", agent.id))
        recent = (await db.execute(select(JobRun.id).where(
            JobRun.job.in_((job_runner.REFRESH_LOCK, "record_autofill")), JobRun.agent_id == agent.id,
            JobRun.started_at >= datetime.now(timezone.utc) - ASK_AGAIN_AFTER).limit(1))).first() is not None
    return {
        "agentId": agent.id, "updates": await autofill.active_updates(agent.id),
        # Not due again straight after an attempt, whatever its outcome and whoever's browser asked.
        "due": check["due"] and not running and not recent, "running": running,
        "checkedAt": check["checkedAt"], "evidence": check["evidence"],
        "fills": list(rules.FIELD_LABELS.values()), "onlyAPerson": list(rules.ONLY_A_PERSON),
        # What only a person can give and this record still lacks.
        "needsPerson": await autofill.person_gaps(agent),
    }


@router.get("/agents/{agent_id}/auto-updates")
async def list_auto_updates(agent_id: str, _=Depends(require_read)):
    """What the registry has filled in or corrected on this agent's record and that still stands."""
    return await state_for(await _agent_or_404(agent_id))


@router.post("/agents/{agent_id}/auto-updates/{update_id}/undo")
async def undo_auto_update(agent_id: str, update_id: str, user=Depends(require_update)):
    """Puts back what was there before. The registry then leaves that field to people."""
    await _agent_or_404(agent_id)
    try:
        result = await autofill.undo_update(agent_id, update_id, user.get("user_id", "unknown"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {**result, **(await state_for(await _agent_or_404(agent_id)))}
