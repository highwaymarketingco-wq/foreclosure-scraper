"""Lincoln County NC open code violations.

2026-10-02 county-breadth investigation (code_enforcement column, 2/148):
this scraper has real, live, open-case data (63 properties / 66 cases as of
the 2026-09-15 build) but had NEVER written raw['code_enforcement'] -- only
its own 'lincoln_code' key -- so distress_score.py's code_enforcement PROPERTY
signal and the county-signal coverage tracker (both of which read
raw['code_enforcement'] specifically) never saw any of it. These tests pin
the bridge: build_listing() must write BOTH keys, and must classify severity
off VIOLATEDESC (VIOLATETYPE is confirmed dead -- NULL on every row, live-
verified 2026-10-02) the same conservative way henderson_code_violations.py
does for its own county: a case ships either way (has_open always True), but
only a physical-deterioration/dumping category earns PROPERTY credit
(vacancy_adjacent=True), never a paperwork/cosmetic one.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.scrapers.counties_nc.lincoln_code_violations import build_listing

NOW = datetime(2026, 10, 2, 12, 0, 0)


def _feat(violation_id, desc, status="Open", submitdt=1_700_000_000_000,
          addr="123 MAIN ST", name="SMITH JOHN", pin=None):
    return {
        "attributes": {
            "VIOLATIONID": violation_id,
            "FULLADDR": addr,
            "LOCDESC": None,
            "VIOLATETYPE": None,     # confirmed dead field, live-verified 2026-10-02
            "VIOLATEDESC": desc,
            "CODE": None,
            "SUBMITDT": submitdt,
            "NAME": name,
            "PHONE": None,
            "EMAIL": None,
            "STATUS": status,
        },
        "geometry": {"x": -81.24, "y": 35.47},
    }


def test_severe_category_earns_code_enforcement_vacancy_adjacent_credit():
    li = build_listing([_feat("V-1", "Solid waste")], now=NOW)
    assert li is not None
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["severe"] is True
    assert ce["vacancy_adjacent"] is True
    assert ce["open_violations"] == 1
    assert li.raw["distressed"] is True
    # The original key is kept, not replaced.
    assert li.raw["lincoln_code"]["open_violations"] == 1


def test_junkyard_and_junk_vehicle_and_abandoned_structure_are_severe():
    for desc in ("Junkyard", "Junk vehicles", "Abandoned structure",
                 "Solid waste; Junkyard"):
        li = build_listing([_feat("V-2", desc)], now=NOW)
        assert li.raw["code_enforcement"]["severe"] is True, desc


def test_paperwork_category_does_not_earn_vacancy_adjacent_credit():
    """Sign/Use-violation/Setback/permit-paperwork cases still ship (has_open
    stays True, the case data is real and present) but score no PROPERTY
    credit -- same shape as a Henderson Zoning-only case."""
    for desc in ("Sign", "Use violation", "Setback encroachment",
                 "Accessory structure - No permit", "Commercial vehicles"):
        li = build_listing([_feat("V-3", desc)], now=NOW)
        ce = li.raw["code_enforcement"]
        assert ce["has_open"] is True, desc
        assert ce["severe"] is False, desc
        assert ce["vacancy_adjacent"] is False, desc
        assert "distressed" not in li.raw, desc


def test_multiple_cases_at_one_property_fold_into_one_listing():
    feats = [_feat("V-4", "Solid waste"), _feat("V-5", "Sign")]
    li = build_listing(feats, now=NOW)
    ce = li.raw["code_enforcement"]
    assert ce["open_violations"] == 2
    assert ce["repeat_offender"] is True
    assert ce["severe"] is True  # any severe case in the group is enough
    assert sorted(ce["violation_types"]) == ["Sign", "Solid waste"]


def test_code_enforcement_violations_carry_case_detail():
    li = build_listing([_feat("V-6", "Junkyard", status="Open")], now=NOW)
    v = li.raw["code_enforcement"]["violations"][0]
    assert v["violation"] == "Junkyard"
    assert v["status"] == "Open"
    assert v["case_id"] == "V-6"


def test_no_open_violations_with_a_description_leaves_code_enforcement_not_severe():
    li = build_listing([_feat("V-7", None)], now=NOW)
    ce = li.raw["code_enforcement"]
    assert ce["violation_types"] == []
    assert ce["severe"] is False
