"""Offline tests for the Buncombe/Gaston Aumentum (Cott eSearch v4) ROD parser.

Fixture mirrors the LIVE cpgvInstruments grid (re-captured 2026-07-01): rows are
<tr class="cottPagedGridViewRowStyle">/"cottPagedGridViewAltRowStyle" with 14
direct-child <td> [row#, Date Filed, Index, Type, Grantor, Grantee, Description,
File Number, Book/Page, Ref, Images, GIS, Tax, spacer]. The Grantor/Grantee cells
embed NESTED <table>s (which is why a naive <tr>-regex parser undercounts cells),
and one row has a MASKED date ('**/**/2026', a protected DTH doc) that the parser
must KEEP with recorded_date=None. CI never hits the network.
"""
from foreclosure_scraper.rod.aumentum import (
    _parse_instruments_grid,
    _is_nod,
    _is_post_sale,
    _split_book_page,
    _parse_date,
)
from foreclosure_scraper.rod.classify import classify_rod_docs
from foreclosure_scraper.enrichment_aumentum_rod import _owner_doc, _name_parts

# Real-shape fixture: header row + 3 data rows (a Deed of Trust, a Satisfaction,
# and a masked-date protected doc). Grantor/Grantee use nested <table> like live.
SAMPLE = """
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
       class="cottPagedGridView">
  <tr class="cottPagedGridViewHeaderStyle">
    <th>&nbsp;</th><th>Date Filed</th><th>Index</th><th>Type</th><th>Grantor</th>
    <th>Grantee</th><th>Description</th><th>File Number</th><th>Book/Page</th>
    <th>Ref</th><th>Images</th><th>GIS</th><th>Tax</th><th></th>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>1</td>
    <td align="center">11/30/2022<br><span class="StatusDate">Date Filed<br />11/30/2022</span></td>
    <td>CRP</td><td>DEED OF TRUST</td>
    <td><div title='Collapsed'><table width='100%'><tr><td colspan='2'>SMITH, JOHN WESLEY SMITH, DEBORAH L</td></tr></table></td>
    <td><table><tr><td>BANK OF AMERICA</td></tr></table></td>
    <td>LOT 5</td><td>2022012345</td><td>6279 / 1440</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
  <tr class="cottPagedGridViewAltRowStyle">
    <td>3</td><td>12/03/2025</td><td>CRP</td><td>DEED OF TRUST SATISFACTION</td>
    <td><table><tr><td>SMITH, JOHN T./ III SMITH, KATHERINE O.</td></tr></table></td>
    <td><table><tr><td>MORTGAGE ELECTRONIC REGISTRATION SYSTEMS, INC.</td></tr></table></td>
    <td></td><td></td><td>6547 / 1497</td><td>5406 / 1411</td><td>1</td><td></td><td></td><td></td>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>5</td>
    <td align="center">**/**/2026<br><span class="StatusDate">Date Filed<br />**/**/2026</span></td>
    <td>DTH</td><td></td>
    <td><table><tr><td>SMITH, MARK</td></tr></table></td>
    <td><table><tr><td>SMITH, JOHNNIE ROBERT</td></tr></table></td>
    <td></td><td></td><td>113 / 1047</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
</table>
"""


def test_parses_all_three_rows_including_masked_date():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    # Old parser dropped the masked-date row (no MM/DD/YYYY) and broke on nested
    # tables — the rebuilt parser keeps all 3.
    assert len(rows) == 3


def test_nested_table_grantor_and_bookpage_split():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    r0 = rows[0]
    assert r0.grantor and "SMITH, JOHN WESLEY" in r0.grantor   # nested-table cell text
    assert r0.grantee and "BANK OF AMERICA" in r0.grantee
    assert r0.book == "6279" and r0.page == "1440"             # Book/Page split on '/'
    assert r0.instrument_no == "2022012345"                    # File Number column (td7)
    assert r0.recorded_date is not None and r0.recorded_date.year == 2022


def test_masked_date_row_kept_with_none_date():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    masked = [r for r in rows if r.grantor and "SMITH, MARK" in r.grantor]
    assert len(masked) == 1
    assert masked[0].recorded_date is None       # '**/**/2026' -> None, row retained
    assert masked[0].book == "113"               # still carries book/page signal


def test_classify_flags_mortgage():
    docs = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    summ = classify_rod_docs(docs, "aumentum_rod")
    assert summ["instrument_count"] == 3
    assert summ["has_mortgage"] is True          # DEED OF TRUST present
    # Both the DT and the 'DEED OF TRUST SATISFACTION' normalize to the mortgage
    # bucket (longest-key-first match prefers 'DEED OF TRUST'), so >=2 mortgages.
    assert summ["mortgage_count"] >= 2


def test_owner_filter_matches_target_owner():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    last, first = _name_parts("SMITH, JOHN")
    mine = [r for r in rows if _owner_doc(r, last, first)]
    assert len(mine) >= 2   # the DT + the satisfaction both name SMITH, JOHN


def test_gaston_terse_type_codes_parse():
    # Gaston renders terse Type codes (D/T, SAT, S/TR) instead of full words.
    gaston = SAMPLE.replace("DEED OF TRUST SATISFACTION", "SAT").replace("DEED OF TRUST", "D/T")
    rows = _parse_instruments_grid(gaston, "Gaston", "NC")
    assert len(rows) == 3
    summ = classify_rod_docs(rows, "aumentum_rod")
    assert summ["has_mortgage"] is True          # 'D/T' recognised as mortgage
    assert summ["satisfaction_count"] >= 1        # terse 'SAT' code classifies as satisfaction


def test_helpers():
    assert _split_book_page("6279 / 1440") == ("6279", "1440")
    assert _split_book_page("") == (None, None)
    assert _parse_date("**/**/2026") is None
    assert _parse_date("12/03/2025").year == 2025
    assert _is_nod("NOTICE OF SALE") is True
    assert _is_nod("DEED") is False
    assert _is_post_sale("SUBSTITUTE TRUSTEE'S DEED") is True
    assert _is_post_sale("DEED OF TRUST") is False


def test_empty():
    assert _parse_instruments_grid("", "Buncombe", "NC") == []
    assert _parse_instruments_grid("<html><body>no grid</body></html>", "Buncombe", "NC") == []
