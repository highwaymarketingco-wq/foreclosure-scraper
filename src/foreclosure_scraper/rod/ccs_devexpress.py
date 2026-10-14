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

IREDELL (NC) -- added 2026-10-14, SAME session this module was built in,
driven over the owner's own live, already-reCAPTCHA-cleared browser-pane tab
(origin `iredellnc.courthousecomputersystems.com`) rather than a fresh
nodriver/Playwright session -- every finding below is from real in-page JS
run against that cleared tab, same "driven as in-page DOM calls on an
already-cleared tab" convention as Jasper above, just executed interactively
instead of from a Python caller (no automated harness in this codebase can
reach a human-cleared CCS session directly; `nc_rod_captcha.py`'s own
Playwright `page` is how a real scrape run will drive this same module).

Confirmed the SAME platform as Jasper (`#subapp_LRSearch_0` iframe,
`levelTab_Advanced`, `#DocTypes` hidden field + `#doctypes_dialog` picker,
`#btnAdvancedSearch`, `#gridTrad`, `[id*="PagerBarTNext"]`, and the exact
same `ccs-home_ui_helper.js` heartbeat bundle -- see "SESSION-REUSE WINDOW"
below) -- this is one vendor product reused county-to-county, confirming the
task's premise that wiring a new county is mostly configuration, not a
rebuild. But two real structural differences surfaced, live, that this pass
generalized the module to handle rather than special-cased per county:

1. **DIFFERENT column layout, not just different codes.** Iredell's own
   `#gridTrad` header row was read live (`td[class*="_Header"]`, e.g.
   `Cell_Grantor_Header`/`Cell_Book_Header`/`Cell_DocNo_Header`/
   `Cell_MapID_Header` -- a vendor-provided, semantically-named CSS class
   per column, `Cell_<Field>_Header`) and does NOT match Jasper's fixed
   positions at all: Iredell uses plain, SEPARATE `Grantor`/`Grantee` name
   columns (no role prefix -- the column itself IS the role), while Jasper
   uses a SINGLE combined `"<or|ee>\t<name>"` cell per party column. Real
   live column map, Iredell (`#DocTypes`="LIEN,LIS/P,FCL,S/TR,BKCY,JGMT",
   2026-10-14): `{"RowNumber":2,"RecordChanged":3,"Image":4,"Date":5,
   "Kind":6,"Grantor":7,"Grantee":8,"Description":9,"Book":10,"Page":11,
   "DocNo":15,"MapID":16}` (17 cells total, 0-16) -- Jasper's own fixed
   positions (Book=5/Page=6/Kind=7/Party1=8/Party2=11/Date=14/
   Description=15/Seq=16/DocNo=17/TaxMap=18) simply do not apply.
   `parse_grid_row()` now takes an optional `header_map` (built live by
   `_SEARCH_JS` from these real `Cell_<Field>_Header` classes, NOT guessed
   or hand-maintained per county) and resolves each logical field through
   it, falling back to Jasper's original fixed positions (`_FALLBACK_INDEXES`)
   ONLY when no `header_map` is given at all -- every call site written
   before this pass (Jasper's own, and this file's own pre-existing tests)
   never passes one, so Jasper's already-tested behavior is byte-for-byte
   unchanged. A future county's own column order is simply read the same
   way, live, rather than re-derived by hand.
2. **The reCAPTCHA clearance does NOT survive a fresh tab/navigation.**
   Live-tested directly, not assumed: a brand-new tab to the same origin
   (same browser profile, so any ordinary cookie would already be present)
   re-showed the real "Please Verify You are Not a Robot" modal and the
   Land Records subapp genuinely never loaded (`#gridTrad` absent) --
   `document.cookie` on that fresh tab carries only client-preference
   cookies (`user_preferences`/`custom_list`/`terminal_id`), no visible
   session id (consistent with an httpOnly session cookie OR a session
   that is simply never granted to a tab that never itself solved the
   challenge). This means the clearance is a property of THIS SPECIFIC
   already-loaded page/tab, not something a scraper can carry into a fresh
   `page.goto()` navigation the way Wake's/Durham's own Tyler Self-Service
   cookie does. Operationally this matters: `_fetch_iredell` (see
   `nc_rod_captcha.py`) must drive the SAME already-gate-cleared Playwright
   `page` object in place via in-page JS only, exactly like this module's
   own `_SEARCH_JS` already does for Jasper -- it must never
   `page.goto()`/reload once past the gate.

