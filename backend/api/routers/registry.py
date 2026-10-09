"""Agent Registry API routers — agents, governance, discovery, tokenomics, value, waste, admin."""
from __future__ import annotations

import json
import re
import secrets
from urllib.parse import urlparse
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, func, and_, case, delete, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.base import get_db_session
from db.models import (
    Agent, Department, Organization, GovernanceReview, GovernanceException,
    Discovery, AgentTokenUsage, ModelTokenPrice, AgentBudget, WasteFinding,
    CostAnomaly, User, AuditLog, AgentIdentity, AgentMetric, PhoenixConfig, AgentRisk, AgentAccessRequest,
    ModelRouting, AgentInfraProfile, AgentResourceLink, AgentInfraCost, AgentContextVersion, AgentContextInsight,
    Insight, InsightFeedback, ContentAuditOptIn, AgentFieldUpdate, AgentRecordCheck,
    ClassificationRecord, AgentVersion, AgentRetirement, EvidenceVerdict, ObservedConsumer,
    ValueAttestation, AgentOutcome, Incident,
)
from api.auth import (
    hash_password, verify_password, create_access_token,
    require_create, require_read, require_update, require_delete, require_admin,
    get_current_user
)
from governance import reuse
from services import reuse_repo
from services.usage_repo import priced_usage
from shared.config import get_settings

# Tables that reference an agent without an ORM cascade.
_AGENT_OWNED_TABLES = (
    AgentAccessRequest, GovernanceException, WasteFinding, CostAnomaly, AgentRisk, AgentMetric, ModelRouting,
    AgentInfraProfile, AgentResourceLink, AgentInfraCost, AgentContextVersion, AgentContextInsight,
    Insight, ContentAuditOptIn, AgentFieldUpdate, AgentRecordCheck,
    ClassificationRecord, AgentVersion, AgentRetirement, EvidenceVerdict, ObservedConsumer,
    ValueAttestation, AgentOutcome, Incident,
)

# ── Routers ──────────────────────────────────────────────────────────────────

