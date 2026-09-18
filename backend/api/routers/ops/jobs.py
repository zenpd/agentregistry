"""Scheduled jobs: status, run history and manual runs."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from api.auth import require_admin, require_read, require_update
from db.base import get_db_session
from db.models import Agent
from orchestrations import job_runner
from orchestrations.scheduler import scheduler_status
from services.audit import log_audit_event

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Jobs"])


def _spec_to_dict(spec: job_runner.JobSpec) -> dict:
    available, unavailable_reason = job_runner.availability(spec)
    return {
        "job": spec.name,
        "label": spec.label,
        "shortLabel": spec.short_label,
        "dailyAt": spec.daily_at.strftime("%H:%M"),
        "schedule": f"Daily {spec.daily_at.strftime('%H:%M')} UTC",
        "adminOnly": spec.admin_only,
        "inRefresh": spec.name in job_runner.REFRESH_JOBS,
        "available": available,
        "unavailableReason": unavailable_reason,
    }


def _spec_or_404(job: str) -> job_runner.JobSpec:
    try:
        return job_runner.get_spec(job)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


async def _require_agent(agent_id: str) -> None:
    async with get_db_session() as db:
        if (await db.execute(select(Agent.id).where(Agent.id == agent_id))).scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Agent not found")


@router.get("/jobs")
async def list_jobs(_=Depends(require_read)):
    scheduler = scheduler_status()
    async with get_db_session() as db:
        latest = await job_runner.latest_runs(db, any_scope=True)
        latest_all = await job_runner.latest_runs(db, None)
    return {
        "scheduler": scheduler,
        "jobs": [
            {
                **_spec_to_dict(spec),
                "enabled": scheduler["enabled"],
                "lastRun": job_runner.run_to_dict(latest[name]),
                "lastAllAgentsRun": job_runner.run_to_dict(latest_all[name]),
            }
            for name, spec in job_runner.JOBS.items()
        ],
    }


@router.get("/jobs/runs")
async def list_job_runs(
    job: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    _=Depends(require_read),
):
    if job:
        _spec_or_404(job)
    async with get_db_session() as db:
        rows = await job_runner.list_runs(db, job=job, agent_id=agent_id or None, limit=limit)
    return {"runs": [job_runner.run_to_dict(r) for r in rows], "count": len(rows)}


@router.post("/jobs/{job}/run")
async def run_job_now(
    job: str,
    agent_id: Optional[str] = None,
    days: Optional[int] = Query(None, ge=1, le=90, description="usage_ingestion only: days to (re)read"),
    user=Depends(require_update),
):
    spec = _spec_or_404(job)
    if spec.admin_only:
        await require_admin(user=user)
    # An empty ?agent_id= means all agents, recorded like any other all-agents run.
    agent_id = agent_id or None
    if agent_id:
        await _require_agent(agent_id)
    kwargs = {"days": days} if job == "usage_ingestion" and days else {}
    result = await job_runner.run_job(job, agent_id=agent_id, trigger="manual", **kwargs)
    await log_audit_event(
        actor=user["user_id"], action="job.run", entity_type="job", entity_id=job,
        changes={"agentId": agent_id, "runId": result["runId"], "status": result["status"], **kwargs},
    )
    return job_runner.for_display(result)


@router.get("/agents/{agent_id}/jobs")
async def agent_jobs(agent_id: str, _=Depends(require_read)):
    await _require_agent(agent_id)
    async with get_db_session() as db:
        mine = await job_runner.latest_runs(db, agent_id)
        everyone = await job_runner.latest_runs(db, None)
    jobs = []
    for name, spec in job_runner.JOBS.items():
        candidates = [r for r in (mine[name], everyone[name]) if r is not None]
        newest = max(candidates, key=lambda r: job_runner.as_utc(r.started_at), default=None)
        jobs.append({
            **_spec_to_dict(spec),
            "agentRun": job_runner.run_to_dict(mine[name]),
            "allAgentsRun": job_runner.run_to_dict(everyone[name]),
            "lastRun": job_runner.run_to_dict(newest),
        })
    return {"agentId": agent_id, "scheduler": scheduler_status(), "jobs": jobs}


@router.post("/agents/{agent_id}/refresh")
async def refresh_agent_data(agent_id: str, user=Depends(require_update)):
    await _require_agent(agent_id)
    result = await job_runner.refresh_agent(agent_id, trigger="manual")
    await log_audit_event(
        actor=user["user_id"], action="agent.refresh", entity_type="agent", entity_id=agent_id,
        changes={
            "status": result["status"],
            "locked": result["locked"],
            "runs": {r["job"]: {"runId": r["runId"], "status": r["status"]} for r in result["results"]},
        },
    )
    return {**result, "results": [job_runner.for_display(r) for r in result["results"]]}
