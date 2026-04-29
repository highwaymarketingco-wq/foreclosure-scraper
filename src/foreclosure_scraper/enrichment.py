"""Multi-source per-listing enrichment.

For every listing with an address, we try to fill missing property details by
cross-referencing the address on:

  1. Zillow (via realsimpli/zillow-property-details-scraper) — beds, baths, sqft,
     year built, lot size, property kind, zestimate, tax value, description, photos.
  2. Realtor.com (when scraped from there originally — already comes with details).
  3. County tax assessor GIS (per-county, top counties only) — zoning, parcel ID.

Designed for ONE batched call per stage (Apify accepts an array of addresses),
not one call per listing — this is critical for cost.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import structlog

from .apify_helper import run_actor_sync
from .budget import cap
from .models import Listing, PropertyKind

log = structlog.get_logger()

ZILLOW_ACTOR = "realsimpli/zillow-property-details-scraper"


# ----- Inference helpers (run before/after Apify) ---------------------------------

NEGATIVE_KEYWORDS = (
    "fire damage", "burned", "smoke damage", "water damage", "flood",
    "mold", "foundation", "structural", "tear down", "vacant", "abandoned",
    "boarded", "hoarder", "as-is", "as is", "needs work", "fixer", "tlc",
    "investor special", "rehab", "gutted", "no power", "no water",
    "termite", "uninhabitable", "condemned",
)
POSITIVE_KEYWORDS = (
    "renovated", "remodeled", "updated", "move-in ready", "turnkey",
    "new roof", "new hvac", "new kitchen", "granite", "hardwood",
    "well maintained", "pristine",
)
_ACRES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:acre|ac\b)", re.I)


def _flags_from_text(text: str) -> list[str]:
    if not text:
        return []
    low = text.lower()
    flags: list[str] = []
    for kw in NEGATIVE_KEYWORDS:
        if kw in low:
            flags.append(kw)
    for kw in POSITIVE_KEYWORDS:
        if kw in low:
            flags.append(kw)
    return flags


def _infer_property_kind(li: Listing) -> PropertyKind:
    desc = " ".join(
        x.lower()
        for x in (li.description or "", li.legal_description or "", li.street_address or "")
        if x
    )
    if any(k in desc for k in ("vacant land", "raw land", "acres ", "tract ", "lot ")) and not any(
        k in desc for k in ("dwelling", "house", "residence")
    ):
        return PropertyKind.LAND
    if any(k in desc for k in ("commercial", "warehouse", "retail", "office bldg", "industrial")):
        return PropertyKind.COMMERCIAL
    if "condominium" in desc or " condo " in desc:
        return PropertyKind.CONDO
    if "townhouse" in desc or "townhome" in desc:
        return PropertyKind.TOWNHOUSE
    if "mobile home" in desc or "manufactured home" in desc:
        return PropertyKind.MOBILE
    if any(k in desc for k in ("single family", "dwelling", "residence", "single-family")):
        return PropertyKind.SINGLE_FAMILY
    return li.property_kind


def _infer_acreage(li: Listing) -> float | None:
    for src in (li.legal_description, li.description):
        if not src:
            continue
        m = _ACRES_RE.search(src)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return li.acreage


# ----- Zillow batch enrichment ----------------------------------------------------


def _zillow_kind(home_type: str | None) -> PropertyKind:
    if not home_type:
        return PropertyKind.UNKNOWN
    s = home_type.upper()
    return {
        "SINGLE_FAMILY": PropertyKind.SINGLE_FAMILY,
        "CONDO": PropertyKind.CONDO,
        "TOWNHOUSE": PropertyKind.TOWNHOUSE,
        "MULTI_FAMILY": PropertyKind.MULTI_FAMILY,
        "MANUFACTURED": PropertyKind.MOBILE,
        "LOT": PropertyKind.LAND,
        "VACANT_LAND": PropertyKind.LAND,
        "COMMERCIAL": PropertyKind.COMMERCIAL,
    }.get(s, PropertyKind.UNKNOWN)


def _apply_zillow_payload(li: Listing, payload: dict[str, Any]) -> None:
    """Pull fields from a Zillow payload into a listing, never overwriting good data."""

    def pick(*keys: str) -> Any:
        for k in keys:
            v = payload.get(k)
            if v not in (None, "", 0):
                return v
        return None

    def maybe(field: str, val: Any) -> None:
        if val in (None, "", 0):
            return
        cur = getattr(li, field, None)
        if cur in (None, "", 0):
            setattr(li, field, val)

    # Basics
    maybe("bedrooms", pick("bedrooms"))
    maybe("bathrooms", pick("bathrooms"))
    maybe("living_sqft", pick("livingArea", "livingAreaValue"))
    maybe("year_built", pick("yearBuilt"))
    maybe("lot_size_sqft", pick("lotSize", "lotAreaValue"))
    maybe("zoning", pick("zoning", "zoningDescription"))
    maybe("market_value", pick("zestimate", "homeValue"))
    maybe("tax_value", pick("taxAssessedValue"))
    maybe("description", (pick("description") or "")[:500] or None)
    maybe("latitude", pick("latitude"))
    maybe("longitude", pick("longitude"))

    # Property kind
    if li.property_kind == PropertyKind.UNKNOWN:
        kind = _zillow_kind(payload.get("homeType") or payload.get("propertyType"))
        if kind != PropertyKind.UNKNOWN:
            li.property_kind = kind

    # Tag the raw payload for downstream use (assessment, audit)
    li.raw.setdefault("zillow", {}).update(
        {k: payload.get(k) for k in (
            "zpid", "homeType", "homeStatus", "yearBuilt", "bedrooms", "bathrooms",
            "livingArea", "lotSize", "zestimate", "rentZestimate", "taxAssessedValue",
            "description", "zoning",
        ) if k in payload}
    )

    # Flags from description text
    text_blob = " ".join(filter(None, (
        payload.get("description"), li.description, li.legal_description,
    )))
    flags = _flags_from_text(text_blob)
    if flags:
        li.raw.setdefault("flags", [])
        for f in flags:
            if f not in li.raw["flags"]:
                li.raw["flags"].append(f)


async def _zillow_batch(addresses: list[str], token: str) -> dict[str, dict]:
    """Look up many addresses in one Apify run. Returns {addr_lower: payload}."""
    if not addresses or not token:
        return {}
    items = await run_actor_sync(
        ZILLOW_ACTOR,
        {"address": addresses},
        token=token,
        timeout_s=420,
    )
    out: dict[str, dict] = {}
    for it in items:
        # Each result has a queriedAddress / address / fullAddress field
        addr = (
            it.get("queriedAddress")
            or it.get("address")
            or it.get("fullAddress")
            or ""
        )
        if isinstance(addr, dict):
            parts = [addr.get("streetAddress", ""), addr.get("city", ""), addr.get("state", ""), addr.get("zipcode", "")]
            addr = ", ".join(p for p in parts if p)
        if addr:
            out[addr.strip().lower()] = it
    log.info("zillow.batch.complete", asked=len(addresses), got=len(out))
    return out


# ----- Public API -----------------------------------------------------------------


async def enrich(listings: list[Listing]) -> list[Listing]:
    """Enrich every listing in place, batching Apify calls."""
    token = os.environ.get("APIFY_TOKEN", "")
    budget = cap("zillow_enrichment_per_run", default=400)

    # 1. Cheap inference first
    for li in listings:
        if li.property_kind == PropertyKind.UNKNOWN:
            li.property_kind = _infer_property_kind(li)
        if li.acreage is None:
            li.acreage = _infer_acreage(li)
        flags = _flags_from_text(" ".join(filter(None, (li.description, li.legal_description))))
        if flags:
            li.raw["flags"] = flags

    # 2. Build address list, prioritizing listings with the most opening_bid signal
    candidates = [
        li for li in listings
        if li.street_address
        and li.zip_code or (li.city and li.state)
        and li.property_kind not in (PropertyKind.LAND,)  # land has no Zillow detail anyway
    ]
    # Sort: highest bid first, then soonest sale date. Use datetime.min for missing
    # dates so the sort is stable across date/None mix.
    from datetime import datetime as _dt
    candidates.sort(key=lambda li: (-(li.opening_bid or 0), li.sale_date or _dt.max))
    candidates = candidates[:budget]

    if not candidates or not token:
        log.info("enrichment.skip", reason="no_candidates_or_token", count=len(candidates), token=bool(token))
        return listings

    # Build clean address strings
    addr_to_listing: dict[str, Listing] = {}
    addresses: list[str] = []
    for li in candidates:
        bits = [
            li.street_address,
            li.city or "",
            f"{li.state or ''} {li.zip_code or ''}".strip(),
        ]
        addr = ", ".join(b for b in bits if b)
        if not addr or len(addr) < 8:
            continue
        addr_to_listing[addr.lower()] = li
        addresses.append(addr)

    log.info("enrichment.zillow.batch", addresses=len(addresses))

    # 3. One batched Apify call. Fail-soft so a bad batch doesn't kill the run.
    try:
        results = await asyncio.wait_for(
            _zillow_batch(addresses, token),
            timeout=540,
        )
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        log.warning("enrichment.zillow.failed", error=str(exc))
        results = {}

    # 4. Apply payloads
    matched = 0
    for addr_lower, payload in results.items():
        li = addr_to_listing.get(addr_lower)
        if not li:
            # Try fuzzy match on street portion
            street = addr_lower.split(",")[0].strip()
            for k, candidate in addr_to_listing.items():
                if k.split(",")[0].strip() == street:
                    li = candidate
                    break
        if not li:
            continue
        _apply_zillow_payload(li, payload)
        matched += 1
    log.info("enrichment.zillow.applied", matched=matched, total=len(addresses))

    return listings
