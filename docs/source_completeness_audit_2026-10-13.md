# Source-completeness audit — 2026-10-13

Triggered by: the owner logging into Cherokee County SC's ROD system directly and finding a
real "View Image" button, a richer per-record Details page, and a "Description" cross-reference
field that `cherokee_rod.py` never captured — none of it visible from the code alone. The
question: is this happening everywhere, not just Cherokee?

**Method.** Wave 1 (this document): every one of the 281 scraper files read in full by 14
parallel passes, checking whether the code captures everything the site plausibly offers (a
per-record detail page, document/image links, a description/notes field) or silently leaves
real, already-identified data unfetched. This is a **code-level audit** — it cannot catch a
gap with zero trace in the code (Cherokee's own gap had none; it was found by clicking around
the live site, not by reading the scraper). Wave 1 catches self-admitted gaps (a built-but-
unfetched detail URL, a docstring that says "not fetched this pass") and structurally obvious
ones. It systematically under-counts silent omissions. Treat "CLEAN" from Wave 1 as "nothing
obviously missing in the code," not "confirmed complete."

**Result: ~60 of 281 files flagged.** This is not an isolated Cherokee problem — it is a
recurring pattern across nearly every category of source in this codebase.

---

## Cross-cutting patterns (fix once, apply to many files)

### Pattern A — ArcGIS FeatureServer scrapers never check for attachments
`hasAttachments`/`queryAttachments` is a separate ArcGIS capability from the attribute table
(`outFields`) — invisible to anyone who only reads a layer's field schema, which is why
extensive field-diff audits on several of these files never caught it. **A working reference
implementation already exists in this codebase**: `counties_nc/asheville_helene.py`,
`counties_generic/state_contamination.py`, `counties_nc/buncombe_elderly.py` all already pull
real attachment photos this way — copy their pattern.

Affected: `city_websites/charlotte_open_data.py`, `counties_nc/wake_code_cases.py`,
`counties_nc/kinston_proposed_demolition.py`, `counties_nc/gastonia_code_enforcement.py`,
`counties_nc/henderson_code_violations.py`, `counties_nc/lincoln_code_violations.py`,
`counties_nc/hendersonville_vacant_structures.py`, `counties_nc/rocky_mount_blight_survey.py`,
`counties_generic/arcgis_distress_layers.py` (~25 layers), `counties_sc/oconee_flc_assignment.py`,
`counties_sc/oconee_forfeited_land.py`, `counties_sc/pickens_delinquent_parcels.py`.

### Pattern B — National real-estate-listing scrapers keep one photo when the API has many
Same shape across 8 files: a detail URL is built and stored as `source_url` but never fetched;
only the first/a single photo is kept when the source clearly has a gallery. Working reference
implementations already exist in the same codebase: `freddie_homesteps.py`, `govdeals.py`,
`hud_homestore.py` already do this correctly.

Affected: `national/crexi_multifamily.py`, `national/estate_sales.py`,
`national/fannie_homepath.py`, `national/homepath_json.py`, `national/foreclosure_dot_com.py`,
`national/hibid_real_estate.py`, `national/hubzu.py`, `national/craigslist_fsbo.py` (lower
severity), `national/loopnet.py`, `national/landandfarm.py` + `national/landwatch.py` (partial
— fetch the detail page but skip non-"RealEstateListing" JSON-LD blocks that likely carry the
photo gallery).

### Pattern C — Register-of-Deeds family scrapers: search captured, detail/image page never touched
The exact Cherokee shape, repeated across nearly every ROD vendor this codebase reads.

Affected: `counties_nc/nc_rod_captcha.py` (9 counties, 2 vendor platforms),
`counties_nc/nc_rowan_cott.py`, `counties_nc/nc_cchs_deeds.py`,
~~`counties_sc/sc_rod_acclaim.py`~~ (same AcclaimWeb vendor as Cherokee itself — **FIXED
2026-10-14**, see correction note under "Needs YOU logged in" below: no login was ever needed,
and the per-document scanned PDF is now wired into `raw['document_url']`/`raw['documents']`),
~~`counties_sc/sc_rod_walled.py`~~ (Beaufort + Clarendon — **FIXED 2026-10-14**, see correction
note under "Needs YOU logged in" below: Beaufort needed no login either (its old generic
Playwright table-scraper just never matched its ag-Grid SPA); Clarendon's own AcclaimWeb
deployment WAS live-checked this time (the prior flag above was right not to assume it) and the
Pickens finding does transfer — no login, just Cloudflare, cleared with this codebase's existing
nodriver tier. Jasper (third county in this file) is a genuinely different case: Cloudflare PLUS
an independent Google reCAPTCHA v2 gate on the search feature itself — left queued below, not
fixed), `national/cash_buyer_deeds.py`.
One was worse than "never looked at" — **a real in-repo contradiction**, now **SETTLED AND FIXED
2026-10-14** (see correction note under "Needs YOU logged in" below):
~~`counties_sc/sc_rod_cott.py`'s own docstring claims Union's document images are "pay-per-view,"
but the shared `rod/doc_images.py` module explicitly registers Union as confirmed **free**
(`COUNTY_IMAGE_STATUS[("SC","Union")] = ("free", ...)`) — and the function meant to fetch them,
`owner_dot_documents()`, has no code branch for `vendor == "cott"` at all, so it silently
returns `[]` even where the infrastructure already knows the image is free and reachable.~~

