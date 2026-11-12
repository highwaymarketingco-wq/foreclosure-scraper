Research complete. Compiling the signal map.

---

# PRE-FORECLOSURE & FORECLOSURE SIGNAL MAP — NC + SC

**Footprint:** 11 NC + 7 SC counties. **Compliance:** free/public only; walls classified, not defeated.
**Privacy note:** I did not query, and this map does not route through, the Lincoln County `Server_Tables/MapServer/10` layer. Its `TCSSN1`/`TCSSN2` fields are exposed SSN columns. That layer must stay out of every enricher, including as a parcel/address join. Flagging as a live PII exposure worth reporting to Lincoln County GIS.

**Verification legend:** ✅ fetched and confirmed this session · ⚠️ UNVERIFIED (search-result or prior-docs only) · 🧱 wall

---

## PART 1 — NC POWER-OF-SALE, ARTIFACT BY ARTIFACT

NC power-of-sale foreclosure is a **special proceeding (SP)** before the Clerk of Superior Court, not a civil action. Two consequences that matter more than anything else here:

- **There is no recorded "Notice of Default" in NC.** NOD is a Western deed-of-trust-state artifact (CA/WA/NV). Any vendor selling you an "NC NOD list" is relabeling something else. The NC functional analog is the **notice of hearing**, and it is a court filing, not a recording.
- **There is no lis pendens in NC power-of-sale.** G.S. 1-116 lis pendens attaches to *civil actions*. It appears in NC only for judicial foreclosure and for **105-374** tax foreclosure. Same relabeling caveat applies.

| # | Artifact | Statute | Who holds it | Published free? | Lead time before sale |
|---|---|---|---|---|---|
| 1 | Pre-foreclosure notice to borrower | G.S. 45-102 ✅ | Mortgage servicer → borrower, by mail | **No.** Private correspondence. Never filed publicly. | ~110-150 d |
| 2 | Pre-foreclosure information filing | G.S. 45-103 ✅ | Servicer → **NC AOC**, e-filed within 3 business days of #1 | **No. Statutory wall.** | ~110-150 d |
| 3 | SHFPP database | G.S. 45-103 / 45-107 ✅ | AOC (holds), NCHFA (designed it) | **No. Statutory wall.** | n/a |
| 4 | Substitution of trustee | G.S. 45-10 ✅ | **Register of Deeds** (recording required, Ch. 47) | **YES** via county ROD index | **~60-120 d. Earliest free NC artifact.** |
| 5 | Request for notice of sale | G.S. 45-21.17A ✅ | Register of Deeds, indexed in grantor index | **YES** via county ROD index | varies; reveals junior lienholders |
| 6 | Notice of hearing | G.S. 45-21.16 ✅ | Clerk of Superior Court (SP file); served ≥10 d pre-hearing, or posted 20 d | Court file only | ~50-90 d |
| 7 | Clerk SP file (the case) | Ch. 45 Art. 2A | Clerk of Superior Court | Portal ⚠️/🧱; in person free | ~50-90 d |
| 8 | Order allowing sale | G.S. 45-21.16(d) ✅ | Clerk (SP file) | Court file only | ~25-45 d |
| 9 | **Notice of sale** | 45-21.16A (contents) + **45-21.17** (posting/publication) ✅ | Trustee. Posted by sheriff at courthouse ≥20 d; **published weekly ×2 successive weeks**, last pub ≤10 d pre-sale; mailed ≥20 d | **YES — the workhorse.** ncnotices.com + firm calendars | **20-25 d** |
| 10 | Preliminary report of sale | G.S. 45-21.26 ✅ | Clerk, filed within **5 d** after sale. Carries **purchaser + winning bid $** | Court file only | −5 d (post) |
| 11 | Upset bid | G.S. 45-21.27 ✅ | Clerk. **10 d**, ≥5% or $750 deposit; each upset resets the clock | Court file only | −10 d+ |
| 12 | Order for possession | G.S. 45-21.29 ✅ | Clerk | Court file only | post |
| 13 | Final report / account | G.S. 45-21.33 ✅ | Clerk, within **30 d** of proceeds. Includes publication affidavit + service proof | Court file only | post |
| 14 | Trustee's deed | Ch. 47 recording | **Register of Deeds** | **YES** via ROD + excise stamps | post |
| 15 | Deficiency | G.S. 45-21.36 ✅ (offset defense); 45-21.38 (purchase-money bar) | Separate **civil action**, Clerk of Superior Court | Judgment docket ⚠️ | post |

