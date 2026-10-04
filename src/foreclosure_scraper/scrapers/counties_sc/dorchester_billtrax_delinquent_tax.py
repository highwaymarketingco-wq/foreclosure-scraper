"""Dorchester County SC delinquent real-property tax roll via the county's BillTrax
Angular SPA -> its BillTrax_County/MongoDB API.

WHY THIS EXISTS
    Dorchester (~160K population, part of the "17-county thin tax-coverage cluster" --
    docs/completeness_audit_2026-09-29.md) had ZERO delinquent-tax scraper. Not qPayBill
    (not on that vendor), not the Catalis/Sturgis CDN roll (a prior probe found
    dorchestercountytaxesonline.com embedding a Catalis GUID, but every live POST to that
    CloudFront distribution -- including a control request with Pickens' own known-good
    GUID -- came back 403 "Request blocked" from CloudFront itself, an infrastructure-side
    condition of that whole distribution, not evidence Dorchester specifically lacks data;
    see qpaybill_delinquent_roll.py's 2026-09-23 docstring and
    tests/test_qpaybill_dillon_edgefield_gap_counties.py). That CloudFront path is
    unrelated to this one: this module targets a THIRD, distinct vendor --
    dorchestercountyscdelinquenttax.billtrax.com -- never before probed in this repo.

THE SITE
    dorchestercountyscdelinquenttax.billtrax.com is an Angular SPA (webpack chunk name
    "county_ui", the same shared white-label template BillTrax deploys per county -- its
    index.html even ships a commented-out `<title>Greenville County</title>` left over
    from copying that build). The entry page is a clean 200, no CAPTCHA, no login, no
    click-through terms. Checked 2026-09-29 for sibling SC tenants under the same
    "<county>countyscdelinquenttax.billtrax.com" naming: none of the other 16 counties in
    the thin-coverage cluster (Abbeville, Allendale, Bamberg, Barnwell, Calhoun, Chester,
    Chesterfield, Darlington, Edgefield, Fairfield, Greenwood, Lee, Marlboro, McCormick,
    Williamsburg) resolve, nor do Greenville/Anderson/Spartanburg/Pickens/Oconee (DNS
    failures on every guess) -- Dorchester appears to be BillTrax's only
    "delinquent-tax"-specific SC tenant, so this is a single-county win, not multi-county.

REVERSE-ENGINEERING THE API (no browser tool available; done by downloading the app's
own JS bundles with plain HTTP GETs and reading them)
    The app's environment config (baked into main.<hash>.js and duplicated inside two
    lazy webpack chunks) names the real data host:
        api: "https://dorchestercountyscdelinquenttaxapi.billtrax.com"
    Every HTTP call in the app funnels through a shared CommonService whose `post(c,S)`
    method wraps S as JSON inside a browser FormData field named "RequestData" and POSTs
    to `api + c`, with a header `ar: 5e3d803410d9620e488249eb` set on EVERY request
    (anonymous or not) via `getHttpHeader()`. That "ar" value is not a login/session
    secret -- it is a static string baked into the public, unauthenticated JS bundle that
    ships to every visitor's browser (the same class of "app-identifier" header as e.g. a
    referrer-restricted public API key), sent by anonymous quick-pay searches with no
    session cookie. There is no bearer token, no CAPTCHA and no click-through gate on the
    actual data calls below -- confirmed by calling them cold, with no prior page load and
    no cookies, and getting real data back (verified live 2026-09-29).

    Two calls, both public POSTs, both returning `HasErrors: false`:

    1. POST /crm/api/utilities/getbyidquickpay  {"utilityId": "<24-hex ObjectId>"}
       Bootstraps the search-field template (NewQuickPayParams: AccountNumber/BillNumber/
       PropertyOwner/PropertyLocation) for one "bill type". The Dorchester utility list
       (POST /crm/api/utilities/list) has exactly one entry:
           Id="6832cda4f10fe04836869fcc"  Name="Delinquent Tax"  BillTypeUniqueId="delinquenttax"
       This whole subdomain is single-purpose, so that id is hardcoded below (UTILITY_ID)
       rather than re-discovered every run -- but a live sanity call is still made, because
       a hand-built minimal request body (Id + NewQuickPayParams + PageCriteria only, no
       other keys) got a server-side NullReferenceException: the backend deserializes the
       WHOLE getbyidquickpay response into one shared model and touches a field this
       scraper doesn't otherwise need, so the safest, most stable shape is "echo back
       exactly what the real client got, with only FieldValue/IsPaid/PageCriteria changed"
       -- the same principle CLAUDE.md asks for (verify the real shape, don't guess it).

    2. POST /crm/api/payment/SearchNewForQuickPayRawBsonExecutorWithRateLimit  <mutated
       copy of #1's response>
       Returns Results[0].Rows[*].BillsAndPayments[*].Bill[] (list of {FieldName,
       FieldValue} pairs) plus Results[0].PageAttributes.TotalRecords.

    CRITICAL VERIFIED FINDING -- the IsPaid filter parameter ("All"/"Paid"/"Unpaid") does
    NOTHING on a blank-owner query: all three values returned an IDENTICAL
    PageAttributes.TotalRecords (22,386) on 2026-09-29. Per CLAUDE.md ("never accept a
    status code -- or a label -- as evidence"), this was checked rather than trusted: a
    3,000-row sample under "Unpaid" showed 2,167 rows with TotalDueNow == 0 (a bill that
    was HISTORICALLY delinquent and has since been paid off -- IsDeliquent stays true
    forever as a permanent marker) versus 819 rows with a genuine nonzero current balance.
    So "Unpaid" means "ever flagged delinquent", not "currently owed" -- this module
    filters on the actual TotalDueNow > 0 value, not the filter label.

    Also verified on that same 3,000-row sample: BillNumber's prefix distinguishes bill
    type perfectly and matches AccountNumber's shape 100% of the time --
        "R-YYYY-########"  (2,917/2,917) -> AccountNumber is a real-estate TMS,
                                              NNN-NN-NN-NNN-NNN (e.g. 012-00-00-137-000)
        "M-YYYY-########"  (83/83)        -> AccountNumber is a plain digit string or an
                                              "FIL########" id (vehicle/manufactured-home/
                                              business-personal-property account, not a
                                              parcel)
    Only "R" (real-estate, TMS-shaped AccountNumber) rows are kept here, matching this
    repo's convention elsewhere (Catalis's RealPropertyType filter, Aiken's mobile-home
    exclusion) of not poisoning parcel-keyed dedupe with non-parcel account numbers.

    A blank PropertyOwner + blank AccountNumber query returns the WHOLE roll directly
    (paginated via PageCriteria), so no qPayBill-style A-Z name-prefix sweep is needed --
    confirmed page 0 and page 1 return disjoint AccountNumbers at PageSize=200, and
    PageSize up to 2,000 returned exactly 2,000 rows with no silent cap (a full sweep of
    22,386 rows is ~12 requests of 2,000 each, well under any reasonable "gentle" budget).

    Free, public, no login. Confirmed multiple times against LIVE production data
    2026-09-29 (not a fixture, not a guess): e.g. account 012-00-00-137-000, owner
    "SMITH THERESA LORAINE", situs "MOUNT ZION RD", notice R-2025-03500291.

WHAT A RECORD CARRIES
    AccountNumber   the TMS (real-estate rows only; see filter above)
    BillNumber      "<R|M>-<year>-########" -- the year is the tax year of THIS bill
    PropertyOwner   billing name (often "LAST FIRST" or an entity)
    PropertyLocation situs, no city/state/zip (single free-text line)
    TotalDueNow     current balance owed on THIS bill, string-encoded double
    BillDate        ISO datetime the notice was issued
    BlockPayment / ReasonToBlockPayment  the county has taken this bill off online pay
                    (e.g. already at the delinquent-tax office) -- kept in raw, not
                    treated as "not a lead"
    BillId / PropertyId  the vendor's own MongoDB ids for this bill/property

    A parcel delinquent for multiple years arrives as multiple bills sharing one
    AccountNumber -- aggregated here into one Listing per parcel (sc_catalis_
    delinquent_roll.aggregate_bills's exact pattern), balances summed, years listed.

PER-BILL NOTICE PDF (AUDITED 2026-10-03)
    Every bill also carries `PdfName` + `ContainerName` -- not previously captured
    anywhere, despite most real (non-placeholder) ones pointing at a genuine, per-bill
    delinquent-tax NOTICE PDF (live sample of 57 current nonzero-balance real-estate
    bills: 35 (61%) had a real filename like "dc_R-2025-10078864_delq.pdf" or
    "mobile_R-2024-10076383-00.pdf"; the rest were the generic placeholder
    "empty-bill.pdf"/"ICVehicleEmpty.pdf" the app falls back to for a too-new bill
    with no notice generated yet).

    Reverse-engineered the actual document retrieval live with a real browser
    (static JS-bundle analysis alone was not enough -- the backend call that mints
    the signed URL is buried in a lazy-loaded Angular chunk this session never
    isolated): the app's "View Bill" action calls
    `window.open("/view/bill/pdfbill?" + base64(f"pdfName={PdfName}&container={ContainerName}"))`
    (URL-encoded). That route is NOT a server redirect -- a plain `httpx`/`fetch`
    GET to it just returns the Angular shell (200 text/html) -- it only resolves once
    a REAL browser navigates to it, Angular bootstraps, and the route's own component
    calls a (still-unidentified) backend endpoint that mints a short-lived (~20 min)
    Azure Blob SAS URL and does `location.href = <that URL>`. CONFIRMED working live
    2026-10-03 (both the placeholder "empty-bill.pdf"/container "billtrax" and a real
    "dc_R-2025-10078864_delq.pdf"/container "dorchester-proptax-2025" -- the FIRST
    attempt at the real one silently hung because the container name is PER-BILL, not
    always "billtrax"; using the bill's own ContainerName fixed it) -- the browser
    tab's title and origin changed to the target PDF / `billtraxblob.blob.core.windows.net`
    in both cases.

    Because that redirect is JS-driven (not a plain HTTP 302), this scraper's plain
    httpx stack CANNOT resolve it to PDF bytes server-side -- there is no browser
    runtime in the scrape loop, and running one per-bill at 22k+ rows is not this
    codebase's architecture (see "no browser tool available" elsewhere in this file).
    So the DETERMINISTIC view-URL (same base64 scheme, built from fields already on
    every bill) is captured into raw as `notice_pdf_view_url` -- a real, always-correct
    link a human (or a future browser-based enrichment pass) can open directly -- but
    is deliberately kept OUT of enrichment_doc_ocr.py's `_DOC_FIELDS` scan (that
    enricher fetches with plain httpx too, so it would just download the Angular
    shell, not the PDF -- harmless, but useless, so there is no point feeding it in).
    Only built when PdfName is a real, non-placeholder filename.

Free, public, no login, no CAPTCHA.
Slug: counties_sc.dorchester_billtrax_delinquent_tax
Category: county_tax
ListingType: TAX_LIEN (standing roll -- no scheduled sale/redemption date on this source)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from datetime import datetime
from typing import Iterable
from urllib.parse import quote as _urlquote

import httpx
import structlog

from ...base_scraper import BaseScraper, OUTCOME_OK, OUTCOME_BLOCKED, OUTCOME_PARTIAL, OUTCOME_ZERO
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_sc.dorchester_billtrax_delinquent_tax"

SITE_URL = "https://dorchestercountyscdelinquenttax.billtrax.com/"
API_BASE = "https://dorchestercountyscdelinquenttaxapi.billtrax.com"
UTILITY_PATH = "/crm/api/utilities/getbyidquickpay"
SEARCH_PATH = "/crm/api/payment/SearchNewForQuickPayRawBsonExecutorWithRateLimit"

#: Dorchester's single bill type ("Delinquent Tax"), from POST /crm/api/utilities/list
#: (verified live 2026-09-29). This whole subdomain is single-purpose, so it is not
#: re-discovered every run.
UTILITY_ID = "6832cda4f10fe04836869fcc"

#: The static "app-identifier" header the public JS bundle sends on every call, anonymous
#: or not -- see module docstring. Not a session/login secret.
_AR_HEADER = "5e3d803410d9620e488249eb"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

#: Real-estate TMS shape observed on every "R-"-prefixed bill: NNN-NN-NN-NNN-NNN.
_TMS_RE = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}-\d{3}$")

#: Page size per request. 2,000 measured live with no server-side cap and ~7s response
#: time; the full ~22k-row roll is ~12 requests at this size.
PAGE_SIZE = int(os.getenv("BILLTRAX_DORCHESTER_PAGE_SIZE", "2000"))

#: Hard ceiling on pages fetched in one run, independent of the server's own
#: PageAttributes.TotalRecords -- a safety valve if that total is ever wrong or the roll
#: grows sharply, not a number expected to bind in practice (22,386 / 2,000 ~= 12 pages).
MAX_PAGES = int(os.getenv("BILLTRAX_DORCHESTER_MAX_PAGES", "40"))

#: Gentle pace between page requests. The endpoint's own name
#: ("...WithRateLimit") says the vendor throttles it; nothing here has hit a 429 yet, and
#: this stays cheap on purpose rather than testing where that line is.
_PACE_S = float(os.getenv("BILLTRAX_DORCHESTER_PACE_S", "1.0"))

_REQUEST_TIMEOUT = float(os.getenv("BILLTRAX_DORCHESTER_TIMEOUT_S", "45.0"))

_BACKOFF_S = 5.0


class BillTraxBlocked(RuntimeError):
    """The host answered 403 or otherwise refused the request. That is the host
    declining, not a rate limit: stop, do not retry, do not work around it (the same
    posture as sc_catalis_delinquent_roll.CatalisBlocked and the CLAUDE.md compliance
    line -- a WAF/challenge/login is a wall, not something to defeat)."""


def _headers() -> dict:
    return {
        "User-Agent": _UA,
        "ar": _AR_HEADER,
        "Accept": "application/json",
        "Referer": SITE_URL,
        "Origin": SITE_URL.rstrip("/"),
    }


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    """POST body as JSON inside a multipart 'RequestData' field, matching the app's own
    CommonService.post() exactly (see module docstring) -- a hand-built minimal body
    without this shape 500'd with a server-side NullReferenceException."""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            r = await client.post(
                API_BASE + path,
                files={"RequestData": (None, json.dumps(body))},
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            await asyncio.sleep(_BACKOFF_S * (attempt + 1))
            continue
        if r.status_code == 403:
            raise BillTraxBlocked(f"HTTP 403 for {path}")
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("Retry-After") or 0) or _BACKOFF_S * (2 ** attempt)
            log.info("dorchester_billtrax.retry", path=path, status=r.status_code,
                     attempt=attempt + 1, sleeping=round(wait, 1))
            await asyncio.sleep(min(wait, 60.0))
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("HasErrors"):
            raise ValueError(f"API HasErrors=true for {path}: "
                             f"{str(data.get('Exception') or data.get('Errors'))[:200]}")
        return data
    raise last_exc or RuntimeError(f"gave up on {path} after retries")


