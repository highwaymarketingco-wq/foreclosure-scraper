"""merge_duplicate_rows() (follow-up to patch_existing_rows(), 2026-09-30).

The problem: append_new_rows() adds rows, patch_existing_rows() mutates a known subset of
EXISTING rows in place -- neither can REMOVE a row, so the only prior path able to clean up the
~1,361 real duplicate rows left on the board by a scraper that wrote a mailing address instead of
a situs address (dedupe() never recognized the two rows as the same property, since their
dedupe_key()s genuinely differ) was load_board() -> dedupe() -> write_artifact(), which now needs
more memory than this 8 GB Mac has free at the board's current size.

merge_duplicate_rows() streams the existing board through _iter_board_records() (never
Listing.model_validate()d in bulk, never held as a full parsed-dict list) and, for each row,
checks a content-hash identity key (row_identity_hash(), over a narrow "as scraped, rarely
revised" field subset -- see its own docstring for why no single existing field, and no
dedupe_key(), is safe to use here) against a small set of pending merge groups. A match is held
(not yet written); once the whole board has been scanned, each group is folded with the REAL
Listing.merge() (dedupe.py's own merge semantics, reused verbatim) and the result is appended;
rows outside any group pass straight through unchanged, exactly like append_new_rows()/
patch_existing_rows().

Covers, in order:
  1. correctness: a 2-row group merges (field precedence, raw deep-merge, also_seen_in,
     LAZY_DETAIL_KEYS round-trip for both the merged row and untouched rows), row order is
     untouched-rows-first then merged rows appended, row-count arithmetic is exact
  2. merge_groups input validation: fewer than 2 members, a repeated key within one group, a key
     claimed by two different groups -- all refused before any I/O (ValueError)
  3. board-state mismatches: a key not found on the board (stale audit), a key matching more than
     one row (ambiguous) -- both refuse the WHOLE call, nothing written (BoardMergeGroupMismatch)
  4. contracts: board lock enforcement, manifest verifies after a merge, the merge-only size
     ceiling and its override, independence from the other ceilings, high-water mark rebase
  5. edge cases: empty merge_groups, merging onto a board that does not exist yet
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int, **kw) -> Listing:
    # House number is i+1, never i -- see test_patch_existing_rows.py's _lead() for why (a
    # leading "0 " is treated as a GIS "no house number assigned" sentinel and nulled on publish).
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               parcel_id=None, street_address=f"{i + 1} Main St", zip_code="28052",
               raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i + 1} Elm St"}],
                    "vision": {"parsed": True}})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Mirrors test_patch_existing_rows.py's fixture: tmp/docs is 'the live board' for lock
    enforcement purposes, tmp/logs/.board.lock its lock."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(wa, "_live_docs_dir", lambda: docs)
    for var in (wa.BOARD_LOCK_ENV, wa.BOARD_LOCK_TOKEN_ENV):
        monkeypatch.delenv(var, raising=False)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return tmp_path


def _seed(docs: Path, n: int = 5) -> list[Listing]:
    leads = [_lead(i) for i in range(n)]
    wa.write_artifact(leads, {"notes": "seed"}, docs_dir=docs)
    return leads


def _hash_for(docs: Path, street_address: str) -> str:
    rows = json.loads((docs / "listings.json").read_text())
    rec = next(r for r in rows if r["street_address"] == street_address)
    return wa.row_identity_hash(rec)


# ===========================================================================
# 1. correctness
# ===========================================================================

def test_two_row_group_merges_the_mailing_vs_situs_duplicate(tmp_path):
    docs = tmp_path / "docs"
    # The real bug this tool cleans up: two rows for ONE property, different dedupe_key()s
    # (situs vs mailing address), so dedupe() never merged them at scrape time.
    situs = _lead(0, parcel_id=None, street_address="100 River Rd", zip_code="28052",
                  source="county_gis", opening_bid=50000.0)
    # A normal-looking street address (passes _is_valid_street_address on publish, unlike a
    # literal "PO Box 42") that is nonetheless the OWNER'S mailing address, not the property's
    # situs -- the actual shape of the bug this tool cleans up.
    mailing = _lead(1, parcel_id="P-555", street_address="77 Corporate Blvd", zip_code="28053",
                    source="law_firm", opening_bid=0.0,
                    raw={"skip_trace": {"phone": "555-1234"}})
    other = _lead(2, street_address="9 Untouched Ln")
    wa.write_artifact([situs, mailing, other], {"notes": "seed"}, docs_dir=docs)

    key_kept = _hash_for(docs, "100 River Rd")
    key_drop = _hash_for(docs, "77 Corporate Blvd")
    assert key_kept != key_drop

    stats = wa.merge_duplicate_rows([[key_kept, key_drop]], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True
    assert stats["groups"] == 1
    assert stats["rows_targeted"] == 2
    assert stats["rows_dropped"] == 1
    assert stats["existing"] == 3
    assert stats["total_after"] == 2

    board = wa.load_board(docs)
    assert len(board) == 2
    assert not any(li.street_address == "77 Corporate Blvd" for li in board)
    kept = next(li for li in board if li.street_address == "100 River Rd")
    assert kept.parcel_id == "P-555"                     # filled from the dropped row
    assert kept.opening_bid == 50000.0                   # kept's own non-zero value wins
    assert kept.source == "county_gis"                   # kept row's identity stays primary
    assert kept.raw.get("skip_trace") == {"phone": "555-1234"}   # merged in from the drop
    assert kept.raw.get("grade") == {"overall": "B"}     # kept's own raw preserved
    assert any(d.get("url") == mailing.source_url for d in kept.raw.get("also_seen_in", []))
    untouched = next(li for li in board if li.street_address == "9 Untouched Ln")
    assert untouched.source == other.source
    assert untouched.raw.get("comps") == other.raw["comps"]


def test_three_row_group_row_count_arithmetic_is_exact(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=6)  # 3 duplicates of one property + 3 untouched
    keys = [wa.row_identity_hash(json.loads((docs / "listings.json").read_text())[i])
            for i in (0, 1, 2)]
    stats = wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert stats["rows_targeted"] == 3
    assert stats["rows_dropped"] == 2
    assert stats["existing"] == 6
    assert stats["total_after"] == 4
    board = wa.load_board(docs)
    assert len(board) == 4


def test_untouched_rows_are_byte_for_byte_unchanged_and_merged_row_appended_last(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    before = json.loads((docs / "listings.json").read_text())
    key_a = wa.row_identity_hash(before[1])
    key_b = wa.row_identity_hash(before[3])

    stats = wa.merge_duplicate_rows([[key_a, key_b]], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True

    after = json.loads((docs / "listings.json").read_text())
    assert len(after) == 4
    # Rows 0, 2, 4 (untouched) keep their original relative order, unchanged, at the front.
    assert after[0] == before[0]
    assert after[1] == before[2]
    assert after[2] == before[4]
    # The merged survivor (row 1's identity, since it is index 0 of the group) is appended last.
    assert after[3]["street_address"] == before[1]["street_address"]


def test_two_groups_in_one_call(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=8)
    rows = json.loads((docs / "listings.json").read_text())
    group1 = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    group2 = [wa.row_identity_hash(rows[4]), wa.row_identity_hash(rows[5]),
              wa.row_identity_hash(rows[6])]
    stats = wa.merge_duplicate_rows([group1, group2], {"notes": "t"}, docs_dir=docs)
    assert stats["groups"] == 2
    assert stats["rows_targeted"] == 5
    assert stats["rows_dropped"] == 3
    assert stats["total_after"] == 5
    board = wa.load_board(docs)
    assert len(board) == 5


# ===========================================================================
# 2. merge_groups input validation (no I/O -- refused before the board is touched)
# ===========================================================================

def test_group_with_fewer_than_two_members_raises_value_error(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    with pytest.raises(ValueError, match="fewer than 2"):
        wa.merge_duplicate_rows([["only-one-key"]], {"notes": "t"}, docs_dir=docs)


def test_repeated_key_within_one_group_raises_value_error(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    with pytest.raises(ValueError, match="more than once"):
        wa.merge_duplicate_rows([["k1", "k1"]], {"notes": "t"}, docs_dir=docs)


def test_key_claimed_by_two_groups_raises_value_error(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    with pytest.raises(ValueError, match="ONE merge group"):
        wa.merge_duplicate_rows([["k1", "k2"], ["k1", "k3"]], {"notes": "t"}, docs_dir=docs)


def test_invalid_merge_groups_touch_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    with pytest.raises(ValueError):
        wa.merge_duplicate_rows([["k1", "k1"]], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


# ===========================================================================
# 3. board-state mismatches -- refuse the WHOLE call, nothing written
# ===========================================================================

def test_key_not_found_on_the_board_refuses_and_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=3)
    real_key = wa.row_identity_hash(json.loads((docs / "listings.json").read_text())[0])
    before = (docs / "listings.json").read_bytes()
    with pytest.raises(wa.BoardMergeGroupMismatch, match="not found"):
        wa.merge_duplicate_rows([[real_key, "no-such-row-hash"]], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


def test_key_matching_more_than_one_row_refuses_and_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    # Two rows that are identical across every _MERGE_HASH_FIELDS field (a genuine, if
    # contrived, ambiguous case) -- merge_duplicate_rows must refuse rather than guess which
    # physical row was meant.
    a = _lead(0, street_address="1 Twin St", source="dup_src", source_url="https://x.test/dup")
    b = _lead(1, street_address="1 Twin St", source="dup_src", source_url="https://x.test/dup")
    other = _lead(2, street_address="9 Untouched Ln")
    wa.write_artifact([a, b, other], {"notes": "seed"}, docs_dir=docs)
    rows = json.loads((docs / "listings.json").read_text())
    key = wa.row_identity_hash(rows[0])
    assert key == wa.row_identity_hash(rows[1])
    other_key = wa.row_identity_hash(rows[2])

    before = (docs / "listings.json").read_bytes()
    with pytest.raises(wa.BoardMergeGroupMismatch, match="more than one row"):
        wa.merge_duplicate_rows([[key, other_key]], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


# ===========================================================================
# 4. contracts: lock, manifest, size ceiling, high-water rebase
# ===========================================================================

def test_refuses_the_live_board_without_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    with pytest.raises(wa.BoardLockNotHeld):
        wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)


def test_succeeds_under_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    with wa.board_lock(live, owner="t"):
        stats = wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_manifest_verifies_after_a_merge(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    result = wa.verify_manifest(docs)
    assert result["ok"] is True, result["problems"]
    assert result["count"] == 4


def test_merge_size_state_is_ok_for_a_small_board(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    st = wa.board_merge_size_state(docs)
    assert st["ok"] is True


def test_merge_refuses_over_its_own_ceiling(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    monkeypatch.setenv("BOARD_MERGE_MAX_SOURCE_MB", "0.0001")
    with pytest.raises(wa.BoardLoadTooLarge) as ei:
        wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert "over the 0 MB ceiling" in str(ei.value)


def test_merge_allow_large_overrides_the_ceiling_for_one_run(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    monkeypatch.setenv("BOARD_MERGE_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_MERGE_ALLOW_LARGE", "1")
    stats = wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_merge_ceiling_is_independent_of_the_other_three_ceilings(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    monkeypatch.setenv("BOARD_LOAD_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_APPEND_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0.0001")
    stats = wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_high_water_mark_rebases_down_by_the_merged_amount(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=3)
    hw_before = json.loads((docs / "board_highwater.json").read_text())["count"]
    assert hw_before == 3

    rows = json.loads((docs / "listings.json").read_text())
    keys = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    stats = wa.merge_duplicate_rows([keys], {"notes": "t"}, docs_dir=docs)
    assert stats["total_after"] == 2

    hw_after = json.loads((docs / "board_highwater.json").read_text())
    assert hw_after["count"] == 2
    assert hw_after.get("rebased_from") == 3


# ===========================================================================
# 5. edge cases
# ===========================================================================

def test_empty_merge_groups_is_a_no_op_and_touches_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    stats = wa.merge_duplicate_rows([], {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": None, "groups": 0, "rows_targeted": 0, "rows_dropped": 0,
                     "written": False, "total_after": None}
    assert (docs / "listings.json").read_bytes() == before


def test_merging_onto_a_board_that_does_not_exist_yet_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    stats = wa.merge_duplicate_rows([["k1", "k2"]], {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": 0, "groups": 1, "rows_targeted": 2, "rows_dropped": 0,
                     "written": False, "total_after": 0}
    assert not (docs / "listings.json").exists()
