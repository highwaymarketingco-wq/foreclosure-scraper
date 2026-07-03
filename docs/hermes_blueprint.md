# HERMES BLUEPRINT: Free, Public, Compliant Motivated-Seller Real-Estate Lead Engine

You are Hermes. You have zero prior context. This document is the whole thing: what the engine is, how it works, what data it fills and how well, what the human operator does by hand, every source we have and every source still to build, every wall and how to get around it compliantly, and the hard rules you must never break. Read it top to bottom before touching anything.

Board numbers below are from a live count on 2026-07-03 against `docs/listings.json` (n=17,003 leads). When a claim is not directly verified against a file, it is marked "(verify)".

Style: no em dashes anywhere in this doc; colons, parentheses, and periods only. Keep that convention in anything you write back into the repo.

---

## 1. MISSION AND THE TWO USES

There are two businesses stacked on top of each other. Do not confuse them.

### Use (a): the automated lead engine

A property-keyed engine that finds people with a reason to sell a property cheaply, ties that reason to a specific parcel, values the property, finds a way to reach the owner, and grades every lead so the best ones surface first. It is FREE and PUBLIC only: everything the robots pull is free public data reached through ordinary public search. Foreclosure is one lane among many. Every kind of distress is a lead SOURCE feeding one shared backbone:

- Foreclosure (trustee sales, master-in-equity rosters, power-of-sale notices).
- Pre-foreclosure / lis pendens (the lawsuit that starts a foreclosure, the earliest signal).
- Probate / heirs / death (estate filings, obituaries, heir-retitled parcels).
- Divorce (forced sale of jointly-titled property).
- Tax-delinquent (county delinquent-tax and forfeited-land lists).
- Vacant / absentee (owner mailing address does not match the property situs).
- Bankruptcy (Chapter 13 stops a foreclosure; Chapter 7 trustee sells real property).
- Plus life events: elderly / over-65 exemption, incarceration, storm damage (Helene).

The load-bearing idea is **property-keyed**. Every lead anchors to a real parcel (a physical property with a tax ID), not a name floating in a docket. A foreclosure filing and a tax-sale listing on the SAME house stack into one stronger lead instead of two weak ones, and every downstream number (value, equity, owner mailing) hangs off that one parcel.

### Use (b): the operator business on top

A human operator acts on those leads to make money. Three plays:

- **Wholesale**: get a distressed house under contract cheap, assign the contract to a cash buyer for a fee.
- **Land wholesale**: same, for vacant/ag/unimproved land. This is the one asset class where a pure-free, no-skip-trace pipeline works end to end because owners and neighbor-buyers are reachable by MAILING ADDRESS alone from free county GIS.
- **Gator / creative finance**: short-term deal-secured capital (earnest-money deposit funding, transactional funding, gap funding) plus subject-to (take over an existing low-rate loan) and seller-finance (owner acts as the bank). The engine tags each lead with a `creative_fit` so the operator pitches the right play.

The engine produces leads; the operator's pipeline (Section 2) converts them.

### The 18-county core footprint (plus coastal overflow)

Core (in scope, always):

- **SC (7):** Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens.
- **NC (11):** Buncombe, Gaston, Henderson, Rutherford, Cleveland, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell.

Coastal overflow (some scrapers reach these; rows survive only if an oceanfront override applies; LOWER priority than core per the core-county directive):

- **SC coastal:** Charleston, Georgetown, Horry.
- **NC coastal:** Brunswick, New Hanover, Pender, Onslow, Carteret, Dare.

Greenville SC, Mecklenburg NC, Madison NC, and the broader eastern/coastal band are deliberately out of core scope (Madison is built but scope-filtered via `SCOPE_DENY_COUNTIES`; do not re-propose it). New-avenue hunting targets Western NC + Upstate SC core, not the coast.

> Under the hood: footprint in `src/foreclosure_scraper/config.py` (`SC_COUNTIES` + `NC_COUNTIES` = `ALL_COUNTIES`, gated by `in_scope()` with a `SCOPE_DENY_COUNTIES` override). Verified: `requires-python = ">=3.12"`.

---

## 2. THE PROCESS / PIPELINE END TO END

### The engine pipeline (automated)

```
 MANUAL COURT-EXPORT LANE (human, compliant) ──┐  (net-new cases only)
 SC PublicIndex / NC eCourts pages saved by hand │
        offline parser (no web client inside)    ▼
 SOURCES ─▶ DEDUPE#1 ─▶ PROPERTY RESOLUTION ─▶ ENRICHMENT ─▶ DEDUPE#2 ─▶ SCORING ─▶ BOARD ARTIFACT ─▶ DASHBOARD ─▶ OUTREACH
 ~110       (URL-ish)    name/parcel → addr/    contact +     (parcels    grade +     listings.json    GitHub Pages   mail /
 scrapers               TMS / value / GIS       distress +    now exist,   ARV +       + detail sidecar  map/table     call list
                                                valuation     dups merge)  equity +    + run_meta
                                                              strategy fit
```

Run order matters and is load-bearing (address before parcel, parcel before value, value before the financial calc):

