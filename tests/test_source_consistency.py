"""Tests for the offline source-consistency verifier.

EVERY CHECK IS PINNED TWICE: once against a case that must trip it, and once
against a LEGITIMATE near-miss that must not. False positives are the failure
mode for this pass — it labels data untrustworthy — so the near-miss tests are
the load-bearing half. Each of them is a real shape measured on the live board,
named in the test, not an invented one.
"""
from __future__ import annotations

import re
from datetime import datetime

from foreclosure_scraper.enrichment_source_consistency import (
    ADDR_CITY_CONFLICT,
    ALL_FLAGS,
    LAND_USE_KIND_CONFLICT,
    URL_CITY_CONFLICT,
    ZIP_STATE_CONFLICT,
    address_trailing_city,
    city_vocabulary,
    enrich_source_consistency,
    land_use_kind_conflict,
    same_place,
    url_city_conflict,
    url_slug_geo,
    zip_state_conflict,
    zip_state_consensus,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw):
    base = dict(
        source="national.auction_dot_com", source_url="http://x",
        listing_type=ListingType.AUCTION, property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={},
    )
    base.update(kw)
    return Listing(**base)


def _flags(li):
    return list((li.raw or {}).get("qa_flags") or [])


# ===========================================================================
# CHECK 1 — source_url_city_conflict
# ===========================================================================

def test_url_city_conflict_trips_on_board_index_zero():
    """The motivating defect: the URL says Shelby, the city field says the COUNTY."""
    assert url_city_conflict(
        "https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
        "CLEVELAND", "Cleveland") == "510-kings-rd-shelby"


def test_url_city_conflict_silent_when_city_is_in_the_slug_tail():
    """The near-miss that produced the bogus ~93% rate.

    A crude regex captured street AND city together, so '423 Camden Lee Court /
    Inman' read as a disagreement. The city is right there in the tail; this
    must say nothing.
    """
    assert url_city_conflict(
        "https://www.homesteps.com/listingdetails/423-camden-lee-court-inman-sc-29349",
        "Inman", "Spartanburg") is None


def test_url_city_conflict_silent_on_marketing_headline_hosts():
    """landandfarm slugs are prose, not addresses.

    'custom-built-home-near-boiling-springs-nc' on a Shelby property is a true
    sentence about a property near Boiling Springs, not a city claim. 23 of
    these tripped an unrestricted parse and all 23 were false positives, so the
    host is not on the address-slug list at all.
    """
    assert url_slug_geo(
        "https://www.landandfarm.com/property/custom-built-home-near-boiling-springs-nc-41624978/") is None
    assert url_city_conflict(
        "https://www.landandfarm.com/property/custom-built-home-near-boiling-springs-nc-41624978/",
        "Shelby", "Cleveland") is None


def test_url_city_conflict_silent_when_slug_names_the_county():
    """'...-in-buncombe-county-nc-...' makes no claim about the city."""
    assert url_city_conflict(
        "https://www.auction.com/details/5-acres-in-buncombe-county-nc-41240293",
        "Asheville", "Buncombe") is None


def test_url_city_conflict_silent_on_an_abbreviated_spelling():
    assert url_city_conflict(
        "https://www.zillow.com/homedetails/12-Main-St-Boiling-Springs-SC-29316/1_zpid/",
        "Boiling Spgs", "Spartanburg") is None


def test_url_city_conflict_silent_with_no_city_field():
    """Nothing to contradict is not a contradiction."""
    assert url_city_conflict(
        "https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
        None, "Cleveland") is None


def test_url_slug_geo_strips_a_trailing_zip():
    assert url_slug_geo(
        "https://www.zillow.com/homedetails/67-Earwood-Ridge-Rd-Fairview-NC-28730/5630058_zpid/"
    ) == ("NC", "67-earwood-ridge-rd-fairview")


def test_url_slug_geo_ignores_county_portal_urls():
    """Only hosts whose detail URL is built FROM the address are parsed."""
    assert url_slug_geo("https://www.rutherfordcountync.gov/TR-452%20Report.xlsx") is None
    assert url_slug_geo("https://bcpwa.ncptscloud.com/") is None


# ===========================================================================
# CHECK 2 — address_city_conflict
# ===========================================================================

_VOCAB = {"SC": {"roebuck", "moore", "inman", "duncan", "woodruff", "greer",
                 "spartanburg", "campobello", "boiling springs", "cross anchor"},
          "NC": {"shelby", "asheville", "henrietta", "mooresboro"}}


def test_address_trailing_city_trips_on_appended_town():
    """'111 FORTUNE DR ROEBUCK' — the town is appended after the street type."""
    assert address_trailing_city("111 FORTUNE DR ROEBUCK", "SC", _VOCAB) == "roebuck"


