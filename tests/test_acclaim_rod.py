"""Harris Acclaim ROD adapter + SC ROD scraper (probate + liens), parser-only."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod import acclaim
from foreclosure_scraper.scrapers.counties_sc.sc_rod_acclaim import _classify, _to_listing
from foreclosure_scraper.models import ListingType


# --- adapter ---
def test_is_distress():
    assert acclaim.is_distress("D/DIST")          # deed of distribution (probate)
    assert acclaim.is_distress("D/DEATH")
    assert acclaim.is_distress("LIEN")
    assert acclaim.is_distress("L/MECH")          # mechanics lien
    assert not acclaim.is_distress("DEED")
    assert not acclaim.is_distress("MTG")
    assert not acclaim.is_distress("M/SAT")       # satisfaction = resolved
    assert not acclaim.is_distress("L/MECH REL")  # lien release = resolved
    assert not acclaim.is_distress("LN/REL")


def test_parse_date():
    d = acclaim._parse_date("/Date(1780315746000)/")
    assert d and d.year == 2026 and d.month == 6
    assert acclaim._parse_date(None) is None
    assert acclaim._parse_date("garbage") is None


def test_row_to_doc():
    row = {"DocType": "D/DIST", "DirectName": "ADAMS J ESTATE",
           "IndirectName": "COOPER A", "RecordDate": "/Date(1780315746000)/",
           "InstrumentNumber": "202608330", "BookType": "DE", "BookPage": "2962/293",
           "ParcelNumber": "5019-11-66-0241", "Comments": "LOT 9 EASLEY"}
    d = acclaim._row_to_doc(row, "SC", "Pickens")
    assert d.county == "Pickens" and d.state == "SC" and d.doc_type == "D/DIST"
    assert d.grantor == "ADAMS J ESTATE" and d.grantee == "COOPER A"
    assert d.book == "2962" and d.page == "293"
    assert d.instrument_no == "202608330" and d.parcel_id == "5019-11-66-0241"
    assert d.notes == "LOT 9 EASLEY"


# --- scraper classification / listing build ---
def test_classify():
    assert _classify("D/DIST")[0] is ListingType.PROBATE_NOTICE
    assert _classify("D/DEATH")[0] is ListingType.PROBATE_NOTICE
    assert _classify("LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("L/MECH")[0] is ListingType.TAX_LIEN
    assert _classify("L/MECH REL") is None  # release
    assert _classify("DEED") is None
    assert _classify("MTG") is None


def _doc(doc_type, **kw):
    from foreclosure_scraper.rod.models import RodDoc
    base = dict(county="Pickens", state="SC", doc_type=doc_type, grantor="SMITH JOHN ESTATE",
                instrument_no="202600001", parcel_id="1-2-3", notes="LOT 1",
                recorded_date=datetime(2026, 6, 1))
    base.update(kw)
    return RodDoc(**base)


def test_to_listing_probate_tags_signal():
    li = _to_listing(_doc("D/DIST"), "counties_sc.sc_rod_acclaim", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.state == "SC" and li.county == "Pickens" and li.parcel_id == "1-2-3"
    assert li.defendant == "SMITH JOHN ESTATE"
    assert li.raw["relationship_signal"]["kind"] == "probate"


def test_to_listing_lien_is_tax_lien():
    li = _to_listing(_doc("LIEN", grantor="DOE JANE"), "counties_sc.sc_rod_acclaim", "http://x")
    assert li.listing_type is ListingType.TAX_LIEN
    assert "relationship_signal" not in li.raw


def test_to_listing_skips_non_distress():
    assert _to_listing(_doc("DEED"), "s", "u") is None
    assert _to_listing(_doc("M/SAT"), "s", "u") is None
