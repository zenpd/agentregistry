"""Read-only tools for the insight agents.

Each tool calls the same function the matching page uses, so a figure an
agent quotes equals the figure on screen, then trims the result to what an
investigation needs. Nothing here writes: there is no tool that changes a
record, a review, a risk or a stage (tests/test_insights.py checks this).

Every item a tool returns carries a `ref` ("risk:<agent>:<id>"). A finding
may only cite refs handed out during its own run; the RefBook records them.
Owner names and contacts are personal data and are never returned — only
whether one is recorded."""
from __future__ import annotations

import re

import json
import statistics
from typing import Any, Awaitable, Callable, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select

from db.base import get_db_session
from db.models import AuditLog
from governance.context_reader import redact
from governance.costing import normalize_model
from services.usage_repo import load_aliases

_USER = {"user_id": "insight-agent", "role": "viewer"}
MAX_TEXT = 600
# Change-log values that are safe and useful to show; every other changed field is named only.
_SAFE_CHANGE_KEYS = ("model_name", "stage", "lifecycle_stage", "phoenix_project", "ai_type", "risk_level")
# Things the audit log records about an agent that change nothing about it.
_NOT_A_CHANGE = ("insight.run", "agent.refresh", "usage.refresh", "try_it", "job.run")
_CHANGE_WORDS = {"ai.autofill": "record filled in or corrected by the registry", "ai.autofill.undo": "automatic update undone"}


_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*\.?\d*")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.+Z-]*)?|\b\d{1,2}:\d{2}\b")
# Names that contain digits (gpt-4.1-mini, GPT-5, mt103) are names, not figures.
_NAME_WITH_DIGITS = re.compile(r"\b[A-Za-z][A-Za-z_]*[-_.]?\d[\w.]*(?:-[\w.]+)*")


def figures_in(text: str) -> list[float]:
    """The figures written in a piece of text, leaving out dates, times and names that contain digits."""
    out = []
    for raw in _NUMBER.findall(_NAME_WITH_DIGITS.sub(" ", _DATE.sub(" ", text))):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            pass
    return out


