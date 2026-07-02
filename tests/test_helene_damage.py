"""Hurricane Helene structural-damage enrichment.

Unit tests use a monkeypatched _fetch_layer so they run offline; the join,
worst-damage collision handling, county gating, and schema stamping are all
exercised against synthetic rows shaped like the real ArcGIS attributes.

There is also an opt-in live smoke test (RUN_LIVE=1) that hits the real
Spartanburg layer to confirm the endpoint + field names haven't drifted.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_helene_damage as mod


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(
        source="test",
        source_url="https://example.test",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=now,
        last_seen=now,
    )
    base.update(kw)
    return Listing(**base)


# Synthetic rows mirroring the LIVE attribute names of each layer.
_SPART_PALMETTO_ROWS = [
    {"Parcel_ID": "7-09-15-013.00", "Address": "137 HILLBROOK DR",
     "Building_Damage": "Minor Damage", "Estimated_Loss": 83050,
     "Occupancy_type": "owned", "Structure_Type": "Single Family",
     "Zip_Code": "29307"},
    # Same parcel, worse severity — worst must win on collision.
    {"Parcel_ID": "7-09-15-013.00", "Address": "137 HILLBROOK DR",
     "Building_Damage": "Destroyed", "Estimated_Loss": 169100,
     "Occupancy_type": "owned", "Structure_Type": "Single Family",
     "Zip_Code": "29307"},
]
_HENDERSON_ROWS = [
    {"PARCELID": "U-03-29-17-0CB-000000-00030.0", "TYPDAMAGE": "Major",
     "STRLOSS": 154669, "HOMETYPE": "Detached Home"},
]


def _patch(monkeypatch, mapping):
    """mapping: source_key -> list[rows]. Any key not present returns []."""
    async def fake_fetch(c, src):
        return mapping.get(src["key"], [])
    monkeypatch.setattr(mod, "_fetch_layer", fake_fetch)


def test_parcel_join_stamps_worst_damage(monkeypatch):
    _patch(monkeypatch, {"spartanburg_palmetto": _SPART_PALMETTO_ROWS})
    li = _lead(county="Spartanburg", state="SC", parcel_id="7-09-15-013.00")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 1
    assert stats["matched_parcel"] == 1
    sd = li.raw["storm_damage"]
    assert sd["damage_level"] == "Destroyed"          # worst-of-collision won
    assert sd["estimated_loss"] == 169100.0
    assert sd["occupancy"] == "owned"
    assert sd["match_method"] == "parcel"
    assert "Spartanburg" in sd["source"]


def test_address_join_when_no_parcel(monkeypatch):
    _patch(monkeypatch, {"spartanburg_palmetto": _SPART_PALMETTO_ROWS})
    li = _lead(county="Spartanburg", state="SC",
               street_address="137 Hillbrook Drive")  # suffix differs on purpose
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 1
    assert stats["matched_address"] == 1
    assert li.raw["storm_damage"]["match_method"] == "address"
    assert li.raw["storm_damage"]["damage_level"] == "Destroyed"


def test_henderson_parcel_only(monkeypatch):
    _patch(monkeypatch, {"henderson_damage_2024": _HENDERSON_ROWS})
    li = _lead(county="Henderson", state="NC",
               parcel_id="U-03-29-17-0CB-000000-00030.0")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 1
    sd = li.raw["storm_damage"]
    assert sd["damage_level"] == "Major"
    assert sd["estimated_loss"] == 154669.0
    assert sd["occupancy"] == "Detached Home"


def test_buncombe_derives_level_from_service(monkeypatch):
    rows = [{"pin": "0605073289", "Address": "398 SUGAR HOLLOW RD",
             "What_Service_are_you_Requesting": "Demo",
             "Was_this_Property_Residential_o": "Residential",
             "Status": "Inspection Completed", "Zipcode": "28730"}]
    _patch(monkeypatch, {"buncombe_ppdr": rows})
    li = _lead(county="Buncombe", state="NC", parcel_id="0605073289")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 1
    assert li.raw["storm_damage"]["damage_level"] == "Demolition Requested"
    assert li.raw["storm_damage"]["occupancy"] == "Residential"


def test_no_match_leaves_lead_untouched(monkeypatch):
    _patch(monkeypatch, {"spartanburg_palmetto": _SPART_PALMETTO_ROWS})
    li = _lead(county="Spartanburg", state="SC", parcel_id="9999999999")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 0
    assert "storm_damage" not in li.raw


def test_wrong_county_does_not_cross_match(monkeypatch):
    # A Greenville lead must not pick up a Spartanburg parcel even if the
    # normalized parcel string happened to collide.
    _patch(monkeypatch, {"spartanburg_palmetto": _SPART_PALMETTO_ROWS})
    li = _lead(county="Greenville", state="SC", parcel_id="7091513000")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 0
    assert "storm_damage" not in li.raw


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "1")
    called = {"n": 0}
    async def fake_fetch(c, src):
        called["n"] += 1
        return _SPART_PALMETTO_ROWS
    monkeypatch.setattr(mod, "_fetch_layer", fake_fetch)
    li = _lead(county="Spartanburg", state="SC", parcel_id="7091513000")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 0
    assert called["n"] == 0  # never even fetched


def test_source_skipped_when_county_absent(monkeypatch):
    # Only a Buncombe lead present -> Spartanburg/Henderson sources must not fetch.
    fetched = []
    async def fake_fetch(c, src):
        fetched.append(src["key"])
        return []
    monkeypatch.setattr(mod, "_fetch_layer", fake_fetch)
    li = _lead(county="Buncombe", state="NC", parcel_id="0605073289")
    asyncio.run(mod.enrich_with_helene_damage([li]))
    assert fetched == ["buncombe_ppdr"]


@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live_spartanburg_endpoint():
    """Hits the real Spartanburg Palmetto layer to catch schema/endpoint drift."""
    from foreclosure_scraper.http_client import client

    async def run():
        src = next(s for s in mod.SOURCES if s["key"] == "spartanburg_palmetto")
        async with client(timeout=40.0) as c:
            rows = await mod._fetch_layer(c, src)
        assert len(rows) > 100, f"expected hundreds of rows, got {len(rows)}"
        recs = [mod._build_record(src, r) for r in rows]
        recs = [r for r in recs if r]
        assert any(r["damage_level"] for r in recs)
        assert any(r["estimated_loss"] for r in recs)
        return len(rows)

    n = asyncio.run(run())
    print(f"live Spartanburg Palmetto rows={n}")
