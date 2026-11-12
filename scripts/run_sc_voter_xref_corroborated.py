#!/usr/bin/env python3
"""SC phone via the NC voter file — ONLY where NC residency is corroborated.

WHY A GUARDED VARIANT EXISTS
    enrichment_sc_voter_xref matches an SC property owner to an NC voter on FIRST +
    LAST NAME ALONE, across state lines. Measured on a random 1,500-row sample it
    hits 8.1%, which extrapolates to ~3,700 phones — but the matches land in Sumter,
    Lexington, Darlington and Williamsburg, the middle of the state. Its safeguard is
    that the name is UNIQUE in the NC voter file, and that is not identity: it means
    one NC voter has that name, not that the SC owner IS them.

    Running it unguarded would put a stranger's number on thousands of leads and
    someone would call an uninvolved person in NC about a house in SC. Wrong contact
    data is worse than none.

WHAT THIS ADDS
    A corroboration requirement: the SC row's OWNER MAILING ADDRESS must itself be in
    NC. Then the owner demonstrably lives in NC, and a unique-name match against the
    NC voter file is evidence rather than coincidence. Verified examples:

        Spartanburg  HUGHES NORMAN T   mails to 1124 TYLER FARMS DR RALEIGH NC
        Spartanburg  RICE CAROLYN J    mails to 749 EDGEHILL RD FAYETTEVILLE NC

    Population: 342 phone-less SC rows with an NC mailing address -> 32 matches
    (9.4%). Small. The ~3,700 figure was almost entirely the unsafe majority.

    Numbers are tagged needs_dnc_scrub=True and additionally carry
    corroboration="nc_mailing_address" so the basis is auditable later.

    python scripts/run_sc_voter_xref_corroborated.py --dry-run
    python scripts/run_sc_voter_xref_corroborated.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import foreclosure_scraper.enrichment_sc_voter_xref as X  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def _om(li) -> dict:
    o = li.raw.get("owner_mailing") if isinstance(li.raw, dict) else None
    return o if isinstance(o, dict) else {}


def _has_phone(li) -> bool:
    return bool(isinstance(li.raw, dict) and (li.raw.get("owner_phone") or {}).get("phone"))


def _nc_mailing(li) -> bool:
    om = _om(li)
    return om.get("mail_state") == "NC" or " NC " in str(om.get("mailing") or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="sc_xref")
    with lock:
        rows = load_board(REPO / "docs")
        n = len(rows)
        targets = [li for li in rows
                   if (li.state or "") == "SC" and li.owner_name
                   and not _has_phone(li) and _nc_mailing(li)]
        print(f"board {n:,} rows")
        print(f"  SC, phone-less, with an NC mailing address: {len(targets):,}")

        X.enrich_sc_phone_xref(targets)
        got = [li for li in targets
               if (li.raw.get("owner_phone") or {}).get("source") == "ncsbe_voter_xref"]
        for li in got:
            # the identity gate (enrichment_sc_phone) is the authority now: its street-level rule is
            # stricter than "any NC mailing address", so only tag phones the gate did not block
            if not li.raw["owner_phone"].get("do_not_dial"):
                li.raw["owner_phone"]["corroboration"] = "nc_mailing_address"
        print(f"  MATCHED: {len(got):,}  ({100*len(got)/max(len(targets),1):.1f}%)")
        for li in got[:6]:
            print(f"    {str(li.county)[:12]:14}{str(li.owner_name)[:28]:30}"
                  f"{str(_om(li).get('mailing'))[:36]}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == n, "row count changed — refusing to write"
        write_artifact(rows, {"sc_xref_corroborated": len(got)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {n:,} rows unchanged, {len(got):,} corroborated phones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
