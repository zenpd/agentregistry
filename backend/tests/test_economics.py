"""Value vs cost of ownership: the pure economics (governance/economics.py)
and the Revenue & Expenditure router against a throwaway DB."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from db.base import Base, engine, get_db_session
from db.models import Agent, AgentTokenUsage, AuditLog, ModelTokenPrice, Organization
from governance.costing import projected_period_end_cents
from governance.economics import (
    agent_economics, build_economics, efficiency_rating, evaluate_financial_flags, monthly_trend, recent_months,
    resolve_infra,
)
from shared.config import get_settings

TODAY = date(2026, 9, 18)
RATE = 60.0


# ── resolve_infra / agent_economics ──────────────────────────────────────────

def test_infra_precedence_metered_then_declared_then_stage_estimate():
    assert resolve_infra(4321.456, 9000, "Production") == {"cents": 4321.46, "source": "metered"}
    assert resolve_infra(0.0, 9000, "Production") == {"cents": 0.0, "source": "metered"}
    assert resolve_infra(None, 9000, "Production") == {"cents": 9000, "source": "declared"}
    assert resolve_infra(None, None, "Production") == {"cents": 8000, "source": "estimate"}
    assert resolve_infra(None, None, "Testing") == {"cents": 2000, "source": "estimate"}
    for stage in ("Ideation", "Development", None):
        assert resolve_infra(None, None, stage) == {"cents": 0, "source": "estimate"}


def test_agent_economics_value_cost_net_roi_and_legacy_keys():
    e = agent_economics(
        value_amount_dollars=1000, hours_saved_monthly=10, hourly_rate=RATE,
        token_cost_cents=1500.5, token_source="phoenix", infra={"cents": 8000, "source": "estimate"},
        one_time_cost_cents=50000,
    )
    assert e["valueCents"] == 100000 and e["realizedValueCents"] == 60000
    assert (e["tokenCostCents"], e["tokenSource"], e["infraCostCents"], e["infraSource"]) == (1500.5, "phoenix", 8000, "estimate")
    assert e["totalCostCents"] == 9500.5 and e["netCents"] == 90499.5
    assert e["roiPct"] == 952.6 and e["costToValuePct"] == 9.5
    assert e["paybackMonths"] == 0.6 and e["costComplete"] is True
    assert (e["revenueCents"], e["expenditureCents"], e["estimatedInfraCostCents"]) == (100000, 9500.5, 8000)


def test_unknown_token_cost_is_none_never_zero():
    e = agent_economics(value_amount_dollars=100, hours_saved_monthly=0, hourly_rate=RATE,
                        token_cost_cents=None, token_source="none", infra={"cents": 2000, "source": "estimate"})
    assert e["tokenCostCents"] is None and e["tokenSource"] == "none"
    assert e["costComplete"] is False and e["totalCostCents"] == 2000


def test_undeclared_value_has_no_roi_and_zero_cost_has_no_roi():
    undeclared = agent_economics(value_amount_dollars=0, hours_saved_monthly=0, hourly_rate=RATE,
                                 token_cost_cents=100, token_source="phoenix", infra={"cents": 8000, "source": "estimate"})
    assert undeclared["valueDeclared"] is False and undeclared["netAvailable"] is False
    assert undeclared["roiPct"] is None and undeclared["costToValuePct"] is None
    free = agent_economics(value_amount_dollars=500, hours_saved_monthly=0, hourly_rate=RATE,
                           token_cost_cents=0, token_source="phoenix", infra={"cents": 0, "source": "estimate"})
    assert free["roiPct"] is None and free["netCents"] == 50000


def test_efficiency_rating_bands():
    assert efficiency_rating(500, 10000, True) == "efficient"
    assert efficiency_rating(2000, 10000, True) == "moderate"
    assert efficiency_rating(9000, 10000, True) == "below_average"
    assert efficiency_rating(12000, 10000, True) == "inefficient"
    assert efficiency_rating(100, 10000, False) == "insufficient_data"
    assert efficiency_rating(100, 0, True) == "not_declared"


# ── monthly_trend ────────────────────────────────────────────────────────────

def test_monthly_trend_marks_unknown_months_and_computes_net_and_roi():
    months = ["2026-07", "2026-08", "2026-09"]
    trend = monthly_trend(
        {"2026-08": 500.0, "2026-09": 300.0},
        {"2026-07": None, "2026-08": {"cents": 8000, "source": "estimate"}, "2026-09": {"cents": 9000, "source": "declared"}},
        10000, months, active_from="2026-08", current_month="2026-09",
    )
    july, aug, sep = trend
    assert july == {"month": "2026-07", "tokenCostCents": None, "infraCostCents": None, "infraSource": None,
                    "totalCostCents": None, "valueCents": None, "netCents": None, "roiPct": None, "partial": False}
    assert (aug["totalCostCents"], aug["valueCents"], aug["netCents"], aug["roiPct"]) == (8500.0, 10000, 1500.0, 17.6)
    assert sep["partial"] is True and sep["infraSource"] == "declared"


def test_monthly_trend_defaults_to_the_last_six_months():
    trend = monthly_trend({}, {}, 0)
    assert len(trend) == 6 and trend[-1]["month"] == datetime.now(timezone.utc).strftime("%Y-%m")
    assert recent_months(date(2026, 2, 3)) == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]


# ── financial flags ──────────────────────────────────────────────────────────

def _month(month, cost, value, token=1.0, infra_source="estimate", partial=False):
    return {"month": month, "totalCostCents": cost, "valueCents": value, "tokenCostCents": token,
            "infraSource": infra_source, "partial": partial}


def _flags(**over):
    args = dict(stage="Production", trend=[], infra_cost_cents=0, infra_source="estimate",
                calls_last_30d=None, has_spend=False, has_budget=True, token_source="phoenix")
    return evaluate_financial_flags(**{**args, **over})


def test_negative_roi_needs_two_consecutive_complete_months():
    two = [_month("2026-07", 12000, 5000), _month("2026-08", 9000, 5000), _month("2026-09", 1, 5000, partial=True)]
    [flag] = _flags(trend=two)
    assert (flag["rule_id"], flag["severity"], flag["source"]) == ("negative_roi_2_months", "HIGH", "phoenix")
    assert "2026-07" in flag["description"] and "2026-08" in flag["description"]
    one = [_month("2026-07", 1000, 5000), _month("2026-08", 9000, 5000)]
    assert _flags(trend=one) == []


def test_negative_roi_ignores_months_whose_only_cost_is_the_estimate():
    estimate_only = [_month("2026-07", 8000, 5000, token=None), _month("2026-08", 8000, 5000, token=None)]
    assert _flags(trend=estimate_only) == []
    declared = [_month(m, 8000, 5000, token=None, infra_source="declared") for m in ("2026-07", "2026-08")]
    assert [f["rule_id"] for f in _flags(trend=declared)] == ["negative_roi_2_months"]


def test_idle_cost_and_no_budget():
    [idle] = _flags(infra_cost_cents=8000, calls_last_30d=0)
    assert (idle["rule_id"], idle["severity"]) == ("idle_cost", "MEDIUM")
    assert _flags(infra_cost_cents=8000, calls_last_30d=None) == []       # not measured is not idle
    assert _flags(infra_cost_cents=8000, calls_last_30d=4) == []
    [nb] = _flags(has_spend=True, has_budget=False, token_source="seed")
    assert (nb["rule_id"], nb["severity"], nb["source"]) == ("no_budget", "LOW", "seed")
    assert set(nb) == {"rule_id", "severity", "title", "description", "source"}


def test_flags_only_apply_to_production():
    assert _flags(stage="Testing", infra_cost_cents=2000, calls_last_30d=0, has_spend=True, has_budget=False) == []


# ── build_economics ──────────────────────────────────────────────────────────

def _agent(**over):
    return {"id": "a1", "name": "A1", "stage": "Production", "value_amount": 0, "value_type": None,
            "hours_saved_monthly": 0, "phoenix_project": None, "created_at": date(2026, 1, 5), **over}


def _row(day, cost, calls=10, priced=True, source="phoenix"):
    return {"day": day, "model": "gpt-4.1-mini", "input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0,
            "calls": calls, "cost_cents": cost, "priced": priced, "source": source}


def _build(agent=None, usage=None, infra_rows=(), profile=None, has_budget=False, ingested=False):
    return build_economics(agent or _agent(), usage or {"rows": [], "source": "none"}, list(infra_rows), profile,
                           has_budget=has_budget, usage_ingested=ingested, today=TODAY, hourly_rate=RATE)


def test_unlinked_agent_without_rows_has_no_usage_data():
    e = _build()
    assert e["tokenCostCents"] is None and e["tokenSource"] == "none"
    assert e["token"]["status"] == "no_usage_data" and e["token"]["callsLast30d"] is None
    assert (e["infraSource"], e["infraCostCents"]) == ("estimate", 8000)
    assert e["costComplete"] is False and e["efficiencyRating"] == "not_declared"
    assert all(m["tokenCostCents"] is None for m in e["trend"])
    assert [f["rule_id"] for f in e["financialFlags"]] == []                # an estimate is not spend


def test_linked_agent_awaiting_ingestion_vs_ingested_with_no_calls():
    waiting = _build(_agent(phoenix_project="retail-onboarding"))
    assert waiting["token"]["status"] == "awaiting_ingestion" and waiting["tokenCostCents"] is None
    quiet = _build(_agent(phoenix_project="retail-onboarding"), ingested=True)
    assert quiet["token"]["status"] == "no_calls"
    assert (quiet["tokenCostCents"], quiet["tokenSource"], quiet["token"]["callsLast30d"]) == (0.0, "phoenix", 0)
    assert [f["rule_id"] for f in quiet["financialFlags"]] == ["idle_cost"]


def test_seed_rows_are_demo_data():
    usage = {"rows": [_row(date(2026, 9, 3), 1234.0, source="seed")], "source": "seed", "unpriced": []}
    e = _build(_agent(id="inv-recon", value_amount=186000, hours_saved_monthly=640), usage)
    assert (e["tokenSource"], e["token"]["status"], e["tokenCostCents"]) == ("seed", "demo", 1234.0)
    assert e["token"]["callsLast30d"] is None                              # demo calls never make an agent look busy
    assert e["realizedValueCents"] == 640 * 60 * 100
    assert e["trend"][-1]["tokenCostCents"] == 1234.0 and e["trend"][-1]["partial"] is True
    assert [f["rule_id"] for f in e["financialFlags"]] == ["no_budget"]
    assert e["financialFlags"][0]["source"] == "seed"


def test_phoenix_rows_run_rate_and_unpriced_models():
    rows = [_row(date(2026, 9, d), 100.0) for d in range(1, 19)]
    e = _build(_agent(phoenix_project="p", value_amount=100), {"rows": rows, "source": "phoenix", "unpriced": []})
    assert e["token"]["status"] == "measured" and e["token"]["monthToDateCents"] == 1800.0
    assert e["tokenCostCents"] == 3000.0                                   # 1800 + 100/day x 12 days left
    assert e["token"]["callsLast30d"] == 180 and e["token"]["pricing"] == "ok"

    unpriced = [_row(date(2026, 9, 10), 0.0, priced=False)]
    missing = _build(_agent(phoenix_project="p"), {"rows": unpriced, "source": "phoenix", "unpriced": ["gpt-9"]})
    assert missing["token"]["pricing"] == "missing" and missing["tokenCostCents"] is None
    assert missing["token"]["unpricedModels"] == ["gpt-9"] and missing["tokenSource"] == "phoenix"
    partial = _build(_agent(phoenix_project="p"), {"rows": rows + unpriced, "source": "phoenix", "unpriced": ["gpt-9"]})
    assert partial["token"]["pricing"] == "partial" and partial["tokenCostCents"] == 3000.0


def test_metered_infra_is_a_monthly_run_rate_and_beats_declared():
    infra = [{"cost_date": date(2026, 9, d), "resource_id": "/subscriptions/s/rg/x", "service_name": "svc",
              "cost_cents": 100, "allocation": "tag"} for d in range(1, 11)]
    e = _build(infra_rows=infra, profile={"monthly_cost_cents": 5000, "effective_from": None, "components": []})
    assert (e["infraSource"], e["infraCostCents"]) == ("metered", 3000.0)  # 1000 over 10 days x 30
    assert e["infra"]["meteredMonthToDateCents"] == 1000 and e["infra"]["meteredThrough"] == "2026-09-10"
    assert e["infra"]["byResource"][0]["cents"] == 1000


def test_declared_infra_and_its_effective_date():
    profile = {"monthly_cost_cents": 5000, "effective_from": date(2026, 8, 1),
               "components": [{"name": "Container App", "costCents": 3000}, {"name": "Setup", "costCents": 20000, "recurring": False}, "  "]}
    e = _build(_agent(value_amount=1000), profile=profile)
    assert (e["infraSource"], e["infraCostCents"]) == ("declared", 5000)
    assert e["oneTimeCostCents"] == 20000 and e["paybackMonths"] == 0.2
    assert [c["name"] for c in e["infra"]["components"]] == ["Container App", "Setup"]
    by_month = {m["month"]: m["infraSource"] for m in e["trend"]}
    assert by_month["2026-08"] == "declared" and by_month["2026-07"] == "estimate"
    future = _build(profile={**profile, "effective_from": date(2026, 10, 1)})
    assert future["infraSource"] == "estimate"


def test_build_flags_negative_roi_from_real_monthly_cost():
    rows = [_row(date(2026, 7, 10), 4000.0), _row(date(2026, 8, 10), 4000.0)]
    e = _build(_agent(phoenix_project="p", value_amount=50, created_at=date(2026, 7, 1)),
               {"rows": rows, "source": "phoenix", "unpriced": []})
    assert [f["rule_id"] for f in e["financialFlags"]] == ["negative_roi_2_months", "idle_cost"]
    july = next(m for m in e["trend"] if m["month"] == "2026-07")
    assert (july["tokenCostCents"], july["infraCostCents"], july["netCents"]) == (4000.0, 8000, -7000.0)
    assert e["trend"][0]["valueCents"] is None                             # before the agent existed


# ── Router ───────────────────────────────────────────────────────────────────

DOT = "digital-onboarding-test-a8bfa826"
INV = "inv-recon"
SEED_CENTS = 1000.0                                                        # 2M x $2.50 + 0.5M x $10 per 1M


def _seed_run_rate() -> float:
    today = datetime.now(timezone.utc).date()
    return round(projected_period_end_cents([{"day": today, "cost_cents": SEED_CENTS}], today), 2)


@pytest_asyncio.fixture
async def client(monkeypatch):
    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    import db.models  # noqa: F401
    from api.auth import require_admin, require_read, require_update
    from api.routers.ops import economics

    settings = get_settings()
    for field in ("azure_cost_scope", "azure_tenant_id", "azure_client_id", "azure_client_secret"):
        monkeypatch.setattr(settings, field, "")

    today = datetime.now(timezone.utc).date()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id=DOT, org_id="org-default", name="Digital Onboarding Test", slug=DOT, owner="Ops",
                        lifecycle_stage="Production", phoenix_project="retail-onboarding", value_amount=0))
            s.add(Agent(id=INV, org_id="org-default", name="Invoice Reconciliation Agent", slug=INV, owner="Fin",
                        lifecycle_stage="Production", value_amount=186000, value_type="Cost avoidance",
                        hours_saved_monthly=640))
            s.add(ModelTokenPrice(id="p-gpt5", model_name="GPT-5", provider="OpenAI", input_price_per_1m=2.5,
                                  output_price_per_1m=10.0, tier="premium"))
            s.add(AgentTokenUsage(agent_id=INV, bucket=datetime.combine(today, time.min, tzinfo=timezone.utc),
                                  model_name="GPT-5", invocation_count=1000, input_tokens=2_000_000,
                                  output_tokens=500_000, source="seed"))
        app = FastAPI()
        app.include_router(economics.router)
        for dep in (require_read, require_update, require_admin):
            app.dependency_overrides[dep] = lambda: {"user_id": "tester", "role": "admin"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await engine.dispose()


async def _audit_actions():
    async with get_db_session() as s:
        return [a.action for a in (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()]


@pytest.mark.asyncio
async def test_economics_endpoint_linked_agent_without_rows(client):
    r = await client.get(f"/api/v1/agents/{DOT}/economics")
    assert r.status_code == 200
    e = r.json()
    assert e["tokenCostCents"] is None and e["tokenSource"] == "none"
    assert e["token"]["status"] == "awaiting_ingestion" and e["token"]["phoenixLinked"] is True
    assert (e["infraSource"], e["infraCostCents"]) == ("estimate", 8000)
    assert e["hourlyRate"] == get_settings().blended_hourly_rate_usd and len(e["trend"]) == 6
    for key in ("agentId", "stage", "revenueCents", "tokenCostCents", "estimatedInfraCostCents", "expenditureCents", "netCents"):
        assert key in e
    assert (await client.get("/api/v1/agents/nope/economics")).status_code == 404


@pytest.mark.asyncio
async def test_economics_endpoint_seed_agent(client):
    e = (await client.get(f"/api/v1/agents/{INV}/economics")).json()
    assert e["tokenSource"] == "seed" and e["token"]["monthToDateCents"] == SEED_CENTS
    assert e["tokenCostCents"] == _seed_run_rate()
    assert e["valueCents"] == 18600000 and e["realizedValueCents"] == 640 * 60 * 100


@pytest.mark.asyncio
async def test_declared_infra_profile_round_trip(client):
    assert (await client.get(f"/api/v1/agents/{DOT}/infra-profile")).json()["exists"] is False
    body = {"platform": "Azure Container Apps", "resourceGroup": " rg-onboarding ", "monthlyCostCents": 12345,
            "components": [{"name": "Container App", "costCents": 9000}, "Cosmos DB", ""], "effectiveFrom": None}
    r = await client.put(f"/api/v1/agents/{DOT}/infra-profile", json=body)
    assert r.status_code == 200
    p = r.json()
    assert p["declared"] is True and p["resourceGroup"] == "rg-onboarding" and p["updatedBy"] == "tester"
    assert p["components"] == [{"name": "Container App", "costCents": 9000, "recurring": True},
                               {"name": "Cosmos DB", "costCents": None, "recurring": True}]
    e = (await client.get(f"/api/v1/agents/{DOT}/economics")).json()
    assert (e["infraSource"], e["infraCostCents"]) == ("declared", 12345)

    # Saving without a cost keeps the details but is not a declared $0.
    p = (await client.put(f"/api/v1/agents/{DOT}/infra-profile", json={**body, "monthlyCostCents": None})).json()
    assert p["declared"] is False and p["platform"] == "Azure Container Apps"
    assert (await client.get(f"/api/v1/agents/{DOT}/economics")).json()["infraSource"] == "estimate"
    assert (await client.put(f"/api/v1/agents/{DOT}/infra-profile", json={"monthlyCostCents": -1})).status_code == 422
    assert await _audit_actions() == ["infra_profile.update", "infra_profile.update"]


@pytest.mark.asyncio
async def test_resource_links_validate_and_audit(client):
    base = f"/api/v1/agents/{DOT}/resource-links"
    assert (await client.get(base)).json() == {"agentId": DOT, "links": []}
    for bad in ({"resourceId": "rg-onboarding"}, {"resourceId": "/subscriptions/"},
                {"resourceId": "/subscriptions/s1/resourceGroups/rg", "sharePct": 0},
                {"resourceId": "/subscriptions/s1/resourceGroups/rg", "sharePct": 101}):
        assert (await client.post(base, json=bad)).status_code == 422, bad

    rg = "/subscriptions/s1/resourceGroups/rg-shared-ai"
    r = await client.post(base, json={"resourceId": rg + "/", "sharePct": 60})
    assert r.status_code == 201
    link = r.json()
    assert (link["resourceId"], link["sharePct"], link["kind"], link["warning"]) == (rg, 60, "resource_group", None)
    assert (await client.post(base, json={"resourceId": rg.upper()})).status_code == 409
    over = (await client.post(f"/api/v1/agents/{INV}/resource-links", json={"resourceId": rg, "sharePct": 50})).json()
    assert over["totalClaimedPct"] == 110 and "scales" in over["warning"]

    listed = (await client.get(base)).json()["links"]
    assert [(x["id"], x["totalClaimedPct"]) for x in listed] == [(link["id"], 110)]
    assert (await client.delete(f"/api/v1/agents/{INV}/resource-links/{link['id']}")).status_code == 404
    assert (await client.delete(f"{base}/{link['id']}")).json()["deleted"] is True
    assert (await client.get(base)).json()["links"] == []
    assert await _audit_actions() == ["resource_link.create", "resource_link.create", "resource_link.delete"]


@pytest.mark.asyncio
async def test_infra_cost_status_and_collect_when_not_configured(client):
    s = (await client.get("/api/v1/infra-costs/status")).json()
    assert s["configured"] is False and s["status"] == "not_configured" and s["lastRun"] is None
    assert s["missing"] == ["AZURE_COST_SCOPE", "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]
    assert s["tagKey"] == "agent-id" and s["scope"] is None and s["requiredRole"] == "Cost Management Reader"

    run = (await client.post("/api/v1/infra-costs/collect")).json()
    assert run["status"] == "not_configured" and run["runId"]
    last = (await client.get("/api/v1/infra-costs/status")).json()["lastRun"]
    assert (last["runId"], last["status"]) == (run["runId"], "not_configured")
    assert "infra_costs.collect" in await _audit_actions()
    assert (await client.post("/api/v1/infra-costs/collect?agentId=nope")).status_code == 404


@pytest.mark.asyncio
async def test_portfolio_keeps_legacy_keys(client):
    p = (await client.get("/api/v1/value/economics")).json()
    assert p["totalRevenueCents"] == 18600000
    cost = round(_seed_run_rate() + 8000 + 8000, 2)
    assert p["totalExpenditureCents"] == p["totalCostCents"] == cost
    assert p["totalNetCents"] == round(18600000 - cost, 2)
    assert p["agentsWithoutUsageData"] == 1 and p["tokenSources"] == {"none": 1, "seed": 1}
    assert [a["agentId"] for a in p["agents"]] == [INV, DOT]
    for a in p["agents"]:
        assert {"name", "revenueCents", "expenditureCents", "netCents"} <= set(a)


@pytest.mark.asyncio
async def test_business_outcome_keeps_legacy_keys(client):
    inv = (await client.get(f"/api/v1/agents/{INV}/cost/business-outcome")).json()
    assert {"agent_id", "total_cost", "business_outcome", "cost_per_outcome", "efficiency_rating"} <= set(inv)
    total = round((_seed_run_rate() + 8000) / 100, 2)
    assert (inv["total_cost"], inv["business_outcome"]) == (total, 186000.0)
    assert inv["cost_per_outcome"] == round((_seed_run_rate() + 8000) / 100 / 186000, 4)
    assert inv["efficiency_rating"] == "efficient"
    dot = (await client.get(f"/api/v1/agents/{DOT}/cost/business-outcome")).json()
    assert dot["cost_per_outcome"] is None and dot["efficiency_rating"] == "not_declared"
