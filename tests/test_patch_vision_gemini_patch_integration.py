"""scripts/patch_vision_gemini.py's board-I/O rewrite (2026-09-30): it used to call
load_board() to build its full-board `listings` list, run vision + recompute calc/grade "onto
every lead", then write_artifact(listings, ...) -- exactly the double materialization
BOARD_LOAD_MAX_SOURCE_MB / read_board_records() now refuse on the real ~217K-row board, which is
what left this script BLOCKED (failing every scheduled 09:30 run). This test proves the new
streaming read (web_artifact._iter_board_records(), sidecar merged) + cheap photo pre-filter +
bounded-candidate vision pass + web_artifact.patch_existing_rows() write reproduces the original
contract -- without ever calling load_board()/write_artifact(), and without any real vision
network call (enrichment_vision.enrich_with_vision is replaced with a small fake).

Covers:
  1. _collect_candidates() finds exactly the rows needing vision AND having a real photo --
     skipping already-scored rows, ollama-quality rows are INCLUDED (upgrade candidates), and
     no-photo rows are excluded even though they technically "need" vision.
  2. main() end-to-end: a row the fake vision pass scores lands its vision/condition_tier/
     calc/grade on the board via patch_existing_rows(); a row the fake pass leaves untouched
     (simulating a wall-clock/cap cutoff) is NOT patched at all (proving the object-identity
     touched-detection actually scopes the patch, not just "every candidate").
  3. VISION_INCLUDE_NO_PHOTO=1 is refused cleanly (rc=3) rather than silently running a
     truncated pass.
  4. Rows outside the candidate filter (already vision-scored, or un-scored with no photo) are
     completely untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import patch_vision_gemini as pvg  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

REAL_IMAGE = {"images": {"real": ["https://example.test/photo.jpg"]}}


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               street_address=f"{i + 1} Main St", zip_code="28052", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0, raw={**REAL_IMAGE}),                                             # target: scored this run
        _row(1, raw={**REAL_IMAGE}),                                             # target: NOT reached this run
        _row(2, raw={"vision": {"_provider": "anthropic", "condition_tier": "C3"}}),  # already properly scored
        _row(3, raw={"vision": {"_provider": "ollama", "condition_tier": "C4"}, **REAL_IMAGE}),  # upgrade candidate
        _row(4, raw={}),                                                         # un-scored, NO photo -> excluded
    ]
    wa.write_artifact(rows, {"notes": "patch_vision_gemini integration seed"}, docs_dir=docs)
    return rows


async def _fake_enrich_scores_first_only(listings, max_listings=None):
    """Mimics enrich_with_vision()'s exact contract (mutate in place, return None) without any
    network/model call: scores only the FIRST listing in the list it's handed (simulating a
    wall-clock cutoff that stops mid-batch), leaving the rest completely untouched -- so both the
    'patched' and 'left alone' outcomes are exercised in one run."""
    if not listings:
        return
    li = listings[0]
    li.raw["vision"] = {"_provider": "gemini", "condition_tier": "C2", "confidence": "HIGH"}
    li.raw["condition_tier"] = "C2"
    li.raw["condition_source"] = "vision-HIGH"


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(pvg, "REPO", repo)
    monkeypatch.setattr(pvg, "DOCS", repo / "docs")
    monkeypatch.setattr(pvg, "enrich_with_vision", _fake_enrich_scores_first_only)
    monkeypatch.setenv("PATCH_PUBLISH", "0")
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")  # unlimited -> no hard_cap wait_for wrapper
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_collect_candidates_finds_exactly_the_scoreable_rows(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    candidates, total_rows, unscored_total = pvg._collect_candidates(docs)
    assert total_rows == 5
    # seed[2] (properly scored) is not un-scored at all; seed[4] is un-scored but has no photo
    assert unscored_total == 4  # seed[0], seed[1], seed[3], seed[4]
    assert {li.street_address for li in candidates} == {
        seed[0].street_address, seed[1].street_address, seed[3].street_address,
    }


def test_main_patches_only_the_row_the_fake_pass_actually_touched(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    rc = pvg.main()
    assert rc == 0

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li for li in rows}

    # scored this run (fake touches listings[0] of the candidate list -- board order, so seed[0])
    scored = by_addr[seed[0].street_address]
    assert scored.raw["vision"]["_provider"] == "gemini"
    assert scored.raw["condition_tier"] == "C2"
    assert "calc" in scored.raw and "grade" in scored.raw  # recomputed for the touched row

    # a candidate the fake pass did NOT reach this run must be completely untouched -- no vision,
    # no calc/grade either (proving the patch is scoped to `touched`, not all `candidates`)
    unreached = by_addr[seed[1].street_address]
    assert "vision" not in unreached.raw
    assert "calc" not in unreached.raw
    assert "grade" not in unreached.raw

    # already-properly-scored row untouched
    assert by_addr[seed[2].street_address].raw["vision"]["_provider"] == "anthropic"
    # ollama upgrade candidate NOT reached this run (fake only touches the first candidate)
    assert by_addr[seed[3].street_address].raw["vision"]["_provider"] == "ollama"
    # no-photo un-scored row was never even a candidate
    assert "vision" not in by_addr[seed[4].street_address].raw


def test_vision_include_no_photo_is_refused(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    before = (docs / "listings.json").read_bytes()
    monkeypatch.setenv("VISION_INCLUDE_NO_PHOTO", "1")
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    rc = pvg.main()
    assert rc == 3
    assert (docs / "listings.json").read_bytes() == before  # refused before touching the board


def test_nothing_to_patch_when_no_candidates(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    # board with nothing needing vision or nothing with a photo
    rows = [_row(0, raw={"vision": {"_provider": "anthropic"}}), _row(1, raw={})]
    wa.write_artifact(rows, {"notes": "seed"}, docs_dir=docs)
    before = (docs / "listings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    async def _never_called(listings, max_listings=None):
        assert not listings
    monkeypatch.setattr(pvg, "enrich_with_vision", _never_called)

    rc = pvg.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before


# --- pending-patch cache (2026-10-01 fix for the BoardLoadTooLarge data-loss bug) ------------
#
# Confirmed live on 2026-10-01 09:30: patch_existing_rows() computed 27 real vision reports
# (API quota genuinely spent), then raised BoardLoadTooLarge before writing anything because the
# real board is over BOARD_PATCH_MAX_SOURCE_MB -- the exception propagated out of main()
# uncaught and all 27 results were discarded. These tests cover the fix: cache on failure,
# skip re-scoring what's already cached, and drain + clear the cache on a later success.


def test_cache_round_trip(tmp_path):
    repo = tmp_path / "repo2"
    assert pvg._load_pending_cache(repo) == {}  # missing file -> empty, never raises

    patches = {"k1": {"raw": {"vision": {"_provider": "gemini"}}}}
    pvg._save_pending_cache(repo, patches)
    path = pvg._pending_cache_path(repo)
    assert path.exists()
    assert pvg._load_pending_cache(repo) == patches

    pvg._clear_pending_cache(repo)
    assert not path.exists()
    assert pvg._load_pending_cache(repo) == {}  # still safe after clearing
    pvg._clear_pending_cache(repo)  # clearing an already-absent cache must not raise


def test_corrupt_cache_file_is_treated_as_empty(tmp_path):
    repo = tmp_path / "repo3"
    path = pvg._pending_cache_path(repo)
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json")
    assert pvg._load_pending_cache(repo) == {}


def test_board_too_large_caches_computed_patches_instead_of_losing_them(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    before = (docs / "listings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    def _raise_too_large(patches, summary, docs_dir):
        raise wa.BoardLoadTooLarge("board source is 9999 MB, over the 2300 MB ceiling")
    monkeypatch.setattr(pvg, "patch_existing_rows", _raise_too_large)

    rc = pvg.main()
    assert rc == 2
    # the refusal happens inside patch_existing_rows(), before it writes anything
    assert (docs / "listings.json").read_bytes() == before

    cache = pvg._load_pending_cache(scratch_repo)
    assert len(cache) == 1  # only seed[0] was actually scored by the fake pass
    key = seed[0].dedupe_key()
    assert key in cache
    assert cache[key]["raw"]["vision"]["_provider"] == "gemini"
    assert "calc" in cache[key]["raw"] and "grade" in cache[key]["raw"]


def test_cached_candidate_is_not_rescored_and_drains_on_next_success(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)

    # Pre-seed the cache as if a PRIOR run already vision-scored seed[1] (the "NOT reached this
    # run" row in _seed_board) but could not persist it.
    cached_raw = {
        "vision": {"_provider": "gemini", "condition_tier": "C4", "confidence": "HIGH"},
        "condition_tier": "C4", "condition_source": "vision-HIGH",
        "calc": {"arv_expected": 123456}, "grade": {"overall": "B"},
    }
    pvg._save_pending_cache(scratch_repo, {seed[1].dedupe_key(): {"raw": cached_raw}})

    seen_addresses: list[str] = []

    async def _fake_enrich_records_then_scores_first(listings, max_listings=None):
        seen_addresses.extend(li.street_address for li in listings)
        if listings:
            li = listings[0]
            li.raw["vision"] = {"_provider": "gemini", "condition_tier": "C2", "confidence": "HIGH"}
            li.raw["condition_tier"] = "C2"
            li.raw["condition_source"] = "vision-HIGH"
    monkeypatch.setattr(pvg, "enrich_with_vision", _fake_enrich_records_then_scores_first)
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    rc = pvg.main()
    assert rc == 0

    # seed[1] already had a cached result -- it must NOT have been handed to the vision pass
    # again (that would mean re-spending API quota on a row already scored).
    assert seed[1].street_address not in seen_addresses
    assert seed[0].street_address in seen_addresses  # the only remaining un-cached candidate

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li for li in rows}
    # the cached-from-a-prior-run patch landed on the board this run, via the merge into
    # combined_patches, even though seed[1] was never touched by THIS run's vision pass
    assert by_addr[seed[1].street_address].raw["vision"]["_provider"] == "gemini"
    assert by_addr[seed[1].street_address].raw["vision"]["condition_tier"] == "C4"
    assert by_addr[seed[1].street_address].raw["calc"]["arv_expected"] == 123456
    # this run's own fresh pass also landed normally
    assert by_addr[seed[0].street_address].raw["vision"]["condition_tier"] == "C2"

    # the write succeeded, so the cache that fed it must be cleared -- nothing left to drain
    assert pvg._load_pending_cache(scratch_repo) == {}
