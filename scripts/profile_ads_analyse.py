"""Profile the four /ads-analyse queries to isolate the cold cost."""
import os
import time

from dotenv import load_dotenv
import psycopg2

load_dotenv(r"D:/Backend_Project/.env")
DSN = (os.environ.get("DATABASE_URL_SYNC") or os.environ["SUPABASE_DB_URL"]).strip()
if DSN.startswith("postgresql+psycopg2://"):
    DSN = DSN.replace("postgresql+psycopg2://", "postgresql://")

FROM_DATE, TO_DATE = "2026-08-16", "2026-09-14"
WHERE_ROW = (
    "al.ad_created_time::date BETWEEN %(f)s AND %(t)s "
    "AND aps.ad_name NOT ILIKE '%%copy%%'"
)

FROM_AGG = (
    "FROM ad_performance_summary aps "
    "LEFT JOIN ad_lifecycle al ON al.ad_id = aps.ad_id "
    "LEFT JOIN public.ad_history_milestones ahm ON ahm.ad_id = aps.ad_id"
)
FROM_LATERAL = FROM_AGG + (
    " LEFT JOIN LATERAL ("
    "  SELECT MIN(ai.date_start) AS first_seen_date "
    "  FROM ad_insights ai WHERE ai.ad_id = aps.ad_id"
    ") fs ON true"
)
FROM_ROWS_FULL = FROM_LATERAL + (
    " LEFT JOIN ("
    "  SELECT DISTINCT ON (ad_id) ad_id, asset_id, media, source"
    "  FROM ("
    "    SELECT ad_id, asset_id, 'video'::text AS media, 'direct'::text AS source, 1 AS pri"
    "      FROM public.content_asset_register WHERE ad_id IS NOT NULL"
    "    UNION ALL"
    "    SELECT ad_id, requisition_id, 'graphic'::text, 'direct'::text, 2"
    "      FROM public.content_graphic_register WHERE ad_id IS NOT NULL"
    "    UNION ALL"
    "    SELECT matched_ad_id, asset_id, 'video'::text, 'ctd_matched'::text, 3"
    "      FROM public.content_asset_register"
    "      WHERE matched_ad_id IS NOT NULL AND ad_id IS NULL"
    "    UNION ALL"
    "    SELECT matched_ad_id, requisition_id, 'graphic'::text, 'ctd_matched'::text, 4"
    "      FROM public.content_graphic_register"
    "      WHERE matched_ad_id IS NOT NULL AND ad_id IS NULL"
    "    UNION ALL"
    "    SELECT matched_ad_id, id::text, 'influencer'::text, 'ctd_matched'::text, 5"
    "      FROM public.content_influencer_posts WHERE matched_ad_id IS NOT NULL"
    "  ) u WHERE ad_id IS NOT NULL"
    "  ORDER BY ad_id, pri"
    " ) asset_direct ON asset_direct.ad_id = aps.ad_id"
    " LEFT JOIN LATERAL ("
    "   SELECT asset_id, media, source FROM ("
    "     SELECT car.asset_id, 'video'::text AS media, 'name_parsed'::text AS source, 1 AS pri"
    "       FROM public.content_asset_register car"
    "       WHERE car.asset_id = substring(aps.ad_name from '([A-Z]{3}[0-9]{3}-[0-9]{4})')"
    "     UNION ALL"
    "     SELECT cgr.requisition_id, 'graphic'::text, 'name_parsed'::text, 2"
    "       FROM public.content_graphic_register cgr"
    "       WHERE cgr.requisition_id = substring(aps.ad_name from '(GAD-[A-Za-z]{3}-[0-9]+)')"
    "     UNION ALL"
    "     SELECT substring(aps.ad_name from '([A-Z]{3}[0-9]{3}-[0-9]{4})'), 'video'::text, 'name_synthetic'::text, 3"
    "       WHERE aps.ad_name ~ '[A-Z]{3}[0-9]{3}-[0-9]{4}'"
    "     UNION ALL"
    "     SELECT substring(aps.ad_name from '(GAD-[A-Za-z]{3}-[0-9]+)'), 'graphic'::text, 'name_synthetic'::text, 4"
    "       WHERE aps.ad_name ~ 'GAD-[A-Za-z]{3}-[0-9]+'"
    "     UNION ALL"
    "     SELECT substring(aps.ad_name from '(SIF-[0-9]+-P[0-9]+)'), 'influencer'::text, 'name_synthetic'::text, 5"
    "       WHERE aps.ad_name ~ 'SIF-[0-9]+-P[0-9]+'"
    "   ) u ORDER BY pri LIMIT 1"
    " ) asset_name ON asset_direct.ad_id IS NULL"
    " LEFT JOIN public.ad_media am ON am.ad_id = aps.ad_id"
    " LEFT JOIN public.ad_thumbnails at ON at.ad_id = aps.ad_id"
)


def timed(cur, label, sql):
    t = time.perf_counter()
    cur.execute(sql, {"f": FROM_DATE, "t": TO_DATE})
    _ = cur.fetchall()
    return time.perf_counter() - t


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SET statement_timeout=120000")

    variants = [
        ("row query (no LATERAL, no assets)",
         f"SELECT aps.ad_id, aps.spend {FROM_AGG} WHERE {WHERE_ROW} ORDER BY aps.spend DESC NULLS LAST LIMIT 100"),
        ("row query (+ first_seen LATERAL)",
         f"SELECT aps.ad_id, aps.spend, fs.first_seen_date {FROM_LATERAL} WHERE {WHERE_ROW} ORDER BY aps.spend DESC NULLS LAST LIMIT 100"),
        ("row query (+ assets + media + thumb)",
         f"SELECT aps.ad_id, aps.spend, fs.first_seen_date, asset_direct.asset_id, am.thumbnail_url {FROM_ROWS_FULL} WHERE {WHERE_ROW} ORDER BY aps.spend DESC NULLS LAST LIMIT 100"),
    ]
    for label, sql in variants:
        cold = timed(cur, label, sql)
        warm = timed(cur, label, sql)
        print(f"{label:<45} cold={cold:6.2f}s   warm={warm:6.2f}s")

    conn.close()


if __name__ == "__main__":
    main()
