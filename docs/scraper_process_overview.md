# Motivated-Seller Engine — Start-to-Finish Process Overview

*Audience: the operator. This is the whole machine end to end, in plain English, so you can run it and describe it to a partner. Each stage has an "Under the hood" line with the real file/function names if someone technical wants to trace it.*

---

## 1. What it is + the mission

This is a **property-keyed motivated-seller engine**, not just a foreclosure list. The mission is simple: find people who have a reason to sell a property cheaply, tie that reason to a specific parcel, figure out what the property is worth and how to reach the owner, then rank the whole board so you work the best leads first.

**Property-keyed** is the load-bearing idea. Every lead is anchored to a real parcel (a physical property with a tax ID), not to a name floating in a court docket. That means a foreclosure filing and a tax-sale listing on the *same house* stack into one stronger lead instead of two weak ones, and every downstream number (value, equity, owner mailing address) hangs off that one parcel.

**Foreclosure is one lane among many.** The engine treats every kind of distress as a *lead source* feeding the same backbone:

- **Foreclosure** — trustee sales, lis pendens (the lawsuit that starts a foreclosure), master-in-equity rosters.
- **Tax delinquency** — county delinquent-tax and forfeited-land (FLC) lists.
- **Probate / death** — obituaries and estate filings surface heirs who inherited a house they don't want.
- **Eviction pressure** — landlords under stress (used as a market signal, see below).
- **Partition / divorce** — co-owners or splitting spouses forced to sell.
- **Life events** — elderly owners, incarceration, bankruptcy, storm damage (Helene).

**Footprint:** an **18-county corridor** — Western North Carolina + Upstate South Carolina, the band west of Charlotte.

- **SC (7):** Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens
- **NC (11):** Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke

Greenville, Mecklenburg, Madison, and all eastern/coastal NC counties are deliberately **out of scope** — some coastal scrapers exist, but their rows get filtered out unless an oceanfront-override applies.

**Free + public-only** is a hard rule. Everything the machine pulls on its own is free public data reached through normal public search. No paid data brokers, no defeating CAPTCHAs, no logins. Where a wall exists, a human does a compliant manual save instead (Section 4).

> **Under the hood:** footprint defined in `src/foreclosure_scraper/config.py` — `SC_COUNTIES` + `NC_COUNTIES` = `ALL_COUNTIES`, gated by `in_scope()` with a `SCOPE_DENY_COUNTIES` override set.

---

## 2. The big picture

```
                           ┌─────────────────────────────────────────────────┐
                           │  MANUAL COURT-EXPORT LANE (human, compliant)     │
                           │  SC PublicIndex / NC eCourts pages saved by hand │
                           │        │ offline parser                          │
                           └────────┼─────────────────────────────────────────┘
                                    │  (net-new cases only)
                                    ▼
 ┌──────────┐   ┌────────┐   ┌────────────┐   ┌────────────┐   ┌─────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐
 │ SOURCES  │──▶│ DEDUPE │──▶│  PROPERTY  │──▶│ ENRICHMENT │──▶│ SCORING │──▶│  BOARD   │──▶│ DASHBOARD │──▶│ OUTREACH │
 │ ~106     │   │  #1    │   │ RESOLUTION │   │ contact +  │   │ distress│   │ ARTIFACT │   │ (web map/ │   │ mail /   │
 │ scrapers │   │        │   │ name/parcel│   │ distress + │   │ grade + │   │ slim +   │   │  table /  │   │ call     │
 │ 21 cats  │   │        │   │ → addr/TMS │   │ valuation  │   │ ARV +   │   │ sidecar  │   │  filters) │   │ list     │
 │          │   │        │   │ /value/GIS │   │ (comps)    │   │ equity +│   │ JSON     │   │           │   │          │
 └──────────┘   └────────┘   └─────┬──────┘   └────────────┘   │ strategy│   └──────────┘   └───────────┘   └──────────┘
                                   │                           └─────────┘
                                   │  DEDUPE #2 (after parcel IDs exist)
                                   └──────────────────────────────────────▶ (cross-source dups finally merge)
```

Read it left to right: **Sources** pull raw listings → **Dedupe** collapses obvious duplicates → **Property resolution** turns names/parcels into real addresses and tax values → **Enrichment** layers on owner contact, liens/distress, and a valuation → **Scoring** grades each lead → the **Board artifact** is the single output file → the **Dashboard** is what you look at → **Outreach** is the mail/call list you act on. The **manual court lane** feeds in from the top: a human saves court pages the robots aren't allowed to scrape, and an offline parser merges those cases onto the same board.

