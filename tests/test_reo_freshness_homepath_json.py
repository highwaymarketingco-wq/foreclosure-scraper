"""enrichment_reo_freshness: national.homepath_json is a snapshot-REO source (audit 2026-10-09).
Since aef7c291 it asks HomePath for Fannie Mae REO only, so retail rows it published earlier
are absent from the fresh pull and must be pruned. Made-up rows, no network."""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.main as main_mod
from foreclosure_scraper import enrichment_reo_freshness as mod
from foreclosure_scraper.models import Listing, ListingType

SLUG = "national.homepath_json"


class _Fake:
    def __init__(self, slug, rows):
        self.slug = slug
        self._rows = rows

    async def safe_run(self):
        return list(self._rows)


def _row(addr, uuid):
    return Listing(source=SLUG, source_url=f"https://homepath.fanniemae.com/property/{uuid}",
                   case_number=f"fannie-{uuid}", listing_type=ListingType.REO, state="NC",
                   county="Sampleton", street_address=addr, opening_bid=100_000.0)


@pytest.fixture(autouse=True)
def _scope(monkeypatch):
    monkeypatch.setattr(main_mod, "_in_scope", lambda li: True)


def test_homepath_json_is_a_snapshot_source():
    assert SLUG in mod.SNAPSHOT_REO_SOURCES
    assert "national.fannie_homepath" in mod.SNAPSHOT_REO_SOURCES


def test_a_retail_row_absent_from_the_reo_only_pull_is_pruned(monkeypatch):
    reo = _row("10 Example Rd", "reo-1")
    retail = _row("20 Sample Ln", "retail-1")      # published before the REO-only filter
    fresh = [_row("10 Example Road", "reo-1b")]    # the REO-only pull: same house, rotated uuid
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_Fake(SLUG, fresh)])
    kept, stats = asyncio.run(mod.prune_stale_reo([reo, retail]))
    addrs = sorted(li.street_address for li in kept)
    assert addrs == ["10 Example Rd"]
    assert kept[0].source_url.endswith("reo-1b")


def test_an_empty_pull_prunes_nothing(monkeypatch):
    rows = [_row("10 Example Rd", "reo-1"), _row("20 Sample Ln", "retail-1")]
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_Fake(SLUG, [])])
    kept, _ = asyncio.run(mod.prune_stale_reo(rows))
    assert len(kept) == 2
