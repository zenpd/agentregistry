"""Agent page — Overview tab API: header KPIs, key facts and context.md
(versions, rule-based insight, suggestions a person confirms or dismisses)."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Iterable, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import require_read, require_update
from api.routers.registry import _agent_to_dict, _resolve_phoenix_endpoint
from db.base import get_db_session
from db.models import Agent, AgentBudget, AgentRisk, Department, User
from governance import context_reader as cr
from governance import costing
from governance import risk_lifecycle as lifecycle
from orchestrations.risk_scan import live_financial, risk_row_dict
from services import context_service as ctx
from services.usage_repo import priced_usage
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Overview"])

GATES = ("arb", "security", "dp")

_OBSERVABILITY_TOKENS = frozenset({
    "phoenix", "arize", "langfuse", "langsmith", "otel", "opentelemetry", "otlp", "collector", "jaeger",
    "zipkin", "tempo", "grafana", "datadog", "applicationinsights", "honeycomb", "signoz", "helicone",
})
_OBSERVABILITY_PATHS = ("/v1/traces", "/v1/metrics", "/v1/logs", "/v1/spans")
_OBSERVABILITY_PORTS = {4317, 4318, 6006}

# Days since the last day with calls: (fresh up to, aging up to); older is stale.
_FRESHNESS_DAYS = {"Production": (1, 7)}
_FRESHNESS_DEFAULT = (7, 30)


def _host(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else f"//{url}").hostname or "").lower()
    except ValueError:
        return ""


def endpoint_warning(url: str | None, telemetry_urls: Iterable[str | None]) -> str | None:
    """Why an API endpoint looks like a telemetry/observability URL rather
    than the agent's own API, or None."""
    if not url or not url.strip():
        return None
    url = url.strip()
    host = _host(url)
    if host and host in {_host(t) for t in telemetry_urls if t}:
        return "Same host as this agent's Phoenix endpoint: this looks like the telemetry URL, not the agent's own API."
    try:
        parsed = urlparse(url if "://" in url else f"//{url}")
        port = parsed.port
    except ValueError:
        parsed, port = None, None
    path = (parsed.path if parsed else url).lower()
    tokens = set(re.split(r"[.\-_]", host)) if host else set()
    if tokens & _OBSERVABILITY_TOKENS or port in _OBSERVABILITY_PORTS or any(p in path for p in _OBSERVABILITY_PATHS):
        return "Looks like an observability (Phoenix / OpenTelemetry) URL rather than the agent's own API endpoint."
    return None


def freshness(stage: str | None, last_day: date | None, today: date) -> str | None:
    """fresh | aging | stale by days since the last day with calls; the
    allowance is tighter for Production."""
    if last_day is None:
        return None
    fresh, aging = _FRESHNESS_DAYS.get(stage or "", _FRESHNESS_DEFAULT)
    age = (today - last_day).days
    return "fresh" if age <= fresh else "aging" if age <= aging else "stale"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


async def _get_agent(db: AsyncSession, agent_id: str) -> Agent:
    # governance_reviews is eager-loaded because _agent_to_dict walks it while
    # scoring risk; lazy-loading it there raises MissingGreenlet under async.
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
    )).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _risk_score(db: AsyncSession, agent: Agent) -> dict:
    """The same population, scored by the same function, as the Risk tab.

    FINANCIAL findings are read live from waste_findings/cost_anomalies and
    deliberately never stored in agent_risks, so counting that table alone
    silently dropped them: one agent read 7 here and 8 on the Risk tab. Both
    now go through lifecycle.score, which is what keeps them from drifting
    apart again. Read-only on purpose — unlike the Risk tab this does not
    expire acceptances, which cannot change the totals since an expired
    acceptance is active either way.
    """
    rows = (await db.execute(select(AgentRisk).where(AgentRisk.agent_id == agent.id))).scalars().all()
    stored = [risk_row_dict(r) for r in rows]
    active = [r for r in stored if r["status"] in lifecycle.ACTIVE_STATUSES]
    financial = await live_financial(db, agent, _agent_to_dict(agent))
    scored = lifecycle.score(active + financial)
    return {"worst": scored["worst"], "openCounts": scored["countsBySeverity"], "total": scored["total"]}


