"""Agent page — Revenue & Expenditure tab API: value vs cost of ownership,
declared hosting cost, Azure resource links and the infra-cost collector.

Overrides the older /agents/{id}/economics, /value/economics and
/agents/{id}/cost/business-outcome in registry.py, keeping their keys.
Showback only: nothing here pauses, throttles or changes an agent.
"""
from __future__ import annotations

import secrets
from datetime import date
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from api.auth import require_admin, require_read, require_update
from costs.azure_cost_collector import config_status
from db.base import get_db_session
from db.models import Agent, AgentInfraProfile, AgentResourceLink, AuditLog, JobRun
from governance.economics import load_economics
from orchestrations import job_runner
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Revenue & Expenditure"])

ORG_ID = "org-default"
INFRA_JOB = "infra_costs"
SETUP_STEPS = [
    "Set AZURE_COST_SCOPE to the subscription or resource group to read, e.g. /subscriptions/<id>.",
    "Create a service principal and set AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET.",
    "Assign that principal the built-in 'Cost Management Reader' role on the scope.",
    "Tag each agent's Azure resources with {tag}=<agent id>, or link shared resources below with a share %.",
]


async def _agent_or_404(db, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _audit(db, user: dict, action: str, entity_type: str, entity_id: str, changes: dict) -> None:
    db.add(AuditLog(org_id=ORG_ID, actor=user["user_id"], action=action, entity_type=entity_type,
                    entity_id=entity_id, changes=changes))


# ── Economics ────────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/economics")
async def agent_economics_endpoint(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        return (await load_economics(db, [agent]))[agent_id]


@router.get("/value/economics")
async def portfolio_economics(_=Depends(require_read)):
    """Every agent's economics plus portfolio totals. Unknown token cost
    counts as nothing in the totals; agentsWithoutUsageData says how many."""
    async with get_db_session() as db:
        agents = list((await db.execute(select(Agent))).scalars().all())
        econ = await load_economics(db, agents)
    rows = sorted(econ.values(), key=lambda e: e["revenueCents"], reverse=True)
    value = sum(e["valueCents"] for e in rows)
    cost = round(sum(e["totalCostCents"] for e in rows), 2)
    token_sources = [e["tokenSource"] for e in rows]
    infra_sources = [e["infraSource"] for e in rows]
    return {
        "totalRevenueCents": value,
        "totalExpenditureCents": cost,
        "totalNetCents": round(value - cost, 2),
        "totalValueCents": value,
        "totalRealizedValueCents": sum(e["realizedValueCents"] for e in rows),
        "totalTokenCostCents": round(sum(e["tokenCostCents"] or 0 for e in rows), 2),
        "totalInfraCostCents": round(sum(e["infraCostCents"] for e in rows), 2),
        "totalCostCents": cost,
        "agentsWithoutUsageData": sum(1 for e in rows if e["tokenCostCents"] is None),
        "tokenSources": {s: token_sources.count(s) for s in sorted(set(token_sources))},
        "infraSources": {s: infra_sources.count(s) for s in sorted(set(infra_sources))},
        "hourlyRate": get_settings().blended_hourly_rate_usd,
        "agents": rows,
    }


@router.get("/agents/{agent_id}/cost/business-outcome")
async def cost_per_outcome(agent_id: str, _=Depends(require_read)):
    """Monthly cost (run rate) per dollar of declared monthly value. The
    snake_case keys are the endpoint's original contract."""
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        e = (await load_economics(db, [agent]))[agent_id]
    total = e["totalCostCents"] / 100
    outcome = e["valueCents"] / 100
    ratio = round(total / outcome, 4) if outcome > 0 and e["costComplete"] else None
    return {
        "agent_id": agent_id,
        "total_cost": round(total, 2),
        "business_outcome": outcome,
        "cost_per_outcome": ratio,
        "efficiency_rating": e["efficiencyRating"],
        "basis": "monthly_run_rate",
        "month": e["period"]["month"],
        "tokenSource": e["tokenSource"],
        "infraSource": e["infraSource"],
        "costComplete": e["costComplete"],
    }


# ── Declared hosting cost ────────────────────────────────────────────────────

class InfraComponent(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    costCents: Optional[int] = Field(None, ge=0)
    recurring: bool = True


class InfraProfileIn(BaseModel):
    platform: Optional[str] = Field(None, max_length=100)
    resourceGroup: Optional[str] = Field(None, max_length=255)
    monthlyCostCents: Optional[int] = Field(None, ge=0, le=1_000_000_000)
    components: list[Union[InfraComponent, str]] = Field(default_factory=list, max_length=50)
    effectiveFrom: Optional[date] = None

    @field_validator("platform", "resourceGroup")
    @classmethod
    def _blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None


def _components(items: list) -> list[dict]:
    out = []
    for c in items:
        name = (c if isinstance(c, str) else c.name).strip()[:200]
        if name:
            cost, recurring = (None, True) if isinstance(c, str) else (c.costCents, c.recurring)
            out.append({"name": name, "costCents": cost, "recurring": recurring})
    return out


def _profile_dict(agent_id: str, p: AgentInfraProfile | None) -> dict:
    if p is None:
        return {"agentId": agent_id, "exists": False, "declared": False, "platform": None, "resourceGroup": None,
                "monthlyCostCents": None, "components": [], "effectiveFrom": None, "updatedBy": None, "updatedAt": None}
    return {
        "agentId": agent_id,
        "exists": True,
        "declared": (p.monthly_cost_cents or 0) > 0,
        "platform": p.platform,
        "resourceGroup": p.resource_group,
        "monthlyCostCents": p.monthly_cost_cents or 0,
        "components": list(p.components or []),
        "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
        "updatedBy": p.updated_by,
        "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/agents/{agent_id}/infra-profile")
async def get_infra_profile(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        return _profile_dict(agent_id, await db.get(AgentInfraProfile, agent_id))


@router.put("/agents/{agent_id}/infra-profile")
async def put_infra_profile(agent_id: str, body: InfraProfileIn, user=Depends(require_update)):
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        profile = await db.get(AgentInfraProfile, agent_id)
        before = _profile_dict(agent_id, profile)
        if profile is None:
            profile = AgentInfraProfile(agent_id=agent_id)
            db.add(profile)
        profile.platform = body.platform
        profile.resource_group = body.resourceGroup
        profile.monthly_cost_cents = body.monthlyCostCents or 0
        profile.components = _components(body.components)
        profile.effective_from = body.effectiveFrom
        profile.updated_by = user["user_id"]
        keys = ("platform", "resourceGroup", "monthlyCostCents", "components", "effectiveFrom")
        after = {"platform": profile.platform, "resourceGroup": profile.resource_group,
                 "monthlyCostCents": profile.monthly_cost_cents, "components": profile.components,
                 "effectiveFrom": profile.effective_from.isoformat() if profile.effective_from else None}
        _audit(db, user, "infra_profile.update", "agent", agent_id,
               {"before": {k: before[k] for k in keys}, "after": after})
        await db.flush()
        await db.refresh(profile)
        return _profile_dict(agent_id, profile)


# ── Azure resource links ─────────────────────────────────────────────────────

class ResourceLinkIn(BaseModel):
    resourceId: str = Field(..., max_length=500)
    sharePct: int = Field(100, ge=1, le=100)

    @field_validator("resourceId")
    @classmethod
    def _arm_id(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.lower().startswith("/subscriptions/") or len(v.split("/")) < 3 or not v.split("/")[2]:
            raise ValueError("resourceId must be an Azure resource id starting with /subscriptions/<id>")
        return v


def _link_dict(link: AgentResourceLink) -> dict:
    parts = link.resource_id.strip("/").split("/")
    return {
        "id": link.id,
        "agentId": link.agent_id,
        "resourceId": link.resource_id,
        "sharePct": link.share_pct,
        "kind": "resource_group" if len(parts) == 4 and parts[2].lower() == "resourcegroups"
        else "subscription" if len(parts) == 2 else "resource",
        "createdAt": link.created_at.isoformat() if link.created_at else None,
    }


async def _claimed_share(db, resource_id: str) -> int:
    """Total share % every agent has linked on this exact resource id."""
    total = (await db.execute(
        select(func.sum(AgentResourceLink.share_pct)).where(func.lower(AgentResourceLink.resource_id) == resource_id.lower())
    )).scalar()
    return int(total or 0)


@router.get("/agents/{agent_id}/resource-links")
async def list_resource_links(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        links = (await db.execute(
            select(AgentResourceLink).where(AgentResourceLink.agent_id == agent_id).order_by(AgentResourceLink.created_at)
        )).scalars().all()
        out = []
        for link in links:
            out.append({**_link_dict(link), "totalClaimedPct": await _claimed_share(db, link.resource_id)})
    return {"agentId": agent_id, "links": out}


@router.post("/agents/{agent_id}/resource-links", status_code=201)
async def add_resource_link(agent_id: str, body: ResourceLinkIn, user=Depends(require_update)):
    async with get_db_session() as db:
        await _agent_or_404(db, agent_id)
        existing = (await db.execute(select(AgentResourceLink).where(
            AgentResourceLink.agent_id == agent_id,
            func.lower(AgentResourceLink.resource_id) == body.resourceId.lower(),
        ))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="This resource is already linked to the agent.")
        link = AgentResourceLink(id=secrets.token_hex(12), agent_id=agent_id,
                                 resource_id=body.resourceId, share_pct=body.sharePct)
        db.add(link)
        _audit(db, user, "resource_link.create", "agent", agent_id,
               {"linkId": link.id, "resourceId": body.resourceId, "sharePct": body.sharePct})
        await db.flush()
        await db.refresh(link)
        claimed = await _claimed_share(db, body.resourceId)
    warning = (f"Agents together claim {claimed}% of this resource; the collector scales the shares down to 100%."
               if claimed > 100 else None)
    return {**_link_dict(link), "totalClaimedPct": claimed, "warning": warning}


@router.delete("/agents/{agent_id}/resource-links/{link_id}")
async def delete_resource_link(agent_id: str, link_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        link = await db.get(AgentResourceLink, link_id)
        if link is None or link.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Resource link not found")
        removed = _link_dict(link)
        await db.delete(link)
        _audit(db, user, "resource_link.delete", "agent", agent_id,
               {"linkId": link_id, "resourceId": removed["resourceId"], "sharePct": removed["sharePct"]})
    return {"deleted": True, "link": removed}


# ── Infra-cost collector (Azure Cost Management) ─────────────────────────────

@router.get("/infra-costs/status")
async def infra_costs_status(_=Depends(require_read)):
    status = config_status(get_settings())
    async with get_db_session() as db:
        last = (await db.execute(
            select(JobRun).where(JobRun.job == INFRA_JOB).order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(1)
        )).scalar_one_or_none()
    return {
        **status,
        "status": "configured" if status["configured"] else "not_configured",
        "lastRun": job_runner.run_to_dict(last),
        "requiredRole": "Cost Management Reader",
        "setup": [s.format(tag=status["tagKey"]) for s in SETUP_STEPS],
    }


@router.post("/infra-costs/collect")
async def collect_infra_costs_now(
    agent_id: Optional[str] = Query(None, alias="agentId"),
    days: int = Query(7, ge=1, le=90),
    user=Depends(require_admin),
):
    if agent_id:
        async with get_db_session() as db:
            await _agent_or_404(db, agent_id)
    result = await job_runner.run_job(INFRA_JOB, agent_id=agent_id, trigger="manual", days=days)
    async with get_db_session() as db:
        _audit(db, user, "infra_costs.collect", "job", INFRA_JOB,
               {"agentId": agent_id, "days": days, "runId": result["runId"], "status": result["status"]})
    return job_runner.for_display(result)
