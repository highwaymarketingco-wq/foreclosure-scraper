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

RE-CHECKED LIVE 2026-10-13 (session-wide audit of "confirmed dead" claims,
prompted by this same session finding other counties' dead-source notes were
wrong): fetched PAGE_URL again, plus the homepage, the Treasurer/
delinquent-matters page, and even ``/robots.txt`` -- EVERY ONE of them now
returns HTTP 403 "Access Denied" from an Akamai edge (``server: AkamaiGHost``,
the classic Akamai Bot Manager block page, internal rewrite target literally
``$(SERVE_403)``), identically via both a scripted WebFetch and a plain curl
with a real desktop Chrome User-Agent. ``robots.txt`` 403ing too is the tell:
that path is conventionally never gated, so this is a DOMAIN-WIDE bot/WAF
wall today, not the page-specific 404 the 2026-10-02 note above describes.
Per this project's compliance stance (a WAF challenge is a wall, not a
technical gap to bypass), the page's actual content could not be
re-confirmed either way today -- so the specific "404, reorganized, no
redirect" mechanism above should NOT be treated as re-verified; only the
net conclusion (no accessible free FLC list via kershaw.sc.gov right now)
still holds, now for a different and more clearly compliance-gated reason.
Did not attempt any bypass. No alternate URL search was possible for the
same reason (every kershaw.sc.gov path tried is walled); the nearest
covered signal is still counties_sc.qpaybill_delinquent_roll (Kershaw).

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

# Dead/unreachable (confirmed live 2026-10-02 as a 404; re-checked live
# 2026-10-13 and found the entire domain, including /robots.txt, now 403s
# from an Akamai WAF/bot-management edge -- a domain-wide wall, not a
# page-specific 404; see the module docstring's 2026-10-13 note). Kept only
# as provenance for what this scraper used to read -- do NOT re-enable
# fetch() against it without re-verifying live first (DEAD means dead the
# day it was probed, not forever).
PAGE_URL = "https://www.kershaw.sc.gov/treasurer/forfeited-land-commission"


class KershawFLC(BaseScraper):
    slug = "counties_sc.kershaw_flc"
    name = "Kershaw County SC Forfeited Land Commission"
    disabled = True
    disabled_reason = ("Entire kershaw.sc.gov domain (PAGE_URL, homepage, Treasurer/"
                       "delinquent-matters, even /robots.txt) 403s from an Akamai WAF/bot-management "
                       "edge today, not the page-specific 404 originally reported - re-searched live "
                       "2026-10-02 for a replacement (Treasurer/delinquent-matters page, Auditor, "
                       "Boards and Commissions, Bids and RFPs, the county's ArcGIS open-data parcel "
                       "layer with no owner field, general web search) and found no current free FLC "
                       "inventory anywhere - the one lead (qPublic owner-name search) is gated behind "
                       "a click-through Terms of Service, a compliance wall per CLAUDE.md, not a "
                       "technical gap - nearest covered signal is counties_sc.qpaybill_delinquent_roll "
                       "(Kershaw pre-sale delinquent roll, a different lane) - mechanism re-checked "
                       "and corrected 2026-10-13 (see module docstring), net conclusion unchanged")
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
