"""Observed dependencies, declared-vs-observed comparison, the span-sample
cache and the Diagram tab router (temp DB, fake Phoenix)."""
from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from discovery import observed_deps as od
from discovery.graph_cache import GraphCache
from services.graph_service import affected_subgraph

PROMPT = "PRIVATE customer passport number 123"


def span(name, kind, attrs=None, span_id=None, parent=None, trace="t1", start=None, end=None):
    return {
        "name": name, "span_kind": kind, "attributes": attrs or {},
        "context": {"trace_id": trace, "span_id": span_id or f"{name}-{kind}"},
        "parent_id": parent, "start_time": start, "end_time": end, "status_code": "OK",
    }


ONBOARDING_SPANS = [
    span("supervisor", "AGENT", {"agent.name": "supervisor", "input.value": PROMPT}),
    span("next_agent", "AGENT"),
    span("LangGraph", "CHAIN"),
    span("ocr_extract_fields", "TOOL", {"tool.name": "ocr_extract_fields", "output.value": PROMPT}),
    span("ocr_extract_fields", "TOOL", {"tool.name": "ocr_extract_fields"}),
    span("sanctions_check", "TOOL", {"tool.name": "sanctions_check"}),
    span("ChatCompletion", "LLM", {
        "llm.model_name": "gpt-4.1-mini-2025-04-14",
        "llm.input_messages.0.message.content": PROMPT,
        "llm.output_messages.0.message.content": PROMPT,
    }),
    span("AzureChatOpenAI", "LLM", {"llm.model_name": "gpt-4.1-mini"}),
    span("CreateEmbeddings", "EMBEDDING", {"embedding.model_name": "text-embedding-3-small"}),
    span("policy_search", "RETRIEVER", {"retrieval.documents.0.document.content": PROMPT}),
    span("call", "TOOL", {"mcp.server": "core-banking-mcp", "mcp.tool": "get_account"}),
]


def by_name(items):
    return {i["name"]: i["count"] for i in items}


# ── observed_from_spans ──────────────────────────────────────────────────────

def test_observed_from_openinference_spans():
    obs = od.observed_from_spans(ONBOARDING_SPANS)
    assert set(obs) == set(od.OBSERVED_KEYS)
    assert by_name(obs["tools"]) == {"ocr_extract_fields": 2, "sanctions_check": 1, "get_account": 1}
    assert obs["tools"][0] == {"name": "ocr_extract_fields", "count": 2}
    assert by_name(obs["mcp_servers"]) == {"core-banking-mcp": 1}
    assert by_name(obs["retrievers"]) == {"policy_search": 1}
    assert by_name(obs["models"]) == {"gpt-4.1-mini-2025-04-14": 1, "gpt-4.1-mini": 1}
    assert by_name(obs["embeddings"]) == {"text-embedding-3-small": 1}
    # next_agent is LangGraph routing plumbing, not an agent.
    assert by_name(obs["agents"]) == {"supervisor": 1}


def test_observed_never_carries_prompt_or_output_text():
    assert PROMPT not in json.dumps(od.observed_from_spans(ONBOARDING_SPANS))
    assert PROMPT not in json.dumps(od.sample_stats(ONBOARDING_SPANS))


def test_attribute_reads_are_allowlisted():
    with pytest.raises(KeyError):
        od._attr({"input.value": PROMPT}, "input.value")


def test_observed_from_gen_ai_and_nested_attributes():
    spans = [
        {"name": "execute_tool lookup", "attributes": {"gen_ai": {"operation": {"name": "execute_tool"},
                                                                  "tool": {"name": "lookup"}}}},
        {"name": "chat gpt-4o", "attributes": {"gen_ai.operation.name": "chat", "gen_ai.response.model": "gpt-4o"}},
        {"name": "invoke_agent", "attributes": {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "Planner"}},
        {"name": "broken", "attributes": "not-a-dict"},
    ]
    obs = od.observed_from_spans(spans)
    assert by_name(obs["tools"]) == {"lookup": 1}
    assert by_name(obs["models"]) == {"gpt-4o": 1}
    assert by_name(obs["agents"]) == {"Planner": 1}


def test_embedding_model_read_from_invocation_parameters_only():
    spans = [
        span("CreateEmbeddings", "EMBEDDING", {
            "embedding.invocation_parameters": '{"model": "text-embedding-3-small", "encoding_format": "base64"}',
            "embedding.embeddings.0.embedding.text": PROMPT,
            "input.value": PROMPT,
        }),
        span("CreateEmbeddings", "EMBEDDING", {"embedding.invocation_parameters": "not json"}),
    ]
    obs = od.observed_from_spans(spans)
    assert by_name(obs["embeddings"]) == {"text-embedding-3-small": 1, "CreateEmbeddings": 1}
    assert PROMPT not in json.dumps(obs)


