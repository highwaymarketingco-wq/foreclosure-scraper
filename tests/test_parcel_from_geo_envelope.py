"""NC OneMap situs sanitizing + the envelope fallback's acceptance rule.

Context (verified live 2026-07-27): NC1Map_Parcels answers every
esriGeometryPoint query with HTTP 200 and zero features, statewide, on a layer
holding 5,938,639 parcels. The identical envelope query works, so _point_query
retries as a ~5.5 m box. Network calls are not exercised here — only the pure
guards that decide what we are willing to write onto a lead.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_parcel_from_geo import (
    _clean_nc_situs,
    _ENVELOPE_HALF_DEG,
    _point_query,
)
from foreclosure_scraper.web_artifact import _is_valid_street_address


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Records each query's geometryType and replays a scripted response list."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.seen: list[str] = []

    async def get(self, url, params=None, timeout=None):
        self.seen.append((params or {}).get("geometryType"))
        return _FakeResp(self._payloads.pop(0))


def _feat(parno):
    return {"attributes": {"parno": parno, "cntyname": "Buncombe"}}


# --- envelope fallback ------------------------------------------------------

@pytest.mark.asyncio
async def test_point_hit_short_circuits_without_an_envelope_call():
    c = _FakeClient([{"features": [_feat("111")]}])
    got = await _point_query(c, "http://x/query", 35.5, -82.5)
    assert got["parno"] == "111"
    assert c.seen == ["esriGeometryPoint"]


@pytest.mark.asyncio
async def test_empty_point_falls_back_to_envelope():
    c = _FakeClient([{"features": []}, {"features": [_feat("222")]}])
    got = await _point_query(c, "http://x/query", 35.5, -82.5)
    assert got["parno"] == "222"
    assert c.seen == ["esriGeometryPoint", "esriGeometryEnvelope"]


@pytest.mark.asyncio
async def test_ambiguous_envelope_is_rejected():
    """A box straddling a boundary matches several parcels. Taking features[0]
    would write a neighbour's parcel onto the lead — worse than no answer."""
    c = _FakeClient([{"features": []}, {"features": [_feat("222"), _feat("333")]}])
    assert await _point_query(c, "http://x/query", 35.5, -82.5) is None


@pytest.mark.asyncio
async def test_arcgis_error_does_not_trigger_a_second_call():
    """ArcGIS reports failure as HTTP 200 + `error` (SCDOT now answers
    'Token Required' that way). Retrying with an envelope just burns a request
    against a layer that is refusing us outright."""
    c = _FakeClient([{"error": {"code": 499, "message": "Token Required"}}])
    assert await _point_query(c, "http://x/query", 35.5, -82.5) is None
    assert c.seen == ["esriGeometryPoint"]


@pytest.mark.asyncio
async def test_envelope_box_is_built_around_the_point():
    captured = {}

    class _C(_FakeClient):
        async def get(self, url, params=None, timeout=None):
            if (params or {}).get("geometryType") == "esriGeometryEnvelope":
                captured["geometry"] = params["geometry"]
                captured["count"] = params.get("resultRecordCount")
            return await super().get(url, params=params, timeout=timeout)

    c = _C([{"features": []}, {"features": []}])
    await _point_query(c, "http://x/query", 35.5, -82.5)
    import json
    env = json.loads(captured["geometry"])
    d = _ENVELOPE_HALF_DEG
    assert env["xmin"] == pytest.approx(-82.5 - d)
    assert env["xmax"] == pytest.approx(-82.5 + d)
    assert env["ymin"] == pytest.approx(35.5 - d)
    assert env["ymax"] == pytest.approx(35.5 + d)
    assert env["spatialReference"] == {"wkid": 4326}
    assert captured["count"] == 2   # only need "exactly one" vs "several"


def test_envelope_stays_tight_enough_to_land_in_one_parcel():
    """~5.5 m. Measured on 25 live leads: 5e-5 -> 13 unique / 4 ambiguous,
    1e-4 -> 14 unique / 9 ambiguous. Guard against someone widening it."""
    assert _ENVELOPE_HALF_DEG * 111_000 < 10


