"""Courthouse Computer Systems (CCS) "DevExpress" land-records web app --
Jasper County SC Register of Deeds.

Confirmed NOT the same product as rod/cchs.py (searched this codebase for
"courthousecomputersystems"/"CCS" first, live 2026-10-14). rod/cchs.py reads
CCS's OLDER classic-ASP product (a plain `SearchService.asp` XML API --
Burke/Cleveland/Lincoln/Madison/Henderson NC). Jasper
(`us6.courthousecomputersystems.com/JasperSC`) runs a NEWER ASP.NET MVC +
DevExpress ASPxGridView product -- `DXR.axd` resource handler,
`LRSearch/ExecuteSearch` (initial search) + `LRSearch/PagingTraditional`
(an opaque, stateful DevExpress grid callback for page 2+), `Image/
ShowDocImage` (the per-document viewer). Same vendor COMPANY, a different
app GENERATION. Net-new to this codebase -- no sibling reader exists.

Everything below was hand-verified live 2026-10-14, AFTER the owner
personally solved the site's real Google reCAPTCHA v2 ("Please complete the
CAPTCHA to enter this site", sitekey
6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb) that gates the Land Records search
feature -- the same hard boundary this whole project respects for every real
CAPTCHA: never automated, stays a manual/operator step. Everything
downstream of that human-cleared session is built here, driven as in-page
DOM/`fetch()`-equivalent calls on an ALREADY-cleared nodriver `tab` (same
convention as `rod.acclaim.discover_recent_nods_via_browser` -- this module
never starts a browser and never attempts the CAPTCHA itself).

SEARCH FORM. The Land Records subapp (`#subapp_LRSearch_0`, a same-origin
iframe) has two tabs: "Standard" (Last/Given name, a From/To Date pair, and
its own `#btnStandardSearch`) and "Advanced" (adds Book/Page/Doc#/a Doc
Types picker/Tax-amount/Description, and its OWN SEPARATE
`#btnAdvancedSearch`). LIVE GOTCHA, caught by actually running this flow,
not assumed: both tabs' content stay in the DOM at once (hidden via CSS, not
removed), and BOTH have a button whose visible text is literally "Search" --
a selector that walks `document.querySelectorAll('button')` for text
"Search" and clicks the FIRST match gets `#btnStandardSearch` (present but
hidden) instead of `#btnAdvancedSearch`, silently submitting an UNFILTERED
search that ignores every Advanced-only field including Doc Types --
live-confirmed: an Advanced search meant to be scoped to 6 Doc Types still
came back with the full unscoped count (6,904 records / 2,676 documents)
when the wrong button fired. `_SEARCH_JS` below targets `#btnAdvancedSearch`
BY ID for exactly this reason, never by button text.

DATE FIELDS -- NOT a recorded-date filter, confirmed empirically, not
assumed. The page labels them plainly "From Date"/"To Date" and separately
shows "Verified Date Range: 01/01/1985 - 10/13/2026" near the top -- a clue
this pass chased down rather than ignored. Three live tests settle what they
actually do:
  1. Blank name + a ONE-DAY window (01/01/2026-01/02/2026): 36 records / 11
     documents, EVERY row's own Date column reads 01/02/2026 -- looks like a
     clean recorded-date filter.
  2. Blank name + a wide ~9.5-month window (01/01/2026-10/14/2026): 10,053
     records / 4,697 documents -- but the very FIRST row is a mortgage
     (Book 945/Page 211) recorded 03/31/2017, nine years before the window
     starts.
  3. Name="OGDEN" (that 2017 mortgage's borrower) + the SAME wide 2026
     window: 5 records, INCLUDING the 2017 mortgage -- but Name="OGDEN" +
     the ONE-DAY window above: 0 records, the 2017 mortgage gone.
The 2017 mortgage is referenced by a satisfaction (Kind SMTG, book
1211/page 1971) recorded 03/03/2026 -- squarely inside the wide window. The
simplest account that fits all three results: From/To Date filters an
internal VERIFICATION/index timestamp (the concept the page's own "Verified
Date Range" label names), not the document's own recorded Date -- an old
document's index row can get touched/re-verified later (here, apparently
because a 2026 satisfaction cross-references it), re-entering ANY window
that covers that later touch, while its displayed Date stays its true
original recording date. For a CURRENT filing the gap is usually zero
(verified same-day), so a recent-window sweep still reliably catches real
new activity -- it just cannot be trusted as a surgical recorded-date cut,
and can occasionally surface an old, already-resolved document pulled back
in by an unrelated later filing. Treated here as "catches real recent
activity plus occasional older cross-referenced noise", not as proof of
completeness for a literal recorded-date range.

A full `01/01/1985` (the site's own stated floor) to today sweep IS
reachable (confirmed: 10,479 records / 9,307 documents, blank name --
genuinely more real DOCUMENTS than the partial-2026 window's 4,697, so the
partial window is not secretly the whole universe). It is NOT a routine
option, though: that one blank-name query alone took roughly 55-60 seconds
server-side before the HTML came back, against ~5-10s for a 90-day window --
a full-history sweep is a rare one-time-backfill candidate, not something to
run on every pass. `discover_recent_distress_via_browser` below defaults to
a 90-day recent window for exactly this reason.

DOC TYPES -- scoping the search server-side, not fetching-everything-then-
filtering. A 90-day blank-name sweep is 6,903 records / 2,675 documents, the
large majority of it routine filings (DEED/MTG/RELS/UCC/...) a distress
sweep does not want. The Advanced tab's own Doc Types picker
(`#doctypes_dialog`, backed by a hidden `#DocTypes` input the search form
actually reads -- a comma list of short CODES, confirmed live by setting it
directly and watching the result count change, e.g.
"DETH,DETH-DB,LIEN,ML,TXLN,LPEN") lets the search itself be scoped up front,
same convention as Wake's own 2-doc-type scoping (`nc_rod_captcha.py`).
Jasper's OWN Kind-code dictionary (read live from the picker, not guessed)
has NO "FORECLOSURE"/"TRUSTEE'S DEED" kind at all -- SC foreclosures run
through the Court of Common Pleas, and a Master-in-Equity deed records here
as a plain "DEED" with no distress-marking Kind code, same as any other
conveyance (the satisfaction/RELS rows this pass saw DO carry a
"CASE NO 2024CPxxxxxxxx" string in their free-text Description, the one
thread back to a foreclosure action -- out of scope for THIS pass's Kind-
code classification, noted for a future one). The real distress-carrying
kinds this county's dictionary DOES have, with their live-CONFIRMED short
codes (read straight off the real `#DocTypes` hidden field's own echo after
checking each one in the picker, not inferred from the grid's 3-5-char
abbreviations):
  DETH     DEATH CERTIFICATE              -> relationship_signal (probate)
  DETH-DB  DEATH CERTIFICATE IN DEED BOOK -> same
  LIEN     LIEN (live examples were mostly real HOA/POA assessment liens)
  ML       MECHANICS LIEN (live example: a real contractor's lien,
           BACKYARD OASIS SERVICES LLC vs. two homeowners, 09/2026)
  TXLN     TAX LIEN (live examples: a real IRS federal tax lien AND a real
           US District Court criminal-case judgment lien, both 09/2026)
  LPEN     LIS PENDENS (the classic SC pre-foreclosure recording -- the
           dictionary has it and the code above is CONFIRMED from the
           picker's own hidden-field echo, but no live GRID ROW example of
           it surfaced in the 90-day sample this session pulled)
A 90-day sweep scoped to exactly these 6 codes is 65 records / 39 documents
(live, 2026-10-14) -- 5 pages at the grid's default 15/page, a trivial
pagination budget, against 461 pages unscoped. The county dictionary ALSO
has "LIEN IN DEED BOOK"/"LIS PENDENS IN DEED BOOK"/"TAX LIEN IN DEED BOOK"
entries (the same signal filed in a different physical book) -- NOT
included in the 6 codes above. A live gotcha explains why: checking a box
under one Book-Type filter view in the picker and then switching that
dropdown to another Book Type UNCHECKS the first view's boxes (confirmed by
watching `#DocTypes`'s own value collapse after doing exactly that) -- a
real UI trap, not a code bug on this module's side. Flagged here as an
honest, narrow partial-coverage gap (the "...IN DEED BOOK" variant of each
of LIEN/LIS PENDENS/TAX LIEN), not silently dropped.

PAGINATION. Changing page or page size goes through DevExpress's own
opaque, stateful ASPxGridView callback protocol (`POST .../LRSearch/
PagingTraditional`, `__DXCallbackArgument` plus a base64 .NET
BinaryFormatter-serialized `callbackState`/`customOperationState` blob that
must be echoed back byte-for-byte from the previous response) -- not a
plain page-number GET/POST a bare httpx client could reconstruct from
scratch. Rather than hand-roll that protocol, this module drives the page's
OWN real client-side pagination
(`document.querySelector('[id*="PagerBarTNext"]').click()`), the same
"Next Page" control a human clicks, and re-reads the grid's rendered rows
from the DOM afterward -- the exact recipe hand-verified live against the
real site through 4+ pages before being ported here.

SESSION-REUSE WINDOW -- the operational question this pass was asked to
answer, from two independent angles, neither of them a guess:
  1. CODE EVIDENCE: the page's own served JS
     (`$(document).ready` -> `var timeoutLength = 43200000;` [12 hours, in
     ms] -> `HomeUIHelper.StartHeartBeat(timeoutLength,
     '/JasperSC/Home/KeepSessionActive')`), read live from the served
     `ccsjs` bundle's `StartHeartBeat`/`SessionHeartBeat` implementation,
     resolves to: ping `KeepSessionActive` once immediately, then
     `window.setInterval(..., Math.round(timeoutLength / 2))` -- every 6
     HOURS thereafter. A heartbeat that only bothers to fire once every 6
     hours is architectural evidence the session is designed to survive at
     LEAST that long unattended -- nothing defends a short session with a
     6-hour ping cadence.
  2. LIVE FLOOR: `window.fetch`/jQuery `.ajax` were monkey-patched in the
     human-cleared tab to silently block any further call to
     `KeepSessionActive` (confirmed the block armed, 0 calls through it the
     entire time), then this pass did its real work -- building, testing
     and documenting this module -- on the SAME tab for 22+ minutes
     (19:10:19Z -> 19:33:00Z, 2026-10-14) with ZERO KeepSessionActive
     heartbeat calls (the client's own 6-hour cadence never had a reason to
     fire in a 22-minute window). A real, deliberate Advanced search issued
     at the end of that gap (DocTypes=DETH, a 2-week window) came back with
     live grid data (21 records / 18 documents), not a CAPTCHA/disclaimer
     redirect. This is a WEAKER claim than Wake's own zero-REQUEST idle
     floor (`nc_rod_captcha.py`, commit 08e29a17) -- this pass's own
     in-between searches/pagination/doc-type probes kept making real
     requests of OTHER kinds throughout that window, so it demonstrates
     "22+ minutes of continuous real use with the heartbeat never needed",
     not "22+ minutes of total silence" -- reported as exactly that, not
     inflated to match Wake's stricter method.
  Combined verdict: Jasper's session is NOT a short, Wake-style
  (7-minute-floor) enterprise session -- the served JS's own 12-hour/6-hour
  constants point to an operator-cleared session comfortably surviving a
  full scraper run, not expiring mid-sweep. The reCAPTCHA clearing ITSELF
  stays, and will keep staying, a manual/operator step -- this module does
  not and will not try to automate solving it.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timedelta
from typing import Any

import structlog

from .models import RodDoc

log = structlog.get_logger()

# (state, county) -> (host, app). Only Jasper on this DevExpress CCS product
# in this codebase today -- confirmed net-new, no sibling.
CCS_DEVEXPRESS_COUNTIES: dict[tuple[str, str], tuple[str, str]] = {
    ("SC", "Jasper"): ("us6", "JasperSC"),
}


def base_url(state: str, county: str) -> str | None:
    cfg = CCS_DEVEXPRESS_COUNTIES.get((state, county))
    if not cfg:
        return None
    host, app = cfg
    return f"https://{host}.courthousecomputersystems.com/{app}"


#: Doc Types short codes, live-confirmed 2026-10-14 by setting
#: `#DocTypes` and reading the search result count change -- see module
#: docstring's "DOC TYPES" section for the full evidence and the
#: full-name <-> code mapping.
JASPER_DISTRESS_DOC_CODES = ("DETH", "DETH-DB", "LIEN", "ML", "TXLN", "LPEN")
JASPER_DISTRESS_DOC_TYPE_NAMES = (
    "DEATH CERTIFICATE", "DEATH CERTIFICATE IN DEED BOOK",
    "LIEN", "MECHANICS LIEN", "TAX LIEN", "LIS PENDENS",
)

_PROBATE_CODES = {"DETH", "DETH-DB"}
_LIEN_CODES = {"LIEN", "ML", "TXLN"}
#: LIS PENDENS is its own bucket, not a plain lien -- the classic SC
#: pre-foreclosure court filing, same ListingType.LIS_PENDENS bucket the
#: sibling _clarendon_doc_to_listing() already uses for "LIS PENDENS"/
#: "FORECLOS"/"TRUSTEE"/"NOTICE OF SALE" kinds in this same file.
_LIS_PENDENS_CODES = {"LPEN", "LPEN-DB"}

#: Budget caps, same spirit as this file's siblings (Clarendon's
#: CLARENDON_LOOKBACK_DAYS=45 / rod.cchs's discover_recent_nods
#: days_back=60) -- 90 days is a bit more generous since one Jasper search
#: already returns the WHOLE window in a handful of pages (65 records / 39
#: docs live, 2026-10-14), not one request per day like some vendors.
JASPER_LOOKBACK_DAYS = 90
#: 5 pages covered the live 90-day/6-doc-type sample in full (65 records at
#: 15/page); capped higher for headroom on a busier window. Still
#: documented as partial-if-exceeded, same honesty convention as every
#: other page budget in this codebase.
JASPER_MAX_PAGES = 15
JASPER_MAX_DOCS = 400


def classify_kind_code(kind: str | None) -> str | None:
    """'probate' | 'lien' | 'lis_pendens' | None, from the grid's own short
    Kind code (exact match against the live-confirmed codes above -- see
    module docstring). Unknown codes (routine filings: MTG, DEED, RELS,
    UCC, COR, SMTG, ...) return None, same as every other non-distress kind
    in this codebase's ROD classifiers."""
    k = (kind or "").strip().upper()
    if not k:
        return None
    if k in _PROBATE_CODES:
        return "probate"
    if k in _LIS_PENDENS_CODES:
        return "lis_pendens"
    if k in _LIEN_CODES:
        return "lien"
    return None


