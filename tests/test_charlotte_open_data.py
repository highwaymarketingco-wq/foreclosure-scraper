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


# --- board audit 2026-09-23: street_address vs parcel-cache situs mismatch -------
# 471 charlotte_open_data rows disagreed with their own parcel_id's county-cache
# situs. Root-caused live against gis.charlottenc.gov/.../CodeEnforcementCasesAll:
# a real (non-fabricated) minority have a FullAddress with no zip code at all, which
# used to make _parse_address() fall through to its unsplit-string branch and leak
# "CHARLOTTE, NC" into street_address. Real examples below, pulled live 2026-09-23.

def test_ziplessfull_address_strips_city_state_case_20210033745():
    """Live case 20210033745 (parcel 16914128), pulled 2026-09-23:
    FullAddress = '435 GRIFFITH RD CHARLOTTE, NC ' (no zip). Before the fix this
    landed on the board as street_address '435 GRIFFITH RD CHARLOTTE, NC' -- the
    city/state never got stripped because _MUNI_RE required a trailing zip that
    isn't there. The parcel cache's own situs for 16914128 is road-only
    ('GRIFFITH RD CHARLOTTE NC', no house number -- unrelated, pre-existing gap,
    not something this fix can or should paper over)."""
    street, city, zip_code = _parse_address("435 GRIFFITH RD CHARLOTTE, NC ")
    assert street == "435 GRIFFITH RD"
    assert city == "Charlotte"
    assert zip_code is None


def test_zipless_house_numberless_address_is_dropped_not_leaked_case_20200051423():
    """Live case 20200051423 (parcel 03505220), pulled 2026-09-23:
    FullAddress = 'OAK ST CHARLOTTE, NC ' -- the city's own record has no house
    number AND no zip (contrast case 20190052019 / 20210024261 on the SAME
    parcel, which both have '400 OAK ST CHARLOTTE, NC 28214'). Before the fix this
    landed on the board as street_address 'OAK ST CHARLOTTE, NC' -- unstripped
    city/state text standing in for a street address, matched against parcel
    03505220's real cache situs '400 OAK ST (3) CHARLOTTE NC' and flagged as a
    mismatch. A street with no house number can't be targeted as a lead, so the
    fix drops the record instead of shipping the garbage string."""
    street, city, zip_code = _parse_address("OAK ST CHARLOTTE, NC ")
    assert street is None
    assert city == "Charlotte"  # still identified; only the unusable street is dropped
    li = _to_listing({
        "CaseNumber": "20200051423",
        "ParcelId": "03505220",
        "CaseType": "Zoning",
        "FullAddress": "OAK ST CHARLOTTE, NC ",
        "CaseStatus": "Open",
        "DateCreated": 1608235735000,
        "CouncilDistrict": "2",
    })
    assert li is None


def test_same_parcel_two_addressed_units_is_not_a_parse_bug_case_08114106():
    """Live parcel 08114106, pulled 2026-09-23: ten Housing/Nuisance cases
    spanning 2020-2026 genuinely alternate between FullAddress '912 Parkwood Av'
    and '914 Parkwood Av' for the SAME ParcelId (a duplex on one tax parcel).
    Both addresses parse correctly and cleanly; a parcel-cache situs of just one
    of the two ('914 Parkwood Av') is expected, not a scraper bug -- see the
    module docstring. Regression guard: neither address should get mangled or
    dropped by the fix above (both have a real house number)."""
    for full in ("912 PARKWOOD AV CHARLOTTE, NC 28205", "914 PARKWOOD AV CHARLOTTE, NC 28205"):
        street, city, zip_code = _parse_address(full)
        assert street in ("912 PARKWOOD AV", "914 PARKWOOD AV")
        assert city == "Charlotte"
        assert zip_code == "28205"
