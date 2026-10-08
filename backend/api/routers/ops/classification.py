"""Classification of an agent (EU AI Act category and registry risk level) and the
approved tool list with a risk class per tool.

Anyone who may update an agent answers the questions and proposes a result. A
person who decides the Architecture Review Board or the Data Protection gate (or
a Registry Admin) confirms it; only a confirmed classification changes the
agent's category and risk level. Confirming below the suggestion needs a reason."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import can_decide_gate, require_admin, require_read, require_update
from db.base import get_db_session
from db.models import Agent, ApprovedTool, AuditLog, ClassificationRecord, User
from governance import classification as cls
from governance import tool_risk
from orchestrations.risk_scan import as_utc

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Classification"])

CONFIRMING_GATES = ("arb", "dp")


def can_confirm(user: dict) -> bool:
    return any(can_decide_gate(user.get("role", ""), g) for g in CONFIRMING_GATES)


def _agent_tools(a: Agent) -> dict:
    return {"id": a.id, "name": a.name, "mcp_servers": a.mcp_servers, "enterprise_systems": a.enterprise_systems,
            "databases": a.databases, "knowledge_bases": a.knowledge_bases}


def _tool_row(t: ApprovedTool) -> dict:
    return {"id": t.id, "name": t.name, "kind": t.kind, "kindLabel": tool_risk.KIND_LABELS.get(t.kind, t.kind),
            "riskClass": t.risk_class, "note": t.note, "addedBy": t.added_by,
            "updatedAt": as_utc(t.updated_at or t.created_at).isoformat() if (t.updated_at or t.created_at) else None}


async def _approved(db) -> list[dict]:
    return [{"name": t.name, "risk_class": t.risk_class} for t in (await db.execute(select(ApprovedTool))).scalars()]


async def tool_risk_of(db, agent: Agent) -> dict:
    return tool_risk.tool_class(_agent_tools(agent), await _approved(db))


def _record(r: ClassificationRecord, names: dict) -> dict:
    return {"id": r.id, "status": r.status, "answers": r.answers or {},
            "suggestedCategory": r.suggested_category, "suggestedRiskLevel": r.suggested_risk_level, "reasons": r.reasons or [],
            "category": r.category, "riskLevel": r.risk_level, "note": r.note,
            "proposedBy": names.get(r.proposed_by, r.proposed_by), "proposedAt": as_utc(r.proposed_at).isoformat() if r.proposed_at else None,
            "confirmedBy": names.get(r.confirmed_by, r.confirmed_by),
            "confirmedAt": as_utc(r.confirmed_at).isoformat() if r.confirmed_at else None}


async def latest_confirmed(db, agent_id: str) -> ClassificationRecord | None:
    return (await db.execute(select(ClassificationRecord).where(
        ClassificationRecord.agent_id == agent_id, ClassificationRecord.status == "confirmed",
    ).order_by(ClassificationRecord.confirmed_at.desc()).limit(1))).scalar_one_or_none()


@router.get("/classification/questions")
async def questions(_=Depends(require_read)):
    return {"questions": cls.QUESTIONS, "categories": list(cls.CATEGORIES), "levels": list(cls.LEVELS),
            "minNoteWhenLower": cls.MIN_NOTE_WHEN_LOWER, "confirmedBy": "Architect Steward, Data Protection Officer or Registry Admin"}


@router.get("/agents/{agent_id}/classification")
async def get_classification(agent_id: str, user=Depends(require_read)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = (await db.execute(select(ClassificationRecord).where(ClassificationRecord.agent_id == agent_id)
                                 .order_by(ClassificationRecord.proposed_at.desc()))).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
        tools = await tool_risk_of(db, agent)
    current = next((r for r in sorted(rows, key=lambda r: r.confirmed_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                    if r.status == "confirmed"), None)
    pending = next((r for r in rows if r.status == "proposed"), None)
    return {"current": _record(current, names) if current else None,
            "pending": _record(pending, names) if pending else None,
            "history": [_record(r, names) for r in rows],
            "recorded": {"category": agent.eu_ai_act_category, "riskLevel": agent.risk_level},
            "toolRisk": tools, "canConfirm": can_confirm(user)}


class Answers(BaseModel):
    answers: dict


@router.post("/agents/{agent_id}/classification/suggest")
async def suggest(agent_id: str, body: Answers, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        tools = await tool_risk_of(db, agent)
    return {**cls.suggest(body.answers, tools["class"], tools["source"]), "missing": cls.missing_answers(body.answers)}


class ClassifyBody(BaseModel):
    answers: dict
    confirm: bool = False
    category: str | None = None
    riskLevel: str | None = None
    note: str = ""


def _check_result(category: str, level: str, sug: dict, note: str) -> None:
    if category not in cls.CATEGORIES or level not in cls.LEVELS:
        raise HTTPException(status_code=422, detail=f"Category must be one of {', '.join(cls.CATEGORIES)} and risk level one of {', '.join(cls.LEVELS)}.")
    if cls.is_lower(category, level, sug["category"], sug["riskLevel"]) and len(note.strip()) < cls.MIN_NOTE_WHEN_LOWER:
        raise HTTPException(status_code=422, detail=f"The result is below the suggestion ({sug['category']}, {sug['riskLevel']}). "
                            f"Say why in the note, in at least {cls.MIN_NOTE_WHEN_LOWER} characters.")


async def _apply(db, agent: Agent, rec: ClassificationRecord, actor: str) -> None:
    for old in (await db.execute(select(ClassificationRecord).where(
            ClassificationRecord.agent_id == agent.id, ClassificationRecord.id != rec.id,
            ClassificationRecord.status.in_(("confirmed", "proposed"))))).scalars():
        old.status = "replaced"
    before = {"category": agent.eu_ai_act_category, "riskLevel": agent.risk_level}
    agent.eu_ai_act_category, agent.risk_level = rec.category, rec.risk_level
    db.add(AuditLog(org_id=agent.org_id or "org-default", actor=actor, action="classification.confirm", entity_type="agent", entity_id=agent.id,
                    changes={"before": before, "after": {"category": rec.category, "riskLevel": rec.risk_level},
                             "suggested": {"category": rec.suggested_category, "riskLevel": rec.suggested_risk_level},
                             **({"reason": rec.note} if rec.note else {})}))


@router.post("/agents/{agent_id}/classification")
async def classify(agent_id: str, body: ClassifyBody, user=Depends(require_update)):
    """Save the answers. With confirm=true (and a role that may confirm) the result
    becomes the agent's classification at once; otherwise it waits as a proposal."""
    missing = cls.missing_answers(body.answers)
    if missing:
        raise HTTPException(status_code=422, detail=f"Answer every question first. Missing: {', '.join(missing)}.")
    if body.confirm and not can_confirm(user):
        raise HTTPException(status_code=403, detail="Your role cannot confirm a classification. Save it as a proposal: an Architect Steward, "
                            "a Data Protection Officer or a Registry Admin confirms it.")
    actor = user.get("user_id", "unknown")
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        tools = await tool_risk_of(db, agent)
        sug = cls.suggest(body.answers, tools["class"], tools["source"])
        category, level = body.category or sug["category"], body.riskLevel or sug["riskLevel"]
        _check_result(category, level, sug, body.note)
        rec = ClassificationRecord(id=f"cls-{uuid.uuid4().hex[:12]}", agent_id=agent_id, answers=body.answers,
                                   suggested_category=sug["category"], suggested_risk_level=sug["riskLevel"], reasons=sug["reasons"],
                                   category=category, risk_level=level, note=body.note.strip() or None,
                                   proposed_by=actor, proposed_at=now, status="proposed")
        db.add(rec)
        await db.flush()
        if body.confirm:
            rec.status, rec.confirmed_by, rec.confirmed_at = "confirmed", actor, now
            await _apply(db, agent, rec, actor)
        else:
            for old in (await db.execute(select(ClassificationRecord).where(
                    ClassificationRecord.agent_id == agent_id, ClassificationRecord.id != rec.id,
                    ClassificationRecord.status == "proposed"))).scalars():
                old.status = "replaced"
            db.add(AuditLog(org_id=agent.org_id or "org-default", actor=actor, action="classification.propose", entity_type="agent",
                            entity_id=agent_id, changes={"category": category, "riskLevel": level}))
        names = dict((await db.execute(select(User.id, User.name))).all())
        return _record(rec, names)


