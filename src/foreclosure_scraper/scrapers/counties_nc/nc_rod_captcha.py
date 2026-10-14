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
  duplicated. Row capture itself is page-1-only (Tyler's ~100-row default
  page size) of the 90-day window,
  newest-first -- NOT full pagination (a 90-day window runs into the
  thousands of rows; out of scope for this pass, flagged here same as every
  other partial-coverage note in this codebase rather than silently claimed
  complete).

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
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

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

_COUNTY_SITES = {
    "wake": {"url": "https://rodrecords.wake.gov/web", "gate": "recaptcha", "search_path": "/user/disclaimer"},
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

        # NOTE: page 1 only (Tyler's ~100-row default page size), newest-first,
        # of a 90-day window -- not full pagination. A 90-day window runs into
        # the thousands of rows on this platform; see module docstring.
        html = await page.content()
        from ...rod.nc_tyler import parse_selfservice
        try:
            records = parse_selfservice(html)
        except Exception as exc:
            log.warning("nc_rod_captcha.durham_parse_failed", error=str(exc)[:160])
            return results
        log.info("nc_rod_captcha.durham_rows", count=len(records))

        for record in records:
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
