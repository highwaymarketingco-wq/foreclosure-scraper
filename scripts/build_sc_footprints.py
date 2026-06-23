#!/usr/bin/env python
"""Build the SC building-footprint sqft table from Microsoft US Building Footprints.

Run periodically (footprints update infrequently). Usage:
  python scripts/build_sc_footprints.py [SC:Spartanburg ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.sc_building_footprints import COUNTY_BBOX, build_footprints  # noqa: E402


def main() -> int:
    only = [tuple(a.split(":", 1)) for a in sys.argv[1:] if ":" in a]
    for state, county in (only or list(COUNTY_BBOX)):
        n = build_footprints(state, county)
        print(f"{state}:{county}: stored {n} building footprints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
