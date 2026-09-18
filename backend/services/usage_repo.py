"""DB access for usage and prices, shared by every tab that shows cost."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentTokenUsage, ModelAlias, ModelTokenPrice
from governance.costing import Price, effective_rows, price_rows


async def load_prices(db: AsyncSession) -> dict[str, Price]:
    result = await db.execute(select(ModelTokenPrice).where(ModelTokenPrice.effective_to.is_(None)))
    prices: dict[str, Price] = {}
    for p in result.scalars().all():
        key = p.model_name.strip().lower()
        prices[key] = Price(key, p.input_price_per_1m, p.output_price_per_1m, p.cache_read_price_per_1m or 0.0)
    return prices


async def load_aliases(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(ModelAlias))
    return {a.alias.strip().lower(): a.model_name.strip().lower() for a in result.scalars().all()}


def _day(bucket: datetime | date) -> date:
    return bucket.date() if isinstance(bucket, datetime) else bucket


async def load_usage_rows(db: AsyncSession, agent_id: str, since: date | None = None) -> list[dict]:
    query = select(AgentTokenUsage).where(AgentTokenUsage.agent_id == agent_id)
    result = await db.execute(query)
    rows = []
    for u in result.scalars().all():
        day = _day(u.bucket)
        if since and day < since:
            continue
        rows.append({
            "day": day,
            "model": u.model_name,
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cached_tokens": u.cached_tokens or 0,
            "calls": u.invocation_count or 0,
            "runs": u.run_count or 0,
            "errors": u.error_count or 0,
            "latency_avg_ms": u.latency_avg_ms,
            "source": u.source or "seed",
            "ingested_at": u.ingested_at,
        })
    return rows


async def priced_usage(db: AsyncSession, agent_id: str, since: date | None = None) -> dict:
    """{rows, source, unpriced, last_ingested_at} — rows carry cost_cents."""
    raw = await load_usage_rows(db, agent_id, since)
    rows, source = effective_rows(raw)
    priced, unpriced = price_rows(rows, await load_prices(db), await load_aliases(db))
    ingested = [r["ingested_at"] for r in rows if r.get("ingested_at")]
    return {
        "rows": priced,
        "source": source,
        "unpriced": unpriced,
        "last_ingested_at": max(ingested).isoformat() if ingested else None,
    }
