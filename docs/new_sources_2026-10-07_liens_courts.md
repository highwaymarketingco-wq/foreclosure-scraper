# New lien, court-filing and title-fact sources, NC + SC (2026-10-07)

Companion data: `docs/new_sources_2026-10-07_liens_courts.json` (same records, every field). Scope: every source found for federal and state tax liens, judgment liens, mechanics and HOA liens, child-support and municipal liens, UCC fixtures, lis pendens, quiet title / partition / unknown-heirs filings, bankruptcy, probate, divorce, sheriff and tax sales, surplus funds, county-owned and tax-deed property, REO, trustee notices, public-notice aggregators and entity filings, for NC, SC and the national systems that cover them.

## How this was done

- Started from what the repo already reads: every scraper module, `docs/SOURCE_REGISTER.md`, `MASTER_SOURCE_AND_COUNTY_REGISTER.md`, `NEW_SOURCES_2026-06-16.md`, `missing_lead_sources_research.md`, `blocked_sources_forensic.md`, `gap_sources.md`, `county_records/README.md`, `county_breadth_research_2026-09-21.md`, `case_type_code_map.md`. 1,493 domains were already referenced; a candidate counts as new only when its specific page, layer or lane is not read by any module.
- New candidates came from web search, the ArcGIS Online item index (to find the data layer behind county map apps) and direct probes: one GET per page, at least 1.7 s between requests to a host, an ordinary browser User-Agent. No CAPTCHA, login, paywall, WAF or bot check was solved, bypassed or routed around; a block page was recorded as the access class and the probe stopped there.
- Each record says whether its access was probed today (`access_evidence`) or carried from an earlier repo document (`documented_before`). Sixteen of the counted sources were documented earlier but never read; they are flagged rather than claimed as discoveries.

## Counts

- Records: **75**. Sources not previously read in any form (including new lanes on an endpoint the repo already calls, and walled or paid ones): **61**. The rest are statutory facts, absent lists and dead endpoints recorded so nobody re-chases them.
- Not-previously-read sources by access class: open 42, bot-check 6, CAPTCHA 4, paid 4, terms-only 2, login 2, JS-app 1.
- All records by access class: open 56, bot-check 6, CAPTCHA 4, paid 4, terms-only 2, login 2, JS-app 1.
- All records by status: live 49, undetermined 11, absent 9, dead 3, empty 2, seasonal 1.

## Where each lien actually lives (the structural finding)

NC and SC file the same liens in different offices, which decides where a reader has to look.

| Lien / filing | North Carolina | South Carolina | What the repo reads |
|---|---|---|---|
| IRS notice of federal tax lien on real property | Clerk of Superior Court (NCGS 44-68.12) | Register of Deeds, or Clerk where the ROD was abolished (SC Code 12-57-30) | NC: Judgment Search `CV - Federal Tax Lien`. SC: not read (see SC-ROD-LIENS). The IRS publishes no list. |
| State tax lien | NC DOR certificate of tax liability docketed with the Clerk (NCGS 105-242) | SC DOR delinquent list; SC DEW lien registry | NC: Judgment Search. SC: both lists read. |
| Money judgment | Docketed judgment is a lien on the debtor's real property in that county (NCGS 1-234) | Judgment roll in the Clerk of Court (Public Index, terms bar automation) | NC: only 'Transcript of Judgment' read; plain money judgments dropped (NC-JS-MONEY). SC: walled. |
| Mechanics / materialmen lien | Claim of lien filed with the Clerk (NCGS 44A-12); lien-agent filings on LiensNC | Register of Deeds (SC Code 29-5-90) | NC: Judgment Search `CV - Claim of Lien` + LiensNC. SC: not read. |
| HOA assessment lien | Claim of lien filed with the Clerk (NCGS 47F-3-116), enforced by power of sale | Register of Deeds; foreclosed through Master-in-Equity | NC: Judgment Search + notices. SC: not read. |
| Child support | Arrears judgments in the Clerk's docket (FAM causes) | Family Court (not public in bulk) | NC: not read (NC-JS-FAM). SC: absent. |
| Lis pendens | Clerk of Superior Court | Clerk of Court (Public Index) | NC read; SC one lane read. |
| UCC fixture filing | Register of Deeds; SoS for entity collateral | Register of Deeds; SoS (ucconline.sc.gov) | NC SoS UCC module built (0 rows); SC not read. |

