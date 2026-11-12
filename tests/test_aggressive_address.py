"""Regression tests for the aggressive-address enrichment.

The county-overwrite bug shipped in commit ab1ac38 caused 50+ SC lis
pendens listings to have their case#-pinned county silently rewritten by
a same-name owner match in a different county. The fix in 0857812 +
this commit's strengthening prevents that. These tests guarantee the
fix doesn't regress.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from foreclosure_scraper.enrichment_aggressive_address import (
    _case_pins_county,
    enrich_with_aggressive_address,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _make_listing(**overrides) -> Listing:
    base = dict(
        source="counties_sc.sc_public_index_lis_pendens",
        source_url="http://example.com/x",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(overrides)
    return Listing(**base)


@pytest.mark.parametrize("state,case_number,expected", [
    ("SC", "2026-CP-04-12345", True),    # Anderson
    ("SC", "2026-CP-42-99999", True),    # Spartanburg
    ("SC", "2026-CP-99-00001", False),   # invalid county code
    ("SC", None,                False),  # no case#
    ("SC", "garbage",           False),  # non-matching format
    ("NC", "2026-CP-04-12345",  False),  # NC state — only SC pins
])
def test_case_pins_county(state, case_number, expected):
    li = _make_listing(state=state, case_number=case_number, county="X", defendant="Y")
    assert _case_pins_county(li) is expected


def test_case_pinned_skips_cross_county_scan():
    """A case#-pinned SC lis pendens must NOT have its county rewritten OR
    its address populated from a wrong-county owner match. Tier A is
    skipped entirely; only Tier B (within stated county) runs."""
    li = _make_listing(
        state="SC",
        county="Anderson",
        case_number="2026-CP-04-12345",
        defendant="Smith John",
    )
    a_search = AsyncMock(return_value={
        "OWNER": "SMITH JOHN",
        "_matched_county": "Cherokee",   # WRONG county
        "PROP_ST_NO": "123",
        "PROP_ST_NA": "WRONG STREET",
        "_centroid": (35.0, -82.0),
    })
    b_search = AsyncMock(return_value=None)

    with patch(
        "foreclosure_scraper.enrichment_aggressive_address._aggressive_owner_search",
        new=a_search,
    ), patch(
        "foreclosure_scraper.enrichment_aggressive_address._fuzzy_partial_search",
        new=b_search,
    ):
        asyncio.run(enrich_with_aggressive_address([li]))

    assert a_search.await_count == 0, "Tier A must be skipped for case-pinned listings"
    assert b_search.await_count == 1, "Tier B should still run"
    assert li.county == "Anderson"
    assert li.street_address is None


def test_non_case_pinned_uses_cross_county_scan():
    """Listings without a case-pinning case# (e.g. NC trustee-sale listings)
    still benefit from the cross-county scan behavior."""
    li = _make_listing(
        source="law_firms.brock_scott",
        listing_type=ListingType.FORECLOSURE_SALE,
        state="NC",
        county="Mecklenburg",
        defendant="Jones Mary",
    )
    a_search = AsyncMock(return_value={
        "OwnerName": "JONES MARY",
        "_matched_county": "Buncombe",
        "PropertyLocation": "456 REAL ST",
        "_centroid": (35.5, -82.5),
    })
    b_search = AsyncMock(return_value=None)

    with patch(
        "foreclosure_scraper.enrichment_aggressive_address._aggressive_owner_search",
        new=a_search,
    ), patch(
        "foreclosure_scraper.enrichment_aggressive_address._fuzzy_partial_search",
        new=b_search,
    ):
        asyncio.run(enrich_with_aggressive_address([li]))

    assert a_search.await_count == 1
    assert li.county == "Buncombe"
    assert li.street_address == "456 REAL ST"
