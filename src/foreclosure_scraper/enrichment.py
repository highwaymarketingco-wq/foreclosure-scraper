"""Property detail enrichment. Pulls beds/baths/zoning/etc. when missing."""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import structlog

from .budget import cap
from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()

# Apify actor IDs for enrichment-by-address
APIFY_ZILLOW_ACTOR = "maxcopell/zillow-detail-scraper"  # one of several public Zillow actors
APIFY_REALTOR_ACTOR = "epctex/realtor-scraper"


async def _zillow_lookup(address: str, token: str) -> dict[str, Any] | None:
    """Best-effort Zillow lookup via Apify. Returns dict or None."""
    if not token or not address:
        return None
    try:
        async with client(timeout=60.0) as c:
            r = await c.post(
                f"https://api.apify.com/v2/acts/{APIFY_ZILLOW_ACTOR.replace('/', '~')}/run-sync-get-dataset-items",
                params={"token": token, "timeout": 60},
                json={"addresses": [address], "extractionMethod": "PAGINATION"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else None
    except Exception as exc:  # noqa: BLE001
        log.debug("enrichment.zillow.error", address=address, error=str(exc))
        return None


def _parse_zillow(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not payload:
        return out
    out["bedrooms"] = payload.get("bedrooms")
    out["bathrooms"] = payload.get("bathrooms")
    out["living_sqft"] = payload.get("livingArea") or payload.get("livingAreaValue")
    out["year_built"] = payload.get("yearBuilt")
    out["lot_size_sqft"] = payload.get("lotSize")
    desc = payload.get("description") or ""
    if desc:
        out["description"] = desc[:500]
    home_type = (payload.get("homeType") or "").upper()
    mapping = {
        "SINGLE_FAMILY": PropertyKind.SINGLE_FAMILY,
        "CONDO": PropertyKind.CONDO,
        "TOWNHOUSE": PropertyKind.TOWNHOUSE,
        "MULTI_FAMILY": PropertyKind.MULTI_FAMILY,
        "MANUFACTURED": PropertyKind.MOBILE,
        "LOT": PropertyKind.LAND,
        "VACANT_LAND": PropertyKind.LAND,
        "COMMERCIAL": PropertyKind.COMMERCIAL,
    }
    if home_type in mapping:
        out["property_kind"] = mapping[home_type]
    return {k: v for k, v in out.items() if v not in (None, "", 0)}


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


_ACRES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:acre|ac\b)", re.I)


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


async def enrich(listings: list[Listing]) -> list[Listing]:
    """Enrich each listing in place. Bounded concurrency for Apify calls."""
    token = os.environ.get("APIFY_TOKEN", "")
    sem = asyncio.Semaphore(4)  # don't hammer Apify

    # Budget guard: only enrich the most promising N listings to fit free tier
    enrich_budget = cap("zillow_enrichment_per_run", default=60)
    # Score listings by promise (has opening bid + sale date, in scope, not land)
    scored = sorted(
        listings,
        key=lambda li: (
            -(li.opening_bid or 0),
            0 if li.property_kind != PropertyKind.LAND else 1,
            li.sale_date or 0,
        ),
    )
    eligible_ids = set(id(li) for li in scored[:enrich_budget])

    async def one(li: Listing) -> Listing:
        # Cheap inferences first
        if li.property_kind == PropertyKind.UNKNOWN:
            li.property_kind = _infer_property_kind(li)
        if li.acreage is None:
            li.acreage = _infer_acreage(li)

        # Skip the expensive Apify hop unless we're missing the big rocks AND
        # this listing is in our budgeted enrich set
        needs_zillow = (
            token
            and id(li) in eligible_ids
            and li.street_address
            and li.zip_code
            and (li.bedrooms is None or li.living_sqft is None)
            and li.property_kind not in (PropertyKind.LAND, PropertyKind.COMMERCIAL)
        )
        if needs_zillow:
            async with sem:
                payload = await _zillow_lookup(li.display_address(), token)
                if payload:
                    parsed = _parse_zillow(payload)
                    for k, v in parsed.items():
                        if getattr(li, k, None) in (None, ""):
                            setattr(li, k, v)
        return li

    return await asyncio.gather(*(one(li) for li in listings))
