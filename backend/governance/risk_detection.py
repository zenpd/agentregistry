"""Auto-detects risk findings from signals the registry can prove: governance
gate state, Phoenix trace KRIs (governance/trace_kri.py), the dependency
graph and the agent's declared fields. Heuristic, not a certification: every
finding carries a stable `rule_id` naming the exact rule that produced it,
so a re-scan can match it to the stored row. Pure functions, no I/O.

FINANCIAL findings are returned too but are never stored in agent_risks;
`partition_findings` splits them off so callers merge them live.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from governance.risk_categories import SEVERITY_ORDER, RiskCategory

SECURITY = RiskCategory.SECURITY.value
DATA_PRIVACY = RiskCategory.DATA_PRIVACY.value
OPERATIONAL = RiskCategory.OPERATIONAL.value
FINANCIAL = RiskCategory.FINANCIAL.value
COMPLIANCE = RiskCategory.COMPLIANCE.value
REPUTATIONAL = RiskCategory.REPUTATIONAL.value

# "Changes Requested" is an active rejection, so it outranks not-yet-reviewed.
_GATE_STATUS_SEVERITY: dict[str, str] = {
    "Not Submitted": "MEDIUM",
    "In Review": "MEDIUM",
    "Approved with Conditions": "LOW",
    "Changes Requested": "HIGH",
}

_GATE_LABELS = {"arb": "Architecture Review", "security": "Security Review", "dp": "Data Protection Review"}

ERROR_RATE_HIGH = 0.10
ERROR_RATE_MEDIUM = 0.02
BLAST_RADIUS_THRESHOLD = 5
GATE_EXPIRY_WARNING_DAYS = 30
# Below this many traces an error rate swings on a handful of spans; the
# finding still fires but says so (research: practitioner convention).
MIN_TRACES_FOR_STABLE_RATE = 50

_TITLE_PROD_NO_SECURITY = "Production agent without an approved security review"
_TITLE_HIGH_RISK_NO_ENDPOINT = "High risk level with no registered API endpoint"
_TITLE_DATA_NO_DP = "Touches real systems/data without an approved DP review"
_TITLE_AT_RISK = "Flagged at-risk while live in Production"

_LEGACY_TITLES: dict[tuple[str, str], str] = {
    **{(COMPLIANCE, f"{label} not approved"): f"compliance.gate_not_approved.{gate}" for gate, label in _GATE_LABELS.items()},
    (SECURITY, _TITLE_PROD_NO_SECURITY): "security.prod_without_security_approval",
    (SECURITY, _TITLE_HIGH_RISK_NO_ENDPOINT): "security.high_risk_without_endpoint",
    (DATA_PRIVACY, _TITLE_DATA_NO_DP): "data_privacy.data_access_without_dp_approval",
    (REPUTATIONAL, _TITLE_AT_RISK): "reputational.at_risk_in_production",
}
_LEGACY_ERROR_RATE_TITLE = re.compile(r"^\d+ error span\(s\) across \d+ sampled spans")
_SLA_MS = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*ms\b", re.IGNORECASE)

# Rules whose verdict depends on one input; when that input is missing the
# rule was not checked, so a stored finding from it must not be auto-closed.
TRACE_RULES = (
    "operational.trace_error_rate",
    "data_privacy.pii_detected",
    "security.prompt_injection_detected",
    "operational.latency_above_sla",
)
OBSERVABILITY_RULE = "compliance.no_observability"
BLAST_RADIUS_RULE = "operational.wide_blast_radius"
DRIFT_RULE = "operational.undeclared_dependencies"
GATE_EXPIRY_RULES = ("compliance.gate_approval_expired", "compliance.gate_approval_expiring")


def legacy_rule_id(category: str, title: str) -> str | None:
    """rule_id for a row stored before findings carried one."""
    rule_id = _LEGACY_TITLES.get((category, title))
    if rule_id:
        return rule_id
    if category == OPERATIONAL and _LEGACY_ERROR_RATE_TITLE.match(title or ""):
        return "operational.trace_error_rate"
    return None


def parse_sla_ms(sla: str | None) -> float | None:
    match = _SLA_MS.search(sla or "")
    return float(match.group(1).replace(",", "")) if match else None


def unevaluated_rules(
    *,
    kri: dict[str, Any] | None,
    trace_status: str | None,
    blast_radius_count: int | None,
    dependency_drift: dict[str, Any] | None,
    gate_states: dict[str, Any] | None,
) -> list[str]:
    """Rule ids (or rule_id prefixes) the given inputs could not check."""
    skipped: list[str] = []
    if kri is None:
        skipped += TRACE_RULES
    if trace_status in (None, "unavailable"):
        skipped.append(OBSERVABILITY_RULE)
    if blast_radius_count is None:
        skipped.append(BLAST_RADIUS_RULE)
    if dependency_drift is None:
        skipped.append(DRIFT_RULE)
    if gate_states is None:
        skipped += GATE_EXPIRY_RULES
    return skipped


def _finding(rule_id: str, category: str, severity: str, title: str, description: str | None) -> dict[str, Any]:
    return {"rule_id": rule_id, "category": category, "severity": severity, "title": title, "description": description}


def _norm_severity(value: Any) -> str:
    severity = str(value or "").upper()
    return severity if severity in SEVERITY_ORDER else "MEDIUM"


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "unknown").lower()).strip("_") or "unknown"


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return (urlparse(url if "://" in url else f"//{url}").hostname or "").lower() or None


def _compliance_findings(reviews: dict[str, str]) -> list[dict[str, Any]]:
    findings = []
    for gate, label in _GATE_LABELS.items():
        status = reviews.get(gate, "Not Submitted")
        if status == "Approved":
            continue
        findings.append(_finding(
            f"compliance.gate_not_approved.{gate}", COMPLIANCE, _GATE_STATUS_SEVERITY.get(status, "MEDIUM"),
            f"{label} not approved", f"Gate '{gate}' is currently '{status}'.",
        ))
    return findings


def _gate_state(value: Any) -> tuple[str, int | None]:
    if isinstance(value, dict):
        state = value.get("state") or value.get("status") or ""
        days = value.get("daysLeft", value.get("days_left", value.get("daysRemaining", value.get("days_remaining"))))
        return str(state).lower(), days if isinstance(days, (int, float)) else None
    return str(value or "").lower(), None


def _gate_expiry_findings(gate_states: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = []
    for gate, value in (gate_states or {}).items():
        label = _GATE_LABELS.get(gate, gate)
        state, days_left = _gate_state(value)
        if state == "expired":
            findings.append(_finding(
                f"compliance.gate_approval_expired.{gate}", COMPLIANCE, "HIGH",
                f"{label} approval expired",
                f"The '{gate}' approval is past its validity date; the gate needs re-review.",
            ))
        elif state in ("expiring", "expiring_soon") and (days_left is None or days_left <= GATE_EXPIRY_WARNING_DAYS):
            when = f"in {int(days_left)} day(s)" if days_left is not None else f"within {GATE_EXPIRY_WARNING_DAYS} days"
            findings.append(_finding(
                f"compliance.gate_approval_expiring.{gate}", COMPLIANCE, "LOW",
                f"{label} approval expires soon",
                f"The '{gate}' approval expires {when}; schedule the re-review.",
            ))
    return findings


def _security_findings(agent: dict[str, Any], endpoint_is_phoenix: bool) -> list[dict[str, Any]]:
    findings = []
    if agent.get("stage") == "Production" and (agent.get("reviews") or {}).get("security") != "Approved":
        findings.append(_finding(
            "security.prod_without_security_approval", SECURITY, "HIGH", _TITLE_PROD_NO_SECURITY,
            "This agent is live in Production but its security governance gate is not Approved.",
        ))
    if agent.get("riskLevel") in ("HIGH", "CRITICAL") and (not agent.get("apiEndpoint") or endpoint_is_phoenix):
        findings.append(_finding(
            "security.high_risk_without_endpoint", SECURITY, "MEDIUM", _TITLE_HIGH_RISK_NO_ENDPOINT,
            "Declared risk level is high, but no endpoint is on record to audit or monitor.",
        ))
    return findings


def _data_privacy_findings(agent: dict[str, Any]) -> list[dict[str, Any]]:
    touches_data = bool(agent.get("databases")) or bool(agent.get("enterpriseSystems"))
    if not touches_data or (agent.get("reviews") or {}).get("dp") == "Approved":
        return []
    return [_finding(
        "data_privacy.data_access_without_dp_approval", DATA_PRIVACY,
        "HIGH" if agent.get("stage") == "Production" else "MEDIUM", _TITLE_DATA_NO_DP,
        "This agent declares databases/enterprise systems it reads or writes, but its Data "
        "Protection governance gate is not Approved.",
    )]


def _error_rate_severity(rate: float) -> str:
    return "HIGH" if rate > ERROR_RATE_HIGH else "MEDIUM" if rate > ERROR_RATE_MEDIUM else "LOW"


def _graph_error_findings(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not graph or graph.get("status") != "ok":
        return []
    nodes = graph.get("nodes") or []
    total = sum(n.get("count", 0) for n in nodes)
    errors = sum(n.get("errorCount", 0) for n in nodes)
    if total == 0 or errors == 0:
        return []
    rate = errors / total
    worst = max(nodes, key=lambda n: n.get("errorCount", 0))
    return [_finding(
        "operational.trace_error_rate", OPERATIONAL, _error_rate_severity(rate),
        f"{errors} error span(s) across {total} sampled spans ({rate:.1%})",
        f"Worst step: '{worst.get('name')}' ({worst.get('errorCount')} error(s) of {worst.get('count')} calls).",
    )]


def _kri_findings(agent: dict[str, Any], kri: dict[str, Any], sla_ms: float | None) -> list[dict[str, Any]]:
    findings = []
    total = kri.get("span_count") or 0
    traces = kri.get("trace_count") or 0
    rate = kri.get("error_rate")
    errors = kri.get("error_spans")
    if errors is None and rate is not None:
        errors = round(rate * total)
    if total and errors:
        rate = errors / total
        worst = kri.get("worst_error_span") or {}
        parts = []
        if worst.get("name"):
            parts.append(f"Worst step: '{worst['name']}' ({worst.get('errors')} error span(s)).")
        if traces < MIN_TRACES_FOR_STABLE_RATE:
            parts.append(f"Small sample: {traces} trace(s) in the last 7 days.")
        findings.append(_finding(
            "operational.trace_error_rate", OPERATIONAL, _error_rate_severity(rate),
            f"{errors} error span(s) across {total} sampled spans ({rate:.1%})",
            " ".join(parts) or None,
        ))

    if (kri.get("pii_spans") or 0) > 0:
        findings.append(_finding(
            "data_privacy.pii_detected", DATA_PRIVACY,
            "HIGH" if agent.get("stage") == "Production" else "MEDIUM",
            "PII detected in traces (last 7 days)",
            f"{kri['pii_spans']} span(s) in {kri.get('pii_traces', 0)} trace(s) carry pii.detected=true. "
            "Confirm the data handling with the Data Protection reviewer.",
        ))

    if (kri.get("injection_spans") or 0) > 0:
        findings.append(_finding(
            "security.prompt_injection_detected", SECURITY, "HIGH",
            "Prompt injection detected in traces (last 7 days)",
            f"{kri['injection_spans']} span(s) in {kri.get('injection_traces', 0)} trace(s) carry "
            "guardrail.injection_detected=true. Inspect those traces in Phoenix.",
        ))

    p95 = kri.get("p95_latency_ms")
    if sla_ms is not None and p95 is not None and p95 > sla_ms:
        findings.append(_finding(
            "operational.latency_above_sla", OPERATIONAL, "MEDIUM",
            f"p95 latency {p95:,.0f} ms exceeds the {sla_ms:,.0f} ms SLA",
            f"Measured over {traces} trace(s) in the last 7 days (whole-trace duration).",
        ))
    return findings


def _observability_findings(agent: dict[str, Any], trace_status: str | None) -> list[dict[str, Any]]:
    if agent.get("stage") != "Production" or trace_status not in ("not_linked", "no_traces"):
        return []
    reason = ("No Phoenix project is linked, so nothing this agent does in Production is observed."
              if trace_status == "not_linked"
              else "The linked Phoenix project recorded no spans in the last 7 days.")
    return [_finding("compliance.no_observability", COMPLIANCE, "MEDIUM",
                     "Production agent without trace observability", reason)]


def _endpoint_is_phoenix_findings(endpoint_is_phoenix: bool) -> list[dict[str, Any]]:
    if not endpoint_is_phoenix:
        return []
    return [_finding(
        "compliance.api_endpoint_is_phoenix", COMPLIANCE, "LOW",
        "API endpoint on record is the Phoenix tracing host",
        "The registered API endpoint points at the Phoenix server, not at the agent. Record the agent's real endpoint.",
    )]


def _graph_findings(blast_radius_count: int | None, dependency_drift: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = []
    if blast_radius_count is not None and blast_radius_count >= BLAST_RADIUS_THRESHOLD:
        findings.append(_finding(
            "operational.wide_blast_radius", OPERATIONAL, "MEDIUM",
            f"Outage would affect {blast_radius_count} dependents",
            "Agents calling this one and the consumers of those agents lose service if it fails. "
            "Check fallbacks and circuit breakers.",
        ))
    observed_only = list((dependency_drift or {}).get("observed_only") or [])
    if observed_only:
        names = ", ".join(
            f"{item.get('kind', 'dependency')} '{item.get('name')}'" if isinstance(item, dict) else f"'{item}'"
            for item in observed_only[:10]
        )
        more = f" and {len(observed_only) - 10} more" if len(observed_only) > 10 else ""
        findings.append(_finding(
            "operational.undeclared_dependencies", OPERATIONAL, "LOW",
            "Undeclared dependencies observed",
            f"Seen in traces but not declared on the agent: {names}{more}.",
        ))
    return findings


def _reputational_findings(agent: dict[str, Any]) -> list[dict[str, Any]]:
    if not (agent.get("atRisk") and agent.get("stage") == "Production"):
        return []
    return [_finding("reputational.at_risk_in_production", REPUTATIONAL, "MEDIUM", _TITLE_AT_RISK,
                     agent.get("riskNote") or "Marked at_risk with no note on record.")]


def _details_text(details: Any) -> str | None:
    if not isinstance(details, dict):
        return None
    parts = [f"{k}: {v}" for k, v in details.items()
             if k != "source" and isinstance(v, (str, int, float, bool))][:4]
    return "; ".join(parts) or None


def _label(value: Any) -> str:
    return str(value or "unknown").replace("_", " ")


def financial_findings(
    *,
    financial_flags: list[dict[str, Any]] | None = None,
    cost_anomalies: list[dict[str, Any]] | None = None,
    waste_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Live FINANCIAL findings; the inputs are open rows/flags only. Each
    carries `origin` (which table or module it came from) and `data_source`
    ('phoenix' | 'seed' | ...) when the input says so."""
    findings = []
    for flag in financial_flags or []:
        code = flag.get("code") or flag.get("rule_id") or flag.get("id") or flag.get("type")
        finding = _finding(
            f"financial.flag.{_slug(code)}", FINANCIAL, _norm_severity(flag.get("severity")),
            flag.get("title") or flag.get("label") or _label(code),
            flag.get("description") or flag.get("detail") or flag.get("message"),
        )
        finding.update(origin="economics", data_source=flag.get("source"), source_id=None)
        findings.append(finding)
    for row in cost_anomalies or []:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        finding = _finding(
            f"financial.cost_anomaly.{_slug(row.get('anomaly_type'))}", FINANCIAL, _norm_severity(row.get("severity")),
            f"Cost anomaly: {_label(row.get('anomaly_type'))}", _details_text(details),
        )
        finding.update(origin="cost_anomalies", data_source=details.get("source"), source_id=row.get("id"))
        findings.append(finding)
    for row in waste_findings or []:
        finding = _finding(
            f"financial.waste.{_slug(row.get('waste_type'))}", FINANCIAL, _norm_severity(row.get("severity")),
            f"Waste: {_label(row.get('waste_type'))}", row.get("recommendation"),
        )
        finding.update(origin="waste_findings", data_source=None, source_id=row.get("id"))
        findings.append(finding)
    return findings


