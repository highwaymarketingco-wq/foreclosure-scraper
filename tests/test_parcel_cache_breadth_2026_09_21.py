"""County-breadth parcel-cache entries (research of 2026-09-21) and the address overlay.

Nothing here touches the network. The layer URLs, field names and row shapes were
VERIFIED LIVE on 2026-09-21 by the research pass (docs/county_breadth_research_2026-09-21.md);
these tests pin the mapping so a later edit that breaks a field name, a value column or the
state tag fails here instead of silently writing a bad cache file.

Row values are invented. Field NAMES and value SHAPES (padded strings, glued state+ZIP,
comma-formatted numbers, epoch-ms dates, float PINs) are the real ones.
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.parse

import pytest

from foreclosure_scraper import parcel_cache as pc

NEW_COUNTIES = ("Florence", "Charleston", "Berkeley", "Aiken", "Greenwood", "Hampton", "Chester",
                "Greenville")


# --------------------------------------------------------------------------- config shape
@pytest.mark.parametrize("county", NEW_COUNTIES)
def test_new_entry_is_well_formed(county):
    cfg = pc.PARCEL_LAYERS[county]
    assert cfg["state"] == "SC"
    assert cfg["url"].startswith("https://") and cfg["url"].endswith("/query")
    assert cfg["id_fields"], "no join key"
    assert set(cfg["map"]) <= set(pc._COLS), "map names a column the cache table does not have"
    # a county with a mailing block must actually map it: that is the point of the entry
    assert cfg["map"].get("owner_mailing")


def test_dual_state_chester_is_pinned_to_sc():
    """Chester exists in both states; an untagged config would raise in _db_path and,
    worse, could be read by an NC lookup."""
    assert "Chester" in pc.DUAL_STATE_COUNTIES
    cfg = pc.resolve_layer_cfg("Chester")
    assert cfg["state"] == "SC"
    assert pc._db_path("Chester", cfg["state"]).name == "chester_sc.sqlite"


def test_assessed_ratio_values_are_never_mapped_as_a_value():
    """Aiken's AssessedValue is 4-6% of market (26,820 on a 670,560 parcel). tax_value is
    the ARV fallback (x1.25), so mapping it would price a $670K house at ~$33K."""
    assert "tax_value" not in pc.PARCEL_LAYERS["Aiken"]["map"]
    # Florence publishes only a BUILDING value, which would understate every improved parcel
    m = pc.PARCEL_LAYERS["Florence"]["map"]
    assert "market_value" not in m and "tax_value" not in m


# ------------------------------------------------------------------------ per-county mapping
def _map_row(county: str, row: dict) -> dict:
    m = pc.PARCEL_LAYERS[county]["map"]
    return {c: pc._map_val(row, c, m.get(c)) for c in pc._COLS}


def _keys(county: str, row: dict) -> set:
    out: set = set()
    for f in pc.PARCEL_LAYERS[county]["id_fields"]:
        out |= pc._id_variants(row.get(f))
    return out


def test_florence_mailing_skips_the_name_line_and_splits_state_zip():
    row = {"TMS": "00001-04-001", "TMSNODASH": "0000104001",
           "OWNERNAME": "TESTOWNER JANE A",
           "ADD1": "C/O TEST PERSON", "ADD2": "120 TOLSON RD               ",
           "ADD3": "LYNCHBURG            SC29080",
           "ADDR_SITE": "2233 E LYNCHES RIVER RD", "CALCULATED_ACREAGE": 24.82215712,
           "TOTBDGVAL": 20865}
    out = _map_row("Florence", row)
    assert out["owner_mailing"] == "120 TOLSON RD LYNCHBURG SC 29080"     # no C/O, no glue
    assert out["address"] == "2233 E LYNCHES RIVER RD"
    assert out["acreage"] == pytest.approx(24.82215712)
    assert out["market_value"] is None and out["tax_value"] is None
    assert {"00001-04-001".replace("-", ""), "0000104001"} <= _keys("Florence", row)


def test_charleston_pid_owner_mailing_and_value():
    row = {"PID": "6000100646", "OWNER1": "TESTOWNER ONE", "OWNER2": "TESTOWNER TWO",
           "MAIL_ST_NO": "1213", "MAIL_ST_NAME": "CUTLER" + " " * 50,
           "MAIL_ST_TYPE": "LN      ", "MAIL_2ND_ADDR": "        ",
           "MAIL_2ND_ADDT": "        ", "MAIL_CITY": "MOUNT PLEASANT" + " " * 16,
           "MAIL_STATE": "SC  ", "MAIL_ZIP": "29466" + " " * 11,
           "CLASS_CODE": "101 - RESID-SFR" + " " * 40, "ACREAGE": 0.34,
           "LAND_APPR": 285200.0, "IMP_APPR": 819900.0, "APPRAISAL": 1105100.0,
           "SALE_PRICE": 440000.0, "DOC_DATE": 1332374400000}
    out = _map_row("Charleston", row)
    assert out["owner"] == "TESTOWNER ONE TESTOWNER TWO"
    assert out["owner_mailing"] == "1213 CUTLER LN MOUNT PLEASANT SC 29466"
    assert out["market_value"] == 1105100.0
    assert out["land_use"] == "101 - RESID-SFR"
    assert out["sale_date"] == "2012-03-22"                 # epoch-ms -> ISO date
    assert "6000100646" in _keys("Charleston", row)


def test_charleston_has_a_pid_keyed_address_overlay_with_a_unit_column():
    o = pc.PARCEL_LAYERS["Charleston"]["address_overlay"]
    assert o["id_fields"] == ["PID"] and o["address"] == "WHOLE_ADDRESS" and o["unit"] == "UNIT"


def test_berkeley_value_is_the_market_figure_and_mail_is_joined():
    row = {"O_TMS": "1430909005", "OwnerName": "TESTOWNER LLC",
           "StreetAddress1": "1612 Military Cutoff Rd ", "StreetAddress2": "",
           "City": "Wilmington", "StateProvince": "NC", "Zip": "28403-1234",
           "GIS_Address": "1314 LIMETREE LN", "TotalTaxValue": 427110.0,
           "SalePrice": 425000.0, "SaleDate": 1639612800000, "TotalAcres": 0.0}
    out = _map_row("Berkeley", row)
    assert out["market_value"] == 427110.0
    assert out["address"] == "1314 LIMETREE LN"
    assert out["owner_mailing"] == "1612 Military Cutoff Rd Wilmington NC 28403-1234"
    assert out["sale_date"] == "2021-12-16"
    assert "1430909005" in _keys("Berkeley", row)


def test_aiken_indexes_both_the_dashed_tms_and_the_old_spaced_number():
    row = {"PARCEL_ASR": "108-14-04-009", "PARC_NO": "00 033 0 01 395",
           "OwnerName": "TESTOWNER TRUST", "LocationAddress": "835 ANDERSON MILL RD  ",
           "OwnerMailingAddress": "835 ANDERSON MILL", "OwnerMailingCity": "AIKEN",
           "OwnerMailingState": "SC", "OwnerMailingZip": "29803",
           "TotalMarketValue": 670560.0, "AssessedValue": 26820.0, "Acres": 1.0,
           "PropertyClassType": "OWNER OCCUPIED RESIDENTIAL", "SalePrice": 88000.0,
           "SaleDate": 1540958400000}
    out = _map_row("Aiken", row)
    assert out["market_value"] == 670560.0            # NOT the 4% assessed 26,820
    assert out["tax_value"] is None
    assert out["address"] == "835 ANDERSON MILL RD"
    assert out["owner_mailing"] == "835 ANDERSON MILL AIKEN SC 29803"
    assert {"1081404009", "00033001395"} <= _keys("Aiken", row)


def test_greenwood_full_cama_row():
    row = {"PIN": "6913-674-230", "SiteAddress": "140 MAIN ST W EXT", "Owner": "TESTOWNER",
           "MailAddress": "PO BOX 915", "MailCityState": "GREENWOOD, SC 29648-0000",
           "MarketValue_Total": 74000, "TaxValue_Total": 65600, "AssessedValue": 3940,
           "SqFt": 1677, "DeedAcres": 1.7, "PropType": "Residential",
           "PurchaseDate": 1003190400000}
    out = _map_row("Greenwood", row)
    assert out["address"] == "140 MAIN ST W EXT"
    assert out["owner_mailing"] == "PO BOX 915 GREENWOOD, SC 29648-0000"
    assert (out["market_value"], out["tax_value"], out["living_sqft"]) == (74000.0, 65600.0, 1677.0)
    assert out["sale_date"] == "2001-10-16"
    assert "6913674230" in _keys("Greenwood", row)


def test_greenville_moved_service_situs_is_the_street_parts_not_the_legal_descr():
    """The county moved this layer to arcgis3/.../GreenvilleNJ/QueryLayers (the old
    GreenvilleJS service is gone). DESCR is a legal description ("PH2", "UNIT B"), and
    STREET is the owner's MAILING street, so neither may leak into the situs."""
    row = {"PIN": "0001000100100", "OWNAM1": "TESTOWNER TRUST", "OWNAM2": "TESTOWNER LLC",
           "STREET": "PO BOX 26011", "CITY": "GREENVILLE", "STATE": "SC", "ZIP5": "29616",
           "STRNUM": "110", "STRPRE": "", "LOCATE": "EBAUGH", "STRTYP": "AVE", "STRSUF": None,
           "DESCR": "PH2", "FAIRMKTVAL": 1156060, "TAXMKTVAL": 533790, "TACRES": 0.24,
           "SQFEET": 1331, "PROPTYPE": "RESIDENTIAL", "SLPRICE": 185000,
           "DEEDDATE": 1492473600000}
    out = _map_row("Greenville", row)
    assert out["address"] == "110 EBAUGH AVE"
    assert out["owner_mailing"] == "PO BOX 26011 GREENVILLE SC 29616"
    # FAIRMKTVAL is the full market value, TAXMKTVAL the capped taxable one
    assert (out["market_value"], out["tax_value"]) == (1156060.0, 533790.0)
    assert out["sale_date"] == "2017-04-18"
    assert "0001000100100" in _keys("Greenville", row)
    assert pc.PARCEL_LAYERS["Greenville"]["url"].startswith(
        "https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/")


