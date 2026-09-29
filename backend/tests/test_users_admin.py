"""Settings → Users: adding the people who can sign in. Runs against a
throwaway DB."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

actor = {"user_id": "u-admin", "role": "admin"}


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import Organization, User
    from api.auth import hash_password, require_admin, require_read
    from api.routers.registry import admin_router, auth_router
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(User(id="u-admin", org_id="org-default", email="admin@example.com", name="Admin",
                   role="Registry Admin", password_hash=hash_password("admin12345")))
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(auth_router)
    app.dependency_overrides[require_admin] = lambda: dict(actor)
    app.dependency_overrides[require_read] = lambda: dict(actor)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await engine.dispose()


NEW = {"email": "  Bob.Approver@Example.com ", "name": "  Bob   Approver ", "role": "Security Reviewer",
       "password": "s3cret-pass"}


@pytest.mark.asyncio
async def test_a_new_user_is_cleaned_listed_audited_and_can_sign_in(client):
    from db.base import get_db_session
    from db.models import AuditLog
    from sqlalchemy import select

    created = await client.post("/api/v1/admin/users", json=NEW)
    assert created.status_code == 200
    assert created.json()["user"] == {"id": created.json()["id"], "email": "bob.approver@example.com",
                                      "name": "Bob Approver", "role": "Security Reviewer", "isActive": True}
    names = [u["name"] for u in (await client.get("/api/v1/admin/users")).json()]
    assert names == ["Admin", "Bob Approver"]
    async with get_db_session() as s:
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "user_create"))).scalar_one()
    assert audit.actor == "u-admin" and "s3cret" not in str(audit.changes)
    # Sign-in ignores the case of the email.
    login = await client.post("/api/v1/auth/login", json={"email": "BOB.approver@example.com", "password": "s3cret-pass"})
    assert login.status_code == 200 and login.json()["user"]["name"] == "Bob Approver"


@pytest.mark.asyncio
async def test_duplicate_email_is_refused_clearly_not_a_crash(client):
    assert (await client.post("/api/v1/admin/users", json=NEW)).status_code == 200
    again = await client.post("/api/v1/admin/users", json={**NEW, "email": "BOB.APPROVER@example.com"})
    assert again.status_code == 409 and "already exists" in again.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change,message", [
    ({"email": "not-an-email"}, "valid email"),
    ({"name": "   "}, "name"),
    ({"role": "Superuser"}, "Role must be one of"),
])
async def test_bad_input_is_explained(client, change, message):
    res = await client.post("/api/v1/admin/users", json={**NEW, **change})
    assert res.status_code == 422 and message in res.json()["detail"]


@pytest.mark.asyncio
async def test_short_password_is_refused(client):
    assert (await client.post("/api/v1/admin/users", json={**NEW, "password": "short"})).status_code == 422


@pytest.mark.asyncio
async def test_settings_report_whether_testing_self_approval_is_on(client, monkeypatch):
    from shared.config import get_settings

    for value in (True, False):
        monkeypatch.setattr(get_settings(), "allow_self_approval", value)
        assert (await client.get("/api/v1/admin/settings")).json() == {"selfApprovalAllowed": value}
