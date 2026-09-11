"""Cobol ContextIntel-style pyvis/vis-network dependency-graph view for the
Agent Registry — a faithful port of cobol_intel/analysis/neo4j_graph_view.py.

Same rendering stack (pyvis → vis-network HTML), same physics (forceAtlas2Based,
springLength 160), same node/edge visual vocabulary, same vendored filter
runtime (services/graph_view_runtime.py) with the ci_kind contract, the
right-click hierarchical entry-point view and the parent postMessage protocol.

Mapping from the Agent Registry model:
  - agents        → circle, fill = department colour, border = lifecycle entry
                    (Production ▶ green / pipeline amber), ci_kind = group:<dept>
  - external      → pale circle (referenced but unregistered agents)
  - system        → database shape (cobol data-file styling)
  - database      → database shape
  - knowledge_base→ box (cobol CICS-map styling)
  - mcp_server    → box (cobol JCL-job styling)
  - consumer      → box (cobol JCL-step styling)

Edges: CALLS solid violet labelled "calls"; ACCESSES dashed amber;
USES_KB dashed green; USES_MCP dashed violet; CONSUMED_BY dashed slate
labelled "feeds".
"""
from __future__ import annotations

import json
from typing import Any

from pyvis.network import Network

from services.graph_service import build_graph
from services.graph_view_runtime import _inject_filter_runtime

# Cobol's palette (raw hex on purpose — serialised into the pyvis document).
_GROUP_PALETTE = ["#6d5efc", "#0891b2", "#c2410c", "#15803d", "#a21caf", "#b91c1c"]
_UNGROUPED_COLOR = "#9ca3af"
_EXTERNAL_FILL = "#f8f7ff"
_EXTERNAL_BORDER = "#e7e4fb"

_KIND_EXTERNAL = "external"

_BASE_SMOOTH = {"enabled": True, "type": "dynamic"}


def _group_kind(group: str) -> str:
    return f"group:{group}"


