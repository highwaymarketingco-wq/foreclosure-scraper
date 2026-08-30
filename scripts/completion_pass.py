#!/usr/bin/env python
"""Slow-phase COMPLETION pass — run the slow, valuable enrichers that the main run's
tight tail caps only partially cover, giving each its PROPER budget, decoupled from the
main run's critical path. Load the current board, run the slow tier, re-fold signals +
re-score, write the board back. Every phase is idempotent (skips leads already done), so
repeated passes CONVERGE the board without re-doing work.

The main run caps these at 900s each so it can't hang. This pass gives each its designed
budget (ROD up to 4h, name-resolve 2h, OCR/divorce 30m). Runs as a BACKGROUND job while the
board is already live — if it dies (laptop sleep) it just re-runs and continues where it left off.

Run ONLY when the board lock is free (after the main run / merge releases it).
Usage:  python scripts/completion_pass.py                 # full slow tier
        COMPLETION_PHASES=rod python scripts/completion_pass.py   # subset: rod|name|ocr|divorce
"""
from __future__ import annotations

import asyncio
import collections
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("FORECLOSURE_CHECKPOINT_DIR", "data/checkpoint_completion")
# make sure the phases that gate on an env flag actually run here
for k in ("FORECLOSURE_GASTON_ROD", "ROD_ENRICH_ON", "FORECLOSURE_DOC_OCR", "FORECLOSURE_DOT_OCR"):
    os.environ.setdefault(k, "1")

from foreclosure_scraper.web_artifact import write_artifact, load_board  # noqa: E402
from foreclosure_scraper.enrichment_gaston_rod import enrich_gaston_rod  # noqa: E402
from foreclosure_scraper.enrichment_cchs_rod import enrich_cchs_rod  # noqa: E402
from foreclosure_scraper.enrichment_aumentum_rod import enrich_aumentum_rod  # noqa: E402
from foreclosure_scraper.enrichment_spartanburg_rod import enrich_spartanburg_rod  # noqa: E402
from foreclosure_scraper.enrichment_resolve_name_to_property import enrich_resolve_name_to_property  # noqa: E402
from foreclosure_scraper.enrichment_dot_ocr import enrich_dot_ocr  # noqa: E402
from foreclosure_scraper.enrichment_doc_ocr import enrich_doc_ocr  # noqa: E402
from foreclosure_scraper.enrichment_nc_divorce import enrich_nc_divorce  # noqa: E402
from foreclosure_scraper.enrichment_sc_divorce import enrich_sc_divorce  # noqa: E402
from foreclosure_scraper.enrichment_lead_signals import enrich_lead_signals  # noqa: E402
from foreclosure_scraper.distress_score import score_board  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"

# (group, name, fn, budget_s) — budget respects each phase's OWN design, not the main run's 900s.
_TIER = [
    ("rod", "gaston_rod", enrich_gaston_rod, 3600),
    ("rod", "cchs_rod", enrich_cchs_rod, 3600),
    ("rod", "aumentum_rod", enrich_aumentum_rod, 3600),
    ("rod", "spartanburg_rod", enrich_spartanburg_rod, 14400),   # 4h — its designed budget
    ("name", "resolve_name", enrich_resolve_name_to_property, 7200),  # 2h
    ("ocr", "dot_ocr", enrich_dot_ocr, 1800),
    ("ocr", "doc_ocr", enrich_doc_ocr, 1800),
    ("divorce", "nc_divorce", enrich_nc_divorce, 1800),
    ("divorce", "sc_divorce", enrich_sc_divorce, 1800),
]


async def _run(board, groups: set[str]):
    for group, name, fn, budget in _TIER:
        if group not in groups:
            continue
        try:
            s = await asyncio.wait_for(fn(board), timeout=budget)
            print(f"  {name}: {s}", flush=True)
        except asyncio.TimeoutError:
            print(f"  {name}: budget-capped at {budget}s (partial; idempotent — re-run continues)",
                  flush=True)
        except Exception:
            print(f"  {name}: ERROR\n{traceback.format_exc()[:400]}", flush=True)


def main() -> int:
    want = os.environ.get("COMPLETION_PHASES")
    groups = set(want.split(",")) if want else {"rod", "name", "ocr", "divorce"}
    board = load_board(DOCS)   # sidecar-safe
    print(f"loaded {len(board)} leads; running groups={sorted(groups)}", flush=True)
    asyncio.run(_run(board, groups))
    for label, fn in (("lead_signals", enrich_lead_signals), ("score_board", score_board)):
        try:
            fn(board)
        except Exception:
            print(f"  {label}: ERROR {traceback.format_exc()[:200]}", flush=True)
    summary = {
        "by_source": dict(collections.Counter(li.source for li in board if li.source)),
        "notes": f"completion_pass: slow-tier {sorted(groups)} at designed budgets",
    }
    lp, mp = write_artifact(board, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name} — {len(board)} leads", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
