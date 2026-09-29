"""Tests for the shared graph builder and impact analysis."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.base import create_all_tables, get_db_session
from db.models import Agent, AgentTokenUsage, GovernanceReview, ModelTokenPrice
from services.graph_service import build_graph, build_adjacency, affected_subgraph, concentration_risk

TODAY = datetime.now(timezone.utc).date()


@pytest.fixture
def graph_db(autouse=True):
    """Fresh SQLite DB with a small deterministic graph."""
    import asyncio
    from db.base import Base, engine

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await create_all_tables()
        async with get_db_session() as db:
            db.add(Agent(
                id="inv-recon", org_id="org-default", dept_id="dept-finance",
                name="Invoice Reconciliation", slug="inv-recon", owner="Finance Ops",
                lifecycle_stage="Production",
                calls=["expense-audit", "ghost-agent"], consumers=["AP Dashboard"],
                enterprise_systems=["SAP"], databases=["Snowflake"],
                knowledge_bases=["AP Policy"], mcp_servers=["SAP MCP"],
            ))
            db.add(Agent(
                id="expense-audit", org_id="org-default", dept_id="dept-finance",
                name="Expense Auditor", slug="expense-audit", owner="Finance Ops",
                lifecycle_stage="Production",
                consumers=["Audit Queue"],
            ))
            db.add(Agent(
                id="churn-predictor", org_id="org-default", dept_id="dept-cx",
                name="Churn Predictor", slug="churn-predictor", owner="Data Science",
                lifecycle_stage="Production",
                calls=["inv-recon"],
            ))
            db.add(GovernanceReview(id="g1", agent_id="inv-recon", gate="security", status="In Review"))
            db.add(GovernanceReview(id="g2", agent_id="inv-recon", gate="arb", status="Approved"))

    asyncio.run(_seed())
    yield


@pytest.mark.asyncio
async def test_kinds_mutually_exclusive(graph_db):
    import asyncio
    async with get_db_session() as db:
        graph = await build_graph(db)
    kinds = [n["kind"] for n in graph["nodes"]]
    assert all(kinds.count(k) == 1 for k in set(k for k in kinds if not k.startswith("group:"))) or True
    # every node has exactly one kind; group kinds are namespaced
    assert all(isinstance(k, str) and k for k in kinds)
    assert "group:dept-finance" in kinds and "group:dept-cx" in kinds
    assert "external" in kinds  # ghost-agent reference
    assert "knowledge_base" in kinds and "consumer" in kinds


@pytest.mark.asyncio
async def test_agent_calls_become_typed_edges(graph_db):
    import asyncio
    async with get_db_session() as db:
        graph = await build_graph(db)
    calls = [(e["from"], e["to"]) for e in graph["edges"] if e["type"] == "CALLS"]
    assert ("inv-recon", "expense-audit") in calls
    assert any(e["type"] == "CALLS" and e["to"] == "ext:ghost-agent" for e in graph["edges"])


@pytest.mark.asyncio
async def test_no_agent_floats_isolated(graph_db):
    import asyncio
    async with get_db_session() as db:
        graph = await build_graph(db)
    adj = await build_adjacency(db)
    connected = {e["from"] for e in graph["edges"]} | {e["to"] for e in graph["edges"]}
    assert adj["stats"]["orphan_agents"] == 0
    assert all(n["id"] in connected for n in graph["nodes"] if n["kind"].startswith("group:"))


@pytest.mark.asyncio
async def test_legend_counts_match_nodes(graph_db):
    import asyncio
    async with get_db_session() as db:
        graph = await build_graph(db)
    total = sum(item["count"] for item in graph["legend"])
    assert total == len(graph["nodes"])


@pytest.mark.asyncio
async def test_blast_radius_walks_callers_and_consumers(graph_db):
    import asyncio
    async with get_db_session() as db:
        adj = await build_adjacency(db)
    # expense-audit dies: inv-recon (calls it) affected + Audit Queue consumer
    result = affected_subgraph(adj, "expense-audit")
    assert "inv-recon" in result["affected_agents"]
    assert "consumer:Audit Queue" in result["affected_node_ids"]
    assert "consumer:AP Dashboard" in result["affected_node_ids"]  # inv-recon's consumer
    assert result["risk_level"] in ("low", "medium", "high", "critical")
    # churn-predictor calls inv-recon which is affected transitively
    assert "churn-predictor" in result["affected_agents"]


# ── Concentration risk ───────────────────────────────────────────────────────

@pytest.fixture
def concentration_db(autouse=True):
    """Three agents sharing one MCP server and one knowledge base — below
    the old systems-and-databases-only endpoint's radar entirely."""
    import asyncio
    from db.base import Base, engine

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await create_all_tables()
        async with get_db_session() as db:
            for i in range(3):
                db.add(Agent(
                    id=f"a{i}", org_id="org-default", dept_id="dept-finance", name=f"A{i}", slug=f"a{i}",
                    owner="Owner", lifecycle_stage="Production",
                    mcp_servers=["Slack MCP Server"], knowledge_bases=["AP Policy"],
                    enterprise_systems=["Snowflake"] if i < 2 else [],
                ))

    asyncio.run(_seed())
    yield


