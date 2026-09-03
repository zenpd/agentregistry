"""Impact Analysis Orchestration — dependency graph analysis and outage simulation.

Builds a dependency graph from agent data and calculates blast radius for outages.
"""
from sqlalchemy import select
from collections import deque
from db.base import get_db_session
from db.models import Agent


async def run_impact_analysis(node_id: str, node_type: str = "agent") -> dict:
    """Run impact analysis for a target node."""
    async with get_db_session() as db:
        # Get target node
        if node_type == "agent":
            result = await db.execute(select(Agent).where(Agent.id == node_id))
            target = result.scalar_one_or_none()
            if not target:
                return {"status": "error", "message": "Agent not found"}
            target_name = target.name
            target_value = target.value_amount
            target_hours = target.hours_saved_monthly
        else:
            # System/database node
            target_name = node_id
            target_value = 0
            target_hours = 0

        # Find all agents
        result = await db.execute(select(Agent))
        all_agents = result.scalars().all()

        # Build adjacency list
        graph = {}
        agent_map = {}
        for agent in all_agents:
            agent_map[agent.id] = agent
            graph[agent.id] = {
                "calls": agent.calls or [],
                "consumers": agent.consumers or [],
                "enterprise_systems": agent.enterprise_systems or [],
                "databases": agent.databases or [],
            }

        # Find direct and transitive dependencies
        direct_deps = []
        transitive_deps = []
        affected_agents = []
        revenue_at_risk = 0
        efficiency_at_risk = 0
        blast_radius_depts = set()

        # Find agents that depend on this node
        for agent_id, deps in graph.items():
            is_dependent = False
            if node_type == "agent":
                if node_id in deps["calls"] or node_id in deps["enterprise_systems"] or node_id in deps["databases"]:
                    is_dependent = True
            else:
                if node_id in deps["enterprise_systems"] or node_id in deps["databases"]:
                    is_dependent = True

            if is_dependent:
                agent = agent_map[agent_id]
                direct_deps.append(agent_id)
                affected_agents.append({
                    "id": agent.id,
                    "name": agent.name,
                    "dept": agent.dept_id,
                    "value": agent.value_amount,
                })
                revenue_at_risk += agent.value_amount
                efficiency_at_risk += agent.hours_saved_monthly
                if agent.dept_id:
                    blast_radius_depts.add(agent.dept_id)

        # BFS for transitive dependencies
        visited = set(direct_deps)
        queue = deque(direct_deps)
        while queue:
            current = queue.popleft()
            for agent_id, deps in graph.items():
                if agent_id not in visited and current in deps["calls"]:
                    visited.add(agent_id)
                    transitive_deps.append(agent_id)
                    queue.append(agent_id)
                    agent = agent_map[agent_id]
                    affected_agents.append({
                        "id": agent.id,
                        "name": agent.name,
                        "dept": agent.dept_id,
                        "value": agent.value_amount,
                    })
                    revenue_at_risk += agent.value_amount
                    efficiency_at_risk += agent.hours_saved_monthly
                    if agent.dept_id:
                        blast_radius_depts.add(agent.dept_id)

        # Determine risk level
        if revenue_at_risk > 500000:
            risk_level = "critical"
        elif revenue_at_risk > 200000:
            risk_level = "high"
        elif revenue_at_risk > 50000:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Generate mitigation suggestions
        mitigation_suggestions = []
        if direct_deps:
            mitigation_suggestions.append(f"Add circuit breaker for {len(direct_deps)} direct dependencies")
        if transitive_deps:
            mitigation_suggestions.append(f"Review {len(transitive_deps)} transitive dependencies")
        if revenue_at_risk > 100000:
            mitigation_suggestions.append("Implement failover for high-value agents")
        if len(blast_radius_depts) > 2:
            mitigation_suggestions.append(f"Cross-departmental impact: {', '.join(blast_radius_depts)}")

        return {
            "status": "completed",
            "target_node_id": node_id,
            "target_node_type": node_type,
            "target_name": target_name,
            "direct_dependencies": len(direct_deps),
            "transitive_dependencies": len(transitive_deps),
            "affected_agents": len(affected_agents),
            "revenue_at_risk": revenue_at_risk,
            "efficiency_at_risk": efficiency_at_risk,
            "blast_radius_depts": list(blast_radius_depts),
            "risk_level": risk_level,
            "mitigation_suggestions": mitigation_suggestions,
        }