def _field_map(fields: list[dict]) -> dict[str, str]:
    return {f.get("FieldName"): f.get("FieldValue") for f in (fields or [])}


def _num(v) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _bill_year(bill_number: str | None) -> int | None:
    """'R-2025-03500291' -> 2025. Best-effort; returns None on any other shape."""
    if not bill_number:
        return None
    parts = bill_number.split("-")
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 4:
        return int(parts[1])
    return None


def _is_real_estate(account_number: str | None) -> bool:
    return bool(account_number and _TMS_RE.match(account_number))


#: The app falls back to one of these generic templates when a bill is too new to
#: have a real per-bill notice PDF generated yet (live-confirmed on current-page
#: bills) -- a view-URL built from one of these would only show boilerplate.
_PLACEHOLDER_PDF_NAMES = {"empty-bill.pdf", "icvehicleempty.pdf", ""}


def _notice_pdf_view_url(pdf_name: str | None, container_name: str | None) -> str | None:
    """The deterministic Angular route that -- ONLY in a real browser, see module
    docstring's "PER-BILL NOTICE PDF" section -- redirects to this bill's actual
    notice PDF. None for a blank/placeholder PdfName."""
    pdf_name = (pdf_name or "").strip()
    container_name = (container_name or "").strip()
    if not pdf_name or not container_name or pdf_name.lower() in _PLACEHOLDER_PDF_NAMES:
        return None
    payload = f"pdfName={pdf_name}&container={container_name}"
    b64 = base64.b64encode(payload.encode()).decode()
    return f"{SITE_URL.rstrip('/')}/view/bill/pdfbill?{_urlquote(b64)}"


