"""Register many agents from a CSV file: a preview that says, row by row, what
would happen, then a commit that does exactly that. Existing agents are never
changed by an import (a matching row is skipped and says which record it matched)."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.auth import require_create, require_read
from db.base import get_db_session
from db.models import Agent, Department

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Import"])

MAX_ROWS = 500
STAGES = ("Ideation", "Development", "Testing", "Production", "Deprecated")
LIST_COLUMNS = ("capabilities", "inputs", "outputs", "mcp_servers", "knowledge_bases")
COLUMNS = ("name", "description", "owner", "owner_contact", "department", "stage", "stage_reason", "ai_type",
           "business_outcome", "value_amount", "hours_saved_monthly", "phoenix_project", "api_endpoint", "model_name",
           "version", "capabilities", "inputs", "outputs", "mcp_servers", "knowledge_bases", "reuse_justification")
EXAMPLE = ["Invoice Matcher", "Matches supplier invoices to purchase orders", "Finance Ops", "finops@example.com",
           "Finance", "Production", "Live since 2025, registered from the inventory", "Autonomous Agent",
           "Fewer manual invoice checks", "12000", "160", "invoice-matcher", "https://invoices.example.com/api",
           "gpt-4.1-mini", "2.3.0", "Invoice matching|Exception routing", "Supplier invoice|Purchase order",
           "Match result", "SAP MCP", "AP policy KB", ""]


class ImportBody(BaseModel):
    csv: str = Field(..., max_length=2_000_000)


@router.get("/agents/import/template.csv", response_class=PlainTextResponse)
async def import_template(_=Depends(require_read)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    w.writerow(EXAMPLE)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="agent-import-template.csv"'})


def _parse(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail="The first line must be the header row, with at least a name column. Download the template.")
    rows = []
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        rows.append({"line": i, **row})
        if len(rows) > MAX_ROWS:
            raise HTTPException(status_code=422, detail=f"At most {MAX_ROWS} agents per import.")
    return rows


async def _plan(text: str) -> list[dict]:
    from api.routers.registry import AI_TYPES, MIN_REUSE_JUSTIFICATION_CHARS, _similar

    rows = _parse(text)
    async with get_db_session() as db:
        depts = {d.name.lower(): d.id for d in (await db.execute(select(Department))).scalars()}
        depts.update({d.lower(): d for d in depts.values()})
        names = {n.lower(): i for i, n in (await db.execute(select(Agent.id, Agent.name))).all()}
        projects = {p: i for i, p in (await db.execute(select(Agent.id, Agent.phoenix_project).where(Agent.phoenix_project.isnot(None)))).all() if p}
        out, seen = [], set()
        for r in rows:
            problems = []
            name = r.get("name", "")
            if not name:
                problems.append("No name.")
            stage = r.get("stage") or "Ideation"
            if stage not in STAGES:
                problems.append(f"Stage must be one of {', '.join(STAGES)}.")
            elif stage != "Ideation" and len(r.get("stage_reason", "")) < MIN_REUSE_JUSTIFICATION_CHARS:
                problems.append(f"A stage after Ideation needs stage_reason (at least {MIN_REUSE_JUSTIFICATION_CHARS} characters).")
            ai_type = r.get("ai_type") or "Autonomous Agent"
            if ai_type not in AI_TYPES:
                problems.append(f"ai_type must be one of: {', '.join(AI_TYPES)}.")
            dept = r.get("department", "")
            dept_id = depts.get(dept.lower()) if dept else None
            if dept and not dept_id:
                problems.append(f"Unknown department {dept!r}.")
            for num in ("value_amount", "hours_saved_monthly"):
                if r.get(num) and not r[num].replace(",", "").isdigit():
                    problems.append(f"{num} must be a whole number.")
            entry = {"line": r["line"], "name": name, "stage": stage, "action": "create", "reason": "", "matchedAgentId": None}
            if problems:
                out.append({**entry, "action": "error", "reason": " ".join(problems)})
                continue
            if name.lower() in seen:
                out.append({**entry, "action": "error", "reason": "The same name appears earlier in the file."})
                continue
            seen.add(name.lower())
            match = names.get(name.lower()) or projects.get(r.get("phoenix_project") or "")
            if match:
                out.append({**entry, "action": "skip", "matchedAgentId": match,
                            "reason": "Already registered (same name or same Phoenix project). An import never changes an existing agent."})
                continue
            lists = {c: [x.strip() for x in (r.get(c) or "").split("|") if x.strip()] for c in LIST_COLUMNS}
            similar = await _similar(db, {"name": name, "description": r.get("description", ""), "business_outcome": r.get("business_outcome", ""),
                                          "capabilities": lists["capabilities"], "api_endpoint": r.get("api_endpoint", "")})
            if similar and len(r.get("reuse_justification", "")) < MIN_REUSE_JUSTIFICATION_CHARS:
                out.append({**entry, "action": "error", "reason": f"Similar agents exist ({', '.join(m['name'] for m in similar[:3])}). "
                                                                   f"Fill reuse_justification (at least {MIN_REUSE_JUSTIFICATION_CHARS} characters) to register it anyway."})
                continue
            out.append({**entry, "payload": {
                "name": name, "description": r.get("description", ""), "owner": r.get("owner", ""), "owner_contact": r.get("owner_contact", ""),
                "dept": dept_id or "", "stage": stage, "stage_reason": r.get("stage_reason", ""), "ai_type": ai_type,
                "business_outcome": r.get("business_outcome", ""), "value_amount": int((r.get("value_amount") or "0").replace(",", "")),
                "hours_saved_monthly": int((r.get("hours_saved_monthly") or "0").replace(",", "")), "phoenix_project": r.get("phoenix_project", ""),
                "api_endpoint": r.get("api_endpoint", ""), "model_name": r.get("model_name", ""), "version": r.get("version", ""),
                "reuse_justification": r.get("reuse_justification", ""), **lists}})
    return out


def _summary(plan: list[dict]) -> dict:
    return {k: sum(1 for p in plan if p["action"] == k) for k in ("create", "skip", "error")}


@router.post("/agents/import/preview")
async def import_preview(body: ImportBody, _=Depends(require_create)):
    plan = await _plan(body.csv)
    return {"rows": [{k: v for k, v in p.items() if k != "payload"} for p in plan], "summary": _summary(plan)}


@router.post("/agents/import/commit")
async def import_commit(body: ImportBody, user=Depends(require_create)):
    """Creates the rows the preview marks create. Skipped and failing rows are reported, not created."""
    from api.routers.registry import AgentCreate, create_agent

    plan = await _plan(body.csv)
    created, failed = [], []
    for p in plan:
        if p["action"] != "create":
            continue
        try:
            res = await create_agent(AgentCreate(**p["payload"]), user)
            created.append({"line": p["line"], "name": p["name"], "id": res["id"]})
        except HTTPException as exc:
            failed.append({"line": p["line"], "name": p["name"], "reason": str(exc.detail)[:300]})
    return {"created": created, "failed": failed, "summary": {**_summary(plan), "created": len(created)}}
