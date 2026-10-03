"""Local (no-network) accuracy check on the bankruptcy_stay signal: does the
real bankruptcy debtor name (raw.bankruptcy_stay.case) actually match the
property's owner_name, or is it a weak fuzzy/token match to an unrelated
person? Entirely derivable from data already on the board -- fast and exhaustive.
"""
import re
import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper import web_artifact

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")

STOPWORDS = {"AND", "JR", "SR", "III", "II", "ETAL", "ET", "AL", "THE", "A"}


def tokens(s):
    if not s:
        return set()
    toks = set(re.findall(r"[A-Z]{2,}", s.upper()))
    return toks - STOPWORDS


def main():
    n = 0
    flagged = 0
    rows = []
    for rec in web_artifact._iter_board_records(DOCS):
        n += 1
        raw = rec.get("raw") or {}
        bs = raw.get("bankruptcy_stay")
        lt = rec.get("listing_type")
        is_bk = (isinstance(bs, dict) and bs) or lt == "bankruptcy"
        if not is_bk:
            continue
        flagged += 1
        if not isinstance(bs, dict):
            continue
        case_name = bs.get("case") or ""
        owner = rec.get("owner_name") or rec.get("defendant") or ""
        ot, ct = tokens(owner), tokens(case_name)
        if not ot or not ct:
            overlap = None
        else:
            overlap = len(ot & ct) / max(1, min(len(ot), len(ct)))
        rows.append({
            "county": rec.get("county"), "state": rec.get("state"),
            "owner_name": owner, "bankruptcy_case_name": case_name,
            "court": bs.get("court"), "docket": bs.get("docket"),
            "overlap": overlap,
        })
        if n % 50000 == 0:
            print(f"...{n}", file=sys.stderr)

    print(f"Total rows scanned: {n}", file=sys.stderr)
    print(f"Total bankruptcy_stay-flagged rows: {flagged}", file=sys.stderr)
    print(f"Rows with both owner_name and case name present: {len(rows)}", file=sys.stderr)

    no_overlap = [r for r in rows if r["overlap"] == 0]
    weak = [r for r in rows if r["overlap"] is not None and 0 < r["overlap"] < 1.0]
    full = [r for r in rows if r["overlap"] == 1.0]
    unknown = [r for r in rows if r["overlap"] is None]

    print(f"\nZERO token overlap (owner and bankruptcy debtor share NO name token at all): {len(no_overlap)}/{len(rows)} ({100*len(no_overlap)/max(1,len(rows)):.1f}%)", file=sys.stderr)
    print(f"PARTIAL overlap (shares some but not all tokens -- the Hundley/Kilpatrick false-positive pattern): {len(weak)}/{len(rows)} ({100*len(weak)/max(1,len(rows)):.1f}%)", file=sys.stderr)
    print(f"FULL token overlap (every owner token found in case name): {len(full)}/{len(rows)} ({100*len(full)/max(1,len(rows)):.1f}%)", file=sys.stderr)
    print(f"Unparseable (no tokens either side): {len(unknown)}/{len(rows)}", file=sys.stderr)

    Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/bankruptcy_namematch_results.json").write_text(
        json.dumps(rows, indent=2, default=str)
    )

    print("\nSample of ZERO-overlap rows (owner vs bankruptcy case name):", file=sys.stderr)
    for r in no_overlap[:15]:
        print(f"  owner={r['owner_name']!r:45s}  case={r['bankruptcy_case_name']!r}", file=sys.stderr)

    by_county = Counter((r["state"], r["county"]) for r in no_overlap)
    print("\nZero-overlap rows by state/county (top 10):", file=sys.stderr)
    for (st, co), cnt in by_county.most_common(10):
        print(f"  {st}-{co}: {cnt}", file=sys.stderr)


if __name__ == "__main__":
    main()
