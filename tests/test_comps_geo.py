"""Geographic comp-accuracy guard.

Owner complaint 2026-06-16: comps were inaccurate — a rural subject was
being valued against county-seat sales 20+ miles away because the matcher
fell back to "kind only" with no geographic anchor. Fix: when the subject
has coordinates, comps must be within COMP_RADIUS_MILES; and county-wide
"kind only" comps are flagged geo_anchored=False so they don't drive ARV.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_comps import (
    COMP_RADIUS_MILES,
    _haversine_miles,
    _pick_3_comps,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _subj(**kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state="SC", county="Spartanburg",
        living_sqft=1500, first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def _comp(street, lat, lon, **kw):
    d = dict(street=street, city="Spartanburg", zip_code="29307", latitude=lat,
             longitude=lon, sold_price=200000, sqft=1500, beds=3,
             last_sold_date="2026-05-01", style="Single Family")
    d.update(kw)
    return d


def test_haversine_known_distance():
    # Spartanburg SC -> Greenville SC is ~27 miles
    d = _haversine_miles(34.9496, -81.9320, 34.8526, -82.3940)
    assert 24 < d < 30


def test_far_comp_excluded_when_subject_has_coords():
    subj = _subj(latitude=34.95, longitude=-81.93)
    pool = [
        _comp("1 Near St", 34.96, -81.92),                        # ~0.9 mi
        _comp("2 Near St", 34.94, -81.95),                        # ~1.3 mi
        _comp("99 Far Rd", 35.30, -82.30, city="Faraway", zip_code="29999"),  # ~30 mi
    ]
    comps = _pick_3_comps(subj, pool)
    addrs = {c["address"] for c in comps}
    assert "99 Far Rd" not in addrs
    assert {"1 Near St", "2 Near St"} <= addrs
    assert all(c["geo_anchored"] for c in comps)
    assert all(c["distance_mi"] is not None and c["distance_mi"] <= COMP_RADIUS_MILES for c in comps)


def test_comps_sorted_closest_first():
    subj = _subj(latitude=34.95, longitude=-81.93)
    pool = [
        _comp("Farther", 34.99, -81.99),
        _comp("Closest", 34.951, -81.931),
    ]
    comps = _pick_3_comps(subj, pool)
    assert comps[0]["address"] == "Closest"


def test_kind_only_comps_flagged_unanchored():
    """No coords, no zip/city match → comps are county-wide and must be
    flagged so they don't silently drive ARV."""
    subj = _subj(zip_code="00000", city="Nowhere")  # no coords
    pool = [_comp("A", 34.9, -81.9, zip_code="29307", city="Spartanburg")]
    comps = _pick_3_comps(subj, pool)
    assert comps
    assert comps[0]["geo_anchored"] is False