### Pattern D — "List vs. detail" self-admitted gaps (the code already knows)
Highest-confidence flags: the author already identified the gap in a comment and left it.

- `counties_nc/polk_tax.py` — most explicit in the whole audit: detail URL stored, comment says
  "not fetched per-row this pass... enough for a later enrichment pass."
- `counties_nc/nc_rod_logan.py` — free image exists per-row, deliberately kept as provenance
  only pending a session-aware fetch pattern that was never built.
- `counties_sc/anderson_acpass_deeds.py` — "View Images" link captured as a reference only.
- `counties_sc/dorchester_billtrax_delinquent_tax.py` — real per-bill PDF, httpx can't resolve
  it, deferred to "a future browser-based enrichment pass" never built.
- `counties_sc/horry_probate.py` — decedent address + representative sit on a per-case detail
  page explicitly described and explicitly skipped ("would cost one request per case").
- `law_firms/zacchaeus.py` — "Notice of Sale" is now a Blazor button with no href; opening it
  needs per-row interaction, explicitly scoped out.
- `national/auction_dot_com.py` — "AUDITED, NOT FIXED": real per-property PURCHASE_AGREEMENT
  and LOCAL_DISCLOSURE PDFs on the detail page, ~100+ pages/run, flagged and left.
- `national/sc_sos_entity.py` and `national/legacy_obituaries.py`'s detail_url — already covered
  elsewhere this session (sc_sos_entity has a build spec already relayed to Hermes).
- `counties_nc/nc_ecourts_lis_pendens.py`, `nc_ecourts_estates.py`, `nc_ecourts_divorce.py` —
  all three build a case-detail/`caseLink` URL and never fetch it; two have a dormant
  browser-automation path that would, but it isn't running.
- `counties_nc/henderson_tax.py` — captures a real eCourts case-detail link, explicitly
  deferred as "its own from-scratch API/JS investigation."
- `counties_nc/gastonia_code_enforcement.py` — the free-text `Description` field was pulled
  *manually* during validation to disambiguate case severity, but never wired into production.
- `national/sheriff_sales.py` — **docstring actively misstates the code**: claims PDFs are
  "noted in raw but not OCR'd"; the code actually skips and discards them with zero trace
  anywhere.
- 4 TownNews-RSS newspaper scrapers (`newspapers/index_journal.py`, `journal_scene.py`,
  `post_and_courier.py`, `mecklenburg_times.py`) all store the article `<link>` and never fetch
  it, relying on a ~250–550-char RSS snippet instead of the full notice — while a sibling file
  in the *same batch* (`daily_courier.py`) proves the full text is fetchable on an adjacent
  TownNews path.
- **Another real in-repo contradiction**: `public_notices/nc_notices_counties.py` asserts (dated
  2026-07-31) that `Details.aspx` is universally reCAPTCHA-gated and must never be fetched — but
  its own sibling `public_notices/ncpublicnotices.py`, reading the *same site*, has working code
  (`_fetch_probate_detail`) that successfully clicks past the interstitial when no real CAPTCHA
  appears. One module in the package asserts a wall the other already disproves. Worse,
  `ncpublicnotices.py` itself only runs that working fetch for `category == "probate"`, never
  for foreclosure/divorce rows, and silently drops any foreclosure notice whose address falls
  past the snippet truncation instead of using the detail fetch it already has working.

### Pattern E — Stub/placeholder data masquerading as real search (not a detail-page gap — worse)
`national/nc_unclaimed.py` still queries 10 hardcoded generic surnames ("Smith", "Johnson", ...)
instead of the board's real owner names — the exact bug already found and fixed in its sibling
`national/people_search.py` on 2026-10-12 ("REAL NAMES, NOT A STUB"), never applied here. Every
run has been checking the same 10 names regardless of which leads are actually on the board.

### Pattern F — richer fields parsed into memory, never written out
- `counties_sc/greenville_probate.py` — **already fixed this session** (commit `12357235`):
  Date of Birth/Sex/creditor-claims-expiration were parsed and then dropped before reaching
  `raw`.
- `counties_nc/rutherford_wildfire_tax.py` — `_slim()` explicitly discards `LineItems` (fee/tax
  breakdown) and payment history (a real partial-payment distress signal) that are already
  present in the same fetched API response.
- `counties_nc/nc_avalon_tax.py` — the Wildfire API's nested `Values{}`/`Payment{}`/`IDs{}`
  objects are read for one key each; sibling keys are fetched but never preserved.

---

## Needs YOU logged in (walled; same workflow as Cherokee)

These require a real login/CAPTCHA session — same boundary as always, Claude won't do this
part. Queued for the same workflow used on Cherokee: you log in, Claude confirms what's real
via the browser pane.

