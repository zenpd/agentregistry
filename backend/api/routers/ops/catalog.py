"""The catalogue for other tools: every agent certified for reuse, published as
an A2A agent card. A card is built from the registry record each time, so it
never goes stale."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.auth import require_read
from db.base import get_db_session
from db.models import Agent
from services import reuse_repo
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Catalogue"])


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "skill"


def agent_card(a: Agent, certified: bool) -> dict:
    base = get_settings().app_base_url.rstrip("/")
    skills = [{"id": _slug(c), "name": c, "description": c, "tags": [a.ai_type] if a.ai_type else [],
               "inputModes": ["text"], "outputModes": ["text"]} for c in (a.capabilities or [])]
    return {
        "name": a.name,
        "description": a.description or a.business_outcome or a.name,
        "url": a.api_endpoint or None,
        "version": a.version or "unversioned",
        "provider": {"organization": a.owner or "Unassigned", "url": base},
        "documentationUrl": f"{base}/agents/{a.id}",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
        "skills": skills,
        # Registry facts other tools may want; not part of the A2A fields above.
        "x-agent-registry": {"id": a.id, "stage": a.lifecycle_stage, "certifiedForReuse": certified,
                             "inputs": a.inputs or [], "outputs": a.outputs or [], "sla": a.sla, "rateLimit": a.rate_limit},
    }


@router.get("/catalog/agent-cards")
async def catalogue(_=Depends(require_read)):
    """Agents certified for reuse, each with the address of its card."""
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).options(selectinload(Agent.governance_reviews)))).scalars().all()
        certs = await reuse_repo.certifications(db, agents)
    return [{"id": a.id, "name": a.name, "card": f"/api/v1/catalog/agents/{a.id}/agent-card.json"}
            for a in agents if certs[a.id]["certified"]]


@router.get("/catalog/agents/{agent_id}/agent-card.json")
async def card(agent_id: str, preview: bool = False, _=Depends(require_read)):
    """The agent's A2A card. Published only once it is certified for reuse;
    preview=true shows what would be published."""
    async with get_db_session() as db:
        a = (await db.execute(select(Agent).options(selectinload(Agent.governance_reviews)).where(Agent.id == agent_id))).scalar_one_or_none()
        if a is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        certified = bool((await reuse_repo.certifications(db, [a]))[a.id]["certified"])
    if not certified and not preview:
        raise HTTPException(status_code=409, detail="Not published: the agent is not certified for reuse yet.")
    return {**agent_card(a, certified), **({"x-preview": True} if not certified else {})}
