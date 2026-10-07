"""Second round of 2026-10-07 distress sources (docs/new_sources_2026-10-07_distress.md):

    counties_sc.charleston_energov_history     Charleston County code cases + demolition permits
    counties_nc.nc_metro_demolition_permits    Mecklenburg, Greensboro, Durham, Cary demolitions
    counties_nc.rowan_delinquent_tax           Rowan delinquent real-estate XLSX
    counties_nc.cumberland_delinquent_tax      Cumberland unpaid real-estate tax ad (PDF)
    counties_nc.iredell_delinquent_tax         Iredell delinquent-parcel outlines -> NC OneMap
    counties_nc.wake_code_cases                Wake County open code cases (90 days)
    counties_nc.nc_tax_lien_ads                Hoke, Lee, Davidson, Randolph tax-lien ads

Offline. Field names and line layouts are the live sources' (2026-10-07); every name, street,
parcel number and amount below is invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_generic import _layer_kit as KIT
from foreclosure_scraper.scrapers.counties_generic import _tax_kit as TAX
from foreclosure_scraper.scrapers.counties_nc import cumberland_delinquent_tax as CU
from foreclosure_scraper.scrapers.counties_nc import iredell_delinquent_tax as IR
from foreclosure_scraper.scrapers.counties_nc import nc_metro_demolition_permits as DP
from foreclosure_scraper.scrapers.counties_nc import nc_tax_lien_ads as ADS
from foreclosure_scraper.scrapers.counties_nc import rowan_delinquent_tax as RO
from foreclosure_scraper.scrapers.counties_nc import wake_code_cases as WK
from foreclosure_scraper.scrapers.counties_sc import charleston_energov_history as CH

NOW = datetime(2026, 10, 7, 12, 0)
SLUGS = (CH.SLUG, DP.SLUG, RO.SLUG, CU.SLUG, IR.SLUG, WK.SLUG, ADS.SLUG)


# ----------------------------------------------------------------------------- shared kits

def test_tax_kit_counts_only_late_years():
    to = TAX.tax_owed_block([(2024, 100.0), (2025, 200.0), (2026, 300.0)], state="NC",
                            county="Rowan", source="t", today=date(2026, 10, 7))
    assert to["years_delinquent"] == 2 and to["unpaid_bill_years"] == 3
    assert to["not_yet_late_years"] == [2026] and to["not_yet_late_amount"] == 300.0
    assert to["balance"] == 300.0 and to["year"] == 2026 and to["years_basis"] == "year_list"
    assert TAX.tax_owed_block([(2026, 50.0)], state="NC", county="X", source="t",
                              today=date(2026, 10, 7)) is None
    assert TAX.tax_owed_block([(2026, 50.0)], state="NC", county="X", source="t",
                              today=date(2027, 1, 6))["years_delinquent"] == 1


def test_interior_point_and_point_in_rings():
    u = [[[0, 0], [6, 0], [6, 6], [4, 6], [4, 2], [2, 2], [2, 6], [0, 6], [0, 0]]]
    p = KIT.interior_point(u)
    assert KIT.point_in_rings(*p, u) and not KIT.point_in_rings(3, 4, u)


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class _Http:
    def __init__(self, bodies):
        self.bodies, self.calls = list(bodies), []

    async def post(self, url, data=None, timeout=None):
        self.calls.append((url, data))
        return _Resp(self.bodies.pop(0))

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _Resp(self.bodies.pop(0))


def test_match_points_polygon_and_nearest_point_layers():
    poly = {"features": [{"attributes": {"parno": "A1", "OWNER_SSN": "x"},
                          "geometry": {"rings": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}
    http = _Http([poly])
    got = asyncio.run(KIT.match_points(http, "https://x/FeatureServer/1", [(0.5, 0.5), (5, 5)],
                                       ("parno",), delay_s=0))
    assert got == [{"parno": "A1"}, None]                    # sensitive column dropped
    pts = {"features": [{"attributes": {"PID": "9"}, "geometry": {"x": -80.0, "y": 33.0}}]}
    got = asyncio.run(KIT.match_points(_Http([pts]), "https://x/MapServer/0",
                                       [(-80.00001, 33.00001), (-80.01, 33.0)], ("PID",),
                                       distance_m=3, delay_s=0))
    assert got == [{"PID": "9"}, None]


# ----------------------------------------------------------------------------- Charleston

def test_charleston_where_clauses_read_only_building_cases_and_demolitions():
    w = CH.where_clauses(datetime(2024, 10, 7))
    assert "CASETYPE IN ('Building Services')" in w["code"] and "DATE '2024-10-07'" in w["code"]
    assert "WORKCLASS LIKE 'Demolition%'" in w["demolition"]


def _feat(case, kind_type, d, x, y, wc=" "):
    return {"attributes": {"CASENUMBER": case, "CASETYPE": kind_type, "WORKCLASS": wc,
                           "APPLICATIONDATE": int(d.replace(tzinfo=timezone.utc).timestamp() * 1000)},
            "geometry": {"x": x, "y": y}}


def test_charleston_cases_dedupe_group_and_age():
    code = CH.unique_cases([_feat("BIS-1", "Building Services", datetime(2026, 3, 1), 1, 1),
                            _feat("BIS-1", "Building Services", datetime(2026, 4, 1), 1, 1)], "code")
    demo = CH.unique_cases([_feat("BLD-9", "Building (R)", datetime(2026, 5, 1), 1, 1, "Demolition")],
                           "demolition")
    assert len(code) == 1 and code[0]["date"] == datetime(2026, 4, 1)
    addr = {"PID": "1234567890", "WHOLE_ADDRESS": "1 SAMPLE ST", "POSTAL_TOWN": "NORTH CHARLESTON",
            "POSTAL_CODE": "29405"}
    groups = CH.group_by_property(code + demo + demo, [addr, addr, None])
    assert len(groups) == 1 and groups[0]["_unmatched"] == 1
    li = CH.to_listing(groups[0], now=NOW)
    assert (li.parcel_id, li.street_address, li.city) == ("1234567890", "1 SAMPLE ST", "North Charleston")
    ce = li.raw["code_enforcement"]
    assert ce["stale_after"] == "2027-04-01" and ce["violations"][0]["status"] == "filed"
    assert li.raw["demolition_permit"]["count"] == 1 and "condemned" not in li.raw
    assert li.source == CH.SLUG and li.foreclosure_process == "code_enforcement"


# ----------------------------------------------------------------------------- demolitions

def test_demolition_feeds_drop_dead_permits_keep_expired_and_mailing():
    feed = next(f for f in DP.FEEDS if f.name == "mecklenburg")
    rows = [
        {"permit_number": "D1", "permit_status": "Permit Expired", "issue_date": 1767225600000,
         "project_address": "9 FAKE ST", "cama_parcel_number": "11111111", "tax_jurisdiction": "CHARLOTTE",
         "owner_name": "PRETEND LLC", "owner_address": "1 ELSEWHERE AVE", "owner_city": "ATLANTA",
         "owner_state": "GA", "owner_zip_code": "30301", "owner_phone": "5555555555"},
        {"permit_number": "D2", "permit_status": "Cancelled", "project_address": "10 FAKE ST",
         "cama_parcel_number": "22222222"},
    ]
    groups = DP.group_permits(feed, rows)
    assert len(groups) == 1
    li = DP.to_listing(groups[0], now=NOW)
    assert li.raw["owner_mailing"]["out_of_state"] is True
    assert li.raw["demolition_permit"]["permits"][0]["status"] == "Permit Expired"
    assert "owner_phone" not in DP.FEEDS[0].fields and li.city == "Charlotte"
    assert li.county == "Mecklenburg" and "condemned" not in li.raw


def test_demolition_where_clauses():
    since = datetime(2024, 10, 7)
    feeds = {f.name: f for f in DP.FEEDS}
    assert "type_of_work='Demolition'" in DP.arcgis_where(feeds["mecklenburg"], since)
    assert "Total Demolish" in DP.arcgis_where(feeds["greensboro"], since)
    assert DP.cary_where(since).endswith("applieddate >= date'2024-10-07'")


# ----------------------------------------------------------------------------- Rowan

ROWAN = {"report_group_description": "REAL", "tax_year": "2025", "parcel_number": "001A001",
         "asset_description": "12 IMAGINARY RD", "taxpayer_name_1": "SAMPLE OWNER",
         "taxpayer_name_2": "", "taxpayer_address_line_1": "PO BOX 1", "taxpayer_city": "RICHMOND",
         "taxpayer_state": "VA", "taxpayer_zip": "23219", "balance_due": "1,234.50",
         "assessed_value": "80000", "type_of_id": "HRS", "bill_number": "2025XX001", "ar_status": "OPEN"}


def test_rowan_reads_only_real_estate_and_shapes_tax_owed():
    li = RO.to_listing(dict(ROWAN), "https://example.invalid/x", now=NOW)
    to = li.raw["tax_owed"]
    assert (to["balance"], to["year"], to["years_delinquent"], to["source"]) == (1234.5, 2025, 1, RO.SLUG)
    assert li.raw["rowan_delinquent_tax"]["years_unpaid"] == [2025]
    assert li.raw["owner_mailing"]["out_of_state"] is True and li.raw["heirs_or_estate_owner"]["type"] == "HRS"
    assert RO.to_listing(dict(ROWAN, report_group_description="PP"), "u") is None
    assert RO.to_listing(dict(ROWAN, tax_year="2099"), "u") is None        # not late yet


def test_rowan_finds_the_newest_xls_link():
    html = ('<a href="/DocumentCenter/View/111" class="x">Download 2024 List (XLS)</a>'
            '<a href="/DocumentCenter/View/222">Download 2025 List (XLS)</a>'
            '<a href="/DocumentCenter/View/333">Download 2025 List (PDF)</a>')
    assert RO.newest_xls(html) == (2025, "https://www.rowancountync.gov/DocumentCenter/View/222")


# ----------------------------------------------------------------------------- Cumberland

CUMB = """Cumberland Co Taxes | SUNDAY, JUNE 21, 2026 | 1
Advertisement of Unpaid Real Estate Taxes for 2025
0417-22-9978 SAMPLE, PERSON
MADEUP 711 PRETEND RD
FAYETTEVILLE NC $1,103.99
0416-91-9008 FAKE HOLDINGS LLC
2281 EXAMPLE ST HOPE MILLS NC 28348
$17 6.08
0442-61-6011 NOBODY
LOT 4 NO STREET $18.00
"""


def test_cumberland_parses_wrapped_records_and_split_amounts():
    recs = CU.parse_text(CUMB)
    assert [r["pin"] for r in recs] == ["0417-22-9978", "0416-91-9008", "0442-61-6011"]
    assert [r["amount"] for r in recs] == [1103.99, 176.08, 18.0]
    assert recs[0]["situs"] == "711 PRETEND RD" and recs[0]["owner"] == "SAMPLE, PERSON MADEUP"
    assert recs[1]["situs"] == "2281 EXAMPLE ST" and recs[2]["situs"] is None
    li = CU.to_listing(recs[1], 2025, "u", now=NOW)
    assert li.parcel_id == "0416-91-9008" and li.raw["tax_owed"]["balance"] == 176.08
    assert CU.to_listing(recs[1], 2099, "u") is None


# ----------------------------------------------------------------------------- Iredell

def test_iredell_outline_to_parcel_lead():
    feats = [{"attributes": {"ASOF": 1791244800000},
              "geometry": {"rings": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}]
    pts = IR.outline_points(feats)
    assert pts[0][1] == "2026-10-06" and KIT.point_in_rings(*pts[0][0], feats[0]["geometry"]["rings"])
    parcel = {"parno": "4700000000", "ownname": "SAMPLE OWNER", "siteadd": "5 MADEUP LN",
              "scity": "STATESVILLE", "szip": "28677", "parval": 150000, "mailadd": "5 MADEUP LN",
              "mcity": "STATESVILLE", "mstate": "NC", "mzip": "28677"}
    li = IR.to_listing(parcel, "2026-10-06", now=NOW, year=2025)
    assert li.parcel_id == "4700000000" and li.raw["tax_owed"]["year"] == 2025
    assert li.raw["tax_owed"]["balance"] is None and li.raw["owner_mailing"]["absentee"] is False
    assert IR.to_listing(parcel, None, year=2099) is None
    assert "cntyname" not in ",".join(IR.ONEMAP_FIELDS)


# ----------------------------------------------------------------------------- Wake

def _wake(status="In Progress", ctype="VIO - Building Inspections", desc="FIRE DAMAGED BUILDING"):
    return {"CASE_NUMBER": "C-1", "OPENED_DATE": 1788000000000, "DISTRICT": "Zebulon",
            "CASE_STATUS": status, "CASE_TYPE": ctype, "DESCRIPTION": desc,
            "STREET_ADDRESS": "7 SAMPLE CT", "CITY_STATE_ZIP": "ZEBULON, NC 27597"}


def test_wake_admits_structural_open_cases_and_never_stores_the_description():
    li = WK.to_listing(_wake(desc="Fire damaged house of John Example"), now=NOW)
    assert li.raw["wake_code_case"]["categories"] == ["fire_damage"]
    assert "John" not in str(li.raw) and li.city == "Zebulon" and li.zip_code == "27597"
    assert li.raw["code_enforcement"]["severe"] is True
    assert WK.to_listing(_wake(status="Closed - VIO Resolved"), now=NOW) is None
    assert WK.to_listing(_wake(desc="homeowner repair request"), now=NOW) is None
    assert WK.to_listing(_wake(ctype="VIO - Planning/Zoning", desc="95.01 Noxious weeds"), now=NOW) is None
    assert WK.to_listing(_wake(ctype="VIO - Planning/Zoning", desc="abandoned house"), now=NOW)
    sep = WK.to_listing(_wake(ctype="VIO - Wastewater", desc="O&M Malfunction Inspection"), now=NOW)
    assert "septic_failure" in sep.raw["wake_code_case"]["categories"]


# ----------------------------------------------------------------------------- tax-lien ads

def test_hoke_lines():
    t = ("OWNER NAME PARCEL CODE AMOUNT DUE PROPERTY DESCRIPTION\n"
         "SAMPLE TRUST 49455-04-01-022 418.04$        2853  PRETEND RD\n"
         "FAKE, PERSON 79452-00-01-032 1,032.29$ 0 ST MADEUP RD\n")
    r = ADS.parse_hoke(t)
    assert [(x["pid"], x["amount"], x["situs"]) for x in r] == [
        ("49455-04-01-022", 418.04, "2853 PRETEND RD"), ("79452-00-01-032", 1032.29, None)]


def test_lee_lines_including_a_record_wrapped_over_three_lines():
    t = ("150723 SAMPLE OWNER LLC 967014532200 1306 PRETEND AVE 2,025 $45.19\n"
         "19 FAKE, PERSON 964173155800 0 MADEUP ST\n"
         "XX\n"
         "2,025 $151.31\n")
    r = ADS.parse_lee(t)
    assert [(x["pid"], x["amount"], x["year"]) for x in r] == [
        ("967014532200", 45.19, 2025), ("964173155800", 151.31, 2025)]
    assert r[0]["situs"] == "1306 PRETEND AVE" and r[1]["situs"] is None


def test_davidson_pads_the_dropped_leading_zero_and_cuts_the_owner_at_legal_text():
    t = ("9043796 SAMPLE PERSON X48X DB1140-1115 PRETEND RD 4.16AC0 0900700000048X $1,003.85\n"
         "9074392 FAKE OWNER JR L18 DB1550-1258 SOMEWHERE .29AC00 603200000018 $1,268.67\n")
    r = ADS.parse_davidson(t)
    assert [x["pid"] for x in r] == ["0900700000048X", "0603200000018"]
    assert r[1]["owner"] == "FAKE OWNER JR" and r[0]["amount"] == 1003.85


def test_randolph_lines_with_a_glued_amount_and_second_owner():
    t = ("ADVERTISEMENT OF TAX LIENS ON REAL ESTATE\nFOR UNPAID 2025 TAXES IN RANDOLPH COUNTY, NC\n"
         "7750872678 SAMPLE PERSON AND OTHER1,796.56\n"
         "6794059611 FAKE, PERSON A 282.58 MADEUP, OTHER B\n")
    r = ADS.parse_randolph(t)
    assert [(x["pid"], x["amount"]) for x in r] == [("7750872678", 1796.56), ("6794059611", 282.58)]
    assert r[1]["owner"] == "FAKE, PERSON A & MADEUP, OTHER B"


def test_ad_listing_shape_and_not_yet_late_drop():
    county = next(c for c in ADS.COUNTIES if c.name == "Hoke")
    li = ADS.to_listing({"pid": "49455-04-01-022", "owner": "SAMPLE", "situs": None, "amount": 10.0},
                        county, now=NOW)
    assert li.listing_type == ListingType.TAX_LIEN and li.raw["tax_owed"]["years_delinquent"] == 1
    assert ADS.to_listing({"pid": "1", "owner": None, "situs": None, "amount": 1.0, "year": 2099}, county) is None


# ----------------------------------------------------------------------------- registry / publish

def test_all_seven_are_registered_and_their_raw_keys_survive_publish():
    from foreclosure_scraper.scrapers._registry import discover
    from foreclosure_scraper.web_artifact import RAW_KEEP
    slugs = {c.slug for c in discover()}
    for s in SLUGS:
        assert s in slugs, s
    for k in ("charleston_energov", "demolition_permit", "rowan_delinquent_tax", "heirs_or_estate_owner",
              "cumberland_delinquent_tax", "iredell_delinquent_tax", "wake_code_case", "nc_tax_lien_ad",
              "tax_owed", "code_enforcement", "owner_mailing"):
        assert k in RAW_KEEP, k


def test_env_gates(monkeypatch):
    for mod, cls in ((CH, CH.CharlestonEnergovHistory), (DP, DP.NCMetroDemolitionPermits),
                     (RO, RO.RowanDelinquentTax), (CU, CU.CumberlandDelinquentTax),
                     (IR, IR.IredellDelinquentTax), (WK, WK.WakeCodeCases), (ADS, ADS.NCTaxLienAds)):
        monkeypatch.setenv(mod.ENV_OFF, "0")
        assert asyncio.run(cls().fetch()) == []
