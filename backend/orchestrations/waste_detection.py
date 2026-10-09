"""Spend review: idle and duplicate spend (item 53 of the improvement plan).

- Idle spend: a Production agent with no call in the last 30 days that still costs
  money for hosting.
- Duplicate spend: two agents that look like they do the same job (the reuse
  similarity rule) while both cost money.

Each becomes an open waste finding with the monthly amount, which the risk scan
shows as a FINANCIAL risk. A finding that no longer applies is resolved.

run_legacy_waste_heuristics below is the earlier placeholder (idle by any token
usage ever, model overkill by name, prompt bloat from the description length).
It is no longer called: it is kept until the final cleanup of the product.
"""
from sqlalchemy import select, func
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage, WasteFinding


async def _existing_finding_ids(db, agent_id: str) -> set:
    """Get IDs of existing waste findings for an agent."""
    result = await db.execute(select(WasteFinding.id).where(WasteFinding.agent_id == agent_id))
    return set(r[0] for r in result.all())


async def run_legacy_waste_heuristics(org_id: str) -> dict:
    """The earlier placeholder checks. Not called any more (see the module note)."""
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



SPEND_TYPES = ("idle_spend", "duplicate_spend")


async def review_spend(agent_id: str | None = None, trigger: str = "manual", **_) -> dict:
    """The daily job: store idle and duplicate spend as open waste findings."""
    from datetime import datetime, timezone

    from api.routers.ops.value_ops import spend_review_data

    async with get_db_session() as db:
        data = await spend_review_data(db)
        wanted: dict[str, dict] = {}
        for i in data["idle"]:
            wanted[f"spend-idle-{i['agentId']}"] = {"agent_id": i["agentId"], "waste_type": "idle_spend", "severity": "medium",
                                                     "monthly_waste_cents": i["monthlyCents"], "recommendation": i["text"] + " Retire it or stop the hosting."}
        for d in data["duplicates"]:
            a, b = d["agents"]
            wanted[f"spend-dup-{min(a['id'], b['id'])}-{max(a['id'], b['id'])}"] = {
                "agent_id": a["id"], "waste_type": "duplicate_spend", "severity": "low",
                "monthly_waste_cents": d["possibleSavingCents"], "recommendation": d["text"]}
        existing = {w.id: w for w in (await db.execute(select(WasteFinding).where(WasteFinding.waste_type.in_(SPEND_TYPES)))).scalars()}
        opened = resolved = 0
        for fid, v in wanted.items():
            row = existing.get(fid)
            if row is None:
                db.add(WasteFinding(id=fid, status="open", **v))
                opened += 1
            else:
                row.monthly_waste_cents, row.recommendation, row.severity = v["monthly_waste_cents"], v["recommendation"], v["severity"]
                if row.status != "open":
                    row.status, row.resolved_at = "open", None
        for fid, row in existing.items():
            if fid not in wanted and row.status == "open":
                row.status, row.resolved_at = "resolved", datetime.now(timezone.utc)
                resolved += 1
    return {"status": "ok", "idle": len(data["idle"]), "duplicates": len(data["duplicates"]), "opened": opened, "resolved": resolved,
            "monthlyCents": sum(v["monthly_waste_cents"] or 0 for v in wanted.values())}


async def run_waste_detection(org_id: str = "org-default") -> dict:
    """The older trigger (POST /orchestrations/waste-detection) runs the spend review."""
    return await review_spend(trigger="manual")
