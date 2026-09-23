#!/usr/bin/env python3
"""Run enrichment_vision.enrich_with_vision() board-wide on the PAID Anthropic
Haiku path, explicitly authorized (2026-09-23: "haiku works for images ...
do what must be done").

This project defaults to FREE-only (see backfill_vision.py, which forces
VISION_PROVIDER=gemini and asserts ANTHROPIC_API_KEY is absent). That default
is why the free-tier daily vision pass only clears a couple hundred leads a
night: Gemini's per-project-per-model daily quota is 20 requests/day per key,
and even with 9 rotating keys across 5 models that tops out around 180-200
calls before every lane reports "daily quota spent" (see
docs/vision_repair_2026-09-21.md and this run's own logs/daily-vision-*.log).
enrichment_vision.py already defaults ANTHROPIC_VISION_MODEL to
"claude-haiku-4-5" specifically because it is cheap enough to fund directly
for exactly this situation (see that module's own comment: ~9,326 leads at
~1,600in/~400out tokens was measured at ~$34 total on Haiku 4.5, $1/$5 per
Mtok) -- this script just stops routing around that path.

Same board_lock / load_board / write_artifact pattern as backfill_vision.py.
VISION_MAX_SPEND_USD (read by enrichment_vision._SpendGuard) is the real
safety net: once cumulative Anthropic spend this run hits the cap, that
backend starts declining and the worker pool falls back to the free
providers for whatever's left instead of continuing to spend.

    python scripts/backfill_vision_haiku.py --dry-run
    python scripts/backfill_vision_haiku.py --max 2000 --max-spend 25
    python scripts/backfill_vision_haiku.py --max 30000 --max-spend 120
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
    """Same dependency-free KEY=VALUE loader as backfill_vision.py."""
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

# .secrets/anthropic_api_key.txt is how scripts/run_local.sh sources this key
# for the real pipeline (see its own `load ANTHROPIC_API_KEY ...` line) --
# mirror that here so this script works the same way standalone.
if not os.environ.get("ANTHROPIC_API_KEY"):
    _key_file = REPO / ".secrets" / "anthropic_api_key.txt"
    if _key_file.exists():
        os.environ["ANTHROPIC_API_KEY"] = _key_file.read_text().strip()

# MUST happen before enrichment_vision is imported anywhere (VISION_PROVIDER,
# ANTHROPIC_VISION_MODEL, and the backend-pool builder's VISION_INCLUDE_ANTHROPIC
# check are all read at import/pool-build time). Explicit rather than relying on
# the module's own defaults, so this script's intent is visible in its own
# source, not just inherited silently.
#
# CAUGHT LIVE 2026-09-23: VISION_PROVIDER alone does NOT add Anthropic to the
# worker pool. _build_backends()'s own comment says why: "Default stays
# 'fallback of last resort' (only added when the free pool is empty) so a
# normal run never spends money by accident." The actual gate is
# `want_anthropic = not backends or os.environ.get("VISION_INCLUDE_ANTHROPIC")
# == "1"` -- with any free backend present (Gemini/Groq/etc almost always are),
# VISION_PROVIDER is read but has no effect on which backends get built. A
# first run of this script without this flag silently used ONLY the free pool
# (by_backend={'gemini': 287, 'groq': 12}, estimated_cost_usd=0.0661 -- that
# figure is Gemini's "would-have-cost" placeholder, not real spend) and scored
# 299 of 5,311 candidates before free-tier quotas and rate limits capped it,
# spending $0 despite the script's whole purpose being to spend real money to
# clear what the free pool can't. VISION_INCLUDE_ANTHROPIC=1 adds Anthropic
# ALONGSIDE the free backends rather than replacing them -- per that same
# comment, "it draws from the SAME shared queue as every other backend, so it
# only picks up listings the free lanes haven't already claimed" -- so this is
# still cost-minimizing, not "force everything through the paid path."
os.environ["VISION_PROVIDER"] = "anthropic"
os.environ.setdefault("ANTHROPIC_VISION_MODEL", "claude-haiku-4-5")
os.environ["VISION_INCLUDE_ANTHROPIC"] = "1"
assert os.environ.get("ANTHROPIC_API_KEY"), (
    "ANTHROPIC_API_KEY not set and .secrets/anthropic_api_key.txt not found -- "
    "this script's whole job is to use the paid Anthropic path, so it has "
    "nothing to do without a key."
)

from foreclosure_scraper.enrichment_vision import (  # noqa: E402
    ANTHROPIC_VISION_MODEL,
    VISION_PROVIDER,
    _ANTHROPIC_PRICE_PER_MTOK,
    _select_image_urls,
    enrich_with_vision,
)
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

# Measured 2026-08-07 on this exact model/prompt (see enrichment_vision.py's
# own comment): ~1,600 input / ~400 output tokens per listing.
_EST_IN_TOK = 1600
_EST_OUT_TOK = 400


def _estimate_cost(n_listings: int) -> float:
    in_price, out_price = _ANTHROPIC_PRICE_PER_MTOK[ANTHROPIC_VISION_MODEL]
    return n_listings * (
        (_EST_IN_TOK / 1_000_000) * in_price + (_EST_OUT_TOK / 1_000_000) * out_price
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=2000, help="max_listings for this run (default 2000)")
    ap.add_argument("--max-spend", type=float, default=0.0,
                     help="VISION_MAX_SPEND_USD for this run (0 = no cap; NOT recommended on the paid path)")
    args = ap.parse_args()

    assert VISION_PROVIDER == "anthropic", f"VISION_PROVIDER={VISION_PROVIDER!r}, expected 'anthropic'"
    if args.max_spend > 0:
        os.environ["VISION_MAX_SPEND_USD"] = str(args.max_spend)
        # _SpendGuard reads this env var at import time (see enrichment_vision.py's
        # module-level `_spend_guard = _SpendGuard()`), which already happened
        # above -- reach into the already-constructed instance instead of relying
        # on a second import to re-read the env.
        from foreclosure_scraper.enrichment_vision import _spend_guard
        _spend_guard.limit = args.max_spend

    print(f"VISION_PROVIDER={VISION_PROVIDER}  model={ANTHROPIC_VISION_MODEL}  "
          f"max_listings={args.max}  max_spend_usd={args.max_spend or 'none'}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_vision_haiku")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        candidates = [li for li in rows if _select_image_urls(li) and not (isinstance(li.raw, dict) and li.raw.get("vision"))]
        print(f"vision candidates (has images, not yet scored): {len(candidates):,}")
        est_full = _estimate_cost(len(candidates))
        est_this_run = _estimate_cost(min(len(candidates), args.max))
        print(f"estimated cost to clear the FULL backlog on {ANTHROPIC_VISION_MODEL}: ~${est_full:,.2f}")
        print(f"estimated cost for THIS run (max={args.max}): ~${est_this_run:,.2f}")

        if args.dry_run:
            print("\nDRY RUN -- enrich_with_vision() not called, nothing written, nothing spent.")
            return 0

        before_scored = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("vision"))
        asyncio.run(enrich_with_vision(rows, max_listings=args.max))
        after_scored = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("vision"))
        print(f"\nnewly scored: {after_scored - before_scored:,}")

        write_artifact(rows, {"backfill_vision_haiku": after_scored - before_scored}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
