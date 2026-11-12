"""Regression tests for the 2026-09-15 _clean_parcel length-gate bug.

Both enrichment_parcel_from_geo._clean_parcel and enrichment_arcgis._apply_attrs
used to reject any candidate parcel id under 5 characters, on the theory that
"real APNs have meaningful structure." That's false: live-verified against
Cleveland County NC, NC OneMap's `parno` field returns bare ids like '1020'
(4 chars) for real, owned, assessed parcels — a direct _point_query() call
returned {'parno': '1020', 'cntyname': 'Cleveland', 'siteadd': '1702 PATRICK
AVE', 'ownname': 'BROWN BRENDA D', 'parval': 181574.0}. The length gate was
silently discarding every short-format parcel id, board-wide, for any county
using a short numeric parno convention. Parcel-id format varies by county
(bare sequential ints vs. long formatted PINs like '6804-28-5537.00'); length
is not a valid plausibility signal. Only blank/whitespace/placeholder values
("0", "0.0") should be rejected.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_arcgis import _apply_attrs
from foreclosure_scraper.enrichment_parcel_from_geo import _clean_parcel
from foreclosure_scraper.models import Listing, ListingType


# --- enrichment_parcel_from_geo._clean_parcel --------------------------------

def test_clean_parcel_accepts_short_real_ids():
    """The exact Cleveland County case that exposed the bug, plus another
    live-confirmed short id from the same county."""
    assert _clean_parcel("1020") == "1020"
    assert _clean_parcel("6183") == "6183"


def test_clean_parcel_accepts_long_formatted_ids():
    assert _clean_parcel("6804-28-5537.00") == "6804-28-5537.00"
    assert _clean_parcel("9648-71-5234") == "9648-71-5234"


def test_clean_parcel_rejects_blank_and_placeholder_values():
    assert _clean_parcel(None) == ""
    assert _clean_parcel("") == ""
    assert _clean_parcel("   ") == ""
    assert _clean_parcel("0") == ""
    assert _clean_parcel("0.0") == ""


# --- enrichment_arcgis._apply_attrs (address-match path) --------------------

def _confident_listing():
    return Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                    state="NC", county="Cleveland")


def test_apply_attrs_writes_a_short_confident_parcel_id():
    li = _confident_listing()
    filled = _apply_attrs(li, {"_match_confident": True, "parno": "1020"})
    assert li.parcel_id == "1020"
    assert filled >= 1


def test_apply_attrs_still_rejects_placeholder_values():
    li = _confident_listing()
    _apply_attrs(li, {"_match_confident": True, "parno": "0"})
    assert li.parcel_id is None

    li2 = _confident_listing()
    _apply_attrs(li2, {"_match_confident": True, "parno": "   "})
    assert li2.parcel_id is None


def test_apply_attrs_does_not_write_without_match_confidence():
    li = _confident_listing()
    _apply_attrs(li, {"parno": "1020"})
    assert li.parcel_id is None
