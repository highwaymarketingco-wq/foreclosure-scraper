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
built, and no scraper flag was changed. The hand-save lane
([OWNER_MANUAL_LANES.md, "SC Judicial Public Index: hand-save
fallback"](OWNER_MANUAL_LANES.md)) is the path for these case lists.

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
Widening that path to partition, quiet title and judgments is possible
without passing any barrier; Charleston is coastal, outside the core footprint,
so it is the owner's call and was not done here.

## Divorce is not in the Public Index

SC divorce filings are Family Court records. They are not in the Public Index;
they are in the Family Court portal `portal.fccms.sccourts.org`, a different
system, read today by `enrichment_sc_divorce.py` (party-name searches against
the portal's JSON API, `curl_cffi` with a Chrome fingerprint). Probe 5 shows
no challenge on that portal's front page today. Open question for the owner:
the attorney's clearance named the Public Index; the 2026-10-01 audit recorded
that the Family Court portal has its own terms page against automated use.
If the clearance also covers that portal (it is terms only), nothing further
is needed for the divorce signal's access path.

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
  a `ListingType` (lis pendens, foreclosure, partition, quiet title and
  judgments to `lis_pendens`; tax liens to `tax_lien`) and keeps the sub-type
  in `raw['sc_public_index']['subtype']`; a live reader would reuse it. One
  thing to fix first: its lane list also takes "possession", "ejectment" and
  "eviction" (meant to catch adverse possession), so a saved eviction grid
  would load tenants as `lis_pendens` rows, while the owner card says to skip
  evictions.
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
