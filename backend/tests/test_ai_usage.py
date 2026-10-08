"""The registry's own AI: switches, the monthly cap with its 1.2x ceiling for
people's requests, the record of every run, and the AI-off check."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def client():
    from db.base import Base, engine, get_db_session
    from db.models import ModelTokenPrice, Organization, User
    from shared.config import get_settings

    assert "data/airegistry.db" not in get_settings().database_url, "tests must use a throwaway DB"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_db_session() as s:
        s.add(Organization(id="org-default", name="Default", slug="default"))
        s.add(User(id="adm", org_id="org-default", email="a@x.io", name="Ada", role="Registry Admin", password_hash="x"))
        s.add(ModelTokenPrice(id="p1", model_name=get_settings().azure_openai_deployment, provider="azure",
                              input_price_per_1m=1.0, output_price_per_1m=4.0, tier="mid"))
    from api.auth import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "adm", "role": "Registry Admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_runs_are_recorded_with_cost_and_the_cap_stops_scheduled_work_first(client):
    from services import ai_meter

    await ai_meter.record("insights", kind="agent_brief", model=ai_meter.deployment(), input_tokens=1_000_000,
                          output_tokens=250_000, duration_ms=900)            # $1 + $1 = 200 cents
    usage = (await client.get("/api/v1/ai-usage")).json()
    row = next(f for f in usage["functions"] if f["function"] == "insights")
    assert row["runs30d"] == 1 and row["costCents30d"] == 200.0 and usage["spentThisMonthCents"] == 200.0
    assert (await client.put("/api/v1/ai-usage/cap", json={"monthlyCapCents": 180})).status_code == 200
    assert "for scheduled work" in await ai_meter.refusal("insights", interactive=False)
    assert await ai_meter.refusal("insights", interactive=True) is None          # 200 < 180 x 1.2 = 216
    await client.put("/api/v1/ai-usage/cap", json={"monthlyCapCents": 150})
    assert "used up" in await ai_meter.refusal("ask", interactive=True)


@pytest.mark.asyncio
async def test_a_switched_off_function_refuses_and_says_why(client):
    from agents.insights.runtime import run_insight
    from agents.insights.specs import SPECS

    assert (await client.put("/api/v1/ai-usage/switches/ask", json={"enabled": False})).status_code == 200
    r = await run_insight(SPECS["ask"], agent_id=None, request="q")
    assert r["status"] == "unavailable" and "switched off" in r["reason"]
    usage = (await client.get("/api/v1/ai-usage")).json()
    ask = next(f for f in usage["functions"] if f["function"] == "ask")
    assert ask["enabled"] is False and ask["refused30d"] == 1
    assert (await client.put("/api/v1/ai-usage/switches/nope", json={"enabled": False})).status_code == 404


@pytest.mark.asyncio
async def test_ai_off_check_passes_without_calling_a_model(client):
    r = (await client.post("/api/v1/ai-usage/off-check")).json()
    assert r["passed"] is True and len(r["checks"]) == 8
