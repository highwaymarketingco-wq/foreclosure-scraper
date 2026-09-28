# Document / image / PDF extraction completeness audit, 2026-09-23

Read-only audit of the full run published at `logs/local-run-20260922T111425.log` (started
2026-09-22T11:14:25, exit at 2026-09-23T04:50:48, elapsed 1056 minutes, 192,805 rows, board written
per `docs/board.manifest.json` at 2026-09-23T08:47:16Z). Scope: is photo condition grading (vision)
working, are documents/PDFs/spreadsheets that carry house information actually pulled and read, and
is any of that landing on the board or being silently dropped.

Method: the run log was streamed with `grep`/`python` line-by-line, never loaded whole (38.5 MB,
147,623 lines). The live board was streamed read-only via
`from foreclosure_scraper.board_stream import iter_board_rows` in 2 passes (counters and small
samples only, no `list()` of the board, no `load_board`, no write). No scraper or board-writer ran.
Code was read, not executed, beyond `.venv/bin/python` running the two streaming scripts above.

## Executive summary

- **Vision condition grading works, but is easy to mistake for complete.** `raw.condition_tier` is
  populated on **192,805 of 192,805 rows (100%)** — but only **10,559 of those (5.5% of the board)**
  are an actual vision-model grade (`condition_source` starting `vision-`). The other **182,246 rows
  (94.5%)** carry a generic fallback (`enrichment_comps.py:695-738`, `_condition_tier`: keyword match,
  else an age-bucket default, else the literal string `"cosmetic"` — "safe middle") that
  `enrichment_comps.py:807-808` writes onto **every** listing unconditionally, before vision ever
  runs. The two fields look identical on the board (`condition_tier: "cosmetic"`) unless a reader
  also checks `condition_source`.
- Of the rows that actually **have** a usable photo (26,423 of 192,805, 13.7% — this is almost
  certainly the "~13%" figure the historical coverage note refers to, and it measures **photo
  availability**, not grading completion), only 10,559 (39.9%) have ever been vision-graded; 15,864
  (60.1%) have a real photo sitting unused and still show the generic default.
- This run's own vision pass scored 494 new listings (385 + 109 across two passes) at a real cost of
  $0.128 — a tiny fraction of the 15,864-row backlog. The first pass stopped early
  (`unscored_remaining=1367`) on the exact failure mode the 2026-09-21 repair added a guard for
  (100 consecutive photo-download failures, `stop_reason: "image_fetch_failing"`) — the repair is
  working (it stopped gracefully and kept the queue instead of silently draining it), but the
  underlying network flakiness that triggers it recurred on this run.
- **Document/PDF OCR (`enrichment_doc_ocr.py`) is not budget-starved or provider-broken.** `targets:
  31` against `aggregate_leads: 8955` is a **queue-composition fact, not a bug**: of the 8,986 board
  rows that carry any document URL at all (4.7% of the board), only 31 point at a document unique to
  that lead; the other 8,955 (99.65%) share just 14 URLs — county tax-roster / sale-list PDFs — which
  by design (`DOC_OCR_MAX_SHARE = 3`, `enrichment_doc_ocr.py:111`) are never OCR'd per-lead. They go
  through a cheaper "read once, match this lead's own row" path instead
  (`_row_backfill_from_aggregate`, `enrichment_doc_ocr.py:543-592`). That path is real but nearly
  non-functional at scale: 12 of 14 shared docs were fetched and parsed, but only **2 of 8,955** leads
  (0.02%) actually got a field filled from it, and it can only ever fill one field
  (`street_address`).
