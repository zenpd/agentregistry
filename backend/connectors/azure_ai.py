"""Microsoft Azure, read-only, with a service principal that has Reader on the
subscriptions: every Azure OpenAI and AI Services account, each model
deployment in it, and the agents of Azure AI Foundry projects where the
service principal may list them.

A model deployment is a finding because something calls it: often an agent
that nobody registered. A Foundry agent is a finding in its own right."""
from __future__ import annotations

from typing import Any

import httpx

from connectors.base import ConnectorError, Finding

ARM = "https://management.azure.com"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
ACCOUNTS_API = "2024-10-01"
PROJECTS_API = "2025-04-01-preview"
AI_KINDS = {"OpenAI", "AIServices"}


class AzureAIConnector:
    kind = "azure"

    def __init__(self, settings: dict, secret: dict, transport: httpx.AsyncBaseTransport | None = None):
        self.tenant = settings.get("tenantId") or ""
        self.client_id = settings.get("clientId") or ""
        self.subscriptions = [s.strip() for s in settings.get("subscriptions") or [] if s and s.strip()]
        self.client_secret = secret.get("clientSecret") or ""
        self._transport = transport

    def _check(self) -> None:
        missing = [n for n, v in (("tenant id", self.tenant), ("client id", self.client_id), ("client secret", self.client_secret),
                                  ("a subscription id", self.subscriptions)) if not v]
        if missing:
            raise ConnectorError("not_configured", "Enter " + ", ".join(missing) + ".")

    async def _token(self, client: httpx.AsyncClient, scope: str) -> str:
        try:
            r = await client.post(TOKEN_URL.format(tenant=self.tenant), data={
                "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret, "scope": scope})
        except httpx.HTTPError as exc:
            raise ConnectorError("unreachable", f"Microsoft sign-in did not answer ({type(exc).__name__}).")
        if r.status_code >= 400:
            raise ConnectorError("unauthorized", f"Microsoft sign-in refused the service principal (HTTP {r.status_code}).")
        return r.json()["access_token"]

    async def _get(self, client, url: str, token: str) -> Any:
        try:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise ConnectorError("unreachable", f"Azure did not answer ({type(exc).__name__}).")
        if r.status_code in (401, 403):
            raise ConnectorError("unauthorized", f"Azure refused access to {url.split('?')[0].replace(ARM, '')} (HTTP {r.status_code}). "
                                                 "Give the service principal Reader on the subscription.")
        if r.status_code >= 400:
            raise ConnectorError("failed", f"Azure answered HTTP {r.status_code}.")
        return r.json()

    async def _list(self, client, url: str, token: str) -> list[dict]:
        out: list[dict] = []
        while url:
            body = await self._get(client, url, token)
            out.extend(body.get("value") or [])
            url = body.get("nextLink")
        return out

    async def test(self) -> dict:
        self._check()
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            token = await self._token(client, f"{ARM}/.default")
            accounts = await self._list(client, f"{ARM}/subscriptions/{self.subscriptions[0]}/providers/Microsoft.CognitiveServices/accounts?api-version={ACCOUNTS_API}", token)
        ai = [a for a in accounts if a.get("kind") in AI_KINDS]
        return {"ok": True, "message": f"Connected. {len(ai)} Azure OpenAI or AI Services account(s) in the first subscription."}

    async def sync(self) -> list[Finding]:
        self._check()
        findings: list[Finding] = []
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            token = await self._token(client, f"{ARM}/.default")
            for sub in self.subscriptions:
                accounts = await self._list(client, f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts?api-version={ACCOUNTS_API}", token)
                for acc in accounts:
                    if acc.get("kind") not in AI_KINDS:
                        continue
                    deployments = await self._list(client, f"{ARM}{acc['id']}/deployments?api-version={ACCOUNTS_API}", token)
                    for d in deployments:
                        model = ((d.get("properties") or {}).get("model") or {})
                        findings.append(Finding(
                            kind="cloud_deployment", external_id=d["id"], name=f"{acc['name']}/{d['name']}",
                            url=f"https://portal.azure.com/#resource{d['id']}",
                            details={"account": acc["name"], "accountKind": acc.get("kind"), "location": acc.get("location"),
                                     "deployment": d["name"], "model": model.get("name"), "modelVersion": model.get("version"),
                                     "sku": (d.get("sku") or {}).get("name"), "capacity": (d.get("sku") or {}).get("capacity"),
                                     "subscription": sub, "resourceGroup": acc["id"].split("/")[4] if acc["id"].count("/") > 4 else None}))
                    if acc.get("kind") == "AIServices":
                        findings.extend(await self._foundry_agents(client, acc))
        return findings

    async def _foundry_agents(self, client, acc: dict) -> list[Finding]:
        """Agents of the account's Foundry projects. Needs a data-plane role (Azure AI User);
        without it the account still reports its deployments, and the reason is noted."""
        try:
            arm = await self._token(client, f"{ARM}/.default")
            projects = await self._list(client, f"{ARM}{acc['id']}/projects?api-version={PROJECTS_API}", arm)
            data_token = await self._token(client, "https://ai.azure.com/.default")
        except ConnectorError:
            return []
        out: list[Finding] = []
        for p in projects:
            name = p["name"].split("/")[-1]
            url = f"https://{acc['name']}.services.ai.azure.com/api/projects/{name}/assistants?api-version=v1"
            try:
                body = await self._get(client, url, data_token)
            except ConnectorError:
                continue
            for agent in body.get("data") or []:
                out.append(Finding(kind="cloud_agent", external_id=f"{acc['id']}/projects/{name}/agents/{agent.get('id')}",
                                   name=agent.get("name") or agent.get("id"), url=None,
                                   details={"account": acc["name"], "project": name, "model": agent.get("model"),
                                            "description": agent.get("description"), "tools": [t.get("type") for t in agent.get("tools") or []],
                                            "createdAt": agent.get("created_at")}))
        return out
