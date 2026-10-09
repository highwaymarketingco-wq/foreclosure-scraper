"""Top-80 register group (Online Record System, Aumentum/Harris Recorder, Charleston): the checked
negative ("screened, none found") for name-index registers, the Harris empty-page fix, the Harris
Marriage index, and the cube's county verdicts. Fixtures are made up; no fetched content."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_generic_rod as g
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod import nc_harris as hz
from foreclosure_scraper.rod import nc_ors, nc_polite, sc_chain, sc_polite
from foreclosure_scraper.rod import sc_online_record_system as ors
from foreclosure_scraper.rod.models import RodDoc
from foreclosure_scraper.rod.nc_chain import OwnerName, SearchResult, parse_owner
from tests._nc_rod_fakes import FakePWPage, install_render

REPO = Path(__file__).resolve().parents[1]


def _lead(county, owner, state="SC", raw=None):
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state=state,
                   county=county, owner_name=owner, raw=raw or {})


@pytest.fixture(autouse=True)
def _clean():
    sc_chain._CACHE.clear()
    sc_polite.BUDGET.reset()
    sc_polite.reset_walled()
    nc_polite.reset_state()
    yield
    sc_chain._CACHE.clear()
    sc_polite.reset_walled()
    nc_polite.reset_state()


# ---- SC: run_search_status says why a search is empty --------------------------------------------
def _doc(grantor, grantee, kind="DEED"):
    return RodDoc(county="Barnwell", state="SC", doc_type=kind, grantor=grantor, grantee=grantee)


def _searcher(docs=None, exc=None, truncated=False):
    def make():
        def search(q, side, date_to):
            if exc:
                raise exc
            out = sc_chain.Docs(docs or [])
            out.truncated = truncated
            return out
        return search
    return make


def test_run_search_status_codes():
    kw = dict(platform="p", state="SC", county="Barnwell", name="Penrose Wilhelmina")
    docs, st, tr = sc_chain.run_search_status(make_searcher=_searcher([]), **kw)
    assert (docs, st, tr) == ([], "ok", False)                    # searched, nothing indexed
    docs, st, tr = sc_chain.run_search_status(make_searcher=_searcher([_doc("PENROSE WILHELMINA", "X")]),
                                              **{**kw, "name": "Penrose Wilhelmina J"})
    assert st == "ok" and len(docs) == 1
    sc_chain._CACHE.clear()
    assert sc_chain.run_search_status(make_searcher=_searcher(truncated=True), **kw)[1:] == ("ok", True)
    sc_chain._CACHE.clear()
    assert sc_chain.run_search_status(make_searcher=_searcher(exc=RuntimeError("boom")), **kw)[1] == "error"
    assert sc_chain.run_search_status(make_searcher=_searcher(), **{**kw, "name": "  "})[1] == "noname"
    b = sc_polite.LookupBudget()
    b.cap = 0
    sc_chain._CACHE.clear()
    assert sc_chain.run_search_status(make_searcher=_searcher(), budget=b, **kw)[1] == "capped"
    sc_polite.mark_walled("SC", "Barnwell", "HTTP 403")
    assert sc_chain.run_search_status(make_searcher=_searcher(), **kw)[1] == "walled"
    assert sc_chain.run_search(make_searcher=_searcher(), **kw) == []   # the old interface is unchanged


def test_sc_ors_search_by_name_status(monkeypatch):
    monkeypatch.setattr(ors, "make_searcher", lambda state, county, **k: _searcher([])())
    docs, st, tr = asyncio.run(ors.search_by_name_status("SC", "Barnwell", "Penrose Wilhelmina"))
    assert (docs, st, tr) == ([], "ok", False)
    assert asyncio.run(ors.search_by_name_status("SC", "Wake", "Penrose Wilhelmina"))[1] == "error"


# ---- NC: the platform base reports status too ----------------------------------------------------
def test_nc_ors_search_by_name_status(monkeypatch):
    seen = {}

    def fake_search(county, who, side="both", date_thru=None):
        seen["who"] = who
        return SearchResult(status=seen.get("status", "ok"), records=[], truncated=seen.get("trunc", False))

    monkeypatch.setattr(nc_ors.ADAPTER, "search", fake_search)
    assert asyncio.run(nc_ors.search_by_name_status("NC", "Davidson", "PENROSE WILHELMINA")) == ([], "ok", False)
    seen["status"] = "walled"
    assert asyncio.run(nc_ors.search_by_name_status("NC", "Davidson", "PENROSE WILHELMINA"))[1] == "walled"
    assert asyncio.run(nc_ors.search_by_name_status("NC", "Davidson", ""))[1] == "noname"
    assert asyncio.run(nc_ors.search_by_name_status("NC", "Wake", "PENROSE WILHELMINA"))[1] == "error"
    assert asyncio.run(nc_ors.search_by_name_status("SC", "Davidson", "PENROSE WILHELMINA"))[1] == "error"


# ---- generic_rod stamps a clean negative, and only a clean one -------------------------------------
class _FakeMod:
    def __init__(self, status="ok", docs=None, truncated=False):
        self.status, self.docs, self.truncated = status, docs or [], truncated

    async def search_by_name_status(self, state, county, name, max_docs=80):
        return self.docs, self.status, self.truncated

    async def search_by_name(self, state, county, name, max_docs=80):
        return self.docs


def _run_generic(monkeypatch, mod, leads):
    monkeypatch.setitem(g.ROD_CONFIG, ("SC", "Fakeville"), ("fakemod", "FORECLOSURE_FAKE_ROD", "1"))
    monkeypatch.setattr(g, "_get_module", lambda name: mod)
    return asyncio.run(g.enrich_generic_rod(leads))


@pytest.mark.parametrize("status,truncated,stamped", [("ok", False, True), ("ok", True, False),
                                                       ("walled", False, False), ("capped", False, False),
                                                       ("error", False, False), ("noname", False, False)])
def test_generic_rod_stamps_only_a_clean_none_found(monkeypatch, status, truncated, stamped):
    lead = _lead("Fakeville", "PENROSE WILHELMINA J")
    stats = _run_generic(monkeypatch, _FakeMod(status, [], truncated), [lead])
    assert ("rod" in lead.raw) is stamped
    assert stats["screened_none_found"] == int(stamped)
    if stamped:
        rod = lead.raw["rod"]
        assert rod["instrument_count"] == 0 and rod["screened_none_found"] is True
        assert rod["has_mortgage"] is False and rod["open_mortgages_est"] == 0 and rod["fetched_at"]
        assert rod["platform"] == "fakemod"


def test_generic_rod_keeps_a_real_hit_and_a_namesake_only_result(monkeypatch):
    mine = _doc("PENROSE WILHELMINA J", "EXAMPLE BANK", "MORTGAGE")
    lead = _lead("Fakeville", "PENROSE WILHELMINA J")
    stats = _run_generic(monkeypatch, _FakeMod("ok", [mine]), [lead])
    assert lead.raw["rod"]["instrument_count"] == 1 and "screened_none_found" not in lead.raw["rod"]
    assert stats["with_instruments"] == 1
    other = _doc("SOMEONE ELSE", "EXAMPLE BANK", "MORTGAGE")            # a namesake row: not the owner's
    lead2 = _lead("Fakeville", "PENROSE WILHELMINA J")
    _run_generic(monkeypatch, _FakeMod("ok", [other]), [lead2])
    assert lead2.raw["rod"]["screened_none_found"] is True


def test_generic_rod_module_without_status_is_unchanged(monkeypatch):
    class Old:
        async def search_by_name(self, state, county, name, max_docs=80):
            return []
    lead = _lead("Fakeville", "PENROSE WILHELMINA J")
    _run_generic(monkeypatch, Old(), [lead])
    assert "rod" not in lead.raw                                          # still "fetch failed, retry"


def test_status_functions_are_on_the_modules_the_cube_counts():
    for name in ("sc_online_record_system", "nc_ors"):
        mod = g._get_module(name)
        assert hasattr(mod, "search_by_name_status"), name
    cfg = {k: v for k, v in g.ROD_CONFIG.items() if v[0] in ("sc_online_record_system", "nc_ors")}
    assert {c for (_s, c) in cfg} >= {"Barnwell", "Berkeley", "Colleton", "Dorchester", "Florence", "Georgetown",
                                      "York", "Lancaster", "Laurens", "Abbeville", "Davidson", "Forsyth",
                                      "Guilford", "New Hanover"}


# ---- Harris: the empty page the live app serves, and the Marriage index --------------------------
ROOT = hz.COUNTIES["Mecklenburg"].root
EMPTY_LIVE = ("<html><body><div>Criteria: Party Name Begins With TESTER ALVIN; 0 records found as of 10/09/2026 "
              "11:55:10 AM count again</div></body></html>")
WELCOME = ("<html><body><a id='cph1_lnkAccept' href=\"javascript:__doPostBack('a','')\">Click here to "
           "acknowledge the disclaimer and enter the site.</a></body></html>")
ENTERED = "<html><body>Search Real Estate Index</body></html>"
RE_FORM = ("<html><body><input id='cphNoMargin_f_txtParty' type='text'/><input type='radio' "
           "id='cphNoMargin_f_drbPartyType_0'/><input type='submit' id='cphNoMargin_SearchButtons1_btnSearch'/>"
           "</body></html>")
MK_FORM = ("<html><body><input id='cphNoMargin_f_txtGrantor' type='text'/>"
           "<input type='submit' id='cphNoMargin_SearchButtons1_btnSearch'/></body></html>")
MK_KEYS = ["RowNumber", "MARRIAGE_ID", "LICENSE_NO", "DATE_OF_APP", "DATE_OF_MARRIAGE", "GROOM", "GROOM_MAIDEN_NAME",
           "BRIDE", "BRIDE_MAIDEN_NAME", "LICENSE_STATUS"]


def mk_row(n, lic, app, wed, groom, bride, status="R"):
    vals = [n, 100 + n, lic, app, wed, groom, groom.split()[0], bride, bride.split()[0], status]
    return f'<tr adr="{n}" type="row">' + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"


def mk_page(found, rows):
    return (f"<html><body>Showing Records 1 through 25 ( {found} records found as of 10/09/2026 )"
            "<table><tr>" + "".join(f'<th key="{k}">{k}</th>' for k in MK_KEYS) + "</tr>" + "".join(rows)
            + "</table></body></html>")


EMPTY_MK_LIVE = ("<html><body>Criteria: Name begins with TESTER ALVIN 0 records found as of 10/09/2026 12:00:40 PM "
                 "count again Get a Free Copy</body></html>")
TESTER_MK = mk_page(2, [mk_row(1, "2019000111", "03/01/2019", "03/09/2019", "ROE RICHARD Q", "TESTER ALVINA"),
                        mk_row(2, "2024000222", "05/01/2024", "05/04/2024", "TESTER ALVIN Q", "DOE JANELLE M")])
MANY_MK = mk_page(60, [mk_row(1, "2020000333", "01/01/2020", "01/05/2020", "SMITH JOHN", "JONES MARY")])


def _site(search_html):
    def search(page):
        if "/Marriage/" in page.url:
            return (ROOT + "/Marriage/SearchResults.aspx", search_html(page.typed.get(hz.MARRIAGE_NAME, "")))
        return (ROOT + "/RealEstate/SearchResults.aspx", EMPTY_LIVE)
    pages = {"/RealEstate/SearchEntry.aspx": RE_FORM, "/Marriage/SearchEntry.aspx": MK_FORM, ROOT + "/": WELCOME}
    return FakePWPage(pages, {hz.ACCEPT_LINK: (ROOT + "/", ENTERED), hz.SEARCH: search})


@pytest.fixture
def harris(monkeypatch):
    made = []

    def go(search_html=lambda typed: EMPTY_LIVE):
        install_render(monkeypatch, lambda: made.append(_site(search_html)) or made[-1])
        return made
    yield go
    hz.ADAPTER.drop_sessions()


def test_harris_empty_live_page_is_a_clean_zero_not_an_error(harris):
    assert hz.parse_results(EMPTY_LIVE) == ([], 0, 0) and hz.no_records(EMPTY_LIVE)
    made = harris()
    res = hz.ADAPTER.search("Mecklenburg", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0 and len(made) == 1


def test_parse_marriage_results_and_match():
    rows, found = hz.parse_marriage_results(TESTER_MK)
    assert found == 2 and len(rows) == 2
    assert rows[1]["groom"] == "TESTER ALVIN Q" and rows[1]["married"] == "2024-05-04"
    who = OwnerName(raw="x", last="TESTER", first="ALVIN")
    hit = hz.marriage_license_from(rows, who, "Mecklenburg")
    assert hit["spouse_name"] == "Doe Janelle M" and hit["license_date"] == "2024-05-04"      # the newest licence
    assert hit["source"] == "harris_marriage_index" and hit["county_issued"] == "Mecklenburg"
    assert hit["match_confidence"] == "high"
    assert hz.marriage_license_from(rows, OwnerName(raw="x", last="NOBODY", first="ZED"), "Mecklenburg") is None
    assert hz.parse_marriage_results(EMPTY_LIVE) == ([], 0) and hz.parse_marriage_results(EMPTY_MK_LIVE) == ([], 0)
    assert not hz.no_records("<html>Criteria: Name begins with X 10 records found as of</html>")
    assert hz.parse_marriage_results("<html>boom</html>") == ([], None)


def test_marriage_search_and_walls(harris):
    made = harris(lambda typed: TESTER_MK if typed.startswith("TESTER") else EMPTY_MK_LIVE)
    res = hz.marriage_search("Mecklenburg", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "ok" and len(res.rows) == 2 and res.found == 2
    assert made[0].typed[hz.MARRIAGE_NAME] == "TESTER ALVIN"
    assert "LoginForm1_txtLogonName" not in made[0].typed                 # the optional sign-in box is untouched
    res = hz.marriage_search("Mecklenburg", OwnerName(raw="x", last="NOBODY", first="ZED"))
    assert res.status == "ok" and res.rows == [] and res.found == 0
    assert hz.marriage_search("Mecklenburg", OwnerName(raw="x", last="ACME LLC", entity=True)).status == "error"
    assert hz.marriage_search("Wake", OwnerName(raw="x", last="TESTER", first="ALVIN")).status == "error"
    nc_polite.mark_walled(hz.PLATFORM, "NC", "Mecklenburg", "HTTP 403")
    assert hz.marriage_search("Mecklenburg", OwnerName(raw="x", last="TESTER", first="ALVIN")).status == "walled"


def test_marriage_enricher_stamps_found_no_match_and_skips_the_unsure(harris, monkeypatch):
    from foreclosure_scraper.enrichment_nc_rod_render import enrich_marriage_render
    import time

    def pick(typed):
        return (TESTER_MK if typed.startswith("TESTER") else MANY_MK if typed.startswith("SMITH") else EMPTY_LIVE)

    harris(pick)
    leads = [_lead("Mecklenburg", "TESTER ALVIN Q", "NC"), _lead("Mecklenburg", "NOBODY ZED", "NC"),
             _lead("Mecklenburg", "SMITH PAT", "NC"), _lead("Mecklenburg", "ACME HOLDINGS LLC", "NC"),
             _lead("Mecklenburg", "TESTER ALVIN Q", "NC", raw={"marriage_license": {"status": "no_match"}}),
             _lead("Wake", "TESTER ALVIN Q", "NC")]
    kw = dict(t0=time.monotonic(), budget_s=600.0)
    monkeypatch.delenv(hz.MARRIAGE_FLAG, raising=False)
    assert asyncio.run(enrich_marriage_render(leads, **kw))["marriage_searched"] == 0       # OFF by default
    monkeypatch.setenv(hz.MARRIAGE_FLAG, "1")
    monkeypatch.delenv(hz.ENV_FLAG, raising=False)
    assert asyncio.run(enrich_marriage_render(leads, **kw))["marriage_searched"] == 0       # needs the Harris flag
    monkeypatch.setenv(hz.ENV_FLAG, "1")
    out = asyncio.run(enrich_marriage_render(leads, **kw))
    assert out["marriage_found"] == 1 and out["marriage_no_match"] == 1 and out["marriage_searched"] == 3
    assert leads[0].raw["marriage_license"]["spouse_name"] == "Doe Janelle M"
    ml = leads[1].raw["marriage_license"]
    assert ml["status"] == "no_match" and ml["checked_at"] and ml["source"] == "harris_marriage_index"
    assert "marriage_license" not in leads[2].raw       # 60 licences, 1 row read: the owner may be on page 2
    assert "marriage_license" not in leads[3].raw and "marriage_license" not in leads[5].raw
    assert leads[4].raw["marriage_license"] == {"status": "no_match"}                       # idempotent


# ---- the cube: county verdicts and built detection -------------------------------------------------
def _gm():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gap_matrix_top80", REPO / "scripts" / "gap_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["gap_matrix_top80"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_source_status_reads_a_column_verdict_from_the_register_block():
    gm = _gm()
    rec = {"rod": {"url": "https://x.example/", "access": "disclaimer_click", "free_name_search": "yes",
                   "column_access": {"marriage_license": "login", "atty_rod_lien_checked": "none"}}}
    S = gm.SPECS
    assert gm.source_status(S["marriage_license"], "NC", rec, "marriage_license")[:2] == ("walled", "login")
    assert gm.source_status(S["marriage_license"], "NC", rec)[0] == "free"            # no col: the block's own status
    assert gm.source_status(S["liens"], "NC", rec, "liens")[0] == "free"              # other columns unaffected
    st = gm.source_status(S["atty_rod_lien_checked"], "NC", rec, "atty_rod_lien_checked")
    assert st[0] == "unknown" and "no free source" in st[2]


def test_matrix_verdicts_for_the_register_group():
    m = {(c["state"], c["county"]): c for c in json.loads(
        (REPO / "docs/county_records/county_records_matrix.json").read_text())["counties"]}
    assert m[("SC", "charleston")]["rod"]["access"] == "captcha"
    assert m[("NC", "moore")]["rod"]["access"] == "blocked"
    for co in ("guilford", "forsyth"):
        assert m[("NC", co)]["rod"]["column_access"]["marriage_license"] == "login"
    assert m[("NC", "davidson")]["rod"]["column_access"]["marriage_license"] == "none"
    for co in ("barnwell", "berkeley", "colleton", "dorchester", "georgetown", "charleston"):
        assert m[("SC", co)]["rod"]["column_access"]["marriage_license"] == "blocked"
    assert "column_access" not in m[("NC", "mecklenburg")]["rod"]           # buildable: not a verdict


def test_liens_producers_name_the_register_counties():
    gm = _gm()
    named = gm.counties_named_in([gm.PKG / f for f in gm.SPECS["liens"].producers if (gm.PKG / f).exists()],
                                 gm._county_patterns())
    for key in [("NC", "Guilford"), ("NC", "Forsyth"), ("NC", "Davidson"), ("SC", "Barnwell"), ("SC", "York"),
                ("SC", "Lancaster"), ("SC", "Florence"), ("NC", "Mecklenburg")]:
        assert key in named, key


# ---- the invariant file -----------------------------------------------------------------------------
def test_top80_register_invariants():
    import importlib.util
    spec = importlib.util.spec_from_file_location("top80_register_ors", REPO / "scripts/audit_checks/top80_register_ors.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    checks = {c.name: c for c in mod.make_checks()}
    neg = {"instrument_count": 0, "has_mortgage": False, "has_adverse_lien": False, "open_mortgages_est": 0,
           "fetched_at": "2026-10-09T00:00:00+00:00", "screened_none_found": True}
    rows = [{"state": "SC", "county": "Barnwell", "owner_name": "A B", "raw": {"rod": dict(neg)}}] \
        + [{"state": "SC", "county": "Barnwell", "owner_name": f"O {i}", "raw": {}} for i in range(25)] \
        + [{"state": "NC", "county": "Davidson", "owner_name": f"O {i}", "raw": {}} for i in range(25)] \
        + [{"state": "SC", "county": "Barnwell", "owner_name": "BAD", "raw": {"rod": {**neg, "has_mortgage": True}}},
           {"state": "NC", "county": "Mecklenburg", "owner_name": "M", "raw": {"marriage_license": {
               "source": "harris_marriage_index", "status": "no_match"}}}]
    for r in rows:
        for c in checks.values():
            c.feed(r)
    out = {n: c.finish() for n, c in checks.items()}
    assert out["top80-register-negative-shape"]["violations"] == 1 and not out["top80-register-negative-shape"]["ok"]
    silent = out["top80-register-county-silent"]
    assert silent["violations"] == 1 and "NC Davidson" in silent["detail"] and "SC Barnwell" not in silent["detail"]
    assert out["top80-marriage-license-shape"]["violations"] == 1
    assert out["top80-register-config-consistent"]["ok"], out["top80-register-config-consistent"]["detail"]
