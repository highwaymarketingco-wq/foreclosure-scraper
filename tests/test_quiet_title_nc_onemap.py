"""quiet_title NcOneMapAdapter (the NC OneMap statewide parcel layer) on hand-written fixtures shaped
like the layer's JSON: made-up names, PINs and numbers, no fetched content. No network."""
import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from foreclosure_scraper.quiet_title import county_records
from foreclosure_scraper.quiet_title.adapters import adapter_class
from foreclosure_scraper.quiet_title.adapters.nc_onemap import (OUT_FIELDS, NcOneMapAdapter, canonical_county,
                                                                layer_date, legal_as_deed_ref, like_pattern,
                                                                parcel_from_onemap, parcel_where, parse_ref,
                                                                pick_feature, pin_key, pin_variants)
from foreclosure_scraper.quiet_title.fetch import PoliteFetcher
from foreclosure_scraper.quiet_title.intake import run_intake
from foreclosure_scraper.quiet_title.model import IntakeResult
from foreclosure_scraper.quiet_title.render import render_html

ATTRS = {
    "parno": "0000-11-2222", "altparno": "99887766", "nparno": "37000_0000-11-2222", "cntyname": "Testcounty",
    "ownname": "TESTER ANNA MARIE HEIRS", "ownname2": "SAMPLE JOHN", "mailadd": "12 EXAMPLE RIDGE RD", "munit": "",
    "mcity": "NOWHERE", "mstate": "NC", "mzip": "28000", "siteadd": "99999 EXAMPLE  RIDGE RD", "sunit": "",
    "scity": "", "saddno": "99999 ", "saddstname": " EXAMPLE RIDGE  RD", "gisacres": 0.0, "recareano": 1.5,
    "recareatx": "1.50", "parval": 52000.0, "landval": 20000.0, "improvval": 32000.0, "parvaltype": "Assessed",
    "presentval": "", "saledatetx": "", "legdecfull": "LOT 7 EXAMPLE ACRES SEC B", "sourceref":
    "Deed Book/Page 000123/00045", "sourcedatx": "03/04/1979", "subdivisio": "EXAMPLE ACRES",
    "mapref": "Plat Book/Page 0012/0034", "revdatetx": "20260507", "sourceagnt": "Testcounty County Assessor",
    "struct": "N", "structyear": 0, "parusedesc": "VACANT", "owntype": "",
}

MATRIX = {"generated": "2026-10-07", "counties": [{
    "county": "henderson", "state": "NC",
    "rod": {"platform": "Example deeds platform", "url": "https://rod.example.invalid/search",
            "free_name_search": "yes", "access": "disclaimer_click", "index_online_back_to_year": 1966,
            "images_free": "yes", "legal_description_in_index": "yes", "plat_books_or_maps_online": "yes",
            "terms_forbid_automation": "no", "how_verified": "made up", "notes": "Older books are not imaged."},
    "probate": {"system": "statewide eCourts", "url": "https://courts.example.invalid/", "free_search": "yes",
                "access": "captcha", "notes": "made up"},
    "tax": {"url": "https://tax.example.invalid/", "free_by_parcel": "yes", "shows_bill_history": "unknown",
            "access": "open", "notes": ""},
    "gis": {"url": None, "notes": "", "legal_description_field": "yes", "deed_book_page_field": "yes",
            "owner_field": "yes"},
    "we_already_read": {}, "manual_lane": "A person reads the deed image for the full legal.", "confidence": "high"}]}


@pytest.fixture()
def matrix(tmp_path, monkeypatch):
    p = tmp_path / "matrix.json"
    p.write_text(json.dumps(MATRIX))
    monkeypatch.setattr(county_records, "MATRIX_PATH", p)
    return p


def test_pin_join_helpers():
    assert pin_key("0438-49-3494") == "0438493494" and pin_key("r05618-001-070-000") == "R05618001070000"
    assert pin_variants("0438493494") == ["0438493494", "0438-49-3494"]
    v = pin_variants("8586223397000")
    assert "8586-22-3397-000" in v and "8586-22-3397.000" in v and "8586223397" in v
    assert pin_variants("R05618001070000") == ["R05618001070000"]
    assert pin_variants("1234'; DROP") == ["1234DROP"]           # nothing but letters, digits, - and .
    assert like_pattern("04-38") == "0%4%3%8"
    w = parcel_where("New Hanover", "R05618001070000")
    assert w.startswith("cntyname='New Hanover' AND (") and "altparno LIKE 'R%0%5" in w and "parno IN (" in w