# --------------------------------------------------------------------------- #
# Row parsing -- one <tr>'s cell-text array -> a flat dict                    #
# --------------------------------------------------------------------------- #
# Column layout confirmed live, 2026-10-14, by reading `gridTrad`'s real
# rendered rows (`Array.from(tr.querySelectorAll('td')).map(td =>
# td.innerText.trim())`) across 20+ distinct real documents: index 5=Book,
# 6=Page, 7=Kind, 8="<or|ee>\t<name>" (party col 1, role + name joined by a
# literal tab in the SAME cell), 11="<or|ee>\t<name>" (party col 2, the
# reciprocal party), 14=Date (recorded), 15=Description (full legal
# description text, free), 16=an internal per-party sequence id
# (e.g. "1-498844"), 17=Doc # (the real instrument number), 18=Tax Map #
# (parcel id(s) -- newline-joined when a document covers multiple parcels).

def _party_from_cell(cell: str) -> tuple[str, str] | None:
    """('or'|'ee', name) from a combined "role\\tname" grid cell, or None."""
    if not cell or "\t" not in cell:
        return None
    role, _, name = cell.partition("\t")
    role, name = role.strip().lower(), name.strip()
    if role not in ("or", "ee") or not name:
        return None
    return role, name


def parse_grid_row(cells: list[str]) -> dict[str, Any] | None:
    """One raw `<tr>`'s cell-text array -> a flat dict, or None on a row
    shape this parser doesn't recognize (defensive -- a future layout tweak
    degrades to 'skip that row', not a crash)."""
    if not isinstance(cells, list) or len(cells) < 18:
        return None
    book, page, kind = cells[5].strip(), cells[6].strip(), cells[7].strip()
    if not (book and page and kind):
        return None
    p1 = _party_from_cell(cells[8]) if len(cells) > 8 else None
    p2 = _party_from_cell(cells[11]) if len(cells) > 11 else None
    date_s = cells[14].strip() if len(cells) > 14 else ""
    desc = cells[15].strip() if len(cells) > 15 else ""
    seq = cells[16].strip() if len(cells) > 16 else ""
    docno = cells[17].strip() if len(cells) > 17 else ""
    parcel_cell = cells[18].strip() if len(cells) > 18 else ""
    grantor = p1[1] if p1 and p1[0] == "or" else (p2[1] if p2 and p2[0] == "or" else None)
    grantee = p1[1] if p1 and p1[0] == "ee" else (p2[1] if p2 and p2[0] == "ee" else None)
    try:
        recorded = datetime.strptime(date_s, "%m/%d/%Y") if date_s else None
    except ValueError:
        recorded = None
    parcel_ids = [p.strip() for p in parcel_cell.splitlines() if p.strip()]
    return {
        "book": book, "page": page, "kind": kind,
        "grantor": grantor, "grantee": grantee,
        "recorded_date": recorded, "description": desc or None,
        "seq": seq or None, "doc_no": docno or None,
        "parcel_id": parcel_ids[0] if parcel_ids else None,
        "parcel_ids": parcel_ids,
    }


