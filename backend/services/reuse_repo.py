"""DB side of governance/reuse.py: certification and registry-card figures
for many agents at once, each computed the way its own tab computes it for
one agent (Risk tab for risk counts, Tokenomics tab for cost per call)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent, AgentRisk, CostAnomaly, WasteFinding
from governance import reuse
from governance import risk_lifecycle as lifecycle
from governance.costing import cost_per_call_cents, effective_rows, price_rows
from governance.economics import load_economics
from governance.risk_detection import financial_findings
from orchestrations.risk_scan import as_utc, cost_anomaly_dict, risk_row_dict, waste_dict
from services.usage_repo import load_aliases, load_prices, load_usage_rows_bulk

# Same trailing window as the Tokenomics tab's default "Cost / call".
COST_WINDOW_DAYS = 30


def agent_mapping(agent: Agent) -> dict[str, Any]:
    """The plain fields governance/reuse.py reads."""
    return {
        "id": agent.id, "name": agent.name, "description": agent.description,
        "business_outcome": agent.business_outcome, "capabilities": agent.capabilities or [],
        "tags": agent.tags or [], "inputs": agent.inputs or [], "outputs": agent.outputs or [],
        "ai_type": agent.ai_type, "stage": agent.lifecycle_stage, "owner": agent.owner,
        "owner_contact": agent.owner_contact, "api_endpoint": agent.api_endpoint,
        "sla": agent.sla, "rate_limit": agent.rate_limit,
    }


async def risk_counts(db: AsyncSession, agents: Sequence[Agent]) -> dict[str, dict[str, int]]:
    """Active findings by severity per agent: the stored register plus live
    FINANCIAL findings, scored by the function the Risk tab uses."""
    ids = [a.id for a in agents]
    if not ids:
        return {}
    stored: dict[str, list[dict]] = defaultdict(list)
    for row in (await db.execute(select(AgentRisk).where(AgentRisk.agent_id.in_(ids)))).scalars().all():
        entry = risk_row_dict(row)
        if entry["status"] in lifecycle.ACTIVE_STATUSES:
            stored[row.agent_id].append(entry)
    anomalies: dict[str, list[dict]] = defaultdict(list)
    for row in (await db.execute(
        select(CostAnomaly).where(CostAnomaly.agent_id.in_(ids), CostAnomaly.resolved_at.is_(None))
    )).scalars().all():
        anomalies[row.agent_id].append(cost_anomaly_dict(row))
    waste: dict[str, list[dict]] = defaultdict(list)
    for row in (await db.execute(
        select(WasteFinding).where(WasteFinding.agent_id.in_(ids), WasteFinding.status == "open")
    )).scalars().all():
        waste[row.agent_id].append(waste_dict(row))
    economics = await load_economics(db, agents)

    out = {}
    for agent in agents:
        flags = [f for f in (economics.get(agent.id) or {}).get("financialFlags") or [] if isinstance(f, dict)]
        financial = financial_findings(
            financial_flags=flags, cost_anomalies=anomalies[agent.id], waste_findings=waste[agent.id],
        )
        out[agent.id] = lifecycle.score(stored[agent.id] + financial)["countsBySeverity"]
    return out


def _reviews(agent: Agent) -> dict[str, dict[str, Any]]:
    return {r.gate: {"status": r.status, "expires_at": as_utc(r.expires_at)} for r in agent.governance_reviews or []}


async def certifications(db: AsyncSession, agents: Sequence[Agent], now: datetime | None = None) -> dict[str, dict]:
    """Certified-for-reuse status per agent. governance_reviews must be
    eager-loaded on every agent passed in."""
    now = now or datetime.now(timezone.utc)
    counts = await risk_counts(db, agents)
    return {a.id: reuse.certification(a.lifecycle_stage, _reviews(a), counts.get(a.id, {}), now) for a in agents}


async def cost_per_call(db: AsyncSession, agent_ids: Sequence[str], today: date | None = None) -> dict[str, dict]:
    """{costPerCallCents, source, pricing} per agent over the trailing 30
    days. pricing is 'ok', 'partial' (some calls ran on a model with no
    price, so the figure is a lower bound) or 'missing' (nothing priced, so
    the cost is unknown and reported as None rather than a false $0).

    One query for every agent's usage (load_usage_rows_bulk), not one query
    per agent — the registry list page calls this for every card on the
    page, so a per-agent loop here was an N+1."""
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=COST_WINDOW_DAYS - 1)
    prices, aliases = await load_prices(db), await load_aliases(db)
    raw_by_agent = await load_usage_rows_bulk(db, agent_ids)
    out = {}
    for agent_id in agent_ids:
        rows, source = effective_rows(raw_by_agent.get(agent_id, []))
        priced, _ = price_rows(rows, prices, aliases)
        window = [r for r in priced if start <= r["day"] <= today]
        unpriced = [r for r in window if not r["priced"]]
        pricing = "ok" if not unpriced else "missing" if len(unpriced) == len(window) else "partial"
        cpc = None if pricing == "missing" else cost_per_call_cents(window)
        out[agent_id] = {
            "costPerCallCents": None if cpc is None else round(cpc, 4),
            "source": source,
            "pricing": pricing,
        }
    return out
