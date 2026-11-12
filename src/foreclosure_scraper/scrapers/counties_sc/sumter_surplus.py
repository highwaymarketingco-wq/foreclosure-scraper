"""Sumter County SC — Surplus Property Sales.

DISABLED 2026-10-04 (extraction-completeness audit, batch 13). Live-fetched
the current page: it no longer carries ANY inline listing table. Every one of
its 5 "Our Current Auctions" nav rows is now a bare link out to
GovDeals.com's legacy `index.cfm?fa=Main.AdvSearchResults&myseller=<id>` path
-- Sumter County Surplus Property (seller 348), Surplus Vehicles/Heavy
Equipment (seller 400), Forfeited Land Commission Real Property (seller
3939), Sheriff's Office Seized/Unclaimed Property (seller 400), and the
Detention Center's volunteer-made items (seller 3361). The page's own HTML
has NO parcel/owner/address/amount anywhere -- the 2026-09-15 digit-presence
guard already correctly filters this nav text out (confirmed live today it
still returns 0, not a false positive), but there is no amount of re-parsing
that page that can ever recover real data, because none is left on it.

The real data (when any exists) now lives entirely on GovDeals, which
`scrapers/national/govdeals.py` (national.govdeals) ALREADY sweeps
state-wide for SC, server-side scoped to the real-estate taxonomy branches
(categoryIds 84 + 95A), with NO seller restriction -- confirmed live
2026-10-04 that an unrestricted SC sweep across both categories returns a
real (if currently sparse, 1 unrelated listing) result set, so whenever
Sumter's FLC/surplus real property IS posted to GovDeals in those
categories, national.govdeals already picks it up with no Sumter-specific
code needed. Right now Sumter has nothing posted in either category
(a genuine current-inventory zero, not a code gap). Disabling this module
rather than leaving it as permanent dead weight (a network request every run
that can structurally never yield a row again).

Pre-migration docstring, for history: Sumter County used to post surplus
property sales directly at
sumtercountysc.gov/online_services/property/surplus_sales.php as an inline
HTML table. Free, public, no login. Slug: counties_sc.sumter_surplus.
Category: county_tax. ListingType: TAX_SALE.

RE-VERIFIED LIVE 2026-10-13 (cross-session disabled-reason audit -- prior
session had found other "confirmed dead" scrapers in this repo to actually
be live, so every disabled_reason got a fresh real fetch instead of being
trusted from the comment). Re-fetched the county page directly: still zero
inline listing data, still exactly the same 5 nav rows link out to the same
GovDeals seller IDs (348, 400 x2, 3939, 3361) via the legacy
`index.cfm?fa=Main.AdvSearchResults&myseller=<id>` path. Those legacy URLs
now 301-redirect to `govdeals.com/search?accountId=<id>` (GovDeals rebuilt
its frontend as an Angular SPA at some point after this module's original
authoring -- the raw HTML shell carries no listing data either way, it is
all client-side rendered from a backend API).

Went one level deeper than the 2026-10-04 pass: queried the real
maestro.lqdt1.com search API directly (the same API national.govdeals
calls) scoped to each of the 4 Sumter accountIds with no category
restriction. Confirmed live, right now:
  - accountId 348 (Sumter Co. Surplus Property): 1 active listing, but it
    is a 1995 International 4900 FIRE TRUCK (categoryDescription "Fire
    Trucks") -- a vehicle, not real property. national.govdeals correctly
    excludes this (scoped server-side to categoryIds 84/95A only), so this
    is a correct exclusion, not a missed row.
  - accountId 400 (Vehicles/Heavy Equip. + Sheriff's seized property): 0
    active listings.
  - accountId 3939 (Forfeited Land Commission real property -- the one
    seller ID that WOULD matter to this project): 0 active listings.
  - accountId 3361 (Detention Center items): 0 active listings.
Also re-ran national.govdeals' own real SC sweep (categoryIds 84 + 95A,
stateDesc South Carolina, no seller restriction): 1 row in category 84
(an unrelated Anderson, SC property), 0 in 95A. No Sumter rows in either.

Conclusion: disabled_reason below is CONFIRMED STILL ACCURATE as of
2026-10-13. The county page is a real, permanent link-out migration (not a
code bug), and national.govdeals already has unrestricted SC-wide coverage
of the one seller ID (3939/FLC) that could ever carry real property for
this project -- it is just that Sumter genuinely has nothing posted right
now. No code change made.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.sumtercountysc.gov/online_services/property/surplus_sales.php"


class SumterSurplusSales(BaseScraper):
    slug = "counties_sc.sumter_surplus"
    name = "Sumter County SC Surplus Property Sales"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    disabled = True
    disabled_reason = ("page migrated to pure GovDeals link-outs (sellers 348/400/3939/3361), "
                       "no inline listing data left to parse; national.govdeals already "
                       "sweeps SC real-estate categories 84/95A state-wide with no seller "
                       "restriction, confirmed live 2026-10-04, re-confirmed live 2026-10-13 "
                       "(direct maestro API query of all 4 Sumter accountIds: 0 real-estate "
                       "rows, only 1 unrelated fire-truck listing under seller 348)")

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("sumter_surplus.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "parcel", "#")):
                continue
            # FOUND 2026-09-15 (background triage agent): this loop had NO
            # digit-presence requirement at all (unlike the near-identical
            # loops in marlboro_delinquent_tax.py / clarendon_tax_auction.py,
            # which both gate on `any(re.search(r"\d", c) for c in clean)`).
            # Confirmed live: it was grabbing the page's SIDEBAR NAVIGATION
            # table (2-column, no digits anywhere -- links like "Sheriff's
            # Office" / "Seized/Unclaimed Property" / "Detention Center
            # Volunteer Inmate Items") and emitting each row as a fake
            # surplus-property listing with every real field null.
            if not any(re.search(r"\d", c) for c in clean):
                continue

            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
                if m:
                    parcel = m.group(1)
                    break

            owner = clean[0] if clean else None
            addr = None
            for c in clean[1:]:
                if re.search(r"\d+\s+\w+", c):
                    addr = c
                    break

            amount = None
            for c in clean:
                m = re.search(r"\$[\d,]+", c)
                if m:
                    try:
                        amount = float(m.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass

            out.append(Listing(
                source="counties_sc.sumter_surplus",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Sumter",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                opening_bid=amount,
                description=" | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sumter_surplus": {"cells": clean[:10]}},
            ))

        # <li>-fallback REMOVED 2026-09-15. Even after adding the same
        # digit-presence guard as the table loop above, live re-verification
        # still produced garbage from it -- one row was literal page
        # JAVASCRIPT (a calendar-widget snippet, "var defaultCalendarColor
        # = ..."), matched because it happened to contain the digit "8" and
        # the substring "sale"/"bid" somewhere in the surrounding script.
        # A keyword-plus-digit match on arbitrary page text is not a safe
        # enough signal to build a listing from -- the fixed table loop
        # above (which requires an actual <table> row shape, not just
        # keyword-and-digit-bearing text anywhere on the page) is kept;
        # this looser fallback is not.

        log.info("sumter_surplus.done", count=len(out))
        return out
