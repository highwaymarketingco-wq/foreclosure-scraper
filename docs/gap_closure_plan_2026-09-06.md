# Foreclosure Board — Data-Completeness Gap-Closure Plan (verified)

Date: 2026-09-06. Source: 13-agent research + adversarial-verify workflow (wf_963fbb68-83d) over the live board (94,384 leads). Every proposed source was fetched/grepped to confirm real + free + not-already-built before inclusion.

## Executive summary

The single biggest lever is the resolver, and verification confirms it is a WIRING/BACKFILL job on infrastructure the repo already owns — not a new-data problem. ~56K liensnc rows sit at 0% geocode/county/parcel despite 71.5% (~35,700) carrying a geocodable NC street+city, because they entered via the standalone ingest_liensnc board-writer and never went through a full main.py enrichment pass. Running the already-built free chain (Census /geographies/addressbatch for lat/lng+county in one call → NC OneMap NC1Map_Parcels point-in-polygon for parno+situs+value) over that cohort moves ~24-26K rows (~26% of the whole 94,384-lead board) from zero to the full assessor/equity/ARV stack at $0. Everything downstream — ARV, comps, photos, phone, mailing — is gated on that resolve step, so resolver work compounds. Verification also produced ONE genuinely net-new free source (NC AddressNC GeocodeServer as a rural fallback geocoder) and confirmed several high-value already-built-but-unwired assets (Redfin Data Center ZIP $/sqft, Mapillary street-level, OneMap sale-date fields, Census B25077). It knocked down the researcher's other headline "new" sources: the NC excise-stamp ROD sweep is unverifiable (flagship URL doesn't resolve; Buncombe stamps already free via GIS), USPS Addresses v3 was monetized 2026-08-01, and Redfin Stingray / qPublic-Schneider / Street View are all walled or paid. Net: no new data-acquisition project is warranted — the work is backfill and wiring of free assets already in the repo, with AddressNC the only new endpoint to add.

## Measured liensnc pool (rank-1 lever, verified against listings.json.gz 2026-09-06)

- liensnc-family rows: **56,452** (counties_generic.liensnc + liensnc)
- has street address: **40,366 (71.5%)**; has city: 100%; geocodable (addr+city): **40,364**
- has county: **0%** | has coords: **0%** | already valued: **0%**  -> this cohort NEVER went through main.py enrichment
- Core-footprint caveat: geocodable rows skew OUT of WNC/Upstate-SC core — top cities Charlotte(2,847), Raleigh(1,339), Durham(1,209), Asheville(681, core), Wilmington(647). All 40K gain the value stack if resolved; in-core slice is a minority.

## Ranked actions