async def _fetch_page(client: httpx.AsyncClient, template: dict, page: int,
                       page_size: int = PAGE_SIZE) -> tuple[list[dict], int]:
    """One search window: records [page*page_size, (page+1)*page_size). Returns
    (bill dicts, TotalRecords). `page_size` is exposed (not always the module-level
    PAGE_SIZE) so _fetch_range_with_recovery can re-request a failing window at a
    finer resolution -- see that function."""
    body = dict(template)
    body["Filter"] = ""
    body["IsPaid"] = "All"  # verified this param does not change the result set on a
                             # blank query (module docstring) -- filtering happens
                             # client-side on TotalDueNow instead.
    params = []
    for p in template.get("NewQuickPayParams", []):
        p2 = dict(p)
        p2["FieldValue"] = ""
        params.append(p2)
    body["NewQuickPayParams"] = params
    body["PageCriteria"] = {"PageNumberToFetch": page, "PageSize": page_size,
                             "SortOrder": "Desc", "SortColumn": ""}
    data = await _post(client, SEARCH_PATH, body)
    results = data.get("Results") or [{}]
    res0 = results[0] if results else {}
    bills: list[dict] = []
    for row in res0.get("Rows", []) or []:
        for bp in row.get("BillsAndPayments", []) or []:
            bill = _field_map(bp.get("Bill"))
            bill["_IsDeliquent"] = bp.get("IsDeliquent")
            bill["_IsPaid"] = bp.get("IsPaid")
            bill["_BillId"] = bp.get("BillId")
            bill["_PropertyId"] = bp.get("PropertyId")
            bills.append(bill)
    total = int((res0.get("PageAttributes") or {}).get("TotalRecords") or 0)
    return bills, total


