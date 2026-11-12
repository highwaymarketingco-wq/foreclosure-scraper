"""Buncombe adapter parsers and the wall detector, on hand-written fixtures (made-up names and
numbers, shaped like the county's pages: no fetched page content)."""
import pytest

from foreclosure_scraper.quiet_title.adapters import adapter_class
from foreclosure_scraper.quiet_title.adapters.buncombe import (BuncombeAdapter, bill_years, hidden_fields, money,
                                                               parcel_from_attrs, parse_gis, parse_rod_detail,
                                                               parse_rod_grid, parse_tax_bill, parse_tax_parcel,
                                                               street_key, ymd)
from foreclosure_scraper.quiet_title.fetch import detect_wall

GIS_JSON = {
    "fields": [{"name": n} for n in ("pinnum", "owner", "CareOf", "Address", "CityName", "State", "Zipcode",
                                     "HouseNumber", "streetname", "StreetType", "DeedBook", "DeedPage", "DeedDate",
                                     "Instrument", "PlatBook", "PlatPage", "Acreage", "Class", "Improved",
                                     "TaxValue", "LandValue", "BuildingValue", "UpdateDate")],
    "features": [{"attributes": {
        "pinnum": "000011112222333", "owner": "ANNA MARIE TESTER (HEIRS)", "CareOf": "JOHN SAMPLE",
        "Address": "12 EXAMPLE RIDGE RD", "CityName": "NOWHERE", "State": "NC", "Zipcode": "28000",
        "HouseNumber": "99999", "streetname": "EXAMPLE RIDGE", "StreetType": "RD", "DeedBook": "0123",
        "DeedPage": "0045", "DeedDate": "19790102", "Instrument": "DEE", "PlatBook": "0000", "PlatPage": "0000",
        "Acreage": 1.5, "Class": "311", "Improved": "N", "TaxValue": "10000", "LandValue": "10000",
        "BuildingValue": "0", "UpdateDate": "20261001"}}],
}

TAX_PARCEL = """<html><body><h1>Parcel Details</h1><div>Active</div>
<h2>Billing History</h2>
<div class="card history-card"><h3><a href="/Bill/Details/0000000001-2026-2026-0000-00">0000000001-2026-2026-0000-00</a></h3>
 <small>Owner</small><div>ANNA MARIE TESTER (HEIRS)</div><small>Value</small><div>$10,000</div>
 <small>PIN</small><div>000011112222333</div><small>Amount Due</small><div>$80.10</div>
 <small>Description</small><div>EXAMPLE RIDGE RD LAND ONLY</div></div>
<div class="card history-card"><h3><a href="/Bill/Details/0000000001-2025-2025-0000-00">0000000001-2025-2025-0000-00</a></h3>
 <small>Owner</small><div>ANNA MARIE TESTER (HEIRS)</div><small>Amount Due</small><div>See Legal</div></div>
<div class="card history-card"><h3><a href="/Bill/Details/0000000001-2021-2023-0001-00">0000000001-2021-2023-0001-00</a></h3>
 <small>Amount Due</small><div>$0.00</div></div>
</body></html>"""

TAX_BILL = """<html><body><h2>Bill Details</h2><div>Owner Name(s):</div><div>ANNA MARIE TESTER (HEIRS)</div>
<div>Amount due:</div><div>$0.00</div><div>Paid!</div>
<table><tr><th>Type</th><th>Date</th><th>Receipt #</th><th>Tax</th><th>Late Fee</th><th>Interest</th><th>Cost/Fee</th><th>Total</th></tr>
<tr><td>BILL</td><td>7/30/2022</td><td></td><td>$50.00</td><td>$0.00</td><td>$1.00</td><td>$0.00</td><td>$51.00</td></tr>
<tr><td>PAYMENT</td><td>1/20/2023</td><td>99</td><td>($50.00)</td><td>$0.00</td><td>($1.00)</td><td>$0.00</td><td>($51.00)</td></tr>
</table>
<div>General</div><div>Status</div><div>Active</div><div>Levy Year</div><div>2022</div></body></html>"""

