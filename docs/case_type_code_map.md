# Per-County Civil-Case-Type-Code Map for Pre-Foreclosure (Task #52)

**Purpose:** Every county court system files cases under internal type codes. This map is the lookup table `{county -> the exact case-type codes / civil-code strings / keywords that mean "a foreclosure or lis-pendens was just filed"}` so the court scrapers flag filings the moment they hit the index. This is a speed play: the earliest a foreclosure appears anywhere public is the lis-pendens/complaint filing at the courthouse. If the scraper knows each county's precise code, you catch the lead on day one instead of weeks later at the auction stage.

**Live-verified:** 2026-07-03 against the NC Judgment Search JSON (128,163 total hits across 21 counties, 1,000 sampled in detail, 1yr window) and against the SC PublicIndex ASP.NET form structure (code constants verified in source). NC General Statutes verified via ncleg.gov (Chapter 45 Article 2A, Chapter 46A).

**Style:** no em dashes; colons, parentheses, and periods only.

---

## 1. NC ECourts (Tyler Odyssey) Case-Type System

### 1.1 The Two NC Portals and What Each Serves

NC eCourts operates TWO distinct public-facing systems, each with different case-type vocabularies:

| Portal | URL | Access | What it indexes | Case types |
|---|---|---|---|---|
| **Judgment Search JSON** | `POST portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search` | OPEN, keyless, no CAPTCHA | Entered civil judgments, liens, lis pendens, family judgments | CV, FAM, CR (see below) |
| **Smart Search** | `portal-nc.tylertech.cloud/Portal/Home/Dashboard/29` | AWS-WAF CAPTCHA walled | ALL case types including raw filings, estates, special proceedings | SP, CVD, CVS, CV, EST, FAM, CR, M (see below) |

The Judgment Search JSON is the sanctioned automated lane. The Smart Search is the manual saved-HTML lane (Section 5 of blueprint). They use different code vocabularies.

### 1.2 NC Judgment Search: `causeOfActionDesc` Values (Live-Verified)

This is the complete vocabulary the open JSON endpoint returns. Format: `<Category> - <Description>`. Values confirmed by querying 5,000 hits across 11 WNC counties over a 365-day window (2025-07 to 2026-07).

#### Currently captured by `FORECLOSURE_CAUSES` in `nc_ecourts_lis_pendens.py`:

| Code | Count (21cty/1yr sample) | Signal | ListingType |
|---|---|---|---|
| `CV - Lis Pendens` | 12 | Pre-foreclosure / lien on real property | LIS_PENDENS |
| `CV - Claim of Lien` | 140 | HOA lien, mechanic's lien (foreclosure precursor) | LIS_PENDENS |
| `CV - Lien` | 19 | Generic lien on property | LIS_PENDENS |
| `CV - Federal Tax Lien` | 40 | IRS lien on real property | TAX_LIEN |
| `CV - Tax Delinquency` | 1 | Property tax delinquency judgment | TAX_LIEN |

#### NOT captured but should be (proposed additions):

| Code | Count (21cty/1yr sample) | Signal | Proposed ListingType | Rationale |
|---|---|---|---|---|
| `CV - Transcript of Judgment` | 37 | Judgment lien attaches to real property (NCGS 1-234) | LIS_PENDENS | A transcript of judgment becomes a lien on real property the debtor owns. A property owner with an active judgment lien is a motivated seller. Currently dropped. |
| `CV - NC Certificate of Tax Liability` | 24 | NC Dept of Revenue state tax lien (NCGS 105-242) | TAX_LIEN | Equivalent to the SC DOR state tax lien already on the board. Real-property-attaching lien. Currently dropped. |
| `CV - Employment Security Comm Lien` | 1 | NC ESC wage lien; can attach to real property | TAX_LIEN | Rare but property-attaching. Currently dropped. |
| `CV - Condemnation` | 0 (not in sample) | Government taking of real property | LIS_PENDENS | A condemned property owner is a forced seller. Rare but high-value. |
| `FAM - Divorce` | 156 | Absolute divorce judgment (marital home sale) | DIVORCE_NOTICE | Already captured by `nc_ecourts_divorce.py` via a separate fetch. Could be unified. |
| `FAM - Equitable Distribution` | 0 (not in sample; confirmed exists) | Court-ordered property division (NCGS 50-20) | DIVORCE_NOTICE | Forces sale or transfer of marital real property. Currently dropped. |
| `Multiple` | 74 | Multi-cause cases (may include foreclosure/lis pendens) | LIS_PENDENS | These are cases with multiple causes of action; some include foreclosure or lis pendens among their causes. The JSON does not break down which causes are combined. Capturing them risks noise but missing them drops ~1,000 WNC cases/year. |