def test_hampton_comma_strings_and_trailing_dot_tms():
    row = {"Map_Number": "009-00-00-001.", "Parcel_polygons_TMS": "009-00-00-001.",
           "Name1": "TESTOWNER LAND COMPANY, INC", "Name2": "C/O TEST PERSON",
           "Address1": "275 PLANTATION DR", "Address2": "LURAY   S C", "ZIP_Code": "29932",
           "Street_Number_E911": "", "Street_Name_E911": "AUGUSTA STAGECOACH",
           "Tot_Market_Appr": "4,229,310", "Tot_Assesd_Value": "68,780",
           "Tot_Number_Acres": "3,553.05", "Consideration": "0"}
    out = _map_row("Hampton", row)
    assert out["market_value"] == 4229310.0 and out["acreage"] == 3553.05
    assert out["tax_value"] is None                       # assessed ratio figure is not mapped
    assert out["owner_mailing"] == "275 PLANTATION DR LURAY S C 29932"
    assert out["address"] == "AUGUSTA STAGECOACH"          # number missing: street only
    assert "0090000001" in _keys("Hampton", row)           # trailing dot normalised away


def test_chester_market_value_is_land_plus_building():
    """Chester publishes land (Appraised_) and building (Appraised1) separately; the live
    row with buildings read 84,200 + 58,400."""
    row = {"Map_Number": "144-00-00-098-000", "Name": "144-00-00-098-000",
           "Name_1": "TESTOWNER ONE", "Name_2": "TESTOWNER TWO",
           "Mailing_Ad": "1813 CURRY RD", "Mailing__1": "EDGEMOOR               SC",
           "Zip_Code": 29712, "Appraised_": 84200, "Appraised1": 58400,
           "DEED_ACRES": "2.575"}
    out = _map_row("Chester", row)
    assert out["market_value"] == 142600.0
    assert out["owner_mailing"] == "1813 CURRY RD EDGEMOOR SC 29712"
    assert out["acreage"] == 2.575
    assert out["address"] is None                          # no situs on this layer
    # land only (no building part) still sums to the land value; nothing at all is None
    assert pc._map_val({"Appraised_": 9200, "Appraised1": 0}, "market_value",
                       pc.PARCEL_LAYERS["Chester"]["map"]["market_value"]) == 9200.0
    assert pc._map_val({}, "market_value", pc.PARCEL_LAYERS["Chester"]["map"]["market_value"]) is None


