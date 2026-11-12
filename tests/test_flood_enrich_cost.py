"""The flood enricher must not re-read zones it already has.

A full run was spending hours re-querying FEMA for every geocoded lead on the
board, one HTTP call per lead, every run — even though a flood zone is a fixed
polygon and raw["flood"] persists. These assert the three savings actually
happen, because "it looks faster" is not evidence.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from foreclosure_scraper import enrichment_flood as fl
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _lead(lat, lon, flood=None) -> Listing:
    now = datetime.utcnow()
    return Listing(
        source="t", source_url="https://example.invalid/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN, state="NC",
        latitude=lat, longitude=lon,
        first_seen=now, last_seen=now,
        raw={"flood": flood} if flood else {},
    )


@pytest.fixture
def counting(monkeypatch):
    """Replace the FEMA call with a counter."""
    calls: list[tuple[float, float]] = []

    async def fake(c, lat, lon):
        calls.append((lat, lon))
        return {"zone": "AE", "sfha_tf": True, "in_sfha": True}

    monkeypatch.setattr(fl, "_query_flood_zone", fake)
    monkeypatch.setattr(fl, "_REFRESH", False)
    return calls


def test_already_tagged_leads_are_not_requeried(counting):
    leads = [_lead(35.5, -82.5, {"zone": "X", "in_sfha": False}),
             _lead(35.6, -82.6)]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 1, "a lead that already had a zone was re-queried"
    assert leads[0].raw["flood"]["zone"] == "X", "existing zone was overwritten"


def test_identical_points_are_queried_once(counting):
    leads = [_lead(35.5, -82.5) for _ in range(25)]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 1, f"same point queried {len(counting)} times"
    assert all(li.raw["flood"]["zone"] == "AE" for li in leads)


def test_nearby_but_distinct_points_are_not_merged(counting):
    """~11 m apart at 4 decimals must stay distinct — merging across a floodway
    edge would tag a property with its neighbour's zone."""
    leads = [_lead(35.50000, -82.50000), _lead(35.50100, -82.50100)]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 2


def test_ungeocoded_leads_are_skipped(counting):
    leads = [_lead(None, None), _lead(35.5, -82.5)]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 1


def test_refresh_env_forces_a_rewrite(counting, monkeypatch):
    monkeypatch.setattr(fl, "_REFRESH", True)
    leads = [_lead(35.5, -82.5, {"zone": "X", "in_sfha": False})]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 1
    assert leads[0].raw["flood"]["zone"] == "AE"


def test_a_realistic_board_collapses_to_few_requests(counting):
    """5,000 leads across 50 buildings is 50 requests, not 5,000."""
    leads = [_lead(35.0 + (i % 50) / 1000, -82.0 - (i % 50) / 1000)
             for i in range(5000)]
    asyncio.run(fl.enrich_with_flood(leads))
    assert len(counting) == 50, f"expected 50 distinct points, got {len(counting)}"
