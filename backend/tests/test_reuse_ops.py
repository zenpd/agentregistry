"""Reuse: observed consumers, reuse figures, chargeback, search gaps, programme
health, starting from a certified agent and the notices to consumer teams.
Runs against a throwaway DB."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from discovery import observed_deps
from governance import reuse_metrics as rm


def test_callers_come_from_the_consumer_team_attribute_once_per_trace():
    spans = [{"context": {"trace_id": "t1"}, "start_time": "2026-10-01T10:00:00Z", "attributes": {"consumer.team": "Payments"}},
             {"context": {"trace_id": "t1"}, "start_time": "2026-10-01T10:00:01Z", "attributes": {"consumer.team": "Payments"}},
             {"context": {"trace_id": "t2"}, "start_time": "2026-10-03T09:00:00Z", "attributes": {"caller": {"team": "Lending"}}},
             {"context": {"trace_id": "t3"}, "start_time": "2026-10-04T09:00:00Z", "attributes": {"consumer.team": "Payments"}}]
    got = observed_deps.callers(spans)
    assert [(c["caller"], c["calls"]) for c in got] == [("Payments", 2), ("Lending", 1)]
    assert got[0]["firstSeen"].date() == date(2026, 10, 1) and got[0]["lastSeen"].date() == date(2026, 10, 4)


def test_consumer_view_and_reuse_figures():
    v = rm.consumer_view([{"team": "Payments", "approvedAt": "2026-09-01"}, {"team": "Lending", "approvedAt": "2026-09-02"}],
                         ["payments ", "Old Team"], [{"caller": "Payments", "calls": 4}, {"caller": "Shadow", "calls": 2}])
    status = {r["name"]: r["status"] for r in v["consumers"]}
    assert status == {"Payments": "both", "Lending": "approved_not_calling", "Shadow": "calling_not_approved", "Old Team": "declared_only"}
    assert v["callingNotApproved"] == ["Shadow"] and v["approvedNotCalling"] == ["Lending"]
    assert rm.days_to_first_call("2026-09-01", "2026-09-05T10:00:00Z") == 4 and rm.days_to_first_call("2026-09-05", "2026-09-01") is None
    f = rm.reuse_figures([{"id": "a", "name": "A", "unit": "Finance", "stage": "Production"},
                          {"id": "b", "name": "B", "unit": "Finance", "stage": "Production"}],
                         [{"agentId": "a", "team": "Payments", "approvedAt": date(2026, 9, 1)}],
                         [{"agentId": "a", "caller": "payments", "kind": "team", "firstSeen": datetime(2026, 9, 3, tzinfo=timezone.utc)}])
    assert f["total"] == {"productionAgents": 2, "reusedAgents": 1, "reuseRate": 50, "buildsAvoided": 1,
                          "medianDaysToFirstCall": 2, "firstCallsMeasured": 1}


def test_chargeback_splits_by_calls_or_equally():
    by_calls = rm.chargeback(1000, "Finance", ["Payments", "Lending"], {"payments": 6, "lending": 2, "shadow": 2})
    assert by_calls["basis"] == "calls" and {s["payer"]: s["cents"] for s in by_calls["shares"]} == {"Payments": 600, "Lending": 200, "Finance": 200}
    equal = rm.chargeback(900, "Finance", ["Payments", "Lending"], {})
    assert equal["basis"] == "equal" and [s["cents"] for s in equal["shares"]] == [300, 300, 300]
    assert rm.chargeback(500, "Finance", [], {})["shares"] == [{"payer": "Finance", "share": 100, "cents": 500}]
    assert rm.coalesce_search({"query": "invoi"}, "invoice match", 10) and not rm.coalesce_search({"query": "invoice"}, "payroll", 10)


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import (Agent, AgentAccessRequest, AgentTokenUsage, Department, GovernanceReview, ModelTokenPrice,
                           ObservedConsumer, Organization, User)
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(timezone.utc)
    later = now + timedelta(days=200)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Department(id="dept-fin", org_id="org-default", name="Finance"))
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("pat", "Pat", "Product Owner")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="cert", org_id="org-default", slug="cert", name="Invoice Matcher", owner="Ops", dept_id="dept-fin",
                    description="Matches invoices to purchase orders", lifecycle_stage="Production", phoenix_project="inv",
                    capabilities=["Match invoices"], inputs=["invoice"], outputs=["match"], sla="99.5%", consumers=["Payments"]))
        for gate in ("arb", "security", "dp"):
            s.add(GovernanceReview(id=f"cert-{gate}", agent_id="cert", gate=gate, status="Approved", expires_at=later))
        s.add(AgentAccessRequest(id="g1", agent_id="cert", requester_id="pat", requester_name="Pat", team="Payments", purpose="match",
                                 status="approved", added_to_consumers=True, decided_at=now - timedelta(days=10)))
        s.add(ObservedConsumer(id="o1", agent_id="cert", kind="team", caller="Payments", calls=8,
                               first_seen=now - timedelta(days=7), last_seen=now - timedelta(days=1), updated_at=now))
        s.add(ObservedConsumer(id="o2", agent_id="cert", kind="team", caller="Shadow Team", calls=2,
                               first_seen=now - timedelta(days=3), last_seen=now - timedelta(days=2), updated_at=now))
        s.add(ModelTokenPrice(id="p1", model_name="gpt-4o", provider="openai", input_price_per_1m=2.5, output_price_per_1m=10, tier="standard"))
        s.add(AgentTokenUsage(agent_id="cert", bucket=now.replace(day=1, hour=1), model_name="gpt-4o", source="phoenix",
                              invocation_count=10, input_tokens=4_000_000, output_tokens=0))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_consumers_tab_marks_approved_seen_or_both(setup):
    c, _ = setup
    v = (await c.get("/api/v1/agents/cert/consumers")).json()
    status = {r["name"]: r["status"] for r in v["consumers"]}
    assert status == {"Payments": "both", "Shadow Team": "calling_not_approved"}
    assert v["attribute"] == "consumer.team" and v["buildsAvoided"] == 1 and v["medianDaysToFirstCall"] == 3


@pytest.mark.asyncio
async def test_chargeback_by_calls_seen(setup):
    c, _ = setup
    r = (await c.get("/api/v1/agents/cert/chargeback")).json()
    assert r["costCents"] == 1000 and r["basis"] == "calls"
    assert {s["payer"]: s["cents"] for s in r["shares"]} == {"Payments": 800, "Finance": 200}
    csv_text = (await c.get("/api/v1/portfolio/chargeback?format=csv")).text
    assert "Invoice Matcher" in csv_text and "Payments" in csv_text


@pytest.mark.asyncio
async def test_empty_searches_become_search_gaps_and_health_reports_them(setup):
    c, _ = setup
    for q in ("payr", "payroll ch", "payroll check"):                    # typing on, one row
        await c.get(f"/api/v1/agents/?q={q}")
    await c.get("/api/v1/agents/?q=invoice")                                # found something: not a gap
    gaps = (await c.get("/api/v1/portfolio/search-gaps")).json()["gaps"]
    assert [(g["term"], g["times"]) for g in gaps] == [("payroll check", 1)]
    h = (await c.get("/api/v1/portfolio/health")).json()
    assert h["known"]["registered"] == 1 and h["owners"]["nameOnly"] == 1 and h["reuse"]["reuseRate"] == 100
    assert h["searchGaps"][0]["term"] == "payroll check" and h["overdueReviews"]["count"] == 0


@pytest.mark.asyncio
async def test_a_registration_can_start_from_a_certified_agent(setup):
    c, _ = setup
    t = (await c.get("/api/v1/agents/cert/template")).json()
    assert t["fields"]["capabilities"] == ["Match invoices"] and "owner" not in t["fields"]
    r = await c.post("/api/v1/agents/", json={"name": "Invoice Matcher EU", "dept": "dept-fin", "owner": "EU Ops", "ai_type": "Autonomous Agent",
                                              "description": "Matches invoices for the EU entities", "stage": "Ideation",
                                              "started_from_agent_id": "cert", **{k: v for k, v in t["fields"].items() if k != "ai_type"},
                                              "reuse_justification": "Different legal entities and a separate ledger in the EU"})
    assert r.status_code == 200, r.text
    new = r.json()["id"]
    assert (await c.get(f"/api/v1/agents/{new}/consumers")).json()["startedFrom"] == {"id": "cert", "name": "Invoice Matcher"}
    assert (await c.get(f"/api/v1/agents/{new}/template")).status_code == 409


@pytest.mark.asyncio
async def test_teams_with_access_hear_about_a_contract_change(setup):
    c, who = setup
    r = (await c.put("/api/v1/agents/cert/contract", json={"sla": "99.9%"})).json()
    assert r["told"] == 1
    who.update(id="pat", role="Product Owner")
    mine = (await c.get("/api/v1/notifications/mine")).json()
    items = mine["rows"]
    assert any("changed its service level" in str(n) for n in items), mine
