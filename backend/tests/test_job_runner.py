"""Job runner, run lock, scheduler loop and the jobs router, against a temp DB."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import anyio
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from db.base import Base, engine, get_db_session
from db.models import Agent, AuditLog, JobRun, Organization
from orchestrations import job_runner, scheduler
from shared.config import get_settings


def _assert_throwaway_db() -> None:
    url = get_settings().database_url
    assert url.startswith("sqlite"), f"tests must use a throwaway SQLite DB, not {url.split(':', 1)[0]}"
    path = os.path.realpath(url.split(":///", 1)[-1])
    roots = {os.path.realpath(p) for p in ("/tmp", tempfile.gettempdir())}
    assert any(path.startswith(root + os.sep) for root in roots), "the test DB must live under a temp directory"


@pytest_asyncio.fixture
async def db():
    _assert_throwaway_db()
    import db.models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="agent-a", org_id="org-default", name="Agent A", slug="agent-a", owner="Ops"))
        yield
    finally:
        await engine.dispose()


class Calls(list):
    """Records (job, agent_id, trigger, kwargs) for every fake job call."""

    def __init__(self, monkeypatch):
        super().__init__()
        self._mp = monkeypatch
        for name in list(job_runner.JOBS):
            self.set(name)

    def set(self, name, result=None, exc=None):
        async def fn(agent_id=None, trigger="manual", **kwargs):
            self.append((name, agent_id, trigger, kwargs))
            if exc:
                raise exc
            return {"status": "ok"} if result is None else result

        self._mp.setitem(job_runner.JOBS, name, replace(job_runner.JOBS[name], target=fn))


@pytest.fixture
def calls(monkeypatch):
    return Calls(monkeypatch)


def _use(monkeypatch, job, fn):
    monkeypatch.setitem(job_runner.JOBS, job, replace(job_runner.JOBS[job], target=fn))


async def _rows(job=None):
    async with get_db_session() as s:
        stmt = select(JobRun).order_by(JobRun.started_at)
        if job:
            stmt = stmt.where(JobRun.job == job)
        return list((await s.execute(stmt)).scalars().all())


async def _insert_running(job, agent_id, minutes_ago, trigger="manual", summary=None):
    async with get_db_session() as s:
        s.add(JobRun(id=f"held-{job}-{minutes_ago}", job=job, agent_id=agent_id, trigger=trigger,
                     status="running", summary=summary or {},
                     started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))


# ── run_job ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_job_records_success(db, calls):
    calls.set("usage_ingestion", result={"status": "ok", "agents": 1, "rows_upserted": 12})
    result = await job_runner.run_job("usage_ingestion", agent_id="agent-a", days=7)

    assert result["status"] == "ok" and result["locked"] is False
    assert result["summary"] == {"agents": 1, "rows_upserted": 12}
    assert calls == [("usage_ingestion", "agent-a", "manual", {"days": 7})]
    [row] = await _rows()
    assert (row.status, row.agent_id, row.trigger) == ("ok", "agent-a", "manual")
    assert row.finished_at is not None and row.error is None
    assert result["startedAt"].endswith("+00:00")


@pytest.mark.asyncio
async def test_unknown_job_raises(db):
    with pytest.raises(ValueError, match="Unknown job"):
        await job_runner.run_job("nope")
    assert await _rows() == []


@pytest.mark.asyncio
async def test_job_exception_is_captured_without_secrets(db, calls):
    calls.set("risk_scan", exc=RuntimeError("boom calling https://x/api?api_key=sk-live-123 Bearer abc.def"))
    result = await job_runner.run_job("risk_scan", agent_id="agent-a")

    assert result["status"] == "error"
    assert result["error"].startswith("RuntimeError: boom")
    assert "sk-live-123" not in result["error"] and "abc.def" not in result["error"]
    [row] = await _rows()
    assert row.status == "error" and row.error == result["error"]


@pytest.mark.asyncio
async def test_non_dict_result_is_an_error(db, calls):
    calls.set("cost_rollup", result=["not", "a", "dict"])
    result = await job_runner.run_job("cost_rollup")
    assert result["status"] == "error" and "without a 'status'" in result["error"]


@pytest.mark.asyncio
async def test_status_outside_the_contract_is_an_error(db, calls):
    calls.set("risk_scan", result={"status": "running", "reason": "confused job"})
    result = await job_runner.run_job("risk_scan", agent_id="agent-a")

    assert result["status"] == "error" and result["finishedAt"]
    assert result["summary"] == {"reason": "confused job", "jobStatus": "running"}
    # Not left holding the lock.
    assert (await job_runner.run_job("risk_scan", agent_id="agent-a"))["status"] == "error"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_missing_module_is_unavailable(db, monkeypatch):
    _use(monkeypatch, "governance_checks", "orchestrations.does_not_exist:run")
    available, reason = job_runner.availability(job_runner.JOBS["governance_checks"])
    assert available is False and "ModuleNotFoundError" in reason

    result = await job_runner.run_job("governance_checks")
    assert result["status"] == "unavailable"
    assert "ModuleNotFoundError" in result["error"] and "<frozen" not in result["error"]
    [row] = await _rows()
    assert row.status == "unavailable"


@pytest.mark.asyncio
async def test_module_that_fails_to_import_is_unavailable(db, monkeypatch, tmp_path):
    (tmp_path / "ar_half_written_job.py").write_text("def run(:\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    _use(monkeypatch, "cost_rollup", "ar_half_written_job:run")

    available, reason = job_runner.availability(job_runner.JOBS["cost_rollup"])
    assert available is False and reason.startswith("SyntaxError")
    result = await job_runner.run_job("cost_rollup", agent_id="agent-a")
    assert result["status"] == "unavailable" and result["error"].startswith("SyntaxError")


@pytest.mark.asyncio
async def test_passthrough_statuses_and_sanitised_summary(db, calls):
    calls.set("infra_costs", result={
        "status": "not_configured", "reason": "No AZURE_COST_SCOPE",
        "items": list(range(1500)), "as_of": datetime(2026, 9, 1, 12, 0), "day": date(2026, 9, 1),
        "api_key": "should-not-be-stored", "input.value": "prompt text",
        "detail": "GET https://cost.example/query?code=s3cr3t failed",
    })
    result = await job_runner.run_job("infra_costs")
    summary = result["summary"]
    assert result["status"] == "not_configured"
    assert len(summary["items"]) == job_runner.MAX_ITEMS_STORED and summary["items_total"] == 1500
    assert summary["as_of"] == "2026-09-01T12:00:00+00:00" and summary["day"] == "2026-09-01"
    assert summary["api_key"] == "[redacted]" and summary["input.value"] == "[redacted]"
    assert "s3cr3t" not in summary["detail"]

    [row] = await _rows()
    shown = job_runner.run_to_dict(row)["summary"]
    assert len(shown["items"]) == job_runner.MAX_ITEMS_SHOWN and shown["items_total"] == 1500


@pytest.mark.asyncio
async def test_non_finite_numbers_are_stored_as_null(db, calls):
    calls.set("cost_rollup", result={
        "status": "ok", "cost": Decimal("NaN"), "total": Decimal("Infinity"), "huge": Decimal("1e400"),
        "series": [[float("inf"), 1.5, Decimal("2.25")], {"x": float("nan")}],
    })
    result = await job_runner.run_job("cost_rollup", agent_id="agent-a")

    expected = {"cost": None, "total": None, "huge": None, "series": [[None, 1.5, 2.25], {"x": None}]}
    assert result["status"] == "ok" and result["summary"] == expected
    [row] = await _rows()
    assert row.summary == expected
    json.dumps(job_runner.run_to_dict(row), allow_nan=False)


def test_rows_written_by_older_code_are_sanitised_on_read():
    row = JobRun(id="old", job="cost_rollup", agent_id=None, trigger="manual", status="ok",
                 started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                 summary={"cost": float("nan"), "note": "token: abc123"}, error="refresh_token=r-1 failed")
    out = job_runner.run_to_dict(row)
    assert out["summary"] == {"cost": None, "note": "token: ***"} and out["error"] == "refresh_token=*** failed"
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize("text, secret", [
    ("GET https://x/cb?access_token=eyJabc.def", "eyJabc.def"),
    ("refresh_token=r-123", "r-123"),
    ("token: abc123", "abc123"),
    ("AccountKey=Zm9vYmFy==;EndpointSuffix=core.windows.net", "Zm9vYmFy"),
    ("Endpoint=sb://x/;SharedAccessKeyName=root;SharedAccessKey=c2FzLWtleQ=", "c2FzLWtleQ"),
    ("subscription-key=SUBKEY1", "SUBKEY1"),
    ("Ocp-Apim-Subscription-Key: SUBKEY2", "SUBKEY2"),
    ("headers={'api-key': 'AZKEY'}", "AZKEY"),
    ('{"client_secret": "cs 1"}', "cs 1"),
    ("https://maps.example/x?key=QKEY&z=1", "QKEY"),
    ("https://acct.blob.core.windows.net/c?sv=2022&sig=abc%2Bdef&se=1", "abc%2Bdef"),
    ("failed with sk-proj-abcdefghijklmnopqrstu", "abcdefghijklmnopqrstu"),
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ("https://user:pa55@host/x", "pa55"),
])
def test_redact_hides_secret_shapes(text, secret):
    assert secret not in job_runner.redact(text)


def test_redact_keeps_ordinary_text():
    text = "HTTP error code: 403; status_code=500 input_tokens=500 max_tokens: 100; No LLM spans in 30 days."
    assert job_runner.redact(text) == text


def test_sensitive_keys_are_blanked_but_counts_kept():
    out = job_runner.jsonable({
        "openai_api_key": "k", "azureApiKey": "k", "connection_string": "c", "refresh_token": "r", "token": "t",
        "sas": "s", "prompt": "p", "completion": "c", "messages": [{"role": "user", "content": "hi"}],
        "attributes.input.value": "v", "llm.prompts": ["p"], "llm.output_messages.0.message.content": "o",
        "prompt_tokens": 12, "completion_tokens": 3, "input_tokens": 5, "tokens_by_model": {"gpt-4.1": 9},
        "tagKey": "agent-id", "traceSignals": "ok", "reason": "fine",
    })
    blanked = {k for k, v in out.items() if v == "[redacted]"}
    assert blanked == {"openai_api_key", "azureApiKey", "connection_string", "refresh_token", "token", "sas",
                       "prompt", "completion", "messages", "attributes.input.value", "llm.prompts",
                       "llm.output_messages.0.message.content"}
    assert out["prompt_tokens"] == 12 and out["tokens_by_model"] == {"gpt-4.1": 9} and out["tagKey"] == "agent-id"


def test_dicts_are_capped_and_existing_total_keys_win():
    out = job_runner.jsonable({"agents": {f"a{i}": i for i in range(80)}, "items": list(range(60)),
                               "items_total": "orig"}, max_items=50)
    assert len(out["agents"]) == 50 and out["agents_total"] == 80
    assert len(out["items"]) == 50 and out["items_total"] == "orig"


@pytest.mark.asyncio
async def test_oversized_summary_is_bounded(db, calls, monkeypatch):
    monkeypatch.setattr(job_runner, "MAX_SUMMARY_BYTES", 2000)
    calls.set("risk_scan", result={"status": "ok", "agentCount": 900, "reason": "done",
                                   "agents": {f"agent-{i}": {"kri": {"x": i}} for i in range(900)}})
    result = await job_runner.run_job("risk_scan")
    assert result["summary"]["agentCount"] == 900 and "agents" not in result["summary"]
    assert "nested details were dropped" in result["summary"]["truncated"]


# ── run lock ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fresh_running_row_blocks_same_job_and_agent(db, calls):
    await _insert_running("usage_ingestion", "agent-a", minutes_ago=5)
    result = await job_runner.run_job("usage_ingestion", agent_id="agent-a")

    assert result["status"] == "skipped" and result["locked"] is True
    assert "held-usage_ingestion-5" in result["reason"]
    assert calls == []
    assert len(await _rows()) == 1  # the refused attempt leaves no row


@pytest.mark.asyncio
async def test_all_agents_and_per_agent_runs_exclude_each_other(db, calls):
    await _insert_running("cost_rollup", "agent-a", minutes_ago=5)
    assert (await job_runner.run_job("cost_rollup", agent_id="agent-b"))["status"] == "ok"
    blocked = await job_runner.run_job("cost_rollup", trigger="scheduled")
    assert blocked["status"] == "skipped" and "for agent agent-a" in blocked["reason"]

    await _insert_running("risk_scan", None, minutes_ago=5, trigger="scheduled")
    blocked = await job_runner.run_job("risk_scan", agent_id="agent-a")
    assert blocked["status"] == "skipped" and "for all agents" in blocked["reason"]
    assert [c[:2] for c in calls] == [("cost_rollup", "agent-b")]


@pytest.mark.asyncio
async def test_old_running_row_is_marked_stale(db, calls):
    await _insert_running("cost_rollup", "agent-a", minutes_ago=45)
    result = await job_runner.run_job("cost_rollup", agent_id="agent-a")

    assert result["status"] == "ok"
    rows = {r.id: r for r in await _rows()}
    stale = rows["held-cost_rollup-45"]
    assert stale.status == "stale" and stale.finished_at is not None and "30 min" in stale.error


@pytest.mark.asyncio
async def test_recent_heartbeat_keeps_an_old_run_locked(db, calls):
    beat = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    await _insert_running("usage_ingestion", None, minutes_ago=90, summary={"heartbeatAt": beat})
    result = await job_runner.run_job("usage_ingestion")
    assert result["status"] == "skipped" and calls == []
    assert (await _rows())[0].status == "running"


@pytest.mark.asyncio
async def test_long_run_writes_heartbeats_then_its_result(db, monkeypatch):
    monkeypatch.setattr(job_runner, "HEARTBEAT_SECONDS", 0.05)
    seen = []

    async def slow(agent_id=None, trigger="manual", **kwargs):
        for _ in range(4):
            await asyncio.sleep(0.06)
            seen.append(dict((await _rows())[0].summary))
        return {"status": "ok", "rows": 3}

    _use(monkeypatch, "usage_ingestion", slow)
    result = await job_runner.run_job("usage_ingestion")
    assert any("heartbeatAt" in s for s in seen)
    assert result["summary"] == {"rows": 3}
    await asyncio.sleep(0.15)  # a late beat must not overwrite the final summary
    assert (await _rows())[0].summary == {"rows": 3}


@pytest.mark.asyncio
async def test_concurrent_runs_exactly_one_executes(db, monkeypatch):
    started, release = [], asyncio.Event()

    async def held(agent_id=None, trigger="manual", **kwargs):
        started.append(agent_id)
        await release.wait()
        return {"status": "ok"}

    jitter = iter([0.05, 0.2, 0.35, 0.5, 0.65, 0.8])
    monkeypatch.setattr(job_runner.random, "uniform", lambda a, b: next(jitter))
    _use(monkeypatch, "risk_scan", held)
    tasks = [asyncio.create_task(job_runner.run_job("risk_scan", agent_id="agent-a")) for _ in range(3)]
    for _ in range(100):
        if sum(t.done() for t in tasks) == 2:
            break
        await asyncio.sleep(0.05)

    assert started == ["agent-a"]
    release.set()
    results = await asyncio.gather(*tasks)
    assert sorted(r["status"] for r in results) == ["ok", "skipped", "skipped"]
    assert (await job_runner.run_job("risk_scan", agent_id="agent-a"))["status"] == "ok"


@pytest.mark.asyncio
async def test_cancelled_run_is_recorded_as_cancelled(db, monkeypatch):
    async def forever(agent_id=None, trigger="manual", **kwargs):
        await asyncio.sleep(60)

    _use(monkeypatch, "risk_scan", forever)
    task = asyncio.create_task(job_runner.run_job("risk_scan", agent_id="agent-a"))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    [row] = await _rows()
    assert row.status == "cancelled" and row.finished_at is not None


@pytest.mark.asyncio
async def test_anyio_cancel_scope_still_records_the_run(db, monkeypatch):
    async def forever(agent_id=None, trigger="manual", **kwargs):
        await asyncio.sleep(60)

    _use(monkeypatch, "risk_scan", forever)
    with anyio.move_on_after(0.3):
        await job_runner.run_job("risk_scan", agent_id="agent-a")
    [row] = await _rows()
    assert row.status == "cancelled" and row.finished_at is not None


# ── refresh_agent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_agent_runs_chain_in_order(db, calls):
    calls.set("cost_rollup", result={"status": "not_configured"})
    result = await job_runner.refresh_agent("agent-a")

    assert [c[0] for c in calls] == ["usage_ingestion", "cost_rollup", "risk_scan", "governance_checks"]
    assert all(c[1] == "agent-a" for c in calls)
    assert [r["status"] for r in result["results"]] == ["ok", "not_configured", "ok", "ok"]
    assert result["status"] == "partial"
    [lock] = await _rows("refresh")
    assert lock.status == "partial" and lock.summary["steps"]["cost_rollup"]["status"] == "not_configured"
    assert len(await _rows()) == 5


@pytest.mark.asyncio
async def test_refresh_agent_continues_after_a_failure(db, calls):
    calls.set("usage_ingestion", exc=ConnectionError("phoenix down"))
    result = await job_runner.refresh_agent("agent-a")
    assert [r["status"] for r in result["results"]] == ["error", "ok", "ok", "ok"]
    assert result["status"] == "partial"


@pytest.mark.asyncio
async def test_refresh_agent_refused_while_another_refresh_runs(db, calls):
    await _insert_running("refresh", "agent-a", minutes_ago=1)
    result = await job_runner.refresh_agent("agent-a")
    assert result["status"] == "skipped" and result["locked"] and result["results"] == [] and calls == []


@pytest.mark.asyncio
async def test_refresh_step_held_elsewhere_makes_it_partial(db, calls):
    await _insert_running("risk_scan", "agent-a", minutes_ago=1)
    result = await job_runner.refresh_agent("agent-a")
    by_job = {r["job"]: r for r in result["results"]}
    assert by_job["risk_scan"]["status"] == "skipped" and by_job["risk_scan"]["locked"]
    assert result["status"] == "partial"
    assert [c[0] for c in calls] == ["usage_ingestion", "cost_rollup", "governance_checks"]


def test_overall_status():
    assert job_runner.overall_status(["ok", "skipped"]) == "ok"
    assert job_runner.overall_status(["error", "unavailable"]) == "error"
    assert job_runner.overall_status(["ok", "unreachable"]) == "partial"
    assert job_runner.overall_status(["unreachable", "error"]) == "error"
    assert job_runner.overall_status(["ok", "not_configured"]) == "partial"
    assert job_runner.overall_status(["not_configured"] * 4) == "error"
    assert job_runner.overall_status([]) == "skipped"


# ── scheduler ────────────────────────────────────────────────────────────────

def _utc(h, m=0):
    return datetime(2026, 9, 17, h, m, tzinfo=timezone.utc)


def test_due_jobs_and_next_wake():
    assert scheduler.due_jobs(_utc(0, 30)) == []
    assert scheduler.due_jobs(_utc(2, 0)) == ["usage_ingestion", "infra_costs", "cost_rollup"]
    assert scheduler.next_wake(_utc(0, 30)) == _utc(1, 0)
    assert scheduler.next_wake(_utc(1, 0)) == _utc(1, 30)
    assert scheduler.next_wake(_utc(3, 0)) == _utc(1, 0) + timedelta(days=1)


@pytest.mark.asyncio
async def test_run_due_jobs_runs_each_job_once_per_day(db, calls):
    now = datetime.now(timezone.utc).replace(hour=2, minute=15)

    first = await scheduler.run_due_jobs(now)
    assert [r["job"] for r in first] == ["usage_ingestion", "infra_costs", "cost_rollup"]
    assert all(r["trigger"] == "scheduled" and r["agentId"] is None for r in first)

    assert await scheduler.run_due_jobs(now) == []
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_scheduled_runs_that_did_no_work_are_retried_same_day(db):
    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_db_session() as s:
        for job, status in [("usage_ingestion", "stale"), ("cost_rollup", "cancelled"),
                            ("risk_scan", "error"), ("infra_costs", "not_configured")]:
            s.add(JobRun(id=f"old-{job}", job=job, agent_id=None, trigger="scheduled", status=status,
                         summary={}, started_at=day))
        s.add(JobRun(id="manual", job="governance_checks", agent_id=None, trigger="manual", status="ok",
                     summary={}, started_at=day))
    done = await job_runner.scheduled_jobs_done_on(day, now)
    assert done == {"risk_scan", "infra_costs"}


@pytest.mark.asyncio
async def test_running_scheduled_rows_count_as_done_only_while_live(db):
    now = datetime.now(timezone.utc).replace(hour=12)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_db_session() as s:
        s.add(JobRun(id="dead", job="usage_ingestion", agent_id=None, trigger="scheduled", status="running",
                     summary={}, started_at=now - timedelta(minutes=45)))
        s.add(JobRun(id="live", job="cost_rollup", agent_id=None, trigger="scheduled", status="running",
                     summary={}, started_at=now - timedelta(minutes=5)))
    assert await job_runner.scheduled_jobs_done_on(day, now) == {"cost_rollup"}


@pytest.mark.asyncio
async def test_scheduler_disabled_starts_nothing(monkeypatch):
    monkeypatch.setattr(get_settings(), "scheduler_enabled", False)
    scheduler.start_scheduler()
    assert scheduler.scheduler_status()["running"] is False
    await scheduler.stop_scheduler()


def _fast_scheduler(monkeypatch):
    for name, spec in list(job_runner.JOBS.items()):
        monkeypatch.setitem(job_runner.JOBS, name, replace(spec, daily_at=time(0, 0)))
    monkeypatch.setattr(get_settings(), "scheduler_enabled", True)
    monkeypatch.setattr(scheduler, "MAX_JITTER_SECONDS", 0.0)
    monkeypatch.setattr(scheduler, "MIN_SLEEP_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "MAX_SLEEP_SECONDS", 0.05)
    monkeypatch.setattr(scheduler, "ERROR_RETRY_SECONDS", 0.01)


async def _wait_for(predicate, seconds=5.0):
    for _ in range(int(seconds / 0.05)):
        if predicate():
            return
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_scheduler_loop_runs_due_jobs_and_stops_cleanly(db, calls, monkeypatch):
    _fast_scheduler(monkeypatch)
    scheduler.start_scheduler()
    try:
        await _wait_for(lambda: len(calls) >= len(job_runner.JOBS))
        await asyncio.sleep(0.2)  # several more ticks: nothing may run twice
        status = scheduler.scheduler_status()
        assert status["enabled"] and status["running"] and status["nextRunAt"]
    finally:
        await scheduler.stop_scheduler()

    assert [c[0] for c in calls] == list(job_runner.JOBS)
    assert scheduler.scheduler_status()["running"] is False


@pytest.mark.asyncio
async def test_scheduler_loop_survives_a_failing_tick(db, calls, monkeypatch):
    _fast_scheduler(monkeypatch)
    real_next_wake, failures = scheduler.next_wake, []

    def flaky(now):
        if not failures:
            failures.append(now)
            raise RuntimeError("clock trouble")
        return real_next_wake(now)

    monkeypatch.setattr(scheduler, "next_wake", flaky)
    scheduler.start_scheduler()
    try:
        await _wait_for(lambda: scheduler.scheduler_status()["nextRunAt"] is not None)
        assert failures and scheduler.scheduler_status()["running"]
    finally:
        await scheduler.stop_scheduler()


# ── router ───────────────────────────────────────────────────────────────────

def _app(user=None) -> FastAPI:
    from api.auth import require_read, require_update
    from api.routers.ops.jobs import router

    app = FastAPI()
    app.include_router(router)
    if user is not None:
        for dep in (require_read, require_update):
            app.dependency_overrides[dep] = lambda: user
    return app


@pytest_asyncio.fixture
async def client():
    app = _app({"user_id": "tester", "role": "admin"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _audit_rows():
    async with get_db_session() as s:
        return list((await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all())


@pytest.mark.asyncio
async def test_router_endpoints(db, calls, client):
    r = await client.post("/api/v1/agents/agent-a/refresh")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    r = await client.post("/api/v1/jobs/infra_costs/run")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    r = await client.get("/api/v1/jobs")
    body = r.json()
    assert body["scheduler"]["enabled"] is False
    by_job = {j["job"]: j for j in body["jobs"]}
    assert list(by_job) == list(job_runner.JOBS)
    assert by_job["infra_costs"]["lastRun"]["agentId"] is None and by_job["infra_costs"]["adminOnly"]
    assert by_job["risk_scan"]["available"] is True and by_job["risk_scan"]["unavailableReason"] is None

    r = await client.get("/api/v1/agents/agent-a/jobs")
    jobs = {j["job"]: j for j in r.json()["jobs"]}
    assert jobs["usage_ingestion"]["agentRun"]["status"] == "ok"
    assert jobs["infra_costs"]["agentRun"] is None and jobs["infra_costs"]["lastRun"]["job"] == "infra_costs"

    r = await client.get("/api/v1/jobs/runs", params={"agent_id": "agent-a", "limit": 2})
    assert r.json()["count"] == 2

    assert (await client.post("/api/v1/jobs/nope/run")).status_code == 404
    assert (await client.get("/api/v1/jobs/runs", params={"job": "nope"})).status_code == 404
    assert (await client.post("/api/v1/agents/ghost/refresh")).status_code == 404
    assert (await client.get("/api/v1/agents/ghost/jobs")).status_code == 404

    audit = await _audit_rows()
    assert [a.action for a in audit] == ["agent.refresh", "job.run"]
    refresh = audit[0].changes
    assert refresh["status"] == "ok" and set(refresh["runs"]) == set(job_runner.REFRESH_JOBS)
    assert all(v["runId"] and v["status"] == "ok" for v in refresh["runs"].values())


@pytest.mark.asyncio
async def test_days_are_validated_passed_to_usage_only_and_audited(db, calls, client):
    assert (await client.post("/api/v1/jobs/usage_ingestion/run", params={"days": 91})).status_code == 422
    assert (await client.post("/api/v1/jobs/usage_ingestion/run", params={"days": 0})).status_code == 422

    r = await client.post("/api/v1/jobs/usage_ingestion/run", params={"agent_id": "agent-a", "days": 7})
    assert r.status_code == 200
    run_id = r.json()["runId"]
    await client.post("/api/v1/jobs/cost_rollup/run", params={"agent_id": "agent-a", "days": 7})
    assert [c[3] for c in calls] == [{"days": 7}, {}]

    audit = await _audit_rows()
    assert audit[0].changes == {"agentId": "agent-a", "runId": run_id, "status": "ok", "days": 7}
    assert audit[1].changes["status"] == "ok" and "days" not in audit[1].changes


@pytest.mark.asyncio
async def test_empty_agent_id_means_all_agents(db, calls, client):
    r = await client.post("/api/v1/jobs/governance_checks/run", params={"agent_id": ""})
    assert r.status_code == 200 and r.json()["agentId"] is None
    assert calls[0][1] is None
    [row] = await _rows()
    assert row.agent_id is None


@pytest.mark.asyncio
async def test_non_finite_result_does_not_break_the_api(db, calls, client):
    calls.set("cost_rollup", result={"status": "ok", "cost": Decimal("NaN"), "rate": float("inf")})
    r = await client.post("/api/v1/jobs/cost_rollup/run", params={"agent_id": "agent-a"})
    assert r.status_code == 200 and r.json()["summary"] == {"cost": None, "rate": None}
    for path in ("/api/v1/jobs", "/api/v1/jobs/runs", "/api/v1/agents/agent-a/jobs"):
        assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_api_shows_a_short_summary(db, calls, client):
    calls.set("risk_scan", result={"status": "ok", "agents": {f"a{i}": {"n": i} for i in range(200)}})
    r = await client.post("/api/v1/jobs/risk_scan/run")
    shown = r.json()["summary"]
    assert len(shown["agents"]) == job_runner.MAX_ITEMS_SHOWN and shown["agents_total"] == 200
    [row] = await _rows()
    assert len(row.summary["agents"]) == 200  # stored whole: the risk tab reads its agent's entry


@pytest.mark.asyncio
async def test_infra_costs_needs_admin_when_rbac_is_on(db, calls, monkeypatch):
    import api.auth

    monkeypatch.setattr(api.auth, "USE_Rbac", True)
    app = _app({"user_id": "viewer", "role": "viewer"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/jobs/infra_costs/run")
        assert r.status_code == 403
        assert (await c.post("/api/v1/jobs/cost_rollup/run")).status_code == 200
    assert [c[0] for c in calls] == ["cost_rollup"]


@pytest.mark.asyncio
async def test_endpoints_need_a_token(db, calls):
    app = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/jobs")).status_code == 401
        assert (await c.get("/api/v1/agents/agent-a/jobs")).status_code == 401
        assert (await c.post("/api/v1/agents/agent-a/refresh")).status_code == 401
        assert (await c.post("/api/v1/jobs/risk_scan/run")).status_code == 401
    assert calls == []
