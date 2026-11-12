# Hermes — Untapped Avenues, Walls, and How To Pull Each (current 2026-08-16)

Companion to the three canonical docs. Read those for full depth; this one is the **current, de-duplicated action list** — what is genuinely still open, what is walled, and the exact method to pull each. It exists because the avenue research is spread across ~8 docs and some entries have since been built.

- **Walls (what you can't get into):** `docs/blocked_sources_forensic.md` — every URL, classified WONT / CANT / ABSENT, with the exact blocker AND a "your manual step" column. That IS the how-to for the walls. Nothing to add there except the session-delta at the top of `hermes_blueprint.md`.
- **Costed strategy + per-element manual playbooks:** `docs/path_to_100.md` (1,131 lines) — every score/source/enrichment: free route, paid route with 2026 pricing, feasibility, and a step-by-step VA playbook per section.
- **Prior avenue research:** `docs/source_research_2026-07.md §4`, `docs/missing_lead_sources_research.md`, `docs/road_to_100_alternates_signals.md`.

**Honesty first:** the engine is ~130 enrichment facets + ~112 scrapers deep. Most "obvious" motivated-seller avenues are ALREADY built or already researched-and-classified: foreclosure, lis pendens, tax-delinquency, probate/estates, divorce (NC+SC), bankruptcy, REO (Fannie/Freddie/HUD/GSA/USDA/VA/Treasury/Bid4Assets), ROD recordings, code enforcement, vacant registries, USPS vacancy, incarceration/jail bookings, obituaries, absentee/out-of-state, opportunity zones, FEMA/Helene, HOA, cash-buyer deeds, estate-sale companies, senior-exemption. Do **not** re-scope those as new. The frontier below is what remains.

---

## ✅ BUILD OUTCOMES (2026-08-16 — probed all 6, built the 2 that were real)

Verification first, per the honesty rule — 4 of 6 turned out walled/seasonal/dead on live probe:
- **BUILT ✅ Craigslist FSBO** (`scrapers/national/craigslist_fsbo.py`) — 264 verified in-footprint FSBO leads (NC+SC) via the CL SAPI JSON (`sapi.craigslist.org/web/v8/postings/search/full`). HTML is JS-hydrated (0 listings) but SAPI returns them. Cracked the delta-encoded posting id (`minPostingId + item[0]`) so URLs resolve; carries price + lat/lng + title. Area ids: asheville 171, charlotte 41, greenville 253, hickory 462, myrtlebeach 254. Auto-registered. FRAGILE (CL bans heavy scraping, SAPI shape can drift) — one low-volume page/region, degrades to 0 never raises. Tests: `tests/test_craigslist_fsbo.py`.
- **BUILT ✅ Vacant-land-use proxy** (`enrichment_vacant_landuse.py`) — free USPS-vacancy substitute. Added a `land_use` column to the parcel cache (Rutherford `Land_Class`, Burke/Henderson `LAND_CLASS`, Spartanburg `LandUse`); stamps a `vacant_lot` distress facet on undeveloped lots. 1,168+ signals on the first 3 counties alone. Pure-local (reads cache, no network). Wired into `main.py` before distress scoring; `vacant_lot` added to `_facet_signals` + `RAW_KEEP`.
- **WALLED ❌ ACPASS (Anderson)** — was open in July, now behind a `Login Form` (`login.php`). Login wall = off-limits.
- **SEASONAL ⏳ tax-sale bidder PDFs** — counties post Oct–Dec; nothing live in August. Build the parser in fall.
- **LOW-VALUE ❌ GSA Auctions API** — `buy.gsa.gov/api` returns an HTML app, endpoint undiscovered, off-footprint.
- **CONFIG, not scraper: CourtListener RECAP alerts** — an API-alert setup, deferred.

---

## PART 1 — Net-new BUILD frontier (free, in-footprint, grep-confirmed NOT built as of 2026-08-16)

Each: what it adds · exact URL/endpoint · how to pull · why it matters.

### 1. Anderson County ACPASS full ingest — HIGHEST VALUE
- **Adds:** Anderson SC is the weakest county in the board (leads carry no parcel_id; tax page is 403; SSL-broken parcel layer). ACPASS closes ROD + tax + **court dockets** at once.
- **URL:** `https://acpass.andersoncountysc.org/` — an integrated no-login CGI (ROD + tax + real property + court dockets).
- **How to pull:** hit the CGI search endpoints directly with `curl_cffi` impersonate=chrome; it's the single most open SC county system, no login/CAPTCHA. Probe `/` for the form action URLs, then replay the GET/POST with owner-name or parcel search. Map its parcel id to the board's Anderson id format to backfill situs + taxes-owed.
- **Classification:** PARTIAL → BUILD.

### 2. County tax-sale bidder-list PDFs — fills the taxes-owed $ gap
- **Adds:** owner + parcel + **amount owed** as a seasonal PDF — a cleaner taxes-owed capture than the per-parcel qPayBill/portal lookups (the $ figure is a known hole; only Spartanburg is solved via qPayBill).
- **URLs:** Oconee `oconeesc.com/delinquent-tax/sale-list`, Spartanburg `spartanburgcounty.org/640/2025-Tax-Sale-Info`, Anderson + Pickens + Cherokee via `postingpro.net` (several SC counties template on one host).
- **How to pull:** fetch the PDF, parse the table (pdfplumber / the existing `enrichment_doc_ocr` Gemini path for scanned ones). These publish seasonally (late summer/fall) — schedule a re-probe each cycle.
- **Classification:** PARTIAL → BUILD.

### 3. NC vacant-land-use proxy (free USPS-vacancy substitute)
- **Adds:** reconstructs most of the paywalled USPS true-vacancy signal for $0. USPS 90-day vacancy is HUD-gated/paid; the land-use-code field is a free proxy.
- **URLs/fields:** NC OneMap `parusecode` field (`services.nconemap.gov/.../NC1Map_Parcels`), Spartanburg `Assessed_Land_Use`. Flag owners whose land-use code = vacant/unimproved lot.
- **How to pull:** add a land-use-code read to the parcel-cache download (it's one more `outFields` entry on layers already being pulled), then a predicate that stamps a `vacant_landuse` signal. Nearly free given the parcel cache already downloads these layers.
- **Classification:** GAP → BUILD (cheap, high leverage — pairs with the new parcel cache).

### 4. Craigslist FSBO — direct motivated sellers
- **Adds:** for-sale-by-owner listings = owners actively trying to sell without an agent (often distressed/time-pressured). Net-new lead SOURCE, not enrichment.
- **URLs:** 5 regional CL sites cover the footprint — `asheville.craigslist.org`, `charlotte.craigslist.org`, `greenville.craigslist.org`, `hickory.craigslist.org`, `myrtlebeach.craigslist.org`; paths `/search/reo` (real estate by owner) and `/search/rea`.
- **How to pull:** CL exposes JSON-LD structured data on listing pages; fetch the search result pages, parse embedded JSON-LD (`@type: Product/Offer` with price + address). ~50+/region. Trivially scrapable, no wall.
- **Classification:** HIGH priority, GAP → BUILD.

### 5. CourtListener RECAP Search Alerts — free federal watch
- **Adds:** federal tax liens, bankruptcy filings, receiverships — federal records not in county systems. We already ingest CourtListener; **alerts** are the incremental "Google Alerts for federal filings" lane.
- **URL:** `free.law/recap/` + CourtListener alert API. Note the May-2026 anon rate cut (~5 req/min) — use an authed free token.
- **How to pull:** create saved search alerts scoped to the footprint districts (NCWD/NCED/NCMD, SCD bankruptcy courts scb/ncwb), poll the alert feed.
- **Classification:** PARTIAL → BUILD.

### 6. GSA Auctions structured API — federal surplus real property
- **Adds:** structured feed of GSA disposal / surplus real property (we scrape the GSA HTML index; the API is cleaner + catches more).
- **URL:** `gsa.github.io/auctions_api/` (open XML/JSON), plus FDIC "Bargain Properties" / real-estate sales `fdic.gov/asset-sales`.
- **How to pull:** hit the documented Auctions API JSON endpoints, filter to real-property categories in NC/SC. Off-footprint mostly, so expect thin — but clean and free.
- **Classification:** PARTIAL.

---

## PART 1b — OPEN for Hermes: full per-source DOCUMENT-ARTIFACT audit (deep dive)

Foundation is BUILT (2026-08-17): `document_links.py` harvests deed/notice/instrument PDFs from a page's
HTML into `raw['documents']` → feeds `enrich_doc_ocr` (which extracts loan amounts / lien detail); compliance
denylist excludes walled/paid ROD image vendors. Wired into 4 scrapers with real per-listing doc links
(brunswick_legal_notices, nc_coastal_tax_foreclosure/Carteret, mewborn_deselms, rogers_townsend). See
`docs/extraction_gaps.md` → "Document-artifact harvester".

**STILL OPEN — the deep dive:** only ~8 of ~247 source pages were VISUALLY inspected (browser). The sampled
pattern was "most public pages expose no per-property documents" (foreclosure lists are data tables; SC tax
pages link an aggregate list PDF that's already consumed; the loose PDFs are procedural junk). BUT some sources
gate content behind a click-through DISCLAIMER (e.g. Kania), behind JS/search loads, or on per-case DETAIL
pages the scraper never opens — and real deed/complaint/notice PDFs can hide there. TASK: walk EVERY source
(and its per-listing detail page where one exists) in a real browser, list the actual document links present,
and wire `stamp_documents(li, harvest_document_links(html, base_url))` wherever a genuine per-listing doc is
being dropped. Keep the accuracy rule: never stamp an aggregate list-PDF onto its own extracted rows, and never
capture the compliance-denylisted ROD vendor image URLs. Walled court/ROD systems (SC PublicIndex ToS+F5, qPublic
CAPTCHA, paid ROD image carts) stay off-limits.

## PART 2 — Genuinely-new avenues NOT in any current doc (with how-to)

These are motivated-seller signals the research docs don't list. Verify each endpoint before wiring — I'm giving the method + where to find it, not a promised live URL.

1. **Property-tax / assessment-APPEAL filings (Board of Equalization).** Owners formally contesting their assessed value are self-identifying as financially pressured or planning to sell. **How:** most NC/SC counties publish BOE/appeal agendas or decisions (county assessor site → "Board of Equalization" minutes/PDFs; some on the ArcGIS open-data portal). Parse owner + parcel from the agenda; stamp a `tax_appeal` signal. Free, under-chased.

2. **PACE / solar / clean-energy assessment liens + UCC fixture filings.** A property-assessed clean-energy lien or a solar UCC fixture filing is a real senior-lien-stack item AND a mild distress signal (over-leveraged improvements). **How:** NC/SC Secretary of State UCC search (NC SoS UCC is free/stealth-reachable — we already hit `sosnc.gov`); filter `collateral` for fixture/energy filings by owner name; feed the lien_stack enricher.

3. **Landlord / rental-registration rolls (tired-landlord signal).** Cities with mandatory rental registration publish the roll (Asheville, some Upstate SC municipalities). A registered rental owned by an out-of-state/absentee owner = tired-landlord. **How:** `site:opendata.arcgis.com {city} rental registration` or the city clerk's open-data page; join to the board on parcel/owner.

4. **Unclaimed foreclosure/tax-sale SURPLUS funds cross-reference.** After a tax/mortgage sale that overbid, the former owner is owed the surplus and has already lost the property — a warm "we can help you recover funds + your next move" contact. Terry Howe FLC covers part of the SC forfeited-land side; the surplus/overage lists are separate. **How:** SC county Delinquent Tax "overage/surplus" lists (often PDFs on the treasurer site), NC Clerk of Superior Court surplus-funds notices; cross-ref owner names to the board.

5. **State unclaimed-property cross-match (NCCash / SC Unclaimed Funds).** Owners with unclaimed property AND a distress signal on the board = a reachable, receptive contact. **How:** `nccash.com` and `treasurer.sc.gov/unclaimed` name search by board owner surnames (rate-limit gently); it's a corroboration/contactability booster, not a primary source.

6. **Bankruptcy Schedule A/B real-property parse (depth on the existing lane).** The bankruptcy lane flags filers; the petition's **Schedule A/B** lists the debtor's owned real estate with the debtor's own value + secured claim. That's a free owner-stated value + lien figure — rare in this data. **How:** for footprint Ch7/13 cases already found via CourtListener/RECAP, pull the schedules PDF (RECAP archive is free) and OCR/parse the real-property rows.

7. **Post-Helene blue-tarp / damage aerial classification (vision on aerials).** We have Helene ArcGIS damage layers; the un-tapped piece is running Vision on **recent aerial/oblique imagery** to flag visibly-damaged or tarped roofs the official layers miss. **How:** county post-storm orthoimagery (NC OneMap / county GIS image services) → tile the parcel bbox → free Vision pool (already built) → `storm_damage_visual` signal. Free, and the Vision pool is idle capacity.

8. **NC eviction / summary-ejectment via small-claims (the open NC half).** SC magistrate eviction rosters are walled (documented), but NC small-claims/summary-ejectment is reachable via the open eCourts **Judgment/Civil** JSON lane we already use for lis-pendens + divorce — not yet wired for ejectment. A landlord filing evictions is a tired-landlord seller. **How:** extend the open NC eCourts Judgment-search query (the non-WAF lane) to the ejectment case type; join to owner.

---

## PART 3 — The three strategies, made concrete

### A. Run the 25-lead paid skip-trace pilot (the #1 move — proves or kills the deal math)
1. Rank the board by distress_stack=HOT, equity high, court_confirmed, mailable. Take the top 25.
2. Skip-trace just those 25: DataZapp (~$0.03) for a cheap baseline OR REISkip/BatchData (~$0.15, DNC/litigator-flagged) for call-ready numbers. ~$4–15 total.
3. Scrub against the National DNC Registry. Dial 8am–9pm local, TCPA wireless rules.
4. Measure: contact rate, conversation rate, cost-per-answered-call vs the 1-in-40–60 assumption. In parallel confirm the ARV/GLA + max-bid fixes are live so the numbers are trustworthy.
5. This is a <$50, one-week experiment that tells you if the whole engine converts. Do it before spending on more sources.

### B. Always-on host (fixes the reliability problem permanently)
- The last two runs died from the **laptop sleeping** (lid-close on battery beats `caffeinate`). Code can't fix that.
- Cheapest fixes, in order: (1) keep the laptop **plugged in + lid open** during a run; (2) a used **Mac Mini** ($150–300) that never sleeps, `run_local.sh` on the existing launchd schedule; (3) a small always-on **Linux VM** ($5–20/mo) — needs the stealth-browser stack (patchright/camoufox) ported, more work.
- With the parcel cache + phase caps shipped this session, a run on an always-on host should finish in single-digit hours unattended.

### C. The "act-on-it" layer (turns the list into deals)
- The engine FINDS + VALUES; it has no outbound workflow. Half-built: `buyer_match` (dispo side).
- Build: export HOT/WARM to a CRM (or n8n flow) → sequenced direct-mail (Stannp/TrueNCOA at ~$20/file NCOA, the cheapest compliant lane) + a call/SMS queue for the skip-traced slice. Direct mail first (no TCPA exposure), phone for the shortlist.
- This is the gap between "17k-lead list" and "signed contract."

---

## PART 4 — The complete wall list is already exhaustive

`docs/blocked_sources_forensic.md` has ~60 rows across Court portals / Taxes / Deeds-ROD / Contact-skip-trace / Comps / Federal-auction / Business / Multifamily / Legal-notice — each with **Category (WONT/CANT/ABSENT) · the bypass that would work · the exact error · why I didn't · your manual step.** That last column IS the how-to. The honest summary there: the biggest bucket is ABSENT (data not published at any price — SC exempt-deed prices §12-24-70, servicer payoff balances, NC power-of-sale debt figures, magistrate-eviction rosters, structured buy-box); the CANT bucket (DataDome/Akamai/Cloudflare/F5 SPAs, decommissioned sites) is where a paid unblocker like Bright Data *might* help; the WONT bucket (CAPTCHA/login/ToS/paid) is pure compliance line — an operator willing to pay or cross it unlocks those. Feed Hermes that file wholesale; don't re-derive it.
