"""NC ITSPublic delinquent-tax portals (Onslow, Graham), added 2026-09-21.

Rows below are hand-built from the shapes read live: Onslow's description carries a zero
padded bill number before the parcel, Graham's does not, and personal property rows say
"Personal Property" with no acreage. Names, parcels and amounts are invented.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

import foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax as m
from foreclosure_scraper.models import ListingType

ONSLOW = m.PORTALS["Onslow"]
GRAHAM = m.PORTALS["Graham"]


def _row(year, bill, owner, desc, orig, bal, acct="496055000", action="<button>+</button>"):
    return {"id": f"{year}/{bill}",
            "cell": [str(year), str(bill), acct, owner, desc, orig, bal, action]}


_FORECLOSURE_CELL = (
    "<div style='white-space: normal; display: inline-block; overflow: auto; "
    "word-wrap: break-word'>This property is currently in Tax Foreclosure. "
    "Contact the tax office for further information</div>"
)
_RETURNED_ITEM_CELL = (
    "<div style='white-space: normal'>There is a returned item on this account.  "
    "Contact the tax office for further information</div>"
)


ON_ROW = _row(2025, 72, "ROE JANE &amp; JOHN",
              "000072<br/>801-154<br />1008 1ST ST SURF CITY NC 28445-8620<br />0.150 AC",
              "2,205.73", "2,387.48")
ON_LOT = _row(2025, 167, "DOE RICHARD",
              "000167<br/>350-194<br />REGALWOOD DR JACKSONVILLE NC 28546<br />8.000 AC",
              "5.24", "5.66")
ON_PARK = _row(2025, 343, "POE SAM",
               "000343<br/>1116-53<br />2478 PINEY GREEN RD MIDWAY PARK NC 28544-1110<br />4.880 AC",
               "436.15", "272.40")
GR_4 = _row(2025, 7, "ROE MARY", "662300010040<br/>2214290<br />HWY 28 PANTHER CK<br />0.280 AC",
            "250.75", "275.76", acct="155899218")
GR_3 = _row(2025, 22, "DOE ANN", "5660111F00071<br /><br />250 ATOAH ST<br />1.000 LT",
            "336.71", "12.76", acct="155891262")
GR_PP = _row(2025, 155, "ADAMS ROBERT", "Personal Property<br /> <br /> ", "10.00", "11.00")


# --------------------------------------------------------------------------- years

@pytest.mark.parametrize("today,back,want", [
    (date(2026, 9, 21), 3, [2025, 2024, 2023]),       # a 2026 bill is current, not delinquent
    (date(2026, 9, 21), 1, [2025]),
    (date(2027, 1, 3), 2, [2025, 2024]),              # before Jan 6 the newest is still 2 back
    (date(2027, 1, 6), 1, [2026]),
])
def test_delinquent_years(today, back, want):
    assert m.delinquent_years(today, back) == want


# --------------------------------------------------------------------------- row parsing

def test_onslow_row_drops_the_bill_prefix_and_splits_the_situs():
    b = m.parse_row(ON_ROW, ONSLOW.cities)
    assert b["parcel"] == "801-154" and b["year"] == 2025 and b["bill"] == "72"
    assert b["street"] == "1008 1ST ST" and b["city"] == "Surf City" and b["zip"] == "28445"
    assert b["acres"] == 0.15 and b["unit"] == "AC"
    assert b["balance"] == 2387.48 and b["original_levy"] == 2205.73
    assert b["owner"] == "ROE JANE & JOHN"                    # entity decoded


def test_a_two_word_city_is_split_from_the_street():
    b = m.parse_row(ON_PARK, ONSLOW.cities)
    assert b["street"] == "2478 PINEY GREEN RD" and b["city"] == "Midway Park"


def test_a_situs_with_no_house_number_is_not_a_street_address():
    b = m.parse_row(ON_LOT, ONSLOW.cities)
    assert b["street"] is None and b["city"] == "Jacksonville" and b["zip"] == "28546"
    assert b["situs_text"].startswith("REGALWOOD DR")


def test_graham_layouts_with_and_without_the_alternate_id():
    a = m.parse_row(GR_4, GRAHAM.cities)
    assert a["parcel"] == "662300010040" and a["alt"] == "2214290"
    assert a["situs_text"] == "HWY 28 PANTHER CK" and a["street"] is None
    b = m.parse_row(GR_3, GRAHAM.cities)
    assert b["parcel"] == "5660111F00071" and b["alt"] is None
    assert b["street"] == "250 ATOAH ST" and b["unit"] == "LT" and b["acres"] is None
    assert b["quantity"] == 1.0


def test_personal_property_is_dropped():
    assert m.parse_row(GR_PP, GRAHAM.cities) is None
    assert m.parse_row({"id": "x", "cell": ["2025"]}, ()) is None


# --------------------------------------------------------------------------- lead

def test_one_lead_per_parcel_with_the_years_summed():
    bills = [m.parse_row(_row(y, 900 + y, "ROE JANE", "00%d<br/>801-154<br />1008 1ST ST SURF CITY NC 28445<br />0.150 AC" % (900 + y),
                              "100.00", bal), ONSLOW.cities)
             for y, bal in ((2025, "120.50"), (2024, "300.25"), (2023, "80.00"))]
    other = m.parse_row(ON_LOT, ONSLOW.cities)
    leads = m.aggregate("Onslow", ONSLOW, bills + [other])
    assert len(leads) == 2
    li = next(x for x in leads if x.parcel_id == "801-154")
    assert li.listing_type == ListingType.TAX_LIEN and li.sale_date is None
    assert li.state == "NC" and li.county == "Onslow"
    assert li.source == "counties_nc.nc_its_public_tax"
    assert li.street_address == "1008 1ST ST" and li.city == "Surf City" and li.zip_code == "28445"
    assert li.acreage == 0.15
    blk = li.raw["nc_its_public_tax"]
    assert blk["years"] == [2023, 2024, 2025] and blk["is_two_year_plus"] is True
    assert blk["total_due"] == 500.75 and blk["oldest_year"] == 2023
    assert li.raw["tax_owed"] == {"balance": 500.75, "kind": "delinquent_tax",
                                  "source": "counties_nc.nc_its_public_tax", "year": 2025,
                                  "basis": "own_record"}
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True and li.raw["two_year_delinquent"]["years"] == 3
    assert "2023-2025 (3 bills)" in li.description and "$500.75" in li.description
    assert li.foreclosure_process == "tax"


def test_bill_status_cell_parsed_for_foreclosure_and_returned_item():
    """2026-10-03 (HERMES extraction-completeness audit, batch 5): cell[7]
    is the UI's own 'Add to Cart' button on a normal bill, but a status
    MESSAGE instead on some bills -- live-sampled 155/500 (31%) of current
    Onslow bills carry the foreclosure message, and parse_row never looked
    at this cell at all (only required len(cell) >= 7)."""
    fc = m.parse_row(_row(2025, 72, "ROE JANE",
                          "000072<br/>801-154<br />1008 1ST ST SURF CITY NC 28445<br />0.150 AC",
                          "2,205.73", "2,404.06", action=_FORECLOSURE_CELL), ONSLOW.cities)
    assert fc["status"] == "in_tax_foreclosure"

    ri = m.parse_row(_row(2025, 167, "HUMPHREY J R",
                          "000167<br/>350-194<br />REGALWOOD DR JACKSONVILLE NC 28546<br />8.000 AC",
                          "5.24", "5.70", action=_RETURNED_ITEM_CELL), ONSLOW.cities)
    assert ri["status"] == "returned_payment"

    normal = m.parse_row(ON_ROW, ONSLOW.cities)
    assert normal["status"] is None


def test_aggregate_surfaces_worst_bill_status_as_tax_sale_status():
    """A parcel whose NEWEST bill is plain but an OLDER bill already shows
    the foreclosure message must still surface as in_foreclosure -- the
    worst status across all bills, not just the head (newest) one."""
    newest = m.parse_row(_row(2025, 801, "ROE JANE",
                              "000801<br/>801-154<br />1008 1ST ST SURF CITY NC 28445<br />0.150 AC",
                              "100.00", "120.50"), ONSLOW.cities)
    oldest = m.parse_row(_row(2023, 802, "ROE JANE",
                              "000802<br/>801-154<br />1008 1ST ST SURF CITY NC 28445<br />0.150 AC",
                              "100.00", "80.00", action=_FORECLOSURE_CELL), ONSLOW.cities)
    li = m.aggregate("Onslow", ONSLOW, [newest, oldest])[0]
    assert li.raw["nc_its_public_tax"]["status"] == "in_tax_foreclosure"
    assert li.raw["tax_sale_status"] == "in_foreclosure"
    assert "ACTIVE TAX FORECLOSURE" in li.description


def test_aggregate_no_status_key_when_all_bills_clean():
    b = m.parse_row(ON_ROW, ONSLOW.cities)
    li = m.aggregate("Onslow", ONSLOW, [b])[0]
    assert li.raw["nc_its_public_tax"]["status"] is None
    assert "tax_sale_status" not in li.raw
    assert "ACTIVE TAX FORECLOSURE" not in li.description


def test_a_bill_with_no_balance_has_no_tax_owed():
    b = m.parse_row(_row(2025, 5, "ROE", "000005<br/>1-1<br />1 MAIN ST X NC 28000<br />1.000 AC", "0.00", "0.00"), ())
    li = m.aggregate("Onslow", ONSLOW, [b])[0]
    assert "tax_owed" not in li.raw


# --------------------------------------------------------------------------- the crawl

def _transport(pages_by_year, seen):
    def handler(req: httpx.Request):
        path = req.url.path
        seen.append((req.method, path))
        if req.method == "GET":
            return httpx.Response(200, text="<html>search</html>",
                                  headers={"set-cookie": "ASP.NET_SessionId=abc; path=/"})
        body = json.loads(req.content or b"{}")
        if path.endswith("GetSearchTablePartial"):
            handler.year = body["TaxYear"]
            assert body["UnpaidBillsOnly"] is True
            return httpx.Response(200, text="<div>fragment</div>")
        assert body["Table"] == "PayTaxBills"
        pages = pages_by_year[handler.year]
        return httpx.Response(200, json={"total": len(pages), "numRecords": 999,
                                         "rows": pages[body["Page"] - 1]})
    return httpx.MockTransport(handler)


@pytest.fixture
def _fast(monkeypatch):
    monkeypatch.setattr(m, "PACE_S", 0.0)


def test_fetch_year_pages_the_session_and_drops_personal_property(_fast):
    seen: list = []
    pages = {"2025": [[ON_ROW, GR_PP], [ON_PARK]]}

    async def go():
        async with httpx.AsyncClient(transport=_transport(pages, seen)) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    bills, stats = asyncio.run(go())
    assert [b["parcel"] for b in bills] == ["801-154", "1116-53"]
    assert stats["pages"] == 2 and stats["skipped_non_real"] == 1 and stats["rows"] == 3
    assert [p for _, p in seen] == [
        "/ITSPublicON/TaxBillSearch/GetSearchTablePartial",
        "/ITSPublicON/TaxBillSearch/GetSearchTableData",
        "/ITSPublicON/TaxBillSearch/GetSearchTableData"]


def test_fetch_year_stops_early_on_a_row_limit(_fast):
    seen: list = []
    pages = {"2025": [[ON_ROW], [ON_PARK], [ON_LOT]]}

    async def go():
        async with httpx.AsyncClient(transport=_transport(pages, seen)) as c:
            return await m.fetch_year(c, ONSLOW, 2025, max_rows=1)

    bills, stats = asyncio.run(go())
    assert len(bills) == 1 and stats["pages"] == 1


def test_a_non_json_page_is_an_error_not_an_empty_roll(_fast):
    def handler(req):
        if req.url.path.endswith("GetSearchTablePartial"):
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="<html>Session expired</html>")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(RuntimeError, match="not JSON"):
        asyncio.run(go())


def test_the_scraper_reads_only_the_newest_year_on_a_sample_run(monkeypatch, _fast):
    seen: list = []
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow")
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = _transport({"2025": [[ON_ROW]], "2024": [[ON_LOT]]}, seen)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 5
    out = asyncio.run(s.fetch())
    assert [li.parcel_id for li in out] == ["801-154"]
    assert sum(1 for _, p in seen if p.endswith("Partial")) == 1     # one year, not three
    assert len(s.partial) == 1


def test_a_failed_county_does_not_kill_the_others(monkeypatch, _fast):
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow,Graham")
    real = httpx.AsyncClient

    def handler(req: httpx.Request):
        if "bttaxpayerportal" in req.url.host:            # Graham answers normally
            if req.method == "GET":
                return httpx.Response(200, text="x")
            if req.url.path.endswith("Partial"):
                return httpx.Response(200, text="x")
            return httpx.Response(200, json={"total": 1, "numRecords": 1, "rows": [GR_3]})
        return httpx.Response(500)                          # Onslow is down

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 5
    out = asyncio.run(s.fetch())
    assert [li.county for li in out] == ["Graham"]


def test_portal_config_is_pinned():
    assert m.PORTALS["Onslow"].base == "https://tax.onslowcountync.gov/ITSPublicON"
    assert m.PORTALS["Graham"].base == "https://www.bttaxpayerportal.com/ITSPublicGR2.0"
    assert m.PAGE_ROWS == 100 and m.PACE_S >= 1.0


def test_a_sample_limit_is_a_hard_cap(monkeypatch, _fast):
    """Graham's first page holds personal property, so the page loop can overshoot the limit."""
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow")
    seen: list = []
    real = httpx.AsyncClient
    rows = [_row(2025, i, f"OWNER {i}",
                 f"{i:06d}<br/>{i}-1<br />{i} MAIN ST JACKSONVILLE NC 28540<br />1.000 AC", "10", "12")
            for i in range(1, 9)]

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = _transport({"2025": [rows[:4], rows[4:]]}, seen)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 6
    assert len(asyncio.run(s.fetch())) == 6


