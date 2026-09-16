"""Reconstructs a structural dependency diagram from a project's raw Phoenix
spans — literally "what does this app's real, running architecture look
like," derived from what it actually did rather than from hand-declared
fields.

One structural node per distinct (span name, span kind) pair — spans repeat
the same call shape across many trace runs, so this aggregates rather than
drawing one node per span (a busy project would otherwise be an unreadable
wall of one-off boxes). An edge is a real parent→child relationship between
two spans, aggregated the same way — count is how many times that call
happened across the sampled traces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

# Phoenix/OpenInference span-kind vocabulary this reconstruction understands.
# Falls back to "UNKNOWN" for anything else — a real, expected outcome, not
# a bug: LangGraph's own auto-instrumentation emits plain CHAIN spans for
# what are domain-level agent invocations (see this org's own
# docs/architecture/TRACE-MAPPING.md in the assureai project for the
# evidence), so "the vendor's span kind doesn't say what I'd guess" is
# normal, not an error to surface as one.
_KNOWN_KINDS = {
    "AGENT", "LLM", "TOOL", "RETRIEVER", "CHAIN",
    "GUARDRAIL", "EVALUATOR", "RERANKER", "EMBEDDING", "UNKNOWN",
}


def _span_kind(span: dict) -> str:
    kind = span.get("span_kind") or (span.get("attributes") or {}).get("openinference.span.kind")
    kind = str(kind).upper() if kind else "UNKNOWN"
    return kind if kind in _KNOWN_KINDS else "UNKNOWN"


def _node_key(name: str, kind: str) -> str:
    return f"{kind}:{name}"


def _latency_ms(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return (e - s).total_seconds() * 1000
    except (ValueError, TypeError):
        return None


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
    count: int = 0


def reconstruct(spans: Iterable[dict]) -> dict:
    """Builds {nodes, edges, spanCount, traceCount} from raw Phoenix span
    dicts. Never raises on one malformed span — a span missing a field it
    needs is just skipped for that field, never fatal to the whole
    reconstruction (one bad span out of thousands in a busy real project
    must not blank the entire diagram)."""
    nodes: dict[str, _NodeAgg] = {}
    edges: dict[tuple[str, str], _EdgeAgg] = {}
    # span_id -> its structural node key, so a child span can resolve its
    # parent's node key regardless of what order pages arrived in.
    span_to_node: dict[str, str] = {}
    parent_of: dict[str, str | None] = {}
    trace_ids: set[str] = set()
    span_count = 0

    for span in spans:
        span_count += 1
        context = span.get("context") or {}
        span_id = context.get("span_id")
        trace_id = context.get("trace_id")
        if trace_id:
            trace_ids.add(trace_id)

        name = span.get("name") or "unnamed"
        kind = _span_kind(span)
        key = _node_key(name, kind)

        if span_id:
            span_to_node[span_id] = key
            parent_of[span_id] = span.get("parent_id")

        node = nodes.setdefault(key, _NodeAgg(name=name, kind=kind))
        node.count += 1
        if span.get("status_code") == "ERROR":
            node.error_count += 1
        latency = _latency_ms(span.get("start_time"), span.get("end_time"))
        if latency is not None:
            node.total_latency_ms += latency
            node.latency_samples += 1

    for span_id, node_key in span_to_node.items():
        parent_id = parent_of.get(span_id)
        if not parent_id:
            continue
        parent_key = span_to_node.get(parent_id)
        if not parent_key or parent_key == node_key:
            continue
        edge = edges.setdefault((parent_key, node_key), _EdgeAgg(frm=parent_key, to=node_key))
        edge.count += 1

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
            }
            for key, n in nodes.items()
        ],
        "edges": [{"from": e.frm, "to": e.to, "count": e.count} for e in edges.values()],
    }
