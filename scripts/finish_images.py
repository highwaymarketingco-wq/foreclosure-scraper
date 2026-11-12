#!/usr/bin/env python
"""Finish image coverage on the board: attach the aerial+satellite+OSM-map layer to
every precise-point lead that lacks an image. This is the FAST, no-network portion of
enrich_with_images (use_mapillary=False + geocode_named=False), so it can't wedge on
the slow Mapillary/geocode passes that timed out during the resolver run.

load_board-safe (preserves the vision/comps/cama sidecar). Leaves raw.images in
listings.json so patch_vision_gemini (which reads listings.json) sees them.

  MAPILLARY=1 -> also layer free street-level photos (slower, per-lead network).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402
from foreclosure_scraper.enrichment_images import enrich_with_images  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _imaged(rows) -> int:
    return sum(1 for li in rows
               if isinstance(li.raw, dict) and (li.raw.get("images") or {}).get("primary"))


def main() -> int:
    m = load_board(DOCS)
    before = _imaged(m)
    print(f"loaded {len(m)} leads | already imaged: {before}", flush=True)

    use_map = os.environ.get("MAPILLARY") == "1"
    # geocode_named off: only 4 leads are address-only; not worth the slow nominatim
    # loop that ate the resolver's image budget.
    asyncio.run(enrich_with_images(m, use_mapillary=use_map, geocode_named=False))

    after = _imaged(m)
    print(f"imaged: {before} -> {after} (+{after - before})", flush=True)

    summary = {
        "notes": "finish_images: aerial+map coverage for precise-point leads"
                 + (" + mapillary street" if use_map else " (no-network, use_mapillary=0)"),
    }
    lp, mp = write_artifact(m, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name} | total {len(m)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
