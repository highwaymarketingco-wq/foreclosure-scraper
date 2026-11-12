"""Greenville County SC Treasurer "Property Tax Search" -> per-parcel multi-year tax BILL
HISTORY. Fills the two columns gap_matrix.py flags "sourced-not-built" for Greenville SC
(multi_year_delinquent_tax, tax_aging_surfaced) — 5,547 est rows across both, per the
2026-11-05 gap sweep that sent this investigation.

WHY THIS EXISTS AND WHAT WAS ALREADY THERE (checked before writing a line here). Greenville
    already has THREE unrelated AS/400-backed web apps, easy to conflate:
      1. `scrapers/counties_sc/greenville_delinquent_tax.py` -- the Tax SALE roster
         (`/appsAS400/Taxsale/`), a LEAD SOURCE. One row per parcel, ONE current total-due
         figure, no per-year breakdown. Its own docstring documents the Map# detail link on
         THAT page (`/appsas400/RealProperty/Details.aspx?TaxYear=...&MapNumber=...`) as
         CONFIRMED BROKEN (hangs / "Tax Year or Map Number cannot be blank!", three
         independent access paths, audited 2026-10-03) -- a dead end, but a DIFFERENT app
         from the one this module uses.
      2. `assessor_cards/greenville_sc.py` -- the ASSESSOR'S RealProperty card (same host,
         same `/appsas400/RealProperty/Details.aspx`, reordered query params), PRICE-ONLY
         (sale price, FMV, deed book/page). Appraisal side, not tax-collection side.
      3. `verification/verifiers/tax_lien_greenville.py` -- a tax_lien VERIFIER that already
         reads the RIGHT page (`/appsas400/votaxqry/RealTaxesResults.aspx`) and already
         proved it live (2026-10-09). But a verifier's VerificationResult lives in the
         verification ledger (SIGNAL="tax_lien"), a separate system from the per-row
         `raw[...]` dict gap_matrix.checked_columns() actually reads for multi_year_
         delinquent_tax / tax_aging_surfaced (scripts/gap_matrix.py lines ~1193-1207: both
         columns are credited ONLY from `raw.get("multi_year_delinquent_tax")` /
         `raw.get("tax_aging_surfaced")` directly on the Listing -- the tax_lien ledger
         verdict never reaches those keys). Also confirmed in enrichment_tax_owed.py's own
         comment (Pass B, ~line 210): a Greenville parcel's `raw["greenville_delinquent_tax"]
         ["total_due"]` DOES already promote into raw['tax_owed']['balance'] generically, but
         with year=None every time (that roster block carries no year field at all) -- so
         raw['tax_owed'] alone can never clear enrichment_tax_aging.py's trigger
         (`to_year is not None or isinstance(to.get("years_delinquent"), (int, float))`) for
         Greenville's existing sources. Neither existing Greenville source (the roster, or
         the ArcGIS `greenville_unpaid_tax_parcels` layer, TOTTAX/ACCTNO -- a single current
         total, same shape) carries a usable per-year history already sitting unused (unlike
         the Transylvania/PTS-Cloud "pure bridge" cases) -- a genuine NEW network fetch is
         required, which is what this module is.

THE REAL SOURCE (live-verified 2026-11-05, both the UI and the GET shortcut):
    https://www.greenvillecounty.org/appsas400/votaxqry/  -- "PROPERTY TAX SEARCH", three
    tabs (Vehicles / Real Estate / Other), no disclaimer gate, no login, no CAPTCHA. The
    Real Estate tab's own form is an ASP.NET `__doPostBack`, but the RESULTS page has a
    plain GET shortcut (same one tax_lien_greenville.py already uses) that skips the
    postback/viewstate dance entirely:
        GET /appsas400/votaxqry/RealTaxesResults.aspx?SearchType=MapNumber&Criteria=<13-char map#>
    Confirmed live against 5 real map numbers (3 pulled fresh off the live Taxsale roster,
    2 pulled fresh off the live ArcGIS `greenville_unpaid_tax_parcels` layer with
    `PAIDDATE IS NULL`, i.e. genuinely-unpaid-right-now parcels, not roster leftovers):
    one `<span id="...lbl_Count">N</span>` and one `<tr>` per BILL YEAR, going back as far
    as 1995-1999 on every parcel tested (far deeper than the verifier's "back to 2009" note
    -- that was this county's own stated floor, not a hard limit). Seven `<td>` cells per
    row, parsed by POSITION (ids vary): 0 owner (bold span) + receipt "YYYY NNNNNNNNN NN NNN"
    + a red status div ("SOLD AT TAX SALE" / "BANKRUPT..." / blank); 1 map#, SID; 2 permit#,
    district; 3 exemption, delinquent "D" mark; 4 assessment value, Date Paid; 5 base amount,
    amount paid; 6 balance due (blank/zero when paid in full).

A MEASURED CAVEAT, NOT A GUESS (read before trusting a rosy "multi_year_delinquent_tax will
    be huge" assumption). Of the 5 live parcels read, the 3 pulled off the CURRENT Taxsale
    roster (already swept into a completed sale) showed BALANCE DUE BLANK/ZERO on every one
    of their 28-31 years, including the sale year itself (status "SOLD AT TAX SALE", base
    amount == amount paid) -- the county's own bookkeeping treats the BASE TAX BILL as
    settled by the sale proceeds; what the former owner still owes to redeem is a separate
    figure this page does not carry. The 2 parcels pulled fresh off the ArcGIS
    `PAIDDATE IS NULL` layer (genuinely unpaid as of today, not yet swept into a sale) DID
    show a real nonzero Balance Due -- but in BOTH cases only for the single newest (2025)
    year; every prior year back to 2012-2016 was marked "D" (late) yet fully paid before the
    next year's bill came due. So the strict multi_year_delinquent_tax CONTRACT (>=2 distinct
    years with a balance CURRENTLY > 0) will clear RARELY for Greenville specifically --
    honest, measured, not a bug in this module -- while the "D" flag's multi-year LATENESS
    history is deep and reliable on nearly every parcel tested. This module therefore builds
    TWO independent things from the one fetch, each gated on its own honest evidence:
      (a) raw['tax_owed'] -- current genuinely-owed balance (sum of this run's balance-due>0
          bills) + years_delinquent (count of those same matured, currently-owed years).
          Written whenever at least one bill is currently owed. This is what
          enrichment_tax_aging.py (tax_aging_surfaced's one, county-unrestricted producer,
          already wired every pipeline run) reads -- so wiring this module is enough to
          surface tax_aging_surfaced for Greenville; no second change needed there.
      (b) raw['multi_year_delinquent_tax'] -- written ONLY when (a)'s matured, currently-owed
          years are >= MIN_YEARS (2, same gate enrichment_ptscloud_multiyear_tax.py and the
          Buncombe/Oconee/Pickens producer both already use), in the exact byte-shape those
          two producers emit (years/per_year/years_delinquent/matured_years/trend/...) so a
          downstream reader sees one consistent contract regardless of which producer filled
          it. Expected to be the RARER of the two outputs for this county, for the structural
          reason above, not an implementation gap.

JOIN KEY = the portal's own 13-character Map #, matched against `li.parcel_id` (every
    Greenville source in this codebase already stores parcel_id in this exact format --
    greenville_delinquent_tax.py's Map#, the assessor card's MapNumber, the ArcGIS layer's
    PIN) and, as a second candidate, `raw['greenville_delinquent_tax']['map_number']` when
    present (the roster's own claimed map#, for a row a merge later re-keyed under a
    different primary parcel_id -- same "claim first, board second" idea
    tax_lien_greenville.py's own `subjects()` already uses, reimplemented here rather than
    imported so this file has no dependency on the verification subpackage).

NOT WALLED. No login, no CAPTCHA, no disclaimer click-through, no rate-limiting observed
    across the live probes this investigation made. The only confirmed dead end anywhere in
    this neighborhood is the DIFFERENT `/appsas400/RealProperty/Details.aspx` app (assessor
    detail-page deep link), already documented in greenville_delinquent_tax.py -- not reused
    or re-attempted here.

Gate OFF by default (network cost, one request per parcel): GREENVILLE_TAX=1.
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
import time
from datetime import date, datetime
from typing import Any, Iterable, Optional

import httpx
import structlog

from . import tax_calendar
from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

SOURCE_KEY = "greenville_tax_history"
TAX_OWED_SOURCE = "greenville_votaxqry"
MYDT_LAYER = "greenville_votaxqry_bill_history"

BASE_URL = "https://www.greenvillecounty.org/appsas400/votaxqry/RealTaxesResults.aspx"

_ENABLED = os.environ.get("GREENVILLE_TAX") == "1"
_MAX_QUERIES = int(os.environ.get("GREENVILLE_TAX_MAX_QUERIES", "1500"))
_MAX_SECONDS = float(os.environ.get("GREENVILLE_TAX_MAX_SECONDS", "1200"))
_QUERY_TIMEOUT_S = float(os.environ.get("GREENVILLE_TAX_QUERY_TIMEOUT_S", "25"))
_BREAKER_FAILS = int(os.environ.get("GREENVILLE_TAX_BREAKER_FAILS", "8"))
_CONCURRENCY = int(os.environ.get("GREENVILLE_TAX_CONCURRENCY", "3"))
MIN_YEARS = int(os.environ.get("GREENVILLE_TAX_MIN_YEARS", "2"))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

COUNTY = ("SC", "Greenville")

# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_COUNT_RE = re.compile(r'lbl_Count"[^>]*>\s*(\d+)', re.I)
_TBODY_RE = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.I | re.S)
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
_DIV_RE = re.compile(r"<div\b[^>]*>(.*?)</div>", re.I | re.S)
_SPAN_RE = re.compile(r"<span\b[^>]*>(.*?)</span>", re.I | re.S)
_TAXYEAR_RE = re.compile(r"TaxYear=((?:19|20)\d{2})", re.I)
_RECEIPT_RE = re.compile(r"\b((?:19|20)\d{2})\s+\d{6,}\s+\d{2}\s+\d{3}\b")
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})")


def _text(s: Any) -> str:
    # Strip tags, THEN decode entities (&nbsp; etc.) before collapsing whitespace -- a raw
    # "D&nbsp;" cell (the live delinquent-flag marker) must become "D", not "D&NBSP;". Found
    # live 2026-11-05: every delinquent-flag cell on the real portal uses &nbsp; padding, so
    # skipping unescape here silently made late_flag/sold_at_tax_sale detection always False.
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", str(s or "")))).strip()


def _money(s: Any) -> Optional[float]:
    t = re.sub(r"[^\d.]", "", str(s or ""))
    if not t or t == ".":
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 0 else None


def _paid_date(s: Any) -> Optional[str]:
    m = _DATE_RE.search(str(s or ""))
    if not m:
        return None
    mm, dd, yy = m.groups()
    return f"{yy}-{int(mm):02d}-{int(dd):02d}"


def map_number(value: Any) -> Optional[str]:
    """Normalize a candidate to the portal's 13-character Map #, or None.

    Same shape rule tax_lien_greenville.map_number() already validates against this exact
    site (13 chars after stripping non-alnum, at least 6 digits present, not all zero) --
    reimplemented here (not imported) so this module has no dependency on the verification
    subpackage, per this task's own "write your own standalone file" instruction.
    """
    k = re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()
    if len(k) != 13 or set(k) <= {"0"} or not re.search(r"\d{6}", k):
        return None
    return k


def candidate_map_numbers(li: Listing) -> list[str]:
    """[map#, ...], deduped: the roster's own claimed map# first (when present on a merged
    row), then the board's own parcel_id -- same "claim first, board second" idea
    tax_lien_greenville.subjects() already uses for this identical site."""
    out: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    roll = raw.get("greenville_delinquent_tax")
    if isinstance(roll, dict):
        m = map_number(roll.get("map_number"))
        if m and m not in out:
            out.append(m)
    m = map_number(li.parcel_id)
    if m and m not in out:
        out.append(m)
    return out


def parse_results(html: str) -> dict:
    """{"count": int | None, "bills": [{year, owner, receipt, billed, paid, owed, paid_on,
    late_flag, sold_at_tax_sale, bankruptcy}]} from a live RealTaxesResults.aspx page.
    Pure; never raises on malformed input (returns an empty bill list)."""
    out: dict[str, Any] = {"count": None, "bills": []}
    cm = _COUNT_RE.search(html or "")
    if cm:
        out["count"] = int(cm.group(1))
    body = _TBODY_RE.search(html or "")
    if not body:
        return out
    for tr in _TR_RE.findall(body.group(1)):
        tds = _TD_RE.findall(tr)
        if len(tds) < 7:
            continue
        # cell 0: owner (bold span) + receipt text (carries the year) + red status div
        span0 = _SPAN_RE.search(tds[0])
        owner = _text(span0.group(1)) if span0 else None
        ym = _TAXYEAR_RE.search(tds[0]) or _RECEIPT_RE.search(_text(tds[0]))
        year = int(ym.group(1)) if ym else None
        if year is None:
            continue
        status_divs = _DIV_RE.findall(tds[0])
        status_text = _text(status_divs[-1]) if status_divs else ""
        status_upper = status_text.upper()
        receipt_m = _RECEIPT_RE.search(_text(tds[0]))

        # cell 3: exemption / delinquent "D" mark
        delq_divs = [_text(d) for d in _DIV_RE.findall(tds[3])]
        late_flag = any(d.strip().upper() == "D" for d in delq_divs)

        # cell 4: assessment value / date paid
        assess_divs = _DIV_RE.findall(tds[4])
        paid_on = _paid_date(assess_divs[1]) if len(assess_divs) > 1 else None

        # cell 5: base amount / amount paid
        amt_divs = _DIV_RE.findall(tds[5])
        billed = _money(amt_divs[0]) if amt_divs else None
        paid = _money(amt_divs[1]) if len(amt_divs) > 1 else None

        # cell 6: balance due (blank/zero once paid in full)
        owed = _money(_text(tds[6])) or 0.0

        out["bills"].append({
            "year": year,
            "owner": owner,
            "receipt": receipt_m.group(0) if receipt_m else None,
            "billed": billed,
            "paid": paid,
            "owed": round(owed, 2),
            "paid_on": paid_on,
            "late_flag": late_flag,
            "sold_at_tax_sale": "SALE" in status_upper or "SOLD" in status_upper,
            "bankruptcy": "BANKRUPT" in status_upper,
        })
    return out


def _matured_owed_years(bills: list[dict], state: Optional[str], county: Optional[str],
                         today: date) -> tuple[list[int], dict[int, float]]:
    """(matured years with a currently-owed balance, {year: owed}) from a parsed bill list.
    A year appearing twice (a corrected/supplemental bill) keeps the LARGER owed amount,
    mirroring scrapers.counties_generic.multi_year_delinquent_tax.build_listing's own
    documented reasoning for the identical case."""
    per_year: dict[int, float] = {}
    for b in bills:
        yr = tax_calendar.levy_year(b.get("year"))
        amt = b.get("owed")
        if yr is None or not isinstance(amt, (int, float)) or amt <= 0:
            continue
        prev = per_year.get(yr)
        per_year[yr] = amt if prev is None else max(prev, amt)
    if not per_year:
        return [], {}
    matured = tax_calendar.completed_delinquent_years(sorted(per_year), state, county, today)
    return sorted(matured), per_year


def build_tax_owed_block(bills: list[dict], map_no: str, state: Optional[str],
                          county: Optional[str], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the canonical raw['tax_owed'] block (balance/kind/source/basis/years/year/
    years_delinquent), or None when nothing on this parcel is currently owed. Only MATURED
    years count toward years_delinquent (a brand-new not-yet-due current bill is not late)."""
    today = today or date.today()
    matured, per_year = _matured_owed_years(bills, state, county, today)
    owed_years = sorted(y for y, amt in per_year.items() if amt > 0)
    if not owed_years:
        return None
    balance = round(sum(per_year[y] for y in owed_years), 2)
    return {
        "balance": balance,
        "kind": "delinquent_tax",
        "source": f"{TAX_OWED_SOURCE}:{map_no}",
        "basis": "own_record",
        "years": [str(y) for y in owed_years],
        "year": owed_years[-1],
        "years_delinquent": len(matured),
        "status": "sold_at_tax_sale" if any(
            b["sold_at_tax_sale"] for b in bills if tax_calendar.levy_year(b.get("year")) in owed_years
        ) else "unpaid",
    }


