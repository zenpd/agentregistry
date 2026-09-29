"""Rate limiting middleware and dependency.

Requests are counted per signed-in user, falling back to the caller's IP for
anonymous ones (login). Counting by `request.client.host` alone is wrong
wherever the app sits behind a proxy — nginx or ACA ingress is then the peer
for everybody, so one busy person would use up the whole organisation's
allowance. The forwarded client IP is only trusted when
`trust_proxy_headers` says a proxy really is in front, because a direct
caller can otherwise set that header themselves.
"""
import time
from typing import Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config import get_settings


class RateLimiter:
    """Simple in-memory sliding window. Per process: with several workers or
    replicas each keeps its own count, so the effective limit is per worker."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, list] = {}

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, retry_after)."""
        now = time.time()
        window_start = now - self.window_seconds

        if key in self._requests:
            self._requests[key] = [t for t in self._requests[key] if t > window_start]
        else:
            self._requests[key] = []

        if len(self._requests[key]) >= self.max_requests:
            retry_after = int(self._requests[key][0] + self.window_seconds - now)
            return False, max(1, retry_after)

        self._requests[key].append(now)
        return True, 0


_settings = get_settings()
login_limiter = RateLimiter(max_requests=_settings.login_attempts_per_5_min, window_seconds=300)
api_limiter = RateLimiter(max_requests=_settings.api_rate_limit_per_minute, window_seconds=60)


def client_ip(request: Request) -> str:
    """The caller's address, from the trusted proxy's own view of it —
    never a hop a client could have written itself.

    X-Real-IP is what this repo's own reverse proxy sets (ui/nginx.conf:
    `proxy_set_header X-Real-IP $remote_addr`) and always overwrites, so a
    client can't forge it. X-Forwarded-For is a comma-joined chain a client
    CAN prepend to (nginx only ever appends via $proxy_add_x_forwarded_for),
    so trusting the first entry — the client's own claim — let a caller pick
    its own rate-limit key. The last entry is nginx's own append and is
    trustworthy for exactly one hop of proxying, matching this deployment."""
    if get_settings().trust_proxy_headers:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_key(request: Request) -> str:
    """Who the request is counted against: the signed-in user when there is
    one, so that people sharing a proxy do not share an allowance."""
    from api.auth import decode_token

    header = request.headers.get("authorization") or ""
    if header.startswith("Bearer "):
        payload = decode_token(header[7:])
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    return f"ip:{client_ip(request)}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to API endpoints."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        if request.url.path == "/api/v1/auth/login" and request.method == "POST":
            # Always by IP: a failed login has no user to attribute it to.
            allowed, retry_after = login_limiter.is_allowed(f"login:{client_ip(request)}")
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Too many login attempts. Try again in {retry_after} seconds."},
                    headers={"Retry-After": str(retry_after)}
                )

        allowed, retry_after = api_limiter.is_allowed(f"api:{rate_limit_key(request)}")
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)}
            )

        response = await call_next(request)
        return response
