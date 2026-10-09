"""Versions of an agent with a changelog, and the version each consumer team uses.

Releasing a version records the changelog and the structural fields at release
(model, tools, endpoint), sets the agent's current version, and tells every team
with approved access. A team uses the version current when its access was
approved, until someone moves it to a later one."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentAccessRequest, AgentVersion, AuditLog, User
from governance import lifecycle
from orchestrations.risk_scan import as_utc
from services import notify

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Versions"])


def record_of(agent: Agent) -> dict:
    return {k: getattr(agent, k, None) for k in lifecycle.STRUCTURAL}


async def released(db, agent_id: str) -> list[AgentVersion]:
    return list((await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent_id)
                                  .order_by(AgentVersion.released_at, AgentVersion.version))).scalars())


@router.get("/agents/{agent_id}/versions")
async def list_versions(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await released(db, agent_id)
        names = dict((await db.execute(select(User.id, User.name))).all())
        grants = (await db.execute(select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id,
                                                                     AgentAccessRequest.status == "approved"))).scalars().all()
    order = [v.version for v in rows]
    versions = []
    for i, v in enumerate(rows):
        changes = lifecycle.changed_since(rows[i - 1].snapshot, (v.snapshot or {}).get("fields", {})) if i else []
        versions.append({"version": v.version, "changelog": v.changelog, "releasedBy": names.get(v.released_by, v.released_by),
                         "releasedAt": as_utc(v.released_at).isoformat() if v.released_at else None,
                         "structuralChanges": lifecycle.describe(changes) if changes else None})
    latest = rows[-1] if rows else None
    consumers = []
    for g in grants:
        used = g.agent_version
        behind = (len(order) - 1 - order.index(used)) if used in order else None
        since = None
        if used in order and latest and used != latest.version:
            snap = next(v for v in rows if v.version == used).snapshot
            changes = lifecycle.changed_since(snap, (latest.snapshot or {}).get("fields", {}))
            since = lifecycle.describe(changes) if changes else "No change to model, tools or endpoint."
        consumers.append({"requestId": g.id, "team": g.team, "contact": g.requester_name, "version": used,
                          "behind": behind, "changedSince": since})
    teams_with_grant = {g.team.lower() for g in grants}
    return {"current": agent.version, "versions": list(reversed(versions)), "consumers": consumers,
            "consumersWithoutGrant": [t for t in (agent.consumers or []) if t.lower() not in teams_with_grant]}


class ReleaseBody(BaseModel):
    version: str
    changelog: str


@router.post("/agents/{agent_id}/versions")
async def release(agent_id: str, body: ReleaseBody, user=Depends(require_update)):
    version, changelog = body.version.strip(), body.changelog.strip()
    if not version or len(version) > 50:
        raise HTTPException(status_code=422, detail="Enter the version, up to 50 characters (for example 2.1.0).")
    if len(changelog) < 10:
        raise HTTPException(status_code=422, detail="Say what changed in this version, in at least 10 characters.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if any(v.version == version for v in await released(db, agent_id)):
            raise HTTPException(status_code=409, detail=f"Version {version} is already released.")
        db.add(AgentVersion(id=f"ver-{uuid.uuid4().hex[:12]}", agent_id=agent_id, version=version, changelog=changelog,
                            snapshot=lifecycle.snapshot(record_of(agent)), released_by=actor, released_at=datetime.now(timezone.utc)))
        before = agent.version
        agent.version = version
        db.add(AuditLog(org_id=agent.org_id or "org-default", actor=actor, action="version.release", entity_type="agent", entity_id=agent_id,
                        changes={"version": version, "previous": before, "changelog": changelog[:300]}))
        grants = (await db.execute(select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id,
                                                                     AgentAccessRequest.status == "approved"))).scalars().all()
        name = agent.name
        told = [(g.requester_id, g.team, g.agent_version) for g in grants]
    for uid, team, used in told:
        await notify.notify(user_id=uid, kind="version", subject=f"Agent Registry: {name} {version} is released",
                            items=[{"type": "version", "link": f"/agents/{agent_id}?tab=integrate",
                                    "text": f"{name} {version}: {changelog} Your team {team} uses version {used or 'not recorded'}."}],
                            dedupe_key=f"version:{agent_id}:{version}:{uid}")
    return {"version": version, "told": len(told)}


class ConsumerVersion(BaseModel):
    version: str


@router.put("/agents/{agent_id}/access/{request_id}/version")
async def set_consumer_version(agent_id: str, request_id: str, body: ConsumerVersion, user=Depends(require_update)):
    async with get_db_session() as db:
        g = await db.get(AgentAccessRequest, request_id)
        if g is None or g.agent_id != agent_id or g.status != "approved":
            raise HTTPException(status_code=404, detail="No approved access for this team")
        if body.version not in [v.version for v in await released(db, agent_id)]:
            raise HTTPException(status_code=422, detail="Choose a released version.")
        before, g.agent_version = g.agent_version, body.version
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="consumer.version", entity_type="agent",
                        entity_id=agent_id, changes={"team": g.team, "from": before, "to": body.version}))
    return {"requestId": request_id, "version": body.version}
