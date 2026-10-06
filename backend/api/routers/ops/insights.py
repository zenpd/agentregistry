"""Insight agents: run one, read the latest, say whether it helped.

Every insight is AI-written and labelled as such. It reads registry facts
through read-only tools and changes nothing: no route here, and no tool an
agent can call, alters a record, a review, a risk or a stage. (Filling in a
record from evidence is a separate, rule-bound step: services/autofill.py.)"""
from __future__ import annotations

import json
import secrets
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from agents.insights import content
from agents.insights.runtime import InsightSpec, fence, run_insight
from agents.insights.specs import BY_TAB, CONTENT_KINDS, SPECS
from agents.insights.tools import RefBook, _clip
from api.auth import require_read, require_update
from api.routers.ops import integrate
from db.base import get_db_session
from db.models import Agent, AuditLog, ContentAuditOptIn, Insight, InsightFeedback
from orchestrations.governance_checks import AGENT_CHANGE_ACTIONS
from orchestrations.risk_scan import as_utc
from services.audit import log_audit_event

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Insights"])

# Which automatic updates each tab mentions (None: all of them). A tab lists only what it shows.
TAB_FIELDS: dict[str, tuple[str, ...] | None] = {
    "overview": None, "governance": None,
    "diagram": ("mcp_servers", "knowledge_bases", "model_name"),
    "tokenomics": ("model_name",),
    "integrate": ("description", "capabilities", "inputs", "outputs", "api_endpoint"),
    "revenue": (), "risk": (),
}
# Which of the things only a person can provide each tab mentions (None: all of them).
TAB_PERSON: dict[str, tuple[str, ...] | None] = {
    "overview": None, "governance": None, "diagram": (),
    "tokenomics": ("budget",), "revenue": ("value", "business_outcome", "budget"),
    "risk": ("owner", "reviews"), "integrate": ("owner", "sla"),
}
RUNS_PER_MINUTE = 20      # a tab runs up to two insights at once
KEEP_PER_KIND = 5          # older runs of the same insight for the same agent are removed
RETRY_FAILED_AFTER = timedelta(minutes=10)
DRAFT_KINDS = ("registration_coach", "duplicates")


def _spec(kind: str) -> InsightSpec:
    spec = SPECS.get(kind)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown insight '{kind}'")
    return spec


def _to_dict(row: Insight, feedback: Optional[InsightFeedback] = None) -> dict:
    spec = SPECS.get(row.kind)
    return {
        "id": row.id, "kind": row.kind, "title": spec.title if spec else row.kind, "agentId": row.agent_id,
        "subject": row.subject, "status": row.status, "output": row.output, "refs": row.refs or {},
        "toolsUsed": row.tools_used or [], "checks": row.checks or {}, "model": row.model,
        "promptVersion": row.prompt_version, "steps": row.steps, "durationMs": row.duration_ms,
        "createdAt": as_utc(row.created_at).isoformat() if row.created_at else None,
        "tags": spec.tags if spec else {},
        "feedback": {"verdict": feedback.verdict, "note": feedback.note} if feedback else None,
    }


async def _agent_or_404(agent_id: str) -> Agent:
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _store(result: dict, *, agent_id: Optional[str], subject: Optional[str], actor: str,
                 started: Optional[datetime] = None) -> dict:
    """started: when the run began reading. The insight is dated from then, so a record change made
    while it was being written still marks it as out of date."""
    row = Insight(
        created_at=started or datetime.now(timezone.utc),
        id=secrets.token_hex(12), org_id="org-default", agent_id=agent_id, kind=result["kind"],
        subject=(subject or None) and subject[:500], status=result["status"],
        output=result.get("output") or ({"summary": result.get("reason", ""), "findings": [], "notDetermined": []}
                                        if result["status"] != "ok" else None),
        refs=result.get("refs"), tools_used=result.get("toolsUsed"), checks={**(result.get("checks") or {}), **(result.get("meta") or {})},
        model=result.get("model"), prompt_version=result.get("promptVersion"), steps=result.get("steps", 0),
        duration_ms=result.get("durationMs", 0), created_by=actor,
    )
    async with get_db_session() as db:
        db.add(row)
        await db.flush()
        await db.refresh(row)
        out = _to_dict(row)
        if agent_id:
            old = list((await db.execute(select(Insight.id).where(Insight.agent_id == agent_id, Insight.kind == row.kind)
                                         .order_by(Insight.created_at.desc()).offset(KEEP_PER_KIND))).scalars())
            if old:
                await db.execute(delete(InsightFeedback).where(InsightFeedback.insight_id.in_(old)))
                await db.execute(delete(Insight).where(Insight.id.in_(old)))
    await log_audit_event(actor=actor, action="insight.run", entity_type="agent" if agent_id else "registry",
                          entity_id=agent_id or "all",
                          changes={"kind": result["kind"], "status": result["status"], "insightId": out["id"]})
    return out


