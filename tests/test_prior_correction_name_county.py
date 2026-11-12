"""enrichment_prior_correction, correction 4: a county read out of a debtor's case name.

6de9dba1 stopped courtlistener_bankruptcy._county_from_text from taking a town out of a person's
name ("Wilson", "Anderson", "Marion"); the rows already published keep the county it produced.
Row shapes are real board rows of 2026-10-06 (the raw blocks, geocoder tags and shared fallback
points the replay found), with every name, case number and id invented.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from foreclosure_scraper import enrichment_prior_correction as pc
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.enrichment_geocode import COUNTY_SEAT_CENTROIDS
from foreclosure_scraper.models import Listing, ListingType

ANDERSON_SEAT = COUNTY_SEAT_CENTROIDS[("SC", "Anderson")]
SHARED_COUNTY_POINT = (35.20001, -82.20001)         # a county centroid a geocode script wrote; not a seat
MEASURED_POINT = (34.612345, -82.401234)            # a real geocode: six decimals, no fallback tag


class FakeCache(pc.CacheReader):
    """parcel_cache stand-in: {(county, pid): row}; with no rows no county has a cache file (the
    correction must not need one)."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        super().__init__(lookup=lambda c, p, s: ((dict(self.rows[(c, str(p))]), "exact") if (c, str(p)) in self.rows
                                                 else (None, None)),
                         available=lambda c, s: bool(self.rows))


def _cl_raw(case_name: str, block: str = "courtlistener", **extra) -> dict:
    raw = {block: {"court": "scb", "docket_number": "26-00123", "chapter": "7", "case_name": case_name,
                   "date_filed": "2026-09-14", "nature_of_suit": None, "trustee": "Sample, Trustee Q"},
           "grade": "C", "data_quality": {"score": 40}}
    raw.update(extra)
    return raw


def _bk(case_name="Rhonda Anderson Tolliver", state="SC", county="Anderson", source="national.courtlistener_bankruptcy",
        block="courtlistener", raw_extra=None, **kw) -> Listing:
    base = dict(source=source, source_url="https://www.courtlistener.test/docket/70000001/sample/",
                listing_type=ListingType.BANKRUPTCY, state=state, county=county, case_number="26-00123",
                defendant=case_name, description=f"Ch.7 bankruptcy filed 2026-09-14 (SCB) - Debtor: {case_name}",
                first_seen=datetime(2026, 9, 20), last_seen=datetime(2026, 10, 5))
    base.update(kw)
    return Listing(raw=_cl_raw(case_name, block, **(raw_extra or {})), **base)


def _dump(li: Listing) -> str:
    return json.dumps(li.model_dump(mode="json"), sort_keys=True, default=str)


def _county_seat_row(pid="1230000001", **kw) -> Listing:
    """25 unrelated debtors of one county-seat parcel: the board's biggest group (Anderson)."""
    lat, lng = ANDERSON_SEAT
    raw_extra = {"parcel_from_geo": {"source": "native_point:Anderson", "lat": lat, "lng": lng},
                 "geo_imprecise": "centroid_snap",
                 "owner_mailing": {"owner": "ANDERSON CITY OF", "mailing": "100 S SAMPLE ST, ANDERSON SC, 29621",
                                   "situs": None, "parcel_id": pid, "source": "sc_assessor_roll"},
                 "zillow": {}, "images": {}, "gis": None,
                 "flood": {"zone": "X", "in_sfha": False}, "census_demographics": {"zcta5": "29621"}}
    raw_extra.update(kw.pop("raw_extra", {}))
    return _bk(parcel_id=pid, latitude=lat, longitude=lng, market_value=47570.0, tax_value=47570.0,
               assessed_value=90000.0, living_sqft=1800.0, zip_code="29621", raw_extra=raw_extra, **kw)


def _run(rows, cache=None):
    return pc.correct_prior_rows(rows, cache=cache or FakeCache())


# --------------------------------------------------------------------------------- cleared rows
def test_a_county_only_row_loses_its_county_and_keeps_the_old_one_in_the_audit():
    li = _bk()
    stats = _run([li])
    assert li.county is None and li.state == "SC"
    a = li.raw[pc.NAME_COUNTY_KEY]
    assert a["county"] == "Anderson" and a["legacy_counties"] == ["Anderson"]
    assert a["point"] == {"action": "absent"} and "cleared" not in a and "parcel_withdrawn" not in a
    assert a["source"] == "national.courtlistener_bankruptcy" and a["state"] == "SC"
    assert li.raw["courtlistener"]["case_name"] == "Rhonda Anderson Tolliver"      # the docket is untouched
    assert stats["name_county_cleared"] == 1 and stats["name_county_detail"]["point_absent"] == 1