def collapse_rows_to_docs(raw_rows: list[list[str]], state: str, county: str) -> list[RodDoc]:
    """Party rows (one per grantor/grantee -- same one-row-per-party shape
    as rod/cchs.py's classic-ASP XML, this vendor's newer product kept the
    convention) -> one RodDoc per (book, page, doc_no)."""
    docs: dict[tuple, RodDoc] = {}
    for cells in raw_rows or []:
        parsed = parse_grid_row(cells)
        if not parsed:
            continue
        key = (parsed["book"], parsed["page"], parsed["doc_no"] or parsed["seq"])
        existing = docs.get(key)
        if existing is not None:
            payload = existing.raw["ccs_devexpress_rod"]
            for name, bucket in ((parsed["grantor"], "grantors"), (parsed["grantee"], "grantees")):
                if name and name not in payload[bucket]:
                    payload[bucket].append(name)
            if not existing.grantor and parsed["grantor"]:
                existing.grantor = parsed["grantor"]
            if not existing.grantee and parsed["grantee"]:
                existing.grantee = parsed["grantee"]
            continue
        # ONE wrapper key ("ccs_devexpress_rod"), same convention as
        # rod/beaufort_dmp.py's "beaufort_rod" / rod/acclaim.py's
        # "acclaim_rod" -- a vendor-specific marker + structured payload,
        # not several new flat raw keys that would each need registering
        # in web_artifact.py's RAW_KEEP allowlist.
        docs[key] = RodDoc(
            county=county, state=state, doc_type=parsed["kind"],
            recorded_date=parsed["recorded_date"], book=parsed["book"], page=parsed["page"],
            grantor=parsed["grantor"], grantee=parsed["grantee"],
            instrument_no=parsed["doc_no"], parcel_id=parsed["parcel_id"],
            notes=parsed["description"],
            raw={"ccs_devexpress_rod": {
                "kind": parsed["kind"], "seq": parsed["seq"],
                "grantors": [parsed["grantor"]] if parsed["grantor"] else [],
                "grantees": [parsed["grantee"]] if parsed["grantee"] else [],
                "parcel_ids": parsed["parcel_ids"],
            }},
        )
    return list(docs.values())