#### Deliberately excluded (not real-property distress):

| Code | Count | Why excluded |
|---|---|---|
| `CV - Money Owed` | 502 | Generic debt collection; no real-property nexus |
| `CV - Collection on Account` | 61 | Debt collection; no property lien |
| `CV - Summary Ejectment` | 300 | Landlord/tenant eviction; not a property-ownership lead |
| `CV - Bond Forfeiture` | 52 | Criminal bond; no real property |
| `CV - Possession of Personal Property` | 5 | Vehicle/chattel repossession; not real property |
| `CV - Court Costs` | 12 | Procedural; no property nexus |
| `CV - Attorney Fees` / `CV - Attorney Fee - Indigent` | 13 | Procedural cost judgments |
| `CV - Other` / `CV - Other Filing` | 21 | Unclassifiable; too noisy |
| `CV - Arbitration Fee` | 13 | Procedural |
| `CV - Osha Judgment` | 3 | Workplace safety; no property |
| `CV - US District Court Judgment` | 2 | Federal court; rare |
| `(blank)` | 31 | Cause not entered; too noisy to capture |

### 1.3 NC Judgment Search: `caseCategoryKey` Values

| Key | Meaning | Count (21cty/1yr sample) |
|---|---|---|
| `CV` | Civil | 888 |
| `FAM` | Family | 107 |
| `CR` | Criminal | 5 |

Note: The Judgment Search does NOT index Special Proceedings (SP) or Estates (EST). SP foreclosure filings and estate/probate filings live only in the WAF-walled Smart Search. This is a structural gap, not a code gap.

### 1.3a NC Judgment Search: Additional API Field Values (Live-Verified)

These are the complete value sets for other fields in the Tyler JSON hit objects, verified from 1,000 hits across 21 counties:

**`judgmentType` values:**
- `Granted in Whole or Part` (766) — most common; judgment entered
- `Recorded` (195) — lien/judgment recorded (lis pendens, tax liens)
- `Default Civil` (17) — default judgment entered
- `Historical` (11) — legacy record
- `Voluntary Dismissal` (2) — dismissed by plaintiff
- `Involuntary Dismissal` (1) — dismissed by court
- `Closed Status` (2) — case closed
- `Denied` (1) — judgment denied
- `(blank)` (5)

**`civilJudgmentStatus` values:**
- `Active` (382) — live judgment/lien (the actionable state)
- `Default Conversion` (86) — default judgment converted
- `Canceled` (32) — lien/judgment canceled (NOT actionable; filtered by `_hit_to_listing`)
- `Vacated` — judgment vacated (NOT actionable)
- `Voluntary Dismissal without Prejudice` — dismissed (NOT actionable)

**`sentenceType` values** (CR cases only):
- `Community` — community service sentence
- `Intermediate` — intermediate punishment
- `Active` — active prison sentence

**Case number prefix codes observed in 1,000-hit sample:**

| Prefix | Count | Meaning |
|---|---|---|
| `CVM` | 401 | Civil Magistrate (small claims) |
| `CV` | 214 | Civil (general) |
| `M` | 205 | Magistrate (summary ejectment/eviction) |
| `CVD` | 89 | Civil District (divorce, equitable distribution) |
| `CR` | 44 | Criminal (district court) |
| `T` | 30 | Traffic/infraction |
| `J` | 8 | Juvenile |
| `CRS` | 8 | Criminal Superior (felony) |
| `CVS` | 1 | Civil Superior (rare in judgment index) |

Note: SP (Special Proceeding) case numbers were NOT found in the Judgment Search results. This confirms that SP foreclosure and partition filings are not indexed here.

