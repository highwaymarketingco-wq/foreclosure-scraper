"""scripts/backfill_derivation_flags.py's board-I/O rewrite (2026-10-02, docs/HANDOFF.md item
41): it used to call load_board() to build the WHOLE board, run enrich_derivation_flags() over
it, then write_artifact(rows, ...) -- the double materialization that kernel-OOM-killed a real
production attempt on the 23GB Oracle VM the same day. This test proves the new path -- a single
streaming pass over board_stream.iter_board_rows(), enrich_derivation_flags() called UNCHANGED on
a one-row-at-a-time batch (verified safe because the function carries no cross-call state), a
per-row diff, one web_artifact.patch_existing_rows() call -- reproduces the original contract
exactly, including the one raw-key DELETION the function performs (stale-flag cleanup), without
ever calling load_board()/write_artifact().

Covers:
  1. A row that newly qualifies for free_and_clear gets raw['derivation_flags'] patched onto it.
  2. The stale-flag-removal hazard this migration's own docstring calls out: a row whose
     derivation_flags was previously set but no longer applies gets raw['derivation_flags'] =
     None patched (the only way patch_existing_rows()'s merge-only write can represent a
     deletion), and the resulting board, when re-read, treats it exactly like an absent key.
  3. An ordinary row with nothing to flag is never sent to patch_existing_rows() at all.
  4. --dry-run computes and prints stats but writes nothing.
  5. Idempotency: a second real run patches nothing.
  6. The board-too-large-to-patch ceiling is checked before the (streaming) pass runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_derivation_flags as D  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

_CLEAN_ROD = {"instrument_count": 2, "has_mortgage": False, "open_mortgages_est": 0,
              "source": "cchs_rod", "fetched_at": "2026-08-01T00:00:00+00:00"}
_OPEN_MTG_ROD = {"instrument_count": 41, "has_mortgage": True, "open_mortgages_est": 3,
                  "source": "cchs_rod", "fetched_at": "2026-08-01T00:00:00+00:00"}
_STALE_FLAGS = {"free_and_clear": {"flag": True, "reason": "no_mortgage_recordings"}}


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.TAX_LIEN, state="SC", county="Spartanburg",
                owner_name="BYRD SANDRA D", raw={})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(D, "REPO", repo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _seed(docs: Path, rows: list[Listing]) -> None:
    wa.write_artifact(rows, {"notes": "backfill_derivation_flags test seed"}, docs_dir=docs)


def _read_board(docs: Path) -> list[dict]:
    from foreclosure_scraper.board_stream import iter_board_rows
    gz = docs / "listings.json.gz"
    plain = docs / "listings.json"
    return list(iter_board_rows(gz if gz.exists() else plain))


def test_newly_qualifying_row_gets_flagged(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, raw={"rod": _CLEAN_ROD})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py"])

    rc = D.main()
    assert rc == 0

    board = _read_board(docs)
    assert board[0]["raw"]["derivation_flags"]["free_and_clear"]["flag"] is True


def test_stale_flag_removal_lands_as_explicit_none_and_reads_as_absent(scratch_repo, monkeypatch):
    """The exact hazard this migration's docstring discloses: enrich_derivation_flags() does
    `del li.raw["derivation_flags"]` when nothing applies anymore. patch_existing_rows() can only
    merge (dict.update()), never delete, so this must land as raw['derivation_flags'] = None --
    verified safe because every real reader (enrichment_property_category.py) does
    `raw.get("derivation_flags") or {}`."""
    docs = scratch_repo / "docs"
    rows = [_row(0, raw={"rod": {"instrument_count": 4, "has_mortgage": True,
                                  "open_mortgages_est": 0, "source": "cchs_rod"},
                         "derivation_flags": _STALE_FLAGS})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py"])

    rc = D.main()
    assert rc == 0

    board = _read_board(docs)
    row = board[0]
    assert row["raw"]["derivation_flags"] is None  # the only representable form of "deleted"
    # and every real reader (enrichment_property_category.py) treats that exactly like an
    # absent key -- it reads via `raw.get("derivation_flags") or {}`, never a presence test.
    assert (row["raw"].get("derivation_flags") or {}) == {}


def test_ordinary_row_is_never_patched(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, raw={})]  # no rod data at all -- nothing can apply
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py"])

    before = (docs / "listings.json").read_bytes()
    rc = D.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before


def test_dry_run_writes_nothing(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, raw={"rod": _CLEAN_ROD})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py", "--dry-run"])

    before = (docs / "listings.json").read_bytes()
    rc = D.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before

    board = _read_board(docs)
    assert "derivation_flags" not in board[0]["raw"]


def test_second_run_is_idempotent(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, raw={"rod": _CLEAN_ROD})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py"])

    assert D.main() == 0
    before = (docs / "listings.json").read_bytes()
    assert D.main() == 0
    assert (docs / "listings.json").read_bytes() == before


def test_board_too_large_refuses_before_the_pass_runs(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed(docs, [_row(0, raw={})])
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0")  # any real board is "too large"
    monkeypatch.setattr(sys, "argv", ["backfill_derivation_flags.py"])
    called = []
    real_run = D._run

    def spy(dry_run):
        called.append(True)
        return real_run(dry_run)
    monkeypatch.setattr(D, "_run", spy)

    with pytest.raises(wa.BoardLoadTooLarge):
        D.main()
    assert not called, "the ceiling must be checked BEFORE the streaming pass, not after"
