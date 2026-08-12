## CAPTURE-RATE AUDIT — Oconee, Cherokee, Union, Laurens (all SC)

Board read: `/Users/cashhigh/foreclosure-scraper/docs/listings.json` (25,552 leads, written 2026-08-03T18:01Z per `docs/run_meta.json`). NC Cherokee and NC Union are in `SCOPE_DENY_COUNTIES` (`src/foreclosure_scraper/config.py:105,117`), so SC-only board rows are correct by scope, not a gap.

| county | source | upstream now | on board | delta | cause | verdict |
|---|---|---|---|---|---|---|
| Oconee | `counties_sc.oconee_forfeited_land` | 1,024 features (L0 948 + L1 76) → 533 distinct TMS | 505 | -28 | `_active_only` drops terminal status; upstream L1 has SOLD 52 / L0 REDEEMED 3 / removed 1 | CAPTURING |
| Oconee | `counties_sc.oconee_flc_assignment` | 657 rows (L1 468 + L0 189); buyable 583 (434 `Status='NONE'` + 149 `Redeem_Assign='NONE'`) | **0** | -583 | Scraper only entered the registry in `07b04cf` (2026-08-04, "registry bug that was dropping 27 scrapers") and its DATELESS entry in `58b48d2` (2026-08-04). Both land AFTER the 08-03 board write | **BROKEN (fix in flight)** |
| Oconee | `counties.multi_year_delinquent_tax` | 1,561 (DT2025 645, DT2024 476, DT2023 440) | **0** (0 globally) | -1,561 | Built `8c51651` 2026-08-03; no full board write since. Never proven in production | **BROKEN (unproven)** |
| Oconee | `counties_sc.oconee_tax_sale` | 4 CSV rows, **0** real parcel rows (2026 sale = Nov 9; list posts Oct 21) | 0 | 0 | Genuinely empty, seasonal | CAPTURING |
| Oconee | `counties_sc.sc_public_notices` | 71 scraped statewide on the 07-31 full run | **0** | -71 | `orchestrator.source_all_filtered` logged: "OK with rows but 0 reached the dashboard post-filter". Dropped pre-dedupe by scope/active/flip | **BROKEN** |
| Oconee | `counties_sc.terry_howe_flc` | 5 TMS attributable (city→county) across the full 515-auction catalog; **0** pass the title gate | 0 | -5 | `_TITLE_COUNTY` requires literal "`<County> County, SC`". "Westminster, SC …", "39 Properties in South Carolina" are dropped whole | **BROKEN (title-gate)** |
| Oconee | `nc_heir_estate_parcels` | **60** heir/estate parcels on `arcserver2.oconeesc.com/.../CitizenServe/MapServer/5` | 0 | -60 | Oconee deliberately omitted from `_HEIR_COUNTIES` with the comment "owner field does not retitle -> 0". Measured today: that is false | **NOT-WIRED** |
| Oconee | `sc_county_rosters` | unmeasured | 7 | ? | Disclaimer requires clicking Accept (terms acceptance) and the live run is already driving it. Not measured | unmeasured |
| Oconee | `sc_public_index` / `_lis_pendens` | unmeasured (406/400 ToS wall) | 360 / 13 | ? | Manual saved-page lane | unmeasured |
| Oconee | `sc_probate_net`, `column_legal_notices`, `sc_tax_delinquent`, `sc_flc` | 0 (Column measured live today; Pickens control returned 3, so the API and filter format are healthy) | 0 | 0 | Genuinely empty upstream | CAPTURING |
| Cherokee | `counties_sc.cherokee_delinquent_tax` | **0 parcel-list PDFs**. `/delinquent-tax/` has 3 uploaded PDFs today, all procedural; `/tax-sale-bidders/` has 1 (privacy policy) | 0 | 0 | Genuinely empty + `active_months` (10,11,12,1) | CAPTURING |
| Cherokee | WP media index (`wp-json/wp/v2/media`) | 12 "tax sale" + 9 "delinquent" objects incl. `Tax-Sale-List-2024` (529 unique TMS) and `2023 Delinquent Tax List` | 0 | -529+ | Ledgers are uploaded but never anchored, so the PDF-anchor scraper structurally cannot see them | **NOT-WIRED** |
| Cherokee | `national.jail_bookings` | unmeasured by policy (roster records embed DOB, endpoint cannot be column-limited). 1,728 rows across 6 portals last run | **1** | ~-N | **Proven**: jail listings carry no parcel / address / case number, so `Listing.dedupe_key()` falls to `url:https://cherokee-so-sc.zuercherportal.com/` — identical for every inmate. Verified: 3 distinct inmates → 1 after `dedupe()` | **BROKEN** |
| Cherokee | `counties_sc.sc_public_notices` | 71 scraped | **0** | -71 | Same all-filtered drop as Oconee | **BROKEN** |
| Cherokee | `counties_sc.terry_howe_flc` | 0 across all 515 auctions | 0 | 0 | Genuinely empty | CAPTURING |
| Cherokee | `nc_heir_estate_parcels` | n/a | 0 | n/a | No `COUNTY_GIS` entry; county runs no ArcGIS. Only free parcel layer is `canoewood/SC_GaffneyCity_01` (12,764 polys / 7,116 address points), unwired | **NOT-WIRED** |
| Cherokee | `sc_public_index` / `_lis_pendens` | unmeasured (wall) | 462 / 29 | ? | Manual lane | unmeasured |
| Cherokee | `sc_county_rosters` | unmeasured | **0** | ? | Accept-terms gate | unmeasured |
| Cherokee | `sc_probate_net`, `column_legal_notices`, `sc_flc`, `sc_tax_delinquent` | 0 (Column measured live) | 0 | 0 | Genuinely empty / 403 Cloudflare on the county host | CAPTURING |
| Union | `counties_sc.sc_rod_cott` (only county-specific source) | 39 (run_health 2026-08-02) | **1** | -38 | **Proven**: parcel # and situs sit in `legal_description` but `parcel_id` / `street_address` / `case_number` are null, so `dedupe_key()` = `url:https://recordroom.cottsystems.com/unionsc/guest/Search/records` for every row. Verified: 3 distinct records → 1 after `dedupe()` | **BROKEN** |
| Union | `counties_sc.sc_public_notices` | 71 scraped | **0** | -71 | Same all-filtered drop | **BROKEN** |
| Union | `counties_sc.terry_howe_flc` | 18 TMS attributable across 515 auctions; **0** pass the title gate | 0 | -18 | Title-gate: "Union, SC – Vacant lot", "29 Properties in South Carolina" etc. | **BROKEN (title-gate)** |
| Union | `nc_heir_estate_parcels` | **4** on `UNION_SC_PARCELS_WFL1/FeatureServer/2` | 2 | -2 | `_is_decedent` entity filter (LLC/TRUST/etc.) | PARTIAL-explained |
| Union | `sc_public_index` / `_lis_pendens` | unmeasured (400 wall) | 399 / 7 | ? | Manual lane | unmeasured |
| Union | `sc_county_rosters` | unmeasured | **0** | ? | Accept-terms gate | unmeasured |
| Union | `column_legal_notices` | 0 (measured live) | 0 | 0 | Genuinely empty | CAPTURING |
| Union | delinquent tax / FLC | n/a | 0 | n/a | `sc_tax_delinquent` Union host DNS-fails; `sc_flc` Union is a JS shell; the FLC assignment list is released in person, cash only, at the Auditor's Office, never posted | NOT-WIRABLE (free lane) |
| Laurens | `counties_nc.nc_heir_estate_parcels` | **169** on `laurenscountygis.org/.../Pebble/TaxParcel/MapServer/5` (layer total 44,880) | 78 | -91 | `_PER_COUNTY_CAP = 80` hard cap. 54% of the county's heir inventory never leaves the scraper | PARTIAL-explained (cap) |
| Laurens | `counties_sc.terry_howe_flc` | 25 TMS pass the title gate (3 "Laurens County, SC" auctions); **+59** more TMS attributable but dropped | 29 (cumulative) | -59 | Title-gate drops "Laurens, SC – …", "Clinton, SC – …", "Gray Court, SC – …", "44 Properties in South Carolina" | PARTIAL / title-gate |
| Laurens | `counties_sc.sc_public_notices` | 71 scraped | **0** | -71 | Same all-filtered drop | **BROKEN** |
| Laurens | `sc_public_index` / `_lis_pendens` | unmeasured (wall) | 622 / 38 | ? | Manual lane | unmeasured |
| Laurens | `sc_county_rosters` | unmeasured | 4 | ? | Accept-terms gate | unmeasured |
| Laurens | `column_legal_notices` | 0 (measured live) | 0 | 0 | Genuinely empty | CAPTURING |
| Laurens | delinquent tax / FLC / probate | n/a | 0 | n/a | Laurens does not attach its delinquent-tax list to the county site; FLC link is a `<li>` with no href; Laurens is not in the `sc_probate_net` dropdown | NOT-WIRABLE / NOT-WIRED |
| Laurens | `newspapers.index_journal` | 6 scraped | 0 | -6 | Greenwood paper, Greenwood is a DENY county. Not a Laurens source | N/A |

