"""Davidson County NC taxsearch.co.davidson.nc.us (BT/ItsPublic TaxBillSearch, OwnerName search)
ViewTaxBill "Deferred Value" field -> the shared raw['rollback_exposure'] contract
enrichment_rollback_deferral.py established and gap_matrix.py's own checked_columns()/
positive_columns() already read.

WHY THIS EXISTS (round 18 of the tax-cluster gap_matrix sweep, 2026-11-17 -- the single biggest
remaining "no source known" rollback_exposure cell, 5,469 rows). Round 17's own note (this
project's memory, project_tax_cluster_round17_2026-11-16.md) found verification/verifiers/
tax_lien_itspublic.py's own PORTALS['Davidson'] entry already live-proves an owner-name search
works on this portal ("own ParcelNumber/AccountNumber/roll-parcel fields all answer zero...
name_search routes every search to OwnerLastName/OwnerFirstName instead") -- but that is the
VERIFIER side only (it confirms an EXISTING tax_lien lead's balance); no PRODUCER existed to
actually READ a rollback/present-use-deferral signal off this portal. Round 17 flagged this as
"next round's concrete, de-risked build target: adapt the verifier's own already-proven
owner-name call shape into a new producer path."

LIVE-CONFIRMED 2026-11-17 (this round, before writing a line of this module). The grid search
itself (GetSearchTablePartial/GetSearchTableData) only ever returns the same 8 fields the
verifier's own parse_rows() already maps (year/bill/owner/description/original/balance/action)
-- no levy-type/description field distinct from the parcel's own acreage/address text, same
vendor-wide limitation this project's declined_registry.json already has HIGH-confidence entries
for across Anson/Yadkin/Caswell/Jones/Graham/Granville/Carteret/Moore/Vance (all the SAME BT
TaxPayer Portal/ItsPublic vendor family). The ROLLBACK SIGNAL is NOT in the grid -- it is one
level deeper, on the per-bill ViewTaxBill DETAIL page (the same page the verifier's own
parse_view() already reads for "Current Balance"/"Last Payment Date"), which carries a
"Deferred Value" line sibling to "Parcel Value Total"/"Taxable Value"
(Taxable Value = Parcel Value Total - Deferred Value, confirmed arithmetically on every sampled
bill). Live-sampled 109 real-property bills with 5+ acres (the shape most likely enrolled in
present-use value -- rural/farm tracts, not subdivision lots): the field is a REAL, live signal,
not a decorative always-0 placeholder. 6 of them carry a nonzero Deferred Value, e.g.:
    parcel 0100900000046 (47.12 AC, HAMMER): Deferred Value $325,610 of $342,800 Parcel Value
        Total (Taxable Value $17,190 = $342,800 - $325,610, exact)
    parcel 0703600000023 (44.97 AC, HEDRICK): Deferred Value $138,100 of $202,990
    parcel 0702800000006 (44.70 AC, HEDRICK): Deferred Value $151,960 of $211,430
    parcel 0100900000010 (115.58 AC, WILLARD): Deferred Value $390,240 of $505,820
while every <1-AC suburban/subdivision lot sampled (FRIEDBERG VILLAGE, LAKE TERRACE, E CENTER
ST, FERNDALE DR) read $0 -- consistent with present-use value being an agricultural/
horticultural/forestry-zoned-land program, not a townhouse-lot one. This is NOT the same vendor
limitation already declined for the bttaxpayerportal.com-hosted counties above: Davidson's own
deployment (a DIFFERENT host, taxsearch.co.davidson.nc.us, confirmed a separate ItsPublic
instance by the verifier's own module docstring) exposes this extra ViewTaxBill field; whether
the SAME field exists on the other counties' ViewTaxBill pages was not re-checked this round
(their own declines were based on the grid only, same as this investigation started from, so
they may be worth a second look later -- flagged, not re-opened here, scope discipline).

WHAT THIS MODULE DOES. Reuses verification/verifiers/tax_lien_itspublic.py's own, already-tested
pure helpers (PORTALS['Davidson'], search_model(), _headers(), parse_rows(), parse_view()) --
nothing here reimplements that parsing, same reuse discipline as every sibling rollback module
(enrichment_johnston_rollback_exposure.py etc. reuse enrichment_bt_parcel_info.py's own pure
helpers rather than re-deriving them). Searches Davidson's OwnerName endpoint (the ONLY field
confirmed live for this portal -- ParcelNumber/AccountNumber are confirmed dead, per the
verifier's own PORTALS comment), confirms the best-matching bill by comparing its own situs
(parse_description(), already embedded in parse_rows()'s own output) against the row's
street_address (never bind on owner name alone -- the same discipline as every sibling), fetches
that confirmed bill's ViewTaxBill detail page, and restates a positive "Deferred Value" into
raw['rollback_exposure'] -- never invented, same build_block() gate as every sibling.

RATE: not derived here. Davidson is NOT one of nc_its_public_tax.py's own dedicated PORTALS
counties (that scraper's roll never reads Davidson), so there is no raw['nc_its_public_tax']
bill-history block on these rows to derive an effective tax rate from -- deferred_value/basis/
source/parcel_value_total only, no annual/estimated_rollback figure, the same honest omission
every sibling makes when its own rate source is absent (see enrichment_johnston_rollback_
exposure.py's own module docstring, "RATE, NEVER ASSUMED").

Bounded, opt-in, free, public, no login, no CAPTCHA (same vendor family already read by
nc_its_public_tax.py and tax_lien_itspublic.py). Gate off entirely with
FORECLOSURE_DAVIDSON_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing
from .name_normalize import is_entity
from .verification.verifiers.tax_lien_itspublic import (
    PORTALS, _headers, parse_rows, parse_view, search_model,
)

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "davidson_itspublic_tenant"
PORTAL = PORTALS["Davidson"]
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("DAVIDSON_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("DAVIDSON_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_DAVIDSON_ROLLBACK") != "0"

#: a real browser UA -- this portal is a friendly, unauthenticated ASP.NET MVC site (plain
#: httpx already answers 200 live, confirmed this round; no impersonation tier needed)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

_PUNCT = re.compile(r"[.,#]")


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "davidson"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def _addr_key(s: Optional[str]) -> str:
    """A loose house-number + first-street-word key for matching a bill's own situs
    (parse_description()'s output, via parse_rows()) against the row's street_address --
    tolerant of directional/suffix spelling differences between the portal and the board, same
    loose standard every sibling rollback module already uses for address confirmation (never
    bind on owner name alone)."""
    toks = _PUNCT.sub(" ", (s or "").upper()).split()
    return " ".join(toks[:2])  # house number + first street-name token is enough to match


def _money(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return None


def _positive(v: Any) -> Optional[float]:
    f = _money(v)
    return f if f and f > 0 else None


def build_block(view: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one ViewTaxBill detail's own "Deferred
    Value" line, or None when it is blank/zero -- never invented. `view` is
    tax_lien_itspublic.parse_view()'s own label/value dict, unmodified."""
    deferred = _positive(view.get("Deferred Value"))
    if deferred is None:
        return None
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Davidson",
        "state": "NC",
        "source": 'taxsearch.co.davidson.nc.us TaxBillSearch, ViewTaxBill ("Deferred Value")',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled; no rate source either
        "match_method": "owner_name+street_address",
    }
    parcel_total = _positive(view.get("Parcel Value Total"))
    if parcel_total:
        rec["parcel_value_total"] = round(parcel_total, 2)
    year_bill = view.get("Year-Bill Number")
    if year_bill:
        rec["tax_year"] = str(year_bill).split("-")[0]
    return rec


