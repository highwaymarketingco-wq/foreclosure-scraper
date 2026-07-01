"""Fannie Mae HomePath REO — address → current propertyUuid re-resolver.

Fannie's HomePath SPA keys every property by a ``propertyUuid`` that appears in
the per-property URL (``/property/{uuid}``). That uuid ROTATES: when Fannie
re-lists / re-syncs a property (price change, status flip, MLS re-feed) the
address stays put but the uuid changes, so a carried-over lead's stored
``source_url`` silently rots — the SPA renders a client-side 404 (HTTP is still
200) and the operator clicks a dead link. Roughly ~58 of ~1057 carried uuids
were found stale on a given run.

This module re-resolves an address to the CURRENT uuid using two open,
undocumented JSON-XHR endpoints the SPA itself calls (no auth, no token, no
CAPTCHA):

  1. DETAIL  GET /cfl/property-inventory/property/{uuid}
        200 + JSON body  -> uuid is still LIVE (fast confirm, one round-trip)
        400 (validation) / 404 / non-JSON -> uuid is gone, fall through to (2)

  2. SEARCH  GET /cfl/property-inventory/search?bounds={sw_lat},{sw_lng},{ne_lat},{ne_lng}
        The same bbox feed the scraper already uses. We draw a TIGHT box
        around the listing's known geoPoint (or, lacking coords, the parent
        state bbox) and address-match the rows to recover the fresh uuid.

Matching is by normalized ``addressLine1`` + zip, with a ``reoId``/``mlsId``
corroboration when the stale listing carries one (those IDs survive uuid
rotation, so they're the strongest confirmation available). On a hit we rebuild
``source_url`` = ``https://homepath.fanniemae.com/property/{new_uuid}`` and
refresh ``case_number`` (``fannie-{uuid}``) so downstream dedupe/prune stay
consistent.

Compliant: open JSON-XHR only, presented with a real Chrome TLS fingerprint via
curl-cffi (same tier http_client uses for F5/Cloudflare-fronted hosts). No login,
no solver, no paid service.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Optional

import structlog

from .http_client import DEFAULT_HEADERS, _host_of, _throttle
from .models import Listing

log = structlog.get_logger()

BASE = "https://homepath.fanniemae.com"
SEARCH_API = f"{BASE}/cfl/property-inventory/search"
DETAIL_API = f"{BASE}/cfl/property-inventory/property"
PROPERTY_URL = f"{BASE}/property"  # public SPA URL: /property/{uuid}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE}/",
}

# Parent state bboxes (mirror the scraper's) used only when a listing has no
# geoPoint to draw a tight box around.
STATE_BBOXES = {
    "NC": (33.75, -84.50, 36.60, -75.30),
    "SC": (32.00, -83.40, 35.25, -78.50),
}

# Half-width (degrees) of the tight search box drawn around a known geoPoint.
# ~0.05 deg ~= 3.5 mi — big enough to survive minor geocode drift, small enough
# that the bbox returns << the 400-row cap so the target isn't truncated out.
_TIGHT_HALF_DEG = float(os.environ.get("HOMEPATH_TIGHT_HALF_DEG", "0.05"))

# A UUID as it appears in HomePath URLs (canonical 8-4-4-4-12 hex).
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _norm_addr(s: str | None) -> str:
    """Loose address key: lowercase, strip punctuation, collapse whitespace.

    Enough to match '1130 Pegram Crossing' across feed vs stored copies without
    depending on suffix expansion (HomePath keeps its own casing/punctuation)."""
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _uuid_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    m = _UUID_RE.search(url)
    return m.group(0) if m else None


async def _get_json(url: str, params: dict | None = None, timeout: float = 30.0) -> Optional[Any]:
    """GET JSON via the curl-cffi Chrome-fingerprint tier (impersonate='chrome').

    HomePath answers plain httpx too, but its edge occasionally 403s a bare
    client on TLS; the impersonation tier is the repo's standard robust path for
    these gov/agency JSON hosts. Honors the shared per-host throttle. Returns the
    parsed JSON, or None on any transport/parse failure or non-200.
    """
    from curl_cffi.requests import AsyncSession  # local import: keep dep optional

    h = dict(DEFAULT_HEADERS)
    h.update(HEADERS)
    proxy = os.environ.get("PROXY_URL") or None
    proxies = {"http": proxy, "https": proxy} if proxy else None

    await _throttle(_host_of(url))
    try:
        async with AsyncSession() as s:
            r = await s.get(
                url,
                params=params or {},
                headers=h,
                impersonate="chrome",
                timeout=timeout,
                proxies=proxies,
                allow_redirects=True,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("homepath_uuid.fetch_failed", url=url[:120], error=str(exc)[:160])
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return None


async def _uuid_is_live(uuid: str, *, timeout: float = 20.0) -> bool:
    """True if the detail endpoint still serves this uuid (fast one-shot confirm)."""
    if not uuid or not _UUID_RE.fullmatch(uuid):
        return False
    d = await _get_json(f"{DETAIL_API}/{uuid}", timeout=timeout)
    return bool(isinstance(d, dict) and d.get("propertyUuid"))


def _bbox_for(
    lat: float | None, lng: float | None, state: str | None
) -> Optional[tuple[float, float, float, float]]:
    """Tight box around a point, else the parent-state box, else None."""
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        h = _TIGHT_HALF_DEG
        return (lat - h, lng - h, lat + h, lng + h)
    if state and state.upper() in STATE_BBOXES:
        return STATE_BBOXES[state.upper()]
    return None


def _match_row(
    rows: list[dict],
    *,
    addr_key: str,
    zip_code: str | None,
    reo_id: str | None,
    mls_id: str | None,
) -> Optional[dict]:
    """Pick the feed row that is this property. reoId/mlsId (uuid-stable) win;
    otherwise normalized-address (+ zip when both sides have it)."""
    if reo_id or mls_id:
        for p in rows:
            if reo_id and (p.get("reoId") or "") == reo_id:
                return p
            if mls_id and str(p.get("mlsId") or "") == str(mls_id):
                return p
    if not addr_key:
        return None
    z = (zip_code or "").strip()[:5]
    addr_hits = [p for p in rows if _norm_addr(p.get("addressLine1")) == addr_key]
    if z:
        zc = [p for p in addr_hits if (p.get("zipCode") or "").strip()[:5] == z]
        if len(zc) == 1:
            return zc[0]
        if zc:
            addr_hits = zc
    if len(addr_hits) == 1:
        return addr_hits[0]
    return None


async def resolve_homepath_uuid(
    address: str,
    *,
    zip_code: str | None = None,
    state: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    reo_id: str | None = None,
    mls_id: str | None = None,
    timeout: float = 30.0,
) -> Optional[dict]:
    """Re-resolve a HomePath address to its CURRENT propertyUuid + fresh URL.

    Draws a tight bbox around (lat,lng) — or the state box as a fallback — hits
    the live search feed, and address/reoId-matches the result. Returns::

        {"property_uuid": str, "source_url": str, "row": <feed dict>}

    or None if the address isn't in current inventory (genuinely sold/withdrawn,
    or out of the NC/SC scope).
    """
    addr_key = _norm_addr(address)
    if not (addr_key or reo_id or mls_id):
        return None
    box = _bbox_for(lat, lng, state)
    if box is None:
        return None
    sw_lat, sw_lng, ne_lat, ne_lng = box
    data = await _get_json(
        SEARCH_API,
        params={"bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}"},
        timeout=timeout,
    )
    if not isinstance(data, dict):
        return None
    rows = data.get("properties") or []
    hit = _match_row(
        rows, addr_key=addr_key, zip_code=zip_code, reo_id=reo_id, mls_id=mls_id
    )
    if not hit:
        return None
    new_uuid = hit.get("propertyUuid")
    if not new_uuid:
        return None
    return {
        "property_uuid": new_uuid,
        "source_url": f"{PROPERTY_URL}/{new_uuid}",
        "row": hit,
    }


async def enrich_homepath_uuids(
    listings: list[Listing], *, verify_live: bool = True
) -> dict:
    """Re-resolve stale Fannie HomePath uuids in-place on carried-over leads.

    For every ``national.fannie_homepath`` listing whose stored uuid is stale
    (detail endpoint no longer serves it), look up the current uuid by address
    and rewrite ``source_url`` + ``case_number``. Fresh-run listings whose uuid
    is still live are left untouched.

    Returns stats: {checked, live, re_resolved, unresolved}.
    """
    targets = [
        li
        for li in listings
        if (li.source or "").endswith("fannie_homepath")
        and _uuid_from_url(li.source_url)
    ]
    if not targets:
        log.info("homepath_uuid.no_targets")
        return {"checked": 0, "live": 0, "re_resolved": 0, "unresolved": 0}

    log.info("homepath_uuid.start", target_count=len(targets))
    sem = asyncio.Semaphore(int(os.environ.get("HOMEPATH_UUID_CONCURRENCY", "6")))
    counts = {"checked": 0, "live": 0, "re_resolved": 0, "unresolved": 0}

    async def one(li: Listing) -> None:
        cur_uuid = _uuid_from_url(li.source_url)
        async with sem:
            counts["checked"] += 1
            # 1. Cheap live-confirm first — most carried uuids are still valid.
            if verify_live and cur_uuid and await _uuid_is_live(cur_uuid):
                counts["live"] += 1
                return
            # 2. Stale (or unverifiable) — re-resolve by address.
            raw = li.raw if isinstance(li.raw, dict) else {}
            res = await resolve_homepath_uuid(
                li.street_address or "",
                zip_code=li.zip_code,
                state=li.state,
                lat=li.latitude,
                lng=li.longitude,
                reo_id=raw.get("reo_id"),
                mls_id=raw.get("mls_id"),
            )
            if res and res["property_uuid"] != cur_uuid:
                li.source_url = res["source_url"]
                li.case_number = f"fannie-{res['property_uuid']}"
                counts["re_resolved"] += 1
            elif res and res["property_uuid"] == cur_uuid:
                # detail probe failed transiently but the uuid is in fact live.
                counts["live"] += 1
            else:
                counts["unresolved"] += 1

    await asyncio.gather(*(one(li) for li in targets))
    log.info("homepath_uuid.done", **counts)
    return counts
