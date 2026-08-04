"""NC OneMap + Buncombe owner-index backends for the name -> parcel resolver.

Every fixture in tests/fixtures/ was saved from a live, free, public, no-auth
response on 2026-08-03 (see the module docstring in
enrichment_resolve_name_to_property for the endpoints).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from foreclosure_scraper.enrichment_resolve_name_to_property import (
    BUNCOMBE_OWNER_FIELDS,
    BUNCOMBE_OWNER_LOOKUP_URL,
    BUNCOMBE_PARCEL_OWNERS_URL,
    NC_ONEMAP_FIELDS,
    NC_ONEMAP_URL,
    _county_upper,
    _endpoint_plan,
    _owner_segments,
    _query_buncombe_owner_index,
    _strict_matches,
    _valid_situs,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.name_normalize import primary_party

FIXTURES = Path(__file__).parent / "fixtures"


def _fx(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _lead(**kw: Any) -> Listing:
    base = dict(
        source="ecourts", listing_type=ListingType.FORECLOSURE_SALE,
        source_url="https://example.invalid/case/1",
        state="NC", county="Buncombe", owner_name="David T Manly",
    )
    base.update(kw)
    return Listing(**base)


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttp:
    """Routes by URL to a saved fixture and records every request it served."""

    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None,
                  timeout: float | None = None) -> _Resp:
        self.calls.append((url, dict(params or {})))
        return _Resp(self.routes.get(url, {"features": []}))


# ---------------------------------------------------------------------------
# GOTCHA 1: county casing
# ---------------------------------------------------------------------------

def test_county_literal_is_not_title_cased_so_mcdowell_survives():
    """REGRESSION: _county_clean applies .title(), which maps 'McDowell' ->
    'Mcdowell'. NC OneMap stores 'McDowell', so a Title-Cased literal matches 0
    of its 33,449 rows — the exact reason a prior pass concluded the county was
    absent from the service."""
    assert _county_upper(_lead(county="McDowell")) == "MCDOWELL"
    assert _county_upper(_lead(county="McDowell County, NC")) == "MCDOWELL"
    assert _county_upper(_lead(county="New Hanover")) == "NEW HANOVER"
    assert "Mcdowell" not in _nc_onemap_where(_lead(county="McDowell"))


def _nc_onemap_where(li: Listing) -> str:
    plan = _endpoint_plan(li)
    onemap = [c for c in plan if c["base"] == NC_ONEMAP_URL]
    assert onemap, "NC OneMap must be in the plan for every NC county"
    return onemap[0]["where_prefix"]


def test_nc_onemap_compares_county_case_insensitively():
    assert _nc_onemap_where(_lead(county="McDowell")) == "UPPER(cntyname) = 'MCDOWELL'"
    assert _nc_onemap_where(_lead(county="Buncombe")) == "UPPER(cntyname) = 'BUNCOMBE'"


# ---------------------------------------------------------------------------
# GOTCHA 2: the county predicate is mandatory, and outFields are enumerated
# ---------------------------------------------------------------------------

def test_every_nc_onemap_cfg_carries_a_county_predicate():
    """Without it an owner LIKE runs against 5.9M statewide rows and can hand the
    strict matcher a same-named stranger 300 miles away."""
    for county in ("Buncombe", "Dare", "McDowell", "Cleveland", "Yancey"):
        for cfg in _endpoint_plan(_lead(county=county)):
            if cfg["base"] == NC_ONEMAP_URL:
                assert cfg["where_prefix"].startswith("UPPER(cntyname) = '")


def test_out_fields_are_enumerated_and_carry_no_owner_mailing_column():
    for spec in (NC_ONEMAP_FIELDS, BUNCOMBE_OWNER_FIELDS):
        assert "*" not in spec
    banned = ("mailadd", "mcity", "mstate", "mzip", "munit", "maddr",
              "Address1", "Address2", "Zip1", "Zip2")
    for bad in banned:
        assert bad not in NC_ONEMAP_FIELDS
        assert bad not in BUNCOMBE_OWNER_FIELDS


# ---------------------------------------------------------------------------
# GOTCHA 3: ';' joins co-owners
# ---------------------------------------------------------------------------

def test_semicolon_is_a_joint_owner_separator():
    assert primary_party("MANLY DAVID T;DILLON MARGARET") == "MANLY DAVID T"
    # Unchanged for every layer that has no ';'.
    assert primary_party("SMITH JOHN C & MELINDA P") == "SMITH JOHN C"


def test_owner_segments_splits_only_on_semicolons():
    assert _owner_segments("MANLY DAVID T;DILLON MARGARET") == [
        "MANLY DAVID T", "DILLON MARGARET"]
    assert _owner_segments("SMITH JOHN C & MELINDA P") == ["SMITH JOHN C & MELINDA P"]
    assert _owner_segments("") == []


def test_a_second_listed_co_owner_can_match_her_own_parcel():
    """The person a divorce/probate lead names is routinely the SECOND owner on
    the deed. primary_party reads only the first, so without segment matching she
    is invisible on her own property."""
    row = {"ownname": "MANLY DAVID T;DILLON MARGARET", "parno": "060502683700000"}
    assert _strict_matches([row], "ownname", "Margaret Dillon")
    assert _strict_matches([row], "ownname", "David T Manly")
    # Strictness is NOT relaxed by widening which strings get compared.
    assert not _strict_matches([row], "ownname", "Margaret Manly")
    assert not _strict_matches([row], "ownname", "Kevin Dillon")


# ---------------------------------------------------------------------------
# Buncombe's 99999 no-address sentinel
# ---------------------------------------------------------------------------

def test_buncombe_no_address_sentinel_is_never_written_as_a_street():
    """13% of Buncombe's OneMap rows (17,788 of 134,741) carry '99999 <street>'
    to mean 'this parcel has no address'."""
    assert _valid_situs("99999 PEARSON  LN") is False
    assert _valid_situs("0 NOWHERE RD") is False
    assert _valid_situs("70 BUTTERROW COVE  RD") is True
    assert _valid_situs("16 SHANNON  DR") is True


# ---------------------------------------------------------------------------
# Plan shape
# ---------------------------------------------------------------------------

def test_buncombe_tries_the_structured_index_first_then_falls_back():
    labels = [c["label"] for c in _endpoint_plan(_lead(county="Buncombe"))]
    assert labels[0] == "buncombe_owner_index"
    assert "nc_onemap" in labels
    assert labels.index("nc_onemap") == len(labels) - 1  # statewide scan paid last


def test_unwired_nc_counties_stop_being_no_endpoint():
    """NC_GIS wires 18 of 100 NC counties. OneMap covers all of them, so a lead in
    Dare/Yancey/Watauga now has a backend instead of falling out unattempted."""
    for county in ("Dare", "Yancey", "Watauga", "Ashe"):
        labels = [c["label"] for c in _endpoint_plan(_lead(county=county))]
        assert labels, county
        assert "nc_onemap" in labels, county


def test_sc_plans_are_untouched_by_the_nc_work():
    for county in ("Spartanburg", "Pickens", "Laurens", "Oconee", "Union"):
        plan = _endpoint_plan(_lead(state="SC", county=county))
        assert plan and all(c["base"] != NC_ONEMAP_URL for c in plan), county
    # The two SC walls stay walls.
    for county in ("Anderson", "Cherokee"):
        assert _endpoint_plan(_lead(state="SC", county=county)) == []


# ---------------------------------------------------------------------------
# Buncombe owner index, end to end against saved live fixtures
# ---------------------------------------------------------------------------

def _buncombe_http() -> _FakeHttp:
    return _FakeHttp({
        BUNCOMBE_OWNER_LOOKUP_URL: _fx("buncombe_owner_lookup_manly"),
        BUNCOMBE_PARCEL_OWNERS_URL: _fx("buncombe_parcel_owners_manly"),
        NC_ONEMAP_URL: _fx("nc_onemap_buncombe_parcels"),
    })


def test_owner_index_walks_name_to_id_to_pin_to_parcel_row():
    http = _buncombe_http()
    cfg = _endpoint_plan(_lead())[0]
    rows = asyncio.run(_query_buncombe_owner_index(http, cfg, "David T Manly"))

    urls = [u for u, _ in http.calls]
    assert urls[0] == BUNCOMBE_OWNER_LOOKUP_URL
    assert BUNCOMBE_PARCEL_OWNERS_URL in urls
    assert urls[-1] == NC_ONEMAP_URL

    # The parcel step is county-scoped so a Pin colliding with another county's
    # parno cannot resolve to the wrong property.
    onemap_where = [p["where"] for u, p in http.calls if u == NC_ONEMAP_URL][0]
    assert onemap_where.startswith("UPPER(cntyname) = 'BUNCOMBE' AND parno IN (")
    assert "'060502683700000'" in onemap_where

    # And the rows it returns are ordinary parcel rows the existing strict
    # matcher adjudicates — the index decides nothing on its own.
    hits = _strict_matches(rows, "ownname", "David T Manly")
    assert len(hits) == 1
    assert hits[0][1]["parno"] == "060502683700000"
    assert hits[0][1]["siteadd"] == "70 BUTTERROW COVE  RD"


def test_owner_index_pages_with_offset_and_a_stable_order():
    http = _buncombe_http()
    asyncio.run(_query_buncombe_owner_index(http, _endpoint_plan(_lead())[0], "David T Manly"))
    for _url, params in http.calls:
        assert "resultOffset" in params
        assert "resultRecordCount" in params
        assert params["orderByFields"]
        assert params["outFields"] != "*"


def test_owner_index_never_requests_the_owner_mailing_address():
    """The lookup table also carries Address1/Address2/City/State/Zip. The
    resolver's job is name -> parcel; not asking is stronger than stripping."""
    http = _buncombe_http()
    asyncio.run(_query_buncombe_owner_index(http, _endpoint_plan(_lead())[0], "David T Manly"))
    lookup = [p for u, p in http.calls if u == BUNCOMBE_OWNER_LOOKUP_URL][0]
    assert lookup["outFields"] == BUNCOMBE_OWNER_FIELDS
    for bad in ("Address1", "Address2", "City", "State", "Zip1", "Zip2"):
        assert bad not in lookup["outFields"]


