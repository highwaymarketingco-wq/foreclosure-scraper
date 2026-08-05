"""Court records enrichment via NC eCourts + SC Public Index.

For every listing with a case number we hit the relevant e-court system through
Apify rag-web-browser (both portals are JS-heavy + Cloudflare-protected) and
extract: plaintiff, defendant, filing date, hearing date, sale location.

ALSO discovers NEW lis pendens / foreclosure cases per county (independent of any
existing listing) by hitting the per-county case-search URL.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable

import structlog

from .render import fetch_rendered
from .config import ALL_COUNTIES
from .models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# ---------- URL templates ----------------------------------------------------------

SC_PUBLICINDEX = "https://publicindex.sccourts.org/{county}/PublicIndex/CaseDetails.aspx?Case={case}"
SC_PUBLICINDEX_SEARCH = (
    "https://publicindex.sccourts.org/{county}/PublicIndex/CaseSearchResults.aspx?"
    "casetype=CP&casesubtype=Foreclosure&filedstart={start}&filedend={end}"
)
NC_ECOURTS_SEARCH = (
    "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26?county={county}"
    "&caseType=SP&caseStatus=Active"
)


# ---------- Field regexes -----------------------------------------------------------

PLAINTIFF_RE = re.compile(r"(?:Plaintiff|Petitioner)[:\s]+(.+?)(?=\n|Defendant|Respondent|$)", re.I | re.S)
DEFENDANT_RE = re.compile(r"(?:Defendant|Respondent)[:\s]+(.+?)(?=\n|Plaintiff|Petitioner|Trustee|$)", re.I | re.S)
TRUSTEE_RE = re.compile(r"(?:Substitute Trustee|Trustee)[:\s]+(.+?)(?=\n|$)", re.I | re.S)
FILING_DATE_RE = re.compile(r"(?:Filed|Filing Date|Date Filed)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
SALE_DATE_RE = re.compile(r"(?:Sale Date|Hearing Date|Auction Date)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
SALE_LOC_RE = re.compile(r"(?:Sale Location|Location)[:\s]+(.+?)(?=\n|$)", re.I | re.S)
NC_CASE_RE = re.compile(r"\b\d{2}\s?SP\s?\d{3,6}(?:-\d+)?\b", re.I)
SC_CASE_RE = re.compile(r"\b\d{4}\s?CP\s?\d{2}\s?\d{4,6}\b", re.I)


def _apply_court_text(li: Listing, text: str) -> int:
    """Pull plaintiff/defendant/trustee/sale info from rendered case-details text."""
    filled = 0

    def maybe(field: str, val):
        nonlocal filled
        if not val:
            return
        cur = getattr(li, field, None)
        if cur in (None, "", 0):
            setattr(li, field, val.strip())
            filled += 1

    if not li.plaintiff:
        m = PLAINTIFF_RE.search(text)
        if m:
            maybe("plaintiff", m.group(1).strip().split("\n")[0][:200])
    if not li.defendant:
        m = DEFENDANT_RE.search(text)
        if m:
            maybe("defendant", m.group(1).strip().split("\n")[0][:200])
    if not li.trustee:
        m = TRUSTEE_RE.search(text)
        if m:
            maybe("trustee", m.group(1).strip().split("\n")[0][:200])
    if not li.sale_location:
        m = SALE_LOC_RE.search(text)
        if m:
            maybe("sale_location", m.group(1).strip().split("\n")[0][:200])
    return filled


# ---------- Enrich existing listings ------------------------------------------------

# Stall-breaker config — NOT a time limit. The per-case court lookups hit the
# e-court portals via the stealth browser; when the headless browser degrades
# (e.g. after a laptop sleep), renders hang and the step ground a whole run for
# hours. These let it process EVERY case while healthy, and bail only if the
# renderer fails/hangs N times in a row. A no-match (empty content) is NOT a
# failure — only timeouts/exceptions count, so legit misses never trip it.
_COURT_CALL_TIMEOUT_S = float(os.environ.get("COURT_CALL_TIMEOUT_S", "90"))
_COURT_BREAKER_FAILS = int(os.environ.get("COURT_BREAKER_FAILS", "12"))


def _norm_case(s: str | None) -> str:
    return re.sub(r"[\s\-]", "", (s or "")).upper()


async def _build_nc_case_index() -> dict:
    """FAST + compliant NC court lookup: run Tyler's working NCJudgmentSearchService
    (the same JSON search the nc_ecourts scraper uses — public API, no CAPTCHA, no
    per-case page render) across our counties for the last 90 days, and index every
    hit by normalized case number. Replaces the broken per-case WorkspaceMode render
    (202-async) that filled 0 fields while costing hours.
    """
    try:
        from .scrapers.counties_nc.nc_ecourts_lis_pendens import (
            SERVICE_URL, SERVICE_HEADERS, TARGET_COUNTIES, _build_search_object,
        )
        from .http_client import client
    except Exception as exc:  # noqa: BLE001
        log.warning("courts.nc_index.import_failed", error=str(exc)[:140])
        return {}
    from datetime import datetime, timedelta
    end = datetime.now()
    start = end - timedelta(days=90)
    index: dict = {}
    try:
        async with client(timeout=45.0, headers=SERVICE_HEADERS) as c:
            r = await c.post(SERVICE_URL, content=b"")
            if r.status_code not in (200, 201):
                log.warning("courts.nc_index.template_status", status=r.status_code)
                return {}
            template = r.json()
            page_from = 0
            for _ in range(25):
                so = _build_search_object(template, counties=TARGET_COUNTIES,
                                          from_date=start, to_date=end,
                                          page_from=page_from, page_size=200)
                r2 = await c.post(SERVICE_URL, json=so)
                if r2.status_code not in (200, 201):
                    break
                sr = (r2.json().get("searchResult") or {})
                hits = sr.get("hits") or []
                if not hits:
                    break
                for h in hits:
                    cn = _norm_case(h.get("caseNumber"))
                    if cn and cn not in index:
                        index[cn] = h
                total = sr.get("totalHits") or 0
                page_from += len(hits)
                if page_from >= total:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("courts.nc_index.failed", error=str(exc)[:140])
    log.info("courts.nc_index.built", cases=len(index))
    return index


def _apply_nc_hit(li: Listing, hit: dict) -> int:
    """Fill plaintiff/defendant from a Tyler hit (only if empty) + stash status."""
    filled = 0
    debtors = "; ".join(d.get("name", "") for d in (hit.get("debtors") or []) if d.get("name"))[:300]
    creditors = "; ".join(c.get("name", "") for c in (hit.get("creditors") or []) if c.get("name"))[:300]
    if debtors and not li.defendant:
        li.defendant = debtors
        filled += 1
    if creditors and not li.plaintiff:
        li.plaintiff = creditors
        filled += 1
    if isinstance(li.raw, dict):
        li.raw.setdefault("court_record", {}).update({
            "cause": hit.get("causeOfActionDesc"), "location": hit.get("location"),
            "ordered_date": hit.get("orderedDate"), "source": "nc_ecourts_search",
        })
    return filled


async def enrich_with_court_records(listings: list[Listing]) -> list[Listing]:
    """Court-record enrichment by case number.

    NC: one batch search against Tyler's public JSON API (fast, compliant), then
        match existing listings by case number — no per-case page renders.
    SC: per-case render of the SC Public Index. NOTE: SC Public Index automated
        access is restricted (admin order); this path is gated by the operator's
        legal clearance, kept available per direction, breaker-protected.
    """
    token = None
    # fields_filled counts ONLY name backfill into an EMPTY plaintiff/defendant,
    # so it reads near-zero on a healthy run (most leads already carry a parsed
    # name and must not be clobbered). court_records is the honest measure of
    # what the NC pass actually produced.
    counts = {"nc_targets": 0, "nc_matched": 0, "fields_filled": 0, "court_records": 0,
              "sc_queried": 0, "sc_matched": 0, "sc_failed": 0}

    # ---- NC: fast batch index ----
    nc = [li for li in listings if li.state == "NC" and li.case_number]
    counts["nc_targets"] = len(nc)
    if nc:
        idx = await _build_nc_case_index()
        for li in nc:
            hit = idx.get(_norm_case(li.case_number))
            if hit:
                counts["nc_matched"] += 1
                counts["fields_filled"] += _apply_nc_hit(li, hit)
                if isinstance(li.raw, dict) and li.raw.get("court_record"):
                    counts["court_records"] += 1

    # ---- SC: per-case render (legal-gated; breaker-protected) ----
    sem = asyncio.Semaphore(4)
    state = {"consec_fail": 0, "tripped": False}

    async def lookup_sc(li: Listing) -> None:
        if li.state != "SC" or not (li.case_number and li.county) or state["tripped"]:
            return
        county_clean = li.county.replace(" County", "").strip().split(",")[0].strip()
        url = SC_PUBLICINDEX.format(county=county_clean, case=li.case_number)
        async with sem:
            if state["tripped"]:
                return
            counts["sc_queried"] += 1
            try:
                # raise_on_http_failure=True so an HTTP-level render failure
                # (bad status / ERR_HTTP_RESPONSE_CODE_FAILURE) raises instead of
                # returning "" — otherwise it would look like a benign empty miss
                # and never count toward the breaker, so the breaker never trips.
                content = (await asyncio.wait_for(
                                fetch_rendered(url, token=token, raise_on_http_failure=True),
                                timeout=_COURT_CALL_TIMEOUT_S)
                           if _COURT_CALL_TIMEOUT_S > 0
                           else await fetch_rendered(url, token=token, raise_on_http_failure=True))
            except (Exception, asyncio.TimeoutError):
                counts["sc_failed"] += 1
                state["consec_fail"] += 1
                if _COURT_BREAKER_FAILS and state["consec_fail"] >= _COURT_BREAKER_FAILS:
                    state["tripped"] = True
                    log.warning("courts.enrich.circuit_open", consec_fail=state["consec_fail"])
                return
            state["consec_fail"] = 0
            if not content:
                return
            counts["sc_matched"] += 1
            counts["fields_filled"] += _apply_court_text(li, content)

    await asyncio.gather(*(lookup_sc(li) for li in listings))
    log.info("courts.enrich.done", tripped=state["tripped"], **counts)
    return listings


# ---------- Discover new lis pendens / foreclosure cases ---------------------------

async def discover_lis_pendens() -> list[Listing]:
    """Hit each county's e-court case-search for NEW foreclosure / lis-pendens filings.

    Returns one Listing per case number found, populated with whatever the
    search-results page exposes (case number, county, listing_type=LIS_PENDENS,
    plus any plaintiff/defendant text we can scrape).
    """
    # Rendering is free (local stealth browser); no token gate.
    token = None

    sem = asyncio.Semaphore(3)
    out: list[Listing] = []

    async def search_county(state: str, county: str) -> None:
        if state == "SC":
            url = (
                f"https://publicindex.sccourts.org/{county}/PublicIndex/"
                "CaseSearchResults.aspx?casetype=CP&casesubtype=Foreclosure"
            )
            case_re = SC_CASE_RE
            ltype = ListingType.LIS_PENDENS
        else:
            url = (
                "https://portal-nc.tylertech.cloud/Portal/Home/WorkspaceMode?"
                f"p=0&q=foreclosure+{county}&caseType=SP"
            )
            case_re = NC_CASE_RE
            ltype = ListingType.LIS_PENDENS

        async with sem:
            content = await fetch_rendered(url, token=token)
            if not content:
                return
            seen: set[str] = set()
            for case in case_re.findall(content):
                clean = re.sub(r"\s+", "", case)
                if clean in seen:
                    continue
                seen.add(clean)
                out.append(
                    Listing(
                        source="courts.lis_pendens_discovery",
                        source_url=url,
                        listing_type=ltype,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        case_number=clean,
                        description=f"Lis pendens / foreclosure filing {clean} ({county} County, {state})",
                        first_seen=__import__("datetime").datetime.utcnow(),
                        last_seen=__import__("datetime").datetime.utcnow(),
                    )
                )

    await asyncio.gather(*(search_county(c.state, c.name) for c in ALL_COUNTIES))
    log.info("courts.lis_pendens.discovered", count=len(out))
    return out
