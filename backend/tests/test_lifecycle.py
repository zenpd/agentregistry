"""Lifecycle rules: approval snapshots and what changed since, reopening the
gates a change touches, required fields, completeness, templates, stalls, waivers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from governance import gate_policy as gp
from governance import lifecycle as lc

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def test_snapshot_diff_names_what_changed_and_which_gates_it_touches():
    snap = lc.snapshot({"model_name": "gpt-4o", "mcp_servers": ["crm", "kyc"], "api_endpoint": "https://a/x"})
    same = lc.changed_since(snap, {"model_name": "gpt-4o", "mcp_servers": ["kyc", "crm", " "], "api_endpoint": "https://a/x"})
    assert same == []
    diff = lc.changed_since(snap, {"model_name": "gpt-4.1-mini", "mcp_servers": ["crm", "kyc", "payments"], "api_endpoint": "https://a/x"})
    assert {c["field"] for c in diff} == {"model_name", "mcp_servers"}
    assert lc.affected_gates(diff) == {"arb", "security", "dp"}
    assert lc.describe(diff) == "Model (gpt-4o → gpt-4.1-mini), Tools and MCP servers (+payments)"


def test_required_fields_are_cumulative_and_completeness_counts_fifteen_fields():
    facts = {"owner": "Ops", "dept": "dept-fin", "description": "too short"}
    assert lc.missing_required("Development", facts) == []
    assert lc.missing_required("Testing", facts) == ["description", "business_outcome"]
    assert lc.missing_required("Production", {**facts, "trace_connector_id": "lf1"}) == ["description", "business_outcome"]
    c = lc.completeness({"owner": "Ops", "dept": "x", "budget": True})
    assert c["total"] == 15 and c["filled"] == 3 and c["score"] == 20 and "a confirmed classification" in c["missing"]


def test_templates_drive_readiness_gates_and_mode():
    assert lc.check_templates(lc.default_templates(365, 180, "warn")) is None
    bad = lc.default_templates(365, 180, "warn")
    bad["LOW"]["gates"] = ["security"]
    assert "Architecture Review Board is always required" in lc.check_templates(bad)
    reviews = {"arb": {"status": "Approved", "expires_at": NOW + timedelta(days=100)}}
    r = gp.stage_readiness({}, reviews, "Production", [], True, NOW, "block", gates=["arb"], missing=[])
    assert r["ready"] and not r["blocked"]
    r = gp.stage_readiness({}, reviews, "Production", [], True, NOW, "block", gates=["arb", "dp"], missing=["owner"])
    assert r["blocked"] and {w["code"] for w in r["warnings"]} == {"owner_missing", "gate_not_approved"}


def test_stalls_and_waiver_rules():
    assert lc.weeks_in_stage(NOW - timedelta(days=70), NOW) == 10
    assert lc.stalled("Testing", 9) and not lc.stalled("Production", 99) and not lc.stalled("Testing", 7)
    assert "cannot be waived" in lc.waiver_refusal("security", "x" * 30)
    assert lc.waiver_refusal("dp", "short") and lc.waiver_refusal("dp", "x" * 25) is None
    counts = lc.waiver_counts([{"status": "active", "first_signer": "a", "second_signer": "b", "reason": "x" * 25},
                               {"status": None, "first_signer": "a", "second_signer": None, "reason": "older one, one signer"},
                               {"status": "pending", "first_signer": "a"}])
    assert counts == {"active": 2, "complete": 1, "share": 50, "pending": 1}


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
        for uid, role in (("adm", "Registry Admin"), ("dpo", "Data Protection Officer"), ("dpo2", "Data Protection Officer")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=uid.upper(), role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Agent One", owner="Ops", description="x" * 30,
                    lifecycle_stage="Testing", model_name="gpt-4o", mcp_servers=["crm"]))
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
async def test_a_change_after_approval_is_shown_and_reopens_the_gates_it_touches(setup):
    c, _ = setup
    for gate in ("arb", "security", "dp"):
        assert (await c.put(f"/api/v1/agents/a1/governance/{gate}", json={"status": "Approved"})).status_code == 200
    from db.base import get_db_session
    from db.models import Agent
    async with get_db_session() as s:
        (await s.get(Agent, "a1")).mcp_servers = ["crm", "payments"]          # a tool appears after approval
    gov = (await c.get("/api/v1/agents/a1/governance")).json()
    sec = next(g for g in gov["gates"] if g["gate"] == "security")
    assert sec["changedSinceApproval"][0]["added"] == ["payments"]
    from orchestrations.governance_checks import run_governance_checks
    result = await run_governance_checks(agent_id="a1")
    assert {r["gate"] for r in result["reopened"]} == {"security", "dp"}
    gates = {g["gate"]: g for g in (await c.get("/api/v1/agents/a1/governance")).json()["gates"]}
    assert gates["arb"]["status"] == "Approved" and gates["security"]["status"] == "In Review"
    assert gates["dp"]["notes"].startswith("Reopened by the registry")


@pytest.mark.asyncio
async def test_two_different_dpos_sign_a_waiver_before_it_covers_the_gate(setup):
    c, who = setup
    who.update(id="dpo", role="Data Protection Officer")
    until = (datetime.now(timezone.utc).date() + timedelta(days=20)).isoformat()
    w = (await c.post("/api/v1/agents/a1/governance/exceptions", json={"gate": "dp", "reason": "DPIA booked for next week with legal", "expiresAt": until})).json()
    assert w["status"] == "pending"
    denied = await c.post("/api/v1/agents/a1/governance/exceptions", json={"gate": "arb", "reason": "x" * 30, "expiresAt": until})
    assert denied.status_code == 403
    assert (await c.post(f"/api/v1/agents/a1/governance/exceptions/{w['id']}/sign")).status_code == 409
    who.update(id="dpo2", role="Data Protection Officer")
    signed = (await c.post(f"/api/v1/agents/a1/governance/exceptions/{w['id']}/sign")).json()
    assert signed["status"] == "active" and signed["twoSigners"] is True
    gov = (await c.get("/api/v1/agents/a1/governance")).json()
    assert gov["exceptions"][0]["secondSignerName"] == "DPO2"
    report = (await c.get("/api/v1/governance/waivers")).json()
    assert report["counts"]["complete"] == 1


@pytest.mark.asyncio
async def test_rules_are_set_by_an_admin_and_apply_to_readiness(setup):
    c, who = setup
    rules = (await c.get("/api/v1/governance/settings")).json()
    rules["templates"]["LOW"]["gates"] = ["arb", "security"]
    rules["templates"]["LOW"]["mode"] = "block"
    assert (await c.put("/api/v1/governance/settings", json={"templates": rules["templates"]})).status_code == 200
    gov = (await c.get("/api/v1/agents/a1/governance")).json()
    assert gov["template"]["gates"] == ["arb", "security"] and gov["enforcement"] == "block"
    assert all(w["gate"] != "dp" for w in gov["readiness"]["production"]["warnings"])
    bad = {**rules["templates"], "HIGH": {**rules["templates"]["HIGH"], "validityDays": 5}}
    assert (await c.put("/api/v1/governance/settings", json={"templates": bad})).status_code == 422
    who.update(id="dpo", role="Data Protection Officer")
    assert (await c.put("/api/v1/governance/settings", json={"templates": rules["templates"]})).status_code == 403
