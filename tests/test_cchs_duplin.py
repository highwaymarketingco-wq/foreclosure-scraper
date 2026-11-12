"""Duplin NC added to the classic-ASP CCHS platform (rod/cchs.py's CCHS_COUNTIES) and to
enrichment_cchs_rod.py's own county list, 2026-10-18. The fixture below
(rod_cchs_duplin_lis_pendens_rows.xml) is a genuine live capture, not hand-written: a real
90-day SearchService.asp getall answer off us4.courthousecomputersystems.com/duplinncnw
(curl-cffi chrome impersonation, same escalation tier get_text(..., impersonate=True) already
auto-tries), a real LIS PENDENS -- Book 2126/Page 570, Doc# 10070136, "NOTICE OF" -- with
several grantor/grantee party rows (GORE MIRACALE SHANTE'T, GORE ZONNIE LAWON, BOEHLING
LAWRENCE S., COLEMAN NATHANIEL T, among others on the same instrument). See rod/cchs.py's
CCHS_COUNTIES docstring comment for the full live-verification note (root and
application.asp both 403, neither blocks the flow actually used).
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.rod import cchs

FIX = Path(__file__).parent / "fixtures" / "rod_cchs_duplin_lis_pendens_rows.xml"
DUPLIN_GETALL_XML = FIX.read_text()


def test_duplin_is_on_the_classic_cchs_platform_same_vendor_as_the_western_nc_five():
    assert ("NC", "Duplin") in cchs.CCHS_COUNTIES
    host, app, root = cchs.CCHS_COUNTIES[("NC", "Duplin")]
    assert host == "us4" and app == "duplinncnw" and root == "duplinnc"


def test_duplin_search_url_and_base():
    assert cchs.search_url("NC", "Duplin") == (
        "https://us4.courthousecomputersystems.com/duplinncnw/realestatesearch.asp")


def test_duplin_getall_fixture_parses_into_a_real_lis_pendens_document():
    docs = cchs._parse_rows(DUPLIN_GETALL_XML, "NC", "Duplin", sold=False)
    assert docs, "the real captured fixture must parse into at least one document"
    doc = docs[0]
    assert doc.book == "2126" and doc.page == "570" and doc.instrument_no == "10070136"
    assert doc.county == "Duplin" and doc.state == "NC"
    names = set(doc.raw["grantors"]) | set(doc.raw["grantees"])
    assert any("GORE" in n for n in names)


def test_duplin_is_in_enrichment_cchs_rod_county_list():
    import foreclosure_scraper.enrichment_cchs_rod as C
    assert "Duplin" in C._COUNTIES
