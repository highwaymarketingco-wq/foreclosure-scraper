"""CourtListener civil: the real-property filter runs server-side, and the
"<code> Real Property: <label>" suit-nature strings /search/ returns are kept.

Before 2026-10-08 the pass paged through every civil docket in each district
(~240 pages in 90 days) under a 50-page/court cap and a 288 s budget, and the
client-side classifier rejected "290 Real Property: Other", so the source
returned 0 rows for 8 straight runs while 8 real-property cases existed.
"""
from __future__ import annotations

import asyncio
from urllib.parse import unquote

from foreclosure_scraper.scrapers.national.courtlistener_civil import (
    CIVIL_REAL_PROPERTY_QUERY,
    _fetch_court_civil,
    _is_real_property_case,
)


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingClient:
    def __init__(self, pages):
        self._pages = list(pages)
        self.urls: list[str] = []

    async def get(self, url, **kw):
        self.urls.append(url)
        return _Resp(self._pages.pop(0) if self._pages else {"results": [], "next": None})


def _hit(**kw):
    base = {
        "caseName": "Example Holdings LLC v. Sample Owner",
        "docketNumber": "2:26-cv-00001",
        "dateFiled": "2026-09-01",
        "court_id": "scd",
        "docket_id": 1,
        "docket_absolute_url": "/docket/1/example/",
        "suitNature": "290 Real Property: Other",
        "cause": "28:1442 Petition for Removal",
    }
    base.update(kw)
    return base


def test_search_style_suit_nature_strings_are_real_property():
    assert _is_real_property_case({"nature_of_suit": "290 Real Property: Other",
                                   "cause": "28:1442 Petition for Removal"})
    assert _is_real_property_case({"nature_of_suit": "220 Real Property: Foreclosure"})
    assert _is_real_property_case({"nature_of_suit": "Real Property: Foreclosure"})
    assert _is_real_property_case({"nature_of_suit": "240 Real Property: Torts to Land"})


def test_other_suit_natures_still_rejected():
    assert not _is_real_property_case({"nature_of_suit": "442 Civil Rights: Jobs"})
    assert not _is_real_property_case({"nature_of_suit": "463 Habeas Corpus - Alien Detainee"})
    assert not _is_real_property_case({"nature_of_suit": "", "cause": ""})


def test_fetch_court_civil_filters_server_side_and_keeps_the_rows():
    c = _RecordingClient([
        {"results": [_hit(), _hit(docketNumber="2:26-cv-00002",
                                  suitNature="220 Real Property: Foreclosure",
                                  cause="28:1345 Foreclosure")],
         "next": None},
    ])
    rows = asyncio.run(_fetch_court_civil(c, "scd", "tok"))
    assert [r["docket_number"] for r in rows] == ["2:26-cv-00001", "2:26-cv-00002"]
    assert len(c.urls) == 1
    url = unquote(c.urls[0])
    assert "court=scd" in url
    assert "&q=" in url and CIVIL_REAL_PROPERTY_QUERY in url
