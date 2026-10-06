"""Fetch GA4 landing-page x channel daily rows into public.ga4_daily_landing.

WHY THIS GRAIN
--------------
One row per (day, landing page, default channel group). That is the
coarsest grain that still answers the three questions this dashboard
already asks elsewhere:

  * Landing Page Analysis has Meta spend and Shopify orders per landing
    page but no traffic figure, so a page that converts badly cannot be
    told apart from a page nobody reached.
  * Channel group is the only honest way to see non-Meta demand next to
    Meta spend. Organic and Direct sessions never appear in any Meta or
    Shopify table.
  * Keeping both on one row means the two can be cross-cut (paid traffic
    to a specific product page) without a second fetch.

WHAT THESE NUMBERS ARE NOT
--------------------------
GA4 sessions are NOT comparable to Meta clicks and NOT a source of
truth for orders. GA4 attributes on its own last-non-direct model,
Shopify records the order, and Meta claims a view-through window. The
three disagree by design. This table exists to show demand and
behaviour, not to arbitrate attribution -- `shopify_order_attribution`
does that.

`sessions` is also not additive with the de-duplicated `total_users`
below it: summing users across days counts a person once per day, the
same trap Meta reach has. Sum sessions; never sum users.

SAMPLING AND THRESHOLDS
-----------------------
The Data API applies (a) sampling on large properties and (b) a privacy
threshold that silently drops rows when the user count is too low to
anonymise. Both are recorded per request: `sampled` and `thresholded`
land on every row so a reader can tell a real zero from a suppressed
one. A day with `thresholded` set does NOT sum to the property total.

TIMEZONE
--------
GA4 reports in the PROPERTY's own timezone, exactly as Meta reports in
the ad account's. The property timezone is read from the Admin API at
run time and stored on every row rather than assumed, because a silent
mismatch between this and the Asia/Kolkata days every other table uses
would shift traffic by a few hours into the wrong day and nobody would
see it. The script refuses to run if the property is not on the same
timezone as the rest of the warehouse unless --allow-tz-mismatch.

AUTH
----
Application Default Credentials with the `analytics.readonly` scope:

    gcloud auth application-default login --scopes=openid,\\
      https://www.googleapis.com/auth/userinfo.email,\\
      https://www.googleapis.com/auth/cloud-platform,\\
      https://www.googleapis.com/auth/sqlservice.login,\\
      https://www.googleapis.com/auth/analytics.readonly

--scopes REPLACES the scope set, so cloud-platform has to be repeated or
the BigQuery scripts lose their credentials. This uses the signed-in
person's own GA access, so it needs no GA admin rights -- unlike a
service account, which has to be added to the property by an admin.

Usage:
    # what can this account see?
    ./.venv/bin/python scripts/fetch_ga4_daily.py --list-properties

    # first backfill (long -- run it in the background)
    ./.venv/bin/python scripts/fetch_ga4_daily.py --from 2026-01-01

    # nightly: re-pull a trailing window, since GA4 keeps revising
    ./.venv/bin/python scripts/fetch_ga4_daily.py --days 7
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Explicit path: load_dotenv() walks up from the *script's* directory,
# which is scripts/, and silently finds nothing here.
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

#: The warehouse's calendar. Every other analytics table is built on IST
#: days; a GA4 property on a different timezone would put traffic in a
#: different day from the spend it caused.
WAREHOUSE_TZ = "Asia/Kolkata"


def _same_clock(a: str, b: str) -> bool:
    """Whether two zone names describe the same wall clock.

    String equality is the wrong test. GA4 reports this property's zone
    as "Asia/Calcutta", the pre-1993 IANA name that is still a live
    alias for "Asia/Kolkata" -- identical offset, identical history,
    different spelling. Comparing the strings refuses a property that is
    in fact correctly configured, and the obvious workaround
    (--allow-tz-mismatch) would switch off the check that catches a
    genuine mismatch too.

    Offsets are sampled across the year rather than taken once, so two
    zones that agree today but diverge over DST are not called equal.
    India has no DST, but the warehouse constant is not guaranteed to
    stay Asia/Kolkata forever.
    """
    try:
        from zoneinfo import ZoneInfo
        za, zb = ZoneInfo(a), ZoneInfo(b)
    except Exception:  # noqa: BLE001
        return a == b
    return all(
        datetime(2026, m, 15, 12).replace(tzinfo=za).utcoffset()
        == datetime(2026, m, 15, 12).replace(tzinfo=zb).utcoffset()
        for m in (1, 4, 7, 10)
    )

#: Matches the data floor the whole dashboard is bounded to -- the blue
#: banner on the Analytics page says "All figures start 01 Jan 2026".
DEFAULT_FROM = date(2026, 1, 1)

#: The Data API caps a single request at 100k rows and charges tokens per
#: request, so the fetch pages rather than asking for everything. One
#: month per request keeps each response well inside the cap even on a
#: property with thousands of landing pages.
MONTHS_PER_REQUEST = 1
API_PAGE_SIZE = 100_000

#: The Supabase pooler drops a single oversized statement, and a month of
#: landing-page rows is easily tens of thousands. Each chunk is its own
#: transaction so a dropped connection costs one chunk, not the run.
WRITE_CHUNK = 1_000

DDL = """
CREATE TABLE IF NOT EXISTS public.ga4_daily_landing (
    property_id    text        NOT NULL,
    day            date        NOT NULL,
    landing_page   text        NOT NULL,
    channel_group  text        NOT NULL,
    sessions                bigint,
    total_users             bigint,
    pdp_views               bigint,
    add_to_carts            bigint,
    checkouts               bigint,
    purchases               bigint,
    revenue                 numeric,
    bounce_rate             numeric,
    key_event_rate          numeric,
    engaged_sessions        bigint,
    property_timezone       text,
    sampled                 boolean DEFAULT false,
    thresholded             boolean DEFAULT false,
    fetched_at              timestamptz DEFAULT NOW(),
    PRIMARY KEY (property_id, day, landing_page, channel_group)
);
CREATE INDEX IF NOT EXISTS ix_ga4_landing_day     ON public.ga4_daily_landing(day);
CREATE INDEX IF NOT EXISTS ix_ga4_landing_page    ON public.ga4_daily_landing(landing_page);
CREATE INDEX IF NOT EXISTS ix_ga4_landing_channel ON public.ga4_daily_landing(channel_group);
"""

UPSERT = """
INSERT INTO public.ga4_daily_landing
    (property_id, day, landing_page, channel_group,
     sessions, total_users, pdp_views, add_to_carts, checkouts, purchases, revenue, bounce_rate, key_event_rate, engaged_sessions, property_timezone, sampled, thresholded, fetched_at)
