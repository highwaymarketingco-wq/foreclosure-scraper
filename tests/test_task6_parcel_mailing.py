"""Task-6 parcel/mailing endpoint corrections: Gaston, Cleveland, Transylvania.

Guards the three behaviours that a future schema drift or a well-meaning
"cleanup" would silently undo:

  1. Cleveland's upstream CAMA join truncates situs/owner at 20 chars, and the
     untruncated values live in sibling columns on the SAME layer.
  2. Gaston's county layer carries the vacant / absentee / owner-changed
     columns the cohort flags are derived from, with blank mailing state
     meaning "unknown", not "out of state".
  3. Transylvania's layer has NO situs column, so it must never run an address
     LIKE (it used to match the property street against a field holding the
     second owner's NAME).

Fixtures are verbatim `attributes` payloads captured live on 2026-08-03.
Hermetic — no network.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import enrichment_arcgis as ga
from foreclosure_scraper.enrichment_owner_mailing import COUNTY_GIS
from foreclosure_scraper.models import Listing

from ._arcgis_fakes import FakeHttp


def _listing(**kw) -> Listing:
    """Listing requires source_url; everything else here is optional."""
    kw.setdefault("source", "test")
    kw.setdefault("source_url", "https://example.test/lead")
    return Listing(**kw)


# --- live-captured rows -----------------------------------------------------

# gis.clevelandcounty.com .../Basemap/Parcels/MapServer/0, PIN 14976.
# COUNTY_ADDRESS/COUNTY_OWNER_1 are the 20-char-capped CAMA columns;
# LOCATE_ADDRESS/GIS_Owner1 are the untruncated siblings.
CLEVELAND_ROW = {
    "GIS_PID": "14976",
    "COUNTY_ADDRESS": "1127 MARYS GROVE CHU",
    "LOCATE_ADDRESS": "1127 MARYS GROVE CHURCH RD",
    "COUNTY_OWNER_1": "CARPENTER JEREMY L",
    "GIS_Owner1": "CARPENTER JEREMY L",
    "COUNTY_MAILING_ADDRESS": "1127 MARYS GROVE CH",
    "COUNTY_CITY": "SHELBY",
    "COUNTY_STATE": "NC",
    "COUNTY_ZIP": "28150",
    "COUNTY_TOTAL_VALUE": 309496,
    "COUNTY_DEED": "1798",
    "COUNTY_PAGE": "1292",
}

# Same layer, a row where the owner name IS truncated and recoverable.
CLEVELAND_TRUNC_OWNER = {
    "COUNTY_ADDRESS": "CAMP CREEK CHURCH RD",
    "LOCATE_ADDRESS": "2431 CAMP CREEK CHURCH RD",
    "COUNTY_OWNER_1": "AMPARANO LUIS EDUARD",
    "GIS_Owner1": "AMPARANO LUIS EDUARDO QUINTANA",
}

# gis.gastoncountync.gov .../PublicGIS/Parcels/FeatureServer/11, PIN 3546-54-4082.
GASTON_ROW = {
    "PIN": "3546-54-4082",
    "PHYSSTRADD": "718 NORTON DR",
    "CURR_NAME1": "ADAMS CHRISTOPHER",
    "CURR_ADDR1": "718 NORTON DR",
    "CURR_CITY": "GASTONIA",
    "CURR_STATE": "NC",
    "CURR_ZIPCODE": "280520000",
    "PRVYRNAME1": "ADAMS CHRISTOPHER",
    "FMV_TOTAL": 198260.0,
    "DEED_BOOK": "4106",
    "DEED_PAGE": "0491",
    "SALESAMT": 25000.0,
    "YEARBLT": 1972,
    "XBEDRM": 3,
    "XBATHS": 2,
    "CALCAC": 0.34,
    "VacantImpro": "Improved",
    "Latitude": 35.27988479,
    "Longitude": -81.19331189,
}


# --- 1. Cleveland truncation repair -----------------------------------------

def test_repair_cleveland_recovers_truncated_situs():
    a = dict(CLEVELAND_ROW)
    ga._repair_cleveland(a)
    assert a["COUNTY_ADDRESS"] == "1127 MARYS GROVE CHURCH RD"


def test_repair_cleveland_recovers_truncated_owner():
    a = dict(CLEVELAND_TRUNC_OWNER)
    ga._repair_cleveland(a)
    assert a["COUNTY_OWNER_1"] == "AMPARANO LUIS EDUARDO QUINTANA"
    assert a["COUNTY_ADDRESS"] == "2431 CAMP CREEK CHURCH RD"


def test_repair_cleveland_never_downgrades_to_a_shorter_sibling():
    """LOCATE_ADDRESS is only 89.9% populated. A blank/short sibling must not
    clobber a good COUNTY_ADDRESS."""
    for sibling in ("", None, "<Null>", "1127 MARYS"):
        a = {"COUNTY_ADDRESS": "1127 MARYS GROVE CHU", "LOCATE_ADDRESS": sibling}
        ga._repair_cleveland(a)
        assert a["COUNTY_ADDRESS"] == "1127 MARYS GROVE CHU", sibling


def test_repaired_situs_and_owner_are_what_the_aliases_read():
    """The repair has to happen before _pick, otherwise the aliases still see
    the truncated column."""
    a = dict(CLEVELAND_TRUNC_OWNER)
    ga._repair_cleveland(a)
    assert ga._pick(a, ga.FIELD_ALIASES["site_address"]) == "2431 CAMP CREEK CHURCH RD"
    assert ga._pick(a, ga.FIELD_ALIASES["owner_name"]) == "AMPARANO LUIS EDUARDO QUINTANA"


# --- 2. Gaston cohort flags -------------------------------------------------

@pytest.mark.parametrize("attrs,expect", [
    ({"VacantImpro": "Vacant"}, {"vacant": True}),
    ({"VacantImpro": "Improved"}, {"vacant": False}),
    ({"CURR_STATE": "FL"}, {"absentee": True}),
    ({"CURR_STATE": "NC"}, {"absentee": False}),
    ({"PRVYRNAME1": "SMITH JOHN", "CURR_NAME1": "JONES ANN"}, {"owner_changed": True}),
    ({"PRVYRNAME1": "SMITH JOHN", "CURR_NAME1": "smith john"}, {"owner_changed": False}),
])
def test_cohort_flags(attrs, expect):
    assert ga._cohort_flags(attrs) == expect


def test_blank_mailing_state_is_unknown_not_absentee():
    """Counting the 43 blank-state rows as absentee is exactly what turns the
    verified 10,340 absentee / 2,962 both-cohort into 10,383 / 2,997."""
    for blank in ("", "   ", None):
        assert "absentee" not in ga._cohort_flags({"CURR_STATE": blank})


def test_cohort_flags_absent_when_columns_absent():
    """A county without these columns must get no flag at all — an emitted
    False would read as a verified negative."""
    assert ga._cohort_flags({"PIN": "123", "OwnerName": "X"}) == {}


def test_apply_attrs_writes_cohort_flags_and_does_not_clobber():
    li = _listing(state="NC", county="Gaston", street_address="718 NORTON DR")
    ga._apply_attrs(li, dict(GASTON_ROW))
    g = li.raw["gis"]
    assert g["vacant"] is False and g["absentee"] is False and g["owner_changed"] is False
    assert g["owner"] == "ADAMS CHRISTOPHER"
    assert g["mailing"] == "718 NORTON DR"

    # a second pass must not overwrite an existing flag
    li.raw["gis"]["vacant"] = True
    ga._apply_attrs(li, dict(GASTON_ROW))
    assert li.raw["gis"]["vacant"] is True


def test_gaston_row_fills_beds_baths_and_value():
    """Bed/bath and FMV_TOTAL are the net-new columns the old city layer lacked."""
    li = _listing(state="NC", county="Gaston", street_address="718 NORTON DR")
    ga._apply_attrs(li, dict(GASTON_ROW))
    assert li.bedrooms == 3
    assert li.bathrooms == 2
    assert li.tax_value == 198260.0
    assert li.year_built == 1972
    assert li.raw["gis"]["last_sale"]["amount"] == 25000.0
    assert li.raw["gis"]["last_sale"]["book"] == "4106"


# --- 3. registry invariants -------------------------------------------------

def test_gaston_points_at_county_layer_11_not_zero():
    url = ga.NC_GIS["Gaston"]["url"]
    assert "gis.gastoncountync.gov" in url
    assert "/FeatureServer/11/query" in url
    assert "cogserver.gastonianc.gov" not in url


def test_cleveland_points_at_the_layer_that_has_an_address():
    cfg = ga.NC_GIS["Cleveland"]
    assert "Basemap/Parcels/MapServer/0" in cfg["url"]
    assert cfg["addr_field"] == "COUNTY_ADDRESS"


def test_transylvania_has_no_situs_column_configured():
    """ADDRESS_3 is the owner's MAILING street on that layer, not the situs."""
    assert ga.NC_GIS["Transylvania"]["addr_field"] is None


