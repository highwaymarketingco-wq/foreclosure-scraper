"""CourtListener adversary-proceeding + 363 sale motion scraper.

Builds on the existing bankruptcy scraper. Two distinct high-signal
filings inside the bankruptcy docket:

  1. Motion to lift automatic stay (11 U.S.C. §362)
     The lender is asking the bankruptcy court for permission to
     proceed with foreclosure DESPITE the automatic stay. This is
     the LATEST possible pre-foreclosure indicator — typically
     within 30-60 days of the lender restarting the foreclosure
     process in state court.

  2. Section 363 sale motion (11 U.S.C. §363)
     The bankruptcy estate is selling debtor real estate. Often
     deeply discounted because the trustee wants liquidity over
     market price.

Both are docket entries WITHIN a bankruptcy case (not separate cases),
so this scraper iterates the docket-entries API for each recent
bankruptcy docket pulled by the parent scraper.

Fee impact: free under the standard CourtListener API (this is
publicly-mirrored PACER, no per-page billing).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from .courtlistener_bankruptcy import (
    API_BASE,
    COURTS,
    COURT_STATE,
    LOOKBACK_DAYS,
    PAGE_SIZE,
    _county_from_text,
    _load_token,
)

log = structlog.get_logger()


# Patterns that classify a docket-entry's description text. Order: most
# specific first (lift-stay is more actionable than generic 363 sale).
LIFT_STAY_RE = re.compile(
    r"(?:motion|moves?|application)\s+(?:for|to)\s+relief\s+from\s+(?:the\s+)?automatic\s+stay"
    r"|motion\s+to\s+lift\s+(?:the\s+)?automatic\s+stay"
    r"|relief\s+from\s+stay"
    r"|stay\s+relief\s+motion",
    re.I,
)
# §363 sale motion — must mention 363 and "sale" near each other.
SECTION_363_RE = re.compile(
    r"(?:11\s*U\.?S\.?C\.?\s*(?:section|§)\s*363|section\s*363|§\s*363)"
    r".{0,80}?(?:sale|sell|sold)|"
    r"(?:sale|sell|sold).{0,80}?(?:section\s*363|§\s*363)",
    re.I | re.S,
)


def _classify_entry(description: str) -> str | None:
    """Return 'lift_stay' / '363_sale' / None for a docket-entry description."""
    if not description:
        return None
    if LIFT_STAY_RE.search(description):
        return "lift_stay"
    if SECTION_363_RE.search(description):
        return "363_sale"
    return None


def _entry_blob(entry: dict) -> str:
    """Combine the entry description with each recap_documents description.

    v4 dockets no longer surface the long-form motion text on the entry
    itself; the descriptive text lives on the nested recap_documents. Build
    one blob so the classifier sees the full filing text.
    """
    parts = [entry.get("description") or ""]
    for rd in entry.get("recap_documents") or []:
        if isinstance(rd, dict):
            parts.append(rd.get("description") or "")
    return " ".join(p for p in parts if p)


async def _fetch_docket_entries(c, token: str, docket_id) -> list[dict]:
    """Pull all docket entries for one docket via the v4 docket-entries
    endpoint, paginating on 'next'. Best-effort, never raises."""
    if not docket_id:
        return []
    entries: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/docket-entries/?docket={docket_id}&page_size={PAGE_SIZE}"
    )
    pages = 0
    while next_url and pages < 20:
        try:
            er = await c.get(
                next_url,
                headers={
                    "Authorization": f"Token {token}",
                    "Accept": "application/json",
                },
            )
            if er.status_code != 200:
                break
            edata = er.json()
        except Exception:
            break
        entries.extend(edata.get("results") or [])
        next_url = edata.get("next")
        pages += 1
    return entries


async def _scan_recent_dockets(
    c, token: str, court: str, deadline: float | None = None
) -> list[dict]:
    """Pull dockets from the last N days from one bankruptcy court, then
    for each docket fetch its entries and look for our motion patterns.

    Returns a list of (docket, entry, classification) tuples shaped as
    dicts so the scraper can build Listings.

    Each docket opens a sub-fetch for its entries (v4 docket-entries
    endpoint), so this is request-heavy. ``deadline`` is a monotonic
    wall-clock budget: when reached we stop and return what we have so
    far rather than letting safe_run() hard-timeout the whole run to 0.
    """
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    hits: list[dict] = []
    # Order by -date_modified, not default -date_filed: lift-stay / §363
    # motions land WEEKS after a case opens, so the dockets carrying them
    # are the recently-TOUCHED ones, not the newest-filed. Newest-filed
    # dockets are mostly skeletal (no RECAP entries mirrored yet) and just
    # burn the entries-fetch budget. This ordering puts entry-bearing
    # dockets first so the budget reaches actual motions.
    next_url: str | None = (
        f"{API_BASE}/dockets/?court={court}&date_filed__gte={cutoff}"
        f"&order_by=-date_modified&page_size={PAGE_SIZE}"
    )
    pages = 0
    # Cap docket-detail traversal harder than pagination (each docket
    # opens a sub-fetch for entries). 2000 dockets/court is plenty.
    docket_cap = 2000
    seen_dockets = 0

    while next_url and pages < 20:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            r = await c.get(
                next_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            )
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as exc:
            log.warning("courtlistener_adv.error",
                        court=court, error=str(exc)[:120])
            break

        for docket in data.get("results", []):
            if seen_dockets >= docket_cap:
                break
            if deadline is not None and time.monotonic() >= deadline:
                next_url = None
                break
            seen_dockets += 1
            docket_id = docket.get("id")
            entries = await _fetch_docket_entries(c, token, docket_id)
            for entry in entries:
                cls = _classify_entry(_entry_blob(entry))
                if cls:
                    hits.append({
                        "docket": docket,
                        "entry": entry,
                        "classification": cls,
                    })
        next_url = data.get("next")
        pages += 1

    return hits


class CourtListenerAdversary(BaseScraper):
    """Lift-stay motions + §363 sale motions inside NC + SC bankruptcy
    dockets. Each is its own Listing (one bankruptcy can produce
    multiple high-signal entries)."""

    slug = "national.courtlistener_adversary"
    name = "CourtListener bankruptcy adversary (lift stay + 363 sale)"
    category = "federal_court"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        token = _load_token()
        if not token:
            log.info("courtlistener_adv.no_token")
            return []

        out: list[Listing] = []
        seen: set[tuple[str, int, str]] = set()

        # Stay inside safe_run()'s soft timeout: the per-docket entries
        # fetch is request-heavy, so budget a wall-clock deadline ~30s
        # under timeout_s and return partial hits rather than getting
        # hard-killed to 0. Split the remaining budget across courts so
        # one slow court can't starve the others.
        deadline = time.monotonic() + max(self.timeout_s - 30.0, 30.0)

        async with client(timeout=30.0) as c:
            for i, court in enumerate(COURTS):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                courts_left = len(COURTS) - i
                court_deadline = time.monotonic() + remaining / courts_left
                hits = await _scan_recent_dockets(c, token, court, court_deadline)
                for h in hits:
                    docket = h["docket"]
                    entry = h["entry"]
                    cls = h["classification"]

                    docket_no = (docket.get("docket_number") or "").strip()
                    case_name = docket.get("case_name") or ""
                    state_default = COURT_STATE.get(court, "NC")
                    state_match, county_match = _county_from_text(case_name)

                    # Dedup on (court, docket_id, entry_id)
                    key = (
                        court, docket.get("id") or 0,
                        str(entry.get("id") or "") + ":" + cls,
                    )
                    if key in seen:
                        continue
                    seen.add(key)

                    label = {
                        "lift_stay": "Motion for Relief from Automatic Stay",
                        "363_sale": "§363 Real-Property Sale Motion",
                    }[cls]
                    desc = (
                        f"{label} filed {entry.get('date_filed') or '?'} in "
                        f"bankruptcy {docket_no} ({court.upper()}) — "
                        f"Debtor: {case_name[:120]}"
                    )[:500]

                    out.append(Listing(
                        source=self.slug,
                        source_url=("https://www.courtlistener.com" + docket["absolute_url"]) if docket.get("absolute_url") else "",
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state_match or state_default,
                        county=county_match,
                        case_number=docket_no or None,
                        defendant=case_name[:200] or None,
                        description=desc,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"courtlistener_adversary": {
                            "court": court,
                            "classification": cls,
                            "docket_number": docket_no,
                            "case_name": case_name,
                            "entry_description": (entry.get("description") or "")[:600],
                            "entry_date": entry.get("date_filed"),
                            "entry_id": entry.get("id"),
                            "docket_id": docket.get("id"),
                            "absolute_url": docket.get("absolute_url"),
                        }},
                    ))

        log.info("courtlistener_adv.done", listings=len(out))
        return out
