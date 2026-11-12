# Road to 100 — free / manual alternates for every ROD and tax-delinquency wall

Written 2026-08-12. Scope: for each register-of-deeds (ROD) and tax-delinquency
wall in the NC+SC footprint, the COMPLIANT free or manual alternate that carries
the same data. Free + public only — no CAPTCHA solving, no robots-Disallow
riding, no people-search PII. MANUAL-SAVE lanes are acceptable.

Sourced from `gap_ledger.md`, `ROD_PORTAL_ACCESS.md`, `COUNTY_SYSTEMS_REGISTRY.md`,
`SOURCE_REGISTER.md`, `completeness_taxNC.md`, `completeness_taxSC.md`,
`completeness_matrix.md`, `net_new_source_register.md`. Live-confirmed probes on
2026-08-12 are marked **[LIVE 08-12]**; everything else is flagged with the state
the source docs recorded.

Legend for access method: **GET** open URL · **ArcGIS** REST FeatureServer query ·
**PDF** county-hosted document · **XLSX/Sheet** spreadsheet · **qPayBill** SC
treasurer no-login form · **NCPTS** ncptscloud open JSON · **manual-save** operator
saves a page, offline parser ingests · **built** already a producing scraper.

---

## WALL 1 — Sturgis / Avalon / Catalis multi-county unpaid-tax API (robots Disallow)

`avalon.sturgiswebservices.com` and `d1ebsyxxbc7tep.cloudfront.net` both publish
`User-agent: * / Disallow: /`. The Catalis/Sturgis "Avalon" tax stack is used for
per-parcel balance lookups by **Rutherford, Burke, Cleveland, Lincoln** NC (and
Pickens SC treasurer). The robots wall hides Rutherford's 29,319 delinquent bills.
It is **not** the only path to that data — every affected county has a free
per-county alternate that carries the same delinquent-tax signal (owner, situs,
parcel, amount).

| County | Free alternate carrying the same delinquent data | URL | Access | Signals | State |
|---|---|---|---|---|---|
| **Spartanburg SC** | qPayBill Unpaid+Year=All (1999–2026, incl. `Sold at Tax Sale` status) **+** county delinquent PDF **+** FLC PDFs | `spartanburgcountytax.qpaybill.com/Taxes/TaxesDefaultType4.aspx` · `spartanburgcounty.gov/DocumentCenter/View/11161` | qPayBill / PDF / **built** (`spartanburg_delinquent_tax`, 2,082 rows) | owner, TMS, amount, year, sold-status | fully free, built |
| **Lincoln NC** | County delinquent-advertisement PDF (text layer, Parcel ID + amount) | `lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice` | PDF / **built** (`nc_county_pdf_delinquent_tax`, 1,592 rows) | owner, parcel, amount | fully free, built |
| **Rutherford NC** | NCPTS delinquent tenant (when county posts) **+** newspaper ad via ncnotices.com. Note `rutherford_tax` already ships 6,830 rows from the open county tax-search leg — the robots wall only blocks the *balance* API, not the roll | `bcpwa.ncptscloud.com/Rutherford` · `ncnotices.com` (The Daily Courier) | NCPTS / manual-save / **built** | owner, parcel, amount | roll free; balance API walled (accept the roll) |
| **Burke NC** | NCPTS tenant (valid tenant, currently 0 blobs — auto-lights-up) **+** newspaper ad (ncnotices.com) **+** `BurkeNC_2026_Billing.zip` as owner/mailing/assessed enrichment (NOT distress) | `bcpwa.ncptscloud.com/Burke` · `ncnotices.com` · `burkenc.org/DocumentCenter/View/5147` | NCPTS / manual-save | owner, parcel, amount (roll); owner+mailing+value (zip) | roll pending county post; per-parcel Catalis is reCAPTCHA (skip) |
| **Cleveland NC** | Newspaper ad via ncnotices.com (Shelby Star) **+** `cleveland_tax` foreclosure subset | `ncnotices.com` · `clevelandcounty.com/main/departments/` | manual-save / **built** (`cleveland_tax`) | owner, parcel, amount | full roll = newspaper only; per-parcel Catalis reCAPTCHA (skip) |
| **Pickens SC** (treasurer Avalon SPA) | Multi-year delinquent **ArcGIS** archive (2020→2025) — richer than the SPA, carries owner mailing + amount | `services1.arcgis.com/59960rq18IxUcAVI/.../dqnt_2024`, `.../DelParces_October2025NewsAd` | ArcGIS / **built** (`pickens_delinquent_parcels`, 1,928 rows) | owner, mailing, situs, amount | **[LIVE 08-12]** dqnt_2024 + NewsAd(412) queryable |

