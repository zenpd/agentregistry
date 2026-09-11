"""Impact Analysis Orchestration — dependency graph analysis and outage simulation.

Delegates graph construction to the shared builder (services/graph_service.py)
and computes the blast radius for an outage at a node. Returns node/edge keys
so the UI can highlight the affected subgraph directly.
"""
from db.base import get_db_session
from services.graph_service import build_adjacency, affected_subgraph


async def run_impact_analysis(node_id: str, node_type: str = "agent") -> dict:
    """Run impact analysis for a target node (agent, system or database)."""
    async with get_db_session() as db:
        adj = await build_adjacency(db)

        if node_type == "agent" and node_id not in adj["agent_kinds"]:
            return {"status": "error", "message": "Agent not found"}

        result = affected_subgraph(adj, node_id)
        target_name = adj["node_names"].get(node_id, node_id)
        agent_attrs = adj["agent_attrs"].get(node_id) or {}

        return {
            "status": "completed",
            "target_node_id": node_id,
            "target_node_type": node_type,
            "target_name": target_name,
            "target_value_amount": agent_attrs.get("value_amount", 0),
            "direct_dependencies": len([
                c for c in adj["callers_of"].get(node_id, [])
            ]) if node_type == "agent" else len(adj["accessors_of"].get(node_id, [])),
            "affected_agents": len(result["affected_agents"]),
            "affected_node_ids": result["affected_node_ids"],
            "affected_edge_keys": result["affected_edge_keys"],
            "revenue_at_risk": result["revenue_at_risk"],
            "efficiency_at_risk": result["hours_at_risk"],
            "blast_radius_depts": result["blast_depts"],
            "risk_level": result["risk_level"],
            "mitigation_suggestions": result["mitigation_suggestions"],
        }
