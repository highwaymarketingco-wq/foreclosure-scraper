"""CCHS classic-ASP deed-index sweep (rod/cchs.py).

FIXTURES. cchs_doctypes_burke.html and cchs_doctypes_lincoln.html are the real
kind dictionaries, trimmed, captured 2026-09-20. cchs_search_cloudflare_403.html
is the real reply to the search that day: a Cloudflare 403 challenge, which is
why cchs_loss_deed_rows_synthetic.xml is SYNTHETIC (real tag layout, placeholder
names). The multi-party row layout it assumes is verified by the parser being
indifferent to it (see test_party_layout_does_not_change_the_result).

No network: the shared client is replaced by a fake that records every URL.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from foreclosure_scraper.rod import cchs
from foreclosure_scraper.rod import inst_class as ic

FIX = Path(__file__).parent / "fixtures"
BURKE_PAGE = (FIX / "cchs_doctypes_burke.html").read_text()
LINCOLN_PAGE = (FIX / "cchs_doctypes_lincoln.html").read_text()
ROWS_XML = (FIX / "cchs_loss_deed_rows_synthetic.xml").read_text()
CLOUDFLARE_403 = (FIX / "cchs_search_cloudflare_403.html").read_text()


# --- fake transport -----------------------------------------------------------------
class _Resp:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text


class _FakeClient:
    def __init__(self, router):
        self.router = router
        self.calls: list[str] = []

    async def get(self, url, **kw):
        self.calls.append(url)
        return self.router(url)

    @property
    def searches(self):
        return [u for u in self.calls if "cmd=search" in u]

    @property
    def getalls(self):
        return [u for u in self.calls if "cmd=getall" in u]


def _install(monkeypatch, router) -> _FakeClient:
    fake = _FakeClient(router)

    @contextlib.asynccontextmanager
    async def factory(**kw):
        yield fake

    monkeypatch.setattr(cchs, "client", factory)
    return fake


def _search_reply(rows: int, docs: int) -> str:
    return f"<SearchResponse><recordcount>{rows}</recordcount><doccount>{docs}</doccount></SearchResponse>"


def _loss_only(xml: str) -> str:
    """The fixture without its deed-of-trust document."""
    return re.sub(r"<r>(?:(?!</r>).)*<ki><!\[CDATA\[D/T\]\]></ki>.*?</r>\n?", "", xml, flags=re.S)


def _router(page=BURKE_PAGE, by_year=None, rows_xml=None):
    """A well-behaved CCHS: 200 bootstrap pages, then per-year search/getall."""
    by_year = by_year if by_year is not None else {2025: (8, 4)}
    rows_xml = rows_xml if rows_xml is not None else _loss_only(ROWS_XML)

    def route(url):
        if "SearchService.asp" not in url:
            return _Resp(200, page if url.endswith("realestatesearch.asp") else "<html>ok</html>")
        q = parse_qs(urlparse(url).query)
        if q["cmd"] == ["search"]:
            year = int(q["fromdate"][0][-4:])
            rows, docs = by_year.get(year, (0, 0))
            return _Resp(200, _search_reply(rows, docs))
        return _Resp(200, rows_xml)

    return route


def _sweep(state="NC", county="Burke", start=date(2025, 1, 1), end=date(2025, 12, 31), **kw):
    return asyncio.run(cchs.sweep_loss_instruments(state, county, start, end, **kw))


# --- the kind dictionary (real pages) ---------------------------------------------------
def test_parse_doctypes_reads_real_burke_blocks_and_unescapes_apostrophes():
    dt = cchs.parse_doctypes(BURKE_PAGE)
    assert ("REAL ESTATE", "COM/D", "COMMISSIONER'S DEED") in dt
    assert ("REAL ESTATE", "TR/D", "TRUSTEES DEED") in dt
    assert ("REAL ESTATE", "SHF/D", "SHERIFF DEED") in dt
    assert ("UCC", "UCCSTD", "STANDARD UCC FILING") in dt
    assert len(dt) == 14


def test_burke_dictionary_yields_exactly_the_three_loss_kinds():
    kinds = cchs.dictionary_loss_kinds(cchs.parse_doctypes(BURKE_PAGE))
    assert set(kinds) == {"COM/D", "SHF/D", "TR/D"}
    # Real neighbours that look close and must not be picked: a pre-sale
    # substitution, a commission, an old-format trustee deed, a deed of trust.
    for not_a_loss in ("SUBST TR", "S/TR", "COMM", "TR-DEED", "D/T", "REL/D", "QCD"):
        assert not_a_loss not in kinds


def test_lincoln_spells_names_without_apostrophes_and_still_matches():
    dt = cchs.parse_doctypes(LINCOLN_PAGE)
    assert ("DEED", "COM/D", "COMMISSIONERS DEED") in dt
    kinds = cchs.dictionary_loss_kinds(dt)
    assert set(kinds) == {"COM/D", "SHF/D", "TR/D"}
    assert "R/COM" not in kinds            # REPORT OF COMMISSIONERS is not a deed


def test_a_page_with_no_dictionary_parses_to_nothing():
    assert cchs.parse_doctypes("<html>Just a moment...</html>") == []
    assert cchs.dictionary_loss_kinds([]) == ()


# --- finding F4: the sold-recordings kind list ---------------------------------------------
def test_sold_types_are_real_kinds_and_include_the_trustees_deed():
    assert cchs._SOLD_TYPES == "TR/D,COM/D,SHF/D"
    for phantom in ("FORECLOSURE DEED", "SUBTRUSTEE DEED", "TRUSTEE"):
        assert phantom not in cchs._SOLD_TYPES.split(",")


def test_cleveland_adds_its_own_spellings_and_others_do_not():
    assert cchs.loss_kinds("NC", "Burke") == ("TR/D", "COM/D", "SHF/D")
    assert cchs.loss_kinds("NC", "Lincoln") == ("TR/D", "COM/D", "SHF/D")
    cle = cchs.loss_kinds("NC", "Cleveland")
    assert set(cle) >= {"TR/D", "COM/D", "SHF/D", "TR/DEED", "COMM/D", "COMM/DEED", "SHERIFFS DEED"}


def test_discover_recent_sold_recordings_asks_for_the_trustees_deed(monkeypatch):
    seen = {}

    async def fake_fetch(state, county, instrument_types, *a, **kw):
        seen[county] = instrument_types
        return []

    monkeypatch.setattr(cchs, "_cchs_fetch", fake_fetch)
    asyncio.run(cchs.discover_recent_sold_recordings("NC", "Burke"))
    asyncio.run(cchs.discover_recent_sold_recordings("NC", "Cleveland"))
    assert seen["Burke"].split(",") == ["TR/D", "COM/D", "SHF/D"]
    assert "TR/DEED" in seen["Cleveland"].split(",")


def test_post_sale_predicate_now_knows_the_vendor_codes():
    for ki in ("TR/D", "COM/D", "SHF/D", "TR/DEED", "SHERIFFS DEED"):
        assert cchs._is_post_sale(ki, ki), ki
    for ki in ("D/T", "S/TR", "FCL", "QCD", "DEED"):
        assert not cchs._is_post_sale(ki, ki), ki


def test_parse_rows_keeps_every_party_of_a_document_in_raw():
    docs = {d.instrument_no: d for d in cchs._parse_rows(ROWS_XML, "NC", "Burke", sold=True)}
    assert len(docs) == 5                                       # 9 party rows, 5 documents
    tr = docs["2025000101"]
    assert tr.doc_type == "TR/D"                                # vendor code, unchanged
    assert tr.grantor == "PLACEHOLDER TRUSTEE SERVICES PLLC"   # first row, as before
    assert tr.raw["grantors"] == ["PLACEHOLDER TRUSTEE SERVICES PLLC", "DOE JOHN", "DOE JANE"]
    assert tr.raw["grantees"] == ["EXAMPLE MORTGAGE HOLDINGS LLC"]
    assert tr.raw["ki"] == "TR/D"
    assert tr.excise_tax_stamp == 135.0 and tr.consideration_amount == 67500.0


# --- collapsing party rows into documents ---------------------------------------------------
def test_party_rows_collapse_to_one_instrument_per_document():
    docs = {d.instrument_no: d for d in cchs.collapse_documents(ROWS_XML, "NC", "Burke")}
    assert len(docs) == 5
    tr = docs["2025000101"]
    assert (tr.inst_code, tr.inst_class) == ("TR/D", ic.TRUSTEE_DEED)
    assert tr.recorded_date == "2025-03-14"
    assert (tr.book, tr.page, tr.parcel_id) == ("9001", "101", "9-1000001")
    assert tr.grantors == ["PLACEHOLDER TRUSTEE SERVICES PLLC", "DOE JOHN Q", "DOE JANE R"]
    assert tr.grantees == ["EXAMPLE MORTGAGE HOLDINGS LLC"]      # repeated on 3 rows, kept once
    assert tr.excise_stamp == 135.0
    assert tr.description == "8123/456"
    assert tr.loss_kind == "mortgage_foreclosure"
    assert tr.loser_names == ["DOE JOHN Q", "DOE JANE R"]        # not the law firm
    assert tr.source == "cchs_classic" and tr.county == "Burke" and tr.state == "NC"


def test_the_officer_flagged_by_the_comm_suffix_is_not_a_loser():
    com = {d.instrument_no: d for d in cchs.collapse_documents(ROWS_XML, "NC", "Burke")}["2025000240"]
    assert com.inst_class == ic.COMMISSIONER_DEED
    assert com.grantors == ["ROE RICHARD T", "SAMPLE ALEX B"]
    assert com.grantees == ["EXAMPLE COUNTY"]
    assert com.loss_kind == "tax_foreclosure"
    assert com.loser_names == ["SAMPLE ALEX B"]


def test_a_served_zero_stamp_stays_zero_not_missing():
    sh = {d.instrument_no: d for d in cchs.collapse_documents(ROWS_XML, "NC", "Burke")}["2025000377"]
    assert sh.inst_class == ic.SHERIFF_DEED and sh.excise_stamp == 0.0
    assert sh.loser_names == ["SPECIMEN CHRIS"]


def test_a_trustee_deed_with_only_a_trust_grantor_names_nobody():
    tr = {d.instrument_no: d for d in cchs.collapse_documents(ROWS_XML, "NC", "Burke")}["2025000512"]
    assert tr.inst_class == ic.TRUSTEE_DEED
    assert (tr.loss_kind, tr.loser_names) == ("unknown", [])


def test_the_deed_of_trust_is_classified_other():
    dot = {d.instrument_no: d for d in cchs.collapse_documents(ROWS_XML, "NC", "Burke")}["2025000410"]
    assert dot.inst_class == ic.OTHER and dot.loser_names == []


def test_party_layout_does_not_change_the_result():
    """Vendor layout is unverified. Give the grantee on the FIRST row only, then
    on every row: the collapsed documents must be identical."""
    every = ROWS_XML
    first_only = re.sub(
        r"(<r><sn>[23]</sn>.*?)<ee><!\[CDATA\[EXAMPLE MORTGAGE HOLDINGS LLC\]\]></ee>",
        r"\1<ee></ee>", ROWS_XML, flags=re.S)
    assert first_only != every

    def key(docs):
        return sorted((d.doc_key, d.grantors, d.grantees, d.loser_names) for d in docs)

    assert key(cchs.collapse_documents(first_only, "NC", "Burke")) == \
        key(cchs.collapse_documents(every, "NC", "Burke"))


def test_a_reply_with_no_rows_collapses_to_nothing():
    assert cchs.collapse_documents("", "NC", "Burke") == []
    assert cchs.collapse_documents(_search_reply(0, 0), "NC", "Burke") == []


# --- the sweep ------------------------------------------------------------------------------
def test_sweep_reads_the_dictionary_and_collapses_a_year(monkeypatch):
    fake = _install(monkeypatch, _router())
    res = _sweep()
    assert res.walled is None and res.problems == []
    assert res.kinds_source == "dictionary" and set(res.kinds) == {"COM/D", "SHF/D", "TR/D"}
    assert res.rows == 8 and res.windows == 1
    assert sorted(d.instrument_no for d in res.instruments) == \
        ["2025000101", "2025000240", "2025000377", "2025000512"]
    # 3 bootstrap pages, then one search and one getall for the year.
    assert res.requests == 5 and len(fake.calls) == 5
    q = parse_qs(urlparse(fake.searches[0]).query)
    assert q["fromdate"] == ["01/01/2025"] and q["todate"] == ["12/31/2025"]
    assert set(q["instrumenttypes"][0].split(",")) == {"COM/D", "SHF/D", "TR/D"}
    assert q["rangetype"] == ["doc"] and q["maxrecordcount"] == [str(cchs.CCHS_MAX_ROWS)]


def test_an_empty_year_costs_one_search_and_no_getall(monkeypatch):
    fake = _install(monkeypatch, _router(by_year={}))
    res = _sweep()
    assert res.instruments == [] and res.problems == [] and res.windows == 0
    assert len(fake.searches) == 1 and fake.getalls == []


def test_sweep_runs_one_search_window_per_year(monkeypatch):
    fake = _install(monkeypatch, _router(by_year={}))
    _sweep(start=date(2023, 6, 15), end=date(2025, 2, 10))
    windows = [(parse_qs(urlparse(u).query)["fromdate"][0], parse_qs(urlparse(u).query)["todate"][0])
               for u in fake.searches]
    assert windows == [("06/15/2023", "12/31/2023"), ("01/01/2024", "12/31/2024"),
                       ("01/01/2025", "02/10/2025")]


def test_a_403_challenge_on_the_search_stops_the_host_and_is_not_read_as_no_records(monkeypatch):
    """The real 2026-09-20 reply, served after three normal 200 bootstrap pages."""
    def route(url):
        if "SearchService.asp" in url:
            return _Resp(403, CLOUDFLARE_403)
        return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")

    fake = _install(monkeypatch, route)
    res = _sweep(start=date(2020, 1, 1), end=date(2025, 12, 31))
    assert res.walled and "403" in res.walled and "us5.courthousecomputersystems.com" in res.walled
    assert res.instruments == []
    # Three bootstrap pages and ONE search. No retry, no second window, no getall.
    assert len(fake.calls) == 4 and len(fake.searches) == 1 and fake.getalls == []


def test_a_200_page_titled_just_a_moment_is_a_wall_too(monkeypatch):
    def route(url):
        if "SearchService.asp" in url:
            return _Resp(200, CLOUDFLARE_403)          # same page, but a 200
        return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")

    _install(monkeypatch, route)
    res = _sweep()
    assert res.walled and "challenge" in res.walled


def test_a_wall_on_the_bootstrap_stops_before_any_search(monkeypatch):
    def route(url):
        return _Resp(403, CLOUDFLARE_403)

    fake = _install(monkeypatch, route)
    res = _sweep()
    assert res.walled and len(fake.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_every_blocking_status_is_a_wall(monkeypatch, status):
    def route(url):
        if "SearchService.asp" in url:
            return _Resp(status, "")
        return _Resp(200, BURKE_PAGE)

    _install(monkeypatch, route)
    assert _sweep().walled == f"us5.courthousecomputersystems.com search 2025-01-01..2025-12-31: HTTP {status}"


def test_the_normal_bootstrap_pages_are_not_mistaken_for_a_wall():
    """The real Burke page embeds Cloudflare's passive jsd script. That is not a challenge."""
    assert cchs._wall_reason(200, BURKE_PAGE) is None
    assert cchs._wall_reason(200, "<title>Burke County, NC</title>") is None
    assert cchs._wall_reason(200, "<title>Please Log In</title>") == "challenge, CAPTCHA or login page"
    assert cchs._wall_reason(200, '<div class="g-recaptcha" data-sitekey="x"></div>')