**Statewide NC fallback for the newspaper-only counties (Gaston, Cleveland,
Rutherford, Burke, Polk, Transylvania, Mitchell):** `ncnotices.com` (NC Press
Association) — all 100 counties in its filter, keyword/date advanced search, no
CAPTCHA. ASP.NET WebForms, needs `__VIEWSTATE`/`__EVENTVALIDATION` replay.
`nc_notices_counties` already drives this (393+ rows).

---

## WALL 2 — Kofile / qPublic / Acclaim / Aumentum / CCHS / Cott ROD portals (robots / CAPTCHA / WAF)

The county recorder is where deeds-of-trust, lis-pendens, substitutions-of-trustee
and satisfactions are recorded — the primary distress record. The commercial ROD
platforms are walled: Kofile (Oconee, robots Disallow), qPublic/Schneider
(reCAPTCHA), AcclaimWeb (Pickens, image paywall), Aumentum (Buncombe/Gaston,
reCAPTCHA image order), CCHS/Courthouse Computer Systems (Cleveland/Burke/Gaston/
Lincoln subscriber), Cott (Polk/Rutherford, now login). Free alternates:

| Free alternate | Counties (footprint) | URL / entry | Access | Signals | State |
|---|---|---|---|---|---|
| **"The Lookup"** (open, click-through disclaimer, **no** automation-restriction language) | **Clay, Haywood, Yancey NC** (core WNC, held 0 board leads) | `search.<county>deeds.com/index.php?Accept=Accept` then `content.php` (**GET only**) | GET / **built** (`wnc_rod_foreclosure_starts`, reader `enrichment_rod_lookup.py`) | grantor/grantee, doc type (D/T, S/T=foreclosure start, TR/D=REO), book/page, date, TIFF/PDF image | **[LIVE 08-12]** Haywood 200, 41 KB, "The Lookup", DEED OF TRUST present |
| **"Online Record System"** (3-step, index carries a recorded **Amount**) | 8 SC: Abbeville, Barnwell, Berkeley, Colleton, Dorchester, Florence, Georgetown, York | `<host>/NameSearch.php?Accept=Accept` → POST `NamePick.php` → POST `NameDisplay.php` | POST / **built** (`enrichment_rod_name_index.py`) | party, doc type, amount, book/page, date | name-lookup enrichment for all 8; bulk-by-date only Barnwell+Georgetown (both out of core footprint) |
| **qPublic per-parcel CARD** (index free-to-view even where image is paywalled) | Pickens, Oconee SC | `qpublic.schneidercorp.com` per-parcel card | manual / stealth per-parcel | full sale-price + book/page history, heated sqft | manual per-parcel only (bulk = reCAPTCHA) |
| **GIS owner layer (`OWNER1`) as name→property substitute** | all footprint counties with an open parcel layer | county ArcGIS parcel FeatureServer | ArcGIS | owner name → situs + parcel (closes the resolver, not the deed $) | free; the recorder widens the funnel top, GIS resolves the middle |
| **MANUAL-SAVE court lane** (for the ToS/WAF-walled index records — lis-pendens, foreclosure filings) | SC PublicIndex counties + NC eCourts (all 100) | operator accepts disclaimer, saves result page | manual-save / **built** (`scripts/ingest_saved.sh`, "Ingest Saved Court Pages" app) | case#, parties, dates | the compliant answer to the two genuinely-daily walled sources |
| **americanlandrecords.com** (Anderson SC recorder — open, no stated gate) | Anderson SC | `americanlandrecords.com/land-record?countyId=2429` | GET | not yet mapped | **candidate — unmapped**, verify before building |

Do NOT count **Permitium** (`<county>rod.permitium.com`, 18 NC counties incl. Dare/
Davidson/Durham/Iredell/Jackson) as coverage — it is a certified-copy ordering
counter with no name index and no date search. Recorded so the next sweep does not
re-adopt it. **Bertie NC** (`bertiedeeds.com`) is a disclaimer loop, still walled.
**Avery NC** (`averydeeds.com`) is reCAPTCHA, out of scope.

