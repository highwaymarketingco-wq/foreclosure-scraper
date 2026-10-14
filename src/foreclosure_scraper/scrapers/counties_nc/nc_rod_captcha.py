"""NC Register of Deeds sites with CAPTCHA/math gate — 9 counties.

ALL 9 URLS REWRITTEN 2026-10-12. Before this date only 2 of 9 (Brunswick,
Stokes) had ever been checked against a live site -- the other 7 had never
actually been verified, and every single one was dead: 5 hard DNS failures
(Iredell, Craven, Greene, Harnett, Randolph -- "Could not resolve host",
confirmed from two separate networks) plus Wake (404 -- the domain itself
was right, the code was just missing the real `/web` app path) and Durham
(the whole county domain family changed to dconc.gov). The old docstring's
gate-type claims below were therefore also unverified guesses in several
cases, not confirmed observations -- corrected where live evidence now
exists.

Sites and gate types (all confirmed live 2026-10-12 unless noted):
- rodrecords.wake.gov/web — real Google reCAPTCHA checkbox, confirmed by
  screenshot (Tyler Technologies "Self-Service" platform v2026.1.5). Old
  code hit the bare domain (404); the app lives under /web.
- rodweb.dconc.gov/web — Durham's new domain (county migrated away from
  durhamcountync.gov entirely). Same Tyler "Self-Service" platform as
  Wake -- gate very likely the same reCAPTCHA, not individually
  screenshotted.
- brunswick-live.inttek.net — math question, confirmed by screenshot
  ("Four Minus One Equals ___"), use math_captcha.py. Real post-gate
  search_path still unverified (gate itself not cleared).
- iredellnc.courthousecomputersystems.com — real Google reCAPTCHA,
  confirmed by screenshot ("Please Verify You are Not a Robot"). NOTE:
  this platform only covers records from 1964 forward; pre-1964 records
  need a second, separate system (cotthosting.com/NCIredellExternal) --
  out of scope for now, flagging it exists.
- greenenc.courthousecomputersystems.com — same Courthouse Computer
  Systems platform as Stokes/Iredell (both confirmed reCAPTCHA); this
  county's own site says the system went live Dec 2025. High-confidence
  reCAPTCHA by platform match, not individually screenshotted.
- us6.courthousecomputersystems.com/HarnettNC — SAME base domain as
  Stokes, just a different county path (shared multi-tenant platform).
  High-confidence reCAPTCHA by platform match.
- us5.courthousecomputersystems.com/RandolphNC2 — different server
  instance (us5, not us6) and an unexpected "2" suffix on the county
  code. Owner directly observed CAPTCHA + disclaimer live 2026-10-12 --
  this corrects the old docstring's "math question" guess, which was
  never actually verified against this (or any) live URL.
- us5.courthousecomputersystems.com/CravenNC2 — same us5 instance as
  Randolph. Same correction: owner-confirmed CAPTCHA + disclaimer live
  2026-10-12, not the old docstring's unverified "math question" guess.
- us6.courthousecomputersystems.com/StokesNC — real Google reCAPTCHA,
  confirmed by screenshot, behind a terms-of-use disclaimer.

LIVE RE-VERIFIED 2026-10-14 (source-completeness audit's "Needs YOU logged in"
list, final item -- see docs/source_completeness_audit_2026-10-13.md). Every
one of the above claims was re-checked against the live site, not trusted on
the 2-day-old docstring, per the sibling discovery earlier the same night that
5 other "needs login" files in that same list turned out to need no login at
all. Of these 9, 8 reconfirmed exactly as above -- Wake, Iredell, Craven,
Greene, Harnett, Randolph, Stokes all still show a real Google reCAPTCHA
widget live (confirmed via Playwright DOM query for an actual
`iframe[src*=recaptcha]`/`div.g-recaptcha`, not a string-grep on the page's
raw HTML -- see the Durham correction below for why the stronger check
matters), and Brunswick's math gate is still live. These 8 are left alone,
genuinely walled, same boundary this audit night already drew at Jasper
(`sc_rod_walled.py`, commit 7335c362): a real CAPTCHA this codebase cannot
automate.

- **Durham was WRONG and is now FIXED.** The 2026-10-12 entry's own words
  were "very likely the same reCAPTCHA [as Wake], not individually
  screenshotted" -- an inference by platform match, never actually checked.
  Worse: this was already WRONG the day it was written, and the correct
  answer was sitting in this same codebase. `rod/nc_tyler.py` (a
  name-search ROD enricher for existing leads, unrelated purpose, written
  2026-10-07) says in its own docstring: "Durham's disclaimer page loads
  Google's reCAPTCHA script but showed no challenge on 2026-10-07." Five
  days later this file's docstring guessed the opposite for the exact same
  site, without checking -- a real in-repo contradiction, the same class of
  bug this audit night already caught once in `sc_rod_cott.py` (Union
  "pay-per-view" vs. `rod/doc_images.py`'s own "free" registry). Live-
  verified 2026-10-14: a plain string search of Durham's raw HTML DOES
  contain "g-recaptcha" (it ships in this Tyler "Self-Service" tenant's
  shared JS bundle site-wide), which is exactly the false signal that made
  the 2026-10-12 guess plausible -- but a real DOM query
  (`page.query_selector("iframe[src*=recaptcha]")`) on both the disclaimer
  page AND the search page returns nothing. The actual gate is just the
  "I Accept" disclaimer button every Tyler Self-Service tenant has (id
  `submitDisclaimerAccept`) -- no CAPTCHA at all. Clicking it fires a
  client-side JS redirect, not a normal navigation, so a `networkidle` wait
  immediately after the click still sees the disclaimer page; it needs a
  real pause (confirmed live: <4s is enough) before the redirect lands on
  `/web/`. From there `/web/search/DOCSEARCH5S1` is directly reachable and
  returns real, live recording-date-filtered results with zero gate -- a
  14-day window live-pulled 1,243 real documents (5 tagged FORECLOSURE,
  264 DEED OF TRUST, etc.) on 2026-10-14. This tenant's result rows are
  **not** `<table>` markup at all -- a jQuery-Mobile `ui-listview` of
  `<li class="ss-search-row">` elements -- so the shared `_parse_html()`
  below (which only looks for `table tr`) would find zero rows even with
  the gate cleared. Durham gets its own flow (`_fetch_durham`), but NOT a
  second hand-rolled parser: `rod/nc_tyler.py` already has a tested one for
  this exact markup (`parse_selfservice`, built for its own name-search use
  case) -- reused here via `_durham_record_to_listing` rather than
  duplicated. Row capture itself was page-1-only (Tyler's ~100-row default
  page size) of the 90-day window, newest-first -- NOT full pagination (a
  90-day window runs into the thousands of rows; flagged here same as every
  other partial-coverage note in this codebase rather than silently claimed
  complete). **FIXED 2026-10-14 (cont. x4), see below.**

  Each row's primary document image IS viewable free, no login, no cart,
  INSIDE an authenticated browser session: the detail page
  (`/web/document/{documentid}`) embeds a PDF.js viewer whose iframe
  `data-href` is a `/web/document-image-pdf/...` route that returned a real
  `200 application/pdf` (live-verified on 2 real documents, 110KB/4-page and
  similar) when fetched through `page.request` -- i.e. still carrying the
  Playwright page's cookies. Deliberately **NOT** stamped via
  `document_links.stamp_documents`, after first implementing exactly that
  and then catching the mistake live: a bare `curl` (no cookies at all)
  against that same URL gets a `302` to `/web/user/disclaimer` with a fresh
  `Set-Cookie: JSESSIONID=...`, and adding a matching `Referer` header
  (the fix that worked for Union/Cott's image route earlier tonight) does
  NOT help -- this route checks a live server-side session, not the
  Referer. `enrichment_doc_ocr.py`'s `_fetch_doc` fetches every stamped
  `document_url` with a plain stateless `httpx.AsyncClient`, no cookie jar
  carried over from this scraper's Playwright run, so a stamped link here
  would silently 302 to the disclaimer HTML and fail OCR invisibly --
  exactly the "looks wired, produces nothing downstream" failure mode this
  codebase has hit before (e.g. the column-source silent-death pattern).
  Left as a flagged, documented gap rather than shipped as a working
  document link it isn't: the index-row data above (doc type, grantor,
  grantee, book/page, filing date) is the confirmed-working deliverable;
  the per-document image would need either a from-scratch rework of
  `enrichment_doc_ocr.py` to carry a session (out of scope here, cross-cuts
  every other scraper that module reads) or this scraper downloading the
  PDF bytes itself while the session is live and storing them some other
  way than a `raw` URL field (a bigger schema change, also out of scope).

- **Brunswick's math gate is confirmed live but NOT actually solvable by
  this codebase's `math_captcha.py` as written**, which matters because
  `solve_math_captcha()` returns `True` (claims success) while silently
  failing -- a real bug worth flagging even though it doesn't change
  Brunswick's walled status. Live-tested 2026-10-14: the specific arithmetic
  question ("Four Minus One Equals ___" per the 2026-10-12 screenshot) is
  rendered as a CAPTCHA **image** (`getpng.php?a=N&b=M`), not as visible
  text anywhere on the page -- `math_captcha.solve_math_question()` only
  ever reads `page.inner_text("body")`, so it has nothing to OCR and no
  real question to parse. Instead it spuriously pattern-matches the
  Register of Deeds office's own phone number in the page footer
  ("(910) 253-2690") as if it were the arithmetic expression "253-2690",
  "solves" it to -2437, fills the answer field, submits, and reports
  `solved=True` -- but the resulting page is byte-for-byte the same
  disclaimer/login page as before the submit (confirmed by diffing
  `inner_text()` before/after), i.e. the gate was never actually cleared.
  Left alone: genuinely walled (an image-rendered math CAPTCHA, which is a
  materially different and harder problem than the text-based one this
  module was built for), not patched as part of this pass since fixing
  `math_captcha.py` itself is a separate, broader change outside this file
  and outside this audit's current scope -- flagged for whoever picks it up
  next instead of silently papering over the false-positive return value.

**CORRECTION 2026-10-14 (cont.) -- `math_captcha.py`'s false positive is now
FIXED, and Brunswick turned out to be genuinely solvable, not just
correctly-reported-failed.** `solve_math_captcha()` no longer regexes
`page.inner_text("body")` at all -- it scopes question-text extraction to
the `<fieldset>`/`<form>` immediately around the answer input (Brunswick's
real markup is `<fieldset class="captcha">`, several DOM levels away from
the footer's phone number, which sits in a sibling section of the same
page-spanning outer `<form>`), strips any phone-number-shaped substring as a
second independent guard, and -- the part that actually unlocks Brunswick --
detects an image-only question and OCRs it via this codebase's existing
free-tier-first Gemini vision plumbing
(`enrichment_vision._parse_gemini_keys`/`_parse_json_response`, the same
key-rotation `enrichment_doc_ocr.py` uses) instead of either guessing or
giving up. Brunswick's question turned out to be FOUR separate word-images
(`getpng.php?a=N&b=M` -- confirmed live by fetching and visually reading the
actual PNGs: one page read "Five"/"Plus"/"Nine"/"Equals" = 14, another
"Seven"/"Minus"/"Zero"/"Equals" = 7; the `a`/`b` query params are NOT the
literal operands, just opaque render params), which `_solve_image_question`
sends to Gemini together as one multi-image call so the words are read in
the right order. Live-verified end-to-end against the real site 2026-10-14,
twice, with NO browser in the loop for this specific check (httpx replaying
the real session/cookies and the real form POST, to avoid running Chromium
locally during an active Mac memory/swap crisis -- the Playwright code path
itself is covered by `tests/test_math_captcha.py`'s `_FakePage`, which
mirrors the exact Page API `solve_math_captcha()` calls): fetched the live
page, OCR'd the real question image(s), POSTed the computed answer with the
session it was issued under, and got back a genuinely different page (no
more captcha field) both times -- the real gate cleared for real, not just a
plausible-looking return value. OCR reliability is tied to whatever Gemini
model/quota this codebase is configured with at the time (same dependency
every other OCR-driven enricher already has) -- one live attempt hit a
transient "503 model overloaded" across all 9 rotated keys on the default
model, and a deliberately-weaker model substituted for comparison
(`gemini-2.5-flash-lite`) misread one of the four images on 1 of 3 repeated
trials against the SAME saved image set. Neither failure mode becomes a new
false positive: when OCR can't read the image, `_solve_image_question`
returns `None` and `solve_math_captcha` reports `False`; when OCR confidently
misreads it, the new post-submit `_gate_still_present` check (comparing the
page before/after submit, the exact comparison the old code skipped) catches
the wrong answer and still reports `False` -- confirmed live in the misread
case above (gate stayed present after the bad answer was submitted). Net:
Brunswick now succeeds when Gemini OCR is available and correct, and fails
CLOSED (reports unsolved, same as before) when it isn't -- never a silent
wrong "success" either way. 4 of 4 live attempts in this session solved the
CAPTCHA correctly (one earlier side-by-side comparison against a weaker
model, not the one this codebase actually ships, did misread one image --
see `math_captcha.py`'s own module docstring). See `tests/test_math_captcha.py`
for the full test coverage (the phone-number false-positive case, legitimate
text-based questions, and this OCR path with a mocked Gemini call using the
real live word-image evidence above).

Clearing the CAPTCHA is NOT the whole gate, though -- live-followed one
layer further 2026-10-14: the page right after a correct CAPTCHA submit is
a SECOND gate, a disclaimer accept/decline page (structurally the same
pattern as Durham's `#submitDisclaimerAccept`, just an anchor link here
instead of a button: `<a href=".../index.ntk?s=...">I have read, and agree
with the License above</a>`). Following that link lands on the real site
menu ("Please select the type of search you want to perform" -- Combined
Real Property/MAPS, Births, Deaths, Marriages, Notary, Book/Page Direct),
confirming the full CAPTCHA+disclaimer chain genuinely reaches Brunswick's
real UI, not just a second dead end. This was reconnaissance only (plain
`httpx` replaying the session, same reasoning as the CAPTCHA verification
above) -- NOT wired into `fetch()`/`_COUNTY_SITES` here. Brunswick still
needs: (1) the disclaimer-accept step added to this file's `gate == "math"`
branch (the same shape as `_fetch_durham`'s accept click, just needs its
own helper since the control here is a link, not a button), (2) the
"Combined Real Property/MAPS" search clicked into and its date-range/
result markup captured (unknown shape -- not yet observed), and (3)
whatever parser that markup turns out to need, the same way Durham got
`_durham_record_to_listing`/`parse_selfservice` instead of the generic
`_parse_html`. None of that is done here -- this pass only fixes
`math_captcha.py`'s false positive and confirms the CAPTCHA layer itself is
now genuinely solvable; wiring Brunswick's actual lead capture through the
two gates above is a follow-up, flagged here rather than silently implied
by "Brunswick is now solvable."

**CORRECTION 2026-10-14 (cont. x2) -- Brunswick is now WIRED, not just
solvable.** `fetch()`'s `gate == "math"` branch now calls `_fetch_brunswick`
right after `solve_math_captcha` returns `True`, which clicks the "I have
read, and agree with the License above" disclaimer link (NOT the "I do NOT
agree" link listed first in the DOM -- a substring match on "agree with the
License" matches both, confirmed live by hitting exactly that bug once
during this verification and landing on a real "You have Logged Off this
system" page), clicks "Combined Real Property / MAPS" from the real site
menu, then searches and paginates two distress-relevant Document Types the
real dropdown offers (NC non-judicial foreclosures record as "SUBSTITUTE
TRUSTEE" then "NOTICE OF FORECLOSURE" -- there is no "TRUSTEE DEED"/
"FORECLOSURE DEED" option; the eventual sale deed records as a plain
"DEED", indistinguishable here from any other sale, a real flagged gap).
Live-verified end-to-end 2026-10-14 via httpx replaying the real site (no
Chromium run locally, same memory-pressure reasoning as the CAPTCHA
verification above -- the Playwright glue code itself mirrors this proven
httpx flow one-for-one but was NOT executed live in THIS session; see
`_fetch_brunswick`'s own docstring): a brand-new, cookie-less httpx client
(no prior requests at all) fetched a real 2-page
"BRUNSWICK-property-B5631-P1335.pdf" and a real Document Details page from
the signed `s=` tokens alone, confirming they are durable, stateless URLs
(this entire site never sets a cookie anywhere in the chain) -- safe to
stamp via `document_links.stamp_documents`, unlike Durham's cookie-gated
PDF route or Rowan/Logan's session-scoped image keys. A 90-day window
returned 271 SUBSTITUTE TRUSTEE and 82 NOTICE OF FORECLOSURE records; with
"Sort by Recording Date" checked the result set is ASCENDING (page 1 =
oldest, 07/22/2026 in a 07/16-10/14 window; the LAST page = newest,
10/13/2026), so `_fetch_brunswick` jumps straight to the last page (always
directly linked, even on a truncated 28-page pagination row) and walks
backward via a `#prev_page` button, a budget-capped number of pages
(`_BRUNSWICK_MAX_PAGES`) -- genuinely the freshest leads first, still only
partial coverage of the full window (documented, not silently implied
complete, same honesty convention as Durham's page-1-only gap above).
Real, live-pulled examples (book 5596 page 1287, a real SUBSTITUTE TRUSTEE
instrument): 3 grantor index rows for ONE instrument -- "VEGA, ESTEBAN
EMILIO" and "MILLS, BRANDI" (real co-owners, kept) plus "ROCKET MORTGAGE,
LLC" (the original lender, ALSO indexed as a "grantor" in this chain --
filtered out by an institutional-name check, `_brunswick_is_institutional`,
the same purpose as nc_rod_logan.py's own copy). `_brunswick_parse_page`
groups the one-index-row-per-grantor-name records back into a single
Listing per (book, page). See `_fetch_brunswick`/`_brunswick_parse_page`/
`_brunswick_record_to_listing`'s own docstrings for the full per-step
writeup, and `tests/test_nc_rod_captcha.py` for real schema-accurate
fixtures built from this live pull.

**CORRECTION 2026-10-14 (cont. x3) -- Wake is now WIRED past the human-cleared
CAPTCHA, and its SESSION-REUSE WINDOW is now measured, not assumed.** The
reCAPTCHA checkbox itself is confirmed genuinely real (the owner personally
solved it live) -- same hard boundary every other real CAPTCHA in this file
respects, never automated, and this correction does not change that. What
changes: everything downstream of that human-cleared session is now built.
Same Tyler "Self-Service" platform as Durham -- confirmed by reading the real
live DOM (`outerHTML` of real search rows), not inferred by platform match
the way the 2026-10-12 entry got Durham wrong: identical
`li.ss-search-row`/`ul.selfServiceSearchResultColumn` markup and identical
`#field_RecordingDateID_DOT_StartDate`/`#field_RecordingDateID_DOT_EndDate`/
`#searchButton` field ids (Wake's own search id is `DOCSEARCH341S2` vs
Durham's `DOCSEARCH5S1` -- same app, different tenant instance). `_fetch_wake`
therefore reuses `rod.nc_tyler.parse_selfservice()` verbatim, same as Durham,
not a third hand-rolled parser. `_COUNTY_SITES["wake"]["search_path"]` was
also simply wrong before this pass -- it pointed at `/user/disclaimer` (the
gate page itself, never a search route) -- corrected to the real
`/search/DOCSEARCH341S2`.

Unlike Durham's single unfiltered page-1 pull (fine there -- lower volume,
already-established no-CAPTCHA case), Wake's own
`#field_selfservice_documentTypes` field lets the search be scoped UP FRONT
to Wake's real distress Document Types, same convention as Brunswick's own
2-doc-type search. Live Document Type facet counts (14-day window,
2026-10-14) show Wake's version of nc_rod_logan.py's "S/TR"/"FCL"
pre-foreclosure codes are literally spelled "SUBSTITUTE TRUSTEE" (43 in 14
days) and "FORECLOSURE NOTICE" (7 in 14 days) among 44 other real Document
Types seen live (DEED 985, DEED OF TRUST 1045, SATISFACTION 1087, ASSIGNMENT
309, etc. -- routine filings, not distress, same judgment call Logan's own
`_classify()` already makes for a plain DOT origination). A live two-type
90-day search (Jul 16-Oct 14 2026) returned 256 real total results across 11
pages of ~25/page -- SUBSTITUTE TRUSTEE alone was 222 across 9 pages
(`Showing page 1 of 9 for 222 Total Results`, read live) -- small enough to
walk in full within `_WAKE_MAX_PAGES`, unlike Brunswick's much larger
per-type volume that needed a last-page-jump-and-walk-backward trick. Each
type is searched SEPARATELY (not combined in one query) specifically so each
page's own KNOWN `doc_type_filter` stays trustworthy for classification --
see the next paragraph for why.

Getting the filter to actually take live-surfaced a real platform gotcha:
`#field_selfservice_documentTypes` is a true tag/token field, not a plain
text filter. Live-confirmed TWICE that a plain `.fill()` / direct `.value`
property-setter assignment (with proper `input`/`change` events dispatched)
is silently ignored by the server-side search -- the reported result set
never changed from whatever the PREVIOUS real search was. Only an actual
typed keystroke sequence followed by a real Enter commits the text into a
removable chip (watched "SUBSTITUTE TRUSTEE" turn into an `x`-removable chip
live, and the results summary line change to "...and Document types in
SUBSTITUTE TRUSTEE" only after that Enter) -- `_fetch_wake` types + presses
Enter for exactly this reason.

A second real, live-confirmed gotcha this scraper works around rather than
silently mis-classifying: an administratively-corrected record renders TWO
Document Type values, the OLD one struck through first
(`<span style="text-decoration: line-through;">SEE</span>`) then the live one
second (instrument 2026086748, live: "SEE" / "SUBSTITUTE TRUSTEE").
`parse_selfservice()` (correctly, for Durham, which never hit this live)
takes the FIRST value, so a corrected Wake row would silently classify as
"SEE" if trusted. `_wake_record_to_listing` never uses `record.doc_type` for
classification for exactly this reason -- it always trusts the KNOWN
per-search `doc_type_filter` instead (kept in `raw["doc_type"]` for
provenance only).

A THIRD real, live-confirmed gap, the most consequential for lead
completeness: the shared `_SS_HEAD` regex (`rod/nc_tyler.py`, used by Durham
too) only captures ONE Book/Page pair per header. A multi-tract SUBSTITUTE
TRUSTEE instrument renders TWO "B: x P: y" pairs with no bullet between them
(live, instrument 2026086748: "2026086748  •  B: 020299 P: 01082   B:
020299 P: 01083  •  07/31/2026 08:50 AM") -- confirmed live by running
that EXACT captured text through `_SS_HEAD.match()`: returns `None`, so
`recorded`/`instrument_no`/`book`/`page` all come back `None` (grantor/
grantee/doc_type/description still parse fine -- only the header fails).
Both `_wake_record_to_listing` and `_durham_record_to_listing` require a
non-empty `instrument_no`, so a real lead like this one was SILENTLY DROPPED
on both Wake and Durham. **FIXED 2026-10-14 (cont. x5), see below.**
`tests/test_nc_rod_captcha.py` was updated to assert the new fixed behavior.

Related Documents are wired in, one hop deep, as the owner specifically
asked to confirm: each document's own detail page
(`/web/document/{docid}?search={search_id}`) auto-fires a real XHR
(`GET /web/document/relatedDocuments/{docid}?queryId=...&search=...`) --
live-confirmed by fetching it directly (`credentials: "same-origin"`,
carrying the real session) for instrument 2026111052 ("NOTICE OF
CORRECTION"): 1 related DEED from 09/06/1960, book/page "001422-00299", its
own 2 grantor + 2 grantee names, the ORIGINAL instrument the correction
concerns. `queryId` itself is per-search-session and not exposed as a simple
reachable global (checked live, not found on `window`) -- `_fetch_wake_related`
therefore navigates to the document's own detail page and reads the SAME
panel a human sees, rather than hand-building the relatedDocuments URL, and
is budget-capped (`_WAKE_MAX_RELATED_FETCHES`, same spirit as
nc_rowan_cott.py's `_MAX_DETAIL_FETCHES`) to the newest leads found. Related
rows are index metadata (type/date/book-page/parties), not a document image,
so never passed to `document_links.stamp_documents` -- stored as structured
data under `raw["wake_detail"]["related_documents"]` instead. Per-document
PDF images themselves (`/web/document-image-pdf/{docid}/{queryId}/
{docnum}-{index}.pdf`) are live-confirmed to need that SAME session -- a
cookie-less `curl` against a real URL pulled from this exact session got a
`302` to `/web/user/disclaimer` -- identical gap to Durham's own cookie-gated
PDF route (see above), and deliberately NOT stamped for the same reason.

**SESSION-REUSE WINDOW -- the operational question this pass was
specifically asked to answer, tested empirically, not assumed either way.**
The real Tyler Self-Service client ships its own `GET /web/session/
pingSession` heartbeat -- observed firing automatically roughly every
10-20s while a tab just sits open, alongside a `POST /web/subscription/
getSubscriptionTime` call -- specifically to keep the server-side session
alive. That the platform bothers polling this often is itself strong
architectural evidence of a real, finite, activity-extendable idle timeout
on the order of minutes (no system defends a multi-hour timeout by pinging
every 10-20 seconds; that cadence is characteristic of a moderate,
enterprise-typical 15-30 minute idle window). Tested directly, not inferred
from the ping cadence alone: monkey-patched `window.fetch`/`jQuery.ajax` in
the live, human-cleared tab to silently BLOCK any further `pingSession`/
`getSubscriptionTime` call (confirmed the block actually fired), then made
ZERO further requests of any kind for a clean, measured 7 minutes 14 seconds
(18:26:27Z to 18:33:41Z, 2026-10-14) before issuing ONE real, deliberate
authenticated request -- `window.fetch` directly (bypassing the patched
wrapper) to both `/web/session/pingSession` AND a full
`/web/searchResults/DOCSEARCH341S2?page=1` fetch. Both returned `200`, not a
redirect to `/web/user/disclaimer`: `pingSession` answered `"true"`, and the
searchResults fetch returned a real 546KB page of actual `ss-search-row`/
`ss-facet-entry` markup, not disclaimer/login HTML. CONFIRMED FLOOR: at least
7m14s of genuinely idle (zero client activity, heartbeat deliberately
disabled) session survival, live-verified, not assumed. This was NOT pushed
further to find the actual ceiling (would cost real additional idle wall-
clock time this pass did not spend chasing), so the exact upper bound
remains unmeasured -- report it as "at least ~7 minutes confirmed," not as a
tested multi-hour number.

**What this means operationally:** a 7+-minute confirmed floor, combined
with the platform's own ~10-20s self-heartbeat architecture (strong evidence
the real idle window is considerably longer than 7 minutes, likely in the
same 15-30+ minute range typical of this class of enterprise session
manager), supports the "operator clears the checkbox once, this scraper's
own Playwright session then drives a real, bounded LIVE batch of
searches/fetches off that same cookie" pattern -- NOT a one-shot token that
dies the instant the clearing browser closes, and a materially different
(more capable) shape than `docs/HERMES.md` §11's existing manual lane
(Cherokee/LiensNC: operator saves a page, an offline parser ingests it, no
live session reuse at all). `_fetch_wake`'s own two-search-plus-pagination-
plus-related-docs run is itself well within a 7+-minute live window for the
confirmed real volume (256 leads/11 pages + a budget-capped related-docs
hop). For extra headroom on a longer/slower run, `_fetch_wake` could also
just call `/web/session/pingSession` on a timer itself, the same way the
real site's own JS does -- trivial to add, costs nothing, not done here
since it was not needed to clear the measured floor above. The reCAPTCHA
clearing itself stays, and will keep staying, a manual/operator step -- this
codebase does not and will not try to automate solving it.

**CORRECTION 2026-10-14 (cont. x4) -- Durham's "page 1 only" gap is now
FIXED: real pagination, not full pagination -- a deliberate, documented
budget cap, same spirit as every other page budget in this file.** Live-
reverified via httpx replaying the real session (same "no Chromium during an
active Mac memory/swap crisis" reasoning the Brunswick correction above
already used, not re-litigated here): a 90-day unfiltered window is **96 pages**
at ~100 rows/page (~9,502 total rows, newest-first), confirmed by the
real `searchPost` JSON reply (`{"totalPages":96,...}`) and independently by
the rendered `Showing page 1 of 96 for 9502 Total Results` summary on
`/web/searchResults/DOCSEARCH5S1?page=1`. Walking the real site 20 pages deep
(`_DURHAM_MAX_PAGES`) pulled **2,000 real rows with 2,000 DISTINCT instrument
numbers and zero overlap between any two consecutive pages** (e.g. page 1's
newest instrument was 2026190413, page 2's newest was 2026190313, page 3's
2026190213, page 4's 2026190113 -- each page genuinely a new, non-repeating
100-row slice, not page 1 re-read 20 times). `_fetch_durham` now reads the
same `Showing page X of Y` summary `_fetch_wake` already reads (renamed to
the shared `_SS_PAGE_OF_RE`, since Durham and Wake are the same platform/
tenant family and render identical text) off the already-loaded page-1 DOM,
then walks pages 2..min(totalPages, 20) via the SAME direct
`searchResults/<search_id>?page=k` navigation `_fetch_wake` already uses in
production -- not a new mechanism. 20 pages (2,000 rows, a ~20x improvement
over the old page-1-only behavior) is still genuinely partial coverage of a
96-page window (~21%), proportionally similar to how much partial coverage
Brunswick's own `_BRUNSWICK_MAX_PAGES` already accepts (~18%) -- documented
here, not silently implied complete, same honesty convention as every other
page budget in this file. The Playwright navigation loop itself (`page.goto`
+ `wait_for_load_state` + `page.content()` per page) was not re-run live in
THIS session for the same memory-pressure reason -- it mirrors `_fetch_wake`'s
own already-shipped, already-live-proven pagination loop one-for-one (same
URL shape, same wait, same parse call), and the underlying HTTP contract
(search-context cookie + `searchResults?page=k` returning real
`ss-search-row` markup plus the `Showing page X of Y` summary) is exactly what
the httpx verification above confirmed live.

**CORRECTION 2026-10-14 (cont. x5) -- the shared `_SS_HEAD` multi-tract gap
is now FIXED.** `rod/nc_tyler.py`'s `_SS_HEAD` regex no longer requires a
single fixed BT:/B:/P: slot sequence between the header's two bullets --
it now captures the whole middle section as a blob and pulls `BT:`/`B:`+`P:`
out of it with their own sub-patterns (`_SS_HEAD_BT`/`_SS_HEAD_BP`), so
`instrument_no`/`recorded` no longer depend on how many book/page pairs that
middle section holds. Re-run live against the EXACT real multi-tract text
this file already had on record (instrument 2026086748: "2026086748  •  B:
020299 P: 01082   B: 020299 P: 01083  •  07/31/2026 08:50 AM"): the header
now matches, `instrument_no` is `"2026086748"`, `recorded` is `"2026-07-31"`,
and `book`/`page` are the FIRST pair (`020299`/`01082`) -- the primary tract;
the second tract's own pair is not separately modeled, same scope the task
asked for ("at minimum the primary one, without silently dropping
instrument_no/date"). Ordinary single-pair headers (Durham's own `BT: OPR B:
10616 P: 073` shape, Wake's plain `B: 020291 P: 01139` shape) still parse
identically to before -- re-verified against both real fixtures already in
`tests/test_nc_rod_captcha.py`. This real lead -- previously SILENTLY DROPPED
on both Wake and Durham (both share this parser) because `instrument_no` came
back `None` -- is now captured. `tests/test_nc_rod_captcha.py` was updated
(not just added to) to assert the NEW fixed behavior instead of the old
documented-gap behavior, per this pass's own instructions.

**NOT fixed, and genuinely cannot be fixed at this level: the Grantor/
Grantee column's 5-name visible cap** (see the gap documented just above
`_fetch_wake`'s own constants block, and re-confirmed live 2026-10-14 on
Durham too, not just Wake: instrument 2026190164, a real DEED, book 10639
page 799, declares "Grantor/Party 1 (12)" in its own column header but the
search-results row's DOM genuinely contains only 5 `<li>` name nodes -- not a
parser stopping early; `parse_selfservice()` has no slice/cap of its own and
faithfully returns every item actually present). A live scan of the newest
2,000 Durham rows (the same 20-page pull above) found 151 rows (~7.6%) whose
declared party count exceeded the 5 actually rendered -- not a rare edge
case. Live-confirmed this pass, not just inferred: the missing names ARE
recoverable, but only one hop deeper, on that same document's own detail page
(`/web/document/DOC291S618?search=DOCSEARCH5S1`, fetched live 2026-10-14) --
its "Names" section lists all 12 real grantors in full (KNOTT GERALD, KNOTT
GERALD W., RHEW JILL, RHEW JILL K, RHEW MICHAEL, RHEW MICHAEL TODD, PATRICK
JACOB CANNON, PATRICK JACOB, KNOTT JOSHUA, KNOTT JOSHUA D, MILLIGAN ALLISON
BLAIR KNOTT, KNOTT ALLISON BLAIR). Getting the full list for every truncated
row would mean a detail-page visit per row -- neither `_fetch_durham` (no
detail-page hop at all today) nor `_fetch_wake`'s existing one-hop
related-documents visit (a different purpose: OTHER instruments a document
references, not this SAME document's own full party list, and itself
budget-capped to `_WAKE_MAX_RELATED_FETCHES`) does this today. Left honestly
flagged, not "fixed" with a change that cannot work at the search-results
level -- the data the task asked for genuinely is not in the markup
`parse_selfservice()` is given.

**CORRECTION 2026-10-14 (cont. x6) -- Iredell: the owner personally solved
the real reCAPTCHA live, and everything downstream of that human-cleared
session is now built, not just documented.** Iredell runs the SAME
Courthouse Computer Systems "DevExpress" product Jasper (SC,
`sc_rod_walled.py`/`rod/ccs_devexpress.py`) already uses -- confirmed live,
not assumed from the platform-match pattern that got this file's own
Durham entry wrong in 2026-10-12 (same `#subapp_LRSearch_0` iframe,
`#DocTypes`/`#doctypes_dialog`, `#btnAdvancedSearch`, `#gridTrad`, and the
identical `ccs-home_ui_helper.js` heartbeat bundle). `_fetch_iredell`
(below) drives `rod.ccs_devexpress.discover_recent_distress_via_browser`
exactly the way `sc_rod_walled.py`'s own `_fetch_jasper` does, over
Iredell's own base URL/doc codes -- see that module's own docstring's
"IREDELL" section for the FULL live evidence this pass gathered (doc-type
dictionary, real sample rows per bucket, the session-reuse measurement,
and -- the one operationally load-bearing difference from Wake above --
why Iredell's own clearance does NOT survive a fresh navigation/tab, so
`_fetch_iredell` drives the SAME already-cleared `page` in place via
in-page JS only and never re-navigates). Still genuinely walled for an
UNATTENDED run (`solve_recaptcha_v2` never actually clears this real
reCAPTCHA v2, same as Wake's own) -- this pass does not and will not
change that; only what happens once a human already has stays new here.
`rod/ccs_devexpress.py` itself was generalized this pass (a live,
`header_map`-driven column resolver, built because Iredell's own grid
column layout turned out genuinely different from Jasper's, not just
relabeled -- see that module's docstring) rather than given a
Iredell-only hand-rolled parser, so the next CCS county (Craven, Greene,
Harnett, Randolph, or Stokes, all still queued -- see `_COUNTY_SITES`
below) is now much closer to "new county config + a live doc-type/column
check" than "rebuild the parser."

Strategy:
1. Launch Playwright browser (headful -- required; see the `headless=False`
   note on the browser launch call below).
2. Navigate to the entry/disclaimer page.
3. Durham (`gate == "none"`): click the disclaimer Accept button, no CAPTCHA
   -- see `_fetch_durham`.
4. Otherwise: if math captcha, try math_captcha.solve_math_captcha(page); if
   reCAPTCHA V2, try enrichment_recaptcha_audio.solve_recaptcha_v2(page).
   reCAPTCHA V2 is live-reverified 2026-10-14 to never actually get past
   Wake/Iredell/Craven/Greene/Harnett/Randolph/Stokes's real gates (see
   above) -- these 7 are expected to always fall through to the WAF-bypass
   attempt and then `continue` past, genuinely blocked, by design. Brunswick
   (`gate == "math"`) is DIFFERENT as of the 2026-10-14 (cont.) correction
   above: `solve_math_captcha` now actually solves it (OCRs the image
   question via Gemini) when quota/the model is available, and correctly
   returns `False` -- same as the other 7 -- when it isn't, rather than the
   old silent wrong "success".
5. Once through, search for deeds by date range.
6. Parse results: Durham via its own row parser (`_durham_record_to_listing`
   / `parse_selfservice`), Brunswick via its own (`_fetch_brunswick` /
   `_brunswick_parse_page` / `_brunswick_record_to_listing` -- see the
   2026-10-14 (cont. x2) correction above), everything else via the generic
   `_parse_html`, which only matches `<table>` markup and would need rework
   if any of the 7-always-walled counties ever actually clears its gate --
   none of them use a `<table>` either, per the live HTML pulled 2026-10-14.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind
from ...rod import ccs_devexpress

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Brunswick (inttek.net "RecordingPRO") -- Combined Real Property search.
# Live-verified end-to-end 2026-10-14 via httpx replaying the real site (no
# browser, same memory-pressure reasoning math_captcha.py's own live
# verification used): math CAPTCHA -> disclaimer accept -> "Combined Real
# Property / MAPS" menu item -> RealEstateForm search -> real paginated
# results, including fetching a real 2-page "BRUNSWICK-property-B5631-
# P1335.pdf" document and a real Document Details page with a BRAND NEW,
# cookie-less httpx client (no prior requests at all) -- confirming the
# "Download PDF" (`pdf-popup-download-all.ntk?s=...`) and "View Detail"
# (`re_detail.ntk?s=...`) links are durable, stateless, signed-token URLs,
# NOT a server-side session gate like Durham's `JSESSIONID` cookie or
# Rowan/Logan's session-scoped image keys. This whole site, in fact, never
# sets a cookie anywhere in the chain (confirmed: an `httpx.Client` after the
# full CAPTCHA+disclaimer+search flow still has `{}` in `.cookies`) -- every
# "session" is carried by the signed `s=` query token alone.
#
# This also surfaced a real platform quirk worth flagging: pagination state
# is NOT encoded in the `s=` token (confirmed by running a SECOND,
# DIFFERENT search from the same box between fetching a results page and
# clicking its own "page 2" link -- the later search silently became the
# "current" one, and the page-2 click landed on page 2 of the WRONG search).
# Re-run immediately with no interleaved search, it works correctly ("Page 2
# of 9"). This looks like server-side state keyed to the requesting
# IP/connection rather than the token itself -- a real constraint for two
# concurrent scrapers sharing an egress IP, but not a problem for this
# single sequential Playwright page, which never interleaves two searches.
#
# "Combined Real Property" is NOT a distress-only index -- a 90-day window
# returned 10,896 records of every instrument type (deeds, mortgages,
# satisfactions, UCC filings, powers of attorney, etc.). The real Document
# Type dropdown (live-captured 2026-10-14, 49 options) has no "TRUSTEE
# DEED"/"FORECLOSURE DEED" option at all -- NC non-judicial foreclosures
# record as "SUBSTITUTE TRUSTEE" (the trustee-appointment filing that always
# precedes a sale, same pre-foreclosure signal nc_rod_logan.py's FCL/S-TR
# codes capture) and "NOTICE OF FORECLOSURE"; the eventual sale deed records
# as a plain "DEED", indistinguishable here from any ordinary sale -- a
# real, flagged gap, not silently claimed covered. Filtering the search to
# just these 2 doc types (one search each) cut the 90-day volume to 271 and
# 82 records respectively -- a live-confirmed, scrapeable number instead of
# the unfiltered firehose.
#
# Each instrument with MULTIPLE grantors (e.g. co-owned property) gets ONE
# INDEX ROW PER GRANTOR NAME, all sharing the same Book/Page and an
# identical Grantee list -- live-confirmed on a real 3-grantor SUBSTITUTE
# TRUSTEE instrument (book 5596 page 1287: "VEGA, ESTEBAN EMILIO" / "MILLS,
# BRANDI" / "ROCKET MORTGAGE, LLC" as three separate Grantor rows). Grouped
# back into ONE Listing per (book, page) below so co-owners (and the
# original lender, who also shows up as a "grantor" in this chain) don't
# become duplicate or false-positive leads -- the lender is filtered out by
# an institutional-name check (same purpose as nc_rod_logan.py's
# `_is_institutional`, kept as Brunswick's own small copy rather than
# importing a sibling scraper's private helpers).
#
# This platform ALSO live-confirmed something the generic 90-day-window
# convention used elsewhere in this file gets backwards here: with "Sort by
# Recording Date" checked, page 1 holds the OLDEST records in the window
# (07/22/2026 in a 07/16-10/14 window) and the LAST page holds the NEWEST
# (10/13/2026, one day before this verification) -- i.e. ascending, not
# descending. The pagination row always links the last page number directly
# even when far away (confirmed on a real 28-page result: "1 ..... 14 15 16
# ... 28" -- "28" is a real clickable link from page 1), and a dedicated
# `#prev_page` button walks backward one page at a time from there. So
# instead of Durham's "page 1 only, oldest end of the window" partial
# coverage, Brunswick jumps straight to the last page and walks backward --
# genuinely the freshest leads first, still only a few pages deep (budget
# below), not the full window.
_BRUNSWICK_LOOKBACK_DAYS = 90
#: Pages fetched per doc type, walking backward from the newest page -- a
#: budget cap in the same spirit as nc_rowan_cott.py's _MAX_DETAIL_FETCHES.
#: 271 SUBSTITUTE TRUSTEE / 82 NOTICE OF FORECLOSURE records over 90 days
#: (10/page) means this is genuinely partial coverage of the window, newest
#: first -- documented here, not silently implied complete.
_BRUNSWICK_MAX_PAGES = 5
_BRUNSWICK_DOC_TYPES = ("SUBSTITUTE TRUSTEE", "NOTICE OF FORECLOSURE")
_BRUNSWICK_PAGE_OF_RE = re.compile(r"Page\s+\d+\s+of\s+(\d+)")
_BRUNSWICK_PDF_HREF_RE = re.compile(r"pdf-popup-download-all\.ntk", re.I)
_BRUNSWICK_DETAIL_HREF_RE = re.compile(r"re_detail\.ntk", re.I)

try:  # reuse the shared business-name filter when importable, same fallback
      # pattern nc_rod_logan.py uses for the same import
    from ...enrichment_address_backfill import _BUSINESS_STOPWORDS as _BRUNSWICK_BUSINESS_STOPWORDS
except Exception:  # pragma: no cover - defensive fallback, never raise on import
    _BRUNSWICK_BUSINESS_STOPWORDS = {
        "llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp",
        "llp", "trust", "trustee", "estate", "of", "the", "and",
    }
#: Institutional/lender/servicer keywords seen live on Brunswick's own
#: Grantor/Grantee rows (DHI MORTGAGE, FAIRWAY INDEPENDENT MORTGAGE, MORTGAGE
#: ELECTRONIC REGISTRATION SYSTEMS / MERS, CARRINGTON MORTGAGE SERVICES,
#: PRESIDENTIAL BANK FSB, ROCKET MORTGAGE, BB&T COLLATERAL SERVICE) -- a
#: Brunswick-specific complement to nc_rod_logan.py's own copy, not a shared
#: import (same reasoning nc_rod_logan.py gives for its own copy: these
#: scrapers are independent and each keeps its own small list).
_BRUNSWICK_INSTITUTION_WORDS = {
    "bank", "mortgage", "mtg", "services", "service", "servicing", "servicer",
    "financial", "finance", "federal", "credit", "association", "assn",
    "capital", "loan", "national", "savings", "bancorp", "holdings",
    "lending", "fsb", "nationstar", "systems", "registration", "electronic",
    "collateral",
    # Added for Iredell's own live JGMT rows, 2026-10-14 (see
    # `_iredell_doc_to_listing`/module docstring's "IREDELL" section):
    # NCDOT eminent-domain condemnation judgments index "DEPARTMENT OF
    # TRANSPORTATION" as BOTH grantor and grantee on self-referential rows
    # alongside the real affected owner -- without this, the state
    # condemnation plaintiff could wrongly become the "defendant" lead.
    "department", "transportation",
}


def _brunswick_is_institutional(name: str | None) -> bool:
    """True if a Grantor/Grantee name reads as a lender/trustee/servicer,
    not the actual distressed homeowner. Defensive: empty/None -> True.
    A trailing "/TR" (every substitute-trustee entity AND the individual
    attorneys acting as one, e.g. "STEPHENS, H. KENNETH II /TR", live-
    confirmed 2026-10-14) marks a non-owner even when the name itself has no
    institutional keyword."""
    s = (name or "").strip()
    if not s:
        return True
    if s.rstrip().lower().endswith("/tr"):
        return True
    toks = set(re.sub(r"[^a-z\s]", " ", s.lower()).split())
    return bool(toks & _BRUNSWICK_BUSINESS_STOPWORDS) or bool(toks & _BRUNSWICK_INSTITUTION_WORDS)


def _brunswick_dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _brunswick_names_in_cell(td: Any) -> list[str]:
    """Every name inside a Grantor/Grantee result cell. Live markup nests
    ONE name per row in a small inner `<table>` (first row labelled
    "Grantor:"/"Grantee:", any further names on blank-labelled rows below
    it) -- confirmed live 2026-10-14 on a 5-name Grantee cell. A cell with
    no nested table (a single plain name) falls back to its own text, minus
    the "Grantor:"/"Grantee:" label."""
    inner = td.find("table")
    if inner is None:
        text = td.get_text(" ", strip=True)
        text = re.sub(r"^(?:Grantor|Grantee):\s*", "", text)
        return [text] if text else []
    names: list[str] = []
    for tr in inner.find_all("tr", recursive=False):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        name = cells[-1].get_text(" ", strip=True)
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Wake (Tyler "Self-Service", same tenant family as Durham) -- live-verified
# 2026-10-14 AFTER the owner personally solved the real Google reCAPTCHA
# checkbox on Wake's disclaimer page (the same hard boundary this whole file
# respects for every other county here -- the CAPTCHA itself is never
# automated). Everything below was exercised through that human-cleared
# browser session: identical markup (`li.ss-search-row` /
# `ul.selfServiceSearchResultColumn`) and identical field ids
# (`#field_RecordingDateID_DOT_StartDate`/`_EndDate`, `#searchButton`) to
# Durham's own Tyler "Self-Service" tenant (DOCSEARCH341S2 here vs Durham's
# DOCSEARCH5S1) -- confirmed by pulling the real DOM (`outerHTML`) of live
# search rows, not by platform-match inference the way the 2026-10-12 entry
# got Durham wrong (see module docstring). `_fetch_wake` therefore reuses
# `rod.nc_tyler.parse_selfservice()` verbatim, same as `_fetch_durham`, no
# third hand-rolled row parser.
#
# UNLIKE Durham (one unfiltered page-1 date-range pull -- fine there because
# Durham's own 2026-10-07 docstring already established "no challenge" and
# it's a lower-volume county), Wake's own `field_selfservice_documentTypes`
# input is a real tag/token field, live-confirmed to need an actual commit
# keystroke: typing text alone (even via a direct `.value` property-setter
# dispatch, tried and failed live) does NOT filter the search -- only after
# pressing Enter does the typed text become a removable chip
# (`<span>SUBSTITUTE TRUSTEE <a class="...">x</a></span>`) and the results
# summary line changes to "...and Document types in SUBSTITUTE TRUSTEE".
# Wake's own live Document Type facet counts (14-day window, 2026-10-14) show
# this county's version of nc_rod_logan.py's "S/TR"/"FCL" pre-foreclosure
# codes are literally spelled "SUBSTITUTE TRUSTEE" (43 in 14 days) and
# "FORECLOSURE NOTICE" (7 in 14 days) -- the other 44 real Document Types
# seen live (DEED 985, DEED OF TRUST 1045, SATISFACTION 1087, ASSIGNMENT 309,
# etc.) are routine filings, not distress signals, same judgment call
# nc_rod_logan.py's own `_classify()` already makes (a plain DEED OF TRUST
# origination is not itself distress). Scoping the search to these 2 types up
# front (one search per type, Brunswick's own convention, not Durham's
# unfiltered-page-1 one) keeps Wake's own 90-day pull small and complete
# instead of Durham's thousands-of-rows-page-1-only gap: a live two-type
# 90-day search (Jul 16 - Oct 14 2026) returned exactly 256 total real
# results across 11 pages of ~25/page -- SUBSTITUTE TRUSTEE alone was 222
# across 9 pages, confirmed live by reading `Showing page 1 of 9 for 222
# Total Results`. Each type is searched SEPARATELY (not combined in one
# query) specifically to keep each page's own `doc_type_filter` trustworthy
# for classification -- see the next paragraph for why `record.doc_type`
# itself cannot be trusted alone.
#
# Real, live-pulled gotcha this scraper works around: a record whose
# Document Type was administratively corrected renders TWO values in the
# "Document Type" column, the OLD one struck through first
# (`<span style="text-decoration: line-through;">SEE</span>`) then the live
# one second (confirmed live, instrument 2026086748: "SEE" / "SUBSTITUTE
# TRUSTEE"). `rod.nc_tyler.parse_selfservice()` (correctly, for Durham, which
# never hit this live) takes `cols[...][0]` -- the FIRST value -- so on a
# corrected Wake row that would silently read back "SEE", not the real type.
# `_wake_record_to_listing` below never trusts `record.doc_type` for
# classification for exactly this reason: it always uses the KNOWN per-search
# `doc_type_filter` (the type this page was searched for, same shape as
# `_brunswick_record_to_listing`'s `doc_type = rec.get("doc_type") or
# doc_type_filter` fallback, just made the primary source here instead of a
# fallback) -- `record.doc_type` is kept in `raw` for provenance only.
#
# A second real, live-confirmed gap: Wake's search-RESULT row (unlike
# Durham's -- or so this file assumed until the 2026-10-14 re-check below)
# caps each Grantor/Grantee column's VISIBLE names at 5
# (`ul.selfServiceSearchResultColumn.five-line-block-with-text` -- a CSS/DOM
# cap, not a rendering artifact) even when the column header's own count says
# more exist (live-confirmed: "Grantor/Party 1 (7)" with only 5 `<li>` name
# nodes actually in the DOM for instrument 2026086748 -- VERNON VERNON J /
# VERNON TERRI L / NEWREZ LLC /TRDG A IN F / NEW PENN FINANCIAL, LLC /
# SHELLPOINT MORTGAGE SERVICING /A IN F, 2 more real parties not rendered
# here at all). GENUINELY NOT FIXABLE at this level, re-confirmed 2026-10-14:
# Durham has the EXACT SAME 5-name cap (not Wake-only after all -- live scan
# of the newest 2,000 Durham rows found 151, ~7.6%, with a declared party
# count above 5; one real example kept as a test fixture, instrument
# 2026190164, "Grantor/Party 1 (12)" with only 5 `<li>` nodes in the DOM), and
# the missing names ARE confirmed to exist one hop deeper -- that document's
# own detail page (`/web/document/DOC291S618?search=DOCSEARCH5S1`, fetched
# live) lists all 12 real grantors in its "Names" section. Not patched here:
# neither `_fetch_durham` nor `_fetch_wake`'s own one-hop related-documents
# visit (a different purpose -- OTHER instruments a document references, not
# this SAME document's own full party list) fetches every row's own detail
# page just for this, and doing so for every truncated row would need a new
# per-row detail-page hop this pass does not add -- a real, flagged
# partial-capture gap on any record with >5 grantors or >5 grantees, same
# honesty convention as every other partial-coverage note in this file
# (Durham's own page-budget cap, Brunswick's page-budget cap).
#
# A THIRD real, live-confirmed gap, and the most consequential one for lead
# completeness: `rod.nc_tyler.parse_selfservice()`'s shared `_SS_HEAD` regex
# -- used by Durham too, not something this pass rewrites -- used to only
# capture ONE Book/Page pair per header. A SUBSTITUTE TRUSTEE instrument that
# references MULTIPLE original tracts renders TWO (or more) "B: x P: y"
# pairs in the same `<h1>` with no middle bullet between them (live-pulled,
# instrument 2026086748: "2026086748  •  B: 020299 P: 01082   B: 020299 P:
# 01083  •  07/31/2026 08:50 AM") -- confirmed live by running that EXACT
# captured text through the OLD `_SS_HEAD.match()`: it returned `None`, so
# `recorded`/`instrument_no`/`book`/`page` all came back `None` on that row
# (grantor/grantee/doc_type/description still parsed fine -- only the header
# line failed). `_wake_record_to_listing` (and `_durham_record_to_listing`,
# same shared behavior) both require a non-empty `instrument_no` and return
# `None` otherwise, so a real multi-tract SUBSTITUTE TRUSTEE lead like this
# one was SILENTLY DROPPED on both Wake and Durham, not just mis-parsed.
#
# **FIXED 2026-10-14**: `_SS_HEAD` now splits the header on its two bullets
# first (instrument_no • middle blob • date), then pulls `BT:`/`B:`+`P:` out
# of the middle blob with their own sub-patterns (`_SS_HEAD_BT`/
# `_SS_HEAD_BP`) instead of requiring one fixed slot sequence -- so
# instrument_no/date no longer depend on how many book/page pairs the middle
# section holds. Re-run live against the SAME captured multi-tract text
# above: `instrument_no` is now `"2026086748"`, `recorded` is
# `"2026-07-31"`, and `book`/`page` are the FIRST pair (`020299`/`01082`,
# the primary tract -- the second tract's pair is not separately modeled).
# Ordinary single-pair headers (Durham's `BT: OPR B: 10616 P: 073`, Wake's
# plain `B: 020291 P: 01139`) still parse identically to before.
# `tests/test_nc_rod_captcha.py` was updated to assert the new fixed
# behavior rather than the old documented-gap behavior.
#
# Related Documents (one hop, as asked): each document's own detail page
# (`/web/document/{docid}?search={search_id}`) auto-fires a real XHR
# (`GET /web/document/relatedDocuments/{docid}?queryId={...}&search={search_id}`)
# that live-confirmed returns real related-instrument rows (one real example,
# instrument 2026111052 "NOTICE OF CORRECTION": 1 related DEED from
# 09/06/1960, book/page "001422-00299", its own grantor/grantee names) --
# the ORIGINAL instrument a correction/trustee/foreclosure filing concerns,
# genuinely useful chain-of-title context the task asked to confirm was being
# captured. The `queryId` itself is per-search-session and not exposed as a
# simple global anywhere reachable without deeper reverse-engineering (tried
# live, not found on `window`) -- `_fetch_wake_related` therefore just
# navigates to the document's own detail page and reads the SAME panel a
# human would see, rather than hand-building the relatedDocuments URL, and is
# budget-capped (`_WAKE_MAX_RELATED_FETCHES`) to the newest leads found, same
# spirit as nc_rowan_cott.py's `_MAX_DETAIL_FETCHES`. Related-document ROWS
# here are index metadata (type/date/book-page/parties), not a document
# image/PDF -- never passed to `document_links.stamp_documents` (nothing to
# stamp), just embedded as structured data under `raw["wake_detail"]
# ["related_documents"]`.
#
# Per-document PDF images (`/web/document-image-pdf/{docid}/{queryId}/
# {docnum}-{index}.pdf`) are live-confirmed to need the SAME live session as
# everything else here (a cookie-less `curl` against a real URL pulled from
# this exact session got a `302` to `/web/user/disclaimer`) -- identical gap
# to Durham's own cookie-gated PDF route (see module docstring), and
# deliberately NOT stamped here for the same reason: `enrichment_doc_ocr.py`
# fetches stamped URLs with a stateless `httpx.AsyncClient` with no cookie
# jar from this scraper's Playwright run, so a stamped link here would
# silently 302 to the disclaimer HTML and fail OCR invisibly.
#
# SESSION-REUSE WINDOW (the operational question this pass was specifically
# asked to answer): see the module docstring's own "Wake session-reuse"
# section for the full live-measured writeup and evidence. Short version:
# the reCAPTCHA clearing itself stays a manual, operator-driven step -- this
# file does not and will not try to automate solving it -- but the session it
# produces is NOT a one-shot token. The live Tyler Self-Service client ships
# its own `GET /web/session/pingSession` heartbeat (observed firing roughly
# every 10-20s while a tab sits open) specifically to keep the server-side
# session alive, which is itself strong evidence the underlying session has a
# real, finite idle timeout the platform expects a client to actively defer --
# not a single-use artifact that dies the instant the browser that cleared it
# closes.
#: Durham pagination budget (2026-10-14 (cont. x4) fix -- see module
#: docstring). Live-verified: an unfiltered 90-day window is 95 pages of
#: ~100 rows/page (~9,500 rows total, newest-first) -- walking it in full
#: every run is neither bounded nor polite. 20 pages (~2,000 rows, the
#: newest ~19 days' worth at the observed ~106 rows/day rate) is a ~20x
#: improvement over the old page-1-only behavior while staying a real,
#: documented budget cap, the same proportion of partial coverage (~21%)
#: Brunswick's own _BRUNSWICK_MAX_PAGES already accepts (~18%) -- not
#: silently implied complete past this cap, same honesty convention as
#: every other page budget in this file.
_DURHAM_MAX_PAGES = 20

_WAKE_LOOKBACK_DAYS = 90
#: Pages read per doc type (~25 rows/page) -- live 90-day counts were 222
#: (SUBSTITUTE TRUSTEE, 9 pages) and well under that for FORECLOSURE NOTICE;
#: capped higher for headroom. Still documented as partial-if-exceeded, same
#: honesty convention as every other page budget in this file.
_WAKE_MAX_PAGES = 12
_WAKE_DISTRESS_DOC_TYPES = ("SUBSTITUTE TRUSTEE", "FORECLOSURE NOTICE")
#: Budget cap on the one-hop related-documents follow-through (one extra page
#: load per document) -- same spirit as nc_rowan_cott.py's
#: _MAX_DETAIL_FETCHES, applied to the newest leads built first.
_WAKE_MAX_RELATED_FETCHES = 25
#: Shared Tyler "Self-Service" pagination-summary regex -- Durham and Wake are
#: the same platform/tenant family and render the identical "Showing page X
#: of Y" text (live-confirmed on both 2026-10-14), so one regex covers both
#: rather than a near-duplicate per county.
_SS_PAGE_OF_RE = re.compile(r"Showing page\s+\d+\s+of\s+(\d+)", re.I)

#: Iredell -- Courthouse Computer Systems "DevExpress" product, SAME vendor
#: platform as SC's Jasper county (`rod/ccs_devexpress.py`, built for Jasper
#: first, generalized this pass for Iredell's own, genuinely different
#: column layout -- see that module's docstring's "IREDELL" section for the
#: full live evidence this pass gathered, driven directly against the
#: owner's own reCAPTCHA-cleared browser-pane tab). `_fetch_iredell` below
#: calls into that shared module exactly the way `sc_rod_walled.py`'s own
#: `_fetch_jasper` does, with Iredell's own base URL/doc codes.
_IREDELL_BASE = ccs_devexpress.base_url("NC", "Iredell") or "https://iredellnc.courthousecomputersystems.com"

#: Craven/Greene/Harnett/Randolph/Stokes -- final batch on this same CCS
#: DevExpress platform, added 2026-10-14 (see rod/ccs_devexpress.py module
#: docstring's "CRAVEN/GREENE/HARNETT/RANDOLPH/STOKES" section for the full
#: live evidence). lower-case `_COUNTY_SITES` key -> (proper-case county
#: name as `ccs_devexpress.CCS_DEVEXPRESS_COUNTIES` spells it, days_back,
#: max_pages, max_docs, doc_codes) -- fed straight into
#: `_fetch_ccs_devexpress_county` below so these 5 counties share ONE
#: generic fetch/convert path instead of 5 hand-maintained near-duplicates
#: of Iredell's own bespoke `_fetch_iredell`/`_iredell_doc_to_listing`
#: (left untouched, already shipped, already tested).
_CCS_DEVEXPRESS_COUNTIES_NC: dict[str, tuple[str, int, int, int, tuple[str, ...]]] = {
    "craven": ("Craven", ccs_devexpress.CRAVEN_LOOKBACK_DAYS, ccs_devexpress.CRAVEN_MAX_PAGES,
               ccs_devexpress.CRAVEN_MAX_DOCS, ccs_devexpress.CRAVEN_DISTRESS_DOC_CODES),
    "greene": ("Greene", ccs_devexpress.GREENE_LOOKBACK_DAYS, ccs_devexpress.GREENE_MAX_PAGES,
               ccs_devexpress.GREENE_MAX_DOCS, ccs_devexpress.GREENE_DISTRESS_DOC_CODES),
    "harnett": ("Harnett", ccs_devexpress.HARNETT_LOOKBACK_DAYS, ccs_devexpress.HARNETT_MAX_PAGES,
                ccs_devexpress.HARNETT_MAX_DOCS, ccs_devexpress.HARNETT_DISTRESS_DOC_CODES),
    "randolph": ("Randolph", ccs_devexpress.RANDOLPH_LOOKBACK_DAYS, ccs_devexpress.RANDOLPH_MAX_PAGES,
                 ccs_devexpress.RANDOLPH_MAX_DOCS, ccs_devexpress.RANDOLPH_DISTRESS_DOC_CODES),
    "stokes": ("Stokes", ccs_devexpress.STOKES_LOOKBACK_DAYS, ccs_devexpress.STOKES_MAX_PAGES,
               ccs_devexpress.STOKES_MAX_DOCS, ccs_devexpress.STOKES_DISTRESS_DOC_CODES),
}


def _wake_extract_docids(html: str) -> list[str]:
    """data-documentid for each li.ss-search-row, in the SAME document order
    `rod.nc_tyler.parse_selfservice()` itself walks (both iterate
    `soup.select("li.ss-search-row")`) -- used to pair each parsed
    IndexRecord with the real docid that shared parser never captures, so
    `_fetch_wake` can build each document's own detail-page URL for the
    one-hop related-documents follow-through below."""
    soup = BeautifulSoup(html or "", "html.parser")
    return [li.get("data-documentid") or "" for li in soup.select("li.ss-search-row")]


def _wake_parse_related_documents(html: str, base_url: str = "") -> list[dict]:
    """Parse Wake's real Related Documents panel (live markup, confirmed
    2026-10-14 -- see module docstring's Wake constants block) -- one dict
    per related instrument: doc_type, recording_date, external_id (the
    book/page-style id the UI shows, e.g. "001422-00299"), document_url (the
    in-app link to THAT related document's own detail page -- index-level
    navigation, NOT a document image/PDF, so never passed to
    `document_links.stamp_documents`), grantors, grantees. Empty list on no
    related documents / unparseable HTML, never raises."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []

    def _names(div: Any) -> list[str]:
        if div is None:
            return []
        return [n.strip() for n in div.get_text("\n").split("\n") if n.strip()]

    for row in soup.select("div.related-table-row"):
        doc_type_el = row.select_one(".related-doc-type")
        date_el = row.select_one(".related-doc-recording-date")
        link = row.select_one("a.document-link")
        panels = row.select(".related-data-panel > div")
        href = link.get("href") if link else None
        out.append({
            "doc_id": row.get("data-docid") or None,
            "doc_type": doc_type_el.get_text(strip=True) if doc_type_el else None,
            "recording_date": date_el.get_text(strip=True) if date_el else None,
            "external_id": link.get_text(strip=True) if link else None,
            "document_url": urljoin(base_url, href) if href else None,
            "grantors": _names(panels[0] if len(panels) > 0 else None),
            "grantees": _names(panels[1] if len(panels) > 1 else None),
        })
    return out


