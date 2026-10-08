"""Source-completeness audit 2026-10-09, group D (code enforcement, vacancy, condemned, REO):
parcel ids that validation would null, and coordinates the layers carry but were never read.

Offline. Field names and value shapes are the live layers' (checked 2026-10-08); every name,
street and number below is invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from foreclosure_scraper.scrapers.counties_generic import arcgis_distress_layers as AD
from foreclosure_scraper.scrapers.counties_nc import asheville_str_permits as STR
from foreclosure_scraper.scrapers.counties_nc import nc_metro_demolition_permits as DP
from foreclosure_scraper.scrapers.counties_nc import rocky_mount_blight_survey as RM
from foreclosure_scraper.validation import _validate_parcel_id

NOW = datetime(2026, 10, 8, 12, 0)


def _survives_validation(li) -> bool:
    stats: dict = {"parcel_nulled_too_short": 0, "parcel_nulled_bad_pattern": 0}
    _validate_parcel_id(li, stats)
    return bool(li.parcel_id)


# ----------------------------------------------------------------------------- Rocky Mount

def _survey_row(parno, altparno, site):
    return {"PARNO": parno, "ALTPARNO": altparno, "OWNNAME": "PRETEND HOLDINGS LLC",
            "SITEADD": site, "SCITY": "ROCKY MOUNT", "PARVAL": 41000}


def test_rocky_mount_nash_short_account_yields_to_the_12_digit_pin():
    nash = next(lay for lay in RM.LAYERS if lay.name == "nash_dilapidated")
    edge = next(lay for lay in RM.LAYERS if lay.name == "edgecombe_dilapidated")
    slots = RM.fold([(nash, _survey_row("027989", "385018315565", "1 MADEUP ST")),
                     (edge, _survey_row("3759-86-6196", "3759866196", "2 MADEUP ST"))])
    by_county = {s["county"]: RM.to_listing(s, now=NOW) for s in slots.values()}
    assert by_county["Nash"].parcel_id == "385018315565"
    assert by_county["Nash"].raw["arcgis_distress"]["PARNO"] == "027989"   # the account stays
    assert by_county["Edgecombe"].parcel_id == "3759-86-6196"              # a long PARNO is kept
    assert all(_survives_validation(li) for li in by_county.values())


def test_rocky_mount_short_parno_without_a_long_alt_is_unchanged():
    nash = next(lay for lay in RM.LAYERS if lay.name == "nash_deteriorated")
    li = RM.to_listing(next(iter(RM.fold([(nash, _survey_row("012345", None, "3 MADEUP ST"))]).values())),
                       now=NOW)
    assert li.parcel_id == "012345"


# ----------------------------------------------------------------------------- Durham demolitions

def test_durham_demolition_uses_the_pin_not_the_short_pid():
    feed = next(f for f in DP.FEEDS if f.name == "durham")
    assert "PIN15" in feed.fields
    rows = [{"PermitNum": "B1", "PID": "100001", "PIN15": "0822537639", "ISSUE_DATE": 1767225600000,
             "PmtStatus": "Issued", "TYPE": "RESI"},
            {"PermitNum": "B2", "PID": "100001", "PIN15": "0822537639", "ISSUE_DATE": 1767312000000,
             "PmtStatus": "CO Issued", "TYPE": "RESI"}]
    groups = DP.group_permits(feed, rows)
    assert len(groups) == 1                                  # one property, two permits
    li = DP.to_listing(groups[0], now=NOW)
    assert li.parcel_id == "0822537639"
    assert li.raw["demolition_permit"]["county_parcel_id"] == "100001"
    assert li.raw["demolition_permit"]["count"] == 2
    assert _survives_validation(li)


def test_other_feeds_keep_their_own_parcel_column():
    feed = next(f for f in DP.FEEDS if f.name == "mecklenburg")
    li = DP.to_listing(DP.group_permits(feed, [{"permit_number": "D9", "permit_status": "Issued",
                                                "project_address": "9 FAKE ST",
                                                "cama_parcel_number": "11111111"}])[0], now=NOW)
    assert li.parcel_id == "11111111"
    assert "county_parcel_id" not in li.raw["demolition_permit"]


# ----------------------------------------------------------------------------- Burke storm damage

def test_burke_storm_damage_keeps_the_assessors_point_and_damage_estimate():
    lay = next(l for l in AD.LAYERS if l.slug == "burke_storm_damage")
    for f in ("latitude", "longitude", "Damage_Val", "BLDG_Val"):
        assert f in lay.fields
    li = AD._to_listing({"REID": 12345, "dmg_loc": "10 PRETEND RD", "damage_cat_cal": "Structure - Major",
                         "latitude": 35.7642, "longitude": -81.7169, "Damage_Val": 51000,
                         "BLDG_Val": 256000}, lay)
    assert (li.latitude, li.longitude) == (35.7642, -81.7169)
    assert li.raw["arcgis_distress"]["Damage_Val"] == 51000


# ----------------------------------------------------------------------------- Asheville STR permits

def test_asheville_str_rows_carry_the_permit_point(monkeypatch):
    sent: dict = {}

    class _Resp:
        def json(self):
            return {"features": [
                {"attributes": {"record_name": "PRETEND OWNER", "address": "1 MADEUP LN, ASHEVILLE, NC 28801",
                                "apn": "206046", "parcel_number": "206046", "record_status": "Expired",
                                "record_id": "HS-1"},
                 "geometry": {"x": -82.5148, "y": 35.4967}},
                {"attributes": {"record_name": "OTHER OWNER", "address": "2 MADEUP LN, ASHEVILLE, NC 28801",
                                "apn": "35795", "record_status": "Revoked", "record_id": "HS-2"},
                 "geometry": {"x": 0, "y": 0}},
            ]}

    class _Client:
        async def get(self, url, params=None):
            sent.update(params or {})
            return _Resp()

    @asynccontextmanager
    async def fake_client(**kw):
        yield _Client()

    monkeypatch.setattr(STR, "client", fake_client)
    rows = asyncio.run(STR.AshevilleSTRPermits().fetch())
    assert sent.get("returnGeometry") == "true" and sent.get("outSR") == "4326"
    by_id = {li.case_number: li for li in rows}
    assert (by_id["HS-1"].latitude, by_id["HS-1"].longitude) == (35.4967, -82.5148)
    assert by_id["HS-2"].latitude is None                     # a 0/0 point is no point
