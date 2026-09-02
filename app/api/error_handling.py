"""Global error handling middleware and exception handlers."""
import traceback
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global error handler to prevent stack traces from leaking."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            raise
        except Exception as e:
            print(f"[ERROR] {request.method} {request.url.path}: {str(e)}")
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "type": "internal_error"}
            )


def add_error_handling(app):
    """Add error handling to the FastAPI app."""
    app.add_middleware(ErrorHandlerMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "type": "http_error"}
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        print(f"[ERROR] Unhandled exception: {str(exc)}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": "internal_error"}
        )
