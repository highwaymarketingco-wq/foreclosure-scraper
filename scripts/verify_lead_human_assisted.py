#!/usr/bin/env python3
"""Operator CLI for the per-lead, human-assisted NC eCourts / NC SOS
verification lane (`src/foreclosure_scraper/verification_human_lane.py`).

See that module's docstring for the full write-up of what this is, why it
exists, and the hard rule it follows: THIS TOOL NEVER SOLVES, BYPASSES, OR
AUTO-COMPLETES A CAPTCHA. It queues the check, opens the real search page in
your own browser, and then STOPS -- you run the search, solve the CAPTCHA (or
bot-check, for NC SOS) yourself, and save the resulting page. Run this script
a second time, pointing it at that saved file, to finish the check.

This is a PER-LEAD, ON-DEMAND tool -- invoke it for one specific lead someone
is about to act on. It is explicitly not a bulk/background sweep (the spec
this implements, docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md
section 4, is explicit that a CAPTCHA step must never be bulk/background).

WRITES THE VERIFICATION LEDGER (2026-10-05, docs/HANDOFF.md item 66): every record
(the step-1 "wall" placeholder and the step-2 verdict) is merged into
docs/handoff/verification/<signal>.json and only those files are committed and pushed;
the VM's next run attaches them to the row as raw['verification'] before scoring. This
script never writes the board. --no-ledger skips the ledger; --no-push (or HANDOFF_PUSH=0)
writes it without git.

Usage
-----
Step 1 -- queue the check for a specific lead (identify it by ANY ONE of
--source-url / --parcel-id / (--case-number [--county]) / --street-address):

    uv run python scripts/verify_lead_human_assisted.py \\
        --parcel-id 9688199972 --county Buncombe

This prints exactly what to search for, opens the NC eCourts Smart Search
portal (and the NC SOS business search, if the party is a business) in your
browser, and writes a `verdict: "wall"` placeholder record to --out (default:
prints to stdout) -- an honest "queued, not yet checked" record, not a guess.

Step 2 -- after you've run the search, solved the CAPTCHA, and saved the
result page (Ctrl+S / Save Page As / "Webpage, HTML only"), finish the check:

    uv run python scripts/verify_lead_human_assisted.py \\
        --parcel-id 9688199972 --county Buncombe \\
        --saved-ecourts-page ~/Downloads/case_detail.html \\
        --out /tmp/verification_result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from foreclosure_scraper import verification_human_lane as lane  # noqa: E402


def _emit(payload, out: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs-dir", default="docs", help="board directory (default: docs)")
    ap.add_argument("--source-url", default=None)
    ap.add_argument("--parcel-id", default=None)
    ap.add_argument("--case-number", default=None)
    ap.add_argument("--street-address", default=None)
    ap.add_argument("--county", default=None, help="disambiguator for case-number/street-address lookups")
    ap.add_argument("--zip", dest="zip_code", default=None)
    ap.add_argument("--saved-ecourts-page", default=None,
                     help="path to the NC eCourts page you saved after clearing the CAPTCHA")
    ap.add_argument("--saved-sos-page", default=None,
                     help="path to the NC SOS business-profile page you saved after clearing the bot-check")
    ap.add_argument("--no-open", action="store_true",
                     help="don't open a browser (print the URL instead) -- e.g. on a headless box")
    ap.add_argument("--out", default=None, help="write JSON result here (default: stdout)")
    ap.add_argument("--no-ledger", action="store_true",
                     help="do not write docs/handoff/verification/<signal>.json")
    ap.add_argument("--no-push", action="store_true",
                     help="write the ledger but do not commit/push it")
    ap.add_argument("--ledger-dir", default=None, help="default docs/handoff/verification")
    args = ap.parse_args()

    try:
        row = lane.find_lead(
            docs_dir=args.docs_dir, source_url=args.source_url, parcel_id=args.parcel_id,
            case_number=args.case_number, street_address=args.street_address,
            county=args.county, zip_code=args.zip_code,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if row is None:
        print("ERROR: no board row matched those identifiers.", file=sys.stderr)
        return 1

    print(f"Found lead: {row.get('street_address') or '(no address)'} "
          f"| {row.get('county')}, {row.get('state')} | {row.get('listing_type')} "
          f"| case={row.get('case_number')}", file=sys.stderr)

    ecourts_spec, sos_spec, scope_error = lane.build_check_specs(row)
    if scope_error:
        print(f"OUT OF SCOPE: {scope_error}", file=sys.stderr)
        return 0

    records = []

    if args.saved_ecourts_page:
        html = lane.read_saved_page(args.saved_ecourts_page)
        record = asyncio.run(lane.verify_ecourts_from_saved_page(html, ecourts_spec, row))
        records.append(record)
    else:
        print("\n--- NC eCourts Smart Search ---", file=sys.stderr)
        for line in ecourts_spec.instructions:
            print(line, file=sys.stderr)
        if not args.no_open:
            lane.open_for_human(ecourts_spec.portal_url)
        records.append(lane.pending_wall_record(ecourts_spec))

    if sos_spec is not None:
        if args.saved_sos_page:
            html = lane.read_saved_page(args.saved_sos_page)
            records.append(lane.parse_saved_sos_page(html, sos_spec))
        else:
            print("\n--- NC Secretary of State business search ---", file=sys.stderr)
            for line in sos_spec.instructions:
                print(line, file=sys.stderr)
            if not args.no_open:
                lane.open_for_human(sos_spec.portal_url)
            records.append(lane.pending_wall_record(sos_spec))

    patch_previews = [lane.build_patch_preview(row, r) for r in records]

    ledger_paths: list[str] = []
    if not args.no_ledger:
        from foreclosure_scraper.verification.ledger import LedgerUnreadable, publish_ledgers
        try:
            for r in records:
                p = lane.record_to_ledger(row, r, directory=Path(args.ledger_dir) if args.ledger_dir else None)
                if str(p) not in ledger_paths:
                    ledger_paths.append(str(p))
        except LedgerUnreadable as exc:
            print(f"ERROR: verification ledger unreadable, not overwritten: {exc}", file=sys.stderr)
            return 1
        print(f"ledger: {', '.join(ledger_paths)}", file=sys.stderr)
        if not args.no_push:
            verdicts = ", ".join(f"{r['signal']} {r['verdict']}" for r in records)
            res, detail = publish_ledgers([Path(p) for p in ledger_paths],
                                          f"verification hand-off (human lane): {verdicts} "
                                          f"[{row.get('county')} {row.get('parcel_id') or row.get('case_number') or ''}]")
            print(f"git: {res} {detail}", file=sys.stderr)

    any_pending = any(r["verdict"] == "wall" for r in records)
    if any_pending:
        print(
            "\nQueued. Re-run this exact command with --saved-ecourts-page "
            "(and --saved-sos-page, if shown above) once you've cleared the "
            "CAPTCHA/bot-check and saved the result page.",
            file=sys.stderr,
        )
    else:
        print(
            "\nDone. The records are in the verification ledger above; the VM's next run "
            "attaches them to this row (raw['verification']). This tool never writes the board.",
            file=sys.stderr,
        )

    _emit({"verification_records": records, "ledger_files": ledger_paths,
           "patch_previews": patch_previews}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
