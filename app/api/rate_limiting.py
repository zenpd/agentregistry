"""Rate limiting middleware and dependency."""
import time
from typing import Dict, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

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


login_limiter = RateLimiter(max_requests=5, window_seconds=300)
api_limiter = RateLimiter(max_requests=100, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to API endpoints."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        if request.url.path == "/api/v1/auth/login" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = login_limiter.is_allowed(f"login:{client_ip}")
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Too many login attempts. Try again in {retry_after} seconds."},
                    headers={"Retry-After": str(retry_after)}
                )

        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after = api_limiter.is_allowed(f"api:{client_ip}")
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)}
            )

        response = await call_next(request)
        return response
