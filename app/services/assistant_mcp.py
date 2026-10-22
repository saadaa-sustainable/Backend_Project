"""Standard Streamable HTTP MCP, limited to the existing read-only analytics tools."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import HTTPException
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services import assistant_api_auth as auth
from app.services.assistant_analytics import (
    ANALYTICS_SYSTEM_PROMPT, ANALYTICS_TOOLS, execute_analytics_tool,
)


class AnalyticsMCP:
    def __init__(self):
        self.server = Server("saadaa-analytics", version="1.0.0", instructions=ANALYTICS_SYSTEM_PROMPT)
        self.limits = auth.Limits()
        self.manager = StreamableHTTPSessionManager(
            self.server, json_response=True, stateless=True, max_request_body_size=64_000,
            # Host/Origin validation below follows the configured deployment, including ASGI calls.
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

        @self.server.list_tools()
        async def list_tools():
            return [types.Tool(name=t["function"]["name"], description=t["function"]["description"],
                               inputSchema=t["function"]["parameters"],
                               annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                                                 idempotentHint=True, openWorldHint=False))
                    for t in ANALYTICS_TOOLS]

        # Pydantic performs input validation centrally, with bounded/sanitized error messages.
        @self.server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict):
            try:
                principal = auth.mcp_identity(self.server.request_context.request)
                with self.limits.admit(principal["key_id"], per_minute=30, concurrent=2):
                    content, failed = await execute_analytics_tool(name, arguments, read_only=True)
                    auth.revalidate(principal)
                structured = json.loads(content) if not failed else None
                if len(content) > 1_000_000:
                    raise HTTPException(413, "Result is too large. Use a smaller date range or limit.")
                return types.CallToolResult(content=[types.TextContent(type="text", text=content)],
                                            structuredContent=structured, isError=failed)
            except HTTPException as exc:
                return self.failure(exc.status_code, str(exc.detail))
            except Exception:
                return self.failure(503, "Could not read analytics. Stopped without retrying.")

    @staticmethod
    def failure(status: int, message: str):
        body = {"error": message, "status": status}
        return types.CallToolResult(isError=True, structuredContent=body,
                                    content=[types.TextContent(type="text", text=json.dumps(body))])

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        try:
            config = auth.settings()
            config.require_configured()
            if request.headers.get("host", "").lower() != urlsplit(config.mcp_url).netloc.lower():
                raise HTTPException(421, "Invalid MCP host.")
            origin = request.headers.get("origin")
            if origin is not None and origin != config.public_origin:
                raise HTTPException(403, "Invalid MCP origin.")
            auth.mcp_identity(request)
            # This stateless server has no unsolicited events or sessions to delete.
            if request.method != "POST":
                await Response(status_code=405, headers={"Allow": "POST", "Cache-Control": "no-store"})(scope, receive, send)
                return
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                               headers={"Cache-Control": "no-store", **(exc.headers or {})})(scope, receive, send)
            return

        async def no_store(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"cache-control", b"no-store")]
            await send(message)

        await self.manager.handle_request(scope, receive, no_store)
