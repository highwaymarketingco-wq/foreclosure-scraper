"""Spartanburg County EnerGov self-service Code Case + Permit scraper.

The search endpoint has been in an unconditional HTTP 500 outage since it was
first discovered (verification pass + independent re-confirmation, both
2026-11-19) -- see the module's own docstring. Unlike spartanburg_condemned.py's
own test fixtures ("shaped exactly like the live ArcGIS feature JSON... captured
from the real service"), the row-shape fixtures below are NOT captured from a real
response -- none exists yet. They are built from field names seen as Angular
grid-column bindings in the self-service portal's own JS bundle
(energov_bundle.js, saved during the verification pass) -- a reasonable, evidence-
grounded guess, not a confirmed shape. Re-validate `_to_listing_code_case`/
`_to_listing_permit` the first time the live endpoint returns real rows.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

import pytest

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc import spartanburg_energov_selfservice as sc

SLUG = "counties_sc.spartanburg_energov_selfservice"


def _s() -> sc.SpartanburgEnergovSelfservice:
    return sc.SpartanburgEnergovSelfservice()


# ---------------------------------------------------------------------------
# Request body -- CONFIRMED shape (built off the live /search/criteria endpoint)
# ---------------------------------------------------------------------------
def test_code_case_body_targets_code_case_module_and_sets_date_floor():
    body = _s()._body(sc._MODULE_CODE_CASE, "code_case", page=1, since_iso="2016-11-19")
    assert body["SearchModule"] == sc._MODULE_CODE_CASE
    assert body["FilterModule"] == sc._MODULE_CODE_CASE
    assert body["CodeCaseCriteria"]["OpenedDateFrom"] == "2016-11-19"
    assert body["CodeCaseCriteria"]["PageNumber"] == 1
    assert body["PageNumber"] == 1 and body["PageSize"] == sc._PAGE_SIZE
    # Every other criteria sub-object stays the server's own blank shape (0/0) --
    # a narrowed, single-module query, not a kitchen-sink search.
    assert body["PermitCriteria"] == {"PageNumber": 0, "PageSize": 0}


def test_permit_body_targets_permit_module_and_sets_date_floor():
    body = _s()._body(sc._MODULE_PERMIT, "permit", page=2, since_iso="2016-11-19")
    assert body["SearchModule"] == sc._MODULE_PERMIT
    assert body["PermitCriteria"]["IssueDateFrom"] == "2016-11-19"
    assert body["PermitCriteria"]["PageNumber"] == 2
    assert body["CodeCaseCriteria"] == {"PageNumber": 0, "PageSize": 0}


def test_body_field_names_match_the_live_criteria_endpoint():
    # These field names are read straight off the server's own authoritative
    # SearchCriteriaModel (GET .../search/criteria, confirmed 200 live) -- not
    # guessed. A rename here would mean this test (and the real request) is
    # using a field the server no longer recognizes.
    body = _s()._body(sc._MODULE_CODE_CASE, "code_case", page=1, since_iso="2020-01-01")
    for top_key in ("Keyword", "ExactMatch", "SearchModule", "FilterModule",
                    "SearchMainAddress", "PlanCriteria", "PermitCriteria",
                    "InspectionCriteria", "CodeCaseCriteria", "RequestCriteria",
                    "PageNumber", "PageSize", "SortBy", "SortAscending"):
        assert top_key in body, top_key
    for cc_key in ("OpenedDateFrom", "PageNumber", "PageSize"):
        assert cc_key in body["CodeCaseCriteria"], cc_key


# ---------------------------------------------------------------------------
# Response envelope unwrapping -- UNCONFIRMED shape (best-effort, see module docstring)
# ---------------------------------------------------------------------------
def test_unwrap_rows_handles_the_confirmed_criteria_envelope_shape():
    # The live /search/criteria endpoint's own confirmed envelope: {"Result": {...}}
    # with the list under a named sub-key.
    body = {"Result": {"Results": [{"a": 1}, {"a": 2}]}, "Success": True}
    assert sc._unwrap_rows(body) == [{"a": 1}, {"a": 2}]


def test_unwrap_rows_handles_plausible_fallback_shapes():
    assert sc._unwrap_rows({"Result": [{"a": 1}]}) == [{"a": 1}]
    assert sc._unwrap_rows({"Items": [{"a": 1}]}) == [{"a": 1}]
    assert sc._unwrap_rows({"Data": []}) == []
    assert sc._unwrap_rows({}) == []
    assert sc._unwrap_rows(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Code Case row -> code_enforcement signal
# ---------------------------------------------------------------------------
_CODE_CASE_OPEN = {
    "CaseNumber": "CE-2026-00412",
    "MainAddress": "3609 SHERWOOD DR",
    "ParcelNumber": "7-21-12-027.00",
    "OwnerName": "SMITH JANE",
    "CaseType": "Dilapidated Structure",
    "StatusName": "Open",
    "OpenedDate": "2026-06-01T00:00:00",
    "ContactAddress": "100 MAIN ST", "ContactCity": "CHARLOTTE",
    "ContactState": "NC", "ContactZip": "28202",
}

_CODE_CASE_CLOSED = dict(_CODE_CASE_OPEN, CaseNumber="CE-2025-00100",
                         ClosedDate="2025-08-01T00:00:00")

_CODE_CASE_GOV = dict(_CODE_CASE_OPEN, OwnerName="CITY OF SPARTANBURG")

_CODE_CASE_NO_KEY = {"OwnerName": "NOBODY", "CaseNumber": "CE-0"}  # no address or parcel


def test_open_code_case_sets_code_enforcement_signal_with_stale_after():
    li = _s()._to_listing_code_case(_CODE_CASE_OPEN)
    assert li is not None
    assert li.source == SLUG
    assert li.state == "SC" and li.county == "Spartanburg"
    assert li.street_address == "3609 SHERWOOD DR"
    assert li.parcel_id == "7-21-12-027.00"
    assert li.owner_name == "SMITH JANE" and li.defendant == "SMITH JANE"
    assert li.listing_type == ListingType.UNKNOWN
    assert li.property_kind == PropertyKind.UNKNOWN
    ce = li.raw.get("code_enforcement")
    assert isinstance(ce, dict)
    assert ce["case_number"] == "CE-2026-00412"
    assert ce["opened_date"] == "2026-06-01"
    # No closed date -> ages out 365 days after opening (charleston_energov_history.py convention)
    assert ce["stale_after"] == (date(2026, 6, 1) + timedelta(days=365)).isoformat()
    assert "has_open" not in ce  # no confirmed status enum to invent this from
    assert li.raw.get("distressed") is True
    assert li.raw.get("owner_mailing") == "100 MAIN ST CHARLOTTE NC 28202"


def test_closed_code_case_has_no_stale_after():
    li = _s()._to_listing_code_case(_CODE_CASE_CLOSED)
    assert li is not None
    ce = li.raw["code_enforcement"]
    assert ce["closed_date"] == "2025-08-01"
    assert "stale_after" not in ce


def test_code_enforcement_signal_is_in_raw_keep_and_survives_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw
    assert RAW_KEEP.get("code_enforcement") == "*"
    assert RAW_KEEP.get("permit_activity") == "*"
    raw_in = {"code_enforcement": {"case_number": "CE-1", "stale_after": "2027-01-01"}}
    assert _slim_raw(raw_in) == raw_in


def test_government_owner_code_case_dropped():
    assert _s()._to_listing_code_case(_CODE_CASE_GOV) is None


def test_code_case_with_no_address_or_parcel_dropped():
    assert _s()._to_listing_code_case(_CODE_CASE_NO_KEY) is None


# ---------------------------------------------------------------------------
# Permit row -> permit_activity signal (stalled-renovation detection)
# ---------------------------------------------------------------------------
def _permit(issue_date: str, final_date: str | None = None, expire_date: str | None = None,
            owner: str = "DOE JOHN") -> dict:
    row = {
        "PermitNumber": "BP-2024-01177",
        "MainAddress": "182 SHERWOOD DR",
        "ParcelNumber": "5-16-13-003.09",
        "OwnerName": owner,
        "PermitType": "Residential Addition/Alteration",
        "StatusName": "Issued",
        "IssueDate": issue_date,
    }
    if final_date:
        row["FinalDate"] = final_date
    if expire_date:
        row["ExpireDate"] = expire_date
    return row


def test_stalled_permit_flagged_when_expired_and_never_finaled():
    row = _permit(issue_date="2025-01-10", expire_date="2025-07-10")
    li = _s()._to_listing_permit(row)
    assert li is not None
    assert li.parcel_id == "5-16-13-003.09"
    act = li.raw["permit_activity"]
    assert act["permit_number"] == "BP-2024-01177"
    assert act["issue_date"] == "2025-01-10"
    assert act["expire_date"] == "2025-07-10"
    assert "final_date" not in act
    assert act["stalled"] is True


def test_stalled_permit_flagged_when_old_and_never_finaled_even_without_expire_date():
    old_issue = (date.today() - timedelta(days=400)).isoformat()
    row = _permit(issue_date=old_issue)
    act = _s()._to_listing_permit(row).raw["permit_activity"]
    assert act["stalled"] is True


def test_finaled_permit_not_flagged_stalled():
    row = _permit(issue_date="2025-01-10", final_date="2025-03-01")
    act = _s()._to_listing_permit(row).raw["permit_activity"]
    assert act["final_date"] == "2025-03-01"
    assert act["stalled"] is False


def test_recent_unexpired_unfinaled_permit_not_yet_flagged_stalled():
    recent_issue = (date.today() - timedelta(days=10)).isoformat()
    row = _permit(issue_date=recent_issue)
    act = _s()._to_listing_permit(row).raw["permit_activity"]
    assert act["stalled"] is False


def test_permit_does_not_set_condemned_flag():
    # charleston_energov_history.py precedent: a permit is an application, not a
    # condemnation. Must never set raw['condemned'] on its own.
    row = _permit(issue_date="2020-01-01", expire_date="2020-07-01")
    li = _s()._to_listing_permit(row)
    assert "condemned" not in li.raw


def test_government_owner_permit_dropped():
    row = _permit(issue_date="2025-01-10", owner="SPARTANBURG COUNTY")
    assert _s()._to_listing_permit(row) is None


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------
def test_parse_date_handles_iso_and_dotnet_json_date():
    assert sc._parse_date("2026-06-01T00:00:00") == date(2026, 6, 1)
    assert sc._parse_date("2026-06-01") == date(2026, 6, 1)
    assert sc._parse_date("/Date(1748736000000)/") == date(2025, 6, 1)
    assert sc._parse_date(None) is None
    assert sc._parse_date("") is None
    assert sc._parse_date("not a date") is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert SLUG in slugs


def test_scraper_whitelisted_as_dateless():
    from foreclosure_scraper.main import DATELESS_OK_SOURCES

    assert SLUG in DATELESS_OK_SOURCES


# ---------------------------------------------------------------------------
# Live smoke (network-gated). Written to pass in EITHER the current confirmed-
# down state or a future healed state, so it does not need rewriting the moment
# Tyler's tenant recovers -- it only asserts "never a silent/misleading zero".
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live Spartanburg EnerGov self-service API — set RUN_NETWORK_TESTS=1",
)
def test_live_reports_blocked_not_a_silent_zero_while_backend_is_down():
    s = _s()
    rows = asyncio.run(s.safe_run())
    if s.last_outcome == "OK":
        # Backend has healed since this was written -- real rows should exist.
        assert rows, "backend reports OK but returned no rows"
        for li in rows:
            assert li.state == "SC" and li.county == "Spartanburg"
            assert li.parcel_id or li.street_address
    else:
        # Still down: must be reported as BLOCKED (base_scraper.py's own 5xx
        # classification), never as a clean OUTCOME_ZERO -- that would silently
        # look like "Spartanburg genuinely has no code cases or permits", which
        # is false and exactly the failure mode this module exists to avoid.
        assert rows == []
        assert s.last_outcome == "BLOCKED", (
            f"expected BLOCKED while backend is down, got {s.last_outcome!r} "
            f"({s.last_reason!r})")