# --- NC placeholder house numbers -------------------------------------------

def test_99999_sentinel_empties_the_situs_and_parks_the_road():
    out = _clean_nc_situs({"siteadd": "99999 MEADOW  RD", "saddno": "99999 ",
                           "saddstname": " MEADOW  RD"})
    assert out["siteadd"] == ""                     # nothing mailable to write
    assert out["situs_road_only"] == "MEADOW RD"    # context survives
    assert out["situs_no_house_number"] is True
    assert out["saddno"] == ""
    assert out["saddstname"] == "MEADOW RD"


def test_zero_sentinel_empties_the_situs_and_parks_the_road():
    out = _clean_nc_situs({"siteadd": "0 BRUSH CREEK  RD"})
    assert out["siteadd"] == ""
    assert out["situs_road_only"] == "BRUSH CREEK RD"
    assert out["situs_no_house_number"] is True


def test_real_house_numbers_survive():
    out = _clean_nc_situs({"siteadd": "801 BILTMORE  AVE", "saddno": "801"})
    assert out["siteadd"] == "801 BILTMORE AVE"
    assert out["saddno"] == "801"
    assert "situs_road_only" not in out
    assert "situs_no_house_number" not in out


def test_a_genuine_address_is_untouched_end_to_end():
    """104 WHITLEY RD is a real address and must stay one, all the way through
    the board validator."""
    out = _clean_nc_situs({"siteadd": "104  WHITLEY RD", "saddno": "104"})
    assert out["siteadd"] == "104 WHITLEY RD"
    assert _is_valid_street_address(out["siteadd"])


def test_sentinel_without_a_road_stays_invalid():
    """'99999' alone must not become an address; the board validator rejects it."""
    out = _clean_nc_situs({"siteadd": "99999", "saddno": "99999"})
    assert out["siteadd"] == ""
    assert "situs_road_only" not in out
    assert not _is_valid_street_address(out["siteadd"])


def test_sanitizer_copies_and_tolerates_missing_fields():
    src = {"siteadd": "99999 MEADOW RD"}
    assert _clean_nc_situs(src)["siteadd"] == ""
    assert src["siteadd"] == "99999 MEADOW RD"   # caller's dict untouched
    assert "situs_road_only" not in src
    assert _clean_nc_situs({}) == {}
    assert _clean_nc_situs({"siteadd": None})["siteadd"] is None


@pytest.mark.parametrize("siteadd", ["99999 MEADOW  RD", "0 MEADOW RD"])
def test_sentinel_forms_never_yield_a_mailable_address(siteadd):
    """Neither the raw sentinel nor anything the sanitizer leaves behind may
    satisfy the board's 'this is a real street address' test."""
    assert not _is_valid_street_address(siteadd)          # raw form rejected
    out = _clean_nc_situs({"siteadd": siteadd})
    assert not _is_valid_street_address(out["siteadd"])   # sanitized form rejected
    # The road is kept, but as context under its own key — and a bare road is
    # still not something we would put on an envelope.
    assert out["situs_road_only"] == "MEADOW RD"


@pytest.mark.parametrize("siteadd", ["99999 MEADOW  RD", "0 MEADOW RD"])
def test_sentinel_bag_never_writes_a_street_address(siteadd):
    """The real failure mode: enrichment_situs_address reads `siteadd` out of
    raw['gis_attrs_full'] and writes it to li.street_address. A sanitized bag
    must leave the lead address-LESS, so it stays eligible for real resolution
    and is never mailed."""
    from foreclosure_scraper.enrichment_situs_address import apply_situs_address
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe")
    bag = _clean_nc_situs({"siteadd": siteadd, "saddno": siteadd.split(" ")[0],
                           "saddstname": "MEADOW RD", "scity": "ASHEVILLE",
                           "szip": "28806", "parno": "9648-71-5234"})
    assert apply_situs_address(li, bag, addr_field="siteadd") == 0
    assert li.street_address is None


