"""Per-lead confirmation / corroboration flag — is the distress CONFIRMED by a
court / authoritative filing, or only flagged by a single MLS/aggregator source?

Every lead carries its full source set = the primary li.source PLUS every
{source,url} recorded in raw['also_seen_in'] (populated by Listing.merge). A
property seen at brock_scott + realtor.com + the county ROD carries all three.

We classify each distinct source slug into a TIER by substring/prefix rules so
new sources fall into place without a per-slug table:

  COURT       — an actual foreclosure filing / trustee sale / statutory legal
                notice (public index, eCourts, master-in-equity, law-firm
                trustee rosters, ROD, CourtListener, legal notices, ...). If ANY
                source is COURT-tier, the distress is court-CONFIRMED.
  GOVERNMENT  — authoritative gov record, but NOT a foreclosure court filing
                (delinquent-tax, tax-sale, forfeited-land, probate/estate,
                obituary, vacant registry, jail/booking, tax-relief exemption,
                GIS/assessor, qPayBill, ...).
  AGGREGATOR  — an MLS/portal/REO feed that merely FLAGS distress, not a filing
                (homeharvest, zillow, realtor, trulia, redfin, hubzu,
                auction.com, foreclosure.com, xome, propwire, national REO feeds).
  other       — anything unmatched.

Writes raw['corroboration'] = {court_confirmed, tier, source_count, sources,
multi_source, label}. Pure-Python, offline, always on. Follows the structure of
enrichment_eviction_market.py (sync, cheap, stamps raw, returns stats).
"""
from __future__ import annotations

from typing import Iterable

from .models import Listing

# Substring/prefix rules per tier. Matched against the lowercased slug so a new
# source (e.g. "counties_nc.some_new_public_index") lands in the right tier
# without a code change. Order below is documentation only — tier strength is
# resolved by _TIER_RANK, not match order.
_COURT_PATTERNS = (
    "public_index", "ecourts", "law_firms.", "master_in_equity", "_mie", "mie",
    "courtlistener", "legal_notices", "column", "substitute_trustee", "trustee",
    "nc_rod", "rod_", "aumentum", "cott", "logan",
)
_GOVERNMENT_PATTERNS = (
    "delinquent_tax", "tax_sale", "forfeited_land", "dor_lien", "dew_lien",
    "probate", "estate", "heir", "obituar", "vacant", "jail", "booking",
    "incarcer", "tax_relief", "str_permit", "gis", "assessor", "qpaybill",
)
_AGGREGATOR_PATTERNS = (
    "homeharvest", "zillow", "realtor", "trulia", "redfin", "distressed",
    "hubzu", "auction_dot_com", "foreclosure_dot_com", "xome", "propwire",
    # national REO feeds — flag distress, not a filing
    "fannie", "freddie", "hud", "gsa", "usda", "vrm", "treasury", "bid4assets",
    "govdeals",
)

# Strongest tier wins: court > government > aggregator > other.
_TIER_RANK = {"court": 3, "government": 2, "aggregator": 1, "other": 0}


def _classify_slug(slug: str) -> str:
    """Classify a single source slug into a tier by substring match.

    COURT is checked first so a slug that matches both a court pattern and a
    weaker one (e.g. a tax-foreclosure court roster) is treated as a filing.
    """
    s = (slug or "").lower()
    if not s:
        return "other"
    if any(p in s for p in _COURT_PATTERNS):
        return "court"
    if any(p in s for p in _GOVERNMENT_PATTERNS):
        return "government"
    if any(p in s for p in _AGGREGATOR_PATTERNS):
        return "aggregator"
    return "other"


def _collect_sources(li: Listing) -> list[str]:
    """Distinct source slugs for a lead: primary li.source + every also_seen_in
    source, dropping falsy / duplicate values (order-preserving)."""
    slugs: list[str] = []
    seen: set[str] = set()

    def _add(s):
        if s and s not in seen:
            seen.add(s)
            slugs.append(s)

    _add(li.source)
    for d in (li.raw or {}).get("also_seen_in", []) or []:
        if isinstance(d, dict):
            _add(d.get("source"))
    return slugs


def enrich_corroboration(listings: Iterable[Listing]) -> dict:
    """Stamp raw['corroboration'] on every lead. Returns distribution stats."""
    stats = {
        "tagged": 0,
        "court_confirmed": 0,
        "government": 0,
        "aggregator_only": 0,
        "multi_source": 0,
    }
    for li in listings:
        slugs = _collect_sources(li)
        if not slugs:
            continue
        tiers = {_classify_slug(s) for s in slugs}
        tier = max(tiers, key=lambda t: _TIER_RANK.get(t, 0))
        court_confirmed = "court" in tiers
        source_count = len(slugs)
        multi_source = source_count >= 2
        sorted_slugs = sorted(slugs)

        label = _label(tier, court_confirmed, source_count, multi_source, li.source)

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["corroboration"] = {
            "court_confirmed": court_confirmed,
            "tier": tier,
            "source_count": source_count,
            "sources": sorted_slugs,
            "multi_source": multi_source,
            "label": label,
        }

        stats["tagged"] += 1
        if court_confirmed:
            stats["court_confirmed"] += 1
        elif tier == "government":
            stats["government"] += 1
        elif tier == "aggregator":
            stats["aggregator_only"] += 1
        if multi_source:
            stats["multi_source"] += 1
    return stats


def _label(tier: str, court_confirmed: bool, source_count: int,
           multi_source: bool, primary: str | None) -> str:
    """Short human string for the dashboard badge."""
    if court_confirmed:
        n = source_count
        return f"Court-confirmed · {n} source" + ("s" if n != 1 else "")
    if tier == "government":
        return f"Gov record · {source_count} source" + ("s" if source_count != 1 else "")
    if tier == "aggregator":
        if not multi_source:
            return f"Single-source · {primary or '?'} (unconfirmed)"
        return f"Aggregator · {source_count} sources (unconfirmed)"
    # other / unmatched
    if not multi_source:
        return f"Single-source · {primary or '?'} (unconfirmed)"
    return f"Unconfirmed · {source_count} sources"
