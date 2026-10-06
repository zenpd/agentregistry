"""Phoenix discovery (the inbox) and the paste-a-URL prefill. Throwaway DB;
Phoenix and target hosts are faked, never called."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from orchestrations import phoenix_discovery as pd

user = {"user_id": "u1", "role": "admin"}


def span(kind="LLM", model=None, tool=None, mcp=None, agent=None, start=None, name="s", extra=None):
    attrs = {"openinference.span.kind": kind, "input.value": "SECRET PROMPT"}
    if model: attrs["llm.model_name"] = model
    if tool: attrs["tool.name"] = tool
    if mcp: attrs["mcp.server"] = mcp
    if agent: attrs["agent.name"] = agent
    attrs.update(extra or {})
    return {"name": name, "span_kind": kind, "start_time": start or "2026-09-30T10:00:00Z", "attributes": attrs}


def test_summary_reads_names_and_counts_only():
    s = pd.summarize_spans([
        span(model="gpt-4o"), span(model="gpt-4o"), span(model="gpt-4o-mini"),
        span(kind="TOOL", tool="lookup_customer"), span(kind="TOOL", name="send_sms"),
        span(mcp="crm-mcp"), span(kind="AGENT", agent="onboarding"), span(kind="AGENT", agent="next_agent"),
        span(start="2026-10-01T08:00:00Z", extra={"service.name": "digital-onboarding", "output.value": "SECRET"}),
    ])
    assert s["span_count"] == 9
    assert s["models"] == ["gpt-4o", "gpt-4o-mini"]            # most used first
    assert set(s["tools"]) == {"lookup_customer", "send_sms"}  # a TOOL span with no tool.name uses its span name
    assert s["mcp_servers"] == ["crm-mcp"]
    assert s["agent_names"] == ["onboarding"]                  # LangGraph plumbing is not an agent
    assert set(s["span_kinds"]) == {"LLM", "TOOL", "AGENT"}
    assert s["last_seen"] == datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    assert s["attribute_keys"] == ["agent.name", "service.name"]  # names only, never prompt or answer attributes
    assert "SECRET" not in repr(s)


def test_summary_of_a_quiet_project():
    s = pd.summarize_spans([])
    assert s["span_count"] == 0 and s["last_seen"] is None and s["models"] == []


class FakeClient:
    spans_by_project: dict = {}
    projects_list: list = []
    fail_auth = False

    def __init__(self, base_url, api_key=None, **_):
        self.api_key = api_key

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None

    async def all_projects(self, **_):
        if FakeClient.fail_auth:
            raise pd.PhoenixError("GET", "x", 401, "no")
        return [{"name": n, "id": n} for n in FakeClient.projects_list]

    async def spans(self, project, start_time=None, **_):
        since = pd._parse_time(start_time) if start_time else None
        for s in FakeClient.spans_by_project.get(project, []):
            if since is None or pd._parse_time(s["start_time"]) >= since:
                yield s


@pytest_asyncio.fixture
async def env(monkeypatch):
    from db.base import Base, engine, get_db_session
    from db.models import Agent, Organization

    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    FakeClient.fail_auth = False
    FakeClient.projects_list = ["digital-onboarding", "payment-orchestrator", "scratch", "old-bot", "empty-one"]
    FakeClient.spans_by_project = {
        "digital-onboarding": [span(model="gpt-4o", start=recent), span(kind="TOOL", tool="kyc_check", start=recent)],
        "payment-orchestrator": [span(model="gpt-4o-mini", start=recent, agent="payments", kind="AGENT")],
        "scratch": [span(model="gpt-4o", start=recent)],
    }
    monkeypatch.setattr(pd, "PhoenixClient", FakeClient)

    async def fake_endpoint(db, agent=None):
        return "https://phoenix.test", "key"
    monkeypatch.setattr("api.routers.registry._resolve_phoenix_endpoint", fake_endpoint)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="reg", org_id="org-default", slug="reg", name="Registered Bot", owner="Ops",
                        lifecycle_stage="Production", description="x", phoenix_project="old-bot"))
        yield
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(env):
    from api.auth import require_read, require_update
    from api.routers.ops.discovery import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_read] = lambda: dict(user)
    app.dependency_overrides[require_update] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_scan_then_inbox_lists_only_unlinked_projects(client):
    result = await pd.discover_phoenix()
    assert result["status"] == "ok" and result["projects"] == 5
    assert result["new"] == 4 and result["linked"] == 1          # old-bot is already a registered agent
    inbox = (await client.get("/api/v1/discovery/phoenix")).json()
    assert inbox["configured"] is True
    assert {r["name"] for r in inbox["inbox"]} == {"digital-onboarding", "payment-orchestrator", "scratch", "empty-one"}
    onboarding = next(r for r in inbox["inbox"] if r["name"] == "digital-onboarding")
    assert onboarding["activity"] == "active" and onboarding["models"] == ["gpt-4o"] and onboarding["tools"] == ["kyc_check"]
    assert next(r for r in inbox["inbox"] if r["name"] == "empty-one")["activity"] == "none"
    assert [r["agentId"] for r in inbox["registered"]] == ["reg"]


@pytest.mark.asyncio
async def test_quiet_and_stale_projects_show_their_real_last_seen(client):
    def ago(days): return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    FakeClient.projects_list = ["sleepy", "gone-cold"]
    FakeClient.spans_by_project = {"sleepy": [span(model="gpt-4o", start=ago(12))], "gone-cold": [span(model="gpt-4o", start=ago(60))]}
    await pd.discover_phoenix()
    rows = {r["name"]: r for r in (await client.get("/api/v1/discovery/phoenix")).json()["inbox"]}
    assert rows["sleepy"]["activity"] == "quiet" and rows["sleepy"]["spanCount"] == 0 and rows["sleepy"]["lastSeen"]
    assert rows["gone-cold"]["activity"] == "stale"
    inbox = (await client.get("/api/v1/discovery/phoenix")).json()
    assert inbox["summary"]["newActive"] == 0 and inbox["sampleCap"] == 300


@pytest.mark.asyncio
async def test_dismiss_needs_a_reason_and_hides_until_restored(client):
    await pd.discover_phoenix()
    assert (await client.post("/api/v1/discovery/phoenix/dismiss", json={"name": "scratch"})).status_code == 422
    assert (await client.post("/api/v1/discovery/phoenix/dismiss", json={"name": "scratch", "reason": "test run"})).status_code == 200
    await pd.discover_phoenix()                                   # a re-scan does not bring it back
    inbox = (await client.get("/api/v1/discovery/phoenix")).json()
    assert "scratch" not in {r["name"] for r in inbox["inbox"]}
    assert inbox["dismissed"][0]["dismissReason"] == "test run"
    await client.post("/api/v1/discovery/phoenix/restore", json={"name": "scratch"})
    assert "scratch" in {r["name"] for r in (await client.get("/api/v1/discovery/phoenix")).json()["inbox"]}


@pytest.mark.asyncio
async def test_prefill_uses_only_what_traces_say(client):
    await pd.discover_phoenix()
    p = (await client.get("/api/v1/discovery/phoenix/prefill", params={"name": "payment-orchestrator"})).json()
    assert p["fields"]["name"] == "Payment Orchestrator"
    assert p["fields"]["model_name"] == "gpt-4o-mini" and p["fields"]["ai_type"] == "Autonomous Agent"
    assert "owner" not in p["fields"] and "owner" in p["missing"]   # never guessed
    assert p["sources"]["model_name"].startswith("Phoenix:")
    assert (await client.get("/api/v1/discovery/phoenix/prefill", params={"name": "nope"})).status_code == 404


@pytest.mark.asyncio
async def test_a_project_phoenix_no_longer_lists_is_dropped(client):
    await pd.discover_phoenix()
    FakeClient.projects_list = ["digital-onboarding"]
    await pd.discover_phoenix()
    names = {r["name"] for r in (await client.get("/api/v1/discovery/phoenix")).json()["inbox"]}
    assert names == {"digital-onboarding"}


@pytest.mark.asyncio
async def test_rejected_key_is_reported_not_raised(env):
    FakeClient.fail_auth = True
    r = await pd.discover_phoenix()
    assert r["status"] == "unreachable" and "key" in r["reason"].lower()


@pytest.mark.asyncio
async def test_not_configured(env, monkeypatch):
    async def none(db, agent=None): return None, None
    monkeypatch.setattr("api.routers.registry._resolve_phoenix_endpoint", none)
    assert (await pd.discover_phoenix())["status"] == "not_configured"


def test_phoenix_discovery_is_a_scheduled_job():
    from orchestrations import job_runner
    assert "phoenix_discovery" in job_runner.JOBS
    assert job_runner.availability(job_runner.JOBS["phoenix_discovery"])[0] is True


# ── paste-a-URL prefill ─────────────────────────────────────────────────────

def test_card_check_names_the_problems():
    from api.routers.ops.discovery import card_check
    assert card_check({"name": "A", "description": "d", "url": "https://x", "skills": []})["conformant"] is True
    bad = card_check({"name": "A"})
    assert not bad["conformant"] and "Missing description" in bad["problems"]
    assert card_check([1])["conformant"] is False


class FakeProbe:
    """Stands in for integrate._probe-level HTTP: path -> (status, json)."""
    routes: dict = {}


@pytest_asyncio.fixture
async def url_client(env, monkeypatch):
    from api.routers.ops import discovery as d, integrate
    import json

    integrate._recent_calls.clear()                              # the per-minute limit is shared by the whole test run

    async def fake_resolve(host, port): return ["10.0.0.5"]
    monkeypatch.setattr(integrate, "_resolve", fake_resolve)

    async def fake_probe(client, url, limit, ip=None):
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
        hit = FakeProbe.routes.get(path)
        if hit is None:
            return {"url": url, "status": 404, "ok": False, "raw": b"", "truncated": False, "redirect": None}
        return {"url": url, "status": 200, "ok": True, "raw": json.dumps(hit).encode(), "truncated": False, "redirect": None}
    monkeypatch.setattr(d, "_probe", fake_probe)

    from api.auth import require_read, require_update
    app = FastAPI()
    app.include_router(d.router)
    app.dependency_overrides[require_read] = lambda: dict(user)
    app.dependency_overrides[require_update] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_prefill_prefers_card_then_openapi_and_uses_the_be_sibling(url_client):
    FakeProbe.routes = {
        "/.well-known/agent-card.json": {"name": "Onboarding Agent", "description": "Opens accounts", "url": "https://x",
                                          "skills": [{"name": "open account"}]},
        "/openapi.json": {"openapi": "3.0.0", "info": {"title": "Onboarding API", "description": "API"},
                          "paths": {"/open": {"post": {"summary": "Open an account"}}}},
        "/health": {"ok": True},
    }
    r = (await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://onboarding-fe.env.azurecontainerapps.io/app"})).json()
    assert r["ok"] and r["base"] == "https://onboarding-be.env.azurecontainerapps.io" and r["usedSibling"] is True
    assert r["fields"]["name"] == "Onboarding Agent" and r["sources"]["name"].startswith("Agent card")
    assert r["fields"]["capabilities"] == ["open account"]
    assert r["fields"]["api_endpoint"] == "https://onboarding-fe.env.azurecontainerapps.io/app"
    assert r["card"]["conformant"] is True and r["openapi"]["operations"] == 1 and r["health"]["ok"] is True


@pytest.mark.asyncio
async def test_prefill_falls_back_to_openapi_and_reports_a_legacy_card(url_client):
    FakeProbe.routes = {
        "/.well-known/agent.json": {"name": "Legacy", "description": "d"},
        "/openapi.json": {"openapi": "3.1.0", "info": {"title": "T"}, "paths": {"/a": {"get": {"summary": "List a"}}}},
    }
    r = (await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://svc.example.com"})).json()
    assert r["card"]["found"] and r["card"]["legacyPath"] is True and r["card"]["conformant"] is False
    assert r["fields"]["name"] == "Legacy"
    FakeProbe.routes = {"/openapi.json": {"openapi": "3.1.0", "info": {"title": "Only API"}, "paths": {"/a": {"get": {"summary": "List a"}}}}}
    r = (await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://svc.example.com"})).json()
    assert r["fields"]["name"] == "Only API" and r["sources"]["name"] == "OpenAPI title" and r["card"]["found"] is False


@pytest.mark.asyncio
async def test_prefill_refuses_bad_and_unsafe_addresses(url_client, monkeypatch):
    for bad in ("ftp://x.example.com", "not a url", "https://user:pw@x.example.com"):
        assert (await url_client.post("/api/v1/agents/prefill-url", json={"url": bad})).status_code == 422
    from api.routers.ops import integrate
    async def metadata(host, port): return ["169.254.169.254"]
    monkeypatch.setattr(integrate, "_resolve", metadata)
    r = await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://evil.example.com"})
    assert r.status_code == 422 and "link-local" in r.json()["detail"]


@pytest.mark.asyncio
async def test_prefill_reports_dns_failure_with_a_hint(url_client, monkeypatch):
    from api.routers.ops import integrate
    async def nodns(host, port): raise OSError(8, "nodename nor servname provided")
    monkeypatch.setattr(integrate, "_resolve", nodns)
    r = (await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://x-be.internal.example.com"})).json()
    assert r["ok"] is False and "VPN" in r["hint"]


# ── finding the app from the project name ───────────────────────────────────

def test_address_candidates_try_the_name_then_drop_one_generic_word():
    from api.routers.ops.discovery import address_candidates
    t = "https://{project}-be.env.example.io"
    assert address_candidates(t, "payment-orchestrator") == ["https://payment-orchestrator-be.env.example.io"]
    assert address_candidates(t, "Digital_Onboarding Assistant") == [
        "https://digital-onboarding-assistant-be.env.example.io", "https://digital-onboarding-be.env.example.io"]
    assert address_candidates(t, "agentzoo-builder") == ["https://agentzoo-builder-be.env.example.io"]  # not a generic word
    assert address_candidates(t, "!!!") == [] and address_candidates("https://fixed.example.io", "x") == []


def test_openapi_io_lists_declared_fields_only():
    from governance.reuse import openapi_io
    spec = {"paths": {
        "/pay": {"post": {"summary": "Orchestrate Payment",
                          "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pay"}}}},
                          "responses": {"200": {"content": {"application/json": {"schema": {
                              "type": "array", "items": {"type": "object", "properties": {"rail": {}, "fee": {}}}}}}}}}},
        "/health": {"get": {"summary": "Health", "responses": {"200": {"description": "ok"}}}},
        "/bad": "nonsense",
    }, "components": {"schemas": {"Pay": {"type": "object", "properties": {"amount": {}, "currency": {}}}}}}
    assert openapi_io(spec) == {"inputs": ["Orchestrate Payment: amount, currency"],
                                "outputs": ["Orchestrate Payment: rail, fee"]}
    assert openapi_io({"nope": 1}) == {"inputs": [], "outputs": []}
    # A line never exceeds what the contract accepts, and never cuts a field name in half.
    from governance.reuse import MAX_ITEM_CHARS, clean_list
    wide = {"paths": {"/x": {"post": {"summary": "S" * 60, "requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "properties": {f"a_rather_long_field_name_{i}": {} for i in range(8)}}}}}}}}}
    lines = openapi_io(wide)["inputs"]
    assert len(lines[0]) <= MAX_ITEM_CHARS and lines[0].endswith(", …") and clean_list(lines) == lines
    for width in range(1, 40):                                    # every label length, so no off-by-one survives
        spec = {"paths": {"/x": {"post": {"summary": "S" * width, "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {f"field_{i}_{'x' * (i * 3)}": {} for i in range(8)}}}}}}}}}
        assert all(len(l) <= MAX_ITEM_CHARS for l in openapi_io(spec)["inputs"])


@pytest_asyncio.fixture
async def find_client(url_client):
    from db.base import get_db_session
    from db.models import Agent, PhoenixConfig
    async with get_db_session() as s:
        s.add(PhoenixConfig(id="c1", org_id="org-default", endpoint="https://phoenix.test", enabled=True,
                            app_url_template="https://{project}-be.env.example.io"))
        s.add(Agent(id="kyc", org_id="org-default", slug="kyc-checker", name="KYC Checker", owner="Ops",
                    lifecycle_stage="Production", description="x"))
    FakeClient.projects_list = ["digital-onboarding-assistant", "lonely"]
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    FakeClient.spans_by_project = {"digital-onboarding-assistant": [
        span(kind="AGENT", agent="kyc_checker", start=recent), span(kind="RETRIEVER", name="policy-index", start=recent)]}
    await pd.discover_phoenix()
    yield url_client


@pytest.mark.asyncio
async def test_find_app_uses_the_saved_pattern_and_labels_the_guess(find_client, monkeypatch):
    from api.routers.ops import discovery as d, integrate
    import json

    async def resolve(host, port):
        if host.startswith("digital-onboarding-assistant"):
            raise OSError(8, "nodename nor servname provided")
        return ["10.0.0.5"]
    monkeypatch.setattr(integrate, "_resolve", resolve)
    FakeProbe.routes = {"/openapi.json": {"openapi": "3.0.0", "info": {"title": "Onboarding API", "description": "Opens accounts"},
                                          "paths": {"/open": {"post": {"summary": "Open", "requestBody": {"content": {
                                              "application/json": {"schema": {"type": "object", "properties": {"customer": {}}}}}}}}}}}
    r = (await find_client.post("/api/v1/discovery/phoenix/find-app", json={"name": "digital-onboarding-assistant"})).json()
    assert r["found"] and r["guessed"] and r["base"] == "https://digital-onboarding-be.env.example.io"
    assert len(r["tried"]) == 2 and "guessed" in r["sources"]["api_endpoint"].lower()
    assert r["fields"]["description"] == "Opens accounts" and r["fields"]["inputs"] == ["Open: customer"]

    FakeProbe.routes = {}                                         # a host answers, but it is not an API
    r = (await find_client.post("/api/v1/discovery/phoenix/find-app", json={"name": "lonely"})).json()
    assert r["found"] is False and r["reason"] == "no_answer"


@pytest.mark.asyncio
async def test_prefill_adds_called_agents_and_knowledge_bases(find_client):
    p = (await find_client.get("/api/v1/discovery/phoenix/prefill", params={"name": "digital-onboarding-assistant"})).json()
    assert p["fields"]["calls"] == ["kyc"] and p["fields"]["knowledge_bases"] == ["policy-index"]
    assert p["canFindApp"] is True


@pytest.mark.asyncio
async def test_find_app_without_a_pattern_says_so(url_client):
    await pd.discover_phoenix()
    r = (await url_client.post("/api/v1/discovery/phoenix/find-app", json={"name": "scratch"})).json()
    assert r == {"ok": False, "found": False, "reason": "no_template", "tried": []}


def test_address_pattern_must_contain_project():
    from api.routers.registry import PhoenixConfigUpdate
    assert PhoenixConfigUpdate(app_url_template=" https://{project}-be.x.io ").app_url_template == "https://{project}-be.x.io"
    assert PhoenixConfigUpdate().app_url_template is None
    with pytest.raises(ValueError):
        PhoenixConfigUpdate(app_url_template="https://fixed.x.io")


@pytest.mark.asyncio
async def test_changing_the_phoenix_address_clears_what_was_found_but_keeps_dismissals(client):
    from api.auth import require_admin
    from api.routers.registry import phoenix_router
    from db.base import get_db_session
    from db.models import PhoenixConfig

    async with get_db_session() as s:
        s.add(PhoenixConfig(id="c1", org_id="org-default", endpoint="https://old.test", enabled=True))
    await pd.discover_phoenix()
    await client.post("/api/v1/discovery/phoenix/dismiss", json={"name": "scratch", "reason": "test run"})
    app = FastAPI()
    app.include_router(phoenix_router)
    app.dependency_overrides[require_admin] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as admin:
        # Saving only the address pattern leaves the list alone.
        await admin.put("/api/v1/phoenix/config", json={"endpoint": "https://old.test", "enabled": True,
                                                        "app_url_template": "https://{project}.x.io"})
        assert len((await client.get("/api/v1/discovery/phoenix")).json()["inbox"]) == 3
        await admin.put("/api/v1/phoenix/config", json={"endpoint": "https://new.test", "enabled": True})
    inbox = (await client.get("/api/v1/discovery/phoenix")).json()
    assert inbox["inbox"] == [] and inbox["registered"] == [] and inbox["needsScan"] is True
    assert [r["name"] for r in inbox["dismissed"]] == ["scratch"]
    async with get_db_session() as s:
        from sqlalchemy import select
        assert (await s.execute(select(PhoenixConfig.app_url_template))).scalar_one() == "https://{project}.x.io"  # kept


@pytest.mark.asyncio
async def test_a_phoenix_that_does_not_answer_gets_a_plain_message(env, monkeypatch):
    async def silent(self, **_): raise pd.PhoenixError("GET", "x", 0, "")
    monkeypatch.setattr(FakeClient, "all_projects", silent)
    r = await pd.discover_phoenix()
    assert r["status"] == "unreachable" and "VPN" in r["reason"] and "HTTP 0" not in r["reason"]


@pytest.mark.asyncio
async def test_the_project_list_is_tried_twice_when_phoenix_is_waking_up():
    from discovery.phoenix_client import PhoenixClient, PhoenixError
    calls = []
    async with PhoenixClient("https://phoenix.test") as c:
        async def fake_get(path, **kw):
            calls.append(path)
            if len(calls) == 1:
                raise PhoenixError("GET", path, 0, "")
            return {"data": [{"name": "a", "id": "1"}], "next_cursor": None}
        c._get = fake_get
        assert [p["name"] for p in await c.all_projects()] == ["a"] and len(calls) == 2
        calls.clear()
        async def refused(path, **kw):
            calls.append(path); raise PhoenixError("GET", path, 401, "no")
        c._get = refused
        with pytest.raises(PhoenixError):
            await c.all_projects()
        assert len(calls) == 1                                     # a rejected key is not retried


# ── hardening from the review ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_odd_addresses_are_refused_not_500(url_client, monkeypatch):
    from api.routers.ops import integrate
    for bad in ("http://host:99999", "http://host:abc"):
        r = await url_client.post("/api/v1/agents/prefill-url", json={"url": bad})
        assert r.status_code == 422, (bad, r.status_code)
    async def too_long(host, port): raise UnicodeError("label too long")      # what getaddrinfo raises for a 70-character label
    monkeypatch.setattr(integrate, "_resolve", too_long)
    r = await url_client.post("/api/v1/agents/prefill-url", json={"url": "http://" + "a" * 70 + ".example.com"})
    assert r.status_code == 200 and r.json()["ok"] is False


@pytest.mark.asyncio
async def test_only_standard_ports_outside_development(url_client, monkeypatch):
    from shared.config import get_settings
    monkeypatch.setattr(get_settings(), "app_env", "production")
    r = await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://internal.example.com:6379"})
    assert r.status_code == 422 and "80 and 443" in r.json()["detail"]


@pytest.mark.asyncio
async def test_the_response_does_not_list_per_path_results(url_client):
    FakeProbe.routes = {"/openapi.json": {"openapi": "3.0.0", "info": {"title": "T"}, "paths": {"/a": {"get": {"summary": "A"}}}}}
    r = (await url_client.post("/api/v1/agents/prefill-url", json={"url": "https://svc.example.com"})).json()
    assert "probes" not in r


def test_cloud_platform_addresses_are_refused():
    from governance.reuse import TryItBlocked, check_addresses
    for ip in ("168.63.129.16", "100.100.100.200", "169.254.169.254"):
        with pytest.raises(TryItBlocked):
            check_addresses([ip], allow_loopback=False)
    check_addresses(["10.1.4.241"], allow_loopback=False)           # private ranges stay allowed


def test_long_project_names_do_not_make_invalid_host_names():
    from api.routers.ops.discovery import address_candidates
    assert address_candidates("https://{project}-be.x.io", "a" * 80) == []


@pytest.mark.asyncio
async def test_project_names_are_quoted_in_the_path():
    from discovery.phoenix_client import PhoenixClient
    seen = []
    async with PhoenixClient("https://phoenix.test") as c:
        async def fake_get(path, **kw):
            seen.append(path); return {"data": [], "next_cursor": None}
        c._get = fake_get
        [_ async for _ in c.spans("a/b?c#d%e")]
    assert seen == ["/v1/projects/a%2Fb%3Fc%23d%25e/spans"]


@pytest.mark.asyncio
async def test_a_page_that_is_not_json_is_a_failure_to_read_not_a_crash():
    from discovery.phoenix_client import PhoenixClient, PhoenixError

    def handler(request):
        return httpx.Response(200, text="<html>login</html>")
    async with PhoenixClient("https://phoenix.test") as c:
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://phoenix.test")
        with pytest.raises(PhoenixError):
            await c.all_projects()


@pytest.mark.asyncio
async def test_a_failed_last_seen_read_keeps_the_project(client, monkeypatch):
    class Flaky(FakeClient):
        async def spans(self, project, start_time=None, **kw):
            if start_time is None:
                raise pd.PhoenixError("GET", "x", 500, "boom")
            return
            yield
    monkeypatch.setattr(pd, "PhoenixClient", Flaky)
    FakeClient.projects_list = ["quiet-one"]
    FakeClient.spans_by_project = {}
    r = await pd.discover_phoenix()
    assert r["failed"] == 0 and r["projects"] == 1


@pytest.mark.asyncio
async def test_spans_are_reduced_before_they_are_kept():
    s = pd._slim({"name": "n", "span_kind": "LLM", "start_time": "t", "attributes": {
        "input.value": "SECRET", "llm.input_messages.0.content": "SECRET", "llm.model_name": "m", "service.name": "svc"}})
    assert s["attributes"] == {"llm.model_name": "m", "service.name": "svc"}


@pytest.mark.asyncio
async def test_a_scan_that_straddles_an_address_change_writes_nothing(client, monkeypatch):
    calls = {"n": 0}
    async def moving(db, agent=None):
        calls["n"] += 1
        return ("https://phoenix.test" if calls["n"] == 1 else "https://other.test"), "key"
    monkeypatch.setattr("api.routers.registry._resolve_phoenix_endpoint", moving)
    r = await pd.discover_phoenix()
    assert r["status"] == "skipped"
    assert (await client.get("/api/v1/discovery/phoenix")).json()["inbox"] == []


@pytest.mark.asyncio
async def test_repointing_phoenix_forgets_the_saved_key_and_is_audited(client):
    from api.auth import require_admin
    from api.routers.registry import phoenix_router
    from db.base import get_db_session
    from db.models import AuditLog, PhoenixConfig
    from sqlalchemy import select
    async with get_db_session() as s:
        s.add(PhoenixConfig(id="c1", org_id="org-default", endpoint="https://old.test", api_key="secret", enabled=True))
    app = FastAPI(); app.include_router(phoenix_router)
    app.dependency_overrides[require_admin] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as admin:
        await admin.put("/api/v1/phoenix/config", json={"endpoint": " https://old.test ", "enabled": True})
        async with get_db_session() as s:
            assert (await s.execute(select(PhoenixConfig.api_key))).scalar_one() == "secret"      # same address: key kept
        await admin.put("/api/v1/phoenix/config", json={"endpoint": "https://new.test", "enabled": True})
        async with get_db_session() as s:
            assert (await s.execute(select(PhoenixConfig.api_key))).scalar_one() is None          # new address: key dropped
            log = (await s.execute(select(AuditLog).where(AuditLog.action == "phoenix_config.update"))).scalars().all()
            assert len(log) == 2 and "secret" not in repr([l.changes for l in log])
        for bad in ("ftp://x", "https://u:p@x.test", "not a url"):
            assert (await admin.put("/api/v1/phoenix/config", json={"endpoint": bad, "enabled": True})).status_code == 422


@pytest.mark.asyncio
async def test_needs_scan_is_false_when_everything_was_dismissed(client):
    await pd.discover_phoenix()
    for n in FakeClient.projects_list:
        await client.post("/api/v1/discovery/phoenix/dismiss", json={"name": n, "reason": "all of them"})
    inbox = (await client.get("/api/v1/discovery/phoenix")).json()
    assert inbox["inbox"] == [] and inbox["needsScan"] is False


# ── background scan, pinned connections ─────────────────────────────────────

def test_requests_are_pinned_to_the_checked_address_but_keep_the_real_name():
    from api.routers.ops.discovery import pinned_request
    url, headers, ext = pinned_request("https://app-be.env.example.io/openapi.json", "10.1.4.241")
    assert url == "https://10.1.4.241/openapi.json" and headers["Host"] == "app-be.env.example.io" and ext == {"sni_hostname": "app-be.env.example.io"}
    url, headers, ext = pinned_request("http://app.example.io:8080/x", "2001:db8::1")
    assert url == "http://[2001:db8::1]:8080/x" and headers["Host"] == "app.example.io:8080"
    assert pinned_request("https://a.example.io/x", None)[0] == "https://a.example.io/x"        # nothing to pin to


@pytest.mark.asyncio
async def test_scan_starts_in_the_background_and_the_inbox_reports_it(client):
    import asyncio
    from api.routers.ops import discovery as d

    gate = asyncio.Event()
    original = pd.discover_phoenix

    async def slow(**kw):
        await gate.wait()
        return await original(**kw)
    from orchestrations import job_runner
    from dataclasses import replace
    job_runner.JOBS["phoenix_discovery"] = replace(job_runner.JOBS["phoenix_discovery"], target=slow)
    try:
        started = await client.post("/api/v1/discovery/phoenix/scan")
        assert started.status_code == 202 and started.json() == {"started": True, "scanning": True}
        again = await client.post("/api/v1/discovery/phoenix/scan")
        assert again.json() == {"started": False, "scanning": True}                               # not started twice
        assert (await client.get("/api/v1/discovery/phoenix")).json()["scanning"] is True
        gate.set()
        await d._scan_task
        inbox = (await client.get("/api/v1/discovery/phoenix")).json()
        assert inbox["scanning"] is False and inbox["summary"]["new"] == 4 and inbox["lastScan"]["status"] == "ok"
    finally:
        job_runner.JOBS["phoenix_discovery"] = replace(job_runner.JOBS["phoenix_discovery"],
                                                       target="orchestrations.phoenix_discovery:discover_phoenix")
