"""Ownership and delegation: transfer with a backup owner, the backup taking over
when an owner is deactivated, orphans, away periods with a deputy, and the review
queue ranked by findings, risk tier and wait. Runs against a throwaway DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def setup():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentRisk, GovernanceReview, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    old = datetime.now(timezone.utc) - timedelta(days=9)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        for uid, name, role in (("adm", "Admin", "Registry Admin"), ("ana", "Ana", "Product Owner"), ("ben", "Ben", "Product Owner"),
                                ("sec", "Sam", "Security Reviewer"), ("sec2", "Sue", "Security Reviewer")):
            s.add(User(id=uid, org_id="org-default", email=f"{uid}@x.io", name=name, role=role, password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Claims Bot", owner="Ops", description="x" * 30, lifecycle_stage="Testing"))
        s.add(Agent(id="a2", org_id="org-default", slug="a2", name="Quiet Bot", owner="Ops", description="x" * 30,
                    lifecycle_stage="Testing", risk_level="HIGH"))
        s.add(Agent(id="a3", org_id="org-default", slug="a3", name="Old Low", owner="Ops", description="x" * 30,
                    lifecycle_stage="Testing", risk_level="LOW"))
        s.add(GovernanceReview(id="a1-sec", agent_id="a1", gate="security", status="In Review"))
        s.add(GovernanceReview(id="a2-sec", agent_id="a2", gate="security", status="In Review"))
        s.add(GovernanceReview(id="a3-sec", agent_id="a3", gate="security", status="In Review", updated_at=old))
        s.add(AgentRisk(id="r1", agent_id="a1", category="SECURITY", severity="CRITICAL", title="Prompt injection", status="open"))
    from api.auth import get_current_user
    from api.main import app

    who = {"id": "adm", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, who
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_and_backup_are_set_and_checked(setup):
    c, _ = setup
    r = await c.put("/api/v1/agents/a1/ownership", json={"ownerUserId": "ana", "backupOwnerUserId": "ana"})
    assert r.status_code == 422 and "different person" in r.json()["detail"]
    r = (await c.put("/api/v1/agents/a1/ownership", json={"ownerUserId": "ana", "backupOwnerUserId": "ben", "reason": "Team change"})).json()
    assert r == {"owner": "Ana", "ownerUserId": "ana", "backupOwnerUserId": "ben"}
    agent = (await c.get("/api/v1/agents/a1")).json()
    assert agent["owner"] == "Ana" and agent["backupOwnerUserId"] == "ben"
    audit = (await c.get("/api/v1/audit?entity=a1&kind=all")).json()["rows"]
    assert [r["action"] for r in audit] == ["ownership.transfer"] and audit[0]["entityName"] == "Claims Bot"


@pytest.mark.asyncio
async def test_the_backup_takes_over_when_the_owner_is_deactivated_else_the_agent_is_an_orphan(setup):
    c, _ = setup
    await c.put("/api/v1/agents/a1/ownership", json={"ownerUserId": "ana", "backupOwnerUserId": "ben"})
    await c.put("/api/v1/agents/a2/ownership", json={"ownerUserId": "ana"})
    assert (await c.put("/api/v1/admin/users/ana", json={"isActive": False})).status_code == 200
    a1 = (await c.get("/api/v1/agents/a1")).json()
    assert a1["owner"] == "Ben" and a1["ownerUserId"] == "ben" and a1["backupOwnerUserId"] is None
    att = (await c.get("/api/v1/portfolio/attention")).json()
    assert [o["name"] for o in att["ownerless"]] == ["Quiet Bot"] and "can no longer sign in" in att["ownerless"][0]["text"]


@pytest.mark.asyncio
async def test_review_queue_is_ranked_and_names_who_can_decide_and_who_is_away(setup):
    c, who = setup
    who.update(id="sec", role="Security Reviewer")
    until = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    r = await c.put("/api/v1/auth/me/away", json={"awayUntil": until, "deputyUserId": "sec2"})
    assert r.status_code == 200, r.text
    assert (await c.put("/api/v1/auth/me/away", json={"awayUntil": until, "deputyUserId": "sec"})).status_code == 422
    who.update(id="adm", role="Registry Admin")
    reviews = (await c.get("/api/v1/approvals")).json()["reviews"]
    assert [r["agentName"] for r in reviews] == ["Claims Bot", "Quiet Bot", "Old Low"]   # critical finding, then HIGH tier, then LOW
    assert reviews[0]["criticalFindings"] == 1 and reviews[1]["riskTier"] == "HIGH"
    assert reviews[2]["overdue"] is True and reviews[2]["daysWaiting"] >= 9 and reviews[0]["overdue"] is False
    d = reviews[0]["deciders"]
    assert d["available"] == ["Sue"] and d["away"] == [{"name": "Sam", "until": until, "deputy": "Sue"}]


@pytest.mark.asyncio
async def test_history_lists_decisions_with_who_and_what(setup):
    c, _ = setup
    assert (await c.put("/api/v1/agents/a3/governance/security", json={"status": "Approved", "notes": "Pen test passed"})).status_code == 200
    rows = (await c.get("/api/v1/approvals/history")).json()["rows"]
    assert rows and rows[0]["agentName"] == "Old Low" and rows[0]["actor"] == "Admin"
    assert "Approved" in rows[0]["summary"]
