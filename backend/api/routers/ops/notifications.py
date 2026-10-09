"""The signed-in person's notification inbox, and the channel status Settings shows."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from api.auth import require_admin, require_read
from db.base import get_db_session
from db.models import Notification
from orchestrations.risk_scan import as_utc
from services import notify

router = APIRouter(prefix="/api/v1", tags=["Agent Ops — Notifications"])


def _to_api(n: Notification) -> dict:
    return {
        "id": n.id, "kind": n.kind, "subject": n.subject, "items": n.items or [],
        "createdAt": as_utc(n.created_at).isoformat() if n.created_at else None,
        "read": n.read_at is not None, "deliveries": n.deliveries or {},
    }


@router.get("/notifications/mine")
async def my_notifications(limit: int = Query(30, ge=1, le=100), user=Depends(require_read)):
    me = user.get("user_id")
    async with get_db_session() as db:
        rows = (await db.execute(select(Notification).where(Notification.user_id == me)
                                 .order_by(Notification.created_at.desc(), Notification.id).limit(limit))).scalars().all()
        unread = (await db.execute(select(func.count()).select_from(Notification).where(
            Notification.user_id == me, Notification.read_at.is_(None)))).scalar() or 0
    return {"rows": [_to_api(n) for n in rows], "unread": unread}


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, user=Depends(require_read)):
    async with get_db_session() as db:
        n = await db.get(Notification, notification_id)
        if n is None or n.user_id != user.get("user_id"):
            raise HTTPException(status_code=404, detail="Notification not found")
        n.read_at = n.read_at or notify.utcnow()
    return {"status": "read"}


@router.post("/notifications/read-all")
async def mark_all_read(user=Depends(require_read)):
    async with get_db_session() as db:
        rows = (await db.execute(select(Notification).where(
            Notification.user_id == user.get("user_id"), Notification.read_at.is_(None)))).scalars().all()
        for n in rows:
            n.read_at = notify.utcnow()
    return {"status": "read", "count": len(rows)}


@router.get("/notifications/status")
async def channel_status(_=Depends(require_read)):
    """Which channels are configured. Secrets are never returned."""
    async with get_db_session() as db:
        last = (await db.execute(select(Notification).where(Notification.user_id.is_not(None))
                                 .order_by(Notification.created_at.desc()).limit(1))).scalar()
    return {**notify.channels(), "lastSentAt": as_utc(last.created_at).isoformat() if last and last.created_at else None,
            "lastDelivery": (last.deliveries or {}) if last else None}


@router.post("/notifications/test")
async def send_test(user=Depends(require_admin)):
    """Send a test message to yourself through every configured channel."""
    nid = await notify.enqueue(user_id=user.get("user_id"), kind="test", subject="Agent Registry: test notification",
                               items=[{"type": "test", "text": "This is a test. Notifications reach you here.", "link": "/settings"}],
                               dedupe_key=f"test:{secrets.token_hex(6)}")
    deliveries = await notify.deliver(nid) if nid else {}
    return {"id": nid, "deliveries": deliveries}
