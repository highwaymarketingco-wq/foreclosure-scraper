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
    assert st["closed_not_emitted"] == {}
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


CLOSED_GRID = (
    '<html><body><table id="ContentPlaceHolder1_SearchResults">' + _HEAD
    + _row("Owner November", "Defendant", "2026CP1000201", "SAMPLE BANK VS Owner November",
           "Foreclosure 420", status="Disposed", disposed="08/01/2026")
    + _row("Owner Oscar", "Defendant", "2026CP1000202", "SAMPLE BANK VS Owner Oscar",
           "Foreclosure 420", status="Dismissed")
    + _row("Owner Papa", "Defendant", "2026CP1000203", "SAMPLE BANK VS Owner Papa",
           "Foreclosure 420")
    + _row("Debtor Quebec", "Defendant", "2026CP1000204", "SAMPLE CREDIT VS Debtor Quebec",
           "Transcript Judgment 540", status="Judgment Entered", disposed="06/01/2026")
    + _row("Debtor Romeo", "Defendant", "2026CP1000205", "SAMPLE CREDIT VS Debtor Romeo",
           "Confession of Judgment 570", status="Satisfied", disposed="06/02/2026")
    + _row("Heir Sierra", "Defendant", "2026CP1000206", "Heir Tango VS Heir Sierra",
           "Partition 440", status="Closed")
    + "</table></body></html>"
)


def test_only_open_cases_are_leads():
    rows = {r["case_number"]: r for r in mod._parse_charleston_results(CLOSED_GRID)}
    assert {cn for cn, r in rows.items() if mod.case_is_open(r)} == {
        "2026CP1000203",   # pending foreclosure
        "2026CP1000204",   # entered judgment: a disposition date does not close a judgment
    }


def test_charleston_pass_does_not_emit_closed_cases(monkeypatch):
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
    assert sorted(r["case_number"] for r in rows) == ["2026CP1000203", "2026CP1000204"]
    assert mod.LAST_CHARLESTON_STATS["closed_not_emitted"] == {
        "foreclosure": 2, "judgment": 1, "partition": 1}