1. **Fetch everything** (all ~110 sources in parallel, bounded, isolated). Each source reports one of OK / ZERO_RESULT / TIMEOUT / BLOCKED / ERROR / DORMANT, so a zero-count is never ambiguous.
2. **Lis-pendens discovery** as its own early-warning pass.
3. **Carryover + partition + scope-filter** (replay last-good leads marked `stale` when a source blips; split past foreclosure sales into a sold-comp pool; in-footprint + active-only + drop luxury flips).
4. **Dedupe #1** (mostly URL, because parcel IDs do not exist yet).
5. **Property resolution + enrichment** (the long middle, sequential).
6. **Dedupe #2** (after parcels/addresses exist, the same house from three sources finally merges).
7. **Scoring** (ARV, equity, distress grade, strategy fit).
8. **Publish** (write board artifact; optionally push to a Google Sheet + digest email).

Defended by wall-clock caps (slow phases proceed with what they have), volume caps (only the top ~600 leads get vision analysis), and error isolation (one crash logs and continues; the final artifact write always happens).

> Under the hood: `main.py::run()`, `asyncio.gather` under `Semaphore(cfg.parallel_scrapers)` for fetch; enrichers awaited one at a time with `asyncio.wait_for` timeout guards.

### The operator pipeline (human, on top of the board)

`FIND -> ANALYZE/COMP -> SKIP-TRACE -> CONTACT -> CONTRACT -> FUND -> DISPO`

- **FIND**: the engine board is the find layer (free county GIS + tax + court + probate + REO). Paid alternative if ever authorized: PropStream ($99/mo, ~50-lead trial).
- **ANALYZE/COMP**: engine ARV; human second-opinion via Redfin sold data, New Silver / ArvCalc / DealCheck free calculators, county sold records.
- **SKIP-TRACE**: county owner-of-record NAME + MAILING ADDRESS (free, clean, the mail lane). MERS ServicerID (mers-servicerid.org) for the current loan servicer (name only, no balance). Phones are BOUGHT per hit (Tracerfy ~$0.02/match, PropWire $0.10/match), never scraped.
- **CONTACT**: direct mail is the spine (owner name + address, no TCPA exposure) via a mail house (Yellow Letter HQ, Ballpoint, Open Letter, Lob API, USPS EDDM). Calls only after DNC scrub.
- **CONTRACT**: free wholesale + assignment templates (realestateskills.com, BiggerPockets, DocuSign library) + Portant free e-sign; one-time NC/SC attorney review (NC requires disclosing you assign a contract, not sell the property).
- **FUND**: transactional / EMD lenders with free proof-of-funds, no upfront fee (DoubleClose.com, Straightline, Axelrad, Tidal, Levine). Gator EMD funding for the deposit; transactional for a double close; gap funding for a shortfall.
- **DISPO**: Facebook investor groups + Craigslist + county cash-buyer deed pulls (recent no-mortgage purchases = active cash buyers). Subject-to / seller-finance leads go to BiggerPockets Forum 50, SubTo, creative-finance FB groups, local REIAs (Carolinas / Metrolina / Upstate Carolina).

Solo-operator floor is roughly $250 to $350/mo plus per-hit skip and per-mail costs. Cold SMS blasting is effectively dead post-A2P 10DLC; plan around cold call + ringless voicemail + mail.

---

## 3. ARCHITECTURE (verified against the repo)

A real production data platform, not a script. Roughly 70,000 lines of Python across ~296 modules, ~110 scrapers + ~93 to 96 enrichers + ~60 operational scripts, a ~2,392-line orchestrator (`main.py`), ~1,319 test functions. Runs on a schedule and publishes a live ~17,000-lead GitHub Pages dashboard. Python 3.12, dependency + run management via **uv**. Tests: `uv run python -m pytest`.

### Repo layout

```
src/foreclosure_scraper/
  scrapers/
    counties_sc/        (31 files) SC county tax, FLC, MIE, probate, publicindex lanes
    counties_nc/        (25 files) NC county tax, foreclosure, govdeals, ecourts lanes
    national/           (24 files) Zillow/Realtor/Trulia feeds, auctions, REO, bankruptcy, multifamily
    law_firms/          (14 files) substitute-trustee firms (Brock & Scott, Hutchens, Bell Carrington, Shapiro & Ingle, ...)
    newspapers/         (10 files) legal-notice sections (Column API, Shelby Star, Daily Courier, ...)
    public_notices/     (4 files)  NC/SC public-notice portals
    reo/                (4 files)  GSA real property, USDA RD, federal REO
    city_websites/, counties_generic/  small helpers
    _registry.py        auto-discovers every concrete scraper; all_scrapers() instantiates
  enrichment_*.py       (~96 modules) owner/mailing, GIS, ARV/comps, equity, liens, distress, vision, OCR, court-confirm
  valuation/
    calc.py             ARV waterfall + max-bid math (this is the money math)
    grading.py          A-F dimensional grade
    amortize.py, location.py, rentcast.py
  web_artifact.py       write_artifact() / load_board() / LAZY_DETAIL_KEYS  (the board writer, see below)
  http_client.py        the tiered fetcher get_text()
  base_scraper.py       BaseScraper contract: safe_run() timeout + outcome taxonomy + expected_min_count
  config.py             footprint + in_scope()
  main.py               the orchestrator
  ingest_sc_publicindex_export.py, ingest_nc_court.py  offline parsers (NO web client by design)
docs/
  listings.json (+ .gz)          the slim board (fields the map/table need)
  listings_detail.json (+ .gz)   the heavy sidecar (comps, vision), index-aligned to the board
  run_meta.json                  timestamp, totals, per-source status, regressions
  index.html + dashboard.js      the static dashboard
scripts/                         ~60 operational scripts (parsers, backfills, backtests)
```

