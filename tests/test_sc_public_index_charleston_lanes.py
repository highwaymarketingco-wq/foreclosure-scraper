"""Charleston's copy of the SC Public Index: case-type lanes (2026-10-07).

Hand-written fixtures: every name and case number below is made up. The grid
shape (10 headed columns, one row per party, title="<plaintiff> VS <defendant>")
follows the state Public Index SearchResults grid recorded in
counties_sc/sc_public_index.py.
"""
from __future__ import annotations

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national import sc_public_index as mod

_HEAD = """
<tr>
  <th>Name</th><th>Party Type</th><th>Case Number</th><th>Filed Date</th>
  <th>Case Status</th><th>Disposition Date</th><th>Type</th><th>Subtype</th>
  <th>Judgment #</th><th>Court Agency</th>
</tr>
"""


def _row(name, role, case, title, subtype, judg="", ctype="Common Pleas", cls="standardRow",
         status="Pending", disposed=""):
    return (f'<tr class="{cls}"><td>{name}</td><td>{role}</td>'
            f'<td title="{title}"><a>{case}</a></td><td>05/01/2026</td><td>{status}</td>'
            f"<td>{disposed}</td><td>{ctype}</td><td>{subtype}</td><td>{judg}</td>"
            f"<td>Common Pleas</td></tr>")


GRID = (
    '<html><body><table id="ContentPlaceHolder1_SearchResults">' + _HEAD
    # foreclosure: plaintiff row first, defendant row second (defendant must win)
    + _row("Sample Bank NA", "Plaintiff", "2026CP1000101",
           "SAMPLE BANK NA VS Owner Alpha, defendant, et al", "Foreclosure 420")
    + _row("Owner Alpha", "Defendant", "2026CP1000101",
           "SAMPLE BANK NA VS Owner Alpha, defendant, et al", "Foreclosure 420", cls="altRow")
    + _row("Heir Bravo", "Defendant", "2026CP1000102", "Heir Charlie VS Heir Bravo", "Partition 440")
    + _row("Claimant Delta", "Plaintiff", "2026CP1000103", "Claimant Delta VS Unknown Heirs",
           "Quiet Title")
    + _row("Debtor Echo", "Defendant", "2026CP1000104", "SAMPLE CREDIT LLC VS Debtor Echo",
           "Transcript Judgment 540", judg="2026JG1000001")
    + _row("Driver Foxtrot", "Defendant", "2026CP1000105", "Rider Golf VS Driver Foxtrot",
           "Auto 210")
    # dropped: eviction (names the tenant), minor's settlement (names a minor),
    # and a non-Common-Pleas case number
    + _row("Tenant Hotel", "Defendant", "2026CP1000106", "SAMPLE RENTALS VS Tenant Hotel",
           "Possession 450")
    + _row("Guardian India", "Plaintiff", "2026CP1000107", "Guardian India VS Insurer Juliet",
           "Minor Settlement 530")
    + _row("Person Kilo", "Defendant", "2026GS1000108", "State VS Person Kilo", "Other",
           ctype="General Sessions")
    + "</table></body></html>"
)


def _by_case(rows):
    return {r["case_number"]: r for r in rows}


def test_lane_labels():
    assert mod.charleston_lane("Foreclosure 420") == "foreclosure"
    assert mod.charleston_lane("Partition 440") == "partition"
    assert mod.charleston_lane("Quiet Title") == "quiet_title"
    assert mod.charleston_lane("Adverse Possession") == "quiet_title"
    assert mod.charleston_lane("Lis Pendens 550") == "lis_pendens"
    for j in ("Transcript Judgment 540", "Foreign Judgment 510",
              "Magistrate's Judgment 520", "Confession of Judgment 570"):
        assert mod.charleston_lane(j) == "judgment"
    assert mod.charleston_lane("Auto 210") == "other"
    assert mod.charleston_lane("", "") is None


def test_skips_evictions_minors_and_sealed():
    assert mod.charleston_skip("Possession 450")
    assert mod.charleston_skip("Minor Settlement 530")
    assert mod.charleston_skip("Sealed")
    assert not mod.charleston_skip("Adverse Possession")
    assert not mod.charleston_skip("Partition 440")
    assert not mod.charleston_skip("Transcript Judgment 540")


