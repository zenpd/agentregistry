"""Unit tests for discovery/reconstruct.py — pure functions, no DB, so these
are safe to run anytime (no shared-SQLite-file risk, unlike tests that go
through the app's TestClient)."""
from __future__ import annotations

from discovery.reconstruct import CALLS, SEQUENCE, reconstruct


def _span(span_id, parent_id, name, kind, status="OK", start=None, end=None,
          trace_id="t1", attributes=None):
    return {
        "context": {"trace_id": trace_id, "span_id": span_id},
        "parent_id": parent_id,
        "name": name,
        "span_kind": kind,
        "status_code": status,
        "start_time": start,
        "end_time": end,
        "attributes": attributes or {},
    }


def _edge(result, frm, to, kind=CALLS):
    return next((e for e in result["edges"] if e["from"] == frm and e["to"] == to and e["kind"] == kind), None)


def test_empty_spans_returns_empty_graph():
    result = reconstruct([])
    assert result == {"spanCount": 0, "traceCount": 0, "nodes": [], "edges": []}


def test_tool_span_is_a_node():
    result = reconstruct([_span("s1", None, "ocr_extract_fields", "TOOL")])
    assert result["spanCount"] == 1
    assert result["traceCount"] == 1
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["id"] == "tool:ocr_extract_fields"
    assert node["name"] == "ocr_extract_fields"
    assert node["kind"] == "tool"
    assert node["count"] == 1
    assert result["edges"] == []


def test_llm_span_with_no_signal_is_not_a_node():
    """A bare LLM call (no tool/agent/mcp attribute) is plumbing for a
    lineage diagram — it's folded into whichever agent step it belongs to,
    not drawn as its own box."""
    result = reconstruct([_span("s1", None, "AzureChatOpenAI", "LLM")])
    assert result["nodes"] == []
    assert result["spanCount"] == 1


