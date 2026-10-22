"""Middleware for the analytics JSON endpoints."""

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send
from starlette.responses import JSONResponse


class AnalyticsGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Older Starlette versions buffer streamed responses when compressing.
        # Restrict compression to analytics so admin SSE keeps streaming.
        if scope["type"] == "http" and scope["path"].startswith("/admin/analytics/"):
            await super().__call__(scope, receive, send)
        else:
            await self.app(scope, receive, send)


class AssistantAPIBoundary:
    """Bound direct API bodies as well as browser requests; never cache auth/chat errors."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/admin/assistant/api/"):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 256_000:
                await JSONResponse({"detail": "Assistant request is too large."}, status_code=413,
                                   headers={"Cache-Control": "no-store"})(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        async def no_store(message):
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, replay, no_store)
