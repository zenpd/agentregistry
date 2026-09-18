"""governance/costing.py — the one cost engine (pure, no DB)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from governance.costing import (
    Price, budget_status, by_model, cost_per_call_cents, daily_series, effective_rows,
    forecast_monthly_cents, month_to_date_cents, normalize_model, period_end, period_start,
    price_rows, projected_period_end_cents, token_cost_cents, trailing_daily_avg_cents,
)

MINI = Price("gpt-4.1-mini", 0.40, 1.60, 0.10)
PRICES = {"gpt-4.1-mini": MINI, "gpt-4.1": Price("gpt-4.1", 2.00, 8.00, 0.50)}
ALIASES = {"gpt-4.1-mini-2025-04-14": "gpt-4.1-mini"}


def _row(day, model="gpt-4.1-mini", source="phoenix", cost=None, **counts):
    row = {"day": day, "model": model, "source": source, "input_tokens": 0, "output_tokens": 0,
           "cached_tokens": 0, "calls": 0, "runs": 0, "errors": 0, **counts}
    if cost is not None:
        row["cost_cents"] = cost
    return row


# ── normalize_model / token_cost_cents ───────────────────────────────────────

def test_normalize_model_lowercases_and_applies_alias():
    assert normalize_model("  GPT-4.1-mini ", ALIASES) == "gpt-4.1-mini"
    assert normalize_model("gpt-4.1-mini-2025-04-14", ALIASES) == "gpt-4.1-mini"
    assert normalize_model("GPT-4.1-MINI-2025-04-14", ALIASES) == "gpt-4.1-mini"
    assert normalize_model("unknown-model", ALIASES) == "unknown-model"
    assert normalize_model(None, ALIASES) == ""


def test_token_cost_prices_cached_share_at_cached_rate():
    # 3,000 prompt tokens of which 2,048 were cache reads, 400 completion:
    # 952 × $0.40 + 2,048 × $0.10 + 400 × $1.60 per 1M = $0.0012256.
    assert token_cost_cents(3000, 400, 2048, MINI) == pytest.approx(0.12256)


def test_token_cost_clamps_bad_counts():
    # More cached than prompt tokens cannot happen; treat all input as cached.
    assert token_cost_cents(100, 0, 500, MINI) == pytest.approx(100 * 0.10 / 1_000_000 * 100)
    assert token_cost_cents(-5, -5, -5, MINI) == 0
    assert token_cost_cents(1_000_000, 1_000_000, 0, MINI) == pytest.approx(200.0)


# ── effective_rows / price_rows ──────────────────────────────────────────────

def test_effective_rows_prefers_phoenix_over_seed():
    d = date(2026, 9, 1)
    seed, real = _row(d, source="seed", calls=5), _row(d, source="phoenix", calls=2)
    assert effective_rows([seed, real]) == ([real], "phoenix")
    assert effective_rows([seed]) == ([seed], "seed")
    assert effective_rows([]) == ([], "none")


def test_price_rows_attaches_cost_and_lists_unpriced_models():
    d = date(2026, 9, 1)
    rows = [
        _row(d, model="gpt-4.1-mini-2025-04-14", input_tokens=1_000_000, calls=1),
        _row(d, model="mystery-llm", input_tokens=1_000_000, calls=1),
    ]
    priced, unpriced = price_rows(rows, PRICES, ALIASES)
    assert priced[0]["model"] == "gpt-4.1-mini"
    assert priced[0]["cost_cents"] == pytest.approx(40.0)
    assert priced[0]["priced"] is True
    assert priced[1]["cost_cents"] == 0.0 and priced[1]["priced"] is False
    assert unpriced == ["mystery-llm"]


# ── daily_series / by_model ──────────────────────────────────────────────────

def test_daily_series_zero_fills_and_sums_per_day():
    start = date(2026, 9, 1)
    rows = [
        _row(start, cost=1.5, calls=2, input_tokens=10, output_tokens=5, errors=1),
        _row(start, model="gpt-4.1", cost=0.5, calls=1, input_tokens=3),
        _row(start + timedelta(days=2), cost=2.0, calls=4),
        _row(start - timedelta(days=1), cost=99.0, calls=9),  # outside the window
    ]
    series = daily_series(rows, start, start + timedelta(days=2))
    assert [e["date"] for e in series] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    first = series[0]
    assert (first["calls"], first["errors"], first["cost_cents"]) == (3, 1, 2.0)
    assert first["models"]["gpt-4.1-mini"] == {"tokens": 15, "cost_cents": 1.5, "calls": 2}
    assert series[1]["calls"] == 0 and series[1]["cost_cents"] == 0.0 and series[1]["models"] == {}
    assert series[2]["cost_cents"] == 2.0


def test_by_model_sorts_by_cost_with_share_and_priced_flag():
    d = date(2026, 9, 1)
    rows = [
        {**_row(d, cost=3.0, calls=3), "priced": True},
        {**_row(d, model="gpt-4.1", cost=1.0, calls=1), "priced": True},
        {**_row(d, model="mystery", cost=0.0, calls=2), "priced": False},
    ]
    out = by_model(rows)
    assert [m["model"] for m in out] == ["gpt-4.1-mini", "gpt-4.1", "mystery"]
    assert [m["share_pct"] for m in out] == [75.0, 25.0, 0.0]
    assert out[2]["priced"] is False


# ── budget periods ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("today,reset,expected", [
    (date(2026, 9, 18), 1, date(2026, 9, 1)),
    (date(2026, 9, 18), 15, date(2026, 9, 15)),
    (date(2026, 9, 10), 15, date(2026, 8, 15)),
    (date(2026, 1, 5), 10, date(2025, 12, 10)),   # year rollover
    (date(2026, 3, 30), 31, date(2026, 3, 28)),   # reset day clamps to 28
    (date(2026, 3, 5), 0, date(2026, 3, 1)),      # 0/None means the 1st
])
def test_period_start(today, reset, expected):
    assert period_start(today, reset) == expected


def test_period_end_is_one_month_later():
    assert period_end(date(2026, 9, 1)) == date(2026, 9, 30)
    assert period_end(date(2026, 2, 15)) == date(2026, 3, 14)


def test_month_to_date_counts_only_the_current_period():
    today = date(2026, 9, 18)
    rows = [_row(date(2026, 8, 31), cost=50.0), _row(date(2026, 9, 1), cost=10.0), _row(today, cost=5.0)]
    assert month_to_date_cents(rows, today) == 15.0
    assert month_to_date_cents(rows, today, reset_day=15) == 5.0


def test_projected_period_end_adds_trailing_average_for_days_left():
    today = date(2026, 9, 16)
    rows = [_row(today - timedelta(days=i), cost=14.0) for i in range(14)]  # 14 days × 14¢
    assert trailing_daily_avg_cents(rows, today, 14) == 14.0
    mtd = 14.0 * 14   # Sept 3..16
    assert projected_period_end_cents(rows, today) == pytest.approx(mtd + 14.0 * 14)  # 14 days left


# ── forecast / budget status / cost per call ─────────────────────────────────

def test_forecast_needs_min_days_with_usage():
    today = date(2026, 9, 18)
    rows = [_row(today - timedelta(days=i), cost=10.0) for i in range(3)]
    result = forecast_monthly_cents(rows, today)
    assert result == {"status": "insufficient_data", "days_with_usage": 3, "months": []}


def test_forecast_flat_usage_projects_thirty_days_of_the_daily_cost():
    today = date(2026, 9, 18)
    rows = [_row(today - timedelta(days=i), cost=10.0) for i in range(30)]
    result = forecast_monthly_cents(rows, today, months=2)
    assert result["status"] == "ok"
    assert result["daily_slope_cents"] == pytest.approx(0.0)
    assert [m["projected_cents"] for m in result["months"]] == [pytest.approx(300.0), pytest.approx(300.0)]


def test_forecast_follows_a_rising_trend_and_never_goes_negative():
    today = date(2026, 9, 18)
    rising = [_row(today - timedelta(days=29 - i), cost=float(i)) for i in range(30)]
    months = forecast_monthly_cents(rising, today, months=2)["months"]
    assert months[1]["projected_cents"] > months[0]["projected_cents"] > sum(range(30))
    falling = [_row(today - timedelta(days=29 - i), cost=float(29 - i)) for i in range(30)]
    assert all(m["projected_cents"] >= 0 for m in forecast_monthly_cents(falling, today, months=3)["months"])


@pytest.mark.parametrize("mtd,budget,alert,state,used", [
    (10.0, None, 80, "no_budget", None),
    (10.0, 0, 80, "no_budget", None),
    (50.0, 100, 80, "on_track", 50.0),
    (80.0, 100, 80, "at_threshold", 80.0),
    (100.0, 100, 80, "over_budget", 100.0),
    (60.0, 100, 50, "at_threshold", 60.0),
])
def test_budget_status(mtd, budget, alert, state, used):
    assert budget_status(mtd, budget, alert) == {"state": state, "used_pct": used}


def test_cost_per_call():
    d = date(2026, 9, 1)
    assert cost_per_call_cents([]) is None
    assert cost_per_call_cents([_row(d, cost=5.0, calls=0)]) is None
    assert cost_per_call_cents([_row(d, cost=6.0, calls=2), _row(d, cost=3.0, calls=1)]) == 3.0
