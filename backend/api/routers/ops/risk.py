"""Agent page — Risk tab API: the per-agent risk register, the lifecycle
actions a person takes on it, and the portfolio risk summary.

FINANCIAL findings are never stored in agent_risks; they are read live and
returned beside the register."""
from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentRisk, AuditLog, JobRun, User
from governance import risk_lifecycle as lifecycle
from orchestrations import job_runner
from orchestrations.risk_scan import (
    TRACE_WINDOW_DAYS, as_utc, live_financial, portfolio_financial, risk_row_dict, utcnow,
)

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Risk"])

ORG_ID = "org-default"
SCAN_JOB = "risk_scan"


class RiskActionIn(BaseModel):
    action: Literal["acknowledge", "mitigate", "resolve", "accept", "reopen", "update"]
    owner: Optional[str] = None
    mitigation: Optional[str] = None
    dueDate: Optional[str] = None
    acceptedUntil: Optional[str] = None
    note: Optional[str] = None


class RiskCreateIn(BaseModel):
    category: str
    severity: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    dueDate: Optional[str] = None
    note: Optional[str] = None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _jsonable(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: _iso(v) if isinstance(v, (date, datetime)) else v for k, v in fields.items() if k != "history"}


_SORT_STATUS = {status: i for i, status in enumerate(lifecycle.ALL_STATUSES)}
_SORT_SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _sort_key(row: dict[str, Any]) -> tuple:
    detected = as_utc(row.get("detected_at"))
    return (
        _SORT_STATUS.get(row.get("status"), len(_SORT_STATUS)),
        _SORT_SEVERITY.get(row.get("severity"), 4),
        -(detected.timestamp() if detected else 0),
    )


def _finding_out(row: dict[str, Any], today: date) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ruleId": row.get("rule_id"),
        "category": row["category"],
        "severity": row["severity"],
        "title": row["title"],
        "description": row.get("description"),
        "source": row.get("source"),
        "status": row.get("status"),
        "owner": row.get("owner"),
        "mitigation": row.get("mitigation"),
        "dueDate": _iso(row.get("due_date")),
        "acceptedUntil": _iso(row.get("accepted_until")),
        "acceptedBy": row.get("accepted_by"),
        "detectedAt": _iso(row.get("detected_at")),
        "lastDetectedAt": _iso(row.get("last_detected_at")),
        "resolvedAt": _iso(row.get("resolved_at")),
        "history": row.get("history") or [],
        "overdue": lifecycle.is_overdue(row, today),
    }


def _financial_out(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": finding["rule_id"],
        "category": finding["category"],
        "severity": finding["severity"],
        "title": finding["title"],
        "description": finding.get("description"),
        "source": "auto",
        "origin": finding.get("origin"),
        "dataSource": finding.get("data_source"),
        "sourceId": finding.get("source_id"),
    }


def _scan_finding_out(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": finding.get("rule_id"),
        "category": finding.get("category"),
        "severity": finding.get("severity"),
        "title": finding.get("title"),
        "description": finding.get("description"),
        "source": "auto",
    }


async def _agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
    )).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _actor_label(db: AsyncSession, user: dict) -> str:
    """Readable name for history entries and accepted_by."""
    row = await db.get(User, user["user_id"])
    return (row.email or row.name) if row else user["user_id"]


