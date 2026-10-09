"""A governance finding names an agent that is already registered, so registering
it again is refused. Runs against a throwaway DB."""
from __future__ import annotations

from datetime import date

import httpx
import pytest


@pytest.mark.asyncio
async def test_a_finding_about_a_registered_agent_cannot_be_registered_again():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Discovery, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Invoice Agent", owner="Ops", description="x"))
        s.add(Discovery(id="d1", org_id="org-default", suspected_name="Invoice Agent", source="governance_gap", confidence=85,
                        signal="Agent has no governance reviews", first_seen=date(2026, 10, 1)))
        s.add(Discovery(id="d2", org_id="org-default", suspected_name="Concentration risk: SAP", source="concentration_risk", confidence=75,
                        signal="3 agents depend on SAP", first_seen=date(2026, 10, 1)))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.post("/api/v1/discoveries/d1/register")).status_code == 409
            assert (await c.post("/api/v1/discoveries/d2/register")).status_code == 409      # a shared system is not an agent
            row = (await c.get("/api/v1/approvals")).json()["discoveries"]
            assert {d["id"]: d["agentId"] for d in row} == {"d1": "a1", "d2": None}
            assert (await c.post("/api/v1/discoveries/d2/dismiss")).status_code == 200
            assert [d["id"] for d in (await c.get("/api/v1/approvals")).json()["discoveries"]] == ["d1"]
            assert len((await c.get("/api/v1/agents/?limit=100")).json()["data"]) == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_findings_use_the_stalled_rule_of_executive_and_leave_shared_systems_out():
    from datetime import datetime, timedelta, timezone

    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from orchestrations.discovery_pipeline import scan_sources

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    old = datetime.now(timezone.utc) - timedelta(weeks=20)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        # Development has a limit of 16 weeks: the earlier rule looked only at Ideation.
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Slow Build", owner="Ops", description="x",
                    lifecycle_stage="Development", created_at=old, enterprise_systems=["SAP"]))
        s.add(Agent(id="a2", org_id="org-default", slug="a2", name="Other", owner="Ops", description="x",
                    lifecycle_stage="Production", enterprise_systems=["SAP"]))
    try:
        found = (await scan_sources("org-default"))["raw_findings"]
        stalled = [f for f in found if f["source"] == "agents_table"]
        assert [f["name"] for f in stalled] == ["Slow Build"] and "limit is 16" in stalled[0]["signal"]
        assert not [f for f in found if f["source"] == "concentration_risk"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleared_follows_the_reviews_the_risk_level_requires():
    from api.routers.registry import review_position

    two = ["arb", "security"]                      # a risk level whose rules ask for two reviews
    assert review_position({"arb": "Approved", "security": "Approved with Conditions"}, two) == "cleared"
    assert review_position({"arb": "Approved", "security": "Approved", "dp": "Changes Requested"}, two) == "cleared"   # dp is not required
    assert review_position({"arb": "Approved", "security": "In Review"}, two) == "in_review"
    assert review_position({"arb": "Changes Requested", "security": "In Review"}, two) == "blocked"
    assert review_position({"arb": "Approved"}, ["arb", "security", "dp"]) == "open"
