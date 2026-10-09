"""Connectors (Langfuse, GitHub, Azure) and what they found. Configuring a
connector needs an admin; reading findings needs read; acting on a finding
(dismiss, link, register) needs update. Secrets are never returned."""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_admin, require_read, require_update
from connectors.base import seal, secret_fields, unseal
from db.base import get_db_session
from db.models import Agent, ConnectorConfig, ExternalFinding
from governance import identity
from orchestrations.risk_scan import as_utc
from services import connectors as svc
from services.audit import log_audit_event

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Connectors"])

SECRET_KEYS = {"langfuse": ("public_key", "secret_key"), "github": ("token",), "azure": ("clientSecret",), "assureai": ("runKey",)}


def _iso(d):
    return as_utc(d).isoformat() if d else None


def _config_to_api(c: ConnectorConfig) -> dict:
    try:
        fields = secret_fields(unseal(c.secret_enc))
    except Exception:
        fields = []
    return {"id": c.id, "kind": c.kind, "kindLabel": svc.LABELS.get(c.kind, c.kind), "label": c.label, "settings": c.settings or {},
            "secretSet": fields, "enabled": c.enabled, "lastSyncAt": _iso(c.last_sync_at), "lastStatus": c.last_status,
            "lastMessage": c.last_message, "lastFound": c.last_found}


class ConnectorBody(BaseModel):
    kind: Optional[str] = None
    label: Optional[str] = Field(None, max_length=120)
    settings: Optional[dict] = None
    secret: Optional[dict] = None
    enabled: Optional[bool] = None


@router.get("/connectors")
async def list_connectors(_=Depends(require_read)):
    async with get_db_session() as db:
        rows = (await db.execute(select(ConnectorConfig).order_by(ConnectorConfig.created_at))).scalars().all()
    return {"kinds": [{"kind": k, "label": v, "secretKeys": list(SECRET_KEYS[k])} for k, v in svc.LABELS.items()],
            "connectors": [_config_to_api(c) for c in rows]}


@router.post("/connectors")
async def create_connector(body: ConnectorBody, user=Depends(require_admin)):
    if body.kind not in svc.KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of: {', '.join(svc.KINDS)}")
    secret = {k: v for k, v in (body.secret or {}).items() if k in SECRET_KEYS[body.kind] and v}
    c = ConnectorConfig(id=secrets.token_hex(8), kind=body.kind, label=(body.label or svc.LABELS[body.kind]).strip(),
                        settings=body.settings or {}, secret_enc=seal(secret), enabled=body.enabled is not False,
                        created_by=user.get("user_id"))
    async with get_db_session() as db:
        db.add(c)
    await log_audit_event(actor=user["user_id"], action="settings.update", entity_type="connector", entity_id=c.id,
                          changes={"created": body.kind, "label": c.label, "settings": c.settings, "secretSet": sorted(secret)})
    return _config_to_api(c)


@router.put("/connectors/{connector_id}")
async def update_connector(connector_id: str, body: ConnectorBody, user=Depends(require_admin)):
    async with get_db_session() as db:
        c = await db.get(ConnectorConfig, connector_id)
        if c is None:
            raise HTTPException(status_code=404, detail="Connector not found")
        if body.label is not None:
            c.label = body.label.strip() or c.label
        if body.settings is not None:
            c.settings = body.settings
        if body.enabled is not None:
            c.enabled = body.enabled
        if body.secret:
            current = unseal(c.secret_enc)
            current.update({k: v for k, v in body.secret.items() if k in SECRET_KEYS[c.kind] and v})
            c.secret_enc = seal(current)
        result = _config_to_api(c)
    await log_audit_event(actor=user["user_id"], action="settings.update", entity_type="connector", entity_id=connector_id,
                          changes={"label": result["label"], "settings": result["settings"], "enabled": result["enabled"],
                                   "secretChanged": sorted((body.secret or {}).keys())})
    return result


@router.delete("/connectors/{connector_id}")
async def delete_connector(connector_id: str, user=Depends(require_admin)):
    async with get_db_session() as db:
        c = await db.get(ConnectorConfig, connector_id)
        if c is None:
            raise HTTPException(status_code=404, detail="Connector not found")
        label = c.label
        for f in (await db.execute(select(ExternalFinding).where(ExternalFinding.connector_id == connector_id))).scalars():
            await db.delete(f)
        await db.delete(c)
    await log_audit_event(actor=user["user_id"], action="settings.update", entity_type="connector", entity_id=connector_id,
                          changes={"deleted": label})
    return {"status": "deleted"}


@router.post("/connectors/{connector_id}/test")
async def test_connector(connector_id: str, _=Depends(require_admin)):
    return await svc.test(connector_id)


@router.post("/connectors/{connector_id}/sync")
async def sync_connector(connector_id: str, user=Depends(require_update)):
    result = await svc.sync(connector_id)
    await log_audit_event(actor=user["user_id"], action="job.run", entity_type="connector", entity_id=connector_id, changes=result)
    return result


# ── Findings ─────────────────────────────────────────────────────────────────

