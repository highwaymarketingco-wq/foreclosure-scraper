"""Reverse-geocode parcel centroid for listings that have a confident
parcel match but no situs address.

Some county GIS layers (Cleveland NC, Cherokee SC, Mitchell NC, …) carry
parcel polygons + owner names but no situs/property-address field. The
parcel centroid is still useful: a Nominatim reverse lookup gives the
nearest road + house number, which is *approximate* but actionable for
human review.

Policy: the result is always written to ``li.raw["parcel_resolution"]
.reverse_geo_approx`` (annotated as approximate). It is ALSO promoted into
``li.street_address`` (with ``raw.address_is_approximate=True``) so the lead
reaches photos/comps/map/outreach — but ONLY when the listing has no real
street_address AND the owner-name->parcel match clears a surname gate. The
owner-name match has false positives where only a first name overlaps (e.g.
defendant 'Jordan Alexander Avalos' matched owner 'MCCLELLAN JORDAN RAY'),
so promotion requires a shared 4+char surname-grade token. Investors will
use this data — we never promote a synthesized address on a shaky match.

Rate-limited to Nominatim's TOS (1 request/second). Bounded to listings
with usable data (parcel_id + lat/lng + missing or placeholder street).
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# Synthetic-address markers — listings with these as street_address still
# count as "address-less" for the purpose of this enrichment.
_SYNTHETIC_PREFIXES = (
    "Lis Pendens ",
    "Vacant parcel",
    "Bk Property",
    "Tax Sale",
    "Tax Lien",
    "Bankruptcy ",
    "Property in ",
)


def _is_address_less(li: Listing) -> bool:
    sa = (li.street_address or "").strip()
    if not sa:
        return True
    return any(sa.startswith(p) for p in _SYNTHETIC_PREFIXES)


def _matched_owner(li: Listing) -> str:
    """The county-GIS owner name the parcel match landed on. Stored either in
    raw.gis.owner (parcel_lookup / name_search) or raw.lis_pendens_resolution
    .matched_owner. Returns "" when unknown."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    gis = raw.get("gis") or {}
    owner = gis.get("owner") or (raw.get("lis_pendens_resolution") or {}).get("matched_owner")
    return str(owner or "")


def _name_tokens(name: str) -> set[str]:
    """4+char alpha tokens, upper-cased. Strips HTML (<br>) and punctuation so
    'OWENS RANDALL & EVANS<br>KIMBERLY' -> {OWENS, RANDALL, EVANS, KIMBERLY}.
    The 4-char floor drops initials and short connective noise (LE, AKA, &)."""
    cleaned = re.sub(r"<[^>]+>", " ", name or "")
    cleaned = re.sub(r"[^A-Za-z ]", " ", cleaned)
    return {t.upper() for t in cleaned.split() if len(t) >= 4}


def _owner_surname_matches(li: Listing) -> bool:
    """Gate parcel-centroid promotion on owner-name confidence.

    The owner-name -> parcel match has false positives where only a *first*
    name overlaps (e.g. defendant 'Jordan Alexander Avalos' matched owner
    'MCCLELLAN JORDAN RAY'). Require the matched owner and the defendant to
    share at least one 4+char surname-grade token before we trust the centroid
    enough to write it into li.street_address. Defensive: missing owner or
    defendant -> no match -> no promotion.
    """
    defendant = li.defendant or ""
    owner = _matched_owner(li)
    if not defendant.strip() or not owner.strip():
        return False
    return bool(_name_tokens(defendant) & _name_tokens(owner))


def _has_useful_centroid(li: Listing) -> bool:
    if not li.parcel_id or not li.latitude or not li.longitude:
        return False
    # Bounding box for NC + SC (rough). Reject (0,0) or wildly out-of-area
    # coords that would produce nonsense reverse-geo results.
    return 32.0 <= li.latitude <= 37.0 and -84.5 <= li.longitude <= -75.0


