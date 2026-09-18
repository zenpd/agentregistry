"""Runs the agent-operations jobs and records every run in job_runs.

Job functions live in other modules and are imported only when a run starts,
so a module that is missing or fails to import is recorded as 'unavailable'
instead of breaking the app.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import math
import random
import re
import secrets
import traceback
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable, Union

import anyio
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db_session
from db.models import JobRun
from shared.logger import get_logger

log = get_logger("orchestrations.job_runner")

JobFn = Callable[..., Awaitable[dict]]

LOCK_MINUTES = 30
HEARTBEAT_SECONDS = 300.0
# Starts this close together are simultaneous: all of them may back off, so they retry.
CONTENTION_SECONDS = 5.0
ACQUIRE_ATTEMPTS = 3
# Stored summaries keep every agent's entry (other tabs read them from all-agents
# runs); API responses show a short view.
MAX_ITEMS_STORED = 1000
MAX_ITEMS_SHOWN = 50
MAX_SUMMARY_BYTES = 2_000_000
MAX_STR_CHARS = 2000
MAX_DEPTH = 6
MAX_ERROR_CHARS = 1000

REFRESH_LOCK = "refresh"
REFRESH_JOBS = ("usage_ingestion", "cost_rollup", "risk_scan", "governance_checks")
JOB_STATUSES = frozenset({"ok", "partial", "not_configured", "skipped", "error", "unreachable"})
_OK = {"ok", "skipped"}
_FAILED = {"error", "unreachable", "not_configured", "unavailable", "stale", "cancelled"}
# A scheduled run that ended like this did no work, so the scheduler retries it the same day.
_RETRY_SAME_DAY = {"stale", "cancelled"}


@dataclass(frozen=True)
class JobSpec:
    name: str
    label: str
    short_label: str
    # "package.module:function", or the function itself (tests inject fakes).
    target: Union[str, JobFn]
    daily_at: time
    admin_only: bool = False


JOBS: dict[str, JobSpec] = {s.name: s for s in (
    JobSpec("usage_ingestion", "Usage ingestion (Phoenix)", "Usage",
            "orchestrations.usage_ingestion:ingest_usage", time(1, 0)),
    JobSpec("infra_costs", "Infra cost pull (Azure Cost Management)", "Infra cost",
            "costs.azure_cost_collector:collect_infra_costs", time(1, 30), admin_only=True),
    JobSpec("cost_rollup", "Cost rollup, budget status, anomalies", "Cost rollup",
            "orchestrations.cost_rollup:rollup_costs", time(2, 0)),
    JobSpec("risk_scan", "Risk scan", "Risk scan",
            "orchestrations.risk_scan:scan_risks", time(2, 30)),
    JobSpec("governance_checks", "Governance checks (expiry, recertification)", "Governance",
            "orchestrations.governance_checks:run_governance_checks", time(3, 0)),
)}


def get_spec(job: str) -> JobSpec:
    spec = JOBS.get(job)
    if spec is None:
        raise ValueError(f"Unknown job '{job}'. Known jobs: {', '.join(JOBS)}")
    return spec


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; every value we store is UTC.
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _resolve(spec: JobSpec) -> JobFn:
    if callable(spec.target):
        return spec.target
    module_name, attr = spec.target.split(":", 1)
    return getattr(importlib.import_module(module_name), attr)


def availability(spec: JobSpec) -> tuple[bool, str | None]:
    """(importable, why not). Imports the module, so a half-written one shows as unavailable."""
    try:
        _resolve(spec)
    except Exception as exc:
        return False, describe_error(exc)
    return True, None


# ── Result sanitising ────────────────────────────────────────────────────────

_SECRET_WORDS = (
    r"api_?keys?|apikey|secrets?|passwords?|passwd|pwd|token|access_?key|account_?key|subscription_?key|"
    r"private_?key|connection_?string|conn_?str|authorization|credentials?|cookie|sas|sig|signature"
)
_CONTENT_WORDS = r"prompts?|completions?|messages|input_messages|output_messages|input_value|output_value"
_SENSITIVE_KEY = re.compile(rf"_(?:{_SECRET_WORDS}|{_CONTENT_WORDS})_")

_STRONG_NAME = (
    r"[A-Za-z0-9_.-]*(?:api[_-]?keys?|apikey|secret|password|passwd|token|access[_-]?key|account[_-]?key|"
    r"subscription[_-]?key|private[_-]?key|authorization|credentials?|signature|connection[_-]?string)"
)
# Generic names that are only secrets as query or connection-string parameters (name=value).
_WEAK_NAME = r"(?:[A-Za-z0-9_.-]*key|code|sig|sas|pwd|auth)"
_SECRET_IN_TEXT = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (re.compile(rf"(?i)(?<![A-Za-z0-9])([\"']?)({_STRONG_NAME})\1(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s&,;'\"}}\]]+)"),
     r"\1\2\1\3***"),
    (re.compile(rf"(?i)(?<![A-Za-z0-9_.-])({_WEAK_NAME})=([^&\s'\"<>,;]+)"), r"\1=***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "sk-***"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), "***"),
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://***:***@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_IN_TEXT:
        text = pattern.sub(replacement, text)
    return text


def _key_words(key: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()
    return "_" + re.sub(r"[^a-z0-9]+", "_", snake).strip("_") + "_"


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(_key_words(key)))


def _finite(x: float) -> float | None:
    return x if math.isfinite(x) else None


def _is_number(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, Decimal))


def jsonable(value: Any, *, max_items: int = MAX_ITEMS_STORED, depth: int = 0) -> Any:
    """JSON-safe copy of a job result: NaN/inf become None, collections and
    strings are cut short, secrets and prompt/output text are blanked."""
    if depth > MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return _finite(value)
    if isinstance(value, Decimal):
        return _finite(float(value)) if value.is_finite() else None
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, str):
        value = redact(value)
        return value if len(value) <= MAX_STR_CHARS else value[:MAX_STR_CHARS] + "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:max_items]:
            key = str(k)
            # Counts such as prompt_tokens are numbers; only text can carry a secret or a prompt.
            if is_sensitive_key(key) and not _is_number(v):
                out[key] = "[redacted]"
                continue
            total_key = f"{key}_total"
            if isinstance(v, (list, tuple, set, frozenset, dict)) and len(v) > max_items and total_key not in value:
                out[total_key] = len(v)
            out[key] = jsonable(v, max_items=max_items, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v, max_items=max_items, depth=depth + 1) for v in list(value)[:max_items]]
    return redact(str(value))[:MAX_STR_CHARS]


def bounded(summary: dict) -> dict:
    size = len(json.dumps(summary))
    if size <= MAX_SUMMARY_BYTES:
        return summary
    slim = {k: v for k, v in summary.items() if _is_number(v) or (isinstance(v, str) and len(v) <= 500)}
    slim["truncated"] = f"The job summary was {size} bytes; nested details were dropped."
    return slim


def summary_view(summary: Any) -> dict:
    return jsonable(summary, max_items=MAX_ITEMS_SHOWN) if isinstance(summary, dict) else {}


def for_display(run: dict) -> dict:
    """A run result with its summary shortened for an API response."""
    return {**run, "summary": summary_view(run.get("summary"))}


def describe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {redact(str(exc))}"
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if not f.filename.startswith("<")]
    # For import failures the last frame is importlib's, which tells the reader nothing.
    if frames and not isinstance(exc, (ImportError, SyntaxError)):
        text += f" [{Path(frames[-1].filename).name}:{frames[-1].lineno}]"
    return text[:MAX_ERROR_CHARS]


def overall_status(statuses: list[str]) -> str:
    if not statuses:
        return "skipped"
    if all(s in _OK for s in statuses):
        return "ok"
    if all(s in _FAILED for s in statuses):
        return "error"
    return "partial"


def run_to_dict(row: JobRun | None, *, full: bool = False) -> dict | None:
    if row is None:
        return None
    started, finished = as_utc(row.started_at), as_utc(row.finished_at)
    summary = row.summary if isinstance(row.summary, dict) else {}
    return {
        "runId": row.id,
        "job": row.job,
        "agentId": row.agent_id,
        "trigger": row.trigger,
        "status": row.status,
        "startedAt": started.isoformat() if started else None,
        "finishedAt": finished.isoformat() if finished else None,
        "durationMs": int((finished - started).total_seconds() * 1000) if started and finished else None,
        # Re-sanitised on read: rows written by older code may hold NaN or unredacted text.
        "summary": jsonable(summary) if full else summary_view(summary),
        "error": redact(row.error) if row.error else None,
    }


# ── Queries ──────────────────────────────────────────────────────────────────

def _scope(stmt, agent_id: str | None):
    return stmt.where(JobRun.agent_id.is_(None) if agent_id is None else JobRun.agent_id == agent_id)


def _overlapping(stmt, agent_id: str | None):
    """Runs that touch the same agents: an all-agents run overlaps every agent's run."""
    if agent_id is None:
        return stmt
    return stmt.where(or_(JobRun.agent_id == agent_id, JobRun.agent_id.is_(None)))


