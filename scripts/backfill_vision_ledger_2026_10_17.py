"""One-time backfill: record a doc_ledger 'vision' entry for every board row whose raw['vision']
grade predates the ledger wrapper (doc_ledger lane 'vision' was introduced whole, commit
ab8de34e, 2026-10-08) and was never recorded.

Found 2026-10-17 (gap-sweep wave 6, docs-processed-has-ledger-entry): enrich_with_vision()'s
ledger wrapper only records a row inside its own run's finally block, and _needs_vision()
permanently skips any row whose raw['vision'] is already set -- a row graded before the ledger
existed can never again pass through the record-on-grade path. 158 live rows (national.landandfarm,
counties_nc.buncombe_delinquent_tax/buncombe_elderly, counties_sc.sc_public_index_lis_pendens, and
others whose leads are rarely re-scraped) are structurally orphaned from the ledger forever without
this one-time pass.

Every input this writes is already stored on the row -- no new network calls, no re-grading.

Usage:
  uv run python scripts/backfill_vision_ledger_2026_10_17.py              # write + save
  uv run python scripts/backfill_vision_ledger_2026_10_17.py --dry-run    # count only, no write
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--board", default=str(REPO / "docs"))
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    a = ap.parse_args(argv)

    from audit_suite import published_rows
    from foreclosure_scraper import doc_inventory as _inv
    from foreclosure_scraper import doc_ledger as _dl
    from foreclosure_scraper.enrichment_vision import VISION_LEDGER_VERSION, _ledger_values

    led = _dl.get_ledger("vision")
    seen = 0
    already_ledgered = 0
    no_image_urls = 0
    recorded = 0

    for row in published_rows(Path(a.board), detail_keys=("vision",)):
        raw = row.get("raw")
        if not isinstance(raw, dict):
            continue
        v = raw.get("vision")
        if not isinstance(v, dict) or v.get("_from_ledger"):
            continue
        urls = v.get("_image_urls")
        if not isinstance(urls, list) or not urls:
            no_image_urls += 1
            continue
        seen += 1
        key = _inv.image_set_key(urls)
        if led.get(key):
            already_ledgered += 1
            continue
        if a.dry_run:
            recorded += 1
            continue
        src = row.get("source")
        county = f"{row.get('state') or '?'}:{row.get('county') or '?'}"
        landed = ["condition_tier"] if str(raw.get("condition_source") or "").startswith("vision") else []
        led.record(key, outcome="graded", version=VISION_LEDGER_VERSION,
                   source=src, county=county, provider=v.get("_provider"),
                   landed=landed, values=_ledger_values(v))
        recorded += 1

    if not a.dry_run and recorded:
        led.save()

    print(f"pre-ledger graded rows with an image set: {seen}")
    print(f"already in the ledger (skipped): {already_ledgered}")
    print(f"no _image_urls stored (skipped, cannot key): {no_image_urls}")
    print(f"{'would record' if a.dry_run else 'recorded'}: {recorded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