## The three scrapers built today

| Module | Source | Live proof 2026-10-07 (counts only) |
|---|---|---|
| `counties_nc.mecklenburg_delinquent_tax` | Mecklenburg NCGS 105-369 advertisement workbooks (individual + business) | 43,355 rows (28,515 + 14,840), tax year 2025, $35.5M due, 9,058 rows at $1,000+; every row has a street, 41,418 a city, 39,297 a ZIP |
| `counties_nc.guilford_tax_foreclosures` | Guilford ForeclosuresPublic layer | 931 rows read, 930 emitted (894 assigned to attorney, 17 notice of sale, 13 upset bid, 6 pending confirmation); all with owner, situs and owner mailing |
| `counties_nc.mecklenburg_tax_foreclosures` | Mecklenburg TaxForeclosures layer | 618 rows (363 unassigned, 116 RBCWB, 73 Kania, 66 in-rem); all with situs, amount due and lat/lng; no owner field on the layer |

Tests (hand-written fixtures, made-up names): `tests/test_mecklenburg_delinquent_tax.py`, `tests/test_guilford_tax_foreclosures.py`, `tests/test_mecklenburg_tax_foreclosures.py` (21 tests). The three raw blocks were added to `web_artifact.RAW_KEEP` so they survive board publication. Each module has an env gate (`FORECLOSURE_MECKLENBURG_DELINQUENT`, `FORECLOSURE_GUILFORD_TAX_FC`, `FORECLOSURE_MECKLENBURG_TAX_FC` = 0 to skip). The Mecklenburg workbook adds about 43k rows to a full run; they carry situs but no parcel number, so the address resolver does the parcel join.

## Top 10 by value

| # | Source | Access | Why |
|---|---|---|---|
| 1 | Mecklenburg advertisement of unpaid tax liens (NCGS 105-369), individual + business workbooks (`NC-MECK-ADV`) | open | 43,355 situs-addressed tax-lien leads in the largest NC county; built. |
| 2 | SC county Register of Deeds indexes: federal tax liens (SC Code 12-57-30), mechanics liens (29-5-90), HOA liens, state tax warrants, lis pendens copies (`SC-ROD-LIENS`) | open | Only free home of SC federal tax liens, mechanics liens and HOA liens; needs per-county adapters for lien document types. |
| 3 | NC eCourts Judgment Search: docketed money judgments lane (CV - Money Owed, Collection on Account, Contract, US District Court Judgment) (`NC-JS-MONEY`) | open | Open JSON already called daily; adding the money-judgment causes surfaces roughly 17% of about 78,663 statewide hits per 90 days, each a lien on the debtor's NC real property (estimate from the repo's own sample). |
| 4 | Bankruptcy court CM/ECF public RSS, District of SC (`FED-RSS-SCB`) | open | Open feed, about 780 docket entries a day incl. about 10 relief-from-stay motions; with NCMB and NCWB about 18 lift-stay motions a day, same-day. |
| 5 | Guilford tax-foreclosure pipeline (ForeclosuresPublic FeatureServer layer) (`NC-GUIL-TFC`) | open | 930 tax-foreclosure leads with owner and mailing; built. |
| 6 | Mecklenburg tax-foreclosure pipeline (TaxForeclosures MapServer layer) (`NC-MECK-TFC`) | open | 618 tax-foreclosure leads with amount owed; built. |
| 7 | Horry County probate (Spartan public portal) (`SC-HORRY-PROBATE`) | open | Open JSON, 2,968 estates in 2026; documented 2026-09-21, never built. |
| 8 | ncnotices.com title-clearing lanes (partition, quiet title, unknown heirs, heirs at law, execution sale, claim of lien) (`NC-NOTICES-TITLE`) | terms-only | Statewide quiet title, partition and unknown-heirs notices on a platform the repo already drives; the attorney's own market. |
| 9 | The Mecklenburg Times public notices (real estate, probate, individual/family groups; RSS export) (`NC-MECKTIMES`) | open | Charlotte's legal organ: power-of-sale notices with SP number, owner and address, plus an RSS export. |
| 10 | The Columbia Star: Master's Sales and Public Notices (Richland MIE notices) (`SC-COLSTAR`) | open | Only open online list of Richland County (Columbia) foreclosure sales; full notice text. |

