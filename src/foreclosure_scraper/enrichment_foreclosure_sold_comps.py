"""Per-county pool of recently-finished foreclosure sales for max-bid
estimation.

The retail-MLS comp pool (raw.comps from HomeHarvest) tells you what
the property is WORTH. The foreclosure-sale comp pool tells you what
the courthouse-steps market actually PAID for similar foreclosed
properties in the same county over the same window. Investors use
these as a max-bid floor — typically 60-75% of retail.

Pool source: any listing with sale_date in the past 0-180 days from
a foreclosure source (law-firm trustee, county Master in Equity,
NC eCourts, county tax-foreclosure, auction.com). Captured BEFORE
the active-only filter drops them; pooled per-county; matched per-
listing against active subjects with strict like-for-like rules.

Like-for-like matching policy (the user's mandate: don't compare
trailers to 5-bed houses):

  * Same county (mandatory)
  * Compatible property_kind (mandatory)
      - single_family <-> townhouse (similar improved-residential trade)
      - mobile <-> manufactured <-> trailer (same category)
      - condo isolated (different floor-plate economics)
      - multi_family isolated
      - land isolated (no improvement comps)
      - commercial isolated
  * If both have bedrooms: ±1 (skip when either is land/mobile)
  * If both have living_sqft: within ±40%
  * Sold within the last LOOKBACK_DAYS (default 180)
  * Top N=5 by similarity score (closer beds + sqft = higher score)

Output:
  li.raw.foreclosure_sold_comps = [{address, sold_price, sold_date,
    beds, baths, living_sqft, property_kind, source, source_url,
    case_number, similarity_score}, ...]
  li.raw.foreclosure_sold_comp_summary = {county, property_kind,
    n_comps, lookback_days, median_sold_price, median_price_per_sqft,
    range_low, range_high}

Dashboard treatment:
  * Sold pool is written to docs/foreclosure_sold_pool.json — separate
    from docs/listings.json so the dashboard doesn't show sold rows
    in the main grid.
  * Per-listing card popouts read raw.foreclosure_sold_comps and
    render the comp table with source_url back-links.

Pure-Python, no I/O, idempotent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()


# Sold within this window counts as "recent enough" for a comp.
# Foreclosure markets shift on tax-cycle / interest-rate timescales —
# 6 months is the conservative default; expand if county pools are sparse.
LOOKBACK_DAYS = 180

# Per-listing comp cap. Five is the user-research-validated number for
# investor decision support — more is information overload.
MAX_COMPS_PER_LISTING = 5

# Property-kind compatibility groups. Comps must share a group with
# the subject; cross-group matches are forbidden (the user's example:
# trailer vs 5-bed house).
KIND_GROUPS: dict[str, frozenset[PropertyKind]] = {
    "improved_detached": frozenset({
        PropertyKind.SINGLE_FAMILY,
        PropertyKind.TOWNHOUSE,
    }),
    "mobile": frozenset({PropertyKind.MOBILE}),
    "condo": frozenset({PropertyKind.CONDO}),
    "multi": frozenset({PropertyKind.MULTI_FAMILY}),
    "land": frozenset({PropertyKind.LAND}),
    "commercial": frozenset({PropertyKind.COMMERCIAL}),
    "mixed": frozenset({PropertyKind.MIXED}),
}


def _group_for(kind: PropertyKind | None) -> Optional[str]:
    if kind is None:
        return None
    for group_name, kinds in KIND_GROUPS.items():
        if kind in kinds:
            return group_name
    return None


def _naive_utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


# Sources we trust as "real foreclosure-sale results" when their
# listings have a past sale_date. Excludes general-real-estate (HomeHarvest
# distressed = preforeclosure marketing, NOT actual auction results;
# CourtListener BK = filing not sale; etc.).
FORECLOSURE_SALE_SOURCES = frozenset({
    # Law-firm trustees actually conduct the sale
    "law_firms.brock_scott",
    "law_firms.hutchens",
    "law_firms.bell_carrington",
    "law_firms.finkel",
    "law_firms.korn",
    "law_firms.aldridge_pite",
    "law_firms.mcmichael_taylor_gray",
    "law_firms.rogers_townsend",
    # County Master in Equity (SC)
    "counties_sc.spartanburg_master_in_equity",
    "counties_sc.anderson_master_in_equity",
    "counties_sc.pickens_master_in_equity",
    "counties_sc.sc_courtrosters",
    "counties_sc.sc_flc",
    # County tax-foreclosure (sale at courthouse steps)
    "counties_nc.wake_tax",
    "counties_nc.forsyth_tax",
    "counties_nc.guilford_tax",
    "counties_nc.durham_tax",
    "counties_nc.new_hanover_tax",
    "counties_nc.mecklenburg_tax",
    "counties_nc.buncombe_tax",
    "counties_nc.cleveland_tax",
    "counties_nc.henderson_tax",
    "counties_nc.polk_tax",
    "counties_nc.rutherford_tax",
    "counties_nc.brunswick_tax",
    "counties_nc.nc_rod_substitute_trustee",  # Trustee's-Deed-Upon-Sale = post-sale recordings
    "counties_sc.sc_tax_delinquent",
    # National auction sites — these ARE foreclosure auctions, sold prices
    # are real outcomes
    "national.auction_dot_com",
    "national.bid4assets",
    # NC eCourts when a "Confirmation of Sale" docket entry shows up
    # (current data has none — confirmation-of-sale parsing is future work)
    "counties_nc.nc_ecourts_lis_pendens",
})


def is_sold_pool_candidate(li: Listing,
                           now: datetime | None = None) -> bool:
    """True if this listing should join the sold-comp pool. Two paths:

    1. Strong signal: ``raw.actual_sold_price`` is set — the scraper has
       confirmed an actual hammer price (Pickens / Anderson / Spartanburg
       results PDFs, NC ROD Trustee's Deed Upon Sale recordings). These
       qualify regardless of sale_date timing because the price-set event
       has already happened — the only nuance is whether the legal sale
       has been finalized (post upset-bid window).

    2. Heuristic signal: sale_date is in the past 0-180 days AND the
       source is a real foreclosure-sale source (law-firm trustee, county
       MIE, county tax-foreclosure, auction.com). The opening_bid is
       used as a sold-price proxy.
    """
    if li.source not in FORECLOSURE_SALE_SOURCES:
        return False
    raw = li.raw if isinstance(li.raw, dict) else {}
    if isinstance(raw.get("actual_sold_price"), (int, float)):
        # Confirmed hammer price — accept regardless of sale_date timing.
        return True
    sd = _naive_utc(li.sale_date)
    if sd is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    days_since = (now - sd).days
    return 0 <= days_since <= LOOKBACK_DAYS


def _county_key(li: Listing) -> Optional[tuple[str, str]]:
    if not (li.county and li.state):
        return None
    return (li.county.replace(" County", "").strip().title(),
            li.state.upper())


def _opening_or_judgment(li: Listing) -> Optional[float]:
    """Best-available 'sold price' approximation. Pickens MIE results
    PDFs surface the actual hammer price; most other sources only have
    opening_bid (the floor) or judgment_amount (the lender's debt).

    Future work: MIE results parsers should populate raw.actual_sold_price
    explicitly, which this function will prefer when present."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    actual = raw.get("actual_sold_price")
    if isinstance(actual, (int, float)) and actual > 0:
        return float(actual)
    if li.opening_bid and li.opening_bid > 0:
        return float(li.opening_bid)
    if li.judgment_amount and li.judgment_amount > 0:
        return float(li.judgment_amount)
    return None


def _kind_compatible(subject_kind: PropertyKind | None,
                     comp_kind: PropertyKind | None) -> bool:
    """True iff subject + comp belong to the same KIND_GROUPS bucket."""
    g1 = _group_for(subject_kind)
    g2 = _group_for(comp_kind)
    if g1 is None or g2 is None:
        return False
    return g1 == g2


def _beds_compatible(subject_beds: int | None, comp_beds: int | None,
                     kind_group: str | None) -> bool:
    """Beds match within ±1 when both have a value. Skip the check
    entirely for land / mobile / commercial groups where bed count
    isn't a meaningful comp dimension."""
    if kind_group in ("land", "commercial", "mobile", "mixed"):
        return True
    if subject_beds is None or comp_beds is None:
        return True  # missing-data lenience
    return abs(subject_beds - comp_beds) <= 1


def _sqft_compatible(subject_sqft: float | None,
                     comp_sqft: float | None,
                     pct: float = 0.40) -> bool:
    """Sqft match within ±pct when both have a value. Lenient on missing."""
    if subject_sqft is None or comp_sqft is None:
        return True
    if subject_sqft <= 0 or comp_sqft <= 0:
        return True
    ratio = abs(subject_sqft - comp_sqft) / max(subject_sqft, comp_sqft)
    return ratio <= pct


def _similarity_score(subject: Listing, comp: Listing) -> float:
    """Higher = more comparable. Used to rank candidates after the hard
    filters (county + kind + beds + sqft) have passed.

    Components: bed-delta closeness, sqft-delta closeness, recency.
    All normalized to [0, 1]. Equal-weighted.
    """
    score = 0.0
    n = 0

    # Bed closeness
    if (subject.bedrooms is not None and comp.bedrooms is not None
            and subject.bedrooms > 0 and comp.bedrooms > 0):
        delta = abs(subject.bedrooms - comp.bedrooms)
        score += max(0.0, 1.0 - delta / 3.0)
        n += 1

    # Sqft closeness
    if (subject.living_sqft is not None and comp.living_sqft is not None
            and subject.living_sqft > 0 and comp.living_sqft > 0):
        ratio = abs(subject.living_sqft - comp.living_sqft) / max(
            subject.living_sqft, comp.living_sqft
        )
        score += max(0.0, 1.0 - ratio)
        n += 1

    # Recency — closer to today = better signal
    sd = _naive_utc(comp.sale_date)
    if sd is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        days_since = (now - sd).days
        score += max(0.0, 1.0 - days_since / LOOKBACK_DAYS)
        n += 1

    if n == 0:
        return 0.0
    return score / n


def _comp_dict(comp: Listing, score: float) -> dict:
    """Compact dict for the dashboard card popout. Only the fields the
    investor needs to evaluate the comp + click through to the source.

    Includes condition signal (from Vision if photos were available
    on the sold comp during enrichment) — a $40k sale at "gut" tells
    a different story than a $40k sale at "move_in_ready". Without
    condition, the price alone is ambiguous."""
    raw = comp.raw if isinstance(comp.raw, dict) else {}
    images = raw.get("images") or {}
    vision = raw.get("vision") or {}
    primary_photo = (
        images.get("primary")
        or (images.get("real") or [None])[0]
        or images.get("map")
    )
    return {
        "sold_price": _opening_or_judgment(comp),
        "sold_date": comp.sale_date.isoformat() if comp.sale_date else None,
        "address": comp.street_address or comp.display_address(),
        "city": comp.city,
        "zip_code": comp.zip_code,
        "county": comp.county,
        "state": comp.state,
        "beds": comp.bedrooms,
        "baths": comp.bathrooms,
        "living_sqft": comp.living_sqft,
        "property_kind": (comp.property_kind.value
                         if comp.property_kind else None),
        "source": comp.source,
        "source_url": comp.source_url,
        "case_number": comp.case_number,
        "similarity_score": round(score, 3),
        "actual_sold_price_known": isinstance(raw.get("actual_sold_price"),
                                              (int, float)),
        # Condition + visual evidence — Vision only fires when photos
        # were sourced (HomeHarvest by address) AND ANTHROPIC_API_KEY
        # was set during enrichment.
        "condition_tier": raw.get("condition_tier"),
        "condition_source": raw.get("condition_source"),
        "vision_confidence": vision.get("confidence"),
        "vision_summary": (vision.get("summary") or "")[:300] or None,
        "primary_photo_url": primary_photo,
        "photo_count": len(images.get("real") or []),
    }


def _summary(comps: list[dict], county: str,
             kind_group: str) -> dict:
    """County-level rollup for the popout header."""
    prices = [c["sold_price"] for c in comps
              if isinstance(c["sold_price"], (int, float))]
    ppsfs = [
        c["sold_price"] / c["living_sqft"]
        for c in comps
        if (isinstance(c["sold_price"], (int, float))
            and isinstance(c["living_sqft"], (int, float))
            and c["living_sqft"] > 0)
    ]
    return {
        "county": county,
        "property_kind_group": kind_group,
        "n_comps": len(comps),
        "lookback_days": LOOKBACK_DAYS,
        "median_sold_price": round(median(prices), 2) if prices else None,
        "median_price_per_sqft": round(median(ppsfs), 2) if ppsfs else None,
        "range_low": round(min(prices), 2) if prices else None,
        "range_high": round(max(prices), 2) if prices else None,
    }


def enrich_foreclosure_sold_comps(
    active_listings: list[Listing],
    sold_pool: list[Listing],
) -> dict:
    """For each active listing, attach the top-N like-for-like sold
    foreclosure comps from the same county. Mutates active_listings.
    Returns stats."""
    if not sold_pool or not active_listings:
        log.info("foreclosure_sold_comps.empty",
                 active=len(active_listings), pool=len(sold_pool))
        return {"active": len(active_listings), "pool": len(sold_pool),
                "matched": 0, "no_county_match": 0,
                "no_kind_match": 0, "no_match_at_all": 0}

    # Index pool by (county, state)
    pool_by_county: dict[tuple[str, str], list[Listing]] = {}
    for sold in sold_pool:
        key = _county_key(sold)
        if key is None:
            continue
        pool_by_county.setdefault(key, []).append(sold)

    stats = {
        "active": len(active_listings),
        "pool": len(sold_pool),
        "matched": 0,
        "no_county_match": 0,
        "no_kind_match": 0,
        "no_match_at_all": 0,
    }

    for li in active_listings:
        ck = _county_key(li)
        if ck is None:
            continue
        county_pool = pool_by_county.get(ck, [])
        if not county_pool:
            stats["no_county_match"] += 1
            continue

        subj_group = _group_for(li.property_kind)
        if subj_group is None:
            stats["no_kind_match"] += 1
            continue

        candidates = []
        for comp in county_pool:
            if comp.source_url == li.source_url:
                continue  # don't comp against self
            if not _kind_compatible(li.property_kind, comp.property_kind):
                continue
            if not _beds_compatible(li.bedrooms, comp.bedrooms, subj_group):
                continue
            if not _sqft_compatible(li.living_sqft, comp.living_sqft):
                continue
            score = _similarity_score(li, comp)
            candidates.append((score, comp))

        if not candidates:
            stats["no_match_at_all"] += 1
            continue

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:MAX_COMPS_PER_LISTING]
        comps_payload = [_comp_dict(c, s) for s, c in top]

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["foreclosure_sold_comps"] = comps_payload
        li.raw["foreclosure_sold_comp_summary"] = _summary(
            comps_payload, ck[0], subj_group,
        )
        stats["matched"] += 1

    log.info("foreclosure_sold_comps.done", **stats)
    return stats
