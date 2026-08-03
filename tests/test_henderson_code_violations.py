"""Henderson NC open ordinance/code violations (PIN-keyed distress source).

Offline tests run against a SAVED slice of the real Ordinance Violations
Tracking layer (14 verbatim open features, including the tab-prefixed PIN the
county's own data carries and a parcel with two open cases), so the grouping,
PIN normalization, open/closed classification, and repeat-offender counter are
all exercised on real shapes.

RUN_LIVE=1 adds an opt-in smoke test against the live layer.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from foreclosure_scraper import arcgis_webmap as agw
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc import henderson_code_violations as mod

from tests._arcgis_fakes import FakeHttp

FIX = Path(__file__).parent / "fixtures"


def _open_features() -> list[dict]:
    return json.loads((FIX / "henderson_code_violations_open.json").read_text())["features"]


def _http(open_payload=None, history=None) -> FakeHttp:
    """First /query = the open-case pull, second = the case-history pull."""
    pages = [open_payload or json.loads(
        (FIX / "henderson_code_violations_open.json").read_text())]
    pages.append(history if history is not None
                 else {"objectIdFieldName": "OBJECTID", "features": []})
    return FakeHttp({}, pages=pages)


def _run(http=None) -> list:
    s = mod.HendersonCodeViolations()
    original = mod.client
    mod.client = lambda *a, **kw: _ctx(http or _http())      # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        mod.client = original


class _ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


# --------------------------------------------------------------------------- #
# open-case filter
# --------------------------------------------------------------------------- #

def test_open_filter_is_a_negative_list_so_new_statuses_stay_visible():
    """A status the county adds tomorrow must read as OPEN (a lead), not vanish."""
    where = mod._OPEN_WHERE
    assert "NOT LIKE" in where
    assert "%No Further Action%" in where
    assert agw.is_safe_expression(where)
    # A brand-new open status is not excluded by any clause.
    assert not mod.is_closed("Abatement Scheduled")


@pytest.mark.parametrize("status,closed", [
    ("Owner Resolved Issue - No Further Action", True),
    ("County Resolved Issue - No Further Action", True),
    ("Invalid Complaint - No Further Action", True),
    ("Resolved - No Further Action (Old Database Data)", True),
    ("Resolved", True),
    ("Inactive", True),
    ("nfa", True),
    ("Refer to proper Authority", True),
    ("Notice of Violation Issued", False),
    ("15 Day Notice Issued", False),
    ("In Progress - Case Assigned and Staff Reviewing", False),
    ("New Case - Pending Review", False),
    (None, False),
])
def test_is_closed_classification(status, closed):
    assert mod.is_closed(status) is closed


def test_query_uses_the_open_where_and_enumerated_out_fields():
    http = _http()
    _run(http)
    verb, url, params = http.calls[0]
    assert params["where"] == mod._OPEN_WHERE
    assert params["outFields"] != "*"
    assert "PIN" in params["outFields"] and "parcelOwner" in params["outFields"]
    assert params["returnGeometry"] == "true" and params["outSR"] == "4326"


# --------------------------------------------------------------------------- #
# grouping + mapping
# --------------------------------------------------------------------------- #

def test_one_listing_per_property_not_per_complaint():
    feats = _open_features()
    rows = _run()
    pins = {mod._norm_pin(f["attributes"].get("PIN")) for f in feats}
    assert len(feats) > len(pins)          # fixture really does contain a repeat parcel
    assert len(rows) == len(pins)
    multi = next(li for li in rows if li.raw["code_enforcement"]["open_violations"] > 1)
    assert multi.parcel_id


def test_listing_shape():
    li = next(li for li in _run() if li.parcel_id == "9651406313")
    assert li.source == "counties_nc.henderson_code_violations"
    assert li.listing_type is ListingType.UNKNOWN
    assert li.state == "NC" and li.county == "Henderson"
    assert li.defendant == li.owner_name == "Jannette Corn"
    assert "163 Bethea Dr" in li.street_address
    assert li.sale_date is None
    assert 35.0 < li.latitude < 35.8 and -82.8 < li.longitude < -82.2
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["violation_types"] == ["Minimum Housing Complaint"]
    assert ce["open_violations"] == 1
    assert ce["opened"] == "2026-08-03"
    assert ce["source"] == "henderson_ordinance_violations_tracking"


def test_pin_is_the_join_key_onto_the_rest_of_the_board():
    for li in _run():
        if li.parcel_id:
            assert li.dedupe_key() == f"parcel:NC:henderson:{li.parcel_id}"


def test_joins_rather_than_duplicates_a_foreclosure_lead_on_the_same_parcel():
    """204 Gull Ave is on BOTH the tax-foreclosure roster (as TOWERY ... HEIRS)
    and the violation list (as 'Towry, Nettie'). One parcel, one lead."""
    from foreclosure_scraper.scrapers.counties_nc import henderson_foreclosure_parcels as fc

    fc_rows = asyncio.run(fc.fetch_source(FakeHttp({
        "items/e25ea4d18d30427cacb1064168c0dea3/data":
            json.loads((FIX / "henderson_exb_app.json").read_text()),
        "items/7c89c21f8cf6401bbb71560ab9c09ab8/data":
            json.loads((FIX / "henderson_webmap.json").read_text()),
        "/query": json.loads(
            (FIX / "henderson_foreclosure_parcels_query.json").read_text()),
    }), fc._SOURCES[0]))

    tax = next(li for li in fc_rows if li.parcel_id == "9577984987")
    viol = next(li for li in _run() if li.parcel_id == "9577984987")
    assert tax.dedupe_key() == viol.dedupe_key()
    merged = tax.merge(viol)
    assert merged.raw["tax_foreclosure"]                # tax debt
    assert merged.raw["heir_estate"]["match"] == "heirs"  # tangled title
    assert merged.raw["code_enforcement"]["has_open"]     # open violation
    assert merged.street_address                          # address survived


def test_tab_prefixed_pin_is_normalized():
    """The county's own data carries at least one '\\t'-prefixed PIN."""
    feats = _open_features()
    dirty = [f for f in feats if "\t" in (f["attributes"].get("PIN") or "")]
    assert dirty, "fixture must retain the real dirty PIN"
    want = dirty[0]["attributes"]["PIN"].strip()
    assert any(li.parcel_id == want for li in _run())


