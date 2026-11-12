"""Hyde County NC ``lrcpwa.ncptscloud.com`` parcel-CAMA "Deferred" fields -> the shared
raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and gap_matrix.py's
own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for Hyde (3,148 applicable), source "tax/property
    card: bcpwa.ncptscloud.com", built=no. THAT SOURCE IS WRONG for this column -- bcpwa.ncptscloud.com
    is the Farragut "BillPWA" delinquent-TAX-BILL CSV cluster this project already reads for Hyde
    (scrapers/counties_nc/nc_ptscloud_delinquent_tax.py TENANTS["Hyde"], live since 2026-07-01, and
    the source of 1,840 of Hyde's 3,148 board rows). LIVE-VERIFIED 2026-10-20 (real download of
    Hyde's current DelinquentExtract.csv, 7,642 rows): its full 23-column header is BILL_NUMBER,
    BILL_TYPE, PARCEL_NUM, TAX_YEAR, OWNER_NAME, MAIL_ADDR1-3, IN_CARE_OF, MAIL_CITY/STATE/ZIP,
    ABSTRACT_TAXABLE_VALUE, DESCRIPTION, PROP_SIZE, ABSTRACT_ASSESS_VALUE, BILL_STATUS, BILL_AMOUNT,
    BILL_DUE_AMT, INTEREST_DUE, TOTAL_DUE_AMOUNT, BILL_DUE_DATE, FLAGS -- a billing roll, no present-
    use/market-vs-use value field of any kind. Same structural dead end
    enrichment_its_public_multiyear_tax.py's docstring already documents for this same vendor
    FAMILY's other product (TaxBillSearch); confirmed here for BillPWA specifically.

    THE REAL SOURCE IS A DIFFERENT NCPTS CLOUD PRODUCT on a different subdomain: lrcpwa.ncptscloud.com
    (LandRecordsCloud CAMA/parcel REST API -- SimpleParcelSearch + getParcelDetails, X-Tenant header
    selects the county, same shape enrichment_ncpts_lrc.py already implements and was RETIRED
    2026-10-09 for being unwired from main.py, not for being broken). LIVE-VERIFIED 2026-10-20: Hyde
    IS a live tenant there (X-Tenant: Hyde -> SimpleParcelSearch totalCount 4,645, no login/CAPTCHA,
    plain httpx 200 on every call), and getParcelDetails carries explicit ``useValueDeferred`` /
    ``totalDeferredValue`` fields -- NOT an inferred market-minus-use subtraction (the NC PTS Cloud
    trap enrichment_rollback_deferral.py's own docstring warns against), the vendor COMPUTES AND
    NAMES the figure itself, the same evidentiary bar Wake's "Total Deferred Value" line cleared.
    Cross-checked live on parcel pk=1600 (PIN 7683-12-4671, COMM/INDUSTRIAL, Swan Quarter):
    totalLandValueAssessed $117,954, landUseValue $52,211, totalDeferredValue $65,743 -- exactly
    117,954 - 52,211 to the dollar, the same identity Mecklenburg's and Wake's sources already
    verified for their own "Deferred" fields.

    So the gap list's premise (bcpwa needs a new tax-roll reader) is simply wrong for this county:
    the tax-roll reader already exists and already runs; the missing piece was reading the RIGHT
    host's RIGHT field into the RIGHT raw key, which is what this module does.

MATCH METHOD: parcel id only, the same single-signal bar enrichment_greenville_rollback_exposure.py
    already uses (no owner-name/address confirmation -- the PIN is dispositive once lrcpwa echoes it
    back unchanged). Query SimpleParcelSearch with the board row's own digits-only parcel_id; a
    result is trusted only when its own formattedPin, stripped to digits, matches EXACTLY -- never
    "closest" or "only result".

    LIVE-MEASURED 2026-10-20 (streamed the real board, read-only): of Hyde's 3,148 rows, 268 (8.5%)
    carry a parcel_id already shaped like lrcpwa's own 10-digit PIN; the other 2,880 either have no
    parcel_id or carry Hyde's own legacy tax-map/lot notation (e.g. "02559-J10-15"), which
    SimpleParcelSearch does not index (live-checked: 0 results for three such ids). Street-address
    coverage on the Hyde board is itself only 186/3,148 (5.9%), so an owner-name+address fallback
    (enrichment_ncpts_lrc.py already has the matching helpers, `_search_parcels`/`_match_parcel`,
    reused directly below rather than re-implemented) was investigated but not wired as a second
    pass here -- the realistic additional reach is small (<60 rows) against real mismatch risk on a
    rural county with few street-named parcels, and is left as a documented follow-up, not guessed at.

GATE. Only a positive ``totalDeferredValue``/``useValueDeferred`` off a parcel_id-CONFIRMED
    getParcelDetails record qualifies -- build_block() never invents one, matching every sibling in
    this family.

RATE, NEVER ASSUMED (same convention enrichment_harnett_rollback_exposure.py and
    enrichment_rollback_deferral.py's Buncombe/Wake sections already use). The effective combined tax
    rate is DERIVED per parcel from that SAME row's own raw['nc_ptscloud_delinquent_tax']['by_year']
    (the per-bill history nc_ptscloud_delinquent_tax.py already attaches) matched to lrcpwa's own
    taxYear, divided into THIS fetch's own landUseValue (the present-use-reduced assessed base, same
    concept as Harnett's "Assessed" line) -- never a hard-coded millage, and kept only inside the
    shared sane band (_RATE_MIN/_RATE_MAX). A parcel whose rate doesn't land in the band, or has no
    matching bill year on the row, still gets its real deferred_value, just without a derived
    annual/estimated-rollback figure.

Bounded, opt-in, free, public JSON API, no login, no CAPTCHA, no robots wall (every call tested
2026-10-20 answered plain httpx with HTTP 200). Gate off entirely with FORECLOSURE_HYDE_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Iterable, Optional

import structlog

from .enrichment_ncpts_lrc import _get_parcel_detail, _search_parcels
from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "hyde_lrcpwa"
TENANT = "Hyde"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("HYDE_ROLLBACK_MAX", "400"))
_CONCURRENCY = int(os.getenv("HYDE_ROLLBACK_CONCURRENCY", "4"))

ENABLED = os.environ.get("FORECLOSURE_HYDE_ROLLBACK") != "0"

_PIN_RE = re.compile(r"^[0-9]{9,11}$")


def _digits(s: Any) -> str:
    return re.sub(r"[^0-9]", "", str(s or ""))


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    pid = (li.parcel_id or "").strip()
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "hyde"
        and _PIN_RE.match(pid) and not _already_done(raw)
    )


def rate_from_ptscloud_bill(raw: dict, assessed_value: Any, tax_year: Any) -> Optional[float]:
    """Pure: the matching tax year's BILL_AMOUNT / assessed_value from this row's OWN already-
    fetched raw['nc_ptscloud_delinquent_tax']['by_year'] -- no new network call, no assumed
    millage. None when there is no bill for that year, no usable assessed_value, or the ratio
    falls outside the sane band every sibling rollback section already validates against."""
    assessed = _positive(assessed_value)
    src = raw.get("nc_ptscloud_delinquent_tax") if isinstance(raw, dict) else None
    if not isinstance(src, dict) or assessed is None:
        return None
    try:
        year_int = str(int(str(tax_year)[:4]))
    except (TypeError, ValueError):
        return None
    for bill in src.get("by_year") or ():
        if not isinstance(bill, dict) or str(bill.get("tax_year") or "")[:4] != year_int:
            continue
        levy = _positive(bill.get("bill_amount"))
        if levy is None:
            continue
        rate = levy / assessed
        if _RATE_MIN <= rate <= _RATE_MAX:
            return rate
    return None


def build_block(detail: dict, raw: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one lrcpwa getParcelDetails response's own
    totalDeferredValue/useValueDeferred, or None when it is blank/zero -- never invented."""
    deferred = _positive(detail.get("totalDeferredValue"))
    if deferred is None:
        deferred = _positive(detail.get("useValueDeferred"))
    if deferred is None:
        return None
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Hyde",
        "state": "NC",
        "source": "lrcpwa.ncptscloud.com getParcelDetails (totalDeferredValue)",
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled
        "match_method": "parcel",
    }
    tax_year = detail.get("taxYear")
    if tax_year:
        rec["tax_year"] = tax_year
    rate = rate_from_ptscloud_bill(raw, detail.get("landUseValue"), tax_year)
    if rate:
        annual = round(deferred * rate, 2)
        rec.update(effective_tax_rate=round(rate, 6), tax_rate_source="nc_ptscloud_delinquent_tax_bill",
                   annual_deferred_tax=annual, estimated_rollback=round(annual * ROLLBACK_YEARS_NC, 2))
    return rec


