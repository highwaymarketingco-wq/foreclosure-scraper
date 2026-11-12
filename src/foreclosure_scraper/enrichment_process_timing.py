"""Foreclosure-process + redemption-clock labels — the NC/SC distinction a
seasoned flipper lives by, derived in pure Python (no I/O, free).

WHY IT MATTERS (expert lens):
  * NC = POWER OF SALE (non-judicial): a trustee forecloses out of court — fast
    (~30-90 days), then a 10-day UPSET-BID window (NCGS 45-21.27). Clean, quick
    title; deal velocity is high.
  * SC = JUDICIAL: a full lawsuit through the Master-in-Equity — slow (often
    6-12+ months), court confirmation required, deficiency possible. Slower
    velocity, more timing risk.
  * TAX sales: NC tax foreclosure conveys at sale; SC tax sale gives only a
    CERTIFICATE with a ~12-MONTH REDEMPTION period (SC Code 12-51-90) — the
    owner can pay and reclaim, so the 'buyer' can't take title/renovate/resell
    until the clock runs. A SC pre-redemption tax row is a MOTIVATED-SELLER lead
    (owner still owns it and is about to lose it), not a biddable acquisition.

Sets Listing.foreclosure_process and, for SC tax sales, Listing.redemption_deadline.
"""
from __future__ import annotations

from datetime import timedelta

from .models import Listing, ListingType

_SC_REDEMPTION_DAYS = 365   # SC Code 12-51-90 (~12 months)

_FORECLOSURE_TYPES = {ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS,
                      ListingType.SHERIFF_SALE, ListingType.AUCTION, ListingType.REO}
_TAX_TYPES = {ListingType.TAX_SALE, ListingType.TAX_LIEN}


def _process_for(li: Listing) -> str | None:
    lt = li.listing_type
    if lt in _TAX_TYPES:
        return "tax"
    if lt is ListingType.HOA_SALE:
        return "judicial" if li.state == "SC" else "power_of_sale"
    if lt in _FORECLOSURE_TYPES:
        if li.state == "NC":
            return "power_of_sale"
        if li.state == "SC":
            return "judicial"
    return None


def enrich_process_timing(listings: list[Listing]) -> dict:
    labeled = 0
    redemptions = 0
    for li in listings:
        proc = _process_for(li)
        if proc:
            li.foreclosure_process = proc
            labeled += 1
        # SC tax SALE -> 12-month redemption clock from the sale date. Only the
        # conveying TAX_SALE event starts the clock; a TAX_LIEN/certificate row
        # is pre-sale and its sale_date semantics differ, so it's excluded.
        if (li.state == "SC" and li.listing_type is ListingType.TAX_SALE and li.sale_date
                and li.redemption_deadline is None):
            li.redemption_deadline = li.sale_date + timedelta(days=_SC_REDEMPTION_DAYS)
            redemptions += 1
    return {"labeled": labeled, "sc_redemption_clocks": redemptions}
