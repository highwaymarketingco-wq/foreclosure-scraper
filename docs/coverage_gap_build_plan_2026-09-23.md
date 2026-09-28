# Coverage gap build plan, 2026-09-23

Research/planning only — no code changed, no scraper run, no board touched, no git command run.
Built directly on `docs/completeness_audit_2026-09-23.md` section 3 (the 146-county, 7-family
breadth table) plus a source-code read of the scrapers named below and a review of prior scoping
docs (`docs/gap_ledger.md`, `docs/COVERAGE_100_LEDGER_2026-09-20.md`,
`docs/county_breadth_research_2026-09-21.md`, `docs/road_to_100_matrix.md`, the
`docs/enumeration*` per-county source inventories). Where a recommendation restates prior work,
that is called out explicitly; nothing here duplicates a scoping pass that already reached a
conclusion — it extends or acts on those conclusions against the fresh 2026-09-23 numbers.

Today's session (before this doc) fixed ~10 execution/data-quality bugs in existing scrapers and
ran a full board repair. None of that added a family to a county that didn't have it. This doc is
about what does.

## 1. The shape of the gap

Of 146 NC+SC counties, 5 have all 7 families (Buncombe, Burke, Cleveland, Henderson, Rutherford —
all NC, all inside the 18-county flip footprint). 141 are missing at least one family, and the
distribution is heavily skewed toward "missing almost everything," not "missing one thing":

| Families present | Counties | What this looks like |
|--:|--:|---|
| 0/7 | 2 | Chester SC, Fairfield SC — zero rows, any source |
| 1/7 | 65 | Tax delinquent only, nothing else — see below |
| 2/7 | 27 | |
| 3/7 | 18 | |
| 4/7 | 8 | |
| 5/7 | 9 | |
| 6/7 | 12 | Usually missing just Divorce or just Tax sale |
| 7/7 | 5 | All inside the 18-county footprint |

**65 of 146 counties (44%) carry exactly one family, and in every single one of them that family
is Tax delinquent.** Their "missing" list is always the same six: TaxS, LisP, Prob, Div, BK, CV.
This is one shape of gap repeated 65 times, not 65 different problems — it is what a county looks
like when it has an already-broad NC/SC tax-roll scraper (`nc_county_pdf_delinquent_tax`,
`nc_county_csv_delinquent_tax`, `nc_ptscloud_delinquent_tax`, or an SC per-county tax scraper) and
literally nothing else has ever been pointed at it.

Families ranked by how commonly they're missing (of 146 counties):

| Family | Missing in | Present in | Notes |
|---|--:|--:|---|
| Divorce | 127 | 19 | All 19 are NC; **zero of 77 SC counties have it at all** |
| Bankruptcy | 123 | 23 | All 23 sit inside a 21-town keyword list (see §2.3) |
| Probate/estate | 108 | 38 | Broader than divorce — obituary/heir sources add reach |
| Lis pendens | 105 | 41 | NC's share comes from one 22-county eCourts scraper |
| Code/vacant | 97 | 49 | County-specific ArcGIS/portal layers, genuinely one-off |
| Tax sale | 88 | 58 | Auction/sale-event data, distinct from delinquent rolls |
| Tax delinquent | 17 | 129 | Nearly solved; remainder is small SC counties |

## 2. Which families have a reusable pattern, and which don't

### 2.1 Lis pendens (NC) — a statewide, single-query, no-CAPTCHA source artificially capped at 22 counties

`src/foreclosure_scraper/scrapers/counties_nc/nc_ecourts_lis_pendens.py` hits NC AOC's public
**Judgment Search** (`portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`) — an open,
keyless, anonymous JSON endpoint with no WAF and no CAPTCHA (confirmed by reading the scraper: it
is a plain `httpx`/`client` POST, no browser, no `enrichment_waf_oss` import). The query shape
(`_build_search_object`, lines ~154-192) builds **one** `searchObject` with a `Location` facet
whose `buckets` list is built by looping `TARGET_COUNTIES` and emitting a District-Court + Superior-
Court bucket per county — then POSTs it **once** and pages `from`/`size` through the results. Adding
a county costs two more facet-bucket entries in the same request; it does not cost an extra round
trip, an extra CAPTCHA solve, or extra code.