def test_row_with_neither_pin_nor_address_is_dropped():
    payload = {"objectIdFieldName": "OBJECTID", "features": [
        {"attributes": {"OBJECTID": 1, "caseID": None, "PIN": None, "address": " ",
                        "violationType": " ", "dispositionStatus": None}}]}
    assert _run(_http(open_payload=payload)) == []


def test_newest_case_drives_the_headline_fields():
    feats = [
        {"attributes": {"OBJECTID": 1, "caseID": "100", "PIN": "1234567890",
                        "address": "1 OLD RD", "parcelOwner": "OLD OWNER",
                        "violationType": "Zoning", "dispositionStatus": "Notice of Violation Issued",
                        "dateReceived": 1_600_000_000_000}},
        {"attributes": {"OBJECTID": 2, "caseID": "200", "PIN": "1234567890",
                        "address": "1 NEW RD", "parcelOwner": "NEW OWNER",
                        "violationType": "Nuisance", "dispositionStatus": "15 Day Notice Issued",
                        "dateReceived": 1_770_000_000_000}},
    ]
    li = mod.build_listing(feats)
    assert li.defendant == "NEW OWNER" and li.street_address == "1 NEW RD"
    assert li.case_number == "200"
    # ...but a blank on the newest case falls back to the older one rather than
    # throwing away an address/owner we already have.
    feats[1]["attributes"]["parcelOwner"] = None
    feats[1]["attributes"]["address"] = " "
    li2 = mod.build_listing(feats)
    assert li2.defendant == "OLD OWNER" and li2.street_address == "1 OLD RD"
    assert li2.case_number == "200"      # headline case is still the newest
    assert li.raw["code_enforcement"]["open_violations"] == 2
    assert li.raw["code_enforcement"]["violation_types"] == ["Nuisance", "Zoning"]


# --------------------------------------------------------------------------- #
# history / repeat offender
# --------------------------------------------------------------------------- #

def test_prior_cases_and_repeat_offender_from_history():
    li = mod.build_listing(
        [{"attributes": {"OBJECTID": 1, "caseID": "9", "PIN": "1234567890",
                         "address": "5 MAIN ST", "parcelOwner": "X",
                         "violationType": "Nuisance",
                         "dispositionStatus": "Notice of Violation Issued",
                         "dateReceived": 1_770_000_000_000}}],
        history={"1234567890": {"total": 5, "closed": 4}})
    ce = li.raw["code_enforcement"]
    assert ce["total_violations"] == 5
    assert ce["prior_cases"] == 4
    assert ce["repeat_offender"] is True
    assert "4 prior case(s)" in li.description


