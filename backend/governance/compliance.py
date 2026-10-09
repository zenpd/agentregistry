"""Compliance packs as data: the controls of the EU AI Act, ISO/IEC 42001 Annex A,
the NIST AI RMF categories and India's Digital Personal Data Protection Act, each
mapped to evidence the registry holds.

A control is "evidenced" for an agent when every piece of registry evidence it is
mapped to is present for that agent (and the registry-wide rules it names are on).
"Evidenced" means the registry holds the record an auditor would ask for. It is not
a statement that the organisation complies. Controls the registry holds no evidence
for are "outside": their evidence lives elsewhere (policies, training records,
filings), and the pack says where.

Pure data and functions. services/compliance_facts.py computes the evidence."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# ── Evidence the registry can show, per agent ───────────────────────────────

AGENT_EVIDENCE = {
    "owner": "An accountable owner is recorded",
    "owner_person": "The owner is a named person with an account",
    "purpose": "The intended purpose is described (20 characters or more)",
    "business_outcome": "The business outcome is stated",
    "value_declared": "Expected value is declared",
    "classification": "The classification is confirmed by a decider",
    "not_prohibited": "The confirmed classification is not Unacceptable Risk",
    "data_recorded": "The personal data it uses is recorded in the classification",
    "retention_recorded": "How long it keeps personal data is recorded",
    "model": "The model is declared",
    "dependencies": "Systems, data stores and tools are declared",
    "tools_listed": "Every declared tool is on the approved tool list",
    "contract": "Capabilities, inputs, outputs and a service level are declared",
    "tracing": "Runtime tracing is linked",
    "hosting_known": "Hosting cost is metered or declared, not estimated",
    "risk_scan": "A risk scan has run",
    "no_high_findings": "No open high or critical security or privacy finding",
    "arb_approved": "Architecture Review Board approval is in force",
    "security_approved": "Security Review approval is in force",
    "dp_approved": "Data Protection Review approval is in force",
    "human_oversight": "Human oversight and fallback are confirmed in the review checklist",
    "decommission_plan": "A rollback and decommissioning plan is confirmed in the review checklist",
    "context_doc": "A context document (context.md) is provided",
    "versions": "At least one version is released with a changelog",
}

# ── Registry-wide rules (from the controls list in Settings) ─────────────────

REGISTRY_EVIDENCE = {
    "roles": "Role checks on every action",
    "audit_log": "Audit rows cannot be changed or deleted",
    "decision_chain": "The hash chain over decisions verifies",
    "stage_gates": "Reviews before a stage change",
    "approval_expiry": "Approvals expire",
    "change_reopens": "A change after approval reopens the reviews it affects",
    "waivers": "Waivers need two different signers",
    "self_approval": "Nobody approves their own access request",
    "classification_rule": "Classification confirmed by a decider",
    "retirement_rule": "Retirement only through checked steps",
    "notices": "Daily notices",
    "incident_linking": "Incidents can be linked to agents and owners asked to stop them",
}

APPLIES_TEXT = {
    "all": "every agent",
    "high_risk": "agents classified High Risk (and agents not classified yet)",
    "production": "agents in Production",
    "personal_data": "agents that use personal data (and agents not classified yet)",
    "interacts": "agents that talk to people or generate content (and agents not classified yet)",
}


def C(cid: str, title: str, *, agent: Iterable[str] = (), registry: Iterable[str] = (), applies: str = "all",
      outside: str | None = None) -> dict:
    return {"id": cid, "title": title, "agent": list(agent), "registry": list(registry), "applies": applies, "outside": outside}


PACKS: dict[str, dict] = {
    "eu_ai_act": {
        "name": "EU AI Act", "source": "Regulation (EU) 2024/1689",
        "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
        "dates": [
            {"key": "in_force", "label": "Entered into force", "date": "2024-08-01"},
            {"key": "prohibitions", "label": "Prohibited practices and AI literacy apply (Articles 4 and 5)", "date": "2025-02-02"},
            {"key": "gpai", "label": "General-purpose AI model obligations apply", "date": "2025-08-02"},
            {"key": "high_risk", "label": "High-risk obligations (Annex III) and Article 50 apply", "date": "2026-08-02"},
            {"key": "products", "label": "High-risk AI in regulated products (Article 6(1)) applies", "date": "2027-08-02"},
        ],
        "controls": [
            C("Art. 4", "AI literacy", outside="Training records for staff who use or run AI are kept in the learning system."),
            C("Art. 5", "Prohibited AI practices", agent=["classification", "not_prohibited"]),
            C("Art. 6 and Annex III", "Classification of high-risk AI systems", agent=["classification"]),
            C("Art. 9", "Risk management system", agent=["risk_scan", "no_high_findings", "security_approved"], applies="high_risk"),
            C("Art. 10", "Data and data governance", agent=["data_recorded", "dp_approved"], applies="high_risk"),
            C("Art. 11 and Annex IV", "Technical documentation", agent=["purpose", "model", "dependencies", "contract", "versions"], applies="high_risk"),
            C("Art. 12", "Record-keeping (automatic logs)", agent=["tracing"], registry=["audit_log"], applies="high_risk"),
            C("Art. 13", "Transparency and information to deployers", agent=["purpose", "contract", "owner"], applies="high_risk"),
            C("Art. 14", "Human oversight", agent=["human_oversight"], applies="high_risk"),
            C("Art. 15", "Accuracy, robustness and cybersecurity", applies="high_risk",
              outside="Accuracy and robustness test results are kept in the tool that tests the agent. The Security Review on each agent covers the cybersecurity part."),
            C("Art. 17", "Quality management system", agent=["arb_approved"],
              registry=["stage_gates", "approval_expiry", "change_reopens", "decision_chain"], applies="high_risk"),
            C("Art. 26", "Obligations of deployers", agent=["owner_person", "human_oversight", "tracing"], applies="high_risk"),
            C("Art. 27", "Fundamental rights impact assessment", applies="high_risk",
              outside="The Data Protection Review is not a fundamental rights impact assessment. Keep the assessment outside and attach it to the review."),
            C("Art. 49", "Registration in the EU database", applies="high_risk", outside="Registration is made in the EU database itself."),
            C("Art. 50", "Transparency for AI that talks to people or generates content", applies="interacts",
              outside="The classification lists the agents this applies to. Whether people are told they deal with AI is checked in each app."),
            C("Art. 72", "Post-market monitoring", agent=["tracing", "risk_scan"], applies="high_risk"),
            C("Art. 73", "Reporting of serious incidents", applies="high_risk",
              outside="Incidents are linked to agents on the Risk tab. The report to the market surveillance authority is made outside the registry."),
        ],
    },
    "iso_42001": {
        "name": "ISO/IEC 42001", "source": "ISO/IEC 42001:2023 Annex A",
        "url": "https://www.iso.org/standard/42001",
        "dates": [{"key": "published", "label": "Standard published", "date": "2023-12-18"},
                  {"key": "audit", "label": "Next certification audit", "date": ""}],
        "controls": [
            C("A.2.2", "AI policy", outside="The AI policy is a document approved by management."),
            C("A.2.3", "Alignment with other organizational policies", outside="Kept with the AI policy."),
            C("A.2.4", "Review of the AI policy", outside="Kept with the AI policy."),
            C("A.3.2", "AI roles and responsibilities", agent=["owner_person"], registry=["roles"]),
            C("A.3.3", "Reporting of concerns", registry=["incident_linking"]),
            C("A.4.2", "Resource documentation", agent=["dependencies", "model"]),
            C("A.4.3", "Data resources", agent=["data_recorded"]),
            C("A.4.4", "Tooling resources", agent=["tools_listed"]),
            C("A.4.5", "System and computing resources", agent=["hosting_known"]),
            C("A.4.6", "Human resources", outside="Skills and staffing records are kept by HR."),
            C("A.5.2", "AI system impact assessment process", registry=["classification_rule"]),
            C("A.5.3", "Documentation of AI system impact assessments", agent=["classification"]),
            C("A.5.4", "Assessing AI system impact on individuals or groups", agent=["classification", "dp_approved"]),
            C("A.5.5", "Assessing societal impacts of AI systems", outside="A societal impact assessment is kept outside the registry."),
            C("A.6.1.2", "Objectives for responsible development of AI systems", agent=["business_outcome"]),
            C("A.6.1.3", "Processes for responsible AI system design and development", agent=["arb_approved"], registry=["stage_gates"]),
            C("A.6.2.2", "AI system requirements and specification", agent=["contract"]),
            C("A.6.2.3", "Documentation of AI system design and development", agent=["purpose", "dependencies", "versions"]),
            C("A.6.2.4", "AI system verification and validation",
              outside="Verification and validation results are kept in the tool that tests the agent. The registry holds the review decisions, not test results."),
            C("A.6.2.5", "AI system deployment", agent=["arb_approved", "security_approved", "dp_approved"], applies="production"),
            C("A.6.2.6", "AI system operation and monitoring", agent=["tracing", "risk_scan"], applies="production"),
            C("A.6.2.7", "AI system technical documentation", agent=["purpose", "contract", "context_doc"]),
            C("A.6.2.8", "AI system recording of event logs", agent=["tracing"], registry=["audit_log"]),
            C("A.7.2", "Data for development and enhancement of AI systems", outside="Training and tuning data records are kept with the data platform."),
            C("A.7.3", "Acquisition of data", outside="Kept with the data platform."),
            C("A.7.4", "Quality of data for AI systems", outside="Kept with the data platform."),
            C("A.7.5", "Data provenance", outside="Kept with the data platform."),
            C("A.7.6", "Data preparation", outside="Kept with the data platform."),
            C("A.8.2", "System documentation and information for users", agent=["contract", "purpose"]),
            C("A.8.3", "External reporting", outside="Reports to outside parties are kept where they are filed."),
            C("A.8.4", "Communication of incidents", registry=["incident_linking", "notices"]),
            C("A.8.5", "Information for interested parties", outside="Kept with the communications team."),
            C("A.9.2", "Processes for responsible use of AI systems", agent=["owner"], registry=["stage_gates", "self_approval"]),
            C("A.9.3", "Objectives for responsible use of AI systems", agent=["business_outcome"]),
            C("A.9.4", "Intended use of the AI system", agent=["purpose", "classification"]),
            C("A.10.2", "Allocating responsibilities", agent=["owner_person"]),
            C("A.10.3", "Suppliers", agent=["model", "tools_listed"]),
            C("A.10.4", "Customers", agent=["contract"]),
        ],
    },
    "nist_ai_rmf": {
        "name": "NIST AI RMF", "source": "NIST AI 100-1 (AI RMF 1.0), categories",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        "dates": [{"key": "published", "label": "Framework published (voluntary)", "date": "2023-01-26"}],
        "controls": [
            C("GOVERN 1", "Policies, processes and practices for AI risk are in place and followed",
              registry=["stage_gates", "approval_expiry", "classification_rule"]),
            C("GOVERN 2", "Accountability structures are in place", agent=["owner_person"], registry=["roles"]),
            C("GOVERN 3", "Workforce diversity, equity, inclusion and accessibility are prioritized", outside="Kept by HR."),
            C("GOVERN 4", "Teams are committed to a culture that considers and communicates AI risk", outside="Kept with training and policy records."),
            C("GOVERN 5", "Processes are in place for engagement with relevant AI actors", outside="Kept with stakeholder records."),
            C("GOVERN 6", "Risks from third-party software and data are addressed", agent=["tools_listed", "model"]),
            C("MAP 1", "Context is established and understood", agent=["purpose", "business_outcome"]),
            C("MAP 2", "Categorization of the AI system is performed", agent=["classification"]),
            C("MAP 3", "Capabilities, usage, benefits and costs are understood", agent=["business_outcome", "value_declared"]),
            C("MAP 4", "Risks and benefits are mapped for all components, including third parties", agent=["dependencies", "tools_listed"]),
            C("MAP 5", "Impacts on individuals, groups, organizations and society are characterized", agent=["classification", "dp_approved"]),
            C("MEASURE 1", "Methods and metrics are identified and applied", agent=["risk_scan"]),
            C("MEASURE 2", "AI systems are evaluated for trustworthy characteristics",
              outside="Evaluation results are kept in the tool that tests the agent. The registry holds the review decisions, not test results."),
            C("MEASURE 3", "Identified AI risks are tracked over time", agent=["tracing", "risk_scan"]),
            C("MEASURE 4", "Feedback about the efficacy of measurement is gathered", outside="Kept with the evaluation team's reviews."),
            C("MANAGE 1", "AI risks are prioritized, responded to and managed", agent=["no_high_findings"]),
            C("MANAGE 2", "Strategies to maximize benefits and minimize negative impacts are planned", agent=["value_declared", "arb_approved"]),
            C("MANAGE 3", "Risks and benefits from third-party entities are managed", agent=["tools_listed"]),
            C("MANAGE 4", "Risk treatments, response, recovery and communication are documented and monitored",
              agent=["decommission_plan"], registry=["incident_linking", "retirement_rule"]),
        ],
    },
    "india_dpdp": {
        "name": "India DPDP Act", "source": "Digital Personal Data Protection Act, 2023, and DPDP Rules, 2025",
        "url": "https://www.meity.gov.in/data-protection-framework",
        "dates": [
            {"key": "act", "label": "Act notified", "date": "2023-08-11"},
            {"key": "rules", "label": "Rules notified", "date": "2025-11-13"},
            {"key": "obligations", "label": "Main data fiduciary obligations apply", "date": "2027-05-13"},
        ],
        "controls": [
            C("S. 4", "Lawful purpose, with consent or a legitimate use", agent=["purpose", "dp_approved"], applies="personal_data"),
            C("S. 5", "Notice to the data principal", applies="personal_data", outside="Notices are shown in each app and kept with the privacy team."),
            C("S. 6", "Consent", applies="personal_data", outside="Consent records are kept by the consent system."),
            C("S. 8(3)", "Complete, accurate and consistent data for decisions", applies="personal_data", outside="Kept with the data platform."),
            C("S. 8(5)", "Reasonable security safeguards", agent=["security_approved", "no_high_findings"], applies="personal_data"),
            C("S. 8(6)", "Intimation of a personal data breach", applies="personal_data",
              outside="Breaches are linked to agents as incidents. The intimation to the Board and to people is made outside the registry."),
            C("S. 8(7)", "Erasure when the purpose is served", agent=["retention_recorded"], applies="personal_data"),
            C("S. 8(10)", "Grievance redressal", applies="personal_data", outside="Kept with the grievance officer."),
            C("S. 9", "Personal data of children", applies="personal_data", outside="Verifiable parental consent is kept by the consent system."),
            C("S. 10", "Significant data fiduciary: impact assessment and audit", agent=["dp_approved"], applies="personal_data"),
        ],
    },
}


def applies(rule: str, agent: Mapping[str, Any]) -> bool:
    """agent: {stage, category, answers, classified}. Unclassified agents are assumed in scope."""
    if rule == "all":
        return True
    if rule == "production":
        return agent.get("stage") == "Production"
    if not agent.get("classified"):
        return True
    answers = agent.get("answers") or {}
    if rule == "high_risk":
        return agent.get("category") in ("High Risk", "Unacceptable Risk")
    if rule == "personal_data":
        return answers.get("data") in ("personal", "special")
    if rule == "interacts":
        return bool(answers.get("interacts"))
    return True


def control_for_agent(control: Mapping[str, Any], evidence: Mapping[str, bool], registry: Mapping[str, bool]) -> dict:
    if control["outside"]:
        return {"status": "outside", "missing": []}
    missing = [AGENT_EVIDENCE[k] for k in control["agent"] if not evidence.get(k)]
    missing += [REGISTRY_EVIDENCE[k] + " (registry rule)" for k in control["registry"] if not registry.get(k)]
    return {"status": "evidenced" if not missing else "missing", "missing": missing}


def coverage(pack_key: str, agents: list[Mapping[str, Any]], registry: Mapping[str, bool]) -> dict:
    """agents: [{id, name, stage, category, answers, classified, evidence: {key: bool}}]

    A control is evidenced across the registry when its registry rules are on and every
    agent it applies to is evidenced. An "agent-free" control (registry rules only) is
    evidenced when its rules are on."""
    pack = PACKS[pack_key]
    rows = []
    for c in pack["controls"]:
        scope = [a for a in agents if applies(c["applies"], a)]
        per = [{"agentId": a["id"], "name": a["name"], **control_for_agent(c, a["evidence"], registry)} for a in scope]
        if c["outside"]:
            status = "outside"
        elif not c["agent"]:
            status = "evidenced" if all(registry.get(k) for k in c["registry"]) else "missing"
        elif not scope:
            status = "not_applicable"
        else:
            status = "evidenced" if all(p["status"] == "evidenced" for p in per) else "missing"
        gaps = [p for p in per if p["status"] == "missing"]
        rows.append({**{k: c[k] for k in ("id", "title", "applies", "outside")}, "appliesText": APPLIES_TEXT[c["applies"]],
                     "evidence": [AGENT_EVIDENCE[k] for k in c["agent"]] + [REGISTRY_EVIDENCE[k] + " (registry rule)" for k in c["registry"]],
                     "status": status, "agentsInScope": len(scope), "agentsMissing": len(gaps), "agents": per,
                     "registryMissing": [REGISTRY_EVIDENCE[k] for k in c["registry"] if not registry.get(k)]})
    counted = [r for r in rows if r["status"] in ("evidenced", "missing")]
    return {"key": pack_key, "name": pack["name"], "source": pack["source"], "url": pack.get("url"), "controls": rows,
            "total": len(rows), "evidenced": sum(1 for r in rows if r["status"] == "evidenced"),
            "missing": sum(1 for r in rows if r["status"] == "missing"), "outside": sum(1 for r in rows if r["status"] == "outside"),
            "notApplicable": sum(1 for r in rows if r["status"] == "not_applicable"), "inRegistry": len(counted)}


from governance.classification import RETENTION  # noqa: E402  one list, used by the data and retention report
