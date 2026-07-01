"""Helene same-parcel dedup — a multi-building complex is inspected per-structure
but is ONE owner/outreach target, so it should collapse to one lead carrying the
most-severe placard + a damaged-building count."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from resolve_geo_only import dedup_helene_by_parcel  # noqa: E402

from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _hel(parcel, desc, owner="ACME LLC", county="Buncombe"):
    return Listing(source="counties_nc.asheville_helene", source_url="u",
                   listing_type=ListingType.DISTRESSED, state="NC", county=county,
                   parcel_id=parcel, owner_name=owner, description=desc,
                   latitude=35.5, longitude=-82.5)


def test_collapses_same_parcel_keeps_worst_placard():
    leads = [
        _hel("P1", "Helene damage: Restricted placard - 40% (Commercial)"),
        _hel("P1", "Helene damage: Unsafe placard - 90% (Commercial)"),      # worst
        _hel("P1", "Helene damage: Restricted placard - 50% (Commercial)"),
        _hel("P2", "Helene damage: Restricted placard - 20% (Residential)"),  # lone, untouched
    ]
    removed = dedup_helene_by_parcel(leads)
    assert removed == 2
    assert len(leads) == 2
    kept = [l for l in leads if l.parcel_id == "P1"][0]
    assert kept.raw["helene"] == {
        "damaged_buildings": 3, "worst_placard": "Unsafe", "worst_damage_pct": 90.0,
    }
    # the lone P2 is left exactly as-is (no helene meta)
    lone = [l for l in leads if l.parcel_id == "P2"][0]
    assert "helene" not in (lone.raw or {})


def test_ties_break_on_damage_pct():
    leads = [
        _hel("P3", "Helene damage: Restricted placard - 30%"),
        _hel("P3", "Helene damage: Restricted placard - 70%"),  # same rank, higher %
    ]
    dedup_helene_by_parcel(leads)
    assert len(leads) == 1
    assert leads[0].raw["helene"]["worst_damage_pct"] == 70.0


def test_ignores_other_sources_and_parcel_less():
    other = Listing(source="counties_nc.other", source_url="u",
                    listing_type=ListingType.FORECLOSURE_SALE, state="NC",
                    county="Buncombe", parcel_id="P1", owner_name="X")
    parcelless = _hel(None, "Helene damage: Unsafe placard - 80%")
    leads = [other, parcelless, _hel("P4", "Helene damage: Unsafe placard - 10%")]
    removed = dedup_helene_by_parcel(leads)
    assert removed == 0
    assert len(leads) == 3  # nothing dropped (no same-parcel helene dupes)