Doc Types dictionary -- read live from the real `#DocTypes` picker
(`bookTypes` select + its checkbox list), same method as Jasper's own build,
NOT assumed from Jasper's dictionary: Iredell's "REAL ESTATE"/"All Doc Types"
book type exposes 113 real short codes (`DEED OF TRUST`/`CHATTEL MTG`/
`CEMETERY RECORDS`/`CONDO`/`NOTARY`/`PLAT`/`RIGHT OF WAY` are each their own,
much narrower, book type -- switching the dialog's Book Type dropdown
live-confirmed each one exposes a DIFFERENT, non-overlapping code subset,
same live UI trap Jasper's own docstring already flagged). Genuinely
DIFFERENT vocabulary from Jasper's, not the same codes under new names: NO
DETH/DETH-DB (death certificate) equivalent exists anywhere in Iredell's
dictionary at all (NC counties evidently don't index vital records through
this ROD platform the way Jasper's SC one does) -- a real, honestly-flagged
coverage gap, not silently dropped. In exchange Iredell's dictionary HAS
real foreclosure-process codes Jasper's SC dictionary has NONE of (Jasper's
own docstring: "NO 'FORECLOSURE'/'TRUSTEE'S DEED' kind at all"): `FCL`
(literal FORECLOSURE) and `S/TR` (SUBSTITUTE TRUSTEE, the same NC
pre-foreclosure signal `nc_rod_logan.py`'s own FCL/S-TR codes and Wake's
"SUBSTITUTE TRUSTEE"/"FORECLOSURE NOTICE" doc types already capture
elsewhere in this codebase), plus `JGMT` (judgment) and `BKCY`
(bankruptcy), neither of which Jasper's dictionary carries either.
`IREDELL_DISTRESS_DOC_CODES = ("LIEN", "LIS/P", "FCL", "S/TR", "BKCY",
"JGMT")` -- live-confirmed via the picker's own hidden-field echo, same
method as Jasper's 6 codes. `classify_kind_code()` was extended (not
replaced) with new `"foreclosure"`/`"pre_foreclosure"`/`"judgment"`/
`"bankruptcy"` buckets alongside the existing `"probate"`/`"lien"`/
`"lis_pendens"` ones -- ONE shared code->bucket table across both counties,
safe because no code was ever seen meaning two different things (only
different SPELLINGS for the same concept: Jasper's `LPEN` vs. Iredell's
`LIS/P`, both `lis_pendens` -- merged into the same bucket, not duplicated
logic).

Real live samples, 90-day window (07/16-10/14/2026) unless noted, Book Type
REAL ESTATE:
- FCL: Book 3238/Page 1295, DocNo 2000008318, grantor AGUILERA RAFAEL /
  grantee MOVEMENT MORTGAGE LLC (9 party rows, same multi-grantor-rows-per-
  instrument shape Brunswick's own SUBSTITUTE TRUSTEE rows already use in
  this codebase) -- a real, individual pre-foreclosure lead.
- S/TR: Book 3238/Page 1416, DocNo 2000008331, grantor NEWREZ LLC / grantee
  MERCER JOHN M (6 party rows) -- here the LENDER chain is grantor and the
  homeowner is grantee, the OPPOSITE role convention from the FCL example
  above and from Wake's own S/TR rows elsewhere in this file -- confirms
  `_iredell_defendant()` cannot trust a fixed role and must prefer the
  non-institutional party either side, same defensive shape Jasper's own
  `_jasper_defendant()` already uses for this exact reason.
