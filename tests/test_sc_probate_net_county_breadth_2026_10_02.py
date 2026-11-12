"""counties_sc.sc_probate_net — county-list breadth extension (2026-10-02).

southcarolinaprobate.net is a SHARED aggregator: its county dropdown lists every
court that participates, statewide (verified live by reading the real
``ddlCounties`` <select>: Aiken, Bamberg, Barnwell, Charleston, Cherokee,
Chester, Colleton, Dorchester, Florence, Georgetown, Kershaw, Lancaster,
Marlboro, Oconee, Orangeburg, Sumter, York) -- COUNTIES only wired 5 of them.
Every one NOT already in COUNTIES was probed live with a single "Smith" search:
Dorchester Probate returned 20 real hits, York Probate returned 3; the other 10
(Aiken, Bamberg, Barnwell, Chester, Kershaw, Lancaster, Orangeburg, Sumter,
Florence, Marlboro) came back "no records", same shape as the already-wired
Colleton/Georgetown/Oconee/Cherokee -- those courts simply don't feed this
aggregator, so they are correctly NOT added.
"""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.scrapers.counties_sc.sc_probate_net as m
from foreclosure_scraper.config import in_scope
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def test_dorchester_and_york_are_in_counties_with_both_probate_and_marriage_variants():
    entries = {(dv, county, marriage) for dv, county, _state, marriage in m.COUNTIES}
    assert ("Dorchester Probate", "Dorchester", False) in entries
    assert ("Dorchester Marriage", "Dorchester", True) in entries
    assert ("York Probate", "York", False) in entries
    assert ("York Marriage", "York", True) in entries


def test_no_duplicate_dropdown_values():
    values = [dv for dv, *_ in m.COUNTIES]
    assert len(values) == len(set(values))


def test_dorchester_and_york_are_outside_the_flip_footprint_but_included_anyway():
    """PROBATE_NOTICE is a distressed-type lead, not a flip -- see
    config.in_scope_distressed / main._county_in_scope. Confirms this extension
    rides that lane deliberately, the same way column_legal_notices.py's
    DISTRESSED_ONLY / EXTRA_COUNTIES lists already do."""
    assert not in_scope("Dorchester", "SC")
    assert not in_scope("York", "SC")
    assert any(c == "Dorchester" for _, c, _, _ in m.COUNTIES)
    assert any(c == "York" for _, c, _, _ in m.COUNTIES)


def test_legit_empty_candidates_were_not_added():
    """These 10 were probed live and returned 'no records' -- must stay absent
    unless a future re-check finds the court now publishing."""
    values = {dv for dv, *_ in m.COUNTIES}
    for absent in ("Aiken", "Bamberg", "Barnwell", "Chester", "Kershaw",
                   "Lancaster", "Orangeburg", "Sumter"):
        assert absent not in values


# --------------------------------------------------------------------------- fetch()-level

@pytest.fixture
def canned(monkeypatch):
    """Drive fetch() offline: `_search_county` answers from a table keyed by
    (dropdown_value, surname)."""
    table: dict[tuple[str, str], list[Listing]] = {}
    calls: list[tuple[str, str]] = []

    async def fake_search_county(client, dropdown_value, county, state, marriage, surname):
        calls.append((dropdown_value, surname))
        return list(table.get((dropdown_value, surname), []))

    monkeypatch.setattr(m, "_search_county", fake_search_county)
    # Skip the real 1s politeness sleep between surnames so the test is instant.
    # Captures the REAL asyncio.sleep before patching so the replacement doesn't
    # recursively call itself through the module attribute it just replaced.
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(m.asyncio, "sleep", lambda *_a, **_k: _real_sleep(0))
    return table, calls


def _probate_listing(case_number: str, decedent: str, county: str) -> Listing:
    return Listing(
        source=m.SCProbateNet.slug, source_url=m.BASE_URL,
        listing_type=ListingType.PROBATE_NOTICE, property_kind=PropertyKind.UNKNOWN,
        state="SC", county=county, owner_name=decedent, defendant=decedent,
        case_number=case_number, description=f"SC probate estate {case_number}",
        raw={"sc_probate_net": {"record_kind": "probate"}},
    )


def test_dorchester_and_york_are_queried_with_every_surname(canned):
    table, calls = canned
    asyncio.run(m.SCProbateNet().fetch())
    asked = set(calls)
    for surname in m.SURNAMES:
        assert ("Dorchester Probate", surname) in asked
        assert ("York Probate", surname) in asked


def test_a_real_dorchester_hit_becomes_a_probate_notice_lead(canned):
    table, _ = canned
    table[("Dorchester Probate", "Smith")] = [
        _probate_listing("2026ES1800123", "ALEXANDER, RICHARD BARTON", "Dorchester")]
    out = asyncio.run(m.SCProbateNet().fetch())
    rows = [li for li in out if li.county == "Dorchester"]
    assert len(rows) == 1
    assert rows[0].listing_type == ListingType.PROBATE_NOTICE
    assert rows[0].owner_name == "ALEXANDER, RICHARD BARTON"
