"""Deferred-value / rollback-tax exposure enrichment.

A present-use (farm / forestry / agricultural) or elderly deferral does NOT
forgive tax — it postpones it. The deferred tax sits as a lien and comes DUE
IN FULL the moment the property sells or changes use. That is a hard,
dollar-denominated constraint on any deal we underwrite: the seller's net at
closing is reduced by the rollback, and a seller who does not know the number
walks away from the table when the attorney tells them. The board models
liens, judgments and delinquent tax, but it has never modelled the rollback,
so every deferred parcel on it has been priced as if the sale were clean.

Stamps ``raw['rollback_exposure']`` on any lead whose parcel matches a county
deferral roll:

    {
      "deferred_value": 285500.0,      # assessed value currently deferred
      "annual_deferred_tax": 2034.0,   # deferred value x effective tax rate
      "rollback_years": 4,             # statutory lookback for that state
      "estimated_rollback": 8138.0,    # what comes due on sale (ex-interest)
      "basis": "present_use_deferral",
      "county": "Buncombe", "state": "NC",
      "source": "...", "source_key": "buncombe_bills",
      "tax_year": 2025,
      "match_method": "parcel",
    }

Statutory lookback:
  * NC G.S. 105-277.4(c) — deferred taxes for the FISCAL YEAR IN WHICH the
    disqualification occurs plus the THREE preceding fiscal years become due,
    with interest. -> ``_ROLLBACK_YEARS["NC"] = 4``.
  * SC Code 12-43-220(d)(4) — rollback runs the THREE years preceding the
    change in use (cut from five by 2020 Act 176, effective TY2021).
    -> ``_ROLLBACK_YEARS["SC"] = 3``.
Interest is deliberately NOT modelled: it is rate- and date-dependent and
would be a guess. ``estimated_rollback`` is therefore a FLOOR, and is labelled
as such for the operator.

Sources (free, public, no auth / no CAPTCHA / no robots wall):

  * Buncombe NC — Buncombe_County_All_Property_Bills_from_2025/0
    (204,065 bill rows; 3,627 with deferred_value > 0, 2,380 distinct pins).
    This layer is used INSTEAD of Real_Estate_Appraisal_Tax_History_2024 for
    one decisive reason: the tax-history layer has DeferredValue but no tax
    amount, so any exposure figure off it needs a HARD-CODED millage guess.
    The bills layer carries original_bill_amount AND total_value on the same
    row, so the effective rate is DERIVED PER PARCEL from the county's own
    numbers (median 0.7019 per $100 across matched leads, which is Buncombe's
    real combined rate) and no rate is ever assumed.
    The tax-history layer is kept below as a corroboration/fallback source.
    Its companion ``Exemption`` column is a DEAD FIELD — 0 non-null rows out
    of all 2.89M — so the elderly/exemption half of that layer yields nothing;
    the live elderly signal is Property_2025.Exempt, already pulled as leads
    by the counties_nc.buncombe_elderly scraper.

  * Anderson SC — the assessor's annual rollback books (report AZR012,
    "EDIT LIST OF ALL AG PROPERTY W/CAPPED VALUES"), 2021-2025, published as
    PDFs under /wp-content/uploads/ (robots.txt explicitly Allows that path).
    THESE PDFs HAVE A FULL TEXT LAYER — pdfplumber lifts ~10.9-11.2k rows per
    book cleanly, so NO OCR IS NEEDED and the repo's vision/OCR path is
    deliberately not invoked (it would burn quota for nothing). Each row gives
    tax map, owner, district, acres, market value, use value, millage, and a
    precomputed rollback tax per acre; annual rollback = per-acre x acres,
    which reproduces (market_value - use_value) x 0.06 x millage exactly.

Both sources load ONCE into memory and are matched locally, so this costs a
handful of paginated GETs plus (optionally) one PDF download per book.
Anderson PDF parsing is OFF by default (``ROLLBACK_ANDERSON=1`` to enable)
and capped at ``ROLLBACK_ANDERSON_BOOKS`` books, because a 200-page pdfplumber
parse is CPU-bound and the full-run has been bitten by unbounded enrichers
before. Kill switch for the whole module: ``FORECLOSURE_ROLLBACK_OFF=1``.
"""
from __future__ import annotations

