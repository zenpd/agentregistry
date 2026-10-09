"""Governance checks: gathers the facts gate_policy needs for one agent and,
as a job, reports approval expiry and recertification reasons for every
agent. Read-only: it never changes a gate, a stage or a risk (the Risk
engine reads gate states itself)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.base import get_db_session
from db.models import (
    Agent, AgentBudget, AgentRisk, AuditLog, GovernanceException, JobRun, PhoenixConfig,
)
from governance import gate_policy as gp
from services.usage_repo import load_aliases, priced_usage
from shared.config import get_settings

OPEN_RISK_STATUSES = ("open", "acknowledged", "mitigating")
HIGH_SEVERITIES = ("HIGH", "CRITICAL")
PII_RULE_ID = "data_privacy.pii_detected"
# Audit actions that change an agent's declared facts (edit form, adopted
# trace dependencies, confirmed context.md suggestions).
AGENT_CHANGE_ACTIONS = ("update", "adopt_observed_dependencies", "context.suggestion.confirm",
                        "ai.autofill", "ai.autofill.undo")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def review_to_dict(review: Any) -> dict:
    return {
        "gate": review.gate,
        "status": review.status or "Not Submitted",
        "reviewer": review.reviewer,
        "notes": review.notes,
        "conditions": review.conditions,
        "evidence": review.evidence or [],
        "checklist": review.checklist or {},
        "reviewed_at": gp.as_utc(review.reviewed_at),
        "expires_at": gp.as_utc(review.expires_at),
        "approved_snapshot": getattr(review, "approved_snapshot", None),
    }


def exception_to_dict(exc: GovernanceException) -> dict:
    return {
        "id": exc.id, "gate": exc.gate, "reason": exc.reason,
        "expires_at": gp.as_utc(exc.expires_at), "approved_by": exc.approved_by,
        "created_at": gp.as_utc(exc.created_at), "status": exc.status,
        "first_signer": exc.first_signer, "second_signer": exc.second_signer,
        "second_signed_at": gp.as_utc(exc.second_signed_at),
    }


def _open_risk_to_dict(r: AgentRisk) -> dict:
    return {"id": r.id, "rule_id": r.rule_id, "category": r.category, "severity": r.severity,
            "title": r.title, "status": r.status}


def _count_high(risks: list[dict], category: str) -> int:
    return sum(
        1 for r in risks
        if r["category"] == category and (r["severity"] or "").upper() in HIGH_SEVERITIES
        and not gp.is_gate_derived_finding(r["rule_id"], r["title"])
    )


async def _observability_urls(db: AsyncSession, agent: Agent, settings: Any) -> list[str]:
    rows = (await db.execute(select(PhoenixConfig.endpoint))).scalars().all()
    return [u for u in [agent.phoenix_endpoint, settings.phoenix_collector_endpoint, *rows] if u]


async def _risk_scan_run(db: AsyncSession, agent_id: str) -> bool:
    auto = await db.execute(
        select(AgentRisk.id).where(AgentRisk.agent_id == agent_id, AgentRisk.source == "auto").limit(1)
    )
    if auto.first():
        return True
    job = await db.execute(
        select(JobRun.id).where(
            JobRun.job == "risk_scan", JobRun.status.in_(("ok", "partial")),
            or_(JobRun.agent_id == agent_id, JobRun.agent_id.is_(None)),
        ).limit(1)
    )
    return job.first() is not None


async def _auto_filled(db: AsyncSession, agent: Agent) -> dict[str, str]:
    from services.autofill import auto_filled_fields
    return await auto_filled_fields(db, agent)


async def _material_changes(db: AsyncSession, agent_id: str) -> list[dict]:
    rows = (await db.execute(
        select(AuditLog.created_at, AuditLog.changes).where(
            AuditLog.entity_type == "agent", AuditLog.entity_id == agent_id,
            AuditLog.action.in_(AGENT_CHANGE_ACTIONS),
        )
    )).all()
    out = []
    for created_at, changes in rows:
        fields = gp.material_fields(changes)
        if fields:
            out.append({"at": gp.as_utc(created_at), "fields": sorted(fields)})
    return out


async def load_state(db: AsyncSession, agent: Agent, now: datetime) -> dict:
    """Everything gate_policy needs about one agent. `agent` must have its
    governance_reviews loaded."""
    settings = get_settings()
    risk_tier = gp.effective_risk_level(agent.risk_level, agent.eu_ai_act_category)

    risks = [_open_risk_to_dict(r) for r in (await db.execute(
        select(AgentRisk).where(AgentRisk.agent_id == agent.id, AgentRisk.status.in_(OPEN_RISK_STATUSES))
    )).scalars().all()]
    scan_run = await _risk_scan_run(db, agent.id)
    pii_open = any(r["rule_id"] == PII_RULE_ID or (r["title"] or "").startswith("PII detected") for r in risks)
    pii_detected = True if pii_open else (False if agent.phoenix_project and scan_run else None)

    days = settings.usage_backfill_days
    priced = await priced_usage(db, agent.id, since=now.date() - timedelta(days=days))
    usage = gp.usage_summary(priced["rows"], priced["source"], days) if agent.phoenix_project else None

    all_exceptions = [exception_to_dict(e) for e in (await db.execute(
        select(GovernanceException).where(GovernanceException.agent_id == agent.id)
    )).scalars().all()]
    exceptions = [e for e in all_exceptions if e["status"] in (None, "active")]
    pending_waivers = [e for e in all_exceptions if e["status"] == "pending"]
    budget = (await db.execute(
        select(AgentBudget.monthly_budget_cents).where(AgentBudget.agent_id == agent.id)
    )).scalar_one_or_none()

    facts = {
        "owner": agent.owner, "dept": agent.dept_id, "description": agent.description,
        "business_outcome": agent.business_outcome, "model_name": agent.model_name,
        "model_provider": agent.model_provider, "sla": agent.sla, "api_endpoint": agent.api_endpoint,
        "observability_urls": await _observability_urls(db, agent, settings),
        "enterprise_systems": agent.enterprise_systems or [], "databases": agent.databases or [],
        "knowledge_bases": agent.knowledge_bases or [], "mcp_servers": agent.mcp_servers or [],
        "calls": agent.calls or [], "phoenix_project": agent.phoenix_project,
        "eu_ai_act_category": agent.eu_ai_act_category, "risk_level": agent.risk_level,
        "context_present": bool((agent.context_md or "").strip()),
        "sunset_date": agent.sunset_date,
        "risk_scan_run": scan_run,
        "open_high_security": _count_high(risks, "SECURITY"),
        "open_high_privacy": _count_high(risks, "DATA_PRIVACY"),
        "pii_detected": pii_detected,
        "observed_model": usage["topModel"] if usage else None,
        "model_aliases": await load_aliases(db),
        "material_changes": await _material_changes(db, agent.id),
        "auto_filled": await _auto_filled(db, agent),
        "validity_days": gp.validity_days(risk_tier, settings),
    }
    from governance import lifecycle, templates as tpl

    template = (await tpl.templates())[risk_tier if risk_tier in lifecycle.TIERS else "HIGH"]
    since = await stage_since(db, agent)
    weeks = lifecycle.weeks_in_stage(since, now)
    facts["validity_days"] = template["validityDays"]
    facts["trace_connector_id"] = agent.trace_connector_id
    facts["value_amount"] = agent.value_amount
    facts["capabilities"], facts["inputs"], facts["outputs"] = agent.capabilities or [], agent.inputs or [], agent.outputs or []
    facts["budget"] = bool(budget and budget > 0)
    facts["classification_detail"] = await _classification_detail(db, agent.id)
    facts["classification"] = facts["classification_detail"] is not None
    facts["reviews"] = any((r.status or "Not Submitted") != "Not Submitted" for r in agent.governance_reviews or [])
    from api.routers.ops.evidence import latest as latest_verdict

    verdict = await latest_verdict(db, agent.id)
    facts["assureai"] = {"verdict": verdict.verdict, "completedAt": gp.as_utc(verdict.completed_at).date().isoformat()
                         if verdict.completed_at else None} if verdict else None
    return {
        "assureai_required": await tpl.assureai_required(),
        "stage_since": since, "weeks_in_stage": weeks,
        "stalled": lifecycle.stalled(agent.lifecycle_stage, weeks, await tpl.stall_weeks()),
        "pendingWaivers": gp.unexpired_exceptions(pending_waivers, now),
        "template": template,
        "required": await tpl.required_fields(),
        "facts": facts,
        "reviews": {r.gate: review_to_dict(r) for r in agent.governance_reviews or [] if r.gate in gp.GATES},
        "exceptions": gp.unexpired_exceptions(exceptions, now),
        "budget_set": bool(budget and budget > 0),
        "risk_tier": risk_tier,
        "open_risks": risks,
        "usage": usage,
        # 'seed' = demo rows only; they are never used as governance evidence.
        "usage_source": "phoenix" if usage else ("seed" if priced["source"] == "seed" else "none"),
    }


async def stage_since(db: AsyncSession, agent: Agent) -> datetime | None:
    """When the agent entered its current stage: the latest recorded move into it, else its registration."""
    rows = (await db.execute(select(AuditLog.created_at, AuditLog.changes).where(
        AuditLog.entity_type == "agent", AuditLog.entity_id == agent.id, AuditLog.action == "stage_change",
    ).order_by(AuditLog.created_at.desc()))).all()
    for at, changes in rows:
        if isinstance(changes, dict) and changes.get("to") == agent.lifecycle_stage:
            return gp.as_utc(at)
    return gp.as_utc(agent.created_at)


async def _classification_confirmed(db: AsyncSession, agent_id: str) -> bool:
    """A person confirmed this agent's classification (item 27)."""
    return await _classification_detail(db, agent_id) is not None