agents_router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])
governance_router = APIRouter(prefix="/api/v1/governance", tags=["Governance"])
discovery_router = APIRouter(prefix="/api/v1/discoveries", tags=["Discovery"])
tokenomics_router = APIRouter(prefix="/api/v1", tags=["Tokenomics"])
graph_router = APIRouter(prefix="/api/v1/graph", tags=["Graph"])
value_waste_router = APIRouter(prefix="/api/v1", tags=["Value & Waste"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
# Distinct from discovery_router above (/api/v1/discoveries — SHADOW-AI
# detection of unregistered apps, an unrelated existing concept): this one
# is real-trace discovery FOR an already-onboarded agent, reading Phoenix's
# REST API — see discovery/phoenix_client.py and discovery/reconstruct.py.
phoenix_router = APIRouter(prefix="/api/v1/phoenix", tags=["Phoenix Discovery"])


# ── Schemas ──────────────────────────────────────────────────────────────────

AI_TYPES = [
    "Autonomous Agent", "Copilot / Assistant", "Predictive / ML Model",
    "Generative AI Feature", "Conversational AI / Chatbot", "Computer Vision Model",
]


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    dept: str = ""
    owner: str = ""
    stage: str = "Ideation"
    ai_type: str = "Autonomous Agent"
    description: str = ""
    business_outcome: str = ""
    value_amount: int = 0
    value_type: str = ""
    hours_saved_monthly: int = 0
    enterprise_systems: List[str] = []
    databases: List[str] = []
    knowledge_bases: List[str] = []
    mcp_servers: List[str] = []
    calls: List[str] = []
    consumers: List[str] = []
    inputs: List[str] = []
    outputs: List[str] = []
    api_endpoint: str = ""
    sla: str = ""
    tags: List[str] = []
    model_name: str = ""          # left empty unless known: the registry fills it in from real usage
    risk_level: str = "LOW"
    phoenix_project: str = ""
    # "" means "use the common org-wide endpoint" (PhoenixConfig / Settings
    # tab) — the onboarding form's dropdown only sends a value here when the
    # user picked "custom endpoint for this app".
    phoenix_endpoint: str = ""
    # Optional free-form markdown context the owner pastes in at onboarding
    # time — shown verbatim on the agent's own page, never parsed.
    context_md: str = ""
    capabilities: List[str] = []
    rate_limit: str = Field("", max_length=255)
    owner_contact: str = Field("", max_length=255)
    # Required when similar agents already exist: why none of them fit.
    reuse_justification: str = Field("", max_length=4000)
    # Required when the agent is registered at a stage after Ideation (for
    # example an agent that is already live): why it skips the earlier gates.
    stage_reason: str = Field("", max_length=1000)
    version: str = Field("", max_length=50)
    # A certified agent whose contract this registration started from.
    started_from_agent_id: str = Field("", max_length=64)

    @validator("capabilities", "inputs", "outputs")
    def validate_lists(cls, v):
        return reuse.clean_list(v)

    @validator("stage")
    def validate_stage(cls, v):
        valid = ["Ideation", "Development", "Testing", "Production", "Deprecated"]
        if v not in valid:
            raise ValueError(f"Invalid stage. Must be one of: {', '.join(valid)}")
        return v

    @validator("ai_type")
    def validate_ai_type(cls, v):
        if v not in AI_TYPES:
            raise ValueError(f"Invalid ai_type. Must be one of: {', '.join(AI_TYPES)}")
        return v

    @validator("risk_level")
    def validate_risk_level(cls, v):
        if v not in ["LOW", "MEDIUM", "HIGH"]:
            raise ValueError("Invalid risk_level. Must be one of: LOW, MEDIUM, HIGH")
        return v

    @validator("value_type")
    def validate_value_type(cls, v):
        if not v:
            return v
        valid = [
            "Cost avoidance", "Revenue influenced", "Revenue retained",
            "Projected cost avoidance", "Projected run-rate", "Projected revenue influenced",
            "Retired", "Not yet quantified"
        ]
        if v not in valid:
            raise ValueError(f"Invalid value_type. Must be one of: {', '.join(valid)}")
        return v


class SimilarQuery(BaseModel):
    name: str = ""
    description: str = ""
    business_outcome: str = ""
    capabilities: List[str] = []
    api_endpoint: str = ""


MIN_REUSE_JUSTIFICATION_CHARS = 20


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    value_amount: Optional[int] = None
    risk_level: Optional[str] = None
    risk_note: Optional[str] = None
    at_risk: Optional[bool] = None
    # Links this agent to the Phoenix project its real traces export under —
    # the only way to back-fill this on an agent registered before the field
    # existed (there's deliberately no auto-guess from the agent name; see
    # Agent.phoenix_project's comment in db/models.py).
    phoenix_project: Optional[str] = None
    phoenix_endpoint: Optional[str] = None
    context_md: Optional[str] = None
    owner_contact: Optional[str] = Field(None, max_length=255)
    # Department id; stored as dept_id.
    dept: Optional[str] = Field(None, max_length=64)
    ai_type: Optional[str] = None
    business_outcome: Optional[str] = None
    hours_saved_monthly: Optional[int] = Field(None, ge=0)

    @validator("name")
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip() if v else v

    @validator("value_amount")
    def validate_value_amount(cls, v):
        if v is not None and v < 0:
            raise ValueError("Value cannot be negative")
        return v

    @validator("ai_type")
    def validate_ai_type(cls, v):
        if v is not None and v not in AI_TYPES:
            raise ValueError(f"Invalid ai_type. Must be one of: {', '.join(AI_TYPES)}")
        return v


class GateUpdate(BaseModel):
    status: str

    @validator("status")
    def validate_status(cls, v):
        valid = ["Not Submitted", "In Review", "Changes Requested", "Approved with Conditions", "Approved"]
        if v not in valid:
            raise ValueError(f"Must be one of: {', '.join(valid)}")
        return v


class ExceptionCreate(BaseModel):
    agentId: str
    gate: str
    reason: str
    expiresAt: str
    approvedBy: str = ""

    @validator("gate")
    def validate_gate(cls, v):
        if v not in ["arb", "security", "dp"]:
            raise ValueError("Invalid gate")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


# The persona roles. Recorded on every user; enforced only when RBAC is on
# (USE_Rbac in api/auth.py).
from api.auth import ROLES as _ROLES
USER_ROLES = tuple(_ROLES)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    role: str = "Executive Viewer"
    password: str = Field(..., min_length=8, max_length=128)
    # Required for an Auditor: the last day the account can sign in.
    accessUntil: Optional[date] = None


def _auditor_end(role: str, access_until: Optional[date]) -> None:
    if role == "Auditor":
        if access_until is None:
            raise HTTPException(status_code=422, detail="An Auditor needs an end date: the last day the account can sign in.")
        if access_until < date.today():
            raise HTTPException(status_code=422, detail="The end date of an Auditor cannot be in the past.")


# ── Auth Router ──────────────────────────────────────────────────────────────

@auth_router.post("/login")
async def login(req: LoginRequest):
    async with get_db_session() as db:
        # Emails are matched without regard to case: Bob@x.com and bob@x.com are one person.
        result = await db.execute(select(User).where(func.lower(User.email) == req.email.strip().lower(),
                                                     User.is_active == True))
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user.id, user.role)
        return {"access_token": token, "token_type": "bearer", "user": {
            "id": user.id, "name": user.name, "email": user.email, "role": user.role
        }}


@auth_router.get("/config")
async def auth_config():
    """Public, before sign-in: whether the login page may show the local demo
    account (development only)."""
    return {"showDemoLogin": get_settings().app_env == "development"}


class AwayBody(BaseModel):
    awayUntil: Optional[date] = None
    deputyUserId: Optional[str] = None


@auth_router.put("/me/away")
async def set_my_away(body: AwayBody, user=Depends(get_current_user)):
    """Away until a date, with a deputy who receives your review notices meanwhile. Empty clears it."""
    async with get_db_session() as db:
        me_row = await db.get(User, user.get("user_id"))
        if me_row is None:
            raise HTTPException(status_code=404, detail="User not found")
        if body.deputyUserId and (body.deputyUserId == me_row.id or await db.get(User, body.deputyUserId) is None):
            raise HTTPException(status_code=422, detail="The deputy must be another existing user.")
        before = (str(me_row.away_until) if me_row.away_until else None, me_row.deputy_user_id)
        me_row.away_until, me_row.deputy_user_id = body.awayUntil, body.deputyUserId or None
        db.add(AuditLog(org_id="org-default", actor=me_row.id, action="user_update", entity_type="user", entity_id=me_row.id,
                        changes={"awayUntil": {"from": before[0], "to": str(body.awayUntil) if body.awayUntil else None},
                                 "deputyUserId": {"from": before[1], "to": body.deputyUserId or None}}))
    return {"awayUntil": body.awayUntil.isoformat() if body.awayUntil else None, "deputyUserId": body.deputyUserId or None}


@auth_router.get("/me")
async def me(user=Depends(get_current_user)):
    """Who is signed in: shown in the top bar, and used by screens that act as this person."""
    async with get_db_session() as db:
        row = await db.get(User, user.get("user_id"))
    from api.auth import permissions_of

    return {**user, "name": row.name if row else None, "email": row.email if row else None,
            "accountRole": row.role if row else None, **permissions_of(user.get("role", "")),
            "awayUntil": row.away_until.isoformat() if row and row.away_until else None,
            "deputyUserId": row.deputy_user_id if row else None}


# ── Agents Router ────────────────────────────────────────────────────────────

@agents_router.get("/")
async def list_agents(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    dept: str = "",
    stage: str = "",
    type: str = "",
    q: str = "",
    certified: bool = False,
    user=Depends(require_read)
):
    """q searches what agents do (name, capabilities, tags, description,
    outcome, inputs/outputs), not only names; with q, results are ranked by
    relevance. certified=true keeps only agents certified for reuse."""
    async with get_db_session() as db:
        query = select(Agent).options(selectinload(Agent.governance_reviews))
        if dept:
            query = query.where(Agent.dept_id == dept)
        if stage:
            query = query.where(Agent.lifecycle_stage == stage)
        if type:
            query = query.where(Agent.ai_type == type)
        agents = (await db.execute(query.order_by(Agent.value_amount.desc(), Agent.name))).scalars().all()

        matches: dict[str, dict] = {}
        if q.strip():
            for a in agents:
                m = reuse.search_match(q, reuse_repo.agent_mapping(a))
                if m is not None:
                    matches[a.id] = m
            # Stable sort: equal relevance keeps the value order.
            agents = sorted((a for a in agents if a.id in matches), key=lambda a: -matches[a.id]["score"])

        certs: dict[str, dict] = {}
        if certified:
            certs = await reuse_repo.certifications(db, agents)
            agents = [a for a in agents if certs[a.id]["certified"]]

        total = len(agents)
        if q.strip() and page == 1 and not (dept or stage or type or certified):
            # Searches that find nothing are the signal for a new shared agent (Programme health).
            from api.routers.ops.reuse_ops import log_search
            await log_search(user.get("user_id"), q, total)
        page_agents = agents[(page - 1) * limit: page * limit]
        if not certified:
            certs = await reuse_repo.certifications(db, page_agents)
        costs = await reuse_repo.cost_per_call(db, [a.id for a in page_agents])
        dept_names = dict((await db.execute(select(Department.id, Department.name))).all())

        return {
            "data": [
                {
                    **_agent_to_dict(a, dept_name=dept_names.get(a.dept_id)),
                    "reuse": certs[a.id],
                    "card": {**costs[a.id], "consumerCount": len(a.consumers or [])},
                    "matchedTerms": matches[a.id]["matched"] if a.id in matches else [],
                }
                for a in page_agents
            ],
            "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}
        }


async def _similar(db: AsyncSession, candidate: dict) -> list[dict]:
    agents = (await db.execute(
        select(Agent).options(selectinload(Agent.governance_reviews))
    )).scalars().all()
    found = reuse.similar_agents(candidate, [reuse_repo.agent_mapping(a) for a in agents])
    if not found:
        return []
    by_id = {a.id: a for a in agents}
    certs = await reuse_repo.certifications(db, [by_id[m["id"]] for m in found])
    return [{**m, "certified": certs[m["id"]]["certified"]} for m in found]


@agents_router.post("/similar")
async def similar_agents(body: SimilarQuery, _=Depends(require_read)):
    """Existing agents that already seem to do what a new registration
    describes — shown before registering so a team can reuse instead."""
    async with get_db_session() as db:
        return {"similar": await _similar(db, body.model_dump())}


@agents_router.get("/duplicates")
async def find_duplicates(_=Depends(require_read)):
    """F-36: Detect duplicate agents by name similarity and shared endpoints."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.name))
        agents = result.scalars().all()

        duplicates = []
        for i, a in enumerate(agents):
            for b in agents[i + 1:]:
                name_sim = _jaccard_similarity(a.name.lower(), b.name.lower())
                shared_endpoint = bool(a.api_endpoint and a.api_endpoint == b.api_endpoint)
                shared_systems = list(set(a.enterprise_systems or []) & set(b.enterprise_systems or []))

                if name_sim > 0.6 or shared_endpoint or len(shared_systems) >= 3:
                    duplicates.append({
                        "agent_a": {"id": a.id, "name": a.name, "dept": a.dept_id},
                        "agent_b": {"id": b.id, "name": b.name, "dept": b.dept_id},
                        "similarity": round(name_sim, 2),
                        "shared_endpoint": shared_endpoint,
                        "shared_systems": shared_systems,
                    })

        return {"duplicates": duplicates, "count": len(duplicates)}


def _jaccard_similarity(a: str, b: str) -> float:
    """Simple Jaccard similarity on word sets."""
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


@agents_router.get("/{agent_id}")
async def get_agent(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        dept_name = None
        if agent.dept_id:
            dept = await db.get(Department, agent.dept_id)
            dept_name = dept.name if dept else None
        # Reuse status rides along so the agent page can show the full
        # certification checklist above every tab, not only on Integrate.
        reuse_status = (await reuse_repo.certifications(db, [agent]))[agent.id]
        # Other records linked to the same Phoenix project: usually the same app registered twice.
        shared = []
        if agent.phoenix_project:
            shared = [{"id": i, "name": n} for i, n in (await db.execute(
                select(Agent.id, Agent.name).where(Agent.phoenix_project == agent.phoenix_project, Agent.id != agent.id))).all()]
        return {**_agent_to_dict(agent, dept_name=dept_name), "reuse": reuse_status, "sharedProject": shared}


@agents_router.post("/")
async def create_agent(agent: AgentCreate, user=Depends(require_create)):
    async with get_db_session() as db:
        # The duplicate check is enforced here, not only in the form, so no
        # client can register a look-alike without saying why.
        similar = await _similar(db, {
            "name": agent.name, "description": agent.description, "business_outcome": agent.business_outcome,
            "capabilities": agent.capabilities, "api_endpoint": agent.api_endpoint,
        })
        stage_reason = agent.stage_reason.strip()
        if agent.stage != "Ideation" and len(stage_reason) < MIN_REUSE_JUSTIFICATION_CHARS:
            raise HTTPException(status_code=422, detail={
                "code": "stage_reason_required",
                "message": f"A new agent starts at Ideation. To register it at {agent.stage}, say in at least "
                           f"{MIN_REUSE_JUSTIFICATION_CHARS} characters why (for example: already live before the registry existed).",
            })
        justification = agent.reuse_justification.strip()
        if similar and len(justification) < MIN_REUSE_JUSTIFICATION_CHARS:
            raise HTTPException(status_code=409, detail={
                "code": "similar_agents_exist",
                "message": f"{len(similar)} similar agent(s) already exist. Reuse one, or explain in at least "
                           f"{MIN_REUSE_JUSTIFICATION_CHARS} characters why none of them fit.",
                "similar": similar,
            })
        # Generate URL-safe agent ID
        slug = re.sub(r'[^a-z0-9-]', '', agent.name.lower().replace(" ", "-"))
        agent_id = f"{slug}-{secrets.token_hex(4)}"
        db_agent = Agent(
            id=agent_id, org_id="org-default", name=agent.name, slug=agent_id,
            description=agent.description, ai_type=agent.ai_type, owner=agent.owner,
            dept_id=agent.dept or None,
            lifecycle_stage=agent.stage, value_amount=agent.value_amount,
            value_type=agent.value_type, hours_saved_monthly=agent.hours_saved_monthly,
            business_outcome=agent.business_outcome, model_name=agent.model_name,
            risk_level=agent.risk_level, tags=agent.tags,
            enterprise_systems=agent.enterprise_systems, databases=agent.databases,
            knowledge_bases=agent.knowledge_bases, mcp_servers=agent.mcp_servers,
            calls=agent.calls, consumers=agent.consumers, inputs=agent.inputs,
            outputs=agent.outputs, api_endpoint=agent.api_endpoint, sla=agent.sla,
            phoenix_project=agent.phoenix_project or None,
            phoenix_endpoint=agent.phoenix_endpoint or None,
            context_md=agent.context_md or None,
            capabilities=agent.capabilities,
            version=agent.version.strip() or None,
            rate_limit=agent.rate_limit.strip() or None,
            owner_contact=agent.owner_contact.strip() or None,
            reuse_checked=[{"id": m["id"], "name": m["name"], "score": m["score"], "certified": m["certified"]}
                           for m in similar],
            reuse_justification=justification if similar else None,
            started_from_agent_id=agent.started_from_agent_id.strip() or None,
        )
        if db_agent.started_from_agent_id and await db.get(Agent, db_agent.started_from_agent_id) is None:
            raise HTTPException(status_code=422, detail="The agent this registration starts from does not exist.")
        db.add(db_agent)
        for gate in ["arb", "security", "dp"]:
            db.add(GovernanceReview(
                id=secrets.token_hex(8), agent_id=agent_id, gate=gate, status="Not Submitted"
            ))
        await db.flush()

        db.add(AuditLog(
            org_id="org-default",
            actor=user.get("user_id", "unknown"),
            action="create",
            entity_type="agent",
            entity_id=agent_id,
            changes={"name": agent.name, "stage": agent.stage, "ai_type": agent.ai_type,
                     "similar_shown": [m["id"] for m in similar]},
        ))
        if agent.stage != "Ideation":
            # Shown in the Governance tab's decision history like any other stage move.
            db.add(AuditLog(
                org_id="org-default", actor=user.get("user_id", "unknown"), action="stage_change",
                entity_type="agent", entity_id=agent_id,
                changes={"from": None, "to": agent.stage, "atRegistration": True, "overrideReason": stage_reason},
            ))

        return {"id": agent_id, "status": "created"}


@agents_router.put("/{agent_id}")
async def update_agent(agent_id: str, update: AgentUpdate, user=Depends(require_update)):
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        update_data = update.model_dump(exclude_unset=True)
        # Stage and risk level decide which reviews an agent needs, so they change
        # only through the routes that check and record that.
        if "lifecycle_stage" in update_data:
            raise HTTPException(status_code=422, detail="Change the stage on the Governance tab "
                                "(PUT /api/v1/agents/{id}/stage), which checks readiness and records the move.")
        if "risk_level" in update_data and update_data["risk_level"] != agent.risk_level:
            raise HTTPException(status_code=422, detail="Change the risk level through the classification "
                                "on the Governance tab, which records who confirmed it and why.")
        update_data.pop("risk_level", None)

        # Columns the table requires; an explicit null would fail in the DB.
        for required in ("name", "owner", "description", "ai_type", "lifecycle_stage"):
            if required in update_data and update_data[required] is None:
                raise HTTPException(status_code=422, detail=f"{required} cannot be null")
        if "dept" in update_data:
            dept = update_data.pop("dept") or None
            if dept and await db.get(Department, dept) is None:
                raise HTTPException(status_code=422, detail=f"Unknown department '{dept}'")
            update_data["dept_id"] = dept
        for field, value in update_data.items():
            setattr(agent, field, value)

        db.add(AuditLog(
            org_id="org-default",
            actor=user.get("user_id", "unknown"),
            action="update",
            entity_type="agent",
            entity_id=agent_id,
            changes=update_data,
        ))

        return {"status": "updated"}


@agents_router.delete("/{agent_id}")
async def delete_agent(agent_id: str, user=Depends(require_delete)):
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        db.add(AuditLog(
            org_id="org-default",
            actor=user.get("user_id", "unknown"),
            action="delete",
            entity_type="agent",
            entity_id=agent_id,
            changes={"name": agent.name, "stage": agent.lifecycle_stage},
        ))

        # Rows that reference the agent without an ORM cascade. Left behind
        # they would keep counting in portfolio totals (the risk summary reads
        # agent_risks directly), and on Postgres the FKs would refuse the delete.
        await db.execute(delete(InsightFeedback).where(
            InsightFeedback.insight_id.in_(select(Insight.id).where(Insight.agent_id == agent_id))))
        for model in _AGENT_OWNED_TABLES:
            await db.execute(delete(model).where(model.agent_id == agent_id))
        # A discovery is a record of detection and outlives the agent.
        await db.execute(
            sql_update(Discovery).where(Discovery.registered_agent_id == agent_id).values(registered_agent_id=None)
        )
        await db.delete(agent)
        return {"status": "deleted"}


@agents_router.post("/{agent_id}/offboard")
async def offboard_agent(agent_id: str, stage: int = 1, user=Depends(require_update)):
    """7-stage decommissioning workflow per PLAN §10.3.

    Stage 1: Retirement decision  – documented rationale, owner signoff
    Stage 2: Knowledge capture    – runbooks, learnings archived
    Stage 3: Dependency mapping   – all consumers identified
    Stage 4: Credential revocation – API keys, OAuth tokens destroyed
    Stage 5: Invocation blocking  – zero new requests accepted
    Stage 6: Data sanitization    – traces archived, PII purged
    Stage 7: Residual validation  – 7-day wait, zero invocations, $0 cost
    """
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        if stage < 1 or stage > 7:
            raise HTTPException(status_code=400, detail="Stage must be 1-7")

        now = datetime.now(timezone.utc)

        if stage == 1:
            agent.risk_note = (agent.risk_note or "") + f" | Retirement decision: owner signoff recorded {now.date()}"
        elif stage == 2:
            agent.risk_note = (agent.risk_note or "") + f" | Knowledge capture: runbooks archived {now.date()}"
        elif stage == 3:
            consumers = agent.consumers or []
            agent.risk_note = (agent.risk_note or "") + f" | Dependency mapping: {len(consumers)} consumers identified {now.date()}"
        elif stage == 4:
            identity_result = await db.execute(select(AgentIdentity).where(AgentIdentity.agent_id == agent_id))
            identity = identity_result.scalar_one_or_none()
            if identity:
                identity.api_key_hash = None
                identity.revoked_at = now
            agent.risk_note = (agent.risk_note or "") + f" | Credential revocation: API keys destroyed {now.date()}"
        elif stage == 5:
            agent.api_endpoint = None
            agent.risk_note = (agent.risk_note or "") + f" | Invocation blocking: zero new requests accepted {now.date()}"
        elif stage == 6:
            agent.risk_note = (agent.risk_note or "") + f" | Data sanitization: traces archived, PII purged {now.date()}"
        elif stage == 7:
            # The stage changes only through the retirement steps, which check traffic first.
            raise HTTPException(status_code=409, detail="Set the stage to Deprecated with the retirement steps on the Governance tab "
                                "(POST /api/v1/agents/{id}/retirement).")

        db.add(AuditLog(
            org_id=agent.org_id,
            actor=user.get("user_id", "unknown"),
            action="offboard",
            entity_type="agent",
            entity_id=agent_id,
            changes={"stage": stage, "lifecycle_stage": agent.lifecycle_stage},
        ))

        return {
            "status": "offboarding",
            "stage": stage,
            "agent_id": agent_id,
            "lifecycle_stage": agent.lifecycle_stage,
            "sunset_date": str(agent.sunset_date) if agent.sunset_date else None,
        }


@agents_router.get("/{agent_id}/identity")
async def get_identity(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(AgentIdentity).where(AgentIdentity.agent_id == agent_id))
        identity = result.scalar_one_or_none()
        if not identity:
            return {"agentId": agent_id, "serviceAccount": f"svc-{agent_id}@airegistry.local", "status": "active"}
        return {
            "agentId": identity.agent_id,
            "serviceAccount": identity.service_account,
            "entraAgentId": identity.entra_agent_id,
            "permissions": identity.permissions,
            "status": "revoked" if identity.revoked_at else "active"
        }


@agents_router.post("/{agent_id}/identity/revoke")
async def revoke_identity(agent_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        result = await db.execute(select(AgentIdentity).where(AgentIdentity.agent_id == agent_id))
        identity = result.scalar_one_or_none()
        if identity:
            identity.revoked_at = datetime.now(timezone.utc)
        return {"status": "revoked"}


# ── Governance Router ────────────────────────────────────────────────────────

VALID_GATES = ["arb", "security", "dp"]

@governance_router.get("/")
async def governance_overview(_=Depends(require_read)):
    async with get_db_session() as db:
        from db.scope import hidden_agent_ids

        hidden = await hidden_agent_ids(db)
        overview = {}
        for gate in VALID_GATES:
            result = await db.execute(
                select(GovernanceReview.status, func.count())
                .where(GovernanceReview.gate == gate, GovernanceReview.agent_id.notin_(hidden))
                .group_by(GovernanceReview.status)
            )
            overview[gate] = {status: count for status, count in result.all()}
        return overview


def review_position(statuses: dict, required: list) -> str:
    """Where an agent stands on the reviews its risk level requires: cleared (each one approved, with or
    without conditions), blocked (changes requested on one), in_review (one awaits a decision), else open."""
    held = [statuses.get(g) or "Not Submitted" for g in required]
    if "Changes Requested" in held:
        return "blocked"
    if "In Review" in held:
        return "in_review"
    return "cleared" if all(s in ("Approved", "Approved with Conditions") for s in held) else "open"


@governance_router.get("/summary")
async def governance_summary(_=Depends(require_read)):
    """The reviews each risk level requires (Settings, Governance rules) and how many agents that are
    not retired stand where on them. Counted over every agent, by the same rule as the stage checks."""
    from governance import templates as tpl
    from sqlalchemy.orm import selectinload

    rules = await tpl.templates()
    required = {tier: list(v.get("gates") or []) for tier, v in rules.items()}
    async with get_db_session() as db:
        agents = (await db.execute(select(Agent).options(selectinload(Agent.governance_reviews))
                                   .where(Agent.lifecycle_stage != "Deprecated"))).scalars().all()
    counts = {"cleared": 0, "blocked": 0, "in_review": 0, "open": 0}
    positions = {}
    for a in agents:
        need = required.get((a.risk_level or "LOW").upper(), required.get("LOW", []))
        positions[a.id] = review_position({r.gate: r.status for r in a.governance_reviews or []}, need)
        counts[positions[a.id]] += 1
    return {"requiredReviews": required, "agents": len(agents), "cleared": counts["cleared"],
            "blocked": counts["blocked"], "inReview": counts["in_review"], "open": counts["open"],
            # Which agents each count is made of: cleared | blocked | in_review | open.
            "positions": positions}


@governance_router.get("/exceptions")
async def list_exceptions(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(GovernanceException).where(GovernanceException.expires_at > datetime.now(timezone.utc))
        )
        return [_exception_to_dict(e) for e in result.scalars().all()]


@governance_router.post("/exceptions")
async def create_exception(exc: ExceptionCreate, user=Depends(require_admin)):
    async with get_db_session() as db:
        db_exc = GovernanceException(
            id=secrets.token_hex(8), agent_id=exc.agentId, gate=exc.gate,
            reason=exc.reason, expires_at=datetime.fromisoformat(exc.expiresAt),
            approved_by=exc.approvedBy
        )
        db.add(db_exc)
        return {"id": db_exc.id, "status": "created"}


# ── Discovery Router ─────────────────────────────────────────────────────────

@discovery_router.get("/")
async def list_discoveries(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(Discovery).order_by(Discovery.confidence.desc()))
        return [_discovery_to_dict(d) for d in result.scalars().all()]


@discovery_router.get("/shadow-ai")
async def shadow_ai(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(Discovery).where(
                Discovery.shadow_ai_risk.in_(["HIGH", "MEDIUM"]),
                Discovery.status == "pending"
            ).order_by(Discovery.confidence.desc())
        )
        return [_discovery_to_dict(d) for d in result.scalars().all()]


# Sources written by the governance checks (orchestrations/discovery_pipeline.py): each is about a registered agent or a shared system.
CHECK_SOURCES = {"agents_table", "concentration_risk", "governance_gap", "idle_detection", "model_overkill"}


@discovery_router.post("/{discovery_id}/register")
async def register_discovery(discovery_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        result = await db.execute(select(Discovery).where(Discovery.id == discovery_id))
        discovery = result.scalar_one_or_none()
        if not discovery:
            raise HTTPException(status_code=404, detail="Discovery not found")
        # Findings from the governance checks name agents that are already registered: never make a second record.
        if discovery.source in CHECK_SOURCES or (await db.execute(select(Agent.id).where(Agent.name == discovery.suspected_name))).first():
            raise HTTPException(status_code=409, detail="This finding is about an agent or system that is already known. "
                                "Open the agent instead. New agents are registered on AI Registry or Discovered.")

        agent_id = f"agent-{secrets.token_hex(6)}"
        slug = discovery.suspected_name.lower().replace(" ", "-")[:80]
        existing = await db.execute(select(Agent).where(Agent.slug == slug))
        if existing.scalar_one_or_none():
            slug = f"{slug}-{secrets.token_hex(3)}"

        agent = Agent(
            id=agent_id,
            org_id=discovery.org_id,
            name=discovery.suspected_name,
            slug=slug,
            description=f"Registered from discovery: {discovery.signal or 'No signal'}",
            ai_type=discovery.suspected_type or "Autonomous Agent",
            owner="Unassigned",
            lifecycle_stage="Ideation",
            source="discovery",
            discovered_at=datetime.now(timezone.utc),
            shadow_ai_risk=discovery.shadow_ai_risk,
        )
        db.add(agent)

        discovery.status = "registered"
        discovery.registered_agent_id = agent_id
        discovery.resolved_at = datetime.now(timezone.utc)

        db.add(AuditLog(
            org_id=discovery.org_id,
            actor=user.get("user_id", "unknown"),
            action="register",
            entity_type="discovery",
            entity_id=discovery_id,
            changes={"registered_agent_id": agent_id, "source": "discovery_pipeline"},
        ))

        return {"status": "registered", "agent_id": agent_id}


@discovery_router.post("/{discovery_id}/dismiss")
async def dismiss_discovery(discovery_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        result = await db.execute(select(Discovery).where(Discovery.id == discovery_id))
        discovery = result.scalar_one_or_none()
        if discovery:
            discovery.status = "dismissed"
            discovery.resolved_at = datetime.now(timezone.utc)
            db.add(AuditLog(org_id=discovery.org_id, actor=user.get("user_id", "unknown"), action="dismiss",
                            entity_type="discovery", entity_id=discovery_id,
                            changes={"name": discovery.suspected_name, "source": discovery.source}))
        return {"status": "dismissed"}


# ── Tokenomics Router ────────────────────────────────────────────────────────

@tokenomics_router.get("/portfolio/cost")
async def portfolio_cost(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(func.count(Agent.id), func.coalesce(func.sum(Agent.value_amount), 0))
            .where(Agent.lifecycle_stage == "Production")
        )
        count, total_value = result.one()
        return {"agentCount": count, "totalValue": total_value}


@tokenomics_router.get("/agents/{agent_id}/tokens")
async def agent_tokens(agent_id: str, _=Depends(require_read)):
    """Older, pre-engine shape kept for compatibility. Recomputed from the
    same governance/costing engine as /tokens/summary and /tokenomics —
    it used to sum the stored cost_cents column, which is rounded to the
    nearest whole cent *per day* and so understated real cost (e.g. 1 vs
    the engine's 1.1454 for two days that individually round to $0 and
    $0.01)."""
    async with get_db_session() as db:
        usage = await priced_usage(db, agent_id)
    rows = usage["rows"]
    cost_known = not rows or any(r.get("priced", True) for r in rows)
    return {
        "agentId": agent_id,
        "inputTokens": sum(r.get("input_tokens", 0) for r in rows),
        "outputTokens": sum(r.get("output_tokens", 0) for r in rows),
        "costCents": round(sum(r.get("cost_cents", 0.0) for r in rows), 4) if cost_known else None,
        "invocations": sum(r.get("calls", 0) for r in rows),
    }


@tokenomics_router.get("/models/prices")
async def model_prices(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(ModelTokenPrice).where(ModelTokenPrice.effective_to.is_(None)))
        return [_price_to_dict(p) for p in result.scalars().all()]


@tokenomics_router.get("/anomalies")
async def list_anomalies(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(CostAnomaly).where(CostAnomaly.resolved_at.is_(None)))
        return [_anomaly_to_dict(a) for a in result.scalars().all()]


# ── Graph Router ─────────────────────────────────────────────────────────────

@graph_router.get("/view")
async def graph_view(_=Depends(require_read)):
    """Cobol-style pyvis/vis-network HTML view (iframe srcdoc + filter runtime)."""
    from services.graph_service import build_graph
    from services.graph_view import build_graph_view_html
    async with get_db_session() as db:
        g = await build_graph(db)
    return build_graph_view_html(g)


@graph_router.get("/v2")
async def full_graph_v2(_=Depends(require_read)):
    """Dependency graph v2 — typed nodes/edges, legend, stats (shared builder)."""
    from services.graph_service import build_graph
    async with get_db_session() as db:
        return await build_graph(db)


@graph_router.get("/entry-points")
async def graph_entry_points(_=Depends(require_read)):
    """Agents that act as outage roots: in Production with consumers or callers."""
    from services.graph_service import build_adjacency
    async with get_db_session() as db:
        adj = await build_adjacency(db)
        entry_points = []
        for agent_id, attrs in adj["agent_attrs"].items():
            if attrs.get("entry") != "production":
                continue
            callers = adj["callers_of"].get(agent_id, [])
            consumers = adj["consumers_of"].get(agent_id, [])
            if callers or consumers:
                entry_points.append({
                    "id": agent_id,
                    "name": adj["node_names"].get(agent_id, agent_id),
                    "dept": attrs.get("dept"),
                    "callers": len(callers),
                    "consumers": len(consumers),
                    "value_amount": attrs.get("value_amount", 0),
                })
        entry_points.sort(key=lambda e: -e["value_amount"])
        return {"entry_points": entry_points, "count": len(entry_points)}


@graph_router.get("/")
async def full_graph(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        nodes = []
        edges = []
        seen_nodes = set()
        for agent in agents:
            nodes.append({"id": agent.id, "name": agent.name, "type": "agent", "stage": agent.lifecycle_stage})
            for sys in agent.enterprise_systems or []:
                node_id = f"sys:{sys}"
                if node_id not in seen_nodes:
                    nodes.append({"id": node_id, "name": sys, "type": "system"})
                    seen_nodes.add(node_id)
                edges.append({"from": agent.id, "to": node_id})
            for db_name in agent.databases or []:
                node_id = f"db:{db_name}"
                if node_id not in seen_nodes:
                    nodes.append({"id": node_id, "name": db_name, "type": "database"})
                    seen_nodes.add(node_id)
                edges.append({"from": agent.id, "to": node_id})
            for mcp in agent.mcp_servers or []:
                node_id = f"mcp:{mcp}"
                if node_id not in seen_nodes:
                    nodes.append({"id": node_id, "name": mcp, "type": "mcp"})
                    seen_nodes.add(node_id)
                edges.append({"from": agent.id, "to": node_id})
        return {"nodes": nodes, "edges": edges}


@graph_router.get("/concentration-risk")
async def concentration_risk(_=Depends(require_read)):
    from services.graph_service import concentration_risk as _concentration_risk

    async with get_db_session() as db:
        return await _concentration_risk(db)


# ── Value & Waste Router ─────────────────────────────────────────────────────

@value_waste_router.get("/value/summary")
async def value_summary(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(
                func.count(Agent.id),
                func.sum(case((Agent.lifecycle_stage == "Production", 1), else_=0)),
                func.sum(case((Agent.lifecycle_stage == "Production", Agent.value_amount), else_=0)),
                func.sum(Agent.value_amount),
                func.sum(Agent.hours_saved_monthly),
                func.sum(case((Agent.at_risk == True, 1), else_=0)),
            )
        )
        total, in_prod, realized, total_val, hours, at_risk = result.one()
        return {
            "totalAgents": total,
            "agentsInProduction": in_prod or 0,
            "realizedValueMonthly": realized or 0,
            "totalValueMonthly": total_val or 0,
            "hoursSavedMonthly": hours or 0,
            "atRiskCount": at_risk or 0,
        }


@value_waste_router.get("/value/by-department")
async def value_by_department(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(Department.name, func.count(Agent.id), func.sum(Agent.value_amount))
            .join(Agent, Agent.dept_id == Department.id, isouter=True)
            .group_by(Department.name)
            .order_by(func.sum(Agent.value_amount).desc().nulls_last())
        )
        return [{"department": name, "agentCount": count, "totalValue": value or 0} for name, count, value in result.all()]


@value_waste_router.get("/value/top-agents")
async def top_agents(limit: int = 5, _=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(Agent).options(selectinload(Agent.governance_reviews)).order_by(Agent.value_amount.desc()).limit(limit))
        return [_agent_to_dict(a) for a in result.scalars().all()]


@value_waste_router.get("/waste/report")
async def waste_report(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(select(WasteFinding))
        return [_waste_to_dict(w) for w in result.scalars().all()]


@value_waste_router.get("/waste/summary")
async def waste_summary(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(func.count(WasteFinding.id), func.sum(WasteFinding.monthly_waste_cents))
        )
        total, waste = result.one()
        return {"totalFindings": total or 0, "totalMonthlyWasteCents": waste or 0}


@value_waste_router.get("/optimizations")
async def optimizations(_=Depends(require_read)):
    async with get_db_session() as db:
        result = await db.execute(
            select(Agent).where(Agent.model_name.in_(["GPT-5", "Claude Sonnet 4.5"]), Agent.lifecycle_stage == "Production")
        )
        opts = []
        for agent in result.scalars().all():
            opts.append({
                "agentId": agent.id,
                "agentName": agent.name,
                "strategy": "model_downgrade",
                "currentModel": agent.model_name,
                "suggestedModel": "GPT-5-mini",
                "reason": f"Downgrade from {agent.model_name} to GPT-5-mini could save 70% on token costs"
            })
        return opts


# ── Admin Router ─────────────────────────────────────────────────────────────

@admin_router.get("/scope")
async def view_scope(_=Depends(require_read)):
    """How many demo agents exist, whether this request includes them, and whether
    the installation has them turned on (DEMO_AGENTS_ENABLED), for Settings → Demo agents."""
    from db.scope import demo_enabled, hiding_demo, set_scope, reset_scope

    including = not hiding_demo()
    tokens = set_scope(False)
    try:
        async with get_db_session() as db:
            count = (await db.execute(select(func.count(Agent.id)).where(Agent.is_demo == True))).scalar() or 0  # noqa: E712
    finally:
        reset_scope(tokens)
    enabled = demo_enabled()
    return {"demoAgents": count if enabled else 0, "includingDemo": including and enabled, "demoEnabled": enabled}


@admin_router.get("/taxonomy")
async def taxonomy(_=Depends(require_read)):
    return {
        "stages": ["Ideation", "Development", "Testing", "Production", "Deprecated"],
        "gates": ["arb", "security", "dp"],
        "reviewStatuses": ["Not Submitted", "In Review", "Changes Requested", "Approved with Conditions", "Approved"],
        "riskLevels": ["LOW", "MEDIUM", "HIGH"],
        "aiTypes": ["Autonomous Agent", "Copilot / Assistant", "Predictive / ML Model", "Generative AI Feature", "Conversational AI / Chatbot", "Computer Vision Model"],
        "userRoles": list(USER_ROLES),
    }


@admin_router.get("/settings")
async def runtime_settings(_=Depends(require_read)):
    """Switches the UI has to reflect, e.g. the testing-only self-approval
    mode, so Settings can say plainly that it is on."""
    return {"selfApprovalAllowed": get_settings().allow_self_approval}


@admin_router.get("/directory")
async def user_directory(_=Depends(require_read)):
    """Active people, for pickers (owner, deputy). Names, emails and roles only."""
    async with get_db_session() as db:
        rows = (await db.execute(select(User).where(User.is_active == True).order_by(User.name))).scalars().all()  # noqa: E712
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in rows]


@admin_router.get("/users")
async def list_users(_=Depends(require_admin)):
    async with get_db_session() as db:
        result = await db.execute(select(User).order_by(User.name))
        return [_user_to_dict(u) for u in result.scalars().all()]


@admin_router.post("/users")
async def create_user(user: UserCreate, actor=Depends(require_admin)):
    email = user.email.strip().lower()
    name = " ".join(user.name.split())
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if not name:
        raise HTTPException(status_code=422, detail="Enter the person's name")
    if user.role not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of: {', '.join(USER_ROLES)}")
    _auditor_end(user.role, user.accessUntil)
    async with get_db_session() as db:
        if (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"A user with {email} already exists")
        db_user = User(
            id=secrets.token_hex(8), org_id="org-default", email=email,
            name=name, role=user.role, password_hash=hash_password(user.password), is_active=True,
            access_until=user.accessUntil if user.role == "Auditor" else None,
        )
        db.add(db_user)
        # Who added whom; never the password.
        db.add(AuditLog(org_id="org-default", actor=actor.get("user_id", "unknown"), action="user_create",
                        entity_type="user", entity_id=db_user.id,
                        changes={"email": email, "name": name, "role": user.role,
                                 **({"accessUntil": str(user.accessUntil)} if user.role == "Auditor" else {})}))
        return {"id": db_user.id, "status": "created", "user": _user_to_dict(db_user)}


# ── Helper functions ─────────────────────────────────────────────────────────

def _agent_to_dict(agent: Agent, dept_name: str | None = None) -> dict:
    return {
        "id": agent.id, "name": agent.name, "slug": agent.slug,
        "description": agent.description, "aiType": agent.ai_type,
        "owner": agent.owner, "ownerContact": agent.owner_contact,
        "stage": agent.lifecycle_stage, "version": agent.version,
        "dept": agent.dept_id, "deptName": dept_name,
        "valueAmount": agent.value_amount, "valueType": agent.value_type,
        "hoursSavedMonthly": agent.hours_saved_monthly,
        "businessOutcome": agent.business_outcome,
        "enterpriseSystems": agent.enterprise_systems,
        "databases": agent.databases, "knowledgeBases": agent.knowledge_bases,
        "mcpServers": agent.mcp_servers, "calls": agent.calls,
        "consumers": agent.consumers, "inputs": agent.inputs,
        "outputs": agent.outputs, "apiEndpoint": agent.api_endpoint,
        "sla": agent.sla, "tags": agent.tags, "modelName": agent.model_name,
        "riskLevel": agent.risk_level, "riskNote": agent.risk_note,
        "atRisk": agent.at_risk, "timeInStageWeeks": agent.time_in_stage_weeks,
        "reviews": {r.gate: r.status for r in agent.governance_reviews} if agent.governance_reviews else {},
        "phoenixProject": agent.phoenix_project,
        "phoenixEndpoint": agent.phoenix_endpoint,
        "contextMd": agent.context_md,
        "capabilities": agent.capabilities or [],
        "rateLimit": agent.rate_limit,
        "isDemo": bool(agent.is_demo),
        "archivedAt": agent.archived_at.isoformat() if agent.archived_at else None,
        "sourceRepo": agent.source_repo, "cloudResourceId": agent.cloud_resource_id,
        "traceConnectorId": agent.trace_connector_id, "ownerUserId": agent.owner_user_id,
        "backupOwnerUserId": agent.backup_owner_user_id,
    }


def _discovery_to_dict(d: Discovery) -> dict:
    return {
        "id": d.id, "suspectedName": d.suspected_name, "suspectedDept": d.suspected_dept,
        "suspectedType": d.suspected_type, "source": d.source, "confidence": d.confidence,
        "signal": d.signal, "status": d.status, "shadowAiRisk": d.shadow_ai_risk,
        "firstSeen": str(d.first_seen),
    }


def _exception_to_dict(e: GovernanceException) -> dict:
    return {
        "id": e.id, "agentId": e.agent_id, "gate": e.gate, "reason": e.reason,
        "expiresAt": str(e.expires_at), "approvedBy": e.approved_by,
    }


def _price_to_dict(p: ModelTokenPrice) -> dict:
    return {
        "id": p.id, "modelName": p.model_name, "provider": p.provider,
        "inputPrice": p.input_price_per_1m, "outputPrice": p.output_price_per_1m,
        "cacheReadPrice": p.cache_read_price_per_1m, "tier": p.tier,
    }


def _anomaly_to_dict(a: CostAnomaly) -> dict:
    return {
        "id": a.id, "agentId": a.agent_id, "type": a.anomaly_type,
        "severity": a.severity, "detectedAt": str(a.detected_at),
        "details": a.details, "resolvedAt": str(a.resolved_at) if a.resolved_at else None,
    }


def _waste_to_dict(w: WasteFinding) -> dict:
    return {
        "id": w.id, "agentId": w.agent_id, "wasteType": w.waste_type,
        "severity": w.severity, "monthlyWasteCents": w.monthly_waste_cents,
        "recommendation": w.recommendation, "status": w.status,
    }


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name,
        "role": u.role, "isActive": u.is_active,
        "awayUntil": u.away_until.isoformat() if u.away_until else None, "deputyUserId": u.deputy_user_id,
        "accessUntil": u.access_until.isoformat() if u.access_until else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ADDITIONAL ENDPOINTS — Tokenomics, Graph, Admin, Auth
# ═══════════════════════════════════════════════════════════════════════════════

# ── Additional Tokenomics Endpoints ───────────────────────────────────────────

@tokenomics_router.get("/portfolio/tokens")
async def portfolio_tokens(_=Depends(require_read)):
    """Get aggregated token usage across all agents."""
    async with get_db_session() as db:
        result = await db.execute(
            select(
                func.sum(AgentTokenUsage.input_tokens),
                func.sum(AgentTokenUsage.output_tokens),
                func.sum(AgentTokenUsage.cached_tokens),
            )
        )
        row = result.one()
        return {
            "totalTokens": (row[0] or 0) + (row[1] or 0),
            "inputTokens": row[0] or 0,
            "outputTokens": row[1] or 0,
            "cachedTokens": row[2] or 0,
        }


@tokenomics_router.put("/models/prices/{model_name}")
async def update_model_price(model_name: str, prices: dict, _=Depends(require_admin)):
    """Update model pricing."""
    async with get_db_session() as db:
        # Close the price in force, so exactly one price applies from now on.
        now = datetime.now(timezone.utc)
        await db.execute(
            sql_update(ModelTokenPrice)
            .where(ModelTokenPrice.model_name == model_name, ModelTokenPrice.effective_to.is_(None))
            .values(effective_to=now)
        )
        # Insert new price
        db.add(ModelTokenPrice(
            id=secrets.token_hex(8),
            model_name=model_name,
            provider=prices.get("provider", "unknown"),
            input_price_per_1m=prices.get("inputPrice", 0),
            output_price_per_1m=prices.get("outputPrice", 0),
            cache_read_price_per_1m=prices.get("cacheReadPrice", 0),
            tier=prices.get("tier", "mid"),
            effective_from=now,
        ))
        db.add(AuditLog(org_id="org-default", actor=_.get("user_id", "unknown") if isinstance(_, dict) else "unknown",
                        action="price.update", entity_type="model_price", entity_id=model_name[:64],
                        changes={k: prices.get(k) for k in ("inputPrice", "outputPrice", "cacheReadPrice", "provider", "tier")}))
        return {"status": "updated", "model": model_name}


@tokenomics_router.post("/anomalies/{anomaly_id}/resolve")
async def resolve_anomaly(anomaly_id: str, _=Depends(require_update)):
    """Mark an anomaly as resolved."""
    async with get_db_session() as db:
        result = await db.execute(select(CostAnomaly).where(CostAnomaly.id == anomaly_id))
        anomaly = result.scalar_one_or_none()
        if anomaly:
            anomaly.resolved_at = datetime.now(timezone.utc)
        return {"status": "resolved"}


# ── Additional Graph Endpoints ────────────────────────────────────────────────

@graph_router.get("/impact/{node_id}")
async def impact_analysis(node_id: str, node_type: str = "agent", _=Depends(require_read)):
    """Run impact analysis for a target node."""
    from orchestrations.impact_analysis import run_impact_analysis
    result = await run_impact_analysis(node_id, node_type)
    return result


# ── Additional Admin Endpoints ────────────────────────────────────────────────

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = None
    isActive: Optional[bool] = None
    awayUntil: Optional[date] = None
    deputyUserId: Optional[str] = None
    accessUntil: Optional[date] = None


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


async def _active_admins(db) -> list[str]:
    rows = (await db.execute(select(User.id).where(User.is_active == True, User.role == "Registry Admin"))).scalars().all()  # noqa: E712
    return list(rows)


@admin_router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, actor=Depends(require_admin)):
    """Change a person's name, role or whether they can sign in. The last active
    Registry Admin cannot be demoted or deactivated, so the registry always has one."""
    async with get_db_session() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        before = {"name": user.name, "role": user.role, "isActive": user.is_active,
                  "awayUntil": str(user.away_until) if user.away_until else None, "deputyUserId": user.deputy_user_id,
                  "accessUntil": str(user.access_until) if user.access_until else None}
        sent = body.model_dump(exclude_unset=True)
        if body.role is not None and body.role not in USER_ROLES:
            raise HTTPException(status_code=422, detail=f"Role must be one of: {', '.join(USER_ROLES)}")
        losing_admin = user.role == "Registry Admin" and user.is_active and (
            (body.role is not None and body.role != "Registry Admin") or body.isActive is False)
        if losing_admin and await _active_admins(db) == [user.id]:
            raise HTTPException(status_code=409, detail="This is the only active Registry Admin. Make someone else an admin first.")
        if body.isActive is False and user.id == actor.get("user_id"):
            raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
        if body.name is not None:
            name = " ".join(body.name.split())
            if not name:
                raise HTTPException(status_code=422, detail="Enter the person's name")
            user.name = name
        if body.role is not None:
            user.role = body.role
        if body.isActive is not None:
            user.is_active = body.isActive
        # Sent as null, these clear the away period or the deputy.
        if "awayUntil" in sent:
            user.away_until = body.awayUntil
        if "deputyUserId" in sent:
            if body.deputyUserId and (body.deputyUserId == user.id or await db.get(User, body.deputyUserId) is None):
                raise HTTPException(status_code=422, detail="The deputy must be another existing user.")
            user.deputy_user_id = body.deputyUserId or None
        if "accessUntil" in sent:
            user.access_until = body.accessUntil
        if "accessUntil" in sent or "role" in sent:          # an unrelated edit never trips an end date already passed
            _auditor_end(user.role, user.access_until)
        if user.role != "Auditor":
            user.access_until = None
        after = {"name": user.name, "role": user.role, "isActive": user.is_active,
                 "awayUntil": str(user.away_until) if user.away_until else None, "deputyUserId": user.deputy_user_id,
                 "accessUntil": str(user.access_until) if user.access_until else None}
        db.add(AuditLog(org_id="org-default", actor=actor.get("user_id", "unknown"), action="user_update",
                        entity_type="user", entity_id=user.id,
                        changes={k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}))
        result = {"status": "updated", "user": _user_to_dict(user)}
    if body.isActive is False and before["isActive"]:
        from services.ownership import on_deactivated
        result["ownership"] = await on_deactivated(user_id, actor.get("user_id", "unknown"))
    return result


@admin_router.post("/users/{user_id}/password")
async def reset_password(user_id: str, body: PasswordReset, actor=Depends(require_admin)):
    """Set a new password for someone. Logged without the password."""
    async with get_db_session() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.password_hash = hash_password(body.password)
        db.add(AuditLog(org_id="org-default", actor=actor.get("user_id", "unknown"), action="user_password_reset",
                        entity_type="user", entity_id=user.id, changes={"email": user.email}))
        return {"status": "updated"}


@admin_router.delete("/users/{user_id}")
async def delete_user(user_id: str, actor=Depends(require_admin)):
    """Deactivate a user (the record stays, so past decisions keep their name)."""
    return await update_user(user_id, UserUpdate(isActive=False), actor)


@admin_router.post("/seed-identities")
async def seed_identities(_=Depends(require_admin)):
    """Seed agent identities."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        count = 0
        for agent in agents:
            # Check if identity exists
            identity_result = await db.execute(
                select(AgentIdentity).where(AgentIdentity.agent_id == agent.id)
            )
            if identity_result.scalar_one_or_none():
                continue
            db.add(AgentIdentity(
                agent_id=agent.id,
                service_account=f"svc-{agent.id}@airegistry.local",
                entra_agent_id=f"entra-{agent.id}",
                permissions=["read", "write", "execute"],
            ))
            count += 1
        return {"status": "seeded", "identities_created": count}


# ── Additional Auth Endpoints ─────────────────────────────────────────────────

@auth_router.post("/register")
async def register(req: UserCreate, _=Depends(require_admin)):
    """Register a new user (admin only)."""
    async with get_db_session() as db:
        # Check if email exists
        result = await db.execute(select(User).where(User.email == req.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")
        user = User(
            id=secrets.token_hex(8),
            org_id="org-default",
            email=req.email,
            name=req.name,
            role=req.role,
            password_hash=hash_password(req.password),
        )
        db.add(user)
        return {"status": "created", "user_id": user.id}


# ── Additional Agent Endpoints ────────────────────────────────────────────────

@agents_router.get("/{agent_id}/graph")
async def agent_graph(agent_id: str, _=Depends(require_read)):
    """Get dependency graph for a specific agent."""
    async with get_db_session() as db:
        result = await db.execute(
            select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent": _agent_to_dict(agent),
            "calls": agent.calls or [],
            "consumers": agent.consumers or [],
        }


class PhoenixConfigUpdate(BaseModel):
    endpoint: str = Field("", max_length=500)
    api_key: str = Field("", max_length=255)
    enabled: bool = True

    @validator("endpoint")
    def _endpoint(cls, v):
        v = (v or "").strip()
        if v:
            parsed = urlparse(v)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("The Phoenix address must be a web address such as https://phoenix.example.com, without a user name or password")
        return v
    # None leaves the saved template as it is; "" clears it.
    app_url_template: Optional[str] = Field(None, max_length=500)

    @validator("app_url_template")
    def _template(cls, v):
        v = (v or "").strip() if v is not None else None
        if v and (not v.lower().startswith(("http://", "https://")) or "{project}" not in v):
            raise ValueError("The address pattern must start with https:// and contain {project}")
        return v


@phoenix_router.get("/config")
async def get_phoenix_config(_=Depends(require_read)):
    """The org-wide COMMON tracing endpoint (the Settings/Config tab) — what
    the onboarding form's "common endpoint" dropdown option resolves to.
    Falls back to this deployment's own env-configured Phoenix (the same one
    this app already exports its own traces to) when no row has been saved
    yet, so a fresh install still has a sensible default to discover from."""
    settings = get_settings()
    async with get_db_session() as db:
        result = await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == "org-default"))
        row = result.scalar_one_or_none()
        if row:
            return {"endpoint": row.endpoint or "", "apiKeySet": bool(row.api_key), "enabled": row.enabled,
                    "source": "saved", "appUrlTemplate": row.app_url_template or ""}
    return {
        "endpoint": _phoenix_rest_base_url_from_settings(settings) or "",
        "apiKeySet": bool(settings.arize_phoenix_api_key),
        "enabled": True,
        "source": "env_default",
        "appUrlTemplate": "",
    }


@phoenix_router.put("/config")
async def update_phoenix_config(update: PhoenixConfigUpdate, user=Depends(require_admin)):
    """Upserts the one org-wide config row. Admin-only — this is the shared
    default every onboarding form falls back to, not a per-user preference."""
    async with get_db_session() as db:
        result = await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == "org-default"))
        row = result.scalar_one_or_none()
        # What discovery found belongs to the Phoenix it was read from: when the
        # endpoint (or whether it is used) changes, that list is cleared so the
        # Discovered page never shows another server's projects. Dismissals are kept.
        before = ((row.endpoint or "").strip(), bool(row.enabled)) if row else None
        repointed = before is not None and before[0] != update.endpoint
        if before is not None and before != (update.endpoint, bool(update.enabled)):
            from db.models import PhoenixProject
            await db.execute(delete(PhoenixProject).where(
                PhoenixProject.org_id == "org-default", PhoenixProject.state != "dismissed"))
            # Dismissals stay, but they were made against the old server: nothing is "read" until a new scan.
            await db.execute(sql_update(PhoenixProject).where(PhoenixProject.org_id == "org-default").values(scanned_at=None))
        if row:
            row.endpoint = update.endpoint or None
            # An empty api_key in the request means "leave it as-is" (the GET
            # above never echoes the real key back, only whether one is set)
            # — only overwrite when a real value is actually supplied.
            if update.api_key:
                row.api_key = update.api_key
            elif repointed:
                # A saved key is never sent to a different address: it must be entered again.
                row.api_key = None
            row.enabled = update.enabled
            if update.app_url_template is not None:
                row.app_url_template = update.app_url_template or None
        else:
            db.add(PhoenixConfig(
                id=secrets.token_hex(8), org_id="org-default",
                endpoint=update.endpoint or None, api_key=update.api_key or None, enabled=update.enabled,
                app_url_template=update.app_url_template or None,
            ))
        db.add(AuditLog(
            org_id="org-default", actor=user.get("user_id", "unknown"), action="phoenix_config.update",
            entity_type="phoenix_config", entity_id="org-default",
            changes={"endpoint": update.endpoint, "enabled": update.enabled, "keyChanged": bool(update.api_key),
                     "keyCleared": bool(row and repointed and not update.api_key),
                     "appUrlTemplate": update.app_url_template}))
        return {"status": "saved"}


