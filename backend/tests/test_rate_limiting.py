"""Who a request is counted against, and the sliding window itself."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from api import rate_limiting as rl
from api.auth import create_access_token


def _request(headers: dict | None = None, client: tuple | None = ("10.0.0.9", 1234)) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/api/v1/agents/", "client": client,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


def test_window_allows_up_to_the_limit_then_refuses():
    limiter = rl.RateLimiter(max_requests=3, window_seconds=60)
    assert [limiter.is_allowed("k")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.is_allowed("k")
    assert allowed is False and retry_after >= 1


def test_each_key_has_its_own_allowance():
    limiter = rl.RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.is_allowed("a")[0] is True
    assert limiter.is_allowed("b")[0] is True
    assert limiter.is_allowed("a")[0] is False


def test_signed_in_people_are_counted_separately_even_behind_one_proxy():
    """The whole point: two users arriving from the same proxy IP must not
    share an allowance."""
    alice = _request({"authorization": f"Bearer {create_access_token('u-alice', 'admin')}"})
    bob = _request({"authorization": f"Bearer {create_access_token('u-bob', 'admin')}"})
    assert rl.rate_limit_key(alice) == "user:u-alice"
    assert rl.rate_limit_key(bob) == "user:u-bob"
    assert rl.rate_limit_key(alice) != rl.rate_limit_key(bob)


def test_anonymous_and_unreadable_tokens_fall_back_to_the_address():
    assert rl.rate_limit_key(_request()) == "ip:10.0.0.9"
    assert rl.rate_limit_key(_request({"authorization": "Bearer not-a-token"})) == "ip:10.0.0.9"


def test_forwarded_address_is_used_only_when_a_proxy_is_trusted(monkeypatch):
    forwarded = _request({"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
    assert rl.client_ip(forwarded) == "10.0.0.9", "a client could otherwise spoof the header"

    settings = rl.get_settings()
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    # The LAST hop, not the first: nginx only ever appends to X-Forwarded-For
    # ($proxy_add_x_forwarded_for), so the first entry is whatever the client
    # itself sent — trusting it let a caller pick its own rate-limit key.
    assert rl.client_ip(forwarded) == "10.0.0.1"


def test_a_spoofed_leading_hop_does_not_fool_the_limiter(monkeypatch):
    """The whole point of the fix above: two different attacker-chosen first
    hops in front of the SAME real proxy hop must resolve to the same key."""
    monkeypatch.setattr(rl.get_settings(), "trust_proxy_headers", True)
    attempt1 = _request({"x-forwarded-for": "1.1.1.1, 10.0.0.1"})
    attempt2 = _request({"x-forwarded-for": "9.9.9.9, 10.0.0.1"})
    assert rl.client_ip(attempt1) == rl.client_ip(attempt2) == "10.0.0.1"


def test_x_real_ip_is_preferred_over_x_forwarded_for(monkeypatch):
    """X-Real-IP is set by this repo's own nginx unconditionally
    (ui/nginx.conf), never appended to by a client, so it wins outright."""
    monkeypatch.setattr(rl.get_settings(), "trust_proxy_headers", True)
    request = _request({"x-real-ip": "10.0.0.1", "x-forwarded-for": "1.1.1.1, 10.0.0.1"})
    assert rl.client_ip(request) == "10.0.0.1"


def test_single_hop_forwarded_for_still_works(monkeypatch):
    monkeypatch.setattr(rl.get_settings(), "trust_proxy_headers", True)
    assert rl.client_ip(_request({"x-forwarded-for": "10.0.0.1"})) == "10.0.0.1"


def test_a_request_without_a_client_still_has_a_key():
    assert rl.rate_limit_key(_request(client=None)) == "ip:unknown"


@pytest.mark.parametrize("limit_attr,expected_min", [("api_rate_limit_per_minute", 60), ("login_attempts_per_5_min", 3)])
def test_limits_are_configurable(limit_attr, expected_min):
    assert getattr(rl.get_settings(), limit_attr) >= expected_min
