"""Alamance County NC delinquent-tax search -- a DIFFERENT Spatialest tenant from the
assessor card already built (assessor_cards/alamance_nc.py's own docstring explicitly says
"Alamance's real delinquent-tax source is a different, not-yet-identified host" -- this module
is that host, found 2026-10-28).

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-28.csv). NC Alamance multi_year_delinquent_tax/
tax_aging_surfaced/two_year_delinquent (2,858 applicable each) all show sourced-not-built, source
"tax/property card: property.spatialest.com" -- the WRONG Spatialest tenant (that's the assessor
card's own host, "/nc/alamance", confirmed dead end there). The real tax-collector tenant is a
SEPARATE slug, "/nc/alamance-tax" (linked from the county's own site, alamancecountync.gov's
property_records/tax pages), running an OLDER jQuery/PHP Spatialest build (not the newer
Laravel SPA the assessor card talks to) with its own simple AJAX endpoint.

THE FLOW (live-verified 2026-10-28, real board owners):
    POST https://property.spatialest.com/nc/alamance-tax/data/getData.php
         qtype=search_results&search=<owner text>
    -> {"count": N, "results": [{"TaxYear": 2026, "Account": "...", "PARID": 106711 or null,
        "OwnerName": "...", "AssetDescription": "<situs, sometimes with house number, sometimes
        without on older years>", "BalanceDue": "0.00", "DatePaid": "...", "Status":
        "OPEN"|"PARTIALLY PAID"|"PAID IN FULL", "PropertyType": "R" (real estate) or "search?"
        (personal property, isPersonal=1, PARID always null -- these are vehicles/boats, not
        this board's signal and always skipped), ...}, ...]}
No CSRF token, no cookies, no login -- a bare POST answers directly.

MATCH METHOD. Searching the row's FULL owner_name text (not just the surname) narrows results
enough to confirm by address directly -- live-verified "OAKLEY TAYLOR" (vs a bare "OAKLEY",
250 results across unrelated Oakleys) returns 5 rows across 3 real PARIDs, one of which
("OAKLEY TAYLOR W/OAKLEY RAGAN R", PARID 141475, "2959 MINE CREEK RD") is an EXACT
address_relation() match to this board row's own street_address ("2959 Mine Creek Road") --
confirmed via a real board row, not invented. The board's own parcel_id does NOT match this
vendor's PARID at all (GHS Properties: board parcel_id "8844451684" vs this vendor's PARID
"106711" for the exact same parcel, confirmed live) -- the same per-vendor-ID-format trap this
project already documents for ustaxdata/BT TaxPayer Portal, so this is name+address match only,
never a parcel_id lookup (tried live, always returns 0 rows).

Once ONE row for a PARID address_relation()-matches, every OTHER row sharing that SAME PARID is
trusted (the vendor's own grouping, not a second guess) -- this is how the full multi-year
history is recovered even though older years' AssetDescription often drops the house number
("COTTONWOOD DR" with no "6815") and would not confirm on its own.

Writes raw['alamance_tax_bills'] = {bills, years_unpaid, balance, taxpayer_of_record,
assessed_value, source_url} -- same shape enrichment_ustaxdata_tax_search.py already uses, so
enrichment_tax_owed.py's existing generic Pass B (gated on `_TAXISH` substring match in the
block name, "tax" qualifies) picks up tax_owed/tax_aging_surfaced with no new wiring there.
multi_year_delinquent_tax/two_year_delinquent are each their own literal raw key (gap_matrix.py
reads them as an exact presence check) and need their own restatement, built() below.

Bounded, opt-in, free, public JSON endpoint, no login, no CAPTCHA. Gate off entirely with
FORECLOSURE_ALAMANCE_TAX=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .http_client import client
from .models import Listing
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend
from .verification.core import address_relation

log = structlog.get_logger()

BASE = "https://property.spatialest.com/nc/alamance-tax"
SEARCH_URL = f"{BASE}/data/getData.php"
COUNTY = "Alamance"

RAW_KEY = "alamance_tax_bills"
MYDT_KEY = "multi_year_delinquent_tax"
TWO_YEAR_KEY = "two_year_delinquent"
MIN_YEARS = 2
_PAID_STATUS = "paid in full"

MAX_LISTINGS = int(os.getenv("ALAMANCE_TAX_MAX", "300"))
_CONCURRENCY = int(os.getenv("ALAMANCE_TAX_CONCURRENCY", "4"))

ENABLED = os.environ.get("FORECLOSURE_ALAMANCE_TAX") != "0"


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == COUNTY.lower()
        and (li.owner_name or "").strip() and not _already_done(raw)
    )


def _money(v: Any) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _search_term(owner_name: str) -> str:
    """The row's own owner_name, cut at the first co-owner joiner ("&"/"/") -- live-
    verified the vendor's search silently returns 0 rows for a term containing "&" at all
    (confirmed on a real board row, "OAKLEY TAYLOR & RAGAN OAKLEY" -> 0, "OAKLEY TAYLOR" alone
    -> the correct confirmed match), while a single owner's own name is enough to confirm by
    address anyway."""
    return re.split(r"\s*[&/]\s*", owner_name, maxsplit=1)[0].strip()


async def _search(c, term: str) -> list[dict]:
    try:
        r = await c.post(SEARCH_URL, data={"qtype": "search_results", "search": term})
        r.raise_for_status()
        data = r.json()
    except Exception:  # noqa: BLE001
        return []
    return [row for row in (data.get("results") or []) if isinstance(row, dict)]


def _confirm_parid(rows: list[dict], street_address: Optional[str]) -> Optional[Any]:
    """The one PARID whose own AssetDescription address_relation()-matches the row's
    street_address -- never \"closest\" or \"only result\"."""
    if not street_address:
        return None
    for row in rows:
        if row.get("PropertyType") != "R" or row.get("PARID") is None:
            continue
        if address_relation(row.get("AssetDescription"), street_address) == "match":
            return row["PARID"]
    return None


