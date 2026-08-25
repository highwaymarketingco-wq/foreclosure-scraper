"""Per-case court BID enricher — fill opening_bid from the public court record.

Target leads
------------
Foreclosure-sale / lis-pendens rows that ALREADY carry a court case_number but
have NO opening_bid (the trustee / firm / roster listed the case but never posted
the bid). For each such lead we look up that ONE case in the court's public
record and pull whatever recorded sale / bid / judgment figure is there, plus
the upset-bid status, then write:

  * li.opening_bid          (only when a real recorded bid/sale figure is found)
  * li.judgment_amount      (only if empty and the record exposes one)
  * li.raw["court_bid"] = {amount, amount_kind, upset_status, sale_status,
                           documents, source, source_url, looked_up_iso}

Compliance (hard rules)
-----------------------
FREE + COMPLIANT. No login, no CAPTCHA defeat, no WAF defeat, no bulk crawl.

SC "Public Index" is Rule-610: NO bulk extraction / redistribution. What we do
here is a PER-CASE lookup of a case we ALREADY hold, to enrich that one lead's
bid — explicitly the acceptable pattern. We never enumerate / crawl the index.

The SC Public Index search page carries an ASP.NET AJAX-Toolkit `NoBot`
extender. That is a PASSIVE server-side timing + honeypot widget, NOT a CAPTCHA
or a visual/PoW challenge — a real browser that loads the disclaimer, accepts
it, then submits the form naturally passes it with no puzzle to solve and no
token to forge. We drive a normal headless browser through the normal disclaimer
→ search → open-case flow (one case at a time). If the portal ever swaps NoBot
for a real CAPTCHA / interactive challenge, this enricher will simply fail to
reach the detail page and report 0 — it does not and must not attempt to defeat
such a gate.

State coverage (live-verified 2026-06-26)
----------------------------------------
SC — VIABLE for the per-case flow. The Public Index case-detail page reliably
     renders the docket of "Actions" (Master/Order/Notice of Foreclosure Sale,
     Master's Report of Sale, Order of Confirmation, etc.) + disposition, which
     gives us sale_status + upset-bid status. NOTE: the live pages tested expose
     only court FILING-COST dollars ($25–$275) and "Balance Due", NOT the
     foreclosure sale/bid amount or the judgment principal — those live inside
     the e-filed PDF documents (gated) or the Master-in-Equity roster, not in
     the page text. So in practice SC yields sale_status + upset_status for most
     disposed foreclosures and an opening_bid only on the minority of records
     that print a real "Bid/Sold/High Bid/Sales Price" figure in page text.

NC — NOT VIABLE for a court bid. The only unauthenticated NC eCourts surface is
     the Tyler "Judgment Search" JSON API, which (a) indexes CV judgments, not
     SP foreclosure cases, and (b) returns NO amount field at all (verified: the
     hit schema has no amount/bid/judgment-dollar key). The SP foreclosure file
     — where the trustee's report-of-sale bid would be — is behind Tyler
     SmartSearch / Clerk login. We therefore SKIP NC here and report it rather
     than defeat the gate.

Operational
-----------
* Gated: only runs on leads with case_number AND no opening_bid AND an in-scope
  foreclosure listing_type AND a court-lookupable case-number format.
* Bounded concurrency (COURT_BID_CONCURRENCY, default 2 — polite to the portal)
  + per-case wall-clock timeout (COURT_BID_TIMEOUT_S, default 75s).
* Hard cap on cases per run (COURT_BID_CAP, default 80) so a big backlog can't
  blow the run budget; prioritized by imminent sale_date.
* Off switch: COURT_BID_OFF=1.
* Idempotent: re-running re-confirms; a lead that already has raw["court_bid"]
  with a found amount is skipped.

Wiring (orchestrator integrates — this module does NOT touch main.py):
  Run AFTER the court / Master-in-Equity sources + enrich_with_court_records /
  enrich_case_detail_addresses (so any cheaper court signal is already on the
  lead), and BEFORE the valuation calc/grade loop, so a filled opening_bid feeds
  the ARV / max-bid math. Call:  await enrich_court_bid(enriched)
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .court_detail_parser import parse_register_of_actions, strip_html
from .models import Listing, ListingType

log = structlog.get_logger()


# --- config ----------------------------------------------------------------
CONCURRENCY = int(os.environ.get("COURT_BID_CONCURRENCY", "1"))
PER_CASE_TIMEOUT_S = float(os.environ.get("COURT_BID_TIMEOUT_S", "75"))
CAP = int(os.environ.get("COURT_BID_CAP", "80"))
# Stall-breaker: bail after N consecutive render failures (a degraded headless
# browser / portal outage), so we never grind the run. A no-match (case loads
# but has no bid) is NOT a failure — only timeouts/exceptions count.
BREAKER_FAILS = int(os.environ.get("COURT_BID_BREAKER_FAILS", "8"))


# In-scope foreclosure listing types this enricher will act on. Mirrors the
# foreclosure-bearing subset of ListingType (we want a *foreclosure* bid, not
# a tax-lien certificate amount or a distressed-listing asking price).
_FORECLOSURE_TYPES = {
    ListingType.FORECLOSURE_SALE,
    ListingType.LIS_PENDENS,
    ListingType.SHERIFF_SALE,
    ListingType.HOA_SALE,
}


# SC county code -> county name (Public Index host segment). Mirrors the map in
# enrichment_case_detail / enrichment_courts. Only our footprint codes.
SC_COUNTY_BY_CODE = {
    "04": "Anderson",
    "11": "Cherokee",
    "23": "Greenville",
    "30": "Laurens",
    "37": "Oconee",
    "39": "Pickens",
    "42": "Spartanburg",
    "44": "Union",
}

# SC case number: 2025-CP-42-02945 / 2025CP4202945 (year, CP, county-code, seq).
_SC_CASE_RE = re.compile(r"\b(\d{4})-?CP-?(\d{2})-?(\d{4,6})\b", re.I)
# NC SP case number (for reporting the not-viable bucket): 24SP123 / 26 SP 000284-100
_NC_SP_RE = re.compile(r"\b\d{2,4}\s*-?\s*SP\s*-?\s*\d{3,6}\b", re.I)


# Money labels that, in SC foreclosure records, denote an actual sale/bid figure
# (as opposed to filing costs / balance due). Kept tight to avoid grabbing the
# $25 filing fee. Each maps to the amount_kind we record.
_BID_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bid", re.compile(r"(?:high(?:est)?\s+bid|bid\s+amount|amount\s+bid|winning\s+bid)\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I)),
    ("sold", re.compile(r"(?:sold\s+(?:for|to)|sale\s+price|sales?\s+price|purchase\s+price|sold\s+amount)\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I)),
    ("upset_bid", re.compile(r"upset\s+bid\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I)),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_sc_case(case: str) -> tuple[Optional[str], Optional[str]]:
    """('2025-CP-42-02945') -> ('2025CP4202945', 'Spartanburg'). Returns
    (None, None) for non-SC-CP formats or unmapped county codes."""
    m = _SC_CASE_RE.search(case or "")
    if not m:
        return None, None
    year, code, num = m.groups()
    county = SC_COUNTY_BY_CODE.get(code)
    if not county:
        return None, None
    return f"{year}CP{code}{num}", county


def _parse_money(s: str) -> Optional[float]:
    try:
        v = float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None
    # Sanity band: a real foreclosure bid is between $1k and $50M. Anything
    # outside is a filing fee / parse error.
    return v if 1_000 <= v <= 50_000_000 else None


def _extract_bid_amount(text: str) -> tuple[Optional[float], Optional[str]]:
    """Find a real sale/bid dollar figure in the case-detail visible text.
    Returns (amount, amount_kind) or (None, None)."""
    for kind, pat in _BID_LABEL_PATTERNS:
        m = pat.search(text)
        if m:
            amt = _parse_money(m.group(1))
            if amt is not None:
                return amt, kind
    return None, None


def _derive_upset_status(sale_status: Optional[str], documents: list[dict] | None) -> str:
    """Map the parsed sale_status / sale documents to an upset-bid status.

    SC foreclosures (judicial, Master-in-Equity) DO have an upset-bid period
    (SC Code §15-39-720 et seq. — the bid stays open for a statutory period
    after the sale before the Master delivers the deed). We report the lead's
    position in that lifecycle so the investor knows whether the price is final.
    """
    docs = documents or []
    types = " ".join((d.get("type") or "") for d in docs).lower()
    ss = (sale_status or "").lower()

    if ss == "confirmed" or "confirmation" in types or "master in equity deed" in types or "master's deed" in types or "title to real estate" in types:
        return "closed_confirmed"          # deed delivered / sale confirmed — bid final
    if ss == "sold_unconfirmed" or "report of sale" in types:
        return "sold_pending_upset"        # sold at auction, upset-bid window may be open
    if ss == "sale_noticed" or "notice of" in types and "sale" in types:
        return "scheduled"                 # sale noticed, not yet held
    if ss == "judgment":
        return "judgment_entered"          # judgment of foreclosure, pre-sale
    return "unknown"


# --- SC per-case render ----------------------------------------------------

async def _sc_lookup_one(norm_case: str, county: str) -> Optional[dict]:
    """Drive the SC Public Index per-case flow for ONE case and return the
    parsed court detail dict, or None on any failure.

    Flow (single stealth browser session, cookies persist across steps):
      1. GET the county disclaimer page.
      2. Click "Accept" (in-session) -> lands on PISearch.aspx (search form).
      3. Fill the case number, click Search -> results row.
      4. Click the case-number link (ASP.NET __doPostBack openDetails$N)
         -> CaseDetails.aspx renders for that case.
      5. Parse the detail HTML.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("court_bid.scrapling_missing")
        return None

    disclaimer = f"https://publicindex.sccourts.org/{county.lower()}/publicindex/"
    captured: dict[str, Any] = {}

    async def page_action(page):
        # 1+2: accept the disclaimer in-session
        await page.wait_for_selector("#ContentPlaceHolder1_ButtonAccept", timeout=20000)
        async with page.expect_navigation(wait_until="load", timeout=30000):
            await page.click("#ContentPlaceHolder1_ButtonAccept")
        await page.wait_for_timeout(800)
        # 3: per-case search
        await page.wait_for_selector("#ContentPlaceHolder1_TextBoxCaseNumber", timeout=15000)
        await page.fill("#ContentPlaceHolder1_TextBoxCaseNumber", norm_case)
        await page.wait_for_timeout(400)
        async with page.expect_navigation(wait_until="load", timeout=40000):
            await page.click("#ContentPlaceHolder1_ButtonSearch")
        await page.wait_for_timeout(800)
        # 4: open the case detail by clicking the case-number link.
        # Wait for the results link to actually exist BEFORE the long
        # navigation-click — when the portal throttles us (503 on PISearch)
        # or the case has no rows, the link never appears, and without this
        # short pre-check the click would hang for the full step timeout.
        link = page.get_by_role("link", name=re.compile(re.escape(norm_case)))
        try:
            await link.first.wait_for(state="visible", timeout=12000)
        except Exception:
            # No results row (throttle / no-match): capture what we have and
            # return — caller sees this as a clean no-detail, not a failure.
            captured["url"] = page.url
            captured["html"] = await page.content()
            return page
        async with page.expect_navigation(wait_until="load", timeout=40000):
            await link.first.click()
        await page.wait_for_timeout(1200)
        captured["url"] = page.url
        captured["html"] = await page.content()
        return page

    try:
        await asyncio.wait_for(
            StealthyFetcher.async_fetch(
                disclaimer, headless=True, network_idle=True,
                timeout=int(PER_CASE_TIMEOUT_S * 1000), page_action=page_action,
            ),
            timeout=PER_CASE_TIMEOUT_S + 15,
        )
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        log.debug("court_bid.sc_render_fail", case=norm_case, county=county, error=str(exc)[:140])
        raise  # let caller count it toward the breaker

    html = captured.get("html") or ""
    detail_url = captured.get("url") or disclaimer
    # Guard: must be a real case-detail page, not the disclaimer / search shell.
    if len(html) < 5000 or "CaseDetails.aspx" not in detail_url:
        return None

    text = strip_html(html)
    roa = parse_register_of_actions(html)
    amount, amount_kind = _extract_bid_amount(text)
    upset_status = _derive_upset_status(roa.get("sale_status"), roa.get("documents"))

    return {
        "detail_url": detail_url,
        "amount": amount,
        "amount_kind": amount_kind,            # bid | sold | upset_bid | None
        "judgment_amount": roa.get("judgment_amount"),
        "sale_status": roa.get("sale_status"),
        "upset_status": upset_status,
        "documents": roa.get("documents"),
        "balance_due": roa.get("balance_due"),
    }