### The two explicit checks you asked for

**Does the NC Commissioner of Banks publish any aggregate or per-filing data? ✅ Effectively NO.**
Fetched `nccob.nc.gov/news-research/publicationsandresearch`. The only foreclosure items are **two legacy narrative reports to the General Assembly** (May 2009, May 2011) on the Emergency Program to Reduce Foreclosures. No ongoing series, no per-filing data, no county breakdown, no current dataset. NCCOB also states it has **no jurisdiction over foreclosure**; SHFPP operationally sits with NCHFA. Treat NCCOB as a dead end for both aggregate and per-filing.

**Does NC AOC publish SP filing counts? ✅ YES, and this is a real find.**
`nccourts.gov/documents/publications/foreclosure-filings` publishes free `.xlsx`, no login. Downloaded and parsed the 2025 file (1.47 MB):

- Sheet `FORE`, header: `CIVIL CASES WITH A HOME OR BUSINESS FORECLOSURE (FORE) FILING, BY FILING DATE THROUGH December 31, 2025, COMPILED January 7, 2026`
- Shape: **County × Year × [All Months + 12 monthly columns]**
- **2006-2025, all 100 counties**, 2,022 rows. All 11 NC footprint counties present (240 footprint rows).
- Annual vintages posted back to 2019 as separate files.
- Caveat stated on the Information sheet: counts **filings, not foreclosures granted**, and the 2018 Data Integrity Initiative affects disposition stats.
- Direct file pattern: `nccourts.gov/assets/documents/publications/foreclosure-2025.xlsx?VersionId=…` (VersionId required).

**What this is and is not:** aggregate only, no per-filing detail, ~1 week compile lag after year end, annual cadence. It cannot generate a lead. It is genuinely valuable as a **denominator**: it tells you exactly how many FORE filings each footprint county had each month, so you can measure your own capture rate per county per month and detect when a scraper silently dies. Given the documented history of silent-death failures (Column API 200+0), a free ground-truth denominator is worth wiring as a QA check.

**Access note on nccourts.gov:** returns 403 to the fetch tool but **200 with an ordinary browser User-Agent**. This is UA filtering, not a WAF or CAPTCHA, and the files are offered for public download. No bypass involved.

---

## PART 2 — NC TAX FORECLOSURE

| Artifact | Statute | Holder | Free? | Lead time |
|---|---|---|---|---|
| Pre-advertisement notice to owner | 105-369 ✅ | Tax collector → owner, mailed **≥30 d** before ad | No | 1-3 yr |
| Collector's report of unpaid liens | 105-369 ✅ | County collector → governing body; **1st Mon Feb** (county), **2nd Mon Feb** (municipal) | Board agenda packet ⚠️ | 1-3 yr |
| **Tax lien advertisement** | **105-369** ✅ | **Published Mar 1 - Jun 30**, courthouse + general-circulation newspaper | **YES.** Owner names alphabetical, parcel description, principal tax $ | **1-3 yr. Best-in-class lead time.** |
| 105-374 mortgage-style action | 105-374 ✅ | Civil action, Clerk. **Complaint itself = lis pendens on filing**, no separate cross-index | Court file; sale ad per Ch.1 Art.29A | 6-18 mo |
| 105-374 commissioner's report / 10-d exceptions + upset | 105-374 ✅ | Clerk | Court file | post |
| **105-375 in rem docket** | **105-375** ✅ | **Certificate docketed with Clerk = valid judgment against the property**, 8%/yr | Judgment docket ⚠️ | 3 mo - 2 yr |
| 105-375 pre-docket notice | 105-375 ✅ | Registered/certified mail ≥30 d; if no receipt in 10 d, **post on property + publish 2 consecutive weeks** | Newspaper leg → **YES** | 3 mo - 2 yr |
| 105-375 execution + sheriff's sale | 105-375 ✅ | Sheriff, **after 3 mo but before 2 yr** from indexing; 30-d notice to parties | Sheriff sale ad → YES | 30 d |

The **105-369 March-June advertisement is the single longest-lead free artifact in the entire NC map.** It names the owner, describes the parcel, and states the dollar amount, and the property may not reach sale for one to three years. It is also the one that overlaps most cleanly with the already-built NC delinquent-tax lane.

