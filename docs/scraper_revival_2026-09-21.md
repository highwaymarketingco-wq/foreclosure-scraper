# Scraper revival, 2026-09-21

Scope: the highest-yield zero-row scrapers from `docs/scraper_registry_reconciliation_2026-09-21.md` section 2, plus the tool that lands them (`scripts/run_scoped_scrapers.py`). Every claim below was measured the same day, live, with a handful of polite requests per source, and each fix has an offline test.

Nothing was written to the board, no `--apply` was run, `load_board` and `write_artifact` were never called against the live board, and nothing was committed. Files touched are listed at the end.

## Bottom line

| Scraper | Was | Now | Expected rows landing |
|---|---|---|---|
| `counties_nc.rutherford_wildfire_tax` | 0 rows. Two stacked causes: the robots gate, and a JSON `Accept` trap that would have made it return 0 even with the gate open | Live and verified. Polite, resumable, one lead per parcel | est. 3,200 distinct real-estate parcels; about 1,900 net new (range 1,100 to 2,900). Exact count is logged by the first full sweep |
| `counties_sc.sc_tax_delinquent` | 1,334 rows, none on the board | 42 rows (only sales whose redemption window is still open) | 0 net new. All 42 are already on the board via `pickens_tax_sale` |
| `counties_nc.gaston_tax_foreclosures` | 81 rows, none on the board | Same 81 are now correctly typed as closed history; 5 date-parse failures fixed | 0 today. No live Gaston sale exists on either county page. A live sale will land with no main.py change |
| `counties_sc.greenville_tax_distress` | disabled | Endpoint verified live (2,855 unpaid-tax parcels). Not edited by me, see item 3 | pending the other agent's file plus a main.py line |
| `counties_sc.anderson_sheriff` | TIMEOUT 3 of 3 (120 s) | Fails in 8 s and says why. The host is down on its side | 0 (host dead; Anderson foreclosures come from `anderson_master_in_equity`) |
| `newspapers.daily_courier` | 0 every run | 2 live foreclosure sales (Sept 22) parsed | 2 |
| `public_notices.funeral_home_rss` | 50 rows/run, all dropped | Unchanged rows, plus owner name; needs one main.py line | 50 (Buncombe 10, Cleveland 20, Anderson 20) |

Three findings contradict the reconciliation doc and are worth knowing before anyone acts on it:

1. **funeral_home_rss rows do carry a county.** All 50 have county and state (set from the host map) and all 50 pass `_in_scope`. The drop is `_active_only`: the slug is not in `DATELESS_OK_SOURCES` (its sibling `gannett_obituaries` is). One line in main.py fixes it.
2. **The 81 Gaston rows did not "pass the filters".** Run through the real `_active_only`, 0 of 81 pass. All 81 are closed sales (sold 65, cancelled 13, redeemed 3) dated 2016 to 2026. The "no `source_all_filtered` warning" evidence only shows that at least one row survived that run.
3. **The 1,334 `sc_tax_delinquent` rows are 97% stale history.** 1,177 come from the 2015 to 2019 sale lists and 115 more from the 2021 to 2024 results, all past the SC 12 month redemption window; only 65 of 1,334 have an address. Landing them would have put about 1,290 dead rows on the board.

## 1. rutherford_wildfire_tax

Class: WALLED by a stale gate (reconciliation). Actual: robots gate plus a content-negotiation trap.

**Changed** (`src/foreclosure_scraper/scrapers/counties_nc/rutherford_wildfire_tax.py`)

