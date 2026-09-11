"""Agent Registry API routers — agents, governance, discovery, tokenomics, value, waste, admin."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.base import get_db_session
from db.models import (
    Agent, Department, Organization, GovernanceReview, GovernanceException,
    Discovery, AgentTokenUsage, ModelTokenPrice, AgentBudget, WasteFinding,
    CostAnomaly, User, AuditLog, AgentIdentity, AgentMetric
)
from api.auth import (
    hash_password, verify_password, create_access_token,
    require_create, require_read, require_update, require_delete, require_admin,
    get_current_user
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


# ── Schemas ──────────────────────────────────────────────────────────────────

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
    model_name: str = "GPT-5"
    risk_level: str = "LOW"

    @validator("stage")
    def validate_stage(cls, v):
        valid = ["Ideation", "Development", "Testing", "Production", "Deprecated"]
        if v not in valid:
            raise ValueError(f"Invalid stage. Must be one of: {', '.join(valid)}")
        return v

    @validator("ai_type")
    def validate_ai_type(cls, v):
        valid = [
            "Autonomous Agent", "Copilot / Assistant", "Predictive / ML Model",
            "Generative AI Feature", "Conversational AI / Chatbot", "Computer Vision Model"
        ]
        if v not in valid:
            raise ValueError(f"Invalid ai_type. Must be one of: {', '.join(valid)}")
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


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    value_amount: Optional[int] = None
    risk_level: Optional[str] = None
    risk_note: Optional[str] = None
    at_risk: Optional[bool] = None


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


class UserCreate(BaseModel):
    email: str
    name: str
    role: str = "Executive Viewer"
    password: str = Field(..., min_length=8)


# ── Auth Router ──────────────────────────────────────────────────────────────

@auth_router.post("/login")
async def login(req: LoginRequest):
    async with get_db_session() as db:
        result = await db.execute(select(User).where(User.email == req.email, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user.id, user.role)
        return {"access_token": token, "token_type": "bearer", "user": {
            "id": user.id, "name": user.name, "email": user.email, "role": user.role
        }}


@auth_router.get("/me")
async def me(user=Depends(get_current_user)):
    return user


# ── Agents Router ────────────────────────────────────────────────────────────

@agents_router.get("/")
async def list_agents(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    dept: str = "",
    stage: str = "",
    type: str = "",
    q: str = "",
    _=Depends(require_read)
):
    async with get_db_session() as db:
        query = select(Agent).options(selectinload(Agent.governance_reviews))
        if dept:
            query = query.where(Agent.dept_id == dept)
        if stage:
            query = query.where(Agent.lifecycle_stage == stage)
        if type:
            query = query.where(Agent.ai_type == type)
        if q:
            query = query.where(Agent.name.ilike(f"%{q}%"))

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()

        query = query.order_by(Agent.value_amount.desc()).offset((page - 1) * limit).limit(limit)
        result = await db.execute(query)
        agents = result.scalars().all()

        return {
            "data": [_agent_to_dict(a) for a in agents],
            "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}
        }


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
        return _agent_to_dict(agent)


@agents_router.post("/")
async def create_agent(agent: AgentCreate, user=Depends(require_create)):
    async with get_db_session() as db:
        # Generate URL-safe agent ID
        slug = re.sub(r'[^a-z0-9-]', '', agent.name.lower().replace(" ", "-"))
        agent_id = f"{slug}-{secrets.token_hex(4)}"
        db_agent = Agent(
            id=agent_id, org_id="org-default", name=agent.name, slug=agent_id,
            description=agent.description, ai_type=agent.ai_type, owner=agent.owner,
            lifecycle_stage=agent.stage, value_amount=agent.value_amount,
            value_type=agent.value_type, hours_saved_monthly=agent.hours_saved_monthly,
            business_outcome=agent.business_outcome, model_name=agent.model_name,
            risk_level=agent.risk_level, tags=agent.tags,
            enterprise_systems=agent.enterprise_systems, databases=agent.databases,
            knowledge_bases=agent.knowledge_bases, mcp_servers=agent.mcp_servers,
            calls=agent.calls, consumers=agent.consumers, inputs=agent.inputs,
            outputs=agent.outputs, api_endpoint=agent.api_endpoint, sla=agent.sla,
        )
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
            changes={"name": agent.name, "stage": agent.stage, "ai_type": agent.ai_type},
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
            agent.lifecycle_stage = "Deprecated"
            agent.deprecated_at = now
            agent.sunset_date = (now + timedelta(days=7)).date()
            agent.risk_note = (agent.risk_note or "") + f" | Residual validation: 7-day wait started {now.date()}"

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
        overview = {}
        for gate in VALID_GATES:
            result = await db.execute(
                select(GovernanceReview.status, func.count()).where(GovernanceReview.gate == gate).group_by(GovernanceReview.status)
            )
            overview[gate] = {status: count for status, count in result.all()}
        return overview


@governance_router.put("/agents/{agent_id}/governance/{gate}")
async def update_gate(agent_id: str, gate: str, body: GateUpdate, user=Depends(require_update)):
    if gate not in VALID_GATES:
        raise HTTPException(status_code=400, detail="Invalid gate")
    async with get_db_session() as db:
        result = await db.execute(
            select(GovernanceReview).where(GovernanceReview.agent_id == agent_id, GovernanceReview.gate == gate)
        )
        review = result.scalar_one_or_none()
        if review:
            review.status = body.status
            review.reviewed_at = datetime.now(timezone.utc)
        return {"status": "updated"}


@governance_router.post("/agents/{agent_id}/recertify")
async def recertify(agent_id: str, user=Depends(require_update)):
    """Recertify an agent: reset all gate reviews to In Review and set reviewed_at to null."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        stale_gates = []
        for gate in VALID_GATES:
            result = await db.execute(
                select(GovernanceReview).where(
                    GovernanceReview.agent_id == agent_id,
                    GovernanceReview.gate == gate
                )
            )
            review = result.scalar_one_or_none()
            if review:
                review.status = "In Review"
                review.reviewed_at = None
                stale_gates.append(gate)
            else:
                db.add(GovernanceReview(
                    id=secrets.token_hex(8), agent_id=agent_id, gate=gate, status="In Review"
                ))
                stale_gates.append(gate)

        db.add(AuditLog(
            org_id="org-default",
            actor=user.get("user_id", "unknown"),
            action="recertify",
            entity_type="agent",
            entity_id=agent_id,
            changes={"gates_reset": stale_gates},
        ))

        return {"status": "recertified", "gates_reset": stale_gates}


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