@pytest.mark.parametrize("county", ["Gaston", "Cleveland"])
def test_wired_counties_enumerate_outfields_and_never_use_star(county):
    """Standing privacy safeguard: endpoints we wire name their columns, so a
    county quietly publishing a sensitive column (Lincoln NC has historically
    exposed TCSSN1/TCSSN2 on a public layer) can't land in li.raw via '*'."""
    out = ga.NC_GIS[county].get("out_fields")
    assert out, f"{county} must pin outFields"
    assert "*" not in out
    fields = {f.strip().lower() for f in out.split(",")}
    assert fields, "outFields must be a non-empty comma list"
    for banned in ("ssn", "tcssn1", "tcssn2", "dob", "birth"):
        assert not any(banned in f for f in fields)


def test_transylvania_mailing_spec_is_field_correct():
    spec = COUNTY_GIS["NC:Transylvania"]
    # ADDRESS_1 is the second owner's NAME — it belongs in owner, never in mail
    assert "ADDRESS_1" in spec["owner"]
    assert "ADDRESS_1" not in spec["mail"]
    # mailing city/state/zip were missing entirely, so out_of_state could never fire
    assert spec.get("mail_state") == "STATE"
    for f in ("CITY", "STATE", "ZIP_CODE"):
        assert f in spec["mail"]
    # LEGAL_ADDR is a legal description, not a situs
    assert spec["situs"] == []