# ----------------------------------------------------------------------------------------------
# the newer build (top-80 tax family, 2026-10-09): form-encoded full model, header-driven columns
# ----------------------------------------------------------------------------------------------

NEWER = ("Alleghany", "Anson", "Caswell", "Duplin", "Granville", "Harnett", "Jones", "Person",
         "Scotland", "Yadkin")
COLS_ADDR = ["TaxYear", "BillNumber", "AccountNumber", "AccountName1", "OriginalBillAmount", "TotalDue",
             "DiscoveryYear", "Description", "Address"]
COLS_DESC = ["TaxYear", "BillNumber", "AccountNumber", "AccountName1", "Description",
             "OriginalBillAmount", "TotalDue"]


def test_the_newer_build_portals_are_configured_and_the_unreadable_ones_have_a_reason():
    for c in NEWER:
        assert m.PORTALS[c].full_model and m.PORTALS[c].base.startswith("https://")
    assert not m.PORTALS["Onslow"].full_model and not m.PORTALS["Graham"].full_model
    assert set(m.UNREADABLE_PORTALS) == {"Clay", "Swain", "Surry", "Warren", "Gates"}
    assert not (set(m.UNREADABLE_PORTALS) & set(m.PORTALS))


def test_form_fields_and_the_posted_form():
    page = ('<input class="form-control search-value" id="OwnerLastName" /> '
            '<select title="Tax Year" name="TaxYear" class="form-control search-value" id="TaxYear">'
            '<input type="checkbox" class="x search-value" checked id="UnpaidBillsOnly" />'
            '<input class="other" id="NotAField" />')
    assert m.form_fields(page) == ["OwnerLastName", "TaxYear", "UnpaidBillsOnly"]
    form = m.search_form(["OwnerLastName", "ParcelSearch", "TaxYear", "UnpaidBillsOnly"], 2024, 100)
    assert form["TaxYear"] == "2024" and form["UnpaidBillsOnly"] == "true" and form["PageSize"] == "100"
    assert form["ParcelSearch"] == "false" and form["OwnerLastName"] == ""