def test_owner_index_searches_structured_surname_and_given_columns():
    http = _buncombe_http()
    asyncio.run(_query_buncombe_owner_index(http, _endpoint_plan(_lead())[0], "David T Manly"))
    where = [p["where"] for u, p in http.calls if u == BUNCOMBE_OWNER_LOOKUP_URL][0]
    assert "UPPER(LastName) = 'MANLY'" in where
    assert "UPPER(FirstName) LIKE 'DAVID%'" in where
    # A '%MANLY%DAVID%' LIKE against one concatenated string would also return
    # 'MANLYWOOD DAVIDSON'; separate columns cannot collide that way.
    assert "LIKE '%MANLY%" not in where


def test_owner_index_skips_companies():
    """The lookup is a person table. An entity name has no surname/given split,
    so probing it would only burn requests."""
    http = _buncombe_http()
    rows = asyncio.run(_query_buncombe_owner_index(
        http, _endpoint_plan(_lead())[0], "Blue Ridge Holdings LLC"))
    assert rows == []
    assert http.calls == []


def test_owner_with_no_parcels_returns_nothing_rather_than_guessing():
    """544,665 owner rows vs 196,836 parcel links: most owners in the lookup are
    historical and hold nothing today. That is a real answer, not a failure."""
    http = _FakeHttp({
        BUNCOMBE_OWNER_LOOKUP_URL: _fx("buncombe_owner_lookup_manly"),
        BUNCOMBE_PARCEL_OWNERS_URL: {"features": []},
        NC_ONEMAP_URL: _fx("nc_onemap_buncombe_parcels"),
    })
    rows = asyncio.run(_query_buncombe_owner_index(
        http, _endpoint_plan(_lead())[0], "David T Manly"))
    assert rows == []
    assert NC_ONEMAP_URL not in [u for u, _ in http.calls]


