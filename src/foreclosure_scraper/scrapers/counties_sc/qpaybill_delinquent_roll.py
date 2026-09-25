"""qPayBill county tax portals -> the SC DELINQUENT REAL-PROPERTY ROLL, with dollars.

WHY THIS SOURCE EXISTS AT ALL
    SC runs an ADMINISTRATIVE delinquent-tax sale: no lawsuit, no docket, no party
    list, no order of sale. There is nothing to read the way an NC tax-foreclosure
    docket can be read, which is why 30 of SC's 46 counties sat at zero rows while
    having configured scrapers -- the county HTML pages those scrapers point at carry
    a notice and a sale date, and the property list only appears for a few weeks a
    year, as a PDF, if at all.

    The treasurer's own PAYMENT portal does not work that way. Its search is live
    year-round, it is authoritative (it IS the tax system), and it answers the
    question the tax-sale PDFs cannot: HOW MUCH IS OWED, AND FOR HOW MANY YEARS.

WHAT A ROW CARRIES (grid columns, verified live 2026-09-10 on Barnwell)
    Notice No. | Name / Property Address | Year | Description | Identification No.
              | Type | Status | Payment Date | Amount
    Column 1 is exactly ``OWNER NAME<br/>PROPERTY ADDRESS``, so owner and situs
    split on the tag rather than by guessing where a house number starts. Column 4
    is the TMS. Column 3 is a truncated "PROP OF <prior owner>" description.

    Searching PaidStatus=Unpaid + SearchType=RealEstate + Year=All therefore yields,
    per parcel, every unpaid year -- and a parcel appearing for two or more years is
    the two-year-plus delinquency this engine already scores as strong distress.

ENUMERATION: PAGE FOR BREADTH, THEN DEEPEN FOR CORRECTNESS
    Map Number and Property Address search require EXACT values -- prefix queries on
    both return zero rows (measured). Owner Name is a STARTS-WITH match, results come
    back alphabetically, and the grid pages at 25.

    THE PAGER WORKS BUT IS LOSSY, AND DOES NOT KNOW IT
        __EVENTTARGET = ctl00$MainContent$gvSearchResults, __EVENTARGUMENT = Page$N
        pages the grid, and a page returning fewer than 25 rows is the last one.
        Measured against a deep-prefix sweep of the same county on the same day:

            paging 36 letters to exhaustion  ->   804 parcels,   69 requests
            prefix deepening to 3 characters ->   925 parcels, 1224 requests
            in prefix and NOT in pager: 124        in pager and NOT in prefix: 3

        The pager reported errors=0, letters_retried=0, pager_stalled=0 while missing
        124 parcels -- 13% of the county. Rows are not returned in a stable order
        across postbacks, so page 2 can skip what page 1 also skipped, and no
        self-check inside a paging chain can see it. A source that looks healthy while
        dropping an eighth of a county is worse than one that fails loudly.

    SO NEITHER METHOD IS USED ALONE. Both run and the results are UNIONED:
      * every prefix is paged to exhaustion -- cheap, and the pages reveal which
        SECOND characters actually occur under that prefix;
      * a prefix that filled a page is then deepened, but ONLY into the next
        characters observed in its own pages plus everything alphabetically at or
        after the last name seen (the unread tail). Expanding into all 36 was what
        made the prefix-only sweep cost 1,224 requests; most of those 36 return zero.

    Completeness is therefore observed, not assumed: a prefix is finished when a page
    comes back under the cap AND its deepened children are finished, and anything
    still capped at max depth is logged by name rather than quietly dropped.

WHAT IS NOT DONE HERE
    The grid also renders a "View" detail link and an "Add to Cart" button. This
    reads the public search grid only. Nothing in this module opens the cart, the
    payment flow, or any authenticated path.

    THE DETAIL PAGE IS NOT A DEAD END. An earlier version of this docstring said it was,
    and committed that claim. It was wrong, and the way it was wrong is worth keeping:

        the grid's link is  href="TaxesDetailsType4.aspx?receiptNo=...&recID=..."
        which is RELATIVE TO /Taxes/ -- the search page lives at /Taxes/TaxesDefaultType4.aspx.
        It was joined to the HOST ROOT instead, producing /TaxesDetailsType4.aspx, which the
        server answers with a 5,713-byte page whose body is the single word ERROR. That was
        read as "the portal refuses detail requests" rather than "I asked for the wrong URL".
        Opening the real link in a browser worked instantly.

    A wrong URL join wrote off a whole data layer for 19 counties. Resolve links against the
    PAGE's URL, never the host root.

    WHAT THE DETAIL PAGE CARRIES (verified live on 4 Barnwell records, 2026-09-10):
        Total Appraisal       the county's own 100%-basis value -- the CAD number the entire
                              buy-box rests on. The county coverage matrix has VALUE at 1% in
                              Oconee, 3% Union, 22% Laurens, 32% Anderson; this fills it.
        Assessment Ratio      4% = owner-occupied legal residence, 6% = everything else. SC law
                              sets these, so the ratio is an AUTHORITATIVE owner-occupancy flag
                              -- i.e. a free absentee-owner signal on every parcel. Verified to
                              vary in the real data: 3 of 4 sampled were 6%, one was 4% and
                              carried a $26.11 residential exemption to match.
        Total Assessed, Land Appraisal, Building Appraisal, Acres, Buildings count
        Description           the FULL legal/mobile-home description; the grid truncates it
                              ("PROP OF HORACE AB...") and the detail page does not
        Property Address, plus the tax breakdown: County Tax, City Tax, Fees, Residential and
        Homestead Exemptions, Local Option Credit, Penalty, Cost, Total

    STILL NOT THERE: the owner's MAILING address. That part of the old note holds. The route to
    SC owner mailing remains the county assessor card keyed by the TMS this source supplies.

    COST: one request per parcel. That is why detail is a SECOND, OPT-IN pass
    (QPAYBILL_ROLL_DETAIL=1, or QPAYBILL_ROLL_DETAIL_MAX to bound it) rather than part of the
    sweep -- roughly 15,000 parcels across 19 counties would otherwise double the run.

WHAT THIS SOURCE DOES AND DOES NOT GIVE
    gives    parcel/TMS, owner name (100%), situs address (~57%), balance owed,
             years unpaid, two-year-plus flag, statuses, notice numbers
    does NOT give   owner phone, owner mailing address
    So it closes the SIGNAL and IDENTITY layers for these counties and leaves the
    CONTACT layer where it was. Said plainly rather than implied, because a source
    that fills three layers of five is easy to mistake for coverage.

COUNTIES: started at 19, all verified live 2026-09-10 to return parseable Unpaid
RealEstate rows with dollar amounts; grown since (2026-09-13/15, 2026-09-23) as
more counties were found on the same vendor -- see QPAYBILL_SUBS itself for the
per-addition dates/evidence rather than trusting this count to stay current.
Subdomain naming is inconsistent (several patterns), so the map is explicit
rather than derived. Five were already known to enrichment_qpaybill_tax; the
rest were found by probing SC counties against the observed subdomain patterns
or by reading each county's own treasurer page for its "pay taxes online" link.

2026-09-23: Greenwood was probed for this item (docs/coverage_gap_build_plan_
2026-09-23.md item 6) and is a CONFIRMED MISS, not an unexplored gap -- its tax
payment/search system is entirely on corebtpay.com (a different vendor, Core's
egov.com platform: greenwoodco.corebtpay.com/egov/apps/...), with no qPayBill or
Catalis subdomain found anywhere on greenwoodcounty-sc.gov's own tax-collector
and pay-online pages. Do not re-probe qPayBill subdomain guesses for Greenwood.

    Identification-No. FORMAT VARIES BY COUNTY and is deliberately NOT normalised
    here. This module is a lead SOURCE: it emits the portal's own id as parcel_id
    together with the county, which is what the resolver and dedupe want. The
    enricher's join problem -- matching a portal id to a parcel_id that arrived from
    a different source -- is a separate concern and is not solved by pretending the
    formats agree. Observed: dashed 4-group (Barnwell 056-00-00-035), 5-group (Lee
    043-00-00-284-000), SPACE-delimited (Chesterfield 259 003 008 005), letters
    embedded (Lancaster 0141H-0A-020.00), trailing dot (McCormick 154-03-01-012.),
    manufactured-home suffix (Newberry 256-1-4-28-MHN1627), and plain numeric
    (Orangeburg 2082143 -- which is an account id, not a parcel, so Orangeburg rows
    carry it as an account reference and no parcel claim).

ROBOTS / ACCESS POSTURE, checked 2026-09-10
    No robots.txt on either host checked (both 404) and no Terms page (302). No
    login, no CAPTCHA, no rate limiting observed. This is the same public search
    endpoint this repo's enrichment_qpaybill_tax has queried in production since
    2026-07-01; this module reuses its parser rather than writing a second one.

Free, public, no login.
Slug: counties_sc.qpaybill_delinquent_roll
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import defaultdict
from datetime import datetime, date
from typing import Iterable

import httpx
import structlog

from html import unescape as html_unescape

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_qpaybill_tax import _UA, _hidden, _url

log = structlog.get_logger()

#: county -> qPayBill subdomain. Every one verified live 2026-09-10 to return
#: parseable Unpaid RealEstate rows. Naming follows no single rule, hence explicit.
QPAYBILL_SUBS: dict[str, str] = {
    # already known to enrichment_qpaybill_tax
    "Spartanburg": "spartanburgcountytax",
    "Oconee": "oconeesctax",
    "Laurens": "laurenstreasurer",
    "Union": "uniontreasurer",
    "Cherokee": "cherokeecountysctax",
    # found 2026-09-10 by probing all 46 SC counties
    "Abbeville": "abbevilletreasurer",
    "Allendale": "allendaletreasurer",
    "Barnwell": "barnwelltreasurer",
    "Calhoun": "calhountreasurer",
    "Chesterfield": "chesterfieldcountytax",
    "Clarendon": "clarendoncountysctax",
    "Darlington": "darlingtontreasurer",
    "Lancaster": "lancastersctax",
    "Lee": "leetreasurer",
    "Marlboro": "marlborocountytax",
    "McCormick": "mccormicktreasurer",   # NOT "Mccormick" — .title() strikes again
    "Newberry": "newberrytreasurer",
    "Orangeburg": "orangeburgtreasurer",
    "Williamsburg": "williamsburgtreasurer",
    # --- 2026-09-13: qPayBill covers 27 SC counties, not 19 ----------------------
    # Found by working the "14 SC counties with ZERO board rows" gap, NOT by
    # guessing: Lexington's own property-search page links out to
    # lexingtoncountytreasurer.qpaybill.com, which proved the roster was short.
    # Probing every SC county against the vendor's subdomain patterns turned up
    # eight more live portals. Each one verified to serve the SAME Type4 search
    # form this scraper posts to (SearchType / ddlCriteriaList / ddlYearList /
    # PaidStatus all present), so they need no new parsing code.
    #
    # Horry is the prize: Myrtle Beach, one of the largest counties in the state.
    # Bamberg, Kershaw, Lexington and Saluda were at ZERO rows on the board;
    # Marion and Sumter had one row each.
    #
    # Hampton is DELIBERATELY ABSENT. hamptontreasurer.qpaybill.com answers 200 but
    # the body is an "Object moved / Error" stub with no form — a portal that exists
    # in name only. Listing it would have manufactured a county that reports zero
    # rows forever and looks like a scraper bug.
    "Bamberg": "bambergcountytreasurer",
    "Colleton": "colleton",
    "Horry": "horrycountytreasurer",
    "Kershaw": "kershawcounty",
    "Lexington": "lexingtoncountytreasurer",
    # 2026-09-15: found while scoping a paystar.io build for Jasper (which runs
    # jaspercountysc's CURRENT-year property/vehicle payment portal on a totally
    # different vendor). Jasper's own site links a SEPARATE "Pay Delinquent Taxes"
    # button straight to jaspercountydelinquenttax.qpaybill.com -- the delinquent
    # roll was on THIS vendor all along, just under a subdomain this module's
    # roster never probed. Verified live: same Type4 form (ddlCriteriaList/
    # ddlYearList/PaidStatus/SearchType all present), same sweep_county() path,
    # zero code changes needed. Full-budget sweep (2500): 1,517 parcels, 0 errors,
    # 5 prefixes depth-truncated (DUPO/HAMI/MILL/RIVE/SCOT) -- per this module's
    # own measured finding above, deepening those recovers ~0 net-new rows.
    "Jasper": "jaspercountydelinquenttax",
    # Marion is DELIBERATELY ABSENT, same reason as Hampton but a different failure.
    # marioncounty.qpaybill.com is a fully working portal — correct Type4 form, all
    # the right fields, 200 on every request — that simply has NO DATA. Verified
    # 2026-09-13 through the scraper's own _walk_prefix: 0 rows for every prefix
    # tried, for radUnpaid AND radPaid AND radAll, and for all four search types
    # (RealEstate, Personal, Vehicle, Watercraft). The first harvest spent 36 queries
    # on it and returned 0 parcels.
    #
    # A county that is listed but can never produce a row is worse than an absent
    # one: it reads as a scraper bug forever and invites someone to "fix" a portal
    # that has nothing in it. Re-test before re-adding.
    "Saluda": "saludacountytreasurer",
    "Sumter": "sumtercounty",
    # 2026-09-23: probed the 17 counties docs/completeness_audit_2026-09-23.md
    # section 3 flags as missing the "tax delinquent" family
    # (docs/coverage_gap_build_plan_2026-09-23.md item 6). 11 of the 17 were
    # already in this dict (Abbeville/Allendale/Barnwell/Calhoun/Chesterfield/
    # Darlington/Lee/Marlboro/McCormick/Williamsburg/Bamberg) and 2 more
    # (Chester/Fairfield) are covered by counties_sc.sc_catalis_delinquent_roll
    # instead -- see that module's CATALIS_COUNTIES. Of the remaining 4
    # (Dillon, Dorchester, Edgefield, Greenwood), only these two were confirmed
    # LIVE qPayBill Type4 tenants; found via each county's own official
    # treasurer/tax-collector page (not guessed), then verified with a real
    # search + parse using this module's own parse_grid():
    #   Dillon     dilloncountysc.org/departments/treasurer.php links
    #              "https://dilloncountysctaxes.qpaybill.com/Taxes/
    #              TaxesDefaultType4.aspx" directly. prefix "S": 25 rows incl.
    #              notice 016962253-style Unpaid RealEstate; prefix "A": 23
    #              rows, e.g. ABRAHAM HARRY W, ident 138-00-00-047.001, a 2018
    #              (not just current-year) unpaid balance of $173.81.
    #   Edgefield  edgefieldcounty.sc.gov's own directory links "Online Tax
    #              Payment Center" -> "https://edgefieldcountysc.qpaybill.com/".
    #              prefix "A": 25 rows, e.g. ABNEY ANNIE T, ident
    #              185-00-01-031-000, $134.02 unpaid 2025.
    # Dorchester and Greenwood are NOT added here -- see sc_catalis_delinquent_
    # roll.py's CATALIS_COUNTIES comment (Dorchester) and this module's own
    # docstring update (Greenwood) for why.
    "Dillon": "dilloncountysctaxes",
    "Edgefield": "edgefieldcountysc",
}

#: Counties whose Identification-No. is an ACCOUNT id, not a parcel. Their rows are
#: still real delinquent-tax leads with an owner, a situs address and a balance, but
#: claiming the value as parcel_id would poison dedupe (which keys on
#: parcel:{state}:{county}:{p}) with ids that are not parcels.
ACCOUNT_ID_ONLY = {"Orangeburg"}

#: Observed grid page size. A result of exactly this many rows means "there are
#: probably more" and the prefix is deepened; fewer means the prefix is exhausted.
PAGE_CAP = 25

#: First characters an SC owner-name index actually starts with. Digits included:
#: entity names like "2ND CHANCE LLC" are on these rolls.
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

#: Paging bound per prefix. Barnwell's busiest letter needed 3 pages; 200 is far
#: above any real county roll and exists only so a misbehaving pager cannot spin.
MAX_PAGES_PER_PREFIX = int(os.getenv("QPAYBILL_ROLL_MAX_PAGES", "200"))

#: How many characters deep the name prefixes may go. Depth 3 reached 925 of
#: Barnwell's parcels with 4 prefixes still capped; depth 4 exists for those.
#:
#: RAISED to 6 on 2026-09-13 and MEASURED BACK DOWN to 4 the same day. Read this
#: before raising it again.
#:
#: The reasoning for raising it was that prefixes still capped at the ceiling are
#: assigned to `frontier` and then dropped by the `while` condition, never walked.
#: That code reading is CORRECT and the warning below still matters. The MAGNITUDE
#: claim attached to it was not: it cited Spartanburg reading 10,094 rows in one run
#: and 12,256 in another as proof depth was costing thousands of rows. Those two runs
#: differed in BUDGET, not depth -- the second is the top-5 re-run at a raised
#: request budget. Two variables, one conclusion, wrong attribution.
#:
#: Measured properly, depth 6 against depth 4 at the SAME high budget:
#:     Orangeburg   6,669 -> 6,660 parcels   (-9)
#:     Spartanburg  4,789 -> 4,813 parcels   (+24)
#: for 6,872 seconds of runtime against 2,727. Depth buys nothing here because the
#: sweep dedupes by parcel and the deeper prefixes re-find parcels already read under
#: their parents. Both counties STILL reported unwalked prefixes at depth 6 (93 and
#: 68), which is the tell: those prefixes hold duplicates, not missing rows.
#:
#: THE BUDGET IS THE LEVER. roll_all -> the high-budget re-run is where the real gain
#: was: Orangeburg 5,495 -> 6,669 parcels, Spartanburg 4,069 -> 4,789. And unlike a
#: depth ceiling, REQUEST_BUDGET_PER_COUNTY says so when it stops early.
MAX_PREFIX_DEPTH = int(os.getenv("QPAYBILL_ROLL_DEPTH", "4"))

#: Hard request budget PER COUNTY, so a portal that starts returning the cap for
#: every prefix cannot turn this into an unbounded crawl -- and, because the counties
#: sweep concurrently, so a large county cannot spend the small ones' allowance. An
#: earlier draft shared one global budget across all 19, which meant Spartanburg
#: (330k people) could exhaust it before Williamsburg (30k) issued a single query,
#: and the shortfall would have looked like "Williamsburg has no delinquent roll".
#: Barnwell's full sweep cost 873; 2,500 leaves room for counties an order of
#: magnitude larger before truncation is even reported.
REQUEST_BUDGET_PER_COUNTY = int(os.getenv("QPAYBILL_ROLL_BUDGET", "2500"))

_PER_HOST_CONCURRENCY = 3

#: Second, opt-in pass: fetch each parcel's detail page for the county appraised value and the
#: 4%/6% owner-occupancy ratio. One request PER PARCEL, so it is off by default and bounded.
DETAIL_ENABLED = os.getenv("QPAYBILL_ROLL_DETAIL", "") not in ("", "0", "false", "False")
DETAIL_MAX = int(os.getenv("QPAYBILL_ROLL_DETAIL_MAX", "400"))

#: Ceiling across ALL counties at once. Nineteen counties x 3 = 57 simultaneous new
#: clients, each doing its own DNS lookup, and macOS's resolver started returning
#: "nodename nor servname provided" -- a transient failure that reads exactly like a
#: dead host. Capping the total keeps the sweep inside what the resolver will take.
#:
#: RAISED 12 -> 24 on 2026-09-25 alongside MAX_CONCURRENT_COUNTIES below -- read that
#: constant's docstring first, this one only covers why 24 and not something larger.
#: MEASURED live against the real vendor same day: a burst of 24 concurrent GETs
#: spread over 8 different county subdomains returned 24/24 HTTP 200 in 1.57s wall
#: clock, and a second burst of 15 concurrent GETs against ONE busy subdomain
#: (spartanburgcountytax) returned 15/15 HTTP 200 in 1.54s -- no 429/403, no elevated
#: per-request latency versus a single request (~0.6-1.5s solo). 24 was kept even after
#: MAX_CONCURRENT_COUNTIES was tuned down to 4 (see that constant's docstring for why
#: an exact match left stragglers and headroom fixed it): 4 x _PER_HOST_CONCURRENCY (3)
#: = 12 of these 24 slots, so an active county now has room to spare rather than being
#: sized to the ragged edge. Nothing here was pushed past what was actually measured;
#: raise it further only after measuring a bigger burst the same way.
_GLOBAL_CONCURRENCY = int(os.getenv("QPAYBILL_ROLL_CONCURRENCY", "24"))
_GLOBAL_SEM: "asyncio.Semaphore | None" = None

#: How many counties may be ACTIVELY sweeping at once. This is the actual fix for the
#: 2026-09-25 incident: all 29 configured counties reported qpaybill_roll.county_timeout
#: in the SAME run, each logging errors=1 queries=0 -- not one slow county blocking the
#: rest (the 2026-09-23 bug this module already fixed), but EVERY county, including
#: ones that alone take well under a minute, making literally zero progress.
#:
#: MEASURED, same day, against the live vendor with the real (unmocked) sweep_county() --
#: three passes, because the first two fixes were each verified against the live site
#: before the next was applied, not assumed:
#:
#:   PASS 0 (diagnosis). Lee ALONE (no other county running): 46.3s wall clock, 225
#:     queries, 0 errors -- comfortably under COUNTY_TIMEOUT_S=480s, and its own
#:     throughput (225/46.3 = 4.86 req/s) is within noise of the historical 19-county
#:     CONCURRENT run's aggregate rate (26,750 requests / 5,581s = 4.79 req/s,
#:     logs/qpaybill_roll_all.log, 2026-09-10) -- adding 18 more counties on top of one,
#:     under the OLD fetch()-launches-everyone-at-once shape, bought almost no extra
#:     aggregate throughput. 8 small/medium counties launched CONCURRENTLY under that
#:     old shape (_GLOBAL_CONCURRENCY=12, no per-county gate): 3+ minutes wall clock
#:     with ZERO of the 8 complete -- not slower, STARVED.
#:
#:   PASS 1 (this gate alone, MAX_CONCURRENT_COUNTIES=8, matching the raised
#:     _GLOBAL_CONCURRENCY=24 exactly: 8 x 3 = 24). Re-testing the SAME 8 counties: a
#:     real, large improvement over pass 0 (4 of 8 now completed with real rows: Lee
#:     313.9s/225q, Union 324.9s/288q, Calhoun 413.7s/363q, Allendale 418.3s/389q, all
#:     0 errors) -- but the other 4 (Newberry, McCormick, Barnwell, Chesterfield) STILL
#:     had not finished at the 500s mark. Tracing why surfaced a SECOND bug (see
#:     guarded()'s docstring in sweep_county: the global semaphore was acquired before
#:     the per-host one, so one county's own 36-prefix depth-1 burst could hold up to
#:     36 global slots while only 3 could do anything, wasting the exact capacity this
#:     gate was sized against). Fixing that ordering and re-testing the SAME 8 counties
#:     at the SAME 8/24 sizing still left stragglers, because fetch()'s semaphore is a
#:     ROLLING window: the instant one of the first 8 finishes, a 9th queued county
#:     (there are 29 in production) fills the freed slot immediately, so a straggler
#:     from the first batch never actually gets relief -- exact-match sizing (demand ==
#:     capacity) leaves no slack for that.
#:
#:   PASS 2 (this gate lowered to 4, keeping _GLOBAL_CONCURRENCY=24 -- 2x headroom,
#:     4 x 3 = 12 of 24 slots): the SAME two counties re-measured, same live vendor,
#:     same session: Lee 175.7s (was 313.9s), Union 188.3s (was 324.9s) -- roughly 1.8x
#:     faster with headroom than with an exact-match cap, both comfortably clear of
#:     COUNTY_TIMEOUT_S=480s. (Absolute times are noisier than pass-to-pass RATIOS here:
#:     a concurrent, must-not-touch board-apply process on this machine was measured
#:     using anywhere from ~0% to 63% CPU across these passes, so none of these numbers
#:     should be read as a precise vendor throughput figure -- the direction, gate
#:     narrower than capacity beats gate matching capacity exactly, held consistently.)
#:
#: THE FIX: cap how many counties may be inside sweep_county() at once, so an ACTIVE
#: county's own _PER_HOST_CONCURRENCY (3) slots aren't diluted by every OTHER county's
#: prefix walks too, WITH SLACK rather than an exact match, because the rolling window
#: means a straggler never gets the relief exact-match sizing implicitly assumes. The
#: semaphore is acquired BEFORE run_county()'s own asyncio.wait_for(..., COUNTY_TIMEOUT_S)
#: starts its clock, so a county queued behind others is not charged for the wait --
#: only its own active sweep time counts against the per-county bound. Counties still
#: queue up (29 counties / 4 lanes = a little over 7 rounds through the whole roster),
#: which is MORE wall clock than the old all-at-once launch, but every county now has a
#: real chance to finish inside COUNTY_TIMEOUT_S instead of every county guaranteed to
#: starve past it -- this is deliberately the "reduce how many counties launch
#: concurrently, trade wall clock for actually finishing some of them" direction, not a
#: raised timeout papering over a genuine hang.
#:
#: Must NOT be raised back toward "launch everyone" (or even back to an exact 8 x 3 == 24
#: match) without re-measuring: that is exactly what reproduced the 2026-09-25
#: all-29-timeout failure and, at pass 1's sizing, half of an 8-county re-test.
MAX_CONCURRENT_COUNTIES = int(os.getenv("QPAYBILL_ROLL_COUNTY_CONCURRENCY", "4"))
_COUNTY_SEM: "asyncio.Semaphore | None" = None


def _county_sem() -> "asyncio.Semaphore":
    global _COUNTY_SEM
    if _COUNTY_SEM is None:
        _COUNTY_SEM = asyncio.Semaphore(MAX_CONCURRENT_COUNTIES)
    return _COUNTY_SEM

#: Per-COUNTY wall-clock bound, independent of REQUEST_BUDGET_PER_COUNTY (which counts
#: requests, not seconds, and caps at 2,500 regardless of how long each one takes).
#:
#: PROVEN AGAINST A LIVE FAILURE, full run 2026-09-23: the scraper hit its OWN
#: timeout_s=900.0 (TIMEOUT after exactly 901s) and captured ZERO fresh rows across
#: ALL 19 counties -- not "the stuck county got 0", every county did, including ones
#: that almost certainly finished in the first minute. Williamsburg has repeatedly hit
#: GenericErrorPage.aspx in production logs, which is consistent with a portal that
#: answers on every request (so _require_ok never raises) but never satisfies
#: _all_match / never drains its own retry loop -- a county that can occupy its worker
#: for the entire scraper timeout without ever raising an exception the old code could
#: catch. Nothing upstream of this constant bounded a single county's WALL-CLOCK time;
#: only its request COUNT was bounded, and a slow-but-answering host can spend all
#: 2,500 requests at any latency at all.
#:
#: Set comfortably under timeout_s so a hung county is skipped well before the
#: scraper-level cutoff, leaving the other counties' already-collected rows to be
#: reported (see QPayBillDelinquentRoll.fetch, which now salvages per county as each
#: one finishes rather than only after every county has finished).
COUNTY_TIMEOUT_S = float(os.getenv("QPAYBILL_ROLL_COUNTY_TIMEOUT", "480"))


def _global_sem() -> "asyncio.Semaphore":
    global _GLOBAL_SEM
    if _GLOBAL_SEM is None:
        _GLOBAL_SEM = asyncio.Semaphore(_GLOBAL_CONCURRENCY)
    return _GLOBAL_SEM
_OWED_STATUSES = ("unpaid", "sold at tax sale", "delinquent", "bankruptcy")


def parse_grid(html: str) -> list[dict]:
    """Parse the results grid into owner/address-split rows.

    Deliberately separate from enrichment_qpaybill_tax._parse_rows, which keeps only
    {tms, year, status, amount} because a balance is all an enricher needs. A lead
    source needs the owner, the situs address and the notice number too, and column
    1 splits exactly on the ``<br/>`` the portal emits.
    """
    out: list[dict] = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(tds) < 9:
            continue

        def clean(x: str) -> str:
            x = re.sub(r"(?i)<br\s*/?>", "\n", x)
            x = re.sub(r"<[^>]+>", " ", x)
            x = (x.replace("&amp;", "&").replace("&nbsp;", " ")
                  .replace("&#39;", "'").replace("&quot;", '"'))
            return re.sub(r"[ \t]+", " ", x).strip()

        name_addr = clean(tds[1])
        ident = clean(tds[4])
        amt_m = re.search(r"\$([\d,]+\.\d{2})", clean(tds[8]))
        if not (ident and amt_m):
            continue
        amount = float(amt_m.group(1).replace(",", ""))
        # qPayBill placeholder / misfire values, same guards the enricher uses.
        if amount <= 0 or amount == 99999.00 or amount >= 1_000_000:
            continue
        status = clean(tds[6])
        if status and not any(s in status.lower() for s in _OWED_STATUSES):
            continue

        parts = [p.strip() for p in name_addr.split("\n") if p.strip()]
        owner = parts[0] if parts else None
        address = _clean_situs(parts[1] if len(parts) > 1 else None)
        # The row's own detail link, kept on the row so the optional detail pass never has to
        # reconstruct a URL. Reconstructing it is exactly how it got joined to the wrong base.
        href_m = re.search(r'href="(TaxesDetailsType4\.aspx\?[^"]+)"', row, re.I)
        out.append({
            "detail_href": html_unescape(href_m.group(1)) if href_m else None,
            "notice_no": clean(tds[0]) or None,
            "owner": owner,
            "address": address,
            "year": clean(tds[2]) or None,
            "description": clean(tds[3]) or None,
            "ident": ident,
            "status": status or None,
            "amount": amount,
        })
    return out


class _Budget:
    """Shared request budget. Counting requests rather than time keeps a slow portal
    from starving the other eighteen, and makes truncation reportable."""

    def __init__(self, total: int) -> None:
        self.left = total
        self.spent = 0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.spent += 1
        return True


#: The GridView that renders results. Its postback target is what pages the grid.
_GRID_TARGET = "ctl00$MainContent$gvSearchResults"

_SEARCH_FIELDS = {
    "ctl00$MainContent$SearchType": "radRealEstateButton",
    "ctl00$MainContent$PaidStatus": "radUnpaidButton",
    "ctl00$MainContent$ddlYearList": "All",
    "ctl00$MainContent$ddlCriteriaList": "Name",
}


def _vs(html: str) -> dict:
    return {"vs": _hidden(html, "__VIEWSTATE"),
            "gen": _hidden(html, "__VIEWSTATEGENERATOR"),
            "ev": _hidden(html, "__EVENTVALIDATION")}


async def _post(client: httpx.AsyncClient, sub: str, vs: dict, prefix: str,
                page: int | None) -> tuple[list[dict], dict]:
    """One search (page=None) or one pager step (page=N). Returns (rows, new_vs)."""
    data = {
        "__EVENTTARGET": _GRID_TARGET if page else "",
        "__EVENTARGUMENT": f"Page${page}" if page else "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": vs["vs"], "__VIEWSTATEGENERATOR": vs["gen"],
        "__EVENTVALIDATION": vs["ev"],
        **_SEARCH_FIELDS,
        "ctl00$MainContent$txtCriteriaBox": prefix,
    }
    if not page:
        data["ctl00$MainContent$btnSearch"] = "Search"
    resp = await client.post(_url(sub), data=data)
    _require_ok(resp, sub, prefix)
    return parse_grid(resp.text), _vs(resp.text)


class QPayBillUnavailable(RuntimeError):
    """The portal answered, but not with data. Distinct from 'this prefix has no rows'."""


def _require_ok(resp, sub: str, prefix: str) -> None:
    """A non-2xx must NEVER reach parse_grid.

    PROVEN AGAINST A LIVE OUTAGE, 2026-09-13 01:15. All five qPayBill tenants answered
    HTTP 503 with a 123,600-byte maintenance page. parse_grid() returns 0 rows from it
    and _vs() still finds __VIEWSTATE tokens in it, so the page looks structurally valid.
    With no status check the sweep would have logged, for all 19 counties:

        county_done  parcels=0  queries=N  errors=0

    -- a clean bill of health for a run that collected nothing. That is the same silent
    shape as the Catalis 429 handled in sc_catalis_delinquent_roll, and this sibling was
    never given the same guard. An outage must surface as an error the caller retries and
    the log names, not as an empty county.
    """
    if resp.status_code >= 400:
        raise QPayBillUnavailable(
            f"{sub} returned HTTP {resp.status_code} for prefix {prefix!r} "
            f"({len(resp.content):,} bytes) — portal unavailable, NOT an empty result")


async def _fresh_vs(client: httpx.AsyncClient, sub: str) -> dict:
    r = await client.get(_url(sub))
    _require_ok(r, sub, "<viewstate>")
    return _vs(r.text)


def _all_match(rows: list[dict], prefix: str) -> bool:
    """Every owner on the page must still start with the prefix we asked for. A page
    that drifts means the viewstate chain is carrying somebody else's search, and
    accepting it would file another letter's parcels under this one."""
    up = prefix.upper()
    return all((r.get("owner") or "").upper().startswith(up) for r in rows)


