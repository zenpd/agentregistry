"""In-process daily scheduler for the agent-operations jobs.

One asyncio task per app process. Each job runs at most once per UTC day for
all agents; with several replicas the run lock in job_runner lets only one of
them run a given job.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

from orchestrations import job_runner
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("orchestrations.scheduler")

# Wake at least this often so a suspended host or clock change can't make a
# long sleep overshoot the day, and so a job refused by the run lock is retried.
MAX_SLEEP_SECONDS = 900.0
MIN_SLEEP_SECONDS = 1.0
ERROR_RETRY_SECONDS = 60.0
# Replicas would otherwise all wake at the same job time; the spread lets one
# take the run lock first instead of all backing off together.
MAX_JITTER_SECONDS = 20.0

_task: asyncio.Task | None = None
_next_run_at: datetime | None = None


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def due_jobs(now: datetime) -> list[str]:
    """Jobs whose time of day has passed, in JOBS order."""
    return [name for name, spec in job_runner.JOBS.items() if spec.daily_at <= now.time()]


def next_wake(now: datetime) -> datetime:
    """The first scheduled job time strictly after now (today or tomorrow)."""
    times = sorted({spec.daily_at for spec in job_runner.JOBS.values()})
    today = _day_start(now)
    for t in times:
        at = today.replace(hour=t.hour, minute=t.minute, second=t.second)
        if at > now:
            return at
    first = times[0]
    return (today + timedelta(days=1)).replace(hour=first.hour, minute=first.minute, second=first.second)


async def run_due_jobs(now: datetime) -> list[dict]:
    day = _day_start(now)
    results = []
    for job in due_jobs(now):
        # Checked per job, right before it: another replica may have run it meanwhile.
        if job in await job_runner.scheduled_jobs_done_on(day, job_runner.utcnow()):
            continue
        try:
            results.append(await job_runner.run_job(job, trigger="scheduled"))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler.job_failed", job=job)
    return results


async def _tick() -> float:
    """Runs what is due; returns how long to sleep before the next tick."""
    global _next_run_at
    await run_due_jobs(job_runner.utcnow())
    now = job_runner.utcnow()
    _next_run_at = next_wake(now)
    return min(MAX_SLEEP_SECONDS, max(MIN_SLEEP_SECONDS, (_next_run_at - now).total_seconds()))


async def _loop() -> None:
    log.info("scheduler.started", jobs=list(job_runner.JOBS))
    await asyncio.sleep(random.uniform(0, MAX_JITTER_SECONDS))
    while True:
        try:
            wait = await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler.tick_failed")
            wait = ERROR_RETRY_SECONDS
        await asyncio.sleep(wait + random.uniform(0, MAX_JITTER_SECONDS))


def _on_done(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("scheduler.crashed", error=job_runner.describe_error(task.exception()))


def start_scheduler() -> None:
    global _task
    if not get_settings().scheduler_enabled:
        log.info("scheduler.disabled")
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.get_running_loop().create_task(_loop(), name="agent-ops-scheduler")
    _task.add_done_callback(_on_done)


async def stop_scheduler() -> None:
    global _task, _next_run_at
    task, _task, _next_run_at = _task, None, None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        # Our own cancellation, not the scheduler task's: pass it on.
        if current is not None and current.cancelling():
            raise
    except Exception:
        pass  # already logged by _on_done
    log.info("scheduler.stopped")


def scheduler_status() -> dict:
    running = _task is not None and not _task.done()
    return {
        "enabled": bool(get_settings().scheduler_enabled),
        "running": running,
        "nextRunAt": _next_run_at.isoformat() if running and _next_run_at else None,
        "timezone": "UTC",
        "lockMinutes": job_runner.LOCK_MINUTES,
    }
