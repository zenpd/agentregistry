"""Daily cost rollup per agent: agent_metrics rows and open cost anomalies.

Works only from Phoenix-sourced usage; an agent with only demo (seed) rows or
no rows is skipped. Informational only: nothing here changes an agent.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db_session
from db.models import Agent, AgentBudget, AgentMetric, AuditLog, CostAnomaly
from governance.cost_anomalies import ANOMALY_TYPES, detect, reconcile
from governance.costing import daily_series, normalize_model
from services.usage_repo import load_aliases, priced_usage
from shared.logger import get_logger

log = get_logger("orchestrations.cost_rollup")

# Covers the 28-day spike baseline, the 7 + 30 day cost-per-call windows and
# the longest budget period.
HISTORY_DAYS = 45
UNPRICED_WINDOW_DAYS = 30
ACTOR = "system:cost_rollup"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime | None) -> datetime:
    # SQLite returns naive datetimes; order everything as naive UTC.
    if dt is None:
        return datetime.min
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def daily_metrics(rows: Iterable[Mapping]) -> dict[date, dict]:
    """agent_metrics values for each day that has usage rows; cost in dollars."""
    days: dict[date, dict] = {}
    for r in rows:
        d = days.setdefault(r["day"], {"tokens": 0, "calls": 0, "errors": 0, "cost_cents": 0.0})
        d["tokens"] += (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        d["calls"] += r.get("calls") or 0
        d["errors"] += r.get("errors") or 0
        d["cost_cents"] += r.get("cost_cents") or 0.0
    out = {}
    for day, d in days.items():
        calls = d["calls"]
        out[day] = {
            "avg_tokens": round(d["tokens"] / calls, 1) if calls else None,
            "total_cost": round(d["cost_cents"] / 100, 6),
            "efficiency": round(1 - d["errors"] / calls, 4) if calls else None,
            "error_rate": round(d["errors"] / calls, 4) if calls else None,
        }
    return out


async def _upsert_metrics(db: AsyncSession, agent_id: str, metrics: dict[date, dict]) -> int:
    existing = {m.metric_date: m for m in (await db.execute(
        select(AgentMetric).where(AgentMetric.agent_id == agent_id)
    )).scalars().all()}
    for day, values in metrics.items():
        row = existing.get(day)
        if row is None:
            db.add(AgentMetric(id=f"{agent_id}-{day.isoformat()}", agent_id=agent_id, metric_date=day, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    return len(metrics)


async def _apply_anomalies(db: AsyncSession, agent_id: str, found: list[dict], now: datetime) -> dict:
    rows = (await db.execute(
        select(CostAnomaly).where(CostAnomaly.agent_id == agent_id, CostAnomaly.anomaly_type.in_(ANOMALY_TYPES))
    )).scalars().all()
    open_rows = sorted((r for r in rows if r.resolved_at is None), key=lambda r: _ts(r.detected_at), reverse=True)
    person_resolved: dict[str, dict] = {}
    for r in sorted((r for r in rows if r.resolved_at is not None and r.resolved_by != "auto"),
                    key=lambda r: _ts(r.resolved_at), reverse=True):
        person_resolved.setdefault(r.anomaly_type, r.details or {})

    plan = reconcile(found, [{"id": r.id, "anomaly_type": r.anomaly_type} for r in open_rows], person_resolved)
    by_id = {r.id: r for r in open_rows}
    for anomaly in plan["create"]:
        row_id = f"ca-{secrets.token_hex(8)}"
        db.add(CostAnomaly(id=row_id, agent_id=agent_id, anomaly_type=anomaly["anomaly_type"],
                           severity=anomaly["severity"], details=anomaly["details"], detected_at=now))
        db.add(AuditLog(org_id="org-default", actor=ACTOR, action="cost_anomaly.open", entity_type="cost_anomaly",
                        entity_id=row_id, changes={"agentId": agent_id, "type": anomaly["anomaly_type"], "severity": anomaly["severity"]}))
    for row_id, anomaly in plan["update"]:
        by_id[row_id].details = anomaly["details"]
        by_id[row_id].severity = anomaly["severity"]
    for row_id in plan["resolve"]:
        by_id[row_id].resolved_at = now
        by_id[row_id].resolved_by = "auto"
        db.add(AuditLog(org_id="org-default", actor=ACTOR, action="cost_anomaly.auto_resolve", entity_type="cost_anomaly",
                        entity_id=row_id, changes={"agentId": agent_id, "type": by_id[row_id].anomaly_type,
                                                   "reason": "condition no longer detected"}))
    return {"opened": len(plan["create"]), "updated": len(plan["update"]), "resolved": len(plan["resolve"])}


async def _rollup_agent(agent_id: str, today: date, now: datetime) -> dict:
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        usage = await priced_usage(db, agent_id)
        if usage["source"] != "phoenix":
            reason = "Only demo (seed) usage rows." if usage["source"] == "seed" else "No usage rows."
            return {"agent_id": agent_id, "status": "skipped", "reason": reason}
        rows = usage["rows"]
        metrics = await _upsert_metrics(db, agent_id, daily_metrics(rows))

        budget = await db.get(AgentBudget, agent_id)
        aliases = await load_aliases(db)
        recent = today - timedelta(days=UNPRICED_WINDOW_DAYS - 1)
        found = detect(
            daily_series(rows, today - timedelta(days=HISTORY_DAYS), today),
            today,
            budget.monthly_budget_cents if budget else None,
            budget.alert_threshold_pct if budget else None,
            normalize_model(agent.model_name, aliases) if agent.model_name else None,
            sorted({r["model"] for r in rows if not r["priced"] and r["day"] >= recent}),
            reset_day=budget.budget_reset_day if budget else 1,
        )
        counts = await _apply_anomalies(db, agent_id, found, now)
    return {"agent_id": agent_id, "status": "ok", "metrics": metrics, "open_anomalies": [a["anomaly_type"] for a in found], **counts}


async def rollup_costs(agent_id: str | None = None, trigger: str = "manual") -> dict:
    now = _utcnow()
    today = now.date()
    async with get_db_session() as db:
        stmt = select(Agent.id).where(Agent.id == agent_id) if agent_id else select(Agent.id)
        agent_ids = list((await db.execute(stmt)).scalars().all())
    if agent_id and not agent_ids:
        return {"status": "error", "trigger": trigger, "reason": f"Agent '{agent_id}' not found.", "agents": []}

    results = []
    for aid in agent_ids:
        try:
            results.append(await _rollup_agent(aid, today, now))
        except Exception as exc:  # one agent's failure must not stop the others
            log.exception("cost_rollup.agent_failed", agent_id=aid)
            results.append({"agent_id": aid, "status": "error", "reason": f"Rollup failed ({type(exc).__name__})."})

    done = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "error"]
    status = "error" if failed and not done else "partial" if failed else "ok" if done else "skipped"
    summary = {
        "status": status,
        "trigger": trigger,
        "date": today.isoformat(),
        "agents_rolled_up": len(done),
        "agents_skipped": sum(1 for r in results if r["status"] == "skipped"),
        "metrics_upserted": sum(r["metrics"] for r in done),
        "anomalies_opened": sum(r["opened"] for r in done),
        "anomalies_updated": sum(r["updated"] for r in done),
        "anomalies_resolved": sum(r["resolved"] for r in done),
        "agents": results if agent_id else done + failed,
    }
    if status == "skipped":
        summary["reason"] = results[0]["reason"] if agent_id and results else "No agent has Phoenix usage yet."
    return summary
