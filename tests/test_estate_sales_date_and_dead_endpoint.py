"""national.estate_sales: 2026-10-01 national/reo per-source extraction audit.

Two gaps found live:

1. _parse_date never handled ISO-8601 datetimes ("2026-10-01T12:00:00.000Z"),
   which is exactly what the schema.org SaleEvent JSON-LD path hands it from
   startDate/endDate -- confirmed live, this is the dominant source of real
   rows (34/34 live 2026-10-01), and every single one had sale_date=None
   despite the real date sitting right in raw.estate_sales.start_date.

2. estatesale.com's /search?zip=...&radius=25 endpoint is a confirmed-dead
   path -- HTTP 404 on all 7 footprint zips, every time, live 2026-10-01.
   The site migrated to a client-rendered SPA (confirmed via robots.txt
   documenting /sales/view/ and /sales/advanceSearch/ instead, both of which
   return a near-empty JS-shell to a plain fetch). _fetch_estatesale_com is
   disabled (returns [] immediately) rather than left burning 7 guaranteed
   404s every run; estatesales.net alone already supplies real rows.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.scrapers.national.estate_sales import (
    EstateSales,
    _fetch_estatesale_com,
    _parse_date,
)


def test_parse_date_handles_iso8601_with_milliseconds_and_z():
    assert _parse_date("2026-10-01T12:00:00.000Z") == datetime(2026, 10, 1, 12, 0, 0)
    assert _parse_date("2026-10-02T03:45:00.000Z") == datetime(2026, 10, 2, 3, 45, 0)


def test_parse_date_handles_iso8601_without_milliseconds():
    assert _parse_date("2026-10-01T12:00:00Z") == datetime(2026, 10, 1, 12, 0, 0)


def test_parse_date_still_handles_pre_existing_formats():
    assert _parse_date("October 1, 2026") == datetime(2026, 10, 1)
    assert _parse_date("10/01/2026") == datetime(2026, 10, 1)
    assert _parse_date("2026-10-01") == datetime(2026, 10, 1)
    assert _parse_date("Sale dates: Jul 15-17, 2026 in Asheville") == datetime(2026, 7, 15)
    assert _parse_date(None) is None
    assert _parse_date("not a date at all") is None


def test_estatesale_com_disabled_returns_empty_without_a_network_call():
    out = asyncio.run(_fetch_estatesale_com("28801", "Asheville", "NC", "Buncombe"))
    assert out == []


def test_fetch_no_longer_reports_rows_from_the_dead_estatesale_com_endpoint(monkeypatch):
    """End-to-end: even if estatesales.net were to return nothing, fetch()
    must not silently resurrect the dead estatesale.com path."""
    from foreclosure_scraper.scrapers.national import estate_sales as m

    async def empty(*a, **kw):
        return []

    monkeypatch.setattr(m, "_fetch_estatesales_net", empty)
    s = EstateSales()
    out = asyncio.run(asyncio.wait_for(s.fetch(), timeout=5.0))
    assert out == []
