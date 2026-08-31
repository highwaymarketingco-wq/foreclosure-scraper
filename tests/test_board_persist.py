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
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

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
