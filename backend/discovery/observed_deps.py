"""Observed dependencies from Phoenix spans, compared with what the owner declared.

Pure functions over plain dicts. Span reading is limited to the span name,
kind, ids, timestamps and the attribute keys in ``_ALLOWED_ATTRS`` — prompt,
output and message attributes are never read.
"""

from __future__ import annotations

import json
import re
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

_ALLOWED_ATTRS = frozenset({
    "openinference.span.kind",
    "gen_ai.operation.name",
    "tool.name",
    "gen_ai.tool.name",
    "mcp.server",
    "mcp.tool",
    "llm.model_name",
    "gen_ai.response.model",
    "gen_ai.request.model",
    "embedding.model_name",
    "embedding.invocation_parameters",
    "agent.name",
    "gen_ai.agent.name",
})

_GEN_AI_OPERATION_KIND = {
    "execute_tool": "TOOL",
    "chat": "LLM",
    "text_completion": "LLM",
    "generate_content": "LLM",
    "embeddings": "EMBEDDING",
    "retrieval": "RETRIEVER",
    "invoke_agent": "AGENT",
}

# LangGraph emits these as AGENT/CHAIN spans; they are routing plumbing, not agents.
_FRAMEWORK_AGENT_NAMES = frozenset({"next_agent", "langgraph", "__start__", "__end__"})
# LangGraph/OTel internal node-naming conventions: a leading underscore
# (_entry_route) or dunder wrapping (__start__) — routing/bookkeeping, never
# a name a team would give their own business step.
_PLUMBING_PATTERN = re.compile(r"^_.+|^__.+__$")

OBSERVED_KEYS = ("tools", "mcp_servers", "retrievers", "models", "agents", "embeddings")
OBSERVED_KIND = {
    "tools": "tool",
    "mcp_servers": "mcp_server",
    "retrievers": "retriever",
    "models": "model",
    "agents": "agent",
    "embeddings": "embedding",
}

DECLARED_KEYS = ("enterprise_systems", "databases", "knowledge_bases", "mcp_servers", "calls", "model_name")
DECLARED_KIND = {
    "enterprise_systems": "system",
    "databases": "database",
    "knowledge_bases": "knowledge_base",
    "mcp_servers": "mcp_server",
    "calls": "agent",
    "model_name": "model",
}

_RESOURCE_OBSERVED = ("tools", "mcp_servers", "retrievers")
_COMPATIBLE_OBSERVED = {
    "system": _RESOURCE_OBSERVED,
    "database": _RESOURCE_OBSERVED,
    "knowledge_base": _RESOURCE_OBSERVED,
    "mcp_server": _RESOURCE_OBSERVED,
    "agent": ("agents",),
    "model": ("models", "embeddings"),
}

ADOPT_FIELD = {
    "tool": "mcp_servers",
    "mcp_server": "mcp_servers",
    "mcp": "mcp_servers",
    "retriever": "knowledge_bases",
    "knowledge_base": "knowledge_bases",
    "system": "enterprise_systems",
    "database": "databases",
}

# Words that say what a thing is rather than which thing it is.
_GENERIC_TOKENS = frozenset({
    "api", "apis", "server", "servers", "service", "services", "svc", "mcp",
    "tool", "tools", "agent", "agents", "system", "systems", "platform", "app",
    "db", "database", "kb", "knowledge", "base", "the", "of", "and", "for",
    # Tool-name verbs: without these "sanctions_check" would match "credit_check".
    "get", "check", "search", "lookup", "fetch", "query", "call", "run", "list",
    "create", "update", "read", "write", "send",
})
_MIN_SUBSTRING_LEN = 4
_MIN_TOKEN_OVERLAP = 0.5
_DATE_SUFFIX = re.compile(r"[-_@]?\d{4}-?\d{2}-?\d{2}$")


def _attr(attrs: Mapping[str, Any], key: str) -> Any:
    """Whitelisted attribute lookup; Phoenix returns flat dotted keys, OTel
    exporters sometimes nest them."""
    if key not in _ALLOWED_ATTRS:
        raise KeyError(f"attribute {key!r} is not on the allowlist")
    if key in attrs:
        return attrs[key]
    node: Any = attrs
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return None if isinstance(node, Mapping) else node


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return None
    text = str(value).strip()
    return text or None


