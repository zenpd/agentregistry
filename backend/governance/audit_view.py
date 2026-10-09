"""How an audit row is shown: who did it (a person or the registry itself),
which kind of event it is, and one plain line about it. Pure functions."""
from __future__ import annotations

# Events the registry does by itself (jobs, AI runs, reads of other systems),
# even when a person's page view started them.
MACHINE_ACTIONS = frozenset({
    "insight.run", "risk_scan", "job.run", "ai.autofill", "agent.refresh", "usage.refresh",
    "cost_anomaly.open", "cost_anomaly.auto_resolve", "discovery.find_app", "discovery.read_app",
    "notification.sent", "notification.failed",
})

CATEGORIES: dict[str, set[str]] = {
    "Decisions": {
        "gate_update", "stage_change", "stage_change_blocked", "recertify", "exception_create", "waiver.sign",
        "access_approve", "access_reject", "access_revoke", "discovery.dismiss", "discovery.restore",
        "ai.autofill.undo", "content_audit.opt_in", "content_audit.opt_out", "risk.update", "risk.create",
        "value.attest", "classification.confirm", "classification.propose", "ownership.transfer", "discovery.merge",
        "discovery.split", "discovery.triage", "retirement.start", "retirement.step", "retirement.finish", "retirement.cancel",
        "tool.approve", "tool.update", "tool.remove", "evidence.record", "incident.stop_request", "incident.stop_ack",
    },
    "Record changes": {
        "create", "update", "delete", "context.save", "infra_profile.update", "adopt_observed_dependencies",
        "budget.update", "offboard", "offboard.step", "version.create", "version.release", "consumer.version",
        "resource_link.add", "resource_link.remove", "register", "value.declare", "outcome.record", "usage.manual",
        "incident.link", "incident.update", "incident.resolve", "agent.restore", "agent.archive", "agent.unarchive",
    },
    "Access and settings": {
        "user_create", "user_update", "user_password_reset", "phoenix_config.update", "price.update",
        "audit.export", "api_key.issue", "api_key.revoke", "settings.update", "model_alias.upsert",
        "content_audit.opt_out",
    },
    "Use": {"try_it", "access_request", "auditor.access", "evidence.export", "grc.export"},
}

ACTION_LABELS = {
    "gate_update": "Review gate changed", "stage_change": "Stage changed", "stage_change_blocked": "Stage change blocked",
    "recertify": "Recertification started", "access_approve": "Access approved", "access_reject": "Access rejected",
    "access_revoke": "Access revoked", "access_request": "Access requested", "create": "Agent registered",
    "update": "Agent record edited", "delete": "Agent deleted", "insight.run": "AI insight written",
    "risk_scan": "Risk scan", "job.run": "Job started", "ai.autofill": "Field filled in automatically",
    "ai.autofill.undo": "Automatic fill undone", "try_it": "Agent called from Try it", "agent.refresh": "Agent data refreshed",
    "usage.refresh": "Usage refreshed", "user_create": "User added", "user_update": "User changed",
    "user_password_reset": "Password reset", "phoenix_config.update": "Tracing connection changed",
    "price.update": "Model price changed", "audit.export": "Audit trail exported",
    "discovery.dismiss": "Discovered project dismissed", "discovery.restore": "Discovered project brought back",
    "discovery.merge": "Discovered project linked to a record", "discovery.split": "Shared project unlinked",
    "discovery.triage": "Discovered project assigned", "discovery.find_app": "Application searched for",
    "discovery.read_app": "Application page read", "stage_change_blocked": "Stage change blocked",
    "exception_create": "Waiver requested", "waiver.sign": "Waiver signed", "risk.update": "Risk changed",
    "risk.create": "Risk recorded", "content_audit.opt_in": "Content audit switched on",
    "content_audit.opt_out": "Content audit switched off", "value.attest": "Value attested",
    "classification.propose": "Classification proposed", "classification.confirm": "Classification confirmed",
    "ownership.transfer": "Owner changed", "tool.approve": "Tool added to the approved list",
    "tool.update": "Approved tool changed", "tool.remove": "Tool removed from the approved list",
    "version.create": "Version recorded", "version.release": "Version released", "consumer.version": "Consumer version changed",
    "retirement.start": "Retirement started", "retirement.step": "Retirement step done", "retirement.finish": "Agent retired",
    "retirement.cancel": "Retirement cancelled", "evidence.record": "Test verdict recorded",
    "offboard": "Offboarding step", "dismiss": "Governance finding dismissed", "register": "Agent registered from a manifest", "budget.update": "Budget changed",
    "model_alias.upsert": "Model name mapping changed", "settings.update": "Settings changed",
    "api_key.issue": "API key issued", "api_key.revoke": "API key revoked", "adopt_observed_dependencies": "Observed dependencies adopted",
    "cost_anomaly.open": "Cost anomaly opened", "cost_anomaly.auto_resolve": "Cost anomaly closed automatically",
    "notification.sent": "Notice sent", "notification.failed": "Notice failed",
    "value.declare": "Value declared", "outcome.record": "Outcomes recorded", "usage.manual": "Usage entered by hand",
    "incident.link": "Incident linked", "incident.update": "Incident updated", "incident.resolve": "Incident resolved",
    "incident.stop_request": "Owner asked to stop the agent", "incident.stop_ack": "Stop request acknowledged",
    "agent.restore": "Agent restored", "agent.archive": "Agent archived", "agent.unarchive": "Agent brought back", "auditor.access": "Auditor viewed", "evidence.export": "Evidence exported", "grc.export": "GRC export",
}