# ------------------------------------------------------------------------- map_val extensions
def test_sum_spec_only_applies_to_numeric_columns():
    assert pc._map_val({"a": 1, "b": 2}, "owner", {"sum": ["a", "b"]}) is None
    assert pc._map_val({"a": "1,000", "b": "$2"}, "market_value", {"sum": ["a", "b"]}) == 1002.0


def test_squash_collapses_internal_padding():
    assert pc._map_val({"x": "CHESTER               SC"}, "owner", "x") == "CHESTER SC"
    assert pc._map_val({"a": "1 ", "b": "MAIN     ST"}, "address", ["a", "b"]) == "1 MAIN ST"


def test_tidy_mailing_only_splits_real_state_codes():
    assert pc._tidy_mailing("LYNCHBURG SC29080") == "LYNCHBURG SC 29080"
    assert pc._tidy_mailing("LYNCHBURG SC290804567") == "LYNCHBURG SC 290804567"
    assert pc._tidy_mailing("PO BOX ZZ12345") == "PO BOX ZZ12345"        # ZZ is not a state
    assert pc._tidy_mailing("120 TOLSON RD") == "120 TOLSON RD"


# ------------------------------------------------------------------------------ address overlay
OCFG = {"id_fields": ["PIN", "TMS"], "address": "ADDRESS", "unit": "UNIT"}


