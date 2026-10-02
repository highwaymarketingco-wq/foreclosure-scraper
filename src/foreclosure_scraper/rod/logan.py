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
_ROW_CELL_RE = re.compile(r'<td class="summary"[^>]*>(.*?)</td>', re.S)


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
    """Parse Logan's embedded result rows.

    Logan renders ONE ROW PER PARTY, not one row per document: a judgment or
    distribution deed naming several debtors/heirs repeats the SAME
    instrument id across many consecutive rows. Live-confirmed on McDowell
    (2026-10-01): one JGMT instrument spanned 18 rows naming 9 distinct
    people, including "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON" and
    five of her relatives -- a textbook probate/heir lead this scraper
    exists to catch. Each such row carries 5 "summary" cells (Book Info,
    Doc Type, Legal Desc, Party Type, Name), not the 6-cell single-row
    shape (Book Info, Doc Type, Legal Desc, Party Type, Searched Party,
    Reverse Party) this function used to assume unconditionally.

    The OLD code built a dict keyed by instrument id from `_LINK_RE`
    (silently collapsing every duplicate-id link match down to the LAST
    occurrence) and a flat per-id cell list from `_CELL_RE`, then always
    sliced `[:6]` off that flat list. For a multi-row instrument this both
    (a) discarded every party but the first, and (b) because real rows are
    5 cells wide here, bled the START of the SECOND row's book-info into a
    bogus 6th "reverse party" value -- corrupting even the one row it kept.

    Fixed by pairing each link anchor with ONLY the cells that appear
    before the NEXT link anchor (i.e. that row's own cells), then
    accumulating every (role, name) pair per instrument across however
    many rows it has, instead of overwriting. `grantor`/`grantee` on the
    returned RodDoc are now "; "-joined, deduped name lists (never just the
    first party); the full lists also land in `raw['logan']['grantors']`/
    `['grantees']` for any downstream consumer that wants the raw list
    (the same `raw['grantors']` convention `rod/cchs.py` already uses).
    """
    links = list(_LINK_RE.finditer(html))
    groups: dict[str, dict] = {}
    order: list[str] = []
    for i, m in enumerate(links):
        inst = m.group(1)
        date_str = m.group(2)
        end = links[i + 1].start() if i + 1 < len(links) else len(html)
        row_cells = [_clean(c) for c in _ROW_CELL_RE.findall(html[m.end():end])]
        if len(row_cells) >= 6:
            # Classic single-row shape: both sides of ONE transaction
            # (Searched Party / Reverse Party) in the same row.
            book_info, doc_type, legal, party_type, searched, reverse = row_cells[:6]
            pairs = []
            if searched:
                pairs.append((party_type, searched))
            if reverse:
                opposite = ("GRANTOR" if "GRANTEE" in (party_type or "").upper()
                            or "INDIRECT" in (party_type or "").upper() else "GRANTEE")
                pairs.append((opposite, reverse))
        else:
            # One-party-per-row shape (live-confirmed on multi-party
            # instruments): Book Info, Doc Type, Legal, Party Type, Name.
            row_cells = (row_cells + [""] * 5)[:5]
            book_info, doc_type, legal, party_type, name = row_cells
            pairs = [(party_type, name)] if name else []
        g = groups.setdefault(inst, {
            "date": date_str, "book_info": book_info, "doc_type": doc_type,
            "legal": legal, "grantors": [], "grantees": [],
            "_seen_grantors": set(), "_seen_grantees": set(),
        })
        if inst not in order:
            order.append(inst)
        for role, name in pairs:
            name = (name or "").strip()
            if not name:
                continue
            is_grantee = "GRANTEE" in (role or "").upper() or "INDIRECT" in (role or "").upper()
            bucket, seen_key = ("grantees", "_seen_grantees") if is_grantee else ("grantors", "_seen_grantors")
            key = name.upper()
            if key in g[seen_key]:
                continue
            g[seen_key].add(key)
            g[bucket].append(name)
    out: list[RodDoc] = []
    for inst in order:
        g = groups[inst]
        book, page = _split_book_page(g["book_info"])
        try:
            rec = datetime.strptime(g["date"], "%m/%d/%Y")
        except ValueError:
            rec = None
        out.append(RodDoc(
            county=county, state=state, doc_type=(g["doc_type"] or "").strip(),
            recorded_date=rec, book=book, page=page,
            grantor="; ".join(g["grantors"]) or None,
            grantee="; ".join(g["grantees"]) or None,
            instrument_no=inst, notes=(g["legal"] or None),
            raw={"logan": {"book_info": g["book_info"],
                           "grantors": g["grantors"], "grantees": g["grantees"]}},
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