## All records

Columns: access class, status, already ingested, role (lead / verification / both), build hours, value. URLs, fields, cadence, volume and evidence are in the JSON.

| id | source | geography | access | status | already ingested | role | hrs | value |
|---|---|---|---|---|---|---|---|---|
| NC-MECK-ADV | Mecklenburg advertisement of unpaid tax liens (NCGS 105-369), individual + business workbooks | Mecklenburg NC | open | live | BUILT 2026-10-07: counties_nc.mecklenburg_delinquent_tax (both lists, every row) | lead | 0 | Largest NC county had no tax-delinquency source; 43,355 situs-addressed tax-lien leads |
| NC-MECK-TFC | Mecklenburg tax-foreclosure pipeline (TaxForeclosures MapServer layer) | Mecklenburg NC | open | live | BUILT 2026-10-07: counties_nc.mecklenburg_tax_foreclosures. Before: law_firms.kania showed about 5 Mecklenburg rows | lead | 0 | 618 pre-sale forced-sale leads with amount owed, about 120x what Kania exposes for this county |
| NC-GUIL-TFC | Guilford tax-foreclosure pipeline (ForeclosuresPublic FeatureServer layer) | Guilford NC | open | live | BUILT 2026-10-07: counties_nc.guilford_tax_foreclosures. Before: law_firms.zacchaeus shows only parcels with a sale date set | lead | 0 | 930 forced-sale leads with owner + mailing; whole pipeline, not only scheduled sales |
| NC-MECK-TOP100 | Mecklenburg Top 100 Delinquent Taxpayers (monthly XLSX) | Mecklenburg NC | open | live | not read | verification | 2 | Current-month check on the biggest Mecklenburg debtors; confirms a lead is still unpaid |
| NC-MECK-PUB | Mecklenburg Delinquent Taxpayer Publication (PDF) | Mecklenburg NC | open | live | not read | verification | 6 | Low: the 105-369 workbooks above carry the real-property liens in clean form |
| NC-MECK-SHERIFF | Mecklenburg Sheriff public auctions (execution sales of real property) | Mecklenburg NC | bot-check | live | not read | lead | 4 | Execution sale = a docketed judgment being enforced against the owner's real estate |
| NC-DURHAM-SHERIFF | Durham County Sheriff notices of execution sale of real property | Durham NC | bot-check | live | not read | lead | 4 | Judgment-lien enforcement sales in Durham |
| NC-FORSYTH-TFC | Forsyth County property tax foreclosure sales page | Forsyth NC | open | live | not read | lead | 3 | Small but complete: owner, case number and minimum bid per parcel |
| NC-FORSYTH-ADV | Forsyth County advertisement of unpaid tax liens (PDFs A-F, G-O, P-Z) | Forsyth NC | open | live | partial: Forsyth delinquents already read by counties_nc.nc_ptscloud_delinquent_tax | verification | 4 | Cross-check of the PTS roll against the legal advertisement |
| NC-CABARRUS-TFC | Cabarrus County tax foreclosures (dataForeclosures.json behind foreclosures.cabarruscounty.us) | Cabarrus NC | open | live | not read | lead | 2 | Clean JSON, case numbers for every tax-foreclosure parcel |
| NC-CABARRUS-OWNED | Cabarrus County Owned Parcels (ArcGIS) | Cabarrus NC | open | live | not read | verification | 2 | Marks parcels the county took; low lead value |
| NC-UNION-TFC | Union County NC property tax foreclosure auction list | Union NC | bot-check | live | not read | lead | 3 | County tax-foreclosure list for a large Charlotte-area county |
| NC-DURHAM-TFC | Durham County tax foreclosure page (per-parcel sale notice PDFs) | Durham NC | open | live | not read | lead | 3 | Small; Durham sells a few tax-foreclosure parcels a month |
| NC-DURHAM-DELQ | Durham County delinquent taxpayer list (Spatialest app) | Durham NC | JS-app | live | not read | lead | 6 | Durham-wide tax-delinquency list, the same kind of lead as the Mecklenburg workbooks |
| NC-MECKTIMES | The Mecklenburg Times public notices (real estate, probate, individual/family groups; RSS export) | Mecklenburg, Union, Iredell NC | open | live | not read directly; ncnotices.com (read) put only 4 Mecklenburg rows on the 2026-10-03 board | lead | 4 | Legal organ for Charlotte; power-of-sale notices with SP numbers and owners for the state's largest county |
| NC-CUMB-SURPLUS | Cumberland County surplus property layer (county-owned, tax-lien fields) | Cumberland NC | open | empty | not read | lead | 2 | Tax-foreclosure-acquired county property; empty now |
| NC-UNION-DEVNET | Union County NC DelinquentTax MapServer (DevNet) | Union NC | open | dead | not read | lead | 0 | Dead endpoint |
| NC-LEE-TFC | Lee County NC tax foreclosure sales and foreclosure-acquired surplus/upset-bid form | Lee NC | open | live | not read | lead | 3 | Small county; low |
| NC-IREDELL-DELQ | Iredell County Delinquent_Taxes ArcGIS service | Iredell NC | open | undetermined | not read | lead | 2 | Re-probe; would add a mid-size county's delinquent parcels |
| NC-FAY-CODE | Fayetteville NC code enforcement cases (ArcGIS) | Fayetteville / Cumberland NC | open | empty | not read | lead | 2 | Municipal code cases precede demolition and cleanup liens; empty now |
| NC-JS-MONEY | NC eCourts Judgment Search: docketed money judgments lane (CV - Money Owed, Collection on Account, Contract, US District Court Judgment) | NC statewide (100 counties) | open | live | partial: counties_nc.nc_ecourts_lis_pendens reads this endpoint but drops these causes | both | 3 | Under NCGS 1-234 a docketed money judgment is a lien on the debtor's real property in that county; a title-search fact and a debt-pressure lead |
| NC-JS-FAM | NC eCourts Judgment Search: family lanes (FAM - Arrears/Child Support, Equitable Distribution, QDRO) | NC statewide | open | live | partial: only 'FAM - Divorce' is read | both | 2 | Child-support arrears judgments are liens; equitable distribution orders force division or sale of marital real property |
| NC-NOTICES-TITLE | ncnotices.com title-clearing lanes (partition, quiet title, unknown heirs, heirs at law, execution sale, claim of lien) | NC statewide (97 counties) | terms-only | live | partial: nc_notices_counties queries only 'foreclosure', 'delinquent taxes', 'advertisement of tax liens', 'notice to creditors'; ncpublicnotices adds divorce/probate terms | lead | 4 | The attorney's own market: who else is clearing title, with the heirs the plaintiff could not find named |
| SC-NOTICES-TITLE | scpublicnotices.com quiet title / partition / heirs-at-law lanes | SC statewide (46 counties) | terms-only | live | partial: counties_sc.sc_public_notices canned categories; column_legal_notices parses quiet title only for Column papers | lead | 4 | SC equivalent of the NC title-clearing lane |
| NC-ECOURTS-HEARINGS | NC eCourts Portal hearing / court-date search (special-proceeding foreclosure hearings) | NC statewide | CAPTCHA | live | not read | lead | 0 | Would show every power-of-sale hearing before the notice of sale |
| NC-AOC-CAL-LEGACY | Legacy NC AOC court calendars (www1.aoc.state.nc.us) | NC statewide | open | dead | not read | lead | 0 | None; replaced by eCourts |
| FED-RSS-NCMB | Bankruptcy court CM/ECF public RSS, Middle District of NC | NC Middle District (24 counties) | open | live | partial: read indirectly through CourtListener (courtlistener_bankruptcy / courtlistener_adversary) | both | 4 | Same-day lift-stay and sale motions without waiting for CourtListener |
| FED-RSS-SCB | Bankruptcy court CM/ECF public RSS, District of SC | SC statewide | open | live | partial: via CourtListener | both | 2 | Largest of the three feeds |
| FED-RSS-NCWB | Bankruptcy court CM/ECF public RSS, Western District of NC | NC Western District (32 counties) | open | live | partial: via CourtListener | both | 2 | Covers the WNC flip footprint |
| FED-RSS-NCEB | Bankruptcy court CM/ECF public RSS, Eastern District of NC | NC Eastern District | open | absent | not read | both | 0 | None; EDNC is covered only through CourtListener/PACER |
| FED-WDNC-CAL | WDNC bankruptcy weekly hearing calendars (per judge, PDF) | NC Western District | open | live | not read | lead | 6 | A lift-stay hearing means the lender is about to resume foreclosure on that debtor's home |
| FED-NCMB-CAL | MDNC bankruptcy court calendars | NC Middle District | open | undetermined | not read | lead | 4 | Same lift-stay signal for Greensboro/Winston-Salem/Durham |
| FED-NCEB-CAL | EDNC bankruptcy court calendar | NC Eastern District | open | undetermined | not read | lead | 4 | Fills the EDNC RSS gap |
| FED-SCB-CAL | DSC bankruptcy public calendar | SC statewide | open | undetermined | not read | lead | 4 | SC lift-stay hearings |
| FED-UCF | U.S. Courts Unclaimed Funds Locator | national | CAPTCHA | live | not read | verification | 0 | Confirms a debtor or heir is owed court-held money |
| FED-SCB-UCF | DSC bankruptcy unclaimed funds database | SC | open | undetermined | not read | verification | 3 | Name check for SC debtors |
| FED-NCWB-UCF | WDNC bankruptcy unclaimed funds search | NC Western District | open | undetermined | not read | verification | 3 | Name check |
| FED-PACER | PACER and PACER Case Locator | national | paid | live | not read (CourtListener/RECAP is the free mirror already read) | both | 0 | Authoritative; bankruptcy Schedule A/B lists the debtor's real property and Schedule D its liens |
| FED-PACERMONITOR | PacerMonitor | national | login | live | not read | verification | 0 | Free tier shows case lists; documents need an account |
| FED-DOCKETALARM | Docket Alarm | national incl. some state courts | paid | live | not read | verification | 0 | Paid alternative to PACER/UniCourt |
| FED-CL-NOS870 | CourtListener federal civil lane: NOS 870 'Taxes (U.S. plaintiff or defendant)' | NC + SC federal district courts | open | live | partial: national.courtlistener_civil filters NOS 220/230/240/290 only | lead | 2 | The only public place an IRS lien turns into a forced sale of a named owner's home |
| SC-ROSTERS-MORE | SC Public Index court rosters, Master-in-Equity sale rosters for counties not yet read (York, Aiken, Lexington, Richland and others) | SC | bot-check | live | partial: sc_county_rosters reads Oconee/Cherokee/Laurens/Union and sc_coastal_rosters the coastal counties; policy is not to extend stealth to new counties | lead | 0 | Every judicial foreclosure sale in the larger Midlands/York counties |
| SC-COLSTAR | The Columbia Star: Master's Sales and Public Notices (Richland MIE notices) | Richland SC | open | live | not read | lead | 5 | Only open online list of Richland County foreclosure sales found (the county MIE page posts none) |
| SC-RICHLAND-MIE | Richland County Master-in-Equity foreclosure sales page | Richland SC | open | absent | not read | lead | 0 | None online; use SC-COLSTAR or the roster |
| SC-RICHLAND-TAXSALE | Richland County delinquent tax sale / FLC listing | Richland SC | bot-check | live | partial: counties_sc.richland_flc reads the FLC list (3 rows) | lead | 3 | Richland tax-sale list |
| SC-RICHLAND-ESTATE | Richland County Probate Estate Inquiry | Richland SC | open | live | not read | both | 4 | Confirms an owner is deceased and an estate is open; heirs lead |
| SC-LEX-TAXSALE | Lexington County delinquent tax sale real-estate and mobile-home files | Lexington SC | open | seasonal | not read | lead | 4 | Large SC county's whole tax-sale list |
| SC-LEX-PROBATE | Lexington County probate search API | Lexington SC | CAPTCHA | live | not read | both | 0 | Lexington estates |
| SC-HORRY-PROBATE | Horry County probate (Spartan public portal) | Horry SC | open | live | not read | lead | 5 | Biggest open SC probate index not yet read |
| SC-GREENWOOD-PROBATE | Greenwood County probate (Spartan public portal) | Greenwood SC | open | live | not read | lead | 3 | Decedent address makes these parcel-joinable |
| SC-HORRY-UPSET | Horry County Master-in-Equity upset bid sales page | Horry SC | open | undetermined | not read | lead | 3 | Small |
| SC-YORK-TAXSALE | York County 2026 tax sale information document | York SC | bot-check | live | partial: counties_sc.york_delinquent_tax is built but returns 0 rows | lead | 0 | York tax-sale list |
| SC-CHAS-OVERAGE | Charleston County unclaimed tax-sale overage list | Charleston SC | open | undetermined | not read | lead | 2 | Heir/former-owner lead if the list exists |
| SC-GVL-OVERAGE | Greenville County tax-sale overage | Greenville SC | open | absent | not read | lead | 0 | None online |
| SC-UCC | SC Secretary of State UCC online search (incl. fixture filings against entity owners) | SC statewide | open | live | not read | verification | 4 | Shows lenders with a security interest in an entity owner's fixtures or rents |
| SC-ROD-LIENS | SC county Register of Deeds indexes: federal tax liens (SC Code 12-57-30), mechanics liens (29-5-90), HOA liens, state tax warrants, lis pendens copies | SC statewide | open | live | partial: ROD adapters exist for deeds; lien document types are not read | both | 6 | In SC every federal tax lien on real property, mechanics lien and HOA lien is here and nowhere else free |
| NC-ROD-UCC | NC county Register of Deeds indexes: UCC fixture filings, deeds of trust, appointments of substitute trustee, lien releases | NC statewide | open | live | partial: substitute-trustee and foreclosure-start lanes for a few WNC counties | verification | 6 | Fixture filings and DOT releases verify encumbrances on a lead |
| PAID-TAXSALERES | Tax Sale Resources | national incl. SC counties | paid | live | not read | lead | 0 | Paid shortcut for SC tax-sale lists |
| PAID-GOLIATH | Goliath Data tax-delinquent lists | national incl. NC/SC counties | paid | live | not read | lead | 0 | Resells what the county files above give free |
| VER-FANNIE-LOOKUP | Fannie Mae Loan Lookup | national | open | live | not read | verification | 0 | Tells whether a later REO would surface on HomePath |
| VER-MERS | MERS ServicerID | national | CAPTCHA | live | not read | verification | 0 | Who to call about a defaulted loan |
| VER-NCCASH | NC Treasurer unclaimed property (NCCash) | NC | open | live | not read | verification | 0 | Decedent or former-owner funds point to heirs |
| FED-FEMA-HMA | OpenFEMA Hazard Mitigation Assistance mitigated properties (v4; replaced by HMA Subapplications Project Site Inventories v1) | national | open | live | not read | verification | 1 | Low: no address |
| FED-HUD-SFREO | HUD single-family REO ArcGIS layer (SF_REO) | national | open | live | partial: hud_homestore reads the same inventory | lead | 1 | Duplicate of HUD Home Store |
| SC-MCDONALD-PATRICK | McDonald Patrick foreclosure sale lists (Greenwood, Edgefield, Abbeville, McCormick, Saluda, Newberry) | 6 SC counties | open | live | not read | lead | 3 | Judicial foreclosure sales in small Upstate counties |
| FED-USDA-FSA | USDA Farm Service Agency inventory property (farm REO) | national | open | undetermined | not read | lead | 2 | Rural NC/SC farm REO, rare |
| FED-HUD-MF | HUD Multifamily property disposition sales | national | open | undetermined | not read | lead | 2 | Rare in NC/SC |
| REO-RESNET | RES.NET | national | login | undetermined | not read | lead | 0 | No public inventory found |
| ABS-IRS-NFTL | IRS notices of federal tax lien: public list | national | open | absent | NC side read via Judgment Search 'CV - Federal Tax Lien'; SC side see SC-ROD-LIENS | verification | 0 | Route is the filing office, not the IRS |
| ABS-NCDOR-LIST | NC Department of Revenue public delinquent-taxpayer list | NC | open | dead | NC DOR certificates of tax liability are read via Judgment Search 'CV - NC Certificate of Tax Liability' | verification | 0 | Dead; the clerk docket is the source |
| ABS-NC-SURPLUS | NC foreclosure surplus funds held by the Clerk of Superior Court: public list | NC | open | absent | not read | lead | 0 | Absent |
| ABS-HOA | Dedicated HOA lien / HOA foreclosure lists | NC + SC | open | absent | partial (clerk + notices) | lead | 0 | Absent as a list |
| ABS-WATER | Water / sewer lien lists | NC + SC | open | absent | not read | lead | 0 | Absent |
| ABS-SC-CHILDSUPPORT | SC DSS child-support delinquent list | SC | open | absent | not read | lead | 0 | Absent |
| ABS-CU-REO | Credit union / regional bank REO lists (SECU and others) | NC + SC | open | absent | not read | lead | 0 | Absent |

