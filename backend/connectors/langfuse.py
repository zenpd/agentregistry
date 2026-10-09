"""Langfuse, read-only, through its public API with a project key pair.

A Langfuse key pair belongs to one project, so one connector is one project.
The connector reports that project as a finding (its trace names, models and
recent activity) and, for an agent linked to it, the daily token usage per model.
Prompt and answer text is never read."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from connectors.base import ConnectorError, Finding

PAGE = 100


class LangfuseConnector:
    kind = "langfuse"

    def __init__(self, settings: dict, secret: dict, transport: httpx.AsyncBaseTransport | None = None):
        self.host = (settings.get("host") or "https://cloud.langfuse.com").rstrip("/")
        self.public_key = secret.get("public_key") or ""
        self.secret_key = secret.get("secret_key") or ""
        self.window_days = int(settings.get("windowDays") or 7)
        self.max_pages = int(settings.get("maxPages") or 10)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        if not (self.public_key and self.secret_key):
            raise ConnectorError("not_configured", "Enter the Langfuse public and secret key.")
        return httpx.AsyncClient(base_url=self.host, auth=(self.public_key, self.secret_key), timeout=30, transport=self._transport)

    async def _get(self, client: httpx.AsyncClient, path: str, **params: Any) -> Any:
        try:
            r = await client.get(path, params={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as exc:
            raise ConnectorError("unreachable", f"Langfuse did not answer at {self.host} ({type(exc).__name__}).")
        if r.status_code in (401, 403):
            raise ConnectorError("unauthorized", "Langfuse refused the key pair.")
        if r.status_code >= 400:
            raise ConnectorError("failed", f"Langfuse answered HTTP {r.status_code} for {path}.")
        try:
            return r.json()
        except ValueError:
            raise ConnectorError("failed", "Langfuse answered with something that is not JSON.")

    async def test(self) -> dict:
        async with self._client() as client:
            projects = (await self._get(client, "/api/public/projects")).get("data") or []
        name = projects[0].get("name") if projects else None
        return {"ok": True, "message": f"Connected to the Langfuse project {name}." if name else "Connected."}

    async def _pages(self, client, path: str, **params) -> list[dict]:
        out: list[dict] = []
        for page in range(1, self.max_pages + 1):
            body = await self._get(client, path, page=page, limit=PAGE, **params)
            data = body.get("data") or []
            out.extend(data)
            total_pages = ((body.get("meta") or {}).get("totalPages")) or 1
            if not data or page >= total_pages:
                break
        return out

    async def sync(self) -> list[Finding]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()
        async with self._client() as client:
            projects = (await self._get(client, "/api/public/projects")).get("data") or []
            traces = await self._pages(client, "/api/public/traces", fromTimestamp=since)
            generations = await self._pages(client, "/api/public/observations", type="GENERATION", fromStartTime=since)
        project = projects[0] if projects else {"id": self.public_key[:12], "name": "Langfuse project"}
        names, models = Counter(t.get("name") for t in traces if t.get("name")), Counter(g.get("model") for g in generations if g.get("model"))
        last = max([t.get("timestamp") for t in traces if t.get("timestamp")] or [None], key=lambda x: x or "")
        return [Finding(kind="trace_project", external_id=str(project.get("id")), name=str(project.get("name")),
                        url=f"{self.host}/project/{project.get('id')}",
                        details={"traces": len(traces), "generations": len(generations), "windowDays": self.window_days,
                                 "traceNames": [n for n, _ in names.most_common(8)], "models": [m for m, _ in models.most_common(6)],
                                 "lastSeen": last, "sampleCapped": len(traces) >= self.max_pages * PAGE})]

    async def daily_usage(self, days: int) -> list[dict]:
        """[{day, model, calls, input_tokens, output_tokens}] for the last `days` days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with self._client() as client:
            generations = await self._pages(client, "/api/public/observations", type="GENERATION", fromStartTime=since)
        return rollup(generations)


def _tokens(g: dict) -> tuple[int, int]:
    usage = g.get("usageDetails") or g.get("usage") or {}
    inp = usage.get("input") or usage.get("promptTokens") or usage.get("input_tokens") or 0
    out = usage.get("output") or usage.get("completionTokens") or usage.get("output_tokens") or 0
    return int(inp or 0), int(out or 0)


def rollup(generations: list[dict]) -> list[dict]:
    """Daily token usage per model from Langfuse generations. Pure."""
    acc: dict[tuple[date, str], dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    for g in generations:
        started, model = g.get("startTime"), g.get("model")
        if not started or not model:
            continue
        try:
            day = datetime.fromisoformat(str(started).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        i, o = _tokens(g)
        row = acc[(day, model)]
        row["calls"] += 1
        row["input_tokens"] += i
        row["output_tokens"] += o
    return [{"day": d, "model": m, **v} for (d, m), v in sorted(acc.items())]
