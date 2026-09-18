"""FastAPI application entry point — Agent Registry.

Extends the bootstrap baseline with Agent Registry routers.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import example, health
from api.routers.registry import (
    agents_router, governance_router, discovery_router,
    tokenomics_router, graph_router, value_waste_router, admin_router, auth_router,
    phoenix_router
)
from api.error_handling import add_error_handling
from api.rate_limiting import RateLimitMiddleware
from observability.tracing import init_tracing, instrument_fastapi
from shared.config import get_settings
from shared.logger import get_logger, setup_logging

log = get_logger("api.main")
settings = get_settings()

APP_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_tracing()

    # Initialize database tables and seed data on startup
    try:
        from scripts.init_db import init_db
        await init_db()
        log.info("database.initialized")
    except Exception as e:
        log.error("database.init_failed", error=str(e))

    from orchestrations.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    log.info("api.startup", env=settings.app_env, version=APP_VERSION)
    yield
    await stop_scheduler()
    log.info("api.shutdown")


app = FastAPI(
    title="Agent Registry API",
    description="Enterprise AI Control Tower — Agent Registry",
    version=APP_VERSION,
    lifespan=lifespan,
)
instrument_fastapi(app)

# CORS configuration
if settings.app_env == "development":
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]
else:
    _cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if not _cors_origins:
        raise RuntimeError(f"CORS_ALLOWED_ORIGINS must be set in app_env={settings.app_env!r}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# Add rate limiting
app.add_middleware(RateLimitMiddleware)

# Add global error handling
add_error_handling(app)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(example.router, prefix="/api/v1/example", tags=["Example"])
app.include_router(auth_router)
from api.routers.ops import ROUTERS as OPS_ROUTERS
for _ops_router in OPS_ROUTERS:
    app.include_router(_ops_router)
app.include_router(agents_router)
app.include_router(governance_router)
app.include_router(discovery_router)
app.include_router(tokenomics_router)
app.include_router(graph_router)
app.include_router(value_waste_router)
app.include_router(admin_router)
app.include_router(phoenix_router)
# Orchestration and WebSocket routers
from api.routers.orchestrations import router as orchestrations_router
from api.websocket_events import router as websocket_router
app.include_router(orchestrations_router, prefix="/api/v1")
app.include_router(websocket_router)
