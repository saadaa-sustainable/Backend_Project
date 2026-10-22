"""Ad name -> master SKU matching: colour-tolerant, longest match wins.

The CPIS section matches an ad to a SKU by looking for the SKU code in
the ad's NAME. Three rules have been tried; the first two were wrong in
opposite directions.

  1. BARE SUBSTRING -- still used by `cpis_by_sku`, see
     docs/cpis-attribution.md section D. Matches `SDFS` inside
     `SDFSK_GRWM_DEC23`, charging Rs 4.36 Cr to SKUs never advertised.

  2. `\\y<sku>\\y` -- avoided that, but Postgres treats `_` as a WORD
     character, so it ALSO rejected `SDFSK_GRWM_DEC23` for `SDFSK`.
     Measured 2026-10-22 over the 30 days to 2026-10-21, that cost
     Rs 33,45,795 of matched spend.

  3. `[^A-Za-z0-9]` bounds, SKU may carry a 0-2 letter COLOUR CODE, and
     when several SKUs match the same ad only the LONGEST of a nested
     family is credited. This is what ships.

Why step 3 needs both halves, measured on the same window:

    SMFSK, bounded only              Rs    93,924   (46% of truth)
    SMFSK, + colour code             Rs 2,04,081   matches Meta exactly
    SDFS,  + colour code, no longest Rs 6,20,266   ALL of SDFSK's spend
    SDFS,  + colour code + longest   Rs         0   correct

Colour tolerance alone misattributes about Rs 12.8 L across the seven
nested SKU families, because `SDFS` + `K` is itself a legal colour code.
The longest-match rule is what makes it safe.

PATTERN and resolve() below mirror the SQL in analytics.py -- the
`matched` CTE, `name_ads_join`, the `asset_sku` join, and the two
`_re.escape`-built regexes behind /cpis/{sku}/ads and the spend-trend
sparkline. All five must agree or a row disagrees with its own
drilldown.
"""
import re

import pytest

#: Mirrors the SQL. Brace-free on purpose: `{0,2}` inside an f-string
#: would be read as a replacement field, and site 1 is an f-string.
PATTERN = r"(^|[^A-Za-z0-9])%s[A-Z]?[A-Z]?([^A-Za-z0-9]|$)"

#: Every master SKU involved in a nesting relationship in the live
#: catalogue on 2026-10-22, plus the SKUs used in the examples below.
#: Not the whole catalogue -- nesting is the only thing that makes
#: resolution non-trivial.
CATALOGUE = {
    "SDAS", "SDASK", "SDASP",
    "SDCP", "SDCPT",
    "SDCS", "SDCSP", "SDCSS",
    "SDFP", "SDFPK",
    "SDFS", "SDFSK",
    "SDT", "SDTJ",
    "SMLS", "SMLSS",
    "SMFSK", "SMCP", "SDFLK", "SDPL", "SDAFD",
}


def candidates(ad_name: str, skus=CATALOGUE) -> set[str]:
    """Every SKU whose code appears in the name, colour code allowed."""
    return {s for s in skus
            if re.search(PATTERN % re.escape(s), ad_name, re.IGNORECASE)}


def resolve(ad_name: str, skus=CATALOGUE) -> set[str]:
    """Candidates minus any that a LONGER matching SKU contains.

    The Python twin of the SQL `NOT EXISTS (... length(o) > length(sku)
    AND position(sku in o) > 0 AND <o also matches> ...)`.
    """
    found = candidates(ad_name, skus)
    return {s for s in found
            if not any(o != s and len(o) > len(s) and s in o for o in found)}


# ---------------------------------------------------------------- colour

