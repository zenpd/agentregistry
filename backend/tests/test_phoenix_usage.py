"""telemetry/phoenix_usage.py (pure) and orchestrations/usage_ingestion.py
(against a temp DB with a fake Phoenix)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.base import Base, engine, get_db_session
from db.models import Agent, AgentTokenUsage, ModelAlias, ModelTokenPrice, Organization
from discovery.phoenix_client import PhoenixError
from orchestrations import usage_ingestion
from shared.config import get_settings
from telemetry.phoenix_usage import ATTRIBUTE_WHITELIST, aggregate_llm_spans, slim_span, token_counts

SECRET_TEXT = "customer passport number 123"


def span(start: str, *, trace="t1", kind="LLM", status="OK", end=None, **attributes) -> dict:
    """Shaped like a span from Phoenix's GET /v1/projects/{p}/spans."""
    return {
        "id": f"s-{start}-{trace}",
        "name": "ChatOpenAI",
        "context": {"trace_id": trace, "span_id": f"sp-{start}"},
        "span_kind": kind,
        "parent_id": None,
        "start_time": start,
        "end_time": end or start,
        "status_code": status,
        "status_message": "",
        "attributes": {
            "openinference.span.kind": kind,
            "input.value": SECRET_TEXT,
            "output.value": SECRET_TEXT,
            "llm.input_messages.0.message.content": SECRET_TEXT,
            "llm.output_messages.0.message.content": SECRET_TEXT,
            "llm.system": "openai",
            **{k.replace("__", "."): v for k, v in attributes.items()},
        },
        "events": [],
    }


def openai_span(start, prompt, completion, cached=None, **kw):
    attrs = {"llm__model_name": "gpt-4.1-mini-2025-04-14", "llm__token_count__prompt": prompt,
             "llm__token_count__completion": completion, "llm__token_count__total": prompt + completion}
    if cached is not None:
        attrs["llm__token_count__prompt_details__cache_read"] = cached
    return span(start, **attrs, **kw)


def langchain_span(start, prompt, completion, **kw):
    return span(start, llm__model_name="gpt-4.1-mini", metadata__ls_model_name="gpt-4.1-mini",
                llm__token_count__prompt=prompt, llm__token_count__completion=completion, **kw)


# ── Pure aggregation ─────────────────────────────────────────────────────────

def test_slim_span_keeps_only_whitelisted_attributes():
    slim = slim_span(openai_span("2026-09-17T10:00:00+00:00", 100, 20, cached=50))
    assert set(slim["attributes"]) <= ATTRIBUTE_WHITELIST
    assert SECRET_TEXT not in repr(slim)
    assert slim["context"] == {"trace_id": "t1"}


def test_aggregates_per_utc_day_and_raw_model():
    spans = [
        openai_span("2026-09-17T10:00:00.000000+00:00", 1000, 200, cached=400, trace="a",
                    end="2026-09-17T10:00:01.500000+00:00"),
        openai_span("2026-09-17T11:00:00+00:00", 500, 100, trace="a", status="ERROR",
                    end="2026-09-17T11:00:00.500000+00:00"),
        langchain_span("2026-09-17T12:00:00Z", 300, 30, trace="b"),
        # 01:00 at +05:30 is still the previous UTC day.
        langchain_span("2026-09-18T01:00:00+05:30", 10, 1, trace="c"),
        span("2026-09-17T10:00:00+00:00", kind="CHAIN", llm__token_count__prompt=999),
    ]
    rows = aggregate_llm_spans(spans)
    by_key = {(r["day"], r["model"]): r for r in rows}
    assert set(by_key) == {(date(2026, 9, 17), "gpt-4.1-mini-2025-04-14"), (date(2026, 9, 17), "gpt-4.1-mini")}
    raw = by_key[(date(2026, 9, 17), "gpt-4.1-mini-2025-04-14")]
    assert (raw["input_tokens"], raw["output_tokens"], raw["cached_tokens"]) == (1500, 300, 400)
    assert (raw["calls"], raw["runs"], raw["errors"]) == (2, 1, 1)
    assert raw["latency_avg_ms"] == 1000.0
    lc = by_key[(date(2026, 9, 17), "gpt-4.1-mini")]
    assert (lc["input_tokens"], lc["calls"], lc["runs"]) == (310, 2, 2)


def test_normalize_merges_model_name_variants():
    spans = [openai_span("2026-09-17T10:00:00+00:00", 100, 10, trace="a"),
             langchain_span("2026-09-17T11:00:00+00:00", 50, 5, trace="b")]
    rows = aggregate_llm_spans(spans, normalize=lambda raw: raw.lower().replace("-2025-04-14", ""))
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4.1-mini"
    assert rows[0]["raw_model_names"] == ["gpt-4.1-mini", "gpt-4.1-mini-2025-04-14"]
    assert (rows[0]["input_tokens"], rows[0]["calls"], rows[0]["runs"]) == (150, 2, 2)