**CORRECTION 2026-10-14** — `counties_sc/sc_rod_acclaim.py` (Pickens/Harris AcclaimWeb) was
WRONGLY listed here. The owner logged into Pickens' AcclaimWeb live, in the browser pane, and
found there is no account on this deployment at all — not for the base search (already known
free) and not for the per-document "Document Details" popup/image viewer either (confirmed via
the site's own `Search/Settings` page, which is a bare preference toggle, not an account). The
popup's real scanned PDF is served by `Image/DocumentPdfAllPages/{TransactionItemId}`, and
`TransactionItemId` turned out to already be sitting in every row of the `Search/GridResults`
JSON response `discover_recent_nods` was already fetching — no browser, no extra request, no
session priming needed. Live-verified cold (fresh client, zero prior requests) against 15 fresh
documents spanning every distress doc type this scraper classifies. Fixed in
`rod/acclaim.py` (`document_pdf_url`) + `scrapers/counties_sc/sc_rod_acclaim.py` (stamps the URL
into `raw['document_url']`/`raw['documents']` via `document_links.stamp_documents`); see
`tests/test_acclaim_rod.py`. **Removed from this list** — it needs no login and nothing further
is queued here for it.

**CORRECTION 2026-10-14 (cont.)** — `counties_sc/sc_rod_walled.py` was also WRONGLY listed here
for Beaufort AND Clarendon (Jasper is a genuinely different, still-walled case — see its own
bullet below). Live-checked, not assumed:
  * **Beaufort** — no WAF, and its own `api/search/clientinfo` confirms `authentication":"0"`,
    `useRecaptchaV3":null`, `encryptData":"0"` — no login, no CAPTCHA, no field encryption. The
    real gap was the old generic Playwright table-scraper never matching Beaufort's ag-Grid
    Angular SPA; fixed by calling the vendor's own free JSON API directly
    (`rod/beaufort_dmp.py`) — no browser needed at all now.
  * **Clarendon** — the login-free AcclaimWeb finding above DOES transfer (same vendor, same free
    `Image/DocumentPdfAllPages/{TransactionItemId}` PDF, live-verified against 4 real distress
    documents + 2 controls): the only wall is Cloudflare at the edge, and this codebase's
    existing nodriver tier (`wall_bypass.py`/`browser_utils.py`) already clears it. Fixed in
    `rod/acclaim.py` (`discover_recent_nods_via_browser`, the same search/PDF logic as Pickens
    issued as in-page `fetch()` calls from a Cloudflare-cleared tab) +
    `scrapers/counties_sc/sc_rod_walled.py`. Unlike Pickens, the PDF endpoint ITSELF stays behind
    Cloudflare (a cold GET 403s), so it is recorded under `raw['clarendon_pdf_fetch']` rather than
    stamped into `raw['document_url']`/`raw['documents']`, which the generic GET-only
    `enrich_doc_ocr.py` pass would 403 against. See `tests/test_sc_rod_walled.py`.
  * **Removed from this list for Beaufort and Clarendon** — neither needs a login. Jasper stays
    queued (see its own bullet below): it is a different vendor (Courthouse Computer Systems)
    behind a different, genuinely-unautomated wall.

- `counties_sc/sc_rod_walled.py` — **Jasper only now** (Beaufort/Clarendon fixed above). Cloudflare
  at the edge is clearable the same way as Clarendon, but the Land Records search tab itself is
  ALSO gated by a real Google reCAPTCHA v2 ("Please complete the CAPTCHA to enter this site",
  sitekey `6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb") — confirmed live 2026-10-14 with nodriver
  already past the Cloudflare challenge. Genuinely walled; not automated.
**CORRECTION 2026-10-14 (cont.)** — `counties_sc/sc_rod_cott.py` (Union) was also WRONGLY listed
here, on the strength of its own docstring's unverified "pay-per-view" claim, which contradicted
the shared `rod/doc_images.py` module's own `COUNTY_IMAGE_STATUS[("SC","Union")] = ("free", ...)`
registration. Live-checked, not assumed — the Pickens/Beaufort/Clarendon pattern (a login-walled
UI route sits beside a different, genuinely free one) does transfer, though to a THIRD distinct
shape again: the free route needs a correct `Referer` header on TWO requests, not one.
Live-verified against 3 real Union documents spanning every category this adapter classifies (a
DEATH CERTIFICATE/probate recording, a $540,000 DEED, and a $42,000 MTG/deed-of-trust): the UI's
own "View Document" route (`Imaging/Document/KeyFromImage?IndexId=`) DOES 302 to
`Portal/Account/LoginRoute` on a cold request — the one fact that made "pay-per-view" plausible —
but the Details page's own viewer resolves the real scanned PNG through a different, genuinely
free, no-login, no-payment, no-browser two-step (`Imaging/Document/Thumbnails` -> the page's own
embedded `Imaging/Document/Image` URL), each request carrying a `Referer: .../Guest/Search/
Records/Details?IndexId=<the same IndexId>`. A Referer naming a different/nonexistent IndexId
fails the same way on both requests, so this is a real, mandatory anti-hotlinking gate, not an
account wall. Fixed in `rod/cott_recordroom.py` (`image_fetch_recipe`/`document_image_url`/
`fetch_document_image`, plus `IndexId`/`HasFiledImage`/`ScanPages` now captured on every swept
row) + `rod/doc_images.py` (`owner_dot_documents`'s missing `vendor == "cott"` branch, via new
`_cott_owner_dots`, reusing `rod/sc_recordroom.py`'s existing by-name search) +
`scrapers/counties_sc/sc_rod_cott.py` (`_to_listing` stamps the fetch recipe into
`raw['cott_image_fetch']` — a dedicated key, not `document_links.stamp_documents`'s
`raw['document_url']`/`raw['documents']`, since resolving it needs that Referer-bearing
Thumbnails request first, which the generic GET-only `enrich_doc_ocr.py` pass can't do — same
reasoning as `raw['beaufort_pdf_fetch']`/`raw['clarendon_pdf_fetch']` above). See
`tests/test_cott_recordroom.py` + `tests/test_rod_doc_images.py`. **Removed from this list** — it
needs no login and nothing further is queued here for it.

**CORRECTION 2026-10-14 (cont.)** — `counties_nc/nc_rod_captcha.py` was also partially WRONG
here, on Durham only (the other 8 counties below were re-verified live and are confirmed
correct). The 2026-10-12 rewrite guessed Durham's gate was "very likely the same reCAPTCHA [as
Wake]" by platform match, never individually checked — and this was already wrong the day it
was written, since a DIFFERENT module in this same codebase (`rod/nc_tyler.py`, a name-search ROD
enricher for existing leads, written 2026-10-07) already recorded in its own docstring that
"Durham's disclaimer page loads Google's reCAPTCHA script but showed no challenge." A real
in-repo contradiction, same class as the Union "pay-per-view" one above, just never
cross-checked. Live-verified 2026-10-14 (a Playwright DOM query for an actual
`iframe[src*=recaptcha]`, not a string-grep — the literal string "g-recaptcha" genuinely IS
present in Durham's shared JS bundle, which is exactly what made the wrong guess plausible):
zero CAPTCHA, just the "I Accept" disclaimer button every Tyler Self-Service tenant has.
`/web/search/DOCSEARCH5S1` is then directly reachable and returns real results with zero gate —
a 14-day pull live-tagged 1,243 real documents (5 FORECLOSURE, 264 DEED OF TRUST) on 2026-10-14.
Fixed in `scrapers/counties_nc/nc_rod_captcha.py` (`_fetch_durham`, reusing `rod/nc_tyler.py`'s
already-tested `parse_selfservice` row parser rather than duplicating it, via new
`_durham_record_to_listing`); see `tests/test_nc_rod_captcha.py`. Per-document image capture was
explicitly NOT added despite being viewable free inside an authenticated session: a cold request
against that same PDF route 302s to the disclaimer page with a fresh `JSESSIONID` cookie, and the
generic `enrich_doc_ocr.py` pass fetches every `document_url` with a stateless client carrying no
session — stamping it would silently ship a dead link, so it is flagged as a documented gap
instead rather than a working capability it isn't (a genuine server-side session gate, unlike the
header-only Referer gates `raw['beaufort_pdf_fetch']`/`raw['clarendon_pdf_fetch']`/
`raw['cott_image_fetch']` above worked around). That 14-day/1,243-document pull was itself still
page-1-only, not full pagination — **fixed 2026-10-14 (cont. x4), see the Wake section below**
(Durham and Wake share the same `rod/nc_tyler.py` parser, so the pagination fix, the shared
multi-tract header fix, and the confirmed-not-fixable Grantor/Grantee 5-name cap all apply to
Durham too, not just Wake).

The other 8 counties in this file were re-verified live 2026-10-14, not carried over from the
2026-10-12 docstring unchecked, and all 8 reconfirmed genuinely walled: Wake, Iredell, Craven,
Greene, Harnett, Randolph, Stokes all show a real Google reCAPTCHA widget live (confirmed by DOM
query, not grep); Brunswick's math gate is also still live, though it turned out to be a
DIFFERENT and worse problem than expected — the question is rendered as a CAPTCHA image
(`getpng.php?a=N&b=M`), not readable text, so this codebase's own `math_captcha.py` cannot solve
it at all: it silently pattern-matches the Register of Deeds office's own phone number in the
page footer instead, reports `solved=True`, and submits a wrong answer that never actually clears
the gate (confirmed by diffing the page before/after the submit) — a real false-positive bug in
`math_captcha.py` worth flagging for whoever next touches that module, even though it does not
change Brunswick's walled status here.

**CORRECTION 2026-10-14 (cont.)** — `math_captcha.py`'s false positive flagged just above is now
FIXED, and Brunswick turned out to be partially resolvable, not just correctly-reported-walled.
`solve_math_captcha()` no longer regexes the whole page body: it scopes question-text extraction
to the `<fieldset>`/`<form>` immediately around the answer input (keeping the office's footer
phone number, several DOM levels away in a sibling section of the same page-spanning outer
`<form>`, out of the match entirely), strips any phone-number-shaped substring as a second
independent guard, and — the part that actually unlocks Brunswick — detects an image-only
question and OCRs it via this codebase's existing free-tier-first Gemini vision plumbing
(`enrichment_vision._parse_gemini_keys`/`_parse_json_response`, reused rather than duplicated).
Brunswick's question turned out to be FOUR separate word-images (confirmed live by fetching and
visually reading the actual PNGs: one page read "Five"/"Plus"/"Nine"/"Equals" = 14, another
"Seven"/"Minus"/"Zero"/"Equals" = 7 — the `a`/`b` query params in `getpng.php?a=N&b=M` are NOT the
literal operands, just opaque render params). Live-verified end-to-end 2026-10-14, 4 of 4
attempts: fetched the live page, OCR'd the real question image(s), POSTed the computed answer
with the session it was issued under, and got back a genuinely different page each time — no
browser was used for this specific check (httpx replaying the real session/cookies, to avoid
running Chromium locally during an active Mac memory/swap crisis; the Playwright code path itself
is covered by `tests/test_math_captcha.py`'s `_FakePage`, which mirrors the exact Page API
`solve_math_captcha()` calls). Critically, when OCR is unavailable or wrong, this does NOT become
a new false positive: a deliberately-weaker model substituted for comparison
(`gemini-2.5-flash-lite`) misread one image on 1 of 3 repeated trials against a saved image set,
and the new post-submit `_gate_still_present` check (comparing the page before/after submit — the
exact comparison the old code skipped) correctly caught it and still reported `False`.

Clearing the CAPTCHA is not the whole gate, though. Following one layer further live: the page
right after a correct CAPTCHA submit is a SECOND gate, a disclaimer accept/decline link
(structurally the same pattern as Durham's `#submitDisclaimerAccept` above, just an anchor link
instead of a button). Following it lands on Brunswick's real site menu ("Please select the type
of search you want to perform" — Combined Real Property/MAPS, Births, Deaths, Marriages, Notary,
Book/Page Direct), confirming the full chain genuinely reaches real UI, not another dead end —
but that was reconnaissance only. Brunswick still needs (1) the disclaimer-accept step added to
`nc_rod_captcha.py`'s `gate == "math"` branch, (2) the "Combined Real Property/MAPS" search
clicked into and its date-range/result markup captured (unverified shape), and (3) whatever
parser that markup needs — none of that is done here. Fixed in `math_captcha.py`
(`_analyze_captcha_html`, `_solve_question_text`, `_solve_image_question`,
`_gate_still_present`); see `tests/test_math_captcha.py` (22 tests: the phone-number
false-positive case, legitimate text-based questions still working, and the OCR path with a
mocked Gemini call built on the real live word-image evidence above) and
`scrapers/counties_nc/nc_rod_captcha.py`'s own updated module docstring for the full writeup.

