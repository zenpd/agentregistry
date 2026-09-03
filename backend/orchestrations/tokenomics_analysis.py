"""Tokenomics Analysis Orchestration — cost calculation and anomaly detection.

Calculates real costs from token usage and model prices, detects budget anomalies.
"""
from sqlalchemy import select, func
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage, ModelTokenPrice, AgentBudget


async def run_tokenomics_analysis(agent_id: str, model_name: str = "GPT-5", budget: float = 5000) -> dict:
    """Run tokenomics analysis for an agent."""
    async with get_db_session() as db:
        # Get agent
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            return {"status": "error", "message": "Agent not found"}

        # Get token usage
        result = await db.execute(
            select(
                func.sum(AgentTokenUsage.input_tokens),
                func.sum(AgentTokenUsage.output_tokens),
                func.sum(AgentTokenUsage.cached_tokens),
                func.sum(AgentTokenUsage.invocation_count),
            ).where(AgentTokenUsage.agent_id == agent_id)
        )
        usage = result.one()

        input_tokens = usage[0] or 0
        output_tokens = usage[1] or 0
        cached_tokens = usage[2] or 0
        invocation_count = usage[3] or 0

        # Get model prices
        result = await db.execute(
            select(ModelTokenPrice).where(
                ModelTokenPrice.model_name == model_name,
                ModelTokenPrice.effective_to.is_(None)
            )
        )
        price = result.scalars().first()

        if not price:
            # Graceful degradation: try any price for this model, else use defaults
            result = await db.execute(
                select(ModelTokenPrice).where(
                    ModelTokenPrice.model_name == model_name
                ).order_by(ModelTokenPrice.effective_from.desc()).limit(1)
            )
            price = result.scalars().first()

        if not price:
            # Last resort: use GPT-5 pricing as a default
            result = await db.execute(
                select(ModelTokenPrice).where(ModelTokenPrice.model_name == "GPT-5")
            )
            price = result.scalars().first()

        if not price:
            # No pricing data at all — return zeros with a warning
            return {
                "status": "completed",
                "agent_id": agent_id,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "invocation_count": invocation_count,
                "monthly_cost": 0,
                "cost_per_invocation": 0,
                "budget_usage_pct": 0,
                "anomaly_detected": False,
                "anomaly_type": None,
                "suggestions": ["No model pricing data available — add pricing via /api/v1/models/prices"],
            }

        # Calculate costs
        input_cost = (input_tokens / 1_000_000) * price.input_price_per_1m
        output_cost = (output_tokens / 1_000_000) * price.output_price_per_1m
        cache_savings = (cached_tokens / 1_000_000) * price.cache_read_price_per_1m
        monthly_cost = max(0, input_cost + output_cost - cache_savings)
        cost_per_invocation = monthly_cost / max(invocation_count, 1)

        # Check budget
        result = await db.execute(select(AgentBudget).where(AgentBudget.agent_id == agent_id))
        budget_record = result.scalar_one_or_none()
        budget_cents = budget_record.monthly_budget_cents if budget_record else budget * 100
        budget_usd = budget_cents / 100
        budget_usage_pct = (monthly_cost / budget_usd) * 100 if budget_usd > 0 else 0

        # Detect anomalies
        anomaly_detected = False
        anomaly_type = None
        suggestions = []

        if budget_usage_pct > 100:
            anomaly_detected = True
            anomaly_type = "budget_breach"
            suggestions.append(f"Cost ${monthly_cost:.2f} exceeds budget ${budget_cents / 100:.2f}")

        if budget_usage_pct > 80:
            suggestions.append("Approaching budget limit — consider model downgrade")

        if cost_per_invocation > 1.0:
            suggestions.append("High cost per invocation — optimize prompt or use cache")

        return {
            "status": "completed",
            "agent_id": agent_id,
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "invocation_count": invocation_count,
            "monthly_cost": round(monthly_cost, 2),
            "cost_per_invocation": round(cost_per_invocation, 4),
            "budget_usage_pct": round(budget_usage_pct, 1),
            "anomaly_detected": anomaly_detected,
            "anomaly_type": anomaly_type,
            "suggestions": suggestions,
        }
