"""Layers added to the config-driven ArcGIS distress reader by the 2026-09-21 county-breadth
research (docs/county_breadth_research_2026-09-21.md).

Offline: the response shape is mocked from a live row (field names and value shapes are the
real ones, the case data is invented). The two things worth pinning are that the server-side
filter really isolates STRUCTURE distress out of a code-case file, and that only the
requested, non-PII fields ever go on the wire.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers as M
from foreclosure_scraper.models import ListingType

COLUMBIA = "columbia_code_vacant_boarded"


def _lay(slug):
    return next(x for x in M.LAYERS if x.slug == slug)


def _resp(body, status=200):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    return r


def _client(handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = handler
        yield stub
    return _cm


def test_columbia_layer_is_registered_with_a_structure_only_filter():
    lay = _lay(COLUMBIA)
    assert (lay.state, lay.county) == ("SC", "Richland")
    assert lay.listing_type == ListingType.DISTRESSED and lay.process == "code_enforcement"
    assert lay.url.endswith("/CodeViolationProperty/FeatureServer/0")
    # only the two OPEN case states, and only structure-level problems
    assert "CaseStatus IN ('In Violation','Open')" in lay.where
    for frag in ("%Boarded Building%", "%Demolition%", "Vacant Building%"):
        assert frag in lay.where
    # a yard, parking or roll-cart case must not be able to slip through the filter text
    for noise in ("Vacant Lot", "Roll Cart", "Parking", "Vehicle"):
        assert noise not in lay.where


def test_columbia_requests_only_case_fields_and_no_wildcard():
    lay = _lay(COLUMBIA)
    assert "*" not in lay.fields
    assert set(lay.fields) == {"CaseNum", "OpenedDate", "Problem", "CaseStatus", "ADDRESS"}


def test_columbia_row_becomes_an_address_only_lead():
    lay = _lay(COLUMBIA)
    li = M._to_listing({"CaseNum": "VBR-2022-0113", "OpenedDate": 1603843200000,
                        "Problem": "Residential Boarded Building",
                        "CaseStatus": "In Violation",
                        "ADDRESS": "1020  TREE St"}, lay)
    assert li is not None
    assert (li.state, li.county) == ("SC", "Richland")
    assert li.street_address == "1020  TREE St"
    assert li.parcel_id is None and li.owner_name is None       # the layer has neither
    assert li.foreclosure_process == "code_enforcement"
    assert "Residential Boarded Building" in li.description


def test_columbia_row_without_an_address_is_dropped():
    lay = _lay(COLUMBIA)
    assert M._to_listing({"CaseNum": "X", "Problem": "Residential Demolition",
                          "ADDRESS": "  "}, lay) is None


def test_columbia_query_carries_the_filter_and_the_explicit_field_list(monkeypatch):
    seen = {}

    async def get(url, **kw):
        if "CodeViolationProperty" in url:
            seen.update(kw["params"])
        return _resp({"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    asyncio.run(M.ArcgisDistressLayers().fetch())
    lay = _lay(COLUMBIA)
    assert seen["where"] == lay.where
    assert seen["outFields"] == ",".join(lay.fields)
    assert seen["returnGeometry"] == "false"


# ----------------------------------------------------------------------------- Greenville
GREENVILLE = "greenville_unpaid_tax_parcels"


def test_greenville_layer_targets_the_moved_service_and_only_unpaid_bills():
    lay = _lay(GREENVILLE)
    assert (lay.state, lay.county) == ("SC", "Greenville")
    # the GreenvilleJS/Map_Layers_JS service is gone; the replacement is arcgis3/.../GreenvilleNJ
    assert "/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0" in lay.url
    assert "GreenvilleJS" not in lay.url
    assert lay.where == "TOTTAX > 0 AND PAIDDATE IS NULL"
    assert lay.listing_type == ListingType.TAX_LIEN and lay.process == "tax"
    # the slug must carry "tax": enrichment_tax_owed's generic scan is gated on it
    assert "tax" in lay.slug


def test_greenville_never_maps_the_owner_mailing_city_onto_the_property():
    """STREET/CITY/STATE/ZIP5 on this layer are the OWNER's mailing address. Mapping CITY
    as the property city would put the owner's home town on every absentee's property."""
    lay = _lay(GREENVILLE)
    assert lay.city is None and lay.zip_ is None
    assert not ({"STREET", "CITY", "STATE", "ZIP5", "DESCR"} & set(lay.fields))


def test_greenville_row_carries_owner_situs_parcel_value_and_the_bill():
    lay = _lay(GREENVILLE)
    li = M._to_listing({"PIN": "0006010103600", "OWNAM1": "TESTOWNER HOLDINGS LLC",
                        "OWNAM2": None, "STRNUM": "2", "STRPRE": "", "LOCATE": "EDGE",
                        "STRTYP": "CT", "STRSUF": None, "TAXMKTVAL": 293010,
                        "TOTTAX": 7013.5, "ACCTNO": "202500019441577001",
                        "PROPTYPE": "RESIDENTIAL"}, lay)
    assert li.parcel_id == "0006010103600"
    assert li.street_address == "2 EDGE CT"
    assert li.owner_name == "TESTOWNER HOLDINGS LLC"
    assert li.tax_value == 293010.0
    blk = li.raw["arcgis_distress"]
    assert blk["amount_owed"] == 7013.5            # the key enrichment_tax_owed scans
    assert blk["TOTTAX"] == 7013.5 and blk["ACCTNO"].startswith("2025")


def test_amount_owed_is_only_written_when_the_layer_declares_an_amount_field():
    columbia = _lay(COLUMBIA)
    assert columbia.amount is None
    li = M._to_listing({"CaseNum": "X", "Problem": "Residential Demolition",
                        "ADDRESS": "1 MAIN ST"}, columbia)
    assert "amount_owed" not in li.raw["arcgis_distress"]
    # a blank or zero bill is not an amount
    gv = _lay(GREENVILLE)
    li2 = M._to_listing({"PIN": "1", "OWNAM1": "X", "TOTTAX": 0, "STRNUM": "1",
                         "LOCATE": "A"}, gv)
    assert "amount_owed" not in li2.raw["arcgis_distress"]


def test_every_declared_amount_field_is_actually_requested():
    for lay in M.LAYERS:
        if lay.amount:
            assert lay.amount in lay.fields, f"{lay.slug} declares amount but never requests it"


def test_a_dead_greenville_host_does_not_sink_the_other_layers(monkeypatch):
    """gcgis.org already moved this service once. It is on the tolerate list, so a
    connection failure there must cost only its own rows, not all the others'."""
    import asyncio as aio

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(aio, "sleep", no_sleep)

    async def get(url, **kw):
        if "gcgis.org" in url:
            raise ConnectionError("Service not found")
        return _resp({"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    asyncio.run(M.ArcgisDistressLayers().fetch())      # must not raise PartialHarvest