def test_overlay_prefers_the_row_without_a_unit_then_the_lowest_unit():
    rows = [
        {"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472", "UNIT": "APT 10"},
        {"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472", "UNIT": "APT 2"},
        {"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472 BLDG", "UNIT": None},
        {"PIN": 111.0, "TMS": "222", "ADDRESS": "5 OAK ST", "UNIT": "B"},
        {"PIN": 111.0, "TMS": "222", "ADDRESS": "5 OAK ST", "UNIT": "A"},
    ]
    idx = pc.build_address_overlay(rows, OCFG)
    # no-unit row wins even though its address text sorts later
    assert pc.overlay_address({"29612040003"}, idx) == "3936 HWY 472 BLDG"
    assert pc.overlay_address({"1120002045"}, idx) == "3936 HWY 472 BLDG"
    assert pc.overlay_address({"111"}, idx) == "5 OAK ST"


def test_overlay_unit_order_is_natural_not_lexical():
    assert pc._unit_key("2") < pc._unit_key("10") < pc._unit_key("B")
    assert pc._unit_key(None) < pc._unit_key("1")
    assert pc._unit_key("  ") == pc._unit_key(None) == (0, ())


def test_overlay_float_pin_matches_an_integer_or_text_primary_pin():
    idx = pc.build_address_overlay(
        [{"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472", "UNIT": None}], OCFG)
    for primary_pin in (29612040003, "29612040003", 29612040003.0):
        assert pc.overlay_address(pc._id_variants(primary_pin), idx) == "3936 HWY 472"
    assert pc.overlay_address(pc._id_variants("39308040324"), idx) is None


