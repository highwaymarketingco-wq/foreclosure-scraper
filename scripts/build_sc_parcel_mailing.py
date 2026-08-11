#!/usr/bin/env python
"""Build the SC bulk owner + MAILING + situs table (Spartanburg + Anderson).

Cached: skips all transfer when the local copy is inside the TTL
(FORECLOSURE_SC_ROLL_TTL_DAYS, default 7) and skips the 123 MB Spartanburg CSV
download when its ETag/Last-Modified/Content-Length is unchanged.

Usage:
  python scripts/build_sc_parcel_mailing.py                 # all counties, cached
  python scripts/build_sc_parcel_mailing.py SC:Anderson     # one county
  python scripts/build_sc_parcel_mailing.py --force         # ignore TTL/ETag
  python scripts/build_sc_parcel_mailing.py --max-rows 5000 # quick smoke
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.sc_parcel_mailing import (  # noqa: E402
    SC_ROLLS, build_mailing_table, get_meta,
)


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    max_rows = None
    if "--max-rows" in args:
        max_rows = int(args[args.index("--max-rows") + 1])
    only = [tuple(a.split(":", 1)) for a in args if ":" in a and not a.startswith("-")]
    for state, county in (only or list(SC_ROLLS)):
        n = build_mailing_table(state, county, force=force, max_rows=max_rows)
        meta = get_meta(state, county) or {}
        print(f"{state}:{county}: {n} parcels  (fetched_at={meta.get('fetched_at')} "
              f"etag={str(meta.get('etag'))[:24]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
