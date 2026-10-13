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
VERSION = "avalon_v3"
TTL_DAYS = 90
SOURCE = "d1ebsyxxbc7tep.cloudfront.net (Wildfire/Avalon)"
GOVERNS: tuple[str, ...] = ("tax_lien", "tax_sale")
WALL = False
#: the ledger is public; a delinquent-tax owner's name is theirs to redact, not publish
#: (found 2026-10-13: 547 real Rutherford owner names had leaked into the committed, public
#: tax_lien ledger because this verifier never set this -- every other tax_lien verifier does)
ROW_SUMMARY_EXCLUDE = ("owner_name",)
# `unconfirmed` reasons that are about the SOURCE being unreachable, not about the row: re-asked
# after hours (registry.Verifier.is_transient), not after the 7-day retry.
TRANSIENT_REASONS = ("fetch_failed", "source_refusing")

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


# --- failure handling (added 2026-10-13) --------------------------------------------------
# A first bulk run verified ~3,400 Rutherford parcels in 22 minutes. The first ~590 were real
# (93% confirmed). At ~12:00Z CloudFront began answering HTTP 403 to every request, and the
# original code turned every failed request into verdict "stale" -- 2,840 consecutive false
# "this bill was paid" verdicts, which core.py says REMOVE the row's scorer signals for the
# verdict's whole TTL. Two independent bugs fed that: (1) a non-200 / exception / bad JSON made
# _fetch_unpaid return an empty list, indistinguishable from "zero unpaid bills"; (2) the
# "parcel not found" branch built a verdict ("not_found") that is not in core.VERDICTS, raised
# ValueError inside a bare `except: pass`, and fell through to "stale".
#
# Rule now: "stale" needs POSITIVE evidence -- a clean 200 that says zero unpaid bills AND a
# clean 200 unfiltered lookup that returns this exact ParcelNumber. Anything else the source
# could not decide is "unconfirmed" (core.py: "says nothing about the claim", changes no score).
_MAX_FAIL_STREAK = 5          # consecutive failed requests before backing off
_COOLDOWN_S = 900.0           # stop hitting a source that is refusing us for this long
_PAUSE_S = 0.4                # politeness gap between requests (the first run had none)
_fail_streak = 0
_blocked_until = 0.0


def _breaker_open() -> bool:
    return time.monotonic() < _blocked_until


def _note(ok: bool) -> None:
    global _fail_streak, _blocked_until
    if ok:
        _fail_streak = 0
        return
    _fail_streak += 1
    if _fail_streak >= _MAX_FAIL_STREAK:
        _blocked_until = time.monotonic() + _COOLDOWN_S
        _fail_streak = 0