def test_a_real_bag_still_writes_its_address():
    from foreclosure_scraper.enrichment_situs_address import apply_situs_address
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe")
    bag = _clean_nc_situs({"siteadd": "104  WHITLEY RD", "saddno": "104"})
    assert apply_situs_address(li, bag, addr_field="siteadd") >= 1
    assert li.street_address == "104 WHITLEY RD"


def test_a_numberless_road_can_never_checkpoint_a_lead_as_resolved():
    """scripts/resolve_addresses banks 'resolved' FOREVER. A lead whose only
    'address' would have been a numberless road must come back 'failed', so it
    stays eligible for a later, real resolution."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from resolve_addresses import classify_outcome, _snapshot
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", parcel_id="9648-71-5234")
    before = _snapshot(li)
    # The enricher ran and, thanks to the sanitizer, wrote no address at all.
    bag = _clean_nc_situs({"siteadd": "99999 MEADOW RD"})
    from foreclosure_scraper.enrichment_situs_address import apply_situs_address
    apply_situs_address(li, bag, addr_field="siteadd")
    status, _gained, _addr = classify_outcome(before, li)
    assert status == "failed"
    assert li.street_address is None


# --- board-wide validator: sentinel house numbers ---------------------------

@pytest.mark.parametrize("addr", [
    "99999 MEADOW RD",          # NC OneMap (17,788 parcels)
    "99999 HAPPY VALLEY RD",    # live on the board today (Buncombe)
    "0 MEADOW RD",              # NC OneMap (285,716 parcels)
    "0 CEDAR SPRINGS RD SPARTANBURG",   # live on the board today (SC)
    "00 BIG BEAR TRL",
])
def test_validator_rejects_no_house_number_sentinels(addr):
    """These lead with digits, so the house-number rule used to wave them
    through, and the road-suffix rule would re-accept them on the 'RD'."""
    assert not _is_valid_street_address(addr)


@pytest.mark.parametrize("addr", [
    "104 WHITLEY RD",
    "801 BILTMORE AVE",
    "1027 Merrimon Ave",
    "10 Broad St",
    "999 Church St",        # not the sentinel — a real number
    "99999A MEADOW RD",     # not a bare sentinel token
    "SR 1135",              # rural designator forms still accepted
    "US 221 N",
])
def test_validator_still_accepts_real_addresses(addr):
    assert _is_valid_street_address(addr)


# --- the caller keeps the road as provenance, not as an address -------------

@pytest.mark.asyncio
async def test_point_nc_parks_the_road_in_raw_and_writes_no_address():
    from foreclosure_scraper.enrichment_parcel_from_geo import _parcel_from_point_nc
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", latitude=35.5, longitude=-82.5)
    li.raw = {}
    c = _FakeClient([{"features": [{"attributes": {
        "parno": "9648-71-5234", "cntyname": "BUNCOMBE",
        "siteadd": "99999 MEADOW  RD", "saddno": "99999",
        "scity": "ASHEVILLE", "szip": "28806",
    }}]}])
    pid = await _parcel_from_point_nc(c, li)

    assert pid == "9648-71-5234"                    # the parcel still resolves
    assert li.street_address is None                # but no address is invented
    assert li.raw["gis_attrs_full"]["siteadd"] == ""
    road = li.raw["situs_road_only"]
    assert road["road"] == "MEADOW RD"
    assert road["mailable"] is False
    assert road["parcel_id"] == "9648-71-5234"      # pinned to the unique parcel id


@pytest.mark.asyncio
async def test_point_nc_leaves_a_real_situs_alone():
    from foreclosure_scraper.enrichment_parcel_from_geo import _parcel_from_point_nc
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="s", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", latitude=35.5, longitude=-82.5)
    li.raw = {}
    c = _FakeClient([{"features": [{"attributes": {
        "parno": "9648-71-5234", "cntyname": "BUNCOMBE",
        "siteadd": "104  WHITLEY RD", "saddno": "104",
    }}]}])
    await _parcel_from_point_nc(c, li)
    assert li.raw["gis_attrs_full"]["siteadd"] == "104 WHITLEY RD"
    assert "situs_road_only" not in li.raw
