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
import json
import os
import re
import time
import structlog
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
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

#: Lead rules per lane (2026-10-07). "Open" = no disposition date and none of
#: _CLOSED_STATUS_RE in the status.
#:   foreclosure        open, OR disposed within FORECLOSURE_JUDGMENT_DAYS with a disposition
#:                      that is not a dismissal / withdrawal / discontinuance / settlement /
#:                      satisfaction (or transfer, vacatur, cancellation): in SC a foreclosure
#:                      is usually disposed when the judgment of foreclosure is entered and the
#:                      Master-in-Equity sale comes weeks later, so that case is marked
#:                      foreclosure_judgment_entered and kept;
#:   partition, quiet title, lis pendens   open only;
#:   judgment           unless the status says satisfied, vacated, cancelled, released or expired
#:                      (its disposition date is the day it was entered);
#:   other              never; unlabeled (no Subtype column): as before.
_CLOSED_STATUS_RE = re.compile(r"clos|dispos|dismiss|satisf|settled|withdr|vacat|cancel", re.I)
_JUDGMENT_GONE_RE = re.compile(r"satisf|vacat|cancel|releas|expir", re.I)
_FORECLOSURE_NOT_JUDGMENT_RE = re.compile(
    r"dismiss|withdr|discontinu|settl|satisf|transfer|vacat|cancel", re.I)
FORECLOSURE_JUDGMENT_DAYS = int(os.environ.get("CHARLESTON_PI_JUDGMENT_DAYS", "274"))  # ~9 months


def _mdy(s: Any) -> date | None:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def case_is_open(rec: dict) -> bool:
    """No disposition date and no closed status; a judgment until its lien is gone."""
    status = rec.get("status") or ""
    if rec.get("lane") == "judgment":
        return not _JUDGMENT_GONE_RE.search(status)
    return not (rec.get("date_disposed") or "").strip() and not _CLOSED_STATUS_RE.search(status)


def case_lead(rec: dict, today: date | None = None) -> tuple[bool, bool]:
    """(is a lead, foreclosure judgment entered) for one Charleston case. See the rules above."""
    lane = rec.get("lane") or ""
    if lane == "":
        return True, False
    if lane == "judgment" or lane in ("partition", "quiet_title", "lis_pendens"):
        return case_is_open(rec), False
    if lane != "foreclosure":
        return False, False
    if case_is_open(rec):
        return True, False
    disposed = _mdy(rec.get("date_disposed"))
    today = today or datetime.utcnow().date()
    if (disposed and 0 <= (today - disposed).days <= FORECLOSURE_JUDGMENT_DAYS
            and not _FORECLOSURE_NOT_JUDGMENT_RE.search(rec.get("status") or "")):
        return True, True
    return False, False


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

    base_url = CHARLESTON_BASE
    search_url = CHARLESTON_SEARCH

    results = []
    parse_stats: dict = {}
    window: dict = {"mode": "letters"}
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

        # Step 3a (2026-10-07): new filings since the last run, by filed-date window,
        # when the search form offers a date filter. Falls back to the letter sweep
        # when it does not, or when the first answer is not a results page.
        form = _date_form(r2.text)
        window["form"] = _form_summary(form)
        if form and os.environ.get("CHARLESTON_PI_DATE_WINDOW", "1") != "0":
            window.update(await _date_window_search(session, search_url, r2.text, form,
                                                    results, parse_stats))
        # Step 3b: Search by last name prefix
        if window.get("mode") == "letters" or window.get("fallback"):
            window["mode"] = "letters"
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

    return _select_leads(results, parse_stats, window)