# ---------------------------------------------------------------------------
# The rule that matters most: never guess between several parcels
# ---------------------------------------------------------------------------

def test_two_parcels_for_one_name_stay_ambiguous_on_the_new_backends():
    rows = [
        {"ownname": "MANLY DAVID T;DILLON MARGARET", "parno": "060502683700000"},
        {"ownname": "MANLY DAVID T", "parno": "968545857200000"},
    ]
    hits = _strict_matches(rows, "ownname", "David T Manly")
    parcels = {r["parno"] for _k, r in hits}
    assert len(hits) == 2 and len(parcels) == 2, (
        "two distinct parcels must reach the ambiguity branch, which flags "
        "candidates and commits nothing"
    )


@pytest.mark.parametrize("lead,owner", [
    ("Michael Duane Crowe", "CROWE KEVIN MICHAEL"),
    ("Casey William Gillespie", "CASEY WILLIAM MICHAEL"),
    ("Margaret Dillon", "DILLON MARGARETTE ANN;MANLY DAVID T"),
])
def test_known_wrong_person_shapes_still_do_not_match(lead, owner):
    assert not _strict_matches([{"ownname": owner}], "ownname", lead)


# ---------------------------------------------------------------------------
# ThirdName filter: the wrong-person shape this backend uniquely creates
# ---------------------------------------------------------------------------