def test_a_surname_that_is_a_town_in_another_state_gets_no_county_either():
    # "Wilson" is a NC county and town; a NC court's debtor named Wilson is not a Wilson County lead
    li = _bk(case_name="Larry Wilson", state="NC", county="Wilson")
    _run([li])
    assert li.county is None and li.raw[pc.NAME_COUNTY_KEY]["county"] == "Wilson"


def test_a_substring_of_a_longer_word_was_the_old_functions_county_and_is_cleared():
    # "Vanderson" contains the town Anderson: the old code matched substrings
    li = _bk(case_name="Jane Vanderson", county="Anderson")
    _run([li])
    assert li.county is None


def test_county_seat_parcel_row_is_cleared_with_its_point_and_the_facts_that_came_with_the_parcel():
    li = _county_seat_row()
    cache = FakeCache({("Anderson", "1230000001"): {"owner": "ANDERSON CITY OF", "market_value": 47570.0,
                                                   "owner_mailing": "100 S SAMPLE ST ANDERSON SC 29621"}})
    stats = _run([li], cache)
    # correction 1 withdrew the fallback parcel and what it could prove was copied from it
    assert li.parcel_id is None and li.market_value is None and li.tax_value is None
    assert pc.FALLBACK_KEY in li.raw and li.raw[pc.FALLBACK_KEY]["reason"] == "county_seat_point"
    # correction 4: the county, the county-seat point and its tags, and the facts step 1 could not prove
    assert li.county is None and li.latitude is None and li.longitude is None
    assert li.zip_code is None and li.assessed_value is None and li.living_sqft is None
    assert "geo_imprecise" not in li.raw
    a = li.raw[pc.NAME_COUNTY_KEY]
    assert a["county"] == "Anderson"
    assert a["point"] == {"action": "cleared", "old": list(ANDERSON_SEAT), "tags": {"geo_imprecise": "centroid_snap"}}
    assert a["cleared"] == {"zip_code": "29621", "assessed_value": 90000.0, "living_sqft": 1800.0}
    assert "parcel_withdrawn" not in a                                    # step 1 did that one
    assert stats["fallback_withdrawn"] == 1 and stats["name_county_cleared"] == 1
    assert stats["name_county_fields_cleared"] == {"zip_code": 1, "assessed_value": 1, "living_sqft": 1}


def test_without_a_parcel_cache_correction_4_clears_the_values_correction_1_could_not_prove():
    # on this Mac 25 counties have no parcel_cache: step 1 keeps the values it cannot match to a record,
    # but a docket carries none, so once the parcel is gone they have no basis
    li = _county_seat_row()
    _run([li])
    assert li.parcel_id is None and li.county is None
    a = li.raw[pc.NAME_COUNTY_KEY]
    assert a["cleared"] == {"market_value": 47570.0, "tax_value": 47570.0, "assessed_value": 90000.0,
                            "living_sqft": 1800.0, "zip_code": "29621"}
    assert li.market_value is li.tax_value is li.assessed_value is li.living_sqft is li.zip_code is None


def test_a_street_written_from_the_withdrawn_fallback_parcel_does_not_keep_the_county():
    # the 2 board rows: street copied from the county-seat parcel's record (parcel_cache:exact)
    lat, lng = ANDERSON_SEAT
    li = _county_seat_row(street_address="100 S SAMPLE ST", raw_extra={"situs_address_source": "parcel_cache:exact",
                          "owner_mailing": {"owner": "ANDERSON CITY OF", "mailing": "PO BOX 1, ANDERSON SC, 29621",
                                            "situs": "100 S SAMPLE ST", "parcel_id": "1230000001", "source": "sc_assessor_roll"}})
    cache = pc.CacheReader(lookup=lambda c, p, s: ({"owner": "ANDERSON CITY OF", "address": "100 S SAMPLE ST",
                                                    "owner_mailing": "PO BOX 1 ANDERSON SC 29621"}, "exact"),
                           available=lambda c, s: True)
    stats = pc.correct_prior_rows([li], cache=cache)
    assert li.street_address is None and li.parcel_id is None and li.county is None
    assert stats["name_county_cleared"] == 1


def test_a_shared_fallback_point_that_is_not_a_county_seat_is_cleared_too():
    # geocode_catchup's county centroid (27 board rows), flagged county_centroid_no_addr
    li = _bk(latitude=SHARED_COUNTY_POINT[0], longitude=SHARED_COUNTY_POINT[1],
             raw_extra={"geo_imprecise": "county_centroid_no_addr"})
    _run([li])
    assert li.county is None and li.latitude is None and li.longitude is None and "geo_imprecise" not in li.raw
    assert li.raw[pc.NAME_COUNTY_KEY]["point"]["old"] == list(SHARED_COUNTY_POINT)