def partition_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(stored in agent_risks, FINANCIAL merged live)."""
    stored = [f for f in findings if f["category"] != FINANCIAL]
    financial = [f for f in findings if f["category"] == FINANCIAL]
    return stored, financial


def detect_risks(
    agent: dict[str, Any],
    graph: dict[str, Any] | None = None,
    *,
    kri: dict[str, Any] | None = None,
    sla_p95_ms: float | None = None,
    financial_flags: list[dict[str, Any]] | None = None,
    cost_anomalies: list[dict[str, Any]] | None = None,
    waste_findings: list[dict[str, Any]] | None = None,
    blast_radius_count: int | None = None,
    dependency_drift: dict[str, Any] | None = None,
    gate_states: dict[str, Any] | None = None,
    trace_status: str | None = None,
    phoenix_base_url: str | None = None,
) -> list[dict[str, Any]]:
    """`agent` is the `_agent_to_dict()` shape. `graph` is the reconstructed
    graph; `kri` (from trace_kri) supersedes it for the error-rate rule.
    `trace_status` is 'ok' | 'no_traces' | 'not_linked' | 'unavailable';
    None means the caller did not look, so the observability rule is skipped."""
    reviews = agent.get("reviews") or {}
    api_host = _host(agent.get("apiEndpoint"))
    endpoint_is_phoenix = bool(api_host) and api_host == _host(phoenix_base_url)
    sla_ms = sla_p95_ms if sla_p95_ms is not None else parse_sla_ms(agent.get("sla"))

    findings: list[dict[str, Any]] = []
    findings += _compliance_findings(reviews)
    findings += _gate_expiry_findings(gate_states)
    findings += _observability_findings(agent, trace_status)
    findings += _endpoint_is_phoenix_findings(endpoint_is_phoenix)
    findings += _security_findings(agent, endpoint_is_phoenix)
    findings += _data_privacy_findings(agent)
    findings += _kri_findings(agent, kri, sla_ms) if kri is not None else _graph_error_findings(graph)
    findings += _graph_findings(blast_radius_count, dependency_drift)
    findings += _reputational_findings(agent)
    findings += financial_findings(
        financial_flags=financial_flags, cost_anomalies=cost_anomalies, waste_findings=waste_findings,
    )
    return findings
