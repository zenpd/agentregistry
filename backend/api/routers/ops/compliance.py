"""Compliance and audit (items 55 to 62):

- compliance packs and their regulatory dates (dates are settings);
- control coverage, with the missing evidence named per agent;
- evidence packs per agent and per control, as PDF or CSV, whose SHA-256 is
  recorded in the audit log so a file can later be checked against it;
- the check of the hash-chained decision log;
- the data and retention report from the classification answers;
- a GRC export (CSV or JSON) for ServiceNow, OneTrust or Archer."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.auth import require_admin, require_read
from db.base import get_db_session
from db.models import (Agent, AgentRetirement, AgentRisk, AgentVersion, AuditLog, ClassificationRecord, DecisionChain, Department,
                       EvidenceVerdict, GovernanceException, Incident, User)
from governance import compliance as cp
from orchestrations.risk_scan import as_utc
from services import compliance_facts as cf
from services.ai_meter import get_setting, set_setting
from services.pdf import Doc, sha256

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Compliance"])


async def pack_dates() -> dict:
    saved = await get_setting("compliance.dates") or {}
    return {k: [{**d, "date": (saved.get(k) or {}).get(d["key"], d["date"])} for d in p["dates"]] for k, p in cp.PACKS.items()}


async def _all_evidence(db) -> list[dict]:
    return [await cf.agent_evidence(db, a) for a in await cf.in_scope_agents(db)]


@router.get("/compliance/packs")
async def packs(_=Depends(require_read)):
    async with get_db_session() as db:
        agents = await _all_evidence(db)
    registry = await cf.registry_evidence()
    dates = await pack_dates()
    out = []
    for key in cp.PACKS:
        c = cp.coverage(key, agents, registry)
        out.append({k: c[k] for k in ("key", "name", "source", "total", "evidenced", "missing", "outside", "notApplicable", "inRegistry")}
                   | {"dates": dates[key]})
    return {"packs": out, "agents": len(agents), "registry": registry,
            "meaning": "Evidenced: the registry holds the record for every agent the control applies to. It is not a statement of compliance. "
                       "Outside: the evidence is kept outside the registry."}


@router.get("/compliance/packs/{key}")
async def pack(key: str, _=Depends(require_read)):
    if key not in cp.PACKS:
        raise HTTPException(status_code=404, detail="No such pack")
    async with get_db_session() as db:
        agents = await _all_evidence(db)
    result = cp.coverage(key, agents, await cf.registry_evidence())
    return {**result, "dates": (await pack_dates())[key]}


class DatesBody(BaseModel):
    dates: dict[str, dict[str, str]]


@router.put("/compliance/dates")
async def update_dates(body: DatesBody, user=Depends(require_admin)):
    clean: dict = {}
    for pk, values in body.dates.items():
        if pk not in cp.PACKS:
            raise HTTPException(status_code=422, detail=f"No pack {pk!r}")
        keys = {d["key"] for d in cp.PACKS[pk]["dates"]}
        for dk, v in values.items():
            if dk not in keys:
                raise HTTPException(status_code=422, detail=f"No date {dk!r} in {pk}")
            if v:
                try:
                    date.fromisoformat(v)
                except ValueError:
                    raise HTTPException(status_code=422, detail=f"{v!r} is not a date like 2026-08-02")
            clean.setdefault(pk, {})[dk] = v
    await set_setting("compliance.dates", clean, user["user_id"])
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user["user_id"], action="settings.update", entity_type="compliance",
                        entity_id="dates", changes=clean))
    return await pack_dates()


# ── Evidence packs ───────────────────────────────────────────────────────────

def _d(v) -> str:
    return as_utc(v).strftime("%Y-%m-%d") if v else "-"


async def agent_pack_data(db, agent: Agent) -> dict:
    from api.routers.ops.governance import get_governance

    ev = await cf.agent_evidence(db, agent)
    gov = await get_governance(agent.id, None)
    names = dict((await db.execute(select(User.id, User.name))).all())
    units = dict((await db.execute(select(Department.id, Department.name))).all())
    rec = (await db.execute(select(ClassificationRecord).where(ClassificationRecord.agent_id == agent.id, ClassificationRecord.status == "confirmed")
                            .order_by(ClassificationRecord.confirmed_at.desc()).limit(1))).scalar_one_or_none()
    waivers = (await db.execute(select(GovernanceException).where(GovernanceException.agent_id == agent.id))).scalars().all()
    risks = (await db.execute(select(AgentRisk).where(AgentRisk.agent_id == agent.id, AgentRisk.status.in_(("open", "acknowledged", "mitigating"))))).scalars().all()
    versions = (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.released_at))).scalars().all()
    verdicts = (await db.execute(select(EvidenceVerdict).where(EvidenceVerdict.agent_id == agent.id))).scalars().all()
    incidents = (await db.execute(select(Incident).where(Incident.agent_id == agent.id))).scalars().all()
    retire = (await db.execute(select(AgentRetirement).where(AgentRetirement.agent_id == agent.id))).scalars().all()
    decisions = (await db.execute(select(AuditLog, DecisionChain).outerjoin(DecisionChain, DecisionChain.audit_id == AuditLog.id)
                                  .where(AuditLog.entity_type == "agent", AuditLog.entity_id == agent.id,
                                         AuditLog.action.in_(cp_decisions())).order_by(AuditLog.id))).all()
    registry = await cf.registry_evidence()
    controls = []
    for key, p in cp.PACKS.items():
        for c in p["controls"]:
            if cp.applies(c["applies"], ev):
                r = cp.control_for_agent(c, ev["evidence"], registry)
                controls.append({"pack": p["name"], "id": c["id"], "title": c["title"], "status": r["status"],
                                 "missing": ". ".join(r["missing"]) if r["missing"] else (c["outside"] or "")})
    from governance.audit_view import ACTION_LABELS, actor_label, summary_of
    return {
        "agent": {"id": agent.id, "name": agent.name, "stage": agent.lifecycle_stage, "owner": agent.owner or "-",
                  "unit": units.get(agent.dept_id, agent.dept_id) or "-", "purpose": agent.description or "-",
                  "riskLevel": agent.risk_level, "category": agent.eu_ai_act_category},
        "classification": None if rec is None else {
            "category": rec.category, "riskLevel": rec.risk_level, "confirmedBy": names.get(rec.confirmed_by, rec.confirmed_by),
            "confirmedAt": _d(rec.confirmed_at), "reasons": rec.reasons or [], "note": rec.note or "",
            "data": rec.answers.get("data"), "retention": cp.RETENTION.get(rec.answers.get("retention"), "-")},
        "gates": [{"gate": g["label"], "status": g["status"], "reviewer": g.get("reviewer") or "-", "reviewedAt": (g.get("reviewedAt") or "-")[:10],
                   "expiresAt": (g.get("expiresAt") or "-")[:10], "conditions": g.get("conditions") or "",
                   "checklist": [(i["label"], i["result"]) for i in g.get("checklist") or []]} for g in gov["gates"]],
        "evidence": [(cp.AGENT_EVIDENCE[k], v) for k, v in ev["evidence"].items()],
        "controls": controls,
        "waivers": [{"gate": w.gate, "reason": w.reason, "status": w.status or "active", "until": _d(w.expires_at),
                     "signers": ", ".join(filter(None, (names.get(w.first_signer or w.approved_by, w.first_signer or w.approved_by),
                                                        names.get(w.second_signer, w.second_signer))))} for w in waivers],
        "risks": [{"category": r.category, "severity": r.severity, "title": r.title, "status": r.status} for r in risks],
        "versions": [{"version": v.version, "at": _d(v.released_at), "changelog": v.changelog} for v in versions],
        "verdicts": [{"run": v.run_id, "verdict": v.verdict or "not read", "at": _d(v.completed_at), "url": v.url or ""} for v in verdicts],
        "incidents": [{"title": i.title, "severity": i.severity, "status": i.status, "opened": _d(i.opened_at),
                       "stop": "requested" + (", acknowledged" if i.stop_acknowledged_at else ", waiting") if i.stop_requested_at else "-"} for i in incidents],
        "retirements": [{"status": r.status, "reason": r.reason, "started": _d(r.started_at), "completed": _d(r.completed_at)} for r in retire],
        "decisions": [{"at": _d(a.created_at), "by": actor_label(a.actor, names), "action": ACTION_LABELS.get(a.action, a.action),
                       "summary": summary_of(a.action, a.changes), "seal": f"#{c.seq} {c.hash[:16]}" if c else "not sealed yet"}
                      for a, c in decisions],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def cp_decisions() -> frozenset[str]:
    from services.decision_chain import decision_actions
    return decision_actions()


def agent_pack_pdf(d: dict) -> bytes:
    a = d["agent"]
    doc = Doc(f"Evidence pack - {a['name']}")
    doc.heading(f"Evidence pack: {a['name']}", 18)
    doc.text(f"Generated {d['generatedAt'][:16].replace('T', ' ')} UTC from the Agent Registry. The SHA-256 of this file is recorded in the audit trail.", 9, grey=True)
    doc.table(["Field", "Value"], [["Agent id", a["id"]], ["Stage", a["stage"]], ["Owner", a["owner"]], ["Unit", a["unit"]],
                                    ["Risk level", a["riskLevel"] or "-"], ["EU AI Act category", a["category"] or "-"], ["Purpose", a["purpose"]]], [1.3, 5])
    doc.heading("Classification", 13)
    c = d["classification"]
    if c:
        doc.text(f"{c['category']}, risk level {c['riskLevel']}, confirmed by {c['confirmedBy']} on {c['confirmedAt']}. "
                 f"Personal data: {c['data'] or '-'}. Kept: {c['retention']}." + (f" Note: {c['note']}" if c["note"] else ""))
        for r in c["reasons"]:
            doc.text(f"- {r}", 9)
    else:
        doc.text("Not confirmed.")
    doc.heading("Reviews", 13)
    for g in d["gates"]:
        doc.text(f"{g['gate']}: {g['status']}. Reviewer {g['reviewer']}, reviewed {g['reviewedAt']}, approval until {g['expiresAt']}."
                 + (f" Conditions: {g['conditions']}" if g["conditions"] else ""), bold=True, size=10)
        doc.table(["Checklist item", "Result"], [[label, result] for label, result in g["checklist"]], [6, 1.2], size=8)
    doc.heading("Evidence the registry holds", 13)
    doc.table(["Evidence", "Present"], [[k, "yes" if v else "no"] for k, v in d["evidence"]], [6, 1.2], size=8)
    doc.heading("Controls", 13)
    doc.table(["Pack", "Control", "Status", "Missing evidence or where it is kept"],
              [[x["pack"], f"{x['id']} {x['title']}", x["status"], x["missing"]] for x in d["controls"]], [1.4, 3, 1.1, 4], size=7.5)
    for title, rows, head, widths in (
            ("Waivers", [[w["gate"], w["status"], w["until"], w["signers"], w["reason"]] for w in d["waivers"]], ["Gate", "Status", "Until", "Signed by", "Reason"], [1, 1, 1, 2, 4]),
            ("Open risks", [[r["category"], r["severity"], r["status"], r["title"]] for r in d["risks"]], ["Category", "Severity", "Status", "Finding"], [1.4, 1, 1.1, 5]),
            ("Versions", [[v["version"], v["at"], v["changelog"]] for v in d["versions"]], ["Version", "Released", "Changelog"], [1, 1, 6]),
            ("AssureAI verdicts", [[v["run"], v["verdict"], v["at"], v["url"]] for v in d["verdicts"]], ["Run", "Verdict", "Completed", "Link"], [2.5, 1, 1, 3.5]),
            ("Incidents", [[i["title"], i["severity"], i["status"], i["opened"], i["stop"]] for i in d["incidents"]], ["Incident", "Severity", "Status", "Opened", "Stop request"], [3.5, 1, 1, 1, 1.8]),
            ("Retirement", [[r["status"], r["started"], r["completed"], r["reason"]] for r in d["retirements"]], ["Status", "Started", "Completed", "Reason"], [1, 1, 1, 5]),
            ("Decisions (sealed in the hash chain)", [[x["at"], x["by"], x["action"], x["summary"], x["seal"]] for x in d["decisions"]],
             ["Date", "By", "Decision", "Detail", "Seal"], [1, 1.4, 1.6, 4, 1.8])):
        doc.heading(title, 13)
        if rows:
            doc.table(head, rows, widths, size=7.5)
        else:
            doc.text("None recorded.", 9, grey=True)
    return doc.bytes()


def agent_pack_csv(d: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "item", "status", "detail"])
    a = d["agent"]
    for k in ("id", "name", "stage", "owner", "unit", "riskLevel", "category"):
        w.writerow(["agent", k, "", a[k]])
    if d["classification"]:
        c = d["classification"]
        w.writerow(["classification", c["category"], c["riskLevel"], f"confirmed by {c['confirmedBy']} on {c['confirmedAt']}, data {c['data']}, kept {c['retention']}"])
    for g in d["gates"]:
        w.writerow(["review", g["gate"], g["status"], f"reviewer {g['reviewer']}, until {g['expiresAt']}"])
        for label, result in g["checklist"]:
            w.writerow(["checklist", f"{g['gate']}: {label}", result, ""])
    for k, v in d["evidence"]:
        w.writerow(["evidence", k, "yes" if v else "no", ""])
    for x in d["controls"]:
        w.writerow(["control", f"{x['pack']} {x['id']} {x['title']}", x["status"], x["missing"]])
    for x in d["decisions"]:
        w.writerow(["decision", f"{x['at']} {x['action']}", x["by"], f"{x['summary']} | {x['seal']}"])
    for x in d["incidents"]:
        w.writerow(["incident", x["title"], x["status"], f"{x['severity']}, opened {x['opened']}, stop {x['stop']}"])
    return buf.getvalue().encode()


async def _record_export(user: dict, what: str, entity_type: str, entity_id: str, digest: str, fmt: str) -> None:
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="evidence.export", entity_type=entity_type,
                        entity_id=entity_id, changes={"what": what, "format": fmt, "sha256": digest}))


@router.get("/agents/{agent_id}/evidence-pack")
async def evidence_pack(agent_id: str, format: str = Query("pdf", pattern="^(pdf|csv|json)$"), user=Depends(require_read)):
    async with get_db_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.governance_reviews)))).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        d = await agent_pack_data(db, agent)
    if format == "json":
        return d
    data = agent_pack_pdf(d) if format == "pdf" else agent_pack_csv(d)
    digest = sha256(data)
    await _record_export(user, f"Evidence pack of {d['agent']['name']}", "agent", agent_id, digest, format)
    return Response(data, media_type="application/pdf" if format == "pdf" else "text/csv",
                    headers={"content-disposition": f'attachment; filename="evidence-{agent_id}.{format}"', "X-Evidence-SHA256": digest,
                             "Access-Control-Expose-Headers": "X-Evidence-SHA256"})


@router.get("/compliance/packs/{key}/controls/{control_id}/evidence")
async def control_evidence(key: str, control_id: str, format: str = Query("csv", pattern="^(pdf|csv)$"), user=Depends(require_read)):
    if key not in cp.PACKS:
        raise HTTPException(status_code=404, detail="No such pack")
    async with get_db_session() as db:
        agents = await _all_evidence(db)
    cov = cp.coverage(key, agents, await cf.registry_evidence())
    ctl = next((c for c in cov["controls"] if c["id"] == control_id), None)
    if ctl is None:
        raise HTTPException(status_code=404, detail="No such control")
    rows = [[a["name"], a["status"], ". ".join(a["missing"])] for a in ctl["agents"]]
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["pack", "control", "title", "control status", "applies to", "evidence asked", "agent", "agent status", "missing"])
        for r in rows or [["-", "-", "-"]]:
            w.writerow([cov["name"], ctl["id"], ctl["title"], ctl["status"], ctl["appliesText"], " | ".join(ctl["evidence"]) or (ctl["outside"] or ""), *r])
        data = buf.getvalue().encode()
    else:
        doc = Doc(f"{cov['name']} {ctl['id']}")
        doc.heading(f"{cov['name']} {ctl['id']}: {ctl['title']}", 15)
        doc.text(f"Status: {ctl['status']}. Applies to {ctl['appliesText']}: {ctl['agentsInScope']} agents.")
        doc.text("Evidence asked: " + (". ".join(ctl["evidence"]) if ctl["evidence"] else (ctl["outside"] or "-")))
        doc.table(["Agent", "Status", "Missing evidence"], rows or [["-", "-", "-"]], [2.5, 1.2, 5])
        data = doc.bytes()
    digest = sha256(data)
    await _record_export(user, f"Evidence of {cov['name']} {ctl['id']}", "control", f"{key}:{control_id}"[:64], digest, format)
    safe = "".join(ch if ch.isalnum() else "-" for ch in control_id)
    return Response(data, media_type="application/pdf" if format == "pdf" else "text/csv",
                    headers={"content-disposition": f'attachment; filename="{key}-{safe}.{format}"', "X-Evidence-SHA256": digest,
                             "Access-Control-Expose-Headers": "X-Evidence-SHA256"})


@router.get("/compliance/exports/check")
async def check_export(sha256_hex: str = Query(..., alias="sha256", min_length=64, max_length=64), _=Depends(require_read)):
    """Says whether a file with this SHA-256 was exported by the registry, and when."""
    async with get_db_session() as db:
        rows = (await db.execute(select(AuditLog).where(AuditLog.action == "evidence.export").order_by(AuditLog.id.desc()).limit(5000))).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
    hit = next((r for r in rows if (r.changes or {}).get("sha256") == sha256_hex.lower()), None)
    if hit is None:
        return {"found": False}
    return {"found": True, "what": hit.changes.get("what"), "format": hit.changes.get("format"),
            "exportedAt": as_utc(hit.created_at).isoformat(), "by": names.get(hit.actor, hit.actor)}


# ── Decision log, data report, GRC export ────────────────────────────────────

@router.get("/compliance/decision-log/verify")
async def verify_decision_log(_=Depends(require_read)):
    from services.decision_chain import verify
    return await verify()


@router.get("/compliance/data-report")
async def data_report(format: str = Query("json", pattern="^(json|csv)$"), _=Depends(require_read)):
    from governance.classification import DATA
    async with get_db_session() as db:
        agents = await cf.in_scope_agents(db)
        units = dict((await db.execute(select(Department.id, Department.name))).all())
        names = dict((await db.execute(select(User.id, User.name))).all())
        recs = {}
        for r in (await db.execute(select(ClassificationRecord).where(ClassificationRecord.status == "confirmed")
                                   .order_by(ClassificationRecord.confirmed_at))).scalars():
            recs[r.agent_id] = r
    rows = []
    for a in sorted(agents, key=lambda a: a.name.lower()):
        r = recs.get(a.id)
        ans = r.answers if r else {}
        rows.append({"agentId": a.id, "name": a.name, "unit": units.get(a.dept_id, a.dept_id) or "-", "stage": a.lifecycle_stage,
                     "data": DATA.get(ans.get("data"), "Not recorded (no confirmed classification)") if r else "Not recorded (no confirmed classification)",
                     "dataKey": ans.get("data"), "retention": cp.RETENTION.get(ans.get("retention"), "Not recorded" if ans.get("data") not in (None, "none") else "-"),
                     "affects": {"staff": "Staff only", "public": "Customers or the public", "both": "Staff and the public"}.get(ans.get("audience"), "-"),
                     "confirmedBy": names.get(r.confirmed_by, r.confirmed_by) if r else None, "confirmedAt": _d(r.confirmed_at) if r else None,
                     "tracing": bool(a.phoenix_project or a.trace_connector_id)})
    summary = {"agents": len(rows), "personal": sum(1 for r in rows if r["dataKey"] == "personal"),
               "special": sum(1 for r in rows if r["dataKey"] == "special"), "none": sum(1 for r in rows if r["dataKey"] == "none"),
               "unknown": sum(1 for r in rows if r["dataKey"] is None)}
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["agent", "unit", "stage", "personal data", "kept", "affects", "confirmed by", "confirmed on", "traces linked"])
        for r in rows:
            w.writerow([r["name"], r["unit"], r["stage"], r["data"], r["retention"], r["affects"], r["confirmedBy"] or "-", r["confirmedAt"] or "-",
                        "yes" if r["tracing"] else "no"])
        return Response(buf.getvalue(), media_type="text/csv", headers={"content-disposition": 'attachment; filename="data-and-retention.csv"'})
    return {"rows": rows, "summary": summary,
            "note": "From the confirmed classification answers. Traces linked means call data, which can hold personal data, is kept in the tracing system too."}


GRC_TOOLS = {"servicenow": "ServiceNow", "onetrust": "OneTrust", "archer": "Archer"}


@router.get("/compliance/grc-export")
async def grc_export(tool: str = Query("servicenow"), kind: str = Query("inventory", pattern="^(inventory|controls)$"),
                     format: str = Query("csv", pattern="^(csv|json)$"), user=Depends(require_read)):
    """Rows for a GRC tool's import. Inventory: one row per agent. Controls: one row per
    pack control with its status and the agents missing evidence. Map the columns in the
    tool's import step."""
    if tool not in GRC_TOOLS:
        raise HTTPException(status_code=422, detail=f"tool is one of: {', '.join(GRC_TOOLS)}")
    async with get_db_session() as db:
        agents = await cf.in_scope_agents(db)
        units = dict((await db.execute(select(Department.id, Department.name))).all())
        evidence = [await cf.agent_evidence(db, a) for a in agents]
    registry = await cf.registry_evidence()
    if kind == "inventory":
        by_id = {e["id"]: e for e in evidence}
        rows = [{"asset_id": a.id, "name": a.name, "description": a.description or "", "business_unit": units.get(a.dept_id, a.dept_id) or "",
                 "owner": a.owner or "", "lifecycle_stage": a.lifecycle_stage, "risk_level": a.risk_level or "",
                 "eu_ai_act_category": a.eu_ai_act_category or "", "classification_confirmed": "yes" if by_id[a.id]["classified"] else "no",
                 "model": a.model_name or "", "registry_link": f"/agents/{a.id}"} for a in agents]
    else:
        rows = []
        for key in cp.PACKS:
            cov = cp.coverage(key, evidence, registry)
            for c in cov["controls"]:
                rows.append({"framework": cov["name"], "control_id": c["id"], "control_title": c["title"], "status": c["status"],
                             "applies_to": c["appliesText"], "agents_in_scope": c["agentsInScope"], "agents_missing_evidence": c["agentsMissing"],
                             "missing_on": " | ".join(f"{a['name']}: {', '.join(a['missing'])}" for a in c["agents"] if a["status"] == "missing")[:2000],
                             "evidence_kept_outside": c["outside"] or ""})
    async with get_db_session() as db:
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="grc.export", entity_type="compliance",
                        entity_id=f"{tool}:{kind}", changes={"tool": GRC_TOOLS[tool], "kind": kind, "rows": len(rows), "format": format}))
    if format == "json":
        return {"tool": GRC_TOOLS[tool], "kind": kind, "rows": rows}
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="{tool}-{kind}.csv"'})
