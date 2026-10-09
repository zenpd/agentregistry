"""The AssureAI evidence line of an agent: the verdict of an AssureAI evaluation
run (pass or fail), its date and a link. The registry is told the run id, by a
person on the Governance tab or by the CI pipeline that ran AssureAI (with a
registry API key that may register), and reads the verdict with the
application's run key (an AssureAI connector in Settings). No scores are copied.

When the governance rules say so, a missing or failed verdict is a readiness gap
for Production."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import require_read, require_update
from connectors.base import ConnectorError
from db.base import get_db_session
from db.models import Agent, AuditLog, ConnectorConfig, EvidenceVerdict, User
from orchestrations.risk_scan import as_utc

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Evidence"])

RUN_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def _row(v: EvidenceVerdict, names: dict, labels: dict) -> dict:
    return {"id": v.id, "runId": v.run_id, "verdict": v.verdict, "application": v.application,
            "completedAt": as_utc(v.completed_at).isoformat() if v.completed_at else None, "url": v.url, "error": v.error,
            "connector": labels.get(v.connector_id), "recordedBy": names.get(v.recorded_by, v.recorded_by),
            "fetchedAt": as_utc(v.fetched_at).isoformat() if v.fetched_at else None}


async def latest(db, agent_id: str) -> EvidenceVerdict | None:
    """The newest run with a verdict, by run completion (then by when it was read)."""
    rows = (await db.execute(select(EvidenceVerdict).where(EvidenceVerdict.agent_id == agent_id,
                                                           EvidenceVerdict.verdict.is_not(None)))).scalars().all()
    if not rows:
        return None
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return max(rows, key=lambda v: (as_utc(v.completed_at) or floor, as_utc(v.fetched_at) or floor))


async def _connector(db, connector_id: str | None) -> ConnectorConfig:
    q = select(ConnectorConfig).where(ConnectorConfig.kind == "assureai", ConnectorConfig.enabled == True)  # noqa: E712
    configs = (await db.execute(q)).scalars().all()
    if connector_id:
        configs = [c for c in configs if c.id == connector_id]
    if not configs:
        raise HTTPException(status_code=422, detail="No AssureAI connector is set up. A Registry Admin adds one in Settings → Connectors, "
                            "with the application's run key.")
    if len(configs) > 1 and not connector_id:
        raise HTTPException(status_code=422, detail="More than one AssureAI connector exists. Say which one (connectorId).")
    return configs[0]


async def read_verdict(config: ConnectorConfig, run_id: str) -> dict:
    from services.connectors import build
    try:
        return {**await build(config).verdict(run_id), "error": None}
    except ConnectorError as exc:
        return {"verdict": None, "completedAt": None, "application": None, "url": None, "error": exc.message}


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except ValueError:
        return None


@router.get("/agents/{agent_id}/evidence")
async def get_evidence(agent_id: str, _=Depends(require_read)):
    from governance import templates as tpl

    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = (await db.execute(select(EvidenceVerdict).where(EvidenceVerdict.agent_id == agent_id)
                                 .order_by(EvidenceVerdict.fetched_at.desc()))).scalars().all()
        best = await latest(db, agent_id)
        names = dict((await db.execute(select(User.id, User.name))).all())
        connectors = (await db.execute(select(ConnectorConfig).where(ConnectorConfig.kind == "assureai"))).scalars().all()
    labels = {c.id: c.label for c in connectors}
    return {"latest": _row(best, names, labels) if best else None, "runs": [_row(v, names, labels) for v in rows],
            "connectors": [{"id": c.id, "label": c.label, "enabled": c.enabled} for c in connectors],
            "requiredForProduction": await tpl.assureai_required(),
            "phoenixProject": agent.phoenix_project}


class RunBody(BaseModel):
    runId: str
    connectorId: str | None = None


@router.post("/agents/{agent_id}/evidence/assureai")
async def record_run(agent_id: str, body: RunBody, user=Depends(require_update)):
    run_id = body.runId.strip()
    if not RUN_ID.match(run_id):
        raise HTTPException(status_code=422, detail="Enter the AssureAI run id (the id shown on the run, for example 3f2a…-…).")
    async with get_db_session() as db:
        if await db.get(Agent, agent_id) is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        config = await _connector(db, body.connectorId)
    got = await read_verdict(config, run_id)
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        row = (await db.execute(select(EvidenceVerdict).where(EvidenceVerdict.agent_id == agent_id,
                                                              EvidenceVerdict.run_id == run_id))).scalar_one_or_none()
        if row is None:
            row = EvidenceVerdict(id=f"ev-{uuid.uuid4().hex[:12]}", agent_id=agent_id, run_id=run_id)
            db.add(row)
        row.connector_id, row.recorded_by, row.fetched_at = config.id, actor, datetime.now(timezone.utc)
        row.verdict, row.application, row.url, row.error = got["verdict"], got["application"], got["url"], got["error"]
        row.completed_at = _parse(got["completedAt"])
        db.add(AuditLog(org_id="org-default", actor=actor, action="evidence.record", entity_type="agent", entity_id=agent_id,
                        changes={"runId": run_id, "verdict": got["verdict"], "error": got["error"]}))
        await db.flush()
        names = dict((await db.execute(select(User.id, User.name))).all())
        return _row(row, names, {config.id: config.label})


async def refresh_waiting(**_) -> dict:
    """Part of the daily connector job: read again the runs that had no verdict yet."""
    async with get_db_session() as db:
        rows = (await db.execute(select(EvidenceVerdict).where(EvidenceVerdict.verdict.is_(None)))).scalars().all()
        configs = {c.id: c for c in (await db.execute(select(ConnectorConfig).where(ConnectorConfig.kind == "assureai"))).scalars()}
    done = 0
    for r in rows:
        config = configs.get(r.connector_id)
        if config is None:
            continue
        got = await read_verdict(config, r.run_id)
        async with get_db_session() as db:
            row = await db.get(EvidenceVerdict, r.id)
            row.fetched_at = datetime.now(timezone.utc)
            row.verdict, row.application, row.url, row.error = got["verdict"], got["application"], got["url"], got["error"]
            row.completed_at = _parse(got["completedAt"])
        done += 1 if got["verdict"] else 0
    return {"waiting": len(rows), "read": done}
