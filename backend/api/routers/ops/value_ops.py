"""Value and spend:

- the owner declares value with a method and a basis, and a finance reviewer attests
  or adjusts it (items 45 and 46);
- measured outcomes from a CSV file, a webhook or typed in, and cost per outcome (47);
- the same tokens priced at other models, and the effect of a price change (50);
- usage typed in or imported for agents without tracing (51);
- idle and duplicate spend (53), the Production scenario (54) and the scorecard PDF (48).

Builds avoided times an agreed build cost (49) is part of the scorecard and the
Programme health figures."""
from __future__ import annotations

import csv
import io
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from api.auth import has_permission, require_admin, require_attest, require_read, require_update
from db.base import get_db_session
from db.models import Agent, AgentOutcome, AgentTokenUsage, AuditLog, Department, User, ValueAttestation
from governance import value as gv
from governance.economics import estimated_infra_cents, load_economics
from orchestrations.risk_scan import as_utc
from services.ai_meter import get_setting, set_setting
from shared.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Value"])

MIN_NOTE = 20


async def _agent(db, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _log(db, actor: str, action: str, agent_id: str, changes: dict) -> None:
    db.add(AuditLog(org_id="org-default", actor=actor, action=action, entity_type="agent", entity_id=agent_id, changes=changes))


# ── Value: method, basis and attestation ─────────────────────────────────────

def _att(v: ValueAttestation, names: dict) -> dict:
    return {"id": v.id, "status": v.status, "declaredCents": v.declared_cents, "declaredMethod": v.declared_method,
            "attestedCents": v.attested_cents, "note": v.note, "attestedBy": names.get(v.attested_by, v.attested_by),
            "attestedAt": as_utc(v.attested_at).isoformat()}


async def value_view(db, agent: Agent, user: dict | None = None) -> dict:
    rows = (await db.execute(select(ValueAttestation).where(ValueAttestation.agent_id == agent.id)
                             .order_by(ValueAttestation.attested_at.desc()))).scalars().all()
    names = dict((await db.execute(select(User.id, User.name))).all())
    history = [_att(v, names) for v in rows]
    method = gv.method_of(agent.value_method, agent.value_type, agent.hours_saved_monthly)
    declared = max(int(agent.value_amount or 0), 0) * 100
    rate = agent.value_hourly_rate_cents or round(get_settings().blended_hourly_rate_usd * 100)
    return {
        "declaredCents": declared, "method": method, "methodLabel": gv.METHODS.get(method) if method else None,
        "methodSet": agent.value_method in gv.METHODS, "basis": agent.value_basis, "valueType": agent.value_type,
        "hoursSavedMonthly": agent.hours_saved_monthly or 0, "hourlyRateCents": rate,
        "timeSavedCents": gv.time_saved_cents(agent.hours_saved_monthly, rate),
        "state": gv.value_state(declared, agent.value_method, history[0] if history else None),
        "attestations": history,
        "methods": [{"value": k, "label": v, "help": gv.METHOD_HELP[k]} for k, v in gv.METHODS.items()],
        "canAttest": bool(user) and has_permission(user.get("role", ""), "attest"),
    }


@router.get("/agents/{agent_id}/value")
async def get_value(agent_id: str, user=Depends(require_read)):
    async with get_db_session() as db:
        return await value_view(db, await _agent(db, agent_id), user)


class ValueBody(BaseModel):
    method: str
    basis: str
    amountDollars: Optional[int] = Field(None, ge=0, le=100_000_000)
    hoursSavedMonthly: Optional[int] = Field(None, ge=0, le=1_000_000)
    hourlyRateCents: Optional[int] = Field(None, ge=0, le=10_000_000)


@router.put("/agents/{agent_id}/value")
async def declare_value(agent_id: str, body: ValueBody, user=Depends(require_update)):
    """The owner's declared monthly value. For time saved, the value is the hours times the rate."""
    if body.method not in gv.METHODS:
        raise HTTPException(status_code=422, detail=f"The method must be one of: {', '.join(gv.METHODS.values())}.")
    if len(body.basis.strip()) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say how the figure is worked out, in at least {MIN_NOTE} characters.")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        before = {"amountDollars": agent.value_amount, "method": agent.value_method, "basis": agent.value_basis}
        if body.method == "time_saved":
            hours = body.hoursSavedMonthly if body.hoursSavedMonthly is not None else agent.hours_saved_monthly
            rate = body.hourlyRateCents or agent.value_hourly_rate_cents or round(get_settings().blended_hourly_rate_usd * 100)
            if not hours:
                raise HTTPException(status_code=422, detail="For time saved, enter the hours saved each month.")
            agent.hours_saved_monthly, agent.value_hourly_rate_cents = hours, rate
            agent.value_amount = gv.time_saved_cents(hours, rate) // 100
        else:
            if body.amountDollars is None:
                raise HTTPException(status_code=422, detail="Enter the monthly value in dollars.")
            agent.value_amount = body.amountDollars
        agent.value_method, agent.value_basis = body.method, body.basis.strip()
        _log(db, user.get("user_id", "unknown"), "value.declare", agent_id,
             {"before": before, "after": {"amountDollars": agent.value_amount, "method": agent.value_method, "basis": agent.value_basis}})
        await db.flush()
        return await value_view(db, agent, user)


class AttestBody(BaseModel):
    status: str
    note: str
    amountDollars: Optional[int] = Field(None, ge=0, le=100_000_000)


@router.post("/agents/{agent_id}/value/attest")
async def attest_value(agent_id: str, body: AttestBody, user=Depends(require_attest)):
    """A finance reviewer confirms the declared value, or adjusts it to another figure."""
    if body.status not in ("attested", "adjusted"):
        raise HTTPException(status_code=422, detail="status is attested (confirm as declared) or adjusted (another amount).")
    if len(body.note.strip()) < MIN_NOTE:
        raise HTTPException(status_code=422, detail=f"Say what you checked, in at least {MIN_NOTE} characters.")
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        declared = max(int(agent.value_amount or 0), 0) * 100
        if body.status == "attested" and declared <= 0:
            raise HTTPException(status_code=409, detail="Nothing is declared yet, so there is nothing to confirm. Adjust it to an amount instead.")
        if body.status == "adjusted" and body.amountDollars is None:
            raise HTTPException(status_code=422, detail="Enter the adjusted monthly value in dollars.")
        cents = declared if body.status == "attested" else body.amountDollars * 100
        db.add(ValueAttestation(id=f"va-{secrets.token_hex(6)}", agent_id=agent_id, status=body.status, declared_cents=declared,
                                declared_method=agent.value_method, attested_cents=cents, note=body.note.strip(),
                                attested_by=user.get("user_id"), attested_at=datetime.now(timezone.utc)))
        _log(db, user.get("user_id", "unknown"), "value.attest", agent_id,
             {"status": body.status, "declaredCents": declared, "attestedCents": cents, "note": body.note.strip()})
        await db.flush()
        return await value_view(db, agent, user)


# ── Measured outcomes and cost per outcome ───────────────────────────────────

class OutcomeBody(BaseModel):
    outcome: str = Field(..., min_length=1, max_length=120)
    count: int = Field(..., ge=0, le=100_000_000)
    day: Optional[date] = None


async def _store_outcomes(agent_id: str, rows: list[dict], source: str, actor: str) -> int:
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        await _agent(db, agent_id)
        for r in rows:
            existing = (await db.execute(select(AgentOutcome).where(AgentOutcome.agent_id == agent_id, AgentOutcome.day == r["day"],
                                                                    AgentOutcome.outcome == r["outcome"]))).scalar_one_or_none()
            if existing is None:
                db.add(AgentOutcome(id=secrets.token_hex(8), agent_id=agent_id, day=r["day"], outcome=r["outcome"], count=r["count"],
                                    source=source, recorded_by=actor, recorded_at=now))
            else:
                existing.count, existing.source, existing.recorded_by, existing.recorded_at = r["count"], source, actor, now
        _log(db, actor, "outcome.record", agent_id, {"rows": len(rows), "source": source,
                                                     "outcomes": sorted({r["outcome"] for r in rows})[:5]})
    return len(rows)


@router.post("/agents/{agent_id}/outcomes")
async def record_outcome(agent_id: str, body: OutcomeBody, user=Depends(require_update)):
    """Webhook: one outcome count for a day (today when no day is given). Sending the same
    agent, day and outcome again replaces the count. A CI job or the agent's own app can
    call this with a registry API key that may register."""
    day = body.day or datetime.now(timezone.utc).date()
    source = "webhook" if user.get("via") == "api_key" or str(user.get("user_id", "")).startswith("key:") else "manual"
    n = await _store_outcomes(agent_id, [{"day": day, "outcome": " ".join(body.outcome.split()), "count": body.count}], source,
                              user.get("user_id", "unknown"))
    return {"stored": n, "day": day.isoformat()}


def parse_outcomes_csv(text: str) -> list[dict]:
    """day,outcome,count with a header row. Days as 2026-10-08."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    need = {"day", "outcome", "count"}
    if not reader.fieldnames or not need <= {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("The first row must be the header day,outcome,count.")
    out = []
    for i, row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            out.append({"day": date.fromisoformat(row["day"]), "outcome": " ".join(row["outcome"].split())[:120],
                        "count": int(row["count"])})
        except (ValueError, KeyError):
            raise ValueError(f"Row {i} is not a day (2026-10-08), an outcome name and a whole number.")
        if not out[-1]["outcome"] or out[-1]["count"] < 0:
            raise ValueError(f"Row {i} needs an outcome name and a count of 0 or more.")
    if not out:
        raise ValueError("The file has no rows under the header.")
    return out


@router.post("/agents/{agent_id}/outcomes/import")
async def import_outcomes(agent_id: str, csv_text: str = Body(..., media_type="text/csv"), user=Depends(require_update)):
    try:
        rows = parse_outcomes_csv(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"stored": await _store_outcomes(agent_id, rows, "csv", user.get("user_id", "unknown"))}


@router.get("/agents/{agent_id}/outcomes")
async def outcomes(agent_id: str, days: int = Query(30, ge=7, le=365), _=Depends(require_read)):
    """Measured outcomes and the cost per outcome over the last `days` days: token cost of
    those days plus hosting for the same share of the month."""
    from services.usage_repo import priced_usage

    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        rows = (await db.execute(select(AgentOutcome).where(AgentOutcome.agent_id == agent_id, AgentOutcome.day >= since)
                                 .order_by(AgentOutcome.day))).scalars().all()
        usage = await priced_usage(db, agent_id, since)
        econ = (await load_economics(db, [agent]))[agent_id]
    token = sum(r["cost_cents"] for r in usage["rows"] if r["day"] >= since) if usage["source"] not in ("none",) else None
    infra = econ["infraCostCents"] * days / 30
    by_outcome: dict[str, int] = {}
    for r in rows:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + r.count
    total_cost = None if token is None else round(token + infra, 2)
    return {
        "days": days, "from": since.isoformat(), "to": today.isoformat(),
        "rows": [{"day": r.day.isoformat(), "outcome": r.outcome, "count": r.count, "source": r.source} for r in rows],
        "outcomes": [{"outcome": k, "count": v, "costPerOutcomeCents": gv.cost_per_outcome(total_cost, v)} for k, v in sorted(by_outcome.items())],
        "costCents": total_cost, "tokenCostCents": None if token is None else round(token, 2), "infraCostCents": round(infra, 2),
        "infraSource": econ["infraSource"], "tokenSource": usage["source"],
    }


# ── The same tokens at other models ──────────────────────────────────────────

@router.get("/agents/{agent_id}/model-whatif")
async def model_whatif(agent_id: str, days: int = Query(30, ge=7, le=90), priceChangePct: float = Query(0, ge=-90, le=300),
                       _=Depends(require_read)):
    from services.usage_repo import load_prices, priced_usage

    since = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    async with get_db_session() as db:
        await _agent(db, agent_id)
        usage = await priced_usage(db, agent_id, since)
        prices = await load_prices(db)
    rows = [r for r in usage["rows"] if r["day"] >= since]
    tokens = {"input": sum(r.get("input_tokens", 0) for r in rows), "output": sum(r.get("output_tokens", 0) for r in rows),
              "cached": sum(r.get("cached_tokens", 0) for r in rows)}
    current = round(sum(r["cost_cents"] for r in rows), 2)
    used = sorted({r["model"] for r in rows})
    return {
        "days": days, "source": usage["source"], "tokens": tokens, "currentCents": current, "modelsUsed": used,
        "unpricedModels": usage["unpriced"], "priceChangePct": priceChangePct,
        "currentAfterChangeCents": round(current * (1 + priceChangePct / 100), 2),
        "models": gv.whatif(tokens, current, [{"model": p.model, "input": p.input_per_1m, "output": p.output_per_1m, "cached": p.cached_per_1m}
                                               for p in prices.values()], priceChangePct),
        "caveat": "Only the price was compared. Answer quality was not compared, so a cheaper model may answer worse.",
    }


# ── Usage without tracing ────────────────────────────────────────────────────

class ManualUsage(BaseModel):
    day: date
    model: str = Field(..., min_length=1, max_length=100)
    calls: int = Field(..., ge=0, le=100_000_000)
    inputTokens: int = Field(0, ge=0)
    outputTokens: int = Field(0, ge=0)


async def _store_usage(agent_id: str, rows: list[dict], actor: str) -> int:
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        if agent.phoenix_project or agent.trace_connector_id:
            raise HTTPException(status_code=409, detail="This agent's usage comes from its tracing link, so it is not typed in.")
        for r in rows:
            bucket = datetime.combine(r["day"], datetime.min.time(), tzinfo=timezone.utc)
            existing = await db.get(AgentTokenUsage, (agent_id, bucket, r["model"]))
            if existing is None:
                db.add(AgentTokenUsage(agent_id=agent_id, bucket=bucket, model_name=r["model"], source="manual",
                                       invocation_count=r["calls"], input_tokens=r["inputTokens"], output_tokens=r["outputTokens"]))
            else:
                existing.source, existing.invocation_count = "manual", r["calls"]
                existing.input_tokens, existing.output_tokens = r["inputTokens"], r["outputTokens"]
        _log(db, actor, "usage.manual", agent_id, {"rows": len(rows), "days": sorted({r["day"].isoformat() for r in rows})[:5]})
    return len(rows)


@router.post("/agents/{agent_id}/usage/manual")
async def add_manual_usage(agent_id: str, body: ManualUsage, user=Depends(require_update)):
    return {"stored": await _store_usage(agent_id, [body.model_dump()], user.get("user_id", "unknown"))}


def parse_usage_csv(text: str) -> list[dict]:
    """day,model,calls,input_tokens,output_tokens with a header row."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    need = {"day", "model", "calls", "input_tokens", "output_tokens"}
    if not reader.fieldnames or not need <= {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("The first row must be the header day,model,calls,input_tokens,output_tokens.")
    out = []
    for i, row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            out.append({"day": date.fromisoformat(row["day"]), "model": row["model"][:100], "calls": int(row["calls"]),
                        "inputTokens": int(row["input_tokens"] or 0), "outputTokens": int(row["output_tokens"] or 0)})
        except (ValueError, KeyError):
            raise ValueError(f"Row {i} is not a day (2026-10-08), a model name and whole numbers.")
        if not out[-1]["model"] or min(out[-1]["calls"], out[-1]["inputTokens"], out[-1]["outputTokens"]) < 0:
            raise ValueError(f"Row {i} needs a model name and numbers of 0 or more.")
    if not out:
        raise ValueError("The file has no rows under the header.")
    return out


@router.post("/agents/{agent_id}/usage/import")
async def import_usage(agent_id: str, csv_text: str = Body(..., media_type="text/csv"), user=Depends(require_update)):
    try:
        rows = parse_usage_csv(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"stored": await _store_usage(agent_id, rows, user.get("user_id", "unknown"))}


@router.get("/agents/{agent_id}/usage/manual")
async def list_manual_usage(agent_id: str, _=Depends(require_read)):
    async with get_db_session() as db:
        agent = await _agent(db, agent_id)
        rows = (await db.execute(select(AgentTokenUsage).where(AgentTokenUsage.agent_id == agent_id, AgentTokenUsage.source == "manual")
                                 .order_by(AgentTokenUsage.bucket.desc()).limit(200))).scalars().all()
    return {"allowed": not (agent.phoenix_project or agent.trace_connector_id),
            "rows": [{"day": as_utc(r.bucket).date().isoformat(), "model": r.model_name, "calls": r.invocation_count,
                      "inputTokens": r.input_tokens, "outputTokens": r.output_tokens} for r in rows]}


@router.delete("/agents/{agent_id}/usage/manual")
async def delete_manual_usage(agent_id: str, day: date, model: str, user=Depends(require_update)):
    bucket = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    async with get_db_session() as db:
        await _agent(db, agent_id)
        result = await db.execute(delete(AgentTokenUsage).where(AgentTokenUsage.agent_id == agent_id, AgentTokenUsage.bucket == bucket,
                                                                AgentTokenUsage.model_name == model, AgentTokenUsage.source == "manual"))
        _log(db, user.get("user_id", "unknown"), "usage.manual", agent_id, {"removed": f"{day.isoformat()} {model}"})
    return {"removed": result.rowcount}


# ── Idle and duplicate spend, scenario ───────────────────────────────────────

async def spend_rows(db) -> tuple[list[Agent], dict]:
    agents = (await db.execute(select(Agent).where(Agent.lifecycle_stage != "Deprecated"))).scalars().all()
    return list(agents), await load_economics(db, list(agents))


def duplicate_pairs(agents: list[Agent]) -> list[dict]:
    from governance import reuse
    from services.reuse_repo import agent_mapping

    maps = [agent_mapping(a) for a in agents]
    pairs = []
    for m in maps:
        for s in reuse.similar_agents(m, maps):
            why = ("the same API endpoint" if s["sameEndpoint"] else
                   f"shared capabilities: {', '.join(s['sharedCapabilities'])}" if s["sharedCapabilities"] else
                   f"similar descriptions: {', '.join(s['matchedTerms'][:4])}")
            pairs.append({"a": {"id": m["id"], "name": m["name"]}, "b": {"id": s["id"], "name": s["name"]}, "reason": why})
    return pairs


async def spend_review_data(db) -> dict:
    agents, econ = await spend_rows(db)
    rows = [{"agentId": a.id, "name": a.name, "stage": a.lifecycle_stage, "callsLast30d": econ[a.id]["token"]["callsLast30d"],
             "infraCents": econ[a.id]["infraCostCents"], "infraSource": econ[a.id]["infraSource"],
             "tokenCents": econ[a.id]["tokenCostCents"]} for a in agents]
    cost = {a.id: econ[a.id]["totalCostCents"] for a in agents}
    return {"idle": gv.idle_spend(rows), "duplicates": gv.duplicate_spend(duplicate_pairs(agents), cost)}


@router.get("/portfolio/spend-review")
async def spend_review(_=Depends(require_read)):
    async with get_db_session() as db:
        return await spend_review_data(db)


@router.get("/portfolio/scenario")
async def production_scenario(agents: str = Query("", description="Comma-separated agent ids; empty means every agent not yet in Production"),
                              _=Depends(require_read)):
    ids = [i for i in agents.split(",") if i.strip()]
    async with get_db_session() as db:
        q = select(Agent).where(Agent.lifecycle_stage.not_in(("Production", "Deprecated")))
        if ids:
            q = q.where(Agent.id.in_(ids))
        rows = (await db.execute(q)).scalars().all()
        econ = await load_economics(db, list(rows))
    data = [{"agentId": a.id, "name": a.name, "stage": a.lifecycle_stage, "valueCents": econ[a.id]["valueCents"],
             "valueState": econ[a.id]["valueState"], "tokenCents": econ[a.id]["tokenCostCents"],
             "infraCents": econ[a.id]["infraCostCents"], "infraSource": econ[a.id]["infraSource"]} for a in rows]
    return {**gv.scenario(data, estimated_infra_cents("Production")),
            "caveat": "Value is the figure finance attested, or the owner's declared figure. Token cost is what each agent costs now, "
                      "and more use in Production would raise it."}


# ── Build cost for reuse savings, and the scorecard ──────────────────────────

@router.get("/value/settings")
async def value_settings(_=Depends(require_read)):
    return {"buildCostCents": await get_setting("value.build_cost_cents"), "hourlyRateUsd": get_settings().blended_hourly_rate_usd}


class ValueSettings(BaseModel):
    buildCostCents: Optional[int] = Field(None, ge=0, le=10_000_000_000)


@router.put("/value/settings")
async def update_value_settings(body: ValueSettings, user=Depends(require_admin)):
    await set_setting("value.build_cost_cents", body.buildCostCents, user["user_id"])
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user["user_id"], action="settings.update", entity_type="value",
                        entity_id="build_cost", changes={"buildCostCents": body.buildCostCents}))
    return await value_settings()


