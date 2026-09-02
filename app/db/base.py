"""SQLAlchemy async engine + session factory.

Supports both SQLite (local dev) and PostgreSQL (production).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from shared.config import get_settings


def _make_engine():
    s = get_settings()
    url = s.database_url

    # SQLite-specific configuration
    if url.startswith("sqlite"):
        # Ensure directory exists
        db_path = url.replace("sqlite+aiosqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_async_engine(url, echo=False)

    # PostgreSQL configuration
    return create_async_engine(url, echo=False, pool_pre_ping=True)


engine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def create_all_tables() -> None:
    """Create all ORM tables if they don't exist. Prefer Alembic in production —
    run `alembic upgrade head` as a pre-deploy step. Kept for local dev only."""
    import db.models  # noqa: F401  (register metadata on Base)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for a DB session with auto commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
