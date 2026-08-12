# CAPTURE-RATE AUDIT — Rutherford / Burke / Lincoln / McDowell / Polk / Transylvania / Mitchell

**Measurement basis.** Registry = 132 wired scrapers (`discover()` run live). Board = `/Users/cashhigh/foreclosure-scraper/docs/listings.json`, 25,552 rows, written 2026-08-03 14:01, of which **3,435** carry one of these 7 counties. Upstream numbers below are **measured live today (2026-08-04, ~12:30-13:00 ET)** by running each scraper's own `fetch()` once, or by a single GET/count endpoint. Board numbers are shown as `primary + also_seen_in`.

**Two board-wide facts that explain most benign deltas:**
1. The last *full multi-source scrape* that touched these counties has `last_seen = 2026-07-31`. Only 5 sources show 08-02/08-03 (partial/enrichment passes). So the board is a 4-day-old snapshot.
2. Three scrapers were **rewritten after that snapshot**: `national.nc_upset_bids` + `counties_nc.polk_tax` (commit `8d45211`, 2026-08-02 15:33) and `counties_nc.rutherford_tax` (commit `8c51651`, 2026-08-03 16:38). The last `run_health` is dated 2026-08-02 09:55 — *before* all three. Their zeros are stale-board, not parser failure.

---

## Table

