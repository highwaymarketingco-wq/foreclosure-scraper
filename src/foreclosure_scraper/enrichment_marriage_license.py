"""Marriage license signal enricher — NC Register of Deeds cross-reference.

A distressed homeowner who recently filed for a marriage license is a life-event
signal: possible name change, joint ownership, or spousal motivation. This
enricher cross-references owner names against marriage license records from NC
county Register of Deeds offices (public records, free).

This is a best-effort signal enricher, not a full scraper. It tries county ROD
public search endpoints and tags listings with match metadata. If a county site
is down or has no searchable interface, it skips gracefully.

Rate-limited: max MARRIAGE_LICENSE_MAX_REQUESTS (default 50) HTTP requests per run.
Idempotent: skips listings that already have marriage_license data.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

MAX_REQUESTS = int(os.getenv("MARRIAGE_LICENSE_MAX_REQUESTS", "50"))
TIMEOUT = 15.0

# County ROD search endpoints (free public records)
ROD_ENDPOINTS = {
    "wake": "https://rod.wake.gov/Search/Names",
    "mecklenburg": "https://epods.mecklenburgcountync.gov/Search",
    "buncombe": "https://www.buncombecounty.org/deeds/search.aspx",
    "durham": "https://rod.durhamcountync.gov/search",
    "forsyth": "https://www.forsythcountync.gov/deeds/search",
    # Fallback statewide portal
    "_fallback": "https://rod.nc.gov/search",
}


def _parse_name(owner: str) -> tuple[str, str] | None:
    """Extract (last, first) from owner_name string."""
    if not owner:
        return None
    o = re.sub(r"[^A-Za-z, ]", " ", owner).strip()
    o = re.sub(r"\s+", " ", o)
    if not o:
        return None
    if "," in o:
        parts = o.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip().split()[0] if parts[1].strip() else ""
        if last and first:
            return (last.upper(), first.upper())
    parts = o.split()
    if len(parts) >= 2:
        return (parts[-1].upper(), parts[0].upper())
    return None


def _search_rod(
    client: httpx.Client,
    county: str,
    last_name: str,
    first_name: str,
) -> list[dict] | None:
    """Search a county ROD site for marriage licenses by name.

    Returns list of match dicts or None on failure.
    This is a best-effort probe — many ROD sites require JS rendering or have
    undocumented search APIs that change frequently.
    """
    county_key = (county or "").lower().replace(" county", "").strip()
    url = ROD_ENDPOINTS.get(county_key) or ROD_ENDPOINTS.get("_fallback")
    if not url:
        return None

    try:
        # Try a simple GET with name params — most ROD search forms accept query params
        resp = client.get(
            url,
            params={"lastname": last_name, "firstname": first_name, "doctype": "marriage"},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return None

        # Parse HTML for result rows (selectolax or regex)
        text = resp.text
        if not text or len(text) < 100:
            return None

        # Look for table rows or JSON containing marriage license data
        matches = []

        # Try JSON response first (some modern ROD sites return JSON)
        if "application/json" in resp.headers.get("content-type", ""):
            try:
                data = resp.json()
                if isinstance(data, list):
                    for item in data[:5]:
                        matches.append({
                            "spouse_name": item.get("spouse_name") or item.get("party2") or "",
                            "license_date": item.get("date_filed") or item.get("license_date") or "",
                            "county_issued": county,
                            "source_url": str(resp.url),
                        })
                elif isinstance(data, dict) and "results" in data:
                    for item in data["results"][:5]:
                        matches.append({
                            "spouse_name": item.get("spouse_name") or item.get("party2") or "",
                            "license_date": item.get("date_filed") or item.get("license_date") or "",
                            "county_issued": county,
                            "source_url": str(resp.url),
                        })
            except Exception:
                pass
            return matches if matches else None

        # Fall back to HTML parsing — look for date patterns and name patterns
        date_matches = re.findall(r"(\d{1,2}/\d{1,2}/\d{4})", text)
        name_pattern = re.compile(
            r"(?:spouse|party2|applicant)\s*[:\s]*(.{3,40})", re.I
        )
        spouse_matches = name_pattern.findall(text)

        for i, d in enumerate(date_matches[:5]):
            spouse = spouse_matches[i] if i < len(spouse_matches) else ""
            matches.append({
                "spouse_name": spouse.strip(),
                "license_date": d,
                "county_issued": county,
                "source_url": str(resp.url),
            })

        return matches if matches else None

    except httpx.TimeoutException:
        log.debug("marriage.timeout", county=county, url=url)
        return None
    except Exception as exc:
        log.debug("marriage.fetch_error", county=county, error=str(exc)[:100])
        return None


def _match_confidence(owner_last: str, owner_first: str, result: dict) -> str:
    """Rate match confidence: high (exact last+first), medium (last only), low."""
    spouse = (result.get("spouse_name") or "").upper()
    if owner_last in spouse and owner_first in spouse:
        return "high"
    if owner_last in spouse:
        return "medium"
    return "low"


def enrich_marriage_licenses(listings: List[Listing]) -> dict:
    """Cross-reference owner names against NC marriage license records."""
    stats = {
        "total": len(listings),
        "with_owner": 0,
        "queried": 0,
        "matches": 0,
        "skipped_existing": 0,
        "errors": 0,
    }
    requests_made = 0

    with httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; PublicRecordsResearch/1.0)"},
        follow_redirects=True,
    ) as client:
        for li in listings:
            raw = li.raw if isinstance(li.raw, dict) else {}
            if not raw:
                continue

            # Idempotent: skip already enriched
            if raw.get("marriage_license"):
                stats["skipped_existing"] += 1
                continue

            # Need an owner name
            owner = li.owner_name or li.defendant or ""
            if not owner:
                continue
            stats["with_owner"] += 1

            parsed = _parse_name(owner)
            if not parsed:
                continue
            last, first = parsed

            # Rate limit
            if requests_made >= MAX_REQUESTS:
                log.info("marriage.rate_limit_reached", max=MAX_REQUESTS)
                break

            county = (li.county or "").replace(" County", "").strip()
            results = _search_rod(client, county, last, first)
            requests_made += 1
            stats["queried"] += 1

            if not results:
                continue

            # Filter to confident matches and store
            best_match = None
            best_conf = "low"
            for r in results:
                conf = _match_confidence(last, first, r)
                if conf == "high":
                    best_match = r
                    best_conf = "high"
                    break
                elif conf == "medium" and best_conf == "low":
                    best_match = r
                    best_conf = "medium"

            if best_match:
                best_match["match_confidence"] = best_conf
                best_match["searched_name"] = f"{last}, {first}"
                raw["marriage_license"] = best_match
                stats["matches"] += 1

    log.info("marriage.done", **stats)
    return stats
