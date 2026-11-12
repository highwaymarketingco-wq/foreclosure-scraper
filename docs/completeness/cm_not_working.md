All probes complete. Compiling the findings.

## 1. Wired set and run reconstruction (measured)

`_registry.discover()` = **132** scraper classes, 132 unique slugs, no duplicates.

| Run | starts | scraper.ok | scraper.error | zero-count | never started (dormant) |
|---|---|---|---|---|---|
| `local-run-20260731T110836.log` (last complete) | 116 | 114 | 0 | 21 | 17 |
| `local-run-20260804T015737.log` | 124 | 116 | 1 | 17 | 8 |
| `local-run-20260804T111456.log` (**live now**, all 124 scrapers finished) | 124 | 124 | 0 | **18** | 8 |

The 7/31 gap of 16 slugs is not a failure: 9 modules did not exist yet (added 7/31–8/4: `pickens_delinquent_parcels`, `oconee_flc_assignment`, `spartanburg_city_condemned`, `henderson_code_violations`, `henderson_foreclosure_parcels`, `hendersonville_vacant_structures`, `rutherford_wildfire_tax`, `nc_notices_counties`, `multi_year_delinquent_tax`), and 8 are `OUTCOME_DORMANT` (`disabled` or off-season), which returns `[]` before `scraper.start` is ever emitted.

**Now healthy (6 of the 21 starting zero-producers are fixed):** `buncombe_tax` 0→33, `polk_tax` 0→1, `hutchens` 0→86, `nc_upset_bids` 0→35, `sc_flc` 0→44, `treasury_seized` 0→1 (that was the "+1 more"). `sc_flc` errored at 01:57 on a Gemini-key quota, then ran clean at 11:14 — transient, not a source problem.

---

## 2. Every non-producing source, root cause, one-line fix

### A. Ran, returned 0 rows (18)