def _invocation_model(value: Any) -> str | None:
    """Only the "model" key of an invocation-parameters JSON blob; the OpenAI
    embeddings instrumentor records the model nowhere else."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return _text(value.get("model")) if isinstance(value, Mapping) else None


def _kind(span: Mapping[str, Any], attrs: Mapping[str, Any]) -> str:
    kind = _text(span.get("span_kind")) or _text(_attr(attrs, "openinference.span.kind"))
    if kind and kind.upper() != "UNKNOWN":
        return kind.upper()
    op = _text(_attr(attrs, "gen_ai.operation.name"))
    return _GEN_AI_OPERATION_KIND.get((op or "").lower(), "UNKNOWN")


def observed_from_spans(spans: Iterable[Mapping[str, Any]]) -> dict[str, list[dict]]:
    """{tools, mcp_servers, retrievers, models, agents, embeddings}, each a list
    of {name, count} sorted by count descending."""
    counters = {key: Counter() for key in OBSERVED_KEYS}
    for span in spans:
        attrs = span.get("attributes") or {}
        if not isinstance(attrs, Mapping):
            attrs = {}
        kind = _kind(span, attrs)
        span_name = _text(span.get("name"))

        tool = (_text(_attr(attrs, "tool.name")) or _text(_attr(attrs, "gen_ai.tool.name"))
                or _text(_attr(attrs, "mcp.tool")))
        if tool or (kind == "TOOL" and span_name):
            counters["tools"][tool or span_name] += 1

        server = _text(_attr(attrs, "mcp.server"))
        if server:
            counters["mcp_servers"][server] += 1

        if kind == "RETRIEVER" and span_name:
            counters["retrievers"][span_name] += 1

        if kind == "EMBEDDING":
            embedding = (_text(_attr(attrs, "embedding.model_name"))
                         or _invocation_model(_attr(attrs, "embedding.invocation_parameters"))
                         or span_name)
            if embedding:
                counters["embeddings"][embedding] += 1
        else:
            model = (_text(_attr(attrs, "llm.model_name")) or _text(_attr(attrs, "gen_ai.response.model"))
                     or _text(_attr(attrs, "gen_ai.request.model")))
            if model:
                counters["models"][model] += 1

        agent = _text(_attr(attrs, "agent.name")) or _text(_attr(attrs, "gen_ai.agent.name"))
        if not agent and kind == "AGENT" and span_name and span_name.lower() not in _FRAMEWORK_AGENT_NAMES:
            agent = span_name
        if agent:
            counters["agents"][agent] += 1

    return {
        key: [{"name": name, "count": count}
              for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        for key, counter in counters.items()
    }


# Node kinds a lineage diagram draws — deliberately narrower than the full
# OpenInference span-kind vocabulary. LLM/EMBEDDING calls are collapsed into
# their calling agent (shown as its token/model metadata, not a separate
# box); only agent steps, tool calls, MCP servers, retrievers and guardrail
# checks are meaningful nodes in a "what depends on what" picture.
LINEAGE_KINDS = ("agent", "tool", "step", "mcp_server", "retriever", "guardrail")


def agent_name_index(spans: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Lower-cased names with real agent evidence somewhere in the sample: an
    AGENT-kind span, or an ``agent.name``/``gen_ai.agent.name`` attribute.

    Needed because LangGraph emits each agent step twice — once as an AGENT
    span carrying ``agent.name`` and once as a bare CHAIN span carrying no
    agent attribute at all. Classifying a span on its own would therefore
    split every agent into an agent node and a step node. A name is an agent
    everywhere as soon as it is an agent anywhere; a CHAIN name that never
    gets that evidence is a graph/workflow step, not an agent.
    """
    names: set[str] = set()
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        attrs = span.get("attributes") or {}
        if not isinstance(attrs, Mapping):
            attrs = {}
        declared = _text(_attr(attrs, "agent.name")) or _text(_attr(attrs, "gen_ai.agent.name"))
        if declared:
            names.add(declared.strip().lower())
            continue
        if _kind(span, attrs) != "AGENT":
            continue
        name = _text(span.get("name"))
        if not name:
            continue
        lname = name.strip().lower()
        if lname in _FRAMEWORK_AGENT_NAMES or _PLUMBING_PATTERN.match(lname):
            continue
        names.add(lname)
    return frozenset(names)


