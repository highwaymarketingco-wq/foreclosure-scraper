# HANDOFF — current state of play

**Updated 2026-08-12.** Read this first in a new session, then go straight to
work. Everything below is either verified or explicitly marked unverified.

Keep this file current. It exists so a fresh session costs one file read instead
of an hour of rediscovery, and so long sessions can be abandoned cheaply.

---

## Where the board is

- ~38,500 leads, all confirmed seen within 7 days.
- ARVs on 25,338; max bids on 20,434.
- 3,809 leads carry a contradicted-ARV flag and correctly publish **no** bid, no
  verdict and no equity.
- `merge_prior_board` handles pulled-then-relisted correctly: `pulled_sale`
  counter, 4-miss retention, and on reappearance it clears the counter while
  preserving enrichment.

## What is running right now

A full engine run started **2026-08-11 13:24** and passed 23 hours. It was
**not hung** — it was re-reading FEMA flood zones for every geocoded lead.

**Where the 23 hours actually went** (measured from the log's 365 timestamped
events — the rest of the file is untimestamped httpx noise):

| span | duration | what |
|---|---|---|
| 13:52 → 19:22 | **5.5 h** | scrape phase, stealth browser on `portal-nc.tylertech.cloud` returning 202 (AWS-WAF CAPTCHA) |
| 19:23 → 05:57 | **10.5 h** | skip trace, grinding `fastpeoplesearch.com` 403s |

**16 of 23 hours were spent retrying sources already documented as permanently
walled**, and neither phase emitted a single log line while it happened.

Both are now bounded. `SKIP_TRACE_MAX_SECONDS` (default 900) and
`SCRAPE_PHASE_MAX_SECONDS` (default 10800) join the budgets the court and vision
phases already had. The scrape budget uses `asyncio.wait`, **not**
`wait_for(gather(...))` — the naive form cancels every task on expiry and throws
away sources that already finished. A test pins that.

**Flood was NOT the bottleneck.** I fixed it before measuring and briefly said it
was; at ~860 req/min the whole FEMA phase is about 35 minutes. The fix is still
worth having (it removes ~30k redundant requests per run) but it was not why runs
take 23 hours. `enrich_with_flood` now skips already-tagged leads, caches by
coordinate rounded to 4 decimals (~11 m, same parcel) and runs at concurrency 8;
`FLOOD_REFRESH=1` forces a full re-read.

Geocode's 1 req/sec is **Nominatim's stated policy, not a bug** — and a batch
pre-pass already resolves the bulk so only the tail reaches that tier. Leave it.

---

## Register of deeds — the current, corrected picture

This was wrong until 2026-08-12 and the correction matters.

### Two platforms, not one

| | The Lookup | Online Record System |
|---|---|---|
| entry | `index.php?Accept=Accept` | `NameSearch.php?Accept=Accept` |
| search | `content.php` (**GET**) | `NamePick.php` → `NameDisplay.php` (POST) |
| amount in index | no | **yes** |
| counties | clay, haywood, yancey (NC) | 8 SC |
| reader | `enrichment_rod_lookup.py` | `enrichment_rod_name_index.py` |

A previous commit recorded **12 counties on one platform**. Nine of them run the
SC platform and return **404 with a 16-byte body** to the Lookup reader, which
reads as "county has no records". Georgetown — the only one of the twelve with
board coverage (409 leads) — was among the nine, so that enricher enriched
nothing. All twelve answered HTTP 200 to the accept step.

### Wrong-state hosts — a standing trap

`<county>deeds.com` never states its state and county names repeat:

- **hendersondeeds.com is Henderson County KENTUCKY**
- **wilsondeeds.com is Wilson County TENNESSEE**

Both were one step from adoption as NC sources on pattern match alone. Both are
now absent from `COUNTY_SYSTEMS_REGISTRY.md` entirely.

The guard took three passes to actually work, which is worth knowing before
touching it:

1. comparing NC against SC only missed both of them (one says Kentucky, the
   other Tennessee). It now checks all 50 state names, plus vendor asset paths
   — `hendersondeeds.com` names no state in prose but loads CSS from
   `/assets/css/ky/henderson/`.
2. rejecting the domain was not enough: the sweep then found
   `search.wilsondeeds.com`, which names no state, and re-adopted it. Hence
   `KNOWN_WRONG_STATE`, matched on registrable domain so subdomains are covered.