async def _usage(db: AsyncSession, agent: Agent, today: date) -> tuple[dict, dict | None]:
    """(telemetry, budget). Budgets are informational only."""
    usage = await priced_usage(db, agent.id)
    rows, source = usage["rows"], usage["source"]
    active_days = [r["day"] for r in rows if (r.get("calls") or 0) > 0]
    last_day = max(active_days) if active_days else None
    linked = bool(agent.phoenix_project)
    status = {"phoenix": "ok", "seed": "demo"}.get(source, "no_usage_yet" if linked else "not_linked")
    telemetry = {
        "linked": linked,
        "phoenixProject": agent.phoenix_project,
        "status": status,
        "source": source,
        "lastIngestedAt": usage["last_ingested_at"],
        "lastActivityDate": last_day.isoformat() if last_day else None,
        "freshness": freshness(agent.lifecycle_stage, last_day, today) if source == "phoenix" else None,
    }

    row = await db.get(AgentBudget, agent.id)
    if row is None or not row.monthly_budget_cents:
        return telemetry, None
    budget = {
        "monthlyBudgetCents": row.monthly_budget_cents,
        "alertThresholdPct": row.alert_threshold_pct,
        "periodStart": costing.period_start(today, row.budget_reset_day).isoformat(),
        "source": source,
        "unpriced": usage["unpriced"],
    }
    if source == "none":
        return telemetry, {**budget, "state": "no_usage_data", "usedPct": None, "mtdCents": None}
    mtd = costing.month_to_date_cents(rows, today, row.budget_reset_day)
    status = costing.budget_status(mtd, row.monthly_budget_cents, row.alert_threshold_pct or 80)
    return telemetry, {**budget, "state": status["state"], "usedPct": status["used_pct"], "mtdCents": round(mtd, 2)}


