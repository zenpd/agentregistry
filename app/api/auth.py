"""Authentication and RBAC dependencies for Agent Registry."""
from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Header
from passlib.context import CryptContext

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
    payload = {
        "sub": user_id,
        "role": role,
        "iss": "airegistry",
        "aud": "airegistry-api",
        "exp": __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(days=7),
        "iat": __import__("datetime").datetime.utcnow(),
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


# RBAC permissions
ROLE_PERMISSIONS = {
    "Registry Admin": {"create": True, "read": True, "update": True, "delete": True, "admin": True},
    "Architect Steward": {"create": True, "read": True, "update": True, "delete": False, "admin": False},
    "Security Reviewer": {"create": False, "read": True, "update": True, "delete": False, "admin": False},
    "Product Owner": {"create": True, "read": True, "update": True, "delete": False, "admin": False},
    "Executive Viewer": {"create": False, "read": True, "update": False, "delete": False, "admin": False},
}


def has_permission(role: str, action: str) -> bool:
    return ROLE_PERMISSIONS.get(role, {}).get(action, False)


async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"user_id": payload["sub"], "role": payload["role"]}


def require_permission(action: str):
    async def permission_checker(user: dict = Depends(get_current_user)):
        role = user.get("role", "Executive Viewer")
        if not has_permission(role, action):
            raise HTTPException(status_code=403, detail=f"Role '{role}' does not have '{action}' permission")
        return user
    return permission_checker


require_create = require_permission("create")
require_read = require_permission("read")
require_update = require_permission("update")
require_delete = require_permission("delete")
require_admin = require_permission("admin")