---

## PART 3 — SC JUDICIAL FORECLOSURE

SC is 100% judicial. Everything runs through the Court of Common Pleas and is referred to the **Master-in-Equity** (or Special Referee where no MIE sits).

| # | Artifact | Authority | Holder | Free? | Lead time |
|---|---|---|---|---|---|
| 1 | **Lis pendens** | **S.C. Code 15-11-10** ⚠️ | **Clerk of Court**, county where land sits. ≤20 d before complaint; ≥20 d before decree; service within 60 d | Public Index 🧱; **ROD ⚠️ = top open question** | **150-365 d. Best SC artifact.** |
| 2 | Summons & complaint | Rule 3 SCRCP | Clerk of Court | Public Index 🧱 | 150-350 d |
| 3 | Order of reference | Rule 53 SCRCP ✅ | Clerk / MIE | Public Index 🧱 | 120-300 d |
| 4 | Hearing before Master | ✅ | MIE. Notice ≥3 d | MIE calendar ⚠️ | 60-150 d |
| 5 | Judgment / decree of foreclosure | ✅ | MIE, filed with Clerk. Sets **judgment $**, fixes deficiency demanded vs waived | Public Index 🧱; **but see #7** | 30-90 d |
| 6 | Notice of sale advertisement | ✅ | **Published once weekly ×3 weeks** | **YES.** scpublicnotices.com + MIE ad sites | **21 d** |
| 7 | **MIE sale roster** | county practice ✅ | Master-in-Equity office | **YES, and unusually rich in Greenville** | **14-30 d** |
| 8 | Sale day | ✅ | MIE, usually 1st Monday | roster | 0 |
| 9 | **Upset bid / compliance period** | ✅ | **30 d open bidding if deficiency sought; 20 d to comply if waived** | roster | −30 d |
| 10 | Report of sale / confirmation | ✅ | MIE; confirmed if no exceptions within 10 d | Public Index 🧱 | post |
| 11 | Deficiency + appraisal | **29-3-660, 29-3-680, 29-3-700/720, 29-3-740** ✅ | Petition for appraisal **within 30 d after sale**; 3 certified appraisers return in 30 d; appraised-minus-sale offsets or cancels the deficiency; waivable with signed written notice | Court file 🧱 | post |
| 12 | Master's deed | ✅ | ROD | **YES** | post |
| 13 | **FLC (Forfeited Land Commission)** | Title 12 Ch.59 ⚠️ | County FLC / Delinquent Tax | **YES**, per-county lists | separate lane |

### The SC standout: `mie.greenvillejournal.com` ✅

Greenville County's MIE publishes **per-case sale ads**, free, no login, and the field set is better than most paid feeds. Verified on live case `2025-CP-23-02520`:

> case number · plaintiff (Freedom Mortgage Corporation) · **named defendant/borrower** (Braxton Inman) · **property address** (371 Riverdale Rd, Simpsonville SC 29680) · full legal description · **TMS parcel** (0584070129100) · **judgment amount ($328,512.87)** · sale date/time (01/05/2026, 11:00 a.m.) · interest rate (5.875%) · deposit terms · publication dates · plaintiff's attorney · **and a downloadable link to the order and judgment document**

That last item matters. Per prior work, the judgment-dollar field sits at ~1.1% fill and FOIA was the only identified route to it. This site hands over judgment amount **and the underlying order PDF** for free, keyed to TMS, for the largest SC county in the footprint. It also has a `/search-results/` endpoint. This is the highest-value single find in this sweep.

### SC footprint MIE endpoint status ✅

| County | Endpoint | Status |
|---|---|---|
| Greenville | `mie.greenvillejournal.com` + `greenvillecounty.org/masterinequity/Sales.aspx` | **200 / rich** |
| Spartanburg | `spartanburgcounty.org/171/Master-in-Equity` | 200 |
| Anderson | `andersoncountysc.org/master-in-equity/` | 200 |
| Pickens | `co.pickens.sc.us/departments/master_in_equity/` | 200 |
| Oconee | `oconeesc.com/master-in-equity` | **500** (server error, retry) |
| Laurens | `laurenscountysc.org/master-in-equity/` | **000** (no connect; find correct host) |
| Cherokee | `cherokeecountysc.com/master-in-equity/` | **404** (find correct path) |