class ConfirmBody(BaseModel):
    category: str | None = None
    riskLevel: str | None = None
    note: str = ""


@router.post("/agents/{agent_id}/classification/{record_id}/confirm")
async def confirm(agent_id: str, record_id: str, body: ConfirmBody, user=Depends(require_update)):
    if not can_confirm(user):
        raise HTTPException(status_code=403, detail="Your role cannot confirm a classification. An Architect Steward, "
                            "a Data Protection Officer or a Registry Admin confirms it.")
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        rec = await db.get(ClassificationRecord, record_id)
        if agent is None or rec is None or rec.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Classification not found")
        if rec.status != "proposed":
            raise HTTPException(status_code=409, detail="Only a proposal waiting for confirmation can be confirmed.")
        sug = {"category": rec.suggested_category, "riskLevel": rec.suggested_risk_level}
        category, level = body.category or rec.category, body.riskLevel or rec.risk_level
        note = body.note.strip() or rec.note or ""
        _check_result(category, level, sug, note)
        rec.category, rec.risk_level, rec.note = category, level, note or None
        rec.status, rec.confirmed_by, rec.confirmed_at = "confirmed", actor, datetime.now(timezone.utc)
        await _apply(db, agent, rec, actor)
        names = dict((await db.execute(select(User.id, User.name))).all())
        return _record(rec, names)


