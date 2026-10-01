"""web_artifact.delete_rows() (task_board_dedupe_stream, 2026-10-01).

The problem: append_new_rows() adds, patch_existing_rows() mutates a known subset of EXISTING
rows, merge_duplicate_rows() folds a known set of duplicate GROUPS into one survivor each -- none
of the three can remove a row with NO survivor. scripts/daily_api_refresh.py's stale-REO prune
(enrichment_reo_freshness.prune_stale_reo: a property confirmed sold/off-market by consecutive
daily misses) is exactly this shape, and today still goes through load_board() -> filter ->
write_artifact() to do it.

delete_rows() streams the existing board through _iter_board_records() (never
Listing.model_validate()d in bulk, never held as a full parsed-dict list) and, for each row,
checks a content-hash identity key (row_identity_hash(), the same narrow "as scraped, rarely
revised" field subset merge_duplicate_rows() uses) against a small set of requested deletions. A
match is held (not yet dropped); once the whole board has been scanned, every requested hash must
have matched EXACTLY one row or the WHOLE call refuses (BoardDeleteMismatch) -- deletion is
irreversible, so this is at least as strict as merge_duplicate_rows()'s all-or-nothing refusal,
stricter than patch_existing_rows()'s "apply to every match" tolerance.

Covers, in order:
  1. correctness: a single row deletes, multiple rows in one call delete, row order and byte
     content of untouched rows is preserved, row-count arithmetic is exact
  2. input validation: a repeated hash in `hashes` refused before any I/O (ValueError)
  3. board-state mismatches: a hash not found on the board, a hash matching more than one row --
     both refuse the WHOLE call, nothing written (BoardDeleteMismatch)
  4. contracts: board lock enforcement, manifest verifies after a delete, the delete-only size
     ceiling and its override, independence from the other four ceilings, high-water mark rebase
  5. edge cases: empty `hashes`, deleting from a board that does not exist yet
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.REO, state="NC", county="Gaston",
               parcel_id=None, street_address=f"{i + 1} Main St", zip_code="28052",
               raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i + 1} Elm St"}],
                    "vision": {"parsed": True}})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Mirrors test_merge_duplicate_rows.py's fixture: tmp/docs is 'the live board' for lock
    enforcement purposes."""
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

def test_single_row_deletes(tmp_path):
    docs = tmp_path / "docs"
    stale = _lead(0, street_address="100 Sold St", source="national.fannie_homepath")
    kept = _lead(1, street_address="9 Still There Ln")
    wa.write_artifact([stale, kept], {"notes": "seed"}, docs_dir=docs)

    h = _hash_for(docs, "100 Sold St")
    stats = wa.delete_rows([h], {"notes": "stale REO prune"}, docs_dir=docs)
    assert stats["written"] is True
    assert stats["existing"] == 2
    assert stats["requested"] == 1
    assert stats["matched"] == 1
    assert stats["deleted"] == 1
    assert stats["not_found"] == 0
    assert stats["total_after"] == 1

    board = wa.load_board(docs)
    assert len(board) == 1
    assert board[0].street_address == "9 Still There Ln"
    assert not any(li.street_address == "100 Sold St" for li in board)
    # the kept row's vision/comps sidecar survived the round-trip untouched
    assert board[0].raw.get("comps") == kept.raw["comps"]
    assert board[0].raw.get("vision") == kept.raw["vision"]


def test_multiple_rows_delete_in_one_call(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=6)
    rows = json.loads((docs / "listings.json").read_text())
    hashes = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[2]),
             wa.row_identity_hash(rows[4])]
    stats = wa.delete_rows(hashes, {"notes": "t"}, docs_dir=docs)
    assert stats["deleted"] == 3
    assert stats["existing"] == 6
    assert stats["total_after"] == 3
    board = wa.load_board(docs)
    assert len(board) == 3
    remaining_addrs = {li.street_address for li in board}
    assert remaining_addrs == {"2 Main St", "4 Main St", "6 Main St"}