**Wrong-state trap:** `hendersondeeds.com` is Henderson County **KENTUCKY**;
`wilsondeeds.com` is Wilson County **TENNESSEE**. Confirm state before adopting any
`<county>deeds.com` host.

---

## WALL 3 — County delinquent-tax rolls not yet captured

Free per-county source for the delinquent roll (owner + parcel + amount) where not
already producing. NC ads are current-year-only by design; multi-year archives are
essentially unavailable except where a county self-hosts GIS snapshots (Pickens).

| County | Free alternate | URL | Access | State |
|---|---|---|---|---|
| **Oconee SC** | Public Google Sheet (651 rows) **+** ArcGIS DT2023/24/25 | `oconeesc.com/delinquent-tax/sale-list` · `services1.arcgis.com/UOvRn2Rvzysthh3i/.../DT2025` | Sheet / ArcGIS / **built** | **[LIVE 08-12]** DT2025 = 645 rows queryable |
| **Cherokee SC** | County-hosted PDFs (`Item#, NAME, Map#, Description`; no $) | `cherokeecountysc.gov/wp-content/uploads/2023-Delinquent-Tax-List.pdf` | PDF / **built** (`cherokee_delinquent_tax`) | free; un-walled 2026-07 |
| **Union / Laurens SC** | qPayBill Unpaid+Year=All (per-parcel balance ladder) | `uniontreasurer.qpaybill.com`, `laurenstreasurer.qpaybill.com` | qPayBill / **built** | free; advertised list is newspaper-only |
| **Henderson NC** | NCPTS bulk CSV (1993–2026, daily) **+** newspaper HTML archive | `bcpwa.ncptscloud.com/Henderson` · `hendersonvillelightning.com/legal-ads/131-tax-notices.html` | NCPTS / GET / **built** (`nc_ptscloud_delinquent_tax`) | fully free |
| **McDowell NC** | County delinquent-advertisement PDF (text) | `mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf` | PDF / **built** | free; current-year only |
| **Buncombe NC** | County advertisement-of-tax-liens PDF | `media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf` | PDF / **built** (1,155 rows) | **[LIVE 08-12]** 200, 643 KB PDF |
| **Gaston / Polk / Transylvania NC** | Newspaper ad only, via `ncnotices.com`; full 105-369 roll behind SPA portal (Catalis/DevNet/BAS) is a wall — accept the newspaper subset | `ncnotices.com` | manual-save | full roll = WALL; ad subset free |
| **Mitchell NC** | **Wall** — HTTP 523, not an NCPTS tenant, no bulk PDF; WP "tax-lien" tags attach to Commissioner minutes, not the list | — | — | no free bulk route (documented, do not re-chase) |
| **Anderson SC** | **Wall** — ACPASS login-gated; free window is seasonal PostingPro (~Sep 30→sale) + Terry Howe FLC pages | `anderson.postingpro.net` (seasonal) | seasonal / manual | balance = auth wall; equity already strong via other legs |
| **Haywood NC** (HANDOFF gap) | No delinquent-tax host located; The Lookup ROD (Wall 2) covers the deed/foreclosure-start signal instead | `search.haywooddeeds.com` | GET / **built** | tax roll not located; ROD lane live |

---

## WALL 4 — Annual tax-SALE lists (NC upset-bid / SC Forfeited-Land-Commission) — published free every year

These are published free every year and largely already captured. Per footprint
county:

### NC upset bids / tax-foreclosure sales
| Source | Counties | URL | Access | State |
|---|---|---|---|---|
| Kania Law Firm JSON (no auth) | Burke, Cleveland, Lincoln, Rutherford, McDowell NC | `kanialawfirm.com/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id=216745` | GET JSON / **built** (`national.nc_upset_bids`, `law_firms.kania`) | free, built |
| County foreclosure-sale pages | Buncombe, Henderson, Rutherford, Gaston, Polk, McDowell | e.g. `taxforeclosures.buncombenc.gov`, `gastongov.com/669/Tax-Foreclosure-Sales` | GET / **built** | free, built |
| Clerk upset-bid file (dollar debt) | statewide NC | Clerk of Court (not online) | FOIA | debt $ is FOIA-only |

