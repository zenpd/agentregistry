"""The audit trail: every recorded change, decision and automatic action,
filterable and exportable. Reading it needs the "audit" permission (Registry
Admin, Auditor). An export is itself recorded."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from api.auth import require_audit
from db.base import get_db_session
from db.models import Agent, AuditLog, User
from db.scope import set_scope, reset_scope
from governance import audit_view as av
from orchestrations.risk_scan import as_utc

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Audit"])

EXPORT_LIMIT = 20_000


def _parse_day(value: Optional[str], end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        day = datetime.fromisoformat(value[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Dates are YYYY-MM-DD, got {value!r}")
    return day + timedelta(days=1) if end else day


def _filtered(actor, action, category, kind, entity, date_from, date_to, q):
    stmt = select(AuditLog)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if category:
        actions = av.MACHINE_ACTIONS if category == "Registry automation" else av.CATEGORIES.get(category)
        if actions is None:
            raise HTTPException(status_code=422, detail=f"Unknown category {category!r}")
        stmt = stmt.where(AuditLog.action.in_(actions))
    machine = or_(AuditLog.action.in_(av.MACHINE_ACTIONS), *[AuditLog.actor.like(f"{p}%") for p in av.SYSTEM_PREFIXES])
    if kind == "people":
        stmt = stmt.where(~machine)
    elif kind == "machine":
        stmt = stmt.where(machine)
    elif kind not in ("all", "", None):
        raise HTTPException(status_code=422, detail="kind is people, machine or all")
    if entity:
        stmt = stmt.where(AuditLog.entity_id == entity)
    start, end = _parse_day(date_from), _parse_day(date_to, end=True)
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at < end)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(AuditLog.action).like(like), func.lower(AuditLog.entity_id).like(like)))
    return stmt


async def _rows(db, rows: list[AuditLog]) -> list[dict]:
    names = dict((await db.execute(select(User.id, User.name))).all())
    agent_ids = {r.entity_id for r in rows if r.entity_type == "agent" and r.entity_id}
    # Names of every agent, demo or not: the trail never hides who was changed.
    tokens = set_scope(False)
    try:
        agents = dict((await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))).all()) if agent_ids else {}
    finally:
        reset_scope(tokens)
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "at": as_utc(r.created_at).isoformat() if r.created_at else None,
            "actorId": r.actor,
            "actor": av.actor_label(r.actor, names),
            "kind": "machine" if av.is_machine(r.actor, r.action) else "people",
            "category": av.category_of(r.action),
            "action": r.action,
            "actionLabel": av.ACTION_LABELS.get(r.action, r.action),
            "entityType": r.entity_type,
            "entityId": r.entity_id,
            "entityName": agents.get(r.entity_id) if r.entity_type == "agent" else None,
            "summary": av.summary_of(r.action, r.changes),
        })
    return out


@router.get("/audit")
async def audit_trail(
    actor: str = "", action: str = "", category: str = "", kind: str = "people", entity: str = "",
    date_from: str = Query("", alias="from"), date_to: str = Query("", alias="to"), q: str = "",
    before_id: Optional[int] = None, limit: int = Query(50, ge=1, le=200),
    _=Depends(require_audit),
):
    """Newest first. Page with before_id (the last id you have). Defaults to
    events by people, because automatic runs outnumber them."""
    async with get_db_session() as db:
        stmt = _filtered(actor, action, category, kind, entity, date_from, date_to, q)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        if before_id:
            stmt = stmt.where(AuditLog.id < before_id)
        rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
        data = await _rows(db, list(rows))
    return {"rows": data, "total": total, "nextBeforeId": data[-1]["id"] if len(data) == limit else None}


@router.get("/audit/options")
async def audit_options(_=Depends(require_audit)):
    """Values the filters offer: everyone who appears in the trail, every action recorded."""
    async with get_db_session() as db:
        actors = (await db.execute(select(AuditLog.actor).distinct())).scalars().all()
        actions = (await db.execute(select(AuditLog.action).distinct())).scalars().all()
        names = dict((await db.execute(select(User.id, User.name))).all())
    return {
        "actors": sorted(({"id": a, "label": av.actor_label(a, names)} for a in actors), key=lambda x: x["label"].lower()),
        "actions": sorted(({"id": a, "label": av.ACTION_LABELS.get(a, a)} for a in actions), key=lambda x: x["label"].lower()),
        "categories": [*av.CATEGORIES, "Registry automation", "Other"],
    }


@router.get("/audit/export.csv")
async def audit_export(
    actor: str = "", action: str = "", category: str = "", kind: str = "people", entity: str = "",
    date_from: str = Query("", alias="from"), date_to: str = Query("", alias="to"), q: str = "",
    user=Depends(require_audit),
):
    """The current filter as CSV (at most 20,000 rows, newest first). The export
    is recorded in the trail with the filter used."""
    async with get_db_session() as db:
        stmt = _filtered(actor, action, category, kind, entity, date_from, date_to, q)
        rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(EXPORT_LIMIT))).scalars().all()
        data = await _rows(db, list(rows))
        db.add(AuditLog(org_id="org-default", actor=user.get("user_id", "unknown"), action="audit.export",
                        entity_type="audit", entity_id=None,
                        changes={"rows": len(data), "filter": {k: v for k, v in {
                            "actor": actor, "action": action, "category": category, "kind": kind, "entity": entity,
                            "from": date_from, "to": date_to, "q": q}.items() if v}}))
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["When (UTC)", "Who", "Person or registry", "Category", "Action", "Entity type", "Entity id", "Entity name", "Details"])
    for r in data:
        w.writerow([r["at"], r["actor"], r["kind"], r["category"], r["actionLabel"], r["entityType"], r["entityId"] or "",
                    r["entityName"] or "", r["summary"]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="audit-trail-{stamp}.csv"'})