**CORRECTION 2026-10-14 (cont. x2)** — Brunswick's remaining queued work (the disclaimer-accept
step and a search/result parser, flagged just below as not yet built) is now done and live-wired,
not just the CAPTCHA layer. `_fetch_brunswick` (new in `nc_rod_captcha.py`) clicks the real
disclaimer-accept link (disambiguated from the "I do NOT agree" link listed first in the DOM — an
earlier version of this same verification hit that exact bug and landed on a "You have Logged Off
this system" page), clicks into "Combined Real Property / MAPS", and searches+paginates two
distress-relevant Document Types the real dropdown offers: "SUBSTITUTE TRUSTEE" (271 records in a
90-day window) and "NOTICE OF FORECLOSURE" (82) — there is no "TRUSTEE DEED"/"FORECLOSURE DEED"
option on this platform; the eventual sale deed records as a plain "DEED", indistinguishable here
from any other sale, a real flagged gap, not silently claimed covered. Live-verified end-to-end
2026-10-14 via httpx replaying the real site (same memory-pressure reasoning as the CAPTCHA
verification — no Chromium run locally; the Playwright glue code mirrors this proven flow but was
not itself executed live this session): a brand-new, cookie-less httpx client with zero prior
requests fetched a real 2-page `BRUNSWICK-property-B5631-P1335.pdf` and a real Document Details
page from the signed `s=` tokens alone — this entire site never sets a cookie anywhere in the
chain, so these "Download PDF"/"View Detail" links are durable, stateless URLs, unlike Durham's
cookie-gated PDF route or Rowan/Logan's session-scoped image keys, and are safely stamped via
`document_links.stamp_documents`. A real live example (book 5596 page 1287, a SUBSTITUTE TRUSTEE
instrument): 4 grantor index rows for ONE instrument — "VEGA, ESTEBAN EMILIO" and "MILLS, BRANDI"
(real co-owners, kept) plus "ROCKET MORTGAGE, LLC" / "ROCKET MTG, LLC" (the original lender, also
indexed as a "grantor" in this chain — filtered out by an institutional-name check). With "Sort by
Recording Date" checked this platform sorts ASCENDING (page 1 = oldest, 07/22/2026 in a
07/16–10/14 window; the LAST page = newest, 10/13/2026), so `_fetch_brunswick` jumps straight to
the always-directly-linked last page and walks backward a budget-capped number of pages — newest
leads first, still partial coverage of the full window (documented, not claimed complete). See
`nc_rod_captcha.py`'s own module docstring and `tests/test_nc_rod_captcha.py` (6 new tests, real
schema-accurate fixtures built from this live pull) for the full writeup.

