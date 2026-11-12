"""Harris 'ROD Web Access' adapter (rod/nc_harris.py) and the render enricher, on hand-written pages
shaped like the live welcome page, search form and WebDataGrid results (made-up names, numbers; no
fetched content), driven through the real rod.nc_render.RenderPage with a scripted fake browser
page. Covers the parse, paging, an empty answer, an error page, a blocked page and a CAPTCHA
(walled, never retried), chain(), the run cap, the enricher, and the registry entries."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod import nc_harris as hz
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakePWPage, install, install_render

ROOT = hz.COUNTIES["Carteret"].root
WELCOME = ("<html><head><title>Welcome - Example ROD Web Access</title></head><body><form id='form1'>"
           "<input type='text' id='LoginForm1_txtLogonName'/><input type='password' id='LoginForm1_txtPassword'/>"
           "<a id='cph1_lnkAccept' href=\"javascript:__doPostBack('ctl00$cph1$lnkAccept','')\">Click here to "
           "acknowledge the disclaimer and enter the site.</a></form></body></html>")
ENTERED = "<html><head><title>Welcome - Example ROD Web Access</title></head><body>Search Real Estate Index</body></html>"
FORM = ("<html><body><form id='form1'><input id='cphNoMargin_f_txtParty' type='text'/>"
        "<input type='radio' id='cphNoMargin_f_drbPartyType_0'/><input type='radio' id='cphNoMargin_f_drbPartyType_1'/>"
        "<input type='radio' id='cphNoMargin_f_drbPartyType_2'/><div id='cphNoMargin_f_ddcDateFiledFrom'><input type='text'/>"
        "</div><div id='cphNoMargin_f_ddcDateFiledTo'><input type='text'/></div>"
        "<input type='submit' id='cphNoMargin_SearchButtons1_btnSearch' value='Search'/></form></body></html>")
KEYS = ["RowNumber", "ImageUrl", "clientSelect", "DetailUrl", "INSTRUMENT_NUMBER_COMBO", "INSTRUMENT_NUMBER", "BOOK", "PAGE",
        "DATE_RECEIVED", "DOCUMENT_TYPE_DESC", "DOCUMENT_TYPE", "NAME_COMBO", "NAME_TYPE", "GRANTOR", "xMORENAMES1",
        "NAME_TYPE2", "GRANTEE", "xMORENAMES2", "COMBINED_LEGAL"]


def row(n, inst, book, page, date, kind, ntype, party, ntype2, reverse, legal=""):
    vals = {"RowNumber": n, "INSTRUMENT_NUMBER": inst, "INSTRUMENT_NUMBER_COMBO": inst, "BOOK": book, "PAGE": page,
            "DATE_RECEIVED": date, "DOCUMENT_TYPE_DESC": kind, "DOCUMENT_TYPE": kind, "NAME_TYPE": ntype,
            "GRANTOR": party, "NAME_TYPE2": ntype2, "GRANTEE": reverse, "COMBINED_LEGAL": legal}
    return f'<tr adr="{n}" type="row">' + "".join(f"<td>{vals.get(k, '')}</td>" for k in KEYS) + "</tr>"


def results(found, rows, pages=1, page_no=1):
    opts = "".join(f"<option value='{i}'{' selected' if i == page_no else ''}>Page {i}</option>" for i in range(1, pages + 1))
    nxt = '' if page_no < pages else ' disabled'
    bar = (f"<select aria-label='Results Page Selection'>{opts}</select>"
           f"<input type='image' id='OptionsBar1_imgNext'{nxt} title='Next'/>")
    return (f"<html><body><div>Showing Records 1 through 25 ( {found} records found as of 10/07/2026 )</div>{bar}"
            "<table><tr>" + "".join(f'<th key="{k}">{k}</th>' for k in KEYS) + "</tr>"
            "<tr>" + "".join(f"<th>{k}</th>" for k in KEYS) + "</tr>" + "".join(rows) + "</table>"
            f"<select aria-label='Results Page Selection'>{opts}</select></body></html>")


TESTER_P1 = results(4, [
    row(1, "2026000300", "700", "40", "01/15/2026", "LIS PENDENS", "E", "TESTER ALVIN Q", "R", "EXAMPLE BANK"),
    row(2, "2022000200", "640", "88", "02/02/2022", "DEED OF TRUST", "R", "TESTER ALVIN Q (+)", "E", "EXAMPLE BANK",
        "LT 7 EXAMPLE ACRES"),
    row(3, "2022000200", "640", "88", "02/02/2022", "DEED OF TRUST", "R", "TESTER BERTHA (+)", "E", "EXAMPLE BANK",
        "LT 7 EXAMPLE ACRES")], pages=2, page_no=1)
TESTER_P2 = results(4, [row(4, "2018000100", "500", "10", "03/01/2018", "DEED", "E", "TESTER ALVIN Q", "R",
                            "SAMPLE CORA B", "LT 7 EXAMPLE ACRES")], pages=2, page_no=2)
SAMPLE_P1 = results(1, [row(1, "2001000050", "350", "77", "05/05/2001", "DEED", "E", "SAMPLE CORA B", "R", "DOE DELLA")])
EMPTY = "<html><body><div>( 0 records found as of 10/07/2026 )</div></body></html>"


def site(**over):
    """A fake browser page for one lookup on a made-up Harris county."""
    def search(page):
        name = page.typed.get(hz.PARTY, "")
        html = TESTER_P1 if name.startswith("TESTER") else SAMPLE_P1 if name.startswith("SAMPLE") else EMPTY
        return (ROOT + "/RealEstate/SearchResults.aspx", html)
    pages = {"/RealEstate/SearchEntry.aspx": FORM, ROOT + "/": WELCOME}
    pages.update(over.pop("pages", {}))
    clicks = {hz.ACCEPT_LINK: (ROOT + "/", ENTERED), hz.SEARCH: search,
              hz.NEXT: (ROOT + "/RealEstate/SearchResults.aspx", TESTER_P2)}
    clicks.update(over.pop("clicks", {}))
    return FakePWPage(pages, clicks)


@pytest.fixture
def fake(monkeypatch):
    made: list[FakePWPage] = []

    def go(**over):
        install(monkeypatch, [], hz.ADAPTER)
        install_render(monkeypatch, lambda: made.append(site(**dict(over))) or made[-1])
        return made
    yield go
    hz.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_parse_results():
    rows, found, pages = hz.parse_results(TESTER_P1)
    assert (found, pages, len(rows)) == (4, 2, 3)
    lp, dt1, dt2 = rows
    assert (lp.kind, lp.grantors, lp.grantees, lp.recorded) == ("lis_pendens", ["EXAMPLE BANK"], ["TESTER ALVIN Q"],
                                                                "2026-01-15")
    assert (dt1.kind, dt1.grantors, dt1.description, dt1.book) == ("deed_of_trust", ["TESTER ALVIN Q"],
                                                                   "LT 7 EXAMPLE ACRES", "640")
    assert dt2.grantors == ["TESTER BERTHA"]                     # '(+)' dropped; one row per party
    assert hz.parse_results(EMPTY) == ([], 0, 0) and hz.no_records(EMPTY)
    assert hz.party_text(OwnerName(raw="x", last="TESTER", first="ALVIN")) == "TESTER ALVIN"


def test_search_pages_and_folds(fake):
    made = fake()
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "ok" and res.total == 4 and not res.truncated
    assert [r.book for r in res.records] == ["700", "640", "500"]          # the two party rows folded
    assert res.records[1].grantors == ["TESTER ALVIN Q", "TESTER BERTHA"]
    p = made[0]
    assert p.typed[hz.PARTY] == "TESTER ALVIN"
    assert ("click", hz.ACCEPT_LINK) in p.log and ("click", hz.NEXT) in p.log
    assert [x for x in p.log if x[0] == "goto"] == [("goto", ROOT + "/"), ("goto", ROOT + "/RealEstate/SearchEntry.aspx")]
    assert "LoginForm1_txtLogonName" not in p.typed                    # the account box is never touched


def test_chain_sides_and_dates(fake):
    made = fake()
    out = hz.chain("Carteret", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [x["book"] for x in out["prior_instruments"]] == ["350"]
    walk = made[1]
    assert ("click", hz.SIDE_RADIO["grantee"]) in walk.log
    assert walk.typed[hz.DATE_TO] == "03/01/2018" and walk.typed[hz.PARTY] == "SAMPLE CORA"


def test_empty_and_error(fake):
    fake()
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0
    fake(pages={"/RealEstate/SearchEntry.aspx": "<html><body>Service unavailable for maintenance</body></html>"})
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "did not open" in res.reason
    fake(clicks={hz.SEARCH: (ROOT + "/RealEstate/SearchResults.aspx", "<html><body>Object reference</body></html>")})
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "could not be read" in res.reason


@pytest.mark.parametrize("wall,reason", [((403, CLOUDFLARE_403.text), "HTTP 403"), (CAPTCHA_PAGE.text, "CAPTCHA")])
def test_blocked_is_walled_and_never_retried(fake, wall, reason):
    made = fake(pages={ROOT + "/": wall})
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(hz.search_by_name("NC", "Carteret", "SAMPLE CORA")) == []
    assert hz.chain("Carteret", "TESTER ALVIN Q")["status"] == "walled"
    assert len(made) == 1 and made[0].log == [("goto", ROOT + "/")]  # one page, nothing after the wall


def test_run_cap_env(fake, monkeypatch):
    made = fake()
    monkeypatch.setenv(hz.CAP_ENV, "1")
    assert hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="TESTER", first="ALVIN")).status == "ok"
    res = hz.ADAPTER.search("Carteret", OwnerName(raw="x", last="SAMPLE", first="CORA"))
    assert res.status == "capped" and "1 lookups" in res.reason and len(made) == 1


def _lead(county, owner, raw=None):
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state="NC",
                   county=county, owner_name=owner, raw=raw or {})


def test_render_enricher(fake, monkeypatch):
    from foreclosure_scraper.enrichment_nc_rod_render import enrich_nc_rod_render
    made = fake()
    leads = [_lead("Carteret", "TESTER ALVIN Q"), _lead("Carteret", "NOBODY ALVIN"),
             _lead("Carteret", "SAMPLE CORA", raw={"rod": {"source": "earlier"}}), _lead("Wake", "TESTER ALVIN Q")]
    monkeypatch.delenv(hz.ENV_FLAG, raising=False)
    assert asyncio.run(enrich_nc_rod_render(leads))["disabled_counties"] == 1 and made == []
    monkeypatch.setenv(hz.ENV_FLAG, "1")
    stats = asyncio.run(enrich_nc_rod_render(leads))
    rod = leads[0].raw["rod"]
    assert rod["source"] == "nc_render:harris_rod_web_access" and rod["has_mortgage"] and rod["has_adverse_lien"]
    assert leads[1].raw["rod"]["instrument_count"] == 0                    # a clean no-match is stamped
    assert leads[2].raw["rod"] == {"source": "earlier"}                    # idempotent: skipped
    assert "rod" not in leads[3].raw
    assert stats["searched"] == 2 and stats["with_instruments"] == 1 and len(made) == 2
    again = asyncio.run(enrich_nc_rod_render(leads))
    assert again["targets"] == 0


def test_render_enricher_stops_a_walled_county(fake, monkeypatch):
    from foreclosure_scraper.enrichment_nc_rod_render import enrich_nc_rod_render
    made = fake(pages={ROOT + "/": CAPTCHA_PAGE.text})
    monkeypatch.setenv(hz.ENV_FLAG, "1")
    leads = [_lead("Carteret", "TESTER ALVIN Q"), _lead("Carteret", "SAMPLE CORA")]
    stats = asyncio.run(enrich_nc_rod_render(leads))
    assert stats["walled_counties"] == ["Carteret"] and all("rod" not in li.raw for li in leads) and len(made) == 1


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    from foreclosure_scraper.enrichment_rod_chain import chain_registry
    for county in hz.COUNTIES:
        assert g.RENDER_ROD_CONFIG[("NC", county)] == ("nc_harris", hz.ENV_FLAG, "0")
        assert ("NC", county) not in g.ROD_CONFIG                          # not run by enrich_generic_rod
        assert chain_registry()[("NC", county)][0] == "nc_harris"
    assert ("NC", "Moore") not in g.RENDER_ROD_CONFIG
