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
    from collections import Counter
    _validate_parcel_id(li, Counter())
    return bool(li.parcel_id)


# ----------------------------------------------------------------------------- Rocky Mount

def _survey_row(parno, altparno, site):
    return {"PARNO": parno, "ALTPARNO": altparno, "OWNNAME": "PRETEND HOLDINGS LLC",
            "SITEADD": site, "SCITY": "ROCKY MOUNT", "PARVAL": 41000}


def test_rocky_mount_keeps_each_county_native_parcel_number():
    # Nash's PARNO is its own 6-digit parcel number, kept by validation since 2026-10-08
    # (COUNTY_NATIVE_SHORT_PARCEL) and the id other Nash sources publish; the 12-digit ALTPARNO
    # stays in the raw block. Edgecombe's PARNO is its dashed PIN.
    nash = next(lay for lay in RM.LAYERS if lay.name == "nash_dilapidated")
    edge = next(lay for lay in RM.LAYERS if lay.name == "edgecombe_dilapidated")
    slots = RM.fold([(nash, _survey_row("027989", "385018315565", "1 MADEUP ST")),
                     (edge, _survey_row("3759-86-6196", "3759866196", "2 MADEUP ST"))])
    by_county = {s["county"]: RM.to_listing(s, now=NOW) for s in slots.values()}
    assert by_county["Nash"].parcel_id == "027989"
    assert by_county["Nash"].raw["arcgis_distress"]["ALTPARNO"] == "385018315565"
    assert by_county["Edgecombe"].parcel_id == "3759-86-6196"
    assert all(_survives_validation(li) for li in by_county.values())


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


# ----------------------------------------------------------------------------- SeeClickFix

def test_seeclickfix_never_keeps_the_complainant(monkeypatch):
    from foreclosure_scraper.scrapers.national import seeclickfix as SCF

    class _Resp:
        status_code = 200

        def json(self):
            return {"issues": [{"id": 1, "summary": "Abandoned property", "description": "vacant house",
                                "address": "1 Pretend St, Spartanburg, SC 29301", "status": "Open",
                                "reporter": {"id": 7, "name": "Made Up Resident", "role": "Registered User"},
                                "html_url": "https://seeclickfix.com/issues/1"}]}

    class _C:
        async def get(self, url, params=None):
            return _Resp()

    @asynccontextmanager
    async def fake_client(**kw):
        yield _C()

    monkeypatch.setattr(SCF, "client", fake_client)
    city = next(c for c in SCF._CITIES if c["city"] == "Spartanburg")
    rows = asyncio.run(SCF.SeeClickFixScraper()._fetch_city(city))
    assert rows and "reporter" not in rows[0].raw["seeclickfix"]
    assert "Made Up Resident" not in repr(rows[0].raw)


# ----------------------------------------------------------------------------- Transylvania vacant

def test_transylvania_legal_location_is_not_a_street_address(monkeypatch):
    from foreclosure_scraper.scrapers.counties_nc import transylvania_vacant as TV

    feats = [{"attributes": {"PIN": f"85{i:08d}", "OWNER_NAME": "PRETEND LAND LLC", "LEGAL_ADDR": legal,
                             "STATE": "NC", "BUILDING_V": 0}}
             for i, legal in enumerate(["OAK LAUREL RD L-71", "TR K OFF FROZEN CREEK RD",
                                        "LAUREL CREEK DR L-5A     1.67", "123 MADEUP RD"])]

    class _Resp:
        status_code = 200

        def json(self):
            return {"features": feats}

    class _C:
        async def get(self, url, params=None):
            return _Resp()

    @asynccontextmanager
    async def fake_client(**kw):
        yield _C()

    monkeypatch.setattr(TV, "client", fake_client)
    rows = {li.legal_description: li for li in asyncio.run(TV.TransylvaniaVacant().fetch())}
    assert rows["OAK LAUREL RD L-71"].street_address is None
    assert rows["TR K OFF FROZEN CREEK RD"].street_address is None
    assert rows["LAUREL CREEK DR L-5A     1.67"].street_address is None
    assert rows["123 MADEUP RD"].street_address == "123 MADEUP RD"


# ----------------------------------------------------------------------------- New Hanover demolitions

def test_new_hanover_reads_only_live_whole_structure_demolitions():
    w = next(l for l in AD.LAYERS if l.slug == "new_hanover_demolition_permits").where
    assert "WORK_CLASS = 'Demolition'" in w and "LIKE" not in w     # 'Interior Demolition' is a renovation
    for dead in ("Void", "Withdrawn", "Revoked"):
        assert f"'{dead}'" in w
    assert "PERMIT_STATUS IS NULL" in w                              # NOT IN alone drops NULL statuses


# ----------------------------------------------------------------------------- EPA FRS county text

