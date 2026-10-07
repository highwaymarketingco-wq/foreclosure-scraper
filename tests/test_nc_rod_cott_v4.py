"""Cott eSearch v4 guest adapter (rod/nc_cott_v4.py) on hand-written pages shaped like the live
form and results grid (made-up names, books and pages; no fetched content). Covers the parse, an
empty answer, an error page, a blocked page and a guest sign-in page (both walled, never retried),
the lookup cap, the cache, search_by_name and chain end to end, and the registry entries."""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import pytest

from foreclosure_scraper.rod import nc_cott_v4 as cott
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CLOUDFLARE_403, SERVER_ERROR, FakeResp, install

BASE = cott.COUNTIES["Nash"].base
P = cott._P

FORM = f"""<html><head><title>eSearch | Quick Name Search</title>
<script src='https://www.google.com/recaptcha/api.js'></script></head><body>
<form method="post" action="./SrchName.aspx" id="aspnetForm">
<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="" />
<input type="hidden" name="ctl00_cphMain_tcMain_ClientState" value="{{&quot;ActiveTabIndex&quot;:0}}" />
<span id="litCurrentUser">Guest User</span>
<input name="{P}txtFirmSurname" type="text" /><input name="{P}txtGivenName" type="text" />
<input type="submit" name="{P}btnInstruments" value="Search (All Matches)" />
</form></body></html>"""


def _names(*names: str, bold: int | None = None) -> str:
    cells = "".join(f"<tr><td>{'<b>' + n + '</b>' if i == bold else n}</td></tr>" for i, n in enumerate(names))
    return f"<table>{cells}</table>"


def _row(n, date, code, kind, grantors, grantees, desc, fileno, book, page, ref=""):
    return (f'<tr class="cottPagedGridViewRowStyle"><td>{n}</td><td>{date}<br/><span>Date Filed</span></td>'
            f'<td>{code}</td><td>{kind}</td><td>{grantors}</td><td>{grantees}</td><td>{desc}</td>'
            f'<td>{fileno}</td><td><a href="javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions('
            f'&quot;ctl00$cphMain$x{n}&quot;, &quot;&quot;, true))">{book} / {page}</a></td><td>{ref}</td>'
            f'<td>3</td><td></td><td></td><td></td></tr>')


def grid(rows: list[str], total: int) -> str:
    return (f"<html><body><div>Your search returned <strong>\n {total}</strong> results on 10/7/2026</div>"
            f'<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments">'
            f"<tr><th>#</th><th>Date</th><th>Index</th><th>Type</th><th>Grantor</th><th>Grantee</th>"
            f"<th>Description</th><th>File</th><th>Book/Page</th><th>Ref</th><th>Images</th></tr>"
            + "".join(rows) + "</table></body></html>")


OWNER_GRID = grid([
    _row(1, "01/15/2026", "CRP", "FORCL", _names("TESTER, ALVIN Q", bold=0),
         _names("EXAMPLE TRUSTEE SERVICES/ TR", "EXAMPLE CREDIT UNION"), "", "", "705", "40", ref="640 / 88"),
    _row(2, "02/02/2022", "CRP", "D/T", _names("TESTER, ALVIN Q", bold=0), _names("EXAMPLE CREDIT UNION"),
         "", "2022000123", "640", "88"),
    _row(3, "03/01/2018", "CRP", "DEED", _names("SAMPLE, CORA B"), _names("TESTER, ALVIN Q", "TESTER, BERTHA", bold=0),
         "Address: 12 EXAMPLE RIDGE RD LOT 7 EXAMPLE ACRES", "", "500", "10"),
    _row(4, "**/**/1983", "DTH", "DEATH", _names("TESTER, ALVIN"), _names("TESTER, OLD"), "", "", "9", "9"),
], 4)
SAMPLE_GRID = grid([
    _row(1, "05/05/2001", "CRP", "DEED", _names("DOE, DELLA"), _names("SAMPLE, CORA B", bold=0),
         "LOT 7 EXAMPLE ACRES", "", "350", "77"),
], 1)
EMPTY_GRID = ("<html><body><div>Your search returned <strong>0</strong> results on 10/7/2026</div>"
              "<div>No records found</div></body></html>")