def build_multi_year_block(bills: list[dict], map_no: str, state: Optional[str],
                            county: Optional[str], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block in the exact shape
    enrichment_ptscloud_multiyear_tax.build_block() / the Buncombe-Oconee-Pickens producer
    both already emit, or None when fewer than MIN_YEARS matured years are currently owed.
    Structurally expected to be the rarer of this module's two outputs for Greenville --
    see the module docstring's measured caveat."""
    today = today or date.today()
    matured, per_year = _matured_owed_years(bills, state, county, today)
    years = sorted(per_year)
    if len(matured) < MIN_YEARS:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    return {
        "years": years,
        "per_year": {str(y): per_year[y] for y in years},
        "years_delinquent": len(matured),
        "unpaid_bill_years": len(years),
        "matured_years": matured,
        "matured_years_delinquent": len(matured),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "county_latest_year": years[-1],
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": total_owed,
        "total_owed": total_owed,
        "matured_owed": matured_owed,
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": True,
        "amount_basis": "balance_due",
        "layers": [MYDT_LAYER],
        "parcel_key": _normalize_parcel(map_no),
        "tenant": "Greenville",
        "source_url": search_url(map_no),
    }


def search_url(map_no: str) -> str:
    return f"{BASE_URL}?SearchType=MapNumber&Criteria={map_no}"


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

async def fetch_bill_history(client: httpx.AsyncClient, map_no: str) -> dict:
    """GET + parse one parcel's full bill history. httpx first; curl_cffi (Chrome
    impersonation), imported locally, only if httpx comes back blocked/403/empty."""
    url = search_url(map_no)
    try:
        r = await client.get(url)
        if r.status_code == 200 and r.text:
            parsed = parse_results(r.text)
            if parsed["count"] is not None:
                return parsed
    except Exception:  # noqa: BLE001
        pass

    from curl_cffi.requests import AsyncSession  # local import: keep dep optional, fallback-only

    async with AsyncSession() as s:
        r = await s.get(url, impersonate="chrome", timeout=_QUERY_TIMEOUT_S,
                         headers={"User-Agent": _UA})
        if r.status_code != 200:
            raise RuntimeError(f"curl_cffi fallback got HTTP {r.status_code}")
        parsed = parse_results(r.text)
        if parsed["count"] is None:
            raise RuntimeError("not a results page (curl_cffi fallback)")
        return parsed


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def _already_done(li: Listing) -> bool:
    return isinstance(li.raw, dict) and isinstance(li.raw.get(SOURCE_KEY), dict)


def _is_greenville_sc(li: Listing) -> bool:
    county_bare = (li.county or "").replace(" County", "").strip()
    return (li.state, county_bare) == COUNTY


async def enrich_greenville_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every Greenville SC listing with a resolvable 13-char Map #, fetch its full tax
    bill history from the county Treasurer's live Property Tax Search, and write:
      raw['greenville_tax_history']   -- always, when the portal returns >=1 bill (audit trail)
      raw['tax_owed']                 -- when >=1 bill is currently owed (feeds
                                          enrichment_tax_aging.py -> tax_aging_surfaced)
      raw['multi_year_delinquent_tax']-- when >=MIN_YEARS matured years are currently owed
    Gated off by default (GREENVILLE_TAX=1), bounded by a query budget, a per-query timeout,
    and a consecutive-failure circuit breaker (same shape as enrichment_qpaybill_tax.py).
    """
    stats = {"targets": 0, "queries": 0, "found": 0, "not_found": 0, "errors": 0,
              "tax_owed_filled": 0, "multi_year_filled": 0}
    if not _ENABLED:
        return stats

    today = date.today()
    targets: list[tuple[Listing, str]] = []
    for li in listings:
        if not _is_greenville_sc(li) or _already_done(li):
            continue
        cands = candidate_map_numbers(li)
        if not cands:
            continue
        targets.append((li, cands[0]))
    stats["targets"] = len(targets)
    targets = targets[:_MAX_QUERIES]
    if not targets:
        return stats

    log.info("greenville_tax.start", targets=stats["targets"], queued=len(targets))
    sem = asyncio.Semaphore(_CONCURRENCY)
    state = {"consec_fail": 0, "deadline": time.monotonic() + _MAX_SECONDS, "tripped": False}

    async with httpx.AsyncClient(timeout=_QUERY_TIMEOUT_S, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        async def one(li: Listing, map_no: str) -> None:
            if state["tripped"] or time.monotonic() > state["deadline"]:
                return
            async with sem:
                if state["tripped"] or time.monotonic() > state["deadline"]:
                    return
                try:
                    parsed = await asyncio.wait_for(fetch_bill_history(client, map_no),
                                                     timeout=_QUERY_TIMEOUT_S)
                    stats["queries"] += 1
                    state["consec_fail"] = 0
                except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
                    stats["errors"] += 1
                    state["consec_fail"] += 1
                    if _BREAKER_FAILS and state["consec_fail"] >= _BREAKER_FAILS:
                        state["tripped"] = True
                        log.warning("greenville_tax.circuit_open", queries=stats["queries"],
                                    last_error=f"{type(exc).__name__}: {str(exc)[:160]}")
                    return

                bills = parsed.get("bills") or []
                if not bills:
                    stats["not_found"] += 1
                    return
                stats["found"] += 1
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw[SOURCE_KEY] = {
                    "map_number": map_no,
                    "results_found": parsed.get("count"),
                    "bills": bills,
                    "source_url": search_url(map_no),
                    "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }

                to_block = build_tax_owed_block(bills, map_no, li.state, li.county, today=today)
                if to_block and not (li.raw.get("tax_owed") or {}).get("balance"):
                    li.raw["tax_owed"] = to_block
                    stats["tax_owed_filled"] += 1

                mydt_block = build_multi_year_block(bills, map_no, li.state, li.county, today=today)
                if mydt_block and not isinstance(li.raw.get("multi_year_delinquent_tax"), dict):
                    li.raw["multi_year_delinquent_tax"] = mydt_block
                    stats["multi_year_filled"] += 1

        await asyncio.gather(*(one(li, map_no) for li, map_no in targets))

    log.info("greenville_tax.done", **stats)
    return stats