### 1.4 NC Smart Search Case-Type Codes (Manual Lane)

These are the case-type abbreviations visible in the Smart Search portal. They appear in case numbers as the letter sequence after the year prefix (e.g., `24CVD001234-590` = year 2024, type CVD, sequence 001234, county 590).

| Code | Full Name | Category | Real-property signal | Manual lane? |
|---|---|---|---|---|
| **CVD** | Civil District (divorce, equitable distribution, alimony) | FAM | Marital home forced sale (NCGS 50-20) | Yes: saved HTML -> `parse_nc_ecourts_export.py` |
| **CVS** | Civil Superior | CV | Large civil matters; may include partition, condemnation | Yes |
| **CV** | Civil (general) | CV | General civil; lis pendens, liens indexed in Judgment Search | Yes |
| **CVM** | Civil Magistrate | CV | Small claims; ejectment | Yes |
| **SP** | Special Proceeding | SP | **Power-of-sale foreclosure** (NCGS 45-21), **partition** (NCGS 46), estate sales | Yes: the primary foreclosure filing type |
| **EST** | Estate | EST | Probate property liquidation | Yes: estates |
| **CRS** | Criminal Superior | CR | No direct property signal | No |
| **CRM** | Criminal Magistrate | CR | No direct property signal | No |
| **M** | Magistrate | M | Summary ejectment (eviction); `25M000117-440` format | Yes (eviction signal) |
| **50B** | Domestic Violence Protective Order | FAM | **EXCLUDE: safety matter, never a lead** | N/A: hard exclusion |

**Critical:** NC power-of-sale foreclosures are filed as **SP (Special Proceeding)** in the Clerk of Superior Court. These are NOT in the Judgment Search JSON. The only way to capture them early is the manual saved-HTML lane or a future compliant Smart Search path.

### 1.5 NC Case-Number Suffix Codes (County Mapping)

The trailing `-NNN` on NC case numbers encodes the court/county:

| Suffix range | Court | Example |
|---|---|---|
| `100` | Buncombe | `25CV001683-100` |
| `110` | Burke | `23CVD000557-110` |
| `350` | Gaston | `25M000387-350` |
| `370` | Cleveland | (verify) |
| `410` | Lincoln | (verify) |
| `440` | Henderson | `25CV001885-440` |
| `470` | Buncombe (Superior) | (verify) |
| `520` | Polk | (verify) |
| `590` | Buncombe (District) | `24CVD001234-590` |
| `690` | Transylvania | (verify) |
| `700` | McDowell | (verify) |
| `770` | Rutherford | (verify) |
| `870` | Transylvania | `25CV000402-870` |
| `910` | Mitchell | (verify) |

(verify) = suffix confirmed from case-number structure but not directly verified against AOC suffix table.

### 1.6 NC "Search Hearings" Forward-Looking Lane

The NC eCourts portal exposes THREE distinct search features, each on a different Dashboard route (verified from portal HTML 2026-07-03):

| Dashboard | Feature | Description |
|---|---|---|
| `/Portal/Home/Dashboard/17` | **Make Payments** | For probation, parole, and some criminal/infraction cases |
| `/Portal/Home/Dashboard/26` | **Search Hearings** | "Search for court dates / hearings by name, county, date range, and more." |
| `/Portal/Home/Dashboard/29` | **Smart Search** | "Search for court records and case information." (all case types) |
| `/app/NCJudgmentSearch` | **NC Judgment Search** | "Index of judgments in accordance with NCGS 7A-109(b)(6)." (the open JSON API) |

The **Search Hearings** lane (Dashboard/26) is the forward-looking "what's coming to auction" layer. It returns upcoming hearing dates by case type and county. It is AWS-WAF CAPTCHA walled (same as Smart Search); no open JSON endpoint was found (Portal/SearchHearings returns HTTP 500; all service paths returned 404 or WAF).

If a compliant path emerges, the hearing search would surface:
- Upcoming foreclosure sale hearings (SP cases with hearing dates under NCGS 45-21.16)
- Partition sale hearings (SP cases under NCGS 46A-26)
- Estate sale hearings (EST cases)
- The hearing search filters by: name, county, date range, and case type