def test_grid_columns_come_from_the_header_ids():
    frag = '<th id="TaxYear">Year</th><th class="x" id="BillNumber">Bill</th><th id="Address">A</th>'
    assert m.grid_columns(frag) == ["TaxYear", "BillNumber", "Address"]


def _cols_row(cols, **cells):
    return {"cell": [cells.get(c, "") for c in cols] + ([cells["_status"]] if "_status" in cells else [])}


def test_address_column_layout_takes_the_situs_from_the_address_cell():
    r = _cols_row(COLS_ADDR, TaxYear="2025", BillNumber="31", AccountNumber="9001", AccountName1="DOE JANE",
                  OriginalBillAmount="100.00", TotalDue="123.45",
                  Description="3033811534<br/>PE0001", Address="147 EXAMPLE RD")
    b = m.parse_row_cols(r, COLS_ADDR)
    assert (b["parcel"], b["alt"], b["street"], b["balance"], b["year"]) == (
        "3033811534", "PE0001", "147 EXAMPLE RD", 123.45, 2025)
    assert b["acres"] is None


def test_scotland_style_parcel_has_its_inner_space_removed():
    r = _cols_row(COLS_ADDR, TaxYear="2025", BillNumber="15", AccountNumber="1", AccountName1="ROE LLC",
                  TotalDue="29.83", Description="010075 02001<br/>0016718", Address="N EXAMPLE RD")
    assert m.parse_row_cols(r, COLS_ADDR)["parcel"] == "01007502001"


