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

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 17), same bug
class as the 2026-10-01 law_firms.korn fix and this same batch's
national.nc_sos_ucc fix: this class never set `disabled = True`, and
`scrapers/_registry.py`'s `discover()` auto-registers EVERY BaseScraper
subclass in the national package with no category filter -- confirmed by
reading it, "enrichment" is not special-cased anywhere. That means
`OpenCorporatesScraper` has been running through the normal safe_run() path
on every orchestration cycle since this source was documented as
confirmed-dead on 2026-10-01, and `fetch()`'s hardcoded `return []`
recorded OUTCOME_ZERO every single time -- indistinguishable from a real
source having a quiet week, on a source that is actually a permanent,
by-design dead-end. Also found: `search_entity()`'s own docstring claims
it is "called by the SOS enrichment pipeline" -- a repo-wide grep (src/,
tests/, scripts/) found ZERO callers of `OpenCorporatesScraper` or
`search_entity` anywhere outside this file and its own test file. That
integration claim is stale; nothing in this codebase currently calls it.
Re-verified live 2026-10-04: still a hard 401 "Invalid Api Token" on the
real endpoint, unchanged.
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

    Enrichment-only: NOT currently called by anything in this codebase
    (see module docstring's 2026-10-04 FOUND note -- the "called by the SOS
    enrichment pipeline" claim below is stale). Standalone fetch returns [].
    """
    slug = "national.opencorporates"
    name = "OpenCorporates API (free entity enrichment)"
    category = "enrichment"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0
    # FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17):
    # see module docstring's FOUND note -- this auto-registers into the
    # normal scrape loop (scrapers/_registry.py discover() has no category
    # filter) and fetch()'s hardcoded `return []` was recording the
    # ambiguous OUTCOME_ZERO every run instead of the accurate
    # OUTCOME_DORMANT this confirmed-permanent, by-design (paid-API,
    # out-of-scope) dead-end deserves.
    disabled = True
    disabled_reason = (
        "OpenCorporates requires a paid API token for every request now "
        "(confirmed live: unauthenticated requests get HTTP 401 'Invalid "
        "Api Token'), and is explicitly named as an out-of-scope paid "
        "broker service by this project's own rules (CLAUDE.md / "
        "HERMES.md section 2 rule 1) -- not a gap to fill, by design."
    )

    async def fetch(self) -> Iterable[Listing]:
        # Confirmed permanently out of scope -- see module docstring.
        # `disabled = True` above means safe_run never even calls this, but
        # fetch() stays a safe no-op for any direct caller (tests,
        # __main__ probes, etc.)
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
