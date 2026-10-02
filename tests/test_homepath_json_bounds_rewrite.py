"""national.homepath_json: 2026-10-01 national/reo per-source extraction audit.

This module's original premise was confirmed false, live, two ways:
1. The documented ``.../search-listings`` endpoint returns HTTP 404.
2. The endpoint it actually called (``.../search`` with state/zipcode/page,
   no ``bounds``) silently IGNORES all of those params and returns the same
   fixed, unfiltered ~400-row nationwide slice on every page -- confirmed by
   identical propertyUuids across pages 1/2/3. Real output was 22 near-random
   rows per run instead of a genuine state-wide sweep.

Rewritten to use the same ``bounds``-based query fannie_homepath.py's bbox
scraper uses (confirmed live: with ``bounds`` present, ``page`` genuinely
paginates distinct results), walking each state's FULL bbox for pagination
DEPTH rather than the sibling's grid-of-single-pages. Live-verified
2026-10-01: 2,927 real NC+SC rows (was 22), each an independently correct
state total (NC 655 + SC 2272 = 2927 exactly, proving fetch() no longer
double-counts after adding self.partial salvage).

case_number was also changed from "homepath-json-{uuid}" to "fannie-{uuid}"
to match fannie_homepath.py, so an overlapping property actually collides
and dedupes on the board as this module's own docstring always claimed it
would (it never could with mismatched id schemes).
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.national import homepath_json as m


def _prop(uuid: str, state: str = "NC", street: str = "1 Test St") -> dict:
    return {
        "propertyUuid": uuid,
        "addressLine1": street,
        "city": "Asheville",
        "state": state,
        "zipCode": "28801",
        "county": "BUNCOMBE COUNTY",
        "propertyType": "Single Family",
        "price": 100000,
        "geoPoint": {"latitude": 35.5, "longitude": -82.5},
    }


def test_case_number_uses_the_fannie_prefix_matching_the_sibling_scraper():
    li = m._to_listing(_prop("abc-123"), m.HomePathJSON.slug)
    assert li is not None
    assert li.case_number == "fannie-abc-123"


def test_fetch_state_sends_bounds_not_state_zipcode(monkeypatch):
    """The confirmed-broken call shape used state/zipcode/page with no
    bounds; the fix must query with bounds (the only param confirmed live to
    actually filter) and must NOT regress back to the dead shape."""
    seen_params = []

    class _FakeResp:
        status_code = 200

        def json(self):
            # First page returns one real row, second page empty -> stop.
            if not seen_params or len(seen_params) == 1:
                return {"properties": [_prop("only-row")]}
            return {"properties": []}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, follow_redirects=True):
            seen_params.append(params)
            return _FakeResp()

    monkeypatch.setattr(m, "client", lambda timeout=30.0: _FakeClient())

    out = asyncio.run(m._fetch_state("NC", "national.homepath_json"))

    assert len(out) == 1
    assert out[0].case_number == "fannie-only-row"
    assert seen_params, "must have made at least one request"
    for p in seen_params:
        assert "bounds" in p, f"bounds param must always be present, got {p}"
        assert p["bounds"] == "33.75,-84.5,36.6,-75.3"
        # The old, confirmed-broken shape must not reappear.
        assert "state" not in p
        assert "zipcode" not in p


def test_fetch_does_not_double_count_rows_from_partial_sink_plus_extend(monkeypatch):
    """Regression guard for the exact bug introduced and caught mid-fix today:
    wiring self.partial as the partial_sink AND still doing out.extend(result)
    after gather() would double every row. fetch() must return exactly what
    each state produced, once."""

    async def fake_fetch_state(state, slug, partial_sink=None):
        rows = [m._to_listing(_prop(f"{state}-1", state=state), slug)]
        if partial_sink is not None:
            partial_sink.extend(rows)
        return rows

    monkeypatch.setattr(m, "_fetch_state", fake_fetch_state)

    scraper = m.HomePathJSON()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(out) == len(m.STATES), (
        f"expected exactly one row per state ({len(m.STATES)}), got {len(out)} "
        "-- a count double len(STATES) means the partial_sink + extend double-count bug is back")
    assert {li.case_number for li in out} == {f"fannie-{s}-1" for s in m.STATES}
    # self.partial must mirror the returned rows exactly (same salvage
    # contract as fannie_homepath.py's own proven pattern).
    assert {li.case_number for li in scraper.partial} == {li.case_number for li in out}
    assert len(scraper.partial) == len(out)


def test_safe_run_salvages_a_state_that_already_finished_when_the_other_hangs(monkeypatch):
    """End-to-end through safe_run(): one state's pagination hangs past
    timeout_s, the other already finished -- its rows must be salvaged as
    PARTIAL, not discarded, same contract as fannie_homepath.py's cells."""

    async def fake_fetch_state(state, slug, partial_sink=None):
        if state == "SC":
            await asyncio.sleep(3600.0)
            return []
        rows = [m._to_listing(_prop("NC-1", state="NC"), slug)]
        if partial_sink is not None:
            partial_sink.extend(rows)
        return rows

    monkeypatch.setattr(m, "_fetch_state", fake_fetch_state)

    scraper = m.HomePathJSON()
    scraper.timeout_s = 0.2
    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected NC's row to be salvaged as PARTIAL while SC hung, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r})")
    assert len(out) == 1
    assert out[0].case_number == "fannie-NC-1"
