"""Pull NC + SC bankruptcy dockets from CourtListener Search API (REST v4).

Uses the operator's token (in .secrets/courtlistener_token.txt).

The /dockets/ endpoint times out on this network (heavy DB scan), but the
/search/ endpoint is Elasticsearch-backed and returns results instantly.

Endpoint: /search/?court=<id>&type=d&order_by=dateFiled+desc

Board-writer — run alone. Idempotent (dedupes by docket_number).
"""
from __future__ import annotations

import json, os, sys, time, subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
TOKEN_FILE = REPO / ".secrets" / "courtlistener_token.txt"

sys.path.insert(0, str(REPO / "src"))
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.web_artifact import load_board, write_artifact

# Correct bankruptcy court IDs (discovered by paginating all 3,359 courts)
BANKRUPTCY_COURTS = {
    "nceb": "NC Eastern",
    "ncmb": "NC Middle",
    "ncwb": "NC Western",
    "scb":  "SC",
}

# Search API uses camelCase field names vs dockets API snake_case
SEARCH_BASE = "https://www.courtlistener.com/api/rest/v4/search/"


def _curl_json(url: str, headers: dict, timeout: int = 45) -> dict | None:
    """Use curl to fetch JSON from CourtListener API."""
    hdr_args = []
    for k, v in headers.items():
        hdr_args += ["-H", f"{k}: {v}"]
    cmd = ["curl", "-s", "-m", str(timeout)] + hdr_args + [url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _fetch_bankruptcy_search(court: str, max_pages: int = 20) -> list[dict]:
    """Fetch bankruptcy dockets via the search endpoint (Elasticsearch-backed).

    The search endpoint is fast because it uses Elasticsearch, not a DB scan.
    Returns raw search results with camelCase field names.
    """
    token = TOKEN_FILE.read_text().strip()
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    all_results = []
    url = (
        f"{SEARCH_BASE}?court={court}&type=d"
        f"&order_by=dateFiled+desc&page_size=100"
    )
    for page in range(1, max_pages + 1):
        page_url = f"{url}&page={page}"
        print(f"  [{court}] page {page}...", end=" ", flush=True)
        data = _curl_json(page_url, headers, timeout=45)
        if not data:
            print("FAILED (no response)")
            break
        results = data.get("results", [])
        count = data.get("count", 0)
        print(f"{len(results)} results (total: {count:,})")
        if not results:
            break
        all_results.extend(results)
        if not data.get("next"):
            break
        time.sleep(1.2)  # rate limit (5K/hr = ~1.4/s, stay safe)
    return all_results


def _search_to_listing(d: dict) -> Listing | None:
    """Convert a CourtListener search result to a board Listing.

    Search API fields (camelCase): caseName, dateFiled, docketNumber,
    docket_id, court_id, chapter, party, etc.
    """
    case_name = d.get("caseName") or d.get("case_name_full") or ""
    if not case_name:
        return None

    # Bankruptcy cases often show "In re: Debtor Name"
    debtor = case_name
    if case_name.lower().startswith("in re "):
        debtor = case_name[6:].strip()

    court_id = d.get("court_id") or ""
    state = "NC" if court_id.startswith("nc") else "SC" if court_id.startswith("sc") else None
    if not state:
        return None

    now = datetime.utcnow()
    docket_num = d.get("docketNumber") or ""
    docket_id = d.get("docket_id")
    chapter = d.get("chapter")  # search API has this directly!
    parties = d.get("party") or []
    trustee = d.get("trustee_str") or ""

    # Use absolute_url if available
    abs_url = d.get("docket_absolute_url") or ""
    source_url = f"https://www.courtlistener.com{abs_url}" if abs_url else ""

    return Listing(
        source="courtlistener.bankruptcy",
        source_url=source_url,
        state=state,
        street_address=None,  # will be filled by enrichment
        owner_name=debtor,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        first_seen=now,
        last_seen=now,
        description=f"Bankruptcy Ch {chapter or '?'} — {case_name[:100]}",
        raw={
            "courtlistener": {
                "docket_id": docket_id,
                "docket_number": docket_num,
                "case_name": case_name,
                "date_filed": d.get("dateFiled"),
                "date_terminated": d.get("dateTerminated"),
                "court": court_id,
                "court_name": d.get("court"),
                "chapter": str(chapter) if chapter else None,
                "nature_of_suit": d.get("suitNature"),
                "cause": d.get("cause"),
                "parties": parties,
                "trustee": trustee,
                "pacer_case_id": d.get("pacer_case_id"),
            }
        },
    )


def main() -> int:
    print("Fetching bankruptcy dockets via search API (Elasticsearch-backed)")
    all_results = []
    for court_id in BANKRUPTCY_COURTS:
        results = _fetch_bankruptcy_search(court_id, max_pages=20)
        all_results.extend(results)
        print(f"  {court_id} ({BANKRUPTCY_COURTS[court_id]}): {len(results)} dockets")
    print(f"\nTotal dockets fetched: {len(all_results)}")

    if not all_results:
        print("No dockets fetched — API may be down or rate-limited")
        return 1

    # Convert to Listings
    listings = []
    for d in all_results:
        li = _search_to_listing(d)
        if li:
            listings.append(li)
    print(f"Converted to {len(listings)} Listings")

    # Load board and merge
    board = load_board(DOCS)
    board_keys = {
        (li.raw or {}).get("courtlistener", {}).get("docket_number", "").upper()
        for li in board
        if li.source == "courtlistener.bankruptcy"
    }
    net_new = [
        li for li in listings
        if (li.raw or {}).get("courtlistener", {}).get("docket_number", "").upper() not in board_keys
    ]
    board.extend(net_new)
    print(f"Board {len(board) - len(net_new)} -> {len(board)} (+{len(net_new)} net-new bankruptcy)")

    lp, mp = write_artifact(board, {"notes": "courtlistener bankruptcy ingest via search API"}, docs_dir=DOCS)
    print(f"Wrote {lp} ({lp.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
