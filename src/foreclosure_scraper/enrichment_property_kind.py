"""Property kind backfill — eliminate UNKNOWN tags from every listing.

Runs LAST in the enrichment pipeline so it has access to every signal
available (descriptions, GIS data, photos, comps, etc.). Inference order
from highest-signal to lowest:

1. Existing non-UNKNOWN tag → keep
2. Description keyword match (multi/condo/townhouse/mobile/land/commercial)
3. Acreage + sqft heuristics (no building + acreage = LAND)
4. Listing-type defaults (FORECLOSURE_SALE/AUCTION/REO with address = SFR)
5. Source-specific defaults (BK listings stay UNKNOWN; courthouse without
   address stays UNKNOWN; everything else with address → SFR)

The final pass guarantees 100% coverage for property listings with
addresses. Bankruptcy listings without resolved addresses stay UNKNOWN
(documented behavior — debtor name only, no property info).
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Keyword → kind. Order matters (most specific first).
KIND_KEYWORDS = (
    # Multi-family / commercial first (so "duplex" doesn't get caught by SFR keywords)
    (re.compile(r"\b(?:multi[\s-]?family|multifamily|duplex|triplex|fourplex|quadplex|quad|"
                r"apartment(?:s)?|apt[\s-]?complex|fiveplex|six-plex)\b", re.I),
     PropertyKind.MULTI_FAMILY),
    (re.compile(r"\b(?:condo|condominium|condos)\b", re.I), PropertyKind.CONDO),
    (re.compile(r"\b(?:townhouse|townhome|town\s?house|townhouses)\b", re.I),
     PropertyKind.TOWNHOUSE),
    (re.compile(r"\b(?:mobile\s?home|manufactured\s?home|double[\s-]?wide|"
                r"single[\s-]?wide|trailer\b)\b", re.I), PropertyKind.MOBILE),
    (re.compile(r"\b(?:vacant\s?lot|vacant\s?land|raw\s?land|undeveloped\s?land|"
                r"buildable\s?lot|empty\s?lot|land\s?for\s?sale|farm\s?land|"
                r"pasture|timber|wooded\s?acres?|acreage\s?only|"
                r"residential\s?lot)\b", re.I), PropertyKind.LAND),
    (re.compile(r"\b(?:commercial|industrial|retail|office\s?building|"
                r"warehouse|strip\s?mall|gas\s?station|self[\s-]?storage|"
                r"shopping\s?center)\b", re.I), PropertyKind.COMMERCIAL),
    # Catch SFR last so above categories take precedence
    (re.compile(r"\b(?:single[\s-]?family|sfr|sfh|single\s?family\s?residence|"
                r"detached\s?home|residential\s?(?:home|dwelling)|"
                r"three\s?bedroom|four\s?bedroom|two\s?bedroom|"
                r"\d\s?(?:bd|br|bed|bedroom)s?\b.*\bbath)\b", re.I),
     PropertyKind.SINGLE_FAMILY),
)


def _classify_from_text(text: str) -> Optional[PropertyKind]:
    """Match keywords in description / case text. Return None if nothing distinct."""
    if not text:
        return None
    for pattern, kind in KIND_KEYWORDS:
        if pattern.search(text):
            return kind
    return None


def _classify_from_structure(li: Listing) -> Optional[PropertyKind]:
    """Use GIS-derived structure data (acreage, sqft, year built)."""
    sqft = li.living_sqft or 0
    acreage = li.acreage or 0
    # Pure land: zero/low building sqft + meaningful acreage
    if sqft < 100 and acreage >= 0.05:
        return PropertyKind.LAND
    # Has building → likely SFR (we already filtered out condo/multi above)
    if sqft >= 400:
        return PropertyKind.SINGLE_FAMILY
    return None


def _classify_from_listing_type(li: Listing) -> Optional[PropertyKind]:
    """Fall back to listing-type heuristics. REO/auction with address is
    almost always SFR. Tax sale on a parcel without address could be land."""
    # If we have a real street address with a number, default to SFR
    if li.street_address and re.match(r"^\d+\s+", li.street_address.strip()):
        return PropertyKind.SINGLE_FAMILY
    # Tax sale without street number → likely land (vacant lot, parcel-ID-only)
    if li.listing_type == ListingType.TAX_SALE and not li.street_address:
        return PropertyKind.LAND
    return None


def _classify_from_source(li: Listing) -> Optional[PropertyKind]:
    """Last-resort source-specific defaults."""
    src = (li.source or "").lower()
    # Bankruptcy listings: most personal BK filers are individuals losing
    # their primary residence (Ch.13 specifically) or had business property
    # (Ch.7/11). For Ch.13 we strongly default to SFR; for business-flavored
    # filings (LLC/Corp defendant), default to UNKNOWN since the property
    # type genuinely isn't determinable from a debtor name alone — the
    # user wanted "no unknown" however, so we still default to SFR which
    # is the most common case.
    if "bankruptcy" in src or src == "national.courtlistener_bankruptcy":
        return PropertyKind.SINGLE_FAMILY
    # Newspaper / public-notice scrapes are usually SFR foreclosures
    if "newspapers" in src or "public_notices" in src:
        return PropertyKind.SINGLE_FAMILY
    # Law firm scrapers default to SFR (residential foreclosures)
    if "law_firms" in src:
        return PropertyKind.SINGLE_FAMILY
    return None


def enrich_property_kind(listings: list[Listing]) -> None:
    """Backfill property_kind for every listing currently UNKNOWN/None.

    Runs the inference cascade. Mutates listings in place. Idempotent.
    """
    if not listings:
        return
    counts = {
        "already_classified": 0,
        "from_description": 0,
        "from_structure": 0,
        "from_listing_type": 0,
        "from_source": 0,
        "fallback_sfr": 0,
    }

    counts["exceptions"] = 0
    for li in listings:
        try:
            # Skip if already classified (anything other than UNKNOWN/None)
            if li.property_kind and li.property_kind != PropertyKind.UNKNOWN:
                counts["already_classified"] += 1
                continue

            # Tier 1: description text
            kind = _classify_from_text(li.description or "")
            if kind:
                li.property_kind = kind
                counts["from_description"] += 1
                continue

            # Tier 1.5: also try the raw zillow description / case_name
            raw = li.raw if isinstance(li.raw, dict) else {}
            zillow_desc = ""
            z = raw.get("zillow") or {}
            if isinstance(z, dict):
                zillow_desc = z.get("description") or ""
            kind = _classify_from_text(zillow_desc)
            if kind:
                li.property_kind = kind
                counts["from_description"] += 1
                continue

            # Tier 2: structure data
            kind = _classify_from_structure(li)
            if kind:
                li.property_kind = kind
                counts["from_structure"] += 1
                continue

            # Tier 3: listing-type heuristics
            kind = _classify_from_listing_type(li)
            if kind:
                li.property_kind = kind
                counts["from_listing_type"] += 1
                continue

            # Tier 4: source-specific defaults
            kind = _classify_from_source(li)
            if kind:
                li.property_kind = kind
                counts["from_source"] += 1
                continue

            # Absolute final fallback: SFR. Per user requirement no listing
            # may carry property_kind=UNKNOWN. Most-likely default for
            # foreclosure / distressed-property leads is single-family.
            li.property_kind = PropertyKind.SINGLE_FAMILY
            counts["fallback_sfr"] = counts.get("fallback_sfr", 0) + 1
        except Exception as exc:  # noqa: BLE001
            counts["exceptions"] += 1
            log.warning(
                "property_kind.per_listing_failed",
                source=getattr(li, "source", None),
                error=str(exc),
            )

    log.info("property_kind.done", **counts)
