#!/usr/bin/env python
"""Build the SC CAMA value+specs table from county Open Data Hub Assessor CSVs.

Run monthly. Usage: python scripts/build_sc_assessor_cama.py [SC:Spartanburg ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.sc_assessor_cama import SC_CAMA, build_cama_table  # noqa: E402


def main() -> int:
    only = [tuple(a.split(":", 1)) for a in sys.argv[1:] if ":" in a]
    for state, county in (only or list(SC_CAMA)):
        n = build_cama_table(state, county)
        print(f"{state}:{county}: stored {n} CAMA parcels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
