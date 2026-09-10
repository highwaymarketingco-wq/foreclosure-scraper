#!/usr/bin/env python3
"""Fold the LiensNC related-filings sidecar into the board in ONE write.

The harvest (`liensnc_related_filings.py` via `run_liensnc_related_all.sh`) is
deliberately decoupled from the board: it appends every result to
`logs/liensnc_related.jsonl` and never takes the board lock. That decoupling exists
because the 2026-09-10 run died at batch 5 after ~3 hours of work when the scheduled
`run_daily_vision.sh` held the lock and the batch-end write raised BoardLockBusy --
the network fetching never needed that lock, only the write did.

So this script is the other half: one pass, one lock acquisition, one board write.

WHAT IT MERGES
    raw['liensnc_related'] = {owner_contact{name,phone,email,mailing}, pin,
                              notices[{entry_number, filed_date, status,
                                       claimant{...}, contracted_through}],
                              notice_count}

    A notice_count >= 1 means a supplier or subcontractor filed a Notice to Lien
    Agent against that project to preserve its lien rights -- trade creditors
    circling a job, which is a graded distress signal rather than the routine
    "Appointment of Lien Agent" registration every builder files. The report also
    carries the OWNER's phone, email and mailing address, which is why this matters:
    the board's own outreach export reported with_phone=0.

SAFETY
    * Row count is asserted unchanged; this enriches, it never adds or drops leads.
    * `owner_name` is only filled when blank -- a scraped name always wins.
    * board_lock(REPO), never board_lock(DOCS): passing the docs dir creates a
      phantom lock at docs/logs/.board.lock that excludes nothing, which is how a
      concurrent job silently reverted an earlier repair.
    * `liensnc_related` is in web_artifact.RAW_KEEP, so it survives the publish slim.
      It was NOT, originally, and 1,500 harvested entries were discarded at write
      time with no error; tests/test_raw_keep_covers_enrichers.py now guards that.

Run with --dry-run first.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

SIDECAR = REPO / "logs" / "liensnc_related.jsonl"


def load_sidecar() -> dict[str, dict]:
    """entry_number -> record. Later lines win, so a re-fetch supersedes."""
    out: dict[str, dict] = {}
    bad = 0
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            ent = str(rec.get("entry_number") or "").strip()
            if ent:
                out[ent] = rec
    if bad:
        print(f"  warning: {bad} unparseable sidecar lines skipped")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    side = load_sidecar()
    print(f"sidecar: {len(side):,} captured entries")
    if not side:
        print("nothing to merge.")
        return 0

    with_phone = sum(1 for r in side.values()
                     if (r.get("owner_contact") or {}).get("phone"))
    with_email = sum(1 for r in side.values()
                     if (r.get("owner_contact") or {}).get("email"))
    with_mail = sum(1 for r in side.values()
                    if (r.get("owner_contact") or {}).get("mailing"))
    notices = sum(int(r.get("notice_count") or 0) for r in side.values())
    print(f"  owner phone {with_phone:,} | email {with_email:,} | mailing {with_mail:,}")
    print(f"  supplier notices total {notices:,}")

    # A --dry-run is READ-ONLY, so it must not take the write lock. Taking it made the
    # dry-run unusable exactly when it is most wanted: while the scheduled
    # run_daily_vision.sh holds the board for hours. Only the real write needs it.
    import contextlib
    _lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO)
    with _lock:
        listings = load_board(REPO / "docs")
        before = len(listings)
        print(f"board rows: {before:,}")

        stats = Counter()
        # Which sidecar entries actually found a board row. A count subtraction gives
        # a NEGATIVE "unmatched" here, because several board rows share one
        # entry_number -- the pool carries both `liensnc` and
        # `counties_generic.liensnc` copies of the same filing, so 14,980 entries
        # matched 17,096 rows. It has to be a set difference.
        hit_entries: set = set()
        for li in listings:
            raw = li.raw if isinstance(li.raw, dict) else {}
            ln = raw.get("liensnc") if isinstance(raw.get("liensnc"), dict) else {}
            ent = str(ln.get("entry_number") or "").strip()
            if not ent or ent not in side:
                continue
            rec = side[ent]
            stats["matched"] += 1
            hit_entries.add(ent)
            oc = rec.get("owner_contact") or {}
            # Count what WOULD change even on a dry run -- a preview that reports
            # zeros for the two things you most want to check is not a preview.
            would_fill = bool(oc.get("name")) and not (li.owner_name or "").strip()
            if would_fill:
                stats["owner_name_filled"] += 1
            if int(rec.get("notice_count") or 0) >= 1:
                stats["with_supplier_notice"] += 1
            if oc.get("phone"):
                stats["gains_owner_phone"] += 1
            if oc.get("mailing"):
                stats["gains_owner_mailing"] += 1
            if args.dry_run:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["liensnc_related"] = {k: v for k, v in rec.items()
                                         if k != "entry_number"}
            if would_fill:
                li.owner_name = oc["name"]

        print(f"\nmatched board rows            : {stats['matched']:,}")
        print(f"  from sidecar entries         : {len(hit_entries):,} "
              f"({stats['matched'] / max(len(hit_entries), 1):.2f} board rows per entry)")
        print(f"  gain an owner PHONE          : {stats['gains_owner_phone']:,}")
        print(f"  gain an owner MAILING        : {stats['gains_owner_mailing']:,}")
        print(f"  owner_name filled where blank: {stats['owner_name_filled']:,}")
        print(f"  >=1 supplier notice on them  : {stats['with_supplier_notice']:,}")
        missed = set(side) - hit_entries
        if missed:
            print(f"  sidecar entries with NO board row: {len(missed):,} "
                  f"(entry left the board since capture)")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(listings) == before, "merge must not change the row count"
        write_artifact(listings, {
            "total": len(listings),
            "notes": (f"liensnc_related sidecar merge: {stats['matched']:,} rows, "
                      f"{with_phone:,} owner phones, {with_mail:,} mailings, "
                      f"{notices:,} supplier notices"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
