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


async def _agent_names() -> dict:
    """{agent id: name} of the agents this request may see."""
    async with get_db_session() as db:
        return {i: n for i, n in (await db.execute(select(Agent.id, Agent.name))).all()}


@router.get("/approvals")
async def approvals(user=Depends(require_read)):
    """Pending access requests (oldest first: longest waiting), gates in
    review (oldest first) and unregistered AI found by discovery (most
    confident first)."""
    me = user.get("user_id", "unknown")
    async with get_db_session() as db:
        requests = (await db.execute(
            # The join lets the demo-agent filter (db/scope.py) apply here too.
            select(AgentAccessRequest).join(Agent, Agent.id == AgentAccessRequest.agent_id)
            .where(AgentAccessRequest.status == "pending")
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
    # Ranked: open critical and high findings first, then risk tier, then the longest wait.
    from datetime import date as _date
    from api.auth import ROLES
    from governance.gate_policy import effective_risk_level
    from db.models import AgentRisk, User

    sla = get_settings().review_sla_days
    today = datetime.utcnow().date()
    async with get_db_session() as db:
        open_risks = (await db.execute(select(AgentRisk.agent_id, AgentRisk.severity).where(
            AgentRisk.status.in_(("open", "acknowledged", "mitigating"))))).all()
        users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    names = {u.id: u.name for u in users}
    severe: dict[str, dict] = {}
    for aid, sev in open_risks:
        bucket = severe.setdefault(aid, {"CRITICAL": 0, "HIGH": 0})
        if sev in bucket:
            bucket[sev] += 1
    tier_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    def deciders(gate: str) -> dict:
        holders = [u for u in users if gate in ROLES.get(u.role, {}).get("gates", set()) and u.role != "Registry Admin"]
        here = [u.name for u in holders if not (u.away_until and u.away_until >= today)]
        away = [{"name": u.name, "until": u.away_until.isoformat(), "deputy": names.get(u.deputy_user_id)}
                for u in holders if u.away_until and u.away_until >= today]
        return {"available": here, "away": away}

    gates = []
    for g, a in reviews:
        since = as_utc(g.updated_at).date() if g.updated_at else None
        waited = (today - since).days if since else None
        s = severe.get(a.id, {"CRITICAL": 0, "HIGH": 0})
        tier = effective_risk_level(a.risk_level, a.eu_ai_act_category)
        gates.append({
            "agentId": a.id, "agentName": a.name, "agentStage": a.lifecycle_stage,
            "gate": g.gate, "gateLabel": GATES.get(g.gate, g.gate), "reviewerRole": REVIEWER_ROLES.get(g.gate),
            "reviewer": g.reviewer, "since": _iso(g.updated_at),
            "criticalFindings": s["CRITICAL"], "highFindings": s["HIGH"], "riskTier": tier,
            "daysWaiting": waited, "overdue": bool(waited is not None and waited > sla), "slaDays": sla,
            "deciders": deciders(g.gate),
        })
    gates.sort(key=lambda x: (-x["criticalFindings"], -x["highFindings"], tier_rank.get(x["riskTier"], 1), -(x["daysWaiting"] or 0)))
    # Classification proposals wait for an Architect Steward, Data Protection Officer or Registry Admin.
    from db.models import ClassificationRecord
    async with get_db_session() as db:
        proposals = (await db.execute(select(ClassificationRecord, Agent).join(Agent, Agent.id == ClassificationRecord.agent_id)
                                      .where(ClassificationRecord.status == "proposed")
                                      .order_by(ClassificationRecord.proposed_at))).all()
    classifications = [{
        "id": r.id, "agentId": a.id, "agentName": a.name, "category": r.category, "riskLevel": r.risk_level,
        "proposedBy": names.get(r.proposed_by, r.proposed_by), "since": _iso(r.proposed_at),
        "daysWaiting": (today - as_utc(r.proposed_at).date()).days if r.proposed_at else None,
    } for r, a in proposals]
    by_name = {n: i for i, n in (await _agent_names()).items()} if discoveries else {}
    found = [{
        "id": d.id, "agentId": by_name.get(d.suspected_name), "suspectedName": d.suspected_name, "suspectedDept": d.suspected_dept,
        "suspectedType": d.suspected_type, "source": d.source, "confidence": d.confidence,
        "signal": d.signal, "shadowAiRisk": d.shadow_ai_risk, "firstSeen": _iso(d.first_seen),
    } for d in discoveries]
    return {
        "accessRequests": access, "reviews": gates, "classifications": classifications, "discoveries": found,
        "selfApprovalAllowed": get_settings().allow_self_approval,
        "counts": {"accessRequests": len(access), "reviews": len(gates), "classifications": len(classifications),
                   "discoveries": len(found), "total": len(access) + len(gates) + len(classifications) + len(found)},
    }



DECISION_ACTIONS = ("gate_update", "access_approve", "access_reject", "access_revoke", "waiver.sign", "exception_create",
                    "stage_change", "discovery.dismiss", "discovery.merge", "classification.confirm", "retirement.finish",
                    "ownership.transfer")


@router.get("/approvals/history")
async def approvals_history(limit: int = 50, _=Depends(require_read)):
    """Decisions already made: who decided what, when, and why when a reason was given."""
    from db.models import AuditLog, User
    from governance.audit_view import ACTION_LABELS, actor_label, summary_of

    async with get_db_session() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.action.in_(DECISION_ACTIONS))
                                 .order_by(AuditLog.id.desc()).limit(max(1, min(limit, 200))))).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
        agents = dict((await db.execute(select(Agent.id, Agent.name))).all())
    out = []
    for r in rows:
        if r.action == "gate_update" and ((r.changes or {}).get("after") or {}).get("status") not in ("Approved", "Approved with Conditions", "Changes Requested", "In Review"):
            continue
        out.append({"at": _iso(r.created_at), "actor": actor_label(r.actor, names), "action": ACTION_LABELS.get(r.action, r.action),
                    "agentId": r.entity_id if r.entity_type == "agent" else None, "agentName": agents.get(r.entity_id),
                    "summary": summary_of(r.action, r.changes)})
    return {"rows": out}
