"""Guard for the NC county delinquent-tax CSV scraper (New Hanover)."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc import nc_county_csv_delinquent_tax as m

# Two parcels, one with two bill-years (must aggregate + sum), BOM on header.
_CSV = (
    "﻿Customer Name,Property ID,Property Location,Bill Year,Bill Number,Total Receivable\n"
    "HERRING SHELBY J,R01000-005-026-016,22 CASTLE FARMS RD,2016,16000250,$324.77 \n"
    "HERRING SHELBY J,R01000-005-026-016,22 CASTLE FARMS RD,2017,17000250,$400.00 \n"
    'SMITH JANE,R02000-001-002-003,5 OAK ST,2020,20000111,"$1,000.00"\n'  # quoted comma-amount, as the real CSV does
    "BADROW NOAMOUNT,R09-9,,2020,9,\n"   # no amount -> dropped
)


def test_parse_aggregates_bill_years_per_parcel():
    recs = m._parse_csv(_CSV, m.COUNTIES["New Hanover"]["cols"])
    by_parcel = {r["parcel"]: r for r in recs}
    assert set(by_parcel) == {"R01000-005-026-016", "R02000-001-002-003"}  # bad row dropped
    herring = by_parcel["R01000-005-026-016"]
    assert round(herring["amount"], 2) == 724.77          # 324.77 + 400.00 summed
    assert herring["years"] == {"2016", "2017"}
    assert herring["situs"] == "22 CASTLE FARMS RD"


def test_to_listing_carries_situs_and_owed():
    recs = m._parse_csv(_CSV, m.COUNTIES["New Hanover"]["cols"])
    rec = next(r for r in recs if r["parcel"] == "R02000-001-002-003")
    li = m._to_listing(rec, "New Hanover", "http://x")
    assert li.state == "NC" and li.county == "New Hanover"
    assert li.street_address == "5 OAK ST"                # county situs -> no resolver
    assert li.owner_name == "SMITH JANE"
    assert li.parcel_id == "R02000-001-002-003"
    assert li.raw["nc_county_csv_delinquent_tax"]["principal_tax_due"] == 1000.0
    assert li.foreclosure_process == "tax"


def test_registered_and_wired():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_nc.nc_county_csv_delinquent_tax" in slugs
    # Dateless (no sale date) + full-county coastal admission (New Hanover).
    from foreclosure_scraper.main import DATELESS_OK_SOURCES, COASTAL_COUNTY_BYPASS_SOURCES
    assert "counties_nc.nc_county_csv_delinquent_tax" in DATELESS_OK_SOURCES
    assert "counties_nc.nc_county_csv_delinquent_tax" in COASTAL_COUNTY_BYPASS_SOURCES