## Walled sources: what a person does by hand

| id | wall | manual step |
|---|---|---|
| NC-MECK-SHERIFF | bot-check: probed 2026-10-07: HTTP 403, Cloudflare 'Attention Required' page to a plain GET; PDFs under /publicauctions/pdf/ seen in search indexes | Open https://www.mecksheriff.com/publicauctions/ in a normal browser, save the page and each notice PDF into the manual-export folder; a parser can read the saved files offline. |
| NC-DURHAM-SHERIFF | bot-check: probed 2026-10-07: HTTP 403 'Access Denied' to a plain GET of a published notice | Open the Sheriff's civil/sales page in a browser and save the notice PDFs for offline parsing. |
| NC-UNION-TFC | bot-check: probed 2026-10-07: HTTP 403 (546-byte block page) to a plain GET | Open the page in a browser and save the linked PDFs, or email taxforeclosures@unioncountync.gov for the list. |
| NC-DURHAM-DELQ | JS-app: probed 2026-10-07: HTTP 200, 7 KB single-page app shell; data endpoint not inspected | Open the page in a browser; if it offers an export, save it for offline parsing. |
| NC-NOTICES-TITLE | terms-only: grid preview open (repo already drives it); detail pages sit behind a terms click-through | Accept the terms once in a browser when detail text is needed; the grid lane needs no click. |
| NC-ECOURTS-HEARINGS | CAPTCHA: probed 2026-10-07: HTTP 405 'Human Verification' AWS-WAF CAPTCHA page | Open the portal, solve the check yourself, search hearings by county and date range with case type Special Proceedings, save the results page for the existing manual-export parser. |
| FED-UCF | CAPTCHA: probed 2026-10-07: HTTP 200, CAPTCHA widget on the search page | Search a name on ucf.uscourts.gov in a browser. |
| FED-PACER | paid: probed 2026-10-07: PCL HTTP 200 login page; $0.10/page, fees waived under $30 per quarter | Person with their own PACER account runs a PCL party search and saves the docket or schedule PDF for a top lead. |
| FED-PACERMONITOR | login: probed 2026-10-07: HTTP 200, login and CAPTCHA widgets | Account holder searches and exports. |
| SC-ROSTERS-MORE | bot-check: York and Aiken county MIE pages link here directly (probed 2026-10-07, both HTTP 200); host is behind an F5 'Client Challenge' plus a disclaimer that bars automated querying | Accept the disclaimer in a browser, open Court Rosters, pick the Master-in-Equity roster for the month, save the page; the existing roster parser reads saved HTML. |
| SC-RICHLAND-TAXSALE | bot-check: probed 2026-10-07: HTTP 403 (451-byte block page) to a plain GET | Open the page in a browser during October-November and save the list file. |
| SC-LEX-PROBATE | CAPTCHA: documented 2026-09-21: HTTP 401; token issued only after reCAPTCHA v3 | Search names in the county's probate search in a browser. |
| SC-YORK-TAXSALE | bot-check: probed 2026-10-07: HTTP 403 Cloudflare 'Just a moment' to a plain GET | Open in a browser and save the PDF. |
| PAID-TAXSALERES | paid: probed 2026-10-07: HTTP 200 county page, list behind login | Subscription only. |
| VER-MERS | CAPTCHA: probed 2026-10-07: HTTP 200, CAPTCHA widget | Search in a browser. |