def test_observed_from_no_spans_is_empty_lists():
    assert od.observed_from_spans([]) == {key: [] for key in od.OBSERVED_KEYS}


def test_sample_stats_window_and_orphan_rate():
    spans = [
        span("root", "CHAIN", span_id="a", start="2026-09-01T10:00:00Z", end="2026-09-01T10:00:05Z"),
        span("child", "LLM", span_id="b", parent="a", start="2026-09-02T09:00:00+00:00"),
        span("orphan", "TOOL", span_id="c", parent="missing", start="2026-08-30T08:00:00Z", end="bad"),
        span("orphan2", "TOOL", span_id="d", parent="gone"),
    ]
    stats = od.sample_stats(spans)
    assert stats["from"] == "2026-08-30T08:00:00+00:00"
    assert stats["to"] == "2026-09-02T09:00:00+00:00"
    assert stats["orphanRate"] == 0.5
    assert od.sample_stats([]) == {"from": None, "to": None, "orphanRate": 0.0}


# ── matching ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,expected", [
    ("Core Banking API", "core_banking", True),
    ("SanctionsCheck", "sanctions-check", True),
    ("Sanctions Screening Service", "sanctions_check", True),
    ("KYC", "kyc_aml", True),
    ("CRM", "crm", True),
    ("Salesforce", "ocr_extract_fields", False),
    ("sanctions_check", "credit_check", False),
    ("Account Service", "get_account", True),
    ("API", "Core Banking API", False),
    ("", "anything", False),
])
def test_names_match(a, b, expected):
    assert od.names_match(a, b) is expected


def test_model_family_ignores_case_provider_prefix_and_date():
    assert od.model_family("azure/GPT-4.1-mini-2025-04-14") == od.model_family("gpt-4.1-mini") == "gpt41mini"
    assert od.model_family("gpt-4.1") != od.model_family("gpt-4.1-mini")


# ── compare ──────────────────────────────────────────────────────────────────

def test_compare_buckets():
    declared = {
        "enterprise_systems": ["Sanctions Screening Service", "Salesforce"],
        "databases": None,
        "knowledge_bases": ["Policy Search KB"],
        "mcp_servers": ["Core Banking MCP", "core banking mcp"],
        "calls": ["Planner"],
        "model_name": "GPT-4.1-mini",
    }
    result = od.compare(declared, od.observed_from_spans(ONBOARDING_SPANS))

    confirmed = {(c["declaredAs"], c["name"]): c for c in result["confirmed"]}
    assert set(confirmed) == {
        ("enterprise_systems", "Sanctions Screening Service"),
        ("knowledge_bases", "Policy Search KB"),
        ("mcp_servers", "Core Banking MCP"),
        ("model_name", "GPT-4.1-mini"),
    }
    assert confirmed[("enterprise_systems", "Sanctions Screening Service")] == {
        "name": "Sanctions Screening Service", "kind": "system", "declaredAs": "enterprise_systems",
        "observedAs": "tools", "observedName": "sanctions_check", "count": 1,
    }
    assert confirmed[("mcp_servers", "Core Banking MCP")]["observedAs"] == "mcp_servers"
    assert confirmed[("model_name", "GPT-4.1-mini")]["kind"] == "model"

    assert result["declared_only"] == [
        {"name": "Salesforce", "kind": "system", "declaredAs": "enterprise_systems"},
        {"name": "Planner", "kind": "agent", "declaredAs": "calls"},
    ]
    observed_only = {(o["kind"], o["name"]): o["count"] for o in result["observed_only"]}
    assert observed_only == {
        ("tool", "ocr_extract_fields"): 2,
        ("tool", "get_account"): 1,
        ("agent", "supervisor"): 1,
        ("embedding", "text-embedding-3-small"): 1,
    }
    for item in result["observed_only"]:
        assert set(item) == {"name", "kind", "observedAs", "count"}


def test_compare_with_nothing_declared_or_observed():
    assert od.compare({}, {}) == {"confirmed": [], "declared_only": [], "observed_only": []}
    only = od.compare({}, {"tools": [{"name": "x_tool", "count": 3}]})["observed_only"]
    assert only == [{"name": "x_tool", "kind": "tool", "observedAs": "tools", "count": 3}]


