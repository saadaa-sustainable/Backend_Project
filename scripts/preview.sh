#!/usr/bin/env bash
# Preview the standalone tracker locally, against your working tree.
#
# WHY A SCRIPT
# Two servers are needed and neither is obvious. The page is a static
# file, so it needs something to serve it -- opening index.html with
# file:// fails, because the browser refuses a cross-origin fetch from
# a file: page. And the API must be told to allow the page's origin,
# or every request is refused by CORS and the dashboard renders its
# empty state rather than an error, which looks like missing data.
#
#   ./scripts/preview.sh            # ports 8100 (api) and 8101 (page)
#   ./scripts/preview.sh 9000 9001  # pick your own
#
# Ctrl-C stops both.
set -euo pipefail

API_PORT="${1:-8100}"
WEB_PORT="${2:-8101}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for p in "$API_PORT" "$WEB_PORT"; do
  if lsof -ti:"$p" >/dev/null 2>&1; then
    echo "Port $p is already in use. Pass different ports:" >&2
    echo "  ./scripts/preview.sh <api-port> <web-port>" >&2
    exit 1
  fi
done

# The API has to accept the page's origin explicitly. CORS here is an
# allow-list, not a wildcard, because /admin/* can trigger ingestion.
EXTRA_APP_ORIGINS="http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}" \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
  >/tmp/preview-api.log 2>&1 &
API_PID=$!

( cd tracker && python3 -m http.server "$WEB_PORT" --bind 127.0.0.1 >/dev/null 2>&1 ) &
WEB_PID=$!

cleanup() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

printf 'Starting API'
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${API_PORT}/health" 2>/dev/null; then
    ok=1; break
  fi
  printf '.'; sleep 1
done
echo
if [ "${ok:-0}" != 1 ]; then
  echo "API did not come up. Last lines of /tmp/preview-api.log:" >&2
  tail -20 /tmp/preview-api.log >&2
  exit 1
fi

cat <<EOF

  Preview ready — serving YOUR WORKING TREE, not what is deployed.

      http://127.0.0.1:${WEB_PORT}/index.html?api=http://127.0.0.1:${API_PORT}

  The ?api= is remembered in the browser, so later visits can drop it.
  Tabs: Hourly Tracker · Live P&L · Inventory
  API log: /tmp/preview-api.log

  Ctrl-C to stop both.

EOF

wait
