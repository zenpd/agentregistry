"""Roles: who may change records, who decides which gate, and the guard that
keeps one active Registry Admin. Runs against a throwaway DB through the real
application."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def make_client():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, GovernanceReview, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        for uid, name, role in (("adm", "Ada Admin", "Registry Admin"), ("sec", "Sam Security", "Security Reviewer"),
                                ("arc", "Ari Architect", "Architect Steward"), ("viw", "Vic Viewer", "Executive Viewer")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Agent One", owner="Ops", description="x",
                    lifecycle_stage="Development"))
        for gate in ("arb", "security", "dp"):
            s.add(GovernanceReview(id=f"a1-{gate}", agent_id="a1", gate=gate, status="In Review"))

    from api.auth import get_current_user
    from api.main import app

    clients = []

    async def _make(user_id: str):
        roles = {"adm": "Registry Admin", "sec": "Security Reviewer", "arc": "Architect Steward", "viw": "Executive Viewer"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": roles[user_id]}
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_reviewer_decides_only_their_own_gate_and_is_recorded_by_name(make_client):
    sec = await make_client("sec")
    denied = await sec.put("/api/v1/agents/a1/governance/arb", json={"status": "Approved"})
    assert denied.status_code == 403 and "Architect Steward" in denied.json()["detail"]
    ok = await sec.put("/api/v1/agents/a1/governance/security", json={"status": "Approved", "reviewer": "Somebody Else"})
    assert ok.status_code == 200 and ok.json()["reviewer"] == "Sam Security"
    # Moving a gate back to In Review is workflow, not a decision: any editor may do it.
    assert (await sec.put("/api/v1/agents/a1/governance/arb", json={"status": "In Review"})).status_code == 200


@pytest.mark.asyncio
async def test_a_viewer_reads_but_cannot_change_anything(make_client):
    viw = await make_client("viw")
    assert (await viw.get("/api/v1/agents/a1")).status_code == 200
    r = await viw.put("/api/v1/agents/a1", json={"description": "changed"})
    assert r.status_code == 403 and r.json()["detail"] == "Your role, Executive Viewer, cannot change records."
    assert (await viw.get("/api/v1/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_me_tells_the_ui_what_this_person_can_do(make_client):
    arc = await make_client("arc")
    me = (await arc.get("/api/v1/auth/me")).json()
    assert me["name"] == "Ari Architect" and me["gates"] == ["arb"] and "admin" not in me["perms"] and me["rbac"] is True


@pytest.mark.asyncio
async def test_the_last_active_admin_cannot_be_demoted_or_deactivated(make_client):
    adm = await make_client("adm")
    demote = await adm.put("/api/v1/admin/users/adm", json={"role": "Executive Viewer"})
    assert demote.status_code == 409
    assert (await adm.put("/api/v1/admin/users/adm", json={"isActive": False})).status_code == 409
    promote = await adm.put("/api/v1/admin/users/sec", json={"role": "Registry Admin"})
    assert promote.status_code == 200 and promote.json()["user"]["role"] == "Registry Admin"
    assert (await adm.put("/api/v1/admin/users/adm", json={"role": "Product Owner"})).status_code == 200
    assert (await adm.put("/api/v1/admin/users/viw", json={"role": "Wizard"})).status_code == 422
    assert (await adm.post("/api/v1/admin/users/viw/password", json={"password": "short"})).status_code == 422
    assert (await adm.post("/api/v1/admin/users/viw/password", json={"password": "a-long-password"})).status_code == 200


@pytest.mark.asyncio
async def test_the_plain_edit_call_cannot_change_stage_or_risk_level(make_client):
    adm = await make_client("adm")
    assert (await adm.put("/api/v1/agents/a1", json={"lifecycle_stage": "Production"})).status_code == 422
    assert (await adm.put("/api/v1/agents/a1", json={"risk_level": "LOW"})).status_code == 200  # unchanged value
    assert (await adm.put("/api/v1/agents/a1", json={"risk_level": "HIGH"})).status_code == 422


@pytest.mark.asyncio
async def test_registering_at_a_later_stage_needs_a_reason_and_is_recorded(make_client):
    adm = await make_client("adm")
    body = {"name": "Live Already", "stage": "Production", "description": "Routes refunds"}
    assert (await adm.post("/api/v1/agents/", json=body)).status_code == 422
    created = await adm.post("/api/v1/agents/", json={**body, "stage_reason": "Live since 2025, registered now"})
    assert created.status_code == 200
    gov = (await adm.get(f"/api/v1/agents/{created.json()['id']}/governance")).json()
    assert [h["action"] for h in gov["history"]][-1] == "stage_change"


@pytest.mark.asyncio
async def test_rule_proposal_saves_nothing_until_accepted_with_a_reason(make_client):
    adm = await make_client("adm")
    proposal = (await adm.post("/api/v1/agents/a1/governance/rule-proposal")).json()
    assert proposal["saved"] is False and len(proposal["gates"]) == 3
    gov = (await adm.get("/api/v1/agents/a1/governance")).json()
    assert {g["status"] for g in gov["gates"]} == {"In Review"}
    assert (await adm.post("/api/v1/agents/a1/governance/rule-proposal/apply", json={"reason": "too short"})).status_code == 422
    applied = await adm.post("/api/v1/agents/a1/governance/rule-proposal/apply",
                             json={"reason": "Low-risk internal pilot, rules are enough for now"})
    assert applied.status_code == 200
    gates = (await adm.get("/api/v1/agents/a1/governance")).json()["gates"]
    assert all(g["reviewer"] == "Ada Admin" for g in gates)
    assert all("Rule-check proposal accepted by Ada Admin" in (g["notes"] or "") for g in gates)


def test_a_weak_signing_key_stops_the_app_outside_development(monkeypatch):
    import api.auth as auth
    from shared.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setenv("AIREGISTRY_SECRET_KEY", "change-me-please")
    with pytest.raises(RuntimeError):
        auth.check_signing_key()
    monkeypatch.setenv("AIREGISTRY_SECRET_KEY", "k" * 40)
    auth.check_signing_key()