def test_description_layout_with_parcel_situs_and_acres():
    r = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="2528813", AccountNumber="299",
                  AccountName1="ROE FARMS LLC", OriginalBillAmount="1,434.77", TotalDue="535.06",
                  Description="10- 557-  -<br/><br />292 SAMPLE RD<br />15.750 AC")
    b = m.parse_row_cols(r, COLS_DESC)
    assert b["parcel"] == "10-557--" and b["street"] == "292 SAMPLE RD" and b["acres"] == 15.75
    assert b["balance"] == 535.06


def test_a_bill_with_only_a_situs_has_no_parcel_but_keeps_the_street_and_city():
    r = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="100230", AccountNumber="1058201",
                  AccountName1="DOE JOHN HEIRS", TotalDue="372.99",
                  Description="<br />995 SAMPLE CHURCH RD EXAMPLETON 27379<br />1.270 AC")
    b = m.parse_row_cols(r, COLS_DESC)
    assert b["parcel"] is None and b["street"] == "995 SAMPLE CHURCH RD"
    assert (b["city"], b["zip"]) == ("Exampleton", "27379")


def test_a_parcel_only_description_is_real_property_and_personal_property_is_dropped():
    r = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="1", AccountNumber="7", AccountName1="ROE LLC",
                  TotalDue="10", Description="742600527368<br/><br /><br />")
    assert m.parse_row_cols(r, COLS_DESC)["parcel"] == "742600527368"
    pp = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="2", AccountNumber="7", AccountName1="ROE LLC",
                   TotalDue="10", Description="Personal Property<br />155 MAPLE ST EXAMPLETON NC 27573<br />")
    assert m.parse_row_cols(pp, COLS_DESC) is None
    assert m.parse_row_cols(_cols_row(COLS_DESC, TaxYear="2025", BillNumber="3", AccountNumber="7",
                                      Description="Escrow"), COLS_DESC) is None