async def _search(c: httpx.AsyncClient, owner: str) -> list[dict]:
    """Davidson's own OwnerName search -> parse_rows()'s bill list (year/bill/owner/ids/situs/
    original/balance/in_tax_foreclosure), newest year first. Reuses search_model()/_headers()/
    parse_rows() from the verifier unmodified."""
    headers = _headers(PORTAL)
    model = search_model(PORTAL, "OwnerName", owner)
    r1 = await c.post(f"{PORTAL.base}/TaxBillSearch/GetSearchTablePartial/", data=model,
                       headers=headers)
    r1.raise_for_status()
    r2 = await c.post(f"{PORTAL.base}/TaxBillSearch/GetSearchTableData",
                       data={"Page": 1, "NumRows": 50, "Table": "PayTaxBills"}, headers=headers)
    r2.raise_for_status()
    payload = r2.json()
    if not isinstance(payload, dict):
        return []
    return parse_rows(payload, PORTAL)


async def _view(c: httpx.AsyncClient, year: Any, bill: str) -> dict:
    """One bill's ViewTaxBill label/value dict. Reuses parse_view() from the verifier
    unmodified."""
    headers = _headers(PORTAL)
    r = await c.post(f"{PORTAL.base}/TaxBillSearch/ViewTaxBill",
                      data={"taxYear": str(year), "billNumber": str(bill)}, headers=headers)
    r.raise_for_status()
    return parse_view(r.text)


async def enrich_davidson_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search taxsearch.co.davidson.nc.us by OwnerName (the only field confirmed live for this
    portal), confirm with street address (never one signal alone), fetch ViewTaxBill for the
    confirmed match's newest bill, and restate its "Deferred Value" line into
    raw['rollback_exposure'] when positive. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_DAVIDSON_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_candidates": 0,
             "too_many_candidates": 0, "no_confident_match": 0, "matched": 0,
             "errors": 0, "deferred_found": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        # the portal needs a live ASP.NET session cookie before any search call
        r0 = await c.get(f"{PORTAL.base}/TaxBillSearch")
        r0.raise_for_status()

        async def one(li: Listing) -> None:
            async with sem:
                try:
                    bills = await _search(c, li.owner_name)
                except Exception:  # noqa: BLE001 - one lead never kills the pass
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            stats["searched"] += 1
            if not bills:
                stats["no_candidates"] += 1
                return
            if len(bills) >= MAX_CANDIDATES:
                stats["too_many_candidates"] += 1
                return
            want = _addr_key(li.street_address)
            match = next((b for b in bills if b.get("situs") and _addr_key(b["situs"]) == want),
                         None) if want else None
            if not match:
                stats["no_confident_match"] += 1
                return
            async with sem:
                try:
                    view = await _view(c, match["year"], match["bill"])
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            if "Current Balance" not in view:
                return
            stats["matched"] += 1
            block = build_block(view)
            if not block:
                return
            stats["deferred_found"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw[RAW_KEY] = block

        await asyncio.gather(*(one(li) for li in targets))
    log.info("davidson_rollback.done", **stats)
    return stats
