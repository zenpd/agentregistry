"""Minimal async client for Phoenix's REST API (project/span discovery).

Deliberately narrow — this project only needs to LIST what Phoenix already
knows about (projects, spans), not upload datasets or run experiments. The
request shape (`GET /v1/projects`, `GET /v1/projects/{name}/spans`, cursor
pagination, `Authorization: Bearer` auth) mirrors the same REST surface
already proven against this org's `zaf-phoenix` instance by a sibling
project (assureai) — see that project's `backend/app/runs/phoenix.py` if
this ever needs to grow past listing.

`observability/tracing.py` in this codebase only WRITES traces (OTLP
export); this is the first code that READS them back.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from urllib.parse import quote

import httpx

PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 15.0


class PhoenixError(Exception):
    """A Phoenix request failed — names the method/URL/status so a caller
    can tell 'Phoenix is unreachable' apart from 'this project has no
    traces yet' (the latter is a normal 200 with an empty list, not this)."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:300]}")
        self.status = status


class PhoenixClient:
    """One client per request — never a module-level singleton, since the
    base URL/key come from settings that a test or a future multi-tenant
    setup may override."""

    def __init__(self, base_url: str, *, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"accept": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout)

    async def __aenter__(self) -> "PhoenixClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.get(path, **kwargs)
        except httpx.HTTPError as exc:
            raise PhoenixError("GET", f"{self.base_url}{path}", 0, str(exc)) from exc
        if response.status_code >= 400:
            raise PhoenixError("GET", f"{self.base_url}{path}", response.status_code, response.text)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            # An HTML login page from a proxy is not Phoenix: report it as a failure to read.
            raise PhoenixError("GET", f"{self.base_url}{path}", 0, "The answer was not JSON") from exc

    async def projects(self) -> list[str]:
        """Every project name Phoenix currently knows about. One page only
        (`PAGE_SIZE`) — this backs a human-facing discovery dropdown, not a
        full sweep."""
        page = await self._get("/v1/projects", params={"limit": PAGE_SIZE})
        return [p["name"] for p in (page or {}).get("data") or []]

    async def all_projects(self, max_pages: int = 20) -> list[dict]:
        """Every project, following the cursor ({name, id}); `projects()` is
        the single-page dropdown helper. Bounded so a runaway cursor ends."""
        found: list[dict] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            try:
                page = await self._get("/v1/projects", params=params)
            except PhoenixError as exc:
                # A Phoenix that scales to zero can miss the first request while it wakes up: one more try.
                if exc.status != 0:
                    raise
                page = await self._get("/v1/projects", params=params)
            found.extend({"name": p["name"], "id": p.get("id")} for p in (page or {}).get("data") or [] if p.get("name"))
            cursor = (page or {}).get("next_cursor")
            if not cursor:
                break
        return found

    async def spans(
        self,
        project: str,
        limit: int = PAGE_SIZE,
        max_pages: int = 5,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        span_kind: str | None = None,
    ) -> AsyncIterator[dict]:
        """Spans for one project, newest first, page by page.

        `max_pages` bounds the sweep (default up to `max_pages * limit` =
        500 spans) — this reconstructs a STRUCTURAL diagram (which node
        calls which), which converges from a bounded recent sample; it does
        not need a project's entire history, and an unbounded sweep against
        a remote Phoenix is exactly the "a human is waiting on this page"
        case the upstream client's own docs warn about.
        """
        cursor: str | None = None
        pages_fetched = 0
        while pages_fetched < max_pages:
            params: dict[str, Any] = {"limit": limit}
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            if span_kind:
                params["span_kind"] = span_kind
            if cursor:
                params["cursor"] = cursor
            page = await self._get(f"/v1/projects/{quote(project, safe='')}/spans", params=params)
            pages_fetched += 1
            for span in (page or {}).get("data") or []:
                yield span
            cursor = (page or {}).get("next_cursor")
            if not cursor:
                return
