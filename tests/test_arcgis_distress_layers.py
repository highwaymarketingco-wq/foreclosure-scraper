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
from foreclosure_scraper import layer_guard
from foreclosure_scraper.layer_guard import PartialHarvest

# ROOT CAUSE (2026-10-03, confirmed with pytest's faulthandler_timeout and a
# real stack-trace dump -- see project_test_arcgis_hang_fix for the session
# that found this): this file was measured to take ~192s standalone, which
# reads exactly like an indefinite hang if you check on it with a short
# timeout -- the process sits at ~0% CPU inside asyncio's `selectors.select`,
# indistinguishable at a glance from blocked I/O.
#
# ArcgisDistressLayers.fetch() builds its LayerHarvest with attempts=3 and
# never exposes retry_delay_s (default 2.0s, real `asyncio.sleep`, never
# mocked) to the caller. Three of the tests below deliberately make every
# layer (or several) fail to exercise the hard-fail contract, and each
# failing layer pays two REAL sleeps (2s then 4s) before it is recorded dead
# -- 25 layers failing at once (test_arcgis_200_with_an_error_body_is_a_failure)
# alone accounts for ~150s of real wall time that has nothing to do with what
# the test is actually asserting. tests/test_layer_guard.py already treats
# this as a known seam and passes retry_delay_s=0 to every LayerHarvest it
# constructs directly -- this file has no such injection point because the
# guard is built *inside* fetch(), so the same discipline has to be applied
# by neutralizing the sleep itself.
#
# This autouse fixture is the regression guard: it keeps retry COUNT/behavior
# intact (so test_http_error_on_one_layer_hard_fails etc. still exercise real
# retry attempts) while removing the real wall-clock cost, for every test in
# this module, present and future.
@pytest.fixture(autouse=True)
def _no_real_retry_backoff(monkeypatch):
    async def _instant_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(layer_guard.asyncio, "sleep", _instant_sleep)


