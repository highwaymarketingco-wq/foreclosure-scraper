Verification complete. Writing the taxonomy.

# THE COMPLETE OBTAINABILITY TAXONOMY

## 0. The honest headline, first

"100% of everything" is not reachable, and the reason is not effort or budget. Of the 112 fields below, **roughly 22% cannot be obtained by anyone at any price** because they are physically never recorded, legally sealed, or held as private party data that no vendor lawfully resells. Another ~20% exist only inside the property or inside the owner's head and require a physical visit or the owner's consent, which means they are gated on *contact succeeding*, not on data acquisition.

The realistic ceiling, stated bluntly:

| Tier | Share of the 112 fields | What it costs |
|---|---|---|
| **FREE-AUTOMATED** at footprint scale today or with known code fixes | **~38%** (43 fields) | $0 |
| **+FREE-MANUAL** (operator pulls, saved HTML, per-parcel, FOIA) | **~22%** (25 fields), cumulative ~60% | $0 cash, 5 to 40 min per lead of human time |
| **+PAID** (vendor unlocks it, legally) | **~18%** (20 fields), cumulative ~78% | $100 to $400/mo tools + $0.07 to $0.25 per skip-trace hit |
| **REQUIRES-CONSENT / REQUIRES-PHYSICAL-VISIT** | **~9%** (10 fields) | gated on contact, not on data |
| **PHYSICALLY-UNRECORDED / LEGALLY-SEALED** (nobody, ever) | **~13%** (14 fields) | unobtainable at any price |

Critically, the percentages above are *field coverage*, not *lead coverage*. A field being FREE-AUTOMATED does not mean it is filled on every lead. Your board today is a good illustration: address is FREE-AUTOMATED and sits at 60.9%; owner_name is FREE-AUTOMATED and sits at 89.9%; recorded loan principal is FREE-MANUAL-to-AUTOMATED and sits at **0.0%**. Multiply field-obtainability by per-lead fill rate and the true "everything, everywhere" number is closer to **35 to 45%**.

**Classification key** (defined up front, per your convention):

- **FREE-AUTOMATED** = a keyless/public endpoint or compliant stealth fetch fills it unattended
- **FREE-MANUAL** = free to obtain but a human must click, save, FOIA, or read a per-parcel card
- **PAID** = a vendor sells it lawfully; free routes fail or are ToS-barred
- **LEGALLY-SEALED** = a statute or court rule bars disclosure
- **PHYSICALLY-UNRECORDED** = no record is ever created; the fact exists only in the world
- **REQUIRES-CONSENT** = only the owner/party can furnish it
- **REQUIRES-PHYSICAL-VISIT** = obtainable only by going there (or by paying someone to)

---

## A. PROPERTY (50 fields)