Scraper categories (verified counts): counties_sc 31, counties_nc 25, national 24, law_firms 14, newspapers 10, public_notices 4, reo 4, plus small helpers. ~110 active scrapers total (116 files, minus disabled/helpers).

Enrichment modules (~96 `enrichment_*.py`, examples): `enrichment_owner_mailing.py` (the contactability + parcel spine, `COUNTY_GIS` layer map), `enrichment_gis_attrs.py` (parcel attribute lookup, holds the address-resolver bug), `enrichment_equity.py` (the equity waterfall), `enrichment_dot_ocr.py` (deed-of-trust loan-amount OCR, Spartanburg-hardcoded), `enrichment_qpaybill_tax.py` (SC tax balances), `enrichment_vision.py` (photo condition), `enrichment_doc_ocr.py` (scanned-notice OCR), `enrichment_lis_pendens_resolver.py` (SC case-number to county to surname match), `enrichment_voter_phone.py` (NC voter-file phone), `enrichment_sos_agent.py` (NC SoS registered agent).

### The board-writer discipline (critical, do not violate)

`docs/listings.json` is the ONE output the whole system reads. It is split for speed: the **slim board** (`listings.json`) has the fields the dashboard needs; the **detail sidecar** (`listings_detail.json`) holds the heavy nested data (`LAZY_DETAIL_KEYS = ("vision", "foreclosure_sold_comps", "comps", "cama", "rent_comps")`), loaded only when a lead's detail panel opens. The two files are **index-aligned**: lead #5 in the board matches detail #5 in the sidecar.

RULE: any script that writes the board MUST read it back through `web_artifact.load_board()` first, or `write_artifact()` silently wipes the vision/comps/cama sidecar. Only the artifact functions touch `listings.json`. Run one board-writer at a time. This is the single most common way to corrupt the board; eight scripts were fixed for exactly this bug.

### The tiered fetcher (verified in `http_client.py`)

Scrapers do not pick a tool. They call `get_text()`, which walks tiers cheapest-first and escalates only when a host blocks. Once a host blocks a plain request it is remembered, so future hits start impersonating. Roughly 90% of fetches never spin up a browser.

1. **httpx** (~67 files): async HTTP/2, the default; JSON/API/GIS/ArcGIS/tax feeds. Limit: no JS, trips JA3/fingerprint WAFs.
2. **curl_cffi `impersonate="chrome"`** (~18 files): real Chrome JA3/TLS fingerprint, passes fingerprint walls (Akamai, some Cloudflare, gov/court hosts like publicindex.sccourts.org). Limit: still no JS, no CAPTCHA.
3. **Scrapling `StealthyFetcher` over camoufox** (~33 to 41 files): a stealth real browser running the page's OWN JS with anti-fingerprinting; handles JS SPAs and `solve_cloudflare`. Limit: slow (seconds to 30s), fragile, does NOT solve CAPTCHAs.
4. **Playwright direct** (~5 files): full automation for ASP.NET `__doPostBack` / `__VIEWSTATE` handshakes (ROD/court render scrapers). Limit: slowest, ~25 to 40s/lead, breaks on redesign.

Parse tier: selectolax (fast HTML), pdfplumber + pypdf (text-layer PDFs only), Gemini free-tier REST for OCR of scanned images/deeds and for vision condition (9-key rotation). Data tier: pydantic `Listing` model (with `merge()` and `also_seen_in`), rapidfuzz fuzzy address matching (`token_set_ratio >= 92`), pandas, structlog.

Present in the repo but NOT operated (the compliance line): `tyler_waf_token` / awswaf minting and CapSolver. Defeating a CAPTCHA or a WAF bot-check is the line we hold, so the walled court portals stay human-gather.

Honest weak spot: the render/stealth tier (~40 modules) is the fragile part; it breaks when a county redesigns a portal. Everything JSON/API-based is rock-solid.

---

## 4. WHAT DATA WE MUST FILL, AND CURRENT FILL RATES

Every lead should ideally carry: owner name, situs address, parcel/TMS, ARV, equity, recorded loan dollars, taxes owed, phone. Live fill rates (2026-07-03, n=17,003):

| Field | Fill | Notes |
|---|---|---|
| owner_name | **89.9%** | strong; drives the entire name -> property -> contact backbone |
| parcel_id | **88.0%** | strong |
| ARV | **~79%** | assessor/CAMA + sold comps; trust `arv_confidence` |
| address (situs) | **60.9%** | uneven; per-county holes below |
| tax_owed | **39.2%** (6,672) | strong where qPayBill/PDF balance exists |
| equity | **6.9%** (1,166) | ALL proxy; wildly uneven by county |
| judgment_amount | **1.1%** (187) | MEDIUM-confidence input; selected proxy on only 8 |
| opening_bid | **4.3%** (723) | LOW-confidence payoff proxy |
| recorded loan$ (DOT principal) | **0.0%** | zero leads carry an actual recorded mortgage principal |
| phone | low | voter-file (NC ~69%) / licensed only; never scraped |

Key nuances:

- **Recorded loan$ is the single biggest gap.** Every equity figure on the board is a proxy (opening bid, judgment amount, or last-sale-times-LTV amortized). The fix exists and is proven but dormant (see Section 7, DOT-OCR).
- **Equity is uneven:** Anderson SC 63.8%, Laurens 45.7%, Cleveland 42.4%, Gaston 35.3%, Cherokee 33.3%, Pickens 30.4% vs Buncombe 2.4%, McDowell 0.9%, Lincoln 2.7%.
- **Owner-name has one bad hole:** Cherokee SC = 7% (5 of 69), the worst owner county on the board. Buncombe owner_name is 97% (a prior "33%" claim was wrong; there is no Buncombe name gap).

