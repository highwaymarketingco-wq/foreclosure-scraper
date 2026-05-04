"""Address backfill via county GIS owner-name lookup.

Many of our scrapers (SC Public Index lis pendens, NC eCourts, courthouse
auction rolls without address columns) emit listings with a defendant name
but NO street address. This breaks downstream:
  - HomeHarvest/Realtor.com photo lookup needs an address
  - Vision needs photos
  - Comp matching prefers an address+zip
  - Map display has no marker

Fix: when a listing has defendant + county + state but no address, hit the
county GIS owner field with a LIKE query on the defendant's distinctive
last name (or LLC name root). If a single match comes back, populate the
address. Pure HTTP, free, leverages the same county GIS endpoints we
already use for address-based enrichment.

Confidence rules:
  - Single result with surname token in owner field → high confidence, write
  - Multiple results → only write if one is unique by additional defendant token
  - Zero results → leave alone
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from .enrichment_arcgis import (
    FIELD_ALIASES,
    NC_GIS,
    SC_LAYER,
    SCDOT_BASE,
    _detect_addr_field,
    _pick,
)
from .http_client import client
from .models import Listing

log = structlog.get_logger()


# Owner-name field candidates per layer schema (case-insensitive). Same set
# we use in enrichment_arcgis for reading, just used differently here (for
# the WHERE clause).
_OWNER_FIELD_CANDIDATES = (
    "OwnerName", "OWNAM1", "Owner1", "PROPERTY_OWNER",
    "full_owner_name", "owner", "ownname", "NAME1", "OWNER_NAME",
    "Name1", "Name", "OWNER", "NAMECO", "OwnerName1",
)


async def _detect_owner_field(c: httpx.AsyncClient, base_url: str) -> str | None:
    """Hit the layer's ?f=json once, find an owner-name field."""
    layer_url = base_url.rsplit("/query", 1)[0]
    try:
        r = await c.get(layer_url, params={"f": "json"}, timeout=15.0)
        if r.status_code != 200:
            return None
        data = r.json()
        fields = [f["name"] for f in data.get("fields", []) if "name" in f]
    except (httpx.HTTPError, ValueError):
        return None
    field_lower = {f.lower(): f for f in fields}
    for cand in _OWNER_FIELD_CANDIDATES:
        if cand.lower() in field_lower:
            return field_lower[cand.lower()]
    # Fallback: any field named "owner" (excluding mailing)
    for f in fields:
        flow = f.lower()
        if "owner" in flow and "mail" not in flow and "addr" not in flow:
            return f
    return None


_BUSINESS_STOPWORDS = {
    "llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp",
    "llp", "trust", "trustee", "estate", "of", "the", "and",
}


def _defendant_search_terms(name: str) -> list[str]:
    """Return search terms ordered by specificity. We try the most distinctive
    first (longest non-stopword token), then fall back to broader matches.
    """
    if not name:
        return []
    s = name.lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split() if len(t) >= 3 and t not in _BUSINESS_STOPWORDS]
    if not tokens:
        return []
    # Try multi-token first (e.g. "MARCUS BROWN" → "%MARCUS%BROWN%"), then
    # single distinctive token (longest), then individual tokens
    tokens_sorted = sorted(tokens, key=len, reverse=True)
    out: list[str] = []
    if len(tokens_sorted) >= 2:
        # First+last name combo, normalized order
        out.append(f"%{tokens_sorted[1].upper()}%{tokens_sorted[0].upper()}%")
        out.append(f"%{tokens_sorted[0].upper()}%{tokens_sorted[1].upper()}%")
    out.append(f"%{tokens_sorted[0].upper()}%")
    return out


