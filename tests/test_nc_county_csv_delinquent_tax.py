"""NC county CSV delinquent-tax extraction-completeness audit (2026-10-03).

Live-pulled New Hanover's real CSV (3,544 rows): header is "Customer Name,
Property ID,Property Location,Bill Year,Bill Number,Total Receivable" --
"Bill Number" (100% filled, the county's own per-year tax-bill id) was read
nowhere. 629 of 1,404 live parcels carry 2+ billing years, so the fix keys
bill numbers by year rather than a flat list to avoid losing the pairing."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_county_csv_delinquent_tax import (
    COUNTIES,
    _parse_csv,
    _to_listing,
)

_COLS = COUNTIES["New Hanover"]["cols"]

# Shape mirrors the real live CSV (owner/parcel/amounts changed).
_CSV_TEXT = (
    "Customer Name,Property ID,Property Location,Bill Year,Bill Number,Total Receivable\n"
    "DOE JOHN,R01000-005-026-016,22 CASTLE FARMS RD,2016,16000250,$324.77 \n"
    "DOE JOHN,R01000-005-026-016,22 CASTLE FARMS RD,2017,17000252,$341.10 \n"
    "SMITH JANE,R02500-003-008-000,1524 ROCK HILL RD,2016,16003059,\"$1,547.16 \"\n"
)


def test_parse_csv_keys_bill_numbers_by_year_not_a_flat_list():
    recs = _parse_csv(_CSV_TEXT, _COLS)
    by_parcel = {r["parcel"]: r for r in recs}
    multi = by_parcel["R01000-005-026-016"]
    assert multi["bill_numbers"] == {"2016": "16000250", "2017": "17000252"}
    single = by_parcel["R02500-003-008-000"]
    assert single["bill_numbers"] == {"2016": "16003059"}


def test_parse_csv_sums_amount_across_years():
    recs = _parse_csv(_CSV_TEXT, _COLS)
    multi = next(r for r in recs if r["parcel"] == "R01000-005-026-016")
    assert round(multi["amount"], 2) == 665.87


def test_to_listing_surfaces_bill_numbers_in_raw():
    rec = _parse_csv(_CSV_TEXT, _COLS)[0]
    li = _to_listing(rec, "New Hanover", COUNTIES["New Hanover"]["url"])
    raw = li.raw["nc_county_csv_delinquent_tax"]
    assert raw["bill_numbers"] == {"2016": "16000250", "2017": "17000252"}
    assert raw["bill_years"] == ["2016", "2017"]


def test_parse_csv_without_bill_number_column_does_not_crash():
    """A county config with no 'bill_number' mapped must still work cleanly."""
    cols_no_bill = {k: v for k, v in _COLS.items() if k != "bill_number"}
    recs = _parse_csv(_CSV_TEXT, cols_no_bill)
    assert recs and all(r["bill_numbers"] == {} for r in recs)
