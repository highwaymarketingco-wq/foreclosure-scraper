"""Rows enrichment_reo_freshness ADDS must leave it with a tier.

2026-10-06: a scratch publish of the 10/5 run's pre_publish checkpoint had 417 rows with no
raw['distress_stack'], 415 of them national.fannie_homepath. main.run_enrich_tail runs
score_board, then (later) prune_stale_reo, whose upsert appends the HomePath listings the
scrape phase never landed (the 9/23 run logged `landed.added=423`). Nothing scored them, so
they published with no HOT/WARM/COLD tier and no intent score until the NEXT run's scorer.

These tests run the real order (score_board over the board, then prune_stale_reo) with a fake
HomePath pull. Addresses and parcel ids are invented.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

import foreclosure_scraper.main as main_mod
from foreclosure_scraper import distress_score
from foreclosure_scraper import enrichment_reo_freshness as mod
from foreclosure_scraper.distress_score import score_board, score_late_rows
from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo
from foreclosure_scraper.models import Listing, ListingType

SLUG = "national.fannie_homepath"
TODAY = date.today()   # prune_stale_reo scores with today; the reference must too


class _FakeScraper:
    def __init__(self, rows):
        self.slug = SLUG
        self._rows = rows

    async def safe_run(self):
        return list(self._rows)


def _homepath(addr, uuid, parcel=None, county="Buncombe"):
    """The shape national.fannie_homepath returns: no enrichment, no distress_stack."""
    return Listing(source=SLUG, source_url=f"https://homepath.fanniemae.com/property/{uuid}",
                   case_number=f"fannie-{uuid}", listing_type=ListingType.REO, state="NC",
                   county=county, city="Asheville", street_address=addr, parcel_id=parcel,
                   opening_bid=180_000.0, raw={"fannie": {"uuid": uuid}})


def _tax_row(addr, parcel, county="Buncombe"):
    return Listing(source="counties_nc.example_tax", source_url="https://example.invalid/tax",
                   listing_type=ListingType.TAX_LIEN, state="NC", county=county,
                   city="Asheville", street_address=addr, parcel_id=parcel,
                   amount_owed=4_200.0, raw={})


def _tier(li):
    ds = (li.raw or {}).get("distress_stack")
    return ds.get("tier") if isinstance(ds, dict) else None


@pytest.fixture(autouse=True)
def _admit_everything(monkeypatch):
    monkeypatch.setattr(main_mod, "_in_scope", lambda li: True)


def _run_tail(board, fresh, monkeypatch):
    """score_board, then prune_stale_reo: the order main.run_enrich_tail uses."""
    score_board(board, previous_path=None, today=TODAY)
    monkeypatch.setattr(mod, "all_scrapers", lambda: [_FakeScraper(fresh)])
    monkeypatch.setattr(mod, "_PREV_BOARD", None)
    return asyncio.run(prune_stale_reo(board))


def test_an_added_homepath_row_leaves_with_a_tier_and_an_intent_score(monkeypatch):
    on_board = _homepath("10 Example Ridge Rd", "u-1")
    board = [on_board, _tax_row("22 Sample Hollow Ln", "9600-11-2233")]
    fresh = [_homepath("10 Example Ridge Rd", "u-1b"), _homepath("31 Placeholder Ct", "u-2")]

    kept, stats = _run_tail(board, fresh, monkeypatch)

    assert stats["landed"]["added"] == 1
    added = [li for li in kept if li.street_address == "31 Placeholder Ct"]
    assert len(added) == 1
    assert _tier(added[0]) in ("HOT", "WARM", "COLD"), "an added row published with no tier"
    assert "intent_score" in added[0].raw and "intent_band" in added[0].raw
    assert all(_tier(li) for li in kept), "every row on the board carries a tier"
    assert sum(stats["added_tiers"].values()) == 1


def test_the_added_row_gets_the_stack_a_whole_board_pass_would_give_it(monkeypatch):
    """A HomePath row with a parcel id that another board row shares is scored WITH that row:
    the same group stack as score_board over the board that already holds it."""
    tax = _tax_row("44 Mock Branch Rd", "9611-22-3344")
    board = [tax, _homepath("5 Other Ln", "u-9")]
    new = _homepath("44 Mock Branch Rd Unit A", "u-3", parcel="9611-22-3344")

    kept, stats = _run_tail(board, [_homepath("5 Other Ln", "u-9"), new], monkeypatch)
    assert stats["landed"]["added"] == 1

    ref_tax = _tax_row("44 Mock Branch Rd", "9611-22-3344")
    ref_new = _homepath("44 Mock Branch Rd Unit A", "u-3", parcel="9611-22-3344")
    score_board([ref_tax, ref_new, _homepath("5 Other Ln", "u-9")], previous_path=None, today=TODAY)

    assert new.raw["distress_stack"] == ref_new.raw["distress_stack"]
    assert tax.raw["distress_stack"] == ref_tax.raw["distress_stack"], (
        "the board row on the same parcel is re-scored with the REO signal it now stacks with")
    assert new.raw["distress_stack"]["stack"] >= 2


def test_score_late_rows_keeps_the_whole_board_counters(monkeypatch):
    board = [_tax_row("1 Fixture Way", "9622-33-4455")]
    score_board(board, previous_path=None, today=TODAY)
    before = dict(distress_score.LAST_STATS)
    score_late_rows(board, [_homepath("2 Fixture Way", "u-4")], previous_path=None, today=TODAY)
    assert distress_score.LAST_STATS == before


def test_late_rows_without_a_parcel_do_not_scan_the_board(monkeypatch):
    """The common HomePath case (no parcel id yet): the late rows are their own groups, so the
    270K-row board is not walked to find parcel siblings."""
    import foreclosure_scraper.dedupe as dedupe_mod

    def _boom(_):
        raise AssertionError("suspicious_parcel_keys must not run over the board here")

    late = [_homepath("3 Fixture Way", "u-5"), _homepath("4 Fixture Way", "u-6")]
    board = [_tax_row("9 Fixture Way", "9633-44-5566")] + late
    monkeypatch.setattr(dedupe_mod, "suspicious_parcel_keys", _boom)
    hist = score_late_rows(board, late, previous_path=None, today=TODAY)
    assert sum(hist.values()) == 2
    assert all(_tier(li) for li in late)
    assert _tier(board[0]) is None, "a row on another parcel is not touched"


def test_a_scorer_failure_still_leaves_every_added_row_with_a_tier(monkeypatch):
    def _broken(*a, **k):
        raise RuntimeError("scorer down")

    monkeypatch.setattr(distress_score, "score_late_rows", _broken)
    kept, stats = _run_tail([], [_homepath("7 Fixture Way", "u-7")], monkeypatch)
    assert stats["landed"]["added"] == 1
    ds = kept[0].raw["distress_stack"]
    assert ds["tier"] == "COLD" and ds["score_error"]
