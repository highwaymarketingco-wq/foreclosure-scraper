"""scripts/patch_distress_score.py's migration (2026-10-01, task_board_dedupe_stream) off
read_board_json() + a hand-rolled path.write_text(json.dumps(data)) + reseal_board(resplit=True)
onto board_dedupe_stream.stream_score_board() + web_artifact.patch_existing_rows().

This is the proof-of-concept migration docs/HANDOFF.md's item 24 flagged as not yet possible;
these tests exercise the SCRIPT end-to-end (main()/_run()), not just the underlying primitive
(see tests/test_board_dedupe_stream.py for the primitive's own correctness tests against the
real score_board()).

Covers:
  1. main() scores a fresh board and patches exactly the rows that need a distress_stack.
  2. a second run against the now-scored board is a no-op (nothing patched, exit 0).
  3. BoardLockBusy is handled gracefully (skips, exit 0) -- same contract the old script had.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import patch_distress_score as pds  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               street_address=f"{i + 1} Main St", zip_code="28052", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _lead(0),  # plain foreclosure -- WARM/COLD depending on contactability, some stack
        # audit 2026-10-01: raw['probate'] must name a real decedent/case (has_real_probate)
        # to count -- a bare True is not a shape any real scraper writes.
        _lead(1, raw={"probate": {"case_number": "22E001234"},
                      "owner_mailing": {"mailing": "1 X St", "absentee": True}}),
        _lead(2, raw={}),  # nothing special
    ]
    wa.write_artifact(rows, {"notes": "patch_distress_score integration seed"}, docs_dir=docs)
    return rows


def test_main_scores_a_fresh_board(tmp_path, monkeypatch):
    repo = tmp_path
    docs = repo / "docs"
    docs.mkdir()
    monkeypatch.setattr(pds, "REPO", repo)
    _seed_board(docs)

    rc = pds.main()
    assert rc == 0

    board = wa.load_board(docs)
    assert len(board) == 3
    stacks = {li.source: (li.raw or {}).get("distress_stack") for li in board}
    # every row got SOME stack (score_board always derives one for every active, non-sold row)
    assert all(stacks[s] is not None for s in stacks)
    assert "LIFE_EVENT" in stacks["src.1"]["categories"]


def test_second_run_is_a_no_op(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    docs = repo / "docs"
    docs.mkdir()
    monkeypatch.setattr(pds, "REPO", repo)
    _seed_board(docs)

    assert pds.main() == 0
    before = (docs / "listings.json").read_bytes()

    assert pds.main() == 0
    out = capsys.readouterr().out
    assert "nothing to patch" in out
    after = (docs / "listings.json").read_bytes()
    assert after == before  # genuinely untouched -- no spurious rewrite


def test_lock_busy_is_handled_gracefully(tmp_path, monkeypatch):
    repo = tmp_path
    docs = repo / "docs"
    docs.mkdir()
    monkeypatch.setattr(pds, "REPO", repo)
    _seed_board(docs)

    with wa.board_lock(repo, owner="someone_else"):
        rc = pds.main()
    assert rc == 0  # skipped, not an error