def last_alive(row: JobRun) -> datetime:
    started = as_utc(row.started_at)
    beat = row.summary.get("heartbeatAt") if isinstance(row.summary, dict) else None
    try:
        beat_at = as_utc(datetime.fromisoformat(beat)) if isinstance(beat, str) else None
    except ValueError:
        beat_at = None
    return max(started, beat_at) if beat_at else started


def is_live(row: JobRun, now: datetime) -> bool:
    return row.status == "running" and last_alive(row) >= now - timedelta(minutes=LOCK_MINUTES)


async def _running(db: AsyncSession, job: str, agent_id: str | None) -> list[JobRun]:
    stmt = select(JobRun).where(JobRun.job == job, JobRun.status == "running")
    return list((await db.execute(_overlapping(stmt, agent_id))).scalars().all())


async def latest_runs(db: AsyncSession, agent_id: str | None = None, *, any_scope: bool = False) -> dict[str, JobRun | None]:
    """Newest run per job. any_scope ignores agent_id; otherwise agent_id=None
    means the all-agents runs."""
    out: dict[str, JobRun | None] = {}
    for job in JOBS:
        stmt = select(JobRun).where(JobRun.job == job)
        if not any_scope:
            stmt = _scope(stmt, agent_id)
        stmt = stmt.order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(1)
        out[job] = (await db.execute(stmt)).scalar_one_or_none()
    return out


