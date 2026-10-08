"""AssureAI, read-only: the gate verdict of one evaluation run.

An AssureAI run key belongs to one application. It can read a run's gate report
(GET /runs/{id}/gate-report) but cannot list runs, so the registry is told the
run id (by a person on the Governance tab, or by the CI pipeline that started the
run) and reads only the verdict, the run date and the application name. No
scores are copied."""
from __future__ import annotations

from typing import Any

import httpx

from connectors.base import ConnectorError, Finding

NO_RUN = "00000000-0000-0000-0000-000000000000"


class AssureAIConnector:
    kind = "assureai"

    def __init__(self, settings: dict, secret: dict, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (settings.get("baseUrl") or "").rstrip("/")
        self.link_template = (settings.get("linkTemplate") or "").strip()
        self.run_key = secret.get("runKey") or ""
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        if not self.base_url:
            raise ConnectorError("not_configured", "Enter the AssureAI API address, for example https://assureai.example.com/api.")
        if not self.run_key:
            raise ConnectorError("not_configured", "Enter the AssureAI run key of the application.")
        return httpx.AsyncClient(base_url=self.base_url, headers={"Authorization": f"Bearer {self.run_key}"}, timeout=30,
                                 transport=self._transport)

    def link(self, run_id: str) -> str:
        return self.link_template.replace("{runId}", run_id) if "{runId}" in self.link_template else f"{self.base_url}/runs/{run_id}/gate-report"

    async def _report(self, run_id: str) -> httpx.Response:
        async with self._client() as client:
            try:
                return await client.get(f"/runs/{run_id}/gate-report")
            except httpx.HTTPError as exc:
                raise ConnectorError("unreachable", f"AssureAI did not answer at {self.base_url} ({type(exc).__name__}).")

    async def test(self) -> dict:
        """Asks for a run that does not exist: 404 means the key was accepted."""
        r = await self._report(NO_RUN)
        if r.status_code in (401, 403):
            raise ConnectorError("unauthorized", "AssureAI refused the run key.")
        if r.status_code == 404:
            return {"ok": True, "message": "AssureAI accepted the run key."}
        raise ConnectorError("failed", f"AssureAI answered HTTP {r.status_code}, not the expected 404 for an unknown run.")

    async def sync(self) -> list[Finding]:
        return []        # AssureAI finds no agents; it only gives verdicts for runs the registry is told about

    async def verdict(self, run_id: str) -> dict[str, Any]:
        """{verdict: pass|fail, completedAt, application, url}."""
        r = await self._report(run_id)
        if r.status_code in (401, 403):
            raise ConnectorError("unauthorized", "AssureAI refused the run key for this run (it may belong to another application).")
        if r.status_code == 404:
            raise ConnectorError("failed", f"AssureAI has no run {run_id}.")
        if r.status_code == 409:
            detail = _detail(r) or "the run has no verdict to export yet"
            raise ConnectorError("failed", f"No verdict yet: {detail}")
        if r.status_code >= 400:
            raise ConnectorError("failed", f"AssureAI answered HTTP {r.status_code}.")
        try:
            body = r.json()
        except ValueError:
            raise ConnectorError("failed", "AssureAI answered with something that is not JSON.")
        verdict = ((body.get("gate") or {}).get("verdict") or "").lower()
        if verdict not in ("pass", "fail"):
            raise ConnectorError("failed", "The gate report has no pass or fail verdict.")
        return {"verdict": verdict, "completedAt": (body.get("run") or {}).get("completedAt"),
                "application": (body.get("application") or {}).get("name"), "url": self.link(run_id)}


def _detail(r: httpx.Response) -> str | None:
    try:
        d = r.json().get("detail")
        return d if isinstance(d, str) else None
    except ValueError:
        return None
