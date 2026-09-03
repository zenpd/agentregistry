"""Audit logging service."""
from typing import Optional
from db.base import get_db_session
from db.models import AuditLog


async def log_audit_event(
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str = "",
    changes: dict = None,
    org_id: str = "org-default"
):
    """Log an audit event to the audit_log table."""
    try:
        async with get_db_session() as db:
            db.add(AuditLog(
                org_id=org_id,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id or None,
                changes=changes,
            ))
    except Exception as e:
        # Audit logging should never break the main operation
        print(f"[AUDIT ERROR] Failed to log event: {e}")