def test_compare_models_match_on_exact_family():
    result = od.compare({"model_name": "gpt-4.1"}, {"models": [{"name": "gpt-4.1-mini", "count": 5}]})
    assert result["confirmed"] == []
    assert result["declared_only"][0]["kind"] == "model"


# ── adopt ────────────────────────────────────────────────────────────────────

def test_adopt_items_maps_kinds_and_skips_duplicates():
    declared = {"mcp_servers": ["OCR-Extract-Fields"], "knowledge_bases": None, "enterprise_systems": ["CRM"]}
    plan = od.adopt_items(declared, [
        {"name": "ocr_extract_fields", "kind": "tool"},
        {"name": "core-banking-mcp", "kind": "mcp_server"},
        {"name": "Core Banking MCP", "kind": "mcp_server"},
        {"name": "policy_search", "kind": "retriever"},
        {"name": "Ledger", "kind": "system"},
    ])
    assert plan["fields"] == {
        "mcp_servers": ["OCR-Extract-Fields", "core-banking-mcp"],
        "knowledge_bases": ["policy_search"],
        "enterprise_systems": ["CRM", "Ledger"],
    }
    assert [s["name"] for s in plan["skipped"]] == ["ocr_extract_fields", "Core Banking MCP"]
    assert declared["mcp_servers"] == ["OCR-Extract-Fields"], "input must not be mutated"


@pytest.mark.parametrize("item", [{"name": "gpt-4.1", "kind": "model"}, {"name": " ", "kind": "tool"}])
def test_adopt_items_rejects_unadoptable(item):
    with pytest.raises(ValueError):
        od.adopt_items({}, [item])


# ── blast radius / upstream / shared resources ──────────────────────────────

def _adjacency():
    """a calls b, b calls c; x calls a; a and y share a KB; a feeds a dashboard."""
    agents = {
        "a": {"stage": "Production", "dept": "ops", "at_risk": False, "value_amount": 1000, "hours_saved_monthly": 5},
        "b": {"stage": "Testing", "dept": "ops", "at_risk": True, "risk_level": "HIGH", "worst_gate": "In Review"},
        "c": {"stage": "Production", "dept": "risk"},
        "x": {"stage": "Development", "dept": "sales", "value_amount": 50},
        "y": {"stage": "Production", "dept": "ops"},
    }
    edges = [
        {"from": "a", "to": "b", "type": "CALLS"},
        {"from": "b", "to": "c", "type": "CALLS"},
        {"from": "x", "to": "a", "type": "CALLS"},
        {"from": "a", "to": "ext:legacy-bot", "type": "CALLS"},
        {"from": "a", "to": "consumer:Dashboard", "type": "CONSUMED_BY"},
        {"from": "x", "to": "consumer:Portal", "type": "CONSUMED_BY"},
        {"from": "a", "to": "kb:Policies", "type": "USES_KB"},
        {"from": "y", "to": "kb:Policies", "type": "USES_KB"},
    ]
    adj = {
        "callers_of": {k: [] for k in agents}, "calls_by": {k: [] for k in agents},
        "consumers_of": {k: [] for k in agents}, "accessors_of": {},
        "agent_attrs": agents, "agent_kinds": {k: "group:ops" for k in agents},
        "node_names": {**{k: f"Agent {k.upper()}" for k in agents}, "ext:legacy-bot": "legacy-bot",
                       "consumer:Dashboard": "Dashboard", "consumer:Portal": "Portal", "kb:Policies": "Policies"},
        "nodes": [{"id": "kb:Policies", "kind": "knowledge_base"}],
        "edges": edges,
    }
    for e in edges:
        if e["type"] == "CALLS":
            adj["calls_by"][e["from"]].append(e["to"])
            if e["to"] in agents:
                adj["callers_of"][e["to"]].append(e["from"])
        elif e["type"] == "CONSUMED_BY":
            adj["consumers_of"][e["from"]].append(e["to"])
    return adj


def test_blast_radius_lists_affected_callers_and_consumers():
    adj = _adjacency()
    view = od.blast_radius_view(adj, "a", affected_subgraph(adj, "a"))
    assert [(a["id"], a["name"], a["stage"], a["hops"]) for a in view["agents"]] == [("x", "Agent X", "Development", 1)]
    assert view["consumers"] == [
        {"id": "consumer:Dashboard", "name": "Dashboard", "hops": 1},
        {"id": "consumer:Portal", "name": "Portal", "hops": 2},
    ]
    assert view["downstreamCount"] == 3
    assert view["revenueAtRisk"] == 1050