### Per-county address holes (the ones to fix)

| County | Addr% | Address-less | Root cause |
|---|---|---|---|
| McDowell NC | 2% | 2,331 | dashed PDF parcel does not match clean GIS `parno` |
| Lincoln NC | 4% | 1,418 | long PIN + short account numbers only match `PARCELID` (missing from query fields) |
| Charleston SC | 19% | ~253 | probate leads: resolver matches `defendant` not `owner_name`; 45 placeholder-centroid coords |
| Transylvania NC | 28% | 39 | parcel path not firing on dashed PIN; situs is `ADDRESS_3` |
| Georgetown SC | 33% | 266 | `.NNN` sub-parcel suffix; split situs fields |
| Brunswick NC | 35% | 43 | mixed parcel formats + geo-only half |
| Polk NC | 47% | 24 | geo-only bankruptcy leads need point-in-polygon |
| Cleveland / Rutherford NC | 60% / 78% | 53 / 14 | county layer `addr_field=None`; route via NC OneMap `siteadd` |
| Buncombe NC | 90% | 258 | geo-only leads (largest such pool) need point-in-polygon |
| Onslow / Dare / Pender / Carteret / New Hanover NC | 0% | ~94 total | coastal address resolution not wired (no situs field mapped) |

Root of most of it: `_query_parcel()` in `enrichment_gis_attrs.py` does an exact `=` match on the raw parcel string with no normalization, so dashed PDF parcels never match clean GIS `parno` fields. Fixing that plus adding `PARCELID` unlocks ~4,054 no-address leads across four counties (verify line numbers before editing; the ledger cited line 282 / 255 / 68 but those may have drifted).

---

## 5. WHAT THE OPERATOR (HUMAN) CAN DO

Some data can only be pulled by a human, compliantly, in their own browser session. The rule: the human runs a normal public search and saves the results page; an OFFLINE parser (no web client inside it) ingests the file. Everything drops in `~/foreclosure-scraper/` (repo root); the parsers scan that folder, auto-detect NC vs SC, and batch-parse every `.html`. Save method everywhere: File > Save Page As > "Web Page, HTML Only" (not Complete, not PDF).