- **Deed-of-trust OCR (`enrichment_dot_ocr.py`) produced zero visibility this run.** It is wired into
  `main.py:2684`, but wrapped in a 900-second wall-clock cap (`main.py:76-88 _await_capped`,
  `default_s=900`) that is **half** the enricher's own internal budget
  (`FORECLOSURE_DOT_OCR_BUDGET_S=1800` + 120s grace, `enrichment_dot_ocr.py:409-410,645-651`). The
  outer cap always fires first, `asyncio.wait_for` cancels the coroutine mid-flight, and it never
  reaches its own `log.info("dot_ocr.done", ...)` line — so this run has **zero** stats on what it
  did in those 900 seconds (searched / image_ok / loan_found are all unknown). Board-wide,
  `raw.dot_ocr` sits on 23 of 192,805 rows (cumulative across every run to date).
- **The three xlsx sources are landing real data, not empty fields.** Charleston tax-sale xlsx (121
  rows), Horry delinquent xlsx (2,235 rows) and Rutherford wildfire tax (499 rows) all populate
  owner/parcel/amount at 94-100% where the source sheet actually carries that fact. The fields that
  read 0% (Horry `opening_bid`/`sale_date`, Rutherford `opening_bid`/`sale_date`) are 0% **because the
  source spreadsheet has no such column** (documented in each scraper's own comments), not because
  the scraper dropped something it saw. Rutherford `street_address` (18%) and `parcel_id` (68.7%) are
  the genuine partial-coverage items, and part of the low street-address rate is a deliberate safety
  guard against geocoding a "house number 0" lot onto the road centroid.
- **One dead code path confirmed**: `enrichment_redfin_datacenter.py` (ZIP-level Redfin market
  stats) is fully built but is called only from `scripts/enrich_board.py`, never from `main.py` —
  it does not run as part of any scheduled or full run.
- **Write-only signals, re-checked against the 2026-09-21 audit's F11/F17**: `storm_damage` and
  `bankruptcy_stay` are **now read** by the scorer — commit `ef8c60e` ("Scoring: evidence classes,
  lifecycle dates, foreclosure lane, evidenced equity (audit F2-F19)", 2026-09-21 15:08, before this
  run started) added both. `court_bid` and `nc_case_status` are **still write-only**: zero matches in
  `distress_score.py`, `enrichment_lead_signals.py`, or `docs/dashboard.js`.
- **New finding this session**: a second, separate "phone" payload (`docs/listings_slim.json.gz`,
  written by `_emit_slim`, `web_artifact.py:1999`) silently drops `condition_tier` on all 192,805
  rows, `amount_owed` on 113,996, `comps` on 80,504, and `owner_email` on 74,908 — logged every
  publish, including this run, by the code's own diagnostic
  (`web_artifact.py:1958-1996, event "web_artifact.slim_dropped_keys"`, note: *"on the board but NOT
  in the slim payload — intended?"*). This is separate from the main board
  (`docs/listings.json.gz`/parts) that `board_stream.py` and (per its own comments)
  `dashboard.js`'s full-board loader read, which does carry `condition_tier`. Whether the browser
  dashboard's own lean-parsing path (`dashboard.js:422 _LEAN_RAW`, which mirrors `_SLIM_RAW` and also
  excludes `condition_tier`) ever gets exercised for on-screen display was not resolved — worth a
  narrow follow-up, not asserted here as a live-dashboard bug.

---

## 1. Photo / vision condition grading

### 1a. What this run did (from the log)

Two vision passes were logged (single call site, `main.py:2181`; the mechanism for two separate
`vision.start`/`vision.done` pairs in one process was not traced further — both carry real
`backend_stats` and are consistent with each other, so both are reported as observed):

| | Pass 1 (03:20:04–03:42:59) | Pass 2 (04:24:14–04:31:24) |
|---|---|---|
| `target_count` | 2,500 (of_total 192,829; hot 25, warm 2,475) | 118 (of_total 159) |
| `scored` | 385 | 109 |
| `ungraded` | 0 | 8 |
| `unscored_remaining` | **1,367** | 0 |
| `no_image` | 748 | 0 |
| `stop_reason` | `image_fetch_failing: 100 rows in a row had no downloadable photo (network down?)` | null (ran to completion) |
| `by_backend` | groq 11, gemini 152, nvidia:ising 145, cloudflare 61, nvidia:nemotron-omni 5, nvidia:muse 11 | cloudflare 15, gemini 49, nvidia:ising 38, nvidia:nemotron-omni 4, groq 1, nvidia:muse 2 |
| `elapsed_s` / cost | 1,375s / $0.0908 | 431s / $0.0372 |

Combined: **494 listings freshly graded this run**, $0.128 total. Pass 1's stop is the exact guard
`docs/vision_repair_2026-09-21.md` added (`VISION_FETCH_STOP_AFTER=100`,
`enrichment_vision.py:1962-1965,2118`): it stopped gracefully and preserved the 1,367-row queue for
next time rather than silently draining it (the pre-repair failure mode). The pool itself was
healthy — `vision.pool_built` shows 51 backends registered both times, matching the repaired
roster in the repair doc. `vision.backend_retired` fired 52 times and `vision.backend_banned` 11
times over the run (expected churn from the half-open circuit breaker, not a regression).

### 1b. Live-board coverage (streamed, 192,805 rows)

`has_photo` = `raw.images.real|street|aerial` truthy, or `raw.zillow.photos|photo` truthy — the exact
set `enrichment_vision.py:341-344,347-374` (`_select_image_urls`) uses to decide whether a listing is
even eligible to be sent to a vision model.

| | count | % of board |
|---|---:|---:|
| Rows with a usable photo (`has_photo`) | 26,423 | 13.7% |
| Rows with **no** usable photo | 166,382 | 86.3% |
| Rows with `condition_tier` populated at all | 192,805 | 100% |
| Rows with a **real vision grade** (`condition_source` starts `vision-`) | 10,559 | 5.5% |
| — of which `vision-HIGH` | 6,888 | |
| — of which `vision-MEDIUM` | 3,671 | |
| — of which `cama` (assessor-condition seed, not vision) | 2 | |

Cross-tab (the number that actually answers "of the rows that COULD be photo-graded, what fraction
actually are"):

| | has photo | no photo |
|---|---:|---:|
| **Vision-graded** (`condition_source` = vision-*) | **10,559 (39.9% of has-photo)** | 0 |
| **Generic default only** (`enrichment_comps.py` fallback, never vision-graded) | 15,864 (60.1% of has-photo) | 166,382 (100% of no-photo) |

So: 60% of the 26,423 photo-bearing rows have a real photo sitting unused, and instead display the
same board-wide default (`condition_tier` value distribution board-wide: `cosmetic` 186,283,
`major` 4,686, `move_in_ready` 1,082, `gut` 754 — a distribution dominated by the fallback's own
age-bucket defaults, not by anything a model looked at).

**Root cause of the 100%-populated-but-5.5%-real gap**: `enrichment_comps.py:807-808` runs for every
listing (`enrich_with_comps`, called at `main.py:2053`, **before** vision at `main.py:2181`) and
unconditionally writes `li.raw["condition_tier"] = tier` where `tier` comes from
`_condition_tier()` (`enrichment_comps.py:695-738`): keyword match in the description, else an
age-bucket table (`DEFAULT_CONDITION_BY_AGE`, `:684-692`), else the literal fallback `"cosmetic"` —
its own comment calls it "safe middle." `comps.done` in this run's log confirms it:
`{"conditions": {"move_in_ready": 1071, "cosmetic": 186344, "major": 4682, "gut": 732}}` at
01:23:10 — essentially the same distribution the board shows now, because vision (which runs after
and does set `condition_source`, `enrichment_vision.py:1827-1834`) only touched 494 more rows this
run. Nothing is silently dropped here — it is silently **faked as a plausible-looking default**,
which is arguably worse for a reader who has no reason to check `condition_source`.

## 2. Document / PDF OCR (`enrichment_doc_ocr.py`)

### 2a. This run's numbers (`doc_ocr.done`, 03:50:30)

```
targets: 31, ocr_ok: 6, backfilled: 6, skipped_budget: 0, no_provider: 0,
aggregate_docs: 14, aggregate_leads: 8955, agg_docs_read: 12, agg_backfilled: 2
```

### 2b. Why targets=31 against aggregate_leads=8955 — exact mechanism, file:line

This is **not** a budget cap (`skipped_budget: 0` — the run never got close to `DOC_OCR_MAX=2500`
candidates or `DOC_OCR_BUDGET_S=2400` seconds, `enrichment_doc_ocr.py:104-105`) and **not** a
provider/key problem (all 9 Gemini keys were present and answering; the only errors logged were 3
transient 503s, `enrichment_doc_ocr.py` `doc_ocr.gemini_error` events, and 2 `item_fail` on
individual documents). It is a **queue-composition split, by design**:

1. `enrich_doc_ocr` (`enrichment_doc_ocr.py:595-687`) first finds every listing carrying a document
   URL in `_DOC_FIELDS` (`:118-122`: `document_url`, `notice_url`, `pdf_url`, `deed_url`, `documents`,
   etc.) that hasn't already been OCR'd — `candidates` at `:609-610`. This run: 31 + 8,955 = **8,986**
   candidates out of 192,805 rows (4.7% of the board carries any document URL at all — up sharply
   from the "5 real targets" the 2026-08-14 note in `docs/extraction_gaps.md:36-44` recorded, because
   the 2026-08-17 document-link harvester (`document_links.py`, wired into 4 scrapers) has since
   populated many more `raw['documents']` URLs).
2. `url_counts = Counter(...)` (`:614-615`) counts how many candidates share the exact same document
   URL. `aggregate = {u for u, c in url_counts.items() if c > DOC_OCR_MAX_SHARE}` (`:616`,
   `DOC_OCR_MAX_SHARE = 3`, `:111`) — any URL referenced by more than 3 leads is judged to be a
   county tax-ad or sale-roster PDF, not a per-property notice (the comment at `:106-111` explains
   why: OCRing a shared roster once per lead burns quota and stamps the top row of the list onto
   every lead that shares it).
3. `targets = [li for li in candidates if _doc_urls(li)[0] not in aggregate]` (`:617`) — **31** leads
   whose document URL is unique-enough (≤3 sharers) go through full per-lead OCR (`_ocr_document`,
   `:308-469`: PDF text layer → Gemini/GitHub/Groq/NVIDIA/Mistral/Claude text fallback, or scanned
   PDF/image → the same provider chain on the image). 6 of 31 (19%) succeeded and all 6 backfilled at
   least one field (`ocr_ok: 6, backfilled: 6`).
4. The other **8,955** leads (99.65% of the 8,986 candidates) reference just **14** distinct shared
   URLs (`aggregate_docs: 14`). Since 2026-08-14 these are no longer discarded outright — each shared
   document is fetched and its text extracted **once** (`agg_map`, `:623-629`; the loop at
   `:657-679`), then every lead sharing it is matched to **its own row** inside that text via
   `_row_backfill_from_aggregate` (`:543-592`): the lead's parcel id / case number / owner name /
   defendant is looked for as a literal substring on each line of the extracted text
   (`_lead_identifiers`, `:531-540`), and only the **one line** that matches is read (deliberately
   line-scoped — a character-window approach was tried and verified to leak the neighbouring row's
   address onto the wrong lead, per the comment at `:561-564`). This run: 12 of the 14 shared docs
   were fetched and had usable text (`agg_docs_read: 12`), but only **2 of 8,955** leads (0.02%)
   actually had their identifier found on a line **and** a plausible street address extracted from
   that line (`agg_backfilled: 2`). `_row_backfill_from_aggregate` can only ever fill one field
   (`street_address`, `:577-586`) — it never touches owner, amount, or sale date even when it hits.

**Verdict**: the 31-vs-8,955 split is intentional routing that correctly avoids a worse failure mode
(stamping one roster row onto thousands of leads). But the intended fallback for those 8,955 leads
is now shown to be almost non-functional in practice — a 0.02% hit rate — which is new information
the log's own summary line does not surface (it reports `agg_docs_read`/`agg_backfilled` but nothing
upstream flags that this is a near-zero yield). This is the single highest-leverage fix identified in
this audit; see the ranked list below.

## 3. Deed-of-trust OCR (`enrichment_dot_ocr.py`) — silently capped this run

Zero `dot_ocr.*` events appear anywhere in the 147,623-line log. The only trace is:

```
113419  {"phase": "dot_ocr", "budget_s": 900, "event": "enrich.time_capped", ...} 05:45:14
113420  {"phase": "dot_ocr", "leads": 192829, "seconds": 901.8, "event": "checkpoint.saved", ...} 06:00:16
```

`enrich_dot_ocr` **is** wired (`main.py:2681-2687`), called as
`await _await_capped(enrich_dot_ocr(enriched), "dot_ocr")` with no `default_s` override, so
`_await_capped` (`main.py:76-88`) applies its default **900-second** `asyncio.wait_for` timeout. The
enricher's own internal wall-clock design is a **1,800-second** budget
(`FORECLOSURE_DOT_OCR_BUDGET_S`, `enrichment_dot_ocr.py:409`) plus a 120-second grace backstop
(`grace_s`, `:645`, wrapping `_all_counties()` in its own `asyncio.wait_for(..., timeout=budget_s +
grace_s)` at `:646-647` — a mechanism the code's own comment at `:632-644` explains was added
specifically so a slow per-county sweep can't run unbounded, citing a 2026-07-31 incident where this
exact enricher spent 13h36m on 25 leads). That internal design is never reached: the **outer** 900s
cap in `main.py` fires first every time, `asyncio.wait_for` cancels the task, and the coroutine never
returns to its own `log.info("dot_ocr.done", **stats)` line (`:654`). Net effect: this enricher ran
for 15 minutes this run and there is **no record of what it accomplished** — not `searched`, not
`image_ok`, not `loan_found`, not `budget_exhausted`. Board-wide (cumulative across every run to
date), `raw.dot_ocr` is present on 23 of 192,805 rows and `raw.loan_amount` on the same 23 — a
negligible amount at the current cadence.

This is a distinct, simpler bug from the doc_ocr queue-composition issue above: a config mismatch
(`main.py:76` default 900s vs. `enrichment_dot_ocr.py:409` internal 1800s+120s) that makes the
outer cap always win and always silence the phase's own accounting.

## 4. Other "fetched but not used" gaps

### 4a. Log-message admissions (grep for dropped/discarded/not used/TODO across this run)

Nothing named itself `discarded`, `not_used`, or `TODO` in this run's log. The `dropped`-adjacent
event names found were mostly ordinary, expected data-quality counters (`comps_dropped_kind_mismatch:
39136` during validation — comps rejected for a property-kind mismatch, `dedup_dropped: 0`,
`redeemed_dropped: 26` on Buncombe tax redemptions, `mortgage_foreclosures_dropped: 8` on a Column
NC feed). One is a genuine, self-flagged extraction gap:

**`web_artifact.slim_dropped_keys`** (`web_artifact.py:1958-1996`), fired once this run at 08:44:28:

```
"note": "on the board but NOT in the slim payload — intended?",
"keys": {"flags": 192805, "is_new": 192805, "condition_tier": 192805, "link_kind": 192805,
         "fema_disaster": 192805, "flood": 150429, "flood_zone": 133405, "amount_owed": 113996,
         "census_demographics": 96130, "market_velocity": 81387, "comps": 80504,
         "eviction_market": 78724, "owner_email": 74908, "first_seen_run": 60135,
         "opportunity_zone": 51458},
"total_dropped": 198
```

This is a **separate artifact** from the main board: `docs/listings_slim.json.gz`, written by
`_emit_slim` (`:1999-2040`) for a "phone"/lightweight client, governed by its own allowlist
(`_SLIM_RAW`, ending `:1751`) that is distinct from `RAW_KEEP` (the gate for the main
`docs/listings.json.gz`/parts board that `board_stream.py` reads, and that this audit's own board
passes confirm **does** carry `condition_tier` on 100% of rows). The diagnostic exists precisely
because the two allowlists have drifted before (the docstring at `:1961-1976` cites a 2026-09-13
incident where `fullmer`, a whole buy-box rank, was invisible on 115,994 slim rows for the same
reason). Today it is flagging `condition_tier`, `amount_owed`, `comps`, and `owner_email` — four
fields a bidder would want — as 0% present in that secondary payload, with the code's own comment
asking "intended?" and not answering it. `dashboard.js:422` (`_LEAN_RAW`) mirrors the same
allowlist and also excludes `condition_tier`; whether the main web dashboard's rendering path ever
actually depends on that lean projection (vs. always reading the full board, which does have the
field — `dashboard.js` comments say the slim file is "a pure speedup, never a dependency") was not
resolved in this audit and would need a rendered-page check, not a code read.

### 4b. F11/F17 re-check (write-only signals from the 2026-09-21 signal-logic audit)

| Signal | 2026-09-21 finding | Status now (re-checked against current code + this run) |
|---|---|---|
| `raw.storm_damage` | written, never read (F11) | **Fixed.** `distress_score.py:155-182,770` now derives a PROPERTY signal from it (`_storm_signal`). Fix landed in commit `ef8c60e` (2026-09-21 15:08:44, before this run started). Board-wide: 1,319 rows carry `raw.storm_damage`. |
| `raw.bankruptcy_stay` | written, never read (F3/F11/F17) | **Fixed.** `distress_score.py:323,603-606` now reads it ("the bankruptcy stay, when one is in force"). Same commit. Board-wide: 234 rows. |
| `raw.court_bid` | written, never read (F17) | **Still write-only.** Zero matches for `court_bid` in `distress_score.py`, `enrichment_lead_signals.py`, or `docs/dashboard.js`. Board-wide: 59 rows carry it. |
| `raw.nc_case_status` | written, never read (F17) | **Still write-only.** Zero matches anywhere in the same three files. Board-wide: 240 rows carry it. |

### 4c. Dead code confirmed

`src/foreclosure_scraper/enrichment_redfin_datacenter.py` (ZIP-level Redfin Data Center market
stats: median sale price, inventory, days-on-market, $/sqft) is fully implemented
(`enrich_redfin_datacenter`, `enrich_batch_redfin_datacenter`, `:112-147`) but its only caller in the
whole repository is `scripts/enrich_board.py`, a standalone script — **not** `main.py`. It does not
run as part of the full run, the daily API refresh, or the daily vision job. Zero `redfin` mentions
appear anywhere in this run's 147,623-line log, confirming it. Not a partial gap — this enricher has
never contributed to the live board via any scheduled process.

## 5. Zillow / comps coverage (Redfin: dead, see 4c)

- **Zillow scraper** (`national/zillow_foreclosures`-class source): `zillow.state_done` fired twice
  this run — NC 289 listings / 8 pages, SC 137 / 4 pages (426 new/refreshed FSBO-foreclosure listings
  found). Separately, `zillow_bulk.state_done` fired twice (bulk photo/spec backfill pass, counts not
  itemized in the grepped event but present and running).
- Board-wide, `raw.zillow` is present on **24,913 of 192,805 rows (12.9%)**, and every one of those
  rows also carries `raw.zillow.photos` or `.photo` — this is the majority feed for the vision
  pipeline's photo pool (`_select_image_urls`'s legacy fallback, `enrichment_vision.py:360-367`).