async def _user_names(db: AsyncSession, ids: Iterable[str | None]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    result = await db.execute(select(User.id, User.name, User.email).where(User.id.in_(wanted)))
    return {r.id: r.name or r.email for r in result}


async def _versions(db: AsyncSession, agent_id: str) -> list[dict]:
    versions = await ctx.list_versions(db, agent_id)
    names = await _user_names(db, (v.saved_by for v in versions))
    return [{**ctx.version_to_dict(v), "savedBy": names.get(v.saved_by, v.saved_by)} for v in versions]


def _facts(agent: Agent, dept_name: str | None, telemetry_urls: list[str | None]) -> dict:
    return {
        "owner": agent.owner,
        "ownerContact": agent.owner_contact,
        "deptId": agent.dept_id,
        "dept": dept_name or agent.dept_id,
        "aiType": agent.ai_type,
        "function": agent.function,
        "version": agent.version,
        "modelName": agent.model_name,
        "modelProvider": agent.model_provider,
        "framework": agent.framework,
        "runtime": agent.runtime,
        "valueAmount": agent.value_amount,
        "valueType": agent.value_type,
        "hoursSavedMonthly": agent.hours_saved_monthly,
        "sla": agent.sla,
        "apiEndpoint": agent.api_endpoint,
        "apiEndpointWarning": endpoint_warning(agent.api_endpoint, telemetry_urls),
        "euAiActCategory": agent.eu_ai_act_category,
        "phoenixProject": agent.phoenix_project,
        "description": agent.description,
        "businessOutcome": agent.business_outcome,
        "tags": list(agent.tags or []),
        "source": agent.source,
        "createdAt": _iso(agent.created_at),
        "updatedAt": _iso(agent.updated_at),
    }


def _context_block(agent: Agent, insight: dict | None, versions: list[dict]) -> dict:
    present = insight is not None
    return {
        "present": present,
        "completenessPct": insight["completenessPct"] if present else 0,
        "sectionsPresent": insight["sectionsPresent"] if present else [],
        "sectionsMissing": insight["sectionsMissing"] if present else list(cr.TEMPLATE_SECTIONS),
        "summary": insight["summary"] if present else None,
        "llmStatus": insight["llmStatus"] if present else "not_run",
        "suggestedRiskCount": len(insight["suggestedRisks"]) if present else 0,
        "suggestedDependencyCount": len(insight["suggestedDependencies"]) if present else 0,
        "sizeBytes": len((agent.context_md or "").encode("utf-8")) if present else 0,
        "updatedAt": versions[0]["savedAt"] if versions else None,
        "versionCount": len(versions),
    }


@router.get("/agents/{agent_id}/overview")
async def agent_overview(agent_id: str, _=Depends(require_read)):
    today = datetime.now(timezone.utc).date()
    async with get_db_session() as db:
        agent = await _get_agent(db, agent_id)
        await ctx.ensure_initial_version(db, agent)
        dept = await db.get(Department, agent.dept_id) if agent.dept_id else None
        gates = await ctx.gate_statuses(db, agent.id)
        telemetry, budget = await _usage(db, agent, today)
        phoenix_base, _key = await _resolve_phoenix_endpoint(db, agent)
        telemetry_urls = [phoenix_base, agent.phoenix_endpoint, get_settings().phoenix_collector_endpoint]
        insight = await ctx.get_insight(db, agent)
        versions = await _versions(db, agent.id)
        return {
            "agentId": agent.id,
            "header": {
                "name": agent.name,
                "stage": agent.lifecycle_stage,
                "owner": agent.owner,
                "dept": dept.name if dept else agent.dept_id,
                "riskLevel": agent.risk_level,
                "riskScore": await _risk_score(db, agent),
                "gates": {g: gates.get(g, "Not Submitted") for g in GATES},
                "budget": budget,
                "telemetry": telemetry,
            },
            "facts": _facts(agent, dept.name if dept else None, telemetry_urls),
            "context": _context_block(agent, insight, versions),
        }


async def _context_payload(db: AsyncSession, agent: Agent) -> dict:
    insight = await ctx.get_insight(db, agent)
    return {
        "agentId": agent.id,
        "present": insight is not None,
        "content": agent.context_md or "",
        "versions": await _versions(db, agent.id),
        "insight": insight,
    }


@router.get("/agents/{agent_id}/context")
async def get_context(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _get_agent(db, agent_id)
        await ctx.ensure_initial_version(db, agent)
        return await _context_payload(db, agent)


class ContextUpdate(BaseModel):
    content: str = ""


@router.put("/agents/{agent_id}/context")
async def put_context(agent_id: str, body: ContextUpdate, user=Depends(require_update)):
    async with get_db_session() as db:
        agent = await _get_agent(db, agent_id)
        result = await ctx.save_context(db, agent, body.content, user["user_id"])
        return {**result, **await _context_payload(db, agent)}


@router.get("/agents/{agent_id}/context/versions/{version_id}")
async def get_context_version(agent_id: str, version_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        await _get_agent(db, agent_id)
        version = await ctx.get_version(db, agent_id, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        names = await _user_names(db, [version.saved_by])
        return {**ctx.version_to_dict(version, include_content=True), "savedBy": names.get(version.saved_by, version.saved_by)}


@router.get("/agents/{agent_id}/context/download")
async def download_context(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _get_agent(db, agent_id)
        if not (agent.context_md or "").strip():
            raise HTTPException(status_code=404, detail="This agent has no context.md")
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", agent.id) + "-context.md"
        return Response(
            content=agent.context_md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/context/template")
async def context_template(_=Depends(require_read)):
    return {
        "content": cr.TEMPLATE_MD,
        "sections": cr.TEMPLATE_SECTIONS,
        "minSectionChars": cr.MIN_SECTION_CHARS,
    }


class SuggestionAction(BaseModel):
    type: Literal["risk", "dependency"]
    key: Optional[str] = None
    name: Optional[str] = None


async def _suggestion_action(agent_id: str, body: SuggestionAction, user: dict, confirm: bool) -> dict:
    ref = body.key or body.name
    if not (ref or "").strip():
        raise HTTPException(status_code=422, detail="Send the suggestion's 'key' (risk) or 'name' (dependency)")
    async with get_db_session() as db:
        agent = await _get_agent(db, agent_id)
        action = ctx.confirm_suggestion if confirm else ctx.dismiss_suggestion
        try:
            result = await action(db, agent, body.type, ref, user["user_id"])
        except ctx.SuggestionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {**result, "insight": await ctx.get_insight(db, agent)}


@router.post("/agents/{agent_id}/context/suggestions/confirm")
async def confirm_context_suggestion(agent_id: str, body: SuggestionAction, user=Depends(require_update)):
    return await _suggestion_action(agent_id, body, user, confirm=True)


@router.post("/agents/{agent_id}/context/suggestions/dismiss")
async def dismiss_context_suggestion(agent_id: str, body: SuggestionAction, user=Depends(require_update)):
    return await _suggestion_action(agent_id, body, user, confirm=False)