def test_pick_feature_joins_on_parno_then_altparno():
    a = {"parno": "0000-11-2222", "altparno": "1"}
    b = {"parno": "7777", "altparno": "R00001-002-003-000"}
    c = {"parno": "0000-11-22229", "altparno": ""}
    assert pick_feature("0000112222", [c, a])[0] is a
    hit, note = pick_feature("R00001002003000", [b])
    assert hit is b and "altparno" in note
    assert pick_feature("0000112222", [c])[0] is None
    assert "no record" in pick_feature("1", [])[1]


@pytest.mark.parametrize("text,want", [
    ("Deed Book/Page 000246/00588", ("Deed", "246", "588")),
    ("Sale Book/Page 005832/001727", ("Sale", "5832", "1727")),
    ("Deed Book/Page 008311", ("Deed", "8311", None)),
    ("Plat Book-Page 194-57", ("Plat", "194", "57")),
    ("Plat Book/Page B/128A", ("Plat", "B", "128A")),
    ("Plat Book/Page /", ("Plat", None, None)),
    ("Plat Book/Page 00000/00000", ("Plat", None, None)),
    ("", (None, None, None)),
])
def test_parse_ref(text, want):
    assert parse_ref(text) == want


def test_legal_field_holding_a_deed_reference():
    assert legal_as_deed_ref("BK 2072 PG 2122 YR 22 ST 300.00") == ("2072", "2122", "22")
    assert legal_as_deed_ref("1097/0502 1993      0.00") == ("1097", "502", "1993")
    assert legal_as_deed_ref("LOT 7 EXAMPLE ACRES SEC B") is None
    assert legal_as_deed_ref("12/13 INT IN TRACT 4") is None


@pytest.mark.parametrize("text,want", [("07/05/1989", "1989-07-05"), ("20260507", "2026-05-07"),
                                       ("2024-07-03 19:49:45.", "2024-07-03"), ("202508", "2025-08"),
                                       ("2006", "2006"), ("", None), ("00000000", None)])
def test_layer_date(text, want):
    assert layer_date(text) == want


def test_parcel_record_from_layer_attributes():
    p = parcel_from_onemap("0000112222", ATTRS, list(OUT_FIELDS))
    assert p.pin == "0000-11-2222" and p.found
    assert p.owner == "TESTER ANNA MARIE HEIRS; SAMPLE JOHN"
    assert p.mailing == "12 EXAMPLE RIDGE RD, NOWHERE NC 28000"
    assert (p.mailing_house_number, p.mailing_street) == ("12", "EXAMPLE RIDGE")
    assert p.situs == "EXAMPLE RIDGE RD" and p.situs_house_number is None and "99999" in p.situs_note
    assert p.situs_street == "EXAMPLE RIDGE"
    assert p.acreage == 1.5 and "recorded area" in p.extra["acreage_note"]
    assert (p.tax_value, p.land_value, p.building_value) == (52000.0, 20000.0, 32000.0)
    assert "not a market price" in p.value_note and "Assessed" in p.value_note
    assert (p.deed_book, p.deed_page, p.deed_date) == ("123", "45", "1979-03-04")
    assert p.deed_ref_text == "Deed Book/Page 000123/00045"
    assert (p.plat_book, p.plat_page) == ("12", "34")
    assert p.legal_kind == "assessor_short" and p.legal_field == "legdecfull"
    assert p.legal_description == "LOT 7 EXAMPLE ACRES SEC B"
    assert p.layer_updated == "2026-05-07" and p.improved == "N"


def test_caldwell_style_legal_is_read_as_the_deed_reference_not_a_legal():
    a = dict(ATTRS, sourceref="", sourcedatx="", legdecfull="BK 2072 PG 2122 YR 22 ST 300.00")
    p = parcel_from_onemap("0000112222", a, [])
    assert p.legal_description is None and p.legal_kind is None
    assert (p.deed_book, p.deed_page) == ("2072", "2122")
    assert p.extra["legdecfull_holds_deed_ref"].startswith("BK 2072")


