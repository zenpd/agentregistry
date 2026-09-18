"""Agent page — Diagram tab API: trace-reconstructed graph, declared vs
observed dependencies, blast radius, and human-confirmed adoption."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_read, require_update
from api.routers.registry import _resolve_phoenix_endpoint
from db.base import get_db_session
from db.models import Agent, AuditLog
from discovery import observed_deps
from discovery.graph_cache import graph_cache
from discovery.phoenix_client import PhoenixClient, PhoenixError
from discovery.reconstruct import reconstruct
from services.graph_service import affected_subgraph, build_adjacency

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Diagram"])

SAMPLE_SPAN_LIMIT = 1000
# A cold VPN connection to Phoenix has taken ~30 s for the first page; the result is cached.
SAMPLE_TIMEOUT_SECONDS = 45.0
# Below this many traces, "declared but not seen" may just be a path that has not run yet.
MIN_TRACES_FOR_ABSENCE = 50

_GRAPH_KEYS = ("status", "project", "reason", "spanCount", "traceCount", "nodes", "edges",
               "cachedAt", "fromCache", "sampleWindow", "sampleLimit", "truncated", "orphanRate")


def _empty_sample(status: str, project: str | None, reason: str | None = None) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "status": status, "project": project, "spanCount": 0, "traceCount": 0,
        "nodes": [], "edges": [], "observed": None, "cachedAt": None, "fromCache": False,
        "sampleWindow": None, "sampleLimit": SAMPLE_SPAN_LIMIT, "truncated": False, "orphanRate": None,
    }
    if reason:
        sample["reason"] = reason
    return sample


async def _load_agent(agent_id: str) -> tuple[Agent, str | None, str | None]:
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        base_url, api_key = (None, None)
        if agent.phoenix_project:
            base_url, api_key = await _resolve_phoenix_endpoint(db, agent=agent)
        return agent, base_url, api_key


async def _project_missing(client: PhoenixClient, project: str) -> bool:
    """A 404 on spans means "no such project" only if Phoenix itself answers
    and does not list it; Phoenix creates a project on its first exported trace."""
    try:
        return project not in await client.projects()
    except (PhoenixError, ValueError):
        return False


async def _fetch_sample(project: str, base_url: str, api_key: str | None) -> dict[str, Any]:
    try:
        async with PhoenixClient(base_url, api_key=api_key, timeout=SAMPLE_TIMEOUT_SECONDS) as client:
            try:
                spans = [span async for span in client.spans(project, limit=SAMPLE_SPAN_LIMIT, max_pages=1)]
            except PhoenixError as exc:
                if exc.status == 404 and await _project_missing(client, project):
                    return _empty_sample("no_traces_yet", project,
                                         f"Phoenix has no project named '{project}' yet; it appears with the first exported trace")
                raise
    except PhoenixError as exc:
        return _empty_sample("phoenix_unreachable", project, str(exc))
    except ValueError:
        return _empty_sample("phoenix_unreachable", project, "Phoenix returned a response that is not JSON")
    graph = reconstruct(spans)
    stats = observed_deps.sample_stats(spans)
    return {
        **graph,
        "status": "ok" if graph["spanCount"] else "no_traces_yet",
        "project": project,
        "observed": observed_deps.observed_from_spans(spans),
        "sampleWindow": {"from": stats["from"], "to": stats["to"]},
        "sampleLimit": SAMPLE_SPAN_LIMIT,
        "truncated": len(spans) >= SAMPLE_SPAN_LIMIT,
        "orphanRate": stats["orphanRate"],
    }


async def _sample(agent: Agent, base_url: str | None, api_key: str | None, refresh: bool) -> dict[str, Any]:
    """The cached span sample for an agent. Only reachable results are cached,
    so Retry after an outage always goes back to Phoenix."""
    project = agent.phoenix_project
    if not project:
        return _empty_sample("not_linked", None)
    if not base_url:
        return _empty_sample("phoenix_unreachable", project, "No Phoenix endpoint configured")

    key = graph_cache.key(agent.id, project, base_url)
    if not refresh and (cached := graph_cache.get(key)):
        return {**cached, "fromCache": True}
    async with graph_cache.lock(key):
        if not refresh and (cached := graph_cache.get(key)):
            return {**cached, "fromCache": True}
        sample = await _fetch_sample(project, base_url, api_key)
        if sample["status"] == "phoenix_unreachable":
            return sample
        return {**graph_cache.set(key, sample), "fromCache": False}


@router.get("/agents/{agent_id}/reconstructed-graph")
async def reconstructed_graph(agent_id: str, refresh: bool = False, _=Depends(require_read)):
    agent, base_url, api_key = await _load_agent(agent_id)
    sample = await _sample(agent, base_url, api_key, refresh)
    return {k: sample[k] for k in _GRAPH_KEYS if k in sample}


def _declared(agent: Agent) -> dict[str, Any]:
    return {
        "enterpriseSystems": list(agent.enterprise_systems or []),
        "databases": list(agent.databases or []),
        "knowledgeBases": list(agent.knowledge_bases or []),
        "mcpServers": list(agent.mcp_servers or []),
        "calls": list(agent.calls or []),
        "consumers": list(agent.consumers or []),
        "modelName": agent.model_name,
    }


@router.get("/agents/{agent_id}/dependencies")
async def dependencies(agent_id: str, refresh: bool = False, _=Depends(require_read)):
    agent, base_url, api_key = await _load_agent(agent_id)
    sample = await _sample(agent, base_url, api_key, refresh)

    async with get_db_session() as db:
        adj = await build_adjacency(db)
    impact = affected_subgraph(adj, agent.id)

    comparison = None
    if sample["status"] == "ok":
        comparison = observed_deps.compare(
            {
                "enterprise_systems": agent.enterprise_systems,
                "databases": agent.databases,
                "knowledge_bases": agent.knowledge_bases,
                "mcp_servers": agent.mcp_servers,
                "calls": [adj["node_names"].get(ref, ref) for ref in agent.calls or []],
                "model_name": agent.model_name,
            },
            sample["observed"],
        )
        comparison["absenceConclusive"] = sample["traceCount"] >= MIN_TRACES_FOR_ABSENCE
        comparison["minTracesForAbsence"] = MIN_TRACES_FOR_ABSENCE

    return {
        "status": sample["status"],
        "project": sample["project"],
        "reason": sample.get("reason"),
        "cachedAt": sample["cachedAt"],
        "fromCache": sample["fromCache"],
        "sampleWindow": sample["sampleWindow"],
        "spanCount": sample["spanCount"],
        "traceCount": sample["traceCount"],
        "declared": _declared(agent),
        "observed": sample["observed"] if sample["status"] == "ok" else None,
        "comparison": comparison,
        "blastRadius": observed_deps.blast_radius_view(adj, agent.id, impact),
        "upstream": observed_deps.upstream_view(adj, agent.id),
        "sharedResources": observed_deps.shared_resources(adj, agent.id),
    }


class AdoptItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., min_length=1, max_length=32)


class AdoptRequest(BaseModel):
    items: list[AdoptItem] = Field(..., min_length=1, max_length=100)


@router.post("/agents/{agent_id}/dependencies/adopt")
async def adopt_dependencies(agent_id: str, body: AdoptRequest, user=Depends(require_update)):
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        current = {field: getattr(agent, field) for field in set(observed_deps.ADOPT_FIELD.values())}
        try:
            plan = observed_deps.adopt_items(current, [item.model_dump() for item in body.items])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        for field, values in plan["fields"].items():
            setattr(agent, field, values)
        if plan["added"]:
            db.add(AuditLog(
                org_id="org-default",
                actor=user.get("user_id", "unknown"),
                action="adopt_observed_dependencies",
                entity_type="agent",
                entity_id=agent_id,
                changes={"added": plan["added"], "skipped": plan["skipped"], "source": "phoenix_traces"},
            ))
        declared = _declared(agent)

    graph_cache.invalidate(agent_id)
    return {
        "status": "updated" if plan["added"] else "unchanged",
        "added": plan["added"],
        "skipped": plan["skipped"],
        "declared": declared,
    }