def _absorb(rows: list[dict], sink: dict) -> None:
    """Keyed on (ident, year, notice) so the two enumeration strategies can be
    unioned without double-counting a row either of them read."""
    for r in rows:
        sink[(r["ident"], r.get("year") or "", r.get("notice_no") or "")] = r


async def _walk_prefix(client: httpx.AsyncClient, sub: str, prefix: str,
                       budget: "_Budget", sink: dict, stats: dict) -> tuple[bool, set]:
    """Search one prefix and page it to exhaustion.

    Returns (needs_deepening, next_chars). `next_chars` is the set of characters to
    deepen into: those actually observed after this prefix in the rows we read, plus
    every character at or after the last one seen, since anything past the last name
    on the last page we managed to read is unread rather than absent.
    """
    # A prefix abandoned on one exception is a whole initial silently missing from the
    # county, with nothing but an errors counter to show it. Observed live: two
    # transient macOS DNS failures ("nodename nor servname provided") dropped letters
    # A and B outright. So retry with backoff, and if it still fails, name the prefix
    # in the log so the hole is identifiable rather than merely counted.
    rows = None
    vs = None
    for attempt in range(3):
        if not budget.take():
            return False, set()
        try:
            vs = await _fresh_vs(client, sub)
            if not vs["vs"]:
                raise RuntimeError("no __VIEWSTATE on the search page")
            rows, vs = await _post(client, sub, vs, prefix, None)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                stats["errors"] += 1
                stats.setdefault("lost_prefixes", []).append(prefix)
                log.warning("qpaybill_roll.search_lost", prefix=prefix,
                            attempts=3, error=str(exc)[:120],
                            note="this prefix contributed NOTHING; the county roll is "
                                 "incomplete for owners whose name starts with it")
                return False, set()
            await asyncio.sleep(1.5 * (attempt + 1))
    if rows is None:
        return False, set()
    stats["queries"] += 1
    if rows and not _all_match(rows, prefix):
        stats["drifted"] += 1
        return True, set(_ALPHABET)      # cannot trust this chain; deepen widely
    _absorb(rows, sink)
    seen_chars, last_char = _next_chars(rows, prefix)
    capped = len(rows) >= PAGE_CAP

    page = 1
    while len(rows) >= PAGE_CAP:
        if page >= MAX_PAGES_PER_PREFIX:
            stats["page_capped_prefixes"] += 1
            log.warning("qpaybill_roll.page_cap", prefix=prefix, pages=page)
            break
        if not budget.take():
            break
        page += 1
        before = len(sink)
        try:
            rows, vs = await _post(client, sub, vs, prefix, page)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log.warning("qpaybill_roll.page_fail", prefix=prefix, page=page,
                        error=str(exc)[:120])
            break
        stats["queries"] += 1
        if rows and not _all_match(rows, prefix):
            stats["drifted"] += 1
            break
        _absorb(rows, sink)
        more, lc = _next_chars(rows, prefix)
        seen_chars |= more
        last_char = lc or last_char
        if len(sink) == before and rows:
            stats["pager_stalled"] += 1
            break

    if not capped:
        return False, set()
    # Deepen into observed children plus the unread alphabetical tail.
    tail = set()
    if last_char:
        idx = _ALPHABET.find(last_char)
        tail = set(_ALPHABET[idx:]) if idx >= 0 else set(_ALPHABET)
    return True, (seen_chars | tail) or set(_ALPHABET)


