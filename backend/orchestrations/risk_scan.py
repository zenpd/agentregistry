"""Risk scan job: gathers each agent's signals, runs governance/risk_detection
and reconciles the result with agent_risks (governance/risk_lifecycle).

Run through orchestrations/job_runner (job 'risk_scan'), which records the
returned summary in job_runs. The scan only records findings; it never
changes an agent, a gate or a budget.
"""
from __future__ import annotations

import importlib
import inspect
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.base import get_db_session
from db.models import Agent, AgentRisk, AuditLog, CostAnomaly, WasteFinding
from discovery.phoenix_client import PhoenixClient
from governance.risk_detection import detect_risks, financial_findings, partition_findings, unevaluated_rules
from governance.risk_lifecycle import reconcile
from governance.trace_kri import kri_from_spans, slim_span
from shared.logger import get_logger

log = get_logger("orchestrations.risk_scan")

TRACE_WINDOW_DAYS = 7
SPAN_PAGE_LIMIT = 1000
SPAN_MAX_PAGES = 5
# Sub-agents inside one app show up as observed "agents"; they are not
# external dependencies, so they never count as drift.
DRIFT_KINDS = frozenset({"tool", "mcp_server", "retriever", "model", "embedding"})
ORG_ID = "org-default"


def _optional(module: str, name: str) -> Callable | None:
    # Sibling modules are optional: a missing or broken one only skips its rule.
    try:
        return getattr(importlib.import_module(module), name)
    except Exception:
        return None


def _call_with(fn: Callable, **available: Any) -> Any:
    """Calls fn with the subset of `available` it accepts; None when fn needs
    an argument we cannot supply."""
    kwargs = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name in available:
            kwargs[name] = available[name]
        elif param.default is inspect.Parameter.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD,
        ):
            return None
    return fn(**kwargs)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def risk_row_dict(row: AgentRisk) -> dict[str, Any]:
    return {
        "id": row.id, "agent_id": row.agent_id, "rule_id": row.rule_id, "category": row.category,
        "severity": row.severity, "title": row.title, "description": row.description,
        "source": row.source, "status": row.status, "owner": row.owner, "mitigation": row.mitigation,
        "due_date": row.due_date, "accepted_until": row.accepted_until, "accepted_by": row.accepted_by,
        "detected_at": row.detected_at, "last_detected_at": row.last_detected_at,
        "resolved_at": row.resolved_at, "history": list(row.history or []),
    }


def cost_anomaly_dict(row: CostAnomaly) -> dict[str, Any]:
    return {"id": row.id, "anomaly_type": row.anomaly_type, "severity": row.severity,
            "details": row.details or {}, "detected_at": row.detected_at}


def waste_dict(row: WasteFinding) -> dict[str, Any]:
    return {"id": row.id, "waste_type": row.waste_type, "severity": row.severity,
            "recommendation": row.recommendation, "monthly_waste_cents": row.monthly_waste_cents}


async def _financial_flags(db: AsyncSession, agent: Agent, agent_dict: dict) -> list[dict] | None:
    fn = _optional("governance.economics", "financial_flags")
    if fn is None:
        return None
    try:
        flags = _call_with(fn, db=db, agent=agent_dict, agent_id=agent.id)
        if inspect.isawaitable(flags):
            flags = await flags
    except Exception as exc:
        log.warning("risk_scan.financial_flags_failed", agent_id=agent.id, error=type(exc).__name__)
        return None
    return [f for f in flags or [] if isinstance(f, dict)]


async def live_financial(db: AsyncSession, agent: Agent, agent_dict: dict) -> list[dict[str, Any]]:
    """FINANCIAL findings for one agent, read at request time."""
    anomalies = (await db.execute(
        select(CostAnomaly).where(CostAnomaly.agent_id == agent.id, CostAnomaly.resolved_at.is_(None))
    )).scalars().all()
    waste = (await db.execute(
        select(WasteFinding).where(WasteFinding.agent_id == agent.id, WasteFinding.status == "open")
    )).scalars().all()
    return financial_findings(
        financial_flags=await _financial_flags(db, agent, agent_dict),
        cost_anomalies=[cost_anomaly_dict(a) for a in anomalies],
        waste_findings=[waste_dict(w) for w in waste],
    )


