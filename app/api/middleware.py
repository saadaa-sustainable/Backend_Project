"""Middleware for the analytics JSON endpoints."""

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send


class AnalyticsGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Older Starlette versions buffer streamed responses when compressing.
        # Restrict compression to analytics so admin SSE keeps streaming.
        if scope["type"] == "http" and scope["path"].startswith("/admin/analytics/"):
            await super().__call__(scope, receive, send)
        else:
            await self.app(scope, receive, send)
