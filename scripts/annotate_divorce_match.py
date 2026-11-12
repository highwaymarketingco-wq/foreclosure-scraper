#!/usr/bin/env python3
"""Stamp raw['divorce']['match'] ('agrees' | 'conflict' | 'unverified') on every divorce hit.

A divorce hit is a NAME match on a court party. Audit 2026-09-21: where both the owner and the
matched party carry a middle initial, 41% disagree, which means a different person with the same
first and last name. The scorer already skips the signal on a proven conflict; this stamps the
verdict on the hit itself so anyone filtering the board can see it. Offline, no network.

    python scripts/annotate_divorce_match.py            # streams the board, counts only
    python scripts/annotate_divorce_match.py --apply    # ONLY board process
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.name_normalize import party_middle_verdict  # noqa: E402


def verdict_for(owner, divorce) -> str | None:
    """None when there is no hit to annotate."""
    if not isinstance(divorce, dict) or not divorce.get("case_count"):
        return None
    return party_middle_verdict(owner, [c.get("parties") for c in (divorce.get("cases") or []) if isinstance(c, dict)])


def _dry_run() -> int:
    from foreclosure_scraper.board_stream import iter_board_rows
    c: Counter = Counter()
    for r in iter_board_rows():
        v = verdict_for(r.get("owner_name"), (r.get("raw") or {}).get("divorce"))
        if v:
            c[v] += 1
    for k, n in c.most_common():
        print(f"  {n:6,}  {k}")
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    if not ap.parse_args().apply:
        return _dry_run()
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner="annotate_divorce_match"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        c: Counter = Counter()
        for li in rows:
            raw = li.raw if isinstance(li.raw, dict) else {}
            v = verdict_for(li.owner_name, raw.get("divorce"))
            if v:
                raw["divorce"]["match"] = v
                c[v] += 1
        assert len(rows) == n
        write_artifact(rows, {"annotate_divorce_match": dict(c)}, docs_dir=REPO / "docs")
        print(f"annotated {sum(c.values()):,} divorce hits {dict(c)}; wrote board: {n:,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