ROD_GRID = """<html><body><span>1 - 2 of 2</span><span>DEATHS Valid From 1/1/1913 Thru 10/1/2026</span>
<table id="ctl00_x_cpgvInstruments">
<tr><td>1</td><td>**/**/1990<br/><span>Date Filed<br/>**/**/1990</span></td><td>DTH</td><td></td>
 <td><div><table><tr><td><b>TESTER, ANNA JOY</b></td></tr><tr><td>OTHERLY, ANNA JOY</td></tr></table></div></td>
 <td><div><table><tr><td>TESTER, JOHN</td></tr><tr><td>[-]</td></tr><tr><td>TESTER, JOHN</td></tr><tr><td>[+]</td></tr></table></div></td>
 <td></td><td></td>
 <td><a href='javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions("ctl00$g$ctl02$lbBP", "", true))'>70 / 1</a></td>
 <td></td><td>1</td><td></td><td></td></tr>
<tr><td>2</td><td>03/04/1979</td><td>DEE</td><td>PRE 95 DEEDS</td>
 <td><div><table><tr><td>SAMPLE, ROY W</td></tr></table></div></td>
 <td><div><table><tr><td><b>TESTER, ANNA MARIE</b></td></tr></table></div></td>
 <td>[W/DEED ] 1.5 ACRES EXAMPLE TWP</td><td></td>
 <td><a href='javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions("ctl00$g$ctl03$lbBP", "", true))'>123 / 45</a></td>
 <td></td><td>3</td><td></td><td></td></tr>
</table><input type="hidden" name="__VIEWSTATE" value="abc"/></body></html>"""

ROD_DETAIL = """<html><body>
<table id="ctl00_cphMain_gvDetails1"><tr><th>Book/Page</th><th>Index Type</th><th>Kind</th><th>Description</th><th>Date Filed</th><th>Images</th></tr>
<tr><td>123 / 45</td><td>PRE 95 DEEDS</td><td>PRE 95 DEEDS</td><td>[W/DEED ] 1.5 ACRES EXAMPLE TWP</td><td>03/04/1979 12:00:00 AM</td><td><a>3 pages</a></td></tr></table>
<table id="ctl00_cphMain_gvParties1"><tr><th>GRANTORS</th></tr><tr><td>SAMPLE, ROY W</td></tr></table>
<table id="ctl00_cphMain_gvParties2"><tr><th>GRANTEES</th></tr><tr><td>TESTER, ANNA MARIE</td></tr></table>
</body></html>"""


def test_money_and_dates():
    assert money("$1,234.56") == 1234.56 and money("($85.34)") == -85.34
    assert money("See Legal") is None
    assert ymd("19790102") == "1979-01-02" and ymd("00000000") is None
    assert bill_years("0000000001-2025-2025-0000-00") == (2025, 2025, True)
    assert bill_years("0000000001-2021-2023-0001-00") == (2021, 2023, False)


def test_street_key():
    assert street_key("12 EXAMPLE RIDGE RD") == ("12", "EXAMPLE RIDGE")
    assert street_key("40 N MAIN ST") == ("40", "MAIN")
    assert street_key("PO BOX 634") == (None, None)


def test_gis_parcel_without_legal_description_field():
    feats, fields = parse_gis(GIS_JSON)
    p = parcel_from_attrs("000011112222333", feats[0], fields)
    assert p.legal_description is None and p.legal_field is None
    assert p.situs == "EXAMPLE RIDGE RD" and "99999" in p.situs_note
    assert (p.mailing_house_number, p.mailing_street) == ("12", "EXAMPLE RIDGE")
    assert (p.deed_book, p.deed_page, p.deed_date) == ("123", "45", "1979-01-02")
    assert p.plat_book is None and p.tax_value == 10000.0 and p.layer_updated == "2026-10-01"