def test_a_point_parcel_that_correction_1_did_not_call_a_fallback_is_withdrawn_by_correction_4():
    # resolved at the row's own flagged county centroid, which no other row shares and is no county seat
    lat, lng = SHARED_COUNTY_POINT
    li = _bk(parcel_id="4440009999", latitude=lat, longitude=lng, market_value=61000.0, zip_code="29640",
             raw_extra={"parcel_from_geo": {"source": "native_point:Anderson", "lat": lat, "lng": lng},
                        "geo_imprecise": "centroid_snap",
                        "owner_mailing": {"owner": "SAMPLE HOLDINGS", "mailing": "PO BOX 9, PICKENS SC, 29671",
                                          "situs": None, "parcel_id": "4440009999", "source": "sc_assessor_roll"}})
    stats = _run([li])
    assert stats["fallback_withdrawn"] == 0                               # not a seat, not shared by 8
    assert li.parcel_id is None and li.county is None and li.latitude is None
    assert li.market_value is None and li.zip_code is None
    assert li.raw[pc.FALLBACK_KEY]["reason"] == "county_name_derived_point"
    a = li.raw[pc.NAME_COUNTY_KEY]
    assert a["parcel_withdrawn"] == "4440009999"
    assert a["cleared"] == {"market_value": 61000.0, "zip_code": "29640"}
    assert "owner_mailing" not in li.raw and "parcel_from_geo" not in li.raw


@pytest.mark.parametrize("source,block,state,county,case_name", [
    ("national.courtlistener_adversary", "courtlistener_adversary", "NC", "Wilson", "In re Larry Wilson"),
    ("national.courtlistener_civil", "courtlistener_civil", "SC", "Anderson", "Rhonda Anderson Tolliver"),
])
def test_the_adversary_and_civil_scrapers_share_the_function_and_the_correction(source, block, state, county, case_name):
    li = _bk(case_name=case_name, state=state, county=county, source=source, block=block,
             listing_type=ListingType.LIS_PENDENS)
    _run([li])
    assert li.county is None and li.raw[pc.NAME_COUNTY_KEY]["source"] == source


# ------------------------------------------------- untouched: the county rests on something else
def test_a_street_found_by_a_name_search_keeps_the_county():
    # resolved_from_name searched the county's owner index; own street and parcel, not a point
    li = _bk(street_address="12 SAMPLE FARM RD", parcel_id="5550007777", latitude=MEASURED_POINT[0],
             longitude=MEASURED_POINT[1], owner_name="Rhonda A Tolliver",
             raw_extra={"resolved_from_name": {"strategy": "gis_owner_name_search", "county": "Anderson", "state": "SC",
                                               "confidence": "unique_match"}})
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before and li.county == "Anderson"
    assert stats["name_county_detail"] == {"skip_own_street": 1}


def test_a_parcel_matched_from_an_address_or_a_name_keeps_the_county():
    li = _bk(parcel_id="5550008888", raw_extra={"parcel_from_address": {"source": "county_gis_address"}})
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before
    assert stats["name_county_detail"] == {"skip_parcel_not_from_point": 1}


def test_a_parcel_resolved_at_a_measured_point_keeps_the_county():
    lat, lng = MEASURED_POINT
    li = _bk(parcel_id="5550009999", latitude=lat, longitude=lng,
             raw_extra={"parcel_from_geo": {"source": "native_point:Anderson", "lat": lat, "lng": lng}})
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before and li.parcel_id == "5550009999"
    assert stats["name_county_detail"] == {"skip_parcel_point_not_county_level": 1}


def test_a_measured_point_without_a_street_or_parcel_keeps_the_county():
    li = _bk(latitude=MEASURED_POINT[0], longitude=MEASURED_POINT[1])
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before
    assert stats["name_county_detail"] == {"skip_measured_point": 1}


def test_property_facts_with_no_parcel_to_explain_them_keep_the_county():
    li = _bk(zip_code="29621", market_value=90000.0)
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before
    assert stats["name_county_detail"] == {"skip_property_facts_without_parcel": 1}


def test_a_county_the_old_function_did_not_produce_is_never_touched():
    # a Greenville parcel resolved for a debtor whose name holds Anderson: the county is the resolver's
    li = _bk(county="Greenville", street_address="3 SAMPLE CT", parcel_id="6660001111", latitude=MEASURED_POINT[0],
             longitude=MEASURED_POINT[1], zip_code="29601")
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before
    assert "name_county_detail" in stats and stats["name_county_detail"] == {}


def test_an_organization_named_for_its_town_keeps_its_county():
    li = _bk(case_name="Wilson Hardware & Supply, LLC", state="NC", county="Wilson")
    before = _dump(li)
    stats = _run([li])
    assert _dump(li) == before and li.county == "Wilson"
    assert stats["name_county_detail"] == {"skip_organization_name": 1}
    assert pc.NAME_COUNTY_KEY not in li.raw