def test_agent_step_calling_a_nested_tool_produces_a_calls_edge():
    spans = [
        _span("s1", None, "kyc_aml", "AGENT"),
        _span("s2", "s1", "sanctions_check", "TOOL"),
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 2
    edge = _edge(result, "agent:kyc_aml", "tool:sanctions_check")
    assert edge is not None
    assert edge["count"] == 1


def test_repeated_call_shape_across_traces_aggregates_into_one_edge():
    """Same structural call (kyc_aml -> sanctions_check) happening across 3
    separate traces must collapse into ONE edge with count=3, not 3
    separate edges — this is the whole point of reconstructing structure,
    not drawing a graph per trace."""
    spans = []
    for i in range(3):
        spans.append(_span(f"root-{i}", None, "kyc_aml", "AGENT", trace_id=f"trace-{i}"))
        spans.append(_span(f"child-{i}", f"root-{i}", "sanctions_check", "TOOL", trace_id=f"trace-{i}"))
    result = reconstruct(spans)
    assert result["traceCount"] == 3
    assert len(result["nodes"]) == 2
    edge = _edge(result, "agent:kyc_aml", "tool:sanctions_check")
    assert edge["count"] == 3
    node = next(n for n in result["nodes"] if n["name"] == "kyc_aml")
    assert node["count"] == 3


def test_langgraph_routing_plumbing_is_folded_not_dropped():
    """Verified against this project's own real traces: LangGraph's routing
    dispatch ("LangGraph" root run, "__start__", "next_agent", any
    underscore-prefixed internal step) sits between real steps with no
    signal of its own — the edge must still connect the two real steps on
    either side of it, not vanish."""
    spans = [
        _span("root", None, "LangGraph", "CHAIN"),
        _span("s1", "root", "supervisor", "AGENT"),
        _span("route", "s1", "next_agent", "AGENT"),
        _span("entry", "route", "_entry_route", "CHAIN"),
        _span("s2", "entry", "kyc_compliance", "CHAIN", attributes={"agent.name": "kyc_compliance"}),
    ]
    result = reconstruct(spans)
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {"agent:supervisor", "agent:kyc_compliance"}
    edge = _edge(result, "agent:supervisor", "agent:kyc_compliance")
    assert edge is not None and edge["count"] == 1


def test_chain_and_agent_twin_spans_merge_into_one_node():
    """LangGraph commonly emits both a CHAIN span and an AGENT span for the
    same logical step (verified live: "supervisor" appears as both, 149 CHAIN
    + 141 AGENT). They must merge into one agent node with a combined count —
    the CHAIN twin carries no agent attribute of its own, so this only works
    because the whole sample is indexed before anything is classified."""
    spans = [
        _span("s1", None, "supervisor", "CHAIN"),
        _span("s2", None, "supervisor", "AGENT"),
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["id"] == "agent:supervisor"
    assert node["count"] == 2


def test_chain_span_with_no_agent_twin_is_a_workflow_step_not_an_agent():
    """Verified live: `respond_and_wait`, `awaiting_review`,
    `onboarding_complete` and `mark_complete` only ever appear as CHAIN spans
    and never carry agent.name — they're LangGraph graph nodes (a wait, an
    interrupt, a terminal state), so calling them agents overstated this
    project's agent count by four."""
    spans = [
        _span("s1", None, "supervisor", "AGENT"),
        _span("s2", None, "respond_and_wait", "CHAIN"),
    ]
    result = reconstruct(spans)
    kinds = {n["id"]: n["kind"] for n in result["nodes"]}
    assert kinds == {"agent:supervisor": "agent", "step:respond_and_wait": "step"}


def test_agent_name_attribute_on_a_chain_span_still_makes_it_an_agent():
    spans = [_span("s1", None, "kyc_compliance", "CHAIN", attributes={"agent.name": "kyc_compliance"})]
    result = reconstruct(spans)
    assert result["nodes"][0]["kind"] == "agent"


def test_agent_evidence_anywhere_upgrades_the_chain_twin_in_every_trace():
    """The AGENT twin can sit in a different trace than the CHAIN one; a name
    that is an agent anywhere in the sample is an agent everywhere, otherwise
    the same step would draw as both an agent node and a step node."""
    spans = [
        _span("a1", None, "triage", "AGENT", trace_id="t1"),
        _span("c1", None, "triage", "CHAIN", trace_id="t2"),
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == "agent:triage"
    assert result["nodes"][0]["count"] == 2


def test_sibling_steps_with_no_span_nesting_get_a_sequence_edge():
    """Verified against real traces: a supervisor's routing handoff to the
    step it picked has no parent-child span link at all — both spans sit
    directly under the same unresolved plumbing root. Recovered as a
    'sequence' edge from real start_time ordering, distinct from a 'calls'
    edge (no true nesting exists here)."""
    spans = [
        _span("root", None, "LangGraph", "CHAIN"),
        _span("s1", "root", "supervisor", "AGENT", start="2026-01-01T00:00:00Z"),
        _span("s2", "root", "triage", "AGENT", start="2026-01-01T00:00:01Z"),
    ]
    result = reconstruct(spans)
    assert _edge(result, "agent:supervisor", "agent:triage", kind=CALLS) is None
    seq_edge = _edge(result, "agent:supervisor", "agent:triage", kind=SEQUENCE)
    assert seq_edge is not None and seq_edge["count"] == 1


def test_sequence_edges_are_ordered_by_start_time_not_span_order():
    spans = [
        _span("root", None, "LangGraph", "CHAIN"),
        _span("s2", "root", "triage", "AGENT", start="2026-01-01T00:00:05Z"),
        _span("s1", "root", "supervisor", "AGENT", start="2026-01-01T00:00:01Z"),
    ]
    result = reconstruct(spans)
    assert _edge(result, "agent:supervisor", "agent:triage", kind=SEQUENCE) is not None
    assert _edge(result, "agent:triage", "agent:supervisor", kind=SEQUENCE) is None


def test_sequence_never_crosses_trace_boundaries():
    spans = [
        _span("root1", None, "LangGraph", "CHAIN", trace_id="t1"),
        _span("s1", "root1", "supervisor", "AGENT", trace_id="t1", start="2026-01-01T00:00:00Z"),
        _span("root2", None, "LangGraph", "CHAIN", trace_id="t2"),
        _span("s2", "root2", "triage", "AGENT", trace_id="t2", start="2026-01-01T00:00:01Z"),
    ]
    result = reconstruct(spans)
    assert result["edges"] == []


def test_agent_name_attribute_wins_over_span_name():
    result = reconstruct([_span("s1", None, "next_agent", "AGENT", attributes={"agent.name": "kyc_compliance"})])
    assert result["nodes"][0]["id"] == "agent:kyc_compliance"


def test_mcp_server_and_retriever_and_guardrail_kinds():
    spans = [
        _span("s1", None, "mcp_session_init", "CHAIN", attributes={"mcp.server": "sap-mcp"}),
        _span("s2", None, "search_kb", "RETRIEVER"),
        _span("s3", None, "pii_check", "GUARDRAIL"),
    ]
    result = reconstruct(spans)
    kinds = {n["kind"] for n in result["nodes"]}
    assert kinds == {"mcp_server", "retriever", "guardrail"}


def test_error_on_a_folded_span_is_attributed_to_its_caller():
    """Verified live: `rag_search`'s three calls each failed inside a child
    CreateEmbeddings span ("BadRequestError: Unsupported data type").
    Embedding spans are folded away, so counting errors only on drawn spans
    reported that tool as clean — the diagram said 0 errors while every call
    it made had failed. The failure belongs to whoever made the call."""
    spans = [
        _span("s1", None, "rag_search", "TOOL"),
        _span("e1", "s1", "CreateEmbeddings", "EMBEDDING", status="ERROR"),
    ]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["id"] == "tool:rag_search"
    assert node["count"] == 1
    assert node["errorCount"] == 1


def test_folded_error_walks_through_plumbing_to_the_nearest_real_step():
    spans = [
        _span("s1", None, "kyc_compliance", "AGENT"),
        _span("p1", "s1", "_entry_route", "CHAIN"),
        _span("llm", "p1", "ChatCompletion", "LLM", status="ERROR"),
    ]
    result = reconstruct(spans)
    node = next(n for n in result["nodes"] if n["id"] == "agent:kyc_compliance")
    assert node["errorCount"] == 1


def test_folded_error_with_no_real_ancestor_is_not_attributed_anywhere():
    """It must not be pinned on an unrelated node just to make it visible."""
    spans = [
        _span("s1", None, "rag_search", "TOOL"),
        _span("orphan", None, "ChatCompletion", "LLM", status="ERROR"),
    ]
    result = reconstruct(spans)
    assert result["nodes"][0]["errorCount"] == 0


def test_error_status_counted_on_the_node():
    spans = [
        _span("s1", None, "sanctions_check", "TOOL", status="OK"),
        _span("s2", None, "sanctions_check", "TOOL", status="ERROR"),
    ]
    result = reconstruct(spans)
    assert result["nodes"][0]["count"] == 2
    assert result["nodes"][0]["errorCount"] == 1


def test_latency_averaged_across_samples():
    spans = [
        _span("s1", None, "sanctions_check", "TOOL", start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:01Z"),
        _span("s2", None, "sanctions_check", "TOOL", start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:03Z"),
    ]
    result = reconstruct(spans)
    # 1000ms and 3000ms -> average 2000ms
    assert result["nodes"][0]["avgLatencyMs"] == 2000.0


def test_malformed_span_missing_context_does_not_raise():
    spans = [{"name": "sanctions_check", "span_kind": "TOOL", "parent_id": None}]
    result = reconstruct(spans)
    assert result["spanCount"] == 1
    assert len(result["nodes"]) == 1
    assert result["traceCount"] == 0


def test_non_dict_span_does_not_raise():
    result = reconstruct([None, "garbage", 42])
    assert result["spanCount"] == 3
    assert result["nodes"] == []
    assert result["edges"] == []


def test_self_referential_parent_does_not_create_self_edge():
    spans = [_span("s1", "s1", "sanctions_check", "TOOL")]
    result = reconstruct(spans)
    assert result["edges"] == []


def test_orphan_parent_id_pointing_nowhere_is_ignored():
    """A child span whose parent_id names a span not in this sample (e.g.
    the parent fell outside the page window) must not crash or fabricate
    an edge to a node that doesn't exist — nor a sequence edge, since there
    is no trace-mate to sequence against."""
    spans = [_span("s2", "does-not-exist", "sanctions_check", "TOOL")]
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1
    assert result["edges"] == []


def test_long_plumbing_chain_within_walk_limit_still_resolves():
    spans = [_span("root", None, "LangGraph", "CHAIN")]
    prev = "root"
    for i in range(10):
        spans.append(_span(f"p{i}", prev, f"_step_{i}", "CHAIN"))
        prev = f"p{i}"
    spans.append(_span("leaf", prev, "sanctions_check", "TOOL"))
    result = reconstruct(spans)
    assert len(result["nodes"]) == 1  # only the tool — everything else is plumbing
    assert result["edges"] == []
