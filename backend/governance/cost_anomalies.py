"""Cost anomaly rules for one agent (pure, informational only).

Input is `governance.costing.daily_series` output: one zero-filled entry per
day with cost_cents, calls, errors and a per-model breakdown. Nothing here
pauses, throttles or changes an agent.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

from governance.costing import budget_status, period_start

SPEND_SPIKE = "spend_spike"
BUDGET_THRESHOLD = "budget_threshold"
OVER_BUDGET = "over_budget"
COST_PER_CALL_JUMP = "cost_per_call_jump"
UNPRICED_MODEL = "unpriced_model"
UNDECLARED_MODEL = "undeclared_model"
ERROR_BURN = "error_burn"

ANOMALY_TYPES = (SPEND_SPIKE, BUDGET_THRESHOLD, OVER_BUDGET, COST_PER_CALL_JUMP, UNPRICED_MODEL, UNDECLARED_MODEL, ERROR_BURN)

# An event happened on a given day and stays open until a person resolves it;
# every other type is a condition that is resolved automatically once it clears.
EVENT_TYPES = frozenset({SPEND_SPIKE, ERROR_BURN})

# Spend spike: modified z-score against the trailing 28-day median
# (NIST/SEMATECH e-Handbook; Iglewicz & Hoaglin flag |M| > 3.5), combined with
# absolute and percentage impact floors as AWS Cost Anomaly Detection does.
SPIKE_MIN_HISTORY_DAYS = 14
SPIKE_BASELINE_DAYS = 28
SPIKE_Z = 3.5
SPIKE_MIN_IMPACT_CENTS = 100
SPIKE_MIN_IMPACT_PCT = 25.0

COST_PER_CALL_RATIO = 2.0
COST_PER_CALL_RECENT_DAYS = 7
COST_PER_CALL_PRIOR_DAYS = 30
ERROR_BURN_RATE = 0.10
# Below this many calls a ratio is noise, for both error rate and cost per call.
MIN_CALLS = 20
UNDECLARED_WINDOW_DAYS = 30

ANOMALY_COST_GREEN_PCT = 2.0
ANOMALY_COST_RED_PCT = 7.0

SEVERITY = {
    SPEND_SPIKE: "HIGH",
    OVER_BUDGET: "HIGH",
    BUDGET_THRESHOLD: "MEDIUM",
    COST_PER_CALL_JUMP: "MEDIUM",
    ERROR_BURN: "MEDIUM",
    UNPRICED_MODEL: "LOW",
    UNDECLARED_MODEL: "LOW",
}


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _index(series: Iterable[Mapping]) -> dict[date, Mapping]:
    return {_as_date(e["date"]): e for e in series}


def _has_usage(entry: Mapping) -> bool:
    return (entry.get("calls") or 0) > 0 or (entry.get("cost_cents") or 0) > 0


def _window(by_date: Mapping[date, Mapping], start: date, end: date) -> list[Mapping]:
    return [by_date[d] for d in by_date if start <= d <= end]


def evaluate_spike(by_date: Mapping[date, Mapping], day: date) -> dict | None:
    """The spend-spike evaluation for one day, or None when it cannot be
    evaluated (under 14 days of history, or a zero baseline, where the
    percentage impact is undefined)."""
    usage_days = [d for d, e in by_date.items() if _has_usage(e) and d < day]
    if not usage_days:
        return None
    first = min(usage_days)
    history_days = (day - first).days
    if history_days < SPIKE_MIN_HISTORY_DAYS:
        return None
    start = max(first, day - timedelta(days=SPIKE_BASELINE_DAYS))
    window = [float((by_date.get(start + timedelta(days=i)) or {}).get("cost_cents") or 0.0) for i in range((day - start).days)]
    baseline = _median(window)
    if baseline <= 0:
        return None
    mad = _median([abs(v - baseline) for v in window])
    cost = float((by_date.get(day) or {}).get("cost_cents") or 0.0)
    impact = cost - baseline
    impact_pct = impact / baseline * 100
    floors = impact >= SPIKE_MIN_IMPACT_CENTS and impact_pct >= SPIKE_MIN_IMPACT_PCT
    if mad > 0:
        z = 0.6745 * impact / mad
        flagged, method = floors and z > SPIKE_Z, "modified_z"
    else:
        z, flagged, method = None, floors, "mad_zero"
    return {
        "date": day.isoformat(),
        "cost_cents": round(cost, 4),
        "baseline_cents": round(baseline, 4),
        "impact_cents": round(impact, 4),
        "impact_pct": round(impact_pct, 1),
        "modified_z": round(z, 2) if z is not None else None,
        "method": method,
        "history_days": history_days,
        "flagged": flagged,
    }


def _evaluate_from(series: Iterable[Mapping], window_start: date) -> tuple[dict[date, Mapping], list[dict]]:
    """Evaluations for days on or after `window_start`; earlier days in the
    series serve only as history."""
    by_date = _index(series)
    evaluated = (evaluate_spike(by_date, d) for d in sorted(by_date) if d >= window_start)
    return by_date, [e for e in evaluated if e]


def spike_days(series: Iterable[Mapping], window_start: date) -> list[dict]:
    """Every flagged spend-spike day from `window_start` on."""
    return [e for e in _evaluate_from(series, window_start)[1] if e["flagged"]]


def anomaly_cost_share(series: Iterable[Mapping], window_start: date) -> dict | None:
    """FinOps Foundation 'Anomaly Cost %' from `window_start` on: spike
    impact / total spend. None when no day could be evaluated."""
    by_date, evaluated = _evaluate_from(series, window_start)
    if not evaluated:
        return None
    total = sum(float(e.get("cost_cents") or 0.0) for d, e in by_date.items() if d >= window_start)
    impact = sum(e["impact_cents"] for e in evaluated if e["flagged"])
    pct = round(impact / total * 100, 1) if total > 0 else 0.0
    band = "green" if pct < ANOMALY_COST_GREEN_PCT else "yellow" if pct <= ANOMALY_COST_RED_PCT else "red"
    return {"pct": pct, "band": band, "impact_cents": round(impact, 4), "evaluated_days": len(evaluated)}


def _error_burn(by_date: Mapping[date, Mapping], day: date) -> dict | None:
    entry = by_date.get(day) or {}
    calls, errors = entry.get("calls") or 0, entry.get("errors") or 0
    if calls < MIN_CALLS or errors / calls <= ERROR_BURN_RATE:
        return None
    return {"date": day.isoformat(), "calls": calls, "errors": errors, "error_rate_pct": round(errors / calls * 100, 1)}


def _cost_per_call(entries: list[Mapping]) -> tuple[float | None, int]:
    calls = sum(e.get("calls") or 0 for e in entries)
    if calls < MIN_CALLS:
        return None, calls
    return sum(float(e.get("cost_cents") or 0.0) for e in entries) / calls, calls


def _anomaly(anomaly_type: str, details: dict) -> dict:
    return {"anomaly_type": anomaly_type, "severity": SEVERITY[anomaly_type], "details": details}


def detect(
    daily_series: Iterable[Mapping],
    today: date,
    budget_cents: int | None,
    alert_pct: int | None,
    declared_model: str | None,
    unpriced_models: Iterable[str],
    reset_day: int = 1,
) -> list[dict]:
    """Anomalies open as of `today`. `declared_model` must already be
    normalised the same way as the series' model names. Event rules look at
    today and yesterday so a spike in yesterday's late-arriving spans is not
    missed."""
    by_date = _index(daily_series)
    found: list[dict] = []

    for anomaly_type, check in ((SPEND_SPIKE, evaluate_spike), (ERROR_BURN, _error_burn)):
        hits = [h for h in (check(by_date, d) for d in (today - timedelta(days=1), today)) if h and h.get("flagged", True)]
        if hits:
            details = {k: v for k, v in hits[-1].items() if k != "flagged"}
            found.append(_anomaly(anomaly_type, {**details, "dates": [h["date"] for h in hits]}))

    if budget_cents:
        start = period_start(today, reset_day)
        mtd = sum(float(e.get("cost_cents") or 0.0) for e in _window(by_date, start, today))
        status = budget_status(mtd, budget_cents, alert_pct or 80)
        if status["state"] in ("over_budget", "at_threshold"):
            found.append(_anomaly(
                OVER_BUDGET if status["state"] == "over_budget" else BUDGET_THRESHOLD,
                {"mtd_cents": round(mtd, 4), "budget_cents": budget_cents, "used_pct": status["used_pct"],
                 "alert_pct": alert_pct or 80, "period_start": start.isoformat()},
            ))

    recent_start = today - timedelta(days=COST_PER_CALL_RECENT_DAYS - 1)
    prior_end = recent_start - timedelta(days=1)
    recent_cpc, recent_calls = _cost_per_call(_window(by_date, recent_start, today))
    prior_cpc, prior_calls = _cost_per_call(_window(by_date, prior_end - timedelta(days=COST_PER_CALL_PRIOR_DAYS - 1), prior_end))
    if recent_cpc is not None and prior_cpc and recent_cpc > COST_PER_CALL_RATIO * prior_cpc:
        found.append(_anomaly(COST_PER_CALL_JUMP, {
            "recent_start": recent_start.isoformat(),
            "recent_cost_per_call_cents": round(recent_cpc, 6), "prior_cost_per_call_cents": round(prior_cpc, 6),
            "ratio": round(recent_cpc / prior_cpc, 2), "recent_calls": recent_calls, "prior_calls": prior_calls,
        }))

    unpriced = sorted(set(unpriced_models))
    if unpriced:
        found.append(_anomaly(UNPRICED_MODEL, {"models": unpriced}))

    declared = (declared_model or "").strip().lower()
    observed: set[str] = set()
    for entry in _window(by_date, today - timedelta(days=UNDECLARED_WINDOW_DAYS - 1), today):
        for model, stats in (entry.get("models") or {}).items():
            if model != "unknown" and ((stats.get("calls") or 0) > 0 or (stats.get("tokens") or 0) > 0):
                observed.add(model)
    undeclared = sorted(m for m in observed if m != declared)
    if undeclared:
        found.append(_anomaly(UNDECLARED_MODEL, {"declared_model": declared or None, "models": undeclared}))

    return found


def same_episode(anomaly_type: str, previous: Mapping | None, current: Mapping) -> bool:
    """Whether `current` is the occurrence a person already reviewed and
    resolved as `previous`, so it must not be reopened."""
    previous = previous or {}
    if anomaly_type in EVENT_TYPES:
        return bool(set(previous.get("dates") or []) & set(current.get("dates") or []))
    if anomaly_type in (BUDGET_THRESHOLD, OVER_BUDGET):
        return previous.get("period_start") is not None and previous.get("period_start") == current.get("period_start")
    if anomaly_type in (UNPRICED_MODEL, UNDECLARED_MODEL):
        return bool(previous.get("models")) and set(current.get("models") or []) <= set(previous["models"])
    if anomaly_type == COST_PER_CALL_JUMP:
        if not previous.get("recent_start") or not current.get("recent_start"):
            return False
        gap = abs((_as_date(current["recent_start"]) - _as_date(previous["recent_start"])).days)
        return gap < COST_PER_CALL_RECENT_DAYS
    return False


def reconcile(found: Iterable[Mapping], open_rows: Iterable[Mapping], person_resolved: Mapping[str, Mapping]) -> dict:
    """Plan the stored-row changes for one agent.

    `open_rows` are its unresolved rows of the types above ({id,
    anomaly_type}), newest first; `person_resolved` maps a type to the details
    of the newest row a person resolved. Returns {create: [anomaly],
    update: [(row_id, anomaly)], resolve: [row_id]}: one open row per type,
    conditions that cleared are resolved, events stay open for a person."""
    open_by_type: dict[str, str] = {}
    duplicates: list[str] = []
    for row in open_rows:
        if row["anomaly_type"] in open_by_type:
            duplicates.append(row["id"])
        else:
            open_by_type[row["anomaly_type"]] = row["id"]
    plan: dict = {"create": [], "update": [], "resolve": duplicates}
    found_types = set()
    for anomaly in found:
        kind = anomaly["anomaly_type"]
        found_types.add(kind)
        if kind in open_by_type:
            plan["update"].append((open_by_type[kind], anomaly))
        elif not (kind in person_resolved and same_episode(kind, person_resolved[kind], anomaly["details"])):
            plan["create"].append(anomaly)
    plan["resolve"] += [rid for kind, rid in open_by_type.items() if kind not in found_types and kind not in EVENT_TYPES]
    return plan
