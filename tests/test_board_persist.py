"""Full-run cumulative-board persistence (board_persist.merge_prior_board).

Pins the invariants that make main.run() ADDITIVE instead of REPLACING the
published board with a fresh-only scrape:

  1. NO COUNT DROP — persisted-but-not-re-scraped leads are kept.
  2. NO RE-GRADE — a matched lead carries its prior raw["vision"] and is not
     re-selected by the vision pass (_needs_vision is False).
  3. FRESH WINS — a matched lead's fresh sale_date/opening_bid/status win;
     only missing enrichment is backfilled from prior.
  4. AGING — prior-only leads are kept but aged via the SAME pulled_sale
     miss counter, and dropped when terminal or past N misses.
  5. NEW leads pass through (enriched normally downstream).
  6. DEDUP collapses fresh<->prior duplicates into one row.

Plus the 2026-10-04 streaming rewrite's OWN invariants (replacing load_board() +
dedupe() with a fresh-indexed stream of _iter_board_records() -- see
board_persist.py's module docstring and web_artifact.BOARD_PRIOR_MERGE_MAX_SOURCE_MB's
comment for the full writeup):

  7. SIZE CEILING — merge_prior_board refuses over its own ceiling, the same
     BOARD_PRIOR_MERGE_ALLOW_LARGE=1 / BOARD_PRIOR_MERGE_MAX_SOURCE_MB override
     pattern every sibling streaming function in web_artifact.py already has.
  8. HOUSE-NUMBER GUARD — a prior row sharing a signature with a fresh row but
     carrying a provably different house number must NOT merge (dedupe()'s own
     safety net, replicated here rather than silently fused).
  9. NEVER VALIDATE A DROPPED ROW — a prior row that is terminal (dropped
     outright) is never run through Listing.model_validate(), even if it would
     fail validation — the whole point of streaming is to not pay that cost for
     rows that never survive into the output.
  10. BOUNDED, NON-FATAL DROP TOLERANCE — a prior row that IS kept (matched or
      aged-and-kept) but fails Listing.model_validate() is counted and dropped,
      not fatal, unless the rate exceeds PRIOR_MERGE_MAX_DROP_RATE, in which case
      merge_prior_board refuses outright (BoardLoadDropError) rather than
      silently publishing a board that quietly lost more than that.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper import board_persist as bp
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_vision import _needs_vision
from foreclosure_scraper.models import Listing, ListingType

NOW = datetime(2026, 7, 31)


def _li(**kw) -> Listing:
    base = dict(
        source="law_firms.brock_scott",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime(2026, 4, 1),
        last_seen=datetime(2026, 5, 1),
    )
    base.update(kw)
    return Listing(**base)


def _write_board(docs_dir: Path, listings: list[Listing]) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    data = [li.model_dump(mode="json") for li in listings]
    (docs_dir / "listings.json").write_text(json.dumps(data))


def _imgs() -> dict:
    return {"images": {"real": ["https://img/1.jpg"]}}


# --------------------------------------------------------------------------
# First run / empty prior board
# --------------------------------------------------------------------------

def test_empty_prior_board_returns_fresh_unchanged(tmp_path):
    fresh = [_li(street_address="1 Main St", zip_code="28801")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert len(out) == 1
    assert stats["prior_count"] == 0
    assert stats["merged_count"] == 1
    # sentinel must never leak
    assert "_seen_this_run" not in (out[0].raw or {})


# --------------------------------------------------------------------------
# Invariant 1 — no count drop; prior-only leads kept
# --------------------------------------------------------------------------

def test_prior_only_lead_is_kept_no_count_drop(tmp_path):
    prior = [
        _li(street_address="10 Oak St", zip_code="28801", source="sc_public_index_export"),
        _li(street_address="20 Elm St", zip_code="28801"),
    ]
    _write_board(tmp_path, prior)
    # fresh scrape re-finds only ONE of the two prior leads, plus a brand new one
    fresh = [
        _li(street_address="20 Elm St", zip_code="28801"),
        _li(street_address="99 New Rd", zip_code="28803"),
    ]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    addrs = {li.street_address for li in out}
    # the non-re-scraped manual-lane lead survived
    assert "10 Oak St" in addrs
    assert "99 New Rd" in addrs
    assert "20 Elm St" in addrs
    assert stats["merged_count"] >= stats["prior_count"]  # no drop


# --------------------------------------------------------------------------
# Invariant 2 — matched lead carries prior vision, not re-graded
# Invariant 3 — fresh fields win
# --------------------------------------------------------------------------

def test_matched_lead_carries_vision_and_fresh_fields_win(tmp_path):
    vision = {"condition_tier": "cosmetic", "vision_summary": "prior read"}
    prior = [
        _li(
            street_address="5 Pine St",
            zip_code="28801",
            sale_date=datetime(2026, 6, 1),
            opening_bid=100000.0,
            auction_status="active",
            raw={**_imgs(), "vision": vision, "gis": {"owner": "OLD OWNER"}},
        )
    ]
    _write_board(tmp_path, prior)
    # fresh re-scrape: NEW sale_date + NEW opening_bid, NO vision (fresh Listing)
    fresh = [
        _li(
            street_address="5 Pine St",
            zip_code="28801",
            sale_date=datetime(2026, 8, 15),
            opening_bid=125000.0,
            auction_status="postponed",
            raw=dict(_imgs()),
        )
    ]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert len(out) == 1  # dedup collapsed
    m = out[0]
    # Invariant 3: fresh scrape fields win
    assert m.sale_date == datetime(2026, 8, 15)
    assert m.opening_bid == 125000.0
    assert m.auction_status == "postponed"
    # Invariant 2: prior vision carried onto the fresh Listing
    assert (m.raw or {}).get("vision") == vision
    assert (m.raw or {}).get("gis", {}).get("owner") == "OLD OWNER"
    # ...and the vision pass will SKIP it (already scored + has imagery)
    assert _needs_vision(m) is False
    assert stats["matched"] == 1
    assert stats["carried_vision"] == 1


# --------------------------------------------------------------------------
# Invariant 4 — aging: prior-only lead gets a miss counter; drops past N / terminal
# --------------------------------------------------------------------------

def test_prior_only_lead_is_aged_with_miss_counter(tmp_path):
    prior = [_li(street_address="7 Birch St", zip_code="28801")]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 Somewhere", zip_code="28803")]
    out, _ = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    aged = [li for li in out if li.street_address == "7 Birch St"][0]
    ps = (aged.raw or {}).get("pulled_sale")
    assert ps and ps["consecutive_misses"] == 1
    assert ps["presumed_withdrawn"] is True
    assert aged.auction_status == "presumed_withdrawn"


def test_prior_only_lead_dropped_past_max_misses(tmp_path):
    # prior lead already at the retention edge
    prior = [
        _li(
            street_address="8 Maple St",
            zip_code="28801",
            raw={"pulled_sale": {"consecutive_misses": 4, "first_missed_at": "2026-06-01Z"}},
        )
    ]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 Somewhere", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW, max_misses=4)
    assert "8 Maple St" not in {li.street_address for li in out}
    assert stats["aged_out_misses"] == 1


def test_prior_only_terminal_sold_confirmed_dropped(tmp_path):
    prior = [
        _li(street_address="9 Cedar St", zip_code="28801", raw={"sold_confirmed": True})
    ]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 Somewhere", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert "9 Cedar St" not in {li.street_address for li in out}
    assert stats["aged_out_terminal"] == 1


def test_prior_only_terminal_sale_past_upset_window_dropped(tmp_path, monkeypatch):
    # NOTE: the module DEFAULT for FULLRUN_PERSIST_TERMINAL_GRACE_DAYS is now 365
    # (Hermes bumped it from 45 to avoid dropping ~47K records) — that is a pending
    # product decision that contradicts the module's own drop-after-the-10-day-
    # upset-window comment. This test pins the drop-at-45 behavior deterministically
    # by forcing the grace window to 45, regardless of whatever the default is.
    import foreclosure_scraper.board_persist as bp

    monkeypatch.setenv("FULLRUN_PERSIST_TERMINAL_GRACE_DAYS", "45")
    monkeypatch.setattr(bp, "TERMINAL_SALE_GRACE_DAYS", 45)

    prior = [
        _li(
            street_address="11 Walnut St",
            zip_code="28801",
            sale_date=NOW - timedelta(days=90),  # 90d > 45d grace => past upset window
        )
    ]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 Somewhere", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert "11 Walnut St" not in {li.street_address for li in out}
    assert stats["aged_out_terminal"] == 1


def test_reappeared_lead_clears_stale_pulled_sale(tmp_path):
    prior = [
        _li(
            street_address="12 Ash St",
            zip_code="28801",
            auction_status="presumed_withdrawn",
            raw={"pulled_sale": {"consecutive_misses": 2, "first_missed_at": "2026-06-01Z"}},
        )
    ]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="12 Ash St", zip_code="28801")]  # re-scraped again
    out, _ = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    m = [li for li in out if li.street_address == "12 Ash St"][0]
    assert "pulled_sale" not in (m.raw or {})
    assert m.auction_status != "presumed_withdrawn"


# --------------------------------------------------------------------------
# Invariant 5 — new fresh-only lead enriched normally (needs vision)
# --------------------------------------------------------------------------

def test_new_fresh_only_lead_still_needs_vision(tmp_path):
    prior = [_li(street_address="20 Elm St", zip_code="28801", raw={**_imgs(), "vision": {"x": 1}})]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="30 New Ave", zip_code="28803", raw=dict(_imgs()))]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    new = [li for li in out if li.street_address == "30 New Ave"][0]
    assert _needs_vision(new) is True  # will be graded
    assert stats["fresh_only"] == 1


# --------------------------------------------------------------------------
# Invariant 6 — dedup collapse, no balloon
# --------------------------------------------------------------------------

def test_dedup_collapses_fresh_and_prior_no_double_count(tmp_path):
    prior = [
        _li(street_address="40 River Rd", zip_code="28801", parcel_id="1234-56-7890", county="Buncombe", state="NC"),
    ]
    _write_board(tmp_path, prior)
    # same property, parcel written differently + fresh source
    fresh = [
        _li(street_address="40 River Rd", zip_code="28801", parcel_id="1234567890", county="Buncombe", state="NC",
            source="counties_nc.buncombe"),
    ]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert len(out) == 1
    assert stats["matched"] == 1


# --------------------------------------------------------------------------
# _needs_vision idempotency gate
# --------------------------------------------------------------------------

def test_needs_vision_gate(monkeypatch):
    scored = _li(street_address="1 A St", zip_code="1", raw={**_imgs(), "vision": {"x": 1}})
    unscored = _li(street_address="2 B St", zip_code="2", raw=dict(_imgs()))
    no_img = _li(street_address="3 C St", zip_code="3", raw={"vision": {"x": 1}})
    monkeypatch.delenv("VISION_REGRADE_SCORED", raising=False)
    assert _needs_vision(scored) is False   # already scored -> skip
    assert _needs_vision(unscored) is True   # has imagery, unscored -> grade
    assert _needs_vision(no_img) is False    # no imagery -> nothing to do
    # escape hatch restores re-grading of already-scored leads
    monkeypatch.setenv("VISION_REGRADE_SCORED", "1")
    assert _needs_vision(scored) is True


# --------------------------------------------------------------------------
# Invariant 7 — merge_prior_board's OWN size ceiling (streaming rewrite, 2026-10-04)
# --------------------------------------------------------------------------

def test_prior_merge_refuses_over_its_own_ceiling(tmp_path, monkeypatch):
    prior = [_li(street_address="1 Oak St", zip_code="28801")]
    _write_board(tmp_path, prior)
    monkeypatch.setenv("BOARD_PRIOR_MERGE_MAX_SOURCE_MB", "0.0001")
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    with pytest.raises(wa.BoardLoadTooLarge) as ei:
        merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert "over the 0 MB ceiling" in str(ei.value)


def test_prior_merge_allow_large_overrides_the_ceiling_for_one_run(tmp_path, monkeypatch):
    prior = [_li(street_address="1 Oak St", zip_code="28801")]
    _write_board(tmp_path, prior)
    monkeypatch.setenv("BOARD_PRIOR_MERGE_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_PRIOR_MERGE_ALLOW_LARGE", "1")
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert stats["prior_count"] == 1
    assert "1 Oak St" in {li.street_address for li in out}


def test_prior_merge_ceiling_is_independent_of_loads_ceiling(tmp_path, monkeypatch):
    """BOARD_LOAD_MAX_SOURCE_MB must not gate merge_prior_board any more -- that was
    exactly the Oracle VM crash (2026-10-04): load_board()'s own, Mac-calibrated
    ceiling refusing a board the streaming rewrite never even asks it about."""
    prior = [_li(street_address="1 Oak St", zip_code="28801")]
    _write_board(tmp_path, prior)
    monkeypatch.setenv("BOARD_LOAD_MAX_SOURCE_MB", "0.0001")
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert stats["prior_count"] == 1


# --------------------------------------------------------------------------
# Invariant 8 — house-number guard (dedupe()'s own safety net, replicated)
# --------------------------------------------------------------------------

def test_shared_parcel_different_house_number_does_not_merge(tmp_path):
    # Same (bad/shared) parcel id, but the street numbers provably differ --
    # dedupe()'s house_number_guard exists exactly because a shared parcel_id
    # across two different houses is a real, observed data bug, not a hypothetical.
    prior = [
        _li(street_address="306 Fountain Way", zip_code="28801",
            parcel_id="9698372180", county="Buncombe", state="NC")
    ]
    _write_board(tmp_path, prior)
    fresh = [
        _li(street_address="346 Fountain Way", zip_code="28801",
            parcel_id="9698372180", county="Buncombe", state="NC",
            source="counties_nc.buncombe")
    ]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    addrs = {li.street_address for li in out}
    # Two distinct houses stay two distinct rows -- a merge here would have
    # silently deleted one of two real properties.
    assert "306 Fountain Way" in addrs
    assert "346 Fountain Way" in addrs
    assert stats["matched"] == 0
    assert stats["fresh_only"] == 1
    assert stats["prior_only_kept"] == 1


# --------------------------------------------------------------------------
# Invariant 9 — a dropped (terminal/aged-out) prior row is NEVER validated,
# even if it would fail validation
# --------------------------------------------------------------------------

def test_terminal_row_is_dropped_without_ever_validating_it(tmp_path):
    docs = tmp_path
    docs.mkdir(parents=True, exist_ok=True)
    # Hand-written board row: sold_confirmed (terminal -> dropped outright) AND
    # carrying an invalid listing_type that Listing.model_validate() would reject.
    # If this function validated it before checking terminal status, it would
    # either raise or show up in prior_drop_errors; it must do neither.
    poison_row = {
        "source": "x", "source_url": "https://example.com/poison",
        "listing_type": "not_a_real_listing_type",
        "street_address": "66 Doom St", "zip_code": "28801",
        "raw": {"sold_confirmed": True},
    }
    (docs / "listings.json").write_text(json.dumps([poison_row]))
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=docs, now=NOW)
    assert stats["aged_out_terminal"] == 1
    assert stats["prior_drop_errors"] == 0
    assert "66 Doom St" not in {li.street_address for li in out}


# --------------------------------------------------------------------------
# Invariant 10 — bounded, non-fatal drop tolerance for a KEPT row that fails
# validation; fatal once the rate exceeds PRIOR_MERGE_MAX_DROP_RATE
# --------------------------------------------------------------------------

def test_one_bad_kept_row_among_many_is_dropped_not_fatal(tmp_path, monkeypatch):
    docs = tmp_path
    docs.mkdir(parents=True, exist_ok=True)
    # 1 bad row in 51 streamed-for-drop-rate rows is ~2%, over the default 0.1%
    # PRIOR_MERGE_MAX_DROP_RATE -- raise the tolerance for THIS test so it can
    # pin the "counted, not fatal, below the limit" behavior on its own; the
    # next test pins what happens ABOVE the limit.
    monkeypatch.setattr(bp, "PRIOR_MERGE_MAX_DROP_RATE", 0.05)
    good = [_li(street_address=f"{i} Good St", zip_code="28801").model_dump(mode="json")
            for i in range(50)]
    bad = {
        "source": "x", "source_url": "https://example.com/bad",
        "listing_type": "not_a_real_listing_type",
        "street_address": "1 Bad St", "zip_code": "28899",
        "raw": {},
    }
    (docs / "listings.json").write_text(json.dumps(good + [bad]))
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=docs, now=NOW)
    assert stats["prior_drop_errors"] == 1
    assert "1 Bad St" not in {li.street_address for li in out}
    # the 50 good rows still made it through
    assert stats["prior_only_kept"] == 50


def test_drop_rate_over_limit_raises(tmp_path, monkeypatch):
    docs = tmp_path
    docs.mkdir(parents=True, exist_ok=True)
    # PRIOR_MERGE_MAX_DROP_RATE is resolved once at module import (same reason
    # TERMINAL_SALE_GRACE_DAYS is: see test_prior_only_terminal_sale_past_upset_
    # window_dropped's own comment) -- monkeypatch the module ATTRIBUTE, not the
    # env var, same pattern that test already uses.
    monkeypatch.setattr(bp, "PRIOR_MERGE_MAX_DROP_RATE", 0.01)  # 1%
    good = [_li(street_address=f"{i} Good St", zip_code="28801").model_dump(mode="json")
            for i in range(5)]
    bad_rows = [
        {"source": "x", "source_url": f"https://example.com/bad{i}",
         "listing_type": "not_a_real_listing_type",
         "street_address": f"{i} Bad St", "zip_code": "28899", "raw": {}}
        for i in range(3)
    ]
    (docs / "listings.json").write_text(json.dumps(good + bad_rows))
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    with pytest.raises(wa.BoardLoadDropError):
        bp.merge_prior_board(fresh, docs_dir=docs, now=NOW)


# --------------------------------------------------------------------------
# Scale sanity — a larger prior-only board (no fresh matches) streams through
# correctly without needing any fresh/prior fuzzy cross product
# --------------------------------------------------------------------------

def test_many_prior_only_rows_all_survive_or_age_consistently(tmp_path):
    prior = [_li(street_address=f"{i} Pine St", zip_code="28801") for i in range(500)]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 New Rd", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW)
    assert stats["prior_count"] == 500
    assert stats["prior_only_kept"] == 500
    assert stats["matched"] == 0
    assert stats["fresh_only"] == 1
    assert len(out) == 501
    for li in out:
        if li.street_address != "99 New Rd":
            assert (li.raw or {}).get("pulled_sale", {}).get("consecutive_misses") == 1
