"""Value vs cost of ownership for one agent, per month.

Cost = token cost (Phoenix-measured usage priced by governance.costing; seed
rows are demo data) + infrastructure cost (metered by Azure Cost Management,
else declared by the owner, else a per-stage estimate). Value is the
owner-declared $/month; realized value is hours saved x a blended hourly rate.
Every figure carries its source, and an unknown figure is None, never 0.

The current month is shown as a monthly run-rate (month to date projected to
month end) so it compares like-for-like with the $/month value.

Everything down to build_economics is pure; load_economics and
financial_flags read the DB. Showback only: nothing here pauses, throttles or
otherwise changes an agent.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from governance.costing import month_to_date_cents, period_end, period_start, projected_period_end_cents

INFRA_ESTIMATE_CENTS_BY_STAGE: dict[str, int] = {
    "Ideation": 0,
    "Development": 0,
    "Testing": 2000,
    "Production": 8000,
    "Deprecated": 0,
}
TREND_MONTHS = 6
IDLE_WINDOW_DAYS = 30

# Cost-to-value bands. An org convention, not an industry standard: McKinsey
# reports ~$3.70 of value per $1 spent on gen AI on average and >$10 for the
# top performers.
EFFICIENT_MAX_RATIO = 0.10
AVERAGE_MAX_RATIO = 0.27


# ── Pure: figures ────────────────────────────────────────────────────────────

def estimated_infra_cents(stage: str | None) -> int:
    return INFRA_ESTIMATE_CENTS_BY_STAGE.get(stage or "", 0)


def resolve_infra(month_metered_cents: float | None, declared_monthly_cents: int | None, stage: str | None) -> dict:
    """Metered beats declared beats the stage estimate."""
    if month_metered_cents is not None:
        return {"cents": round(month_metered_cents, 2), "source": "metered"}
    if declared_monthly_cents is not None:
        return {"cents": declared_monthly_cents, "source": "declared"}
    return {"cents": estimated_infra_cents(stage), "source": "estimate"}


def _pct(num: float, den: float) -> float | None:
    return round(num / den * 100, 1) if den else None


def agent_economics(
    *,
    value_amount_dollars: int | None,
    hours_saved_monthly: int | None,
    hourly_rate: float,
    token_cost_cents: float | None,
    token_source: str,
    infra: Mapping,
    one_time_cost_cents: int | None = None,
) -> dict:
    """One month of economics. token_cost_cents None means no usage data: it
    is left out of the total and costComplete is False."""
    value = max(int(value_amount_dollars or 0), 0) * 100
    declared = value > 0
    realized = round(max(hours_saved_monthly or 0, 0) * hourly_rate * 100)
    token = None if token_cost_cents is None else round(token_cost_cents, 2)
    infra_cents = infra["cents"]
    total = round((token or 0) + infra_cents, 2)
    monthly_net = value - total
    payback = (
        round(one_time_cost_cents / monthly_net, 1)
        if one_time_cost_cents and declared and monthly_net > 0 else None
    )
    return {
        "valueCents": value,
        "valueDeclared": declared,
        "realizedValueCents": realized,
        "tokenCostCents": token,
        "tokenSource": token_source,
        "infraCostCents": infra_cents,
        "infraSource": infra["source"],
        "totalCostCents": total,
        "costComplete": token is not None,
        "netCents": round(monthly_net, 2),
        "netAvailable": declared,
        "roiPct": _pct(monthly_net, total) if declared else None,
        "paybackMonths": payback,
        "oneTimeCostCents": one_time_cost_cents or 0,
        "costToValuePct": _pct(total, value) if declared else None,
        # Legacy keys (Executive dashboard, older clients).
        "revenueCents": value,
        "estimatedInfraCostCents": infra_cents,
        "expenditureCents": total,
    }


def efficiency_rating(total_cost_cents: float, value_cents: int, cost_complete: bool) -> str:
    if value_cents <= 0:
        return "not_declared"
    if not cost_complete:
        return "insufficient_data"
    ratio = total_cost_cents / value_cents
    if ratio < EFFICIENT_MAX_RATIO:
        return "efficient"
    if ratio < AVERAGE_MAX_RATIO:
        return "moderate"
    if ratio < 1:
        return "below_average"
    return "inefficient"


def run_rate_cents(month_to_date: float, through: date, start: date, end: date) -> float:
    """Month-to-date cost covering start..through, scaled to the whole period."""
    covered = max((through - start).days + 1, 1)
    return month_to_date / covered * ((end - start).days + 1)


# ── Pure: months ─────────────────────────────────────────────────────────────

def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def recent_months(today: date, n: int = TREND_MONTHS) -> list[str]:
    """The last n calendar months, oldest first, ending with today's month."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def monthly_trend(
    token_by_month: Mapping[str, float | None],
    infra_by_month: Mapping[str, Mapping | None],
    value_cents: int | None,
    months: Sequence[str] | None = None,
    *,
    active_from: str | None = None,
    current_month: str | None = None,
) -> list[dict]:
    """[{month, tokenCostCents, infraCostCents, infraSource, totalCostCents,
    valueCents, netCents, roiPct, partial}] for each month (default: the last
    TREND_MONTHS calendar months), oldest first. A month missing from a
    mapping is unknown (None), not zero."""
    if months is None:
        months = recent_months(datetime.now(timezone.utc).date())
    out = []
    for m in months:
        token = token_by_month.get(m)
        infra = infra_by_month.get(m)
        value = value_cents if value_cents and (active_from is None or m >= active_from) else None
        known = [c for c in (token, infra["cents"] if infra else None) if c is not None]
        total = round(sum(known), 2) if known else None
        net = round(value - total, 2) if value is not None and total is not None else None
        out.append({
            "month": m,
            "tokenCostCents": None if token is None else round(token, 2),
            "infraCostCents": infra["cents"] if infra else None,
            "infraSource": infra["source"] if infra else None,
            "totalCostCents": total,
            "valueCents": value,
            "netCents": net,
            "roiPct": _pct(net, total) if net is not None and total else None,
            "partial": m == current_month,
        })
    return out


