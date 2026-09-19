"""Copy exact lifetime ad timing into the existing metrics mirror.

Runs read-only by default. Use --apply after the normal metrics sync's
three additive timing columns have been installed. No metrics, rows,
or refresh timestamps are replaced by this focused backfill.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import os
from pathlib import Path
import signal
import sys
import time

from dotenv import dotenv_values
import psycopg2
from psycopg2.extras import execute_values


PROJECT_ENV = Path(__file__).resolve().parents[1] / ".env"
TIME_LIMIT_SECONDS = 45
BATCH_SIZE = 500
SOURCE_SQL = """
SELECT ad_id, first_seen_date, date_target_imp_achieved,
       days_to_target_f1, date_of_result, days_to_result
FROM public.ae_table_view
WHERE ad_id IS NOT NULL
"""
MATCHED_SQL = """
SELECT COUNT(*) FROM public.ad_metrics_external WHERE ad_id = ANY(%s)
"""
UPDATE_SQL = """
UPDATE public.ad_metrics_external AS target
SET first_seen_date = incoming.first_seen_date,
    impressions_50k_date = incoming.impressions_50k_date,
    days_to_50k = incoming.days_to_50k,
    date_of_result = incoming.date_of_result,
    days_to_result = incoming.days_to_result
FROM (VALUES %s) AS incoming (
    ad_id, first_seen_date, impressions_50k_date,
    days_to_50k, date_of_result, days_to_result
)
WHERE target.ad_id = incoming.ad_id
  AND (target.first_seen_date, target.impressions_50k_date,
       target.days_to_50k, target.date_of_result, target.days_to_result)
      IS DISTINCT FROM
      (incoming.first_seen_date, incoming.impressions_50k_date,
       incoming.days_to_50k, incoming.date_of_result, incoming.days_to_result)
RETURNING target.ad_id
"""
VALUE_TEMPLATE = "(%s::text, %s::date, %s::date, %s::integer, %s::date, %s::integer)"


def _dsn(value: str | None) -> str:
    return (value or "").replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def _connections(source_env: Path | None) -> tuple[str, str]:
    settings = {**dotenv_values(PROJECT_ENV), **os.environ}
    source = settings.get("AD_METRICS_SOURCE_URL")
    if source_env is not None:
        if not source_env.is_file():
            raise ValueError("The source environment file does not exist.")
        source_settings = dotenv_values(source_env)
        source = (
            source_settings.get("AD_METRICS_SOURCE_URL")
            or source_settings.get("SUPABASE_DB_URL")
        )
    target = settings.get("DATABASE_URL_SYNC") or settings.get("DATABASE_URL")
    if not source or not target:
        raise ValueError("Source and target database connections must both be configured.")
    return _dsn(source), _dsn(target)


@contextmanager
def _time_limit(seconds: int):
    def expired(_signum, _frame):
        raise TimeoutError("Timing backfill exceeded its time limit.")

    previous_handler = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _connect(dsn: str, *, readonly: bool):
    connection = psycopg2.connect(
        dsn, connect_timeout=5,
        options="-c statement_timeout=10000 -c lock_timeout=3000",
    )
    try:
        connection.set_session(readonly=readonly, autocommit=False)
    except BaseException:
        connection.close()
        raise
    return connection


def _update_rows(cursor, rows: list[tuple], deadline: float) -> int:
    changed = 0
    for start in range(0, len(rows), BATCH_SIZE):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise TimeoutError("Timing backfill exceeded its time limit.")
        cursor.execute("SELECT set_config('statement_timeout', %s, true)",
                       (f"{min(10000, remaining_ms)}ms",))
        result = execute_values(
            cursor, UPDATE_SQL, rows[start:start + BATCH_SIZE],
            template=VALUE_TEMPLATE, page_size=BATCH_SIZE, fetch=True,
        )
        changed += len(result)
    return changed


def _run(source_dsn: str, target_dsn: str, *, apply: bool, deadline: float) -> int:
    with closing(_connect(source_dsn, readonly=True)) as source:
        with source, source.cursor() as cursor:
            cursor.execute(SOURCE_SQL)
            rows = cursor.fetchall()
    if not rows:
        raise ValueError("Source returned no ads; target was left unchanged.")
    ids = [str(row[0]) for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Source returned duplicate ad IDs; target was left unchanged.")
    print(f"Source ads: {len(rows):,}.", flush=True)

    with closing(_connect(target_dsn, readonly=not apply)) as target:
        with target, target.cursor() as cursor:
            cursor.execute(MATCHED_SQL, (ids,))
            matched = cursor.fetchone()[0]
            print(f"Existing target ads matched: {matched:,}.", flush=True)
            if not apply:
                print("Dry run: no changes made. Use --apply to copy timing fields.")
                return 0
            if not matched:
                raise ValueError("No target ads matched; target was left unchanged.")
            changed = _update_rows(cursor, rows, deadline)
    print(f"Updated timing for {changed:,} ads; {matched - changed:,} already matched.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write timing fields only.")
    parser.add_argument("--source-env", type=Path,
                        help="Read the source database URL from this environment file only.")
    args = parser.parse_args()
    try:
        with _time_limit(TIME_LIMIT_SECONDS):
            deadline = time.monotonic() + TIME_LIMIT_SECONDS
            source, target = _connections(args.source_env)
            return _run(source, target, apply=args.apply, deadline=deadline)
    except ValueError as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        # Database exceptions can include connection strings or row values.
        # Report only their class/code; never echo credentials or source data.
        code = getattr(error, "pgcode", None)
        detail = f", SQLSTATE {code}" if code else ""
        print(f"Timing backfill stopped: {type(error).__name__}{detail}. "
              "No retries were attempted; uncommitted changes were rolled back.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