| # | Field | Exists as a record? | Best FREE source | Paid fallback + price | Class |
|---|---|---|---|---|---|
| A1 | Parcel ID / PIN / TMS | Yes | County GIS ArcGIS; NC OneMap parcels layer (verified 200, keyless) | Regrid (quote) | FREE-AUTOMATED |
| A2 | Situs address | Yes | County GIS `siteadd`/`PHYSICALADDR`; NC OneMap statewide fallback | Regrid, ATTOM ~$90/mo | FREE-AUTOMATED |
| A3 | Lat/long centroid | Yes | Parcel polygon centroid; FCC block API (verified 200) | n/a | FREE-AUTOMATED |
| A4 | Legal description | Yes (deed) | ROD index/image where free (Spartanburg Logan) | DataTree/TitlePro247, ~$100 to $200/mo | FREE-MANUAL |
| A5 | Acreage / lot size | Yes | County GIS `acres`/calc from polygon | Regrid | FREE-AUTOMATED |
| A6 | **Heated sqft** | Yes, in CAMA | NC assessor layers carry it; **SC GIS is blank everywhere** (LivingArea = 0 of 29,402 on the AGOL CAMA mirror). SC path is per-parcel qPublic CARD (Pickens/Oconee) | Paid county CAMA extract; ATTOM | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A7 | Beds | Yes, in CAMA | NC assessor; SC per-parcel card | ATTOM/PropStream $99/mo | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A8 | Baths | Yes, in CAMA | same as A7 | same | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A9 | Year built | Yes | County GIS/CAMA | ATTOM | FREE-AUTOMATED |
| A10 | Construction type / exterior wall | Yes, in CAMA | Assessor card; some GIS layers | Paid CAMA extract | FREE-MANUAL |
| A11 | **Roof age** | Rarely | Roof *material* sometimes on assessor card; **age almost never recorded**. Permit history is the only proxy (re-roof permit date) | Insurance/inspection data, not resold | PHYSICALLY-UNRECORDED (age); FREE-MANUAL (material) |
| A12 | **HVAC type / age** | Rarely | Assessor card lists heat type; **age unrecorded**. Mechanical permit is the proxy | none | PHYSICALLY-UNRECORDED (age) |
| A13 | Septic vs sewer | Yes | County health dept septic permit layers (several NC counties publish); assessor utility code | Paid CAMA | FREE-AUTOMATED (partial) / FREE-MANUAL |
| A14 | Well vs public water | Yes | Same as A13; utility service-area GIS | Paid CAMA | FREE-AUTOMATED (partial) |
| A15 | Zoning | Yes | County/municipal zoning GIS layers | Regrid zoning bundle | FREE-AUTOMATED |
| A16 | Land use code | Yes | County GIS/CAMA `landuse` | Regrid | FREE-AUTOMATED |
| A17 | **Flood zone** | Yes | **FEMA NFHL ArcGIS, verified HTTP 200 keyless**: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer` | n/a, free is complete | FREE-AUTOMATED |
| A18 | **Soil type / class** | Yes | **USDA Soil Data Access, verified HTTP 200, POST SQL, keyless**: `https://sdmdataaccess.sc.egov.usda.gov/Tabular/SDMTabularService/post.rest` | n/a | FREE-AUTOMATED |
| A19 | **Topography / slope** | Yes | **USGS EPQS, verified HTTP 200 keyless**: `https://epqs.nationalmap.gov/v1/json?x=&y=&units=Feet`; USGS 3DEP DEM for slope raster | n/a | FREE-AUTOMATED |
| A20 | Road frontage | Partial | Parcel polygon vs road centerline geometry (compute it); some CAMA carry frontage ft | Paid CAMA | FREE-AUTOMATED (computed) |
| A21 | Access / easements | Partially | Recorded easements in ROD index by doc type; landlocked status computable from geometry | Title search $75 to $200/parcel | FREE-MANUAL |
| A22 | Utilities available at road | Partial | Municipal utility service-area GIS; broadband via FCC | Utility co. direct | FREE-AUTOMATED (partial) |
| A23 | School district / assigned schools | Yes | **Urban Institute Education Data API, verified 200 keyless**: `https://educationdata.urban.org/api/v1/schools/ccd/directory/`; NCES EDGE district boundary shapefiles | GreatSchools API (paid) | FREE-AUTOMATED |
| A24 | HOA membership (is there one?) | Partially | Recorded declaration of covenants in ROD; subdivision plat; NC/SC SoS nonprofit registration for the HOA entity | PropStream flags it | FREE-MANUAL |
| A25 | **HOA dues amount** | Yes, but privately | **No public record.** Only the HOA, the management co., or a resale certificate states it | Resale cert $200 to $400, ordered by a party to a transaction | REQUIRES-CONSENT |
| A26 | Deed restrictions / covenants | Yes | ROD recorded declaration (free index; image free in Spartanburg-class counties) | Title search | FREE-MANUAL |
| A27 | Mineral rights severed? | Yes | ROD index for mineral reservation/severance deeds; requires full chain read | Title/landman search $150+ | FREE-MANUAL |
| A28 | Timber rights / standing timber value | Partial | Timber deeds in ROD; NAIP/LiDAR canopy for volume proxy | Forestry cruise $500+ | FREE-MANUAL (rights) / REQUIRES-PHYSICAL-VISIT (value) |
| A29 | Solar lease / PPA on the roof | Yes if recorded | **UCC-1 fixture filing at NC/SC SoS** (this is the real tell) plus recorded lease memo in ROD | none needed | FREE-MANUAL |
| A30 | Cell tower lease | Yes if recorded | Recorded lease memorandum/easement in ROD; FCC ASR for the structure itself | Lease-buyout firms' data, not sold | FREE-MANUAL |
| A31 | **Environmental contamination** | Yes | **EPA Envirofacts REST, verified 200 keyless**: `https://data.epa.gov/efservice/<table>/<col>/<val>/rows/0:1/JSON` (TRI, RCRA, Superfund, UST/LUST); state DEQ/DHEC brownfield layers | EDR Phase I ~$300 to $600 | FREE-AUTOMATED |
| A32 | Historic designation | Yes | **NPS NRHP MapServer, verified 200 keyless**: `https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer`; local historic-district GIS | n/a | FREE-AUTOMATED |
| A33 | Radon zone | Yes | EPA county radon zone map (static tables, county level only) | Home test $15 | FREE-AUTOMATED (county) / REQUIRES-PHYSICAL-VISIT (actual) |
| A34 | Wetlands | Yes | USFWS National Wetlands Inventory ArcGIS (public) | Delineation $2k+ | FREE-AUTOMATED |
| A35 | **Exterior condition** | No record | **Google Street View / Mapillary imagery + vision model.** Your `photo_address_stack` already does this. Stale by 1 to 4 years | Drive-by service $10 to $25 | FREE-AUTOMATED (proxy) |
| A36 | **Interior condition** | No record | **None.** No free source exists. Old MLS photos via Zillow/Realtor listing history are the only proxy, and those are ToS-restricted | Paid MLS/IDX access; inspection $400 | REQUIRES-PHYSICAL-VISIT |
| A37 | **Interior photos** | Only if listed | Prior-listing photos on portals (ToS-barred to scrape); assessor cards occasionally carry one interior shot | MLS access via licensee | REQUIRES-PHYSICAL-VISIT |
| A38 | Exterior photos | No record | Street View, county assessor parcel photos (your `parcel_photos` lane), NAIP aerial | n/a | FREE-AUTOMATED |
| A39 | Occupancy status | No direct record | **Proxies only:** USPS vacancy indicator (HUD-licensed, not open), utility shutoff (walled), mail-return, tall grass in Street View, absentee mailing mismatch | USPS/Melissa vacancy flag via PropStream $99/mo | PAID (clean) / FREE-AUTOMATED (proxy) |
| A40 | Vacancy duration | No record | Compare Street View capture dates | none | PHYSICALLY-UNRECORDED |
| A41 | Rental status (is it a rental?) | Partial | Absentee-owner flag; STR registries (Asheville built); local rental-registration rolls where they exist | PropStream/RentCast | FREE-AUTOMATED (proxy) |
| A42 | **Current rent being collected** | No record | **None.** Rent is a private contract | RentCast/Zillow rent AVM = *estimate*, not actual, ~$50/mo | PHYSICALLY-UNRECORDED (actual) |
| A43 | Building permits | Yes | Municipal permit portals (Accela/Tyler/CityView); many publish open data | Shovels.ai, BuildZoom (paid) | FREE-AUTOMATED (partial) / FREE-MANUAL |
| A44 | Code violations / open cases | Yes | Asheville built; **most counties have no free feed (confirmed WALL)**; LiensNC is login-gated | none reliable | FREE-MANUAL / FOIA |
| A45 | Tax assessed value | Yes | County GIS/CAMA, tax bill portals | n/a | FREE-AUTOMATED |
| A46 | Tax bill amount / annual taxes | Yes | Tax portals; qPayBill (SC), PTS bcpwa (NC) | n/a | FREE-AUTOMATED |
| A47 | Market value (AVM) | Derived | Your own model off assessor + sold comps (79% ARV coverage today) | ATTOM AVM, HouseCanary $$ | FREE-AUTOMATED |
| A48 | ARV | Derived | Computed in `calc.py`; unbiased at median, noisy, trust `arv_confidence` | HouseCanary/Clear Capital | FREE-AUTOMATED |
| A49 | Comps (sold) | Yes in NC | **NC: deed stamp × 500 recovers price.** SC: §12-24-70 exempts distressed deeds from stating value, so recorded price is genuinely absent; qPublic per-parcel CARD is the workaround | ATTOM/PropStream comps | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A50 | Days on market / prior listing history | Yes | **No compliant free route.** Portal ToS bars scraping listing history | MLS via licensee; ATTOM listing history | PAID |

