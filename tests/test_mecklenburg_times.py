"""The Mecklenburg Times real-estate notices RSS (hand-written items, made-up parties).

Item shape follows the live export read 2026-10-07: title = property address,
description = "Auction Date: MM/DD/YYYY Description: <notice preview>".
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import mecklenburg_times as mod


def _item(title, desc, n):
    return (f"<item><title>{title}</title>"
            f"<link>https://mecktimes.com/public-notice/search-detail?indexgroup=real_estate&amp;detail={n}</link>"
            f"<description><![CDATA[{desc}]]></description><pubDate>Tue, 06 Oct 2026 00:00:00 +0000</pubDate></item>")


LABELLED = ("Auction Date: 10/19/2026 Description: NOTICE OF FORECLOSURE SALE NORTH CAROLINA MECKLENBURG COUNTY "
            "Special Proceeding No. 26SP009001-590 Trustee: Pat Sample Date of Sale: October 19, 2026 Time of Sale: "
            "3:00 p.m. Place of Sale: Mecklenburg County Courthouse Description of Property: See Deed of Trust "
            "Record Owner: Alexandra Q. Testperson and Robert Testperson Address of Property: 100 Example Meadow Road "
            "Charlotte, NC 28215 Deed of Trust: Book : 99999 Page: 123 Dated: December 1, 2023")
TRUSTEE = ("Auction Date: 10/20/2026 Description: NOTICE OF SUBSTITUTE TRUSTEE’S FORECLOSURE SALE OF REAL PROPERTY "
           "26SP009002-590 UNDER AND BY VIRTUE of the power and authority contained in that certain Deed of Trust "
           "executed and delivered by Lee Placeholder dated May 26, 2021 and recorded")
HOA = ("Auction Date: 10/21/2026 Description: NOTICE OF SALE OF REAL ESTATE UNDER CLAIM OF LIEN 26 SP 009003 "
       "Fiction Commons Homeowners Association, Inc.")
NOISE = "Auction Date: 10/22/2026 Description: NOTICE OF PUBLIC HEARING on a rezoning request"
FEED = ("<?xml version='1.0' encoding='UTF-8'?><rss version=\"2.0\"><channel><title>The Mecklenburg Times</title>"
        + _item("100 Example Meadow Rd Charlotte", LABELLED, 1)
        + _item("517 Fiction Dr Monroe", TRUSTEE, 2)
        + _item("9 Pretend Ct Huntersville", HOA, 3)
        + _item("1 Nowhere St Charlotte", NOISE, 4)
        + "</channel></rss>")
NOW = mod.datetime(2026, 10, 7)


def _rows():
    items = mod.parse_feed(FEED)
    return [(i, mod.parse_item(i)) for i in items]


def test_labelled_notice_gives_case_owner_address_trustee_and_auction_date():
    item, rec = _rows()[0]
    assert rec["kind"] == "foreclosure"
    assert rec["case_number"] == "26SP009001-590"
    assert rec["owner"] == "Alexandra Q. Testperson and Robert Testperson"
    assert (rec["street"], rec["city"], rec["zip"], rec["county"]) == ("100 Example Meadow Road", "Charlotte", "28215", "Mecklenburg")
    assert rec["trustee"] == "Pat Sample"
    assert rec["auction_date"].date().isoformat() == "2026-10-19"
    assert rec["deed_of_trust"] == {"book": "99999", "page": "123"}


def test_trustee_notice_takes_grantor_and_county_from_the_title_city():
    _, rec = _rows()[1]
    assert rec["owner"] == "Lee Placeholder" and rec["county"] == "Union"
    assert (rec["street"], rec["city"]) == ("517 Fiction Dr", "Monroe")


def test_hoa_lien_kind_and_noise_is_skipped():
    rows = _rows()
    assert rows[2][1]["kind"] == "hoa_lien" and rows[2][1]["case_number"] == "26SP009003"
    assert rows[3][1] is None


def test_listings_are_lis_pendens_outside_the_flip_footprint_and_reach_the_board():
    item, rec = _rows()[0]
    li = mod.build_listing(rec, item, now=NOW)
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.foreclosure_process == "power_of_sale" and li.sale_date.date().isoformat() == "2026-10-19"
    assert li.raw["public_notice"]["kind"] == "foreclosure"
    assert main._in_scope(li) and main._active_only(li, 120, now=NOW)


class _Resp:
    def __init__(self, text, status_code=200):
        self.text, self.status_code = text, status_code


class _Http:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def get(self, url, **kw):
        self.calls.append(url)
        return self.pages.pop(0) if self.pages else _Resp("<rss><channel></channel></rss>")


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_pages_until_an_empty_page_and_dedupes(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    http = _Http([_Resp(FEED), _Resp(FEED)])
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.MecklenburgTimesNotices().fetch())
    assert sorted(li.case_number for li in rows) == ["26SP009001-590", "26SP009002-590", "26SP009003"]
    assert len(http.calls) == 3   # page 1, page 2 (all repeats), page 3 empty -> stop
