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
    assert ce["vacancy_adjacent"] is True
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
    assert ce["vacancy_adjacent"] is False
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


# --------------------------------------------------------------------------- #
# vacancy_adjacent gating (2026-10-03 fix, mirrors henderson_code_violations.py
# commit 19d3888e) -- this feed's own ApplicationTypeDescription vocabulary is
# NOT Henderson's ArcGIS violationType domain, so it was independently live-
# verified: full-city crawl 2026-10-03, 3,304 open cases / 1,493 properties
# with >=1 open case. Under the OLD _SEVERE_RE (pre-fix), 729/1,493 (48.8%)
# were non-severe; the live case-Description sample additionally moved
# Abandoned Vehicle onto _SEVERE (genuine junk/debris, 3/3 sampled), landing
# the final split at 719/1,493 (48.2%) non-vacancy-adjacent -- essentially the
# same scale of over-crediting Henderson had (53.1%).
# --------------------------------------------------------------------------- #

#: Real case (captured live 2026-10-03): genuine junk/debris, same concept as
#: Junk Vehicles under a different label. AKPAR/MapPoint are not the verbatim
#: captured values (not recorded at sample time) but the category, reference
#: number, address, and status are real.
ABANDONED_VEHICLE_OPEN = {
    "ApplicationTypeDescription": "Abandoned Vehicle",
    "LinkText": "CEABDV20262402:Abandoned Vehicle",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEABDV20262402",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "102925"},
    "MapPoint": {"X": -9037000.0, "Y": 4198000.0, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "512 OLIVER ST, GASTONIA, NC 28052",
    "ReferenceNumber": "CEABDV20262402",
    "Status": "Open",
}

#: Constructed-but-realistic (not a verbatim capture): Zoning/Land Use is a
#: real, common open-case category at this feed (299/3,304 open cases live
#: 2026-10-03) -- sampled Historic District/Fence/Building Code cases under
#: this same "paperwork, not property condition" umbrella were confirmed via
#: live detail-page Descriptions; this shape matches the feed's real markers.
ZONING_LAND_USE_OPEN = {
    "ApplicationTypeDescription": "Zoning/Land Use",
    "LinkText": "CEZON20260900:Zoning/Land Use",
    "LinkUri": "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber=CEZON20260900",
    "MapRelationValue": {"LayerName": "Parcels", "AttributeName": "AKPAR", "AttributeValue": "199999"},
    "MapPoint": {"X": -9037500.0, "Y": 4198500.0, "WKID": 3857},
    "Module": "CE",
    "PrimaryLocation": "9 ZONING WAY, GASTONIA, NC 28052",
    "ReferenceNumber": "CEZON20260900",
    "Status": "Notice/Order Sent",
}


def test_abandoned_vehicle_is_severe_and_vacancy_adjacent():
    """Live-sampled 2026-10-03: all 3 real Abandoned Vehicle cases pulled
    described genuine junk/debris left on the property, the same concept as
    Junk Vehicles under a different label."""
    li = mod.build_listing([ABANDONED_VEHICLE_OPEN])
    ce = li.raw["code_enforcement"]
    assert ce["violation_types"] == ["Abandoned Vehicle"]
    assert ce["severe"] is True
    assert ce["vacancy_adjacent"] is True
    assert ce["has_open"] is True
    assert li.raw["distressed"] is True


def test_zoning_land_use_only_case_is_open_but_not_vacancy_adjacent():
    """The live feed's real category vocabulary includes 'Zoning/Land Use'
    (299 of 3,304 open cases, 2026-10-03) -- a land-use/zoning complaint says
    nothing about vacancy or condemnation, same reasoning as Henderson's
    Zoning exclusion."""
    from foreclosure_scraper.distress_score import _signals_for
    from foreclosure_scraper.signal_freshness import code_enforcement_open

    li = mod.build_listing([ZONING_LAND_USE_OPEN])
    ce = li.raw["code_enforcement"]
    assert ce["severe"] is False
    assert ce["vacancy_adjacent"] is False
    assert ce["has_open"] is True                 # still a real, visible open case
    assert "distressed" not in li.raw
    assert code_enforcement_open(ce) is False
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" not in names         # no PROPERTY credit from this alone


def test_vegetation_weeds_only_case_does_not_score_either():
    """Vegetation/Weeds is the single largest open-case category at this feed
    (1,533 of 3,304 open cases live 2026-10-03) and was already excluded from
    _SEVERE before this fix; this pins that it also withholds PROPERTY credit
    via the new vacancy_adjacent gate, not just the severe/distressed label."""
    from foreclosure_scraper.distress_score import _signals_for
    from foreclosure_scraper.signal_freshness import code_enforcement_open

    li = mod.build_listing([DOFFIN_OPEN])
    ce = li.raw["code_enforcement"]
    assert ce["vacancy_adjacent"] is False
    assert code_enforcement_open(ce) is False
    assert "code_enforcement" not in [n for n, _b, _w in _signals_for(li)]


def test_a_severe_case_alongside_a_non_severe_case_still_scores():
    """A property with BOTH an open Public Nuisance case and an open Zoning/
    Land Use case is vacancy-adjacent on the strength of the Nuisance case;
    mixing in a zoning complaint must not suppress real evidence."""
    from foreclosure_scraper.distress_score import _signals_for

    nuisance_same_parcel = dict(PNU_OPEN)
    zoning_same_parcel = dict(ZONING_LAND_USE_OPEN)
    zoning_same_parcel["MapRelationValue"] = nuisance_same_parcel["MapRelationValue"]
    zoning_same_parcel["PrimaryLocation"] = nuisance_same_parcel["PrimaryLocation"]

    li = mod.build_listing([zoning_same_parcel, nuisance_same_parcel])
    ce = li.raw["code_enforcement"]
    assert ce["vacancy_adjacent"] is True
    assert "code_enforcement" in [n for n, _b, _w in _signals_for(li)]


def test_code_enforcement_signal_is_scored_when_vacancy_adjacent():
    from foreclosure_scraper.distress_score import _signals_for
    li = mod.build_listing([PNU_OPEN])
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" in names


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

def test_live():
    """Opt-in live smoke test against the real devsvcs.gastonianc.gov feed.

    Set RUN_LIVE=1 to run. A full crawl takes ~70-90s (recursive quadrant
    splitter over the whole city extent), so this is not run by default.
    """
    import os

    if not os.environ.get("RUN_LIVE"):
        import pytest
        pytest.skip("live smoke; set RUN_LIVE=1")

    import asyncio as _asyncio

    from foreclosure_scraper.distress_score import _signals_for
    from foreclosure_scraper.http_client import client

    async def _crawl():
        async with client(timeout=30.0) as http:
            await http.get(mod.LOCATOR_URL)
            markers = await mod._query_bbox(
                http, mod.CITY_XMIN, mod.CITY_XMAX, mod.CITY_YMIN, mod.CITY_YMAX)
        by_ref = {}
        for m in markers:
            ref = m.get("ReferenceNumber")
            if ref:
                by_ref[ref] = m
        groups: dict = {}
        for m in by_ref.values():
            key = mod._group_key(m)
            if key:
                groups.setdefault(key, []).append(m)
        rows = [li for feats in groups.values()
                if (li := mod.build_listing(feats)) is not None]
        return rows

    rows = _asyncio.run(_crawl())
    assert len(rows) >= mod.GastoniaCodeEnforcement.expected_min_count
    assert all(li.raw["code_enforcement"]["has_open"] for li in rows)
    # 2026-10-03: live categories must include a non-vacancy-adjacent lane
    # (Vegetation/Weeds, Zoning/Land Use, etc.) that the validation flagged --
    # confirms this isn't a severe-only feed by coincidence.
    non_vacancy_adjacent = [li for li in rows
                            if li.raw["code_enforcement"]["vacancy_adjacent"] is False]
    assert non_vacancy_adjacent, "expected at least one open non-vacancy-adjacent property live"
    assert all("code_enforcement" not in [n for n, _b, _w in _signals_for(li)]
               for li in non_vacancy_adjacent)
    print(f"live gastonia open code-enforcement properties={len(rows)} "
          f"not_vacancy_adjacent={len(non_vacancy_adjacent)}")
