"""Resolve the tokens GA4 puts in utm_content to real ad ids.

The problem
-----------
`utm_content` is supposed to carry the Meta ad id, and usually does.
But the field is whatever the ad's URL template produced, so over a
30-day window the first-click column holds four different kinds of
thing:

    id                 1,141 tokens   Rs 2.03 Cr   a real ad id
    third_party_token    726          Rs 48.4 L    kwikengage, affiliate
    google_ad             13          Rs 26.3 L    a Google Ads id
    ad NAME               97          Rs 9.3 L     the name, not the id
    {{ad.id}}              2          Rs 98.7 K    an unexpanded macro

Everything downstream joins `ad_lifecycle` on `ad_id`, so a NAME never
matches. Those orders sit in the First Click table under a row labelled
with the raw name, carrying no spend and therefore no ROAS, while the
real ad sits in another row missing that revenue.

What this resolves, and what it refuses to
------------------------------------------
    name_unique   the name matches exactly one ad          43 tokens
    name_spend    several ads share it, one ever spent     14 tokens

    name_ambiguous  several candidates, no way to choose   40 tokens
    google_ad       a Google id -- name only, no Meta spend
    third_party     not an ad at all
    unexpanded_macro  the ad's URL template is broken

Ambiguity is left unresolved on purpose. Ad names repeat heavily here
-- one name is shared by seventeen ads -- and this codebase has already
paid for a loose match once: colour-code tolerance in the CPIS SKU
matcher would have moved Rs 12.8 L to the wrong SKU before a
longest-match rule was added. Guessing which of seventeen creatives
earned an order is worse than leaving it labelled by its name.

`{{ad.id}}` is not a data defect and cannot be fixed here: the ad's URL
template never expanded, so the click arrived with the literal macro.
It needs correcting in Ads Manager, and is surfaced so somebody can.

Window-free on purpose: `name_spend` asks whether an ad EVER spent, not
whether it spent in some window, so the mapping does not change when a
dashboard date range changes.

Usage:
    ./.venv/bin/python scripts/refresh_ad_token_resolution.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.dbq import connect  # noqa: E402

VIEW = """
CREATE MATERIALIZED VIEW public.ad_token_resolution AS
WITH tokens AS (
    -- FIRST click only, because that is all GA4 carries. There was a
    -- `last_ad_id` arm here and the column does not exist: last click
    -- is derived from our own order data, never from GA4, so the
    -- UNION was reading a column that was dropped when that became
    -- clear. It failed the step outright -- UndefinedColumn, every
    -- night -- rather than quietly returning less.
    --
    -- DISTINCT: one row per token. Without it this returned one row per
    -- ORDER, and every reader that joins on `token` multiplied its
    -- orders by the number of orders sharing that token.
    SELECT DISTINCT first_ad_id AS token FROM public.ga4_order_attribution
     WHERE first_ad_id IS NOT NULL
),
by_name AS (
    SELECT t.token,
           COUNT(DISTINCT a.ad_id)                        AS n_named,
           MIN(a.ad_id)                                   AS only_ad_id,
           COUNT(DISTINCT a.ad_id) FILTER (WHERE s.ad_id IS NOT NULL) AS n_spent,
           MIN(a.ad_id)            FILTER (WHERE s.ad_id IS NOT NULL) AS only_spent_ad_id
    FROM tokens t
    JOIN public.ad_lifecycle a ON a.ad_name = t.token
    LEFT JOIN (SELECT DISTINCT ad_id FROM public.insights_daily_by_ad WHERE spend > 0) s
           ON s.ad_id = a.ad_id
    GROUP BY t.token
)
SELECT
    t.token,
    CASE
      WHEN l.ad_id IS NOT NULL            THEN t.token
      WHEN b.n_named = 1                  THEN b.only_ad_id
      WHEN b.n_spent = 1                  THEN b.only_spent_ad_id
    END AS resolved_ad_id,
    CASE
      WHEN l.ad_id IS NOT NULL            THEN 'id'
      WHEN b.n_named = 1                  THEN 'name_unique'
      WHEN b.n_spent = 1                  THEN 'name_spend'
      WHEN b.token IS NOT NULL            THEN 'name_ambiguous'
      WHEN t.token LIKE '{{%'             THEN 'unexpanded_macro'
      WHEN g.ad_id IS NOT NULL            THEN 'google_ad'
      ELSE 'third_party_token'
    END AS method,
    -- The label to show. A resolved token takes the real ad's name; an
    -- unresolved one keeps its token, because a blank would hide real
    -- orders and the token is at least recognisable to whoever built
    -- the URL.
    COALESCE(
        l.ad_name,
        CASE WHEN b.n_named = 1 THEN (SELECT a2.ad_name FROM public.ad_lifecycle a2
                                       WHERE a2.ad_id = b.only_ad_id LIMIT 1)
             WHEN b.n_spent = 1 THEN (SELECT a2.ad_name FROM public.ad_lifecycle a2
                                       WHERE a2.ad_id = b.only_spent_ad_id LIMIT 1)
        END,
        g.ad_name,
        t.token
    ) AS label,
    b.n_named AS ads_sharing_this_name
FROM tokens t
LEFT JOIN public.ad_lifecycle l ON l.ad_id = t.token
LEFT JOIN by_name b             ON b.token = t.token
LEFT JOIN public.google_ads g   ON g.ad_id = t.token
"""


def main() -> int:
    t0 = time.time()
    with connect(autocommit=False, statement_timeout="600s") as conn:
        with conn.cursor() as cur:
            # Stored, not a plain view: building it reads a few hundred
            # thousand blocks, and First Click joins it up to six times
            # per request. Rebuilt here; a token that arrives in between
            # falls back to its raw id until the next run.
            cur.execute("SELECT relkind FROM pg_class "
                        "WHERE oid = to_regclass('public.ad_token_resolution')")
            kind = cur.fetchone()
            if kind:
                what = "MATERIALIZED VIEW" if kind[0] == "m" else "VIEW"
                cur.execute(f"DROP {what} public.ad_token_resolution CASCADE")
            cur.execute(VIEW)
            # Unique, so a duplicate token can never fan a join out again.
            cur.execute("CREATE UNIQUE INDEX ad_token_resolution_token "
                        "ON public.ad_token_resolution (token)")
            cur.execute("""
                SELECT method, COUNT(*) FROM public.ad_token_resolution
                GROUP BY method ORDER BY 2 DESC
            """)
            for method, n in cur.fetchall():
                print(f"  {method:<20} {n:>6,}")
        conn.commit()
    print(f"  done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