- BKCY: Book 3234/Page 2264, DocNo 2000006843, grantor BARTHELEMY NATASHA
  NICOLE / grantee "-----" (a real Chapter 13 filing, case B-26-50333C-13W
  in the Description cell, no real second party -- the dash is the
  platform's own placeholder, not a parse failure).
- JGMT: a REAL, mixed bucket -- live rows include both a genuine individual
  civil judgment (DELUCA STEPHEN B. vs. U.S. DISTRICT COURT MIDDLE DISTRICT
  OF FLORIDA) and several NCDOT eminent-domain condemnation judgments
  where "DEPARTMENT OF TRANSPORTATION" appears as BOTH grantor and
  grantee on self-referential index rows (Book 3229/Page 973, DocNo
  2000004514) alongside real affected owners (MILLS DON E. JR./MILLS
  KAREN C., Book 3231/Page 423) -- institutional-word filtering
  (`_brunswick_is_institutional`, shared with Wake/Brunswick) needed
  "department"/"transportation" added to its word list for exactly this
  live-observed noise; without it a government condemnation plaintiff
  would wrongly become the "defendant" lead.
- LIS/P: only ONE example surfaced in a wider 180-day sweep
  (04/17-10/14/2026), and it is a genuinely ambiguous one -- Book 3241/Page
  630, DocNo 2000009460, grantor AND grantee both "HYMAN JOSEPH EDWARD"
  (self-referential) with Description "CAN" (reads as a CANCELLATION of a
  prior lis pendens, not a fresh filing) -- flagged honestly as a thin,
  possibly-not-actionable sample, not claimed as a clean worked example the
  way Jasper's own LPEN code (never seen live at all) was flagged as
  code-only-confirmed.
- LIEN: ZERO live rows in EITHER window (90-day or the wider 180-day
  sweep) -- genuinely confirmed absent from live Iredell activity this
  pass, not an unchecked gap. The code stays in
  `IREDELL_DISTRESS_DOC_CODES` (live-confirmed to exist in the picker, same
  "code exists, no example surfaced yet" honesty convention as Jasper's own
  LPEN code) rather than being dropped for lack of a current example.

Document images: the per-document `/Image/ShowDocImage` endpoint is the
SAME controller action Jasper's own `jasper_doc_image` raw block already
targets -- confirmed live by actually opening one (Book 3238/Page 1220,
DocNo 2000008303, DEED): `GET /Image/ShowDocImage?DocNum=2000008303&
BookNum=3238&PageNum=1220&Kind=DEED&Date=09%2F01%2F2026&Referrer=r&
BookType=&SeqNum=0&TIF2PDF=true&SearchTabID=0&HideDetails=false`, a real
signed NC General Warranty Deed image (grantor/grantee signature blocks,
notary seal, full legal description exhibit), free, no further gate beyond
the same session -- it 200'd straight from the already-cleared tab and
redirected into a per-session `/ProcessedImages/<TerminalID>_doc_<id>.pdf`,
the same session-gated pattern Jasper's own `jasper_doc_image` block already
documents (a cold GET of that same URL from outside this exact cleared
session is expected to 403/redirect to the reCAPTCHA gate, same as Jasper --
not re-tested cold this pass to avoid spending the owner's own cleared
session on a negative control). Iredell's own live URL carries a few extra
query params (`Date`/`Referrer`/`BookType`/`SeqNum`) beyond Jasper's
already-shipped, already-tested URL -- `nc_rod_captcha.py`'s own
`_iredell_doc_to_listing` builds Iredell's URL with these confirmed params
rather than reusing Jasper's exact string (which was NOT re-verified live
this pass and is left untouched to avoid regressing already-shipped
behavior); a future pass, once a THIRD county confirms the same endpoint
shape again, can safely factor this into one shared builder.

