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


# ---------------------------------------------------------------------------
# Batch 2: tax-sale + county-owned surplus.
# ---------------------------------------------------------------------------

def test_county_surplus_is_tagged_so_it_cannot_reach_an_outreach_list():
    """The owner on these rows is the county itself. Buying at a surplus sale
    and cold-calling an owner in default are different workflows; if surplus
    leaks into a mail merge we are writing to the county tax office."""
    surplus = [x for x in M.LAYERS if x.slug.endswith("_county_owned")]
    assert surplus, "no surplus layers declared"
    for lay in surplus:
        assert lay.process == "county_surplus", lay.slug


def test_no_surplus_layer_is_typed_as_a_foreclosure_or_tax_lien():
    """Typing county inventory as TAX_LIEN would make it score as distress."""
    from foreclosure_scraper.models import ListingType
    for lay in M.LAYERS:
        if lay.process == "county_surplus":
            assert lay.listing_type not in (
                ListingType.TAX_LIEN, ListingType.TAX_SALE,
                ListingType.FORECLOSURE_SALE), lay.slug


def test_split_situs_columns_are_composed_into_an_address():
    """Buncombe's surplus layer has no single address column; without this all
    98 rows land with street_address=None and cannot be driven to."""
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_county_owned")
    assert lay.situs_parts, "buncombe surplus declares no situs_parts"
    li = M._to_listing({"pin": "9699215869", "owner": "COUNTY OF BUNCOMBE",
                        "HouseNumber": "550", "streetname": "OLD US 70",
                        "StreetType": "HWY"}, lay)
    assert li.street_address == "550 OLD US 70 HWY"


def test_spartanburg_maps_only_self_describing_columns():
    """The CAMA join renamed every column to a positional alias. Those shift if
    the county rebuilds the join, so only the Tax_Sale_* columns may drive the
    mapping — a wrong owner is worse than no owner."""
    lay = next(x for x in M.LAYERS if x.slug == "spartanburg_city_tax_sale")
    for role in (lay.parcel, lay.owner_last, lay.situs):
        assert role.startswith("Tax_Sale_"), f"{role} is a positional alias"


def test_spartanburg_row_maps():
    lay = next(x for x in M.LAYERS if x.slug == "spartanburg_city_tax_sale")
    li = M._to_listing({"Tax_Sale_1": "7-17-10-041.00", "Tax_Sale_2": "RT & C LLC",
                        "Tax_Sale_4": "2117 OAKHURST CIR",
                        "L20CAMA_18": "LOT 8 BLK A OAKHURST DEV CO"}, lay)
    assert li.parcel_id == "7-17-10-041.00"
    assert li.owner_name == "RT & C LLC"
    assert li.street_address == "2117 OAKHURST CIR"
    assert li.county == "Spartanburg" and li.state == "SC"


def test_every_layer_declares_a_way_to_locate_the_property():
    """A layer with neither a parcel column nor any address column produces
    rows that are dropped on the floor — declare it and you get silence."""
    for lay in M.LAYERS:
        assert lay.parcel or lay.situs or lay.situs_parts, lay.slug


def test_no_layer_carries_an_owner_or_complainant_phone():
    """Buncombe's HMGP layer has a Phone column and Lincoln's has PHONE/EMAIL.
    Contact data belongs to the skip-trace path under its own DNC rules, not to
    a source reader that has no consent context."""
    banned = {"phone", "phone_number", "email", "homeowner_phone_number",
              "pocphone", "pocemail"}
    for lay in M.LAYERS:
        leak = {f for f in lay.fields if f.lower() in banned}
        assert not leak, f"{lay.slug} requests {leak}"


def test_storm_damage_counties_are_actually_covered():
    """Transylvania and Burke read ZERO on storm damage not because they were
    undamaged but because only Buncombe's roll was wired."""
    storm = {x.county for x in M.LAYERS if x.process == "storm_damage"}
    assert {"Burke", "Transylvania", "Buncombe"} <= storm, storm


def test_every_layer_has_a_distinct_process_tag():
    """process drives how a lead may be used. A buyout applicant, a county
    surplus parcel and a delinquent owner are three different workflows."""
    for lay in M.LAYERS:
        assert lay.process, f"{lay.slug} has no process tag"