def test_overlay_choice_is_deterministic_when_points_tie():
    a = {"PIN": 5.0, "TMS": "5", "ADDRESS": "469 SOUTH SANTEE RD", "UNIT": None}
    b = {"PIN": 5.0, "TMS": "5", "ADDRESS": "467 SOUTH SANTEE RD", "UNIT": None}
    assert (pc.overlay_address({"5"}, pc.build_address_overlay([a, b], OCFG))
            == pc.overlay_address({"5"}, pc.build_address_overlay([b, a], OCFG))
            == "467 SOUTH SANTEE RD")


def test_horry_overlay_is_the_verified_layer_22():
    o = pc.PARCEL_LAYERS["Horry"]["address_overlay"]
    assert o["url"].endswith("/HorryCountyGISApp/MapServer/22/query")
    assert o["id_fields"] == ["PIN", "TMS"] and o["address"] == "ADDRESS" and o["unit"] == "UNIT"
    # the primary layer still has no situs field: the overlay is the only source
    assert "address" not in pc.PARCEL_LAYERS["Horry"]["map"]


# ------------------------------------------------------------------ refresh_county, offline
def _fake_get_text(layers):
    """layers: {url_prefix: [attribute dicts]}. Serves returnCountOnly and paged queries."""
    calls = []

    async def get_text(url, timeout=None, impersonate=None, **kw):
        calls.append(url)
        base, _, qs = url.partition("?")
        q = dict(urllib.parse.parse_qsl(qs))
        rows = layers[base]
        if q.get("returnCountOnly") == "true":
            return json.dumps({"count": len(rows)})
        off, n = int(q["resultOffset"]), int(q["resultRecordCount"])
        return json.dumps({"features": [{"attributes": r} for r in rows[off:off + n]]})

    get_text.calls = calls
    return get_text


P_URL = "https://gis.example.test/parcels/MapServer/0/query"
O_URL = "https://gis.example.test/parcels/MapServer/9/query"


def _cfg(state="SC", overlay=True):
    cfg = {"state": state, "url": P_URL, "id_fields": ["PINtext", "TMS"],
           "map": {"owner": "OwnerName", "owner_mailing": ["Street", "City"],
                   "market_value": "MarketProp"}}
    if overlay:
        cfg["address_overlay"] = {"url": O_URL, "id_fields": ["PIN", "TMS"],
                                  "address": "ADDRESS", "unit": "UNIT"}
    return cfg


PRIMARY = [
    {"PINtext": "29612040003", "TMS": "1120002045", "OwnerName": "TESTOWNER A",
     "Street": "9 ELM ST", "City": "CONWAY   SC", "MarketProp": 100000},
    {"PINtext": "39412040907", "TMS": "1660628307", "OwnerName": "TESTOWNER B",
     "Street": "PO BOX 1", "City": "LORIS    SC", "MarketProp": 50000},
    {"PINtext": "77700000001", "TMS": "7770000001", "OwnerName": "TESTOWNER C",
     "Street": "4 PINE ST", "City": "AYNOR    SC", "MarketProp": 75000},
]
OVERLAY = [
    {"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472", "UNIT": "APT 2"},
    {"PIN": 29612040003.0, "TMS": "1120002045", "ADDRESS": "3936 HWY 472", "UNIT": None},
    {"PIN": 39412040907.0, "TMS": "1660628307", "ADDRESS": "12 ORANGE AVE", "UNIT": None},
]


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    yield tmp_path
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()


def _run(county, layers, monkeypatch):
    import foreclosure_scraper.http_client as hc
    monkeypatch.setattr(hc, "get_text", _fake_get_text(layers))
    return asyncio.run(pc.refresh_county(county))


def test_refresh_fills_missing_addresses_from_the_overlay(cache_env, monkeypatch):
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Overlayville", _cfg())
    st = _run("Overlayville", {P_URL: PRIMARY, O_URL: OVERLAY}, monkeypatch)
    assert st["ok"] and st["downloaded"] == 3 and st["overlay_addresses"] == 2
    hit = pc.lookup("Overlayville", "29612040003", "SC")
    assert hit["address"] == "3936 HWY 472"                 # the no-unit row won
    assert hit["owner_mailing"] == "9 ELM ST CONWAY SC"
    assert hit["market_value"] == 100000.0
    assert pc.lookup("Overlayville", "1660628307", "SC")["address"] == "12 ORANGE AVE"   # via TMS
    assert "address" not in pc.lookup("Overlayville", "77700000001", "SC")   # no overlay point


