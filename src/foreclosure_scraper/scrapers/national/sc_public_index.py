"""SC Public Index scraper — searches foreclosure cases across SC counties.

Source: https://publicindex.sccourts.org/<county>/publicindex/

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 18), flagged
for the operator rather than acted on unilaterally: the Charleston
disclaimer page's own click-through text (jcmsweb.charlestoncounty.org,
re-read live this batch) states plainly "Access to the South Carolina
Judicial Department Public Index web sites by a site data scraper or any
similar software intended to discover and extract data from a website
through automated, repetitive querying for the purpose of collecting such
data is expressly prohibited." This module already auto-accepts that same
disclaimer programmatically (both the Charleston curl flow and the
nodriver flow below) as part of its existing, multi-session-invested
architecture (predates this audit by weeks, per the dated findings
throughout this docstring) -- not a new behavior introduced here. Noted
for the record, not disabled: this is a standing compliance judgment call
for the project owner, outside this audit's extraction-completeness scope,
and disabling a heavily-engineered, actively-producing source (9,464+ real
party names verified for Charleston alone per main.py's own comment) is
not a call to make unilaterally mid-audit.

Also FOUND/FIXED this batch (small, code-level, zero live-testing-risk
fix): `_parse_search_results()` parses a 6th results-table column,
`date_disposed`, off every row -- but `_to_listings()` never read it back
out, so it was silently discarded on every case, every run. Now carried
through to `raw["sc_public_index"]["date_disposed"]`.

SC foreclosure cases are filed as Common Pleas (CP) — case format YYYYCPNNNNNNN.
The search form uses ASP.NET WebForms with a disclaimer/accept flow + NoBot extender.

Two paths:
  Charleston: uses jcmsweb.charlestoncounty.org — NOT behind F5/Varnish, curl-cffi works.
  All other counties: behind F5 BIG-IP JS challenge + Varnish WAF. curl-cffi and
    Playwright both fail. nodriver (undetected Chrome) passes the F5 challenge,
    accepts the disclaimer, and successfully submits the ASP.NET search form --
    but ONLY in headed (headless=False) mode. See _nodriver_search_county's
    docstring: headless nodriver gets HTTP 406'd by the WAF (MEASURED
    2026-09-27), which is a big part of why this scraper produced zero rows.

Flow for non-Charleston:
1. nodriver opens the disclaimer page (F5 JS challenge auto-solved by real Chrome)
2. Click the disclaimer accept button
3. Fill last name field via JS, blur to trigger NoBot state
4. Click search button via document.querySelector
5. Parse GridView results table for CP cases

RUN BUDGET (MEASURED 2026-09-27, live): one county's full 26-prefix sweep in
WORKING (headed) mode takes ~353s wall-clock (Spartanburg: 1,233 deduped real
CP cases). 44 non-Charleston counties x ~353s is ~4.3 hours -- no realistic
timeout_s covers all of them in a single invocation, so fetch() runs
Charleston (fast, curl, every run) plus a bounded, day-rotating BATCH of the
other 44 (see BATCH_SIZE / _select_county_batch), landing real rows for a few
counties every run instead of chasing full coverage and getting none.

Counties in our SC footprint:
  Spartanburg, Greenville, Pickens, Oconee, Anderson, Cherokee, Laurens,
  Union, Newberry, Abbeville, Greenwood, McCormick, Edgefield, Saluda,
  York, Chester, Chesterfield, Lancaster, Fairfield, Kershaw, Richland,
  Sumter, Lee, Darlington, Dillon, Marlboro, Marion, Horry, Georgetown,
  Williamsburg, Clarendon, Beaufort, Jasper, Colleton, Hampton, Allendale,
  Bamberg, Barnwell, Aiken, Lexington, Calhoun, Orangeburg, Dorchester,
  Berkeley, Charleston
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import structlog
from datetime import datetime
from typing import Any

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# All SC counties with public index sites
SC_COUNTIES = [
    "spartanburg", "greenville", "pickens", "oconee", "anderson",
    "cherokee", "laurens", "union", "newberry", "abbeville",
    "greenwood", "mccormick", "edgefield", "saluda", "york",
    "chester", "chesterfield", "lancaster", "fairfield", "kershaw",
    "richland", "sumter", "lee", "darlington", "dillon",
    "marlboro", "marion", "horry", "georgetown", "williamsburg",
    "clarendon", "beaufort", "jasper", "colleton", "hampton",
    "allendale", "bamberg", "barnwell", "aiken", "lexington",
    "calhoun", "orangeburg", "dorchester", "berkeley", "charleston",
]

# Common last name prefixes to search (covers vast majority of population)
SEARCH_PREFIXES = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
    "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
    "U", "V", "W", "X", "Y", "Z",
]

# Delay between county searches (seconds)
REQUEST_DELAY = 2.0

# Max results per county search (the site caps at ~2500)
MAX_RESULTS_PER_SEARCH = 2500

# Charleston uses the fast curl-cffi path (not behind F5/Varnish) and is
# always run every invocation; the rest need the slow headed-nodriver flow
# and are batched below.
_NODRIVER_COUNTIES = [c for c in SC_COUNTIES if c != "charleston"]

#: How many of the 44 non-Charleston counties ONE fetch() call sweeps.
#:
#: MEASURED 2026-09-27 (live): one WORKING county sweep (headed nodriver,
#: after the headless-WAF-block fix below) takes ~353s wall-clock
#: (Spartanburg, 1,233 deduped real CP cases). BATCH_SIZE=2 x COUNTY_TIMEOUT_S
#: (480s each, see below) = 960s, comfortably inside timeout_s=1200 with
#: Charleston's curl pass (seconds) folded into the remaining margin.
#: All 44 counties are still covered -- just spread across
#: ceil(44/BATCH_SIZE) runs by the rotation below, instead of every run
#: attempting (and never finishing) all 44.
BATCH_SIZE = int(os.environ.get("SC_PUBLIC_INDEX_BATCH_SIZE", "2"))

#: Per-COUNTY wall-clock bound, independent of the 26-prefix script's own
#: sleeps. Mirrors counties_sc.qpaybill_delinquent_roll.COUNTY_TIMEOUT_S
#: (also 480s by default, also sized this same week from a live measurement)
#: so ONE slow/hung county (real network latency, WAF hiccup, a challenge
#: that takes longer than the scripted 12s to clear) can't eat this run's
#: whole timeout_s and take the other BATCHED counties' already-collectible
#: rows down with it.
COUNTY_TIMEOUT_S = float(os.environ.get("SC_PUBLIC_INDEX_COUNTY_TIMEOUT", "480"))


def _select_county_batch(counties: list[str], batch_size: int) -> list[str]:
    """Pick a bounded, rotating slice of ``counties`` for THIS run.

    Deterministic, stateless day-of-year rotation -- no cursor file to
    create, corrupt, or coordinate under board_lock. Repeated runs on the
    same UTC day hit the same batch (stable for re-runs/testing); the batch
    advances on its own as calendar days pass, cycling through every county
    once every ``ceil(len(counties) / batch_size)`` days.
    """
    if batch_size <= 0 or not counties:
        return []
    n_batches = -(-len(counties) // batch_size)  # ceil division
    day = datetime.utcnow().timetuple().tm_yday
    idx = day % n_batches
    start = idx * batch_size
    return counties[start:start + batch_size]


def _parse_search_results(html: str) -> list[dict[str, str]]:
    """Parse search result table rows into case records."""
    tree = HTMLParser(html)
    results = []
    grids = tree.css("table")
    for grid in grids:
        rows = grid.css("tr")
        if len(rows) < 3:
            continue
        for row in rows:
            cells = row.css("td")
            if len(cells) < 3:
                continue
            try:
                name = cells[0].text().strip() if len(cells) > 0 else ""
                role = cells[1].text().strip() if len(cells) > 1 else ""
                case_number = cells[2].text().strip() if len(cells) > 2 else ""
                date_filed = cells[3].text().strip() if len(cells) > 3 else ""
                status = cells[4].text().strip() if len(cells) > 4 else ""
                date_disposed = cells[5].text().strip() if len(cells) > 5 else ""

                # Only keep CP (Common Pleas) cases — that's where foreclosures live
                if not re.search(r"\d{4}CP\d+", case_number):
                    continue

                results.append({
                    "name": name,
                    "role": role,
                    "case_number": case_number,
                    "date_filed": date_filed,
                    "status": status,
                    "date_disposed": date_disposed,
                })
            except Exception:
                continue
    return results


# --------------------------------------------------------------------------- #
# Charleston case-type lanes (2026-10-07).
#
# Charleston County runs its own copy of the Index (jcmsweb.charlestoncounty.org),
# which answers ordinary requests with no bot check; the attorney cleared the
# court's terms (Rule 610) the same day. Its SearchResults grid carries Type,
# Subtype, Judgment # and Court Agency columns past the six the shared positional
# parser reads, so the Charleston path parses the grid by HEADER and labels each
# Common Pleas case with a lane: foreclosure, partition, quiet title, lis pendens,
# judgment, or other. Judgments (Transcript / Foreign / Magistrate's / Confession
# of Judgment) are liens on the debtor's real property (S.C. Code 15-35-810) and
# go out under JUDGMENT_LIEN_SOURCE so the scorer names them 'judgment_lien'
# (distress_score._SOURCE_OVERRIDE), the same signal the NC docketed judgments
# use. Evictions (they name the tenant) and minors' settlements (they name a
# minor) are dropped. The other counties' path (_nodriver_search_county) and its
# parser are untouched; their rows carry none of these keys and convert exactly
# as before.
# --------------------------------------------------------------------------- #
JUDGMENT_LIEN_SOURCE = "national.sc_public_index.judgment_lien"

#: The last Charleston pass's counts (cases per lane, 'other' cases not emitted,
#: party rows dropped, the grid's header labels). Logged as
#: sc_public_index.charleston_lanes and copied onto the scraper as `lane_stats`.
LAST_CHARLESTON_STATS: dict = {}

_CHARLESTON_SKIP_RE = re.compile(
    r"minor|sealed|protection order|restraining|domestic|juvenile|adoption", re.I)


def charleston_lane(subtype: str, case_type: str = "") -> str | None:
    """The lane of one Common Pleas case from its Subtype (and Type) text, or None
    when the grid gave neither (no label: the row converts exactly as before)."""
    s = f"{subtype or ''} {case_type or ''}".strip().lower()
    if not s:
        return None
    if "quiet title" in s or "adverse possession" in s:
        return "quiet_title"
    if "partition" in s:
        return "partition"
    if "foreclosure" in s:
        return "foreclosure"
    if "lis pendens" in s:
        return "lis_pendens"
    if "judgment" in s:
        return "judgment"
    return "other"


def charleston_skip(subtype: str, case_type: str = "") -> bool:
    """True for a case that must not become a row: an eviction (names the tenant,
    not the owner), a minor's settlement, or a sealed / protective / family matter."""
    from ...ingest_sc_publicindex_export import is_eviction_subtype

    if is_eviction_subtype(subtype, case_type):
        return True
    return bool(_CHARLESTON_SKIP_RE.search(f"{subtype or ''} {case_type or ''}"))


