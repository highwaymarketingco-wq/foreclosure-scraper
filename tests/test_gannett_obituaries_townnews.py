"""gannett_obituaries: 2026-10-04 final-batch extraction-completeness audit.

Despite this module's own docstring claiming all 8 "Gannett" papers run on
Tukios, ``thedigitalcourier.com`` is actually TownNews -- its static
``/obituaries/`` list page server-renders only the single newest obituary,
while its real TownNews RSS search feed carries 50. Live-confirmed
2026-10-04 (see the module docstring for the full investigation).
``REAL_RSS`` below is a trimmed-but-real capture of that feed (one item,
2026-10-04), including the real ``<enclosure>`` photo this module never
captured before.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from foreclosure_scraper.scrapers.public_notices import gannett_obituaries as M

REAL_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>thedigitalcourier.com - RSS Results</title>
<item>
    <title>Charles E. Smith</title>
    <description>Charles E. Smith, age 89, of Ellenboro, passed away Tuesday, September 29, 2026 at Fair Haven of Forest City.</description>
    <pubDate>Fri, 02 Oct 2026 09:48:00 -0400</pubDate>
    <guid isPermaLink="false">http://www.thedigitalcourier.com/tncms/asset/editorial/0b49e181-403f-55bf-bc42-19f7ef373174</guid>
    <link>https://www.thedigitalcourier.com/archives/charles-e-smith/article_0b49e181-403f-55bf-bc42-19f7ef373174.html</link>
    <author>cbumgarner@thedigitalcourier.com (cbumgarner)</author>
    <enclosure url="https://bloximages.newyork1.vip.townnews.com/thedigitalcourier.com/content/tncms/assets/v3/editorial/6/3a/63a8c5a5-0117-5e1c-9dab-8149a23f35d2/6abfb7eb51ecf.image.jpg?resize=300%2C402" length="222824" type="image/jpeg" />
</item>
<item>
    <title>Mary Jones</title>
    <description>Mary Jones, age 101, of Rutherfordton, passed away Monday, September 28, 2026.</description>
    <pubDate>Thu, 01 Oct 2026 09:00:00 -0400</pubDate>
    <guid isPermaLink="false">http://www.thedigitalcourier.com/tncms/asset/editorial/aaaa1111</guid>
    <link>https://www.thedigitalcourier.com/archives/mary-jones/article_11112222-3333-4444-5555-666677778888.html</link>
</item>
</channel>
</rss>"""


def test_thedigitalcourier_is_in_the_townnews_set():
    assert "thedigitalcourier.com" in M._TOWNNEWS_RSS_HOSTS
    # every other current paper is still Tukios (unaffected by this fix)
    assert set(M.PAPERS) - M._TOWNNEWS_RSS_HOSTS == {
        "citizen-times.com", "blueridgenow.com", "gastongazette.com",
        "shelbystar.com", "goupstate.com", "greenvilleonline.com",
        "independentmail.com",
    }


def test_townnews_rss_url_shape():
    assert M._townnews_rss_url("thedigitalcourier.com") == (
        "https://www.thedigitalcourier.com/search/"
        "?f=rss&t=article&c=obituaries&l=50&s=start_time&sd=desc"
    )


def test_townnews_age_phrasing_parsed_by_shared_description_parser():
    """TownNews says 'Name, age 89, of City' -- one extra token vs. Tukios'
    'Name, 80, of City'. Both must parse through the SAME function."""
    out = M._parse_detail_description(
        "Charles E. Smith, age 89, of Ellenboro, passed away Tuesday, "
        "September 29, 2026 at Fair Haven of Forest City."
    )
    assert out["age"] == 89
    assert out["death_date_text"] == "September 29, 2026"


def test_tukios_age_phrasing_still_parses_unchanged():
    """Regression guard: the one-token regex tweak must not break the
    existing Tukios 'Name, 80, of City' shape."""
    out = M._parse_detail_description(
        "Darlene Rice Honeycutt, 80, of Asheville, North Carolina, passed "
        "away on September 26, 2026."
    )
    assert out["age"] == 80


