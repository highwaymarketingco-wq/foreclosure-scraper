"""NC PTS Cloud LAND-RECORDS parcel resolver — parcel# -> situs address +
assessed value + owner + mailing address (FREE, unauthenticated JSON API).

The billing cluster (bcpwa.ncptscloud.com) hands us the delinquent roll (owner +
parcel + amount owed) but NO situs address. The sibling LAND-RECORDS PWA
(lrcpwa.ncptscloud.com) resolves any parcel number to its full record:

    POST /api/GetParcelDetailsByQueryParam
         header X-Tenant: <County>
         body   {"searchKey": "ParcelId", "searchValue": "<parcel number>"}
    -> { propertyAddress1, physicalAddress* (street#/name/type/city/state/zip),
         totalPropertyValue, primaryOwnerName, mailingAddress* , id, ... }

Live-verified 2026-07-01: parcel 10007200 (Henderson) -> "201 SUGARLOAF RD,
HENDERSONVILLE NC 28792", assessed $4,762,600, owner HENDERSONVILLE HOSPITALITY
LLC, mailing DULUTH GA (absentee). Tenants on this cluster: Henderson, Madison,
Rutherford, Burke (IsValidTenant=true; other NC counties false).

Fills street_address/city/state/zip_code + market_value (assessed) when blank,
and stashes owner + mailing (skip-trace / absentee signal) + the internal land-
record id in raw['lrcpwa']. Idempotent (skips leads that already have a street
address), budget-bounded, gated FORECLOSURE_LRCPWA=0.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Iterable, Optional

import httpx
import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger(__name__)

BASE = "https://lrcpwa.ncptscloud.com"
TENANTS = {"Henderson", "Madison", "Rutherford", "Burke"}   # NC land-records cluster
_ENABLED = os.environ.get("FORECLOSURE_LRCPWA") != "0"
_BUDGET_S = float(os.environ.get("LRCPWA_BUDGET_S", "900"))
_MAX = int(os.environ.get("LRCPWA_MAX", "6000"))
_CONC = int(os.environ.get("LRCPWA_CONCURRENCY", "8"))


def _county(li: Listing) -> Optional[str]:
    c = (li.county or "").replace(" County", "").strip().title()
    return c if c in TENANTS else None


def _money(v) -> Optional[float]:
    try:
        f = float(v)
        return f if 1000 <= f <= 50_000_000 else None
    except (TypeError, ValueError):
        return None


def _search_key(li: Listing) -> str:
    """The value this API's `ParcelId` search actually wants.

    Henderson/Madison/Rutherford leads reach the board already carrying the
    county ACCOUNT number, so parcel_id is the right key. Burke leads carry the
    10-digit map PIN instead, and lrcpwa answers a PIN with HTTP 500 — measured
    2026-08-03 over 26 Burke board leads, 0/26 resolved by PIN against 25/26 for
    the same parcels' REIDs, which is why this tenant has sat at 0.6% coverage
    while Henderson runs at 78%. nc_burke_spine stamps the REID onto
    raw['burke_spine'], so prefer it whenever the spine has run.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    spine = raw.get("burke_spine")
    reid = spine.get("reid") if isinstance(spine, dict) else None
    return str(reid).strip() if reid else (li.parcel_id or "").strip()


async def _lookup(http: httpx.AsyncClient, tenant: str, parcel: str) -> Optional[dict]:
    try:
        r = await http.post(
            f"{BASE}/api/GetParcelDetailsByQueryParam",
            headers={"X-Tenant": tenant, "Content-Type": "application/json",
                     "Accept": "application/json"},
            content=json.dumps({"searchKey": "ParcelId", "searchValue": parcel}),
        )
    except Exception:
        return None
    if r.status_code != 200 or not r.text.strip() or r.text.strip() in ("null", "[]"):
        return None
    try:
        j = r.json()
    except Exception:
        return None
    return (j[0] if isinstance(j, list) and j else j) if isinstance(j, (list, dict)) else None


def _is_placeholder_addr(addr: str) -> bool:
    a = addr.upper()
    return ("NO ADDRESS" in a or "NOT ASSIGNED" in a or a in ("0", "", "TBD")
            or a.startswith("0 NO ") or "NO SITUS" in a)


def _apply(li: Listing, rec: dict) -> bool:
    filled = False
    addr = (rec.get("propertyAddress1") or rec.get("locationAddress")
            or rec.get("formattedPhysicalAddress") or "").strip()
    if _is_placeholder_addr(addr):
        addr = ""   # vacant/unaddressed parcel — keep value/owner, but not a fake street
    if addr and not (li.street_address or "").strip():
        li.street_address = addr
        filled = True
    if not (li.city or "").strip() and (rec.get("physicalAddressCity") or rec.get("city")):
        li.city = str(rec.get("physicalAddressCity") or rec.get("city")).strip().title()
    if not (li.state or "").strip():
        li.state = (rec.get("physicalAddressState") or "NC").strip()
    z = str(rec.get("physicalAddressZip") or "").strip()[:5]
    if z and not (li.zip_code or "").strip():
        li.zip_code = z
    mv = _money(rec.get("totalPropertyValue")) or _money(rec.get("costTotalValue"))
    if mv and not li.market_value:
        li.market_value = mv
        filled = True
    owner = (rec.get("primaryOwnerName") or "").strip()
    if owner and not (li.owner_name or "").strip():
        li.owner_name = owner
    if not isinstance(li.raw, dict):
        li.raw = {}
    mail_state = (rec.get("mailingAddressState") or "").strip().upper()
    li.raw["lrcpwa"] = {
        "id": rec.get("id"),
        "reid": rec.get("reid") or rec.get("parcelId"),
        "assessed_value": mv,
        "owner": owner or None,
        "mailing": {
            "addr": (rec.get("mailingAddress1") or "").strip() or None,
            "city": (rec.get("mailingAddressCity") or "").strip() or None,
            "state": mail_state or None,
            "zip": (rec.get("mailingAddressZip") or "").strip() or None,
        },
        # absentee = owner mails somewhere other than the property's state
        "absentee": bool(mail_state and mail_state != "NC"),
    }
    return filled


async def enrich_lrcpwa_parcel(listings: Iterable[Listing]) -> dict:
    stats = {"targets": 0, "resolved": 0, "address_filled": 0, "value_filled": 0,
             "absentee": 0, "skipped_budget": 0}
    if not _ENABLED:
        return stats
    targets = [li for li in listings
               if _county(li) and (li.parcel_id or "").strip()
               and not (li.street_address or "").strip()]
    stats["targets"] = len(targets)
    if not targets:
        return stats

    start = time.monotonic()
    sem = asyncio.Semaphore(_CONC)
    async with client(timeout=25.0) as http:
        async def one(li: Listing):
            if (time.monotonic() - start) > _BUDGET_S:
                stats["skipped_budget"] += 1
                return
            async with sem:
                rec = await _lookup(http, _county(li), _search_key(li))
            if not rec:
                return
            had_addr = bool((li.street_address or "").strip())
            had_val = bool(li.market_value)
            if _apply(li, rec):
                stats["resolved"] += 1
            if (li.street_address or "").strip() and not had_addr:
                stats["address_filled"] += 1
            if li.market_value and not had_val:
                stats["value_filled"] += 1
            if (li.raw.get("lrcpwa") or {}).get("absentee"):
                stats["absentee"] += 1

        # cap total for safety
        await asyncio.gather(*(one(li) for li in targets[:_MAX]))
    log.info("lrcpwa.done", **stats)
    return stats
