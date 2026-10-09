"""CSV import: a preview row by row, then a commit that creates only the rows marked create."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

HEADER = "name,description,department,stage,stage_reason,ai_type,phoenix_project,capabilities,value_amount\n"


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Department, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Department(id="dept-fin", org_id="org-default", name="Finance"))
        s.add(Agent(id="old", org_id="org-default", slug="old", name="Existing Bot", owner="x", description="Answers payroll questions",
                    phoenix_project="existing-proj"))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_preview_says_what_each_row_does_and_commit_does_only_that(client):
    text = HEADER + "\n".join([
        "Route Planner,Plans delivery routes,Finance,Ideation,,Autonomous Agent,,Route planning|Load balancing,1500",
        "Live Already,Scores leads,finance,Production,Live since 2025 before the registry existed,Autonomous Agent,,,",
        "No Reason,Scores leads too,Finance,Production,,Autonomous Agent,,,",
        "Existing Bot,Anything,Finance,Ideation,,Autonomous Agent,,,",
        "Other Name,Anything,Finance,Ideation,,Autonomous Agent,existing-proj,,",
        "Bad Dept,x,Marketing,Ideation,,Autonomous Agent,,,",
        "Route Planner,dup,Finance,Ideation,,Autonomous Agent,,,",
    ])
    preview = (await client.post("/api/v1/agents/import/preview", json={"csv": text})).json()
    actions = {r["name"] + str(r["line"]): r["action"] for r in preview["rows"]}
    assert actions == {"Route Planner2": "create", "Live Already3": "create", "No Reason4": "error", "Existing Bot5": "skip",
                       "Other Name6": "skip", "Bad Dept7": "error", "Route Planner8": "error"}
    assert preview["summary"] == {"create": 2, "skip": 2, "error": 3}
    done = (await client.post("/api/v1/agents/import/commit", json={"csv": text})).json()
    assert [c["name"] for c in done["created"]] == ["Route Planner", "Live Already"] and done["failed"] == []
    live = (await client.get(f"/api/v1/agents/{done['created'][1]['id']}")).json()
    assert live["stage"] == "Production" and live["dept"] == "dept-fin"
    planner = (await client.get(f"/api/v1/agents/{done['created'][0]['id']}")).json()
    assert planner["capabilities"] == ["Route planning", "Load balancing"] and planner["valueAmount"] == 1500


@pytest.mark.asyncio
async def test_template_and_a_file_without_header(client):
    t = await client.get("/api/v1/agents/import/template.csv")
    assert t.status_code == 200 and t.text.startswith("name,description,owner")
    assert (await client.post("/api/v1/agents/import/preview", json={"csv": "just,text\n1,2"})).status_code == 422
