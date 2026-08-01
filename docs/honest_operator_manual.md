# The Honest Operator Manual: What This Engine Can and Cannot Get You

**Footprint:** 11 NC counties + 7 SC counties (Upstate/Western NC core)
**Board measured:** `docs/listings.json`, 29,946 leads, snapshot 2026-07-30
**Walls re-probed live:** 2026-07-31, ~65 endpoints, read-only, two tiers (plain HTTP and TLS-fingerprint parity)
**Compliance line:** free and public only. No CAPTCHA solving, no login bypass, no ToS-prohibited automation, no human-in-the-loop CAPTCHA step.

This document answers five questions: what is blocked, what gets automated, what you have to touch by hand, what does not exist at any price, and what one build is worth more than the rest combined.

---

## 1. What is blocked, and why

Five buckets. The bucket a source sits in determines whether you ever think about it again.

### A. HARD WALL. Technically blocked or legally prohibited. Never automated.

| Source | The actual blocker | What you do instead |
|---|---|---|
| NC eCourts Smart Search (estates, divorce, special proceedings) | AWS WAF, HTTP 405 + "Human Verification" image grid. Identical on both request tiers. | Manual save to the offline parser. NC estates also arrive via the Column legal-notice API. Divorce is now fully solved a different way, see bucket E. |
| SC PublicIndex, every lane beyond the one frozen lis-pendens lane | F5/Shape challenge **plus** an explicit disclaimer banning "automated, repetitive querying" (Rule 610) | Manual save to `ingest_sc_publicindex_export.py`. Do not widen the existing lane. |
| SC Family Court FCCMS bulk | Reachable, but the same ToS ban. Legal wall, not technical. | Per-name lookups only, already built. |
| Spartanburg "Common Pleas Daybook" | Looks like a county-hosted route around PublicIndex. It is not. It 302-redirects to `publicindex.sccourts.org/daybook` with the identical scraper prohibition. Also self-defeating: filings are removed once they get a case number. | Nothing. Close this idea. |
| Kofile / Oconee SC ROD | `robots.txt` literally reads `Allow: /$` then `Disallow: /`. The page loads fine at 98 KB. This was never a technical wall, it is a machine-readable no-automation directive. | Per-parcel by hand. Documents cost $2 to $4. |
| PropWire, DealStream | DataDome 403 on every data path, both tiers | PropWire: export CSV from your own free account. |
| LoopNet | Akamai JS interstitial, 2.5 KB of obfuscation, zero listing data | Crexi is the only free multifamily source. |
| SC SoS `businessfilings.sc.gov` | reCAPTCHA on the entity search form | County assessor mailing address already covers the actionable output. NC entities resolve free via NC SoS. |
| LiensNC, Cott RecordRoom, Cherokee SC ROD, Anderson SC tax portal | Mandatory login or paid subscriber wall | Per-parcel by hand, or FOIA. |
| SC LLR contractor roster | 403 to stateless HTTP, session seats only via a full JS click flow | Headed browser export by hand, or FOIA. Not a seller-lead source anyway. |
| TruePeopleSearch, FastPeopleSearch, Spokeo, Radaris, Whitepages | Cloudflare 403 **and** ToS bans automation | NC voter file plus direct mail. There is no free substitute. |
| Zillow, Redfin, Facebook Marketplace | ToS-prohibited and anti-bot | Realtor.com public JSON for comps. Nothing for FBM. |
| Buncombe and Charleston deed "select all" | Their own server-side defect. The container never populates and the backend SQL-errors. | ArcGIS CAMA distress signals. |
| Google Geocoding API | ToS forbids storing geocodes without displaying them on a Google map | Census plus Nominatim cascade, already built. |
| Utility and water shutoff lists | NC G.S. 132-1.1 expressly removes public-enterprise customer billing information from the definition of a public record | Nothing compels it. Stop asking. |

### B. MANUAL-ONLY. Legally gettable by a human, automation off-limits.

NC eCourts estates / divorce / SP foreclosure. SC PublicIndex six-lane sweep and per-case detail. SC SoS entity detail. SC LLR roster. Anderson and Pickens tax balances. Deed-of-trust images in walled counties. The clerk's SP-file debt figure (not published online anywhere, it lives in the paper file). SC magistrate evictions. The full NC 105-369 delinquent roll in the four counties that publish only the foreclosure subset. Code enforcement, vacant registries, demolition orders outside Asheville. SC bulk CAMA with sale amount and heated square footage.

Ranked and pruned in section 3.

### C. PAID-ONLY. No free access exists.

Skip-trace APIs, owner email, PropStream/ATTOM/Regrid-premium, NCOALink, OpenCorporates API, SC voter file, per-doc-fee recorder images, Trepp/CRED-iQ, UniCourt/Trellis, Google Places API, MLS feed. Prices in section 4.

### D. DOES NOT EXIST. Not published by anyone, at any price.

Exact live mortgage payoff. SC recorded sale price on distressed deeds. SC recorded $/sqft comps. A structured investor buy-box feed. SC voter phone (the column is not in the file). The NC power-of-sale debt figure in the Notice of Sale. SC magistrate eviction bulk roster. Interior property condition. Comps for parcels with fewer than three nearby arms-length sales. Full list and statutory reasons in section 4.