async def _match_by_pin(tenant: str, pin: str) -> Optional[dict]:
    """The one lrcpwa result whose own formattedPin, stripped to digits, equals `pin` exactly --
    never "closest" or "only result in a loose text search"."""
    results = await _search_parcels(tenant, pin, limit=5)
    for r in results:
        if _digits(r.get("formattedPin")) == pin:
            return r
    return None


async def enrich_hyde_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Look up Hyde NC rows whose parcel_id is already shaped like lrcpwa's own 10-digit PIN,
    confirm an exact PIN match on lrcpwa.ncptscloud.com, and restate a positive deferred value
    into raw['rollback_exposure']. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_HYDE_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_match": 0, "matched": 0,
             "errors": 0, "deferred_found": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(li: Listing) -> None:
        pin = _digits(li.parcel_id)
        async with sem:
            try:
                hit = await _match_by_pin(TENANT, pin)
            except Exception:  # noqa: BLE001 - one lead never kills the pass
                stats["errors"] += 1
                return
            stats["searched"] += 1
            if not hit or not hit.get("id"):
                stats["no_match"] += 1
                return
            try:
                detail = await _get_parcel_detail(TENANT, hit["id"])
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                return
            await asyncio.sleep(0.2)
        if not detail:
            return
        stats["matched"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        block = build_block(detail, raw)
        if not block:
            return
        stats["deferred_found"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[RAW_KEY] = block

    await asyncio.gather(*(one(li) for li in targets))
    log.info("hyde_rollback.done", **stats)
    return stats
