"""Gender buckets must partition the pages, and `women` must not read as `men`.

Two failure modes, both silent:

  * "women" CONTAINS "men". A substring match files every women's page
    under men, and the numbers still look plausible.
  * The tag lookup is a subquery, so it is NULL on a non-product page.
    NULL IN (...) is NULL, and `NOT (NULL) AND (TRUE)` is NULL, which a
    WHERE drops -- so a men's COLLECTION page fell out of men without
    landing in other. Measured against the live endpoint before the
    fix: the three buckets returned 2,800 of 2,872 pages and 1.27M of
    1.79M sessions, and nothing announced the shortfall.
"""

import re
import sqlite3

import pytest

from app.api.routers import analytics as A


# Real paths from the catalogue, 2026-10-16. The women-token ones are
# the trap: each contains "men" as a substring.
WOMEN_PATHS = [
    "/collections/women-airy-linen-split-neck-short-kurta",
    "/collections/shop-all-women-2",
    "/collections/best-sellers-women",
    "/collections/women-straight-fit-cotton-pant",
    "/products/women-khakhi-cotton-straight-pant",
]
MEN_PATHS = [
    "/collections/men-cotton-pant",
    "/collections/shop-all-men-2",
    "/collections/men-behtar-cotton",
    "/products/men-black-cotton-pant",
    "/collections/men-flat-knit-round-neck-t-shirt",
]
NEITHER_PATHS = [
    "/",
    "/collections/cotton-trousers",
    "/collections/viscose-palazzo-pants",
    "/collections/short-kurtas",
    "/collections/3-pack-bundles",
    "(not set)",
]


def _slug(expr_key: str, path: str) -> bool:
    """Run the shipped slug regex through Python's engine.

    The production pattern is POSIX ERE evaluated by Postgres; the
    subset used here -- anchors, a character class, `?`, alternation --
    means the same thing in both engines, so this is a faithful check
    of the pattern itself rather than of a paraphrase of it.
    """
    sql = A._LANDING_PAGE_GENDER_SLUG[expr_key]
    pattern = re.search(r"~ '(.*)'$", sql).group(1)
    return re.search(pattern, path) is not None


@pytest.mark.parametrize("path", WOMEN_PATHS)
def test_a_women_path_is_women_and_never_men(path):
    assert _slug("women", path)
    # The whole trap in one assertion.
    assert not _slug("men", path), f"{path} matched the men pattern via 'wo-MEN'"


@pytest.mark.parametrize("path", MEN_PATHS)
def test_a_men_path_is_men_and_never_women(path):
    assert _slug("men", path)
    assert not _slug("women", path)


@pytest.mark.parametrize("path", NEITHER_PATHS)
def test_an_ungendered_path_matches_neither(path):
    assert not _slug("men", path)
    assert not _slug("women", path)


def test_the_patterns_never_both_match():
    for path in WOMEN_PATHS + MEN_PATHS + NEITHER_PATHS:
        assert not (_slug("men", path) and _slug("women", path)), path


def test_men_is_defined_as_men_minus_women():
    """Order matters: without the exclusion, a page carrying both the
    women tag and the men token would be counted in both buckets and
    the three counts would overshoot the total."""
    assert A._LANDING_PAGE_GENDER_SQL["men"].startswith(
        f"(NOT {A._LANDING_PAGE_WOMEN_SQL}")


def test_the_tag_lookup_can_never_evaluate_to_null():
    """The bug that broke the partition. A predicate that can be NULL
    cannot be safely negated, and `men` negates `women`."""
    for sql in (A._LANDING_PAGE_WOMEN_SQL, A._LANDING_PAGE_MEN_SQL):
        assert "COALESCE(substring(" in sql, "tag subquery is not NULL-collapsed"
        assert "), FALSE)" in sql
    # And a NULL path still has to land somewhere, so `other` keeps its
    # own COALESCE for the same reason page_type's version does.
    assert A._LANDING_PAGE_GENDER_OTHER_SQL.startswith("COALESCE(NOT (")
    assert A._LANDING_PAGE_GENDER_OTHER_SQL.endswith(", TRUE)")


def test_buckets_partition_on_a_real_sqlite_table():
    """Every page lands in exactly one bucket, so the three counts add
    up to the unfiltered total -- the property that silently failed."""
    db = sqlite3.connect(":memory:")
    db.create_function("regexp", 2, lambda p, v: 1 if v is not None and re.search(p, v) else 0)
    db.execute("CREATE TABLE lp(path TEXT, sessions INT)")
    rows = ([(p, 10) for p in WOMEN_PATHS] + [(p, 20) for p in MEN_PATHS]
            + [(p, 30) for p in NEITHER_PATHS] + [(None, 40)])
    db.executemany("INSERT INTO lp VALUES (?,?)", rows)

    # Build the three predicates in sqlite's regexp(pattern, value) form.
    def pat(key: str) -> str:
        return re.search(r"~ '(.*)'$", A._LANDING_PAGE_GENDER_SLUG[key]).group(1)

    women = f"COALESCE(regexp('{pat('women')}', path), 0) = 1"
    men_raw = f"COALESCE(regexp('{pat('men')}', path), 0) = 1"
    buckets = {
        "women": women,
        "men": f"NOT ({women}) AND ({men_raw})",
        "other": f"NOT (({women}) OR ({men_raw}))",
    }
    total_pages, total_sessions = db.execute(
        "SELECT COUNT(*), SUM(sessions) FROM lp").fetchone()
    pages = sessions = 0
    for name, where in buckets.items():
        n, s = db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(sessions),0) FROM lp WHERE {where}").fetchone()
        pages += n
        sessions += s
    assert pages == total_pages, f"{pages} bucketed vs {total_pages} rows"
    assert sessions == total_sessions
    db.close()


def test_tag_match_is_anchored_not_a_substring():
    """`LIKE '%men%'` would pull back every "women ..." tag and put the
    trap straight back in through the tag lookup."""
    sql = A._landing_page_gender_tag_sql("men")
    assert "lower(t) = 'men'" in sql
    assert "lower(t) LIKE 'men %'" in sql
    assert "'%men%'" not in sql
    assert "p.handle IS NOT NULL" in sql


def test_tag_lookup_only_applies_to_product_pages():
    """A collection handle must never be matched against the product
    table -- the two namespaces overlap (there is a `cotton-trousers`
    collection and could be a product of the same handle)."""
    assert "'^/products/([^/?#]+)'" in A._landing_page_gender_tag_sql("women")