# ── Pure: financial flags ────────────────────────────────────────────────────

def _money(cents: float | None) -> str:
    return "unknown" if cents is None else f"${cents / 100:,.2f}"


def _cost_exceeds_value(month: Mapping) -> bool:
    value, cost = month.get("valueCents"), month.get("totalCostCents")
    # A month whose only cost is the stage estimate proves nothing.
    real_cost = month.get("tokenCostCents") is not None or month.get("infraSource") in ("metered", "declared")
    return bool(value) and cost is not None and real_cost and cost > value


def evaluate_financial_flags(
    *,
    stage: str | None,
    trend: Sequence[Mapping],
    infra_cost_cents: float,
    infra_source: str,
    calls_last_30d: int | None,
    has_spend: bool,
    has_budget: bool,
    token_source: str = "none",
) -> list[dict]:
    """Rules for Production agents, visibility only:
    negative_roi_2_months (HIGH): cost > declared value in both of the last two
      complete months; idle_cost (MEDIUM): infra cost > 0 and zero LLM calls in
      the last 30 days of a linked Phoenix project (calls_last_30d None = not
      measured, never idle); no_budget (LOW): real spend this month and no budget.
    Each flag's `source` is the usage source behind it ('seed' = demo data)."""
    if stage != "Production":
        return []
    flags = []
    complete = [m for m in trend if not m.get("partial")][-2:]
    if len(complete) == 2 and all(_cost_exceeds_value(m) for m in complete):
        detail = "; ".join(f"{m['month']}: cost {_money(m['totalCostCents'])} vs value {_money(m['valueCents'])}" for m in complete)
        flags.append({
            "rule_id": "negative_roi_2_months", "severity": "HIGH",
            "title": "Cost exceeded declared value for 2 consecutive months",
            "description": f"{detail}. Review the declared value or the cost drivers.",
            "source": token_source,
        })
    if infra_cost_cents > 0 and calls_last_30d == 0:
        flags.append({
            "rule_id": "idle_cost", "severity": "MEDIUM",
            "title": "Hosting cost with no LLM calls in 30 days",
            "description": (f"Infrastructure costs {_money(infra_cost_cents)}/month ({infra_source}) but the linked "
                            f"Phoenix project recorded no LLM calls in the last {IDLE_WINDOW_DAYS} days."),
            "source": "phoenix",
        })
    if has_spend and not has_budget:
        flags.append({
            "rule_id": "no_budget", "severity": "LOW",
            "title": "Production agent with spend and no budget",
            "description": "Set a monthly budget so spend can be tracked against it (visibility only; nothing is enforced).",
            "source": token_source,
        })
    return flags


