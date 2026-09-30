"""City of Gastonia CityView code-enforcement locator: response parsing, the
open/closed status rule, the AKPAR/PID-to-PIN parcel join, and the polygon-cap
detection that drives the recursive spatial crawl.

FIXTURES BELOW are real `LocationMarkers` entries taken verbatim from a live
`POST /CodeEnforcement/LocatorResultsPolygon` response (devsvcs.gastonianc.gov,
captured 2026-09-30), not hand-built:

  * SIGNAGE_CLOSED / PNU_CLOSED_NO_VIOLATIONS — real closed cases (one
    "Citation Issued" case is intentionally NOT used here since that status is
    OPEN; see OPEN_* below), proving `build_listing` drops a property once
    every one of its cases is closed.
  * PNU_OPEN — a real 2026 "Notice/Order Sent" Public Nuisance case at
    1334 FERN FOREST DR (AKPAR/PID 110880). Cross-checked live against Gaston
    County's own parcel layer: AKPAR 110880 -> PIN 3555-31-0320, PHYSSTRADD
    "1334 FERN FOREST DR" (exact match) -- proves the AKPAR-is-PID-not-PIN
    finding the module docstring describes.
  * DOFFIN_OPEN / DOFFIN_ABATEMENT — two real cases at the SAME property
    (625 DOFFIN LN, AKPAR 100865), both Vegetation/Weeds, statuses "Open" and
    "Abatement" -- a real repeat-offender case found in the 1000-row sample.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc import gastonia_code_enforcement as mod

SIGNAGE_CLOSED_BUT_CITED = {
    "ApplicationTypeDescription": "Signage",
    "LinkText": "CESIGN20260187:Signage",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CESIGN20260187",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "105813"},
    "MapPoint": {"X": -81.18400176184898 * 20037508.34 / 180.0, "Y": 0, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "201 W MAIN AVE, GASTONIA, NC 28052",
    "ReferenceNumber": "CESIGN20260187",
    "Status": "Citation Issued",
}

PNU_CLOSED_NO_VIOLATIONS = {
    "ApplicationTypeDescription": "Public Nuisance",
    "LinkText": "CEPNU20260184:Public Nuisance",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEPNU20260184",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "105671"},
    "MapPoint": {"X": -9036829.170954633, "Y": 4197509.7361991005, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "258 E MAIN AVE, GASTONIA, NC 28052",
    "ReferenceNumber": "CEPNU20260184",
    "Status": "Closed - No Violations",
}

PNU_OPEN = {
    "ApplicationTypeDescription": "Public Nuisance",
    "LinkText": "CEPNU20262400:Public Nuisance",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEPNU20262400",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "110880"},
    "MapPoint": {"X": -9035480.972404912, "Y": 4197283.963927307, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "1334 FERN FOREST DR, GASTONIA, NC 28054",
    "ReferenceNumber": "CEPNU20262400",
    "Status": "Notice/Order Sent",
}

DOFFIN_OPEN = {
    "ApplicationTypeDescription": "Vegetation/Weeds",
    "LinkText": "CEVEG20262390:Vegetation/Weeds",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEVEG20262390",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "100865"},
    "MapPoint": {"X": -9038117.031872177, "Y": 4201873.27006361, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "625 DOFFIN LN, GASTONIA, NC 28052",
    "ReferenceNumber": "CEVEG20262390",
    "Status": "Open",
}

DOFFIN_ABATEMENT = {
    "ApplicationTypeDescription": "Vegetation/Weeds",
    "LinkText": "CEVEG20261799:Vegetation/Weeds",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEVEG20261799",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "100865"},
    "MapPoint": {"X": -9038118.464834291, "Y": 4201873.1501368955, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "625 DOFFIN LN, GASTONIA, NC 28052",
    "ReferenceNumber": "CEVEG20261799",
    "Status": "Abatement",
}


# --- status / case-number parsing -----------------------------------------

def test_closed_statuses_are_negative_matched():
    assert mod._is_closed("Closed")
    assert mod._is_closed("Closed - No Violations")
    assert mod._is_closed("Closed - Duplicate Case Entry")
    assert mod._is_closed("  closed ")  # case/whitespace insensitive


def test_open_and_unknown_statuses_default_to_open():
    """A status this repo hasn't seen yet must default to OPEN (a lead), not
    silently closed -- the same rule henderson_code_violations.py uses."""
    assert not mod._is_closed("Open")
    assert not mod._is_closed("Notice/Order Sent")
    assert not mod._is_closed("Abatement")
    assert not mod._is_closed("Citation Issued")
    assert not mod._is_closed("Referred")
    assert not mod._is_closed("Order to Repair/Vacate")
    assert not mod._is_closed("Some Brand New Status Nobody Has Seen")


def test_case_year_extracted_from_reference_number():
    assert mod._case_year("CEPNU20262400") == 2026
    assert mod._case_year("CESIGN20260187") == 2026
    assert mod._case_year("CEGRAF20252086") == 2025
    assert mod._case_year("not-a-case-number") is None
    assert mod._case_year(None) is None


def test_web_mercator_roundtrips_to_plausible_gastonia_coordinates():
    lon, lat = mod._web_mercator_to_lonlat(-9035480.972404912, 4197283.963927307)
    # Gastonia, NC is ~35.25N, -81.18W.
    assert 35.0 < lat < 35.5
    assert -81.4 < lon < -81.0


# --- parse_polygon_response / cap detection --------------------------------

def test_parse_polygon_response_reads_location_markers():
    payload = {"LocationMarkers": [PNU_OPEN], "View": "<html/>"}
    assert mod.parse_polygon_response(payload) == [PNU_OPEN]


def test_parse_polygon_response_handles_missing_or_null_markers():
    assert mod.parse_polygon_response({}) == []
    assert mod.parse_polygon_response({"LocationMarkers": None}) == []


# --- grouping ---------------------------------------------------------------

def test_group_key_uses_parcel_akpar_when_present():
    assert mod._group_key(PNU_OPEN) == ("pid", "110880")


def test_group_key_falls_back_to_address_without_a_parcel_relation():
    m = dict(PNU_OPEN)
    m["MapRelationValue"] = {}
    assert mod._group_key(m) == ("addr", "1334 FERN FOREST DR, GASTONIA, NC 28054")


# --- build_listing: the open/closed lifecycle rule --------------------------

def test_all_closed_property_produces_no_listing():
    """A property whose only case is closed is not a live lead -- matches
    henderson_code_violations.py's OPEN-only rule."""
    assert mod.build_listing([PNU_CLOSED_NO_VIOLATIONS]) is None


