"""Insight refresh: keeps the AI insights current without anyone pressing a
button. For each agent that has real traces it re-runs the insights shown on
the agent's tabs, after the day's facts (usage, cost, risks, reviews) are in.

Only the insights that read registry facts are run. The two that read other
people's text (evidence documents, trace content) run only when a person asks.
A model that cannot be reached is reported, never raised."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from agents.insights.specs import SCHEDULED_KINDS
from db.base import get_db_session
from db.models import Agent
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("orchestrations.insight_refresh")
PARALLEL = 2


async def refresh_insights(agent_id: str | None = None, trigger: str = "manual", **_: Any) -> dict:
    from api.routers.ops.insights import run_agent_insight

    settings = get_settings()
    base = {"trigger": trigger, "agents": 0, "insights": 0, "unavailable": 0}
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        return {**base, "status": "not_configured", "reason": "No model is configured (Azure OpenAI endpoint and key)."}
    async with get_db_session() as db:
        stmt = select(Agent).where(Agent.id == agent_id) if agent_id else select(Agent).where(Agent.phoenix_project.isnot(None))
        agents = [a for a in (await db.execute(stmt)).scalars() if agent_id or (a.phoenix_project or "").strip()]
    agents = agents[: settings.insight_job_max_agents]
    if not agents:
        return {**base, "status": "skipped", "reason": "No agent has a Phoenix project linked, so there is nothing to refresh."}

    gate = asyncio.Semaphore(PARALLEL)
    done = {"ok": 0, "unavailable": 0}

    async def one(agent: Agent, kind: str) -> None:
        async with gate:
            try:
                result = await run_agent_insight(agent, kind, subject=None, actor=f"job:{trigger}")
                done["ok" if result["status"] == "ok" else "unavailable"] += 1
            except Exception:
                log.exception("insight_refresh.failed", agent_id=agent.id, kind=kind)
                done["unavailable"] += 1

    await asyncio.gather(*(one(a, k) for a in agents for k in SCHEDULED_KINDS))
    status = "ok" if not done["unavailable"] else ("partial" if done["ok"] else "unreachable")
    return {**base, "status": status, "agents": len(agents), "insights": done["ok"], "unavailable": done["unavailable"],
            "reason": None if status == "ok" else f"{done['unavailable']} insight(s) could not be written; the model may be unreachable."}
