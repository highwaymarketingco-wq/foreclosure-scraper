"""Berkeley County SC — delinquent Real Property tax roll via the paystar.io
payment portal's own unauthenticated search API.

BACKGROUND
    Berkeley (and Jasper, and Florence) route their tax payment portal through
    a vendor called paystar.io. Found 2026-09-14 driving Berkeley's portal
    (berkeleycountysc.paystar.io) with a real browser and network capture: its
    search box calls a plain, unauthenticated JSON API. Its Terms of Use is a
    plain liability disclaimer ("no warranties... for informational use
    only"), the same shape as other disclaimer pages already treated as
    non-prohibitive in this codebase -- not a scraping-prohibition clause.

    Scoped 2026-09-14 as a "qpaybill_delinquent_roll.py-scale build" because
    the FIRST endpoint found (`/api/search/suggest?searchTerm=X`) is a
    5-result autocomplete with no bulk path -- exactly the shape that forced
    qpaybill's alphabet-prefix enumeration. Investigated further 2026-09-15
    and found the autocomplete widget is backed by a SECOND, much better
    endpoint the search RESULTS PAGE itself calls: `POST /api/search`. That
    endpoint takes an EMPTY searchTerm plus facet filters and returns the
    ENTIRE roll directly -- no name enumeration needed at all, unlike every
    other SC tax-portal source in this codebase.

VERIFIED LIVE 2026-09-15 (plain httpx, no browser, no cookies, no auth):

    POST https://berkeleycountysc.paystar.io/api/search
    {"searchTerm": "", "facetFilters": {"PaymentStatus": ["Unpaid"],
     "AssetType": ["Real Property"], "TaxYear": []}, "page": 1, "pageSize": 1000}

    -> {"data": {"results": [...], "totalCount": 3587, "facets": [...]}}

    pageSize accepts up to at least 5000 (the whole roll in ONE request,
    confirmed); paginated at 1000 here to stay well inside whatever cap the
    vendor might tighten later. Each list row carries only invoiceNumberHash/
    invoiceNumber/taxYear/invoiceeName/paymentStatus -- no address, no
    parcel, no amount -- so a SECOND, per-row request is required:

    GET https://berkeleycountysc.paystar.io/api/invoices/{invoiceNumberHash}

    This is the real find. One response carries EVERYTHING a lead needs, in
    ONE call, that no other SC tax source in this codebase gives together:
      - invoiceAmountMinor        the actual balance owed, in cents
      - assetIdentifierDisplay    the TMS parcel number
      - invoiceStreetAddress1/City/State/PostalCode   OWNER'S MAILING address
      - assetMetaJson             a stringified JSON blob holding the county's
        OWN raw record: SiteAddress/SiteCity/SiteState/SiteZip (the SITUS --
        i.e. the actual property location, distinct from the mailing address
        above), ParentTMS, DeedBook/DeedPage, TaxesDue, Millage,
        ResidentialAssessmentExemption (owner-occupancy signal), appraisal
        and assessment values, acreage.
    A mismatch between the mailing address and SiteAddress is a live,
    first-party absentee-owner signal -- computed here the same way
    enrichment_owner_mailing.py's _is_absentee() already does for every other
    SC source, reused rather than reimplemented so the two never drift.

NOT A SOLVE-ONCE-FOR-ALL-THREE, CORRECTED CLAIM
    2026-09-14's queue note scoped this as one build covering Berkeley,
    Jasper, AND Florence. That was WRONG, checked live 2026-09-15 before
    building anything on the assumption:
      - Jasper's REAL delinquent roll turned out to live on qpaybill.com, a
        completely different vendor Jasper's own site links to from a
        separate "Pay Delinquent Taxes" button -- paystar there is only the
        CURRENT-year vehicle/property portal. Added to
        counties_sc.qpaybill_delinquent_roll's QPAYBILL_SUBS instead (see
        that module); NOT built here.
      - Florence's tenant on paystar runs an OLDER, DIFFERENT API generation
        (`GET /api/business-units/florence-county-tax/invoices/
        search-configurations/{id}/search`, not the unified `POST
        /api/search` this file uses) that REJECTS an empty searchText
        (returns `data: null`) -- it needs the SAME alphabet/prefix name
        enumeration this whole paystar detour was meant to avoid, and a
        first "Real Property" + name-prefix probe returned zero live rows,
        so it is unclear real-property delinquency data is even loaded into
        that tenant. Deferred, not built.
    So this file covers ONLY Berkeley. Retracted plainly per this session's
    own standing rule on over-optimistic claims, rather than silently
    narrowing the docstring.

WHAT THIS DOES NOT DO
    Nothing here opens the cart, the payment flow, or any authenticated path
    -- read-only GETs/POSTs against the public search/detail API exactly as
    the portal's own front end calls them.

Free, no login, no WAF, no CAPTCHA, no cookies required (verified with
credentials omitted).
Slug: counties_sc.berkeley_paystar_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...enrichment_owner_mailing import _is_absentee
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_HOST = "https://berkeleycountysc.paystar.io"
_SEARCH_URL = f"{_HOST}/api/search"
_DETAIL_URL = f"{_HOST}/api/invoices/{{hash}}"
_UI_URL = f"{_HOST}/app/invoices/{{hash}}"

_PAGE_SIZE = 1000
# MEASURED live 2026-09-23 (uncached httpx, no browser, no CAPTCHA/WAF hit at any point):
# the Unpaid Real Property roll is 3,426 rows (grown from the 2,310 seen in the 2026-09-23
# full run that TIMED OUT at exactly 300s with 0 rows shipped). This vendor is per-request
# latency-bound around ~1s/invoice, NOT a single stuck request the way qpaybill's
# Williamsburg county hung -- every request in >5,000 live detail calls during this
# investigation eventually returned (0 real errors), it is just genuinely too slow to
# finish the whole roll inside 300s:
#   concurrency=10: 2,200/3,426 details in 270.6s (8.1 req/s sustained; extrapolates to
#     ~420s for the full roll)
#   concurrency=20: 3,000/3,426 details in 330.3s (9.1 req/s sustained -- barely better
#     despite 2x the concurrency) and the LAST 300 of those slowed to 3.9 req/s, well below
#     concurrency=10's pace at a comparable cumulative request count -- consistent with
#     server-side backpressure/soft rate-limiting kicking in under higher sustained load,
#     not a client-side bottleneck.
# Net: doubling concurrency did not reliably buy throughput and risked provoking harsher
# throttling from a small county vendor, so concurrency is left UNCHANGED at 10. The real
# fix is the timeout (below) plus incremental self.partial salvage in fetch() -- see
# tests/test_berkeley_paystar_tax_timeout.py for the pinned numbers.
_DETAIL_CONCURRENCY = 10


def _not_yet_due_rows(rows: list[dict]) -> list[dict]:
    """Drop rows for the CURRENT tax year -- they are freshly-issued bills, not
    delinquent accounts, even though the portal's own "Unpaid" status covers both.

    GOTCHA, live-verified 2026-10-03 (same day as this fix, a season boundary that
    had not yet been crossed when this file was first built 2026-09-14/15/23): the
    county's 2026 annual roll loaded into paystar THIS WEEK, and an unfiltered
    "Unpaid Real Property" search balloons from the ~3,426-3,587 genuinely
    delinquent rows measured in September to 123,450 -- 120,359 of those are
    TaxYear=2026 with `delinquent: false`, `invoiceIssueDate`/`invoiceDueDate`
    both null, and an empty owner/address (confirmed on a live sample: invoice
    2026-0045354, $1,813.29 "due", `delinquent: false`). SC real-property tax
    bills go out in October and aren't due until the FOLLOWING January (confirmed
    on the same live sample: `Penalty1Date: "2027-01-15"` for a 2026 bill) -- so a
    bill for the current calendar year can never actually be delinquent yet. A
    real 2025 (prior-year) sample fetched the same day confirms the distinguishing
    field: `delinquent: true`, real owner/address populated (invoice 2025-0122247,
    108 N HWY 52 LLC, $15,429.16).

    This is a LIST-level, pre-detail-fetch filter (not just a post-filter in
    _detail_to_listing) because the whole point is to avoid spending a detail GET
    on ~120k rows that are never going to survive the delinquent-only publish
    anyway -- at the measured ~9 req/s detail-fetch pace, 120k extra requests
    would blow this scraper's 600s timeout by over 20x and turn every future run
    into the exact all-zero TIMEOUT failure tests/test_berkeley_paystar_tax_timeout.py
    already fixed once for a completely different reason (vendor latency, not a
    filter gap). A row with a missing/non-int taxYear is kept rather than dropped
    (conservative: "unclear" is not the same as "known not-yet-due").
    """
    current_year = datetime.utcnow().year
    return [r for r in rows
            if not (isinstance(r.get("taxYear"), int) and r["taxYear"] >= current_year)]


async def _prior_tax_years(client: httpx.AsyncClient) -> list[str] | None:
    """Every TaxYear facet value strictly BEFORE the current (not-yet-due) one,
    straight from the search endpoint's own facets -- no guessing a year range.

    2026-10-03 GOTCHA this exists to fix: _list_all used to page an UNFILTERED
    "Unpaid Real Property" search (facetFilters.TaxYear=[]) and rely on
    _not_yet_due_rows to drop the current year client-side AFTER listing. That
    broke the moment the county's 2026 annual roll loaded this week: the vendor
    returns results with every current-year row FIRST (live-confirmed: the
    first 50,000 results, the existing stall-guard's whole cap, were 100%
    taxYear=2026, zero real prior-year rows reached within that cap) -- so the
    client-side filter correctly dropped everything it saw, but the real
    ~3,091 delinquent rows never got paged to at all, and the scraper shipped
    0. Querying the facets directly (one cheap pageSize=1 call) and then
    passing an EXPLICIT facetFilters.TaxYear list of prior years straight to
    the server-side filter sidesteps the ordering problem entirely -- live-
    verified 2026-10-03: totalCount drops from 123,450 (unfiltered) to exactly
    3,091 (the sum of every prior-year facet count), matching
    _not_yet_due_rows' independent client-side math exactly.

    Returns None (not []) when the facets can't be read, so callers can fall
    back to the old unfiltered-then-client-filter path rather than silently
    requesting zero years.
    """
    try:
        r = await client.post(_SEARCH_URL, json={
            "searchTerm": "",
            "facetFilters": {"PaymentStatus": ["Unpaid"], "AssetType": ["Real Property"], "TaxYear": []},
            "page": 1, "pageSize": 1,
        })
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        facets = data.get("facets") or []
        tax_year_values = next(
            (f.get("facetValues") or [] for f in facets if f.get("facetName") == "TaxYear"), [])
        years = [v.get("propertyValue") for v in tax_year_values if v.get("propertyValue")]
        int_years = [(y, int(y)) for y in years if str(y).isdigit()]
        if not int_years:
            return None
        max_year = max(n for _, n in int_years)
        return [y for y, n in int_years if n < max_year]
    except Exception as exc:  # noqa: BLE001
        log.warning("berkeley_paystar.facets_fail", error=str(exc)[:160])
        return None


async def _list_all(client: httpx.AsyncClient) -> list[dict]:
    """Page the Unpaid Real Property roll, scoped to prior (actually-due) tax
    years whenever the facets are readable (see _prior_tax_years). Falls back to
    an unfiltered page sweep, with the current year dropped client-side by
    _not_yet_due_rows afterward, only if the facets call itself fails.

    No name enumeration -- this endpoint (unlike qpaybill and Florence's
    older paystar tenant) answers an empty search directly.
    """
    prior_years = await _prior_tax_years(client)
    tax_year_filter: list[str] = prior_years if prior_years is not None else []
    log.info("berkeley_paystar.tax_year_scope",
             mode="server_side_prior_years" if prior_years is not None else "unfiltered_fallback",
             years=tax_year_filter or None)

    out: list[dict] = []
    page = 1
    while True:
        r = await client.post(_SEARCH_URL, json={
            "searchTerm": "",
            "facetFilters": {"PaymentStatus": ["Unpaid"], "AssetType": ["Real Property"],
                             "TaxYear": tax_year_filter},
            "page": page,
            "pageSize": _PAGE_SIZE,
        })
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        results = data.get("results") or []
        out.extend(results)
        if len(results) < _PAGE_SIZE:
            break
        page += 1
        if page > 50:   # 50,000 rows -- far above any single SC county's roll; a stall guard, not a real cap
            log.warning("berkeley_paystar.list_page_guard_hit", pages=page)
            break
    return out


async def _fetch_detail(client: httpx.AsyncClient, sem: asyncio.Semaphore, invoice_hash: str) -> tuple[str, dict | None]:
    """Returns (invoice_hash, detail) so callers can consume results as they land
    (asyncio.as_completed) instead of needing one big all-or-nothing gather() to know
    which hash a result belongs to.
    """
    async with sem:
        try:
            r = await client.get(_DETAIL_URL.format(hash=invoice_hash))
            r.raise_for_status()
            return invoice_hash, (r.json() or {}).get("data") or None
        except Exception as exc:
            log.warning("berkeley_paystar.detail_fail", invoice_hash=invoice_hash, error=str(exc)[:140])
            return invoice_hash, None


def _meta(detail: dict) -> dict[str, Any]:
    raw = detail.get("assetMetaJson")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _full_addr(line1: str | None, city: str | None, state: str | None, zip_: str | None) -> str | None:
    line1 = (line1 or "").strip()
    city = (city or "").strip()
    state = (state or "").strip()
    zip_ = (zip_ or "").strip()
    bits = [b for b in (line1, ", ".join(b for b in (city, state) if b), zip_) if b]
    return " ".join(bits) or None


#: assetMetaJson keys the detail call already returns and this scraper used to drop
#: (2026-10-07 extraction audit, live-checked on two real invoices): the bill's own
#: breakdown (taxes, penalties, staged penalty amounts and their dates, totals),
#: the homestead exemption (age 65+/disabled relief: an elderly signal), per-class
#: land/building values, and the district/account/receipt identifiers.
_BILL_MONEY = {
    "taxes_due": "TaxesDue", "tax_penalties": "TaxPenalties", "dlq_penalties": "DLQPenalties",
    "tax_total": "TaxTotal", "bill_total": "BillTotal",
    "taxes_due_penalty1": "TaxesDuePenalty1", "taxes_due_penalty2": "TaxesDuePenalty2",
    "taxes_due_penalty3": "TaxesDuePenalty3",
    "homestead_exemption": "HomesteadExemption", "homestead_percentage": "HomesteadPercentage",
    "qr_land_value": "QRLandValue", "qr_building_value": "QRBuildingValue",
    "ot_land_value": "OTLandValue", "ot_building_value": "OTBuildingValue",
    "ag_land_value": "AgLandValue", "ag_building_value": "AgBuildingValue",
    "building_count": "TotalBuildingCount", "lot_count": "LotCount",
}
_BILL_TEXT = {
    "penalty1_date": "Penalty1Date", "penalty2_date": "Penalty2Date", "penalty3_date": "Penalty3Date",
    "homestead_application_year": "HomesteadApplicationYear", "delinquent_code": "DelinquentCode",
    "dlq_penalty_code": "DLQPenaltyCode", "exempt_code": "ExemptCode",
    "tax_district": "TaxDistrict", "fire_district": "FireDistrict", "jurisdiction": "Jurisdiction",
    "account_number": "AccountNum", "receipt_number": "ReceiptNumber",
    "rollback_code": "RollbackCode", "rollback_description": "RollbackDesc",
    "legal": "Legal1", "subdivision": "Sub", "block": "Block", "lot": "Lot",
}


def _class_total(meta: dict, kind: str) -> float | None:
    """Land + building across the QR/OT/AG classes ('Value' or 'Assessment')."""
    tot = 0.0
    for cls in ("QR", "OT", "Ag"):
        for part in ("Land", "Building"):
            tot += _num(meta.get(f"{cls}{part}{kind}")) or 0.0
    return round(tot, 2) or None


def _bill_detail(meta: dict) -> dict:
    out: dict[str, Any] = {}
    for k, src in _BILL_MONEY.items():
        v = _num(meta.get(src))
        if v:                                   # 0 / blank is "none", not a value
            out[k] = v
    for k, src in _BILL_TEXT.items():
        v = str(meta.get(src) or "").strip()
        if v and not re.fullmatch(r"0+(\.0+)?", v):     # '000' is this roll's blank
            out[k] = v
    return out


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f
    except (TypeError, ValueError):
        return None


def _detail_to_listing(detail: dict, invoice_hash: str) -> Listing | None:
    meta = _meta(detail)
    parcel = detail.get("assetIdentifierDisplay") or meta.get("Identifier") or None
    owner = detail.get("invoiceeName") or detail.get("assetOwner") or meta.get("BillName") or None
    if not (parcel or owner):
        return None

    amount_minor = detail.get("invoiceAmountMinor")
    amount = round(amount_minor / 100.0, 2) if isinstance(amount_minor, (int, float)) else _num(meta.get("TaxesDue"))
    if not amount or amount <= 0:
        return None

    # Safety net behind the list-level _not_yet_due_rows() filter in fetch(): a
    # row whose own detail explicitly says `delinquent: false` is a freshly-issued,
    # not-yet-due bill (see _not_yet_due_rows' docstring), never a real lead, even
    # if it somehow reached this point (e.g. a future season where the current
    # year's rows aren't cleanly separable by taxYear alone). Only an EXPLICIT
    # False is excluded -- None/missing stays in, matching this file's existing
    # "uncertain is not the same as known-clean" convention elsewhere.
    if detail.get("delinquent") is False:
        return None

    situs = _full_addr(meta.get("SiteAddress"), meta.get("SiteCity"), meta.get("SiteState"), meta.get("SiteZip"))
    mailing = _full_addr(detail.get("invoiceStreetAddress1"), detail.get("invoiceCity"),
                         detail.get("invoiceState"), detail.get("invoicePostalCode"))
    mail_state = (detail.get("invoiceState") or "").strip().upper() or None

    tax_year = detail.get("taxYear")
    invoice_number = detail.get("invoiceNumber") or invoice_hash
    now = datetime.utcnow()

    raw: dict[str, Any] = {
        "berkeley_paystar_tax": {
            "invoice_number": invoice_number,
            "tax_year": tax_year,
            "total_due": amount,
            "delinquent": bool(detail.get("delinquent")),
            "deed_book": meta.get("DeedBook") or None,
            "deed_page": meta.get("DeedPage") or None,
            "parent_tms": meta.get("ParentTMS") or None,
            "acres": _num(meta.get("AcresCount")),
            # All three assessment classes (2026-10-07 extraction audit): QR = owner-
            # occupied 4%, OT = other 6%, AG = agricultural. Summing QR alone left this
            # None on every non-owner-occupied parcel (on ~84% of board rows); a QR-only
            # parcel's value is unchanged.
            "appraised_value": _class_total(meta, "Value"),
            "assessed_value": _num(meta.get("TotalAssessment")),
            "millage": _num(meta.get("Millage")),
            "residential_assessment_exemption": meta.get("ResidentialAssessmentExemption") or None,
            **_bill_detail(meta),
        }
    }
    if mailing:
        raw["owner_mailing"] = {
            "owner": owner,
            "mailing": mailing,
            "situs": situs,
            "parcel_id": parcel,
            "mail_state": mail_state,
            "absentee": _is_absentee(situs, mailing),
            "out_of_state": bool(mail_state and mail_state != "SC"),
            "mailing_source": "berkeley_paystar_tax",
        }

    situs_line = meta.get("SiteAddress") or None
    return Listing(
        source="counties_sc.berkeley_paystar_tax",
        source_url=_UI_URL.format(hash=invoice_hash),
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Berkeley",
        parcel_id=parcel,
        street_address=situs_line,
        city=(meta.get("SiteCity") or None),
        zip_code=(meta.get("SiteZip") or None),
        case_number=str(invoice_number),
        owner_name=owner,
        defendant=owner,
        description=(f"Delinquent {tax_year} property tax of ${amount:,.2f} owed by {owner}"
                     + (f" (parcel {parcel})" if parcel else "")),
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class BerkeleyPaystarTax(BaseScraper):
    slug = "counties_sc.berkeley_paystar_tax"
    name = "Berkeley County SC Delinquent Real Property Tax (paystar.io)"
    category = "county_tax"
    # MEASURED live 2026-09-23 (see _DETAIL_CONCURRENCY comment above for the full data):
    # sustained throughput was 8.1-9.1 req/s and DEGRADING over a long run (not a single
    # stuck request) -- list <1s, details alone extrapolate to ~420-450s+ for the full
    # 3,426-row roll at this vendor's pace, and the roll only grows over the season. 300s
    # was never enough, and because the old fetch() held every parsed Listing in a purely-
    # local `out` list, a wait_for() cancellation at 300s discarded ALL of it -- hence the
    # 2026-09-23 full run's 0-row TIMEOUT despite real (if slow) progress underneath.
    # Raised to 600s: comfortable margin over the ~420-450s measured/extrapolated full-roll
    # time, still well inside the 900s ceiling already used by the heaviest county_tax
    # source in this same directory (greenville_hard_distress.py) and the per-scraper
    # Semaphore(parallel_scrapers) scheduling in main.py that lets one slow scraper run
    # long without blocking others (main.py deliberately avoids a global wait_for(gather())
    # that would cancel every scraper together). Paired with the self.partial salvage below
    # so that even if the vendor degrades further and 600s still isn't enough, the run
    # ships whatever it collected instead of repeating the 0-row TIMEOUT.
    timeout_s = 600.0
    expected_min_count = 500
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                rows = await _list_all(client)
            except Exception as exc:
                log.warning("berkeley_paystar.list_fail", error=str(exc)[:160])
                return out
            if not rows:
                return out

            # Drop the current (not-yet-due) tax year BEFORE spending a detail GET on
            # each row -- see _not_yet_due_rows' docstring (live-verified 2026-10-03:
            # the just-loaded 2026 roll balloons an unfiltered "Unpaid" search from
            # ~3,426 real delinquent rows to 123,450).
            listed_total = len(rows)
            rows = _not_yet_due_rows(rows)
            log.info("berkeley_paystar.not_yet_due_filtered",
                     listed_total=listed_total, after_filter=len(rows))
            if not rows:
                return out

            hashes = [r["invoiceNumberHash"] for r in rows if r.get("invoiceNumberHash")]
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            skipped = 0

            # Consume detail fetches AS THEY COMPLETE (asyncio.as_completed) and append
            # each parsed Listing to self.partial immediately, instead of one big
            # asyncio.gather() that only becomes visible after EVERY request finishes.
            # safe_run()'s soft-timeout handler ships self.partial on asyncio.TimeoutError
            # -- so if the roll grows past what timeout_s covers, or the vendor slows down,
            # this run still ships whatever it managed instead of the old all-or-nothing
            # behavior that turned a merely-slow run into a silent 0-row TIMEOUT (see class
            # docstring above and tests/test_berkeley_paystar_tax_timeout.py).
            tasks = [asyncio.ensure_future(_fetch_detail(client, sem, h)) for h in hashes]
            try:
                for coro in asyncio.as_completed(tasks):
                    invoice_hash, detail = await coro
                    if not detail:
                        skipped += 1
                        continue
                    li = _detail_to_listing(detail, invoice_hash)
                    if li is None:
                        skipped += 1
                        continue
                    out.append(li)
                    self.partial.append(li)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()

        log.info("berkeley_paystar.done", listed=len(rows), skipped=skipped, total=len(out))
        return out
