"""The evidence the compliance packs are checked against, read from the registry:
per agent (record, classification, reviews, checklist, tracing, risks, tools,
versions, AssureAI verdict) and registry-wide (the controls list and the decision chain)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.models import Agent, AgentVersion, ApprovedTool, ClassificationRecord, User
from governance import gate_policy as gp
from governance import lifecycle, tool_risk


def _approved(review: dict | None, now: datetime) -> bool:
    return bool(review) and review.get("status") in gp.APPROVED_STATUSES and gp.gate_expiry_state(review, now) != "expired"


def _ticked(gate: str, item: str, facts: dict, review: dict | None) -> bool:
    for i in gp.evaluate_checklist(gate, facts, (review or {}).get("checklist")):
        if i["id"] == item:
            return i["result"] == "pass"
    return False


async def agent_evidence(db, agent: Agent, now: datetime | None = None) -> dict:
    """{evidence: {key: bool}, classified, category, answers, details: {key: text}}"""
    from api.routers.ops.evidence import latest as latest_verdict
    from governance.economics import load_economics
    from orchestrations import governance_checks as gc

    now = now or datetime.now(timezone.utc)
    state = await gc.load_state(db, agent, now)
    f, reviews = state["facts"], state["reviews"]
    rec = (await db.execute(select(ClassificationRecord).where(ClassificationRecord.agent_id == agent.id, ClassificationRecord.status == "confirmed")
                            .order_by(ClassificationRecord.confirmed_at.desc()).limit(1))).scalar_one_or_none()
    answers = rec.answers if rec else {}
    owner = await db.get(User, agent.owner_user_id) if agent.owner_user_id else None
    tools = tool_risk.tool_class({"mcp_servers": agent.mcp_servers, "enterprise_systems": agent.enterprise_systems,
                                  "databases": agent.databases, "knowledge_bases": agent.knowledge_bases},
                                 [{"name": t.name, "risk_class": t.risk_class} for t in (await db.execute(select(ApprovedTool))).scalars()])
    versions = (await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id).limit(1))).scalar()
    verdict = await latest_verdict(db, agent.id)
    econ = (await load_economics(db, [agent]))[agent.id]
    ev = {
        "owner": lifecycle.filled("owner", f),
        "owner_person": bool(owner and owner.is_active),
        "purpose": lifecycle.filled("description", f),
        "business_outcome": lifecycle.filled("business_outcome", f),
        "value_declared": (agent.value_amount or 0) > 0,
        "classification": rec is not None,
        "not_prohibited": rec is not None and rec.category != "Unacceptable Risk",
        "data_recorded": rec is not None and answers.get("data") in ("none", "personal", "special"),
        "retention_recorded": rec is not None and (answers.get("data") == "none" or bool(answers.get("retention"))),
        "model": lifecycle.filled("model_name", f),
        "dependencies": _ticked("arb", "arb.dependencies", f, reviews.get("arb")),
        "tools_listed": not tools["listEmpty"] and not tools["unlisted"],
        "contract": all(lifecycle.filled(k, f) for k in ("capabilities", "inputs", "outputs", "sla")),
        "tracing": bool(agent.phoenix_project or agent.trace_connector_id),
        "hosting_known": econ["infraSource"] in ("metered", "declared"),
        "risk_scan": bool(f.get("risk_scan_run")),
        "no_high_findings": not f.get("open_high_security") and not f.get("open_high_privacy"),
        "arb_approved": _approved(reviews.get("arb"), now),
        "security_approved": _approved(reviews.get("security"), now),
        "dp_approved": _approved(reviews.get("dp"), now),
        "human_oversight": _ticked("arb", "arb.human_oversight", f, reviews.get("arb")),
        "decommission_plan": _ticked("arb", "arb.decommission", f, reviews.get("arb")),
        "context_doc": bool(f.get("context_present")),
        "evaluation_pass": bool(verdict and verdict.verdict == "pass"),
        "versions": bool(versions),
    }
    return {"id": agent.id, "name": agent.name, "stage": agent.lifecycle_stage, "classified": rec is not None,
            "category": rec.category if rec else agent.eu_ai_act_category, "answers": answers, "evidence": ev,
            "classification": {"category": rec.category, "riskLevel": rec.risk_level, "confirmedAt": rec.confirmed_at.isoformat() if rec.confirmed_at else None,
                               "confirmedBy": rec.confirmed_by} if rec else None}


async def registry_evidence() -> dict:
    from api.routers.ops.controls import controls
    from services.decision_chain import verify

    states = {c["key"]: c["state"] for c in (await controls(None))["controls"]}
    chain = await verify()
    return {
        "roles": states.get("roles") == "enforced",
        "audit_log": states.get("audit") == "enforced",
        "decision_chain": chain["ok"],
        "stage_gates": states.get("stage_gates") in ("enforced", "partly", "recorded"),
        "approval_expiry": states.get("approval_expiry") == "enforced",
        "change_reopens": states.get("change_reopens") in ("enforced", "recorded"),
        "waivers": states.get("waivers") == "enforced",
        "self_approval": states.get("self_approval") == "enforced",
        "classification_rule": states.get("classification") == "enforced",
        "retirement_rule": states.get("retirement") == "enforced",
        "notices": states.get("notices") in ("enforced", "recorded"),
        "incident_linking": True,
    }


async def in_scope_agents(db) -> list[Agent]:
    """Agents the packs are checked for: everything not retired (the demo filter applies)."""
    return list((await db.execute(select(Agent).where(Agent.lifecycle_stage != "Deprecated")
                                  .options(selectinload(Agent.governance_reviews)))).scalars())
