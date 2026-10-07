"""Tyler register adapter (rod/nc_tyler.py), Self-Service and EagleWeb, on hand-written pages shaped
like the live ones (made-up names, books, pages; no fetched content). Covers each parser, the
request sequences, an empty answer, error replies, a blocked page and a CAPTCHA (walled, never
retried), chain() end to end, and the registry entries."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.rod import nc_polite
from foreclosure_scraper.rod import nc_tyler as ty
from foreclosure_scraper.rod.nc_chain import OwnerName
from tests._nc_rod_fakes import CAPTCHA_PAGE, CLOUDFLARE_403, FakeResp, install

DUR = ty.COUNTIES["Durham"].root
JOH = ty.COUNTIES["Johnston"].root


def ss_item(doc, docno, bt, book, page, date, kind, grantors, grantees, legal):
    col = lambda label, vals: (f'<div class="searchResultFourColumn"><ul class="selfServiceSearchResultColumn">'  # noqa: E731
                               f"<li>{label}{f' ({len(vals)})' if len(vals) > 1 else ''} </li>"
                               + "".join(f'<li class="selfServiceSearchResult{"Collapsed" if i == 0 else "FullResult"}">'
                                         f"<b>{v}</b></li>" for i, v in enumerate(vals)) + "</ul></div>")
    return (f'<li class="ss-search-row" data-documentid="{doc}" data-href="/web/document/{doc}?search=X">'
            f'<div class="selfServiceSearchRowRight"><h1> {docno} • BT: {bt} B: {book} P: {page} • {date} 08:36 AM </h1>'
            + col("Document Type", [kind]) + col("Grantor/Party 1", grantors) + col("Grantee/Party 2", grantees)
            + col("Legal", legal) + "</div></li>")


def ss_page(*items):
    return ('<html><body><div id="filters"><h2>Description</h2></div><ul class="selfServiceSearchResultList">'
            + "".join(items) + "</ul></body></html>")


SS_TESTER = ss_page(
    ss_item("DOC1", "2026000300", "OPR", "700", "40", "01/15/2026", "LIS PENDENS", ["EXAMPLE BANK"],
            ["TESTER ALVIN Q"], []),
    ss_item("DOC2", "2022000200", "OPR", "640", "88", "02/02/2022", "DEED OF TRUST", ["TESTER ALVIN Q", "TESTER BERTHA"],
            ["EXAMPLE BANK"], ["Subdivision EXAMPLE ACRES Lot 7"]),
    ss_item("DOC3", "2018000100", "OPR", "500", "10", "03/01/2018", "DEED", ["SAMPLE CORA B"], ["TESTER ALVIN Q"],
            ["Subdivision EXAMPLE ACRES Lot 7", "Subdivision EXAMPLE ACRES Lot 8"]),
)
SS_SAMPLE = ss_page(ss_item("DOC4", "2001000050", "OPR", "350", "77", "05/05/2001", "DEED", ["DOE DELLA"],
                            ["SAMPLE CORA B"], ["Subdivision EXAMPLE ACRES Lot 7"]))
SS_DISCLAIMER = FakeResp("<html><head><title>Self-Service</title></head><body><button id='submitDisclaimerAccept'>"
                         "I Accept</button></body></html>", 200, DUR + "/web/user/disclaimer")
SS_FORM = ("<html><body><form id='SelfService-1-search-form' action='/web/searchPost/DOCSEARCH5S1' method='post'>"
           "<input name='field_BothNamesID_DOT_Surname'/></form></body></html>")


class SelfService:
    def __init__(self):
        self.last = ""

    def routes(self):
        return [("POST", "/web/user/disclaimer", FakeResp("true")),
                ("GET", "/web/search/", FakeResp(SS_FORM)),
                ("POST", "/web/searchPost/", self.post),
                ("GET", "/web/searchResults/", self.results),
                ("GET", "/web/", SS_DISCLAIMER)]

    def post(self, method, url, params, data):
        self.last = next((v for k, v in data.items() if k.endswith("_DOT_Surname") and v), "")
        n = {"TESTER": 1, "SAMPLE": 1}.get(self.last, 0)
        return FakeResp(json.dumps({"validationMessages": {}, "totalPages": n, "currentPage": 1}))

    def results(self, method, url, params, data):
        return FakeResp({"TESTER": SS_TESTER, "SAMPLE": SS_SAMPLE}.get(self.last, ss_page()))


EW_DISCLAIMER = ("<html><head><title>Example County - Disclaimer</title></head><body>"
                 "<form method='POST' action='../web/loginPOST.jsp;jsessionid=ABC'><input type='hidden' name='guest' "
                 "value='true'/><input type='submit' name='submit' value='I Acknowledge'/></form></body></html>")
EW_FORM = ("<html><body><form name='docSearch' action='../eagleweb/docSearchPOST.jsp' method='post'>"
           "<input type='text' name='BothNamesIDSurname'/><input type='text' name='BothNamesIDName'/>"
           "<input type='text' name='GranteeIDSurname'/><input type='text' name='GranteeIDName'/>"
           "<input type='text' name='RecordingDateIDStart'/><input type='text' name='RecordingDateIDEnd'/>"
           "<select name='ClerkNameIDSearchType'><option value='Starts With' selected>Starts With</option></select>"
           "<input type='hidden' name='AllDocuments' value='ALL'/><input type='checkbox' name='BothNamesIDSoundex'/>"
           "<input type='submit' value='Search'/></form></body></html>")


def ew_row(node, kind, docno, book, page, date, grantors, grantees, legal=""):
    return (f'<tr class="odd"><td><strong><a href="../eagleweb/viewDoc.jsp?node={node}">{kind}<br/> {docno}</a></strong></td>'
            f'<td><a href="../eagleweb/viewDoc.jsp?node={node}"><b>BOOK: {book} PAGE: {page}-{int(page) + 1}</b> {date} '
            f'09:12:19 AM <small><table cellspacing="0"><tr><td><b>Grantor:</b><br/>{grantors}</td>'
            f"<td><b>Grantee:</b><br/>{grantees}</td><td><b>Related:</b><br/></td><td><b>Correction Info/Notes:</b><br/></td>"
            f"<td><b>Legal:</b><br/>{legal} </td></tr></table></small></a></td><td>View Image</td><td></td></tr>")


def ew_page(n, *rows):
    return ("<html><body><table id='searchResultsTable'><thead><tr><th>Description</th><th>Summary</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><div id='recentSearches'><ul><li><strong>Search 1:</strong> "
            f"<strong><a href='../eagleweb/docSearchResults.jsp?searchId=0&c=1'>*{n} results</a></strong></li></ul></div>"
            "</body></html>")


EW_TESTER = ew_page(3,
                    ew_row("D1", "LIS PENDENS", "2026000300", "700", "40", "01/15/2026", "EXAMPLE BANK", "TESTER ALVIN Q"),
                    ew_row("D2", "DEED OF TRUST", "2022000200", "640", "88", "02/02/2022", "TESTER ALVIN Q, TESTER BERTHA",
                           "EXAMPLE BANK, N.A."),
                    ew_row("D3", "DEED", "2018000100", "500", "10", "03/01/2018", "SAMPLE CORA B", "TESTER ALVIN Q",
                           "Subdivision: EXAMPLE ACRES Lot: 7"))
EW_SAMPLE = ew_page(1, ew_row("D4", "DEED", "2001000050", "350", "77", "05/05/2001", "DOE DELLA", "SAMPLE CORA B"))


class EagleWeb:
    def routes(self):
        return [("GET", "/recorder/web/", FakeResp(EW_DISCLAIMER, 200, JOH + "/recorder/web/")),
                ("POST", "loginPOST.jsp", FakeResp("<html>Deed Records</html>")),
                ("GET", "docSearch.jsp", FakeResp(EW_FORM, 200, JOH + "/recorder/eagleweb/docSearch.jsp")),
                ("POST", "docSearchPOST.jsp", self.post)]

    def post(self, method, url, params, data):
        d = dict(data)
        last = d.get("BothNamesIDSurname") or d.get("GranteeIDSurname")
        return FakeResp({"TESTER": EW_TESTER, "SAMPLE": EW_SAMPLE}.get(last, ew_page(0)))


@pytest.fixture
def fake(monkeypatch):
    def go(routes):
        return install(monkeypatch, routes, ty.ADAPTER)
    yield go
    ty.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_selfservice_parsers():
    assert ty.parse_search_post('{"validationMessages":{},"totalPages":3,"currentPage":1}') == (3, {})
    assert ty.parse_search_post('{"validationMessages":{"x":"bad date"},"totalPages":0}')[1] == {"x": "bad date"}
    assert ty.parse_search_post("<html>error</html>") == (None, {})
    rows = ty.parse_selfservice(SS_TESTER)
    assert [r.book for r in rows] == ["700", "640", "500"]
    lp, dt, deed = rows
    assert (lp.kind, lp.instrument_no, lp.index_code, lp.recorded) == ("lis_pendens", "2026000300", "OPR", "2026-01-15")
    assert (dt.kind, dt.grantors, dt.grantees) == ("deed_of_trust", ["TESTER ALVIN Q", "TESTER BERTHA"], ["EXAMPLE BANK"])
    assert deed.description == "Subdivision EXAMPLE ACRES Lot 7; Subdivision EXAMPLE ACRES Lot 8"
    assert ty.parse_selfservice(ss_page()) == []


def test_eagleweb_parsers():
    assert ty.split_names("HAMILTON LARA K., SMITH LARA K.") == ["HAMILTON LARA K.", "SMITH LARA K."]
    assert ty.split_names("EXAMPLE BANK, N.A., EXAMPLE HOLDINGS, LLC") == ["EXAMPLE BANK, N.A.", "EXAMPLE HOLDINGS, LLC"]
    rows, count, capped = ty.parse_eagleweb(EW_TESTER)
    assert count == 3 and not capped and [r.book for r in rows] == ["700", "640", "500"]
    lp, dt, deed = rows
    assert (lp.kind, lp.doc_type, lp.instrument_no, lp.page) == ("lis_pendens", "LIS PENDENS", "2026000300", "40")
    assert dt.grantors == ["TESTER ALVIN Q", "TESTER BERTHA"] and dt.grantees == ["EXAMPLE BANK, N.A."]
    assert (deed.recorded, deed.description) == ("2018-03-01", "Subdivision: EXAMPLE ACRES Lot: 7")
    assert ty.parse_eagleweb(ew_page(50))[2] is True                 # the guest maximum: truncated
    assert ty.parse_eagleweb(ew_page(0))[:2] == ([], 0)


def test_selfservice_sequence_and_chain(fake):
    sess = fake(SelfService().routes())
    out = ty.chain("Durham", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    assert [d["book"] for d in out["liens"]["lis_pendens"]] == ["700"]
    first = [(c[0], c[1].replace(DUR, "")) for c in sess.calls[:6]]
    assert first == [("GET", "/web/"), ("POST", "/web/user/disclaimer"), ("GET", "/web/search/DOCSEARCH5S1"),
                     ("POST", "/web/searchPost/DOCSEARCH5S1"), ("GET", "/web/searchResults/DOCSEARCH5S1?page=1"),
                     ("GET", "/web/search/DOCSEARCH5S1")]
    walk = next(c for c in sess.calls if c[0] == "POST" and "searchPost" in c[1] and "field_GranteeID_DOT_Surname" in c[3])
    assert walk[3]["field_GranteeID_DOT_Surname"] == "SAMPLE" and walk[3]["field_RecordingDateID_DOT_EndDate"] == "03/01/2018"


def test_eagleweb_sequence_and_chain(fake):
    sess = fake(EagleWeb().routes())
    out = ty.chain("Johnston", "TESTER ALVIN Q")
    assert out["status"] == "ok" and out["last_deed"]["book"] == "500"
    assert [p["book"] for p in out["prior_instruments"]] == ["350"]
    login = next(c for c in sess.calls if "loginPOST.jsp" in c[1])
    assert login[1] == JOH + "/recorder/web/loginPOST.jsp;jsessionid=ABC" and login[3] == {"guest": "true",
                                                                                         "submit": "I Acknowledge"}
    search = next(c for c in sess.calls if "docSearchPOST.jsp" in c[1])
    sent = dict(search[3])
    assert sent["BothNamesIDSurname"] == "TESTER" and sent["BothNamesIDName"] == "ALVIN"
    assert sent["AllDocuments"] == "ALL" and sent["ClerkNameIDSearchType"] == "Starts With"
    assert "BothNamesIDSoundex" not in sent                          # an unticked box is not sent


def test_empty_answers(fake):
    sess = fake(SelfService().routes())
    res = ty.ADAPTER.search("Durham", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == []
    assert not any("searchResults" in c[1] for c in sess.calls)      # zero pages: no results page fetched
    fake(EagleWeb().routes())
    res = ty.ADAPTER.search("Johnston", OwnerName(raw="x", last="NOBODY", first="ALVIN"))
    assert res.status == "ok" and res.records == [] and res.total == 0


def test_error_replies(fake):
    routes = SelfService().routes()
    routes[2] = ("POST", "/web/searchPost/", FakeResp("<html>Session expired</html>"))
    fake(routes)
    res = ty.ADAPTER.search("Durham", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "JSON" in res.reason
    routes[2] = ("POST", "/web/searchPost/", FakeResp('{"validationMessages":{"d":"bad"},"totalPages":0}'))
    fake(routes)
    res = ty.ADAPTER.search("Durham", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "refused" in res.reason
    routes = EagleWeb().routes()
    routes[3] = ("POST", "docSearchPOST.jsp", FakeResp("<html>An error occurred</html>"))
    fake(routes)
    res = ty.ADAPTER.search("Johnston", OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "error" and "could not be read" in res.reason


@pytest.mark.parametrize("county,first_route,wall,reason", [
    ("Durham", "/web/", CLOUDFLARE_403, "HTTP 403"),
    ("Johnston", "/recorder/web/", CAPTCHA_PAGE, "CAPTCHA"),
])
def test_blocked_is_walled_and_never_retried(fake, county, first_route, wall, reason):
    sess = fake([("GET", first_route, wall)])
    res = ty.ADAPTER.search(county, OwnerName(raw="x", last="TESTER", first="ALVIN"))
    assert res.status == "walled" and res.reason == reason
    assert asyncio.run(ty.search_by_name("NC", county, "SAMPLE CORA")) == []
    assert ty.chain(county, "TESTER ALVIN Q")["status"] == "walled"
    assert len(sess.calls) == 1


def test_registry_entries_are_off_by_default():
    from foreclosure_scraper import enrichment_generic_rod as g
    for county in ty.COUNTIES:
        assert g.ROD_CONFIG[("NC", county)] == ("nc_tyler", ty.ENV_FLAG, "0")
    assert ("NC", "Wake") not in g.ROD_CONFIG