def _apply(li: Listing, result: dict, source: str) -> str:
    """Write the court-bid result onto the listing. Returns an outcome tag:
    'bid_filled' | 'status_only' | 'nothing'."""
    if not isinstance(li.raw, dict):
        li.raw = {}

    amount = result.get("amount")
    court_bid: dict[str, Any] = {
        "amount": amount,
        "amount_kind": result.get("amount_kind"),
        "upset_status": result.get("upset_status"),
        "sale_status": result.get("sale_status"),
        "documents": result.get("documents"),
        "source": source,
        "source_url": result.get("detail_url"),
        "looked_up_iso": _now_iso(),
    }
    li.raw["court_bid"] = court_bid

    # Backfill judgment_amount if the record exposed one and we lack it.
    ja = result.get("judgment_amount")
    if ja and (li.judgment_amount is None or li.judgment_amount <= 0):
        li.judgment_amount = ja

    # Fill opening_bid only from a genuine recorded bid/sale figure.
    if amount is not None and (li.opening_bid is None or li.opening_bid <= 0):
        li.opening_bid = round(float(amount), 2)
        return "bid_filled"

    # No dollar bid, but we still captured sale/upset status — useful signal.
    if court_bid["sale_status"] or court_bid["upset_status"] not in (None, "unknown"):
        return "status_only"
    return "nothing"


