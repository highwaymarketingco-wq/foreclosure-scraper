#!/usr/bin/env python3
"""The built-but-low-yield bucket is the single biggest one in the gap list -- 6,498 of 11,252
cells tonight, 58%. It is a completely different motion from the discovery/build loop the other
buckets need: the source and the code already exist for every cell in this bucket; what's
missing is just RUNNING the existing backfill/enrichment/verifier against the rows that never
got swept. This script extracts that bucket alone, as a ranked work queue, so it's a standing
answer to "what's already built that just needs running" instead of re-deriving it from a raw
gap_list CSV grep each time.

It does NOT try to tell you how to run each one -- next_action already has that (reused
verbatim) -- it just ranks and groups so the biggest real opportunities surface first.

Usage: python scripts/low_yield_queue.py [--gap-list PATH] [--out PATH] [--top N]
Reads the most recent gap_list_*.csv in docs/gap_matrix/ by default.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _latest_gap_list(docs_gap_matrix: Path) -> Path:
    cands = sorted(docs_gap_matrix.glob("gap_list_*.csv"))
    if not cands:
        raise SystemExit(f"no gap_list_*.csv found in {docs_gap_matrix}")
    return cands[-1]


def build(gap_list: Path) -> list[dict]:
    rows = []
    with gap_list.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("gap_class", "") != "built-but-low-yield":
                continue
            rows.append({
                "state": row["state"], "county": row["county"], "column": row["column"],
                "applicable": int(row["applicable"] or 0), "target": int(row["target"] or 0),
                "pct": float(row["pct"] or 0), "est_rows_affected": int(row["est_rows_affected"] or 0),
                "next_action": row.get("next_action", ""), "source": row.get("source", ""),
            })
    rows.sort(key=lambda r: -r["est_rows_affected"])
    return rows


def render_markdown(rows: list[dict], gap_list: Path, top: int) -> str:
    total = sum(r["est_rows_affected"] for r in rows)
    lines = [
        "# Built-but-low-yield work queue",
        "",
        f"Generated from `{gap_list.name}`. Regenerate with "
        "`python scripts/low_yield_queue.py` any time the gap list changes -- this file is a "
        "derived view, not hand-maintained.",
        "",
        "Every row here already has a working reader/enrichment/verifier -- the gap is "
        "coverage, not code. `next_action` names the existing script/sweep to run; "
        "`check-before-building` still applies if the next_action text is wrong or stale (it's "
        "a heuristic guess, not ground truth) -- confirm what's actually wired before assuming "
        "a rewrite is needed.",
        "",
        f"**{len(rows):,} cells, {total:,} total est_rows_affected.**",
        "",
        f"## Top {top} by est_rows_affected",
        "",
        "| state | county | column | pct done | est_rows left | next_action |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows[:top]:
        lines.append(f"| {r['state']} | {r['county']} | {r['column']} | {r['pct']:.1f}% | "
                     f"{r['est_rows_affected']:,} | {r['next_action'][:120]} |")
    lines.append("")

    by_col: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_col[r["column"]].append(r)
    lines.append("## Rolled up by column (which existing readers have the most unswept rows)")
    lines.append("")
    lines.append("| column | cells | total est_rows_affected |")
    lines.append("|---|---|---|")
    col_totals = sorted(by_col.items(), key=lambda kv: -sum(r["est_rows_affected"] for r in kv[1]))
    for col, col_rows in col_totals[:40]:
        lines.append(f"| {col} | {len(col_rows):,} | "
                     f"{sum(r['est_rows_affected'] for r in col_rows):,} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-list", default="")
    ap.add_argument("--out", default=str(REPO / "docs" / "gap_matrix" / "low_yield_queue.md"))
    ap.add_argument("--top", type=int, default=150)
    args = ap.parse_args(argv)

    gap_matrix_dir = REPO / "docs" / "gap_matrix"
    gap_list = Path(args.gap_list) if args.gap_list else _latest_gap_list(gap_matrix_dir)
    rows = build(gap_list)
    out_path = Path(args.out)
    out_path.write_text(render_markdown(rows, gap_list, args.top))
    print(f"wrote {out_path}")
    print(f"  {len(rows):,} cells, {sum(r['est_rows_affected'] for r in rows):,} "
          f"total est_rows_affected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
