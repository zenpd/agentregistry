"""The audit trail page: filters, people against registry automation, names
instead of ids, CSV export that records itself, and who may read it."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from governance import audit_view as av


def test_registry_runs_are_machine_events_even_when_a_page_view_started_them():
    assert av.is_machine("user-1", "insight.run") and av.is_machine("job:scheduled", "update")
    assert not av.is_machine("user-1", "gate_update")
    assert av.category_of("gate_update") == "Decisions" and av.category_of("risk_scan") == "Registry automation"
    assert av.actor_label("job:scheduled", {}) == "Registry job (scheduled)"
    assert av.summary_of("gate_update", {"gate": "arb", "before": {"status": "In Review"}, "after": {"status": "Approved"},
                                         "source": "rule_proposal"}) == "arb: In Review → Approved (rule-proposed)"
    assert av.summary_of("stage_change", {"from": None, "to": "Production", "overrideReason": "Live already"}) \
        == "new → Production · reason: Live already"


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AuditLog, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(User(id="u1", org_id="org-default", email="a@x.io", name="Ada Admin", role="Registry Admin", password_hash="x"))
        s.add(User(id="u2", org_id="org-default", email="v@x.io", name="Vic Viewer", role="Executive Viewer", password_hash="x"))
        s.add(Agent(id="d1", org_id="org-default", slug="d1", name="Demo One", owner="x", description="x", is_demo=True))
        t = datetime(2026, 10, 1, tzinfo=timezone.utc)
        s.add(AuditLog(org_id="org-default", actor="u1", action="gate_update", entity_type="agent", entity_id="d1",
                       changes={"gate": "arb", "before": {"status": "In Review"}, "after": {"status": "Approved"}}, created_at=t))
        s.add(AuditLog(org_id="org-default", actor="u1", action="insight.run", entity_type="agent", entity_id="d1", created_at=t))
        s.add(AuditLog(org_id="org-default", actor="job:scheduled", action="risk_scan", entity_type="agent_risks", created_at=t))

    from api.auth import get_current_user
    from api.main import app

    who = {"id": "u1", "role": "Registry Admin"}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": who["id"], "role": who["role"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.who = who
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_people_by_default_with_names_even_for_hidden_demo_agents(client):
    page = (await client.get("/api/v1/audit")).json()
    assert page["total"] == 1
    [row] = page["rows"]
    assert row["actor"] == "Ada Admin" and row["entityName"] == "Demo One" and row["category"] == "Decisions"
    assert row["summary"] == "arb: In Review → Approved"
    machine = (await client.get("/api/v1/audit", params={"kind": "machine"})).json()
    assert {r["action"] for r in machine["rows"]} == {"insight.run", "risk_scan"}
    assert (await client.get("/api/v1/audit", params={"kind": "all", "entity": "d1"})).json()["total"] == 2
    assert (await client.get("/api/v1/audit", params={"from": "2026-10-02"})).json()["total"] == 0


@pytest.mark.asyncio
async def test_export_is_csv_and_records_itself(client):
    r = await client.get("/api/v1/audit/export.csv", params={"kind": "all"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("When (UTC),Who") and len(lines) == 4
    after = (await client.get("/api/v1/audit", params={"action": "audit.export"})).json()
    assert after["total"] == 1 and after["rows"][0]["actionLabel"] == "Audit trail exported"


@pytest.mark.asyncio
async def test_only_admins_and_auditors_read_the_trail(client):
    client.who.update(id="u2", role="Executive Viewer")
    r = await client.get("/api/v1/audit")
    assert r.status_code == 403 and "audit trail" in r.json()["detail"]
    client.who.update(id="u2", role="Auditor")
    assert (await client.get("/api/v1/audit")).status_code == 200
