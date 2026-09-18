"""Unit tests for governance/risk_detection.py — pure functions, no DB."""
from __future__ import annotations

import pytest

from governance.risk_detection import (
    detect_risks, financial_findings, legacy_rule_id, parse_sla_ms, partition_findings, unevaluated_rules,
)


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


# ── rule ids, trace KRIs and the extra inputs ────────────────────────────────

_UNAPPROVED = {"arb": "Not Submitted", "security": "Not Submitted", "dp": "Not Submitted"}


def _kri(**overrides):
    base = {"span_count": 500, "trace_count": 120, "error_spans": 0, "error_rate": 0.0,
            "pii_spans": 0, "pii_traces": 0, "injection_spans": 0, "injection_traces": 0,
            "p95_latency_ms": None, "llm_calls": 40}
    base.update(overrides)
    return base


def _by_rule(findings):
    return {f["rule_id"]: f for f in findings}


def test_every_finding_has_a_unique_stable_rule_id():
    agent = _agent(stage="Production", riskLevel="HIGH", apiEndpoint="", atRisk=True,
                   databases=["Snowflake"], reviews=_UNAPPROVED)
    findings = detect_risks(agent, kri=_kri(error_spans=5, pii_spans=1, injection_spans=1, p95_latency_ms=900),
                            sla_p95_ms=500, blast_radius_count=6,
                            dependency_drift={"declared_only": [], "observed_only": [{"kind": "tool", "name": "x"}]},
                            gate_states={"arb": "expired"}, trace_status="ok")
    rule_ids = [f["rule_id"] for f in findings]
    assert all(rule_ids)
    assert len(rule_ids) == len(set(rule_ids))
    assert rule_ids == [f["rule_id"] for f in detect_risks(
        agent, kri=_kri(error_spans=5, pii_spans=1, injection_spans=1, p95_latency_ms=900),
        sla_p95_ms=500, blast_radius_count=6,
        dependency_drift={"declared_only": [], "observed_only": [{"kind": "tool", "name": "x"}]},
        gate_states={"arb": "expired"}, trace_status="ok")]


def test_digital_onboarding_shape_gives_the_five_known_findings():
    agent = _agent(stage="Production", reviews=_UNAPPROVED)
    findings = _by_rule(detect_risks(agent, kri=_kri(span_count=500, error_spans=2), trace_status="ok"))
    assert set(findings) == {
        "compliance.gate_not_approved.arb", "compliance.gate_not_approved.security",
        "compliance.gate_not_approved.dp", "security.prod_without_security_approval",
        "operational.trace_error_rate",
    }
    assert findings["operational.trace_error_rate"]["severity"] == "LOW"
    assert findings["operational.trace_error_rate"]["title"] == "2 error span(s) across 500 sampled spans (0.4%)"


@pytest.mark.parametrize("errors,severity", [(1, "LOW"), (20, "LOW"), (21, "MEDIUM"), (100, "MEDIUM"), (101, "HIGH")])
def test_error_rate_thresholds_from_kri(errors, severity):
    findings = _by_rule(detect_risks(_agent(), kri=_kri(span_count=1000, error_spans=errors)))
    assert findings["operational.trace_error_rate"]["severity"] == severity


def test_no_errors_means_no_error_rate_finding():
    assert detect_risks(_agent(), kri=_kri(error_spans=0)) == []


def test_small_trace_sample_is_called_out():
    findings = _by_rule(detect_risks(_agent(), kri=_kri(trace_count=10, error_spans=3)))
    assert "Small sample" in findings["operational.trace_error_rate"]["description"]


def test_kri_takes_precedence_over_graph():
    graph = {"status": "ok", "nodes": [{"name": "a", "count": 10, "errorCount": 5}]}
    assert detect_risks(_agent(), graph=graph, kri=_kri(error_spans=0)) == []


@pytest.mark.parametrize("stage,severity", [("Production", "HIGH"), ("Testing", "MEDIUM")])
def test_pii_in_traces_is_data_privacy(stage, severity):
    findings = _by_rule(detect_risks(_agent(stage=stage), kri=_kri(pii_spans=2, pii_traces=1)))
    finding = findings["data_privacy.pii_detected"]
    assert finding["category"] == "DATA_PRIVACY"
    assert finding["severity"] == severity


def test_prompt_injection_is_high_security():
    finding = _by_rule(detect_risks(_agent(), kri=_kri(injection_spans=1, injection_traces=1)))[
        "security.prompt_injection_detected"]
    assert (finding["category"], finding["severity"]) == ("SECURITY", "HIGH")


@pytest.mark.parametrize("sla,expected", [
    ("p95 < 800ms", 800.0), ("1,500 ms p95", 1500.0), ("250.5 MS", 250.5),
    ("99.5% uptime", None), ("2s", None), (None, None), ("", None), ("500 msec", None),
])
def test_parse_sla_ms(sla, expected):
    assert parse_sla_ms(sla) == expected


def test_latency_above_sla_is_operational_medium():
    agent = _agent(sla="p95 under 800ms")
    assert "operational.latency_above_sla" not in _by_rule(detect_risks(agent, kri=_kri(p95_latency_ms=800)))
    finding = _by_rule(detect_risks(agent, kri=_kri(p95_latency_ms=801)))["operational.latency_above_sla"]
    assert (finding["category"], finding["severity"]) == ("OPERATIONAL", "MEDIUM")


def test_latency_rule_needs_an_ms_sla():
    assert detect_risks(_agent(sla="99.9% uptime"), kri=_kri(p95_latency_ms=99999)) == []