TOO_MANY = ("<html><body><div>The search exceeds the maximum number of allowable results. Please narrow "
            "your search.</div></body></html>")


def _post_router(by_last: dict[str, str]):
    def answer(method, url, params, data):
        last = (data or {}).get(P + "txtFirmSurname", "")
        return FakeResp(by_last.get(last, EMPTY_GRID), 200, url)
    return answer


@pytest.fixture
def fake(monkeypatch):
    def go(routes):
        return install(monkeypatch, routes, cott.ADAPTER)
    yield go
    cott.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_parse_grid_reads_every_column():
    rows, total = cott.parse_grid(OWNER_GRID)
    assert total == 4 and len(rows) == 4
    fcl, dot, deed, death = rows
    assert (fcl.recorded, fcl.doc_type, fcl.kind, fcl.book, fcl.page, fcl.xref) == \
        ("2026-01-15", "FORCL", "foreclosure_notice", "705", "40", "640 / 88")
    assert fcl.grantees == ["EXAMPLE TRUSTEE SERVICES/ TR", "EXAMPLE CREDIT UNION"]
    assert (dot.kind, dot.instrument_no, dot.index_code) == ("deed_of_trust", "2022000123", "CRP")
    assert deed.grantors == ["SAMPLE, CORA B"] and deed.grantees == ["TESTER, ALVIN Q", "TESTER, BERTHA"]
    assert deed.description.startswith("Address: 12 EXAMPLE RIDGE RD")
    assert death.recorded is None                      # a masked date stays unknown, never guessed


def test_parse_grid_empty_and_too_many():
    assert cott.parse_grid(EMPTY_GRID) == ([], 0)
    assert cott.parse_grid(SERVER_ERROR.text) == ([], None)
    assert cott.too_many(TOO_MANY) and not cott.too_many(OWNER_GRID)


def test_name_form_person_entity_and_side():
    d = cott.name_form(FORM, OwnerName(raw="x", last="TESTER", first="ALVIN"), "grantee", "2018-03-01")
    assert d["__VIEWSTATE"] == "" and d[P + "txtFirmSurname"] == "TESTER" and d[P + "ddlWildcardLast"] == "2"
    assert d[P + "txtGivenName"] == "ALVIN" and d[P + "ddlSide"] == "2" and d[P + "txtFiledThru"] == "03/01/2018"
    e = cott.name_form(FORM, OwnerName(raw="x", last="EXAMPLE HOLDINGS LLC", entity=True), "both", None)
    assert e[P + "ddlWildcardLast"] == "0" and e[P + "txtGivenName"] == "" and e[P + "ddlSide"] == "-1"


def test_search_by_name_end_to_end(fake):
    sess = fake([("GET", "SrchName.aspx", FakeResp(FORM)), ("POST", "SrchName.aspx", FakeResp(OWNER_GRID))])
    docs = asyncio.run(cott.search_by_name("NC", "Nash", "TESTER ALVIN Q"))
    assert len(docs) == 4 and docs[2].book == "500" and docs[2].grantee == "TESTER, ALVIN Q; TESTER, BERTHA"
    assert docs[1].raw["kind"] == "deed_of_trust" and docs[0].raw["xref"] == "640 / 88"
    assert [c[0] for c in sess.calls] == ["GET", "POST"]
    assert asyncio.run(cott.search_by_name("NC", "Rutherford", "TESTER ALVIN")) == []   # not configured
    assert asyncio.run(cott.search_by_name("SC", "Nash", "TESTER ALVIN")) == []


def test_empty_answer_is_ok_and_empty(fake):
    fake([("GET", "SrchName.aspx", FakeResp(FORM)), ("POST", "SrchName.aspx", FakeResp(EMPTY_GRID))])
    res = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0


def test_error_page_is_an_error_not_an_empty_county(fake):
    fake([("GET", "SrchName.aspx", FakeResp(FORM)), ("POST", "SrchName.aspx", SERVER_ERROR)])
    res = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and res.reason == "HTTP 500"
    assert nc_polite.walled_reason(cott.PLATFORM, "NC", "Nash") is None
    assert asyncio.run(cott.search_by_name("NC", "Nash", "SAMPLE CORA")) == []


