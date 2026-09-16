"""Auto-detects risk findings from real signals already in the registry —
governance gate status, the reconstructed-trace error rate, and an agent's
own declared fields. Explicitly heuristic, not a safety/compliance
certification: every rule below is named for the exact signal it reads, so
a reviewer can tell "the tool flagged this because X" rather than trusting
an opaque score. Pure functions — no DB/HTTP I/O — so they're safe to unit
test without touching the database (see the "never run pytest against the
live SQLite file" rule elsewhere in this codebase's history).
"""

from __future__ import annotations

from typing import Any

from governance.risk_categories import RiskCategory

# Gate status -> severity if that gate isn't Approved. "Changes Requested" is
# an active rejection (worse than simply not-yet-reviewed), so it outranks
# the other two.
_GATE_STATUS_SEVERITY: dict[str, str] = {
    "Not Submitted": "MEDIUM",
    "In Review": "MEDIUM",
    "Approved with Conditions": "LOW",
    "Changes Requested": "HIGH",
}

_GATE_LABELS = {"arb": "Architecture Review", "security": "Security Review", "dp": "Data Protection Review"}


def _compliance_findings(reviews: dict[str, str]) -> list[dict[str, Any]]:
    findings = []
    for gate, label in _GATE_LABELS.items():
        status = reviews.get(gate, "Not Submitted")
        if status == "Approved":
            continue
        severity = _GATE_STATUS_SEVERITY.get(status, "MEDIUM")
        findings.append({
            "category": RiskCategory.COMPLIANCE,
            "severity": severity,
            "title": f"{label} not approved",
            "description": f"Gate '{gate}' is currently '{status}'.",
        })
    return findings


def _security_findings(agent: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    # An agent live in Production with no completed security review is the
    # single clearest security signal this registry can read without a real
    # scanner — everything else here would be a guess this module refuses
    # to make.
    if agent.get("stage") == "Production" and agent.get("reviews", {}).get("security") != "Approved":
        findings.append({
            "category": RiskCategory.SECURITY,
            "severity": "HIGH",
            "title": "Production agent without an approved security review",
            "description": "This agent is live in Production but its security governance gate is not Approved.",
        })
    if agent.get("riskLevel") in ("HIGH", "CRITICAL") and not agent.get("apiEndpoint"):
        findings.append({
            "category": RiskCategory.SECURITY,
            "severity": "MEDIUM",
            "title": "High risk level with no registered API endpoint",
            "description": "Declared risk level is high, but no endpoint is on record to audit or monitor.",
        })
    return findings


def _data_privacy_findings(agent: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    touches_data = bool(agent.get("databases")) or bool(agent.get("enterpriseSystems"))
    if touches_data and agent.get("reviews", {}).get("dp") != "Approved":
        findings.append({
            "category": RiskCategory.DATA_PRIVACY,
            "severity": "HIGH" if agent.get("stage") == "Production" else "MEDIUM",
            "title": "Touches real systems/data without an approved DP review",
            "description": "This agent declares databases/enterprise systems it reads or writes, but its Data "
                            "Protection governance gate is not Approved.",
        })
    return findings


def _operational_findings(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Reads the RECONSTRUCTED-FROM-TRACES graph (discovery/reconstruct.py),
    not declared fields — this is the one category that's only available
    once an agent is linked to a Phoenix project and has real traces."""
    if not graph or graph.get("status") != "ok":
        return []
    nodes = graph.get("nodes") or []
    total = sum(n.get("count", 0) for n in nodes)
    errors = sum(n.get("errorCount", 0) for n in nodes)
    if total == 0 or errors == 0:
        return []
    error_rate = errors / total
    severity = "HIGH" if error_rate > 0.10 else "MEDIUM" if error_rate > 0.02 else "LOW"
    worst = max(nodes, key=lambda n: n.get("errorCount", 0))
    return [{
        "category": RiskCategory.OPERATIONAL,
        "severity": severity,
        "title": f"{errors} error span(s) across {total} sampled spans ({error_rate:.1%})",
        "description": f"Worst step: '{worst.get('name')}' ({worst.get('errorCount')} error(s) of {worst.get('count')} calls).",
    }]


def _reputational_findings(agent: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    if agent.get("atRisk") and agent.get("stage") == "Production":
        findings.append({
            "category": RiskCategory.REPUTATIONAL,
            "severity": "MEDIUM",
            "title": "Flagged at-risk while live in Production",
            "description": agent.get("riskNote") or "Marked at_risk with no note on record.",
        })
    return findings


def detect_risks(agent: dict[str, Any], graph: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """`agent` is the same dict shape `_agent_to_dict()` produces. `graph` is
    the optional reconstructed-graph response for this agent (None if it
    isn't linked to a Phoenix project, or the caller chose not to fetch it).
    Returns every current finding across all five AgentRisk categories —
    the caller (the /risks/scan endpoint) decides how to persist them."""
    reviews = agent.get("reviews") or {}
    findings: list[dict[str, Any]] = []
    findings += _compliance_findings(reviews)
    findings += _security_findings(agent)
    findings += _data_privacy_findings(agent)
    findings += _operational_findings(graph)
    findings += _reputational_findings(agent)
    return findings