`TARGET_COUNTIES` today has 22 entries (the 11 WNC/foothills footprint counties plus 11 coastal
counties added piecemeal 2026-06-25 through 2026-08-19). That is a historical artifact of the flip
footprint, not a technical ceiling — NC AOC's Judgment Search indexes every NC county's Clerk of
Superior Court, and this scraper already proves the facet mechanism works statewide-shaped. The
listing type this produces (`LIS_PENDENS`, occasionally `TAX_LIEN`) is **not** in
`main._FLIP_LISTING_TYPES`, so it is scope-gated by `config.in_scope_distressed()` — confirmed by
reading `main.py`'s `_county_in_scope()` — which accepts any real NC/SC county with **no** deny
list. Concretely: adding Wake, Mecklenburg, Forsyth, Guilford, Durham, etc. to `TARGET_COUNTIES`
would not be blocked by `SCOPE_DENY_COUNTIES` for this listing type, even though those same
counties are denied for flip-type leads.

**This is the single highest-leverage item in this plan.** 65 counties are TaxD-only today
specifically because nothing else reaches them; a huge fraction of NC's TaxD-only counties would
move to 2/7 (TaxD + LisP) the next time this scraper runs with a wider `TARGET_COUNTIES`.

### 2.2 Divorce (NC) — two existing code paths, one proven and costly, one cheap and unverified

`nc_ecourts_divorce.py` is the scraper actually producing today's 19-county divorce coverage. It
drives Tyler's full **Smart Search** SPA (not the Judgment Search JSON), which sits behind an
AWS-WAF image-grid CAPTCHA. The existing bypass (`enrichment_waf_oss.solve_waf_via_browser`, a
free OSS Gemini-vision solver) already works — memory confirms this is the "keep bypass code"
class of infrastructure the user has explicitly said to preserve — but the scraper loops **per
county** (`for county in counties:` at line 270), meaning one WAF solve per county per run. That is
why coverage stops at 22 counties and why 2 of those 22 (Lincoln, Mitchell) still show 0% divorce
in the fresh audit despite being in `TARGET_COUNTIES` — the WAF solve isn't 100% reliable per
attempt.

A cheaper path was scoped in a prior session and, as far as the current source reads, was **never
implemented**: `docs/gap_ledger.md` (line 119) documents that the open Judgment Search JSON — the
same endpoint §2.1 already drives with zero CAPTCHAs — was live-verified to also carry
`causeOfActionDesc == "FAM - Divorce"` / `caseCategoryKey == "FAM"` judgment rows, with both
spouses structured the same way lien debtors/creditors are. Reading `nc_ecourts_lis_pendens.py`'s
current `FORECLOSURE_CAUSES` set today confirms `"FAM - Divorce"` is **not** in it — the fix
described in the gap ledger was written up but not shipped. If it holds up under a fresh live
check, adding that cause to the same statewide, single-query, no-WAF endpoint would give divorce
coverage across however many counties `TARGET_COUNTIES` lists — the same batched-query economics
as §2.1 — and could let the expensive `nc_ecourts_divorce.py` WAF path be retired rather than
scaled. Flagging this as **unverified, not disproven**: it was proposed once, never shipped, and
there may be a reason it stalled that isn't written down (e.g. `causeOfActionDesc` values may
have since changed, or a granted-divorce judgment may not be the same lead quality as a raw CVD
filing). Treat it as a cheap spike, not a guaranteed win.

