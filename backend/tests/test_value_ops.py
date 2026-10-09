"""Value and spend: value method and attestation, outcomes and cost per outcome,
the model what-if, usage without tracing, idle and duplicate spend, the Production
scenario, the scorecard PDF and the Azure cost setup. Runs against a throwaway DB."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from governance import value as gv


def test_value_state_follows_declarations_and_finance_checks():
    assert gv.method_of(None, "Projected cost avoidance") == "cost_avoidance" and gv.method_of(None, None, 10) == "time_saved"
    assert gv.value_state(0, None, None)["state"] == "none"
    assert gv.value_state(500_000, "cost_avoidance", None)["state"] == "declared"
    att = {"status": "adjusted", "declaredCents": 500_000, "declaredMethod": "cost_avoidance", "attestedCents": 300_000}
    assert gv.value_state(500_000, "cost_avoidance", att) == {"state": "adjusted", "cents": 300_000, "label": "Adjusted by finance"}
    assert gv.value_state(600_000, "cost_avoidance", att)["state"] == "stale"
    assert gv.value_state(500_000, "risk_avoided", att)["cents"] == 500_000


def test_whatif_idle_duplicates_and_scenario():
    rows = gv.whatif({"input": 2_000_000, "output": 1_000_000, "cached": 0}, 1500,
                     [{"model": "big", "input": 5, "output": 10}, {"model": "small", "input": 0.5, "output": 1}], price_change_pct=-10)
    assert [(r["model"], r["cents"]) for r in rows] == [("small", 180.0), ("big", 1800.0)] and rows[0]["changePct"] == -88.0
    idle = gv.idle_spend([{"agentId": "a", "name": "A", "stage": "Production", "callsLast30d": 0, "infraCents": 4000, "infraSource": "metered", "tokenCents": 0},
                          {"agentId": "b", "name": "B", "stage": "Production", "callsLast30d": None, "infraCents": 4000},
                          {"agentId": "c", "name": "C", "stage": "Testing", "callsLast30d": 0, "infraCents": 4000}])
    assert [i["agentId"] for i in idle] == ["a"] and "metered" in idle[0]["text"]
    dup = gv.duplicate_spend([{"a": {"id": "a", "name": "A"}, "b": {"id": "b", "name": "B"}, "reason": "the same API endpoint"},
                              {"a": {"id": "b", "name": "B"}, "b": {"id": "a", "name": "A"}, "reason": "the same API endpoint"}],
                             {"a": 1000, "b": 300})
    assert len(dup) == 1 and dup[0]["possibleSavingCents"] == 300
    sc = gv.scenario([{"agentId": "x", "name": "X", "stage": "Testing", "valueCents": 100_000, "valueState": "attested",
                       "tokenCents": 2000, "infraCents": 0, "infraSource": "estimate"},
                      {"agentId": "p", "name": "P", "stage": "Production", "valueCents": 5, "tokenCents": 0, "infraCents": 0}], 15_000)
    assert (sc["valueCents"], sc["costCents"], sc["attestedShare"]) == (100_000, 17_000, 100)


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentTokenUsage, Department, ModelTokenPrice, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(timezone.utc)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Department(id="dept-fin", org_id="org-default", name="Finance"))
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("fin", "Fay", "Finance Reviewer"), ("po", "Pat", "Product Owner")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="traced", org_id="org-default", slug="traced", name="Invoice Matcher", owner="Ops", dept_id="dept-fin",
                    description="Matches invoices to purchase orders", lifecycle_stage="Production", phoenix_project="inv",
                    api_endpoint="https://inv.example/api"))
        s.add(Agent(id="plain", org_id="org-default", slug="plain", name="Invoice Matcher Two", owner="Ops", dept_id="dept-fin",
                    description="Matches invoices to purchase orders", lifecycle_stage="Testing", api_endpoint="https://inv.example/api"))
        s.add(ModelTokenPrice(id="p1", model_name="gpt-4o", provider="openai", input_price_per_1m=2.5, output_price_per_1m=10, tier="standard"))
        s.add(ModelTokenPrice(id="p2", model_name="gpt-4o-mini", provider="openai", input_price_per_1m=0.15, output_price_per_1m=0.6, tier="standard"))
        s.add(AgentTokenUsage(agent_id="traced", bucket=now - timedelta(days=2), model_name="gpt-4o", source="phoenix",
                              invocation_count=10, input_tokens=2_000_000, output_tokens=0))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_value_is_declared_with_a_method_and_attested_by_finance(setup):
    c, who = setup
    r = await c.put("/api/v1/agents/traced/value", json={"method": "time_saved", "basis": "short"})
    assert r.status_code == 422
    v = (await c.put("/api/v1/agents/traced/value", json={"method": "time_saved", "hoursSavedMonthly": 100, "hourlyRateCents": 5000,
                                                         "basis": "100 hours of manual matching a month at the team's rate"})).json()
    assert v["declaredCents"] == 500_000 and v["state"]["state"] == "declared" and v["methodLabel"] == "Time saved"
    who.update(id="po", role="Product Owner")
    assert (await c.post("/api/v1/agents/traced/value/attest", json={"status": "attested", "note": "x" * 25})).status_code == 403
    who.update(id="fin", role="Finance Reviewer")
    v = (await c.post("/api/v1/agents/traced/value/attest", json={"status": "adjusted", "amountDollars": 3000,
                                                                 "note": "Only 60 of the 100 hours are moved to other work"})).json()
    assert v["state"] == {"state": "adjusted", "cents": 300_000, "label": "Adjusted by finance"} and v["attestations"][0]["attestedBy"] == "Fay"
    econ = (await c.get("/api/v1/agents/traced/economics")).json()
    assert econ["valueCents"] == 300_000 and econ["valueState"] == "adjusted" and econ["valueDeclaredCents"] == 500_000
    who.update(id="adm", role="Registry Admin")
    await c.put("/api/v1/agents/traced/value", json={"method": "cost_avoidance", "amountDollars": 4000,
                                                     "basis": "Two contractor days a week are no longer bought"})
    econ = (await c.get("/api/v1/agents/traced/economics")).json()
    assert econ["valueState"] == "stale" and econ["valueCents"] == 400_000


@pytest.mark.asyncio
async def test_outcomes_give_a_cost_per_outcome(setup):
    c, _ = setup
    assert (await c.post("/api/v1/agents/traced/outcomes", json={"outcome": "invoice matched", "count": 50})).status_code == 200
    csv_text = f"day,outcome,count\n{(date.today() - timedelta(days=1)).isoformat()},invoice matched,150\n"
    r = await c.post("/api/v1/agents/traced/outcomes/import", content=csv_text, headers={"content-type": "text/csv"})
    assert r.json() == {"stored": 1}
    bad = await c.post("/api/v1/agents/traced/outcomes/import", content="day,count\n", headers={"content-type": "text/csv"})
    assert bad.status_code == 422 and "header" in bad.json()["detail"]
    o = (await c.get("/api/v1/agents/traced/outcomes")).json()
    out = o["outcomes"][0]
    assert out["outcome"] == "invoice matched" and out["count"] == 200
    assert o["tokenCostCents"] == 500.0 and out["costPerOutcomeCents"] == round(o["costCents"] / 200, 2)


@pytest.mark.asyncio
async def test_whatif_and_usage_without_tracing(setup):
    c, _ = setup
    w = (await c.get("/api/v1/agents/traced/model-whatif")).json()
    assert w["currentCents"] == 500.0 and [m["model"] for m in w["models"]] == ["gpt-4o-mini", "gpt-4o"] and "quality" in w["caveat"]
    refused = await c.post("/api/v1/agents/traced/usage/manual", json={"day": "2026-10-01", "model": "gpt-4o", "calls": 3})
    assert refused.status_code == 409
    csv_text = "day,model,calls,input_tokens,output_tokens\n" + f"{date.today().isoformat()},gpt-4o,40,1000000,0\n"
    assert (await c.post("/api/v1/agents/plain/usage/import", content=csv_text, headers={"content-type": "text/csv"})).json() == {"stored": 1}
    econ = (await c.get("/api/v1/agents/plain/economics")).json()
    assert econ["tokenSource"] == "manual" and econ["token"]["status"] == "measured" and econ["tokenCostCents"] > 0
    assert (await c.get("/api/v1/agents/plain/usage/manual")).json()["rows"][0]["calls"] == 40


@pytest.mark.asyncio
async def test_spend_review_scenario_and_scorecard(setup):
    c, _ = setup
    from orchestrations.waste_detection import review_spend
    review = (await c.get("/api/v1/portfolio/spend-review")).json()
    assert review["idle"] == []                                   # the traced agent was called 2 days ago
    [dup] = review["duplicates"]                                  # same endpoint, and both cost money (tokens, hosting estimate)
    assert dup["reason"] == "the same API endpoint" and {a["id"] for a in dup["agents"]} == {"traced", "plain"}
    result = await review_spend()
    assert result["status"] == "ok" and result["opened"] == 1 and result["duplicates"] == 1
    assert (await review_spend())["opened"] == 0                  # a second run updates, it does not add
    sc = (await c.get("/api/v1/portfolio/scenario")).json()
    assert [a["agentId"] for a in sc["agents"]] == ["plain"] and sc["agents"][0]["infraBasis"] == "estimate"
    card = (await c.get("/api/v1/portfolio/scorecard?unit=dept-fin")).json()
    assert card["scope"] == "Finance" and card["count"] == 2 and card["reuseSavingsCents"] is None
    assert (await c.put("/api/v1/value/settings", json={"buildCostCents": 5_000_000})).status_code == 200
    pdf = await c.get("/api/v1/portfolio/scorecard?format=pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-1.4") and b"%%EOF" in pdf.content[-10:]


@pytest.mark.asyncio
async def test_azure_cost_setup_is_saved_without_returning_the_secret(setup):
    c, _ = setup
    r = (await c.put("/api/v1/infra-costs/config", json={"tenantId": "t", "clientId": "c", "clientSecret": "s3cret",
                                                        "scope": "/subscriptions/1234567890ab/resourceGroups/rg"})).json()
    assert r["configured"] is True and r["configSource"] == "settings" and r["secretSet"] is True
    assert "s3cret" not in str(r) and r["scope"] == "/subscriptions/****90ab/resourceGroups/rg"
    r = (await c.put("/api/v1/infra-costs/config", json={"tenantId": "t2", "clientId": "c", "scope": "/subscriptions/1234567890ab"})).json()
    assert r["tenantId"] == "t2" and r["secretSet"] is True                 # an empty secret keeps the saved one
