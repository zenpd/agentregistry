"""Compliance and audit: packs and coverage, the hash-chained decision log, the
auditor end date and access log, incidents and stop requests, evidence packs with a
recorded hash, the data and retention report and the GRC export. Throwaway DB."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from governance import compliance as cp


def test_packs_hold_the_published_control_lists():
    assert {k: len(p["controls"]) for k, p in cp.PACKS.items()} == {"eu_ai_act": 17, "iso_42001": 38, "nist_ai_rmf": 19, "india_dpdp": 10}
    iso = [c for c in cp.PACKS["iso_42001"]["controls"]]
    assert sum(1 for c in iso if c["outside"]) == 13 and iso[0]["id"] == "A.2.2" and iso[-1]["id"] == "A.10.4"
    for p in cp.PACKS.values():
        for c in p["controls"]:
            assert all(k in cp.AGENT_EVIDENCE for k in c["agent"]) and all(k in cp.REGISTRY_EVIDENCE for k in c["registry"])
            assert c["outside"] or c["agent"] or c["registry"], c["id"]
    unclassified = {"stage": "Testing", "classified": False}
    assert cp.applies("high_risk", unclassified) and not cp.applies("production", unclassified)
    assert not cp.applies("personal_data", {"classified": True, "answers": {"data": "none"}})


def test_coverage_names_the_agents_missing_evidence():
    ev_all = {k: True for k in cp.AGENT_EVIDENCE}
    agents = [{"id": "a", "name": "A", "stage": "Production", "classified": True, "category": "Minimal Risk", "answers": {"data": "none"}, "evidence": ev_all},
              {"id": "b", "name": "B", "stage": "Testing", "classified": True, "category": "Minimal Risk", "answers": {"data": "none"},
               "evidence": {**ev_all, "tracing": False}}]
    reg = {k: True for k in cp.REGISTRY_EVIDENCE}
    cov = cp.coverage("iso_42001", agents, reg)
    logs = next(c for c in cov["controls"] if c["id"] == "A.6.2.8")
    assert logs["status"] == "missing" and logs["agentsMissing"] == 1 and logs["agents"][1]["missing"] == ["Runtime tracing is linked"]
    deploy = next(c for c in cov["controls"] if c["id"] == "A.6.2.5")
    assert deploy["agentsInScope"] == 1 and deploy["status"] == "evidenced"            # Production agents only
    assert (cov["total"], cov["outside"]) == (38, 13) and cov["evidenced"] + cov["missing"] + cov["notApplicable"] == 25
    eu = cp.coverage("eu_ai_act", agents, reg)
    assert next(c for c in eu["controls"] if c["id"] == "Art. 9")["status"] == "not_applicable"   # neither agent is High Risk


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
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("own", "Olu", "Product Owner"), ("po", "Pat", "Product Owner")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Claims Bot", owner="Olu", owner_user_id="own",
                    description="Triages insurance claims for the claims team", lifecycle_stage="Testing"))
        for gate in ("arb", "security", "dp"):
            s.add(GovernanceReview(id=f"a1-{gate}", agent_id="a1", gate=gate, status="In Review"))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_decisions_are_sealed_and_a_change_is_found(setup):
    c, _ = setup
    assert (await c.put("/api/v1/agents/a1/governance/arb", json={"status": "Approved"})).status_code == 200
    assert (await c.put("/api/v1/agents/a1/governance/dp", json={"status": "Changes Requested", "notes": "DPIA missing"})).status_code == 200
    v = (await c.get("/api/v1/compliance/decision-log/verify")).json()
    assert v["ok"] is True and v["entries"] == 2 and v["unsealed"] == 0
    from sqlalchemy import text
    from db.base import engine
    async with engine.begin() as conn:     # tampering straight in the database (the test DB has no append-only trigger)
        await conn.execute(text("UPDATE audit_log SET actor = 'someone-else' WHERE action = 'gate_update' AND id = (SELECT min(id) FROM audit_log WHERE action = 'gate_update')"))
    v = (await c.get("/api/v1/compliance/decision-log/verify")).json()
    assert v["ok"] is False and v["firstBroken"]["seq"] == 1 and "changed after it was sealed" in v["firstBroken"]["problem"]


@pytest.mark.asyncio
async def test_auditors_need_an_end_date_and_every_request_is_logged(setup):
    c, _ = setup
    body = {"email": "aud@x.io", "name": "Audrey", "role": "Auditor", "password": "auditor-pass-1"}
    assert (await c.post("/api/v1/admin/users", json=body)).status_code == 422
    until = (date.today() + timedelta(days=14)).isoformat()
    created = (await c.post("/api/v1/admin/users", json={**body, "accessUntil": until})).json()
    assert created["user"]["accessUntil"] == until
    from api.auth import create_access_token
    from api.main import app
    app.dependency_overrides.clear()                        # the real sign-in path, with a token
    token = create_access_token(created["id"], "Auditor")
    r = await c.get("/api/v1/agents/a1", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert (await c.put("/api/v1/agents/a1", json={"sla": "x"}, headers={"Authorization": f"Bearer {token}"})).status_code == 403
    from db.base import get_db_session
    from db.models import AuditLog, User
    from sqlalchemy import select
    async with get_db_session() as s:
        logged = (await s.execute(select(AuditLog).where(AuditLog.action == "auditor.access"))).scalars().all()
        assert [x.changes["path"] for x in logged][:1] == ["/api/v1/agents/a1"]
        (await s.get(User, created["id"])).access_until = date.today() - timedelta(days=1)
    r = await c.get("/api/v1/agents/a1", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and "ended on" in r.json()["detail"]


@pytest.mark.asyncio
async def test_incidents_link_ask_the_owner_to_stop_and_record_the_answer(setup):
    c, who = setup
    i = (await c.post("/api/v1/agents/a1/incidents", json={"title": "Wrong claim decisions", "severity": "high",
                                                          "url": "https://acme.pagerduty.com/incidents/Q1W2E3"})).json()
    assert (i["source"], i["externalId"]) == ("pagerduty", "Q1W2E3")
    assert (await c.post(f"/api/v1/agents/a1/incidents/{i['id']}/stop-request", json={"note": "short"})).status_code == 422
    r = (await c.post(f"/api/v1/agents/a1/incidents/{i['id']}/stop-request", json={"note": "It approves claims it should send to a person"})).json()
    assert r["told"] == 1 and r["toldOwners"] is True
    att = (await c.get("/api/v1/portfolio/attention")).json()
    assert att["stopWaiting"][0]["name"] == "Claims Bot"
    who.update(id="po", role="Product Owner")
    assert (await c.post(f"/api/v1/agents/a1/incidents/{i['id']}/stop-ack", json={"note": "x" * 25})).status_code == 403
    who.update(id="own", role="Product Owner")
    mine = (await c.get("/api/v1/notifications/mine")).json()["rows"]
    assert any("stop Claims Bot now" in n["subject"] for n in mine)
    ack = (await c.post(f"/api/v1/agents/a1/incidents/{i['id']}/stop-ack", json={"note": "Switched off the claims queue at 10:40"})).json()
    assert ack["stop"]["acknowledgedBy"] == "Olu"
    who.update(id="adm", role="Registry Admin")
    inbound = {"agent": "Claims Bot", "title": "Latency", "source": "servicenow", "externalId": "INC0012345", "severity": "low"}
    assert (await c.post("/api/v1/incidents/inbound", json=inbound)).json()["created"] is True
    done = (await c.post("/api/v1/incidents/inbound", json={**inbound, "status": "resolved"})).json()
    assert done == {"id": done["id"], "agentId": "a1", "created": False, "status": "resolved"}
    hist = (await c.get("/api/v1/agents/a1/incidents")).json()
    assert hist["open"] == 1 and any(h["kind"] == "stop" for h in hist["history"])


@pytest.mark.asyncio
async def test_evidence_packs_record_their_hash_and_reports_export(setup):
    c, _ = setup
    pdf = await c.get("/api/v1/agents/a1/evidence-pack?format=pdf")
    assert pdf.content.startswith(b"%PDF-1.4") and pdf.headers["x-evidence-sha256"] == hashlib.sha256(pdf.content).hexdigest()
    found = (await c.get(f"/api/v1/compliance/exports/check?sha256={pdf.headers['x-evidence-sha256']}")).json()
    assert found["found"] is True and found["what"] == "Evidence pack of Claims Bot"
    assert (await c.get(f"/api/v1/compliance/exports/check?sha256={'0' * 64}")).json() == {"found": False}
    csv_ctl = await c.get("/api/v1/compliance/packs/iso_42001/controls/A.6.2.8/evidence?format=csv")
    assert csv_ctl.text.startswith("pack,control,title") and "Claims Bot" in csv_ctl.text
    packs = (await c.get("/api/v1/compliance/packs")).json()
    assert [(p["key"], p["total"]) for p in packs["packs"]] == [("eu_ai_act", 17), ("iso_42001", 38), ("nist_ai_rmf", 19), ("india_dpdp", 10)]
    rep = (await c.get("/api/v1/compliance/data-report")).json()
    assert rep["summary"]["unknown"] == 1 and rep["rows"][0]["data"].startswith("Not recorded")
    grc = await c.get("/api/v1/compliance/grc-export?tool=onetrust&kind=controls")
    assert grc.text.startswith("framework,control_id,control_title,status")
    dates = (await c.put("/api/v1/compliance/dates", json={"dates": {"eu_ai_act": {"high_risk": "2027-12-02"}}})).json()
    assert next(d for d in dates["eu_ai_act"] if d["key"] == "high_risk")["date"] == "2027-12-02"
