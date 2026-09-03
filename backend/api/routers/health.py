"""Liveness / readiness probe. Consumed by ACA + Docker HEALTHCHECK + nginx."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@router.get("/api/v1/health")
async def health_api():
    """Alias under /api/v1 so the frontend's relative api.get('/health') works."""
    return {"status": "ok", "version": "1.0.0"}
