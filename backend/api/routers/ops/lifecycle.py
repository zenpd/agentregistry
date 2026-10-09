"""Lifecycle settings and reports: gate templates by risk tier, required fields
per stage, stall limits, and the waiver report. Reading needs read; changing
needs an admin, and every change is recorded."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import require_admin, require_read, require_update
from db.base import get_db_session
from db.models import Agent, GovernanceException, User
from governance import lifecycle
from governance import templates as tpl
from orchestrations.risk_scan import as_utc
from services import ai_meter
from services.audit import log_audit_event

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Lifecycle"])

REQUIRABLE = ("owner", "dept", "description", "business_outcome", "sla", "phoenix_project", "value_amount", "model_name",
              "api_endpoint", "capabilities", "inputs", "outputs", "classification")


@router.get("/governance/settings")
async def governance_settings(_=Depends(require_read)):
    return {"templates": await tpl.templates(), "requiredFields": await tpl.required_fields(), "stallWeeks": await tpl.stall_weeks(),
            "requirable": [{"key": k, "label": lifecycle.FIELD_LABELS[k]} for k in REQUIRABLE]}


class SettingsBody(BaseModel):
    templates: dict | None = None
    requiredFields: dict | None = None
    stallWeeks: dict | None = None


@router.put("/governance/settings")
async def update_governance_settings(body: SettingsBody, user=Depends(require_admin)):
    if body.templates is not None:
        problem = lifecycle.check_templates(body.templates)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        await ai_meter.set_setting("governance.templates", body.templates, user["user_id"])
    if body.requiredFields is not None:
        bad = [k for v in body.requiredFields.values() for k in (v or []) if k not in REQUIRABLE]
        if bad or set(body.requiredFields) - {"Development", "Testing", "Production"}:
            raise HTTPException(status_code=422, detail=f"Stages are Development, Testing and Production. Fields: {', '.join(REQUIRABLE)}.")
        await ai_meter.set_setting("stage.required_fields", body.requiredFields, user["user_id"])
    if body.stallWeeks is not None:
        if any(not isinstance(v, int) or v < 1 for v in body.stallWeeks.values()) or set(body.stallWeeks) - {"Ideation", "Development", "Testing"}:
            raise HTTPException(status_code=422, detail="Stall limits are whole weeks for Ideation, Development and Testing.")
        await ai_meter.set_setting("stage.stall_weeks", body.stallWeeks, user["user_id"])
    await log_audit_event(actor=user["user_id"], action="settings.update", entity_type="governance", entity_id="settings",
                          changes={k: v for k, v in body.model_dump().items() if v is not None})
    return await governance_settings()


@router.get("/governance/waivers")
async def waiver_report(_=Depends(require_read)):
    """Every waiver: who signed, until when, and the share with a reason and two signers."""
    async with get_db_session() as db:
        rows = (await db.execute(select(GovernanceException).order_by(GovernanceException.expires_at))).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
        agents = dict((await db.execute(select(Agent.id, Agent.name))).all())
    items = [{"id": w.id, "agentId": w.agent_id, "agentName": agents.get(w.agent_id), "gate": w.gate, "reason": w.reason,
              "expiresAt": as_utc(w.expires_at).isoformat() if w.expires_at else None, "status": w.status or "active",
              "firstSigner": names.get(w.first_signer, w.first_signer or w.approved_by), "secondSigner": names.get(w.second_signer, w.second_signer),
              "first_signer": w.first_signer or w.approved_by, "second_signer": w.second_signer} for w in rows if w.agent_id in agents]
    return {"waivers": items, "counts": lifecycle.waiver_counts(items)}


class OwnershipBody(BaseModel):
    ownerUserId: str | None = None
    ownerText: str | None = None
    backupOwnerUserId: str | None = None
    reason: str = ""


@router.put("/agents/{agent_id}/ownership")
async def set_ownership(agent_id: str, body: OwnershipBody, user=Depends(require_update)):
    """Name the accountable owner (a person with an account, or a team name) and a backup owner.
    Empty strings clear a field; fields not sent stay as they are."""
    from services import ownership

    fields = body.model_dump(exclude_unset=True)
    try:
        return await ownership.transfer(agent_id, owner_user_id=fields.get("ownerUserId"), backup_user_id=fields.get("backupOwnerUserId"),
                                        owner_text=fields.get("ownerText"), actor=user["user_id"], reason=body.reason.strip())
    except LookupError:
        raise HTTPException(status_code=404, detail="Agent not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Archived agents ──────────────────────────────────────────────────────────
# Archiving leaves an agent out of every page, count and job but keeps it and
# all its rows, so it can be brought back. Deleting is a separate, permanent step.

class ArchiveBody(BaseModel):
    reason: str


@router.post("/agents/{agent_id}/archive")
async def archive_agent(agent_id: str, body: ArchiveBody, user=Depends(require_admin)):
    from datetime import datetime, timezone

    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(status_code=422, detail="Say why the agent is archived, in at least 10 characters.")
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent.archived_at:
            raise HTTPException(status_code=409, detail=f"{agent.name} is already archived.")
        agent.archived_at, agent.archived_reason = datetime.now(timezone.utc), reason
        name = agent.name
    await log_audit_event(actor=user["user_id"], action="agent.archive", entity_type="agent", entity_id=agent_id,
                          changes={"name": name, "reason": reason})
    return {"agentId": agent_id, "archived": True}


@router.post("/agents/{agent_id}/unarchive")
async def unarchive_agent(agent_id: str, user=Depends(require_admin)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if not agent.archived_at:
            raise HTTPException(status_code=409, detail=f"{agent.name} is not archived.")
        agent.archived_at, agent.archived_reason = None, None
        name = agent.name
    await log_audit_event(actor=user["user_id"], action="agent.unarchive", entity_type="agent", entity_id=agent_id,
                          changes={"name": name})
    return {"agentId": agent_id, "archived": False}


@router.get("/admin/archived-agents")
async def archived_agents(_=Depends(require_read)):
    from db.scope import reset_scope, set_scope, showing_archived

    tokens = set_scope(False)
    try:
        with showing_archived():
            async with get_db_session() as db:
                rows = (await db.execute(select(Agent).where(Agent.archived_at.is_not(None)).order_by(Agent.name))).scalars().all()
    finally:
        reset_scope(tokens)
    return {"agents": [{"id": a.id, "name": a.name, "stage": a.lifecycle_stage, "isDemo": bool(a.is_demo),
                        "archivedAt": as_utc(a.archived_at).isoformat(), "reason": a.archived_reason} for a in rows]}
