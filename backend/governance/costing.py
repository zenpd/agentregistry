"""The one cost engine: every cost figure on the agent page comes from here.

Pure functions over plain dicts — no DB or HTTP — so they are unit-tested
without touching the live database.

Usage row shape (one per agent × day × model):
    {"day": date, "model": str, "input_tokens": int, "output_tokens": int,
     "cached_tokens": int, "calls": int, "runs": int, "errors": int,
     "source": "phoenix" | "seed"}
`input_tokens` is the full prompt count and already includes
`cached_tokens` (the cache-read subset billed at the cached rate).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Price:
    model: str
    input_per_1m: float
    output_per_1m: float
    cached_per_1m: float


def normalize_model(raw: str | None, aliases: Mapping[str, str]) -> str:
    name = (raw or "").strip().lower()
    return aliases.get(name, name)


def token_cost_cents(input_tokens: int, output_tokens: int, cached_tokens: int, price: Price) -> float:
    cached = min(max(cached_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens, 0) - cached
    dollars = (
        uncached * price.input_per_1m
        + cached * price.cached_per_1m
        + max(output_tokens, 0) * price.output_per_1m
    ) / 1_000_000
    return dollars * 100


def effective_rows(rows: Iterable[Mapping]) -> tuple[list[Mapping], str]:
    """Real (phoenix) rows win: seed rows are dropped once any real row exists.
    Returns (rows, source) where source is 'phoenix', 'seed' or 'none'."""
    rows = list(rows)
    real = [r for r in rows if r.get("source") == "phoenix"]
    if real:
        return real, "phoenix"
    if rows:
        return rows, "seed"
    return [], "none"


def price_rows(rows: Iterable[Mapping], prices: Mapping[str, Price], aliases: Mapping[str, str]) -> tuple[list[dict], list[str]]:
    """Attach cost_cents and the normalised model to each row.
    Returns (priced_rows, unpriced_models)."""
    out, unpriced = [], set()
    for r in rows:
        model = normalize_model(r.get("model"), aliases)
        price = prices.get(model)
        cost = token_cost_cents(r.get("input_tokens", 0), r.get("output_tokens", 0), r.get("cached_tokens", 0), price) if price else 0.0
        if price is None:
            unpriced.add(model or "unknown")
        out.append({**r, "model": model, "cost_cents": cost, "priced": price is not None})
    return out, sorted(unpriced)


def daily_series(rows: Iterable[Mapping], start: date, end: date) -> list[dict]:
    """One entry per day in [start, end], zero-filled."""
    by_day: dict[date, dict] = {}
    for r in rows:
        d = r["day"]
        if d < start or d > end:
            continue
        agg = by_day.setdefault(d, {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "calls": 0, "runs": 0, "errors": 0, "cost_cents": 0.0, "models": {}})
        for k in ("input_tokens", "output_tokens", "cached_tokens", "calls", "runs", "errors"):
            agg[k] += r.get(k, 0) or 0
        agg["cost_cents"] += r.get("cost_cents", 0.0)
        m = agg["models"].setdefault(r.get("model") or "unknown", {"tokens": 0, "cost_cents": 0.0, "calls": 0})
        m["tokens"] += (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
        m["cost_cents"] += r.get("cost_cents", 0.0)
        m["calls"] += r.get("calls", 0) or 0
    series = []
    d = start
    while d <= end:
        agg = by_day.get(d) or {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "calls": 0, "runs": 0, "errors": 0, "cost_cents": 0.0, "models": {}}
        series.append({"date": d.isoformat(), **{k: (round(v, 4) if k == "cost_cents" else v) for k, v in agg.items()}})
        d += timedelta(days=1)
    return series


def by_model(rows: Iterable[Mapping]) -> list[dict]:
    agg: dict[str, dict] = {}
    for r in rows:
        m = agg.setdefault(r.get("model") or "unknown", {"model": r.get("model") or "unknown", "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "calls": 0, "cost_cents": 0.0, "priced": True})
        for k in ("input_tokens", "output_tokens", "cached_tokens", "calls"):
            m[k] += r.get(k, 0) or 0
        m["cost_cents"] += r.get("cost_cents", 0.0)
        m["priced"] = m["priced"] and r.get("priced", True)
    total = sum(m["cost_cents"] for m in agg.values()) or 0.0
    out = sorted(agg.values(), key=lambda m: m["cost_cents"], reverse=True)
    for m in out:
        m["cost_cents"] = round(m["cost_cents"], 4)
        m["share_pct"] = round(m["cost_cents"] / total * 100, 1) if total else 0.0
    return out


def period_start(today: date, reset_day: int = 1) -> date:
    """Start of the current budget period given a reset day (1–28)."""
    reset_day = min(max(reset_day or 1, 1), 28)
    if today.day >= reset_day:
        return today.replace(day=reset_day)
    prev_month_end = today.replace(day=1) - timedelta(days=1)
    return prev_month_end.replace(day=reset_day)


def period_end(start: date) -> date:
    """Last day of the budget period that begins on `start`."""
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    return start + timedelta(days=days_in_month - 1)


def month_to_date_cents(rows: Iterable[Mapping], today: date, reset_day: int = 1) -> float:
    start = period_start(today, reset_day)
    return sum(r.get("cost_cents", 0.0) for r in rows if start <= r["day"] <= today)


def trailing_daily_avg_cents(rows: Iterable[Mapping], today: date, days: int) -> float:
    start = today - timedelta(days=days - 1)
    total = sum(r.get("cost_cents", 0.0) for r in rows if start <= r["day"] <= today)
    return total / days


def projected_period_end_cents(rows: list[Mapping], today: date, reset_day: int = 1) -> float:
    """Month-to-date + trailing 14-day daily average × days left in the period."""
    start = period_start(today, reset_day)
    end = period_end(start)
    days_left = max((end - today).days, 0)
    return month_to_date_cents(rows, today, reset_day) + trailing_daily_avg_cents(rows, today, 14) * days_left


def forecast_monthly_cents(rows: list[Mapping], today: date, months: int = 3, min_days: int = 7) -> dict:
    """Linear trend over the trailing 30 days of daily cost, projected forward
    as 30-day months. Returns status 'insufficient_data' with fewer than
    `min_days` days that have any usage."""
    start = today - timedelta(days=29)
    daily: dict[date, float] = {}
    for r in rows:
        if start <= r["day"] <= today:
            daily[r["day"]] = daily.get(r["day"], 0.0) + r.get("cost_cents", 0.0)
    if len([v for v in daily.values() if v > 0]) < min_days:
        return {"status": "insufficient_data", "days_with_usage": len([v for v in daily.values() if v > 0]), "months": []}
    xs = list(range(30))
    ys = [daily.get(start + timedelta(days=i), 0.0) for i in xs]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var_x if var_x else 0.0
    intercept = mean_y - slope * mean_x
    out = []
    for m in range(1, months + 1):
        first = 30 + 30 * (m - 1)
        total = sum(max(intercept + slope * (first + i), 0.0) for i in range(30))
        out.append({"month": m, "projected_cents": round(total, 2)})
    return {"status": "ok", "daily_slope_cents": round(slope, 4), "months": out}


def budget_status(mtd_cents: float, budget_cents: int | None, alert_pct: int = 80) -> dict:
    """Informational only — the registry never enforces a budget."""
    if not budget_cents:
        return {"state": "no_budget", "used_pct": None}
    used = mtd_cents / budget_cents * 100
    state = "over_budget" if used >= 100 else "at_threshold" if used >= alert_pct else "on_track"
    return {"state": state, "used_pct": round(used, 1)}


def cost_per_call_cents(rows: Iterable[Mapping]) -> float | None:
    rows = list(rows)
    calls = sum(r.get("calls", 0) or 0 for r in rows)
    if not calls:
        return None
    return sum(r.get("cost_cents", 0.0) for r in rows) / calls
