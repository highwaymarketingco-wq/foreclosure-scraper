"""The config-driven county distress-layer reader.

Built to close a measured gap: the 18 per-county enumeration docs list ~525
verified free endpoints and 263 are still unbuilt, most of them a single layer
that IS the signal and needs only a field mapping.

Two invariants matter more than the parsing:
  * outFields is never a wildcard — several of these layers carry the phone and
    email of the person who FILED the complaint, who is not a distressed owner.
  * a declared layer that fails is a hard failure, not a smaller number.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

import foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers as M
from foreclosure_scraper.layer_guard import PartialHarvest


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body if body is not None else {"features": []})
    return r


def _client(handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = handler
        yield stub
    return _cm


def test_outfields_is_never_a_wildcard():
    """A wildcard here would sweep up complainant phone/email from the Lincoln
    and Pickens layers. Pin it at the config level."""
    for lay in M.LAYERS:
        assert lay.fields, f"{lay.slug} declares no fields"
        assert "*" not in lay.fields, f"{lay.slug} requests a wildcard"


def test_no_complainant_contact_field_is_ever_requested():
    banned = {"name", "phone", "email", "pocphone", "pocemail", "pocfullname",
              "pocfirstname", "poclastname"}
    for lay in M.LAYERS:
        leak = {f for f in lay.fields if f.lower() in banned}
        assert not leak, f"{lay.slug} requests complainant PII: {leak}"


def test_requested_fields_reach_the_query(monkeypatch):
    seen = {}

    async def get(url, **kw):
        seen[url] = kw.get("params", {})
        return _resp(200, {"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    asyncio.run(M.ArcgisDistressLayers().fetch())
    assert seen, "no query issued"
    for params in seen.values():
        assert params["outFields"] != "*"
        assert params["returnGeometry"] == "false"


def test_arcgis_200_with_an_error_body_is_a_failure(monkeypatch):
    """ArcGIS answers 200 with an error payload. Treating that as an empty
    result is how a token wall or a renamed layer reads as 'no rows today'."""
    async def get(url, **kw):
        return _resp(200, {"error": {"code": 499, "message": "Token Required"}})

    monkeypatch.setattr(M, "client", _client(get))
    with pytest.raises(PartialHarvest):
        asyncio.run(M.ArcgisDistressLayers().fetch())


def test_http_error_on_one_layer_hard_fails(monkeypatch):
    async def get(url, **kw):
        if "lincolncountync" in url:
            return _resp(503)
        return _resp(200, {"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    with pytest.raises(PartialHarvest):
        asyncio.run(M.ArcgisDistressLayers().fetch())


def test_row_without_address_or_parcel_is_dropped():
    lay = M.LAYERS[0]
    assert M._to_listing({"owner1_last_name": "SMITH"}, lay) is None


def test_buncombe_row_maps_to_a_usable_lead():
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_unpaid_bills")
    li = M._to_listing({
        "bill": "0003018081-2025-2025-0000-00", "pin": "9686-54-0826-00000",
        "owner1_last_name": "ROBINSON", "owner1_first_name": "LORA",
        "address_line1": "28 DODE WHITAKER RD", "city": "ASHEVILLE",
        "postal_code": "28804", "total_value": 374100.0, "real_value": 374100.0,
    }, lay)
    assert li.owner_name == "ROBINSON, LORA"
    assert li.parcel_id == "9686-54-0826-00000"
    assert li.street_address == "28 DODE WHITAKER RD"
    assert li.tax_value == 374100.0
    assert li.county == "Buncombe" and li.state == "NC"
    assert li.foreclosure_process == "tax"


def test_buncombe_filter_excludes_personal_property():
    """7,900 unpaid bills, but 6,873 are vehicle tax. Only real property is a
    lead; without this filter the board gains 6,873 non-properties."""
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_unpaid_bills")
    assert "real_value>0" in lay.where


def test_lincoln_filter_excludes_closed_violations():
    """3,465 violations back to 1999; 66 are open. A closed violation is not a
    distress signal."""
    lay = next(x for x in M.LAYERS if x.slug == "lincoln_code_violations")
    assert "STATUS='Open'" in lay.where


def test_every_layer_slug_is_unique():
    slugs = [x.slug for x in M.LAYERS]
    assert len(slugs) == len(set(slugs))