class RefBook:
    """The refs handed out in one run, with a readable label for each, and
    every number the tools returned (for the figure check)."""

    def __init__(self) -> None:
        self.labels: dict[str, str] = {}
        self.numbers: set[float] = set()
        self.tools_used: list[str] = []

    def ref(self, kind: str, *parts: Any, label: str) -> str:
        ref = ":".join([kind, *[str(p) for p in parts]])
        self.labels[ref] = str(label)[:160]
        return ref

    def note_numbers(self, value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            self.numbers.add(float(value))
        elif isinstance(value, str):
            # A figure quoted from text the agent read (a description saying "19 specialist agents") is not invented.
            self.numbers |= set(figures_in(value))
        elif isinstance(value, dict):
            for v in value.values():
                self.note_numbers(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                self.note_numbers(v)


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    text = redact(" ".join(str(text or "").split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _no_names(text: Any) -> Any:
    """People's names stay out of what the model reads: 'confirmed ..., by Ana on 2026-10-08' loses the name."""
    return re.sub(r",? by [^,]+? on (\d{4}-\d{2}-\d{2})", r" on \1", text) if isinstance(text, str) else text


def _usd(cents: Any) -> float | None:
    return None if cents is None else round(float(cents) / 100, 4)


async def _agent(agent_id: str) -> dict:
    from api.routers import registry
    return await registry.get_agent(agent_id, _=_USER)


# ── The tools ───────────────────────────────────────────────────────────────

async def get_record(agent_id: str, book: RefBook) -> dict:
    a = await _agent(agent_id)
    return {
        "ref": book.ref("agent", agent_id, label=a["name"]),
        "name": a["name"], "stage": a["stage"], "aiType": a["aiType"], "department": a.get("deptName"),
        "ownerRecorded": bool((a.get("owner") or "").strip()),
        "description": _clip(a.get("description")), "businessOutcome": _clip(a.get("businessOutcome")),
        "capabilities": [_clip(c, 120) for c in (a.get("capabilities") or [])][:15],
        "declaredModel": a.get("modelName"), "declaredRiskLevel": a.get("riskLevel"),
        "declaredMonthlyValueUsd": a.get("valueAmount"), "hoursSavedMonthly": a.get("hoursSavedMonthly"),
        "valueType": a.get("valueType") or None, "sla": a.get("sla"),
        "declaredSystems": a.get("enterpriseSystems") or [], "declaredDatabases": a.get("databases") or [],
        "declaredKnowledgeBases": a.get("knowledgeBases") or [], "declaredToolsAndMcp": a.get("mcpServers") or [],
        "declaredCalls": a.get("calls") or [], "declaredConsumers": a.get("consumers") or [],
        "phoenixProject": a.get("phoenixProject") or None, "weeksInStage": a.get("timeInStageWeeks"),
        "certifiedForReuse": bool((a.get("reuse") or {}).get("certified")),
    }


async def get_automatic_updates(agent_id: str, book: RefBook) -> dict:
    """What the registry filled in or corrected on this record by itself and that still stands,
    and the things it never sets because only a person can give them."""
    from governance import autofill as fill_rules
    from services import autofill
    rows = await autofill.active_updates(agent_id)
    check = await autofill.last_check(agent_id)
    from db.base import get_db_session
    from db.models import Agent
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
    gaps = await autofill.person_gaps(agent) if agent is not None else []
    return {
        # The page lists these itself, below your text.
        "stillNeededFromAPerson": [{"what": g["label"], "why": g["why"]} for g in gaps],
        "lastChecked": check["checkedAt"] if check else None,
        "couldNotRead": list((check or {}).get("unread") or []),
        "filledInAutomatically": [{
            "ref": book.ref("auto", agent_id, r["id"], label=f"{r['label']} (filled in automatically)"),
            "field": r["label"], "previouslyOnTheRecord": r["from"], "nowOnTheRecord": r["to"], "basedOn": r["sourceLabel"],
            "evidenceAtTheTime": r["reason"], "when": r["appliedAt"],
        } for r in rows],
        "note": "These fields are already filled in or corrected: the record now agrees with the evidence. Do not report any of "
                "them as a mismatch, a gap or a change made by the agent. The agent itself did not change.",
        "theRegistryFillsInByItself": list(fill_rules.FIELD_LABELS.values()),
        "onlyAPersonCanProvide": list(fill_rules.ONLY_A_PERSON),
    }


async def get_reviews(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import governance
    g = await governance.get_governance(agent_id, _=_USER)
    gates = []
    for gate in g["gates"]:
        gates.append({
            "ref": book.ref("review", agent_id, gate["gate"], label=f"{gate['label']} review"),
            "gate": gate["gate"], "label": gate["label"], "status": gate["status"],
            "reviewerRole": gate.get("reviewerRole"), "expiresAt": gate.get("expiresAt"),
            "conditions": _clip(gate.get("conditions"), 300) or None,
            "evidenceLinks": len(gate.get("evidence") or []),
            "checklist": [{
                "ref": book.ref("check", agent_id, c["id"], label=c["label"]),
                "item": c["label"], "result": c.get("result"), "automatic": c.get("auto"),
                "ticked": c.get("tick"), "detail": _no_names(c.get("detail")),
            } for c in gate.get("checklist") or []],
            # Model, tools or endpoint changed after this review was approved.
            "changedSinceApproval": [{"what": ch.get("label"), "added": ch.get("added"), "removed": ch.get("removed"),
                                      "before": ch.get("before") if "added" not in ch else None,
                                      "after": ch.get("after") if "added" not in ch else None}
                                     for ch in gate.get("changedSinceApproval") or []],
        })
    return {
        "stage": g["stage"], "riskTier": g.get("riskTier"), "euAiActCategory": g.get("euAiActCategory"),
        "enforcement": g.get("enforcement"), "gates": gates,
        "recertification": g.get("recertification"), "readiness": g.get("readiness"),
        "activeWaivers": len(g.get("exceptions") or []),
        "waiversWaitingForASecondSigner": len(g.get("pendingWaivers") or []),
        "classificationConfirmed": any(c.get("id") == "arb.eu_tier" and c.get("result") == "pass"
                                       for gate in g["gates"] for c in gate.get("checklist") or []),
        "weeksInStage": g.get("weeksInStage"), "stalledInStage": g.get("stalled"),
    }


async def get_risks(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import risk
    r = await risk.agent_risks(agent_id, status="active", _=_USER)
    return {
        "score": r.get("score"), "lastScan": r.get("lastScan"),
        "findings": [{
            "ref": book.ref("risk", agent_id, f["id"], label=f["title"]),
            "title": f["title"], "category": f["category"], "severity": f["severity"], "status": f["status"],
            "rule": f.get("ruleId"), "description": _clip(f.get("description"), 300),
            "firstDetected": f.get("detectedAt"), "mitigation": _clip(f.get("mitigation"), 200) or None,
        } for f in r.get("findings") or []][:40],
        "financial": r.get("financial"),
        "incidents": await _incidents(agent_id, book),
    }


async def _incidents(agent_id: str, book: RefBook) -> list[dict]:
    """Open incidents linked to the agent, and whether its owner was asked to stop it."""
    from sqlalchemy import select
    from db.base import get_db_session
    from db.models import Incident
    async with get_db_session() as db:
        rows = (await db.execute(select(Incident).where(Incident.agent_id == agent_id, Incident.status == "open"))).scalars().all()
    return [{"ref": book.ref("incident", agent_id, i.id, label=f"Incident: {i.title}"), "title": _clip(i.title, 200),
             "severity": i.severity, "openedAt": i.opened_at.isoformat() if i.opened_at else None,
             "ownerAskedToStop": bool(i.stop_requested_at), "stopAcknowledged": bool(i.stop_acknowledged_at)} for i in rows]


def _ratio(now: float, before: float) -> float | None:
    return round(now / before, 2) if before else None


async def get_usage_and_cost(agent_id: str, book: RefBook) -> dict:
    """Usage per day and per model, anomalies and budget — plus, for each day
    with usage, how it compares with the average of the earlier usage days, so
    the agent quotes calculated ratios instead of working them out itself."""
    from api.routers.ops import tokenomics
    t = await tokenomics.agent_tokenomics(agent_id, days=30, _=_USER)
    days = [d for d in t["daily"] if d["calls"]]
    rows, seen = [], []
    for d in days:
        tokens = d["inputTokens"] + d["outputTokens"]
        row = {
            "ref": book.ref("usage", agent_id, d["date"], label=f"Usage on {d['date']}"),
            "date": d["date"], "calls": d["calls"], "inputTokens": d["inputTokens"], "outputTokens": d["outputTokens"],
            "errors": d["errors"], "costUsd": _usd(d["costCents"]), "tokensPerCall": round(tokens / d["calls"], 1),
            "flaggedAsSpike": bool(d.get("spike")),
        }
        if seen:
            row["comparedWithEarlierDays"] = {
                "callsRatio": _ratio(d["calls"], statistics.mean(s["calls"] for s in seen)),
                "tokensPerCallRatio": _ratio(row["tokensPerCall"], statistics.mean(s["tokensPerCall"] for s in seen)),
                "costRatio": _ratio(row["costUsd"] or 0, statistics.mean((s["costUsd"] or 0) for s in seen)),
            }
        rows.append(row)
        seen.append(row)
    return {
        "source": t.get("source"), "windowDays": t["days"], "window": [t["windowStart"], t["windowEnd"]],
        "lastIngestedAt": t.get("lastIngestedAt"), "declaredModel": t.get("declaredModel"),
        "totals": {"calls": t["totals"]["calls"], "inputTokens": t["totals"]["inputTokens"],
                   "outputTokens": t["totals"]["outputTokens"],
                   "totalTokens": t["totals"]["inputTokens"] + t["totals"]["outputTokens"], "errors": t["totals"]["errors"],
                   "costUsd": _usd(t["totals"]["costCents"])},
        "costPerCallUsd": _usd(t.get("costPerCallCents")), "daysWithUsage": len(rows), "daily": rows[-20:],
        "byModel": [{
            "ref": book.ref("model", agent_id, m["model"], label=f"Model {m['model']}"),
            "model": m["model"], "calls": m["calls"], "costUsd": _usd(m["costCents"]), "sharePct": m["sharePct"],
            "priced": m["priced"],
        } for m in t.get("byModel") or []],
        "anomalies": [{
            "ref": book.ref("anomaly", agent_id, a["id"], label=f"Cost anomaly: {a['type'].replace('_', ' ')}"),
            "type": a["type"], "severity": a["severity"], "detectedAt": a["detectedAt"], "details": a.get("details"),
        } for a in t.get("anomalies") or []],
        "budget": {"state": t["budget"]["state"], "monthlyBudgetUsd": _usd(t["budget"]["monthlyBudgetCents"]),
                   "usedPct": t["budget"]["usedPct"], "monthToDateUsd": _usd(t["budget"]["monthToDateCents"])},
        "forecast": t.get("forecast", {}).get("status"),
    }


async def get_economics(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import economics
    e = await economics.agent_economics_endpoint(agent_id, _=_USER)
    return {
        "ref": book.ref("economics", agent_id, label="Value against cost"),
        "month": e["period"]["month"], "valueDeclared": e["valueDeclared"],
        # No figure rather than a zero when nobody declared one: a zero invites comparing it with peers.
        # valueUsd is the figure every page uses: the finance figure when finance attested or adjusted it, else the owner's.
        "valueUsd": _usd(e["valueCents"]) if e["valueDeclared"] else None,
        "valueIs": e.get("valueStateLabel"), "declaredByOwnerUsd": _usd(e.get("valueDeclaredCents")) if e.get("valueDeclaredCents") else None,
        "valueMethod": e.get("valueMethodLabel"),
        "tokenCostUsd": _usd(e["tokenCostCents"]), "tokenCostSource": e["tokenSource"],
        "infraCostUsd": _usd(e["infraCostCents"]), "infraCostSource": e["infraSource"],
        "totalCostUsd": _usd(e["totalCostCents"]), "costComplete": e["costComplete"], "roiPct": e.get("roiPct"),
        "efficiencyRating": e.get("efficiencyRating"), "flags": e.get("financialFlags") or [],
    }


async def get_dependencies(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import diagram
    from discovery import observed_deps
    d = await diagram.dependencies(agent_id, refresh=False, _=_USER)
    if d.get("status") != "ok":
        return {"status": d.get("status"), "reason": d.get("reason"), "declared": d.get("declared")}
    cmp_ = d["comparison"]

    def dep(x: dict, where: str) -> dict:
        return {"ref": book.ref("dep", agent_id, x["name"], label=f"{x.get('kind', 'dependency')} {x['name']}"),
                "name": x["name"], "kind": x.get("kind"), "seenInCalls": x.get("count"), "state": where}
    blast = d.get("blastRadius") or {}
    seen_only = cmp_.get("observed_only") or []
    own_steps = [x for x in seen_only if x.get("kind") == "agent"]
    return {
        "status": "ok", "tracesRead": d["traceCount"], "spansRead": d["spanCount"], "window": d.get("sampleWindow"),
        "absenceIsConclusive": cmp_.get("absenceConclusive"),
        "declaredAndSeen": [dep(x, "declared and seen") for x in cmp_.get("confirmed") or []][:25],
        "declaredButNotSeen": [dep(x, "declared, not seen in traces") for x in cmp_.get("declared_only") or []][:25],
        # Only things a record can declare. The registry adds tools and knowledge sources itself.
        "seenButNotDeclared": [dep(x, "seen in traces, not declared") for x in seen_only if x.get("kind") in observed_deps.ADOPT_FIELD][:25],
        # The record holds one model name; there is no field for a second model or an embedding model.
        "alsoCallsTheseModels": {"names": [x["name"] for x in seen_only if x.get("kind") in ("model", "embedding")][:10],
                                 "note": "Part of how the app works. Nothing has to be recorded for them."},
        # Steps inside the app's own graph. They are how it works, not dependencies: there is nothing to declare.
        "ownSteps": {"count": len(own_steps), "names": [x["name"] for x in own_steps[:20]],
                     "note": "Steps inside this app: part of how it works. Nothing has to be recorded for them."},
        "modelsSeen": d["observed"].get("models"),
        "blastRadius": {"downstreamCount": blast.get("downstreamCount"), "riskLevel": blast.get("riskLevel"),
                        "agentsAffected": [a.get("name") if isinstance(a, dict) else a for a in blast.get("agents") or []][:10],
                        "consumersAffected": blast.get("consumers") or []},
        "sharedResources": d.get("sharedResources") or [],
    }


async def get_trace_graph(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import diagram
    g = await diagram.reconstructed_graph(agent_id, refresh=False, _=_USER)
    if g.get("status") != "ok":
        return {"status": g.get("status"), "reason": g.get("reason")}
    nodes = sorted(g["nodes"], key=lambda n: n["count"], reverse=True)
    return {
        "status": "ok", "mode": g.get("mode"), "tracesRead": g["traceCount"], "spansRead": g["spanCount"],
        "window": g.get("sampleWindow"), "sampleIsTruncated": g.get("truncated"),
        "steps": [{
            "ref": book.ref("step", agent_id, n["id"], label=f"Step {n['name']}"),
            "name": n["name"], "kind": n["kind"], "runs": n["count"], "errors": n["errorCount"],
            "avgLatencyMs": n.get("avgLatencyMs"),
        } for n in nodes[:30]],
        "calls": [{"from": e["from"].split(":", 1)[-1], "to": e["to"].split(":", 1)[-1], "kind": e["kind"], "count": e["count"]}
                  for e in sorted(g["edges"], key=lambda e: e["count"], reverse=True)[:40]],
    }


async def get_context_notes(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import overview
    c = await overview.get_context(agent_id, _=_USER)
    if not c.get("present"):
        return {"present": False}
    return {"ref": book.ref("context", agent_id, label="Context notes"), "present": True,
            "text": _clip(c.get("content"), 4000), "insight": c.get("insight")}


async def get_change_log(agent_id: str, book: RefBook) -> dict:
    async with get_db_session() as db:
        rows = list((await db.execute(
            select(AuditLog).where(AuditLog.entity_id == agent_id, AuditLog.action.notin_(_NOT_A_CHANGE))
            .order_by(AuditLog.created_at.desc()).limit(25)
        )).scalars())
    out = []
    for r in rows:
        changes = r.changes if isinstance(r.changes, dict) else {}
        after = changes.get("after") if isinstance(changes.get("after"), dict) else None
        automatic = r.action == "ai.autofill"
        what = _CHANGE_WORDS.get(r.action, r.action)
        out.append({
            "ref": book.ref("change", agent_id, r.id, label=f"{what} on {str(r.created_at)[:10]}"),
            "at": r.created_at.isoformat() if r.created_at else None, "action": what,
            "by": "the registry, automatically" if automatic else "a person",
            "fieldsChanged": sorted(after if after is not None and r.action.startswith("ai.autofill") else changes)[:20],
            "values": {k: _clip(changes[k], 80) for k in _SAFE_CHANGE_KEYS if k in changes},
        })
    return {"changes": out,
            "note": "An entry made by the registry corrects the record to match the evidence. It is not a change to the agent: "
                    "its model, tools and behaviour were the same before and after."}


async def get_contract(agent_id: str, book: RefBook) -> dict:
    from api.routers.ops import integrate
    i = await integrate.integration(agent_id, _=_USER)
    c = i["contract"]
    return {
        "ref": book.ref("contract", agent_id, label="Contract and reuse status"),
        "endpointRecorded": bool(c.get("apiEndpoint")), "endpointKind": c.get("endpointKind"),
        "capabilities": c.get("capabilities"), "inputs": c.get("inputs"), "outputs": c.get("outputs"),
        "sla": c.get("sla"), "rateLimit": c.get("rateLimit"), "gaps": i.get("gaps"),
        "certifiedForReuse": i["reuse"]["certified"],
        "certificationChecks": [{"check": k.get("label") or k.get("id"), "passed": k.get("ok", k.get("passed"))}
                                for k in i["reuse"].get("checks") or []],
        "approvedConsumerTeams": i.get("consumers", {}).get("approvedTeams"),
    }


async def list_agent_catalog(book: RefBook) -> dict:
    """Every registered agent, briefly — for comparing purposes by meaning."""
    from api.routers import registry
    page = await registry.list_agents(page=1, limit=200, dept="", stage="", type="", q="", certified=False, user=_USER)
    agents = page.get("agents") or page.get("data") or []
    return {"count": len(agents), "agents": [{
        "ref": book.ref("agent", a["id"], label=a["name"]),
        "id": a["id"], "name": a["name"], "stage": a["stage"], "aiType": a["aiType"], "department": a.get("deptName"),
        "purpose": _clip(a.get("description"), 220), "outcome": _clip(a.get("businessOutcome"), 120),
        "capabilities": [_clip(c, 60) for c in (a.get("capabilities") or [])][:6],
        "model": a.get("modelName"), "certifiedForReuse": bool((a.get("reuse") or {}).get("certified")),
    } for a in agents]}


async def search_agents(book: RefBook, text: str = "", stage: str = "", department: str = "", model: str = "") -> dict:
    cat = (await list_agent_catalog(book))["agents"]
    def keep(a: dict) -> bool:
        blob = json.dumps(a).lower()
        return ((not text or text.lower() in blob) and (not stage or a["stage"].lower() == stage.lower())
                and (not department or department.lower() in (a.get("department") or "").lower())
                and (not model or model.lower() in (a.get("model") or "").lower()))
    hits = [a for a in cat if keep(a)]
    return {"matches": len(hits), "agents": hits[:40]}


async def get_portfolio_overview(book: RefBook) -> dict:
    """One row per registered agent with the facts needed to answer questions
    across the whole registry: stage, owner recorded, reviews approved, open
    risks by severity, unresolved cost anomalies and the declared model against
    the models in its usage. Counted from the registry's own tables."""
    from db.models import Agent, AgentRisk, AgentTokenUsage, CostAnomaly, GovernanceReview
    async with get_db_session() as db:
        agents = list((await db.execute(select(Agent))).scalars())
        reviews = list((await db.execute(select(GovernanceReview.agent_id, GovernanceReview.status))).all())
        risks = list((await db.execute(select(AgentRisk.agent_id, AgentRisk.severity, AgentRisk.status))).all())
        anomalies = list((await db.execute(select(CostAnomaly.agent_id, CostAnomaly.anomaly_type)
                                           .where(CostAnomaly.resolved_at.is_(None)))).all())
        used = list((await db.execute(select(AgentTokenUsage.agent_id, AgentTokenUsage.model_name)
                                      .where(AgentTokenUsage.source.in_(("phoenix", "langfuse"))).distinct())).all())
        aliases = await load_aliases(db)
    rows = []
    for a in agents:
        open_risks = [r.severity for r in risks if r.agent_id == a.id and r.status in ("open", "acknowledged", "mitigating")]
        models_used = sorted({u.model_name for u in used if u.agent_id == a.id})
        rows.append({
            "ref": book.ref("agent", a.id, label=a.name), "id": a.id, "name": a.name, "stage": a.lifecycle_stage,
            "aiType": a.ai_type, "ownerRecorded": bool((a.owner or "").strip()),
            "purposeRecorded": len((a.description or "").strip()) >= 20,
            "reviewsApproved": sum(1 for r in reviews if r.agent_id == a.id and str(r.status).startswith("Approved")),
            "reviewsTotal": sum(1 for r in reviews if r.agent_id == a.id),
            "openRisks": len(open_risks), "openHighOrCriticalRisks": sum(1 for s in open_risks if s in ("HIGH", "CRITICAL")),
            "unresolvedCostAnomalies": sorted({x.anomaly_type for x in anomalies if x.agent_id == a.id}),
            "declaredModel": a.model_name, "modelsSeenInRealUsage": models_used,
            # Compared after the registry's own name normalisation, so a version suffix is not a mismatch.
            "declaredModelMatchesUsage": (normalize_model(a.model_name, aliases) in models_used) if models_used and a.model_name else None,
            "hasRealUsage": bool(models_used), "phoenixLinked": bool((a.phoenix_project or "").strip()),
            "declaredMonthlyValueUsd": float(a.value_amount or 0),
        })
    return {"agents": rows, "count": len(rows),
            "note": "declaredModelMatchesUsage is null for agents with no Phoenix usage: for those a model mismatch cannot be judged. Use that field, not your own comparison of names."}


async def get_peer_figures(book: RefBook, ai_type: str = "") -> dict:
    """Declared value and cost of other agents of the same type, as medians,
    so a claimed value can be put in context."""
    from api.routers.ops import economics
    from api.routers import registry
    page = await registry.list_agents(page=1, limit=200, dept="", stage="", type="", q="", certified=False, user=_USER)
    types = {a["id"]: a["aiType"] for a in (page.get("agents") or page.get("data") or [])}
    rows = (await economics.portfolio_economics(_=_USER))["agents"]
    peers = [r for r in rows if not ai_type or types.get(r["agentId"], "").lower() == ai_type.lower()]
    declared = [r["valueCents"] / 100 for r in peers if r.get("valueDeclared") and r["valueCents"]]
    costs = [r["totalCostCents"] / 100 for r in peers if r.get("totalCostCents")]
    return {
        "aiType": ai_type or "all types", "agentsCompared": len(peers), "agentsWithDeclaredValue": len(declared),
        "medianDeclaredMonthlyValueUsd": round(statistics.median(declared), 2) if declared else None,
        "highestDeclaredMonthlyValueUsd": round(max(declared), 2) if declared else None,
        "medianMonthlyCostUsd": round(statistics.median(costs), 2) if costs else None,
    }


async def get_data_freshness(agent_id: str, book: RefBook) -> dict:
    from orchestrations import job_runner
    async with get_db_session() as db:
        latest = await job_runner.latest_runs(db, any_scope=True)
    return {"lastRuns": {name: {"status": row.status, "at": row.started_at.isoformat() if row.started_at else None}
                         for name, row in latest.items() if row is not None}}


# ── Catalogue: name -> (function, description, needs an agent id, extra args) ─

class _NoArgs(BaseModel):
    pass


class _AgentArg(BaseModel):
    agent_id: str = Field(description="The id of the registered agent, exactly as returned by search_agents or list_agent_catalog")


class _SearchArgs(BaseModel):
    text: str = Field("", description="Words to look for in name, purpose or capabilities")
    stage: str = Field("", description="Ideation, Development, Testing, Production or Deprecated")
    department: str = Field("", description="Department name")
    model: str = Field("", description="Model name")


class _PeerArgs(BaseModel):
    ai_type: str = Field("", description="The AI type to compare with, e.g. 'Autonomous Agent'; empty for all")


PER_AGENT: dict[str, tuple[Callable[..., Awaitable[dict]], str]] = {
    "get_record": (get_record, "The agent's declared record: purpose, stage, model, declared dependencies and value."),
    "get_automatic_updates": (get_automatic_updates, "What the registry filled in or corrected on this record by itself, and what only a person can provide."),
    "get_reviews": (get_reviews, "The three governance reviews: status, expiry, checklist items and recertification."),
    "get_risks": (get_risks, "Open risk findings with category, severity and the rule that raised each."),
    "get_usage_and_cost": (get_usage_and_cost, "Usage and cost per day and per model for 30 days, anomalies, budget, and each day compared with earlier days."),
    "get_economics": (get_economics, "Declared value against token and hosting cost this month."),
    "get_dependencies": (get_dependencies, "Declared dependencies against what the traces show, and who is affected if this agent fails."),
    "get_trace_graph": (get_trace_graph, "The steps seen in traces: runs, errors, latency, and which step calls which."),
    "get_context_notes": (get_context_notes, "The owner's context notes, if any."),
    "get_change_log": (get_change_log, "Recent changes to the record: when, what action, which fields."),
    "get_contract": (get_contract, "How other teams call it: contract gaps and reuse certification."),
    "get_data_freshness": (get_data_freshness, "When the registry's daily jobs last refreshed its facts."),
}
GLOBAL: dict[str, tuple[Callable[..., Awaitable[dict]], str, type[BaseModel]]] = {
    "list_agent_catalog": (list_agent_catalog, "Every registered agent, briefly: id, name, purpose, capabilities, stage.", _NoArgs),
    "search_agents": (search_agents, "Find registered agents by words, stage, department or model.", _SearchArgs),
    "get_portfolio_overview": (get_portfolio_overview, "One row per agent: stage, owner recorded, reviews approved, open risks, cost anomalies, declared model against models seen in real usage. Use this for any question across all agents.", _NoArgs),
    "get_peer_figures": (get_peer_figures, "Median declared value and cost of agents of one type.", _PeerArgs),
}
ALL_TOOL_NAMES = (*PER_AGENT, *GLOBAL)


def build_tools(book: RefBook, names: list[str], agent_id: Optional[str]) -> list[StructuredTool]:
    """The named tools as LangChain tools. With `agent_id` given, per-agent
    tools take no arguments (the agent cannot wander to another record);
    without it (Ask the Registry) they take the id as an argument."""
    tools: list[StructuredTool] = []

    def wrap(name: str, call: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[str]]:
        async def run(**kwargs: Any) -> str:
            book.tools_used.append(name)
            try:
                result = await call(**kwargs)
            except Exception as exc:  # a failing tool is reported to the agent, never raised into the run
                detail = getattr(exc, "detail", None) or type(exc).__name__
                result = {"error": f"This tool could not be read: {str(detail)[:200]}"}
            book.note_numbers(result)
            return json.dumps(result, default=str)[:24000]
        return run

    for name in names:
        if name in PER_AGENT:
            fn, description = PER_AGENT[name]
            if agent_id:
                tools.append(StructuredTool.from_function(
                    coroutine=wrap(name, lambda fn=fn: fn(agent_id, book)), name=name, description=description, args_schema=_NoArgs))
            else:
                tools.append(StructuredTool.from_function(
                    coroutine=wrap(name, lambda agent_id, fn=fn: fn(agent_id, book)), name=name, description=description, args_schema=_AgentArg))
        elif name in GLOBAL:
            fn, description, schema = GLOBAL[name]
            tools.append(StructuredTool.from_function(
                coroutine=wrap(name, lambda fn=fn, **kw: fn(book, **kw)), name=name, description=description, args_schema=schema))
        else:
            raise ValueError(f"Unknown insight tool '{name}'")
    return tools