SYSTEM_PREFIXES = ("system", "job:", "ai:")


def category_of(action: str) -> str:
    if action in MACHINE_ACTIONS:
        return "Registry automation"
    for name, actions in CATEGORIES.items():
        if action in actions:
            return name
    return "Other"


def is_machine(actor: str, action: str) -> bool:
    return action in MACHINE_ACTIONS or (actor or "").startswith(SYSTEM_PREFIXES)


def actor_label(actor: str, names: dict[str, str]) -> str:
    if actor in names:
        return names[actor]
    if actor == "system" or not actor:
        return "Registry (system)"
    if actor.startswith("job:"):
        return f"Registry job ({actor[4:]})"
    if actor.startswith("system:"):
        return f"Registry job ({actor[7:]})"
    if actor.startswith("ai:"):
        return f"Registry AI ({actor[3:]})"
    return actor


def summary_of(action: str, changes: dict | None) -> str:
    """One readable line from the stored changes, without dumping JSON."""
    c = changes or {}
    if action == "gate_update":
        before, after = (c.get("before") or {}), (c.get("after") or {})
        line = f"{c.get('gate', '')}: {before.get('status', '?')} → {after.get('status', '?')}"
        if c.get("source") == "rule_proposal":
            line += " (rule-proposed)"
        return line
    if action in ("stage_change", "stage_change_blocked"):
        line = f"{c.get('from') or 'new'} → {c.get('to')}"
        if c.get("overrideReason"):
            line += f" · reason: {c['overrideReason']}"
        return line
    if action == "update":
        return "Changed: " + ", ".join(sorted(k for k in c if k != "dept_id")) if c else "Changed"
    if action == "user_update":
        return ", ".join(f"{k}: {v.get('from')} → {v.get('to')}" for k, v in c.items() if isinstance(v, dict))
    if action == "ai.autofill":
        return f"{c.get('field', '')} from {c.get('source', '')}".strip()
    if action == "ownership.transfer":
        before, after = c.get("before") or {}, c.get("after") or {}
        line = f"Owner {before.get('owner') or 'none'} → {after.get('owner') or 'none'}"
        if before.get("backupOwnerUserId") != after.get("backupOwnerUserId") and "backupOwnerUserId" in after:
            line += ", backup owner changed"
        return line + (f" · reason: {c['reason']}" if c.get("reason") else "")
    if action == "classification.confirm":
        before, after, sug = c.get("before") or {}, c.get("after") or {}, c.get("suggested") or {}
        line = (f"{before.get('category') or 'none'}, {before.get('riskLevel') or 'none'} → "
                f"{after.get('category')}, {after.get('riskLevel')} (suggested {sug.get('category')}, {sug.get('riskLevel')})")
        return line + (f" · reason: {c['reason']}" if c.get("reason") else "")
    if action == "classification.propose":
        return f"{c.get('category')}, {c.get('riskLevel')}"
    if action in ("tool.approve", "tool.remove"):
        return f"{c.get('name')} ({c.get('riskClass')})"
    if action == "version.release":
        return f"{c.get('previous') or 'none'} → {c.get('version')}: {c.get('changelog', '')}"
    if action == "consumer.version":
        return f"{c.get('team')}: {c.get('from') or 'not recorded'} → {c.get('to')}"
    if action in ("retirement.start", "retirement.finish", "retirement.cancel"):
        return f"reason: {c.get('reason')}" + (f", replacement {c['replacement']}" if c.get("replacement") else "")
    if action == "retirement.step":
        return f"{c.get('step')}: {c.get('note') or c.get('detail') or ''}"
    if action == "evidence.record":
        return f"run {c.get('runId')}: {c.get('verdict') or 'not read'}" + (f" ({c['error']})" if c.get("error") else "")
    if action == "value.attest":
        return f"{c.get('status')}: {c.get('declaredCents', 0) / 100:,.0f} declared, {c.get('attestedCents', 0) / 100:,.0f} attested a month · {c.get('note', '')}"
    if action == "value.declare":
        after = c.get("after") or {}
        return f"{after.get('method')}: {after.get('amountDollars')} a month · {after.get('basis', '')}"
    if action == "auditor.access":
        return f"{c.get('method')} {c.get('path')}"
    if action == "evidence.export":
        return f"{c.get('what')} ({c.get('format')}), SHA-256 {str(c.get('sha256'))[:16]}…"
    if action in ("incident.stop_request", "incident.stop_ack"):
        return f"{c.get('incident')}: {c.get('reason') or c.get('note')}"
    if action == "tool.update":
        before, after = c.get("before") or {}, c.get("after") or {}
        return f"{c.get('name')}: {before.get('riskClass')} → {after.get('riskClass')}"
    parts = []
    for k, v in list(c.items())[:4]:
        if isinstance(v, (str, int, float, bool)) and str(v):
            parts.append(f"{k}: {str(v)[:80]}")
    return ", ".join(parts)
