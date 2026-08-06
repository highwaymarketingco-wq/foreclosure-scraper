All 33 county rows confirmed, including the 10 missing coastal/small counties. The critic's completeness point is verified: the matrix listed 23, board has 33 counties with leads. Note Onslow/Dare/Pender/Carteret/New Hanover all show 0% address (coastal address resolution not wired), and Pender/Dare/Onslow do carry `tax_lien` leads confirming the delinquent-tax lane is partially live there.

I have everything needed. Writing the final integrated ledger as my return value.

---

# MASTER GAP LEDGER — Free/Public Motivated-Seller Lead Engine (NC + SC footprint) — FINAL

Board verified live 2026-07-03 against `/Users/cashhigh/foreclosure-scraper/docs/listings.json` (n=17,003). Address 60.9% filled, owner_name 89.9%, parcel_id 88.0%, equity 6.9% (1,166 leads), tax_owed 39.2% (6,672). Recorded loan-dollar (DOT principal) figures: 0.0%. Judgment-dollar figures: 187 leads (1.1%). Opening-bid figures: 723 leads (4.3%).

Status legend: **HAVE-auto** (wired scraper fills it now) / **PARTIAL** (some coverage, uneven) / **MANUAL-gather** (operator pulls, no compliant scraper) / **FOIA-licensed** (records request or paid vendor) / **WALL-dead** (no free path, blocker named).

---

## 1. Executive gap summary — the biggest gaps

1. **Recorded loan$ = 0.0% of the board, but judgment$ is already on 187 leads (1.1%).** Every equity figure on the board (1,166 leads / 6.9%) is a proxy: auction opening bid, judgment amount, or last-sale-times-LTV amortized. Zero leads carry an actual recorded Deed-of-Trust principal. Note the nuance: `judgment_amount` is populated on 187 leads (a MEDIUM-confidence input already sitting on the board), even though it is only the selected `amount_owed` proxy on 8 of them. **One-line fix:** the DOT-image OCR pipeline (`enrichment_dot_ocr.py`) is built and proven (GARRETT to $56,097 from a free Spartanburg image) but hardcoded to `_TARGET = ("SC","Spartanburg")`, capped at 25/run, gated to HOT/WARM only, and has never been run at scale. Raise the cap, drop the grade gate, let it grind nightly. This alone converts the largest SC county from LOW-confidence proxy to HIGH-confidence recorded figures.

