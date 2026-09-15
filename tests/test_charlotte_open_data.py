"""charlotte_open_data.py was rewritten 2026-09-15: the old Socrata
endpoints all redirect to a dead ArcGIS Hub legacy page. The real replacement
is an ArcGIS FeatureServer where FullAddress has no delimiter between the
street and city ("2601 ABELWOOD RD CHARLOTTE, NC 28216") -- a naive lazy
regex split grabs just the house number as "street". Verify the
municipality-anchored parser gets this right."""
from foreclosure_scraper.scrapers.city_websites.charlotte_open_data import (
    _parse_address,
    _to_listing,
)


def test_no_delimiter_address_splits_correctly():
    street, city, zip_code = _parse_address("2601 ABELWOOD RD CHARLOTTE, NC 28216")
    assert street == "2601 ABELWOOD RD"
    assert city == "Charlotte"
    assert zip_code == "28216"


def test_other_municipality_recognized():
    street, city, zip_code = _parse_address("123 MAIN ST HUNTERSVILLE, NC 28078")
    assert street == "123 MAIN ST"
    assert city == "Huntersville"
    assert zip_code == "28078"


def test_multi_word_street_type():
    street, city, zip_code = _parse_address("718 N POPLAR ST CHARLOTTE, NC 28202")
    assert street == "718 N POPLAR ST"
    assert city == "Charlotte"


def test_real_row_converts_with_no_privacy_leak():
    li = _to_listing({
        "CaseNumber": "20190055069",
        "ParcelId": "06916309",
        "CaseType": "Housing",
        "FullAddress": "2601 ABELWOOD RD CHARLOTTE, NC 28216",
        "CaseStatus": "Open",
        "DateCreated": 1570744875000,
        "CouncilDistrict": "2",
        "DetailedDescription": "Violations Cited (98):\r\nContact Inspector",
    })
    assert li is not None
    assert li.street_address == "2601 ABELWOOD RD"
    assert li.city == "Charlotte"
    assert li.county == "Mecklenburg"
    assert li.zip_code == "28216"
    assert li.case_number == "20190055069"
    assert li.parcel_id == "06916309"
    assert li.sale_date is None
    # No inspector email/phone requested or leaked into raw.
    assert "email" not in str(li.raw).lower()
    assert "phone" not in str(li.raw).lower()


def test_missing_address_is_dropped():
    assert _to_listing({"CaseNumber": "1", "FullAddress": None}) is None


def test_missing_case_number_is_dropped():
    assert _to_listing({"FullAddress": "1 MAIN ST CHARLOTTE, NC 28202"}) is None