## The failure mode that matters most: upstream rows, board zero

**1. `dedupe_key()` url-fallback collapse — confirmed by execution, not inference.** `src/foreclosure_scraper/models.py:228`. Any listing with no `parcel_id`, no `street_address` and no `case_number` returns `f"url:{self.source_url}"`. Sources that emit one constant `source_url` for the whole feed therefore collapse to exactly one board row:

- `national.jail_bookings`: 1,728 rows last run → **4** on board (one per portal URL), Cherokee = 1.
- `counties_sc.sc_rod_cott`: 39 Union rows → **1** on board, even though `raw['cott']` and `legal_description` carry the parcel (`072-00-00-048 000`) and the situs (`559 RILEY ROAD BUFFALO, SC 29321`). Promoting those two into `parcel_id` / `street_address` fixes Union's only county-specific source outright.

**2. Two Oconee sources are wired but have never reached a board write.** `oconee_flc_assignment` (583 buyable rows) and `multi_year_delinquent_tax` (1,561 Oconee rows) both landed in commits dated 2026-08-03/04, after the 2026-08-03T18:01Z board write, and one of them was inside the 27 scrapers the registry bug was dropping. These should appear when the live run publishes. If they do not, that is the thing to re-check first.

**3. `counties_sc.sc_public_notices` scrapes 71 and lands 0** for all four counties. Hard evidence in `logs/local-run-20260731T110836.log`: `orchestrator.source_all_filtered source=counties_sc.sc_public_notices scraped=71`. The drop happens before dedupe (scope / active / flip chain), and the slug is already in `DATELESS_OK_SOURCES`, so the suspect is the scope predicate on rows whose county the scraper had to infer from the case code. Same warning fires for `pickens_tax_sale` (160), `zacchaeus` (145), `city_websites.search` (165), `craigslist_fsbo` (245).