| Source | Rows | Outcome | Root cause (measured today) | One-line fix |
|---|---|---|---|---|
| `counties_nc.buncombe_tax_foreclosure` | 0 | ZERO | **UPSTREAM-EMPTY.** Trumba ICS 200, 225 bytes, valid `VCALENDAR` named "Tax Foreclosures - All", **0 `VEVENT`s**. Last event ran out ~7/10 (was 1/run through 7/10). | None — leave running; feed self-heals when the next sale posts. |
| `counties_nc.gaston_surplus_properties` | 0 | ZERO | **UPSTREAM-EMPTY.** Page 200, anchor resolves correctly to the *new* id `/DocumentCenter/View/9608`; PDF text is literally `There are no surplus properties at this time. July 2026`. | Update the stale `SURPLUS_PDF_FALLBACK` (1686 → 9608) so the fallback isn't a dead id. |
| `counties_nc.rutherford_wildfire_tax` | 0 | ZERO | **WALLED (robots).** Verified live today: both `d1ebsyxxbc7tep.cloudfront.net/robots.txt` and `avalon.sturgiswebservices.com/robots.txt` = `User-agent: *\nDisallow: /`. Guard fails closed by design. | None available compliantly — ask Rutherford/Sturgis for access; ~29,319 delinquent rows behind it. |
| `counties_sc.oconee_tax_sale` | 0 | ZERO | **SEASONAL.** CSV 200; only announcement rows. Window read off the sheet: *list online **Oct 21, 2026**, sale **Nov 9, 2026***. | None — `active_months` should be set to (10,11) so it reports DORMANT instead of a false zero. |
| `counties_sc.sc_tax_delinquent` | 0 | ZERO | **Mixed SEASONAL + DEAD-URL.** All 7 counties 0. Live: Spartanburg `/delinquent-tax` **404**, `/treasurer` **404**; Union `countyofunion.com` **connection reset**; Cherokee 200 but no list; Pickens links only post-sale RESULT PDFs (correctly filtered); Anderson/Oconee 200, no table; Laurens notice is off-site on a host whose robots disallows AI agents. | Re-point Spartanburg + Union to their live CivicEngage paths and set `active_months=(10,11,12,1)`. |
| `law_firms.aldridge_pite` | 0 | ZERO | **UPSTREAM-EMPTY.** 200 with Referer; `table.posts-data-table` present, `data-config` has `serverSide:false`, header row rendered, **`tbody` = 0 rows**. Never produced in any logged run. | None — but add an explicit "empty table" log so a parser break can't hide here. |
| `law_firms.korn` | 0 | ZERO | **DEAD-URL.** `kornlawfirm.com/foreclosure-sales/` 200 but **1,130 bytes** = domain-parking shim. Stub returns `[]` without network. | Retire the slug, or re-point if the firm republishes. |
| `law_firms.mewborn_deselms` | 0 | **BLOCKED** | **WALLED (Cloudflare).** 4× `HTTP/1.1 403` today across all three tiers; correctly raises so it reports BLOCKED, not a clean zero. | None compliant — request access from the firm; do not re-add the retry-until-it-relents loop. |
| `national.crexi_multifamily` | 0 | ZERO | **DEAD-URL.** `/properties/{ST}/Multifamily` now **permanently** 30x-redirects to `/search/multifamily-properties-for-sale/{st}` for both NC and SC, both attempts. Stealth gets 200 but `got: 0` → `no_grid`. Produced 226/227/169/228 through 7/10; **0 since 7/24**. Plain httpx = 403 (Cloudflare). | Teach the parser the `/search/` card DOM (or find its link shape) instead of treating `/search/` as `no_grid` — this is a ~220-row/run regression. |
| `national.gsa_realproperty` | 0 | ZERO | **FILTERED (state filter), upstream fine.** Index 200, **12 active asset ids nationwide, 0 in NC/SC**. Working as designed. | None — keep as a watcher. |
| `national.landsofamerica` | 0 | ZERO | **WALLED (Akamai).** Live: `landsofamerica.com` and `land.com` both **403** with `_abck` in the body. Stealth gets a ~414-byte body, hits the `len(html) < 5000` guard and breaks **with no log at all**. Never produced. | Add a log on the short-body break (today it's invisible); source is otherwise not free-viable. |
| `national.probate_foreclosure_leads` | 0 | ZERO | **Policy stub.** Paid Apify actor; deliberately returns `[]`. No network. | Retire the slug or gate it behind an explicit paid flag. |
| `national.propwire` | 0 | ZERO | **Policy stub.** Paid ($0.007/record); deliberately returns `[]`. | Same. |
| `newspapers.daily_courier` | 0 | ZERO | **UPSTREAM-EMPTY.** Pipeline fully worked: 3 index pages 200, 10 `ad_*.html` details fetched — all are `NOTICE TO CREDITORS`, none foreclosure. Produced 1–7 on most prior runs. | None. |
| `newspapers.index_journal` | 0 | ZERO | **UPSTREAM-EMPTY.** All 4 RSS queries 200. Unfiltered legal feed = 9 items, all `NOTICE TO CREDITORS`; `q=foreclosure` and `q=master+in+equity` each return **0 `<item>`s**. Produced 6–7 on 7/24 and 7/31. | None. |
| `newspapers.shelby_star` | 0 | ZERO | **DEAD-URL / redundant.** `/legal-notices/` **404**; `/public-notices/` 308 → `/public-notices` 200, but that page is a Gannett Next.js shell whose only content is links to **ncnotices.com**. Never produced. | Retire it — `public_notices.nc_notices_counties` already pulled 512 rows from ncnotices today. |
| `newspapers.tryon_bulletin` | 0 | ZERO | **DEAD-URL.** `/category/legal-notices/` **404**; the WP search returns 15 dated articles, all editorial (farmers market, camps) plus 2017 pieces. Never produced in any logged run. | Retire, or re-point at the paper's actual legals vendor once identified. |
| `public_notices.publicnoticesc` | 0 | ZERO | **WALLED (Cloudflare).** Documented stub, no network issued. | None free; SC notices partly covered by `sc_public_index_lis_pendens` + county MIE. |

### B. Dormant — never started (8)

| Source | Reason recorded | Class | One-line fix |
|---|---|---|---|
| `counties_sc.charleston_delinquent_tax` | `active_months=(10,11,12,1,2)` | **SEASONAL** (Oct–Feb) | None — auto-resumes in October. |
| `counties_sc.cherokee_delinquent_tax` | `active_months=(10,11,12,1)` | **SEASONAL** (Oct–Jan) | None. |
| `counties_sc.colleton_tax_sale` | `active_months=(12,1,2,3)` | **SEASONAL** (Dec–Mar) | None. |
| `counties_sc.sc_delinquent_tax_list` | `active_months=(10,11,12,1)` | **SEASONAL** (Oct–Jan) | None. |
| `national.foreclosure_dot_com` | disabled: edge-WAF 403 to GET/impersonate/stealth; paid preview | **WALLED** + paid | None; redundant with auction.com/Xome. |
| `counties_nc.nc_ecourts_estates` | disabled: AWS-WAF CAPTCHA unsolvable | **WALLED** | None; NC estates covered via Column. |
| `counties_sc.greenville_tax_distress` | disabled: `FORECLOSURE_INCLUDE_GREENVILLE` unset | **FILTERED (by operator scope policy)** | Set the env var if Greenville comes back in scope. |
| `counties_sc.sc_dew_lien_registry` | disabled: cross-reference only | **By design** — feeds `enrichment_dew_liens`, not the board | None. |

---

## 3. Ranked partial-data risks — the 97 swallow sites

Static AST scan of loops over declared endpoint/layer/county/page/feed sets containing a handler that `continue`/`pass`/`break`s without re-raising: **97 sites across 66 modules** (82 in 55 scrapers, 15 in 11 enrichers). Only **4 modules** have adopted `LayerHarvest` (`pickens_delinquent_parcels`, `oconee_flc_assignment`, `oconee_forfeited_land`, `enrichment_helene_damage`). Ranked by rows actually at risk today:

| # | Source | Rows shipped today | Measured loss / exposure | Fix |
|---|---|---|---|---|
| 1 | ~~`counties_nc.nc_ptscloud_delinquent_tax`~~ **FIXED 2026-08-04** (`192ca99`) | **21,463** | Declares **17** tenants, logged **8** `tenant_done`. The other 9 — Burke, Cumberland, Durham, Hertford, Mecklenburg, Randolph, **Rutherford**, Stokes, Wayne — produced **zero log lines**; `_download_delinquent_csv` has **5 silent `return None` exits**, and `if not text: continue` logs nothing. I probed 3 live: Burke/Rutherford/Mecklenburg return **200 with an empty blob list** (genuinely no export today; Madison has one) — so today's data is intact, but a broken endpoint and an empty one are indistinguishable, on the largest source in the board. | **DONE.** Breakages raise `TenantExportBroken`; a clean 200 with no delinquent blob logs `tenant_empty`; loop runs under `LayerHarvest` over `TENANTS`. All 17 probed live 08-04: **8 producing, 9 empty, 0 broken** — data was intact. |
| 2 | `national.landwatch` + `national.landandfarm` | **650 + 650** | **CORRECTED 2026-08-04 — not compliantly fixable.** I first wrote this up as a page-param bug. It is not. landwatch.com is Akamai-walled: every HEAD in the 08-04 run returned 403, and `robots.txt` **itself** returns Access Denied, so no permissive policy can even be read. Absent a readable robots the host is treated as disallowed and pages 2+ are out of reach under the free-and-public rule. Original (wrong) diagnosis kept below for the record. ~~Pagination is dead.~~ Every one of ~26 counties logged exactly `found:25, new:25` then stopped — no page-2 `page_done` anywhere. Cause: `f"{base_url}?page={page}"` against `landwatch.com/{state}-land-for-sale/{county}-county`, whose real pagination is a **path segment**, so page 2 re-serves page 1 → `new == 0` → silent break. Docstring itself says "most counties have 2–5 pages". Unmeasured how many rows are behind pages 2+. | **None available compliantly.** Do not engineer around Akamai. Leave page 1 as-is. |
| 3 | `national.crexi_multifamily` | 0 (was ~220) | Already covered above — the `/search/` redirect is swallowed as `no_grid` and the source silently went from 228 to 0 between 7/10 and 7/24 with no alarm. | See table above. |
| 4 | `national.courtlistener_adversary` | 158 | **4 of 15** court×phrase searches truncated today (`scb`/lift stay, `scb`/363 sale, `scb`/abandonment, `ncwb`/relief from stay), each a `break` out of pagination. The `error` field is **empty string** on all four, so the cause isn't even recorded. | Retry the search page like `brock_scott._page` does; log `type(exc).__name__` when `str(exc)` is blank. |
| 5 | `counties.sitemap_walker` | 30 | **13** endpoint failures absorbed: `polknc.gov` sitemap 404×3, `hendersoncountync.gov` 403×5, `co.pickens.sc.us` 404×3, `spartanburgcounty.gov` 404×2. | Declare the host set and hard-fail on a shrunken sweep. |
| 6 | `national.auction_dot_com` | 388 | **CORRECTED 2026-08-04 — NOT A BUG.** I read `page 2 -> new:0` as dead pagination. The module's own docstring says the opposite and is right: auction.com is an SPA that "Load More"s in place and **embeds the whole result set on page 1**; there is no URL-addressable pagination. NC page 1 already returns all 309, SC all 79, and the loop correctly stops on the first page that adds nothing. The 516 → 388 drift is upstream inventory, not lost rows. (The 27 `405`s here are `link_validator` HEADs, correctly retried as GET — not a loss.) | **None. Do not "fix" this.** |
| 7 | `national.estate_sales` | 7 | **Half the source is dead**: `estatesale.com/search?zip=…` returns **404 on all 4 zips**; only `estatesales.net` works (81/zip). Failure is logged then discarded. | Drop the dead host or repair its URL shape. |
| 8 | `counties_sc.sc_public_index` | 1,743 | 2 swallow sites over `SEARCHES`; no failures logged today, but a dropped search is invisible. This source has previously vanished whole (3,628 rows) without an alarm. | `LayerHarvest` over `SEARCHES`. |
| 9 | `counties_nc.nc_county_pdf_delinquent_tax` | 8,922 | 1 swallow site over a county/PDF set; no failures today, but a dropped county is a 4-figure silent hole. | `LayerHarvest`. |
| 10 | ~~`link_validator`~~ **FIXED 2026-08-04** (`82ad439`) | tags 3,819 bankruptcy rows | Self-inflicted: 24-way concurrent HEADs drew **1,043 of 3,349 `429`s** from courtlistener.com (31%). No rows drop, but ~1,000 leads get `link_check.status="auth"` purely from our own rate — a misleading quality signal, and impolite. | **DONE.** `LINK_PER_HOST_WORKERS` (default 4) bounds in-flight requests per hostname; global pool stays wide. Also deduped by URL (57.5% of the pass was repeat requests) and gated on freshness. |

**Not at risk (verified, don't chase these):** `law_firms.brock_scott` took 17 × `429` today but its retry loop recovered every page — `failed_pages: null`, 73 rows kept. That's the pattern the other nine should copy.

Key paths: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/base_scraper.py` (`safe_run`, outcome classification), `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/layer_guard.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/counties_nc/nc_ptscloud_delinquent_tax.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/national/landwatch.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/national/crexi_multifamily.py`.