- Robots preflight is off by default and kept behind `ROBOTS_STRICT=1` (`_robots_blocks` and `_path_disallowed` are unchanged; the flag restores the old fail-closed behaviour exactly).
- **Accept trap (found live).** The records endpoint answers HTTP 200 with an HTML page titled "Avalon :: Data Only" (3.4 KB) unless the request has `Accept: application/json`. The shared client's default Accept is HTML, so the old `r.json()` failed on every page and the sweep ended with zero rows even with the gate open. Every POST now sends the SPA's Accept header, and a non-JSON 200 raises `WildfireNotJson` instead of returning an empty result.
- **Wall rules.** HTTP 403 or a 200 challenge/CAPTCHA page raises `WildfireWall` and aborts the whole sweep at once (rows already collected still ship; nothing collected reports BLOCKED). No probing around it.
- **Politeness.** One request at a time. The shared client spaces same-host requests 0.8 to 1.5 s; `RUTHERFORD_WILDFIRE_DELAY_S` (default 0.25) adds to that. 429 and 503 honour `Retry-After` (cap 300 s, 4 attempts).
- **Resumable and cached.** State after every page in `data/rutherford_wildfire_state.json` (per year: reported total, next skip, done) and `data/rutherford_wildfire_bills.jsonl` (one slimmed real-estate bill per line, about 0.7 KB). A rerun within 72 h continues at the recorded skip (a fresh search token is minted, then it continues at the saved offset); a complete sweep younger than 12 h is served from disk with zero requests. A rejected token (401) is re-minted up to twice per year. Both files are git-ignored (`data/`). Delete them to restart.
- **Count check, not count trust.** Each year's fetched bill count is compared with the server's reported total and a shortfall below 98% logs `rutherford_wildfire.year_short`.
- **One lead per parcel.** Bills roll up by parcel: one TAX_LIEN lead with summed amount and, new, `raw.rutherford_wildfire.years_detail` (per year: amount due, original bill, bill numbers, flags), `amount_by_year`, `oldest_delinquent_year`. Bills are de-duplicated by IDHash so a replayed page never double counts. IND and BUS personal-property bills are never stored.
- Situs: house number 0 means a vacant lot (`0 GLEN RIDGE TRL`); that is a road name, not an address, so `street_address` is left empty (the road-centroid geocoder trap) and `raw.situs_vacant_lot=True` keeps the raw string. About half of the sample parcels are vacant lots. `CHIMNEY ROCK VILLAGE` is split off as a city.
- `timeout_s` 3000 (env `RUTHERFORD_WILDFIRE_TIMEOUT_S`); partial rows are refreshed into `BaseScraper.partial` every 25 pages so a soft timeout still ships the sweep so far. `apply_row_limit(n)` (used by the runner) caps pages at ceil(n/6).

**Live check** (server-side numbers 2026-09-21)

- `TotalRecords` for Unpaid, Property, TY2016 to TY2025: **27,822** (29,319 on 8/3). Per year: 2025 6,925; 2024 5,568; 2023 4,637; 2022 2,667; 2021 1,384; 2020 1,803; 2019 2,352; 2018 1,678; 2017 807; 2016 1. The largest year is under the 10,000 row search window, which is why years are swept one at a time.
- Real scraper run, 5 pages: 100 bills, 44 parcel leads, resume verified live (second run continued at skip 60, then 100). Sample: parcel 232588, TAX_LIEN, $2,186.53, `referred_outside_counsel`, owner mailing address captured.
- **Distinct parcels: estimated 3,216, 95% interval about 1,800 to 4,600.** Not measured exactly, because the full sweep is 1,392 requests and the brief limited live checks to a handful. Method: 5 random result pages (100 bills) drawn proportional to year size; 34 were real estate (34%, so about 9,460 real-estate bills of 27,822); for each sampled parcel one lookup by parcel number returned its bill count m; the Horvitz-Thompson sum of 1/m over sampled bills, scaled to 27,822. Bills per parcel is heavy tailed (median about 7; 14 of 34 sampled parcels have 9 unpaid tax years). The estimate is clustered by page, so treat the interval as rough. The first full sweep logs `rutherford_wildfire.done distinct_parcels=N`.
- Net new: of the first 30 parcels (TY2025 pages), 11 are already on the board (via `rutherford_tax`) and 19 are new. Applying 63% to about 3,200 gives about 1,900. The sample is TY2025-heavy; older-year-only parcels are less likely to be on the board, so expect this to be a floor rather than a ceiling.
- Politeness: about 60 POSTs and 4 shell GETs in total, sequential, 0 429s, 0 challenge pages.

**Remaining blocker:** none for code. It needs one full sweep (about 33 minutes) and a merge. No main.py change (`counties_nc.rutherford_wildfire_tax` is already in `DATELESS_OK_SOURCES`; TAX_LIEN uses the any-NC/SC scope rule).

**Command**

