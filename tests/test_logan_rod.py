"""Logan 'The Lookup' ROD adapter parser + NC scraper classification."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod import logan
from foreclosure_scraper.scrapers.counties_nc.nc_rod_logan import _classify, _to_listing
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod.models import RodDoc

_FIXTURE = """
<a href="javascript: loadDetailsScreen('2026002775');" id="link_2026002775"> 06/12/2026&nbsp; </a></td>
<td class="summary" id="2026002775">DOC 1191  835 &nbsp; </td>
<td class="summary" id="2026002775">TR/D&nbsp;</td>
<td class="summary" id="2026002775">CONNESTEE FALLS LT:112&nbsp;</td>
<td class="summary" id="2026002775">GRANTOR&nbsp;</td>
<td class="summary" id="2026002775">FEHSENFELD CAROLYN C TR&nbsp;</td>
<td class="summary" id="2026002775">ACME BANK NA&nbsp;</td>
"""


def test_parse_records():
    docs = logan._parse_records(_FIXTURE, "NC", "Transylvania")
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_type == "TR/D"
    assert d.recorded_date == datetime(2026, 6, 12)
    assert d.book == "1191" and d.page == "835"
    assert d.grantor == "FEHSENFELD CAROLYN C TR"   # party_type GRANTOR -> searched
    assert d.grantee == "ACME BANK NA"
    assert d.instrument_no == "2026002775"
    assert "CONNESTEE" in d.notes


def test_parse_grantee_party_flips_sides():
    fx = _FIXTURE.replace("GRANTOR&nbsp;", "GRANTEE&nbsp;")
    d = logan._parse_records(fx, "NC", "Transylvania")[0]
    assert d.grantee == "FEHSENFELD CAROLYN C TR"   # searched is now grantee
    assert d.grantor == "ACME BANK NA"


def test_classify():
    assert _classify("FCL")[0] is ListingType.LIS_PENDENS
    assert _classify("S/TR")[0] is ListingType.LIS_PENDENS
    assert _classify("TR/D")[0] is ListingType.FORECLOSURE_SALE
    assert _classify("SHF/D")[0] is ListingType.FORECLOSURE_SALE
    assert _classify("D/DIST")[0] is ListingType.PROBATE_NOTICE
    assert _classify("LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("JUDGMENT")[0] is ListingType.TAX_LIEN
    assert _classify("DEED") is None
    assert _classify("MTG") is None


def test_to_listing_probate_tags_signal():
    doc = RodDoc(county="Transylvania", state="NC", doc_type="D/DIST",
                 grantor="SMITH ESTATE", instrument_no="2026000001",
                 notes="LOT 1", recorded_date=datetime(2026, 6, 1))
    li = _to_listing(doc, "counties_nc.nc_rod_logan", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant == "SMITH ESTATE" and li.county == "Transylvania"


def test_to_listing_skips_non_distress():
    doc = RodDoc(county="Transylvania", state="NC", doc_type="DEED", grantor="X")
    assert _to_listing(doc, "s", "u") is None


def test_logan_counties_are_the_three_working_nc():
    assert set(logan.LOGAN_COUNTIES) == {("NC", "Transylvania"), ("NC", "McDowell"), ("NC", "Mitchell")}