async def _query_by_owner(
    c: httpx.AsyncClient,
    base_url: str,
    owner_field: str,
    defendant: str,
) -> list[dict[str, Any]]:
    """Search the layer by owner-name LIKE patterns. Returns deduped results."""
    patterns = _defendant_search_terms(defendant)
    if not patterns:
        return []
    seen_oids: set[Any] = set()
    out: list[dict[str, Any]] = []
    for pat in patterns:
        where = (
            f"UPPER({owner_field}) LIKE '{pat.replace(chr(39), chr(39)+chr(39))}'"
        )
        try:
            r = await c.get(
                base_url,
                params={
                    "where": where,
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": "8",
                    "f": "json",
                },
                timeout=20.0,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            for f in data.get("features", []):
                attrs = dict(f.get("attributes", {}) or {})
                oid = attrs.get("OBJECTID") or attrs.get("FID")
                if oid and oid in seen_oids:
                    continue
                if oid:
                    seen_oids.add(oid)
                # Centroid
                geom = f.get("geometry") or {}
                cx = cy = None
                if "x" in geom and "y" in geom:
                    cx, cy = geom["x"], geom["y"]
                elif geom.get("rings"):
                    pts = [p for ring in geom["rings"] for p in ring]
                    if pts:
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                if cx is not None and cy is not None:
                    attrs["_centroid"] = (cy, cx)
                out.append(attrs)
            if out:
                # Stop on first pattern that returns results — most specific wins
                break
        except (httpx.HTTPError, ValueError):
            continue
    return out


def _populate_from_attrs(li: Listing, attrs: dict[str, Any]) -> int:
    """Fill the missing-address fields from a GIS record. Conservative:
    only writes when the field is currently empty.

    Also writes parcel_id (with confidence flag), property specs, and
    infers property_kind from zoning/structure when we can.
    """
    from .enrichment_arcgis import _apply_attrs
    from .models import PropertyKind

    filled = 0

    site = _pick(attrs, FIELD_ALIASES["site_address"])
    if site and not li.street_address:
        site_str = str(site).strip()
        # Filter out GIS placeholder strings (counties use these for parcels
        # without a registered address — e.g. raw land, easements, ROW)
        site_upper = site_str.upper()
        is_placeholder = (
            "NO ADDRESS" in site_upper
            or site_upper in ("UNKNOWN", "NONE", "N/A", "TBD", "0")
            or site_upper.startswith("0 NO ")
            or site_str.strip() in ("", "0")
        )
        if not is_placeholder:
            li.street_address = site_str
            filled += 1

    city = _pick(attrs, FIELD_ALIASES["city"])
    if city and not li.city:
        li.city = str(city).strip()
        filled += 1

    z = _pick(attrs, FIELD_ALIASES["zip"])
    if z and not li.zip_code:
        zs = str(z).strip()
        if zs.isdigit() and len(zs) >= 5:
            li.zip_code = zs[:5]
            filled += 1

    centroid = attrs.get("_centroid")
    if centroid and not li.latitude and not li.longitude:
        try:
            li.latitude = float(centroid[0])
            li.longitude = float(centroid[1])
            filled += 2
        except (ValueError, TypeError):
            pass

    # Owner / mailing — useful for verification
    owner = _pick(attrs, FIELD_ALIASES["owner_name"])
    if owner:
        gis = li.raw.setdefault("gis", {})
        if not gis.get("owner"):
            gis["owner"] = str(owner).strip()
            filled += 1
        gis["owner_match_strategy"] = "name_search"

    # Reuse the standard arcgis attr application for the property specs
    # (year_built, sqft, beds, baths, tax_value, parcel_id with confidence).
    # We're at this code path because owner-name was a confident match.
    attrs.setdefault("_match_confident", True)
    filled += _apply_attrs(li, attrs)

    # Best-effort property_kind inference from zoning + structure fields
    if not li.property_kind or li.property_kind == PropertyKind.UNKNOWN:
        kind = _infer_property_kind(attrs)
        if kind:
            li.property_kind = kind
            filled += 1

    return filled


def _infer_property_kind(attrs: dict[str, Any]):
    """Guess property_kind from GIS zoning/structure fields.

    Uses a blob of zoning + land-use-ish fields, plus living_sqft + acreage
    heuristics. Returns a PropertyKind or None if nothing distinctive.
    """
    from .models import PropertyKind

    z = (_pick(attrs, FIELD_ALIASES["zoning"]) or "").upper()
    living = _pick(attrs, FIELD_ALIASES["living_sqft"])
    try:
        living_f = float(living) if living else 0.0
    except (TypeError, ValueError):
        living_f = 0.0
    acreage = _pick(attrs, FIELD_ALIASES["acreage"])
    try:
        acres_f = float(acreage) if acreage else 0.0
    except (TypeError, ValueError):
        acres_f = 0.0

    use = ""
    norm_keys = {k.lower(): k for k in attrs.keys()}
    for k in ("LAND_USE", "LandUse", "USE_DESC", "PROP_CLASS", "PROPCLASS",
              "PROPERTY_CLASS", "PROPERTY_TYPE", "PROPTYPE", "BLDG_USE",
              "BUILDING_USE", "DESCRIPT", "PROP_DESC"):
        if k.lower() in norm_keys:
            v = attrs.get(norm_keys[k.lower()])
            if v:
                use = str(v).upper()
                break

    blob = f"{z} {use}"

    if "MULTI" in blob or "APARTMENT" in blob or "DUPLEX" in blob or "TRIPLEX" in blob:
        return PropertyKind.MULTI_FAMILY
    if "CONDO" in blob:
        return PropertyKind.CONDO
    if "TOWNHOUSE" in blob or "TOWNHOME" in blob:
        return PropertyKind.TOWNHOUSE
    if "MANUFACTURED" in blob or "MOBILE" in blob:
        return PropertyKind.MOBILE
    if ("COMMERCIAL" in blob or "INDUSTRIAL" in blob or "RETAIL" in blob
            or "OFFICE" in blob):
        return PropertyKind.COMMERCIAL
    # Pure land: zero/low building sqft + meaningful acreage
    if living_f < 100 and acres_f >= 0.05:
        return PropertyKind.LAND
    # Standard SFR — has a building of meaningful size
    if living_f >= 400:
        return PropertyKind.SINGLE_FAMILY
    return None


async def enrich_addresses_from_owner(
    listings: list[Listing], concurrency: int = 6
) -> None:
    """For every listing with defendant + county + state but no street_address,
    look up the property by owner name in the appropriate county GIS and
    populate the address fields when a confident match comes back.
    """
    targets = [
        li
        for li in listings
        if li.defendant
        and li.county
        and li.state
        and not li.street_address
        and li.source != "national.courtlistener_bankruptcy"
    ]
    if not targets:
        log.info("addr_backfill.no_targets")
        return  # bankruptcy listings handled by enrich_bankruptcy_property below

    log.info("addr_backfill.start", target_count=len(targets), of_total=len(listings))

    sem = asyncio.Semaphore(concurrency)
    counts = {"queried": 0, "matched_single": 0, "matched_multi": 0,
              "fields_filled": 0, "no_layer": 0, "no_owner_field": 0}
    owner_field_cache: dict[str, str | None] = {}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        # Resolve county GIS endpoint
        county_clean = li.county.replace(" County", "").strip()
        for suffix in (", NC", ", SC", ",NC", ",SC"):
            if county_clean.upper().endswith(suffix):
                county_clean = county_clean[: -len(suffix)].strip()
        county_clean = county_clean.split(",")[0].strip()

        if li.state == "SC":
            layer = SC_LAYER.get(county_clean)
            if not layer:
                counts["no_layer"] += 1
                return
            base = f"{SCDOT_BASE}/{layer}/query"
        elif li.state == "NC":
            cfg = NC_GIS.get(county_clean)
            if not cfg:
                counts["no_layer"] += 1
                return
            base = cfg["url"]
        else:
            return

        # Detect owner field once per layer
        if base not in owner_field_cache:
            owner_field_cache[base] = await _detect_owner_field(c, base)
        owner_field = owner_field_cache[base]
        if not owner_field:
            counts["no_owner_field"] += 1
            return

        async with sem:
            counts["queried"] += 1
            results = await _query_by_owner(c, base, owner_field, li.defendant)
            if not results:
                return
            # Confidence: only auto-populate when a single result comes back.
            # Multiple results → too risky (could be two different properties
            # owned by different "Smith"s). We could break ties by checking
            # all defendant tokens in the owner string, but conservative wins.
            if len(results) == 1:
                counts["matched_single"] += 1
                counts["fields_filled"] += _populate_from_attrs(li, results[0])
            else:
                counts["matched_multi"] += 1
                # Try to find a uniquely-best result: one whose owner contains
                # ALL of the defendant's distinctive tokens
                d_tokens = {
                    t for t in re.split(r"\W+", li.defendant.lower())
                    if len(t) >= 3 and t not in _BUSINESS_STOPWORDS
                }
                best = None
                best_score = 0
                for r in results:
                    owner = (_pick(r, FIELD_ALIASES["owner_name"]) or "").lower()
                    score = sum(1 for t in d_tokens if t in owner)
                    if score > best_score:
                        best_score = score
                        best = r
                # Need ALL distinctive tokens to match to call it confident
                if best and best_score == len(d_tokens) and len(d_tokens) >= 2:
                    counts["fields_filled"] += _populate_from_attrs(li, best)

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("addr_backfill.done", **counts)
