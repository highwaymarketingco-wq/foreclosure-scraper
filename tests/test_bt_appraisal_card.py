"""BT TaxPayer Portal appraisal cards: heated sqft + the RIGHT sale price, 14 NC counties.

This closes the oldest open gap on the project. Single-family heated sqft sits at 13%
coverage, ARV is capped to MEDIUM without it, and ~38% of rows were waiting on a PAID
Zillow-FACTS enricher. These counties publish the assessor's full appraisal card as a
free PDF keyed on the parcel number.

Three separate traps were found building this, all caught by checking rather than
assuming — each has a test below.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_bt_appraisal_card import (
    REJECTED_TENANTS, TENANTS, card_url, parse_card, parse_card_text,
)

#: Verbatim from McDowell parcel 0668-00-82-0841, as pypdf extracts it: every field on
#: its own line. This layout is the whole reason the first sales regex was wrong.
REAL_CARD = """
HEATED AREA 2,100
Bedrooms/Bathrooms/Half-Bathrooms 4/2/0
AYB 2008
SALES DATA
OFF. RECORD
DATE
DEED
INDICATE
BOOK
PAGE
MO
YR
TYPE
Q/U
V/I
SALES PRICE
01342
0402
2
2021
WD
X
I
229,000
00970
0790
8
2008
WD
Q
I
20,000
00964
0020
5
2008
WD
X
V
20,000
00233
0595
1
1973
WD
Q
V
0
TOTAL APPRAISED VALUE - PARCEL 261,870
"""


# ---------------------------------------------------------------------------
# TRAP 1: a tenant code that serves a DIFFERENT county
# ---------------------------------------------------------------------------

def test_only_verified_tenant_codes_are_wired():
    """A source sweep proposed 19 counties. Fetching each landing page and reading the
    county name off it found 14 correct, 5 dead stubs, and ONE ACTIVELY WRONG:
    ITSPublicMA was proposed for MARTIN and the page says PERSON COUNTY. Wiring it would
    have filed Person appraisals against Martin parcels and nothing would have failed --
    the same shape as the code-enforcement endpoint that was the City of Yucaipa, CA."""
    assert len(TENANTS) == 14
    assert TENANTS["Martin"] == "MT", "MA serves Person County, not Martin"
    assert "Martin(MA)" in REJECTED_TENANTS
    for dead in ("Craven", "Graham", "Jones", "Surry", "Gates"):
        assert dead not in TENANTS, f"{dead} returns a stub with no county name"


@pytest.mark.parametrize("county", ["Craven", "Graham", "Jones", "Surry", "Gates", "Wake"])
def test_an_unverified_county_yields_no_url_rather_than_a_guess(county):
    assert card_url(county, "0668-00-82-0841") is None


# ---------------------------------------------------------------------------
# TRAP 2: "McDowell".title() == "Mcdowell"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spelling", ["McDowell", "mcdowell", "MCDOWELL", " McDowell "])
def test_mcdowell_resolves_however_it_is_spelled(spelling):
    """Python's .title() lowercases after the first letter, so a .title() lookup missed
    McDowell -- a FOOTPRINT county, and the one this was first tested against."""
    u = card_url(spelling, "0668-00-82-0841")
    assert u is not None and "/ITSPublicMD/" in u


def test_the_parcel_id_is_stripped_of_punctuation():
    u = card_url("McDowell", "0668-00-82-0841")
    assert "id=066800820841%2f" in u


def test_a_blank_parcel_yields_no_url():
    assert card_url("McDowell", "") is None
    assert card_url("McDowell", "----") is None


# ---------------------------------------------------------------------------
# TRAP 3: the most recent "Q" sale is NOT the market price
# ---------------------------------------------------------------------------

def test_the_most_recent_IMPROVED_sale_wins_not_the_most_recent_Q():
    """THE one that would have poisoned ARV. On this real card the 2021 sale of the house
    for $229,000 carries Q/U = 'X', while the only 'Q' row is a $20,000 transfer from
    2008. Preferring 'Q' picked a 13-year-old figure at a tenth of the real value, and
    that number feeds ARV directly. V/I is the reliable column: I = improved."""
    got = parse_card_text(REAL_CARD)
    assert got["last_sale_price"] == 229000.0
    assert got["last_sale_year"] == 2021
    assert got["last_sale_improved"] is True
    assert got["last_sale_qu_code"] == "X"


def test_every_sale_row_is_parsed_with_its_flags():
    got = parse_card_text(REAL_CARD)
    # the $0 1973 row is dropped: a zero-price transfer is not a sale
    assert len(got["sales"]) == 3
    assert [s["year"] for s in got["sales"]] == [2021, 2008, 2008]
    assert got["sales"][0]["deed_book"] == "01342" and got["sales"][0]["deed_page"] == "0402"


def test_zero_price_transfers_are_not_sales():
    """Family/estate transfers record $0 and would drag any average to nothing."""
    assert all(s["price"] >= 100 for s in parse_card_text(REAL_CARD)["sales"])


def test_a_vacant_only_card_still_reports_its_sale():
    """When there is no improved sale, the most recent sale is better than none."""
    vacant = REAL_CARD.replace("WD\nX\nI\n229,000", "WD\nX\nV\n229,000") \
                      .replace("WD\nQ\nI\n20,000", "WD\nQ\nV\n20,000")
    got = parse_card_text(vacant)
    assert got["last_sale_price"] == 229000.0
    assert got["last_sale_improved"] is False


# ---------------------------------------------------------------------------
# The fields this exists for
# ---------------------------------------------------------------------------

def test_heated_sqft_and_value_are_parsed():
    got = parse_card_text(REAL_CARD)
    assert got["heated_sqft"] == 2100.0
    assert got["appraised_value"] == 261870.0
    assert (got["bedrooms"], got["bathrooms"], got["half_baths"]) == (4, 2, 0)
    assert got["year_built"] == 2008


def test_a_non_card_response_yields_nothing():
    """An error page or an HTML redirect must never look like a parsed card."""
    assert parse_card(b"<html>Not found</html>") == {}
    assert parse_card(b"") == {}
    assert parse_card_text("just some words") == {}
