"""Auth helpers — EntraID (Azure AD) JWT validation, optional.

By default endpoints are open (accelerator/demo posture). To protect a route,
add ``user=Depends(require_user)`` and set ENTRA_* settings. Replace the stub
verification with real JWKS validation (msal / python-jose) for production.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.config import get_settings

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Validate the bearer token and return claims. Stubbed by default."""
    if settings.app_env == "development" and not settings.entra_audience:
        return {"sub": "dev-user", "roles": ["admin"]}

    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    # TODO: validate creds.credentials against Entra JWKS (audience/issuer/exp).
    # For now, presence of a token is accepted outside development.
    return {"sub": "token-user", "roles": ["user"]}