def _limit(actor: str) -> None:
    if not integrate._within_rate_limit(actor, "insights", RUNS_PER_MINUTE):
        raise HTTPException(status_code=429, detail=f"At most {RUNS_PER_MINUTE} insights per minute")


@router.get("/insights/catalog")
async def catalog(_=Depends(require_read)):
    """The insights that exist, with the question each answers and where it appears."""
    return {"insights": [{"kind": s.kind, "title": s.title, "question": s.question, "where": s.where, "scope": s.scope,
                          "readsContent": s.kind in ("evidence_review", "trace_audit"), "tags": s.tags}
                         for s in SPECS.values()], "byTab": BY_TAB}


async def run_agent_insight(agent: Agent, kind: str, *, subject: Optional[str], actor: str) -> dict:
    """Runs one insight for one agent and stores it. Used by the page (a person
    asked) and by the daily job. Raises 409 when trace text is not switched on."""
    spec = _spec(kind)
    agent_id = agent.id
    book = RefBook()
    request = f"The agent under investigation is '{agent.name}' (id {agent.id})."
    if subject:
        request += f" Subject: {_clip(subject, 200)}."
    data_block, meta = "", {}

    if kind == "evidence_review":
        data_block, meta = await content.evidence_block(agent_id, subject if subject in ("arb", "security", "dp") else None, book)
        if not meta["documents"]:
            return await _store({"kind": kind, "status": "nothing_to_read", "meta": meta, "promptVersion": spec.version,
                                 "reason": "No evidence links are attached to this agent's reviews, so there is nothing to read."},
                                agent_id=agent_id, subject=subject, actor=actor)
        if not meta["readable"]:
            return await _store({"kind": kind, "status": "nothing_to_read", "meta": meta, "promptVersion": spec.version,
                                 "reason": ("None of the attached evidence could be read, so nothing was judged. "
                                            + " ".join(f"{u}." for u in meta["unreadable"][:5])
                                            + " Evidence behind a sign-in, or a file that is not a web page or text, cannot be read here.")},
                                agent_id=agent_id, subject=subject, actor=actor)
    elif kind == "trace_audit":
        async with get_db_session() as db:
            opted = (await db.execute(select(ContentAuditOptIn).where(ContentAuditOptIn.agent_id == agent_id))).scalar_one_or_none()
        if opted is None:
            raise HTTPException(status_code=409, detail="Reading trace text is off for this agent. Its owner has to switch it on first.")
        data_block, meta = await content.trace_block(agent_id, book)
        if meta["status"] != "ok":
            return await _store({"kind": kind, "status": meta["status"], "meta": meta, "promptVersion": spec.version,
                                 "reason": meta.get("reason", "")}, agent_id=agent_id, subject=subject, actor=actor)

    started = datetime.now(timezone.utc)
    result = await run_insight(spec, agent_id=agent_id, request=request, data_block=data_block, book=book)
    result["meta"] = meta
    return await _store(result, agent_id=agent_id, subject=subject, actor=actor, started=started)