#: Floor window size for _fetch_range_with_recovery's bisection. Live-diagnosed
#: 2026-09-29: a full PAGE_SIZE=2000 page failed with a server-side MongoDB
#: "not a valid 24 digit hex string" error (a malformed ObjectId on ONE record in
#: BillTrax's own data, not anything this scraper sends), and bisecting at
#: PageSize=200 isolated it to a single 200-record window (offset 17,200 of
#: 22,386) while every window on either side of it succeeded cleanly. Bisecting
#: down to this floor bounds the worst-case data loss from one such bad record to
#: (at most, two adjacent) _MIN_WINDOW-sized windows instead of an entire
#: PAGE_SIZE page (2,000) or the whole rest of the roll.
#:
#: Kept at a clean power-of-two fraction of the default PAGE_SIZE (2000 -> 1000 ->
#: 500 -> 250) rather than halved further: PAGE_SIZE's remaining odd factor (125)
#: cannot be split into two EQUAL integer halves, and an uneven split would risk
#: silently skipping or double-counting the boundary record. 250 already bounds
#: the loss far below one full page, so recursion deliberately stops before that
#: parity problem could occur.
_MIN_WINDOW = 250


async def _fetch_range_with_recovery(
    client: httpx.AsyncClient, template: dict, offset: int, size: int,
) -> tuple[list[dict], int | None, list[tuple[int, int]]]:
    """Fetch bills in [offset, offset+size). On failure, retries once, then bisects
    down to _MIN_WINDOW to isolate a bad record to the smallest possible window
    instead of losing the whole range. Returns (bills, TotalRecords-or-None,
    skipped [(offset, size), ...] windows that still failed at the floor)."""
    assert size > 0 and offset % size == 0, f"offset {offset} must be a multiple of size {size}"
    page = offset // size
    try:
        bills, total = await _fetch_page(client, template, page, page_size=size)
        return bills, total, []
    except Exception as exc:  # noqa: BLE001
        log.warning("dorchester_billtrax.window_error", offset=offset, size=size,
                    error=str(exc)[:160])
    await asyncio.sleep(_BACKOFF_S)
    try:
        bills, total = await _fetch_page(client, template, page, page_size=size)
        return bills, total, []
    except Exception as exc:  # noqa: BLE001
        log.warning("dorchester_billtrax.window_error_retry_failed", offset=offset,
                    size=size, error=str(exc)[:160])
    if size <= _MIN_WINDOW or size % 2 != 0:
        # size % 2 != 0 guards a non-default PAGE_SIZE (env override) that hits an odd
        # number before reaching _MIN_WINDOW -- halving an odd size unevenly risks
        # silently skipping or double-fetching the boundary record, so this is treated
        # as the floor instead of bisecting further.
        log.warning("dorchester_billtrax.window_skipped", offset=offset, size=size,
                    note="bounded gap: this window failed at the floor granularity "
                         "and is being skipped rather than blocking the rest of the roll")
        return [], None, [(offset, size)]
    half = size // 2
    b1, t1, s1 = await _fetch_range_with_recovery(client, template, offset, half)
    b2, t2, s2 = await _fetch_range_with_recovery(client, template, offset + half, half)
    return b1 + b2, t1 or t2, s1 + s2