def _finding_to_api(f: ExternalFinding, config: ConnectorConfig | None) -> dict:
    return {"id": f.id, "kind": f.kind, "name": f.name, "url": f.url, "details": f.details or {}, "state": f.state,
            "dismissReason": f.dismiss_reason, "linkedAgentId": f.linked_agent_id, "firstSeenAt": _iso(f.first_seen_at),
            "lastSeenAt": _iso(f.last_seen_at), "connectorId": f.connector_id,
            "connector": {"kind": config.kind, "label": config.label} if config else None}


@router.get("/connectors/findings")
async def findings(_=Depends(require_read)):
    """Everything the connectors found, with the registered agents each may be."""
    async with get_db_session() as db:
        rows = (await db.execute(select(ExternalFinding).order_by(ExternalFinding.last_seen_at.desc()))).scalars().all()
        configs = {c.id: c for c in (await db.execute(select(ConnectorConfig))).scalars()}
        agents = (await db.execute(select(Agent))).scalars().all()
    candidates = [{"id": a.id, "slug": a.slug, "name": a.name, "owner": a.owner, "apiEndpoint": a.api_endpoint,
                   "phoenixProject": a.phoenix_project, "modelName": a.model_name, "mcpServers": a.mcp_servers or []} for a in agents]
    out = []
    for f in rows:
        item = _finding_to_api(f, configs.get(f.connector_id))
        if f.state == "new":
            probe = {"name": f.name, "serviceNames": [], "models": [m for m in [f.details.get("model")] if m] + list(f.details.get("models") or []),
                     "tools": []}
            item["matches"] = identity.matches(probe, candidates)
        out.append(item)
    return {"findings": out, "summary": {s: len([x for x in out if x["state"] == s]) for s in ("new", "dismissed", "linked")}}


class DismissBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/connectors/findings/{finding_id}/dismiss")
async def dismiss_finding(finding_id: str, body: DismissBody, user=Depends(require_update)):
    async with get_db_session() as db:
        f = await db.get(ExternalFinding, finding_id)
        if f is None:
            raise HTTPException(status_code=404, detail="Finding not found")
        f.state, f.dismiss_reason = "dismissed", body.reason.strip()
    await log_audit_event(actor=user["user_id"], action="discovery.dismiss", entity_type="finding", entity_id=finding_id,
                          changes={"reason": body.reason.strip()})
    return {"status": "dismissed"}


@router.post("/connectors/findings/{finding_id}/restore")
async def restore_finding(finding_id: str, user=Depends(require_update)):
    async with get_db_session() as db:
        f = await db.get(ExternalFinding, finding_id)
        if f is None:
            raise HTTPException(status_code=404, detail="Finding not found")
        f.state, f.dismiss_reason, f.linked_agent_id = "new", None, None
    await log_audit_event(actor=user["user_id"], action="discovery.restore", entity_type="finding", entity_id=finding_id)
    return {"status": "new"}


class LinkBody(BaseModel):
    agentId: str = Field(..., max_length=64)


@router.post("/connectors/findings/{finding_id}/link")
async def link_finding(finding_id: str, body: LinkBody, user=Depends(require_update)):
    """This finding is that registered agent: record where it is known (repository,
    cloud resource, or the Langfuse project that holds its traces)."""
    async with get_db_session() as db:
        f = await db.get(ExternalFinding, finding_id)
        agent = await db.get(Agent, body.agentId)
        if f is None or agent is None:
            raise HTTPException(status_code=404, detail="Finding or agent not found")
        if f.kind == "code_repo":
            agent.source_repo = f.url or f.external_id
        elif f.kind in ("cloud_deployment", "cloud_agent"):
            agent.cloud_resource_id = f.external_id
        elif f.kind == "trace_project":
            agent.trace_connector_id = f.connector_id
        f.state, f.linked_agent_id = "linked", agent.id
        name = agent.name
    await log_audit_event(actor=user["user_id"], action="discovery.merge", entity_type="agent", entity_id=body.agentId,
                          changes={"finding": f.name, "kind": f.kind})
    return {"status": "linked", "agentId": body.agentId, "agentName": name}


@router.get("/connectors/findings/{finding_id}/prefill")
async def finding_prefill(finding_id: str, _=Depends(require_read)):
    """Registration form values from a finding, each with where it came from."""
    async with get_db_session() as db:
        f = await db.get(ExternalFinding, finding_id)
        config = await db.get(ConnectorConfig, f.connector_id) if f else None
    if f is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    d, where = f.details or {}, f"{(config.label if config else 'connector')}"
    fields: dict = {"name": f.name}
    sources: dict = {"name": where}
    card = d.get("agentCard") or {}
    description = card.get("description") or d.get("description")
    if description:
        fields["description"], sources["description"] = description, f"{where} ({'agent card' if card.get('description') else 'repository description'})"
    if card.get("skills"):
        fields["capabilities"], sources["capabilities"] = card["skills"], f"{where} (agent card skills)"
    model = d.get("model") or (d.get("models") or [None])[0]
    if model:
        fields["model_name"], sources["model_name"] = model, f"{where} (model)"
    if d.get("tools"):
        fields["mcp_servers"], sources["mcp_servers"] = [t for t in d["tools"] if t], f"{where} (tools)"
    return {"findingId": f.id, "fields": fields, "sources": sources}