async def list_runs(db: AsyncSession, job: str | None = None, agent_id: str | None = None, limit: int = 50) -> list[JobRun]:
    stmt = select(JobRun)
    if job:
        stmt = stmt.where(JobRun.job == job)
    if agent_id:
        stmt = stmt.where(JobRun.agent_id == agent_id)
    stmt = stmt.order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def scheduled_jobs_done_on(day_start: datetime, now: datetime) -> set[str]:
    """Jobs that already have a scheduled all-agents run today (a live
    'running' row counts: another replica holds it). Errors count as done so a
    failing source is not hammered all day."""
    async with get_db_session() as db:
        rows = (await db.execute(
            select(JobRun).where(
                JobRun.trigger == "scheduled", JobRun.agent_id.is_(None), JobRun.started_at >= day_start,
            )
        )).scalars().all()
    return {
        r.job for r in rows
        if r.status not in _RETRY_SAME_DAY and (r.status != "running" or is_live(r, now))
    }


# ── Run lock ─────────────────────────────────────────────────────────────────

async def _acquire(run_id: str, job: str, agent_id: str | None, trigger: str) -> JobRun | None:
    """Insert our 'running' row, then look for another live run that overlaps
    it. Returns that holder (our row is removed) or None when we hold the lock.
    Each side inserts before it looks, so two runs never proceed together."""
    attempt = 0
    while True:
        attempt += 1
        now = utcnow()
        async with get_db_session() as db:
            for old in await _running(db, job, agent_id):
                if not is_live(old, now):
                    old.status = "stale"
                    old.finished_at = now
                    old.error = f"No sign of life for {LOCK_MINUTES} min; the process running it probably stopped."
            db.add(JobRun(id=run_id, job=job, agent_id=agent_id, trigger=trigger,
                          status="running", started_at=now, summary={}))

        async with get_db_session() as db:
            others = [r for r in await _running(db, job, agent_id) if r.id != run_id and is_live(r, utcnow())]
            if not others:
                return None
            await db.delete(await db.get(JobRun, run_id))

        holder = min(others, key=lambda r: (as_utc(r.started_at), r.id))
        simultaneous = all(abs((as_utc(r.started_at) - now).total_seconds()) < CONTENTION_SECONDS for r in others)
        if not simultaneous or attempt >= ACQUIRE_ATTEMPTS:
            return holder
        await asyncio.sleep(random.uniform(0.05, 0.5))