### E. SOLVABLE. Reachable free right now, just not built.

Ordered by value: Greenville SC probate, the NC divorce cause filter, LOGS/Shapiro Power BI feed, jail bookings, Aumentum ROD rebuild, irsauctions.gov, four SC delinquent-tax counties, GovDeals re-key, USDA RD, Fannie HomePath re-resolver, Aldridge Pite NC, DOT-principal OCR, SC per-parcel assessor cards, NC PTS Cloud tenants, BusinessesForSale.com, legacy.com obituaries.

### Walls that changed status this week

Eleven of eighteen top walls were stale or misdiagnosed. This matters because each one was costing you a source you thought was dead.

| Source | What the docs said | What is true today |
|---|---|---|
| **Greenville SC probate** | Unbuilt | 200, 3.19 MB, 1,423 rows, zero WAF, plain GET. Largest free win on the board and it was never walled. |
| **NC divorce (eCourts)** | Behind the WAF | The open Judgment Search JSON already serves `causeOfActionDesc = "FAM - Divorce"`. One config line. |
| **irsauctions.gov** | "No reachable listing endpoint" | `/auction/items` returns 200 / 46 KB and accepts `?state=NC`. |
| **Cherokee, Spartanburg, Laurens, Union SC delinquent tax** | 403 / 404 / DNS failure | All four were plain domain migrations to `.gov`. Cherokee returns 270 KB with 57 tax-sale matches. Not walls. |
| **US Marshals** | "403, blocked" | 403 to plain HTTP, 200 / 196 KB with fingerprint parity. Same mistake as GovDeals. The data is still thin (USMS delegates to contract auctioneers, mostly non-real-estate). |
| **BusinessesForSale.com** | "Cloudflare 403, do NOT re-chase" | 200 / 344 KB / 137 asking-price matches on plain HTTP. |
| **legacy.com** | "Cloudflare 403" | 200, NC obit index returns 288 obituary links. |
| **Murphy Business, Foreclosure.com** | 503 / edge-WAF 403 | Both 200. Foreclosure.com is low value (paid-preview detail, redundant with 8 feeds you already have). |
| **Aumentum ROD (Buncombe, Gaston)** | "Bot-protected, 0 rows" | Server alive, endpoint moved. Stale parser, not a wall. |
| **SCDOT statewide SC parcels** | "The contactability path for SC" | **Now dead.** Returns `{"error":{"code":499,"message":"Token Required"}}` and the layer is delisted. This is a permissions decision by the state. Nothing to engineer around. |
| **NC SoS (`sosnc.gov`)** | "Runs free" | Cloudflare 403 to both HTTP tiers. Works only through the full stealth browser. Anyone assuming a cheap path gets a silent zero. |

Two corrections to file in the repo docs:

- `coverage_gap_analysis.md` ranks "SC case detail pages (HKey)" as build priority #1. That is automated postback traffic against SC PublicIndex, which every other doc correctly calls a ToS wall. It moves from E to B. It is the one place the build queue contradicts the compliance line.
- Kofile/Oconee is in BUILD_NOW in the unblock plan. It belongs in bucket A. Remove it before anyone spends a day on endpoint discovery.

A quarterly re-probe job would have caught all eleven. That job does not exist yet.

---

## 2. What gets automated, and what will not be

### Automated today, no operator time

