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

import base64
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

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

# Two more columns trail every row's `class="summary"` cells (live-verified on
# Transylvania/McDowell/Mitchell 2026-10-03, headers "XRef" + "Image?") that
# the old code never looked at because they aren't `class="summary"`:
#   XRef   -- the UNDERLYING recorded instrument this one refers to (e.g. the
#             Deed of Trust a Notice of Sale forecloses on, or the deed a
#             judgment-debtor took title under) -- real ownership-chain
#             context, free, already in the fetched HTML.
#   Image? -- a free `view_image.php?key=<hex>&type=pdf` link to the actual
#             recorded document image. The key is scoped to the PHPSESSID
#             that rendered it (live-verified 2026-10-13 against all three
#             working counties: a FRESH session's client gets a 500/0-byte
#             body, or a 23-byte "Image not found" placeholder, for the same
#             key) so it is NOT a durable URL a later, separate pass can
#             fetch -- stamping it alone into the generic `raw['documents']`/
#             _DOC_FIELDS convention would just waste a guaranteed-failing
#             request. The key IS still fetchable, though, with the SAME
#             still-open session that swept it (live-verified 2026-10-13:
#             real `application/pdf` bytes, every doc type tried --
#             S/TR, TR/D, TD, not just the D/T rows rod/doc_images.py's
#             LoganImageSession already fetches for the equity sweep) --
#             see `_fetch_doc_image` + `discover_recent_nods(fetch_images=
#             True)` below, which does exactly that and embeds the result as
#             a data: URI (session-scoped binary captured now or never, same
#             convention scrapers.national.jail_bookings uses for its
#             session/vendor-scoped mugshot bytes) in `raw['logan']['image']`.
_XREF_RE = re.compile(r"loadDetailsScreen\('(\d+)'\);?\"[^>]*>(.*?)</a>", re.S)
_KEY_RE = re.compile(r"key=([0-9a-f]+)&(?:amp;)?type=pdf")

#: `view_image.php` PDFs here run well under this (live-verified 23 KB-180 KB
#: across Transylvania/McDowell/Mitchell, 2026-10-13); cap defensively so one
#: abnormally large recorded TIFF/PDF can never balloon a published Listing.
_MAX_IMAGE_BYTES = 2 * 1024 * 1024
#: Bound the extra requests one sweep call makes -- the Logan counties wired
#: here are small (3-18 distress rows per 60-day window, live-verified), but
#: a future county/window combination returning far more rows must not turn
#: one scraper run into hundreds of extra document fetches.
_MAX_IMAGES_PER_SWEEP = 40


async def _fetch_doc_image(c, host: str, key: str) -> Optional[tuple[bytes, str]]:
    """One `view_image.php` PDF using the CALLER's still-open client/session --
    the key is scoped to the PHPSESSID that rendered it (see the `Image?`
    comment above), so this must run before that client closes. Best-effort:
    None on any failure, wrong content-type, or an oversized body -- never
    raises, never blocks the sweep that produced the key."""
    try:
        r = await c.get(f"{host}/view_image.php?key={key}&type=pdf")
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200 or not r.content:
        return None
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not (ct == "application/pdf" or ct.startswith("image/")):
        return None  # the dead-key placeholder is a tiny text/html stub
    if len(r.content) > _MAX_IMAGE_BYTES:
        return None
    return r.content, ct


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")).strip()


#: The date Party 1 / Party 2 sides and <br>-split party cells were fixed (Spartanburg rows read
#: before it carry the searched party on the grantor side whatever its role).
PARTY_SIDES_FIX_DATE = "2026-10-07"
_BR_SPLIT = re.compile(r"<br\s*/?>|&lt;br\s*/?&gt;", re.I)


def party_names(cell_html: str) -> list[str]:
    """The names in one party cell. Spartanburg's build lists several in one cell, split by
    <br>; reading the cell as one string glued co-owners into one name."""
    out: list[str] = []
    for part in _BR_SPLIT.split(cell_html or ""):
        n = _clean(part)
        if n and n not in out:
            out.append(n)
    return out