def test_fetch_townnews_host_gets_two_full_obits_with_photo_no_extra_get(monkeypatch):
    """The real value proposition: 2 real rows from ONE RSS fetch, each
    already carrying age/death-date/photo -- no per-decedent GET at all,
    unlike the Tukios path's _fetch_detail."""
    calls = []

    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        calls.append({"url": url, "impersonate": impersonate})
        return REAL_RSS

    monkeypatch.setattr(M, "get_text", fake_get_text)

    out = asyncio.run(M._fetch_townnews_host(
        "thedigitalcourier.com", "Rutherford", "NC",
        datetime.utcnow(), M.GannettObituaries.slug,
    ))
    assert len(calls) == 1  # one RSS fetch, zero per-decedent GETs
    assert calls[0]["impersonate"] is True
    assert len(out) == 2

    smith = next(li for li in out if li.defendant == "Charles E. Smith")
    assert smith.county == "Rutherford"
    assert smith.state == "NC"
    assert smith.raw["obituary"]["age"] == 89
    assert smith.raw["obituary"]["death_date_text"] == "September 29, 2026"
    assert smith.source_url.endswith("article_0b49e181-403f-55bf-bc42-19f7ef373174.html")
    assert smith.raw["images"]["real"] == [
        "https://bloximages.newyork1.vip.townnews.com/thedigitalcourier.com/"
        "content/tncms/assets/v3/editorial/6/3a/63a8c5a5-0117-5e1c-9dab-"
        "8149a23f35d2/6abfb7eb51ecf.image.jpg?resize=300%2C402"
    ]

    jones = next(li for li in out if li.defendant == "Mary Jones")
    assert jones.raw["obituary"]["age"] == 101
    assert "images" not in jones.raw  # this item had no <enclosure>


def test_fetch_townnews_host_survives_a_blocked_fetch(monkeypatch):
    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        raise RuntimeError("impersonate got 429 for " + url)

    monkeypatch.setattr(M, "get_text", fake_get_text)
    out = asyncio.run(M._fetch_townnews_host(
        "thedigitalcourier.com", "Rutherford", "NC",
        datetime.utcnow(), M.GannettObituaries.slug,
    ))
    assert out == []


def test_fetch_townnews_host_survives_a_fetch_exception(monkeypatch):
    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr(M, "get_text", fake_get_text)
    out = asyncio.run(M._fetch_townnews_host(
        "thedigitalcourier.com", "Rutherford", "NC",
        datetime.utcnow(), M.GannettObituaries.slug,
    ))
    assert out == []


def test_full_fetch_routes_thedigitalcourier_through_townnews(monkeypatch):
    """End-to-end fetch(): the digital courier host must go through the
    TownNews branch (one RSS GET via get_text), every other host through
    the normal Tukios /obituaries/ list-page GET on the shared client."""
    client_urls = []
    get_text_urls = []

    async def get(url, **kw):
        client_urls.append(url)
        return MagicMock(status_code=200, text="<html>no obits</html>")

    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        get_text_urls.append(url)
        return REAL_RSS

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    monkeypatch.setattr(M, "client", fake_client)
    monkeypatch.setattr(M, "get_text", fake_get_text)
    monkeypatch.setattr(M, "PAPERS", {
        "thedigitalcourier.com": ("Rutherford", "NC"),
        "citizen-times.com": ("Buncombe", "NC"),
    })

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert len(get_text_urls) == 1
    assert "thedigitalcourier.com" in get_text_urls[0]
    assert len(client_urls) == 1  # only the Tukios host used the shared client
    assert "citizen-times.com" in client_urls[0]
    assert len(result) == 2  # the 2 TownNews rows; citizen-times page had none
    assert all(li.raw["obituary"]["paper"] == "thedigitalcourier.com" for li in result)