def _apply(row: AgentRisk, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        setattr(row, field, value)


def _audit(db: AsyncSession, actor: str, action: str, risk_id: str, changes: dict[str, Any]) -> None:
    db.add(AuditLog(org_id=ORG_ID, actor=actor, action=action, entity_type="agent_risk",
                    entity_id=risk_id, changes=changes))


def _expire_acceptances(db: AsyncSession, rows: dict[str, AgentRisk], now: datetime) -> None:
    """An acceptance past its date reopens the finding on the next read."""
    for update in lifecycle.expire_acceptances([risk_row_dict(r) for r in rows.values()], now):
        row = rows[update["id"]]
        _audit(db, "system", "risk.acceptance_expired", row.id, {
            "agentId": row.agent_id, "ruleId": row.rule_id, "from": {"status": row.status},
            "to": _jsonable(update["changes"]),
        })
        _apply(row, update["changes"])


async def _last_scan(db: AsyncSession, agent_id: str) -> dict[str, Any] | None:
    run = (await db.execute(
        select(JobRun)
        .where(JobRun.job == SCAN_JOB, or_(JobRun.agent_id == agent_id, JobRun.agent_id.is_(None)))
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if run is None:
        return None
    summary = run.summary or {}
    if run.agent_id is None:
        summary = (summary.get("agents") or {}).get(agent_id) or {}
    return {
        "runId": run.id,
        "status": run.status,
        "trigger": run.trigger,
        "scope": "agent" if run.agent_id else "all",
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
        "error": run.error,
        "traceSignals": summary.get("traceSignals"),
        "traceReason": summary.get("traceReason"),
        "traceWindowDays": summary.get("traceWindowDays") or TRACE_WINDOW_DAYS,
        "sampleCapped": summary.get("sampleCapped"),
        "kri": summary.get("kri"),
        "blastRadius": summary.get("blastRadius"),
        "reconcile": summary.get("reconcile"),
    }


@router.post("/agents/{agent_id}/risks/scan")
async def scan_agent_risks(agent_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
    run = await job_runner.run_job(SCAN_JOB, agent_id=agent_id, trigger="manual", actor=user["user_id"])
    if run.get("locked"):
        raise HTTPException(status_code=409, detail=run.get("reason") or "A risk scan is already running")
    summary = run.get("summary") or {}
    if run["status"] not in ("ok", "partial"):
        raise HTTPException(status_code=500, detail=run.get("error") or summary.get("reason") or "Risk scan failed")
    return {
        "status": "scanned",
        "runId": run.get("runId"),
        "scannedAt": summary.get("scannedAt"),
        "findingCount": summary.get("findingCount", 0),
        "findings": [_scan_finding_out(f) for f in summary.get("findings") or []],
        "financial": [_financial_out(f) for f in summary.get("financial") or []],
        "reconcile": summary.get("reconcile"),
        "uncheckedRules": summary.get("uncheckedRules") or [],
        "traceSignals": summary.get("traceSignals"),
        "traceReason": summary.get("traceReason"),
        "kri": summary.get("kri"),
        "blastRadius": summary.get("blastRadius"),
    }


@router.get("/agents/{agent_id}/risks")
async def agent_risks(
    agent_id: str,
    status: Literal["active", "all"] = Query("active", description="active = open, acknowledged, mitigating, accepted"),
    _=Depends(require_read),
):
    from api.routers.registry import _agent_to_dict

    now = utcnow()
    today = now.date()
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        rows = {r.id: r for r in (await db.execute(
            select(AgentRisk).where(AgentRisk.agent_id == agent_id)
        )).scalars().all()}
        _expire_acceptances(db, rows, now)
        stored = [risk_row_dict(r) for r in rows.values()]
        financial = await live_financial(db, agent, _agent_to_dict(agent))
        last_scan = await _last_scan(db, agent_id)

    active = [r for r in stored if r["status"] in lifecycle.ACTIVE_STATUSES]
    listed = stored if status == "all" else active
    return {
        "agentId": agent_id,
        "statusFilter": status,
        "findings": [_finding_out(r, today) for r in sorted(listed, key=_sort_key)],
        "financial": [_financial_out(f) for f in financial],
        "score": {
            **lifecycle.score(active + financial),
            "overdue": sum(1 for r in active if lifecycle.is_overdue(r, today)),
            "resolved": sum(1 for r in stored if r["status"] == "resolved"),
        },
        "lastScan": last_scan,
        "phoenixLinked": bool(agent.phoenix_project),
        "phoenixProject": agent.phoenix_project,
        "today": today.isoformat(),
        "maxAcceptanceDays": lifecycle.MAX_ACCEPTANCE_DAYS,
    }


@router.patch("/agents/{agent_id}/risks/{risk_id}")
async def update_agent_risk(agent_id: str, risk_id: str, body: RiskActionIn, user=Depends(require_update)):
    now = utcnow()
    payload = body.model_dump(exclude_unset=True)
    async with get_db_session() as db:
        row = await db.get(AgentRisk, risk_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Risk finding not found")
        _expire_acceptances(db, {row.id: row}, now)
        before = risk_row_dict(row)
        actor = await _actor_label(db, user)
        try:
            result = lifecycle.apply_action(before, payload, actor, now)
        except lifecycle.RiskValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _apply(row, result["changes"])
        changed = _jsonable(result["changes"])
        _audit(db, user["user_id"], f"risk.{body.action}", row.id, {
            "agentId": agent_id, "ruleId": row.rule_id,
            "from": _jsonable({k: before.get(k) for k in changed}),
            "to": changed, "note": payload.get("note"),
        })
        out = _finding_out(risk_row_dict(row), now.date())
    return out


@router.post("/agents/{agent_id}/risks", status_code=201)
async def create_agent_risk(agent_id: str, body: RiskCreateIn, user=Depends(require_update)):
    now = utcnow()
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        actor = await _actor_label(db, user)
        try:
            item = lifecycle.new_manual_risk(body.model_dump(), actor, now)
        except lifecycle.RiskValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        row = AgentRisk(id=secrets.token_hex(8), agent_id=agent_id, **item)
        db.add(row)
        _audit(db, user["user_id"], "risk.create", row.id, {"agentId": agent_id, **_jsonable(item)})
        out = _finding_out(item | {"id": row.id}, now.date())
    return out


@router.get("/governance/risks/summary")
async def risks_summary(_=Depends(require_read)):
    """Portfolio counts over active findings (open, acknowledged, mitigating,
    accepted) plus live FINANCIAL ones: byCategory for the pie,
    heatmap for the category x severity grid."""
    async with get_db_session() as db:
        # Both halves of this summary skip findings whose agent no longer
        # exists, for the same reason portfolio_financial does: no Risk tab
        # can show them, so counting them here would make the portfolio
        # disagree with the sum of its parts.
        live_agents = select(Agent.id).scalar_subquery()
        stored = (await db.execute(
            select(AgentRisk.category, AgentRisk.severity).where(
                AgentRisk.status.in_(lifecycle.ACTIVE_STATUSES), AgentRisk.agent_id.in_(live_agents),
            )
        )).all()
        financial = await portfolio_financial(db)
    return lifecycle.portfolio_summary(
        [{"category": c, "severity": s} for c, s in stored] + financial
    )
