"""Dead service and host URLs repaired 2026-09-21.

Greenville: the county removed GreenvilleJS/Map_Layers_JS (the old URL answers HTTP 200 with a
JSON "Service ... not found" body, which is why nothing noticed). The parcel layer now lives at
GreenvilleNJ/QueryLayers/MapServer/0 and the sales layer no longer exists.

CivicPlus: four county hosts stopped resolving (curl exit 6). Each replacement was fetched once
on 2026-09-21 and answered HTTP 200 with the county's own page title. These tests are offline
and pin the constants; they do not resolve DNS.
"""
from __future__ import annotations

import asyncio

import foreclosure_scraper.scrapers.counties_nc.nc_civicplus_tax_sale as civ
import foreclosure_scraper.scrapers.counties_sc.greenville_hard_distress as gv


# --------------------------------------------------------------------------- Greenville

def test_greenville_points_at_the_replacement_service():
    assert gv.GIS == "https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer"
    assert gv.PARCEL_LAYER == gv.GIS + "/0"
    assert "GreenvilleJS" not in gv.GIS and "Map_Layers_JS" not in gv.PARCEL_LAYER


def test_the_sales_layer_is_gone_and_the_join_makes_no_request():
    assert gv.SALES_LAYER is None

    class Boom:
        async def get(self, *a, **kw):
            raise AssertionError("no request may be made for a layer that does not exist")
        post = get

    assert asyncio.run(gv.fetch_sales_by_pin(Boom(), ["0012000101200"])) == {}


def test_the_parcel_field_list_asks_for_the_street_parts_the_new_layer_carries():
    for f in ("STRNUM", "STRPRE", "LOCATE", "STRTYP", "STRSUF", "TOTTAX", "PAIDDATE", "OWNAM1"):
        assert f in gv.PARCEL_FIELDS.split(","), f


def test_situs_is_built_from_all_five_parts():
    # Verified live 2026-09-21: STRNUM 209, STRPRE W, LOCATE PARK, STRTYP AVE.
    assert gv._situs("209", "PARK", "AVE", "W", "") == "209 W PARK AVE"
    assert gv._situs("14", "OLD ANDERSON", "RD") == "14 OLD ANDERSON RD"
    assert gv._situs("", "OLD ANDERSON", "RD") == "OLD ANDERSON RD"
    assert gv._situs("00000", "PARK") == "PARK"                 # the vacant-lot filler
    assert gv._situs("5", "MAIN", "ST", None, "N") == "5 MAIN ST N"


def test_a_listing_takes_the_street_type_from_the_parcel_layer():
    attrs = {"PIN": "0012000101200", "OWNAM1": "ROE JOHN", "TOTTAX": 825.5, "PAIDDATE": None,
             "STRNUM": "209", "STRPRE": "W", "LOCATE": "PARK", "STRTYP": "AVE", "STRSUF": "",
             "STREET": "PO BOX 1", "CITY": "GREENVILLE", "STATE": "SC", "ZIP5": "29601",
             "PROPTYPE": "RESIDENTIAL", "IMPROVED": "YES"}
    li = gv.build_listing("0012000101200", attrs, None)
    assert li.street_address == "209 W PARK AVE"
    # An old-style sale row still wins nothing over the parcel layer's own type.
    li2 = gv.build_listing("0012000101200", attrs, None, sale={"STRTYP": "ZZ"})
    assert li2.street_address == "209 W PARK AVE"
    # A parcel row with no type falls back to the sale's, as before.
    bare = {**attrs, "STRTYP": "", "STRPRE": ""}
    assert gv.build_listing("0012000101200", bare, None, sale={"STRTYP": "ST"}).street_address == "209 PARK ST"


# --------------------------------------------------------------------------- CivicPlus

DEAD = ("grahamcounty.gov", "northamptonnc.gov", "tyrrellcountync.gov", "washingtoncountync.gov")
FIXED = {
    "Graham": "https://grahamcounty.org",
    "Northampton": "https://www.northamptonnc.com",
    "Tyrrell": "http://tyrrellcounty.org",          # http only: the host redirects to /en/
    "Washington": "https://washconc.org",
}


def test_the_four_dead_hosts_are_gone_and_the_replacements_are_pinned():
    for county, url in FIXED.items():
        assert civ.CIVICPLUS_COUNTIES[county] == url
    joined = " ".join(civ.CIVICPLUS_COUNTIES.values())
    for host in DEAD:
        assert host not in joined, host


def test_every_civicplus_base_is_a_bare_http_or_https_origin():
    for county, url in civ.CIVICPLUS_COUNTIES.items():
        assert url.startswith(("http://", "https://")), county
        assert not url.endswith("/"), county
        assert url.count("/") == 2, f"{county}: {url} has a path; it must be an origin"