def test_a_200_page_that_is_not_a_grid_is_an_error(fake):
    fake([("GET", "SrchName.aspx", FakeResp(FORM)),
          ("POST", "SrchName.aspx", FakeResp("<html><body>Session expired</body></html>"))])
    res = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "not a results grid" in res.reason


def test_too_many_is_reported(fake):
    fake([("GET", "SrchName.aspx", FakeResp(FORM)), ("POST", "SrchName.aspx", FakeResp(TOO_MANY))])
    res = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "too_many"


def test_blocked_page_records_walled_and_never_retries(fake):
    sess = fake([("GET", "SrchName.aspx", CLOUDFLARE_403)])
    who = OwnerName(raw="x", last="TESTER", first="ALVIN")
    res = cott.ADAPTER.search("Nash", who)
    assert res.status == "walled" and res.reason == "HTTP 403"
    assert nc_polite.walled_reason(cott.PLATFORM, "NC", "Nash") == "HTTP 403"
    sent = len(sess.calls)
    assert asyncio.run(cott.search_by_name("NC", "Nash", "SAMPLE CORA")) == []
    assert cott.chain("Nash", "SAMPLE CORA")["status"] == "walled"
    assert len(sess.calls) == sent == 1                 # nothing more went to the county


def test_guest_signin_page_is_walled(fake):
    login = FakeResp("<html><head><title>eSearch | Account Sign In</title></head><body>"
                     "<input name='ctl00$cphMain$blkLogin$txtPassword' type='password'/>"
                     "<input type='submit' name='ctl00$cphMain$blkLogin$btnGuestLogin' value='Sign in as a Guest'/>"
                     "</body></html>", 200, "https://cotthosting.com/ncexample/User/Login.aspx?ReturnUrl=%2f")
    sess = fake([("GET", "SrchName.aspx", login)])
    res = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == "login page"
    assert [c[0] for c in sess.calls] == ["GET"]          # the guest button was never pressed


def test_lookup_cap_and_cache(fake, monkeypatch):
    sess = fake([("GET", "SrchName.aspx", FakeResp(FORM)), ("POST", "SrchName.aspx", FakeResp(OWNER_GRID))])
    monkeypatch.setenv("NC_ROD_MAX_LOOKUPS_PER_COUNTY", "1")
    who = OwnerName(raw="x", last="TESTER", first="ALVIN")
    assert cott.ADAPTER.search("Nash", who).status == "ok"
    assert cott.ADAPTER.search("Nash", who).status == "ok"          # cached: no new lookup
    assert len(sess.calls) == 2
    other = cott.ADAPTER.search("Nash", OwnerName(raw="x", last="SAMPLE", first="CORA"))
    assert other.status == "capped" and len(sess.calls) == 2


def test_chain_end_to_end(fake):
    sess = fake([("GET", "SrchName.aspx", FakeResp(FORM)),
                 ("POST", "SrchName.aspx", _post_router({"TESTER": OWNER_GRID, "SAMPLE": SAMPLE_GRID}))])
    out = cott.chain("Nash", "TESTER ALVIN Q", depth=3)
    assert out["status"] == "ok" and out["platform"] == "cott_esearch_v4"
    assert out["last_deed"]["book"] == "500" and out["last_deed"]["recorded"] == "2018-03-01"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    assert "DOE, DELLA" in out["chain_stopped"]
    assert [d["book"] for d in out["liens"]["foreclosure_notices"]] == ["705"]
    assert out["liens"]["open_deeds_of_trust_est"] == 1
    assert out["source_url"] == BASE + "SrchName.aspx"
    posts = [c[3] for c in sess.calls if c[0] == "POST"]
    assert posts[1][P + "ddlSide"] == "2" and posts[1][P + "txtFiledThru"] == "03/01/2018"


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in ("Alexander", "Graham", "Granville", "Jackson", "Jones", "Nash", "Pamlico", "Wayne"):
        module, flag, default = g.ROD_CONFIG[("NC", county)]
        assert (module, flag, default) == ("nc_cott_v4", cott.ENV_FLAG, "0")
    assert g.ROD_CONFIG[("NC", "Polk")][:2] == ("cott", "FORECLOSURE_COTT_ROD")      # unchanged