@pytest.mark.parametrize("ad_name,sku", [
    # The case the user caught: SMFSK's biggest ads carry a colour code.
    ("PDP-SMFSKEC_IFAD_THESTORYOF RAVI_12/04/2025_H0", "SMFSK"),
    ("SMFSKEC_VRP_RV_1PA-SIF-1997-P1", "SMFSK"),
    # Colour code mid-name, slash-separated.
    ("SMFSKRT/SMCPBE_VRP_GR_1PA-SIF-1391", "SMFSK"),
    ("SMFSKRT/SMCPBE_VRP_GR_1PA-SIF-1391", "SMCP"),
    # Plain colour codes.
    ("SDCPBL-Reel-Oct", "SDCP"),
    ("SMCPBL-Reel-Oct", "SMCP"),
])
def test_colour_code_after_sku_matches(ad_name, sku):
    assert sku in resolve(ad_name)


@pytest.mark.parametrize("ad_name,sku", [
    # The underscore case rule 2 lost.
    ("SDFSK_GRWM_DEC23", "SDFSK"),
    ("SDCP_OFF_FL_916_ITE-Feb-25", "SDCP"),
    ("CLP-SDAMK+MU+NA+IHP+SDFLK_VRP", "SDFLK"),
    # Separators rule 2 already handled.
    ("SDFSK+SDFLK", "SDFSK"),
    ("SDFSK+SDFLK", "SDFLK"),
    # String edges.
    ("SDCP", "SDCP"),
    ("Reel-SDCP", "SDCP"),
    # Case-insensitive, as `~*` is.
    ("sdcp_oct_reel", "SDCP"),
])
def test_bounded_sku_still_matches(ad_name, sku):
    assert sku in resolve(ad_name)


# ------------------------------------------------------- longest match

@pytest.mark.parametrize("ad_name,winner,loser", [
    ("SDFSK_GRWM_DEC23", "SDFSK", "SDFS"),
    ("SDFSKBL_GRWM_DEC23", "SDFSK", "SDFS"),
    ("SDCPT_OFF_916", "SDCPT", "SDCP"),
    ("SDASK-Reel-Oct", "SDASK", "SDAS"),
    ("SDASP_V2", "SDASP", "SDAS"),
    ("SDCSP+MU", "SDCSP", "SDCS"),
    ("SDCSS_X", "SDCSS", "SDCS"),
    ("SDFPK_Y", "SDFPK", "SDFP"),
    ("SDTJ_Z", "SDTJ", "SDT"),
    ("SMLSS_Q", "SMLSS", "SMLS"),
])
def test_longest_sku_wins_within_a_nested_family(ad_name, winner, loser):
    got = resolve(ad_name)
    assert winner in got
    assert loser not in got, (
        f"{loser} must not be credited for an ad named after {winner}")


def test_colour_tolerance_without_longest_match_would_collide():
    """Documents WHY the NOT EXISTS guard exists, not just that it does."""
    # SDFS is a legitimate candidate -- `SDFS` + colour `K` -- and that
    # is exactly the trap. Only the longest-match pass removes it.
    assert "SDFS" in candidates("SDFSK_GRWM_DEC23")
    assert "SDFS" not in resolve("SDFSK_GRWM_DEC23")


def test_multi_sku_ads_keep_every_unrelated_sku():
    """Longest-match must not collapse genuinely different SKUs."""
    assert resolve("SMFSKRT/SMCPBE_VRP") == {"SMFSK", "SMCP"}
    assert resolve("SDFSK+SDFLK") == {"SDFSK", "SDFLK"}


# ------------------------------------------------------------ negatives

@pytest.mark.parametrize("ad_name,sku,why", [
    ("Nothing-Here", "SDCP", "absent"),
    ("XSDCPX", "SDCP", "embedded, no leading boundary"),
    ("SDCPABCD_Y", "SDCP", "more than two trailing letters"),
    ("SDCP123_Y", "SDCP", "digits are not a colour code"),
])
def test_non_matches(ad_name, sku, why):
    assert sku not in resolve(ad_name), why


def test_pattern_is_brace_free():
    """`{0,2}` inside an f-string is a replacement field. Site 1 is an f-string."""
    assert "{" not in PATTERN.replace("%s", "")