**SC divorce is a confirmed dead end for automation, not a gap.** SC's FCCMS portal
(`portal.fccms.sccourts.org`) is technically reachable — no login wall, a real API — but its own
disclaimer explicitly prohibits "automated, repetitive querying." `docs/gap_ledger.md` and
`docs/COVERAGE_100_LEDGER_2026-09-20.md` both record this as a **legal**, not technical, wall, and
note a one-time authorized manual/batch search was already run (28,660 of ~30,300 eligible SC
leads searched, 5,523 hits, since folded into scoring). There is no live incremental SC divorce
lane to build; 0/77 SC counties will stay at 0 for this family absent a change in that legal
posture.

### 2.3 Bankruptcy — already statewide at the source; the bottleneck is a 21-entry keyword dict

`national/courtlistener_bankruptcy.py` pulls from **all four** federal bankruptcy districts
covering NC and SC (`ncwb`, `ncmb`, `nceb`, `scb`) — those four districts partition the entirety
of both states by definition; there is no county-level restriction at the API layer. The scraper
itself says so: "pulls ... from the 4 federal bankruptcy courts covering our footprint" and, more
importantly, the docket data genuinely has no address field, so county attribution is done by
regexing city names out of the case caption against a hardcoded `CITY_TO_COUNTY` dict
(lines 104-129). That dict has exactly 21 distinct counties in it (the 18-county flip footprint
plus Mecklenburg/Yancey/Madison, presumably added because they're adjacent to footprint counties
and show up in captions). Every filing whose caption doesn't mention one of those ~28 town names
falls back to a state-level, county-less lead — which is why bankruptcy is present in only 23
counties even though the underlying source structurally spans all 146.

This needs **zero new scraping or API calls** — the dockets for every county's residents are
already being fetched every run. The fix is a bigger gazetteer: extend `CITY_TO_COUNTY` from 21 to
all 146 county seats (and realistically their next few largest towns, since debtors don't only
live in the county seat). Caveat from the scraper's own comment: a city mention "rare[ly]" appears
in the caption at all, so this should be sized as an incremental improvement, not a guaranteed
fix for the full 123-county gap — but it is free to try and cannot make anything worse.

### 2.4 Probate/estate (NC) — the same WAF pattern as divorce, plus a discovery-bound obituary lane

`nc_ecourts_estates.py` mirrors `nc_ecourts_divorce.py` exactly: same Smart Search WAF, same
22-county `TARGET_COUNTIES`, same per-county solve loop, same generalization cost/reliability
profile as §2.2. Widening its county list is the same tier-2 move as widening divorce's.

Probate's wider reach (38 counties vs. divorce's 19) comes from a second, independent lane:
funeral-home obituary RSS. `public_notices/funeral_home_rss.py` is a **host-map pattern** —
add one URL, get one funeral home's feed — currently wired for exactly 3 homes covering 3
counties (Buncombe, Cleveland, Anderson). Its own docstring says the path to scale is "probe more
core-county homes with the same two URL shapes [Frazer CMS `/feed`, or WordPress `ltobits` plugin
`/?feed=rss2&post_type=ltobits`] and add them to the host map." This is a commodity CMS market —
most independent funeral homes run one of a small number of platforms — so a systematic sweep
(search "obituaries + [county seat] funeral home" for each of the 141 gap counties, test both URL
shapes) is bounded, low-tech, and each hit is a one-line config add.

A national obituary aggregator that would have been the single biggest lever here —
`national/legacy_obituaries.py` (Legacy.com, which syndicates thousands of funeral homes and
newspapers) — is a **confirmed, documented dead end as currently written**, not a gap: its own
docstring records it was disabled 2026-09-15 after live verification that the `stateId=nc`
parameter is a no-op (a search scoped to "Asheville" returned real obituaries from Tampa FL, New
Britain CT, and New Zealand), so every row it emitted carried fabricated geography. It's cheap to
re-attempt only if someone finds Legacy.com's real numeric `stateId` values or a working
lat/lng-radius parameter — until then, don't route effort here.

### 2.5 Code enforcement/vacant — a real generic *wiring* pattern, but genuinely bespoke *discovery*

