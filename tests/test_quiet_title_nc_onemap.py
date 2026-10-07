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


# ---- Polk: the statewide parcel record plus the county's open Cott register ----------------------

def _grid(rows):
    tr = ""
    for i, (d, idx, kind, gr, ge, bp, pages) in enumerate(rows, 1):
        tr += (f"<tr><td>{i}</td><td>{d}</td><td>{idx}</td><td>{kind}</td>"
               f"<td><div><table><tr><td>{gr}</td></tr></table></div></td>"
               f"<td><div><table><tr><td><b>{ge}</b></td></tr></table></div></td><td>LOT 3 EXAMPLE</td><td></td>"
               f"<td><a href='javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions(\"ctl00$g$ctl0{i}$lbBP\", \"\", true))'>{bp}</a></td>"
               f"<td></td><td>{pages}</td><td></td><td></td></tr>")
    n = len(rows)
    return (f"<html><body><span>{'1 - ' + str(n) + ' of ' + str(n) if n else ''}</span><table id='x_cpgvInstruments'>{tr}</table>"
            f"<input type='hidden' name='__VIEWSTATE' value=''/></body></html>")


class _PolkSession:
    def __init__(self, onemap):
        self.onemap, self.calls = onemap, []

    def request(self, method, url, params=None, data=None, timeout=None):
        self.calls.append((method, url, dict(params or {}), dict(data or {})))
        if "nconemap" in url:
            return _Resp(url, self.onemap)
        if "SrchBookPage" in url and method == "GET":
            body = _grid([("05/05/2020", "CRP", "DEED OF TRUST", "BUYER, BOB", "LENDER INC", "448 / 1232", "9"),
                          ("05/05/2020", "CRP", "DEED", "SELLER, SAM", "BUYER, BOB", "448 / 1232", "3")])
        elif "SrchBookPage" in url:
            body = "<html><body><table id='ctl00_cphMain_gvParties1'><tr><td>SELLER, SAM</td></tr></table></body></html>"
        elif method == "GET":
            body = "<html><body><form><input type='hidden' name='__VIEWSTATE' value=''/></form></body></html>"
        else:
            body = _grid([])
        r = _Resp(url, {})
        r.text, r.content, r.url = body, body.encode(), url
        return r


def test_polk_reads_its_register_picks_the_deed_by_year_and_has_no_deaths_index(tmp_path, matrix):
    cls = adapter_class("Polk", "NC")
    assert cls.__name__ == "PolkAdapter" and cls.register_fetched is True and cls.deaths_index is False
    attrs = dict(ATTRS, parno="P00-11", altparno="", sourceref="Deed Book/Page 448/1232", sourcedatx="2020",
                 legdecfull="", mailadd="PO BOX 1", ownname="BUYER BOB", ownname2="")
    ses = _PolkSession(_body(attrs))
    f = PoliteFetcher(tmp_path, session_factory=lambda: ses, sleep=lambda s: None)
    res = IntakeResult(county="Polk", state="NC", pin="P0011", started=datetime(2026, 10, 7, tzinfo=timezone.utc))
    run_intake(cls(f, res, "20261007"), "P0011", date(2026, 10, 7))
    assert res.parcel.found and (res.parcel.deed_book, res.parcel.deed_page, res.parcel.deed_date) == ("448", "1232", "2020")
    assert res.vesting is not None and res.vesting.kind == "DEED" and res.vesting.grantees == ["BUYER, BOB"]
    assert "the year only" in res.vesting_note and "the deed among the entries" in res.vesting_note
    assert res.deed_link.startswith("https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/SrchBookPage.aspx")
    assert res.searches, "the chain was searched"
    assert res.death_searches == [] and "no deaths index" in res.deaths_note
    posted = [c[3] for c in ses.calls if c[0] == "POST" and "SrchName" in c[1]]
    assert posted and all(d.get("ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$ddlIndexType") != "DTH" for d in posted)
    st = {r.record: r.status for r in res.records}
    assert st["Register of Deeds deaths index"] == "not run" and st["Tax records (county tax bills)"] == "not run"
    h = render_html(res)
    assert "Legal description: needs the deed image" in h and "no deaths index online" in h
    assert "searched this county's register index live" in h