#: The ten column labels of Charleston's SearchResults grid, lower-cased, as the live
#: page showed them on 2026-10-07 (coordinator's run of scripts/charleston_lane_proof.py).
CHARLESTON_HEADERS = ("name", "party type", "case number", "filed date", "case status",
                      "disposition date", "type", "subtype", "judgment #", "court agency")

#: A case is a lead only while it is open (2026-10-07). Non-judgment lanes: no
#: disposition date and none of these words in the status. Judgments: the
#: disposition date is the day the judgment was entered, so only a status saying the
#: lien is gone (satisfied, vacated, cancelled, released, expired) closes one.
_CLOSED_STATUS_RE = re.compile(r"clos|dispos|dismiss|satisf|settled|withdr|vacat|cancel", re.I)
_JUDGMENT_GONE_RE = re.compile(r"satisf|vacat|cancel|releas|expir", re.I)


def case_is_open(rec: dict) -> bool:
    """Is this Charleston case still a lead? See _CLOSED_STATUS_RE / _JUDGMENT_GONE_RE."""
    status = rec.get("status") or ""
    if rec.get("lane") == "judgment":
        return not _JUDGMENT_GONE_RE.search(status)
    return not (rec.get("date_disposed") or "").strip() and not _CLOSED_STATUS_RE.search(status)


