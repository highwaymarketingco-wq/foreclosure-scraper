Audit complete. All upstream numbers below are **real measurements**, dated, from either (a) the live run's own per-source counters in `/Users/cashhigh/foreclosure-scraper/logs/local-run-20260804T111456.log` (today 2026-08-04, the run that is currently executing), or (b) single polite probes I made myself. Board numbers are from `/Users/cashhigh/foreclosure-scraper/docs/listings.json` (25,552 rows, written 2026-08-03 14:01, whose scrape content is the **2026-07-31 full run** — the Aug 2/3 commits were enrichment passes, not re-scrapes).

## Headline

Three distinct failure classes, not one:

1. **One true silent-drop bug that has persisted across both the 7/31 and today's runs**: `newspapers.hendersonville_lightning` (Henderson) — 5 rows scraped, 0 land, missing `DATELESS_OK_SOURCES` entry.
2. **One design decision that is probably misfiring**: `counties_nc.henderson_tax` — all 15 parcels are routed to the sold-comp pool, not the board, because the county's page carries a past batch date.
3. **A large "built-but-never-merged" backlog** — 6 sources serving these counties were fixed or created *after* the 7/31 scrape that produced the current board. They read 0 today but are landing in the run that is executing right now. Not bugs.

## Table

| county | source | upstream now | on board | delta | cause | verdict |
|---|---|---|---|---|---|---|
| Buncombe | counties_nc.buncombe_elderly | 4,341 | 3,536 (3,631 incl. `also_seen_in`) | -805 | cross-source dedupe + board aging since 7/31 | PARTIAL-explained |
| Buncombe | counties_nc.buncombe_delinquent_tax | 1,181 | 1,154 | -27 | payoff churn + dedupe | CAPTURING |
| Buncombe | counties_nc.asheville_str_permits | 678 | 620 | -58 | dedupe | PARTIAL-explained |
| Buncombe | counties_nc.asheville_helene | 652 | 172 (216 anywhere) | -480 | dedupe: 242 board rows carry helene in `raw.also_seen_in`, +74 merged under ncnotices, +44 under buncombe_elderly. Exact reconciliation **unmeasured** | PARTIAL-explained |
| Buncombe | counties.multi_year_delinquent_tax | 2,078 raw Buncombe rows (2013–2025 layers) | 0 | -2,078 | scraper **created 2026-08-03** (commit 8c51651), after the 7/31 board scrape. Never merged | PARTIAL-explained (lands this run) |
| Buncombe | counties_nc.buncombe_tax (Trumba JSON) | 33 | 0 | -33 | was `ZERO_RESULT` on 7/31 (date-window regression); fixed 8/2 + added to `DATELESS_OK_SOURCES`. Board predates the fix | PARTIAL-explained (lands this run) |
| Buncombe | counties_nc.buncombe_tax_foreclosure (Trumba .ics) | 0 VEVENTs — **I probed it**: 200 OK, valid VCALENDAR, 225 bytes, zero events | 0 | 0 | NOT genuinely empty. The `.ics` endpoint takes no date window and defaults future-only; every Buncombe bidding-begins date is past — the exact bug `buncombe_tax` fixed in its `.json` twin off the same calendar. Zero net lead loss because `buncombe_tax` covers the identical inventory | BROKEN (zero-impact duplicate lane) |
| Buncombe | counties_nc.nc_heir_estate_parcels | 55 | 47 (53) | -8 | churn + dedupe | CAPTURING |
| Buncombe | public_notices.nc_notices_counties | 512 total, Buncombe is 1 of 11 ticked counties; per-county split **unmeasured** | 0 | full | whitelisted 2026-07-31 **21:11**; the 7/31 run started 11:08 — too late | PARTIAL-explained (lands this run) |
| Buncombe | law_firms.kania | 0 Buncombe rows in the 188-row feed (**I pulled the ninja-table AJAX**) | 0 | 0 | Kania publishes no Buncombe parcels today | CAPTURING |
| Buncombe | counties_nc.nc_ptscloud_delinquent_tax / nc_county_pdf_delinquent_tax | n/a | 0 | n/a | Buncombe is not a tenant/county in either module | NOT-WIRED |
| Henderson | counties_nc.nc_ptscloud_delinquent_tax | 1,141 today (1,155 on 7/31) | 1,068 (1,082) | -73 / -87 | payoff churn + dedupe; 93% capture | CAPTURING |
| Henderson | counties_nc.henderson_tax | **15** (I fetched the page: 15 data rows, only date on page = "May 27, 2026 at 10:00am") | 0 primary, 9 via `also_seen_in`, **15 in `docs/foreclosure_sold_pool.json`** | -15 from board | Sale date is 69 days past → `is_sold_pool_candidate` routes all 15 to the max-bid comp pool before the board filter. BY DESIGN — but the design assumes a past batch date means the sale finished. If Henderson simply has not refreshed the page, live inventory is being filed as comps | PARTIAL-explained — **flag for review** |
| Henderson | counties_nc.henderson_foreclosure_parcels | 15 | 0 | -15 | scraper created 2026-08-03, after the board scrape | PARTIAL-explained (lands this run) |
| Henderson | counties_nc.henderson_code_violations | 156 | 0 | -156 | same (created 2026-08-03) | PARTIAL-explained (lands this run) |
| Henderson | counties_nc.hendersonville_vacant_structures | 51 | 0 | -51 | same (created 2026-08-03, commit 4542622) | PARTIAL-explained (lands this run) |
| Henderson | **newspapers.hendersonville_lightning** | **5** | **0** | **-5** | `_townnews`-style parser sets `sale_date=None` when no date parses; slug is **not** in `DATELESS_OK_SOURCES` and **not** in `FORECLOSURE_SALE_SOURCES`, so it gets neither the dateless lane nor the sold-pool lane. All-filtered on **both** 7/31 and today | **BROKEN** |
| Henderson | counties_nc.nc_heir_estate_parcels | 73 | 73 | 0 | — | CAPTURING |
| Henderson | law_firms.kania | 0 Henderson rows upstream | 0 | 0 | Kania publishes no Henderson parcels today | CAPTURING |
| Gaston | counties_nc.gaston_surplus_properties | **0** — I fetched the county's own PDF (`/DocumentCenter/View/9608`, July 2026 edition): *"There are no surplus properties at this time."* | 0 | 0 | genuinely empty, not broken. (Note: the scraper's hard-coded `SURPLUS_PDF_FALLBACK` points at the stale id 1686, but `_find_pdf_url` correctly discovers 9608, so the fallback never fires) | CAPTURING |
| Gaston | counties_nc.nc_county_tax_foreclosure | 87 across Gaston/McDowell/Rutherford; per-county split **unmeasured** | 1 | — | Gaston's `/669` active page carries ~1 property; the ~70-row volume is on `/671` **Previous** Sales, which the scraper tags `sold`/`redeemed` and the board deliberately hides | CAPTURING (actionable subset) |
| Gaston | counties_nc.nc_heir_estate_parcels | 72 | 67 | -5 | churn + dedupe | CAPTURING |
| Gaston | *(delinquent property tax)* | — | 0 | — | Gaston is in **no** tax-arrears module: not a PTS Cloud tenant, not in the Lincoln/Catawba/McDowell PDF set, not in multi_year (Buncombe/Oconee/Pickens only). Gaston is the only one of the four with no property-tax-arrears lane at all | **NOT-WIRED** (structural gap) |
| Cleveland | counties_nc.cleveland_tax | 9 today (8 on 7/31) | 4 on board + 4 in sold pool = **8 of 8 accounted for** on 7/31 | 0 unexplained | scheduled-sale rows with recent past dates → sold pool by design; dateless "currently in foreclosure" rows → board | CAPTURING |
| Cleveland | **law_firms.kania** | **7 Cleveland parcels** (measured: 188 rows / 25 counties in the live ninja-table feed) | **0** | **-7** | `law_firms.kania` was added to `DATELESS_OK_SOURCES` at 2026-07-31 **21:11** (commit fa04a2d); the 7/31 run started **11:08**, so its 6 rows were 100% filtered. It is **not** in today's all-filtered list → it is landing in the current run | PARTIAL-explained (self-healing this run) |
| Cleveland | counties_nc.nc_heir_estate_parcels | 60 | 52 | -8 | churn + dedupe | CAPTURING |
| Cleveland | newspapers.shelby_star | 0 (`ZERO_RESULT` today and 7/31) | 0 | 0 | Cleveland's own paper returns nothing two runs running. I did **not** independently verify the page has no legals — genuinely-empty vs. silently-broken is **unmeasured** | CAPTURING-unverified |
| Cleveland | public_notices.nc_notices_counties | Cleveland is 1 of 11 ticked; split **unmeasured** | 0 | full | same late-whitelist cause as Buncombe | PARTIAL-explained (lands this run) |