```
.venv/bin/python scripts/run_scoped_scrapers.py --slugs counties_nc.rutherford_wildfire_tax \
    --limit 100000 --timeout 3000 --save-json /tmp/rw_kept.json        # dry run, ~33 min, resumable
.venv/bin/python scripts/run_scoped_scrapers.py --load-json /tmp/rw_kept.json --apply   # lands it
```

The state files currently hold the first 100 bills from the live check, so the first sweep resumes at skip 100 of TY2025 if started within 72 h.

## 2. sc_tax_delinquent and gaston_tax_foreclosures

### sc_tax_delinquent

Class: NOT LANDED (reconciliation). Actual: landed nothing because nothing was worth landing.

Why nothing landed. (a) The 8/28 run, the last that wrote the board, timed out on this scraper; the 8/29 and 9/8 runs scraped 1,334 rows and passed `_in_scope` and `_active_only` (the slug is in `DATELESS_OK_SOURCES`) but never wrote the board. (b) Live run today, same 1,334, all Pickens: the 2015 to 2019 sale lists (1,177 rows) plus the 2021 to 2024 results (115) plus 42 rows from the 2025 results. Only the last is a live lead, and `pickens_tax_sale` already parses that same PDF (160 rows). Anderson, Spartanburg, Cherokee, Oconee, Union and Laurens all returned 0: their annual lists are not posted yet.

**Changed:** a post-sale RESULTS PDF is emitted only while its redemption window is open (sale year plus 1, to Dec 31, the same convention `pickens_tax_sale` uses), rows carry `redemption_deadline` and `raw.sc_tax_delinquent.{post_sale,sale_year,disposition}`. Closed results are skipped before any download (year from label, file name, `?t=` stamp, then PDF text), so a run makes 2 Pickens PDF requests instead of 9. `SC_TAX_DELINQUENT_INCLUDE_HISTORICAL=1` restores the old behaviour.

**Live check:** 42 rows in 30 s (was 1,334). Board scan: 30 of the 30 checked were already on the board, 0 new.

**Expected rows landed:** 0 net new now. Real yield arrives when the six counties post their 2026 lists (October to November); those flow with no change. The reconciliation's "correct run_meta" item stands: `run_meta` calls this source EMPTY while it scraped 1,334 rows.

**Blocker:** none. **Command:** included in the batch command at the end.

### gaston_tax_foreclosures

Class: NOT LANDED (reconciliation). Actual: no live sale exists.

Live check: `/669` (active) empty; `/671` (previous) 81 rows dated 2016 to 2026. Through the real gates: `_in_scope` 81, `_active_only` 0 (76 past the 14 day grace, 5 dateless), sold-pool candidates 0 (the slug is not in `FORECLOSURE_SALE_SOURCES`).

**Changed:** ordinal dates ("August 4th, 2021") now parse (that was the 5 dateless rows); the free-text status maps to a terminal `auction_status` (`sold`, `cancelled`, `redeemed`, all in `TERMINAL_AUCTION_STATUSES`) so closed history is recognisable; sold rows carry `raw.actual_sold_price` (the final bid); a printed future "Last Day to Upset" is published as `raw.upset_bid` (`in_window`, `deadline_iso`, `source=published`, the shape `in_upset_window` already reads). A dated live sale passes scope and `_active_only` untouched (tested), so no whitelist entry is needed.

**Expected rows landed:** 0 today. Gaston had 4 sale dates in the last 12 months; each active sale lands as a TAX_SALE flip-lane row.

**main.py or other-module changes (optional, not required for landing):**

1. Sold-price comps: add `"counties_nc.gaston_tax_foreclosures"` to `enrichment_foreclosure_sold_comps.FORECLOSURE_SALE_SOURCES`. Caution: path 1 of `is_sold_pool_candidate` (an `actual_sold_price` is set) has no age cap, so all 65 sold rows back to 2016 would enter the pool. Add a recency cap first.
2. NC published upset window. `_active_only` keeps an SC tax sale alive through its redemption clock but has no equivalent for a published NC "Last Day to Upset" that runs past sale + 14 days. Inert today (nothing is in an upset window). Sketch, directly under the `sc_tax_redemption_open` line:

