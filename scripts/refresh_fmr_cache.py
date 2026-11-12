#!/usr/bin/env python3
"""Refresh the HUD Fair Market Rent table the run applies offline (audit 2026-10-09, unwired_enrichers).

The tail step enrichment_tail_extras.enrich_local_pre_gate reads data/fmr_cache/fmr_by_county.json
and never calls HUD. This refreshes that file from the HUD FMR API (HUD_API_TOKEN in the
environment or .env; about 2 calls per state plus 1 a second per non-metro county, a few minutes).
A failed or empty answer keeps the old table. Schedule: monthly on the Mac (HUD publishes the new
fiscal year's FMRs once a year, effective October 1), then the usual copy of data/ to the VM.

    uv run python scripts/refresh_fmr_cache.py            # refresh when the table is 30+ days old
    uv run python scripts/refresh_fmr_cache.py --force    # refresh now
Exit 0 refreshed or still fresh, 1 no table after the attempt.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper import enrichment_hud_fmr as H  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    before = H._CACHE_FILE.stat().st_mtime if H._CACHE_FILE.exists() else None
    H._load_fmr_data(force=a.force)
    if not H._CACHE_FILE.exists():
        print("no FMR table after the refresh attempt (check HUD_API_TOKEN)", file=sys.stderr)
        return 1
    d = json.loads(H._CACHE_FILE.read_text())
    years = sorted({str(v.get("year")) for v in list((d.get("county_rent") or {}).values())
                    + list((d.get("metro_rent") or {}).values())})
    after = H._CACHE_FILE.stat().st_mtime
    print(f"{H._CACHE_FILE}: {len(d.get('county_rent') or {})} counties, {len(d.get('metro_rent') or {})} "
          f"metros, FMR year(s) {', '.join(years)}, cached_at {d.get('cached_at')} "
          f"({'refreshed' if after != before else 'unchanged'}; {datetime.now():%Y-%m-%d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
