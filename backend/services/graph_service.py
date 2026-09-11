"""Shared dependency-graph builder for the Agent Registry.

Every graph surface (graph API v2, impact analysis, concentration risk) reads
from this one builder so nodes, kinds, edges and metadata can never disagree —
the same rule cobol_contextintel enforces with its single neo4j_graph_view
builder.

Node kinds are mutually exclusive (mirrors cobol's `ci_kind` contract):
  - group:<dept_id>   agents, one kind per department
  - system            enterprise systems
  - database          databases
  - knowledge_base    knowledge bases
  - mcp_server        MCP / tool servers
  - consumer          downstream dashboards, queues, channels, portals
  - external          referenced but unregistered agents (shadow-AI candidates)

Entry-point-ness is deliberately NOT a kind — it rides along as
``attrs["entry"]`` ("production" | "pipeline") so hiding a lifecycle stage can
never be confused with hiding a node family.

Edges are typed: CALLS, CONSUMED_BY, ACCESSES, USES_KB, USES_MCP.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent, GovernanceReview, AgentTokenUsage

# Raw hex on purpose: these colours are serialised straight into the graph
# payload consumed by the canvas (the cobol exemption from CSS variables).
_GROUP_PALETTE = [
    "#6d5efc", "#0891b2", "#c2410c", "#15803d", "#a21caf",
    "#b91c1c", "#0f766e", "#b45309", "#4d7c0f", "#7c3aed",
]
_UNGROUPED_COLOR = "#9ca3af"
_KIND_COLORS = {
    "system": "#0891b2",
    "database": "#c2410c",
    "knowledge_base": "#15803d",
    "mcp_server": "#a21caf",
    "consumer": "#475569",
    "external": "#9ca3af",
}
_ENTRY_COLORS = {"production": "#17b26a", "pipeline": "#d97706"}

_GATE_SEVERITY = {
    "Changes Requested": 4,
    "Not Submitted": 3,
    "In Review": 2,
    "Approved with Conditions": 1,
    "Approved": 0,
}


def _node_id(prefix: str, name: str) -> str:
    return f"{prefix}:{name}"


async def load_agents(db: AsyncSession, org_id: str | None = None) -> list[Agent]:
    query = select(Agent)
    if org_id:
        query = query.where(Agent.org_id == org_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _worst_gate_map(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(GovernanceReview.agent_id, GovernanceReview.status))
    worst: dict[str, str] = {}
    for agent_id, status in result.all():
        current = worst.get(agent_id)
        if current is None or _GATE_SEVERITY.get(status, 0) > _GATE_SEVERITY.get(current, 0):
            worst[agent_id] = status
    return worst


async def _token_cost_map(db: AsyncSession) -> dict[str, float]:
    from sqlalchemy import func

    result = await db.execute(
        select(AgentTokenUsage.agent_id, func.sum(AgentTokenUsage.cost_cents))
        .group_by(AgentTokenUsage.agent_id)
    )
    return {agent_id: (cents or 0) / 100 for agent_id, cents in result.all()}


async def build_graph(db: AsyncSession, org_id: str | None = None) -> dict[str, Any]:
    """Build the full dependency graph: nodes, typed edges, legend and stats."""
    agents = await load_agents(db, org_id)
    gates = await _worst_gate_map(db)
    token_cost = await _token_cost_map(db)

    dept_order: list[str] = []
    for agent in agents:
        dept = agent.dept_id or "unassigned"
        if dept not in dept_order:
            dept_order.append(dept)

    def dept_color(dept: str) -> str:
        if dept not in dept_order:
            return _UNGROUPED_COLOR
        return _GROUP_PALETTE[dept_order.index(dept) % len(_GROUP_PALETTE)]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    agent_ids = {a.id for a in agents}

    def add_node(node: dict[str, Any]) -> None:
        if node["id"] not in seen:
            nodes.append(node)
            seen.add(node["id"])

    def add_edge(src: str, dst: str, etype: str) -> None:
        edges.append({"from": src, "to": dst, "type": etype})

    for agent in agents:
        dept = agent.dept_id or "unassigned"
        stage = agent.lifecycle_stage or "Ideation"
        add_node({
            "id": agent.id,
            "name": agent.name,
            "kind": f"group:{dept}",
            "attrs": {
                "dept": dept,
                "stage": stage,
                "entry": "production" if stage == "Production" else "pipeline",
                "model_name": agent.model_name,
                "value_amount": agent.value_amount or 0,
                "hours_saved_monthly": agent.hours_saved_monthly or 0,
                "token_cost": round(token_cost.get(agent.id, 0.0), 2),
                "at_risk": bool(agent.at_risk),
                "risk_level": agent.risk_level,
                "worst_gate": gates.get(agent.id),
            },
        })

    def ensure_ref_node(ref: str) -> str | None:
        """Map a free-text reference to a registered agent node, else an external node."""
        if ref in agent_ids:
            return ref
        ext_id = _node_id("ext", ref)
        add_node({"id": ext_id, "name": ref, "kind": "external", "attrs": {"ref": ref}})
        return ext_id

    for agent in agents:
        for callee in agent.calls or []:
            dst = ensure_ref_node(callee)
            if dst and dst != agent.id:
                add_edge(agent.id, dst, "CALLS")
        for system in agent.enterprise_systems or []:
            nid = _node_id("sys", system)
            add_node({"id": nid, "name": system, "kind": "system", "attrs": {}})
            add_edge(agent.id, nid, "ACCESSES")
        for database in agent.databases or []:
            nid = _node_id("db", database)
            add_node({"id": nid, "name": database, "kind": "database", "attrs": {}})
            add_edge(agent.id, nid, "ACCESSES")
        for kb in agent.knowledge_bases or []:
            nid = _node_id("kb", kb)
            add_node({"id": nid, "name": kb, "kind": "knowledge_base", "attrs": {}})
            add_edge(agent.id, nid, "USES_KB")
        for mcp in agent.mcp_servers or []:
            nid = _node_id("mcp", mcp)
            add_node({"id": nid, "name": mcp, "kind": "mcp_server", "attrs": {}})
            add_edge(agent.id, nid, "USES_MCP")
        for consumer in agent.consumers or []:
            nid = _node_id("consumer", consumer)
            add_node({"id": nid, "name": consumer, "kind": "consumer", "attrs": {}})
            add_edge(agent.id, nid, "CONSUMED_BY")

    legend = _build_legend(nodes, dept_color)
    stats = _build_stats(nodes, edges, agents)
    return {"nodes": nodes, "edges": edges, "legend": legend, "stats": stats}


def _build_legend(nodes: list[dict[str, Any]], dept_color) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1

    def color_of(kind: str) -> str:
        if kind.startswith("group:"):
            return dept_color(kind.removeprefix("group:"))
        return _KIND_COLORS.get(kind, _UNGROUPED_COLOR)

    def label_of(kind: str) -> str:
        if kind.startswith("group:"):
            return kind.removeprefix("group:").replace("dept-", "").replace("-", " ").title()
        return {
            "system": "Enterprise Systems",
            "database": "Databases",
            "knowledge_base": "Knowledge Bases",
            "mcp_server": "MCP Servers",
            "consumer": "Consumers",
            "external": "Unregistered (Shadow AI)",
        }.get(kind, kind)

    order = {"external": 98}
    builtins = ["system", "database", "knowledge_base", "mcp_server", "consumer", "external"]
    groups = sorted(k for k in counts if k.startswith("group:"))
    builtins_sorted = sorted(
        (k for k in counts if not k.startswith("group:")),
        key=lambda k: order.get(k, builtins.index(k) if k in builtins else 50),
    )
    result = []
    for kind in groups + builtins_sorted:
        result.append({"kind": kind, "label": label_of(kind), "count": counts[kind], "color": color_of(kind)})
    return result


def _build_stats(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], agents: list[Agent]) -> dict[str, Any]:
    agent_nodes = [n for n in nodes if n["kind"].startswith("group:")]
    agent_ids = {n["id"] for n in agent_nodes}
    cross_agent = [e for e in edges if e["type"] == "CALLS"]
    cross_dept = 0
    dept_by_id = {a.id: (a.dept_id or "unassigned") for a in agents}
    for e in cross_agent:
        src_dept = dept_by_id.get(e["from"])
        dst_node = next((n for n in nodes if n["id"] == e["to"]), None)
        dst_dept = dst_node["attrs"].get("dept") if dst_node else None
        if src_dept and dst_dept and src_dept != dst_dept:
            cross_dept += 1
    connected = {e["from"] for e in edges} | {e["to"] for e in edges}
    orphans = [n["id"] for n in agent_nodes if n["id"] not in connected]
    return {
        "agents": len(agents),
        "nodes": len(nodes),
        "edges": len(edges),
        "cross_agent_edges": len(cross_agent),
        "cross_dept_edges": cross_dept,
        "orphan_agents": len(orphans),
        "orphan_agent_ids": orphans,
        "production_agents": sum(1 for n in agent_nodes if n["attrs"].get("entry") == "production"),
    }


# ── Adjacency views for impact / blast-radius analysis ───────────────────────

def _empty_adjacency() -> dict[str, Any]:
    return {
        "callers_of": {},      # agent_id -> [agent_ids that CALL it]
        "calls_by": {},        # agent_id -> [agent_ids it calls]
        "consumers_of": {},    # agent_id -> [consumer_node_ids]
        "accessors_of": {},    # sys/db node_id -> [agent_ids]
        "agent_attrs": {},     # agent_id -> attrs
        "agent_kinds": {},     # agent_id -> kind
        "node_names": {},      # node_id -> name
        "edge_ids": {},        # (from, to, type) -> edge index key
    }


async def build_adjacency(db: AsyncSession, org_id: str | None = None) -> dict[str, Any]:
    graph = await build_graph(db, org_id)
    adj = _empty_adjacency()
    for node in graph["nodes"]:
        adj["node_names"][node["id"]] = node["name"]
        if node["kind"].startswith("group:"):
            adj["agent_attrs"][node["id"]] = node["attrs"]
            adj["agent_kinds"][node["id"]] = node["kind"]
            adj["callers_of"].setdefault(node["id"], [])
            adj["calls_by"].setdefault(node["id"], [])
            adj["consumers_of"].setdefault(node["id"], [])
            adj["accessors_of"].setdefault(node["id"], [])
        if node["kind"] in ("system", "database"):
            adj["accessors_of"].setdefault(node["id"], [])
    for i, e in enumerate(graph["edges"]):
        key = f"{e['from']}|{e['to']}|{e['type']}"
        adj["edge_ids"][key] = i
        if e["type"] == "CALLS":
            adj["calls_by"].setdefault(e["from"], []).append(e["to"])
            if e["to"] not in adj["agent_kinds"]:
                continue  # CALLS to an external node: no upstream walk
            adj["callers_of"].setdefault(e["to"], []).append(e["from"])
        elif e["type"] == "CONSUMED_BY":
            adj["consumers_of"].setdefault(e["from"], []).append(e["to"])
        elif e["type"] == "ACCESSES" and e["to"] in adj["accessors_of"]:
            adj["accessors_of"][e["to"]].append(e["from"])
    adj["nodes"] = graph["nodes"]
    adj["edges"] = graph["edges"]
    adj["legend"] = graph["legend"]
    adj["stats"] = graph["stats"]
    return adj


def affected_subgraph(adj: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Blast radius for an outage at ``node_id``.

    Walks *upstream* through CALLS (an agent that calls a dead agent is
    affected) and collects consumers of every affected agent (they lose the
    service). Returns node ids + edge keys so the UI can highlight exactly the
    affected subgraph — cobol's "out-edges only, BFS, first visit wins"
    discipline, pointed the direction an outage actually travels.
    """
    affected_agents: list[str] = []
    affected_nodes: set[str] = set()
    affected_edges: set[str] = set()
    blast_depts: set[str] = set()

    if node_id in adj["agent_kinds"]:
        roots = [node_id]
    else:
        roots = list(adj["accessors_of"].get(node_id, []))
        affected_nodes.add(node_id)

    visited: set[str] = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current not in adj["agent_kinds"]:
            continue
        affected_agents.append(current)
        affected_nodes.add(current)
        attrs = adj["agent_attrs"].get(current) or {}
        if attrs.get("dept"):
            blast_depts.add(attrs["dept"])
        for caller in adj["callers_of"].get(current, []):
            key = f"{caller}|{current}|CALLS"
            if caller not in visited:
                affected_edges.add(key)
                queue.append(caller)
        for consumer in adj["consumers_of"].get(current, []):
            key = f"{current}|{consumer}|CONSUMED_BY"
            affected_edges.add(key)
            affected_nodes.add(consumer)

    revenue_at_risk = sum((adj["agent_attrs"].get(a) or {}).get("value_amount", 0) for a in affected_agents)
    hours_at_risk = sum((adj["agent_attrs"].get(a) or {}).get("hours_saved_monthly", 0) for a in affected_agents)
    if revenue_at_risk > 500000:
        risk_level = "critical"
    elif revenue_at_risk > 200000:
        risk_level = "high"
    elif revenue_at_risk > 50000:
        risk_level = "medium"
    else:
        risk_level = "low"

    mitigation: list[str] = []
    direct_callers = sum(1 for a in affected_agents for c in adj["callers_of"].get(a, []) if c not in affected_agents)
    if direct_callers:
        mitigation.append(f"Add circuit breakers on {direct_callers} upstream caller(s)")
    if len(affected_agents) > 1:
        mitigation.append(f"Review {len(affected_agents) - 1} transitively affected agent(s)")
    if revenue_at_risk > 100000:
        mitigation.append("Implement failover / redundancy for high-value dependencies")
    if len(blast_depts) > 2:
        mitigation.append(f"Cross-departmental impact: {', '.join(sorted(blast_depts))}")

    return {
        "affected_agents": affected_agents,
        "affected_node_ids": sorted(affected_nodes),
        "affected_edge_keys": sorted(affected_edges),
        "revenue_at_risk": revenue_at_risk,
        "hours_at_risk": hours_at_risk,
        "blast_depts": sorted(blast_depts),
        "risk_level": risk_level,
        "mitigation_suggestions": mitigation,
    }
