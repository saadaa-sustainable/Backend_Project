#!/usr/bin/env bash
# Google Ads spend + GA4 ARPU, then the tracker rows that read them.
#
# LOCAL ONLY, and that is the point. Both pulls authenticate with the
# OAuth tokens in secrets/, which exist on this machine and nowhere
# else -- there is no CI secret to add and none should be added. So
# this runs here, under whatever scheduler this machine offers, and
# the nightly on GitHub does not attempt it.
#
# GRPC_DNS_RESOLVER=native: gRPC ships its own c-ares resolver and it
# fails on this network with "could not contact DNS servers". The
# native resolver is the system one and works.
#
# Order matters. The two fetches write their own tables; the ingest
# reads those tables and spreads the daily totals across the hours, so
# running it first would spread yesterday's figures.
#
# Usage:  scripts/refresh_google_arpu.sh [days]      (default 2)
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
DAYS="${1:-2}"
PY=.venv/bin/python
export GRPC_DNS_RESOLVER=native

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
step() { printf '\n[%s] %s\n' "$(ts)" "$1"; }

rc=0
step "Google Ads spend (12 days)"
"$PY" scripts/fetch_google_ads_api.py --days 12 || rc=1

step "GA4 ARPU (12 days)"
"$PY" scripts/fetch_ga4_arpu.py --days 12 || rc=1

# Attempted even if a fetch failed: the other one's figures still need
# spreading across the hours, and a half-refresh beats none.
step "Hourly tracker (${DAYS} day(s))"
"$PY" scripts/fetch_hourly_tracker.py --days "$DAYS" || rc=1

step "done (exit ${rc})"
exit "$rc"