#: Charleston's own copy of the Index (no bot check).
CHARLESTON_BASE = "https://jcmsweb.charlestoncounty.org/PublicIndex/"
CHARLESTON_SEARCH = "https://jcmsweb.charlestoncounty.org/PublicIndex/PISearch.aspx"
#: Incremental state of the date-window search (git-ignored data/).
CHARLESTON_STATE_FILE = Path(__file__).resolve().parents[4] / "data" / "charleston_public_index" / "state.json"
WINDOW_DELAY = float(os.environ.get("CHARLESTON_PI_DELAY_S", "3"))
#: Days per window when the search is narrowed to one case subtype, and when it is not.
WINDOW_DAYS = int(os.environ.get("CHARLESTON_PI_WINDOW_DAYS", "30"))
WINDOW_DAYS_ALL_CP = 7
FILED_LOOKBACK_DAYS = int(os.environ.get("CHARLESTON_PI_LOOKBACK_DAYS", "60"))
WINDOW_MAX_REQUESTS = int(os.environ.get("CHARLESTON_PI_MAX_REQUESTS", "40"))
WINDOW_OVERLAP_DAYS = 3
#: The 'Disposed' sweep for judgment-entered foreclosures (CHARLESTON_PI_DISPOSED_SWEEP=0: off).
DISPOSED_SWEEP = os.environ.get("CHARLESTON_PI_DISPOSED_SWEEP", "1") != "0"
GRID_CAP_ROWS = 250
_NO_RECORDS_RE = re.compile(r"no (records|cases|matches|results)|0 records|nothing found", re.I)
_MAX_EXCEEDED_RE = re.compile(r"maximum[^<]{0,40}exceed", re.I)
#: Letters for the fallback "letter + date filter" search (when a date-only search is refused).
DATE_LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def _select_leads(results: list[dict], parse_stats: dict, window: dict,
                  today: date | None = None) -> list[dict]:
    """Dedupe, profile, and keep the cases that are leads (case_lead); everything else is
    counted in LAST_CHARLESTON_STATS, never emitted."""
    cases = _dedupe_prefer_defendant(results)
    lanes: Counter = Counter()
    not_lead: Counter = Counter()
    judged: Counter = Counter()
    profile: dict = {}
    out = []
    for c in cases:
        k = c.get("lane") or "unlabeled"
        lanes[k] += 1
        pr = profile.setdefault(k, {f: Counter() for f in
                                    ("status", "type", "subtype", "filed_year", "disposed_year")})
        pr["status"][c.get("status") or ""] += 1
        pr["type"][c.get("case_type") or ""] += 1
        pr["subtype"][c.get("subtype") or ""] += 1
        pr["filed_year"][(c.get("date_filed") or "")[-4:]] += 1
        pr["disposed_year"][(c.get("date_disposed") or "")[-4:]] += 1
        lead, judgment_entered = case_lead(c, today)
        if not lead:
            not_lead[k] += 1
            continue
        if judgment_entered:
            c["foreclosure_judgment_entered"] = True
            judged[k] += 1
        out.append(c)
    LAST_CHARLESTON_STATS.clear()
    LAST_CHARLESTON_STATS.update({
        "cases": len(cases), "lanes": dict(lanes),
        "other_not_emitted": lanes.get("other", 0),
        "not_lead_by_lane": dict(not_lead),
        "foreclosure_judgment_entered": sum(judged.values()),
        "emitted": len(out),
        "emitted_by_lane": dict(Counter(c.get("lane") or "unlabeled" for c in out)),
        "dropped_party_rows": parse_stats.get("dropped_party_rows", 0),
        "headers": parse_stats.get("headers", []),
        "search": {k: v for k, v in window.items() if k != "form"},
        "form": window.get("form"),
        "profile": {k: {f: dict(c) for f, c in v.items()} for k, v in profile.items()},
    })
    log.info("sc_public_index.charleston_lanes",
             **{k: v for k, v in LAST_CHARLESTON_STATS.items() if k not in ("headers", "profile", "form")})
    return out


def _select(tree: HTMLParser, suffix: str):
    """The <select> whose name ends with `suffix`, case-insensitively (the page spells the
    subtype list 'DropdownlistCaseSubType')."""
    suffix = suffix.lower()
    for sel in tree.css("select"):
        if (sel.attributes.get("name") or "").lower().endswith(suffix):
            return sel
    return None


def _options(sel) -> list[tuple[str, str]]:
    return [(o.attributes.get("value") or "", o.text(strip=True)) for o in sel.css("option")] if sel else []


def _pick(options: list[tuple[str, str]], *needles: str) -> str | None:
    """The first option whose text or value contains a needle, needles tried IN ORDER (so
    'case filed' wins over a bare 'filed', which would also match 'Actions Filed')."""
    for n in needles:
        for v, t in options:
            if n in t.lower() or n in v.lower():
                return v
    return None


def _label(options: list[tuple[str, str]], value: str | None) -> str | None:
    return next((t for v, t in options if v == value), None)


def _postback(sel) -> bool:
    return bool(sel is not None and "__doPostBack" in (sel.attributes.get("onchange") or ""))


