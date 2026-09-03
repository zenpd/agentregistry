"""Authentication and RBAC dependencies for Agent Registry."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Header
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db
from db.models import User

# bcrypt password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _get_secret_key() -> str:
    """Get JWT secret key from environment."""
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
    return key


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


# RBAC permissions — DEFAULT ADMIN MODE: all permissions granted to all authenticated users
# Role-based personas can be re-enabled by flipping USE_Rbac below.
USE_Rbac = False

if USE_Rbac:
    ROLE_PERMISSIONS = {
        "Registry Admin": {"create": True, "read": True, "update": True, "delete": True, "admin": True},
        "Architect Steward": {"create": True, "read": True, "update": True, "delete": False, "admin": False},
        "Security Reviewer": {"create": False, "read": True, "update": True, "delete": False, "admin": False},
        "Product Owner": {"create": True, "read": True, "update": True, "delete": False, "admin": False},
        "Executive Viewer": {"create": False, "read": True, "update": False, "delete": False, "admin": False},
    }
else:
    ROLE_PERMISSIONS = {
        "admin": {"create": True, "read": True, "update": True, "delete": True, "admin": True},
        "user": {"create": True, "read": True, "update": True, "delete": True, "admin": True},
    }


def has_permission(role: str, action: str) -> bool:
    return ROLE_PERMISSIONS.get(role, {}).get(action, False)


async def get_current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Default: accept any valid token, return admin role.

    When USE_Rbac is True, the role from the token is used for permission checks.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User account not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Default admin mode: always return admin role
    return {"user_id": payload["sub"], "role": "admin"}


def require_permission(action: str):
    async def permission_checker(user: dict = Depends(get_current_user)):
        if USE_Rbac:
            role = user.get("role", "admin")
            if not has_permission(role, action):
                raise HTTPException(status_code=403, detail=f"Role '{role}' does not have '{action}' permission")
        return user
    return permission_checker


require_create = require_permission("create")
require_read = require_permission("read")
require_update = require_permission("update")
require_delete = require_permission("delete")
require_admin = require_permission("admin")