def test_parse_grid_lanes_and_drops():
    rows = mod._dedupe_prefer_defendant(mod._parse_charleston_results(GRID))
    by = _by_case(rows)
    assert sorted(by) == ["2026CP1000101", "2026CP1000102", "2026CP1000103",
                          "2026CP1000104", "2026CP1000105"]
    assert {c: r["lane"] for c, r in by.items()} == {
        "2026CP1000101": "foreclosure", "2026CP1000102": "partition",
        "2026CP1000103": "quiet_title", "2026CP1000104": "judgment",
        "2026CP1000105": "other",
    }
    fc = by["2026CP1000101"]
    assert fc["role"] == "Defendant" and fc["name"] == "Owner Alpha"
    assert fc["plaintiff"] == "SAMPLE BANK NA" and fc["defendant"] == "Owner Alpha"
    assert by["2026CP1000104"]["judgment_number"] == "2026JG1000001"


def test_listings_judgment_is_a_judgment_lien_lead():
    scraper = mod.SCPublicIndexScraper()
    rows = mod._dedupe_prefer_defendant(mod._parse_charleston_results(GRID))
    for r in rows:
        r["_county"] = "charleston"
    lis = {li.case_number: li for li in scraper._to_listings(rows)}
    j = lis["2026CP1000104"]
    assert j.source == mod.JUDGMENT_LIEN_SOURCE
    assert j.listing_type == ListingType.DISTRESSED
    assert j.defendant == "Debtor Echo" and j.county == "Charleston"
    names = [s[0] for s in ds._signals_for(j)]
    assert "judgment_lien" in names and "distressed" not in names
    assert main._active_only(j, 120)  # dateless, kept by the prefix whitelist
    for cn in ("2026CP1000101", "2026CP1000102", "2026CP1000103", "2026CP1000105"):
        li = lis[cn]
        assert li.source == "national.sc_public_index"
        assert li.listing_type == ListingType.LIS_PENDENS
        assert li.raw["sc_public_index"]["lane"] == mod.charleston_lane(
            li.raw["sc_public_index"]["subtype"])


def test_unknown_layout_falls_back_to_the_positional_parser():
    html = ("<html><body><table><tr><td>a</td></tr><tr><td>b</td></tr>"
            "<tr><td>Owner Lima</td><td>Defendant</td><td>2026CP1000109</td>"
            "<td>05/01/2026</td><td>Pending</td><td></td></tr></table></body></html>")
    assert mod._parse_charleston_results(html) == mod._parse_search_results(html)
    rec = mod._parse_charleston_results(html)[0]
    assert "lane" not in rec


def test_other_counties_rows_convert_exactly_as_before():
    """A record from the other counties' path (no lane keys) gives the same row as
    before this change: same source, type, raw block, no party fields."""
    case = {"name": "Owner Mike", "role": "Defendant", "case_number": "2026CP4200110",
            "date_filed": "05/01/2026", "status": "Pending", "date_disposed": "",
            "_county": "spartanburg"}
    li = mod.SCPublicIndexScraper()._to_listings([case])[0]
    assert li.source == "national.sc_public_index"
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.plaintiff is None and li.defendant is None
    assert li.raw == {"sc_public_index": {
        "name": "Owner Mike", "role": "Defendant", "case_number": "2026CP4200110",
        "date_filed": "05/01/2026", "status": "Pending", "date_disposed": "",
        "court": "SC Common Pleas", "source": "publicindex.sccourts.org"}}


# --------------------------------------------------------------------------- #
# The Charleston pass end to end against a fake session (no network): 'other'
# cases are counted, not emitted; dropped party rows and headers are recorded.
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class _FakeCurlSession:
    HIDDEN = '<input type="hidden" name="__VIEWSTATE" value="x" />'

    def __init__(self, *a, **k):
        self.posts = 0

    def get(self, url, **k):
        return _Resp("<html><body>" + self.HIDDEN + "</body></html>")

    def post(self, url, data=None, **k):
        self.posts += 1
        if url.endswith("PISearch.aspx"):
            return _Resp(GRID.replace("<html><body>", "<html><body>" + self.HIDDEN))
        return _Resp("<html><body>" + self.HIDDEN + "</body></html>")


def test_charleston_pass_counts_other_and_does_not_emit_it(monkeypatch):
    import asyncio

    import curl_cffi.requests as cf

    monkeypatch.setattr(cf, "Session", _FakeCurlSession)
    monkeypatch.setattr(mod, "REQUEST_DELAY", 0)
    monkeypatch.setattr(mod, "SEARCH_PREFIXES", ["A"])
    rows = asyncio.run(mod._curl_search_county("charleston"))
    assert sorted(r["lane"] for r in rows) == ["foreclosure", "judgment", "partition", "quiet_title"]
    st = mod.LAST_CHARLESTON_STATS
    assert st["cases"] == 5 and st["other_not_emitted"] == 1 and st["emitted"] == 4
    assert st["not_lead_by_lane"] == {"other": 1}
    assert st["search"]["mode"] == "letters" and st["form"] == {"date_filter": False}
    assert st["lanes"] == {"foreclosure": 1, "partition": 1, "quiet_title": 1,
                           "judgment": 1, "other": 1}
    assert st["dropped_party_rows"] == 2  # the eviction and the minor's settlement
    assert "subtype" in st["headers"] and "judgment #" in st["headers"]


