"""Agent page — Governance tab API: gate reviews, stage readiness,
recertification and exceptions. Rules live in governance/gate_policy.py;
nothing here approves, registers or changes anything unless a person asks."""
from __future__ import annotations

import asyncio
import re
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator, BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import USE_Rbac, has_permission, require_admin, require_read, require_update
from db.base import get_db_session
from db.models import Agent, AuditLog, GovernanceException, GovernanceReview, User
from governance import gate_policy as gp
from orchestrations import governance_checks as gc
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Governance"])

LLM_TIMEOUT_S = 90
LLM_MAX_TOKENS = 900
HISTORY_LIMIT = 20


# ── Schemas ─────────────────────────────────────────────────────────────────

def _check_status(value: str) -> str:
    if value not in gp.STATUSES:
        raise ValueError(f"Must be one of: {', '.join(gp.STATUSES)}")
    return value


GateStatus = Annotated[str, AfterValidator(_check_status)]


class EvidenceLink(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., max_length=2000)

    @field_validator("url")
    @classmethod
    def http_url(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"https?://\S+", v, flags=re.IGNORECASE):
            raise ValueError("Evidence links must be http(s) URLs")
        return v


class GateReviewUpdate(BaseModel):
    # A body with a status records a decision (reviewed_at, expiry); without
    # one it only edits reviewer, notes, conditions, evidence or ticks.
    status: Optional[GateStatus] = None
    reviewer: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    conditions: Optional[str] = None
    evidence: Optional[list[EvidenceLink]] = None
    checklist: Optional[dict[str, Optional[str]]] = None

    @field_validator("checklist")
    @classmethod
    def tick_values(cls, v: Optional[dict[str, Optional[str]]]) -> Optional[dict[str, Optional[str]]]:
        for item_id, tick in (v or {}).items():
            if tick not in gp.TICK_VALUES and tick not in (None, ""):
                raise ValueError(f"{item_id}: tick must be one of pass, fail, n/a (or empty to clear)")
        return v


class LegacyGateUpdate(BaseModel):
    status: GateStatus


class StageChange(BaseModel):
    stage: str
    overrideReason: Optional[str] = Field(None, max_length=2000)

    @field_validator("stage")
    @classmethod
    def known_stage(cls, v: str) -> str:
        if v not in gp.STAGES:
            raise ValueError(f"Must be one of: {', '.join(gp.STAGES)}")
        return v


class RecertifyRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=2000)


class ExceptionRequest(BaseModel):
    gate: str
    reason: str = Field(..., min_length=1, max_length=4000)
    expiresAt: str
    approvedBy: str = Field(..., min_length=1, max_length=255)

    @field_validator("gate")
    @classmethod
    def known_gate(cls, v: str) -> str:
        if v not in gp.GATES:
            raise ValueError(f"Must be one of: {', '.join(gp.GATES)}")
        return v


# ── Helpers ─────────────────────────────────────────────────────────────────

def _iso(value: Any) -> str | None:
    dt = gp.as_utc(value)
    return dt.isoformat() if dt else None


def _require_gate(gate: str) -> None:
    if gate not in gp.GATES:
        raise HTTPException(status_code=400, detail=f"Invalid gate. Must be one of: {', '.join(gp.GATES)}")


async def _agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
    )).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _review_row(agent: Agent, gate: str) -> GovernanceReview:
    review = next((r for r in agent.governance_reviews if r.gate == gate), None)
    if review is None:
        review = GovernanceReview(id=secrets.token_hex(8), agent_id=agent.id, gate=gate,
                                  status="Not Submitted", evidence=[], checklist={})
        agent.governance_reviews.append(review)
    return review


def _snapshot(review: GovernanceReview) -> dict:
    return {
        "status": review.status, "reviewer": review.reviewer, "notes": review.notes,
        "conditions": review.conditions, "evidence": list(review.evidence or []),
        "checklist": dict(review.checklist or {}),
        "reviewedAt": _iso(review.reviewed_at), "expiresAt": _iso(review.expires_at),
    }


def _audit(db: AsyncSession, user: dict, action: str, agent_id: str, changes: dict) -> None:
    db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action=action,
                    entity_type="agent", entity_id=agent_id, changes=changes))


def _gate_to_api(gate: str, review: dict | None, facts: dict, now: datetime) -> dict:
    review = review or {"status": "Not Submitted"}
    checklist = gp.evaluate_checklist(gate, facts, review.get("checklist"))
    return {
        "gate": gate,
        "label": gp.GATES[gate],
        "reviewerRole": gp.REVIEWER_ROLES[gate],
        "status": review["status"],
        "reviewer": review.get("reviewer"),
        "notes": review.get("notes"),
        "conditions": review.get("conditions"),
        "evidence": review.get("evidence") or [],
        "checklist": checklist,
        "checklistSummary": gp.checklist_summary(checklist),
        "reviewedAt": _iso(review.get("reviewed_at")),
        "expiresAt": _iso(review.get("expires_at")),
        "expiryState": gp.gate_expiry_state(review, now),
    }


