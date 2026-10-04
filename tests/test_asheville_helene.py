"""Asheville/Buncombe NC Hurricane Helene damaged-structure placards.

EXTRACTION-COMPLETENESS AUDIT 2026-10-03: the live FeatureServer layer reports
`hasAttachments: True`, and 5 sampled live Unsafe/Restricted objectids each
carried 2-5 real inspection JPEGs via `queryAttachments` /
`{objectid}/attachments/{id}` that the scraper never fetched at all. Fixtures
below mirror the real shapes (objectid/geometry from the feature query,
attachmentGroups from queryAttachments), with coordinates/ids changed from
the live sample.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_nc import asheville_helene as mod

from tests._arcgis_fakes import FakeHttp, FakeResponse

FEATURE_WITH_PHOTOS = {
    "attributes": {
        "objectid": 21, "incident_name": "Helene", "inspect_date": 1729257600000,
        "building_type": "Single Family", "building_primary_occupancy": "Residential",
        "building_damage": "Moderate", "previous_posting": "Unsafe",
        "current_posting": "Restricted", "building_number_res_units": 1,
    },
    "geometry": {"y": 35.5951, "x": -82.5515},
}
FEATURE_NO_PHOTOS = {
    "attributes": {
        "objectid": 22, "incident_name": "Helene", "inspect_date": 1729257600000,
        "building_type": "Single Family", "building_primary_occupancy": "Residential",
        "building_damage": "Severe", "previous_posting": "Unsafe",
        "current_posting": "Unsafe", "building_number_res_units": 1,
    },
    "geometry": {"y": 35.6, "x": -82.55},
}
FEATURE_NO_GEOMETRY = {
    "attributes": {"objectid": 23, "current_posting": "Unsafe"},
    "geometry": {},
}

FEATURE_PAGE = {"features": [FEATURE_WITH_PHOTOS, FEATURE_NO_PHOTOS, FEATURE_NO_GEOMETRY]}

ATTACHMENTS_PAGE = {
    "attachmentGroups": [
        {"parentObjectId": 21, "attachmentInfos": [
            {"id": 12, "contentType": "image/jpeg", "name": "Photos-1.jpg"},
            {"id": 13, "contentType": "image/jpeg", "name": "Photos-2.jpg"},
            {"id": 14, "contentType": "application/pdf", "name": "notes.pdf"},  # not a photo
        ]},
        # objectid 22 deliberately absent -- no attachments for that feature.
    ]
}


def _run_fetch(http) -> list:
    s = mod.AshevilleHeleneDamage()
    original = mod.client
    mod.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        mod.client = original


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


# --------------------------------------------------------------------------- #
# _fetch_attachments
# --------------------------------------------------------------------------- #

def test_attachments_batch_builds_real_photo_urls_and_drops_non_images():
    http = FakeHttp(pages=[ATTACHMENTS_PAGE])
    out = asyncio.run(mod._fetch_attachments(http, [21, 22]))
    assert list(out.keys()) == [21]  # 22 has no attachmentGroup -> not in the map
    assert out[21] == [
        f"{mod._LAYER_BASE}/21/attachments/12",
        f"{mod._LAYER_BASE}/21/attachments/13",
    ]
    # One batched call, not one per objectid.
    assert len(http.calls) == 1
    verb, url, params = http.calls[0]
    assert url == mod._ATTACH_URL
    assert params["objectIds"] == "21,22"


def test_attachments_are_capped_at_max_photos():
    many = {"attachmentGroups": [{"parentObjectId": 1, "attachmentInfos": [
        {"id": i, "contentType": "image/jpeg"} for i in range(20)
    ]}]}
    http = FakeHttp(pages=[many])
    out = asyncio.run(mod._fetch_attachments(http, [1]))
    assert len(out[1]) == mod._MAX_PHOTOS


def test_object_ids_are_chunked_to_keep_query_strings_bounded():
    ids = list(range(1, 301))  # 300 ids, chunk size 150 -> 2 calls
    http = FakeHttp(pages=[{"attachmentGroups": []}, {"attachmentGroups": []}])
    asyncio.run(mod._fetch_attachments(http, ids))
    assert len(http.calls) == 2
    first_ids = http.calls[0][2]["objectIds"].split(",")
    second_ids = http.calls[1][2]["objectIds"].split(",")
    assert len(first_ids) == mod._ATTACH_CHUNK
    assert len(second_ids) == 300 - mod._ATTACH_CHUNK


def test_a_failed_attachments_call_yields_no_photos_not_a_crash():
    http = FakeHttp(routes={mod._ATTACH_URL: FakeResponse({}, status_code=500)})
    out = asyncio.run(mod._fetch_attachments(http, [1, 2]))
    assert out == {}


# --------------------------------------------------------------------------- #
# fetch() -- end to end
# --------------------------------------------------------------------------- #

def test_fetch_wires_real_photos_onto_the_matching_listing_only(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_HELENE", raising=False)
    http = FakeHttp(pages=[FEATURE_PAGE, ATTACHMENTS_PAGE])
    rows = _run_fetch(http)
    # FEATURE_NO_GEOMETRY (objectid 23) has no lat/lng -> dropped, matching
    # existing (pre-fix) behavior; this fix must not change that.
    assert len(rows) == 2
    with_photos = next(l for l in rows if l.raw["helene"]["current_posting"] == "Restricted")
    assert with_photos.raw["images"]["real"] == [
        f"{mod._LAYER_BASE}/21/attachments/12",
        f"{mod._LAYER_BASE}/21/attachments/13",
    ]
    no_photos = next(l for l in rows if l.raw["helene"]["current_posting"] == "Unsafe")
    assert "images" not in no_photos.raw


def test_fetch_still_returns_rows_when_the_attachments_call_fails(monkeypatch):
    """Photos are a bonus; a broken attachments endpoint must not drop real leads."""
    monkeypatch.delenv("FORECLOSURE_HELENE", raising=False)
    http = FakeHttp(pages=[FEATURE_PAGE, {"error": "boom"}])
    rows = _run_fetch(http)
    assert len(rows) == 2
    assert all("images" not in l.raw for l in rows)


def test_env_gate_skips_without_any_network_call(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_HELENE", "0")
    http = FakeHttp(pages=[FEATURE_PAGE, ATTACHMENTS_PAGE])
    assert _run_fetch(http) == []
    assert http.calls == []


# --------------------------------------------------------------------------- #
# wiring guard
# --------------------------------------------------------------------------- #

def test_registered_in_the_scraper_registry():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    assert mod.AshevilleHeleneDamage.slug in slugs


# --------------------------------------------------------------------------- #
# live smoke -- proves the attachments really exist on the real service.
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live_feed_carries_real_photos_on_most_rows():
    s = mod.AshevilleHeleneDamage()
    rows = asyncio.run(s.safe_run())
    assert len(rows) > 100
    with_photos = [l for l in rows if l.raw.get("images", {}).get("real")]
    # Live-confirmed 2026-10-03: 651/652 features carry real photos.
    assert len(with_photos) / len(rows) > 0.9
    for l in with_photos[:3]:
        print(l.raw["helene"]["current_posting"], l.raw["images"]["real"])