_VS_RES = (re.compile(r"^\s*(.*?)\s+VS\.?\s+(.*?)\s*$", re.I),
           re.compile(r"^\s*(.*?)\s+V\.?\s+(.*?)\s*$", re.I))
_ROLE_TAIL_RE = re.compile(r",\s*(defendant|plaintiff)(\s*,\s*et\s*al\.?)?\s*$", re.I)


def _parse_charleston_results(html: str, stats: dict | None = None) -> list[dict[str, str]]:
    """Charleston's SearchResults grid, read by column HEADER, with the case-type
    columns. Falls back to the shared positional parser when the grid or its
    "Case Number" header is missing, so a layout change degrades to today's rows.

    `stats` (optional) collects the header labels seen and how many party rows were
    dropped (eviction / minor / sealed). Columns are matched EXACTLY to the ten
    labels the live Charleston grid showed on 2026-10-07 (CHARLESTON_HEADERS).
    """
    tree = HTMLParser(html)
    grid = tree.css_first("table#ContentPlaceHolder1_SearchResults")
    headers = [th.text(strip=True).lower() for th in grid.css("th")] if grid else []

    def col(label: str) -> int | None:
        return headers.index(label) if label in headers else None

    case_i = col("case number")
    if stats is not None:
        stats["headers"] = headers
    if grid is None or case_i is None:
        return _parse_search_results(html)
    name_i, role_i = col("name"), col("party type")
    filed_i, status_i = col("filed date"), col("case status")
    disp_i, type_i = col("disposition date"), col("type")
    sub_i, judg_i, agency_i = col("subtype"), col("judgment #"), col("court agency")

    def cell(cells, i) -> str:
        return cells[i].text(strip=True) if i is not None and i < len(cells) else ""

    out: list[dict[str, str]] = []
    for row in grid.css("tr"):
        cells = row.css("td")
        if len(cells) <= case_i:
            continue
        case_number = cell(cells, case_i)
        if not re.search(r"\d{4}CP\d+", case_number):
            continue
        subtype, case_type = cell(cells, sub_i), cell(cells, type_i)
        if charleston_skip(subtype, case_type):
            if stats is not None:
                stats["dropped_party_rows"] = stats.get("dropped_party_rows", 0) + 1
            continue
        rec = {
            "name": cell(cells, name_i),
            "role": cell(cells, role_i),
            "case_number": case_number,
            "date_filed": cell(cells, filed_i),
            "status": cell(cells, status_i),
            "date_disposed": cell(cells, disp_i),
            "case_type": case_type,
            "subtype": subtype,
            "judgment_number": cell(cells, judg_i),
            "court_agency": cell(cells, agency_i),
            # no Subtype column: unlabeled (emitted as before), never guessed from Type alone
            "lane": (charleston_lane(subtype, case_type) or "") if sub_i is not None else "",
        }
        title = cells[case_i].attributes.get("title") or ""
        m = _VS_RES[0].match(title) or _VS_RES[1].match(title)
        if m:
            rec["plaintiff"] = m.group(1).strip()
            rec["defendant"] = _ROLE_TAIL_RE.sub("", m.group(2)).strip()
        out.append(rec)
    return out