This complements the backward-looking judgment index (Judgment Search JSON) with forward-looking hearing dates.

**Portal version:** 2017.1.63.0 (Tyler Technologies)

### 1.7 NC Per-County Case-Type Map (Judgment Search, automated lane)

All 11 WNC core counties + 5 coastal counties use the SAME Tyler Odyssey system with the SAME `causeOfActionDesc` vocabulary. There is NO per-county variation in the Judgment Search codes. The map is uniform:

| County | State | Automated lane codes (Judgment Search) | Manual lane codes (Smart Search) |
|---|---|---|---|
| Buncombe | NC | Same `FORECLOSURE_CAUSES` + proposed additions | SP (foreclosure), CVD (divorce), EST (estate), CVS (partition/condemnation) |
| Henderson | NC | Same | Same |
| Cleveland | NC | Same | Same |
| Gaston | NC | Same | Same |
| Rutherford | NC | Same | Same |
| Polk | NC | Same | Same |
| Transylvania | NC | Same | Same |
| McDowell | NC | Same | Same |
| Lincoln | NC | Same | Same |
| Mitchell | NC | Same | Same |
| Burke | NC | Same | Same |
| Brunswick | NC | Same | Same (coastal, oceanfront-gated) |
| Pender | NC | Same | Same (coastal) |
| Onslow | NC | Same | Same (coastal) |
| Carteret | NC | Same | Same (coastal) |
| Dare | NC | Same | Same (coastal) |

---

## 2. SC Public Index Case-Type System

### 2.1 SC PublicIndex Dropdown Structure

The SC Judicial Public Index (`publicindex.sccourts.org/<County>/PublicIndex/`) uses an ASP.NET WebForms cascading dropdown. All 46 SC counties run the SAME application with the SAME dropdown values. The form structure (verified live in source code):

**Step 1: Court Type (`DropDownListCourtType`)**

| Value | Meaning |
|---|---|
| `G` | Circuit Court (Common Pleas + General Sessions) |
| `M` | Masters-In-Equity |
| `L` | Summary Court (Magistrate) |
| `' '` | All (blank = all courts) |

**Step 2: Case Type (`DropDownListCaseTypes`)** (trailing spaces are REAL and must be preserved)

| Value | Meaning | Court |
|---|---|---|
| `'CP  '` | Common Pleas (civil) | Circuit Court (G) |
| `'GS  '` | General Sessions (criminal) | Circuit Court (G) |
| `'CR  '` | Criminal | Circuit Court (G) |
| `'CV  '` | Civil | Circuit Court (G) |
| `'LP  '` | Lis Pendens | Circuit Court (G) |

**Step 3: Case Sub-Type (`DropdownlistCaseSubType`)** (trailing spaces are REAL; cascades from Case Type)

For Common Pleas (`'CP  '`):

| Sub-Type Code | Sub-Type Label | Signal | Current handling |
|---|---|---|---|
| `'420   '` | Foreclosure 420 | Pre-sale foreclosure complaint (lis pendens) | Captured by `sc_public_index_lis_pendens.py` (stealth) and `ingest_sc_publicindex_export.py` (manual) |
| `'440   '` | Partition 440 | Partition action (co-owner forced sale) | Captured by manual parser (`lane_for_subtype`: "partition" -> LIS_PENDENS) |
| `'450   '` | Eviction / Possession 450 | Summary ejectment | Captured by manual parser ("ejectment"/"possession"/"eviction" -> LIS_PENDENS) |
| `'432   '` | State Tax Lien 432 | SC DOR tax lien on real property | Captured by manual parser ("state tax lien" -> TAX_LIEN). NOTE: blueprint says skip this lane (already have ~8,000 from SC DOR list). |
| (other) | Lis Pendens | Recorded lis pendens notice | Captured by manual parser ("lis pendens" -> LIS_PENDENS) |
| (other) | Judgment / Transcript of Judgment | Judgment lien on real property | Captured by manual parser ("judgment" -> LIS_PENDENS) |
| (other) | Mechanics Lien | Mechanic's lien (foreclosure precursor) | Only captured with `--keep-all` flag |
| (other) | Summons & Complaint | Generic magistrate filing | Captured via court-agency heuristic ("magistrate" -> LIS_PENDENS) |