def test_the_status_cell_past_the_named_columns_is_read():
    r = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="9", AccountNumber="7", AccountName1="ROE LLC",
                  TotalDue="10", Description="<br />1 SAMPLE ST<br />1.000 AC", _status=_FORECLOSURE_CELL)
    assert m.parse_row_cols(r, COLS_DESC)["status"] == "in_tax_foreclosure"


def test_no_parcel_bills_group_by_account_and_situs_and_the_block_records_the_read_years():
    def bill(year, bal):
        return {"year": year, "bill": str(year), "account": "55", "owner": "DOE JOHN HEIRS",
                "original_levy": bal, "balance": bal, "status": None, "parcel": None, "alt": None,
                "situs_text": "995 SAMPLE CHURCH RD EXAMPLETON 27379", "acres": 1.27, "unit": "AC",
                "street": "995 SAMPLE CHURCH RD", "city": "Exampleton", "zip": "27379"}
    li = m.aggregate("Caswell", m.PORTALS["Caswell"], [bill(2025, 10.0), bill(2024, 20.0), bill(2023, 5.0)],
                     years_read=[2025, 2024, 2023], truncated=False)
    assert len(li) == 1 and li[0].parcel_id is None and li[0].street_address == "995 SAMPLE CHURCH RD"
    blk = li[0].raw["nc_its_public_tax"]
    assert blk["years_delinquent"] == 3 and blk["years_read"] == [2025, 2024, 2023]
    assert blk["read_truncated"] is False and "None" not in li[0].description
    assert li[0].raw["two_year_delinquent"]["is_two_year_plus"] is True


