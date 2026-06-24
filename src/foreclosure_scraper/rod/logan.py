"""Logan Systems "The Lookup" Register-of-Deeds adapter (browserless, free).

Logan's instrument-type DATE-RANGE search is reachable without a browser, IF you
submit SPECIFIC instrument codes (SELECT-ALL builds malformed SQL on some
deployments; specific codes don't). Flow:
  1. GET  {host}/index.php                       -> PHPSESSID
  2. POST {host}/index.php   (Accept=Accept)      -> "The Lookup" page w/ token
  3. POST {host}/content.php?<token>
        searchType=it & start_date & end_date & instType[InstCodes][CODE]=CODE...
     -> a (large) HTML page with the result rows EMBEDDED:
        <a id="link_<INST>">MM/DD/YYYY</a> + <td class="summary" id="<INST>">…</td>
        cells = [Book Info, Doc Type, Legal Desc, Party Type, Searched Party,
                 Reverse Party]

Codes are county-specific. Counties whose pick-list loads (Transylvania,
McDowell, Mitchell) share the standard Logan distress codes below. Spartanburg's
loader is broken AND its codes differ (DEED returns 0), so it needs its own code
set sourced separately — not wired here yet.

SC ROD landscape (verified 2026-06-22, both httpx + real browser):
  * SPARTANBURG — newer Logan; the name-less instrument-type date sweep mechanics
    are fully reverse-engineered, BUT the deployment is in a QC/empty-index state
    returning ZERO rows for EVERY search type. No live data => its codes cannot be
    derived empirically. Mechanics are ready; activates when the county restores
    the index. (County-side outage, not a request bug.)
  * LAURENS — older Logan (NameSearch.php/NamePick.php). search_type=Standard ONLY
    => NAME-REQUIRED; there is NO name-less instrument-type date sweep. Distress
    labels use FULL TEXT (instType[FORECLOSURE DEED]=...), not short codes:
    FORECLOSURE DEED, DEED OF DISTRIBUTION (probate), TAX DEED, HOMEOWNERS
    ASSOCIATION LIEN, ORDER BY JUDGE. Cannot be swept; only name-searched.
  * Architecturally, SC foreclosure is JUDICIAL — the lis pendens + judgment are
    Common Pleas (Clerk of Court / Public Index) records, NOT the ROD. So SC ROD
    holds only POST-sale foreclosure deeds, probate, and tax deeds. SC pre-
    foreclosure leads come from the court Public Index + tax-delinquent lists
    (already covered), NOT from a ROD sweep.
  * The name-search that DOES work on every Logan deployment is the path to the
    MORTGAGE-BALANCE / EQUITY gap: name (we have owner names) -> Deed of Trust
    recording -> original loan amount + date -> amortized payoff estimate ->
    equity = ARV - payoff - junior liens. Built per-listing in Pass 2.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

import structlog

from ..http_client import client
from .models import RodDoc

log = structlog.get_logger()

LOGAN_COUNTIES: dict[tuple[str, str], str] = {
    ("NC", "Transylvania"): "https://search.transylvaniadeeds.com",
    ("NC", "McDowell"): "https://search.mcdowelldeeds.com",
    ("NC", "Mitchell"): "https://search.mitchelldeeds.com",
}

# Standard Logan distress instrument codes (foreclosure / lien / probate).
# Extra codes a county doesn't have are harmless (they just don't match).
DISTRESS_CODES = (
    "FCL", "LIS/P", "TR/D", "TD", "C/TR/D", "SHF/D", "S/TR", "N/SUB", "R/TR",
    "LIEN", "LN", "LIEN000", "JUDGMENT", "JGMT", "JUDG", "JUDGM",
    "D/DIST", "DEED/DIST", "ADM/DT", "EXEC/DT",
)
_TOKEN_RE = re.compile(r"content\.php\?(\d+)")
_LINK_RE = re.compile(r'id="link_(\d+)"[^>]*>\s*(\d{2}/\d{2}/\d{4})')
_CELL_RE = re.compile(r'<td class="summary" id="(\d+)">(.*?)</td>', re.S)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")).strip()


def _split_book_page(book_info: str) -> tuple[str | None, str | None]:
    r"""Split a Logan 'Book Info' cell into (book, page).

    Spartanburg-era Logan books can carry an ALPHA SUFFIX — e.g. "149D", which the
    county searches as "149-D" (per the ROD office). The old digits-only parse
    (re.findall r"\d+") silently dropped the letter (book "149-D" -> "149").
    Preserve the suffix, normalize to the dashed searchable form, then take the
    next number as the page.
    """
    s = book_info or ""
    bm = re.search(r"\d+(?:\s*-\s*[A-Za-z]\b|[A-Za-z]\b)?", s)
    if not bm:
        return None, None
    book = re.sub(r"^(\d+)\s*-?\s*([A-Za-z])$", r"\1-\2", re.sub(r"\s+", "", bm.group(0)))
    pm = re.search(r"\d+", s[bm.end():])
    return (book or None), (pm.group(0) if pm else None)


def _parse_records(html: str, state: str, county: str) -> list[RodDoc]:
    links = dict(_LINK_RE.findall(html))
    cells: dict[str, list[str]] = defaultdict(list)
    for inst, val in _CELL_RE.findall(html):
        cells[inst].append(_clean(val))
    out: list[RodDoc] = []
    for inst, date in links.items():
        c = cells.get(inst, [])
        c = (c + [""] * 6)[:6]
        book_info, doc_type, legal, party_type, searched, reverse = c
        # Party Type tells which side the Searched Party is on.
        if "GRANTEE" in (party_type or "").upper() or "INDIRECT" in (party_type or "").upper():
            grantor, grantee = reverse, searched
        else:
            grantor, grantee = searched, reverse
        book, page = _split_book_page(book_info)
        try:
            rec = datetime.strptime(date, "%m/%d/%Y")
        except ValueError:
            rec = None
        out.append(RodDoc(
            county=county, state=state, doc_type=(doc_type or "").strip(),
            recorded_date=rec, book=book, page=page,
            grantor=grantor or None, grantee=grantee or None,
            instrument_no=inst, notes=(legal or None),
            raw={"logan": {"book_info": book_info, "party_type": party_type}},
        ))
    return out


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 400) -> list[RodDoc]:
    """Sweep recent Logan recordings for distress instrument types."""
    host = LOGAN_COUNTIES.get((state, county))
    if not host:
        return []
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days_back))
    fmt = lambda d: f"{d.month:02d}/{d.day:02d}/{d.year}"  # noqa: E731
    codes = "&".join(f"instType[InstCodes][{c}]={c}" for c in DISTRESS_CODES)
    body = (f"searchType=it&start_date={fmt(frm)}&end_date={fmt(today)}&{codes}")
    try:
        async with client(timeout=60.0) as c:
            await c.get(f"{host}/index.php")
            acc = await c.post(f"{host}/index.php", data={"Accept": "Accept"})
            m = _TOKEN_RE.search(acc.text)
            if not m:
                log.warning("logan.no_token", county=county)
                return []
            token = m.group(1)
            r = await c.post(f"{host}/content.php?{token}", content=body,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code != 200 or 'string(' in r.text[:200]:  # SQL error dump
                log.warning("logan.search_error", county=county, head=r.text[:80])
                return []
            docs = _parse_records(r.text, state, county)
    except Exception:
        log.warning("logan.discover_failed", state=state, county=county)
        return []
    log.info("logan.discovered", county=county, distress=len(docs))
    return docs[:max_docs]
