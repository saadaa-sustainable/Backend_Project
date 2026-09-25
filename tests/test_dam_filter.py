"""The DAM count and the DAM filter must be one rule.

An asset the register holds no link for cannot be tested: there is no
file to put in an ad. Counting it in the untested backlog overstates
what anyone can action, and on influencer it dominates -- 12,359 of
14,709 posts carry no link at all.

Measured 2026-09-25 with match_state=all:

    video        1,203 rows    723 in DAM    500 tested /   223 not
    graphic      1,588 rows  1,484 in DAM  1,055 tested /   429 not
    influencer  14,709 rows  2,350 in DAM  1,211 tested / 1,139 not

The tile and the table read the same predicate. If they drift, the card
says 723 while the filtered table shows something else and nothing on
screen explains it.
"""

import inspect
import re

from app.api.routers.analytics import (
    _HAS_LINK,
    UntestedAssetsResponse,
    get_untested_assets,
)


def _source() -> str:
    src = inspect.getsource(get_untested_assets)
    return "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())


def test_empty_string_is_not_a_link():
    """The registers are hand-maintained; a cleared cell arrives as ''
    rather than NULL, so IS NOT NULL alone counts blanks as assets that
    have a file."""
    assert "IS NOT NULL" in _HAS_LINK
    assert "btrim(b.link) <> ''" in _HAS_LINK


def test_filter_and_counts_read_the_same_predicate():
    src = _source()
    # the filter
    assert "outer_filters.append(_HAS_LINK)" in src
    assert 'outer_filters.append(f"NOT {_HAS_LINK}")' in src
    # the counts -- same name, not a second spelling
    assert src.count("_HAS_LINK") >= 4
    assert "b.link IS NOT NULL" not in src, "predicate spelled inline somewhere"


def test_counts_come_from_the_same_base_as_the_rows():
    """Counting off _UNTESTED_COVERAGE_SQL instead would use a query
    that has no normalised `link` column, so the tile and the table
    would be answering different questions."""
    src = _source()
    assert "WITH base AS ({base_select})" in src


def test_counts_ignore_the_row_filters():
    """The tiles describe the register, not the current page. Deriving
    them from the filtered rows is what once made the ad-level category
    tiles read 3 against a real 1,768."""
    src = _source()
    block = src[src.index("cov = (await session.execute"):]
    block = block[:block.index('"""))).one()')]
    assert "where_clause" not in block
    assert "outer_filters" not in block


def test_coverage_and_dam_cost_one_round_trip():
    """This endpoint is pinned at two DB round trips by
    tests/test_untested_loading.py, for the reason this branch exists:
    an extra trip is paid on every load. The DAM split rides along with
    the coverage query rather than adding a third."""
    src = _source()
    assert src.count("await session.execute") == 2
    assert "cov AS (" in src and "dam AS (" in src
    assert "FROM cov CROSS JOIN dam" in src


def test_response_exposes_the_split_and_its_complement():
    f = UntestedAssetsResponse.model_fields
    for name in ("dam_total", "dam_tested", "dam_untested", "without_link"):
        assert name in f, name
        assert f[name].default == 0


def test_has_link_defaults_to_returning_everything():
    sig = inspect.signature(get_untested_assets)
    assert sig.parameters["has_link"].default.default is None