def test_rows_of_other_sources_and_rows_without_a_case_name_are_not_candidates():
    other = Listing(source="counties_sc.sc_public_index", source_url="https://example.test/x", state="SC",
                    county="Anderson", defendant="Rhonda Anderson Tolliver", raw={"sc_public_index": {}})
    nameless = _bk()
    nameless.raw["courtlistener"].pop("case_name")
    b1, b2 = _dump(other), _dump(nameless)
    stats = _run([other, nameless])
    assert _dump(other) == b1 and _dump(nameless) == b2
    assert stats["name_county_cleared"] == 0 and stats["name_county_detail"] == {}


# ------------------------------------------------------------------ idempotence, audit, dedupe
def test_running_the_step_twice_changes_nothing_more():
    rows = [_bk(), _county_seat_row(), _bk(case_name="Larry Wilson", state="NC", county="Wilson"),
            _bk(case_name="Wilson Hardware & Supply, LLC", state="NC", county="Wilson"),
            _bk(street_address="12 SAMPLE FARM RD", parcel_id="5550007777")]
    first = _run(rows)
    snap = [_dump(r) for r in rows]
    second = _run(rows)
    assert [_dump(r) for r in rows] == snap
    # cleared: the county-only row, the county-seat row, the debtor named Wilson; kept: the organization
    # and the row with its own street and parcel
    assert first["name_county_cleared"] == 3 and second["name_county_cleared"] == 0
    assert second["fallback_withdrawn"] == 0


def test_the_audit_key_is_protected_from_the_other_corrections_and_survives_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert RAW_KEEP.get(pc.NAME_COUNTY_KEY) == "*" and pc.NAME_COUNTY_KEY in pc._PROTECTED_RAW


def test_the_cleared_prior_copy_folds_into_its_county_less_rescrape_instead_of_standing_beside_it():
    prior = _bk()
    fresh = _bk(county=None)
    assert len(dedupe([_bk(), _bk(county=None)])) == 2                    # as published: two rows
    _run([prior])
    assert prior.dedupe_key() == fresh.dedupe_key()
    assert len(dedupe([prior, fresh])) == 1


# ------------------------------------------------------------------------- the frozen old logic
def _old_county_from_text(text, state):
    """courtlistener_bankruptcy._county_from_text exactly as it was before 6de9dba1."""
    from foreclosure_scraper._bankruptcy_city_to_county import KNOWN_CITIES, bankruptcy_county_for
    if not text:
        return None
    upper = text.upper()
    for city in KNOWN_CITIES:
        if city.upper() in upper:
            county = bankruptcy_county_for(city, state)
            if county:
                return county
    return None


@pytest.mark.parametrize("name,state", [
    ("Larry Wilson", "NC"), ("Jane Vanderson", "SC"), ("Sample Marion Doe", "NC"), ("Charlotte Q Example", "NC"),
    ("Wilson Hardware & Supply, LLC", "NC"), ("Rhonda Anderson Tolliver", "SC"), ("Pat Q Example", "SC"),
    ("North Charleston Sample Foods, Inc.", "SC"), ("Mount Airy Example Tire Co.", "NC"), ("", "NC"), (None, "SC"),
    ("Larry Wilson", None),
])
def test_legacy_helper_returns_what_the_old_function_returned(name, state):
    old = _old_county_from_text(name, state)
    legacy = pc.legacy_name_counties(name, state)
    if old is None:
        assert legacy == set()
    else:
        assert old in legacy
    # no tie in these names, so the set is the old answer exactly
    assert legacy == ({old} if old else set())


def test_legacy_helper_returns_every_county_of_a_tie_for_the_best_rank():
    # two towns of equal rank in one name: the old order between them was a set's iteration order
    from foreclosure_scraper._bankruptcy_city_to_county import KNOWN_CITIES, bankruptcy_county_for
    by_rank = {}
    for c in KNOWN_CITIES:
        if bankruptcy_county_for(c, "NC") and " " not in c:
            by_rank.setdefault(len(c), []).append(c)
    pair = next(((a, b) for v in by_rank.values() for a in v for b in v
                 if a < b and bankruptcy_county_for(a, "NC") != bankruptcy_county_for(b, "NC")
                 and a not in b and b not in a), None)
    assert pair, "gazetteer has no equal-length NC towns of different counties"
    text = f"{pair[0].title()} {pair[1].title()}"
    got = pc.legacy_name_counties(text, "NC")
    assert _old_county_from_text(text, "NC") in got
    assert {bankruptcy_county_for(pair[0], "NC"), bankruptcy_county_for(pair[1], "NC")} <= got
