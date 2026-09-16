"""Unit tests for discovery/reconstruct.py — pure functions, no DB, so these
are safe to run anytime (no shared-SQLite-file risk, unlike tests that go
through the app's TestClient)."""
from __future__ import annotations

from discovery.reconstruct import reconstruct


def _span(span_id, parent_id, name, kind, status="OK", start=None, end=None, trace_id="t1"):
    return {
        "context": {"trace_id": trace_id, "span_id": span_id},
        "parent_id": parent_id,
        "name": name,
        "span_kind": kind,
        "status_code": status,
        "start_time": start,
        "end_time": end,
    }


def test_empty_spans_returns_empty_graph():
    result = reconstruct([])
    assert result == {"spanCount": 0, "traceCount": 0, "nodes": [], "edges": []}


def test_single_span_no_parent_is_one_node_no_edges():
    result = reconstruct([_span("s1", None, "root", "CHAIN")])
    assert result["spanCount"] == 1
    assert result["traceCount"] == 1
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["name"] == "root"
    assert result["nodes"][0]["kind"] == "CHAIN"
    assert result["nodes"][0]["count"] == 1
    assert result["edges"] == []


def test_parent_child_spans_produce_one_edge():
    spans = [
        _span("s1", None, "pipeline_run", "CHAIN"),
        _span("s2", "s1", "classify", "LLM"),
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert edge["from"] == "CHAIN:pipeline_run"
    assert edge["to"] == "LLM:classify"
    assert edge["count"] == 1


def test_repeated_call_shape_across_traces_aggregates_into_one_edge():
    """Same structural call (root -> classify) happening across 3 separate
    traces must collapse into ONE edge with count=3, not 3 separate edges —
    this is the whole point of reconstructing structure, not drawing a
    graph per trace."""
    spans = []
    for i in range(3):
        spans.append(_span(f"root-{i}", None, "pipeline_run", "CHAIN", trace_id=f"trace-{i}"))
        spans.append(_span(f"child-{i}", f"root-{i}", "classify", "LLM", trace_id=f"trace-{i}"))
    result = reconstruct(spans)
    assert result["traceCount"] == 3
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    assert result["edges"][0]["count"] == 3
    node = next(n for n in result["nodes"] if n["name"] == "pipeline_run")
    assert node["count"] == 3


def test_unknown_span_kind_falls_back_to_unknown_not_dropped():
    result = reconstruct([_span("s1", None, "weird_step", "SOME_FUTURE_VENDOR_KIND")])
    assert result["nodes"][0]["kind"] == "UNKNOWN"
    assert result["nodes"][0]["name"] == "weird_step"


def test_span_kind_read_from_attributes_when_top_level_field_absent():
    span = {
        "context": {"trace_id": "t1", "span_id": "s1"},
        "parent_id": None,
        "name": "AzureChatOpenAI",
        "attributes": {"openinference.span.kind": "LLM"},
        "status_code": "OK",
    }
    result = reconstruct([span])
    assert result["nodes"][0]["kind"] == "LLM"


def test_error_status_counted_on_the_node():
    spans = [
        _span("s1", None, "call", "TOOL", status="OK"),
        _span("s2", None, "call", "TOOL", status="ERROR"),
    ]
    result = reconstruct(spans)
    assert result["nodes"][0]["count"] == 2
    assert result["nodes"][0]["errorCount"] == 1


def test_latency_averaged_across_samples():
    spans = [
        _span("s1", None, "call", "LLM", start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:01Z"),
        _span("s2", None, "call", "LLM", start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:03Z"),
    ]
    result = reconstruct(spans)
    # 1000ms and 3000ms -> average 2000ms
    assert result["nodes"][0]["avgLatencyMs"] == 2000.0


def test_malformed_span_missing_context_does_not_raise():
    spans = [{"name": "broken", "parent_id": None}]
    result = reconstruct(spans)
    assert result["spanCount"] == 1
    assert len(result["nodes"]) == 1
    assert result["traceCount"] == 0


def test_self_referential_parent_does_not_create_self_edge():
    spans = [_span("s1", "s1", "weird", "CHAIN")]
    result = reconstruct(spans)
    assert result["edges"] == []


def test_orphan_parent_id_pointing_nowhere_is_ignored():
    """A child span whose parent_id names a span not in this sample (e.g.
    the parent fell outside the page window) must not crash or fabricate
    an edge to a node that doesn't exist."""
    spans = [_span("s2", "does-not-exist", "classify", "LLM")]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1
    assert result["edges"] == []