`counties_generic/arcgis_distress_layers.py` is exactly the kind of generic multi-county module
the audit should be checking for: a single `Layer` NamedTuple config table, and its own docstring
states the intent plainly — "adding the next verified [endpoint] is a few lines rather than a new
file." Today it has ~15 `Layer` entries covering roughly 10 counties (Buncombe, Lincoln,
Spartanburg, Pickens, Henderson, Transylvania, Burke, New Hanover, Richland, Greenville).

Its docstring also references a backlog: "the 18 per-county enumeration docs list ~525 verified
free endpoints, and a measured 263 of them are still unbuilt." That backlog (`docs/enumeration/`,
`docs/enumeration_r2/`, `docs/enumeration_r3/`) is real and already-researched — but it is scoped
to the **18 flip-footprint counties only**, confirmed by the file list (`enum_Anderson.md`,
`enum_Buncombe.md`, ... `enum_Union.md`, 18 files, no file for any of the other 128 counties). So
this backlog is high-leverage for *depth* inside counties that mostly already have several
families (per §1's table, most footprint counties are missing only Tax sale or Divorce, not Code/
vacant) — it does **not** attack the 128-county breadth problem for this family, because nobody
has run the equivalent per-county enumeration sweep outside the footprint yet.

**Conclusion for Code/vacant: the wiring is generic, but the discovery work for the 128 non-
footprint counties has not been done anywhere in this repo.** Each of those counties needs its own
"does this county publish a code-violation/condemned-structure/demolition-permit ArcGIS layer or
open-data portal" check before it can be wired — there is no statewide shortcut analogous to
§2.1/§2.3. This is the most honestly bespoke family in the list, alongside NC tax sale below.

### 2.6 Tax sale — SC has a semi-generic pattern (FLC); NC does not

