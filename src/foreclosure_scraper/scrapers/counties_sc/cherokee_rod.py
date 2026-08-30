"""Cherokee County SC Register of Deeds — sclandrecords.net.

Cherokee County SC uses the statewide SC ROD portal at sclandrecords.net
(hosted by Cott Systems). We search for mortgage satisfactions, deed transfers,
and lien filings by owner name for properties in Cherokee County.

This is an ENRICHMENT scraper called by enrichment_cchs_rod or a dedicated
enrichment module. When run standalone, it returns [].

Free, public, no login. Server-rendered HTML with ASP.NET form POST.
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

_BASE = "https://www.sclandrecords.com"
_CHEROKEE_SEARCH = f"{_BASE}/cherokee/"

# Mortgage/lien document types.
_LIEN_DOCTYPES = {
    "SATISFACTION", "RELEASE", "LIEN", "MORTGAGE", "DEED OF TRUST",
    "MECHANICS LIEN", "JUDGMENT", " lis pendens",
}


class CherokeeSCROD(BaseScraper):
    """Cherokee County SC ROD name search via sclandrecords.net.

    Enrichment-only: called by the ROD enrichment pipeline. Standalone fetch
    returns [].
    """
    slug = "counties_sc.cherokee_rod"
    name = "Cherokee County SC Register of Deeds (sclandrecords.net)"
    category = "rod_enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return []

    @staticmethod
    async def search_owner(owner_name: str) -> dict | None:
        """Search Cherokee County SC ROD for filings by owner name.

        Returns dict with lien/mortgage info or None if not found.
        """
        if not owner_name or len(owner_name.strip()) < 3:
            return None

        # Split "Last, First" -> search terms.
        parts = owner_name.split(",", 1)
        last = parts[0].strip() if parts else owner_name.strip()
        first = parts[1].strip() if len(parts) > 1 else ""

        async with client(timeout=30.0) as c:
            try:
                # GET the search page first to capture any form tokens.
                r = await c.get(_CHEROKEE_SEARCH, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                })
            except Exception as exc:
                log.warning("cherokee_rod.search_fail", name=owner_name, error=str(exc)[:160])
                return None

            if r.status_code != 200 or len(r.text) < 500:
                log.warning("cherokee_rod.bad_response", status=r.status_code, size=len(r.text))
                return None

            # Parse any hidden form fields (ASP.NET __VIEWSTATE, __EVENTVALIDATION).
            tree = HTMLParser(r.text)
            viewstate = ""
            event_val = ""
            for inp in tree.css("input[type='hidden']"):
                name = inp.attributes.get("name", "")
                val = inp.attributes.get("value", "")
                if name == "__VIEWSTATE":
                    viewstate = val
                elif name == "__EVENTVALIDATION":
                    event_val = val

            # POST the search.
            try:
                r2 = await c.post(_CHEROKEE_SEARCH, data={
                    "__VIEWSTATE": viewstate,
                    "__EVENTVALIDATION": event_val,
                    "txtLastName": last,
                    "txtFirstName": first,
                    "btnSearch": "Search",
                }, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Referer": _CHEROKEE_SEARCH,
                })
            except Exception as exc:
                log.warning("cherokee_rod.post_fail", name=owner_name, error=str(exc)[:160])
                return None

        if r2.status_code != 200 or len(r2.text) < 500:
            return None

        rtree = HTMLParser(r2.text)
        rbody = rtree.body.text(separator="\n") if rtree.body else r2.text

        # Parse result rows from the table.
        has_mortgage = False
        has_lien = False
        has_satisfaction = False
        filings: list[dict] = []

        rows = rtree.css("table tr, .result-row, .data-row")
        if not rows:
            rows = rtree.css("tr")

        for row in rows:
            text = row.text(separator=" ").strip()
            if not text or len(text) < 10:
                continue
            text_upper = text.upper()
            doc_type = None
            for dt in _LIEN_DOCTYPES:
                if dt in text_upper:
                    doc_type = dt.strip()
                    break
            if doc_type:
                if "MORTGAGE" in text_upper or "DEED OF TRUST" in text_upper:
                    has_mortgage = True
                if "LIEN" in text_upper:
                    has_lien = True
                if "SATISFACTION" in text_upper or "RELEASE" in text_upper:
                    has_satisfaction = True
                filings.append({
                    "doc_type": doc_type,
                    "excerpt": text[:300],
                })

        return {
            "owner_name": owner_name,
            "has_mortgage": has_mortgage,
            "has_lien": has_lien,
            "has_satisfaction": has_satisfaction,
            "filing_count": len(filings),
            "filings": filings[:20],
            "url": _CHEROKEE_SEARCH,
        }