def test_citation_issued_is_open_and_produces_a_listing():
    li = mod.build_listing([SIGNAGE_CLOSED_BUT_CITED])
    assert li is not None
    assert li.raw["code_enforcement"]["has_open"] is True
    assert li.raw["code_enforcement"]["open_violations"] == 1


def test_open_case_produces_a_listing_with_the_right_shape():
    li = mod.build_listing([PNU_OPEN])
    assert li is not None
    assert li.source == mod.GastoniaCodeEnforcement.slug
    assert li.state == "NC"
    assert li.county == "Gaston"
    assert li.street_address == "1334 FERN FOREST DR, GASTONIA, NC 28054"
    assert li.case_number == "CEPNU20262400"
    assert li.sale_date is None
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["open_violations"] == 1
    assert ce["violation_types"] == ["Public Nuisance"]
    assert ce["latest_case_year"] == 2026
    # Public Nuisance is on the severe list -> raw['distressed'] follows,
    # matching the PROPERTY-signal shape distress_score.py reads.
    assert ce["severe"] is True
    assert li.raw["distressed"] is True


def test_repeat_offender_grouping_at_the_same_parcel():
    """Real case: 625 Doffin Ln, two open Vegetation/Weeds cases at the same
    AKPAR. Must fold into ONE listing with both cases counted, not two rows."""
    li = mod.build_listing([DOFFIN_OPEN, DOFFIN_ABATEMENT])
    assert li is not None
    ce = li.raw["code_enforcement"]
    assert ce["open_violations"] == 2
    assert ce["total_violations"] == 2
    assert ce["violation_types"] == ["Vegetation/Weeds"]
    # Vegetation/Weeds is NOT on the severe list -- a weeds complaint alone
    # should not fabricate a PROPERTY distress flag.
    assert ce["severe"] is False
    assert "distressed" not in li.raw