SESSION-REUSE WINDOW -- same two-angle method as Jasper's and Wake's own
measurements, not assumed: (1) CODE EVIDENCE is IDENTICAL to Jasper's --
Iredell serves the exact same `ccs-home_ui_helper.js` bundle
(`timeoutLength = 43200000` [12h] -> `HomeUIHelper.StartHeartBeat` ->
`KeepSessionActive` on a 6-hour cadence), confirmed live by reading the
real inline script text, not assumed by platform match. (2) LIVE FLOOR:
`window.fetch`/`jQuery.ajax` were monkey-patched on the owner's own cleared
tab to block any `KeepSessionActive`/`pingSession`/`heartbeat`-matching
call (confirmed armed, 0 calls through it the entire window), then this
pass did its own real work (reading the doc-type dictionary, running
multiple live searches, writing and testing this module's code) on that
SAME tab for 679 seconds (11m19s, 2026-10-14) with ZERO heartbeat calls,
then issued ONE real, deliberate Advanced search (DocTypes=BKCY, a 2-week
window) at the end of that gap: it came back with live grid data (8 real
total records), not a reCAPTCHA/disclaimer redirect -- CONFIRMED FLOOR: at
least 11m19s of genuinely idle (zero client activity, heartbeat
deliberately disabled) session survival, live-verified, not assumed. This
is a STRONGER result than Wake's own 7m14s floor and in the same
architecture class as Jasper's own finding (shorter wall-clock than
Jasper's 22+ minutes only because this pass's own interactive live
debugging -- discovering the column-layout difference, the fresh-tab
re-gate behavior, the doc-type dictionary -- took real requests of other
kinds throughout most of the window; not pushed further to find the actual
ceiling, so report this as "at least ~11 minutes confirmed," not a tested
upper bound). Combined with the identical 12h/6h heartbeat architecture,
the same operational verdict as Jasper applies: an operator-cleared
Iredell session is NOT a short, Wake-style session -- it comfortably
survives a bounded scraper run once cleared, PROVIDED that run drives the
SAME tab in place (see the fresh-tab/navigation finding above for why
that proviso is load-bearing here specifically).
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timedelta
from typing import Any

import structlog

from .models import RodDoc

log = structlog.get_logger()

# (state, county) -> (host, app). Jasper (SC) + Iredell (NC) confirmed live
# on this DevExpress CCS product so far; app="" for a tenant hosted at the
# bare host with no per-county path segment (Iredell's own
# "iredellnc.courthousecomputersystems.com" vs. Jasper's
# "us6.courthousecomputersystems.com/JasperSC") -- see base_url() below.
CCS_DEVEXPRESS_COUNTIES: dict[tuple[str, str], tuple[str, str]] = {
    ("SC", "Jasper"): ("us6", "JasperSC"),
    ("NC", "Iredell"): ("iredellnc", ""),
}


def base_url(state: str, county: str) -> str | None:
    cfg = CCS_DEVEXPRESS_COUNTIES.get((state, county))
    if not cfg:
        return None
    host, app = cfg
    if not app:
        return f"https://{host}.courthousecomputersystems.com"
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
#: "LIS/P" is Iredell's own spelling of the same concept, added 2026-10-14
#: -- live-confirmed from its own #DocTypes picker echo (see module
#: docstring's "IREDELL" section), not guessed from Jasper's "LPEN".
_LIS_PENDENS_CODES = {"LPEN", "LPEN-DB", "LIS/P"}

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

#: Iredell's own live-confirmed distress codes (see module docstring's
#: "IREDELL" section) -- a genuinely DIFFERENT vocabulary from Jasper's, not
#: the same 6 codes renamed: Iredell has real FCL/S-TR/JGMT/BKCY codes
#: Jasper's SC dictionary has none of, and has NO DETH/death-certificate
#: equivalent at all (a real, flagged coverage gap, not silently dropped).
IREDELL_DISTRESS_DOC_CODES = ("LIEN", "LIS/P", "FCL", "S/TR", "BKCY", "JGMT")
IREDELL_DISTRESS_DOC_TYPE_NAMES = (
    "LIEN", "LIS PENDENS", "FORECLOSURE", "SUBSTITUTE TRUSTEE",
    "BANKRUPTCY", "JUDGMENT",
)
#: Same 90-day convention as Jasper. Live-confirmed 2026-10-14: the 6-code
#: 90-day sweep is 313 records / 63 documents / 21 pages at 15/page --
#: materially busier than Jasper's own 65/39/5, so the page budget below
#: gets real headroom (not just Jasper's 3x-over-need margin) rather than
#: being copied verbatim.
IREDELL_LOOKBACK_DAYS = 90
IREDELL_MAX_PAGES = 25
IREDELL_MAX_DOCS = 400