def test_untouched_rows_are_byte_for_byte_unchanged_and_order_preserved(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    before = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(before[2])

    stats = wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True

    after = json.loads((docs / "listings.json").read_text())
    assert len(after) == 4
    # rows 0, 1, 3, 4 (untouched) keep their original relative order, byte-identical
    assert after == [before[0], before[1], before[3], before[4]]


# ===========================================================================
# 2. input validation (no I/O -- refused before the board is touched)
# ===========================================================================

def test_repeated_hash_raises_value_error(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    with pytest.raises(ValueError, match="more than once"):
        wa.delete_rows(["h1", "h1"], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


# ===========================================================================
# 3. board-state mismatches -- refuse the WHOLE call, nothing written
# ===========================================================================

def test_hash_not_found_refuses_and_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    with pytest.raises(wa.BoardDeleteMismatch, match="not found"):
        wa.delete_rows(["no-such-row-hash"], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


def test_one_bad_hash_among_good_ones_refuses_the_whole_batch(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=4)
    rows = json.loads((docs / "listings.json").read_text())
    good = [wa.row_identity_hash(rows[0]), wa.row_identity_hash(rows[1])]
    before = (docs / "listings.json").read_bytes()
    with pytest.raises(wa.BoardDeleteMismatch):
        wa.delete_rows(good + ["stale-hash"], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


def test_hash_matching_more_than_one_row_refuses_and_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    # Two rows identical across every _MERGE_HASH_FIELDS field -- a genuine, if contrived,
    # ambiguous case delete_rows() must refuse rather than guess which physical row was meant.
    a = _lead(0, street_address="1 Twin St", source="dup_src", source_url="https://x.test/dup")
    b = _lead(1, street_address="1 Twin St", source="dup_src", source_url="https://x.test/dup")
    other = _lead(2, street_address="9 Untouched Ln")
    wa.write_artifact([a, b, other], {"notes": "seed"}, docs_dir=docs)
    rows = json.loads((docs / "listings.json").read_text())
    key = wa.row_identity_hash(rows[0])
    assert key == wa.row_identity_hash(rows[1])

    before = (docs / "listings.json").read_bytes()
    with pytest.raises(wa.BoardDeleteMismatch, match="more than one row"):
        wa.delete_rows([key], {"notes": "t"}, docs_dir=docs)
    assert (docs / "listings.json").read_bytes() == before


# ===========================================================================
# 4. contracts: lock, manifest, size ceiling, high-water rebase
# ===========================================================================

def test_refuses_the_live_board_without_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    with pytest.raises(wa.BoardLockNotHeld):
        wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)


def test_succeeds_under_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    with wa.board_lock(live, owner="t"):
        stats = wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_manifest_verifies_after_a_delete(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    result = wa.verify_manifest(docs)
    assert result["ok"] is True, result["problems"]
    assert result["count"] == 4


def test_delete_size_state_is_ok_for_a_small_board(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    st = wa.board_delete_size_state(docs)
    assert st["ok"] is True


def test_delete_refuses_over_its_own_ceiling(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    monkeypatch.setenv("BOARD_DELETE_MAX_SOURCE_MB", "0.0001")
    with pytest.raises(wa.BoardLoadTooLarge) as ei:
        wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert "over the 0 MB ceiling" in str(ei.value)


def test_delete_allow_large_overrides_the_ceiling_for_one_run(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    monkeypatch.setenv("BOARD_DELETE_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_DELETE_ALLOW_LARGE", "1")
    stats = wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_delete_ceiling_is_independent_of_the_other_four_ceilings(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    monkeypatch.setenv("BOARD_LOAD_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_APPEND_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_MERGE_MAX_SOURCE_MB", "0.0001")
    stats = wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_high_water_mark_rebases_down_by_the_deleted_amount(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=3)
    hw_before = json.loads((docs / "board_highwater.json").read_text())["count"]
    assert hw_before == 3

    rows = json.loads((docs / "listings.json").read_text())
    h = wa.row_identity_hash(rows[0])
    stats = wa.delete_rows([h], {"notes": "t"}, docs_dir=docs)
    assert stats["total_after"] == 2

    hw_after = json.loads((docs / "board_highwater.json").read_text())
    assert hw_after["count"] == 2
    assert hw_after.get("rebased_from") == 3


# ===========================================================================
# 5. edge cases
# ===========================================================================

def test_empty_hashes_is_a_no_op_and_touches_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    stats = wa.delete_rows([], {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": None, "requested": 0, "matched": 0, "deleted": 0,
                     "not_found": 0, "written": False, "total_after": None}
    assert (docs / "listings.json").read_bytes() == before


def test_deleting_from_a_board_that_does_not_exist_yet_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    stats = wa.delete_rows(["h1", "h2"], {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": 0, "requested": 2, "matched": 0, "deleted": 0,
                     "not_found": 2, "written": False, "total_after": 0}
    assert not (docs / "listings.json").exists()