async def _reverse_geo(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[dict]:
    """Nominatim reverse lookup. Returns {display_name, address} or None."""
    try:
        r = await c.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat, "lon": lon, "format": "json",
                "zoom": 18, "addressdetails": 1,
            },
            headers={"User-Agent": "foreclosure-scraper/parcel-reverse-geo"},
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


def _promote_approx_address(li: Listing, approx: str, stats: dict) -> None:
    """Promote the reverse-geo approximate address into li.street_address so the
    lead reaches photos/comps/map/outreach. Only when the listing has no real
    street_address and the owner-name->parcel match clears the surname gate.
    Flags raw.address_is_approximate so downstream never treats it as
    authoritative. Defensive: missing/blank approx -> no-op."""
    approx = (approx or "").strip()
    if not approx:
        return
    if not _is_address_less(li):
        return  # never clobber a real (or non-synthetic) street_address
    if not _owner_surname_matches(li):
        stats["promotion_gated"] = stats.get("promotion_gated", 0) + 1
        return
    li.street_address = approx
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["address_is_approximate"] = True
    stats["promoted"] = stats.get("promoted", 0) + 1


async def enrich_parcel_reverse_geo(listings: list[Listing]) -> dict:
    """For every listing with a confident parcel_id + centroid but no real
    street_address, do a Nominatim reverse-geo lookup and annotate the raw
    blob with the approximate address. Never touches ``li.street_address``.
    """
    targets = [
        li for li in listings
        if _is_address_less(li) and _has_useful_centroid(li)
    ]
    if not targets:
        log.info("parcel_reverse_geo.no_targets")
        return {"queried": 0, "annotated": 0}

    log.info("parcel_reverse_geo.start", target_count=len(targets))
    stats = {"queried": 0, "annotated": 0, "no_match": 0,
             "promoted": 0, "promotion_gated": 0}

    # Nominatim's TOS: max 1 request/second from a single client. We use a
    # token bucket via asyncio.sleep (no concurrency).
    async with httpx.AsyncClient() as c:
        for li in targets:
            # Skip the Nominatim query if a previous run already annotated this
            # listing — keep the enrichment idempotent across weekly cycles. We
            # still attempt promotion: ~195 listings were annotated by older
            # runs that never promoted the approx into li.street_address.
            already = (li.raw or {}).get("parcel_resolution", {}) if isinstance(li.raw, dict) else {}
            if already.get("reverse_geo_approx"):
                _promote_approx_address(li, already["reverse_geo_approx"], stats)
                continue

            stats["queried"] += 1
            j = await _reverse_geo(c, li.latitude, li.longitude)
            await asyncio.sleep(1.05)  # be polite to Nominatim

            if not j or not j.get("display_name"):
                stats["no_match"] += 1
                continue

            addr = j.get("address") or {}
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw.setdefault("parcel_resolution", {})
            li.raw["parcel_resolution"]["reverse_geo_approx"] = j["display_name"]
            li.raw["parcel_resolution"]["reverse_geo_components"] = {
                "house_number": addr.get("house_number"),
                "road": addr.get("road"),
                "city": addr.get("city") or addr.get("town") or addr.get("village"),
                "county": addr.get("county"),
                "state": addr.get("state"),
                "postcode": addr.get("postcode"),
            }
            li.raw["parcel_resolution"]["reverse_geo_note"] = (
                "Approximate: nearest-road snap from parcel centroid. "
                "Verify before relying on this address."
            )
            # 2026-06-19: PROMOTE the resolved county to li.county when missing.
            # Reverse-geo already had it but only stashed it in components, so 600+
            # listings sat county-less. Normalize "Buncombe County" -> "Buncombe".
            # The post-enrichment scope re-pass (main.py) then drops any that
            # resolve to a denied county.
            rg_county = (addr.get("county") or "").replace(" County", "").strip()
            if rg_county and not (li.county or "").strip():
                li.county = rg_county
                stats["county_filled"] = stats.get("county_filled", 0) + 1
            stats["annotated"] += 1
            _promote_approx_address(li, j["display_name"], stats)

    log.info("parcel_reverse_geo.done", **stats)
    return stats
