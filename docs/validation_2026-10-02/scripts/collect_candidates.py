"""Step 1: stream the board and collect every row carrying a truthy
raw['jail_booking'] or raw['jail_booking_new'] signal. Read-only, streamed via
_iter_board_records (never materializes the whole board).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from foreclosure_scraper.web_artifact import _iter_board_records  # noqa: E402

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
OUT = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/"
           "b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/candidates_raw.json")


def main() -> None:
    candidates = []
    n_total = 0
    n_jail_booking = 0
    n_jail_booking_new = 0
    n_both = 0
    county_counts = {}

    for rec in _iter_board_records(DOCS):
        n_total += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        jb = raw.get("jail_booking")
        jbn = raw.get("jail_booking_new")
        if not jb and not jbn:
            continue
        if jb:
            n_jail_booking += 1
        if jbn:
            n_jail_booking_new += 1
        if jb and jbn:
            n_both += 1

        key = (rec.get("state"), jb.get("county") if jb else (jbn or {}).get("county"))
        county_counts[key] = county_counts.get(key, 0) + 1

        candidates.append({
            "defendant": rec.get("defendant"),
            "owner_name": rec.get("owner_name"),
            "state": rec.get("state"),
            "county": rec.get("county"),
            "street_address": rec.get("street_address"),
            "city": rec.get("city"),
            "parcel_id": rec.get("parcel_id"),
            "source": rec.get("source"),
            "owner_mailing": raw.get("owner_mailing"),
            "jail_booking": jb,
            "jail_booking_new": jbn,
        })

    print(f"total board rows scanned: {n_total}")
    print(f"rows with jail_booking: {n_jail_booking}")
    print(f"rows with jail_booking_new: {n_jail_booking_new}")
    print(f"rows with BOTH: {n_both}")
    print(f"total candidate rows: {len(candidates)}")
    print("county breakdown (state, roster_county) -> count:")
    for k, v in sorted(county_counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    OUT.write_text(json.dumps(candidates, indent=2, default=str))
    print(f"\nwrote {len(candidates)} candidates to {OUT}")


if __name__ == "__main__":
    main()