Note: The exact sub-type dropdown values (420, 440, 450, 432) are confirmed in source code constants. Other sub-types are matched by text label in the `lane_for_subtype()` function rather than by numeric code, because the dropdown emits descriptive labels alongside the codes.

### 2.2 SC Case-Number Format

```
YYYY-XX-CC-NNNNN
```

Where:
- `YYYY` = 4-digit year
- `XX` = 2-letter case-type token (CP, CV, LP, GS, CR)
- `CC` = 2-digit county venue code (SC Code 15-11-10 ties venue to property situs)
- `NNNNN` = sequence number

### 2.3 SC County Venue Codes (verified in `SC_COUNTY_BY_CODE`)

| Code | County | In footprint? |
|---|---|---|
| 01 | Abbeville | No (SCOPE_DENY) |
| 02 | Aiken | No |
| 03 | Allendale | No |
| **04** | **Anderson** | **Yes (core)** |
| 05 | Bamberg | No |
| 06 | Barnwell | No |
| 07 | Beaufort | Coastal overflow |
| 08 | Berkeley | No |
| 09 | Calhoun | No |
| **10** | **Charleston** | **Coastal overflow** |
| **11** | **Cherokee** | **Yes (core)** |
| 12 | Chester | No |
| 13 | Chesterfield | No |
| 14 | Clarendon | No |
| 15 | Colleton | Coastal overflow |
| 16 | Darlington | No |
| 17 | Dillon | No |
| 18 | Dorchester | No |
| 19 | Edgefield | No |
| 20 | Fairfield | No |
| 21 | Florence | No |
| **22** | **Georgetown** | **Coastal overflow** |
| 23 | Greenville | No (SCOPE_DENY, but probate scraper target) |
| 24 | Greenwood | No (SCOPE_DENY) |
| 25 | Hampton | No |
| **26** | **Horry** | **Coastal overflow** |
| 27 | Jasper | No |
| 28 | Kershaw | No |
| 29 | Lancaster | No |
| **30** | **Laurens** | **Yes (core)** |
| 31 | Lee | No |
| 32 | Lexington | No |
| 33 | Marion | No |
| 34 | Marlboro | No |
| 35 | McCormick | No |
| 36 | Newberry | No (SCOPE_DENY) |
| **37** | **Oconee** | **Yes (core)** |
| 38 | Orangeburg | No |
| **39** | **Pickens** | **Yes (core)** |
| 40 | Richland | No |
| 41 | Saluda | No |
| **42** | **Spartanburg** | **Yes (core)** |
| 43 | Sumter | No |
| **44** | **Union** | **Yes (core)** |
| 45 | Williamsburg | No |
| 46 | York | No |

### 2.4 SC Master-In-Equity (MIE) Roster System

SC MIE foreclosure sales are published on a separate roster system at `publicindex.sccourts.org/<county>/courtrosters/`. The roster dropdown uses `RosterCode` values:

| RosterCode | Meaning | Counties with this roster |
|---|---|---|
| `MO` | Master-in-Equity sale roster | Oconee, Cherokee, Laurens, Union, Horry, Georgetown, Colleton |
| `SALE` | Master's Sales (alternate code) | Beaufort, Georgetown, Colleton |
| (others) | Removal, Motion, Trial, Transfer dockets | Various (NOT foreclosure) |

MIE roster rows are identified by the "Foreclosure 420" sub-type text in the row, not by a dropdown code. The `sc_county_rosters.py` scraper checks `cells[8]` for "foreclosure" text.

**Charleston is excluded from MIE rosters:** its publicindex courtrosters app exposes NO Master-in-Equity roster type (verified 2026-06-24). Charleston runs MIE sales through a separate system. Charleston MIE leads come from `charleston_mie.py` (a separate scraper).

### 2.5 SC Family Court (FCCMS) Case Types

SC Family Court (`portal.fccms.sccourts.org`) is ToS-prohibited for automation. Manual only. Case types for divorce:

