#!/usr/bin/env python3
"""Run enrichment_vision.enrich_with_vision() board-wide, safely, FREE-only.

enrich_with_vision()'s own module-level default is VISION_PROVIDER="anthropic"
(paid, ~$0.01-0.03/listing) unless overridden. This script forces
VISION_PROVIDER=gemini in os.environ BEFORE importing enrichment_vision (the
constant is read at module-import time, so setting it after import is a
no-op), and asserts ANTHROPIC_API_KEY is absent as a second, explicit
guard -- belt-and-braces against ever touching the paid path, matching the
standing FREE-only rule for this project.

enrich_with_vision() already has its own internal worker pool with health
tracking, requeueing, and a VISION_MAX_SECONDS deadline -- no external
chunking/checkpointing needed here, unlike the geocode/parcel backfills.
The caller controls scope via `max_listings`; this script defaults to a
small first batch (500) to verify the whole pipeline end-to-end (provider
selection, real key rotation, real score-writing) before scaling up to the
full candidate pool in a later run.

    python scripts/backfill_vision.py --dry-run
    python scripts/backfill_vision.py --max 500
    python scripts/backfill_vision.py --max 5500
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def _load_env_file(path: Path) -> None:
    """Same dependency-free KEY=VALUE loader as backfill_doc_ocr.py -- see
    that script's docstring for why python-dotenv can't be relied on here."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file(REPO / ".env")

# MUST happen before enrichment_vision is imported anywhere (including
# transitively) -- VISION_PROVIDER is read into a module-level constant at
# import time.
os.environ["VISION_PROVIDER"] = "gemini"
assert not os.environ.get("ANTHROPIC_API_KEY"), (
    "ANTHROPIC_API_KEY is set -- refusing to run. This project is FREE-only; "
    "enrich_with_vision() defaults to the paid Anthropic provider, and this "
    "script's whole job is to guarantee that path is never reachable."
)

from foreclosure_scraper.enrichment_vision import (  # noqa: E402
    VISION_PROVIDER,
    _select_image_urls,
    enrich_with_vision,
)
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=500, help="max_listings for this run (default 500)")
    args = ap.parse_args()

    assert VISION_PROVIDER == "gemini", f"VISION_PROVIDER={VISION_PROVIDER!r}, expected 'gemini'"
    print(f"VISION_PROVIDER={VISION_PROVIDER}  max_listings={args.max}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_vision")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        candidates = [li for li in rows if _select_image_urls(li) and not (isinstance(li.raw, dict) and li.raw.get("vision"))]
        print(f"vision candidates: {len(candidates):,}")

        if args.dry_run:
            print("\nDRY RUN — enrich_with_vision() not called, nothing written.")
            return 0

        before_scored = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("vision"))
        asyncio.run(enrich_with_vision(rows, max_listings=args.max))
        after_scored = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("vision"))
        print(f"\nnewly scored: {after_scored - before_scored:,}")

        write_artifact(rows, {"backfill_vision": after_scored - before_scored}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
