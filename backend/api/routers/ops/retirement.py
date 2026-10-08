"""Retiring an agent in checked steps, each recorded with who and when:

1. No calls for 7 days, read from the stored usage. An agent without a tracing
   link cannot show this, so a person confirms it and says how they checked.
2. Consumers told. Starting the retirement sends a notice to everyone with
   approved access and to the owner. Teams with no contact in the registry are
   listed, and a person confirms they were told another way.
3. Keys and access revoked: the agent's identity key and every approved access grant.
4. Stage set to Deprecated, only when steps 1 to 3 are done.

The stage route refuses Deprecated, so this is the only way to retire an agent."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentAccessRequest, AgentIdentity, AgentRetirement, AgentTokenUsage, AuditLog, User
from orchestrations.risk_scan import as_utc
from services import notify

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Retirement"])

QUIET_DAYS = 7
MIN_NOTE = 20
STEP_LABELS = {
    "traffic": f"No calls for {QUIET_DAYS} days",
    "consumers": "Consumers told",
    "access": "Keys and access revoked",
    "stage": "Stage set to Deprecated",
}


def traffic_step(linked: bool, last_call: date | None, today: date, confirmed: dict | None) -> dict:
    if confirmed:
        return {"state": "done", "detail": f"Confirmed by {confirmed['by']}: {confirmed['note']}", "at": confirmed.get("at")}
    if not linked:
        return {"state": "needs_confirmation",
                "detail": "Not linked to tracing, so the registry cannot see its calls. Confirm that it receives none and say how you checked."}
    if last_call is None:
        return {"state": "done", "detail": "No call recorded since it was linked to tracing."}
    days = (today - last_call).days
    if days >= QUIET_DAYS:
        return {"state": "done", "detail": f"Last call on {last_call.isoformat()}, {days} days ago."}
    return {"state": "waiting", "detail": f"Last call on {last_call.isoformat()}, {days} day{'s' if days != 1 else ''} ago. "
                                         f"This step completes on {(last_call + timedelta(days=QUIET_DAYS)).isoformat()} if no call comes in."}


def consumers_step(step: dict) -> dict:
    told, untold, confirmed = step.get("notified", []), step.get("noContact", []), step.get("confirmed")
    parts = [f"Notice sent to {', '.join(told)}." if told else "Nobody with approved access to notify."]
    if untold and not confirmed:
        return {"state": "needs_confirmation", "detail": " ".join(parts + [
            f"No contact in the registry for {', '.join(untold)}. Confirm they were told another way."])}
    if confirmed:
        parts.append(f"{', '.join(untold)} told another way, confirmed by {confirmed['by']}: {confirmed['note']}")
    return {"state": "done", "detail": " ".join(parts)}


async def _names(db) -> dict:
    return dict((await db.execute(select(User.id, User.name))).all())


async def _last_call(db, agent_id: str) -> date | None:
    last = (await db.execute(select(func.max(AgentTokenUsage.bucket)).where(
        AgentTokenUsage.agent_id == agent_id, AgentTokenUsage.source.in_(("phoenix", "langfuse")),
        AgentTokenUsage.invocation_count > 0))).scalar()
    return as_utc(last).date() if last else None


async def _view(db, agent: Agent, r: AgentRetirement | None) -> dict:
    today = datetime.now(timezone.utc).date()
    names = await _names(db)
    past = (await db.execute(select(AgentRetirement).where(AgentRetirement.agent_id == agent.id, AgentRetirement.status != "in_progress")
                             .order_by(AgentRetirement.started_at.desc()))).scalars().all()
    history = [{"status": p.status, "reason": p.reason, "startedBy": names.get(p.started_by, p.started_by),
                "startedAt": as_utc(p.started_at).isoformat() if p.started_at else None,
                "completedAt": as_utc(p.completed_at).isoformat() if p.completed_at else None} for p in past]
    if r is None:
        return {"active": None, "history": history, "quietDays": QUIET_DAYS, "stage": agent.lifecycle_stage}
    s = r.steps or {}
    steps = {
        "traffic": traffic_step(bool(agent.phoenix_project or agent.trace_connector_id), await _last_call(db, agent.id), today, s.get("traffic", {}).get("confirmed")),
        "consumers": consumers_step(s.get("consumers", {})),
        "access": ({"state": "done", "detail": s["access"]["detail"], "at": s["access"].get("at")} if s.get("access", {}).get("done")
                   else {"state": "todo", "detail": "Revoke the agent's identity key and every approved access grant."}),
    }
    ready = all(v["state"] == "done" for v in steps.values())
    steps["stage"] = {"state": "done" if r.status == "done" else ("todo" if ready else "waiting"),
                      "detail": "Set to Deprecated." if r.status == "done" else
                      ("Ready: finish the retirement to set the stage." if ready else "Waits for the steps above.")}
    replacement = await db.get(Agent, r.replacement_agent_id) if r.replacement_agent_id else None
    return {"active": {"id": r.id, "status": r.status, "reason": r.reason,
                       "replacement": {"id": replacement.id, "name": replacement.name} if replacement else None,
                       "startedBy": names.get(r.started_by, r.started_by), "startedAt": as_utc(r.started_at).isoformat() if r.started_at else None,
                       "steps": [{"key": k, "label": STEP_LABELS[k], **v} for k, v in steps.items()], "canFinish": ready},
            "history": history, "quietDays": QUIET_DAYS, "stage": agent.lifecycle_stage}


async def _active(db, agent_id: str) -> AgentRetirement | None:
    return (await db.execute(select(AgentRetirement).where(AgentRetirement.agent_id == agent_id, AgentRetirement.status == "in_progress")
                             .limit(1))).scalar_one_or_none()


async def _agent(db, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _log(db, agent: Agent, actor: str, action: str, changes: dict) -> None:
    db.add(AuditLog(org_id=agent.org_id or "org-default", actor=actor, action=action, entity_type="agent", entity_id=agent.id, changes=changes))


@router.get("/agents/{agent_id}/retirement")
async def get_retirement(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        return await _view(db, agent, await _active(db, agent_id))


class StartBody(BaseModel):
    reason: str
    replacementAgentId: str | None = None


@router.post("/agents/{agent_id}/retirement")
async def start_retirement(agent_id: str, body: StartBody, user=Depends(require_update)):
    reason = body.reason.strip()
    if len(reason) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say why the agent is retired, in at least {MIN_NOTE} characters.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        if agent.lifecycle_stage == "Deprecated":
            raise HTTPException(status_code=409, detail="The agent is already retired.")
        if await _active(db, agent_id):
            raise HTTPException(status_code=409, detail="A retirement is already in progress for this agent.")
        if body.replacementAgentId and (body.replacementAgentId == agent_id or await db.get(Agent, body.replacementAgentId) is None):
            raise HTTPException(status_code=422, detail="The replacement must be another registered agent.")
        grants = (await db.execute(select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id,
                                                                     AgentAccessRequest.status == "approved"))).scalars().all()
        users = {u.id: u for u in (await db.execute(select(User).where(User.is_active == True))).scalars()}  # noqa: E712
        recipients = {g.requester_id: g.team for g in grants if g.requester_id in users}
        contacted_teams = {g.team.lower() for g in grants if g.requester_id in users}
        no_contact = [t for t in (agent.consumers or []) if t.lower() not in contacted_teams]
        if agent.owner_user_id and agent.owner_user_id in users:
            recipients.setdefault(agent.owner_user_id, "owner")
        replacement = await db.get(Agent, body.replacementAgentId) if body.replacementAgentId else None
        r = AgentRetirement(id=f"ret-{uuid.uuid4().hex[:12]}", agent_id=agent_id, status="in_progress", reason=reason,
                            replacement_agent_id=body.replacementAgentId, started_by=actor, started_at=datetime.now(timezone.utc),
                            steps={"consumers": {"notified": sorted({f"{users[u].name} ({t})" for u, t in recipients.items()}), "noContact": no_contact}})
        db.add(r)
        _log(db, agent, actor, "retirement.start", {"reason": reason, "replacement": replacement.name if replacement else None})
        name = agent.name
    text = f"{name} is being retired: {reason}" + (f" Its replacement is {replacement.name}." if replacement else "")
    for uid in recipients:
        await notify.notify(user_id=uid, kind="retirement", subject=f"Agent Registry: {name} is being retired",
                            items=[{"type": "retirement", "text": text, "link": f"/agents/{agent_id}"}],
                            dedupe_key=f"retirement:{r.id}:{uid}")
    async with get_db_session() as db:
        return await _view(db, await _agent(db, agent_id), await _active(db, agent_id))


class ConfirmBody(BaseModel):
    step: str
    note: str


@router.post("/agents/{agent_id}/retirement/confirm")
async def confirm_step(agent_id: str, body: ConfirmBody, user=Depends(require_update)):
    if body.step not in ("traffic", "consumers"):
        raise HTTPException(status_code=422, detail="Only the traffic and consumers steps are confirmed by a person.")
    note = body.note.strip()
    if len(note) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say how you checked, in at least {MIN_NOTE} characters.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        r = await _active(db, agent_id)
        if r is None:
            raise HTTPException(status_code=409, detail="No retirement is in progress.")
        names = await _names(db)
        steps = dict(r.steps or {})
        steps[body.step] = {**steps.get(body.step, {}), "confirmed": {"by": names.get(actor, actor), "note": note,
                                                                      "at": datetime.now(timezone.utc).isoformat()}}
        r.steps = steps
        _log(db, agent, actor, "retirement.step", {"step": STEP_LABELS[body.step], "note": note})
        return await _view(db, agent, r)


@router.post("/agents/{agent_id}/retirement/revoke")
async def revoke_access(agent_id: str, user=Depends(require_update)):
    actor = user.get("user_id", "unknown")
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        r = await _active(db, agent_id)
        if r is None:
            raise HTTPException(status_code=409, detail="Start the retirement first.")
        identity = await db.get(AgentIdentity, agent_id)
        key_revoked = bool(identity and identity.api_key_hash and not identity.revoked_at)
        if identity and not identity.revoked_at:
            identity.api_key_hash, identity.revoked_at = None, now
        grants = (await db.execute(select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id,
                                                                     AgentAccessRequest.status == "approved"))).scalars().all()
        consumers = list(agent.consumers or [])
        for g in grants:
            g.status, g.decided_at, g.decision_note = "revoked", now, "Revoked because the agent is being retired."
            if g.added_to_consumers:
                consumers = [c for c in consumers if c.lower() != g.team.lower()]
                g.added_to_consumers = False
        agent.consumers = consumers
        detail = (f"{'Identity key revoked' if key_revoked else 'No active identity key'}, "
                  f"{len(grants)} access grant{'s' if len(grants) != 1 else ''} revoked.")
        steps = dict(r.steps or {})
        steps["access"] = {"done": True, "detail": detail, "at": now.isoformat()}
        r.steps = steps
        _log(db, agent, actor, "retirement.step", {"step": STEP_LABELS["access"], "detail": detail})
        return await _view(db, agent, r)


@router.post("/agents/{agent_id}/retirement/finish")
async def finish(agent_id: str, user=Depends(require_update)):
    actor = user.get("user_id", "unknown")
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        r = await _active(db, agent_id)
        if r is None:
            raise HTTPException(status_code=409, detail="No retirement is in progress.")
        view = await _view(db, agent, r)
        if not view["active"]["canFinish"]:
            open_steps = [s["label"] for s in view["active"]["steps"] if s["state"] != "done" and s["key"] != "stage"]
            raise HTTPException(status_code=409, detail=f"Not every step is done: {', '.join(open_steps)}.")
        before = agent.lifecycle_stage
        agent.lifecycle_stage, agent.deprecated_at, agent.time_in_stage_weeks = "Deprecated", now, 0
        r.status, r.completed_at = "done", now
        _log(db, agent, actor, "stage_change", {"from": before, "to": "Deprecated", "source": "retirement", "reason": r.reason})
        _log(db, agent, actor, "retirement.finish", {"reason": r.reason})
        return await _view(db, agent, None)


class CancelBody(BaseModel):
    reason: str


@router.post("/agents/{agent_id}/retirement/cancel")
async def cancel(agent_id: str, body: CancelBody, user=Depends(require_update)):
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        r = await _active(db, agent_id)
        if r is None:
            raise HTTPException(status_code=409, detail="No retirement is in progress.")
        r.status, r.completed_at = "cancelled", datetime.now(timezone.utc)
        _log(db, agent, actor, "retirement.cancel", {"reason": body.reason.strip() or None,
                                                    "note": "Revoked access is not restored. Teams ask for access again."})
        return await _view(db, agent, None)
