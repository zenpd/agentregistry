"""Lifecycle rules: what an approval covered and what changed since, time in
stage and stalls, required fields per stage and record completeness, gate
templates by risk tier, and waivers. Pure functions over plain data."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

# ── What an approval covered ─────────────────────────────────────────────────

STRUCTURAL: dict[str, str] = {
    "model_name": "Model", "mcp_servers": "Tools and MCP servers", "knowledge_bases": "Knowledge bases",
    "databases": "Databases", "enterprise_systems": "Enterprise systems", "api_endpoint": "API endpoint",
    "calls": "Agents it calls",
}
# Which reviews a change touches.
AFFECTS: dict[str, tuple[str, ...]] = {
    "model_name": ("arb", "security"), "mcp_servers": ("security", "dp"), "knowledge_bases": ("security", "dp"),
    "databases": ("security", "dp"), "enterprise_systems": ("arb", "dp"), "api_endpoint": ("arb",), "calls": ("arb",),
}


def _norm(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return sorted({str(v).strip() for v in value if str(v).strip()})
    return (str(value).strip() if value is not None else "") or None


def snapshot(record: Mapping[str, Any]) -> dict:
    """The structural fields an approval was given for, and their hash."""
    fields = {k: _norm(record.get(k)) for k in STRUCTURAL}
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    return {"fields": fields, "hash": digest}


def changed_since(snap: Mapping[str, Any] | None, record: Mapping[str, Any]) -> list[dict]:
    """[{field, label, before, after, added, removed}] for every structural field that differs."""
    if not snap or not snap.get("fields"):
        return []
    now = snapshot(record)
    if now["hash"] == snap.get("hash"):
        return []
    out = []
    for key, label in STRUCTURAL.items():
        before, after = snap["fields"].get(key), now["fields"].get(key)
        if before == after:
            continue
        item = {"field": key, "label": label, "before": before, "after": after}
        if isinstance(before, list) or isinstance(after, list):
            item["added"] = sorted(set(after or []) - set(before or []))
            item["removed"] = sorted(set(before or []) - set(after or []))
        out.append(item)
    return out


def affected_gates(changes: list[dict]) -> set[str]:
    return {g for c in changes for g in AFFECTS.get(c["field"], ())}


def describe(changes: list[dict]) -> str:
    parts = []
    for c in changes:
        if "added" in c:
            bits = ([f"+{', '.join(c['added'])}"] if c["added"] else []) + ([f"-{', '.join(c['removed'])}"] if c["removed"] else [])
            parts.append(f"{c['label']} ({' '.join(bits)})")
        else:
            parts.append(f"{c['label']} ({c['before'] or 'empty'} → {c['after'] or 'empty'})")
    return ", ".join(parts)


# ── Time in stage ────────────────────────────────────────────────────────────

DEFAULT_STALL_WEEKS = {"Ideation": 12, "Development": 16, "Testing": 8}


def weeks_in_stage(since: datetime | None, now: datetime) -> int | None:
    if since is None:
        return None
    return max(0, (now - since).days // 7)


def stalled(stage: str, weeks: int | None, limits: Mapping[str, int] | None = None) -> bool:
    limit = (limits or DEFAULT_STALL_WEEKS).get(stage)
    return bool(limit and weeks is not None and weeks >= limit)


# ── Required fields and completeness ─────────────────────────────────────────

FIELD_LABELS = {
    "owner": "an accountable owner", "dept": "the owning department", "description": "a description",
    "business_outcome": "the business outcome", "sla": "a service level", "phoenix_project": "a tracing link",
    "value_amount": "the declared value", "model_name": "the model", "api_endpoint": "the API endpoint",
    "capabilities": "capabilities", "inputs": "inputs", "outputs": "outputs", "budget": "a monthly budget",
    "classification": "a confirmed classification", "reviews": "submitted reviews",
}
DEFAULT_REQUIRED = {
    "Development": ["owner", "dept"],
    "Testing": ["owner", "dept", "description", "business_outcome"],
    "Production": ["owner", "dept", "description", "business_outcome", "phoenix_project"],
}
COMPLETENESS_FIELDS = ("owner", "dept", "description", "business_outcome", "value_amount", "model_name", "api_endpoint",
                       "capabilities", "inputs", "outputs", "sla", "phoenix_project", "budget", "classification", "reviews")


def filled(key: str, facts: Mapping[str, Any]) -> bool:
    value = facts.get(key)
    if key == "owner":
        return bool(value) and str(value).strip().lower() not in ("", "unassigned")
    if key == "description":
        return len(str(value or "").strip()) >= 20
    if key == "value_amount":
        return bool(value) and int(value) > 0
    if key == "phoenix_project":
        return bool(value) or bool(facts.get("trace_connector_id"))
    if key in ("budget", "classification", "reviews"):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return bool(str(value or "").strip())


def missing_required(target: str, facts: Mapping[str, Any], required: Mapping[str, list[str]] | None = None) -> list[str]:
    """Fields the target stage requires (cumulative along the normal path) that the record lacks."""
    required = required if required is not None else DEFAULT_REQUIRED
    order = ("Development", "Testing", "Production")
    if target not in order:
        return []
    needed: list[str] = []
    for stage in order[: order.index(target) + 1]:
        for key in required.get(stage, []):
            if key not in needed:
                needed.append(key)
    return [k for k in needed if not filled(k, facts)]


def completeness(facts: Mapping[str, Any]) -> dict:
    have = [k for k in COMPLETENESS_FIELDS if filled(k, facts)]
    missing = [FIELD_LABELS[k] for k in COMPLETENESS_FIELDS if k not in have]
    return {"score": round(100 * len(have) / len(COMPLETENESS_FIELDS)), "filled": len(have),
            "total": len(COMPLETENESS_FIELDS), "missing": missing}


# ── Gate templates by risk tier ──────────────────────────────────────────────

GATES = ("arb", "security", "dp")
TIERS = ("LOW", "MEDIUM", "HIGH")


def default_templates(validity_default: int, validity_high: int, mode: str) -> dict:
    """Defaults that keep today's behaviour: every gate, the configured validity, the configured mode."""
    return {
        "LOW": {"gates": list(GATES), "validityDays": validity_default, "mode": mode},
        "MEDIUM": {"gates": list(GATES), "validityDays": validity_default, "mode": mode},
        "HIGH": {"gates": list(GATES), "validityDays": validity_high, "mode": mode},
    }


