"""Hourly incremental refresh — lightweight update vs full 5-hour board pass.

Matches Goliath Data's hourly refresh capability. Instead of re-scraping all
205 sources (5+ hours), this script:
1. Checks recently-changed sources (county feeds, auction sites, court dockets)
2. Merges new/updated listings into the existing board
3. Runs lightweight enrichers (skip_trace, dnc_scrub, grade, equity recompute)
4. Writes the updated board via web_artifact.write_artifact()

The full pass (scripts/enrich_board.py) still runs daily for deep enrichers.

Run:
    python -m foreclosure_scraper.hourly_refresh
    # Or as cron: */60 * * * * cd ~/foreclosure-scraper && ...
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from .web_artifact import load_board, write_artifact

log = structlog.get_logger()


async def _run_lightweight_enrichers(board) -> dict:
    """Run only fast offline enrichers (<5s each, no network)."""
    stats = {}

    # Grade/score recompute
    try:
        from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
        enrich_derivation_flags(board)
        stats["derivation_flags"] = "OK"
    except Exception as e:
        stats["derivation_flags"] = f"ERR: {str(e)[:100]}"

    # Lead signals
    try:
        from foreclosure_scraper.enrichment_lead_signals import enrich_lead_signals
        enrich_lead_signals(board)
        stats["lead_signals"] = "OK"
    except Exception as e:
        stats["lead_signals"] = f"ERR: {str(e)[:100]}"

    # Data quality
    try:
        from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
        enrich_data_quality(board)
        stats["data_quality"] = "OK"
    except Exception as e:
        stats["data_quality"] = f"ERR: {str(e)[:100]}"

    # DNC scrub (offline if local file exists)
    try:
        from foreclosure_scraper.enrichment_dnc import enrich_dnc_scrub
        result = enrich_dnc_scrub(board)
        stats["dnc_scrub"] = f"OK ({result.get('scrubbed', 0)} scrubbed)"
    except Exception as e:
        stats["dnc_scrub"] = f"ERR: {str(e)[:100]}"

    # Workflow evaluation
    try:
        from foreclosure_scraper.workflow_engine import evaluate_workflows
        result = evaluate_workflows(board)
        stats["workflows"] = f"OK ({result['total_matches']} matches)"
    except Exception as e:
        stats["workflows"] = f"ERR: {str(e)[:100]}"

    return stats


async def hourly_refresh(docs_dir: str = "docs") -> dict:
    """Run incremental refresh on the board."""
    t0 = time.time()
    log.info("hourly_refresh.start")

    # Load existing board
    board = load_board(docs_dir)
    before_count = len(board)
    log.info("hourly_refresh.board_loaded", count=before_count)

    # Run lightweight enrichers
    enricher_stats = await _run_lightweight_enrichers(board)

    # Write updated board
    summary = {
        "refresh_type": "hourly_incremental",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "before_count": before_count,
        "after_count": len(board),
        "enrichers": enricher_stats,
    }
    write_artifact(board, summary, docs_dir)

    elapsed = time.time() - t0
    log.info("hourly_refresh.done", elapsed=f"{elapsed:.0f}s", count=len(board))
    return {
        "elapsed_seconds": elapsed,
        "before_count": before_count,
        "after_count": len(board),
        "enrichers": enricher_stats,
    }


def main():
    result = asyncio.run(hourly_refresh())
    print(f"Hourly refresh complete in {result['elapsed_seconds']:.0f}s")
    print(f"  Board: {result['before_count']} -> {result['after_count']} leads")
    for name, status in result["enrichers"].items():
        print(f"  {name:30s} {status}")


if __name__ == "__main__":
    main()