class ConnectionTest(BaseModel):
    endpoint: str = Field("", max_length=500)
    apiKey: str = Field("", max_length=500)
    project: str = Field("", max_length=255)


@phoenix_router.post("/test-connection")
async def phoenix_test_connection(body: ConnectionTest, user=Depends(require_read)):
    """Check a Phoenix connection step by step and say which step fails. With no
    endpoint in the body, the saved common connection is tested; testing a typed
    address needs an admin, because it makes the server call that address."""
    from api.auth import has_permission
    from discovery.connection import test_connection

    endpoint = body.endpoint.strip()
    if endpoint and not has_permission(user.get("role", ""), "admin"):
        raise HTTPException(status_code=403, detail="Only a Registry Admin can test a typed address.")
    async with get_db_session() as db:
        saved_url, saved_key = await _resolve_phoenix_endpoint(db, agent=None)
    base_url = endpoint or saved_url
    api_key = body.apiKey.strip() or (saved_key if not endpoint or endpoint == saved_url else None)
    result = await test_connection(base_url, api_key, body.project.strip() or None,
                                   allow_loopback=get_settings().app_env == "development")
    return {"endpoint": base_url, **result}


@phoenix_router.get("/projects")
async def phoenix_projects(_=Depends(require_read)):
    """Every project Phoenix currently knows about — backs the "link this
    agent to its real telemetry" picker in the onboarding/edit form. Real
    discovery, not a guess: a project only appears here if Phoenix actually
    has traces filed under that name. Always resolves against the COMMON
    endpoint (org-wide discovery isn't scoped to one agent's custom override).

    Returns an explicit `reachable: false` (never a 500) when Phoenix itself
    can't be reached — that's a real, expected state for local dev with no
    Phoenix running, not a bug to surface as a crash."""
    from discovery.phoenix_client import PhoenixClient, PhoenixError

    async with get_db_session() as db:
        base_url, api_key = await _resolve_phoenix_endpoint(db, agent=None)
    if not base_url:
        return {"reachable": False, "reason": "No Phoenix endpoint configured", "projects": []}

    try:
        async with PhoenixClient(base_url, api_key=api_key) as client:
            projects = await client.projects()
        return {"reachable": True, "projects": projects}
    except PhoenixError as exc:
        return {"reachable": False, "reason": str(exc), "projects": []}