async def portfolio_financial(db: AsyncSession) -> list[dict[str, Any]]:
    """Every agent's live FINANCIAL findings, so portfolio counts match the
    sum of the per-agent Risk tabs.

    Rows whose agent no longer exists are skipped: no Risk tab can show them,
    so counting them here would make the portfolio disagree with the sum of
    its parts (a deleted agent left one behind before deletes cleaned up)."""
    live_agents = select(Agent.id).scalar_subquery()
    anomalies = (await db.execute(select(CostAnomaly).where(
        CostAnomaly.resolved_at.is_(None), CostAnomaly.agent_id.in_(live_agents)))).scalars().all()
    waste = (await db.execute(select(WasteFinding).where(
        WasteFinding.status == "open", WasteFinding.agent_id.in_(live_agents)))).scalars().all()
    flags: list[dict] = []
    load_economics = _optional("governance.economics", "load_economics")
    if load_economics is not None:
        try:
            agents = (await db.execute(select(Agent))).scalars().all()
            economics = await load_economics(db, agents)
            flags = [f for e in economics.values() for f in e.get("financialFlags") or [] if isinstance(f, dict)]
        except Exception as exc:
            log.warning("risk_scan.portfolio_flags_failed", error=type(exc).__name__)
    return financial_findings(
        financial_flags=flags,
        cost_anomalies=[cost_anomaly_dict(a) for a in anomalies],
        waste_findings=[waste_dict(w) for w in waste],
    )


