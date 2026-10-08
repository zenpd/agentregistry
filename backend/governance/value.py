"""Value and spend: how a declared value is worked out (the method), whether a
finance reviewer attested it, cost per measured outcome, the same tokens priced
at other models, idle and duplicate spend, and what moving agents to Production
would change. Pure functions over plain data."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

METHODS = {
    "cost_avoidance": "Cost avoidance",
    "revenue_influenced": "Revenue influenced",
    "time_saved": "Time saved",
    "risk_avoided": "Risk avoided",
}
METHOD_HELP = {
    "cost_avoidance": "Money the organisation no longer spends because the agent does the work, for example fewer outsourced hours or licences.",
    "revenue_influenced": "Revenue the agent helps win or keep, for example sales it assists or customers it retains.",
    "time_saved": "Hours people no longer spend each month, times an hourly rate.",
    "risk_avoided": "Expected loss avoided, for example fewer errors or penalties times what each one costs.",
}
# The older value types map to a method, so every value figure can show one.
_FROM_TYPE = {
    "Cost avoidance": "cost_avoidance", "Projected cost avoidance": "cost_avoidance",
    "Revenue influenced": "revenue_influenced", "Revenue retained": "revenue_influenced",
    "Projected revenue influenced": "revenue_influenced", "Projected run-rate": "revenue_influenced",
}


def method_of(value_method: str | None, value_type: str | None, hours_saved: int | None = None) -> str | None:
    if value_method in METHODS:
        return value_method
    if value_type in _FROM_TYPE:
        return _FROM_TYPE[value_type]
    return "time_saved" if hours_saved else None


def time_saved_cents(hours_monthly: int | None, rate_cents: int | None) -> int:
    return max(int(hours_monthly or 0), 0) * max(int(rate_cents or 0), 0)


def value_state(declared_cents: int, method: str | None, latest: Mapping[str, Any] | None) -> dict:
    """What every page shows next to the value:

    none: nothing declared and nothing attested.
    declared: the owner's figure, not checked by finance.
    attested: a finance reviewer confirmed the declared figure.
    adjusted: a finance reviewer set another figure, which is the one used.
    stale: the owner changed the figure or the method after the last check, so the declared figure is shown again."""
    if latest is None:
        state = "declared" if declared_cents > 0 else "none"
        return {"state": state, "cents": declared_cents, "label": "Declared by the owner" if state == "declared" else "Not declared"}
    changed = latest["declaredCents"] != declared_cents or (latest.get("declaredMethod") or None) != (method or None)
    if changed:
        return {"state": "stale", "cents": declared_cents,
                "label": "Declared again after the last finance check: not attested"}
    if latest["status"] == "adjusted":
        return {"state": "adjusted", "cents": latest["attestedCents"], "label": "Adjusted by finance"}
    return {"state": "attested", "cents": latest["attestedCents"], "label": "Attested by finance"}


def cost_per_outcome(cost_cents: float | None, outcomes: int) -> float | None:
    """Token and hosting cost of the period per measured outcome; None when either is missing."""
    if cost_cents is None or outcomes <= 0:
        return None
    return round(cost_cents / outcomes, 2)


def whatif(tokens: Mapping[str, int], current_cents: float, prices: Iterable[Mapping[str, Any]], price_change_pct: float = 0.0) -> list[dict]:
    """The same tokens (input, output, cached) priced at each model in the price list.
    price_change_pct applies a change to every price (for example -20 for a 20% cut).
    Quality was not compared: a cheaper model may answer worse."""
    factor = 1 + price_change_pct / 100
    out = []
    for p in prices:
        cached = min(max(tokens.get("cached", 0), 0), max(tokens.get("input", 0), 0))
        dollars = ((tokens.get("input", 0) - cached) * p["input"] + cached * p.get("cached", 0)
                   + tokens.get("output", 0) * p["output"]) / 1_000_000
        cents = round(dollars * 100 * factor, 2)
        out.append({"model": p["model"], "cents": cents,
                    "changePct": round(100 * (cents - current_cents) / current_cents, 1) if current_cents else None})
    return sorted(out, key=lambda r: r["cents"])


IDLE_DAYS = 30


def idle_spend(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Production agents with no calls in the last 30 days that still cost money for hosting.
    rows: [{agentId, name, stage, callsLast30d, infraCents, infraSource, tokenCents}]"""
    out = []
    for r in rows:
        if r["stage"] != "Production" or r.get("callsLast30d") is None or r["callsLast30d"] > 0:
            continue
        cost = (r.get("infraCents") or 0) + (r.get("tokenCents") or 0)
        if cost <= 0:
            continue
        out.append({"agentId": r["agentId"], "name": r["name"], "monthlyCents": round(cost),
                    "text": f"No call in the last {IDLE_DAYS} days, but it costs about ${cost / 100:,.2f} a month "
                            f"({'metered' if r.get('infraSource') == 'metered' else 'declared or estimated'} hosting)."})
    return sorted(out, key=lambda x: -x["monthlyCents"])


def duplicate_spend(pairs: Iterable[Mapping[str, Any]], cost: Mapping[str, float]) -> list[dict]:
    """Pairs of agents that look like they do the same job while both are paid for.
    pairs: [{a: {id, name}, b: {id, name}, reason}]  cost: agentId -> monthly cents."""
    out, seen = [], set()
    for p in pairs:
        a, b = p["a"], p["b"]
        key = tuple(sorted((a["id"], b["id"])))
        if key in seen or cost.get(a["id"], 0) <= 0 or cost.get(b["id"], 0) <= 0:
            continue
        seen.add(key)
        cheaper = min((a, b), key=lambda x: cost[x["id"]])
        out.append({"agents": [a, b], "reason": p["reason"], "monthlyCents": round(cost[a["id"]] + cost[b["id"]]),
                    "possibleSavingCents": round(cost[cheaper["id"]]),
                    "text": f"{a['name']} and {b['name']} look like they do the same job ({p['reason']}), and both cost money. "
                            f"Keeping one could save about ${cost[cheaper['id']] / 100:,.2f} a month."})
    return sorted(out, key=lambda x: -x["possibleSavingCents"])


def scenario(rows: Iterable[Mapping[str, Any]], production_infra_cents: int) -> dict:
    """If these agents move to Production: the monthly value that becomes live and the
    monthly cost it brings. rows: [{agentId, name, stage, valueCents, valueState, tokenCents, infraCents, infraSource}]

    Value is the attested or declared figure. Token cost is today's run rate, which a
    larger Production load may raise. Hosting is the metered or declared figure, or the
    registry's Production estimate when there is none."""
    items = []
    for r in rows:
        if r["stage"] in ("Production", "Deprecated"):
            continue
        infra = r["infraCents"] if r.get("infraSource") in ("metered", "declared") else production_infra_cents
        items.append({"agentId": r["agentId"], "name": r["name"], "stage": r["stage"], "valueCents": r["valueCents"],
                      "valueState": r.get("valueState"), "tokenCents": round(r.get("tokenCents") or 0),
                      "infraCents": round(infra), "infraBasis": r.get("infraSource") if r.get("infraSource") in ("metered", "declared") else "estimate"})
    value = sum(i["valueCents"] for i in items)
    cost = sum(i["tokenCents"] + i["infraCents"] for i in items)
    return {"agents": items, "valueCents": value, "costCents": cost, "netCents": value - cost,
            "attestedShare": round(100 * sum(i["valueCents"] for i in items if i["valueState"] in ("attested", "adjusted")) / value) if value else None}
