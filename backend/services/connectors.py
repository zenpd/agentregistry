"""Running the connectors: build the adapter for a stored configuration, test
it, scan it and keep its findings (new ones in, gone ones out, a person's
dismissal or link kept), and read Langfuse usage for agents linked to it."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from connectors.azure_ai import AzureAIConnector
from connectors.base import ConnectorError, unseal
from connectors.github import GitHubConnector
from connectors.langfuse import LangfuseConnector
from db.base import get_db_session
from db.models import Agent, AgentTokenUsage, ConnectorConfig, ExternalFinding
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("services.connectors")

KINDS = {"langfuse": LangfuseConnector, "github": GitHubConnector, "azure": AzureAIConnector}
LABELS = {"langfuse": "Langfuse project", "github": "GitHub organisation", "azure": "Azure subscription"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build(config: ConnectorConfig, transport=None):
    cls = KINDS.get(config.kind)
    if cls is None:
        raise ConnectorError("failed", f"Unknown connector kind {config.kind!r}")
    return cls(config.settings or {}, unseal(config.secret_enc), transport=transport)


async def test(config_id: str) -> dict:
    async with get_db_session() as db:
        config = await db.get(ConnectorConfig, config_id)
    if config is None:
        return {"ok": False, "status": "failed", "message": "Connector not found."}
    try:
        return {**(await build(config).test()), "status": "ok"}
    except ConnectorError as exc:
        return {"ok": False, "status": exc.status, "message": exc.message}


async def sync(config_id: str) -> dict:
    """Scan one connector and store what it found."""
    async with get_db_session() as db:
        config = await db.get(ConnectorConfig, config_id)
    if config is None:
        return {"status": "failed", "message": "Connector not found."}
    try:
        found = await build(config).sync()
        status, message = "ok", f"{len(found)} found."
    except ConnectorError as exc:
        found, status, message = None, exc.status, exc.message
    except Exception as exc:  # an odd answer from the outside system must not stop the other connectors
        log.exception("connector.sync_failed", connector=config_id)
        found, status, message = None, "failed", f"The scan failed ({type(exc).__name__})."
    now = utcnow()
    async with get_db_session() as db:
        config = await db.get(ConnectorConfig, config_id)
        config.last_sync_at, config.last_status, config.last_message = now, status, message[:500]
        if found is not None:
            config.last_found = len(found)
            rows = {r.external_id: r for r in (await db.execute(
                select(ExternalFinding).where(ExternalFinding.connector_id == config_id))).scalars()}
            seen = set()
            for f in found:
                seen.add(f.external_id)
                row = rows.get(f.external_id)
                if row is None:
                    row = ExternalFinding(id=secrets.token_hex(8), connector_id=config_id, kind=f.kind,
                                          external_id=f.external_id[:500], name=f.name[:255], state="new")
                    db.add(row)
                row.name, row.url, row.details, row.last_seen_at = f.name[:255], (f.url or "")[:500] or None, f.details, now
            # Gone from the source: dropped, unless a person dismissed or linked it.
            gone = [r.id for k, r in rows.items() if k not in seen and r.state == "new"]
            if gone:
                await db.execute(delete(ExternalFinding).where(ExternalFinding.id.in_(gone)))
    return {"connector": config_id, "status": status, "message": message, "found": len(found or [])}


async def sync_all(agent_id: str | None = None, trigger: str = "manual", **_: Any) -> dict:
    """The daily job: scan every enabled connector, then read Langfuse usage for linked agents."""
    async with get_db_session() as db:
        configs = (await db.execute(select(ConnectorConfig).where(ConnectorConfig.enabled == True))).scalars().all()  # noqa: E712
    if not configs:
        return {"status": "skipped", "reason": "No connector is configured (Settings → Connectors)."}
    results = [await sync(c.id) for c in configs]
    usage = await ingest_langfuse_usage()
    failed = [r for r in results if r["status"] != "ok"]
    status = "ok" if not failed else ("partial" if len(failed) < len(results) else "error")
    return {"status": status, "connectors": results, "langfuseUsage": usage,
            "reason": "; ".join(f"{r['message']}" for r in failed)[:300] if failed else None}


async def ingest_langfuse_usage(agent_id: str | None = None) -> dict:
    """Daily token usage per model for agents whose traces are in a Langfuse project."""
    days = get_settings().usage_backfill_days
    async with get_db_session() as db:
        stmt = select(Agent).where(Agent.trace_connector_id.isnot(None))
        if agent_id:
            stmt = stmt.where(Agent.id == agent_id)
        agents = (await db.execute(stmt)).scalars().all()
        configs = {c.id: c for c in (await db.execute(select(ConnectorConfig))).scalars()}
    done, errors = 0, []
    for a in agents:
        config = configs.get(a.trace_connector_id)
        if config is None or config.kind != "langfuse":
            continue
        try:
            rows = await build(config).daily_usage(days)
        except ConnectorError as exc:
            errors.append(f"{a.name}: {exc.message}")
            continue
        now = utcnow()
        async with get_db_session() as db:
            for r in rows:
                bucket = datetime(r["day"].year, r["day"].month, r["day"].day, tzinfo=timezone.utc)
                existing = await db.get(AgentTokenUsage, (a.id, bucket, r["model"]))
                if existing is None:
                    existing = AgentTokenUsage(agent_id=a.id, bucket=bucket, model_name=r["model"])
                    db.add(existing)
                existing.invocation_count, existing.input_tokens, existing.output_tokens = r["calls"], r["input_tokens"], r["output_tokens"]
                existing.source, existing.run_count, existing.ingested_at = "langfuse", r["calls"], now
        done += 1
    return {"agents": done, "errors": errors}
