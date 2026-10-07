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


# --------------------------------------------------------------------------- FLAGS audit (2026-10-03)
#
# FLAGS is a free-text, comma-joined column every row already carries that
# nothing ever read. Live-verified across 7 tenants: FORECLOSURE (Guilford
# 924/3,547 parcels, 26%; Beaufort; Orange), BANKRUPTCY (Hyde), ADVERTISED,
# OWNERSHIP TRANSFER, Judgement Filed, FINAL NOTICE, HARDSHIP PAY PLAN,
# REJECTED FORECLOSURE (must not count as foreclosure=True), and several USPS
# return-mail codes (RM-NOT DELIVERABLE, RM-VACANT PROPERTY, MAIL RETURNED).

def test_flags_summary_plain_delinquent_only():
    f = m._flags_summary("DLQ")
    assert f["in_foreclosure"] is False
    assert f["tokens"] == ["DLQ"]


def test_flags_summary_detects_foreclosure():
    f = m._flags_summary("DLQ, FORECLOSURE, OWNERSHIP TRANSFER")
    assert f["in_foreclosure"] is True
    assert f["ownership_transfer"] is True
    assert f["foreclosure_rejected"] is False


def test_flags_summary_rejected_foreclosure_is_not_in_foreclosure():
    f = m._flags_summary("ADVERTISED, DLQ, REJECTED FORECLOSURE")
    assert f["in_foreclosure"] is False
    assert f["foreclosure_rejected"] is True
    assert f["advertised"] is True


def test_flags_summary_bankruptcy_and_mail_undeliverable():
    f = m._flags_summary("BANKRUPTCY, DLQ")
    assert f["bankruptcy_mentioned"] is True
    f2 = m._flags_summary("DLQ, RM-NOT DELIVERABLE")
    assert f2["mail_undeliverable"] is True
    f3 = m._flags_summary("ADVERTISED, DLQ, FINAL NOTICE, MAIL RETURNED")
    assert f3["mail_undeliverable"] is True
    assert f3["final_notice"] is True


def test_flags_summary_vacant_property_and_judgment():
    f = m._flags_summary("DLQ, RM-VACANT PROPERTY")
    assert f["vacant_property_flag"] is True
    f2 = m._flags_summary("DLQ, Judgement Filed")
    assert f2["judgment_filed"] is True


def test_flags_summary_blank_is_all_false():
    f = m._flags_summary("")
    assert not any(v for k, v in f.items() if k not in ("raw", "tokens"))
    assert f["tokens"] is None


_FLAGS_CSV = (
    "BILL_TYPE,PARCEL_NUM,TAX_YEAR,OWNER_NAME,MAIL_ADDR1,MAIL_CITY,MAIL_STATE,MAIL_ZIP,"
    "ABSTRACT_ASSESS_VALUE,ABSTRACT_TAXABLE_VALUE,TOTAL_DUE_AMOUNT,BILL_AMOUNT,INTEREST_DUE,"
    "BILL_DUE_DATE,FLAGS,BILL_NUMBER\n"
    # older year: plain DLQ. newest year: FORECLOSURE -- union must catch it.
    "REI,7777,2023,\"HILL, SAM\",10 Pine St,Asheville,NC,28801,100000,100000,400.00,350.00,50.00,"
    "09/01/2023 00:00:00,DLQ,B20\n"
    "REI,7777,2024,\"HILL, SAM\",10 Pine St,Asheville,NC,28801,100000,100000,250.00,220.00,30.00,"
    "09/01/2024 00:00:00,\"DLQ, FORECLOSURE\",B21\n"
)


def test_flags_union_across_aggregated_years_catches_later_foreclosure_flag():
    leads = m._parse_csv(_FLAGS_CSV, "Guilford", "NC", "Guilford")
    assert len(leads) == 1
    li = leads[0]
    assert li.raw["tax_sale_status"] == "in_foreclosure"
    assert li.description.startswith("ACTIVE TAX FORECLOSURE — ")
    tv = li.raw["nc_ptscloud_delinquent_tax"]
    assert tv["flags"]["in_foreclosure"] is True
    # interest + original bill amount summed across both years, same as principal
    assert tv["interest_due"] == 80.0
    assert tv["original_bill_amount"] == 570.0
    assert tv["taxable_value"] == 100000.0
    # bill_due_date is the representative (latest-year) row's own date
    assert tv["bill_due_date"] == "09/01/2024 00:00:00"


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


# --- 2026-10-07 extraction audit: the per-year bill history was read and dropped ---

_YEARS_CSV = (
    "BILL_NUMBER,BILL_TYPE,PARCEL_NUM,TAX_YEAR,OWNER_NAME,ABSTRACT_ASSESS_VALUE,"
    "BILL_STATUS,BILL_AMOUNT,BILL_DUE_AMT,INTEREST_DUE,TOTAL_DUE_AMOUNT,BILL_DUE_DATE\n"
    "B21,REI,7001,2021,\"SAMPLE, PAT\",90000,DLQ,400.00,400.00,120.00,520.00,01/05/2022\n"
    "B23,REI,7001,2023,\"SAMPLE, PAT\",90000,DLQ,410.00,410.00,60.00,470.00,01/05/2024\n"
    "B24,REI,7001,2024,\"SAMPLE, PAT\",90000,DLQ,420.00,200.00,10.00,210.00,01/05/2025\n"
    "B25,REI,7002,2024,\"EXAMPLE, LEE\",50000,DLQ,300.00,300.00,5.00,305.00,01/05/2025\n"
)


def test_every_delinquent_year_is_kept_not_just_the_newest():
    by = {l.parcel_id: l for l in m._parse_csv(_YEARS_CSV, "Madison", "NC", "Madison")}
    b = by["7001"].raw["nc_ptscloud_delinquent_tax"]
    assert b["tax_year"] == "2024"                       # unchanged: newest year
    assert b["years_unpaid"] == ["2021", "2023", "2024"]
    assert b["years_delinquent"] == 3
    assert b["oldest_year"] == "2021"
    assert [y["tax_year"] for y in b["by_year"]] == ["2024", "2023", "2021"]
    assert [y["bill_number"] for y in b["by_year"]] == ["B24", "B23", "B21"]
    assert b["by_year"][0]["bill_due_amt"] == 200.0
    assert b["by_year"][0]["interest_due"] == 10.0
    assert b["by_year"][2]["total_due"] == 520.0
    assert b["by_year"][1]["bill_status"] == "DLQ"
    assert b["unpaid_bill_amount"] == 1010.0             # 400 + 410 + 200
    assert b["principal_tax_due"] == 1200.0              # unchanged: TOTAL_DUE summed


def test_single_year_parcel_reports_one_year():
    by = {l.parcel_id: l for l in m._parse_csv(_YEARS_CSV, "Madison", "NC", "Madison")}
    b = by["7002"].raw["nc_ptscloud_delinquent_tax"]
    assert b["years_delinquent"] == 1 and b["oldest_year"] == "2024"
    assert len(b["by_year"]) == 1


def test_years_reach_the_normalized_tax_block():
    """enrichment_tax_owed promotes years_delinquent from a sibling block."""
    from foreclosure_scraper import enrichment_tax_owed as t
    li = next(l for l in m._parse_csv(_YEARS_CSV, "Madison", "NC", "Madison")
              if l.parcel_id == "7001")
    assert t._find_years_delinquent(li.raw) == 3