# -- Iredell: Courthouse Computer Systems "DevExpress" (rod/ccs_devexpress.py) --

#: kind bucket (rod.ccs_devexpress.classify_kind_code's return value) ->
#: ListingType. "probate" is deliberately absent: Iredell's own #DocTypes
#: dictionary has NO death-certificate-equivalent code (see
#: rod/ccs_devexpress.py module docstring's "IREDELL" section), so
#: classify_kind_code can never actually return "probate" for a doc_type
#: drawn from IREDELL_DISTRESS_DOC_CODES -- left out rather than mapped to
#: a ListingType that would never be reached, so this table only claims
#: buckets this county can really produce.
_IREDELL_LISTING_TYPE: dict[str, ListingType] = {
    "lis_pendens": ListingType.LIS_PENDENS,
    # FCL/S-TR are both NC pre-/in-process foreclosure signals -- same
    # LIS_PENDENS bucket Wake's own SUBSTITUTE TRUSTEE/FORECLOSURE NOTICE
    # doc types and Clarendon's own FORECLOS/TRUSTEE/NOTICE OF SALE kinds
    # already use elsewhere in this codebase, not a new type.
    "foreclosure": ListingType.LIS_PENDENS,
    "pre_foreclosure": ListingType.LIS_PENDENS,
    "bankruptcy": ListingType.BANKRUPTCY,
    # LIEN_CLAIM (not TAX_LIEN, Jasper's own catch-all): a generic LIEN or
    # a civil JGMT both read, on Iredell's own live rows, as the
    # contractor/HOA/judgment-creditor class of claim LIEN_CLAIM's own
    # docstring describes, not a government property-tax lien.
    "lien": ListingType.LIEN_CLAIM,
    "judgment": ListingType.LIEN_CLAIM,
}


