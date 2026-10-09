"""The connector contract: test the connection, and list what may be an agent.
Each adapter is small: it reads one kind of system and returns Findings.
Nothing here writes to the outside system."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class Finding:
    kind: str                    # trace_project | code_repo | cloud_deployment | cloud_agent
    external_id: str
    name: str
    url: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ConnectorError(Exception):
    """A connector could not do its work; the message says why, in plain words."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status     # unauthorized | unreachable | not_configured | failed
        self.message = message


class Connector(Protocol):
    kind: str

    async def test(self) -> dict: ...
    async def sync(self) -> list[Finding]: ...


# ── Secrets at rest ──────────────────────────────────────────────────────────
# Encrypted with a key derived from the sign-in signing key. Rotating that key
# makes stored connector secrets unreadable: they then have to be entered again.

def _fernet() -> Fernet:
    from api.auth import _get_secret_key

    digest = hashlib.sha256(("connector-secrets:" + (_get_secret_key() or "dev")).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(secret: dict | None) -> str | None:
    if not secret:
        return None
    return _fernet().encrypt(json.dumps(secret).encode()).decode()


def unseal(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        raise ConnectorError("not_configured", "The stored secret cannot be read (the signing key changed). Enter it again.")


def secret_fields(secret: dict | None) -> list[str]:
    """Which secret fields are set, never their values."""
    return sorted(k for k, v in (secret or {}).items() if v)
