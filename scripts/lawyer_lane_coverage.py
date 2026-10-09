"""Per-item coverage of the attorney's quiet-title list (lawyer_lane.items), by group and county.

  uv run python scripts/lawyer_lane_coverage.py --board <board.json.gz or docs dir> [--out JSON]
        [--sample-out PRIVATE.jsonl --per-county 12]

Groups: the call-ready lanes as published on the row (raw.call_ready.lane A..E) and the quiet-title
candidate classes (lawyer_lane.candidate_classes: heir_estate, elderly_long, tax2_unclear; and
quiet_title_any, their union). For each group x county x item it counts rows whose item is
sourced (and dated), missing, walled or n/a. One streamed pass (board_stream), counters only.

--out writes counts only (public-safe). --sample-out writes, OUTSIDE the repository, a capped
sample of quiet-title candidates in counties whose register a platform adapter reads (parcel,
county, owner name, the county record's last sale): the input for the chain-precision check and
the intake runs. It refuses a path inside the repository (owner names).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import lawyer_lane as LL  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402


def _inside_repo(p: Path) -> bool:
    try:
        p.resolve().relative_to(REPO)
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--out", help="counts JSON (public-safe)")
    ap.add_argument("--sample-out", help="private JSONL of candidate leads (outside the repo)")
    ap.add_argument("--per-county", type=int, default=12)
    a = ap.parse_args(argv)
    if a.sample_out and _inside_repo(Path(a.sample_out)):
        print("Refusing to write owner names inside the repository.", file=sys.stderr)
        return 2
    today = date.today()
    cnt: Counter = Counter()          # (group, state, county, item, status)
    rows_by: Counter = Counter()      # (group, state, county)
    complete: Counter = Counter()     # (group, state, county)
    sample: dict = defaultdict(list)
    n = 0
    for r in iter_board_rows(a.board):
        n += 1
        raw = r.get("raw") or {}
        cr = raw.get("call_ready") if isinstance(raw.get("call_ready"), dict) else {}
        groups = []
        if cr.get("lane"):
            groups.append("lane_" + cr["lane"])
        cls = LL.candidate_classes(r, cr)
        groups += ["cand_" + c for c in cls]
        if cls:
            groups.append("quiet_title_any")
        if not groups:
            continue
        its = LL.items(r, today)
        st, co = str(r.get("state") or "").upper(), str(r.get("county") or "").strip().title()
        full = LL.complete(its)
        for g in groups:
            rows_by[(g, st, co)] += 1
            complete[(g, st, co)] += full
            for k, v in its.items():
                cnt[(g, st, co, k, v["status"])] += 1
        if a.sample_out and cls and r.get("parcel_id") and str(r.get("owner_name") or "").strip() \
                and LL.register_adapter(co, st):
            key = (st, co)
            if len(sample[key]) < a.per_county:
                ls = LL.county_deed_ref(r)
                sample[key].append({"state": st, "county": co, "parcel_id": r.get("parcel_id"),
                                    "owner_name": r.get("owner_name"), "classes": cls, "lane": cr.get("lane"),
                                    "tier": cr.get("tier"), "last_sale": ls,
                                    "items": LL.published(its), "id": r.get("id") or r.get("listing_id")})
    groups = sorted({k[0] for k in rows_by})
    out = {"board": str(a.board), "rows": n, "computed_on": today.isoformat(), "groups": {}}
    for g in groups:
        tot = sum(v for k, v in rows_by.items() if k[0] == g)
        per_item = {it: {s: sum(v for k, v in cnt.items() if k[0] == g and k[3] == it and k[4] == s)
                         for s in ("sourced", "missing", "walled", "n/a")} for it in LL.ITEMS}
        by_county = {}
        for (gg, st, co), c in sorted(rows_by.items(), key=lambda kv: -kv[1]):
            if gg != g:
                continue
            by_county[f"{st}|{co}"] = {"rows": c, "complete": complete[(gg, st, co)],
                                       **{it: cnt[(gg, st, co, it, "sourced")] for it in LL.ITEMS}}
        out["groups"][g] = {"rows": tot, "complete": sum(v for k, v in complete.items() if k[0] == g),
                            "items": per_item, "by_county": by_county}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    for g in groups:
        G = out["groups"][g]
        print(f"{g:22s} rows {G['rows']:>7,}  complete {G['complete']:>5}  " +
              "  ".join(f"{it}:{G['items'][it]['sourced']}" for it in LL.ITEMS))
    if a.sample_out:
        p = Path(a.sample_out).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            for key in sorted(sample):
                for s in sample[key]:
                    f.write(json.dumps(s, default=str) + "\n")
        print(f"sample: {sum(len(v) for v in sample.values())} leads in {len(sample)} counties -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
