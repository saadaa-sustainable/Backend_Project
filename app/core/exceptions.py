"""Centralized exception hierarchy.

Every error the service can raise inherits from :class:`AppError` so a single
FastAPI exception handler (see ``app/api/error_handlers.py``) can map any
failure to a consistent JSON error response, and so retry logic in the Meta
client can cleanly distinguish transient vs. permanent failures by type
rather than by inspecting strings.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all application-raised errors."""

    #: default HTTP status used by the FastAPI exception handler
    status_code: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.__class__.__name__, "message": self.message, **self.details}


# --------------------------------------------------------------------------
# Meta Graph API errors
# --------------------------------------------------------------------------


class MetaAPIError(AppError):
    """Base class for any error returned by / while calling the Meta Graph API."""

    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        status_code_from_meta: int | None = None,
        meta_error_code: int | None = None,
        meta_error_subcode: int | None = None,
        fbtrace_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.status_code_from_meta = status_code_from_meta
        self.meta_error_code = meta_error_code
        self.meta_error_subcode = meta_error_subcode
        self.fbtrace_id = fbtrace_id


class MetaAuthenticationError(MetaAPIError):
    """Access token missing, invalid, expired, or lacking required scopes."""

    status_code = 401


class MetaPermissionError(MetaAPIError):
    """Token is valid but lacks permission for the requested object/edge."""

    status_code = 403


class MetaRateLimitError(MetaAPIError):
    """Meta responded with a rate-limit / throttling error (retryable)."""

    status_code = 429

    def __init__(self, message: str, *, retry_after_seconds: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds


class MetaTransientError(MetaAPIError):
    """Server-side / network failure that is safe to retry (5xx, timeouts)."""

    status_code = 502


class MetaPermanentError(MetaAPIError):
    """Client-side error that will never succeed on retry (400, bad params)."""

    status_code = 400


class MetaPaginationError(MetaAPIError):
    """Pagination cursor was invalid or expired mid-fetch."""

    status_code = 502


# --------------------------------------------------------------------------
# Ingestion / persistence errors
# --------------------------------------------------------------------------


class IngestionError(AppError):
    """A sync/ingestion service failed to complete a batch."""

    status_code = 500


class RepositoryError(AppError):
    """A database persistence operation failed."""

    status_code = 500


class ConfigurationError(AppError):
    """Required configuration (credentials, settings) is missing or invalid."""

    status_code = 500


class UnknownEndpointError(AppError):
    """A requested endpoint/registry key does not exist."""

    status_code = 404