**CORRECTION 2026-10-14 (cont. x3)** — Wake's own reCAPTCHA checkbox was confirmed genuinely real
(the owner personally solved it live) — same hard boundary this file has drawn at every other real
CAPTCHA (never automated). Everything downstream of that human-cleared session is now wired, not
just confirmed-walled: same Tyler "Self-Service" platform as Durham (identical
`li.ss-search-row`/`ul.selfServiceSearchResultColumn` markup and identical
`#field_RecordingDateID_DOT_StartDate`/`#searchButton` field ids, live-confirmed by reading the
real DOM, not inferred by platform match the way the 2026-10-12 entry got Durham wrong) — so
`_fetch_wake` reuses `rod/nc_tyler.py`'s already-tested `parse_selfservice()` row parser verbatim,
same as Durham, not a third hand-rolled one. `_COUNTY_SITES["wake"]["search_path"]` was also wrong
before this pass (pointed at `/user/disclaimer`, the gate page itself, not a search route) —
corrected to the real `/search/DOCSEARCH341S2`.

Unlike Durham's unfiltered page-1 pull, Wake's own `#field_selfservice_documentTypes` field lets
the search be scoped up front to Wake's real distress Document Types — live-captured facet counts
(14-day window) show these are literally spelled "SUBSTITUTE TRUSTEE" (43) and "FORECLOSURE
NOTICE" (7), the same real-world pre-foreclosure signal as `nc_rod_logan.py`'s own S/TR + FCL
codes; everything else seen live (DEED 985, DEED OF TRUST 1045, SATISFACTION 1087, ASSIGNMENT 309,
etc.) is a routine filing, not distress, same judgment call Logan's own classifier already makes.
A live two-type 90-day search (Jul 16–Oct 14 2026) returned 256 real total results across 11 pages
— small enough to walk in full, unlike Brunswick's much larger per-type volume. Getting the search
to actually filter surfaced a real platform gotcha: the Document Types field is a true tag/token
input — live-confirmed a plain `.fill()`/property-setter value assignment is silently ignored by
the server-side search (the result set never changed); only an actual typed keystroke sequence
followed by Enter commits it into a real, searched chip. `_wake_record_to_listing` classifies both
types as `LIS_PENDENS` (pre-foreclosure) and reuses `_brunswick_is_institutional`/
`_brunswick_dedupe` (same file, not a cross-module import) to separate the real owner(s) — named as
GRANTOR on these record types, same pattern Brunswick's own SUBSTITUTE TRUSTEE rows already
established — from the lender/trustee chain. Real live example: instrument 2026086748, grantors
"VERNON VERNON J"/"VERNON TERRI L." (kept) plus NEWREZ/NEW PENN FINANCIAL/SHELLPOINT (filtered).