### SC Forfeited Land Commission (buy-direct + peak-distress)
| Source | County | URL | Access | State |
|---|---|---|---|---|
| Spartanburg FLC PDFs (Real + Mobile) | Spartanburg | `spartanburgcounty.gov/DocumentCenter/View/102066` · `/104129` | PDF / **built** (`spartanburg_flc`) | free; republished at same IDs — snapshot |
| Oconee `Assignment_FLC` (189, `FLC_Bid`, `Redeem_Assign`) + Google Sheet | Oconee | `services1.arcgis.com/UOvRn2Rvzysthh3i/.../Assignment_FLC` | ArcGIS / **built** (`oconee_flc_assignment` 585, `oconee_forfeited_land` 454) | free; maps dark ~Oct–Jan (snapshot) |
| Pickens `FLC_2022` layer + FLC list | Pickens | `services1.arcgis.com/59960rq18IxUcAVI/.../FLC_2022` · `co.pickens.sc.us/departments/delinquent_tax` | ArcGIS / GET / **built** | free |
| Horry FLC xlsx (year-stamped) | Horry | `horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx` | XLSX / **built** (`horry_flc`) | **[LIVE 08-12]** 200, xlsx |
| Terry Howe auctions (Laurens/Spartanburg/Anderson FLC) | Laurens, Spartanburg, Anderson | `terryhowe.com/wp-json/wp/v2/auctions?per_page=100` | GET JSON / **built** (`terry_howe_flc`) | free |
| `sc_flc` multi-county | Spartanburg, Anderson + | `spartanburgcounty.gov/216/Tax-Collector`, `andersoncountysc.org/.../treasurer/` | GET / **built** (44 rows last run) | free |
| Union / Cherokee FLC | Union, Cherokee | in-person/office only | manual | **no free published list** — office contact only |

**Sold-but-unredeemed (peak distress):** no SC county publishes a standalone list,
but **Spartanburg qPayBill** exposes `Status = "Sold at Tax Sale"` under
`PaidStatus=Unpaid` per parcel with amount + year — the one free systematic
substitute. SC redemption is 12 months.

---

## Walls with NO free alternate (accept / FOIA / manual only)

| Wall | Why | Compliant fallback |
|---|---|---|
| Rutherford Sturgis/Avalon **balance** API (29,319 bills) | robots Disallow on both hosts | roll is free via NCPTS/newspaper; the *balance* number is not free-obtainable — FOIA Rutherford/Sturgis |
| Anderson SC delinquent **balance** | ACPASS login (account = not public data) | seasonal PostingPro + Terry Howe FLC; equity already strong via other legs |
| Cleveland / Gaston / Polk / Transylvania NC **full 105-369 roll** | Catalis / DevNet / BAS SPA, reCAPTCHA per-parcel, no bulk file | newspaper ad subset via ncnotices.com only |
| Mitchell NC delinquent roll | HTTP 523, not NCPTS tenant, no bulk PDF | none free — documented dead end |
| Union / Cherokee SC FLC list | office/in-person only | manual office contact |
| SC PublicIndex ROD/court records | ToS forbids automated querying | **manual-save lane** (`ingest_saved.sh`) |
| NC eCourts Smart Search (estates, raw divorce) | AWS-WAF escalating CAPTCHA | manual-save lane; NC estates partly via Column |
| Recorded deed sale price on SC exempt deeds | §12-24-70 states no value (ABSENT) | per-parcel qPublic CARD where present |
| NC power-of-sale debt $ | notice legally states only terms/deposit/upset bid | Clerk file = FOIA |
| Live mortgage payoff balance | servicer PII | DOT-image OCR → original principal (estimate only) |

---

## Bottom line

Every ROD and tax-delinquency wall in the footprint has a compliant free or
manual alternate **except** four true dead-ends: the Rutherford Avalon balance
number, the Anderson balance, the Mitchell delinquent roll, and the four NC-SPA
full-roll counties (newspaper subset only). The largest opportunity is that the
alternates for Wall 1 (Sturgis/Avalon) and Wall 2 (walled ROD) are already **built
and producing** or one config away — the free side-channels the operator expected
do exist and are, in most counties, already wired.