def check_templates(templates: Mapping[str, Any]) -> str | None:
    for tier in TIERS:
        t = templates.get(tier)
        if not isinstance(t, Mapping):
            return f"A template for {tier} is missing."
        if not t.get("gates") or any(g not in GATES for g in t["gates"]):
            return f"{tier}: gates must be some of {', '.join(GATES)} (at least one)."
        if "arb" not in t["gates"]:
            return f"{tier}: the Architecture Review Board is always required (it is the gate into Testing)."
        if not isinstance(t.get("validityDays"), int) or not 30 <= t["validityDays"] <= 730:
            return f"{tier}: approval validity must be 30 to 730 days."
        if t.get("mode") not in ("warn", "block"):
            return f"{tier}: mode must be warn or block."
    return None


# ── Waivers ──────────────────────────────────────────────────────────────────

NOT_WAIVABLE = {"security": "A failed Security Review cannot be waived. Fix the finding instead."}
MIN_WAIVER_REASON = 20


def waiver_refusal(gate: str, reason: str) -> str | None:
    if gate in NOT_WAIVABLE:
        return NOT_WAIVABLE[gate]
    if len((reason or "").strip()) < MIN_WAIVER_REASON:
        return f"Say why in at least {MIN_WAIVER_REASON} characters."
    return None


def waiver_counts(waivers: list[Mapping[str, Any]]) -> dict:
    """Waiver completeness: share of active waivers with a reason and two signers."""
    active = [w for w in waivers if w.get("status") in ("active", None)]
    complete = [w for w in active if w.get("first_signer") and w.get("second_signer") and len((w.get("reason") or "").strip()) >= MIN_WAIVER_REASON]
    return {"active": len(active), "complete": len(complete),
            "share": round(100 * len(complete) / len(active)) if active else None,
            "pending": len([w for w in waivers if w.get("status") == "pending"])}
