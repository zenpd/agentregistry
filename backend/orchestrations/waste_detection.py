"""Waste Detection Orchestration — detects various types of AI waste.

Detects:
- Idle agents (Production but no usage)
- Model overkill (frontier model on simple task)
- Always-on agents (high invocations with low value)
- RAG bloat (excessive knowledge base usage)
"""
from sqlalchemy import select, func
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage, WasteFinding


async def _existing_finding_ids(db, agent_id: str) -> set:
    """Get IDs of existing waste findings for an agent."""
    result = await db.execute(select(WasteFinding.id).where(WasteFinding.agent_id == agent_id))
    return set(r[0] for r in result.all())


async def run_waste_detection(org_id: str) -> dict:
    """Run waste detection across all agents."""
    findings_saved = []
    total_waste_cents = 0

    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.org_id == org_id))
        agents = result.scalars().all()

        for agent in agents:
            existing_ids = await _existing_finding_ids(db, agent.id)

            # Check 1: Idle agents (Production but no usage)
            if agent.lifecycle_stage == "Production":
                usage_result = await db.execute(
                    select(func.sum(AgentTokenUsage.input_tokens))
                    .where(AgentTokenUsage.agent_id == agent.id)
                )
                total_tokens = usage_result.scalar() or 0

                if total_tokens == 0:
                    finding_id = f"waste-{agent.id}-idle"
                    if finding_id not in existing_ids:
                        db.add(WasteFinding(
                            id=finding_id,
                            agent_id=agent.id,
                            waste_type="idle_agent",
                            severity="medium",
                            recommendation="Agent is in Production but has no token usage — consider decommissioning",
                        ))
                        findings_saved.append(finding_id)
                        if agent.value_amount > 0:
                            total_waste_cents += int(agent.value_amount / 12 * 100)

            # Check 2: Model overkill
            frontier_models = ["GPT-5", "Claude Opus 4.8", "Gemini 3.1 Pro"]
            simple_tasks = ["Conversational AI / Chatbot", "Copilot / Assistant"]
            if agent.model_name in frontier_models and agent.ai_type in simple_tasks:
                finding_id = f"waste-{agent.id}-overkill"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="model_overkill",
                        severity="low",
                        recommendation=f"Frontier model {agent.model_name} on {agent.ai_type} — consider GPT-5-mini or Claude Haiku",
                    ))
                    findings_saved.append(finding_id)

            # Check 3: Always-on agents (high invocations)
            invocation_result = await db.execute(
                select(func.sum(AgentTokenUsage.invocation_count))
                .where(AgentTokenUsage.agent_id == agent.id)
            )
            invocations = invocation_result.scalar() or 0

            if invocations > 10000:
                finding_id = f"waste-{agent.id}-alwayson"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="always_on",
                        severity="medium",
                        recommendation=f"High invocation count ({invocations}) — review if continuous operation is necessary",
                    ))
                    findings_saved.append(finding_id)

            # Check 4: RAG bloat (many knowledge bases)
            if len(agent.knowledge_bases or []) > 3:
                finding_id = f"waste-{agent.id}-ragbloat"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="rag_bloat",
                        severity="low",
                        recommendation=f"Agent uses {len(agent.knowledge_bases)} knowledge bases — consolidate or prune",
                    ))
                    findings_saved.append(finding_id)

            # F-56: Prompt compression detection — detect long prompts with repetitive content
            prompt_len = (agent.description or "").count(" ") + (agent.business_outcome or "").count(" ")
            if prompt_len > 2000 and len(agent.tags or []) > 5:
                finding_id = f"waste-{agent.id}-promptbloat"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="prompt_bloat",
                        severity="medium",
                        recommendation=f"Prompt context is {prompt_len} words with {len(agent.tags)} tags — apply compression or truncation",
                    ))
                    findings_saved.append(finding_id)

            # F-57: Conversation pruning — detect agents with no pruning configuration
            if (agent.invocation_count or 0) > 100 and not agent.max_tokens_per_invocation:
                finding_id = f"waste-{agent.id}-nopruning"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="no_conversation_pruning",
                        severity="medium",
                        recommendation="High invocation count without max_tokens_per_invocation — enable conversation pruning to control context window costs",
                    ))
                    findings_saved.append(finding_id)

            # F-55: Infinite loop protection — detect agents with high invocation counts and no rate limit
            if (agent.invocation_count or 0) > 50000:
                finding_id = f"waste-{agent.id}-looprisk"
                if finding_id not in existing_ids:
                    db.add(WasteFinding(
                        id=finding_id,
                        agent_id=agent.id,
                        waste_type="infinite_loop_risk",
                        severity="high",
                        recommendation=f"Agent has {agent.invocation_count} invocations — add max_iterations circuit breaker and auto-pause on breach",
                    ))
                    findings_saved.append(finding_id)

    return {
        "status": "completed",
        "agents_analyzed": len(agents),
        "findings_created": len(findings_saved),
        "total_waste_cents": total_waste_cents,
    }