def test_blast_radius_of_a_leaf_walks_every_caller():
    adj = _adjacency()
    view = od.blast_radius_view(adj, "c", affected_subgraph(adj, "c"))
    assert [(a["id"], a["hops"]) for a in view["agents"]] == [("b", 1), ("a", 2), ("x", 3)]
    assert view["agents"][0]["atRisk"] is True


def test_upstream_includes_stage_risk_and_unregistered_callees():
    assert od.upstream_view(_adjacency(), "a") == [
        {"id": "b", "name": "Agent B", "registered": True, "stage": "Testing",
         "atRisk": True, "riskLevel": "HIGH", "worstGate": "In Review"},
        {"id": "ext:legacy-bot", "name": "legacy-bot", "registered": False, "stage": None,
         "atRisk": None, "riskLevel": None, "worstGate": None},
    ]


def test_shared_resources_counts_other_users():
    assert od.shared_resources(_adjacency(), "a") == [
        {"id": "kb:Policies", "name": "Policies", "kind": "knowledge_base", "alsoUsedBy": 1, "concentrated": False},
    ]


# ── cache ────────────────────────────────────────────────────────────────────

def test_graph_cache_ttl_and_invalidate():
    now = [0.0]
    cache = GraphCache(ttl_seconds=300, clock=lambda: now[0])
    k1, k2 = cache.key("a", "proj", "http://p"), cache.key("b", "proj", "http://p")
    stored = cache.set(k1, {"status": "ok"})
    cache.set(k2, {"status": "ok"})
    assert stored["cachedAt"] and cache.get(k1) == stored

    now[0] = 299
    assert cache.get(k1) is not None
    now[0] = 301
    assert cache.get(k1) is None

    assert cache.invalidate("b") == 1
    assert cache.get(k2) is None


# ── router ───────────────────────────────────────────────────────────────────

class FakePhoenix:
    calls = 0
    fail = False
    projects_listed: list[str] = []

    def __init__(self, base_url, *, api_key=None, timeout=None):
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def projects(self):
        return type(self).projects_listed

    async def spans(self, project, limit=100, max_pages=5, **kwargs):
        from discovery.phoenix_client import PhoenixError

        type(self).calls += 1
        url = f"{self.base_url}/v1/projects/{project}/spans"
        if type(self).fail == "404":
            raise PhoenixError("GET", url, 404, f"Project with name {project} not found")
        if type(self).fail:
            raise PhoenixError("GET", url, 0, "connect timeout")
        for s in ONBOARDING_SPANS:
            yield s


@pytest_asyncio.fixture
async def db():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    import db.models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="linked", org_id="org-default", name="Linked", slug="linked", owner="Ops",
                        lifecycle_stage="Production", phoenix_project="retail", phoenix_endpoint="http://phoenix.test",
                        model_name="GPT-4.1-mini", enterprise_systems=["Sanctions Screening Service"],
                        mcp_servers=None, calls=["plain"]))
            s.add(Agent(id="plain", org_id="org-default", name="Plain", slug="plain", owner="Ops",
                        lifecycle_stage="Testing", at_risk=True, knowledge_bases=["Policies"]))
        yield
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(monkeypatch):
    from api.auth import require_read, require_update
    from api.routers.ops import diagram

    FakePhoenix.calls, FakePhoenix.fail, FakePhoenix.projects_listed = 0, False, []
    monkeypatch.setattr(diagram, "PhoenixClient", FakePhoenix)
    monkeypatch.setattr(diagram, "graph_cache", GraphCache())
    app = FastAPI()
    app.include_router(diagram.router)
    user = {"user_id": "tester", "role": "admin"}
    for dep in (require_read, require_update):
        app.dependency_overrides[dep] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_graph_is_cached_until_refresh(db, client):
    first = (await client.get("/api/v1/agents/linked/reconstructed-graph")).json()
    assert first["status"] == "ok" and first["fromCache"] is False
    assert first["spanCount"] == len(ONBOARDING_SPANS) and first["cachedAt"]
    assert "observed" not in first

    second = (await client.get("/api/v1/agents/linked/reconstructed-graph")).json()
    assert second["fromCache"] is True and second["cachedAt"] == first["cachedAt"]

    deps = (await client.get("/api/v1/agents/linked/dependencies")).json()
    assert deps["fromCache"] is True and FakePhoenix.calls == 1

    third = (await client.get("/api/v1/agents/linked/reconstructed-graph?refresh=1")).json()
    assert third["fromCache"] is False and FakePhoenix.calls == 2


