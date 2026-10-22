"""Nested assistant deadlines, ordered so inner errors reach the browser.

SQL can use the warehouse's normal two-minute budget. Connection/cache wait and
model response time have separate headroom. Next.js waits 250s and the browser
260s for a chat turn; keep those longer than CHAT_TIMEOUT_SECONDS.
"""

SQL_TIMEOUT_MS = 120_000
TOOL_TIMEOUT_SECONDS = 130
MCP_TIMEOUT_SECONDS = 140
CHAT_TIMEOUT_SECONDS = 240
SESSION_LEASE_SECONDS = CHAT_TIMEOUT_SECONDS + 30
