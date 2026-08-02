"""CourtListener bankruptcy: the /search/ lane that replaced the N+1 timeout.

The scraper used to list dockets via /dockets/ (no chapter field) and then make
ONE EXTRA API call per docket to /bankruptcy-information/ just to learn the
chapter. With ~3,900 dockets in the 90-day window and a per-host throttle of
~1.15s, that pass could not finish inside the 900s soft timeout and the source
returned nothing at all.

/search/?type=r carries `chapter` inline, so these tests pin:
  * the normalizer maps search field names onto the docket shape, chapter included
  * fetch() consumes the inline chapter and makes NO per-docket lookup
  * the wall-clock deadline stops pagination instead of running past the timeout
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (
    CourtListenerBankruptcy,
    _auth_headers,
    _fetch_court,
    _normalize_search_hit,
)


def _hit(**kw):
    base = {
        "caseName": "Jane Q Debtor",
        "docketNumber": "26-03547",
        "dateFiled": "2026-08-02",
        "chapter": "13",
        "court_id": "scb",
        "docket_id": 73708684,
        "docket_absolute_url": "/docket/73708684/jane-q-debtor/",
        "suitNature": "",
        "cause": "",
        "trustee_str": "John Trustee",
    }
    base.update(kw)
    return base


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingClient:
    """Serves canned search pages and records every URL requested."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.urls: list[str] = []

    async def get(self, url, **kw):
        self.urls.append(url)
        return _Resp(self._pages.pop(0) if self._pages else {"results": [], "next": None})


# --- normalizer -------------------------------------------------------------

def test_normalizer_carries_chapter_inline():
    d = _normalize_search_hit(_hit(), "scb")
    assert d["chapter"] == "13"
    assert d["case_name"] == "Jane Q Debtor"
    assert d["docket_number"] == "26-03547"
    assert d["date_filed"] == "2026-08-02"
    assert d["absolute_url"] == "/docket/73708684/jane-q-debtor/"
    assert d["docket_id"] == 73708684


def test_token_is_optional():
    """/search/ answers anonymously — a missing token must not add a bad header."""
    assert "Authorization" not in _auth_headers(None)
    assert _auth_headers("abc")["Authorization"] == "Token abc"


# --- pagination + deadline --------------------------------------------------

def test_fetch_court_hits_the_search_endpoint_and_follows_next():
    c = _RecordingClient([
        {"results": [_hit(docketNumber="26-1")], "next": "https://cl/next-page"},
        {"results": [_hit(docketNumber="26-2")], "next": None},
    ])
    rows = asyncio.run(_fetch_court(c, "scb", "tok"))
    assert [r["docket_number"] for r in rows] == ["26-1", "26-2"]
    assert "/search/?type=r&court=scb" in c.urls[0]
    assert c.urls[1] == "https://cl/next-page"
    # The whole point: no /bankruptcy-information/ call.
    assert not any("bankruptcy-information" in u for u in c.urls)


def test_deadline_stops_pagination():
    """An already-expired deadline must return immediately, not page forever."""
    c = _RecordingClient([{"results": [_hit()], "next": "https://cl/p2"}] * 50)
    rows = asyncio.run(_fetch_court(c, "scb", "tok", time.monotonic() - 1))
    assert rows == []
    assert c.urls == []


# --- end-to-end -------------------------------------------------------------

def test_fetch_uses_inline_chapter_without_per_docket_lookup():
    dockets = [
        _normalize_search_hit(_hit(docketNumber="26-1", chapter="13"), "ncwb"),
        _normalize_search_hit(_hit(docketNumber="26-2", chapter="7"), "ncwb"),
    ]
    lookup = AsyncMock(return_value="13")

    async def _run():
        with patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_court",
            new=AsyncMock(side_effect=lambda c, court, tok, deadline=None: (
                dockets if court == "ncwb" else []
            )),
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._load_token",
            return_value=None,   # anonymous must still work
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_chapter",
            new=lookup,
        ):
            return await CourtListenerBankruptcy().fetch()

    rows = list(asyncio.run(_run()))
    assert len(rows) == 2
    assert lookup.await_count == 0, "inline chapter must not trigger the N+1 lookup"
    chapters = sorted(r.raw["courtlistener"]["chapter"] for r in rows)
    assert chapters == ["13", "7"]
    assert all(r.description.startswith("Ch.") for r in rows)
