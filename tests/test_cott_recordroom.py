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
    assert cr.is_distress("DIS STMT") is True
    assert cr.is_distress("TAX LIEN") is True
    assert cr.is_distress("DEED") is False
    assert cr.is_distress("SAT TAX LIEN") is False          # resolution excluded


def test_classify():
    assert _classify("DEED OF DISTRIBUTION")[0] is ListingType.PROBATE_NOTICE
    assert _classify("DIS STMT")[0] is ListingType.PROBATE_NOTICE
    assert _classify("DEATH/C")[0] is ListingType.PROBATE_NOTICE
    assert _classify("TAX LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("SAT LIEN") is None
    assert _classify("DEED") is None


def test_to_listing_probate_tags_signal():
    d = RodDoc(county="Union", state="SC", doc_type="DEED OF DISTRIBUTION",
               grantor="ALLEN, FLOYD", instrument_no="2026000123", notes="LOT 5")
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant == "ALLEN, FLOYD" and li.county == "Union"


def test_union_wired():
    assert ("SC", "Union") in cr.COTT_RR_COUNTIES