---

## B. OWNER (25 fields)

| # | Field | Exists? | Best FREE source | Paid + price | Class |
|---|---|---|---|---|---|
| B1 | Legal name | Yes | County GIS `OWNER1`; ROD grantee index (89.9% of your board) | n/a | FREE-AUTOMATED |
| B2 | All co-owners / vested parties | Yes | ROD deed (OWNER2 field often truncated in GIS; deed is authoritative) | Title search | FREE-AUTOMATED (partial) / FREE-MANUAL (full) |
| B3 | Entity vs individual | Yes | String heuristic on owner name (LLC/INC/TRUST) | n/a | FREE-AUTOMATED |
| B4 | Entity officers | Yes | **NC SoS via stealth (Cloudflare JS-challenge, not CAPTCHA; verified 403 to plain curl, clears under stealth).** SC SoS is CAPTCHA-gated, so SC entities are skipped | OpenCorporates paid token | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| B5 | Registered agent | Yes | Same as B4, `enrichment_sos_agent.py` | OpenCorporates | FREE-AUTOMATED (NC) |
| B6 | Entity good-standing / admin dissolution | Yes | NC SoS profile (dissolution is a distress signal in itself) | n/a | FREE-AUTOMATED (NC) |
| B7 | **Trust beneficiaries** | Usually not | **Trusts are not registered.** Only the trustee name appears on the deed | none | PHYSICALLY-UNRECORDED |
| B8 | Mailing address | Yes | County tax roll mailing field; probate PR address (Charleston lane gives it direct) | n/a | FREE-AUTOMATED |
| B9 | Absentee / out-of-state status | Derived | Compare mailing vs situs state | n/a | FREE-AUTOMATED |
| B10 | **Phone** | Third-party PII | **NC voter file, verified free bulk download 200, ~498MB**: `https://dl.ncsbe.gov/data/ncvoter_Statewide.zip`, ~69% NC coverage. **SC has zero free route** (SC voter list is paid, purpose-restricted by SC Code 30-2-50, and carries no phone) | Skip trace **$0.07 to $0.25/record** (BatchData from ~$0.07; TLOxp from ~$100/mo; Accurint from ~$200/mo, $1 to $5/individual trace) | FREE-AUTOMATED (NC only) / PAID (SC) |
| B11 | **Email** | Third-party PII | **None. No free compliant source exists.** | Email append, per-hit paid | PAID |
| B12 | Age / DOB | Partially | **Jail booking rosters carry full DOB** (P2C, Zuercher, Citizen Connect endpoints verified, not yet built). Voter file carries birth year | Skip trace | FREE-AUTOMATED (once built) |
| B13 | **Marital status** | Partially | Deed vesting language ("husband and wife", "a single person") is the free tell. Marriage licenses are county-level, patchy online | Skip trace | FREE-AUTOMATED (proxy) / FREE-MANUAL |
| B14 | Heirs | Yes when probated | **Heir-parcel GIS sweep** ("X HEIRS", "ESTATE OF") plus Charleston probate PR name and address; obituaries name survivors | none | FREE-AUTOMATED |
| B15 | Death / date of death | Yes | Obituaries (Gannett + funeral-home RSS, built); probate filings; SSDI is no longer publicly open | LexisNexis deceased flag | FREE-AUTOMATED |
| B16 | **Incarceration (federal)** | Yes | **BOP Inmate Locator JSON, verified 200, `"Captcha":false`**: `https://www.bop.gov/PublicInfo/execute/inmateloc?todo=query&output=json&nameFirst=&nameLast=` | n/a | FREE-AUTOMATED |
| B17 | Incarceration (state/county) | Yes | SCDC wired; NC DPS offender search reachable (200, JS-heavy); county jail rosters BUILD-READY | n/a | FREE-AUTOMATED |
| B18 | Bankruptcy | Yes | **CourtListener RECAP v4, verified keyless 200, 133 results on ncwb**: `https://www.courtlistener.com/api/rest/v4/search/?type=r&court=ncwb&q=...` | PACER $0.10/page | FREE-AUTOMATED |
| B19 | Number of properties owned | Yes | Owner-name index across county GIS layers (self-join your own board) | PropStream portfolio search $99/mo | FREE-AUTOMATED |
| B20 | Other liens against the person | Partial | ROD name index (existence); SCDOR top-delinquent list (built) | Title search per name | FREE-AUTOMATED (existence) |
| B21 | Civil judgments | Yes NC / walled SC | **NC eCourts Judgment Search JSON, open and keyless** (already driving your lis-pendens lane). SC PublicIndex is ToS-no-scrape | UniCourt/Trellis paid API | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| B22 | **Employment** | No public record | **None.** Employer appears only on a UCC/UI-tax lien edge case or a court filing | Skip trace/credit header, restricted-use | PAID (restricted) |
| B23 | **Income** | No public record | None | Credit-header data is FCRA-restricted for this use | LEGALLY-SEALED |
| B24 | **Credit score / payment history** | Yes, at bureaus | **None. FCRA bars use for deal-sourcing.** | Not lawfully purchasable for this purpose | LEGALLY-SEALED |
| B25 | Relatives / associates | Third-party PII | Obituary survivor lists; shared-surname parcel joins | Skip trace relationship graph | FREE-AUTOMATED (partial) / PAID |