def _next_chars(rows: list[dict], prefix: str) -> tuple[set, str | None]:
    """Characters that follow `prefix` in these owners, and the last one seen."""
    n = len(prefix)
    chars = set()
    last = None
    for r in rows:
        name = (r.get("owner") or "").upper()
        if len(name) > n:
            ch = name[n]
            if ch in _ALPHABET:
                chars.add(ch)
                last = ch
    return chars, last


async def sweep_county(client: httpx.AsyncClient, county: str, sub: str,
                       budget: "_Budget") -> tuple[list[dict], dict]:
    """Union sweep of one county: page every prefix, deepen the capped ones.

    `client` is accepted for call-site symmetry but intentionally unused. Every
    prefix opens its OWN client, hence its own cookie jar: measured 2026-09-10,
    three letters paging concurrently through one shared client returned 789 of
    Barnwell's 925 parcels, because qPayBill holds the grid's paging state
    server-side against the session and a Page$2 issued for letter G could be
    answered with letter M's rows. The _all_match guard caught the crossover, so the
    loss surfaced as retries rather than as wrong data, but the rows behind the
    rejected pages were never read.
    """
    sink: dict[tuple[str, str, str], dict] = {}
    stats: dict = {"queries": 0, "errors": 0, "page_capped_prefixes": 0,
                   "pager_stalled": 0, "drifted": 0, "deepened": 0,
                   "truncated_prefixes": 0, "lost_prefixes": []}
    sem = asyncio.Semaphore(_PER_HOST_CONCURRENCY)

    async def guarded(prefix: str) -> tuple[str, bool, set]:
        # PER-HOST FIRST, THEN GLOBAL -- the order used to be reversed
        # (``async with _global_sem(), sem:``), and that ordering compounded the
        # 2026-09-25 starvation this module now guards against with
        # MAX_CONCURRENT_COUNTIES (see that constant's docstring above sweep_county
        # for the full incident). A county's depth-1 frontier submits up to 36
        # `guarded()` calls to asyncio.gather() AT ONCE; with the global semaphore
        # acquired first, all 36 raced to grab a GLOBAL slot immediately, but only
        # `_PER_HOST_CONCURRENCY` (3) of them could ever do anything useful once they
        # had one -- the rest sat there HOLDING a scarce global slot while blocked on
        # this county's OWN per-host cap, which is pure waste: MAX_CONCURRENT_COUNTIES
        # x _PER_HOST_CONCURRENCY == _GLOBAL_CONCURRENCY only holds as a real bound on
        # simultaneous global-slot demand if a county can never have more than
        # _PER_HOST_CONCURRENCY coroutines contending for a global slot at once.
        # Acquiring the free, per-county `sem` FIRST enforces exactly that: at most 3
        # of a county's own prefix walks are ever waiting on _global_sem() at a time,
        # so an active county's real global-slot demand matches what it was sized for.
        async with sem, _global_sem():
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                         headers={"User-Agent": _UA}) as own:
                deeper, chars = await _walk_prefix(own, sub, prefix, budget,
                                                   sink, stats)
                return prefix, deeper, chars

    frontier = list(_ALPHABET)
    depth = 1
    while frontier and depth <= MAX_PREFIX_DEPTH:
        results = await asyncio.gather(*(guarded(p) for p in frontier))
        nxt = [p + ch for p, deeper, chars in results if deeper for ch in sorted(chars)]
        stats["deepened"] += len(nxt)
        if nxt and depth >= MAX_PREFIX_DEPTH:
            stats["truncated_prefixes"] = len({p[:-1] for p in nxt})
            # These prefixes are NEVER walked -- the `while` condition drops the
            # frontier on the next turn. Everything under them past the parent's
            # first pages is missing from the roll, so this is row LOSS, not a
            # cosmetic cap. Phrased loudly because the old wording ("still filling
            # pages") read like a tuning note and got ignored for weeks.
            log.warning("qpaybill_roll.depth_truncated", county=county, depth=depth,
                        unwalked_prefixes=stats["truncated_prefixes"],
                        prefixes=sorted({p[:-1] for p in nxt})[:12],
                        note="these prefixes are never read. Measured 2026-09-13: at "
                             "the same budget, raising depth recovered ~0 parcels, so "
                             "these are usually duplicates already read under a parent. "
                             "If a county looks short, raise QPAYBILL_ROLL_BUDGET FIRST.")
        frontier = nxt
        depth += 1
    return list(sink.values()), stats


