"""GET /agents/{id}/tokens (registry.py) — the older, pre-engine-backed
shape kept for compatibility. It used to sum the stored cost_cents column,
which is rounded to the nearest whole cent per day; recomputed from the
same governance/costing engine as /tokens/summary and /tokenomics."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api.routers.registry import agent_tokens
from db.base import Base, create_all_tables, engine, get_db_session
from db.models import Agent, AgentTokenUsage, ModelTokenPrice

TODAY = datetime.now(timezone.utc)


@pytest.fixture
def tokens_db(autouse=True):
    import asyncio

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await create_all_tables()
        async with get_db_session() as db:
            db.add(Agent(id="a1", org_id="org-default", dept_id="dept-finance", name="A1", slug="a1",
                         owner="o", lifecycle_stage="Production"))
            db.add(Agent(id="unpriced", org_id="org-default", dept_id="dept-finance", name="U", slug="u",
                         owner="o", lifecycle_stage="Production"))
            db.add(ModelTokenPrice(id="p1", model_name="gpt-4.1-mini", provider="azure-openai", tier="lightweight",
                                   input_price_per_1m=0.40, output_price_per_1m=1.60, cache_read_price_per_1m=0.10))
            # Same two rows as the real digital-onboarding-test data: each day's
            # cost rounds to a whole-cent stored value (0, then 1) that sums to
            # 1 cent, while the true unrounded total is 1.1454 cents.
            db.add(AgentTokenUsage(agent_id="a1", bucket=TODAY, model_name="gpt-4.1-mini",
                                   invocation_count=5, input_tokens=2769, output_tokens=477,
                                   cost_cents=0, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="a1", bucket=TODAY.replace(day=max(TODAY.day - 7, 1)),
                                   model_name="gpt-4.1-mini", invocation_count=24, input_tokens=15087,
                                   output_tokens=2794, cached_tokens=3072, cost_cents=1, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="unpriced", bucket=TODAY, model_name="some-unpriced-model",
                                   invocation_count=3, input_tokens=1000, output_tokens=100,
                                   cost_cents=0, source="phoenix"))

    asyncio.run(_seed())
    yield


@pytest.mark.asyncio
async def test_legacy_tokens_matches_the_engine_not_the_rounded_stored_column(tokens_db):
    result = await agent_tokens("a1", None)
    assert result["invocations"] == 29
    assert result["inputTokens"] == 17856 and result["outputTokens"] == 3271
    assert result["costCents"] == pytest.approx(1.1454, abs=0.0005)
    assert result["costCents"] != 1  # the old, rounded-column answer


@pytest.mark.asyncio
async def test_legacy_tokens_is_null_not_zero_when_every_call_is_unpriced(tokens_db):
    result = await agent_tokens("unpriced", None)
    assert result["costCents"] is None


@pytest.mark.asyncio
async def test_legacy_tokens_is_a_real_zero_with_no_usage_at_all(tokens_db):
    result = await agent_tokens("no-such-agent-yet-a-real-zero", None)
    assert result["costCents"] == 0
    assert result["invocations"] == 0
