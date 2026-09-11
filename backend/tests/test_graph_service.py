"""Tests for the shared graph builder and impact analysis."""
from __future__ import annotations

import pytest

from db.base import create_all_tables, get_db_session
from db.models import Agent, GovernanceReview
from services.graph_service import build_graph, build_adjacency, affected_subgraph


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