# ── Pure: one agent from plain data ──────────────────────────────────────────

def _token_status(source: str, linked: bool, ingested: bool) -> str:
    if source == "phoenix":
        return "measured"
    if linked and ingested:
        return "no_calls"
    if source == "seed":
        return "demo"
    return "awaiting_ingestion" if linked else "no_usage_data"


def _declared_components(components: Iterable[Any] | None) -> tuple[list[dict], int]:
    out, one_time = [], 0
    for c in components or []:
        if isinstance(c, str):
            c = {"name": c}
        if not isinstance(c, Mapping) or not str(c.get("name") or "").strip():
            continue
        cents = c.get("costCents")
        recurring = c.get("recurring", True) is not False
        out.append({"name": str(c["name"]).strip(), "costCents": cents, "recurring": recurring})
        if not recurring and isinstance(cents, (int, float)):
            one_time += int(cents)
    return out, one_time


def build_economics(
    agent: Mapping,
    usage: Mapping,
    infra_rows: Sequence[Mapping],
    profile: Mapping | None,
    *,
    has_budget: bool,
    usage_ingested: bool,
    today: date,
    hourly_rate: float,
) -> dict:
    """agent: {id, name, stage, value_amount, value_type, hours_saved_monthly,
    phoenix_project, created_at (date|None)}. usage: services.usage_repo.
    priced_usage() output. infra_rows: [{cost_date, resource_id, service_name,
    cost_cents, allocation}]. profile: {monthly_cost_cents, effective_from,
    components} or None."""
    stage = agent.get("stage")
    months = recent_months(today)
    current = months[-1]
    start = period_start(today)
    end = period_end(start)

    linked = bool((agent.get("phoenix_project") or "").strip())
    status = _token_status(usage.get("source", "none"), linked, usage_ingested)
    rows = list(usage.get("rows") or []) if status in ("measured", "demo") else []
    token_source = {"measured": "phoenix", "no_calls": "phoenix", "demo": "seed"}.get(status, "none")
    priced_flags = [r.get("priced", True) for r in rows]
    pricing = "missing" if rows and not any(priced_flags) else "partial" if not all(priced_flags) else "ok"
    if pricing == "missing":
        # Every call is on a model without a price: a $0 here would be false.
        mtd = projected = None
    elif status in ("measured", "demo"):
        mtd = month_to_date_cents(rows, today)
        projected = projected_period_end_cents(rows, today)
    elif status == "no_calls":
        mtd = projected = 0.0
    else:
        mtd = projected = None
    calls_30d = (
        sum(r.get("calls") or 0 for r in rows if r["day"] >= today - timedelta(days=IDLE_WINDOW_DAYS - 1))
        if status in ("measured", "no_calls") else None
    )

    metered_by_month: dict[str, float] = defaultdict(float)
    current_rows = []
    for r in infra_rows:
        metered_by_month[month_key(r["cost_date"])] += r["cost_cents"] or 0
        if start <= r["cost_date"] <= today:
            current_rows.append(r)
    metered_run_rate = None
    if current_rows:
        through = max(r["cost_date"] for r in current_rows)
        metered_run_rate = run_rate_cents(sum(r["cost_cents"] or 0 for r in current_rows), through, start, end)

    declared = profile.get("monthly_cost_cents") if profile else None
    declared_from = month_key(profile["effective_from"]) if profile and profile.get("effective_from") else None
    declared_now = declared if declared is not None and (declared_from is None or declared_from <= current) else None
    infra = resolve_infra(metered_run_rate, declared_now, stage)
    components, one_time = _declared_components(profile.get("components") if profile else None)

    firsts = [month_key(d) for d in (
        agent.get("created_at"),
        min((r["day"] for r in rows), default=None),
        min((r["cost_date"] for r in infra_rows), default=None),
    ) if d]
    active_from = min(firsts) if firsts else None

    token_by_month: dict[str, float | None] = {}
    if rows and pricing != "missing":
        first = month_key(min(r["day"] for r in rows))
        token_by_month = {m: 0.0 for m in months if m >= first}
        for r in rows:
            if month_key(r["day"]) in token_by_month:
                token_by_month[month_key(r["day"])] += r.get("cost_cents", 0.0)
    if projected is not None:
        token_by_month[current] = projected

    infra_by_month: dict[str, dict | None] = {}
    for m in months[:-1]:
        if m in metered_by_month:
            infra_by_month[m] = {"cents": round(metered_by_month[m], 2), "source": "metered"}
        elif active_from and m < active_from:
            infra_by_month[m] = None
        elif declared is not None and (declared_from is None or m >= declared_from):
            infra_by_month[m] = {"cents": declared, "source": "declared"}
        else:
            infra_by_month[m] = {"cents": estimated_infra_cents(stage), "source": "estimate"}
    infra_by_month[current] = infra

    econ = agent_economics(
        value_amount_dollars=agent.get("value_amount"),
        hours_saved_monthly=agent.get("hours_saved_monthly"),
        hourly_rate=hourly_rate,
        token_cost_cents=projected,
        token_source=token_source,
        infra=infra,
        one_time_cost_cents=one_time,
    )
    trend = monthly_trend(token_by_month, infra_by_month, econ["valueCents"], months,
                          active_from=active_from, current_month=current)
    has_spend = (projected or 0) > 0 or (infra["source"] != "estimate" and infra["cents"] > 0)

    by_resource: dict[str, dict] = {}
    for r in current_rows:
        entry = by_resource.setdefault(r["resource_id"], {
            "resourceId": r["resource_id"], "serviceName": r.get("service_name"),
            "cents": 0, "allocation": r.get("allocation"),
        })
        entry["cents"] += r["cost_cents"] or 0

    return {
        "agentId": agent["id"],
        "name": agent.get("name"),
        "stage": stage,
        "valueType": agent.get("value_type"),
        "hoursSavedMonthly": agent.get("hours_saved_monthly") or 0,
        "hourlyRate": hourly_rate,
        "period": {
            "month": current, "start": start.isoformat(), "end": end.isoformat(),
            "daysElapsed": (today - start).days + 1, "daysInPeriod": (end - start).days + 1,
            "basis": "run_rate",
        },
        **econ,
        "token": {
            "status": status,
            "pricing": pricing,
            "monthToDateCents": None if mtd is None else round(mtd, 2),
            "projectedCents": None if projected is None else round(projected, 2),
            "unpricedModels": list(usage.get("unpriced") or []) if rows else [],
            "lastIngestedAt": usage.get("last_ingested_at"),
            "phoenixLinked": linked,
            "phoenixProject": agent.get("phoenix_project"),
            "callsLast30d": calls_30d,
        },
        "infra": {
            "source": infra["source"],
            "cents": infra["cents"],
            "meteredMonthToDateCents": sum(r["cost_cents"] or 0 for r in current_rows) if current_rows else None,
            "meteredThrough": max(r["cost_date"] for r in current_rows).isoformat() if current_rows else None,
            "declaredMonthlyCents": declared,
            "declaredFrom": profile["effective_from"].isoformat() if profile and profile.get("effective_from") else None,
            "components": components,
            "estimateCents": estimated_infra_cents(stage),
            "byResource": sorted(by_resource.values(), key=lambda e: e["cents"], reverse=True)[:20],
        },
        "efficiencyRating": efficiency_rating(econ["totalCostCents"], econ["valueCents"], econ["costComplete"]),
        "hasBudget": has_budget,
        "trend": trend,
        "financialFlags": evaluate_financial_flags(
            stage=stage, trend=trend, infra_cost_cents=infra["cents"], infra_source=infra["source"],
            calls_last_30d=calls_30d, has_spend=has_spend, has_budget=has_budget, token_source=token_source,
        ),
    }


