"""counties_nc.cleveland_tax_foreclosure — ninja_clmn_nm_salestatus gap (audit 2026-10-01).

Per-source extraction audit (docs/HERMES.md sec 8): the live Ninja-Tables grid at
Cleveland County's in-house tax-foreclosure page carries an 11th column,
`ninja_clmn_nm_salestatus`, live-verified 2026-10-01 against the real page --
but `_parse_sales_table` never read it, so every scheduled-sale row landed with
`Listing.auction_status` unset even once a sale actually closed ("Sold" /
"Cancelled" / "Redeemed", the same lifecycle gaston_tax_foreclosures.py already
tracks). Today's live page has 8 active rows, all genuinely blank (none has
sold yet) -- this fixture synthesizes the populated case to prove the
extraction + classification actually works once the county fills it in.

counties_nc.cleveland_tax.py scrapes the SAME URL/grid under a different slug
and got the identical fix in the same pass; see that file's test for the
fuller parser test suite (two-parcel rows, property-kind mapping, inline
upset-bid/pending parsing). This file covers only the new column.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.cleveland_tax_foreclosure import (
    _parse_sales_table,
    _status_class,
)

ROW_TMPL = """
<table>
<tbody>
<tr class="ninja_table_row">
  <td class="ninja_column_0 ninja_clmn_nm_county">Cleveland</td>
  <td class="ninja_column_1 ninja_clmn_nm_address">124 Galilee Church Rd, Kings Mountain</td>
  <td class="ninja_column_2 ninja_clmn_nm_parcel">12811</td>
  <td class="ninja_column_3 ninja_clmn_nm_saledatetime">6/25/2026 11:00:00 AM</td>
  <td class="ninja_column_4 ninja_clmn_nm_openingbid">$20,100.00</td>
  <td class="ninja_column_5 ninja_clmn_nm_currentbid">&nbsp;</td>
  <td class="ninja_column_6 ninja_clmn_nm_closedate">7/6/2026</td>
  <td class="ninja_column_7 ninja_clmn_nm_propertytype">Residential Home</td>
  <td class="ninja_column_8 ninja_clmn_nm_courtfile">25CV003450-220</td>
  <td class="ninja_column_9 ninja_clmn_nm_ourfile">24491</td>
  <td class="ninja_column_10 ninja_clmn_nm_salestatus">{status}</td>
</tr>
</tbody>
</table>
"""


def test_status_class_mapping():
    # _status_class receives already-decoded text (via _text()/_lines(), which
    # strips/decodes &nbsp; before this ever runs) -- see
    # test_blank_salestatus_leaves_auction_status_none below for that path.
    assert _status_class(None) is None
    assert _status_class("") is None
    assert _status_class("Sale Closed-Property Sold") == "sold"
    assert _status_class("Settled, Sale Cancelled") == "cancelled"
    assert _status_class("Settled- Property Redeemed") == "redeemed"


def test_blank_salestatus_leaves_auction_status_none():
    rows = _parse_sales_table(ROW_TMPL.format(status="&nbsp;"))
    assert len(rows) == 1
    assert rows[0].auction_status is None
    assert rows[0].raw["cleveland_tax_foreclosure"]["sale_status_raw"] is None
    assert rows[0].raw["cleveland_tax_foreclosure"]["status_class"] is None


def test_populated_salestatus_is_captured_and_classified():
    rows = _parse_sales_table(ROW_TMPL.format(status="Sale Closed-Property Sold"))
    assert len(rows) == 1
    li = rows[0]
    assert li.auction_status == "sold"
    assert li.raw["cleveland_tax_foreclosure"]["sale_status_raw"] == "Sale Closed-Property Sold"
    assert li.raw["cleveland_tax_foreclosure"]["status_class"] == "sold"


def test_cancelled_salestatus_is_classified():
    rows = _parse_sales_table(ROW_TMPL.format(status="Settled, Sale Cancelled"))
    assert rows[0].auction_status == "cancelled"
