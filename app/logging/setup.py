"""Structured logging setup built on top of ``structlog``.

Every log line is emitted as a structured event (JSON in production,
human-readable console output in development) and automatically carries a
``request_id`` / ``batch_id`` when bound via :func:`bind_context`. This gives
us request tracing across the API layer, the Meta client, and the ingestion
services without threading a logger object through every call.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure stdlib logging + structlog. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        # stdlib.LoggerFactory (not PrintLoggerFactory) -- add_logger_name
        # above needs a stdlib logging.Logger's .name attribute, which
        # PrintLogger doesn't have; this codebase's shared_processors and
        # get_logger()'s return type both assume stdlib integration.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name`` (defaults to caller module)."""
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind key/value pairs (e.g. ``request_id``, ``batch_id``) to all
    subsequent log calls on this async context / thread."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear any context previously bound with :func:`bind_context`."""
    structlog.contextvars.clear_contextvars()
