"""Classification rules and records, and the risk class from approved tools.
Runs against a throwaway DB."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from governance import classification as cls
from governance import tool_risk

BASE = {"area": "none", "interacts": False, "audience": "staff", "data": "none", "decisions": "suggests"}


def test_suggestion_follows_the_rules_and_gives_reasons():
    assert cls.suggest(BASE) == {"category": "Minimal Risk", "riskLevel": "LOW", "reasons": [
        "Minimal Risk: no banned practice, no Annex III area and no direct contact with people.",
        "Risk level from the answers: LOW, because only staff are affected, no personal data is used and a person makes every decision."]}
    s = cls.suggest({**BASE, "interacts": True, "audience": "public", "data": "personal"})
    assert (s["category"], s["riskLevel"]) == ("Limited Risk", "MEDIUM")
    assert s["reasons"][-1] == "Risk level from the answers: MEDIUM, because it uses personal data, and it affects customers or the public."
    s = cls.suggest({**BASE, "area": "employment", "narrow_task": False})
    assert (s["category"], s["riskLevel"]) == ("High Risk", "HIGH")
    s = cls.suggest({**BASE, "area": "employment", "narrow_task": True})
    assert s["category"] == "Minimal Risk" and any("Article 6(3)" in r for r in s["reasons"])
    s = cls.suggest({**BASE, "prohibited": ["social_scoring"]})
    assert s["category"] == "Unacceptable Risk" and "must not be used" in s["reasons"][0]
    s = cls.suggest({**BASE, "decisions": "decides_alone", "audience": "both"})
    assert s["riskLevel"] == "HIGH"
    s = cls.suggest(BASE, tool_class="HIGH", tool_source="payments-mcp")
    assert s["riskLevel"] == "HIGH" and s["reasons"][-1] == "Raised to HIGH: it uses a tool approved as HIGH (payments-mcp)."
    assert cls.missing_answers({"area": "education"}) == ["interacts", "audience", "data", "decisions", "narrow_task"]
    assert cls.is_lower("Minimal Risk", "LOW", "High Risk", "HIGH") and not cls.is_lower("High Risk", "HIGH", "High Risk", "MEDIUM")


def test_tool_class_is_the_highest_listed_and_unlisted_tools_are_named():
    agent = {"mcp_servers": ["CRM ", "payments"], "databases": ["crm", "ledger"], "knowledge_bases": []}
    approved = [{"name": "crm", "risk_class": "LOW"}, {"name": "Payments", "risk_class": "HIGH"}]
    r = tool_risk.tool_class(agent, approved)
    assert r["class"] == "HIGH" and r["source"] == "payments" and r["unlisted"] == ["ledger"]
    assert [t["name"] for t in r["tools"]] == ["CRM", "payments", "ledger"]       # crm declared twice counts once
    assert tool_risk.tool_class({"mcp_servers": ["x"]}, [])["listEmpty"] is True
    c = tool_risk.candidates([{"name": "A", "mcp_servers": ["x", "crm"]}, {"name": "B", "databases": ["x"]}], approved)
    assert c == [{"name": "x", "kind": "mcp", "agents": ["A", "B"]}]


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, GovernanceReview, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("po", "Pat", "Product Owner"), ("arch", "Ari", "Architect Steward")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Claims Bot", owner="Ops", description="x" * 30,
                    lifecycle_stage="Development", mcp_servers=["payments"], risk_level="LOW"))
        s.add(GovernanceReview(id="a1-arb", agent_id="a1", gate="arb", status="In Review"))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_proposes_steward_confirms_and_the_agent_changes(setup):
    c, who = setup
    who.update(id="po", role="Product Owner")
    answers = {**BASE, "interacts": True, "audience": "public", "data": "personal", "retention": "1_year"}
    denied = await c.post("/api/v1/agents/a1/classification", json={"answers": answers, "confirm": True})
    assert denied.status_code == 403 and "proposal" in denied.json()["detail"]
    assert (await c.post("/api/v1/agents/a1/classification", json={"answers": {"area": "none"}})).status_code == 422
    p = (await c.post("/api/v1/agents/a1/classification", json={"answers": answers})).json()
    assert p["status"] == "proposed" and (p["category"], p["riskLevel"]) == ("Limited Risk", "MEDIUM") and p["proposedBy"] == "Pat"
    assert (await c.get("/api/v1/agents/a1")).json()["riskLevel"] == "LOW"        # nothing changes until confirmed
    who.update(id="arch", role="Architect Steward")
    low = await c.post(f"/api/v1/agents/a1/classification/{p['id']}/confirm", json={"riskLevel": "LOW"})
    assert low.status_code == 422 and "below the suggestion" in low.json()["detail"]
    ok = (await c.post(f"/api/v1/agents/a1/classification/{p['id']}/confirm", json={})).json()
    assert ok["status"] == "confirmed" and ok["confirmedBy"] == "Ari"
    agent = (await c.get("/api/v1/agents/a1")).json()
    assert agent["riskLevel"] == "MEDIUM"
    gov = (await c.get("/api/v1/agents/a1/governance")).json()
    arb = next(g for g in gov["gates"] if g["gate"] == "arb")
    item = next(i for i in arb["checklist"] if i["id"] == "arb.eu_tier")
    assert item["result"] == "pass" and item["detail"].startswith("Confirmed as Limited Risk, risk level MEDIUM, by Ari on ")
    data = (await c.get("/api/v1/agents/a1/classification")).json()
    assert data["current"]["id"] == p["id"] and data["pending"] is None and data["canConfirm"] is True
    who.update(id="adm", role="Registry Admin")
    trail = (await c.get("/api/v1/audit?entity=a1&kind=all")).json()["rows"]
    assert [r["action"] for r in trail][:2] == ["classification.confirm", "classification.propose"]
    assert "Minimal Risk, LOW → Limited Risk, MEDIUM" in trail[0]["summary"]


@pytest.mark.asyncio
async def test_approved_tools_raise_the_suggested_level(setup):
    c, who = setup
    listing = (await c.get("/api/v1/tools/approved")).json()
    assert listing["candidates"] == [{"name": "payments", "kind": "mcp", "agents": ["Claims Bot"]}]
    t = (await c.post("/api/v1/tools/approved", json={"name": "Payments", "kind": "mcp", "riskClass": "HIGH"})).json()
    assert (await c.post("/api/v1/tools/approved", json={"name": "payments"})).status_code == 409
    tools = (await c.get("/api/v1/agents/a1/tools")).json()
    assert tools["class"] == "HIGH" and tools["unlisted"] == []
    s = (await c.post("/api/v1/agents/a1/classification/suggest", json={"answers": BASE})).json()
    assert s["riskLevel"] == "HIGH" and s["missing"] == []
    r = await c.put(f"/api/v1/tools/approved/{t['id']}", json={"riskClass": "LOW"})
    assert r.status_code == 200 and r.json()["riskClass"] == "LOW", r.text
    who.update(id="po", role="Product Owner")
    assert (await c.post("/api/v1/tools/approved", json={"name": "crm"})).status_code == 403
