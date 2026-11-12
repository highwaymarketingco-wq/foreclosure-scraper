#!/usr/bin/env python3
"""Ingest all new scraped data sources into the board and publish.

Merges:
  - /tmp/liensnc_results.json (NC lien filings)
  - /tmp/ncecourts_results.json (NC eCourts foreclosure judgments)
  - /tmp/publicnoticesc_results.json (SC foreclosure notices)
  - /tmp/recap_bulk_results.json (CourtListener RECAP dockets)

Into the existing board via load_board → write_artifact.
"""
import json, os, sys, re, collections
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/src"))
os.environ.setdefault("PYTHONPATH", os.path.expanduser("~/foreclosure-scraper/src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS = Path(os.path.expanduser("~/foreclosure-scraper/docs"))


def _load_json(path):
    if not os.path.exists(path):
        print(f"  SKIP {path} (not found)")
        return []
    with open(path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} records from {path}")
    return data


def ingest_liensnc() -> list[Listing]:
    """Convert LiensNC JSON to Listing objects.

    Field mapping from LiensNC records:
      entry_number -> case_number
      filed_by     -> defendant (lien agent filer)
      address      -> street_address (may contain multi-line text)
      pin          -> parcel_id
      city         -> city
      zip_code     -> zip_code
      filing_date   -> sale_date (lien filing date)
      detail_url   -> source_url
      property_text/owner_text -> raw (full text for later parsing)
    """
    records = _load_json("/tmp/liensnc_results.json")
    listings = []
    for r in records:
        raw = {"liensnc": r}
        # Clean up address — LiensNC returns multi-line text blobs
        addr = r.get("address", "") or ""
        # Extract the first line that looks like a street address
        street = None
        for line in addr.split("\n"):
            line = line.strip()
            if line and any(c.isdigit() for c in line) and len(line) > 5:
                street = line
                break
        if not street:
            street = addr.strip() or None

        city = r.get("city", "") or ""
        # City field sometimes has multi-line text too — take last line
        if "\n" in city:
            city = city.split("\n")[-1].strip()

        # Parse filing date
        fd = r.get("filing_date", "") or ""
        sale_date = None
        if fd:
            try:
                sale_date = datetime.strptime(fd, "%m/%d/%Y")
            except Exception:
                pass

        li = Listing(
            source="counties_generic.liensnc",
            source_url=r.get("detail_url", "https://apps.liensnc.com/scr/"),
            listing_type=ListingType.TAX_LIEN,
            defendant=r.get("filed_by", "") or r.get("owner_text", ""),
            case_number=r.get("entry_number", ""),
            parcel_id=r.get("pin", "") or None,
            street_address=street,
            city=city or None,
            state="NC",
            zip_code=r.get("zip_code", "") or None,
            sale_date=sale_date,
            raw=raw,
        )
        listings.append(li)
    print(f"  → {len(listings)} LiensNC listings")
    return listings


def ingest_ncecourts() -> list[Listing]:
    """Convert NC eCourts judgments to Listing objects."""
    records = _load_json("/tmp/ncecourts_results.json")
    listings = []
    cause_to_type = {
        "CV - Lis Pendens": ListingType.LIS_PENDENS,
        "CV - Claim of Lien": ListingType.LIS_PENDENS,
        "CV - Lien": ListingType.TAX_LIEN,
        "CV - Federal Tax Lien": ListingType.TAX_LIEN,
        "CV - Possession": ListingType.LIS_PENDENS,
    }
    for r in records:
        raw = {"nc_ecourts": r}
        cause = r.get("cause_of_action", "")
        lt = cause_to_type.get(cause, ListingType.UNKNOWN)

        jd = r.get("judgment_date", "")
        sale_date = None
        if jd:
            try:
                sale_date = datetime.fromisoformat(jd.replace("Z", ""))
            except Exception:
                pass

        li = Listing(
            source="nc_ecourts_judgments",
            source_url=r.get("source_url", "https://portal-nc.tylertech.cloud/"),
            listing_type=lt,
            defendant=r.get("defendant", ""),
            plaintiff=r.get("plaintiff", ""),
            case_number=r.get("case_number", ""),
            county=r.get("county", ""),
            state="NC",
            sale_date=sale_date,
            raw=raw,
        )
        listings.append(li)
    print(f"  → {len(listings)} NC eCourts listings")
    return listings


def ingest_publicnoticesc() -> list[Listing]:
    """Convert SC public notice foreclosure data to Listing objects."""
    records = _load_json("/tmp/publicnoticesc_results.json")
    listings = []
    for r in records:
        # Skip records with no useful data
        if not r.get("debtor") and not r.get("case_number"):
            continue
        raw = {"publicnoticesc": r}
        li = Listing(
            source="publicnoticesc",
            source_url=r.get("source_url", "https://www.scpublicnotices.com/"),
            listing_type=ListingType.FORECLOSURE_SALE,
            defendant=r.get("debtor", ""),
            case_number=r.get("case_number", ""),
            county=r.get("county", ""),
            state="SC",
            street_address=r.get("address", "") or None,
            raw=raw,
        )
        listings.append(li)
    print(f"  → {len(listings)} publicnoticesc listings (skipped {len(records)-len(listings)} empty)")
    return listings


def ingest_recap() -> list[Listing]:
    """Convert RECAP bulk dockets to Listing objects."""
    records = _load_json("/tmp/recap_bulk_results.json")
    listings = []
    for r in records:
        raw = {"courtlistener_recap": r}
        court_exact = r.get("court_exact", "") or ""
        state = "NC" if court_exact.startswith("nc") else ("SC" if court_exact.startswith("sc") else None)

        case_name = r.get("caseName", "") or ""
        is_bk = "bankruptcy" in (r.get("court", "") or "").lower()
        lt = ListingType.BANKRUPTCY if is_bk else ListingType.UNKNOWN

        df = r.get("dateFiled", "")
        sale_date = None
        if df:
            try:
                sale_date = datetime.fromisoformat(df.replace("Z", ""))
            except Exception:
                pass

        li = Listing(
            source="courtlistener.recap",
            source_url=r.get("absolute_url", ""),
            listing_type=lt,
            defendant=case_name,
            case_number=r.get("docketNumber", ""),
            state=state,
            sale_date=sale_date,
            raw=raw,
        )
        listings.append(li)
    print(f"  → {len(listings)} RECAP listings")
    return listings


def _dedup_key(li: Listing) -> str:
    if li.case_number:
        return f"{li.source}:{li.case_number}"
    if li.street_address:
        return f"{li.source}:{li.street_address.lower()}"
    return f"{li.source}:{li.defendant}:{li.county}"


def main():
    print("=== INGESTING NEW LEADS INTO BOARD ===\n")

    # Load existing board
    print("Loading existing board...")
    board = load_board(DOCS)
    print(f"  Board size: {len(board)}")

    # Ingest all sources
    print("\nIngesting data sources:")
    new_listings = []
    new_listings.extend(ingest_liensnc())
    new_listings.extend(ingest_ncecourts())
    new_listings.extend(ingest_publicnoticesc())
    new_listings.extend(ingest_recap())

    print(f"\nTotal new listings to add: {len(new_listings)}")

    # Dedup
    existing_keys = set()
    for li in board:
        existing_keys.add(_dedup_key(li))

    added = 0
    for li in new_listings:
        k = _dedup_key(li)
        if k not in existing_keys:
            board.append(li)
            existing_keys.add(k)
            added += 1

    print(f"  Added (after dedup): {added}")
    print(f"  Skipped (duplicates): {len(new_listings) - added}")
    print(f"  New board size: {len(board)}")

    by_state = collections.Counter(li.state for li in board if li.state)
    by_source = collections.Counter(li.source for li in board if li.source)
    summary = {
        "ingestion": "bulk_merge",
        "sources": {
            "liensnc": sum(1 for l in new_listings if l.source == "counties_generic.liensnc"),
            "nc_ecourts": sum(1 for l in new_listings if l.source == "nc_ecourts_judgments"),
            "publicnoticesc": sum(1 for l in new_listings if l.source == "publicnoticesc"),
            "recap": sum(1 for l in new_listings if l.source == "courtlistener.recap"),
        },
        "added_after_dedup": added,
        "total_board_size": len(board),
        "by_state": dict(by_state),
        "by_source": dict(by_source),
        "timestamp": datetime.now().isoformat(),
    }

    print(f"\nWriting board with {len(board)} listings...")
    path, meta = write_artifact(board, summary, DOCS)
    print(f"  Written to: {path}")
    print(f"  Board size: {len(board)} listings")
    print(f"\n=== INGESTION COMPLETE ===")


if __name__ == "__main__":
    main()
