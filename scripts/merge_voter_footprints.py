"""Merge voter phone enrichment + re-run footprint estimation.

Run AFTER the board pass completes. This script:
1. Loads the board
2. Runs NC voter phone enrichment with fuzzy matching (Soundex + nicknames)
3. Runs SC voter cross-reference enrichment
4. Re-runs footprint sqft estimation (now that county data is built)
5. Saves the board

Usage:
    cd ~/foreclosure-scraper && export PATH="$HOME/bin:$PATH" && \
    PYTHONPATH=~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH \
    python3.12 scripts/merge_voter_footprints.py
"""
import time
import structlog

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone
from foreclosure_scraper.enrichment_sc_voter_xref import enrich_sc_phone_xref
from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft

log = structlog.get_logger()


def main():
    t0 = time.time()
    board = load_board()
    log.info("merge.board_loaded", total=len(board))

    # 1. NC voter phone enrichment (with fuzzy matching)
    nc = [li for li in board if li.state == "NC"]
    before_nc = sum(1 for li in nc if li.raw.get("owner_phone"))
    stats = enrich_voter_phone(nc)
    after_nc = sum(1 for li in nc if li.raw.get("owner_phone"))
    log.info("merge.voter_phone_done",
             before=before_nc, after=after_nc,
             new=after_nc - before_nc, stats=stats)

    # 2. SC voter cross-reference (SC owners against NC voter file)
    sc = [li for li in board if li.state == "SC"]
    before_sc = sum(1 for li in sc if li.raw.get("owner_phone"))
    xref_stats = enrich_sc_phone_xref(sc)
    after_sc = sum(1 for li in sc if li.raw.get("owner_phone"))
    log.info("merge.sc_voter_xref_done",
             before=before_sc, after=after_sc,
             new=after_sc - before_sc, stats=xref_stats)

    # 3. Re-run footprint sqft estimation (county data now built)
    fp_stats = enrich_footprint_sqft(board)
    log.info("merge.footprint_done", stats=fp_stats)

    # 4. Save board
    summary = {
        "voter_phones_nc": after_nc,
        "voter_phones_sc": after_sc,
        "footprint_estimated": fp_stats.get("estimated", 0),
    }
    write_artifact(board, summary, docs_dir="docs")
    log.info("merge.board_saved", summary=summary, elapsed=f"{time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