# ── Approved tool list ───────────────────────────────────────────────────────

@router.get("/tools/approved")
async def approved_tools(_=Depends(require_read)):
    async with get_db_session() as db:
        rows = (await db.execute(select(ApprovedTool).order_by(ApprovedTool.name))).scalars().all()
        agents = [_agent_tools(a) for a in (await db.execute(select(Agent))).scalars()]
    listed = [{"name": t.name, "risk_class": t.risk_class} for t in rows]
    used = {}
    for a in agents:
        for t in tool_risk.declared(a):
            used.setdefault(tool_risk.key(t["name"]), []).append(a["name"])
    return {"tools": [{**_tool_row(t), "usedBy": used.get(tool_risk.key(t.name), [])} for t in rows],
            "candidates": tool_risk.candidates(agents, listed),
            "kinds": [{"value": k, "label": v} for k, v in tool_risk.KIND_LABELS.items()], "classes": list(tool_risk.LEVELS)}


class ToolBody(BaseModel):
    name: str | None = None
    kind: str | None = None
    riskClass: str | None = None
    note: str | None = None


def _check_tool(body: ToolBody) -> None:
    if body.riskClass is not None and body.riskClass not in tool_risk.LEVELS:
        raise HTTPException(status_code=422, detail="The risk class must be LOW, MEDIUM or HIGH.")
    if body.kind is not None and body.kind not in tool_risk.KIND_LABELS:
        raise HTTPException(status_code=422, detail=f"The kind must be one of {', '.join(tool_risk.KIND_LABELS)}.")


@router.post("/tools/approved")
async def add_tool(body: ToolBody, user=Depends(require_admin)):
    _check_tool(body)
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(status_code=422, detail="Enter the tool's name as agents declare it.")
    async with get_db_session() as db:
        existing = [t for t in (await db.execute(select(ApprovedTool))).scalars() if tool_risk.key(t.name) == tool_risk.key(name)]
        if existing:
            raise HTTPException(status_code=409, detail=f"{existing[0].name} is already on the list.")
        t = ApprovedTool(id=f"tool-{uuid.uuid4().hex[:10]}", name=name, kind=body.kind or "mcp", risk_class=body.riskClass or "MEDIUM",
                         note=(body.note or "").strip() or None, added_by=user.get("user_id"), created_at=datetime.now(timezone.utc))
        db.add(t)
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="tool.approve", entity_type="tool", entity_id=t.id,
                        changes={"name": name, "riskClass": t.risk_class, "kind": t.kind}))
        await db.flush()
        return _tool_row(t)


@router.put("/tools/approved/{tool_id}")
async def update_tool(tool_id: str, body: ToolBody, user=Depends(require_admin)):
    _check_tool(body)
    async with get_db_session() as db:
        t = await db.get(ApprovedTool, tool_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Tool not found")
        before = {"riskClass": t.risk_class, "kind": t.kind, "note": t.note}
        if body.riskClass is not None:
            t.risk_class = body.riskClass
        if body.kind is not None:
            t.kind = body.kind
        if body.note is not None:
            t.note = body.note.strip() or None
        t.updated_at = datetime.now(timezone.utc)
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="tool.update", entity_type="tool", entity_id=t.id,
                        changes={"name": t.name, "before": before, "after": {"riskClass": t.risk_class, "kind": t.kind, "note": t.note}}))
        await db.flush()
        return _tool_row(t)


@router.delete("/tools/approved/{tool_id}")
async def remove_tool(tool_id: str, user=Depends(require_admin)):
    async with get_db_session() as db:
        t = await db.get(ApprovedTool, tool_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Tool not found")
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="tool.remove", entity_type="tool", entity_id=t.id,
                        changes={"name": t.name, "riskClass": t.risk_class}))
        await db.delete(t)
    return {"status": "removed"}


@router.get("/agents/{agent_id}/tools")
async def agent_tools(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return await tool_risk_of(db, agent)