def _one_row_xml() -> str:
    first = re.search(r"<r>.*?</r>", ROWS_XML, re.S).group(0)
    return f"<GetPageResponse><PageResults>{first}</PageResults></GetPageResponse>"


def _parse_us(d: str) -> date:
    return date(int(d[6:]), int(d[:2]), int(d[3:5]))


def test_a_window_at_the_row_cap_is_split_until_it_fits(monkeypatch):
    """A reply at the cap may be the head of a longer list, never a complete answer."""
    cap = 4
    windows = []

    def route(url):
        if "SearchService.asp" not in url:
            return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")
        q = parse_qs(urlparse(url).query)
        if q["cmd"] == ["getall"]:
            return _Resp(200, _one_row_xml())
        a, b = _parse_us(q["fromdate"][0]), _parse_us(q["todate"][0])
        windows.append((a, b))
        # anything wider than 100 days is "at the cap"; narrower holds one row
        return _Resp(200, _search_reply(cap if (b - a).days > 100 else 1, 1))

    fake = _install(monkeypatch, route)
    res = _sweep(max_rows=cap)
    assert windows[0] == (date(2025, 1, 1), date(2025, 12, 31))
    leaves = sorted(w for w in windows if (w[1] - w[0]).days <= 100)
    assert len(leaves) == 4 and res.windows == 4 and len(fake.getalls) == 4
    # the leaves tile the year: no gap and no overlap
    assert leaves[0][0] == date(2025, 1, 1) and leaves[-1][1] == date(2025, 12, 31)
    for (_, prev_end), (nxt_start, _) in zip(leaves, leaves[1:]):
        assert (nxt_start - prev_end).days == 1
    assert res.truncated == []


