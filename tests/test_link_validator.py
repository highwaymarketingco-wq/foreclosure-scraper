"""Pin the link_validator's no-drop / tag-only behavior.

The 2026-05 incident: link_validator was DROPPING ~245 SC lis-pendens
listings because publicindex.sccourts.org returns 406 on default HEAD
requests. Investor-grade policy: never drop a listing on link health
alone — tag the link state so the dashboard can warn, but keep the
underlying scraped data.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from foreclosure_scraper.link_validator import (
    KNOWN_ANTI_BOT_HOSTS,
    _check_one,
    validate,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(url="http://example.com/x", **kw) -> Listing:
    base = dict(
        source="x", source_url=url,
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={},
    )
    base.update(kw)
    return Listing(**base)


def _resp(status_code: int):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    return r


def _mock_client(head_status=200, get_status=None):
    c = AsyncMock()
    c.head = AsyncMock(return_value=_resp(head_status))
    if get_status is not None:
        c.get = AsyncMock(return_value=_resp(get_status))
    return c


def test_known_anti_bot_hosts_skip_network_check():
    """SC Public Index, Tyler portal, Realtor.com etc. are kept without
    making a network request — they're known to reject naive HEAD/GET."""
    for host in ("publicindex.sccourts.org", "portal-nc.tylertech.cloud",
                 "www.realtor.com", "www.foreclosure.com"):
        url = f"https://{host}/some/path"
        c = AsyncMock()
        # If _check_one DOES hit the network for these hosts, head will be called.
        c.head = AsyncMock(side_effect=AssertionError("must NOT hit network"))
        label, status = asyncio.run(_check_one(c, url))
        assert label == "skipped", f"{host} not bypassed"
        assert status is None
        c.head.assert_not_called()


def test_406_does_NOT_drop():
    """The exact bug the 2026-05 incident triggered: SC Public Index
    returned 406 → old validator dropped the listing. New validator
    tags it 'anti-bot' and keeps it."""
    # Use a non-bypassed URL so we exercise the network path
    li = _li(url="https://example.com/case/2026-CP-42-01438")
    c = _mock_client(head_status=406)
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1, "listing dropped despite 406!"
    assert out[0].raw["link_check"]["status"] == "anti-bot"
    assert out[0].raw["link_check"]["http"] == 406


def test_404_does_NOT_drop_either():
    """Even a genuine 404 is kept. The scraper already parsed the data;
    a stale source URL doesn't invalidate the foreclosure record."""
    li = _li(url="https://example.com/missing")
    c = _mock_client(head_status=404)
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1, "listing dropped on 404!"
    assert out[0].raw["link_check"]["status"] == "dead"
    assert out[0].raw["link_check"]["http"] == 404


def test_429_kept_as_auth():
    li = _li(url="https://example.com/rate-limited")
    c = _mock_client(head_status=429)
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1
    assert out[0].raw["link_check"]["status"] == "auth"


def test_5xx_kept_as_server():
    li = _li(url="https://example.com/error")
    c = _mock_client(head_status=503)
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1
    assert out[0].raw["link_check"]["status"] == "server"


def test_2xx_tagged_ok():
    li = _li(url="https://example.com/good")
    c = _mock_client(head_status=200)
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1
    assert out[0].raw["link_check"]["status"] == "ok"
    assert out[0].raw["link_check"]["http"] == 200


def test_connection_failure_kept_as_unreachable():
    """Even on connection-level failure, keep the listing. The scraper
    already has the data; the link being unreachable just means the
    consumer can't click through, not that the listing is invalid."""
    li = _li(url="https://nonexistent.invalid/x")
    c = AsyncMock()
    c.head = AsyncMock(side_effect=httpx.ConnectError("DNS failure"))
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate([li]))
    assert len(out) == 1
    assert out[0].raw["link_check"]["status"] == "unreachable"


def test_validate_returns_all_listings():
    """Top-line invariant: validate() never returns fewer listings than
    it received. This is the contract the rest of the pipeline depends
    on now that we tag instead of drop."""
    listings = [_li(url=f"http://example.com/{i}") for i in range(10)]
    # Mix of statuses
    statuses = [200, 404, 406, 429, 500, 200, 403, 500, 404, 406]
    call_idx = {"i": 0}

    async def head(*args, **kw):
        i = call_idx["i"]
        call_idx["i"] += 1
        return _resp(statuses[i])

    c = AsyncMock()
    c.head = head
    with patch("foreclosure_scraper.link_validator.client") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=c)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        out = asyncio.run(validate(listings))
    assert len(out) == 10, "validate() must not drop ANY listings"


def test_known_anti_bot_hosts_set_includes_critical_sources():
    """Pin the anti-bot bypass list — these are the hosts that will
    silently drop our data if we miss them."""
    must_be_present = {
        "publicindex.sccourts.org",
        "portal-nc.tylertech.cloud",
        "www.realtor.com",
        "ap.rdcpix.com",
    }
    for host in must_be_present:
        assert host in KNOWN_ANTI_BOT_HOSTS, f"{host} missing from bypass list"
