"""Keys for the registry's own API, and the two calls a CI pipeline makes:
register or update an agent from a manifest, and check that it may go to a
stage ("fail the build if the agent is not certified for the target stage")."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from api.auth import API_KEY_PREFIX, SCOPE_PERMS, hash_api_key, require_admin, require_create, require_read
from db.base import get_db_session
from db.models import Agent, ApiKey, AuditLog
from governance import gate_policy as gp
from orchestrations import governance_checks as gc
from orchestrations.risk_scan import as_utc
from services import reuse_repo

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — API keys and CI"])

SCOPES = tuple(SCOPE_PERMS)


def _key_to_api(k: ApiKey) -> dict:
    iso = lambda d: as_utc(d).isoformat() if d else None  # noqa: E731
    return {"id": k.id, "label": k.label, "prefix": k.prefix, "scopes": k.scopes or [], "createdBy": k.created_by,
            "createdAt": iso(k.created_at), "expiresAt": iso(k.expires_at), "lastUsedAt": iso(k.last_used_at),
            "revokedAt": iso(k.revoked_at), "active": k.revoked_at is None and (k.expires_at is None or as_utc(k.expires_at) > datetime.now(timezone.utc))}


class KeyCreate(BaseModel):
    label: str = Field(..., min_length=3, max_length=120)
    scopes: List[str] = Field(..., min_length=1)
    expiresInDays: Optional[int] = Field(None, ge=1, le=730)


@router.get("/admin/api-keys")
async def list_keys(_=Depends(require_admin)):
    async with get_db_session() as db:
        rows = (await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars().all()
    return [_key_to_api(k) for k in rows]


@router.post("/admin/api-keys")
async def issue_key(body: KeyCreate, user=Depends(require_admin)):
    """The key is in this answer only. It is stored as a hash and cannot be shown again."""
    bad = [s for s in body.scopes if s not in SCOPES]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown scope(s): {', '.join(bad)}. Scopes: {', '.join(SCOPES)}")
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(id=secrets.token_hex(8), label=body.label.strip(), prefix=key[:12], key_hash=hash_api_key(key),
                 scopes=sorted(set(body.scopes)), created_by=user.get("user_id"),
                 expires_at=datetime.now(timezone.utc) + timedelta(days=body.expiresInDays) if body.expiresInDays else None)
    async with get_db_session() as db:
        db.add(row)
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="api_key.issue",
                        entity_type="api_key", entity_id=row.id, changes={"label": row.label, "scopes": row.scopes, "prefix": row.prefix}))
    return {**_key_to_api(row), "key": key}


@router.delete("/admin/api-keys/{key_id}")
async def revoke_key(key_id: str, user=Depends(require_admin)):
    """Revoked at once. The key stays listed so its history is visible."""
    async with get_db_session() as db:
        row = await db.get(ApiKey, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="API key not found")
        if row.revoked_at is None:
            row.revoked_at, row.revoked_by = datetime.now(timezone.utc), user.get("user_id")
            db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="api_key.revoke",
                            entity_type="api_key", entity_id=row.id, changes={"label": row.label, "prefix": row.prefix}))
        result = _key_to_api(row)
    return result


# ── CI ───────────────────────────────────────────────────────────────────────

async def _find_agent(db, ref: str) -> Agent:
    from sqlalchemy.orm import selectinload

    ref = ref.strip()
    agent = (await db.execute(select(Agent).options(selectinload(Agent.governance_reviews)).where(
        or_(Agent.id == ref, Agent.slug == ref, func.lower(Agent.name) == ref.lower())))).scalars().first()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"No agent with id, slug or name {ref!r}")
    return agent


@router.get("/ci/check")
async def ci_check(agent: str = Query(..., min_length=1), stage: str = Query("Production"), _=Depends(require_read)):
    """May this agent go to `stage`? allowed=false lists every reason, so a
    pipeline can fail the build and print them."""
    if stage not in gp.STAGES:
        raise HTTPException(status_code=422, detail=f"stage must be one of: {', '.join(gp.STAGES)}")
    from api.routers.ops.governance import _readiness

    now = gc.utcnow()
    async with get_db_session() as db:
        a = await _find_agent(db, agent)
        state = await gc.load_state(db, a, now)
        readiness = _readiness(state, stage, now, "block")
        cert = (await reuse_repo.certifications(db, [a]))[a.id]
    reasons = [w["message"] for w in readiness["warnings"]]
    return {"agentId": a.id, "name": a.name, "currentStage": a.lifecycle_stage, "targetStage": stage,
            "allowed": not readiness["blocked"], "certifiedForReuse": bool(cert.get("certified")),
            "reasons": reasons}


class Manifest(BaseModel):
    """What a pipeline declares about its agent. Stage and risk level are not in
    a manifest: they change only through governance."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field("", max_length=255)
    description: str = ""
    owner: str = ""
    owner_contact: str = Field("", max_length=255)
    dept: str = ""
    ai_type: str = "Autonomous Agent"
    business_outcome: str = ""
    capabilities: List[str] = []
    inputs: List[str] = []
    outputs: List[str] = []
    api_endpoint: str = ""
    phoenix_project: str = ""
    model_name: str = ""
    version: str = Field("", max_length=50)
    sla: str = ""
    rate_limit: str = Field("", max_length=255)
    mcp_servers: List[str] = []
    knowledge_bases: List[str] = []
    reuse_justification: str = Field("", max_length=4000)


UPDATABLE = ("description", "owner", "owner_contact", "business_outcome", "capabilities", "inputs", "outputs",
             "api_endpoint", "phoenix_project", "model_name", "version", "sla", "rate_limit", "mcp_servers", "knowledge_bases")


@router.post("/ci/register")
async def ci_register(body: Manifest, user=Depends(require_create)):
    """Register the agent, or update its declared fields when it exists (matched by
    slug, then name). New agents start at Ideation with the duplicate check."""
    from api.routers.registry import AgentCreate, create_agent

    slug = body.slug.strip() or re.sub(r"[^a-z0-9-]", "", body.name.lower().replace(" ", "-"))
    async with get_db_session() as db:
        existing = (await db.execute(select(Agent).where(or_(Agent.slug == slug, func.lower(Agent.name) == body.name.lower())))).scalars().first()
        if existing is not None:
            changed = {}
            for field in UPDATABLE:
                value = getattr(body, field)
                value = value.strip() if isinstance(value, str) else value
                if value in ("", [], None):
                    continue
                if getattr(existing, field) != value:
                    changed[field] = value
                    setattr(existing, field, value)
            if changed:
                db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="update",
                                entity_type="agent", entity_id=existing.id, changes={**changed, "via": "ci_register"}))
            return {"id": existing.id, "status": "updated" if changed else "unchanged", "changed": sorted(changed)}
    created = await create_agent(AgentCreate(
        name=body.name, dept=body.dept, owner=body.owner, ai_type=body.ai_type, description=body.description,
        business_outcome=body.business_outcome, capabilities=body.capabilities, inputs=body.inputs, outputs=body.outputs,
        api_endpoint=body.api_endpoint, phoenix_project=body.phoenix_project, model_name=body.model_name, version=body.version,
        sla=body.sla, rate_limit=body.rate_limit, owner_contact=body.owner_contact, mcp_servers=body.mcp_servers,
        knowledge_bases=body.knowledge_bases, reuse_justification=body.reuse_justification), user)
    return {"id": created["id"], "status": "created", "changed": []}
