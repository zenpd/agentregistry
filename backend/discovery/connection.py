"""Test a Phoenix connection step by step and name what is wrong, so Settings
can say "the key is refused" instead of a bare "unreachable".

States: connected, not_configured, blocked_address, unreachable, not_phoenix,
unauthorized, project_not_found."""
from __future__ import annotations

import asyncio
import socket
from urllib.parse import urlparse

from discovery.phoenix_client import PhoenixClient, PhoenixError
from governance.reuse import TryItBlocked, check_addresses

MESSAGES = {
    "connected": "Connected.",
    "not_configured": "No Phoenix address is set. Enter it in Settings.",
    "blocked_address": "This address is not allowed (a cloud platform, link-local or reserved address).",
    "unreachable": "Phoenix did not answer. Check the address and the network (Phoenix is reached over the VPN).",
    "not_phoenix": "Something answered, but it is not Phoenix (for example a login page in front of it).",
    "unauthorized": "Phoenix refused the key. Check the API key in Settings.",
    "project_not_found": "Phoenix answered, but has no project with that name.",
}


def _host_addresses(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


async def test_connection(base_url: str | None, api_key: str | None, project: str | None = None,
                          allow_loopback: bool = True) -> dict:
    if not base_url:
        return {"state": "not_configured", "message": MESSAGES["not_configured"]}
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"state": "blocked_address", "message": "The address must start with http:// or https://."}
    try:
        addresses = await asyncio.to_thread(_host_addresses, parsed.hostname)
        check_addresses(addresses, allow_loopback=allow_loopback)
    except TryItBlocked as exc:
        return {"state": "blocked_address", "message": f"{MESSAGES['blocked_address']} {exc}"}
    except OSError:
        return {"state": "unreachable", "message": "The host name is not known to this server's DNS. " + MESSAGES["unreachable"]}

    version = None
    async with PhoenixClient(base_url, api_key=api_key, timeout=20) as client:
        try:
            raw = await client._client.get("/arize_phoenix_version")
            version = raw.text.strip()[:40] if raw.status_code == 200 else None
        except Exception:
            version = None
        try:
            projects = [p["name"] for p in await client.all_projects(max_pages=5)]
        except PhoenixError as exc:
            if exc.status in (401, 403):
                return {"state": "unauthorized", "message": MESSAGES["unauthorized"], "version": version}
            if exc.status == 0 and "not JSON" in str(exc):
                return {"state": "not_phoenix", "message": MESSAGES["not_phoenix"]}
            if exc.status == 0:
                return {"state": "unreachable", "message": MESSAGES["unreachable"]}
            return {"state": "not_phoenix", "message": f"{MESSAGES['not_phoenix']} (HTTP {exc.status})"}
    if project and project not in projects:
        return {"state": "project_not_found", "message": f"{MESSAGES['project_not_found']} ({project})",
                "version": version, "projectCount": len(projects)}
    return {"state": "connected", "message": MESSAGES["connected"], "version": version, "projectCount": len(projects)}
