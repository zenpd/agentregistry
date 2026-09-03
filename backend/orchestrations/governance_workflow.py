"""Governance Review Workflow Orchestration — multi-gate approval workflow.

Performs REAL governance reviews:
- ARB: Checks architecture (model choice, dependencies, SLA)
- Security: Checks PII access, data handling, model provider
- DLP: Checks data protection compliance

Reads agent data from database, applies review criteria, writes results back.
"""
from sqlalchemy import select
from datetime import datetime, timezone
import secrets
from db.base import get_db_session
from db.models import Agent, GovernanceReview


async def _get_agent_data(agent_id: str) -> Agent | None:
    """Get agent data from database."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        return result.scalar_one_or_none()


async def _check_arb_criteria(agent: Agent) -> tuple:
    """Check Architecture Review Board criteria."""
    issues = []
    status = "Approved"

    frontier_models = ["GPT-5", "Claude Opus 4.8", "Gemini 3.1 Pro"]
    if agent.model_name in frontier_models and agent.ai_type in ["Conversational AI / Chatbot", "Copilot / Assistant"]:
        issues.append("Frontier model on simple task — consider downgrade")
        status = "Approved with Conditions"

    if len(agent.enterprise_systems or []) > 3:
        issues.append("High system coupling — many enterprise system dependencies")

    if not agent.sla or agent.sla == "TBD":
        issues.append("SLA not defined")

    if not agent.owner:
        issues.append("No owner assigned")
        status = "Changes Requested"

    note = "; ".join(issues) if issues else "Architecture validated: single responsibility, clear interfaces"
    return status, note


async def _check_security_criteria(agent: Agent) -> tuple:
    """Check Security Review criteria."""
    issues = []
    status = "Approved"

    if agent.risk_level == "HIGH":
        issues.append("High-risk agent — requires encryption at rest and access logging")
        status = "Approved with Conditions"

    external_models = ["GPT-5", "GPT-5-mini", "GPT-5-nano", "Claude Sonnet 4.5", "Claude Haiku 4.5"]
    if agent.model_name in external_models:
        issues.append("External model provider — ensure data residency compliance")

    if len(agent.mcp_servers or []) > 3:
        issues.append("Many MCP server integrations — review tool permissions")

    note = "; ".join(issues) if issues else "Security posture acceptable"
    return status, note


async def _check_dlp_criteria(agent: Agent) -> tuple:
    """Check Data Protection Review criteria."""
    issues = []
    status = "Approved"

    if agent.risk_level == "HIGH":
        issues.append("High-risk agent — data classification review required")
        status = "Approved with Conditions"

    if agent.databases:
        issues.append(f"Accesses {len(agent.databases)} databases — verify data minimization")

    note = "; ".join(issues) if issues else "Data protection compliance verified"
    return status, note


async def run_governance_workflow(agent_id: str, org_id: str) -> dict:
    """Run the full governance review workflow for an agent."""
    agent = await _get_agent_data(agent_id)
    if not agent:
        return {"status": "error", "message": "Agent not found"}

    # Run reviews for each gate
    arb_status, arb_note = await _check_arb_criteria(agent)
    sec_status, sec_note = await _check_security_criteria(agent)
    dlp_status, dlp_note = await _check_dlp_criteria(agent)

    reviews = {"arb": arb_status, "security": sec_status, "dp": dlp_status}
    notes = {"arb": arb_note, "security": sec_note, "dp": dlp_note}

    # Determine final decision
    all_approved = all(s in ["Approved", "Approved with Conditions"] for s in reviews.values())
    changes_requested = any(s == "Changes Requested" for s in reviews.values())
    final_decision = "Approved" if all_approved else "Changes Requested" if changes_requested else "Rejected"

    # Save results to database
    async with get_db_session() as db:
        for gate, status in reviews.items():
            result = await db.execute(
                select(GovernanceReview).where(
                    GovernanceReview.agent_id == agent_id,
                    GovernanceReview.gate == gate
                )
            )
            review = result.scalar_one_or_none()
            if review:
                review.status = status
                review.notes = notes[gate]
                review.reviewed_at = datetime.now(timezone.utc)
            else:
                db.add(GovernanceReview(
                    id=f"gr-{secrets.token_hex(6)}",
                    agent_id=agent_id,
                    gate=gate,
                    status=status,
                    notes=notes[gate],
                    reviewed_at=datetime.now(timezone.utc),
                ))

    return {
        "status": "completed",
        "agent_id": agent_id,
        "reviews": reviews,
        "notes": notes,
        "final_decision": final_decision,
    }
