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


def _node(result, name):
    return next(n for n in result["nodes"] if n["name"] == name)


def test_span_kinds_map_to_trajectory_roles():
    spans = [
        _span("s1", None, "onboarding_graph", "AGENT"),
        _span("s2", "s1", "classify_document", "LLM"),
        _span("s3", "s1", "sanctions_screen", "TOOL"),
        _span("s4", "s1", "policy_kb", "RETRIEVER"),
        _span("s5", "s1", "pii_guardrail", "GUARDRAIL"),
    ]
    result = reconstruct(spans)
    assert _node(result, "onboarding_graph")["role"] == "step"
    assert _node(result, "classify_document")["role"] == "model"
    assert _node(result, "sanctions_screen")["role"] == "tool"
    assert _node(result, "policy_kb")["role"] == "resource"
    assert _node(result, "pii_guardrail")["role"] == "check"


def test_root_span_has_depth_zero_and_is_flagged_root():
    spans = [_span("s1", None, "onboarding_graph", "AGENT")]
    result = reconstruct(spans)
    root = result["nodes"][0]
    assert root["depth"] == 0
    assert root["isRoot"] is True


def test_depth_increases_along_the_call_chain():
    """root -> classify -> sanctions_screen must lay out left-to-right in
    that order, not scattered — depth is what the frontend positions on."""
    spans = [
        _span("s1", None, "onboarding_graph", "AGENT"),
        _span("s2", "s1", "classify_document", "LLM"),
        _span("s3", "s2", "sanctions_screen", "TOOL"),
    ]
    result = reconstruct(spans)
    assert _node(result, "onboarding_graph")["depth"] == 0
    assert _node(result, "classify_document")["depth"] == 1
    assert _node(result, "sanctions_screen")["depth"] == 2
    assert _node(result, "onboarding_graph")["isRoot"] is True
    assert _node(result, "classify_document")["isRoot"] is False


def test_depth_uses_shortest_path_when_paths_converge():
    """A node reachable both directly from the root and via a longer chain
    lays out at its shallowest reachable position (BFS), not its deepest —
    see _layer_depths' docstring for why longest-path was dropped."""
    spans = [
        _span("s1", None, "root", "AGENT"),
        _span("s2", "s1", "step_a", "TOOL"),
        _span("s3", "s2", "step_b", "TOOL"),
        _span("s4", "s3", "converge", "TOOL"),
        _span("s5", "s1", "converge", "TOOL"),  # same structural node, direct from root
    ]
    result = reconstruct(spans)
    assert _node(result, "converge")["depth"] == 1


def test_cyclic_trace_does_not_hang_or_crash():
    """A retry loop (LangGraph revisiting a node) creates a real cycle in the
    span graph — the layering must still terminate with small, sensible
    depths (not inflate with every trip around the loop)."""
    spans = [
        _span("s1", None, "graph", "AGENT"),
        _span("s2", "s1", "retry_step", "TOOL"),
        _span("s3", "s2", "graph", "AGENT"),  # cycle: retry_step -> graph again
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 2
    assert _node(result, "graph")["depth"] == 0
    assert _node(result, "retry_step")["depth"] == 1


def test_supervisor_loop_depth_stays_bounded_not_inflated_by_loop_count():
    """A LangGraph supervisor dispatching to N agents and looping back is a
    real, common shape (this is what broke the original longest-path
    design on live retail-onboarding traces: depth hit 99-100). However many
    times the loop repeats, depth must stay bounded by the graph's actual
    shape, not the number of spans sampled."""
    spans = [_span("root", None, "supervisor", "AGENT")]
    trace_id = "t1"
    for i in range(60):
        spans.append(_span(f"a{i}", "root", "next_agent", "AGENT", trace_id=trace_id))
        spans.append(_span(f"b{i}", f"a{i}", "supervisor", "AGENT", trace_id=trace_id))
    result = reconstruct(spans)
    depths = {n["name"]: n["depth"] for n in result["nodes"]}
    assert depths["supervisor"] <= 2
    assert depths["next_agent"] <= 2


def test_no_root_falls_back_to_first_node_without_crashing():
    """A sample that is pure cycle (or whose true root fell outside the
    page window) still needs a starting column for layout."""
    spans = [_span("s1", "s2", "a", "TOOL"), _span("s2", "s1", "b", "TOOL")]
    result = reconstruct(spans)
    assert any(n["isRoot"] for n in result["nodes"])
