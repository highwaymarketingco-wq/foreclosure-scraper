"""Greenville SC Master-in-Equity adverts: TMS + the actual judgment debt.

docs/blocked_sources_forensic.md recorded "SC PublicIndex — per-case DETAIL (TMS +
judgment $)" as ABSENT, reasoning that the detail sits behind __doPostBack links that are
dead in a saved HTML file. That reasoned from the wrong artifact. The Master-in-Equity is
REQUIRED to advertise every foreclosure sale, and Greenville publishes those adverts as
ordinary web pages. publicindex.sccourts.org is never touched, so the ToS wall stands.

Live 2026-09-11: 772 adverts enumerable, 40/40 sampled parsed with BOTH a TMS and a
judgment amount.

The judgment figure is what makes this valuable: it is the actual debt against the
property, not an estimate. calc.est_gross_margin -- the input to the margin-covers-
curative test that IS the buy box -- was populated on 1,297 of 94,384 board rows, 1.4%.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.greenville_mie_adverts import (
    SITEMAP, parse_advert, parse_sitemap,
)

#: Trimmed verbatim from https://mie.greenvillejournal.com/advert/2022-cp-23-03386/
REAL = """
<html><body>
<p>STATE OF SOUTH CAROLINA COUNTY OF GREENVILLE</p>
<p>Case No. 2022-CP-23-03386</p>
<p>AmeriHome Mortgage Company, LLC,<br/>Plaintiff,<br/>vs.<br/>
Jane Q Homeowner,<br/>Defendant.</p>
<p>BY VIRTUE of a decree heretofore granted, I will sell on 08/07/2023 at public auction.</p>
<p>TMS map: 0577040104000</p>
<p>THE STREET ADDRESS IS:<br/>4002 Fork Shoals Rd Simpsonville, SC 29680</p>
<p>the total judgment debt set forth in the Order is $161,897.79 plus interest.</p>
</body></html>
"""

URL = "https://mie.greenvillejournal.com/advert/2022-cp-23-03386/"


def test_every_field_the_buy_box_needs():
    li = parse_advert(URL, REAL)
    assert li is not None
    assert li.case_number == "2022-CP-23-03386"
    assert li.parcel_id == "0577040104000"
    assert li.judgment_amount == 161897.79
    assert li.street_address == "4002 Fork Shoals Rd Simpsonville"
    assert li.zip_code == "29680"
    assert li.sale_date is not None and li.sale_date.strftime("%m/%d/%Y") == "08/07/2023"
    assert li.state == "SC" and li.county == "Greenville"
    assert li.raw["greenville_mie"]["total_judgment_debt"] == 161897.79


def test_the_judgment_amount_is_parsed_as_a_number_not_a_string():
    """It feeds arithmetic. A '$161,897.79' string silently breaks every margin calc."""
    li = parse_advert(URL, REAL)
    assert isinstance(li.judgment_amount, float)


@pytest.mark.parametrize("tms", ["0577040104000", "0028.01-01-007.00", "030000114300"])
def test_the_real_tms_formats_all_parse(tms):
    """Greenville mixes a 13-digit form and a dotted/dashed form; both are live."""
    li = parse_advert(URL, REAL.replace("0577040104000", tms))
    assert li.parcel_id == tms


def test_a_row_with_neither_parcel_nor_address_is_not_a_lead():
    """It could not be underwritten, joined to the assessor, or routed to a county."""
    stripped = REAL.replace("TMS map: 0577040104000", "").replace(
        "THE STREET ADDRESS IS:<br/>4002 Fork Shoals Rd Simpsonville, SC 29680", "")
    assert parse_advert(URL, stripped) is None


def test_a_missing_judgment_does_not_lose_the_lead():
    """No dollar figure is a weaker lead, not a discarded one."""
    li = parse_advert(URL, REAL.replace(
        "the total judgment debt set forth in the Order is $161,897.79 plus interest.", ""))
    assert li is not None
    assert li.judgment_amount is None
    assert li.parcel_id == "0577040104000"


def test_the_case_number_falls_back_to_the_url_slug():
    """The slug IS the case number, which is also the join key to any SC case list."""
    li = parse_advert(URL, "<html><body>TMS map: 0577040104000</body></html>")
    assert li.case_number == "2022-CP-23-03386"


# --------------------------------------------------------------------------
# The sitemap answers HTTP 404 while serving 772 valid entries
# --------------------------------------------------------------------------

def test_the_sitemap_parses_regardless_of_status_code():
    """THE trap. wp-sitemap-posts-advert-1.xml returns 404 with 96KB of valid XML. A
    probe that checks the status and stops sees nothing -- the same shape as the qPayBill
    detail page written off for a wrong URL: the status said no, the body said yes."""
    xml = ('<?xml version="1.0"?><urlset>'
           '<url><loc>https://mie.greenvillejournal.com/advert/2022-cp-23-03386/</loc></url>'
           '<url><loc>https://mie.greenvillejournal.com/advert/2026-cp-23-00730/</loc></url>'
           '</urlset>')
    got = parse_sitemap(xml)
    assert len(got) == 2
    assert got[0].endswith("/advert/2022-cp-23-03386/")


def test_the_sitemap_parser_ignores_non_advert_urls_and_dedupes():
    xml = ('<urlset>'
           '<url><loc>https://mie.greenvillejournal.com/advert/a/</loc></url>'
           '<url><loc>https://mie.greenvillejournal.com/advert/a/</loc></url>'
           '<url><loc>https://mie.greenvillejournal.com/about/</loc></url>'
           '</urlset>')
    assert parse_sitemap(xml) == ["https://mie.greenvillejournal.com/advert/a/"]


def test_empty_sitemap_yields_nothing_rather_than_raising():
    assert parse_sitemap("") == []
    assert parse_sitemap("<urlset></urlset>") == []


def test_the_sitemap_url_is_the_advert_post_type():
    assert SITEMAP.endswith("wp-sitemap-posts-advert-1.xml")
