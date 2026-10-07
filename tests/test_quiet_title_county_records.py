"""quiet_title.county_records: the per-county 'where to look' block, read from the county records
matrix. Fixture records are made up; one test reads the repo's own matrix to check every NC county
name the adapters use has a record. No network."""
import json
from datetime import date, datetime, timezone

import pytest

from foreclosure_scraper.quiet_title import county_records
from foreclosure_scraper.quiet_title.adapters.nc_onemap import NC_COUNTIES
from foreclosure_scraper.quiet_title.county_records import county_key, county_record, where_to_look


def rec(county, **rod):
    base = {"platform": "Example platform", "url": f"https://{county}.example.invalid/rod", "free_name_search": "yes",
            "access": "open", "index_online_back_to_year": None, "images_free": "yes",
            "legal_description_in_index": "yes", "plat_books_or_maps_online": "unknown",
            "terms_forbid_automation": "no", "how_verified": "made up", "notes": ""}
    base.update(rod)
    return {"county": county, "state": "NC", "rod": base,
            "probate": {"system": "statewide eCourts", "url": "https://courts.example.invalid/", "free_search": "yes",
                        "access": "captcha", "notes": ""},
            "tax": {"url": f"https://{county}.example.invalid/tax", "free_by_parcel": "yes",
                    "shows_bill_history": "unknown", "access": "blocked", "notes": "Cloudflare page to scripts."},
            "gis": {"url": None, "notes": "", "legal_description_field": "no", "deed_book_page_field": "yes",
                    "owner_field": "yes"},
            "we_already_read": {}, "manual_lane": "", "confidence": "medium"}


@pytest.fixture()
def matrix(tmp_path, monkeypatch):
    data = {"generated": "2026-10-07", "counties": [
        rec("alpha", access="captcha", index_online_back_to_year=1966, images_free="no"),
        rec("Beta", access="blocked", terms_forbid_automation="yes", notes="Books before 1950 are not imaged."),
        rec("new-gamma", access="open", plat_books_or_maps_online="yes", index_online_back_to_year="1871"),
    ]}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(data))
    monkeypatch.setattr(county_records, "MATRIX_PATH", p)
    return p


def test_county_key():
    assert county_key("New Hanover County") == county_key("new-hanover") == "new hanover"
    assert county_key("McDowell") == "mcdowell"


def test_captcha_register_with_paid_images(matrix):
    w = where_to_look("Alpha", "NC")
    assert w.found and w.rod_url == "https://alpha.example.invalid/rod" and w.rod_back_to == 1966
    assert w.rod_script_ok is False
    assert w.rod_person_needed.startswith("yes: a CAPTCHA") and "deed images are paid" in w.rod_person_needed
    assert w.probate_person.startswith("yes, a person does it") and "CAPTCHA" in w.probate_person
    assert w.tax_person.startswith("yes:") and "Cloudflare" in w.tax_person
    rows = dict(w.rows)
    assert rows["Online index goes back to"] == "1966"
    assert rows["Index free / images free"] == "index: yes; deed images: no"
    assert rows["Register of deeds portal"].startswith("https://alpha.example.invalid/rod (Example platform)")


def test_blocked_register_and_terms_and_old_book_note(matrix):
    w = where_to_look("beta")
    assert "Cloudflare" in w.rod_person_needed and "terms forbid automated searching" in w.rod_person_needed
    assert "Books before 1950 are not imaged." in dict(w.rows)["Plat books and old books"]
    assert dict(w.rows)["Online index goes back to"] == "not stated by the register"


def test_open_register_and_hyphenated_name(matrix):
    w = where_to_look("New Gamma County")
    assert w.rod_script_ok is True and w.rod_person_needed == "no for the index and images"
    assert w.rod_back_to == 1871


def test_county_missing_from_the_matrix_still_gets_a_block(matrix):
    w = where_to_look("Nowhere")
    assert not w.found and "No entry for Nowhere County" in w.rows[0][1]


def test_every_nc_county_the_adapters_name_has_a_matrix_record():
    missing = [c for c in NC_COUNTIES if county_record(c, "NC", county_records.MATRIX_PATH.parent /
                                                        "county_records_matrix.json") is None]
    assert missing == [] and len(NC_COUNTIES) == 100


def test_the_sheet_prints_the_block(matrix, tmp_path):
    from foreclosure_scraper.quiet_title.fetch import PoliteFetcher
    from foreclosure_scraper.quiet_title.intake import run_intake
    from foreclosure_scraper.quiet_title.model import IntakeResult
    from foreclosure_scraper.quiet_title.render import render_html
    from tests.test_quiet_title_intake import PIN, FakeAdapter

    res = IntakeResult(county="Testshire", state="NC", pin=PIN, started=datetime(2026, 10, 7, tzinfo=timezone.utc))
    run_intake(FakeAdapter(PoliteFetcher(tmp_path), res, "20261007"), PIN, date(2026, 10, 7))
    h = render_html(res)
    assert "Where to look in Testshire County" in h and "No entry for Testshire County" in h
    assert "searched this county's register index live" in h

    class Alpha(FakeAdapter):
        county = "Alpha"
    res2 = IntakeResult(county="Alpha", state="NC", pin=PIN, started=datetime(2026, 10, 7, tzinfo=timezone.utc))
    run_intake(Alpha(PoliteFetcher(tmp_path), res2, "20261007"), PIN, date(2026, 10, 7))
    h2 = render_html(res2)
    assert "https://alpha.example.invalid/rod" in h2 and "a CAPTCHA" in h2 and "deed images are paid" in h2
    assert res2.where["rod_back_to"] == 1966