def as_utc(value: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; every value stored is UTC.
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _gate_states(agent: Agent, now: datetime) -> dict[str, Any] | None:
    fn = _optional("governance.gate_policy", "gate_expiry_state")
    if fn is None:
        return None
    states = {}
    for review in agent.governance_reviews or []:
        expires_at = as_utc(review.expires_at)
        try:
            state = fn({"status": review.status, "expires_at": expires_at}, now)
        except Exception as exc:
            log.warning("risk_scan.gate_state_failed", agent_id=agent.id, error=type(exc).__name__)
            return None
        days_left = (expires_at - now).days if expires_at else None
        states[review.gate] = {"state": state, "daysLeft": days_left}
    return states


def _blast_radius(adjacency: dict | None, agent_id: str) -> int | None:
    if adjacency is None or agent_id not in adjacency["agent_kinds"]:
        return None
    from services.graph_service import affected_subgraph

    impact = affected_subgraph(adjacency, agent_id)
    return len(set(impact["affected_node_ids"]) - {agent_id})


def _declared(agent: Agent) -> dict[str, Any]:
    return {
        "enterprise_systems": agent.enterprise_systems or [], "databases": agent.databases or [],
        "knowledge_bases": agent.knowledge_bases or [], "mcp_servers": agent.mcp_servers or [],
        "calls": agent.calls or [], "model_name": agent.model_name,
    }


def _dependency_drift(declared: dict[str, Any], spans: list[dict]) -> dict[str, Any] | None:
    observed_from_spans = _optional("discovery.observed_deps", "observed_from_spans")
    compare = _optional("discovery.observed_deps", "compare")
    if observed_from_spans is None or compare is None:
        return None
    result = compare(declared, observed_from_spans(spans))
    return {
        "declared_only": result.get("declared_only") or [],
        "observed_only": [i for i in result.get("observed_only") or [] if i.get("kind") in DRIFT_KINDS],
    }


async def _trace_signals(ctx: dict[str, Any], now: datetime) -> None:
    """Fills ctx with trace_status, kri and drift. Span payloads are slimmed
    as they stream in, so prompt/output text is never held."""
    ctx.update(trace_status="not_linked", kri=None, drift=None, sample_capped=False)
    project = ctx["project"]
    if not project:
        return
    if not ctx["base_url"]:
        ctx["trace_status"] = "unavailable"
        ctx["trace_reason"] = "No Phoenix endpoint configured"
        return
    spans: list[dict] = []
    try:
        async with PhoenixClient(ctx["base_url"], api_key=ctx["api_key"]) as client:
            async for span in client.spans(
                project, limit=SPAN_PAGE_LIMIT, max_pages=SPAN_MAX_PAGES,
                start_time=(now - timedelta(days=TRACE_WINDOW_DAYS)).isoformat(), end_time=now.isoformat(),
            ):
                spans.append(slim_span(span))
    # Phoenix is an external source: any failure skips the trace rules, never the scan.
    except Exception as exc:
        status = getattr(exc, "status", 0)
        ctx["trace_status"] = "unavailable"
        ctx["trace_reason"] = (
            f"Phoenix project '{project}' not found" if status == 404
            else f"Phoenix request failed (HTTP {status})" if status
            else f"Phoenix unreachable ({type(exc).__name__})"
        )
        return
    ctx["kri"] = kri_from_spans(spans)
    ctx["trace_status"] = "ok" if spans else "no_traces"
    ctx["sample_capped"] = len(spans) >= SPAN_PAGE_LIMIT * SPAN_MAX_PAGES
    ctx["drift"] = _dependency_drift(ctx["declared"], spans)


async def _gather(agent_id: str | None, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from api.routers.registry import _agent_to_dict, _resolve_phoenix_endpoint
    from services.graph_service import build_adjacency

    notes: dict[str, Any] = {}
    async with get_db_session() as db:
        stmt = select(Agent).options(selectinload(Agent.governance_reviews)).order_by(Agent.id)
        if agent_id:
            stmt = stmt.where(Agent.id == agent_id)
        agents = list((await db.execute(stmt)).scalars().all())
        try:
            adjacency = await build_adjacency(db)
        except Exception as exc:
            log.warning("risk_scan.graph_failed", error=type(exc).__name__)
            adjacency = None
            notes["blastRadius"] = "unavailable"

        contexts = []
        for agent in agents:
            agent_dict = _agent_to_dict(agent)
            # Resolved for unlinked agents too: the endpoint-is-Phoenix rule needs the host.
            base_url, api_key = await _resolve_phoenix_endpoint(db, agent)
            contexts.append({
                "agent_id": agent.id,
                "agent": agent_dict,
                "declared": _declared(agent),
                "project": agent.phoenix_project,
                "base_url": base_url,
                "api_key": api_key,
                "financial": await live_financial(db, agent, agent_dict),
                "gate_states": _gate_states(agent, now),
                "blast_radius": _blast_radius(adjacency, agent.id),
            })
    return contexts, notes


def _apply_plan(db: AsyncSession, agent_id: str, rows: dict[str, AgentRisk], plan: dict[str, Any]) -> None:
    for item in plan["inserts"]:
        db.add(AgentRisk(id=secrets.token_hex(8), agent_id=agent_id, **item))
    for item in plan["updates"] + plan["closes"]:
        row = rows[item["id"]]
        for field, value in item["changes"].items():
            setattr(row, field, value)


async def _reconcile_agent(ctx: dict[str, Any], now: datetime, actor: str) -> dict[str, Any]:
    inputs = {
        "kri": ctx["kri"],
        "trace_status": ctx["trace_status"],
        "blast_radius_count": ctx["blast_radius"],
        "dependency_drift": ctx["drift"],
        "gate_states": ctx["gate_states"],
    }
    detected = detect_risks(ctx["agent"], phoenix_base_url=ctx["base_url"], **inputs)
    stored, _ = partition_findings(detected)
    unchecked = unevaluated_rules(**inputs)
    async with get_db_session() as db:
        if await db.get(Agent, ctx["agent_id"]) is None:
            return {"agentId": ctx["agent_id"], "status": "not_found"}
        rows = {r.id: r for r in (await db.execute(
            select(AgentRisk).where(AgentRisk.agent_id == ctx["agent_id"])
        )).scalars().all()}
        plan = reconcile([risk_row_dict(r) for r in rows.values()], stored, now, unevaluated=unchecked)
        _apply_plan(db, ctx["agent_id"], rows, plan)
        db.add(AuditLog(
            org_id=ORG_ID, actor=actor, action="risk_scan", entity_type="agent_risks",
            entity_id=ctx["agent_id"], changes={"counts": plan["counts"], "traceSignals": ctx["trace_status"]},
        ))
    return {
        "agentId": ctx["agent_id"],
        "status": "scanned",
        "findingCount": len(stored),
        "findings": stored,
        "financial": ctx["financial"],
        "reconcile": plan["counts"],
        "uncheckedRules": unchecked,
        "traceSignals": ctx["trace_status"],
        "traceReason": ctx.get("trace_reason"),
        "traceWindowDays": TRACE_WINDOW_DAYS,
        "sampleCapped": ctx["sample_capped"],
        "kri": ctx["kri"],
        "blastRadius": ctx["blast_radius"],
    }


_COMPACT_KEYS = ("findingCount", "reconcile", "traceSignals", "traceReason", "traceWindowDays",
                 "sampleCapped", "kri", "blastRadius")


async def scan_risks(agent_id: str | None = None, trigger: str = "manual", actor: str = "system") -> dict:
    """One agent, or every agent when agent_id is None. Phoenix being
    unreachable skips the trace rules for that agent only."""
    now = utcnow()
    contexts, notes = await _gather(agent_id, now)
    if agent_id and not contexts:
        return {"status": "error", "reason": f"Agent '{agent_id}' not found", "agentId": agent_id}

    results = []
    for ctx in contexts:
        await _trace_signals(ctx, now)
        results.append(await _reconcile_agent(ctx, now, actor))

    totals: dict[str, int] = {}
    for result in results:
        for key, value in (result.get("reconcile") or {}).items():
            totals[key] = totals.get(key, 0) + value
    summary = {
        "status": "ok",
        "trigger": trigger,
        "scannedAt": now.isoformat(),
        "agentCount": len(results),
        "totals": totals,
        "agents": {r["agentId"]: {k: r.get(k) for k in _COMPACT_KEYS} for r in results},
        **notes,
    }
    if agent_id:
        summary.update({k: v for k, v in results[0].items() if k != "status"})
    return summary