import io
import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .http_client import client
from .models import Listing, _normalize_parcel

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_ROLLBACK_OFF"

# Statutory rollback lookback, in tax years, by state (see module docstring).
_ROLLBACK_YEARS = {"NC": 4, "SC": 3}

# ---- Buncombe NC -----------------------------------------------------------

BUNCOMBE_BILLS_URL = (
    "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
    "Buncombe_County_All_Property_Bills_from_2025/FeatureServer/0/query"
)
# Enumerated explicitly. The layer also carries owner names, mailing address,
# mortgage company and loan_num; none of those are requested here.
BUNCOMBE_BILLS_FIELDS = (
    "pin,bill,deferred_value,total_value,original_bill_amount,levy_due,levy_year"
)

# A parcel carries SEVERAL bill rows: the current-year county/municipal/fire
# levy, plus (for parcels already disqualified) one row per prior deferred year.
# The bill number encodes the tax year in its third dash-segment —
# '0000742141-2025-2021-0070-00' is levy year 2025, TAX year 2021.
_BILL_YEAR_RE = re.compile(r"^[^-]*-(?P<levy>\d{4})-(?P<tax>\d{4})-")

# Sane band for a derived NC combined rate, expressed as a fraction of value
# (0.30-1.60 per $100). Buncombe's real combined rates land 0.63-0.99; the
# tails outside this band are partial-district or fee-only bill rows whose
# ratio is not a tax rate at all. Anything outside falls back to the median
# rate DERIVED FROM THIS SAME PULL — no millage is ever hard-coded.
_RATE_MIN, _RATE_MAX = 0.0030, 0.0160
BUNCOMBE_BILLS_WHERE = (
    "deferred_value IS NOT NULL AND deferred_value<>'' AND deferred_value<>'0'"
)

# Corroboration / fallback only: DeferredValue with no tax amount on the row.
BUNCOMBE_TAXHIST_URL = (
    "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
    "Real_Estate_Appraisal_Tax_History_2024/FeatureServer/0/query"
)

# ---- Anderson SC -----------------------------------------------------------

ANDERSON_BASE = "https://www.andersoncountysc.org/wp-content/uploads/"
# (tax_year, path). 2024's book is published under the AG-PROPERTY-LISTING
# name but is the same AZR012 report — verified identical layout + millage.
ANDERSON_BOOKS: tuple[tuple[int, str], ...] = (
    (2025, "2026/01/2025-Rollbacks.pdf"),
    (2024, "2025/02/AG-PROPERTY-LISTING-2024.pdf"),
    (2023, "2023/11/2023-Rollback-Book.pdf"),
    (2022, "2023/03/2022-Rollback-Book.pdf"),
    (2021, "2023/03/2021-Rollback-Book.pdf"),
)

# 002-00-01-002 ROSE SARAH FRANKUM 004 13.91 63,990 1,530 .32807 89.10
# Sub-acre rows print acreage with no leading zero (".85"), hence [\d,]* .
ANDERSON_ROW_RE = re.compile(
    r"^(?P<tms>\d{3}-\d{2}-\d{2}-\d{3})\s+"
    r"(?P<owner>.+?)\s+"
    r"(?P<district>\d{3})\s+"
    r"(?P<acres>[\d,]*\.\d+)\s+"
    r"(?P<market>[\d,]+)\s+"
    r"(?P<use>[\d,]+)\s+"
    r"(?P<millage>\.\d+)\s+"
    r"(?P<per_acre>[\d,]+\.\d+)\s*$"
)

_ANDERSON_ON = os.environ.get("ROLLBACK_ANDERSON", "0") == "1"
_ANDERSON_MAX_BOOKS = int(os.environ.get("ROLLBACK_ANDERSON_BOOKS", "1"))
_MAX_PDF_BYTES = 20 * 1024 * 1024


def _to_float(v: Any) -> Optional[float]:
    """Parse a money/number that may arrive as a string with , or $."""
    if v in (None, "", " ", "<Null>"):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f


def _positive(v: Any) -> Optional[float]:
    f = _to_float(v)
    return f if f is not None and f > 0 else None


