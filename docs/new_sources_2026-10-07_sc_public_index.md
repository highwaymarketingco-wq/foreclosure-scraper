# SC Judicial Public Index: automation stopped at a technical barrier (2026-10-07)

## Decision being acted on

The owner's attorney cleared the SC Judicial Branch Public Index
(`publicindex.sccourts.org`) for our use, including Rule 610 and the
administrative order against automated, repetitive queries, and cleared
S.C. Code 30-2-50 for our SC mailings. Terms-only restrictions are therefore
not a wall for this source. The hard line is unchanged: if the site presents a
CAPTCHA, a login, a bot, Cloudflare or WAF challenge, or any other technical
block, the reader records it and stops. It never solves or routes around one.

## Verdict

**A technical barrier exists today on `publicindex.sccourts.org`. Nothing was
built against it.** The automatic lanes for foreclosure, lis pendens,
partition, quiet title, judgments and divorce from the Public Index were not
built for the 45 counties it serves, and no scraper flag was changed. The
hand-save lane ([OWNER_MANUAL_LANES.md](OWNER_MANUAL_LANES.md), Public Index
card) is the path for those counties. Charleston's own copy of the Index has no
barrier, and its existing reader now labels partition, quiet-title and judgment
cases. Family Court divorce now covers all 46 counties; the portal shows no barrier
(sections below).

## The probe (2026-10-07, about 15:00 ET)

Five GET requests in total, one at a time, at least 3 seconds apart, from
Python `httpx` with an ordinary desktop Chrome `User-Agent` and the standard
`Accept` / `Accept-Language` headers. No POST, so no disclaimer was accepted.
No JavaScript was executed. Facts recorded: status, final URL, title, byte
count, response header names, cookie names, and yes/no markers. No page
content was kept.