def _aggregate(bills: Iterable[dict]) -> list[Listing]:
    """One Listing per real-estate parcel, balances summed across bill-years -- the same
    shape as sc_catalis_delinquent_roll.aggregate_bills, for the same reason: a parcel
    delinquent for N years arrives as N bills sharing one AccountNumber, and the board
    merges same-parcel rows on the parcel key anyway."""
    by_parcel: dict[str, list[dict]] = {}
    skipped_non_real_estate = 0
    skipped_zero_balance = 0
    for b in bills:
        acct = (b.get("AccountNumber") or "").strip()
        if not _is_real_estate(acct):
            skipped_non_real_estate += 1
            continue
        if (_num(b.get("TotalDueNow")) or 0) <= 0:
            skipped_zero_balance += 1
            continue
        by_parcel.setdefault(acct, []).append(b)

    now = datetime.utcnow()
    out: list[Listing] = []
    for acct, group in by_parcel.items():
        group = sorted(group, key=lambda b: _bill_year(b.get("BillNumber")) or 0, reverse=True)
        latest = group[0]
        owner = (latest.get("PropertyOwner") or "").strip() or None
        situs = (latest.get("PropertyLocation") or "").strip() or None

        per_bill = []
        for b in group:
            pdf_name = b.get("PdfName")
            container_name = b.get("ContainerName")
            per_bill.append({
                "bill_number": b.get("BillNumber"),
                "year": _bill_year(b.get("BillNumber")),
                "total_due_now": _num(b.get("TotalDueNow")),
                "bill_date": b.get("BillDate"),
                "block_payment": str(b.get("BlockPayment")).lower() == "true",
                "reason_to_block_payment": b.get("ReasonToBlockPayment") or None,
                "bill_id": b.get("_BillId"),
                "property_id": b.get("_PropertyId"),
                "sticker_no": (b.get("StickerNo") or "").strip() or None,
                "pdf_name": pdf_name or None,
                "container_name": container_name or None,
                "notice_pdf_view_url": _notice_pdf_view_url(pdf_name, container_name),
            })
        years = sorted({p["year"] for p in per_bill if p["year"]})
        total_due = round(sum(p["total_due_now"] or 0 for p in per_bill), 2) or None
        # Surface the most relevant (current-year, or else newest) real notice link
        # at the parcel level too, so it's reachable without scanning every bill.
        notice_url = next(
            (p["notice_pdf_view_url"] for p in per_bill if p["notice_pdf_view_url"]),
            None)

        raw = {
            "billtrax_dorchester_delinquent_tax": {
                "account_number": acct,
                "owner": owner,
                "property_location": situs,
                "bills": per_bill,
                "years": years,
                "years_delinquent": len(years),
                "is_two_year_plus": len(years) >= 2,
                "total_due": total_due,
                "property_id": latest.get("_PropertyId"),
                # Deliberately NOT a top-level raw["document_url"]/etc key --
                # enrichment_doc_ocr.py's _DOC_FIELDS scan fetches with plain
                # httpx, which cannot resolve this JS-driven redirect (see
                # module docstring's "PER-BILL NOTICE PDF" section).
                "notice_pdf_view_url": notice_url,
            },
        }
        if total_due:
            raw["tax_owed"] = {"balance": total_due, "kind": "delinquent_tax", "source": SLUG,
                               "year": years[-1] if years else None, "basis": "own_record"}

        span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
        out.append(Listing(
            source=SLUG,
            source_url=SITE_URL,
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county="Dorchester",
            parcel_id=acct,
            defendant=owner,
            owner_name=owner,
            street_address=situs,
            description=(f"Delinquent property tax {span}"
                         f" ({len(years) or len(group)} bill"
                         f"{'s' if (len(years) or len(group)) != 1 else ''})"
                         + (f": ${total_due:,.2f} due" if total_due else "")),
            first_seen=now, last_seen=now,
            raw=raw,
        ))
    if skipped_non_real_estate or skipped_zero_balance:
        log.info("dorchester_billtrax.filtered", non_real_estate=skipped_non_real_estate,
                 zero_balance=skipped_zero_balance, kept_parcels=len(out))
    return out


class DorchesterBillTraxDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Dorchester SC Delinquent Tax (BillTrax)"
    category = "county_tax"
    timeout_s = 300.0
    expected_min_count = 200
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers=_headers()) as client:
            try:
                template = await _post(client, UTILITY_PATH, {"utilityId": UTILITY_ID})
            except BillTraxBlocked:
                log.warning("dorchester_billtrax.blocked_403", stage="getbyidquickpay",
                            note="host answered 403; treating as a wall, not retrying")
                self.last_outcome = OUTCOME_BLOCKED
                self.last_reason = "HTTP 403 on getbyidquickpay"
                return []
            except Exception as exc:  # noqa: BLE001
                log.error("dorchester_billtrax.template_fetch_error", error=str(exc)[:200])
                self.last_outcome = OUTCOME_ZERO
                self.last_reason = f"could not fetch search template: {exc}"[:200]
                return []

            all_bills: list[dict] = []
            total_records = None
            all_skipped: list[tuple[int, int]] = []
            page = 0
            while page < MAX_PAGES:
                offset = page * PAGE_SIZE
                try:
                    bills, total, skipped = await _fetch_range_with_recovery(
                        client, template, offset, PAGE_SIZE)
                except BillTraxBlocked:
                    log.warning("dorchester_billtrax.blocked_403", stage="search", page=page,
                                note="host answered 403; stopping, shipping what we have")
                    self.partial = _aggregate(all_bills)
                    self.last_outcome = OUTCOME_PARTIAL if all_bills else OUTCOME_BLOCKED
                    self.last_reason = f"HTTP 403 on search page {page}"
                    return self.partial

                if skipped:
                    # A page-sized window failed even after a retry and full bisection
                    # down to _MIN_WINDOW (see _fetch_range_with_recovery's docstring):
                    # a small, precisely-bounded gap, logged so it is visible in the run
                    # report rather than silently thinning the roll. The final message
                    # (using the fully-accumulated totals) is built once after the loop
                    # ends, not here, so it never reports a stale partial count.
                    all_skipped.extend(skipped)

                if total_records is None and total:
                    total_records = total
                    log.info("dorchester_billtrax.total_records", total=total_records)
                all_bills.extend(bills)
                self.partial = _aggregate(all_bills)
                page += 1
                covered = page * PAGE_SIZE
                if total_records:
                    # The authoritative stop condition. A page thinned by a skipped
                    # sub-window still legitimately advances `covered` by a full
                    # PAGE_SIZE -- it is the OFFSET that has been walked past, not the
                    # row count, so a skip must never be mistaken for "reached the end".
                    if covered >= total_records:
                        break
                elif not bills and not skipped:
                    # total_records still unknown (even page 0 never returned one) --
                    # fall back to "an empty, non-skipped page means done".
                    break
                await asyncio.sleep(_PACE_S)

        listings = _aggregate(all_bills)
        incomplete_reason = None
        if all_skipped:
            incomplete_reason = (
                f"{len(all_skipped)} window(s) totalling "
                f"{sum(s for _, s in all_skipped)} rows skipped after bisection "
                f"(first at offset {all_skipped[0][0]}); {len(all_bills)} of "
                f"{total_records or '?'} raw bills read")
        log.info("dorchester_billtrax.done", pages=page, raw_bills=len(all_bills),
                 total_records=total_records, parcels=len(listings),
                 elapsed_s=round(time.monotonic() - t0, 1), incomplete=bool(incomplete_reason))
        if incomplete_reason:
            self.partial = listings
            self.last_outcome = OUTCOME_PARTIAL if listings else OUTCOME_ZERO
            self.last_reason = incomplete_reason
        else:
            self.last_outcome = OUTCOME_OK if listings else OUTCOME_ZERO
        return listings