Tax sale (the actual auction/sale-event list, distinct from a delinquent-tax roll) is missing in
88/146 counties. SC already has a repeatable shape here: South Carolina's Forfeited Land
Commission process is served by `counties_sc.sc_flc` plus per-county `<county>_flc.py` files
(confirmed built today: Spartanburg, Oconee (+ an assignment variant), McCormick, Lexington,
Richland, Terry Howe, Horry — 7-8 SC counties). SC has 46 counties total, so roughly 38 remain
unchecked against the same FLC vendor/portal shape — a genuine "extend the pattern" opportunity,
though (per §2.5's lesson) each one still needs a per-county existence check before it's free
wiring.

NC tax sale has no equivalent generic layer in this codebase: NC's tax-foreclosure procedure runs
through each county's own Clerk-of-Court in-rem or mortgage-style posting, and the existing
scrapers reflect that — one bespoke file per county (`buncombe_tax_foreclosure.py`,
`gaston_tax_foreclosures.py`, `wake_tax_foreclosure.py`, `haywood_tax_foreclosures.py`, etc., ~15
of them, all footprint or footprint-adjacent). There is no statewide NC tax-sale index analogous to
the Judgment Search JSON. Treat NC tax sale as bespoke-per-county, same tier as Code/vacant.

### 2.7 Tax delinquent — already 129/146; the last 17 are small SC counties on known vendors

The remaining gap (17 counties, all SC, all in the audit's lowest-row-count band — Chester and
Fairfield literally have 0 rows) is likely closeable cheaply rather than requiring new scraper
design. Two generic vendor patterns already exist and are proven extensible:

- `qpaybill_delinquent_roll.py` — one scraper, already covers **19** SC counties on the
  qPayBill/Springbrook vendor stack.
- `sc_catalis_delinquent_roll.py` — a second vendor pattern (Catalis/Sturgis), currently wired for
  only **Pickens**, but written generically (prefix-enumeration over `POST /Records`, the same
  shape regardless of tenant) and explicitly framed in its own docstring as a repeatable API, not
  a Pickens-only hack.

The concrete next step is a tenant-existence probe: for each of the 17 gap counties, check whether
it's a qPayBill or Catalis tenant not yet in either scraper's county list, before assuming a
bespoke build is needed.

## 3. Confirmed dead ends — do not build against these

| Item | Wall type | Evidence |
|---|---|---|
| SC divorce automation (FCCMS) | Legal (ToS bans automated/repetitive querying); portal itself is technically open | `docs/gap_ledger.md:123`, `docs/COVERAGE_100_LEDGER_2026-09-20.md:63` — one-time authorized manual batch already run and scored |
| SC lis pendens automation (SC PublicIndex) | Legal/technical (406 to automated GET, ToS-no-scrape) | `docs/gap_ledger.md:40`; manual saved-page lane exists instead |
| NC eCourts full Smart Search (raw SP intakes, raw CVD filings, non-JSON detail) | Technical, behind Tyler Identity Provider login | `nc_ecourts_lis_pendens.py` docstring: "Tyler's full SmartSearch ... is gated behind a Tyler Identity Provider login" |
| `national.legacy_obituaries` (Legacy.com aggregator) | Technical — not walled, but confirmed broken (geo-scoping no-op, fabricates state/country) | Scraper's own docstring, disabled 2026-09-15 |
| `repeat_tax_loss` deed-index sweep | Technical (Cloudflare bot challenge) | `docs/COVERAGE_100_LEDGER_2026-09-20.md:82,95` — code + 179 tests done, live search still blocked |
| Cherokee/Union SC assessor portals (owner, mailing, value) | Technical (Cloudflare interstitial) | `docs/COVERAGE_100_LEDGER_2026-09-20.md:106-107` |
| SC phone/contact ceiling (~21% free ceiling) | Structural (SC voter file is paid; consumer people-search is bot-walled/barred) | `docs/COVERAGE_100_LEDGER_2026-09-20.md:104-105` — an enrichment-depth ceiling, not a family-breadth gap, listed here for completeness |
| `ncnotices.com` / `scpublicnotices.com` full statewide expansion (all 97 NC / 46 SC counties in the filter) | Gray zone — grid preview is technically open (no CAPTCHA at list level, already scraped for 11-19 counties), but the site's written terms ban scraping and detail pages are click-through + reCAPTCHA walled | `docs/county_breadth_research_2026-09-21.md:298-299,331` calls this "an owner decision, not a clean win" — surfaced below as a build item that needs an explicit go/no-go, not chased by default |

## 4. Ranked build plan

Ranked by (family/counties closed) × (reuses an existing, proven pattern) ÷ (effort). "Hours" means
a config/list change to already-working code; "Medium" means the code path exists and works but
scaling it has a real per-unit cost (a WAF solve, a per-county discovery check); "Build" means no
existing pattern reaches this county/family combination at all.

| # | Move | Closes | Why high-leverage | Effort |
|--:|---|---|---|---|
| 1 | Widen `nc_ecourts_lis_pendens.TARGET_COUNTIES` from 22 to as many of NC's 100 counties as the Judgment Search facet mechanism accepts | Lis pendens, up to ~78 more NC counties, in one run | Single batched JSON query, no WAF, no CAPTCHA, no per-county cost; not blocked by `SCOPE_DENY_COUNTIES` for this listing type (verified in `main._county_in_scope`); moves a large slice of the 65 "TaxD-only" counties to 2/7 | Hours |
| 2 | Spike: add `"FAM - Divorce"` (and the `caseCategoryKey == "FAM"` guard) to the same Judgment Search query and route through the existing 50B/DVPO exclusion pattern | Divorce, potentially the same NC counties as #1, at the same zero-CAPTCHA cost | Reuses the exact endpoint #1 already proves out; a prior session (`gap_ledger.md`) scoped this and live-verified the cause code exists but never shipped it — cheapest possible test of the biggest single-family gap (Divorce, missing in 127/146) | Hours to test; unverified premise, spot-check live before trusting |
| 3 | Extend `courtlistener_bankruptcy.CITY_TO_COUNTY` from 21 counties/~28 towns to all 146 county seats + top towns | Bankruptcy, partial gains across up to 123 counties | Zero new scraping — same dockets already fetched every run, purely a parsing/attribution fix; cannot regress anything | Hours (build a ~150-200 row NC/SC gazetteer) |
| 4 | Widen `nc_ecourts_estates.TARGET_COUNTIES` the same way as #1, using the existing WAF bypass | Probate/estate, additional NC counties beyond the current 22 | Same proven bypass code (`enrichment_waf_oss`), same county-list mechanism as divorce; genuinely additive since probate's obituary lane doesn't reach most of these counties either | Medium — one more WAF image-grid solve per added county per run; reliability scales with WAF-solve success rate, not with code complexity |
| 5 | Sweep for more funeral-home RSS feeds (Frazer `/feed`, WordPress `ltobits`) across the 141 gap counties, add hits to `funeral_home_rss.py`'s host map | Probate/estate, county-by-county | Commodity CMS market — cheap per-hit once found; independent of the WAF path, so it's additive reach, not redundant with #4 | Medium — discovery-heavy (has to be done per county), each hit trivial to wire |
| 6 | Tenant-probe the last 17 tax-delinquent counties against qPayBill (19-county vendor, generic) and Catalis (1-county so far, built generic) before designing anything bespoke | Tax delinquent, closing 129/146 toward 146/146 | Two vendor patterns already proven extensible; likely a config-list add, not new code, for however many of the 17 turn out to be existing-vendor tenants | Hours to probe; per-hit wiring is small |
| 7 | Extend the SC FLC pattern (`sc_flc.py` + `<county>_flc.py`) to the ~38 SC counties not yet checked | Tax sale, SC side of the 88-county gap | Same code shape already working for 7-8 SC counties; SC's tax-sale process is more standardized (state FLC statute) than NC's per-county Clerk process | Medium — per-county existence check, then reuse the pattern |
| 8 | Owner decision needed, not a default build: widen `ncnotices.com`/`scpublicnotices.com` county-checkbox filters from today's 11/19 NC + partial SC toward the full 97 NC / 46 SC counties the site's own filter supports, staying at the grid-preview level (no walled detail-page fetch) | Lis pendens/probate/divorce/tax-sale name+case leads, potentially dozens of counties | The mechanism is proven (already running for 11-19 counties) and the mechanism itself hits no CAPTCHA — but two independent prior research passes flagged the site's written terms as banning scraping outright, which is a different question from whether it's technically blocked | Medium once approved; effort is mechanical (more checkbox ticks + postbacks), the open question is permission, not code |
| — | Code/vacant (97/146 missing) and NC tax sale (part of the 88/146 missing) | — | No statewide or generic shortcut exists in this codebase for either; each needs a genuine per-county discovery pass (the kind `docs/enumeration/*` already did for the 18 footprint counties) before any wiring can start | Build, one county at a time — not recommended as a batch move; call out explicitly as the two families with no cheap lever, so effort isn't wasted looking for one |

## 5. What to verify before touching code

None of items 1, 2 or 4 above were re-run live in this research pass (this task was research-only
and the board is mid-run). Before building:

- Confirm NC AOC's Judgment Search actually indexes all 100 counties as `<County> District Court`
  / `<County> Superior Court` facet names (a handful of NC counties share a Clerk of Court office
  with a neighbor for some case types — verify facet names exist before assuming a 1:1 county
  mapping).
- Live-check that `causeOfActionDesc` still contains a divorce-classified value before writing
  item 2's filter — the gap ledger's finding is from a prior session and could be stale.
- Confirm `in_scope_distressed()` really does admit a newly-added county through the full
  ingest → enrichment → publish path end to end for at least one test county outside the current
  22, not just at the `_in_scope()` gate (other stages — e.g. the resolver, `DATELESS_OK_SOURCES`
  routing — were not re-checked here for county-list sensitivity).
