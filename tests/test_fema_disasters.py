"""fema_disasters.py was rewritten 2026-09-15: the old HTML page is now
Akamai-walled, so this switched to FEMA's free OpenFEMA v2 REST API, which
gives real per-county data via `designatedArea`."""
from foreclosure_scraper.scrapers.national.fema_disasters import _row_to_listing

_REAL_ROW = {
    "femaDeclarationString": "FM-5582-NC",
    "disasterNumber": 5582,
    "state": "NC",
    "declarationType": "FM",
    "declarationDate": "2025-05-03T00:00:00.000Z",
    "incidentType": "Fire",
    "declarationTitle": "SUNSET DRIVE FIRE",
    "ihProgramDeclared": False,
    "iaProgramDeclared": False,
    "designatedArea": "Brunswick (County)",
}


def test_real_row_parses_county_from_designated_area():
    li = _row_to_listing(_REAL_ROW)
    assert li is not None
    assert li.county == "Brunswick"
    assert li.state == "NC"
    assert li.sale_date is None
    assert "SUNSET DRIVE FIRE" in li.description
    assert li.raw["fema_disaster"]["fema_id"] == "FM-5582-NC"


def test_statewide_designation_passes_through():
    row = {**_REAL_ROW, "designatedArea": "Statewide"}
    li = _row_to_listing(row)
    assert li.county == "Statewide"


def test_blank_designated_area_is_dropped():
    row = {**_REAL_ROW, "designatedArea": ""}
    assert _row_to_listing(row) is None


def test_missing_designated_area_key_is_dropped():
    row = {k: v for k, v in _REAL_ROW.items() if k != "designatedArea"}
    assert _row_to_listing(row) is None