def test_history_never_reports_fewer_cases_than_we_can_see():
    li = mod.build_listing(
        [{"attributes": {"OBJECTID": i, "caseID": str(i), "PIN": "1234567890",
                         "address": "5 MAIN ST", "violationType": "Nuisance",
                         "dispositionStatus": "Notice of Violation Issued",
                         "dateReceived": 1_770_000_000_000}} for i in (1, 2, 3)],
        history={"1234567890": {"total": 1, "closed": 0}})   # stale/short index
    ce = li.raw["code_enforcement"]
    assert ce["total_violations"] == 3 and ce["prior_cases"] == 0


def test_history_indexes_on_the_normalized_pin():
    """The tab-prefixed and clean spellings of one PIN are ONE parcel's history."""
    http = FakeHttp({}, pages=[{"objectIdFieldName": "OBJECTID", "features": [
        {"attributes": {"PIN": "\t965120887", "caseID": "1",
                        "dispositionStatus": "Resolved"}},
        {"attributes": {"PIN": "965120887", "caseID": "2",
                        "dispositionStatus": "Owner Resolved Issue - No Further Action"}},
        {"attributes": {"PIN": "965120887", "caseID": "3",
                        "dispositionStatus": "Notice of Violation Issued"}},
    ]}])
    idx = asyncio.run(mod.fetch_history(http, ["\t965120887", "965120887"]))
    assert idx == {"965120887": {"total": 3, "closed": 2}}


def test_history_short_circuits_on_an_empty_pin_list():
    http = FakeHttp({}, pages=[])
    assert asyncio.run(mod.fetch_history(http, [])) == {}
    assert http.calls == []


def test_history_query_sends_raw_pins_and_posts_when_long():
    http = FakeHttp({}, pages=[{"objectIdFieldName": "OBJECTID", "features": []}])
    pins = [f"{i:010d}" for i in range(300)]
    asyncio.run(mod.fetch_history(http, pins))
    verb, url, params = http.calls[0]
    assert verb == "POST"                       # 300 PINs blows past the URL limit
    assert params["where"].startswith("PIN IN (")
    assert params["outFields"] != "*"


def test_history_failure_costs_the_counter_not_the_leads():
    http = FakeHttp({}, pages=[
        json.loads((FIX / "henderson_code_violations_open.json").read_text()),
        {"error": {"code": 400, "message": "boom"}},
    ])
    rows = _run(http)
    assert rows                                  # leads survive
    assert all(li.raw["code_enforcement"]["prior_cases"] >= 0 for li in rows)


# --------------------------------------------------------------------------- #
# severity + scoring + gating
# --------------------------------------------------------------------------- #

def test_severe_types_flag_physical_distress():
    rows = _run()
    junk = next(li for li in rows
                if "Junkyard" in li.raw["code_enforcement"]["violation_types"])
    assert junk.raw["code_enforcement"]["severe"] is True
    assert junk.raw["distressed"] is True


def test_code_enforcement_signal_is_scored():
    from foreclosure_scraper.distress_score import _signals_for
    li = _run()[0]
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" in names


def test_env_gate_skips_without_fetching(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "0")
    http = _http()
    assert _run(http) == []
    assert http.calls == []


def test_query_error_propagates_as_an_exception():
    http = FakeHttp({}, pages=[{"error": {"code": 400, "message": "Invalid field: PIN"}}])
    with pytest.raises(agw.ArcGisError):
        _run(http)


# --------------------------------------------------------------------------- #
# wiring guard (fails until main.py is updated — see the report)
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    """A code violation has no sale_date. Without the whitelist entry,
    main._active_only silently drops every one of them and the source reads 0."""
    from foreclosure_scraper import main
    slug = mod.HendersonCodeViolations.slug
    assert slug in main.DATELESS_OK_SOURCES, (
        f'add "{slug}" to main.DATELESS_OK_SOURCES')


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live():
    s = mod.HendersonCodeViolations()
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(rows) >= s.expected_min_count
    assert all(li.raw["code_enforcement"]["has_open"] for li in rows)
    assert sum(1 for li in rows if li.parcel_id) / len(rows) > 0.95   # PIN-keyed
    assert any(li.raw["code_enforcement"]["repeat_offender"] for li in rows)
    print(f"live henderson open code violations parcels={len(rows)} "
          f"cases={sum(li.raw['code_enforcement']['open_violations'] for li in rows)} "
          f"repeat={sum(1 for li in rows if li.raw['code_enforcement']['repeat_offender'])}")
