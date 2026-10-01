"""The pre-write backup must work on a fresh-clone-style working directory, not just
the local runner's directory.

THE BUG (found 2026-09-30, live on the Oracle VM revived that day). docs/listings.json
(plain) and a single docs/listings.json.gz are both gitignored/uncommitted -- the board
exceeds GitHub's 100MB/file limit even gzipped as one file, so what git actually tracks is
docs/board.manifest.json + docs/listings_part_NNN.json.gz shards (see .gitignore and
board_parts.py). A `git clone` therefore never materializes a monolithic listings.json; only
something that locally runs write_artifact()/load_board() regenerates the plain copy.

_count_guard_and_backup()'s pre-write backup step did not know this: it called
`shutil.copy2(listings_path, ...)` unconditionally, assuming the plain file always exists.
On the VM's fresh clone that raised FileNotFoundError, which the surrounding
`except Exception: log.warning(...)` swallowed -- so the write proceeded with NO real backup,
silently, while producing a log line ("web_artifact.backup_failed") easy to miss in a run's
output. A real vision-grading write on the VM that day hit exactly this: it succeeded, but
with no safety net, unlike every write on the Mac (which always has the plain file locally).

Fixed by _backup_listings_board(), which asks the same source-selection the READ path already
uses (_choose_board_source) which representation of docs/listings.json is actually on disk --
plain, a single .gz twin, or the listings_part_NNN.json.gz shard set -- and backs up whichever
one it finds, as a plain file copy (cheap; never parses the board into memory, which matters on
the Mac's 8GB budget).
"""
from __future__ import annotations

import gzip
import json
import time

from foreclosure_scraper import board_parts as bp
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import (
    _BACKUP_KEEP,
    _backup_listings_board,
    append_new_rows,
    write_artifact,
)


def _lead(i: int) -> Listing:
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "B"}})


def _strip_to_fresh_clone_shape(docs) -> None:
    """Delete everything a real `git clone` would never materialize, leaving only what git
    actually tracks: board.manifest.json + listings_part_NNN.json.gz (+ the detail/slim .gz
    twins, which are committed as single files and unaffected by this bug)."""
    for name in ("listings.json", "listings_slim.json", "listings_detail.json"):
        p = docs / name
        if p.exists():
            p.unlink()


# ===========================================================================
# 1. THE REAL BUG: parts-only ("fresh clone") directory must get a real backup
# ===========================================================================

def test_backup_succeeds_on_parts_only_fresh_clone_style_dir(tmp_path):
    docs = tmp_path / "docs"
    write_artifact([_lead(i) for i in range(10)], {"notes": "seed"}, docs_dir=docs)
    _strip_to_fresh_clone_shape(docs)
    assert not (docs / "listings.json").exists()
    assert not (docs / "listings.json.gz").exists()
    assert (docs / "board.manifest.json").exists()
    assert (docs / "listings_part_000.json.gz").exists()

    stats = append_new_rows([_lead(100), _lead(101)], {"notes": "vm write"}, docs_dir=docs)
    assert stats["written"] is True
    assert stats["total_after"] == 12

    backups = tmp_path / "backups"
    parts_backups = list(backups.glob("listings_2*_parts"))
    assert len(parts_backups) == 1, (
        "no parts-shaped backup was created -- this is the silent no-op bug: the write "
        "proceeded with no real safety net"
    )
    backup_dir = parts_backups[0]
    assert (backup_dir / "board.manifest.json").exists()
    assert (backup_dir / "listings_part_000.json.gz").exists()

    # It must be a REAL, USABLE snapshot of the board as it stood BEFORE this write (10
    # rows) -- not empty, not partial, not the post-write board.
    recovered = bp.read_rows(backup_dir)
    assert len(recovered) == 10, (
        f"backup should hold the pre-write 10-row board, got {len(recovered)} rows -- "
        "a backup that doesn't match the prior state isn't a safety net"
    )


