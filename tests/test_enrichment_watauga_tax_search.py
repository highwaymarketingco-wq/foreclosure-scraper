"""enrichment_watauga_tax_search.py's pure parsing against real captured responses (2026-11-28,
tests/fixtures/watauga_tax_search_*.html). See that module's docstring for the live site shape."""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper import enrichment_watauga_tax_search as m
from foreclosure_scraper.models import Listing, ListingType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_a_real_multiyear_result():
    html = (FIXTURES / "watauga_tax_search_multiyear.html").read_text()
    bills = m._parse_bills(html)
    by_year = {b["year"]: b for b in bills}
    assert set(by_year) == {2022, 2023, 2024, 2025, 2026}
    assert by_year[2026] == {"year": 2026, "status": "unpaid", "total_due": 5374.82}
    for y in (2022, 2023, 2024, 2025):
        assert by_year[y] == {"year": y, "status": "paid", "total_due": None}


def test_parses_no_record_found_as_empty():
    html = (FIXTURES / "watauga_tax_search_noresults.html").read_text()
    assert m._parse_bills(html) == []


def test_eligible_requires_nc_watauga_with_board_shaped_parcel_id():
    good = Listing.model_construct(state="NC", county="Watauga", parcel_id="2848-99-0061-000",
                                   raw={})
    assert m._eligible(good)

    wrong_state = Listing.model_construct(state="SC", county="Watauga",
                                          parcel_id="2848-99-0061-000", raw={})
    assert not m._eligible(wrong_state)

    wrong_county = Listing.model_construct(state="NC", county="Ashe",
                                            parcel_id="2848-99-0061-000", raw={})
    assert not m._eligible(wrong_county)

    no_parcel = Listing.model_construct(state="NC", county="Watauga", parcel_id=None, raw={})
    assert not m._eligible(no_parcel)

    wrong_shape = Listing.model_construct(state="NC", county="Watauga", parcel_id="123456",
                                          raw={})
    assert not m._eligible(wrong_shape)

    already_done = Listing.model_construct(
        state="NC", county="Watauga", parcel_id="2848-99-0061-000",
        raw={"watauga_delinquent_tax": {"bills": []}})
    assert not m._eligible(already_done)


class _FakeSession:
    """Returns the multi-year fixture for the GET, and the same fixture again for the POST --
    enough to exercise enrich_watauga_tax_search() end to end without a real network call."""

    def __init__(self, html: str):
        self._html = html

    def get(self, *a, **k):
        return _FakeResp(self._html)

    def post(self, *a, **k):
        return _FakeResp(self._html)


class _FakeResp:
    def __init__(self, text: str):
        self.text = text


def test_enrich_writes_watauga_delinquent_tax_and_two_year_always():
    """This fixture's parcel has exactly ONE delinquent year on file (2026, $5,374.82) --
    enrich_watauga_tax_search() must still fetch and record it (raw['watauga_delinquent_tax']),
    and build_two_year_block() writes unconditionally either way, but build_block()'s own
    MIN_YEARS=2 gate (shared, unmodified, with ustaxdata's module) must correctly DECLINE to
    call one bad year "multi-year delinquent" -- qualified stays 0, raw['multi_year_delinquent_
    tax'] stays absent. (A parcel with 2+ delinquent years would need a second captured
    fixture to test the qualifying path; not chased further this round since the gate itself is
    ustaxdata's own already-tested code, not new logic this module adds.)"""
    li = Listing.model_construct(state="NC", county="Watauga", parcel_id="2848-99-0061-000",
                                 raw={}, listing_type=ListingType.UNKNOWN)
    html = (FIXTURES / "watauga_tax_search_multiyear.html").read_text()
    stats = m.enrich_watauga_tax_search([li], session=_FakeSession(html))
    assert stats == {"eligible": 1, "fetched": 1, "qualified": 0, "two_year_written": 1,
                     "fetch_errors": 0}
    assert li.raw[m.SRC_KEY]["bills"]
    assert m.RAW_KEY not in li.raw
    assert li.raw[m.TWO_YEAR_KEY]["is_two_year_plus"] is False


def test_enrich_respects_max_rows():
    html = (FIXTURES / "watauga_tax_search_multiyear.html").read_text()
    rows = [Listing.model_construct(state="NC", county="Watauga",
                                    parcel_id=f"2848-99-0061-{i:03d}", raw={},
                                    listing_type=ListingType.UNKNOWN) for i in range(5)]
    stats = m.enrich_watauga_tax_search(rows, session=_FakeSession(html), max_rows=2)
    assert stats["fetched"] == 2
    assert stats["eligible"] == 3  # the loop still counts eligibility before the max_rows cutoff
