"""Regression tests for the parcel-centroid reverse-geo enrichment.

Policy under test:
  * Listings with parcel_id + lat/lng + (no/synthetic) street_address
    are reverse-geocoded.
  * The result is annotated to raw.parcel_resolution.reverse_geo_approx.
  * street_address is NEVER overwritten (approximate is not authoritative).
  * Idempotent: a second run with an existing annotation skips that listing.
  * Out-of-area centroids (outside NC+SC bbox) are skipped to avoid noise.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.enrichment_parcel_reverse_geo import (
    _has_useful_centroid,
    _is_address_less,
    enrich_parcel_reverse_geo,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw):
    base = dict(
        source="counties_nc.nc_ecourts_lis_pendens", source_url="http://x",
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---------- _is_address_less ----------

def test_is_address_less_blank():
    assert _is_address_less(_li(street_address=None)) is True
    assert _is_address_less(_li(street_address="")) is True


def test_is_address_less_synthetic():
    assert _is_address_less(_li(street_address="Lis Pendens 26M-XXX")) is True
    assert _is_address_less(_li(street_address="Vacant parcel 8564")) is True
    assert _is_address_less(_li(street_address="Bk Property X")) is True
    assert _is_address_less(_li(street_address="Tax Sale 123")) is True


def test_is_address_less_real():
    assert _is_address_less(_li(street_address="123 Main St")) is False
    assert _is_address_less(_li(street_address="2718 Toney Road")) is False


# ---------- _has_useful_centroid ----------

def test_useful_centroid_in_carolinas():
    li = _li(parcel_id="X", latitude=35.4, longitude=-81.5)  # Cleveland NC
    assert _has_useful_centroid(li) is True


def test_useful_centroid_no_parcel():
    li = _li(parcel_id=None, latitude=35.4, longitude=-81.5)
    assert _has_useful_centroid(li) is False


def test_useful_centroid_out_of_area():
    li = _li(parcel_id="X", latitude=40.0, longitude=-74.0)  # NJ — out of scope
    assert _has_useful_centroid(li) is False


def test_useful_centroid_null_island():
    li = _li(parcel_id="X", latitude=0.0, longitude=0.0)
    assert _has_useful_centroid(li) is False


# ---------- end-to-end ----------

def test_annotates_raw_does_not_touch_street_address():
    """Bivins-style: parcel found, centroid known, no situs in GIS. The
    enrichment must annotate raw and leave street_address as-is."""
    li = _li(
        state="NC", county="Cleveland",
        case_number="26M000084-220",
        defendant="Bivins, Cynthia K",
        street_address="Lis Pendens 26M000084-220 — Bivins, Cynthia K",
        parcel_id="2641302296",
        latitude=35.40038961,
        longitude=-81.53973716,
    )
    fake_geo = {
        "display_name": "2718, Toney Road, Cleveland County, NC, 28090",
        "address": {
            "house_number": "2718", "road": "Toney Road",
            "county": "Cleveland County", "state": "North Carolina",
            "postcode": "28090",
        },
    }
    with patch(
        "foreclosure_scraper.enrichment_parcel_reverse_geo._reverse_geo",
        new=AsyncMock(return_value=fake_geo),
    ), patch("asyncio.sleep", new=AsyncMock()):
        stats = asyncio.run(enrich_parcel_reverse_geo([li]))

    # street_address must NOT be overwritten
    assert li.street_address == "Lis Pendens 26M000084-220 — Bivins, Cynthia K"
    # raw blob annotated
    pr = li.raw["parcel_resolution"]
    assert pr["reverse_geo_approx"] == "2718, Toney Road, Cleveland County, NC, 28090"
    assert pr["reverse_geo_components"]["road"] == "Toney Road"
    assert "Approximate" in pr["reverse_geo_note"]
    assert stats["queried"] == 1
    assert stats["annotated"] == 1


def test_skips_real_addresses():
    """A listing with a real (non-synthetic) street_address is skipped."""
    li = _li(
        state="NC", county="Cleveland",
        street_address="123 Main St",
        parcel_id="X", latitude=35.4, longitude=-81.5,
    )
    qm = AsyncMock(return_value={"display_name": "should not be called"})
    with patch(
        "foreclosure_scraper.enrichment_parcel_reverse_geo._reverse_geo",
        new=qm,
    ):
        stats = asyncio.run(enrich_parcel_reverse_geo([li]))

    assert qm.await_count == 0
    assert stats["queried"] == 0
    assert "parcel_resolution" not in (li.raw or {})


def test_idempotent_skips_already_annotated():
    """A listing already annotated by a prior run is skipped (idempotent)."""
    li = _li(
        state="NC", county="Cleveland",
        street_address="Lis Pendens X",
        parcel_id="X", latitude=35.4, longitude=-81.5,
        raw={"parcel_resolution": {"reverse_geo_approx": "already done"}},
    )
    qm = AsyncMock(return_value={"display_name": "new result"})
    with patch(
        "foreclosure_scraper.enrichment_parcel_reverse_geo._reverse_geo",
        new=qm,
    ):
        stats = asyncio.run(enrich_parcel_reverse_geo([li]))

    assert qm.await_count == 0
    # Existing annotation is preserved
    assert li.raw["parcel_resolution"]["reverse_geo_approx"] == "already done"