## The zero-on-board list you asked to be flagged

Today's live run logged 23 `orchestrator.source_all_filtered` warnings — sources that scraped rows and had **zero** survive. Filtered to ones that plausibly touch these four counties:

- `counties_nc.henderson_tax` (15) — sold-pool routing, explained above
- `newspapers.hendersonville_lightning` (5) — **real bug, needs a `DATELESS_OK_SOURCES` entry**
- `law_firms.alaw` (26; 18 NC / 8 SC per `alaw.parsed` events) — not in `DATELESS_OK_SOURCES` **and** not in `FORECLOSURE_SALE_SOURCES`, so its rows have no lane. County split **unmeasured** — worth a follow-up since ALAW is a statewide NC trustee firm that could carry any of the four
- `law_firms.ingle_firm` (1), `city_websites.search` (159), `counties.sitemap_walker` (30), `public_notices.funeral_home_rss` (50) — same missing-lane shape, county attribution **unmeasured**
- `law_firms.zacchaeus` (142) — in `DATELESS_OK` but coastal-scoped (Onslow/Dare); legitimate scope filter, not a gap for these counties

## Two fixes worth making

1. `src/foreclosure_scraper/main.py` — add `"newspapers.hendersonville_lightning"` to `DATELESS_OK_SOURCES` (line ~302). It is the only confirmed, repeatable, unexplained zero among the four counties.
2. `counties_nc.buncombe_tax_foreclosure` is a dead `.ics` twin of `counties_nc.buncombe_tax` hitting the same Trumba calendar. It will read "EMPTY (verified)" forever. Either give it the same past-window treatment or retire it, so run_health stops reporting a healthy zero.

Also worth a human look: whether Henderson's "May 27, 2026" tax-foreclosure table is a **finished** sale (sold-pool routing correct) or a **stale page** listing live inventory (in which case 15 real Henderson leads are sitting in the comp pool instead of the board). The page itself gives no way to tell.