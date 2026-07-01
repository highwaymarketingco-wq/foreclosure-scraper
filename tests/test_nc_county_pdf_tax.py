"""Unit tests for the NC county PDF delinquent-tax parser (no network)."""
from foreclosure_scraper.scrapers.counties_nc import nc_county_pdf_delinquent_tax as m


def test_name_id_amt_layout():
    text = (
        "Column1 Column2 Column3\n"
        "ABERNATHY JOHN DAVID          90537 174.99\n"
        "120 HICKORY LLC               26326 12693.24\n"
        "ZERO OWED LLC                 11111 0\n"          # zero-owed dropped
        "some prose line with no id\n"
    )
    rows = m._parse_name_id_amt(text, (1, 7))
    ids = {r[1]: r for r in rows}
    assert set(ids) == {"90537", "26326"}
    assert ids["90537"][0] == "ABERNATHY JOHN DAVID"
    assert ids["120" if False else "26326"][2] == 12693.24


def test_parcel_amt_owner_layout():
    text = (
        "079700586730              $5,847.85\n"
        "307 BLUERIDGE DR S UT1 LND TST\n"
        "077000420045               $829.95\n"
        "7F RENOVATIONS LLC\n"
    )
    rows = m._parse_parcel_amt_owner(text)
    by = {r[1]: r for r in rows}
    assert set(by) == {"079700586730", "077000420045"}
    assert by["079700586730"][0] == "307 BLUERIDGE DR S UT1 LND TST"
    assert by["079700586730"][2] == 5847.85


def test_to_listing_parcel_flag():
    cfg_pin = {"url": "u", "id_is_parcel": True}
    cfg_acct = {"url": "u", "id_is_parcel": False}
    li_pin = m._to_listing("A B", "90537", 100.0, "Lincoln", cfg_pin)
    li_acct = m._to_listing("C D", "33566", 100.0, "Catawba", cfg_acct)
    assert li_pin.parcel_id == "90537"
    assert li_acct.parcel_id is None  # account #, not a GIS PIN
    assert li_acct.raw["nc_county_pdf_delinquent_tax"]["county_id"] == "33566"
    assert li_pin.listing_type.value == "tax_lien"


def test_money_and_owner():
    assert m._money("1,234.50") == 1234.50
    assert m._money("0") is None
    assert m._clean_owner("  SMITH,  JOHN ;") == "SMITH, JOHN"
    assert m._clean_owner("") is None