---

## C. DISTRESS EVENT (25 fields)

| # | Field | Exists? | Best FREE source | Paid + price | Class |
|---|---|---|---|---|---|
| C1 | **Mortgage original principal** | Yes, on the image only | **ROD index carries type/lender/date/book-page but NO dollar.** The figure is only on the scanned DOT image. Free image confirmed in Spartanburg (Logan `view_image.php`, ~281 to 313KB PDF, no cart/login). OCR it. **Your `enrichment_dot_ocr.py` is built and proven but hardcoded to Spartanburg, capped at 25/run, HOT/WARM-gated, and has never run at scale. This is your single largest unforced gap: recorded loan $ is 0.0% of the board.** | DataTree/TitlePro247 ~$100 to $200/mo | FREE-AUTOMATED (Spartanburg-class) / FREE-MANUAL (paywalled-image counties) |
| C2 | **Current loan balance / payoff** | Held by servicer only | **NONE. This cannot be obtained by anyone at any price.** Not public, changes mid-month, PII. MERS ServicerID returns servicer *name* only (site returned 503 maintenance at probe time, so treat as unverified today) | No vendor sells it. Even paid data brokers model it | PHYSICALLY-UNRECORDED |
| C3 | Lender / servicer name | Yes | ROD index (lender on DOT); MERS ServicerID for current servicer | n/a | FREE-AUTOMATED |
| C4 | **Payment status / months delinquent** | Held by servicer | **NONE free or paid.** Foreclosure filing is the only public proxy, and by then it is already late | none | PHYSICALLY-UNRECORDED |
| C5 | Foreclosure stage | Yes | NC eCourts Judgment JSON (LP); county foreclosure feeds; SC MIE rosters; SC FLC | ForeclosureRadar-class, paid | FREE-AUTOMATED |
| C6 | Sale date | Yes | Same as C5; auction feeds | n/a | FREE-AUTOMATED |
| C7 | Opening bid | Yes | Auction/MIE rosters (on 723 of your leads, 4.3%) | n/a | FREE-AUTOMATED |
| C8 | Judgment amount / indebtedness | Yes, unevenly | NC eCourts judgment records + CCHS `mo` money field (on 187 of your leads, 1.1%). **NC power-of-sale notices legally state only sale terms, deposit, and upset bid, never the debt (0 of 24 sampled notices carried any dollar figure)** | none | FREE-AUTOMATED (partial) / FOIA (Clerk of Court) |
| C9 | Redemption deadline | Yes, derivable | Statutory: computed from sale date per NCGS/SC code | n/a | FREE-AUTOMATED (computed) |
| C10 | Upset-bid status | Yes NC | NC Clerk of Superior Court upset-bid postings; some counties publish | n/a | FREE-MANUAL |
| C11 | Tax delinquency amount | Yes | **Strongest lane you have, 39.2% of board.** NC 105-369 PDFs (Buncombe/Lincoln/McDowell), PTS bcpwa CSVs (Henderson), SC qPayBill Unpaid (Spartanburg/Oconee/Cherokee/Union/Laurens) | n/a | FREE-AUTOMATED |
| C12 | Tax delinquent years | Yes | Same sources; year columns in the roll | n/a | FREE-AUTOMATED |
| C13 | Other liens + priority | Partial | ROD index for existence; SC state tax lien via SCDOR (built) | Title search $75 to $200 | FREE-AUTOMATED (existence) / PAID (full priority) |
| C14 | **IRS federal tax lien** | Yes, recorded | Recorded at county ROD, so free *where the ROD index is open*. Not free at scale across walled counties | Title/lien vendors | FREE-MANUAL |
| C15 | **HOA arrears** | Only if a lien was filed | Recorded HOA assessment lien in ROD (Charleston parsed, broader blocked on ROD rebuild). **Un-liened arrears are invisible** | none | FREE-MANUAL (liened) / REQUIRES-CONSENT (un-liened) |
| C16 | **Utility shutoff** | Yes, at the utility | **NONE. Customer records are exempt from public records in both NC and SC** | none | LEGALLY-SEALED |
| C17 | Probate stage | Yes | Charleston `southcarolinaprobate.net` (case, decedent, **PR name and full mailing address**); heir-parcel GIS; Column estate creditor notices. **Greenville SC probate is net-new and BUILD-READY** (`SearchResults.aspx?LastName=X`, plain GET, 5,637 rows on a test) | UniCourt | FREE-AUTOMATED |
| C18 | Divorce stage | Yes NC | **NC Judgment JSON already serves `causeOfActionDesc="FAM - Divorce"` with both spouses structured.** You have 1 divorce lead on the board because the filter was never widened. SC FCCMS forbids automated querying (legal wall, not technical) | UniCourt/Trellis | FREE-AUTOMATED (NC, config change) / FREE-MANUAL (SC) |
| C19 | **Eviction filings (seller-side)** | Yes, at magistrate | **Confirmed WALL.** SC portal exposes only Circuit-court roster types; there is no magistrate/ejectment roster type at all. NC eviction is walled | FOIA Chief Magistrate; LSC data-sharing agreement | FREE-MANUAL (FOIA only) |
| C20 | Vacancy duration | No record | Street View capture-date deltas | USPS vacancy flag via PropStream | PHYSICALLY-UNRECORDED |
| C21 | Code cases | Yes | Asheville built; most counties have no free feed | none | FREE-MANUAL |
| C22 | Lis pendens | Yes NC | NC eCourts Judgment JSON statewide (1,178 leads) | n/a | FREE-AUTOMATED |
| C23 | Bankruptcy chapter + 363 sales | Yes | CourtListener RECAP; `q="motion to sell" "real property"` surfaces trustee sales. **Fix: add ncmb, switch to keyless `/search/?type=r`, read party[] + Schedules** | PACER | FREE-AUTOMATED |
| C24 | Mortgage recording date / loan age | Yes | ROD index (date is in the index even when the dollar is not) | n/a | FREE-AUTOMATED |
| C25 | 2nd DOT / HELOC existence + amount | Yes | Existence from ROD index; **amount only from the image, same free-image ceiling as C1** | Title search | FREE-AUTOMATED (existence) / FREE-MANUAL (amount) |