@router.get("/agents/{agent_id}/insights")
async def latest_for_tab(agent_id: str, tab: str, _=Depends(require_read)):
    """The latest run of each insight shown on one tab of the agent page, in display order."""
    kinds = BY_TAB.get(tab)
    if kinds is None:
        raise HTTPException(status_code=404, detail=f"No insights are shown on '{tab}'")
    agent = await _agent_or_404(agent_id)
    out = []
    async with get_db_session() as db:
        # When the record itself last changed, by a person or by the registry.
        changed_at = (await db.execute(select(func.max(AuditLog.created_at)).where(
            AuditLog.entity_type == "agent", AuditLog.entity_id == agent_id, AuditLog.action.in_((*AGENT_CHANGE_ACTIONS, "stage_change", "offboard"))))).scalar()
        for kind in kinds:
            spec = SPECS[kind]
            row = (await db.execute(select(Insight).where(Insight.agent_id == agent_id, Insight.kind == kind)
                                    .order_by(Insight.created_at.desc()).limit(1))).scalar_one_or_none()
            feedback = None
            if row is not None:
                feedback = (await db.execute(select(InsightFeedback).where(InsightFeedback.insight_id == row.id)
                                             .order_by(InsightFeedback.created_at.desc()).limit(1))).scalar_one_or_none()
            # Rewritten on the next visit when it was written by older instructions, or before the
            # record last changed: it would describe a record that is no longer there.
            outdated = row is not None and kind not in CONTENT_KINDS and changed_at is not None \
                and as_utc(row.created_at) < as_utc(changed_at)
            # A run that could not reach the model is tried again on a later visit, not on every one.
            failed = row is not None and row.status in ("unavailable", "error") \
                and as_utc(row.created_at) < datetime.now(timezone.utc) - RETRY_FAILED_AFTER
            out.append({"kind": kind, "title": spec.title, "question": spec.question,
                        "readsContent": kind in CONTENT_KINDS, "insight": _to_dict(row, feedback) if row else None,
                        "stale": bool(row is not None and (row.prompt_version != spec.version or outdated or failed)),
                        "recordChangedSince": bool(outdated)})
        opted = (await db.execute(select(ContentAuditOptIn).where(ContentAuditOptIn.agent_id == agent_id))).scalar_one_or_none()
    from api.routers.ops import autofill as autofill_api
    state = await autofill_api.state_for(agent)
    shown = TAB_FIELDS.get(tab)
    state["updates"] = [u for u in state["updates"] if shown is None or u["field"] in shown]
    wanted = TAB_PERSON.get(tab)
    state["needsPerson"] = [n for n in state["needsPerson"] if wanted is None or n["key"] in wanted]
    return {"agentId": agent_id, "tab": tab, "insights": out, "traceTextAllowed": opted is not None,
            "autoUpdates": {k: state[k] for k in ("updates", "due", "running", "checkedAt", "evidence", "needsPerson")}}


class RunBody(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=300, description="e.g. a review (arb, security, dp)")


@router.post("/agents/{agent_id}/insights/{kind}/run")
async def run_for_agent(agent_id: str, kind: str, body: Optional[RunBody] = None, user=Depends(require_update)):
    spec = _spec(kind)
    if spec.scope != "agent":
        raise HTTPException(status_code=422, detail=f"'{kind}' is not run for one agent")
    agent = await _agent_or_404(agent_id)
    actor = user.get("user_id", "unknown")
    _limit(actor)
    return await run_agent_insight(agent, kind, subject=(body.subject if body else None) or None, actor=actor)


@router.get("/agents/{agent_id}/insights/{kind}")
async def latest_for_agent(agent_id: str, kind: str, _=Depends(require_read)):
    _spec(kind)
    async with get_db_session() as db:
        row = (await db.execute(select(Insight).where(Insight.agent_id == agent_id, Insight.kind == kind)
                                .order_by(Insight.created_at.desc()).limit(1))).scalar_one_or_none()
        if row is None:
            return {"insight": None}
        feedback = (await db.execute(select(InsightFeedback).where(InsightFeedback.insight_id == row.id)
                                     .order_by(InsightFeedback.created_at.desc()).limit(1))).scalar_one_or_none()
        return {"insight": _to_dict(row, feedback)}


class DraftBody(BaseModel):
    name: str = Field("", max_length=255)
    description: str = Field("", max_length=4000)
    business_outcome: str = Field("", max_length=1000)
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    ai_type: str = Field("", max_length=80)
    owner_recorded: bool = False
    value_amount: float = 0
    inputs: list[str] = Field(default_factory=list, max_length=30)
    outputs: list[str] = Field(default_factory=list, max_length=30)
    model_name: str = Field("", max_length=120)
    eu_ai_act_category: str = Field("", max_length=80)