#: Header class-name field aliases -- `_SEARCH_JS` below builds a real,
#: live `header_map` (field name -> column index) from `#gridTrad`'s own
#: `Cell_<Field>_Header` header-cell CSS classes (see module docstring's
#: "IREDELL" section for the discovery that made this necessary: Iredell's
#: column layout is genuinely different from Jasper's, not just relabeled).
#: A logical field can have more than one real spelling across counties
#: (Iredell's own parcel column reads "MapID" on its own header class, not
#: "Parcel") -- tried in order, first match wins.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Parcel": ("MapID", "Parcel", "TaxMap", "PIN"),
}
#: Fallback cell indices for the ORIGINAL (Jasper) grid layout -- used ONLY
#: when a row is parsed with NO `header_map` at all (every call site
#: written before this pass, including this file's own pre-existing tests),
#: so Jasper's already-tested behavior stays byte-for-byte unchanged. When a
#: real `header_map` IS given (any county wired after this pass) and it
#: doesn't resolve a field, that field is genuinely absent for that county
#: (e.g. Iredell's grid exposes no stand-alone "Seq" column) rather than
#: silently defaulting to a position that may not even exist in that row.
_FALLBACK_INDEXES = {
    "Book": 5, "Page": 6, "Kind": 7, "Party1": 8, "Party2": 11,
    "Date": 14, "Description": 15, "Seq": 16, "DocNo": 17, "Parcel": 18,
}


#: NC foreclosure-process codes, live-confirmed on Iredell's own #DocTypes
#: dictionary 2026-10-14 -- Jasper's SC dictionary has NO equivalent
#: (Master-in-Equity deeds record there as a plain DEED, see above), so
#: these stay unused for Jasper and are additive, not a replacement.
_FORECLOSURE_CODES = {"FCL"}
_PRE_FORECLOSURE_CODES = {"S/TR"}
_JUDGMENT_CODES = {"JGMT"}
_BANKRUPTCY_CODES = {"BKCY"}


def classify_kind_code(kind: str | None) -> str | None:
    """'probate' | 'lien' | 'lis_pendens' | 'foreclosure' | 'pre_foreclosure'
    | 'judgment' | 'bankruptcy' | None, from the grid's own short Kind code
    (exact match against the live-confirmed codes above -- see module
    docstring). Unknown codes (routine filings: MTG, DEED, RELS, UCC, COR,
    SMTG, CAN*, SAT, ...) return None, same as every other non-distress
    kind in this codebase's ROD classifiers. ONE shared code->bucket table
    across every CCS DevExpress county wired so far (Jasper SC + Iredell
    NC) -- live-confirmed safe to share: no code was ever seen meaning two
    DIFFERENT things, only different SPELLINGS for the same concept
    (Jasper's "LPEN" vs. Iredell's "LIS/P", both lis_pendens -- merged into
    one bucket rather than duplicated per-county logic)."""
    k = (kind or "").strip().upper()
    if not k:
        return None
    if k in _PROBATE_CODES:
        return "probate"
    if k in _LIS_PENDENS_CODES:
        return "lis_pendens"
    if k in _FORECLOSURE_CODES:
        return "foreclosure"
    if k in _PRE_FORECLOSURE_CODES:
        return "pre_foreclosure"
    if k in _JUDGMENT_CODES:
        return "judgment"
    if k in _BANKRUPTCY_CODES:
        return "bankruptcy"
    if k in _LIEN_CODES:
        return "lien"
    return None


# --------------------------------------------------------------------------- #
# Row parsing -- one <tr>'s cell-text array -> a flat dict                    #
# --------------------------------------------------------------------------- #
# Jasper's OWN fixed column layout (no `header_map`, see _FALLBACK_INDEXES
# above), confirmed live 2026-10-14 by reading `gridTrad`'s real rendered
# rows (`Array.from(tr.querySelectorAll('td')).map(td => td.innerText.
# trim())`) across 20+ distinct real documents: index 5=Book, 6=Page,
# 7=Kind, 8="<or|ee>\t<name>" (party col 1, role + name joined by a literal
# tab in the SAME cell), 11="<or|ee>\t<name>" (party col 2, the reciprocal
# party), 14=Date (recorded), 15=Description (full legal description text,
# free), 16=an internal per-party sequence id (e.g. "1-498844"), 17=Doc #
# (the real instrument number), 18=Tax Map # (parcel id(s) -- newline-joined
# when a document covers multiple parcels). Iredell's OWN layout is
# genuinely different (separate plain-name Grantor/Grantee columns, no
# combined role+name cell) -- see module docstring's "IREDELL" section and
# `_FIELD_ALIASES`/`header_map` below for how this parser now handles BOTH
# without hand-maintaining a third county's fixed indices by guesswork.

