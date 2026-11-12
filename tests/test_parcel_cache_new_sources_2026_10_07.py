"""Jasper SC and Beaufort SC parcel-cache sources (research of 2026-10-07).

docs/new_sources_2026-10-07_contact_and_facts.md picked these two as the highest-lift OPEN
sources not yet read for the weakest South Carolina counties. Nothing here touches the network.
Field NAMES and value SHAPES (the ten-digit "0"+ZIP5+ZIP4 Jasper ZIP, the spaced Jasper TMS,
Beaufort's 18-character PIN and "M/D/YYYY" sale date) are the real ones read on 2026-10-07;
every name, street and number below is invented.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

from foreclosure_scraper import parcel_cache as pc
from foreclosure_scraper.sensitive_fields import is_sensitive_field

REPO = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------------ config shape
def test_jasper_entry_is_well_formed():
    cfg = pc.PARCEL_LAYERS["Jasper"]
    assert cfg["state"] == "SC"
    assert cfg["url"].startswith("https://") and cfg["url"].endswith("/query")
    assert cfg["id_fields"] == ["TaxPIN"]
    assert set(cfg["map"]) <= set(pc._COLS)
    assert cfg["map"]["owner_mailing"] == ["Address2", "Address3", "ZipCode"]
    assert cfg["page_delay_s"] >= 1.6


def test_beaufort_sc_lives_outside_parcel_layers():
    """PARCEL_LAYERS is keyed by bare name; an SC Beaufort there would hijack the NC refresh."""
    assert "Beaufort" not in pc.PARCEL_LAYERS
    cfg = pc.SC_DUAL_LAYERS["Beaufort"]
    assert cfg["state"] == "SC"
    assert set(cfg["map"]) <= set(pc._COLS)
    assert cfg["page_delay_s"] >= 1.6
    # the capped / 4%-6% ratio figures are never a value column (tax_value is the ARV fallback)
    assert "tax_value" not in cfg["map"]
    assert cfg["map"]["market_value"] == "GisFile_Appraised"


def test_resolve_layer_cfg_is_unchanged_without_a_state():
    for st in (None, "NC", "nc"):
        cfg = pc.resolve_layer_cfg("Beaufort", st)
        assert cfg["state"] == "NC" and cfg["url"] == pc.NC_ONEMAP_URL
        assert cfg["where"] == "cntyname='Beaufort'"
    assert pc.resolve_layer_cfg("Jasper") is pc.PARCEL_LAYERS["Jasper"]
    assert pc.resolve_layer_cfg("Buncombe", "SC") == pc.resolve_layer_cfg("Buncombe")


def test_resolve_layer_cfg_sc_reads_only_the_sc_table():
    assert pc.resolve_layer_cfg("Beaufort", "SC") is pc.SC_DUAL_LAYERS["Beaufort"]
    assert pc.resolve_layer_cfg("beaufort", " sc ") is pc.SC_DUAL_LAYERS["Beaufort"]
    # a two-state name with no SC config yet: nothing, never the NC OneMap fallback
    assert pc.resolve_layer_cfg("Union", "SC") is None
    assert pc.resolve_layer_cfg("Cherokee", "SC") is None
    assert pc._db_path("Beaufort", "SC").name == "beaufort_sc.sqlite"


def _all_configs():
    yield from pc.PARCEL_LAYERS.items()
    yield from pc.SC_DUAL_LAYERS.items()
    yield "NC OneMap", pc.nc_onemap_cfg("Wake")


@pytest.mark.parametrize("name,cfg", list(_all_configs()))
def test_no_mapped_field_looks_sensitive(name, cfg):
    """_download_rows drops SSN/licence/birth-date-looking columns; a config that MAPPED one
    would silently lose that column, so none may."""
    fields = pc._src_fields(cfg["id_fields"], cfg["map"]).split(",")
    assert not [f for f in fields if is_sensitive_field(f)], name


# ------------------------------------------------------------------------------ row mapping
def _map(cfg: dict, row: dict) -> dict:
    return {c: pc._map_val(row, c, cfg["map"].get(c)) for c in pc._COLS}


JASPER_ROW = {
    "TaxPIN": "081-00 -01-024", "Expr2": "081-00 -01-024", "Expr3": "TESTOWNER JANE Q",
    "Address1": "% TEST CAREOF", "Address2": "123 SAMPLE PINE LN", "Address3": "HARDEEVILLE  SC",
    "ZipCode": "0299270000", "StreetNumberE911": "45", "StreetNameE911": "MADEUP OAK RD",
    "TotMarketAppr": 88400, "TotNumberAcres": 1, "Consideration": 65000, "YearBuilt": 0,
}


def test_jasper_row_maps_mailing_situs_value_and_sale():
    out = _map(pc.PARCEL_LAYERS["Jasper"], JASPER_ROW)
    assert out["owner"] == "TESTOWNER JANE Q"
    assert out["owner_mailing"] == "123 SAMPLE PINE LN HARDEEVILLE SC 29927"   # no care-of line
    assert out["address"] == "45 MADEUP OAK RD"
    assert out["market_value"] == 88400.0
    assert out["acreage"] == 1.0
    assert pc.sale_amount(out["sale_price"]) == 65000.0
    assert out["sale_date"] is None and out["living_sqft"] is None


def test_jasper_zip_plus4_is_kept_and_an_out_of_state_mailing_survives():
    row = dict(JASPER_ROW, Address2="PO BOX 77", Address3="SAVANNAH GA", ZipCode="0314011234")
    assert _map(pc.PARCEL_LAYERS["Jasper"], row)["owner_mailing"] == "PO BOX 77 SAVANNAH GA 31401-1234"


def test_jasper_board_tms_with_its_embedded_space_matches_the_layer_id():
    keys = set()
    for f in pc.PARCEL_LAYERS["Jasper"]["id_fields"]:
        keys |= pc._id_variants(JASPER_ROW.get(f))
    board_pid = "081-00 -01-024"                 # qPayBill rows carry the same spaced shape
    assert {k for k, _t in pc._lookup_candidates(board_pid)} & keys


BEAUFORT_ROW = {
    "GisFile_PIN": "R600 012 00A 0123 0000", "GisFile_Owner1": "TESTOWNER HOLDINGS LLC",
    "GisFile_SitusAddre": "17 INVENTED MARSH DR", "GisFile_MailingAdd": "900 EXAMPLE BLVD STE 5",
    "GisFile_City": "BLUFFTON", "GisFile_State": "SC", "GisFile_ZIP": "29910-1234",
    "GisFile_Appraised": 412000, "GisFile_Acres": "0.31", "GisFile_ResSquareF": 1850,
    "GisFile_ClassCode": "SAMPLE RESIDENTIAL", "GisFile_SalePrice": "$301,500",
    "GisFile_SaleDate": "3/14/2019", "GisFile_Assessed": 16480, "GisFile_Capped": 380000,
}


def test_beaufort_row_maps_every_column():
    out = _map(pc.SC_DUAL_LAYERS["Beaufort"], BEAUFORT_ROW)
    assert out["owner"] == "TESTOWNER HOLDINGS LLC"
    assert out["address"] == "17 INVENTED MARSH DR"
    assert out["owner_mailing"] == "900 EXAMPLE BLVD STE 5 BLUFFTON SC 29910-1234"
    assert out["market_value"] == 412000.0           # Appraised, never Assessed or Capped
    assert out["tax_value"] is None
    assert out["acreage"] == pytest.approx(0.31)
    assert out["living_sqft"] == 1850.0
    assert out["land_use"] == "SAMPLE RESIDENTIAL"
    assert pc.sale_amount(out["sale_price"]) == 301500.0
    assert out["sale_date"] == "3/14/2019"


def test_beaufort_pin_matches_the_board_spelling():
    keys = pc._id_variants(BEAUFORT_ROW["GisFile_PIN"])
    assert {k for k, _t in pc._lookup_candidates("R600 012 00A 0123 0000")} & keys


# ------------------------------------------------------------------------------ _tidy_mailing
@pytest.mark.parametrize("text,want", [
    ("1 TEST ST RIDGELAND SC 0299360000", "1 TEST ST RIDGELAND SC 29936"),
    ("1 TEST ST RIDGELAND SC 0299365555", "1 TEST ST RIDGELAND SC 29936-5555"),
    ("1 TEST ST RIDGELAND S C 0299360000", "1 TEST ST RIDGELAND SC 29936"),     # spaced state
    ("1 TEST ST SAMPLETOWN TEXAS 0750010000", "1 TEST ST SAMPLETOWN TEXAS 75001"),
    ("1 TEST ST TOWN X Y 0299360000", "1 TEST ST TOWN X Y 29936"),          # XY is no state
    ("PO BOX 12 0299360000", "PO BOX 12 0299360000"),                        # after a number
    ("1 TEST ST RIDGELAND SC 1299360000", "1 TEST ST RIDGELAND SC 1299360000"),  # no leading 0
    ("1 TEST ST RIDGELAND SC 029936000", "1 TEST ST RIDGELAND SC 029936000"),    # nine digits
    ("LYNCHBURG SC29080", "LYNCHBURG SC 29080"),                                # Florence rule kept
])
def test_tidy_mailing_zero_led_zip10(text, want):
    assert pc._tidy_mailing(text) == want


# ------------------------------------------------------------------------------ refresh, offline
def _fake_get_text(layers, calls):
    async def get_text(url, timeout=None, impersonate=None, **kw):
        calls.append(url)
        base, _, qs = url.partition("?")
        q = dict(urllib.parse.parse_qsl(qs))
        rows = layers[base]
        if q.get("returnCountOnly") == "true":
            return json.dumps({"count": len(rows)})
        off, n = int(q["resultOffset"]), int(q["resultRecordCount"])
        return json.dumps({"features": [{"attributes": r} for r in rows[off:off + n]]})
    return get_text


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    yield tmp_path
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()


def test_refresh_beaufort_sc_writes_the_sc_file_and_sleeps_between_pages(cache_env, monkeypatch):
    import foreclosure_scraper.http_client as hc
    url = pc.SC_DUAL_LAYERS["Beaufort"]["url"]
    second = dict(BEAUFORT_ROW, GisFile_PIN="R600 012 00A 0124 0000",
                  GisFile_SitusAddre="19 INVENTED MARSH DR")
    calls: list = []
    monkeypatch.setattr(hc, "get_text", _fake_get_text({url: [BEAUFORT_ROW, second]}, calls))
    monkeypatch.setitem(pc.SC_DUAL_LAYERS["Beaufort"], "page", 1)     # force two pages
    slept: list = []

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr(pc.asyncio, "sleep", fake_sleep)

    st = asyncio.run(pc.refresh_county("Beaufort", "SC"))
    assert st["ok"] and st["downloaded"] == 2
    assert (cache_env / "beaufort_sc.sqlite").exists()
    assert not (cache_env / "beaufort_nc.sqlite").exists()
    # one sleep before each page request, none before the count
    assert len(calls) == 3 and slept == [1.7, 1.7]
    hit = pc.lookup("Beaufort", "R600 012 00A 0123 0000", "SC")
    assert hit["owner_mailing"] == "900 EXAMPLE BLVD STE 5 BLUFFTON SC 29910-1234"
    assert hit["address"] == "17 INVENTED MARSH DR"
    assert pc.lookup("Beaufort", "R600 012 00A 0123 0000", "NC") is None
    assert pc.lookup("Beaufort", "R600 012 00A 0123 0000") is None       # no state: refuse


def test_download_drops_sensitive_columns_as_it_reads(monkeypatch):
    import foreclosure_scraper.http_client as hc
    base = "https://gis.example.test/layer/0/query"
    row = {"PIN": "1", "OWNER": "TESTOWNER", "OWNER_SSN": "000-00-0000", "DOB": "1900-01-01",
           "DRIVERS_LIC": "X0", "CLASSNAME": "RES"}
    monkeypatch.setattr(hc, "get_text", _fake_get_text({base: [row]}, []))
    rows, exp = asyncio.run(pc._download_rows(base, "1=1", "PIN,OWNER,CLASSNAME"))
    assert exp == 1
    assert rows == [{"PIN": "1", "OWNER": "TESTOWNER", "CLASSNAME": "RES"}]


def test_refresh_jasper_offline(cache_env, monkeypatch):
    import foreclosure_scraper.http_client as hc
    url = pc.PARCEL_LAYERS["Jasper"]["url"]
    monkeypatch.setattr(hc, "get_text", _fake_get_text({url: [JASPER_ROW]}, []))

    async def fake_sleep(s):
        return None
    monkeypatch.setattr(pc.asyncio, "sleep", fake_sleep)
    st = asyncio.run(pc.refresh_county("Jasper"))
    assert st["ok"] and st["downloaded"] == 1
    hit = pc.lookup("Jasper", "081-00 -01-024", "SC")
    assert hit["owner_mailing"] == "123 SAMPLE PINE LN HARDEEVILLE SC 29927"
    assert hit["market_value"] == 88400.0


# ------------------------------------------------------------------------------ refresh script
def _script():
    spec = importlib.util.spec_from_file_location("refresh_parcel_cache",
                                                  REPO / "scripts" / "refresh_parcel_cache.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_script_targets():
    mod = _script()
    assert mod.targets(["Beaufort:SC", "Buncombe", "jasper:sc"]) == [
        ("Beaufort", "SC"), ("Buncombe", None), ("jasper", "SC")]
    default = mod.targets([])
    assert ("Beaufort", "SC") in default and ("Buncombe", None) in default
    assert ("Beaufort", None) not in default


# ------------------------------------------------------------------------------ lift measurement
def _measure_mod():
    import sys as _sys
    _sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("measure_parcel_cache_lift",
                                                  REPO / "scripts" / "measure_parcel_cache_lift.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_measure_counts_id_join_fills_and_unapplied_mailing(cache_env, monkeypatch):
    import foreclosure_scraper.http_client as hc
    url = pc.PARCEL_LAYERS["Jasper"]["url"]
    other = dict(JASPER_ROW, TaxPIN="081-00 -01-025", Expr3="TESTOWNER JOHN R")
    monkeypatch.setattr(hc, "get_text", _fake_get_text({url: [JASPER_ROW, other]}, []))

    async def fake_sleep(s):
        return None
    monkeypatch.setattr(pc.asyncio, "sleep", fake_sleep)
    assert asyncio.run(pc.refresh_county("Jasper"))["ok"]
    mod = _measure_mod()
    rows = [
        # parcel id, no mailing, owner agrees: the join adds mailing, value and sale
        {"state": "SC", "county": "Jasper", "parcel_id": "081-00 -01-024",
         "owner_name": "TESTOWNER JANE Q", "listing_type": "tax_lien", "raw": {}},
        # already has a mailing: nothing added for mail, value still added
        {"state": "SC", "county": "Jasper", "parcel_id": "081-00 -01-025",
         "owner_name": "TESTOWNER JOHN R", "listing_type": "tax_lien",
         "raw": {"gis": {"mailing": "1 OTHER ST TESTTOWN SC 29999"}}},
        # an overage claim is never joined
        {"state": "SC", "county": "Jasper", "parcel_id": "081-00 -01-024",
         "owner_name": "TESTCLAIMANT", "listing_type": "tax_sale_overage", "raw": {}},
    ]
    res = mod.measure(rows, {("jasper", "SC")})
    c = res["targets"]["SC:Jasper"]
    assert c["rows"] == 3 and c["id_join_hit"] == 2
    assert c["base_mail"] == 1 and c["after_mail"] == 2
    assert c["id_join_adds_value"] == 2 and c["after_value"] == 2
    assert c["id_join_adds_sale"] == 2
    assert res["unapplied_cached_mailing_total"] == 1        # only the first row
    assert res["unapplied_cached_mailing_top"] == [("SC:Jasper", 1)]
