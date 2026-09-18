"""Azure Cost Management collector: pure parsing/allocation against a
recorded-style query response, and the collect job against a mocked Azure
(httpx.MockTransport) and a throwaway DB."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from costs import azure_cost_collector as collector
from costs.azure_cost_collector import (
    API_VERSION, mask_scope, missing_settings, parse_query_response, query_body, service_from_resource_id,
)
from db.base import Base, engine, get_db_session
from db.models import Agent, AgentInfraCost, AgentResourceLink, Organization
from shared.config import get_settings

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "azure_cost_query_sample.json").read_text())
SUB = "/subscriptions/00000000-aaaa-bbbb-cccc-000000000001"
DOT = "digital-onboarding-test-a8bfa826"
INV = "inv-recon"
FOUNDRY = f"{SUB}/resourcegroups/rg-shared-ai/providers/microsoft.cognitiveservices/accounts/zaf-ai-foundry"
KV = f"{SUB}/resourcegroups/rg-shared-ai/providers/microsoft.keyvault/vaults/zaf-kv-01"
API = f"{SUB}/resourcegroups/rg-onboarding/providers/microsoft.app/containerapps/onboarding-api"
LINKS = [
    # Stored the way a person types them: mixed case, resource group scope.
    {"agent_id": INV, "resource_id": "/subscriptions/00000000-AAAA-BBBB-CCCC-000000000001/resourceGroups/rg-shared-ai", "share_pct": 60},
    {"agent_id": DOT, "resource_id": f"{SUB}/resourceGroups/rg-shared-ai/providers/Microsoft.CognitiveServices/accounts/zaf-ai-foundry", "share_pct": 25},
]


def _alloc(result, agent_id, resource_id, day):
    matches = [a for a in result["allocations"]
               if a["agent_id"] == agent_id and a["resource_id"] == resource_id and a["cost_date"] == day]
    assert len(matches) == 1, matches
    return matches[0]


# ── Pure ─────────────────────────────────────────────────────────────────────

def test_tag_allocation_is_case_insensitive_on_key_and_agent_id():
    result = parse_query_response(FIXTURE, "agent-id", LINKS, agent_ids=[DOT, INV])
    a = _alloc(result, DOT, API, date(2026, 9, 15))
    assert (a["cost_cents"], a["allocation"], a["currency"]) == (321, "tag", "USD")
    assert a["service_name"] == "microsoft.app/containerapps"
    assert _alloc(result, DOT, API, date(2026, 9, 16))["cost_cents"] == 310
    cosmos = f"{SUB}/resourcegroups/rg-onboarding/providers/microsoft.documentdb/databaseaccounts/onboarding-cosmos"
    tagged = _alloc(result, DOT, cosmos, date(2026, 9, 15))
    assert (tagged["cost_cents"], tagged["allocation"]) == (150, "tag")


def test_links_split_by_share_with_resource_group_prefix_and_exact_id():
    result = parse_query_response(FIXTURE, "agent-id", LINKS, agent_ids=[DOT, INV])
    day = date(2026, 9, 15)
    assert _alloc(result, INV, FOUNDRY, day)["cost_cents"] == 744          # 60% via its resource group
    assert _alloc(result, DOT, FOUNDRY, day)["cost_cents"] == 310          # 25% via the exact resource id
    assert _alloc(result, INV, KV, day) == {
        "agent_id": INV, "cost_date": day, "resource_id": KV, "service_name": "microsoft.keyvault/vaults",
        "cost_cents": 240, "currency": "USD", "allocation": "link",
    }


def test_unallocated_keeps_the_remainder_and_ignores_zero_rows():
    result = parse_query_response(FIXTURE, "agent-id", LINKS, agent_ids=[DOT, INV])
    by_resource = {r["resource_id"]: r["cost_cents"] for r in result["unallocated_resources"]}
    assert by_resource[FOUNDRY] == 186                                     # 15% nobody claimed
    assert by_resource[KV] == 160
    assert by_resource[f"{SUB}/resourcegroups/rg-platform/providers/microsoft.network/applicationgateways/agw-edge"] == 725
    # rg-shared-ai-archive is not inside rg-shared-ai: prefixes match whole segments only.
    assert by_resource[f"{SUB}/resourcegroups/rg-shared-ai-archive/providers/microsoft.storage/storageaccounts/aiarchive"] == 200
    # A tag naming no registered agent is not allocated to anyone.
    assert by_resource[f"{SUB}/resourcegroups/rg-legacy/providers/microsoft.web/sites/retired-bot"] == 88
    assert result["unallocated_cents"] == 1359
    assert not any("onboarding-ai" in a["resource_id"] for a in result["allocations"])
    allocated = sum(a["cost_cents"] for a in result["allocations"])
    assert allocated + result["unallocated_cents"] == 3434


def test_without_agent_list_every_tag_value_is_trusted():
    result = parse_query_response(FIXTURE, "agent-id", [], agent_ids=None)
    assert {a["agent_id"] for a in result["allocations"]} == {DOT, "Digital-Onboarding-Test-A8BFA826", "retired-bot-agent"}


def test_tag_wins_over_a_link_on_the_same_resource():
    links = [{"agent_id": INV, "resource_id": f"{SUB}/resourceGroups/rg-onboarding", "share_pct": 100}]
    result = parse_query_response(FIXTURE, "agent-id", links, agent_ids=[DOT, INV])
    assert not any(a["agent_id"] == INV for a in result["allocations"])


def test_over_claimed_resource_is_scaled_to_its_real_cost():
    links = [
        {"agent_id": DOT, "resource_id": f"{SUB}/resourceGroups/rg-platform", "share_pct": 70},
        {"agent_id": INV, "resource_id": f"{SUB}/resourceGroups/rg-platform", "share_pct": 60},
    ]
    result = parse_query_response(FIXTURE, "agent-id", links, agent_ids=[DOT, INV])
    agw = [a for a in result["allocations"] if "agw-edge" in a["resource_id"]]
    assert sum(a["cost_cents"] for a in agw) == 725
    assert not any("agw-edge" in r["resource_id"] for r in result["unallocated_resources"])


def test_most_specific_link_of_one_agent_wins():
    links = [
        {"agent_id": INV, "resource_id": SUB, "share_pct": 10},
        {"agent_id": INV, "resource_id": f"{SUB}/resourceGroups/rg-platform", "share_pct": 50},
    ]
    result = parse_query_response(FIXTURE, "agent-id", links, agent_ids=[DOT, INV])
    agw = [a for a in result["allocations"] if "agw-edge" in a["resource_id"]]
    assert [a["cost_cents"] for a in agw] == [362]                         # 50% of 725, not 60%


def test_alternate_column_names_service_name_and_string_dates():
    payload = {"properties": {
        "columns": [{"name": "PreTaxCost", "type": "Number"}, {"name": "ResourceId", "type": "String"},
                    {"name": "ServiceName", "type": "String"}, {"name": "UsageDate", "type": "Datetime"},
                    {"name": "Currency", "type": "String"}],
        "rows": [[1.25, f"{SUB}/resourceGroups/rg-platform/providers/Microsoft.Web/sites/bot", "Azure App Service",
                  "2026-09-14T00:00:00", "EUR"]],
    }}
    links = [{"agent_id": INV, "resource_id": f"{SUB}/resourceGroups/rg-platform", "share_pct": 100}]
    [a] = parse_query_response(payload, "agent-id", links)["allocations"]
    assert (a["cost_date"], a["service_name"], a["currency"], a["cost_cents"]) == (
        date(2026, 9, 14), "Azure App Service", "EUR", 125)

    usd = {"properties": {"columns": [{"name": "CostUSD"}, {"name": "UsageDate"}, {"name": "Currency"}],
                          "rows": [[2.5, 20260914, "EUR"]]}}
    parsed = parse_query_response(usd, "agent-id", [])
    assert parsed["unallocated_cents"] == 250
    assert parsed["unallocated_resources"][0]["resource_id"] == collector.NO_RESOURCE_ID


def test_payload_without_cost_column_is_rejected():
    with pytest.raises(ValueError):
        parse_query_response({"properties": {"columns": [{"name": "UsageDate"}], "rows": []}}, "agent-id", [])


def test_query_body_matches_the_cost_management_contract():
    body = query_body("agent-id", date(2026, 9, 12), date(2026, 9, 18))
    assert body["type"] == "ActualCost" and body["timeframe"] == "Custom"
    assert body["timePeriod"] == {"from": "2026-09-12T00:00:00Z", "to": "2026-09-18T23:59:59Z"}
    assert body["dataset"]["granularity"] == "Daily"
    assert body["dataset"]["aggregation"] == {"totalCost": {"name": "Cost", "function": "Sum"}}
    # The Query API accepts at most two grouping clauses.
    assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ResourceId"},
                                           {"type": "TagKey", "name": "agent-id"}]


def test_helpers():
    assert service_from_resource_id(API) == "microsoft.app/containerapps"
    assert service_from_resource_id(f"{SUB}/resourceGroups/rg") is None
    assert mask_scope("/subscriptions/12345678-aaaa-bbbb-cccc-1234567890ab/resourceGroups/rg-ai") == \
        "/subscriptions/****90ab/resourceGroups/rg-ai"
    assert mask_scope("") is None
    empty = SimpleNamespace(azure_cost_scope="", azure_tenant_id="t", azure_client_id=" ", azure_client_secret="s")
    assert missing_settings(empty) == ["AZURE_COST_SCOPE", "AZURE_CLIENT_ID"]


# ── Collect job ──────────────────────────────────────────────────────────────

def _settings(**over):
    base = dict(azure_cost_scope=SUB, azure_tenant_id="tenant-guid", azure_client_id="client-guid",
                azure_client_secret="s3cret-value", azure_cost_tag_key="agent-id")
    return SimpleNamespace(**{**base, **over})


@pytest.mark.asyncio
async def test_not_configured_makes_no_network_call(monkeypatch):
    def no_network():
        raise AssertionError("network used while not configured")

    monkeypatch.setattr(collector, "_http_client", no_network)
    monkeypatch.setattr(collector, "get_settings", lambda: _settings(azure_cost_scope="", azure_client_secret=""))
    result = await collector.collect_infra_costs()
    assert result["status"] == "not_configured"
    assert result["missing"] == ["AZURE_COST_SCOPE", "AZURE_CLIENT_SECRET"]


@pytest_asyncio.fixture
async def db():
    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    import db.models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            for aid in (DOT, INV):
                s.add(Agent(id=aid, org_id="org-default", name=aid, slug=aid, owner="Ops"))
            for i, link in enumerate(LINKS):
                s.add(AgentResourceLink(id=f"link-{i}", **link))
        yield
    finally:
        await engine.dispose()


class FakeAzure:
    """Token endpoint + a two-page query (the second page reached via nextLink)."""

    def __init__(self, query_status=200, headers=None, next_link=None):
        self.requests: list[httpx.Request] = []
        self.query_status, self.headers = query_status, headers or {}
        rows = FIXTURE["properties"]["rows"]
        page2 = f"https://management.azure.com{SUB}/providers/Microsoft.CostManagement/query?api-version={API_VERSION}&$skiptoken=AQAAAA%3D%3D"
        self.pages = [
            {"properties": {"columns": FIXTURE["properties"]["columns"], "rows": rows[:4], "nextLink": next_link or page2}},
            {"properties": {"columns": FIXTURE["properties"]["columns"], "rows": rows[4:], "nextLink": None}},
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            form = parse_qs(request.content.decode())
            assert request.url.path == "/tenant-guid/oauth2/v2.0/token"
            assert form["grant_type"] == ["client_credentials"]
            assert form["scope"] == ["https://management.azure.com/.default"]
            return httpx.Response(200, json={"access_token": "tok-123", "token_type": "Bearer", "expires_in": 3599})
        assert request.headers["authorization"] == "Bearer tok-123"
        if self.query_status != 200:
            return httpx.Response(self.query_status, headers=self.headers,
                                  json={"error": {"code": "AuthorizationFailed", "message": "no access"}})
        assert request.url.path == f"{SUB}/providers/Microsoft.CostManagement/query"
        assert request.url.params["api-version"] == API_VERSION
        assert json.loads(request.content)["dataset"]["grouping"][1] == {"type": "TagKey", "name": "agent-id"}
        return httpx.Response(200, json=self.pages[1 if "skiptoken" in str(request.url) else 0])


def _use(monkeypatch, fake):
    monkeypatch.setattr(collector, "get_settings", lambda: _settings())
    monkeypatch.setattr(collector, "_utcnow", lambda: datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(collector, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake)))


async def _stored():
    async with get_db_session() as s:
        return (await s.execute(select(AgentInfraCost).order_by(AgentInfraCost.agent_id, AgentInfraCost.cost_date,
                                                                AgentInfraCost.resource_id))).scalars().all()


@pytest.mark.asyncio
async def test_collect_follows_next_link_and_upserts(db, monkeypatch):
    fake = FakeAzure()
    _use(monkeypatch, fake)
    result = await collector.collect_infra_costs(days=7)
    assert result["status"] == "partial"                                   # some cost is unallocated
    assert result["pages"] == 2 and result["unallocated_cents"] == 1359
    assert result["rows"] == 6 and result["agents"] == [DOT, INV]
    assert "s3cret" not in json.dumps(result, default=str)

    rows = await _stored()
    assert len(rows) == 6
    assert {(r.agent_id, r.allocation) for r in rows} == {(DOT, "tag"), (DOT, "link"), (INV, "link")}
    assert sum(r.cost_cents for r in rows) == 2075

    await collector.collect_infra_costs(days=7)                            # a re-run replaces, never duplicates
    assert len(await _stored()) == 6


@pytest.mark.asyncio
async def test_collect_for_one_agent_leaves_the_others(db, monkeypatch):
    _use(monkeypatch, FakeAzure())
    await collector.collect_infra_costs(days=7)
    result = await collector.collect_infra_costs(agent_id=INV, days=7)
    assert result["agents"] == [INV]
    assert {r.agent_id for r in await _stored()} == {DOT, INV}


@pytest.mark.asyncio
@pytest.mark.parametrize("code,headers,status", [
    (403, {}, "forbidden"),
    (401, {}, "forbidden"),
    (429, {"x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "60"}, "throttled"),
    (500, {}, "error"),
])
async def test_collect_maps_azure_errors_to_a_status(db, monkeypatch, code, headers, status):
    _use(monkeypatch, FakeAzure(query_status=code, headers=headers))
    result = await collector.collect_infra_costs()
    assert result["status"] == status and result["httpStatus"] == code
    if code == 429:
        assert result["retryAfterSeconds"] == "60"
    assert await _stored() == []


@pytest.mark.asyncio
async def test_rejected_client_secret_is_forbidden(db, monkeypatch):
    def fake(request):
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "AADSTS7000215"})

    _use(monkeypatch, fake)
    result = await collector.collect_infra_costs()
    assert result["status"] == "forbidden" and "invalid_client" in result["reason"]


@pytest.mark.asyncio
async def test_unreachable_azure(db, monkeypatch):
    def fake(request):
        raise httpx.ConnectError("dns failure")

    _use(monkeypatch, fake)
    assert (await collector.collect_infra_costs())["status"] == "unreachable"


@pytest.mark.asyncio
async def test_next_link_off_azure_never_gets_the_token(db, monkeypatch):
    fake = FakeAzure(next_link="https://evil.example.com/steal")
    _use(monkeypatch, fake)
    result = await collector.collect_infra_costs()
    assert result["status"] == "error"
    assert all(r.url.host != "evil.example.com" for r in fake.requests)