def _party_from_cell(cell: str) -> tuple[str, str] | None:
    """('or'|'ee', name) from a combined "role\\tname" grid cell (Jasper's
    own party-column convention -- ONE column holds both the party's role
    and name), or None."""
    if not cell or "\t" not in cell:
        return None
    role, _, name = cell.partition("\t")
    role, name = role.strip().lower(), name.strip()
    if role not in ("or", "ee") or not name:
        return None
    return role, name


def _cell(cells: list[str], idx: int | None) -> str:
    """Bounds-safe `cells[idx].strip()`, "" on a missing/out-of-range/None
    index -- lets every field lookup below stay a one-liner regardless of
    which county's (possibly shorter or differently-shaped) row it's
    reading."""
    if idx is None or idx < 0 or idx >= len(cells):
        return ""
    return (cells[idx] or "").strip()


def _resolve_col(header_map: dict[str, int], logical: str) -> int | None:
    """`logical` field name -> real column index, preferring a live
    `header_map` (see module docstring's "IREDELL" section) over Jasper's
    original fixed positions. With NO header_map at all (every call site
    written before this pass), always falls back to `_FALLBACK_INDEXES` --
    Jasper's already-tested behavior is unchanged. WITH a header_map that
    simply doesn't have this field/alias, returns None (genuinely absent
    for that county) rather than guessing a position that may not exist in
    that row at all."""
    for alias in _FIELD_ALIASES.get(logical, (logical,)):
        if alias in header_map:
            return header_map[alias]
    if not header_map:
        return _FALLBACK_INDEXES.get(logical)
    return None


def parse_grid_row(cells: list[str], header_map: dict[str, int] | None = None) -> dict[str, Any] | None:
    """One raw `<tr>`'s cell-text array -> a flat dict, or None on a row
    shape this parser doesn't recognize (defensive -- a future layout tweak
    degrades to 'skip that row', not a crash).

    `header_map` (field name -> column index, built live by `_SEARCH_JS`
    from the grid's own `Cell_<Field>_Header` header-cell CSS classes) lets
    this ONE parser handle different counties' genuinely different column
    layouts instead of assuming Jasper's fixed positions everywhere --
    live-confirmed 2026-10-14 this is a REAL difference, not just new
    doc-type codes at the same positions (see module docstring's "IREDELL"
    section): Jasper's grid uses a SINGLE combined "<or|ee>\\t<name>" cell
    per party (no separate Grantor/Grantee columns), while Iredell's grid
    uses plain, SEPARATE `Grantor`/`Grantee` name columns with no role
    prefix at all -- the role is implicit in which column it's in. Omitting
    `header_map` (every call site written before this pass) parses exactly
    as before, via `_FALLBACK_INDEXES`."""
    if not isinstance(cells, list) or len(cells) < 6:
        return None
    hm = header_map or {}

    book = _cell(cells, _resolve_col(hm, "Book"))
    page = _cell(cells, _resolve_col(hm, "Page"))
    kind = _cell(cells, _resolve_col(hm, "Kind"))
    if not (book and page and kind):
        return None

    if "Grantor" in hm or "Grantee" in hm:
        # Split, plain-name columns (Iredell's own convention, see above)
        # -- the column identity already encodes the role, no "or\t"/"ee\t"
        # prefix to strip. A "-----" placeholder (Iredell's own blank-party
        # marker, e.g. a Chapter 13 BKCY row with no real second party --
        # see module docstring) reads as no party, same as an empty cell.
        grantor = _cell(cells, hm.get("Grantor")) or None
        grantee = _cell(cells, hm.get("Grantee")) or None
        grantor = None if grantor and set(grantor) <= {"-"} else grantor
        grantee = None if grantee and set(grantee) <= {"-"} else grantee
    else:
        # Combined role+name cell (Jasper's own convention, the only shape
        # this parser knew before this pass).
        p1 = _party_from_cell(_cell(cells, _resolve_col(hm, "Party1")))
        p2 = _party_from_cell(_cell(cells, _resolve_col(hm, "Party2")))
        grantor = p1[1] if p1 and p1[0] == "or" else (p2[1] if p2 and p2[0] == "or" else None)
        grantee = p1[1] if p1 and p1[0] == "ee" else (p2[1] if p2 and p2[0] == "ee" else None)

    date_s = _cell(cells, _resolve_col(hm, "Date"))
    desc = _cell(cells, _resolve_col(hm, "Description"))
    seq = _cell(cells, _resolve_col(hm, "Seq"))
    docno = _cell(cells, _resolve_col(hm, "DocNo"))
    parcel_cell = _cell(cells, _resolve_col(hm, "Parcel"))
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