async def _discard(run_id: str) -> None:
    try:
        async with get_db_session() as db:
            row = await db.get(JobRun, run_id)
            if row is not None and row.status == "running":
                await db.delete(row)
    except Exception:
        log.warning("job.discard_failed", run_id=run_id)


async def _acquire_or_discard(run_id: str, job: str, agent_id: str | None, trigger: str) -> JobRun | None:
    try:
        return await _acquire(run_id, job, agent_id, trigger)
    except BaseException:
        # Cancelled or failed mid-acquire: don't leave a 'running' row holding the lock.
        with anyio.CancelScope(shield=True):
            await _discard(run_id)
        raise


async def _heartbeat(run_id: str) -> None:
    """Keeps a long run from being declared stale while its process is alive."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            async with get_db_session() as db:
                await db.execute(
                    update(JobRun).where(JobRun.id == run_id, JobRun.status == "running")
                    .values(summary={"heartbeatAt": utcnow().isoformat()})
                )
        except Exception:  # a missed beat only risks a false 'stale' much later
            log.warning("job.heartbeat_failed", run_id=run_id)


async def _write_finish(run_id: str, status: str, summary: dict, error: str | None) -> JobRun | None:
    async with get_db_session() as db:
        row = await db.get(JobRun, run_id)
        if row is None:
            return None
        row.status = status
        row.summary = summary
        row.error = error
        row.finished_at = utcnow()
    return row


async def _finish(run_id: str, status: str, summary: dict, error: str | None) -> JobRun | None:
    try:
        return await _write_finish(run_id, status, summary, error)
    except Exception as exc:
        log.warning("job.finish_failed", run_id=run_id, error=describe_error(exc))
        note = f"The job ended '{status}' but its result could not be stored ({describe_error(exc)})."
        return await _write_finish(run_id, "error", {}, note[:MAX_ERROR_CHARS])


def _locked(job: str, agent_id: str | None, trigger: str, holder: JobRun) -> dict:
    scope = f"for agent {holder.agent_id}" if holder.agent_id else "for all agents"
    return {
        "runId": None, "job": job, "agentId": agent_id, "trigger": trigger,
        "status": "skipped", "locked": True,
        "reason": f"Already running {scope} since {as_utc(holder.started_at).isoformat()} (run {holder.id}).",
        "startedAt": None, "finishedAt": None, "durationMs": None, "summary": {}, "error": None,
    }


# ── Running ──────────────────────────────────────────────────────────────────

async def _execute(spec: JobSpec, agent_id: str | None, trigger: str, kwargs: dict) -> tuple[str, dict, str | None]:
    try:
        fn = _resolve(spec)
    except Exception as exc:  # missing or broken module: the job cannot run yet
        return "unavailable", {"reason": f"Job code '{spec.target}' is not available."}, describe_error(exc)
    result = await fn(agent_id=agent_id, trigger=trigger, **kwargs)
    if not isinstance(result, dict) or not isinstance(result.get("status"), str) or not result["status"]:
        return "error", {}, f"Job returned {type(result).__name__} without a 'status' key."
    summary = bounded(jsonable({k: v for k, v in result.items() if k != "status"}))
    status = result["status"]
    if status in JOB_STATUSES:
        return status, summary, None
    reported = redact(status)[:40]
    summary["jobStatus"] = reported
    return "error", summary, f"The job reported status '{reported}', which is not one of {', '.join(sorted(JOB_STATUSES))}."


async def run_job(job: str, agent_id: str | None = None, trigger: str = "manual", **kwargs: Any) -> dict:
    spec = get_spec(job)
    run_id = secrets.token_hex(12)
    holder = await _acquire_or_discard(run_id, job, agent_id, trigger)
    if holder is not None:
        return _locked(job, agent_id, trigger, holder)

    clock = monotonic()
    status, summary, error = "error", {}, None
    beat = asyncio.create_task(_heartbeat(run_id))
    try:
        status, summary, error = await _execute(spec, agent_id, trigger, kwargs)
    except asyncio.CancelledError:
        status, error = "cancelled", "Cancelled while running (app shutdown)."
        raise
    except Exception as exc:  # a failing job must never take the caller down
        status, error = "error", describe_error(exc)
    finally:
        beat.cancel()
        # Shielded: under anyio's level-triggered cancellation this write would be cancelled too.
        with anyio.CancelScope(shield=True):
            finished = await _finish(run_id, status, summary, error)

    log.info("job.finished", job=job, agent_id=agent_id, trigger=trigger, status=status,
             ms=int((monotonic() - clock) * 1000))
    if error:
        log.warning("job.error", job=job, agent_id=agent_id, error=error)
    if finished is None:
        raise RuntimeError(f"Job run {run_id} disappeared from job_runs before it finished.")
    return {**run_to_dict(finished, full=True), "locked": False}


async def refresh_agent(agent_id: str, trigger: str = "manual") -> dict:
    """Usage → cost → risk → governance for one agent, one after another. A
    failed step does not stop the next: each works from whatever data exists.
    A 'refresh' row in job_runs keeps two refreshes of one agent from interleaving."""
    started = utcnow()
    run_id = secrets.token_hex(12)
    holder = await _acquire_or_discard(run_id, REFRESH_LOCK, agent_id, trigger)
    if holder is not None:
        return {
            "agentId": agent_id, "trigger": trigger, "status": "skipped", "locked": True,
            "reason": f"A refresh of this agent is already running since {as_utc(holder.started_at).isoformat()} (run {holder.id}).",
            "startedAt": started.isoformat(), "finishedAt": utcnow().isoformat(), "results": [],
        }

    results: list[dict] = []
    status, error = "error", None
    try:
        for job in REFRESH_JOBS:
            results.append(await run_job(job, agent_id=agent_id, trigger=trigger))
        # A step held by another run refreshed nothing, so the refresh is only partial.
        status = overall_status(["partial" if r.get("locked") else r["status"] for r in results])
    except asyncio.CancelledError:
        status, error = "cancelled", "Cancelled while running (app shutdown)."
        raise
    except Exception as exc:
        error = describe_error(exc)
        raise
    finally:
        steps = {r["job"]: {"runId": r["runId"], "status": r["status"]} for r in results}
        with anyio.CancelScope(shield=True):
            await _finish(run_id, status, {"steps": steps}, error)
    return {
        "agentId": agent_id, "trigger": trigger, "status": status, "locked": False,
        "startedAt": started.isoformat(), "finishedAt": utcnow().isoformat(),
        "results": results,
    }