def _norm(v: Any) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def _post(body: dict, token: str = "") -> tuple[Optional[dict], Optional[int], str]:
    """One POST. Returns (parsed JSON or None, HTTP status or None, failure reason or "").
    Only a clean 200 with parseable JSON counts as an answer."""
    headers = dict(_HEADERS)
    if token:
        headers["SearchToken"] = token
    time.sleep(_PAUSE_S)
    try:
        r = requests.post(_AVALON_URL, json=body, headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001
        _note(False)
        return None, None, f"request error: {type(exc).__name__}"
    if r.status_code != 200:
        _note(False)
        return None, r.status_code, f"HTTP {r.status_code}"
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        _note(False)
        return None, 200, "unparseable response"
    if not isinstance(data, dict):
        _note(False)
        return None, 200, "unexpected response shape"
    _note(True)
    return data, 200, ""


def _fetch_unpaid(parcel_id: str) -> tuple[list[dict], int, bool, str]:
    """Unpaid-facet search for one parcel, following the SearchToken scroll cursor.

    Returns (records, total, ok, why). ok is True ONLY when every request in the scroll was a
    clean answer -- an empty list with ok=False means "could not ask", never "zero bills"."""
    all_records: list[dict] = []
    token = ""
    skip = 0
    total = 0
    retried_401 = False

    while True:
        body = {
            "value": parcel_id,
            "skip": skip,
            "facets": {"Status": {"Unpaid": True}},
            "direct": False,
        }
        data, status, why = _post(body, token)
        if data is None:
            if status == 401 and token and not retried_401:
                # scroll token expired: restart the scroll once, fresh
                retried_401 = True
                token, skip = "", 0
                all_records.clear()
                continue
            return all_records, total, False, why

        records = data.get("Records") or []
        total = data.get("TotalRecords", 0) or 0
        token = data.get("SearchToken", "") or token

        if not records:
            break
        all_records.extend(records)
        if len(all_records) >= total or len(records) < 20:
            break
        skip += len(records)

    return all_records, total, True, ""


def _unconfirmed(reason: str, detail: str = "", **extra: Any) -> VerificationResult:
    """`reason` is a machine token (see TRANSIENT_REASONS); `detail` is the human explanation."""
    ev = {"reason": reason, "checked_url": _AVALON_URL}
    if detail:
        ev["detail"] = detail
    ev.update(extra)
    return result(SIGNAL, "unconfirmed", ev, source=SOURCE, version=VERSION, verifier="avalon_tax")


async def verify(row: dict, client=None) -> VerificationResult:
    parcel_id = str(row.get("parcel_id") or "").strip()
    addr = str(row.get("street_address") or "").strip()

    if not parcel_id and not addr:
        return _unconfirmed("no_row_identity", "row has no parcel_id and no street address")

    if _breaker_open():
        return _unconfirmed("source_refusing", "source is refusing requests; backing off, not queried "
                            "(NOT evidence of payment)")

    # Avalon matches on ParcelNumber / BillKey; fall back to the street address only to FIND
    # unpaid bills, never to prove one was paid.
    search_value = parcel_id or addr
    records, total, ok, why = _fetch_unpaid(search_value)

    if not ok:
        return _unconfirmed("fetch_failed", f"{why}; NOT evidence of payment", parcel_id=parcel_id)

    if total == 0 and not records:
        # A clean "zero unpaid" answer. That alone is not proof the bill was paid: the parcel
        # may simply not be what we searched. Require the parcel to exist, by exact ParcelNumber.
        if not parcel_id:
            return _unconfirmed("no_parcel_id", "a street-address text search cannot prove payment",
                                address=addr)
        data, status, why = _post({"value": parcel_id, "skip": 0, "facets": {}, "direct": True})
        if data is None:
            return _unconfirmed("fetch_failed", f"existence check failed ({why}); NOT evidence of payment",
                                parcel_id=parcel_id)
        match = [r for r in (data.get("Records") or [])
                 if _norm(r.get("ParcelNumber")) == _norm(parcel_id)]
        if not match:
            return _unconfirmed("parcel_not_found", "no exact ParcelNumber match in live tax data",
                                parcel_id=parcel_id)
        years = sorted({str(r.get("BillYear")) for r in match if r.get("BillYear")})
        return result(SIGNAL, "stale", {
            "reason": "parcel exists (exact ParcelNumber match) and has no unpaid/delinquent bills",
            "parcel_id": parcel_id, "checked_url": _AVALON_URL,
            "unpaid_total": 0, "bills_seen_years": years,
        }, source=SOURCE, version=VERSION, verifier="avalon_tax")

    # Unpaid records exist. Aggregate across years.
    total_owed = 0.0
    delinquent_years: list[str] = []
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
    if not confirmed:
        # Unpaid-facet records came back but carried no amount/year/flag: undecidable, not "paid".
        return _unconfirmed("unpaid_records_undecidable",
                            "unpaid records returned but with no amount, year or flag",
                            parcel_id=parcel_id, unpaid_record_count=total)
    return result(SIGNAL, "confirmed", detail, source=SOURCE, version=VERSION, verifier="avalon_tax")