def test_a_single_day_at_the_cap_is_reported_as_truncated(monkeypatch):
    def route(url):
        if "SearchService.asp" not in url:
            return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")
        q = parse_qs(urlparse(url).query)
        if q["cmd"] == ["search"]:
            return _Resp(200, _search_reply(8, 4))               # always at the cap of 8
        return _Resp(200, _loss_only(ROWS_XML))

    _install(monkeypatch, route)
    res = _sweep(start=date(2025, 3, 14), end=date(2025, 3, 14), max_rows=8)
    assert res.truncated == ["2025-03-14..2025-03-14"]


def test_a_short_getall_page_narrows_the_window_instead_of_being_accepted(monkeypatch):
    calls = {"getall": 0}

    def route(url):
        if "SearchService.asp" not in url:
            return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")
        q = parse_qs(urlparse(url).query)
        if q["cmd"] == ["search"]:
            wide = q["fromdate"][0] == "01/01/2025" and q["todate"][0] == "12/31/2025"
            return _Resp(200, _search_reply(8 if wide else 0, 4))
        calls["getall"] += 1
        return _Resp(200, "<GetPageResponse><PageResults><r><bk>1</bk></r></PageResults></GetPageResponse>")

    fake = _install(monkeypatch, route)
    res = _sweep()
    assert calls["getall"] == 1                     # asked for 8 rows, got 1: split, nothing kept
    assert res.instruments == [] and len(fake.searches) == 3


