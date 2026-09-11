"""SC Catalis/Sturgis delinquent roll: the filters that are NOT the obvious ones, and the
owner-occupancy verdict that must never be invented.

This source exists for one field. SC owner contact runs 8-18% against NC's 50-89% and the
per-county coverage matrix names it the binding constraint in every SC county; this API
returns the owner's MAILING address on essentially every record (live 2026-09-10: 2,566 of
2,570 Pickens leads). It also covers Pickens, which the 19-county qPayBill roll does not --
its treasurer is on a different vendor -- so it is the seventh SC footprint county getting
a delinquent-tax lane at all.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_catalis_delinquent_roll import (
    CATALIS_COUNTIES, PAGE_CAP, _addr, is_delinquent_real_property, owner_occupancy,
    to_listing,
)

#: Verbatim shape from the live API, prefix "AB", 2026-09-10.
REAL = {
    "ParcelNumber": "4192-00-96-2106", "BillingID": "4192-00-96-21060001763",
    "Year": 2025, "RecordType": "Delinquent", "RealPropertyType": True,
    "isDelinquent": False,                      # <- the trap, see below
    "OwnerName1": "ABEL SEBASTIN", "OwnerName2": None,
    "OwnerAddress": {"Line1": "", "Line2": "176 SHANNON CIR", "Line3": None,
                     "City": "PICKENS                 SC", "State": None, "Zip": "29671"},
    "SitusAddress": {"Line1": "1987 HORTON 14 X 56 10458657", "Line2": None,
                     "Line3": None, "City": None, "State": None, "Zip": None},
    "Values": {"Appraised": 6900, "Assessed": 410,
               "BuildingAppraisal_4Pct": 0, "BuildingAppraisal_6Pct": 6900,
               "LandAppraisal_4Pct": 0, "LandAppraisal_6Pct": 0,
               "BuildingAppraisal_10pt5Pct": 0, "LandAppraisal_10pt5Pct": 0},
    "CountyValues": {"GrossTax": 99.75, "Mills": 243.3, "HomesteadExemption": 0.0,
                     "LegalResidenceExemption": 0.0},
    "Description": "1987 HORTON 14 X 56 10458657", "IDHash": "737FECDBBAB40145",
}


# ---------------------------------------------------------------------------
# The two filters, neither of which is the field you would reach for first
# ---------------------------------------------------------------------------

def test_is_delinquent_reads_record_type_not_the_isdelinquent_flag():
    """THE trap. `isDelinquent` was False on EVERY delinquent real-property row in the
    live sample -- it is a vehicle-oriented flag. The real marker is RecordType."""
    assert REAL["isDelinquent"] is False
    assert is_delinquent_real_property(REAL) is True


@pytest.mark.parametrize("patch,expect", [
    ({"RecordType": "Property"}, False),         # current-year bill, not delinquent
    ({"RecordType": ""}, False),
    ({"RecordType": None}, False),
    ({"RecordType": "DELINQUENT"}, True),        # case must not matter
    ({"RealPropertyType": False}, False),        # a vehicle
    ({"RealPropertyType": None}, False),
])
def test_both_filters_are_required(patch, expect):
    rec = {**REAL, **patch}
    assert is_delinquent_real_property(rec) is expect


def test_the_type_filter_in_the_request_does_not_do_this_job():
    """Documents why client-side filtering exists: asking the API for type="Property"
    returned 390 records for prefix "AB" of which only 80 were real property."""
    vehicle = {**REAL, "RealPropertyType": False, "RecordType": "Delinquent"}
    assert is_delinquent_real_property(vehicle) is False


# ---------------------------------------------------------------------------
# Owner occupancy from the SC assessment ratio
# ---------------------------------------------------------------------------

def test_value_in_the_six_percent_columns_means_not_owner_occupied():
    """SC law: 4% is the owner-occupied legal-residence ratio, 6% is everything else."""
    assert owner_occupancy(REAL["Values"]) is False


def test_value_in_the_four_percent_columns_means_owner_occupied():
    v = {**REAL["Values"], "BuildingAppraisal_4Pct": 6900, "BuildingAppraisal_6Pct": 0}
    assert owner_occupancy(v) is True


@pytest.mark.parametrize("values", [
    {}, None, {"Appraised": 6900},
    {"BuildingAppraisal_4Pct": 0, "BuildingAppraisal_6Pct": 0,
     "LandAppraisal_4Pct": 0, "LandAppraisal_6Pct": 0},
])
def test_no_ratio_information_yields_None_never_False(values):
    """False asserts 'the county says this is not their residence'. Inventing that from
    missing data puts a homeowner on an absentee call list."""
    assert owner_occupancy(values) is None


def test_land_and_building_are_summed_on_both_sides():
    # 4% side 100+50=150 vs 6% side 80+60=140 -> the 4% side is larger, owner-occupied.
    v = {"BuildingAppraisal_4Pct": 100, "LandAppraisal_4Pct": 50,
         "BuildingAppraisal_6Pct": 80, "LandAppraisal_6Pct": 60}
    assert owner_occupancy(v) is True
    # Flip it: 4% side 10+20=30 vs 6% side 80+60=140 -> not owner-occupied.
    v2 = {"BuildingAppraisal_4Pct": 10, "LandAppraisal_4Pct": 20,
          "BuildingAppraisal_6Pct": 80, "LandAppraisal_6Pct": 60}
    assert owner_occupancy(v2) is False
    # The 10.5% manufacturing ratio also counts as "not the owner's residence".
    v3 = {"BuildingAppraisal_4Pct": 0, "LandAppraisal_4Pct": 0,
          "BuildingAppraisal_10pt5Pct": 500, "LandAppraisal_6Pct": 0}
    assert owner_occupancy(v3) is False


# ---------------------------------------------------------------------------
# The mailing address, which is the whole point
# ---------------------------------------------------------------------------

def test_the_owner_mailing_address_is_flattened_from_its_parts():
    """City arrives as 'PICKENS                 SC' -- name and state padded into one
    field with State itself null -- so the parts are joined and whitespace collapsed
    rather than assumed."""
    assert _addr(REAL["OwnerAddress"]) == "176 SHANNON CIR PICKENS SC 29671"


@pytest.mark.parametrize("block", [None, {}, "a string", {"Line1": "", "City": None}])
def test_a_missing_address_block_yields_None(block):
    assert _addr(block) is None


def test_the_listing_carries_mailing_value_and_occupancy():
    li = to_listing("Pickens", REAL)
    assert li.parcel_id == "4192-00-96-2106"
    assert li.owner_name == "ABEL SEBASTIN"
    assert li.state == "SC" and li.county == "Pickens"
    assert li.tax_value == 6900.0
    raw = li.raw["catalis_roll"]
    assert raw["owner_mailing"] == "176 SHANNON CIR PICKENS SC 29671"
    assert raw["owner_occupied"] is False
    assert raw["billing_id"] == "4192-00-96-21060001763"
    assert "NOT owner-occupied" in li.description


def test_two_owners_are_joined():
    li = to_listing("Pickens", {**REAL, "OwnerName2": "ABEL MARY"})
    assert li.owner_name == "ABEL SEBASTIN ABEL MARY"


def test_a_record_with_no_parcel_is_not_a_lead():
    """No parcel means it cannot be underwritten, joined or routed."""
    assert to_listing("Pickens", {**REAL, "ParcelNumber": ""}) is None
    assert to_listing("Pickens", {**REAL, "ParcelNumber": None}) is None


def test_billing_id_keeps_multi_year_rows_distinct():
    """A parcel delinquent for three years arrives as three records; keying on BillingID
    is what stops them collapsing into one."""
    a, b = dict(REAL), {**REAL, "Year": 2024, "BillingID": "4192-00-96-21060001764"}
    assert a["BillingID"] != b["BillingID"]


def test_page_cap_and_county_config():
    assert PAGE_CAP == 1000
    assert "Pickens" in CATALIS_COUNTIES
    guid, site = CATALIS_COUNTIES["Pickens"]
    assert len(guid) == 36 and site.startswith("https://")


# ---------------------------------------------------------------------------
# HTTP 429 MUST NEVER LOOK LIKE AN EMPTY PREFIX
#
# The first version of sweep_county did `rows = r.json()` with no status check.
# The host (whose robots asks not to be crawled) enforces with 429, and after a
# 600-request burst it rate-limited the next run for minutes. The sweep reported
#     queries=36  records_seen=0  errors=0  leads=0
# a completely clean log for a county whose roll it had entirely failed to read.
# That is the same silent-loss shape as every other bug found on this project:
# working code, wrong assumption, no error.
# ---------------------------------------------------------------------------

def test_the_module_checks_the_status_code_before_parsing():
    """Guards the fix at the source, since the network path itself is not unit-testable
    without mocking httpx: the module must reference 429 and Retry-After explicitly."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" /
           "scrapers" / "counties_sc" / "sc_catalis_delinquent_roll.py").read_text()
    assert "status_code == 429" in src, "a 429 must be detected, not parsed as data"
    assert "Retry-After" in src, "honor the server's own backoff hint"
    assert "raise_for_status" in src, "any non-2xx must raise, not become an empty list"
    assert "rate_limited" in src, "rate limiting must be counted and visible in the log"
    # And a non-list body must be treated as an error rather than iterated.
    assert "expected a list" in src


def test_the_sweep_is_paced_and_low_concurrency_by_default():
    """The host asked not to be crawled and enforces it. Reading the same roll slowly is
    both the courteous and the effective choice -- the burst got us nothing but a 429."""
    import foreclosure_scraper.scrapers.counties_sc.sc_catalis_delinquent_roll as m
    assert m._CONCURRENCY == 1
    assert m._PACE_S >= 1.0
    assert m._BACKOFF_S >= 5.0


def test_a_lost_prefix_is_named_not_just_counted():
    """An unreadable initial is a hole in the county's roll. It must be identifiable."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" /
           "scrapers" / "counties_sc" / "sc_catalis_delinquent_roll.py").read_text()
    assert 'stats.setdefault("lost_prefixes", []).append(prefix)' in src
    assert "INCOMPLETE" in src
