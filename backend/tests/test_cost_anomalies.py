"""governance/cost_anomalies.py (pure) and orchestrations/cost_rollup.py
(against a temp DB)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.base import Base, engine, get_db_session
from db.models import (
    Agent, AgentBudget, AgentMetric, AgentTokenUsage, AuditLog, CostAnomaly, ModelTokenPrice, Organization,
)
from governance import cost_anomalies as ca
from orchestrations import cost_rollup
from shared.config import get_settings

TODAY = date(2026, 9, 18)


def series(costs: dict[int, float], calls: dict[int, int] | None = None, errors: dict[int, int] | None = None,
           models: dict[int, dict] | None = None, days: int = 60) -> list[dict]:
    """Zero-filled daily series; keys are days before TODAY (0 = today)."""
    calls, errors, models = calls or {}, errors or {}, models or {}
    out = []
    for back in range(days - 1, -1, -1):
        out.append({
            "date": (TODAY - timedelta(days=back)).isoformat(),
            "cost_cents": costs.get(back, 0.0),
            "calls": calls.get(back, 0),
            "errors": errors.get(back, 0),
            "models": models.get(back, {}),
        })
    return out


def steady(days: int, low: float = 100.0, high: float = 110.0) -> dict[int, float]:
    """Alternating daily costs for `days` days before today (not today)."""
    return {back: (low if back % 2 else high) for back in range(1, days + 1)}


def types(found):
    return [a["anomaly_type"] for a in found]


def detect(daily, budget=None, alert=None, declared=None, unpriced=(), reset_day=1):
    return ca.detect(daily, TODAY, budget, alert, declared, unpriced, reset_day=reset_day)


# ── Spend spike (modified z-score against the trailing median) ───────────────

def test_spend_spike_flags_a_large_jump_with_enough_history():
    found = detect(series({**steady(20), 0: 1000.0}))
    assert types(found) == [ca.SPEND_SPIKE]
    spike = found[0]
    assert spike["severity"] == "HIGH"
    assert spike["details"]["dates"] == [TODAY.isoformat()]
    assert spike["details"]["baseline_cents"] == 105.0
    assert spike["details"]["method"] == "modified_z"
    assert spike["details"]["modified_z"] > ca.SPIKE_Z


def test_spend_spike_needs_fourteen_days_of_history():
    assert detect(series({**steady(10), 0: 1000.0})) == []


def test_spend_spike_needs_a_dollar_of_impact():
    assert detect(series({**steady(20, 10.0, 11.0), 0: 90.0})) == []


def test_spend_spike_needs_25_percent_impact():
    # A $1.10 rise on a $10 baseline is only 11%.
    assert detect(series({**steady(20, 1000.0, 1000.0), 1: 999.0, 2: 1001.0, 0: 1110.0})) == []


def test_spend_spike_with_zero_spread_uses_the_floors_alone():
    found = detect(series({**steady(20, 200.0, 200.0), 0: 400.0}))
    assert types(found) == [ca.SPEND_SPIKE]
    assert found[0]["details"]["method"] == "mad_zero"


def test_spend_spike_on_yesterday_is_still_reported_today():
    found = detect(series({**steady(20), 1: 1000.0}))
    assert types(found) == [ca.SPEND_SPIKE]
    assert found[0]["details"]["dates"] == [(TODAY - timedelta(days=1)).isoformat()]


def test_zero_baseline_is_not_evaluated():
    daily = series({15: 50.0, 0: 5000.0})
    assert detect(daily) == []
    assert ca.anomaly_cost_share(daily, TODAY - timedelta(days=5)) is None


# ── Budget ───────────────────────────────────────────────────────────────────

def test_budget_threshold_and_over_budget():
    daily = series({back: 100.0 for back in range(0, 18)})  # $1/day since Sept 1 → 1,800¢ MTD
    assert types(detect(daily, budget=5000, alert=80)) == []
    at = detect(daily, budget=2000, alert=80)
    assert types(at) == [ca.BUDGET_THRESHOLD] and at[0]["severity"] == "MEDIUM"
    assert at[0]["details"]["period_start"] == "2026-09-01" and at[0]["details"]["used_pct"] == 90.0
    over = detect(daily, budget=1500, alert=80)
    assert types(over) == [ca.OVER_BUDGET] and over[0]["severity"] == "HIGH"
    assert types(detect(daily, budget=None)) == []
    assert types(detect(daily, budget=2000, alert=80, reset_day=10)) == []  # 900¢ since Sept 10


# ── Cost per call, error burn, models ────────────────────────────────────────

def test_cost_per_call_jump():
    prior = {back: 100.0 for back in range(7, 37)}
    prior_calls = {back: 10 for back in range(7, 37)}
    recent = {back: 300.0 for back in range(0, 7)}
    recent_calls = {back: 10 for back in range(0, 7)}
    found = detect(series({**prior, **recent}, calls={**prior_calls, **recent_calls}))
    jump = [a for a in found if a["anomaly_type"] == ca.COST_PER_CALL_JUMP]
    assert jump and jump[0]["details"]["ratio"] == 3.0
    assert jump[0]["details"]["recent_start"] == (TODAY - timedelta(days=6)).isoformat()


def test_cost_per_call_needs_enough_calls():
    found = detect(series({7: 10.0, 0: 100.0}, calls={7: 5, 0: 5}))
    assert ca.COST_PER_CALL_JUMP not in types(found)


@pytest.mark.parametrize("calls,errors,flagged", [(25, 5, True), (25, 2, False), (19, 10, False), (20, 3, True)])
def test_error_burn(calls, errors, flagged):
    found = detect(series({}, calls={0: calls}, errors={0: errors}))
    assert (ca.ERROR_BURN in types(found)) is flagged


def test_unpriced_and_undeclared_models():
    models = {0: {"gpt-4.1-mini": {"calls": 3, "tokens": 10}, "gpt-4o": {"calls": 1, "tokens": 5},
                  "unknown": {"calls": 1, "tokens": 1}}}
    found = detect(series({}, models=models), declared="gpt-4.1-mini", unpriced=["mystery", "mystery"])
    by_type = {a["anomaly_type"]: a for a in found}
    assert by_type[ca.UNPRICED_MODEL]["details"]["models"] == ["mystery"]
    assert by_type[ca.UNDECLARED_MODEL]["details"] == {"declared_model": "gpt-4.1-mini", "models": ["gpt-4o"]}
    assert all(a["severity"] == "LOW" for a in found)
    assert ca.UNDECLARED_MODEL not in types(detect(series({}, models={0: {"gpt-4.1-mini": {"calls": 1}}}),
                                                   declared="gpt-4.1-mini"))


def test_anomaly_cost_share_bands():
    daily = series({**steady(30), 0: 1000.0})
    share = ca.anomaly_cost_share(daily, TODAY - timedelta(days=9))
    assert share["band"] == "red" and share["pct"] > ca.ANOMALY_COST_RED_PCT
    calm = ca.anomaly_cost_share(series(steady(30)), TODAY - timedelta(days=9))
    assert calm == {"pct": 0.0, "band": "green", "impact_cents": 0.0, "evaluated_days": 10}


# ── Episodes and reconcile ───────────────────────────────────────────────────

def test_same_episode():
    assert ca.same_episode(ca.SPEND_SPIKE, {"dates": ["2026-09-17"]}, {"dates": ["2026-09-17", "2026-09-18"]})
    assert not ca.same_episode(ca.SPEND_SPIKE, {"dates": ["2026-09-10"]}, {"dates": ["2026-09-18"]})
    assert ca.same_episode(ca.BUDGET_THRESHOLD, {"period_start": "2026-09-01"}, {"period_start": "2026-09-01"})
    assert not ca.same_episode(ca.OVER_BUDGET, {"period_start": "2026-08-01"}, {"period_start": "2026-09-01"})
    assert ca.same_episode(ca.UNPRICED_MODEL, {"models": ["a", "b"]}, {"models": ["a"]})
    assert not ca.same_episode(ca.UNDECLARED_MODEL, {"models": ["a"]}, {"models": ["a", "c"]})
    assert ca.same_episode(ca.COST_PER_CALL_JUMP, {"recent_start": "2026-09-10"}, {"recent_start": "2026-09-12"})
    assert not ca.same_episode(ca.COST_PER_CALL_JUMP, {"recent_start": "2026-09-01"}, {"recent_start": "2026-09-12"})
    assert not ca.same_episode(ca.BUDGET_THRESHOLD, None, {"period_start": "2026-09-01"})


def test_reconcile_updates_creates_and_resolves():
    found = [
        {"anomaly_type": ca.BUDGET_THRESHOLD, "severity": "MEDIUM", "details": {"period_start": "2026-09-01"}},
        {"anomaly_type": ca.UNPRICED_MODEL, "severity": "LOW", "details": {"models": ["x"]}},
        {"anomaly_type": ca.UNDECLARED_MODEL, "severity": "LOW", "details": {"models": ["y"]}},
    ]
    open_rows = [
        {"id": "b1", "anomaly_type": ca.BUDGET_THRESHOLD},
        {"id": "b0", "anomaly_type": ca.BUDGET_THRESHOLD},       # older duplicate
        {"id": "e1", "anomaly_type": ca.ERROR_BURN},             # event: stays open
        {"id": "c1", "anomaly_type": ca.COST_PER_CALL_JUMP},     # condition cleared
    ]
    person_resolved = {ca.UNPRICED_MODEL: {"models": ["x"]}, ca.UNDECLARED_MODEL: {"models": ["z"]}}
    plan = ca.reconcile(found, open_rows, person_resolved)
    assert [rid for rid, _ in plan["update"]] == ["b1"]
    assert [a["anomaly_type"] for a in plan["create"]] == [ca.UNDECLARED_MODEL]
    assert sorted(plan["resolve"]) == ["b0", "c1"]


# ── Rollup against a temp DB ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db(monkeypatch):
    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    import db.models  # noqa: F401

    now = datetime.combine(TODAY, time(9, 30), tzinfo=timezone.utc)
    monkeypatch.setattr(cost_rollup, "_utcnow", lambda: now)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="real", org_id="org-default", name="Real", slug="real", owner="o", model_name="GPT-4.1-mini"))
            s.add(Agent(id="demo", org_id="org-default", name="Demo", slug="demo", owner="o", model_name="GPT-5"))
            s.add(ModelTokenPrice(id="p1", model_name="gpt-4.1-mini", provider="azure-openai", input_price_per_1m=0.40,
                                  output_price_per_1m=1.60, cache_read_price_per_1m=0.10, tier="lightweight"))
            s.add(AgentBudget(agent_id="real", monthly_budget_cents=100, alert_threshold_pct=80, budget_reset_day=1))
            s.add(AgentTokenUsage(agent_id="demo", bucket=datetime(2026, 9, 3, 2, 28), model_name="GPT-5",
                                  invocation_count=10, input_tokens=100, source="seed"))
            for back, model, calls, errors in [(1, "gpt-4.1-mini", 10, 1), (0, "gpt-4.1-mini", 30, 0), (0, "mystery", 2, 0)]:
                s.add(AgentTokenUsage(
                    agent_id="real", bucket=datetime.combine(TODAY - timedelta(days=back), time.min), model_name=model,
                    invocation_count=calls, error_count=errors, input_tokens=1_000_000 * calls, output_tokens=0,
                    cached_tokens=0, source="phoenix", run_count=calls,
                ))
        yield
    finally:
        await engine.dispose()


async def _all(model, **where):
    async with get_db_session() as s:
        stmt = select(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        return list((await s.execute(stmt)).scalars().all())


@pytest.mark.asyncio
async def test_rollup_writes_metrics_and_anomalies_and_skips_demo_data(db):
    result = await cost_rollup.rollup_costs()
    assert result["status"] == "ok"
    assert (result["agents_rolled_up"], result["agents_skipped"], result["metrics_upserted"]) == (1, 1, 2)

    metrics = {m.metric_date: m for m in await _all(AgentMetric, agent_id="real")}
    today = metrics[TODAY]
    assert today.id == f"real-{TODAY.isoformat()}"
    assert today.total_cost == pytest.approx(12.0)          # 30M input tokens × $0.40
    assert today.avg_tokens == pytest.approx(1_000_000.0)
    assert today.error_rate == 0 and today.efficiency == 1
    assert metrics[TODAY - timedelta(days=1)].error_rate == pytest.approx(0.1)
    assert await _all(AgentMetric, agent_id="demo") == []

    open_types = sorted(a.anomaly_type for a in await _all(CostAnomaly, agent_id="real") if a.resolved_at is None)
    assert open_types == [ca.OVER_BUDGET, ca.UNDECLARED_MODEL, ca.UNPRICED_MODEL]
    assert {a.action for a in await _all(AuditLog)} == {"cost_anomaly.open"}


@pytest.mark.asyncio
async def test_rollup_is_idempotent_and_auto_resolves_cleared_conditions(db):
    await cost_rollup.rollup_costs(agent_id="real")
    second = await cost_rollup.rollup_costs(agent_id="real")
    assert (second["anomalies_opened"], second["anomalies_updated"]) == (0, 3)
    assert len(await _all(AgentMetric, agent_id="real")) == 2

    async with get_db_session() as s:
        budget = await s.get(AgentBudget, "real")
        budget.monthly_budget_cents = 1_000_000
    third = await cost_rollup.rollup_costs(agent_id="real")
    assert third["anomalies_resolved"] == 1
    over = (await _all(CostAnomaly, anomaly_type=ca.OVER_BUDGET))[0]
    assert over.resolved_at is not None and over.resolved_by == "auto"


@pytest.mark.asyncio
async def test_rollup_does_not_reopen_what_a_person_resolved(db):
    await cost_rollup.rollup_costs(agent_id="real")
    async with get_db_session() as s:
        row = (await s.execute(select(CostAnomaly).where(CostAnomaly.anomaly_type == ca.UNPRICED_MODEL))).scalar_one()
        row.resolved_at = datetime.now(timezone.utc)
    again = await cost_rollup.rollup_costs(agent_id="real")
    assert again["anomalies_opened"] == 0
    assert [a.resolved_at is not None for a in await _all(CostAnomaly, anomaly_type=ca.UNPRICED_MODEL)] == [True]


@pytest.mark.asyncio
async def test_rollup_single_agent_statuses(db):
    demo = await cost_rollup.rollup_costs(agent_id="demo")
    assert demo["status"] == "skipped" and "demo" in demo["reason"]
    assert (await cost_rollup.rollup_costs(agent_id="missing"))["status"] == "error"
