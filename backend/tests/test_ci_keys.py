"""API keys and the CI calls, through the real application and real key sign-in."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


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
        s.add(User(id="adm", org_id="org-default", email="a@x.io", name="Ada", role="Registry Admin", password_hash="x"))
        s.add(Agent(id="inv", org_id="org-default", slug="inv", name="Invoice Agent", owner="Finance", description="Matches invoices",
                    lifecycle_stage="Testing"))
        for gate in ("arb", "security", "dp"):
            s.add(GovernanceReview(id=f"inv-{gate}", agent_id="inv", gate=gate, status="In Review"))
    from api.auth import create_access_token
    from api.main import app

    admin = {"Authorization": f"Bearer {create_access_token('adm', 'Registry Admin')}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, admin
    await engine.dispose()


async def _issue(c, admin, scopes):
    r = await c.post("/api/v1/admin/api-keys", headers=admin, json={"label": f"ci {scopes}", "scopes": scopes})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_a_key_is_shown_once_stored_as_hash_and_listed_without_it(setup):
    c, admin = setup
    issued = await _issue(c, admin, ["certify_check"])
    assert issued["key"].startswith("ark_") and issued["prefix"] == issued["key"][:12]
    listed = (await c.get("/api/v1/admin/api-keys", headers=admin)).json()
    assert listed[0]["id"] == issued["id"] and "key" not in listed[0]
    assert (await c.post("/api/v1/admin/api-keys", headers=admin, json={"label": "bad one", "scopes": ["root"]})).status_code == 422


@pytest.mark.asyncio
async def test_check_blocks_with_reasons_and_scopes_are_enforced(setup):
    c, admin = setup
    key = (await _issue(c, admin, ["certify_check"]))["key"]
    h = {"Authorization": f"Bearer {key}"}
    chk = (await c.get("/api/v1/ci/check", params={"agent": "Invoice Agent", "stage": "Production"}, headers=h)).json()
    assert chk["allowed"] is False and chk["reasons"] and chk["currentStage"] == "Testing"
    denied = await c.post("/api/v1/ci/register", headers=h, json={"name": "Nope"})
    assert denied.status_code == 403 and "cannot register agents" in denied.json()["detail"]
    gate = await c.put("/api/v1/agents/inv/governance/arb", headers=h, json={"status": "Approved"})
    assert gate.status_code == 403                       # a key never decides a review


@pytest.mark.asyncio
async def test_register_creates_then_updates_declared_fields_never_the_stage(setup):
    c, admin = setup
    key = (await _issue(c, admin, ["register"]))["key"]
    h = {"Authorization": f"Bearer {key}"}
    created = (await c.post("/api/v1/ci/register", headers=h, json={"name": "Payout Router", "description": "Routes payouts"})).json()
    assert created["status"] == "created"
    again = (await c.post("/api/v1/ci/register", headers=h, json={"name": "Payout Router", "version": "1.2.0", "description": "Routes payouts"})).json()
    assert again == {"id": created["id"], "status": "updated", "changed": ["version"]}
    agent = (await c.get(f"/api/v1/agents/{created['id']}", headers=h)).json()
    assert agent["stage"] == "Ideation" and agent["version"] == "1.2.0"


@pytest.mark.asyncio
async def test_a_revoked_key_stops_at_once(setup):
    c, admin = setup
    issued = await _issue(c, admin, ["read"])
    h = {"Authorization": f"Bearer {issued['key']}"}
    assert (await c.get("/api/v1/agents/inv", headers=h)).status_code == 200
    assert (await c.delete(f"/api/v1/admin/api-keys/{issued['id']}", headers=admin)).json()["active"] is False
    assert (await c.get("/api/v1/agents/inv", headers=h)).status_code == 401
