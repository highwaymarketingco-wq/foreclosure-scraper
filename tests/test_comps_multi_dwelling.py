"""Multi-dwelling "investment property" comp exclusion (enrichment_comps.py).

Confirmed live example (2026-10-04): 140 Old Leicester Rd, Asheville NC --
HomeHarvest's `style` stays SINGLE_FAMILY and combined sqft=1529, but the
real listing `text` (captured live, see enrichment_gis_sale_crosscheck.py's
module docstring and tests/test_gis_sale_crosscheck.py) says:

    "...two separate dwellings: a 1940s bungalow and a single-wide mobile
    home..."

Neither dwelling alone is anywhere near 1529 sqft, so this listing should
never be used as a same-kind single-family comp when enough clean
alternatives exist. No structured field distinguishes this from an ordinary
single-family sale -- only the free listing text does, so the filter is
precision-first: narrow, unambiguous phrasing only, and it must never starve
a thin comp pool below 3.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_comps import (
    _is_multi_dwelling_listing,
    _pick_3_comps,
    _pick_3_rent_comps,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# The real, live-captured 140 Old Leicester Rd listing text (2026-10-04).
REAL_MULTI_DWELLING_TEXT = (
    "Income-Generating Potential Near Asheville! This property offers a rare "
    "opportunity for investors with two separate dwellings: a 1940s bungalow "
    "and a single-wide mobile home, both ripe for renovation and poised to "
    "generate excellent rental income. Situated on a picturesque 1.88-acre "
    "parcel graced by a beautiful creek..."
)


def _subj(**kw) -> Listing:
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Buncombe",
        city="Asheville", zip_code="28804",
        living_sqft=1500, bedrooms=3, year_built=1960,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def _comp(street, **kw) -> dict:
    d = dict(street=street, city="Asheville", zip_code="28804", sold_price=400000,
              sqft=1500, beds=3, full_baths=2, year_built=1960,
              last_sold_date="2026-05-01", style="SINGLE_FAMILY", text="")
    d.update(kw)
    return d


# ---- detector itself --------------------------------------------------------

def test_detects_the_real_140_old_leicester_text():
    assert _is_multi_dwelling_listing({"text": REAL_MULTI_DWELLING_TEXT}) is True


def test_ordinary_description_is_not_flagged():
    assert _is_multi_dwelling_listing({
        "text": "Charming 3 bed 2 bath single-family home with updated "
                "kitchen, hardwood floors, and a cozy screened porch."
    }) is False


def test_mere_mention_of_guest_or_cottage_alone_does_not_trigger():
    """Precision guard: a loose single-word match ('guest', 'cottage') must
    not fire -- e.g. 'guest room' or a cottage-style single dwelling."""
    assert _is_multi_dwelling_listing({
        "text": "Cottage-style single family home with a guest room off the kitchen."
    }) is False


def test_empty_or_missing_text_is_not_flagged():
    assert _is_multi_dwelling_listing({}) is False
    assert _is_multi_dwelling_listing({"text": None}) is False


def test_detects_common_adu_phrasing():
    assert _is_multi_dwelling_listing(
        {"text": "Main house plus a detached guest house, both move-in ready."}
    ) is True
    assert _is_multi_dwelling_listing(
        {"text": "Rare find with an accessory dwelling unit (ADU) in the backyard."}
    ) is True


# ---- wired into the comp matcher -------------------------------------------

def test_multi_dwelling_comp_excluded_when_enough_clean_comps_remain():
    subj = _subj()
    pool = [
        _comp("1 Clean St"),
        _comp("2 Clean St"),
        _comp("3 Clean St"),
        _comp("4 Suspect Rd", text=REAL_MULTI_DWELLING_TEXT, sqft=1529, sold_price=140000),
    ]
    comps = _pick_3_comps(subj, pool)
    addrs = {c["address"] for c in comps}
    assert "4 Suspect Rd" not in addrs
    assert all(c["multi_dwelling_suspected"] is False for c in comps)
    assert "+single_dwelling" in comps[0]["match_quality"]


def test_multi_dwelling_comp_kept_when_pool_too_thin_without_it():
    """Never starve a thin pool on a text guess alone -- mirrors the
    condition-tier filter's existing 'keep all if <3 would remain' rule."""
    subj = _subj()
    pool = [
        _comp("1 Clean St"),
        _comp("4 Suspect Rd", text=REAL_MULTI_DWELLING_TEXT, sqft=1529, sold_price=140000),
    ]
    comps = _pick_3_comps(subj, pool)
    addrs = {c["address"] for c in comps}
    assert "4 Suspect Rd" in addrs
    flagged = [c for c in comps if c["address"] == "4 Suspect Rd"][0]
    assert flagged["multi_dwelling_suspected"] is True
    assert "+single_dwelling" not in flagged["match_quality"]


def test_rent_comps_also_exclude_multi_dwelling_when_enough_remain():
    subj = _subj()
    pool = [
        _comp("1 Clean St", list_price=1800),
        _comp("2 Clean St", list_price=1850),
        _comp("3 Clean St", list_price=1900),
        _comp("4 Suspect Rd", text=REAL_MULTI_DWELLING_TEXT, list_price=2500, sqft=1529),
    ]
    rents = _pick_3_rent_comps(subj, pool)
    addrs = {r["address"] for r in rents}
    assert "4 Suspect Rd" not in addrs