VALUES %s
ON CONFLICT (property_id, day, landing_page, channel_group) DO UPDATE SET
    sessions           = EXCLUDED.sessions,
    total_users        = EXCLUDED.total_users,
    pdp_views          = EXCLUDED.pdp_views,
    add_to_carts       = EXCLUDED.add_to_carts,
    checkouts          = EXCLUDED.checkouts,
    purchases          = EXCLUDED.purchases,
    revenue            = EXCLUDED.revenue,
    bounce_rate        = EXCLUDED.bounce_rate,
    key_event_rate     = EXCLUDED.key_event_rate,
    engaged_sessions   = EXCLUDED.engaged_sessions,
    property_timezone  = EXCLUDED.property_timezone,
    sampled            = EXCLUDED.sampled,
    thresholded        = EXCLUDED.thresholded,
    fetched_at         = EXCLUDED.fetched_at
"""

#: Order matters: the response returns dimension and metric values as
#: positional arrays, so these lists ARE the parsing contract.
#: `landingPage`, NOT `landingPagePlusQueryString`.
#:
#: The query-string form splits one page into a separate row per URL
#: variant -- 312,658 distinct values in a single week on this property,
#: because nearly every session arrives with ?utm_source=META&... An
#: exact match on the bare path then captures only 1.6% of sessions.
#: `landingPage` is the same dimension with the query string stripped,
#: which is what a per-page analysis wants and what the Shopify side of
#: this section already aggregates to. 1,805 distinct pages.
#:
#: Rates (bounce_rate, key_event_rate) MUST come from GA4 at this grain
#: rather than be re-derived downstream: their denominators are not
#: exposed by the API, so they cannot be re-weighted across query-string
#: variants or channels after the fact.
DIMENSIONS = ["date", "landingPage", "sessionDefaultChannelGroup"]

#: Ten is the Data API's cap per request, so this is the whole budget.
#: Chosen to span the funnel end to end -- arrival, product interest,
#: intent, checkout, purchase -- because the point of the section is to
#: see WHERE a page loses people, not just how many it gets.
#:
#: itemViewEvents is the PDP step (the `view_item` count). checkouts and
#: ecommercePurchases replace Shopify's own funnel tail, which reads ~10x
#: low here: GoKwik owns the checkout, so Shopify never sees completion.
METRICS = [
    "sessions",
    "totalUsers",
    "itemViewEvents",        # PDP views
    "addToCarts",
    "checkouts",
    "ecommercePurchases",
    "totalRevenue",
    "bounceRate",
    "sessionKeyEventRate",
    "engagedSessions",
]


def _dsn() -> str:
    return os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")


SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

#: Fixed, because a `web` OAuth client only accepts redirect URIs that
#: were registered on it by hand. A random high port would be rejected
#: every time with redirect_uri_mismatch.
OAUTH_PORT = 8080

#: Where the one-time browser consent is cached. secrets/ is gitignored
#: and the repository is public, so nothing here may ever be committed.
TOKEN_PATH = ROOT / "secrets" / "ga4_token.json"

#: The OAuth client downloaded from this project's own console. Google
#: blocks `gcloud auth application-default login --scopes=...analytics`
#: because gcloud's client is SHARED across every gcloud user and is not
#: verified for a restricted scope -- that refusal is about gcloud, not
#: about the account, and retrying it cannot succeed. A client owned by
#: the same project, consented to by its owner, has no such problem.
def _client_secrets_file() -> Path | None:
    """Pick the OAuth client that can actually complete the flow.

    secrets/ may hold several. Choosing by filename order would be
    choosing by accident -- the ids are random, so the "first" one is
    whichever happens to sort low, and that silently changes the moment
    another client is dropped in.

    The discriminator is the loopback redirect URI. A `web` client ships
    with none, and Google matches the redirect EXACTLY, so a client
    without http://localhost:<port>/ registered cannot finish the
    consent no matter how much GA4 access the signing-in account has --
    it fails with redirect_uri_mismatch. A client that has it was
    prepared for this job on purpose.

    Ties break on most-recently-modified, i.e. the one just added.
    """
    explicit = os.getenv("GA4_OAUTH_CLIENT_FILE")
    if explicit:
        return Path(explicit)

    loopback = f"http://localhost:{OAUTH_PORT}/"
    usable: list[tuple[float, Path]] = []
    fallback: list[tuple[float, Path]] = []
    for path in (ROOT / "secrets").glob("client_secret_*.json"):
        try:
            blob = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue
        cfg = blob.get("web") or blob.get("installed") or {}
        uris = cfg.get("redirect_uris") or []
        bucket = usable if any(u.rstrip("/") == loopback.rstrip("/") for u in uris) else fallback
        bucket.append((path.stat().st_mtime, path))
    chosen = usable or fallback
    return max(chosen)[1] if chosen else None


def _oauth_login():
    """One-time browser consent, cached to TOKEN_PATH.

    Uses whatever OAuth client sits in secrets/. A `web` client works as
    well as a desktop one, but ONLY if the loopback address is
    registered on it -- Google matches the redirect exactly, and a web
    client ships with no redirect URIs at all.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    path = _client_secrets_file()
    if path is None or not path.exists():
        raise SystemExit(
            "No OAuth client found. Put the JSON you downloaded from\n"
            "  GCP console -> APIs & Services -> Credentials\n"
            f"into {ROOT / 'secrets'}/ (any name starting client_secret_),\n"
            "or point GA4_OAUTH_CLIENT_FILE at it."
        )
    # Announced, because secrets/ can hold several clients and the one
    # picked decides WHICH project must have the Analytics APIs enabled.
    # Getting a SERVICE_DISABLED error while looking at the console for
    # a different project is a genuinely confusing ten minutes.
    cfg = json.loads(path.read_text())
    cfg = cfg.get("web") or cfg.get("installed") or {}
    print(f"OAuth client: {path.name}")
    print(f"  project:    {cfg.get('project_id')}   <- enable the Analytics APIs HERE")
    print(f"  redirect:   {cfg.get('redirect_uris')}")
    print(f"  scope:      {SCOPE}")
    print("\nSign in as the account that can see the GA4 property. Property\n"
          "access follows the person consenting, not this project.\n")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), scopes=[SCOPE])
    creds = flow.run_local_server(port=OAUTH_PORT, prompt="consent",
                                  authorization_prompt_message="")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
    return creds


