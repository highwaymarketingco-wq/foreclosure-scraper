#!/usr/bin/env python3
"""Automated FOIA / public-records requests for Vacant-Property Registries and
Demolition Lists (FREE, compliant).

Cities don't publish these online, but under state open-records law they must
hand them over on request. This composes a correct, statute-cited records
request per jurisdiction and (only when YOU pass --send with YOUR own SMTP
credentials) emails the clerk. It is meant to be run on the 1st of each month
via cron/launchd so the lists refresh themselves.

COMPLIANCE / SAFETY:
  * DRY-RUN by default — prints the exact emails it WOULD send, sends nothing.
  * Refuses to send to any target whose `records_email` you haven't verified
    and filled in (no guessed addresses ever leave the machine).
  * Sending requires --send AND FOIA_SMTP_USER / FOIA_SMTP_PASS in the env
    (a Gmail App Password, not your login password). You operate it; the
    scraper never sends mail on its own.
  * Logs every request to a CSV so you have a dated paper trail.

Correct statutes: NC Public Records Act, N.C.G.S. § 132-1 et seq.;
SC Freedom of Information Act, S.C. Code § 30-4-10 et seq.

Usage:
    # see what it would send (safe):
    uv run python scripts/foia_vacant_demolition.py --state sc
    # actually send (you, with your creds):
    FOIA_SMTP_USER=you@gmail.com FOIA_SMTP_PASS=app_pw \
        uv run python scripts/foia_vacant_demolition.py --send --state sc
"""
from __future__ import annotations

import argparse
import csv
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

# --- target jurisdictions: CORE = Western NC + Upstate SC ---------------------
# records_email is intentionally EMPTY. Fill in the VERIFIED clerk / open-records
# email for each (from the city's website) before sending — the script skips any
# target still missing one. `suggested_lookup` points you at where to find it.
TARGETS = [
    # ---- Upstate SC ----
    {"jurisdiction": "City of Spartanburg, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "cityofspartanburg.org -> City Clerk / FOIA"},
    {"jurisdiction": "City of Greenville, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "greenvillesc.gov -> City Clerk / FOIA request"},
    {"jurisdiction": "City of Anderson, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "cityofandersonsc.com -> Municipal Clerk"},
    {"jurisdiction": "City of Union, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "cityofunion.org -> City Clerk"},
    {"jurisdiction": "City of Gaffney, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "cityofgaffney.us -> City Clerk"},
    {"jurisdiction": "City of Greer, SC", "state": "SC", "records_email": "",
     "suggested_lookup": "cityofgreer.org -> City Clerk"},
    # ---- Western NC ----
    {"jurisdiction": "City of Asheville, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "ashevillenc.gov -> Public Records Request"},
    {"jurisdiction": "City of Hendersonville, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "hendersonvillenc.gov -> City Clerk"},
    {"jurisdiction": "City of Shelby, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "cityofshelby.com -> City Clerk"},
    {"jurisdiction": "City of Gastonia, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "gastonianc.gov -> City Clerk / Public Records"},
    {"jurisdiction": "City of Forest City, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "townofforestcity.com -> Town Clerk"},
    {"jurisdiction": "City of Marion, NC", "state": "NC", "records_email": "",
     "suggested_lookup": "marionnc.org -> City Clerk"},
]

_STATUTE = {
    "SC": "the South Carolina Freedom of Information Act (S.C. Code § 30-4-10 et seq.)",
    "NC": "the North Carolina Public Records Act (N.C.G.S. § 132-1 et seq.)",
}


def _body(t: dict) -> str:
    month = date.today().strftime("%B %Y")
    return (
        f"To the City Clerk / Public Records Officer, {t['jurisdiction']}:\n\n"
        f"Under {_STATUTE[t['state']]}, I request a digital copy (CSV or Excel "
        f"if available) of the following current records as of {month}:\n\n"
        f"  1. The Vacant / Abandoned Property Registry (all registered "
        f"properties, with owner name, property address, and registration "
        f"date/status).\n"
        f"  2. The active Demolition / Condemnation list (properties ordered or "
        f"scheduled for demolition, with address and order date).\n\n"
        f"If any records are maintained in a database, a data export is "
        f"preferred over printed copies. Please advise if fees will exceed "
        f"$25.00 before proceeding; otherwise please treat this as a request to "
        f"produce responsive records at minimal cost.\n\n"
        f"Thank you for your time.\n"
    )


def _compose(t: dict, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Public Records Request: Vacant Property Registry & Demolition List"
    msg["From"] = sender or "you@example.com"
    msg["To"] = t["records_email"]
    msg.set_content(_body(t))
    return msg


def main():
    ap = argparse.ArgumentParser(description="Compose/send FOIA vacant+demolition records requests")
    ap.add_argument("--send", action="store_true", help="actually send (needs FOIA_SMTP_USER/PASS)")
    ap.add_argument("--state", choices=["NC", "SC", "nc", "sc"], help="limit to one state")
    ap.add_argument("--log", default="foia_requests_log.csv", help="CSV audit log path")
    args = ap.parse_args()

    state = args.state.upper() if args.state else None
    targets = [t for t in TARGETS if not state or t["state"] == state]
    sender = os.environ.get("FOIA_SMTP_USER", "")

    ready = [t for t in targets if t["records_email"].strip()]
    missing = [t for t in targets if not t["records_email"].strip()]

    print(f"{len(targets)} target(s){' in '+state if state else ''}: "
          f"{len(ready)} with a verified email, {len(missing)} still need one.\n")
    for t in missing:
        print(f"  [FILL EMAIL] {t['jurisdiction']:<32} lookup: {t['suggested_lookup']}")
    if missing:
        print()

    server = None
    if args.send:
        user, pw = os.environ.get("FOIA_SMTP_USER"), os.environ.get("FOIA_SMTP_PASS")
        if not user or not pw:
            print("ERROR: --send needs FOIA_SMTP_USER and FOIA_SMTP_PASS (Gmail App Password) in env.")
            sys.exit(1)
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(user, pw)

    log_rows = []
    for t in ready:
        msg = _compose(t, sender)
        if args.send and server:
            server.send_message(msg)
            status = "SENT"
        else:
            status = "DRY-RUN"
            print(f"--- {status}: {t['jurisdiction']} -> {t['records_email']} ---")
            print(msg.get_content())
        log_rows.append({"date": date.today().isoformat(), "jurisdiction": t["jurisdiction"],
                         "state": t["state"], "to": t["records_email"], "status": status})

    if server:
        server.quit()

    if log_rows:
        exists = Path(args.log).exists()
        with open(args.log, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "jurisdiction", "state", "to", "status"])
            if not exists:
                w.writeheader()
            w.writerows(log_rows)
        print(f"\nLogged {len(log_rows)} request(s) -> {args.log}")
    if not args.send:
        print("\n(DRY-RUN — nothing was sent. Fill in records_email values, then re-run with --send.)")


if __name__ == "__main__":
    main()
