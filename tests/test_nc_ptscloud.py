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


_PLACEHOLDER_CSV = (
    "BILL_TYPE,PARCEL_NUM,TAX_YEAR,OWNER_NAME,MAIL_ADDR1,MAIL_CITY,MAIL_STATE,MAIL_ZIP,"
    "ABSTRACT_ASSESS_VALUE,TOTAL_DUE_AMOUNT,BILL_NUMBER,DESCRIPTION\n"
    # two DIFFERENT real properties both carry the Farragut "no parcel linked"
    # placeholder PARCEL_NUM=0 -- live-verified on Hyde's export, 532 distinct
    # properties shared this value and the old code collapsed them all into one
    # Listing. DESCRIPTION is the field that is actually per-property here.
    "REI,0,2023,\"JONES, VIOLET\",,,,,30000,100.00,B10,05222-Q9-78\n"
    "REI,0,2024,\"JONES, VIOLET\",,,,,30000,50.00,B11,05222-Q9-78\n"  # same property, 2nd year
    "REI,0,2024,\"WESTON, MAMIE\",,,,,20000,75.00,B12,02757-J10-47\n"
    # a real (non-placeholder) PARCEL_NUM with an embedded GIS PIN -- the PIN
    # should be promoted to parcel_id (cross-source matching), PARCEL_NUM kept
    # as the aggregation key (already correct, tested above) and as parcel_raw.
    "REI,183,2023,\"HAYES RUN REALTY, LLC\",,,,,20400,114.24,B13,"
    "PIN: 09706955900 PROPERTY ACREAGE: 1.64 TOWNSHIP: NORTH MARSHALL\n"
)


def test_placeholder_parcel_num_does_not_collide_distinct_properties():
    leads = m._parse_csv(_PLACEHOLDER_CSV, "Hyde", "NC", "Hyde")
    # 2 distinct real properties under PARCEL_NUM=0, not 1 merged row.
    by_parcel_id = {l.parcel_id: l for l in leads if l.raw["nc_ptscloud_delinquent_tax"]["parcel_raw"] == "0"}
    assert len(by_parcel_id) == 2
    assert by_parcel_id["05222-Q9-78"].owner_name == "JONES, VIOLET"
    # the two-year same-property rows summed, not duplicated
    assert by_parcel_id["05222-Q9-78"].raw["nc_ptscloud_delinquent_tax"]["principal_tax_due"] == 150.00
    assert by_parcel_id["02757-J10-47"].raw["nc_ptscloud_delinquent_tax"]["principal_tax_due"] == 75.00


def test_embedded_pin_promoted_to_parcel_id_over_internal_sequence_number():
    leads = m._parse_csv(_PLACEHOLDER_CSV, "Madison", "NC", "Madison")
    hayes = [l for l in leads if "HAYES" in (l.owner_name or "").upper()]
    assert len(hayes) == 1
    li = hayes[0]
    # the real GIS PIN, not Farragut's internal "183" sequence number
    assert li.parcel_id == "09706955900"
    assert li.raw["nc_ptscloud_delinquent_tax"]["parcel_raw"] == "183"


def test_row_identity_direct():
    # placeholder with no embedded PIN -> DESCRIPTION is the identity
    assert m._row_identity("0", "05222-Q9-78") == ("05222-Q9-78", "05222-Q9-78")
    # placeholder WITH an embedded PIN -> the PIN wins for both
    assert m._row_identity("0", "PIN: 09706955900 ACREAGE 1") == ("09706955900", "09706955900")
    # a real, non-placeholder PARCEL_NUM stays the aggregation key regardless
    assert m._row_identity("1234", "no pin here") == ("1234", "1234")
    assert m._row_identity("1234", "PIN: 09706955900") == ("1234", "09706955900")


def test_stray_nul_byte_does_not_nuke_the_roll():
    # Pitt's real extract carries a lone NUL inside a field; csv.DictReader would
    # raise "line contains NUL" and drop the whole county. _parse_csv must strip
    # it and still return the good rows.
    dirty = _CSV.replace("10 OAK ST", "10 OAK ST\x00")
    leads = m._parse_csv(dirty, "Pitt", "NC", "Pitt")
    by = {l.parcel_id: l for l in leads}
    assert set(by) == {"1234", "5678"}
    assert by["1234"].raw["nc_ptscloud_delinquent_tax"]["principal_tax_due"] == 800.50