---

## D. MARKET CONTEXT (12 fields)

| # | Field | Exists? | Best FREE source | Paid + price | Class |
|---|---|---|---|---|---|
| D1 | Recent arms-length sales | Yes NC | NC deed stamp × 500; assessor sale history. **SC: §12-24-70 exempts distressed deeds from stating value, and AcclaimWeb omits consideration from its GridResults JSON. This is structural, not a bug** | ATTOM, PropStream $99/mo | FREE-AUTOMATED (NC) / PAID (SC bulk) |
| D2 | $/sqft | Derived | NC: computable (price from stamps + sqft from CAMA). **SC: not computable free, since both SaleAmount and LivingArea are blank across every free SC GIS layer** | Paid county CAMA extract | FREE-AUTOMATED (NC) / PAID (SC) |
| D3 | Rent comps | Partial | **HUD FMR API (verified: returns 401 without a token, so a free registration token is required)**; **Census ACS B25064 median gross rent (verified: "Missing Key", free key required)**. Both are area medians, not unit-level | RentCast ~$50/mo, Zillow Rent AVM | FREE-AUTOMATED (with free key, area-level) / PAID (unit-level) |
| D4 | **Cap rates** | Not published | **NONE free.** Cap rate requires actual NOI, which is private | CBRE/Trepp/CRED-iQ, paid subscription | PAID |
| D5 | Absorption rate | Derived from MLS | No compliant free source | MLS via licensee; Redfin Data Center (aggregate, free-ish, ToS-limited) | PAID |
| D6 | Months of inventory | Derived from MLS | Redfin/Realtor market data downloads publish metro/county aggregates free | MLS | FREE-AUTOMATED (aggregate) |
| D7 | List-to-sale ratio | Derived from MLS | Same as D6, aggregate only | MLS | FREE-AUTOMATED (aggregate) |
| D8 | Price trend / appreciation | Yes | FHFA House Price Index (free, county level); Zillow ZHVI research files | ATTOM | FREE-AUTOMATED |
| D9 | Buyer activity / cash-buyer counts | Yes | Grantee-name frequency in ROD deed index (count LLCs buying repeatedly). **This is your best free buyer-intel play and it is underused** | PropStream buyer search | FREE-AUTOMATED |
| D10 | **Structured investor buy-box** | Not published | **NONE. No free, public, scrapeable structured buy box exists.** Land buyers name counties as SEO text; builders take land by relationship. You built a curated static registry, which is the correct answer | none sells this | PHYSICALLY-UNRECORDED |
| D11 | Rental vacancy rate | Yes | Census ACS (free key) | n/a | FREE-AUTOMATED |
| D12 | Population / migration / new permits | Yes | Census ACS + Census Building Permits Survey | n/a | FREE-AUTOMATED |