def test_gis_legal_field_is_used_when_a_layer_has_one():
    j = {"fields": [{"name": "pinnum"}, {"name": "LegalDesc"}],
         "features": [{"attributes": {"pinnum": "1", "LegalDesc": "LOT 7 EXAMPLE ACRES"}}]}
    feats, fields = parse_gis(j)
    p = parcel_from_attrs("1", feats[0], fields)
    assert p.legal_field == "LegalDesc" and p.legal_description == "LOT 7 EXAMPLE ACRES"


def test_gis_error_body_is_not_an_empty_answer():
    with pytest.raises(ValueError):
        parse_gis({"error": {"code": 500, "message": "Error performing query operation"}})


def test_tax_parcel_page_bills_and_see_legal():
    status, bills = parse_tax_parcel(TAX_PARCEL)
    assert status == "Active" and len(bills) == 3
    b26, b25, disc = bills
    assert (b26.levy_year, b26.amount_due, b26.regular) == (2026, 80.10, True)
    assert b25.amount_due is None and b25.amount_due_text == "See Legal"
    assert disc.regular is False


def test_tax_bill_transactions():
    d = parse_tax_bill(TAX_BILL)
    assert d["amount_due_text"] == "$0.00" and d["status_text"] == "Paid!" and d["levy_year"] == "2022"
    assert [t.type for t in d["transactions"]] == ["BILL", "PAYMENT"]
    assert d["transactions"][1].total == -51.00 and d["transactions"][0].interest == 1.0


def test_rod_grid_parties_bold_toggles_and_masks():
    g = parse_rod_grid(ROD_GRID)
    assert g["total"] == 2 and g["coverage"] == [("DEATHS", "1/1/1913", "10/1/2026")]
    death, deed = g["rows"]
    assert death.year == 1990 and death.date_iso is None
    assert death.grantors == ["TESTER, ANNA JOY", "OTHERLY, ANNA JOY"] and death.matched == ["TESTER, ANNA JOY"]
    assert death.grantees == ["TESTER, JOHN"]           # toggles and the repeated list are dropped
    assert death.matched_side == "grantor"
    assert deed.date_iso == "1979-03-04" and deed.book_page == "123 / 45" and deed.pages == 3
    assert deed.link_target == "ctl00$g$ctl03$lbBP" and deed.matched_side == "grantee"
    assert hidden_fields(ROD_GRID) == {"__VIEWSTATE": "abc"}


def test_rod_detail():
    d = parse_rod_detail(ROD_DETAIL)
    assert d["grantors"] == ["SAMPLE, ROY W"] and d["grantees"] == ["TESTER, ANNA MARIE"]
    assert d["images"] == "3 pages" and d["kind"] == "PRE 95 DEEDS"


def test_wall_detector():
    assert detect_wall(403, "https://x", "") == "HTTP 403"
    assert detect_wall(402, "https://x", "") == "HTTP 402"
    assert detect_wall(200, "https://x", "<title>Just a moment...</title>") == "challenge page"
    assert detect_wall(200, "https://x", '<div class="g-recaptcha" data-sitekey="k"></div>') == "CAPTCHA"
    # a script include alone is not a challenge (the register loads invisible reCAPTCHA v3 everywhere)
    assert detect_wall(200, "https://x", "<script src='https://www.google.com/recaptcha/api.js'></script>") is None
    assert detect_wall(200, "https://x/account/login", '<input type="password" name="p">') == "login page"
    assert detect_wall(200, "https://x/search", "<table>results</table>") is None


def test_adapter_registry():
    assert adapter_class("Buncombe", "NC") is BuncombeAdapter
    assert adapter_class("buncombe county") is BuncombeAdapter
    with pytest.raises(SystemExit):
        adapter_class("Nowhere", "NC")
