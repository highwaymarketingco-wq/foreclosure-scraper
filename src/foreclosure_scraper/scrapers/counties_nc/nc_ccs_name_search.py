"""NC CCS 4 Counties via name-search pattern (Caldwell, Franklin, Hertford, Gates).

Adapted from enrichment_gaston_rod.py's proven pattern.

PROBLEM: Broad date-range POST times out (Cloudflare 524 - backend can't handle it)
SOLUTION: Per-surname search using same 3-step session pattern as Gaston

Counties: Caldwell, Franklin, Hertford, Gates.

FOUND 2026-11-24 (Hermes, confirmed live by Claude): 3 of the 4
(caldwellnc/franklinnc/hertfordnc) are now Cloudflare-walled -- a plain GET
gets HTTP 403, same "Just a moment" posture Gaston's host has (and did NOT
have as of the 2026-10-13 audit this scraper was originally built against).
gatesnc is NOT blocked (confirmed live, repeated checks, real 200 + content)
-- it keeps the original plain-httpx path below. The 3 blocked hosts go
through _run_stealthy_county(), the same StealthyFetcher Cloudflare-bypass
+ in-page-fetch pattern already proven for enrichment_gaston_rod.py --
reuses that module's generic _PageSession/_PageResp (page-wrapping, not
Gaston-specific) rather than duplicating them.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from typing import AsyncGenerator

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_gaston_rod import _PageSession

log = structlog.get_logger()

# County subdomains. FIXED 2026-11-24 (Hertford): the dedicated subdomain
# "hertfordnc.courthousecomputersystems.com" is DEAD -- confirmed live, a real
# browser navigation there (and a plain curl once past Cloudflare) 302s away
# to the vendor's own generic marketing page (courthousecomputersystems.com/
# corporate/), never Hertford's tenant. The real live tenant is at a
# county.gov-linked "framed" portal (hertfordrod.net, itself just an iframe
# wrapper, confirmed live) pointing at a DIFFERENT, shared-cluster host +
# path pattern CCS has migrated some tenants to: "us4.courthousecomputer
# systems.com/hertfordnc/" -- confirmed live (200, real Register of Deeds
# content, not the marketing page). Stored here as a FULL URL (see
# _resolve_base()) rather than a bare subdomain, same pattern this file's
# sibling enrichment_probate_spartan.py already uses for its own migrated-
# tenant case.
#
# NOT YET A WORKING SEARCH, but now FULLY MAPPED (2026-11-24): confirmed
# live this tenant is on an OLDER classic-ASP CCS deployment, NOT the modern
# /LRSearch/LRIndex + /LRSearch/ExecuteSearch app Gaston/Caldwell/Franklin/
# Gates all share -- that path 404s here. The disclaimer.asp page's REAL
# "accept" control is a javascript: link (not a form/GET), and it points at
# a DIFFERENT tenant folder than the one in this dict -- "hertfordncNW"
# (note the "nw" suffix), not "hertfordnc": https://us4.courthousecomputer
# systems.com/hertfordncnw/application.asp?resize=true. THAT url (not the
# base in this dict) IS the one actually behind Cloudflare (confirmed: plain
# curl gets a real "Just a moment..." 403 challenge page there) -- solved
# fine with the same StealthyFetcher bypass the other 3 counties use.
# Once solved, application.asp is a 3-tab frameset; the real search lives in
# its "Consolidated Land Index" tab, an iframe at realestatesearch.asp
# (confirmed live, 181KB real form). That form posts to a different endpoint
# entirely -- SearchService.asp, not ExecuteSearch -- with DIFFERENT field
# names than Gaston's body(): last, given, searchtype (radio 1/2/3),
# fromdate/todate, datefilter, indextype (radio, 3 checked by default),
# codetype (radio, 3="Either" checked), matchtype (beginswith/exactmatch/
# matchcontains radio, beginswith checked), plus docnumber/booknumber/
# pagenumber/description fields.
#
# FULL REQUEST SHAPE NOW KNOWN (read the real inline JS, not guessed):
# the form's real submit path is realestatesearch.asp's own `Search()` ->
# `mgr.trySearch()` -> `POST SearchService.asp` with BODY (not querystring)
# `cmd=search&<qs>&rnd=<Math.random()>`, qs built in this EXACT field order
# via a `qsItem(pd, name)` helper that only emits a field when it has a
# truthy value: indextype, searchtype, codetype, fromdate, todate,
# sortorder, instrumenttypes, description, docnumber, booknumber,
# pagenumber, taxfrom, taxto, resultstype, maxrecordcount,
# similarnamesearch1, similarnamesearch2, symbolsetout, usecontains,
# exactmatch, directoryresultlink, filteruniquedocuments (last/given go
# first, built separately). Response is XML (`dataType: "xml"`, parsed via
# `dom.getElementsByTagName('recordcount')` etc.), NOT JSON -- a real
# parser for this needs an XML reader, not _parse_rows()'s regex-over-HTML
# approach the LRSearch siblings use. CLIENT-SIDE VALIDATION (may or may
# not be enforced server-side too, untested): last/given name must be 2+
# characters, or the JS alerts and refuses to send anything -- don't test
# single-letter searches here the way Caldwell's zero-yield investigation
# did. OPEN QUESTION: the request may need a `search_token` field read from
# `window.parent.searchToken` (the application.asp frameset page, not this
# iframe) -- grep that page's own script for whether it actually assigns
# this property; if it never does, the token is skipped entirely (confirmed
# in the JS: `tok = window.parent.searchToken ? ... : ''`, and empty tok
# means no token param is sent at all). A live attempt to call the page's
# own `Search()` via Playwright's frame.evaluate() hit "Search is not
# defined" at the 3s mark tried so far -- likely just needs a longer wait
# for the Manager/mgr init script to finish, not a sign the function
# doesn't exist (it's defined plainly at the top of this same iframe's
# inline script).
#
# UPDATE 2026-11-24 (later same day): the "longer wait" theory was WRONG --
# retested at 5s AND 10s, jQuery itself (`typeof window.jQuery`) stays
# `undefined` either way, so nothing downstream of it (including Search/
# mgr) ever initializes. Not a Cloudflare block on the jQuery asset either
# (ruled out two ways: a plain curl to that exact URL 403s with no
# clearance cookie, as expected, but an in-page `fetch()` from INSIDE the
# live solved session, same URL, returns a real 200 with real jQuery 1.6.4
# source -- so the resource itself is reachable fine from this session).
# The real anomaly: listening for every network response matching "jquery"
# or "webcore" during a real page load captured ZERO requests -- the
# browser never even ATTEMPTS to fetch any of the iframe's <script src>
# tags, despite them being present in the DOM (`document.scripts.length`
# reports 12, `document.getElementById('last')` finds the real form). No
# CSP header blocks this (checked: only `x-frame-options: SAMEORIGIN` on
# the iframe's own response, nothing script-blocking). This now looks like
# something about how the iframe's scripts get parsed/executed (or not)
# that a network-level or timing fix won't touch -- worth a real,
# non-headless, eyes-on-screenshot session to see if the SAME thing happens
# to a human, or scrapling/Playwright-specific iframe script-execution
# debugging, before any more blind timing/retry attempts. Next real step: hand-build the
# POST per the shape above and compare against what a real browser actually
# sends over the wire (network-capture it, don't guess blind).
#
# RESOLVED 2026-11-25, two real findings from live eyes-on debugging (Playwright
# page/response event listeners registered via page_setup, BEFORE navigation --
# the earlier "zero requests" reading came from reading performance.getEntriesByType()
# AFTER the fact, which reports zeroed duration/transferSize for this cross-cutting
# response regardless of whether it actually loaded; it is not reliable evidence of
# "never requested" and should not be trusted again here).
#
# FINDING 1 -- a real bug, now understood: _run_stealthy_county() points
# StealthyFetcher.async_fetch()'s own TOP-LEVEL target at `base + "/"` (the bare
# tenant root). solve_cloudflare=True's automatic detect+solve runs ONCE,
# automatically, against THAT url, before page_action ever runs -- but the bare
# root is NOT the Cloudflare-protected url; application.asp?resize=true is (see
# the 2026-11-24 entry above). Confirmed live: pointing async_fetch() itself at
# application.asp?resize=true made the detector correctly find `cType:
# 'interactive'`, solve a real Cloudflare Turnstile challenge, and land on the
# genuine page (title "La'Tia L. Wynn ... Register of Deeds, Hertford County, NC",
# 20+ real frames including realestatesearch.asp) -- vs. solving the bare root,
# which scrapling's own detector sometimes fails to recognize at all ("No
# Cloudflare challenge found", confirmed reproduced twice), leaving the whole
# session unsolved. ACTION: any future stealthy fetch of this tenant should solve
# against application.asp?resize=true directly (or whatever the real protected
# url is for a given tenant), not the bare subdomain root.
#
# FINDING 2 -- the real jQuery mechanism, narrowed to execution, not loading:
# with the Cloudflare fix above, jquery.min.js's real network response (captured
# via page.on("response"), not performance timing) is a clean 200, from_cache=
# false, 91,671 bytes decompressed, correct jQuery-1.6.4 header and UMD closing
# line, and `node --check` on the exact captured body passes -- the file is not
# corrupted, truncated, or blocked at the network layer at all. No
# page.on("pageerror") or uncaught exception fires anywhere on the page. Yet
# `typeof window.jQuery` stays "undefined" no matter HOW the file is run inside
# this specific frame via a NATIVE execution path: as a real <script src> tag
# (original observation), via plain eval(code), AND via
# document.createElement('script') + appendChild (onload fires "loaded" cleanly,
# jQuery still absent after). A plain `window.__x = 42` assignment in the same
# frame works fine, so window itself is not frozen/proxied -- this is specific
# to jQuery's own `(function(window, undefined){ ... window.jQuery = window.$ =
# jQuery; })(window);` wrapper failing to bind to the TRUE global window when
# parsed/run via any of those native paths on THIS page (old 2016-era CCS
# markup; a plausible cause is a named DOM element shadowing the bare `window`
# identifier for top-level script execution, though the exact mechanism was not
# fully isolated -- not worth more time once a working fix was found, below).
#
# WORKING FIX, confirmed live: fetch the script's own source text and run it via
# `new Function(code).call(window)` instead of any native path --
# `jquery_after: "function"` every time, reliably. Replaying ALL of
# realestatesearch.asp's own <script src> files in document order this same way
# (Sarissa.js, OpenDocumentImage.js, Slider.js, AutoComplete.js, jquery.min.js,
# jquery.cookie.js, jquery.maskedinput-1.3.min.js, Querystring.js) succeeds
# cleanly for every one of them -- jQuery ends up genuinely initialized
# (`typeof window.jQuery === "function"`).
#
# REMAINING GAP (new, precisely scoped, not yet solved): the LAST script --
# realestatesearch.asp's own big (150,328-char) inline script, the one that
# actually builds `mgr`/`Search`/`trySearch` -- throws `ReferenceError:
# OpenImageWindow is not defined` partway through when replayed the same way,
# so mgr/Search/trySearch are STILL "undefined" even with jQuery itself fixed.
# OpenImageWindow is not defined anywhere in the TOP (application.asp) frame
# either (checked directly, confirmed absent and not even mentioned in any of
# its own scripts) -- likely a function that belongs to one of the OTHER
# sibling frames (IndexBookImageView.asp / viewimage.asp / viewimageframe.asp,
# all real frames confirmed present in the solved frameset) for an unrelated
# "view document image" feature bundled into the same inline script as the
# search Manager, not something Search() itself should need to call. NEXT
# STEP for whoever picks this back up: find OpenImageWindow's real home (one of
# those sibling frames, via window.parent.<framename>.OpenImageWindow or
# similar), either stub it out harmlessly before replaying this inline script
# (cheapest fix if it's truly unrelated to search) or make it resolve for real;
# then re-run this same replay-in-order technique and confirm trySearch becomes
# callable, before attempting a real POST to SearchService.asp per the shape
# documented above.
_COUNTIES = {
    "Caldwell": "caldwellnc",
    "Franklin": "franklinnc",
    # FIXED 2026-11-25: "hertfordnc" (no "nw") is the confirmed-dead tenant from the
    # 2026-11-24 entry above -- this was never updated to the real one once it was
    # found, because the Cloudflare+jQuery chain downstream of it wasn't solved yet
    # either. Both are now far enough along (see the 2026-11-25 entries above) that
    # pointing this at the real tenant is worth landing on its own.
    "Hertford": "https://us4.courthousecomputersystems.com/hertfordncnw",
    "Gates": "gatesnc",
}

# 2026-11-25: per-county override for the URL StealthyFetcher's own solve_cloudflare
# should run its automatic detect+solve against -- see the module docstring's
# "FINDING 1" entry. Hertford's real Cloudflare-protected url is application.asp,
# not its bare tenant root (confirmed live); Caldwell/Franklin are a different,
# modern LRSearch platform never tested against this specific failure mode, so they
# keep defaulting to the bare root (base + "/") rather than guessing a path change
# for them too.
_SOLVE_URL_OVERRIDE = {
    "Hertford": "/application.asp?resize=true",
}

# Confirmed live 2026-11-24 (see module docstring) -- these 3 need the
# StealthyFetcher Cloudflare bypass; Gates does not and keeps the plain
# httpx path below.
_CLOUDFLARE_BLOCKED = {"Caldwell", "Franklin", "Hertford"}

_BASE = "https://{subdomain}.courthousecomputersystems.com"
_LRINDEX = "/LRSearch/LRIndex?searchTabID=0"
_EXEC = "/LRSearch/ExecuteSearch"


def _resolve_base(subdomain: str) -> str:
    """A _COUNTIES value is normally a bare subdomain on the shared
    courthousecomputersystems.com host; Hertford's value is a full URL on a
    different host+path instead (see _COUNTIES's own 2026-11-24 comment) --
    accept either, same convention as enrichment_probate_spartan.py's PORTALS.
    """
    return subdomain.rstrip("/") if subdomain.startswith(("http://", "https://")) \
        else _BASE.format(subdomain=subdomain)

_HDRS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Distress indicators
_DISTRESS_KINDS = re.compile(
    r"\b(LIEN|JUDG|TAX|LIS\s*PEND|FORECLOS|TRUSTEE|EXECUTION|MECHANIC)\b", re.I
)

# DevExpress grid parsing (from Gaston)
_ROW = re.compile(r'<tr id="gridTrad_DXDataRow\d+"[^>]*>(.*?)</tr>', re.S)
_CELL = re.compile(r'class="[^"]*Cell_(\w+) dxgv"[^>]*>(.*?)</td>', re.S)

# Top 50 US surnames (should cover ~12% of population)
_COMMON_SURNAMES = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES",
    "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ",
    "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON",
    "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN",
    "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS",
    "SANCHEZ", "CLARK", "RAMIREZ", "LEWIS", "ROBINSON",
    "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT",
    "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES",
    "GREEN", "ADAMS", "NELSON", "BAKER", "HALL",
    "RIVERA", "CAMPBELL", "MITCHELL", "CARTER", "ROBERTS",
]


def _text(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _body(last: str) -> str:
    """Build POST body for surname search."""
    params = [
        "MaxRecordCount=2000",
        "PageSize=200",
        "SortOrder=1",
        "IsAdvancedSearch=true",
        "ResultsAreFiltered=false",
        "SearchWasDirectory=false",
        "SearchTabID=0",
        "LRMatchContainsDefaultOn=False",
        "allRowsAreExpanded=false",
        "SearchType=3",
        f"MultiNameLast%5B%5D={urllib.parse.quote(last)}",
        "MultiNameGiven%5B%5D=",  # Empty first name
        "MultiNameSearchType%5B%5D=3",
        "SearchRefDocs=false",
        "SimilarNameSearch=none",
        "MatchType=beginswith",
        "CodeType=3",
        "IndexType=3",
        "SymbolSetOut=false",
        "AdvancedDescriptionQualifier%5B%5D=%2B%2B",
        "AdvancedDescriptionAndOr%5B%5D=AND",
        "ResultsType=1",
        "ExpandAllRows=false",
        "HighlightSearchTermsInResults=false",
        "AutocompleteEnabled=false",
        "SortDirectionPrimary=1",
        "SortDirectionSecondary=1",
    ]
    return "&".join(params)


def _parse_rows(html: str) -> list[dict]:
    """Parse DevExpress grid into instrument dicts."""
    rows: list[dict] = []
    for rm in _ROW.finditer(html or ""):
        cells = {}
        for cm in _CELL.finditer(rm.group(1)):
            cells[cm.group(1).lower()] = _text(cm.group(2))
        if any(cells.get(k) for k in ("grantor", "grantee", "kind", "date")):
            rows.append(cells)
    return rows


def _has_distress_signal(row: dict) -> bool:
    """Check if instrument row indicates distress."""
    kind = row.get("kind", "")
    desc = row.get("description", "")
    blob = f"{kind} {desc}"
    return bool(_DISTRESS_KINDS.search(blob))


async def _seed_and_search(
    client: httpx.AsyncClient,
    base: str,
    surname: str
) -> list[dict]:
    """3-step session + search, return distress instruments."""
    try:
        # Step 1: GET / for session cookie
        await client.get(base, follow_redirects=True)
        
        # Step 2: Seed search context
        lrindex_url = base + _LRINDEX
        resp = await client.get(lrindex_url)
        
        if resp.status_code != 200:
            log.warning("ccs_name.seed_failed", base=base, status=resp.status_code)
            return []
        
        # Step 3: Execute search
        exec_url = base + _EXEC
        headers = {**_HDRS, "Referer": lrindex_url}
        body = _body(surname)
        
        resp = await client.post(exec_url, content=body, headers=headers)
        
        if resp.status_code != 200:
            log.warning("ccs_name.search_failed", surname=surname, status=resp.status_code)
            return []
        
        # Parse and filter
        all_rows = _parse_rows(resp.text)
        distress_rows = [r for r in all_rows if _has_distress_signal(r)]
        
        if distress_rows:
            log.info("ccs_name.distress_found", surname=surname, 
                    total=len(all_rows), distress=len(distress_rows))
        
        return distress_rows
        
    except Exception as exc:
        log.error("ccs_name.exception", surname=surname, error=str(exc)[:200])
        return []


async def _stealthy_seed_and_search(session: _PageSession, base: str, surname: str) -> list[dict]:
    """Same 3-step seed+search as _seed_and_search(), but through a
    _PageSession (an already-Cloudflare-solved browser page) instead of a
    plain httpx client -- for the 3 _CLOUDFLARE_BLOCKED hosts. Identical
    logic to _seed_and_search(); kept separate rather than parameterizing
    one function over both session types, since _PageSession's .get()/.post()
    already duck-type the httpx interface closely enough that forcing a
    single call site to handle both would add indirection without reducing
    real complexity."""
    try:
        await session.get(base)
        lrindex_url = base + _LRINDEX
        resp = await session.get(lrindex_url)
        if resp.status_code != 200:
            log.warning("ccs_name.stealthy_seed_failed", base=base, status=resp.status_code)
            return []

        exec_url = base + _EXEC
        headers = {**_HDRS, "Referer": lrindex_url}
        resp = await session.post(exec_url, data=_body(surname), headers=headers)
        if resp.status_code != 200:
            log.warning("ccs_name.stealthy_search_failed", surname=surname, status=resp.status_code)
            return []

        all_rows = _parse_rows(resp.text)
        distress_rows = [r for r in all_rows if _has_distress_signal(r)]
        if distress_rows:
            log.info("ccs_name.stealthy_distress_found", surname=surname,
                    total=len(all_rows), distress=len(distress_rows))
        return distress_rows
    except Exception as exc:  # noqa: BLE001
        log.error("ccs_name.stealthy_exception", surname=surname, error=str(exc)[:200])
        return []


async def _run_stealthy_county(county: str, subdomain: str) -> list[dict]:
    """One county, fully through a Cloudflare-solved browser session: solve
    once, then loop every surname as in-page fetch() calls on that same
    solved page (same reasoning as enrichment_gaston_rod.py's _run_stealthy --
    a fresh plain session here would hit the exact wall this function exists
    to get past). Each of the 3 blocked counties is a different origin, so
    this is called once per county rather than trying to share one browser
    session across all of them (cross-origin fetch() from a page loaded on
    a DIFFERENT county's domain would not carry that other domain's own
    Cloudflare clearance or cookies)."""
    base = _resolve_base(subdomain)
    county_instruments: list[dict] = []

    async def page_action(page):
        session = _PageSession(page)
        for surname in _COMMON_SURNAMES:
            instruments = await _stealthy_seed_and_search(session, base, surname)
            county_instruments.extend(instruments)

    try:
        from scrapling.fetchers import StealthyFetcher
    except Exception as exc:  # noqa: BLE001
        log.warning("ccs_name.scrapling_missing", county=county, error=str(exc)[:160])
        return []

    solve_url = base + _SOLVE_URL_OVERRIDE.get(county, "/")
    try:
        await StealthyFetcher.async_fetch(
            solve_url,
            headless=True,
            network_idle=True,
            timeout=60000,
            page_action=page_action,
            solve_cloudflare=True,
            wait=5000,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ccs_name.stealthy_fetch_failed", county=county, error=str(exc)[:200])

    return county_instruments


class NcCcsNameSearchScraper(BaseScraper):
    """NC CCS 4 counties via per-surname discovery."""
    
    slug = "counties_nc.nc_ccs_name_search"
    name = "NC CCS Name Search (4 counties)"
    category = "rod"
    timeout_s = 1800.0  # 30 min for all counties
    
    async def fetch(self) -> list[Listing]:
        """Search each county x common surnames for distress signals.

        Gates (not Cloudflare-blocked) uses the original plain-httpx path.
        Caldwell/Franklin/Hertford (confirmed blocked 2026-11-24) each get
        their own StealthyFetcher-solved browser session via
        _run_stealthy_county() -- see _CLOUDFLARE_BLOCKED and the module
        docstring."""

        results: list[Listing] = []
        per_county_instruments: dict[str, list[dict]] = {}

        blocked = [(c, s) for c, s in _COUNTIES.items() if c in _CLOUDFLARE_BLOCKED]
        unblocked = [(c, s) for c, s in _COUNTIES.items() if c not in _CLOUDFLARE_BLOCKED]

        for county, subdomain in blocked:
            log.info("ccs_name.county_start", county=county, path="stealthy")
            per_county_instruments[county] = await _run_stealthy_county(county, subdomain)

        if unblocked:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                for county, subdomain in unblocked:
                    base = _resolve_base(subdomain)
                    log.info("ccs_name.county_start", county=county, path="httpx")
                    county_instruments: list[dict] = []
                    for surname in _COMMON_SURNAMES:
                        instruments = await _seed_and_search(client, base, surname)
                        county_instruments.extend(instruments)
                    per_county_instruments[county] = county_instruments

        for county, county_instruments in per_county_instruments.items():
                # base was only in scope inside the fetch loops above (and
                # never set at all for blocked counties, handled inside
                # _run_stealthy_county) -- recompute it fresh per county here
                # rather than relying on a leftover loop variable.
                base = _resolve_base(_COUNTIES[county])
                # Dedupe by doc number within county
                seen = set()
                unique_instruments = []
                for instr in county_instruments:
                    doc_no = instr.get("docno", "")
                    if doc_no and doc_no not in seen:
                        seen.add(doc_no)
                        unique_instruments.append(instr)
                
                log.info("ccs_name.county_done", county=county, 
                        total=len(county_instruments), unique=len(unique_instruments))
                
                # Convert to Listings
                for instr in unique_instruments:
                    # Extract address from description if present
                    desc = instr.get("description", "")
                    addr_match = re.search(
                        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:St|Ave|Dr|Rd|Ln|Way|Ct|Blvd))?",
                        desc
                    )
                    street_address = addr_match.group(0) if addr_match else None
                    
                    # Determine listing type from kind/description
                    kind = instr.get("kind", "").upper()
                    if "LIS" in kind or "LIS PEND" in desc.upper():
                        listing_type = ListingType.LIS_PENDENS
                    elif "LIEN" in kind or "LIEN" in desc.upper():
                        listing_type = ListingType.TAX_LIEN
                    elif "JUDG" in kind:
                        listing_type = ListingType.LIEN_CLAIM
                    else:
                        listing_type = ListingType.UNKNOWN
                    
                    results.append(Listing(
                        source=self.slug,
                        listing_type=listing_type,
                        property_kind=PropertyKind.UNKNOWN,
                        county=county,
                        state="NC",
                        street_address=street_address,
                        source_url=base + "/LRSearch",
                        raw={
                            "kind": instr.get("kind"),
                            "date": instr.get("date"),
                            "grantor": instr.get("grantor"),
                            "grantee": instr.get("grantee"),
                            "description": desc[:500],
                            "doc_no": instr.get("docno"),
                            "book": instr.get("book"),
                            "page": instr.get("page"),
                        },
                    ))
        
        return results
