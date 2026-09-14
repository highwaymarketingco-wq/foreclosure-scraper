"""Tests for Greenville County SC delinquent tax sale HTML table parser."""
import asyncio
from unittest.mock import patch

from foreclosure_scraper.scrapers.counties_sc.greenville_delinquent_tax import GreenvilleDelinquentTax

SAMPLE_HTML = """
<html><body>
<table>
<tr><th>Item #</th><th>Map #</th><th>Name</th><th>Amount Due</th></tr>
<tr><td>20</td><td>0376000105000</td><td>A S K ENTERPRISES &amp; FUNDING LL</td><td>$3,245.19</td></tr>
<tr><td>24</td><td>0376000105001</td><td>A S K ENTERPRISES &amp; FUNDING LL</td><td>$1,008.83</td></tr>
<tr><td>96068</td><td></td><td>MERHEB MICHAEL</td><td>$1,196.45</td></tr>
<tr><td>96069</td><td></td><td>MICHAEL JANET</td><td>$858.03</td></tr>
<tr><td>1140</td><td>WG02060100600</td><td>BBJ EQUITIES FL LLC</td><td>$3,531.73</td></tr>
</table>
<table>
<tr><td>Monday</td><td>Tuesday</td><td>Hours</td><td>8:30 a.m.</td></tr>
</table>
</body></html>
"""


def _run(html):
    async def fake_get_text(*a, **k):
        return html
    with patch("foreclosure_scraper.scrapers.counties_sc.greenville_delinquent_tax.get_text", fake_get_text):
        return asyncio.run(GreenvilleDelinquentTax().fetch())


def test_parses_real_estate_rows_with_parcel():
    rows = list(_run(SAMPLE_HTML))
    with_parcel = [r for r in rows if r.parcel_id]
    assert len(with_parcel) == 3
    ids = {r.parcel_id for r in with_parcel}
    assert ids == {"0376000105000", "0376000105001", "WG02060100600"}


def test_alpha_prefixed_map_number_is_not_misread_as_personal_property():
    """Regression: an earlier digits-only regex here silently reclassified every
    alpha-prefixed parcel (e.g. condo/mobile-home-park codes) as parcel-less
    personal property, discovered live on 383 of 2,112 real Greenville rows."""
    rows = list(_run(SAMPLE_HTML))
    bbj = next(r for r in rows if r.owner_name == "BBJ EQUITIES FL LLC")
    assert bbj.parcel_id == "WG02060100600"


def test_parses_personal_property_rows_without_parcel():
    rows = list(_run(SAMPLE_HTML))
    no_parcel = [r for r in rows if not r.parcel_id]
    assert len(no_parcel) == 2
    names = {r.owner_name for r in no_parcel}
    assert names == {"MERHEB MICHAEL", "MICHAEL JANET"}


def test_owner_name_and_defendant_both_set():
    rows = list(_run(SAMPLE_HTML))
    for r in rows:
        assert r.owner_name == r.defendant


def test_amount_captured_in_raw_total_due():
    rows = list(_run(SAMPLE_HTML))
    ask = next(r for r in rows if r.parcel_id == "0376000105000")
    assert ask.raw["greenville_delinquent_tax"]["total_due"] == 3245.19


def test_skips_office_hours_junk_row():
    rows = list(_run(SAMPLE_HTML))
    names = {r.owner_name for r in rows}
    assert "Monday" not in names
    assert not any("a.m." in (r.owner_name or "") for r in rows)


def test_no_sale_date_set():
    """DATELESS_OK: this is a standing roster, not a scheduled event."""
    rows = list(_run(SAMPLE_HTML))
    assert all(r.sale_date is None for r in rows)


def test_all_rows_are_tax_sale_type():
    from foreclosure_scraper.models import ListingType
    rows = list(_run(SAMPLE_HTML))
    assert all(r.listing_type == ListingType.TAX_SALE for r in rows)


def test_empty_html():
    assert list(_run("")) == []
    assert list(_run("<html><body>no table here</body></html>")) == []