Nine substitute-trustee law-firm calendars. NC eCourts Judgment Search JSON (lis pendens, claims of lien, liens). SC PublicIndex Common Pleas + General Sessions rolling sweep and the lis-pendens lane. SC Master-in-Equity roster PDFs. NC ROD substitute-trustee and Logan distress recordings. SC ROD (Pickens Acclaim). Column legal notices. ncnotices and scpublicnotices. Delinquent tax across five SC counties via qPayBill and two NC scrapers. Obituaries and funeral-home RSS. Jail bookings (partially wired). Bankruptcy. SC DEW lien registry (~8,000 liens, and the forensic doc's "can't" entry on this is simply wrong). Name-to-parcel resolution against 5 pinned SC county layers and 18 NC county layers plus NC OneMap. Owner mailing address across 16 counties. Geocoding cascade. Assessor cards for four SC counties. Deed-of-trust OCR (Spartanburg only, gated). Distress scoring and valuation.

### Will not be automated, and the compliant route around each

| Refused | Reason | Route around |
|---|---|---|
| NC eCourts Smart Search | CAPTCHA (AWS WAF image grid) | Manual save → offline parser. Estates via Column. Divorce via the open Judgment JSON. SP foreclosure via the trustee law-firm feeds, which arrive earlier and carry the address. |
| Any SC PublicIndex lane beyond the frozen one, including detail postbacks and the daybook | ToS (Rule 610, explicit ban on automated repetitive querying) | Manual save. MIE roster PDFs for judgment dollars. FOIA for scale. |
| Kofile / Oconee ROD | robots.txt `Disallow: /` | Per-parcel by hand. |
| SC SoS entity search | reCAPTCHA | County assessor mailing address (already on 16,054 leads). NC SoS via stealth for NC entities. |
| People-search sites | Cloudflare + ToS | NC voter file. Direct mail. |
| PropWire, DealStream, LoopNet | DataDome / Akamai | PropWire own-account CSV export. Crexi for multifamily. |
| qPublic bulk | Cloudflare Turnstile on the bulk endpoint | Low-volume per-parcel render, already capped and in use. |

No CAPTCHA gets solved, no login gets forged, and a "pause here and let the human click the checkbox" step is not an automation step. If a source needs one, it is bucket B and it lives in section 3.

---

## 3. What you must grab by hand

### KEEP, in this order (unique value per operator-minute)

**1. FOIA batch. 15 minutes per month, then it arrives without you.**
NC Clerk of Superior Court (foreclosure special proceedings plus civil money judgments **with the judgment amount**), 11 counties. SC Clerk of Court copying the Master-in-Equity (Common Pleas foreclosures plus MIE sale roster and judgment amounts), 7 counties. SC Chief Magistrate (ejectment / rule to vacate), which is the only free case-level eviction route in existence. Always request CSV or Excel. SC must respond in 10 business days (20 if the records are older than 24 months) and produce within 30. NC has no deadline.

Why it ranks first: the board has 29,946 leads and **42 plausible judgment amounts**. Nothing else free closes that. Templates are in `docs/foia_court_records.md`. No FOIA response file exists anywhere in the repo, so this lane has never actually been run to completion.

**2. NC eCourts ESTATES. 6 minutes per week for 3 core counties, 22 for all 11.**
Smart Search, Location = county, Case Category = Estate, blank name, last 7 days (first pull: 6 months). Save as HTML Only to the repo root, parser picks it up. Yields decedent name, executor or personal representative, filing date. **Zero automated substitute.** The scraper is written and wired and returns 0 rows because of the WAF. Verify on your first save that the personal representative name survives into the saved grid.

**3. PropWire monthly export. 10 minutes per month.**
Foreclosure and pre-foreclosure filter, footprint counties, Export CSV, run `ingest_contacts.py`. Data tier only, skip the paid skip-trace tier. This is the one manual lane with a working landing parser. Limit: it matches to the board by parcel or property address, so it will land on your address-bearing tax and REO inventory, not on the court inventory where the gap actually is.

**4. SC PublicIndex Foreclosure (420), Spartanburg / Anderson / Laurens only. 6 minutes per month.**
Circuit Court, Common Pleas, Sub-Type Foreclosure (420), Date Type = Case Filed. This is insurance, not new data. The portal grid caps at 250 rows per search (documented in the scraper's own docstring), and a 45-day all-Common-Pleas window in those three counties very likely exceeds it, meaning the automated sweep is silently truncated. I did not measure the truncation directly. The cap is code-documented, the overflow is inference. Skip Pickens, Oconee, Cherokee, Union: their volume is nowhere near the cap.

**5. Anderson and Pickens tax balance. On demand, top leads only.**
Genuinely uncovered. `enrichment_qpaybill_tax.py` maps Spartanburg, Oconee, Laurens, Union, Cherokee and nothing else. **Read the number and type it into the CRM. Do not save the HTML.** Nothing reads `anderson_tax_*.html`.

### STOP doing these. An automated free source already covers the field.

| Stop | Covered by |
|---|---|
| NC eCourts divorce saves | `nc_ecourts_divorce.py`, 176 rows, last seen 2026-07-22. Pure duplication. And the open Judgment JSON is about to make it statewide. |
| SC PublicIndex lis pendens | Automated, 372 rows, and the best-resolving court source on the board at 61% name-to-parcel. |
| SC PublicIndex state tax lien (432) | Redundant with the SC DOR registry. |
| SC PublicIndex evictions (450) | The ingest keys on the **defendant**, who in an eviction is the tenant, not the owner. Every save adds a name that will never resolve to a parcel the target owns. Resume only after the landlord-side signal ships. |
| Pickens qPublic assessor cards | `assessor_cards/qpublic_render.py` already automates that exact card for Pickens, Spartanburg, Oconee and Union. The pass is gated off by default. Set `ASSESSOR_CARD_ON=1` for a run and cover hundreds of parcels instead of one every three minutes. |
| SC SoS entity lookups | CAPTCHA wall, no parser, and `enrichment_owner_mailing.py` already returns the mailing address for LLC-held property on 16,054 leads. |
| SC LLR roster | No parser exists. It is a contractor-sourcing asset, not a seller-lead source. |
| NC SP-foreclosure Smart Search | The trustee law-firm feeds (~318 rows) beat it on both timing and content, and they carry the address outright. Save SP only for a county where the law-firm feeds show nothing. |
| **SC per-case DETAIL page saves** | **Dead drop.** In theory this is the highest-value manual grab (TMS plus the judgment dollar figure). In practice there is no parser: the ingest matcher only recognizes the search-results table, so a saved detail page parses to zero rows, and nothing in the repo greps a saved SC detail page for "Tax Map". Until someone writes that parser, read the number by eye for the 5 to 10 leads you are actually calling and type it into the CRM. |

### Three defects that make part of the current manual lane worthless

1. **The SC list export writes a fake judgment amount.** All 118 `judgment_amount` values on the SC export source are exactly `2026.0`. One distinct value across 118 rows. `ingest_sc_publicindex_export.py:216` matches a column named "judgment", which on that grid is **"Judgment #"**, and the money parser then reads the case-number year out of it. The list page carries no judgment dollars at all. This poisons the one financial field the manual lane claims to feed. Match on "judgment amount" only, or drop the column.

2. **Four of the nine documented drop files have no reader.** `detail_<case>.html`, `anderson_tax_<parcel>.html`, `pickens_card_<parcel>.html`, `sc_sos_<entity>.html` and `sc_llr_roster.html` are all instructed in `gather_steps.md` and nothing in `scripts/` or `src/` opens any of them.

3. **`manual_playbook_and_limits.md` overstates the resolver.** It says GIS resolves the property from the owner name so you do not need to open each case. Measured: 201 unique matches out of 701 attempts, **28.7%**. Best case is SC lis pendens at 61%, NC lis pendens at 42%, bankruptcy at 7%. And the 2,976-row automated SC sweep was never attempted at all, which is why it sits at 0% address and 0% parcel.

### On the Register-of-Deeds premise

The idea was that NC lis pendens and notices of sale are recorded at the ROD with a legal description and often a parcel ID, making manual court-detail work unnecessary. Partly right, mostly not.

NC lis pendens is a **court** record under G.S. 1-116/1-117, filed with and cross-indexed by the Clerk of Superior Court, not the ROD. What the ROD does carry is the Appointment/Substitution of Trustee (a real early pre-foreclosure signal), sometimes the Notice of Sale, and post-sale Trustee's Deeds. That sweep is already live and returns 57 NC rows against 655 from the judgment feed and ~318 from the law firms.

In SC the ROD route for pre-foreclosure **does not exist**. SC foreclosure is judicial, so the lis pendens and the judgment are Common Pleas records. SC ROD holds only post-sale foreclosure deeds, probate and tax deeds. There is no ROD backdoor around the PublicIndex wall.

ROD indexes carry a legal-description text field, which is not a parcel ID. Measured fill on the NC ROD rows is 23 to 26% parcel and 16 to 19% address, no better than resolving the court name. The one exception is Pickens SC Acclaim at 88% parcel on 150 rows, because that county exposes a clean index.

---

## 4. What literally cannot be obtained free

Blunt version. These are not build items. Stop spending time on them.

| Data | Why free is impossible | Paid floor |
|---|---|---|
| **Exact live mortgage payoff** | 15 U.S.C. §1639g (TILA) and RESPA/Reg X release a payoff statement only to the borrower or a borrower-authorized third party. No vendor sells it, at any price. | Per-deal only, after your seller signs an authorization. $0, but not before you have a signature. |
| **SC recorded sale price on distressed deeds** | SC Code §12-24-70: exempt deeds (foreclosure, deed in lieu, spouse) state **no value**, only an exemption reason. Your targets are exactly the exempt class. NC's deed-stamp path works. SC has no equivalent. | ATTOM (~$500/mo, ~$6k/yr entry tier) is the one vendor that beats this, because it sources from deed recorders directly. |
| **SC $/sqft comps, SC foreclosure sold-price comps** | Same statute. | Same. |
| **Personal email, any owner** | Not in any public record. Verified empirically: the entire 29,946-lead board contains 4 email strings, three of them a notice vendor's own address and one a foreclosure attorney's. NC SoS entity records have no email field. Permit open-data layers redact applicant email. Professional-license lookups publish a business address, not an email. | DataZapp ~$0.02 to $0.03 per match, $125 minimum (~4,000 records). BatchData $0.07 to $0.18. Email match rates run far below phone. |
| **Individual owner mobile phone** | Not published as a dataset anywhere. Paid brokers assemble it from proprietary sources. The public dataset does not exist. | Tracerfy ~$0.02/record. DataZapp $0.02 to $0.03. BatchData $0.07 to $0.18 (~$0.02 at volume). REISkip $0.15 to $0.22 pay-per-hit at a claimed 85 to 90% hit rate. **Full-board sweep of 30k ≈ $600 to $900. Monthly HOT/WARM delta of 2,000 to 3,000 ≈ $60 to $450/mo.** TLOxp and idiCORE are credentialing-walled and you do not qualify. |
| **SC voter phone** | The field is not in the file. This is an absent column, not a paywall. And SC Code §30-2-50 restricts commercial use regardless. | Nothing to buy. |
| **NC power-of-sale debt figure in the Notice of Sale** | NCGS requires only sale terms, deposit and upset-bid procedure. 0 of 24 real notices contained any dollar figure. The number exists only in the clerk's paper SP file. | FOIA (free) or a title O&E at $85 to $95. |
| **SC magistrate eviction bulk roster** | PublicIndex exposes only circuit-court roster codes. There is no magistrate roster type. Those courts are county-operated and in person. | FOIA the Chief Magistrate, or LSC data-sharing (`civilcourtdata@lsc.gov`). |
| **Address for unimproved/vacant parcels** | The county never assigned a situs. `0 NO ADDRESS ASSIGNED`, `GRAY FOX ROAD S2-L45`. Roughly 15% of parcels in these counties. | **Not buyable.** No vendor invents an address that does not exist. |
| **Structured investor buy-box feed** | Does not exist free or paid. Land buyers name counties as SEO text and take deals by relationship. | Curated static registry is the only answer, and it is already built. |
| **Interior property condition** | No vendor sells it without a human visit. Exterior imagery is the ceiling. | A person, in a car. |
| **Comps for ultra-rural or unique parcels** | Fewer than three nearby arms-length sales. RentCast, ATTOM and HouseCanary all thin out identically. | Nothing fixes a data-density wall. |
| **MLS expired/withdrawn, short-sale listings, closed-sale price** | Agent and partner only, never published publicly. | Licensed-agent MLS feed (Canopy / MLS Grid + Upstate SC board). Requires a license. |
| **Six SC foreclosure firms' sale lists** (Crawford & von Keller, Scott & Corley, Grimsley, Nodell Glass & Haskell, Goddard & Peterson, Ward & Smith) | They publish no sale list at all. | County MIE rosters, already automated. |
| **SBA REO, US Marshals first-party real-property feed, HUD multifamily in-footprint** | No portal exists (SBA). USMS delegates to contract auctioneers. HUD's national multifamily list currently holds about 2 properties, neither in NC/SC. | Nothing worth buying. |

### Two legal caveats you should read before scaling mail

**SC Code §30-2-50 (Family Privacy Protection Act, extended to local governments in 2017).** It is a misdemeanor to knowingly obtain or use personal information from a state agency, local government or political subdivision for "commercial solicitation." Personal information expressly includes **name and home address**. Commercial solicitation is defined as contact by telephone, mail or email for the purpose of selling or marketing a consumer product or service. Penalty up to $500 and/or one year.

Whether buy-side mail ("I will buy your house") is "selling or marketing a consumer product or service" is genuinely ambiguous, and I am not going to pretend otherwise. But the SC half of your footprint is direct-mailing names and home addresses pulled from county government, which is the exact fact pattern the statute describes. The risk attaches to the **use**, not the acquisition method, so it applies to the data you already hold. Get an opinion from SC counsel before scaling SC mail volume.

**NC G.S. 132-10.** County GIS databases are public records at reasonable cost, but as a condition of furnishing an electronic copy a county **may require a written agreement that the copy not be resold or used for trade or commercial purposes**. Carve-outs exist for news media, real estate trade associations, MLSs, and licensed professionals using the data in the course of their profession. A REI direct-mail operation is not obviously any of those unless the principal holds an NC real estate license. This is why you should **not** FOIA the bulk roll: the open ArcGIS REST endpoints impose no such agreement, and paginating a public FeatureServer is already a bulk download.

Which is the answer to the bulk-roll question: **17 of your 18 counties already publish an open, paginated ArcGIS parcel/CAMA layer. There is nothing to request.** The one genuinely net-new request is Cherokee SC (~31k parcels, qPublic only, no REST endpoint). One email, not eighteen. Doing all eighteen would cost $0 to ~$1,500 in fees, 20 to 40 hours of drafting and schema-normalizing, over 4 to 10 weeks, in exchange for a stale snapshot of what a nightly query already returns, encumbered by a no-commercial-use agreement.

And the thing bulk rolls would not have fixed: **zero of the 18 counties expose tax delinquency in GIS.** Grepped Buncombe, Henderson and Gaston field lists for delinquent, owed, unpaid, due, balance, arrears. All none. Delinquency lives in separate treasurer systems, which is exactly where the per-county tax work already points. Polk NC does carry `TOTAL_TAX_OWED` on 98.5% of parcels, which means it is the **annual levy, not a delinquent balance**. Do not read it as distress.

---

## 5. The join chain to "100%", field by field

How a bare name or a bare parcel becomes a mailable lead, and where each hop stops.

### The chain

**Name + county → parcel.** Owner-name search against 5 pinned SC county ArcGIS layers and 18 NC county layers, plus NC OneMap statewide `ownname` search. Strict matcher with normalization. Defendant promoted to owner on match.

**Parcel → everything.** Parcel to street/city/zip/lat-lng/specs. Parcel or lat-lng to situs street. Point-in-polygon or parcel to value/owner/sqft/year/acreage. Parcel or address to owner plus **mailing address** plus absentee/out-of-state flag. Parcel to sqft and sale history via the qPublic assessor card. TMS to tax balance owed via qPayBill. Parcel centroid to approximate street via Nominatim at 1 request/second.

**Address → parcel.** Address to lat-lng through a four-tier cascade (Census, Nominatim, city centroid, county-seat centroid), then lat-lng to parcel by point-in-polygon.

**Contact.** Name plus address to phone via the NC voter file. Phone to line type via LERG. Entity owner to officers plus address via NC SoS. Notice and deed PDFs to owner/address/debt via OCR.

**Value → equity.** GIS value to ARV, ARV minus payoff minus senior liens. Payoff comes from a recorded deed of trust, an amount-owed field, the judgment or opening bid, or a last-sale amortization.

### Measured fill and realistic free ceiling

| Field | Filled now | Free ceiling | What sets the ceiling |
|---|---|---|---|
| Street address | **57.15%** (17,113) | ~82 to 85% | Two free lifts available (below). Residual is parcels where the county never assigned a situs. |
| Parcel ID | **77.89%** (23,326) | ~90% NC, stalled in SC | NC OneMap is live and fast. SC lost its statewide fallback when SCDOT went token-gated. Greenville, Anderson, Cherokee, Charleston, Georgetown, Greenwood and Horry now have no free statewide parcel route. |
| Owner name | **71.39%** | ~85% | Same GIS coverage bound. |
| Any name (owner or defendant) | 93.86% | 95%+ | Effectively solved. |
| **Owner mailing address** | **36.58% usable** (10,954) | **~72%** | 16,054 leads carry a mailing record (53.6%), but only 10,954 hold a usable address string. Plan on the lower number. 21,721 leads sit in a wired county **with** a parcel or address, so 10,767 are reachable with existing code and existing endpoints. This is throughput, not capability. |
| Any value | **61.53%** | ~85% | Same GIS bound. NC OneMap `parval` backfill lands close to 100% on the NC parcel-only leads. |
| ARV | 56.65% | tracks value | |
| **Equity** | **11.67%** (3,494), of which 3,411 are low confidence, 76 medium, 7 high | **~50 to 60%, all soft** | Of 16,962 leads with an ARV, **14,445 (85.2%) have no payoff input at all.** The equity module is not broken, it correctly refuses to emit without a payoff. The missing ingredient is current mortgage principal. |
| **Phone** | **0.84%** (251) | **~7 to 8% of board** | One free source exists: the NC voter file (`full_phone_number`, ~69% populated, 13 county files cached). NC only. SC's list is paid, purpose-restricted, and has no phone column, so 13,973 SC leads (46.7%) have **zero** free phone route. Matching needs name and street to agree, so only owner-occupants match. Absentee owners (20.5% of the board) never will. Addressable pool is 6,320 NC leads, 4,421 owner-occupant, honest ceiling ~2,000 to 2,400 phones. Every number needs a DNC scrub. |
| **Email** | **0.00%** | **0%** | See section 4. Not a build. |
| Tax owed | 26.7% (7,982) | ~45% | Five SC counties wired via qPayBill. Anderson and Pickens have no automated balance path. NC delinquency is not in any GIS layer. |
| Distress detail | 99.99% | solved | |
| Address + parcel + owner, all three | 38.14% | ~70% | |

Conditional on having a street address (n = 17,113): parcel 93.6%, owner 67.9%, mailing 41.0%, value 71.5%, equity 16.4%, phone 1.4%.

### The cohorts that define the breaks

- **7,309** leads have a parcel but no address (McDowell 2,247, Hyde 1,390, Lincoln 1,361, Spartanburg 730, Buncombe 516, Georgetown 262).
- **5,496** have an address but no owner (Spartanburg 2,921, Buncombe 1,119).
- **5,149** have a name and neither address nor parcel. This is the true name-resolver pool, and **only 701 of them have ever been attempted.** The per-run wall-clock budget is the binding constraint. Running the backlog at the measured 28.7% rate yields roughly **+1,270 resolved parcels**.
- **72** leads are entirely unjoinable.

### Name → parcel: the number you most need to accept

Three independent measurements agree: engine production 28.7% unique match (n=701), probe A 20.0% (n=60), probe B 29.3% (n=41). Ambiguity is real and unfixable free: `HYDER, BOYD L` in Henderson returns **34 parcels**, `Burrell, William` in Transylvania returns 17, one Buncombe name returns 3 on three different streets. There is no free discriminator that picks the right one, and committing a guess mails the wrong person.

The bigger half of the miss is not a data failure. Roughly **50 to 55% of court defendants simply do not own real property in that county.** Renters, out-of-county parties, deceased, or the property already transferred. Chasing 100% here is semantically wrong, not just technically hard. Honest ceiling: ~25 to 30% automatic, ~45% with human disambiguation.

### Three free lifts that move the most, in order

1. **Promote the situs string you already have.** 3,414 address-less parcel leads carry a real situs inside `raw.owner_mailing.situs` that was never written to `street_address`. 2,269 are house-number grade (needs a leading-zero strip: `000489 HARMONY GROVE RD`), 1,140 are street-name only, 5 are placeholders. Zero HTTP requests. **+2,269 addresses, +7.6 points.** This is a write gap between two enrichers, not a data gap.

2. **Run owner-mailing to completion in the 16 wired counties.** 10,767 reachable leads unfilled. Mailing goes from 36.6% to roughly 70%. Existing code, existing endpoints, pure throughput. This is the mail spine.

3. **Add NC OneMap `parno` → `siteadd` / `ownname` / `mailadd` / `parval` as a first-class parcel-side enricher.** Probed 12 real board parcels across Buncombe, Cleveland, McDowell, Brunswick and Transylvania: 12/12 returned a record, 8/12 had a non-empty situs, 12/12 returned owner, mailing and value. Applied to the 6,179 NC parcel-no-address leads that is roughly **+4,100 addresses**. OneMap is currently used only for point-in-polygon and bankruptcy owner search, never for a straight parcel-ID join. It holds 5,938,639 parcels statewide, free, no auth, refreshed weekly.

### One correction to file

`docs/free_skip_tracing_options.md` line 6 says mailing coverage is "89.9% of board." It is **36.58%** usable, 41.0% among address-bearing leads. Any plan built on 89.9% is built on a bad input.

### One infrastructure bug worth more than eighteen FOIA requests

**Spartanburg is wired to the wrong ArcGIS layer.** The current endpoint returns **29,402** records and belongs to the **City** of Spartanburg's server. The county-wide CAMA layer returns **167,131** and carries `OwnerName`, `TaxpayerNa`, full street address, `PropertyLo`, `SaleDate`, `SaleAmount`, `YearBuilt`, `LivingArea`, `BedRooms`, `FullBaths`, `LandUse`, `CurrentAppraisal`, `Assessment`. That is 5.7x the parcels plus a complete CAMA schema on your largest SC county, from a one-line URL change.

Related: the code comment saying "Anderson SC and Cherokee SC: no ArcGIS owner/mailing layer" is wrong for Anderson. Anderson's QueryMap layer serves **120,187** parcels with owner, physical address, market value, sale price, sale year and improvement flag. It carries situs but **no owner mailing address**, so it fixes valuation and owner-name coverage, not absentee detection.

---

## 6. The holy grail

### Build the persistent event ledger

**What it is.** An append-only, per-run event log keyed on the existing dedupe key, recording for every lead on every run: seen or not seen, tax owed, equity, distress tier, sale date, auction status, and the source set. Stored beside the board, never overwritten. It exposes four derived fields: `first_seen`, `days_since_first_seen`, `balance_trend_quarters`, `signal_onset_date`.

**Why it is the one that matters.** It is the only candidate on the list that produces an asset a competitor cannot buy.

The competitor benchmark is PropertyRadar at $99 to $119/month solo. It covers all 46 SC counties and your entire NC footprint, with foreclosure history back to 2004 to 2017 depending on county, document images in Buncombe/Henderson/Gaston/Lincoln/McDowell/Transylvania and all seven SC counties, property tax status, recorder data, divorce for several NC counties, and monitoring lists with change alerts. Anything on that list is parity, not edge.

What nobody sells is **queryable history**. PropertyRadar sells the present tense plus a forward-looking alert. It cannot retroactively manufacture a past. And two things make your archive specifically un-buyable:

- **Your upstream sources overwrite themselves.** NC G.S. 105-369 advertised delinquent rolls, SC forfeited-land-commission lists, county tax-sale PDFs and MIE rosters are published and then replaced. Counties do not archive them. A three-year Buncombe/Lincoln/McDowell delinquent-roll archive cannot be purchased from anyone at any price.
- **Half your sources are outside every vendor's universe**: obituaries, funeral RSS, jail bookings, SCDC, Helene ATC-45 placards, the Buncombe senior-exemption roll (3,505 leads), FLC lists, bankruptcy 363 sales, Spartanburg condemned-properties GIS. Nobody has their present state, let alone their history.

**What you have today: almost none of it.** The new-listings diff compares against exactly one prior run. The board merge is fresh-wins, so last quarter's tax balance is destroyed on write. Only 15 commits touch the board file since 2026-04-28. **4.0% of leads (1,209) carry any first-seen date.**

**What it unlocks.** Balance-growth trajectory (three consecutive rising quarters is a confirmed non-payer, not a clerical error). Signal onset date, which is your mail-saturation proxy. Appearance and disappearance events (a lead vanishing means someone else got it, stop mailing). Equity drift. And the only calibration set you will ever have for which signals actually predicted a closed deal.

**Cost: $0 in dollars. 2 to 4 days of build.** Structurally it is a small change, not a new subsystem. The merge function and the new-listings diff already implement a one-run version of exactly this, and the dedupe key is stable.

**The honest downside: it returns nothing in month one and little in month three.** That delay is the moat. Every day you run, the gap between you and anyone starting later widens by one day, permanently.

### Runner-up: un-gate deed-of-trust OCR beyond Spartanburg

**Cost: $0 in dollars. 1 to 2 weeks of build**, because it is render-session-bound at roughly 25 to 40 seconds per owner and each recorder vendor (Logan, Acclaim, Cott, Aumentum, CCS, Kofile) is a separate portal.

Equity is filled on 11.7% of the board and recorded deed-of-trust principal on approximately 0%. The OCR module is proven but hardcoded to Spartanburg, capped at 25 per run, and gated to HOT/WARM. Spartanburg's Logan deed-of-trust images are confirmed free (application/pdf, no cart, no login).

Be clear-eyed about what this is: **it replicates a $99/month product.** PropertyRadar already sells document images and derived loan data across most of your footprint. It is excellent cost-avoidance and it unblocks your equity engine, but a competitor with a credit card is not behind you on it. It also caps around 50 to 60%, because Kofile counties and per-doc-fee recorders paywall the page, and it is fragile: Burke, Cleveland, Rutherford, Polk and Mitchell show no document-image coverage in the vendor table either, which mirrors the free gaps.

Build the ledger first. If you need deals this quarter rather than next year, build this second, because it improves the ranking of the leads you can mail **today**.

### What I am not picking, and why

**Speed.** Real, already banked, and over-hyped. You pull from county and court hosts directly plus nine trustee-firm feeds. PropStream and BatchLeads both resell First American bulk with county lag from same-day to 60-plus days, and small NC/SC counties are the worst of that tail. You are days-to-weeks ahead on NC foreclosure. But the "5-minute rule" statistics come from inbound web-lead research and do not transfer to cold outbound mail. NC's own clock argues against urgency: 45-day pre-foreclosure notice under G.S. 45-102, notice of hearing 10 days out, notice of sale posted 20 days, then a 10-day upset-bid period. That is a months-long decision window. Aged distressed leads reportedly close at a **higher** rate because motivation has matured. Do not spend build budget here.

**Multi-signal stacking.** Already built, and the honest finding is that it is thin. Only **925 of 29,946 leads (3.1%)** hit two or more distinct distress categories, 16 hit three or more, and only 173 are HOT. 22,914 leads carry exactly one signal. More scoring sophistication on that distribution produces nothing. What limits the stack is source breadth per parcel, not scoring logic. Treat "3+ signals" as a marketing line, not a pipeline.

**Undiscovered free datasets.** I found none. Utility shutoffs are statutorily dead. The Spartanburg daybook is the PublicIndex wall wearing a different hostname. SC lis pendens at the ROD does not exist. Expired listings are MLS-only. USPS vacancy is HUD-gated to governmental and nonprofit licensees, and the land-use vacancy proxy already in place is the correct substitute. Mortgage-satisfaction gaps, out-of-state owner concentration, HOA liens and lien priority are all already built. That is a finding, not a failure: source discovery is essentially complete. The remaining leverage is in what you do with the data over time.

**Contactability, the real ceiling.** 0.84% phone coverage means 29,695 of 30,000 leads cannot be called. This dominates every other constraint on the board. It is also not a buildable free project: SC has no free phone source at all and a statute restricting commercial use of local-government personal information, and NC's free file only matches owner-occupants. **Mail is the channel.** I am flagging this as the true ceiling and explicitly not recommending a free build against it, because the honest answer is that free phone at scale is a wall.

---

## 7. Do this next

Ordered. Items 1 through 5 are free and cost days, not weeks.

1. **Promote `raw.owner_mailing.situs` into `street_address`.** Zero HTTP. +2,269 addresses, +7.6 points. Half a day.
2. **Add `"FAM - Divorce"` to the NC Judgment JSON cause filter.** One config line. Divorce goes from 176 rows to statewide, and it routes around the WAF entirely.
3. **Repoint Spartanburg at the county-wide CAMA layer.** One URL. 29,402 parcels becomes 167,131 with full CAMA including sale amount, living area, beds and baths. Also correct the Anderson comment and wire its 120,187-parcel layer.
4. **Build the persistent event ledger.** 2 to 4 days. Every day of delay is a day of history permanently lost.
5. **Run owner-mailing to completion in the 16 wired counties, and raise the name-resolver backlog cap.** Mailing 36.6% to ~70% (10,767 leads). Resolver backlog of ~4,450 unattempted leads yields roughly +1,270 parcels at the measured rate.
6. **Send the FOIA batch.** NC clerks, SC clerks copying the MIE, SC chief magistrates. 15 minutes, then it arrives without you. This is the only free route to judgment dollars at scale.
7. **Build Greenville SC probate.** 3.19 MB, 1,423 rows, zero WAF, plain GET. The Upstate hub currently contributes 0 leads. Small build, largest single unbuilt free win.
8. **Fix the fake judgment amount** in the SC export ingest (match "judgment amount" only) and **delete the four dead-drop instructions** from `gather_steps.md` so you stop producing files nothing reads.
9. **Un-gate deed-of-trust OCR** beyond Spartanburg. 1 to 2 weeks. This is what lifts equity off 11.7%.
10. **Get an SC attorney's read on §30-2-50** before scaling SC mail volume. This is a legal exposure question, not a data question, and it applies to data you already hold.
11. **Stand up a quarterly wall re-probe job.** Eleven of eighteen walls were stale this week. Four were plain domain migrations to `.gov`. Two were fingerprint artifacts repeating a mistake already made once with GovDeals. A one-hour recurring job would have caught all of them.

**Not on the list, deliberately:** FOIA the bulk assessor rolls (you already have 17 of 18 free, and NC's G.S. 132-10 agreement would encumber what the open endpoints do not). Chase Kofile/Oconee (robots.txt). Chase the utility shutoff list (statutorily exempt). Chase expired listings (MLS-only). Buy PropStream at $99 to $699/month before the free throughput items above are actually running to completion.

---

### Source files referenced

`/Users/cashhigh/foreclosure-scraper/docs/blocked_sources_forensic.md`, `source_unblock_plan.md`, `gap_ledger.md`, `path_to_100.md`, `coverage_gap_analysis.md`, `manual_playbook_and_limits.md`, `gather_steps.md`, `foia_court_records.md`, `free_skip_tracing_options.md`, `listings.json`
`/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/ingest_sc_publicindex_export.py` (line 216, judgment-column defect), `enrichment_owner_mailing.py`, `enrichment_situs_address.py`, `enrichment_resolve_name_to_property.py`, `enrichment_equity.py`, `enrichment_dot_ocr.py`, `enrichment_assessor_card.py`, `enrichment_qpaybill_tax.py`, `distress_score.py`, `models.py`
