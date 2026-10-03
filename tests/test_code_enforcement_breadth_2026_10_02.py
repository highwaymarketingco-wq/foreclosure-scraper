"""2026-10-02 code_enforcement/condemned county-breadth investigation.

`arcgis_distress_layers.py`'s `_to_listing()` wrote raw["arcgis_distress"] +
foreclosure_process="code_enforcement" for every layer tagged
process="code_enforcement", but NEVER raw["code_enforcement"] -- the key
distress_score.py's PROPERTY signal and the county-signal coverage tracker
actually read. That meant 5 already-live, already-wired layers
(columbia_code_vacant_boarded, greensboro_code_housing,
durham_open_code_violations, rockhill_code_housing,
rockhill_code_exterior_major) contributed NOTHING to either, despite being
real and current (live-verified counts 2026-10-02: 1,020 / 665 / 1,110 / 17 /
15). These tests pin the bridge, and that it is scoped ONLY to
process="code_enforcement" layers (a tax/flood_damage/etc. layer must never
get a code_enforcement block it has no business claiming).

rockhill_code_demolition (process="demolition_permit", a CODE-ENFORCEMENT-
ordered demolition case on OpenCodeEnforcementCases, NOT a homeowner's own
voluntary teardown-permit application like New Hanover's unrelated
demolition_permits layer) stamps raw["condemned"] instead -- Rock Hill's own
equivalent of Spartanburg's condemned flag.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers as M


def _lay(slug):
    return next(x for x in M.LAYERS if x.slug == slug)


# --------------------------------------------------------------------------
# Layers already pre-filtered to a structurally-severe category (ce_severe_re
# left at its default None) -- severe=True unconditionally.
# --------------------------------------------------------------------------

def test_columbia_code_case_bridges_into_code_enforcement_and_is_severe():
    lay = _lay("columbia_code_vacant_boarded")
    li = M._to_listing({"CaseNum": "26-001", "Problem": "Vacant Building",
                        "ADDRESS": "100 MAIN ST"}, lay)
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["severe"] is True
    assert ce["vacancy_adjacent"] is True
    assert li.raw["distressed"] is True
    assert li.raw["arcgis_distress"]["layer"] == "columbia_code_vacant_boarded"


def test_greensboro_housing_case_bridges_and_is_severe():
    lay = _lay("greensboro_code_housing")
    li = M._to_listing({"CaseNumber": "26-002", "FullAddress": "200 ELM ST"}, lay)
    assert li.raw["code_enforcement"]["severe"] is True
    assert li.raw["distressed"] is True


def test_rockhill_housing_and_exterior_major_bridge_and_are_severe():
    for slug in ("rockhill_code_housing", "rockhill_code_exterior_major"):
        lay = _lay(slug)
        li = M._to_listing({"CaseNumber": "CN-2026001", "Status": "Open",
                            "AddressText": "300 OAK ST"}, lay)
        assert li.raw["code_enforcement"]["severe"] is True, slug


# --------------------------------------------------------------------------
# Durham: unfiltered Topic mix -- ce_severe_re gates severity per-row.
# --------------------------------------------------------------------------

def test_durham_structural_topics_are_severe():
    lay = _lay("durham_open_code_violations")
    for topic in ("Repair Only (<50%)", "Repair or Demolish (>50%)",
                  "Unsafe Building", "B/C Abatement"):
        li = M._to_listing({"CaseNum": "26-0001", "Topic": topic,
                            "AddressNum": "400", "Street": "PINE ST"}, lay)
        ce = li.raw["code_enforcement"]
        assert ce["severe"] is True, topic
        assert ce["vacancy_adjacent"] is True, topic
        assert li.raw["distressed"] is True, topic


def test_durham_yard_nuisance_topics_are_not_severe():
    """Weedy/Junked Lot, Vehicle, Weedy Chronic Violator are yard-nuisance
    categories (the module's own comment calls Greensboro/Rock Hill's
    equivalents "weaker"/"yard-nuisance") -- still shipped (has_open True),
    no PROPERTY credit claimed."""
    lay = _lay("durham_open_code_violations")
    for topic in ("Weedy/Junked Lot", "Vehicle", "Weedy Chronic Violator"):
        li = M._to_listing({"CaseNum": "26-0002", "Topic": topic,
                            "AddressNum": "401", "Street": "PINE ST"}, lay)
        ce = li.raw["code_enforcement"]
        assert ce["has_open"] is True, topic
        assert ce["severe"] is False, topic
        assert ce["vacancy_adjacent"] is False, topic
        assert "distressed" not in li.raw, topic


# --------------------------------------------------------------------------
# rockhill_code_demolition: condemned, not code_enforcement.
# --------------------------------------------------------------------------

def test_rockhill_demolition_stamps_condemned_not_code_enforcement():
    lay = _lay("rockhill_code_demolition")
    assert lay.process == "demolition_permit"
    li = M._to_listing({"CaseNumber": "CN-2026009", "Status": "Open",
                        "AddressText": "500 BIRCH ST"}, lay)
    assert li.raw["condemned"] is True
    assert "code_enforcement" not in li.raw


def test_new_hanover_demolition_permits_does_not_get_condemned():
    """New Hanover's demolition_permits layer is a building-PERMIT application
    record (a homeowner's own voluntary teardown), not a code-enforcement-
    ordered demolition case -- must NOT be swept into raw['condemned'] by a
    blanket process=="demolition_permit" rule. Only the rockhill_code_
    demolition SLUG is special-cased."""
    lay = _lay("new_hanover_demolition_permits")
    assert lay.process == "demolition_permit"
    li = M._to_listing({"PID": "R12345", "PERMIT_STATUS": "Issued",
                        "NUMBER": "600", "STREET": "CEDAR ST"}, lay)
    assert li is not None
    assert "condemned" not in li.raw


# --------------------------------------------------------------------------
# Regression guard: a non-code_enforcement layer must never get either key.
# --------------------------------------------------------------------------

def test_tax_layer_never_gets_a_code_enforcement_or_condemned_block():
    lay = _lay("buncombe_unpaid_bills")
    assert lay.process == "tax"
    li = M._to_listing({
        "bill": "0003018081-2025-2025-0000-00", "pin": "9686-54-0826-00000",
        "owner1_last_name": "ROBINSON", "house_num": "42",
        "street_name": "DODE WHITAKER RD", "real_value": 374100.0,
    }, lay)
    assert "code_enforcement" not in li.raw
    assert "condemned" not in li.raw
    assert "distressed" not in li.raw
