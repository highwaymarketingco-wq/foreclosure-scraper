"""SITUS-ADDRESS WRITER — the #1 address unlock.

The single biggest address gap is leads that carry a parcel_id and/or a
lat/lng but no street_address (lis-pendens rolls, courthouse auction lists,
distressed feeds with only a point). The county GIS parcel feature already
knows the property's SITUS (physical) address — we just weren't writing it
onto the Listing.

What this does (per address-LESS lead that has parcel_id OR lat/lng):
  1. Find the matched GIS attribute bag. enrichment_gis_attrs already stashes
     the full feature in raw['gis_attrs_full'] (outFields=*), so for any lead
     it touched we read straight from there — ZERO new HTTP.
  2. If gis_attrs_full is absent (the lead was skipped by gis_attrs because it
     already had every value/spec field, or gis_attrs hasn't run), query the
     county GIS ourselves: point-in-polygon on lat/lng first, parcel-id where-
     query as fallback. The matched bag is stashed back into gis_attrs_full.
  3. Pull the SITUS street address out of that bag using the situs-preferring
     field detector from enrichment_arcgis (_detect_addr_field /
     _ADDR_FIELD_CANDIDATES), and the matching city + zip. NEVER an owner-
     mailing field (_MAILING_FIELD_MARKERS) and never a C/O / PO-box / blank /
     '0 NO ADDRESS' placeholder.
  4. Write li.street_address (+ li.city, li.zip_code) — missing-only, never
     overwrites a real address.

Free / pure-HTTP / no auth / compliant. Reuses the exact SCDOT + NC GIS
endpoints and situs field list already audited in enrichment_arcgis.

Wiring (orchestrator owns the single write; do NOT wire here): add
    from foreclosure_scraper.enrichment_situs_address import enrich_situs_address
    await _step("situs_address", enrich_situs_address(merged, concurrency=16))
in scripts/merge_today_sources.py immediately AFTER the "gis_attrs" step and
BEFORE images / the second geocode pass (so the freshly-written address feeds
photo lookup + geocode + map markers). It is idempotent and missing-only, so
ordering relative to address_backfill/aggressive_address is not critical, but
running it right after gis_attrs lets it reuse gis_attrs_full with no new HTTP.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from .enrichment_arcgis import (
    _detect_addr_field,
    _MAILING_FIELD_MARKERS,
)
from .enrichment_gis_attrs import (
    _query_parcel,
    _query_point,
    _resolve_layer,
)
from .http_client import client
from .models import Listing

log = structlog.get_logger()


# City / ZIP companion fields (case-insensitive). Situs city/zip preferred over
# any mailing city/zip — the same _MAILING_FIELD_MARKERS guard is applied so a
# layer's owner-mailing CITY/ZIP never wins.
_CITY_FIELD_CANDIDATES = (
    "LOCCITY", "SITUS_CITY", "SITUSCITY", "PROP_CITY", "PROPCITY",
    "PHYSCITY", "PHYS_CITY", "SITE_CITY", "City", "CITY",
)
_ZIP_FIELD_CANDIDATES = (
    "LOCZIP", "SITUS_ZIP", "SITUSZIP", "PROP_ZIP", "PROPZIP",
    "PHYSZIP", "PHYS_ZIP", "SITE_ZIP", "Zip", "ZIP", "ZIPCODE", "ZipCode",
)

# Some layers (e.g. Georgetown SC) carry NO single combined situs-address field —
# only a split house-number + street-name pair — so the combined-field detector
# finds nothing and the lead stays address-less. These let us compose the situs
# from the split parts. All are situs (non-mailing) field names; the same
# _MAILING_FIELD_MARKERS guard still applies in _pick_field.
_STREET_NUM_FIELD_CANDIDATES = (
    "StreetNumber", "STREETNUMBER", "STREET_NUM", "STREETNUM", "STR_NUM",
    "HOUSE_NUM", "HOUSENUM", "HOUSE_NO", "HOUSENO", "SITUS_NUM", "ADDR_NUM",
)
_STREET_NAME_FIELD_CANDIDATES = (
    "StreetName", "STREETNAME", "STREET_NAME", "STREETNM", "STR_NAME",
    "SITUS_STREET", "SITE_STREET", "ROAD_NAME", "RD_NAME",
)


# Trailing sub-parcel / interest suffix some counties append to a base parcel id
# (e.g. Georgetown SC FLC PINs "01-0442-029-03-00.001") that the county GIS TMS /
# parcel field does NOT carry — it stores only the base "01-0442-029-03-00".
_SUBPARCEL_SUFFIX_RE = re.compile(r"\.\d+$")


async def _query_parcel_norm(
    c: httpx.AsyncClient, base: str, parcel: str
) -> dict[str, Any] | None:
    """Exact parcel-id match, with a sub-parcel-suffix retry on zero result.

    The county GIS exact match is tried first (unchanged behaviour). Only when it
    returns NOTHING do we strip a trailing ".NNN" sub-parcel suffix and retry —
    this is what unlocks Georgetown SC FLC leads whose PIN carries a sub-parcel
    suffix the SCDOT TMS field lacks. Scoped to the zero-result retry path so it
    can never mis-resolve a county whose exact id already matched, and it is a
    no-op for any parcel that has no such suffix.
    """
    attrs = await _query_parcel(c, base, parcel)
    if attrs is not None:
        return attrs
    stripped = _SUBPARCEL_SUFFIX_RE.sub("", parcel.strip())
    if stripped and stripped != parcel.strip():
        return await _query_parcel(c, base, stripped)
    return None


def _norm_ci(attrs: dict[str, Any]) -> dict[str, Any]:
    """Lowercase-keyed view of the attribute bag (drops _centroid/_match_* meta)."""
    return {k.lower(): v for k, v in attrs.items() if not k.startswith("_")}


def _pick_field(norm: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    """First non-empty candidate that is NOT an owner-mailing field."""
    for cand in candidates:
        cl = cand.lower()
        if any(m in cl for m in _MAILING_FIELD_MARKERS):
            continue
        v = norm.get(cl)
        if v not in (None, "", " ", "<Null>", "NULL"):
            return v
    return None


def _is_junk_address(s: str) -> bool:
    """Reject GIS placeholders and non-situs strings.

    Counties stuff parcels with no registered address with placeholders, and
    some layers leak owner C/O or PO-box mailing lines into a generic addr
    field — none of those are a usable property situs.
    """
    if not s:
        return True
    u = s.strip().upper()
    if u in ("", "0", "UNKNOWN", "NONE", "N/A", "NA", "TBD", "NULL"):
        return True
    if "NO ADDRESS" in u or u.startswith("0 NO ") or u.startswith("0 NO-"):
        return True
    if "C/O" in u or " C O " in u or u.startswith("CO "):
        return True
    if "PO BOX" in u or "P O BOX" in u or "P.O." in u or "POBOX" in u:
        return True
    # Must contain at least one letter (a street name) — a bare number or a
    # string of punctuation is not a real address.
    if not any(ch.isalpha() for ch in u):
        return True
    # A real situs has a house number OR a named street; require >= 4 chars of
    # signal so we don't accept stray tokens.
    if len(re.sub(r"[^A-Za-z0-9]", "", u)) < 4:
        return True
    return False


def apply_situs_address(li: Listing, attrs: dict[str, Any], addr_field: str | None = None) -> int:
    """Write SITUS street_address (+ city + zip) from a matched GIS feature.

    Missing-only: never overwrites an existing real address. Returns the number
    of address fields newly populated (0-3). `addr_field`, when supplied, is the
    situs field detected for this layer; otherwise we fall back to the
    situs-preferring candidate scan over the bag's own keys.
    """
    if li.street_address and li.street_address.strip():
        return 0  # already has a real address — nothing to do

    norm = _norm_ci(attrs)
    filled = 0

    # Resolve the situs value. Prefer the layer-detected situs field (already
    # mailing-filtered); fall back to the situs-preferring candidate list.
    raw_addr = None
    if addr_field and not any(m in addr_field.lower() for m in _MAILING_FIELD_MARKERS):
        raw_addr = norm.get(addr_field.lower())
    if raw_addr in (None, "", " "):
        # Reuse the same priority list the detector uses, but read it directly
        # from the bag here (situs fields first, mailing fields excluded).
        from .enrichment_arcgis import _ADDR_FIELD_CANDIDATES
        raw_addr = _pick_field(norm, _ADDR_FIELD_CANDIDATES)

    if raw_addr in (None, "", " "):
        # No combined situs field — compose from split house-number + street-name
        # (the only situs form some layers, e.g. Georgetown SC, expose). Street
        # name alone is enough to write; the number is prepended when present.
        num = _pick_field(norm, _STREET_NUM_FIELD_CANDIDATES)
        name = _pick_field(norm, _STREET_NAME_FIELD_CANDIDATES)
        name_s = re.sub(r"\s+", " ", str(name).strip()) if name not in (None, "") else ""
        if name_s and any(ch.isalpha() for ch in name_s):
            num_s = re.sub(r"\s+", " ", str(num).strip()) if num not in (None, "") else ""
            raw_addr = f"{num_s} {name_s}".strip() if num_s else name_s

    if raw_addr in (None, "", " "):
        return 0

    addr = re.sub(r"\s+", " ", str(raw_addr).strip())
    if _is_junk_address(addr):
        return 0

    li.street_address = addr
    filled += 1

    # Companion situs city.
    if not (li.city and li.city.strip()):
        city = _pick_field(norm, _CITY_FIELD_CANDIDATES)
        if city:
            cs = re.sub(r"\s+", " ", str(city).strip())
            if cs and not cs.isdigit() and len(cs) >= 2:
                li.city = cs.title() if cs.isupper() else cs
                filled += 1

    # Companion situs zip (first 5 digits).
    if not (li.zip_code and li.zip_code.strip()):
        z = _pick_field(norm, _ZIP_FIELD_CANDIDATES)
        if z is not None:
            digits = re.sub(r"\D", "", str(z))
            if len(digits) >= 5:
                li.zip_code = digits[:5]
                filled += 1

    # Provenance breadcrumb so the dashboard / QA can see the source.
    if isinstance(li.raw, dict):
        li.raw["situs_address_source"] = "gis_parcel_situs"

    return filled


# ---- Public API ----------------------------------------------------------------

async def enrich_situs_address(listings: list[Listing], concurrency: int = 16) -> dict:
    """Write SITUS addresses for every address-LESS lead that carries a
    parcel_id OR lat/lng in a supported SC/NC county.

    Strategy per lead:
      * reuse raw['gis_attrs_full'] if present (no HTTP),
      * else query the county GIS (point-in-polygon, then parcel-id fallback)
        and stash the bag back into gis_attrs_full.

    Returns a stats dict for the orchestrator log.
    """
    targets = [
        li for li in listings
        if not (li.street_address and li.street_address.strip())
        and ((li.parcel_id and li.parcel_id.strip())
             or (li.latitude is not None and li.longitude is not None))
    ]
    stats = {
        "targets": len(targets), "of_total": len(listings),
        "from_cache": 0, "queried": 0, "matched": 0,
        "wrote_address": 0, "wrote_city": 0, "wrote_zip": 0, "junk_skipped": 0,
    }
    if not targets:
        log.info("situs_address.no_targets")
        return stats

    # PLACEHOLDER-COORDINATE DETECTION. Many lis-pendens / courthouse-roll leads
    # carry only a county-centroid point (e.g. thousands of distinct parcels all
    # tagged with one coord). A real distinct property never shares an EXACT
    # coordinate with others; a coord shared by 3+ leads is a placeholder. We
    # refuse point-in-polygon for those — it would write one wrong situs to all
    # of them. Such leads must resolve by parcel_id or not at all.
    from collections import Counter
    coord_counts: Counter = Counter()
    for li in targets:
        if li.latitude is not None and li.longitude is not None:
            try:
                coord_counts[(round(float(li.latitude), 4), round(float(li.longitude), 4))] += 1
            except (ValueError, TypeError):
                pass
    placeholder_coords = {k for k, n in coord_counts.items() if n >= 3}
    stats["placeholder_coords"] = len(placeholder_coords)

    def _is_placeholder_point(li: Listing) -> bool:
        if li.latitude is None or li.longitude is None:
            return False
        try:
            return (round(float(li.latitude), 4), round(float(li.longitude), 4)) in placeholder_coords
        except (ValueError, TypeError):
            return False

    sem = asyncio.Semaphore(concurrency)
    # Per-layer situs-field cache so we resolve the addr field once per county.
    addr_field_cache: dict[str, str | None] = {}

    async def _addr_field_for(c: httpx.AsyncClient, base: str) -> str | None:
        if base not in addr_field_cache:
            addr_field_cache[base] = await _detect_addr_field(c, base)
        return addr_field_cache[base]

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        base = _resolve_layer(li)  # may be None for unsupported counties
        has_parcel = bool(li.parcel_id and li.parcel_id.strip())
        placeholder_pt = _is_placeholder_point(li)

        # 1) Cheapest path: a previously-stashed full attribute bag.
        #    BUT distrust a cached bag for placeholder-point leads — gis_attrs
        #    also queries point-first, so the cached bag may be the WRONG parcel
        #    that sits at the shared centroid. For those, re-resolve by parcel_id.
        attrs: dict[str, Any] | None = None
        from_cache = False
        if (isinstance(li.raw, dict)
                and isinstance(li.raw.get("gis_attrs_full"), dict)
                and not (placeholder_pt and has_parcel)):
            attrs = li.raw["gis_attrs_full"]
            from_cache = True

        # 2) No trusted cached bag → query the GIS ourselves.
        #
        # PARCEL-ID FIRST. The parcel_id uniquely identifies the property; a
        # lat/lng can be imprecise or an outright PLACEHOLDER. Point-in-polygon
        # is only a fallback, and is SKIPPED entirely when the coordinate is a
        # detected placeholder (shared by many leads).
        if attrs is None:
            if not base:
                return
            async with sem:
                if has_parcel:
                    attrs = await _query_parcel_norm(c, base, li.parcel_id)
                if (attrs is None and not placeholder_pt
                        and li.latitude is not None and li.longitude is not None):
                    try:
                        attrs = await _query_point(
                            c, base, float(li.latitude), float(li.longitude)
                        )
                    except (ValueError, TypeError):
                        attrs = None
                stats["queried"] += 1
            if not attrs:
                return
            # Stash for any later enricher (gis_derived, etc.) — outFields=* bag.
            if isinstance(li.raw, dict):
                li.raw["gis_attrs_full"] = attrs

        if from_cache:
            stats["from_cache"] += 1
        stats["matched"] += 1

        # Resolve the situs field for this layer (mailing-filtered) when we know
        # the layer; otherwise apply_situs_address scans the bag's own keys.
        addr_field = None
        if base:
            async with sem:
                addr_field = await _addr_field_for(c, base)

        before_addr = bool(li.street_address and li.street_address.strip())
        n = apply_situs_address(li, attrs, addr_field=addr_field)
        if n == 0:
            if not before_addr:
                stats["junk_skipped"] += 1
            return
        if li.street_address and not before_addr:
            stats["wrote_address"] += 1
        # city/zip counted by delta is overkill; track via the returned count.
        if n >= 2:
            stats["wrote_city"] += 1
        if n >= 3:
            stats["wrote_zip"] += 1

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("enrichment.situs_address.done", **stats)
    return stats