def test_address_trailing_city_prefers_the_longest_name():
    assert address_trailing_city("11900 HIGHWAY 56 CROSS ANCHOR", "SC", _VOCAB) == "cross anchor"


def test_address_trailing_city_silent_when_the_town_name_IS_the_street():
    """'100 GREER ST' is a street called Greer, not a property in Greer.

    The street-type token must come BEFORE the candidate. Here it comes after,
    so the street name has not ended and nothing is claimed.
    """
    assert address_trailing_city("100 GREER ST", "SC", _VOCAB) is None


def test_address_trailing_city_silent_on_a_town_name_mid_street_name():
    """'2226 HARRIS HENRIETTA RD' contains the town Henrietta inside the street name."""
    assert address_trailing_city("2226 HARRIS HENRIETTA RD", "NC", _VOCAB) is None


def test_address_trailing_city_honours_a_street_type_abbreviation_before_it():
    assert address_trailing_city("325 CAROLINA DR EXT ROEBUCK", "SC", _VOCAB) == "roebuck"


def test_address_trailing_city_refuses_a_placeholder_that_contains_a_town():
    """A court-index blob is not an address, even when a real one is buried in it.

    Verbatim from the board. Same discipline as refusing to read a city out of a
    landandfarm marketing headline: only parse geography out of a string that is
    structurally an address, which here means it starts with a house number.
    """
    assert address_trailing_city(
        "Vacant parcel — D Dist Recorded 2026 06 03 Babcock Michael Lance "
        "Estate 103 Barkley St Easley", "SC", {"SC": {"easley"}}) is None
    assert address_trailing_city("103 Barkley St Easley", "SC", {"SC": {"easley"}}) == "easley"


def test_address_city_conflict_flag_trips_on_a_defaulted_county_name():
    """The spartanburg_vacant defect: city defaulted to the county name."""
    li = _li(street_address="111 FORTUNE DR ROEBUCK", city="Spartanburg",
             county="Spartanburg", state="SC", property_kind=PropertyKind.LAND)
    enrich_source_consistency([li] + _support_for_vocab())
    assert ADDR_CITY_CONFLICT in _flags(li)


def test_address_city_conflict_silent_when_the_two_agree():
    li = _li(street_address="532 ALVERSON RD INMAN", city="Inman",
             county="Spartanburg", state="SC")
    enrich_source_consistency([li] + _support_for_vocab())
    assert ADDR_CITY_CONFLICT not in _flags(li)


def test_address_city_conflict_silent_on_an_abbreviation():
    """'Boiling Spgs' and 'Boiling Springs' are one town spelled two ways."""
    li = _li(street_address="1852 OLD FURNACE RD BOILING SPRINGS",
             city="Boiling Spgs", county="Spartanburg", state="SC")
    enrich_source_consistency([li] + _support_for_vocab())
    assert ADDR_CITY_CONFLICT not in _flags(li)


def test_address_city_conflict_silent_when_the_city_field_is_empty():
    """1,472 leads on the live board. Recoverable data, NOT a contradiction."""
    li = _li(street_address="111 FORTUNE DR ROEBUCK", city=None,
             county="Spartanburg", state="SC")
    out = enrich_source_consistency([li] + _support_for_vocab())
    assert ADDR_CITY_CONFLICT not in _flags(li)
    assert out.get("address_city_recoverable", 0) >= 1


def test_city_vocabulary_needs_support_so_one_typo_never_becomes_a_town():
    lis = [_li(city="Roebuck", state="SC") for _ in range(6)]
    lis.append(_li(city="Roebcuk", state="SC"))
    voc = city_vocabulary(lis)
    assert "roebuck" in voc["SC"]
    assert "roebcuk" not in voc["SC"]


def test_city_vocabulary_denies_generic_address_words():
    """'Park' and 'Ridge' are towns AND address furniture; never a trailing city."""
    lis = [_li(city="Park", state="NC") for _ in range(9)]
    assert "park" not in city_vocabulary(lis)["NC"]


def _support_for_vocab():
    """Filler leads that give the board-built city vocabulary its support."""
    out = []
    for city in ("Roebuck", "Inman", "Boiling Springs", "Duncan", "Moore"):
        out += [_li(city=city, state="SC", county="Spartanburg",
                    street_address=f"{i} Nowhere Ln") for i in range(6)]
    return out


# ===========================================================================
# CHECK 3 — zip_state_conflict
# ===========================================================================

