"""'The Lookup' adapter (rod/nc_lookup.py) on hand-written pages shaped like the live search page,
pick list and instrument list (made-up names, books and pages; no fetched content). Covers the
parse (with and without a published code list, multi-row instruments), an empty answer, an error
page, a blocked page and a CAPTCHA (walled, never retried), a stale selection, and the browser's
own request sequence."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.rod import nc_lookup as lk
from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, SERVER_ERROR, FakeResp, install

HOST = lk.COUNTIES["Avery"].host

SEARCH_PAGE = """<html><head><title>The Lookup</title><script src="js/functions.js"></script></head><body>
<form method="post" target="content_frame" action="content.php?1234567" id="name_form" name="name_form">
<input type="hidden" name="searchType" value="name"/>
<input type="text" name="last_name"/><input type="text" name="first_name"/>
<input type="checkbox" name="instType[ALL]" value="ALL"/>
<input type="checkbox" name="instType[DEED][D]" value="D"/> D ~ DEED
<input type="checkbox" name="instType[DEED OF TRUST][DT]" value="DT"/> DT ~ DEED OF TRUST
<input type="checkbox" name="instType[CANCELLATION][SF]" value="SF"/> SF ~ SATISFACTION
<input type="checkbox" name="instType[OTHER][LP]" value="LP"/> LP ~ LIS PENDENS
</form></body></html>"""
SEARCH_PAGE_NO_CODES = SEARCH_PAGE.replace("instType[DEED]", "x").replace("instType[DEED OF TRUST]", "x") \
    .replace("instType[CANCELLATION]", "x").replace("instType[OTHER]", "x")


def pick_page(names: list[tuple[str, str, str, int]]) -> str:
    rows = "".join(f'<tr><td><input type="checkbox" name="entityID[]" value="{eid}" id="{eid}" '
                   f'onclick="storeEID({cnt}, {eid})"/> &nbsp;</td><td>{last}&nbsp;</td><td>{first}&nbsp;</td>'
                   f'<td>{cnt}&nbsp;</td></tr>' for eid, last, first, cnt in names)
    return ("<html><body><div>Pick List</div><table><thead><tr><th>Select</th><th>LastName</th><th>FirstName</th>"
            f"<th>Count</th></tr></thead><tbody>{rows}</tbody></table>"
            '<form method="post" action="content.php" name="pickListForm" id="pickListForm">'
            '<input type="hidden" name="searchType" value="name"/><input type="hidden" name="start_date" value=""/>'
            '<input type="hidden" name="end_date" value=""/><input type="hidden" name="party_type" value="Both"/>'
            "</form></body></html>")


def _r(inst, date, book_info, code, desc, role, searched, reverse, xref=""):
    x = (f"<a href=\"javascript: loadDetailsScreen('{inst}9');\">{xref}</a>" if xref else "")
    return (f'<tr id="{inst}" class=""><td><font class="invisibleText">x</font><br/>'
            f'<a href="javascript: loadDetailsScreen(\'{inst}\');" id="link_{inst}"> {date}&nbsp;</a></td>'
            f'<td class="summary" id="{inst}">{book_info} &nbsp; </td><td class="summary" id="{inst}">{code}&nbsp;</td>'
            f'<td class="summary" id="{inst}"> {desc} &nbsp;</td><td class="summary" id="{inst}"> {role}&nbsp;</td>'
            f'<td class="summary" id="{inst}">{searched}&nbsp; </td><td class="summary" id="{inst}">{reverse}&nbsp; </td>'
            f"<td>{x}</td><td></td><td><a href='view_image.php?key=00ff&type=pdf'>PDF</a></td></tr>")


ROWS_TESTER = ("<html><body><table><thead><tr><th>Date</th></tr></thead><tbody>"
               + _r("2026000300", "01/15/2026", "RE 700  40", "LP", "", "GRANTEE", "TESTER ALVIN Q", "EXAMPLE BANK")
               + _r("2022000200", "02/02/2022", "RE 640  88", "DT", "LOT 7\n   EXAMPLE ACRES", "GRANTOR",
                    "TESTER ALVIN Q", "EXAMPLE BANK")
               + _r("2022000200", "02/02/2022", "RE 640  88", "DT", "LOT 7\n   EXAMPLE ACRES", "GRANTOR",
                    "TESTER BERTHA", "EXAMPLE BANK")
               + _r("2021000150", "06/01/2021", "RE 610  3", "SF", "", "GRANTOR", "TESTER ALVIN Q", "EXAMPLE BANK",
                    xref="DT\n  500 12 (1)")
               + _r("2018000100", "03/01/2018", "RE 500  10", "D", "LOT 7 EXAMPLE ACRES", "GRANTEE",
                    "TESTER ALVIN Q", "SAMPLE CORA B")
               + "</tbody></table></body></html>")
ROWS_SAMPLE = ("<html><body><table><tbody>"
               + _r("2001000050", "05/05/2001", "RE 350  77", "D", "LOT 7 EXAMPLE ACRES", "GRANTEE", "SAMPLE CORA B",
                    "DOE DELLA")
               + "</tbody></table></body></html>")
EMPTY_PICK = pick_page([])

PICK_TESTER = pick_page([("11", "TESTER", "ALVIN Q", 4), ("12", "TESTER", "BERTHA", 1), ("13", "TESTER", "ZELDA", 9)])
PICK_SAMPLE = pick_page([("21", "SAMPLE", "CORA B", 1)])


class Site:
    """A made-up Lookup county: answers pick lists by surname, remembers the ticked names the way
    the session does, and serves the rows of the ticked names."""

    def __init__(self, check_override: str | None = None):
        self.ticked: list[str] = []
        self.check_override = check_override

    def routes(self):
        return [("GET", "index.php", FakeResp(SEARCH_PAGE)),
                ("GET", "content.php", self.content),
                ("POST", "ajaxActions.php", self.ajax)]

    def content(self, method, url, params, data):
        p = dict(params) if isinstance(params, list) else dict(params or {})
        if p.get("show_pick_list"):
            self.ticked = []
            return FakeResp({"TESTER": PICK_TESTER, "SAMPLE": PICK_SAMPLE}.get(p.get("last_name"), EMPTY_PICK))
        if set(self.ticked) <= {"11", "12"} and self.ticked:
            return FakeResp(ROWS_TESTER)
        if self.ticked == ["21"]:
            return FakeResp(ROWS_SAMPLE)
        return FakeResp("<html><body>nothing</body></html>")

    def ajax(self, method, url, params, data):
        if data.get("action") == "storeEID":
            self.ticked.append(data["entityID"])
            return FakeResp("")
        return FakeResp(self.check_override if self.check_override is not None else str(len(self.ticked)))


@pytest.fixture
def fake(monkeypatch):
    def go(routes):
        return install(monkeypatch, routes, lk.ADAPTER)
    yield go
    lk.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_code_categories_and_parse_rows():
    cats = lk.code_categories(SEARCH_PAGE)
    assert cats == {"D": "DEED", "DT": "DEED OF TRUST", "SF": "CANCELLATION", "LP": "OTHER"}
    assert lk.code_categories(SEARCH_PAGE_NO_CODES) == {}
    rows = lk.parse_rows(ROWS_TESTER, cats)
    assert [r.instrument_no for r in rows] == ["2026000300", "2022000200", "2021000150", "2018000100"]
    lp, dt, sf, d = rows
    assert (lp.kind, lp.grantors, lp.grantees) == ("lis_pendens", ["EXAMPLE BANK"], ["TESTER ALVIN Q"])
    assert (dt.kind, dt.book, dt.page, dt.index_code) == ("deed_of_trust", "640", "88", "RE")
    assert dt.grantors == ["TESTER ALVIN Q", "TESTER BERTHA"] and dt.grantees == ["EXAMPLE BANK"]
    assert dt.description == "LOT 7 EXAMPLE ACRES"                 # whitespace collapsed
    assert (sf.kind, sf.xref) == ("satisfaction", "DT 500 12 (1)")
    assert (d.kind, d.recorded, d.grantors, d.grantees) == ("deed", "2018-03-01", ["SAMPLE CORA B"], ["TESTER ALVIN Q"])
    # no published code list: the codes classify by their own text
    rows2 = lk.parse_rows(ROWS_TESTER, {})
    assert [r.kind for r in rows2] == ["lis_pendens", "deed_of_trust", "other", "deed"]


def test_pick_list_parse_and_matching():
    names, hidden = lk.parse_pick_list(PICK_TESTER)
    assert [(n.entity_id, n.last, n.first, n.count) for n in names] == \
        [("11", "TESTER", "ALVIN Q", 4), ("12", "TESTER", "BERTHA", 1), ("13", "TESTER", "ZELDA", 9)]
    assert ("party_type", "Both") in hidden
    chosen = lk.pick_matching(names, OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert [n.entity_id for n in chosen] == ["11"]
    assert lk.parse_pick_list(EMPTY_PICK) == ([], [("searchType", "name"), ("start_date", ""), ("end_date", ""),
                                                   ("party_type", "Both")])


def test_search_follows_the_browser_sequence(fake):
    site = Site()
    sess = fake(site.routes())
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="TESTER", first="ALVIN"), "both", None)
    assert res.status == "ok" and len(res.records) == 4
    seq = [(c[0], c[1].rsplit("/", 1)[-1].split("?")[0], (c[3] or {}).get("action") if c[3] else None)
           for c in sess.calls]
    assert seq == [("GET", "index.php", None), ("GET", "content.php", None),
                   ("POST", "ajaxActions.php", "storeEID"), ("POST", "ajaxActions.php", "checkEID"),
                   ("GET", "content.php", None)]
    assert sess.calls[0][1] == HOST + "/index.php?Accept=Accept"
    pick_params = sess.calls[1][2]
    assert pick_params["last_name"] == "TESTER" and pick_params["first_name"] == "ALVIN"
    assert pick_params["show_pick_list"] == "1" and pick_params["embed"] == "1"
    assert ("embed", "1") in sess.calls[4][2]


def test_empty_answer(fake):
    fake(Site().routes())
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0


def test_a_stale_selection_is_not_read(fake):
    fake(Site(check_override="7").routes())
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "rows not read" in res.reason


def test_error_page(fake):
    fake([("GET", "index.php", FakeResp(SEARCH_PAGE)), ("GET", "content.php", SERVER_ERROR)])
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and res.reason == "HTTP 500"
    fake([("GET", "index.php", FakeResp("<html><title>Disclaimer</title></html>"))])
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "did not open" in res.reason


@pytest.mark.parametrize("wall,reason", [(CLOUDFLARE_403, "HTTP 403"), (CAPTCHA_PAGE, "CAPTCHA")])
def test_blocked_or_captcha_is_walled_and_never_retried(fake, wall, reason):
    sess = fake([("GET", "index.php", wall)])
    res = lk.ADAPTER.search("Avery", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(lk.search_by_name("NC", "Avery", "SAMPLE CORA")) == []
    assert lk.chain("Avery", "TESTER ALVIN Q")["status"] == "walled"
    assert len(sess.calls) == 1


def test_chain_and_search_by_name_end_to_end(fake):
    site = Site()
    fake(site.routes())
    docs = asyncio.run(lk.search_by_name("NC", "Avery", "TESTER ALVIN Q"))
    assert len(docs) == 4 and docs[1].grantor == "TESTER ALVIN Q; TESTER BERTHA"
    out = lk.chain("Avery", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    li = out["liens"]
    assert [d["book"] for d in li["lis_pendens"]] == ["700"]
    assert [d["book"] for d in li["satisfactions"]] == ["610"]
    assert li["open_deeds_of_trust_est"] == 0                 # one D/T, one satisfaction since the deed


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in lk.COUNTIES:
        assert g.ROD_CONFIG[("NC", county)] == ("nc_lookup", lk.ENV_FLAG, "0")


def test_concurrent_lookups_never_interleave_their_steps(fake):
    """enrich_generic_rod runs several lookups per county at once; the pick list and the ticked
    names live in the server session, so one lookup's steps must finish before the next starts."""
    import time

    site = Site()
    fast_ajax = site.ajax
    site.ajax = lambda *a: (time.sleep(0.02), fast_ajax(*a))[1]    # give the threads room to interleave
    sess = fake(site.routes())

    async def both():
        return await asyncio.gather(lk.search_by_name("NC", "Avery", "TESTER ALVIN Q"),
                                    lk.search_by_name("NC", "Avery", "SAMPLE CORA B"))

    tester, sample = asyncio.run(both())
    assert [d.book for d in tester] == ["700", "640", "610", "500"]
    assert [d.book for d in sample] == ["350"]
    steps = [c for c in sess.calls if "index.php" not in c[1]]
    assert len(steps) == 8
    for block in (steps[:4], steps[4:]):                       # pick, store, check, list: contiguous
        assert block[0][2]["show_pick_list"] == "1"
        assert [c[0] for c in block] == ["GET", "POST", "POST", "GET"]
