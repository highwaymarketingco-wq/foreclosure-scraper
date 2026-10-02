"""Offline tests for the Buncombe/Gaston Aumentum (Cott eSearch v4) ROD parser.

Fixture mirrors the LIVE cpgvInstruments grid (re-captured 2026-07-01): rows are
<tr class="cottPagedGridViewRowStyle">/"cottPagedGridViewAltRowStyle" with 14
direct-child <td> [row#, Date Filed, Index, Type, Grantor, Grantee, Description,
File Number, Book/Page, Ref, Images, GIS, Tax, spacer]. The Grantor/Grantee cells
embed NESTED <table>s (which is why a naive <tr>-regex parser undercounts cells),
and one row has a MASKED date ('**/**/2026', a protected DTH doc) that the parser
must KEEP with recorded_date=None. CI never hits the network.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from foreclosure_scraper.rod import aumentum
from foreclosure_scraper.rod.aumentum import (
    _parse_instruments_grid,
    _is_nod,
    _is_post_sale,
    _split_book_page,
    _parse_date,
    _result_count,
)
from foreclosure_scraper.rod.classify import classify_rod_docs
from foreclosure_scraper.enrichment_aumentum_rod import _owner_doc, _name_parts

# Real-shape fixture: header row + 3 data rows (a Deed of Trust, a Satisfaction,
# and a masked-date protected doc). Grantor/Grantee use nested <table> like live.
SAMPLE = """
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
       class="cottPagedGridView">
  <tr class="cottPagedGridViewHeaderStyle">
    <th>&nbsp;</th><th>Date Filed</th><th>Index</th><th>Type</th><th>Grantor</th>
    <th>Grantee</th><th>Description</th><th>File Number</th><th>Book/Page</th>
    <th>Ref</th><th>Images</th><th>GIS</th><th>Tax</th><th></th>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>1</td>
    <td align="center">11/30/2022<br><span class="StatusDate">Date Filed<br />11/30/2022</span></td>
    <td>CRP</td><td>DEED OF TRUST</td>
    <td><div title='Collapsed'><table width='100%'><tr><td colspan='2'>SMITH, JOHN WESLEY SMITH, DEBORAH L</td></tr></table></td>
    <td><table><tr><td>BANK OF AMERICA</td></tr></table></td>
    <td>LOT 5</td><td>2022012345</td><td>6279 / 1440</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
  <tr class="cottPagedGridViewAltRowStyle">
    <td>3</td><td>12/03/2025</td><td>CRP</td><td>DEED OF TRUST SATISFACTION</td>
    <td><table><tr><td>SMITH, JOHN T./ III SMITH, KATHERINE O.</td></tr></table></td>
    <td><table><tr><td>MORTGAGE ELECTRONIC REGISTRATION SYSTEMS, INC.</td></tr></table></td>
    <td></td><td></td><td>6547 / 1497</td><td>5406 / 1411</td><td>1</td><td></td><td></td><td></td>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>5</td>
    <td align="center">**/**/2026<br><span class="StatusDate">Date Filed<br />**/**/2026</span></td>
    <td>DTH</td><td></td>
    <td><table><tr><td>SMITH, MARK</td></tr></table></td>
    <td><table><tr><td>SMITH, JOHNNIE ROBERT</td></tr></table></td>
    <td></td><td></td><td>113 / 1047</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