---

## E. The four structural walls, named honestly

These are not code bugs and no budget fixes them:

1. **Live payoff balance (C2) and payment status (C4).** Held only by the servicer, changes mid-month, PII. No vendor at any price sells the real number. Everything else in the market, including PropStream and ATTOM, is modeling it from original principal plus amortization, exactly as you would.
2. **SC recorded sale price (D1, D2, A49).** SC Code §12-24-70 exempts foreclosure, deed-in-lieu, and spousal transfers from stating value. Distressed deeds carry no recoverable stamp *by statute*. Combined with blank `LivingArea`/`SaleAmount` on every free SC GIS layer, SC $/sqft comps require a paid county CAMA extract or per-parcel qPublic cards. Do not rebuild this expecting a free win.
3. **Interior condition (A36, A37).** No record is ever created for a non-listed house. This is the field that most determines your spread and it is the one you can least obtain remotely. It is REQUIRES-PHYSICAL-VISIT and always will be.
4. **Credit, income, employment (B22, B23, B24).** FCRA makes these legally unusable for deal-sourcing regardless of whether a vendor would sell them. Treat as sealed.

Secondary but worth naming: **utility shutoff (C16)** is exempt from public records in both states; **HOA dues (A25)** exist only in a resale certificate a transaction party orders; **eviction rosters (C19)** genuinely do not exist as a bulk feed anywhere in SC, confirmed by driving the roster endpoint directly.