def test_model_name_fallbacks():
    only_meta = span("2026-09-17T10:00:00+00:00", metadata__ls_model_name="gpt-4o")
    only_llm_model = span("2026-09-17T10:00:00+00:00", llm__model="gpt-4.1")
    nothing = span("2026-09-17T10:00:00+00:00")
    assert [r["model"] for r in aggregate_llm_spans([only_meta, only_llm_model, nothing])] == ["gpt-4.1", "gpt-4o", "unknown"]


@pytest.mark.parametrize("attrs,expected", [
    ({}, (0, 0, 0)),
    ({"llm.token_count.total": 120}, (120, 0, 0)),
    ({"llm.token_count.prompt": "100", "llm.token_count.completion": 20.0}, (100, 20, 0)),
    ({"llm.token_count.completion": 20, "llm.token_count.total": 120}, (100, 20, 0)),
    ({"llm.token_count.prompt": 100, "llm.token_count.total": 130}, (100, 30, 0)),
    ({"llm.token_count.prompt": 100, "llm.token_count.completion": None,
      "llm.token_count.prompt_details.cache_read": 64}, (100, 0, 64)),
    ({"llm.token_count.prompt": "n/a", "llm.token_count.completion": -5}, (0, 0, 0)),
])
def test_token_counts_handle_missing_values(attrs, expected):
    assert token_counts(attrs) == expected


def test_spans_without_start_time_or_span_kind_are_skipped():
    no_time = openai_span("", 10, 1)
    kind_only_in_attributes = openai_span("2026-09-17T10:00:00+00:00", 10, 1)
    kind_only_in_attributes["span_kind"] = None
    rows = aggregate_llm_spans([no_time, kind_only_in_attributes])
    assert [r["calls"] for r in rows] == [1]


# ── Ingestion against a temp DB ──────────────────────────────────────────────

NOW = datetime(2026, 9, 18, 9, 30, tzinfo=timezone.utc)


class FakePhoenix:
    """Stands in for discovery.phoenix_client.PhoenixClient."""
    spans_by_project: dict[str, list[dict]] = {}
    error: PhoenixError | None = None
    requests: list[dict] = []

    def __init__(self, base_url, *, api_key=None, timeout=None):
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def spans(self, project, limit=100, max_pages=5, *, start_time=None, end_time=None, span_kind=None):
        FakePhoenix.requests.append({"project": project, "start_time": start_time, "end_time": end_time,
                                     "span_kind": span_kind, "limit": limit, "max_pages": max_pages})
        if FakePhoenix.error:
            raise FakePhoenix.error
        start, end = datetime.fromisoformat(start_time), datetime.fromisoformat(end_time)
        matching = [s for s in FakePhoenix.spans_by_project.get(project, [])
                    if start <= datetime.fromisoformat(s["start_time"]) <= end
                    and (span_kind is None or s["span_kind"] == span_kind)]
        for s in sorted(matching, key=lambda s: s["start_time"], reverse=True)[: limit * max_pages]:
            yield s


@pytest_asyncio.fixture
async def db(monkeypatch):
    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    import db.models  # noqa: F401

    FakePhoenix.spans_by_project, FakePhoenix.error, FakePhoenix.requests = {}, None, []
    monkeypatch.setattr(usage_ingestion, "PhoenixClient", FakePhoenix)
    monkeypatch.setattr(usage_ingestion, "_utcnow", lambda: NOW)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="linked", org_id="org-default", name="Linked", slug="linked", owner="o",
                        model_name="GPT-4.1-mini", phoenix_project="proj", phoenix_endpoint="http://phoenix.test"))
            s.add(Agent(id="unlinked", org_id="org-default", name="Unlinked", slug="unlinked", owner="o"))
            s.add(ModelTokenPrice(id="p1", model_name="gpt-4.1-mini", provider="azure-openai", input_price_per_1m=0.40,
                                  output_price_per_1m=1.60, cache_read_price_per_1m=0.10, tier="lightweight"))
            s.add(ModelAlias(alias="gpt-4.1-mini-2025-04-14", model_name="gpt-4.1-mini"))
            s.add(AgentTokenUsage(agent_id="unlinked", bucket=datetime(2026, 9, 3, 2, 28), model_name="GPT-5",
                                  invocation_count=10, input_tokens=100, source="seed"))
        yield
    finally:
        await engine.dispose()


async def _usage_rows(agent_id="linked"):
    async with get_db_session() as s:
        rows = (await s.execute(select(AgentTokenUsage).where(AgentTokenUsage.agent_id == agent_id))).scalars().all()
    return sorted(rows, key=lambda r: (r.bucket, r.model_name))


def _day_spans(day: date, calls: int, prompt=1_000_000, completion=0):
    at = datetime.combine(day, time(6), tzinfo=timezone.utc)
    return [openai_span((at + timedelta(minutes=i)).isoformat(), prompt, completion, trace=f"{day}-{i // 2}")
            for i in range(calls)]