# --------------------------------------------------------------------------- #
# Browser-driven search -- in-page DOM calls on an already-cleared tab        #
# --------------------------------------------------------------------------- #
# Every selector/id here (#subapp_LRSearch_0, levelTab_Advanced, the
# From/To Date inputs found by their <label> text, #DocTypes,
# #btnAdvancedSearch, #gridTrad, [id*="PagerBarTNext"]) was hand-verified
# live against the real site, 2026-10-14 -- see module docstring.
_SEARCH_JS = r"""
(async () => {
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
    function isLoading(d) {
        return Array.from(d.querySelectorAll('*'))
            .some(e => e.children.length === 0 && e.textContent.trim() === 'Loading...');
    }

    let ifr = document.getElementById('subapp_LRSearch_0');
    if (!ifr) {
        const link = Array.from(document.querySelectorAll('*'))
            .find(e => e.children.length === 0 && e.textContent.trim() === 'Land Records');
        if (link) link.click();
        for (let i = 0; i < 20 && !ifr; i++) { await sleep(300); ifr = document.getElementById('subapp_LRSearch_0'); }
    }
    if (!ifr || !ifr.contentDocument) return JSON.stringify({error: 'no_lrsearch_iframe'});
    const doc = ifr.contentDocument;

    const advTab = doc.getElementById('levelTab_Advanced');
    if (advTab) advTab.click();
    await sleep(400);

    function setVal(el, v) {
        el.value = v;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
    }
    const labels = Array.from(doc.querySelectorAll('label'));
    function inputAfterLabel(text) {
        const lbl = labels.find(l => l.textContent.trim() === text);
        return lbl ? lbl.parentElement.querySelector('input[type=text], input:not([type])') : null;
    }
    const fromEl = inputAfterLabel('From Date');
    const toEl = inputAfterLabel('To Date');
    const lastEl = inputAfterLabel('Last Name/Firm Name');
    const docTypesEl = doc.getElementById('DocTypes');
    if (!fromEl || !toEl || !docTypesEl) {
        return JSON.stringify({error: 'missing_fields', fromFound: !!fromEl,
                                toFound: !!toEl, docTypesFound: !!docTypesEl});
    }
    if (lastEl) setVal(lastEl, '');
    setVal(fromEl, %(from_date)r);
    setVal(toEl, %(to_date)r);
    docTypesEl.value = %(doc_codes)r;
    docTypesEl.dispatchEvent(new Event('input', {bubbles: true}));
    docTypesEl.dispatchEvent(new Event('change', {bubbles: true}));

    const searchBtn = doc.getElementById('btnAdvancedSearch');
    if (!searchBtn) return JSON.stringify({error: 'no_advanced_search_button'});
    searchBtn.click();

    function readState() {
        const grid = doc.getElementById('gridTrad');
        if (!grid) return null;
        const rows = Array.from(grid.querySelectorAll('tr'))
            .filter(tr => tr.id && tr.id.includes('DXDataRow'))
            .map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()));
        const totalRec = doc.getElementById('total_records');
        const totalDoc = doc.getElementById('total_documents');
        return {
            rows,
            total_records: totalRec ? totalRec.textContent.trim() : null,
            total_documents: totalDoc ? totalDoc.textContent.trim() : null,
        };
    }

    let state = null;
    for (let i = 0; i < 40; i++) {
        await sleep(500);
        if (!isLoading(doc)) { state = readState(); if (state) break; }
    }
    if (!state) return JSON.stringify({error: 'search_timeout'});

    const pages = [state.rows];
    for (let p = 1; p < %(max_pages)d; p++) {
        const nextBtn = doc.querySelector('[id*="PagerBarTNext"]');
        if (!nextBtn) break;
        const beforeKey = state.rows.length ? (state.rows[0][16] || '') : '';
        nextBtn.click();
        let advanced = false;
        for (let i = 0; i < 40; i++) {
            await sleep(500);
            if (isLoading(doc)) continue;
            const s2 = readState();
            if (!s2) continue;
            const afterKey = s2.rows.length ? (s2.rows[0][16] || '') : '';
            if (afterKey !== beforeKey) { state = s2; advanced = true; break; }
            if (!s2.rows.length) { state = s2; advanced = true; break; }
        }
        if (!advanced) break;
        pages.push(state.rows);
    }

    return JSON.stringify({
        total_records: state.total_records, total_documents: state.total_documents,
        pages_read: pages.length, rows: pages.flat(),
    });
})()
"""