def _phoenix_rest_base_url_from_settings(settings) -> str | None:
    """Phoenix's REST API (`/v1/projects`, ...) lives on the same host as the
    OTLP trace-ingest endpoint this app already exports to
    (`phoenix_collector_endpoint`, e.g. `https://zaf-phoenix.../v1/traces`)
    — strip the ingest-specific `/v1/traces` suffix to get the base URL the
    REST endpoints hang off. Falls back to `phoenix_host`/`phoenix_port` for
    local dev, matching observability/tracing.py's own fallback."""
    endpoint = (settings.phoenix_collector_endpoint or "").rstrip("/")
    if endpoint:
        return endpoint[: -len("/v1/traces")] if endpoint.endswith("/v1/traces") else endpoint
    if settings.phoenix_host:
        return f"http://{settings.phoenix_host}:{settings.phoenix_port}"
    return None


async def _resolve_phoenix_endpoint(db: AsyncSession, agent: "Agent | None") -> tuple[str | None, str | None]:
    """(base_url, api_key), resolved in priority order: agent's own custom
    endpoint (no stored key for a custom endpoint — this deployment doesn't
    have credentials for an arbitrary third-party Phoenix) -> saved org
    config row -> this deployment's own env default."""
    if agent is not None and agent.phoenix_endpoint:
        return agent.phoenix_endpoint.rstrip("/"), None

    result = await db.execute(select(PhoenixConfig).where(PhoenixConfig.org_id == "org-default"))
    row = result.scalar_one_or_none()
    if row and row.enabled and row.endpoint:
        return row.endpoint.rstrip("/"), row.api_key or None

    settings = get_settings()
    return _phoenix_rest_base_url_from_settings(settings), settings.arize_phoenix_api_key or None