# Backstop for the backstop: if a future change reintroduces a real sleep on
# this path (or any other blocking call), fail loudly in seconds instead of
# silently costing minutes. Every test below runs in well under 1s once the
# fixture above is in place.
pytestmark = pytest.mark.timeout(15)


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
    # services6.arcgis.com carries the county-scale layers (Buncombe et al) --
    # those stay hard-fail. lincolncountync (single-city, TLS-chain issue) was
    # moved to the tolerate-list 2026-09-15; see
    # test_tolerated_single_host_layer_does_not_sink_the_batch below.
    async def get(url, **kw):
        if "services6.arcgis.com" in url:
            return _resp(503)
        return _resp(200, {"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    with pytest.raises(PartialHarvest):
        asyncio.run(M.ArcgisDistressLayers().fetch())


def test_tolerated_single_host_layer_does_not_sink_the_batch(monkeypatch):
    """lincolncountync.gov has an incomplete TLS chain (found 2026-09-15) and
    was discarding all 18 layers' rows every run because the guard hard-
    failed the whole batch on this one flaky single-host layer. It's now in
    the harvester's tolerate-list, same treatment as the three county-owned
    layers -- a failure here must not raise PartialHarvest."""
    async def get(url, **kw):
        if "lincolncountync" in url:
            raise ConnectionError("certificate verify failed")
        return _resp(200, {"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    # Should not raise — the flaky layer is tolerated, the rest still land.
    asyncio.run(M.ArcgisDistressLayers().fetch())


def test_row_without_address_or_parcel_is_dropped():
    lay = M.LAYERS[0]
    assert M._to_listing({"owner1_last_name": "SMITH"}, lay) is None


def test_buncombe_row_maps_to_a_usable_lead():
    """Live-verified shape (2026-09-29): address_line1/city/state/postal_code is the
    TAXPAYER'S MAILING address, e.g. owner ROBINSON LORA's bill is mailed to "28 Dode
    Whitaker Rd, Fairview NC" while her actual parcel sits at "42 Dode Whitaker Rd" per
    house_num/street_name/street_type -- same street, different house, a real
    absentee-adjacent case, not a typo. street_address must come from the situs
    columns, not address_line1 (that bug is what DENY_SOURCES / board_selfcheck.py
    document as the buncombe_unpaid_bills vs multi_year_delinquent_tax fusion gap)."""
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_unpaid_bills")
    li = M._to_listing({
        "bill": "0003018081-2025-2025-0000-00", "pin": "9686-54-0826-00000",
        "owner1_last_name": "ROBINSON", "owner1_first_name": "LORA",
        "house_num": "42", "street_direction": None, "street_name": "DODE WHITAKER RD",
        "street_type": None,
        "address_line1": "28 DODE WHITAKER RD", "city": "FAIRVIEW", "state": "NC",
        "postal_code": "28730", "total_value": 374100.0, "real_value": 374100.0,
    }, lay)
    assert li.owner_name == "ROBINSON, LORA"
    assert li.parcel_id == "9686-54-0826-00000"
    assert li.street_address == "42 DODE WHITAKER RD"
    assert li.tax_value == 374100.0
    assert li.county == "Buncombe" and li.state == "NC"
    assert li.foreclosure_process == "tax"
    # city/zip_code are left unset -- this layer has no genuine situs city/zip column,
    # only the mailing one, and asserting the mailing city as the property's own would
    # be wrong for an absentee/out-of-state owner (see the out-of-state test below).
    assert li.city is None and li.zip_code is None


def test_buncombe_mailing_address_is_kept_separate_not_asserted_as_situs():
    """The mailing block still reaches the board (useful absentee/out-of-state signal)
    but under raw['owner_mailing'], never as street_address/city/zip_code. Live-verified
    2026-09-29: owner RADIFY ASHEVILLE LLC's bill mails to North Bend, WA while the
    parcel is 155 Tunnel Rd, Asheville NC -- an out-of-state absentee LLC landlord."""
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_unpaid_bills")
    li = M._to_listing({
        "pin": "0000000000000", "owner1_last_name": "RADIFY ASHEVILLE LLC",
        "house_num": "155", "street_name": "TUNNEL RD",
        "address_line1": "249 MAIN AVE S STE 107 PMB 362", "city": "NORTH BEND",
        "state": "WA", "postal_code": "98045", "real_value": 200000.0,
    }, lay)
    assert li.street_address == "155 TUNNEL RD"
    om = li.raw["owner_mailing"]
    assert om["situs"] == "155 TUNNEL RD"
    assert om["mailing"] == "249 MAIN AVE S STE 107 PMB 362 NORTH BEND WA 98045"
    assert om["mail_state"] == "WA"
    assert om["out_of_state"] is True
    assert om["absentee"] is True
    # Tagged like multi_year_delinquent_tax.py tags this same Buncombe table, so
    # repair_parcel_from_address.py's PARCEL_MAILING_SOURCES recognizes the block.
    assert om["source"] == "county_tax_roll"


def test_buncombe_house_number_sentinel_is_dropped_not_joined_in():
    """NC layers write '0' or '99999' in the house-number slot to mean 'no address
    assigned' -- a real sentinel, not a real number (same convention as
    web_artifact._PLACEHOLDER_HOUSE_NUM_RE / enrichment_parcel_from_geo.
    _NC_NO_NUMBER_SENTINELS). Live-verified 2026-09-29 (owner GENEVA SUMNER, house_num
    '0', street NEW COVENANT DR). Joining it in verbatim would produce '0 NEW COVENANT
    DR', a different (fake) address from the '0'-less situs multi_year_delinquent_tax
    emits for the same parcel, defeating the whole point of the fix."""
    lay = next(x for x in M.LAYERS if x.slug == "buncombe_unpaid_bills")
    li = M._to_listing({
        "pin": "1111111111111", "owner1_last_name": "SUMNER",
        "house_num": "0", "street_name": "NEW COVENANT DR",
        "address_line1": "7776 SUTTER RD", "city": "GREENSBORO", "state": "NC",
        "postal_code": "27455", "real_value": 50000.0,
    }, lay)
    assert li.street_address == "NEW COVENANT DR"


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


# --- 2026-10-07 extraction audit. Values below are made up. ---

def _layer(slug):
    return next(lay for lay in M.LAYERS if lay.slug == slug)


def test_greenville_requests_sale_deed_value_and_building_columns():
    f = set(_layer("greenville_unpaid_tax_parcels").fields)
    for col in ("SLPRICE", "DEEDDATE", "CUBOOK", "CUPAGE", "FAIRMKTVAL", "LANDVAL",
                "BLDGVAL", "SQFEET", "BEDROOMS", "BATHRMS", "POWNNM", "GIS_ACRES"):
        assert col in f, col


def test_greenville_new_columns_land_in_the_raw_block():
    li = M._to_listing({"PIN": "0000000000002", "OWNAM1": "SAMPLE OWNER", "STRNUM": "5",
                        "LOCATE": "TEST", "STRTYP": "RD", "TAXMKTVAL": 1000, "TOTTAX": 10.0,
                        "SLPRICE": 90000, "DEEDDATE": 1577836800000, "CUBOOK": "1234",
                        "CUPAGE": 56, "FAIRMKTVAL": 120000, "SQFEET": 1400, "BEDROOMS": 3,
                        "POWNNM": "EXAMPLE PAT", "GIS_ACRES": 0.3},
                       _layer("greenville_unpaid_tax_parcels"))
    b = li.raw["arcgis_distress"]
    assert b["SLPRICE"] == 90000 and b["CUBOOK"] == "1234" and b["CUPAGE"] == 56
    assert b["FAIRMKTVAL"] == 120000 and b["SQFEET"] == 1400 and b["BEDROOMS"] == 3
    assert b["POWNNM"] == "EXAMPLE PAT" and b["GIS_ACRES"] == 0.3


def test_new_hanover_uses_its_own_coordinates_and_keeps_the_permit_description():
    lay = _layer("new_hanover_demolition_permits")
    li = M._to_listing({"PERMIT_NUMBER": "P-1", "WORK_CLASS": "Demolition",
                        "PERMIT_STATUS": "Issued", "NUMBER": "1", "STREET": "TEST",
                        "TYPE": "ST", "PID": "R00000-000-000-000", "DESCRIPTION": "Demo house",
                        "ISSUE_DATE": 1704067200000, "Lat": 34.2, "Lon": -77.9}, lay)
    assert (li.latitude, li.longitude) == (34.2, -77.9)
    assert li.raw["arcgis_distress"]["DESCRIPTION"] == "Demo house"
    assert li.raw["arcgis_distress"]["ISSUE_DATE"] == 1704067200000


def test_zero_or_missing_own_coordinates_are_not_used():
    lay = _layer("new_hanover_demolition_permits")
    base = {"NUMBER": "1", "STREET": "TEST", "TYPE": "ST", "PID": "R00000-000-000-001"}
    assert M._to_listing({**base, "Lat": 0, "Lon": 0}, lay).latitude is None
    assert M._to_listing(base, lay).latitude is None


def test_an_ssn_like_column_never_reaches_the_raw_block():
    li = M._to_listing({"PIN": "0000000000003", "OWNAM1": "SAMPLE", "STRNUM": "1",
                        "LOCATE": "TEST", "TCSSN1": "000-00-0000"},
                       _layer("greenville_unpaid_tax_parcels"))
    assert "TCSSN1" not in li.raw["arcgis_distress"]