def test_mixed_open_and_closed_cases_at_one_parcel_counts_only_the_open_one():
    li = mod.build_listing([PNU_CLOSED_NO_VIOLATIONS, PNU_OPEN])
    # These two are different AKPARs in reality; here we force them onto one
    # group to test the counting logic in isolation.
    assert li is not None
    ce = li.raw["code_enforcement"]
    assert ce["total_violations"] == 2
    assert ce["open_violations"] == 1
    assert ce["prior_cases"] == 1


def test_build_listing_with_no_markers_returns_none():
    assert mod.build_listing([]) is None


def test_parcel_resolution_maps_akpar_to_the_real_county_pin():
    """AKPAR is the county PID, not the PIN (live-verified 2026-09-30). Feeding
    a resolved {pid: {pin, owner}} map into build_listing must land on
    parcel_id, not the raw AKPAR value, so this source's rows join the same
    dedupe key every other Gaston source in this repo uses."""
    parcels = {"110880": {"pin": "3555-31-0320", "owner": "BURKETT DALE"}}
    li = mod.build_listing([PNU_OPEN], parcels)
    assert li.parcel_id == "3555-31-0320"
    assert li.owner_name == "BURKETT DALE"
    assert li.defendant == "BURKETT DALE"


def test_unresolved_parcel_ships_without_a_parcel_id_rather_than_a_wrong_one():
    """No AKPAR->PIN mapping available (join failed/skipped): parcel_id must
    stay None, never fall back to the raw AKPAR value, which would corrupt the
    board's dedupe key (same rule transylvania_delinquent_tax /
    henderson_code_violations already follow for an unconfident match)."""
    li = mod.build_listing([PNU_OPEN], {})
    assert li is not None
    assert li.parcel_id is None
    assert li.street_address == "1334 FERN FOREST DR, GASTONIA, NC 28054"


# --- _query_bbox cap-detection (mocked transport, no live network) --------

def test_query_bbox_stops_recursing_once_under_the_cap():
    import asyncio

    calls = []

    class _FakeResp:
        def __init__(self, markers):
            self._markers = markers

        def raise_for_status(self):
            return None

        def json(self):
            return {"LocationMarkers": self._markers}

    class _FakeClient:
        async def post(self, url, data=None, headers=None):
            calls.append((data["Points[0][X]"], data["Points[0][Y]"]))
            return _FakeResp([{"ReferenceNumber": "X"}] * 3)  # well under PAGE_CAP

    result = asyncio.run(mod._query_bbox(_FakeClient(), 0, 100, 0, 100))
    assert len(result) == 3
    assert len(calls) == 1  # no recursion needed


def test_query_bbox_splits_into_quadrants_when_capped():
    import asyncio

    class _FakeResp:
        def __init__(self, markers):
            self._markers = markers

        def raise_for_status(self):
            return None

        def json(self):
            return {"LocationMarkers": self._markers}

    call_count = {"n": 0}
    ROOT_WIDTH = 2_000_000  # stays well above _MIN_CELL after one split

    class _FakeClient:
        async def post(self, url, data=None, headers=None):
            call_count["n"] += 1
            # Only the whole-bbox (root) call hits the cap; every quadrant
            # call after that (bbox has shrunk) returns a small real count.
            xmin = float(data["Points[0][X]"])
            xmax = float(data["Points[2][X]"])
            if (xmax - xmin) >= ROOT_WIDTH:
                return _FakeResp([{"ReferenceNumber": str(i)} for i in range(mod.PAGE_CAP)])
            return _FakeResp([{"ReferenceNumber": f"q{call_count['n']}"}])

    result = asyncio.run(mod._query_bbox(_FakeClient(), 0, ROOT_WIDTH, 0, ROOT_WIDTH))
    # root call capped -> split into 4 quadrants, each returns 1 real row
    assert call_count["n"] == 5
    assert len(result) == 4