---

## 3. Stage by stage, in run order

### (a) Sources — where leads come from

**~106 individual scrapers** across **21 categories**. Each one is a small self-contained module that knows how to pull one website or feed, normalize the rows, and tag every row with its own source ID so you always know where a lead came from.

The big categories, by count:

| Category | Count | What it is |
|---|---:|---|
| county_tax | 26 | Delinquent-tax + forfeited-land (FLC) lists |
| law_firm | 12 | Foreclosure trustee / substitute-trustee firms (Brock & Scott, Hutchens, Bell Carrington, etc.) |
| county_court | 11 | Master-in-equity rosters, lis-pendens, court dockets |
| national_aggregator | 10 | Zillow/Realtor/Trulia foreclosure feeds, bankruptcy |
| newspaper_legal | 9 | Legal-notice sections (Shelby Star, Daily Courier, Column) |
| national_auction | 5 | Auction.com, Bid4Assets, Hubzu, Xome, ServiceLink |
| motivated_seller | 5 | Obituaries, funeral RSS, elderly, Helene-damaged |
| register_of_deeds | 4 | Recorded deeds/trustee documents (ROD) |
| federal_reo | 4 | Fannie, Freddie, HUD, VA/USDA bank-owned |
| *(others)* | — | multifamily, probate, city surplus, state liens, etc. |

Each scraper carries a few important flags: a **timeout** (soft cap so one slow site can't hang the run), an **expected-minimum count** (a regression floor — if it usually returns 40 and today returns 3, that's flagged), a **disabled** switch (7 scrapers ship OFF because their target is walled — the code stays in place per policy, it just reports "DORMANT"), and **seasonal gating** (SC annual tax lists only run in-season).

The key design guarantee: **a scraper never crashes the run and a zero-count is never ambiguous.** Every source reports one of: `OK`, `ZERO_RESULT`, `TIMEOUT`, `BLOCKED` (a 403/CAPTCHA/WAF wall), `ERROR` (a real code bug), or `DORMANT` (intentionally off). So when a source returns nothing, you know *why* — blocked vs. genuinely empty vs. off-season.

> **Under the hood:** every source subclasses `BaseScraper` (`base_scraper.py`) and implements `fetch()`; `safe_run()` wraps it with the timeout + outcome taxonomy. The registry `scrapers/_registry.py` auto-discovers all concrete scrapers; `all_scrapers()` instantiates them.

### (b) A scheduled run — the orchestration lifecycle

When a run fires, one program (`main.py`, function `run()`) walks the whole pipeline top to bottom. The shape of it:

