"""Column legal-notice API: five NC counties (tax foreclosures only) and the SC Pee Dee
probate lane (added 2026-09-21).

The owner rule is "flips only in the 18 footprint counties, distressed anywhere in NC and
SC". Washington, Hertford, Bertie, Gates and Martin are not footprint counties, so in those
a MORTGAGE foreclosure sale (a flip) is dropped and only a county/town TAX foreclosure sale
(a distressed lead) is kept, typed TAX_SALE, never FORECLOSURE_SALE.

Every notice text below is hand-built from the shapes read live on 2026-09-21. Names,
parcels and case numbers are invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import pytest

import foreclosure_scraper.scrapers.newspapers.column_legal_notices as m
from foreclosure_scraper.config import in_scope
from foreclosure_scraper.models import ListingType

WASH_TAX = (
    "10 THE ROANOKE BEACON # CLASSIFIEDS Deadlines: Classifieds, Legals 5 p.m. Friday "
    "NOTICE OF TAX FORECLOSURE SALE Under and by virtue of an order of the District Court of "
    "Washington County, North Carolina, made and entered in the action entitled COUNTY OF "
    "WASHINGTON & TOWN OF PLYMOUTH vs. JANE Q PUBLIC and JANE Q PUBLIC'S SPOUSE, if any, and "
    "all possible heirs and assignees of JANE Q PUBLIC, or any other person or entity claiming "
    "thereunder, et al, 25CV000168-930, the undersigned Commissioner will on the 23rd day of "
    "July, 2026, offer for sale and sell for cash, to the last and highest bidder at public "
    "auction at the courthouse door in Washington County, North Carolina, Plymouth, North "
    "Carolina at 12:00 o'clock, noon, the following described real property. Parcel "
    "Identification Number: 6767.12-85-4828 Parcel Identification Number: 6767.15-54-0682 "
    "The undersigned Commissioner makes no warranties in connection with this property."
)
MORTGAGE = (
    "NORTH CAROLINA MARTIN COUNTY Special Proceedings No. 26SP000042-570 Trustee: Philip A. Glass "
    "NOTICE OF FORECLOSURE SALE Date of Sale: September 24, 2026 Time of Sale: 2:30 p.m. "
    "Place of Sale: Martin County Courthouse Record Owners: John Roe Address of Property: "
    "12 Elm St, Williamston, NC 27892 Deed of Trust Book 1 Page 2"
)
DOT_MATTER = ("NOTICE OF FORECLOSURE SALE STATE OF NORTH CAROLINA COUNTY OF MARTIN IN THE GENERAL "
              "COURT OF JUSTICE SUPERIOR COURT DIVISION BEFORE THE CLERK 26SP000047-570 IN THE "
              "MATTER OF THE FORECLOSURE OF A DEED OF TRUST from Someone")
OCR_HYPHEN = (
    "NOTICE OF TAX FORECLO- SURE SALE Under and by virtue of an order of the Dis- trict Court "
    "of Martin County, North Car- olina, made and entered in the action enti- tled TOWN OF "
    "WILLIAMSTON vs. RONNIE D. ROE and RONNIE D. ROE SPOUSE, if any, et al, 22CVD000260-570, "
    "the undersigned Commissioner will on the 4th day of June, 2026, offer for sale. "
    "Parcel Identification Number: 0504346"
)
NORTHAMPTON_NO_COURT = (
    "Proof Client COLUMN NOTICE OF TAX FORECLOSURE SALE made and entered in the action "
    "entitled COUNTY OF NORTHAMPTON vs. LAURA PARKER a/k/a LAURA J PARKER, 23CVD000177-650, "
    "the undersigned Commissioner will on the 10th day of February, 2026, offer for sale. "
    "FC/PID 04-04089"
)


def _item(text, county="Washington", id_="abc-0", ntype="Foreclosure Sale", state="North Carolina"):
    return {"text": text, "county": county, "state": state, "noticetype": ntype,
            "newspapername": "The Test Paper", "publishedtimestamp": 1_784_073_600_000,
            "pdfurl": f"https://example.invalid/{id_}.pdf", "filer": "f", "id": id_}


# --------------------------------------------------------------------------- footprint rule

def test_the_new_counties_are_outside_the_flip_footprint():
    """That is WHY they are tax-only. If one of these ever joins config.NC_COUNTIES, revisit."""
    for c in m.NC_DISTRESSED_ONLY:
        assert not in_scope(c, "NC"), c
    for c in m.SC_DISTRESSED_ONLY:
        assert not in_scope(c, "SC"), c
    assert m.NC_DISTRESSED_ONLY == ("Washington", "Hertford", "Bertie", "Gates", "Martin")
    assert m.SC_DISTRESSED_ONLY == ("Florence", "Marion", "Marlboro")


# --------------------------------------------------------------------------- classifier

@pytest.mark.parametrize("text,expect", [
    (WASH_TAX, True), (OCR_HYPHEN, True), (NORTHAMPTON_NO_COURT, True),
    ("NOTICE OF TAX FORECLOSURE SALE", True),
    ("NOTICE OF TAX FORE- CLOSURE SALE", True),
    (MORTGAGE, False), (DOT_MATTER, False), ("", False), (None, False),
])
def test_tax_versus_mortgage_foreclosure(text, expect):
    assert m.is_tax_foreclosure(text) is expect


# --------------------------------------------------------------------------- parser

def test_washington_tax_notice_fields():
    p = m._parse_nc_tax_foreclosure(WASH_TAX)
    assert p["plaintiff"] == "COUNTY OF WASHINGTON & TOWN OF PLYMOUTH"
    assert p["owner_name"] == "JANE Q PUBLIC"                 # cut before the spouse clause
    assert p["case_number"] == "25CV000168-930"
    assert p["sale_date"] == datetime(2026, 7, 23)
    assert p["sale_time"].startswith("12:00")
    assert p["parcel_id"] == "6767.12-85-4828"
    assert p["parcel_ids"] == ["6767.12-85-4828", "6767.15-54-0682"]
    assert p["county"] == "Washington"


def test_ocr_hyphenation_and_a_spouse_written_without_the_apostrophe():
    p = m._parse_nc_tax_foreclosure(OCR_HYPHEN)
    assert p["plaintiff"] == "TOWN OF WILLIAMSTON"
    assert p["owner_name"] == "RONNIE D. ROE"
    assert p["case_number"] == "22CVD000260-570"
    assert p["sale_date"] == datetime(2026, 6, 4)
    assert p["parcel_id"] == "0504346" and p["county"] == "Martin"


def test_county_falls_back_to_the_plaintiff_when_ocr_loses_the_court_line():
    """Column tags this notice 'Hertford'; it is Northampton's."""
    p = m._parse_nc_tax_foreclosure(NORTHAMPTON_NO_COURT)
    assert "county" in p and p["county"] == "Northampton"
    assert p["owner_name"] == "LAURA PARKER"                  # cut at a/k/a
    assert p["parcel_id"] == "04-04089"                       # the FC/PID form


