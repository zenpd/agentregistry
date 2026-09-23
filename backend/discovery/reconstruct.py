"""Reconstructs an agent-lineage diagram from a project's raw Phoenix spans
— "which agent steps call which tools, MCP servers and knowledge bases, and
in what order," derived from what the app actually did rather than from
hand-declared fields.

Every span is resolved to a lineage node via ``discovery.observed_deps.
classify_span`` (agent / tool / mcp_server / retriever / guardrail) — the
same function the declared-vs-observed comparison's own classifier agrees
with on *kind*, so a step is never an agent on one view and a plain step on
the other. Their *counts* can still differ (see classify_span's docstring):
this module's per-node count is a span tally, and a CHAIN span merges into
the same node as its AGENT twin without deduplicating, so a step with both
counts twice here. A span that resolves to nothing — LangGraph's own
routing dispatch, `interrupt()` bookkeeping, the graph's own root run, a
bare LLM/embedding call — is plumbing: it is folded through to its nearest
resolved ancestor rather than dropped, so a true nested call still gets an
edge even when several plumbing hops sit between the two spans. LangGraph
also commonly emits a CHAIN span and an AGENT span for the same logical
step (e.g. "supervisor" appearing twice); resolving purely on (kind, name)
merges them into one node, with a combined (summed, not deduplicated)
count — see ``test_chain_and_agent_twin_spans_merge_into_one_node``.

Two distinct edge kinds, verified against this project's own real traces
(``retail-onboarding``) rather than assumed:

- **calls** — a true span parent→child relationship (after folding
  plumbing). This is what shows up when one step's work is literally
  nested inside another's, e.g. an agent calling a tool, or a step
  invoking a sub-step as part of its own execution.
- **sequence** — same trace, no span-nesting reaches another real node at
  all, even after walking through plumbing. Verified live: this app's
  LangGraph instrumentation nests its graph steps (guardrails, supervisor,
  kyc_compliance, human_review, ...) all directly under the same "LangGraph"
  root-run span, as siblings — the span tree captures *what ran inside
  what*, not *what the graph executor ran next*, so a supervisor's routing
  handoff to the step it picked has no parent-child link to walk. The
  sequence edge recovers that handoff from real ordering: within one
  trace, every resolved step whose ancestor walk found nothing (a true
  structural root, not just one with a missing `parent_id`) is connected
  to the next such step, by `start_time`. This is the literal "trajectory"
  one onboarding run took through the agent's steps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from discovery.observed_deps import agent_name_index, classify_span

# How many plumbing hops to walk through when looking for a resolved
# ancestor — generous enough for any real LangGraph interrupt/routing
# chain, bounded so a malformed parent_id cycle can never loop forever.
_MAX_ANCESTOR_WALK = 50

# Groups classify_span's lineage-node kinds into the handful of lanes the
# Diagram tab's trajectory view draws: the agent's own steps, the tools/
# skills it invokes, the resources (MCP servers, retrievers) it reads, and
# the guardrail checks it runs. LLM/EMBEDDING calls never reach here — they
# are folded into their calling step above, not drawn as their own node —
# so there is deliberately no "model" kind in LINEAGE_KINDS to map.
_ROLE_BY_KIND = {
    "agent": "step",
    "step": "step",
    "tool": "tool",
    "mcp_server": "tool",
    "retriever": "resource",
    "guardrail": "check",
}
ROLE_LANES = ["step", "model", "tool", "resource", "check", "other"]

CALLS = "calls"
SEQUENCE = "sequence"


def _latency_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return (e - s).total_seconds() * 1000
    except (ValueError, TypeError):
        return None


def _sort_ts(value: str | None) -> str:
    # Spans without a start_time sort after ones that have it, stably.
    return value or "9999"


@dataclass
class _NodeAgg:
    name: str
    kind: str
    count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    latency_samples: int = 0


@dataclass
class _EdgeAgg:
    frm: str
    to: str
    kind: str
    count: int = 0


def _layer_depths(node_keys: Iterable[str], edge_pairs: Iterable[tuple[str, str]]) -> tuple[dict[str, int], set[str]]:
    """BFS distance from a root, for a left-to-right trajectory layout.

    This was originally longest-path-from-root (depth = one more than the
    deepest prerequisite), which reads naturally for a straight-line
    pipeline — but a real LangGraph supervisor pattern loops (supervisor ->
    agent -> back to supervisor -> next agent, dozens of times per trace),
    and longest-path has no ceiling on a cycle: on real retail-onboarding
    traces it inflated to depth 99-100, which would draw a diagram 100
    columns wide. BFS first-visit-wins depth is bounded by the graph's
    actual diameter regardless of how many times it loops, so the layout
    stays a handful of columns wide even for a heavily looping graph.
    """
    keys = list(node_keys)
    adj: dict[str, list[str]] = {k: [] for k in keys}
    incoming = {k: 0 for k in keys}
    for frm, to in edge_pairs:
        if frm in adj and to in adj:
            adj[frm].append(to)
            incoming[to] += 1
    roots = {k for k in keys if incoming[k] == 0} or set(keys[:1])

    depth: dict[str, int] = {}
    queue: deque[str] = deque()
    for r in roots:
        depth[r] = 0
        queue.append(r)
    while queue:
        cur = queue.popleft()
        for nxt in adj[cur]:
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                queue.append(nxt)
    # A node no root can reach (disconnected component, or every path into
    # it runs through another such node) still needs a column to draw in.
    for k in keys:
        depth.setdefault(k, 0)
    return depth, roots


def reconstruct(spans: Iterable[dict]) -> dict:
    """Builds {nodes, edges, spanCount, traceCount} from raw Phoenix span
    dicts. Never raises on one malformed span — a span missing a field it
    needs is just skipped for that field, never fatal to the whole
    reconstruction (one bad span out of thousands in a busy real project
    must not blank the entire diagram)."""
    # Materialised because classification needs two passes: an agent step's
    # CHAIN twin carries no agent attribute, so which names are agents can
    # only be known after looking at every span (see agent_name_index).
    spans = list(spans)
    agent_names = agent_name_index(spans)
    nodes: dict[str, _NodeAgg] = {}
    edges: dict[tuple[str, str, str], _EdgeAgg] = {}
    # span_id -> its resolved lineage-node key, or None for a plumbing span
    # that should be walked through when building "calls" edges.
    resolved_of: dict[str, str | None] = {}
    parent_of: dict[str, str | None] = {}
    trace_of: dict[str, str | None] = {}
    start_of: dict[str, str | None] = {}
    trace_ids: set[str] = set()
    span_count = 0

    # Spans that are folded away (an LLM or embedding call, routing plumbing)
    # but that FAILED. The failure is real and belongs to whichever step made
    # the call, so it is walked up to the nearest drawn node below rather than
    # dropped with the span — otherwise a tool whose every call failed inside
    # its embedding reports a clean zero.
    folded_errors: list[str] = []

    for span in spans:
        span_count += 1
        if not isinstance(span, dict):
            continue
        context = span.get("context") or {}
        span_id = context.get("span_id")
        trace_id = context.get("trace_id")
        if trace_id:
            trace_ids.add(trace_id)

        classified = classify_span(span, agent_names)
        key = None
        if not classified and span_id and span.get("status_code") == "ERROR":
            folded_errors.append(span_id)
        if classified:
            kind, name = classified
            key = f"{kind}:{name.strip().lower()}"
            node = nodes.setdefault(key, _NodeAgg(name=name.strip(), kind=kind))
            node.count += 1
            if span.get("status_code") == "ERROR":
                node.error_count += 1
            latency = _latency_ms(span.get("start_time"), span.get("end_time"))
            if latency is not None:
                node.total_latency_ms += latency
                node.latency_samples += 1

        if span_id:
            resolved_of[span_id] = key
            parent_of[span_id] = span.get("parent_id")
            trace_of[span_id] = trace_id
            start_of[span_id] = span.get("start_time")

    def _nearest_resolved(span_id: str) -> str | None:
        ancestor_id = parent_of.get(span_id)
        steps = 0
        while ancestor_id and steps < _MAX_ANCESTOR_WALK:
            candidate = resolved_of.get(ancestor_id)
            if candidate:
                return candidate
            ancestor_id = parent_of.get(ancestor_id)
            steps += 1
        return None

    # Attribute each folded failure to the step that made the failing call.
    for span_id in folded_errors:
        ancestor_key = _nearest_resolved(span_id)
        if ancestor_key and ancestor_key in nodes:
            nodes[ancestor_key].error_count += 1

    def _add_edge(frm: str, to: str, kind: str) -> None:
        if frm == to:
            return
        edge = edges.setdefault((frm, to, kind), _EdgeAgg(frm=frm, to=to, kind=kind))
        edge.count += 1

    # "calls" — real span nesting, walked through any folded plumbing. A
    # resolved span whose walk finds nothing is a structural root — not
    # necessarily one with a missing parent_id, just one with no real
    # ancestor to connect to (see module docstring) — and becomes a
    # candidate for the "sequence" pass below.
    top_level_by_trace: dict[str, list[tuple[str, str | None]]] = {}
    for span_id, node_key in resolved_of.items():
        if not node_key:
            continue
        ancestor_id = parent_of.get(span_id)
        ancestor_key = None
        steps = 0
        while ancestor_id and steps < _MAX_ANCESTOR_WALK:
            candidate = resolved_of.get(ancestor_id)
            if candidate:
                ancestor_key = candidate
                break
            ancestor_id = parent_of.get(ancestor_id)
            steps += 1
        if ancestor_key:
            _add_edge(ancestor_key, node_key, CALLS)
        else:
            trace_id = trace_of.get(span_id)
            if trace_id:
                top_level_by_trace.setdefault(trace_id, []).append((node_key, start_of.get(span_id)))

    # "sequence" — every structural root in a trace, connected to the next
    # one by when it actually started.
    for steps in top_level_by_trace.values():
        ordered = sorted(steps, key=lambda pair: _sort_ts(pair[1]))
        for (frm, _), (to, _) in zip(ordered, ordered[1:]):
            _add_edge(frm, to, SEQUENCE)

    # The trajectory layout's depth/root computation walks BOTH edge kinds —
    # not just "calls". This matters: LangGraph nests this app's real steps
    # as siblings under one root-run span (see module docstring), so "calls"
    # alone leaves most steps looking like their own root at depth 0.
    # "sequence" edges are exactly what recovers the true order between them.
    depth_by_key, root_keys = _layer_depths(nodes.keys(), ((e.frm, e.to) for e in edges.values()))

    return {
        "spanCount": span_count,
        "traceCount": len(trace_ids),
        "nodes": [
            {
                "id": key,
                "name": n.name,
                "kind": n.kind,
                "count": n.count,
                "errorCount": n.error_count,
                "avgLatencyMs": round(n.total_latency_ms / n.latency_samples, 1) if n.latency_samples else None,
                "role": _ROLE_BY_KIND.get(n.kind, "other"),
                "depth": depth_by_key.get(key, 0),
                "isRoot": key in root_keys,
            }
            for key, n in nodes.items()
        ],
        "edges": [{"from": e.frm, "to": e.to, "kind": e.kind, "count": e.count} for e in edges.values()],
    }
