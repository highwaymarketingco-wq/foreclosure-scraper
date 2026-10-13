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
`counties_nc/nc_rowan_cott.py`, `counties_nc/nc_cchs_deeds.py`, `counties_sc/sc_rod_acclaim.py`
(same AcclaimWeb vendor as Cherokee itself), `counties_sc/sc_rod_walled.py` (Clarendon runs the
literal same AcclaimWeb software), `national/cash_buyer_deeds.py`.
One is worse than "never looked at" — **a real in-repo contradiction**:
`counties_sc/sc_rod_cott.py`'s own docstring claims Union's document images are "pay-per-view,"
but the shared `rod/doc_images.py` module explicitly registers Union as confirmed **free**
(`COUNTY_IMAGE_STATUS[("SC","Union")] = ("free", ...)`) — and the function meant to fetch them,
`owner_dot_documents()`, has no code branch for `vendor == "cott"` at all, so it silently
returns `[]` even where the infrastructure already knows the image is free and reachable.

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

- `counties_sc/sc_rod_acclaim.py` (Pickens/Harris AcclaimWeb — same vendor as Cherokee)
- `counties_sc/sc_rod_walled.py` (Beaufort/Jasper/Clarendon — Clarendon is the same AcclaimWeb)
- `counties_sc/sc_rod_cott.py` (Union — the free/pay-per-view contradiction above needs settling)
- `counties_nc/nc_rod_captcha.py` (9 counties — already has real login/CAPTCHA mechanics built)
- `national/sc_sos_entity.py` (build spec already given to Hermes earlier this session)
- `public_notices/nc_notices_counties.py` vs `ncpublicnotices.py` (same site — does the
  interstitial actually gate it or not? One module says yes, the other's code says no.)
- `counties_sc/sc_qpublic.py` (worth confirming the search form even works at all — the code
  never submits a query)

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