### #1 — resolver (the 56K liensnc pool; unlocks the entire value stack for the majority of the board)
- **Confidence:** high | **Effort:** medium | **Type:** already_built wiring/backfill — endpoints grep-confirmed in repo (geocode_catchup.py, enrichment_parcel_from_geo.py, NC1Map_Parcels); re-measure the geocodable-address rate against listings.json.gz before committing the yield number
- **Est. lift:** ~24-26K rows (~26% of the 94,384-lead board) from 0% to full assessor value/equity/comps/ARV; honest floor: the ~28.5% with no street address (garbage username + case# only) are unresolvable, and much of the pool geocodes out-of-core-footprint (Mecklenburg/Wake/Durham dominate)
- **Action:** Build a dedicated backfill that runs the already-wired free chain over the ~35,700 liensnc rows carrying a geocodable NC street+city: Census /geographies/addressbatch (lat/lng + county FIPS in one keyless call, reuse scripts/geocode_catchup.py's geographies parser) then enrichment_parcel_from_geo.py NC OneMap NC1Map_Parcels point-in-polygon for parno+siteadd+cntyname+parval. Root cause is that these rows entered via the standalone ingest_liensnc/scrape_liensnc board-writer and never went through a full main.py enrichment pass; countyless rows also fall through the geocoder's county-gated Tier-4 centroid.

### #2 — valuation (ARV 27%, comps 20%) — converts the existing 35% sqft coverage almost directly into ARV even where zero individual comps exist
- **Confidence:** medium | **Effort:** medium | **Type:** already_built-but-unwired + dead-URL fix; NOT the researcher's claimed two-line wire-up — the S3 repoint + gz decompress must land first or the enricher silently hits its download_failed path
- **Est. lift:** ARV 27%→~33-40% (toward the ~35% resolved ceiling), MEDIUM confidence
- **Action:** Wire the already-built-but-unwired Redfin Data Center ZIP median $/sqft into the ARV waterfall. Two blockers found in verification: (a) enrichment_redfin_datacenter.py's REDFIN_ZIP_URL is DEAD (redfin.com/data-library path now 404→429) — repoint to the S3 host https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/zip_code_market_tracker.tsv000.gz (HTTP 200, no auth, 1.5GB gzip) and add gzip decompression; (b) enrich_batch_redfin_datacenter is never called in main.py and calc.py never reads market_stats. Then add a MEDIUM-confidence tier in valuation/calc.py _arv_signals() computing market_stats.median_ppsf × _plausible_living_sqft(li), slotted below Tier 1b recorded-ratio and above Tier 2 zestimate.

### #3 — resolver (raises geocode yield on the rank-1 cohort, especially rural Western-NC roads)
- **Confidence:** medium | **Effort:** medium | **Type:** real_and_new (only genuinely net-new free source in the whole audit; live-verified keyless) — BUT its metadata exposes a global Esri composite locator, so the 'better rural-NC coverage' rationale is unverified: A/B a rural-WNC sample vs Census before trusting the lift
- **Est. lift:** geocode-eligible fraction of the 35.7K from ~65% to ~78-80% (net-new tier)
- **Action:** Add the NC AddressNC statewide GeocodeServer (services.nconemap.gov/secure/rest/services/AddressNC/AddressNC_geocoder/GeocodeServer, geocodeAddresses batch, keyless despite /secure/ path) as a score-gated NC fallback geocode tier AFTER Census batch, to recover the rural WNC situs addresses Census silently drops. Gate on candidate match-score + NC bbox.

### #4 — valuation — ARV on the resolved-but-unpriceable SC/rural slice the $/sqft path can never reach
- **Confidence:** medium | **Effort:** medium | **Type:** already_built config expansion of a firing mechanism; verify each rural layer's sale field individually — do not assume schema
- **Est. lift:** +3-6 board points, MEDIUM/LOW confidence
- **Action:** Expand the already-firing recorded sale-to-assessed RATIO comp path (enrichment_recorded_comps.py RECORDED_COMP_CONFIG / enrichment_recorded_sales.py) to the remaining core counties. This is the ONLY comp path that needs no living_sqft, so it is the only route for the SC counties whose GIS omits heated sqft (Spartanburg, Pickens, Oconee, Anderson, Laurens, Charleston). Work is per-county field verification (sale-price field, date-filter syntax, assessed-value field).

### #5 — photos / real-photo vision grade (11% graded from an actual photo)
- **Confidence:** high | **Effort:** XS | **Type:** already_built, disabled solely for lack of a free token (grep-confirmed); the only free street-level source (Street View is paid, Bing retired)
- **Est. lift:** +2-5% TRUE (non-aerial) grades, dense on Asheville/Hendersonville/Spartanburg/Greenville corridors, thin on rural private drives
- **Action:** Re-enable the already-built Mapillary street-level lane: create a free Mapillary developer token, add MAPILLARY_TOKEN to enrichment_images.py's _mapillary_image() call (currently sends no token → HTTP 500 invalid-token), and flip the two enrich_with_images(use_mapillary=False) flags in main.py (lines ~1832, ~1940). Verify with one authenticated live call before a full run.

### #6 — deed chain + last-sale DATE breadth across all 100 NC counties (near-zero effect on deed PRICE)
- **Confidence:** high | **Effort:** trivial | **Type:** real_and_new (field the endpoint already returns, currently un-extracted)
- **Est. lift:** sale-DATE coverage on every NC resolved lead; do NOT read as a price lift
- **Action:** Add saledate,saledatetx,transfdate to the _NC1_FIELDS outFields list in enrichment_recorded_sales.py (line ~162) and map into gis.last_sale date + enrichment_deed_chain.py. The OneMap statewide parcel layer already exposes these (live-verified) but carries NO price field.

### #7 — valuation — makes the low-tier fallback for the un-comped tail more honest than tax×1.25
- **Confidence:** high | **Effort:** low | **Type:** already_built data (location.py) + calc.py tier
- **Est. lift:** marginal / coarse (whole-ZCTA median, not property-specific); quality not coverage
- **Action:** Add a last-resort ARV floor tier in calc.py reading the Census ACS B25077 median-home-value that valuation/location.py ALREADY fetches (stored as median_home_value, surfaced in web_artifact.py) — slot it below FHFA, above the tax×1.25 / opening_bid×2.4 proxies. This is a formula change, not a data acquisition; the researcher's proposal to add B25077 to enrichment_census_rent.py is redundant.

### #8 — cross-cutting — converts free data ALREADY being fetched into board coverage (contact, resolver, mailing)
- **Confidence:** high | **Effort:** medium | **Type:** already-fetched data wiring; the net-new distress-SOURCE dimension is otherwise closed (18-county footprint source- and county-complete)
- **Est. lift:** ~4,054 dash-strip leads recovered + scattered owner/phone/value fields across ~25 scrapers
- **Action:** Work the docs/extraction_gaps.md queue (~25 scrapers that fetch owner/phone/value/parcel then drop it) and apply the parcel dash/suffix-strip fix (McDowell/Lincoln/Georgetown/Transylvania ~4,054 no-address leads) documented in docs/gap_ledger.md. Also wire the NCSBE voter file's residential-address column (already downloaded for the phone enricher) to emit current-address/absentee confirmation for NC leads.

## Quick wins (do first)

- Re-enable Mapillary with a free token: add MAPILLARY_TOKEN env + flip two use_mapillary=False flags in main.py (XS, +2-5% true street-level grades) — rank 5
- Add saledate/transfdate to _NC1_FIELDS in enrichment_recorded_sales.py (trivial, NC deed-chain DATE breadth across all 100 counties, price-neutral) — rank 6
- Add a Census B25077 median-home-value floor tier in calc.py — the value is already fetched by valuation/location.py, so this is a pure formula change (low effort) — rank 7
- Repoint enrichment_redfin_datacenter.py's dead REDFIN_ZIP_URL to the S3 .gz host (the prerequisite half of rank 2 — the enricher is currently hitting its own download_failed path silently)

## Confirmed dead-ends (STOP chasing — verified walls)

- NAME→parcel matching for the liensnc pool: the `defendant` field holds scraped portal usernames ('Rabbits1966','downeasthomes'), owner_name is 0% — there is no real name to match. Only ADDRESS→geocode→parcel works for this cohort; the whole fuzzy-owner-match resolver stack cannot help it.
- NC excise-stamp Register-of-Deeds grantor sweep (the researcher's deed-price 'biggest lever'): UNVERIFIABLE — flagship buncombe.nc.publicsearch.us does not resolve via curl or WebFetch, the <county>.nc.publicsearch.us free-index pattern is unproven, repo's kofile.py knows only Oconee SC and already guards a robots-disallowed search path, and Buncombe stamps are ALREADY free via GIS. Do not schedule; at most a one-county spike to prove the stamp is served on a FREE index row before any build.
- USPS Addresses v3 API (the researcher's contactability 'biggest lever #2'): NO LONGER FREE as of 2026-08-01 — now requires a funded Enterprise Payment Account + signed DocuSign license ($10 flat then ~$4/1k, no free allowance). Violates the free-only mandate; use the already-wired Census geocoder + HUD USPS-vacancy signal for a 'mailable' flag instead.
- Redfin Stingray gis-csv individual-comp endpoint: Akamai-walled — WebFetch and the researcher's own proposed curl_cffi impersonate=chrome bypass both returned HTTP 403. Plus Redfin ToS forbids scraping it.
- qPublic/Schneider (beacon.schneidercorp.com) assessor photos: live HTTP 403 Cloudflare Turnstile challenge; StealthyFetcher bypass unproven. Spartanburg (largest Upstate SC county) has no free photo path — time-box a single stealth spike at most, else route to manual operator lane.
- Google Street View Static: paid — REQUEST_DENIED without a billed API key; the 10k/mo free tier still requires billing/a card on file. Correctly fenced OFF; only revisit if the free-only rule relaxes to 'free tier with a card'.
- Bing Maps imagery + Streetside: RETIRED for free/Basic accounts (Jun 30 2025 / Oct 2025); enterprise-paid only until 2028. Do not build against Bing.
- SCDOT SC_Parcels statewide MapServer: token-walled (HTTP 200 + {error 499 Token Required}), a server-side SCDOT permission change. No free path back; kills SC statewide point→parcel resolution.
- Regrid parcel API 'free tier': evaluation/30-day sandbox only; real use is $500-2,000/mo. Adds nothing OneMap doesn't already give statewide for NC at $0.
- HUD Aggregated USPS vacancy data: free but access-restricted to governmental/educational/non-profit registrants (USPS agreement) and tract/ZIP-aggregate — a for-profit lead-gen operator is ineligible. Census ACS B25004 is the compliant substitute (0 new leads, scoring only). Note enrichment_usps_vacancy.py already exists dormant behind this wall.
- County CitizenProblems / open code-enforcement ArcGIS layers as a distressed-OWNER source: the endpoint is free/public but the records are reporter-not-owner complaints (mostly public-works/road: bridge closures, damaged signs) with complainant PII the repo deliberately excludes and no owner/parcel locator; the Oconee 'analog' is login-walled/decommissioned. Repo already examined and rejected the Pickens layer. Marginal (a few dozen blight/litter cases).
- SC voter file as a free phone source: paid ($25-$2,500), §30-2-50 bars commercial solicitation to SC residents, and it carries NO phone column. SC personal phone ≈ 0 free — SC contactability is mail-only via recorded owner-mailing address.
- People-search scraping (TruePeopleSearch/FastPeopleSearch/Radaris/Whitepages/Spokeo): Cloudflare/DataDome + ToS bot-wall. enrichment_free_phones.py exists but is deliberately dormant — do NOT wire it.
- SC exempt-deed consideration (foreclosure, deed-in-lieu, intra-family, estate — exactly the distressed targets): legally omitted under S.C. Code §12-24-40/§12-24-70. No free source recovers these prices at volume. HARD legal wall. Also SC county GIS SaleAmount fields are corrupt denormalized doubles (~1.2e9) and are type-guarded/discarded.
- ATTOM transactional API + paid AVM/comp vendors (RentCast, HouseCanary, BatchData, PropWire, Tracerfy, PropertyReach): out of scope under free-only; ATTOM ToS additionally forbids caching >24h and building a derivative DB, which breaks the persistent self-enriching board.
- FreeCNAM (caller-ID name lookup): real and free but adds 0 new phones (name-from-number validation only) and returned HTTP 500 on live test (no-SLA community service). Wire only as a cache-heavy, failure-tolerant confidence tag if at all — not a coverage lever.
- Eviction (SC magistrate / NC summary-ejectment), SC Family Court divorce, and NC power-of-sale (SP) foreclosure debt$: confirmed durable walls (no free bulk feed / access-restricted / statutorily absent). NC divorce is NC-eCourts-Judgment-JSON only (92 leads); the net-new distress-SOURCE dimension is otherwise closed across the 18-county footprint.