def build_graph_view_html(graph: dict[str, Any]) -> dict[str, Any]:
    """Render the Agent Registry dependency graph as a cobol-style pyvis HTML view.

    Returns {"html", "node_count", "edge_count", "legend", "entry_point_count"}.
    """
    nodes_src = graph["nodes"]
    edges_src = graph["edges"]

    departments = sorted({n["kind"].removeprefix("group:") for n in nodes_src if n["kind"].startswith("group:")})
    dept_colors = {d: _GROUP_PALETTE[i % len(_GROUP_PALETTE)] for i, d in enumerate(departments)}
    dept_colors["unassigned"] = _UNGROUPED_COLOR

    net = Network(
        height="620px", width="100%", directed=True, bgcolor="#ffffff", font_color="#1f2937"
    )
    net.set_options(
        json.dumps(
            {
                "physics": {
                    "solver": "forceAtlas2Based",
                    "forceAtlas2Based": {"springLength": 160},
                },
                "edges": {
                    "arrows": {"to": {"enabled": True}},
                    "color": {"color": "#a78bfa"},
                    "smooth": _BASE_SMOOTH,
                },
            }
        )
    )

    entry_point_count = 0
    for n in nodes_src:
        kind = n["kind"]
        attrs = n.get("attrs") or {}
        if kind.startswith("group:"):
            is_agent = True
            dept = kind.removeprefix("group:")
            is_production = attrs.get("entry") == "production"
            is_entry = is_production
            border_color = "#17b26a" if is_production else "#d97706"
            prefix = "▶ " if is_production else ""
            entry_flavor = "production" if is_production else "pipeline"
            fill = dept_colors.get(dept, _GROUP_PALETTE[0])
            node_kind = kind
            label = f"{prefix}{n['name']}" if is_entry else n["name"]
            title_parts = [f"Dept: {dept}", f"Stage: {attrs.get('stage', '')}"]
            if attrs.get("model_name"):
                title_parts.append(f"Model: {attrs['model_name']}")
            title_parts.append(f"Value: ${attrs.get('value_amount', 0)}/mo · {attrs.get('hours_saved_monthly', 0)} h/mo")
            if attrs.get("at_risk"):
                title_parts.append("⚠ FLAGGED AT RISK")
            if attrs.get("worst_gate"):
                title_parts.append(f"Governance: {attrs['worst_gate']}")
            if is_entry:
                title_parts.append("right-click for a hierarchical view of what it feeds")
            title = "\n".join(title_parts)
        else:
            is_agent = False
            is_entry = False
            entry_flavor = ""
            label = n["name"]
            if kind == "external":
                node_kind = _KIND_EXTERNAL
                fill = _EXTERNAL_FILL
                border_color = _EXTERNAL_BORDER
                title = "Unregistered agent (referenced but not in the registry)"
            elif kind == "system":
                node_kind = "system"
                fill, border_color = "#dbeafe", "#0891b2"
                title = f"Enterprise system: {n['name']}"
            elif kind == "database":
                node_kind = "database"
                fill, border_color = "#fef3c7", "#c2410c"
                title = f"Database: {n['name']}"
            elif kind == "knowledge_base":
                node_kind = "knowledge_base"
                fill, border_color = "#dcfce7", "#15803d"
                title = f"Knowledge base: {n['name']}"
            elif kind == "mcp_server":
                node_kind = "mcp_server"
                fill, border_color = "#fee2e2", "#a21caf"
                title = f"MCP / tool server: {n['name']}"
            else:  # consumer
                node_kind = "consumer"
                fill, border_color = "#f1f5f9", "#475569"
                title = f"Consumer: {n['name']}"

        net.add_node(
            n["id"],
            label=label,
            ci_kind=node_kind,
            color={
                "background": fill,
                "border": border_color if is_entry else (border_color),
            },
            font={
                "color": "#9ca3af" if kind == _KIND_EXTERNAL else ("#ffffff" if is_agent else "#1f2937"),
                "size": 13 if is_agent else 12,
            },
            title=title,
            borderWidth=5 if is_entry else 2,
            shape="circle" if is_agent else ("database" if kind in ("system", "database") else "box"),
            **({"ci_entry": entry_flavor} if is_entry else {}),
        )
        if is_entry:
            entry_point_count += 1

    for e in edges_src:
        etype = e["type"]
        if etype == "CALLS":
            net.add_edge(e["from"], e["to"], label="calls", title="calls")
        elif etype == "CONSUMED_BY":
            net.add_edge(e["from"], e["to"], label="feeds", color="#475569", dashes=True)
        elif etype == "ACCESSES":
            net.add_edge(e["from"], e["to"], color="#d97706", dashes=True)
        elif etype == "USES_KB":
            net.add_edge(e["from"], e["to"], color="#15803d", dashes=True)
        elif etype == "USES_MCP":
            net.add_edge(e["from"], e["to"], color="#a21caf", dashes=True)

    legend = _build_legend(net.nodes, dept_colors)

    net.write_html("/tmp/agentregistry_graph.html", notebook=False, open_browser=False)
    html = _inject_filter_runtime(open("/tmp/agentregistry_graph.html", encoding="utf-8").read())

    return {
        "html": html,
        "node_count": len(nodes_src),
        "edge_count": len(edges_src),
        "entry_point_count": entry_point_count,
        "group_colors": dept_colors,
        "legend": legend,
    }


def _build_legend(net_nodes: list[dict], dept_colors: dict[str, str]) -> list[dict]:
    """One legend entry per node kind actually present — cobol's contract:
    department groups first, then the supporting node kinds. Counts come from
    the finished node list (pyvis silently drops duplicate ids)."""
    kind_counts: dict[str, int] = {}
    for node in net_nodes:
        kind = node.get("ci_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    entries: list[dict] = []

    for dept in sorted(dept_colors):
        kind = _group_kind(dept)
        if kind in kind_counts and dept != "unassigned":
            entries.append(
                {"key": kind, "label": dept.replace("dept-", "").replace("-", " ").title(), "color": dept_colors[dept], "border": dept_colors[dept], "shape": "circle"}
            )

    for kind, label, color, border, shape in (
        (_KIND_EXTERNAL, "Unregistered (Shadow AI)", _EXTERNAL_FILL, "#c7c2e8", "circle"),
        ("system", "Enterprise Systems", "#dbeafe", "#0891b2", "database"),
        ("database", "Databases", "#fef3c7", "#c2410c", "database"),
        ("knowledge_base", "Knowledge Bases", "#dcfce7", "#15803d", "box"),
        ("mcp_server", "MCP Servers", "#fee2e2", "#a21caf", "box"),
        ("consumer", "Consumers", "#f1f5f9", "#475569", "box"),
    ):
        if kind in kind_counts:
            entries.append(
                {"key": kind, "label": label, "color": color, "border": border, "shape": shape}
            )

    for entry in entries:
        entry["count"] = kind_counts[entry["key"]]
    return entries
