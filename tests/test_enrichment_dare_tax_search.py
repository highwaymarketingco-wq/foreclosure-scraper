"""enrichment_dare_tax_search.py's pure parsing against real captured responses (2026-11-28,
tests/fixtures/dare_taxcert_*.html). See that module's docstring for the live site shape and
the 9-digit-vs-12-digit parcel scoping decision."""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper import enrichment_dare_tax_search as m
from foreclosure_scraper.models import Listing, ListingType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_an_all_paid_result():
    html = (FIXTURES / "dare_taxcert_allpaid.html").read_text()
    bills = m._parse_bills(html)
    assert len(bills) == 10
    assert all(b["status"] == "paid" and b["total_due"] is None for b in bills)
    assert {b["year"] for b in bills} == set(range(2017, 2027))


def test_parses_one_delinquent_year_among_several_paid():
    html = (FIXTURES / "dare_taxcert_onedelinquent.html").read_text()
    bills = m._parse_bills(html)
    by_year = {b["year"]: b for b in bills}
    assert by_year[2026] == {"year": 2026, "status": "unpaid", "total_due": 1651.87}
    for y in (2019, 2020, 2021, 2022, 2023, 2024, 2025):
        assert by_year[y]["status"] == "paid"


def test_parses_no_record_sentinel_as_empty():
    html = (FIXTURES / "dare_taxcert_norecord.html").read_text()
    assert m._parse_bills(html) == []


def test_eligible_requires_the_9digit_shape_not_the_12digit_pin_shape():
    nine_digit = Listing.model_construct(state="NC", county="Dare", parcel_id="014822090",
                                         raw={})
    assert m._eligible(nine_digit)

    twelve_digit_pin = Listing.model_construct(state="NC", county="Dare",
                                               parcel_id="987309166326", raw={})
    assert not m._eligible(twelve_digit_pin), (
        "the board's 12-digit PIN shape is NOT the 9-digit tax-parcel-number this portal "
        "searches by -- see the module docstring's crosswalk note")

    wrong_state = Listing.model_construct(state="SC", county="Dare", parcel_id="014822090",
                                          raw={})
    assert not m._eligible(wrong_state)

    wrong_county = Listing.model_construct(state="NC", county="Currituck",
                                            parcel_id="014822090", raw={})
    assert not m._eligible(wrong_county)

    already_done = Listing.model_construct(
        state="NC", county="Dare", parcel_id="014822090",
        raw={"dare_delinquent_tax": {"bills": []}})
    assert not m._eligible(already_done)


class _FakeSession:
    def __init__(self, html: str):
        self._html = html

    def get(self, *a, **k):
        return _FakeResp(self._html)


class _FakeResp:
    def __init__(self, text: str):
        self.text = text


def test_enrich_writes_dare_delinquent_tax_and_two_year_always():
    """Same shape as enrichment_watauga_tax_search.py's own test: this fixture's parcel has
    exactly ONE delinquent year, so build_block()'s MIN_YEARS=2 gate correctly declines it --
    qualified stays 0, multi_year_delinquent_tax stays absent, but the fetch itself and the
    unconditional two_year_delinquent write both still happen."""
    li = Listing.model_construct(state="NC", county="Dare", parcel_id="004213001", raw={},
                                 listing_type=ListingType.UNKNOWN)
    html = (FIXTURES / "dare_taxcert_onedelinquent.html").read_text()
    stats = m.enrich_dare_tax_search([li], session=_FakeSession(html))
    assert stats == {"eligible": 1, "fetched": 1, "qualified": 0, "two_year_written": 1,
                     "fetch_errors": 0}
    assert li.raw[m.SRC_KEY]["bills"]
    assert m.RAW_KEY not in li.raw
    assert li.raw[m.TWO_YEAR_KEY]["is_two_year_plus"] is False


def test_enrich_skips_12digit_pin_rows_entirely():
    li = Listing.model_construct(state="NC", county="Dare", parcel_id="987309166326", raw={},
                                 listing_type=ListingType.UNKNOWN)
    html = (FIXTURES / "dare_taxcert_onedelinquent.html").read_text()
    stats = m.enrich_dare_tax_search([li], session=_FakeSession(html))
    assert stats["eligible"] == 0
    assert stats["fetched"] == 0
    assert m.SRC_KEY not in li.raw
