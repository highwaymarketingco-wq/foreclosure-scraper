"""Kershaw County SC - Forfeited Land Commission (FLC) properties.

DISABLED 2026-10-02 (per-source audit follow-up item 4), NOT JUST DORMANT.
``PAGE_URL`` (``kershaw.sc.gov/treasurer/forfeited-land-commission``) 404s
live -- the county reorganized its site onto a new URL scheme at some point
after this scraper was written (every department now sits under
``/government/departments-a-g/...`` or ``/government/departments-r-z/...``,
confirmed via the live sitemap, ``sitemap-page-1.xml``, 235 pages). There is
no redirect; the old Treasurer path is a hard dead end, exactly as the task
that found this reported.

REAL SEARCH DONE, NOT A GUESS -- every free avenue checked live 2026-10-02:
  * The county's OWN Treasurer department now lives at
    ``/government/departments-r-z/treasurer``, with a dedicated
    ``/treasurer/delinquent-matters`` sub-page. That page explicitly lists
    "Maintaining property list for the Forfeit Land Commission" as one of
    the office's duties -- so Kershaw DOES maintain an FLC list -- but
    publishes no link to it, no PDF, no table. The page's only document link
    is a "Tax Sale Guide" (``/home/showpublisheddocument/18071``, actually a
    .docx despite the URL) -- fetched and read: it is the GENERAL RULES for
    the annual delinquent tax sale (Nov 2 2026 this cycle, S.C. Code
    §12-51-xx bidder/redemption procedure), not a parcel inventory, and
    carries no property list at all.
  * Auditor department page (``/government/departments-a-g/auditor``): no
    FLC/forfeited-land content.
  * Boards and Commissions (``/government/boards-and-commissions``): no FLC
    board sub-page (page itself is near-empty).
  * Purchasing Bids & RFPs (``/government/departments-h-q/purchasing/
    bids-rfps``): no FLC-related solicitation among the active bids (a prior
    web search hit suggested FLC parcels sometimes move through a
    council/procurement packet at other SC counties -- not currently the
    case for Kershaw; nothing to parse today).
  * Kershaw County GIS Open Data Portal
    (``kershawcountydataportal-kershawcounty.hub.arcgis.com``, confirmed via
    its DCAT catalog, ``/api/feed/dcat-us/1.1.json``): the one parcel layer
    (``services6.arcgis.com/kyYrMHheB5jkAnFA/.../Parcels_view/FeatureServer/0``)
    carries ONLY ``PRSNTP_ID`` (parcel id) and ``taxTotalAc`` (acreage) --
    no owner field at all, so FLC-held parcels can't be identified by an
    owner-name query the way Oconee's ArcGIS layer allows (see
    ``counties_sc/oconee_flc.py``'s own disabled-reason for that working
    pattern, which does not transfer here).
  * Kershaw's CAMA/tax-record system (qPublic, Schneider Geospatial,
    ``qpublic.schneidercorp.com/Application.aspx?App=KershawCountySC``) DOES
    support an owner-name search that could in principle surface
    FLC-held parcels -- but the site gates every search behind a
    click-through "Terms and Conditions" modal (confirmed live). Per this
    project's compliance line (CLAUDE.md: "a CAPTCHA, a login, a Cloudflare
    or other WAF challenge, and click-through terms still are walls"), this
    is a real wall, not a technical gap, and was not clicked through.
  * General web search for a third-party mirror or PDF of a current Kershaw
    FLC roster: nothing found.

The closest already-covered sibling signal is
``counties_sc.qpaybill_delinquent_roll`` (``QPAYBILL_SUBS["Kershaw"] =
"kershawcounty"``), which reads Kershaw's PRE-sale delinquent tax roll
(parcels still owing, not yet forfeited) -- a different, earlier-stage lane
than FLC (parcels the county already owns after an unsold tax sale), but the
nearest real distress signal this engine already captures for Kershaw.

Converted to the standard disabled=True/disabled_reason (see
counties_sc/oconee_flc.py, counties_sc/clarendon_tax_auction.py for the same
pattern) instead of leaving a silently-404ing fetch() in place, so this
reads as DORMANT in run reports, not an ambiguous zero or a hidden error.
Kershaw is outside the 18-county core footprint (SC_COUNTIES /
NC_COUNTIES in config.py), so this stays a bounded, re-checkable dead end
rather than a source worth building a heavier (e.g. qPublic-ToS-exempt)
workaround for.

Free, public, no login -- when (if) the county republishes a real FLC list.
Slug: counties_sc.kershaw_flc
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

# Dead (404, confirmed live 2026-10-02): the county's site reorganized and
# never redirected this path. Kept only as provenance for what this scraper
# used to read -- do NOT re-enable fetch() against it without re-verifying
# live first (DEAD means dead the day it was probed, not forever).
PAGE_URL = "https://www.kershaw.sc.gov/treasurer/forfeited-land-commission"


class KershawFLC(BaseScraper):
    slug = "counties_sc.kershaw_flc"
    name = "Kershaw County SC Forfeited Land Commission"
    disabled = True
    disabled_reason = ("PAGE_URL 404s (county site reorganized, no redirect) - re-searched live "
                       "2026-10-02 for a replacement (Treasurer/delinquent-matters page, Auditor, "
                       "Boards and Commissions, Bids and RFPs, the county's ArcGIS open-data parcel "
                       "layer with no owner field, general web search) and found no current free FLC "
                       "inventory anywhere - the one lead (qPublic owner-name search) is gated behind "
                       "a click-through Terms of Service, a compliance wall per CLAUDE.md, not a "
                       "technical gap - nearest covered signal is counties_sc.qpaybill_delinquent_roll "
                       "(Kershaw pre-sale delinquent roll, a different lane) - confirmed 2026-10-02")
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
