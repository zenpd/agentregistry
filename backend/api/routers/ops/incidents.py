"""Incidents and stop requests (item 60).

An incident from PagerDuty, ServiceNow or anywhere else is linked to an agent by
its address or number (the registry does not read those systems: their own
automation can post to /incidents/inbound with a registry API key). Anyone who
may change records can ask the owner to stop the agent; the owner and the backup
owner are told at once and acknowledge with a note. Each agent keeps one history
of its incidents and its changes."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from api.auth import has_permission, require_read, require_update
from db.base import get_db_session
from db.models import Agent, AuditLog, Incident, User
from orchestrations.risk_scan import as_utc
from services import notify

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Incidents"])

SEVERITIES = ("low", "medium", "high", "critical")
MIN_NOTE = 20
# Changes shown next to incidents in an agent's history.
CHANGE_ACTIONS = ("stage_change", "gate_update", "version.release", "update", "ownership.transfer", "classification.confirm",
                  "retirement.start", "retirement.finish", "exception_create", "waiver.sign")


def detect(url: str | None) -> tuple[str, str | None]:
    """(source, external id) from an incident address."""
    u = (url or "").strip()
    if "pagerduty.com" in u:
        m = re.search(r"/incidents/([A-Za-z0-9]+)", u)
        return "pagerduty", m.group(1) if m else None
    if "service-now.com" in u or "servicenow" in u:
        m = re.search(r"(INC\d{5,})", u) or re.search(r"sys_id=([0-9a-f]{32})", u)
        return "servicenow", m.group(1) if m else None
    return ("other" if u else "manual"), None


def _iso(v) -> str | None:
    return as_utc(v).isoformat() if v else None


def _row(i: Incident, names: dict) -> dict:
    return {"id": i.id, "agentId": i.agent_id, "source": i.source, "externalId": i.external_id, "url": i.url, "title": i.title,
            "severity": i.severity, "status": i.status, "openedAt": _iso(i.opened_at), "resolvedAt": _iso(i.resolved_at),
            "resolution": i.resolution, "createdBy": names.get(i.created_by, i.created_by),
            "stop": None if not i.stop_requested_at else {
                "requestedAt": _iso(i.stop_requested_at), "requestedBy": names.get(i.stop_requested_by, i.stop_requested_by),
                "reason": i.stop_reason, "acknowledgedAt": _iso(i.stop_acknowledged_at),
                "acknowledgedBy": names.get(i.stop_acknowledged_by, i.stop_acknowledged_by), "note": i.stop_note}}


def _log(db, actor: str, action: str, agent_id: str, changes: dict) -> None:
    db.add(AuditLog(org_id="org-default", actor=actor, action=action, entity_type="agent", entity_id=agent_id, changes=changes))


async def _agent(db, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/agents/{agent_id}/incidents")
async def list_incidents(agent_id: str, _=Depends(require_read)):
    from governance.audit_view import ACTION_LABELS, actor_label, summary_of

    async with get_db_session() as db:
        await _agent(db, agent_id)
        rows = (await db.execute(select(Incident).where(Incident.agent_id == agent_id).order_by(Incident.opened_at.desc()))).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
        changes = (await db.execute(select(AuditLog).where(AuditLog.entity_type == "agent", AuditLog.entity_id == agent_id,
                                                           AuditLog.action.in_(CHANGE_ACTIONS))
                                    .order_by(AuditLog.id.desc()).limit(100))).scalars().all()
    items = [_row(i, names) for i in rows]
    history = [{"at": i["openedAt"], "kind": "incident", "text": f"Incident opened ({i['severity']}): {i['title']}", "by": i["createdBy"]}
               for i in items]
    history += [{"at": i["resolvedAt"], "kind": "incident", "text": f"Incident resolved: {i['title']}", "by": None} for i in items if i["resolvedAt"]]
    history += [{"at": i["stop"]["requestedAt"], "kind": "stop", "text": f"Owner asked to stop the agent: {i['stop']['reason']}",
                 "by": i["stop"]["requestedBy"]} for i in items if i["stop"]]
    history += [{"at": _iso(c.created_at), "kind": "change", "text": f"{ACTION_LABELS.get(c.action, c.action)}: {summary_of(c.action, c.changes)}",
                 "by": actor_label(c.actor, names)} for c in changes]
    history.sort(key=lambda h: h["at"] or "", reverse=True)
    return {"incidents": items, "open": sum(1 for i in items if i["status"] == "open"), "history": history[:150]}


class IncidentBody(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    url: Optional[str] = Field(None, max_length=500)
    source: Optional[str] = None
    externalId: Optional[str] = Field(None, max_length=120)
    severity: str = "medium"
    openedAt: Optional[datetime] = None


@router.post("/agents/{agent_id}/incidents")
async def link_incident(agent_id: str, body: IncidentBody, user=Depends(require_update)):
    if body.severity not in SEVERITIES:
        raise HTTPException(status_code=422, detail=f"Severity is one of: {', '.join(SEVERITIES)}.")
    source, ext = detect(body.url)
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        i = Incident(id=f"inc-{secrets.token_hex(6)}", agent_id=agent_id, source=body.source or source,
                     external_id=body.externalId or ext, url=(body.url or "").strip() or None, title=body.title.strip(),
                     severity=body.severity, status="open", opened_at=body.openedAt or datetime.now(timezone.utc), created_by=actor)
        db.add(i)
        _log(db, actor, "incident.link", agent_id, {"title": i.title, "severity": i.severity, "source": i.source, "externalId": i.external_id})
        names = dict((await db.execute(select(User.id, User.name))).all())
        owners = [u for u in (agent.owner_user_id, agent.backup_owner_user_id) if u]
        name = agent.name
        row = _row(i, names)
    if body.severity in ("high", "critical"):
        for uid in owners:
            await notify.notify(user_id=uid, kind="incident", subject=f"Agent Registry: {body.severity} incident on {name}",
                                items=[{"type": "incident", "text": f"{name}: {body.title}", "link": f"/agents/{agent_id}?tab=risk"}],
                                dedupe_key=f"incident:{row['id']}:{uid}")
    return row


class ResolveBody(BaseModel):
    resolution: str = Field(..., min_length=5, max_length=2000)


@router.post("/agents/{agent_id}/incidents/{incident_id}/resolve")
async def resolve_incident(agent_id: str, incident_id: str, body: ResolveBody, user=Depends(require_update)):
    async with get_db_session() as db:
        i = await db.get(Incident, incident_id)
        if i is None or i.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Incident not found")
        i.status, i.resolved_at, i.resolution = "resolved", datetime.now(timezone.utc), body.resolution.strip()
        _log(db, user.get("user_id", "unknown"), "incident.resolve", agent_id, {"title": i.title, "resolution": i.resolution})
        names = dict((await db.execute(select(User.id, User.name))).all())
        return _row(i, names)


class NoteBody(BaseModel):
    note: str


@router.post("/agents/{agent_id}/incidents/{incident_id}/stop-request")
async def request_stop(agent_id: str, incident_id: str, body: NoteBody, user=Depends(require_update)):
    """Asks the owner (and the backup owner, and the admins when there is no owner) to stop the agent."""
    if len(body.note.strip()) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say why the agent should stop, in at least {MIN_NOTE} characters.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        i = await db.get(Incident, incident_id)
        if i is None or i.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Incident not found")
        if i.stop_requested_at and not i.stop_acknowledged_at:
            raise HTTPException(status_code=409, detail="A stop request is already waiting for the owner.")
        i.stop_requested_at, i.stop_requested_by, i.stop_reason = datetime.now(timezone.utc), actor, body.note.strip()
        i.stop_acknowledged_at = i.stop_acknowledged_by = i.stop_note = None
        _log(db, actor, "incident.stop_request", agent_id, {"incident": i.title, "reason": i.stop_reason})
        owners = [u for u in (agent.owner_user_id, agent.backup_owner_user_id) if u]
        name = agent.name
        names = dict((await db.execute(select(User.id, User.name))).all())
        row = _row(i, names)
    told = owners or await notify.admins()
    for uid in told:
        await notify.notify(user_id=uid, kind="stop_request", subject=f"Agent Registry: stop {name} now",
                            items=[{"type": "stop_request", "link": f"/agents/{agent_id}?tab=risk",
                                    "text": f"You are asked to stop {name} because of the incident \"{row['title']}\": {body.note.strip()} "
                                            "Acknowledge on the Risk tab when it is stopped."}],
                            dedupe_key=f"stop:{incident_id}:{uid}:{row['stop']['requestedAt'][:16]}")
    return {**row, "told": len(told), "toldOwners": bool(owners)}


@router.post("/agents/{agent_id}/incidents/{incident_id}/stop-ack")
async def acknowledge_stop(agent_id: str, incident_id: str, body: NoteBody, user=Depends(require_update)):
    """The owner, the backup owner or an admin says the agent is stopped (or why not)."""
    if len(body.note.strip()) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say what was done, in at least {MIN_NOTE} characters.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        if actor not in (agent.owner_user_id, agent.backup_owner_user_id) and not has_permission(user.get("role", ""), "admin"):
            raise HTTPException(status_code=403, detail="Only the owner, the backup owner or a Registry Admin acknowledges a stop request.")
        i = await db.get(Incident, incident_id)
        if i is None or i.agent_id != agent_id or not i.stop_requested_at:
            raise HTTPException(status_code=404, detail="No stop request on this incident")
        i.stop_acknowledged_at, i.stop_acknowledged_by, i.stop_note = datetime.now(timezone.utc), actor, body.note.strip()
        _log(db, actor, "incident.stop_ack", agent_id, {"incident": i.title, "note": i.stop_note})
        names = dict((await db.execute(select(User.id, User.name))).all())
        return _row(i, names)


class InboundBody(BaseModel):
    agent: str = Field(..., description="The agent's id or exact name")
    title: str = Field(..., min_length=3, max_length=300)
    source: str = "other"
    externalId: str = Field(..., min_length=1, max_length=120)
    url: Optional[str] = None
    severity: str = "medium"
    status: str = "open"


@router.post("/incidents/inbound")
async def inbound(body: InboundBody, user=Depends(require_update)):
    """For PagerDuty or ServiceNow automation: opens, updates or resolves the incident
    with this source and external id on the named agent."""
    if body.severity not in SEVERITIES or body.status not in ("open", "resolved"):
        raise HTTPException(status_code=422, detail="severity is low, medium, high or critical; status is open or resolved.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(or_(Agent.id == body.agent, Agent.name == body.agent)))).scalars().first()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"No agent with the id or name {body.agent!r}.")
        i = (await db.execute(select(Incident).where(Incident.source == body.source, Incident.external_id == body.externalId))).scalar_one_or_none()
        created = i is None
        if created:
            i = Incident(id=f"inc-{secrets.token_hex(6)}", agent_id=agent.id, source=body.source, external_id=body.externalId,
                         opened_at=datetime.now(timezone.utc), created_by=actor, title=body.title, status="open")
            db.add(i)
        i.title, i.severity, i.url = body.title, body.severity, body.url or i.url
        if body.status == "resolved" and i.status != "resolved":
            i.status, i.resolved_at, i.resolution = "resolved", datetime.now(timezone.utc), f"Resolved in {body.source}."
        _log(db, actor, "incident.link" if created else "incident.update", agent.id,
             {"title": i.title, "severity": i.severity, "source": i.source, "externalId": i.external_id, "status": i.status})
        return {"id": i.id, "agentId": agent.id, "created": created, "status": i.status}


@router.get("/portfolio/incidents")
async def open_incidents(_=Depends(require_read)):
    async with get_db_session() as db:
        rows = (await db.execute(select(Incident, Agent).join(Agent, Agent.id == Incident.agent_id)
                                 .where(or_(Incident.status == "open", Incident.stop_requested_at.is_not(None)))
                                 .order_by(Incident.opened_at.desc()))).all()
        names = dict((await db.execute(select(User.id, User.name))).all())
    return {"open": [{**_row(i, names), "agentName": a.name} for i, a in rows if i.status == "open"],
            "stopWaiting": [{**_row(i, names), "agentName": a.name} for i, a in rows if i.stop_requested_at and not i.stop_acknowledged_at]}