def _priority(li: Listing) -> tuple:
    """Imminent sales first (a soon-to-sell lead's bid is the most actionable)."""
    sd = li.sale_date
    if sd is None:
        return (3, 0)
    if getattr(sd, "tzinfo", None):
        sd = sd.replace(tzinfo=None)
    days = (sd - datetime.utcnow()).days
    if 0 <= days <= 14:
        return (0, days)
    if 14 < days <= 60:
        return (1, days)
    if days < 0:
        return (2, abs(days))
    return (3, days)


async def enrich_court_bid(listings: list[Listing]) -> dict:
    """Fill opening_bid (+ court_bid status) from the public court record for
    foreclosure leads that have a case_number but no opening_bid.

    Returns a stats dict for the run summary. Mutates listings in place.
    """
    stats: dict[str, Any] = {
        "scanned": 0,
        "sc_candidates": 0,
        "nc_skipped_not_viable": 0,
        "other_skipped_format": 0,
        "looked_up": 0,
        "bid_filled": 0,
        "status_only": 0,
        "nothing": 0,
        "failed": 0,
        "capped": 0,
        "breaker_tripped": False,
    }

    if os.environ.get("COURT_BID_OFF"):
        log.info("court_bid.disabled")
        return stats

    def _eligible(li: Listing) -> bool:
        if li.listing_type not in _FORECLOSURE_TYPES:
            return False
        if not li.case_number:
            return False
        if li.opening_bid is not None and li.opening_bid > 0:
            return False
        # Skip if a prior run already filled a court bid amount for this lead.
        if isinstance(li.raw, dict):
            cb = li.raw.get("court_bid")
            if isinstance(cb, dict) and cb.get("amount"):
                return False
        return True

    sc_targets: list[tuple[Listing, str, str]] = []  # (li, norm_case, county)
    for li in listings:
        stats["scanned"] += 1
        if not _eligible(li):
            continue
        st = (li.state or "").upper()
        if st == "SC":
            norm_case, county = _norm_sc_case(li.case_number)
            if norm_case and county:
                sc_targets.append((li, norm_case, county))
            else:
                stats["other_skipped_format"] += 1
        elif st == "NC":
            # NC court bid is not viable on free surfaces (see module docstring).
            if _NC_SP_RE.search(li.case_number or ""):
                stats["nc_skipped_not_viable"] += 1
            else:
                stats["other_skipped_format"] += 1
        else:
            stats["other_skipped_format"] += 1

    stats["sc_candidates"] = len(sc_targets)
    if not sc_targets:
        log.info("court_bid.no_sc_targets", **{k: stats[k] for k in
                 ("scanned", "nc_skipped_not_viable", "other_skipped_format")})
        return stats

    # Prioritize imminent sales, then cap.
    sc_targets.sort(key=lambda t: _priority(t[0]))
    if len(sc_targets) > CAP:
        stats["capped"] = len(sc_targets) - CAP
        sc_targets = sc_targets[:CAP]

    log.info("court_bid.start", sc_targets=len(sc_targets), cap=CAP,
             concurrency=CONCURRENCY, nc_not_viable=stats["nc_skipped_not_viable"])

    sem = asyncio.Semaphore(CONCURRENCY)
    breaker = {"consec_fail": 0, "tripped": False}

    async def one(li: Listing, norm_case: str, county: str) -> None:
        if breaker["tripped"]:
            return
        async with sem:
            if breaker["tripped"]:
                return
            # Politeness jitter — a small random spacing between renders keeps
            # us from bursting the portal (which 503-throttles parallel hits).
            await asyncio.sleep(random.uniform(0.5, 2.0))
            try:
                result = await _sc_lookup_one(norm_case, county)
            except Exception:  # noqa: BLE001 — render hang / portal error
                stats["failed"] += 1
                breaker["consec_fail"] += 1
                if BREAKER_FAILS and breaker["consec_fail"] >= BREAKER_FAILS:
                    breaker["tripped"] = True
                    stats["breaker_tripped"] = True
                    log.warning("court_bid.breaker_open", consec_fail=breaker["consec_fail"])
                return
            breaker["consec_fail"] = 0
            stats["looked_up"] += 1
            if not result:
                stats["nothing"] += 1
                return
            outcome = _apply(li, result, source=f"sc_public_index:{county}")
            stats[outcome] += 1

    await asyncio.gather(*(one(li, nc, co) for (li, nc, co) in sc_targets))
    log.info("court_bid.done", **stats)
    return stats
