"""enrichment_probate_spartan (top-80 2026-10-09): Spartan public probate inquiry, three SC courts.
Names, case numbers and counts below are made up."""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import foreclosure_scraper.enrichment_probate_spartan as P
from foreclosure_scraper import screen_ledger as SL

PAGE_HTML = ("<select name=\"ctl00$ContentPlaceHolder1$PartySearchControl1$AgencySearchForm$AgencyId\" "
             "id=\"x\"><option value=\"24500\">Example County Estates</option></select>"
             "<script>SetDataTable('#partyListGrid', '/ExamplePortal/Handlers/Data.asmx/CasePartySearch', 'x.gif',")


def answer(total, rows):
    inner = {"Error": None, "sEcho": 1, "recordsTotal": total, "recordsFiltered": total,
             "aaData": [{"WARANTNO": c, "PTYNAME": n, "CSPTYTYP": "DEC", "APPCODE": "24500"} for c, n in rows]}
    return json.dumps({"d": json.dumps(inner)})


class FakeHttp:
    def __init__(self, pages, fail_after=None):
        self.pages = pages          # {start: (total, rows)}
        self.calls = []
        self.fail_after = fail_after

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if url.endswith("PartySearchPage.aspx"):
            return SimpleNamespace(status_code=200, text=PAGE_HTML)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            return SimpleNamespace(status_code=500, text="")
        start = int(params["iDisplayStart"])
        total, rows = self.pages[start]
        return SimpleNamespace(status_code=200, text=answer(total, rows))