3. **13 rows are still marked `unverified`.** That is the honest state, not a
   failure — a shared county name on a page that says nothing. Hand-check
   before using any of them; silence must never read as a pass.

### What is open

- **`counties_nc.wnc_rod_foreclosure_starts`** (NEW, working): substitutions of
  trustee in **Clay, Haywood, Yancey NC** — three core counties that held zero
  leads. In NC an `S/T` is what *starts* a power-of-sale foreclosure, recorded
  before the notice of hearing reaches the clerk, so every other NC foreclosure
  source here is downstream of it. Validated live: 3 leads in a 4-day window.
- **8 SC counties**, name lookup only. Bulk date-range works on **Barnwell and
  Georgetown only**; the other five return the head of the whole index (exactly
  2000 parties for any window, including one day) so `bulk_by_date` refuses them.
  Both working counties are outside the core footprint, so the capability is
  built and documented but not wired as a lead source.

### Traps that look like success

- **One document is many rows.** The index emits a row per party and batching
  repeats a document once per batch. A raw 3-day Haywood window is **8,528 rows
  and 133 documents**. Dedupe on (date, book, type).
- **The pick list caps at 1000.** Haywood returned exactly 1000 parties for 21
  days vs 385 for 3. `bulk_by_date` halves a capped window and reads both halves.
- **The lead is the natural-person GRANTOR.** Servicer, lender and two trustees
  are all parties to the same instrument; without filtering, the lead reads
  "U.S. BANK TRUST, NATIONAL ASSOCIATION".

### Closed dead ends — do not re-attempt

- **`received_from`** on The Lookup: eight parameter variants, all 0 bytes.
- **Permitium** (18 NC counties): an ordering counter for certified copies. No
  name index, no date search. Counting it as coverage inflates recorders by 40%.
- **Bertie NC**: 2,617-byte disclaimer loop, still walled.

Full derivation: [`ROD_PORTAL_ACCESS.md`](ROD_PORTAL_ACCESS.md).

---

## Do next, in order

1. **Time a full run** now that both unbounded phases are capped. Expect
   roughly 7 hours rather than 23. If it is still long, get the timeline the
   same way: `grep -oE '\[2026-[0-9-]+ [0-9:]+\]' <log> | uniq -c` and look for
   the silent gaps, not the noisy parts.
2. **Mark the walled sources dormant.** Tyler NC portal, SC PublicIndex and
   fastpeoplesearch are known permanent walls but still get retried every run.
   Enrichers have no `dormant` flag the way scrapers do; that is the gap.
3. **Wire `wnc_rod_foreclosure_starts` into a scheduled run** and confirm its
   leads survive a board merge.
4. **York SC** date-window behaviour is *undetermined*, not walled — it timed
   out repeatedly on a 470 KB page. Retry with a longer timeout.
5. **15 bespoke recorder platforms** still unclassified: alamance, beaufort
   NC+SC, cumberland, gates, guilford, henderson, lincoln, montgomery, orange,
   perquimans, warren, wilson, chester SC. Beaufort SC = Tyler, Wilson =
   TitleSearcher (paid).
6. **104 counties** have no recorder located by pattern. A miss is recorded as
   "not found", never "does not exist".
7. **`americanlandrecords.com`** (Anderson SC recorder) unmapped.
8. SC court URL patterns absent from the registry (NC's 100 are exact).

---

## Reference

| doc | what |
|---|---|
| `ROD_PORTAL_ACCESS.md` | both recorder platforms, full request recipes |
| `SOURCE_REGISTER.md` | every source with URL, gate, cost, cadence |
| `COUNTY_SYSTEMS_REGISTRY.md` | 146 counties × 4 systems, accessibility recorded not filtered |
| `OPERATIONS.md` | how to run the engine |
| `gap_ledger.md` | what cannot be done and why |
| `path_to_100.md` | costed blueprint; 3 hard walls |

## Scripts worth knowing

| script | what |
|---|---|
| `board_selfcheck.py` | 9 invariants, exit 1 on breach, plus a movement report |
| `recompute_valuation.py` | 40-second offline valuation recompute |
| `build_county_registry.py` | 146-county system sweep |
| `discover_linked_systems.py` | crawls county sites for systems we do not use |
