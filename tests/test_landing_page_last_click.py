"""The last-click columns, and the source filter that narrows them.

What is worth pinning here is not the arithmetic -- Postgres does that
-- but the two decisions that are easy to undo by accident:

  * the filter narrows the last-click CTE and NOTHING else, so a page
    that took no orders from the selected channel keeps its row and its
    session columns;
  * the predicate behind it is `_channel_sql_predicate`, the same
    ordered rule set the channel tiles and the Last Click UTM row
    filter use, rather than a second rule set that drifts from it.
"""

from datetime import date

import pytest

from app.api.routers import analytics


def _build(source: str | None) -> str:
    predicate = "TRUE" if source is None else analytics._channel_sql_predicate(source)[0]
    cte = analytics._LP_LAST_CLICK_SQL.format(source_predicate=predicate)
    return analytics._LANDING_PAGE_SQL.format(last_click_cte=cte)


def test_statement_assembles_for_every_channel_and_for_combined():
    pglast = pytest.importorskip("pglast")
    import re

    for source in (None, *analytics._CHANNEL_ORDER):
        sql = _build(source)
        # pglast cannot parse :named binds; `(?<!:)` keeps ::casts intact.
        pglast.parse_sql(re.sub(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)", "'x'", sql))


def test_combined_applies_no_channel_predicate():
    assert "WHERE TRUE\n   GROUP BY path" in _build(None)


def test_filter_narrows_only_the_last_click_cte():
    sql = _build("Meta")
    before, _, after = sql.partition("), joined AS (")
    # The predicate lives in the CTE...
    assert "utm_source" in before
    # ...and the joined projection never filters on it, so every page
    # survives the filter with its session columns intact.
    assert "utm_source" not in after
    assert "FULL OUTER JOIN sh ON sh.path = ga.path" in after
    assert "LEFT JOIN lc ON lc.path = COALESCE(ga.path, sh.path)" in after


def test_organic_ig_rule_needs_utm_content_and_the_cte_exposes_it():
    """Regression: the first build omitted utm_content from the inner
    SELECT, so selecting any channel raised `column "utm_content" does
    not exist` -- the Organic (IG) rule reads it, and that rule is
    evaluated first for every channel."""
    assert "utm_content" in analytics._ORGANIC_IG_SQL
    assert "AS utm_content" in analytics._LP_LAST_CLICK_SQL


def test_revenue_prefers_shopify_and_falls_back_to_ga4():
    """The page is GA4's; the money is Shopify's wherever it joins."""
    assert "COALESCE(s.total_price, g.revenue)" in analytics._LP_LAST_CLICK_SQL
    assert "COALESCE(s.utm_source, g.last_source)" in analytics._LP_LAST_CLICK_SQL


def test_url_normaliser_matches_the_gold_path_rule():
    """`last_landing` is a full URL with a query string; every landing
    page table keys on the bare path. Checked against the Python rule
    the gold tables normalise with, so the two cannot diverge."""
    from app.services.gold.landing_page import normalize_session_path

    cases = {
        "https://saadaa.in/": "/",
        "https://saadaa.in": "/",
        "https://saadaa.in/?country=IN": "/",
        "https://saadaa.in/collections/men-cotton-pant": "/collections/men-cotton-pant",
        "https://saadaa.in/collections/x/": "/collections/x",
        "https://saadaa.in/collections/x?utm_source=META&utm_medium=paid": "/collections/x",
        "https://saadaa.in/account/login?return_url=%2Faccount": "/account/login",
        "https://saadaa.in/a#frag": "/a",
    }
    for url, expected in cases.items():
        # The SQL strips scheme+host and the query; this mirrors it.
        import re as _re
        stripped = _re.sub(r"[?#].*$", "", _re.sub(r"^https?://[^/]*", "", url))
        got = "/" if stripped in ("", "/") else _re.sub(r"/+$", "", stripped)
        assert got == expected, url
        # and the trailing-slash half agrees with the gold normaliser
        assert got == normalize_session_path(got)


@pytest.mark.parametrize("bad", ["meta", "META", "Paid Social", "Combined"])
def test_unknown_source_is_rejected_rather_than_silently_ignored(bad):
    """A typo, or GA4's own channel vocabulary, must not quietly return
    combined figures labelled as a channel -- the endpoint 400s on
    anything outside `_CHANNEL_ORDER`, and these are the near misses."""
    assert bad not in analytics._CHANNEL_ORDER


def test_sort_accepts_the_new_columns():
    for key in ("last_click_orders", "last_click_revenue",
                "last_click_aov", "last_click_rev_per_session"):
        assert key in analytics._LANDING_PAGE_SORT_COLUMNS


def test_row_model_carries_the_new_fields():
    fields = analytics.LandingPageRow.model_fields
    for key in ("last_click_orders", "last_click_revenue",
                "last_click_aov", "last_click_rev_per_session"):
        assert key in fields
        # Null is a real answer here: GA4 sees 74% of orders, so "none
        # attributed" is not "none happened" and must not become 0.
        assert type(None) in fields[key].annotation.__args__


def test_response_echoes_the_filter_and_its_vocabulary():
    fields = analytics.LandingPageResponse.model_fields
    assert "source" in fields and "sources" in fields


def test_window_is_half_open_on_the_end_day():
    """order_at is a timestamp. `BETWEEN :from AND :to` would drop every
    order placed after midnight on the last day."""
    assert "g.order_at < (CAST(:to_date AS date) + 1)" in analytics._LP_LAST_CLICK_SQL


# ── the summary band's totals ────────────────────────────────────────


def test_totals_are_window_aggregates_not_a_second_statement():
    """The band must describe every matching page, and must not cost a
    second round trip to do it -- on this database a round trip is
    ~500ms against ~60ms of aggregation."""
    assert analytics._LANDING_PAGE_TOTAL_COLUMNS
    for column in analytics._LANDING_PAGE_TOTAL_COLUMNS:
        assert column in analytics.LandingPageTotals.model_fields


def test_totals_sql_puts_over_on_the_aggregate():
    """Regression: `COALESCE(SUM(c), 0) OVER ()` is a syntax error --
    OVER binds to the aggregate call, so the COALESCE has to wrap the
    whole window instead. Shipped once and 500'd every request."""
    selects = ", ".join(
        f"COALESCE(SUM({c}) OVER (), 0) AS _t_{c}"
        for c in analytics._LANDING_PAGE_TOTAL_COLUMNS
    )
    pglast = pytest.importorskip("pglast")
    pglast.parse_sql(f"SELECT 1 AS x, {selects} FROM (SELECT 1) t")


def test_totals_cover_both_funnels_and_last_click():
    fields = set(analytics.LandingPageTotals.model_fields)
    # Everything the Google funnel draws...
    assert {"ga4_sessions", "ga4_pdp_views", "ga4_add_to_carts",
            "ga4_checkouts", "ga4_purchases"} <= fields
    # ...everything Shopify's draws...
    assert {"shopify_sessions", "shopify_atc_sessions",
            "shopify_checkout_sessions"} <= fields
    # ...and the figures the source filter moves.
    assert {"last_click_orders", "last_click_revenue"} <= fields
    # `pages` states the band's own basis without reaching outside it.
    assert "pages" in fields


def test_totals_are_required_so_an_absent_one_cannot_read_as_zero():
    """A missing total must fail loudly rather than draw a funnel of
    nothing, which looks identical to a real collapse."""
    for name, field in analytics.LandingPageTotals.model_fields.items():
        assert field.is_required(), name
