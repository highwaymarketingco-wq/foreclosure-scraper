"""Wake County NC open code cases.

2026-11-16 (round 9, vacant_structure "no source known" breadth pass): this file already
classified a "vacant" tag (DESCRIPTION matched the module's `_STRUCT["vacant"]` regex) into
code_enforcement.violation_types/vacancy_adjacent, but never mirrored it into
raw['vacancy']/raw['gis']['vacant'] -- the two keys gap_matrix.py's own "vacancy"/"vacant" columns
actually check -- same omission, same fix, as lincoln_code_violations.py's "Abandoned structure"
rows (round 8, same day).

While live-sampling 144 real open cases to measure this fix's yield, the ONLY case the old
`vacant|abandon|boarded` regex matched was VIO-008568-2026, "Use of vacant LOT to park and store
commercial tow trucks" -- a zoning/land-use complaint about an ordinary vacant PARCEL, not a
distressed structure. These tests pin both the new vacancy/gis.vacant bridge AND the regex fix
that keeps a "vacant lot" complaint from falsely triggering it (and, pre-existing this pass, from
falsely contributing to `severe`/`distressed` too).
"""
from __future__ import annotations

from datetime import datetime, timezone

from foreclosure_scraper.scrapers.counties_nc.wake_code_cases import classify, to_listing

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


def _attrs(case_type, description, *, case_number="VIO-000001-2026",
           status="In Progress", street="123 MAIN ST", city_zip="RALEIGH, NC 27601",
           opened_ms=1_700_000_000_000):
    return {
        "CASE_NUMBER": case_number, "OPENED_DATE": opened_ms, "DISTRICT": "Raleigh",
        "CASE_STATUS": status, "CASE_TYPE": case_type, "DESCRIPTION": description,
        "STREET_ADDRESS": street, "CITY_STATE_ZIP": city_zip,
    }


def test_vacant_lot_tow_truck_complaint_is_not_vacant_structure_evidence():
    """The real live false positive (VIO-008568-2026): 'vacant lot' land-use text must not
    tag 'vacant' at all -- not severity, not distressed, not the new vacancy mirror."""
    tags = classify("VIO - Planning/Zoning",
                     "Use of vacant lot to park and store commercial tow trucks.")
    assert tags is None  # no other structural category matches either -> not distress at all
    li = to_listing(_attrs("VIO - Planning/Zoning",
                           "Use of vacant lot to park and store commercial tow trucks."),
                     now=NOW)
    assert li is None


def test_abandoned_and_boarded_structure_sets_vacancy_and_gis_vacant():
    li = to_listing(_attrs("VIO - Planning/Zoning",
                           "Property is vacant and abandoned, boarded windows."),
                     now=NOW)
    assert li is not None
    assert li.raw["vacancy"] == {
        "vacant": True, "boarded_up": None, "utility_status": None,
        "source": "counties_nc.wake_code_cases",
    }
    assert li.raw["gis"]["vacant"] is True
    assert li.raw["distressed"] is True
    assert "condemned" not in li.raw   # vacant/abandoned is not a condemnation claim


def test_bare_vacant_structure_text_still_matches():
    """The negative lookahead excludes 'vacant lot/land/parcel' specifically, not 'vacant' in
    general -- a genuine vacant-structure description must still tag and mirror."""
    tags = classify("VIO - Building Inspections", "Vacant structure with open access, unsecured.")
    assert tags and "vacant" in tags
    li = to_listing(_attrs("VIO - Building Inspections",
                           "Vacant structure with open access, unsecured."), now=NOW)
    assert li.raw["vacancy"]["vacant"] is True
    assert li.raw["gis"]["vacant"] is True


def test_dilapidated_text_alone_does_not_set_vacancy_or_condemned():
    """'Dilapidated'/'condemn'-family text (deteriorat/condemn/uninhabit/unfit) is severe, but
    is a DIFFERENT, broader tag than 'vacant' -- it must not fall through into the vacancy
    mirror (same discipline as lincoln_code_violations.py's own Abandoned-structure-only scope,
    and as durham_unsafe_building's narrower Topic-based split elsewhere in this same pass)."""
    li = to_listing(_attrs("VIO - Building Inspections", "Structure is dilapidated and unfit."),
                     now=NOW)
    assert li is not None
    assert li.raw["code_enforcement"]["severe"] is True
    assert "vacancy" not in li.raw
    assert "gis" not in li.raw
    assert "condemned" not in li.raw


def test_closed_case_is_dropped():
    li = to_listing(_attrs("VIO - Building Inspections", "Vacant and abandoned structure.",
                           status="Closed - Resolved"), now=NOW)
    assert li is None
