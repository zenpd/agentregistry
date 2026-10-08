"""Risk class from tools: the approved list gives each tool, system, database or
knowledge base a class (LOW, MEDIUM, HIGH). An agent's tool class is the highest
class among the tools it declares. Tools not on the list are named, never guessed.
Pure functions over plain data."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

LEVELS = ("LOW", "MEDIUM", "HIGH")
KINDS = {"mcp_servers": "mcp", "enterprise_systems": "system", "databases": "database", "knowledge_bases": "knowledge_base"}
KIND_LABELS = {"mcp": "MCP server or tool", "system": "Enterprise system", "database": "Database", "knowledge_base": "Knowledge base"}


def key(name: str) -> str:
    return " ".join(str(name).split()).lower()


def declared(agent: Mapping[str, Any]) -> list[dict]:
    """[{name, kind}] for every tool the record declares, without repeats."""
    out, seen = [], set()
    for field, kind in KINDS.items():
        for name in agent.get(field) or []:
            if str(name).strip() and key(name) not in seen:
                seen.add(key(name))
                out.append({"name": str(name).strip(), "kind": kind})
    return out


def tool_class(agent: Mapping[str, Any], approved: Iterable[Mapping[str, Any]]) -> dict:
    """{class, source, tools: [{name, kind, class|None}], unlisted: [names], listEmpty}.
    class is None when none of the declared tools is on the list."""
    by_key = {key(t["name"]): t for t in approved}
    tools = []
    for t in declared(agent):
        hit = by_key.get(key(t["name"]))
        tools.append({**t, "class": hit["risk_class"] if hit else None, "approvedName": hit["name"] if hit else None})
    classed = [t for t in tools if t["class"] in LEVELS]
    top = max(classed, key=lambda t: LEVELS.index(t["class"])) if classed else None
    return {
        "class": top["class"] if top else None,
        "source": ", ".join(t["name"] for t in classed if t["class"] == top["class"]) if top else None,
        "tools": tools,
        "unlisted": [t["name"] for t in tools if t["class"] is None],
        "listEmpty": not by_key,
    }


def candidates(agents: Iterable[Mapping[str, Any]], approved: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Declared tools not yet on the list, with how many agents declare each: the
    list an admin starts from."""
    listed = {key(t["name"]) for t in approved}
    found: dict[str, dict] = {}
    for a in agents:
        for t in declared(a):
            if key(t["name"]) in listed:
                continue
            row = found.setdefault(key(t["name"]), {"name": t["name"], "kind": t["kind"], "agents": []})
            row["agents"].append(a.get("name") or a.get("id"))
    return sorted(found.values(), key=lambda r: (-len(r["agents"]), r["name"].lower()))
