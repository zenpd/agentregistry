"""Discovery Pipeline Orchestration — multi-source agent discovery workflow.

Scans real data sources from the database and writes discovered agents to the discoveries table.
"""
import secrets
from datetime import date
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db_session
from db.models import Agent, Discovery, GovernanceReview, AgentTokenUsage


async def scan_sources(org_id: str) -> dict:
    """Scan all discovery sources from the database."""
    sources_scanned = []
    raw_findings = []

    async with get_db_session() as db:
        # Source 1: Scan agents table for stalled agents
        result = await db.execute(
            select(Agent.id, Agent.name, Agent.lifecycle_stage, Agent.time_in_stage_weeks)
            .where(Agent.org_id == org_id)
        )
        agents = result.all()
        sources_scanned.append("agents_table")
        for agent in agents:
            if agent.lifecycle_stage == "Ideation" and agent.time_in_stage_weeks and agent.time_in_stage_weeks > 12:
                confidence = min(90, 50 + (agent.time_in_stage_weeks - 12) * 2)
                raw_findings.append({
                    "source": "agents_table",
                    "name": agent.name,
                    "suspected_dept": "Unknown",
                    "suspected_type": "Autonomous Agent",
                    "confidence": confidence,
                    "signal": f"Agent stalled in Ideation for {agent.time_in_stage_weeks} weeks",
                    "shadow_ai_risk": "HIGH" if agent.time_in_stage_weeks > 20 else "MEDIUM",
                })

        # Source 2: Scan for concentration risks
        result = await db.execute(text("""
            SELECT system_name, COUNT(*) as cnt FROM (
                SELECT json_each.value as system_name FROM agents, json_each(agents.enterprise_systems)
                UNION ALL
                SELECT json_each.value as system_name FROM agents, json_each(agents.databases)
            ) GROUP BY system_name HAVING cnt >= 2
        """))
        concentration_risks = result.all()
        sources_scanned.append("concentration_risk")
        for risk in concentration_risks:
            confidence = min(95, 60 + risk[1] * 5)
            raw_findings.append({
                "source": "concentration_risk",
                "name": f"Concentration risk: {risk[0]}",
                "suspected_dept": "IT Operations",
                "suspected_type": "Infrastructure",
                "confidence": confidence,
                "signal": f"System {risk[0]} has {risk[1]} dependent agents",
                "shadow_ai_risk": "HIGH" if risk[1] >= 4 else "MEDIUM",
            })

        # Source 3: Scan for agents with no governance reviews
        result = await db.execute(text("""
            SELECT a.id, a.name FROM agents a
            LEFT JOIN governance_reviews gr ON a.id = gr.agent_id
            WHERE gr.id IS NULL
        """))
        ungoverned = result.all()
        sources_scanned.append("governance_gap")
        for agent in ungoverned:
            raw_findings.append({
                "source": "governance_gap",
                "name": agent[1],
                "suspected_dept": "Unknown",
                "suspected_type": "Autonomous Agent",
                "confidence": 85,
                "signal": "Agent has no governance reviews",
                "shadow_ai_risk": "HIGH",
            })

        # Source 4: Scan for idle agents (no token usage in Production)
        result = await db.execute(text("""
            SELECT a.id, a.name FROM agents a
            LEFT JOIN agent_token_usage tu ON a.id = tu.agent_id
            WHERE tu.agent_id IS NULL AND a.lifecycle_stage = 'Production'
        """))
        idle_agents = result.all()
        sources_scanned.append("idle_detection")
        for agent in idle_agents:
            raw_findings.append({
                "source": "idle_detection",
                "name": agent[1],
                "suspected_dept": "Unknown",
                "suspected_type": "Autonomous Agent",
                "confidence": 70,
                "signal": "Production agent has no token usage data",
                "shadow_ai_risk": "MEDIUM",
            })

        # Source 5: Scan for model overkill
        result = await db.execute(
            select(Agent.id, Agent.name, Agent.model_name, Agent.ai_type)
            .where(Agent.model_name.in_(["GPT-5", "Claude Opus 4.8", "Gemini 3.1 Pro"]))
            .where(Agent.ai_type.in_(["Conversational AI / Chatbot", "Copilot / Assistant"]))
        )
        overkill = result.all()
        sources_scanned.append("model_overkill")
        for agent in overkill:
            raw_findings.append({
                "source": "model_overkill",
                "name": agent.name,
                "suspected_dept": "Unknown",
                "suspected_type": agent.model_name,
                "confidence": 65,
                "signal": f"Frontier model {agent.model_name} on simple task",
                "shadow_ai_risk": "LOW",
            })

    return {"sources_scanned": sources_scanned, "raw_findings": raw_findings}


async def create_discoveries(org_id: str, findings: list) -> list:
    """Write discovery records to the database, skipping duplicates."""
    created = []
    async with get_db_session() as db:
        for finding in findings:
            if finding.get("confidence", 0) < 60:
                continue

            # Dedup: check for existing discovery with same name + source
            existing = await db.execute(
                select(Discovery.id).where(
                    Discovery.org_id == org_id,
                    Discovery.suspected_name == finding["name"],
                    Discovery.source == finding["source"],
                    Discovery.status.in_(["pending", "registered", "dismissed"]),
                )
            )
            if existing.all():
                continue

            discovery_id = f"disc-{secrets.token_hex(8)}"
            db.add(Discovery(
                id=discovery_id, org_id=org_id,
                suspected_name=finding["name"],
                suspected_dept=finding.get("suspected_dept", ""),
                suspected_type=finding.get("suspected_type", ""),
                source=finding["source"],
                confidence=finding["confidence"],
                signal=finding.get("signal", ""),
                shadow_ai_risk=finding.get("shadow_ai_risk", "MEDIUM"),
                first_seen=date.today()
            ))
            created.append(discovery_id)
    return created


async def run_discovery_pipeline(org_id: str) -> dict:
    """Run the full discovery pipeline for an organization."""
    scan_result = await scan_sources(org_id)
    created = await create_discoveries(org_id, scan_result["raw_findings"])
    return {
        "status": "completed",
        "sources_scanned": len(scan_result["sources_scanned"]),
        "raw_findings": len(scan_result["raw_findings"]),
        "discoveries_created": len(created),
    }