# --------------------------------------------------------------------------- listing

def _scraper():
    return m.ColumnLegalNotices()


def test_a_tax_notice_is_a_tax_sale_with_the_case_parcel_and_plaintiff():
    li = _scraper()._nc_tax_listing(_item(WASH_TAX), "Washington")
    assert li.listing_type == ListingType.TAX_SALE          # NEVER foreclosure_sale
    assert li.foreclosure_process == "tax"
    assert li.state == "NC" and li.county == "Washington"
    assert li.case_number == "25CV000168-930" and li.parcel_id == "6767.12-85-4828"
    assert li.plaintiff.startswith("COUNTY OF WASHINGTON")
    assert li.owner_name == li.defendant == "JANE Q PUBLIC"
    assert li.sale_date == datetime(2026, 7, 23)
    assert li.source == "counties.column_legal_notices"
    assert li.raw["column"]["tax_foreclosure"]["parcel_ids"] == ["6767.12-85-4828", "6767.15-54-0682"]
    assert li.raw["column"]["tax_foreclosure"]["column_county_tag"] == "Washington"


def test_the_hertford_tag_is_re_derived_to_northampton():
    li = _scraper()._nc_tax_listing(_item(NORTHAMPTON_NO_COURT, county="Hertford"), "Hertford")
    assert li.county == "Northampton"
    assert li.raw["column"]["tax_foreclosure"]["column_county_tag"] == "Hertford"


def test_without_a_sale_date_it_is_only_a_standing_lien():
    text = WASH_TAX.replace("on the 23rd day of July, 2026,", "")
    li = _scraper()._nc_tax_listing(_item(text), "Washington")
    assert li.sale_date is None and li.listing_type == ListingType.TAX_LIEN


def test_a_notice_with_neither_owner_nor_parcel_is_not_a_lead():
    text = "NOTICE OF TAX FORECLOSURE SALE 22CVD000260-570 the undersigned Commissioner will on the 4th day of June, 2026"
    assert _scraper()._nc_tax_listing(_item(text), "Martin") is None


# --------------------------------------------------------------------------- estate county

def test_estate_county_is_read_from_the_body():
    body = "NOTICE TO CREDITORS NORTH CAROLINA, NORTHAMPTON COUNTY File No: 26E000012-650 Having qualified"
    assert m.estate_county(body, "Hertford") == "Northampton"
    assert m.estate_county("no county line here", "Hertford") == "Hertford"


# --------------------------------------------------------------------------- SC probate

def test_sc_case_number_without_dashes_is_captured():
    """Florence and Marlboro print '2026ES2100725'; only Marion dashes it."""
    a = m._parse_sc_probate("IN THE MATTER OF: JANE Q PUBLIC (Decedent) CASE NUMBER: 2026ES2100725 NOTICE")
    assert a["case_number"] == "2026ES2100725"
    b = m._parse_sc_probate("CASE NUMBER 2026-ES-33-00121 IN THE MATTER OF Jane Q Public (Deceased)")
    assert b["case_number"] == "2026-ES-33-00121"


# --------------------------------------------------------------------------- the whole lane