def test_headers_match_the_ten_live_labels_exactly():
    st: dict = {}
    mod._parse_charleston_results(GRID, st)
    assert tuple(st["headers"]) == mod.CHARLESTON_HEADERS
    # a variant label is not guessed at: "Case #" means an unknown layout -> the
    # positional fallback, rows without a lane (today's behaviour)
    html = GRID.replace("<th>Case Number</th>", "<th>Case #</th>")
    assert all("lane" not in r for r in mod._parse_charleston_results(html))
    # a missing Subtype label leaves the case unlabeled rather than reading another column
    html = GRID.replace("<th>Subtype</th>", "<th>Sub Type</th>")
    assert {r["lane"] for r in mod._parse_charleston_results(html)} == {""}


from datetime import date, timedelta  # noqa: E402

TODAY = date(2026, 10, 7)
_RECENT = (date.today() - timedelta(days=60)).strftime("%m/%d/%Y")   # within 9 months of the run
_OLD = (date.today() - timedelta(days=400)).strftime("%m/%d/%Y")     # beyond it

CLOSED_GRID = (
    '<html><body><table id="ContentPlaceHolder1_SearchResults">' + _HEAD
    # foreclosure disposed recently, not dismissed: judgment entered, sale ahead -> lead
    + _row("Owner November", "Defendant", "2023CP1000201", "SAMPLE BANK VS Owner November",
           "Foreclosure 420", status="Disposed", disposed=_RECENT)
    + _row("Owner Oscar", "Defendant", "2026CP1000202", "SAMPLE BANK VS Owner Oscar",
           "Foreclosure 420", status="Dismissed", disposed=_RECENT)
    + _row("Owner Papa", "Defendant", "2026CP1000203", "SAMPLE BANK VS Owner Papa",
           "Foreclosure 420")
    + _row("Debtor Quebec", "Defendant", "2026CP1000204", "SAMPLE CREDIT VS Debtor Quebec",
           "Transcript Judgment 540", status="Judgment Entered", disposed="06/01/2026")
    + _row("Debtor Romeo", "Defendant", "2026CP1000205", "SAMPLE CREDIT VS Debtor Romeo",
           "Confession of Judgment 570", status="Satisfied", disposed="06/02/2026")
    + _row("Heir Sierra", "Defendant", "2026CP1000206", "Heir Tango VS Heir Sierra",
           "Partition 440", status="Closed")
    + _row("Owner Victor", "Defendant", "2025CP1000207", "SAMPLE BANK VS Owner Victor",
           "Foreclosure 420", status="Judgment", disposed=_OLD)
    + _row("Owner Whiskey", "Defendant", "2026CP1000208", "SAMPLE BANK VS Owner Whiskey",
           "Foreclosure 420", status="Settled", disposed=_RECENT)
    + "</table></body></html>"
)


def test_lead_rules_per_lane():
    def lead(**kw):
        return mod.case_lead({"status": "Pending", "date_disposed": "", **kw}, TODAY)
    assert lead(lane="foreclosure") == (True, False)
    assert lead(lane="foreclosure", status="Referred To Master") == (True, False)
    assert lead(lane="foreclosure", status="Judgment", date_disposed="08/01/2026") == (True, True)
    assert lead(lane="foreclosure", status="Disposed", date_disposed="01/15/2026") == (True, True)
    assert lead(lane="foreclosure", status="Disposed", date_disposed="12/01/2025") == (False, False)  # > 9 months
    for st in ("Dismissed", "Withdrawn", "Discontinued", "Settled", "Satisfied", "Transferred"):
        assert lead(lane="foreclosure", status=st, date_disposed="08/01/2026") == (False, False), st
    for lane in ("partition", "quiet_title", "lis_pendens"):
        assert lead(lane=lane) == (True, False)
        assert lead(lane=lane, status="Judgment", date_disposed="08/01/2026") == (False, False)
    assert lead(lane="judgment", status="Judgment Entered", date_disposed="06/01/2020") == (True, False)
    for st in ("Satisfied", "Vacated", "Cancelled", "Released", "Expired"):
        assert lead(lane="judgment", status=st) == (False, False), st
    assert lead(lane="other") == (False, False)
    assert lead(lane="") == (True, False)   # unlabeled (unknown layout): as before


