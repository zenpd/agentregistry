"""The approvals inbox: what is waiting for a decision across the registry.
Runs against a throwaway DB."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

user = {"user_id": "u1", "role": "admin"}
T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db():
    from db.base import Base, engine, get_db_session
    from db.models import (Agent, AgentAccessRequest, Discovery, GovernanceReview, Organization)
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    later = datetime.now(timezone.utc) + timedelta(days=200)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            for aid, stage in (("cert", "Production"), ("draft", "Development"), ("old", "Deprecated")):
                s.add(Agent(id=aid, org_id="org-default", slug=aid, name=aid.title(), owner="Ops",
                            lifecycle_stage=stage, description="x"))
            for gate in ("arb", "security", "dp"):
                s.add(GovernanceReview(id=f"cert-{gate}", agent_id="cert", gate=gate, status="Approved",
                                       expires_at=later))
            s.add(GovernanceReview(id="draft-arb", agent_id="draft", gate="arb", status="In Review", updated_at=T0))
            s.add(GovernanceReview(id="draft-sec", agent_id="draft", gate="security", status="Changes Requested"))
            s.add(GovernanceReview(id="old-dp", agent_id="old", gate="dp", status="In Review"))
            s.add(AgentAccessRequest(id="r-new", agent_id="draft", requester_id="u2", requester_name="Bob",
                                     team="Payments", purpose="Route payouts", status="pending",
                                     created_at=T0 + timedelta(days=2)))
            s.add(AgentAccessRequest(id="r-old", agent_id="cert", requester_id="u1", requester_name="Alice",
                                     team="Lending", purpose="Score applications", status="pending", created_at=T0))
            s.add(AgentAccessRequest(id="r-done", agent_id="cert", requester_id="u2", team="Ops",
                                     purpose="Already decided", status="approved"))
            s.add(Discovery(id="d-low", org_id="org-default", suspected_name="Low bot", source="logs",
                            confidence=60, status="pending", first_seen=date(2026, 9, 3)))
            s.add(Discovery(id="d-high", org_id="org-default", suspected_name="High bot", source="Slack",
                            confidence=91, status="pending", first_seen=date(2026, 9, 1)))
            s.add(Discovery(id="d-gone", org_id="org-default", suspected_name="Dismissed", source="x",
                            confidence=99, status="dismissed", first_seen=date(2026, 9, 1)))
        yield get_db_session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db):
    from api.auth import require_read
    from api.routers.ops.approvals import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_read] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_pending_access_requests_oldest_first_with_what_an_approver_needs(client):
    inbox = (await client.get("/api/v1/approvals")).json()
    reqs = inbox["accessRequests"]
    assert [r["id"] for r in reqs] == ["r-old", "r-new"]          # decided requests are not waiting
    old, new = reqs
    assert old["agentName"] == "Cert" and old["certified"] is True and old["mine"] is True
    assert new["agentStage"] == "Development" and new["certified"] is False and new["mine"] is False


@pytest.mark.asyncio
async def test_only_gates_waiting_on_a_reviewer_and_never_for_retired_agents(client):
    reviews = (await client.get("/api/v1/approvals")).json()["reviews"]
    assert [(r["agentId"], r["gate"]) for r in reviews] == [("draft", "arb")]
    assert reviews[0]["gateLabel"] == "Architecture Review Board" and reviews[0]["reviewerRole"] == "ARB chair"


@pytest.mark.asyncio
async def test_pending_discoveries_most_confident_first(client):
    inbox = (await client.get("/api/v1/approvals")).json()
    assert [d["id"] for d in inbox["discoveries"]] == ["d-high", "d-low"]
    assert inbox["discoveries"][0]["firstSeen"] == "2026-09-01"
    assert inbox["counts"] == {"accessRequests": 2, "reviews": 1, "discoveries": 2, "total": 5}


@pytest.mark.asyncio
async def test_the_inbox_changes_nothing(client, db):
    from sqlalchemy import func, select
    from db.models import AgentAccessRequest, AuditLog

    await client.get("/api/v1/approvals")
    async with db() as s:
        pending = (await s.execute(select(func.count()).where(AgentAccessRequest.status == "pending"))).scalar()
        audits = (await s.execute(select(func.count()).select_from(AuditLog))).scalar()
    assert pending == 2 and audits == 0
