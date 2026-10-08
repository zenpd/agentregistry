"""Authentication and RBAC dependencies for Agent Registry."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Header, Request
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db
from db.models import AuditLog, User

# bcrypt password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


WEAK_KEYS = {"", "change-me", "changeme", "secret", "dev"}


def _get_secret_key() -> str:
    """The one key that signs sign-in tokens: AIREGISTRY_SECRET_KEY, else
    APP_SECRET_KEY from settings. check_signing_key() refuses a weak one
    outside development."""
    key = os.environ.get("AIREGISTRY_SECRET_KEY", "")
    if not key:
        # Fallback: try to load from .env file manually
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("AIREGISTRY_SECRET_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not key:
        from shared.config import get_settings
        key = get_settings().app_secret_key or ""
    return key


def check_signing_key() -> None:
    """Called at start-up. Outside development a weak or short signing key would
    let anyone who knows it forge sign-ins, so the app refuses to start."""
    from shared.config import get_settings

    if get_settings().app_env == "development":
        return
    key = _get_secret_key()
    if key.lower() in WEAK_KEYS or key.startswith("change-me") or len(key) < 32:
        raise RuntimeError("Set AIREGISTRY_SECRET_KEY to a random value of at least 32 characters before starting outside development.")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(user_id: str, role: str) -> str:
    secret_key = _get_secret_key()
    if not secret_key:
        raise RuntimeError("AIREGISTRY_SECRET_KEY environment variable is required")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iss": "airegistry",
        "aud": "airegistry-api",
        "exp": now + timedelta(days=7),
        "iat": now,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    secret_key = _get_secret_key()
    if not secret_key:
        return None
    try:
        return jwt.decode(
            token,
            secret_key,
            algorithms=["HS256"],
            issuer="airegistry",
            audience="airegistry-api",
            options={"require": ["exp", "iss", "aud"]}
        )
    except Exception:
        return None


# ── Roles ────────────────────────────────────────────────────────────────────
# Each role says what it may do and which governance gates its holder decides.
# "audit" opens the audit trail. Role checks are on unless RBAC_ENABLED=false
# (a single-person test setup).
ROLES: dict[str, dict] = {
    "Registry Admin": {"perms": {"create", "read", "update", "delete", "admin", "audit", "attest"}, "gates": {"arb", "security", "dp"}},
    "Architect Steward": {"perms": {"create", "read", "update"}, "gates": {"arb"}},
    "Security Reviewer": {"perms": {"read", "update"}, "gates": {"security"}},
    "Data Protection Officer": {"perms": {"read", "update"}, "gates": {"dp"}},
    "Product Owner": {"perms": {"create", "read", "update"}, "gates": set()},
    "Executive Viewer": {"perms": {"read"}, "gates": set()},
    "Auditor": {"perms": {"read", "audit"}, "gates": set()},
    # Confirms or adjusts the value owners declare ("attest").
    "Finance Reviewer": {"perms": {"read", "attest"}, "gates": set()},
}
# Older role names still found in tokens, tests and early data.
ROLE_ALIASES = {"admin": "Registry Admin", "user": "Product Owner", "viewer": "Executive Viewer"}
# What each gate's decision needs, for messages.
GATE_ROLE = {"arb": "Architect Steward", "security": "Security Reviewer", "dp": "Data Protection Officer"}


def _rbac_from_settings() -> bool:
    try:
        from shared.config import get_settings
        return bool(get_settings().rbac_enabled)
    except Exception:
        return True


# Module attribute so tests can switch it; read through rbac_on().
USE_Rbac = _rbac_from_settings()


def rbac_on() -> bool:
    import api.auth as _self
    return bool(_self.USE_Rbac)


def role_spec(role: str) -> dict:
    return ROLES.get(ROLE_ALIASES.get(role, role), {"perms": set(), "gates": set()})


def has_permission(role: str, action: str) -> bool:
    if not rbac_on():
        return True
    return action in role_spec(role)["perms"]


def can_decide_gate(role: str, gate: str) -> bool:
    if not rbac_on():
        return True
    return gate in role_spec(role)["gates"]


def permissions_of(role: str) -> dict:
    """What the UI needs to show only the actions this person can take."""
    spec = role_spec(role) if rbac_on() else ROLES["Registry Admin"]
    return {"perms": sorted(spec["perms"]), "gates": sorted(spec["gates"]), "rbac": rbac_on()}


API_KEY_PREFIX = "ark_"
# What each API key scope allows, in the terms of the role permissions.
SCOPE_PERMS = {"read": {"read"}, "register": {"read", "create", "update"}, "certify_check": {"read"}}


def hash_api_key(key: str) -> str:
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()


async def _api_key_user(db: AsyncSession, token: str) -> dict:
    from datetime import datetime as _dt, timezone as _tz
    from db.models import ApiKey

    row = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))).scalar_one_or_none()
    now = _dt.now(_tz.utc)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Unknown or revoked API key")
    expires = row.expires_at.replace(tzinfo=_tz.utc) if row.expires_at and row.expires_at.tzinfo is None else row.expires_at
    if expires and expires < now:
        raise HTTPException(status_code=401, detail="This API key has expired")
    last = row.last_used_at.replace(tzinfo=_tz.utc) if row.last_used_at and row.last_used_at.tzinfo is None else row.last_used_at
    if last is None or (now - last).total_seconds() > 60:
        row.last_used_at = now
    return {"user_id": f"key:{row.id}", "role": "api", "scopes": list(row.scopes or []), "keyLabel": row.label}


async def get_current_user(
    request: Request,
    authorization: str = Header(None),
):
    """The signed-in person and their role as stored now (a role change applies
    at once, without a new token), or an API key with its scopes. An Auditor
    signs in only until their end date, and every request they make is logged.

    The lookup uses a short session of its own, closed before the endpoint runs:
    a session held for the whole request would keep a pooled connection busy
    while a slow endpoint (an AI insight run) waits, and run the pool dry."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.replace("Bearer ", "")
    from db.base import get_db_session

    async with get_db_session() as db:
        if token.startswith(API_KEY_PREFIX):
            return await _api_key_user(db, token)
        payload = decode_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        result = await db.execute(select(User).where(User.id == payload["sub"]))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User account not found")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")
        if ROLE_ALIASES.get(user.role, user.role) == "Auditor":
            from datetime import date as _date
            if user.access_until is None:
                raise HTTPException(status_code=403, detail="An auditor account needs an end date. Ask a Registry Admin to set it.")
            if _date.today() > user.access_until:
                raise HTTPException(status_code=403, detail=f"Your auditor access ended on {user.access_until.isoformat()}.")
            db.add(AuditLog(org_id="org-default", actor=user.id, action="auditor.access", entity_type="request",
                            entity_id=request.url.path[:64], changes={"method": request.method, "path": request.url.path,
                                                                       "query": str(request.url.query)[:200] or None}))
        return {"user_id": user.id, "role": user.role}