Four of seven confirmed live. Three need URL discovery, and none of the three failures look like a wall.

### The SC wall, stated honestly 🧱

`publicindex.sccourts.org/Greenville/PublicIndex/` and `sccourts.org/caseSearch/` both return **406**. Independently, **SCACR Rule 610 prohibits automated scraping and commercial bulk redistribution of the Public Index**. The rule is the binding constraint, not the 406. Do not design around either. Everything SC in this map is deliberately routed through MIE rosters, newspaper legals, ROD, and county tax, none of which are Public Index.

---

## PART 4 — PRE-FILING SIGNALS, RANKED BY LEAD TIME

Ranked longest lead first. "Lead" = time before the foreclosure sale.

| Rank | Signal | Lead | Free in footprint? | Where | Status |
|---|---|---|---|---|---|
| 1 | **Property tax delinquency** | **1-3 yr** | **Yes, broadly** | NC: 105-369 ad (Mar-Jun), county collector sites. SC: county delinquent tax + `greenvillecounty.org/appsAS400/TaxSale/` ✅ (2.5 MB list), Spartanburg qPayBill | **BUILT** (~11.9k NC leads; Spartanburg SC solved) |
| 2 | **Probate / death** | 6 mo - yrs | Partial | NC eCourts estates 🧱 permanent. Obituary lane is the workaround | **BUILT** (Gannett Upstate + funeral RSS) |
| 3 | **Code violations** | 3 mo - yrs | **2 of 18 only** | Asheville Accela (stale 2016-18), Gaston EnerGov CSS | **WEAK. Biggest coverage gap.** |
| 4 | **Judgment dockets** | 6 mo - yrs | NC yes / SC no | NC eCourts Judgment Search JSON (POST-only, `405` on GET ✅ = consistent with open API). SC 🧱 Rule 610 | **BUILT (NC)** |
| 5 | **Divorce filings** | 3-18 mo | NC yes / SC no | NC eCourts Judgment Search (same open endpoint) | **BUILT (NC)** |
| 6 | **HOA lien filings** | 3-12 mo | Partial | County ROD lien index | Charleston parsed; **blocked on ROD rebuild elsewhere** |
| 7 | **Assignment of DOT** | 3-12 mo | Yes | County ROD grantor/grantee index | Index yes; **transfer-to-special-servicer classifier not built** |
| 8 | **Substitution of trustee (NC)** | **60-120 d** | **Yes** | ROD, doc type `SUBSTITUTION OF TRUSTEE` / `APPOINTMENT OF SUBSTITUTE TRUSTEE`, G.S. 45-10 ✅. Grantee ∈ {Brock & Scott, Hutchens/Foundation, Shapiro & Ingle, ALAW, Rogers Townsend} | **Spec'd, ~95% reliable. Highest-conviction NC build.** |
| 9 | **Mechanic's / utility / water liens** | 3-12 mo | Partial | ROD lien index; municipal utility liens rarely published | Mechanic's blocked on ROD rebuild; **utility = effectively no free feed** |
| 10 | **Bankruptcy, esp. Ch.13 dismissal** | **30-90 d, very high intent** | **Fee-metered, not free** | PACER; **$30/quarter free allowance** ✅, then metered. PCL needs registered account | **NOT BUILT. Best intent-per-record on the list.** |
| 11 | **Mortgage satisfaction NOT recorded** | not a timing signal | Yes | ROD, absence of release | **BUILT** as `open_mortgages_est = mtg − sat` (a count, never a balance) |
| 12 | **Insurance lapse** | n/a | **NO. Hard wall.** | Force-placed insurance is not recorded anywhere public. No free proxy exists | **Drop it.** Do not spend time here. |

### Notes on the ranking

**#1 is not close.** Tax delinquency fires one to three years before any sale, is free in nearly every footprint county, and is already built. Every other signal is a fraction of that lead.

**#8 is the best unbuilt NC item.** A substitution of trustee naming a known foreclosure firm is a near-certain pre-foreclosure flag, because those firms do not get substituted in unless a power-of-sale is imminent. It is a recorded ROD instrument, so it is free, it precedes the notice of hearing, and grantor = borrower, which means the property-and-equity join already works. Reuses existing AcclaimWeb/lrcpwa adapters.