@value_waste_router.get("/compliance/eu-ai-act")
async def eu_ai_act_compliance(_=Depends(require_read)):
    """F-59: EU AI Act compliance mapping."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()

        tiers = {"Minimal Risk": [], "Limited Risk": [], "High Risk": []}
        for a in agents:
            cat = a.eu_ai_act_category or "Minimal Risk"
            if cat not in tiers:
                cat = "Minimal Risk"
            tiers[cat].append({"id": a.id, "name": a.name, "dept": a.dept_id, "ai_type": a.ai_type})

        return {
            "total_agents": len(agents),
            "tiers": {k: len(v) for k, v in tiers.items()},
            "agents_by_tier": tiers,
            "recommendation": "Review all 'High Risk' agents for mandatory conformity assessment under EU AI Act Article 6.",
        }


@value_waste_router.get("/batch-processing")
async def batch_processing_detection(_=Depends(require_read)):
    """F-67: Detect batch processing workloads."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()

        batch_agents = []
        for a in agents:
            is_batch = (
                not a.api_endpoint and
                a.ai_type in ["Predictive / ML Model", "Generative AI Feature"]
            )
            if is_batch:
                batch_agents.append({
                    "id": a.id,
                    "name": a.name,
                    "ai_type": a.ai_type,
                    "api_endpoint": a.api_endpoint or "N/A",
                    "recommendation": "Consider off-peak scheduling to reduce compute costs",
                })

        return {"batch_agents": batch_agents, "count": len(batch_agents)}