- **Comps** (`enrichment_comps.py`, HomeHarvest-sourced sold/rent comps): `comps.start` count 192,829,
  `comps.pools_built` 18 counties / 9,235 sold pool rows / 447 rent pool rows,
  `comps.done`: **sold_matched 79,876 (41.4% of the board got at least one like-for-like sold comp)**,
  **rent_matched 20,721 (10.7%)**, but **`backfilled: 97`** — the spec-backfill half of this same pass
  (pulling missing sqft/beds/baths from a matched comp, `_backfill_property_data`) touched only 97 of
  192,829 listings this run. That is a real but low-leverage gap: most listings that are missing
  sqft/beds/baths and would benefit from comp-based backfill are not getting it, though the much
  larger comp-matching function itself (sold/rent pool attachment) is working at scale.
- Board-wide `raw.comps` is present on 80,504 rows via `iter_board_rows` (close to but not identical
  to `comps.done`'s 79,876 `sold_matched` for this run alone, since `raw.comps` persists across runs
  and a small number of prior-run matches can carry forward even when this run didn't re-match them).
  `raw.rent_comps` read as present on 0 rows via the slim board stream — `rent_comps` is a
  `LAZY_DETAIL_KEYS` sidecar field (`web_artifact.py:1580`), stripped from the main published file the
  same way `vision` is, so this reads as 0 from `board_stream` by design, not because rent comps are
  missing; `comps.done`'s own `rent_matched: 20,721` is the trustworthy figure for that.
- **Redfin**: see 4c — built, never wired, zero live contribution.

## 6. Ranked fix list (by estimated lead-count impact)

1. **Doc-OCR aggregate path yield (0.02%, 8,955 leads affected).** `_row_backfill_from_aggregate`
   (`enrichment_doc_ocr.py:543-592`) only fills one field and only on an exact-substring line match.
   Highest-leverage fix identified: after finding the matching line, also parse an owner name and a
   dollar amount off it (the same regex classes `_ADDR_IN_ROW` already uses for address could be
   paired with a name/amount extractor), and loosen the match to tolerate the whitespace/punctuation
   drift a county PDF-to-text extraction typically introduces (currently an exact case-insensitive
   substring). Even a modest yield improvement here (e.g. 10-20%) would beat the entire rest of
   doc_ocr's output by 100-200x, because 8,955 leads already have the document identified and
   fetched — the entire cost is sitting in inventory, unused.
2. **Vision backlog on already-available photos (15,864 leads, 60% of photo-eligible rows).** No
   code bug — this is a throughput/cadence gap: 494 scored this run against a 15,864 backlog. At
   this run's pace it would take ~32 more full/daily vision passes to clear the existing backlog
   alone (before new photo-bearing leads arrive). The 2026-09-21 repair fixed the pool; the remaining
   lever is running vision more often (the daily 09:30 job) or raising `VISION_MAX_LISTINGS`/wall
   clock, not a further code fix.
3. **dot_ocr's outer cap silences its own accounting (900s vs. its designed 1800s+120s, all leads
   affected indirectly via unmonitored equity data).** One-line fix:
   `_await_capped(enrich_dot_ocr(enriched), "dot_ocr", default_s=2000)` at `main.py:2684` (or read
   `FORECLOSURE_DOT_OCR_BUDGET_S` there instead of hard-coding 900) so the enricher's own graceful
   stop and stats logging get a chance to run before the outer wrapper does. This does not by itself
   raise dot_ocr's yield (that is gated on `DOC_IMAGE_COUNTIES` robots-clean coverage, a separate,
   already-documented wall) but it restores visibility into what the phase is doing.
