"""Fannie HomePath address -> current propertyUuid re-resolver.

Pure-logic tests (offline) + one network-gated live re-resolution smoke.
"""
from __future__ import annotations

import os

import pytest

from foreclosure_scraper import enrichment_homepath_uuid as hp
from foreclosure_scraper.models import Listing, ListingType


# --- pure helpers -----------------------------------------------------------

def test_norm_addr_collapses_case_and_punct():
    assert hp._norm_addr("1130 Pegram Crossing") == "1130 pegram crossing"
    assert hp._norm_addr("7518  Prindle Lake Dr.") == "7518 prindle lake dr"
    assert hp._norm_addr(None) == ""


def test_uuid_from_url_extracts_canonical_uuid():
    u = "7313f203-8146-4a23-a5a1-a0a264f2cca5"
    assert hp._uuid_from_url(f"https://homepath.fanniemae.com/property/{u}") == u
    assert hp._uuid_from_url("https://homepath.fanniemae.com/") is None
    assert hp._uuid_from_url(None) is None


def test_bbox_tight_around_point_then_state_then_none():
    tight = hp._bbox_for(35.228, -80.816, "NC")
    assert tight is not None
    sw_lat, sw_lng, ne_lat, ne_lng = tight
    assert sw_lat < 35.228 < ne_lat and sw_lng < -80.816 < ne_lng
    # no coords -> parent state box
    assert hp._bbox_for(None, None, "SC") == hp.STATE_BBOXES["SC"]
    # no coords, no known state -> None
    assert hp._bbox_for(None, None, "TX") is None


def test_match_row_prefers_reoid_over_address():
    rows = [
        {"addressLine1": "1 Main St", "zipCode": "28205",
         "reoId": "3yd-X-1", "mlsId": "1", "propertyUuid": "u1"},
        {"addressLine1": "1 Main St", "zipCode": "28205",
         "reoId": "3yd-X-2", "mlsId": "2", "propertyUuid": "u2"},
    ]
    # address alone is ambiguous (two hits) -> None; reoId disambiguates.
    assert hp._match_row(rows, addr_key="1 main st", zip_code="28205",
                         reo_id=None, mls_id=None) is None
    hit = hp._match_row(rows, addr_key="1 main st", zip_code="28205",
                        reo_id="3yd-X-2", mls_id=None)
    assert hit is not None and hit["propertyUuid"] == "u2"


def test_match_row_by_address_and_zip():
    rows = [
        {"addressLine1": "1130 Pegram Crossing", "zipCode": "28205",
         "propertyUuid": "good"},
        {"addressLine1": "9 Other Rd", "zipCode": "28205", "propertyUuid": "bad"},
    ]
    hit = hp._match_row(rows, addr_key="1130 pegram crossing", zip_code="28205",
                        reo_id=None, mls_id=None)
    assert hit is not None and hit["propertyUuid"] == "good"
    # no match at all
    assert hp._match_row(rows, addr_key="404 nowhere", zip_code=None,
                         reo_id=None, mls_id=None) is None


# --- resolver + batch enrichment (mocked network) ---------------------------

@pytest.mark.asyncio
async def test_resolve_homepath_uuid_matches_feed_row(monkeypatch):
    async def fake_get_json(url, params=None, timeout=30.0):
        assert "search" in url
        return {"properties": [
            {"addressLine1": "1130 Pegram Crossing", "zipCode": "28205",
             "state": "NC", "propertyUuid": "fresh-uuid-123",
             "reoId": "3yd-TRIADNC-1209828", "mlsId": "1209828"},
        ]}
    monkeypatch.setattr(hp, "_get_json", fake_get_json)
    res = await hp.resolve_homepath_uuid(
        "1130 Pegram Crossing", zip_code="28205", state="NC",
        lat=35.228233, lng=-80.81631,
    )
    assert res is not None
    assert res["property_uuid"] == "fresh-uuid-123"
    assert res["source_url"] == "https://homepath.fanniemae.com/property/fresh-uuid-123"


@pytest.mark.asyncio
async def test_enrich_rewrites_stale_but_keeps_live(monkeypatch):
    stale_uuid = "11111111-2222-3333-4444-555555555555"
    stale = Listing(
        source="national.fannie_homepath",
        source_url=f"https://homepath.fanniemae.com/property/{stale_uuid}",
        listing_type=ListingType.REO, state="NC", county="Mecklenburg",
        city="Charlotte", zip_code="28205", street_address="1130 Pegram Crossing",
        latitude=35.228233, longitude=-80.81631,
        case_number=f"fannie-{stale_uuid}",
        raw={"reo_id": "3yd-TRIADNC-1209828", "mls_id": "1209828"},
    )
    live_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    live = Listing(
        source="national.fannie_homepath",
        source_url=f"https://homepath.fanniemae.com/property/{live_uuid}",
        listing_type=ListingType.REO, state="NC", county="Wake",
        street_address="9 Other Rd", latitude=35.8, longitude=-78.6,
        case_number=f"fannie-{live_uuid}",
    )

    async def fake_is_live(uuid, timeout=20.0):
        return uuid == live_uuid  # only the "live" listing's uuid confirms

    async def fake_resolve(address, **kw):
        if "Pegram" in address:
            new = "fedcba98-7654-3210-fedc-ba9876543210"
            return {"property_uuid": new,
                    "source_url": f"https://homepath.fanniemae.com/property/{new}",
                    "row": {}}
        return None

    monkeypatch.setattr(hp, "_uuid_is_live", fake_is_live)
    monkeypatch.setattr(hp, "resolve_homepath_uuid", fake_resolve)

    stats = await hp.enrich_homepath_uuids([stale, live])
    assert stats["checked"] == 2
    assert stats["live"] == 1
    assert stats["re_resolved"] == 1
    # stale got a fresh url + case_number; live untouched
    assert stale.source_url.endswith("fedcba98-7654-3210-fedc-ba9876543210")
    assert stale.case_number == "fannie-fedcba98-7654-3210-fedc-ba9876543210"
    assert live.source_url.endswith(live_uuid)


# --- live smoke (network-gated) ---------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live homepath.fanniemae.com JSON API",
)
async def test_live_resolve_real_address():
    """Pull one real current listing from the feed, then re-resolve it by
    address and confirm we recover the SAME uuid."""
    data = await hp._get_json(
        hp.SEARCH_API, params={"bounds": "35.0,-81.2,35.4,-80.6"}
    )
    assert isinstance(data, dict)
    rows = [p for p in (data.get("properties") or []) if p.get("propertyUuid")]
    assert rows, "no live HomePath rows returned"
    p = rows[0]
    geo = p.get("geoPoint") or {}
    res = await hp.resolve_homepath_uuid(
        p["addressLine1"], zip_code=p.get("zipCode"), state=p.get("state"),
        lat=geo.get("latitude"), lng=geo.get("longitude"),
        reo_id=p.get("reoId"), mls_id=p.get("mlsId"),
    )
    assert res is not None
    assert res["property_uuid"] == p["propertyUuid"]
    # and the uuid is confirmed live via the detail endpoint
    assert await hp._uuid_is_live(res["property_uuid"]) is True