def _iredell_defendant(grantor: str | None, grantee: str | None) -> str | None:
    """The real individual -- homeowner, debtor, or judgment party -- for
    an Iredell row. UNLIKE Jasper's own single fixed "claimant is grantor,
    owner is grantee" convention (rod.ccs_devexpress._jasper_defendant()),
    Iredell's own live rows showed BOTH orientations depending on doc kind:
    FCL has the homeowner as grantor / lender as grantee (the SAME
    convention Wake's own SUBSTITUTE TRUSTEE rows use elsewhere in this
    file), while S/TR has the OPPOSITE -- lender as grantor, homeowner as
    grantee (live examples: Book 3238/Page 1295 FCL, AGUILERA RAFAEL
    grantor / MOVEMENT MORTGAGE LLC grantee; Book 3238/Page 1416 S/TR,
    NEWREZ LLC grantor / MERCER JOHN M. grantee -- see
    rod/ccs_devexpress.py module docstring's "IREDELL" section). This
    never trusts either role fixed, same defensive shape
    `_jasper_defendant` already uses for the identical reason. Reuses
    `_brunswick_is_institutional` (shared with Wake/Brunswick, extended
    this pass with "department"/"transportation" for Iredell's own
    NCDOT-condemnation JGMT noise -- see that set's own comment)."""
    g, e = (grantor or "").strip() or None, (grantee or "").strip() or None
    if not e:
        return g
    if not g:
        return e
    g_inst, e_inst = _brunswick_is_institutional(g), _brunswick_is_institutional(e)
    if g_inst and not e_inst:
        return e
    if e_inst and not g_inst:
        return g
    if g_inst and e_inst:
        # Both sides read institutional -- a real, live-confirmed case:
        # NCDOT eminent-domain condemnation judgments index "DEPARTMENT OF
        # TRANSPORTATION" as BOTH grantor and grantee on some rows (Book
        # 3229/Page 973, DocNo 2000004514). No real individual lead here --
        # the caller (`_iredell_doc_to_listing`) skips the Listing
        # entirely rather than shipping a government agency as the
        # "defendant".
        return None
    # Neither reads institutional -- both individuals (e.g. a judgment
    # between two people). Prefer grantor, the more common "party against
    # whom the record runs" convention across this file's other counties.
    return g


