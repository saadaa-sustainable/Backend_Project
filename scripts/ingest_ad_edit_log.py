"""Mirror `ad_edit_log` from the legacy Meta_ads_data project.

WHAT IT IS
----------
Meta's Activity log, already flattened and — since 2026-09-21 — carrying
`adset_id` and `campaign_name` on every row. 93,350 rows, 12,638 ads,
events from 2024-09-18, refreshed daily on the source side.

WHY LAST-CLICK NEEDS IT
-----------------------
`utm_content` is frozen at click time: it holds the ad's name *as it was
then*. `ad_lifecycle` and `meta_ads` hold only the name *now*. Every
rename between the click and today silently breaks name matching, which
is exactly what the `adset_name_miss` tier is — the ad set resolved, the
name did not. 54,055 orders sit there, ₹6.69 Cr of revenue attributed to
an ad set but to no ad.

The 4,404 `update_ad_friendly_name` rows carry `old_value` and
`new_value`, so they reconstruct every name an ad has answered to.

WHY THE adset_id COLUMN MATTERS
-------------------------------
Without it, resolving a historical name to an ad set meant joining
`ad_lifecycle` on ad_id — an extra hop that yields the ad's CURRENT ad
set rather than the one it was in at rename time. With it, the log
yields the lookup key directly:

    (adset_id, historical_name) -> ad_id

which is exactly the pair an order already provides: `utm_term` is the
ad set id, `utm_content` is the name. It drops straight into the
cascade's Step 2 with no traversal at all.

It is also a far safer key. Measured on the source:

    name alone          6,217 keys,  825 ambiguous  (13.3%)
    (adset_id, name)    7,397 keys,  144 ambiguous  ( 1.9%)

Ambiguity is terminal in this cascade, so that 13.3% is matches thrown
away. Scoping to the ad set recovers most of them.

Worth recording honestly: no ad in the log has ever appeared under more
than one adset_id (0 of 12,638). So the column is not correcting a
mis-mapping the ad_lifecycle join would have made — its value is the
ambiguity reduction and the removed hop, not a fixed bug.

WHY MIRROR RATHER THAN QUERY ACROSS
-----------------------------------
The attribution cascade loads its whole universe up front and must not
depend on a second project being reachable mid-refresh. A local mirror
also means `ad_name_alias` can be rebuilt without re-reading 93k rows
over a cross-region pooler (this source is ap-northeast-1; our database
is not).

Usage:
    ./.venv/bin/python scripts/ingest_ad_edit_log.py            # full, idempotent
    ./.venv/bin/python scripts/ingest_ad_edit_log.py --since 2026-09-01
    ./.venv/bin/python scripts/ingest_ad_edit_log.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


def _dsn(raw: str) -> str:
    return (raw.replace("postgresql+psycopg2://", "postgresql://")
               .replace("postgresql+asyncpg://", "postgresql://")
               .split("?")[0])


SOURCE_DSN_ENV = "SUPABASE_DB_URL"
TARGET_DSN_ENV = "DATABASE_URL_SYNC"

#: Mirrors the source columns exactly. row_hash is the source's own key,
#: so re-running is a no-op rather than a duplicate.
DDL = """
CREATE TABLE IF NOT EXISTS public.ad_edit_log (
    row_hash              text PRIMARY KEY,
    account_id            text NOT NULL,
    account_name          text,
    ad_id                 text,
    adset_id              text,
    campaign_name         text,
    object_name           text,
    object_type           text,
    event_time            timestamptz NOT NULL,
    event_type            text,
    translated_event_type text,
    actor_id              text,
    actor_name            text,
    extra_data            jsonb,
    application_name      text,
    date_time_in_timezone text,
    fetched_at            timestamptz NOT NULL,
    ingested_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ael_ad_id      ON public.ad_edit_log (ad_id);
CREATE INDEX IF NOT EXISTS ix_ael_adset_id   ON public.ad_edit_log (adset_id);
-- The alias build filters to rename events and orders by time; this is
-- the index that query wants.
CREATE INDEX IF NOT EXISTS ix_ael_event_type ON public.ad_edit_log (event_type, event_time DESC);
"""

COLUMNS = [
    "row_hash", "account_id", "account_name", "ad_id", "adset_id", "campaign_name",
    "object_name", "object_type", "event_time", "event_type", "translated_event_type",
    "actor_id", "actor_name", "extra_data", "application_name",
    "date_time_in_timezone", "fetched_at",
]

#: Keyset, not OFFSET. The source is a cross-region pooler and a deep
#: OFFSET re-scans everything it skips.
SELECT_PAGE = f"""
SELECT {', '.join(COLUMNS)}
  FROM public.ad_edit_log
 WHERE row_hash > %s
   AND (%s::timestamptz IS NULL OR event_time >= %s::timestamptz)
 ORDER BY row_hash
 LIMIT %s
"""

UPSERT = f"""
INSERT INTO public.ad_edit_log ({', '.join(COLUMNS)}) VALUES %s
ON CONFLICT (row_hash) DO UPDATE SET
    {', '.join(f'{c} = EXCLUDED.{c}' for c in COLUMNS if c != 'row_hash')},
    ingested_at = now()
"""

PAGE = 2000
WRITE_CHUNK = 500


class _Db:
    """Reconnecting handle -- both ends of this job are Supabase poolers.

    A dropped connection here is not hypothetical: it has cost this
    project a 368k-row read, a 41k-row write and two whole Meta fetches.
    Every statement retries on the two errors that mean the handle is
    dead rather than the statement wrong.
    """

    def __init__(self, dsn: str, label: str) -> None:
        self._dsn, self._label, self._conn = dsn, label, None

    def _fresh(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = psycopg2.connect(self._dsn)
        return self._conn

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            return self._fresh()
        return self._conn

    def run(self, fn, *, attempts: int = 4, commit: bool = True):
        last: Exception | None = None
        for i in range(attempts):
            conn = self.conn
            try:
                out = fn(conn)
                if commit:
                    conn.commit()
                return out
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                last = exc
                print(f"    [{self._label}] connection lost ({exc.__class__.__name__}); "
                      f"reconnecting ({i + 1}/{attempts})", flush=True)
                self._fresh()
                time.sleep(2 ** i)
        assert last is not None
        raise last

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", help="Only rows with event_time >= this date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read and count from the source; write nothing.")
    args = ap.parse_args()

    src_raw = os.environ.get(SOURCE_DSN_ENV)
    if not src_raw:
        print(f"{SOURCE_DSN_ENV} is not set -- it must point at the "
              f"Meta_ads_data project that owns ad_edit_log.", file=sys.stderr)
        return 2
    tgt_raw = os.environ.get(TARGET_DSN_ENV)
    if not tgt_raw:
        print(f"{TARGET_DSN_ENV} is not set.", file=sys.stderr)
        return 2

    src = _Db(_dsn(src_raw), "source")
    tgt = _Db(_dsn(tgt_raw), "target")
    t0 = time.monotonic()
    try:
        if not args.dry_run:
            tgt.run(lambda c: [c.cursor().execute(DDL)])

        cursor_key, total, renames = "", 0, 0
        while True:
            def _page(conn, key=cursor_key):
                with conn.cursor() as cur:
                    cur.execute(SELECT_PAGE, (key, args.since, args.since, PAGE))
                    return cur.fetchall()

            rows = src.run(_page, commit=False)
            if not rows:
                break

            renames += sum(1 for r in rows if r[COLUMNS.index("event_type")]
                           == "update_ad_friendly_name")
            if not args.dry_run:
                payload = [
                    tuple(psycopg2.extras.Json(v) if c == "extra_data" and v is not None else v
                          for c, v in zip(COLUMNS, row))
                    for row in rows
                ]
                # Each chunk is its own transaction, so a drop mid-page
                # costs one chunk rather than the page.
                for i in range(0, len(payload), WRITE_CHUNK):
                    chunk = payload[i:i + WRITE_CHUNK]

                    def _write(conn, chunk=chunk):
                        with conn.cursor() as cur:
                            psycopg2.extras.execute_values(
                                cur, UPSERT, chunk, page_size=WRITE_CHUNK)

                    tgt.run(_write)

            total += len(rows)
            cursor_key = rows[-1][0]
            print(f"  {total:>7,} rows", flush=True)
            if len(rows) < PAGE:
                break

        verb = "would ingest" if args.dry_run else "ingested"
        print(f"\n[OK] {verb} {total:,} rows ({renames:,} ad renames) "
              f"in {time.monotonic() - t0:.1f}s", flush=True)
        if not args.dry_run:
            def _check(conn):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*), count(adset_id), max(event_time)::date "
                        "FROM public.ad_edit_log")
                    return cur.fetchone()
            n, with_adset, last = tgt.run(_check, commit=False)
            print(f"      local ad_edit_log: {n:,} rows, {with_adset:,} with adset_id, "
                  f"latest event {last}", flush=True)
    finally:
        src.close()
        tgt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
