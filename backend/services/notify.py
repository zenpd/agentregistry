"""Notifications: store a message for a person (the in-app inbox), then deliver
it by e-mail and to the Teams channel when those are configured.

A message is unique by its dedupe key, so a job that runs twice in a day does
not send the same digest twice. Delivery never raises: a failed e-mail is
recorded on the message and shown in Settings."""
from __future__ import annotations

import asyncio
import secrets
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy import select

from db.base import get_db_session
from db.models import Notification, User
from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("services.notify")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def channels() -> dict:
    """Which outside channels are configured (never the secrets themselves)."""
    s = get_settings()
    return {
        "inApp": True,
        "email": bool(s.smtp_host and s.smtp_from),
        "teams": bool(s.teams_webhook_url),
        "emailFrom": s.smtp_from or None,
    }


def _link(path: str | None) -> str | None:
    if not path:
        return None
    return path if path.startswith("http") else get_settings().app_base_url.rstrip("/") + path


def _text_body(subject: str, items: list[dict]) -> str:
    lines = [subject, ""]
    for it in items:
        link = _link(it.get("link"))
        lines.append(f"- {it['text']}" + (f"\n  {link}" if link else ""))
    lines += ["", "Sent by the Agent Registry. Open the registry to act on these items."]
    return "\n".join(lines)


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def _post_teams(subject: str, items: list[dict]) -> None:
    text = f"**{subject}**\n\n" + "\n".join(
        f"- {it['text']}" + (f" ([open]({_link(it.get('link'))}))" if it.get("link") else "") for it in items)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(get_settings().teams_webhook_url, json={"text": text})
        r.raise_for_status()


async def enqueue(*, user_id: str | None, kind: str, subject: str, items: list[dict], dedupe_key: str) -> str | None:
    """Store a message unless one with the same key exists. Returns its id, or None when it already existed."""
    async with get_db_session() as db:
        exists = (await db.execute(select(Notification.id).where(Notification.dedupe_key == dedupe_key))).scalar()
        if exists:
            return None
        n = Notification(id=secrets.token_hex(10), org_id="org-default", user_id=user_id, kind=kind,
                         subject=subject[:300], items=items, dedupe_key=dedupe_key[:200], deliveries={})
        db.add(n)
        return n.id


async def deliver(notification_id: str) -> dict:
    """Send one stored message by e-mail (to its person) or to Teams (no person)."""
    ch = channels()
    async with get_db_session() as db:
        n = await db.get(Notification, notification_id)
        if n is None:
            return {}
        user = await db.get(User, n.user_id) if n.user_id else None
        subject, items = n.subject, list(n.items or [])
    deliveries: dict = {}
    if user is not None:
        if not ch["email"]:
            deliveries["email"] = {"status": "not_configured", "at": utcnow().isoformat()}
        elif not user.email:
            deliveries["email"] = {"status": "no_email", "at": utcnow().isoformat()}
        else:
            try:
                await asyncio.to_thread(_send_email, user.email, subject, _text_body(subject, items))
                deliveries["email"] = {"status": "sent", "at": utcnow().isoformat()}
            except Exception as exc:  # recorded, never raised
                deliveries["email"] = {"status": "failed", "error": str(exc)[:300], "at": utcnow().isoformat()}
    else:
        if not ch["teams"]:
            deliveries["teams"] = {"status": "not_configured", "at": utcnow().isoformat()}
        else:
            try:
                await _post_teams(subject, items)
                deliveries["teams"] = {"status": "sent", "at": utcnow().isoformat()}
            except Exception as exc:
                deliveries["teams"] = {"status": "failed", "error": str(exc)[:300], "at": utcnow().isoformat()}
    async with get_db_session() as db:
        n = await db.get(Notification, notification_id)
        if n is not None:
            n.deliveries = {**(n.deliveries or {}), **deliveries}
    return deliveries


async def notify(*, user_id: str | None, kind: str, subject: str, items: list[dict], dedupe_key: str) -> str | None:
    nid = await enqueue(user_id=user_id, kind=kind, subject=subject, items=items, dedupe_key=dedupe_key)
    if nid:
        await deliver(nid)
    return nid


async def admins() -> list[str]:
    async with get_db_session() as db:
        return list((await db.execute(
            select(User.id).where(User.is_active == True, User.role == "Registry Admin")  # noqa: E712
        )).scalars().all())


async def job_failed(job: str, label: str, status: str, error: str | None) -> None:
    """Tell every active Registry Admin that a job failed, once per job per day."""
    day = utcnow().date().isoformat()
    items = [{"type": "job_failed", "text": f"{label} ended with '{status}'" + (f": {error[:200]}" if error else "."),
              "link": "/pipelines"}]
    for uid in await admins():
        await notify(user_id=uid, kind="job_failed", subject=f"Agent Registry: {label} failed",
                     items=items, dedupe_key=f"job_failed:{job}:{uid}:{day}")
