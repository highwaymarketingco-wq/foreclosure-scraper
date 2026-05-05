"""Regression tests for the SC Public Index lis-pendens scraper.

The scraper queries each county portal in turn and tags returned listings
with the iteration county. We add a defense-in-depth check that decodes
the county from the case# prefix (authoritative venue per SC §15-11-10);
if the decoded county disagrees with the queried county, the case#
decoding wins and a warning is logged.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.sc_public_index_lis_pendens import (
    _county_from_case,
    _parse_results,
)


def test_county_from_case_anderson():
    assert _county_from_case("2026-CP-04-12345") == "Anderson"


def test_county_from_case_spartanburg():
    assert _county_from_case("2026-CP-42-99999") == "Spartanburg"


def test_county_from_case_charleston():
    assert _county_from_case("2026-CP-10-00001") == "Charleston"


def test_county_from_case_unknown_code():
    assert _county_from_case("2026-CP-99-00001") is None


def test_county_from_case_invalid_format():
    assert _county_from_case("garbage") is None


def test_county_from_case_none():
    assert _county_from_case("") is None


def test_parser_uses_case_decoded_county_when_disagrees():
    """Hypothetical: SC portal returned a Cherokee (11) case under the
    Spartanburg endpoint due to portal cross-listing. Scraper must tag
    the case with Cherokee (case# truth) not Spartanburg (queried)."""
    html = """
    <table id="ContentPlaceHolder1_SearchResults">
      <tr><th>Case Number</th><th>Filed Date</th><th>Case Status</th>
          <th>Subtype</th><th>Party Type</th><th>Name</th></tr>
      <tr class="standardRow">
        <td title="LENDER VS Smith John"><a>2026CP1199999</a></td>
        <td>05/01/2026</td>
        <td>Active</td>
        <td>Foreclosure 420</td>
        <td>Defendant</td>
        <td>Smith John</td>
      </tr>
    </table>
    """
    listings = _parse_results(html, "Spartanburg")
    assert len(listings) == 1
    li = listings[0]
    # Case decodes to Cherokee → that wins over queried Spartanburg.
    assert li.county == "Cherokee", f"got {li.county!r}"
    assert li.case_number == "2026-CP-11-99999"


def test_parser_uses_queried_county_when_case_decode_fails():
    """If the case# is malformed or decodes to no known county, fall back
    to the iteration county (the URL we hit must be a real SC county)."""
    html = """
    <table id="ContentPlaceHolder1_SearchResults">
      <tr><th>Case Number</th><th>Filed Date</th><th>Case Status</th>
          <th>Subtype</th><th>Party Type</th><th>Name</th></tr>
      <tr class="standardRow">
        <td title="LENDER VS Smith John"><a>BAD-FORMAT</a></td>
        <td>05/01/2026</td>
        <td>Active</td>
        <td>Foreclosure 420</td>
        <td>Defendant</td>
        <td>Smith John</td>
      </tr>
    </table>
    """
    listings = _parse_results(html, "Spartanburg")
    # Either the malformed case# was filtered out (acceptable) or it
    # falls back to Spartanburg.
    if listings:
        assert listings[0].county == "Spartanburg"