_ACTION_WORDS = {
    "create": "register agents", "read": "view the registry", "update": "change records",
    "delete": "delete agents", "admin": "change settings or users", "audit": "open the audit trail",
}


def require_permission(action: str):
    async def permission_checker(user: dict = Depends(get_current_user)):
        role = user.get("role", "")
        if role == "api":
            allowed = set().union(*(SCOPE_PERMS.get(s, set()) for s in user.get("scopes") or []))
            if action not in allowed:
                raise HTTPException(status_code=403, detail=f"This API key ({', '.join(user.get('scopes') or []) or 'no scopes'}) "
                                                            f"cannot {_ACTION_WORDS.get(action, action)}.")
            return user
        if not has_permission(role, action):
            raise HTTPException(status_code=403,
                                detail=f"Your role, {ROLE_ALIASES.get(role, role)}, cannot {_ACTION_WORDS.get(action, action)}.")
        return user
    return permission_checker


require_create = require_permission("create")
require_read = require_permission("read")
require_update = require_permission("update")
require_delete = require_permission("delete")
require_admin = require_permission("admin")
require_audit = require_permission("audit")
require_attest = require_permission("attest")


async def user_display_name(user: dict) -> str:
    """The signed-in person's name as it is recorded on decisions (falls back to
    the email, then the id). Decisions record who made them, never typed names."""
    from db.base import get_db_session

    async with get_db_session() as db:
        row = await db.get(User, user.get("user_id"))
    if row is None:
        return str(user.get("user_id") or "unknown")
    return row.name or row.email
