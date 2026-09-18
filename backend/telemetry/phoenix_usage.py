"""Aggregates Phoenix LLM spans into daily usage rows.

Only whitelisted, non-content fields are read. Prompt, output and message
text (input.value, output.value, llm.input_messages.*, llm.output_messages.*)
is never copied: `slim_span` drops it as soon as a span arrives.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable, Iterable, Mapping

MODEL_KEYS = ("llm.model_name", "llm.model", "metadata.ls_model_name")
PROMPT = "llm.token_count.prompt"
COMPLETION = "llm.token_count.completion"
TOTAL = "llm.token_count.total"
CACHE_READ = "llm.token_count.prompt_details.cache_read"
KIND = "openinference.span.kind"

ATTRIBUTE_WHITELIST = frozenset((*MODEL_KEYS, PROMPT, COMPLETION, TOTAL, CACHE_READ, KIND))


def slim_span(span: Mapping) -> dict:
    """The span reduced to the fields usage aggregation needs."""
    attributes = span.get("attributes") or {}
    return {
        "span_kind": span.get("span_kind"),
        "start_time": span.get("start_time"),
        "end_time": span.get("end_time"),
        "status_code": span.get("status_code"),
        "context": {"trace_id": (span.get("context") or {}).get("trace_id")},
        "attributes": {k: attributes[k] for k in ATTRIBUTE_WHITELIST if k in attributes},
    }


def _count(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(int(float(value)), 0)
    except (TypeError, ValueError):
        return None


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def is_llm_span(span: Mapping) -> bool:
    kind = span.get("span_kind") or (span.get("attributes") or {}).get(KIND)
    return str(kind or "").upper() == "LLM"


def model_of(attributes: Mapping) -> str:
    for key in MODEL_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def token_counts(attributes: Mapping) -> tuple[int, int, int]:
    """(input, output, cached). A span that reports only a total is counted
    as input so its tokens are not lost; a missing side is derived from the
    total when the other side is present."""
    prompt = _count(attributes.get(PROMPT))
    completion = _count(attributes.get(COMPLETION))
    total = _count(attributes.get(TOTAL)) or 0
    if prompt is None and completion is None:
        prompt, completion = total, 0
    elif prompt is None:
        prompt = max(total - completion, 0)
    elif completion is None:
        completion = max(total - prompt, 0)
    return prompt, completion, _count(attributes.get(CACHE_READ)) or 0


def aggregate_llm_spans(spans: Iterable[Mapping], normalize: Callable[[str], str] | None = None) -> list[dict]:
    """One row per (UTC day of start_time, model).

    Without `normalize`, `model` is the raw model name from the span. With it,
    rows are keyed by the normalised name so traces are counted once per
    billed model, and `raw_model_names` lists the names seen."""
    groups: dict[tuple[date, str], dict] = {}
    for span in spans:
        if not is_llm_span(span):
            continue
        start = _parse_time(span.get("start_time"))
        if start is None:
            continue
        attributes = span.get("attributes") or {}
        raw = model_of(attributes)
        model = normalize(raw) if normalize else raw
        g = groups.setdefault((start.date(), model), {
            "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "calls": 0, "errors": 0,
            "traces": set(), "raw": set(), "latency_total": 0.0, "latency_samples": 0,
        })
        prompt, completion, cached = token_counts(attributes)
        g["input_tokens"] += prompt
        g["output_tokens"] += completion
        g["cached_tokens"] += cached
        g["calls"] += 1
        if str(span.get("status_code") or "").upper() == "ERROR":
            g["errors"] += 1
        trace_id = (span.get("context") or {}).get("trace_id")
        if trace_id:
            g["traces"].add(trace_id)
        g["raw"].add(raw)
        end = _parse_time(span.get("end_time"))
        if end is not None and end >= start:
            g["latency_total"] += (end - start).total_seconds() * 1000
            g["latency_samples"] += 1

    rows = []
    for (day, model), g in sorted(groups.items()):
        rows.append({
            "day": day,
            "model": model,
            "raw_model_names": sorted(g["raw"]),
            "input_tokens": g["input_tokens"],
            "output_tokens": g["output_tokens"],
            "cached_tokens": g["cached_tokens"],
            "calls": g["calls"],
            "runs": len(g["traces"]),
            "errors": g["errors"],
            "latency_avg_ms": round(g["latency_total"] / g["latency_samples"], 1) if g["latency_samples"] else None,
        })
    return rows
