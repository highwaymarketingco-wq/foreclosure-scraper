"""Scheduled NC SOS registered-agent pass — fills raw['sos_agent'] (registered
agent + officers = a free mailable contact) for entity-owned NC leads that
otherwise have no owner contact. Runs on the committed board (no re-scrape);
stealth + slow so it is its own opt-in pass, not part of the weekly crawl.

Board-writer — run it alone (the weekly/merge/lrcpwa passes must not be active).
Idempotent: skips leads that already carry raw['sos_agent']. Sets SOS_AGENT=1
itself so the enricher is enabled.

Usage:  SOS_AGENT_MAX_CHECK=80 uv run python scripts/sos_agent_refresh.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("SOS_AGENT", "1")

from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_sos_agent import enrich_with_sos_agent
from foreclosure_scraper.web_artifact import write_artifact, load_board

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    listings = load_board(DOCS)  # merges lazy-detail sidecar back so it round-trips
    before = sum(1 for l in listings if (l.raw or {}).get("sos_agent"))
    # skip leads already carrying an agent record so repeat runs advance the frontier
    todo = [l for l in listings if not (l.raw or {}).get("sos_agent")]
    print(f"loaded {len(listings)} | already have sos_agent={before} | candidates={len(todo)}", flush=True)

    stats = asyncio.run(enrich_with_sos_agent(listings))
    print("sos_agent:", stats, flush=True)

    after = sum(1 for l in listings if (l.raw or {}).get("sos_agent"))
    with_contact = sum(1 for l in listings
                       if ((l.raw or {}).get("sos_agent") or {}).get("best_contact_name"))
    write_artifact(listings, {"notes": "scheduled NC SOS registered-agent refresh"}, docs_dir=DOCS)
    print(f"wrote board | sos_agent={after}(+{after - before}) with_contact={with_contact}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
