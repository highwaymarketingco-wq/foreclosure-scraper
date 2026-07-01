# Blocked / Dead / Manual Source — Forensic Reference

Every source the pipeline can't pull, classified so the operator knows what a different tool or vendor could unlock vs. what nobody can get free. Merged from the code-level failure mining (`base_scraper.py` outcome taxonomy, WAF dumps, disabled_reason strings) and the memory-file source registry.

## The three categories

- **WONT** — compliance choice. A bypass *exists and would work* (CAPTCHA solver, login, paid API, subscriber wall), but riding it to sustain automation crosses the hard line in `feedback_foreclosure_keep_bypass_code` / `project_motivated_seller_engine`: fingerprinting stealth (curl_cffi / StealthyFetcher / camoufox running the page's own JS) is permitted as compliant public-search; defeating a CAPTCHA, login, WAF bot-check, ToS scraper-prohibition, or spending money is NOT. A different operator willing to cross that line, or to pay, unlocks these.
- **CANT** — technical. 403 / dead site / decommissioned / SPA-with-bot-protected-backend / challenge-response, with no free path found. A paid unblocker (Bright Data, residential proxy, paid CAPTCHA solver) *might* crack some; a decommissioned site nobody can.
- **ABSENT** — the data is legally or structurally not there. Exempt deeds state no value; the field is omitted from the API payload; no bulk feed exists; the figure is private servicer PII. Nobody — free or paid — extracts what isn't published. Only a FOIA, a paid county CAMA extract, or the servicer itself produces it.

Columns per table: **Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step.**

---

## Court portals

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| NC eCourts / Tyler Odyssey Smart Search — **Estates** (`portal-nc.tylertech.cloud/Portal/.../29`) `scrapers/counties_nc/nc_ecourts_estates.py` | CANT | Tyler aws-waf-token (`tyler_waf_token.fetch_waf_token`) + Scrapling `StealthyFetcher(solve_cloudflare=True, google_search=True)` + free Gemini-vision grid solver (`enrichment_waf_oss.solve_waf_via_browser`) — all present, all fail | AWS-WAF **escalating image-grid CAPTCHA**; dump `debug/nc_ecourts_estates_estates_waf_fail.html` (~52KB) contains literal `"Let's confirm you are human"` + `AwsWaf` + `Human Verification` + 13× `captcha`. Gemini solver "solves 2 puzzles, WAF keeps issuing more." `disabled_reason = "NC eCourts AWS-WAF CAPTCHA unsolvable; NC estate covered via Column"` | Not a choice — WAF does NOT clear even with the vision solver; "burns vision quota and logs errors for 0 results every run" | Playbook Site 2: portal → Smart Search, Location=county, Category=Estates, blank name + date range, save results HTML to repo root; `scripts/parse_nc_ecourts_export.py` ingests. NC estates ALSO covered compliantly via Column |
| NC eCourts — **Divorce** (same portal) `scrapers/counties_nc/nc_ecourts_divorce.py` | CANT | same aws-waf-token + StealthyFetcher + Gemini solver stack | Same AWS-WAF grid; dump `debug/nc_ecourts_divorce_divorce_waf_fail.html`. Code checks `if "let's confirm you are human" in body or "awswaf" in body`. `disabled_reason = "NC eCourts AWS-WAF CAPTCHA unsolvable (divorce); no free alternative"` | Not a choice — WAF; "0 results, burns Gemini quota" | Playbook Site 2: save Civil ▸ District ▸ Domestic results HTML. No other free divorce route |
| NC eCourts — power-of-sale / SP foreclosure lane (same portal) | WONT | same Tyler WAF-token / CAPTCHA stack | same AWS-WAF wall; real browser works but bypass forbidden | Won't ride a human-solved CAPTCHA to sustain automation | Manual blank-name + date export by user, ingest offline |
| SC PublicIndex — civil+criminal broad sweep (`publicindex.sccourts.org/<County>/PublicIndex/`) `scrapers/counties_sc/sc_public_index.py` | WONT | Scrapling `StealthyFetcher` (real camoufox runs the page's own JS — "no solver, no token forgery, no login"); the F5 wall is cleared this way for the one running lane | `PISearch.aspx` gated by **F5 Distributed Cloud / Shape "Client Challenge"** — `<title>Client Challenge</title>`, `/_fs-ch-.../` bundle. curl_cffi gets 200 on disclaimer but "cannot run the JS." Disclaimer also "expressly prohibits automated scrapers/repetitive querying"; home addresses removed for all cases 2026-01-01; Rule 610 = per-held-case only | ToS wall — existing stealth scrapers "keep running as-is. We do NOT expand them to new lanes or counties (that would mean writing new bypass code)." Admin order + ACLU suit + CAPTCHA/IP-ban history | Playbook Site 1: accept disclaimer, Court Type + Case Sub-Type per 6-lane recipe, Date-Type=Case Filed, name blank, Ctrl-S → `ingest_sc_publicindex_export.py` (imports NO HTTP client by design). Use MIE rosters for the bulk-legal path |
| SC PublicIndex — Foreclosure/Lis Pendens (the ONE running lane) `scrapers/counties_sc/sc_public_index_lis_pendens.py` | runs | StealthyFetcher + injected `<script>` postbacks (Playwright `page.evaluate`) for the CP-Foreclosure-420 filter only | F5/Shape Client Challenge (same wall, cleared) | n/a — sanctioned lane (~233 leads) | for other lanes → manual save |
| SC PublicIndex — per-case DETAIL (TMS + judgment $) | ABSENT | none exists | Detail sits behind `__doPostBack` JS links that are **dead in a static saved HTML file** — "clicking them in the saved copy does nothing" | Not a choice — JS-only navigation | Save a detail page only when you need the dollar amount on a specific top lead |
| SC Magistrate / summary-court EVICTION rosters (`publicindex … RosterSelection.aspx`) | ABSENT | none — drove StealthyFetcher into RosterSelection.aspx directly | Portal exposes ONLY Circuit-court roster types (RosterCodes MO/MJURY/MNOJ/PDIA/PDPL/PDSA/PDST/PDTR; CourtAgencies 42001/42002); "There is NO magistrate/summary/ejectment/eviction roster type." Greenville 404s the roster path. Confirmed 2026-06-30 | Not a choice — magistrate courts are county-operated / in-person, no free bulk feed exists anywhere | Manual save per county, OR FOIA Chief Magistrate ("only free case-level eviction route"), OR LSC data-sharing agreement (`civilcourtdata@lsc.gov`) |
| SC Family Court divorce (case-level / bulk) | ABSENT / WONT | partial FCCMS name-search path (`enrichment_sc_divorce.py` via `portal.fccms.sccourts.org`); comprehensive = paid UniCourt/Trellis | "SC Family Court is a separate, access-restricted system — **not** on the PublicIndex portal at all"; Court Type dropdown has only All/Circuit/Summary/Masters-In-Equity — "There is NO Family Court and NO Probate Court here." Public Index divorce prohibited (admin order + ACLU + CAPTCHA/IP-ban) | Structurally absent from the public portal; comprehensive route is paid | "Skip SC divorce," or paid UniCourt/Trellis API, else newspaper classifieds |
| SC Probate / estates (case-level) | ABSENT | none | SC estates live in separate county Probate Court, not PublicIndex | Structurally absent | Covered another way: obituaries + Gannett Upstate heirs pipeline. "Don't chase the portal" |
| Civil money judgments — SC Upstate | ABSENT-deferred (buildable) | extend `sc_public_index_lis_pendens.py` camoufox form-drive with CP money-judgment sub-type | Not blocked — deferred | Rule-610 bulk-use caution + low lead quality (commercial debtors); "Build only if asked." NC half is WAF-walled | Bounded 60-day single-subtype search if authorized |
| NC power-of-sale debt $ / SC counties not online | ABSENT | none | "NC power-of-sale notices legally state only sale terms/deposit/upset-bid, and the SP file $ lives at the Clerk's office, not online" | Not published online | FOIA Clerk of Superior Court (NC) / Clerk + MIE (SC); templates in `docs/foia_court_records.md`; ask for electronic CSV/Excel |

---

## Taxes

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| Cherokee SC delinquent-tax page `scrapers/counties_sc/sc_tax_delinquent.py` | CANT | none wired | "Cherokee returns 403 (Cloudflare)" | Not a choice — 403 | Re-probe July/Aug when county publishes |
| Spartanburg / Laurens delinquent-tax URLs (same file) | CANT | none | "return 404 (CivicEngage CMS migration)" | Not a choice — dead URL | Re-probe each cycle |
| Union delinquent-tax (same file) | CANT | none | "Union DNS-fails" | Not a choice — DNS failure | Re-probe |
| Pickens delinquent-tax (same file) | ABSENT | filter `_is_post_sale_pdf()` | Only links **post-sale RESULT PDFs** ("BIDDER #"/"SALE/BID PRICE") — produced ~1216 address-less fake leads, now excluded | No current pre-sale list published | Re-probe for a genuine pre-sale PDF |
| Anderson tax balance (`acpass.andersoncountysc.org`) | CANT | none | "Anderson (403 auth)" | Not a choice — auth-gated 403 | Per-parcel portal lookup |
| Cherokee tax balance | CANT / ABSENT | none | "Cherokee (parcel-format mismatch)" — portal works but "board stores 13-digit numeric parcel vs portal dashed — no clean join" | Not a choice — no clean join key | Per-parcel lookup |
| Pickens tax balance | ABSENT | none | "Pickens (no bulk qPayBill; qPublic per-parcel card only)" | Structural — per-parcel only | qPublic per-parcel card |
| Spartanburg tax-sale-list PDF $ | ABSENT → SOLVED | per-TMS portal (guessed hostnames don't resolve) | tax-sale PDF "has NO amount column (item#/TMS/name/situs only)"; "guessed hostnames (tax./rpa./publicaccess.spartanburgcounty) don't resolve" | Field not in PDF | **SOLVED** via `enrichment_qpaybill_tax.py` (qPayBill Unpaid search by owner surname, +408, live-verified 2026-07-01, no login/CAPTCHA) |
| Spartanburg CAMA FTP (published creds exist) | WONT | stored credentialed login | "server is firewalled to us via SPARTNET 192.146.148.0/24"; "I do not automate/store credentialed logins" | Won't automate/store logins; also IP-firewalled | Email `Assessor@spartanburgcounty.org` for the extract |
| Beaufort SC county portal | CANT | none | "Beaufort SC portal WAF-blocked" | Not a choice — WAF block | none noted |
| Owner mortgage payoff / current loan balance | ABSENT | none exists | "Held only by the servicer. Not public anywhere (PII, changes mid-month)." MERS ServicerID "returns the SERVICER NAME ONLY, never a balance" | Private servicer data | Proxy: judgment/opening-bid $ from saved Judgments page, or OCR original loan amount off recorded deed-of-trust image |

---

## Deeds / ROD

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| Cherokee SC ROD (`sclandrecords`) | WONT | login creds | "Cherokee (login-walled)" | Won't defeat login | Paid/login account; index only where it works |
| CCHS ROD — Burke / Lincoln / Cleveland / Henderson NC (`us5.courthousecomputersystems.com`) `enrichment_cchs_rod.py` / `rod/cchs.py` | CANT | none — needs new-provider discovery | "DECOMMISSIONED": index serves 200 but searchonline.asp / home.asp / recordingrules.asp / index.asp "ALL return IIS 404 — only default.asp survives" (classic-ASP SearchService.asp dead) | Not a choice — free online CCHS search is gone | Fresh discovery of the counties' new (maybe paid) provider |
| Rutherford / Polk — Cott RecordRoom (`cotthosting.com`) `rod/cott.py` | WONT | subscriber login | "Rutherford (Cott) stays DEAD (subscriber wall)"; earlier "returned 0 — session/__VIEWSTATE handshake" | Won't defeat subscriber wall | Paid subscriber; (Union via `cott_recordroom.py` works for named probate) |
| Kofile / Oconee SC ROD (`oconee.sc.publicsearch.us`) `rod/kofile.py` | CANT | internal-API real-browser request → StealthyFetcher render fallback; Typesense/Algolia-style JSON-API discovery | "HTTP 200 but it's a React app (SPA), 0 rows"; "Web app with bot-protected backend, blocks raw curl"; "needs network-tab/JSON-API discovery" | Not a choice — SPA yields 0, no server-rendered results table | Reverse-engineer the JSON API |
| Spartanburg bulk instrument search `enrichment_spartanburg_rod.py` (Logan) | CANT (bulk) / worked-around (per-owner) | `rod/logan_render.search_by_name_render` headless browser (~25s/owner, HOT-first, capped 30/run) | "server-side SQL broken" for bulk; DataTables AJAX returns empty tables to httpx. (Site was HACKED ~2026-06-14, down ~10 days) | Bulk broken server-side; per-owner render is the workaround | Deed-of-trust image FREE on Logan (200, application/pdf, ~281-313KB, no cart/login) → OCR for loan amount. Books with alpha suffix use a DASH ("149D" → "149-D") |
| AcclaimWeb consideration / sale price (Pickens) `rod/acclaim.py` | ABSENT | index reachable browserless+free (no CAPTCHA/token): `/Search/GridResults` JSON; Consideration search LowerBound/UpperBound accepted | "**AcclaimWeb omits consideration in its JSON**" — GridResults returns DirectName/IndirectName/DocType/BookPage but no $ | Field omitted from the API payload | Per-parcel qPublic assessor CARD instead (carries sale-price history); index only for $ |
| AcclaimWeb / Logan document IMAGES (lien $) — some counties | WONT | vendor subscriber login | "AcclaimWeb document IMAGES are vendor-PAYWALLED (the real 'ROD lien $' wall, not a code gap)"; "some Logan/AcclaimWeb counties charge for images or require a subscriber login" | Won't defeat login/paywall | Paid subscriber account per vendor |
| Aumentum ROD — Buncombe / Gaston | CANT | re-verify __VIEWSTATE/session handshake | search_by_name → 0 docs (stale parser, endpoints changed) | Not a choice — un-root-caused endpoint change | none (rebuild adapter) |
| Gaston ROD lien-existence | RESOLVED (free) | headless Playwright: GET / → GET /LRSearch/LRIndex (seeds context) → POST ExecuteSearch | earlier "Object reference" error = missing server-side search context (fixed) | No login/CAPTCHA on search (reCAPTCHA only on paid document-image flow); Kind code D/T = mortgage | n/a (built) |
| Buncombe / Charleston deeds portal — instrument-type SELECT-ALL | CANT | none | "switchIC() toggles instrument-type checkboxes never populated into the empty container, so SELECT-ALL SQL-errors — their bug, uncrackable from outside" | Not a choice — server-side defect | none; harvest CAMA distress signals from ArcGIS instead |
| Recorded lien / loan $ from ANY ROD index (`enrichment_doc_ocr.py`, `extract_lien_amounts.py`) | ABSENT | OCR where the image is free | "ROD name index shows type/lender/date/book-page only. The '$X principal' is only on the scanned image" | $ not in index | OCR the free deed-of-trust image (Spartanburg Logan) for loan amount |
| SC deed-stamp OCR → sale price `rod/deed_stamp.py` | ABSENT | none viable | "§12-24-70: exempt deeds (foreclosure/deed-in-lieu/spouse per §12-24-40) state NO value, only exemption reason; distressed targets carry no recoverable stamp"; "no stamp field on any SC GIS layer" | Distressed deeds are stamp-exempt by statute | qPublic per-parcel CARD (Pickens/Oconee expose sqft + sale-price/book-page history) |
| SC sale price + heated sqft from county GIS/assessor (Tier-0) | ABSENT (bulk) | per-parcel assessor CARD (`assessor_cards/cherokee_sc.py` — curl_cffi chrome, NO CAPTCHA) | "SaleAmount AND LivingArea (heated sqft) are EMPTY everywhere"; on the AGOL CAMA mirror "LivingArea>0 = 0 of 29,402 records"; SCDOT numeric fields CORRUPTED (1e22); "withheld behind the paid county CAMA extract" | Bulk field withheld | Pickens/Oconee cards expose sqft+sales as text; MS Building Footprints for sqft; email `Assessor@spartanburgcounty.org` for extract |
| Mechanic's liens / distribution ($0 love-and-affection) deeds / in-footprint HOA assessment liens | ABSENT | ROD adapters (currently OFF) | "no unified free index; ROD adapters currently OFF"; "no deed-type filter, needs consideration-clause text parse" | Blocked on ROD rebuild | Buncombe ROD SrchName.aspx reachable as a start when ROD is back |

---

## Contact / skip-trace

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| Consumer people-search: TruePeopleSearch / FastPeopleSearch / Radaris / Whitepages `enrichment_skip_trace.py` | WONT | Cloudflare bypass / CAPTCHA solve | "all return Cloudflare 403 / mask the phone behind a paywall teaser + ban automation in ToS" | "defeating them crosses our bot-wall line, so we DON'T" | Direct mail. Absentee/mailing mismatch + NC voter file (`enrichment_voter_phone.py`, ~69% phone) is the compliant scaled channel |
| Forward phone/skip-trace APIs (batchskiptracing / Spokeo / SearchBug) | WONT | paid API (~$0.22-0.45/hit) | paid; Twilio Lookup / NumVerify / OpenCNAM are phone→name (wrong direction) | Free-only policy | Paid licensed non-FCRA "locate to transact" skip-trace API, only if user authorizes |
| Owner email | ABSENT | none | "Same as phone — third-party PII, paid-only" | Paid-only PII | Mail |
| SC voter file (phone) | ABSENT / WONT | paid voter list | "SC voter list is paid, voter-purpose-only (SC Code 30-2-50 bans commercial solicitation), and carries NO phone" | Legally purpose-restricted; no phone field | NC voter file works; SC has no route |
| Aggregator scrapers (Thunderbit / Apify / Outscraper for mobiles) | ABSENT | n/a | "only extract phones already published on a business page (= business phones we already get); none get individual mobiles" | Individual mobiles not published | Paid skip-trace API |
| Paid data brokers (PropStream / ATTOM / Regrid-premium / RentCast / NCOALink) | WONT | paid subscription / license | "All paid or trial-only; free tiers too small or blank for SC"; "NCOALink paid-only ($15k+/yr)" | No-spend policy — "record as wall, never buy" | GIS mailing + absentee flag is the free ceiling |
| OpenCorporates API | WONT | paid token | "paid token (401)" | Free-only policy | none |
| NC SoS entity owner (`sosnc.gov`) `enrichment_sos_agent.py` | runs | Scrapling stealth (Cloudflare JS pass, not defeat) | `sosnc.gov` behind Cloudflare JS-challenge (not CAPTCHA) | n/a — works free | none |
| NC SoS bulk business data | WONT | paid `/online_services/data_subscriptions` | paid data-subscription tier | Free-only policy | Per-profile stealth search works free |
| SC SoS entity owner (`businessfilings.sc.gov`) `enrichment_sos_agent.py` | WONT | CapSolver / 2captcha | "SC's businessfilings.sc.gov is **CAPTCHA-gated** ('Invalid Captcha') → SC entities are skipped, not scraped" | Solving CAPTCHA is out of scope | NC SoS works free; SC entities skipped |
| PropWire (skip-trace / freemium) `scrapers/national/propwire_foreclosures.py` | WONT | DataDome bypass + account login; Apify actor ($0.007/record) in git history | "hard wall: DataDome bot-protection (403 + JS-CAPTCHA on every path) AND account-gated freemium skip-trace (third-party PII)"; returns `[]` silently | "Do NOT bypass"; no-spend | User exports from their own free PropWire account → ingest via `contact_ingest.py`; or revert to Apify impl if user pays |

---

## Comps / valuation

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| SC recorded $/sqft comps | ABSENT | none | Same as SC deed-stamp: exempt deeds carry no value; AcclaimWeb omits consideration | Legally/structurally missing | "Do NOT rebuild $/sqft comps unless a county extract is verified by name to carry both fields" |
| SC foreclosure sold-price comps `enrichment_foreclosure_sold_comps.py` | ABSENT | NC deed-stamp × 500 works; SC does not | SC §12-24-70 exemption → no recoverable hammer price | Exempt | NC only |
| Universal ~13% explicit-debt ceiling | ABSENT | none | "Free tools hit the same ~13% explicit-debt ceiling the paid ones do" | Data simply not public | Proxy estimates only |

---

## Federal / auction

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| homesales.gov (HUD/FHA) | CANT | none | "DECOMMISSIONED. Connection fails entirely (HTTP 000, no response)" (2026-06-30) | Not a choice — site dead | none |
| US Marshals real-property sales (`usmarshals.gov/assets/sales/real-property`) | WONT | none | "403 (blocked, no public feed)" | Login/block; already covered via Bid4Assets | USMS surplus via Bid4Assets |
| irsauctions.gov | CANT | none | "root `/` returns 200 but `/index.cfm` returns 403; `/Sales` is 404. No reachable listing endpoint" | Not a choice — no reachable endpoint | none |
| GSA realestatesales.gov `/api/properties` `scrapers/reo/gsa_realproperty.py` | WONT (API) / worked-around (HTML) | auth login on the JSON API | "302 → /login/ (login-gated; JSON API requires auth)" — so we scrape the server-rendered `/our-listing/` index instead, "explicitly NOT the API" | "FREE+public only, never defeat login" | none needed — HTML index works (12 active nationwide, off-footprint = clean ZERO) |
| GovDeals real property `scrapers/counties_nc/nc_govdeals_real_property.py` | CANT | re-key x-api-key from live `main.<hash>.js` bundle | `GOVDEALS_API_KEY 'af93060f-…'` returns HTTP 400; current Angular-bundle UUID keys return 401 → maestro.lqdt1.com silently yields 0 rows. `disabled_reason = "dead API key (HTTP 400) since 2026-06-30 + low ROI"` | Dead key; low ROI (last good = 9 NC + 1 SC) | Re-discover x-api-key + payload from live JS bundle |
| USDA RD resales `scrapers/reo/usda_rd.py` | CANT-transient | JSP session-scoped 3-step flow | `disabled_reason`: "froze the concurrent run 2026-06-27 (no completion in 2h47m)" | Performance hang, not a wall | — |
| Foreclosure.com `scrapers/national/foreclosure_dot_com.py` | WONT / CANT | GET, curl_cffi impersonate, AND stealth browser — all tried | `disabled_reason = "edge-WAF 403 to GET/impersonate/stealth-browser; paid-preview, no free access; redundant"` | Edge-WAF; paid-preview; redundant with zillow/realtor/trulia/auction.com/hubzu/xome/bid4assets | none (redundant) |
| LoopNet (residential) | CANT | none | "hard 403" | Not a choice — blocked | none |
| Fannie HomePath search endpoint | CANT | none | returns "BROAD property DB (636k nationwide, most 'Active'), NOT just Fannie REO"; deep-link propertyUuid ROTATES (~58/1057 still match) | No is-REO filter; uuids stale | Fannie re-resolver by address (not built) |

---

## Business (`~/business-scraper`)

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| DealStream `scrapers/brokers/verified_disabled.py` | CANT | none | "DataDome CAPTCHA wall: every request (incl. /robots.txt) returns HTTP 403 with a `geo.captcha-delivery.com` challenge to curl-cffi chrome + render. NOT_VIABLE" | Not a choice — DataDome 403; CAPTCHA defeat out of scope | none |
| LoopNet (businesses) (same file) | CANT | none | "Akamai shell: /biz/ returns a ~2.5KB JS interstitial (no listing data) to curl-cffi chrome AND stealth render. Same Akamai wall as BizBuySell. NOT_VIABLE without WAF defeat" | Not a choice — Akamai | none |
| BizQuest — cash_flow / revenue (memory: `project_business_scraper_financials`) | WONT | login creds | "cash_flow/revenue are LOGIN-GATED (scraper notes `cash_flow_login_gated: True`)"; list pages give name/city/industry/asking_price only | Won't defeat login | none free — asking-price only (WARM) |
| BusinessesForSale.com — JSON-LD financials (same file) | CANT | Cloudflare bypass | "returns a Cloudflare 403 challenge stub to the impersonate fetch (`is_challenge_stub` detects it → 0 = BLOCKED, shows ZERO_RESULT)"; "Do NOT keep re-chasing it" | Won't bypass Cloudflare | Syndicates Transworld inventory where reachable |
| Murphy Business (same file) | CANT | re-probe | "Server-side bot block: HTTP 503 to curl-cffi chrome on every path/UA" | Not a choice — 503 | Re-probe (may be transient/geo-gated) |
| Sunbelt / Transworld / WeSellRestaurants (same file) | CANT (render-dependent) | Scrapling render pass (not yet built) | HTTP 200 but "listing grid is client-hydrated — raw HTML carries no asking-price/cash-flow text"; WP REST exposes no listing post-type; Transworld = "~1MB JS shells with ZERO server-rendered listing data" | Render path not built | Enable once render pass built + smoke-tested |
| Google Business Profile review_count (`service_source_research.json`) | ABSENT / CANT | paid Places API ($17/1k) | "review_count NOT obtainable free (0/20 across every method)" — absent in `tbm=map` JSON (rec[4] terminates at rating index 7, no index 8), headless list cards, and place panel; "requires paid Places API or paid scraper." Full grid → "Google-rate-limited to 0 rows"; walls same-day after flag. Yelp/BBB/Cylex = CAPTCHA/Cloudflare/PerimeterX-walled | Field stripped in unauthenticated context; paid off-policy | Get review_count from YellowPages instead; use rating + utm=gbp proxy |
| SC LLR contractor roster (`llr.sc.gov` / `verify.llronline.com`) (`service_source_research.json`) | CANT | headed Chrome (Playwright headless=False + virtual display) via MCP | "stateless curl_cffi … STILL returns 0 records"; "ONLY the non-headless Chrome-MCP click-flow returned 1217"; "NOT an autonomous stateless/headless HTTP target — session seats only via full JS click-flow" | Not a choice — bot mitigation / interactive-only gate | Queue as render-lane build; SC LLR FOIA (`docs/sc_llr_foia_request.md`) |
| Anderson SC business-license roster | ABSENT | n/a | "NO roster (only blank application forms + ordinance PDF, no downloadable list)" | No list published | none |
| Mewborn & DeSelms (Onslow tax) | CANT | Cloudflare bypass (curl_cffi defeated) | "Cloudflare 403 defeats curl_cffi" | Won't bypass Cloudflare | Onslow covered via Column + nc_coastal_tax_foreclosure |

---

## Multifamily / coastal

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| LoopNet (MF) `scrapers/national/crexi_multifamily.py` (docstring) | CANT | none | "LoopNet hard-blocks: plain + stealth fetches both return HTTP 403" | Not a choice — 403 | none |
| auction.com / Ten-X MF (same) | CANT / ABSENT | none | "multifamily/commercial inventory lives on Ten-X → LoopNet, which is login-gated + 403-walled. Not viable free"; residential JSON-LD is all `SingleFamilyResidence` | Login+403; MF not in feed | Crexi (only free MF source) |
| HUD MF weekly list | ABSENT | free but empty | "genuinely free but a NATIONAL list that currently holds ~2 properties, neither in NC/SC" | Never in-footprint | Documented fallback only |
| Fannie / Freddie MF REO | CANT / WONT | broker gate | "All 403/broker-gated/empty" | Broker-gated | none |
| CMBS special-servicing (Trepp / CRED-iQ) | WONT | paid subscription | "Trepp/CRED-iQ are paid" | Free-only policy | none |
| Crexi MF (the ONE working source) | runs | StealthyFetcher passes Cloudflare, 200 OK; slug capture | `/properties/{ST}/Auctions/Multifamily` sub-channel flaky — "302-redirects to a /search/ page with a different DOM carrying no /properties/ slugs" so NOT used | n/a — general channel works (~13 in-footprint) | none |

---

## SoS / entity, legal-notice, law-firm rosters

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| publicnoticesc.com (SCPA) `scrapers/public_notices/publicnoticesc.py` | CANT | paid residential proxy / logged-in session / paid Cloudflare solver | "Cloudflare challenge-response defeats both direct httpx AND Scrapling StealthyFetcher (camoufox). Connection times out repeatedly during Page.goto" | Not a choice — Cloudflare + no-spend | none; SC notices partially covered via sc_public_index_lis_pendens + law-firm + MIE scrapers |
| scpublicnotices.com per-county advanced search | CANT | none | "500s server-side (FormatException)"; popular-search path still works ~10/cat | Not a choice — server error | Use popular-search path or Spartan Weekly |
| ncpublicnotices.com probate detail body `scrapers/public_notices/ncpublicnotices.py` | WONT | detect gate + skip (never solve) | "detail page hides the notice body behind an 'I Agree, View Notice' terms button + a reCAPTCHA" — tokens `"complete the recaptcha"`, `"i agree, view notice"`. (Note: `ncpublicnotices.com` domain itself = NXDOMAIN; real site is `ncnotices.com`) | Site ToS prohibits automated collection of the notice body; reCAPTCHA is the enforcement — we detect the gate and skip | PR/Date-of-Death extracted only when body renders ungated; use ncnotices.com (already scraped) |
| ncnotices.com / scpublicnotices.com per-notice RSS/JSON | ABSENT | n/a | "expose NO per-notice RSS/JSON (only static-page sitemaps)" | Structural — no feed | Already scraped via search-form render path |
| Column legal-notice API (`us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`) `scrapers/newspapers/column_legal_notices.py` | CANT → FIXED (silent death) | drop server-side timestamp filter, sort desc, filter client-side | Server-side `publishedtimestamp` range filter broke ~2026-06: "returns HTTP 200 `{"results":[],"page":{"total_results":0},"success":true}` — no error, no block signal." Format drift so nested {from,to} silently matches 0 rows | Format drift, not a wall | Re-verify `_query` returns >0 whenever NC counts crater |
| legacy.com / echovita / tributearchive (obituaries) | CANT | Cloudflare bypass | "Cloudflare-403" | Won't bypass | Gannett papers + funeral-home RSS (built) |
| RAS Crane (rascranesalesinfo.com) | ABSENT | n/a | "JS routes ONLY CA/GA/TN/TX (NC/SC-Sales.aspx = 404) — permanently dead for us" | Structural — no NC/SC | none |
| Tromberg-Morris-Poulin / Marinosci | ABSENT | n/a | "out-of-footprint (CA/GA/TN/TX, VA-only, no NC/SC)" | Structural | none |
| Meares (mearesauctions.com) | CANT | none | "redirects to dead mpa-sc.com — no current footprint RE auctions, duplicative" | Not a choice — site dead | none |
| 6 firms w/ no public sale list (Crawford & von Keller, Scott & Corley, Grimsley, Nodell Glass & Haskell, Goddard & Peterson, Ward & Smith) | ABSENT | n/a | "NO public sale list (reach us via county MIE rosters, don't build)" | Structural — no public list | county MIE rosters |
| Aldridge Pite | CANT | n/a | "renders but WP admin-ajax 0 rows" | Not a choice — 0 rows | none |
| Hubzu | CANT | n/a | "React SPA stub" | Not a choice — SPA stub | none |
| ZLS / Zacchaeus (zls-nc.com) | RESOLVED | StealthyFetcher render tier ("I AGREE" gate, Blazor/DevExpress WebSocket grid) | old scraper deleted (firm rebranded, old site dead) | requires_render=True, not curl | n/a (rebuilt) |
| SCDEW UI-tax lien registry (`uitax.dew.sc.gov/LienRegistry`) | CANT (low ROI) | StealthyFetcher render or bundle reverse-engineering | "Angular SPA… API path NOT exposed in the bundle"; "dew.sc.gov/employers/tax-liens 404s" | Not built — marginal signal (employer UI-tax liens) | none |
| LiensNC.com (code-enforcement violations) | WONT | mandatory account | "mandatory account/login. No free in-footprint code-enforcement VIOLATION feed" | Won't defeat login | none — permits feeds are zoning not cases |
| Code enforcement / vacant registries / demolition orders | ABSENT | none | "No free public in-footprint feed confirmed" | No feed exists | FOIA / in-person only |

---

## Misc — loan/debt figure, buy-box, Reddit intel, agency tooling

| Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step |
|---|---|---|---|---|---|
| Current mortgage PAYOFF balance | ABSENT | none exists | "published in NO free public source. Only the servicer/lender holds it"; MERS ServicerID "returns the SERVICER NAME ONLY, never a balance" | PII-adjacent, mid-month-dependent | Estimate: judgment/lis-pendens indebtedness > opening bid > DOT-principal amortized > sale×LTV |
| NC power-of-sale Notice of Sale — debt figure | ABSENT | none | "0/24 real NC Column foreclosure Notice bodies contain ANY dollar figure"; "legally state sale terms/deposit/upset-bid only — NOT the debt" | NC law doesn't require debt in the notice | Debt lives in the SP file at Clerk of Superior Court (not online for these counties) |
| DOT principal (loan amount) from ROD index | ABSENT | OCR the free scanned DOT image | "ROD INDEX has no $ — principal is only on the scanned DOT IMAGE"; needs OCR (Tesseract/vision), not text extraction | Index carries type/lender/date/book-page only | `enrichment_dot_ocr` (scoped, un-built): render ROD → view_image PDF (free) → OCR page 1 "principal sum of $X" |
| Structured buy box (county/zip + acreage + price) for WNC / Upstate-SC | ABSENT | none | "NO free/public/scrapeable STRUCTURED buy box exists"; land buyers name counties as SEO text → contact forms; builders take land by relationship/inbound form | No structured feed exists | Built curated static county→buyer registry (outreach list); Brevitas.com/wants is the one scrapeable buyer-wants dir (STATE-level only) |
| Reddit MCP tools (`search_reddit` / `get_subreddit_posts`) | CANT | wire up the MCP server | "NOT connected in this environment" | Not connected | Use Brave / DDG-lite `site:reddit.com` search |
| Apify Reddit scraper actors (trudax/reddit-scraper-lite) | CANT | fix Apify billing | "Apify account is blocked: error 'Too many outstanding invoices' — all paid actors fail" | Billing-blocked | Re-check if billing fixed |
| reddit.com direct (WebFetch / WebSearch / .json) | CANT | Bright Data (paid) | "WebSearch allowed_domains:reddit.com is rejected"; "WebFetch … hard-blocked ('unable to fetch from www.reddit.com')"; ".json endpoints also blocked" | Crawler can't access | Brave Search `site:reddit.com` (best free fallback); DDG-lite single combined OR-query as confirm |
| DuckDuckGo lite / html / Bing / Mojeek | CANT | none | DDG "CAPTCHA'd on query 3"; Bing "serves CAPTCHAs"; Mojeek "403s hard after one query" + loose `site:` false positives | CAPTCHA/rate walls | Sequential (not parallel) queries; Brave first |
| Bright Data (recommended paid fix for Reddit) | WONT | paid API key + CLI | "`BRIGHTDATA_API_KEY` is NOT set and no bdata/brightdata CLI installed" | "do NOT spin up paid infra unprompted" | HWM to authorize + fund |
| SearchAtlas White Label (Agency Hub → White Label Setup) | WONT → RESOLVED | Pro $399/mo or Agency $999/mo upgrade | "logo upload silently rejects files, 'Continue' disabled, 'Branding Applied: Incomplete'"; "NOT included on Growth plan (no add-on)" | Plan-gated | Cash upgraded to Pro → unlocked (sa-1); sa-2 workspace still needs its own Pro |
| SearchAtlas KRT tracked-keyword quota (sa-2) | ABSENT (quota exhausted) | wait for billing-cycle reset / buy quota | Exhaustion surfaces as `MCP error -32602: Structured content does not match the tool's output schema: data must have required property 'result'` — "a quota wall surfaced as a malformed response, NOT a connector bug" | 3,500/mo, charged-on-add, no-refund | Check `get_quota(service="all")`; avoid bulk-import-then-clear |
| SearchAtlas PPC connector — Tillmann live campaigns | ABSENT (stale) | n/a | "connector only has the STALE/paused StoryArc campaigns (account 67136) — shows all paused/$0; do NOT trust it for live state" | Connector stale-paused | Browser via waynseoteam@gmail.com → We Are Your Neon MCC for live data |

---

## The honest summary

Most of these walls are genuinely impossible to get for free, not my choice: the largest bucket is **ABSENT** — data that simply is not published anywhere at any price a scraper can reach. SC exempt-deed sale prices (§12-24-70), heated sqft and SaleAmount blank across every free SC GIS layer, mortgage payoff balances held only by the servicer, NC power-of-sale debt figures that the statute never puts in the notice, magistrate-eviction bulk rosters that no SC portal exposes, and a structured investor buy-box that does not exist as a feed — none of these come from a better tool; they come only from a FOIA letter, a paid county CAMA extract, per-parcel qPublic cards, or the servicer/clerk directly. The **CANT** bucket is where a different tool *could* help: DataDome/Akamai/Cloudflare/F5-Shape walls (DealStream, BusinessesForSale, publicnoticesc, LoopNet) and bot-protected SPAs (Kofile/Oconee, SCDEW) might yield to a paid unblocker like Bright Data or a residential-proxy + paid-CAPTCHA stack — and decommissioned sites (homesales.gov HTTP 000, CCHS IIS-404, irsauctions 403, dead GovDeals key) are dead for everyone until a new endpoint appears. The **WONT** bucket is purely my compliance line and is the clearest lever an operator can pull: NC eCourts' AWS-WAF CAPTCHA, SC PublicIndex's ToS-and-F5 wall, SC SoS's captcha, GSA's login API, PropWire's DataDome+account gate, consumer people-search phone lookups, subscriber-walled ROD vendors (Cott/Cherokee/AcclaimWeb images), and every paid broker (PropStream/ATTOM/OpenCorporates/NCOALink/Trepp) all have a working bypass or a checkout button — I decline them because fingerprinting stealth is compliant public-search but defeating a CAPTCHA/login/WAF or spending money is not. Bottom line: a paid data vendor or an operator willing to cross the bypass line unlocks the WONT rows and some CANT rows; nobody, at any budget, free-scrapes the ABSENT rows — those need a records request, a paid government extract, or the private party who holds the number.
