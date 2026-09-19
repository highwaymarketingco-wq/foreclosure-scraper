"""write_artifact() must prune BOTH backup patterns, not just the main one.

Regression guard for a real bug found 2026-09-17 live on the production board:
the prune step globbed "listings_2*.json" (the main backup) and tried to
derive a sibling glob for the paired listings_detail_<ts>.json(.gz) file by
rsplit()-ing the stem on "_" -- but "listings_<ts>".rsplit("_", 1)[0]
produces "listings_<date>", a prefix that never matches "listings_detail_...".
Main backups pruned fine at 10 files; detail backups never matched ANY prune
glob and grew unbounded -- 214 files / 24GB found on the live backups/
directory, which drove the Mac's disk to 0 bytes free mid-backfill (visible
as "tee: No space left on device" in a running script's log) and put the
next atomic board write at real risk of landing on a full disk. Fixed by
pruning both patterns independently by their own recency instead of relying
on one glob's leftovers to also catch the other's files.
"""
from __future__ import annotations

import os
import time

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import write_artifact


def _lead(i: int) -> Listing:
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "B"}})


def test_prune_caps_both_main_and_detail_backups(tmp_path):
    docs = tmp_path / "docs"
    backups = tmp_path / "backups"
    backups.mkdir()

    # First write: no existing board yet, so no backup/prune runs.
    write_artifact([_lead(0)], {"notes": "seed"}, docs_dir=docs)

    # Seed 15 fake old backups of EACH pattern with distinct, old, increasing
    # mtimes so recency-sort ordering is deterministic regardless of clock
    # resolution.
    base = time.time() - 100_000
    for i in range(15):
        m = base + i
        main = backups / f"listings_202601{i:02d}_000000.json"
        detail = backups / f"listings_detail_202601{i:02d}_000000.json"
        main.write_text("{}")
        detail.write_text("{}")
        os.utime(main, (m, m))
        os.utime(detail, (m, m))

    # The seed write above had no prior board yet, so it created no backup of
    # its own -- these counts are purely the 15 fakes just seeded.
    assert len(list(backups.glob("listings_2*.json"))) == 15
    assert len(list(backups.glob("listings_detail_2*.json*"))) == 15

    # Second write triggers the prune step (board now exists).
    write_artifact([_lead(0), _lead(1)], {"notes": "pass 2"}, docs_dir=docs)

    main_count = len(list(backups.glob("listings_2*.json")))
    detail_count = len(list(backups.glob("listings_detail_2*.json*")))
    from foreclosure_scraper.web_artifact import _BACKUP_KEEP
    assert main_count <= _BACKUP_KEEP, f"main backups not pruned: {main_count} files"
    assert detail_count <= _BACKUP_KEEP, f"detail backups not pruned (the real bug): {detail_count} files"