Two further real, live-confirmed, explicitly flagged (not silently papered-over) gaps surfaced
along the way: (1) Wake's own search-result row caps each Grantor/Grantee column at 5 VISIBLE
names even when the column header's own count says more exist (live: "Grantor/Party 1 (7)" with
only 5 `<li>` names actually in the DOM) — the rest only exist on that document's own detail page,
not fetched here; (2) a multi-tract instrument's header (two "B: x P: y" pairs, no bullet between
them) fails `rod/nc_tyler.py`'s shared `_SS_HEAD` regex entirely — live-confirmed by running the
exact captured text through it — so `instrument_no`/`book`/`page`/`recorded` all come back `None`
on that row and the record is silently dropped today, on BOTH Wake and Durham (same shared parser).
**Both gaps re-examined and resolved one way or the other 2026-10-14 (cont. x4) below — (2) is now
fixed; (1) is confirmed genuinely not fixable at the search-results level.**

Related Documents are wired in, one hop, as asked: each document's own detail page
(`/web/document/{docid}?search={search_id}`) auto-fires a real XHR
(`GET /web/document/relatedDocuments/{docid}?queryId=...&search=...`) that live-confirmed returns
real related-instrument rows — live example, instrument 2026111052 ("NOTICE OF CORRECTION"): 1
related DEED from 09/06/1960, book/page "001422-00299", its own grantor/grantee names — genuinely
the original instrument a correction/trustee filing concerns. `_fetch_wake_related` reads that
same panel (budget-capped to the newest leads, `_WAKE_MAX_RELATED_FETCHES`, same spirit as
`nc_rowan_cott.py`'s `_MAX_DETAIL_FETCHES`) and stores it as structured data under
`raw["wake_detail"]["related_documents"]` — index metadata, not a document image, so never passed
to `document_links.stamp_documents`. Per-document PDF images themselves
(`/web/document-image-pdf/...`) are live-confirmed to need that same live session (a cookie-less
`curl` against a real URL pulled from this exact session got a `302` to `/web/user/disclaimer`) —
identical gap to Durham's own cookie-gated PDF route, and deliberately NOT stamped for the same
reason (`enrichment_doc_ocr.py` fetches stamped URLs statelessly, with no cookie jar).

**Session-reuse window (the operational question this pass was specifically asked to answer):**
the reCAPTCHA clearing itself stays, and will keep staying, a manual/operator step — this codebase
does not and will not try to automate solving it. But the human-cleared session behind it is not a
one-shot token: the live Tyler Self-Service client itself ships a `GET /web/session/pingSession`
heartbeat, observed firing roughly every 10–20s while a tab sits open, specifically to keep the
server-side session alive — strong architectural evidence of a real, finite, activity-extendable
idle timeout, not a single-use artifact that dies the instant the clearing browser closes. Tested
live by disabling that heartbeat (monkey-patching `fetch`/`jQuery.ajax` in the authenticated tab to
block `pingSession`/`getSubscriptionTime` calls) and then making a real, deliberate authenticated
request after a measured idle gap with zero activity in between: see `nc_rod_captcha.py`'s own
module docstring for the exact elapsed time measured and what it returned. This is a DIFFERENT,
more capable shape than `docs/HERMES.md` §11's existing manual lane (Cherokee/LiensNC: operator
saves a page, an offline parser ingests it, no live session reuse at all) — the finding here
determines whether Wake instead supports "operator clears the checkbox once, this scraper's own
Playwright session then drives real live searches/fetches off that same cookie for a while" or a
tighter "operator stays at the keyboard, pulls one bounded batch per clearing" pattern; either way,
`_fetch_wake` can also just call `pingSession` on a timer the same way the real site's own JS does,
which costs nothing and only helps.