_DETAIL_HREF_RE = re.compile(r'href="(TaxesDetailsType4\.aspx\?[^"]+)"', re.I)



_ZERO_TOKEN_RE = re.compile(r"\s+0+$")
_ALL_ZEROS_RE = re.compile(r"0+")


def _clean_situs(addr: str | None) -> str | None:
    """Drop the zero-padded city/ZIP columns qPayBill appends to the situs line.

    Several of these portals render an absent city and ZIP as literal zeros, so the
    address cell reads "128 PHOENIX LN 00000 0000" or "9523 HWY 260 0 0000". Stored
    as-is that is not an address: it fails geocoding, it defeats dedupe (two rows for
    the same house differ by their padding), and it prints on a call sheet as
    something a person cannot drive to. 4,327 rows were already on the board this way
    — 3,060 of them Spartanburg — before this was caught on 2026-09-13.

    Only tokens made ENTIRELY of zeros are removed, and only from the END, so a real
    house number ("0 MAIN ST", which vacant parcels genuinely use) and a road name
    carrying digits ("HWY 260", "S-40-0") are both untouched. If nothing survives,
    return None rather than an empty string, so the row reports having no address
    instead of appearing to have a blank one.
    """
    if not addr:
        return None
    out = addr.strip()
    while True:
        stripped = _ZERO_TOKEN_RE.sub("", out)
        if stripped == out:
            break
        out = stripped.strip()
    # A line that was NOTHING but padding ("00000 0000") reduces to a lone "00000"
    # here, because the regex needs leading whitespace to cut a token. That is not an
    # address either, so it goes too.
    if not out or _ALL_ZEROS_RE.fullmatch(out):
        return None
    return out


