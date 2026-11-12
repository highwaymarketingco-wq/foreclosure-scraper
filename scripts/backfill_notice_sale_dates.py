#!/usr/bin/env python3
"""Recover the SALE DATE from NC foreclosure-notice preview text.

WHY
    The NC press-association notices land with sale_date EMPTY on 310 of 310 rows,
    because the full body is behind a reCAPTCHA gate and only the ~300-char preview
    parses. But the preview often begins "NOTICE OF FORECLOSURE SALE Date of Sale:
    <date>" — the date is right there in text we already hold, unparsed.

    Without a sale date a foreclosure is not actionable: it cannot be sorted by
    urgency, and it never appears in the future-dated call list.

WHY ONLY THE EXPLICIT CUE
    A foreclosure notice contains SEVERAL dates — the deed of trust date, the
    recording date, the sale date. 103 of 310 previews contain some date, but only
    45 label one "Date of Sale". Taking any date would silently stamp deed dates as
    auction dates, which is worse than leaving the field empty: someone would drive
    to a sale that already happened, or miss one that had not.

    So this matches ONLY an explicit "Date of Sale" (or "sale ... will be held on")
    cue. The other 58 are left alone and reported.

    python scripts/backfill_notice_sale_dates.py --dry-run
    python scripts/backfill_notice_sale_dates.py
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

_MONTH = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December")
# Explicit cue only. Both orders seen in real notices.
_CUE = re.compile(
    rf"(?:Date\s+of\s+Sale|sale\s+(?:will\s+be\s+held|is\s+scheduled)\s+(?:on|for))"
    rf"\s*:?\s*((?:{_MONTH})\s+\d{{1,2}},?\s+20\d{{2}})", re.I)
_ANY = re.compile(rf"(?:{_MONTH})\s+\d{{1,2}},?\s+20\d{{2}}", re.I)


def parse_sale_date(text: str) -> str | None:
    m = _CUE.search(text or "")
    if not m:
        return None
    raw = re.sub(r",", "", m.group(1)).strip()
    for fmt in ("%B %d %Y",):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="sale_date")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        targets = [li for li in rows
                   if not li.sale_date
                   and "notices" in (li.source or "")
                   and (li.description or "")]
        print(f"notice rows with no sale_date: {len(targets):,}")

        c = Counter()
        ex: list[str] = []
        today = datetime.utcnow().date().isoformat()
        for li in targets:
            d = parse_sale_date(li.description or "")
            if not d:
                if _ANY.search(li.description or ""):
                    c["has a date but NO explicit cue (left alone)"] += 1
                else:
                    c["no date in preview"] += 1
                continue
            c["sale_date recovered"] += 1
            if d >= today:
                c["  of which FUTURE-dated (actionable)"] += 1
            if len(ex) < 8:
                ex.append(f"{(li.county or '?'):14}{d}  {(li.case_number or '')[:18]}")
            if not args.dry_run:
                li.sale_date = d

        for k, v in c.most_common():
            print(f"  {k:44} {v:,}")
        print("\nexamples:")
        for e in ex:
            print("   ", e)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"notice_sale_dates": c["sale_date recovered"]},
                       docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