# ── DB ───────────────────────────────────────────────────────────────────────

def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


async def _ingested_agent_ids(db: Any, agent_ids: set[str]) -> set[str]:
    """Agents whose most recent usage ingestion finished ok for them."""
    from sqlalchemy import select

    from db.models import JobRun

    runs = (await db.execute(
        select(JobRun).where(JobRun.job == "usage_ingestion", JobRun.status.in_(("ok", "partial")))
        .order_by(JobRun.started_at.desc()).limit(50)
    )).scalars().all()
    seen: dict[str, bool] = {}
    for run in runs:
        for entry in (run.summary or {}).get("agents") or []:
            aid = entry.get("agent_id") if isinstance(entry, dict) else None
            if aid in agent_ids and aid not in seen:
                seen[aid] = entry.get("status") in ("ok", "partial")
    return {aid for aid, ok in seen.items() if ok}


async def load_economics(db: Any, agents: Sequence[Any], today: date | None = None) -> dict[str, dict]:
    """build_economics for each Agent row, keyed by agent id."""
    from sqlalchemy import select

    from db.models import AgentBudget, AgentInfraCost, AgentInfraProfile
    from services.usage_repo import priced_usage
    from shared.config import get_settings

    today = today or datetime.now(timezone.utc).date()
    ids = [a.id for a in agents]
    if not ids:
        return {}
    since = date.fromisoformat(recent_months(today)[0] + "-01")

    infra_rows: dict[str, list[dict]] = defaultdict(list)
    for r in (await db.execute(
        select(AgentInfraCost).where(AgentInfraCost.agent_id.in_(ids), AgentInfraCost.cost_date >= since)
    )).scalars().all():
        infra_rows[r.agent_id].append({
            "cost_date": r.cost_date, "resource_id": r.resource_id, "service_name": r.service_name,
            "cost_cents": r.cost_cents or 0, "allocation": r.allocation,
        })
    # A profile saved with $0 (e.g. only platform filled in) is not a declared
    # cost: the column cannot hold NULL, and a blank must never show as $0.
    profiles = {
        p.agent_id: {"monthly_cost_cents": p.monthly_cost_cents if (p.monthly_cost_cents or 0) > 0 else None,
                     "effective_from": p.effective_from, "components": p.components or []}
        for p in (await db.execute(select(AgentInfraProfile).where(AgentInfraProfile.agent_id.in_(ids)))).scalars().all()
    }
    budgeted = set((await db.execute(
        select(AgentBudget.agent_id).where(AgentBudget.agent_id.in_(ids), AgentBudget.monthly_budget_cents > 0)
    )).scalars().all())
    ingested = await _ingested_agent_ids(db, set(ids))
    rate = get_settings().blended_hourly_rate_usd

    out = {}
    for a in agents:
        agent = {
            "id": a.id, "name": a.name, "stage": a.lifecycle_stage, "value_amount": a.value_amount,
            "value_type": a.value_type, "hours_saved_monthly": a.hours_saved_monthly,
            "phoenix_project": a.phoenix_project, "created_at": _as_date(a.created_at),
        }
        out[a.id] = build_economics(
            agent, await priced_usage(db, a.id, since), infra_rows.get(a.id, []), profiles.get(a.id),
            has_budget=a.id in budgeted, usage_ingested=a.id in ingested, today=today, hourly_rate=rate,
        )
    return out


async def financial_flags(db: Any, agent_id: str, today: date | None = None) -> list[dict]:
    """[{rule_id, severity, title, description}] for one agent; [] when the
    agent does not exist. Used by the risk scan."""
    from sqlalchemy import select

    from db.models import Agent

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        return []
    return (await load_economics(db, [agent], today))[agent_id]["financialFlags"]
