"""Parcel-based address resolution.

Many listings have a parcel_id (REID/PIN/TMS) but no street address. Common
cases: tax foreclosures on undeveloped lots, lis pendens on parcels referenced
by tax-roll number only, courthouse rosters that publish parcel# instead of
street.

This enrichment:
  1. Detects parcel-like identifiers (in parcel_id field OR in description text
     via regex for "REID Number XXX", "PIN: XXX", "TMS: XXX-XX-XX-XXX", etc.)
  2. Queries the appropriate county GIS by parcel/PIN/REID
  3. Backfills street_address (or synthesized lot+subdivision when GIS shows
     "0 NO ADDRESS ASSIGNED" / undeveloped lot)
  4. Backfills city/zip/lat/lng/sqft/year_built/acreage/owner when available

Free, pure HTTP, no auth.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx
import structlog

from .enrichment_arcgis import (
    FIELD_ALIASES,
    NC_GIS,
    SC_LAYER,
    SCDOT_BASE,
    _apply_attrs,
    _pick,
)
from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()


# Parcel-id field-name candidates per layer schema (case-insensitive).
PARCEL_FIELD_CANDIDATES = (
    "PIN", "REID", "TMS", "PARCEL", "PARCELNUMBER", "PARCEL_ID",
    "PARNO", "PARID", "MAPNUMBER", "pid_long", "pinnum", "pid",
)


# Regex patterns to extract parcel/PIN/REID from description text
PARCEL_PATTERNS = (
    re.compile(r"\bREID\s*(?:Number|#|No\.?)?\s*[:=]?\s*([\d\-]{4,15})\b", re.I),
    re.compile(r"\bPIN\s*(?:Number|#|No\.?)?\s*[:=]?\s*([\d\-]{6,15})\b", re.I),
    re.compile(r"\bTMS\s*[:=]?\s*([\d\-]{6,20})\b", re.I),
    re.compile(r"\bParcel\s*(?:Number|#|No\.?|ID)?\s*[:=]?\s*([\d\-]{4,15})\b", re.I),
    # SC tax map number format: 0123-45-6789 or 0123-45-67-890
    re.compile(r"\b(\d{3,4}-\d{2}-\d{2}-\d{3,4})\b"),
)

# Subdivision/lot extraction from description (NC tax format)
SUBDIVISION_RE = re.compile(
    r"\b([A-Z][A-Z0-9& '\-]{3,40}?)\s+(?:LO|LOT|LT)[:.]?\s*(\d+)"
    r"(?:\s+(?:PH|PHASE|BL|BLK|BLOCK)[:.]?\s*([A-Z0-9]+))?",
    re.I,
)


def _extract_parcel_candidates(text: str) -> list[str]:
    if not text:
        return []
    out: set[str] = set()
    for pat in PARCEL_PATTERNS:
        for m in pat.finditer(text):
            v = m.group(1).strip()
            if len(v) >= 4:
                out.add(v)
    return list(out)


def _synthesize_address_from_description(
    description: str, gis_attrs: dict[str, Any]
) -> Optional[str]:
    """When GIS returns "0 NO ADDRESS ASSIGNED" we can still construct a
    usable identifier from subdivision + lot info in the original description.
    Example: 'SEVEN FALLS LO:127 PH:1A' + city/zip → 'Lot 127 Seven Falls Ph 1A'.
    """
    if not description:
        return None
    m = SUBDIVISION_RE.search(description.upper())
    if not m:
        return None
    subdivision = m.group(1).strip().title()
    lot = m.group(2)
    phase = m.group(3) or ""
    pieces = [f"Lot {lot}", subdivision]
    if phase:
        pieces.append(f"Ph {phase}")
    return " ".join(pieces)


async def _detect_parcel_field(
    c: httpx.AsyncClient, base_url: str
) -> Optional[str]:
    layer_url = base_url.rsplit("/query", 1)[0]
    try:
        r = await c.get(layer_url, params={"f": "json"}, timeout=15.0)
        if r.status_code != 200:
            return None
        fields = [f["name"] for f in r.json().get("fields", []) if "name" in f]
    except (httpx.HTTPError, ValueError):
        return None
    field_lower = {f.lower(): f for f in fields}
    for cand in PARCEL_FIELD_CANDIDATES:
        if cand.lower() in field_lower:
            return field_lower[cand.lower()]
    return None


async def _query_by_parcel(
    c: httpx.AsyncClient,
    base_url: str,
    parcel_value: str,
) -> list[dict[str, Any]]:
    """Try multiple parcel-field names. First match wins."""
    layer_url = base_url.rsplit("/query", 1)[0]
    try:
        r = await c.get(layer_url, params={"f": "json"}, timeout=10.0)
        if r.status_code != 200:
            return []
        fields = [f["name"] for f in r.json().get("fields", []) if "name" in f]
    except Exception:
        return []
    field_lower = {f.lower(): f for f in fields}
    candidates: list[str] = []
    for cand in PARCEL_FIELD_CANDIDATES:
        actual = field_lower.get(cand.lower())
        if actual:
            candidates.append(actual)

    for fld in candidates:
        try:
            r = await c.get(
                base_url,
                params={
                    "where": f"{fld}='{parcel_value}'",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": "3",
                    "f": "json",
                },
                timeout=15.0,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            for f in data.get("features", []):
                attrs = dict(f.get("attributes", {}) or {})
                geom = f.get("geometry") or {}
                if "x" in geom and "y" in geom:
                    attrs["_centroid"] = (geom["y"], geom["x"])
                elif geom.get("rings"):
                    pts = [p for ring in geom["rings"] for p in ring]
                    if pts:
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                        attrs["_centroid"] = (cy, cx)
                if attrs:
                    return [attrs]  # first hit wins
        except Exception:
            continue
    return []


def _populate_from_parcel(li: Listing, attrs: dict[str, Any]) -> int:
    """Apply GIS attributes to a listing. Always sets some address field —
    falls back to subdivision+lot synthesis when GIS has no address.
    """
    filled = 0

    # Primary: read site_address from any of the common field names
    site = _pick(attrs, FIELD_ALIASES["site_address"])
    if site:
        site_str = str(site).strip()
        upper = site_str.upper()
        is_placeholder = (
            "NO ADDRESS" in upper or upper.startswith("0 NO ")
            or upper in ("UNKNOWN", "NONE", "N/A", "TBD", "0")
        )
        if not is_placeholder:
            li.street_address = site_str
            filled += 1

    # If still no street_address, synthesize from subdivision+lot in description
    if not li.street_address:
        synth = _synthesize_address_from_description(li.description or "", attrs)
        if synth:
            li.street_address = synth
            filled += 1

    # City/zip
    city = _pick(attrs, FIELD_ALIASES["city"])
    if city and not li.city:
        c = str(city).strip().title()
        if c and c.upper() != "NO ADDRESS":
            li.city = c
            filled += 1
    z = _pick(attrs, FIELD_ALIASES["zip"])
    if z and not li.zip_code:
        zs = str(z).strip()
        if zs.isdigit() and len(zs) >= 5:
            li.zip_code = zs[:5]
            filled += 1

    # Coordinates
    centroid = attrs.get("_centroid")
    if centroid and not li.latitude and not li.longitude:
        try:
            li.latitude = float(centroid[0])
            li.longitude = float(centroid[1])
            filled += 2
        except (ValueError, TypeError):
            pass

    # Owner
    owner = _pick(attrs, FIELD_ALIASES["owner_name"])
    if owner and isinstance(li.raw, dict):
        gis = li.raw.setdefault("gis", {})
        if not gis.get("owner"):
            gis["owner"] = str(owner).strip()
            filled += 1
        gis["owner_match_strategy"] = "parcel_lookup"

    # Specs (sqft/beds/baths/year/acreage/tax_value)
    attrs.setdefault("_match_confident", True)
    filled += _apply_attrs(li, attrs)

    return filled


async def enrich_with_parcel_lookup(listings: list[Listing]) -> None:
    """For listings without addresses, look up parcel/PIN/REID in county GIS."""
    targets = []
    for li in listings:
        if li.street_address:
            continue
        if li.source == "national.courtlistener_bankruptcy":
            continue
        # Need state + county to know which GIS to hit
        if not (li.state and li.county):
            continue
        # Either explicit parcel_id or one extractable from description
        if li.parcel_id or _extract_parcel_candidates(li.description or ""):
            targets.append(li)

    if not targets:
        log.info("parcel_lookup.no_targets")
        return

    log.info("parcel_lookup.start", target_count=len(targets))

    sem = asyncio.Semaphore(6)
    counts = {"queried": 0, "matched": 0, "addr_resolved": 0, "synthesized": 0}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        # Resolve county GIS endpoint
        county_clean = li.county.replace(" County", "").strip().title()
        county_clean = county_clean.split(",")[0].strip()
        if li.state == "NC":
            cfg = NC_GIS.get(county_clean)
            if not cfg:
                return
            base = cfg["url"]
        elif li.state == "SC":
            layer = SC_LAYER.get(county_clean)
            if not layer:
                return
            base = f"{SCDOT_BASE}/{layer}/query"
        else:
            return

        # Build candidate parcel values to try
        candidates: list[str] = []
        if li.parcel_id:
            candidates.append(li.parcel_id.strip())
        candidates.extend(_extract_parcel_candidates(li.description or ""))
        # Dedupe preserving order
        seen: set[str] = set()
        candidates = [c for c in candidates if not (c in seen or seen.add(c))]

        async with sem:
            counts["queried"] += 1
            for pv in candidates[:5]:  # cap attempts per listing
                results = await _query_by_parcel(c, base, pv)
                if results:
                    counts["matched"] += 1
                    had_addr = bool(li.street_address)
                    n = _populate_from_parcel(li, results[0])
                    if li.street_address and not had_addr:
                        # Decide whether it's real or synthesized
                        if "Lot " in li.street_address and " Ph " in li.street_address.lower():
                            counts["synthesized"] += 1
                        else:
                            counts["addr_resolved"] += 1
                    return

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("parcel_lookup.done", **counts)
