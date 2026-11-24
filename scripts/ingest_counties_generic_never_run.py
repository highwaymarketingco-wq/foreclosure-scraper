#!/usr/bin/env python3
"""Ingest three counties_generic.* scrapers fixed/confirmed in the 2026-09-15
misc-category zero-row audit:

    counties_generic.arcgis_distress_layers  -- was hard-failing the whole
        18-layer batch every run because one flaky single-host layer
        (lincoln_code_violations) has an incomplete TLS chain; added to the
        harvester's existing tolerate-list. Also fixed a DATELESS_OK_SOURCES
        gap that only whitelisted 1 of 18 layers by exact string instead of
        the shared dynamic-slug prefix.
    counties_generic.state_contamination     -- already correctly wired,
        missing its DATELESS_OK_SOURCES prefix entry.
    counties_generic.epa_frs_sites           -- same, missing prefix entry.

All three ship rows under dynamic per-layer/per-registry/per-program source
slugs (not their class-level scraper slug), so dedupe is scoped by the UNION
of every real source prefix these three scrapers can emit, all confirmed at
0 existing board rows.

REWRITTEN 2026-11-23 (found never having been run at all -- its own load_board()
call crashes outright now that the board is 5.7GB, same BoardLoadTooLarge family as
daily_api_refresh.py's confirmed 19GB OOM kill, same fix already applied to
ingest_nc_never_run_batch2.py). append_new_rows() streams the existing board once
instead of materializing it, and its dedupe check is additive-only by construction
(a candidate matching an existing row is skipped, the existing row is never
touched) -- strictly safer than the old load+merge+rewrite for this shape of ingest,
not just lighter. SOURCE_PREFIXES now only backs the expected-prefix sanity check.

    python scripts/ingest_counties_generic_never_run.py --dry-run
    python scripts/ingest_counties_generic_never_run.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers import ArcgisDistressLayers  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.epa_frs_sites import EpaFrsSites  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.state_contamination import StateContamination  # noqa: E402
from foreclosure_scraper.web_artifact import append_new_rows, board_lock  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("arcgis_distress_layers", ArcgisDistressLayers),
    ("state_contamination", StateContamination),
    ("epa_frs_sites", EpaFrsSites),
]
# Real per-row source prefixes each scraper actually emits (dynamic slugs),
# not the class-level self.slug.
SOURCE_PREFIXES = (
    "counties_generic.arcgis_distress.",
    "counties_generic.state_contamination.",
    "counties_generic.epa_frs.",
)


async def _fetch_new() -> list:
    out: list = []
    for name, cls in SCRAPERS:
        try:
            rows = list(await cls().fetch())
        except Exception as e:
            print(f"  [FAIL] {name}: {e!r}")
            continue
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
        print(f"  [OK]   {name}: scraped={len(rows)} kept={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 3 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1
    unexpected = {(li.source or "") for li in new_rows
                  if not (li.source or "").startswith(SOURCE_PREFIXES)}
    assert not unexpected, f"scraper slug drifted out of SOURCE_PREFIXES: {unexpected}"

    self_deduped = dedupe(new_rows)
    print(f"self-deduped (within this batch): {len(new_rows):,} -> {len(self_deduped):,}")

    # FOUND 2026-11-23: this batch's own dedupe() pass logged an unusually high poisoned-
    # parcel rate (one key, parcel:SC:pickens:405300300529, shared by 59 distinct
    # addresses -- 16 keys total, 138 addresses). dedupe()'s house-number guards already
    # keep that from fusing rows WITHIN this batch, but append_new_rows()'s own check
    # against the EXISTING board (_append_row_sigs -> dedupe._strong_sigs) has no
    # equivalent guard -- a candidate sharing one of these keys with an unrelated existing
    # row elsewhere on the board would be wrongly treated as already-on-board and
    # dropped. Carve those rows out explicitly rather than accept that risk: the failure
    # mode this avoids is silent (a missed lead, not a crash), so it would never
    # self-report. Hand them to the EXACT same threshold dedupe()'s own logging uses
    # (suspicious_parcel_keys, min_addresses=4) so this stays in sync with it.
    from foreclosure_scraper.dedupe import suspicious_parcel_keys
    suspicious = suspicious_parcel_keys(self_deduped)
    safe_rows = [li for li in self_deduped if li.dedupe_key() not in suspicious]
    held_back = [li for li in self_deduped if li.dedupe_key() in suspicious]
    if held_back:
        print(f"\nheld back {len(held_back):,} rows on {len(suspicious)} suspicious "
              f"(4+ distinct address) parcel keys -- NOT landed, needs manual review:")
        for li in held_back:
            print(f"  {li.dedupe_key()}  {li.source}  {li.street_address or '(no address)'}")

    if args.dry_run:
        print(f"\nDRY RUN — nothing written ({len(safe_rows):,} would be checked against "
              "the existing board via append_new_rows(), skipping any already present).")
        return 0

    with board_lock(REPO, owner="counties_generic_never_run_ingest", wait=1800, poll=10):
        stats = append_new_rows(safe_rows,
                                {"counties_generic_never_run_ingest": len(safe_rows)},
                                docs_dir=REPO / "docs")
    print(f"\n{stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