def collapse_rows_to_docs(raw_rows: list[list[str]], state: str, county: str,
                           header_map: dict[str, int] | None = None) -> list[RodDoc]:
    """Party rows (one per grantor/grantee -- same one-row-per-party shape
    as rod/cchs.py's classic-ASP XML, this vendor's newer product kept the
    convention) -> one RodDoc per (book, page, doc_no). `header_map`: see
    `parse_grid_row()` -- omitted (the default), this parses Jasper's own
    fixed layout exactly as before this pass."""
    docs: dict[tuple, RodDoc] = {}
    for cells in raw_rows or []:
        parsed = parse_grid_row(cells, header_map)
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
# live against the real site, 2026-10-14 -- see module docstring. Re-verified
# live again against Iredell the same day: identical ids/selectors, same
# vendor product -- the two additions below (the iframe-recovery retry and
# the live `header_map` build) are the only real changes this second county
# needed.
_SEARCH_JS = r"""
(async () => {
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
    function isLoading(d) {
        return Array.from(d.querySelectorAll('*'))
            .some(e => e.children.length === 0 && e.textContent.trim() === 'Loading...');
    }

    let ifr = document.getElementById('subapp_LRSearch_0');
    // Two real reasons to (re)click into the Land Records subapp, both
    // live-confirmed 2026-10-14: (a) it doesn't exist in the DOM yet at
    // all (first-ever load, Jasper's own original scenario), or (b) it
    // EXISTS but reads zero width/height because another subapp (e.g. the
    // per-document image/"Open Details" viewer, Iredell's own live-hit
    # scenario this pass ran into) is currently fronted instead -- the grid
    // itself never populates while that's true. The top-level tab control's
    // own visible text differs by tenant (Jasper: "Land Records"; Iredell:
    // "Real Property Index", id `subappTab_LRSearch_0`) -- try the stable
    // id first, text second, so a future county's own label doesn't need a
    // code change to work.
    if (!ifr || ifr.offsetWidth === 0 || ifr.offsetHeight === 0) {
        const tabBtn = document.getElementById('subappTab_LRSearch_0') ||
            Array.from(document.querySelectorAll('*'))
                .find(e => e.children.length === 0 &&
                    ['Land Records', 'Real Property Index', 'Real Property'].includes(e.textContent.trim()));
        if (tabBtn) tabBtn.click();
        for (let i = 0; i < 20; i++) {
            await sleep(300);
            ifr = document.getElementById('subapp_LRSearch_0');
            if (ifr && ifr.offsetWidth > 0 && ifr.offsetHeight > 0) break;
        }
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

    // Field name -> column index, read live from `#gridTrad`'s own header
    // row (`Cell_<Field>_Header` CSS classes, a vendor-provided marker --
    // see module docstring's "IREDELL" section). Computed once the grid
    // exists; a county whose header cells don't carry this class (none
    // seen yet) just yields {}, and parse_grid_row() falls back to
    // Jasper's fixed positions in that case, same as if no header_map were
    // passed at all.
    function readHeaderMap() {
        const grid = doc.getElementById('gridTrad');
        if (!grid) return {};
        const map = {};
        Array.from(grid.querySelectorAll('td[class*="_Header"]')).forEach(td => {
            const m = Array.from(td.classList)
                .map(c => c.match(/^Cell_(\w+)_Header$/))
                .find(Boolean);
            if (m) map[m[1]] = td.cellIndex;
        });
        return map;
    }

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
    const headerMap = readHeaderMap();

    const pages = [state.rows];
    for (let p = 1; p < %(max_pages)d; p++) {
        const nextBtn = doc.querySelector('[id*="PagerBarTNext"]');
        if (!nextBtn) break;
        // Whole-row JSON compare, not one assumed-stable column index --
        // works regardless of which county's column layout this is (the
        // old `rows[0][16]` key assumed Jasper's own internal-seq-id
        // position, which doesn't exist at that index on every county).
        const beforeKey = JSON.stringify(state.rows[0] || null);
        nextBtn.click();
        let advanced = false;
        for (let i = 0; i < 40; i++) {
            await sleep(500);
            if (isLoading(doc)) continue;
            const s2 = readState();
            if (!s2) continue;
            const afterKey = JSON.stringify(s2.rows[0] || null);
            if (afterKey !== beforeKey) { state = s2; advanced = true; break; }
            if (!s2.rows.length) { state = s2; advanced = true; break; }
        }
        if (!advanced) break;
        pages.push(state.rows);
    }

    return JSON.stringify({
        total_records: state.total_records, total_documents: state.total_documents,
        pages_read: pages.length, rows: pages.flat(), header_map: headerMap,
    });
})()
"""