def _person(name: str):
    from foreclosure_scraper.name_normalize import person_orderings
    return person_orderings(name)[0]


def test_a_contradicting_spelled_out_middle_name_is_dropped_before_it_can_win():
    """MEASURED: the structured probe asks for every 'MCCURRY, JAMES%' on
    purpose. If only the wrong one owns a parcel, the chain yields exactly one
    candidate and it commits as a unique 'strong' hit — uniqueness bought by
    property ownership, not by the name being distinctive."""
    from foreclosure_scraper.enrichment_resolve_name_to_property import (
        _drop_middle_name_conflicts)
    rows = [
        {"ID": 1, "LastName": "MCCURRY", "FirstName": "JAMES", "ThirdName": "BRUCE"},
        {"ID": 2, "LastName": "MCCURRY", "FirstName": "JAMES", "ThirdName": "RODNEY"},
    ]
    kept = _drop_middle_name_conflicts(rows, _person("James Rodney Mccurry"))
    assert [r["ID"] for r in kept] == [2]


def test_an_initial_or_a_blank_middle_can_never_contradict():
    """Same evidentiary bar as name_normalize.middle_conflict: 'MCCURRY JAMES R'
    does not disagree with 'James Rodney Mccurry', it just says less."""
    from foreclosure_scraper.enrichment_resolve_name_to_property import (
        _drop_middle_name_conflicts)
    rows = [
        {"ID": 1, "ThirdName": "R"},
        {"ID": 2, "ThirdName": None},
        {"ID": 3, "ThirdName": ""},
        {"ID": 4, "ThirdName": "RODNEY"},
    ]
    kept = _drop_middle_name_conflicts(rows, _person("James Rodney Mccurry"))
    assert [r["ID"] for r in kept] == [1, 2, 3, 4]


def test_a_lead_with_no_middle_name_filters_nothing():
    from foreclosure_scraper.enrichment_resolve_name_to_property import (
        _drop_middle_name_conflicts)
    rows = [{"ID": 1, "ThirdName": "BRUCE"}, {"ID": 2, "ThirdName": "RODNEY"}]
    kept = _drop_middle_name_conflicts(rows, _person("James Mccurry"))
    assert len(kept) == 2
