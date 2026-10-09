"""DEMO_AGENTS_ENABLED=false: the demo agents are left out of every page, link,
graph and job, kept in the database, and not seeded into an empty database.
Runs against a throwaway DB."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

DEMO = {"X-Include-Demo": "1"}


@pytest_asyncio.fixture
async def setup(monkeypatch):
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Agent(id="real", org_id="org-default", slug="real", name="Real One", owner="Ops", description="x", calls=["demo1"]))
        s.add(Agent(id="demo1", org_id="org-default", slug="demo1", name="Demo One", owner="Ops", description="x", is_demo=True))
    monkeypatch.setattr(get_settings(), "demo_agents_enabled", False)
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_turned_off_demo_agents_are_left_out_everywhere_but_kept(setup):
    c = setup
    listed = (await c.get("/api/v1/agents/?limit=100", headers=DEMO)).json()["data"]
    assert [a["name"] for a in listed] == ["Real One"]                          # the viewer's switch cannot bring them back
    assert (await c.get("/api/v1/agents/demo1", headers=DEMO)).status_code == 404   # not even by its own link
    assert (await c.get("/api/v1/admin/scope", headers=DEMO)).json() == {"demoAgents": 0, "includingDemo": False, "demoEnabled": False}
    graph = (await c.get("/api/v1/graph/v2", headers=DEMO)).json()
    assert not any(n["kind"] == "external" for n in graph["nodes"])            # the call to it is not drawn as shadow AI

    from sqlalchemy import func, select
    from db.base import get_db_session
    from db.models import Agent
    from db.scope import unfiltered
    async with get_db_session() as s:
        assert (await s.execute(select(func.count(Agent.id)))).scalar() == 1     # jobs leave it out
        with unfiltered():
            assert (await s.execute(select(func.count(Agent.id)))).scalar() == 2  # but it is kept


@pytest.mark.asyncio
async def test_an_empty_database_is_seeded_without_demo_agents(setup):
    from sqlalchemy import func, select
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Department, User
    from db.scope import unfiltered
    from scripts.init_db import init_db

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    async with get_db_session() as s:
        with unfiltered():
            assert (await s.execute(select(func.count(Agent.id)))).scalar() == 0
        assert (await s.execute(select(func.count(Department.id)))).scalar() > 0
        assert await s.get(User, "user-admin") is not None
    await init_db()                                                                  # a second start seeds nothing either
    async with get_db_session() as s:
        with unfiltered():
            assert (await s.execute(select(func.count(Agent.id)))).scalar() == 0