async def _search_via_tab(tab, from_date: datetime, to_date: datetime,
                           doc_codes: str, max_pages: int) -> dict[str, Any]:
    js = _SEARCH_JS % {
        "from_date": from_date.strftime("%m/%d/%Y"),
        "to_date": to_date.strftime("%m/%d/%Y"),
        "doc_codes": doc_codes,
        "max_pages": max_pages,
    }
    try:
        result = await tab.evaluate(js, await_promise=True, return_by_value=True)
        return _json.loads(result)
    except Exception as exc:  # noqa: BLE001
        log.warning("ccs_devexpress.tab_search_failed",
                    error=f"{type(exc).__name__}: {exc}"[:200])
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


async def discover_recent_distress_via_browser(
    tab, state: str, county: str,
    days_back: int = JASPER_LOOKBACK_DAYS,
    max_pages: int = JASPER_MAX_PAGES,
    max_docs: int = JASPER_MAX_DOCS,
    doc_codes: tuple[str, ...] = JASPER_DISTRESS_DOC_CODES,
) -> list[RodDoc]:
    """Recent distress recordings (lien/mechanics-lien/tax-lien/lis-pendens/
    death-certificate) for a CCS DevExpress county, driven over an
    ALREADY reCAPTCHA-cleared nodriver `tab` (operator-assisted -- see
    module docstring; this function never attempts the CAPTCHA). Scopes the
    search server-side to `doc_codes` rather than fetching the whole
    unscoped window and filtering client-side -- see module docstring's
    "DOC TYPES" section for why (461 unscoped pages vs. 5 scoped, live)."""
    if base_url(state, county) is None:
        return []
    today = datetime.utcnow()
    earliest = today - timedelta(days=max(1, days_back))
    result = await _search_via_tab(tab, earliest, today, ",".join(doc_codes), max_pages)
    if result.get("error"):
        log.warning("ccs_devexpress.search_failed", county=county, error=result["error"])
        return []
    docs = collapse_rows_to_docs(result.get("rows") or [], state, county)
    log.info("ccs_devexpress.discovered_via_browser", county=county,
              total_records=result.get("total_records"),
              total_documents=result.get("total_documents"),
              pages_read=result.get("pages_read"), documents_parsed=len(docs))
    return docs[:max_docs]
