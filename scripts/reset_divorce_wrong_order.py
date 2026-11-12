#!/usr/bin/env python3
"""Clear divorce stamps that were searched with the wrong name order.

Found 2026-09-18: enrichment_sc_divorce._name_parts read every name as county-
GIS SURNAME-FIRST, but court-party / probate-notice sources (sc_public_index,
sc_probate_notices.*) store Title Case FIRST [MIDDLE] LAST. Those leads were
searched as last=KRYSTAL, first=HENDERSON. Live check on 40 sc_public_index
leads: old parser 0 hits, fixed parser 11 (27.5%). So a stamp on such a lead,
whether "no divorce" or a hit, came from the wrong person and must be redone.

Selects SC core-county, non-entity leads that carry raw['divorce'] whose search
the pre-fix parser built differently from the fixed one (so unchanged names are
untouched), removes raw['divorce'] and the 'divorce' distress category it added, and
leaves them in the never-checked pool for backfill_sc_divorce.py to search
correctly. --dry-run (default) only counts. Needs the board in memory: run it as
the ONLY board process.

    python scripts/reset_divorce_wrong_order.py            # count only
    python scripts/reset_divorce_wrong_order.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_sc_divorce import _COUNTY_CODE, _name_parts  # noqa: E402
from foreclosure_scraper.name_normalize import is_entity  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def _old_name_parts(owner: str) -> tuple[str, str]:
    """The parser exactly as it was before the fix: every name read SURNAME-FIRST."""
    o = re.split(r"[;]|<br\s*/?>", owner or "", maxsplit=1)[0]
    o = re.sub(r"[^A-Za-z, ]", " ", o).upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def needs_reset(li) -> bool:
    """True when this lead's stamp came from a search for a different person
    than the one the (fixed) parser now reads. Entity-looking owners are left
    alone: a company cannot be a divorce party, so their stamp stands."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    if not raw.get("divorce"):
        return False
    if li.state != "SC" or (li.county or "").strip() not in _COUNTY_CODE:
        return False
    owner = li.owner_name or ""
    if is_entity(owner):
        return False
    return _old_name_parts(owner) != _name_parts(owner)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with board_lock(REPO, owner="reset_divorce_wrong_order"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        targets = [li for li in rows if needs_reset(li)]
        hits = sum(1 for li in targets if li.raw["divorce"].get("case_count"))
        by_src = Counter(li.source for li in targets)
        print(f"board rows: {n:,}")
        print(f"stamps searched with the wrong name order: {len(targets):,} ({hits} of them recorded hits)")
        for src, c in by_src.most_common(10):
            print(f"  {c:6,}  {src}")
        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return 0

        for li in targets:
            li.raw.pop("divorce", None)
            ds = li.raw.get("distress_stack")
            if isinstance(ds, dict) and isinstance(ds.get("categories"), list):
                ds["categories"] = [c for c in ds["categories"] if c != "divorce"]
        assert len(rows) == n
        write_artifact(rows, {"reset_divorce_wrong_order": {"cleared": len(targets), "hits_cleared": hits}},
                       docs_dir=REPO / "docs")
        print(f"cleared {len(targets):,} stamps ({hits} hits); wrote board: {n:,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