def test_backup_also_succeeds_via_write_artifact_not_just_append(tmp_path):
    """append_new_rows and write_artifact share _count_guard_and_backup -- pin the other
    caller too, since a fix scoped to only one entry point would leave the other broken."""
    docs = tmp_path / "docs"
    write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)
    _strip_to_fresh_clone_shape(docs)

    write_artifact([_lead(i) for i in range(5)] + [_lead(5)], {"notes": "pass2"}, docs_dir=docs)

    backups = tmp_path / "backups"
    parts_backups = list(backups.glob("listings_2*_parts"))
    assert len(parts_backups) == 1
    recovered = bp.read_rows(parts_backups[0])
    assert len(recovered) == 5, "backup must reflect the board as it stood before pass2"


# ===========================================================================
# 2. NO REGRESSION: the local-runner shape (plain file present) is unchanged
# ===========================================================================

def test_backup_still_copies_the_plain_file_directly_when_present(tmp_path):
    docs = tmp_path / "docs"
    write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)
    prior_plain = json.loads((docs / "listings.json").read_text())

    write_artifact([_lead(i) for i in range(5)] + [_lead(5)], {"notes": "pass2"}, docs_dir=docs)

    backups = tmp_path / "backups"
    main_backups = [p for p in backups.glob("listings_2*.json") if p.is_file()]
    assert len(main_backups) == 1, "plain-file case must still produce a plain .json backup"
    assert not list(backups.glob("listings_2*_parts")), (
        "a board with a plain file present must not take the parts-backup path"
    )
    backed_up = json.loads(main_backups[0].read_text())
    assert backed_up == prior_plain, "backup content must match the pre-write board exactly"


# ===========================================================================
# 3. Unit-level: _backup_listings_board handles all three on-disk shapes
# ===========================================================================

def test_backup_listings_board_handles_legacy_single_gz_with_no_manifest(tmp_path):
    """Before the board was split into parts, a single docs/listings.json.gz was the
    committed artifact (see read_board_json's docstring). _backup_listings_board must still
    handle that shape too, not just plain and parts."""
    docs = tmp_path / "docs"
    docs.mkdir()
    rows = [{"id": i} for i in range(3)]
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode("utf-8")))

    backups = tmp_path / "backups"
    backups.mkdir()
    dest = _backup_listings_board(docs / "listings.json", backups, "20260101_000000")

    assert dest.name == "listings_20260101_000000.json.gz"
    assert dest.is_file()
    recovered = json.loads(gzip.decompress(dest.read_bytes()).decode("utf-8"))
    assert recovered == rows


def test_backup_listings_board_raises_when_nothing_exists(tmp_path):
    """Sanity check: with no board at all, there is nothing to back up -- this must raise
    (caught by the caller's except-and-warn), not silently succeed with an empty file."""
    docs = tmp_path / "docs"
    docs.mkdir()
    backups = tmp_path / "backups"
    backups.mkdir()
    import pytest
    with pytest.raises(FileNotFoundError):
        _backup_listings_board(docs / "listings.json", backups, "20260101_000000")


# ===========================================================================
# 4. Pruning must bound the new parts-shaped (directory) backups too
# ===========================================================================

def test_prune_caps_old_parts_backups_too(tmp_path):
    docs = tmp_path / "docs"
    write_artifact([_lead(0)], {"notes": "seed"}, docs_dir=docs)
    _strip_to_fresh_clone_shape(docs)

    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    base = time.time() - 100_000
    for i in range(15):
        d = backups / f"listings_202601{i:02d}_000000_parts"
        d.mkdir()
        (d / "board.manifest.json").write_text("{}")
        m = base + i
        import os
        os.utime(d, (m, m))
    assert len(list(backups.glob("listings_2*_parts"))) == 15

    # Triggers the parts-shaped backup + the prune step (board now exists, parts-only shape).
    append_new_rows([_lead(1)], {"notes": "trigger"}, docs_dir=docs)

    remaining = list(backups.glob("listings_2*_parts"))
    assert len(remaining) <= _BACKUP_KEEP, f"parts backups not pruned: {len(remaining)} dirs"