def build_block(bills: list[dict]) -> dict[str, Any]:
    """Pure: the raw[RAW_KEY] block from one parcel's full bill list (one dict per TaxYear,
    already filtered to a single confirmed PARID)."""
    years_unpaid = sorted({b["year"] for b in bills if b.get("status") != _PAID_STATUS})
    unpaid_total = round(sum(b["balance"] for b in bills
                             if b.get("status") != _PAID_STATUS and b.get("balance")), 2) or None
    latest = max(bills, key=lambda b: b["year"]) if bills else {}
    block: dict[str, Any] = {
        "bills": bills,
        "years_unpaid": years_unpaid,
        "taxpayer_of_record": latest.get("owner_name"),
        "assessed_value": latest.get("taxable_value"),
        "source_url": SEARCH_URL,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if unpaid_total:
        block["balance"] = unpaid_total
        block["total_due"] = unpaid_total
    return block


def build_mydt_block(bills: list[dict], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw[MYDT_KEY] block, status-based (not amount-based -- a confirmed-unpaid bill
    with no resolved balance must still count, same reasoning as the ustaxdata sibling)."""
    today = today or date.today()
    per_year: dict[int, Optional[float]] = {
        b["year"]: b.get("balance") for b in bills if b.get("status") != _PAID_STATUS}
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, "NC", COUNTY, today)]
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    known = [per_year[y] for y in years if per_year[y]]
    return {
        "years": years,
        "per_year": {str(y): per_year[y] for y in years},
        "years_delinquent": len(matured),
        "unpaid_bill_years": len(years),
        "matured_years": matured,
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": round(sum(known), 2) if known else None,
        "amount_known": bool(known),
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "amount_basis": "annual_bill",
        "source": "enrichment_alamance_tax_search",
    }


def build_two_year_block(bills: list[dict], *, today: Optional[date] = None) -> dict:
    """Pure: unconditional real answer, same convention every sibling restatement uses."""
    today = today or date.today()
    unpaid_years = sorted({b["year"] for b in bills if b.get("status") != _PAID_STATUS})
    matured = tax_calendar.completed_delinquent_years(unpaid_years, "NC", COUNTY, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": "enrichment_alamance_tax_search",
    }


async def enrich_alamance_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search Alamance NC rows by owner name, confirm a PARID by address, and stamp
    raw['alamance_tax_bills'] + raw['multi_year_delinquent_tax'] + raw['two_year_delinquent']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_ALAMANCE_TAX=0)"}
    targets = [li for li in listings if _eligible(li)][:MAX_LISTINGS]
    stats = {"eligible": len(targets), "searched": 0, "no_match": 0, "confirmed": 0,
             "mydt_qualified": 0, "errors": 0}
    if not targets:
        return stats
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(li: Listing) -> None:
        async with sem:
            try:
                rows = await _search(c, _search_term(li.owner_name))
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                return
            stats["searched"] += 1
            await asyncio.sleep(0.3)
        parid = _confirm_parid(rows, li.street_address)
        if parid is None:
            stats["no_match"] += 1
            return
        stats["confirmed"] += 1
        bills = []
        for row in rows:
            if row.get("PARID") != parid:
                continue
            year = row.get("TaxYear")
            if not isinstance(year, int):
                continue
            bills.append({
                "year": year,
                "status": str(row.get("Status") or "").strip().lower(),
                "balance": _money(row.get("BalanceDue")),
                "owner_name": row.get("OwnerName"),
                "taxable_value": _money(row.get("TaxableValue")),
                "account": row.get("Account"),
                "situs": row.get("AssetDescription"),
            })
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[RAW_KEY] = build_block(bills)
        mydt = build_mydt_block(bills)
        if mydt:
            li.raw[MYDT_KEY] = mydt
            stats["mydt_qualified"] += 1
        li.raw[TWO_YEAR_KEY] = build_two_year_block(bills)

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(li) for li in targets))
    log.info("alamance_tax.done", **stats)
    return stats