def grantee_side(role: str) -> bool:
    """Whether a Party Type cell names the grantee side of the instrument: GRANTEE or INDIRECT
    on most builds, 'Party 2' on Spartanburg's (where 'Party 1' is the grantor side: the
    seller on a deed, the borrower on a mortgage). Live-checked 2026-10-07 on Spartanburg:
    'Party 2' rows are deeds into the searched owner; its mortgages and liens list the owner as
    'Party 1'."""
    r = (role or "").upper()
    return "GRANTEE" in r or "INDIRECT" in r or bool(re.search(r"\bPARTY\s*(?:2|TWO)\b", r))


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
        window = html[m.end():end]
        raw_cells = _ROW_CELL_RE.findall(window)
        row_cells = [_clean(c) for c in raw_cells]
        # pairs are (side, name) with side "grantor" | "grantee"
        if len(row_cells) >= 6:
            # Classic single-row shape: both sides of ONE transaction
            # (Searched Party / Reverse Party) in the same row. A party cell can
            # hold several names split by <br> (Spartanburg), and the role is
            # GRANTOR/GRANTEE (DIRECT/INDIRECT) or 'Party 1'/'Party 2'.
            book_info, doc_type, legal, party_type = row_cells[:4]
            searched_side = "grantee" if grantee_side(party_type) else "grantor"
            reverse_side = "grantor" if searched_side == "grantee" else "grantee"
            pairs = [(searched_side, n) for n in party_names(raw_cells[4])]
            pairs += [(reverse_side, n) for n in party_names(raw_cells[5])]
        else:
            # One-party-per-row shape (live-confirmed on multi-party
            # instruments): Book Info, Doc Type, Legal, Party Type, Name.
            row_cells = (row_cells + [""] * 5)[:5]
            raw_cells = (list(raw_cells) + [""] * 5)[:5]
            book_info, doc_type, legal, party_type, _name = row_cells
            side = "grantee" if grantee_side(party_type) else "grantor"
            pairs = [(side, n) for n in party_names(raw_cells[4])]
        g = groups.setdefault(inst, {
            "date": date_str, "book_info": book_info, "doc_type": doc_type,
            "legal": legal, "grantors": [], "grantees": [],
            "_seen_grantors": set(), "_seen_grantees": set(),
            "xref": None, "xref_instrument_no": None, "image_key": None,
        })
        if inst not in order:
            order.append(inst)
        # XRef (underlying instrument this one refers to) + the free
        # document-image key are page chrome that repeats identically on
        # every row of a multi-row instrument -- take the first occurrence.
        if g["xref"] is None:
            xm = _XREF_RE.search(window)
            if xm:
                g["xref_instrument_no"] = xm.group(1)
                g["xref"] = _clean(xm.group(2)) or None
        if g["image_key"] is None:
            km = _KEY_RE.search(window)
            if km:
                g["image_key"] = km.group(1)
        for side, name in pairs:
            name = (name or "").strip()
            if not name:
                continue
            bucket, seen_key = (("grantees", "_seen_grantees") if side == "grantee"
                                else ("grantors", "_seen_grantors"))
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
                           "grantors": g["grantors"], "grantees": g["grantees"],
                           "xref": g["xref"],
                           "xref_instrument_no": g["xref_instrument_no"],
                           "image_key": g["image_key"]}},
        ))
    return out


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 400, *,
                               fetch_images: bool = False) -> list[RodDoc]:
    """Sweep recent Logan recordings for distress instrument types.

    `fetch_images=True` additionally downloads each row's free `view_image.php`
    PDF, using THIS SAME still-open session (the key dies with it -- see
    `_fetch_doc_image`), and embeds the bytes as a data: URI in
    `raw['logan']['image']`. Best-effort per row: a fetch that fails, or a row
    with no image key, just carries no `image` -- the sweep itself never fails
    because of it.
    """
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
            if fetch_images:
                fetched = 0
                for d in docs:
                    if fetched >= _MAX_IMAGES_PER_SWEEP:
                        break
                    logan_raw = d.raw.get("logan") or {}
                    key = logan_raw.get("image_key")
                    if not key:
                        continue
                    fetched += 1
                    got = await _fetch_doc_image(c, host, key)
                    if got:
                        data, ct = got
                        logan_raw["image"] = {
                            "mime": ct, "bytes": len(data),
                            "data_uri": f"data:{ct};base64,"
                                       f"{base64.b64encode(data).decode('ascii')}",
                        }
    except Exception:
        log.warning("logan.discover_failed", state=state, county=county)
        return []
    log.info("logan.discovered", county=county, distress=len(docs))
    return docs[:max_docs]
