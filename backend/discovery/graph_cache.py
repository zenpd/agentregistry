"""In-memory TTL cache for per-agent Phoenix span samples (graph + observed
dependencies), so opening the Diagram tab does not re-pay the Phoenix round
trip each time. Process-local: each worker keeps its own copy."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_TTL_SECONDS = 300.0

CacheKey = tuple[str, str, str]


class GraphCache:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[CacheKey, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[CacheKey, asyncio.Lock] = {}

    @staticmethod
    def key(agent_id: str, project: str, endpoint: str) -> CacheKey:
        return (agent_id, project, endpoint)

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._clock() - stored_at > self.ttl_seconds:
            del self._entries[key]
            return None
        return value

    def set(self, key: CacheKey, value: dict[str, Any]) -> dict[str, Any]:
        """Stores a copy stamped with cachedAt (UTC ISO) and returns it."""
        stamped = {**value, "cachedAt": datetime.now(timezone.utc).isoformat()}
        self._entries[key] = (self._clock(), stamped)
        return stamped

    def invalidate(self, agent_id: str | None = None) -> int:
        """Drops every entry for one agent (all entries when agent_id is None)."""
        doomed = [k for k in self._entries if agent_id is None or k[0] == agent_id]
        for k in doomed:
            del self._entries[k]
        return len(doomed)

    def lock(self, key: CacheKey) -> asyncio.Lock:
        """One fetch per key at a time, so parallel tab requests share a sample."""
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock


graph_cache = GraphCache()