def test_a_search_reply_without_recordcount_is_a_problem_not_zero_rows(monkeypatch):
    def route(url):
        if "SearchService.asp" in url:
            return _Resp(200, "<html><body>Service temporarily unavailable</body></html>")
        return _Resp(200, BURKE_PAGE if url.endswith("realestatesearch.asp") else "<html>ok</html>")

    _install(monkeypatch, route)
    res = _sweep()
    assert res.instruments == [] and res.walled is None
    assert len(res.problems) == 1 and "no <recordcount>" in res.problems[0]


def test_a_doccount_that_disagrees_with_the_collapsed_documents_is_a_problem(monkeypatch):
    _install(monkeypatch, _router(by_year={2025: (8, 9)}))       # says 9 documents, rows hold 4
    res = _sweep()
    assert any("<doccount> 9 but 4 documents" in p for p in res.problems)
    assert len(res.instruments) == 4


def test_documents_of_the_wrong_kind_are_dropped_and_counted(monkeypatch):
    _install(monkeypatch, _router(by_year={2025: (9, 5)}, rows_xml=ROWS_XML))   # D/T included
    res = _sweep()
    assert len(res.instruments) == 4
    assert any("1 of 5 documents were not loss kinds" in p for p in res.problems)


def test_a_page_without_a_dictionary_falls_back_to_the_static_kinds_and_says_so(monkeypatch):
    _install(monkeypatch, _router(page="<html>no dictionary here</html>"))
    res = _sweep(county="Cleveland")
    assert res.kinds_source == "static"
    assert "TR/DEED" in res.kinds and "TR/D" in res.kinds
    assert any("no kind dictionary" in p for p in res.problems)