```python
    ub = li.raw.get("upset_bid") if isinstance(li.raw, dict) else None
    if sale <= cutoff_future and isinstance(ub, dict) and ub.get("in_window") and ub.get("source") == "published":
        try:
            if datetime.fromisoformat(str(ub.get("deadline_iso"))) >= ref:
                return True
        except ValueError:
            pass
```

## 3. greenville_tax_distress

The registered slug `counties_sc.greenville_tax_distress` lives in `greenville_hard_distress.py`, which the brief assigns to the other agent (there is no `greenville_tax_distress.py`), so I did not edit it. That agent's in-progress diff already repoints the GIS URL to `gcgis.org/arcgis3/.../GreenvilleNJ/QueryLayers/MapServer/0`.

My live check of that layer: `TOTTAX > 0 AND PAIDDATE IS NULL` returns **2,855** parcels (the old layer read 5,014), fields present, paging works. So the endpoint is good.

Two things remain and neither is in a file I own:

- The class stays `disabled` unless `FORECLOSURE_INCLUDE_GREENVILLE=1`. To run it without a code change: `--env FORECLOSURE_INCLUDE_GREENVILLE=1` on the runner (the env is set before the registry instantiates scrapers, which is when the flag is read).
- **main.py:** add the slug to `DATELESS_OK_SOURCES`, or every row is dropped. The module docstring says so; it is not there yet. It emits TAX_LIEN, which `_in_scope` already admits for Greenville (`in_scope_distressed('Greenville','SC')` is True; the deny list only binds flips).

```python
    "counties_sc.greenville_tax_distress",       # Greenville unpaid-tax + tax-sale parcels (dateless); emits only with FORECLOSURE_INCLUDE_GREENVILLE=1
```

Preview command (writes nothing): `--slugs counties_sc.greenville_tax_distress --env FORECLOSURE_INCLUDE_GREENVILLE=1 --dateless-ok-extra counties_sc.greenville_tax_distress`.

## 4. anderson_sheriff, daily_courier, funeral_home_rss

### anderson_sheriff

Class: TIMEOUT 3 of 3. Actual: the host is dead, not slow. `www.andersonsheriff.com` resolves to 192.155.253.203; from this Mac a TCP connect to :443 times out (25 s), from a second network (the WebFetch tool) it is refused (ECONNREFUSED), and the bare domain does not resolve. The old code retried through `get_text(impersonate=True)` (3 x 8 s, a 45 s curl fallback, 3 more tries), which exceeded 120 s and was labelled TIMEOUT.

**Changed:** one plain GET; connect failures propagate at once so `safe_run` classifies them in seconds (live: `TIMEOUT (network timeout (ConnectTimeout))` in 8 s). The Chrome-fingerprint tier runs only on a block status (401/403/406/409). SC case numbers like `2024-CP-04-00123` are no longer cut at `2024-CP-04`. The row parser could not be re-verified against a live page, since there is none.

**Expected:** 0. Anderson's real foreclosure sales come from `anderson_master_in_equity`; a sheriff's sale is a rare judgment execution. **Blocker:** the host. If it returns, check the parser first.

### daily_courier

Class: DEAD (regressed). Actual: the page is fine and carried two live foreclosure sales on the day of the fix. The parser had drifted in three ways:

1. NC file numbers now print `26SP000130-800` (six digits plus county code); the old pattern allowed 1 to 5 digits, so it never matched.
2. Notices now read `Address of Property:` and `Record Owners:`; the old patterns looked for `Property address` and `Present Owner(s)`. With no case number and no address, the precision gate dropped every row.
3. The meta description is cut at about 270 characters with the words run together; the full notice is the `itemprop="description"` element (6 KB).

Also found: the host answers **429** (plain text, no `Retry-After`) after about four requests in a few seconds, and the old loop skipped a 429'd ad silently.

**Changed:** re-fit to the current layout (case number, address split into street, city and zip, owner, trustee, original beneficiary as plaintiff, deed of trust book/page/date, sale date, time and place). Cards whose title says NOTICE TO CREDITORS or PUBLIC HEARING are not fetched (8 of 10 cards today), fetches are paced 6 s apart (`DAILY_COURIER_DELAY_S`), a 429 is retried with a growing wait, `timeout_s` 240, and rows go into `partial` as they are read.