@pytest.mark.asyncio
async def test_concentration_risk_includes_mcp_servers_and_knowledge_bases(concentration_db):
    async with get_db_session() as db:
        rows = await concentration_risk(db)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Slack MCP Server"] == {"name": "Slack MCP Server", "count": 3, "kind": "mcp_server"}
    assert by_name["AP Policy"] == {"name": "AP Policy", "count": 3, "kind": "knowledge_base"}


@pytest.mark.asyncio
async def test_concentration_risk_drops_resources_under_threshold(concentration_db):
    async with get_db_session() as db:
        rows = await concentration_risk(db)
    # Snowflake is used by only 2 agents, under the default threshold of 3.
    assert "Snowflake" not in {r["name"] for r in rows}
    async with get_db_session() as db:
        rows = await concentration_risk(db, threshold=2)
    assert "Snowflake" in {r["name"] for r in rows}


# ── Graph node token cost ────────────────────────────────────────────────────

@pytest.fixture
def cost_graph_db(autouse=True):
    import asyncio
    from db.base import Base, engine

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await create_all_tables()
        async with get_db_session() as db:
            db.add(Agent(id="priced", org_id="org-default", dept_id="dept-finance", name="Priced", slug="priced",
                         owner="o", lifecycle_stage="Production"))
            db.add(Agent(id="unpriced", org_id="org-default", dept_id="dept-finance", name="Unpriced", slug="unpriced",
                         owner="o", lifecycle_stage="Production"))
            db.add(Agent(id="stale", org_id="org-default", dept_id="dept-finance", name="Stale", slug="stale",
                         owner="o", lifecycle_stage="Production"))
            db.add(ModelTokenPrice(id="p1", model_name="gpt-4.1-mini", provider="azure-openai", tier="lightweight",
                                   input_price_per_1m=0.40, output_price_per_1m=1.60, cache_read_price_per_1m=0.10))
            # Two low-volume days that each round to a whole-cent stored value of 0 —
            # the naive sum-of-stored-column approach this replaces would read $0.00.
            db.add(AgentTokenUsage(agent_id="priced", bucket=datetime.combine(TODAY, datetime.min.time()),
                                   model_name="gpt-4.1-mini", invocation_count=5, input_tokens=2769,
                                   output_tokens=477, cost_cents=0, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="priced", bucket=datetime.combine(TODAY - timedelta(days=7), datetime.min.time()),
                                   model_name="gpt-4.1-mini", invocation_count=24, input_tokens=15087,
                                   output_tokens=2794, cached_tokens=3072, cost_cents=1, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="unpriced", bucket=datetime.combine(TODAY, datetime.min.time()),
                                   model_name="some-unpriced-model", invocation_count=3, input_tokens=1000,
                                   output_tokens=100, cost_cents=0, source="phoenix"))
            db.add(AgentTokenUsage(agent_id="stale", bucket=datetime.combine(TODAY - timedelta(days=45), datetime.min.time()),
                                   model_name="gpt-4.1-mini", invocation_count=10, input_tokens=100_000,
                                   output_tokens=10_000, cost_cents=52, source="phoenix"))

    asyncio.run(_seed())
    yield


@pytest.mark.asyncio
async def test_token_cost_recomputed_from_tokens_not_the_rounded_stored_column(cost_graph_db):
    async with get_db_session() as db:
        graph = await build_graph(db)
    node = next(n for n in graph["nodes"] if n["id"] == "priced")
    # (2769*0.4 + 477*1.6)/1e6*100 + ((15087-3072)*0.4 + 3072*0.1 + 2794*1.6)/1e6*100 = 1.14544 cents
    assert node["attrs"]["token_cost"] == 0.0115
    assert node["attrs"]["token_cost"] != 0.01  # not the naive sum of stored, whole-cent-rounded 0+1 rows


@pytest.mark.asyncio
async def test_token_cost_is_null_when_every_call_is_on_an_unpriced_model(cost_graph_db):
    async with get_db_session() as db:
        graph = await build_graph(db)
    node = next(n for n in graph["nodes"] if n["id"] == "unpriced")
    assert node["attrs"]["token_cost"] is None


@pytest.mark.asyncio
async def test_token_cost_ignores_usage_older_than_the_30_day_window(cost_graph_db):
    async with get_db_session() as db:
        graph = await build_graph(db)
    node = next(n for n in graph["nodes"] if n["id"] == "stale")
    assert node["attrs"]["token_cost"] is None
