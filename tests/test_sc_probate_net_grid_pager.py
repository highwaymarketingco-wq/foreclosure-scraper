"""southcarolinaprobate.net: every page of a name search's results grid is read.

The grid pages at 20 rows (ASP.NET GridView pager, __doPostBack(grid, 'Page$N')).
Live 2026-10-08, Charleston Probate "Smith": pager Page$2..Page$5 and page 2 held 20
estates not on page 1; the scraper read page 1 only. Markup below is minimal and
invented; the parser is stubbed so the test is about paging alone.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from foreclosure_scraper.scrapers.counties_sc import sc_probate_net as m

GRID = m.PRE + "cgvCases"


def _page(n: int, last: int) -> str:
    links = "".join(
        f"<a href=\"javascript:__doPostBack(&#39;{GRID}&#39;,&#39;Page${k}&#39;)\">{k}</a>"
        for k in range(1, last + 1) if k != n)
    cases = "".join(f"CASE:2026ES10{n:02d}{i:03d} " for i in range(20 if n < last else 7))
    return (f"<html><input type=\"hidden\" name=\"__VIEWSTATE\" value=\"vs{n}\">"
            f"<div>{cases}</div><table><tr><td>{links}</td></tr></table></html>")


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


class _Server:
    def __init__(self, last: int):
        self.last = last
        self.posts: list[str] = []

    async def get(self, url, **kw):
        return _Resp("<html><input type=\"hidden\" name=\"__VIEWSTATE\" value=\"vs0\"></html>")

    async def post(self, url, data=None, **kw):
        arg = data.get("__EVENTARGUMENT") or ""
        tgt = data.get("__EVENTTARGET") or ""
        self.posts.append(f"{tgt}|{arg}")
        if tgt.endswith("ddlCounties"):
            return _Resp("<html><input type=\"hidden\" name=\"__VIEWSTATE\" value=\"vsc\"></html>")
        if tgt.endswith("btnSearch"):
            return _Resp(_page(1, self.last))
        n = int(arg.split("$")[1])
        return _Resp(_page(n, self.last))


def _stub_parse(html, county, state):
    return [SimpleNamespace(case_number=c) for c in re.findall(r"CASE:(\w+)", html)]


def test_search_follows_the_grid_pager(monkeypatch):
    monkeypatch.setattr(m, "_parse_probate", _stub_parse)
    monkeypatch.setattr(m, "GRID_PAGE_PAUSE_S", 0)
    srv = _Server(last=4)
    rows = asyncio.run(m._search_county(srv, "Charleston Probate", "Charleston", "SC", False, "Smith"))
    assert len(rows) == 20 * 3 + 7
    assert len({r.case_number for r in rows}) == 67
    assert [p for p in srv.posts if "Page$" in p] == [f"{GRID}|Page${k}" for k in (2, 3, 4)]


def test_single_page_result_costs_no_extra_request(monkeypatch):
    monkeypatch.setattr(m, "_parse_probate", _stub_parse)
    monkeypatch.setattr(m, "GRID_PAGE_PAUSE_S", 0)
    srv = _Server(last=1)
    rows = asyncio.run(m._search_county(srv, "Charleston Probate", "Charleston", "SC", False, "Smith"))
    assert len(rows) == 7
    assert not any("Page$" in p for p in srv.posts)


def _li(kind, **b):
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(source=m.SCProbateNet.slug, source_url="https://example.test",
                   listing_type=ListingType.PROBATE_NOTICE, property_kind=PropertyKind.UNKNOWN,
                   state="SC", county="Charleston",
                   raw={"sc_probate_net": {"record_kind": kind, **b}})


def test_old_closed_estates_and_old_licenses_are_not_leads():
    from datetime import datetime
    now = datetime(2026, 10, 8)
    assert m.is_current(_li("probate", status="Opened", filing_date="03/02/1990"), now)
    assert m.is_current(_li("probate", status="Closed", filing_date="01/15/2026"), now)
    assert not m.is_current(_li("probate", status="Closed", filing_date="01/15/2019"), now)
    assert not m.is_current(_li("probate", status="Closed"), now)
    assert m.is_current(_li("marriage", application_date="05/01/2026"), now)
    assert not m.is_current(_li("marriage", application_date="05/01/2001"), now)