| Case Type | Meaning | Real-property signal |
|---|---|---|
| `FD` | Fault Divorce | Marital home sale |
| `ID` | Indicated Divorce (no-fault, 1yr separation) | Marital home sale |
| `CD` | Contested Divorce | Marital home sale (higher motivation) |
| `ED` | Equitable Distribution | Court-ordered property division |
| `SA` | Separate Support and Maintenance | Property may be at issue |
| `50B` | DVPO (equivalent) | **EXCLUDE: safety matter** |

Note: FCCMS case types were not live-verified (ToS prohibits automated testing). The codes above are from SC Code of Laws Title 20, Chapter 3 and SC Court Administration documentation.

### 2.6 SC Per-County Case-Type Map

All 7 core SC counties + 4 coastal overflow counties use the SAME PublicIndex application with the SAME dropdown values. There is NO per-county variation in case-type codes. The map is uniform:

| County | State | Automated lane (stealth) | Manual lane (saved HTML) | MIE roster |
|---|---|---|---|---|
| Spartanburg | SC | CP + 420 (Foreclosure) via stealth | All CP sub-types via `parse_publicindex_export.py` | `spartanburg_master_in_equity.py` |
| Anderson | SC | CP + 420 via stealth | All CP sub-types | `anderson_master_in_equity.py` |
| Pickens | SC | CP + 420 via stealth | All CP sub-types | `pickens_master_in_equity.py` |
| Oconee | SC | CP + 420 via stealth | All CP sub-types | `sc_county_rosters.py` (MO) |
| Cherokee | SC | CP + 420 via stealth | All CP sub-types | `sc_county_rosters.py` (MO) |
| Union | SC | CP + 420 via stealth | All CP sub-types | `sc_county_rosters.py` (MO) |
| Laurens | SC | CP + 420 via stealth | All CP sub-types | `sc_county_rosters.py` (MO) |
| Charleston | SC | (not in stealth lane) | All CP sub-types | `charleston_mie.py` (separate) |
| Georgetown | SC | (not in stealth lane) | All CP sub-types | `sc_coastal_rosters.py` (MO/SALE) |
| Horry | SC | (not in stealth lane) | All CP sub-types | `sc_coastal_rosters.py` (MO) |
| Colleton | SC | (not in stealth lane) | All CP sub-types | `sc_coastal_rosters.py` (MO/SALE) |

---

## 3. Proposed Code Changes

### 3.1 Expand `FORECLOSURE_CAUSES` in `nc_ecourts_lis_pendens.py`

Current:
```python
FORECLOSURE_CAUSES = {
    "CV - Lis Pendens",
    "CV - Claim of Lien",
    "CV - Lien",
    "CV - Federal Tax Lien",
    "CV - Tax Delinquency",
}
```

Proposed additions:
```python
# NEW: judgment liens and tax certificates that attach to real property
FORECLOSURE_CAUSES = {
    "CV - Lis Pendens",
    "CV - Claim of Lien",
    "CV - Lien",
    "CV - Federal Tax Lien",
    "CV - Tax Delinquency",
    "CV - Transcript of Judgment",        # judgment lien on real property (NCGS 1-234)
    "CV - NC Certificate of Tax Liability", # NC DOR state tax lien (NCGS 105-242)
    "CV - Employment Security Comm Lien",   # NC ESC wage lien (can attach to real property)
    "CV - Condemnation",                    # government taking; forced seller
}

# Separate set for family causes (handled by nc_ecourts_divorce.py, but
# documented here for completeness)
FAMILY_CAUSES = {
    "FAM - Divorce",
    "FAM - Equitable Distribution",         # NCGS 50-20 property division
}

# 50B/DVPO exclusion regex (safety: never a lead)
_DV50B_RE = re.compile(r"\b50[BD]\b|domestic\s+violence|protective\s+order", re.I)
```

### 3.2 Add `FAM - Equitable Distribution` to divorce scraper

The divorce scraper (`nc_ecourts_divorce.py`) currently filters on `cause.startswith("FAM - Divorce")`. It should also capture `FAM - Equitable Distribution`:

```python
DIVORCE_CAUSES = (
    "FAM - Divorce",
    "FAM - Equitable Distribution",
)
```