**#10 is the best unbuilt item overall by intent.** A Chapter 13 dismissal is the single highest-intent event on this list: the automatic stay drops and the previously stalled foreclosure resumes within weeks. PACER is not free at scale, but the $30/quarter allowance covers a meaningful monitoring volume if you query narrowly (footprint districts, Ch.13, dismissal orders) rather than crawling. Worth a scoped pilot.

**#12 should be closed out.** There is no free public insurance-lapse source and no honest proxy. Recording it as a permanent wall stops it from being re-proposed.

---

## PART 5 — FREE PUBLICATION VENUES (the actual pipes)

| Venue | URL | Status | Carries |
|---|---|---|---|
| NC Press Assn public notices | `https://www.ncnotices.com/` | ✅ 200 | NC notices of sale (45-21.17), **105-369 tax lien ads**, 105-375 publication. Free, statewide, keyword search, email alerts |
| SC Press Assn public notices | `https://www.scpublicnotices.com/` | ✅ 200 | SC 3-week sale ads, delinquent tax ads |
| **Greenville MIE ads** | `https://mie.greenvillejournal.com/` | ✅ 200 | **Per-case: borrower, address, TMS, judgment $, sale date, order PDF** |
| NC AOC foreclosure filings | `https://www.nccourts.gov/documents/publications/foreclosure-filings` | ✅ 200 (browser UA) | County×year×month FORE counts, 2006-2025, `.xlsx` |
| NC eCourts Portal | `https://portal-nc.tylertech.cloud/Portal/` | ✅ 200 | Judgment Search JSON open (POST); Smart Search WAF-walled 🧱 |
| Firm calendars | Brock & Scott ✅ 200 · ALAW ✅ 200 · Rogers Townsend ✅ 200 · Hutchens 404 (merged into Foundation, do not dup) · Shapiro 000 | mixed | Notice-of-sale-stage lists |
| SC FLC / tax sale | Spartanburg FLC ✅ 200 · Greenville tax sale ✅ 200 (2.5 MB) | ✅ | Post-tax-sale inventory |
| SC Public Index | `publicindex.sccourts.org` | 🧱 **406 + Rule 610** | Do not automate |
| NCCOB | `nccob.nc.gov/news-research/publicationsandresearch` | ✅ 200 | **Nothing usable.** 2 legacy reports only |

Brock & Scott's list is JS/filter-rendered and rate-limits (`429` on a param probe), so throttle. Hutchens 404s because of the Foundation merger already noted in prior work.

---

## RECOMMENDED BUILD ORDER

1. **SC lis pendens via ROD ⚠️ — test first, highest payoff.** SC Code 15-11-10 puts lis pendens with the **Clerk of Court**, but many SC counties also record/cross-index it at the **ROD**, which is *not* the Public Index and therefore *not* Rule 610 material. If it lands at ROD in the 7 SC counties, that converts the single best SC signal (150-365 days) from walled to free. Test with the existing SC ROD adapters, not guessed URLs. My guessed portal hosts returned 404/000, so this is genuinely unverified and worth one focused hour.
2. **Greenville MIE per-case scraper.** Free judgment dollars plus order PDFs plus TMS, for the largest SC county. Directly attacks the ~1.1% judgment-$ fill that FOIA was previously the only answer to.
3. **NC substitution-of-trustee scraper.** 60-120 day lead, ~95% precision, reuses existing ROD adapters, grantor = borrower so the equity join already works.
4. **AOC foreclosure-filings as a QA denominator.** Cheap. Gives per-county-per-month ground truth to catch silent scraper death.
5. **Fix 3 SC MIE endpoints** (Oconee 500, Laurens 000, Cherokee 404). URL discovery, not walls.
6. **Scoped PACER Ch.13-dismissal pilot** inside the $30/quarter allowance.

## CLOSED AS WALLS (stop re-proposing)

- G.S. 45-103 pre-foreclosure filings / SHFPP database: **statutory** access limit to AOC, NCHFA, and clerk. Not a technical wall, cannot be engineered around.
- NCCOB: publishes no aggregate and no per-filing foreclosure data.
- SC Public Index: 406 plus Rule 610 prohibition on automated scraping and commercial bulk redistribution.
- NC eCourts estates: permanent wall (confirmed in prior work).
- Insurance lapse: no free public source, no honest proxy.
- "NC Notice of Default" and "NC power-of-sale lis pendens": **these artifacts do not exist.** Any list sold under those names is mislabeled.