@pytest.mark.asyncio
async def test_first_run_backfills_and_rerun_replaces_instead_of_adding(db):
    today, old = NOW.date(), NOW.date() - timedelta(days=20)
    FakePhoenix.spans_by_project["proj"] = _day_spans(today, 3) + _day_spans(old, 2) + [langchain_span(
        datetime.combine(today, time(8), tzinfo=timezone.utc).isoformat(), 1_000_000, 0, trace="lc")]

    first = await usage_ingestion.ingest_usage(agent_id="linked")
    assert first["status"] == "ok"
    agent = first["agents"][0]
    assert (agent["days"], agent["rows"], agent["calls"], agent["status"]) == (30, 2, 6, "ok")
    assert FakePhoenix.requests[0]["span_kind"] == "LLM" and FakePhoenix.requests[0]["limit"] == 1000
    assert FakePhoenix.requests[0]["start_time"].startswith((today - timedelta(days=29)).isoformat())

    rows = await _usage_rows()
    assert [(r.bucket.date(), r.model_name, r.invocation_count) for r in rows] == [(old, "gpt-4.1-mini", 2), (today, "gpt-4.1-mini", 4)]
    latest = rows[1]
    assert latest.source == "phoenix" and latest.run_count == 3
    assert latest.raw_model_names == ["gpt-4.1-mini", "gpt-4.1-mini-2025-04-14"]
    assert latest.input_tokens == 4_000_000 and latest.cost_cents == 160  # 4M × $0.40
    assert (latest.bucket.hour, latest.bucket.minute) == (0, 0)
    assert SECRET_TEXT not in repr([(r.raw_model_names, r.model_name) for r in rows])

    second = await usage_ingestion.ingest_usage(agent_id="linked")
    assert second["agents"][0]["days"] == usage_ingestion.INCREMENTAL_DAYS
    assert [(r.bucket.date(), r.invocation_count) for r in await _usage_rows()] == [(old, 2), (today, 4)]


@pytest.mark.asyncio
async def test_rerun_drops_a_model_no_longer_seen_on_a_reread_day_but_keeps_older_days(db):
    today = NOW.date()
    FakePhoenix.spans_by_project["proj"] = _day_spans(today, 1) + _day_spans(today - timedelta(days=10), 1)
    await usage_ingestion.ingest_usage(agent_id="linked")
    async with get_db_session() as s:
        s.add(AgentTokenUsage(agent_id="linked", bucket=datetime.combine(today, time.min), model_name="stale-name",
                              invocation_count=7, source="phoenix"))
    FakePhoenix.spans_by_project["proj"] = _day_spans(today, 2)  # older spans purged by Phoenix retention
    await usage_ingestion.ingest_usage(agent_id="linked", days=30)
    assert [(r.bucket.date(), r.model_name, r.invocation_count) for r in await _usage_rows()] == [
        (today - timedelta(days=10), "gpt-4.1-mini", 1), (today, "gpt-4.1-mini", 2)]


@pytest.mark.asyncio
async def test_unreachable_phoenix_is_reported_not_raised(db):
    FakePhoenix.error = PhoenixError("GET", "http://phoenix.test/v1/projects/proj/spans", 0, "timed out")
    result = await usage_ingestion.ingest_usage(agent_id="linked")
    assert result["status"] == "error"
    assert result["agents"][0]["status"] == "unreachable"
    assert await _usage_rows() == []

    FakePhoenix.error = PhoenixError("GET", "http://phoenix.test/v1/projects/proj/spans", 401, "no")
    assert (await usage_ingestion.ingest_usage(agent_id="linked"))["agents"][0]["status"] == "auth_failed"


@pytest.mark.asyncio
async def test_unlinked_or_missing_agent_is_skipped_or_error(db):
    skipped = await usage_ingestion.ingest_usage(agent_id="unlinked")
    assert skipped["status"] == "skipped" and "No Phoenix project" in skipped["reason"]
    assert (await usage_ingestion.ingest_usage(agent_id="nope"))["status"] == "error"
    everyone = await usage_ingestion.ingest_usage()
    assert [a["agent_id"] for a in everyone["agents"]] == ["linked"]
    assert everyone["agents"][0]["reason"] == "No LLM spans in the last 30 days."
    assert [r.source for r in await _usage_rows("unlinked")] == ["seed"]


@pytest.mark.asyncio
async def test_truncated_read_keeps_the_partly_read_oldest_day(db, monkeypatch):
    monkeypatch.setattr(usage_ingestion, "PAGE_LIMIT", 2)
    monkeypatch.setattr(usage_ingestion, "MAX_PAGES", 2)
    today = NOW.date()
    FakePhoenix.spans_by_project["proj"] = _day_spans(today, 3) + _day_spans(today - timedelta(days=1), 3)
    result = await usage_ingestion.ingest_usage(agent_id="linked")
    agent = result["agents"][0]
    assert (result["status"], agent["status"], agent["truncated"]) == ("partial", "partial", True)
    assert [(r.bucket.date(), r.invocation_count) for r in await _usage_rows()] == [(today, 3)]


def test_overall_status():
    assert usage_ingestion.overall_status([]) == "skipped"
    assert usage_ingestion.overall_status(["ok", "ok"]) == "ok"
    assert usage_ingestion.overall_status(["ok", "unreachable"]) == "partial"
    assert usage_ingestion.overall_status(["ok", "partial"]) == "partial"
    assert usage_ingestion.overall_status(["unreachable", "auth_failed"]) == "error"
