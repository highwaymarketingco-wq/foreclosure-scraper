"""Greenville SC Master-in-Equity scraper — recovery regression.

This source was deleted 2026-05-04 ("flawless v1" commit) when it broke,
and re-discovered 2026-06-16 during the source-inventory audit. Greenville
is the largest SC county and had NO foreclosure-sale coverage in its
absence. Recovered + hardened:
  - TMS column-drift guard (some rows put an attorney name where the TMS
    belongs; reject anything not TMS-shaped)
  - situs extraction from the result/notes cell

Network test (hits the live county roster) — RUN_NETWORK_TESTS=1 to enable.
Pure-parse assertions below run always.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_sc.greenville_master_in_equity import (
    GreenvilleMasterInEquity,
    _GREENVILLE_ADDR_RE,
)


# ---- pure-parse unit tests (always run) ----

def test_addr_re_extracts_situs_from_notes():
    notes = "Completed-05/29/2026 Sale # 1 161 Catnip Trail, Landrum"
    m = _GREENVILLE_ADDR_RE.search(notes)
    assert m, "should extract address from result notes"
    assert "161 Catnip Trail" in m.group(1)


def test_addr_re_ignores_no_address_notes():
    assert _GREENVILLE_ADDR_RE.search("Completed-05/29/2026 Sale # 1") is None


def test_scraper_is_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.greenville_master_in_equity" in slugs


# ---- live network test ----

@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live Greenville county roster — set RUN_NETWORK_TESTS=1",
)
def test_greenville_live_returns_foreclosures():
    out = list(asyncio.run(GreenvilleMasterInEquity().fetch()))
    assert len(out) >= 5, f"expected >=5 Greenville foreclosures, got {len(out)}"

    # No attorney-name leaks into parcel_id (the column-drift bug).
    name_leaks = [li for li in out if li.parcel_id and not li.parcel_id[0].isdigit()]
    assert not name_leaks, f"parcel_id has non-TMS values: {[li.parcel_id for li in name_leaks[:3]]}"

    # Every listing is a Greenville SC foreclosure with a case number.
    for li in out:
        assert li.state == "SC"
        assert li.county == "Greenville"
        assert li.case_number, "foreclosure row missing case_number"