def test_owner_names_with_a_comma_or_on_an_assessor_roll_are_read_surname_first():
    from foreclosure_scraper.quiet_title.intake import owner_people
    a = owner_people("TESTER, ANNA M HEIRS", [], [], "first_last")
    assert a[0]["person"].last == "TESTER" and a[0]["person"].given == ["ANNA", "M"]
    assert "comma after the surname" in a[0]["reading"]
    b = owner_people("TESTER ANNA MARIE ESTATE", [], [], "last_first")
    assert b[0]["person"].last == "TESTER" and "assessor's roll" in b[0]["reading"]
    c = owner_people("ANNA MARIE TESTER (HEIRS)", [], [], "first_last")      # Buncombe's own layer
    assert c[0]["person"].last == "TESTER"


def test_care_of_inside_the_owner_field_is_split_out():
    from foreclosure_scraper.quiet_title.adapters.nc_onemap import split_care_of
    assert split_care_of("TESTER ANNA HEIRS & C/O JOHN SAMPLE") == ("TESTER ANNA HEIRS", "JOHN SAMPLE")
    assert split_care_of("TESTER ANNA") == ("TESTER ANNA", None)
    p = parcel_from_onemap("1", dict(ATTRS, ownname="TESTER ANNA HEIRS & C/O JOHN SAMPLE", ownname2=""), [])
    assert p.owner == "TESTER ANNA HEIRS" and p.care_of == "JOHN SAMPLE"


def test_polk_grid_layout_reads_pages_from_the_images_column():
    from foreclosure_scraper.quiet_title.adapters.cott_v4 import parse_rod_grid
    html = ("<table id='x_cpgvInstruments'><tr><th></th><th>Date Filed</th><th>Index</th><th>Kind</th><th>Grantor</th>"
            "<th>Grantee</th><th>Description (Not Warranted)</th><th>File Number</th><th>Book/Page</th><th>Ref</th>"
            "<th>Amount</th><th>Images</th><th></th></tr>"
            "<tr><td>1</td><td>05/05/2020</td><td>CRP</td><td>DEED</td><td>SELLER, SAM</td><td>BUYER, BOB</td>"
            "<td>LOT 3</td><td>1</td><td><a>448 / 1232</a></td><td></td><td>$250</td><td>3</td><td></td></tr>"
            "<tr><td>2</td><td></td><td>REL</td><td></td><td></td><td></td><td></td><td></td><td><a>198 / 520</a></td>"
            "<td></td><td></td><td>1</td><td></td></tr></table>")
    g = parse_rod_grid(html)
    assert [(r.book, r.page, r.pages) for r in g["rows"]] == [("448", "1232", 3), ("198", "520", 1)]
    assert g["rows"][1].date_iso is None and g["rows"][1].index_code == "REL"


def test_acreage_prefers_the_recorded_area_and_ignores_a_unit_error():
    p = parcel_from_onemap("1", dict(ATTRS, gisacres=1.63e-05, recareano=0.71, recareatx=""), [])
    assert p.acreage == 0.71 and "unit error" in p.extra["acreage_note"]
    q = parcel_from_onemap("1", dict(ATTRS, gisacres=0.68, recareano=0.0, recareatx=""), [])
    assert q.acreage == 0.68


def test_plat_written_inside_the_short_legal():
    p = parcel_from_onemap("1", dict(ATTRS, mapref="", legdecfull="EXAMPLE HEIGHTS LO:19 PL:0037-0023"), [])
    assert (p.plat_book, p.plat_page) == ("37", "23") and p.extra["plat_from_legal"]
    q = parcel_from_onemap("1", ATTRS, [])
    assert (q.plat_book, q.plat_page) == ("12", "34") and "plat_from_legal" not in q.extra


def test_the_same_care_of_in_both_owner_fields_is_shown_once():
    p = parcel_from_onemap("1", dict(ATTRS, ownname="TESTER ANNA HEIRS & C/O JOHN SAMPLE",
                                     ownname2="C/O JOHN SAMPLE"), [])
    assert p.care_of == "JOHN SAMPLE" and p.owner == "TESTER ANNA HEIRS"