@router.post("/insights/draft/{kind}")
async def run_for_draft(kind: str, body: DraftBody, user=Depends(require_update)):
    """Coach or duplicate check for a registration that is still being typed. Nothing is stored against an agent."""
    if kind not in DRAFT_KINDS:
        raise HTTPException(status_code=422, detail=f"'{kind}' cannot be run on a draft")
    if not (body.name.strip() or body.description.strip()):
        raise HTTPException(status_code=422, detail="Enter a name or a description first")
    spec = _spec(kind)
    if kind == "duplicates":
        spec = replace(spec, tools=["list_agent_catalog"], scope="draft")
    actor = user.get("user_id", "unknown")
    _limit(actor)
    book = RefBook()
    draft = {"ref": book.ref("draft", "new", label="This draft"), "name": _clip(body.name, 255),
             "description": _clip(body.description, 3000), "businessOutcome": _clip(body.business_outcome, 800),
             "capabilities": [_clip(c, 120) for c in body.capabilities], "aiType": body.ai_type,
             "ownerRecorded": body.owner_recorded, "declaredMonthlyValueUsd": body.value_amount,
             "inputs": [_clip(i, 120) for i in body.inputs], "outputs": [_clip(o, 120) for o in body.outputs],
             "declaredModel": body.model_name, "declaredEuAiActTier": body.eu_ai_act_category or None}
    book.note_numbers(draft)
    result = await run_insight(spec, agent_id=None, request="The subject is the draft registration below.",
                               data_block=fence("draft registration", json.dumps(draft)), book=book)
    return await _store(result, agent_id=None, subject=f"draft: {body.name[:200]}", actor=actor)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=600)


@router.post("/insights/ask")
async def ask(body: AskBody, user=Depends(require_update)):
    actor = user.get("user_id", "unknown")
    _limit(actor)
    result = await run_insight(SPECS["ask"], agent_id=None, request="The person's question is in the data block.",
                               data_block=fence("question from a signed-in user", body.question.strip()))
    return await _store(result, agent_id=None, subject=body.question.strip(), actor=actor)


class FeedbackBody(BaseModel):
    verdict: Literal["useful", "not_useful"]
    note: Optional[str] = Field(default=None, max_length=1000)


@router.post("/insights/{insight_id}/feedback")
async def feedback(insight_id: str, body: FeedbackBody, user=Depends(require_update)):
    async with get_db_session() as db:
        if (await db.execute(select(Insight.id).where(Insight.id == insight_id))).scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Insight not found")
        db.add(InsightFeedback(id=secrets.token_hex(8), insight_id=insight_id, verdict=body.verdict,
                               note=(body.note or "").strip() or None, actor=user.get("user_id", "unknown")))
    return {"status": "saved"}


# ── Permission to read trace text (per agent, off by default) ───────────────

@router.get("/agents/{agent_id}/content-audit")
async def content_audit_state(agent_id: str, _=Depends(require_read)):
    await _agent_or_404(agent_id)
    async with get_db_session() as db:
        row = (await db.execute(select(ContentAuditOptIn).where(ContentAuditOptIn.agent_id == agent_id))).scalar_one_or_none()
    return {"agentId": agent_id, "enabled": row is not None, "enabledBy": row.opted_by if row else None,
            "enabledAt": as_utc(row.created_at).isoformat() if row and row.created_at else None,
            "sampleSize": content.TRACE_SAMPLE}


class OptInBody(BaseModel):
    enabled: bool


@router.put("/agents/{agent_id}/content-audit")
async def set_content_audit(agent_id: str, body: OptInBody, user=Depends(require_update)):
    """Switches reading of this agent's trace text on or off. Recorded in the audit log either way."""
    await _agent_or_404(agent_id)
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        await db.execute(delete(ContentAuditOptIn).where(ContentAuditOptIn.agent_id == agent_id))
        if body.enabled:
            db.add(ContentAuditOptIn(agent_id=agent_id, opted_by=actor))
    await log_audit_event(actor=actor, action="content_audit.opt_in" if body.enabled else "content_audit.opt_out",
                          entity_type="agent", entity_id=agent_id, changes={"enabled": body.enabled})
    return {"agentId": agent_id, "enabled": body.enabled}
