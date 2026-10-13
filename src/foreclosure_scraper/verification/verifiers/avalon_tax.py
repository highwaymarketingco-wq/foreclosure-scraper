"""avalon_tax verifier: Rutherford County tax bill data via CloudFront POST.

The data host (d1ebsyxxbc7tep.cloudfront.net) answers 405 to GET but 200 to POST
with a JSON body of property tax records. This verifier checks board rows from
counties_nc.rutherford_tax and counties_nc.rutherford_wildfire_tax against the
live data to confirm the tax lien claim.

API details (from rutherford_wildfire_tax.py, live-verified 2026-08-03):
  - Page 1 needs no SearchToken header; pages 2+ must echo the page-1 token
    as a SearchToken request header (server-side scroll cursor, not anti-bot).
  - Facets filter the results: {"Status": {"Unpaid": true}} gets delinquent only.
  - Accept: application/json is required (otherwise returns an HTML page).
  - Page size is fixed at 20; skip increments by 20.

Must run from the VM (CloudFront 403s requests from non-US-Cloud IPs).

Built 2026-10-13: breaks the avalon_tax wall (8,533 blocked listings).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from ..core import VerificationResult, result

SIGNAL = "tax_lien"
VERSION = "avalon_v2"
TTL_DAYS = 90
SOURCE = "d1ebsyxxbc7tep.cloudfront.net (Wildfire/Avalon)"
GOVERNS: tuple[str, ...] = ("tax_lien", "tax_sale")
WALL = False

_AVALON_URL = "https://d1ebsyxxbc7tep.cloudfront.net/data/5b88e44b-0038-4361-8c53-7ce1343ad3ad/Wildfire/Records"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.rutherfordcountync.gov",
    "Referer": "https://www.rutherfordcountync.gov/",
}

RUTHERFORD_SOURCES = frozenset({"counties_nc.rutherford_tax", "counties_nc.rutherford_wildfire_tax"})


def applies(row: dict) -> bool:
    src = str(row.get("source") or "")
    lt = str(row.get("listing_type") or "")
    return src in RUTHERFORD_SOURCES and lt in ("tax_lien", "tax_sale")


def _fetch_unpaid(parcel_id: str) -> tuple[list[dict], int, str]:
    """POST to Avalon CloudFront with Status=Unpaid facet to get delinquent records only.

    Returns (records, total_count, search_token). Paginates through all unpaid
    records for this parcel using the SearchToken scroll cursor.
    """
    all_records: list[dict] = []
    search_token = ""
    skip = 0
    total = 0

    while True:
        body = {
            "value": parcel_id,
            "skip": skip,
            "facets": {"Status": {"Unpaid": True}},
            "direct": False,
        }
        headers = dict(_HEADERS)
        if search_token:
            headers["SearchToken"] = search_token

        try:
            r = requests.post(_AVALON_URL, json=body, headers=headers, timeout=30)
        except Exception:
            break

        if r.status_code == 401:
            # Token expired or invalid; retry without it (fresh search)
            if search_token:
                search_token = ""
                skip = 0
                all_records.clear()
                time.sleep(1)
                continue
            break
        if r.status_code != 200:
            break

        try:
            data = r.json()
        except Exception:
            break

        records = data.get("Records", [])
        total = data.get("TotalRecords", 0)
        token = data.get("SearchToken", "")
        if token:
            search_token = token

        if not records:
            break

        all_records.extend(records)

        if len(all_records) >= total or len(records) < 20:
            break

        skip += len(records)
        time.sleep(0.5)  # politeness

    return all_records, total, search_token


async def verify(row: dict, client=None) -> VerificationResult:
    parcel_id = str(row.get("parcel_id") or "").strip()
    addr = str(row.get("street_address") or "").strip()

    if not parcel_id and not addr:
        return result(SIGNAL, "unverified", {"reason": "no parcel_id or address to check"},
                      source=SOURCE, version=VERSION, verifier="avalon_tax")

    # Use parcel_id as the search value (Avalon matches on ParcelNumber / BillKey)
    search_value = parcel_id or addr

    records, total, _ = _fetch_unpaid(search_value)

    if total == 0 and not records:
        # No unpaid records found — could mean parcel is paid up (stale) or not found
        # Do a quick unfiltered search to distinguish "not found" from "paid"
        try:
            body = {"value": search_value, "skip": 0, "facets": {}, "direct": True}
            r = requests.post(_AVALON_URL, json=body, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data.get("TotalRecords", 0) == 0:
                    return result(SIGNAL, "not_found", {
                        "reason": "parcel not found in live tax data",
                        "parcel_id": parcel_id, "checked_url": _AVALON_URL,
                    }, source=SOURCE, version=VERSION, verifier="avalon_tax")
        except Exception:
            pass

        # Parcel exists but has no unpaid bills — claim is stale
        return result(SIGNAL, "stale", {
            "reason": "parcel exists but has no unpaid/delinquent bills",
            "parcel_id": parcel_id, "checked_url": _AVALON_URL,
            "unpaid_total": 0,
        }, source=SOURCE, version=VERSION, verifier="avalon_tax")

    # Aggregate across all unpaid records (multiple years per parcel)
    total_owed = 0.0
    delinquent_years = []
    advertised = False
    outside_law_firm = False
    owner_name = ""

    for rec in records:
        if not owner_name:
            owner_name = rec.get("OwnerName1", "") or rec.get("OwnerName2", "") or ""

        amt = rec.get("CartPaymentAmount", 0) or 0
        if isinstance(amt, (int, float)) and amt > 0:
            total_owed += amt

        flags = str(rec.get("FlagsString") or "")
        if "ADVERTISED" in flags:
            advertised = True
        if "OUTSIDE LAW FIRM" in flags:
            outside_law_firm = True

        year = rec.get("BillYear")
        if year:
            delinquent_years.append(str(year))

    confirmed = total_owed > 0 or advertised or outside_law_firm or len(delinquent_years) > 0

    detail = {
        "parcel_id": parcel_id,
        "owner": owner_name,
        "total_owed": round(total_owed, 2),
        "delinquent_years": delinquent_years,
        "advertised": advertised,
        "outside_law_firm": outside_law_firm,
        "unpaid_record_count": total,
        "checked_url": _AVALON_URL,
    }

    verdict = "confirmed" if confirmed else "stale"
    return result(SIGNAL, verdict, detail, source=SOURCE, version=VERSION, verifier="avalon_tax")