## New lanes on sources the repo already reads

- `NC-FORSYTH-ADV`: partial: Forsyth delinquents already read by counties_nc.nc_ptscloud_delinquent_tax
- `NC-JS-MONEY`: partial: counties_nc.nc_ecourts_lis_pendens reads this endpoint but drops these causes
- `NC-JS-FAM`: partial: only 'FAM - Divorce' is read
- `NC-NOTICES-TITLE`: partial: nc_notices_counties queries only 'foreclosure', 'delinquent taxes', 'advertisement of tax liens', 'notice to creditors'; ncpublicnotices adds divorce/probate terms
- `SC-NOTICES-TITLE`: partial: counties_sc.sc_public_notices canned categories; column_legal_notices parses quiet title only for Column papers
- `FED-RSS-NCMB`: partial: read indirectly through CourtListener (courtlistener_bankruptcy / courtlistener_adversary)
- `FED-RSS-SCB`: partial: via CourtListener
- `FED-RSS-NCWB`: partial: via CourtListener
- `FED-CL-NOS870`: partial: national.courtlistener_civil filters NOS 220/230/240/290 only
- `SC-ROSTERS-MORE`: partial: sc_county_rosters reads Oconee/Cherokee/Laurens/Union and sc_coastal_rosters the coastal counties; policy is not to extend stealth to new counties
- `SC-RICHLAND-TAXSALE`: partial: counties_sc.richland_flc reads the FLC list (3 rows)
- `SC-YORK-TAXSALE`: partial: counties_sc.york_delinquent_tax is built but returns 0 rows
- `SC-ROD-LIENS`: partial: ROD adapters exist for deeds; lien document types are not read
- `NC-ROD-UCC`: partial: substitute-trustee and foreclosure-start lanes for a few WNC counties
- `FED-HUD-SFREO`: partial: hud_homestore reads the same inventory
- `ABS-HOA`: partial (clerk + notices)

