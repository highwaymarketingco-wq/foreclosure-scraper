"""Hurricane Helene structural-damage enrichment.

Unit tests use a monkeypatched _fetch_layer so they run offline; the join,
worst-damage collision handling, county gating, and schema stamping are all
exercised against synthetic rows shaped like the real ArcGIS attributes.

There is also an opt-in live smoke test (RUN_LIVE=1) that hits the real
Spartanburg layer to confirm the endpoint + field names haven't drifted.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
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
    assert fetched == ["buncombe_ppdr", "buncombe_placards", "buncombe_accela_damage"]


# --------------------------------------------------------------------------
# Buncombe ATC-45 placards + Accela damage parcels (added 2026-08-03)
# --------------------------------------------------------------------------

_PLACARD_ROWS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures"
     / "buncombe_helene_placards.json").read_text())
_ACCELA_ROWS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures"
     / "buncombe_accela_helene_damage.json").read_text())


def _first(rows, **match):
    for r in rows:
        if all(r.get(k) == v for k, v in match.items()):
            return r
    raise AssertionError(f"fixture has no row matching {match}")


def test_placard_stamps_posting_and_substantial_damage(monkeypatch):
    row = _first(_PLACARD_ROWS, substantial_damage_determinatio="yes")
    _patch(monkeypatch, {"buncombe_placards": [row]})
    li = _lead(county="Buncombe", state="NC", parcel_id=row["pinnum"])
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 1
    sd = li.raw["storm_damage"]
    assert sd["source_key"] == "buncombe_placards"
    assert sd["placard"] in ("red", "yellow", "green")
    # The FEMA 50%-rule finding is the whole point of this layer.
    assert sd["substantial_damage"] is True
    assert sd["match_method"] == "parcel"


def test_placard_substantial_damage_outranks_a_bare_red(monkeypatch):
    """A yellow-placard structure found >=50% damaged must beat a plain red
    placard from another layer on the same parcel."""
    pin = "9611111111"
    yellow_sub = {"pinnum": pin, "structure_address": "1 TEST RD", "posting": "yellow",
                  "structure_type": "residence", "primary_occupancy_type": "Single family",
                  "substantial_damage_determinatio": "yes"}
    red_plain = {"pinnum": pin, "structure_address": "1 TEST RD", "posting": "red",
                 "structure_type": "residence", "primary_occupancy_type": "Single family",
                 "substantial_damage_determinatio": "no"}
    _patch(monkeypatch, {"buncombe_placards": [red_plain, yellow_sub]})
    li = _lead(county="Buncombe", state="NC", parcel_id=pin)
    asyncio.run(mod.enrich_with_helene_damage([li]))
    assert li.raw["storm_damage"]["placard"] == "yellow"
    assert li.raw["storm_damage"]["substantial_damage"] is True


def test_placard_access_point_rows_are_not_structures(monkeypatch):
    """The layer holds a few road/access rows whose 'posting' is not an
    ATC-45 placard; they carry no seller signal and must be dropped."""
    row = {"pinnum": "9612222222", "structure_address": "2 TEST RD",
           "posting": "access point - open", "structure_type": None,
           "primary_occupancy_type": None}
    _patch(monkeypatch, {"buncombe_placards": [row]})
    li = _lead(county="Buncombe", state="NC", parcel_id="9612222222")
    stats = asyncio.run(mod.enrich_with_helene_damage([li]))
    assert stats["matched"] == 0
    assert "storm_damage" not in li.raw


def test_placard_padded_pin_joins_the_board_form(monkeypatch):
    """Placard pinnum is the 15-digit padded PIN; board leads carry both the
    padded and the bare 10-digit form."""
    row = {"pinnum": "968914245000000", "structure_address": "875 Warren Wilson Road",
           "posting": "red", "structure_type": "commercial",
           "primary_occupancy_type": "B", "substantial_damage_determinatio": "no"}
    _patch(monkeypatch, {"buncombe_placards": [row]})
    bare = _lead(county="Buncombe", state="NC", parcel_id="9689142450")
    padded = _lead(county="Buncombe", state="NC", parcel_id="968914245000000")
    stats = asyncio.run(mod.enrich_with_helene_damage([bare, padded]))
    assert stats["matched"] == 2


def test_accela_destroyed_outranks_a_green_placard(monkeypatch):
    destroyed = _first(_ACCELA_ROWS, DamageType="NATURAL DISASTER - DESTROYED")
    pin = destroyed["pin"]
    green = {"pinnum": pin, "structure_address": "3 TEST RD", "posting": "green",
             "structure_type": "residence", "primary_occupancy_type": "Single family",
             "substantial_damage_determinatio": "no"}
    _patch(monkeypatch, {"buncombe_accela_damage": [destroyed],
                         "buncombe_placards": [green]})
    li = _lead(county="Buncombe", state="NC", parcel_id=pin)
    asyncio.run(mod.enrich_with_helene_damage([li]))
    sd = li.raw["storm_damage"]
    assert sd["source_key"] == "buncombe_accela_damage"
    assert sd["damage_level"] == "NATURAL DISASTER - DESTROYED"


def test_accela_damage_types_are_all_ranked():
    """An unranked DamageType silently scores 0 and loses every collision."""
    for row in _ACCELA_ROWS:
        assert mod._rank(row["DamageType"]) > 0, row["DamageType"]


def test_accela_layer_paginates_with_an_explicit_sort():
    """Accela/MapServer/7 has objectIdField=null: any resultOffset request 400s
    unless orderByFields is supplied."""
    src = next(s for s in mod.SOURCES if s["key"] == "buncombe_accela_damage")
    assert src.get("order_by")


def test_no_source_requests_a_wildcard_field_list(monkeypatch):
    """The placard layer carries building_contact_info (owner/occupant phone +
    email). outFields must stay enumerated for every source, forever."""
    seen = []

    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"features": []}

    class FakeClient:
        async def get(self, url, params=None, timeout=None):
            seen.append(params)
            return FakeResp()

    for src in mod.SOURCES:
        asyncio.run(mod._fetch_layer(FakeClient(), src))
    assert seen, "no source issued a request"
    for params in seen:
        fields = params["outFields"]
        assert fields and fields != "*"
        assert "building_contact_info" not in fields


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