1. **Fetch everything at once.** All ~106 sources run **in parallel** (bounded so we don't hammer the network), each isolated so a failure can't take down its neighbors. Results are folded into one big raw list, with per-source counts and outcomes recorded.
2. **Lis-pendens discovery** runs as its own pass — an early-warning sweep for brand-new foreclosure lawsuits that haven't hit a trustee calendar yet.
3. **Carryover + partition + filter.** A source that returned solid numbers last week but zero this week gets its prior leads replayed (marked `stale`) so a one-off outage doesn't blank the board. Past foreclosure *sales* (last 180 days) are split off into a separate "sold pool" used later for comps. Everything else is scope-filtered (in-footprint only), active-only, and luxury-flip-dropped.
4. **Dedupe #1** — first duplicate collapse (mostly by URL at this point, because parcel IDs don't exist yet).
5. **Property resolution + enrichment** — the long middle, stages (c) and (d) below. These run **sequentially and in a specific order**, because the order is load-bearing: address before parcel, parcel before value, value before the financial calc.
6. **Dedupe #2** — reruns *after* parcels/addresses exist, so the same house pulled from three different sources finally merges into one lead.
7. **Scoring** — stage (e).
8. **Publish** — stage (f): write the board artifact, then optionally push to a Google Sheet and send a digest email.

Throughout, the run is defended by **wall-clock caps** (slow phases like court records get a hard time budget, then the run *proceeds* with what it has rather than discarding the tail), **volume caps** (e.g. only the top ~600 leads get expensive photo-vision analysis), and **error isolation** (nearly every step is wrapped so one crash logs and continues — the final artifact write always happens). There are also **off-switches** (environment gates) so any expensive or flaky enricher can be turned off for a given run without touching code.

> **Under the hood:** `main.py::run()` (entry ~line 576), `asyncio.gather` under `Semaphore(cfg.parallel_scrapers)` for fetch; enrichers `await`ed one at a time; timeout guards via `asyncio.wait_for(...)` logging `*_time_capped` and continuing.

### (c) Property resolution — turning a name or parcel into a real property

Most raw leads arrive incomplete: a court case is just a name and a case number; a legal notice might be a defendant and nothing else. Resolution is the backbone that converts those into a real property.

The chain: take whatever we have (an address fragment, a parcel ID, a defendant name, or just a case number), and query the **county GIS parcel systems** — 25 dedicated county map servers, plus statewide fallbacks (NC OneMap for all NC counties, SCDOT for all SC counties). From those we pull the **parcel ID / TMS** (the property's tax key), the **owner name**, the **situs address** (where the property physically is), and the **assessor's tax/market value** (which becomes the raw material for the value estimate later).

For SC lis-pendens leads specifically, the case number itself encodes the county (a "04" prefix means Anderson, by venue statute), so the resolver decodes the correct county, re-tags the lead if it was wrong, then searches that county's parcel layer by the defendant's surname — and only commits an address on a **confident** name match (fiduciary defendants like executors/trustees never get an address auto-committed, to avoid pinning a lead to the wrong house).

If GIS can't place it, a geocoder (Nominatim, free) turns the address into lat/long, and a reverse point-in-parcel lookup recovers the parcel ID from the coordinates.

> **Under the hood:** `enrichment_owner_mailing.py` (the contactability + parcel spine, `COUNTY_GIS` layer map), `enrichment_lis_pendens_resolver.py` (SC case-number → county → surname match), plus `enrichment_geocode.py`, `enrichment_parcel_reverse_geo.py`, `enrichment_situs_address.py`.

### (d) Enrichment — contact, distress, and valuation

Once a lead is a real property, three families of enrichers pile data onto it, in this order.

**Contact — how do we reach the owner?**
- **Owner mailing address** comes from the same GIS parcel pull. Critically, this reveals **absentee** owners: when the mailing address differs from the property address (especially out-of-state), the owner doesn't live there — a classic motivated-seller signal.
- For **entity-owned** NC properties (an LLC or Inc owns the house), a free NC Secretary of State lookup pulls the **registered agent and officers**, so a faceless LLC becomes a mailable human without paying for skip-trace.
- Supporting: voter-file phone matching, owner-name promotion, skip-trace scaffolding.

**Distress / liens — how motivated, and what debt is attached?**
- **Delinquent tax dollars.** The tax-list scrapers give you the parcel and owner but *not the amount owed*. A separate step hits the county treasurer payment portals (qPayBill, verified for several SC counties) to fill in the actual delinquent-tax **balance**.
- **Lis pendens** (the active foreclosure lawsuit) and its filing details.
- **Eviction market pressure** — a county-level eviction-filing *rate* attached as market context (not a per-case lead), so you know which counties are hot.
- **Lien stack** — an owner's *other* recorded debts (state tax liens especially) get attached to the property so the equity math can subtract them. State tax liens are "super-priority" — they survive any sale — so they always come off the value.
- **Photo condition (Vision)** — up to 7 property photos go to a vision model with a flipper-trained prompt, which grades condition (move-in / cosmetic / major / gut) and estimates rehab cost per square foot.
- **Document OCR** — scanned legal notices and deeds get read to pull the buried owner name, address, and dollar amounts that county systems left blank.

**Valuation — what's it worth?** This is the comps → value pipeline:
- **Recorded-sale comps** (highest confidence) — actual arms-length sales near the property, pulled from county GIS.
- **Scraped comps** — recently sold listings via HomeHarvest (free, Realtor.com public data), strictly matched to the subject (same property type, within a radius, similar sqft/beds/age) and price-adjusted toward the subject.
- These feed the ARV (After-Repair Value) estimate in the next stage.

> **Under the hood:** `enrichment_owner_mailing.py`, `enrichment_sos_agent.py`, `enrichment_qpaybill_tax.py`, `enrichment_eviction_market.py`, `enrichment_lien_stack.py`, `enrichment_vision.py`, `enrichment_doc_ocr.py`; comps in `enrichment_recorded_comps.py` + `enrichment_comps.py`. Vision uses a free-first backend pool (Gemini/GitHub/Groq/etc.), paid only as last resort.

### (e) Scoring — how a lead gets graded

Four headline numbers get computed for every lead.

**ARV (After-Repair Value)** — a waterfall that uses the best comp data available: recorded sales first, then scraped comps, then a Zillow estimate, then tax-value × 1.25, then (worst case) the opening bid × 2.4. Whatever tier it lands on, the number gets sanity-floored/capped and adjusted for photo-assessed condition, and stamped with a confidence (HIGH / MEDIUM / LOW) so you know how much to trust it.

**Equity** — `ARV − estimated mortgage payoff − senior liens`. The payoff is estimated from the recorded deed-of-trust amount amortized to today, or the foreclosure judgment/opening-bid as a proxy. This is *the* flipper number: high equity = room to make an offer.

**Distress grade (HOT / WARM / COLD)** — this is where property-keying pays off. Signals are grouped by parcel and bucketed into 5 categories (Financial / Sales / Legal / Life-event / Property). A property with a foreclosure *and* a tax sale *and* a probate filing has a **stack of 3** distinct categories — much hotter than one signal three times. The score is the best-weighted signal per category, plus equity and contactability bonuses (absentee, out-of-state), minus a penalty if a senior lien would survive the sale (a title-wipeout risk). The tiers:
- **HOT** = stacked ≥2 categories **AND** decent equity **AND** the owner is actually mailable **AND** no surviving-senior-debt risk. (Contactability is a hard gate — an ungrabbable lead can't be HOT.)
- **WARM** = a meaningful stack or score with some equity, or an absentee owner with at least one signal.
- **COLD** = everything else.

**Strategy fit** — a tag for the play you'd run each lead as: **WHOLESALE** (equity-rich + distressed), **LAND_WHOLESALE** (vacant land), **SUBJECT_TO** (low-equity foreclosure — take over payments), **FIX_FLIP** (rough condition + some equity), **BUY_HOLD**, **GATOR**. Each tag comes with a one-line reason.

> **Under the hood:** `valuation/calc.py` (ARV waterfall + max-bid math), `valuation/grading.py` (A–F dimensional grade), `enrichment_equity.py`, `distress_score.py::score_board()` (HOT/WARM/COLD), `enrichment_strategy_fit.py`. A standing backtest harness (`scripts/backtest_arv.py`) checks ARV accuracy against real recorded sale prices.

### (f) Publish — the board artifact

The graded leads are written to **one output file the whole system reads from**: `docs/listings.json`. It's written in two pieces for speed:
- **The slim board** (`listings.json`) — every lead with the fields the map/table/cards actually need. Trimmed on purpose so the dashboard loads fast.
- **The detail sidecar** (`listings_detail.json`) — the heavy nested stuff (full comps arrays, vision analysis) split out and loaded *only* when you open a lead's detail panel. The two files are **index-aligned**: lead #5 in the board matches detail #5 in the sidecar.
- **Run metadata** (`run_meta.json`) — timestamp, totals, per-source status, regressions, errors.

Anyone who wants to add leads to the board later (the manual court lane, daily refreshers) must go through the proper **round-trip loader** so the heavy detail gets merged back in and isn't silently dropped.

> **Under the hood:** `web_artifact.py::write_artifact()` writes the three files; `LAZY_DETAIL_KEYS` is the split list; `load_board()` is the required read-back entry point for every incremental writer. This is the **one-board-writer** rule — only these functions touch the artifact.

### (g) Dashboard — what you see

The board is a **static website** (hosted free on GitHub Pages) with a **map, a table, and a card view** of every lead. It loads `listings.json`, and when you open a specific lead it lazily fetches that lead's heavy detail from the sidecar.

The filters are the operator's cockpit:
- **Stage** — In Foreclosure / Pre-Foreclosure / Outbound / REO.
- **Distress tier** — HOT, HOT+WARM, or "stacked ≥2 only."
- **Strategy fit** — filter to just wholesale deals, subject-to, land, etc.
- **Geography / type / source** — state, county, land-vs-improved, which scraper it came from.
- **Contact & signal** — has phone, has mailing address, entity-owned, absentee, out-of-state, has a mortgage, elderly, Helene-damaged.
- **ARV confidence** — show only HIGH-confidence values if you want to trust the numbers.

Court-confirmed *sold* properties are hidden automatically. There's a sortable table and an **"Export filtered as CSV"** button so any filtered view becomes an outreach list. Outreach itself is direct mail (the compliant scaled channel) plus cherry-picked calls.

> **Under the hood:** `docs/index.html` + `docs/dashboard.js` — `loadDataset()`, `applyFilters()`, `renderTable/renderCards`/Leaflet map, `ensureDetails()` for the lazy sidecar fetch (the browser mirror of `load_board`).

---

## 4. The manual court-export lane — where the human fits

Two of the richest sources — **SC PublicIndex** and **NC eCourts (Tyler Odyssey)** — sit behind bot walls (F5/Shape challenge on SC, an AWS-WAF image-CAPTCHA on NC) *and* their terms of service prohibit automated scraping. So this lane is **compliant by construction**: a human opens the portal in their own browser, runs the search normally, and does a plain "Save Page As" to drop the results HTML into the repo. Offline parsers — which contain **no** web client, browser, or fetcher of any kind — turn those saved pages into board leads: the SC parser recognizes each case sub-type (Foreclosure, Partition, Ejectment, Judgment, State Tax Lien) and maps it to a lead type; the NC parser extracts the parties and filing details. New cases are resolved to a parcel/owner through the same backbone (Section 3c) and scored like any other lead. Only net-new cases are appended, so re-saving the same page is harmless.

**Why it's manual, in one line:** the compliance boundary. Defeating a CAPTCHA or a login, or riding a ToS "no automated scraping" wall, is the line the project won't cross — so the human does the one action a human is allowed to do (a normal search + save), and the machine only touches the file that results.

> **Under the hood:** `ingest_sc_publicindex_export.py` (parser lib), `scripts/ingest_publicindex_files.py` (SC board-writer, uses `load_board`), `scripts/parse_nc_ecourts_export.py` (`--as-listings`), merged via `merge_today_sources.py`'s name→property resolver. The last run merged **674 saved SC PublicIndex court leads** this way.

---

## 5. Scheduling — the automated cadence

Four scheduled jobs run on the Mac (launchd). Missed runs (Mac asleep) fire once at next wake. Each job is a single writer, guarded so two can't clobber the board at once.

| Job | When | What it does |
|---|---|---|
| **Weekly full run** | **Tue + Fri, 9:30 AM** | The complete pipeline (Sections 3a–3f). On a healthy run it publishes the fresh board to the web. |
| **Daily vision** | **Daily, 9:30 AM** | Refreshes REO/Fannie/HUD links (kills dead 404s) and runs incremental photo-condition scoring. **Skips itself on full-run days** (Tue/Fri) so it doesn't race the big run. |
| **Land-records refresh** | **Daily, 12:00 PM** | Fills in land-record addresses/values/photos that got deferred by API rate limits; commits and pushes. |
| **SOS agent refresh** | **Daily, 2:00 PM** | Advances the NC Secretary-of-State registered-agent frontier (~40 new LLC leads/day); commits **only if the board actually changed** (a blocked run must not create an empty commit). |

The live board is fed by the local Tuesday/Friday run pushing the updated data files to GitHub Pages (the old cloud-CI publishing path is retired).

---

## 6. Compliance boundaries

Three rules govern the whole machine:

1. **Free + public-only.** Everything the robots pull is free public data reached through ordinary public search. Fingerprinting stealth (running a page's own JavaScript to clear a bot-check) is allowed as compliant public browsing; **defeating a CAPTCHA, logging in, riding a ToS "no-scraping" wall, or spending money is not.** No paid data brokers.
2. **One board writer.** Only the artifact functions (`write_artifact` / `load_board`) touch `listings.json`. Every incremental job reads through the round-trip loader so nothing silently drops the heavy detail. This is what keeps the board from corrupting when four jobs run in a day.
3. **What's NOT done (by design).** Personal phone/email (paid-only PII → we mail instead), exact mortgage payoff (private servicer data → we estimate), SC divorce and SC probate portals (access-restricted → covered another way or skipped), and the bot-walled court portals (→ the manual lane). These are settled dead-ends, not bugs — the point of documenting them is so nobody re-chases them.

Full detail on every wall and every manual click-path lives in **`docs/blocked_sources_forensic.md`** (every blocked source, classified WONT / CANT / ABSENT) and **`docs/manual_playbook_and_limits.md`** (what can't be pulled, and the exact site-by-site manual steps).

---

## 7. Current scale

As of the last run (2026-07-01):

- **~17,000 leads on the board** (17,003 exact), spanning the 18-county footprint.
- **~106 scrapers** across **21 categories**, plus the manual court lane.
- **~66% mailable** — 11,190 leads (65.8%) carry an owner mailing address, which is the compliant direct-mail channel that replaces paid phone/email.
- **Distress mix:** **185 HOT**, **5,869 WARM**, **10,946 COLD** — the HOT set is the tight, work-today list (stacked distress + equity + reachable + clean title).
- **Geography:** 11,541 NC / 5,462 SC.

The COLD majority is the point, not a flaw: the machine casts wide across every distress trigger, then the scoring and dashboard filters concentrate your attention on the few hundred that are actually worth a stamp or a call.