**Live check:** 16 s, 1 listing request plus 2 detail requests. 2 rows: `26SP000130` (2831 Cove Road, Rutherfordton, sale 2026-09-22 1:00 p.m., Rutherford County Courthouse) and `26SP000105` (225 S. Hillside Street, same sale). Both pass `_in_scope` and `_active_only`. Board scan: both new.

**Expected rows landed:** 2 now (both sell tomorrow, so act on them first). Future volume is unmeasured: the page held 2 on the day of the check. The listing shows only about 10 live ads, so a notice is visible only while it is one of them. Estate (NOTICE TO CREDITORS) notices are deliberately not emitted; adding them needs a PROBATE_NOTICE branch and a `DATELESS_OK_SOURCES` line. **Blocker:** none.

### funeral_home_rss

Class: FILTERED. Actual: see finding 1. All 50 rows have county and state and pass scope; `_active_only` drops them because the slug is not whitelisted. There is no field a scraper can set that changes `_active_only` for a dateless lead, so the fix is in main.py.

**Changed:** `owner_name` now equals the decedent (the resolver reads `owner_name` first, then `defendant`), and `raw.dateless=True`. All 50 are already name-resolver targets (`_is_target`: name, NC/SC, no address or parcel, core county).

**main.py change (exact):**

```python
    "public_notices.funeral_home_rss",           # funeral-home obituary RSS -> pre-probate heir leads (dateless; county set from the host map)
```

**Expected rows landed:** 50 per pass (Buncombe 10, Cleveland 20, Anderson 20), all new on the board in the scan. They arrive name-only; the resolver pins the ones whose decedent owned property in county. Until main.py is changed, `--dateless-ok-extra public_notices.funeral_home_rss` lands them, but the next full run will still drop them (so change main.py before relying on it). **Blocker:** the one main.py line.

## 5. scripts/run_scoped_scrapers.py

```
python scripts/run_scoped_scrapers.py --slugs a,b,c | --slugs-file f | --load-json f
       [--limit 200] [--timeout SEC] [--env K=V ...] [--dateless-ok-extra s,s]
       [--horizon-days N] [--no-board] [--save-json f] [--apply] [--no-score]
```

- **Filters are main.py's, imported not copied:** the sold-pool partition (`is_sold_pool_candidate`), `_in_scope`, `_active_only` (with `DATELESS_OK_SOURCES`), `_flip_candidate`, then the shared `dedupe`. Tested by monkeypatching `main._in_scope` and `main._active_only` and watching the runner obey. Reason text is explanation only; the keep or drop decision is main's own function.
- **Dry run by default.** Per slug: outcome and seconds, rows scraped (and pre-cap count), kept, NEW versus already on the board, per-filter drop counts with reasons (`sale 90d ago (grace 14d)`, `dateless and slug not in DATELESS_OK_SOURCES`, `terminal status 'sold'`, `flip outside the 18-county footprint (Wake NC)`), and a sample row.
- **One streaming pass over the board** (`board_stream.iter_board_rows`, about 300 MB, no `load_board`) for the whole batch. A row counts as already on the board when its `dedupe_key` or any strong signature from `dedupe._strong_sigs` matches (parcel + state, case + address, address + zip, canonical street + county).
- **`apply_rows(rows, new_listings, *, docs_dir=None, write=True, score=True) -> dict`.** `rows` is the existing board from `load_board`. Additive only: a survivor matching an existing row is counted and skipped; existing rows are never modified or removed, asserted by fingerprinting every existing row before and after (and length and order), and it refuses to write on any change. New rows get offline enrichment only (tax-owed fold, valuation calc and grade, distress score, `raw.landed_by`); the network chain (geocode, parcel/GIS, name resolver, images) is not run, so follow with `merge_today_sources.py` or the next full run. Writes with `write_artifact` under `board_lock` (the CLI takes the lock and calls `load_board`; exit 75 when a writer holds it, which is the case while the daily vision job runs).
- `--save-json` then `--load-json` lets you land exactly what you reviewed without re-scraping. `--env` sets flags before scrapers are built. `--dateless-ok-extra` previews or lands a source whose main.py line is not added yet, printing a warning.
- A scraper may define `apply_row_limit(n)` to stop early; the rest are truncated to `--limit` after the fact.