4. **`condition_tier` / `condition_source` ambiguity (182,246 rows show a value with no way to tell
   it's a default without a second field lookup).** Not a data-loss bug, but a trust/labeling gap: a
   dashboard or export reading `condition_tier` alone cannot distinguish a vision-graded "cosmetic"
   from the age-bucket default "cosmetic". Cheapest fix: rename or tag the fallback's writes (e.g.
   `condition_source: "default-age"` is already partially there for `cama`; extend the same labelling
   to the `enrichment_comps.py:807-808` default path, which currently writes no `condition_source` at
   all) so every consumer can filter on confidence the way `condition_source` already lets them for
   vision.
5. **`web_artifact.slim_dropped_keys` (up to 192,805 rows, only for consumers of
   `listings_slim.json.gz`).** Decide, per the code's own open question, whether `condition_tier`,
   `amount_owed`, `comps`, and `owner_email` belong in `_SLIM_RAW`
   (`web_artifact.py:1700-1751`)/`_LEAN_RAW` (`dashboard.js:422`) and add them if so — currently
   unresolved and re-logged every publish.
6. **`court_bid` / `nc_case_status` still write-only (59 and 240 rows respectively).** Small in count,
   already scoped with a fix in the 2026-09-21 signal-logic audit (F17); lower priority than the
   above purely on lead-count, but cheap once someone is already in `distress_score.py`.
