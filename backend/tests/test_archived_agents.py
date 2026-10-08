"""Archived agents: left out of every page and job, kept in the database, shown
by their own address and in the archived list, and brought back on request.
Runs against a throwaway DB."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Agent(id="real", org_id="org-default", slug="real", name="Real One", owner="Ops", description="x", calls=["demo2"]))
        s.add(Agent(id="demo1", org_id="org-default", slug="demo1", name="Demo One", owner="Ops", description="x", is_demo=True))
        s.add(Agent(id="demo2", org_id="org-default", slug="demo2", name="Demo Two", owner="Ops", description="x", is_demo=True))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


DEMO = {"X-Include-Demo": "1"}


async def names(c, headers=None):
    return sorted(a["name"] for a in (await c.get("/api/v1/agents/?limit=100", headers=headers or {})).json()["data"])


@pytest.mark.asyncio
async def test_an_archived_agent_is_left_out_everywhere_and_can_come_back(setup):
    c = setup
    assert (await c.post("/api/v1/agents/demo2/archive", json={"reason": "short"})).status_code == 422
    assert (await c.post("/api/v1/agents/demo2/archive", json={"reason": "Repeats Demo One in the demo set"})).status_code == 200
    assert await names(c, DEMO) == ["Demo One", "Real One"]
    assert await names(c) == ["Real One"]
    assert (await c.get("/api/v1/admin/scope", headers=DEMO)).json()["demoAgents"] == 1
    graph = (await c.get("/api/v1/graph/v2", headers=DEMO)).json()
    assert not any(n["kind"] == "external" for n in graph["nodes"])               # a call to it is not drawn as shadow AI
    assert not any(e["type"] == "CALLS" for e in graph["edges"])
    page = (await c.get("/api/v1/agents/demo2", headers=DEMO)).json()
    assert page["name"] == "Demo Two" and page["archivedAt"]                     # its own address still opens
    listed = (await c.get("/api/v1/admin/archived-agents")).json()["agents"]
    assert [(a["name"], a["reason"]) for a in listed] == [("Demo Two", "Repeats Demo One in the demo set")]

    # Jobs and scripts (outside a request) leave it out too.
    from sqlalchemy import select
    from db.base import get_db_session
    from db.models import Agent
    async with get_db_session() as s:
        assert sorted((await s.execute(select(Agent.name))).scalars()) == ["Demo One", "Real One"]

    assert (await c.post("/api/v1/agents/demo2/unarchive")).status_code == 200
    assert await names(c, DEMO) == ["Demo One", "Demo Two", "Real One"]
    trail = [r["action"] for r in (await c.get("/api/v1/audit?entity=demo2&kind=all")).json()["rows"]]
    assert trail[:2] == ["agent.unarchive", "agent.archive"]