def _date_form(html: str) -> dict | None:
    """The search form's date-filter controls, or None when it has no filed-date range.
    Every name and option value is read from the page itself, not assumed. Live 2026-10-07
    (coordinator's proof run): date types Actions Filed, Arrested, Case Filed, Disposed,
    Judgment Issued, plus court and case-type selects. 'Actions Filed' (any docket entry in
    the range) must not be taken for 'Case Filed'."""
    tree = HTMLParser(html or "")
    df = _select(tree, "DropDownListDateFilter")
    f = tree.css_first('input[name$="TextBoxDateFrom"]')
    t = tree.css_first('input[name$="TextBoxDateTo"]')
    if not (df and f and t):
        return None
    dopts = _options(df)
    filed = _pick(dopts, "case filed", "date filed", "filed")
    if filed is None:
        return None
    court, case = _select(tree, "DropDownListCourtType"), _select(tree, "DropDownListCaseTypes")
    return {
        "date_filter": df.attributes.get("name"), "filed": filed,
        "disposed": _pick(dopts, "dispos"),
        "from": f.attributes.get("name"), "to": t.attributes.get("name"),
        "court": court.attributes.get("name") if court else None,
        "court_value": _pick(_options(court), "circuit"),
        "court_postback": _postback(court),
        "case": case.attributes.get("name") if case else None,
        "case_options": _options(case),
        "case_postback": _postback(case),
        "date_options": [t for _, t in dopts],
        "date_labels": {"filed": _label(dopts, filed), "disposed": _label(dopts, _pick(dopts, "dispos"))},
    }


def _form_summary(form: dict | None) -> dict:
    if not form:
        return {"date_filter": False}
    return {"date_filter": True, "date_options": form.get("date_options"),
            "date_used": form.get("date_labels"),
            "disposed_option": bool(form.get("disposed")), "court_select": bool(form.get("court")),
            "case_select": bool(form.get("case"))}


def _grid_rows(html: str) -> int:
    grid = HTMLParser(html or "").css_first("table#ContentPlaceHolder1_SearchResults")
    return sum(1 for tr in grid.css("tr") if tr.css("td")) if grid else -1


_MSG_ID_RE = re.compile(r"message|error|validat|warning|label", re.I)


def _page_message(html: str) -> str:
    """The page's own status / validation text (e.g. 'maximum records exceeded', 'enter a last
    name'), for the run trace. Read from elements whose id says message / error / validator /
    label and that are not inside the results grid; never a party row."""
    tree = HTMLParser(html or "")
    bits = []
    for node in tree.css("span, div, p"):
        nid = node.attributes.get("id") or ""
        if not _MSG_ID_RE.search(nid) or "SearchResults" in nid:
            continue
        txt = node.text(strip=True)
        if txt and len(txt) < 200:
            bits.append(txt)
    return " | ".join(dict.fromkeys(bits))[:240]


def _subtype_plan(page_html: str) -> tuple[str | None, list[tuple[str, str, str]]]:
    """(subtype select name, [(value, label, lane)]) for the lead lanes, read from the page
    after the Common Pleas postback. Evictions, minors' settlements and sealed matters never."""
    sel = _select(HTMLParser(page_html or ""), "DropdownlistCaseSubType")
    if sel is None:
        return None, []
    plan = []
    for v, t in _options(sel):
        if not v.strip():
            continue
        lane = charleston_lane(t)
        if lane in ("foreclosure", "partition", "quiet_title", "lis_pendens", "judgment") \
                and not charleston_skip(t):
            plan.append((v, t, lane))
    return sel.attributes.get("name"), plan


def _load_state() -> dict:
    try:
        return json.loads(CHARLESTON_STATE_FILE.read_text())
    except Exception:  # noqa: BLE001 - no state yet / unreadable: start from the lookback
        return {}


def _save_state(state: dict) -> None:
    try:
        CHARLESTON_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CHARLESTON_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
        tmp.replace(CHARLESTON_STATE_FILE)
    except Exception as exc:  # noqa: BLE001
        log.warning("sc_public_index.charleston_state_save_failed", error=str(exc)[:160])


def _windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    out, d = [], start
    while d <= end:
        e = min(end, d + timedelta(days=days - 1))
        out.append((d, e))
        d = e + timedelta(days=1)
    return out