def test_the_same_document_twice_is_stored_once(monkeypatch):
    _install(monkeypatch, _router(by_year={2024: (8, 4), 2025: (8, 4)}))
    res = _sweep(start=date(2024, 1, 1), end=date(2025, 12, 31))
    assert res.windows == 2 and len(res.instruments) == 4


def test_a_county_that_is_not_a_cchs_classic_install_is_reported():
    res = _sweep(county="Buncombe")
    assert res.instruments == [] and "not a CCHS classic-ASP county" in res.problems[0]


def test_a_transport_error_is_reported_not_swallowed_as_zero_rows(monkeypatch):
    def route(url):
        raise ConnectionError("reset by peer")

    _install(monkeypatch, route)
    res = _sweep()
    assert res.instruments == [] and "ConnectionError" in res.problems[0]


# --- what the F4 fix now feeds into the sold-recordings scraper --------------------------------
def test_sold_listing_names_the_borrower_not_the_foreclosing_law_firm():
    """The post-sale sweep now returns trustee's deeds, and doc.grantor is the first
    party row, which is usually the law firm."""
    from foreclosure_scraper.scrapers.counties_nc.nc_rod_substitute_trustee import _sold_doc_to_listing

    docs = {d.instrument_no: d for d in cchs._parse_rows(ROWS_XML, "NC", "Burke", sold=True)}
    tr = docs["2025000101"]
    assert tr.grantor == "PLACEHOLDER TRUSTEE SERVICES PLLC"
    li = _sold_doc_to_listing(tr, "cchs")
    assert li.defendant == "DOE JOHN" and li.plaintiff == "EXAMPLE MORTGAGE HOLDINGS LLC"
    assert li.opening_bid == 67500.0 and li.raw["actual_sold_price"] == 67500.0
    # a trust as the only grantor names nobody: the grantor as served is kept
    trust = docs["2025000512"]
    assert _sold_doc_to_listing(trust, "cchs").defendant == "SAMPLE FAMILY LIVING TRUST"
