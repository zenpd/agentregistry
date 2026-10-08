"""The Phoenix connection test names the failing step."""
from __future__ import annotations

import pytest

from discovery import connection
from discovery.phoenix_client import PhoenixClient, PhoenixError


@pytest.fixture
def phoenix(monkeypatch):
    state = {"addresses": ["10.0.0.5"], "error": None, "projects": [{"name": "retail-onboarding", "id": "1"}]}
    monkeypatch.setattr(connection, "_host_addresses", lambda host: state["addresses"])

    async def all_projects(self, max_pages=20):
        if state["error"]:
            raise state["error"]
        return state["projects"]

    monkeypatch.setattr(PhoenixClient, "all_projects", all_projects)
    return state


@pytest.mark.asyncio
async def test_each_failure_has_its_own_state(phoenix):
    url = "https://phoenix.internal"
    assert (await connection.test_connection(None, None))["state"] == "not_configured"
    assert (await connection.test_connection("ftp://x", None))["state"] == "blocked_address"
    phoenix["addresses"] = ["169.254.169.254"]
    assert (await connection.test_connection(url, None))["state"] == "blocked_address"
    phoenix["addresses"] = ["10.0.0.5"]
    phoenix["error"] = PhoenixError("GET", url, 401, "nope")
    assert (await connection.test_connection(url, "bad"))["state"] == "unauthorized"
    phoenix["error"] = PhoenixError("GET", url, 0, "The answer was not JSON")
    assert (await connection.test_connection(url, None))["state"] == "not_phoenix"
    phoenix["error"] = PhoenixError("GET", url, 0, "connect timeout")
    assert (await connection.test_connection(url, None))["state"] == "unreachable"
    phoenix["error"] = None
    assert (await connection.test_connection(url, None, "missing"))["state"] == "project_not_found"
    ok = await connection.test_connection(url, None, "retail-onboarding")
    assert ok["state"] == "connected" and ok["projectCount"] == 1