7. **Redfin market-stats enricher fully dead (0 rows, but 0 cost to leave alone).** Either wire
   `enrich_batch_redfin_datacenter` into `main.py` alongside the other market-context enrichers, or
   remove it from the "capabilities" list if ZIP-level Redfin stats are no longer wanted — currently
   it is neither.
8. **Comp-based spec backfill (97 of 192,829 listings, low volume).** Lowest priority of the group;
   the comp-matching itself (79,876/20,721) is healthy, only the secondary spec-fill inside the same
   pass is thin. Not investigated further in this pass — would need its own read of
   `_backfill_property_data`'s match criteria to say why so few listings qualify.

## Answering the user's framing directly

- **Is vision/OCR/spreadsheet extraction working as intended?** Partially, and unevenly. Vision
  grading itself works correctly when it runs (the 2026-09-21 repair is holding — pool healthy, 51
  backends, graceful stop on a real network hiccup) but the pipeline creates the appearance of 100%
  coverage via an unrelated default-fill enricher, when true model-graded coverage is 5.5% of the
  board. Doc OCR's targeted per-lead path works correctly (6/31 this run, budget and providers both
  fine); its aggregate/roster path is functioning as designed but nearly worthless in practice
  (0.02% yield on 99.65% of doc-bearing leads). Deed-of-trust OCR is misconfigured (a timeout
  mismatch) and produced no visibility this run. The three xlsx spreadsheet sources are working
  correctly — real owner/parcel/amount values are landing on the board at 94-100% fill for every
  field the source sheet actually contains.
- **What fraction of available house information is actually being captured?** For photos: 13.7% of
  the board has a photo available at all, and of that, 39.9% has actually been graded (5.5% of the
  whole board). For documents: 4.7% of the board has a document URL captured at all; of that, the
  31 unique-document leads are handled properly and the 8,955 shared-roster leads are handled at a
  0.02% success rate. For the three xlsx sources: essentially 100% of what the source spreadsheet
  contains is captured (the "gaps" are source-side absence of a column, documented in the scraper
  code, not scraper failure).
- **Top gaps, in order**: (1) doc_ocr's aggregate-roster path yields 0.02% on 8,955 leads that are
  already fetched and identified — the single highest-leverage, lowest-cost fix; (2) a 15,864-row
  vision backlog on leads that already have a usable photo, a cadence problem, not a code problem;
  (3) dot_ocr's outer timeout silencing its own accounting every run; (4) the condition_tier
  default-vs-real-grade ambiguity; (5) the separate phone/lean payload silently dropping
  `condition_tier`/`amount_owed`/`comps`/`owner_email`.