</table>
"""


def test_parses_all_three_rows_including_masked_date():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    # Old parser dropped the masked-date row (no MM/DD/YYYY) and broke on nested
    # tables — the rebuilt parser keeps all 3.
    assert len(rows) == 3


def test_nested_table_grantor_and_bookpage_split():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    r0 = rows[0]
    assert r0.grantor and "SMITH, JOHN WESLEY" in r0.grantor   # nested-table cell text
    assert r0.grantee and "BANK OF AMERICA" in r0.grantee
    assert r0.book == "6279" and r0.page == "1440"             # Book/Page split on '/'
    assert r0.instrument_no == "2022012345"                    # File Number column (td7)
    assert r0.recorded_date is not None and r0.recorded_date.year == 2022


def test_masked_date_row_kept_with_none_date():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    masked = [r for r in rows if r.grantor and "SMITH, MARK" in r.grantor]
    assert len(masked) == 1
    assert masked[0].recorded_date is None       # '**/**/2026' -> None, row retained
    assert masked[0].book == "113"               # still carries book/page signal


def test_classify_flags_mortgage():
    docs = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    summ = classify_rod_docs(docs, "aumentum_rod")
    assert summ["instrument_count"] == 3
    assert summ["has_mortgage"] is True          # DEED OF TRUST present
    # Both the DT and the 'DEED OF TRUST SATISFACTION' normalize to the mortgage
    # bucket (longest-key-first match prefers 'DEED OF TRUST'), so >=2 mortgages.
    assert summ["mortgage_count"] >= 2


def test_owner_filter_matches_target_owner():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    last, first = _name_parts("SMITH, JOHN")
    mine = [r for r in rows if _owner_doc(r, last, first)]
    assert len(mine) >= 2   # the DT + the satisfaction both name SMITH, JOHN


def test_gaston_terse_type_codes_parse():
    # Gaston renders terse Type codes (D/T, SAT, S/TR) instead of full words.
    gaston = SAMPLE.replace("DEED OF TRUST SATISFACTION", "SAT").replace("DEED OF TRUST", "D/T")
    rows = _parse_instruments_grid(gaston, "Gaston", "NC")
    assert len(rows) == 3
    summ = classify_rod_docs(rows, "aumentum_rod")
    assert summ["has_mortgage"] is True          # 'D/T' recognised as mortgage
    assert summ["satisfaction_count"] >= 1        # terse 'SAT' code classifies as satisfaction


def test_helpers():
    assert _split_book_page("6279 / 1440") == ("6279", "1440")
    assert _split_book_page("") == (None, None)
    assert _parse_date("**/**/2026") is None
    assert _parse_date("12/03/2025").year == 2025
    assert _is_nod("NOTICE OF SALE") is True
    assert _is_nod("DEED") is False
    assert _is_post_sale("SUBSTITUTE TRUSTEE'S DEED") is True
    assert _is_post_sale("DEED OF TRUST") is False


def test_empty():
    assert _parse_instruments_grid("", "Buncombe", "NC") == []
    assert _parse_instruments_grid("<html><body>no grid</body></html>", "Buncombe", "NC") == []


# --------------------------------------------------------------------------- #
# 2026-10-02 Date-Range sweep fix: 30-day vendor cap + 500-row page cap.      #
# Live-verified root cause (module docstring): the GET/nav/search POST never  #
# had a missing field — the vendor silently bounces a >30-calendar-day search #
# back to the New-Search tab, and a window's own "Your search returned X      #
# results" banner can exceed the grid's 500-row page cap even within a legal  #
# <=29-day-span window (Buncombe: 3,805 results in one real 30-day window).   #
# --------------------------------------------------------------------------- #

def test_result_count_parses_the_real_banner_text():
    html = ('<div class="searchCriteriaSummary">Your search returned <strong>\n'
            '    3,805</strong> results on <strong>10/2/2026</strong></div>')
    assert _result_count(html) == 3805
    assert _result_count("<html>no banner here</html>") is None


def _grid_html(rows: list[tuple[str, str, str]], total: int) -> str:
    """A minimal real-shape cpgvInstruments grid (see SAMPLE above) carrying
    `total` in the "Your search returned" banner and one <tr> per (date,
    book/page, grantor) row — enough for _parse_instruments_grid + the sweep's
    cap-detection to both work against."""
    trs = "".join(
        f'<tr class="cottPagedGridViewRowStyle"><td>1</td><td>{d}</td><td>CRP</td>'
        f'<td>DEED OF TRUST</td><td><table><tr><td>{g}</td></tr></table></td>'
        f'<td><table><tr><td>BANK</td></tr></table></td><td></td><td>{bp.replace("/", "")}</td>'
        f'<td>{bp}</td><td></td><td>1</td><td></td><td></td><td></td></tr>'
        for d, bp, g in rows
    )
    return (
        '<div class="searchCriteriaSummary">Your search returned <strong>\n'
        f'    {total}</strong> results</div>'
        '<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments">'
        f'{trs}</table>'
    )


class _FakeDateSession:
    """Routes _sweep_date_window's POSTs by the (txtFiledFrom, txtFiledThru)
    pair embedded in the body, exactly as aumentum._date_search_body builds
    it — no real network, no curl_cffi."""

    def __init__(self, by_window: dict[tuple[str, str], tuple[int, list[tuple[str, str, str]]]]):
        self.by_window = by_window
        self.calls: list[tuple[str, str]] = []

    async def post(self, url, data, headers, allow_redirects, timeout):
        key = (data[aumentum._P_DATE + "txtFiledFrom"], data[aumentum._P_DATE + "txtFiledThru"])
        self.calls.append(key)
        total, rows = self.by_window.get(key, (0, []))
        return SimpleNamespace(text=_grid_html(rows, total))


def test_sweep_date_window_bisects_a_capped_window_and_keeps_both_halves():
    """A window whose OWN result count is >= the 500-row page cap is the head
    of a longer list — _sweep_date_window must split it rather than accept
    whatever that one page happened to return, down to leaf windows that are
    under the cap."""
    a, b = datetime(2026, 9, 1), datetime(2026, 9, 30)   # span 29, legal per-call
    mid = a + timedelta(days=(b - a).days // 2)          # 2026-09-15
    fmt = "%m/%d/%Y"
    session = _FakeDateSession({
        (a.strftime(fmt), b.strftime(fmt)): (600, [("09/01/2026", "1/1", "DECOY ONE")]),
        (a.strftime(fmt), mid.strftime(fmt)): (2, [("09/02/2026", "100/1", "ALPHA ONE"),
                                                   ("09/03/2026", "100/2", "ALPHA TWO")]),
        ((mid + timedelta(days=1)).strftime(fmt), b.strftime(fmt)):
            (2, [("09/20/2026", "200/1", "BETA ONE"), ("09/21/2026", "200/2", "BETA TWO")]),
    })
    out: list = []
    seen: set = set()
    asyncio.run(aumentum._sweep_date_window(session, "https://x", "Buncombe", "NC", a, b, out, seen))

    # 3 POSTs: the capped top-level window, then its two halves.
    assert len(session.calls) == 3
    names = sorted(d.grantor for d in out)
    assert names == ["ALPHA ONE", "ALPHA TWO", "BETA ONE", "BETA TWO"]
    assert "DECOY ONE" not in names        # the capped page's own rows are discarded, not kept


def test_sweep_date_window_accepts_a_window_under_the_cap_without_bisecting():
    a, b = datetime(2026, 9, 1), datetime(2026, 9, 3)
    fmt = "%m/%d/%Y"
    session = _FakeDateSession({
        (a.strftime(fmt), b.strftime(fmt)): (3, [("09/01/2026", "1/1", "ONE"),
                                                 ("09/02/2026", "1/2", "TWO")]),
    })
    out: list = []
    seen: set = set()
    asyncio.run(aumentum._sweep_date_window(session, "https://x", "Buncombe", "NC", a, b, out, seen))
    assert len(session.calls) == 1         # no bisection: 3 < _RESULTS_PAGE_CAP
    assert sorted(d.grantor for d in out) == ["ONE", "TWO"]


def test_sweep_date_window_dedupes_across_sub_windows():
    """A document straddling a bisection boundary (same book/page/instrument
    seen from two different sub-window POSTs) must be kept once."""
    a, b = datetime(2026, 9, 1), datetime(2026, 9, 2)
    out: list = []
    seen: set = set()
    fmt = "%m/%d/%Y"
    session = _FakeDateSession({
        (a.strftime(fmt), b.strftime(fmt)): (1, [("09/01/2026", "9/9", "DUP")]),
    })
    asyncio.run(aumentum._sweep_date_window(session, "https://x", "Buncombe", "NC", a, b, out, seen))
    asyncio.run(aumentum._sweep_date_window(session, "https://x", "Buncombe", "NC", a, b, out, seen))
    assert len(out) == 1


def test_date_swept_docs_at_raw_row_cap_none_scans_the_full_window(monkeypatch):
    """2026-10-02 regression: passing a small raw_row_cap (the OLD max_docs*6
    behavior) could early-exit after the FIRST ~29-day chunk's recursive
    bisection alone (hundreds of rows from just a few calendar days), silently
    returning a biased sample that happened to contain zero NOD-type docs even
    though real ones existed later in the window. raw_row_cap=None must sweep
    every top-level chunk regardless of how many raw rows the first one had."""
    windows_seen: list[tuple] = []

    async def fake_sweep(session, date_url, county, state, a, b, out, seen):
        windows_seen.append((a.date(), b.date()))
        out.append(object())  # one row per window call, just to prove it ran

    monkeypatch.setattr(aumentum, "_sweep_date_window", fake_sweep)

    class _FakeResp:
        def __init__(self, url=""):
            self.url = url
            self.text = ""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _FakeResp(url)

        async def post(self, url, **kw):
            return _FakeResp(url)

    monkeypatch.setattr(
        "curl_cffi.requests.AsyncSession", lambda **kw: _FakeSession())

    out = asyncio.run(aumentum._date_swept_docs_at(
        "https://x", "Buncombe", "NC", days_back=60, raw_row_cap=None))

    # 60 days / 29-day-span chunks = 3 top-level windows (29 + 29 + 2), and
    # EVERY one of them must have been swept, not just the first.
    assert len(windows_seen) == 3
    assert len(out) == 3


def test_date_swept_docs_at_raw_row_cap_stops_early(monkeypatch):
    """cash_buyer_deeds.py's use case: an early-stop sample of ANY doc type is
    fine (deed/DOT rows are common), so raw_row_cap=N must still short-circuit
    once N raw rows are collected — this is the ONE caller that wants that."""
    call_count = {"n": 0}

    async def fake_sweep(session, date_url, county, state, a, b, out, seen):
        call_count["n"] += 1
        out.extend([object(), object(), object()])  # 3 rows per window

    monkeypatch.setattr(aumentum, "_sweep_date_window", fake_sweep)

    class _FakeResp:
        def __init__(self, url=""):
            self.url = url
            self.text = ""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _FakeResp(url)

        async def post(self, url, **kw):
            return _FakeResp(url)

    monkeypatch.setattr(
        "curl_cffi.requests.AsyncSession", lambda **kw: _FakeSession())

    out = asyncio.run(aumentum._date_swept_docs_at(
        "https://x", "Buncombe", "NC", days_back=60, raw_row_cap=5))

    assert call_count["n"] == 2            # stops after the 2nd window (3, then 6 >= 5)
    assert len(out) == 5                   # sliced to the cap