def test_adapter_registry_falls_back_to_the_statewide_layer():
    cls = adapter_class("Henderson", "NC")
    assert issubclass(cls, NcOneMapAdapter) and cls.county == "Henderson" and cls.register_fetched is False
    assert adapter_class("new-hanover").county == "New Hanover"
    assert canonical_county("MCDOWELL COUNTY") == "McDowell"
    with pytest.raises(SystemExit):
        adapter_class("Henderson", "SC")


class _Resp:
    def __init__(self, url, body):
        self.status_code, self.url, self.text = 200, url, json.dumps(body)
        self.content = self.text.encode()


class _Session:
    def __init__(self, body):
        self.body, self.calls = body, []

    def request(self, method, url, params=None, data=None, timeout=None):
        self.calls.append((method, url, dict(params or {})))
        return _Resp(url + "?x", self.body)


def _body(*attrs, extra_field=None):
    names = list(OUT_FIELDS) + ([extra_field] if extra_field else [])
    return {"fields": [{"name": n} for n in names], "features": [{"attributes": a} for a in attrs]}


def _run(tmp_path, body, pin="0000112222"):
    ses = _Session(body)
    f = PoliteFetcher(tmp_path, session_factory=lambda: ses, sleep=lambda s: None)
    cls = NcOneMapAdapter.for_county("Henderson")
    res = IntakeResult(county=cls.county, state="NC", pin=pin, started=datetime(2026, 10, 7, 16, tzinfo=timezone.utc))
    ad = cls(f, res, "20261007")
    run_intake(ad, pin, date(2026, 10, 7))
    return res, ses


def test_mailing_number_on_the_same_road_is_checked_with_a_second_request(tmp_path, matrix):
    res, ses = _run(tmp_path, _body(ATTRS))
    assert len(ses.calls) == 2
    assert ses.calls[1][2]["where"] == "cntyname='Henderson' AND siteadd LIKE '12 %EXAMPLE RIDGE%'"
    assert "house number 12 on EXAMPLE RIDGE" in res.mailing_check_note


def test_one_request_explicit_fields_and_the_sheet_says_what_was_not_fetched(tmp_path, matrix):
    res, ses = _run(tmp_path, _body(dict(ATTRS, mailadd="PO BOX 12")))
    assert len(ses.calls) == 1
    params = ses.calls[0][2]
    assert params["outFields"] == ",".join(OUT_FIELDS) and "*" not in params["outFields"]
    assert params["where"].startswith("cntyname='Henderson' AND (")
    assert res.parcel.found and res.register_fetched is False
    assert res.register_link == "https://rod.example.invalid/search"
    assert "Not fetched by the tool: use the link above" in res.chain_note
    assert "book 123 page 45" in res.vesting_note and res.searches == [] and res.death_searches == []
    assert res.tax.fetched is False and "https://tax.example.invalid/" in res.tax.note
    st = {r.record: r.status for r in res.records}
    assert st["Parcel record (NC OneMap statewide parcel layer)"] == "checked"
    assert st["Register of Deeds deaths index"] == "not run"
    assert st["Probate and estate files (Clerk of Superior Court, Estates)"] == "walled"
    h = render_html(res)
    assert "Short assessor legal (not the deed&#x27;s full legal description)" in h
    assert "full text of the legal description is on the deed image" in h
    assert "https://rod.example.invalid/search" in h
    assert "Not fetched by the tool: use the link above" in h
    assert "not a market price" in h
    # the person's link to the same query opens the layer's own HTML query page
    person = urlsplit(res.exhibits[res.parcel.exhibit].url)
    assert person.path.endswith("/FeatureServer/1/query") and parse_qs(person.query)["f"] == ["html"]


def test_identifier_columns_are_dropped_and_not_saved(tmp_path, matrix):
    leaky = dict(ATTRS, TCSSN1="000-00-0000")
    res, _ = _run(tmp_path, _body(leaky, extra_field="TCSSN1"))
    assert res.parcel.found
    ex = res.exhibits[res.parcel.exhibit]
    saved = (tmp_path / "exhibits" / ex.files[0]).read_text()
    assert "TCSSN1" not in saved and "000-00-0000" not in saved
    assert "TCSSN1" not in res.parcel.field_names


def test_no_record_for_the_pin(tmp_path, matrix):
    res, _ = _run(tmp_path, _body(dict(ATTRS, parno="5555-55-5555", altparno="")))
    assert res.parcel.found is False
    assert "none has a parcel number equal" in res.parcel.extra["join_note"]
    assert "No parcel record was found" in render_html(res)