def test_charleston_pass_keeps_live_cases_and_marks_judgment_entered(monkeypatch):
    import asyncio

    import curl_cffi.requests as cf

    class _Closed(_FakeCurlSession):
        def post(self, url, data=None, **k):
            if url.endswith("PISearch.aspx"):
                return _Resp(CLOSED_GRID.replace("<html><body>", "<html><body>" + self.HIDDEN))
            return super().post(url, data, **k)

    monkeypatch.setattr(cf, "Session", _Closed)
    monkeypatch.setattr(mod, "REQUEST_DELAY", 0)
    monkeypatch.setattr(mod, "SEARCH_PREFIXES", ["A"])
    rows = asyncio.run(mod._curl_search_county("charleston"))
    by = {r["case_number"]: r for r in rows}
    assert sorted(by) == ["2023CP1000201", "2026CP1000203", "2026CP1000204"]
    assert by["2023CP1000201"]["foreclosure_judgment_entered"] is True
    st = mod.LAST_CHARLESTON_STATS
    assert st["not_lead_by_lane"] == {"foreclosure": 3, "judgment": 1, "partition": 1}
    assert st["foreclosure_judgment_entered"] == 1
    assert st["profile"]["foreclosure"]["status"]["Disposed"] == 1
    # the judgment-entered foreclosure filed in 2023 survives the 2024+ filter, flagged
    for r in rows:
        r["_county"] = "charleston"
    lis = {li.case_number: li for li in mod.SCPublicIndexScraper()._to_listings(rows)}
    fj = lis["2023CP1000201"]
    assert fj.raw["foreclosure_judgment_entered"] is True
    assert fj.raw["foreclosure_judgment_date"] == _RECENT
    assert fj.raw["sc_public_index"]["foreclosure_judgment_entered"] is True
    assert "foreclosure_judgment_entered" not in lis["2026CP1000203"].raw


# --------------------------------------------------------------------------- #
# Filed-date window search (made-up form markup in the shape of the state form).
# --------------------------------------------------------------------------- #

FORM = """<html><body>
<input type="hidden" name="__VIEWSTATE" value="v0" />
<select name="ctl00$ContentPlaceHolder1$DropDownListCourtType"
        onchange="javascript:setTimeout('__doPostBack(\'ctl00$ContentPlaceHolder1$DropDownListCourtType\',\'\')', 0)">
  <option value=" ">All</option><option value="G">Circuit Court</option><option value="L">Summary Court</option>
</select>
<select name="ctl00$ContentPlaceHolder1$DropDownListCaseTypes">
  <option value=" ">All</option><option value="CP  ">Common Pleas</option><option value="GS  ">General Sessions</option>
</select>
<select name="ctl00$ContentPlaceHolder1$DropDownListDateFilter">
  <option value="">Select</option><option value="Filed">Case Filed</option><option value="Disposed">Case Disposed</option>
</select>
<input name="ctl00$ContentPlaceHolder1$TextBoxDateFrom" /><input name="ctl00$ContentPlaceHolder1$TextBoxDateTo" />
</body></html>"""


def _grid_page(n_cases, subtype="Foreclosure 420", start=1):
    rows = "".join(_row(f"Owner {i}", "Defendant", f"2026CP10{start + i:05d}", f"SAMPLE BANK VS Owner {i}",
                        subtype) for i in range(n_cases))
    return ('<html><body><input type="hidden" name="__VIEWSTATE" value="v1" />'
            '<table id="ContentPlaceHolder1_SearchResults">' + _HEAD + rows + "</table></body></html>")


class _WindowSession(_FakeCurlSession):
    """Accept -> FORM; court postback -> FORM; a search answers by window length: a window
    longer than 7 days is 'capped' (250 rows), shorter ones answer 2 cases."""
    def __init__(self, *a, **k):
        super().__init__()
        self.searches = []

    def post(self, url, data=None, **k):
        if not url.endswith("PISearch.aspx"):
            return _Resp(FORM)
        if data.get("__EVENTTARGET"):
            return _Resp(FORM)
        f = data["ctl00$ContentPlaceHolder1$TextBoxDateFrom"]
        t = data["ctl00$ContentPlaceHolder1$TextBoxDateTo"]
        self.searches.append((data["ctl00$ContentPlaceHolder1$DropDownListDateFilter"], f, t,
                              data.get("ctl00$ContentPlaceHolder1$DropDownListCourtType"),
                              data.get("ctl00$ContentPlaceHolder1$DropDownListCaseTypes")))
        from datetime import datetime as _dt
        days = (_dt.strptime(t, "%m/%d/%Y") - _dt.strptime(f, "%m/%d/%Y")).days + 1
        if days > 7:
            return _Resp(_grid_page(250))
        return _Resp(_grid_page(2, start=len(self.searches) * 10))


