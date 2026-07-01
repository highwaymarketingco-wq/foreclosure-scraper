"""Tests for the offline SC Public Index export parser.

Fixtures are SYNTHETIC — small representative ``ContentPlaceHolder1_SearchResults``
tables built inline covering the foreclosure / partition / possession / judgment
lanes, plus a malformed row, a duplicate case number, and a disclaimer-only page.

Also asserts the parser module imports NO fetcher (grep its own source).
"""
from __future__ import annotations

import inspect
import re

from foreclosure_scraper import ingest_sc_publicindex_export as mod
from foreclosure_scraper.ingest_sc_publicindex_export import (
    lane_for_subtype,
    parse_publicindex_html,
)
from foreclosure_scraper.models import ListingType


# --------------------------------------------------------------------------- #
# Synthetic fixtures
# --------------------------------------------------------------------------- #

def _table(rows: str) -> str:
    return f"""
    <html><body>
    <table id="ContentPlaceHolder1_SearchResults">
      <tr>
        <th>Case Number</th><th>Filed Date</th><th>Case Status</th>
        <th>Subtype</th><th>Party Type</th><th>Name</th>
        <th>Judgment Amount</th>
      </tr>
      {rows}
    </table>
    </body></html>
    """


# County codes: 42=Spartanburg, 04=Anderson, 39=Pickens, 23=Greenville.
MIXED_HTML = _table(
    """
    <tr class="standardRow">
      <td title="US BANK NA VS Doe Jane, defendant"><a>2026CP4201547</a></td>
      <td>05/01/2026</td><td>Active</td>
      <td>Foreclosure 420</td><td>Defendant</td><td>Doe Jane</td><td></td>
    </tr>
    <tr class="altRow">
      <td title="Heir Alpha VS Heir Beta"><a>2026-CP-04-00099</a></td>
      <td>04/15/2026</td><td>Active</td>
      <td>Partition of Real Property</td><td>Plaintiff</td><td>Heir Alpha</td><td></td>
    </tr>
    <tr class="standardRow">
      <td title="LANDLORD LLC VS Renter Rick"><a>2026CP3900123</a></td>
      <td>06/02/2026</td><td>Active</td>
      <td>Ejectment / Possession</td><td>Defendant</td><td>Renter Rick</td><td></td>
    </tr>
    <tr class="altRow">
      <td title="ACME FINANCE VS Owen Owner"><a>2026-CP-23-04567</a></td>
      <td>03/10/2026</td><td>Judgment Entered</td>
      <td>Transcript of Judgment</td><td>Defendant</td><td>Owen Owner</td>
      <td>$12,345.67</td>
    </tr>
    <!-- malformed: no parseable SC case number -->
    <tr class="standardRow">
      <td title="SOMEBODY VS Nobody"><a>NOT-A-CASE</a></td>
      <td>01/01/2026</td><td>Active</td>
      <td>Foreclosure 420</td><td>Defendant</td><td>Nobody</td><td></td>
    </tr>
    <!-- duplicate of the first foreclosure case number (second party row) -->
    <tr class="altRow">
      <td title="US BANK NA VS Doe John, defendant, et al"><a>2026CP4201547</a></td>
      <td>05/01/2026</td><td>Active</td>
      <td>Foreclosure 420</td><td>Defendant</td><td>Doe John</td><td></td>
    </tr>
    """
)

DISCLAIMER_ONLY_HTML = """
<html><body>
  <h1>Public Index Disclaimer</h1>
  <p>By using this site you agree to the terms...</p>
  <input type="submit" id="ContentPlaceHolder1_ButtonAccept" value="Accept" />
</body></html>
"""


# --------------------------------------------------------------------------- #
# Row counts
# --------------------------------------------------------------------------- #

def test_row_count_dedup_and_malformed_dropped():
    listings = parse_publicindex_html(MIXED_HTML)
    # 4 unique valid rows: 1 foreclosure (dupe collapsed) + partition +
    # possession + judgment. Malformed row dropped.
    assert len(listings) == 4
    cases = sorted(li.case_number for li in listings)
    assert cases == [
        "2026-CP-04-00099",
        "2026-CP-23-04567",
        "2026-CP-39-00123",
        "2026-CP-42-01547",
    ]


def test_disclaimer_only_page_yields_empty():
    assert parse_publicindex_html(DISCLAIMER_ONLY_HTML) == []


def test_empty_html_yields_empty():
    assert parse_publicindex_html("") == []


# --------------------------------------------------------------------------- #
# Lane mapping
# --------------------------------------------------------------------------- #

def test_lane_for_subtype_mapping():
    assert lane_for_subtype("Foreclosure 420") == ListingType.LIS_PENDENS
    assert lane_for_subtype("Partition of Real Property") == ListingType.LIS_PENDENS
    assert lane_for_subtype("Ejectment / Possession") == ListingType.LIS_PENDENS
    assert lane_for_subtype("State Tax Lien") == ListingType.TAX_LIEN
    assert lane_for_subtype("Transcript of Judgment") == ListingType.LIS_PENDENS
    assert lane_for_subtype("Something Unknown") is None
    assert lane_for_subtype("") is None