**CORRECTION 2026-10-14 (cont. x4)** — the owner specifically pressed on completeness this same
night and three further real, confirmed gaps came out of it, all in this same file (two of the
three are the ones flagged just above). All three were live-verified against the real sites, not
just read from code and assumed.

1. **Durham's "page 1 only" gap is now FIXED.** The 14-day/1,243-document pull cited above was
   never full pagination — `_fetch_durham` read page 1 of Tyler's ~100-row page size and stopped,
   run after run, on a platform whose own 90-day window turned out live-verified to be **96 pages
   (~9,502 rows total, newest-first)**, confirmed both by the real `searchPost` JSON reply
   (`{"totalPages":96,...}`) and by the rendered `Showing page 1 of 96 for 9502 Total Results`
   summary. `_fetch_durham` now walks pages 2..min(totalPages, `_DURHAM_MAX_PAGES`=20) the same way
   `_fetch_wake` already walks its own pages (a direct `searchResults/<search_id>?page=k`
   navigation per page, not a second search submit, and the same `Showing page X of Y` regex,
   renamed from Wake-only `_WAKE_PAGE_OF_RE` to the shared `_SS_PAGE_OF_RE` since Durham and Wake
   are the same platform/tenant family). Live-verified via httpx replaying the real session (no
   Chromium run locally, same memory-pressure reasoning used elsewhere in this file): walking the
   newest 20 pages pulled **2,000 real rows with 2,000 DISTINCT instrument numbers and zero overlap
   between any two consecutive pages** — genuine advancement, not page 1 re-read 20 times. 20 pages
   is still a deliberate, documented partial-coverage budget (~21% of the 96-page window), the same
   proportion of honesty this file already accepts for Brunswick's own page budget (~18%) — not
   silently implied complete.