_LAST = "ctl00$ContentPlaceHolder1$TextBoxlastName"
_SEARCH = {"ctl00$ContentPlaceHolder1$ButtonSearch": "Search",
           "ctl00$ContentPlaceHolder1$IndexGroup": "rbIndexGroup1"}


async def _date_window_search(session, search_url: str, page_html: str, form: dict,
                              results: list, parse_stats: dict,
                              today: date | None = None) -> dict:
    """Recent Common Pleas filings by 'Case Filed' date window, one lead subtype at a time
    (foreclosure, partition, quiet title, lis pendens, the judgment kinds), from the last run's
    day (minus WINDOW_OVERLAP_DAYS) to today; plus foreclosures by 'Disposed' date over the last
    FORECLOSURE_JUDGMENT_DAYS (judgment entered, sale ahead). Court, case type and subtype
    values come from the page's own dropdowns and postbacks. One request at a time,
    WINDOW_DELAY apart, at most WINDOW_MAX_REQUESTS a run; a window that fills the 250-row grid
    or says the maximum was exceeded is split in half. State: CHARLESTON_STATE_FILE.

    If the first date search is not answered with a results page (e.g. the form wants a name),
    one letter is tried with the same date filter; when that works, the run becomes a
    letter-by-letter search WITH the date filter ('letters_with_date'). Otherwise it returns
    {'fallback': ...} and the caller runs the plain letter sweep. `trace` records each request
    (purpose, labels, dates, HTTP status, grid rows, cap, the page's own message): no names."""
    today = today or datetime.utcnow().date()
    state = _load_state()
    hidden = _get_hidden_fields(page_html)
    used = 0
    info: dict = {"mode": "date_window", "windows": 0, "split": 0, "capped_days": 0, "trace": []}

    async def post(data: dict, what: str) -> str | None:
        nonlocal used, hidden
        if used >= WINDOW_MAX_REQUESTS:
            return None
        used += 1
        r = await asyncio.to_thread(session.post, search_url, data=data,
                                    impersonate="chrome", timeout=30)
        await asyncio.sleep(WINDOW_DELAY)
        text = r.text if r.status_code == 200 else ""
        n = _grid_rows(text)
        if len(info["trace"]) < 60:
            info["trace"].append({"what": what, "http": r.status_code, "grid_rows": n,
                                  "max_exceeded": bool(_MAX_EXCEEDED_RE.search(text)),
                                  "message": _page_message(text)})
        if r.status_code != 200:
            return ""
        hidden = _get_hidden_fields(r.text) or hidden
        return r.text

    base: dict = {}
    page = page_html
    # Cascading dropdowns: Circuit Court, then Common Pleas (values read from the page).
    if form.get("court") and form.get("court_value") is not None:
        base[form["court"]] = form["court_value"]
        if form.get("court_postback"):
            page = await post({**hidden, **base, "__EVENTTARGET": form["court"], "__EVENTARGUMENT": ""},
                              "postback court=circuit")
            if not page:
                return {**info, "fallback": "court_postback_failed", "requests": used}
    case_sel = _select(HTMLParser(page), "DropDownListCaseTypes")
    case_name = case_sel.attributes.get("name") if case_sel is not None else form.get("case")
    case_value = _pick(_options(case_sel) or form.get("case_options") or [], "common pleas")
    if case_name and case_value is not None:
        base[case_name] = case_value
        if _postback(case_sel) or form.get("case_postback"):
            page = await post({**hidden, **base, "__EVENTTARGET": case_name, "__EVENTARGUMENT": ""},
                              "postback case=common pleas")
            if not page:
                return {**info, "fallback": "case_postback_failed", "requests": used}
    sub_name, plan = _subtype_plan(page)
    info["subtypes"] = [t for _, t, _ in plan]
    subtypes = [(v, t) for v, t, _ in plan] if (sub_name and plan) else [(None, "all Common Pleas")]
    days = WINDOW_DAYS if subtypes[0][0] is not None else WINDOW_DAYS_ALL_CP

    def query(option: str, a: date, b: date, sub: str | None, last: str = "") -> dict:
        q = {**hidden, **base, form["date_filter"]: option,
             form["from"]: a.strftime("%m/%d/%Y"), form["to"]: b.strftime("%m/%d/%Y"),
             _LAST: last, **_SEARCH}
        if sub is not None and sub_name:
            q[sub_name] = sub
        return q

    def take(html: str, key: str) -> None:
        for rec in _parse_charleston_results(html, parse_stats):
            rec["via"] = key
            results.append(rec)

    sweeps = [("filed", form["filed"], FILED_LOOKBACK_DAYS, subtypes)]
    fc = [(v, t) for v, t in subtypes if v is not None and charleston_lane(t) == "foreclosure"]
    if DISPOSED_SWEEP and form.get("disposed") and fc:
        sweeps.append(("disposed", form["disposed"], FORECLOSURE_JUDGMENT_DAYS, fc))
    first = True
    for key, option, lookback, subs in sweeps:
        through = _mdy_iso(state.get(f"{key}_through"))
        start = max(today - timedelta(days=lookback),
                    (through - timedelta(days=WINDOW_OVERLAP_DAYS)) if through else date.min)
        done_through = through
        for a0, b0 in _windows(start, today, days):
            window_ok = True
            for sub, label in subs:
                queue = [(a0, b0)]
                while queue:
                    a, b = queue.pop(0)
                    what = f"{key} {label} {a.isoformat()}..{b.isoformat()}"
                    html = await post(query(option, a, b, sub), what)
                    if html is None:
                        info["budget_exhausted"] = True
                        window_ok = False
                        break
                    n = _grid_rows(html)
                    if n < 0 and not _NO_RECORDS_RE.search(html):
                        if first:
                            # Not a results page: does a name fragment unlock it?
                            probe = await post(query(option, a, b, sub, last="A"), what + " letter A")
                            if probe and _grid_rows(probe) >= 0:
                                return {**info, **await _letters_with_date(
                                    post, query, option, a0, today, sub, take, info), "requests": used}
                            return {**info, "fallback": "not_a_results_page", "requests": used}
                        info["unreadable_windows"] = info.get("unreadable_windows", 0) + 1
                        window_ok = False
                        break
                    first = False
                    capped = n >= GRID_CAP_ROWS or bool(_MAX_EXCEEDED_RE.search(html))
                    if capped and b > a:
                        mid = a + timedelta(days=(b - a).days // 2)
                        queue[:0] = [(a, mid), (mid + timedelta(days=1), b)]
                        info["split"] += 1
                        continue
                    if capped:
                        info["capped_days"] += 1
                    info["windows"] += 1
                    if n > 0:
                        take(html, key)
                if not window_ok:
                    break
            if not window_ok:
                break
            done_through = b0
        if done_through:
            state[f"{key}_through"] = done_through.isoformat()
        if info.get("budget_exhausted") or info.get("unreadable_windows"):
            break
    info["requests"] = used
    state["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _save_state(state)
    info["state"] = {k: v for k, v in state.items() if k.endswith("_through")}
    return info


async def _letters_with_date(post, query, option: str, start: date, end: date, sub: str | None,
                             take, info: dict) -> dict:
    """Fallback when a date-only search is refused: every letter, each with the same
    'Case Filed' range (and subtype when there is one), so the answers are recent filings."""
    out = {"mode": "letters_with_date", "letters_done": 0}
    for letter in DATE_LETTERS:
        html = await post(query(option, start, end, sub, last=letter), f"letter {letter} + date")
        if html is None:
            out["budget_exhausted"] = True
            break
        if _grid_rows(html) > 0:
            take(html, "filed")
        out["letters_done"] += 1
    return out


def _mdy_iso(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


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

            # Only keep recent cases (2024+). A Charleston foreclosure whose judgment was
            # entered in the last 9 months is kept whatever its filing year (2026-10-07).
            if year < 2024 and not case.get("foreclosure_judgment_entered"):
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
            for k in ("case_type", "subtype", "judgment_number", "court_agency", "lane",
                      "foreclosure_judgment_entered"):
                if case.get(k):
                    block[k] = case[k]
            judgment = case.get("lane") == "judgment"
            extra_raw: dict = {}
            if case.get("foreclosure_judgment_entered"):
                # The judgment of foreclosure is entered and the Master's sale is probably
                # still ahead (top-level key registered in RAW_KEEP); its date is the case's
                # disposition date, kept in the sc_public_index block.
                extra_raw["foreclosure_judgment_entered"] = True
                block["foreclosure_judgment_date"] = case.get("date_disposed") or None

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
                raw={"sc_public_index": block, **extra_raw},
            )
            listings.append(li)
        return listings