def _exception_to_api(exc: dict, now: datetime) -> dict:
    expires = gp.as_utc(exc["expires_at"])
    return {
        "id": exc["id"], "gate": exc["gate"], "gateLabel": gp.GATES.get(exc["gate"], exc["gate"]),
        "reason": exc["reason"], "approvedBy": exc["approved_by"],
        "expiresAt": _iso(expires), "createdAt": _iso(exc.get("created_at")),
        "daysLeft": max(0, (expires - now).days) if expires else None,
    }


def _readiness(state: dict, target: str, now: datetime, mode: str | None = None) -> dict:
    return gp.stage_readiness(state["facts"], state["reviews"], target, state["exceptions"],
                              state["budget_set"], now, mode)


def _approval_warnings(checklist: list[dict]) -> list[dict]:
    """Approving is the reviewer's call; open checklist items are reported, not enforced."""
    return [
        {"code": f"checklist_{item['result']}", "message": f"{item['label']}: "
         + ("failing" if item["result"] == "fail" else "not yet confirmed")}
        for item in checklist if item["result"] in ("fail", "pending")
    ]


# ── Governance state ────────────────────────────────────────────────────────

async def _history(db: AsyncSession, agent_id: str) -> list[dict]:
    rows = (await db.execute(
        select(AuditLog.created_at, AuditLog.actor, AuditLog.action, AuditLog.changes, User.email)
        .outerjoin(User, User.id == AuditLog.actor)
        .where(AuditLog.entity_type == "agent", AuditLog.entity_id == agent_id,
               AuditLog.action.in_(gp.HISTORY_ACTIONS))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(HISTORY_LIMIT)
    )).all()
    return [
        {"at": _iso(at), "actor": email or actor, "action": action, **gp.history_entry(action, changes)}
        for at, actor, action, changes, email in rows
    ]


@router.get("/agents/{agent_id}/governance")
async def get_governance(agent_id: str, _=Depends(require_read)):
    now = gc.utcnow()
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        state = await gc.load_state(db, agent, now)
        history = await _history(db, agent_id)
    facts = state["facts"]
    nxt = gp.next_stage(agent.lifecycle_stage)
    return {
        "agentId": agent.id,
        "stage": agent.lifecycle_stage,
        "riskLevel": agent.risk_level,
        "riskTier": state["risk_tier"],
        "euAiActCategory": agent.eu_ai_act_category,
        "enforcement": gp.enforcement_mode(),
        "validityDays": facts["validity_days"],
        "maxExceptionDays": gp.MAX_EXCEPTION_DAYS,
        "gates": [_gate_to_api(gate, state["reviews"].get(gate), facts, now) for gate in gp.GATES],
        "exceptions": [_exception_to_api(e, now) for e in state["exceptions"]],
        "readiness": {
            "current": agent.lifecycle_stage,
            "next": _readiness(state, nxt, now) if nxt else None,
            "production": _readiness(state, "Production", now),
        },
        "recertification": gc.recertification(state, now),
        "telemetry": {"phoenixProject": agent.phoenix_project, "usage": state["usage"],
                      "usageSource": state["usage_source"]},
        "contextPresent": facts["context_present"],
        "history": history,
    }


async def _apply_gate_update(agent_id: str, gate: str, body: GateReviewUpdate, user: dict, legacy: bool) -> dict:
    """Shared by the agent-page path and the legacy portfolio path. The legacy
    body carries only a status, so it cannot name a reviewer or conditions."""
    _require_gate(gate)
    now = gc.utcnow()
    updates = body.model_dump(exclude_unset=True)
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        review = _review_row(agent, gate)
        before = _snapshot(review)

        if "checklist" in updates:
            unknown = set(updates["checklist"] or {}) - gp.checklist_item_ids(gate)
            if unknown:
                raise HTTPException(status_code=422, detail=f"Unknown checklist item(s): {', '.join(sorted(unknown))}")
            ticks = dict(review.checklist or {})
            for item_id, tick in (updates["checklist"] or {}).items():
                if tick in gp.TICK_VALUES:
                    ticks[item_id] = tick
                else:
                    ticks.pop(item_id, None)
            review.checklist = ticks
        if "reviewer" in updates:
            review.reviewer = (updates["reviewer"] or "").strip() or None
        if "notes" in updates:
            review.notes = (updates["notes"] or "").strip() or None
        if "conditions" in updates:
            review.conditions = (updates["conditions"] or "").strip() or None
        if "evidence" in updates:
            review.evidence = [e.model_dump() for e in body.evidence or []]

        status = updates.get("status")
        if status:
            if not legacy and status == "Approved with Conditions" and not review.conditions:
                raise HTTPException(status_code=422, detail="Conditions are required for 'Approved with Conditions'")
            if not legacy and status in gp.APPROVED_STATUSES and not review.reviewer:
                raise HTTPException(status_code=422, detail="Name the accountable reviewer before approving")
            review.status = status
            review.reviewed_at = now
            review.expires_at = (now + timedelta(days=gp.validity_days(
                gp.effective_risk_level(agent.risk_level, agent.eu_ai_act_category), get_settings(),
            ))) if status in gp.APPROVED_STATUSES else None

        state = await gc.load_state(db, agent, now)
        result = _gate_to_api(gate, state["reviews"].get(gate), state["facts"], now)
        changes = {"gate": gate, "path": "legacy" if legacy else "agent", "before": before, "after": _snapshot(review)}
        if status in gp.APPROVED_STATUSES:
            changes["openItemsAtApproval"] = [i["id"] for i in result["checklist"] if i["result"] in ("fail", "pending")]
        _audit(db, user, "gate_update", agent_id, changes)

    warnings = _approval_warnings(result["checklist"]) if status in gp.APPROVED_STATUSES else []
    return {**result, "warnings": warnings}