def classify_span(
    span: Mapping[str, Any],
    agent_names: frozenset[str] = frozenset(),
) -> tuple[str, str] | None:
    """Resolves one span to a lineage node ``(kind, name)``, or ``None`` when
    the span is LangGraph/OTel routing or bookkeeping plumbing (a supervisor
    dispatch step, a checkpoint/interrupt marker, the graph's own root run)
    that carries no information of its own — the caller folds it through to
    its nearest resolved ancestor instead of dropping the edge. Used by the
    trace-reconstructed graph (``discovery/reconstruct.py``), so a step's
    *kind* (agent vs plain workflow step) there always agrees with
    ``observed_from_spans`` above — but the two do not share a *count*: this
    function folds a CHAIN span into the same node as its AGENT twin (see
    module docstring on ``reconstruct.py``), so a step with both emits two
    increments there, while ``observed_from_spans`` only ever counts the
    AGENT-kind span. A step's occurrence count can legitimately differ
    between the trace graph and the declared-vs-observed comparison for
    that reason — only the kind classification is guaranteed to match.

    ``agent_names`` comes from :func:`agent_name_index` over the same sample.
    Without it a CHAIN span can only be reported as a ``step``, since the
    evidence that it is an agent lives on its AGENT twin, not on itself."""
    attrs = span.get("attributes") or {}
    if not isinstance(attrs, Mapping):
        attrs = {}
    kind = _kind(span, attrs)
    name = _text(span.get("name"))

    tool = (_text(_attr(attrs, "tool.name")) or _text(_attr(attrs, "gen_ai.tool.name"))
            or _text(_attr(attrs, "mcp.tool")))
    if tool:
        return ("tool", tool)
    if kind == "TOOL" and name:
        return ("tool", name)

    server = _text(_attr(attrs, "mcp.server"))
    if server:
        return ("mcp_server", server)

    if kind == "RETRIEVER" and name:
        return ("retriever", name)

    agent = _text(_attr(attrs, "agent.name")) or _text(_attr(attrs, "gen_ai.agent.name"))
    if agent:
        return ("agent", agent)

    if not name:
        return None
    lname = name.strip().lower()
    if lname in _FRAMEWORK_AGENT_NAMES or _PLUMBING_PATTERN.match(lname):
        return None

    if kind == "AGENT":
        return ("agent", name)
    # LangGraph's default auto-instrumentation emits a domain agent step as a
    # plain CHAIN span too, so a CHAIN name is an agent when its AGENT twin
    # exists in this sample. Everything else CHAIN-kind is a graph/workflow
    # node (an interrupt, a wait, a terminal state) — real, but not an agent.
    if kind == "CHAIN":
        return ("agent", name) if lname in agent_names else ("step", name)
    if kind == "GUARDRAIL":
        return ("guardrail", name)

    return None  # LLM/EMBEDDING/EVALUATOR/RERANKER/UNKNOWN with no other signal


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def sample_stats(spans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Time window covered by the sample and the share of spans whose parent
    is missing from it (a high share means the sample cut traces in half)."""
    span_ids: set[str] = set()
    parents: list[str | None] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for span in spans:
        context = span.get("context") or {}
        if context.get("span_id"):
            span_ids.add(context["span_id"])
        parents.append(span.get("parent_id"))
        start, end = _parse_ts(span.get("start_time")), _parse_ts(span.get("end_time"))
        if start:
            starts.append(start)
        if end or start:
            ends.append(end or start)
    orphans = sum(1 for parent in parents if parent and parent not in span_ids)
    return {
        "from": min(starts).isoformat() if starts else None,
        "to": max(ends).isoformat() if ends else None,
        "orphanRate": round(orphans / len(parents), 4) if parents else 0.0,
    }


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _tokens(name: str) -> set[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    tokens = {t for t in re.split(r"[^a-z0-9]+", split.lower()) if t}
    specific = tokens - _GENERIC_TOKENS
    return specific or tokens


def names_match(a: str, b: str) -> bool:
    """Case/punctuation-insensitive fuzzy match: equal, a substring of at least
    four characters, or half the distinguishing words in common."""
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = sorted((na, nb), key=len)
    if len(shorter) >= _MIN_SUBSTRING_LEN and shorter in longer:
        return True
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / max(len(ta), len(tb)) >= _MIN_TOKEN_OVERLAP


def model_family(name: str) -> str:
    """'azure/GPT-4.1-mini-2025-04-14' -> 'gpt41mini'."""
    base = name.strip().lower().rsplit("/", 1)[-1]
    return _normalise(_DATE_SUFFIX.sub("", base))


def _models_match(a: str, b: str) -> bool:
    fa, fb = model_family(a), model_family(b)
    return bool(fa) and fa == fb


def _declared_items(declared: Mapping[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for field in DECLARED_KEYS:
        values = declared.get(field) or []
        if isinstance(values, str):
            values = [values]
        seen: set[str] = set()
        for value in values:
            name = _text(value)
            if not name or _normalise(name) in seen:
                continue
            seen.add(_normalise(name))
            items.append((field, name))
    return items


def compare(declared: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, list[dict]]:
    """Declared vs observed dependencies.

    declared: {enterprise_systems, databases, knowledge_bases, mcp_servers,
    calls: [str]} plus optional model_name (str or [str]); missing/None = [].
    observed: the output of observed_from_spans.

    Returns {confirmed, declared_only, observed_only}:
      confirmed      {name, kind, declaredAs, observedAs, observedName, count}
      declared_only  {name, kind, declaredAs}
      observed_only  {name, kind, observedAs, count}
    declaredAs is the declared field, observedAs the observed key. An observed
    item confirms every declared item it matches; it is observed_only only when
    it matches none. Models match on family (date suffix ignored), everything
    else with names_match.
    """
    observed_items = [
        (key, item) for key in OBSERVED_KEYS for item in (observed.get(key) or [])
        if _text(item.get("name"))
    ]
    matched: set[int] = set()
    confirmed: list[dict] = []
    declared_only: list[dict] = []

    for field, name in _declared_items(declared):
        kind = DECLARED_KIND[field]
        match = _models_match if kind == "model" else names_match
        best: tuple[int, str, dict] | None = None
        for index, (key, item) in enumerate(observed_items):
            if key not in _COMPATIBLE_OBSERVED[kind] or not match(name, item["name"]):
                continue
            matched.add(index)
            if best is None or item.get("count", 0) > best[2].get("count", 0):
                best = (index, key, item)
        if best is None:
            declared_only.append({"name": name, "kind": kind, "declaredAs": field})
        else:
            _, key, item = best
            confirmed.append({
                "name": name, "kind": kind, "declaredAs": field,
                "observedAs": key, "observedName": item["name"], "count": item.get("count", 0),
            })

    observed_only = [
        {"name": item["name"], "kind": OBSERVED_KIND[key], "observedAs": key, "count": item.get("count", 0)}
        for index, (key, item) in enumerate(observed_items) if index not in matched
    ]
    return {"confirmed": confirmed, "declared_only": declared_only, "observed_only": observed_only}


def adopt_items(declared: Mapping[str, Any], items: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    """Plan for appending observed items to the declared fields.

    Returns {fields: {field: new list}, added: [...], skipped: [...]}; only
    changed fields appear in `fields`. Raises ValueError on an unknown kind."""
    fields: dict[str, list] = {}
    added: list[dict] = []
    skipped: list[dict] = []
    for item in items:
        kind = (item.get("kind") or "").strip().lower()
        field = ADOPT_FIELD.get(kind)
        if field is None:
            raise ValueError(f"cannot adopt kind {kind!r}; expected one of {sorted(ADOPT_FIELD)}")
        name = _text(item.get("name"))
        if not name:
            raise ValueError("item name is empty")
        current = fields.get(field)
        if current is None:
            current = list(declared.get(field) or [])
        if any(_normalise(str(existing)) == _normalise(name) for existing in current):
            skipped.append({"name": name, "field": field, "reason": "already declared"})
            continue
        fields[field] = [*current, name]
        added.append({"name": name, "field": field})
    return {"fields": fields, "added": added, "skipped": skipped}


def _agent_hops(adj: Mapping[str, Any], agent_id: str) -> dict[str, int]:
    hops = {agent_id: 0}
    queue = deque([agent_id])
    while queue:
        current = queue.popleft()
        for caller in adj["callers_of"].get(current, []):
            if caller not in hops:
                hops[caller] = hops[current] + 1
                queue.append(caller)
    return hops


def blast_radius_view(adj: Mapping[str, Any], agent_id: str, impact: Mapping[str, Any]) -> dict[str, Any]:
    """Who loses service if this agent goes down. `adj` is
    graph_service.build_adjacency output, `impact` is affected_subgraph(adj, agent_id)."""
    hops = _agent_hops(adj, agent_id)
    agents = []
    for other in impact.get("affected_agents", []):
        if other == agent_id:
            continue
        attrs = adj["agent_attrs"].get(other) or {}
        agents.append({
            "id": other,
            "name": adj["node_names"].get(other, other),
            "stage": attrs.get("stage"),
            "dept": attrs.get("dept"),
            "atRisk": bool(attrs.get("at_risk")),
            "riskLevel": attrs.get("risk_level"),
            "hops": hops.get(other),
        })
    agents.sort(key=lambda a: (a["hops"] or 0, a["name"].lower()))

    consumer_hops: dict[str, int] = {}
    for affected in [agent_id, *(a["id"] for a in agents)]:
        for consumer in adj["consumers_of"].get(affected, []):
            hop = hops.get(affected, 0) + 1
            consumer_hops[consumer] = min(hop, consumer_hops.get(consumer, hop))
    consumers = sorted(
        ({"id": cid, "name": adj["node_names"].get(cid, cid), "hops": hop} for cid, hop in consumer_hops.items()),
        key=lambda c: (c["hops"], c["name"].lower()),
    )
    return {
        "downstreamCount": len(agents) + len(consumers),
        "agents": agents,
        "consumers": consumers,
        "revenueAtRisk": impact.get("revenue_at_risk", 0),
        "hoursAtRisk": impact.get("hours_at_risk", 0),
        "riskLevel": impact.get("risk_level"),
        "depts": impact.get("blast_depts", []),
    }


def upstream_view(adj: Mapping[str, Any], agent_id: str) -> list[dict[str, Any]]:
    """Agents this one calls, with their stage and risk flags; unregistered
    references come back with registered=False."""
    out = []
    for callee in dict.fromkeys(adj["calls_by"].get(agent_id, [])):
        attrs = adj["agent_attrs"].get(callee)
        name = adj["node_names"].get(callee, callee)
        if attrs is None:
            out.append({"id": callee, "name": name, "registered": False, "stage": None,
                        "atRisk": None, "riskLevel": None, "worstGate": None})
        else:
            out.append({"id": callee, "name": name, "registered": True, "stage": attrs.get("stage"),
                        "atRisk": bool(attrs.get("at_risk")), "riskLevel": attrs.get("risk_level"),
                        "worstGate": attrs.get("worst_gate")})
    return out


_RESOURCE_EDGES = frozenset({"ACCESSES", "USES_KB", "USES_MCP"})
CONCENTRATION_THRESHOLD = 3


def shared_resources(adj: Mapping[str, Any], agent_id: str) -> list[dict[str, Any]]:
    """Declared systems/databases/KBs/MCP servers of this agent and how many
    other agents declare the same one."""
    users: dict[str, set[str]] = {}
    for edge in adj.get("edges", []):
        if edge["type"] in _RESOURCE_EDGES:
            users.setdefault(edge["to"], set()).add(edge["from"])
    kinds = {node["id"]: node["kind"] for node in adj.get("nodes", [])}
    out = []
    for resource, agents in users.items():
        if agent_id not in agents:
            continue
        others = len(agents - {agent_id})
        out.append({
            "id": resource,
            "name": adj["node_names"].get(resource, resource),
            "kind": kinds.get(resource),
            "alsoUsedBy": others,
            "concentrated": others >= CONCENTRATION_THRESHOLD,
        })
    out.sort(key=lambda r: (-r["alsoUsedBy"], r["name"].lower()))
    return out
