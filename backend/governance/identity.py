"""Which registered agent a discovered project probably is, who probably owns
it, and what is odd about the project. Pure functions over plain dicts.

Match keys, strongest first:
- high:   the project's service name is the agent's slug or name, or the
          agent's API address contains the project name;
- medium: the names are alike (at least 60% of their words in common);
- low:    same model and at least two tools in common.
A match is a suggestion. Nothing is merged until a person presses Merge."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_SPLIT = re.compile(r"[^a-z0-9]+")
_EVAL_PROJECT = re.compile(r"^experiment[-_][0-9a-f]{6,}$", re.I)
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def words(text: str | None) -> set[str]:
    return {w for w in _SPLIT.split((text or "").lower()) if w and w not in {"agent", "the", "test", "app", "be", "fe"}}


def norm(text: str | None) -> str:
    return "-".join(w for w in _SPLIT.split((text or "").lower()) if w)


def similarity(a: str | None, b: str | None) -> float:
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def is_evaluation_project(name: str) -> bool:
    """Projects a testing tool creates for its experiment runs (Experiment-<hex>): evaluation traffic, not an agent."""
    return bool(_EVAL_PROJECT.match(name or ""))


def hygiene(project: dict) -> list[dict]:
    """What is odd about a project, each {code, text}."""
    out = []
    name = project.get("name") or ""
    if name.strip().lower() == "default":
        out.append({"code": "default_project",
                    "text": "Spans land in the project named default, so several apps may be mixed here. Each app should set its own project name."})
    services = project.get("serviceNames") or []
    if len(services) > 1:
        out.append({"code": "several_services",
                    "text": f"{len(services)} services send to this project ({', '.join(services[:3])}), so it may hold more than one agent."})
    spans, errors = project.get("spanCount") or 0, project.get("errorCount") or 0
    if spans >= 20 and errors / spans >= 0.10:
        out.append({"code": "high_errors", "text": f"{errors} of the last {spans} spans ended in an error."})
    return out


def matches(project: dict, agents: list[dict], limit: int = 3) -> list[dict]:
    """Registered agents this project may be, best first: {agentId, name, owner, confidence, reason}."""
    name = project.get("name") or ""
    services = [norm(s) for s in project.get("serviceNames") or []]
    found: dict[str, dict] = {}

    def add(agent: dict, confidence: str, reason: str) -> None:
        current = found.get(agent["id"])
        if current is None or CONFIDENCE_ORDER[confidence] < CONFIDENCE_ORDER[current["confidence"]]:
            found[agent["id"]] = {"agentId": agent["id"], "name": agent["name"], "owner": agent.get("owner"),
                                  "linkedProject": agent.get("phoenixProject"), "confidence": confidence, "reason": reason}

    for a in agents:
        slug, aname = norm(a.get("slug") or a["id"]), norm(a["name"])
        host = (urlparse(a.get("apiEndpoint") or "").hostname or "").lower()
        if services and (slug in services or aname in services):
            add(a, "high", f"The project's service name is {a['name']}'s name.")
        elif host and norm(name) and f"-{norm(name)}-" in f"-{norm(host)}-":
            add(a, "high", f"{a['name']}'s API address ({host}) contains the project name.")
        sim = similarity(name, a["name"])
        if sim >= 0.6:
            add(a, "medium", f"The names are alike ({round(sim * 100)}% of their words in common).")
        models, tools = set(project.get("models") or []), set(project.get("tools") or [])
        shared_tools = tools & set(a.get("mcpServers") or [])
        if a.get("modelName") and a["modelName"] in models and len(shared_tools) >= 2:
            add(a, "low", f"Same model ({a['modelName']}) and {len(shared_tools)} tools in common.")
    return sorted(found.values(), key=lambda m: (CONFIDENCE_ORDER[m["confidence"]], m["name"]))[:limit]


def owner_guess(project: dict, best_match: dict | None) -> dict | None:
    """{value, confidence, reason}: from the agent.owner attribute on the spans
    first, then the owner of the best matching record."""
    hinted = (project.get("hints") or {}).get("agent.owner")
    if hinted:
        return {"value": hinted, "confidence": "high", "reason": "The spans carry agent.owner."}
    if best_match and best_match.get("owner") and best_match["owner"] != "Unassigned":
        return {"value": best_match["owner"], "confidence": "medium" if best_match["confidence"] == "high" else "low",
                "reason": f"Owner of the matching record {best_match['name']}."}
    return None