**4. `terry_howe_flc` title gate.** `_county_of()` (`terry_howe_flc.py`) only accepts titles matching `<County> County, SC`. Measured over the full catalog (515 auctions, 6 pages): the gate accepts **25** TMS rows for the four counties (all Laurens) and drops **82** more that the engine's own `_upstate_city_to_county` lookup resolves cleanly (Laurens 59, Union 18, Oconee 5). Second, smaller issue: the scraper fetches `per_page=100` once with no pagination, so it reads 100 of 515 auctions (`X-WP-Total: 515`, 6 pages).

**5. `nc_heir_estate_parcels` is misconfigured for Oconee and capped for Laurens.** Oconee is excluded with the comment "Oconee's owner field does not retitle -> 0"; the live layer returns **60** heir/estate parcels. Laurens has 169 upstream against a `_PER_COUNTY_CAP = 80`.

## What I deliberately did not measure

- `publicindex.sccourts.org` rosters and the Public Index (`sc_county_rosters`, `sc_public_index`, `sc_public_index_lis_pendens`): reaching them requires clicking the disclaimer Accept button, which is a terms acceptance, and the live run is already hitting that host. Upstream **unmeasured**, not zero.
- Cherokee Zuercher roster size: the endpoint returns DOB in every record and cannot be column-limited, so per this audit's privacy rule I did not re-fetch it. The delta is proven from `dedupe_key()` regardless of the exact roster size.

Scratch scripts: `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/` (`board_counts.py`, `up_oconee.py`, `up_oc2.py`, `up_th3.py`, `up_cherokee.py`, `up_heir.py`, `up_column.py`). No board writes, no git state changes, no scraper runs.