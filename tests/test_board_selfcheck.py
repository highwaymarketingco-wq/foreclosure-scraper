"""scripts/board_selfcheck.py — the current-board read, not the stale mobile payload.

THE BUG THIS COVERS (2026-09-30). append_new_rows()/patch_existing_rows() (2026-09-29,
commits 3272b3c0/758d0bb5) are now the write path for essentially all board landings on a
board too big for load_board()/write_artifact() to re-materialize, and both deliberately skip
regenerating docs/listings_slim.json.gz (see their own docstrings: doing so needs the
parsed-dict form of the WHOLE board, exactly the cost these functions exist to avoid).
board_selfcheck.py's `_current()` used to read that same listings_slim.json.gz for its
INVARIANT checks -- the file `board_selfcheck.py` was written to grade -- so every invariant
check run since the first append/patch landing was silently grading a board smaller and older
than the one actually published (confirmed live: 217,773 slim rows vs. 219,530 real rows,
commit ba3e57b3 is the slim file's last regeneration). A run that would have caught a fresh
defect in the un-slimmed rows could not have: it never saw them.

The fix: `_current()` now reads the real board through
foreclosure_scraper.board_stream.iter_board_rows(), the same memory-safe streaming reader
CLAUDE.md requires for board reads. `_previous()` (MOVEMENT only, never invariants) still
reads the committed listings_slim.json.gz via `git show` -- that is unaffected by this bug and
is the only single stable path the full parts-based board has ever had in git history (see
_previous()'s own docstring in the script).

This module loads scripts/board_selfcheck.py by file path (it is a script, not a package
module) via importlib, the same pattern tests/test_publish_plumbing.py uses for
check_pages_publish.py.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.board_stream import iter_board_rows
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _load_selfcheck():
    spec = importlib.util.spec_from_file_location(
        "board_selfcheck", SCRIPTS / "board_selfcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
                parcel_id=f"P{i}", street_address=f"{i} Main St",
                raw={"grade": {"overall": "B"}})
    base.update(kw)
    return Listing(**base)


# ===========================================================================
# 1. _current() reads the LIVE board, not the stale slim payload
# ===========================================================================

def test_current_reads_the_real_board_not_the_stale_slim_payload(tmp_path):
    """The exact scenario that shipped stale: write a 5-row board (slim regenerated
    to match), then append 3 more rows the way append_new_rows() does in production
    -- which by design leaves listings_slim.json.gz at 5. _current() must report 8,
    the real count, not 5."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)

    slim_before = json.loads(gzip.decompress((docs / "listings_slim.json.gz").read_bytes()))
    assert len(slim_before) == 5, "sanity: the seed write regenerated slim to match"

    stats = wa.append_new_rows([_lead(100), _lead(101), _lead(102)], {"notes": "t"},
                                docs_dir=docs)
    assert stats["written"] is True
    assert stats["total_after"] == 8

    # The documented, disclosed gap: append_new_rows() does NOT touch slim.
    slim_after = json.loads(gzip.decompress((docs / "listings_slim.json.gz").read_bytes()))
    assert len(slim_after) == 5, (
        "if this fails, append_new_rows() started regenerating slim and the "
        "board_selfcheck comments/tests describing it as stale need updating too"
    )

    mod = _load_selfcheck()
    mod.DOCS = docs
    current = mod._current()
    assert len(current) == 8, (
        "_current() read the stale slim payload (5) instead of the real board (8) -- "
        "this is the exact bug: every invariant check would silently run against an "
        "undercounted, out-of-date board"
    )
    # And it must be the SAME rows iter_board_rows() gives a caller directly -- not some
    # independent re-derivation that happens to agree on count.
    assert len(current) == len(list(iter_board_rows(docs / "listings.json.gz")))


def test_current_matches_slim_when_no_append_or_patch_has_happened(tmp_path):
    """Immediately after a full write_artifact() the two ARE the same size -- the bug only
    shows up once append_new_rows()/patch_existing_rows() runs. This pins the non-buggy case
    so a future change cannot "fix" the count by coincidence."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)
    mod = _load_selfcheck()
    mod.DOCS = docs
    assert len(mod._current()) == 5


def test_current_raises_a_clear_error_on_an_empty_board(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    mod = _load_selfcheck()
    mod.DOCS = docs
    with pytest.raises(SystemExit):
        mod._current()


def test_current_raises_on_a_torn_parts_set_rather_than_silently_undercounting(tmp_path):
    """A parts board whose manifest disagrees with what is on disk must fail loudly (the
    codebase's own standing rule: never silently accept a smaller/wrong board), not be
    swallowed into an empty or partial read."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(30)], {"notes": "seed"}, docs_dir=docs)
    manifest_path = docs / "board.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # Corrupt one part's recorded size so verify_dir/resolve() must raise.
    manifest["parts"]["files"][0]["bytes"] += 1
    manifest_path.write_text(json.dumps(manifest))

    mod = _load_selfcheck()
    mod.DOCS = docs
    with pytest.raises(SystemExit):
        mod._current()


# ===========================================================================
# 2. invariants() over the shape iter_board_rows() actually yields
#
# (board_selfcheck.py had no test file at all before this one.) These rows are the
# _to_dict()/RAW_KEEP shape -- top-level parcel_id/street_address/county plus a whole
# raw.calc / raw.equity block -- not the further-projected SLIM-V1 shape. Both keep
# calc and equity whole ("*" in both RAW_KEEP and _SLIM_RAW), which is exactly why the
# fix above needed no change to invariants()/movement() themselves.
# ===========================================================================

def _row(parcel_id: str, calc: dict, equity_value=None) -> dict:
    raw = {"calc": calc}
    if equity_value is not None:
        raw["equity"] = {"value": equity_value}
    return {"parcel_id": parcel_id, "street_address": "1 Main St", "county": "Gaston",
            "state": "NC", "source": "test", "case_number": None, "raw": raw}


def test_contradicted_arv_carrying_a_max_bid_is_flagged(tmp_path):
    mod = _load_selfcheck()
    flag = next(iter(mod.CONTRADICTED))
    board = [_row("P1", {"arv_flags": [flag], "max_bid_70": 150_000})]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no max_bid_70 on a contradicted ARV"]
    assert entry["count"] == 1
    assert entry["ok"] is False


def test_clean_board_breaches_nothing(tmp_path):
    mod = _load_selfcheck()
    board = [_row("P1", {"arv_expected": 200_000, "max_bid_70": 140_000}, equity_value=50_000)]
    inv = mod.invariants(board)
    assert all(i["ok"] for i in inv), [i for i in inv if not i["ok"]]


def test_duplicate_parcel_rows_are_counted_once_each_over_the_limit(tmp_path):
    mod = _load_selfcheck()
    board = [_row("DUP1", {}), _row("DUP1", {})]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no duplicate identifiable properties"]
    assert entry["count"] == 1
    assert entry["ok"] is False