## What could not be determined

- Exact volumes for the SC Master-in-Equity rosters in York, Aiken, Lexington and Richland (behind the Public Index F5 challenge and terms), the Union NC and Richland SC lists (bot-checked), and the Mecklenburg and Durham sheriff execution sales (Cloudflare / Access Denied).
- Whether the Charleston County overage list is still published (not linked from either delinquent-tax page today).
- The file formats of the MDNC, EDNC and DSC bankruptcy hearing calendars and the DSC / WDNC unclaimed-funds searches (pages answer 200; contents not inspected).
- Current locations of the USDA FSA farm-REO list, HUD multifamily disposition sales, the Freddie Mac loan lookup and NCCash's search (old paths 404).
- The Iredell delinquent-tax layer (server error 500), the Horry MIE upset-bid list (not in static HTML), the Durham Spatialest delinquent list's data endpoint, Lexington's 2026 tax-sale file (posts about October 15).
- Whether the Ruff, Bond, Cobb, Wade & Bethune firm (116 Mecklenburg tax foreclosures) publishes its own sale list; no HOA-collection or substitute-trustee firm list beyond those already read was found before the web-search budget ran out.
- Paid aggregators (PACER, PacerMonitor, Docket Alarm, Tax Sale Resources, Goliath) were not tested beyond their public landing pages.

