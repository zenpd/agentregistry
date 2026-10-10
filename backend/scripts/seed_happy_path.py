"""Adds one demo agent, "Digital Onboarding Prod", that shows the registry with every check green.

Its record is a copy of the real agent "retail bank onboarding" (description, capabilities, inputs, outputs, tools,
model, endpoint and Phoenix project), so the cards, the diagram and the traces look like a real agent's. On top
of that copy everything a person provides is filled in: the agent is in Production with an owner and a backup owner, a confirmed classification, the
three reviews approved with every checklist item ticked, a finance-attested value, declared hosting cost,
six months of token usage, a released version, one approved consuming team and a risk scan with no findings.
It costs $3,000 in the current month (token cost plus hosting) and earns $8,000 of value, a profit of $5,000.

Run it against a running backend. It uses the registry's own API, so every step is audited like a person's
action. It deletes nothing. When the agent already exists, the script only tops it up: it adds the days of usage
that are missing up to today and re-declares the hosting cost, so the current month stays at $3,000.00. Run it
again after a few days, or at the start of a month, to keep the figures as described.

    DATABASE_URL=sqlite+aiosqlite:///./data/airegistry.db PYTHONPATH=. ./.venv/bin/python scripts/seed_happy_path.py

Add --recreate to delete the demo agent first (only an agent with this name that is marked as a demo agent) and
build it again from the current record of the source agent.

Environment: AR_API (default http://127.0.0.1:8002/api/v1), AR_ADMIN_EMAIL and AR_ADMIN_PASSWORD (the
development administrator by default).
"""
from __future__ import annotations

import asyncio
import calendar
import os
import secrets
import sys
from datetime import date, datetime, timedelta, timezone

import httpx

API = os.environ.get("AR_API", "http://127.0.0.1:8002/api/v1")
NAME = "Digital Onboarding Prod"
VALUE_DOLLARS = 8000            # a month
EXPENDITURE_CENTS = 300_000     # a month, tokens plus hosting, in the current month
SOURCE_NAME = "retail bank onboarding"      # the real agent whose record is copied
# One model, one day of use that costs exactly $20.00 at the list price of gpt-4.1-mini: 20,000,000 uncached input
# tokens at $0.40 per million, 40,000,000 cached input tokens at $0.10 per million and 5,000,000 output tokens at
# $1.60 per million. 12,000 calls a day, about 5,000 tokens in and 400 out for each call.
MODEL = "gpt-4.1-mini"
DAY_UNCACHED, DAY_CACHED, DAY_OUTPUT, DAY_CALLS = 20_000_000, 40_000_000, 5_000_000, 12_000
# The context document: seven of the eight sections the registry looks for (no Links section), so it reads 88% complete.
CONTEXT_MD = """# Agent context

## Purpose
Onboards retail, corporate, merchant and vendor customers. It reads the documents an applicant uploads, screens the applicant against sanction lists and prepares the application for a decision. It does not open accounts and it does not set credit limits.

## Users & decisions supported
Onboarding staff use its output in the branch account-opening screen. It recommends approve, refer or reject for each application. A reviewer makes the decision on every application it refers or rejects. No decision is fully automated.

## Data handled
It reads the applicant details and the uploaded documents, and it produces a risk band with the reasons. Applications are kept in the Onboarding applications database for 30 days, then removed.

## Systems & tools
Core banking, the Onboarding applications database and the Onboarding policy knowledge base. Tools: ocr_extract_fields, sanctions_check and rag_search. Model: gpt-4.1-mini.

## Human oversight
A reviewer decides every referred or rejected application and can overrule any recommendation. The platform team switches the agent off by disabling its route in the API gateway.

## Failure modes & fallback
When a document cannot be read, the application is sent to a reviewer. When the sanction list service does not answer, the application waits and is retried, and nothing is approved meanwhile. When the agent is unavailable, staff complete the onboarding by hand in the branch system.

## Owners & support
Business owner: the head of customer onboarding. Technical owner: the onboarding platform team. Support channel: onboarding-team@example.com. Escalation: the on-call platform engineer.
"""