## F. Where the cheap wins actually are

Ranked by field-fill gained per hour of work, from what is already built but dormant:

1. **Run the Spartanburg DOT-OCR at scale.** C1 goes from 0.0% to something real. Zero new code, just raise the cap and drop the grade gate.
2. **Widen the NC Judgment JSON filter to `FAM - Divorce`.** C18 goes from 1 lead to a live statewide feed, one config line, carry the 50B exclusion.
3. **Fix `_query_parcel` normalization.** Not a new field, but it unlocks 4,054 leads that currently carry *no* A2, which cascades into A6 through A50.
4. **Add the free federal enrichers you are not calling at all:** FEMA flood (A17), USDA soil (A18), USGS slope (A19), EPA contamination (A31), NPS historic (A32), BOP incarceration (B16). All six verified keyless today, all six are pure additive coverage, and none of them exist on your board.

## G. Verified vs unverified

**Verified live by direct probe during this task (HTTP 200, keyless unless noted):** FEMA NFHL MapServer; EPA Envirofacts efservice; USDA Soil Data Access post.rest (POST SQL, returned real mapunit rows); USGS EPQS (returned 2084.9 ft); BOP inmate locator (returned real records, `"Captcha":false`); NPS NRHP MapServer; NC voter file bulk zip (~498MB); Urban Institute education data API; FCC census-block API; CourtListener REST v4 (133 results, ncwb); NC OneMap parcels layer.