def test_date_form_is_read_from_the_page():
    form = mod._date_form(FORM)
    assert form["filed"] == "Filed" and form["disposed"] == "Disposed"
    assert form["court_value"] == "G" and form["court_postback"] is True
    assert form["case_postback"] is False
    assert mod._date_form("<html><body>no date filter</body></html>") is None


def test_date_window_search_is_incremental_and_splits_capped_windows(monkeypatch, tmp_path):
    import asyncio

    import curl_cffi.requests as cf

    sess = {}

    def _make(*a, **k):
        sess["s"] = _WindowSession()
        return sess["s"]

    monkeypatch.setattr(cf, "Session", _make)
    monkeypatch.setattr(mod, "REQUEST_DELAY", 0)
    monkeypatch.setattr(mod, "WINDOW_DELAY", 0)
    monkeypatch.setattr(mod, "WINDOW_DAYS", 14)
    monkeypatch.setattr(mod, "FILED_LOOKBACK_DAYS", 20)
    monkeypatch.setattr(mod, "FORECLOSURE_JUDGMENT_DAYS", 5)
    monkeypatch.setattr(mod, "WINDOW_MAX_REQUESTS", 40)
    monkeypatch.setattr(mod, "CHARLESTON_STATE_FILE", tmp_path / "state.json")
    rows = asyncio.run(mod._curl_search_county("charleston"))
    st = mod.LAST_CHARLESTON_STATS["search"]
    assert st["mode"] == "date_window" and st["split"] >= 1 and "fallback" not in st
    searches = sess["s"].searches
    assert all(c == "G" and k == "CP  " for _, _, _, c, k in searches)   # Circuit, Common Pleas
    assert {d for d, *_ in searches} == {"Filed", "Disposed"}
    assert rows and all(r["lane"] == "foreclosure" for r in rows)
    import json as _json
    state = _json.loads((tmp_path / "state.json").read_text())
    today = date.today().isoformat()
    assert state["filed_through"] == today and state["disposed_through"] == today
    # next run: starts from the saved day minus the overlap, not the lookback
    n_before = len(searches)
    asyncio.run(mod._curl_search_county("charleston"))
    second = sess["s"].searches
    assert len(second) < n_before
    first_from = min(_dt_parse(f) for d, f, *_ in second if d == "Filed")
    assert (date.today() - first_from).days == mod.WINDOW_OVERLAP_DAYS


def _dt_parse(s):
    from datetime import datetime as _dt
    return _dt.strptime(s, "%m/%d/%Y").date()


def test_not_a_results_page_falls_back_to_the_letter_sweep(monkeypatch, tmp_path):
    import asyncio

    import curl_cffi.requests as cf

    class _Odd(_WindowSession):
        def post(self, url, data=None, **k):
            if url.endswith("PISearch.aspx") and not data.get("__EVENTTARGET") \
                    and data.get("ctl00$ContentPlaceHolder1$TextBoxDateFrom"):
                return _Resp("<html><body>Please enter a last name</body></html>")
            if url.endswith("PISearch.aspx") and data.get("ctl00$ContentPlaceHolder1$TextBoxlastName"):
                return _Resp(GRID.replace("<html><body>", "<html><body>" + self.HIDDEN))
            return super().post(url, data, **k)

    monkeypatch.setattr(cf, "Session", _Odd)
    monkeypatch.setattr(mod, "REQUEST_DELAY", 0)
    monkeypatch.setattr(mod, "WINDOW_DELAY", 0)
    monkeypatch.setattr(mod, "SEARCH_PREFIXES", ["A"])
    monkeypatch.setattr(mod, "CHARLESTON_STATE_FILE", tmp_path / "state.json")
    rows = asyncio.run(mod._curl_search_county("charleston"))
    st = mod.LAST_CHARLESTON_STATS["search"]
    assert st["mode"] == "letters" and st["fallback"] == "not_a_results_page"
    assert len(rows) == 4
    assert not (tmp_path / "state.json").exists()