@pytest.mark.asyncio
async def test_dependencies_for_linked_agent(db, client):
    body = (await client.get("/api/v1/agents/linked/dependencies")).json()
    assert body["status"] == "ok"
    assert body["declared"]["mcpServers"] == [] and body["declared"]["calls"] == ["plain"]
    confirmed = {c["name"] for c in body["comparison"]["confirmed"]}
    assert confirmed == {"Sanctions Screening Service", "GPT-4.1-mini"}
    assert {d["name"] for d in body["comparison"]["declared_only"]} == {"Plain"}
    assert body["comparison"]["absenceConclusive"] is False
    assert body["upstream"] == [{"id": "plain", "name": "Plain", "registered": True, "stage": "Testing",
                                 "atRisk": True, "riskLevel": "LOW", "worstGate": None}]
    assert PROMPT not in json.dumps(body)


@pytest.mark.asyncio
async def test_not_linked_agent_still_gets_declared_and_blast_radius(db, client):
    body = (await client.get("/api/v1/agents/plain/dependencies")).json()
    assert body["status"] == "not_linked" and body["observed"] is None and body["comparison"] is None
    assert body["declared"]["knowledgeBases"] == ["Policies"]
    assert [a["id"] for a in body["blastRadius"]["agents"]] == ["linked"]
    assert body["blastRadius"]["agents"][0]["stage"] == "Production"
    assert FakePhoenix.calls == 0

    graph = (await client.get("/api/v1/agents/plain/reconstructed-graph")).json()
    assert graph["status"] == "not_linked" and graph["nodes"] == []


@pytest.mark.asyncio
async def test_unreachable_is_200_and_not_cached(db, client):
    FakePhoenix.fail = True
    r = await client.get("/api/v1/agents/linked/reconstructed-graph")
    assert r.status_code == 200 and r.json()["status"] == "phoenix_unreachable"
    assert "connect timeout" in r.json()["reason"]
    FakePhoenix.fail = False
    assert (await client.get("/api/v1/agents/linked/reconstructed-graph")).json()["status"] == "ok"
    assert FakePhoenix.calls == 2


@pytest.mark.asyncio
async def test_missing_project_is_no_traces_yet_but_other_404s_are_unreachable(db, client):
    FakePhoenix.fail, FakePhoenix.projects_listed = "404", ["some-other-project"]
    body = (await client.get("/api/v1/agents/linked/reconstructed-graph")).json()
    assert body["status"] == "no_traces_yet" and "no project named 'retail'" in body["reason"]

    FakePhoenix.projects_listed = ["retail"]
    body = (await client.get("/api/v1/agents/linked/dependencies?refresh=1")).json()
    assert body["status"] == "phoenix_unreachable" and "HTTP 404" in body["reason"]
    assert body["comparison"] is None and body["declared"]["enterpriseSystems"]


@pytest.mark.asyncio
async def test_adopt_appends_audits_and_invalidates(db, client):
    from db.base import get_db_session
    from db.models import Agent, AuditLog

    await client.get("/api/v1/agents/linked/dependencies")
    r = await client.post("/api/v1/agents/linked/dependencies/adopt", json={"items": [
        {"name": "ocr_extract_fields", "kind": "tool"},
        {"name": "policy_search", "kind": "retriever"},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "updated"
    assert body["declared"]["mcpServers"] == ["ocr_extract_fields"]
    assert body["declared"]["knowledgeBases"] == ["policy_search"]

    again = (await client.post("/api/v1/agents/linked/dependencies/adopt",
                               json={"items": [{"name": "OCR Extract Fields", "kind": "tool"}]})).json()
    assert again["status"] == "unchanged" and again["skipped"][0]["reason"] == "already declared"

    async with get_db_session() as s:
        agent = (await s.execute(select(Agent).where(Agent.id == "linked"))).scalar_one()
        audits = (await s.execute(select(AuditLog))).scalars().all()
    assert agent.mcp_servers == ["ocr_extract_fields"]
    assert len(audits) == 1 and audits[0].action == "adopt_observed_dependencies"
    assert audits[0].actor == "tester" and audits[0].entity_id == "linked"

    deps = (await client.get("/api/v1/agents/linked/dependencies")).json()
    assert deps["fromCache"] is False
    assert "ocr_extract_fields" in {c["name"] for c in deps["comparison"]["confirmed"]}

    bad = await client.post("/api/v1/agents/linked/dependencies/adopt", json={"items": [{"name": "gpt", "kind": "model"}]})
    assert bad.status_code == 422
    missing = await client.post("/api/v1/agents/nope/dependencies/adopt", json={"items": [{"name": "x", "kind": "tool"}]})
    assert missing.status_code == 404