# ---- Buncombe fetch --------------------------------------------------------


def _bill_years(bill: Any) -> tuple[Optional[int], Optional[int]]:
    m = _BILL_YEAR_RE.match(str(bill or ""))
    if not m:
        return None, None
    return int(m.group("levy")), int(m.group("tax"))


async def _fetch_buncombe(c: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    """Page the Buncombe bills layer and index deferred parcels by PIN.

    Returns {normalized_pin: record}. Grouping matters: a parcel carries one
    bill row per taxing unit (county / municipality / fire district) and, once
    it has been disqualified, one more per prior deferred year. We dedupe by
    bill number, pick the current-year row with the LARGEST effective rate as
    that parcel's combined rate, and separately surface any prior-year rows —
    those are a rollback the county has ALREADY BILLED, which is a hard fact
    rather than an estimate.
    """
    rows = await _fetch_buncombe_rows(c)
    if not rows:
        return {}

    by_pin: dict[str, dict[str, dict[str, Any]]] = {}
    for a in rows:
        pin = _normalize_parcel(a.get("pin"))
        if not pin or _positive(a.get("deferred_value")) is None:
            continue
        # Dedupe: the layer repeats identical bill rows.
        by_pin.setdefault(pin, {})[str(a.get("bill") or id(a))] = a

    # County-level fallback rate, derived from this same pull.
    per_pin_rate: dict[str, Optional[float]] = {}
    for pin, bills in by_pin.items():
        per_pin_rate[pin] = _pick_rate(bills.values())
    sane = sorted(r for r in per_pin_rate.values()
                  if r is not None and _RATE_MIN <= r <= _RATE_MAX)
    median_rate = sane[len(sane) // 2] if sane else None
    log.info("rollback.buncombe_rate", median_per_100=round((median_rate or 0) * 100, 4),
             pins_with_sane_rate=len(sane), pins=len(by_pin))

    out: dict[str, dict[str, Any]] = {}
    for pin, bills in by_pin.items():
        rate, rate_source = per_pin_rate[pin], "parcel_bill"
        if rate is None or not (_RATE_MIN <= rate <= _RATE_MAX):
            rate, rate_source = median_rate, "county_median"
        out[pin] = _buncombe_record(bills.values(), rate, rate_source)
    return out


def _pick_rate(bills: Iterable[dict[str, Any]]) -> Optional[float]:
    """Effective rate for a parcel = the largest current-levy-year bill ratio.

    The biggest current-year row is the full county+municipal+fire levy; the
    smaller siblings are single-district slices that would understate the
    rollback badly (0.10 per $100 instead of 0.70).
    """
    best: Optional[float] = None
    fallback: Optional[float] = None
    for a in bills:
        tv = _positive(a.get("total_value"))
        amt = _positive(a.get("original_bill_amount")) or _positive(a.get("levy_due"))
        if not tv or not amt:
            continue
        rate = amt / tv
        levy, tax = _bill_years(a.get("bill"))
        if levy is not None and tax is not None and levy == tax:
            if best is None or rate > best:
                best = rate
        elif fallback is None or rate > fallback:
            fallback = rate
    return best if best is not None else fallback


async def _fetch_buncombe_rows(c: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Page every deferred-value bill row out of the Buncombe bills layer."""
    out: list[dict[str, Any]] = []
    offset, page = 0, 2000
    while True:
        params = {
            "where": BUNCOMBE_BILLS_WHERE,
            "outFields": BUNCOMBE_BILLS_FIELDS,
            "returnGeometry": "false",
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        try:
            r = await c.get(BUNCOMBE_BILLS_URL, params=params, timeout=60.0)
            if r.status_code != 200:
                log.warning("rollback.buncombe_status", code=r.status_code)
                break
            data = r.json()
            if "error" in data:
                log.warning("rollback.buncombe_error", error=str(data.get("error"))[:200])
                break
            feats = data.get("features", [])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("rollback.buncombe_fail", error=str(exc)[:200])
            break

        out.extend(ft.get("attributes", {}) or {} for ft in feats)

        if len(feats) < page or not data.get("exceededTransferLimit"):
            break
        offset += page
        if offset >= 60000:      # safety cap
            log.warning("rollback.buncombe_cap", offset=offset)
            break
    return out


def _buncombe_record(bills: Iterable[dict[str, Any]], rate: Optional[float],
                     rate_source: str) -> dict[str, Any]:
    """Build one exposure record from a parcel's deduped Buncombe bill rows.

    ``rate`` is never a hard-coded millage: it is either this parcel's own
    original_bill_amount / total_value (for a deferred parcel total_value IS
    the use-value taxable base the bill was struck on, so the ratio is the
    real combined county+municipal+fire rate) or, when that ratio is not a
    plausible tax rate, the median of every other deferred parcel in the same
    pull.
    """
    bills = list(bills)
    deferred = max((_positive(a.get("deferred_value")) or 0.0) for a in bills)
    years = _ROLLBACK_YEARS["NC"]
    annual = round(deferred * rate, 2) if (rate and deferred) else None

    # Prior-tax-year rows on a 2025 levy are rollback the county has already
    # billed — a fact, not a projection.
    billed = 0.0
    billed_years: list[int] = []
    for a in bills:
        levy, tax = _bill_years(a.get("bill"))
        if levy is not None and tax is not None and tax < levy:
            billed += _positive(a.get("original_bill_amount")) or 0.0
            billed_years.append(tax)

    rec: dict[str, Any] = {
        "deferred_value": deferred,
        "effective_tax_rate": round(rate, 6) if rate else None,
        "tax_rate_source": rate_source,
        "annual_deferred_tax": annual,
        "rollback_years": years,
        "estimated_rollback": round(annual * years, 2) if annual else None,
        "estimate_is_floor": True,      # statutory interest not modelled
        "basis": "present_use_deferral",
        "county": "Buncombe",
        "state": "NC",
        "source": "Buncombe County All Property Bills 2025 (deferred_value)",
        "source_key": "buncombe_bills",
        "bill_rows": len(bills),
    }
    if billed > 0:
        rec["rollback_already_billed"] = round(billed, 2)
        rec["rollback_billed_years"] = sorted(set(billed_years))
    ty = _to_float(next((a.get("levy_year") for a in bills if a.get("levy_year")), None))
    if ty:
        rec["tax_year"] = int(ty)
    return rec


# ---- Anderson fetch --------------------------------------------------------


def parse_anderson_book(data: bytes, tax_year: int) -> list[dict[str, Any]]:
    """Parse one Anderson AZR012 rollback book PDF into exposure rows.

    Text-layer only (pdfplumber) — these books are digitally generated, so no
    OCR is required. Rows the report prints malformed (a missing market value,
    or a per-acre figure overflowed to ``*********``) simply don't match and
    are skipped; that is ~0.2-1.5% of tax-map lines per book.
    """
    try:
        import pdfplumber
    except ImportError:       # pragma: no cover - dependency is pinned
        log.warning("rollback.anderson_no_pdfplumber")
        return []

    rows: list[dict[str, Any]] = []
    years = _ROLLBACK_YEARS["SC"]
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").splitlines():
                    m = ANDERSON_ROW_RE.match(line.strip())
                    if not m:
                        continue
                    g = m.groupdict()
                    acres = _to_float(g["acres"])
                    per_acre = _to_float(g["per_acre"])
                    market = _to_float(g["market"])
                    use = _to_float(g["use"])
                    if not acres or per_acre is None:
                        continue
                    annual = round(per_acre * acres, 2)
                    rows.append({
                        "tms": g["tms"],
                        "deferred_value": (round(market - use, 2)
                                           if market is not None and use is not None
                                           else None),
                        "market_value": market,
                        "use_value": use,
                        "acres": acres,
                        "millage": _to_float(g["millage"]),
                        "rollback_tax_per_acre": per_acre,
                        "annual_deferred_tax": annual,
                        "rollback_years": years,
                        "estimated_rollback": round(annual * years, 2),
                        "estimate_is_floor": True,
                        "basis": "agricultural_use_deferral",
                        "county": "Anderson",
                        "state": "SC",
                        "source": f"Anderson County Assessor {tax_year} Rollback Book (AZR012)",
                        "source_key": "anderson_rollback_book",
                        "tax_year": tax_year,
                    })
    except Exception as exc:  # noqa: BLE001 - pdfplumber raises broadly
        log.warning("rollback.anderson_parse_fail", year=tax_year, error=str(exc)[:200])
        return []
    return rows


def _anderson_key(tms: str) -> str:
    """Anderson TMS -> board parcel key.

    The books print '002-00-01-002'; the board carries the same map stripped
    of punctuation AND of its leading zero ('930802014' for '093-08-02-014'),
    so both sides are normalized then left-padded to 10 digits.
    """
    k = _normalize_parcel(tms)
    return k.zfill(10) if k and k.isdigit() and len(k) <= 10 else k


async def _fetch_anderson(c: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    """Download + parse the most recent N Anderson rollback books."""
    out: dict[str, dict[str, Any]] = {}
    for tax_year, path in ANDERSON_BOOKS[:max(0, _ANDERSON_MAX_BOOKS)]:
        url = ANDERSON_BASE + path
        try:
            r = await c.get(url, timeout=120.0)
            if r.status_code != 200:
                log.warning("rollback.anderson_status", year=tax_year, code=r.status_code)
                continue
            data = r.content
        except httpx.HTTPError as exc:
            log.warning("rollback.anderson_fail", year=tax_year, error=str(exc)[:200])
            continue
        if not data or len(data) > _MAX_PDF_BYTES:
            log.warning("rollback.anderson_size", year=tax_year, bytes=len(data or b""))
            continue
        rows = parse_anderson_book(data, tax_year)
        log.info("rollback.anderson_book", year=tax_year, rows=len(rows))
        for rec in rows:
            # Newest book wins; ANDERSON_BOOKS is newest-first.
            out.setdefault(_anderson_key(rec["tms"]), rec)
    return out


# ---- matching --------------------------------------------------------------


def _county_of(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _lead_keys(li: Listing) -> list[str]:
    """Normalized parcel keys to try for a lead, widest-safe first."""
    k = _normalize_parcel(li.parcel_id)
    if not k:
        return []
    keys = [k]
    if k.isdigit() and len(k) < 10:
        keys.append(k.zfill(10))
    return keys


async def enrich_with_rollback_exposure(listings: Iterable[Listing]) -> dict[str, int]:
    """Stamp raw['rollback_exposure'] on leads sitting on a deferred parcel."""
    stats = {"targets": 0, "matched": 0, "matched_buncombe": 0,
             "matched_anderson": 0, "with_estimate": 0}
    if os.environ.get(ENV_OFF):
        return stats
    leads = [li for li in listings]
    if not leads:
        return stats

    want_buncombe = any(
        _county_of(li) == "buncombe" and (li.state or "").upper() == "NC" for li in leads
    )
    want_anderson = _ANDERSON_ON and any(
        _county_of(li) == "anderson" and (li.state or "").upper() == "SC" for li in leads
    )
    if not want_buncombe and not want_anderson:
        log.info("rollback.no_relevant_counties")
        return stats

    buncombe: dict[str, dict[str, Any]] = {}
    anderson: dict[str, dict[str, Any]] = {}
    async with client(timeout=60.0) as c:
        if want_buncombe:
            buncombe = await _fetch_buncombe(c)
            log.info("rollback.buncombe_loaded", parcels=len(buncombe))
        if want_anderson:
            anderson = await _fetch_anderson(c)
            log.info("rollback.anderson_loaded", parcels=len(anderson))

    if not buncombe and not anderson:
        return stats

    for li in leads:
        county, state = _county_of(li), (li.state or "").upper()
        if county == "buncombe" and state == "NC":
            idx, bucket = buncombe, "matched_buncombe"
        elif county == "anderson" and state == "SC":
            idx, bucket = anderson, "matched_anderson"
        else:
            continue
        if not idx:
            continue
        stats["targets"] += 1

        rec = None
        for k in _lead_keys(li):
            rec = idx.get(k)
            if rec:
                break
        if rec is None:
            continue

        payload = dict(rec)
        payload["match_method"] = "parcel"
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rollback_exposure"] = payload
        stats["matched"] += 1
        stats[bucket] += 1
        if payload.get("estimated_rollback"):
            stats["with_estimate"] += 1

    log.info("rollback.done", **stats)
    return stats
