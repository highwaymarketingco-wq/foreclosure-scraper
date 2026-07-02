"""Terry Howe FLC parser — county filter + TaxID-table parcel extraction."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc import terry_howe_flc as th


def test_county_of_keeps_in_footprint_sc():
    assert th._county_of("Spartanburg County, SC – 8 Properties for FLC") == "Spartanburg"
    assert th._county_of("Laurens County, SC – 6 Properties") == "Laurens"


def test_county_of_drops_out_of_footprint():
    # Fairfield is not in the SC footprint; a city-only title has no county.
    assert th._county_of("Fairfield County, SC – 6 Properties") is None
    assert th._county_of("Rock Hill, SC – 4 BR home") is None


def test_split_row_pulls_street_and_city_dropping_state():
    assert th._split_row("817 Saxon Ave, Spartanburg, SC") == ("817 Saxon Ave", "Spartanburg")
    assert th._split_row("Off Dodd St, Wellford, SC") == ("Off Dodd St", "Wellford")
    # single-field cell => street only, no city
    assert th._split_row("Cherry Rd") == ("Cherry Rd", None)


def test_split_row_city_is_field_before_state_not_unit():
    # A unit field sits between street and city; the city is the field just
    # before ", SC", and the trailing Type/notes column is dropped.
    street, city = th._split_row("505 N Broad St, Units A&B, Clinton, SC Duplex. Rented.")
    assert city == "Clinton"
    assert street == "505 N Broad St, Units A&B"


def test_split_row_drops_trailing_type_column():
    assert th._split_row("1123 Sunset Park Ext, Laurens, SC House") == (
        "1123 Sunset Park Ext", "Laurens")


def test_parse_flc_rows_upstate_dashed_table():
    # Real Spartanburg body shape: "TaxID Description" then dashed TMS + addr, SC.
    body = (
        "Bidding starts at $100. TaxID Description "
        "5-16-09-084.02 Off Dodd St, Wellford, SC "
        "6-18-07-053.00 817 Saxon Ave, Spartanburg, SC "
        "7-15-04-009.00 4 Buckthorn Rd, Spartanburg, SC "
        "9-05-02-031.00 111 Spruce Ave, Greer, SC"
    )
    rows = th.parse_flc_rows(body)
    assert len(rows) == 4
    by_parcel = {r["parcel_id"]: r for r in rows}
    # every row carries a real TMS Parcel ID
    assert set(by_parcel) == {"5-16-09-084.02", "6-18-07-053.00",
                              "7-15-04-009.00", "9-05-02-031.00"}
    # house-number address + city captured
    assert by_parcel["6-18-07-053.00"]["street_address"] == "817 Saxon Ave"
    assert by_parcel["6-18-07-053.00"]["city"] == "Spartanburg"
    assert by_parcel["9-05-02-031.00"]["city"] == "Greer"
    # "Off <street>" locator parcels are KEPT (they are real forfeited lots)
    assert by_parcel["5-16-09-084.02"]["street_address"] == "Off Dodd St"
    assert by_parcel["5-16-09-084.02"]["city"] == "Wellford"


def test_parse_flc_rows_long_dotted_zero_table():
    # Fairfield-style long TMS ("088-00-00-068-000").
    body = (
        "Tax ID Description "
        "088-00-00-068-000 Off Chester Rd, Winnsboro, SC "
        "126-04-01-006-000 410 Davis Cir, Winnsboro, SC"
    )
    rows = th.parse_flc_rows(body)
    assert len(rows) == 2
    by_parcel = {r["parcel_id"]: r for r in rows}
    assert by_parcel["126-04-01-006-000"]["street_address"] == "410 Davis Cir"
    assert by_parcel["126-04-01-006-000"]["city"] == "Winnsboro"


def test_parse_flc_rows_dedups_repeat_parcel():
    body = ("TaxID Description "
            "6-18-07-053.00 817 Saxon Ave, Spartanburg, SC "
            "6-18-07-053.00 817 Saxon Ave, Spartanburg, SC")
    rows = th.parse_flc_rows(body)
    assert len(rows) == 1


def test_parse_flc_rows_fallback_address_harvest_when_no_table():
    # No "TaxID Description" table and no TMS tokens — fall back to a plain
    # street-address harvest (parcel_id None) so older posts still surface.
    body = "These FLC lots include 817 Saxon Ave and 4 Buckthorn Rd this spring."
    rows = th.parse_flc_rows(body)
    streets = {r["street_address"] for r in rows}
    assert "817 Saxon Ave" in streets
    assert "4 Buckthorn Rd" in streets
    assert all(r["parcel_id"] is None for r in rows)
