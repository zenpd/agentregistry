"""governance/risk_lifecycle.py (pure), plus the risk scan and the Risk tab
router against a throwaway DB."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from governance import risk_lifecycle as lc

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def _detected(rule_id, severity="MEDIUM", category="COMPLIANCE", title=None):
    return {"rule_id": rule_id, "category": category, "severity": severity,
            "title": title or rule_id, "description": f"about {rule_id}"}


def _row(id, rule_id=None, status="open", source="auto", severity="MEDIUM", category="COMPLIANCE",
         title=None, **extra):
    return {"id": id, "rule_id": rule_id, "category": category, "severity": severity,
            "title": title or rule_id or id, "description": None, "source": source, "status": status,
            "history": [], **extra}


def _by_id(items):
    return {item["id"]: item for item in items}


# ── reconcile ────────────────────────────────────────────────────────────────

def test_new_finding_is_inserted_open_with_history():
    plan = lc.reconcile([], [_detected("a.b")], NOW)
    [insert] = plan["inserts"]
    assert insert["rule_id"] == "a.b"
    assert insert["status"] == "open"
    assert insert["source"] == "auto"
    assert insert["last_detected_at"] == NOW
    assert insert["history"][0]["action"] == "detected"
    assert plan["counts"]["inserted"] == 1


@pytest.mark.parametrize("status", ["open", "acknowledged", "mitigating", "accepted"])
def test_still_detected_row_is_updated_in_place(status):
    extra = {"accepted_until": TODAY + timedelta(days=10)} if status == "accepted" else {}
    plan = lc.reconcile([_row("r1", "a.b", status=status, **extra)], [_detected("a.b", severity="HIGH")], NOW)
    assert plan["inserts"] == [] and plan["closes"] == []
    changes = _by_id(plan["updates"])["r1"]["changes"]
    assert changes["severity"] == "HIGH"
    assert changes["last_detected_at"] == NOW
    assert "status" not in changes
    assert changes["history"][-1]["action"] == "severity changed"


def test_resolved_row_that_reappears_is_reopened():
    plan = lc.reconcile([_row("r1", "a.b", status="resolved", resolved_at=NOW)], [_detected("a.b")], NOW)
    update = _by_id(plan["updates"])["r1"]
    assert update["changes"]["status"] == "open"
    assert update["changes"]["resolved_at"] is None
    assert "reopened" in update["actions"]
    assert plan["counts"]["reopened"] == 1


@pytest.mark.parametrize("status", ["open", "acknowledged", "mitigating"])
def test_cleared_auto_finding_is_resolved(status):
    plan = lc.reconcile([_row("r1", "a.b", status=status)], [], NOW)
    [close] = plan["closes"]
    assert close["changes"]["status"] == "resolved"
    assert close["changes"]["resolved_at"] == NOW
    assert close["changes"]["history"][-1]["action"] == "auto-resolved: condition cleared"


def test_cleared_but_unevaluated_rule_is_left_alone():
    rows = [_row("r1", "operational.trace_error_rate"), _row("r2", "compliance.gate_approval_expired.arb")]
    plan = lc.reconcile(rows, [], NOW, unevaluated=["operational.trace_error_rate", "compliance.gate_approval_expired"])
    assert plan["closes"] == [] and plan["updates"] == []
    assert plan["counts"]["unchecked"] == 2


def test_accepted_within_date_is_left_accepted_even_when_cleared():
    row = _row("r1", "a.b", status="accepted", accepted_until=TODAY)
    plan = lc.reconcile([row], [], NOW)
    assert plan == {"inserts": [], "updates": [], "closes": [], "counts": plan["counts"]}


def test_expired_acceptance_reopens_when_still_detected():
    row = _row("r1", "a.b", status="accepted", accepted_until=TODAY - timedelta(days=1))
    update = _by_id(lc.reconcile([row], [_detected("a.b")], NOW)["updates"])["r1"]
    assert update["changes"]["status"] == "open"
    assert update["changes"]["history"][-1]["action"] == "acceptance expired"
    assert update["changes"]["history"][-1]["by"] == "system"


def test_expired_acceptance_of_cleared_finding_is_reopened_then_resolved():
    row = _row("r1", "a.b", status="accepted", accepted_until=TODAY - timedelta(days=1))
    [close] = lc.reconcile([row], [], NOW)["closes"]
    assert [h["action"] for h in close["changes"]["history"]] == ["acceptance expired", "auto-resolved: condition cleared"]


@pytest.mark.parametrize("source", ["manual", "context"])
def test_manual_findings_are_never_auto_closed(source):
    row = _row("m1", None, source=source, title="Vendor lock-in")
    plan = lc.reconcile([row], [_detected("a.b")], NOW)
    assert "m1" not in _by_id(plan["updates"] + plan["closes"])


def test_expired_manual_acceptance_reopens():
    row = _row("m1", None, source="manual", status="accepted", accepted_until=TODAY - timedelta(days=3))
    update = _by_id(lc.reconcile([row], [], NOW)["updates"])["m1"]
    assert update["changes"]["status"] == "open"


def test_legacy_rows_are_matched_by_title_and_backfilled_once():
    legacy = [
        _row("L1", None, title="Security Review not approved"),
        _row("L2", None, category="OPERATIONAL", severity="LOW",
             title="2 error span(s) across 500 sampled spans (0.4%)"),
        _row("L3", None, title="Security Review not approved"),  # an old duplicate
    ]
    detected = [
        _detected("compliance.gate_not_approved.security", title="Security Review not approved"),
        _detected("operational.trace_error_rate", category="OPERATIONAL", severity="LOW",
                  title="3 error span(s) across 480 sampled spans (0.6%)"),
    ]
    plan = lc.reconcile(legacy, detected, NOW)
    updates = _by_id(plan["updates"])
    assert plan["inserts"] == []
    assert updates["L1"]["changes"]["rule_id"] == "compliance.gate_not_approved.security"
    assert updates["L2"]["changes"]["rule_id"] == "operational.trace_error_rate"
    assert updates["L2"]["changes"]["title"].startswith("3 error span(s)")
    [dup] = plan["closes"]
    assert dup["id"] == "L3"
    assert dup["changes"]["history"][-1]["action"] == "auto-resolved: duplicate of another finding"
    assert plan["counts"]["backfilled"] == 2


def test_legacy_row_for_an_unevaluated_rule_is_backfilled_but_kept_open():
    legacy = _row("L2", None, category="OPERATIONAL", title="2 error span(s) across 500 sampled spans (0.4%)")
    plan = lc.reconcile([legacy], [], NOW, unevaluated=["operational.trace_error_rate"])
    assert plan["closes"] == []
    changes = _by_id(plan["updates"])["L2"]["changes"]
    assert changes == {"rule_id": "operational.trace_error_rate", "history": changes["history"]}


def test_rerun_is_idempotent_on_rule_ids():
    first = lc.reconcile([], [_detected("a.b"), _detected("c.d")], NOW)
    rows = [{**item, "id": f"id{i}"} for i, item in enumerate(first["inserts"])]
    second = lc.reconcile(rows, [_detected("a.b"), _detected("c.d")], NOW + timedelta(hours=1))
    assert second["inserts"] == [] and second["closes"] == []
    assert len(second["updates"]) == 2


# ── person actions ───────────────────────────────────────────────────────────

def _act(row, **payload):
    return lc.apply_action(row, payload, "alice@example.com", NOW)


def test_acknowledge_then_mitigate_then_resolve():
    row = _row("r1", "a.b")
    ack = _act(row, action="acknowledge", note="looking")
    assert ack["changes"]["status"] == "acknowledged"
    assert ack["changes"]["history"][-1] == {"at": NOW.isoformat(), "by": "alice@example.com",
                                             "action": "acknowledged", "note": "looking"}
    row = {**row, **ack["changes"]}
    mit = _act(row, action="mitigate", mitigation="Add guardrail", note="ticket SEC-1")
    assert mit["changes"]["status"] == "mitigating"
    assert mit["changes"]["mitigation"] == "Add guardrail"
    row = {**row, **mit["changes"]}
    res = _act(row, action="resolve")
    assert res["changes"]["status"] == "resolved"
    assert res["changes"]["resolved_at"] == NOW


@pytest.mark.parametrize("status,action", [
    ("acknowledged", "acknowledge"), ("mitigating", "acknowledge"), ("resolved", "resolve"),
    ("accepted", "mitigate"), ("resolved", "accept"), ("open", "reopen"), ("mitigating", "reopen"),
])
def test_invalid_transitions_are_rejected(status, action):
    with pytest.raises(lc.RiskValidationError):
        _act(_row("r1", "a.b", status=status), action=action, acceptedUntil=(TODAY + timedelta(days=5)).isoformat())


def test_accept_requires_a_date_within_a_year():
    row = _row("r1", "a.b", status="acknowledged")
    with pytest.raises(lc.RiskValidationError, match="required"):
        _act(row, action="accept")
    with pytest.raises(lc.RiskValidationError, match="within 365"):
        _act(row, action="accept", acceptedUntil=(TODAY + timedelta(days=366)).isoformat())
    with pytest.raises(lc.RiskValidationError, match="past"):
        _act(row, action="accept", acceptedUntil=(TODAY - timedelta(days=1)).isoformat())
    with pytest.raises(lc.RiskValidationError, match="accepted_by"):
        lc.apply_action(row, {"action": "accept", "acceptedUntil": TODAY.isoformat()}, "", NOW)
    ok = _act(row, action="accept", acceptedUntil=(TODAY + timedelta(days=365)).isoformat(), note="low impact")
    assert ok["changes"]["status"] == "accepted"
    assert ok["changes"]["accepted_by"] == "alice@example.com"
    assert ok["changes"]["accepted_until"] == TODAY + timedelta(days=365)
    assert ok["changes"]["history"][-1]["note"].startswith("Accepted until")


@pytest.mark.parametrize("status", ["resolved", "accepted"])
def test_reopen_clears_resolution_and_acceptance(status):
    row = _row("r1", "a.b", status=status, accepted_until=TODAY, accepted_by="bob", resolved_at=NOW)
    changes = _act(row, action="reopen", note="regressed")["changes"]
    assert changes["status"] == "open"
    assert changes["resolved_at"] is None and changes["accepted_until"] is None and changes["accepted_by"] is None


def test_update_owner_and_due_date_records_history():
    row = _row("r1", "a.b", owner=None, due_date=None)
    changes = _act(row, action="update", owner="Bob", dueDate="2026-10-01")["changes"]
    assert changes["owner"] == "Bob"
    assert changes["due_date"] == date(2026, 10, 1)
    assert "owner: — -> Bob" in changes["history"][-1]["note"]


def test_update_with_nothing_changed_is_rejected():
    with pytest.raises(lc.RiskValidationError, match="Nothing to update"):
        _act(_row("r1", "a.b", owner="Bob"), action="update", owner="Bob")


def test_bad_date_and_unknown_action_are_rejected():
    with pytest.raises(lc.RiskValidationError, match="Invalid date"):
        _act(_row("r1"), action="update", dueDate="next week")
    with pytest.raises(lc.RiskValidationError, match="Unknown action"):
        _act(_row("r1"), action="delete")


def test_new_manual_risk_validates_fixed_categories_and_severities():
    item = lc.new_manual_risk({"category": "reputational", "severity": "high", "title": " Brand misuse ",
                               "owner": "Comms", "dueDate": "2026-12-01"}, "alice", NOW)
    assert (item["category"], item["severity"], item["title"]) == ("REPUTATIONAL", "HIGH", "Brand misuse")
    assert item["source"] == "manual" and item["status"] == "open" and item["rule_id"] is None
    assert item["due_date"] == date(2026, 12, 1)
    for bad in ({"category": "OTHER", "severity": "LOW", "title": "x"},
                {"category": "SECURITY", "severity": "SEVERE", "title": "x"},
                {"category": "SECURITY", "severity": "LOW", "title": "  "}):
        with pytest.raises(lc.RiskValidationError):
            lc.new_manual_risk(bad, "alice", NOW)


def test_overdue_only_for_open_states():
    past = TODAY - timedelta(days=1)
    assert lc.is_overdue(_row("r", status="acknowledged", due_date=past), TODAY)
    assert not lc.is_overdue(_row("r", status="accepted", due_date=past), TODAY)
    assert not lc.is_overdue(_row("r", status="open", due_date=TODAY), TODAY)
    assert not lc.is_overdue(_row("r", status="open"), TODAY)


def test_score_and_portfolio_summary():
    findings = [
        {"category": "SECURITY", "severity": "HIGH"}, {"category": "COMPLIANCE", "severity": "MEDIUM"},
        {"category": "COMPLIANCE", "severity": "MEDIUM"}, {"category": "NOPE", "severity": "LOW"},
    ]
    score = lc.score(findings)
    assert score["worst"] == "HIGH"
    assert score["total"] == 3
    assert score["countsBySeverity"] == {"LOW": 0, "MEDIUM": 2, "HIGH": 1, "CRITICAL": 0}
    assert score["countsByCategory"]["COMPLIANCE"] == 2
    assert lc.score([])["worst"] is None
    summary = lc.portfolio_summary(findings)
    assert summary["totalFindings"] == 3
    assert {c["category"]: c["count"] for c in summary["byCategory"]}["COMPLIANCE"] == 2
    assert summary["severities"] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert {r["category"]: r["counts"] for r in summary["heatmap"]}["SECURITY"]["HIGH"] == 1


# ── risk scan + router against a temp DB ─────────────────────────────────────

AGENT = "prod-agent"
LEGACY = [
    ("L1", "COMPLIANCE", "MEDIUM", "Architecture Review not approved"),
    ("L2", "COMPLIANCE", "MEDIUM", "Security Review not approved"),
    ("L3", "COMPLIANCE", "MEDIUM", "Data Protection Review not approved"),
    ("L4", "SECURITY", "HIGH", "Production agent without an approved security review"),
    ("L5", "OPERATIONAL", "LOW", "2 error span(s) across 500 sampled spans (0.4%)"),
]


@pytest_asyncio.fixture
async def db():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentRisk, GovernanceReview, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(User(id="u1", org_id="org-default", email="alice@example.com", name="Alice", password_hash="x"))
            s.add(Agent(id=AGENT, org_id="org-default", name="Prod Agent", slug="prod-agent", owner="Ops",
                        lifecycle_stage="Production", api_endpoint="https://agent.example.com/run"))
            for gate in ("arb", "security", "dp"):
                s.add(GovernanceReview(id=f"g-{gate}", agent_id=AGENT, gate=gate, status="Not Submitted"))
            for rid, category, severity, title in LEGACY:
                s.add(AgentRisk(id=rid, agent_id=AGENT, category=category, severity=severity, title=title,
                                source="auto", status="open"))
            s.add(AgentRisk(id="M1", agent_id=AGENT, category="REPUTATIONAL", severity="LOW",
                            title="Vendor lock-in", source="manual", status="open", history=[]))
        yield get_db_session
    finally:
        await engine.dispose()


async def _risks(get_db_session):
    from db.models import AgentRisk

    async with get_db_session() as s:
        return {r.id: r for r in (await s.execute(select(AgentRisk).where(AgentRisk.agent_id == AGENT))).scalars()}


@pytest.mark.asyncio
async def test_scan_backfills_legacy_rows_and_never_touches_manual_ones(db):
    from orchestrations.risk_scan import scan_risks

    first = await scan_risks(AGENT, actor="u1")
    assert first["status"] == "ok"
    assert first["traceSignals"] == "not_linked"
    assert first["reconcile"]["backfilled"] == 5
    rows = await _risks(db)
    auto = [r for r in rows.values() if r.source == "auto"]
    assert len({r.rule_id for r in auto}) == len(auto)
    assert {rid: rows[rid].rule_id for rid, *_ in LEGACY} == {
        "L1": "compliance.gate_not_approved.arb", "L2": "compliance.gate_not_approved.security",
        "L3": "compliance.gate_not_approved.dp", "L4": "security.prod_without_security_approval",
        "L5": "operational.trace_error_rate",
    }
    # No Phoenix link: the trace rule was not checked, so its legacy row stays open.
    assert rows["L5"].status == "open"
    assert rows[next(r.id for r in auto if r.rule_id == "compliance.no_observability")].status == "open"

    manual_before = (rows["M1"].status, rows["M1"].history, rows["M1"].detected_at)
    for _ in range(3):
        again = await scan_risks(AGENT)
        assert again["reconcile"]["inserted"] == 0 and again["reconcile"]["resolved"] == 0
    rows = await _risks(db)
    assert (rows["M1"].status, rows["M1"].history, rows["M1"].detected_at) == manual_before
    assert len(rows) == 7


@pytest.mark.asyncio
async def test_scan_reopens_resolved_true_rule_and_resolves_cleared_one(db):
    from db.models import GovernanceReview
    from orchestrations.risk_scan import scan_risks

    await scan_risks(AGENT)
    async with db() as s:
        (await s.get(__import__("db.models", fromlist=["AgentRisk"]).AgentRisk, "L4")).status = "resolved"
        (await s.get(GovernanceReview, "g-arb")).status = "Approved"
    result = await scan_risks(AGENT)
    assert result["reconcile"]["reopened"] == 1
    assert result["reconcile"]["resolved"] == 1
    rows = await _risks(db)
    assert rows["L4"].status == "open"
    assert rows["L4"].history[-1]["action"] == "reopened"
    assert rows["L1"].status == "resolved"
    assert rows["L1"].history[-1]["action"] == "auto-resolved: condition cleared"


@pytest_asyncio.fixture
async def client(db):
    from api.auth import require_read, require_update
    from api.routers.ops.risk import router

    app = FastAPI()
    app.include_router(router)
    for dep in (require_read, require_update):
        app.dependency_overrides[dep] = lambda: {"user_id": "u1", "role": "admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_router_scan_list_act_and_summary(client, db):
    base = f"/api/v1/agents/{AGENT}/risks"
    scan = (await client.post(f"{base}/scan")).json()
    assert scan["status"] == "scanned"
    assert scan["findingCount"] == len(scan["findings"]) == 5
    assert scan["reconcile"]["backfilled"] == 5
    assert scan["traceSignals"] == "not_linked"

    listing = (await client.get(base)).json()
    assert listing["lastScan"]["status"] == "ok"
    assert listing["lastScan"]["traceSignals"] == "not_linked"
    assert listing["phoenixLinked"] is False
    assert listing["score"]["worst"] == "HIGH"
    by_rule = {f["ruleId"]: f for f in listing["findings"] if f["ruleId"]}
    manual = next(f for f in listing["findings"] if f["source"] == "manual")
    assert {"id", "ruleId", "category", "severity", "title", "description", "source", "status", "owner",
            "mitigation", "dueDate", "acceptedUntil", "acceptedBy", "detectedAt", "lastDetectedAt",
            "resolvedAt", "history", "overdue"} <= set(manual)

    gate = by_rule["compliance.gate_not_approved.arb"]["id"]
    r = await client.patch(f"{base}/{gate}", json={"action": "acknowledge", "owner": "Bob", "dueDate": "2020-01-01"})
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"
    assert r.json()["overdue"] is True
    assert r.json()["history"][-1]["by"] == "alice@example.com"

    sec = by_rule["compliance.gate_not_approved.security"]["id"]
    too_far = (datetime.now(timezone.utc).date() + timedelta(days=400)).isoformat()
    assert (await client.patch(f"{base}/{sec}", json={"action": "accept", "acceptedUntil": too_far})).status_code == 422
    until = (datetime.now(timezone.utc).date() + timedelta(days=90)).isoformat()
    accepted = (await client.patch(f"{base}/{sec}", json={"action": "accept", "acceptedUntil": until})).json()
    assert (accepted["status"], accepted["acceptedUntil"], accepted["acceptedBy"]) == ("accepted", until, "alice@example.com")

    prod = by_rule["security.prod_without_security_approval"]["id"]
    assert (await client.patch(f"{base}/{prod}", json={"action": "resolve", "note": "fixed"})).json()["status"] == "resolved"
    assert prod not in {f["id"] for f in (await client.get(base)).json()["findings"]}
    assert prod in {f["id"] for f in (await client.get(base, params={"status": "all"})).json()["findings"]}

    rescan = (await client.post(f"{base}/scan")).json()
    assert rescan["reconcile"]["reopened"] == 1
    reopened = next(f for f in (await client.get(base)).json()["findings"] if f["id"] == prod)
    assert reopened["status"] == "open"

    created = await client.post(base, json={"category": "SECURITY", "severity": "CRITICAL", "title": "Shared admin key",
                                            "owner": "SecOps", "dueDate": "2026-12-31"})
    assert created.status_code == 201
    assert created.json()["source"] == "manual"
    assert (await client.post(base, json={"category": "OTHER", "severity": "LOW", "title": "x"})).status_code == 422
    assert (await client.patch(f"{base}/nope", json={"action": "acknowledge"})).status_code == 404
    assert (await client.get("/api/v1/agents/missing/risks")).status_code == 404

    summary = (await client.get("/api/v1/governance/risks/summary")).json()
    listing = (await client.get(base)).json()
    assert summary["totalFindings"] == listing["score"]["total"]
    assert set(summary) == {"totalFindings", "byCategory", "severities", "heatmap"}

    from db.models import AuditLog
    async with db() as s:
        actions = {a.action for a in (await s.execute(select(AuditLog))).scalars()}
    assert {"risk_scan", "risk.acknowledge", "risk.accept", "risk.resolve", "risk.create"} <= actions


@pytest.mark.asyncio
async def test_expired_acceptance_reopens_on_read(client, db):
    from db.models import AgentRisk

    async with db() as s:
        row = await s.get(AgentRisk, "M1")
        row.status, row.accepted_until, row.accepted_by = "accepted", date(2020, 1, 1), "bob"
    listing = (await client.get(f"/api/v1/agents/{AGENT}/risks")).json()
    m1 = next(f for f in listing["findings"] if f["id"] == "M1")
    assert m1["status"] == "open"
    assert m1["history"][-1]["action"] == "acceptance expired"


@pytest_asyncio.fixture
async def both_tabs(db):
    """Overview and Risk routers on one app, so their answers can be compared."""
    from api.auth import require_read, require_update
    from api.routers.ops.overview import router as overview_router
    from api.routers.ops.risk import router as risk_router

    app = FastAPI()
    app.include_router(risk_router)
    app.include_router(overview_router)
    for dep in (require_read, require_update):
        app.dependency_overrides[dep] = lambda: {"user_id": "u1", "role": "admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_overview_header_and_risk_tab_report_the_same_totals(both_tabs, db):
    """FINANCIAL findings are read live from waste_findings/cost_anomalies and
    deliberately never stored in agent_risks. The Overview header used to count
    that table alone, so it silently dropped them and the two tabs disagreed
    about one agent in the same breath (7 in the header, 8 on the Risk tab).
    """
    from db.models import WasteFinding

    async with db() as s:
        s.add(WasteFinding(id="W1", agent_id=AGENT, waste_type="idle_agent", severity="MEDIUM",
                           monthly_waste_cents=5000, recommendation="Retire or consolidate", status="open"))

    risk = (await both_tabs.get(f"/api/v1/agents/{AGENT}/risks")).json()
    header = (await both_tabs.get(f"/api/v1/agents/{AGENT}/overview")).json()["header"]["riskScore"]

    # The waste finding must actually reach the Risk tab, or this proves nothing.
    assert risk["score"]["countsByCategory"]["FINANCIAL"] >= 1
    assert any(f["category"] == "FINANCIAL" for f in risk["financial"])

    assert header["total"] == risk["score"]["total"]
    assert header["worst"] == risk["score"]["worst"]
    assert header["openCounts"] == risk["score"]["countsBySeverity"]
