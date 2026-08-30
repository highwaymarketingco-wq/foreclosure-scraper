"""NC Secretary of State business-entity enrichment (403-bypass variant).

The NC SOS business search at https://www.sosnc.gov/online/Search returns HTTP
403 to a plain httpx request because the site fingerprints the TLS handshake
and blocks non-browser clients. This module tries multiple strategies before
giving up, so a subset of entity-owned leads still gets SOS data without needing
the heavier Scrapling stealth path used by enrichment_sos_dissolution /
enrichment_sos_agent:

  Strategy A: GET the search page with browser-like User-Agent + Accept headers
               (the same default UA pool already used by http_client, but here we
               also send a rich Accept header and Referer to look like a real
               navigation).
  Strategy B: POST the search form endpoint with the entity name + form params,
               as a real browser does when submitting the search box.
  Strategy C: Try the (undocumented) JSON API path at https://www.sosnc.gov/api/
               if one exists, returning JSON directly.

Fills raw["nc_sos_entity"] with:
  business_name, status, registered_agent, registered_agent_address,
  principal_address, sos_url, strategy (which endpoint worked)

This is a LIGHTER companion to enrichment_sos_agent (which uses Scrapling
stealth and pulls officers too). Use this when stealth is unavailable or too
slow — it fills the headline entity fields only, not the officer list.

Free, no auth, public record. Handles 403 gracefully: returns None + logs a
warning so the run continues.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

# Browser-like headers sent on every request in this module. The shared
# http_client already rotates a real-browser UA, but the SOS endpoint is
# stricter — it also inspects Accept + Referer — so we override per-request.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.sosnc.gov/online/Search",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_SEARCH_PAGE_URL = "https://www.sosnc.gov/online/Search"
_SEARCH_FORM_URL = "https://www.sosnc.gov/online_services/search/by_title/_Business_Registration"
_API_URL = "https://www.sosnc.gov/api/search/business"
_DETAIL_URL = "https://www.sosnc.gov/online_services/search/by_title/_Business_Registration?server={{id}}"

_SEMAPHORE = asyncio.Semaphore(3)  # be polite, SOS rate limits

# Reuse the business-entity detection already proven by sos_dissolution /
# sos_agent so we only query SOS for names that are actually entities.
_BUSINESS_MARKERS = (
    "llc", "l.l.c.", "inc", "inc.", "corp", "corp.", "corporation",
    "company", "co.", "ltd", "ltd.", "lp", "l.p.", "llp",
)


def _is_business(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(m in n for m in _BUSINESS_MARKERS)


def _entity_of(listing: Listing) -> Optional[str]:
    """The entity name to look up (owner preferred over defendant)."""
    for raw in (listing.owner_name, listing.defendant):
        if raw and _is_business(raw):
            # strip litigation captions + trustee tails, lightly
            s = raw.strip()
            # "Plaintiff v. Defendant LLC" -> keep the defendant side
            parts = s.split(" v. ")
            if len(parts) > 1:
                s = parts[-1].strip()
            s = s.split(";")[0].strip()
            if s:
                return s
    return None


async def _strategy_a_search_page(name: str) -> dict[str, Any] | None:
    """Strategy A: GET the search page with browser-like headers.

    Sometimes the 403 is on the POST/data endpoint only, and the GET landing
    page returns HTML we can parse for a CSRF token or a redirect to the real
    results. We do not expect structured data here — it's a probe to see if
    the host answers browser-like requests at all before trying POST.
    """
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _SEARCH_PAGE_URL,
                headers=_BROWSER_HEADERS,
                params={"searchText": name},
            )
            if resp.status_code == 403:
                log.debug("nc_sos.strategy_a_403")
                return None
            if resp.status_code != 200:
                return None
            # We got *something* — but the GET landing page is HTML, not JSON.
            # Hand off to strategy B for the actual data.
            return None
    except Exception as exc:
        log.debug("nc_sos.strategy_a_fail", error=str(exc)[:80])
        return None


async def _strategy_b_post_form(name: str) -> dict[str, Any] | None:
    """Strategy B: POST to the search form endpoint with browser-like headers.

    The real browser submits the search box as a POST with form-encoded params.
    We mimic that here. The response is usually HTML, so we parse key fields
    from the text with simple substring/regex matching.
    """
    import re

    try:
        async with client(timeout=15.0) as c:
            resp = await c.post(
                _SEARCH_FORM_URL,
                data={
                    "searchText": name,
                    "button": "Search",
                },
                headers={
                    **_BROWSER_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.sosnc.gov",
                },
            )
            if resp.status_code == 403:
                log.debug("nc_sos.strategy_b_403")
                return None
            if resp.status_code != 200:
                return None
            text = resp.text or ""
    except Exception as exc:
        log.debug("nc_sos.strategy_b_fail", error=str(exc)[:80])
        return None

    if not text or len(text) < 200:
        return None

    # The HTML response is unstructured; pull the first result block with
    # simple regexes. NC SOS detail pages carry labeled rows like
    # "Status:", "Registered Agent:", etc.
    result: dict[str, Any] = {"strategy": "post_form"}

    m = re.search(r"Status:\s*</[^>]+>\s*([^<]+)", text, re.I)
    if m:
        result["status"] = m.group(1).strip()

    m = re.search(r"Business Name:\s*</[^>]+>\s*([^<]+)", text, re.I)
    if m:
        result["business_name"] = m.group(1).strip()

    m = re.search(r"Registered Agent:\s*</[^>]+>\s*([^<]+)", text, re.I)
    if m:
        result["registered_agent"] = m.group(1).strip()

    m = re.search(r"Registered Office:\s*</[^>]+>\s*([^<]+)", text, re.I)
    if m:
        result["registered_agent_address"] = m.group(1).strip()

    m = re.search(r"Principal Office:\s*</[^>]+>\s*([^<]+)", text, re.I)
    if m:
        result["principal_address"] = m.group(1).strip()

    # Need at least a business name or status to count as a hit
    if not result.get("business_name") and not result.get("status"):
        return None
    result["sos_url"] = _SEARCH_FORM_URL
    return result


async def _strategy_c_api(name: str) -> dict[str, Any] | None:
    """Strategy C: Try the (undocumented) SOS API endpoint.

    If the SOS exposes a JSON API at /api/search/business, we get structured
    data directly. This is speculative — the endpoint may not exist — but it's
    the cleanest path when it does, and costs only one request.
    """
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _API_URL,
                params={"name": name, "format": "json"},
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("nc_sos.strategy_c_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("nc_sos.strategy_c_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, dict):
        return None

    # The shape of an undocumented API is uncertain; try common keys.
    results = (
        data.get("results")
        or data.get("data")
        or data.get("entities")
        or []
    )
    if not results or not isinstance(results, list):
        return None

    first = results[0] if isinstance(results[0], dict) else {}
    if not first:
        return None

    return {
        "business_name": first.get("businessName") or first.get("name"),
        "status": first.get("status") or first.get("entityStatus"),
        "registered_agent": first.get("registeredAgentName")
        or first.get("agentName"),
        "registered_agent_address": first.get("registeredAgentAddress")
        or first.get("agentAddress"),
        "principal_address": first.get("principalOfficeAddress")
        or first.get("officeAddress"),
        "sos_url": _SEARCH_FORM_URL,
        "strategy": "api",
    }


async def _lookup_nc_sos(name: str) -> dict[str, Any] | None:
    """Try all three strategies in order; return first non-None result."""
    async with _SEMAPHORE:
        for label, fn in (
            ("strategy_a", _strategy_a_search_page),
            ("strategy_b", _strategy_b_post_form),
            ("strategy_c", _strategy_c_api),
        ):
            try:
                result = await fn(name)
            except Exception as exc:
                log.warning("nc_sos.strategy_exception",
                            strategy=label, error=str(exc)[:120])
                result = None
            if result:
                log.info("nc_sos.found", strategy=result.get("strategy", label),
                         name=name[:60])
                return result

    log.warning("nc_sos.all_strategies_failed", name=name[:60])
    return None


async def enrich_nc_sos(listing: Listing) -> Listing:
    """Enrich a listing with NC SOS business-entity data (403-bypass variant)."""
    entity_name = _entity_of(listing)
    if not entity_name:
        return listing

    # NC only — SC SOS is CAPTCHA-gated
    if (listing.state or "").upper() != "NC":
        return listing

    result = await _lookup_nc_sos(entity_name)
    if not result:
        # 403 or all strategies exhausted — log + continue
        return listing

    raw_update: dict[str, Any] = {"nc_sos_entity": result}
    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_nc_sos(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with NC SOS business-entity data.

    Only NC listings whose owner/defendant is a business entity are queried.
    Handles 403 gracefully: skipped listings keep their prior raw, and a
    warning is logged.
    """
    need_sos = [
        l for l in listings
        if (l.state or "").upper() == "NC"
        and _entity_of(l)
        and "nc_sos_entity" not in (l.raw or {})
    ]
    if not need_sos:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_nc_sos(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_sos], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if (listing.state or "").upper() == "NC" and _entity_of(listing) \
                and "nc_sos_entity" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "nc_sos.batch_done",
        total=len(need_sos),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