def test_overlay_never_overwrites_an_address_the_primary_layer_has(cache_env, monkeypatch):
    cfg = _cfg()
    cfg["map"]["address"] = "SitusAddr"
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Ownsitus", cfg)
    prim = [dict(PRIMARY[0], SitusAddr="1 REAL SITUS RD")] + PRIMARY[1:]
    st = _run("Ownsitus", {P_URL: prim, O_URL: OVERLAY}, monkeypatch)
    assert st["ok"] and st["overlay_addresses"] == 1
    assert pc.lookup("Ownsitus", "29612040003", "SC")["address"] == "1 REAL SITUS RD"


def test_short_overlay_leaves_the_existing_cache_untouched(cache_env, monkeypatch):
    """A truncated overlay would regress a cache that had addresses last week."""
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Shortoverlay", _cfg())
    assert _run("Shortoverlay", {P_URL: PRIMARY, O_URL: OVERLAY}, monkeypatch)["ok"]
    before = pc._db_path("Shortoverlay", "SC").read_bytes()

    import foreclosure_scraper.http_client as hc
    fake = _fake_get_text({P_URL: PRIMARY, O_URL: OVERLAY})

    async def flaky(url, **kw):
        # the overlay reports 3 rows but every page comes back empty
        if url.startswith(O_URL) and "returnCountOnly" not in url:
            return json.dumps({"features": []})
        return await fake(url, **kw)

    monkeypatch.setattr(hc, "get_text", flaky)
    st = asyncio.run(pc.refresh_county("Shortoverlay"))
    assert st["ok"] is False and "overlay" in st["error"]
    assert st["overlay_downloaded"] == 0 and st["overlay_expected"] == 3
    assert pc._db_path("Shortoverlay", "SC").read_bytes() == before


def test_count_failure_on_the_overlay_is_reported_not_swallowed(cache_env, monkeypatch):
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Countfail", _cfg())
    import foreclosure_scraper.http_client as hc
    fake = _fake_get_text({P_URL: PRIMARY, O_URL: OVERLAY})

    async def boom(url, **kw):
        if url.startswith(O_URL):
            raise ConnectionError("down")
        return await fake(url, **kw)

    monkeypatch.setattr(hc, "get_text", boom)
    st = asyncio.run(pc.refresh_county("Countfail"))
    assert st["ok"] is False and st["error"].startswith("address overlay count")
    assert not pc._db_path("Countfail", "SC").exists()


def test_config_without_an_overlay_behaves_exactly_as_before(cache_env, monkeypatch):
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Plainville", _cfg(overlay=False))
    st = _run("Plainville", {P_URL: PRIMARY}, monkeypatch)
    assert st["ok"] and "overlay_addresses" not in st
    assert "address" not in pc.lookup("Plainville", "29612040003", "SC")


def test_incomplete_primary_download_is_still_refused(cache_env, monkeypatch):
    monkeypatch.setitem(pc.PARCEL_LAYERS, "Shortprimary", _cfg(overlay=False))
    import foreclosure_scraper.http_client as hc
    fake = _fake_get_text({P_URL: PRIMARY})

    async def short(url, **kw):
        if "returnCountOnly" not in url:
            return json.dumps({"features": []})
        return await fake(url, **kw)

    monkeypatch.setattr(hc, "get_text", short)
    st = asyncio.run(pc.refresh_county("Shortprimary"))
    assert st["ok"] is False and "incomplete" in st["error"]


def test_src_fields_handles_string_list_and_sum_specs():
    got = pc._src_fields(["PID"], {"owner": ["A", "B"], "market_value": {"sum": ["C", "D"]},
                                   "address": "E", "acreage": None})
    assert set(got.split(",")) == {"PID", "A", "B", "C", "D", "E"}
