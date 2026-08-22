"""Centralized FastAPI exception handling.

Every :class:`AppError` subclass carries its own ``status_code`` and a
``to_dict()`` serializer, so a single handler here maps any application
error — Meta API failures, ingestion failures, repository failures,
configuration errors — to a consistent JSON error body instead of each
route needing its own try/except.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.logging.setup import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.error(
            "request_failed",
            path=str(request.url.path),
            error_type=type(exc).__name__,
            message=exc.message,
        )
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "request_failed_unexpected",
            path=str(request.url.path),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "message": "An unexpected error occurred."},
        )
