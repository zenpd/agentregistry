"""The connectors against recorded answers of Langfuse, GitHub and Azure
(httpx MockTransport), and the stored-finding lifecycle. No outside system is
called: these tests prove the parsing and the rules, not a live connection."""
from __future__ import annotations

import base64
import json

import httpx
import pytest
import pytest_asyncio

from connectors.azure_ai import AzureAIConnector
from connectors.base import ConnectorError, seal, unseal
from connectors.github import GitHubConnector, _dep_hits
from connectors.langfuse import LangfuseConnector, rollup


def _json(body, status=200, headers=None):
    return httpx.Response(status, json=body, headers=headers or {})


def langfuse_transport(status=200):
    def handler(req: httpx.Request):
        if status != 200:
            return _json({"message": "no"}, status)
        p = req.url.path
        if p == "/api/public/projects":
            return _json({"data": [{"id": "proj-1", "name": "claims-bot"}]})
        if p == "/api/public/traces":
            return _json({"data": [{"name": "triage", "timestamp": "2026-10-07T10:00:00Z"}, {"name": "triage", "timestamp": "2026-10-08T09:00:00Z"}],
                          "meta": {"totalPages": 1}})
        if p == "/api/public/observations":
            return _json({"data": [
                {"model": "gpt-4.1-mini", "startTime": "2026-10-07T10:00:01Z", "usageDetails": {"input": 100, "output": 20}},
                {"model": "gpt-4.1-mini", "startTime": "2026-10-07T11:00:01Z", "usage": {"promptTokens": 50, "completionTokens": 5}},
                {"model": "gpt-4.1", "startTime": "2026-10-08T09:00:01Z", "usageDetails": {"input": 10, "output": 1}}], "meta": {"totalPages": 1}})
        return _json({}, 404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_langfuse_project_finding_and_daily_usage():
    c = LangfuseConnector({"host": "https://lf.example"}, {"public_key": "pk", "secret_key": "sk"}, transport=langfuse_transport())
    [f] = await c.sync()
    assert f.kind == "trace_project" and f.name == "claims-bot" and f.details["traceNames"] == ["triage"]
    assert f.details["models"][0] == "gpt-4.1-mini" and f.details["lastSeen"] == "2026-10-08T09:00:00Z"
    usage = await c.daily_usage(30)
    assert [(str(u["day"]), u["model"], u["calls"], u["input_tokens"], u["output_tokens"]) for u in usage] == [
        ("2026-10-07", "gpt-4.1-mini", 2, 150, 25), ("2026-10-08", "gpt-4.1", 1, 10, 1)]
    bad = LangfuseConnector({}, {"public_key": "pk", "secret_key": "sk"}, transport=langfuse_transport(401))
    with pytest.raises(ConnectorError) as e:
        await bad.test()
    assert e.value.status == "unauthorized"
    with pytest.raises(ConnectorError) as e:
        await LangfuseConnector({}, {}).test()
    assert e.value.status == "not_configured"


def test_dependency_signals():
    f, mcp, tracing = _dep_hits('langgraph>=0.2\nlangchain-openai\nmcp==1.2\nopeninference-instrumentation-langchain\n')
    assert "LangGraph" in f and mcp is True and tracing == {"OpenInference"}
    f, mcp, _ = _dep_hits(json.dumps({"dependencies": {"@openai/agents": "^0.1", "@modelcontextprotocol/sdk": "1"}}))
    assert f == {"OpenAI Agents SDK"} and mcp is True
    assert _dep_hits("requests\nflask\n")[0] == set()


def github_transport():
    def b64(text):
        return {"encoding": "base64", "size": len(text), "content": base64.b64encode(text.encode()).decode()}

    def handler(req: httpx.Request):
        p = req.url.path
        if p == "/orgs/acme/repos":
            return _json([{"name": "claims-agent", "full_name": "acme/claims-agent", "default_branch": "main", "html_url": "https://github.com/acme/claims-agent",
                           "description": "Handles claims", "language": "Python", "pushed_at": "2026-10-01T00:00:00Z"},
                          {"name": "website", "full_name": "acme/website", "default_branch": "main", "html_url": "https://github.com/acme/website"},
                          {"name": "forked", "full_name": "acme/forked", "fork": True}])
        if p == "/repos/acme/claims-agent/git/trees/main":
            return _json({"tree": [{"type": "blob", "path": "requirements.txt"}, {"type": "blob", "path": ".well-known/agent-card.json"},
                                   {"type": "blob", "path": ".vscode/mcp.json"}, {"type": "blob", "path": "app/main.py"}]})
        if p == "/repos/acme/website/git/trees/main":
            return _json({"tree": [{"type": "blob", "path": "package.json"}]})
        if p == "/repos/acme/claims-agent/contents/requirements.txt":
            return _json(b64("crewai==0.80\nlangfuse\n"))
        if p == "/repos/acme/claims-agent/contents/.well-known/agent-card.json":
            return _json(b64(json.dumps({"name": "Claims Agent", "description": "Triages insurance claims", "skills": [{"name": "Claim triage"}]})))
        if p == "/repos/acme/website/contents/package.json":
            return _json(b64(json.dumps({"dependencies": {"react": "18"}})))
        return _json({}, 404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_github_finds_agent_repositories_only():
    c = GitHubConnector({"orgs": ["acme"]}, {}, transport=github_transport())
    [f] = await c.sync()
    assert f.external_id == "acme/claims-agent" and f.name == "Claims Agent"
    assert f.details["frameworks"] == ["CrewAI"] and f.details["tracing"] == ["Langfuse"]
    assert f.details["mcpConfigs"] == [".vscode/mcp.json"] and f.details["agentCard"]["skills"] == ["Claim triage"]


def azure_transport():
    def handler(req: httpx.Request):
        if req.url.host == "login.microsoftonline.com":
            return _json({"access_token": "t"})
        p = req.url.path
        if p.endswith("/providers/Microsoft.CognitiveServices/accounts"):
            return _json({"value": [{"id": "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/aoai1",
                                     "name": "aoai1", "kind": "OpenAI", "location": "eastus"},
                                    {"id": "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/speech",
                                     "name": "speech", "kind": "SpeechServices"}]})
        if p.endswith("/accounts/aoai1/deployments"):
            return _json({"value": [{"id": "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/aoai1/deployments/gpt41mini",
                                     "name": "gpt41mini", "properties": {"model": {"name": "gpt-4.1-mini", "version": "2025-04-14"}},
                                     "sku": {"name": "GlobalStandard", "capacity": 50}}]})
        return _json({}, 404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_azure_lists_model_deployments_of_ai_accounts():
    c = AzureAIConnector({"tenantId": "t", "clientId": "c", "subscriptions": ["s1"]}, {"clientSecret": "x"}, transport=azure_transport())
    [f] = await c.sync()
    assert f.kind == "cloud_deployment" and f.name == "aoai1/gpt41mini"
    assert f.details["model"] == "gpt-4.1-mini" and f.details["resourceGroup"] == "rg" and f.details["capacity"] == 50
    with pytest.raises(ConnectorError) as e:
        await AzureAIConnector({}, {}).sync()
    assert e.value.status == "not_configured" and "tenant id" in e.value.message


def test_secrets_are_sealed_and_unsealed():
    token = seal({"token": "ghp_123"})
    assert "ghp_123" not in token and unseal(token) == {"token": "ghp_123"}
    assert rollup([{"model": "m", "startTime": "bad"}]) == []


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(Agent(id="claims", org_id="org-default", slug="claims", name="Claims Agent", owner="x", description="x"))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_findings_are_stored_matched_dismissed_and_linked(client, monkeypatch):
    from services import connectors as svc

    real_build = svc.build
    monkeypatch.setattr(svc, "build", lambda config, transport=None: real_build(config, transport=github_transport()))
    created = (await client.post("/api/v1/connectors", json={"kind": "github", "label": "Acme GitHub", "settings": {"orgs": ["acme"]},
                                                             "secret": {"token": "ghp_secret"}})).json()
    assert created["secretSet"] == ["token"] and "ghp_secret" not in json.dumps(created)
    assert (await client.post(f"/api/v1/connectors/{created['id']}/sync")).json()["found"] == 1
    data = (await client.get("/api/v1/connectors/findings")).json()
    [f] = data["findings"]
    assert f["matches"][0]["agentId"] == "claims" and f["connector"]["label"] == "Acme GitHub"
    prefill = (await client.get(f"/api/v1/connectors/findings/{f['id']}/prefill")).json()
    assert prefill["fields"]["description"] == "Triages insurance claims" and prefill["fields"]["capabilities"] == ["Claim triage"]
    linked = await client.post(f"/api/v1/connectors/findings/{f['id']}/link", json={"agentId": "claims"})
    assert linked.json()["status"] == "linked"
    agent = (await client.get("/api/v1/agents/claims")).json()
    assert agent.get("sourceRepo") == "https://github.com/acme/claims-agent"
    # A rescan keeps the person's decision.
    await client.post(f"/api/v1/connectors/{created['id']}/sync")
    assert (await client.get("/api/v1/connectors/findings")).json()["summary"] == {"new": 0, "dismissed": 0, "linked": 1}