def test_epa_frs_reads_the_county_from_suffixes_cities_and_one_close_spelling():
    from foreclosure_scraper.scrapers.counties_generic import epa_frs_sites as E

    def row(county, city, addr="1 PRETEND INDUSTRIAL RD"):
        return {"county_name": county, "city_name": city, "location_address": addr,
                "primary_name": "MADE UP MILL", "pgm_sys_id": "X1", "registry_id": "110000000001"}

    cases = [
        (row("ROBESON COUNTY", "LUMBERTON"), "NC", "Robeson", "county_name"),
        (row("WILSON COOUNTY", "WILSON"), "NC", "Wilson", "county_name"),
        (row(" NOT DEFINED ", "SALISBURY"), "NC", "Rowan", "city"),
        (row("GREENVILLE", "GREENVILLE"), "NC", "Pitt", "city"),        # an NC city, not the SC county
        (row(None, "WENDELL"), "NC", "Wake", "city"),
        (row("ALLLENDALE", "NOWHERE TOWN"), "SC", "Allendale", "close_spelling"),
        (row("GREENVILLE", "GREER"), "SC", "Greenville", "county_name"),
    ]
    for r, st, county, how in cases:
        li = E._to_listing(r, st, "ACRES")
        assert li is not None, r
        assert (li.county, li.raw["epa_frs"]["county_from"]) == (county, how), r
    assert E._to_listing(row(" NOT DEFINED ", "NOWHERE TOWN"), "SC", "SEMS") is None
    assert E._to_listing(row("CUMBERLAND", "FAYETTEVILLE", addr="UNKNOWN"), "NC", "ACRES") is None


# ----------------------------------------------------------------------------- national.distressed

def test_distressed_reads_every_active_listing_not_a_120_day_window(monkeypatch):
    import sys
    import types

    from foreclosure_scraper.scrapers.national import homeharvest_distressed as HD

    seen_kw: dict = {}

    class _DF:
        def __len__(self):
            return 0

    fake = types.ModuleType("homeharvest")

    def scrape_property(**kw):
        seen_kw.update(kw)
        return _DF()

    fake.scrape_property = scrape_property
    monkeypatch.setitem(sys.modules, "homeharvest", fake)
    monkeypatch.setattr(HD, "PAST_DAYS", 0)
    HD._scrape_county("NC", "Polk")
    assert seen_kw.get("listing_type") == "for_sale" and "past_days" not in seen_kw


def test_distressed_keeps_prior_sale_unit_mls_and_status_dates():
    import datetime as dt

    from foreclosure_scraper.scrapers.national import homeharvest_distressed as HD

    row = {"property_url": "https://example.invalid/p/1", "street": "1 Pretend Ln", "unit": "Apt 2",
           "city": "Tryon", "state": "NC", "zip_code": "28782", "list_price": 150000,
           "text": "Sold as-is, motivated seller", "mls": "CMLS", "mls_id": "4100001",
           "last_sold_date": dt.date(2019, 5, 1), "last_sold_price": 90000.0,
           "pending_date": float("nan"), "last_status_change_date": "2026-09-30T12:00:00",
           "hoa_fee": 35.0, "stories": 2.0, "new_construction": False}
    li = HD._to_listing(row, "Polk", ["as-is"])
    d = li.raw["distressed"]
    assert d["unit"] == "Apt 2" and d["mls_id"] == "4100001" and d["mls"] == "CMLS"
    assert d["last_sold_date"] == "2019-05-01" and d["last_sold_price"] == 90000.0
    assert d["pending_date"] is None and d["last_status_change_date"] == "2026-09-30"
    assert d["hoa_fee"] == 35.0 and d["new_construction"] is False
    import json
    json.dumps(li.raw)                                       # publishable as JSON


def test_distressed_salvages_finished_counties_on_a_timeout(monkeypatch):
    import time

    from foreclosure_scraper.models import Listing, ListingType
    from foreclosure_scraper.scrapers.national import homeharvest_distressed as HD

    def fake_scrape(state, county):
        if county == "Polk":
            return [Listing(source="national.distressed", source_url="https://example.invalid/p/9",
                            listing_type=ListingType.DISTRESSED, state=state, county=county)]
        time.sleep(1.5)
        return []

    monkeypatch.setattr(HD, "COUNTY_UNIVERSE", (("NC", "Polk"), ("NC", "Wake")))
    monkeypatch.setattr(HD, "_scrape_county", fake_scrape)
    s = HD.DistressedListings()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert [li.county for li in rows] == ["Polk"]


def test_homeharvest_foreclosures_have_no_list_date_window(monkeypatch):
    import sys
    import types

    from foreclosure_scraper.scrapers.national import homeharvest as HH

    calls: list = []
    fake = types.ModuleType("homeharvest")

    def scrape_property(**kw):
        calls.append(kw)
        return None

    fake.scrape_property = scrape_property
    monkeypatch.setitem(sys.modules, "homeharvest", fake)
    HH._scrape_one_county("Spartanburg", "SC", "Spartanburg")
    assert calls and all("past_days" not in kw for kw in calls)