2. **Two big NC tax counties are 2-4% address-filled: McDowell 2% (2,331 no-address leads), Lincoln 4% (1,418).** Root cause verified live: `_query_parcel()` in `enrichment_gis_attrs.py` line 282 does an exact `=` match on the raw parcel string with no normalization. The delinquent-tax PDF stores dashed parcels (`1728-00-87-8115`) but the county GIS `parno` field is clean (`172800878115`), so every lookup returns 0 rows. **One-line fix:** dash-strip and retry variants in `_query_parcel` (+add `PARCELID` to `_PARCEL_FIELDS` for Lincoln's short account numbers). Measured yield: McDowell 85%, Lincoln 100% on samples. Combined with Transylvania (39) and Georgetown (266), the full address-resolver fix unlocks **4,054 no-address leads** across four counties.

3. **Charleston 19% address-filled (312 leads, mostly probate).** These carry the decedent name in `owner_name` but the resolver matches on `defendant` (the petitioner/heir, wrong person), and 45 leads have placeholder town-centroid coords that point-in-polygon correctly refuses. **One-line fix:** have `address_owner_v2` fall back to `owner_name` against SCDOT `OWNER1` when source is probate/estate. Up to 236 leads.

4. **Divorce = 1 lead on 17,003.** The coded NC divorce scraper points at the AWS-WAF-walled Smart Search SPA (HTTP 405 + CAPTCHA, compliant dead-end). **One-line fix:** the open NC Judgment Search JSON the engine already drives for lis-pendens serves `causeOfActionDesc="FAM - Divorce"` with both spouses structured; add the family cause to the filter set in `nc_ecourts_lis_pendens.py` and the board goes 1 to live statewide next run. SC divorce stays manual (FCCMS ToS forbids automation).

5. **Federal REO disposition feeds are landing ~2% of their claimed volume — effectively a soft wall, not a HAVE.** Of the 110 REO leads on the board, 76 come from `zillow_bulk`; the four federal disposition sources the engine showcases land only ~29: **Fannie HomePath 6, HUD HomeStore 6, Freddie HomeSteps 1, VRM/VA 16**. HomePath is landing 6 of a claimed "315 NC/SC on one bbox," so the bbox pagination or the ingest join is dropping ~98% of rows. **One-line fix:** treat §2.6 as BUILD/BROKEN, not HAVE — debug HomePath pagination/ingest first (highest volume), then the VRM card regex.

6. **20% of the board (elderly_disabled, 3,505 leads) is a single county's exemption roll — 100% Buncombe.** This is the 2nd-largest source and it is entirely concentrated in one county. If Buncombe's senior-exemption roll drifts, delists, or changes format, a fifth of the board evaporates. **One-line fix:** none instant — but this makes "senior-exemption flags for more counties" a top-priority **diversification** item (BUILD-READY endpoints identified), not a nice-to-have, and it belongs on the fragility watch list.

7. **Full NC 105-369 delinquent roll is missing in four SPA-portal counties.** tax_owed is on 39.2% of the board (strong), but Cleveland/Gaston/Polk/Transylvania publish only the foreclosure subset (Government Window / DevNet / Revize / BAS SPAs, no bulk file), so the full delinquent roll is a true wall there. **One-line fix:** none free for the full roll in those four; route to manual per-parcel or accept the foreclosure subset.

---

## 2. Signal ledgers

### 2.1 Lis Pendens / Pre-Foreclosure

**HAVE-auto (1,178 leads):** NC eCourts Judgment Search JSON — `POST portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`, open/keyless/no-CAPTCHA. Serves lis-pendens statewide, facet-selectable per county (11 WNC + 5 coastal in `TARGET_COUNTIES`). Returns case#, county, both parties structured, ordered date, disposition. No property address (resolves downstream via owner to GIS).

- **Manual path:** SC Common Pleas LP lives on `publicindex.sccourts.org` = ToS-no-scrape wall (406 to automation). MANUAL-gather via the saved-HTML offline-parser lane (`scripts/parse_publicindex_export.py`) — operator accepts the disclaimer, saves the result page.
- **Scrape path:** NC statewide JSON (built). No compliant SC automated LP lane exists — that is the explicit "none, here is why" (SC PublicIndex ToS-no-scrape).

**GAPS:**
- **Loan$ / equity on the LP cohort:** the pre-foreclosure lead has more runway than an NOD, but carries no recorded debt figure. Only fix is the DOT-OCR path (see enrichment ledger).
- **Bankruptcy-stay pre-foreclosures** (Ch.13 filers stopping a state foreclosure) are a distinct pre-foreclosure lane sitting in RECAP, not eCourts. See Federal/Bankruptcy below.

### 2.2 Foreclosure (judicial + power-of-sale + MIE sale)

**HAVE-auto (417 foreclosure_sale + 25 auction leads):**
- NC: per-county foreclosure feeds (`taxforeclosures.buncombenc.gov`, `henderson_tax`, `rutherfordcountync.gov/.../foreclosure_sale_dates.php`, `cleveland_tax`, `gaston_surplus_properties`, `polk_tax`).
- SC: FLC (Forfeited Land Commission) lists via `sc_flc.py`, plus MIE/master-in-equity sale lists (Charleston `charleston_mie`).
- Auction feeds already capture opening bid — `opening_bid` is present on 723 leads (4.3%), the LOW-confidence payoff proxy (fires as the selected proxy on ~587 after grade-gating).

**GAPS:**
- **Judgment/indebtedness dollar** is present on 187 leads (1.1%, MEDIUM confidence) and selected as the payoff proxy on only 8. Extend the parse: CCHS `mo` money field + NC eCourts judgment amount where present; FOIA to Clerk of Court for the indebtedness figure where SC PublicIndex is walled.
- **SC master-in-equity rosters** pull stale sale dates on some coastal counties (known coastal-roster staleness).

**Per-county note:** SPA-portal NC counties (Cleveland/Gaston/Polk/Transylvania) expose only the foreclosure subset, not the full delinquent roll — foreclosure lane is HAVE-auto there, tax-roll lane is WALL.

### 2.3 Tax Delinquency

**HAVE-auto, list + balance (tax_owed on 39.2% of board):**

| County | List route | Balance route | Note |
|---|---|---|---|
| Spartanburg SC | AUTO (PDF + FLC) | AUTO (qPayBill, +408) | fully open |
| Oconee SC | AUTO (page + Sheets + ArcGIS) | AUTO (qPayBill, +110) | fully open |
| Cherokee SC | AUTO (was 403 Cloudflare, now 200) | AUTO (qPayBill) | **un-walled 2026-07-03** |
| Union SC | AUTO (`unioncountytc.com`, was DNS-fail) | AUTO (qPayBill) | **hostname-drift fixed** |
| Laurens SC | AUTO (`.gov` treasurer) | AUTO (qPayBill, +2) | CivicEngage 404 was URL-drift, fixed |
| Buncombe NC | AUTO (105-369 PDF, ~1,153 rows) | AUTO (in PDF) | anchor county |
| Henderson NC | AUTO (PTS `bcpwa`, fresh CSV 2026-07-02) | AUTO (TOTAL_DUE in CSV) | OWNER+PARCEL+addr |
| Lincoln NC | AUTO (self-host PDF, ~1,406 rows) | AUTO (in PDF) | year-stamped URL |
| McDowell NC | AUTO (self-host PDF, ~2,260 rows) | AUTO (in PDF) | year-stamped URL |

**AUTO-pending (auto-lights-up when county posts):** Rutherford, Burke NC — valid PTS `bcpwa` tenants, 0 blobs today. Transient (waiting on county, not a tech wall). Re-run `nc_ptscloud` to catch blob drops.

**List-AUTO / balance-MANUAL:**
- **Georgetown SC** — list is AUTO (396 leads flowing via SCDOT layer-22 resolver path); only the **balance** is MANUAL (per-parcel treasurer lookup). Do not mark the whole county MANUAL.
- **Pickens SC** — list page AUTO, balance per-parcel only (qPublic 403s to plain curl, Schneider bot-check).
- **Charleston SC** — balance sits in list PDF row.
- **Horry SC** — balance in FLC xlsx, year-stamped URL.

**PARTIAL — coastal delinquent-tax (three of six already live):**
- **Onslow NC (50), Dare NC (13), Pender NC (12)** already carry `tax_lien` leads on the board — the delinquent-tax lane is **partially LIVE** there, not "unconfirmed." Manual path: county treasurer per-parcel. Scrape path: probe each for a PTS `bcpwa` tenant or self-host PDF to lift from partial to full roll.
- **Carteret NC (10), New Hanover NC (9)** — LP/foreclosure/distressed flowing; no confirmed tax bulk host yet. Manual: county treasurer. Scrape: PTS-tenant probe pending.
- **Brunswick NC (66)** — LP live; full delinquent roll needs the coastal PTS-tenant probe (lower priority per core-county directive).

**WALL / true blockers:**
- **Anderson SC balance:** `acpass.andersoncountysc.org` 302 to `/loginreg3/login.php` = auth wall. List is MANUAL via treasurer/FLC page. FOIA/paid alternative only. (Equity already strong here at 63.8% from other legs.)
- **Cleveland / Gaston / Polk / Transylvania NC full 105-369 roll:** Government Window/Catalis, DevNet Wedge, Revize, BAS SPAs respectively — no bulk file, no PTS tenant. Only the foreclosure subset is scrapable. MANUAL per-parcel for the full roll.
- **Mitchell NC:** HTTP 523 (Cloudflare origin-down) today + not a PTS tenant + no known bulk PDF. Transient on the 523, but WALL on any bulk route regardless.

**MANUAL / unconfirmed:** Georgetown SC balance (per-parcel), Beaufort SC (3 leads), plus stray Currituck/Hyde/Colleton NC/SC (1 each — treasurer per-parcel only, negligible volume). Lower priority per core-county directive.

**Note:** Madison NC is built but scope-filtered (`SCOPE_DENY_COUNTIES`) per prior direction — do not re-propose.

### 2.4 Probate / Estates / Heirs

**HAVE-auto (654 probate_notice + property-keyed heir parcels):**
- **Charleston SC:** `sc_probate_net.py` via `southcarolinaprobate.net` aggregator. Case#, decedent, type, dates, **+ PR name and full mailing address** (the Jan-2026 SC address-suppression hit the Judicial Public Index, not this probate app). Skip-trace-free contact.
- **Heir/estate parcels via county GIS** (`nc_heir_estate_parcels.py`): queries owner layer for `"<name> HEIRS"` / `"ESTATE OF"` retitled parcels across 11 NC + 4 Upstate SC (Spartanburg/Pickens/Laurens/Union). Returns owner+situs+PIN+mailing, already parcel-resolved. Highest-yield, lowest-friction estate source.
- **Obituaries / death signal:** `gannett_obituaries.py` (8 Gannett papers: Buncombe/Henderson/Gaston/Cleveland/Rutherford/Spartanburg/Greenville/Anderson, 128 landed) + `funeral_home_rss.py` (Frazer + WordPress-ltobits). Name-only leads to GIS owner-name index.
- **Estate creditor notices** via Column legal-notice API (already wired).

**GAP — probate owner-fill is under-filled board-wide, not just Charleston.** Buncombe probate owner-fill is ~25%; the decedent-vs-petitioner mismatch already flagged for Charleston recurs across counties. Widening heir-parcels + obituaries is right, but existing probate leads also need the owner-name resolver fix applied everywhere probate flows, not only Charleston.

**BUILD-READY:**
- **Greenville SC probate — net-new, not built.** Own standalone ASP.NET index at `greenvillecounty.org/appsas400/Probate/`; `SearchResults.aspx?LastName=X` is a plain GET (no viewstate/cookie), live test `LastName=Smith` returned 5,637 rows, zero WAF, party types Deceased Person + Personal Representative. Clone the `sc_probate_net.py` surname-sweep. Upstate hub bordering Spartanburg/Anderson/Pickens/Laurens. Currently 0 leads on the board.
- **Aggregator dead dropdowns:** Cherokee/Oconee/Georgetown/Colleton are listed in `southcarolinaprobate.net` but return 0 records (dropdown is not data). Do not chase.

**WALL:**
- **NC eCourts estates (all 100 counties):** estates sit in Tyler Smart Search behind AWS-WAF (`portal-nc.tylertech.cloud/Portal/Home/Dashboard/29` returns Human Verification, 11 WAF markers). No open-JSON backdoor — estates are Clerk special proceedings, absent from the Judgment JSON. `nc_ecourts_estates.py` correctly stays disabled. **Manual path:** browser + `scripts/parse_nc_ecourts_export.py`. **Scrape path:** none compliant — lean on property-keyed heir-parcel + obituary lanes instead.
- **SC non-Charleston/Greenville:** no online index (Spartanburg/Anderson/Pickens/Laurens/Union/Horry). MANUAL/in-person at Probate office.

### 2.5 Divorce

**Current: 1 divorce_notice lead on the board (confirmed live).**

**THE FIX (NC — HAVE-auto after a config change):** the open NC Judgment Search JSON already driven for lis-pendens serves granted divorce judgments: `causeOfActionDesc == "FAM - Divorce"`, `caseCategoryKey == "FAM"`. Live-verified Buncombe rows (real spouse pairs, both parties structured as debtors[]/creditors[], judgment date). In a 45-day 6-county probe, FAM-Divorce was the 5th most common cause of all judgment types. Wire effort: add `FAMILY_CAUSES = {"FAM - Divorce"}` to `nc_ecourts_lis_pendens.py`, map plaintiff/defendant to the two spouses, set `listing_type=DIVORCE_NOTICE`, route through `DATELESS_OK_SOURCES`, carry over the `_DV50B_RE` exclusion (drop 50B/DVPO/domestic-violence rows — safety matter, never a lead). Caveat: this indexes granted divorces (further down the NCGS 50-20 equitable-distribution timeline, arguably closer to a forced marital-home sale), not raw CVD filings (those live only in the WAF-walled Smart Search).

**Retire:** `nc_ecourts_divorce.py` (points at the WAF-walled Smart Search SPA, HTTP 405 + CAPTCHA, compliant dead-end).

**WALL (SC):** FCCMS (`portal.fccms.sccourts.org`) is technically reachable (public API `apiurl/api/FE/FEPublicAccessCases/caseSearch`, 500 to a bad payload, not 401/403 — no login wall) but the disclaimer gate explicitly prohibits "automated, repetitive querying" — a **legal**, not technical, wall. **Manual path:** operator accepts disclaimer, searches Family cases per county, saves pages to the offline parser. SC divorce is not published as a legal notice, so the newspaper lane yields ~0. **Scrape path:** none exists — ToS prohibition, not a bug.

### 2.6 Federal / Government REO — BUILD/BROKEN, not HAVE

**Board reality (110 reo leads):** 76 from `zillow_bulk`; the four federal disposition feeds land only ~29 combined. The showcased feeds are landing a small fraction of claimed volume — this section is effectively a soft wall until the ingest is debugged.

| Channel | Status | On board | Note |
|---|---|---|---|
| Zillow bulk (general REO) | HAVE | 76 | the actual source of most REO today |
| VA REO / VRM | PARTIAL (fix card regex) | 16 | old "1 card" was a stale regex; recovers listings |
| Fannie Mae HomePath | **BROKEN** — claims 315 on one bbox, lands 6 | 6 | bbox pagination or ingest join dropping ~98%; debug first (highest volume) |
| HUD Home Store (FHA REO) | PARTIAL | 6 | `POST hudhomestore.gov/searchresult?handler=GetFilteredResult` w/ token+cookie |
| Freddie HomeSteps | PARTIAL | 1 | `homesteps.com/listing/search?search=NC|SC` — near-zero landing |
| Hubzu | HAVE | 3 | auction-REO |
| USDA Rural Dev | HAVE (near-empty) | 0-2 | `getCountiesOfStateWithActiveProperties?stateCode=45` |

**Fix order:** (1) Fannie HomePath pagination/ingest join (biggest recover), (2) VRM card regex, (3) verify HUD/Freddie landing.

**WALL-dead (re-confirmed 2026-07-03, do NOT re-chase):**
- homesales.gov — HTTP 000, decommissioned.
- US Marshals real property — 403 (current + legacy paths).
- IRS — irsauctions.gov root is a marketing shell, `/index.cfm` 403, irssales.gov 301s back. No data path.
- GSA realestatesales.gov — `/api/properties` 302 to `/login` (login-gated, off-limits per policy).
- SBA — no real-property REO portal exists; collateral liquidated by lenders/CDCs, surplus flows through GovDeals (already in registry). Nothing net-new.

**DORMANT (mechanism live, inventory ~0 — skip):** FDIC (`fdicrealestatelistings.com` has a state filter but "No Properties" — expected with no bank failures), Treasury seized RP (`upcoming.shtml` 404, negligible NC/SC volume).

### 2.7 Bankruptcy — the single highest-value federal channel

**HAVE-auto (481 bankruptcy leads):** CourtListener/RECAP, tokenless `GET courtlistener.com/api/rest/v4/search/?type=r&court=<ID>&q="363" real property`. Returns caseName, dateFiled, docketNumber, party[], trustee_str, chapter, attorney/firm, and the recap_documents[] Schedules filing that enumerates the debtor's real property. Live counts on `363 real property`: ncwb 102, nceb 388, ncmb 133, scb 151. PACER-RSS freshness feeds ON for ncwb/ncmb/scb.

**GAPS — 3 fixes to `national/courtlistener_bankruptcy.py`:**
1. It omits **ncmb** (MDNC) — add it.
2. Its docstring wrongly claims dockets carry no debtor address — the `party[]` + Schedules doc give the property.
3. It uses the token-gated `/dockets/` path when `/search/?type=r` is keyless — switch it.

`enrichment_recap_document.py` already exists to pull the PDF. Ch.13 filers stopping a state foreclosure = pre-foreclosure leads with more lead time than an NOD; `q="motion to sell" "real property"` surfaces 363 trustee sales.

**Per-county note:** court-level (district), not county — resolve to county via the Schedules property address to GIS.

### 2.8 Liens & Judgments

**HAVE / PARTIAL:**
- **Property tax delinquency lien** — SOLVED, 39.2% of board (see 2.3).
- **SC state tax lien (super-priority)** — built: `enrichment_lien_stack.py` joins the SCDOR top-delinquent list by name.
- **Judgment liens existence** — ROD index flags them; `judgment_amount` populated on 187 leads.

**GAPS:**
- **Judgment lien dollar** — present on 187 but not universal; where absent, needs image OCR / court detail. Extend `extract_lien_amounts.py`.
- **2nd DOT / HELOC (junior)** — same DOT-OCR pipeline, same free-image ceiling.

**WALL:**
- **HOA liens** — Charleston HOA parsed (2 hoa_sale on board); broader HOA blocked on ROD rebuild.
- **IRS federal tax lien** — not free at scale.
- **Mechanic's liens / distribution deeds / in-footprint HOA** — blocked on ROD rebuild.

### 2.9 Distress signals you may have missed

- **Partition actions:** would ride the same NC Judgment JSON if a partition cause label exists — check the live `cause_distribution` log the scraper prints. Not currently filtered. BUILD-READY (low effort, verify label).
- **Code-enforcement / vacant registries:** Asheville code-enf BUILT; Asheville STR + Spartanburg vacant (5k) BUILD-READY endpoints identified. Broader code-enf = confirmed WALL (no free feed in most counties).
- **Evictions:** seller-side evictions = confirmed WALL (SC magistrate roster + NC eviction both walled). Not a distress signal we can source free.
- **Condemnation / demolition:** confirmed WALL.
- **Incarceration (jail bookings):** net-new lane, nothing built yet (0 on board — BUILD-READY, not HAVE) — P2C jqGrid (Cleveland), Zuercher (Cherokee/Anderson SC), Southern Software Citizen Connect (Henderson) endpoints verified; SCDC state-prison already wired. Some carry full DOB (skip-trace gold).
- **Elderly/disabled (3,505 leads):** the 2nd-largest source but 100% Buncombe (concentration risk, see §1.6). Senior-exemption flags for more counties = BUILD-READY, now a diversification priority.

---

## 3. Enrichment ledgers

### 3.1 Address resolution (60.9% overall; per-county fix for the low-fill counties)

**Root-cause bug (fixes 4,054 no-address leads across the 4 target counties):** `_query_parcel()` in `enrichment_gis_attrs.py` line 282 does exact `=` on the raw parcel string, no normalization. `_norm_parcel()` already exists in the same file (line 68) but is used only for the cache key. Two fixes: (1) try normalized variants raw to dash-stripped to suffix-stripped to leading-zero-stripped; (2) add `PARCELID` to `_PARCEL_FIELDS` (line 255) for Lincoln's short account numbers.

| County | Now | Address-less | Why low | Fix / resolver |
|---|---|---|---|---|
| McDowell NC | 2% | 2,331 | dashed PDF parcel ≠ clean `parno` | dash-strip → ~85%. Resolver `services9.arcgis.com/ETP7IuCigkUz7iI9/.../McDowell_Parcels/0`, situs `siteadd` |
| Lincoln NC | 4% | 1,418 | long PIN + short account numbers; account only matches `PARCELID` (missing) | add `PARCELID` + dash-strip → 100%. `arcgisserver.lincolncountync.gov/.../Server_TaxParcelViewerSP/0`, situs `PHYSICALADDR` |
| Georgetown SC | 33% | 266 | `.NNN` sub-parcel suffix; split situs | suffix-strip (mirror `_query_parcel_norm`) → 24/25. SCDOT layer 22, `TMS`, situs `StreetNumber`+`StreetName` |
| Transylvania NC | 28% | 39 | parcel path not firing on dashed PIN; situs is `ADDRESS_3` | PIN query (dash or clean both match) → 13/13. `gis.transylvaniacounty.org/.../Parcels/2` |
| Charleston SC | 19% | 253 | probate leads: resolver matches `defendant` not `owner_name`; 45 placeholder-centroid coords | owner-name fallback vs SCDOT `OWNER1`. See §2.4 |
| Buncombe NC | 90% | 258 | geo-only leads (largest such pool on the board) need point-in-polygon | point-intersect via OneMap `parno`+`siteadd`. Not previously listed — add this path |
| Polk NC | 47% | 24 | geo-only bankruptcy leads need point-in-polygon | point-intersect → 21/23; bonus `TOTAL_TAX_OWED`. `services1.arcgis.com/23uf7jKvz6SRPFWJ/.../TaxParcels/0` |
| Brunswick NC | 35% | 43 | mixed parcel formats + geo-only half | point-intersect → 17/23. `bcgis.brunswickcountync.gov/.../TaxParcels/0` |
| Cleveland NC | 60% | 53 | county layer `addr_field=None` | route via NC OneMap `siteadd` (now covers Cleveland — docstring saying absent is stale) → 15/15 |
| Rutherford NC | 78% | 14 | same `addr_field=None` | NC OneMap fallback |
| Mitchell NC | 69% | 9 | `LocAddr` = street name only | prefer OneMap `siteadd`. Low priority (9 leads) |
| Onslow / Dare / Pender / Carteret / New Hanover NC | 0% | 94 total | coastal address resolution not wired (no situs field mapped) | point-in-polygon via OneMap `siteadd` statewide layer; coastal, lower priority per core-county directive |

**Universal safety net:** NC OneMap `services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1` (no auth despite `/secure/`) carries both `parno` and `siteadd` statewide, resolves by point-in-polygon or dash-stripped parcel, now covers Cleveland+Rutherford. Already wired for geo-to-parcel (`enrichment_parcel_from_geo.py`) but its `siteadd` is not read as a situs fallback — make it a last-resort situs source to close every NC `addr_field=None` gap AND the coastal 0%-address counties in one move.

**Priority:** (1) dash/suffix-strip + `PARCELID` → 4,054 leads (two-function change: McDowell, Lincoln, Transylvania, Georgetown). (2) OneMap `siteadd` fallback → Cleveland/Rutherford/Mitchell + coastal 0% counties. (3) point-in-polygon for geo-only → Buncombe 258, Polk 21/23, Brunswick half. (4) Charleston probate owner-name fix → up to 236 leads.

### 3.2 Mortgage / Loan amount + Equity math

**Ground truth:** the "0%" premise is precise only for **recorded DOT principal** (0.0%). Equity itself is on 6.9% (1,166 leads) but wildly uneven (Anderson SC 63.8%, Laurens 45.7%, Cleveland 42.4%, Gaston 35.3%, Cherokee 33.3%, Pickens 30.4% vs Buncombe 2.4%, McDowell 0.9%, Lincoln 2.7%). Every current equity figure is a proxy. The engine (`enrichment_equity.py`) already implements the exact waterfall correctly; the inputs are the problem.

Current proxy mix (all LOW confidence except judgment): opening-bid `opening_bid` present on 723 (fires as selected proxy ~587), last-sale-amortized ~381, `judgment_amount` present on 187 (MEDIUM, selected on 8), assorted assumed-date variants. What is genuinely 0% is recorded DOT dollars.

**Free loan-proxy stack (best to worst):**
1. Recorded DOT original principal (OCR the free image) → amortize — HIGH. Free image today: **Spartanburg only** (Logan `view_image.php`, proven). Candidates to verify: Cleveland/Burke (CCHS `SearchService.asp`). Ceiling ~40-55% of owned parcels, gated by free-image counties.
2. Foreclosure judgment / indebtedness — MEDIUM. Already on 187 leads; expand via NC eCourts Judgment JSON + CCHS `mo` field.
3. Auction opening bid — LOW. On 723 leads (4.3%).
4. Assessed/market value × typical LTV — LOW. Everywhere ARV exists (79%). The floor.
5. Last arms-length sale × ~90% amortized — LOW. ~2.7% today, expandable via CAMA sale-history backfill.
6. MERS servicer lookup (mersinc.org, free) — name only, NO balance. Skip-trace/servicer identity only.

**Equity = ARV − payoff_proxy − senior liens.** Lien legs: property tax (SOLVED, 39.2%), SC state tax lien (built), 2nd DOT/HELOC (partial, same free-image ceiling), judgment liens (existence yes / $ on 187), HOA (mostly missing), IRS (not free).

**Build plan (priority):**
- **B1 (highest ROI, zero new code):** run the built-but-dormant Spartanburg DOT-OCR at scale. Raise `FORECLOSURE_DOT_OCR_MAX` from 25, drop the HOT/WARM gate, let it grind nightly (idempotent, 30-day refresh). 9 Gemini keys present, so provider is not the blocker. Expected: Spartanburg equity 4.0% → 40-60% HIGH-confidence over 2-3 weeks. Single biggest move; needs config + a scale test.
- **B2:** generalize `enrichment_dot_ocr.py` off the `_TARGET=("SC","Spartanburg")` hardcode to a `DOT_IMAGE_COUNTIES` map reusing each ROD adapter's image-fetch; live-verify free-image posture of Cleveland/Burke CCHS and Logan-family NC counties; wire only counties returning a free `%PDF`.
- **B3:** point `extract_lien_amounts.py` (already OCRs a folder, pdfplumber + Gemini fallback) at operator-pulled DOT images.
- **B4:** backfill DOT recording dates + sale history from `sc_cama.db` and NC parcel layers so proxy #5 fires on more of the tail.

**GATHER (walled counties):** AcclaimWeb image counties (Pickens — index free, image paywalled), Kofile (Oconee — robots.txt disallows all but root), Cott/Cherokee (subscriber login), Buncombe/Gaston Aumentum (image order reCAPTCHA-gated). Real walls, not code gaps. Route to manual operator pull (staff opens the free-to-view-in-browser image, saves PDF) → `extract_lien_amounts.py` folder. HOT/A-grade leads only.

**FOIA:** foreclosure judgment indebtedness figure from Clerk of Court where SC PublicIndex is ToS-walled.

**DEAD:** current live payoff balance is servicer-held PII, unobtainable free at any effort (OCR yields original principal → amortization gives an estimate, never the exact balance).

### 3.3 ARV / comps

**HAVE:** ARV on ~79% (assessor/CAMA + sold-comps). Calibration backtested vs sold prices: unbiased at median, noisy (trust `arv_confidence`); max-bid was double-charging the selling fee (fixed 0.70→0.75); ARV floor must read cama/assessor sales. Recompute board after `calc.py` changes; harness `scripts/backtest_arv.py`.

**GAPS:** SC recorded-$/sqft comps are paywalled/restricted (not a code bug). Per-parcel qPublic CARDs (Pickens/Oconee) expose heated sqft + full sale-price/book-page history as structured text (live-verified) — a manual/stealth per-parcel path, not bulk.

### 3.4 Owner contact / phone (PII wall + compliant mail ceiling)

**HAVE:** owner_name 89.9% overall. Correction: **Buncombe owner_name is 97% (5,276/5,444), not 33% — there is no Buncombe name-index gap.** Mailing address on heir-parcel + Charleston-probate lanes (PR mailing address direct). SoS registered-agent enricher for entity-owned parcels (NC SoS via stealth = agent + officers free; SC SoS captcha-walled).

**GAP — Cherokee SC owner_name = 7% (5 of 69), the worst owner county on the board.** Owner-name drives the entire name→property→contact backbone, so a 7%-owner county is a bigger hole than its loan$ gap. Cherokee's LP (27) + distressed (24) + foreclosure (15) leads need owner backfill before they are actionable. **Path:** resolve owner from the SC ROD index or GIS `OWNER1` by parcel/situs (Cherokee tax lane is un-walled, so the parcel key exists) — the same OWNER1 join used for Charleston probate.

**WALL:** phone/PII at scale is not free-compliant. The compliant ceiling is direct mail to the recorded mailing address + NC voter-file for phone where it exists. SC SoS captcha-walled, OpenCorporates/NC-bulk paid.

**Action layer gap:** the engine has no DNC-scrub / act-on-it layer (noted in path_to_100). Before any phone outreach, DNC scrub is required — currently missing.

---

## 4. County coverage matrix

Every footprint county with leads (33 total) appears below. Each row carries an addr%, the top missing item, and a resolution path.

| County | Leads | Signals covered | Addr% | Top 1-2 missing + path |
|---|---|---|---|---|
| Buncombe NC | 5,444 | tax, LP, foreclosure, probate-heir, obits, elderly(3,505) | 90% | 258 geo-only leads (OneMap point-in-polygon); loan$; owner_name is 97% (NOT a gap); concentration risk on elderly |
| Spartanburg NC→SC | 3,282 | tax+balance, heir-parcels, DOT-OCR (dormant) | 77% | run DOT-OCR at scale (equity 4%→40-60%) |
| McDowell NC | 2,387 | tax+balance | 2% | **address (dash-strip bug)**; loan$ |
| Lincoln NC | 1,477 | tax+balance | 4% | **address (PARCELID + dash-strip)**; loan$ |
| Henderson NC | 1,444 | tax+balance (fresh CSV), foreclosure, obits | 65% | loan$ |
| Oconee SC | 574 | tax+balance, forfeited-land | 92% | loan$ (Kofile image walled) |
| Georgetown SC | 396 | tax **list AUTO**, **balance manual** | 33% | **address (suffix-strip)**; balance per-parcel |
| Anderson SC | 354 | list (manual), heir-parcels, obits | 76% | **balance (auth wall)**; equity strong already (63.8%) |
| Charleston SC | 312 | probate (+PR mailing), tax list, MIE, HOA | 19% | **address (probate owner-name fix)** |
| Pickens SC | 214 | tax list, heir-parcels | 70% | balance per-parcel (qPublic 403); DOT image paywalled |
| Gaston NC | 204 | foreclosure/surplus, VRM | 81% | full 105-369 roll (DevNet SPA wall) |
| Laurens SC | 151 | tax+balance, heir-parcels | 77% | loan$ (equity 45.7% already) |
| Cleveland NC | 132 | foreclosure, obits, jail-bookings (ready) | 60% | full tax roll (Catalis SPA); OneMap situs fallback |
| Burke NC | 93 | tax (AUTO-pending), foreclosure | 59% | tax CSV not posted yet (transient); CCHS DOT verify |
| Cherokee SC | 69 | tax+balance (un-walled), obits, jail (ready) | 65% | **owner_name only 7% (worst on board)** — backfill via ROD/GIS OWNER1; loan$ |
| Brunswick NC | 66 | LP | 35% | point-in-polygon; full tax roll (coastal, low pri) |
| Rutherford NC | 63 | tax (AUTO-pending), foreclosure | 78% | tax CSV not posted; OneMap situs fallback |
| Transylvania NC | 54 | bankruptcy, tax | 28% | **address (PIN query)**; full tax roll (BAS SPA) |
| Union SC | 52 | tax+balance (un-walled), heir-parcels | 63% | loan$ |
| Onslow NC | 50 | **LP 29, tax_lien 10, probate 5, distressed 5** | 0% | **address (OneMap point-in-polygon)**; tax lane PARTIAL-live |
| Polk NC | 45 | bankruptcy, foreclosure | 47% | point-in-polygon (+taxes-owed bonus) |
| Horry SC | 45 | tax list (FLC xlsx) | 84% | balance in-list only |
| Mitchell NC | 29 | tax | 69% | 523 origin-down + no bulk tax route (wall) |
| Dare NC | 13 | foreclosure 4, LP 3, tax_lien 3, probate 3 | 0% | address (OneMap); tax lane PARTIAL-live |
| Pender NC | 12 | tax_lien 6, LP 6 | 0% | address (OneMap); tax lane PARTIAL-live |
| Carteret NC | 10 | distressed 5, LP 3, foreclosure 2 | 0% | address (OneMap); tax host probe pending |
| New Hanover NC | 9 | distressed 6, foreclosure 1, probate 1 | 0% | address (OneMap); tax host probe pending |
| Beaufort SC | 3 | distressed | 0% | address (SCDOT); treasurer per-parcel — negligible volume |
| Currituck NC | 1 | distressed | 0% | address (OneMap); treasurer per-parcel — negligible |
| Hyde NC | 1 | distressed | 0% | address (OneMap); treasurer per-parcel — negligible |
| Colleton SC | 1 | distressed | 0% | address (SCDOT); treasurer per-parcel — negligible |
| Greenville SC | 0 | **none (net-new probate to build)** | — | build probate index scraper (§2.4) |

(Two residual rows carry a blank county string: 9 SC + 7 NC leads with unresolved county — route to a county-backfill pass off situs/geo before scoring.)

### Signal x county wall summary
- **Tax full-roll walls:** Cleveland, Gaston, Polk, Transylvania (SPA portals), Mitchell (523+no bulk), Anderson balance (auth).
- **Tax PARTIAL-live coastal:** Onslow, Dare, Pender (tax_lien already flowing); Carteret, New Hanover (probe pending).
- **Address bug/gap counties:** McDowell, Lincoln, Transylvania, Georgetown (parcel-norm), Charleston (owner-name), Buncombe/Polk/Brunswick (point-in-polygon), Cleveland/Rutherford (OneMap situs), coastal 0% (Onslow/Dare/Pender/Carteret/New Hanover, OneMap).
- **Owner-name gap:** Cherokee SC (7%).
- **Concentration risk:** Buncombe elderly_disabled (3,505 = 20% of board, single county).
- **Loan$ = 0 recorded everywhere** except where DOT-OCR runs (Spartanburg only, dormant); judgment$ on 187 leads.

---

## 5. The action queue

### BUILD_NOW (compliant scrapes / config changes)

Ranked by value:

1. **Run Spartanburg DOT-OCR at scale** (config: raise `FORECLOSURE_DOT_OCR_MAX`, drop grade gate in `enrichment_dot_ocr.py`). First real recorded loan$ on the board; Spartanburg equity 4%→40-60% HIGH-conf. Zero new code.
2. **Address resolver fix** (`enrichment_gis_attrs.py`: variant-retry + `PARCELID`). **4,054 no-address leads:** McDowell 2,331, Lincoln 1,418, Georgetown 266, Transylvania 39. Two-function change.
3. **NC divorce lane** (add `FAM - Divorce` to `nc_ecourts_lis_pendens.py`, carry the 50B exclusion, retire `nc_ecourts_divorce.py`). 1 → live statewide divorce feed next run.
4. **Fannie HomePath debug + RECAP bankruptcy 3 fixes.** HomePath: fix bbox pagination/ingest join dropping ~98% of rows (6→potentially hundreds). RECAP (`courtlistener_bankruptcy.py`): add ncmb, use keyless `/search/?type=r`, read party[]+Schedules address.
5. **OneMap `siteadd` situs fallback** for `addr_field=None` + coastal 0% counties. Cleveland/Rutherford/Mitchell + Onslow/Dare/Pender/Carteret/New Hanover.
6. **Point-in-polygon for geo-only leads** (`_query_point` before parcel path). Buncombe 258 (largest pool), Polk 21/23 + taxes-owed, Brunswick half.
7. **Charleston probate owner-name resolver fallback** (`address_owner_v2` → `owner_name` vs SCDOT `OWNER1`) + **apply the same owner fix board-wide to under-filled probate**. Charleston up to 236 leads; Cherokee 7%-owner backfill via the same OWNER1 join.
8. **Greenville SC probate scraper** (clone `sc_probate_net.py` surname-sweep against `SearchResults.aspx?LastName=X`). Only free automatable case-side index in reach; Deceased Person + PR rolls. Currently 0 leads.
9. **Generalize DOT-OCR beyond Spartanburg** (`DOT_IMAGE_COUNTIES` map; verify Cleveland/Burke CCHS free-image). Lifts loan$ to the next free-image counties.
10. **VRM card regex fix** (recovers VA REO listings) + **HUD/Freddie landing verify**.
11. **Re-run `nc_ptscloud`** to catch Rutherford/Burke tax-CSV blob drops (auto-lights-up).
12. **Senior-exemption flags for more counties** (diversify off 100%-Buncombe elderly concentration) + **jail-booking + partition-cause** BUILD-READY endpoints (verify partition cause label in the live `cause_distribution` log).

### GATHER (operator pulls, with recipe)

- **SC divorce (FCCMS):** accept the disclaimer in a real browser, search Family cases per county, save result pages → offline parser. ToS forbids automation; manual only.
- **NC eCourts estates:** solve the human check in-browser, save Smart Search results → `scripts/parse_nc_ecourts_export.py`. Same for raw NC CVD divorce filings and SC PublicIndex lis-pendens.
- **DOT images in walled counties** (Pickens/Oconee/Cott-Cherokee/Aumentum): open the free-to-view-in-browser image, save PDF → `extract_lien_amounts.py` folder. HOT/A-grade leads only.
- **Anderson SC balance / Cleveland / Gaston / Polk / Transylvania full tax roll:** per-parcel lookup in the county SPA portal for A-grade leads.
- **Georgetown SC balance:** per-parcel treasurer lookup (list is already AUTO).
- **Coastal tax roll (Carteret/New Hanover + confirm Onslow/Dare/Pender):** county treasurer per-parcel until a PTS tenant is confirmed.
- **Bump year-stamped URLs** (Lincoln, McDowell, Horry) when 2026 lists post.

### FOIA / LICENSED

- **Foreclosure judgment indebtedness $** from Clerk of Court where SC PublicIndex is ToS-walled (records request).
- **NC voter file** for compliant phone appends (mail-ceiling alternative).
- Everything requiring paid vendors: OpenCorporates/NC-bulk (entity owners), IRS federal tax lien, SC recorded-$/sqft comps, live payoff balance (servicer PII — no vendor gives this free/compliant).

### DEAD (with reason, do not re-chase)

- **homesales.gov** (HTTP 000, decommissioned), **US Marshals** (403), **IRS auctions** (`/index.cfm` 403, marketing shell), **GSA `/api/properties`** (302→login, policy-off), **SBA REO** (no portal exists).
- **NC eCourts estates + raw CVD** (AWS-WAF Human Verification, no JSON backdoor).
- **SC FCCMS divorce automation** (ToS legal prohibition, not technical).
- **SC PublicIndex / SC magistrate evictions** (ToS-no-scrape 406).
- **Live mortgage payoff balance** (servicer PII).
- **Broader code-enforcement / condemnation / demolition / seller-side evictions** (no free feed).
- **Aggregator dropdown probate** for Cherokee/Oconee/Georgetown/Colleton (0 records — dropdown is not data).
- **FDIC / Treasury seized RP** (mechanism live, inventory ~0 — dormant, not dead; only wake if bank failures resume).
- **Census reverse-geocode for street address** (returns tract/block, not street).

---

Board numbers verified live 2026-07-03 against `/Users/cashhigh/foreclosure-scraper/docs/listings.json` (n=17,003): address 60.9%, owner_name 89.9%, parcel_id 88.0%, equity 6.9% (1,166), tax_owed 39.2% (6,672), recorded loan$ 0.0%, judgment$ 187 (1.1%), opening_bid 723 (4.3%). Per-county fills confirmed exactly: Buncombe owner 97% / 258 geo-only, Cherokee owner 7% (5/69), elderly_disabled 3,505 all Buncombe, REO 110 (zillow_bulk 76, VRM 16, Fannie 6, HUD 6, Freddie 1), and all 33 counties-with-leads including the 5 coastal 0%-address counties. Primary fix targets: `enrichment_gis_attrs.py` (resolver, 4,054 leads), `enrichment_dot_ocr.py` (loan$), `nc_ecourts_lis_pendens.py` (divorce), `national/courtlistener_bankruptcy.py` (bankruptcy), `national/fannie_homepath` ingest (REO), `enrichment_address_owner_v2.py` (Charleston + board-wide probate owner-fill).

---

## 6. Verified 2026-08-06 — built, and deliberately discarded

### BUILT this pass

- **SC Notice to Creditors probate** (`counties_sc/sc_probate_notices.py`) — 886 estates live:
  Pickens 516, Cherokee 245, Laurens 125. 885 are net-new against the board even
  when compared on decedent NAME, not just case number; the single overlap
  (Donald Ray Davis) is already a `sc_public_index_lis_pendens` lead, so it is a
  probate + lis-pendens cross-signal rather than a duplicate. 884/886 carry a
  personal-representative MAILING address, which is the thinnest field in the
  engine. This is the compliant answer to the ToS-walled SC PublicIndex probate
  docket: SCPC 62-3-801 forces the same facts into a public newspaper notice.
  County is derived from the two-digit county code inside the ES case number,
  never from which paper ran the notice.
- **EPA brownfield + Superfund** (`counties_generic/epa_frs_sites.py`) — 269 in
  footprint. Read via FRS because `sems.envirofacts_site` returns HTTP 500.
- **Lincoln NC jail roster** — same CentralSquare jqGrid build as Cleveland, so
  no new code. 173 in custody. Jail rosters now 10 of 18 counties.

### DISCARDED — checked, and NOT a distress signal (do not re-chase)

- **Burke County `BurkeNC_2026_Billing.zip`** (burkenc.org Data Sets, 19 MB
  zipped / 615 MB raw, one fixed-width record per bill, 8,925 chars wide).
  It is a print-image feed for the bill-printing vendor covering EVERY 2026
  tax bill: 56,536 REI + 9,095 IND + 3,330 BUS in the sampled 68,961, ALL tax
  year 2026, billed 07/01/2026 with a delinquency date of 01/06/2027 that has
  not yet arrived. There is no paid/unpaid flag and no prior-year balance
  anywhere in the record. An apparent "PAID" match is the phrase "if paid" in
  the early-payment discount line. Being sent a tax bill is not distress.
  NOTE it is still a legitimate ENRICHMENT candidate and not worthless: it
  carries owner name, owner MAILING address, situs, parcel/account, assessed
  value and acreage for every Burke real-estate parcel.
- **Gaston `DocumentCenter/View/8855`**, the only document linked from
  gastongov.com/1043/Delinquent-Taxes, is not a delinquent list. It is
  "Tales for Tales Flyer February", a library storytime flyer.
- **Transylvania `tax.transylvaniacounty.org/TaxBillSearch`** has a real
  "UnpaidBillsOnly" control, but `GetSearchTablePartial` returns HTTP 200 with
  a ZERO-length body for every model shape tried, including bounded
  single-surname searches, and `GetSearchTableData` 500s. So this is not a
  blocked bulk export, it is an endpoint that does not answer. The page's
  sha256 dependency is only the Forte payment gateway signature, not a request
  signature, so there is nothing to reproduce and nothing that should be.
  Transylvania delinquent tax remains a genuine wall.
- **Mitchell News-Journal legals** — redundant. Mitchell NC probate is already
  carried by `nc_notices_counties`, `ncpublicnotices` and `column_legal_notices`,
  and the page held exactly one notice.
- **Burke NCPTS delinquent tenant** is still a valid tenant but now returns
  ZERO blobs, so the county currently publishes no delinquent extract there.
  Transylvania, Polk, Mitchell, McDowell, Cleveland, Gaston, Lincoln and
  Buncombe all return HTTP 500 on that cluster, i.e. they are not tenants.
