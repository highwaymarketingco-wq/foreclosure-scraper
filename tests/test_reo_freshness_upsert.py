"""enrichment_reo_freshness.prune_stale_reo must LAND the fresh pull it already
fetched, not only use it to decide what to prune.

MEASURED 2026-09-23 (docs/full_run_execution_audit_2026-09-23.md, section
"fannie_homepath fix -- did it behave as expected?"): the 2026-09-23 run's
freshness-prune step re-invoked national.fannie_homepath directly (08:07:46Z,
~17h after the main scrape phase's own attempt at the same scraper timed out)
and it succeeded cleanly -- 8,244 rows, matching Fannie Mae's live REO
inventory (`reo_freshness.live slug=national.fannie_homepath live=8244`). That
fetch was used ONLY to prune 24 stale carryover rows
(`reo_freshness.done pruned={'national.fannie_homepath': 24}`); none of the
8,244 fresh rows were landed as new/updated board listings. The final board
carried only 124 national.fannie_homepath rows -- 1.5% of the verified-live
8,244 -- even though every one of those 8,244 properties had just been proven
live and reachable in the same run. The fetch was never the gap; discarding
its results was.

These tests exercise the fix directly against prune_stale_reo() (this module's
only public entry point), with a fake scraper standing in for the real network
call -- the real fannie_homepath.py scrape behavior has its own coverage in
tests/test_fannie_homepath_timeout.py and
tests/test_fannie_homepath_partial_salvage.py.
"""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.main as main_mod
from foreclosure_scraper import enrichment_reo_freshness as mod
from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo
from foreclosure_scraper.models import Listing, ListingType

SLUG = "national.fannie_homepath"


class _FakeScraper:
    """Stands in for FannieHomePath: no HTTP, just a fixed fresh-pull result --
    exercises prune_stale_reo()'s own match/upsert/prune logic, not the
    scraper's JSON parsing."""

    def __init__(self, slug: str, rows: list[Listing]):
        self.slug = slug
        self._rows = rows

    async def safe_run(self) -> list[Listing]:
        return list(self._rows)


class _FailingScraper:
    slug = SLUG

    async def safe_run(self) -> list[Listing]:
        raise RuntimeError("boom")


def _board_row(addr="123 Main St", state="NC", county="Rutherford", uuid="old-uuid",
                raw=None) -> Listing:
    return Listing(
        source=SLUG,
        source_url=f"https://homepath.fanniemae.com/property/{uuid}",
        case_number=f"fannie-{uuid}",
        listing_type=ListingType.REO,
        state=state,
        county=county,
        street_address=addr,
        opening_bid=100_000.0,
        raw=raw or {},
    )


def _fresh_row(addr="123 Main Street", state="NC", county="Rutherford", uuid="new-uuid",
               opening_bid=95_000.0) -> Listing:
    return Listing(
        source=SLUG,
        source_url=f"https://homepath.fanniemae.com/property/{uuid}",
        case_number=f"fannie-{uuid}",
        listing_type=ListingType.REO,
        state=state,
        county=county,
        street_address=addr,
        opening_bid=opening_bid,
    )


@pytest.fixture(autouse=True)
def _patch_in_scope(monkeypatch):
    """prune_stale_reo() lazily imports `_in_scope` from `.main` the first time
    it needs to gate a genuinely-new row. Default every test to admitting
    everything; individual tests override this to prove the gate is real."""
    monkeypatch.setattr(main_mod, "_in_scope", lambda li: True)
    yield


def test_matched_fresh_row_refreshes_volatile_fields_and_preserves_enrichment(monkeypatch):
    """The core bug: a fresh row for a property ALREADY on the board (matched
    by normalized street address + state, not the rotating uuid-bearing
    source_url/case_number) must refresh source_url/case_number/opening_bid/
    last_seen on the EXISTING row -- and must not touch its prior enrichment
    (vision/comps/grade live in .raw) or create a duplicate row."""
    existing = _board_row(addr="123 Main St", uuid="old-uuid",
                           raw={"vision": {"roof": "ok"}, "grade": {"tier": "WARM"}})
    fresh = _fresh_row(addr="123 Main Street", uuid="new-uuid", opening_bid=88_000.0)
    # "Main St" vs "Main Street" prove the match is address-based, not string-exact.

    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(SLUG, [fresh])])

    kept, stats = asyncio.run(prune_stale_reo([existing]))

    assert len(kept) == 1, "a matched fresh row must UPDATE the existing row, not add a second one"
    row = kept[0]
    assert row is existing, "the same board object must be updated in place"
    assert row.source_url.endswith("new-uuid")
    assert row.case_number == "fannie-new-uuid"
    assert row.opening_bid == 88_000.0
    assert row.raw == {"vision": {"roof": "ok"}, "grade": {"tier": "WARM"}}, (
        "prior enrichment must survive a volatile-field refresh untouched")
    assert stats["landed"]["matched"] == 1
    assert stats["landed"]["added"] == 0


