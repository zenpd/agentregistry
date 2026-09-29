"""Agent page — Tokenomics tab API: Phoenix-derived usage and cost, budget
(informational only), forecast, cost anomalies and model aliases.

Also overrides the older per-agent usage/cost/budget endpoints in
registry.py with values from the one cost engine (governance/costing.py),
keeping their response keys and adding "source".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_admin, require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentBudget, AgentTokenUsage, CostAnomaly, JobRun, ModelAlias
from governance.cost_anomalies import anomaly_cost_share, spike_days
from governance.costing import (
    budget_status, by_model, cost_per_call_cents, daily_series, forecast_monthly_cents,
    month_to_date_cents, normalize_model, period_end, period_start, projected_period_end_cents,
)
from orchestrations import job_runner
from services.audit import log_audit_event
from services.usage_repo import load_aliases, load_prices, priced_usage

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Tokenomics"])

FORECAST_MIN_DAYS = 7
SPIKE_BASELINE_DAYS = 28
BUDGET_NOTE = "Informational only — the registry never pauses or stops an agent."
FORECAST_METHOD = "Linear trend of the last 30 days of daily cost"
_TOTAL_KEYS = ("input_tokens", "output_tokens", "cached_tokens", "calls", "runs", "errors")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(p.title() for p in rest)


def _cents(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


async def _load(agent_id: str) -> tuple[Agent, dict, AgentBudget | None]:
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        usage = await priced_usage(db, agent_id)
        budget = await db.get(AgentBudget, agent_id)
    return agent, usage, budget


def _window(rows: list[dict], today: date, days: int) -> list[dict]:
    start = today - timedelta(days=days - 1)
    return [r for r in rows if start <= r["day"] <= today]


def _cost_known(rows: list[dict]) -> bool:
    """Whether a cost can be stated for these rows. No rows means no calls,
    which really did cost nothing; rows that all ran on a model with no price
    mean the cost is unknown, and a $0 there would be a lie."""
    return not rows or any(r.get("priced", True) for r in rows)


def _totals(rows: list[dict], has_data: bool) -> dict:
    """Cost is None without usage data, and also when nothing is priced, so
    it never reads as a real $0."""
    out = {_camel(k): sum(r.get(k, 0) or 0 for r in rows) for k in _TOTAL_KEYS}
    out["costCents"] = _cents(sum(r.get("cost_cents", 0.0) for r in rows)) if has_data and _cost_known(rows) else None
    return out


def _cost_per_call(rows: list[dict]) -> float | None:
    return _cents(cost_per_call_cents(rows)) if _cost_known(rows) else None


def _iso_utc(value: str | None) -> str | None:
    # usage_repo returns SQLite's naive timestamps; every stored value is UTC.
    return job_runner.as_utc(datetime.fromisoformat(value)).isoformat() if value else None


def _budget_view(budget: AgentBudget | None, rows: list[dict], today: date, has_data: bool) -> dict:
    """Spend figures are None when there is no usage data at all, so an
    agent without data never shows as $0 spent."""
    cents = (budget.monthly_budget_cents or 0) if budget else 0
    alert = (budget.alert_threshold_pct or 80) if budget else 80
    reset = min(max((budget.budget_reset_day or 1) if budget else 1, 1), 28)
    start = period_start(today, reset)
    view = {
        "monthlyBudgetCents": cents,
        "alertThresholdPct": alert,
        "budgetResetDay": reset,
        "state": "no_budget" if not cents else "no_data",
        "usedPct": None,
        "periodStart": start.isoformat(),
        "periodEnd": period_end(start).isoformat(),
        "monthToDateCents": None,
        "projectedPeriodEndCents": None,
        "projectedOverBudget": False,
        "note": BUDGET_NOTE,
    }
    if has_data and _cost_known(rows):
        mtd = month_to_date_cents(rows, today, reset)
        projected = projected_period_end_cents(rows, today, reset)
        status = budget_status(mtd, cents, alert)
        view.update(state=status["state"], usedPct=status["used_pct"], monthToDateCents=_cents(mtd),
                    projectedPeriodEndCents=_cents(projected), projectedOverBudget=bool(cents) and projected > cents)
    return view


def _forecast_view(rows: list[dict], today: date, months: int) -> dict:
    f = forecast_monthly_cents(rows, today, months, min_days=FORECAST_MIN_DAYS)
    start = today - timedelta(days=29)
    days_with_cost = len({r["day"] for r in rows if start <= r["day"] <= today and r.get("cost_cents", 0) > 0})
    return {
        "status": f["status"],
        "method": FORECAST_METHOD,
        "minDays": FORECAST_MIN_DAYS,
        "daysWithUsage": days_with_cost,
        "dailySlopeCents": f.get("daily_slope_cents"),
        "months": [{"month": m["month"], "projectedCents": m["projected_cents"]} for m in f["months"]],
    }


def _anomaly_view(a: CostAnomaly) -> dict:
    detected = job_runner.as_utc(a.detected_at)
    return {
        "id": a.id, "type": a.anomaly_type, "severity": a.severity,
        "detectedAt": detected.isoformat() if detected else None, "details": a.details or {},
    }


async def _open_anomalies(agent_id: str) -> list[dict]:
    async with get_db_session() as db:
        rows = (await db.execute(
            select(CostAnomaly).where(CostAnomaly.agent_id == agent_id, CostAnomaly.resolved_at.is_(None))
        )).scalars().all()
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return [_anomaly_view(a) for a in sorted(rows, key=lambda a: (order.get(a.severity, 4), a.anomaly_type))]


def _entry_for(run: JobRun, agent_id: str) -> dict | None:
    """This agent's part of an ingestion run, or None when an all-agents run
    did not cover it."""
    entry = next((a for a in (run.summary or {}).get("agents") or [] if a.get("agent_id") == agent_id), None)
    if entry is None and run.agent_id == agent_id:
        return {}
    return entry


async def _last_refresh(agent_id: str) -> dict | None:
    """The newest usage ingestion that covered this agent, as this agent saw it."""
    async with get_db_session() as db:
        runs = (await db.execute(
            select(JobRun).where(
                JobRun.job == "usage_ingestion",
                (JobRun.agent_id == agent_id) | JobRun.agent_id.is_(None),
                JobRun.status != "running",
            ).order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(20)
        )).scalars().all()
    found = next(((r, e) for r in runs if (e := _entry_for(r, agent_id)) is not None), None)
    if found is None:
        return None
    run, mine = found
    summary = run.summary or {}
    at = job_runner.as_utc(run.finished_at or run.started_at)
    return {
        "status": mine.get("status") or run.status,
        "reason": mine.get("reason") or summary.get("reason") or run.error,
        "truncated": bool(mine.get("truncated")),
        "days": mine.get("days"),
        "at": at.isoformat() if at else None,
        "trigger": run.trigger,
    }


# ── Tokenomics tab ───────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/tokenomics")
async def agent_tokenomics(agent_id: str, days: int = Query(30, ge=7, le=90), _=Depends(require_read)):
    agent, usage, budget = await _load(agent_id)
    today = _today()
    rows = usage["rows"]
    window = _window(rows, today, days)
    window_start = today - timedelta(days=days - 1)
    has_data = usage["source"] != "none"
    budget_view = _budget_view(budget, rows, today, has_data)

    daily = daily_series(rows, window_start, today)
    spikes: set[str] = set()
    anomaly_share = None
    if usage["source"] == "phoenix":
        history = daily_series(rows, window_start - timedelta(days=SPIKE_BASELINE_DAYS), today)
        spikes = {s["date"] for s in spike_days(history, window_start)}
        share = anomaly_cost_share(history, window_start)
        if share:
            anomaly_share = {"pct": share["pct"], "band": share["band"], "impactCents": share["impact_cents"],
                             "evaluatedDays": share["evaluated_days"]}

    return {
        "agentId": agent_id,
        "linked": bool((agent.phoenix_project or "").strip()),
        "phoenixProject": agent.phoenix_project or None,
        "declaredModel": agent.model_name,
        "source": usage["source"],
        "lastIngestedAt": _iso_utc(usage["last_ingested_at"]),
        "lastRefresh": await _last_refresh(agent_id),
        "unpricedModels": sorted({r["model"] for r in window if not r["priced"]}),
        "currency": "USD",
        "days": days,
        "windowStart": window_start.isoformat(),
        "windowEnd": today.isoformat(),
        "totals": _totals(window, has_data),
        "monthToDateCents": budget_view["monthToDateCents"],
        "projectedPeriodEndCents": budget_view["projectedPeriodEndCents"],
        "costPerCallCents": _cost_per_call(window),
        "budget": budget_view,
        "daily": [
            {**{_camel(k): d[k] for k in ("date", *_TOTAL_KEYS)}, "costCents": d["cost_cents"], "spike": d["date"] in spikes}
            for d in daily
        ],
        "byModel": [
            {"model": m["model"], "inputTokens": m["input_tokens"], "outputTokens": m["output_tokens"],
             "cachedTokens": m["cached_tokens"], "calls": m["calls"], "costCents": m["cost_cents"],
             "sharePct": m["share_pct"], "priced": m["priced"]}
            for m in by_model(window)
        ],
        "forecast": _forecast_view(rows, today, 3),
        "anomalyCostShare": anomaly_share,
        "anomalies": await _open_anomalies(agent_id),
    }


async def _require_agent(agent_id: str) -> None:
    async with get_db_session() as db:
        if await db.get(Agent, agent_id) is None:
            raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/agents/{agent_id}/usage/refresh")
async def refresh_usage(
    agent_id: str,
    days: Optional[int] = Query(None, ge=1, le=90, description="Days to (re)read; default 30 on first read, else 2"),
    user=Depends(require_update),
):
    await _require_agent(agent_id)
    ingestion = await job_runner.run_job("usage_ingestion", agent_id=agent_id, trigger="manual", **({"days": days} if days else {}))
    rollup = await job_runner.run_job("cost_rollup", agent_id=agent_id, trigger="manual")
    summary = ingestion.get("summary") or {}
    mine = next((a for a in summary.get("agents") or [] if a.get("agent_id") == agent_id), {})
    usage = {
        "status": mine.get("status") or ingestion["status"],
        "reason": mine.get("reason") or summary.get("reason") or ingestion.get("reason") or ingestion.get("error"),
        "days": mine.get("days"),
        "rows": mine.get("rows", 0),
        "calls": mine.get("calls", 0),
        "truncated": bool(mine.get("truncated")),
        "unpricedModels": mine.get("unpriced_models") or [],
    }
    statuses = [ingestion["status"], rollup["status"]]
    status = "skipped" if all(s == "skipped" for s in statuses) else job_runner.overall_status(statuses)
    await log_audit_event(
        actor=user["user_id"], action="usage.refresh", entity_type="agent", entity_id=agent_id,
        changes={"days": days, "status": status, "usageStatus": usage["status"],
                 "ingestionRunId": ingestion.get("runId"), "rollupRunId": rollup.get("runId")},
    )
    return {"agentId": agent_id, "status": status, "usage": usage, "ingestion": ingestion, "rollup": rollup}


# ── Budget (informational only) ──────────────────────────────────────────────

def _legacy_budget(agent_id: str, usage: dict, budget: AgentBudget | None) -> dict:
    view = _budget_view(budget, usage["rows"], _today(), usage["source"] != "none")
    mtd = view["monthToDateCents"]
    budget_dollars = view["monthlyBudgetCents"] / 100
    return {
        "agentId": agent_id,
        "monthlyBudget": budget_dollars,
        "currentSpend": round(mtd / 100, 2) if mtd is not None else None,
        "remaining": round(budget_dollars - mtd / 100, 2) if mtd is not None and budget_dollars else None,
        "budgetUsagePct": (view["usedPct"] or 0) if mtd is not None else None,
        "source": usage["source"],
        **view,
    }


@router.get("/agents/{agent_id}/budget")
async def get_budget(agent_id: str, _=Depends(require_read)):
    _, usage, budget = await _load(agent_id)
    return _legacy_budget(agent_id, usage, budget)


class BudgetUpdate(BaseModel):
    # agent_budgets.monthly_budget_cents is a 32-bit Integer column.
    monthlyBudgetCents: Optional[int] = Field(None, ge=0, le=2_000_000_000)
    monthlyBudget: Optional[float] = Field(None, ge=0, le=20_000_000, description="Dollars (legacy)")
    alertThresholdPct: Optional[int] = Field(None, ge=1, le=100)
    budgetResetDay: Optional[int] = Field(None, ge=1, le=28)


@router.put("/agents/{agent_id}/budget")
async def put_budget(agent_id: str, body: BudgetUpdate, user=Depends(require_update)):
    wanted = {
        "monthly_budget_cents": body.monthlyBudgetCents if body.monthlyBudgetCents is not None
        else (round(body.monthlyBudget * 100) if body.monthlyBudget is not None else None),
        "alert_threshold_pct": body.alertThresholdPct,
        "budget_reset_day": body.budgetResetDay,
    }
    wanted = {k: v for k, v in wanted.items() if v is not None}
    if not wanted:
        raise HTTPException(status_code=422, detail="Nothing to update: send monthlyBudgetCents, monthlyBudget, alertThresholdPct or budgetResetDay.")
    async with get_db_session() as db:
        if await db.get(Agent, agent_id) is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        budget = await db.get(AgentBudget, agent_id)
        if budget is None:
            # The column defaults to True, but budgets here are never enforced.
            budget = AgentBudget(agent_id=agent_id, monthly_budget_cents=0, alert_threshold_pct=80,
                                 budget_reset_day=1, auto_pause_on_breach=False)
            db.add(budget)
        changes = {}
        for field, value in wanted.items():
            old = getattr(budget, field)
            if old != value:
                changes[_camel(field)] = {"from": old, "to": value}
                setattr(budget, field, value)
    if changes:
        await log_audit_event(actor=user["user_id"], action="budget.update", entity_type="agent_budget",
                              entity_id=agent_id, changes=changes)
    _, usage, budget = await _load(agent_id)
    return _legacy_budget(agent_id, usage, budget)


# ── Older per-agent endpoints, now engine-backed ─────────────────────────────

@router.get("/agents/{agent_id}/tokens/summary")
async def token_summary(agent_id: str, _=Depends(require_read)):
    _, usage, _ = await _load(agent_id)
    rows = usage["rows"]
    has_data = usage["source"] != "none"
    totals = _totals(rows, has_data)
    per_call = _cost_per_call(rows)
    return {
        "agentId": agent_id,
        "inputTokens": totals["inputTokens"],
        "outputTokens": totals["outputTokens"],
        "cachedTokens": totals["cachedTokens"],
        "invocations": totals["calls"],
        "costCents": totals["costCents"],
        "costPerInvocation": round(per_call / 100, 6) if per_call is not None else None,
        "source": usage["source"],
        "unpricedModels": usage["unpriced"],
    }


@router.get("/agents/{agent_id}/tokens/trend")
async def token_trend(agent_id: str, days: int = Query(30, ge=1, le=365), _=Depends(require_read)):
    _, usage, _ = await _load(agent_id)
    today = _today()
    series = daily_series(usage["rows"], today - timedelta(days=days - 1), today)
    return {
        "agentId": agent_id,
        "days": days,
        "source": usage["source"],
        "trend": [
            {"date": d["date"], "inputTokens": d["input_tokens"], "outputTokens": d["output_tokens"],
             "cachedTokens": d["cached_tokens"], "invocations": d["calls"], "costCents": d["cost_cents"]}
            for d in series
        ],
    }


@router.get("/agents/{agent_id}/cost")
async def agent_cost(agent_id: str, _=Depends(require_read)):
    """monthlyCost is the trailing 30 days of token cost, in dollars."""
    _, usage, budget = await _load(agent_id)
    today = _today()
    window = _window(usage["rows"], today, 30)
    has_data = usage["source"] != "none"
    per_call = _cost_per_call(window)
    mtd = _budget_view(budget, usage["rows"], today, has_data)["monthToDateCents"]
    return {
        "agentId": agent_id,
        "monthlyCost": round(sum(r["cost_cents"] for r in window) / 100, 4) if has_data and _cost_known(window) else None,
        "costPerInvocation": round(per_call / 100, 6) if per_call is not None else None,
        "monthToDate": round(mtd / 100, 4) if mtd is not None else None,
        "periodDays": 30,
        "source": usage["source"],
        "unpricedModels": sorted({r["model"] for r in window if not r["priced"]}),
    }


@router.get("/agents/{agent_id}/cost/forecast")
async def cost_forecast(agent_id: str, months: int = Query(3, ge=1, le=12), _=Depends(require_read)):
    _, usage, _ = await _load(agent_id)
    today = _today()
    rows = usage["rows"]
    forecast = _forecast_view(rows, today, months)
    trailing = sum(r["cost_cents"] for r in _window(rows, today, 30)) / 100
    projected = [{"month": m["month"], "projectedCost": round(m["projectedCents"] / 100, 2)} for m in forecast["months"]]
    return {
        "agentId": agent_id,
        "currentMonthlyAvg": round(trailing, 2) if usage["source"] != "none" else None,
        "forecast": projected,
        "totalProjected": round(sum(p["projectedCost"] for p in projected), 2) if projected else None,
        "source": usage["source"],
        "status": forecast["status"],
        "method": forecast["method"],
        "daysWithUsage": forecast["daysWithUsage"],
        "minDays": forecast["minDays"],
    }


# ── Model aliases ────────────────────────────────────────────────────────────

@router.get("/models/aliases")
async def list_model_aliases(_=Depends(require_read)):
    async with get_db_session() as db:
        aliases = (await db.execute(select(ModelAlias).order_by(ModelAlias.alias))).scalars().all()
        prices = await load_prices(db)
        alias_map = await load_aliases(db)
        observed = set((await db.execute(
            select(AgentTokenUsage.model_name).where(AgentTokenUsage.source == "phoenix").distinct()
        )).scalars().all())
    return {
        "aliases": [{"alias": a.alias, "modelName": a.model_name, "priced": a.model_name.strip().lower() in prices}
                    for a in aliases],
        "pricedModels": sorted(prices),
        "unpricedObservedModels": sorted({m for m in observed if normalize_model(m, alias_map) not in prices}),
    }


class AliasUpdate(BaseModel):
    modelName: str = Field(..., min_length=1, max_length=100)


@router.put("/models/aliases/{alias:path}")
async def put_model_alias(alias: str, body: AliasUpdate, user=Depends(require_admin)):
    key = alias.strip().lower()
    target = body.modelName.strip().lower()
    if not key or len(key) > 150:
        raise HTTPException(status_code=422, detail="Alias must be 1-150 characters.")
    if key == target:
        raise HTTPException(status_code=422, detail="An alias cannot point to itself.")
    async with get_db_session() as db:
        if target not in await load_prices(db):
            raise HTTPException(status_code=422, detail=f"'{body.modelName}' has no current price; add the price first.")
        row = await db.get(ModelAlias, key)
        old = row.model_name if row else None
        if row is None:
            db.add(ModelAlias(alias=key, model_name=target))
        else:
            row.model_name = target
    if old != target:
        await log_audit_event(actor=user["user_id"], action="model_alias.upsert", entity_type="model_alias",
                              entity_id=key[:64], changes={"alias": key, "from": old, "to": target})
    return {"alias": key, "modelName": target, "priced": True}