def _dedupe_prefer_defendant(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """One record per case number, in first-seen order. The grid has one row per
    party; the defendant's row wins (the owner, debtor or co-owner being sued)."""
    by_case: dict[str, dict[str, str]] = {}
    for r in results:
        cn = r.get("case_number", "")
        if not cn:
            continue
        cur = by_case.get(cn)
        if cur is None:
            by_case[cn] = r
        elif ("defendant" not in (cur.get("role") or "").lower()
              and "defendant" in (r.get("role") or "").lower()):
            by_case[cn] = r
    return list(by_case.values())


def _get_hidden_fields(html: str) -> dict[str, str]:
    """Extract all ASP.NET hidden form fields from HTML."""
    tree = HTMLParser(html)
    fields = {}
    for inp in tree.css('input[type="hidden"]'):
        name = inp.attributes.get("name", "")
        val = inp.attributes.get("value", "")
        if name:
            fields[name] = val or ""
    return fields


async def _nodriver_search_county(county: str) -> list[dict[str, str]]:
    """Search one non-Charleston county using nodriver (undetected Chrome).

    nodriver passes the F5 BIG-IP JS challenge, accepts the disclaimer,
    and submits the ASP.NET search form with NoBot extender -- but ONLY in
    headed (headless=False) mode. See the headless-vs-headed block below.

    MEASURED (2026-09-25 incident): a live run logged scraper.timeout for
    this scraper (safe_run()'s asyncio.wait_for firing on timeout_s) at
    05:05:33 UTC -- a clean ~3min run -- but its uc_* Chrome child process
    kept running, pegged at high CPU, for hours afterward until manually
    killed; killing it unstuck the pipeline. Root cause: asyncio.CancelledError
    (raised inside this function's try block by the outer timeout, e.g. while
    awaiting asyncio.sleep(12)/page.find()/page.evaluate()) is a BaseException,
    not an Exception, so the old `except Exception:` handler never caught it
    and neither of the old inline `browser.stop()` calls ever ran -- the
    process leaked every time this function got cancelled mid-flight, not
    just on a genuine internal error. Every exit path -- normal completion,
    an ordinary exception, or cancellation -- now shares one try/finally so
    browser.stop() (a sync call that terminates/kills the underlying OS
    process; safe to run from a finally block, including one unwinding a
    CancelledError) always runs. CancelledError itself is never swallowed --
    it re-raises after cleanup, per asyncio best practice.

    MEASURED 2026-09-27 (live, real network, THIS investigation): the reason
    this scraper returned zero rows was upstream of the 26-prefix timing --
    `uc.start(headless=True)` never raises for this site, so the old
    `except Exception: browser = await uc.start(headless=False)` fallback
    never fired. What actually happens: headless Chrome's first navigation to
    publicindex.sccourts.org gets HTTP 406 from the WAF, which Chrome renders
    as its own chrome-error://chromewebdata interstitial (confirmed via
    `location.href` and the body text "This page isn't working ... HTTP ERROR
    406"). That "succeeds" (no exception) at loading a WAF block page, so the
    disclaimer-button click below grabbed Chrome's own "Reload" button
    instead, and the code ran out its clock finding no search form -- for
    EVERY county, every run, regardless of the prefix-sweep arithmetic.
    Headed (headless=False) navigation to the SAME URL, same run, got the
    real Spartanburg County disclaimer page every time tested. This matches
    enrichment_case_detail.py's own docstring for this exact site: "nodriver
    (headless=False) — the ONLY method that works for SC Public Index." Fixed
    by detecting the block from PAGE CONTENT (chrome-error:// on the current
    URL) and restarting headed, instead of an exception handler nothing ever
    throws into. Once headed mode actually reaches the site, the WAF-bypass
    flow works exactly as originally documented: a live Spartanburg sweep
    (all 26 prefixes) took 353.0s wall-clock and returned 1,233 deduped real
    CP cases.
    """
    import nodriver as uc

    base_url = f"https://publicindex.sccourts.org/{county}/publicindex/"

    all_results: list[dict[str, str]] = []
    browser = None

    try:
        try:
            # Try headless first (8GB-safe headline case). Do NOT gate the
            # headed fallback on an exception here -- uc.start(headless=True)
            # succeeds every time for this site; the block is detected from
            # the resulting PAGE, below.
            browser = await uc.start(headless=True)
            page = await browser.get(base_url)
            # Wait for F5 JS challenge to resolve (also long enough for a
            # WAF chrome-error interstitial, if any, to settle before we
            # check for it below).
            await asyncio.sleep(12)

            cur_url = await page.evaluate("location.href")
            if isinstance(cur_url, str) and cur_url.startswith("chrome-error:"):
                # Headless got WAF-blocked (HTTP 406 -> Chrome's own network
                # interstitial, not a Python exception -- see this function's
                # docstring). Restart headed for just this county.
                log.warning("sc_public_index.headless_blocked", county=county,
                            url=base_url)
                try:
                    browser.stop()
                except Exception as exc:
                    log.warning("sc_public_index.browser_stop_fail",
                                county=county, error=str(exc)[:160])
                browser = await uc.start(headless=False)
                page = await browser.get(base_url)
                await asyncio.sleep(12)

            # Accept disclaimer — click first button found
            btn = await page.find("button", best_match=True)
            if not btn:
                # Try finding by text
                btn = await page.find("Accept", best_match=True)
            if btn:
                await btn.click()
                await asyncio.sleep(8)
            else:
                # Maybe already past disclaimer, check if form is present
                html = await page.get_content()
                if "TextBoxlastName" not in html and "ContentPlaceHolder1_TextBoxlastName" not in html:
                    log.warning("sc_public_index.no_disclaimer_button", county=county)
                    return []

            # Verify we're on the search page
            html = await page.get_content()
            if "ContentPlaceHolder1_TextBoxlastName" not in html:
                log.warning("sc_public_index.no_form", county=county, page_size=len(html))
                return []

            # Search each prefix
            for prefix in SEARCH_PREFIXES:
                # Fill last name field via JS
                await page.evaluate(f"""
                    var el = document.getElementById('ContentPlaceHolder1_TextBoxlastName');
                    if (el) {{ el.value = '{prefix}'; }}
                """)
                await asyncio.sleep(0.5)

                # Blur to trigger NoBot state calculation
                await page.evaluate(
                    "document.getElementById('ContentPlaceHolder1_TextBoxlastName').blur();"
                )
                await asyncio.sleep(2)

                # Click search button via JS
                await page.evaluate("""
                    var btn = document.querySelector('input[name="ctl00$ContentPlaceHolder1$ButtonSearch"]');
                    if (btn) { btn.click(); }
                """)
                await asyncio.sleep(8)

                # Parse results
                html2 = await page.get_content()
                page_results = _parse_search_results(html2)
                all_results.extend(page_results)

                log.info("sc_public_index.prefix_done", county=county,
                         prefix=prefix, cases=len(page_results))

                await asyncio.sleep(REQUEST_DELAY)

        except asyncio.CancelledError:
            log.warning("sc_public_index.nodriver_cancelled", county=county)
            raise
        except Exception as exc:
            log.error("sc_public_index.nodriver_error",
                      county=county, error=str(exc)[:200])
            return []
    finally:
        if browser is not None:
            try:
                browser.stop()
            except Exception as exc:
                log.warning("sc_public_index.browser_stop_fail",
                            county=county, error=str(exc)[:160])

    # Deduplicate by case number
    seen = set()
    deduped = []
    for r in all_results:
        cn = r.get("case_number", "")
        if cn and cn not in seen:
            seen.add(cn)
            deduped.append(r)
    return deduped


async def _curl_search_county(county: str) -> list[dict[str, str]]:
    """Search Charleston county using curl-cffi (not behind F5/Varnish).

    2026-09-24: session.get()/session.post() (curl_cffi) are fully
    synchronous/blocking -- part of the same event-loop-starvation sweep
    that found and fixed counties_sc.zombie_properties (confirmed live:
    froze every sibling scraper for 41m50s). This function already yields
    between search-prefix iterations via `await asyncio.sleep(REQUEST_DELAY)`
    below, so it was never a total, unbounded freeze like that one -- but
    each individual blocking call (up to 30s on the search POST) still froze
    the whole event loop for every other concurrent scraper while it ran.
    Each call is now wrapped in asyncio.to_thread so the loop stays free even
    during a single slow request; curl_cffi can't be swapped for the async
    httpx client here (this file's own docstring: Charleston works via
    curl-cffi specifically because it's the one county NOT behind the F5/
    Varnish WAF the other counties need nodriver for -- a different fetch
    tier, not interchangeable). Reusing the same `session` object across
    sequential awaited to_thread calls is safe: only one call is in flight
    on the worker pool at a time, exactly as when it ran on the main thread.
    """
    from curl_cffi import requests as cf

    base_url = "https://jcmsweb.charlestoncounty.org/PublicIndex/"
    search_url = "https://jcmsweb.charlestoncounty.org/PublicIndex/PISearch.aspx"

    results = []
    parse_stats: dict = {}
    try:
        session = cf.Session()

        # Step 1: GET disclaimer page
        r1 = await asyncio.to_thread(session.get, base_url, impersonate="chrome", timeout=15)
        if r1.status_code != 200:
            return []
        await asyncio.sleep(REQUEST_DELAY)

        hidden = _get_hidden_fields(r1.text)
        hidden["ctl00$ContentPlaceHolder1$ButtonAccept"] = "Accept"

        # Step 2: POST accept
        r2 = await asyncio.to_thread(
            session.post, base_url, data=hidden, impersonate="chrome",
            timeout=15, allow_redirects=True)
        if r2.status_code != 200:
            return []

        search_hidden = _get_hidden_fields(r2.text)
        if not search_hidden:
            return []
        await asyncio.sleep(REQUEST_DELAY)

        # Step 3: Search by last name prefix
        for prefix in SEARCH_PREFIXES:
            search_data = dict(search_hidden)
            search_data["ctl00$ContentPlaceHolder1$TextBoxlastName"] = prefix
            search_data["ctl00$ContentPlaceHolder1$ButtonSearch"] = "Search"
            search_data["ctl00$ContentPlaceHolder1$IndexGroup"] = "rbIndexGroup1"

            try:
                r3 = await asyncio.to_thread(
                    session.post, search_url, data=search_data,
                    impersonate="chrome", timeout=30)
                if r3.status_code != 200:
                    continue

                # Header-aware Charleston parse (case-type lanes, 2026-10-07);
                # falls back to _parse_search_results on an unknown layout.
                page_results = _parse_charleston_results(r3.text, parse_stats)
                results.extend(page_results)
                search_hidden = _get_hidden_fields(r3.text)
                await asyncio.sleep(REQUEST_DELAY)
            except Exception:
                continue

    except Exception as exc:
        log.error("sc_public_index.curl_error", county=county, error=str(exc)[:200])
        return []

    # One record per case; the defendant's party row wins (2026-10-07).
    cases = _dedupe_prefer_defendant(results)
    # Charleston 'other' cases (auto, contracts, torts...) are not property
    # suits, and a closed case (disposed, dismissed, satisfied...) is not a lead:
    # both are counted in the run stats, never emitted (2026-10-07). Unlabeled
    # cases (the grid had no Subtype column) still go out as before.
    lanes: dict[str, int] = {}
    closed: dict[str, int] = {}
    out = []
    for c in cases:
        k = c.get("lane") or "unlabeled"
        lanes[k] = lanes.get(k, 0) + 1
        if k == "other":
            continue
        if c.get("lane") and not case_is_open(c):
            closed[k] = closed.get(k, 0) + 1
            continue
        out.append(c)
    LAST_CHARLESTON_STATS.clear()
    LAST_CHARLESTON_STATS.update({
        "cases": len(cases), "lanes": lanes,
        "other_not_emitted": lanes.get("other", 0),
        "closed_not_emitted": closed,
        "emitted": len(out),
        "dropped_party_rows": parse_stats.get("dropped_party_rows", 0),
        "headers": parse_stats.get("headers", []),
    })
    log.info("sc_public_index.charleston_lanes", **{k: v for k, v in LAST_CHARLESTON_STATS.items()
                                                     if k != "headers"})
    return out


class SCPublicIndexScraper(BaseScraper):
    """Scrapes SC county public index for foreclosure (Common Pleas) cases.

    Uses nodriver (undetected Chrome, headed -- see _nodriver_search_county)
    for non-Charleston counties that are behind F5 BIG-IP + Varnish WAF. Uses
    curl-cffi for Charleston which has its own subdomain not behind F5.
    """

    slug = "national.sc_public_index"
    requires_render = False
    # MEASURED 2026-09-27 (live): BaseScraper's default timeout_s=180 could
    # never have been enough even in the best case -- one WORKING county
    # sweep alone takes ~353s. Sized for BATCH_SIZE counties (COUNTY_TIMEOUT_S
    # each, see module docstring) + Charleston's fast curl pass + margin;
    # matches this file's sibling counties_sc.sc_public_notices (also a
    # multi-minute, multi-step WAF-flow scraper) rather than inventing a new
    # outlier value.
    timeout_s = 1200.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counties = SC_COUNTIES
        self.lane_stats: dict = {}

    async def fetch(self) -> list[Listing]:
        """Search Charleston (every run) plus a bounded, rotating BATCH of
        the other 44 counties (see module docstring for the measured
        per-county budget and why full 45-county coverage can't fit in one
        invocation)."""
        all_results: list[dict[str, str]] = []
        county_counts: dict[str, int] = {}

        def _salvage(county: str, county_results: list[dict[str, str]]) -> None:
            county_counts[county] = len(county_results)
            # Stamp each case with its OWN county before it joins the
            # flattened all_results list below -- _to_listings() used to
            # receive the merged list with no way to tell which county any
            # individual case came from (see its own docstring/comment,
            # "we don't track which county each case came from separately"),
            # so every Listing got county=None. Combined with every Listing
            # also sharing one hardcoded source_url, dedupe_key() fell all
            # the way through the parcel/address/case+county branches to the
            # url: fallback -- identical for every row -- and collapsed
            # nearly the whole batch into one survivor (confirmed live
            # 2026-09-27: 1,632 real cases scraped, 1 survived in-batch
            # dedupe). Tagging here, one dict key, fixes it: _to_listings()
            # reads "_county" below and dedupe_key()'s case+county branch is
            # then reachable and unique per real case.
            for case in county_results:
                case["_county"] = county
            all_results.extend(county_results)
            # Populate self.partial AS EACH COUNTY FINISHES so
            # base_scraper.safe_run()'s timeout-salvage path has real rows to
            # ship if this run's own timeout_s fires mid-batch. fetch() used
            # to only ever return at the very end, so a scraper-level
            # timeout discarded every county already collected, not just
            # whichever one was in flight.
            self.partial.extend(self._to_listings(county_results))

        counties = list(self._counties)

        if "charleston" in counties:
            charleston_results = await _curl_search_county("charleston")
            self.lane_stats = dict(LAST_CHARLESTON_STATS)
            _salvage("charleston", charleston_results)
            log.info("sc_public_index.county_done", county="charleston",
                     cp_cases=len(charleston_results))

        nodriver_counties = [c for c in counties if c != "charleston"]
        batch = _select_county_batch(nodriver_counties, BATCH_SIZE)
        log.info("sc_public_index.batch_selected", batch=batch,
                 batch_size=BATCH_SIZE, total_counties=len(nodriver_counties))

        for county in batch:
            try:
                county_results = await asyncio.wait_for(
                    _nodriver_search_county(county), timeout=COUNTY_TIMEOUT_S)
            except asyncio.TimeoutError:
                # Bound ONE county's wall-clock so a hung/slow county can't
                # burn this run's whole timeout_s and take the other
                # batched counties' already-collected rows with it (same
                # failure shape counties_sc.qpaybill_delinquent_roll's
                # COUNTY_TIMEOUT_S fixed 2026-09-23). _nodriver_search_county
                # already cleans up its own browser via try/finally on
                # cancellation, so this wait_for firing is safe.
                log.warning("sc_public_index.county_timeout", county=county,
                            timeout_s=COUNTY_TIMEOUT_S)
                county_results = []

            _salvage(county, county_results)
            log.info("sc_public_index.county_done", county=county,
                     cp_cases=len(county_results))

        log.info("sc_public_index.complete",
                 total_cp_cases=len(all_results),
                 county_counts=county_counts)

        # Convert CP cases to Listings
        listings = self._to_listings(all_results, county_counts)
        log.info("sc_public_index.listings_built", count=len(listings))
        return listings

    def _to_listings(self, cases: list[dict[str, str]],
                    county_counts: dict[str, int] | None = None) -> list[Listing]:
        """Convert CP case records to Listing objects."""
        # Build a reverse lookup: case_number -> county
        case_to_county: dict[str, str] = {}
        if county_counts:
            # We don't track which county each case came from separately,
            # so use the case_number prefix mapping
            pass

        listings = []
        for case in cases:
            case_num = case.get("case_number", "")
            if not case_num:
                continue

            # Extract year from case number (YYYYCP...)
            year_match = re.match(r"(\d{4})CP", case_num)
            year = int(year_match.group(1)) if year_match else 2026

            # Only keep recent cases (2024+)
            if year < 2024:
                continue

            name = case.get("name", "")
            role = case.get("role", "")
            date_filed = case.get("date_filed", "")
            status = case.get("status", "")
            # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch
            # 18): _parse_search_results() already parses a 6th column,
            # date_disposed, off every result row (it's right there in the
            # same cells[5] read as date_filed/status), but this function
            # never read it back out of the case dict -- it was captured
            # then silently thrown away on every single case, every run.
            date_disposed = case.get("date_disposed", "")
            # See _salvage()'s comment in fetch() for why this must be read
            # per-case, not passed in as a separate county_counts summary --
            # county=None here is what let dedupe_key() collapse nearly the
            # whole batch into one survivor. SC_COUNTIES entries are
            # lowercase ("charleston"); title-case to match how county names
            # are stored everywhere else on the board.
            county_raw = case.get("_county")
            county = county_raw.strip().title() if county_raw else None

            block = {
                "name": name,
                "role": role,
                "case_number": case_num,
                "date_filed": date_filed,
                "status": status,
                "date_disposed": date_disposed,
                "court": "SC Common Pleas",
                "source": "publicindex.sccourts.org",
            }
            # Charleston case-type lanes (2026-10-07, _parse_charleston_results):
            # only a Charleston record carries these keys, so every other row
            # converts exactly as before.
            for k in ("case_type", "subtype", "judgment_number", "court_agency", "lane"):
                if case.get(k):
                    block[k] = case[k]
            judgment = case.get("lane") == "judgment"

            li = Listing(
                source=JUDGMENT_LIEN_SOURCE if judgment else self.slug,
                source_url="https://publicindex.sccourts.org/",
                listing_type=ListingType.DISTRESSED if judgment else ListingType.LIS_PENDENS,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=county,
                case_number=case_num,
                plaintiff=case.get("plaintiff") or None,
                defendant=case.get("defendant") or None,
                raw={"sc_public_index": block},
            )
            listings.append(li)
        return listings