def test_explicit_sla_overrides_text():
    findings = _by_rule(detect_risks(_agent(sla="5000ms"), kri=_kri(p95_latency_ms=900), sla_p95_ms=500))
    assert "operational.latency_above_sla" in findings


@pytest.mark.parametrize("count,fires", [(None, False), (4, False), (5, True), (12, True)])
def test_blast_radius_threshold(count, fires):
    findings = _by_rule(detect_risks(_agent(), blast_radius_count=count))
    assert ("operational.wide_blast_radius" in findings) is fires
    if fires:
        assert findings["operational.wide_blast_radius"]["severity"] == "MEDIUM"


def test_undeclared_dependencies_observed_is_operational_low():
    drift = {"declared_only": [{"name": "Snowflake"}], "observed_only": [{"kind": "tool", "name": "kyc_lookup"}]}
    finding = _by_rule(detect_risks(_agent(), dependency_drift=drift))["operational.undeclared_dependencies"]
    assert (finding["category"], finding["severity"]) == ("OPERATIONAL", "LOW")
    assert "kyc_lookup" in finding["description"]
    assert detect_risks(_agent(), dependency_drift={"declared_only": [{"name": "x"}], "observed_only": []}) == []


def test_gate_expiry_states():
    findings = _by_rule(detect_risks(_agent(), gate_states={
        "arb": "expired", "security": {"state": "expiring", "daysLeft": 12}, "dp": "valid",
    }))
    assert findings["compliance.gate_approval_expired.arb"]["severity"] == "HIGH"
    expiring = findings["compliance.gate_approval_expiring.security"]
    assert expiring["severity"] == "LOW"
    assert "12 day" in expiring["description"]
    assert not any(r.endswith(".dp") for r in findings)


def test_expiring_more_than_30_days_out_is_not_a_finding():
    assert detect_risks(_agent(), gate_states={"arb": {"state": "expiring", "daysLeft": 31}}) == []


def test_production_without_observability():
    prod = _agent(stage="Production")
    assert "compliance.no_observability" in _by_rule(detect_risks(prod, trace_status="not_linked"))
    assert "compliance.no_observability" in _by_rule(detect_risks(prod, trace_status="no_traces"))
    assert detect_risks(prod, trace_status="unavailable") == []
    assert detect_risks(prod, trace_status="ok") == []
    assert detect_risks(_agent(stage="Testing"), trace_status="not_linked") == []


def test_api_endpoint_pointing_at_phoenix_is_flagged():
    agent = _agent(apiEndpoint="https://phoenix.example.com/", riskLevel="HIGH")
    findings = _by_rule(detect_risks(agent, phoenix_base_url="https://PHOENIX.example.com"))
    assert findings["compliance.api_endpoint_is_phoenix"]["severity"] == "LOW"
    assert "security.high_risk_without_endpoint" in findings
    assert detect_risks(_agent(apiEndpoint="https://agent.example.com"), phoenix_base_url="https://phoenix.example.com") == []


def test_financial_findings_are_returned_but_partitioned_off():
    findings = detect_risks(
        _agent(),
        cost_anomalies=[{"id": "a1", "anomaly_type": "spend_spike", "severity": "HIGH",
                         "details": {"source": "seed", "impact_cents": 900}}],
        financial_flags=[{"code": "negative_net", "severity": "medium", "title": "Costs exceed value"}],
    )
    stored, financial = partition_findings(findings)
    assert stored == []
    by_rule = _by_rule(financial)
    anomaly = by_rule["financial.cost_anomaly.spend_spike"]
    assert anomaly["title"] == "Cost anomaly: spend spike"
    assert anomaly["data_source"] == "seed"
    assert anomaly["source_id"] == "a1"
    assert "source" not in (anomaly["description"] or "")
    assert by_rule["financial.flag.negative_net"]["severity"] == "MEDIUM"


def test_financial_findings_from_waste_rows():
    [finding] = financial_findings(waste_findings=[
        {"id": "w1", "waste_type": "idle_agent", "severity": "BOGUS", "recommendation": "Retire it"},
    ])
    assert finding["rule_id"] == "financial.waste.idle_agent"
    assert finding["severity"] == "MEDIUM"
    assert finding["description"] == "Retire it"


@pytest.mark.parametrize("category,title,rule_id", [
    ("COMPLIANCE", "Security Review not approved", "compliance.gate_not_approved.security"),
    ("SECURITY", "Production agent without an approved security review", "security.prod_without_security_approval"),
    ("OPERATIONAL", "2 error span(s) across 500 sampled spans (0.4%)", "operational.trace_error_rate"),
    ("OPERATIONAL", "Something else", None),
])
def test_legacy_rule_id(category, title, rule_id):
    assert legacy_rule_id(category, title) == rule_id


def test_unevaluated_rules_names_rules_whose_input_was_missing():
    everything = unevaluated_rules(kri=None, trace_status=None, blast_radius_count=None,
                                   dependency_drift=None, gate_states=None)
    assert "operational.trace_error_rate" in everything
    assert "compliance.no_observability" in everything
    assert "operational.wide_blast_radius" in everything
    assert "operational.undeclared_dependencies" in everything
    assert "compliance.gate_approval_expired" in everything
    nothing = unevaluated_rules(kri=_kri(), trace_status="ok", blast_radius_count=0,
                                dependency_drift={"observed_only": []}, gate_states={})
    assert nothing == []
    unlinked = unevaluated_rules(kri=None, trace_status="not_linked", blast_radius_count=0,
                                 dependency_drift=None, gate_states={})
    assert "compliance.no_observability" not in unlinked
    assert "data_privacy.pii_detected" in unlinked