@pytest.fixture
def canned(monkeypatch):
    """Drive fetch() offline: `_query` answers from a table keyed by (state, county, type)."""
    table: dict = {}
    calls: list = []

    async def fake_query(c, state, county, noticetype, from_ms, to_ms):
        calls.append((state, county, noticetype))
        return list(table.get((state, county, noticetype), []))

    @asynccontextmanager
    async def fake_client(*a, **kw):
        yield object()

    monkeypatch.setattr(m, "_query", fake_query)
    monkeypatch.setattr(m, "client", fake_client)
    monkeypatch.setattr(m, "NC_FOOTPRINT", ("Burke",))
    monkeypatch.setattr(m, "SC_FOOTPRINT", ("Anderson",))
    return table, calls


def test_mortgage_foreclosures_are_dropped_and_tax_ones_kept_outside_the_footprint(canned):
    table, calls = canned
    table[("North Carolina", "Martin", "Foreclosure Sale")] = [
        _item(MORTGAGE, "Martin", "m1-0"), _item(DOT_MATTER, "Martin", "m2-0"),
        _item(OCR_HYPHEN, "Martin", "m3-0")]
    table[("North Carolina", "Washington", "Foreclosure Sale")] = [_item(WASH_TAX, "Washington", "w1-0")]
    out = asyncio.run(_scraper().fetch())
    fc = [li for li in out if li.county in ("Martin", "Washington")]
    assert {li.listing_type for li in fc} == {ListingType.TAX_SALE}
    assert not any(li.listing_type == ListingType.FORECLOSURE_SALE for li in fc)
    assert sorted(li.county for li in fc) == ["Martin", "Washington"]


def test_the_same_case_published_twice_under_two_ids_is_one_lead(canned):
    table, _ = canned
    table[("North Carolina", "Washington", "Foreclosure Sale")] = [
        _item(WASH_TAX, "Washington", "w1-0"), _item(WASH_TAX, "Washington", "w2-0")]
    out = asyncio.run(_scraper().fetch())
    assert len([li for li in out if li.county == "Washington"]) == 1


def test_the_footprint_lane_still_emits_foreclosure_sale(canned):
    """Regression guard: Burke is a footprint county, so its mortgage foreclosures stay flips."""
    table, _ = canned
    table[("North Carolina", "Burke", "Foreclosure Sale")] = [_item(MORTGAGE, "Burke", "b1-0")]
    out = asyncio.run(_scraper().fetch())
    burke = [li for li in out if li.county == "Burke"]
    assert len(burke) == 1 and burke[0].listing_type == ListingType.FORECLOSURE_SALE


def test_the_new_counties_are_queried_for_estates_and_the_pee_dee_for_probate(canned):
    table, calls = canned
    asyncio.run(_scraper().fetch())
    asked = set(calls)
    for c in m.NC_DISTRESSED_ONLY:
        assert ("North Carolina", c, "Foreclosure Sale") in asked
        assert ("North Carolina", c, "Estate (Probate) Filings") in asked
        assert ("North Carolina", c, "Notice to Creditors") in asked
    for c in m.SC_DISTRESSED_ONLY:
        assert ("South Carolina", c, "Estate (Probate) Filings") in asked
    # No SC foreclosure lane per Pee Dee county: SC's is one statewide query.
    assert not any(k[0] == "South Carolina" and k[2] == "Foreclosure Sale" and k[1] for k in asked)


def test_a_hertford_tagged_estate_notice_lands_in_northampton(canned):
    table, _ = canned
    body = ("NOTICE TO CREDITORS NORTH CAROLINA, NORTHAMPTON COUNTY File No: 26E000012-650 Having "
            "qualified as Executor of the Estate of John Q Public, deceased, this is to notify")
    table[("North Carolina", "Hertford", "Estate (Probate) Filings")] = [
        _item(body, "Hertford", "e1-0", ntype="Estate (Probate) Filings")]
    out = asyncio.run(_scraper().fetch())
    est = [li for li in out if li.listing_type == ListingType.PROBATE_NOTICE]
    assert len(est) == 1 and est[0].county == "Northampton" and est[0].state == "NC"
    assert est[0].owner_name == "John Q Public"


def test_only_new_counties_skips_the_footprint_lanes_and_the_statewide_sc_query(canned):
    """The ingest script lands just the new counties; nothing else may be queried or re-emitted."""
    table, calls = canned
    table[("North Carolina", "Burke", "Foreclosure Sale")] = [_item(MORTGAGE, "Burke", "b1-0")]
    table[("North Carolina", "Washington", "Foreclosure Sale")] = [_item(WASH_TAX, "Washington", "w1-0")]
    s = _scraper()
    s.only_new_counties = True
    out = asyncio.run(s.fetch())
    assert [li.county for li in out] == ["Washington"]
    asked = set(calls)
    assert not any(k[1] in ("Burke", "Anderson") for k in asked)
    assert not any(k[0] == "South Carolina" and k[1] is None for k in asked)     # statewide lane
    assert ("South Carolina", "Florence", "Estate (Probate) Filings") in asked
