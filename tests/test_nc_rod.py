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
    _all_grantor_names,
    _doc_to_listing,
)


def test_sources_cover_in_scope_nc_counties():
    """In-scope NC counties with a WIRED ROD vendor must appear.

    Lincoln and Henderson were previously believed to need an unwired
    ASP.NET-MVC install (us4/LincolnNC2) — that was wrong even at the time
    (rod/cchs.py's CCHS_COUNTIES has run BOTH on the SAME live classic-ASP
    SearchService.asp flow as Burke/Cleveland since 2026-06-30/07-27; see that
    module's docstring). This SOURCES list just never got updated after cchs.py
    grew them, so two working counties silently returned 0 leads. Re-verified
    live 2026-09-28: SearchService.asp is Cloudflare-fronted and needs the
    curl-cffi Chrome-fingerprint tier (rod/cchs.py now uses
    http_client.get_text_impersonate for it), not a captured antiforgery token.
    """
    counties = {county for county, _, _ in SOURCES}
    assert counties == {
        "Buncombe", "Polk", "Rutherford", "Burke", "Cleveland",
        "Lincoln", "Henderson",
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


def test_gaston_deliberately_excluded_dead_aumentum_host():
    """Gaston is NOT in SOURCES (2026-10-03). It used to route through the
    Aumentum adapter, but `deeds.gastongov.com` is a confirmed-dead host
    (live-tested 2026-10-03: TCP connects, TLS handshake never completes,
    5+ attempts across multiple tools/timeout values, with sibling Aumentum
    hosts and a general-internet control all answering normally in the same
    session) — Gaston moved its ROD to Courthouse Computer Systems on
    2026-05-28 and this scraper's SOURCES list was never re-pointed. This is
    a regression guard, not just documentation: it fails loudly if someone
    re-adds Gaston to SOURCES without also re-adding a live, re-verified
    host to AUMENTUM_COUNTIES (or a new vendor module for the real CCHS
    LRSearch host, gastonnc.courthousecomputersystems.com)."""
    from foreclosure_scraper.rod.aumentum import AUMENTUM_COUNTIES
    counties = {county for county, _, _ in SOURCES}
    assert "Gaston" not in counties
    assert ("NC", "Gaston") not in AUMENTUM_COUNTIES


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


# ---- multi-grantor (CCHS "one row per party") pre-sale listings ----

def test_pre_sale_defendant_joins_all_cchs_grantors_not_just_the_first():
    """rod/cchs.py serves one <r> row per PARTY and collapses them into
    raw['grantors'] (module docstring: 'Burke 2025: 166 party rows for 55
    documents'). The old code used only doc.grantor (the first party),
    silently dropping every co-owner on a multi-grantor Notice of Sale."""
    doc = RodDoc(
        county="Burke", state="NC",
        doc_type="NOTICE OF SALE",
        recorded_date=datetime(2026, 5, 1),
        instrument_no="20260099999",
        grantor="Hardin Clarence",   # first party row CCHS happened to emit
        grantee="Trustee Acme",
        raw={"grantors": ["Hardin Clarence", "Hardin Oma"]},
    )
    li = _doc_to_listing(doc, vendor_label="cchs")
    assert li.defendant == "Hardin Clarence; Hardin Oma"
    assert li.raw["nc_rod"]["grantors"] == ["Hardin Clarence", "Hardin Oma"]


def test_pre_sale_defendant_dedupes_repeated_grantor_rows():
    doc = RodDoc(
        county="Cleveland", state="NC",
        doc_type="LIS PENDENS",
        grantor="Smith John",
        raw={"grantors": ["Smith John", "Smith John", "Smith John"]},
    )
    assert _all_grantor_names(doc) == "Smith John"


def test_pre_sale_defendant_falls_back_to_plain_grantor_without_a_list():
    """Aumentum/Cott docs never populate raw['grantors'] — behavior for
    those vendors must be unchanged (single doc.grantor, as before)."""
    doc = RodDoc(
        county="Buncombe", state="NC",
        doc_type="NOTICE OF SALE",
        grantor="Smith John",
        raw={},
    )
    assert _all_grantor_names(doc) == "Smith John"


def test_all_grantor_names_handles_no_raw_dict_at_all():
    doc = RodDoc(county="Polk", state="NC", doc_type="LIS PENDENS", grantor="Brown Jane")
    assert _all_grantor_names(doc) == "Brown Jane"


# ---- scraper class metadata ----

def test_scraper_class_metadata():
    s = NCRodSubstituteTrustee()
    assert s.slug == "counties_nc.nc_rod_substitute_trustee"
    # No longer requires_render — the vendor modules use plain httpx
    assert s.requires_render is False
    # Empty weeks are normal for ROD scraping (small counties)
    assert s.expected_min_count == 0


def test_spartan_weekly_pr_regex_handles_out_of_state_and_pobox():
    """PR mailing-address regex must keep out-of-state executors + PO-Box lines
    (the absentee-heir cases the old SC|NC|GA-only pattern dropped)."""
    from foreclosure_scraper.scrapers.counties_sc.spartan_weekly_legals import _PROBATE_PR
    cases = {
        "Personal Representative: Michael Davis 10 Pipeline Lane Lyman, SC 29365":
            ("Michael Davis", "SC"),
        "Personal Representative: Riedar Mark Oestenstad 3245 260th Avenue Spencer, IA 51301":
            ("Riedar Mark Oestenstad", "IA"),
        "Personal Representative: Cathy Phillips Holland Post Office Box 24, Moore, SC 29369":
            ("Cathy Phillips Holland", "Box"),
    }
    for body, (name, addr_marker) in cases.items():
        m = _PROBATE_PR.search(body)
        assert m, f"no match: {body}"
        assert m.group(1).strip() == name
        assert addr_marker in m.group(2)
