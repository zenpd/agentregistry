"""The hash chain over decision records (item 59).

Every decision row in the audit log (gate decisions, stage changes, waivers, access
decisions, classifications, ownership, retirement and similar) is sealed into
decision_chain right after the session that wrote it commits. Each entry's hash
covers the decision's stored content and the previous entry's hash, so a changed,
removed or re-ordered decision breaks the chain from that point on. verify()
recomputes every hash and names the first entry that no longer matches.

Both tables are append-only in the database (triggers), so the chain guards
against changes made around the application, such as edits straight in the database."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import Session

GENESIS = "0" * 64
_lock = asyncio.Lock()


def decision_actions() -> frozenset[str]:
    from governance.audit_view import CATEGORIES
    return frozenset(CATEGORIES["Decisions"])


def _ts(v) -> str:
    if v is None:
        return ""
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def row_digest(row) -> str:
    """A stable text of what a decision row says."""
    return json.dumps({"id": row.id, "at": _ts(row.created_at), "actor": row.actor, "action": row.action,
                       "entityType": row.entity_type, "entityId": row.entity_id, "changes": row.changes},
                      sort_keys=True, default=str, separators=(",", ":"))


def link_hash(prev_hash: str, digest: str) -> str:
    return hashlib.sha256((prev_hash + "\n" + digest).encode()).hexdigest()


# A session that adds a decision row is flagged, so get_db_session seals it after commit.
@event.listens_for(Session, "before_flush")
def _flag_decisions(session, flush_context, instances):
    from db.models import AuditLog
    if any(isinstance(o, AuditLog) and o.action in decision_actions() for o in session.new):
        session.info["seal_decisions"] = True


async def seal_pending() -> int:
    """Appends every decision row not yet in the chain, in id order. Returns how many."""
    from db.base import AsyncSessionLocal
    from db.models import AuditLog, DecisionChain

    async with _lock:
        async with AsyncSessionLocal() as db:
            last = (await db.execute(select(DecisionChain).order_by(DecisionChain.seq.desc()).limit(1))).scalar_one_or_none()
            sealed = select(DecisionChain.audit_id)
            rows = (await db.execute(select(AuditLog).where(AuditLog.action.in_(decision_actions()), AuditLog.id.not_in(sealed))
                                     .order_by(AuditLog.id))).scalars().all()
            prev, seq = (last.hash, last.seq) if last else (GENESIS, 0)
            now = datetime.now(timezone.utc)
            for r in rows:
                seq += 1
                h = link_hash(prev, row_digest(r))
                db.add(DecisionChain(seq=seq, audit_id=r.id, prev_hash=prev, hash=h, sealed_at=now))
                prev = h
            await db.commit()
            return len(rows)


async def verify() -> dict:
    """Recomputes the chain. {ok, entries, firstBroken: {seq, auditId, problem}|None, unsealed, lastHash}."""
    from db.base import AsyncSessionLocal
    from db.models import AuditLog, DecisionChain

    await seal_pending()
    async with AsyncSessionLocal() as db:
        chain = (await db.execute(select(DecisionChain).order_by(DecisionChain.seq))).scalars().all()
        rows = {r.id: r for r in (await db.execute(select(AuditLog).where(AuditLog.id.in_([c.audit_id for c in chain])))).scalars()} if chain else {}
        unsealed = len((await db.execute(select(AuditLog.id).where(AuditLog.action.in_(decision_actions()),
                                                                   AuditLog.id.not_in(select(DecisionChain.audit_id))))).all())
    prev, broken = GENESIS, None
    for i, c in enumerate(chain, start=1):
        row = rows.get(c.audit_id)
        problem = None
        if c.seq != i:
            problem = f"entry {i} is missing or out of order"
        elif c.prev_hash != prev:
            problem = "it does not follow the entry before it"
        elif row is None:
            problem = "the decision it seals is gone from the audit log"
        elif link_hash(prev, row_digest(row)) != c.hash:
            problem = "the decision was changed after it was sealed"
        if problem:
            broken = {"seq": c.seq, "auditId": c.audit_id, "problem": problem}
            break
        prev = c.hash
    first = chain[0].sealed_at if chain else None
    return {"ok": broken is None, "entries": len(chain), "firstBroken": broken, "unsealed": unsealed,
            "lastHash": chain[-1].hash if chain and broken is None else None,
            # Decisions made before this moment were sealed as they stood then: the chain protects them from that point on.
            "sealingSince": (first if first.tzinfo else first.replace(tzinfo=timezone.utc)).isoformat() if first else None,
            "checkedAt": datetime.now(timezone.utc).isoformat()}
