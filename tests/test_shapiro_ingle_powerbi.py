"""Shapiro & Ingle / LOGS NC Power BI docket scraper.

Added 2026-07-01. Calls the public Power BI querydata JSON-XHR endpoint
(resourceKey 10e35a6c-…, modelId 452995, entity "web Upcoming Sales Report NC"),
decodes the DSR/DM0 delta-encoding (C=present values, R=repeat mask, Ø=null
mask, ValueDicts=string pools), splits the SALE_DATE inline status string, and
emits in-footprint NC foreclosure Listings. Richer than law_firms.ingle_firm's
HTML table (full statewide docket + servicer + status + case #).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.law_firms.shapiro_ingle_powerbi import (
    RESOURCE_KEY,
    ShapiroInglePowerBI,
    decode_dm0,
    decode_embed_resource_key,
    split_sale_date,
    _money,
    _ms_to_clock,
    _row_to_listing,
)


def test_decode_embed_resource_key():
    # The exact base64 ?r= blob from logs.com/nc-upcoming-sales-report.html.
    blob = (
        "eyJrIjoiMTBlMzVhNmMtM2NlYi00MzY0LTg0YWQtMGY2MzEyYzNmNDhlIiwidCI6ImRm"
        "ZmRlOTRmLTcyZmItNDlhZS1hY2IyLTBiOTYxYWJkNWI0MSIsImMiOjN9"
    )
    assert decode_embed_resource_key(blob) == RESOURCE_KEY
    assert decode_embed_resource_key("not-base64") is None


def test_split_sale_date_plain():
    orig, eff, status = split_sale_date("01/05/26")
    assert orig == datetime(2026, 1, 5)
    assert eff == datetime(2026, 1, 5)
    assert status == "active"


def test_split_sale_date_cancelled_until():
    # bare mm/dd "Until" token — year anchored to the original (2026), and since
    # 07/16 > 01/05 it stays in the same year.
    orig, eff, status = split_sale_date("01/05/26 Cancelled Until 07/16")
    assert orig == datetime(2026, 1, 5)
    assert eff == datetime(2026, 7, 16)
    assert status == "cancelled"


def test_split_sale_date_postponed_rolls_year():
    # "Until 01/03" lands before the 12/20 original -> roll to next year.
    orig, eff, status = split_sale_date("12/20/25 Postponed Until 01/03")
    assert orig == datetime(2025, 12, 20)
    assert eff == datetime(2026, 1, 3)
    assert status == "postponed"


def test_split_sale_date_empty():
    assert split_sale_date(None) == (None, None, None)
    assert split_sale_date("") == (None, None, None)


def test_money_and_clock():
    assert _money(235115.7) == 235115.7
    assert _money(0) is None
    assert _money(None) is None
    assert _money("$427,000.00") == 427000.0
    assert _ms_to_clock(37800000) == "10:30"   # 10:30 AM
    assert _ms_to_clock(39600000) == "11:00"
    assert _ms_to_clock(None) is None


def _synthetic_ds0() -> dict:
    """A hand-built DSR/DS[0] exercising C/R/Ø + ValueDicts, in COLUMNS order:
    OFFICE_CODE, CASE_TYPE_NAME, STATUS_NAME, SALE_RESULTS, SALES_DATE,
    SALE_DATE, CLIENT_CODE, COUNTY_NAME, SALE_TIME, CASE_COURT_NUMB,
    FULL_ADDRESS, BID_AMNT.
    """
    return {
        "ValueDicts": {
            "D0": ["NC"],
            "D1": ["Foreclosure"],
            "D2": ["ACTIVE"],
            "D3": ["Cancelled"],
            "D4": ["01/05/26", "01/05/26 Cancelled Until 07/16"],
            "D5": ["RMY", "CEV"],
            "D6": ["Buncombe", "Gaston"],
            "D7": ["21SP000183-100", "24SP000319-800"],
            "D8": [
                "18 Olive St, Asheville, North Carolina 28801",
                "388 Island Creek Road, Gastonia, North Carolina 28052",
            ],
        },
        "PH": [
            {
                "DM0": [
                    {
                        # Full first row + schema. Non-dict columns (SALES_DATE=4,
                        # SALE_TIME=8, BID_AMNT=11) are literals.
                        "S": [
                            {"N": "G0", "T": 1, "DN": "D0"},
                            {"N": "G1", "T": 1, "DN": "D1"},
                            {"N": "G2", "T": 1, "DN": "D2"},
                            {"N": "G3", "T": 1, "DN": "D3"},
                            {"N": "G4", "T": 7},
                            {"N": "G5", "T": 1, "DN": "D4"},
                            {"N": "G6", "T": 1, "DN": "D5"},
                            {"N": "G7", "T": 1, "DN": "D6"},
                            {"N": "G8", "T": 7},
                            {"N": "G9", "T": 1, "DN": "D7"},
                            {"N": "G10", "T": 1, "DN": "D8"},
                            {"N": "G11", "T": 3},
                        ],
                        # all 12 present
                        "C": [0, 0, 0, 0, 1767571200000, 0, 0, 0, 37800000, 0, 0, None],
                        "Ø": 2048,  # bit 11 (BID_AMNT) null
                    },
                    {
                        # Row 2: repeat OFFICE_CODE(0),CASE_TYPE(1),STATUS(2),
                        # RESULTS(3) from prev (R bits 0-3 = 1+2+4+8=15); supply
                        # the rest. BID present this time.
                        "C": [1767571200000, 1, 1, 1, 39600000, 1, 1, 427000.0],
                        "R": 15,
                    },
                ]
            }
        ],
    }


def test_decode_dm0_c_r_o_masks():
    rows = decode_dm0(_synthetic_ds0())
    assert len(rows) == 2

    r0, r1 = rows
    # Row 0 — dict derefs + literal date + null bid.
    assert r0["OFFICE_CODE"] == "NC"
    assert r0["CASE_TYPE_NAME"] == "Foreclosure"
    assert r0["STATUS_NAME"] == "ACTIVE"
    assert r0["SALE_RESULTS"] == "Cancelled"
    assert r0["SALES_DATE"] == 1767571200000
    assert r0["SALE_DATE"] == "01/05/26"
    assert r0["CLIENT_CODE"] == "RMY"
    assert r0["COUNTY_NAME"] == "Buncombe"
    assert r0["SALE_TIME"] == 37800000
    assert r0["CASE_COURT_NUMB"] == "21SP000183-100"
    assert r0["FULL_ADDRESS"].startswith("18 Olive St")
    assert r0["BID_AMNT"] is None  # Ø masked

    # Row 1 — R mask reused 0-3 from row 0; new values for the rest.
    assert r1["OFFICE_CODE"] == "NC"        # repeated
    assert r1["CASE_TYPE_NAME"] == "Foreclosure"
    assert r1["STATUS_NAME"] == "ACTIVE"
    assert r1["SALE_RESULTS"] == "Cancelled"
    assert r1["SALE_DATE"] == "01/05/26 Cancelled Until 07/16"
    assert r1["CLIENT_CODE"] == "CEV"
    assert r1["COUNTY_NAME"] == "Gaston"
    assert r1["CASE_COURT_NUMB"] == "24SP000319-800"
    assert r1["BID_AMNT"] == 427000.0


def test_row_to_listing_in_scope_and_split():
    rows = decode_dm0(_synthetic_ds0())
    listings = [_row_to_listing(r, "law_firms.shapiro_ingle_powerbi") for r in rows]
    listings = [x for x in listings if x is not None]
    # Both Buncombe + Gaston are in the 11-county NC footprint.
    assert len(listings) == 2

    b = next(x for x in listings if x.county == "Buncombe")
    assert b.state == "NC"
    assert b.listing_type == ListingType.FORECLOSURE_SALE
    assert b.street_address == "18 Olive St"
    assert b.city == "Asheville"
    assert b.zip_code == "28801"
    assert b.case_number == "21SP000183-100"
    assert b.sale_time == "10:30"
    assert b.foreclosure_process == "power_of_sale"
    assert b.trustee == "Shapiro & Ingle, LLP"

    g = next(x for x in listings if x.county == "Gaston")
    # SALE_DATE "01/05/26 Cancelled Until 07/16" -> effective 2026-07-16, cancelled.
    assert g.auction_status == "cancelled"
    assert g.sale_date == datetime(2026, 7, 16)
    assert g.opening_bid == 427000.0


def test_row_to_listing_drops_out_of_scope():
    rec = {
        "OFFICE_CODE": "NC",
        "CASE_TYPE_NAME": "Foreclosure",
        "COUNTY_NAME": "Wake",  # denied county
        "SALE_DATE": "01/05/26",
        "CASE_COURT_NUMB": "25SP000001-910",
        "FULL_ADDRESS": "1 Fayetteville St, Raleigh, North Carolina 27601",
    }
    assert _row_to_listing(rec, "law_firms.shapiro_ingle_powerbi") is None


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.shapiro_ingle_powerbi" in {s.slug for s in all_scrapers()}


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live wabi analysis.windows.net — set RUN_NETWORK_TESTS=1",
)
def test_live_returns_in_scope_nc_docket():
    out = list(asyncio.run(ShapiroInglePowerBI().fetch()))
    assert out, "expected a non-empty in-scope NC docket"
    for li in out:
        assert li.state == "NC"
        assert li.listing_type == ListingType.FORECLOSURE_SALE
        assert li.county
        assert li.street_address  # feed carries a full address on every row