def test_gaston_mailing_spec_repointed_to_county_layer():
    url = COUNTY_GIS["NC:Gaston"]["url"]
    assert "gis.gastoncountync.gov" in url and url.endswith("/FeatureServer/11")


# --- 4. query plumbing ------------------------------------------------------

def test_arcgis_query_sends_the_pinned_outfields():
    http = FakeHttp(routes={"query": {"features": [
        {"attributes": dict(CLEVELAND_ROW), "geometry": {"x": -81.5, "y": 35.3}},
    ]}})
    pinned = ga.NC_GIS["Cleveland"]["out_fields"]
    rows = asyncio.run(ga._arcgis_query(
        http, ga.NC_GIS["Cleveland"]["url"], "COUNTY_ADDRESS",
        "1127 Marys Grove Church Rd", "1127", out_fields=pinned))
    assert rows
    _, _, params = http.calls[0]
    assert params["outFields"] == pinned
    assert params["outFields"] != "*"


def test_arcgis_query_repairs_truncation_before_returning():
    http = FakeHttp(routes={"query": {"features": [
        {"attributes": dict(CLEVELAND_TRUNC_OWNER)},
    ]}})
    rows = asyncio.run(ga._arcgis_query(
        http, ga.NC_GIS["Cleveland"]["url"], "COUNTY_ADDRESS",
        "2431 Camp Creek Church Rd", "2431",
        out_fields=ga.NC_GIS["Cleveland"]["out_fields"]))
    assert rows[0]["COUNTY_ADDRESS"] == "2431 CAMP CREEK CHURCH RD"
    assert rows[0]["COUNTY_OWNER_1"] == "AMPARANO LUIS EDUARDO QUINTANA"


def test_default_outfields_star_is_unchanged_for_unwired_counties():
    """The other ~18 counties still rely on '*' for their alias coverage."""
    http = FakeHttp(routes={"query": {"features": []}})
    asyncio.run(ga._arcgis_query(http, "https://example/query", "Address", "1 Main St"))
    assert http.calls[0][2]["outFields"] == "*"


def test_enrich_never_address_queries_a_county_with_no_situs(monkeypatch):
    """Transylvania regression: addr_field=None must skip the address path
    entirely rather than falling through to _detect_addr_field, which picked
    ADDRESS_1 (the second owner's name) and produced bogus matches."""
    calls: list[str] = []

    async def boom(*a, **kw):
        calls.append("queried")
        return []

    monkeypatch.setattr(ga, "_arcgis_query", boom)
    monkeypatch.setattr(ga, "_detect_addr_field", boom)

    li = _listing(state="NC", county="Transylvania",
                  street_address="123 Whitewater Cove Rd")
    asyncio.run(ga.enrich([li]))
    assert calls == []
