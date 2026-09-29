"""patch_existing_rows() (follow-up to append_new_rows()/task_0658b33b, 2026-09-29).

The problem: append_new_rows() solved "add a handful of NEW rows" without load_board()'s full
materialization, but left a gap -- a script that needs to MUTATE a small, known SUBSET of
EXISTING rows (not add, not remove) still had to fall back to load_board()/write_artifact(),
exactly the double materialization now refused on this board's real size.
scripts/resolver_backfill_parcel.py is the concrete, currently-blocked caller: it resolves a
parcel_id for ~1,000-1,500 leads per run and needs to land just those onto the board.

patch_existing_rows() streams the existing board through _iter_board_records() (never
Listing.model_validate()d, never held as a full parsed-dict list) and, for each row, checks its
Listing.dedupe_key() against a small dict of pending patches; a match gets its field updates
applied directly to the raw dict (raw merged, not replaced) before the row is re-encoded and
passed through -- exactly like append_new_rows(), but mutating in place instead of skipping.

Covers, in order:
  1. correctness: a matching row is patched (top-level field + merged raw update), all other
     rows pass through byte-for-byte unchanged, the lazy-detail sidecar round-trips correctly
     for both patched and untouched rows
  2. identity matching: dedupe_key() match via address (no parcel yet -- the resolver's own
     case), no match leaves the row untouched and is reported not_found, a key matching more
     than one row patches all of them and is reported as a duplicate
  3. count-guard: patch_existing_rows's OWN stricter guard (exact match against the manifest's
     sealed record count) fires on ANY mismatch, not just the >10% shrink append_new_rows()
     tolerates; the shared backup-before-overwrite still runs
  4. contracts: board lock enforcement, the manifest verifies after a patch, the patch-only
     size ceiling and its override, independence from the load/append ceilings
  5. edge cases: empty patches dict, patching onto a board that does not exist yet, zero matches
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int, **kw) -> Listing:
    # House number is i+1, never i: web_artifact._is_valid_street_address() (correctly) treats
    # a leading "0 " as a "no house number assigned" GIS sentinel (_PLACEHOLDER_HOUSE_NUM_RE)
    # and nulls street_address in the PUBLISHED record, which would silently break every
    # address-branch dedupe_key() match in these tests for i == 0.
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               parcel_id=None, street_address=f"{i + 1} Main St", zip_code="28052",
               raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i + 1} Elm St"}],
                    "vision": {"parsed": True}})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Mirrors test_append_new_rows.py's fixture: tmp/docs is 'the live board' for lock
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


# ===========================================================================
# 1. correctness: patch applied, everything else byte-for-byte unchanged
# ===========================================================================

def test_matching_row_is_patched_top_level_field_and_merged_raw(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    target = seed[2]
    patches = {target.dedupe_key(): {
        "parcel_id": "P999",
        "raw": {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.1, "lng": -81.2}},
    }}
    stats = wa.patch_existing_rows(patches, {"notes": "t"}, docs_dir=docs)

    assert stats["written"] is True
    assert stats["existing"] == 5
    assert stats["matched"] == 1
    assert stats["applied"] == 1
    assert stats["not_found"] == 0
    assert stats["total_after"] == 5

    rows = wa.load_board(docs)
    assert len(rows) == 5
    r = next(li for li in rows if li.street_address == target.street_address)
    assert r.parcel_id == "P999"
    assert r.raw.get("parcel_from_geo") == {"source": "nc_onemap_point", "lat": 35.1, "lng": -81.2}
    # pre-existing raw content must survive the merge, not be clobbered
    assert r.raw.get("grade") == {"overall": "B"}
    assert r.raw.get("comps") == target.raw["comps"]
    assert r.raw.get("vision") == {"parsed": True}


def test_unmatched_rows_are_byte_for_byte_unchanged(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    before = json.loads((docs / "listings.json").read_text())
    before_detail = json.loads((docs / "listings_detail.json").read_text())

    target = seed[2]
    wa.patch_existing_rows({target.dedupe_key(): {"parcel_id": "P999"}}, {"notes": "t"},
                           docs_dir=docs)

    after = json.loads((docs / "listings.json").read_text())
    after_detail = json.loads((docs / "listings_detail.json").read_text())
    assert len(after) == 5 and len(after_detail) == 5
    for i in range(5):
        if i == 2:
            continue
        assert after[i] == before[i]
        assert after_detail[i] == before_detail[i]
    assert after[2] != before[2]
    assert after[2]["parcel_id"] == "P999"


def test_lazy_detail_sidecar_round_trips_for_patched_row(tmp_path):
    """A patch that sets a LAZY_DETAIL_KEYS field (e.g. comps) via raw must land in the
    sidecar, not in listings.json directly -- the same split write_artifact()/
    append_new_rows() already enforce."""
    docs = tmp_path / "docs"
    seed = _seed(docs, n=3)
    target = seed[0]
    wa.patch_existing_rows(
        {target.dedupe_key(): {"raw": {"comps": [{"addr": "NEW COMP"}]}}},
        {"notes": "t"}, docs_dir=docs)

    rows = wa.load_board(docs)
    r = next(li for li in rows if li.street_address == target.street_address)
    assert r.raw.get("comps") == [{"addr": "NEW COMP"}]

    plain = json.loads((docs / "listings.json").read_text())
    rec0 = next(r for r in plain if r["street_address"] == target.street_address)
    assert "comps" not in (rec0.get("raw") or {})


def test_multiple_patches_in_one_call(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    patches = {seed[i].dedupe_key(): {"parcel_id": f"P{i}00"} for i in (0, 1, 3)}
    stats = wa.patch_existing_rows(patches, {"notes": "t"}, docs_dir=docs)
    assert stats["matched"] == 3
    assert stats["applied"] == 3
    assert stats["total_after"] == 5

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li.parcel_id for li in rows}
    assert by_addr[seed[0].street_address] == "P000"
    assert by_addr[seed[1].street_address] == "P100"
    assert by_addr[seed[3].street_address] == "P300"
    assert by_addr[seed[2].street_address] is None
    assert by_addr[seed[4].street_address] is None


def test_by_state_and_by_source_on_board_reflect_the_patched_values(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=4)
    target = seed[0]
    wa.patch_existing_rows({target.dedupe_key(): {"state": "SC"}}, {"notes": "t"}, docs_dir=docs)
    meta = json.loads((docs / "run_meta.json").read_text())
    assert meta["by_state"] == {"NC": 3, "SC": 1}
    assert sum(meta["by_source_on_board"].values()) == 4


# ===========================================================================
# 2. identity matching
# ===========================================================================

def test_matches_by_dedupe_key_address_branch_when_no_parcel_exists_yet(tmp_path):
    """The resolver_backfill_parcel.py use case: a lead with no parcel_id yet, matched by its
    address+zip dedupe_key() branch (exactly what Listing.dedupe_key() falls back to)."""
    docs = tmp_path / "docs"
    seed = [_lead(0, parcel_id=None, street_address="42 Oak St", zip_code="28052")]
    wa.write_artifact(seed, {"notes": "seed"}, docs_dir=docs)
    key = seed[0].dedupe_key()
    assert key.startswith("addr:")
    stats = wa.patch_existing_rows({key: {"parcel_id": "P42"}}, {"notes": "t"}, docs_dir=docs)
    assert stats["applied"] == 1
    rows = wa.load_board(docs)
    assert rows[0].parcel_id == "P42"


def test_no_match_is_reported_not_found_and_touches_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    stats = wa.patch_existing_rows({"addr:9999 nowhere st|00000": {"parcel_id": "PX"}},
                                   {"notes": "t"}, docs_dir=docs)
    assert stats["matched"] == 0
    assert stats["applied"] == 0
    assert stats["not_found"] == 1
    assert stats["written"] is False
    assert (docs / "listings.json").read_bytes() == before


def test_key_matching_more_than_one_row_patches_all_and_is_flagged_duplicate(tmp_path):
    """A dedupe_key() shared by two on-board rows (the board already has a duplicate under
    that key -- dedupe()'s own job is to prevent this, but patch_existing_rows must not
    silently patch only one of them or crash)."""
    docs = tmp_path / "docs"
    # Two rows with the SAME address+zip (and no parcel) share one dedupe_key().
    seed = [_lead(0, parcel_id=None, street_address="7 Shared St", zip_code="28052",
                 source="src.a"),
            _lead(1, parcel_id=None, street_address="7 Shared St", zip_code="28052",
                 source="src.b")]
    wa.write_artifact(seed, {"notes": "seed"}, docs_dir=docs)
    key = seed[0].dedupe_key()
    assert key == seed[1].dedupe_key()

    stats = wa.patch_existing_rows({key: {"parcel_id": "P7"}}, {"notes": "t"}, docs_dir=docs)
    assert stats["matched"] == 1          # one PATCH KEY matched
    assert stats["applied"] == 2          # but it hit two rows
    assert stats["duplicate_key_matches"] == 1

    rows = wa.load_board(docs)
    assert all(li.parcel_id == "P7" for li in rows)


# ===========================================================================
# 3. count-guard: stricter than append_new_rows()'s
# ===========================================================================

def test_count_mismatch_against_the_manifest_raises_before_writing(tmp_path):
    """A 1-row-out-of-20 mismatch (5%) is well under append_new_rows()'s 10% shrink tolerance
    -- proving patch_existing_rows()'s guard is a genuinely STRICTER, exact-equality check, not
    just a re-use of the loose one. Provoked by hand-editing the manifest's recorded count for
    listings.json, the same way a torn write or a stale manifest would."""
    docs = tmp_path / "docs"
    seed = _seed(docs, n=20)
    manifest_path = docs / wa.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["listings.json"]["records"] = 19   # poison: board has 20, manifest says 19
    manifest_path.write_text(json.dumps(manifest))

    target = seed[0]
    with pytest.raises(wa.BoardPatchCountMismatch, match="19"):
        wa.patch_existing_rows({target.dedupe_key(): {"parcel_id": "PX"}}, {"notes": "t"},
                               docs_dir=docs)
    # nothing was written
    assert json.loads((docs / "listings.json").read_text())[0]["parcel_id"] is None


def test_backup_still_runs_even_though_the_shrink_check_is_a_no_op(tmp_path):
    """_count_guard_and_backup is still shared for its backup-before-overwrite side effect --
    the shrink check inside it is a no-op here (patch never changes the count), but the backup
    must still happen."""
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}}, {"notes": "t"},
                           docs_dir=docs)
    backups = list((docs.parent / "backups").glob("listings_*.json"))
    assert len(backups) >= 1


# ===========================================================================
# 4. contracts: lock, manifest, size ceiling
# ===========================================================================

def test_refuses_the_live_board_without_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    with pytest.raises(wa.BoardLockNotHeld):
        wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}}, {"notes": "t"},
                               docs_dir=docs)


def test_succeeds_under_the_lock(live):
    docs = live / "docs"
    with wa.board_lock(live, owner="seed"):
        seed = _seed(docs, n=3)
    with wa.board_lock(live, owner="t"):
        stats = wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}},
                                       {"notes": "t"}, docs_dir=docs)
    assert stats["written"] is True


def test_manifest_verifies_after_a_patch(tmp_path):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"},
                           seed[1].dedupe_key(): {"parcel_id": "P1"}},
                          {"notes": "t"}, docs_dir=docs)
    result = wa.verify_manifest(docs)
    assert result["ok"] is True, result["problems"]
    assert result["count"] == 5


def test_patch_size_state_is_ok_for_a_small_board(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=5)
    st = wa.board_patch_size_state(docs)
    assert st["ok"] is True


def test_patch_refuses_over_its_own_ceiling(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0.0001")
    with pytest.raises(wa.BoardLoadTooLarge) as ei:
        wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}}, {"notes": "t"},
                               docs_dir=docs)
    assert "over the 0 MB ceiling" in str(ei.value)


def test_patch_allow_large_overrides_the_ceiling_for_one_run(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_PATCH_ALLOW_LARGE", "1")
    stats = wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}}, {"notes": "t"},
                                   docs_dir=docs)
    assert stats["written"] is True


def test_patch_ceiling_is_independent_of_load_and_append_ceilings(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seed = _seed(docs, n=5)
    monkeypatch.setenv("BOARD_LOAD_MAX_SOURCE_MB", "0.0001")
    monkeypatch.setenv("BOARD_APPEND_MAX_SOURCE_MB", "0.0001")
    stats = wa.patch_existing_rows({seed[0].dedupe_key(): {"parcel_id": "P0"}}, {"notes": "t"},
                                   docs_dir=docs)
    assert stats["written"] is True


# ===========================================================================
# 5. edge cases
# ===========================================================================

def test_empty_patches_is_a_no_op_and_touches_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    before = (docs / "listings.json").read_bytes()
    stats = wa.patch_existing_rows({}, {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": None, "patches": 0, "matched": 0, "applied": 0,
                     "not_found": 0, "duplicate_key_matches": 0, "written": False,
                     "total_after": None}
    assert (docs / "listings.json").read_bytes() == before


def test_patching_a_board_that_does_not_exist_yet_reports_not_found_and_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    stats = wa.patch_existing_rows({"addr:1 nowhere st|00000": {"parcel_id": "PX"}},
                                   {"notes": "t"}, docs_dir=docs)
    assert stats == {"existing": 0, "patches": 1, "matched": 0, "applied": 0, "not_found": 1,
                     "duplicate_key_matches": 0, "written": False, "total_after": 0}
    assert not (docs / "listings.json").exists()


def test_all_patches_unmatched_writes_nothing(tmp_path):
    docs = tmp_path / "docs"
    _seed(docs, n=3)
    stats = wa.patch_existing_rows({"addr:nope|00000": {"parcel_id": "PX"},
                                   "addr:also nope|00000": {"parcel_id": "PY"}},
                                  {"notes": "t"}, docs_dir=docs)
    assert stats["applied"] == 0
    assert stats["not_found"] == 2
    assert stats["written"] is False
    assert not (docs.parent / "backups").exists() or not list(
        (docs.parent / "backups").glob("listings_*.json"))
