"""Key risk indicators computed from Phoenix spans.

Only whitelisted span fields are read. Prompt and output text
(input.value, output.value, llm.input_messages.*, llm.output_messages.*)
never leaves `slim_span`, so it cannot reach a finding, a log or the DB.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable

# Flags for the KRIs plus the dependency names discovery.observed_deps reads.
ALLOWED_ATTRIBUTES = (
    "openinference.span.kind",
    "pii.detected",
    "guardrail.injection_detected",
    "gen_ai.operation.name",
    "tool.name",
    "gen_ai.tool.name",
    "mcp.server",
    "mcp.tool",
    "llm.model_name",
    "gen_ai.response.model",
    "gen_ai.request.model",
    "embedding.model_name",
    "agent.name",
    "gen_ai.agent.name",
)


def _attr(attributes: dict, key: str) -> Any:
    if key in attributes:
        return attributes[key]
    # Some Phoenix versions return attributes nested instead of dotted.
    node: Any = attributes
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return None if isinstance(node, dict) else node


def slim_span(span: dict) -> dict:
    attributes = span.get("attributes") or {}
    context = span.get("context") or {}
    kept = {}
    for key in ALLOWED_ATTRIBUTES:
        value = _attr(attributes, key)
        if value is not None:
            kept[key] = value
    return {
        "name": span.get("name"),
        "span_kind": span.get("span_kind") or kept.get("openinference.span.kind"),
        "status_code": span.get("status_code"),
        "start_time": span.get("start_time"),
        "end_time": span.get("end_time"),
        "parent_id": span.get("parent_id"),
        "context": {"trace_id": context.get("trace_id"), "span_id": context.get("span_id")},
        "attributes": kept,
    }


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return False


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def kri_from_spans(spans: Iterable[dict]) -> dict:
    """p95_latency_ms is over whole traces (first span start to last span
    end), the closest thing to request latency an SLA describes."""
    span_count = 0
    error_spans = 0
    pii_spans = 0
    injection_spans = 0
    llm_calls = 0
    traces: set[str] = set()
    pii_traces: set[str] = set()
    injection_traces: set[str] = set()
    errors_by_name: dict[str, int] = {}
    trace_bounds: dict[str, list[datetime]] = {}

    for span in spans:
        span_count += 1
        trace_id = (span.get("context") or {}).get("trace_id")
        attributes = span.get("attributes") or {}
        if trace_id:
            traces.add(trace_id)
        if span.get("status_code") == "ERROR":
            error_spans += 1
            name = span.get("name") or "unnamed"
            errors_by_name[name] = errors_by_name.get(name, 0) + 1
        kind = span.get("span_kind") or _attr(attributes, "openinference.span.kind")
        if str(kind or "").upper() == "LLM":
            llm_calls += 1
        if is_truthy(_attr(attributes, "pii.detected")):
            pii_spans += 1
            if trace_id:
                pii_traces.add(trace_id)
        if is_truthy(_attr(attributes, "guardrail.injection_detected")):
            injection_spans += 1
            if trace_id:
                injection_traces.add(trace_id)
        start, end = _parse_time(span.get("start_time")), _parse_time(span.get("end_time"))
        if trace_id and start and end:
            bounds = trace_bounds.get(trace_id)
            if bounds is None:
                trace_bounds[trace_id] = [start, end]
            else:
                bounds[0] = min(bounds[0], start)
                bounds[1] = max(bounds[1], end)

    durations = [(e - s).total_seconds() * 1000 for s, e in trace_bounds.values()]
    p95 = percentile(durations, 95)
    worst = max(errors_by_name.items(), key=lambda kv: kv[1]) if errors_by_name else None
    return {
        "span_count": span_count,
        "trace_count": len(traces),
        "error_spans": error_spans,
        "error_rate": (error_spans / span_count) if span_count else None,
        "worst_error_span": {"name": worst[0], "errors": worst[1]} if worst else None,
        "pii_spans": pii_spans,
        "pii_traces": len(pii_traces),
        "injection_spans": injection_spans,
        "injection_traces": len(injection_traces),
        "p95_latency_ms": round(p95, 1) if p95 is not None else None,
        "llm_calls": llm_calls,
    }