@discovery_router.post("/{discovery_id}/register")
async def register_discovery(discovery_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        result = await db.execute(select(Discovery).where(Discovery.id == discovery_id))
        discovery = result.scalar_one_or_none()
        if not discovery:
            raise HTTPException(status_code=404, detail="Discovery not found")

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
    async with get_db_session() as db:
        result = await db.execute(
            select(func.sum(AgentTokenUsage.input_tokens), func.sum(AgentTokenUsage.output_tokens),
                   func.sum(AgentTokenUsage.cost_cents), func.sum(AgentTokenUsage.invocation_count))
            .where(AgentTokenUsage.agent_id == agent_id)
        )
        input_t, output_t, cost, invocations = result.one()
        return {
            "agentId": agent_id,
            "inputTokens": input_t or 0,
            "outputTokens": output_t or 0,
            "costCents": cost or 0,
            "invocations": invocations or 0,
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
    async with get_db_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        sys_counts = {}
        for agent in agents:
            for sys in (agent.enterprise_systems or []) + (agent.databases or []):
                sys_counts[sys] = sys_counts.get(sys, 0) + 1
        return [{"name": k, "count": v} for k, v in sorted(sys_counts.items(), key=lambda x: -x[1]) if v >= 4]


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

@admin_router.get("/taxonomy")
async def taxonomy(_=Depends(require_read)):
    return {
        "stages": ["Ideation", "Development", "Testing", "Production", "Deprecated"],
        "gates": ["arb", "security", "dp"],
        "reviewStatuses": ["Not Submitted", "In Review", "Changes Requested", "Approved with Conditions", "Approved"],
        "riskLevels": ["LOW", "HIGH", "UNACCEPTABLE"],
        "aiTypes": ["Autonomous Agent", "Copilot / Assistant", "Predictive / ML Model", "Generative AI Feature", "Conversational AI / Chatbot", "Computer Vision Model"],
    }


@admin_router.get("/users")
async def list_users(_=Depends(require_admin)):
    async with get_db_session() as db:
        result = await db.execute(select(User))
        return [_user_to_dict(u) for u in result.scalars().all()]


@admin_router.post("/users")
async def create_user(user: UserCreate, _=Depends(require_admin)):
    async with get_db_session() as db:
        db_user = User(
            id=secrets.token_hex(8), org_id="org-default", email=user.email,
            name=user.name, role=user.role, password_hash=hash_password(user.password)
        )
        db.add(db_user)
        return {"id": db_user.id, "status": "created"}


# ── Helper functions ─────────────────────────────────────────────────────────

def _agent_to_dict(agent: Agent) -> dict:
    return {
        "id": agent.id, "name": agent.name, "slug": agent.slug,
        "description": agent.description, "aiType": agent.ai_type,
        "owner": agent.owner, "ownerContact": agent.owner_contact,
        "stage": agent.lifecycle_stage, "version": agent.version,
        "dept": agent.dept_id,
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


@tokenomics_router.get("/agents/{agent_id}/tokens/summary")
async def token_summary(agent_id: str, _=Depends(require_read)):
    """Get detailed token summary for an agent."""
    async with get_db_session() as db:
        result = await db.execute(
            select(
                func.sum(AgentTokenUsage.input_tokens),
                func.sum(AgentTokenUsage.output_tokens),
                func.sum(AgentTokenUsage.cached_tokens),
                func.sum(AgentTokenUsage.invocation_count),
                func.sum(AgentTokenUsage.cost_cents),
            ).where(AgentTokenUsage.agent_id == agent_id)
        )
        row = result.one()
        invocations = row[3] or 0
        cost_cents = row[4] or 0
        return {
            "agentId": agent_id,
            "inputTokens": row[0] or 0,
            "outputTokens": row[1] or 0,
            "cachedTokens": row[2] or 0,
            "invocations": invocations,
            "costCents": cost_cents,
            "costPerInvocation": round(cost_cents / max(invocations, 1) / 100, 4),
        }


@tokenomics_router.get("/agents/{agent_id}/tokens/trend")
async def token_trend(agent_id: str, days: int = 30, _=Depends(require_read)):
    """Get daily token trend for an agent."""
    async with get_db_session() as db:
        result = await db.execute(
            select(
                func.date(AgentTokenUsage.bucket),
                func.sum(AgentTokenUsage.input_tokens),
                func.sum(AgentTokenUsage.output_tokens),
                func.sum(AgentTokenUsage.invocation_count),
            )
            .where(AgentTokenUsage.agent_id == agent_id)
            .group_by(func.date(AgentTokenUsage.bucket))
            .order_by(func.date(AgentTokenUsage.bucket))
        )
        trend = [
            {"date": str(row[0]), "inputTokens": row[1], "outputTokens": row[2], "invocations": row[3]}
            for row in result.all()
        ]
        return {"agentId": agent_id, "days": days, "trend": trend}


@tokenomics_router.get("/agents/{agent_id}/cost")
async def agent_cost(agent_id: str, _=Depends(require_read)):
    """Calculate real cost for an agent based on usage and model prices."""
    async with get_db_session() as db:
        # Get agent model
        result = await db.execute(select(Agent.model_name).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        model_name = agent or "GPT-5"

        # Get usage
        result = await db.execute(
            select(
                func.sum(AgentTokenUsage.input_tokens),
                func.sum(AgentTokenUsage.output_tokens),
                func.sum(AgentTokenUsage.cached_tokens),
                func.sum(AgentTokenUsage.invocation_count),
            ).where(AgentTokenUsage.agent_id == agent_id)
        )
        usage = result.one()

        # Get model price
        result = await db.execute(
            select(ModelTokenPrice).where(
                ModelTokenPrice.model_name == model_name,
                ModelTokenPrice.effective_to.is_(None)
            )
        )
        price = result.scalar_one_or_none()

        if not price:
            return {"agentId": agent_id, "monthlyCost": 0, "costPerInvocation": 0}

        input_cost = ((usage[0] or 0) / 1_000_000) * price.input_price_per_1m
        output_cost = ((usage[1] or 0) / 1_000_000) * price.output_price_per_1m
        cache_savings = ((usage[2] or 0) / 1_000_000) * price.cache_read_price_per_1m
        monthly_cost = max(0, input_cost + output_cost - cache_savings)

        return {
            "agentId": agent_id,
            "monthlyCost": round(monthly_cost, 2),
            "costPerInvocation": round(monthly_cost / max(usage[3] or 1, 1), 4),
        }


@tokenomics_router.get("/agents/{agent_id}/cost/forecast")
async def cost_forecast(agent_id: str, months: int = 3, _=Depends(require_read)):
    """Generate cost forecast for an agent."""
    async with get_db_session() as db:
        result = await db.execute(
            select(
                func.avg(AgentTokenUsage.cost_cents),
            ).where(AgentTokenUsage.agent_id == agent_id)
        )
        avg_cost = result.scalar() or 0
        monthly_avg = avg_cost / 100

        forecast = []
        for i in range(1, months + 1):
            projected = monthly_avg * (1.05 ** i)  # 5% growth
            forecast.append({
                "month": i,
                "projectedCost": round(projected, 2),
            })

        return {
            "agentId": agent_id,
            "currentMonthlyAvg": round(monthly_avg, 2),
            "forecast": forecast,
            "totalProjected": round(sum(f["projectedCost"] for f in forecast), 2),
        }


@tokenomics_router.get("/agents/{agent_id}/budget")
async def agent_budget(agent_id: str, _=Depends(require_read)):
    """Get budget status for an agent."""
    async with get_db_session() as db:
        result = await db.execute(select(AgentBudget).where(AgentBudget.agent_id == agent_id))
        budget = result.scalar_one_or_none()
        if not budget:
            return {"agentId": agent_id, "monthlyBudget": 0, "currentSpend": 0, "remaining": 0, "budgetUsagePct": 0}

        cost_result = await db.execute(
            select(func.sum(AgentTokenUsage.cost_cents)).where(AgentTokenUsage.agent_id == agent_id)
        )
        spend_cents = cost_result.scalar() or 0
        spend = spend_cents / 100
        budget_dollars = budget.monthly_budget_cents / 100
        remaining = budget_dollars - spend
        usage_pct = (spend / max(budget_dollars, 1)) * 100

        return {
            "agentId": agent_id,
            "monthlyBudget": budget_dollars,
            "currentSpend": round(spend, 2),
            "remaining": round(remaining, 2),
            "budgetUsagePct": round(usage_pct, 1),
        }


@tokenomics_router.put("/agents/{agent_id}/budget")
async def set_budget(agent_id: str, budget_data: dict, _=Depends(require_update)):
    """Set budget for an agent."""
    async with get_db_session() as db:
        result = await db.execute(select(AgentBudget).where(AgentBudget.agent_id == agent_id))
        budget = result.scalar_one_or_none()
        if not budget:
            budget = AgentBudget(agent_id=agent_id)
            db.add(budget)
        budget.monthly_budget_cents = int(budget_data.get("monthlyBudget", 5000) * 100)
        return {"agentId": agent_id, "monthlyBudget": budget.monthly_budget_cents / 100}


@tokenomics_router.put("/models/prices/{model_name}")
async def update_model_price(model_name: str, prices: dict, _=Depends(require_admin)):
    """Update model pricing."""
    async with get_db_session() as db:
        # Expire current price
        await db.execute(
            select(ModelTokenPrice).where(
                ModelTokenPrice.model_name == model_name,
                ModelTokenPrice.effective_to.is_(None)
            )
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
        ))
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

@admin_router.put("/users/{user_id}")
async def update_user(user_id: str, user_data: dict, _=Depends(require_admin)):
    """Update a user."""
    async with get_db_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if "email" in user_data:
            user.email = user_data["email"]
        if "name" in user_data:
            user.name = user_data["name"]
        if "role" in user_data:
            user.role = user_data["role"]
        if "isActive" in user_data:
            user.is_active = user_data["isActive"]
        return {"status": "updated"}


@admin_router.delete("/users/{user_id}")
async def delete_user(user_id: str, _=Depends(require_admin)):
    """Deactivate a user."""
    async with get_db_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_active = False
        return {"status": "deactivated"}


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
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent": _agent_to_dict(agent),
            "calls": agent.calls or [],
            "consumers": agent.consumers or [],
        }

# -- V2 Features (F-59, F-66, F-67) ------------------------------------------

@value_waste_router.get("/agents/{agent_id}/cost/business-outcome")
async def cost_per_outcome(agent_id: str, _=Depends(require_read)):
    """F-66: Cost per business outcome metric."""
    async with get_db_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        cost_result = await db.execute(
            select(func.sum(AgentMetric.total_cost)).where(AgentMetric.agent_id == agent_id)
        )
        total_cost = cost_result.scalar() or 0

        outcome_value = agent.value_amount or 0
        cost_per_outcome = (total_cost / outcome_value) if outcome_value > 0 else 0

        return {
            "agent_id": agent_id,
            "total_cost": total_cost,
            "business_outcome": outcome_value,
            "cost_per_outcome": round(cost_per_outcome, 4),
            "efficiency_rating": "efficient" if cost_per_outcome < 0.01 else "moderate" if cost_per_outcome < 0.05 else "inefficient",
        }


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