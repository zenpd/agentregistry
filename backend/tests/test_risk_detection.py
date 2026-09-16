"""Unit tests for governance/risk_detection.py — pure functions, no DB."""
from __future__ import annotations

from governance.risk_detection import detect_risks


def _agent(**overrides):
    base = {
        "stage": "Ideation", "riskLevel": "LOW", "atRisk": False, "apiEndpoint": "https://x",
        "databases": [], "enterpriseSystems": [],
        "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"},
    }
    base.update(overrides)
    return base


def test_fully_approved_low_risk_agent_has_no_findings():
    assert detect_risks(_agent()) == []


def test_unapproved_gate_produces_compliance_finding():
    findings = detect_risks(_agent(reviews={"arb": "In Review", "security": "Approved", "dp": "Approved"}))
    assert len(findings) == 1
    assert findings[0]["category"] == "COMPLIANCE"
    assert findings[0]["severity"] == "MEDIUM"


def test_changes_requested_gate_is_high_severity():
    findings = detect_risks(_agent(reviews={"arb": "Approved", "security": "Changes Requested", "dp": "Approved"}))
    assert findings[0]["severity"] == "HIGH"


def test_production_without_security_approval_is_security_finding():
    findings = detect_risks(_agent(stage="Production", reviews={"arb": "Approved", "security": "Not Submitted", "dp": "Approved"}))
    categories = [f["category"] for f in findings]
    assert "SECURITY" in categories
    assert "COMPLIANCE" in categories  # the same unapproved gate also trips compliance


def test_databases_without_dp_approval_is_data_privacy_finding():
    findings = detect_risks(_agent(databases=["Snowflake"], reviews={"arb": "Approved", "security": "Approved", "dp": "In Review"}))
    categories = [f["category"] for f in findings]
    assert "DATA_PRIVACY" in categories


def test_no_databases_and_no_dp_approval_is_not_a_finding():
    """A DP-gate-not-approved agent that touches nothing shouldn't be flagged
    for data privacy — there's nothing to protect if it never named a system."""
    findings = detect_risks(_agent(databases=[], enterpriseSystems=[], reviews={"arb": "Approved", "security": "Approved", "dp": "Not Submitted"}))
    categories = [f["category"] for f in findings]
    assert "DATA_PRIVACY" not in categories


def test_at_risk_in_production_is_reputational_finding():
    findings = detect_risks(_agent(stage="Production", atRisk=True, riskNote="customer complaints"))
    categories = [f["category"] for f in findings]
    assert "REPUTATIONAL" in categories


def test_at_risk_outside_production_is_not_reputational():
    findings = detect_risks(_agent(stage="Development", atRisk=True))
    categories = [f["category"] for f in findings]
    assert "REPUTATIONAL" not in categories


def test_no_graph_means_no_operational_findings():
    assert detect_risks(_agent(), graph=None) == []


def test_graph_not_ok_status_means_no_operational_findings():
    graph = {"status": "not_linked", "nodes": []}
    assert detect_risks(_agent(), graph=graph) == []


def test_graph_with_low_error_rate_is_medium_severity():
    graph = {
        "status": "ok",
        # total=200, errors=6 -> 3% (above the 2% floor, below the 10% ceiling)
        "nodes": [
            {"name": "classify", "count": 100, "errorCount": 6},
            {"name": "extract", "count": 100, "errorCount": 0},
        ],
    }
    findings = detect_risks(_agent(), graph=graph)
    op = [f for f in findings if f["category"] == "OPERATIONAL"]
    assert len(op) == 1
    assert op[0]["severity"] == "MEDIUM"


def test_graph_with_high_error_rate_is_high_severity():
    graph = {
        "status": "ok",
        "nodes": [
            {"name": "classify", "count": 50, "errorCount": 20},  # 20/100 = 20%
            {"name": "extract", "count": 50, "errorCount": 0},
        ],
    }
    findings = detect_risks(_agent(), graph=graph)
    op = [f for f in findings if f["category"] == "OPERATIONAL"]
    assert len(op) == 1
    assert op[0]["severity"] == "HIGH"
    assert "classify" in op[0]["description"]
