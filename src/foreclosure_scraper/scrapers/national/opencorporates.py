"""OpenCorporates API — PAID, OUT OF SCOPE for this free-only engine.

WALLED-CONFIRMED-DEAD / OUT OF SCOPE (2026-10-01 per-source audit).

This module's own docstring used to claim a usable anonymous free tier
("No key required for basic searches"). That is no longer true -- confirmed
live: an unauthenticated request to the exact endpoint below now returns
HTTP 401 with body {"error": {"message": "Invalid Api Token. Please check
your OpenCorporates account"}}. OpenCorporates requires a paid API token
for every request now, with no free/anonymous fallback.

This also means the module was already in direct conflict with this repo's
own hard rule before this audit: CLAUDE.md / HERMES.md section 2 rule 1
names OpenCorporates explicitly as a PAID broker service that is "out of
scope for the engine" ("No paid APIs ... no paid broker data (PropStream,
ATTOM, OpenCorporates, NCOALink, Trepp, UniCourt, Trellis)"). Acquiring or
paying for an OC_API_TOKEN would violate that rule directly, so this is not
a gap to fill -- there is no free path here, by the project's own design,
and now also confirmed by the live API itself.

This is an ENRICHMENT scraper, not a lead source (fetch() has always been
a no-op). search_entity() is left as-is -- it already fails safely (no
token set -> request goes out unauthenticated -> 401 -> returns None,
never raises, never fabricates a result) rather than being "fixed" into
something that would require paying for API access this engine is not
allowed to buy.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_API = "https://api.opencorporates.com/v0.4/companies/search"

# Jurisdictions for our footprint.
_JURISDICTIONS = ("us_nc", "us_sc")


class OpenCorporatesScraper(BaseScraper):
    """OpenCorporates free API entity search.

    Enrichment-only: called by the SOS enrichment pipeline. Standalone fetch
    returns [].
    """
    slug = "national.opencorporates"
    name = "OpenCorporates API (free entity enrichment)"
    category = "enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return []

    @staticmethod
    async def search_entity(entity_name: str) -> dict | None:
        """Search OpenCorporates for a company by name.

        Returns dict with entity info or None if not found.
        Requires free API token for reliable results (set OC_API_TOKEN in .env).
        Without a token, rate-limited to ~30 req/day from a single IP.
        """
        if not entity_name or len(entity_name.strip()) < 3:
            return None

        token = os.environ.get("OC_API_TOKEN", "")
        params: dict[str, str] = {"q": entity_name.strip()}
        if token:
            params["api_token"] = token

        async with client(timeout=30.0) as c:
            try:
                r = await c.get(_API, params=params, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                })
            except Exception as exc:
                log.warning("opencorp.search_fail", name=entity_name, error=str(exc)[:160])
                return None

        if r.status_code != 200:
            log.warning("opencorp.status", name=entity_name, status=r.status_code)
            return None

        try:
            data = r.json()
        except Exception:
            log.warning("opencorp.json_fail", name=entity_name)
            return None

        results = data.get("results", {})
        companies = results.get("companies", [])
        if not companies:
            return None

        # Find the best match (first company that matches our name closely).
        target_lower = entity_name.lower().strip()
        best = None
        for comp_wrapper in companies:
            comp = comp_wrapper.get("company", {})
            name = (comp.get("name") or "").lower()
            if not name:
                continue
            # Exact or contains match.
            if target_lower in name or name in target_lower:
                best = comp
                break
            if not best:
                best = comp  # fallback to first result

        if not best:
            return None

        # Filter to our jurisdictions if possible.
        jurisdiction = best.get("jurisdiction_code", "")
        if jurisdiction and jurisdiction not in _JURISDICTIONS:
            # Still return it but flag as out-of-footprint.
            log.debug("opencorp.out_of_footprint", name=entity_name, jurisdiction=jurisdiction)

        status = best.get("current_status") or ""
        company_type = best.get("company_type") or ""
        reg_agent = best.get("registered_agent_address") or ""
        if isinstance(reg_agent, dict):
            reg_agent = reg_agent.get("address") or ""

        return {
            "name": best.get("name") or entity_name,
            "status": status or "Unknown",
            "entity_type": company_type,
            "jurisdiction": jurisdiction,
            "incorporation_date": best.get("incorporation_date"),
            "registered_agent": reg_agent if isinstance(reg_agent, str) else None,
            "company_number": best.get("company_number"),
            "url": best.get("opencorporates_url") or "",
            "dissolved": "dissolut" in status.lower() or "revok" in status.lower(),
        }