| # | URL | Status | Body | What came back |
|---|---|---|---|---|
| 1 | `https://publicindex.sccourts.org/Spartanburg/PublicIndex/` (county landing / disclaimer) | **406** | 0 bytes | No title, no cookies, no `server` header |
| 2 | `https://publicindex.sccourts.org/Spartanburg/PublicIndex/PISearch.aspx` (search form) | **406** | 0 bytes | Same |
| 3 | `https://publicindex.sccourts.org/` (site root) | **406** | 0 bytes | Response headers are a caching edge's: `via`, `x-served-by`, `x-cache`, `x-cache-hits`, `x-timer`. The refusal is host-wide, at the edge, before the court application |
| 4 | `https://jcmsweb.charlestoncounty.org/PublicIndex/` (Charleston County's own copy of the Index, a different host) | 200 | 10.6 KB | "Public Index Search" disclaimer page with the Accept button and the "automated, repetitive querying ... expressly prohibited" text (terms only, cleared). One `ASP.NET_SessionId` cookie. No challenge markers |
| 5 | `https://portal.fccms.sccourts.org/` (Family Court portal, a different system) | 200 | 5.7 KB | Angular application shell titled "Home". No challenge markers |

Probe 1 to 3 are the barrier: the Index's edge refuses a request that
identifies itself as an ordinary browser by its headers, with HTTP 406 and an
empty body, on every path tried, including the root. This is a technical
block, so the probe stopped there. It was not retried with a different TLS
fingerprint, a headless browser or a stealth browser, because each of those is
a way around the block.

## What sits behind the 406 (earlier measurements in this repo, not re-run today)

Re-measuring these would mean passing the block, so they are cited, not
repeated:

- 2026-06-30 recon (`scrapers/counties_sc/sc_public_index.py` docstring): a
  client presenting Chrome's TLS fingerprint (`curl_cffi`, impersonate) got
  the disclaimer page, but after the disclaimer the search page `PISearch.aspx`
  served an F5 Distributed Cloud / Shape **"Client Challenge"** (page title
  "Client Challenge", a `/_fs-ch-.../` script bundle). It runs obfuscated
  browser-fingerprinting JavaScript and issues a clearance cookie only to a
  client that passes it. That is a bot challenge in the plain sense of the
  hard line.
- 2026-09-27 (`scrapers/national/sc_public_index.py` docstring): headless
  Chrome got HTTP 406 from the same edge. Only a headed, anti-detection Chrome
  (`nodriver`) or Scrapling's `StealthyFetcher` (camoufox) got through.
- 2026-10-01 (`scrapers/counties_sc/sc_county_rosters.py` comment): the
  `CaseDetails.aspx` case-detail page sits behind the same challenge and
  renders blank without a stealth browser.
- `src/foreclosure_scraper/http_client.py` notes that this host returns 403/406
  to plain clients on the TLS handshake alone.

The 2026-10-02 validation ("58 live searches in 8 counties, no CAPTCHA") and
the 2026-10-04 manual-steps table that repeats it are consistent with this:
there is no CAPTCHA. The barrier is the edge refusal plus the JavaScript
client challenge, which a person's desktop browser passes without showing
anything, and which an automated client passes only by running
anti-detection software. The owner card that said "The wall: None today" was
written from those notes; it is corrected to point here.

## Which counties this covers

Forty-five of the 46 counties are served from `publicindex.sccourts.org/<County>/`
and are behind the barrier. Charleston runs its own copy of the Index at
`jcmsweb.charlestoncounty.org`, which answered normally (probe 4). Charleston is
already read every run by `national.sc_public_index`'s Charleston path.
Distressed leads are statewide with no coastal exclusion (owner's rule), so that
path now labels partition, quiet title and judgments too (next section).

## Charleston case-type lanes (built 2026-10-07)

Coordinator decision, same day: the five stealth paths stay exactly as they are
(not touched, extended or copied); the open Charleston copy is extended with
plain requests and the disclaimer click-through it already performs.

- **What changed** (`scrapers/national/sc_public_index.py`, Charleston path
  only): `_parse_charleston_results()` reads the SearchResults grid by column
  header, including Type, Subtype, Judgment # and Court Agency, which the shared
  six-column positional parser drops. Each Common Pleas case gets
  `raw['sc_public_index']['lane']`: `foreclosure`, `partition`, `quiet_title`
  (also adverse possession), `lis_pendens`, `judgment` (Transcript, Foreign,
  Magistrate's, Confession of Judgment) or `other`, plus `subtype`, `case_type`,
  `judgment_number`, `court_agency`, and plaintiff/defendant from the case
  cell's caption, as the other court scrapers do.
- **Judgments** become `judgment_lien` leads: source
  `national.sc_public_index.judgment_lien`, listing type `distressed`, which the
  scorer names `judgment_lien` (FINANCIAL 12, the NC docketed-judgment signal).
  A transcribed judgment is a lien on the debtor's SC real property (S.C. Code
  15-35-810). Foreclosure, partition, quiet title and lis pendens stay
  `lis_pendens` under the old source.
- **`other` is no longer a lead** (coordinator, 2026-10-07): auto accidents,
  contracts, torts and the rest are counted, not emitted
  (`LAST_CHARLESTON_STATS['other_not_emitted']`, the
  `sc_public_index.charleston_lanes` log line, the scraper's `lane_stats`).
  Cases with no Subtype column (unknown layout) still go out as before.
- **Dropped:** evictions (name the tenant), minors' settlements (name a minor),
  sealed, protection-order and family matters. Previously every Charleston
  Common Pleas case was kept.
- **Dedupe:** one row per case, and the defendant's party row now wins (it was
  the first party seen, often the plaintiff).
- **Pacing:** 2 s now also after the landing GET and after the Accept POST, then
  26 letter searches 2 s apart, one thread, about 28 requests a run.
- **Unchanged:** the other 44 counties' rows (no lane keys; a test pins their
  output). If Charleston's grid lacks a "Case Number" header, the parser falls
  back to the old positional one and rows carry no lane.
- **Wiring:** none. The rows pass `_in_scope` and `_active_only` as they are
  (tested; `DATELESS_OK_SOURCES` matches the judgment sub-slug by prefix).
- **Tests:** `tests/test_sc_public_index_charleston_lanes.py` (11, made-up
  names and case numbers, including full passes against a fake session).
- **Live proof (run by the coordinator with the owner's clearance, 2026-10-07,
  letters B, M, W).** Grid headers: name, party type, case number, filed date,
  case status, disposition date, type, subtype, judgment #, court agency. The
  parser now matches exactly these ten labels (`CHARLESTON_HEADERS`); any other
  layout falls back to the positional parser and rows go out unlabeled. Cases
  seen 2,700: other 2,016 (75%), foreclosure 520, judgment 158, partition 5,
  lis pendens 1; 422 eviction / minor / sealed party rows dropped; 684 emitted,
  only 14 of them filed 2024 or later.
- **Lead rules per lane** (`case_lead`, coordinator's second pass the same day).
  Open = no disposition date and no closed status (closed, disposed, dismissed,
  satisfied, settled, withdrawn, vacated, cancelled).
  - Foreclosure: open, OR disposed in the last 9 months (274 days) with a
    disposition that is not a dismissal, withdrawal, discontinuance,
    settlement, satisfaction, transfer, vacatur or cancellation. In SC a
    foreclosure is usually disposed when the judgment of foreclosure is entered
    and the Master-in-Equity sale comes weeks later, so such a case is kept and
    marked `raw['foreclosure_judgment_entered'] = True` with
    `raw['foreclosure_judgment_date']` (the disposition date). It is kept even
    when filed before 2024. The same flag sits inside `raw['sc_public_index']`,
    which the board publishes whole; the two top-level keys are published only
    once they are added to `web_artifact.RAW_KEEP`. That edit was not made here
    because `web_artifact.py` has another session's uncommitted changes.
  - Partition, quiet title, lis pendens: open only.
  - Judgment: kept unless the status says satisfied, vacated, cancelled,
    released or expired (its disposition date is the day it was entered).
  - Other: never. Unlabeled (unknown layout): as before.
  Everything not kept is counted in `not_lead_by_lane`, and the run stats carry
  a per-lane profile of distinct status / type / subtype values and filed and
  disposition years.
- **Share of the 520 foreclosures kept: not measured yet.** It needs one more
  run of `scripts/charleston_lane_proof.py`, which now prints
  `foreclosure_kept_share`, the distinct status / type / subtype values and the
  year distributions per lane. It accepts the Charleston disclaimer, so the
  agent did not run it; the coordinator or the owner does. About 11 requests,
  3 s apart.
- **Filed-date window search (built, unverified live).** When the search page
  (the one reached after the disclaimer) has a date-type dropdown with a
  "filed" option and From / To boxes, each run sets Circuit Court and Common
  Pleas (option values read from the page, with the dropdowns' own postbacks)
  and searches 14-day filed-date windows from the last day read (minus 3 days of
  overlap) to today. On the first run it looks back 120 days. A window that
  fills the 250-row grid, or says the maximum was exceeded, is split in half. If
  the form also offers a disposition date type, a second sweep reads the last 9
  months of dispositions, which is where judgment-entered foreclosures show up.
  Caps: 40 requests a run, 3 s apart, one thread; an interrupted run resumes.
  State: `data/charleston_public_index/state.json` (git-ignored; keys
  `filed_through`, `disposed_through`). If the page has no date filter, or the
  first answer is not a results page, the run falls back to the letter sweep
  and saves no state. Switch: `CHARLESTON_PI_DATE_WINDOW=0`. Whether
  Charleston's form has these controls is not known yet: part 2 of the proof
  script prints the form's date options and runs two windows.

### Cleanup of carried rows (prior correction 6, narrowed)

The blanket rule (withdraw every carried Charleston row without a lead label:
all 1,549 on today's board) is removed. Rows the scraper no longer emits are
retired by the normal carry-forward aging, and relabelled ones come back on the
next run. What remains withdraws a carried Charleston row of
`national.sc_public_index` (or its `judgment_lien` sub-slug) only when its stored
lane is `other` or its stored status records a dismissal, withdrawal,
discontinuance or satisfaction. Withdrawn means listing type `unknown` (the row
stays on the board), with `raw['withdrawn_case_type_other']` = {reason, at,
listing_type, lane, status, date_disposed}. It is reversible: when a later copy
no longer meets the rule, the audit key is dropped and the recorded type comes
back if the row is still `unknown`; `restore_case_type_withdrawal()` does it by
hand. Tests: `tests/test_prior_correction_charleston_case_type.py` (6).

**What it would withdraw on today's board** (one read-only pass, counts only):
260 of the 1,549 Charleston rows (Dismissed 252, Satisfied 8). The other 1,289
are left alone, including the 557 open ones without a label and the 570
Settled ones: settlement is not in the cleanup rule, and those rows age out if
the scraper stops emitting them.

## Divorce is not in the Public Index

SC divorce filings are Family Court records. They are not in the Public Index;
they are in the Family Court portal `portal.fccms.sccourts.org`, a different
system, read today by `enrichment_sc_divorce.py` (party-name searches against
the portal's JSON API, `curl_cffi` with a Chrome fingerprint). The attorney's
clearance covers its terms (coordinator, 2026-10-07).

**Covered until 2026-10-07: 8 counties.** All 5,105 SC divorce rows on the
board come from them: Spartanburg, Pickens, Greenville, Cherokee, Oconee,
Laurens, Anderson, Union. The limit was our code, not the portal: `_COUNTY_CODE`
in `enrichment_sc_divorce.py` mapped only those 8 counties.

**The other 38 counties are reachable with no barrier.** Bounded probe,
2026-10-07, ordinary headers, 3 s apart, no person searched: GET `/` (200, the
search application, no CAPTCHA, challenge, login or terms markers), then the two
calls the search form makes when it loads: POST `/Home/GetAntiForgeryToken`
(200, token) and POST `/apiurl/api/FEPublicAccessValidationCodes/Validationcode`
with `{"codeType":"LOCATION"}` (200). The location list has all **46** counties,
codeIDs 1005 to 1050 in alphabetical order: Abbeville 1005, Aiken 1006,
Allendale 1007, Anderson 1008, Bamberg 1009, Barnwell 1010, Beaufort 1011,
Berkeley 1012, Calhoun 1013, Charleston 1014, Cherokee 1015, Chester 1016,
Chesterfield 1017, Clarendon 1018, Colleton 1019, Darlington 1020, Dillon 1021,
Dorchester 1022, Edgefield 1023, Fairfield 1024, Florence 1025, Georgetown 1026,
Greenville 1027, Greenwood 1028, Hampton 1029, Horry 1030, Jasper 1031,
Kershaw 1032, Lancaster 1033, Laurens 1034, Lee 1035, Lexington 1036,
Marion 1037, Marlboro 1038, McCormick 1039, Newberry 1040, Oconee 1041,
Orangeburg 1042, Pickens 1043, Richland 1044, Saluda 1045, Spartanburg 1046,
Sumter 1047, Union 1048, Williamsburg 1049, York 1050. The 8 codes in
`_COUNTY_CODE` match this list.

**Now all 46 (2026-10-07).** `_COUNTY_CODE` holds the full list, looked up
case-insensitively (`_county_code`: "Mccormick", "York County"). Per-run cap
(400), refresh windows, 30-minute budget, 3 workers and the 12-failure abort are
unchanged, so the newly eligible leads in 38 counties are worked through over
several runs. Tests: `tests/test_sc_divorce_all_counties.py` (4, made-up names).
Live proof, 2 new counties, counts only, nothing written to the board: 2 person
owners each in Horry (1030) and Lexington (1036), one worker, 3 s before each
lead: 4 searched, 12 category calls, 0 errors, 0 divorce cases for those 4
owners. One common-surname query per county (category 110 - Divorce) confirms
the codes return cases: Horry 1,505 and Lexington 1,288 matches (over the
portal's 500 display cap). No CAPTCHA, challenge or login at any point.

## Premise check: the "disabled" scrapers are already running

The task assumed `counties_sc.sc_public_index_lis_pendens` and the SC divorce
enricher were still disabled from the 2026-10-01 audit. They are not. On
2026-10-02 the owner had every one of those disables reverted:

- `b45e3e79` (2026-10-01) added `disabled=True` to
  `sc_public_index_lis_pendens`; `4d442dea` (2026-10-02) removed it, together
  with the same flag on `counties_sc.sc_public_index` and
  `national.sc_public_index`, and rewired `enrichment_courts.py` back through
  `sc_public_index._scrape_county()`.
- `3827b032` (2026-10-02) restored the `enrich_sc_divorce` call in `main.py`
  ("RE-ENABLED 2026-10-02 per owner direction").

So there is no disable flag left to remove. These code paths are live and pass
the challenge with anti-detection browsers:

| Code path | How it gets past the barrier |
|---|---|
| `scrapers/counties_sc/sc_public_index_lis_pendens.py` (7 Upstate counties, CP Foreclosure 420) | Scrapling `StealthyFetcher` (camoufox) |
| `scrapers/counties_sc/sc_public_index.py` (7 Upstate counties, CP + GS empty-name sweep) | Scrapling `StealthyFetcher` |
| `scrapers/national/sc_public_index.py` (44 non-Charleston counties, rotating batch) | headed `nodriver` (undetected Chrome) |
| `enrichment_courts.py` (SC plaintiff/defendant backfill) | calls `sc_public_index._scrape_county()` |
| `enrichment_case_detail.py` (SC case detail) | headed `nodriver` |

Each of these conflicts with the hard line as restated on 2026-10-07. They
were left untouched, because the owner's standing instruction since
2026-10-02 is that no scraper is disabled without his explicit say-so. This is
for the owner to decide: either these paths stop (and the hand-save lane
covers the Index), or the hard line has an exception for them.

## If the barrier goes away

Re-probe with the same five ordinary GETs (`scripts/reprobe_walls.py` already
lists `sc_publicindex`). If the county landing and `PISearch.aspx` both return
the page itself to an ordinary client, with no 406 and no "Client Challenge",
the build is straightforward, because the form and parser are already known:

- Form (live-verified 2026-06-30): court type `G` (Circuit), case type
  `CP  ` (Common Pleas, trailing spaces real), sub-type (Foreclosure `420   `,
  Partition 440, the quiet-title sub-type), date type `Filed`, a date window,
  last name blank (the date-bounded docket browse the site offers). Results
  grid `table#ContentPlaceHolder1_SearchResults`, capped at 250 rows, so the
  window must shrink when it fills.
- Parser: `ingest_sc_publicindex_export.py` already maps each Case Sub-Type to
  a `ListingType` (lis pendens, foreclosure, partition, quiet title, adverse
  possession and judgments to `lis_pendens`; tax liens to `tax_lien`) and keeps
  the sub-type in `raw['sc_public_index']['subtype']`; a live reader would
  reuse it.
- Shape: one county at a time, one request at a time, 2 s or more apart,
  per-run caps on pages and requests, resumable per-county
  last-filed-date state, skip Family Court, sealed and protection-order case
  types.

## Board today (one read-only pass, counts only)

One `iter_board_rows()` pass on 2026-10-07 (29 s, 284 MB peak): 350,013 rows,
108,590 of them SC.

SC rows by listing type: tax_sale 46,780; distressed 23,398; tax_lien 18,129;
unknown 9,382; lis_pendens 5,865; probate_notice 2,222; reo 1,041;
foreclosure_sale 451; bankruptcy 399; auction 363; estate_lead 326;
tax_sale_overage 234.

Rows whose source is one of the Public Index readers: **7,905**
(`counties_sc.sc_public_index` 5,540, `national.sc_public_index` 1,999,
`counties_sc.sc_public_index_lis_pendens` 362, the hand-save
`counties_sc.sc_public_index_export` 4). By type: lis_pendens 5,177, unknown
2,728. These are 88% of all SC lis_pendens rows. The three automatic readers
all have rows last seen 2026-10-06: they ran yesterday, through the barrier.

| County | Public Index rows | All SC lis_pendens rows | Divorce-positive rows (Family Court portal) |
|---|---|---|---|
| Charleston (own host, open) | 1,549 | 1,617 | 0 |
| Spartanburg | 1,209 | 728 | 1,856 |
| Anderson | 1,189 | 743 | 284 |
| Pickens | 959 | 415 | 746 |
| Laurens | 892 | 420 | 406 |
| Cherokee | 799 | 417 | 488 |
| Oconee | 461 | 354 | 471 |
| Union | 397 | 214 | 174 |
| Beaufort | 360 | 377 | 0 |
| Edgefield | 48 | 48 | 0 |
| Saluda | 42 | 42 | 0 |
| Greenville | 0 | 324 | 680 |
| The other 34 counties | 0 | 166 in all | 0 |

(Public Index rows include `unknown`-typed criminal and civil sweep rows, so a
county's Public Index count can exceed its lis_pendens count.)

- Case sub-types carried: "Foreclosure 420" on 334 rows; none on the rest. No
  partition, quiet-title or judgment rows from the Index exist on the board.
- Divorce: 5,105 SC rows carry a divorce hit, all from the Family Court portal
  (`raw['divorce']['source'] == 'sc_fccms'`), in 8 counties. None come from the
  Public Index.
- **What the Index could add per county was not measured**: it cannot be
  counted without passing the barrier. The only earlier measure in the repo is
  one full Spartanburg Common Pleas sweep on 2026-09-27: 1,233 distinct cases
  (`national.sc_public_index` docstring). If the owner keeps the hand-save
  lane, the gap it would fill is largest in the 35 counties with no Index rows
  at all, and in partition, quiet-title and judgment lists everywhere.

## Hand-save loader: evictions skipped (2026-10-07)

`ingest_sc_publicindex_export.py` used to file "Possession", "Ejectment" and
"Eviction" cases as `lis_pendens`, putting the tenant's name on the board.
`distress_score.py` has no eviction signal (only the county-level LSC
eviction-rate context), so these rows are now skipped by `is_eviction_subtype()`
on the Subtype or Type cell, even under `lane_override` or `keep_all_subtypes`.
"Adverse possession" (an occupant's title claim) still loads as `lis_pendens`.
Magistrate civil rows with the generic "Summons & Complaint" sub-type (for
example an HOA collection suit against the owner) still load. Tests:
`tests/test_publicindex_export.py` (3 new, 2 updated).

Test fixture names (2026-10-07): `tests/test_publicindex_export.py`,
`tests/test_sc_divorce_search.py` and
`tests/test_sc_divorce_party_role_and_middle_match.py` carried party names,
owner names and captions copied from live pages and the board; they are now
made up (same name shapes: ALL-CAPS surname-first, Title Case first-last,
comma, suffix, "&", "et al.", "AND"), with the test logic unchanged.
