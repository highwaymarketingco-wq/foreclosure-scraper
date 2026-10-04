"""Cott RecordRoom adapter (Union SC) — HTML cleaning, distress filter, classify."""
from __future__ import annotations

from foreclosure_scraper.rod import cott_recordroom as cr
from foreclosure_scraper.scrapers.counties_sc.sc_rod_cott import _classify, _to_listing
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod.models import RodDoc


def test_clean_strips_html():
    assert cr._clean("<div>DENKERS, TIMOTHY</div>") == "DENKERS, TIMOTHY"
    assert cr._clean("DEE<br/>DIS STMT") == "DEE DIS STMT"
    assert cr._clean(None) == ""


def test_is_distress():
    assert cr.is_distress("DEE<br/>DOD") is True            # deed of distribution
    assert cr.is_distress("<div>DEATH/C</div>") is True
    assert cr.is_distress("TAX LIEN") is True
    assert cr.is_distress("DEED") is False
    assert cr.is_distress("SAT TAX LIEN") is False          # resolution excluded
    # 2026-10-04 (batch 13): "DIS STMT" is NOT a probate signal. Live-pulled
    # every "DEE DIS STMT" row Union has recorded in the last 90 days (37 of
    # them, 74% of this adapter's live output) -- all 37 are "HOMEOWNERS
    # DISCLOSURE STATEMENT" filings with the Dept of Building Safety / City
    # Planning Dept as the counterparty, never an estate distribution
    # statement. Was a 100% false-positive match; removed from _DISTRESS.
    assert cr.is_distress("DEE<br/>DIS STMT") is False


def test_classify():
    assert _classify("DEED OF DISTRIBUTION")[0] is ListingType.PROBATE_NOTICE
    assert _classify("DEATH/C")[0] is ListingType.PROBATE_NOTICE
    assert _classify("TAX LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("SAT LIEN") is None
    assert _classify("DEED") is None
    # Same false-positive fix as test_is_distress, on the scraper-side classifier.
    assert _classify("DIS STMT") is None


def test_property_block_extraction():
    """Parcel #, situs address, remarks and $ consideration embedded inside the
    vendor's own HTML cells (not plain text) -- live-shaped sample from a real
    Union "DEE DOD" deed-of-distribution row (2026-10-04 audit)."""
    prop_html = (
        '<div><div data-propertyid="16734651"><div class="indexdetail_primary">'
        '<strong>City Name:</strong> <span class="indexdetail_data">UNION COUNTY</span> '
        '<strong>Parcel #:</strong> <span class="indexdetail_data">'
        '<a class="gpinActive" href="../../Search?parcelNumber=074-10-02-003">074-10-02-003</a>'
        '</span> <strong>Remarks:</strong> <span class="indexdetail_data">LOT OF LAND W/IMP '
        'FRONTING ON PERRIN AVENUE. SEE INSTRUMENT</span></div>'
        '<div class="indexdetail_address"><strong>Address: </strong>'
        '<span class="indexdetail_data">709 PERRIN AVENUE  UNION, SC 29379</span></div>'
        '</div></div>'
    )
    assert cr._extract_parcel(prop_html) == "074-10-02-003"
    assert cr._extract_block_address(prop_html) == "709 PERRIN AVENUE UNION, SC 29379"
    assert cr._extract_remarks(prop_html) == "LOT OF LAND W/IMP FRONTING ON PERRIN AVENUE. SEE INSTRUMENT"
    assert cr._extract_amount(prop_html) is None  # deed of distribution: no consideration

    deed_html = (
        '<span class="amtDesc"> <strong>Amount:</strong> $500.00</span>'
        '<div><div data-propertyid="1"><div class="indexdetail_primary">'
        '<strong>Parcel #:</strong> <span class="indexdetail_data">'
        '<a href="#">074-07-13-001.000</a></span></div></div></div>'
    )
    assert cr._extract_amount(deed_html) == 500.00

    party_html = (
        '<div>KNOX, BARBARA DOVER<div class="indexdetail_address">'
        '<span class="indexdetail_label">Address: </span>'
        '<span class="indexdetail_data">522 T BISHOP ROAD JONESVILLE, SC 29353</span>'
        '</div></div>'
    )
    assert cr._extract_block_address(party_html) == "522 T BISHOP ROAD JONESVILLE, SC 29353"
    assert cr._extract_parcel(party_html) is None


def test_to_listing_wires_parcel_and_address():
    """sc_rod_cott._to_listing must carry parcel_id/street_address through from
    the RodDoc, matching the sibling sc_rod_acclaim.py convention (previously
    missing entirely on this adapter -- see test_property_block_extraction)."""
    d = RodDoc(county="Union", state="SC", doc_type="DEED OF DISTRIBUTION",
               grantor="ALLEN, FLOYD", instrument_no="2026000123", notes="LOT 5",
               parcel_id="074-10-02-003", property_address="709 PERRIN AVENUE UNION, SC 29379",
               raw={"cott_recordroom": {"grantee_address": "522 T BISHOP ROAD JONESVILLE, SC 29353",
                                        "consideration_amount": 500.0}})
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.parcel_id == "074-10-02-003"
    assert li.street_address == "709 PERRIN AVENUE UNION, SC 29379"
    assert li.raw["rod"]["grantee_address"] == "522 T BISHOP ROAD JONESVILLE, SC 29353"
    assert li.raw["rod"]["consideration_amount"] == 500.0


def test_to_listing_probate_tags_signal():
    d = RodDoc(county="Union", state="SC", doc_type="DEED OF DISTRIBUTION",
               grantor="ALLEN, FLOYD", instrument_no="2026000123", notes="LOT 5")
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant == "ALLEN, FLOYD" and li.county == "Union"


def test_union_wired():
    assert ("SC", "Union") in cr.COTT_RR_COUNTIES
