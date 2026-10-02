"""Column legal-notice API — probate/estate lane breadth extension (2026-10-02).

Closes part of the project-wide probate/heir-estate coverage gap (28/148 counties
had any probate signal before this): Column's estate/creditor-notice endpoint is
the SAME mechanism already built for NC_FOOTPRINT/SC_FOOTPRINT — "which county" is
just a query parameter on a single stateless API, so every NC/SC county outside
the existing footprint + DISTRESSED_ONLY lists was probed live (365-day window)
for real estate/probate notices. NC_ESTATE_EXTRA_COUNTIES (55) and
SC_PROBATE_EXTRA_COUNTIES (3) are the ones that came back with real hits — see
their own comments in column_legal_notices.py for the full probe methodology and
zero-hit list.

This only touches the estate/probate lane (fetch() steps 2/3). The foreclosure
lanes (steps 1/4) are untouched by design: these extra counties must never turn a
mortgage foreclosure into a flip lead outside the 18-county footprint.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

import foreclosure_scraper.scrapers.newspapers.column_legal_notices as m
from foreclosure_scraper.config import in_scope
from foreclosure_scraper.models import ListingType

NC_ESTATE_BODY = (
    "NOTICE TO CREDITORS NORTH CAROLINA, WAKE COUNTY File No: 26E001234-920 Having "
    "qualified as Executor of the Estate of John Q Public, deceased, this is to notify "
    "all persons having claims. This the 1st day of June, 2026. Jane R Public, Executor"
)
SC_PROBATE_BODY = (
    "NOTICE TO CREDITORS STATE OF SOUTH CAROLINA COUNTY OF DARLINGTON IN THE PROBATE "
    "COURT Estate: John Q Public Case Number: 2026-ES-16-00321 Date of Death: May 1, 2026 "
    "Personal Representative: Jane R Public Address: 123 Main St, Darlington, SC 29532"
)


def _item(text, county, id_, ntype, state="North Carolina"):
    return {"text": text, "county": county, "state": state, "noticetype": ntype,
            "newspapername": "The Test Paper", "publishedtimestamp": 1_784_073_600_000,
            "pdfurl": f"https://example.invalid/{id_}.pdf", "filer": "f", "id": id_}


def _scraper():
    return m.ColumnLegalNotices()


# --------------------------------------------------------------------------- the lists themselves

def test_extra_counties_are_disjoint_from_the_existing_footprint_and_distressed_only():
    nc_existing = set(m.NC_FOOTPRINT) | set(m.NC_DISTRESSED_ONLY)
    sc_existing = set(m.SC_FOOTPRINT) | set(m.SC_DISTRESSED_ONLY)
    assert not (set(m.NC_ESTATE_EXTRA_COUNTIES) & nc_existing)
    assert not (set(m.SC_PROBATE_EXTRA_COUNTIES) & sc_existing)
    # No internal dupes either.
    assert len(m.NC_ESTATE_EXTRA_COUNTIES) == len(set(m.NC_ESTATE_EXTRA_COUNTIES)) == 55
    assert len(m.SC_PROBATE_EXTRA_COUNTIES) == len(set(m.SC_PROBATE_EXTRA_COUNTIES)) == 3


def test_extra_counties_are_real_nc_sc_counties():
    """Every name must resolve against the real county lists, not a typo."""
    from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES
    for c in m.NC_ESTATE_EXTRA_COUNTIES:
        assert c in NC_COUNTIES, c
    for c in m.SC_PROBATE_EXTRA_COUNTIES:
        assert c in SC_COUNTIES, c


def test_mecklenburg_and_wake_are_outside_the_flip_footprint_but_in_the_extra_list():
    """These are classic DENIED-for-flip counties -- confirming the extension rides the
    DISTRESSED lane (no deny list), never the flip one."""
    assert "Wake" in m.NC_ESTATE_EXTRA_COUNTIES
    assert "Mecklenburg" in m.NC_ESTATE_EXTRA_COUNTIES
    assert not in_scope("Wake", "NC")
    assert not in_scope("Mecklenburg", "NC")
    assert "Greenville" in m.SC_PROBATE_EXTRA_COUNTIES
    assert not in_scope("Greenville", "SC")


def test_timeout_raised_for_the_added_query_volume():
    """58 more counties (55 NC x2 noticetypes + 3 SC) added ~113 sequential queries
    behind the shared per-host throttle; the old 240s ceiling left no margin."""
    assert m.ColumnLegalNotices.timeout_s >= 400.0


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
    # Shrink the pre-existing lanes to near-nothing so each test's assertions are
    # about the EXTRA counties specifically, not drowned in the full footprint.
    monkeypatch.setattr(m, "NC_FOOTPRINT", ())
    monkeypatch.setattr(m, "SC_FOOTPRINT", ())
    return table, calls


def test_estate_lane_queries_every_nc_extra_county_for_both_notice_types(canned):
    table, calls = canned
    asyncio.run(_scraper().fetch())
    asked = set(calls)
    for county in m.NC_ESTATE_EXTRA_COUNTIES:
        assert ("North Carolina", county, "Estate (Probate) Filings") in asked
        assert ("North Carolina", county, "Notice to Creditors") in asked
    # The foreclosure lane must NOT pick up the extra counties -- they ride the
    # estate/probate lane only.
    assert not any(k[0] == "North Carolina" and k[2] == "Foreclosure Sale" and k[1] in
                   m.NC_ESTATE_EXTRA_COUNTIES for k in asked)


def test_probate_lane_queries_every_sc_extra_county(canned):
    table, calls = canned
    asyncio.run(_scraper().fetch())
    asked = set(calls)
    for county in m.SC_PROBATE_EXTRA_COUNTIES:
        assert ("South Carolina", county, "Estate (Probate) Filings") in asked


def test_a_real_wake_estate_notice_becomes_a_probate_notice_lead(canned):
    table, _ = canned
    table[("North Carolina", "Wake", "Estate (Probate) Filings")] = [
        _item(NC_ESTATE_BODY, "Wake", "w1-0", "Estate (Probate) Filings")]
    out = asyncio.run(_scraper().fetch())
    rows = [li for li in out if li.county == "Wake"]
    assert len(rows) == 1
    assert rows[0].listing_type == ListingType.PROBATE_NOTICE
    assert rows[0].owner_name == "John Q Public"
    assert rows[0].state == "NC"


def test_a_real_darlington_probate_notice_becomes_a_probate_notice_lead(canned):
    table, _ = canned
    table[("South Carolina", "Darlington", "Estate (Probate) Filings")] = [
        _item(SC_PROBATE_BODY, "Darlington", "d1-0", "Estate (Probate) Filings",
              state="South Carolina")]
    out = asyncio.run(_scraper().fetch())
    rows = [li for li in out if li.listing_type == ListingType.PROBATE_NOTICE
            and li.state == "SC"]
    assert len(rows) == 1
    assert rows[0].owner_name == "John Q Public"
    assert rows[0].county == "Darlington"


def test_partial_is_populated_for_soft_timeout_salvage(canned):
    """`out` must be `self.partial` (not a throwaway local list), or a soft-timeout
    mid-run would silently discard every row already fetched -- the exact bug class
    sc_probate_notices.py and qpaybill_delinquent_roll.py already document fixing."""
    table, _ = canned
    table[("North Carolina", "Wake", "Estate (Probate) Filings")] = [
        _item(NC_ESTATE_BODY, "Wake", "w1-0", "Estate (Probate) Filings")]
    s = _scraper()
    out = asyncio.run(s.fetch())
    assert len(s.partial) >= len(out) > 0
    assert any(li.county == "Wake" for li in s.partial)
