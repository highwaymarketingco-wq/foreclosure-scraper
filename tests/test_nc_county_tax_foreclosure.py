"""NC county in-rem tax-foreclosure scraper (Gaston/McDowell/Rutherford).

Discovered 2026-06-16. Tax foreclosures are a separate track from the
eCourts mortgage pipeline; these county pages are the only public surface.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_nc.nc_county_tax_foreclosure import (
    COUNTY_PAGES,
    NCCountyTaxForeclosure,
    parse_text,
)


def test_parse_extracts_file_parcel_bid_addr():
    text = ("Upcoming Tax Foreclosure Sales  "
            "File 25 M 388 Parcel 1728-00-88-4682 128 Boiler Rd current bid $19,845.00 "
            "sale Dec 19, 2024  "
            "File 26-CVD-178 Parcel 1703-00-95-0253 minimum bid $7,000.00")
    out = parse_text(text, "Rutherford", "http://x")
    assert len(out) == 2
    first = out[0]
    assert first.case_number == "25 M 388"
    assert first.county == "Rutherford"
    assert first.state == "NC"
    assert first.opening_bid == 19845.0
    assert "Boiler Rd" in (first.street_address or "")


def test_parse_dedupes_repeat_file_numbers():
    text = "File 25 M 388 $1,000.00 ... again File 25 M 388 $1,000.00"
    out = parse_text(text, "Gaston", "http://x")
    assert len(out) == 1


def test_parse_empty_when_no_file_numbers():
    assert parse_text("No active tax foreclosure sales at this time.", "Polk", "http://x") == []


def test_in_scope_counties_only():
    assert set(COUNTY_PAGES) == {"Gaston", "McDowell", "Rutherford"}


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.nc_county_tax_foreclosure" in {s.slug for s in all_scrapers()}


@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="live stealth fetch")
def test_live_returns_tax_foreclosures():
    out = list(asyncio.run(NCCountyTaxForeclosure().fetch()))
    for li in out:
        assert li.state == "NC"
        assert li.county in COUNTY_PAGES
        assert li.case_number
