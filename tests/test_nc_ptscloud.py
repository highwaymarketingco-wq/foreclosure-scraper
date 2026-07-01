"""Unit tests for the NC PTS Cloud delinquent-tax scraper (parse logic, no network)."""
from foreclosure_scraper.scrapers.counties_nc import nc_ptscloud_delinquent_tax as m

_CSV = (
    "BILL_TYPE,PARCEL_NUM,TAX_YEAR,OWNER_NAME,MAIL_ADDR1,MAIL_CITY,MAIL_STATE,MAIL_ZIP,"
    "ABSTRACT_ASSESS_VALUE,TOTAL_DUE_AMOUNT,BILL_NUMBER\n"
    # same parcel, two years -> summed to one lead
    "REI,1234,2023,\"SMITH, JOHN\",10 OAK ST,MARSHALL,NC,28753,120000,500.00,B1\n"
    "REI,1234,2024,\"SMITH, JOHN\",10 OAK ST,MARSHALL,NC,28753,120000,300.50,B2\n"
    # owner-name noise must be stripped
    "REI,5678,2024,\"REDMON, J H ADDRESS IS WRONG-DO NOT SEND;\",,,,,45000,923.00,B3\n"
    # non-real-estate rows dropped
    "IND,9999,2024,\"DOE, JANE\",,,,,0,88.00,B4\n"
    "BUS,8888,2024,\"ACME LLC\",,,,,0,999.00,B5\n"
    # placeholder + zero-owed dropped
    "REI,UNK1,2024,\"GHOST, X\",,,,,0,10.00,B6\n"
    "REI,4321,2024,\"POE, EDGAR\",,,,,50000,0,B7\n"
)


def test_parse_dedupes_sums_and_filters():
    leads = m._parse_csv(_CSV, "Madison", "NC", "Madison")
    by = {l.parcel_id: l for l in leads}
    # 1234 (summed) + 5678 kept; IND/BUS/UNK/zero-owed dropped
    assert set(by) == {"1234", "5678"}
    assert by["1234"].raw["nc_ptscloud_delinquent_tax"]["principal_tax_due"] == 800.50
    assert by["1234"].listing_type.value == "tax_lien"
    assert by["1234"].raw["nc_ptscloud_delinquent_tax"]["assessed_value"] == 120000.0
    assert by["1234"].raw["nc_ptscloud_delinquent_tax"]["mailing"]["city"] == "MARSHALL"


def test_owner_noise_stripped():
    leads = m._parse_csv(_CSV, "Madison", "NC", "Madison")
    by = {l.parcel_id: l for l in leads}
    assert by["5678"].owner_name == "REDMON, J H"  # note text removed


def test_clean_owner_direct():
    assert m._clean_owner("JONES, MARY; DO NOT SEND") == "JONES, MARY"
    assert m._clean_owner("BROWN, SAM DECEASED") == "BROWN, SAM"
    assert m._clean_owner("  LEE, ANN  ") == "LEE, ANN"
    assert m._clean_owner("") is None


def test_money():
    assert m._money("1,234.50") == 1234.50
    assert m._money("$0") is None
    assert m._money("") is None
