"""governance/trace_kri.py: KRIs from Phoenix spans, and the attribute whitelist."""
from __future__ import annotations

import json

import pytest

from governance.trace_kri import is_truthy, kri_from_spans, percentile, slim_span


def _span(trace="t1", status="OK", kind="CHAIN", start="2026-09-18T10:00:00+00:00",
          end="2026-09-18T10:00:01+00:00", name="step", **attributes):
    return {
        "name": name, "span_kind": kind, "status_code": status, "start_time": start, "end_time": end,
        "context": {"trace_id": trace, "span_id": f"{trace}-{name}"}, "attributes": attributes,
    }


def test_empty_spans_give_zero_counts_and_no_rates():
    kri = kri_from_spans([])
    assert kri["span_count"] == 0
    assert kri["trace_count"] == 0
    assert kri["error_rate"] is None
    assert kri["p95_latency_ms"] is None
    assert kri["llm_calls"] == 0


def test_counts_spans_traces_errors_and_llm_calls():
    spans = [
        _span("t1", kind="LLM"), _span("t1", status="ERROR", name="classify"),
        _span("t2", kind="LLM"), _span("t2", status="ERROR", name="classify"),
        _span("t2", status="ERROR", name="extract"),
    ]
    kri = kri_from_spans(spans)
    assert kri["span_count"] == 5
    assert kri["trace_count"] == 2
    assert kri["error_spans"] == 3
    assert kri["error_rate"] == pytest.approx(0.6)
    assert kri["llm_calls"] == 2
    assert kri["worst_error_span"] == {"name": "classify", "errors": 2}


def test_span_kind_falls_back_to_openinference_attribute():
    spans = [_span(kind=None, **{"openinference.span.kind": "LLM"})]
    assert kri_from_spans(spans)["llm_calls"] == 1


@pytest.mark.parametrize("value,expected", [
    (True, True), ("true", True), ("TRUE", True), (1, True), ("1", True),
    (False, False), ("false", False), (0, False), (None, False), ("yes", False), (2, False),
])
def test_is_truthy(value, expected):
    assert is_truthy(value) is expected


def test_pii_and_injection_flags_count_spans_and_traces():
    spans = [
        _span("t1", **{"pii.detected": "true"}),
        _span("t1", **{"pii.detected": True}),
        _span("t2", **{"pii.detected": 1, "guardrail.injection_detected": "true"}),
        _span("t3", **{"pii.detected": "false", "guardrail.injection_detected": 0}),
    ]
    kri = kri_from_spans(spans)
    assert kri["pii_spans"] == 3
    assert kri["pii_traces"] == 2
    assert kri["injection_spans"] == 1
    assert kri["injection_traces"] == 1


def test_nested_attributes_are_read_too():
    spans = [_span(**{"pii": {"detected": True}, "guardrail": {"injection_detected": "true"}})]
    kri = kri_from_spans(spans)
    assert kri["pii_spans"] == 1
    assert kri["injection_spans"] == 1


def test_p95_latency_is_over_whole_traces():
    spans = []
    for i in range(20):
        # each trace: two spans, first 0-100ms, second 100ms-(200 + i*10)ms
        spans.append(_span(f"t{i}", start="2026-09-18T10:00:00.000+00:00", end="2026-09-18T10:00:00.100+00:00"))
        spans.append(_span(f"t{i}", start="2026-09-18T10:00:00.100+00:00",
                           end=f"2026-09-18T10:00:00.{200 + i * 10:03d}+00:00"))
    kri = kri_from_spans(spans)
    # durations 200..390ms; nearest-rank p95 of 20 values is the 19th = 380ms
    assert kri["p95_latency_ms"] == pytest.approx(380.0)


def test_unparseable_times_are_ignored_for_latency():
    kri = kri_from_spans([_span(start="not-a-time"), _span("t2", start=None)])
    assert kri["p95_latency_ms"] is None
    assert kri["span_count"] == 2


def test_percentile_nearest_rank():
    assert percentile([], 95) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([float(v) for v in range(1, 101)], 95) == 95.0


def test_slim_span_drops_prompt_and_output_text():
    span = _span(**{
        "input.value": "SECRET PROMPT", "output.value": "SECRET ANSWER",
        "llm.input_messages.0.message.content": "SECRET MESSAGE",
        "llm.output_messages.0.message.content": "SECRET REPLY",
        "llm": {"input_messages": [{"message": {"content": "SECRET NESTED"}}], "model_name": "gpt-4.1-mini"},
        "pii.detected": "true", "tool.name": "kyc_lookup",
    })
    slim = slim_span(span)
    dumped = json.dumps(slim)
    assert "SECRET" not in dumped
    assert slim["attributes"] == {"pii.detected": "true", "tool.name": "kyc_lookup", "llm.model_name": "gpt-4.1-mini"}
    assert slim["context"] == {"trace_id": "t1", "span_id": "t1-step"}
    assert kri_from_spans([slim])["pii_spans"] == 1
