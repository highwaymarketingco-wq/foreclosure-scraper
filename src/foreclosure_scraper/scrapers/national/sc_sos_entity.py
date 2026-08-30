"""SC Secretary of State business entity search — businessfilings.sc.gov.

Looks up LLC/Corp entities by name for the enrichment pipeline. Used to detect
dissolved/admin/revoked entities (distress signal for LLC-owned properties).

This is an ENRICHMENT scraper, not a lead source. It is called by the
enrichment_sos_sc module when a listing has an LLC/Inc defendant or owner.
The scraper does a name search and returns entity status.

Free, public, no login required. Server-rendered HTML with a form POST.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SEARCH_URL = "https://businessfilings.sc.gov/BusinessFiling/Web/Reporting/SearchByName"

# Entity status values that signal distress.
_DISTRESS_STATUSES = {"dissolved", "revoked", "administratively dissolved", "forfeited"}


def _normalize_entity_name(name: str) -> str:
    """Strip LLC/Inc/Corp suffixes for broader search matching."""
    s = name.strip()
    for suffix in (", LLC", ", L.L.C.", ", INC.", ", INC", ", CORP.", ", CORP",
                   ", CORPORATION", " LLC", " L.L.C.", " INC.", " INC",
                   " CORP.", " CORP", " CORPORATION", ", LLP", " LLP"):
        if s.upper().endswith(suffix.upper()):
            s = s[: -len(suffix)].strip()
    return s


class SCSOSBusinessSearch(BaseScraper):
    """Search SC SOS for business entity status by name.

    This scraper is designed to be called directly by the enrichment pipeline
    (enrichment_sos_sc) rather than producing standalone leads. When called
    as a standalone scraper, it does nothing (returns []).
    """
    slug = "national.sc_sos_entity"
    name = "SC Secretary of State Business Entity Search"
    category = "enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        # Standalone: no-op. This module is called by enrichment_sos_sc.
        return []

    @staticmethod
    async def search_entity(entity_name: str) -> dict | None:
        """Search for a single entity by name. Returns dict with status info
        or None if not found.

        Returns: {
            "name": str,
            "status": str,         # "Good Standing", "Dissolved", etc.
            "entity_type": str,    # "Limited Liability Company", "Corporation", etc.
            "original_filing_date": str,
            "registered_agent": str | None,
            "url": str,
        }
        """
        if not entity_name:
            return None
        clean_name = _normalize_entity_name(entity_name)
        if len(clean_name) < 3:
            return None

        async with client(timeout=30.0) as c:
            try:
                r = await c.post(
                    _SEARCH_URL,
                    data={
                        "SearchCriteria": clean_name,
                        "SearchType": "Contains",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml",
                        "Referer": _SEARCH_URL,
                    },
                )
            except Exception as exc:
                log.warning("sc_sos.search_fail", name=entity_name, error=str(exc)[:160])
                return None

        if r.status_code != 200 or len(r.text) < 500:
            log.warning("sc_sos.bad_response", name=entity_name,
                        status=r.status_code, size=len(r.text))
            return None

        tree = HTMLParser(r.text)
        # Results are in a table. Find the first row matching our entity.
        rows = tree.css("table tr, .results-row, .search-result")
        if not rows:
            # Try generic table row search.
            rows = tree.css("tr")

        for row in rows:
            text = row.text(separator=" ")
            if not text or len(text) < 10:
                continue
            # Check if this row contains our entity name (case-insensitive).
            if clean_name.lower() not in text.lower():
                continue
            # Try to extract entity detail link.
            link_el = row.css_first("a[href]")
            detail_url = ""
            if link_el:
                href = link_el.attributes.get("href", "")
                if href:
                    if href.startswith("/"):
                        detail_url = f"https://businessfilings.sc.gov{href}"
                    else:
                        detail_url = href

            # Parse status from the row text.
            status = None
            for s in ("Good Standing", "Dissolved", "Revoked",
                      "Administratively Dissolved", "Forfeited", "Active"):
                if s.lower() in text.lower():
                    status = s
                    break

            # Fetch detail page for richer info if we have a link.
            registered_agent = None
            entity_type = None
            filing_date = None
            if detail_url:
                try:
                    async with client(timeout=20.0) as c2:
                        r2 = await c2.get(detail_url)
                    if r2.status_code == 200 and len(r2.text) > 500:
                        dtree = HTMLParser(r2.text)
                        dbody = dtree.body.text(separator="\n") if dtree.body else r2.text
                        # Extract fields by label.
                        for label, field_name in [
                            ("Entity Type", "entity_type"),
                            ("Original Filing Date", "filing_date"),
                            ("Registered Agent", "registered_agent"),
                        ]:
                            m = re.search(
                                rf"{label}[:\s]*([^\n]+)",
                                dbody, re.I,
                            )
                            if m:
                                val = m.group(1).strip()
                                if field_name == "entity_type":
                                    entity_type = val
                                elif field_name == "filing_date":
                                    filing_date = val
                                elif field_name == "registered_agent":
                                    registered_agent = val
                except Exception as exc:
                    log.debug("sc_sos.detail_fail", url=detail_url, error=str(exc)[:120])

            return {
                "name": entity_name,
                "status": status or "Unknown",
                "entity_type": entity_type,
                "original_filing_date": filing_date,
                "registered_agent": registered_agent,
                "url": detail_url or _SEARCH_URL,
                "distress": bool(status and status.lower() in _DISTRESS_STATUSES),
            }

        return None