def test_new_fresh_row_with_no_board_match_is_added_when_in_scope(monkeypatch):
    """This is the actual coverage-gap fix: a fresh row with NO existing board
    twin (the 8,220 discarded rows in the 2026-09-23 run) must be LANDED as a
    new listing, not merely used to decide what to prune."""
    fresh = _fresh_row(addr="456 New Ave", uuid="brand-new")
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(SLUG, [fresh])])

    kept, stats = asyncio.run(prune_stale_reo([]))

    assert len(kept) == 1
    assert kept[0].case_number == "fannie-brand-new"
    assert stats["landed"]["added"] == 1
    assert stats["landed"]["matched"] == 0


def test_new_fresh_row_out_of_scope_is_not_added(monkeypatch):
    """A late-pipeline add must go through the SAME in-scope gate the main
    scrape phase applies to every national.* row, so this step can't
    reintroduce out-of-footprint noise the earlier pipeline stages would have
    filtered."""
    monkeypatch.setattr(main_mod, "_in_scope", lambda li: False)
    fresh = _fresh_row(addr="1 Nowhere Rd", uuid="out-of-scope-uuid")
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(SLUG, [fresh])])

    kept, stats = asyncio.run(prune_stale_reo([]))

    assert kept == []
    assert stats["landed"]["added"] == 0
    assert stats["landed"]["skipped_out_of_scope"] == 1


def test_stale_row_with_no_fresh_match_is_still_pruned(monkeypatch):
    """The pre-existing prune behavior must be unaffected by the upsert
    addition: a carried-over row whose URL is no longer in the live set is
    still dropped, even though it has no address match in the fresh pull
    either (e.g. the property sold and its address left inventory too)."""
    stale = _board_row(addr="999 Sold St", uuid="sold-uuid")
    fresh = _fresh_row(addr="456 New Ave", uuid="brand-new")
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(SLUG, [fresh])])

    kept, stats = asyncio.run(prune_stale_reo([stale]))

    kept_uuids = {li.case_number for li in kept}
    assert "fannie-sold-uuid" not in kept_uuids
    assert stats["by_source"].get(SLUG) == 1
    assert stats["pruned"] == 1


def test_empty_fresh_pull_skips_both_prune_and_upsert(monkeypatch):
    """Fail-safe, unchanged: an empty pull is a transient outage, not 'sold
    out' -- must not prune anything, and (new) must not add anything either."""
    existing = _board_row()
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(SLUG, [])])

    kept, stats = asyncio.run(prune_stale_reo([existing]))

    assert kept == [existing]
    assert stats["pruned"] == 0


def test_scraper_failure_is_fail_safe(monkeypatch):
    """Unchanged: an exception from the live re-scrape must never crash the
    run or touch the board."""
    existing = _board_row()
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FailingScraper()])

    kept, stats = asyncio.run(prune_stale_reo([existing]))

    assert kept == [existing]
    assert stats["pruned"] == 0


def test_a_healthy_run_lands_new_rows_and_refreshes_matched_rows_together(monkeypatch):
    """End-to-end shape of the real fix: one matched row gets refreshed, one
    brand-new row gets added, one truly-sold row gets pruned -- all from a
    single fresh pull, mirroring what an 8,244-row live inventory against a
    124-row stale board should do."""
    matched_existing = _board_row(addr="1 Match Ln", uuid="old-1")
    sold_existing = _board_row(addr="2 Sold Ln", uuid="old-2")
    fresh_matched = _fresh_row(addr="1 Match Ln", uuid="new-1")
    fresh_new = _fresh_row(addr="3 Brand New Ln", uuid="new-3")
    monkeypatch.setattr(
        mod, "all_scrapers",
        lambda: [_FakeScraper(SLUG, [fresh_matched, fresh_new])],
    )

    kept, stats = asyncio.run(prune_stale_reo([matched_existing, sold_existing]))

    case_numbers = {li.case_number for li in kept}
    assert case_numbers == {"fannie-new-1", "fannie-new-3"}
    assert stats["landed"] == {
        "matched": 1, "added": 1, "skipped_no_addr": 0, "skipped_out_of_scope": 0,
    }
    assert stats["pruned"] == 1
