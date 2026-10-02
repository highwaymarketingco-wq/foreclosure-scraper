"""fdic_failed_banks.py's State column is a full name ("Pennsylvania"), but
downstream scope checks compare state.upper() against "NC"/"SC" -- a full
name would never match, silently dropping any in-footprint bank failure.
Found in the 2026-09-15 national.* zero-row audit; currently latent (no
NC/SC failures exist right now) but worth locking in.

2026-10-01 (batch-5 extraction-completeness audit): the live table has a
7th column (Fund #) the module's own docstring already named but the code
never read, and the Bank Name cell carries a per-bank FDIC detail-page link
that every row discarded in favor of one shared generic source_url (same bug
class as counties_generic.epa_frs_sites, fixed the same day). Both fixed
below; see test_fund_number_and_detail_url_captured."""
import asyncio
from datetime import datetime, timedelta

from foreclosure_scraper.scrapers.national import fdic_failed_banks as fdic
from foreclosure_scraper.scrapers.national.fdic_failed_banks import (
    FDICFailedBanks,
    _normalize_state,
)


def test_full_nc_name_normalizes_to_abbreviation():
    assert _normalize_state("North Carolina") == "NC"


def test_full_sc_name_normalizes_to_abbreviation():
    assert _normalize_state("South Carolina") == "SC"


def test_case_insensitive():
    assert _normalize_state("north carolina") == "NC"


def test_already_abbreviated_passes_through():
    assert _normalize_state("NC") == "NC"


def test_unrelated_state_passes_through_unchanged():
    assert _normalize_state("Texas") == "Texas"


def test_empty_or_none_is_safe():
    assert _normalize_state("") == ""
    assert _normalize_state(None) == ""


def _sample_table_html(fail_date: str) -> str:
    # Structurally faithful trim of the live table (captured 2026-10-01):
    # Bank Name cell carries the per-bank detail-page link; 7 real columns.
    # Padded past fetch()'s len(html) < 500 "empty response" guard.
    return f"""
    <!-- {"padding " * 60} -->
    <table>
    <tr><th>Bank Name</th><th>City</th><th>State</th><th>Cert</th>
        <th>Acquiring Institution</th><th>Closing Date</th><th>Fund</th></tr>
    <tr>
      <td><a href="/bank-failures/failed-bank-list/nano-banc">Nano Banc</a></td>
      <td>Irvine</td>
      <td>California</td>
      <td>58590</td>
      <td>Sunwest Bank</td>
      <td>{fail_date}</td>
      <td>10555</td>
    </tr>
    </table>
    """


def test_fund_number_and_detail_url_captured(monkeypatch):
    """The docstring already named the real 7th column (Fund #), and the Bank
    Name cell links to a per-bank detail page -- both were previously
    discarded (fund # never read; every row shared one generic source_url)."""
    recent = (datetime.now() - timedelta(days=5)).strftime("%B %d, %Y")

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        return _sample_table_html(recent)

    monkeypatch.setattr(fdic, "get_text", fake_get_text)
    rows = asyncio.run(FDICFailedBanks().fetch())

    assert len(rows) == 1
    li = rows[0]
    assert li.raw["fund_number"] == "10555"
    assert li.source_url == "https://www.fdic.gov/bank-failures/failed-bank-list/nano-banc"
    assert li.raw["cert_number"] == "58590"
    assert li.raw["acquiring_institution"] == "Sunwest Bank"


def test_missing_fund_column_is_tolerated(monkeypatch):
    """A 6-cell row (no Fund # column, e.g. a future markup change dropping
    it) must not crash -- fund_number is simply None."""
    recent = (datetime.now() - timedelta(days=5)).strftime("%B %d, %Y")
    html = f"""
    <!-- {"padding " * 60} -->
    <table><tr>
      <td>Some Bank</td><td>Townsville</td><td>Texas</td>
      <td>12345</td><td>Acquirer Bank</td><td>{recent}</td>
    </tr></table>
    """

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        return html

    monkeypatch.setattr(fdic, "get_text", fake_get_text)
    rows = asyncio.run(FDICFailedBanks().fetch())
    assert len(rows) == 1
    assert rows[0].raw["fund_number"] is None
    assert rows[0].source_url == fdic.PAGE_URL
