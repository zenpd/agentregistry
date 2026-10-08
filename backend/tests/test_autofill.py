"""Automatic updates to an agent's record: the rules for what may be filled
in, applying and recording them, undoing them, and what reviewers are told.
Throwaway DB; evidence is faked, nothing is fetched and no model is called."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from governance import autofill as rules
from governance.autofill import Past, plan_updates

user = {"user_id": "u1", "role": "admin"}
NOW = datetime.now(timezone.utc)

EMPTY = {"model_name": "GPT-5", "mcp_servers": [], "knowledge_bases": [], "api_endpoint": "https://app-be.x.io",
         "description": "", "capabilities": [], "inputs": [], "outputs": []}
SEEN = [{"name": "ocr_extract_fields", "kind": "tool", "count": 14}, {"name": "sanctions_check", "kind": "tool", "count": 4},
        {"name": "one_off", "kind": "tool", "count": 1}, {"name": "policy-index", "kind": "retriever", "count": 3},
        {"name": "supervisor", "kind": "agent", "count": 72}, {"name": "gpt-4.1-mini", "kind": "model", "count": 20}]


def fields(updates):
    return {u["field"]: u for u in updates}


# ── the rules ───────────────────────────────────────────────────────────────

def test_the_declared_model_is_corrected_to_the_one_in_real_use():
    plan = fields(plan_updates(EMPTY, {"usage_models": [("gpt-4.1-mini", 29)], "usage_days": 30}))
    u = plan["model_name"]
    assert (u["old"], u["new"], u["source"]) == ("GPT-5", "gpt-4.1-mini", "usage")
    assert "29 of its 29 real calls" in u["reason"] and "none used the declared GPT-5" in u["reason"]


@pytest.mark.parametrize("record,usage", [
    (EMPTY, [("gpt-4.1-mini", 4)]),                                              # too few calls to say
    ({**EMPTY, "model_name": "gpt-4.1-mini-2025-04-14"}, [("gpt-4.1-mini", 29)]),  # the same model, with its version
    (EMPTY, [("gpt-4.1-mini", 10), ("gpt-4o", 9)]),                              # no model clearly in use
    (EMPTY, [("gpt-5", 3), ("gpt-4.1-mini", 30)]),                               # the declared model is in use
    (EMPTY, []),
])
def test_the_model_is_left_alone_without_clear_evidence(record, usage):
    assert "model_name" not in fields(plan_updates(record, {"usage_models": usage}))


def test_tools_and_knowledge_sources_seen_in_traces_are_added_never_removed():
    record = {**EMPTY, "mcp_servers": ["SAP MCP Server"]}
    plan = fields(plan_updates(record, {"observed_only": SEEN}))
    assert plan["mcp_servers"]["new"] == ["SAP MCP Server", "ocr_extract_fields", "sanctions_check", "one_off"]
    assert plan["knowledge_bases"]["new"] == ["policy-index"]
    assert "ocr_extract_fields (14 times)" in plan["mcp_servers"]["reason"] and "one_off (once)" in plan["mcp_servers"]["reason"]
    assert all("supervisor" not in str(u["new"]) and "gpt-4.1-mini" not in str(u["new"]) for u in plan.values())  # steps and models are not tools


def test_something_a_person_removed_is_not_added_back():
    history = [Past("mcp_servers", old=[], new=["ocr_extract_fields", "sanctions_check", "one_off"])]
    record = {**EMPTY, "mcp_servers": ["sanctions_check"]}                # the person deleted the other two
    assert "mcp_servers" not in fields(plan_updates(record, {"observed_only": SEEN}, history))
    newly = [*SEEN, {"name": "rag_search", "kind": "tool", "count": 5}]
    assert fields(plan_updates(record, {"observed_only": newly}, history))["mcp_servers"]["new"] == ["sanctions_check", "rag_search"]


def test_a_field_a_person_took_back_is_never_touched_again():
    undone = [Past("model_name", old="GPT-5", new="gpt-4.1-mini", reverted=True),
              Past("mcp_servers", old=[], new=["ocr_extract_fields"], reverted=True),
              Past("description", old="", new="Drafted.", reverted=True)]
    evidence = {"usage_models": [("gpt-4.1-mini", 29)], "observed_only": SEEN,
                "app": {"via": "endpoint", "description": "Routes payments across payment rails."},
                "draft": {"description": "Reads identity documents and runs sanctions checks for new customers."}}
    assert set(fields(plan_updates(EMPTY, evidence, undone))) == {"knowledge_bases"}
    edited = [Past("model_name", old="GPT-5", new="gpt-4.1-mini")]
    assert "model_name" not in fields(plan_updates({**EMPTY, "model_name": "gpt-4o"}, {"usage_models": [("gpt-4.1-mini", 29)]}, edited))
    # still ours and the evidence moved on: it follows
    assert fields(plan_updates({**EMPTY, "model_name": "gpt-4.1-mini"}, {"usage_models": [("gpt-4o", 40)]}, edited))["model_name"]["new"] == "gpt-4o"


def test_text_is_filled_only_where_it_is_empty_and_the_apps_own_words_come_first():
    app = {"via": "endpoint", "url": "https://app-be.x.io", "description": "Routes payments across SWIFT, ACH and local rails.",
           "capabilities": ["Health Check", "Orchestrate Payment", "Root", "List Rails"],
           "inputs": ["Orchestrate Payment: amount, currency"], "outputs": ["Health: status", "Orchestrate Payment: rail, fee"]}
    draft = {"description": "Reads identity documents and runs sanctions checks for new customers.", "capabilities": ["Check sanctions"]}
    plan = fields(plan_updates(EMPTY, {"app": app, "draft": draft}))
    assert plan["description"]["source"] == "app_api" and plan["description"]["new"].startswith("Routes payments")
    assert plan["capabilities"]["new"] == ["Orchestrate Payment", "List Rails"]           # health and root say nothing
    assert plan["outputs"]["new"] == ["Orchestrate Payment: rail, fee"] and plan["inputs"]["source"] == "app_api"
    assert "api_endpoint" not in plan                                                     # an address is already recorded
    written = {**EMPTY, "description": "Owner's own words.", "capabilities": ["Their capability"]}
    assert not {"description", "capabilities"} & set(fields(plan_updates(written, {"app": app, "draft": draft})))


def test_a_draft_is_used_only_when_nothing_else_can_say_it_and_only_within_bounds():
    draft = {"description": "Reads identity documents and runs sanctions checks for new customers.", "capabilities": ["Check sanctions", "Read documents."]}
    plan = fields(plan_updates(EMPTY, {"draft": draft}))
    assert plan["description"]["source"] == "ai_draft" and plan["capabilities"]["new"] == ["Check sanctions", "Read documents"]
    assert "description" not in fields(plan_updates(EMPTY, {"draft": {"description": "Too short."}}))
    assert "description" not in fields(plan_updates(EMPTY, {"draft": {"description": "x" * 500}}))
    assert rules.needs_draft(EMPTY, {}) is True
    assert rules.needs_draft(EMPTY, {"app": {"via": "endpoint", "description": "Routes payments across rails.", "capabilities": ["Pay"]}}) is False


def test_an_address_is_recorded_only_from_the_pattern_and_only_when_none_is_recorded():
    app = {"via": "pattern", "url": "https://iso-mapper-be.env.io"}
    assert fields(plan_updates({**EMPTY, "api_endpoint": None}, {"app": app}))["api_endpoint"]["new"] == "https://iso-mapper-be.env.io"
    assert "api_endpoint" not in fields(plan_updates(EMPTY, {"app": app}))
    assert "api_endpoint" not in fields(plan_updates({**EMPTY, "api_endpoint": ""}, {"app": {**app, "via": "endpoint"}}))


def test_review_findings_on_the_model_rule_and_the_draft_guard():
    def model(declared, usage):
        return fields(plan_updates({**EMPTY, "model_name": declared}, {"usage_models": usage})).get("model_name")
    assert model("claude-sonnet-4-5", [("claude-sonnet-4-5-20250929", 29)]) is None       # a release date is not another model
    assert model("GPT-4.1 mini", [("gpt-4.1-mini", 29)]) is None                           # nor is spacing or case
    assert model("gpt-4.1", [("gpt-4.1-mini", 29)])["new"] == "gpt-4.1-mini"               # but mini is not the base model
    assert model("GPT-5", [("unknown", 500), ("gpt-4.1-mini", 5)]) is None                 # five known calls out of 505 prove nothing
    from services import autofill
    assert autofill._QUANTITY.search("Handles 9 million customers a day") and autofill._QUANTITY.search("Processes thousands of invoices")
    assert not autofill._QUANTITY.search("Reads identity documents and runs sanctions checks")


def test_only_the_listed_fields_can_ever_be_planned():
    everything = {"usage_models": [("gpt-4.1-mini", 29)], "observed_only": SEEN,
                  "app": {"via": "pattern", "url": "https://a-be.x.io", "description": "Routes payments across rails.",
                          "capabilities": ["Pay"], "inputs": ["Pay: amount"], "outputs": ["Pay: fee"], "owner": "Mallory", "stage": "Production"},
                  "draft": {"description": "Reads identity documents and runs sanctions checks.", "owner": "Mallory", "value_amount": 9}}
    plan = plan_updates({**EMPTY, "api_endpoint": ""}, everything)
    assert {u["field"] for u in plan} <= set(rules.FIELD_LABELS)
    assert not {"owner", "value_amount", "lifecycle_stage", "business_outcome", "risk_level", "eu_ai_act_category"} & set(rules.FIELD_LABELS)


def test_undo_restores_a_value_only_if_nobody_changed_it_and_keeps_what_a_person_added_to_a_list():
    assert rules.undo_value("model_name", "gpt-4.1-mini", "GPT-5", "gpt-4.1-mini") == (True, "GPT-5", None)
    possible, _, why = rules.undo_value("model_name", "gpt-4o", "GPT-5", "gpt-4.1-mini")
    assert possible is False and "changed after" in why
    assert rules.undo_value("mcp_servers", ["SAP", "ocr", "kyc", "theirs"], ["SAP"], ["SAP", "ocr", "kyc"]) == (True, ["SAP", "theirs"], None)
    assert rules.undo_value("mcp_servers", ["SAP"], ["SAP"], ["SAP", "ocr"])[0] is False


# ── applying, recording, undoing ────────────────────────────────────────────

@pytest_asyncio.fixture
async def db(monkeypatch):
    from db.base import Base, engine, get_db_session
    from db.models import Agent, AgentTokenUsage, GovernanceReview, Organization
    from services import autofill
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with get_db_session() as s:
            s.add(Organization(id="org-default", name="Default", slug="default"))
            s.add(Agent(id="a1", org_id="org-default", slug="a1", name="Onboarding", owner="", lifecycle_stage="Production",
                        description="", model_name="GPT-5", phoenix_project="retail-onboarding", api_endpoint="https://app-be.x.io"))
            s.add(Agent(id="a2", org_id="org-default", slug="a2", name="No traces", owner="Ops", lifecycle_stage="Ideation",
                        description="Typed by its owner.", model_name="gpt-4o"))
            s.add(AgentTokenUsage(agent_id="a1", bucket=NOW - timedelta(days=2), model_name="gpt-4.1-mini",
                                  invocation_count=29, input_tokens=100, output_tokens=50, source="phoenix"))
            s.add(AgentTokenUsage(agent_id="a2", bucket=NOW - timedelta(days=2), model_name="gpt-4.1-mini",
                                  invocation_count=99, input_tokens=100, output_tokens=50, source="seed"))   # demo usage is not evidence
            for gate in ("arb", "security", "dp"):
                s.add(GovernanceReview(id=f"a1-{gate}", agent_id="a1", gate=gate, status="Approved",
                                       reviewed_at=NOW - timedelta(days=20), expires_at=NOW + timedelta(days=200)))

        recalculated = []

        async def observed(agent):
            return (SEEN, 380, True) if agent.id == "a1" else ([], 0, True)

        async def app(agent, record, history):
            return None, True

        async def draft(agent):
            return {"description": "Reads identity documents and runs sanctions checks for new customers.", "capabilities": ["Check sanctions"]}

        async def recalc(agent_id, trigger):
            recalculated.append(agent_id)
        monkeypatch.setattr(autofill, "_observed", observed)
        monkeypatch.setattr(autofill, "_app", app)
        monkeypatch.setattr(autofill, "_draft", draft)
        monkeypatch.setattr(autofill, "_recalculate", recalc)
        monkeypatch.setattr(get_settings(), "azure_openai_endpoint", "https://model.test")
        monkeypatch.setattr(get_settings(), "azure_openai_api_key", "k")
        get_db_session.recalculated = recalculated
        yield get_db_session
    finally:
        await engine.dispose()


async def _agent(db, agent_id="a1"):
    from db.models import Agent
    from sqlalchemy import select
    async with db() as s:
        return (await s.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()


@pytest.mark.asyncio
async def test_a_record_is_filled_in_recorded_and_not_filled_twice(db):
    from db.models import AgentFieldUpdate, AuditLog
    from services import autofill
    from sqlalchemy import select

    result = await autofill.maintain_agent("a1")
    assert {a["field"] for a in result["applied"]} == {"model_name", "mcp_servers", "knowledge_bases", "description", "capabilities"}
    assert result["evidence"] == {"realCalls": 29, "tracesRead": 380, "appRead": False, "draftUsed": True, "unread": []}
    agent = await _agent(db)
    assert agent.model_name == "gpt-4.1-mini" and agent.mcp_servers == ["ocr_extract_fields", "sanctions_check", "one_off"]
    assert agent.description.startswith("Reads identity documents") and agent.owner == "" and agent.lifecycle_stage == "Production"
    async with db() as s:
        rows = list((await s.execute(select(AgentFieldUpdate))).scalars())
        audit = list((await s.execute(select(AuditLog).where(AuditLog.action == "ai.autofill"))).scalars())
    assert len(rows) == 5 and all(r.applied_by == "ai:record-keeper" and r.reverted_at is None for r in rows)
    model = next(r for r in rows if r.field == "model_name")
    assert model.old_value == {"v": "GPT-5"} and model.new_value == {"v": "gpt-4.1-mini"} and model.source == "usage"
    assert len(audit) == 5 and all(a.actor == "ai:record-keeper" and a.changes["before"] is not None for a in audit)
    assert db.recalculated == ["a1"]                               # cost, risks and governance are redone on the new record

    again = await autofill.maintain_agent("a1")
    assert again["applied"] == [] and db.recalculated == ["a1"]


@pytest.mark.asyncio
async def test_an_agent_without_evidence_is_left_exactly_as_it_is(db):
    from services import autofill
    result = await autofill.maintain_agent("a2")
    agent = await _agent(db, "a2")
    assert result["applied"] == [] and agent.model_name == "gpt-4o" and agent.description == "Typed by its owner."
    assert (await autofill.maintain_agent("missing"))["status"] == "error"


@pytest.mark.asyncio
async def test_undo_puts_the_old_value_back_and_the_registry_then_leaves_that_field_alone(db):
    from services import autofill
    await autofill.maintain_agent("a1")
    updates = {u["field"]: u for u in await autofill.active_updates("a1")}
    assert updates["model_name"]["from"] == "GPT-5" and updates["model_name"]["to"] == "gpt-4.1-mini" and updates["model_name"]["canUndo"]
    assert updates["mcp_servers"]["added"] == ["ocr_extract_fields", "sanctions_check", "one_off"] and updates["description"]["from"] == "empty"

    assert (await autofill.undo_update("a1", updates["model_name"]["id"], "u1"))["status"] == "undone"
    assert (await _agent(db)).model_name == "GPT-5"
    assert "model_name" not in {u["field"] for u in await autofill.active_updates("a1")}
    assert (await autofill.maintain_agent("a1"))["applied"] == []               # not put back, though the evidence still says so
    with pytest.raises(ValueError):
        await autofill.undo_update("a1", updates["model_name"]["id"], "u1")     # already undone
    with pytest.raises(LookupError):
        await autofill.undo_update("a1", "nope", "u1")


@pytest.mark.asyncio
async def test_a_field_a_person_has_edited_cannot_be_undone_and_a_list_keeps_what_they_added(db):
    from services import autofill
    await autofill.maintain_agent("a1")
    updates = {u["field"]: u for u in await autofill.active_updates("a1")}
    async with db() as s:
        from db.models import Agent
        from sqlalchemy import select
        agent = (await s.execute(select(Agent).where(Agent.id == "a1"))).scalar_one()
        agent.description = "Rewritten by the owner."
        agent.mcp_servers = [*agent.mcp_servers, "their own tool"]
    with pytest.raises(ValueError, match="changed after"):
        await autofill.undo_update("a1", updates["description"]["id"], "u1")
    await autofill.undo_update("a1", updates["mcp_servers"]["id"], "u1")
    assert (await _agent(db)).mcp_servers == ["their own tool"]
    still = {u["field"]: u for u in await autofill.active_updates("a1")}
    assert "description" not in still                      # rewritten by the owner: no longer listed as filled in


@pytest.mark.asyncio
async def test_an_automatic_change_after_approval_still_asks_for_recertification(db):
    from orchestrations import governance_checks as gc
    from services import autofill
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import Agent

    async def reasons():
        async with db() as s:
            agent = (await s.execute(select(Agent).where(Agent.id == "a1").options(selectinload(Agent.governance_reviews)))).scalar_one()
            state = await gc.load_state(s, agent, datetime.now(timezone.utc))
            return {r["code"]: r["message"] for r in gc.recertification(state, datetime.now(timezone.utc))["reasons"]}, state
    before, _ = await reasons()
    assert "model_drift" in before                                  # approved as GPT-5, runs gpt-4.1-mini
    await autofill.maintain_agent("a1")
    after, state = await reasons()
    assert "model_drift" not in after                               # the record now says what runs...
    assert "material_change" in after and "model_name" in after["material_change"]   # ...and reviewers are still told it changed
    assert state["facts"]["auto_filled"]["description"] == "an AI draft from its traces"


@pytest.mark.asyncio
async def test_reviewers_are_told_when_a_passing_check_rests_on_an_automatic_entry(db):
    from governance import gate_policy as gp
    facts = {"description": "Reads identity documents and runs sanctions checks.", "model_name": "gpt-4.1-mini",
             "auto_filled": {"description": "an AI draft from its traces"}}
    items = {i["id"]: i for i in gp.evaluate_checklist("arb", facts)}
    assert items["arb.purpose"]["result"] == "pass" and "filled in automatically from an AI draft from its traces" in items["arb.purpose"]["detail"]
    assert "automatically" not in (items["arb.model"]["detail"] or "")           # the owner entered that one
    assert "automatically" not in (items["arb.owner"]["detail"] or "")
    plain = {i["id"]: i for i in gp.evaluate_checklist("arb", {**facts, "auto_filled": {}})}
    assert plain["arb.purpose"]["detail"] is None


@pytest.mark.asyncio
async def test_a_person_editing_the_field_makes_it_theirs_again_for_reviewers(db):
    from services import autofill
    await autofill.maintain_agent("a1")
    async with db() as s:
        from db.models import Agent
        from sqlalchemy import select
        agent = (await s.execute(select(Agent).where(Agent.id == "a1"))).scalar_one()
        assert set(await autofill.auto_filled_fields(s, agent)) == {"model_name", "mcp_servers", "knowledge_bases", "description", "capabilities"}
        agent.description = "Rewritten by the owner."
        assert "description" not in await autofill.auto_filled_fields(s, agent)


@pytest.mark.asyncio
async def test_a_draft_with_an_unsupported_figure_is_refused(db, monkeypatch):
    from agents.insights import runtime
    from services import autofill
    monkeypatch.undo()                                             # the real _draft, with a fake run behind it

    async def fake_run(spec, *, agent_id, request, **kw):
        assert spec.kind == "record_draft" and "get_trace_graph" in spec.tools
        return {"status": "ok", "output": {"findings": [
            {"tag": "description", "detail": "Handles 9000 customers a day through onboarding.", "title": "d", "unverifiedFigures": ["9000"]},
            {"tag": "capability", "title": "Check sanctions", "detail": "", "unverifiedFigures": []}]}}
    monkeypatch.setattr(runtime, "run_insight", fake_run)
    out = await autofill._draft(await _agent(db))
    assert out == {"description": None, "capabilities": ["Check sanctions"]}


# ── the job and the API ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_daily_job_fills_records_and_redoes_the_figures_of_the_agents_it_changed(db):
    from orchestrations import job_runner, record_autofill
    r = await record_autofill.autofill_records(trigger="scheduled")
    assert r["status"] == "ok" and r["agents"] == 1 and r["updated"] == 1 and r["fields"] == 5
    # Also when it runs late in the day, after the cost, risk and governance jobs have been and gone.
    assert r["items"][0]["agent_id"] == "a1" and db.recalculated == ["a1"]
    assert (await record_autofill.autofill_records(trigger="scheduled"))["fields"] == 0
    assert db.recalculated == ["a1"]                               # nothing changed the second time, nothing redone
    assert (await record_autofill.autofill_records(agent_id="a1", recalculate=False))["status"] == "ok"
    names = list(job_runner.JOBS)
    assert names.index("usage_ingestion") < names.index("record_autofill") < names.index("cost_rollup")   # reads usage, feeds cost and risk
    assert job_runner.availability(job_runner.JOBS["record_autofill"])[0] is True


@pytest_asyncio.fixture
async def client(db):
    from api.auth import require_read, require_update
    from api.routers.ops import autofill as api, insights

    app = FastAPI()
    app.include_router(api.router)
    app.include_router(insights.router)
    app.dependency_overrides[require_read] = lambda: dict(user)
    app.dependency_overrides[require_update] = lambda: dict(user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_run_list_and_undo_through_the_api(client, db):
    from orchestrations import job_runner
    first = (await client.get("/api/v1/agents/a1/auto-updates")).json()
    assert first["updates"] == [] and first["due"] is True and first["checkedAt"] is None
    assert "an accountable owner" in first["onlyAPerson"] and "Model" in first["fills"]
    # worked out from the record: this agent has no owner, outcome, value, budget or service level, and one department-less record
    assert [n["key"] for n in first["needsPerson"]] == ["owner", "business_outcome", "value", "budget", "sla", "department"]
    run = await job_runner.run_job("record_autofill", agent_id="a1")
    assert run["status"] == "ok" and run["summary"]["fields"] == 5
    ran = (await client.get("/api/v1/agents/a1/auto-updates")).json()
    assert len(ran["updates"]) == 5 and ran["due"] is False and ran["running"] is False
    assert ran["evidence"]["realCalls"] == 29 and ran["evidence"]["unread"] == []
    model = next(u for u in ran["updates"] if u["field"] == "model_name")
    undone = await client.post(f"/api/v1/agents/a1/auto-updates/{model['id']}/undo")
    assert undone.status_code == 200 and len(undone.json()["updates"]) == 4
    assert (await client.post(f"/api/v1/agents/a1/auto-updates/{model['id']}/undo")).status_code == 409
    assert (await client.post("/api/v1/agents/a1/auto-updates/nope/undo")).status_code == 404
    assert (await client.get("/api/v1/agents/missing/auto-updates")).status_code == 404
    # there is no route through which a caller could choose a field or a value
    assert (await client.post("/api/v1/agents/a1/auto-updates/run", json={"field": "owner", "value": "Mallory"})).status_code in (404, 405)
    assert (await client.put("/api/v1/agents/a1/auto-updates", json={"field": "owner", "value": "Mallory"})).status_code == 405
    assert (await _agent(db)).owner == ""


@pytest.mark.asyncio
async def test_each_tab_mentions_only_the_automatic_updates_it_shows(client):
    from services import autofill
    await autofill.maintain_agent("a1")
    for tab, expected in (("overview", {"model_name", "mcp_servers", "knowledge_bases", "description", "capabilities"}),
                          ("tokenomics", {"model_name"}), ("diagram", {"model_name", "mcp_servers", "knowledge_bases"}),
                          ("integrate", {"description", "capabilities"}), ("revenue", set()), ("risk", set())):
        body = (await client.get("/api/v1/agents/a1/insights", params={"tab": tab})).json()
        assert {u["field"] for u in body["autoUpdates"]["updates"]} == expected, tab
        assert body["autoUpdates"]["due"] is False and body["autoUpdates"]["checkedAt"]
    needs = {}
    for tab in ("overview", "tokenomics", "revenue", "risk", "integrate", "diagram"):
        body = (await client.get("/api/v1/agents/a1/insights", params={"tab": tab})).json()
        needs[tab] = [n["key"] for n in body["autoUpdates"]["needsPerson"]]
    assert needs == {"overview": ["owner", "business_outcome", "value", "budget", "sla", "department"], "tokenomics": ["budget"],
                     "revenue": ["business_outcome", "value", "budget"], "risk": ["owner"], "integrate": ["owner", "sla"], "diagram": []}


@pytest.mark.asyncio
async def test_the_insight_agents_can_read_what_was_filled_in(db):
    from agents.insights.tools import RefBook, get_automatic_updates
    from services import autofill
    await autofill.maintain_agent("a1")
    out = await get_automatic_updates("a1", RefBook())
    model = next(x for x in out["filledInAutomatically"] if x["field"] == "Model")
    assert (model["previouslyOnTheRecord"], model["nowOnTheRecord"], model["basedOn"]) == ("GPT-5", "gpt-4.1-mini", "its real usage")
    assert "not report any of them as a mismatch" in out["note"]
    # the change log names the registry as the author and leaves out things that change nothing about the agent
    from agents.insights.tools import get_change_log
    from services.audit import log_audit_event
    await log_audit_event(actor="u1", action="insight.run", entity_type="agent", entity_id="a1", changes={"kind": "agent_brief"})
    log = await get_change_log("a1", RefBook())
    assert {c["action"] for c in log["changes"]} == {"record filled in or corrected by the registry"}
    assert all(c["by"] == "the registry, automatically" for c in log["changes"])
    assert {f for c in log["changes"] for f in c["fieldsChanged"]} == {"model_name", "mcp_servers", "knowledge_bases", "description", "capabilities"}
    assert "not a change to the agent" in log["note"]
    assert "Model" in out["theRegistryFillsInByItself"] and "review decisions" in out["onlyAPersonCanProvide"]
    assert out["lastChecked"] and out["couldNotRead"] == []
    assert [g["what"] for g in out["stillNeededFromAPerson"]][:2] == ["An accountable owner", "The business outcome"]


@pytest.mark.asyncio
async def test_agents_behind_one_address_share_a_description_only_when_they_are_the_same_app(db):
    from db.models import Agent
    from services import autofill
    async with db() as s:
        s.add(Agent(id="b1", org_id="org-default", slug="b1", name="Same app again", owner="x", phoenix_project="retail-onboarding",
                    api_endpoint="https://app-fe.x.io/dashboard"))
    a1 = await _agent(db)
    assert await autofill._shared_with_another_app(a1, a1.api_endpoint) is False       # same project, same app
    async with db() as s:
        s.add(Agent(id="b2", org_id="org-default", slug="b2", name="Other app", owner="x", phoenix_project="billing",
                    api_endpoint="https://app-be.x.io/v2"))
    assert await autofill._shared_with_another_app(a1, a1.api_endpoint) is True        # a different app on that host


@pytest.mark.asyncio
async def test_a_reload_cannot_start_a_second_refresh_and_a_summary_is_dated_from_its_start(client, db):
    from api.routers.ops import insights
    from db.models import JobRun
    assert (await client.get("/api/v1/agents/a1/auto-updates")).json()["due"] is True
    async with db() as s:
        s.add(JobRun(id="r1", job="refresh", agent_id="a1", trigger="manual", status="error",
                     started_at=datetime.now(timezone.utc) - timedelta(minutes=2), summary={}))
    assert (await client.get("/api/v1/agents/a1/auto-updates")).json()["due"] is False   # tried two minutes ago
    async with db() as s:
        (await s.get(JobRun, "r1")).started_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    assert (await client.get("/api/v1/agents/a1/auto-updates")).json()["due"] is True
    began = datetime.now(timezone.utc) - timedelta(seconds=40)
    stored = await insights._store({"kind": "agent_brief", "status": "ok", "output": {"summary": "s", "findings": [], "notDetermined": []}},
                                   agent_id="a1", subject=None, actor="u1", started=began)
    assert abs((datetime.fromisoformat(stored["createdAt"]) - began).total_seconds()) < 1


def test_what_only_a_person_can_provide_is_worked_out_from_the_record():
    full = {"owner": "Priya N", "dept_id": "finance", "business_outcome": "Faster onboarding", "value_amount": 5000,
            "hours_saved_monthly": 0, "has_budget": True, "sla": "99.5%", "reviews": {"arb": "Approved", "security": "In Review", "dp": "Approved"}}
    assert rules.missing_from_person(full) == []
    empty = {"owner": "Unassigned", "dept_id": None, "business_outcome": " ", "value_amount": 0, "hours_saved_monthly": 0,
             "has_budget": False, "sla": None, "reviews": {"arb": "Not Submitted", "security": "Approved"}}
    out = rules.missing_from_person(empty)
    assert [g["key"] for g in out] == ["owner", "business_outcome", "value", "reviews", "budget", "sla", "department"]
    assert next(g for g in out if g["key"] == "reviews")["why"] == "Not submitted yet: Architecture, Data Protection."   # no row counts as not submitted
    assert [g["key"] for g in rules.missing_from_person({**full, "value_amount": 0, "hours_saved_monthly": 40})] == ["value"]   # hours alone give no return on cost
    assert all(set(g) == {"key", "label", "why"} for g in out)


@pytest.mark.asyncio
async def test_a_field_a_person_emptied_stays_empty(db):
    from db.models import Agent
    from services import autofill
    from sqlalchemy import select
    await autofill.maintain_agent("a1")
    async with db() as s:
        agent = (await s.execute(select(Agent).where(Agent.id == "a1"))).scalar_one()
        agent.description, agent.capabilities = "", []
    assert (await autofill.maintain_agent("a1"))["applied"] == []
    agent = await _agent(db)
    assert agent.description == "" and agent.capabilities == []


@pytest.mark.asyncio
async def test_the_registry_looks_again_only_when_there_is_reason_to(db, monkeypatch):
    from db.models import Agent, AgentRecordCheck
    from services import autofill
    from sqlalchemy import select

    async def state(agent_id="a1"):
        return await autofill.check_state(await _agent(db, agent_id))
    assert (await state())["due"] is True and (await state())["checkedAt"] is None      # never looked at
    assert (await state("a2"))["due"] is False                                          # nothing it could read
    await autofill.maintain_agent("a1")
    after = await state()
    assert after["due"] is False and after["checkedAt"] and after["evidence"]["tracesRead"] == 380

    async with db() as s:                                                               # a day and more later
        (await s.get(AgentRecordCheck, "a1")).checked_at = datetime.now(timezone.utc) - timedelta(hours=27)
    assert (await state())["due"] is True
    await autofill.maintain_agent("a1")
    assert (await state())["due"] is False

    async with db() as s:                                                               # pointed at another project
        (await s.execute(select(Agent).where(Agent.id == "a1"))).scalar_one().phoenix_project = "another-project"
    assert (await state())["due"] is True

    async def unreachable(agent):
        return [], 0, False
    monkeypatch.setattr(autofill, "_observed", unreachable)
    result = await autofill.maintain_agent("a1")
    assert result["evidence"]["unread"] == ["its traces"]
    assert (await state())["due"] is False                                              # just tried: not again straight away
    async with db() as s:
        (await s.get(AgentRecordCheck, "a1")).checked_at = datetime.now(timezone.utc) - timedelta(hours=2)
    assert (await state())["due"] is True                                               # ...but sooner than a full day


@pytest.mark.asyncio
async def test_an_agent_with_only_a_web_address_is_covered_too(db, monkeypatch):
    from db.models import Agent
    from orchestrations import record_autofill
    from services import autofill
    async with db() as s:
        s.add(Agent(id="a3", org_id="org-default", slug="a3", name="Address only", owner="Ops", lifecycle_stage="Ideation",
                    description="Typed by its owner.", api_endpoint="https://zen-fe.x.io/"))
        s.add(Agent(id="a4", org_id="org-default", slug="a4", name="Retired", owner="Ops", lifecycle_stage="Deprecated",
                    description="", api_endpoint="https://old.x.io/", deprecated_at=NOW))

    async def app(agent, record, history):
        return ({"via": "endpoint", "url": "https://zen-be.x.io", "capabilities": ["Health Check", "Assess Controls"],
                 "inputs": ["Assess Controls: framework, scope"], "outputs": []}, True) if agent.id == "a3" else (None, True)
    monkeypatch.setattr(autofill, "_app", app)
    r = await record_autofill.autofill_records(trigger="scheduled")
    assert r["agents"] == 2 and {i["agent_id"] for i in r["items"]} == {"a1", "a3"}      # the retired one is left alone
    a3 = await _agent(db, "a3")
    assert a3.capabilities == ["Assess Controls"] and a3.inputs == ["Assess Controls: framework, scope"]
    assert a3.description == "Typed by its owner."


@pytest.mark.asyncio
async def test_the_one_agent_refresh_fills_the_record_before_it_recalculates(db, monkeypatch):
    from orchestrations import job_runner
    order = []

    async def fake_execute(spec, agent_id, trigger, kwargs):
        order.append((spec.name, dict(kwargs)))
        return "ok", {}, None
    monkeypatch.setattr(job_runner, "_execute", fake_execute)
    result = await job_runner.refresh_agent("a1")
    assert result["status"] == "ok"
    assert [name for name, _ in order] == ["usage_ingestion", "record_autofill", "cost_rollup", "risk_scan", "governance_checks"]
    assert dict(order)["record_autofill"] == {"recalculate": False}                    # the next three steps do that


@pytest.mark.asyncio
async def test_a_summary_written_before_the_record_changed_is_marked_for_rewriting(client, db):
    from agents.insights.specs import SPECS
    from db.models import Insight
    from services import autofill
    async with db() as s:
        s.add(Insight(id="i1", org_id="org-default", agent_id="a1", kind="agent_brief", status="ok", created_by="u1",
                      output={"summary": "The record names GPT-5.", "findings": [], "notDetermined": []},
                      prompt_version=SPECS["agent_brief"].version, created_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    before = (await client.get("/api/v1/agents/a1/insights", params={"tab": "overview"})).json()["insights"][0]
    assert before["stale"] is False and before["recordChangedSince"] is False
    await autofill.maintain_agent("a1")
    after = (await client.get("/api/v1/agents/a1/insights", params={"tab": "overview"})).json()["insights"][0]
    assert after["stale"] is True and after["recordChangedSince"] is True


def test_operations_every_service_has_are_not_capabilities_or_contract_lines():
    from governance import reuse
    assert all(reuse.is_plumbing(x) for x in ("Health Check", "health", "Root", "Ping", "Health Check: status, timestamp"))
    assert not any(reuse.is_plumbing(x) for x in ("Start Onboarding", "Get Config", "Check Sanctions", "Status Report"))
    doc = {"openapi": "3.0.0", "paths": {
        "/health": {"get": {"summary": "Health Check", "responses": {"200": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"status": {"type": "string"}}}}}}}}},
        "/pay": {"post": {"summary": "Orchestrate Payment", "responses": {"200": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"rail": {"type": "string"}}}}}}}}}}}
    assert reuse.openapi_io(doc)["outputs"] == ["Orchestrate Payment: rail"]


def test_version_comes_from_agent_version_on_the_spans_unless_a_person_owns_it():
    from governance import autofill as r

    ev = {"hints": {"agent.version": "2.4.1"}}
    [u] = [x for x in r.plan_updates({"version": None}, ev) if x["field"] == "version"]
    assert u["new"] == "2.4.1" and u["source"] == "traces"
    history = [r.Past(field="version", old=None, new="2.4.0", reverted=True)]
    assert not [x for x in r.plan_updates({"version": None}, ev, history) if x["field"] == "version"]


def test_owner_and_department_are_suggested_from_the_spans_never_set():
    from governance import autofill as r

    gaps = r.missing_from_person({"owner": "", "dept_id": None, "hints": {"agent.owner": "Card Ops"},
                                  "hint_dept": {"id": "dept-fin", "name": "Finance"}})
    by = {g["key"]: g for g in gaps}
    assert by["owner"]["suggested"] == {"value": "Card Ops", "label": "Card Ops", "source": "agent.owner on its spans"}
    assert by["department"]["suggested"]["value"] == "dept-fin"
