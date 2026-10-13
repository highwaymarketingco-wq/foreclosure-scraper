"""avalon_tax verifier: Rutherford County tax bill data via CloudFront POST.

The data host (d1ebsyxxbc7tep.cloudfront.net) answers 405 to GET but 200 to POST
with a JSON body of property tax records. This verifier checks board rows from
counties_nc.rutherford_tax and counties_nc.rutherford_wildfire_tax against the
live data to confirm the tax lien claim.

Built 2026-10-13: breaks the avalon_tax wall (8,533 blocked listings).
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from ..core import VerificationResult, result

SIGNAL = "tax_lien"
VERSION = "avalon_v1"
TTL_DAYS = 90
SOURCE = "d1ebsyxxbc7tep.cloudfront.net (Wildfire/Avalon)"
GOVERNS: tuple[str, ...] = ("tax_lien", "tax_sale")
WALL = False

_AVALON_URL = "https://d1ebsyxxbc7tep.cloudfront.net/data/5b88e44b-0038-4361-8c53-7ce1343ad3ad/Wildfire/Records"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
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


def _fetch_records(parcel_id: str = "", address: str = "", limit: int = 20) -> tuple[list[dict], int]:
    """POST to Avalon CloudFront and return matching records + total count."""
    try:
        search_value = parcel_id or address
        body = {"value": search_value, "skip": 0, "facets": {}, "direct": False}
        r = requests.post(_AVALON_URL, json=body, headers=_HEADERS, timeout=30)
        if r.status_code != 200:
            return [], 0
        data = r.json()
        return data.get("Records", []), data.get("TotalRecords", 0)
    except Exception:
        return [], 0


async def verify(row: dict, client=None) -> VerificationResult:
    parcel_id = str(row.get("parcel_id") or "").strip()
    addr = str(row.get("street_address") or "").strip()

    if not parcel_id and not addr:
        return result(SIGNAL, "unverified", {"reason": "no parcel_id or address to check"},
                      source=SOURCE, version=VERSION, verifier="avalon_tax")

    records, total = _fetch_records(parcel_id, addr, limit=20)

    if not records:
        return result(SIGNAL, "not_found", {
            "reason": "parcel/address not found in live tax data",
            "parcel_id": parcel_id, "checked_url": _AVALON_URL,
        }, source=SOURCE, version=VERSION, verifier="avalon_tax")

    # Aggregate across all returned records (multiple years per parcel)
    total_owed = 0.0
    delinquent_years = []
    advertised = False
    outside_law_firm = False
    owner_name = ""

    for rec in records:
        # Owner
        if not owner_name:
            owner_name = rec.get("OwnerName1", "") or rec.get("OwnerName2", "") or ""

        # Amount due
        amt = rec.get("CartPaymentAmount", 0) or 0
        if isinstance(amt, (int, float)) and amt > 0:
            # Only count if unpaid
            if rec.get("isDelinquent"):
                total_owed += amt

        # Flags
        flags = str(rec.get("FlagsString") or "")
        if "ADVERTISED" in flags:
            advertised = True
        if "OUTSIDE LAW FIRM" in flags:
            outside_law_firm = True
        if rec.get("isDelinquent"):
            year = rec.get("BillYear")
            if year:
                delinquent_years.append(str(year))

    # Confirmed if any delinquent amount, advertised, or outside law firm
    confirmed = total_owed > 0 or advertised or outside_law_firm or len(delinquent_years) > 0

    detail = {
        "parcel_id": parcel_id,
        "owner": owner_name,
        "total_owed": round(total_owed, 2),
        "delinquent_years": delinquent_years,
        "advertised": advertised,
        "outside_law_firm": outside_law_firm,
        "total_records": total,
        "checked_url": _AVALON_URL,
    }

    verdict = "confirmed" if confirmed else "not_found"
    return result(SIGNAL, verdict, detail, source=SOURCE, version=VERSION, verifier="avalon_tax")
