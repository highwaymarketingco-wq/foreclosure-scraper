"""SC probate notices: every page of every search term is read, bodies are de-duplicated
BEFORE anything is counted, and the Gaffney Ledger is read through GeoDirectory's public
listing route (50 notices with text per request) with the article-page lane as fallback.

Measured 2026-10-08: Pickens returns 90 + 117 posts for the two search terms (the old
fixed two-page loop read 100 of the 117, and the 120-entry cap was applied to the
combined, not yet de-duplicated list); the Gaffney search reports 557 hits and the old
lane read 120 article pages. Every name and address below is invented.
"""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from foreclosure_scraper.scrapers.counties_sc import sc_probate_notices as m

HEADER = "NOTICE TO CREDITORS\nOF ESTATES\nAll persons having claims against the following estates.\n"


def _body(n: int, county_code: str = "39") -> str:
    return (HEADER + f"Estate: Testperson Number{n}\nDate of Death: 5/30/2026\n"
            f"Case Number: 2026ES{county_code}{n:05d}\nPersonal Representative:\n"
            f"Sample Representative\nAddress: 1 Example St.,\nExampletown, SC 29631\n")


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _WPServer:
    """posts route: term -> list of post numbers; per_page/page honoured."""

    def __init__(self, posts_by_term=None, geodir_by_term=None, geodir_fails=False):
        self.posts_by_term = posts_by_term or {}
        self.geodir_by_term = geodir_by_term or {}
        self.geodir_fails = geodir_fails
        self.urls: list[str] = []

    async def get(self, url, **kw):
        self.urls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        term = q.get("search", "").replace(" ", "+")
        page = int(q.get("page", "1"))
        per = int(q.get("per_page", "50"))
        if u.path.endswith("/wp/v2/posts"):
            nums = self.posts_by_term.get(term, [])
            chunk = nums[(page - 1) * per: page * per]
            if not chunk and page > 1:
                return _Resp(400, {"code": "rest_post_invalid_page_number"})
            return _Resp(200, [{"link": f"https://{u.netloc}/p/{n}", "date": "2026-09-01T00:00:00",
                                "content": {"rendered": _body(n).replace("\n", "<br>")}}
                               for n in chunk])
        if u.path.endswith("/geodir/v2/classifieds"):
            if self.geodir_fails:
                return _Resp(404, {"code": "rest_no_route"})
            rows = self.geodir_by_term.get(term, [])
            chunk = rows[(page - 1) * per: page * per]
            if not chunk and page > 1:
                return _Resp(400, {"code": "rest_post_invalid_page_number"})
            return _Resp(200, [{"link": f"https://{u.netloc}/c/{n}", "date": d,
                                "content": {"rendered": _body(n, "11").replace("\n", "<br>")}}
                               for n, d in chunk])
        if u.path.endswith("/wp/v2/search"):
            nums = [n for n, _ in self.geodir_by_term.get(term, [])][:50] if page == 1 else []
            return _Resp(200, [{"url": f"https://{u.netloc}/a/{n}"} for n in nums])
        if "/a/" in u.path:
            n = int(u.path.rsplit("/", 1)[1])
            return _Resp(200, None, "<html><body>" + _body(n, "11").replace("\n", "<br>") + "</body></html>")
        return _Resp(404, {})


def _run(paper, server):
    async def _noop(*a, **k):
        return None
    orig = m.asyncio.sleep
    m.asyncio.sleep = _noop
    try:
        return asyncio.run(m._fetch_paper(server, paper))
    finally:
        m.asyncio.sleep = orig


def test_posts_lane_reads_every_page_and_dedupes_before_counting():
    # 90 posts for term 1, 117 for term 2, 40 of them shared: 167 distinct notices.
    t1 = list(range(1, 91))
    t2 = list(range(51, 168))
    srv = _WPServer(posts_by_term={"notice+to+creditors": t1, "estate+notice": t2})
    rows = _run(m.Paper("Pickens", "www.example-pickens.test", "posts"), srv)
    assert len(rows) == 167
    assert len({r.case_number for r in rows}) == 167


def test_geodir_lane_reads_the_listing_route_and_stops_at_the_lookback():
    recent = [(n, "2026-09-0%dT10:00:00" % (1 + n % 9)) for n in range(1, 81)]
    old = [(n, "2020-01-01T10:00:00") for n in range(81, 131)]
    srv = _WPServer(geodir_by_term={"notice+to+creditors": recent + old})
    rows = _run(m.Paper("Cherokee", "www.example-gaffney.test", "geodir"), srv)
    assert len(rows) == 80
    assert all(r.county == "Cherokee" for r in rows)
    assert not any("/a/" in u for u in srv.urls), "no per-article requests on the JSON lane"
    # page 1 (50) + page 2 (30 recent + 20 old -> stop); then term 2 answers empty.
    assert sum("/geodir/v2/classifieds" in u for u in srv.urls) == 3


def test_geodir_failure_falls_back_to_article_pages():
    recent = [(n, "2026-09-01T10:00:00") for n in range(1, 6)]
    srv = _WPServer(geodir_by_term={"notice+to+creditors": recent}, geodir_fails=True)
    rows = _run(m.Paper("Cherokee", "www.example-gaffney.test", "geodir"), srv)
    assert len(rows) == 5
    assert any("/a/" in u for u in srv.urls)