Dry-run result today (real scrapers, real board scan, nothing written):

| Source | Kept after filters | Already on board | New |
|---|--:|--:|--:|
| `newspapers.daily_courier` | 2 | 0 | 2 |
| `public_notices.funeral_home_rss` (with the extra dateless flag) | 50 | 0 | 50 |
| `counties_nc.gaston_tax_foreclosures` | 0 (81 closed sales, all terminal) | | |
| `counties_sc.anderson_sheriff` | 0 (host down) | | |
| `counties_nc.rutherford_wildfire_tax` (30 of about 3,200 parcels) | 30 | 11 | 19 |
| `counties_sc.sc_tax_delinquent` (30 of 42) | 30 | 30 | 0 |

## Commands, in the order to run them

Run the applies only when the daily vision job has released the board lock (`logs/.board.lock`). Memory is tight (swap was 5.9 of 7 GB during this work): one board process at a time.

```
# 1. Everything except the long Rutherford sweep (about 1 minute)
.venv/bin/python scripts/run_scoped_scrapers.py \
    --slugs newspapers.daily_courier,public_notices.funeral_home_rss,counties_nc.gaston_tax_foreclosures,counties_sc.sc_tax_delinquent,counties_sc.anderson_sheriff \
    --save-json /tmp/revival_a.json          # add --dateless-ok-extra public_notices.funeral_home_rss until main.py has the line
.venv/bin/python scripts/run_scoped_scrapers.py --load-json /tmp/revival_a.json --apply

# 2. Rutherford full sweep (about 33 minutes, resumable), then apply
.venv/bin/python scripts/run_scoped_scrapers.py --slugs counties_nc.rutherford_wildfire_tax --limit 100000 --timeout 3000 --save-json /tmp/rw_kept.json
.venv/bin/python scripts/run_scoped_scrapers.py --load-json /tmp/rw_kept.json --apply
```

The Sept 22 Rutherford sales are the time-sensitive part of step 1.

## main.py change list, consolidated

Both are single lines in `DATELESS_OK_SOURCES`:

```python
    "public_notices.funeral_home_rss",           # funeral-home obituary RSS -> pre-probate heir leads (dateless)
    "counties_sc.greenville_tax_distress",       # Greenville unpaid-tax + tax-sale parcels (dateless); flag-gated
```

Optional, not needed to land anything: the NC published-upset-window branch in `_active_only` and the Gaston sold-comps entry (both under item 2).

## Politeness accounting (live requests made)

Rutherford CDN about 60 POSTs and 4 GETs (sequential, no 429); Pickens about 12; thedigitalcourier.com about 10 (two 429s, both from bursts before the pacing fix; the fixed scraper made 3 in a 16 s run with none); gastongov.com 6; three funeral-home feeds 9; andersonsheriff.com 4 (connect failures); gcgis.org 2.

## Tests

`uv run python -m pytest -q -p no:cacheprovider` on: `tests/test_rutherford_wildfire_tax.py` (existing, 21), `tests/test_rutherford_wildfire_revival.py` (24), `tests/test_scraper_revival_2026_09_21.py` (35, covers gaston, sc_tax_delinquent, anderson_sheriff, daily_courier, funeral_home_rss), `tests/test_run_scoped_scrapers.py` (18). New fixtures: `tests/fixtures/daily_courier_*.html` (synthetic names and addresses; the repo is public).

## Files

Edited: `src/foreclosure_scraper/scrapers/counties_nc/rutherford_wildfire_tax.py`, `counties_nc/gaston_tax_foreclosures.py`, `counties_sc/sc_tax_delinquent.py`, `counties_sc/anderson_sheriff.py`, `newspapers/daily_courier.py` (rewritten), `public_notices/funeral_home_rss.py`. New: `scripts/run_scoped_scrapers.py`, the four test files and three fixtures above, this document. Not touched: the registry, `sc_catalis_delinquent_roll.py`, `greenville_hard_distress.py`, `nc_civicplus_tax_sale.py`, the Column scraper, `main.py`, `web_artifact.py`, `distress_score.py`, `parcel_cache.py`.
