"""Agent page — Integrate tab API: what a team needs to consume an agent.

The contract (endpoint, inputs, outputs, SLA, rate limit), whether the agent
is certified for reuse, access requests and their approval, and Try it, a
server-side call to the agent's own endpoint.

Try it runs from the registry's network, so it refuses link-local and
reserved addresses (cloud metadata), loopback outside development, embedded
credentials and redirects, and never forwards the caller's token. Private
ranges stay allowed because internal agents live on them."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.auth import require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentAccessRequest, AuditLog, User
from governance import reuse
from governance.gate_policy import endpoint_kind
from orchestrations.risk_scan import as_utc
from services import reuse_repo
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Integrate"])

ORG_ID = "org-default"
MAX_REQUEST_BYTES = 32_000
MAX_RESPONSE_BYTES = 64_000
OPEN_STATUSES = ("pending", "approved")


class ContractIn(BaseModel):
    api_endpoint: Optional[str] = Field(None, max_length=500)
    capabilities: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    sla: Optional[str] = Field(None, max_length=255)
    rate_limit: Optional[str] = Field(None, max_length=255)
    owner_contact: Optional[str] = Field(None, max_length=255)


class AccessRequestIn(BaseModel):
    team: str = Field(..., min_length=2, max_length=255)
    purpose: str = Field(..., min_length=10, max_length=2000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "revoke"]
    note: Optional[str] = Field(None, max_length=2000)


class TryIn(BaseModel):
    method: Literal["POST", "GET"] = "POST"
    body: Any = None


def _iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def _request_dict(r: AgentAccessRequest) -> dict:
    return {
        "id": r.id, "team": r.team, "purpose": r.purpose, "status": r.status,
        "requesterId": r.requester_id, "requesterName": r.requester_name,
        "decidedBy": r.decided_by, "decidedAt": _iso(r.decided_at), "decisionNote": r.decision_note,
        "createdAt": _iso(r.created_at),
    }


async def _agent_or_404(db, agent_id: str) -> Agent:
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews))
    )).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _user_label(db, user_id: str) -> str:
    user = await db.get(User, user_id)
    return f"{user.name} <{user.email}>" if user else user_id


def _try_it_state(agent: Agent) -> dict:
    if agent.lifecycle_stage in reuse.NOT_REUSABLE_STAGES:
        return {"available": False, "reason": "The agent is deprecated", "url": None}
    try:
        url = reuse.resolve_try_url(agent.api_endpoint, get_settings().agent_gateway_base_url)
    except reuse.TryItBlocked as exc:
        return {"available": False, "reason": str(exc), "url": None}
    return {"available": True, "reason": None, "url": url}


def _audit(agent_id: str, actor: str, action: str, changes: dict) -> AuditLog:
    return AuditLog(org_id=ORG_ID, actor=actor, action=action, entity_type="agent",
                    entity_id=agent_id, changes=changes)


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/integration")
async def integration(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        cert = (await reuse_repo.certifications(db, [agent]))[agent.id]
        requests = (await db.execute(
            select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id)
            .order_by(AgentAccessRequest.created_at.desc(), AgentAccessRequest.id)
        )).scalars().all()
    approved = {r.team.lower() for r in requests if r.status == "approved"}
    consumers = agent.consumers or []
    return {
        "agentId": agent.id,
        "contract": {
            "apiEndpoint": agent.api_endpoint, "endpointKind": endpoint_kind(agent.api_endpoint),
            "endpointAdvice": reuse.endpoint_advice(agent.api_endpoint),
            "capabilities": agent.capabilities or [], "inputs": agent.inputs or [], "outputs": agent.outputs or [],
            "sla": agent.sla, "rateLimit": agent.rate_limit,
            "owner": agent.owner, "ownerContact": agent.owner_contact,
        },
        "gaps": reuse.contract_gaps(reuse_repo.agent_mapping(agent)),
        "reuse": cert,
        "reuseCheck": {"checked": agent.reuse_checked or [], "justification": agent.reuse_justification},
        "tryIt": {**_try_it_state(agent), "examplePayload": reuse.example_payload(agent.inputs)},
        "accessRequests": [_request_dict(r) for r in requests],
        "consumers": {
            "approvedTeams": [c for c in consumers if c.lower() in approved],
            "declared": [c for c in consumers if c.lower() not in approved],
        },
    }


# ── Contract ─────────────────────────────────────────────────────────────────

@router.put("/agents/{agent_id}/contract")
async def update_contract(agent_id: str, body: ContractIn, user=Depends(require_update)):
    changes = body.model_dump(exclude_unset=True)
    for key in ("capabilities", "inputs", "outputs"):
        if key in changes:
            try:
                changes[key] = reuse.clean_list(changes[key] or [])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
    for key in ("api_endpoint", "sla", "rate_limit", "owner_contact"):
        if key in changes:
            changes[key] = (changes[key] or "").strip() or None
    if changes.get("api_endpoint") and endpoint_kind(changes["api_endpoint"]) != "app":
        raise HTTPException(status_code=422, detail="The API endpoint must be the agent's own http(s) URL or "
                                                    "path, not a tracing/observability URL")
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        before = {k: getattr(agent, k) for k in changes}
        for key, value in changes.items():
            setattr(agent, key, value)
        db.add(_audit(agent_id, user.get("user_id", "unknown"), "update",
                      {k: {"before": before[k], "after": v} for k, v in changes.items() if before[k] != v}))
    return {"status": "updated", "fields": sorted(changes)}


# ── Access requests ──────────────────────────────────────────────────────────

@router.post("/agents/{agent_id}/access-requests")
async def request_access(agent_id: str, body: AccessRequestIn, user=Depends(require_update)):
    team, purpose = " ".join(body.team.split()), body.purpose.strip()
    requester = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        if agent.lifecycle_stage in reuse.NOT_REUSABLE_STAGES:
            raise HTTPException(status_code=409, detail="The agent is deprecated and not open to new consumers")
        existing = (await db.execute(
            select(AgentAccessRequest).where(AgentAccessRequest.agent_id == agent_id,
                                             AgentAccessRequest.status.in_(OPEN_STATUSES))
        )).scalars().all()
        clash = next((r for r in existing if r.team.lower() == team.lower()), None)
        if clash:
            raise HTTPException(status_code=409, detail=f"{clash.team} already has a {clash.status} request")
        row = AgentAccessRequest(
            id=secrets.token_hex(8), agent_id=agent_id, requester_id=requester,
            requester_name=await _user_label(db, requester), team=team, purpose=purpose, status="pending",
        )
        db.add(row)
        db.add(_audit(agent_id, requester, "access_request", {"request_id": row.id, "team": team}))
    return {"id": row.id, "status": "pending"}


@router.post("/agents/{agent_id}/access-requests/{request_id}/decision")
async def decide_access(agent_id: str, request_id: str, body: DecisionIn, user=Depends(require_update)):
    actor = user.get("user_id", "unknown")
    note = (body.note or "").strip() or None
    if body.decision in ("reject", "revoke") and not note:
        raise HTTPException(status_code=422, detail=f"A note is required to {body.decision} access")
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
        row = await db.get(AgentAccessRequest, request_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Access request not found")
        allowed = {"approve": "pending", "reject": "pending", "revoke": "approved"}[body.decision]
        if row.status != allowed:
            raise HTTPException(status_code=409, detail=f"Cannot {body.decision} a request that is {row.status}")
        # Segregation of duties: with RBAC off, anyone could otherwise
        # approve their own request.
        if body.decision == "approve" and row.requester_id == actor:
            raise HTTPException(status_code=403, detail="You cannot approve your own access request")

        consumers = list(agent.consumers or [])
        lowered = [c.lower() for c in consumers]
        if body.decision == "approve":
            row.status = "approved"
            if row.team.lower() not in lowered:
                consumers.append(row.team)
                row.added_to_consumers = True
        elif body.decision == "reject":
            row.status = "rejected"
        else:
            row.status = "revoked"
            if row.added_to_consumers:
                consumers = [c for c in consumers if c.lower() != row.team.lower()]
                row.added_to_consumers = False
        # A new list, so SQLAlchemy sees the JSON column change.
        agent.consumers = consumers
        row.decided_by = await _user_label(db, actor)
        row.decided_at = datetime.now(timezone.utc)
        row.decision_note = note
        db.add(_audit(agent_id, actor, f"access_{body.decision}",
                      {"request_id": row.id, "team": row.team, "consumers": consumers}))
    return {"id": request_id, "status": row.status}


# ── Try it ───────────────────────────────────────────────────────────────────

_recent_calls: dict[tuple[str, str], deque] = defaultdict(deque)


def _within_rate_limit(user_id: str, agent_id: str, per_minute: int) -> bool:
    now = time.monotonic()
    calls = _recent_calls[(user_id, agent_id)]
    while calls and now - calls[0] > 60:
        calls.popleft()
    if len(calls) >= per_minute:
        return False
    calls.append(now)
    return True


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port)
    return [info[4][0] for info in infos]


def _http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _read_capped(resp: httpx.Response) -> tuple[bytes, bool]:
    """Stops reading at MAX_RESPONSE_BYTES, so a huge reply never sits in memory."""
    chunks, size = [], 0
    async for chunk in resp.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            return b"".join(chunks)[:MAX_RESPONSE_BYTES], True
    return b"".join(chunks), False


def _decode(resp: httpx.Response, raw: bytes, truncated: bool) -> Any:
    try:
        text = raw.decode(resp.charset_encoding or "utf-8", errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    if not truncated and "json" in resp.headers.get("content-type", ""):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


@router.post("/agents/{agent_id}/try")
async def try_agent(agent_id: str, body: TryIn, user=Depends(require_update)):
    settings = get_settings()
    actor = user.get("user_id", "unknown")
    async with get_db_session() as db:
        agent = await _agent_or_404(db, agent_id)
    state = _try_it_state(agent)
    if not state["available"]:
        raise HTTPException(status_code=422, detail=state["reason"])
    url = state["url"]
    payload = None if body.method == "GET" else json.dumps(body.body if body.body is not None else {})
    if payload is not None and len(payload.encode()) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail=f"Request body is over {MAX_REQUEST_BYTES // 1000} KB")
    if not _within_rate_limit(actor, agent_id, settings.try_it_calls_per_minute):
        raise HTTPException(status_code=429, detail=f"At most {settings.try_it_calls_per_minute} Try it calls "
                                                    "per minute per agent")

    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    result: dict[str, Any] = {"url": url, "method": body.method}
    try:
        # Checked before connecting; the hostname is resolved again on
        # connect, which leaves a DNS-rebinding window this does not close.
        reuse.check_addresses(await _resolve(parsed.hostname, port), settings.app_env == "development")
    except reuse.TryItBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSError as exc:
        result.update(ok=False, error=f"Could not resolve {parsed.hostname}: {exc.strerror or exc}")
    else:
        headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.5", "X-Registry-Try-It": "true"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            async with _http_client(settings.try_it_timeout_seconds) as client:
                async with client.stream(body.method, url, content=payload, headers=headers) as resp:
                    raw, truncated = await _read_capped(resp)
        except httpx.TimeoutException:
            result.update(ok=False, error=(
                f"No response within {settings.try_it_timeout_seconds:g} seconds. If this app scales to zero "
                "when idle (e.g. Azure Container Apps), the first call after idle can be slower than this — "
                "try Send again."
            ))
        except httpx.HTTPError as exc:
            result.update(ok=False, error=f"Could not reach the endpoint: {type(exc).__name__}: {exc}")
        else:
            result.update(
                ok=resp.is_success, status=resp.status_code, contentType=resp.headers.get("content-type"),
                body=_decode(resp, raw, truncated), truncated=truncated, location=resp.headers.get("location"),
            )
        result["latencyMs"] = round((time.perf_counter() - started) * 1000)

    async with get_db_session() as db:
        # Bodies are left out on purpose: they may carry personal data.
        db.add(_audit(agent_id, actor, "try_it", {
            "url": url, "method": body.method, "status": result.get("status"),
            "ok": result.get("ok"), "error": result.get("error"), "latencyMs": result.get("latencyMs"),
        }))
    return result