async def scorecard_data(db, unit: str | None) -> dict:
    from api.routers.ops.reuse_ops import _figures

    units = dict((await db.execute(select(Department.id, Department.name))).all())
    agents = (await db.execute(select(Agent).where(Agent.lifecycle_stage != "Deprecated"))).scalars().all()
    if unit:
        agents = [a for a in agents if a.dept_id == unit or units.get(a.dept_id) == unit]
    econ = await load_economics(db, list(agents))
    from services import reuse_repo
    risks = await reuse_repo.risk_counts(db, list(agents))
    figures = await _figures(db)
    build_cost = await get_setting("value.build_cost_cents")
    ids = {a.id for a in agents}
    builds = sum(x["buildsAvoided"] for x in figures["agents"] if x["agentId"] in ids)
    rows = []
    for a in sorted(agents, key=lambda a: -econ[a.id]["valueCents"]):
        e = econ[a.id]
        r = risks.get(a.id, {})
        rows.append({"id": a.id, "name": a.name, "unit": units.get(a.dept_id, a.dept_id) or "No unit", "stage": a.lifecycle_stage,
                     "valueCents": e["valueCents"], "valueState": e["valueState"], "valueMethod": e["valueMethodLabel"],
                     "costCents": e["totalCostCents"], "costComplete": e["costComplete"], "tokenSource": e["tokenSource"],
                     "roiPct": e["roiPct"], "openHighRisks": (r.get("CRITICAL", 0) or 0) + (r.get("HIGH", 0) or 0),
                     "buildsAvoided": next((x["buildsAvoided"] for x in figures["agents"] if x["agentId"] == a.id), 0)})
    value = sum(r["valueCents"] for r in rows)
    cost = round(sum(r["costCents"] for r in rows), 2)
    return {
        "scope": unit and (units.get(unit) or unit) or "All units", "agents": rows, "count": len(rows),
        "production": sum(1 for r in rows if r["stage"] == "Production"),
        "valueCents": value, "attestedValueCents": sum(r["valueCents"] for r in rows if r["valueState"] in ("attested", "adjusted")),
        "costCents": cost, "netCents": round(value - cost, 2),
        # No return is worked out while no value is declared at all: -100% would only restate that.
        "roiPct": round(100 * (value - cost) / cost, 1) if cost and value else None,
        "costIncomplete": sum(1 for r in rows if not r["costComplete"]),
        "openHighRisks": sum(r["openHighRisks"] for r in rows),
        "buildsAvoided": builds, "buildCostCents": build_cost,
        "reuseSavingsCents": builds * build_cost if build_cost else None,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _usd(c: float | None) -> str:
    if c is None:
        return "-"
    sign, c = ("-" if c < 0 else ""), abs(c)
    return f"{sign}${c / 100:,.0f}" if c >= 10_000 else f"{sign}${c / 100:,.2f}"


STATE_WORDS = {"none": "not declared", "declared": "declared", "attested": "attested", "adjusted": "adjusted by finance",
               "stale": "declared again, not attested"}


def scorecard_pdf(d: dict) -> bytes:
    from services.pdf import Doc

    doc = Doc(f"Agent scorecard - {d['scope']}")
    doc.heading(f"Agent scorecard: {d['scope']}", 18)
    doc.text(f"Generated {d['generatedAt'][:16].replace('T', ' ')} UTC from the registry. Monthly figures. Retired agents are left out.", 9, grey=True)
    doc.rule()
    doc.table(["Figure", "Value"], [
        ["Agents", f"{d['count']} ({d['production']} in Production)"],
        ["Value a month", f"{_usd(d['valueCents'])}, of which {_usd(d['attestedValueCents'])} attested or adjusted by finance"],
        ["Cost a month (tokens and hosting)", _usd(d['costCents']) + (f" ({d['costIncomplete']} agents without usage data are counted as $0 tokens)" if d['costIncomplete'] else "")],
        ["Net a month", _usd(d['netCents'])],
        ["Return on cost", ("No value is declared yet" if not d['valueCents'] else "-") if d['roiPct'] is None else f"{d['roiPct']}%"],
        ["Open high and critical risks", str(d['openHighRisks'])],
        ["Builds avoided (approved reuse)", str(d['buildsAvoided'])],
        ["Reuse savings", "Set an agreed build cost in Settings" if d['reuseSavingsCents'] is None
         else f"{_usd(d['reuseSavingsCents'])} ({d['buildsAvoided']} x {_usd(d['buildCostCents'])} agreed build cost)"],
    ], [2, 5])
    doc.heading("Agents", 13)
    doc.table(["Agent", "Unit", "Stage", "Value / month", "Value is", "Cost / month", "Return", "High risks", "Reused by"],
              [[r["name"], r["unit"], r["stage"], _usd(r["valueCents"]), STATE_WORDS.get(r["valueState"], r["valueState"]) + (f" ({r['valueMethod']})" if r["valueMethod"] else ""),
                _usd(r["costCents"]) + ("" if r["costComplete"] else " *"), "-" if r["roiPct"] is None else f"{r['roiPct']}%",
                str(r["openHighRisks"]), str(r["buildsAvoided"])] for r in d["agents"]],
              [2.6, 1.4, 1.3, 1.3, 1.8, 1.3, 1, 0.9, 0.9], size=8)
    doc.text("* No usage data: token cost counted as $0. Value is: declared by the owner, attested or adjusted by finance, or stale "
             "(changed after the last finance check). Reused by: teams with approved access.", 8, grey=True)
    return doc.bytes()


@router.get("/portfolio/scorecard")
async def scorecard(unit: Optional[str] = None, format: str = "json", _=Depends(require_read)):
    async with get_db_session() as db:
        d = await scorecard_data(db, unit)
    if format == "pdf":
        name = "".join(ch if ch.isalnum() else "-" for ch in d["scope"].lower())
        return Response(scorecard_pdf(d), media_type="application/pdf",
                        headers={"content-disposition": f'attachment; filename="scorecard-{name}.pdf"'})
    return d
