"""Multi-source free phone enrichment — covers SC + NC gaps.

The voter_phone enricher only covers NC (NCSBE voter file, ~69% of NC owners).
SC has no free voter phone file. This module adds free people-search sources:

  1. TruePeopleSearch.com — free, no login, name+address → phone
  2. FastPeopleSearch.com — free, no login, name+city+state → phone  
  3. Sync.me / SpyDialer — free reverse lookups (fallback)

All sources are bot-protected, so we use the stealth browser (StealthyFetcher).
Results are tagged with low confidence and need DNC scrubbing.

Strategy:
  - Only query listings that DON'T already have a phone (idempotent)
  - Prioritize: SC listings first (no voter file), then NC gaps
  - Rate-limited: 2 concurrent, 500 max per run
  - Results tagged source + confidence + needs_dnc_scrub

Output: writes to li.raw["owner_phone"] with source="free_people_search"
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Sequence

import structlog

from .models import Listing

log = structlog.get_logger()

_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_PHONE_RAW_RE = re.compile(r"\b\d{10}\b")

# Rate limiting
_MAX_CONCURRENT = 2
_MAX_PER_RUN = 500


def _normalize_name(owner: str | None) -> tuple[str, str] | None:
    """Extract (first, last) from owner name."""
    if not owner:
        return None
    o = re.sub(r"[^A-Za-z\s]", " ", owner).strip()
    o = re.sub(r"\s+", " ", o)
    if not o:
        return None
    parts = o.split()
    if len(parts) < 2:
        return None
    # Handle "LAST, FIRST" format
    if "," in owner:
        segs = owner.split(",")
        last = segs[0].strip()
        first = segs[1].strip().split()[0] if len(segs) > 1 and segs[1].strip() else ""
        if last and first:
            return (first.upper(), last.upper())
    # Handle "FIRST LAST" or "LAST FIRST MIDDLE"
    # Try both orderings
    return (parts[0].upper(), parts[-1].upper())


def _extract_phones(html: str) -> list[str]:
    """Extract phone numbers from HTML text."""
    phones = set()
    for m in _PHONE_RE.finditer(html):
        p = re.sub(r"\D", "", m.group())
        if len(p) == 10 and not p.startswith("000") and not p.startswith("999"):
            phones.add(p)
    for m in _PHONE_RAW_RE.finditer(html):
        p = m.group()
        if not p.startswith("000") and not p.startswith("999"):
            phones.add(p)
    return list(phones)


async def _fetch_stealth(url: str, timeout: float = 15.0) -> str | None:
    """Fetch URL using stealth browser if available, else httpx."""
    try:
        from .render import fetch_rendered
        return await fetch_rendered(url)
    except ImportError:
        pass
    
    # Fallback: httpx
    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception as exc:
        log.debug("phone_fetch.httpx_error", url=url, error=str(exc)[:80])
    
    return None


async def _search_truepeoplesearch(
    first: str, last: str, city: str | None, state: str
) -> list[str]:
    """Search TruePeopleSearch by name + location."""
    base = "https://www.truepeoplesearch.com/results"
    params = f"?name={first}+{last}"
    if city:
        params += f"&city={city}"
    params += f"&state={state}"
    url = base + params
    
    html = await _fetch_stealth(url)
    if not html:
        return []
    
    phones = _extract_phones(html)
    # Filter out obvious non-phone numbers (area codes in the 800/888 range)
    return [p for p in phones if p[:3] not in ("800", "888", "877", "866", "855", "900")]


async def _search_fastpeoplesearch(
    first: str, last: str, city: str | None, state: str
) -> list[str]:
    """Search FastPeopleSearch by name + location."""
    # URL format: /name/firstname-lastname_city-state
    name_slug = f"{first.lower()}-{last.lower()}"
    city_slug = re.sub(r"\s+", "-", city.lower()) if city else ""
    if city_slug:
        url = f"https://www.fastpeoplesearch.com/name/{name_slug}_{city_slug}-{state.lower()}"
    else:
        url = f"https://www.fastpeoplesearch.com/name/{name_slug}_{state.lower()}"
    
    html = await _fetch_stealth(url)
    if not html:
        return []
    
    phones = _extract_phones(html)
    return [p for p in phones if p[:3] not in ("800", "888", "877", "866", "855", "900")]


async def _lookup_phone(li: Listing) -> list[str]:
    """Try multiple free sources for a single listing."""
    name = _normalize_name(li.owner_name or li.defendant)
    if not name:
        return []
    
    first, last = name
    city = li.city or ""
    state = li.state or ""
    
    if not state or not last:
        return []
    
    phones: list[str] = []
    
    # Try TruePeopleSearch first (better coverage)
    try:
        tps_phones = await _search_truepeoplesearch(first, last, city, state)
        phones.extend(tps_phones)
    except Exception as exc:
        log.debug("phone.tps.error", owner=li.owner_name, error=str(exc)[:60])
    
    # Dedupe
    seen = set()
    unique = []
    for p in phones:
        if p not in seen:
            seen.add(p)
            unique.append(p)
        if len(unique) >= 3:
            break
    
    return unique


async def enrich_free_phones(listings: Sequence[Listing]) -> dict:
    """Enrich phone numbers from free people-search sources.
    
    Only processes listings that don't already have a phone.
    Prioritizes SC listings (no voter file) then NC gaps.
    """
    stats = {
        "total_listings": 0,
        "already_have_phone": 0,
        "targets": 0,
        "queried": 0,
        "found": 0,
        "phones_found": 0,
        "errors": 0,
    }
    
    # Filter to listings needing phones
    targets: list[Listing] = []
    for li in listings:
        stats["total_listings"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        
        # Skip if already has phone from voter or skip_trace
        existing = (raw.get("owner_phone") or {}).get("phone")
        skip_phones = (raw.get("skip_trace") or {}).get("phone_numbers")
        if existing or skip_phones:
            stats["already_have_phone"] += 1
            continue
        
        # Need at least a name and state
        if not (li.owner_name or li.defendant) or not li.state:
            continue
        
        targets.append(li)
    
    stats["targets"] = len(targets)
    
    # Prioritize SC first, then by grade (A/B first)
    def _priority(li: Listing) -> tuple:
        raw = li.raw if isinstance(li.raw, dict) else {}
        grade = raw.get("grade")
        if isinstance(grade, dict):
            grade = grade.get("overall", "Z")
        grade = str(grade or "Z").upper()
        state_pri = 0 if li.state == "SC" else 1  # SC first (no voter file)
        return (state_pri, grade)
    
    targets.sort(key=_priority)
    
    # Cap at max per run
    targets = targets[:_MAX_PER_RUN]
    
    # Process with semaphore for rate limiting
    sem = asyncio.Semaphore(_MAX_CONCURRENT)
    
    async def _process_one(li: Listing):
        async with sem:
            nonlocal queried, found, phones_found, errors
            queried += 1
            try:
                phones = await _lookup_phone(li)
                if phones:
                    found += 1
                    phones_found += len(phones)
                    if not isinstance(li.raw, dict):
                        li.raw = {}
                    li.raw["owner_phone"] = {
                        "phone": f"({phones[0][:3]}) {phones[0][3:6]}-{phones[0][6:]}",
                        "additional_phones": [
                            f"({p[:3]}) {p[3:6]}-{p[6:]}" for p in phones[1:]
                        ] if len(phones) > 1 else [],
                        "source": "free_people_search",
                        "line_type": "unknown",
                        "needs_dnc_scrub": True,
                        "match": "name+location",
                        "confidence": "low",
                        "found_at": datetime.utcnow().isoformat(),
                    }
            except Exception as exc:
                errors += 1
                log.debug("phone.lookup.error", owner=li.owner_name, error=str(exc)[:60])
    
    queried = found = phones_found = errors = 0
    
    # Run in batches
    batch_size = 50
    for i in range(0, len(targets), batch_size):
        batch = targets[i:i + batch_size]
        await asyncio.gather(*[_process_one(li) for li in batch])
        if (i + batch_size) % 100 == 0:
            log.info(
                "phone.progress",
                batch_start=i,
                queried=queried,
                found=found,
                phones=phones_found,
            )
    
    stats["queried"] = queried
    stats["found"] = found
    stats["phones_found"] = phones_found
    stats["errors"] = errors
    
    log.info(
        "free_phones.complete",
        targets=stats["targets"],
        queried=queried,
        found=found,
        phones=phones_found,
    )
    
    return stats