def test_zip_state_conflict_trips_on_an_out_of_state_zip():
    """6055 OLD MEADOW CT, county Buncombe NC, zip 23111 = Mechanicsville VIRGINIA."""
    assert zip_state_conflict("23111", "NC", {}) == "zip_range"


def test_zip_state_conflict_silent_on_an_in_state_zip():
    assert zip_state_conflict("28801", "NC", {}) is None
    assert zip_state_conflict("29301", "SC", {}) is None


def test_zip_state_conflict_silent_on_a_placeholder_zip():
    """counties_nc.rutherford_tax writes '00000'. Missing, not wrong."""
    assert zip_state_conflict("00000", "NC", {}) is None
    assert zip_state_conflict("99999", "SC", {}) is None


def test_zip_state_conflict_silent_on_a_border_crossing_zip():
    """The reason consensus is consulted BEFORE the range table.

    A ZIP whose delivery area really does straddle the state line shows both
    states on the board, so it never reaches the 98% bar and the range table —
    which would convict — is never reached.
    """
    lis = ([_li(zip_code="29349", state="SC") for _ in range(24)]
           + [_li(zip_code="29349", state="NC") for _ in range(4)])
    cons = zip_state_consensus(lis)
    assert zip_state_conflict("29349", "NC", cons) is None


def test_zip_state_conflict_uses_consensus_when_the_board_is_unanimous():
    lis = [_li(zip_code="28801", state="NC") for _ in range(40)]
    cons = zip_state_consensus(lis)
    assert zip_state_conflict("28801", "SC", cons) == "board_consensus"


def test_zip_state_conflict_reads_zip_plus_four():
    assert zip_state_conflict("28151-0146", "SC", {}) == "zip_range"


# ===========================================================================
# CHECK 4 — land_use_kind_conflict
# ===========================================================================

def test_land_use_kind_conflict_trips_on_a_dwelling_class_on_a_land_parcel():
    assert land_use_kind_conflict("land", "Residential - Single Family") == "structure_on_land_parcel"


def test_land_use_kind_conflict_trips_on_vacant_dirt_priced_as_a_house():
    """521 Zion Hill Rd: land_use 'Undeveloped Land', kind multi_family, bid $332,000."""
    assert land_use_kind_conflict("multi_family", "Undeveloped Land") == "vacant_lot_priced_as_dwelling"


def test_land_use_kind_conflict_silent_when_the_two_agree():
    assert land_use_kind_conflict("land", "Residential Subdivision Undeveloped Lot") is None
    assert land_use_kind_conflict("single_family", "Residential - Single Family") is None


def test_land_use_kind_conflict_silent_on_mobile_home_classes():
    """'Mobile Home Lot' (578 on the board) does not say whether a home is on it."""
    assert land_use_kind_conflict("land", "Mobile Home Lot") is None
    assert land_use_kind_conflict("single_family", "Mobile Home Combined With Land") is None


def test_land_use_kind_conflict_silent_on_farms():
    """A farm legitimately has both a farmhouse and acres of undeveloped land."""
    assert land_use_kind_conflict("land", "Farms-General") is None
    assert land_use_kind_conflict("single_family", "Farms-Fruits & Vegetables") is None


def test_land_use_kind_conflict_silent_on_coded_and_empty_land_use():
    """Spartanburg publishes codes like '4Oor' / '6Rgr'; they decide nothing."""
    for lu in ("", None, "4Oor", "6Rgr", "A", "CBD Central Business District"):
        assert land_use_kind_conflict("land", lu) is None


def test_land_use_kind_conflict_accepts_the_enum_not_just_the_string():
    assert land_use_kind_conflict(PropertyKind.LAND, "Duplex") == "structure_on_land_parcel"


# ===========================================================================
# same_place — the abbreviation guard shared by checks 1 and 2
# ===========================================================================

def test_same_place_accepts_abbreviations_and_rejects_different_towns():
    assert same_place("Boiling Spgs", "Boiling Springs")
    assert same_place("asheville", "ASHEVILLE")
    assert not same_place("Roebuck", "Spartanburg")
    assert not same_place("Shelby", "Cleveland")
    assert not same_place("Inman", "Campobello")


# ===========================================================================
# THE PASS ITSELF — composition, idempotence, and the money contract
# ===========================================================================

def test_extends_existing_qa_flags_never_replaces_them():
    """enrichment_board_qa ASSIGNS raw['qa_flags']; this pass must only extend.

    Running in the other order silently deletes everything here, which is why
    scripts/recompute_valuation.py calls board_qa first.
    """
    li = _li(source_url="https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
             city="CLEVELAND", county="Cleveland", state="NC",
             raw={"qa_flags": ["no_sqft", "arv_sanity_flag"]})
    enrich_source_consistency([li])
    assert _flags(li)[:2] == ["no_sqft", "arv_sanity_flag"]
    assert URL_CITY_CONFLICT in _flags(li)


