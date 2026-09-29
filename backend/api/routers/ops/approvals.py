"""Approvals inbox: everything across the registry that is waiting for
someone's decision, in one place, so an approver does not have to open
agents one by one to find it.

Read-only. Every decision still goes through the endpoint that owns it —
access requests through the Integrate API, gates on the agent's Governance
tab, discoveries on the Governance page — so their rules (no approving your
own request, a note to reject, gate evidence) apply unchanged."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.auth import require_read
from db.base import get_db_session
from db.models import Agent, AgentAccessRequest, Discovery, GovernanceReview
from governance.gate_policy import GATES, REVIEWER_ROLES
from orchestrations.risk_scan import as_utc
from services import reuse_repo
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Approvals"])

# A gate in this status is waiting on its reviewer, not on the owner.
AWAITING_REVIEWER = "In Review"


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat() if isinstance(value, datetime) else value.isoformat()


@router.get("/approvals")
async def approvals(user=Depends(require_read)):
    """Pending access requests (oldest first: longest waiting), gates in
    review (oldest first) and unregistered AI found by discovery (most
    confident first)."""
    me = user.get("user_id", "unknown")
    async with get_db_session() as db:
        requests = (await db.execute(
            select(AgentAccessRequest).where(AgentAccessRequest.status == "pending")
            .order_by(AgentAccessRequest.created_at, AgentAccessRequest.id)
        )).scalars().all()
        reviews = (await db.execute(
            select(GovernanceReview, Agent).join(Agent, Agent.id == GovernanceReview.agent_id)
            .where(GovernanceReview.status == AWAITING_REVIEWER, Agent.lifecycle_stage != "Deprecated")
            .order_by(GovernanceReview.updated_at, Agent.name, GovernanceReview.gate)
        )).all()
        discoveries = (await db.execute(
            select(Discovery).where(Discovery.status == "pending")
            .order_by(Discovery.confidence.desc(), Discovery.suspected_name)
        )).scalars().all()
        # Whether each requested agent is certified for reuse: what an
        # approver most needs to know before letting a team depend on it.
        requested = (await db.execute(
            select(Agent).where(Agent.id.in_({r.agent_id for r in requests}))
            .options(selectinload(Agent.governance_reviews))
        )).scalars().all() if requests else []
        certs = await reuse_repo.certifications(db, requested) if requested else {}
    agents = {a.id: a for a in requested}

    access = [{
        "id": r.id, "agentId": r.agent_id,
        "agentName": agents[r.agent_id].name if r.agent_id in agents else r.agent_id,
        "agentStage": agents[r.agent_id].lifecycle_stage if r.agent_id in agents else None,
        "certified": bool(certs.get(r.agent_id, {}).get("certified")),
        "team": r.team, "purpose": r.purpose,
        "requesterId": r.requester_id, "requesterName": r.requester_name,
        "createdAt": _iso(r.created_at),
        # Approving your own request is refused unless ALLOW_SELF_APPROVAL (testing).
        "mine": r.requester_id == me,
    } for r in requests]
    gates = [{
        "agentId": a.id, "agentName": a.name, "agentStage": a.lifecycle_stage,
        "gate": g.gate, "gateLabel": GATES.get(g.gate, g.gate), "reviewerRole": REVIEWER_ROLES.get(g.gate),
        "reviewer": g.reviewer, "since": _iso(g.updated_at),
    } for g, a in reviews]
    found = [{
        "id": d.id, "suspectedName": d.suspected_name, "suspectedDept": d.suspected_dept,
        "suspectedType": d.suspected_type, "source": d.source, "confidence": d.confidence,
        "signal": d.signal, "shadowAiRisk": d.shadow_ai_risk, "firstSeen": _iso(d.first_seen),
    } for d in discoveries]
    return {
        "accessRequests": access, "reviews": gates, "discoveries": found,
        "selfApprovalAllowed": get_settings().allow_self_approval,
        "counts": {"accessRequests": len(access), "reviews": len(gates), "discoveries": len(found),
                   "total": len(access) + len(gates) + len(found)},
    }
