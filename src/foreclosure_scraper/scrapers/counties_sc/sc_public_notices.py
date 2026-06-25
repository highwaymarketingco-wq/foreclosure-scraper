"""SC public notices (scpublicnotices.com, SC Press Association) — the FREE,
legal, public-by-design route to statewide SC foreclosure + probate leads.

SC foreclosure is judicial and the court Public Index is scraping-prohibited, but
legal NOTICES (foreclosure summons/sale, estate/creditor, tax sale) must be
published and are public — this site aggregates them for all 46 counties. This
fills the SC gap where ROD-probate isn't wired (Spartanburg/Anderson/Cherokee/
Oconee) and cross-checks foreclosures.

Mechanism (render path, verified 2026-06-24): the site is ASP.NET WebForms with a
COOKIELESS session (the /(S(id))/ path segment) and an AJAX UpdatePanel grid.
A bare second __doPostBack via raw httpx POST returns HTTP 500 — the grid MUST be
driven through a real browser. We mirror ncpublicnotices.py's StealthyFetcher
render + page_action: GET Search.aspx -> select the popular-search category in
ddlPopularSearches (triggers the grid) -> set ddlPerPage to its MAX (50; the
option list is 5/10/15/20/25/30/50 — 100 is NOT offered) -> parse page 1, click
the grid's Next button (ctl14/ctl01 btnNext) -> parse page 2. 50/page x 2 pages
captures ~100 notices/category (the grid reports "of 100 Pages" at the default
10/page, i.e. up to ~1000 rows; we take the first 100 most-recent statewide and
filter to our in-scope counties).

Each result is one <table class="nested">: a row with the Details.aspx?ID= view
button + a <div class="left"> publication/date and a hidden <div class="right">
City:/County:, then a sibling row whose <td colspan> holds the TRUNCATED preview
notice text (ends in "... click 'view' to open the full text."). The preview is
enough for county/city/date + decedent/defendant extraction; the full body lives
on the (browser-session-bound) Details page and is not fetched per-row to stay
inside timeout_s.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.scpublicnotices.com/Search.aspx"
# Element IDs/selectors confirmed against the live grid (2026-06-24).
_DDL_POPULAR = "select[id$='_ddlPopularSearches']"
_DDL_PERPAGE = "select[id$='_ddlPerPage']"
_GRID_PANEL_ID = "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_updateWSGrid"
_BTN_NEXT = "input[id$='_btnNext']"
_PER_PAGE_MAX = "50"   # the ddlPerPage option list is 5/10/15/20/25/30/50 (no 100)
_RENDER_TIMEOUT_MS = 90000

# Popular-search category -> (our listing type, kind tag)
_CATEGORIES = {
    "4":  (ListingType.LIS_PENDENS, "foreclosure"),    # Foreclosures (summons/sale)
    "23": (ListingType.PROBATE_NOTICE, "probate"),     # Probate Notices
    "30": (ListingType.PROBATE_NOTICE, "probate"),     # Notice to Creditors (estate)
    "26": (ListingType.TAX_SALE, "tax"),               # Tax Sales
}
_IN_SCOPE = {"spartanburg", "anderson", "pickens", "oconee", "cherokee", "union", "laurens"}

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_ID_RE = re.compile(r"Details\.aspx\?SID=[^&]+&(?:amp;)?ID=(\d+)")
_COUNTY_RE = re.compile(r"County:\s*([A-Za-z .'-]+?)(?:\s*City:|\s*$|\s*<)", re.I)
_CITY_RE = re.compile(r"City:\s*([A-Za-z .'-]+?)\s*County:", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b|"
                      r"\b([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b")
# defendant / decedent extraction from legal-notice text
_VS_RE = re.compile(r"(?:plaintiff[s]?,?\s+)?v[s.]{1,3}\.?\s+([A-Z][A-Za-z .,'&-]{3,60}?)(?:,?\s+defendant|,?\s+et al|\s+TO THE|\s*\.|\s*$)", re.I)
_ESTATE_RE = re.compile(r"(?:estate of|in re:?|decedent:?)\s+([A-Z][A-Za-z .,'-]{3,60}?)(?:,|\s+deceased|\s+date of death|\s*\()", re.I)
_ADDR_RE = re.compile(r"(?:property\s+(?:located\s+at|address)|premises\s+(?:known|located)\s+as)[:\s]+([0-9][^,.;]{6,60})", re.I)
# Probate "Notice to Creditors" fields — ported from spartan_weekly_legals.py.
# "Estate: <DECEDENT> Date of Death: <DATE> Case Number: <ES#> Personal
# Representative: <PR NAME> <PR ADDRESS>". These appear in the full notice body;
# the grid preview is truncated so they often won't all be present, but parse
# defensively (each is best-effort, None when absent).
_PROBATE_ESTATE = re.compile(
    r"\bEstate:\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+(?:Date of Death|Case Number|a/?k/?a|aka)\b", re.I)
_PROBATE_DOD = re.compile(r"Date of Death:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
_PROBATE_PR = re.compile(
    r"Personal Representative:\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+"
    r"(\d{1,5}\s+[A-Za-z0-9 .,'\-]+?\b(?:SC|NC|GA|N\.C\.|S\.C\.)\s*\d{5})", re.I)
_ES_CASE_RE = re.compile(r"\b(20\d{2}ES\d{6,9})\b")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")
                  .replace("&amp;", "&").replace("&#39;", "'")).strip()


def _result_blocks(html: str) -> Iterable[str]:
    """Yield one HTML fragment per result. The live render wraps each result in
    its own <table class="nested"> (metadata row + a sibling row holding the
    truncated preview text); the unit-test fixtures use a flat single <tr> per
    result. Prefer nested-table blocks; fall back to per-<tr> so both shapes work."""
    blocks = re.findall(r'<table class="nested".*?</table>', html, re.S)
    if blocks:
        yield from blocks
        return
    yield from _ROW_RE.findall(html)


def _parse_results(html: str) -> list[dict]:
    """Parse the results GridView into notice dicts (publication/date/city/county/text/id)."""
    out: list[dict] = []
    for block in _result_blocks(html):
        m = _ID_RE.search(block)
        if not m:
            continue
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        cells = [c for c in cells if c and "javascript" not in c.lower()]
        meta = next((c for c in cells if "county:" in c.lower()), "")
        # body = the longest non-metadata cell (the notice text / truncated preview).
        # Strip the live grid's "click 'view' to open the full text." trailer.
        body = max((c for c in cells if "county:" not in c.lower()), key=len, default="")
        body = re.sub(r"\s*\.{2,}\s*click 'view' to open the full text\.?\s*$", "", body, flags=re.I)
        county_m = _COUNTY_RE.search(meta)
        city_m = _CITY_RE.search(meta)
        date_m = _DATE_RE.search(meta)
        out.append({
            "notice_id": m.group(1),
            "county": (county_m.group(1).strip() if county_m else ""),
            "city": (city_m.group(1).strip() if city_m else ""),
            "date_text": (date_m.group(1) or date_m.group(2)) if date_m else "",
            "publication": meta.split(" ")[0:3] and " ".join(meta.split()[:3]) or "",
            "text": body,
        })
    return out


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _defendant(text: str, kind: str) -> str | None:
    if kind == "probate":
        m = _ESTATE_RE.search(text)
    else:
        m = _VS_RE.search(text)
    return _clean(m.group(1)) if m else None


def _to_listing(n: dict, cat: str, slug: str) -> Listing | None:
    if (n["county"] or "").strip().lower() not in _IN_SCOPE:
        return None
    lt, kind = _CATEGORIES[cat]
    text = n["text"]
    # Foreclosure: distinguish a SALE notice from a pre-foreclosure summons.
    if kind == "foreclosure" and re.search(r"\b(master'?s sale|notice of sale|will be sold|public auction)\b", text, re.I):
        lt = ListingType.FORECLOSURE_SALE
    rec = _parse_date(n["date_text"])
    addr_m = _ADDR_RE.search(text)
    defendant = _defendant(text, kind)
    street_address = (_clean(addr_m.group(1)) if addr_m else None)
    case_number = None
    raw: dict = {"public_notice": {"notice_id": n["notice_id"], "publication": n["publication"],
                                   "category": cat, "city": n["city"], "text": text[:4000]}}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": "public_notice",
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
        # Port of spartan_weekly_legals probate parse: prefer the "Estate:" field
        # for the decedent, fall back to the "estate of" caption. The DECEDENT is
        # the property owner, so put them in `defendant` for owner-name backfill
        # (probate notices carry NO property address).
        em = _PROBATE_ESTATE.search(text)
        decedent = _clean(em.group(1)) if em else defendant
        if decedent:
            defendant = decedent
        prm = _PROBATE_PR.search(text)
        dod = _PROBATE_DOD.search(text)
        esm = _ES_CASE_RE.search(text)
        case_number = esm.group(1) if esm else None
        raw["probate"] = {
            "decedent": decedent or None,
            "date_of_death": (dod.group(1) if dod else None),
            "personal_representative": (_clean(prm.group(1)) if prm else None),
            "pr_address": (_clean(prm.group(2)) if prm else None),
            "es_case_number": case_number,
        }
        street_address = None  # no property address in a probate notice
    return Listing(
        source=slug,
        source_url=f"https://www.scpublicnotices.com/Details.aspx?ID={n['notice_id']}",
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state="SC", county=n["county"].strip().title(),
        city=n["city"].strip().title() or None,
        defendant=defendant,
        street_address=street_address,
        case_number=case_number,
        description=(text[:200] or f"{kind} notice"),
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


async def _render_category(cat: str) -> list[dict]:
    """Drive the AJAX grid for one popular-search category via StealthyFetcher
    (mirrors ncpublicnotices.py's render + page_action). Selects the category,
    bumps ddlPerPage to its MAX (50), parses page 1, clicks Next, parses page 2
    — capturing ~100 notices/category. Returns parsed notice dicts; [] on any
    failure (defensive — never raises)."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("scpublicnotices.scrapling_missing")
        return []

    pages_html: list[str] = []

    async def _row_count(page) -> int:
        try:
            return await page.eval_on_selector_all(
                "input[id$='_btnView2']", "els => els.length"
            )
        except Exception:
            return 0

    async def _wait_rows(page, predicate_js: str) -> None:
        """Wait for the AJAX grid to settle on a new state. The view-button
        count is the reliable signal — a static innerHTML-length check fires
        instantly off the previous page and skips the postback."""
        try:
            await page.wait_for_function(
                f"() => {{ const n = document.querySelectorAll(\"input[id$='_btnView2']\").length; return {predicate_js}; }}",
                timeout=30000,
            )
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        # 1) pick the category -> triggers the grid postback (default ~10 rows)
        try:
            await page.select_option(_DDL_POPULAR, cat, timeout=8000)
        except Exception:
            return
        await _wait_rows(page, "n >= 5")
        # 2) bump per-page to its MAX (50) -> grid re-renders to ~50 rows/page
        try:
            await page.select_option(_DDL_PERPAGE, _PER_PAGE_MAX, timeout=8000)
            await _wait_rows(page, "n > 20")
        except Exception:
            pass
        # capture page 1
        try:
            pages_html.append(await page.content())
        except Exception:
            pass
        # 3) page through (page 1 @ 50 + page 2 -> ~100). A bare second postback
        #    via raw POST 500s; clicking Next in the live browser is the unlock.
        #    The page-2 rows are entirely new (distinct Details IDs), so wait a
        #    beat for the UpdatePanel swap before snapshotting.
        try:
            btn = await page.query_selector(_BTN_NEXT)
            if btn and await btn.is_enabled():
                before = await _row_count(page)
                await btn.click(timeout=8000)
                await _wait_rows(page, "n >= 1")
                try:
                    await page.wait_for_timeout(2500)
                except Exception:
                    pass
                if await _row_count(page) or before:
                    pages_html.append(await page.content())
        except Exception:
            pass

    try:
        await StealthyFetcher.async_fetch(
            _BASE, headless=True, network_idle=True,
            timeout=_RENDER_TIMEOUT_MS, page_action=page_action,
        )
    except Exception as exc:
        log.warning("scpublicnotices.fetch_fail", category=cat, error=str(exc)[:200])
        return []

    # Parse + dedupe across the captured pages (a stuck pager would repeat page 1).
    rows: list[dict] = []
    seen: set[str] = set()
    for html in pages_html:
        for n in _parse_results(html):
            nid = n["notice_id"]
            if nid in seen:
                continue
            seen.add(nid)
            rows.append(n)
    log.info("scpublicnotices.category_done", category=cat,
             pages=len(pages_html), rows=len(rows))
    return rows


class SCPublicNotices(BaseScraper):
    slug = "counties_sc.sc_public_notices"
    name = "SC Public Notices (scpublicnotices.com — foreclosure/probate/tax)"
    category = "public_notices"
    expected_min_count = 0
    timeout_s = 600.0   # 4 categories x render+paginate (~2 page loads each)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for cat in _CATEGORIES:
            try:
                for n in await _render_category(cat):
                    li = _to_listing(n, cat, self.slug)
                    if li:
                        out.append(li)
            except Exception:
                log.warning("scpublicnotices.category_failed", category=cat)
        log.info("scpublicnotices.done", leads=len(out))
        return out
