# Source Research — NC + SC Motivated-Seller Public Records (2026-07)

Merged from five research briefs into one cited reference. Scope: NC footprint (Buncombe, Gaston, Henderson, Rutherford, Cleveland, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell) + SC footprint (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens).

**Coverage legend** (mapped against our ~110-scraper stack): **HAVE** = already scraped/wired; **PARTIAL** = partial coverage, a county or field or lane is missing; **GAP** = genuinely not in the pipeline.

**Access legend:** **OPEN** = anonymous JSON/CSV/REST, no barrier; **CLICK-THROUGH** = free but a disclaimer/ToS accept-button gates the UI, then anonymous; **CAPTCHA** = periodic bot challenge; **ToS-ANTISCRAPE** = terms expressly forbid automated collection; **LOGIN** = account required; **PAID** = subscription or per-doc fee is the only route to the useful data.

Two structural realities frame everything: **NC is an OPEN state** (eCourts/Odyssey live in all 100 counties as of 2025-10-13 ([nccourts.gov/ecourts](https://www.nccourts.gov/ecourts)); NC Judgment Search is a login-free statutory index; NC OneMap gives statewide parcels). **SC is a GATED state** (the SC Public Index expressly bans scrapers and enforces it technically + via bar discipline ([sccourts case-records-search](https://www.sccourts.org/case-records-search/), [ACLU-SC](https://www.aclusc.org/press-releases/march-30-2022-data-scraping/))). SC distress data therefore leans on county tax/assessor portals, MIE rosters, press-association notices, and manual court exports.

---

## 1. Distress-signal taxonomy

Ranked by motivation strength. "Do we have it?" maps to the existing stack.

| Signal | What it means / motivation strength | Public source | Have it? |
|---|---|---|---|
| **Pre-foreclosure / NOD / lis pendens** | Lender started the clock, owner still controls sale; hard deadline a cash offer solves. **Extremely high.** NC records a notice-of-hearing special proceeding + lis pendens ([LegalFix NC](https://www.legalfix.com/topics/real-property/lis-pendens/nc)); SC is judicial (Master-in-Equity). | NC Judgment Search JSON (lis pendens) + eCourts SP; NC/SC ROD lis pendens; SC Public Index (manual) | **HAVE** — NC eCourts lis pendens (stealth + Judgment JSON), SC Public Index lis pendens (stealth/manual), + law-firm substitute-trustee feeds |
| **Substitute-trustee foreclosure sale** | Power-of-sale sale scheduled (NC Ch.45 Art.2 [§45-21.16](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.16.pdf)); SC MIE 1st-Monday sale. **Very high.** | Law-firm trustee feeds; MIE rosters; newspaper legals; ncnotices.com / scpublicnotices.com | **HAVE** — Brock&Scott, Bell Carrington, Aldridge Pite, Finkel, Hutchens, Korn, McMichael Taylor Gray, Rogers Townsend, Shapiro&Ingle; MIE Anderson/Pickens/Charleston; Column + ncnotices |
| **Tax-sale / upset-bid foreclosure (imminent)** | Delinquent-tax foreclosure heading to auction. NC 10-day upset-bid ([TaxSaleAcademy NC](https://taxsaleacademy.com/north-carolina-tax-sales-tax-deeds/)); SC annual lien sale + 12-mo redemption ([SC Title 12 Ch.51](https://www.scstatehouse.gov/code/t12c051.php)). **Very high.** | County tax-collector foreclosure lists (PDF/HTML); Terry Howe FLC | **HAVE** — SC qPayBill (Spartanburg/Oconee/Laurens/Union) + Oconee CSV + forfeited-land; NC PTS Cloud + county PDF rolls |
| **Divorce (at petition)** | Forced marital-home liquidation; catch at filing not decree. **High.** | NC eCourts (open) / Judgment JSON; SC Public Index (manual) | **HAVE (NC) / PARTIAL (SC)** — NC eCourts judgment-search JSON revived divorce; SC = manual gather only |
| **Probate / estate / inherited** | Owner died, heirs can't/won't keep it; file names executor + heirs. **High.** | NC eCourts "Estate" case type (CAPTCHA/manual); SC [southcarolinaprobate.net](https://www.southcarolinaprobate.net/search/) | **HAVE** — heir/estate scraper (15 counties); NC estates = manual/CAPTCHA wall |
| **Pre-probate (obituary → heirs)** | Earliest estate signal, low competition; match obit name → parcel owner. **High.** | Funeral-home RSS, [Legacy.com](https://www.legacy.com/obituaries/search), Gannett/paper obits | **HAVE** — Gannett Upstate + funeral-home RSS obituary lane |
| **Tax delinquency (early, pre-suit)** | Behind on taxes, no suit yet; highest-volume earliest financial flag. **Moderate-high.** | County tax portals (qPayBill unpaid; qPublic NC) | **PARTIAL** — parcels/balances captured where portal joins by TMS; **taxes-owed dollar amount is a known gap** in most counties |
| **Bankruptcy (Ch.7/13)** | Trustee sale (7) or plan (13); watch Motion to Sell / Notice of Abandonment ([BatchData](https://batchdata.io/uncategorized/how-to-find-out-if-someone-filed-bankruptcy)). **High, chapter-nuanced.** | PACER (PAID) / CourtListener-RECAP (free archive) | **HAVE** — CourtListener bankruptcy/civil/adversary |
| **Federal / state tax + judgment liens** | Recorded encumbrance clouds title; liens stack into strong motivation. NFTL filed at county ROD ([IRS IRM 5.17.2](https://www.irs.gov/irm/part5/irm_05-017-002)). **Moderate-high.** | County ROD; NC Judgment Search (docketed); SC DOR Lien Registry | **HAVE** — SC DOR state-tax-lien registry (~8k) + NC eCourts judgment + ROD; **lien $ amount only in scanned PDF (OCR lane)** |
| **Mechanic's & HOA liens** | Unpaid contractor (NC 120-day file window [FS NC](https://www.fsresidential.com/north-carolina/news-events/articles/a-guide-to-nc-liens/)) or HOA dues; cash-flow trouble / stalled rehab. **Moderate.** | County ROD (+ Clerk for mechanic's claim) | **PARTIAL** — HOA-Charleston parsed; broader in-footprint HOA/mechanic-lien mining blocked on ROD rebuild |
| **Code-enforcement / condemnation** | Active nuisance/unfit-for-habitation case (NC Ch.160D Art.12 [PDF](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/ByArticle/Chapter_160D/Article_12.pdf)). **Moderate-high, condition-driven.** | Accela/open-data portals; GIS condemned layers; FOIA-by-address | **PARTIAL** — Asheville lapsed-STR + code-enf built; most small towns FOIA-by-address; Spartanburg `Condemned_Properties` GIS layer unwired = GAP |
| **Demolition / unsafe-building orders** | Board ordered repair/close/demolish; teardown assessment billed to owner. **High when present, rare.** | City council agendas + published legal notices | **GAP** — no central list; per-municipality agenda/notice mining not wired |
| **Vacant / zombie / abandoned** | Unoccupied + neglected; under-chased. NC zombie foreclosures +67% QoQ, SC +34% ([ATTOM Q1-2026](https://www.attomdata.com/news/market-trends/foreclosures/q1-2026-vacancy-and-zombie-foreclosure-report/), [MeckTimes](https://mecktimes.com/news/2026/06/11/zombie-foreclosures-rise-north-carolina-67-percent/)). **Moderate alone, strong stacked.** | USPS 90-day flag (PAID/HUD-gated); assessor absentee + no-homestead + land-use=vacant proxies | **PARTIAL** — Spartanburg vacant built; USPS true-vacancy paywalled; free proxies reconstruct most of it |
| **Fire / hoarder / environmental damage** | Deep condition distress, wants out as-is. **High when found, hard to source.** | Fire/NFIRS reports (FOIA); MLS free-text; drive-for-dollars | **GAP** — no open structured feed; condition-flag enrichment only |
| **Absentee / out-of-state / tired landlord** | Owner mailing ≠ situs; multiplies every other signal. **Moderate alone, powerful filter.** | Assessor/parcel (NC OneMap `mailadd`; SC cards) | **HAVE** — owner-mailing/absentee flag lane |
| **High-equity / long-tenure / free-and-clear** | Paid-down, held long; retirement cash-out, de-risked spread. **Moderate, high value.** | Computed: last-sale + open DoT vs ARV; tenure = years since sale | **HAVE** — equity engine (ARV − payoff − liens) |
| **Expired / withdrawn / cancelled listing** | Seller already tried and failed; pre-established motivation. **High intent.** | MLS / REDX / Vulcan7 (PAID) | **GAP** — not a public record; MLS/vendor-only; **no compliant free path** (conflicts with free+public mandate) |
| **Eviction / summary-ejectment** | Landlord filing = candidate tired-landlord. NC "summary ejectment" magistrate ([NC Ch.42 Art.3](https://www.ncleg.net/EnactedLegislation/Statutes/PDF/ByArticle/Chapter_42/Article_3.pdf)). **Moderate, seller-side.** | NC eCourts small-claims (open); SC Public Index magistrate (ToS wall) | **GAP** — NC eviction lane not wired; SC magistrate evictions = confirmed wall (no free bulk feed) |
| **Senior/disability relief + PUV rollback** | Elderly/low-income exemption flags equity-rich downsizers; ag PUV disqualification rolls back current +3 prior years deferred tax ([G.S. 105-277.1F](https://law.justia.com/codes/north-carolina/chapter-105/article-12/section-105-277-1f/)). **Moderate, best as filter.** | County assessor (qPublic NC / county tax) | **PARTIAL** — Buncombe senior/disabled + Henderson use-value rollback built; senior-exemption flags build-ready elsewhere |
| **Jail bookings / incarceration** | Incarcerated owner = distressed-sale candidate (property-keyed via name→parcel). **Moderate.** | County jail rosters (P2C, Zuercher, Citizen Connect); SCDC | **HAVE** — Buncombe/Greenville/Gaston/Cherokee/Cleveland/Anderson bookings + SCDC |
| **Driving-for-dollars visual proxies** | Overgrowth, boarding, tarped roofs; validates a data-signal lead. **Moderate, high-confirmation.** | Google Street View (free); CV tooling (PAID) | **GAP** — manual/virtual only; not systematized |

**Meta-play:** every source agrees highest conversion = the *intersection* of signals, not any single list ([partnerwithez](https://partnerwithez.com/blog/distressed-property-sellers/), [PropertyRadar](https://www.propertyradar.com/blog/find-motivated-sellers)). Our property-keyed backbone (name → property → equity → contact) is exactly what enables stacking; property-keyed signals (assessor/GIS, tax-delinquent, code, vacant) stack cleaner than name-indexed ones (probate, divorce, bankruptcy, liens) which need a name→parcel join.

---

## 2. NC access + gating map

| Dataset | Where it lives (portal / vendor) | Access | Our status |
|---|---|---|---|
| eCourts Judgment Search (lis pendens, divorce, civil judgments, docketed state-tax liens) | [portal-nc.tylertech.cloud/app/NCJudgmentSearch/](https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/) — NCGS 7A-109(b)(6) | **OPEN JSON** (cookies req; raw HTML returns a browser-stub, hit JSON directly). Note: lis pendens/claims-of-lien surface as "M" files, status "Default Conversion," category "Civil Judgement" ([NCBar enhancements](https://www.ncbar.org/wp-content/uploads/2023/06/Odyssey-Portal-Judgment-Searching-Enhancements.pdf)) | **HAVE** — compliant NC court lane; divorce revived off JSON |
| eCourts Portal "Smart Search" (foreclosure SP, estates, evictions, all cases + images) | [portal-nc.tylertech.cloud/Portal/](https://portal-nc.tylertech.cloud/Portal/) | **CLICK-THROUGH + CAPTCHA every ~10 min** (Tyler platform-wide [Portal FAQs](https://www.nccourts.gov/assets/documents/publications/Portal-FAQs-20231027.pdf)); 200-result cap; 1-doc-at-a-time; some docs admin-restricted | **HAVE (manual) / PARTIAL** — estates + foreclosure-SP detail = WAF/CAPTCHA view-only; not bulk |
| Bankruptcy (W.D.N.C. Asheville/Shelby) | PACER; [CourtListener-RECAP](https://www.courtlistener.com/recap/) | PACER = **PAID** $0.10/pg; RECAP archive = **OPEN** free REST API | **HAVE** — CourtListener |
| ROD — Cott / cotthosting.com (Rutherford, Polk) | [cotthosting.com/ncrutherfordexternal/…](https://cotthosting.com/ncrutherfordexternal/LandRecords/protected/v4/SrchName.aspx) | **CLICK-THROUGH guest** index free; **LOGIN** (signed application, 30-day expiry) for full; **PAID cart** for images | **HAVE (Cott Union pattern)** — index lane; images paid |
| ROD — Courthouse Computer Systems / CCS (Gaston, Cleveland, Lincoln, Burke) | [gastonnc.courthousecomputersystems.com](https://gastonnc.courthousecomputersystems.com/), us5…/clevelandnc, courtcompsys.com/burkeNC | **OPEN index** free; unofficial copies free; certified fee'd | **PARTIAL** — CCS vendor not yet templated (Gaston migrated to CCS ~2026-05-28) |
| ROD — Buncombe Sentry | [registerofdeeds.buncombenc.gov](https://registerofdeeds.buncombenc.gov/External/Sentry/Home.aspx) | **OPEN** anon name search; **LOGIN** account for images | **HAVE** — Aumentum Buncombe/Gaston ROD |
| ROD — self-branded (Henderson, McDowell "The Lookup", Transylvania FREE images, Mitchell) | [hendersoncountync.gov/rd](https://www.hendersoncountync.gov/rd), [transylvaniadeeds.com](https://www.transylvaniadeeds.com/) | **OPEN / CLICK-THROUGH** index; images vary (Transylvania free) | **PARTIAL** — self-branded portals not all wired |
| Tax/parcel — PTS Cloud PWA (Henderson, Rutherford, Madison, Burke) | [lrcpwa.ncptscloud.com/Henderson](https://lrcpwa.ncptscloud.com/Henderson/) (land) + [bcpwa.ncptscloud.com/hendersontax](https://bcpwa.ncptscloud.com/hendersontax/) (bills/unpaid) | **OPEN** structured PWA/API | **HAVE** — lrcpwa parcel→address/value/photo + PTS Cloud bcpwa tenants |
| Assessor + sales history | [qpublic.net/nc/ncassessors](https://qpublic.net/nc/ncassessors/) (Schneider) | **CLICK-THROUGH** disclaimer, then OPEN; sales list/comps | **HAVE** — qPublic NC parcels/sales |
| County GIS FeatureServer (Rutherford, Buncombe, Henderson, Gastonia) | county ArcGIS REST; [data.buncombecounty.org](https://data.buncombecounty.org/); [gis-data-hub-gastonianc.hub.arcgis.com](https://gis-data-hub-gastonianc.hub.arcgis.com/) | **OPEN REST** (query JSON) + bulk shapefile/CSV/GeoJSON download | **HAVE** — NC county GIS/parcel ArcGIS + OneMap |
| Statewide parcels | [services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1](https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1) | **OPEN REST** despite `/secure/` path; `maxRecordCount 5000`; fields `ownname/mailadd/mstate/parval/saledate/parusecode` | **HAVE** — NC OneMap 11-county unified fallback |
| Delinquent / tax-foreclosure lists | [buncombenc.gov/622](https://www.buncombenc.gov/622/Tax-Foreclosure-Sales), [gastongov.com/668](https://www.gastongov.com/668/Tax-Foreclosures), [hendersoncountync.gov/tax](https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales) | **OPEN** HTML/PDF (NCGS 105-369 advertising, 105-375 In Rem) | **HAVE** — county .gov PDF rolls + forfeited-land |
| Foreclosure / estate / notice-of-sale | [ncnotices.com](https://www.ncnotices.com/) (NC Press Assoc.) | **OPEN/FREE**, statewide, 12-mo current + archive | **HAVE** — ncnotices.com + Column legal notices |
| Voter file (skip-trace/occupancy) | [dl.ncsbe.gov/data/ncvoter_Statewide.zip](https://s3.amazonaws.com/dl.ncsbe.gov/data/ncvoter_Statewide.zip) | **OPEN** free weekly; name+residential address; DOB/SSN redacted | **HAVE** — NC voter-file phone |
| Secretary of State (LLC-owner → human) | [sosnc.gov/divisions/business_registration](https://www.sosnc.gov/divisions/business_registration) | **OPEN** web search but scripted search **prohibited**; bulk = PAID | **HAVE** — NC SoS stealth agent+officers enricher |
| Unclaimed property | NCCash | **OPEN** web search, no bulk API | **HAVE** — NC/SC unclaimed property |

---

## 3. SC access + gating map

| Dataset | Where it lives (portal / vendor) | Access | Our status |
|---|---|---|---|
| SC Judicial Public Index (Common Pleas foreclosure/lis pendens/partition; magistrate evictions) | [publicindex.sccourts.org/<county>/PublicIndex/](https://publicindex.sccourts.org/pickens/publicindex/) — back end Journal Technologies | **ToS-ANTISCRAPE + CLICK-THROUGH** — verbatim ban on "a site data scraper or any similar software … automated, repetitive querying" ([disclaimer](https://publicindex.sccourts.org/Pickens/PublicIndex/disclaimer.aspx), [Data Innovation](https://datainnovation.org/2022/03/south-carolinas-misguided-restrictions-on-scraping-judicial-data/)); technical block + bar discipline; NAACP/ACLU 1A suit pending ([ACLU-SC](https://www.aclusc.org/press-releases/march-30-2022-data-scraping/)). **Home addresses stripped from public display as of 2026-01-01** | **HAVE (manual) / GAP (auto)** — the hard wall; operator-saved-HTML → offline-parser lane |
| Court Roster Search (foreclosure/motion rosters) | redirects into `publicindex.sccourts.org/<county>/courtrosters/` | **Same domain, same ToS wall** — not a loophole | **PARTIAL** — manual only |
| Master-in-Equity foreclosure sale rosters | County MIE pages (Spartanburg [313/Foreclosure-Sale](https://www.spartanburgcounty.gov/313/Foreclosure-Sale)) + newspaper legals | **OPEN** PDF/HTML, 1st-Monday sales | **HAVE** — MIE Anderson/Pickens/Charleston; Spartanburg via legals |
| Bankruptcy (D.S.C. Spartanburg/Greenville/Anderson) | PACER; CourtListener-RECAP | PACER **PAID**; RECAP **OPEN** | **HAVE** — CourtListener |
| ROD — Spartanburg | [search.spartanburgdeeds.com](https://search.spartanburgdeeds.com/) (Harris/Acclaim-family) | **CLICK-THROUGH** disclaimer; index free | **HAVE** — Spartanburg ROD (Logan render, Instrument-Types flow) |
| ROD — Anderson ACPASS | [acpass.andersoncountysc.org](https://acpass.andersoncountysc.org/) (in-house cgi) | **OPEN** — most open in footprint; integrated ROD + tax + court dockets, no login, stable `rpcnamen.cgi`/`real_prop.htm` | **PARTIAL/GAP** — richest open SC lane, not fully wired |
| ROD — Pickens AcclaimWeb | [pickensscrod.us/AcclaimWeb](https://www.pickensscrod.us/AcclaimWeb) (Harris/Acclaim) | **CLICK-THROUGH**; Consideration search LowerBound/UpperBound but **GridResults JSON omits consideration** | **PARTIAL** — AcclaimWeb pattern known |
| ROD — Oconee | Cott eSearch via [oconeesc.com](https://oconeesc.com/departments/register-of-deeds) | **CLICK-THROUGH**; Java viewer; index 1957+, images 2002+ | **HAVE** — Cott pattern (also Union) |
| ROD — Union / Cherokee / Laurens | [search.laurensdeeds.com](https://search.laurensdeeds.com/); Cherokee via [sclandrecords.com](https://www.sclandrecords.com/) | **CLICK-THROUGH** index; images vary | **PARTIAL** — Cott Union have; Laurens/Cherokee not wired |
| Tax collector / delinquent tax sale + FLC | County treasurer PDFs (Spartanburg [640](https://www.spartanburgcounty.org/640/2025-Tax-Sale-Info)); [terryhowe.com](https://terryhowe.com/) FLC auctioneer | **OPEN** — county PDFs + open HTML FLC tables (view free; bidding = registration); Anderson uses PostingPro | **HAVE (tax) / PARTIAL (FLC)** — qPayBill Spartanburg/Oconee/Laurens/Union; Terry Howe FLC HTML not templated |
| Tax balances (taxes-owed $) | qPayBill unpaid search (Spartanburg SOLVED, join by TMS) | **OPEN** but most SC counties' parcel keys mismatch | **PARTIAL** — Spartanburg solved (+408); Anderson ACPASS viable; rest mismatch |
| County GIS / parcel | [maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer](https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer); [propertyviewer.andersoncountysc.org](https://propertyviewer.andersoncountysc.org/) | **OPEN ArcGIS REST** (`/query` JSON) + Spartanburg open-data hub CSV/GeoJSON | **HAVE** — SC county GIS incl Charleston chascogis resolver; Spartanburg CAMA_Parcels reusable |
| Assessor cards + sqft + sale history | [qpublic.net/sc/scassessors](https://qpublic.net/sc/scassessors/body-a.html); Union [qpublic.net/sc/union](https://qpublic.net/sc/union/search.html) | **CLICK-THROUGH** disclaimer, then OPEN | **HAVE (partial)** — Pickens/Oconee CARDs expose heated sqft + full sale-price/book-page history; Union card = sqft only, no sales table |
| SC DOR State Tax Lien Registry | [dor.sc.gov/LienRegistry](https://dor.sc.gov/LienRegistry) → MyDORWAY | **OPEN**, free, no login, but single-lookup, **no bulk export** (cookie/session gate); balance/payoff + county + tax type; name-keyed | **HAVE** — SC DOR state-tax-lien registry (~8k) |
| SC situs / address resolution | SCDOT layer10 (`PROP_ST_NO`/`PROP_ST_NA`); Charleston [chascogis ArcGIS](https://services.arcgis.com/jR9eNCjAkxwH2nLe) | **OPEN REST** | **HAVE** — SCDOT layer + Charleston resolver (net-new) |
| Voter file (skip-trace) | [scvotes.gov/…/sale-of-voter-registration-lists](https://scvotes.gov/resources/sale-of-voter-registration-lists/) | **PAID** ($25–$2,500) + **§30-2-50 bars commercial solicitation to SC residents** — usable for ID/address confirm, not mail campaigns | **GAP** — no SC voter phone (correctly not pursued) |
| Secretary of State | [businessfilings.sc.gov](https://businessfilings.sc.gov/) | **OPEN** web search, no public API, **CAPTCHA-walled** | **GAP** — SC SoS captcha wall (NC SoS have) |
| SC statewide open data | [dor.sc.gov top-delinquent-taxpayers](https://dor.sc.gov/transparency/compliance-searches-license-validation/south-carolinas-top-delinquent-taxpayers); data.sc.gov | **OPEN** but thin — top debtors only; no parcel-level distress | Not worth wiring (residential-thin) |

---

## 4. NEW sources to pursue (genuinely not in coverage), ranked

Each = what it adds, URL/vendor, access, and BUILD (open API/ArcGIS) vs GATHER (walled/manual) vs LICENSED.

1. **Spartanburg `Condemned_Properties` GIS layer — BUILD.** A direct condemned/substandard distress flag, not just parcels. `https://maps.spartanburgcounty.org/server/rest/services/GIS` (validate exact layer id via `/0?f=json`). **OPEN ArcGIS REST.** Net-new distress *signal*, not a coverage dup — our SC GIS use today is parcels/situs, not condemnation. **GAP → high value.**

2. **NC voter file statewide zip — BUILD (skip-trace/occupancy).** `https://s3.amazonaws.com/dl.ncsbe.gov/data/ncvoter_Statewide.zip`, weekly, free, name + residential address. Confirms an owner still lives at situs or finds their new address by name. We have "NC voter-file phone" — confirm whether the *full statewide occupancy join* (not just phone) is wired; if only phone, the address-confirmation lane is a **PARTIAL → BUILD** upgrade.

3. **Anderson ACPASS full ingest — BUILD.** [acpass.andersoncountysc.org](https://acpass.andersoncountysc.org/) integrates ROD + tax + real-property + **court dockets** in one no-login cgi. The single most open SC county — closes Anderson ROD + Anderson taxes-owed + Anderson dockets at once. **PARTIAL → BUILD.**

4. **County tax-sale bidder-list PDFs (seasonal) — BUILD/GATHER.** Oconee [sale-list](https://oconeesc.com/delinquent-tax/sale-list), Spartanburg [640](https://www.spartanburgcounty.org/640/2025-Tax-Sale-Info), Anderson (PostingPro), Pickens, Cherokee. Owner + parcel + **amount-owed** as PDF — a cleaner taxes-owed capture than per-parcel portals (fills the known $ gap). Anderson/several SC counties template once on `postingpro.net`. **PARTIAL → BUILD.**

5. **Terry Howe FLC HTML tables — BUILD.** [terryhowe.com](https://terryhowe.com/) FLC/surplus auctions for Spartanburg, Anderson, Laurens + others; owner-lost, deeply distressed parcels; tables open HTML (Parcel ID + Address), no CAPTCHA to view. **GAP → BUILD.**

6. **NC vacant land-use owners from `parusecode` — BUILD (free vacancy proxy).** NC OneMap `parusecode` + Spartanburg `Assessed_Land_Use` yield vacant-lot owners with zero USPS/third-party data. Reconstructs most of the paywalled USPS vacancy signal. **GAP → BUILD.**

7. **Charlotte-style code-enforcement ArcGIS layers — BUILD where they exist in-footprint.** Model: [data.charlottenc.gov code-enforcement-cases-all](https://data.charlottenc.gov/datasets/charlotte::code-enforcement-cases-all/about) (open FeatureServer, searchable by parcel). Charlotte is out-of-core but the pattern (`site:opendata.arcgis.com {county}` → code-enf layer) is the template to hunt in-footprint. **GAP → BUILD (where published).**

8. **CCS ROD vendor template (Gaston/Cleveland/Lincoln/Burke) — BUILD.** [courthousecomputersystems.com](https://gastonnc.courthousecomputersystems.com/) — open index, 4 footprint counties on one vendor. **PARTIAL → BUILD.**

9. **CourtListener RECAP Search Alerts — BUILD (free federal watch).** [free.law/recap](https://free.law/recap/) — "Google Alerts for federal filings"; federal tax liens, bankruptcy, receiverships not in county records. We ingest CourtListener already; **alerts** are the net-new incremental lane. **PARTIAL → BUILD.**

10. **Federal REO six-pack — BUILD/GATHER.** [HUD HomeStore](https://www.hudhomestore.gov/), [USDA resales](https://www.resales.usda.gov/resales/public/home) (rural = footprint-relevant), [Fannie HomePath](https://www.homepath.fanniemae.com/), [Freddie HomeSteps](https://www.homesteps.com/), [FDIC real-estate](https://www.fdic.gov/asset-sales/real-estate-and-property-sales), [GSA disposal](https://disposal.gsa.gov/s/) + [GSA Auctions API](https://gsa.github.io/auctions_api/) (open XML/JSON). Mostly **HAVE** (federal REO Fannie/Freddie/HUD/GSA/USDA/VA/Treasury) — the **GSA Auctions structured API** and **FDIC "Bargain Properties"** are the incremental adds. **PARTIAL.**

11. **scpublicnotices.com — BUILD (compliant SC foreclosure/estate mirror).** [scpublicnotices.com](https://www.scpublicnotices.com/) (SC Press Assoc.) — free, searchable, statewide; a *compliant* parallel to the scrape-banned SC Public Index for sale/foreclosure/estate notices. **GAP → BUILD (high value, routes around the wall).**

**Confirmed NOT-new / already-covered "new"-looking items:** NC OneMap parcels (HAVE), ncnotices.com (HAVE), NC eCourts Portal (HAVE), obituaries/Legacy.com (HAVE — Gannett + funeral RSS), federal REO core (HAVE), qPublic sales cards (HAVE), SC DOR lien registry (HAVE).

---

## 5. Gating cheat-sheet — by vendor

Know on sight what any new county portal will require.

- **Tyler "Odyssey / Enterprise Justice Portal"** (NC eCourts, most US courts) — **CAPTCHA every ~10 min** for anonymous *and* registered users (platform-wide), + **AWS-WAF** JS-token challenge (`aws-waf-token` cookie) that can escalate to CAPTCHA ([Portal FAQs](https://www.nccourts.gov/assets/documents/publications/Portal-FAQs-20231027.pdf), [AWS WAF docs](https://docs.aws.amazon.com/waf/latest/developerguide/waf-captcha-and-challenge.html)). Smart Search = 200-cap, 1-doc downloads. **Exception:** the separate **NC Judgment Search app** is login-free open JSON — the one compliant Tyler lane. Bulk = paid **RPA program**.

- **Journal Technologies (JTI)** (SC Public Index back end + C-Track appellate) — **express ToS anti-scrape ban** (the sharpest in the footprint) + **technical block** + **attorney bar discipline** for violation; active NAACP/ACLU First-Amendment challenge unresolved. Assume a hard wall; use manual export. Home addresses dropped from display 2026-01-01.

- **Cott Systems / CottHosting** (`cotthosting.com/<county>External`) — **"Sign in as Guest"** = free index/name/book-page search; **full account requires a signed, reviewed application** (form, signature, submitted; expires 30 days if incomplete); **document images run through a PAID cart** (Subtotal + Service Fee). Standard indemnify/hold-harmless "not the Official Record" disclaimer. Upsells PropertyCheck.

- **AcclaimWeb / Grant Street (Harris Recording)** (SC ROD — Pickens, Spartanburg-family) — **CLICK-THROUGH disclaimer**, index anonymous/free; **document images per-doc PAID**; **GridResults JSON omits the consideration/$** even when Consideration search is offered. Search by Name/Book-Page/Doc-Type/Description/Consideration/TMS/Record-Date.

- **Kofile / PublicSearch.us** (`psearch.kofile.com`, `<jur>.<state>.publicsearch.us`) — **LOGIN + PAID tiered**; free search + image view once registered, but **downloads ~$4.00/doc (+$1.50 surcharge)**, or **$175/mo subscription** drops to ~$2.00/doc; ToS has anti-account-sharing/anti-automation clause (Kofile may suspend at sole discretion). *(No footprint county surfaced on Kofile in this sweep.)*

- **Courthouse Computer Systems (CCS)** (`courthousecomputersystems.com` / `courtcompsys.com`) — **OPEN index**, unofficial copies free online, certified copies fee'd; optimized for older browsers. Low friction; 4 NC footprint counties.

- **Aumentum / Sentry (Tyler/Harris)** (Buncombe, Gaston ROD) — anonymous name search **OPEN**; **LOGIN account for full images**.

- **qPublic / Beacon (Schneider Geospatial)** (dominant assessor/parcel/GIS, NC + SC) — **one "Agree" GIS disclaimer** ("as is, no warranty… do not replace surveys/deeds") gates the UI, then fully **OPEN** free anonymous parcel/owner/CAMA/sales search. Light throttling, no legal wall. Our workhorse for sqft + sale history + owner.

- **PTS Cloud / Farragut (ncptscloud.com)** (WNC tax/parcel) — **OPEN** structured PWA/API; `lrcpwa.` = land records (owner/value/photo), `bcpwa.` = bills/unpaid (taxes-owed). No gate.

- **Grant Street TaxSys / LienHub / DeedAuction** (tax billing + tax-sale) — **OPEN** bill/delinquent-list lookup; **LOGIN-to-bid** for auctions.

- **County ArcGIS / FeatureServer / Open-Data Hub** (Buncombe, Henderson, Spartanburg, Anderson, Gastonia) — fully **OPEN REST** `/query` JSON + bulk shapefile/CSV/GeoJSON/WFS. The cleanest, most scrape-friendly tier; always check `.../server/rest/services?f=json` for a distressed layer (condemned, code-enf, land-use) before falling back to qPublic.

- **NC OneMap** (`services.nconemap.gov/secure/…`) — **OPEN REST** despite `/secure/` in the path; statewide parcels, `maxRecordCount 5000`, export sqlite/filegdb.

- **Anti-bot fingerprints to recognize elsewhere:** F5/Shape ("Client Challenge" interstitial), Imperva/Incapsula (`incap_ses_*`, `visid_incap_*`, `reese84`), PerimeterX/HUMAN (`_pxAppId`), DataDome (PropWire), Akamai (GovDeals/maestro.lqdt1.com — bypass via `curl_cffi impersonate=chrome`), Cloudflare, Turnstile/reCAPTCHA/hCaptcha. Detect by cookie/JS signature ([is-antibot](https://github.com/microlinkhq/is-antibot)).

- **PostingPro (`postingpro.net`)** (several SC delinquent-tax sales, Anderson) — bidder-registration to bid, listings/lists open to view; one template reusable across counties.

- **Secretary of State:** NC SoS — free web search but **scripted search prohibited**, bulk PAID (use stealth-agent). SC SoS — free web search, **CAPTCHA-walled**, no API.

---

## 6. Honest bottom line

**Genuinely new, free, and buildable (act on these):**
1. **Spartanburg `Condemned_Properties` ArcGIS layer** — a true distress *signal* (condemnation), open REST, not a dup of our parcel/situs use. Highest-value net-new.
2. **scpublicnotices.com** — compliant statewide SC foreclosure/estate/sale-notice mirror that *routes around the Public Index scrape wall*. High value precisely because SC courts are walled.
3. **Terry Howe FLC HTML tables** — deeply-distressed owner-lost parcels, open HTML, view-free.
4. **County tax-sale bidder-list PDFs + PostingPro template** — the cleanest fix for the **taxes-owed $ gap** we've carried; owner+parcel+amount in one seasonal PDF.
5. **Anderson ACPASS full ingest** — one open cgi closes Anderson ROD + taxes + dockets simultaneously (currently our most under-exploited open SC county).
6. **NC vacant-land-use (`parusecode`) owner extraction** — free reconstruction of the paywalled USPS vacancy signal.
7. **CCS ROD vendor template** — four NC footprint counties (Gaston/Cleveland/Lincoln/Burke) on one open-index vendor we haven't templated.
8. **CourtListener RECAP Search Alerts** + **GSA Auctions structured API** + **FDIC Bargain Properties** — incremental federal lanes on top of what we run.

**Already covered (do not re-build):** NC eCourts Judgment Search JSON (lis pendens/divorce/judgments/state-tax liens), NC Smart Search manual estates/foreclosure-SP, law-firm trustee feeds, MIE rosters, SC/NC ROD via Cott/AcclaimWeb/Logan/Aumentum index, qPublic parcels+sales, PTS Cloud tax, NC OneMap + SCDOT + Charleston resolver, ncnotices.com + Column, obituaries (Gannett + funeral RSS), heir/estate scraper, jail bookings, SC DOR lien registry, CourtListener bankruptcy, Spartanburg qPayBill taxes-owed, federal REO core, NC voter-file, NC SoS agent enricher, unclaimed property.

**Walls we already knew — confirmed still walls, don't re-chase:**
- **SC Public Index** = express ToS anti-scrape + technical block + bar discipline + pending 1A suit → manual gather only (and now **home addresses stripped since 2026-01-01**, so case→property must go through ROD/GIS).
- **NC eCourts Smart Search** = CAPTCHA-every-10-min + AWS-WAF → estates/foreclosure-SP detail is view-only, not bulk (Judgment JSON is the compliant lane).
- **SC exempt-deed sale prices** legally absent (§12-24-70) — distressed targets carry no recoverable stamp.
- **RoD document images** subscriber-walled (Cott cart, Kofile $4/doc-or-$175/mo, AcclaimWeb per-image) — but recorded PDFs are frequently free-downloadable and OCR-able for loan/lien $.
- **Evictions** = no free bulk feed (SC magistrate wall; NC eviction lane not yet wired but open via eCourts small claims).
- **Code-enforcement** = no free in-footprint feed except where a county publishes an ArcGIS code-enf/condemned layer (hunt per-county).
- **USPS true vacancy** = HUD-gated (gov/non-profit only, aggregated to tract/ZIP) or Regrid/Landgrid PAID (and discourages direct-mail use) — reconstruct from land-use + delinquency + no-homestead + condemned proxies.
- **Expired/withdrawn listings** = MLS/vendor-only (REDX/Vulcan7 PAID) — the one signal with no compliant free path; skip under the free+public mandate.
- **SC voter file** = PAID + **§30-2-50 commercial-solicitation ban** — ID/address-confirm only, not campaign mail; no SC voter phone.
- **PACER** bankruptcy = per-page PAID (use CourtListener RECAP archive + alerts instead).
- **US Marshals / Treasury / IRS / homesales.gov** seized-real-property feeds = 403/decommissioned dead ends; the live federal routes are the REO six-pack.
- **SC SoS** = CAPTCHA-walled, no API.

Net: of everything surveyed, the **eight buildable adds in section 4/6** are the real yield — led by the **condemned-properties GIS layer, scpublicnotices.com, Terry Howe FLC, and the tax-sale bidder-list PDFs** (which finally close the taxes-owed dollar gap). Everything else is either already in the ~110-scraper stack or a wall we had already mapped and correctly stopped chasing.