**Verified as gated:** HUD FMR API returns `{"error":"Unauthenticated"}` (free token required); Census API returns "Missing Key" (free key required); NC SoS returns Cloudflare 403 to plain curl (repo notes stealth clears it as a JS challenge, which I did not re-test).

**Unverified:** MERS ServicerID returned a 503 maintenance page at probe time, so its behavior is unconfirmed today. `hazards.fema.gov/gis/nfhl/...` is behind a WebSEAL 404; use the `/arcgis/` path above instead. Pricing figures for PropStream ($99 / $199 / $699 per month), ATTOM (self-serve from ~$90 to $95/mo, enterprise $10k to $100k+/yr), skip tracing ($0.07 to $0.25 per record; TLOxp from ~$100/mo; Accurint from ~$200/mo) come from vendor and third-party comparison pages, not from a checkout I completed, and vendor sales-gated pricing moves. Regrid publishes no per-county rate card and is quote-only.

Sources: [PropStream official pricing](https://www.propstream.com/news/how-much-does-propstream-cost), [ATTOM API pricing overview](https://zillapi.com/blog/attom-api/), [Regrid nationwide parcels licensing](https://regrid.com/nationwide-parcels), [skip tracing price comparison 2026](https://batchdata.io/blog/best-skip-tracing-tools-for-bulk-data-processing)

Repo docs that already contain much of the blocker forensics, read-only: `/Users/cashhigh/foreclosure-scraper/docs/blocked_sources_forensic.md`, `/Users/cashhigh/foreclosure-scraper/docs/gap_ledger.md`, `/Users/cashhigh/foreclosure-scraper/docs/free_skip_tracing_options.md`