def _credentials():
    """A service account, a cached OAuth token, or ADC -- in that order.

    Service account first because it is the only one of the three that
    survives unattended: it never expires and it is what GitHub Actions
    already restores for the nightly run. The cached OAuth token is the
    local convenience path. ADC is last and, for this API, usually the
    one that fails -- it carries whatever scopes the gcloud login asked
    for, which by default do not include Analytics.
    """
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from google.oauth2.credentials import Credentials as UserCreds
    from google.auth.transport.requests import Request

    sa = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if sa and Path(sa).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(sa, scopes=[SCOPE])

    if TOKEN_PATH.exists():
        creds = UserCreds.from_authorized_user_file(str(TOKEN_PATH), scopes=[SCOPE])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        if creds.valid:
            return creds

    try:
        creds, _ = google.auth.default(scopes=[SCOPE])
        return creds
    except DefaultCredentialsError as exc:
        raise SystemExit(
            "No Google credentials. Easiest fix, using the OAuth client "
            "already in secrets/:\n\n"
            "  ./.venv/bin/python scripts/fetch_ga4_daily.py --auth"
        ) from exc


#: The command that fixes the single most likely failure. Repeated in
#: full because a partial --scopes REPLACES the scope set: telling
#: someone to "add analytics.readonly" gets BigQuery's credentials
#: dropped, and that breaks a different pipeline a day later.
_RELOGIN = (
    "gcloud auth application-default login --scopes=openid,"
    "https://www.googleapis.com/auth/userinfo.email,"
    "https://www.googleapis.com/auth/cloud-platform,"
    "https://www.googleapis.com/auth/sqlservice.login,"
    "https://www.googleapis.com/auth/analytics.readonly"
)


