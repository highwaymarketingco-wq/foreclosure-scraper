"""Pin the Permitium NC ROD search-results HTML parser.

Permitium tenants vary in HTML structure but the documented common
patterns (table.results-table, table.search-results, div.result-card,
generic table tbody tr fallback) cover most observed configurations.
These tests use synthetic HTML mirroring those patterns.

Note: the live Buncombe Permitium portal (buncombe-recordings.permitium.com)
was DNS-blocked from the dev sandbox, so the parser is tested against
synthetic-but-pattern-faithful HTML. First CI run with the live portal
will surface real structure via the nc_rod.permitium_landing log if
this parser misses anything; targeted refinements land in follow-ups.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_rod_substitute_trustee import (
    _parse_permitium_results_html,
    _sold_price_from_stamp,
)


def test_parses_table_results_with_trustees_deed():
    """Trustee's Deed Upon Sale row with deed-tax stamp -> sold_price set,
    sale_date set."""
    html = """
    <table class="results-table">
      <tbody>
        <tr>
          <td>Inst # 12345678</td>
          <td>Recorded On: 04/15/2026</td>
          <td>Trustee's Deed Upon Sale</td>
          <td>Grantor: Smith John</td>
          <td>EXCISE TAX: $50.00</td>
        </tr>
      </tbody>
    </table>
    """
    listings = _parse_permitium_results_html(
        html, county="Buncombe",
        source_url="https://buncombe-recordings.permitium.com/",
        doc_type="Trustee's Deed Upon Sale",
    )
    assert len(listings) == 1
    li = listings[0]
    assert li.county == "Buncombe"
    assert li.state == "NC"
    assert li.opening_bid == 25000.0  # $50 stamp * 500
    assert li.raw["actual_sold_price"] == 25000.0
    assert li.case_number == "INST-12345678"
    assert "Smith John" in (li.defendant or "")


def test_parses_substitute_trustee_deed_pre_sale():
    """Substitute Trustee Deed = pre-sale appointment, no price expected."""
    html = """
    <table class="search-results">
      <tbody>
        <tr>
          <td>Inst # 87654321</td>
          <td>Recorded: 03/22/2026</td>
          <td>Substitute Trustee Deed</td>
          <td>Defendant: Brown Jane</td>
        </tr>
      </tbody>
    </table>
    """
    listings = _parse_permitium_results_html(
        html, county="Buncombe", source_url="https://x/",
        doc_type="Substitute Trustee Deed",
    )
    assert len(listings) == 1
    li = listings[0]
    assert li.opening_bid is None  # no stamp = no price
    assert "actual_sold_price" not in li.raw


def test_parses_div_card_results_format():
    """Some Permitium tenants use card-style div layouts instead of tables."""
    html = """
    <div class="results">
      <div class="result-card">
        Notice of Sale Inst # 99999000 Recorded: 05/01/2026
        Grantor: Acme Bank Notice of foreclosure sale
      </div>
    </div>
    """
    listings = _parse_permitium_results_html(
        html, county="Buncombe", source_url="https://x/",
        doc_type="Notice of Sale",
    )
    assert len(listings) == 1
    assert listings[0].case_number == "INST-99999000"


def test_skips_unrelated_document_types():
    """A Mortgage / Deed of Trust / Release row in the same table
    should be skipped — we only want foreclosure-relevant docs.
    Instrument numbers in real Permitium tenants are 8+ digits."""
    html = """
    <table class="results-table">
      <tbody>
        <tr><td>Inst # 20260111 Mortgage Recorded: 01/01/2026 Grantor: Foo</td></tr>
        <tr><td>Inst # 20260222 Trustee's Deed Upon Sale Recorded: 02/02/2026 EXCISE TAX: $80.00 Grantor: Bar</td></tr>
        <tr><td>Inst # 20260333 Release of Lien Recorded: 03/03/2026 Grantor: Baz</td></tr>
      </tbody>
    </table>
    """
    listings = _parse_permitium_results_html(
        html, county="Buncombe", source_url="https://x/",
        doc_type="Trustee's Deed Upon Sale",
    )
    assert len(listings) == 1
    assert listings[0].case_number == "INST-20260222"
    assert listings[0].raw["actual_sold_price"] == 40000.0


def test_book_page_used_when_no_instrument():
    """Some recordings reference book/page instead of instrument#."""
    html = """
    <table class="results-table">
      <tbody>
        <tr>
          <td>Trustee's Deed Upon Sale Book 5432 Page 109 Recorded: 04/15/2026
              EXCISE TAX: $100.00 Grantor: Doe John</td>
        </tr>
      </tbody>
    </table>
    """
    listings = _parse_permitium_results_html(
        html, county="Buncombe", source_url="https://x/",
        doc_type="Trustee's Deed Upon Sale",
    )
    assert len(listings) == 1
    assert listings[0].case_number == "BK5432-PG109"


def test_empty_html_returns_empty():
    assert _parse_permitium_results_html("", "Buncombe", "https://x/", "Notice of Sale") == []


def test_html_with_no_recognizable_rows_returns_empty():
    """Ad-only / placeholder pages — nothing to parse."""
    html = "<html><body><h1>Search</h1><p>No results found.</p></body></html>"
    assert _parse_permitium_results_html(html, "Buncombe", "https://x/", "Notice of Sale") == []


# ---- top-level _sold_price_from_stamp sanity (integration) ----

def test_consideration_pattern_used_by_permitium():
    """Some Permitium tenants surface 'Consideration: $X' explicitly."""
    text = "Trustee's Deed Upon Sale Inst#123 CONSIDERATION: $87,500.00"
    assert _sold_price_from_stamp(text) == 87500.0
