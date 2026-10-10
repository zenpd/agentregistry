"""Demo agents are left out of every portfolio answer unless the viewer
switches them on, and a demo agent's own page still opens. Runs against a
throwaway DB through the real application, so a new endpoint that forgets the
rule shows up here."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

ADMIN = {"user_id": "u1", "role": "admin"}
DEMO_NAME = "Zebra Demo Agent"
NOW = datetime.now(timezone.utc)

PORTFOLIO = [
    "/api/v1/agents/?limit=100",
    "/api/v1/value/economics",
    "/api/v1/governance/risks/summary",
    "/api/v1/governance/",
    "/api/v1/approvals",
    "/api/v1/graph/v2",
    "/api/v1/graph/concentration-risk",
]


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import (Agent, AgentAccessRequest, AgentRisk, AgentTokenUsage, GovernanceReview,
                           Organization)
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        for aid, name, demo, value in (("real", "Real Agent", False, 1000), ("demo", DEMO_NAME, True, 5000)):
            s.add(Agent(id=aid, org_id="org-default", slug=aid, name=name, owner="Ops", description="x",
                        lifecycle_stage="Production", value_amount=value, is_demo=demo,
                        enterprise_systems=["SAP", "Shared CRM"], consumers=[f"{name} team"]))
            for gate in ("arb", "security", "dp"):
                s.add(GovernanceReview(id=f"{aid}-{gate}", agent_id=aid, gate=gate,
                                       status="Approved" if aid == "real" else "In Review"))
            s.add(AgentRisk(id=f"{aid}-r", agent_id=aid, category="OPERATIONAL", severity="HIGH",
                            title=f"{name} risk", status="open"))
            s.add(AgentAccessRequest(id=f"{aid}-q", agent_id=aid, requester_id="u2", team=f"{name} team",
                                     purpose="use it", status="pending"))
            s.add(AgentTokenUsage(agent_id=aid, bucket=NOW - timedelta(days=1), model_name="gpt-4.1-mini",
                                  invocation_count=10, input_tokens=1000, output_tokens=100, source="phoenix"))
        # A third agent shares systems so concentration risk has something to say.
        s.add(Agent(id="real2", org_id="org-default", slug="real2", name="Second Real", owner="Ops",
                    description="x", lifecycle_stage="Testing", enterprise_systems=["SAP", "Shared CRM"]))

    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _get(client, path, include):
    r = await client.get(path, headers={"X-Include-Demo": "1"} if include else {})
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PORTFOLIO)
async def test_portfolio_answers_leave_demo_agents_out_unless_asked(client, path):
    hidden = json.dumps(await _get(client, path, include=False))
    shown = json.dumps(await _get(client, path, include=True))
    assert DEMO_NAME not in hidden and '"demo"' not in hidden, path
    assert hidden != shown, f"{path} does not change when demo agents are switched on"


@pytest.mark.asyncio
async def test_counts_agree_across_pages(client):
    agents = await _get(client, "/api/v1/agents/?limit=100", include=False)
    assert agents["pagination"]["total"] == 2
    assert {a["id"] for a in agents["data"]} == {"real", "real2"}
    assert all(a["isDemo"] is False for a in agents["data"])
    overview = await _get(client, "/api/v1/governance/", include=False)
    assert sum(overview["arb"].values()) == 0 or overview["arb"].get("In Review", 0) == 0


@pytest.mark.asyncio
async def test_a_demo_agents_own_page_still_opens_and_says_it_is_demo(client):
    agent = await _get(client, "/api/v1/agents/demo", include=False)
    assert agent["isDemo"] is True and agent["name"] == DEMO_NAME
    overview = await client.get("/api/v1/agents/demo/overview")
    assert overview.status_code == 200


@pytest.mark.asyncio
async def test_scope_summary_tells_the_shell_how_many_are_hidden(client):
    hidden = await _get(client, "/api/v1/admin/scope", include=False)
    assert hidden == {"demoAgents": 1, "includingDemo": False, "demoEnabled": True}
    shown = await _get(client, "/api/v1/admin/scope", include=True)
    assert shown == {"demoAgents": 1, "includingDemo": True, "demoEnabled": True}


@pytest.mark.asyncio
async def test_a_showcase_agent_is_shown_while_the_other_demo_agents_are_hidden(monkeypatch):
    """The complete example agent stays visible by default. Turning demo agents off for the installation hides it too."""
    import httpx
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Agent(id="real", org_id="org-default", slug="real", name="Real One", owner="Ops", description="x"))
        s.add(Agent(id="demo", org_id="org-default", slug="demo", name="Demo One", owner="Ops", description="x", is_demo=True))
        s.add(Agent(id="show", org_id="org-default", slug="show", name="Showcase", owner="Ops", description="x", is_demo=True, source="showcase"))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            names = lambda r: sorted(a["name"] for a in r.json()["data"])  # noqa: E731
            assert names(await c.get("/api/v1/agents/?limit=100")) == ["Real One", "Showcase"]
            assert names(await c.get("/api/v1/agents/?limit=100", headers={"X-Include-Demo": "1"})) == ["Demo One", "Real One", "Showcase"]
            assert (await c.get("/api/v1/governance/summary")).json()["agents"] == 2
            monkeypatch.setattr(get_settings(), "demo_agents_enabled", False)
            assert names(await c.get("/api/v1/agents/?limit=100")) == ["Real One"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