@router.put("/agents/{agent_id}/governance/{gate}")
async def update_gate_review(agent_id: str, gate: str, body: GateReviewUpdate, user=Depends(require_update)):
    return await _apply_gate_update(agent_id, gate, body, user, legacy=False)


@router.put("/governance/agents/{agent_id}/governance/{gate}")
async def update_gate_legacy(agent_id: str, gate: str, body: LegacyGateUpdate, user=Depends(require_update)):
    review = await _apply_gate_update(agent_id, gate, GateReviewUpdate(status=body.status), user, legacy=True)
    return {"status": "updated", "review": review}


# ── Review-notes drafting (never saved here) ───────────────────────────────

def _context_for_prompt(context_md: str | None, gate: str) -> str | None:
    if not (context_md or "").strip():
        return None
    from governance.context_reader import parse_sections, redact, strip_comments

    text = redact(strip_comments(context_md)).strip()
    return gp.context_for_gate(gate, text, parse_sections(text)) if text else None


def _llm_client():
    from llm_client import LLMClient

    settings = get_settings()
    client = LLMClient()
    client.endpoint = settings.azure_openai_endpoint or client.endpoint
    client.api_key = settings.azure_openai_api_key or client.api_key
    client.deployment = settings.azure_openai_deployment or client.deployment
    client.api_version = settings.azure_openai_api_version or client.api_version
    return client


async def _ask_llm(system: str, user_prompt: str) -> str | None:
    client = _llm_client()
    if not client.available:
        return None
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(client.chat, system, user_prompt, LLM_MAX_TOKENS), LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return None
    text = (text or "").strip()
    # LLMClient answers with a "[DETERMINISTIC]" placeholder when the call fails.
    if not text or text.startswith("[DETERMINISTIC]"):
        return None
    return text


def _prompt_facts(agent: Agent, reviews: dict) -> dict:
    return {
        "name": agent.name, "description": agent.description, "aiType": agent.ai_type,
        "stage": agent.lifecycle_stage, "owner": agent.owner, "department": agent.dept_id,
        "businessOutcome": agent.business_outcome, "model": agent.model_name,
        "modelProvider": agent.model_provider, "riskLevel": agent.risk_level,
        "euAiActCategory": agent.eu_ai_act_category, "sla": agent.sla, "apiEndpoint": agent.api_endpoint,
        "phoenixProject": agent.phoenix_project, "enterpriseSystems": agent.enterprise_systems or [],
        "databases": agent.databases or [], "knowledgeBases": agent.knowledge_bases or [],
        "mcpServers": agent.mcp_servers or [], "calls": agent.calls or [], "consumers": agent.consumers or [],
        "gateStatuses": {gate: (reviews.get(gate) or {}).get("status", "Not Submitted") for gate in gp.GATES},
    }


@router.post("/agents/{agent_id}/governance/{gate}/draft-notes")
async def draft_review_notes(agent_id: str, gate: str, _=Depends(require_update)):
    _require_gate(gate)
    now = gc.utcnow()
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        state = await gc.load_state(db, agent, now)
        facts = _prompt_facts(agent, state["reviews"])
        context_text = _context_for_prompt(agent.context_md, gate)
    review = state["reviews"].get(gate) or {}
    checklist = gp.evaluate_checklist(gate, state["facts"], review.get("checklist"))
    # Gate statuses are in the facts; findings derived from them lag until the next risk scan.
    risks = [r for r in state["open_risks"] if not gp.is_gate_derived_finding(r["rule_id"], r["title"])]
    system, user_prompt = gp.review_prompt(gate, facts, checklist, state["usage"], risks, context_text)
    draft = await _ask_llm(system, user_prompt)
    if draft is None:
        return {
            "gate": gate, "llmStatus": "unavailable", "usedContext": False,
            "draft": gp.fallback_review_notes(gate, checklist, risks, state["usage"]),
        }
    return {"gate": gate, "llmStatus": "ok", "usedContext": context_text is not None, "draft": draft}