def _explain(exc: Exception) -> SystemExit:
    """Turn the two expected Google failures into an instruction.

    Both arrive as a 403 from deep inside the generated client, and both
    read like "you lack access to this property" when they are nothing
    of the kind -- one is a missing scope on the login, the other an API
    that was never switched on for the project.
    """
    text = str(exc)
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text:
        return SystemExit(
            "\nThese credentials carry no Analytics scope.\n\n"
            "  ./.venv/bin/python scripts/fetch_ga4_daily.py --auth\n\n"
            "Do NOT try `gcloud auth application-default login --scopes="
            "...analytics.readonly`: gcloud's OAuth client is shared and "
            "is not verified for that restricted scope, so Google answers "
            "\"This app is blocked\" no matter who signs in."
        )
    if "SERVICE_DISABLED" in text or "has not been used in project" in text:
        return SystemExit(
            "\nThe Analytics API is not enabled on this Google Cloud "
            "project. Enable both, then re-run:\n"
            "  analyticsadmin.googleapis.com   (listing properties)\n"
            "  analyticsdata.googleapis.com    (fetching reports)\n\n"
            f"Original error:\n{text[:400]}"
        )
    return SystemExit(f"\nGoogle Analytics call failed:\n{text[:800]}")


def list_properties(creds) -> list[tuple[str, str, str]]:
    """(property_id, display_name, timezone) for everything this account sees."""
    from google.analytics.admin import AnalyticsAdminServiceClient

    admin = AnalyticsAdminServiceClient(credentials=creds)
    out: list[tuple[str, str, str]] = []
    try:
        summaries = list(admin.list_account_summaries())
    except Exception as exc:  # noqa: BLE001
        raise _explain(exc) from exc
    for summary in summaries:
        for prop in summary.property_summaries:
            # property_summaries carries no timezone, so the property
            # itself is read for it -- one extra call per property, and
            # the timezone is the thing most likely to be wrong.
            pid = prop.property.split("/")[-1]
            try:
                detail = admin.get_property(name=f"properties/{pid}")
                tz = detail.time_zone
            except Exception as exc:  # noqa: BLE001
                tz = f"<unreadable: {type(exc).__name__}>"
            out.append((pid, prop.display_name, tz))
    return out