# Used when the source agent is not in this registry.
FALLBACK = {
    "description": "AI-powered digital onboarding platform for Retail, Corporate, Merchant, and Vendor journeys. Powered by LangGraph + 19 specialist agents.",
    "capabilities": ["Start Onboarding", "Resume Onboarding", "Sync Temporal Workflows", "List Sessions", "Get Session Detail", "Upload Document", "Submit Review Decision", "List Pending Reviews"],
    "inputs": ["Start Onboarding: journey_type, initial_message", "Resume Onboarding: session_id, message", "Submit Review Decision: session_id, decision, notes"],
    "outputs": ["Edit Application: session_id, updated_fields, updated_at", "Analyze Kyc Risk: risk_score, risk_band, risk_factors"],
    "mcpServers": ["ocr_extract_fields", "sanctions_check", "rag_search"], "modelName": MODEL, "aiType": "Autonomous Agent", "dept": "dept-finance",
    "apiEndpoint": "/agents/v1/digital-onboarding-prod", "phoenixProject": "retail-onboarding",
}
DAY_COST_CENTS = 2000
HISTORY_DAYS = 185


def step(text: str) -> None:
    print(f"  {text}")


def need(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 300:
        sys.exit(f"{what} failed ({r.status_code}): {r.text[:400]}")
    return r.json() if r.content else {}


async def add_usage(agent_id: str, today: date) -> int:
    """Adds a day of usage for every day of the last HISTORY_DAYS days that has none. Returns how many were added."""
    from sqlalchemy import select
    from db.base import get_db_session
    from db.models import AgentTokenUsage

    added = 0
    async with get_db_session() as db:
        have = {b.date() for b in (await db.execute(select(AgentTokenUsage.bucket).where(AgentTokenUsage.agent_id == agent_id))).scalars().all()}
        for i in range(HISTORY_DAYS):
            day = today - timedelta(days=i)
            if day in have:
                continue
            db.add(AgentTokenUsage(agent_id=agent_id, bucket=datetime(day.year, day.month, day.day, tzinfo=timezone.utc), model_name=MODEL,
                                   invocation_count=DAY_CALLS, input_tokens=DAY_UNCACHED + DAY_CACHED, cached_tokens=DAY_CACHED,
                                   output_tokens=DAY_OUTPUT, cost_cents=DAY_COST_CENTS, latency_avg_ms=820, error_count=0,
                                   source="phoenix", run_count=DAY_CALLS, raw_model_names=[MODEL], ingested_at=datetime.now(timezone.utc)))
            added += 1
    return added


async def mark_demo(agent_id: str) -> None:
    from db.base import get_db_session
    from db.models import Agent

    # A demo agent that is always shown: db/scope.py keeps a "showcase" agent visible when the other demo agents are hidden.
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        agent.is_demo, agent.source = True, "showcase"


async def top_up(c: httpx.AsyncClient, agent_id: str, today: date, hosting_cents: int) -> None:
    added = await add_usage(agent_id, today)
    step(f"{added} missing days of usage added")
    profile = need(await c.get(f"/agents/{agent_id}/infra-profile"), "Reading the hosting cost")
    if profile.get("monthlyCostCents") != hosting_cents:
        need(await c.put(f"/agents/{agent_id}/infra-profile", json={
            "platform": "Azure Container Apps", "monthlyCostCents": hosting_cents, "effectiveFrom": profile.get("effectiveFrom"),
            "components": [{"name": "Container Apps and gateway", "costCents": hosting_cents - 60_000, "recurring": True},
                           {"name": "Database and storage", "costCents": 60_000, "recurring": True}]}), "Re-declaring the hosting cost")
        step(f"hosting cost re-declared as ${hosting_cents / 100:,.2f} a month")
    await mark_demo(agent_id)
    print("Done.")


async def main() -> None:
    today = datetime.now(timezone.utc).date()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    month_token_cents = DAY_COST_CENTS * days_in_month           # the current month, projected from a constant day
    hosting_cents = EXPENDITURE_CENTS - month_token_cents         # declared monthly hosting that makes the month $3,000.00
    async with httpx.AsyncClient(base_url=API, timeout=60) as c:
        r = await c.post("/auth/login", json={"email": os.environ.get("AR_ADMIN_EMAIL", "admin@airegistry.local"),
                                               "password": os.environ.get("AR_ADMIN_PASSWORD", "admin123")})
        c.headers["Authorization"] = f"Bearer {need(r, 'Sign-in')['access_token']}"
        c.headers["X-Include-Demo"] = "1"
        agents = need(await c.get("/agents/", params={"limit": 100}), "Listing agents")["data"]
        existing = next((a for a in agents if a["name"] == NAME), None)
        if existing and "--recreate" in sys.argv:
            if not existing.get("isDemo"):
                sys.exit(f"{NAME} exists and is not a demo agent, so it is left alone.")
            need(await c.delete(f"/agents/{existing['id']}"), "Deleting the earlier demo agent")
            print(f"Deleted the earlier {NAME}.")
            existing = None
        if existing:
            print(f"{NAME} already exists: topping up its usage and hosting cost.")
            await top_up(c, existing["id"], today, hosting_cents)
            return
        me = need(await c.get("/auth/me"), "Reading the signed-in user")
        source = next((a for a in agents if a["name"] == SOURCE_NAME), None)
        src = {k: (source or {}).get(k) or v for k, v in FALLBACK.items()}
        print(f"Adding {NAME}" + (f", copied from {SOURCE_NAME}" if source else f" ({SOURCE_NAME} was not found, so built-in values are used)"))

        # A second person to be the backup owner.
        users = need(await c.get("/admin/users"), "Listing users")
        backup = next((u for u in users if u["email"] == "demo.backup@airegistry.local"), None)
        if backup is None:
            backup = need(await c.post("/admin/users", json={"email": "demo.backup@airegistry.local", "name": "Demo Backup Owner",
                                                             "role": "Architect Steward", "password": secrets.token_urlsafe(18)}), "Adding the backup owner")
            step("added the user Demo Backup Owner (no one knows the password: it was random)")

        created = need(await c.post("/agents/", json={
            "name": NAME, "dept": src["dept"], "owner": me["name"], "ai_type": src["aiType"], "stage": "Production",
            "stage_reason": "Demo agent: a complete example with every check passed, so the registry can be shown end to end.",
            "reuse_justification": "Demo agent: the production copy of the onboarding agent, with every check passed. The other onboarding records are still in Ideation.",
            "description": src["description"],
            "business_outcome": "New customers are onboarded in minutes instead of days, with fewer manual document and sanction checks.",
            "value_amount": VALUE_DOLLARS, "value_type": "Cost avoidance", "hours_saved_monthly": 120,
            "enterprise_systems": ["Core banking"], "databases": ["Onboarding applications"], "knowledge_bases": ["Onboarding policy"], "mcp_servers": src["mcpServers"],
            "inputs": src["inputs"], "outputs": src["outputs"], "capabilities": src["capabilities"],
            "api_endpoint": src["apiEndpoint"], "sla": "99.9% uptime", "rate_limit": "100 requests a minute",
            "owner_contact": "onboarding-team@example.com", "tags": ["onboarding", "customer"], "model_name": src["modelName"] or MODEL,
            "phoenix_project": src["phoenixProject"], "risk_level": "LOW", "version": "v1.0",
            "context_md": CONTEXT_MD,
        }), "Registering the agent")
        agent_id = created["id"]
        step(f"registered in Production with the id {agent_id}")
        a = f"/agents/{agent_id}"

        need(await c.put(f"{a}/ownership", json={"ownerUserId": me["user_id"], "backupOwnerUserId": backup["id"],
                                                  "reason": "Demo agent: the owner and a backup owner are both people with accounts."}), "Setting the owners")
        step("owner and backup owner are people with accounts")

        answers = {"prohibited": [], "area": "none", "interacts": True, "audience": "public", "data": "personal",
                   "retention": "30_days", "decisions": "decides_reviewed"}
        rec = need(await c.post(f"{a}/classification", json={"answers": answers, "confirm": True, "note": "Confirmed for the demo agent."}), "Classifying")
        step(f"classified: {rec.get('category')}, {rec.get('riskLevel')} risk, confirmed")

        need(await c.post(f"{a}/risks/scan"), "Running the risk scan")
        step("risk scan ran with no findings")

        gov = need(await c.get(f"{a}/governance"), "Reading the reviews")
        ticks = {}
        for g in gov["gates"]:
            for item in g.get("checklist", []):
                if item.get("auto") == "manual":
                    ticks[(g["gate"], item["id"])] = "pass"
        for gate in ("arb", "security", "dp"):
            checks = {i: t for (g, i), t in ticks.items() if g == gate}
            need(await c.put(f"{a}/governance/{gate}", json={"status": "In Review", "checklist": checks}), f"Submitting the {gate} review")
            need(await c.put(f"{a}/governance/{gate}", json={"status": "Approved", "checklist": checks,
                                                              "notes": "Demo agent: every checklist item passes."}), f"Approving the {gate} review")
        step("the three reviews are approved")

        # Findings such as "review not approved" were raised by the first scan. Scanning again, now the reviews are approved, closes them.
        need(await c.post(f"{a}/risks/scan"), "Running the risk scan again")
        step("risk scan ran again: no open findings")

        need(await c.put(f"{a}/value", json={"method": "cost_avoidance", "basis": "Onboarding cases handled without a person: 120 hours a month at the blended rate, plus fewer manual identity checks.",
                                             "amountDollars": VALUE_DOLLARS, "hoursSavedMonthly": 120}), "Declaring the value")
        need(await c.post(f"{a}/value/attest", json={"status": "attested", "note": "Demo agent: finance confirmed the declared value."}), "Attesting the value")
        step(f"value of ${VALUE_DOLLARS:,} a month declared and confirmed by finance")

        need(await c.put(f"{a}/infra-profile", json={
            "platform": "Azure Container Apps", "monthlyCostCents": hosting_cents, "effectiveFrom": (today - timedelta(days=HISTORY_DAYS)).replace(day=1).isoformat(),
            "components": [{"name": "Container Apps and gateway", "costCents": hosting_cents - 60_000, "recurring": True},
                           {"name": "Database and storage", "costCents": 60_000, "recurring": True}]}), "Declaring hosting cost")
        step(f"hosting cost of ${hosting_cents / 100:,.2f} a month declared")

        need(await c.put(f"{a}/budget", json={"monthlyBudgetCents": 400_000, "alertThresholdPct": 80, "budgetResetDay": 1}), "Setting the budget")
        step("monthly budget of $4,000 set")

        need(await c.post(f"{a}/versions", json={"version": "v1.0", "changelog": "First production release."}), "Releasing a version")
        step("version v1.0 released")

        req = need(await c.post(f"{a}/access-requests", json={"team": "Retail Banking Operations", "purpose": "Use the onboarding decision in the branch account-opening screen."}), "Requesting access")
        need(await c.post(f"{a}/access-requests/{req['id']}/decision", json={"decision": "approve", "note": "Approved for the demo."}), "Approving access")
        step("one consuming team approved")

    # Token usage: the same busy day for six months, read as if it came from the agent's traces.
    added = await add_usage(agent_id, today)
    step(f"{added} days of token usage added, $20.00 a day, no errors")
    await mark_demo(agent_id)
    print(f"Done. Open /agents/{agent_id} with the demo agents shown (Settings → Demo agents).")


if __name__ == "__main__":
    asyncio.run(main())