| County | Source | Upstream now | On board | Delta | Cause | Verdict |
|---|---|---|---|---|---|---|
| **Rutherford** | `counties_nc.rutherford_tax` | **9,328** bills / $5,639,937.64 | 5+0 | −9,323 | Rewrite landed 08-03 16:38; the 5 board rows are the retired frozen-mirror parse (`first_seen 2026-06-26`, no `judgment_amount`, one row with the parcel embedded in the street string). Never run into the board. | PARTIAL-explained (stale board) |
| Rutherford | `national.nc_upset_bids` | **25** | 0+0 | −25 | Fix landed 08-02 15:33, after the last run (`run_health` = "EMPTY (verified)"). Zero rows with this slug board-wide and zero `also_seen_in` references. | **BROKEN (never landed)** |
| Rutherford | `law_firms.kania` | **14** (9 survive scope/active/flip) | 0+0 | −14 | Zero kania rows board-wide. Spot-checked 4 Kania parcels by address — none on the board. Not a dedupe merge. | **BROKEN** |
| Rutherford | `counties_nc.nc_county_tax_foreclosure` | 6 | 3+0 | −3 | 07-31 snapshot; page repointed | PARTIAL-explained |
| Rutherford | `counties_nc.rutherford_wildfire_tax` | unreachable (vendor's own `TotalRecords` = 29,319) | 0+0 | n/a | Both hosts publish `Disallow: /`; robots preflight fails closed by design. No override exists. | NOT-WIRED (compliance wall) |
| Rutherford | `counties_nc.nc_ptscloud_delinquent_tax` | **0** (`GetTaxpayerDownloadList` → `[]`) | 0+0 | 0 | Valid tenant, no export blob posted. Henderson on the same host returns a 5.9 MB blob dated today — so the probe is sound. **Genuinely empty, not broken.** | CAPTURING |
| Rutherford | `national.cash_buyer_deeds` / `nc_rod_substitute_trustee` (Cott) | 0 | 0+0 | 0 | `cotthosting.com/NCRUTHERFORDEXTERNAL/.../SrchDocType.aspx` now returns **`<title>eSearch \| Account Sign In`** — the ROD went behind a login. | NOT-WIRED (login wall, **new**) |
| Rutherford | `counties_nc.nc_ecourts_lis_pendens` | 6 | 0+0 | −6 | Rolling recent-filings window; nothing Rutherford landed at 07-31 | PARTIAL-explained |
| Rutherford | `counties_nc.nc_ecourts_divorce` | 4 | 0+0 | −4 | same | PARTIAL-explained |
| Rutherford | `counties_nc.nc_heir_estate_parcels` | 80 | 133+1 | +54 | Board > upstream = carryover persistence | CAPTURING |
| Rutherford | `counties.column_legal_notices` | 7 | 1+1 | −5 | 07-31 snapshot | PARTIAL-explained |
| Rutherford | `newspapers.daily_courier` | **0** | 0+0 | 0 | Page HTTP 200, 262 KB, `foreclos` count = 0. Genuinely no foreclosure notices today (3 on 08-02). | CAPTURING |
| Rutherford | `public_notices.gannett_obituaries` | 1 | 0+**17** | ~0 | Deduped into other rows (`also_seen_in`) | CAPTURING |
| **Burke** | `national.cash_buyer_deeds` (CCHS) | **62** | 0+0 | −62 | See systemic note below | **BROKEN** |
| Burke | `national.nc_upset_bids` | 3 | 0+0 | −3 | as Rutherford | **BROKEN** |
| Burke | `law_firms.kania` | **20** (17 survive filters) | 0+0 | −20 | as Rutherford | **BROKEN** |
| Burke | `counties_nc.nc_rod_substitute_trustee` (CCHS) | 11 | 0+1 | −10 | Board-wide this source has 3 rows, `last_seen 2026-07-01` — hasn't landed in 5 weeks despite 19 fetched on 08-02 | **BROKEN / stalled** |
| Burke | `counties_nc.nc_ptscloud_delinquent_tax` | **0** (`[]`) | 0+0 | 0 | Valid tenant, no export blob | CAPTURING |
| Burke | `counties.column_legal_notices` | 28 | 10+3 | −15 | 07-31 snapshot | PARTIAL-explained |
| Burke | `counties_nc.nc_ecourts_lis_pendens` | 11 | 9+0 | −2 | rolling window | CAPTURING |
| Burke | `counties_nc.nc_heir_estate_parcels` | 56 | 52+0 | −4 | snapshot | CAPTURING |
| Burke | `public_notices.ncnotices` | 4 | 1+2 | −1 | dedupe + snapshot | CAPTURING |
| Burke | `counties_nc.nc_govdeals_real_property` | 0 | 0+0 | 0 | Master search returns 3 rows, none in footprint; legacy seller 29265 non-resolving | CAPTURING (empty) |
| **Lincoln** | `counties_nc.nc_county_pdf_delinquent_tax` | **1,406** | 199+2 | −1,205 | **Not stale-board.** Board parcel keys are 10-12-digit GIS PINs (`2656983646`); upstream now emits 4-6-digit IDs (`00116`). **Zero key overlap** between the 168 distinct board PINs and the 1,406 upstream. The Lincoln PDF's ID column changed shape. All 1,406 pass scope/active/flip and survive `dedupe()` unchanged. | **BROKEN (ID-column drift)** |
| Lincoln | `national.cash_buyer_deeds` (CCHS) | **45** | 0+0 | −45 | systemic note below | **BROKEN** |
| Lincoln | `law_firms.kania` | 8 (8 survive) | 0+0 | −8 | as above | **BROKEN** |
| Lincoln | `counties_nc.nc_ecourts_lis_pendens` | **25** | 4+0 | −21 | Largest lis-pendens gap of the 7. Rolling window + 4-day-stale board only partly covers it. | PARTIAL-explained, watch |
| Lincoln | `national.nc_upset_bids` | 2 | 0+0 | −2 | as above | **BROKEN** |
| Lincoln | `counties_nc.nc_heir_estate_parcels` | 44 | 45+3 | +4 | carryover | CAPTURING |
| Lincoln | `counties_nc.nc_ptscloud_delinquent_tax` | n/a | 0+1 | — | Lincoln is not a ptscloud tenant (runs a different portal) | NOT-WIRED (correct) |
| Lincoln | `counties_nc.nc_rod_substitute_trustee` | n/a | 0+1 | — | Deliberately excluded (different CCHS install, `us4/LincolnNC2`) | NOT-WIRED (known) |
| **McDowell** | `counties_nc.nc_county_pdf_delinquent_tax` | 2,260 | 2,084+13 | −163 | 93% capture; snapshot + dedupe | CAPTURING |
| McDowell | `national.cash_buyer_deeds` (Logan) | **148** | 24+5 | −119 | Only county where this source landed anything at all | **PARTIAL / BROKEN** |
| McDowell | `counties_nc.nc_rod_logan` | 9 | 2+2 | −5 | 60-day rolling window vs 07-31 snapshot | PARTIAL-explained |
| McDowell | `counties_nc.nc_heir_estate_parcels` | 71 | 45+24 | −2 | dedupe (24 in `also_seen_in`) | CAPTURING |
| McDowell | `counties_nc.nc_ecourts_lis_pendens` | 6 | 7+17 | +18 | carryover + dedupe | CAPTURING |
| McDowell | `counties_nc.nc_ecourts_divorce` | 4 | 0+7 | +3 | **All merged into other rows** — the 0 primary is dedupe, not loss | CAPTURING |
| McDowell | `counties.column_legal_notices` | 54 | 5+69 | +20 | dedupe (69 in `also_seen_in`) | CAPTURING |
| McDowell | `counties_nc.nc_county_tax_foreclosure` | 1 | 0+1 | 0 | dedupe merge | CAPTURING |
| McDowell | `national.nc_upset_bids` / `law_firms.kania` | 0 / 0 | 0 / 0 | 0 | genuinely nothing published | CAPTURING |
| **Polk** | `counties_nc.polk_tax` | **1** (`P65-38`, sale 2026-09-01 11 AM, bid `$TBD`) | 0+0 | −1 | `$TBD` regression fix committed 08-02 15:33; `run_health` 08-02 09:55 still shows "REGRESSED (expected ≥ 1)". Scraper re-run today parses the row correctly. Parcel `P65-38` is absent from the board. | PARTIAL-explained (fix not yet run) |
| Polk | ROD via Cott (`cash_buyer_deeds` + `nc_rod_substitute_trustee`) | 0 | 0+0 | 0 | `ncpolkexternal/.../SrchDocType.aspx` and `SrchName.aspx` return the **identical 54,258-byte body** titled `eSearch \| Quick Name Search` — the doc-type form is gone, so the POST binds to nothing and `cott.py` swallows it and returns `[]`. Silent. | **BROKEN (silent)** |
| Polk | `newspapers.tryon_bulletin` | **0** | 0+0 | 0 | `/category/legal-notices/` is a hard **404**; the two `?s=` searches return only 2010-2013 editorial articles, no current notices. Nothing to capture today, but the category URL is dead — a latent miss if Polk notices resume there. | CAPTURING (empty) + dead-URL flag |
| Polk | `counties_nc.nc_ecourts_lis_pendens` | 12 | 2+0 | −10 | rolling window + stale board | PARTIAL-explained, watch |
| Polk | `national.nc_upset_bids` / `law_firms.kania` | 1 / 1 | 0 / 0 | −2 | as above | **BROKEN** |
| Polk | `counties_nc.nc_heir_estate_parcels` | 70 | 95+0 | +25 | carryover | CAPTURING |
| Polk | `public_notices.ncnotices` | 3 | 4+1 | +2 | carryover | CAPTURING |
| **Transylvania** | `national.cash_buyer_deeds` (Logan) | **94** | 0+0 | −94 | Logan Transylvania host responds (5 distress docs via `discover_recent_nods`) — the vendor works, the source still landed nothing | **BROKEN** |
| Transylvania | `counties_nc.nc_rod_logan` | 5 | 12+0 | +7 | carryover | CAPTURING |
| Transylvania | `counties_nc.nc_ecourts_lis_pendens` | 22 | 29+6 | +13 | carryover | CAPTURING |
| Transylvania | `counties_nc.nc_ecourts_divorce` | 8 | 9+0 | +1 | carryover | CAPTURING |
| Transylvania | `counties_nc.nc_heir_estate_parcels` | 72 | 75+1 | +4 | carryover | CAPTURING |
| Transylvania | `counties.column_legal_notices` | 2 | 1+1 | 0 | dedupe | CAPTURING |
| Transylvania | `counties_nc.nc_govdeals_real_property` (+ county news feed) | 0 | 0+0 | 0 | storefront `tcncre` non-resolving; master search has no in-footprint rows | CAPTURING (empty) |
| **Mitchell** | `counties_nc.nc_rod_logan` | **0** | 0+0 | 0 | `search.mitchelldeeds.com` responds; `logan.discovered county=Mitchell distress=0`. Genuinely nothing in 60 days (county pop. ~15k). | CAPTURING (empty) |
| Mitchell | `national.cash_buyer_deeds` (Logan) | 0 | 0+0 | 0 | same host, same result | CAPTURING (empty) |
| Mitchell | `counties_nc.nc_heir_estate_parcels` | 80 | 76+0 | −4 | snapshot | CAPTURING |
| Mitchell | `counties_nc.nc_ecourts_lis_pendens` | 1 | 0+0 | −1 | rolling window | PARTIAL-explained |
| Mitchell | `counties_nc.nc_ecourts_divorce` / `nc_upset_bids` / `kania` | 0 | 0 | 0 | genuinely nothing | CAPTURING |
| Mitchell | `public_notices.ncnotices` | 0 | 1+0 | +1 | carryover | CAPTURING |
| **All 7** | `public_notices.nc_notices_counties` | **unmeasured** (900 s Playwright flow, 11 county postbacks — declined while the live run is hitting ncnotices.com) | **0 board-wide** | — | Absent entirely from the 2026-08-02 `run_health` (one of 10 registry slugs missing from it) — it did not run. `expected_min_count = 0` so it never alarms. | **BROKEN / never lands** |
| All 7 | `counties.multi_year_delinquent_tax` | 2,095 (Buncombe/Oconee/Pickens only) | 0 | 0 | Out of these counties by design | NOT-WIRED (correct) |
| All 7 | `national.jail_bookings` | 1,728 fetched 08-02; board-wide **4** rows (Buncombe/Cleveland/Cherokee SC/Anderson SC) | 0 | 0 | P2C/Zuercher/Citizen Connect vendors cover none of these 7 counties | NOT-WIRED for these counties (but see note) |

---

## Sources where upstream has rows and the board has ZERO — the failure mode that matters

Ranked by rows lost:

1. **`national.cash_buyer_deeds` — 491 fetched today, 24 on the board board-wide, all McDowell.** Burke 62, Transylvania 94, Lincoln 45 → **0 each**. `run_health` 2026-08-02 recorded 499 fetched / "OK (499)". The slug is in `DATELESS_OK_SOURCES`, the counties are in-footprint, and the rows carry no `opening_bid` so `_flip_candidate` keeps them — none of the three visible filters explains it. Board `first_seen` for the 24 surviving rows is spread over 5 dates, so it isn't one bad run either. **Cause not determined — this is the single largest unexplained loss in these 7 counties (~330 rows/run).**

2. **`law_firms.kania` — 59 in-footprint upstream, 43 survive `in_scope` + `_active_only(120)` + `_flip_candidate` (Burke 17, Rutherford 9, Lincoln 8, Polk 1, Cleveland 8), 0 on the board board-wide.** Verified not a dedupe merge: four Kania addresses (243 Pleasant View Loop, 227 Table Rock Terrace NW, 7087 Silver Creek Lane, 578 E. Settings Blvd NW) appear nowhere on the board. `run_health` 08-02 recorded only 6 fetched vs 59 today, so the feed itself also swung — but 6 → 0 landed is still a total loss.

3. **`counties_nc.nc_county_pdf_delinquent_tax` (Lincoln) — 1,406 upstream, 199 on board, zero parcel-key overlap.** Not staleness: the ID column changed shape (10-12-digit PIN → 4-6-digit). Today's 1,406 rows would land as brand-new keys, and the 199 legacy rows will never re-match. McDowell on the same scraper is fine (2,260 → 2,084, 93%).

4. **`national.nc_upset_bids` — 35 rows today (Rutherford 25, Cleveland 4, Burke 3, Lincoln 2, Polk 1), 0 board-wide, 0 in any `also_seen_in`.** Explained by the 08-02 15:33 rewrite post-dating the last full run — should self-heal on the live run. Worth re-checking after it lands.

5. **`counties_nc.nc_rod_substitute_trustee` — 19 fetched 08-02, 11 Burke upstream today, 3 rows board-wide with `last_seen 2026-07-01`.** Stalled for 5 weeks.

6. **`public_notices.nc_notices_counties` — 0 board-wide, and it did not appear in the last run at all.** `expected_min_count = 0` means a silent no-show never raises. Same silent-absence class as the 27-scraper registry bug fixed in `07b04cf`.

7. **`counties.sitemap_walker` (30 fetched) and `city_websites.search` (165 fetched) — both 0 rows board-wide.** Outside this audit's county scope to attribute, but flagged: they fetch and land nothing anywhere.

## Two newly-measured access walls (not bugs, do not "fix" by bypassing)

- **Rutherford ROD (Cott) is now login-gated** — `SrchDocType.aspx` and `SrchName.aspx` both title `eSearch | Account Sign In`. This kills `cash_buyer_deeds` and `nc_rod_substitute_trustee` for Rutherford. Previously free.
- **Polk ROD (Cott) doc-type form is gone** — both paths serve one identical `Quick Name Search` body. This is a *drift*, not a wall, and is fixable: `rod/cott.py::discover_recent_nods` posts `ctl00$cphMain$ddlDocType` into a page that no longer has that control, then swallows the failure and returns `[]`.

## Also worth noting

- `counties_nc.rutherford_wildfire_tax` is correctly inert behind `Disallow: /`. Its 29,319 figure is the vendor's own `TotalRecords`, never harvested.
- `counties_nc.nc_ptscloud_delinquent_tax` reads **genuinely empty** for Rutherford and Burke — the tenants are valid and Henderson on the same host returned a blob timestamped `2026-08-04T06:02:41`, so the probe is proven live. Do not chase this one.
- `newspapers.daily_courier` and `newspapers.tryon_bulletin` are **genuinely empty today**, not broken — but Tryon's `/category/legal-notices/` is a hard 404 and should be repointed before the next Polk notice cycle.

Relevant files: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/rod/cott.py` (silent `return []` at the doc-type POST), `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/national/cash_buyer_deeds.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/counties_nc/nc_county_pdf_delinquent_tax.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/newspapers/tryon_bulletin.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/main.py` (`DATELESS_OK_SOURCES`, lines 302-452).