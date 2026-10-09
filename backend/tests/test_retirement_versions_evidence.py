"""Retirement steps, versions with consumers, the controls list and the tool-call share.
Runs against a throwaway DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from discovery import observed_deps


def test_tool_call_share_counts_calls_by_tool_or_server():
    spans = [{"name": "search", "span_kind": "TOOL", "attributes": {"tool.name": "search_customers", "mcp.server": "crm"}},
             {"name": "search", "span_kind": "TOOL", "attributes": {"tool.name": "search_customers", "mcp.server": "crm"}},
             {"name": "pay", "span_kind": "TOOL", "attributes": {"tool.name": "make_payment"}},
             {"name": "llm", "span_kind": "LLM", "attributes": {"llm.model_name": "gpt-4.1"}}]
    calls = observed_deps.tool_calls(spans)
    assert calls == [{"tool": "search_customers", "server": "crm", "count": 2}, {"tool": "make_payment", "server": None, "count": 1}]
    share = observed_deps.approved_call_share(calls, ["CRM "])
    assert share == {"total": 3, "approved": 2, "share": 67, "notApproved": [{"name": "make_payment", "count": 1}]}
    assert observed_deps.approved_call_share([], ["crm"])["share"] is None


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentAccessRequest, AgentIdentity, AgentTokenUsage, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(timezone.utc)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("pat", "Pat", "Product Owner")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Claims Bot", owner="Ops", description="x" * 30, version="1.0",
                    lifecycle_stage="Production", phoenix_project="claims", consumers=["Payments", "Legacy Team"], model_name="gpt-4o"))
        s.add(Agent(id="a2", org_id="org-default", slug="a2", name="Claims Bot Two", owner="Ops", description="x" * 30))
        s.add(AgentIdentity(agent_id="a1", service_account="svc-claims", api_key_hash="h"))
        s.add(AgentAccessRequest(id="g1", agent_id="a1", requester_id="pat", requester_name="Pat", team="Payments", purpose="pay",
                                 status="approved", added_to_consumers=True, agent_version="1.0"))
        s.add(AgentTokenUsage(agent_id="a1", bucket=now - timedelta(days=3), source="phoenix", model_name="gpt-4o",
                              invocation_count=5, input_tokens=10, output_tokens=5))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_retirement_runs_its_steps_before_the_stage_changes(setup):
    c, _ = setup
    blocked = await c.put("/api/v1/agents/a1/stage", json={"stage": "Deprecated"})
    assert blocked.status_code == 409 and "retirement steps" in blocked.json()["detail"]
    assert (await c.post("/api/v1/agents/a1/retirement", json={"reason": "short"})).status_code == 422
    r = (await c.post("/api/v1/agents/a1/retirement", json={"reason": "Replaced by the second claims bot", "replacementAgentId": "a2"})).json()
    steps = {s["key"]: s for s in r["active"]["steps"]}
    assert steps["traffic"]["state"] == "waiting" and "3 days ago" in steps["traffic"]["detail"]
    assert steps["consumers"]["state"] == "needs_confirmation" and "Pat (Payments)" in steps["consumers"]["detail"]
    assert "Legacy Team" in steps["consumers"]["detail"] and steps["stage"]["state"] == "waiting"
    mine = (await c.get("/api/v1/notifications/mine")).json()
    assert mine is not None
    r = (await c.post("/api/v1/agents/a1/retirement/confirm", json={"step": "consumers", "note": "Told the Legacy Team lead by e-mail today"})).json()
    r = (await c.post("/api/v1/agents/a1/retirement/revoke")).json()
    steps = {s["key"]: s for s in r["active"]["steps"]}
    assert steps["access"]["detail"] == "Identity key revoked, 1 access grant revoked."
    assert (await c.post("/api/v1/agents/a1/retirement/finish")).status_code == 409      # calls 3 days ago
    from db.base import get_db_session
    from sqlalchemy import update
    from db.models import AgentTokenUsage
    async with get_db_session() as s:
        await s.execute(update(AgentTokenUsage).where(AgentTokenUsage.agent_id == "a1")
                        .values(bucket=datetime.now(timezone.utc) - timedelta(days=9)))
    done = (await c.post("/api/v1/agents/a1/retirement/finish")).json()
    assert done["stage"] == "Deprecated" and done["active"] is None and done["history"][0]["status"] == "done"
    agent = (await c.get("/api/v1/agents/a1")).json()
    assert agent["stage"] == "Deprecated" and agent["consumers"] == ["Legacy Team"]
    trail = [r["action"] for r in (await c.get("/api/v1/audit?entity=a1&kind=all")).json()["rows"]]
    assert trail[:2] == ["retirement.finish", "stage_change"] and "retirement.start" in trail


@pytest.mark.asyncio
async def test_versions_record_changes_and_the_version_each_team_uses(setup):
    c, _ = setup
    assert (await c.post("/api/v1/agents/a1/versions", json={"version": "1.0", "changelog": "First release in the registry"})).status_code == 200
    from db.base import get_db_session
    from db.models import Agent
    async with get_db_session() as s:
        (await s.get(Agent, "a1")).model_name = "gpt-4.1"
    r = (await c.post("/api/v1/agents/a1/versions", json={"version": "1.1", "changelog": "Moved to a newer model"})).json()
    assert r == {"version": "1.1", "told": 1}
    assert (await c.post("/api/v1/agents/a1/versions", json={"version": "1.1", "changelog": "again and again"})).status_code == 409
    v = (await c.get("/api/v1/agents/a1/versions")).json()
    assert v["current"] == "1.1" and v["versions"][0]["structuralChanges"] == "Model (gpt-4o → gpt-4.1)"
    team = v["consumers"][0]
    assert team["version"] == "1.0" and team["behind"] == 1 and team["changedSince"] == "Model (gpt-4o → gpt-4.1)"
    assert v["consumersWithoutGrant"] == ["Legacy Team"]
    await c.put("/api/v1/agents/a1", json={"version": "9"})            # not an editable field: only a release changes it
    assert (await c.get("/api/v1/agents/a1")).json()["version"] == "1.1"
    assert (await c.put("/api/v1/agents/a1/access/g1/version", json={"version": "2.0"})).status_code == 422
    assert (await c.put("/api/v1/agents/a1/access/g1/version", json={"version": "1.1"})).json()["version"] == "1.1"