async def _classification_detail(db: AsyncSession, agent_id: str) -> dict | None:
    """The latest confirmed classification: category, risk level, who and when."""
    from db.models import ClassificationRecord, User

    row = (await db.execute(select(ClassificationRecord).where(
        ClassificationRecord.agent_id == agent_id, ClassificationRecord.status == "confirmed",
    ).order_by(ClassificationRecord.confirmed_at.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    who = await db.get(User, row.confirmed_by) if row.confirmed_by else None
    return {"category": row.category, "riskLevel": row.risk_level, "by": (who.name if who else row.confirmed_by) or "unknown",
            "on": gp.as_utc(row.confirmed_at).date().isoformat() if row.confirmed_at else "unknown date"}


def recertification(state: dict, now: datetime) -> dict:
    reasons = gp.needs_recertification(state["facts"], state["reviews"], now)
    return {"due": bool(reasons), "reasons": reasons}


async def run_governance_checks(agent_id: str | None = None, trigger: str = "manual") -> dict:
    now = utcnow()
    async with get_db_session() as db:
        stmt = select(Agent).options(selectinload(Agent.governance_reviews)).order_by(Agent.name)
        if agent_id:
            stmt = stmt.where(Agent.id == agent_id)
        agents = (await db.execute(stmt)).scalars().all()
        if agent_id and not agents:
            return {"status": "error", "reason": f"Agent {agent_id} not found"}

        from governance import lifecycle

        results, reopened = [], []
        for agent in agents:
            state = await load_state(db, agent, now)
            gates = {gate: gp.gate_expiry_state(state["reviews"].get(gate), now) for gate in gp.GATES}
            if state.get("weeks_in_stage") is not None and agent.time_in_stage_weeks != state["weeks_in_stage"]:
                agent.time_in_stage_weeks = state["weeks_in_stage"]
            # An approval stops covering a record whose model, tools or systems changed since:
            # the gates the change touches go back to In Review, saying what changed.
            record = {k: getattr(agent, k) for k in lifecycle.STRUCTURAL}
            for review in agent.governance_reviews or []:
                if review.status not in gp.APPROVED_STATUSES or not review.approved_snapshot:
                    continue
                changes = lifecycle.changed_since(review.approved_snapshot, record)
                if changes and review.gate in lifecycle.affected_gates(changes):
                    what = lifecycle.describe(changes)
                    before = review.status
                    review.status, review.expires_at = "In Review", None
                    review.notes = (f"Reopened by the registry on {now.date().isoformat()}: changed since the approval: {what}."
                                    + (f"\n\n{review.notes}" if review.notes else ""))
                    db.add(AuditLog(org_id="org-default", actor="system", action="gate_update", entity_type="agent",
                                    entity_id=agent.id, changes={"gate": review.gate, "path": "registry", "source": "changed_since_approval",
                                                                 "before": {"status": before}, "after": {"status": "In Review"},
                                                                 "changed": [c["field"] for c in changes]}))
                    reopened.append({"agentId": agent.id, "name": agent.name, "gate": review.gate, "what": what})
            results.append({
                "agentId": agent.id, "name": agent.name, "stage": agent.lifecycle_stage,
                "gates": gates, "recertification": recertification(state, now),
                "weeksInStage": state.get("weeks_in_stage"), "stalled": state.get("stalled", False),
            })

    def with_state(state_name: str) -> list[dict]:
        return [{"agentId": r["agentId"], "gate": g} for r in results for g, s in r["gates"].items() if s == state_name]

    return {
        "status": "ok",
        "trigger": trigger,
        "checkedAt": now.isoformat(),
        "agentsChecked": len(results),
        "expired": with_state("expired"),
        "expiring": with_state("expiring"),
        "recertificationDue": [r["agentId"] for r in results if r["recertification"]["due"]],
        "reopened": reopened,
        "stalled": [{"agentId": r["agentId"], "name": r["name"], "stage": r["stage"], "weeks": r["weeksInStage"]} for r in results if r["stalled"]],
        "agents": results,
    }