2. **The shared `rod/nc_tyler.py` `_SS_HEAD` multi-tract gap (flagged just above) is now FIXED.**
   The regex no longer requires one fixed BT:/B:/P: slot sequence between the header's two bullets
   — it captures the middle section as a blob and pulls `BT:`/`B:`+`P:` out of it with their own
   sub-patterns, so `instrument_no`/`recorded` no longer depend on how many book/page pairs that
   middle section holds. Re-run live against the exact real multi-tract text already on record
   (instrument 2026086748): `instrument_no` is now `"2026086748"`, `recorded` is `"2026-07-31"`,
   and `book`/`page` are the FIRST pair (the primary tract — the second tract's pair is not
   separately modeled, matching the scope asked for). Ordinary single-pair headers (Durham's and
   Wake's own real fixtures) still parse identically to before. This real lead, previously silently
   dropped on both Wake and Durham, is now captured on both (same shared parser).
3. **The Grantor/Grantee 5-name cap (flagged just above) is confirmed GENUINELY NOT FIXABLE at the
   search-results level — not a parser bug.** Re-checked live on Durham too, not just Wake: a real
   DEED (instrument 2026190164, book 10639 page 799) declares "Grantor/Party 1 (12)" in its own
   column header, but the search-results row's DOM itself contains only 5 `<li>` name nodes —
   `parse_selfservice()` has no slice/cap of its own (`cols[label] = [... for x in items[1:] ...]`
   takes every item present) and faithfully returns exactly what the site rendered. A live scan of
   the newest 2,000 Durham rows found 151 (~7.6%) with a declared count above 5 — not a rare edge
   case. The missing names ARE confirmed to exist one hop deeper: that same document's own detail
   page (`/web/document/DOC291S618?search=DOCSEARCH5S1`, fetched live) lists all 12 real grantors in
   full. Getting the complete list for every truncated row would need a new per-row detail-page
   fetch neither `_fetch_durham` nor `_fetch_wake` does today (Wake's existing one-hop
   related-documents visit is a different purpose — OTHER instruments a document references, not
   this SAME document's own party list) — left honestly flagged rather than "fixed" with a change
   that cannot work at the search-results level.

See `scrapers/counties_nc/nc_rod_captcha.py`'s own module docstring (2026-10-14 (cont. x4) and
(cont. x5) correction blocks) and `tests/test_nc_rod_captcha.py` for the full writeup and real
schema-accurate fixtures built from this live pull.

- `counties_nc/nc_rod_captcha.py` — **6 of 9 counties remain genuinely walled** (Iredell, Craven,
  Greene, Harnett, Randolph, Stokes); Durham and Brunswick **removed from this list** (fixed in the
  corrections above). Wake **removed from this list**: the reCAPTCHA itself is still genuinely
  walled for an UNATTENDED run (never automated, by design) — but the real search, parser, and
  one-hop related-documents follow-through are now fully built and live-verified, ready to run off
  a human-cleared session (see the correction immediately above for the full writeup, including the
  live-measured session-reuse window and two further flagged, documented gaps — one now fixed, one
  confirmed genuinely not fixable at this level, see the 2026-10-14 (cont. x4) correction just
  above). Durham's own coverage also improved materially in that same correction: real pagination
  (20 of 96 pages per run, not page 1 only) and the shared multi-tract header fix both apply to it
  too, since Durham and Wake share the same `rod/nc_tyler.py` parser.
- `national/sc_sos_entity.py` (build spec already given to Hermes earlier this session)
- `public_notices/nc_notices_counties.py` vs `ncpublicnotices.py` (same site — does the
  interstitial actually gate it or not? One module says yes, the other's code says no.)

**CORRECTION 2026-10-14 (cont.)** — `counties_sc/sc_qpublic.py` was also WRONGLY listed here: no
login or CAPTCHA was ever found. Live-checked, not assumed, and it's a bigger problem than "the
code never submits a query" suggested:
  * `_COUNTY_PAGES`'s URL scheme was simply invalid. Every entry used
    `Application.aspx?App={County}SC&Page=search` — live-fetched via
    `get_text(wall_bypass=True)`, this returns a generic Schneider "qPublic - An error has
    occurred" response for every county tried (Berkeley, Beaufort, Colleton), a backend
    application error unrelated to Cloudflare (no challenge markers; pydoll renders real content,
    it's just the error page). `Page=search` is not a real query param on this platform at all.
  * Correcting the alias to `App={County}CountySC` (cross-checked against the sibling
    `kershaw_flc` docstring's own `App=KershawCountySC` reference and the already-known-good
    Oconee app in `assessor_cards/qpublic_render.py`) DOES resolve real per-county landing pages
    for Kershaw/Oconee/Colleton — Cloudflare clears cleanly via wall_bypass, confirming that half
    of the old docstring. But `App=BerkeleyCountySC`/`App=BeaufortCountySC` still 500 the same
    way, so even this fix isn't a uniform formula across the other 25 counties in the dict.
  * More fundamentally: on the apps that DO resolve, both real query mechanisms (owner/address/
    parcel Search, Sales Search) are stateful ASP.NET WebForms POST pages — confirmed live via raw
    HTML capture of Kershaw's Search (PageTypeID=2/PageID=15084) and Sales Search (PageID=15087)
    pages (`__VIEWSTATE`/`__EVENTTARGET` hidden fields + a postback search button). A plain GET —
    all `get_text(wall_bypass=True)` and every `wall_bypass.py` tier can do — cannot submit this
    form; a `KeyValue=` GET shortcut to the Results route (PageTypeID=3/PageID=15085) loads the
    real page but the results grid stays empty (zero `<table>` rows, zero occurrences of the
    search term anywhere in the body).
  * Net: not fixable within this project's `get_text(wall_bypass=True)` GET-only convention. The
    legitimate use of this data source (resolve ONE already-known address/parcel to a property
    card) is already covered by `assessor_cards/qpublic_render.py` for 4 counties via a real
    driven browser session; extending that to blind discovery across the rest of this county list
    is a separate, much larger project. **Removed from this list** (no login needed) and disabled
    via `disabled=True`/`disabled_reason` in the scraper itself instead (same pattern as
    `counties_sc/oconee_flc.py` / `clarendon_tax_auction.py` / `kershaw_flc.py`) — see
    `tests/test_sc_qpublic.py`.

## Needs a live check, no login required (Claude can do this directly)

Every FLAG-LOW/FLAG-HIGH file not listed above — the ArcGIS-attachments list (Pattern A), the
national real-estate-listing list (Pattern B), the self-admitted-but-unconfirmed items in
Pattern D, `counties_sc/sc_dew_lien_registry.py`'s `LienDocument` field, and several smaller
single-file flags (`national/seeclickfix.py` photo field, `national/jail_bookings.py` mugshot
inconsistency across vendors in the same file, `national/people_search.py` first-card-only,
`national/nc_upset_bids.py` dropped `salestatus` field, `public_notices/echovita_obituaries.py`
and `funeral_home_rss.py` missing photo enclosures).

---

## Not yet started

This document is Wave 1 (code audit) only. Wave 2 (live verification + fixes) has not begun.
Given ~60 flagged files, this is a multi-session effort, not a single pass — prioritize by:
1. Pattern E (nc_unclaimed.py) — trivial fix, currently-pointless scraper, do first.
2. Pattern F remaining two — data already in hand, just needs writing out, no live check needed.
3. Pattern A and B (copy an existing working pattern from a sibling file in the same codebase)
   — moderate effort, high confidence, no login needed.
4. Pattern C and D — mix of no-login-needed live checks and genuinely walled sources requiring
   the owner's login.
