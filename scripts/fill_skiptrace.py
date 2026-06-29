#!/usr/bin/env python
"""Apply paid skip-trace (phones+emails) to the persisted board. No-op + no cost unless
SKIPTRACE_API_KEY is set. Then: export SKIPTRACE_API_KEY=... && python scripts/fill_skiptrace.py
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_skiptrace import enrich_skiptrace
from foreclosure_scraper.web_artifact import write_artifact
DOCS = Path(__file__).resolve().parent.parent / "docs"
async def main():
    raw = json.loads((DOCS/"listings.json").read_text())
    leads = []
    for d in raw:
        try: leads.append(Listing.model_validate(d))
        except Exception: pass
    s = await enrich_skiptrace(leads)
    print("skiptrace:", s)
    if s.get("enabled") and (s.get("phones") or s.get("emails")):
        write_artifact(leads, {"notes": "skip-trace phones/emails (DNC-gated)"}, docs_dir=DOCS)
        print("wrote board")
    else:
        print("no key / no hits -> board unchanged")
raise SystemExit(asyncio.run(main()))