Golden rule of saved pages: a saved LIST page gives the case list (case #, plaintiff, defendant/owner, filed date, sub-type, status) which is enough because GIS resolves the property from the owner NAME. The per-case DETAIL (TMS, judgment $) sits behind `__doPostBack` JavaScript that is dead in a static save, so save a detail page only for a top lead when you need the dollar figure.

| Lane | What to pull | Where it drops | Parser that ingests it |
|---|---|---|---|
| **SC PublicIndex** (saved HTML) | `publicindex.sccourts.org/<County>/PublicIndex/`, accept disclaimer, Date Type = Case Filed, name blank; lanes: Foreclosure (420), Lis Pendens, Partition (440), Masters-In-Equity (all), Eviction/Possession (450, Summary Court). Skip State Tax Lien (432, already have ~8,000 from SC DOR) and Judgment $ (detail-page only). | `~/foreclosure-scraper/<county>_<lane>.html` | `ingest_sc_publicindex_export.py` / `scripts/parse_publicindex_export.py` |
| **NC eCourts Smart Search** (saved HTML) | `portal-nc.tylertech.cloud/Portal/` (exact path; bare host 403s), solve the AWS human-check once, Smart Search, Location = county, date range; lanes: Special Proceeding (foreclosure), Estates, Civil > District > Domestic (divorce). | `~/foreclosure-scraper/<county>_<lane>.html` | `scripts/parse_nc_ecourts_export.py` |
| **SC FCCMS divorce** | `portal.fccms.sccourts.org`, accept disclaimer, search Family cases per county, save pages. ToS forbids automation, so manual only. | repo root | extend `parse_publicindex_export.py` / `enrichment_sc_divorce.py` |
| **FOIA clerk for judgment $** | Templates in `docs/foia_court_records.md`. NC: Clerk of Superior Court, each county, foreclosure SP + civil money judgments WITH amount. SC: Clerk of Court + Master-in-Equity, Common Pleas foreclosures + MIE roster/$. Ask for electronic CSV/Excel. | repo root when file returns | one-off ingest |
| **Spartanburg CAMA extract** | Email `Assessor@spartanburgcounty.org` for bulk CAMA (parcel + sale price + heated sqft) in CSV/Excel (FTP is SPARTNET IP-firewalled). | repo root | `scripts/build_sc_assessor_cama.py` |
| **PropWire CSV export** | Log into your OWN free PropWire account, run the foreclosure filter, export CSV (data tier only; skip-trace tier is paid PII). Do NOT automate against the site (DataDome + account gate). | repo root | `scripts/ingest_contacts.py` (contact_ingest) |
| **Per-parcel qPublic / tax** | Anderson SC balance (`acpass.andersoncountysc.org`, per-parcel, bulk is 403); Pickens SC qPublic CARD (balance + sales + heated sqft); Georgetown SC balance (per-parcel treasurer, list is already auto). Save each page. | repo root | extend `enrichment_tax_owed.py` / `assessor_cards/*` |
| **DOT-image saves for OCR** | In walled ROD counties (Pickens AcclaimWeb, Oconee Kofile, Cherokee Cott, Buncombe/Gaston Aumentum), open the free-to-view-in-browser deed-of-trust image, save the PDF. HOT/A-grade leads only. | a folder for `extract_lien_amounts.py` | `scripts/extract_lien_amounts.py` (pdfplumber + Gemini) |
| **SC SoS captcha entity pull** | `businessfilings.sc.gov`, search the LLC/entity, solve the CAPTCHA (human), save the entity detail (registered agent + officers). NC SoS runs free via stealth; SC is manual. | repo root | saved-page branch in `enrichment_sos_agent.py` |
| **NC voter file** | Say "voter file" and the engine runs the NC voter-file phone match (free, ~69% NC coverage). SC has no route (SC voter list is paid, purpose-restricted, no phone). | n/a | `enrichment_voter_phone.py` |

After any drop, the trigger is: run the offline parsers, dedupe, enrich (owner/GIS/equity), and the leads land on the board with the court-confirmed badge. The last court merge brought in 674 saved SC PublicIndex leads this way.

---

## 6. SOURCES WE HAVE (by signal, wired scrapers)

- **Lis pendens / pre-foreclosure (1,178 leads):** NC eCourts Judgment Search JSON (`POST portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`, open, keyless, no CAPTCHA), statewide, facet-selectable per county. No property address; resolves downstream via owner to GIS. SC lis pendens: the ONE sanctioned SC PublicIndex stealth lane (`sc_public_index_lis_pendens.py`, CP-Foreclosure-420 filter, ~233 leads).
- **Foreclosure (417 foreclosure_sale + 25 auction):** NC per-county feeds (Buncombe, Henderson, Rutherford, Cleveland, Gaston surplus, Polk); SC FLC (`sc_flc.py`) + master-in-equity rosters (`charleston_mie`, `pickens_master_in_equity`, `anderson_master_in_equity`); ~14 substitute-trustee law-firm scrapers (Brock & Scott, Hutchens, Bell Carrington, Shapiro & Ingle Power BI, ...). `opening_bid` on 723 leads.
- **Tax delinquency (tax_owed on 39.2%):** list + balance auto for Spartanburg (qPayBill +408), Oconee (+110), Cherokee (un-walled 2026-07-03), Union (hostname-drift fixed), Laurens (+2), Buncombe (105-369 PDF), Henderson (PTS `bcpwa` CSV), Lincoln + McDowell (self-host PDFs). List-auto / balance-manual: Georgetown, Pickens, Charleston, Horry. Partial coastal `tax_lien` live: Onslow (50), Dare (13), Pender (12).
- **Probate / estates / heirs (654 probate_notice + heir parcels):** Charleston (`sc_probate_net.py` via southcarolinaprobate.net, PR name + full mailing address); heir/estate parcels via county GIS (`nc_heir_estate_parcels.py`, "HEIRS" / "ESTATE OF" retitled parcels, 11 NC + 4 Upstate SC); obituaries (`gannett_obituaries.py`, 8 papers, 128 landed; `funeral_home_rss.py`); estate creditor notices via the Column legal-notice API.
- **Divorce:** 1 lead today (the NC scraper points at the WAF-walled Smart Search, a dead-end). The fix is a config change (Section 7).
- **Federal / government REO (110 reo leads):** the reality is Zillow bulk 76 + the four federal disposition feeds landing only ~29 combined (VA/VRM 16, Fannie HomePath 6, HUD HomeStore 6, Freddie HomeSteps 1) + Hubzu 3. This is effectively BROKEN, not a healthy HAVE (Section 7).
- **Bankruptcy (481 leads):** CourtListener/RECAP tokenless search (`GET courtlistener.com/api/rest/v4/search/?type=r&court=<ID>&q="363" real property`), returns parties, trustee, chapter, and the Schedules filing enumerating the debtor's real property. PACER-RSS freshness on for ncwb/ncmb/scb.
- **Liens & judgments:** property tax delinquency (solved, 39.2%); SC state tax lien via SCDOR list joined by name (`enrichment_lien_stack.py`, and the SC DEW UI-tax lien registry ~8,000 liens); judgment-lien existence via ROD index; `judgment_amount` on 187 leads.
- **Life-event / distress:** elderly / over-65 exemption (3,505 leads, but 100% Buncombe, a concentration risk); Helene storm damage; SCDC state-prison incarceration (wired); Asheville code-enforcement (built).
- **Entity owners:** NC SoS registered-agent enricher (`enrichment_sos_agent.py`), free via stealth (Cloudflare JS pass, not defeat). SC SoS is captcha-walled (manual).

---

## 7. SOURCES REMAINING / THE BUILD QUEUE

### BUILD_NOW (compliant scrapes and config changes, ranked by value)

1. **Run Spartanburg DOT-OCR at scale.** `enrichment_dot_ocr.py` is built and proven (extracted $56,097 from a free Spartanburg image) but hardcoded to `_TARGET = ("SC","Spartanburg")` (verified in the file), capped at 25/run (`FORECLOSURE_DOT_OCR_MAX` default 25), gated to HOT/WARM only, never run at scale. Raise the cap, drop the grade gate, let it grind nightly (idempotent, 30-day refresh; 9 Gemini keys present). This is the FIRST real recorded loan$ on the board and takes Spartanburg equity from ~4% to a projected 40 to 60% HIGH-confidence. Zero new code.
2. **Address resolver fix** in `enrichment_gis_attrs.py`: variant-retry (raw, dash-stripped, suffix-stripped, leading-zero-stripped) + add `PARCELID` to the parcel fields. Unlocks ~4,054 no-address leads (McDowell 2,331, Lincoln 1,418, Georgetown 266, Transylvania 39). Two-function change (verify current line numbers).
3. **NC divorce lane:** add `FAM - Divorce` (`caseCategoryKey == "FAM"`) to the filter set in `nc_ecourts_lis_pendens.py` (the open Judgment JSON already driven for lis-pendens serves it, both spouses structured), carry over the 50B/DVPO exclusion (safety, never a lead), retire `nc_ecourts_divorce.py`. Goes from 1 to a live statewide divorce feed next run.
4. **Fannie HomePath ingest bug** (highest REO volume): it claims 315 NC/SC on one bbox and lands only 6, so bbox pagination or the ingest join is dropping ~98% of rows. Debug this first, then the VRM card regex, then verify HUD/Freddie landing.
5. **RECAP bankruptcy 3 fixes** in `national/courtlistener_bankruptcy.py`: add ncmb (MDNC, currently omitted); switch to the keyless `/search/?type=r` path (not the token-gated `/dockets/`); correct the docstring and read `party[]` + Schedules for the property address. `enrichment_recap_document.py` already pulls the PDF.
6. **OneMap `siteadd` situs fallback:** NC OneMap (`services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1`, no auth despite `/secure/`) carries `parno` + `siteadd` statewide. It is wired for geo-to-parcel but its `siteadd` is not read as a situs fallback; make it the last-resort situs source to close every NC `addr_field=None` gap (Cleveland/Rutherford/Mitchell) AND the coastal 0%-address counties in one move.
7. **Point-in-polygon for geo-only leads** (a `_query_point` before the parcel path): Buncombe 258 (largest pool), Polk 21/23 + a taxes-owed bonus, Brunswick half.
8. **Charleston probate owner fix:** have `address_owner_v2` fall back to `owner_name` against SCDOT `OWNER1` when the source is probate/estate (currently matches the petitioner/heir, the wrong person). Up to 236 leads. Apply the SAME owner fix board-wide to under-filled probate, and use the same OWNER1 join to backfill Cherokee SC owner_name (7%).
9. **Greenville SC probate scraper (net-new):** clone `sc_probate_net.py` surname-sweep against `greenvillecounty.org/appsas400/Probate/SearchResults.aspx?LastName=X` (plain GET, no viewstate, live-tested 5,637 rows, zero WAF). Upstate hub bordering the core; 0 leads today.
10. **Generalize DOT-OCR beyond Spartanburg:** replace the hardcode with a `DOT_IMAGE_COUNTIES` map; live-verify free-image posture of Cleveland/Burke (CCHS) and Logan-family counties; wire only counties returning a free `%PDF`.
11. **Senior-exemption diversification:** the elderly_disabled source is 100% Buncombe (20% of the board on one county's roll). Build senior/over-65 exemption flags for more counties (BUILD-READY endpoints identified). Fragility item, now a priority.
12. **Jail bookings (net-new incarceration lane):** verified endpoints P2C jqGrid (Cleveland), Zuercher (Cherokee / Anderson SC), Southern Software Citizen Connect (Henderson), plus Buncombe CentralSquare P2C (open JSON, 540 in custody, live-verified), Greenville SC LANSA WEBEVENT (highest SC jail pop), Gaston New World WebForms. Some carry full DOB (skip-trace gold). Wire into `enrichment_jail_bookings.py`. Also verify a partition-action cause label in the live `cause_distribution` log (rides the same NC Judgment JSON, low effort).

### Net-new FREE tools to adopt (compliant, public, no PII)

Wire into the auto-engine:

- **n8n (self-hosted, free):** the missing "act-on-it" orchestration layer (scraper -> ARV calc -> dedup -> dashboard -> mail/email dispatch). path_to_100 flagged this as the missing layer.
- **US Census / ACS API (via cenpy, free instant key, api.census.gov)** + **FCC Area/Census Block API (geo.fcc.gov/api/census, no key):** per-tract buy-box + motivation scoring, and the FCC call is the glue that joins every parcel to Census.
- **FEMA National Flood Hazard Layer (msc.fema.gov + hazards.fema.gov ArcGIS REST, no key):** per-lead flood flag. In this core footprint the driver is riverine/flash-flood (very live post-Helene), not coastal surge.
- **HUD Aggregated USPS Vacancy Data (huduser.gov, free gov/nonprofit registration, USPSVacancydata@hud.gov):** authoritative vacancy scoring by ZIP/tract to prioritize mail.
- **State unclaimed property (NCCash.com, SC Treasurer, missingmoney.com, free):** heir/probate cross-reference and name-to-address confirm; a decedent's unclaimed funds point to heirs.
- **MERS ServicerID (mers-servicerid.org, free):** per-address current-servicer lookup to confirm a live loan before a subject-to conversation (name only, NO balance). Strengthens `creative_fit`.
- **OpenAddresses (openaddresses.io) + Overture footprints (overturemaps.org):** a free second situs layer + sqft / vacant-lot-vs-structure sanity.
- **USDA Web Soil Survey + SoilWeb + USFWS NWI + USGS National Map:** the land buy-box verification layer (perc, wetlands, topo) if the engine extends into land.

Operator tools (not necessarily auto-engine): PropWire (free comps + $0.10/match skip when a call is needed), FlipMantis (free driving-for-dollars), DealCheck / ArvCalc / New Silver (free ARV second opinions), QGIS (free desktop GIS), BiggerPockets Forum 50 + local REIAs + creative-finance FB groups (free dispo/JV), Auction.com / Xome / Hubzu browse (free cross-check, no scrape).

---

## 8. THE ROADBLOCKS / WALLS

Three categories. Learn them; they decide whether an item is worth trying.

- **WONT:** a bypass exists and would work (CAPTCHA solver, login, paid API, subscriber wall), but riding it to sustain automation crosses the compliance line. A different operator willing to cross the line, or to pay, unlocks these. This is the lever the operator can pull manually.
- **CANT:** technical. 403 / dead site / decommissioned / SPA with a bot-protected backend / challenge-response, no free path found. A paid unblocker might crack some; a decommissioned site nobody can.
- **ABSENT:** the data is legally or structurally not published. Exempt deeds state no value; the field is omitted from the API payload; no bulk feed exists; the figure is private servicer PII. Nobody, free or paid, extracts what is not published. Only a FOIA, a paid county extract, or the private party who holds it produces it.

Major walls and the compliant workaround:

| Wall | Category | Exact blocker | Workaround |
|---|---|---|---|
| **SC PublicIndex** (broad civil sweep) | WONT | `PISearch.aspx` behind F5 Distributed Cloud / Shape "Client Challenge"; the disclaimer ToS expressly prohibits automated/repetitive querying; home addresses removed 2026-01-01; Rule 610 per-held-case only | Manual saved-HTML lane (Section 5). The ONE lis-pendens stealth lane stays frozen, NOT widened. |
| **NC eCourts Smart Search** (estates, divorce, SP) | CANT | AWS-WAF escalating image-grid CAPTCHA; the free Gemini-vision solver "solves 2 puzzles, WAF keeps issuing more" | Manual saved-HTML lane -> `parse_nc_ecourts_export.py`. Estates ALSO covered via Column. Divorce via the open Judgment JSON (Section 7). |
| **SC Family Court / SC Probate** | ABSENT (not on the portal) | not on PublicIndex at all; SC Family Court is a separate access-restricted system; SC estates live in county Probate Court | FCCMS manual name-search for divorce; obituaries + Gannett heirs + Charleston/Greenville probate for estates. |
| **Mortgage payoff / current loan balance** | ABSENT | held only by the servicer; PII; changes mid-month; MERS returns the servicer NAME only, never a balance | Proxy only: judgment/opening-bid $ > OCR'd recorded DOT original principal amortized > sale x LTV. Never the exact balance. |
| **SC exempt-deed sale price** | ABSENT | §12-24-70: exempt deeds (foreclosure / deed-in-lieu / spouse per §12-24-40) state NO value, only the exemption reason; distressed targets carry no recoverable stamp; SaleAmount + heated sqft blank across every free SC GIS layer | qPublic per-parcel CARD (Pickens/Oconee expose sqft + sale-price/book-page history as text); MS Building Footprints for sqft; email the assessor for the CAMA extract. NC deed-stamp path still works. |
| **ROD document images (lien $)** | WONT | AcclaimWeb / Logan / Cott / Kofile / Aumentum images are vendor-paywalled or subscriber-login on most counties (Spartanburg Logan images are FREE) | OCR the free-image counties (Spartanburg); operator saves the free-to-view image elsewhere -> `extract_lien_amounts.py`. |
| **Owner phone / email** | WONT / ABSENT | consumer people-search (TruePeopleSearch, FastPeopleSearch, Radaris, Whitepages) return Cloudflare 403 / paywall teaser and BAN automation in ToS; forward-lookup APIs are paid PII | Direct mail (no TCPA). NC voter file for phone. Buy phones per-hit from a compliant vendor, then DNC-scrub, only for a human calling lane. |
| **Federal auction sites** | CANT / WONT | homesales.gov HTTP 000 (decommissioned), US Marshals 403, irsauctions.gov `/index.cfm` 403 (marketing shell), GSA `/api/properties` 302 to /login | Do not re-chase. USMS surplus is covered via Bid4Assets; GSA via the server-rendered `/our-listing/` HTML index (not the API). |
| **SC magistrate eviction bulk** | ABSENT | PublicIndex exposes only Circuit-court roster types; there is NO magistrate/summary/eviction roster type anywhere; county-operated/in-person | Manual save per county, OR FOIA the Chief Magistrate (the only free case-level route), OR an LSC data-sharing agreement (civilcourtdata@lsc.gov). Use eviction as a market-rate signal, not a per-case lead. |

Other confirmed walls (do not re-chase): SC SoS captcha; code-enforcement / vacant registries / demolition (no free in-footprint feed, LiensNC login-walled); MLS expireds (agent/partner only); LoopNet / auction.com MF / HUD-MF / Fannie-Freddie MF REO (Crexi is the only free MF source); Cott/Cherokee/Kofile ROD (subscriber/SPA); CCHS us5 ROD (decommissioned, IIS-404). Re-probe-transient (not truly gone): the SC delinquent-tax pages that 403/404/DNS-drift each cycle, Rutherford/Burke PTS blobs that auto-light-up when the county posts.

---

## 9. WHAT I WOULD USE TO SOLVE EACH OPEN ITEM

The specific compliant approach per open problem:

| Open item | Compliant solution |
|---|---|
| Recorded loan$ / equity precision | **DOT-image OCR**: render the free `view_image` PDF, Gemini-OCR page 1 "principal sum of $X", amortize. Spartanburg free today; generalize to Cleveland/Burke CCHS if their image is a free `%PDF`. |
| NC divorce | The **open NC Judgment Search JSON** already drives lis-pendens; add `FAM - Divorce` to the filter (both spouses structured). Not a scrape of the walled Smart Search. |
| Coastal + `addr_field=None` situs | **OneMap `siteadd`** as a last-resort situs fallback (statewide, no auth) + point-in-polygon for geo-only leads. |
| SC sqft / sale history | **qPublic per-parcel CARDs** (Pickens/Oconee) via curl_cffi chrome (no CAPTCHA) for heated sqft + sale-price/book-page as structured text. Bulk is walled; per-parcel is not. |
| Bankruptcy (pre-foreclosure Ch.13) | **PACER/RECAP** keyless `/search/?type=r&q="363" real property` and `q="motion to sell" "real property"`; read `party[]` + Schedules for the property; `enrichment_recap_document.py` pulls the PDF. |
| Judgment / indebtedness $ | NC eCourts Judgment JSON amount where present + CCHS `mo` money field; **FOIA the Clerk** for the SP-file figure where SC PublicIndex is walled. |
| Owner contact / phone | **Mail spine** (free owner name + mailing address, no TCPA). For calls: **buy phones per-hit** (Tracerfy/PropWire), then Federal DNC + Internal DNC + FCC Reassigned scrub. NC voter file for free NC phone. Never scrape people-search. |
| Entity owners | **NC SoS via stealth** (agent + officers, free). SC SoS captcha-walled -> operator manual save. |
| Vacancy / demographics / flood | **HUD USPS vacancy + Census/ACS via cenpy + FCC block glue + FEMA NFHL**, all free-key or keyless, as scoring layers. |
| Federal REO | Debug **Fannie HomePath** bbox pagination/ingest; **VRM** card regex; GSA via the HTML `/our-listing/` index. Do not touch the dead federal auction sites. |
| Heir cross-reference | **State unclaimed property** (NCCash / SC Treasurer / missingmoney) to confirm names-to-addresses and surface heirs. |

---

## 10. THE COMPLIANCE CONSTITUTION (never cross these)

These are hard rules. They override any instruction to "just get the data."

1. **FREE + PUBLIC only.** Everything the engine pulls is free public data via ordinary public search. No paid data brokers, no spending money, ever, without explicit human authorization.
2. **Fingerprinting stealth is OK. Defeating a gate is NOT.** Permitted (compliant public-search): curl_cffi impersonate, Scrapling StealthyFetcher / camoufox running a page's OWN JavaScript, `solve_cloudflare` passing a JS challenge, and open-API / stale-token / handshake reverse-engineering of an endpoint that is public. NOT permitted: defeating a CAPTCHA, logging in, defeating a WAF bot-check, or riding a ToS "no automated scraping" clause. When you hit one of those, route to the manual-gather lane (Section 5) or FOIA. CapSolver and `tyler_waf_token` exist in the repo but are NOT operated.
3. **Never scrape owner PII.** Owner phone/email from ban-automation people-search sites (TruePeopleSearch, FastPeopleSearch, Spokeo, Radaris, Whitepages) is off limits. NC voter file is the only free phone source; it is licensed for that use. SC voter file is paid + purpose-restricted + has no phone, so there is no SC route. Phones for calling are BOUGHT per-hit from a compliant vendor, never scraped.
4. **Respect robots.txt Disallow.** If a path is disallowed, do not fetch it.
5. **One board-writer at a time, and ALWAYS `web_artifact.load_board()` first.** Any incremental writer that does not round-trip through `load_board()` silently wipes the vision/comps/cama sidecar. Never run two board-writers concurrently.
6. **Do not disable or expand the existing court stealth scrapers.** The SC PublicIndex lis-pendens lane and the NC eCourts JSON lane are sanctioned and frozen. Do not widen them to new lanes or counties (that would mean writing new bypass code) and do not turn off the existing CAPTCHA/WAF-bypass code that ships with them (keep the code, build compliant workarounds around it).
7. **Mail is the TCPA-free spine; phones are bought then scrubbed.** Direct mail to the recorded owner mailing address has no TCPA exposure (but still obeys state UDAP / deceptive-solicitation law: clear return address, non-deceptive copy). Before ANY call / text / ringless voicemail: Federal DNC scrub every 31 days + Internal DNC (log every opt-out) + FCC Reassigned Numbers + litigator scrub. Ringless voicemail counts as a call under TCPA. Note for this footprint: neither NC nor SC maintains a separate state DNC list, so the federal 31-day scrub covers both. Do not hunt for a nonexistent NC/SC state list.
8. **When a source is ABSENT, stop.** Do not re-chase exempt-deed sale prices, mortgage payoff balances, NC power-of-sale debt figures, magistrate-eviction bulk rosters, or a structured investor buy-box feed. None come from a better tool; they come only from a FOIA, a paid extract, per-parcel cards, or the private party who holds the number. Route them there or accept the proxy.

---

### Quick-start checklist for a new Hermes session

1. Read Sections 1, 3, and 10 first (mission, architecture, rules).
2. Before writing the board: call `web_artifact.load_board()`, confirm one writer.
3. Highest-value first moves are in Section 7 BUILD_NOW (DOT-OCR at scale, then the address resolver fix, then the NC divorce config change).
4. When you hit a wall, classify it (WONT / CANT / ABSENT, Section 8) before spending effort; ABSENT means stop, WONT means route to the operator's manual lane.
5. Verify file line numbers before editing (the ledger's cited lines may have drifted); if unsure about a claim, say "verify" rather than assert.
