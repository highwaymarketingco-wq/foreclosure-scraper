#!/usr/bin/env python
"""Ingest a skip-trace / Propwire contact-export CSV onto the board.

Usage:
    uv run python scripts/ingest_contacts.py <export.csv> [--source propwire_export]

Matches each CSV row to a board lead by parcel/APN (preferred) or property address,
stamps raw['contact'] (phones tagged needs_dnc_scrub), and rewrites docs/listings.json.
Compliant: the operator exports from their own skip-trace account; we only ingest.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from foreclosure_scraper.contact_ingest import ingest_contacts
from foreclosure_scraper.web_artifact import write_artifact, load_board


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--source", default="skip_trace_export")
    ap.add_argument("--docs", default="docs")
    args = ap.parse_args()

    docs = Path(args.docs)
    listings = load_board(docs)
    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    stamp = datetime.utcnow().date().isoformat()
    stats = ingest_contacts(listings, rows, source=args.source, ingested_at=stamp)
    print("CONTACT INGEST:", stats, flush=True)
    if stats["matched"]:
        write_artifact(listings, {"notes": f"contact ingest: {args.source}"}, docs_dir=docs)
        print("wrote board", flush=True)
    else:
        print("no matches — board untouched", flush=True)


if __name__ == "__main__":
    main()
