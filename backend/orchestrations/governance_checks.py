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
AGENT_CHANGE_ACTIONS = ("update", "adopt_observed_dependencies", "context.suggestion.confirm")


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
    }


def exception_to_dict(exc: GovernanceException) -> dict:
    return {
        "id": exc.id, "gate": exc.gate, "reason": exc.reason,
        "expires_at": gp.as_utc(exc.expires_at), "approved_by": exc.approved_by,
        "created_at": gp.as_utc(exc.created_at),
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

    exceptions = [exception_to_dict(e) for e in (await db.execute(
        select(GovernanceException).where(GovernanceException.agent_id == agent.id)
    )).scalars().all()]
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
        "validity_days": gp.validity_days(risk_tier, settings),
    }
    return {
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

        results = []
        for agent in agents:
            state = await load_state(db, agent, now)
            gates = {gate: gp.gate_expiry_state(state["reviews"].get(gate), now) for gate in gp.GATES}
            results.append({
                "agentId": agent.id, "name": agent.name, "stage": agent.lifecycle_stage,
                "gates": gates, "recertification": recertification(state, now),
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
        "agents": results,
    }
