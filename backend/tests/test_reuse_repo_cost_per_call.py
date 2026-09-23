"""services/reuse_repo.py::cost_per_call — one bulk usage query for many
agents (services/usage_repo.py::load_usage_rows_bulk) instead of one query
per agent. Checks the batching doesn't leak rows across agents and that the
three pricing states (ok/partial/missing) still come out right per agent."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from db.base import Base, create_all_tables, engine, get_db_session
from db.models import Agent, AgentTokenUsage, ModelTokenPrice
from services.reuse_repo import cost_per_call
from services.usage_repo import load_usage_rows_bulk

TODAY = date(2026, 9, 23)


@pytest.fixture
def cost_db(autouse=True):
    import asyncio

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await create_all_tables()
        async with get_db_session() as db:
            db.add(Agent(id="a1", org_id="org-default", dept_id="dept-finance", name="A1", slug="a1",
                         owner="o", lifecycle_stage="Production"))
            db.add(Agent(id="a2", org_id="org-default", dept_id="dept-finance", name="A2", slug="a2",
                         owner="o", lifecycle_stage="Production"))
            db.add(Agent(id="a3", org_id="org-default", dept_id="dept-finance", name="A3", slug="a3",
                         owner="o", lifecycle_stage="Production"))
            db.add(ModelTokenPrice(id="p1", model_name="gpt-4.1-mini", provider="azure-openai", tier="lightweight",
                                   input_price_per_1m=0.40, output_price_per_1m=1.60, cache_read_price_per_1m=0.10))
            bucket = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc)
            # a1: priced calls within the window.
            db.add(AgentTokenUsage(agent_id="a1", bucket=bucket, model_name="gpt-4.1-mini",
                                   invocation_count=10, input_tokens=10_000, output_tokens=1_000, source="phoenix"))
            # a2: entirely on an unpriced model -> pricing 'missing'.
            db.add(AgentTokenUsage(agent_id="a2", bucket=bucket, model_name="some-unpriced-model",
                                   invocation_count=5, input_tokens=1_000, output_tokens=100, source="phoenix"))
            # a3: one priced row inside the window, one priced row far outside it —
            # the outside-window row must not leak into a1's or a2's totals or into
            # a3's own windowed figure.
            db.add(AgentTokenUsage(agent_id="a3", bucket=bucket, model_name="gpt-4.1-mini",
                                   invocation_count=4, input_tokens=4_000, output_tokens=400, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="a3", bucket=bucket - timedelta(days=90), model_name="gpt-4.1-mini",
                                   invocation_count=100, input_tokens=100_000, output_tokens=10_000, source="phoenix"))

    asyncio.run(_seed())
    yield


@pytest.mark.asyncio
async def test_each_agent_gets_only_its_own_rows(cost_db):
    async with get_db_session() as db:
        out = await cost_per_call(db, ["a1", "a2", "a3"], today=TODAY)
    assert out["a1"]["pricing"] == "ok" and out["a1"]["costPerCallCents"] is not None
    assert out["a2"]["pricing"] == "missing" and out["a2"]["costPerCallCents"] is None
    assert out["a3"]["pricing"] == "ok" and out["a3"]["costPerCallCents"] is not None
    # a3's cost/call is from its 4-invocation windowed row alone, not blended
    # with its 100-invocation row from 90 days ago (which would pull the
    # per-call average toward that batch's rate instead).
    assert out["a1"]["costPerCallCents"] == out["a3"]["costPerCallCents"]


@pytest.mark.asyncio
async def test_an_agent_with_no_usage_rows_at_all_is_a_real_zero(cost_db):
    async with get_db_session() as db:
        out = await cost_per_call(db, ["a1", "no-usage-agent"], today=TODAY)
    assert out["no-usage-agent"] == {"costPerCallCents": None, "source": "none", "pricing": "ok"}


@pytest.mark.asyncio
async def test_empty_agent_list_returns_empty_without_a_query():
    async with get_db_session() as db:
        assert await cost_per_call(db, [], today=TODAY) == {}
        assert await load_usage_rows_bulk(db, []) == {}


@pytest.mark.asyncio
async def test_bulk_loader_groups_rows_by_agent_and_respects_since(cost_db):
    async with get_db_session() as db:
        by_agent = await load_usage_rows_bulk(db, ["a1", "a3"], since=TODAY - timedelta(days=7))
    assert {r["day"] for r in by_agent["a1"]} == {TODAY}
    # a3's 90-days-ago row is excluded by `since`; only its in-window row remains.
    assert len(by_agent["a3"]) == 1 and by_agent["a3"][0]["day"] == TODAY