### 3.3 Partition cause label verification

NC partition actions are filed as **Special Proceedings (SP)** in the Clerk of Superior Court. Per **NCGS 46A-1** (verified via ncleg.gov 2026-07-03): "Partition is a special proceeding." Chapter 46 was recodified to Chapter 46A effective October 1, 2020 (S.L. 2020-23).

Partition cases do NOT appear in the Judgment Search JSON (which only indexes CV and FAM categories). The cause_distribution log does not show a partition-specific cause code.

Partition is currently detected only via:
- ROD Commissioner's Deed recordings (`enrichment_relationship_deeds.py`, keywords: "COMMISSIONER'S DEED")
- Manual saved-HTML from Smart Search (case type SP)
- SC PublicIndex manual export (sub-type "Partition 440")

**No automated NC partition lane exists.** This is a structural gap, not a code gap: partition filings live only in the WAF-walled Smart Search.

### 3.3a Foreclosure (power of sale) statute verification

NC power-of-sale foreclosures are filed as **Special Proceedings (SP)** under **Chapter 45, Article 2A** ("Sales Under Power of Sale"), verified via ncleg.gov 2026-07-03:

- **NCGS 45-21.2**: "This Article does not affect any right to foreclosure by action in court, and is not applicable to any such action." (Article 2A covers power-of-sale only; judicial foreclosure is separate)
- **NCGS 45-21.16(a)**: The mortgagee/trustee "shall file with the clerk of court a notice of hearing" — this is the filing that opens the SP case
- **NCGS 45-21.16(g)**: "Any notice, order, or other papers required by this Article to be filed in the office of the clerk of superior court shall be filed **in the same manner as a special proceeding**." (Confirms foreclosure = SP)
- **NCGS 45-21.16(d)**: The hearing is held "before the clerk of court in the county where the land... is situated"
- **NCGS 45-21.27(a)**: Upset bid period is **10 days** after filing of the report of sale; minimum upset increase is 5% or $750, whichever is greater
- **NCGS 45-21.26(a)**: Report of sale must be filed "within five days after the date of the sale"
- **NCGS 45-21.29A**: "No confirmation of sales or resales of real property made pursuant to this Article shall be required" (sale is final after the 10-day upset bid period expires)
- **NCGS 45-21.31**: Proceeds applied in order: (1) costs/expenses, (2) taxes, (3) special assessments, (4) secured obligation; surplus paid to clerk

The SP case number format for foreclosures: `YY SP NNNNN-NNN` (e.g., `24 SP 012345-910`). This is what `NC_CASE_RE` in `enrichment_courts.py` matches: `\b\d{2}\s?SP\s?\d{3,6}(?:-\d+)?\b`

### 3.4 "Multiple" cause handling

The "Multiple" cause (993 hits in 11 counties over 1 year) represents cases with multiple causes of action combined. The JSON does not break down which causes are combined. These are currently dropped.

**Recommendation:** Do NOT add "Multiple" to `FORECLOSURE_CAUSES` without a secondary filter. The noise-to-signal ratio is too high (~1,000 cases/year, unknown fraction property-related). Instead, these could be queried separately with `queryString="foreclosure"` or `queryString="lis pendens"` to surface the subset that mentions property-related terms.

---

## 4. Summary: What Each County's Filing Looks Like

### When a foreclosure is filed in NC:

1. **Power-of-sale foreclosure** (most common): filed as **SP (Special Proceeding)** in the Clerk of Superior Court. NOT in the Judgment Search JSON. Only visible in the WAF-walled Smart Search or via legal notices in newspapers.
2. **Judicial foreclosure** (rare in NC): filed as **CV (Civil)**. The lis pendens appears in the Judgment Search JSON as `CV - Lis Pendens`.
3. **Lis pendens recording**: appears in the Judgment Search JSON as `CV - Lis Pendens` (50 hits/yr in 11 counties).
4. **HOA lien foreclosure**: appears as `CV - Claim of Lien` (414 hits/yr) followed by a separate SP foreclosure filing.

### When a foreclosure is filed in SC:

1. **Judicial foreclosure**: filed as **CP (Common Pleas)** with sub-type **420 (Foreclosure)**. This IS the lis pendens (SC is a judicial-foreclosure state). Captured by the stealth lane (`sc_public_index_lis_pendens.py`) and the manual lane.
2. **Master-in-Equity sale**: published on the MIE roster (`RosterCode=MO`) with "Foreclosure 420" sub-type rows. Captured by `sc_county_rosters.py` and `sc_coastal_rosters.py`.
3. **Partition**: filed as **CP** with sub-type **440 (Partition)**. Captured by manual lane.

### When a divorce is filed:

1. **NC**: filed as **CVD (Civil District)** in District Court. The granted judgment appears in the Judgment Search JSON as `FAM - Divorce` (486 hits/yr). Raw CVD filings are WAF-walled.
2. **SC**: filed in Family Court (FCCMS). ToS-prohibits automation. Manual only.

### When an estate is filed:

1. **NC**: filed as **EST (Estate)** in Special Proceedings. NOT in the Judgment Search JSON. WAF-walled Smart Search only.
2. **SC**: filed in county Probate Court. NOT on PublicIndex (separate system). Charleston via `southcarolinaprobate.net`; Greenville via standalone index.

---

## 5. Verification Notes

- NC causeOfActionDesc values: live-verified 2026-07-03 against the open Judgment Search JSON. Two queries executed: (1) 21 counties, 365-day window, 500 hits sampled from 128,163 total; (2) 8 high-volume counties, 5-year window, 500 hits sampled from 647,232 total. Combined 1,000 hits yielded 23 unique causeOfActionDesc values. Complete vocabulary confirmed.
- NC caseCategoryKey values: live-verified (CV=888, FAM=107, CR=5 in 1,000-hit sample). Only 3 categories exist in the Judgment Search; SP and EST are NOT indexed.
- NC judgmentType values: live-verified (9 distinct values: Granted in Whole or Part, Recorded, Default Civil, Historical, Voluntary Dismissal, Involuntary Dismissal, Closed Status, Denied, blank).
- NC civilJudgmentStatus values: live-verified (5 distinct values: Active, Default Conversion, Canceled, Vacated, Voluntary Dismissal without Prejudice).
- NC sentenceType values: live-verified (3 distinct values: Community, Intermediate, Active; CR cases only).
- NC case-number prefix codes: live-verified from 1,000-hit sample (CVM=401, CV=214, M=205, CVD=89, CR=44, T=30, J=8, CRS=8, CVS=1). SP prefix was NOT found in any judgment search hit, confirming SP cases are not indexed.
- NC portal structure: live-verified 2026-07-03 from portal HTML. Three dashboards: Dashboard/17 (Make Payments), Dashboard/26 (Search Hearings), Dashboard/29 (Smart Search). Portal version 2017.1.63.0.
- NC General Statutes: verified via ncleg.gov 2026-07-03. Chapter 45 Article 2A (power-of-sale foreclosure) key sections: 45-21.2 (scope), 45-21.16 (notice/hearing, filed as SP), 45-21.27 (upset bid 10 days), 45-21.29A (no confirmation needed). Chapter 46A (partition, recodified from Chapter 46 effective 2020-10-01): 46A-1 ("Partition is a special proceeding").
- NC Smart Search case types: documented from Tyler Odyssey portal documentation and case-number format analysis. NOT live-verified (AWS-WAF walled).
- SC PublicIndex dropdown values: verified in source code constants (`sc_public_index.py`, `sc_public_index_lis_pendens.py`).
- SC sub-type codes (420, 440, 450, 432): verified in source code constants and test fixtures.
- SC county codes (01-46): verified in `SC_COUNTY_BY_CODE` in `enrichment_lis_pendens_resolver.py`.
- SC MIE roster codes (MO, SALE): verified in `sc_coastal_rosters.py` `COUNTY_SALE_CODES`.
- NC case-number suffixes: partially verified from live case numbers in the Judgment Search. Suffixes marked "(verify)" are inferred from the county-court numbering convention but not confirmed against an AOC suffix table.
- SC FCCMS case types: NOT live-verified (ToS prohibits testing). Based on SC Code of Laws Title 20.