def _month_spans(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] split into calendar-month chunks."""
    spans: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        spans.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    return spans


def fetch_span(client, property_id: str, since: date, until: date):
    """Every row for [since, until], following the API's own paging."""
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest,
    )

    offset, rows, sampled, thresholded = 0, [], False, False
    while True:
        resp = client.run_report(RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=since.isoformat(),
                                   end_date=until.isoformat())],
            dimensions=[Dimension(name=d) for d in DIMENSIONS],
            metrics=[Metric(name=m) for m in METRICS],
            limit=API_PAGE_SIZE,
            offset=offset,
        ))
        # Recorded, not ignored: a sampled or thresholded response is
        # still worth storing, but a reader has to be able to tell.
        if getattr(resp, "property_quota", None) is not None:
            pass
        sampled = sampled or bool(getattr(resp, "metadata", None)
                                  and getattr(resp.metadata, "sampling_metadatas", None))
        thresholded = thresholded or bool(
            getattr(resp, "metadata", None)
            and getattr(resp.metadata, "subject_to_thresholding", False))
        rows.extend(resp.rows)
        offset += len(resp.rows)
        if len(resp.rows) < API_PAGE_SIZE or offset >= resp.row_count:
            break
    return rows, sampled, thresholded


def _to_tuples(rows, *, property_id: str, tz: str, sampled: bool,
               thresholded: bool) -> list[tuple]:
    now = datetime.now()
    out: list[tuple] = []
    for r in rows:
        d = [v.value for v in r.dimension_values]
        m = [v.value for v in r.metric_values]
        # GA4 returns the date as YYYYMMDD with no separators.
        day = date(int(d[0][:4]), int(d[0][4:6]), int(d[0][6:8]))
        # Positional, in METRICS order: sessions, totalUsers,
        # itemViewEvents, addToCarts, checkouts, ecommercePurchases,
        # totalRevenue, bounceRate, sessionKeyEventRate, engagedSessions.
        # The rates arrive as fractions; stored as fractions, formatted
        # as percentages at the edge.
        i = lambda x: int(float(x or 0))
        f = lambda x: float(x or 0)
        out.append((
            property_id, day, d[1] or "(not set)", d[2] or "(not set)",
            i(m[0]), i(m[1]), i(m[2]), i(m[3]), i(m[4]), i(m[5]),
            f(m[6]), f(m[7]), f(m[8]), i(m[9]),
            tz, sampled, thresholded, now,
        ))
    return out


