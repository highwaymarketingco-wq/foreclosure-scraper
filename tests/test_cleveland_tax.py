"""Offline tests for the Cleveland County NC in-house tax-foreclosure parser.

Cleveland runs its tax sales IN-HOUSE via the county Legal Department. The page
publishes properties in two shapes and the parser must handle BOTH:

1. A "Ninja Tables" grid of SCHEDULED auction sales (semantic `ninja_clmn_nm_*`
   cell classes; real sale date + opening bid). One row can pack two parcels
   (address / parcel cells split on <br>) -> one Listing per parcel. The OLD
   regex-only parser dropped this entire grid.
2. Inline text: the 10-day upset-bid item + "PROPERTIES CURRENTLY IN FORECLOSURE"
   pending items, shaped "Parcel[:] <id> / File # <case#> / Address: <addr> /...".

The fixture mirrors the live 2026 page (captured 2026-07-30). CI never hits the
network. The &nbsp;-padded "/" separators are intentional (live shape).
"""
from foreclosure_scraper.scrapers.counties_nc.cleveland_tax import (
    parse,
    _parse_sales_table,
    _parse_inline,
    _money,
    _lines,
)
from foreclosure_scraper.models import ListingType, PropertyKind
from selectolax.parser import HTMLParser

# Real-shape fixture: Ninja grid (3 rows, first packs 2 parcels via <br>) + the
# inline upset-bid paragraph + the "CURRENTLY IN FORECLOSURE" pending block.
SAMPLE = """
<html><body>
<p>For questions, please contact the legal department at (704) 476-3089 or
e-mail christie.wooten@clevelandcountync.gov. Auctions Scheduled and/or cases
that are currently in the 10-day upset bid period:</p>
<p>1. Parcel 57139 /&nbsp;File # 26CV000065-220 /&nbsp;Address: 2500 Parnell
Drive, Shelby / Map 6-4A, Block 3, Lot 7- This file is in the 10-day upset bid
period.</p>
<table class="foo_ninja_table">
 <tbody>
  <tr class="ninja_table_row">
    <td class="ninja_column_0 ninja_clmn_nm_county footable-first-visible">Cleveland</td>
    <td class="ninja_column_1 ninja_clmn_nm_address">(51411) Afton Dr, Kings Mountain<br>124 Afton Dr, Kings Mountain</td>
    <td class="ninja_column_2 ninja_clmn_nm_parcel">51411<br>12005</td>
    <td class="ninja_column_3 ninja_clmn_nm_saledatetime">6/25/2026 11:00:00 AM</td>
    <td class="ninja_column_4 ninja_clmn_nm_openingbid">$11,300.00</td>
    <td class="ninja_column_5 ninja_clmn_nm_currentbid">&nbsp;</td>
    <td class="ninja_column_6 ninja_clmn_nm_closedate">7/6/2026</td>
    <td class="ninja_column_7 ninja_clmn_nm_propertytype">Mixed</td>
    <td class="ninja_column_8 ninja_clmn_nm_courtfile">25CV003091-220</td>
    <td class="ninja_column_9 ninja_clmn_nm_ourfile">24481</td>
    <td class="ninja_column_10 ninja_clmn_nm_salestatus footable-last-visible">&nbsp;</td>
  </tr>
  <tr class="ninja_table_row">
    <td class="ninja_column_0 ninja_clmn_nm_county">Cleveland</td>
    <td class="ninja_column_1 ninja_clmn_nm_address">126 Brunet Dr, Casar</td>
    <td class="ninja_column_2 ninja_clmn_nm_parcel">47004</td>
    <td class="ninja_column_3 ninja_clmn_nm_saledatetime">6/25/2026 11:00:00 AM</td>
    <td class="ninja_column_4 ninja_clmn_nm_openingbid">$6,200.00</td>
    <td class="ninja_column_5 ninja_clmn_nm_currentbid">&nbsp;</td>
    <td class="ninja_column_6 ninja_clmn_nm_closedate">7/6/2026</td>
    <td class="ninja_column_7 ninja_clmn_nm_propertytype">Residential Vacant Lot</td>
    <td class="ninja_column_8 ninja_clmn_nm_courtfile">25CV003791-220</td>
    <td class="ninja_column_9 ninja_clmn_nm_ourfile">24486</td>
    <td class="ninja_column_10 ninja_clmn_nm_salestatus">&nbsp;</td>
  </tr>
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
    <td class="ninja_column_10 ninja_clmn_nm_salestatus">&nbsp;</td>
  </tr>
 </tbody>
</table>
<hr>
<p>PROPERTIES CURRENTLY IN FORECLOSURE. The following parcels are waiting for
deadlines to be met in the foreclosure process:</p>
<p>Parcel: 34843 /&nbsp;File # 22-CVD-1122 /&nbsp;Address: 207 Southard Street /
Map L 3, Block: 8, Lot 7L. Foreclosure on hold</p>
<p>Parcel 34980 /&nbsp;File # 26CV001033-220 /&nbsp;326 W Main Street,
Lawndale, NC 28090 / Map L 3, Block 10, Lot 1</p>
<p>Parcel 3515 /&nbsp;File # 26CV000833-220 /&nbsp;305 Cedarwood Drive,
Shelby, NC 28150 / Map A105, Block 4, lot 10</p>
</body></html>
"""


