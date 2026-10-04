"""SC Secretary of State business entity search — businessfilings.sc.gov.

Looks up LLC/Corp entities by name for the enrichment pipeline. Used to detect
dissolved/admin/revoked entities (distress signal for LLC-owned properties).

This is an ENRICHMENT scraper, not a lead source. The scraper does a name
search and returns entity status. CORRECTED 2026-10-04 (batch 18): this
docstring used to claim it is "called by the enrichment_sos_sc module" --
no such module exists anywhere in this codebase (only
enrichment_sos_agent.py and enrichment_sos_dissolution.py do, and neither
calls this), and a repo-wide grep for search_entity() finds zero callers
outside this file's own test. Stale claim, same pattern batch 17 found on
opencorporates.py's identical docstring claim.

WALLED-CONFIRMED-DEAD (2026-10-01 per-source audit), matches the operator's
own prior note ("SC SoS captcha-walled"):

  1. _SEARCH_URL below (the old /BusinessFiling/Web/Reporting/SearchByName
     POST endpoint) is itself dead -- confirmed live HTTP 404. The real
     current site flow is businessfilings.sc.gov -> "Search Existing
     Entities" -> /BusinessFiling/Entity/ExistingFiling (302) ->
     /BusinessFiling/Entity/Search, a server-rendered form with
     input#SearchTextBox (name="EntityName") and
     button#EntitySearchButton.
  2. That form IS gated by a real Google reCAPTCHA on submission --
     confirmed live: the results page returned after filling the name and
     clicking Search contains a populated div.g-recaptcha with a real
     data-sitekey (6Leb4xEUAAAAABb-cJNQHgSXe100c1ch58rsqKJh), not an
     invisible/managed Cloudflare-style challenge a stealth browser can run
     through on its own. Per this codebase's compliance line a CAPTCHA is a
     wall: do not solve it, do not route around it.

Fixing the stale URL alone would not restore function -- it would only
trade a 404 for a reCAPTCHA wall at the next step. search_entity() below is
left as-is (it already fails safely, returning None rather than crashing
or fabricating a result) rather than "fixed" into something that still
cannot complete a real search. NC's equivalent (enrichment_sos_agent.py)
remains the free path for entity/agent lookups; this one does not have one.

Free, public, no login required for the search ITSELF -- but gated by a
CAPTCHA. Server-rendered HTML with a form POST.

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 18), same bug
class as the 2026-10-01 law_firms.korn fix and the 2026-10-04 (batch 17)
national.nc_sos_ucc / national.opencorporates fixes: this class never set
`disabled = True`, and `scrapers/_registry.py`'s `discover()` auto-registers
every BaseScraper subclass in the national package with no category filter
(confirmed by reading it -- "enrichment" is not special-cased anywhere).
That means `SCSOSBusinessSearch` has been running through the normal
safe_run() path on every orchestration cycle since the CAPTCHA wall was
documented 2026-10-01, and `fetch()`'s hardcoded `return []` recorded
OUTCOME_ZERO every single time -- indistinguishable from a real source
having a quiet week, on a helper that is actually a permanent dead-end for
its one real function. Also found: this docstring's own claim that
search_entity() "is called by the enrichment_sos_sc module" is stale/false
-- no `enrichment_sos_sc` module exists anywhere in this codebase (only
`enrichment_sos_agent.py` and `enrichment_sos_dissolution.py` do, and
neither calls this), and a repo-wide grep for `search_entity` found ZERO
callers outside this file and its own test file -- the exact same
stale-docstring pattern batch 17 found on opencorporates.py. Re-verified
live 2026-10-04 via a real browser session (not just curl): the real
current `/BusinessFiling/Entity/Search` page carries the SAME reCAPTCHA
sitekey (`6Leb4xEUAAAAABb-cJNQHgSXe100c1ch58rsqKJh`) the 2026-10-01 note
found, hidden on load but confirmed to render VISIBLY after submitting a
real search (`document.getElementById('SearchTextBox').value='Smith'` +
clicking `EntitySearchButton`) -- genuine, unchanged wall.
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

    Enrichment-only: NOT currently called by anything in this codebase (see
    module docstring's 2026-10-04 FOUND note -- the "called by
    enrichment_sos_sc" claim was stale). Standalone fetch returns [].
    search_entity()'s one real function is reCAPTCHA-walled (re-verified
    live 2026-10-04).
    """
    slug = "national.sc_sos_entity"
    name = "SC Secretary of State Business Entity Search"
    category = "enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0
    # FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 18):
    # see module docstring's FOUND note -- this auto-registers into the
    # normal scrape loop (scrapers/_registry.py discover() has no category
    # filter) and fetch()'s hardcoded `return []` was recording the
    # ambiguous OUTCOME_ZERO every run instead of the accurate
    # OUTCOME_DORMANT this confirmed-permanent CAPTCHA wall (re-verified
    # live 2026-10-04) and currently-uncalled helper deserves.
    disabled = True
    disabled_reason = (
        "search_entity()'s one real function is reCAPTCHA-gated (confirmed "
        "live 2026-10-04: a real Google reCAPTCHA renders on the results "
        "page after any search submission, same sitekey the 2026-10-01 "
        "audit found) -- a compliance wall this codebase does not solve or "
        "route around. Also uncalled: no enrichment_sos_sc module exists in "
        "this codebase and a repo-wide grep finds zero callers of "
        "search_entity() outside this file's own test."
    )

    async def fetch(self) -> Iterable[Listing]:
        # Confirmed permanently CAPTCHA-walled -- see module docstring.
        # `disabled = True` above means safe_run never even calls this, but
        # fetch() stays a safe no-op for any direct caller (tests,
        # __main__ probes, etc.)
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
