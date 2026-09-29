"""Identify and consume through the API: registry search and certification,
the registration duplicate check, and the Integrate tab (contract, access
requests, Try it). Runs against a throwaway DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

AGENTS = {
    "prod": dict(name="Invoice Reconciliation Agent", lifecycle_stage="Production",
                 description="Matches incoming vendor invoices against purchase orders.",
                 api_endpoint="https://agent.example.com/run", inputs=["Vendor invoice"],
                 outputs=["Match disposition"], consumers=["AP Dashboard"]),
    "risky": dict(name="Fraud Scoring Model", lifecycle_stage="Production",
                  description="Scores card transactions for fraud."),
    "wasteful": dict(name="Campaign Copy Writer", lifecycle_stage="Production",
                     description="Drafts marketing campaign copy."),
    "dev": dict(name="Pricing Optimizer", lifecycle_stage="Development", description="Suggests deal pricing."),
    "old": dict(name="Change Validator", lifecycle_stage="Deprecated", description="Validates change tickets.",
                api_endpoint="https://old.example.com/run"),
    "relative": dict(name="Support Triage", lifecycle_stage="Production", description="Routes support tickets.",
                     api_endpoint="/agents/v1/support-triage"),
}
APPROVED_AGENTS = ("prod", "risky", "wasteful", "old", "relative")
user = {"user_id": "u1", "role": "admin"}


@pytest_asyncio.fixture
async def db():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentRisk, Department, GovernanceReview, Organization, User, WasteFinding
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    expires = datetime.now(timezone.utc) + timedelta(days=200)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Department(id="dept-finance", org_id="org-default", name="Finance"))
            s.add(User(id="u1", org_id="org-default", email="alice@example.com", name="Alice", password_hash="x"))
            s.add(User(id="u2", org_id="org-default", email="bob@example.com", name="Bob", password_hash="x"))
            for aid, fields in AGENTS.items():
                s.add(Agent(id=aid, org_id="org-default", slug=aid, owner="Ops", **fields))
                for gate in ("arb", "security", "dp"):
                    approved = aid in APPROVED_AGENTS
                    s.add(GovernanceReview(id=f"{aid}-{gate}", agent_id=aid, gate=gate,
                                           status="Approved" if approved else "In Review",
                                           expires_at=expires if approved else None))
            s.add(AgentRisk(id="R1", agent_id="risky", category="SECURITY", severity="HIGH", title="Open port",
                            source="manual", status="open", history=[]))
            s.add(AgentRisk(id="R2", agent_id="prod", category="OPERATIONAL", severity="MEDIUM", title="Slow",
                            source="manual", status="open", history=[]))
            # HIGH and FINANCIAL: never stored in agent_risks, read live.
            s.add(WasteFinding(id="W1", agent_id="wasteful", waste_type="idle_agent", severity="HIGH",
                               monthly_waste_cents=90000, status="open"))
        yield get_db_session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db):
    from api.auth import require_create, require_delete, require_read, require_update
    from api.routers.ops import integrate
    from api.routers.ops.risk import router as risk_router
    from api.routers.ops.tokenomics import router as tokenomics_router
    from api.routers.registry import agents_router

    integrate._recent_calls.clear()
    user.update(user_id="u1")
    app = FastAPI()
    for r in (integrate.router, risk_router, tokenomics_router, agents_router):
        app.include_router(r)
    for dep in (require_read, require_update, require_create, require_delete):
        app.dependency_overrides[dep] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def as_user(user_id: str) -> None:
    user["user_id"] = user_id


async def _integration(client, agent_id="prod") -> dict:
    return (await client.get(f"/api/v1/agents/{agent_id}/integration")).json()


# ── Identify ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_certified_badge_agrees_with_the_risk_and_governance_tabs(client):
    listing = (await client.get("/api/v1/agents/?limit=100")).json()["data"]
    by_id = {a["id"]: a for a in listing}
    assert {a["id"] for a in listing if a["reuse"]["certified"]} == {"prod", "relative"}

    for agent_id, agent in by_id.items():
        risk = (await client.get(f"/api/v1/agents/{agent_id}/risks")).json()["score"]
        blocked = any(u["code"] == "open_high_risk" for u in agent["reuse"]["unmet"])
        assert blocked == (risk["worst"] in ("HIGH", "CRITICAL")), agent_id
    # A stored HIGH risk and a live FINANCIAL one both block.
    assert [u["code"] for u in by_id["risky"]["reuse"]["unmet"]] == ["open_high_risk"]
    assert [u["code"] for u in by_id["wasteful"]["reuse"]["unmet"]] == ["open_high_risk"]
    assert [u["code"] for u in by_id["old"]["reuse"]["unmet"]] == ["stage"]
    assert by_id["prod"]["card"]["consumerCount"] == 1


@pytest.mark.asyncio
async def test_certified_filter_and_capability_search(client):
    certified = (await client.get("/api/v1/agents/?certified=true")).json()
    assert {a["id"] for a in certified["data"]} == {"prod", "relative"}
    assert certified["pagination"]["total"] == 2

    found = (await client.get("/api/v1/agents/", params={"q": "reconcile invoices"})).json()
    assert [a["id"] for a in found["data"]] == ["prod"]
    assert found["data"][0]["matchedTerms"] == ["reconcile", "invoices"]
    assert (await client.get("/api/v1/agents/", params={"q": "weather radar"})).json()["data"] == []


@pytest.mark.asyncio
async def test_registration_is_refused_until_the_team_says_why_no_existing_agent_fits(client):
    new = {"name": "Invoice Reconciliation Bot", "description": "Matches vendor invoices against purchase orders",
           "capabilities": ["Invoice matching"], "inputs": ["Invoice PDF"], "rate_limit": "5/s"}
    similar = (await client.post("/api/v1/agents/similar", json=new)).json()["similar"]
    assert [m["id"] for m in similar] == ["prod"] and similar[0]["certified"] is True

    refused = await client.post("/api/v1/agents/", json=new)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "similar_agents_exist"
    assert (await client.post("/api/v1/agents/", json={**new, "reuse_justification": "too short"})).status_code == 409

    reason = "Needs line-level matching for multi-currency invoices, which prod does not support"
    created = await client.post("/api/v1/agents/", json={**new, "reuse_justification": reason})
    assert created.status_code == 200
    detail = await _integration(client, created.json()["id"])
    assert detail["reuseCheck"]["justification"] == reason
    assert [c["id"] for c in detail["reuseCheck"]["checked"]] == ["prod"]
    assert detail["contract"]["capabilities"] == ["Invoice matching"]
    assert detail["contract"]["rateLimit"] == "5/s"


@pytest.mark.asyncio
async def test_registration_cleans_lists_and_limits_field_lengths(client):
    created = await client.post("/api/v1/agents/", json={
        "name": "Weather Reporter", "description": "Posts the daily weather forecast",
        "capabilities": [" Weather  forecast ", "weather forecast", ""], "inputs": ["City", "city"],
    })
    detail = await _integration(client, created.json()["id"])
    assert detail["contract"]["capabilities"] == ["Weather forecast"]
    assert detail["contract"]["inputs"] == ["City"]
    too_long = await client.post("/api/v1/agents/", json={"name": "Radar", "rate_limit": "x" * 300})
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_an_unrelated_registration_needs_no_justification(client):
    created = await client.post("/api/v1/agents/", json={"name": "Weather Reporter",
                                                         "description": "Posts the daily weather forecast"})
    assert created.status_code == 200
    assert (await _integration(client, created.json()["id"]))["reuseCheck"] == {"checked": [], "justification": None}


# ── Contract ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contract_edit_cleans_lists_rejects_tracing_urls_and_is_audited(client, db):
    from db.models import AuditLog

    bad = await client.put("/api/v1/agents/prod/contract", json={"api_endpoint": "https://x.example.com:6006/v1/traces"})
    assert bad.status_code == 422

    ok = await client.put("/api/v1/agents/prod/contract", json={
        "capabilities": [" Invoice   matching ", "invoice matching", "", "PO lookup"], "rate_limit": " 10 req/s ",
    })
    assert ok.json()["fields"] == ["capabilities", "rate_limit"]
    detail = await _integration(client)
    assert detail["contract"]["capabilities"] == ["Invoice matching", "PO lookup"]
    assert detail["contract"]["rateLimit"] == "10 req/s"
    assert detail["contract"]["inputs"] == ["Vendor invoice"]  # untouched
    async with db() as s:
        audit = (await s.execute(select(AuditLog).where(AuditLog.entity_id == "prod"))).scalars().all()
    assert audit[-1].changes["rate_limit"] == {"before": None, "after": "10 req/s"}


# ── Access requests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_access_request_approval_puts_the_team_in_the_dependency_graph(client, db):
    from services.graph_service import build_graph

    as_user("u2")
    rid = (await client.post("/api/v1/agents/prod/access-requests",
                             json={"team": "Treasury Ops", "purpose": "Reconcile treasury invoices daily"})).json()["id"]
    dup = await client.post("/api/v1/agents/prod/access-requests",
                            json={"team": "treasury ops", "purpose": "Same team, different case"})
    assert dup.status_code == 409

    own = await client.post(f"/api/v1/agents/prod/access-requests/{rid}/decision", json={"decision": "approve"})
    assert own.status_code == 403

    as_user("u1")
    assert (await client.post(f"/api/v1/agents/prod/access-requests/{rid}/decision",
                              json={"decision": "approve"})).json()["status"] == "approved"
    detail = await _integration(client)
    assert detail["consumers"] == {"approvedTeams": ["Treasury Ops"], "declared": ["AP Dashboard"]}
    [req] = detail["accessRequests"]
    assert req["requesterName"] == "Bob <bob@example.com>" and req["decidedBy"] == "Alice <alice@example.com>"
    async with db() as s:
        graph = await build_graph(s)
    assert {"from": "prod", "to": "consumer:Treasury Ops", "type": "CONSUMED_BY"} in graph["edges"]

    decide = f"/api/v1/agents/prod/access-requests/{rid}/decision"
    assert (await client.post(decide, json={"decision": "revoke"})).status_code == 422  # note required
    assert (await client.post(decide, json={"decision": "approve"})).status_code == 409  # already approved
    assert (await client.post(decide, json={"decision": "revoke", "note": "Contract ended"})).json()["status"] == "revoked"
    assert (await _integration(client))["consumers"] == {"approvedTeams": [], "declared": ["AP Dashboard"]}


@pytest.mark.asyncio
async def test_revoking_never_removes_a_consumer_the_owner_declared(client):
    as_user("u2")
    rid = (await client.post("/api/v1/agents/prod/access-requests",
                             json={"team": "AP Dashboard", "purpose": "Formalise the existing dashboard feed"})).json()["id"]
    as_user("u1")
    decide = f"/api/v1/agents/prod/access-requests/{rid}/decision"
    await client.post(decide, json={"decision": "approve"})
    await client.post(decide, json={"decision": "revoke", "note": "Testing revoke"})
    assert (await _integration(client))["consumers"]["declared"] == ["AP Dashboard"]


@pytest.mark.asyncio
async def test_rejection_needs_a_note_and_deprecated_agents_take_no_requests(client):
    as_user("u2")
    rid = (await client.post("/api/v1/agents/prod/access-requests",
                             json={"team": "Sales Ops", "purpose": "Explore invoice matching for deals"})).json()["id"]
    as_user("u1")
    decide = f"/api/v1/agents/prod/access-requests/{rid}/decision"
    assert (await client.post(decide, json={"decision": "reject", "note": " "})).status_code == 422
    assert (await client.post(decide, json={"decision": "reject", "note": "Use the CRM agent"})).json()["status"] == "rejected"
    assert (await _integration(client))["consumers"]["approvedTeams"] == []
    old = await client.post("/api/v1/agents/old/access-requests", json={"team": "X team", "purpose": "Some purpose here"})
    assert old.status_code == 409


@pytest.mark.asyncio
async def test_deleting_an_agent_removes_its_access_requests(client, db):
    from db.models import AgentAccessRequest

    await client.post("/api/v1/agents/prod/access-requests", json={"team": "Ops", "purpose": "Daily reconciliation"})
    assert (await client.delete("/api/v1/agents/prod")).status_code == 200
    async with db() as s:
        assert (await s.execute(select(AgentAccessRequest))).scalars().all() == []


@pytest.mark.asyncio
async def test_cost_is_reported_unknown_not_zero_when_no_model_price_exists(client, db):
    """An agent whose traces ran on a model with no price has an unknown
    cost, not a $0 one. A false zero would make it look like the cheapest
    agent in the portfolio."""
    from db.models import AgentTokenUsage

    async with db() as s:
        s.add(AgentTokenUsage(agent_id="dev", bucket=datetime.now(timezone.utc), model_name="fixture-model",
                              invocation_count=100, input_tokens=5000, output_tokens=1000, source="phoenix"))
    card = next(a for a in (await client.get("/api/v1/agents/?limit=100")).json()["data"]
                if a["id"] == "dev")["card"]
    assert card["pricing"] == "missing" and card["costPerCallCents"] is None

    tokenomics = (await client.get("/api/v1/agents/dev/tokenomics?days=30")).json()
    assert tokenomics["totals"]["calls"] == 100, "the calls themselves are still counted"
    assert tokenomics["unpricedModels"] == ["fixture-model"]
    assert tokenomics["totals"]["costCents"] is None
    assert tokenomics["costPerCallCents"] is None
    assert tokenomics["budget"]["monthToDateCents"] is None
    assert tokenomics["projectedPeriodEndCents"] is None


@pytest.mark.asyncio
async def test_portfolio_risk_ignores_findings_whose_agent_is_gone(client, db):
    """A finding left behind by a deleted agent appears on no Risk tab, so
    counting it in the portfolio makes the total disagree with the sum of
    its parts."""
    from db.models import CostAnomaly

    async with db() as s:
        s.add(CostAnomaly(id="C-ORPHAN", agent_id="deleted-long-ago", anomaly_type="undeclared_model",
                          severity="LOW", details={}))
    listing = (await client.get("/api/v1/agents/?limit=100")).json()["data"]
    per_agent = 0
    for a in listing:
        per_agent += (await client.get(f"/api/v1/agents/{a['id']}/risks")).json()["score"]["total"]
    portfolio = (await client.get("/api/v1/governance/risks/summary")).json()
    assert portfolio["totalFindings"] == per_agent


@pytest.mark.asyncio
async def test_no_calls_in_the_window_costs_zero_not_unknown(client, db):
    """No calls really did cost nothing — that is a $0, not an unknown."""
    from db.models import AgentTokenUsage

    async with db() as s:
        s.add(AgentTokenUsage(agent_id="relative", bucket=datetime.now(timezone.utc) - timedelta(days=120),
                              model_name="fixture-model", invocation_count=5, source="phoenix"))
    tokenomics = (await client.get("/api/v1/agents/relative/tokenomics?days=30")).json()
    assert tokenomics["totals"]["calls"] == 0
    assert tokenomics["totals"]["costCents"] == 0


# ── Edit and delete from the registry tiles ──────────────────────────────────

@pytest.mark.asyncio
async def test_profile_edit_updates_fields_and_validates(client):
    ok = await client.put("/api/v1/agents/dev", json={
        "name": "  Deal Pricing Optimizer ", "dept": "dept-finance", "ai_type": "Copilot / Assistant",
        "owner_contact": "pricing@example.com", "hours_saved_monthly": 40, "business_outcome": "Faster quotes",
    })
    assert ok.status_code == 200
    agent = (await client.get("/api/v1/agents/dev")).json()
    assert (agent["name"], agent["dept"], agent["aiType"]) == ("Deal Pricing Optimizer", "dept-finance",
                                                               "Copilot / Assistant")
    assert (agent["ownerContact"], agent["hoursSavedMonthly"], agent["businessOutcome"]) == (
        "pricing@example.com", 40, "Faster quotes")
    assert agent["stage"] == "Development"

    for bad in ({"name": "  "}, {"dept": "dept-nowhere"}, {"ai_type": "Robot"}, {"value_amount": -5},
                {"hours_saved_monthly": -1}, {"name": None}, {"owner": None}, {"description": None}):
        assert (await client.put("/api/v1/agents/dev", json=bad)).status_code == 422, bad


@pytest.mark.asyncio
async def test_delete_removes_everything_the_agent_owned(client, db):
    from api.routers.registry import _AGENT_OWNED_TABLES
    from db.models import AgentContextVersion, AgentInfraProfile, AgentRisk, AuditLog, Discovery, GovernanceReview

    async with db() as s:
        s.add(AgentContextVersion(id="cv1", agent_id="risky", content_hash="h", content="# ctx"))
        s.add(AgentInfraProfile(agent_id="risky", monthly_cost_cents=100))
        s.add(Discovery(id="d1", org_id="org-default", suspected_name="Fraud thing", source="phoenix", confidence=90,
                        status="registered", registered_agent_id="risky", first_seen=datetime(2026, 9, 1).date()))
    await client.post("/api/v1/agents/risky/access-requests", json={"team": "Ops", "purpose": "Screen payments"})
    before = (await client.get("/api/v1/governance/risks/summary")).json()["totalFindings"]
    own = (await client.get("/api/v1/agents/risky/risks")).json()["score"]["total"]
    assert own >= 1

    assert (await client.delete("/api/v1/agents/risky")).status_code == 200
    assert (await client.get("/api/v1/agents/risky")).status_code == 404
    async with db() as s:
        for model in (*_AGENT_OWNED_TABLES, GovernanceReview):
            rows = (await s.execute(select(model).where(model.agent_id == "risky"))).scalars().all()
            assert rows == [], model.__tablename__
        discovery = await s.get(Discovery, "d1")
        assert discovery is not None and discovery.registered_agent_id is None
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "delete"))).scalar_one()
        assert audit.entity_id == "risky"
    # Everything its Risk tab showed leaves the portfolio with it.
    assert (await client.get("/api/v1/governance/risks/summary")).json()["totalFindings"] == before - own


@pytest.mark.asyncio
async def test_portfolio_ignores_findings_whose_agent_is_gone(client, db):
    """A finding left behind by an agent that no longer exists must not count.
    The delete path cleans these up, but a row that survives one anyway (an
    older delete, a restore, a direct write) would otherwise make the portfolio
    total disagree with the sum of the per-agent Risk tabs, which no longer
    have anywhere to show it."""
    from db.models import AgentRisk

    before = (await client.get("/api/v1/governance/risks/summary")).json()["totalFindings"]
    async with db() as s:
        s.add(AgentRisk(
            id="orphan-risk", agent_id="an-agent-that-was-deleted", category="COMPLIANCE", severity="HIGH",
            title="Left behind", description="Its agent is gone.", source="auto", status="open",
        ))
    after = (await client.get("/api/v1/governance/risks/summary")).json()["totalFindings"]
    assert after == before, "an orphaned finding must not inflate the portfolio total"


# ── Try it ───────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_agent(monkeypatch):
    """The agent's server, as an httpx MockTransport. Set `respond` to
    change the reply; `calls` records every request that reached it."""
    from api.routers.ops import integrate

    state = {"calls": [], "addresses": ["20.1.2.3"],
             "respond": lambda req: httpx.Response(200, json={"disposition": "matched"})}

    async def resolve(host, port):
        return state["addresses"]

    def handler(request):
        state["calls"].append(request)
        return state["respond"](request)

    monkeypatch.setattr(integrate, "_resolve", resolve)
    monkeypatch.setattr(integrate, "_http_client",
                        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False))
    return state


@pytest.mark.asyncio
async def test_try_it_calls_the_agent_without_forwarding_the_callers_token(client, db, fake_agent):
    from db.models import AuditLog

    result = (await client.post("/api/v1/agents/prod/try", json={"body": {"vendor_invoice": "INV-1"}},
                                headers={"Authorization": "Bearer secret"})).json()
    assert result["ok"] is True and result["status"] == 200
    assert result["body"] == {"disposition": "matched"}
    [sent] = fake_agent["calls"]
    assert str(sent.url) == "https://agent.example.com/run" and sent.method == "POST"
    assert sent.content == b'{"vendor_invoice": "INV-1"}'
    assert "authorization" not in sent.headers and sent.headers["x-registry-try-it"] == "true"
    async with db() as s:
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "try_it"))).scalar_one()
    assert audit.changes["status"] == 200 and "INV-1" not in str(audit.changes)


@pytest.mark.asyncio
async def test_try_it_refuses_metadata_addresses_before_any_request(client, fake_agent):
    fake_agent["addresses"] = ["169.254.169.254"]
    refused = await client.post("/api/v1/agents/prod/try", json={"body": {}})
    assert refused.status_code == 422 and "link-local" in refused.json()["detail"]
    assert fake_agent["calls"] == []


@pytest.mark.asyncio
async def test_try_it_does_not_follow_redirects(client, fake_agent):
    fake_agent["respond"] = lambda req: httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    result = (await client.post("/api/v1/agents/prod/try", json={"body": {}})).json()
    assert result["status"] == 302 and result["location"] == "http://169.254.169.254/"
    assert len(fake_agent["calls"]) == 1


@pytest.mark.asyncio
async def test_try_it_reports_an_unreachable_agent_as_a_result_not_a_crash(client, fake_agent):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    fake_agent["respond"] = refuse
    result = (await client.post("/api/v1/agents/prod/try", json={"body": {}})).json()
    assert result["ok"] is False and "ConnectError" in result["error"]


@pytest.mark.asyncio
async def test_try_it_explains_why_an_agent_cannot_be_called(client, fake_agent):
    relative = await client.post("/api/v1/agents/relative/try", json={"body": {}})
    assert relative.status_code == 422 and "AGENT_GATEWAY_BASE_URL" in relative.json()["detail"]
    old = await client.post("/api/v1/agents/old/try", json={"body": {}})
    assert old.status_code == 422 and "deprecated" in old.json()["detail"]
    assert fake_agent["calls"] == []


@pytest.mark.asyncio
async def test_try_it_stops_reading_a_huge_response(client, fake_agent):
    from api.routers.ops.integrate import MAX_RESPONSE_BYTES

    fake_agent["respond"] = lambda req: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES * 20),
                                                       headers={"content-type": "application/json"})
    result = (await client.post("/api/v1/agents/prod/try", json={"body": {}})).json()
    assert result["truncated"] is True and len(result["body"]) == MAX_RESPONSE_BYTES


@pytest.mark.asyncio
async def test_try_it_is_rate_limited_per_user_and_agent(client, fake_agent):
    from shared.config import get_settings

    limit = get_settings().try_it_calls_per_minute
    for _ in range(limit):
        assert (await client.post("/api/v1/agents/prod/try", json={"body": {}})).status_code == 200
    assert (await client.post("/api/v1/agents/prod/try", json={"body": {}})).status_code == 429
    as_user("u2")
    assert (await client.post("/api/v1/agents/prod/try", json={"body": {}})).status_code == 200