async def _run_js(tab_or_page, js: str):
    """Execute `js` (a self-contained async IIFE that returns a JSON
    string) on either a nodriver `tab` (Jasper/SC's own caller,
    `sc_rod_walled.py`'s `_fetch_jasper`) or a Playwright `page`
    (Iredell/NC's own caller, `nc_rod_captcha.py`'s `_fetch_iredell`) --
    the one piece of this module that was genuinely nodriver-specific
    before this pass. nodriver's `Tab.evaluate(expr, await_promise=,
    return_by_value=)` and Playwright's `Page.evaluate(expr)` take
    different call signatures (Playwright has no such kwargs -- it always
    auto-awaits a returned Promise and serializes the result on its own),
    but the SAME `_SEARCH_JS` string works unchanged on both, since it's
    already a self-contained async IIFE that returns a JSON string either
    way. Tries nodriver's signature first; a Playwright `page.evaluate`
    rejects the unexpected kwargs with a `TypeError` at the Python
    call-binding stage (before any JS runs, so this is safe to retry, not a
    double-execution risk), and the plain-signature call is retried."""
    try:
        return await tab_or_page.evaluate(js, await_promise=True, return_by_value=True)
    except TypeError:
        return await tab_or_page.evaluate(js)


async def _search_via_tab(tab, from_date: datetime, to_date: datetime,
                           doc_codes: str, max_pages: int) -> dict[str, Any]:
    js = _SEARCH_JS % {
        "from_date": from_date.strftime("%m/%d/%Y"),
        "to_date": to_date.strftime("%m/%d/%Y"),
        "doc_codes": doc_codes,
        "max_pages": max_pages,
    }
    try:
        result = await _run_js(tab, js)
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
    death-certificate/foreclosure/substitute-trustee/judgment/bankruptcy,
    depending on which `doc_codes` the caller scopes to -- see
    `classify_kind_code()`) for a CCS DevExpress county, driven over an
    ALREADY reCAPTCHA-cleared `tab` -- either a nodriver `Tab` (Jasper/SC's
    own caller) or a Playwright `Page` (Iredell/NC's own caller, see
    `_run_js()`) -- operator-assisted in both cases; this function never
    attempts the CAPTCHA itself. Scopes the search server-side to
    `doc_codes` rather than fetching the whole unscoped window and
    filtering client-side -- see module docstring's "DOC TYPES" section for
    why (461 unscoped pages vs. 5 scoped, live, on Jasper)."""
    if base_url(state, county) is None:
        return []
    today = datetime.utcnow()
    earliest = today - timedelta(days=max(1, days_back))
    result = await _search_via_tab(tab, earliest, today, ",".join(doc_codes), max_pages)
    if result.get("error"):
        log.warning("ccs_devexpress.search_failed", county=county, error=result["error"])
        return []
    header_map = result.get("header_map") or None
    docs = collapse_rows_to_docs(result.get("rows") or [], state, county, header_map)
    log.info("ccs_devexpress.discovered_via_browser", county=county,
              total_records=result.get("total_records"),
              total_documents=result.get("total_documents"),
              pages_read=result.get("pages_read"), documents_parsed=len(docs),
              header_map_fields=sorted(header_map) if header_map else None)
    return docs[:max_docs]
