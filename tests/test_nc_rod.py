"""Tests for the NC Register-of-Deeds pre-foreclosure scraper.

After 2026-05-07e the scraper delegates to the working
rod/aumentum + rod/cott + rod/cchs modules instead of an unreachable
Permitium portal. These tests pin the scope (which counties), the
vendor mapping, and the RodDoc -> Listing conversion logic.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod.models import RodDoc
from foreclosure_scraper.scrapers.counties_nc.nc_rod_substitute_trustee import (
    SOURCES,
    NCRodSubstituteTrustee,
    _doc_to_listing,
)


def test_sources_cover_in_scope_nc_counties():
    """In-scope NC counties with a WIRED ROD vendor must appear.

    Lincoln is intentionally absent: its CCHS install is the ASP.NET-MVC variant
    (us4/LincolnNC2) whose ExecuteSearch needs a captured antiforgery payload —
    not yet wired (returns 500 on a blind POST). Lincoln foreclosures still flow
    via nc_ecourts_lis_pendens + the law-firm scrapers, so it's not lead-blind;
    only the ROD substitute-trustee layer is pending. Re-add when MVC is wired.
    """
    counties = {county for county, _, _ in SOURCES}
    assert counties == {
        "Buncombe", "Gaston", "Polk", "Rutherford", "Burke", "Cleveland",
    }


def test_vendor_labels_only_cover_known_vendors():
    """Only aumentum/cott/cchs are wired — kofile not yet for any
    in-scope NC county. If a future county uses kofile, add it here
    and to the SOURCES list."""
    labels = {label for _, _, label in SOURCES}
    assert labels <= {"aumentum", "cott", "cchs"}


def test_aumentum_counties_match():
    """Cross-check: every Aumentum entry in SOURCES must be in the
    vendor module's AUMENTUM_COUNTIES dict, otherwise the search call
    returns [] silently."""
    from foreclosure_scraper.rod.aumentum import AUMENTUM_COUNTIES
    aumentum_in_sources = {c for c, _, l in SOURCES if l == "aumentum"}
    aumentum_supported = {county for (state, county) in AUMENTUM_COUNTIES if state == "NC"}
    assert aumentum_in_sources <= aumentum_supported, (
        f"SOURCES has Aumentum counties not in AUMENTUM_COUNTIES: "
        f"{aumentum_in_sources - aumentum_supported}"
    )


def test_cott_counties_match():
    from foreclosure_scraper.rod.cott import COTT_COUNTIES
    cott_in_sources = {c for c, _, l in SOURCES if l == "cott"}
    cott_supported = {county for (state, county) in COTT_COUNTIES if state == "NC"}
    assert cott_in_sources <= cott_supported


def test_cchs_counties_match():
    from foreclosure_scraper.rod.cchs import CCHS_COUNTIES
    cchs_in_sources = {c for c, _, l in SOURCES if l == "cchs"}
    cchs_supported = {county for (state, county) in CCHS_COUNTIES if state == "NC"}
    assert cchs_in_sources <= cchs_supported


# ---- _doc_to_listing conversion ----

def test_doc_with_instrument_no():
    doc = RodDoc(
        county="Buncombe", state="NC",
        doc_type="NOTICE OF SALE",
        recorded_date=datetime(2026, 5, 1),
        instrument_no="20260054321",
        grantor="Smith John",
        grantee="Trustee Acme",
        book="1234", page="56",
    )
    li = _doc_to_listing(doc, vendor_label="aumentum")
    assert li.state == "NC"
    assert li.county == "Buncombe"
    assert li.case_number == "INST-20260054321"
    assert li.defendant == "Smith John"
    assert li.plaintiff == "Trustee Acme"
    nc_rod = li.raw["nc_rod"]
    assert nc_rod["vendor"] == "aumentum"
    assert nc_rod["doc_type"] == "NOTICE OF SALE"
    assert nc_rod["recorded_date"] == "2026-05-01T00:00:00"


def test_doc_without_instrument_uses_book_page():
    """Some recordings only have book/page, no instrument_no."""
    doc = RodDoc(
        county="Polk", state="NC",
        doc_type="LIS PENDENS",
        recorded_date=datetime(2026, 4, 22),
        book="9876", page="123",
        grantor="Brown Jane",
    )
    li = _doc_to_listing(doc, vendor_label="cott")
    assert li.case_number == "BK9876-PG123"
    assert li.county == "Polk"


def test_source_url_resolves_to_vendor_search_page():
    """The source_url should link back to the vendor's search portal so
    investors can pull the actual recorded document."""
    doc = RodDoc(
        county="Buncombe", state="NC",
        doc_type="NOTICE OF SALE",
        recorded_date=datetime(2026, 5, 1),
        grantor="Smith",
    )
    li = _doc_to_listing(doc, vendor_label="aumentum")
    # Buncombe's official ROD search portal (current host; the old .org vendor
    # domain was retired). source_url must land on the searchable record page.
    assert "registerofdeeds.buncombenc.gov" in li.source_url
    assert li.source_url.lower().endswith(".aspx")


def test_doc_listing_type_is_lis_pendens():
    """These are pre-foreclosure recordings (NOD/NOS) — not yet sold.
    Marking as LIS_PENDENS makes them flow through DATELESS_OK_SOURCES."""
    from foreclosure_scraper.models import ListingType
    doc = RodDoc(
        county="Burke", state="NC",
        doc_type="NOTICE OF FORECLOSURE SALE",
        recorded_date=datetime(2026, 5, 1),
        grantor="Doe John",
    )
    li = _doc_to_listing(doc, vendor_label="cchs")
    assert li.listing_type == ListingType.LIS_PENDENS


# ---- scraper class metadata ----

def test_scraper_class_metadata():
    s = NCRodSubstituteTrustee()
    assert s.slug == "counties_nc.nc_rod_substitute_trustee"
    # No longer requires_render — the vendor modules use plain httpx
    assert s.requires_render is False
    # Empty weeks are normal for ROD scraping (small counties)
    assert s.expected_min_count == 0