_COUNTY_SITES = {
    # search_path corrected 2026-10-14 from "/user/disclaimer" (the gate page
    # itself) to the real Tyler Self-Service search route -- live-confirmed
    # the exact same way Durham's DOCSEARCH5S1 was: Wake's own search form
    # posts to/reads from /web/search/DOCSEARCH341S2 (same "Self-Service"
    # platform, a different per-tenant search id). See _fetch_wake below.
    "wake": {"url": "https://rodrecords.wake.gov/web", "gate": "recaptcha", "search_path": "/search/DOCSEARCH341S2"},
    # gate "none": live-reverified 2026-10-14 -- no CAPTCHA at all, just a
    # disclaimer click-through. See module docstring's Durham correction.
    "durham": {"url": "https://rodweb.dconc.gov/web", "gate": "none", "search_path": "/search/DOCSEARCH5S1"},
    "brunswick": {"url": "https://brunswick-live.inttek.net", "gate": "math", "search_path": "/search"},
    "iredell": {"url": "https://iredellnc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "craven": {"url": "https://us5.courthousecomputersystems.com/CravenNC2", "gate": "recaptcha", "search_path": "/search"},
    "greene": {"url": "https://greenenc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "harnett": {"url": "https://us6.courthousecomputersystems.com/HarnettNC", "gate": "recaptcha", "search_path": "/search"},
    "randolph": {"url": "https://us5.courthousecomputersystems.com/RandolphNC2", "gate": "recaptcha", "search_path": "/search"},
    "stokes": {"url": "https://us6.courthousecomputersystems.com/StokesNC", "gate": "recaptcha", "search_path": "/search"},
}


class NcRodCaptchaScraper(BaseScraper):
    """NC ROD sites with CAPTCHA/math gate — Playwright + auto-solver."""

    slug = "counties_nc.nc_rod_captcha"
    name = "NC ROD CAPTCHA Sites"
    category = "rod"
    timeout_s = 900.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_rod_captcha.no_playwright")
            return results

        async with async_playwright() as p:
            # headless=False: confirmed live 2026-10-12 -- the Courthouse
            # Computer Systems platform (Stokes/Iredell/Greene/Harnett/
            # Randolph/Craven, 6 of these 9 counties) 403s headless
            # Chromium even on a correct, live URL and 200s the identical
            # request headful. Same bot-detection pattern already proven
            # and fixed for polk_tax.py -- requires a real display
            # (DISPLAY=:99 / Xvfb on the VM, same as Polk/Avalon/Morganton).
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                page = None
                try:
                    page = await browser.new_page()
                    entry_url = cfg["url"]
                    log.info("nc_rod_captcha.fetching", county=county)

                    await page.goto(entry_url, timeout=30000)
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    gate = cfg["gate"]

                    if gate == "none":
                        # Durham: no CAPTCHA, just the disclaimer Accept button --
                        # see module docstring's 2026-10-14 correction. Completely
                        # different DOM (no <table>), so it gets its own parser
                        # instead of the generic search-fill + _parse_html below.
                        county_results = await self._fetch_durham(page, entry_url, cfg["search_path"])
                        results.extend(county_results)
                        await page.close()
                        log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                        continue

                    gate_cleared = False

                    if gate == "math":
                        try:
                            from ...math_captcha import solve_math_captcha
                            gate_cleared = await solve_math_captcha(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.math_failed", county=county, error=str(exc)[:160])

                        if gate_cleared and county == "brunswick":
                            # Brunswick's gate is a 3-step chain -- math CAPTCHA
                            # (just cleared above) -> disclaimer accept link ->
                            # the real "Combined Real Property / MAPS" search UI
                            # -- see module docstring's 2026-10-14 (cont. x2)
                            # correction for the full live-verified writeup. The
                            # generic search_url/_parse_html path below assumes a
                            # <table> this platform never uses (live-confirmed),
                            # so Brunswick gets its own flow, same as Durham's
                            # _fetch_durham.
                            county_results = await self._fetch_brunswick(page, entry_url)
                            results.extend(county_results)
                            await page.close()
                            log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                            continue

                    elif gate == "recaptcha":
                        try:
                            from ...enrichment_recaptcha_audio import solve_recaptcha_v2
                            gate_cleared = await solve_recaptcha_v2(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.recaptcha_failed", county=county, error=str(exc)[:160])

                    if not gate_cleared:
                        log.info("nc_rod_captcha.gate_failed_try_waf", county=county)
                        try:
                            from ...enrichment_waf_oss import solve_waf_via_browser
                            gate_cleared = await solve_waf_via_browser(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.waf_failed", county=county, error=str(exc)[:160])
                        if gate_cleared:
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        else:
                            log.warning("nc_rod_captcha.gate_blocked", county=county)
                            await page.close()
                            continue

                    if county == "wake":
                        # Wake's real gate is a genuine Google reCAPTCHA checkbox --
                        # solve_recaptcha_v2 is live-reverified (module docstring)
                        # to never actually clear it, so gate_cleared only reaches
                        # here for Wake when the Playwright BrowserContext this
                        # scraper is driving was already carrying a human-cleared
                        # session (e.g. a persisted storage_state an operator
                        # captured after solving the checkbox themselves -- see
                        # the module docstring's "Wake session-reuse" finding for
                        # how long that session stays good for). Same Tyler
                        # "Self-Service" platform as Durham -- its own method
                        # below reuses rod.nc_tyler.parse_selfservice(), same as
                        # Durham, instead of a third hand-rolled parser.
                        county_results = await self._fetch_wake(page, entry_url, cfg["search_path"])
                        results.extend(county_results)
                        await page.close()
                        log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                        continue

                    if county == "iredell":
                        # Same shape as Wake just above: solve_recaptcha_v2 is
                        # live-reverified to never actually clear this genuine
                        # reCAPTCHA v2 gate (module docstring), so gate_cleared
                        # only reaches here when the Playwright BrowserContext
                        # was already carrying a human-cleared session. UNLIKE
                        # Wake's own Tyler "Self-Service" platform, this one's
                        # clearance does NOT survive a fresh navigation/tab
                        # (live-confirmed 2026-10-14, see
                        # rod/ccs_devexpress.py module docstring's "IREDELL"
                        # section) -- `_fetch_iredell` therefore drives THIS
                        # SAME already-loaded `page` in place via in-page JS
                        # only (rod.ccs_devexpress.discover_recent_distress_
                        # via_browser), never page.goto()-ing anywhere else,
                        # same convention sc_rod_walled.py's own
                        # `_fetch_jasper` already uses for the same platform.
                        county_results = await self._fetch_iredell(page, entry_url)
                        results.extend(county_results)
                        await page.close()
                        log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                        continue

                    if county in _CCS_DEVEXPRESS_COUNTIES_NC:
                        # Craven/Greene/Harnett/Randolph/Stokes -- the final
                        # batch on this same CCS DevExpress platform, added
                        # 2026-10-14 (see rod/ccs_devexpress.py module
                        # docstring's "CRAVEN/GREENE/HARNETT/RANDOLPH/STOKES"
                        # section). Same shape as Iredell just above for
                        # exactly the same reason: solve_recaptcha_v2 never
                        # actually clears this real reCAPTCHA v2, so
                        # gate_cleared only reaches here on an already
                        # human-cleared session, and (live-reverified on
                        # Craven, presumed shared across this batch) the
                        # clearance does not survive a fresh navigation/tab --
                        # `_fetch_<county>` drives THIS SAME already-loaded
                        # `page` in place, never page.goto()-ing anywhere
                        # else. Routed through one shared, county-
                        # parameterized helper (`_fetch_ccs_devexpress_county`)
                        # instead of 5 hand-maintained near-duplicates.
                        county_results = await self._fetch_ccs_devexpress_county(
                            page, entry_url, *_CCS_DEVEXPRESS_COUNTIES_NC[county])
                        results.extend(county_results)
                        await page.close()
                        log.info("nc_rod_captcha.county_done", county=county, found=len(county_results))
                        continue

                    search_url = f"{entry_url}{cfg['search_path']}"
                    await page.goto(search_url, timeout=30000)

                    cutoff = (datetime.now() - timedelta(days=90))
                    cutoff_str = cutoff.strftime("%m/%d/%Y")
                    end_str = datetime.now().strftime("%m/%d/%Y")

                    for selector in [
                        "input[name*='from'], input[name*='start'], input[name*='begdate']",
                        "input[name*='to'], input[name*='end'], input[name*='enddate']",
                    ]:
                        try:
                            inputs = await page.query_selector_all(selector)
                            if len(inputs) >= 2:
                                await inputs[0].fill(cutoff_str)
                                await inputs[1].fill(end_str)
                                break
                        except Exception:
                            pass

                    for btn_sel in [
                        "button[type='submit']",
                        "input[type='submit']",
                        "a:has-text('Search')",
                        "#btnSearch",
                    ]:
                        try:
                            btn = await page.query_selector(btn_sel)
                            if btn:
                                await btn.click()
                                break
                        except Exception:
                            pass

                    await page.wait_for_load_state("networkidle", timeout=15000)

                    html = await page.content()
                    results.extend(self._parse_html(html, county, entry_url))

                    await page.close()
                    log.info("nc_rod_captcha.county_done", county=county, found=len(results))

                except Exception as exc:
                    log.warning("nc_rod_captcha.county_error", county=county, error=str(exc)[:200])
                    if page:
                        try:
                            await page.close()
                        except BaseException:
                            pass

            await browser.close()

        return results

    async def _fetch_durham(self, page: Any, entry_url: str, search_path: str) -> list[Listing]:
        """Durham ROD: disclaimer click-through only, no CAPTCHA (confirmed live
        2026-10-14 -- see module docstring's Durham correction for the full
        evidence, including why the 2026-10-12 "very likely the same reCAPTCHA"
        guess was wrong). Tyler "Self-Service" platform, same as Wake, but this
        tenant never actually renders a recaptcha widget.
        """
        results: list[Listing] = []

        try:
            accept_btn = await page.wait_for_selector("#submitDisclaimerAccept", timeout=10000)
            await accept_btn.click(force=True)
            # The Accept click fires a client-side JS redirect, not a normal
            # navigation -- a `networkidle` wait immediately after the click
            # still sees the disclaimer page (confirmed live). Give the
            # redirect time to land on /web/ before moving on.
            await page.wait_for_timeout(4000)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_disclaimer_failed", error=str(exc)[:160])
            return results

        search_url = f"{entry_url}{search_path}"
        try:
            await page.goto(search_url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)

            cutoff = datetime.now() - timedelta(days=90)
            start_str = cutoff.strftime("%m/%d/%Y")
            end_str = datetime.now().strftime("%m/%d/%Y")

            start_input = await page.wait_for_selector(
                "#field_RecordingDateID_DOT_StartDate", timeout=10000)
            end_input = await page.query_selector("#field_RecordingDateID_DOT_EndDate")
            await start_input.fill(start_str)
            await end_input.fill(end_str)

            search_btn = await page.query_selector("#searchButton")
            if not search_btn:
                log.warning("nc_rod_captcha.durham_no_search_button")
                return results
            await search_btn.click()
            await page.wait_for_timeout(5000)
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_search_failed", error=str(exc)[:160])
            return results

        # Real pagination (2026-10-14 (cont. x4) fix -- see module docstring
        # and `_DURHAM_MAX_PAGES`). Page 1's own full page load (above) already
        # carries the "Showing page X of Y" summary the same way Wake's does
        # (same Tyler "Self-Service" platform/tenant family, live-confirmed
        # identical text) -- read it once here, then walk pages 2..N the SAME
        # way `_fetch_wake` does: a direct `searchResults/<search_id>?page=k`
        # navigation per page, not a second search submit.
        search_id = search_path.rsplit("/", 1)[-1]
        html = await page.content()
        m = _SS_PAGE_OF_RE.search(html)
        total_pages = int(m.group(1)) if m else 1
        pages_to_fetch = min(total_pages, _DURHAM_MAX_PAGES)
        log.info("nc_rod_captcha.durham_search_done", total_pages=total_pages, pages_to_fetch=pages_to_fetch)

        from ...rod.nc_tyler import parse_selfservice
        all_records = []
        try:
            all_records.extend(parse_selfservice(html))
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_parse_failed", page_num=1, error=str(exc)[:160])

        for pg_num in range(2, pages_to_fetch + 1):
            try:
                await page.goto(f"{entry_url}/searchResults/{search_id}?page={pg_num}", timeout=20000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                page_html = await page.content()
            except Exception as exc:
                log.warning("nc_rod_captcha.durham_page_failed", page_num=pg_num, error=str(exc)[:160])
                break
            try:
                all_records.extend(parse_selfservice(page_html))
            except Exception as exc:
                log.warning("nc_rod_captcha.durham_parse_failed", page_num=pg_num, error=str(exc)[:160])
                continue

        log.info("nc_rod_captcha.durham_rows", count=len(all_records),
                  truncated=total_pages > _DURHAM_MAX_PAGES)

        for record in all_records:
            li = self._durham_record_to_listing(record, search_url)
            if li is not None:
                results.append(li)

        return results

    def _durham_record_to_listing(self, record: Any, source_url: str) -> Listing | None:
        """Build a Listing from one `rod.nc_tyler.parse_selfservice` IndexRecord.
        Reuses that already-tested parser (same `rod/nc_tyler.py` module that
        already correctly found, on 2026-10-07, that Durham's disclaimer page
        "loads Google's reCAPTCHA script but showed no challenge" -- a finding
        this file's own 2026-10-12 entry contradicted and got wrong, see the
        module docstring's Durham correction) instead of hand-rolling a second
        parser for the exact same HTML shape. Mirrors the shared `_parse_html`'s
        raw-key shape (county/doc_type/filing_date/grantor/grantee/book_page)
        so no new raw keys need registering in web_artifact.py."""
        doc_number = (record.instrument_no or "").strip()
        if not doc_number:
            return None

        book_page = " ".join(
            p for p in (
                f"BT: {record.index_code}" if record.index_code else "",
                f"B: {record.book}" if record.book else "",
                f"P: {record.page}" if record.page else "",
            ) if p
        )

        return Listing(
            source=self.slug,
            source_url=source_url,
            listing_type=ListingType.UNKNOWN,
            property_kind=PropertyKind.UNKNOWN,
            county="Durham",
            state="NC",
            case_number=doc_number,
            owner_name=", ".join(record.grantees) or None,
            plaintiff=", ".join(record.grantors) or None,
            legal_description=record.description or None,
            raw={
                "county": "durham",
                "doc_type": record.doc_type or "",
                "filing_date": record.recorded or "",
                "grantor": ", ".join(record.grantors),
                "grantee": ", ".join(record.grantees),
                "book_page": book_page,
            },
        )

    async def _fetch_brunswick(self, page: Any, entry_url: str) -> list[Listing]:
        """Brunswick ROD: math CAPTCHA already cleared by the caller (see
        `fetch()`'s `gate == "math"` branch) -- this picks up right after,
        clicks through the disclaimer, enters the real "Combined Real
        Property / MAPS" search, and walks the newest-first pages of 2
        distress-relevant doc types. See this module's Brunswick constants
        block above for the full live-verified writeup (2026-10-14, via
        httpx replaying the real site)."""
        results: list[Listing] = []

        # Step 1: disclaimer accept. TWO links exist here -- "I do NOT
        # agree with the License above" (listed FIRST in the live DOM) and
        # "I have read, and agree with the License above" (listed second).
        # A substring match on "agree with the License" matches BOTH (this
        # module's own live verification hit exactly that bug once: it
        # landed on a real "You have Logged Off this system" page instead).
        # The full phrase below is unambiguous -- it is not a substring of
        # the NOT-agree link's text.
        try:
            accept_link = page.locator("a", has_text="I have read, and agree with the License above")
            await accept_link.first.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception as exc:
            log.warning("nc_rod_captcha.brunswick_disclaimer_failed", error=str(exc)[:160])
            return results

        # Step 2: the real site menu ("Please select the type of search you
        # want to perform") -- Combined Real Property/MAPS, Births, Deaths,
        # Marriages, Notary, Book/Page Direct (live-captured 2026-10-14).
        try:
            combined_link = page.locator("a", has_text="Combined Real Property / MAPS")
            await combined_link.first.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception as exc:
            log.warning("nc_rod_captcha.brunswick_menu_failed", error=str(exc)[:160])
            return results

        cutoff = datetime.now() - timedelta(days=_BRUNSWICK_LOOKBACK_DAYS)
        date_from = cutoff.strftime("%m/%d/%Y")
        date_to = datetime.now().strftime("%m/%d/%Y")

        for di, doc_type in enumerate(_BRUNSWICK_DOC_TYPES):
            try:
                await page.fill("#form_date_from", date_from)
                await page.fill("#form_date_to", date_to)
                # "Sort by Recording Date" -- live-confirmed 2026-10-14 this
                # makes the result set ASCENDING by filing date (page 1 =
                # oldest in the window), which is why this method jumps to
                # the LAST page below instead of reading forward from 1.
                await page.check("#form_sort")
                await page.select_option("select[name='form_doc_type']", doc_type)
                search_btn = page.locator("input[name='do_search2']").first
                await search_btn.click()
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception as exc:
                log.warning("nc_rod_captcha.brunswick_search_failed", doc_type=doc_type, error=str(exc)[:160])
                continue

            search_url = page.url
            try:
                html = await page.content()
            except Exception as exc:
                log.warning("nc_rod_captcha.brunswick_no_content", doc_type=doc_type, error=str(exc)[:160])
                continue
            m = _BRUNSWICK_PAGE_OF_RE.search(html)
            total_pages = int(m.group(1)) if m else 1
            log.info("nc_rod_captcha.brunswick_search_done", doc_type=doc_type, total_pages=total_pages)

            # Jump straight to the last (newest) page -- live-confirmed the
            # pagination row always links it directly, even truncated (e.g.
            # "1 ..... 14 15 16 ... 28" on a real 28-page result). Exact
            # text match (Playwright's :text-is()), not a substring --
            # "28" as `has_text` would also match any link whose text merely
            # CONTAINS "28" (e.g. a "128"-numbered page, or unrelated chrome
            # text elsewhere on the page).
            if total_pages > 1:
                try:
                    last_link = page.locator(f"a:text-is('{total_pages}')").first
                    await last_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception as exc:
                    log.warning("nc_rod_captcha.brunswick_lastpage_failed", doc_type=doc_type, error=str(exc)[:160])

            pages_fetched = 0
            while pages_fetched < _BRUNSWICK_MAX_PAGES:
                try:
                    html = await page.content()
                except Exception as exc:
                    log.warning("nc_rod_captcha.brunswick_page_content_failed", error=str(exc)[:160])
                    break
                page_results = self._brunswick_parse_page(html, page.url or search_url, doc_type)
                results.extend(page_results)
                pages_fetched += 1
                log.info("nc_rod_captcha.brunswick_page_parsed", doc_type=doc_type,
                         page_num=pages_fetched, found=len(page_results))
                if pages_fetched >= _BRUNSWICK_MAX_PAGES:
                    break
                prev_btn = await page.query_selector("#prev_page")
                if not prev_btn:
                    break
                try:
                    await prev_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception as exc:
                    log.warning("nc_rod_captcha.brunswick_prevpage_failed", error=str(exc)[:160])
                    break

            # Return to the blank search form before the next doc type --
            # live-confirmed "Return to search page" is present on every
            # results page (first page and last page both checked).
            if di < len(_BRUNSWICK_DOC_TYPES) - 1:
                try:
                    back_link = page.locator("a", has_text="Return to search page")
                    await back_link.first.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception as exc:
                    log.warning("nc_rod_captcha.brunswick_return_failed", error=str(exc)[:160])
                    break

        return results

    def _brunswick_parse_page(self, html: str, source_url: str, doc_type_filter: str) -> list[Listing]:
        """Parse one page of Brunswick's real Combined Real Property results.
        Each instrument is 4 DIRECT (non-nested) `<tr>` rows inside the
        results `<table>` -- live-confirmed 2026-10-14 by diffing
        `find_all("tr")` (recursive, pollutes the flat list with each
        Grantor/Grantee cell's OWN inner name-table rows) against
        `find_all("tr", recursive=False)` (clean, exactly 4 rows/record):
          1. "Filing Date: .../Book: .../Page: .../Status: ..."
          2. "Type: .../Desc: .../Subdivision: ..." (Desc/Subdivision blank
             when not applicable)
          3. "Grantor: NAME" (+ a "Download PDF" link, confirmed live to be
             a durable, cookie-less, signed-token URL -- see module
             docstring)
          4. "Grantee: NAME [NAME2 NAME3 ...]" (+ "View Image"/"View Detail"
             links; "View Detail" is ALSO durable, live-confirmed the same
             way, but not fetched here -- see module docstring on scope)
        A single instrument with multiple grantors gets one such 4-row
        group PER GRANTOR, all sharing the same Book/Page -- grouped back
        together by (book, page) below.
        """
        soup = BeautifulSoup(html, "html.parser")
        results_table = None
        for t in soup.find_all("table"):
            # <td> is a direct child of <tr>, not of <table> -- walk the
            # table's direct-child <tr>s first, then each one's direct
            # <td>s. Each "Filing Date:" label sits inside a <b> tag
            # alongside the actual date as plain sibling text (e.g.
            # "<td><b>Filing Date:</b> 07/16/2026</td>") -- more than one
            # child node, so BeautifulSoup's `.string` is always None here
            # and a `string=` predicate search never matches. get_text()
            # instead.
            found = False
            for tr in t.find_all("tr", recursive=False):
                for td in tr.find_all("td", recursive=False):
                    if td.get_text(" ", strip=True).startswith("Filing Date:"):
                        found = True
                        break
                if found:
                    break
            if found:
                results_table = t
                break
        if results_table is None:
            return []

        rows = results_table.find_all("tr", recursive=False)
        groups: dict[tuple[str, str], dict] = {}
        order: list[tuple[str, str]] = []
        i, n = 0, len(rows)
        while i < n:
            tds = rows[i].find_all("td", recursive=False)
            first = tds[0].get_text(" ", strip=True) if tds else ""
            if not first.startswith("Filing Date:"):
                i += 1
                continue

            filing_date = first.split(":", 1)[1].strip()
            book = page_num = status = ""
            for td in tds[1:]:
                t_text = td.get_text(" ", strip=True)
                if t_text.startswith("Book:"):
                    book = t_text.split(":", 1)[1].strip()
                elif t_text.startswith("Page:"):
                    page_num = t_text.split(":", 1)[1].strip()
                elif t_text.startswith("Status:"):
                    status = t_text.split(":", 1)[1].strip()
            i += 1
            if not book and not page_num:
                continue

            doc_type = desc = subdivision = ""
            if i < n:
                tds2 = rows[i].find_all("td", recursive=False)
                first2 = tds2[0].get_text(" ", strip=True) if tds2 else ""
                if first2.startswith("Type:"):
                    doc_type = first2.split(":", 1)[1].strip()
                    for td in tds2[1:]:
                        t_text = td.get_text(" ", strip=True)
                        if t_text.startswith("Desc:"):
                            desc = t_text.split(":", 1)[1].strip()
                        elif t_text.startswith("Subdivision:"):
                            subdivision = t_text.split(":", 1)[1].strip()
                    i += 1

            grantors: list[str] = []
            pdf_url = None
            if i < n:
                tds3 = rows[i].find_all("td", recursive=False)
                first3 = tds3[0].get_text(" ", strip=True) if tds3 else ""
                if first3.startswith("Grantor:"):
                    grantors = _brunswick_names_in_cell(tds3[0])
                    if len(tds3) > 1:
                        link = tds3[1].find("a", href=_BRUNSWICK_PDF_HREF_RE)
                        if link and link.get("href"):
                            pdf_url = urljoin(source_url, link.get("href"))
                    i += 1

            grantees: list[str] = []
            detail_url = None
            if i < n:
                tds4 = rows[i].find_all("td", recursive=False)
                first4 = tds4[0].get_text(" ", strip=True) if tds4 else ""
                if first4.startswith("Grantee:"):
                    grantees = _brunswick_names_in_cell(tds4[0])
                    if len(tds4) > 1:
                        link = tds4[1].find("a", href=_BRUNSWICK_DETAIL_HREF_RE)
                        if link and link.get("href"):
                            detail_url = urljoin(source_url, link.get("href"))
                    i += 1

            key = (book, page_num)
            if key not in groups:
                groups[key] = {
                    "filing_date": filing_date, "book": book, "page": page_num,
                    "status": status, "doc_type": doc_type, "desc": desc,
                    "subdivision": subdivision, "grantors": [], "grantees": [],
                    "pdf_url": None, "detail_url": None,
                }
                order.append(key)
            g = groups[key]
            for name in grantors:
                if name and name not in g["grantors"]:
                    g["grantors"].append(name)
            if not g["grantees"] and grantees:
                g["grantees"] = grantees
            if not g["pdf_url"] and pdf_url:
                g["pdf_url"] = pdf_url
            if not g["detail_url"] and detail_url:
                g["detail_url"] = detail_url

        listings: list[Listing] = []
        for key in order:
            li = self._brunswick_record_to_listing(groups[key], source_url, doc_type_filter)
            if li is not None:
                listings.append(li)
        return listings

    def _brunswick_record_to_listing(self, rec: dict, source_url: str, doc_type_filter: str) -> Listing | None:
        """Build one Listing per (book, page) group from `_brunswick_parse_page`.
        The homeowner being foreclosed on is named as a GRANTOR here (NOT the
        grantee, unlike this file's generic deed convention) -- live-confirmed
        on real SUBSTITUTE TRUSTEE / NOTICE OF FORECLOSURE rows, e.g. book 5596
        page 1287's grantors "VEGA, ESTEBAN EMILIO" / "MILLS, BRANDI" (real
        people, kept) / "ROCKET MORTGAGE, LLC" (the original lender, also
        indexed as a "grantor" in this chain -- filtered out). Grantees are the
        lender/trustee/servicer/MERS chain -- kept as `plaintiff`, with any
        "/TR"-suffixed name also surfaced as `trustee`."""
        book, page_num = rec.get("book") or "", rec.get("page") or ""
        if not book and not page_num:
            return None
        book_page = ", ".join(p for p in (f"B: {book}" if book else "", f"P: {page_num}" if page_num else "") if p)

        raw_grantors = rec.get("grantors") or []
        raw_grantees = rec.get("grantees") or []
        defendants = _brunswick_dedupe([g for g in raw_grantors if not _brunswick_is_institutional(g)])
        plaintiffs = _brunswick_dedupe(raw_grantees)
        trustees = _brunswick_dedupe([g for g in raw_grantees if g.rstrip().lower().endswith("/tr")])

        desc_parts = [p for p in (rec.get("desc") or None, rec.get("subdivision") or None) if p]
        legal_description = "; ".join(desc_parts) or None
        doc_type = rec.get("doc_type") or doc_type_filter
        filing_date = rec.get("filing_date") or "unknown date"

        raw: dict = {
            "county": "brunswick",
            "doc_type": doc_type,
            "filing_date": rec.get("filing_date") or "",
            "grantor": ", ".join(raw_grantors),
            "grantee": ", ".join(raw_grantees),
            "book_page": book_page,
            # ONE new block-name key covers everything Brunswick adds beyond
            # the shared county/doc_type/grantor/grantee/book_page names
            # this file already writes (and has registered) for Durham/the
            # generic _parse_html path -- see this session's final report
            # ("NEW RAW KEYS TO REGISTER"), same pattern as nc_rowan_cott.py's
            # "rowan_detail".
            "brunswick_detail": {
                "status": rec.get("status") or None,
                "subdivision": rec.get("subdivision") or None,
                # the original instrument this one references (e.g. the
                # Deed of Trust a Notice of Foreclosure/Substitute Trustee
                # filing concerns), straight from the site's own "Desc:"
                # field -- free ownership-chain context, same idea as
                # nc_rod_logan.py's raw["rod"]["xref"].
                "xref": rec.get("desc") or None,
                "detail_url": rec.get("detail_url"),
            },
        }

        li = Listing(
            source=self.slug,
            source_url=source_url,
            listing_type=ListingType.LIS_PENDENS,
            property_kind=PropertyKind.UNKNOWN,
            county="Brunswick",
            state="NC",
            case_number=book_page or None,
            defendant="; ".join(defendants) or None,
            plaintiff="; ".join(plaintiffs) or None,
            trustee="; ".join(trustees) or None,
            legal_description=legal_description,
            description=f"{doc_type} recorded {filing_date}",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw=raw,
        )

        pdf_url = rec.get("pdf_url")
        if pdf_url:
            try:
                from ...document_links import stamp_documents
                stamp_documents(li, [pdf_url])
            except Exception as exc:
                log.warning("nc_rod_captcha.brunswick_stamp_failed", error=str(exc)[:160])

        return li

    # -- Wake (Tyler "Self-Service", same platform family as Durham) --------

    async def _fetch_wake(self, page: Any, entry_url: str, search_path: str) -> list[Listing]:
        """Wake ROD: reCAPTCHA already cleared by a human before this method
        runs (see the Wake constants block above for the full live-verified
        writeup). Runs ONE search per real distress Document Type
        (_WAKE_DISTRESS_DOC_TYPES), not one combined query, so each page's own
        KNOWN doc type can be trusted for classification instead of each
        row's own parsed `doc_type` (which can read back a stale "SEE" on an
        administratively-corrected record -- see module docstring). Reuses
        `rod.nc_tyler.parse_selfservice()` for row parsing, same real markup
        as Durham, no third hand-rolled parser."""
        results: list[Listing] = []
        search_id = search_path.rsplit("/", 1)[-1]
        search_url = f"{entry_url}{search_path}"

        cutoff = datetime.now() - timedelta(days=_WAKE_LOOKBACK_DAYS)
        start_str = cutoff.strftime("%m/%d/%Y")
        end_str = datetime.now().strftime("%m/%d/%Y")

        from ...rod.nc_tyler import parse_selfservice

        for doc_type in _WAKE_DISTRESS_DOC_TYPES:
            try:
                # Fresh navigation to the search route: live-confirmed this
                # Self-Service search id is a STATEFUL server-side context
                # (it restores whatever the last search on it was, not a
                # blank form) -- "Clear Selections" resets it before this
                # iteration's own date range + doc type are set, so a doc
                # type chip from a PRIOR iteration of this same loop can
                # never leak into the next search. Best-effort: a missing/
                # failed Clear Selections control still lets the fields
                # below get explicitly (re)filled, same defensive shape as
                # the generic county path's own selector loops.
                await page.goto(search_url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                try:
                    clear_btn = page.locator("a, button", has_text="Clear Selections").first
                    await clear_btn.click(timeout=5000)
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

                start_input = await page.wait_for_selector(
                    "#field_RecordingDateID_DOT_StartDate", timeout=10000)
                end_input = await page.query_selector("#field_RecordingDateID_DOT_EndDate")
                await start_input.fill(start_str)
                await end_input.fill(end_str)

                # Document Types is a real tag/token field -- live-confirmed a
                # plain .fill()/.value assignment is silently ignored by the
                # actual search (the server-reported result set never
                # changed), and the typed text only becomes a real, searched
                # chip after an explicit Enter commits it (watched it turn
                # into a removable "x SUBSTITUTE TRUSTEE" chip live, and the
                # results summary line change to "...and Document types in
                # SUBSTITUTE TRUSTEE" only after that Enter).
                doc_type_input = await page.wait_for_selector(
                    "#field_selfservice_documentTypes", timeout=10000)
                await doc_type_input.click()
                await doc_type_input.type(doc_type)
                await doc_type_input.press("Enter")

                search_btn = await page.query_selector("#searchButton")
                if not search_btn:
                    log.warning("nc_rod_captcha.wake_no_search_button", doc_type=doc_type)
                    continue
                await search_btn.click()
                await page.wait_for_timeout(4000)
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as exc:
                log.warning("nc_rod_captcha.wake_search_failed", doc_type=doc_type, error=str(exc)[:160])
                continue

            try:
                html = await page.content()
            except Exception as exc:
                log.warning("nc_rod_captcha.wake_no_content", doc_type=doc_type, error=str(exc)[:160])
                continue
            m = _SS_PAGE_OF_RE.search(html)
            total_pages = int(m.group(1)) if m else 1
            log.info("nc_rod_captcha.wake_search_done", doc_type=doc_type, total_pages=total_pages)

            type_results: list[Listing] = []
            for pg_num in range(1, min(total_pages, _WAKE_MAX_PAGES) + 1):
                if pg_num > 1:
                    try:
                        await page.goto(f"{entry_url}/searchResults/{search_id}?page={pg_num}", timeout=20000)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        html = await page.content()
                    except Exception as exc:
                        log.warning("nc_rod_captcha.wake_page_failed", doc_type=doc_type,
                                    page_num=pg_num, error=str(exc)[:160])
                        break

                try:
                    records = parse_selfservice(html)
                except Exception as exc:
                    log.warning("nc_rod_captcha.wake_parse_failed", doc_type=doc_type,
                                page_num=pg_num, error=str(exc)[:160])
                    continue
                docids = _wake_extract_docids(html)
                for i, record in enumerate(records):
                    docid = docids[i] if i < len(docids) else None
                    li = self._wake_record_to_listing(record, search_url, doc_type, docid)
                    if li is not None:
                        type_results.append(li)

            log.info("nc_rod_captcha.wake_type_done", doc_type=doc_type, found=len(type_results))
            results.extend(type_results)

        # One-hop related-documents follow-through (see module docstring),
        # budget-capped to the newest leads built above -- one extra page
        # load per document, so this is bounded even though the full 2-type
        # 90-day pull itself (~256 live) is not.
        for li in results[:_WAKE_MAX_RELATED_FETCHES]:
            detail = (li.raw or {}).get("wake_detail") if isinstance(li.raw, dict) else None
            docid = detail.get("docid") if isinstance(detail, dict) else None
            if not docid:
                continue
            related = await self._fetch_wake_related(page, entry_url, search_id, docid)
            if related:
                detail["related_documents"] = related

        return results

    def _wake_record_to_listing(self, record: Any, source_url: str, doc_type_filter: str,
                                 docid: str | None) -> Listing | None:
        """Build one Listing from a parse_selfservice() IndexRecord pulled
        from a Wake search known to be scoped to `doc_type_filter`
        (SUBSTITUTE TRUSTEE or FORECLOSURE NOTICE). Classifies like
        nc_rod_logan.py's own pre-foreclosure codes -- both Wake types are
        the same real-world signal as Logan's S/TR + FCL -- LIS_PENDENS, pre_
        foreclosure. Always trusts `doc_type_filter` (the KNOWN type this
        search was scoped to) over the row's own parsed `record.doc_type` for
        classification -- a corrected record's `record.doc_type` can read
        back the stale struck-through value ("SEE") instead of the real one,
        see module docstring. The homeowner is named as a GRANTOR here, the
        same real pattern this scraper's own live pull confirmed on Wake
        (instrument 2026086748: grantors "VERNON VERNON J"/"VERNON TERRI L."
        plus the lender/trustee chain) and that Brunswick's own SUBSTITUTE
        TRUSTEE rows already established for this same codebase. Reuses
        `_brunswick_is_institutional`/`_brunswick_dedupe` rather than a third
        near-identical word list -- both already live in this same module
        (not a cross-file private import, unlike why Brunswick itself keeps
        its own copy instead of importing nc_rod_logan.py's)."""
        doc_number = (record.instrument_no or "").strip()
        if not doc_number:
            return None

        book_page = " ".join(
            p for p in (
                f"BT: {record.index_code}" if record.index_code else "",
                f"B: {record.book}" if record.book else "",
                f"P: {record.page}" if record.page else "",
            ) if p
        )

        grantors = record.grantors or []
        grantees = record.grantees or []
        defendants = _brunswick_dedupe([g for g in grantors if not _brunswick_is_institutional(g)])
        plaintiffs = _brunswick_dedupe(grantees)
        trustees = _brunswick_dedupe([g for g in grantees if g.rstrip().lower().endswith("/tr")])

        raw: dict = {
            "county": "wake",
            "doc_type": record.doc_type or "",
            "filing_date": record.recorded or "",
            "grantor": ", ".join(grantors),
            "grantee": ", ".join(grantees),
            "book_page": book_page,
            # ONE new block-name key covers everything Wake adds beyond the
            # shared county/doc_type/grantor/grantee/book_page names this
            # file already writes (and has registered) for Durham/Brunswick/
            # the generic _parse_html path -- see this session's final report
            # ("NEW RAW KEYS TO REGISTER"), same pattern as nc_rowan_cott.py's
            # "rowan_detail" / Brunswick's "brunswick_detail".
            "wake_detail": {
                "docid": docid,
                # the search's own KNOWN type -- authoritative for
                # classification above, see this method's own docstring.
                "searched_doc_type": doc_type_filter,
                # filled in by _fetch_wake after this Listing is built, if
                # the one-hop related-documents budget allows it; None here
                # means "not attempted" (budget/no docid), [] means
                # "attempted, found none" -- stays None until then.
                "related_documents": None,
            },
        }

        return Listing(
            source=self.slug,
            source_url=source_url,
            listing_type=ListingType.LIS_PENDENS,
            property_kind=PropertyKind.UNKNOWN,
            county="Wake",
            state="NC",
            case_number=doc_number,
            defendant="; ".join(defendants) or None,
            plaintiff="; ".join(plaintiffs) or None,
            trustee="; ".join(trustees) or None,
            legal_description=(record.description or None),
            description=f"{doc_type_filter} recorded {record.recorded or 'unknown date'}",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw=raw,
        )

    async def _fetch_wake_related(self, page: Any, entry_url: str, search_id: str,
                                   docid: str) -> list[dict]:
        """One hop: navigate to this document's own detail page and read the
        SAME Related Documents panel a human sees there -- live-confirmed it
        auto-populates via the page's own XHR
        (`GET /web/document/relatedDocuments/{docid}?queryId=...&search=...`)
        on load (see module docstring for the real live example). Returns []
        on any failure/timeout/no related documents -- never raises, so one
        bad document never aborts the rest of the budget-capped loop in
        `_fetch_wake`."""
        detail_url = f"{entry_url}/document/{docid}?search={search_id}"
        try:
            await page.goto(detail_url, timeout=20000)
            await page.wait_for_selector(".related-doc-list", timeout=8000)
        except Exception:
            return []
        try:
            html = await page.content()
        except Exception:
            return []
        return _wake_parse_related_documents(html, detail_url)

    async def _fetch_iredell(self, page: Any, entry_url: str) -> list[Listing]:
        """Iredell ROD: SAME Courthouse Computer Systems "DevExpress"
        platform as SC's Jasper county (rod/ccs_devexpress.py, built for
        Jasper first, generalized this pass for Iredell's own genuinely
        different column layout -- see that module's docstring's
        "IREDELL" section for the full live evidence). reCAPTCHA already
        cleared by a human before this method runs (see the `county ==
        "iredell"` branch in `fetch()` above for why this drives the SAME
        already-loaded `page` in place rather than navigating anywhere --
        Iredell's own clearance does NOT survive a fresh navigation/tab,
        live-confirmed 2026-10-14, unlike Wake's Tyler Self-Service
        cookie)."""
        out: list[Listing] = []
        try:
            docs = await ccs_devexpress.discover_recent_distress_via_browser(
                page, "NC", "Iredell",
                days_back=ccs_devexpress.IREDELL_LOOKBACK_DAYS,
                max_pages=ccs_devexpress.IREDELL_MAX_PAGES,
                max_docs=ccs_devexpress.IREDELL_MAX_DOCS,
                doc_codes=ccs_devexpress.IREDELL_DISTRESS_DOC_CODES,
            )
        except Exception as exc:
            log.warning("nc_rod_captcha.iredell_sweep_failed", error=str(exc)[:200])
            return out
        source_url = f"{entry_url}/Image/ImageIndex"
        for doc in docs:
            li = self._iredell_doc_to_listing(doc, source_url)
            if li is not None:
                out.append(li)
        return out

    def _iredell_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        """Build one Listing from a rod.ccs_devexpress.RodDoc parsed off
        Iredell's own real search grid. See rod/ccs_devexpress.py's module
        docstring's "IREDELL" section for the full live evidence (real doc
        examples per bucket, the doc-type dictionary, the image-URL
        params) this mapping is drawn from."""
        kind = ccs_devexpress.classify_kind_code(doc.doc_type)
        if kind is None:
            return None
        lt = _IREDELL_LISTING_TYPE.get(kind)
        if lt is None:
            return None
        defendant = _iredell_defendant(doc.grantor, doc.grantee)
        # Defensive, same as _iredell_defendant's own "both institutional"
        # branch -- also catches the one-party case (e.g. a BKCY row whose
        # ONLY party happens to itself read institutional, which
        # _iredell_defendant's "not e"/"not g" shortcuts don't separately
        # re-check) so an institutional name can never slip through as a
        # "defendant" lead.
        if not defendant or _brunswick_is_institutional(defendant):
            return None
        rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
        desc = (f"{doc.doc_type} recorded {rec}: {defendant}"
                f"{' (' + doc.notes + ')' if doc.notes else ''}")
        raw: dict[str, Any] = dict(doc.raw or {})
        raw["rod"] = {"doc_type": doc.doc_type, "grantor": doc.grantor, "grantee": doc.grantee,
                      "book": doc.book, "page": doc.page, "instrument": doc.instrument_no,
                      "recorded": rec}
        # The per-document image (/Image/ShowDocImage -- the SAME
        # controller action Jasper's own raw['jasper_doc_image'] block
        # already targets on the SC side of this vendor platform, live-
        # confirmed by actually opening one, see rod/ccs_devexpress.py
        # module docstring's "IREDELL" section for the real captured URL
        # this is built from) needs the SAME reCAPTCHA+session-cleared tab
        # as the search itself; a cold GET is expected to redirect back to
        # the gate, same documented gap as Jasper's own. The full legal
        # description text is NOT behind this gate -- already free in
        # doc.notes (the grid's own Description column) and lands in
        # legal_description below with no extra fetch.
        book, page = (doc.book or "").strip(), (doc.page or "").strip()
        if book and page and doc.instrument_no:
            date_q = doc.recorded_date.strftime("%m/%d/%Y") if doc.recorded_date else ""
            image_url = (f"{_IREDELL_BASE}/Image/ShowDocImage?DocNum={doc.instrument_no}"
                         f"&BookNum={book}&PageNum={page}&Kind={quote(doc.doc_type or '', safe='')}"
                         f"&Date={quote(date_q, safe='')}&Referrer=r&BookType=&SeqNum=0"
                         f"&TIF2PDF=true&SearchTabID=0&HideDetails=false")
            raw["iredell_doc_image"] = {
                "method": "GET", "url": image_url,
                "requires": "iredell_recaptcha_and_session_cleared_tab",
                "note": "cold GET is expected to redirect to the reCAPTCHA "
                        "gate (same session-gated /ProcessedImages/ pattern "
                        "as Jasper's own jasper_doc_image, see "
                        "rod.ccs_devexpress module docstring) -- only "
                        "fetchable from the SAME already-cleared tab. Not "
                        "stamped into raw['documents']/['document_url'] for "
                        "this reason, same convention as jasper_doc_image.",
            }
        return Listing(
            source=self.slug, source_url=source_url,
            listing_type=lt, property_kind=PropertyKind.UNKNOWN,
            state="NC", county="Iredell",
            parcel_id=doc.parcel_id,
            defendant=defendant,
            case_number=(doc.instrument_no or "").strip() or None,
            legal_description=(doc.notes or "").strip() or None,
            description=desc,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )

    # -- Craven/Greene/Harnett/Randolph/Stokes: SAME CCS DevExpress platform,
    # final batch, 2026-10-14 (see rod/ccs_devexpress.py module docstring's
    # "CRAVEN/GREENE/HARNETT/RANDOLPH/STOKES" section). Routed through ONE
    # shared, county-parameterized pair of methods instead of 5 near-
    # duplicate copies of _fetch_iredell/_iredell_doc_to_listing above --
    # the mapping/defendant-picking/image-URL logic those two already
    # encode is verbatim-identical for every county on this platform
    # (confirmed live per county, not assumed: see module docstring for
    # each county's own doc-type dictionary and sample rows). Iredell
    # itself is left on its own bespoke methods, already shipped and
    # already tested, rather than retrofitted onto this shared path.

    async def _fetch_ccs_devexpress_county(
        self, page: Any, entry_url: str, county_cap: str,
        days_back: int, max_pages: int, max_docs: int,
        doc_codes: tuple[str, ...],
    ) -> list[Listing]:
        """Generic CCS DevExpress NC-county fetch -- same shape as
        `_fetch_iredell` above, parameterized by county so the 5 counties
        in `_CCS_DEVEXPRESS_COUNTIES_NC` share one implementation. reCAPTCHA
        already cleared by a human before this runs (see the `county in
        _CCS_DEVEXPRESS_COUNTIES_NC` branch in `fetch()` above); drives THIS
        SAME already-loaded `page` in place, never navigating away, same
        operational reason as Iredell's own clearance not surviving a fresh
        tab (live-reverified on Craven this pass)."""
        out: list[Listing] = []
        try:
            docs = await ccs_devexpress.discover_recent_distress_via_browser(
                page, "NC", county_cap, days_back=days_back, max_pages=max_pages,
                max_docs=max_docs, doc_codes=doc_codes,
            )
        except Exception as exc:
            log.warning("nc_rod_captcha.ccs_sweep_failed", county=county_cap.lower(), error=str(exc)[:200])
            return out
        source_url = f"{entry_url}/Image/ImageIndex"
        for doc in docs:
            li = self._ccs_doc_to_listing(doc, county_cap, source_url)
            if li is not None:
                out.append(li)
        return out

    def _ccs_doc_to_listing(self, doc: Any, county_cap: str, source_url: str) -> Listing | None:
        """Generic version of `_iredell_doc_to_listing` above, parameterized
        by county name -- see that method's own docstring for the shared
        mapping/defendant-picking/image-URL-shape convention this reuses
        verbatim. Confirmed (not assumed) identical for Craven/Greene/
        Harnett/Randolph/Stokes this pass: each county's own real sample
        rows (see rod/ccs_devexpress.py module docstring) resolve through
        the SAME `_IREDELL_LISTING_TYPE` bucket table and the SAME
        `_iredell_defendant` institutional-party filter without any
        county-specific special-casing needed here."""
        kind = ccs_devexpress.classify_kind_code(doc.doc_type)
        if kind is None:
            return None
        lt = _IREDELL_LISTING_TYPE.get(kind)
        if lt is None:
            return None
        defendant = _iredell_defendant(doc.grantor, doc.grantee)
        if not defendant or _brunswick_is_institutional(defendant):
            return None
        rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
        desc = (f"{doc.doc_type} recorded {rec}: {defendant}"
                f"{' (' + doc.notes + ')' if doc.notes else ''}")
        raw: dict[str, Any] = dict(doc.raw or {})
        raw["rod"] = {"doc_type": doc.doc_type, "grantor": doc.grantor, "grantee": doc.grantee,
                      "book": doc.book, "page": doc.page, "instrument": doc.instrument_no,
                      "recorded": rec}
        # Per-document image -- the SAME /Image/ShowDocImage controller
        # action Jasper's/Iredell's own raw[...]_doc_image blocks already
        # target, live-confirmed by actually opening one PER COUNTY this
        # pass (see module docstring): needs the SAME reCAPTCHA+session-
        # cleared tab as the search itself, so stamped under its own
        # per-county raw key rather than raw['documents']/['document_url'],
        # same convention as jasper_doc_image/iredell_doc_image.
        book, page = (doc.book or "").strip(), (doc.page or "").strip()
        base = ccs_devexpress.base_url("NC", county_cap)
        if book and page and doc.instrument_no and base:
            county_lower = county_cap.lower()
            date_q = doc.recorded_date.strftime("%m/%d/%Y") if doc.recorded_date else ""
            image_url = (f"{base}/Image/ShowDocImage?DocNum={doc.instrument_no}"
                         f"&BookNum={book}&PageNum={page}&Kind={quote(doc.doc_type or '', safe='')}"
                         f"&Date={quote(date_q, safe='')}&Referrer=r&BookType=&SeqNum=0"
                         f"&TIF2PDF=true&SearchTabID=0&HideDetails=false")
            raw[f"{county_lower}_doc_image"] = {
                "method": "GET", "url": image_url,
                "requires": f"{county_lower}_recaptcha_and_session_cleared_tab",
                "note": "cold GET is expected to redirect to the reCAPTCHA "
                        "gate (same session-gated /ProcessedImages/ pattern "
                        "as Jasper's/Iredell's own doc_image keys, see "
                        "rod.ccs_devexpress module docstring) -- only "
                        "fetchable from the SAME already-cleared tab. Not "
                        "stamped into raw['documents']/['document_url'] for "
                        "this reason.",
            }
        return Listing(
            source=self.slug, source_url=source_url,
            listing_type=lt, property_kind=PropertyKind.UNKNOWN,
            state="NC", county=county_cap,
            parcel_id=doc.parcel_id,
            defendant=defendant,
            case_number=(doc.instrument_no or "").strip() or None,
            legal_description=(doc.notes or "").strip() or None,
            description=desc,
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )

    async def _fetch_craven(self, page: Any, entry_url: str) -> list[Listing]:
        cfg = _CCS_DEVEXPRESS_COUNTIES_NC["craven"]
        return await self._fetch_ccs_devexpress_county(page, entry_url, *cfg)

    def _craven_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        return self._ccs_doc_to_listing(doc, "Craven", source_url)

    async def _fetch_greene(self, page: Any, entry_url: str) -> list[Listing]:
        cfg = _CCS_DEVEXPRESS_COUNTIES_NC["greene"]
        return await self._fetch_ccs_devexpress_county(page, entry_url, *cfg)

    def _greene_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        return self._ccs_doc_to_listing(doc, "Greene", source_url)

    async def _fetch_harnett(self, page: Any, entry_url: str) -> list[Listing]:
        cfg = _CCS_DEVEXPRESS_COUNTIES_NC["harnett"]
        return await self._fetch_ccs_devexpress_county(page, entry_url, *cfg)

    def _harnett_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        return self._ccs_doc_to_listing(doc, "Harnett", source_url)

    async def _fetch_randolph(self, page: Any, entry_url: str) -> list[Listing]:
        cfg = _CCS_DEVEXPRESS_COUNTIES_NC["randolph"]
        return await self._fetch_ccs_devexpress_county(page, entry_url, *cfg)

    def _randolph_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        return self._ccs_doc_to_listing(doc, "Randolph", source_url)

    async def _fetch_stokes(self, page: Any, entry_url: str) -> list[Listing]:
        cfg = _CCS_DEVEXPRESS_COUNTIES_NC["stokes"]
        return await self._fetch_ccs_devexpress_county(page, entry_url, *cfg)

    def _stokes_doc_to_listing(self, doc: Any, source_url: str) -> Listing | None:
        return self._ccs_doc_to_listing(doc, "Stokes", source_url)

    def _parse_html(self, html: str, county: str, base_url: str) -> list[Listing]:
        """Parse deed search results from HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table.results tr, table.grid tr, .search-result, table tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            book_page = cells[0].get_text(strip=True)
            filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not book_page or book_page == "\xa0":
                continue

            results.append(Listing(
                source=self.slug,
                source_url=base_url,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                county=county.title(),
                state="NC",
                case_number=book_page,
                owner_name=grantee,
                plaintiff=grantor,
                raw={
                    "county": county,
                    "doc_type": doc_type,
                    "filing_date": filing_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": book_page,
                },
            ))

        return results
