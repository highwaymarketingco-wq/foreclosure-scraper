"""NC Register of Deeds — Substitute Trustee Deed indexer scraper.

Recorded "Substitute Trustee" appointments and "Notice of Sale" filings
at the county ROD precede the SP foreclosure docket by 2-6 weeks. They
are the EARLIEST publicly-available indicator that a foreclosure is
imminent — high-value lead source.

Per-county portals (verified May 2026):

  Mecklenburg  https://meckrod.manatron.com/                  (Manatron/Aumentum)
  Wake         https://services.wakegov.com/booksweb/          (Aumentum)
  Durham       https://rod-public.dconc.gov/                   (Aumentum)
  Buncombe     https://buncombe-recordings.permitium.com/      (Permitium)

Each has its own quirks (document-type filter values, search form
WebForms hidden fields, F5/Shape challenge variants). All require
Scrapling stealth to render — plain httpx returns the disclaimer page.

This scraper is wired into the registry but classified
``requires_render=True`` so the run summary shows RENDER-REQUIRED
rather than REGRESSED while the per-portal Scrapling stealth flows
are pending. The skeleton is in place so a future commit can drop
in the actual fetch+parse without touching the public surface.

Document types we want (varies by county vendor):
  * "Substitute Trustee Deed" / "STD"
  * "Notice of Sale" / "NOS"
  * "Notice of Hearing Prior to Foreclosure"
  * "Claim of Lien" (HOA / COA — escalates to foreclosure)
  * "Trustee's Deed Upon Sale" (post-sale, useful for upset bid window)
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()


# Per-county configuration. Document-type values are the actual filter
# strings each portal accepts — verified from the indexer dropdown
# options as of May 2026. 2026-05-07 scope rollback: dropped Mecklenburg
# / Wake / Durham portals; only Buncombe (in user's WNC core scope)
# remains. Portal configs for the dropped counties are preserved here
# in code comments below for future re-activation if scope changes.
#
# DEACTIVATED PORTALS (kept as comments for fast re-activation):
#   Mecklenburg: https://meckrod.manatron.com/RealEstate/SearchEntry.aspx (manatron)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN, TRUSTEES DEED
#   Wake: https://services.wakegov.com/booksweb/PublicFreeMonitorSearch.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
#   Durham: https://rod-public.dconc.gov/Search.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
COUNTY_PORTALS: dict[str, dict] = {
    "Buncombe": {
        "url": "https://buncombe-recordings.permitium.com/",
        "search_path": "/searches/new",
        "doc_types": [
            "SUBSTITUTE TRUSTEE DEED",
            "NOTICE OF SALE",
        ],
        "vendor": "permitium",
    },
}


class NCRodSubstituteTrustee(BaseScraper):
    """NC Register of Deeds — substitute-trustee + notice-of-sale recordings."""

    slug = "counties_nc.nc_rod_substitute_trustee"
    name = "NC ROD Substitute Trustee + Notice of Sale (4 counties)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_apify = False
    # Each portal is ASP.NET behind anti-bot; needs Scrapling stealth.
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        # Skeleton emit: portal config is registered, but the per-vendor
        # stealth flow isn't wired yet. Returning [] keeps the run summary
        # accurate (RENDER-REQUIRED) until a commit can drive the search
        # form for each vendor (Manatron / Aumentum / Permitium each have
        # different WebForms postback patterns).
        log.info(
            "nc_rod.skeleton",
            counties=list(COUNTY_PORTALS),
            note=("Wired into registry — render flow per vendor pending. "
                  "Drop in Scrapling stealth page_action for each county "
                  "to start producing listings."),
        )
        return []
