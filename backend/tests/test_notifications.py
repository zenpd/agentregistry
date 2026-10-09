"""Notifications: who gets told about what, one digest per person per day,
inbox reads, and delivery that records 'not configured' instead of failing."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from api.auth import ROLES
from governance import notify_rules as rules

TODAY = date(2026, 10, 8)
USERS = [{"id": "adm", "role": "Registry Admin"}, {"id": "sec", "role": "Security Reviewer"},
         {"id": "own", "role": "Product Owner"}]


def test_reviews_go_to_the_deciding_role_and_admins_only_when_nobody_holds_it():
    d = rules.build_digests(today=TODAY, users=USERS, roles=ROLES,
                            reviews=[{"agentId": "a", "agentName": "A", "gate": "security", "since": TODAY - timedelta(days=3)},
                                     {"agentId": "a", "agentName": "A", "gate": "arb", "since": TODAY}],
                            expiring=[], requests=[], budgets=[], projects=[], risks=[])
    assert [i["text"] for i in d["sec"]] == ["A: the Security Review has waited for a decision for 3 days."]
    assert [i["text"] for i in d["adm"]] == ["A: the Architecture Review Board has waited for a decision for 0 days."]
    assert "own" not in d


def test_owner_items_reach_the_linked_owner_and_the_admins():
    d = rules.build_digests(today=TODAY, users=USERS, roles=ROLES, reviews=[], expiring=[], projects=[],
                            requests=[{"agentId": "a", "agentName": "A", "team": "Payments", "ownerUserId": "own"}],
                            budgets=[{"agentId": "a", "agentName": "A", "state": "over_budget", "usedPct": 112.0, "ownerUserId": None}],
                            risks=[{"agentId": "a", "agentName": "A", "title": "Leak", "dueDate": date(2026, 10, 1), "ownerUserId": "own"}])
    assert len(d["own"]) == 2 and len(d["adm"]) == 3
    assert "is over its monthly budget" in d["adm"][1]["text"]
    assert rules.digest_subject(d["adm"]) == "Agent Registry: 3 items for you today"
    assert {s["text"] for s in rules.channel_summary(d)} == {"1 access requests", "1 budget alerts", "1 overdue risks"}


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, GovernanceReview, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(User(id="adm", org_id="org-default", email="adm@x.io", name="Ada", role="Registry Admin", password_hash="x"))
        s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Real One", owner="x", description="x"))
        s.add(Agent(id="d1", org_id="org-default", slug="d1", name="Demo One", owner="x", description="x", is_demo=True))
        for aid in ("a1", "d1"):
            s.add(GovernanceReview(id=f"{aid}-arb", agent_id=aid, gate="arb", status="In Review",
                                   updated_at=datetime.now(timezone.utc) - timedelta(days=2)))

    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_job_stores_one_digest_per_person_per_day_and_skips_demo_agents(client, monkeypatch):
    from shared.config import get_settings

    monkeypatch.setattr(get_settings(), "smtp_host", "")
    from orchestrations.notifications import send_daily_notifications

    first = await send_daily_notifications()
    assert first["digestsStored"] == 1 and first["items"] == 1 and first["email"]["not_configured"] == 1
    again = await send_daily_notifications()
    assert again["digestsStored"] == 0
    inbox = (await client.get("/api/v1/notifications/mine")).json()
    assert inbox["unread"] == 1
    [n] = inbox["rows"]
    assert n["items"][0]["text"].startswith("Real One: the Architecture Review Board has waited")
    assert n["deliveries"]["email"]["status"] == "not_configured"
    assert (await client.post(f"/api/v1/notifications/{n['id']}/read")).status_code == 200
    assert (await client.get("/api/v1/notifications/mine")).json()["unread"] == 0


@pytest.mark.asyncio
async def test_a_failed_scheduled_job_tells_the_admins_once_a_day(client):
    from services import notify

    await notify.job_failed("usage_ingestion", "Usage ingestion (Phoenix)", "unreachable", "Phoenix did not answer")
    await notify.job_failed("usage_ingestion", "Usage ingestion (Phoenix)", "unreachable", "Phoenix did not answer")
    rows = (await client.get("/api/v1/notifications/mine")).json()["rows"]
    assert [r["kind"] for r in rows] == ["job_failed"]
    assert "Phoenix did not answer" in rows[0]["items"][0]["text"]


@pytest.mark.asyncio
async def test_status_and_test_message(client):
    status = (await client.get("/api/v1/notifications/status")).json()
    assert status["inApp"] is True and "smtp_password" not in str(status)
    sent = (await client.post("/api/v1/notifications/test")).json()
    assert sent["id"] and sent["deliveries"]["email"]["status"] in ("not_configured", "sent", "failed")


def test_items_for_someone_away_go_to_their_deputy():
    from datetime import date as _d
    users = [{"id": "sec", "role": "Security Reviewer", "name": "Sam", "awayUntil": _d(2026, 10, 20), "deputy": "sec2"},
             {"id": "sec2", "role": "Security Reviewer", "name": "Sue"}, {"id": "adm", "role": "Registry Admin"}]
    d = rules.build_digests(today=TODAY, users=users, roles=ROLES,
                            reviews=[{"agentId": "a", "agentName": "A", "gate": "security", "since": TODAY - timedelta(days=9), "slaDays": 5}],
                            expiring=[], requests=[], budgets=[], projects=[], risks=[])
    assert "sec" not in d
    assert any(t["text"].startswith("For Sam, who is away until 2026-10-20: A: the Security Review has waited") and t["text"].endswith("It is overdue.")
               for t in d["sec2"])