# ── Stage changes ───────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/stage-readiness")
async def get_stage_readiness(agent_id: str, target: str = Query("Production"), _=Depends(require_read)):
    if target not in gp.STAGES:
        raise HTTPException(status_code=422, detail=f"target must be one of: {', '.join(gp.STAGES)}")
    now = gc.utcnow()
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        state = await gc.load_state(db, agent, now)
    return {"agentId": agent_id, "current": agent.lifecycle_stage, **_readiness(state, target, now)}


@router.put("/agents/{agent_id}/stage")
async def change_stage(agent_id: str, body: StageChange, user=Depends(require_update)):
    now = gc.utcnow()
    mode = gp.enforcement_mode()
    override = (body.overrideReason or "").strip() or None
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        state = await gc.load_state(db, agent, now)
        readiness = _readiness(state, body.stage, now, mode)
        current = agent.lifecycle_stage
        if body.stage == current:
            return {"agentId": agent_id, "from": current, "to": current, "changed": False, "mode": mode,
                    "warnings": readiness["warnings"], "readiness": readiness}
        if readiness["blocked"] and override and USE_Rbac and not has_permission(user.get("role", ""), "admin"):
            raise HTTPException(status_code=403, detail="Only an admin can override a blocked stage change")
        blocked = readiness["blocked"] and not override
        _audit(db, user, "stage_change_blocked" if blocked else "stage_change", agent_id, {
            "from": current, "to": body.stage, "mode": mode, "overrideReason": override,
            "warnings": [{"code": w["code"], "message": w["message"]} for w in readiness["warnings"]],
        })
        if not blocked:
            agent.lifecycle_stage = body.stage
            agent.time_in_stage_weeks = 0
            agent.deprecated_at = (agent.deprecated_at or now) if body.stage == "Deprecated" else None
    if blocked:
        raise HTTPException(status_code=409, detail={
            "message": f"Moving to {body.stage} is blocked (GOVERNANCE_ENFORCEMENT=block). "
                       "Resolve the warnings, or give an override reason.",
            "mode": mode, "warnings": readiness["warnings"],
        })
    return {"agentId": agent_id, "from": current, "to": body.stage, "changed": True, "mode": mode,
            "overrideReason": override, "warnings": readiness["warnings"], "readiness": readiness}


# ── Recertification and exceptions ──────────────────────────────────────────

async def _recertify(agent_id: str, user: dict, reason: str | None) -> dict:
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        before = {}
        for gate in gp.GATES:
            review = _review_row(agent, gate)
            before[gate] = {"status": review.status, "expiresAt": _iso(review.expires_at)}
            review.status = "In Review"
            review.reviewed_at = None
            review.expires_at = None
        _audit(db, user, "recertify", agent_id, {"gates_reset": list(gp.GATES), "reason": reason, "before": before})
    return {"status": "recertified", "gates_reset": list(gp.GATES)}


@router.post("/agents/{agent_id}/recertify")
async def recertify(agent_id: str, body: Optional[RecertifyRequest] = None, user=Depends(require_update)):
    return await _recertify(agent_id, user, ((body.reason or "").strip() or None) if body else None)


@router.post("/governance/agents/{agent_id}/recertify")
async def recertify_legacy(agent_id: str, user=Depends(require_update)):
    return await _recertify(agent_id, user, None)


@router.post("/agents/{agent_id}/governance/exceptions")
async def create_exception(agent_id: str, body: ExceptionRequest, user=Depends(require_admin)):
    now = gc.utcnow()
    expires = gp.parse_exception_expiry(body.expiresAt)
    error = gp.validate_exception_expiry(expires, now)
    if error:
        raise HTTPException(status_code=422, detail=error)
    reason, approved_by = body.reason.strip(), body.approvedBy.strip()
    if not reason or not approved_by:
        raise HTTPException(status_code=422, detail="reason and approvedBy are required")
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        exc = GovernanceException(id=secrets.token_hex(8), agent_id=agent_id, gate=body.gate, reason=reason,
                                  expires_at=expires, approved_by=approved_by, created_at=now)
        db.add(exc)
        _audit(db, user, "exception_create", agent_id, {
            "id": exc.id, "gate": body.gate, "reason": reason, "expiresAt": _iso(expires), "approvedBy": approved_by,
        })
    return _exception_to_api(gc.exception_to_dict(exc), now)