def test_is_idempotent_across_republishes():
    li = _li(source_url="https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
             city="CLEVELAND", county="Cleveland", state="NC")
    enrich_source_consistency([li])
    first = _flags(li)
    enrich_source_consistency([li])
    assert _flags(li) == first


def test_publishes_no_flag_on_a_clean_lead():
    li = _li(source_url="https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
             street_address="510 KINGS RD", city="Shelby", county="Cleveland",
             state="NC", zip_code="28150", land_use="Residential - Single Family")
    enrich_source_consistency([li])
    assert not set(_flags(li)) & set(ALL_FLAGS)


def test_gates_no_money():
    """None of these four withholds a dollar. A wrong city is not a wrong ARV.

    The one candidate that could plausibly have earned a retraction is
    land_use_kind_conflict, and 550 of the 648 leads carrying it WITH a max bid
    have no living_sqft — their ARV came from the county's own valuation, which
    already prices whatever is standing on the parcel.
    """
    calc = {"arv_expected": 300000.0, "max_bid_70": 210000.0, "roi_pct": 40.0,
            "deal_status": "GREAT"}
    li = _li(source_url="https://www.auction.com/details/510-kings-rd-shelby-nc-2141050",
             city="CLEVELAND", county="Cleveland", state="NC", zip_code="23111",
             property_kind=PropertyKind.LAND, land_use="Residential - Single Family",
             raw={"calc": dict(calc), "equity": {"value": 90000.0}})
    enrich_source_consistency([li])
    assert set(_flags(li)) >= {URL_CITY_CONFLICT, ZIP_STATE_CONFLICT, LAND_USE_KIND_CONFLICT}
    assert li.raw["calc"] == calc
    assert li.raw["equity"] == {"value": 90000.0}


def test_flag_strings_are_absent_from_the_grading_trust_sets():
    """The money contract, pinned. Adding one of these to a trust set is a
    deliberate act that must break this test first."""
    from foreclosure_scraper.valuation.grading import (
        ARV_FLAGS_CONTRADICTED, ARV_FLAGS_WEAK_EVIDENCE,
    )
    for f in ALL_FLAGS:
        assert f not in ARV_FLAGS_CONTRADICTED
        assert f not in ARV_FLAGS_WEAK_EVIDENCE


def test_flag_names_cannot_be_misread_as_an_arv_verdict_by_the_dashboard():
    """docs/dashboard.js:2174 treats a qa_flags name as an ARV claim only when it
    contains 'arv'; :2060 then paints it RED if it matches _ARV_BAD_WORDS. None
    of these four impugns a valuation, so neither may happen. This is why every
    name says 'conflict' and not 'mismatch'."""
    bad_words = re.compile(
        r"(above|below|exceed|extreme|outlier|suspect|unverif|unreliab|implausib|"
        r"ceiling|inflat|mismatch|withheld|suppress|overrid|contradict)")
    for f in ALL_FLAGS:
        assert "arv" not in f, f
        assert not bad_words.search(f), f


def test_flag_names_do_not_collide_with_the_board_qa_namespace():
    """Both passes write raw['qa_flags']. One name, one meaning."""
    import foreclosure_scraper.enrichment_board_qa as bq
    theirs = {bq.SHARED_ANCHOR_FLAG, bq.OWNER_MISMATCH_FLAG, bq.SALE_PASSED_FLAG,
              "dup_address", "gis_row_shared", "arv_below_asis", "arv_above_asis",
              "arv_sanity_flag", "arv_withheld", "verdict_on_flagged_arv",
              "bid_on_contradicted_arv", "derived_without_arv", "rehab_vs_condition",
              "missing_last_sale", "no_sqft", "no_owner"}
    assert not theirs & set(ALL_FLAGS)


def test_empty_board_returns_empty_summary():
    assert enrich_source_consistency([]) == {}


def test_survives_a_lead_object_with_no_raw_attribute_at_all():
    """Board passes are duck-typed over Listing-shaped objects; a missing or
    non-dict `raw` must not take the pass down for the other 38,499 leads."""
    class _Bare:
        source_url = "https://www.auction.com/details/510-kings-rd-shelby-nc-2141050"
        city = "CLEVELAND"
        county = "Cleveland"

    li = _Bare()
    enrich_source_consistency([li])          # must not raise
    assert URL_CITY_CONFLICT in (li.raw or {}).get("qa_flags", [])