def test_listing_type_per_lane():
    by_case = {li.case_number: li for li in parse_publicindex_html(MIXED_HTML)}
    assert by_case["2026-CP-42-01547"].listing_type == ListingType.LIS_PENDENS  # foreclosure
    assert by_case["2026-CP-04-00099"].listing_type == ListingType.LIS_PENDENS  # partition
    assert by_case["2026-CP-39-00123"].listing_type == ListingType.LIS_PENDENS  # possession
    assert by_case["2026-CP-23-04567"].listing_type == ListingType.LIS_PENDENS  # judgment


def test_tax_lien_lane():
    html = _table(
        """
        <tr class="standardRow">
          <td title="SC DEPT OF REVENUE VS Delinquent Dan"><a>2026-CP-42-07777</a></td>
          <td>02/01/2026</td><td>Active</td>
          <td>State Tax Lien</td><td>Defendant</td><td>Delinquent Dan</td><td></td>
        </tr>
        """
    )
    listings = parse_publicindex_html(html)
    assert len(listings) == 1
    assert listings[0].listing_type == ListingType.TAX_LIEN


def test_subtype_stashed_in_raw():
    by_case = {li.case_number: li for li in parse_publicindex_html(MIXED_HTML)}
    li = by_case["2026-CP-04-00099"]
    assert li.raw["sc_public_index"]["subtype"] == "Partition of Real Property"
    # every row carries the exact subtype text, foreclosure included
    fc = by_case["2026-CP-42-01547"]
    assert fc.raw["sc_public_index"]["subtype"] == "Foreclosure 420"


# --------------------------------------------------------------------------- #
# Party / county / judgment extraction
# --------------------------------------------------------------------------- #

def test_plaintiff_defendant_from_title_attr():
    by_case = {li.case_number: li for li in parse_publicindex_html(MIXED_HTML)}
    li = by_case["2026-CP-42-01547"]
    assert li.plaintiff == "US BANK NA"
    # trailing ", defendant" role tag stripped
    assert li.defendant == "Doe Jane"


def test_county_decoded_from_case_number():
    by_case = {li.case_number: li for li in parse_publicindex_html(MIXED_HTML)}
    assert by_case["2026-CP-42-01547"].county == "Spartanburg"
    assert by_case["2026-CP-04-00099"].county == "Anderson"
    assert by_case["2026-CP-39-00123"].county == "Pickens"
    assert by_case["2026-CP-23-04567"].county == "Greenville"


def test_default_county_fallback_when_case_decode_fails():
    # county code 99 doesn't exist -> falls back to default_county arg.
    html = _table(
        """
        <tr class="standardRow">
          <td title="BANK VS Person"><a>2026-CP-99-00001</a></td>
          <td>05/01/2026</td><td>Active</td>
          <td>Foreclosure 420</td><td>Defendant</td><td>Person</td><td></td>
        </tr>
        """
    )
    listings = parse_publicindex_html(html, default_county="Spartanburg")
    assert len(listings) == 1
    assert listings[0].county == "Spartanburg"


def test_judgment_amount_captured():
    by_case = {li.case_number: li for li in parse_publicindex_html(MIXED_HTML)}
    assert by_case["2026-CP-23-04567"].judgment_amount == 12345.67


def test_keep_all_subtypes_flag():
    html = _table(
        """
        <tr class="standardRow">
          <td title="X VS Y"><a>2026-CP-42-00001</a></td>
          <td>05/01/2026</td><td>Active</td>
          <td>Mechanics Lien</td><td>Defendant</td><td>Y</td><td></td>
        </tr>
        """
    )
    # default: unknown lane skipped
    assert parse_publicindex_html(html) == []
    # keep-all: emitted as UNKNOWN
    kept = parse_publicindex_html(html, keep_all_subtypes=True)
    assert len(kept) == 1
    assert kept[0].listing_type == ListingType.UNKNOWN
    assert kept[0].raw["sc_public_index"]["subtype"] == "Mechanics Lien"


def test_source_and_state_stamped():
    li = parse_publicindex_html(MIXED_HTML)[0]
    assert li.source == "counties_sc.sc_public_index_export"
    assert li.state == "SC"


# --------------------------------------------------------------------------- #
# Compliance: the module must import NO fetcher.
# --------------------------------------------------------------------------- #

def test_module_imports_no_fetcher():
    src = inspect.getsource(mod)
    for banned in ("httpx", "StealthyFetcher", "requests", "playwright", "scrapling"):
        assert not re.search(rf"\b{re.escape(banned)}\b", src), (
            f"offline parser must not reference {banned!r}"
        )
