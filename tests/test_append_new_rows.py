"""append_new_rows() (task_0658b33b, follow-up to audit O13's streaming load_board() fix).

The problem: load_board()/write_artifact() re-validates and re-serializes EVERY row on the
board, which is right for a full rescrape but wrong for "scrape a handful of new listings, check
they are not already on the board, add them" -- run_scoped_scrapers.py --apply's real use case.
append_new_rows() streams the existing board through as opaque, already-published rows (never
Listing.model_validate()d, never held as a full parsed-dict list either -- see its docstring and
BOARD_APPEND_MAX_SOURCE_MB's comment in web_artifact.py) and appends only the new, already-
validated Listing objects.

Covers, in order:
  1. correctness: dedupe (parcel/case/address signatures, exact and via dedupe_key), additive-
     only (existing rows' content is byte-for-byte unchanged), lazy-detail sidecar preserved for
     existing rows AND correctly split out for new rows that carry vision/comps of their own
  2. drop-rate / count-guard: append_new_rows shares write_artifact's exact
     _count_guard_and_backup, so a run that would otherwise look like an unexplained board
     shrink still refuses (it never legitimately should, since this is additive-only, but the
     guard must still be wired through correctly)
  3. contracts: board lock enforcement, the manifest verifies after a write, load_board() reads
     the result back correctly, the append-only size ceiling and its override
  4. the empty/no-op and bootstrap (first-ever board) edge cases
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               parcel_id=f"P{i}", street_address=f"{i} Main St",
               raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i} Elm St"}],
                    "vision": {"parsed": True}})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Mirrors test_board_integrity.py's fixture: tmp/docs is 'the live board' for lock
    enforcement purposes, tmp/logs/.board.lock its lock."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(wa, "_live_docs_dir", lambda: docs)
    for var in (wa.BOARD_LOCK_ENV, wa.BOARD_LOCK_TOKEN_ENV):
        monkeypatch.delenv(var, raising=False)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return tmp_path


def _seed(docs: Path, n: int = 5) -> None:
    wa.write_artifact([_lead(i) for i in range(n)], {"notes": "seed"}, docs_dir=docs)


# ===========================================================================
# 1. correctness: dedupe, additive-only, sidecar handling
# ===========================================================================

def test_genuinely_new_row_is_added_and_matching_row_is_skipped(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    new = _lead(100)               # genuinely new parcel
    dup = _lead(2)                 # same parcel as an existing seeded row
    stats = wa.append_new_rows([new, dup], {"notes": "t"}, docs_dir=docs)

    assert stats["written"] is True
    assert stats["existing"] == 5
    assert stats["added"] == 1
    assert stats["already_on_board"] == 1
    assert stats["total_after"] == 6
    assert stats["skipped_by_source"] == {dup.source: 1}
    assert stats["added_by_source"] == {new.source: 1}

    rows = wa.load_board(docs)
    assert len(rows) == 6
    assert sorted(li.parcel_id for li in rows) == ["P0", "P1", "P100", "P2", "P3", "P4"]


def test_dedupe_falls_back_to_dedupe_key_url_match_when_no_strong_signature_exists(tmp_path):
    """dedupe.py's _strong_sigs() never includes a source_url signature (only parcel,
    case+address, address+zip, canonical street+county) -- Listing.dedupe_key()'s URL fallback
    is what catches a duplicate that has NEITHER a parcel NOR an address NOR a case_number, only
    a shared source_url. append_new_rows() must check both, not just _strong_sigs()."""
    docs = tmp_path / "docs"
    seed = [_lead(0, parcel_id=None, case_number=None, street_address=None,
                  source_url="https://example.test/shared-notice")]
    wa.write_artifact(seed, {"notes": "seed"}, docs_dir=docs)
    dup = _lead(1, parcel_id=None, case_number=None, street_address=None,
               source_url="https://example.test/shared-notice")
    stats = wa.append_new_rows([dup], {"notes": "t"}, docs_dir=docs)
    assert stats["added"] == 0
    assert stats["already_on_board"] == 1


def test_dedupe_matches_by_case_and_address_not_just_parcel(tmp_path):
    docs = tmp_path / "docs"
    seed = [_lead(0, parcel_id=None, case_number="24CVS100", street_address="9 Oak St")]
    wa.write_artifact(seed, {"notes": "seed"}, docs_dir=docs)
    # No parcel at all, but same case_number + county + address -- _strong_sigs' case signature.
    dup = _lead(1, parcel_id=None, case_number="24-CVS-100", street_address="9 Oak St")
    stats = wa.append_new_rows([dup], {"notes": "t"}, docs_dir=docs)
    assert stats["added"] == 0
    assert stats["already_on_board"] == 1
    assert stats["written"] is False   # nothing NEW to write


def test_existing_rows_are_byte_for_byte_unchanged(tmp_path):
    """Additive-only: appending must not alter a single byte of an existing row's published
    content (state/source/raw/etc.), even though every existing row is popped-and-reencoded to
    reproduce the split between listings.json and listings_detail.json."""
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    before = json.loads((docs / "listings.json").read_text())
    before_detail = json.loads((docs / "listings_detail.json").read_text())

    wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)

    after = json.loads((docs / "listings.json").read_text())
    after_detail = json.loads((docs / "listings_detail.json").read_text())
    assert after[:5] == before
    assert after_detail[:5] == before_detail
    assert len(after) == 6 and len(after_detail) == 6


def test_new_rows_own_lazy_detail_is_split_into_the_sidecar(tmp_path):
    """A new row that already carries vision/comps (e.g. pre-enriched before landing) must have
    those keys popped into listings_detail.json exactly like write_artifact does, not left
    sitting in listings.json."""
    docs = tmp_path / "docs"
    _seed(docs, n=2)
    new = _lead(100, raw={"grade": {"overall": "A"}, "vision": {"score": 9},
                          "comps": [{"addr": "1 New St"}]})
    wa.append_new_rows([new], {"notes": "t"}, docs_dir=docs)

    rows = wa.load_board(docs)
    r = next(li for li in rows if li.parcel_id == "P100")
    assert r.raw.get("vision") == {"score": 9}
    assert r.raw.get("comps") == [{"addr": "1 New St"}]

    # and NOT present in the slim listings.json directly (it must live only in the sidecar)
    plain = json.loads((docs / "listings.json").read_text())
    rec100 = next(r for r in plain if r["parcel_id"] == "P100")
    assert "vision" not in (rec100.get("raw") or {})
    assert "comps" not in (rec100.get("raw") or {})


def test_multiple_new_rows_added_in_one_call(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    fresh = [_lead(10), _lead(11), _lead(12)]
    stats = wa.append_new_rows(fresh, {"notes": "t"}, docs_dir=docs)
    assert stats["added"] == 3
    assert stats["total_after"] == 6
    assert wa.load_board(docs).__len__() == 6


def test_by_state_and_by_source_on_board_reflect_the_new_total(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=4)   # src.0, src.1, src.0, src.1
    wa.append_new_rows([_lead(50, source="brand_new_src")], {"notes": "t"}, docs_dir=docs)
    meta = json.loads((docs / "run_meta.json").read_text())
    assert meta["by_state"] == {"NC": 5}
    assert meta["by_source_on_board"]["brand_new_src"] == 1
    assert sum(meta["by_source_on_board"].values()) == 5


# ===========================================================================
# 2. drop-rate / count-guard wiring
# ===========================================================================

def test_count_guard_still_fires_through_append_new_rows(tmp_path, monkeypatch):
    """append_new_rows shares write_artifact's exact _count_guard_and_backup. This can only be
    provoked artificially here (append is additive, so total_after >= existing always) -- it
    exists to prove the SHARED guard is actually wired through, not bypassed."""
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    hw = docs / "board_highwater.json"
    hw.write_text(json.dumps({"count": 999}))   # poison the high-water mark far above reality
    with pytest.raises(RuntimeError, match="COUNT GUARD"):
        wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)


def test_count_guard_can_be_bypassed_with_the_existing_env_var(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    (docs / "board_highwater.json").write_text(json.dumps({"count": 999}))
    monkeypatch.setenv("BOARD_ALLOW_SHRINK", "1")
    stats = wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


# ===========================================================================
# 3. contracts: lock, manifest, size ceiling
# ===========================================================================

def test_refuses_the_live_board_without_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        _seed(docs, n=3)
    with pytest.raises(wa.BoardLockNotHeld):
        wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)


def test_succeeds_under_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        _seed(docs, n=3)
    with wa.board_lock(live, owner="t"):
        stats = wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_manifest_verifies_after_an_append(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    wa.append_new_rows([_lead(100), _lead(101)], {"notes": "t"}, docs_dir=docs)
    result = wa.verify_manifest(docs)
    assert result["ok"] is True, result["problems"]
    assert result["count"] == 7


def test_append_size_state_is_ok_for_a_small_board(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    st = wa.board_append_size_state(docs)
    assert st["ok"] is True


def test_append_refuses_over_its_own_ceiling(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    monkeypatch.setenv("BOARD_APPEND_MAX_SOURCE_MB", "0.0001")
    with pytest.raises(wa.BoardLoadTooLarge) as ei:
        wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)
    assert "over the 0 MB ceiling" in str(ei.value)


def test_append_allow_large_overrides_the_ceiling_for_one_run(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    monkeypatch.setenv("BOARD_APPEND_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_APPEND_ALLOW_LARGE", "1")
    stats = wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_append_ceiling_is_independent_of_loads_ceiling(tmp_path, monkeypatch):
    """BOARD_LOAD_MAX_SOURCE_MB must not gate append_new_rows -- they are deliberately separate
    ceilings (see BOARD_APPEND_MAX_SOURCE_MB's comment: append is measurably cheaper)."""
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    monkeypatch.setenv("BOARD_LOAD_MAX_SOURCE_MB", "0.0001")
    stats = wa.append_new_rows([_lead(100)], {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


# ===========================================================================
# 4. empty / bootstrap edge cases
# ===========================================================================

def test_empty_new_listings_is_a_no_op_and_touches_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    stats = wa.append_new_rows([], {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": None, "candidates": 0, "added": 0, "already_on_board": 0,
                     "added_by_source": {}, "skipped_by_source": {}, "written": False,
                     "total_after": None}
    assert (docs / "listings.json").read_bytes() == before


def test_bootstrap_onto_an_empty_board(tmp_path):
    """No listings.json/run_meta.json exists yet -- the very first write. append_new_rows must
    work here too (a fresh publish), not assume a board already exists."""
    docs = tmp_path / "docs"
    docs.mkdir()
    stats = wa.append_new_rows([_lead(0), _lead(1)], {"notes": "first ever"}, docs_dir=docs)
    assert stats["existing"] == 0
    assert stats["added"] == 2
    assert stats["total_after"] == 2
    rows = wa.load_board(docs)
    assert len(rows) == 2


def test_all_candidates_already_on_board_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    stats = wa.append_new_rows([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=docs)
    assert stats["added"] == 0
    assert stats["already_on_board"] == 2
    assert stats["written"] is False
    # nothing was rewritten -- board_highwater.json should not have been touched
    assert not (docs / "board_highwater.json").exists() or json.loads(
        (docs / "board_highwater.json").read_text())["count"] == 3
