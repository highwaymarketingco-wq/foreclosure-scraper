"""Column legal-notice API -- SC probate/estate lane, 3rd stale_scope re-probe (2026-11-16).

gap_matrix's stale_scope bucket (section 4) flagged 54 cells / 308,052 est_rows with the
reason "Column's SC estate lane only queries 19 of 46 counties per run" across
heir_naming_publication and quiet_title, led by York (81,350) and Lexington (31,402). A
live re-probe (3rd pass; 2026-10-02 and 2026-10-23 already ran this same check) found:

  - 25 of the 27 previously-missing counties, York and Lexington included, are a genuine
    true negative: Column's own `total_results` is 0 even over a 10-year lookback, for
    every county-name variant tried. No county-list edit can fix that -- it was already
    correctly scoped, not stale. These tests do NOT claim otherwise.

  - 2 of the 27 (Orangeburg, Calhoun) DO have real, recoverable notices -- not because
    their own county name was missing from a list, but because Column tags them under a
    combined NEWSPAPER-COVERAGE-REGION string ("Orangeburg, Bamberg and Calhoun"), the
    exact same quirk already documented for the SC foreclosure lane (step 4 of fetch()),
    just never extended to the probate/estate lane (step 3) before now. Bamberg -- the
    tag's 3rd nominal member -- had zero real notices of its own in a 5-year sample and
    stays a true negative too (SC_PROBATE_COVERED_COUNTIES deliberately excludes it).

See SC_PROBATE_REGION_TAGS's own comment in column_legal_notices.py for the full
live-probe evidence (353 notices / 5 years, 126 / 365 days, text-resolved 353/353).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

import foreclosure_scraper.scrapers.newspapers.column_legal_notices as m
from foreclosure_scraper.models import ListingType

REGION_TAG = "Orangeburg, Bamberg and Calhoun"

SC_NOTICE_TO_CREDITORS_ORANGEBURG = (
    "NOTICE TO CREDITORS All persons having claims against the following estates are "
    "required to deliver or mail their claims to the indicated Personal Representative(s) "
    "appointed to administer these estates, and to file their claims on form 371PC with the "
    "Probate Court of Orangeburg County, Post Office Box 9000. Estate: Jane Q Public "
    "Case Number: 2026-ES-38-00123 Personal Representative: John R Public"
)
SC_PROBATE_CALHOUN = (
    "NOTICE TO CREDITORS STATE OF SOUTH CAROLINA COUNTY OF CALHOUN IN THE PROBATE COURT "
    "Estate: Mary L Public Case Number: 2026-ES-09-00045 Date of Death: March 1, 2026 "
    "Personal Representative: Sam T Public"
)
SC_QUIET_TITLE_WILLIAMSBURG = (
    "STATE OF SOUTH CAROLINA IN THE PROBATE COURT COUNTY OF ORANGEBURG CASE NO. "
    "2026-CP-38-00987 SUMMONS AND NOTICE TO quiet tax title as to the real property known "
    "as 123 Main St, Williamsburg County, South Carolina, against the Heirs-at-Law of "
    "Jane Doe Deceased or by any such designation; John Doe and Mary Roe Defendants."
)
SC_NO_COUNTY_MARKER = "NOTICE TO CREDITORS this body carries no county marker at all."


def _item(text, county, id_, ntype="Estate (Probate) Filings", state="South Carolina"):
    return {"text": text, "county": county, "state": state, "noticetype": ntype,
            "newspapername": "The Test Paper", "publishedtimestamp": 1_784_073_600_000,
            "pdfurl": f"https://example.invalid/{id_}.pdf", "filer": "f", "id": id_}


def _scraper():
    return m.ColumnLegalNotices()


# --------------------------------------------------------------------------- the constants

def test_region_tags_members_are_real_sc_counties_not_typos():
    from foreclosure_scraper.validation import SC_COUNTIES
    for tag, members in m.SC_PROBATE_REGION_TAGS.items():
        assert isinstance(tag, str) and tag
        for county in members:
            assert county in SC_COUNTIES, county


def test_covered_counties_are_a_subset_of_region_tag_members():
    """SC_PROBATE_COVERED_COUNTIES only lists members with VERIFIED real notices (Bamberg,
    a nominal member of the Orangeburg tag, had zero of its own in the 5-year probe and
    must stay out -- never claim coverage the live data didn't back up)."""
    all_members = {c for members in m.SC_PROBATE_REGION_TAGS.values() for c in members}
    assert set(m.SC_PROBATE_COVERED_COUNTIES) <= all_members
    assert "Bamberg" in all_members
    assert "Bamberg" not in m.SC_PROBATE_COVERED_COUNTIES
    assert "Orangeburg" in m.SC_PROBATE_COVERED_COUNTIES
    assert "Calhoun" in m.SC_PROBATE_COVERED_COUNTIES


def test_covered_counties_are_disjoint_from_the_existing_active_set():
    existing = set(m.SC_FOOTPRINT) | set(m.SC_DISTRESSED_ONLY) | set(m.SC_PROBATE_EXTRA_COUNTIES)
    assert not (set(m.SC_PROBATE_COVERED_COUNTIES) & existing)


def test_york_and_lexington_are_not_claimed_as_covered_by_anything():
    """The two biggest stale_scope rows stay a genuine true negative -- this fix must never
    quietly claim York/Lexington coverage it doesn't have."""
    all_members = {c for members in m.SC_PROBATE_REGION_TAGS.values() for c in members}
    assert "York" not in all_members
    assert "Lexington" not in all_members
    assert "York" not in m.SC_PROBATE_COVERED_COUNTIES
    assert "Lexington" not in m.SC_PROBATE_COVERED_COUNTIES


# --------------------------------------------------------------------------- _sc_estate_county

@pytest.mark.parametrize("text,fallback,expected", [
    (SC_NOTICE_TO_CREDITORS_ORANGEBURG, REGION_TAG, "Orangeburg"),
    (SC_PROBATE_CALHOUN, REGION_TAG, "Calhoun"),
    (SC_QUIET_TITLE_WILLIAMSBURG, REGION_TAG, "Williamsburg"),
    (SC_NO_COUNTY_MARKER, REGION_TAG, REGION_TAG),  # best-effort fallback, never a guess
])
def test_sc_estate_county_resolves_the_real_county_from_the_notice_body(text, fallback, expected):
    assert m._sc_estate_county(text, fallback) == expected


def test_sc_estate_county_prefers_the_quiet_title_property_address_pattern():
    """When a notice is BOTH a quiet-title suit (property address pattern) and happens to
    mention another county in the caption, the property's own county wins -- it is the
    more specific, more correct signal for heir_naming_publication/quiet_title specifically."""
    text = (SC_QUIET_TITLE_WILLIAMSBURG)  # caption says "COUNTY OF ORANGEBURG", property is Williamsburg
    assert "COUNTY OF ORANGEBURG" in text
    assert m._sc_estate_county(text, REGION_TAG) == "Williamsburg"


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
    monkeypatch.setattr(m, "NC_FOOTPRINT", ())
    monkeypatch.setattr(m, "SC_FOOTPRINT", ())
    monkeypatch.setattr(m, "SC_DISTRESSED_ONLY", ())
    monkeypatch.setattr(m, "SC_PROBATE_EXTRA_COUNTIES", ())
    return table, calls


def test_fetch_queries_every_region_tag_literally(canned):
    table, calls = canned
    asyncio.run(_scraper().fetch())
    asked = set(calls)
    for tag in m.SC_PROBATE_REGION_TAGS:
        assert ("South Carolina", tag, "Estate (Probate) Filings") in asked


def test_a_real_orangeburg_notice_under_the_region_tag_becomes_a_correctly_countied_lead(canned):
    table, _ = canned
    table[("South Carolina", REGION_TAG, "Estate (Probate) Filings")] = [
        _item(SC_NOTICE_TO_CREDITORS_ORANGEBURG, REGION_TAG, "ob1-0"),
        _item(SC_PROBATE_CALHOUN, REGION_TAG, "ob2-0"),
    ]
    out = asyncio.run(_scraper().fetch())
    rows = [li for li in out if li.listing_type == ListingType.PROBATE_NOTICE]
    assert len(rows) == 2
    counties = sorted(li.county for li in rows)
    assert counties == ["Calhoun", "Orangeburg"]
    # Never the raw compound tag string on a resolved row.
    assert all(li.county != REGION_TAG for li in rows)


def test_a_quiet_title_notice_under_the_region_tag_gets_the_property_county_and_signal(canned):
    table, _ = canned
    table[("South Carolina", REGION_TAG, "Estate (Probate) Filings")] = [
        _item(SC_QUIET_TITLE_WILLIAMSBURG, REGION_TAG, "wb1-0"),
    ]
    out = asyncio.run(_scraper().fetch())
    rows = [li for li in out if li.listing_type == ListingType.PROBATE_NOTICE]
    assert len(rows) == 1
    assert rows[0].county == "Williamsburg"
    assert rows[0].raw.get("heir_naming_publication")


def test_unresolvable_region_tag_notice_falls_back_to_the_raw_tag_not_a_guess(canned):
    table, _ = canned
    table[("South Carolina", REGION_TAG, "Estate (Probate) Filings")] = [
        _item(SC_NO_COUNTY_MARKER, REGION_TAG, "nc1-0"),
    ]
    out = asyncio.run(_scraper().fetch())
    rows = [li for li in out if li.listing_type == ListingType.PROBATE_NOTICE]
    assert len(rows) == 1
    assert rows[0].county == REGION_TAG


def test_partial_is_populated_for_the_region_tag_lane_too(canned):
    """Same soft-timeout salvage guarantee as every other lane in this scraper (`out` must
    be `self.partial`, not a throwaway local list)."""
    table, _ = canned
    table[("South Carolina", REGION_TAG, "Estate (Probate) Filings")] = [
        _item(SC_NOTICE_TO_CREDITORS_ORANGEBURG, REGION_TAG, "ob1-0"),
    ]
    s = _scraper()
    out = asyncio.run(s.fetch())
    assert len(s.partial) >= len(out) > 0
    assert any(li.county == "Orangeburg" for li in s.partial)
