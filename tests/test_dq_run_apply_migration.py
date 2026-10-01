"""_dq_common.run_apply()'s 2026-10-01 board-I/O migration off load_board()/write_artifact()
(docs/HANDOFF.md item 21/22): it now builds its working set from board_stream.iter_board_rows()
(no lazy-detail sidecar) instead of load_board(), and lands the result via
web_artifact.patch_existing_rows() (only the rows apply_fn actually changed) instead of a
whole-board write_artifact(). apply_rows() itself is UNCHANGED in every dependent script --
these tests exercise the SHARED harness end-to-end (seed a tiny board, call the real `_apply()`
entry point, read the board back), not the per-row logic the existing test_dq_*.py /
test_dq_apply_rows_contract.py files already cover directly.

Covers:
  1. The simplest caller (fix_county_mc_mac_casing, no raw keys) round-trips through the real
     board on disk.
  2. quarantine_flip_leaks's self-correcting "stamp cleared" removal of raw['scope'] -- the one
     raw-key deletion among the 7 migrated callers -- survives the patch_existing_rows() write
     (_RAW_DELETE_SAFE_AS_NONE).
  3. map_account_ids_to_parcels mutates a raw SUB-dict in place (raw['qpaybill_roll'][...] = ...)
     rather than reassigning raw itself -- proving _snapshot_rows()'s deep copy (not a shallow
     one) is what makes that change visible to the diff.
  4. undo_resolver_middle_conflicts and repair_parcel_from_address -- both blank raw['owner_mailing'],
     which mailing_shape.py presence-tests -- raise loudly instead of being silently migrated.
  5. The board-too-large-to-patch ceiling is checked BEFORE the expensive full-list read, not
     skipped by the new code path.
  6. Untouched rows are never sent to patch_existing_rows() at all (the write stays exactly as
     small as the real change).
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _dq_common as C  # noqa: E402
import fix_county_mc_mac_casing as FX  # noqa: E402
import map_account_ids_to_parcels as M  # noqa: E402
import quarantine_flip_leaks as Q  # noqa: E402
import undo_resolver_middle_conflicts as U  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


_counter = itertools.count()


def _li(**kw) -> Listing:
    # a fresh, monotonic counter -- NOT id(kw)/id(object()), which CPython can and does reuse
    # across short-lived objects in a tight loop, silently colliding "unique" source_urls.
    base = dict(source="counties_nc.x", source_url=f"https://example.invalid/{next(_counter)}",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Mcdowell", raw={})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(C, "REPO", repo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _seed(docs: Path, rows: list[Listing]) -> None:
    wa.write_artifact(rows, {"notes": "run_apply migration test seed"}, docs_dir=docs)


def _read_board(docs: Path) -> list[dict]:
    gz = docs / "listings.json.gz"
    plain = docs / "listings.json"
    from foreclosure_scraper.board_stream import iter_board_rows
    path = gz if gz.exists() else plain
    return list(iter_board_rows(path))


# ---- 1. simplest caller: no raw keys at all ------------------------------------------------
def test_fix_county_mc_mac_casing_round_trips_through_the_real_board(scratch_repo):
    docs = scratch_repo / "docs"
    rows = [_li(county="Mcdowell"), _li(county="Buncombe"), _li(county="Mccormick", state="SC")]
    _seed(docs, rows)

    rc = FX._apply()
    assert rc == 0

    board = _read_board(docs)
    assert len(board) == 3
    counties = sorted(r["county"] for r in board)
    assert counties == ["Buncombe", "McCormick", "McDowell"]


def test_fix_county_mc_mac_casing_is_idempotent(scratch_repo):
    docs = scratch_repo / "docs"
    _seed(docs, [_li(county="Mcdowell")])
    FX._apply()
    FX._apply()  # second run: nothing left to fix, must not error or touch anything else
    board = _read_board(docs)
    assert board[0]["county"] == "McDowell"


# ---- 2. the one raw-key DELETION among the safe callers ------------------------------------
def test_quarantine_flip_leaks_clears_a_stale_scope_stamp_via_patch(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    # avoid touching real parcel-cache sqlite files via backfill_missing_county.build_evidence()
    import backfill_missing_county as B
    monkeypatch.setattr(B, "cache_files", lambda: [])

    rows = [
        _li(listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Spartanburg",
            raw={"scope": Q.STAMP}),                      # now in footprint: stamp must clear
        _li(listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Charleston",
            raw={}),                                       # a genuine leak: must get stamped
    ]
    _seed(docs, rows)

    rc = Q._apply()
    assert rc == 0

    board = _read_board(docs)
    by_county = {r["county"]: r for r in board}
    # patch_existing_rows() can only MERGE raw sub-keys (dict.update()), never delete one, so a
    # removal lands as an explicit raw['scope']=None rather than the key being absent -- this is
    # _RAW_DELETE_SAFE_AS_NONE's one real case. Proven safe because the only consumer
    # (distress_score.py: `r.get("scope") == OUT_OF_FOOTPRINT`) treats None exactly like absent;
    # nothing in this codebase does a bare `"scope" in raw` presence test (verified by grep when
    # this was migrated). So the correctness bar is "not still reading as the stamp", not "the
    # key is gone from the dict" -- unlike owner_mailing (see the exclusion tests below), where a
    # real `"owner_mailing" in raw` presence test exists and None would NOT be equivalent.
    assert by_county["Spartanburg"]["raw"].get("scope") is None  # locks down the None mechanism
    assert by_county["Charleston"]["raw"]["scope"] == Q.STAMP

    # and the real scorer function agrees the Spartanburg row is no longer out-of-footprint
    from foreclosure_scraper.distress_score import flip_outside_footprint
    from foreclosure_scraper.models import Listing as L
    assert not flip_outside_footprint(L.model_validate(by_county["Spartanburg"]))
    assert flip_outside_footprint(L.model_validate(by_county["Charleston"]))


def test_quarantine_flip_leaks_leaves_untouched_rows_out_of_the_patch(scratch_repo, monkeypatch):
    """A row quarantine_flip_leaks.apply_rows() never looks at twice (not a flip at all) must
    never be sent to patch_existing_rows() -- i.e. the write stays exactly as small as the real
    change, same contract as every other board patch this week."""
    docs = scratch_repo / "docs"
    import backfill_missing_county as B
    monkeypatch.setattr(B, "cache_files", lambda: [])
    rows = [_li(listing_type=ListingType.TAX_LIEN, state="SC", county="Charleston", raw={})]
    _seed(docs, rows)

    calls = []
    real_patch = wa.patch_existing_rows

    def spy(patches, summary, docs_dir):
        calls.append(dict(patches))
        return real_patch(patches, summary, docs_dir=docs_dir)
    # run_apply() does `from foreclosure_scraper.web_artifact import ... patch_existing_rows`
    # INSIDE its own body, re-executed every call, so patching the attribute on the real module
    # before calling _apply() is picked up.
    monkeypatch.setattr(wa, "patch_existing_rows", spy)

    Q._apply()
    assert calls and calls[0] == {}, "a TAX_LIEN row is not a flip at all -- nothing to patch"


# ---- 3. a raw SUB-dict mutated in place, not reassigned ------------------------------------
def test_map_account_ids_to_parcels_sees_an_in_place_raw_subdict_mutation(scratch_repo, monkeypatch):
    monkeypatch.setattr(M, "_cache_fn", lambda: (lambda pid: None))
    docs = scratch_repo / "docs"
    rows = [_li(county="Laurens", state="SC", parcel_id="000789",
                raw={"qpaybill_roll": {"identification_no": "000789",
                                       "detail": {"map_number": "094-00-00-036.002"}}})]
    _seed(docs, rows)

    rc = M._apply()
    assert rc == 0

    board = _read_board(docs)
    row = board[0]
    assert row["parcel_id"] == "094-00-00-036.002"
    # qpaybill_roll is a SUB-dict of raw that apply_rows mutates with `q["is_account_id_not_parcel"]
    # = True` (in place) rather than replacing raw["qpaybill_roll"] outright -- only a DEEP
    # pre-mutation snapshot catches this; a shallow dict(li.raw) copy would have shared the same
    # nested object and shown no diff at all.
    assert row["raw"]["qpaybill_roll"]["is_account_id_not_parcel"] is True
    assert row["raw"]["qpaybill_roll"]["identification_no"] == "000789"


# ---- 4. the two excluded callers: loud refusal, not silent corruption ----------------------
def test_undo_resolver_middle_conflicts_refuses_rather_than_dropping_owner_mailing(scratch_repo):
    docs = scratch_repo / "docs"
    filler = [_li(source="counties_sc.sc_public_index", parcel_id=None, street_address=None,
                  state="SC", county="Spartanburg", raw={}) for _ in range(9)]
    resolved = _li(
        source="counties_sc.sc_public_index", state="SC", county="Spartanburg",
        parcel_id="712207947183", street_address="922 LOGAN ST SPARTANBURG",
        market_value=14600.0, living_sqft=1150.0, owner_name="EVANS DAVID N",
        defendant="David Lee Evans",
        raw={"resolved_from_name": {"queried": True, "confidence": "strong",
                                    "matched_owner": "EVANS DAVID N", "query_name": "David Lee Evans"},
             "gis": {"owner": "EVANS DAVID N"}, "owner_mailing": {"mailing": "1 X ST"}})
    rows = filler + [resolved]
    _seed(docs, rows)

    with pytest.raises(RuntimeError, match="owner_mailing"):
        U._apply()

    # and the board on disk is UNCHANGED -- the refusal happened before any write.
    board = _read_board(docs)
    assert len(board) == 10
    still = next(r for r in board if r["source_url"] == resolved.source_url)
    assert still["raw"]["owner_mailing"] == {"mailing": "1 X ST"}
    assert still["parcel_id"] == "712207947183"


def test_diff_raw_refuses_owner_mailing_removal_the_same_way_for_any_caller():
    """repair_parcel_from_address.py's apply_ops() pops raw['owner_mailing'] the same way
    undo_resolver_middle_conflicts.py does (scripts/repair_parcel_from_address.py:291-292) --
    both go through the SAME shared _diff_raw() guard inside run_apply(), proven end-to-end for
    undo_resolver_middle_conflicts above. Driving repair_parcel_from_address's own planner (it
    needs a real parcel cache to decide a withdrawal) is out of scope for this plumbing test, so
    this confirms the shared code path directly: the guard does not special-case which script
    triggered it, it reacts to the raw-key set difference alone."""
    before = {"owner_mailing": {"mailing": "1 X ST"}, "gis": {"owner": "EVANS DAVID N"}}
    after = {}  # both keys popped, exactly what repair_parcel_from_address.apply_ops() does
    with pytest.raises(RuntimeError, match="owner_mailing"):
        C._diff_raw(before, after, owner="repair_parcel_from_address")


# ---- 5. the ceiling guard fires before the expensive full-list read -----------------------
def test_board_too_large_refuses_before_building_the_working_set(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed(docs, [_li(county="Mcdowell")])
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0")  # any real board is "too large"
    called = []
    real_light_rows = C._light_rows

    def spy(d):
        called.append(True)
        return real_light_rows(d)
    monkeypatch.setattr(C, "_light_rows", spy)

    with pytest.raises(wa.BoardLoadTooLarge):
        FX._apply()
    assert not called, "the ceiling must be checked BEFORE the full-list read, not after"
