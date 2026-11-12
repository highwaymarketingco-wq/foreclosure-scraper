"""Gannett obituaries: slug->name parsing + footprint + registry discovery."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from foreclosure_scraper.scrapers.public_notices.gannett_obituaries import (
    GannettObituaries,
    PAPERS,
    _fetch_detail,
    _name_from_slug,
    _parse_detail_description,
)


def test_name_basic_suffix_initial():
    assert _name_from_slug("jefferson-trawick-austin") == "Jefferson Trawick Austin"
    assert _name_from_slug("harry-a-chapman-jr") == "Harry A Chapman Jr."


def test_name_strips_trailing_disambiguator():
    assert _name_from_slug("sara-moore-2026-1") == "Sara Moore"
    assert _name_from_slug("glenn-stepp") == "Glenn Stepp"


def test_covers_core_wnc_and_upstate_counties():
    counties = {c for c, _ in PAPERS.values()}
    # Western NC core
    assert {"Buncombe", "Henderson", "Gaston", "Cleveland", "Rutherford"} <= counties
    # Upstate SC core
    assert {"Spartanburg", "Greenville", "Anderson"} <= counties
    states = {s for _, s in PAPERS.values()}
    assert states == {"NC", "SC"}


def test_registry_auto_discovers_it():
    from foreclosure_scraper.scrapers._registry import discover
    assert any(c is GannettObituaries for c in discover())


# ---------------------------------------------------------------------------
# Per-decedent detail parsing (extraction_gaps.md: age/funeral-home/survivors
# were never fetched). The real obituary narrative never renders even in a
# full stealth-browser DOM (live-checked), but the server-rendered meta
# description already carries it on a plain GET -- these fixtures are the
# real strings live-captured from citizen-times.com on 2026-10-01.
# ---------------------------------------------------------------------------

def test_parses_age_and_death_date_from_city_only_description():
    desc = ("Darlene Rice Honeycutt, 80, of Asheville, North Carolina, passed "
            "away on September 26, 2026. Born on January 22, 1946, she was "
            "the daughter of the late Frank Rice and Pauline Ra...")
    out = _parse_detail_description(desc)
    assert out["age"] == 80
    assert out["death_date_text"] == "September 26, 2026"
    assert "home_address" not in out  # city-only, no street-level address


def test_parses_literal_home_address_when_present():
    desc = ("Jerry Deal, 92, of 11 Elk Mountain Road, died on Wednesday, "
            "September 30, 2026, at his home. Graveside services will be "
            "held at 11 AM on Wednesday, October 3, at Ashelawn Garden...")
    out = _parse_detail_description(desc)
    assert out["age"] == 92
    assert out["home_address"] == "11 Elk Mountain Road"
    assert out["service_venue"] and "Ashelawn" in out["service_venue"]


def test_parses_age_with_no_street_address():
    desc = ("Martha Katherine Johnson Tedder, 61, of Asheville, passed away "
            "Saturday, September 26, 2026 at Mission Hospital. A Celebration "
            "of Life Service will be held at 12:00 PM on Sunday...")
    out = _parse_detail_description(desc)
    assert out["age"] == 61
    assert "home_address" not in out


def test_implausible_age_rejected():
    # a name-leading number that isn't a plausible human age must not become one
    out = _parse_detail_description("Jones Funeral Home, 1200, of Anytown,")
    assert "age" not in out


def test_empty_description_returns_empty():
    assert _parse_detail_description("") == {}
    assert _parse_detail_description(None) == {}


def test_fetch_detail_parses_real_response_shape(monkeypatch):
    html_body = (
        '<html><head><meta name="description" content="Darlene Rice '
        'Honeycutt, 80, of Asheville, North Carolina, passed away on '
        'September 26, 2026. Born on January 22, 1946, ..."></head></html>'
    )
    resp = MagicMock(status_code=200, text=html_body)
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    out = asyncio.run(_fetch_detail(c, "http://x/obituaries/darlene-honeycutt"))
    assert out["age"] == 80
    assert out["death_date_text"] == "September 26, 2026"


def test_fetch_detail_never_raises_on_failure():
    c = AsyncMock()
    c.get = AsyncMock(side_effect=OSError("connection reset"))
    out = asyncio.run(_fetch_detail(c, "http://x/obituaries/broken"))
    assert out == {}


def test_fetch_detail_handles_non_200():
    resp = MagicMock(status_code=404, text="")
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    out = asyncio.run(_fetch_detail(c, "http://x/obituaries/missing"))
    assert out == {}


# ---------------------------------------------------------------------------
# fetch() integration: a decedent with a home address is anchored directly
# (street_address set, no resolver needed); age reaches raw + the caption;
# a detail-fetch failure must not drop the list-only lead.
# ---------------------------------------------------------------------------

def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


def test_fetch_anchors_a_lead_with_a_literal_home_address(monkeypatch):
    import foreclosure_scraper.scrapers.public_notices.gannett_obituaries as M

    list_html = '<a href="/obituaries/jerry-deal">Jerry Deal</a>'
    detail_html = (
        '<html><head><meta name="description" content="Jerry Deal, 92, of '
        '11 Elk Mountain Road, died on Wednesday, September 30, 2026, at '
        'his home. Graveside services will be held at Ashelawn Garden...">'
        '</head></html>'
    )

    async def get(url, **kw):
        if url.endswith("/obituaries/"):
            return MagicMock(status_code=200, text=list_html)
        return MagicMock(status_code=200, text=detail_html)

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert len(result) == 1
    li = result[0]
    assert li.defendant == "Jerry Deal"
    assert li.street_address == "11 Elk Mountain Road"
    assert li.raw["obituary"]["age"] == 92
    assert li.raw["obituary"]["home_address_used_as_situs"] is True
    assert "age 92" in li.description


def test_fetch_survives_a_detail_fetch_failure(monkeypatch):
    """A detail-fetch exception must not drop the list-only lead -- the
    scraper's whole value proposition before this change was the name+slug."""
    import foreclosure_scraper.scrapers.public_notices.gannett_obituaries as M

    list_html = '<a href="/obituaries/glenn-stepp">Glenn Stepp</a>'

    async def get(url, **kw):
        if url.endswith("/obituaries/"):
            return MagicMock(status_code=200, text=list_html)
        raise OSError("connection reset")

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert len(result) == 1
    assert result[0].defendant == "Glenn Stepp"
    assert result[0].street_address is None
    assert "age" not in result[0].raw["obituary"]


def test_fetch_detail_disabled_by_env(monkeypatch):
    """FORECLOSURE_OBIT_DETAIL=0 keeps the pre-existing name-only behavior and
    makes zero detail GETs."""
    import foreclosure_scraper.scrapers.public_notices.gannett_obituaries as M

    list_html = '<a href="/obituaries/glenn-stepp">Glenn Stepp</a>'
    calls = []

    async def get(url, **kw):
        calls.append(url)
        return MagicMock(status_code=200, text=list_html)

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert len(result) == 1
    assert len(calls) == 1, "only the list page should be fetched, no detail GET"
    assert "age" not in result[0].raw["obituary"]