def test_full_parse_row_count_and_no_dupes():
    rows = parse(SAMPLE)
    # 4 scheduled table listings (row1 -> 2 parcels) + 1 inline upset-bid
    # + 3 inline pending = 8 unique.
    assert len(rows) == 8
    keys = [(r.parcel_id, r.case_number) for r in rows]
    assert len(keys) == len(set(keys))  # dedup on (parcel, case)


def test_scheduled_table_rows_carry_date_and_bid():
    rows = _parse_sales_table(SAMPLE)
    assert len(rows) == 4  # the two-parcel row expands to two listings
    galilee = next(r for r in rows if r.parcel_id == "12811")
    assert galilee.listing_type == ListingType.TAX_SALE
    assert galilee.opening_bid == 20100.0
    assert galilee.sale_date is not None and galilee.sale_date.year == 2026
    assert galilee.sale_date.month == 6 and galilee.sale_date.day == 25
    assert galilee.case_number == "25CV003450-220"
    assert galilee.property_kind == PropertyKind.SINGLE_FAMILY
    assert galilee.street_address == "124 Galilee Church Rd, Kings Mountain"


def test_two_parcel_row_expands_to_two_listings():
    rows = _parse_sales_table(SAMPLE)
    afton = [r for r in rows if r.case_number == "25CV003091-220"]
    assert len(afton) == 2
    assert {r.parcel_id for r in afton} == {"51411", "12005"}
    # Both share the same case, sale date and opening bid...
    assert all(r.opening_bid == 11300.0 for r in afton)
    # ...but carry their own distinct address (split on <br>).
    assert {r.street_address for r in afton} == {
        "(51411) Afton Dr, Kings Mountain",
        "124 Afton Dr, Kings Mountain",
    }


def test_property_kind_mapping():
    rows = _parse_sales_table(SAMPLE)
    kinds = {r.parcel_id: r.property_kind for r in rows}
    assert kinds["47004"] == PropertyKind.LAND          # Residential Vacant Lot
    assert kinds["12811"] == PropertyKind.SINGLE_FAMILY  # Residential Home
    assert kinds["51411"] == PropertyKind.MIXED          # Mixed


def test_inline_upset_bid_and_pending_stages():
    rows = _parse_inline(SAMPLE)
    # 1 upset-bid (scheduled, before marker) + 3 pending (after marker) = 4.
    assert len(rows) == 4
    upset = next(r for r in rows if r.parcel_id == "57139")
    assert upset.listing_type == ListingType.TAX_SALE
    assert upset.raw["cleveland_tax"]["stage"] == "upset_bid"
    assert upset.street_address == "2500 Parnell Drive, Shelby"

    pending = [r for r in rows if r.listing_type == ListingType.LIS_PENDENS]
    assert len(pending) == 3
    assert all(r.auction_status == "pending" for r in pending)
    assert {r.parcel_id for r in pending} == {"34843", "34980", "3515"}


def test_nbsp_separator_does_not_drop_inline_rows():
    # The live page pads "/" with &nbsp;. Regression guard: the inline parser
    # must still find every "Parcel / File # / Address" entry.
    rows = _parse_inline(SAMPLE)
    assert {r.case_number for r in rows} == {
        "26CV000065-220", "22-CVD-1122", "26CV001033-220", "26CV000833-220",
    }


def test_br_line_split_and_money_helpers():
    cell = HTMLParser("<table><tr><td>51411<br>12005</td></tr></table>").css_first("td")
    assert _lines(cell) == ["51411", "12005"]
    assert _money("$11,300.00") == 11300.0
    assert _money("$6,200") == 6200.0
    assert _money("") is None
    assert _money("&nbsp;") is None


def test_empty_and_no_grid():
    assert _parse_sales_table("") == []
    assert _parse_sales_table("<html><body>no grid here</body></html>") == []
    assert parse("<html><body>nothing</body></html>") == []