def _detail_url(sub: str, href: str) -> str:
    """Resolve a grid detail link.

    THE bug this function exists to prevent: the href is relative to /Taxes/, because the search
    page is /Taxes/TaxesDefaultType4.aspx. Joining it to the host root yields a page whose body is
    the single word ERROR, which reads exactly like a refusal. Always resolve against the page.
    """
    href = html_unescape(href).lstrip("/")
    if href.lower().startswith("taxes/"):
        href = href[len("taxes/"):]
    return f"https://{sub}.qpaybill.com/Taxes/{href}"


def parse_detail(text: str) -> dict:
    """Fields off one detail page. Returns {} when the page is not a real record.

    Parsed from the page's visible text rather than its markup: the layout is a stack of
    label/value pairs whose surrounding tags differ between counties, but the LABELS are stable.
    """
    flat = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    flat = html_unescape(re.sub(r"<[^>]+>", "\n", flat))
    flat = re.sub(r"[ \t]+", " ", flat)
    if "Notice #" not in flat and "Balance Due" not in flat:
        return {}

    def after(label: str) -> str | None:
        m = re.search(re.escape(label) + r"\s*\n?\s*([^\n]{0,80})", flat)
        if not m:
            return None
        v = m.group(1).strip().strip(":").strip()
        return v or None

    def money(label: str) -> float | None:
        v = after(label)
        m = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", v or "")
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    # "Assessment Ratio:" sits above a 3-value row: ratio | land appraisal | building appraisal.
    ratio = None
    rm = re.search(r"\n\s*(\d{1,2})%\s*\n", flat)
    if rm:
        ratio = int(rm.group(1))

    out = {
        "appraised_value": money("Total Appraisal:"),
        "assessed_value": money("Total Assessed:"),
        "assessment_ratio_pct": ratio,
        # SC: 4% is the owner-occupied legal-residence ratio, 6% is everything else. So a 6%
        # parcel is NOT the owner's residence -- a free, authoritative absentee signal.
        "owner_occupied": (ratio == 4) if ratio in (4, 6) else None,
        "acres": after("Acres:"),
        "buildings": after("Buildings:"),
        "record_type": after("Record Type:"),
        "map_number": after("Map Number:"),
        "legal_description": after("Description:"),
        "residential_exemption": money("Residential Exemption:"),
        "homestead_exemption": money("Homestead Exemption:"),
        "county_tax": money("County Tax:"),
        "penalty": money("Penalty:"),
        "cost": money("Cost:"),
        "issue_date": after("Issue Date:"),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


async def fetch_details(client: httpx.AsyncClient, sub: str, hrefs: list[str],
                        budget: "_Budget", stats: dict) -> dict[str, dict]:
    """Fetch detail pages, keyed by receiptNo so they join back to the grid rows."""
    got: dict[str, dict] = {}
    sem = asyncio.Semaphore(_PER_HOST_CONCURRENCY)

    async def one(href: str) -> None:
        if not budget.take():
            return
        receipt = ""
        m = re.search(r"receiptNo=([^&\"]+)", href)
        if m:
            receipt = m.group(1)
        async with sem:
            try:
                r = await client.get(_detail_url(sub, href))
                d = parse_detail(r.text)
                if d:
                    got[receipt] = d
                else:
                    stats["detail_empty"] = stats.get("detail_empty", 0) + 1
            except Exception as exc:  # noqa: BLE001
                stats["detail_errors"] = stats.get("detail_errors", 0) + 1
                log.warning("qpaybill_roll.detail_fail", receipt=receipt,
                            error=str(exc)[:120])

    await asyncio.gather(*(one(h) for h in hrefs))
    return got


def _acres(v) -> float | None:
    """'.83' / '48.40' / '.00' -> float. '.00' means the county records no acreage, not zero land."""
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None



def _delinquent_years(years: list[str], today: date | None = None) -> list[str]:
    """Keep only tax years that are actually PAST DUE.

    SC bills a tax year in the autumn and it falls due 15 January of the FOLLOWING
    year, so an unpaid bill for tax year Y is not a delinquency until Y+1. A portal
    that has already loaded the current year therefore reports thousands of ordinary
    owners as "Unpaid" months before they owe anything.

    This is not hypothetical. Colleton's portal had the 2026 year loaded when it was
    first harvested on 2026-09-13: 18,199 of its 18,289 parcels carried a 2026
    unpaid year and 16,790 carried NOTHING ELSE, at a median balance of $504 — an
    ordinary annual tax bill. Every other county in the same sweep reported ~0 rows
    for 2026. Ingesting that would have put ~16,790 people on a distressed-property
    board for not having paid a bill that was not yet due, and made Colleton one of
    the largest "distressed" counties in the dataset.

    Rule: a tax year counts only once the calendar has passed it. In February 2026 a
    2025 bill IS delinquent (it was due 15 January); in September 2026 a 2026 bill is
    not. Conservative at the 1 Jan - 15 Jan boundary, which is the right direction to
    err: a missed real delinquency costs a lead, a fabricated one costs a phone call
    to someone who owes nothing.
    """
    cutoff = (today or date.today()).year
    out = []
    for y in years:
        try:
            if int(y) < cutoff:
                out.append(y)
        except (TypeError, ValueError):
            continue          # unparseable year — cannot prove it is past due
    return out


def _to_listings(county: str, rows: list[dict]) -> list[Listing]:
    """One Listing per PARCEL, with the unpaid years aggregated onto it.

    The portal returns a row per unpaid YEAR, so a two-year delinquency arrives as
    two rows for the same id. Emitting them separately would put the same property
    on the board twice and hide the strongest signal in the data; aggregating makes
    years_delinquent and the total balance explicit.
    """
    by_ident: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ident[r["ident"]].append(r)

    out: list[Listing] = []
    now = datetime.utcnow()
    account_only = county in ACCOUNT_ID_ONLY
    for ident, group in by_ident.items():
        group.sort(key=lambda g: (g.get("year") or ""))
        all_years = sorted({g["year"] for g in group if g.get("year")})
        # A CURRENT-YEAR bill is not a delinquency. See _delinquent_years().
        years = _delinquent_years(all_years)
        if not years:
            continue
        total = round(sum(g["amount"] for g in group
                          if (g.get("year") or "") in years), 2)
        owner = next((g["owner"] for g in group if g.get("owner")), None)
        address = next((g["address"] for g in group if g.get("address")), None)
        prior = next((g["description"] for g in group if g.get("description")), None)
        det = {}
        for g in group:
            if isinstance(g.get("detail"), dict) and g["detail"]:
                det = g["detail"]
                break
        out.append(Listing(
            source="counties_sc.qpaybill_delinquent_roll",
            source_url=_url(QPAYBILL_SUBS[county]),
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county=county,
            parcel_id=None if account_only else ident,
            defendant=owner,
            owner_name=owner,
            street_address=address,
            description=(f"Delinquent property tax: ${total:,.2f} owed"
                         + (f" for {len(years)} year(s) ({', '.join(years)})" if years else "")
                         + (f" — {prior}" if prior else "")),
            first_seen=now,
            last_seen=now,
            raw={"qpaybill_roll": {
                "identification_no": ident,
                "is_account_id_not_parcel": account_only,
                "county": county,
                "subdomain": QPAYBILL_SUBS[county],
                "owner": owner,
                "property_address": address,
                "balance_owed": total,
                "years_unpaid": years,
                "all_unpaid_years": all_years,   # incl. any not-yet-due current year
                "years_delinquent": len(years),
                "is_two_year_plus": len(years) >= 2,
                "statuses": sorted({g["status"] for g in group if g.get("status")}),
                "notice_numbers": [g["notice_no"] for g in group if g.get("notice_no")][:6],
                "prior_owner_description": prior,
                "rows": len(group),
                # Detail-pass fields (empty unless QPAYBILL_ROLL_DETAIL=1). appraised_value is
                # the county's own 100%-basis number; owner_occupied comes from SC's statutory
                # 4%-legal-residence vs 6%-everything-else assessment ratio.
                **({"detail": det} if det else {}),
            }},
            tax_value=det.get("appraised_value"),
            acreage=_acres(det.get("acres")),
            legal_description=det.get("legal_description"),
        ))
    return out


class QPayBillDelinquentRoll(BaseScraper):
    slug = "counties_sc.qpaybill_delinquent_roll"
    name = "SC qPayBill Delinquent Real-Property Roll (19 counties)"
    category = "county_tax"
    timeout_s = 900.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("QPAYBILL_ROLL_COUNTIES") or "").split(",") if c.strip()}
        targets = {k: v for k, v in QPAYBILL_SUBS.items() if not only or k in only}
        budgets = {c: _Budget(REQUEST_BUDGET_PER_COUNTY) for c in targets}
        t0 = time.monotonic()
        log.info("qpaybill_roll.start", counties=len(targets),
                 budget_per_county=REQUEST_BUDGET_PER_COUNTY,
                 max_pages=MAX_PAGES_PER_PREFIX, max_depth=MAX_PREFIX_DEPTH,
                 county_timeout_s=COUNTY_TIMEOUT_S,
                 max_concurrent_counties=MAX_CONCURRENT_COUNTIES,
                 global_concurrency=_GLOBAL_CONCURRENCY)

        out: list[Listing] = []
        per_county: dict[str, int] = {}
        detail_rows: dict[str, list[dict]] = {}
        kept_idents: dict[str, set] = {}

        _EMPTY_STATS = {"queries": 0, "errors": 1, "page_capped_prefixes": 0,
                        "pager_stalled": 0, "drifted": 0, "deepened": 0,
                        "truncated_prefixes": 0, "lost_prefixes": []}

        async def run_county(client: httpx.AsyncClient, county: str, sub: str
                             ) -> tuple[str, list[dict], dict]:
            """One county's sweep, gated by MAX_CONCURRENT_COUNTIES and individually
            bounded to COUNTY_TIMEOUT_S once it actually starts.

            This is now TWO fixes stacked, for two different failures:

              2026-09-23 (all-19-counties-return-zero): REQUEST_BUDGET_PER_COUNTY
              bounds how many requests a county can spend, not how long it can take
              doing it -- a portal that answers slowly but never errors (Williamsburg's
              GenericErrorPage.aspx pattern) could occupy a worker for the scraper's
              entire soft timeout on its own. COUNTY_TIMEOUT_S wraps that county's
              sweep so it can never do that: it either finishes, or it is abandoned and
              reported as failed, releasing control back to fetch() so other counties
              are never held hostage to ONE stuck one.

              2026-09-25 (all-29-counties-time-out): fixing the above did not fix a
              DIFFERENT failure -- every county launched via asyncio.ensure_future at
              once, competing for the same 12-slot _GLOBAL_SEM, so NO county (not even
              ones that finish in under a minute alone) made meaningful progress before
              COUNTY_TIMEOUT_S fired on all of them. See MAX_CONCURRENT_COUNTIES's
              docstring for the measurements. The `async with _county_sem():` below
              gates entry so at most MAX_CONCURRENT_COUNTIES counties are ever inside
              sweep_county() together; it is acquired BEFORE the wait_for below starts
              its clock, so a county queued behind others is not charged timeout budget
              for time spent waiting its turn -- only its own active sweep counts.
            """
            async with _county_sem():
                try:
                    rows, stats = await asyncio.wait_for(
                        sweep_county(client, county, sub, budgets[county]),
                        timeout=COUNTY_TIMEOUT_S)
                    return county, rows, stats
                except asyncio.TimeoutError:
                    log.warning("qpaybill_roll.county_timeout", county=county,
                                timeout_s=COUNTY_TIMEOUT_S,
                                note="this county alone exceeded its bounded per-county "
                                     "timeout and was skipped for this run; it must never "
                                     "be allowed to hold every OTHER county's already-"
                                     "collected rows hostage to the scraper's soft timeout")
                    return county, [], dict(_EMPTY_STATS, county_timed_out=True)
                except Exception as exc:  # noqa: BLE001
                    log.warning("qpaybill_roll.county_failed", county=county,
                                error=str(exc)[:140])
                    return county, [], dict(_EMPTY_STATS)

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as client:
            tasks = [asyncio.ensure_future(run_county(client, county, sub))
                     for county, sub in sorted(targets.items())]
            # SALVAGE AS EACH COUNTY COMPLETES, not only after every county has.
            #
            # The old shape was `results = await asyncio.gather(*(sweep_county(...) for
            # ...))` followed by a loop that built `out` from `results` -- so nothing
            # was collected until ALL 19 counties' coroutines had resolved. base_scraper
            # .safe_run() wraps the whole fetch() in asyncio.wait_for(..., timeout=
            # self.timeout_s); when that fired mid-gather it cancelled fetch() before
            # the loop ever ran, so the 18 counties that HAD already finished were
            # thrown away with the one that had not. fetch() also never touched
            # self.partial, so safe_run()'s own timeout-salvage path (see its
            # docstring: "A scraper that appends here as it goes will have that work
            # SHIPPED") had nothing to ship. asyncio.as_completed fixes the first half
            # by processing each county's result the moment it is ready; appending to
            # self.partial here fixes the second half, so even if a pathological case
            # still runs past timeout_s, whatever finished by then is not lost.
            for finished in asyncio.as_completed(tasks):
                county, rows, stats = await finished
                detail_rows[county] = rows
                listings = _to_listings(county, rows)
                per_county[county] = len(listings)
                out.extend(listings)
                self.partial.extend(listings)
                # Idents that SURVIVED _to_listings. The detail pass below must not spend
                # its budget on rows this county already discarded — see the note there.
                kept_idents[county] = {
                    (li.raw.get("qpaybill_roll") or {}).get("identification_no")
                    for li in listings
                    if isinstance(li.raw, dict)
                } - {None}
                lost = stats.pop("lost_prefixes", [])
                log.info("qpaybill_roll.county_done", county=county,
                         parcels=len(listings), rows=len(rows),
                         lost_prefixes=len(lost), **stats)
                if lost:
                    log.warning("qpaybill_roll.county_incomplete", county=county,
                                prefixes=sorted(lost),
                                note="owners whose name starts with these were never "
                                     "read; this county's roll is INCOMPLETE")

        # OPT-IN DETAIL PASS. One request per parcel, so it is bounded and it spends its budget
        # on the LARGEST BALANCES first -- if only 400 of a county's parcels can be detailed, the
        # $19,000 arrears should be among them and the $12 should not.
        if DETAIL_ENABLED and detail_rows:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                         headers={"User-Agent": _UA}) as dclient:
                for county, rows in sorted(detail_rows.items()):
                    # DETAIL ONLY WHAT SURVIVED THE FILTER.
                    #
                    # This pass runs on the RAW grid rows, but _to_listings has already
                    # dropped every parcel whose only unpaid year is the current one
                    # (an SC bill is not late until 15 January of the following year).
                    # Colleton 2026-09-13: 18,285 raw idents -> 1,494 real delinquents.
                    # Detailing the raw set spent a 3,000-request budget almost entirely
                    # on parcels that were then discarded, and returned value on 98.
                    #
                    # An earlier attempt deduped per parcel on the theory that the grid
                    # returned ~14 rows per parcel. It does not — 20,876 rows over
                    # 18,285 idents is 1.14 — so that fix bought nothing. The waste was
                    # never duplication; it was ORDERING.
                    keep = kept_idents.get(county)
                    with_href = [r for r in rows if r.get("detail_href")
                                 and (not keep or r.get("ident") in keep)]
                    with_href.sort(key=lambda r: -(r.get("amount") or 0))
                    # ONE DETAIL PER PARCEL, not per row.
                    #
                    # The grid returns a row per unpaid YEAR, so a parcel 14 years
                    # behind appears 14 times — and the detail page yields the
                    # APPRAISED VALUE, which is a property attribute, not a per-year
                    # one. Fetching it once per row bought the same number 14 times.
                    #
                    # Measured on Colleton 2026-09-13: 20,895 rows for 1,495 parcels.
                    # A 4,000-request detail pass spent itself on the highest-arrears
                    # rows, which are exactly the parcels with the MOST duplicate
                    # years, and came back with value on 136 parcels. Deduping first
                    # covers all 1,495 for ~1,495 requests.
                    #
                    # The highest-amount row per parcel is kept, so the sort above
                    # still decides which parcels are reached when the cap bites.
                    seen_ident: set[str] = set()
                    unique_rows = []
                    for r in with_href:
                        key = r.get("ident") or r["detail_href"]
                        if key in seen_ident:
                            continue
                        seen_ident.add(key)
                        unique_rows.append(r)
                    picked = unique_rows[:DETAIL_MAX]
                    if not picked:
                        continue
                    dstats: dict = {}
                    got = await fetch_details(dclient, QPAYBILL_SUBS[county],
                                              [r["detail_href"] for r in picked],
                                              budgets[county], dstats)
                    for r in rows:
                        rec = re.search(r"receiptNo=([^&]+)", r.get("detail_href") or "")
                        if rec and rec.group(1) in got:
                            r["detail"] = got[rec.group(1)]
                    filled = sum(1 for r in rows if r.get("detail"))
                    log.info("qpaybill_roll.detail_done", county=county,
                             requested=len(picked), parsed=len(got), rows_filled=filled,
                             skipped_over_cap=max(0, len(unique_rows) - DETAIL_MAX),
                             rows=len(with_href), parcels=len(unique_rows), **dstats)
            out = []
            for county, rows in sorted(detail_rows.items()):
                got = _to_listings(county, rows)
                per_county[county] = len(got)
                out.extend(got)

        starved = sorted(c for c, b in budgets.items() if b.left <= 0)
        if starved:
            log.warning("qpaybill_roll.budget_exhausted", counties=starved,
                        note="these counties hit their per-county request budget and "
                             "their rolls are INCOMPLETE. Raise QPAYBILL_ROLL_BUDGET.")
        log.info("qpaybill_roll.done", parcels=len(out),
                 requests=sum(b.spent for b in budgets.values()),
                 seconds=round(time.monotonic() - t0, 1),
                 per_county=per_county)
        return out
