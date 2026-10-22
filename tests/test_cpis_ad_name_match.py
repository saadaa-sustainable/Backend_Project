"""Ad name -> master SKU matching must be bounded on non-alphanumerics.

The CPIS section matches an ad to a SKU by looking for the SKU code in
the ad's NAME. Two rules have been tried and both failed, in opposite
directions:

  * bare substring (still used by `cpis_by_sku`, see
    docs/cpis-attribution.md section D) matches `SDFS` inside
    `SDFSK_GRWM_DEC23`, charging Rs 4.36 Cr to SKUs never advertised.

  * `\\y<sku>\\y` avoided that, but Postgres treats `_` as a WORD
    character, so it ALSO rejected `SDFSK_GRWM_DEC23` for `SDFSK` -- the
    ad that SKU is plainly named after. Measured 2026-10-22 over the 30
    days to 2026-10-21 that cost Rs 33,45,795 of matched spend:
    Rs 60,80,028 found against Rs 94,25,823 available.

Bounding explicitly on `[^A-Za-z0-9]` keeps the collision guard and
recovers the underscore case. These tests pin both halves so neither
regression can come back silently.

The regex is duplicated across five sites in analytics.py (three in SQL,
two built in Python). PATTERN below must stay identical to them.
"""
import re

import pytest

#: Must match analytics.py's `name_ads_join`, the `matched` CTE, the
#: `asset_sku` join, and the two `_re.escape`-built regexes.
PATTERN = r"(^|[^A-Za-z0-9])%s([^A-Za-z0-9]|$)"


def matches(ad_name: str, sku: str) -> bool:
    return re.search(PATTERN % re.escape(sku), ad_name, re.IGNORECASE) is not None


@pytest.mark.parametrize("ad_name,sku", [
    # The underscore case the \y form lost. This is the whole point.
    ("SDFSK_GRWM_DEC23", "SDFSK"),
    ("SDCP_OFF_FL_916_ITE-Feb-25", "SDCP"),
    ("CLP-SDAMK+MU+NA+IHP+SDVSK_VRP", "SDVSK"),
    # Separators the \y form already handled; must keep working.
    ("SDFSK+SDFLK", "SDFSK"),
    ("SDFSK+SDFLK", "SDFLK"),
    ("SDCP-Oct-Reel", "SDCP"),
    # Boundaries at the very start and end of the string.
    ("SDCP", "SDCP"),
    ("Reel-SDCP", "SDCP"),
    ("SDCP-Reel", "SDCP"),
    # Case-insensitive, as `~*` is.
    ("sdcp_oct_reel", "SDCP"),
])
def test_bounded_sku_matches(ad_name, sku):
    assert matches(ad_name, sku)


@pytest.mark.parametrize("ad_name,sku,why", [
    # THE COLLISION GUARD. `SDFS` and `SDFSK` are both real master SKUs
    # and the first is a prefix of the second, so a bare substring match
    # credits SDFS for every SDFSK ad.
    ("SDFSK_GRWM_DEC23", "SDFS", "SDFS is a prefix of SDFSK"),
    ("SDFSKBL_GRWM_DEC23", "SDFS", "prefix, with a colour code too"),
    ("SDCPBL-Reel", "SDCP", "colour code: deliberately not matched"),
    ("SMCPBL-Reel-Oct", "SMCP", "colour code: deliberately not matched"),
    ("Nothing-Here", "SDCP", "absent"),
    ("XSDCPX", "SDCP", "embedded in a longer token"),
])
def test_unbounded_sku_does_not_match(ad_name, sku, why):
    assert not matches(ad_name, sku), why


#: Every master SKU in `cpis_sku_context` that is a substring of another
#: master SKU there, with the SKUs it hides inside. Measured against the
#: live catalogue on 2026-10-22 -- these are the only pairs a prefix
#: collision can occur between, and `cpis_sku_context` is the SKU
#: universe the /cpis-utm endpoint pages over.
NESTED_SKUS = {
    "SDAS": ("SDASK", "SDASP"),
    "SDCP": ("SDCPT",),
    "SDCS": ("SDCSP", "SDCSS"),
    "SDFP": ("SDFPK",),
    "SDFS": ("SDFSK",),
    "SDT":  ("SDTJ",),
    "SMLS": ("SMLSS",),
}


@pytest.mark.parametrize("shorter,longer", [
    (short, long_) for short, longs in NESTED_SKUS.items() for long_ in longs
])
def test_nested_master_sku_pairs_never_collide(shorter, longer):
    """An ad named after the LONGER SKU must never credit the shorter one."""
    for name in (f"{longer}_GRWM_DEC23", f"{longer}-Reel-Oct", f"CLP+{longer}_V2"):
        assert matches(name, longer), f"{longer} should match {name}"
        assert not matches(name, shorter), f"{shorter} must NOT match {name}"


def test_bare_substring_would_have_collided():
    """Documents what the old cpis_by_sku rule does, so the contrast is testable."""
    assert "sdfs" in "SDFSK_GRWM_DEC23".lower()      # the bug
    assert not matches("SDFSK_GRWM_DEC23", "SDFS")   # and the fix