@pytest.fixture(autouse=True)
def _fast(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "PACE_S", 0.0)
    monkeypatch.setattr(P, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(P, "PAGE", 2)


# --------------------------------------------------------------------------- the portal

def test_search_page_gives_the_handler_and_the_agency():
    assert P.parse_search_page(PAGE_HTML) == ("/ExamplePortal/Handlers/Data.asmx/CasePartySearch", "24500")
    with pytest.raises(P.SpartanError):
        P.parse_search_page("<html>nothing</html>")


def test_the_request_lists_decedents_with_a_stable_two_column_sort():
    p = P.page_params("24500", 200)
    assert p["PartyType"] == "DEC" and p["LastName"] == "" and p["AgencyId"] == "24500"
    assert p["iDisplayStart"] == "200" and p["iSortingCols"] == "2" and p["iSortCol_1"] == "1"


def test_parse_answer_and_errors():
    total, rows = P.parse_answer(answer(7, [("1985ES2400360", "DOE, JANE A")]))
    assert total == 7 and rows == [["1985ES2400360", "DOE, JANE A"]]
    for bad in ("not json", json.dumps({"d": "not json"}), json.dumps({"d": json.dumps({"Error": "boom"})})):
        with pytest.raises(P.SpartanError):
            P.parse_answer(bad)


def test_read_index_pages_to_the_total_and_is_complete():
    http = FakeHttp({0: (3, [("2001ES1", "DOE, JANE A"), ("2002ES2", "ROE, JOHN")]), 2: (3, [("2003ES3", "POE, SAM")])})
    doc = asyncio.run(P.read_index(http, "https://h.example/ExamplePortal", None, deadline=1e18))
    assert doc["complete"] and doc["total"] == 3 and len(doc["rows"]) == 3
    url, params, hdr = http.calls[1]
    assert url == "https://h.example/ExamplePortal/Handlers/Data.asmx/CasePartySearch"
    assert hdr == {"Content-Type": "application/json"}


def test_a_duplicate_row_from_tied_sort_keys_is_dropped_and_still_complete():
    http = FakeHttp({0: (3, [("1", "DOE, A"), ("2", "ROE, B")]), 2: (3, [("2", "ROE, B")])})
    doc = asyncio.run(P.read_index(http, "https://h.example/X", None, deadline=1e18))
    assert len(doc["rows"]) == 2 and doc["total"] == 3 and not doc["complete"]      # 2 of 3 < 99%


def test_a_budget_stop_saves_progress_and_the_next_run_resumes():
    pages = {0: (4, [("1", "DOE, A"), ("2", "ROE, B")]), 2: (4, [("3", "POE, C"), ("4", "LOE, D")])}
    first = asyncio.run(P.read_index(FakeHttp(pages), "https://h.example/X", None, deadline=0.0))
    assert not first["complete"] and first["rows"] == [] and first["next_start"] == 0
    # one page in, then the deadline: simulate by a cache that already holds the first page
    cache = {"fetched_on": date.today().isoformat(), "complete": False, "total": 4, "next_start": 2,
             "rows": [["1", "DOE, A"], ["2", "ROE, B"]]}
    http = FakeHttp(pages)
    done = asyncio.run(P.read_index(http, "https://h.example/X", cache, deadline=1e18))
    assert done["complete"] and len(done["rows"]) == 4
    assert [int(c[1]["iDisplayStart"]) for c in http.calls[1:]] == [2]           # resumed, not restarted


def test_a_failing_portal_raises_after_retries():
    http = FakeHttp({0: (1, [])}, fail_after=1)
    with pytest.raises(P.SpartanError):
        asyncio.run(P.read_index(http, "https://h.example/X", None, deadline=1e18))


# --------------------------------------------------------------------------- cache

def test_cache_round_trip_and_ttl():
    doc = {"fetched_on": date.today().isoformat(), "complete": True, "rows": []}
    P.save_cache("Greenwood", doc)
    assert P.load_cache("Greenwood") == doc
    old = {"fetched_on": (date.today() - timedelta(days=P.CACHE_TTL_DAYS + 1)).isoformat(), "complete": True}
    P.save_cache("Newberry", old)
    assert P.load_cache("Newberry") is None and P.load_cache("Calhoun") is None


# --------------------------------------------------------------------------- matching

ROWS = [["1985ES2400360", "SMITHSON, LOUGENIA H"], ["2019ES2400111", "SMITHSON, LOUGENIA"],
        ["2020ES2400222", "ROEBUCK, TIMOTHY ALAN"], ["1999ES2400333", "ZOLLER, KARL"]]


def row(owner, county="Greenwood", raw=None, state="SC"):
    return SimpleNamespace(county=county, state=state, owner_name=owner, raw=raw, listing_type="foreclosure_sale")


def test_full_and_initial_fits_are_found_and_a_different_middle_name_is_not():
    idx = P.DecedentIndex(ROWS)
    fits = idx.fits(["SMITHSON LOUGENIA H"])
    assert fits and fits[0]["level"] in ("full", "middle_initial") and fits[0]["case_number"].endswith("ES2400360")
    assert idx.fits(["SMITHSON LOUGENIA B"]) == [] or all(f["case_number"] != "1985ES2400360" for f in
                                                         idx.fits(["SMITHSON LOUGENIA B"]))
    assert idx.fits(["ROEBUCK TIMOTHY ALAN"])[0]["level"] == "full"
    assert idx.fits(["NOBODY HERE"]) == []


def test_given_surname_only_counts_for_a_recent_case():
    idx = P.DecedentIndex([["1999ES1", "ZOLLER, KARL ERIC"], ["2015ES2", "ZOLLER, KARL ERIC"]])
    got = idx.fits(["ZOLLER KARL"])
    assert [f["case_number"] for f in got] == ["2015ES2"]            # the 1999 case is too old for a thin fit


def test_a_name_match_alone_never_writes_raw_probate():
    idx = P.DecedentIndex(ROWS)
    r = row("ROEBUCK TIMOTHY ALAN")
    st = P.match_rows([r], {"Greenwood": idx})
    assert r.raw["probate_index_match"][0]["case_number"] == "2020ES2400222"
    assert "probate" not in r.raw
    assert (st["rows_matched_against"], st["match_stamped"], st["probate_promoted"]) == (1, 1, 0)


def test_a_death_on_the_roll_promotes_the_match_to_raw_probate_without_overwriting_a_case():
    idx = P.DecedentIndex(ROWS)
    r = row("ESTATE OF ROEBUCK TIMOTHY ALAN")
    P.match_rows([r], {"Greenwood": idx})
    pr = r.raw["probate"]
    assert pr["case_number"] == "2020ES2400222" and pr["es_case_number"] == "2020ES2400222"
    assert pr["source"] == P.SOURCE and pr["match_confidence"] in ("full", "middle_initial")
    keep = row("ESTATE OF ROEBUCK TIMOTHY ALAN", raw={"probate": {"case_number": "X9", "decedent": "Someone"}})
    P.match_rows([keep], {"Greenwood": idx})
    assert keep.raw["probate"]["case_number"] == "X9"
    assert keep.raw["probate_index_match"]


def test_other_states_counties_and_unindexed_counties_are_untouched():
    idx = P.DecedentIndex(ROWS)
    a, b, c = row("ROEBUCK TIMOTHY ALAN", state="NC"), row("ROEBUCK TIMOTHY ALAN", county="Aiken"), row(None)
    st = P.match_rows([a, b, c], {"Greenwood": idx})
    assert a.raw is None and b.raw is None and c.raw is None and st["rows_matched_against"] == 0


# --------------------------------------------------------------------------- the enrichment end to end

def test_enrich_builds_matches_and_reports_the_screened_county(monkeypatch):
    http = FakeHttp({0: (2, [("2020ES2400222", "ROEBUCK, TIMOTHY ALAN"), ("1999ES1", "ZOLLER, KARL")])})
    import contextlib

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        yield http

    monkeypatch.setattr(P, "client", fake_client)
    rows = [row("ROEBUCK TIMOTHY ALAN"), row("SOMEONE ELSE"), row("ROEBUCK TIMOTHY ALAN", county="Aiken")]
    st = asyncio.run(P.enrich_probate_spartan(rows))
    assert st["screened"] == {"probate": ["SC|Greenwood"]}
    assert st["counties"]["Greenwood"]["complete"] and st["counties"]["Greenwood"]["total"] == 2
    assert rows[0].raw["probate_index_match"] and rows[1].raw is None and rows[2].raw is None
    # a second run reads nothing: the complete cache is used
    http.calls.clear()
    st2 = asyncio.run(P.enrich_probate_spartan(rows))
    assert http.calls == [] and st2["screened"] == {"probate": ["SC|Greenwood"]}
    assert st2["counties"]["Greenwood"]["requests"] == 0


def test_a_failed_county_claims_no_screen(monkeypatch):
    http = FakeHttp({0: (1, [])}, fail_after=1)
    import contextlib

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        yield http

    monkeypatch.setattr(P, "client", fake_client)
    st = asyncio.run(P.enrich_probate_spartan([row("A B")]))
    assert st["screened"] == {} and "error" in st["counties"]["Greenwood"]


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(P.ENV, "0")
    assert "skipped" in asyncio.run(P.enrich_probate_spartan([row("A B")]))


def test_ledger_reads_the_probate_screen():
    health = {"sources": [], "enrichments": {"probate_spartan": {"screened": {"probate": ["SC|Greenwood", "SC|Nowhere"]}}}}
    led = SL.build(health)
    assert SL.screened(led, "probate", "SC", "Greenwood") and not SL.screened(led, "probate", "SC", "Aiken")


def test_a_thin_fit_with_a_unique_name_and_no_case_year_is_kept_and_promoted_only_with_a_death_on_the_roll():
    idx = P.DecedentIndex([["2399", "GOVAN, FRANCES"], ["1155", "WISE, BP"], ["1788", "WISE, BP"]])
    live = row("Frances Govan", county="Calhoun")
    P.match_rows([live], {"Calhoun": idx})
    assert live.raw["probate_index_match"][0]["level"] == "given_surname" and "probate" not in live.raw
    dead = row("ESTATE OF Frances Govan", county="Calhoun")
    P.match_rows([dead], {"Calhoun": idx})
    assert dead.raw["probate"]["case_number"] == "2399"
    twin = row("ESTATE OF Bp Wise", county="Calhoun")                  # two decedents with the name: ambiguous
    P.match_rows([twin], {"Calhoun": idx})
    assert twin.raw is None