def _newer_transport(seen, rows, cols_html):
    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("content-type", "")))
        if req.method == "GET":
            return httpx.Response(200, text='<input class="search-value" id="TaxYear" /> '
                                            '<input class="search-value" id="UnpaidBillsOnly" />')
        body = dict(x.split("=", 1) for x in req.content.decode().split("&") if "=" in x)
        if req.url.path.endswith("GetSearchTablePartial/"):
            assert body["TaxYear"] == "2025" and body["UnpaidBillsOnly"] == "true"
            return httpx.Response(200, text=cols_html + '<script>PopulateTable("PayTaxBills", x)</script>')
        assert body["Table"] == "PayTaxBills" and "PostData" in body
        return httpx.Response(200, json={"total": 1, "numRecords": len(rows), "rows": rows})
    return httpx.MockTransport(handler)


def test_fetch_year_posts_the_full_form_and_parses_by_header(_fast):
    seen: list = []
    cols_html = "".join(f'<th id="{c}">x</th>' for c in COLS_DESC)
    rows = [_cols_row(COLS_DESC, TaxYear="2025", BillNumber="5", AccountNumber="1", AccountName1="ROE LLC",
                      TotalDue="40.00", Description="<br />9 SAMPLE ST<br />2.000 AC"),
            _cols_row(COLS_DESC, TaxYear="2025", BillNumber="6", AccountNumber="1", AccountName1="ROE LLC",
                      TotalDue="4.00", Description="Personal Property<br /><br />")]
    m._FORM_FIELDS[m.PORTALS["Person"].base] = ["TaxYear", "UnpaidBillsOnly"]

    async def go():
        async with httpx.AsyncClient(transport=_newer_transport(seen, rows, cols_html)) as c:
            return await m.fetch_year(c, m.PORTALS["Person"], 2025)

    bills, stats = asyncio.run(go())
    assert [b["street"] for b in bills] == ["9 SAMPLE ST"] and stats["skipped_non_real"] == 1
    assert stats["truncated"] is False
    assert all("json" not in ct for meth, _p, ct in seen if meth == "POST")
    assert [p for _, p, _ in seen] == ["/ITSPublicPR/TaxBillSearch/GetSearchTablePartial/",
                                       "/ITSPublicPR/TaxBillSearch/GetSearchTableData"]


def test_a_newer_build_with_no_result_grid_is_an_error_not_an_empty_roll(_fast):
    m._FORM_FIELDS[m.PORTALS["Person"].base] = ["TaxYear"]

    def handler(req):
        return httpx.Response(200, text="<div>nothing</div>")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, m.PORTALS["Person"], 2025)

    with pytest.raises(RuntimeError, match="no result grid"):
        asyncio.run(go())


def test_the_county_deadline_truncates_and_says_so(_fast):
    cols_html = "".join(f'<th id="{c}">x</th>' for c in COLS_DESC)
    row = _cols_row(COLS_DESC, TaxYear="2025", BillNumber="5", AccountNumber="1", AccountName1="ROE LLC",
                    TotalDue="40.00", Description="<br />9 SAMPLE ST<br />2.000 AC")
    m._FORM_FIELDS[m.PORTALS["Person"].base] = ["TaxYear", "UnpaidBillsOnly"]

    def handler(req):
        if req.url.path.endswith("Partial/"):
            return httpx.Response(200, text=cols_html)
        return httpx.Response(200, json={"total": 3, "numRecords": 3, "rows": [row]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, m.PORTALS["Person"], 2025, deadline=0.0)

    bills, stats = asyncio.run(go())
    assert stats["truncated"] is True and stats["pages"] == 1 and len(bills) == 1