def _write(conn_factory, rows: list[tuple]) -> int:
    written = 0
    for i in range(0, len(rows), WRITE_CHUNK):
        chunk = rows[i:i + WRITE_CHUNK]
        for attempt in range(4):
            try:
                conn = conn_factory()
                with conn, conn.cursor() as cur:
                    psycopg2.extras.execute_values(cur, UPSERT, chunk, page_size=WRITE_CHUNK)
                conn.close()
                written += len(chunk)
                break
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                # The pooler closed an idle handle while we were talking
                # to Google. Reconnect and redo this chunk only.
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auth", action="store_true",
                    help="Run the one-time browser consent and cache the token.")
    ap.add_argument("--list-properties", action="store_true",
                    help="Print every GA4 property this account can read, then exit.")
    ap.add_argument("--property", default=os.getenv("GA4_PROPERTY_ID"),
                    help="Numeric GA4 property id (or set GA4_PROPERTY_ID in .env).")
    ap.add_argument("--from", dest="from_date", default=None,
                    help=f"First day, YYYY-MM-DD (default {DEFAULT_FROM}).")
    ap.add_argument("--to", dest="to_date", default=None,
                    help="Last day, YYYY-MM-DD (default yesterday).")
    ap.add_argument("--days", type=int, default=None,
                    help="Trailing window ending yesterday. Overrides --from/--to.")
    ap.add_argument("--allow-tz-mismatch", action="store_true",
                    help=f"Proceed even if the property is not on {WAREHOUSE_TZ}.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and report, write nothing.")
    args = ap.parse_args()

    if args.auth:
        _oauth_login()
        print(f"Signed in. Token cached at {TOKEN_PATH} (gitignored).")
        print("Now run:  ./.venv/bin/python scripts/fetch_ga4_daily.py --list-properties")
        return 0

    creds = _credentials()

    if args.list_properties:
        props = list_properties(creds)
        if not props:
            print("This account can see no GA4 properties.")
            return 1
        print(f"{len(props)} GA4 propert{'y' if len(props) == 1 else 'ies'} visible:\n")
        for pid, name, tz in props:
            print(f"   {pid:<14} {name:<44} {tz}")
        print("\nPut the id you want in .env as GA4_PROPERTY_ID, "
              "or pass --property.")
        return 0

    if not args.property:
        print("No property id. Run --list-properties first, then set "
              "GA4_PROPERTY_ID in .env or pass --property.", file=sys.stderr)
        return 2

    # Timezone check BEFORE any fetching: a mismatch makes every row
    # wrong in a way that looks plausible, so it is worth one API call.
    from google.analytics.admin import AnalyticsAdminServiceClient
    admin = AnalyticsAdminServiceClient(credentials=creds)
    try:
        prop = admin.get_property(name=f"properties/{args.property}")
    except Exception as exc:  # noqa: BLE001
        raise _explain(exc) from exc
    tz = prop.time_zone
    print(f"Property:   {args.property}  ({prop.display_name})")
    print(f"Timezone:   {tz}")
    if _same_clock(tz, WAREHOUSE_TZ) and tz != WAREHOUSE_TZ:
        print(f"            (same clock as {WAREHOUSE_TZ}; "
              f"{tz} is an alias for it)")
    if not _same_clock(tz, WAREHOUSE_TZ) and not args.allow_tz_mismatch:
        print(f"\nRefusing to run: this property reports in {tz}, but every "
              f"other table in the warehouse is built on {WAREHOUSE_TZ} days. "
              f"Traffic would land in a different day from the spend that "
              f"caused it.\nPass --allow-tz-mismatch to proceed anyway; the "
              f"timezone is stored on every row either way.", file=sys.stderr)
        return 2

    yesterday = date.today() - timedelta(days=1)
    if args.days:
        until, since = yesterday, yesterday - timedelta(days=args.days - 1)
    else:
        since = date.fromisoformat(args.from_date) if args.from_date else DEFAULT_FROM
        until = date.fromisoformat(args.to_date) if args.to_date else yesterday
    if since > until:
        print(f"Empty range: {since} .. {until}", file=sys.stderr)
        return 2

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    client = BetaAnalyticsDataClient(credentials=creds)

    spans = _month_spans(since, until)
    print(f"Range:      {since} .. {until}  ({len(spans)} request"
          f"{'' if len(spans) == 1 else 's'})")
    print(f"Grain:      day x landing page x channel group\n")

    def _conn():
        c = psycopg2.connect(_dsn(), connect_timeout=20)
        c.autocommit = False
        return c

    if not args.dry_run:
        conn = _conn()
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
        conn.close()

    t0, total, any_sampled, any_thresholded = time.time(), 0, False, False
    for s, e in spans:
        t1 = time.time()
        try:
            rows, sampled, thresholded = fetch_span(client, args.property, s, e)
        except Exception as exc:  # noqa: BLE001
            raise _explain(exc) from exc
        tuples = _to_tuples(rows, property_id=args.property, tz=tz,
                            sampled=sampled, thresholded=thresholded)
        n = 0 if args.dry_run else _write(_conn, tuples)
        total += len(tuples)
        any_sampled = any_sampled or sampled
        any_thresholded = any_thresholded or thresholded
        sess = sum(t[4] for t in tuples)
        flags = ("  SAMPLED" if sampled else "") + ("  THRESHOLDED" if thresholded else "")
        print(f"  {s} .. {e}   {len(tuples):>7,} rows   "
              f"{sess:>10,} sessions   {time.time() - t1:>5.1f}s{flags}")

    verb = "would write" if args.dry_run else "written"
    print(f"\n[OK] {total:,} rows {verb} in {time.time() - t0:.1f}s")
    if any_sampled:
        print("     NOTE: at least one span was SAMPLED -- those figures are "
              "estimates, not counts.")
    if any_thresholded:
        print("     NOTE: at least one span was THRESHOLDED -- GA4 suppressed "
              "low-volume rows, so those days do not sum to the property total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
