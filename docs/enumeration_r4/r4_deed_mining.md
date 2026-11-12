# DEED / INSTRUMENT-TYPE MINING — Anderson SC + 18-county ROD capability matrix

All probes run live 2026-08-03. No CAPTCHA/WAF was defeated; no login was created; no disclaimer click-through was accepted on my behalf (see Compliance).

## HEADLINE CORRECTIONS TO THE PREMISE

Four load-bearing claims in the task did not survive verification.

1. **`acpass.andersoncountysc.org/robots.txt` returns `User-agent: * / Disallow: /`.** The endpoint is keyless and auth-free, but the operator has posted a blanket crawl exclusion. This is a robots wall, not a technical one — I classified it and kept verification to ~50 hand-paced requests rather than designing a sweep. **This is an operator policy decision, not mine to make.** Same pattern on Logan (Spartanburg, Laurens, McDowell, Mitchell), Tyler PublicSearch (Oconee), Cott RecordRoom (Union), and CCHS `us4` (Henderson, Lincoln).
2. **The "Amount" field is empty.** Verified across 8 detail pages spanning DEED, MORT, HOA LIEN, and COURT ORDER. The label renders; the value is blank on every sample. This matches the repo's existing finding (`blocked_sources_forensic.md:175`): the ROD index carries type/lender/date/book-page only; `$` lives on the scanned image.
3. **PR / EST role tags were not observed.** Across the same 8 detail pages the only role tags emitted are `GRANTOR`/`GRANTEE` (deeds, liens, orders) and `MORTGAGOR`/`MORTGAGEE` (mortgages). No `PR`, `EST`, `EXECUTOR`, `HEIR`, `TRUSTEE`, or `ADMIN*`. The estate signal at Anderson is carried in the free-text `DESCRIPTION`, not a role tag.
4. **"144 codes" is a legacy vocabulary, not 144 usable facets.** I tested 38 of the 144 over a 24-month window: **16 return rows, 22 return zero.** And the specific distress types the task named largely have **no code at all** in the dropdown.

**Project memory is right for the wrong reason.** The "lien and distribution-deed mining is BLOCKED pending a ROD rebuild" note should NOT be flipped to open. It is blocked at Anderson for a harder reason than a rebuild: **the instruments do not exist in this ROD.**

| Type the task asked for | Anderson status |
|---|---|
| HOA lien | **193 — LIVE**, the one real win |
| Mechanics lien | **No code exists** (SC §29-5-90 allows ROD *or* Clerk; Anderson routes to Clerk) |
| Tax lien / federal tax lien | **No code exists** |
| Lis pendens | **No code exists** — SC LP is Clerk of Court, §15-11-10 |
| Foreclosure deed | **No code** — recorded as generic `DEED`, and §12-24-40(13) makes it value-exempt |
| Deed of distribution | **No code** |
| Deed in lieu | **No code** — also §12-24-40(13) exempt |
| Bankruptcy | 043 BANKR / 055 BKR exist → **0 rows in 24 months** |
| Guardianship / conservatorship | 102 / 097 / 099 / 085 exist → **0 rows in 24 months** |
| Satisfaction | **LIVE** via 007 / 064 / 110 / 184 (018, 040, 118 are dead) |
| Substitution of trustee | **Cannot exist.** SC is a judicial-foreclosure mortgage state — no deed of trust, no trustee. NC-only instrument. |
| Notice of default | **No code exists** |
| Mobile-home affidavits | **132 / 135 — LIVE** |

---

## 1. MECHANICS — verified query shape (Anderson ACPASS)

Search form (source of the 144-code `QryType` dropdown):
`https://acpass.andersoncountysc.org/deeda.cgi?SearchType=L` — HTTP 200, 39,725 bytes, one `<select name="QryType">` with exactly 144 `<option>` values.

Result page: `POST https://acpass.andersoncountysc.org/deedmain.cgi`
`QrySrchType=L&QryName=&QryFromDate=MM/DD/YYYY&QryToDate=MM/DD/YYYY&QryType=NNN&Submit=Submit`

Three mechanics the premise missed:

- **A type code is mandatory.** `QryType=` empty returns the error page, 0 rows. There is no type-less date sweep — you must iterate codes.
- **Hard 25 rows/page with cursor pagination.** The 25-row page carries hidden `daten` (last file date, `YYYYMMDD`) and `instrnon` (last instrument no.). Next page is a **different endpoint**:
  `POST https://acpass.andersoncountysc.org/dedtypen.cgi`
  `searchtype=L&searchinstr=193&searchbegdate=20250101&searchenddate=20261231&daten=20250204&instrnon=250002630`
  (`dedtypep.cgi` = previous.) Verified: page 2 of code 193 returned a fresh 25 rows and a new cursor. **Without this, the premise's "25 rows" is page 1 of an unknown total — the 01/01/2025–12/31/2026 HOA query truncates at 2/04/2025.**
- Detail: `GET https://acpass.andersoncountysc.org/deddetail1.cgi?instryearnbr=L{year}{instr}` → Inst#, File Date, Amount (empty), Type, Book/Page, Last Modified, party list with role tags, DESCRIPTION, and a free "View Images" link.

## 2. THE 16 LIVE CODES (of 38 tested; 24-month window)

| Code | Label | Page-1 rows | Paged | Distress read |
|---|---|---|---|---|
| **193** | HOA LIEN | 25 | Y | **Delinquent dues + street address in DESCRIPTION.** The one clean net-new facet. |
| **195** | COURT ORDER | 17 (finite) | n | **`ORDER ESTABLISHING HEIRS`, `ORDER DETERMINING HEIRS`, `ORDER QUIET TITLE`.** Highest value per row on the whole board. |
| **132** | MH AFF CERT | 25 | Y | Mobile-home affidavit of affixation |
| **135** | MH SEV AFF | 2 (finite) | n | MH severance — chattel conversion, pre-move |
| **189** | MORTMODIFY | 25 | Y | **Loan modification = recorded workout.** Closest thing to a delinquency proxy here. |
| **190** | MORTSUBORD | 25 | Y | Subordination — refi/2nd-lien stacking |
| **007** | MORT SAT | 25 | Y | Satisfaction (free-and-clear detection) |
| **064** | CANCEL | 25 | Y | Cancellation |
| **110** | MORT REL | 25 | Y | Release |
| **184** | MISC HOA SAT | 25 | Y | HOA lien satisfied — **negative signal, use to suppress 193** |
| **045** | MORT ASI | 25 | Y | Assignment — servicer transfer |
| **016** | ASSIGN | 25 | Y | Assignment (generic) |
| **020** | POA | 25 | Y | Power of attorney — incapacity / absentee owner |
| **036** | NOTICE | 24 (finite) | n | Mixed notices |
| **002** | DEED | 25 | Y | Chain of title |
| **003** | MORT | 25 | Y | New mortgage |

**Dead (0 rows, 24 months):** 018 SAT, 025 RELEASE, 027 ASSIGNMENT, 040 REL&SAT, 041 REV POA, 043 BANKR, 044 MORTGAGE, 053 PJ, 055 BKR, 062 SUB, 066 LIST, 074 NOT, 081 DECREE, 082 ASSENT, 085 CONSERV, 097 CONSER, 099 CONSERSHIP, 102 GUARDSHIP, 116 MORT REL NF, 118 SAT DEED, 122 MORT NF, 175 M UCC MH, 186 MORT SUB.

Full 144-code dump: `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/and_deeda.cgi_SearchType_L.html`

## 3. PER-COUNTY ROD CAPABILITY MATRIX — date+type sweep WITHOUT login

The question was "which support date-range + type query without a login." **Answer: one, and it is gated by a terms click-through.**

| County | Platform | Query-ready URL | Date+type sweep, no name? | robots.txt | Access | NEW/SCRAPED |
|---|---|---|---|---|---|---|
| **Anderson SC** | ACPASS (county CGI) | `POST https://acpass.andersoncountysc.org/deedmain.cgi` + `dedtypen.cgi` | **YES** — only one verified | **`Disallow: /`** | Keyless, no auth | **NEW** (mechanics fully mapped) |
| **Pickens SC** | Harris AcclaimWeb | `https://www.pickensscrod.us/AcclaimWeb/search/SearchTypeDocType` | **YES (structurally)** — dedicated DocType+date search exists | **none (no robots.txt)** | 302 until `POST /AcclaimWeb/Search/Disclaimer` `disclaimer=true`. **I did not accept.** | SCRAPED (`rod/acclaim.py`) |
| **Buncombe NC** | Aumentum eSearch v4 | `.../protected/v4/SrchName.aspx` | **NO** — guest menu is *Quick Name Search only*; name required | none (404) | Guest OK w/ cookie jar (`Guest User` confirmed) | SCRAPED |
| **Polk NC** | Cott/Aumentum v4 | `https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/SrchName.aspx` | **NO** — guest apps: Indexed Records / Property Check / Quick Name Search | none (404) | Guest OK | SCRAPED |
| **Rutherford NC** | Cott/Aumentum v4 | `.../NCRUTHERFORDEXTERNAL/...SrchName.aspx` | **NO** | none (404) | **302 → `/User/Login.aspx`. LOGIN WALL** — contradicts docs | SCRAPED (dead) |
| **Cleveland NC** | CCHS classic ASP | `us5.../clevelandnc/searchonline.asp` | **NO** | none (404) | **HTTP 404 — search decommissioned** | dead |
| **Burke NC** | CCHS | `us5.../burkenc/searchonline.asp` | **NO** | none (404) | **HTTP 404 — decommissioned** | dead |
| **Henderson NC** | CCHS | `us4.../hendersonnc/searchonline.asp` | **NO** | `Disallow: /` | **HTTP 404 — decommissioned** | dead |
| **Lincoln NC** | CCHS | `us4.../lincolnnc/searchonline.asp` | **NO** | `Disallow: /` | **HTTP 404 — decommissioned** | dead |
| **Gaston NC** | CCHS (new host) | `https://gastonnc.courthousecomputersystems.com/` | Unknown — 128 KB SPA, needs XHR discovery | none (404) | 200, no login | SCRAPED (adapter mispointed) |
| **Spartanburg SC** | Logan "The Lookup" | `https://search.spartanburgdeeds.com/index.php` | Unknown | **`Disallow: /`** | 200; repo reports 0 rows for all search types | SCRAPED |
| **Laurens SC** | Logan (older) | `https://search.laurensdeeds.com/NameSearch.php` | **NO** — `search_type=Standard`, name mandatory | **`Disallow: /`** | 200, no login | SCRAPED |
| **McDowell NC** | Logan | `https://search.mcdowelldeeds.com/` | Unknown | **`Disallow: /`** | **Recovered from HTTP 500 → 200**, disclaimer gate | SCRAPED |
| **Transylvania NC** | Logan | `https://search.transylvaniadeeds.com/` | Unknown | **none (404)** | **Recovered 500 → 200**, disclaimer gate. Only robots-clean Logan county | SCRAPED |
| **Mitchell NC** | Logan | `https://search.mitchelldeeds.com/` | Unknown | **`Disallow: /`** | 200 | SCRAPED |
| **Union SC** | Cott RecordRoom | `https://recordroom.cottsystems.com/unionsc/guest/Search/records` | Unknown | **`Disallow: /` + `Disallow: *.pdf`** | Open via `/guest/`; images pay-per-view | SCRAPED |
| **Cherokee SC** | **Avenu** SC Land Records | `https://www.sclandrecords.com/sclr/` → `countycode` picker (16 counties incl. **Georgetown**) | Unknown — JSP session app, `clickCounty()` bootstrap | none (404) | Open for search; Register/Login only for Fraud Alerts | SCRAPED |
| **Oconee SC** | Tyler PublicSearch | `https://oconee.sc.publicsearch.us/` | n/a | **`Disallow: /`** | **Free-account registration wall** | blocked |

Platform note: the task's list should be corrected — **Kofile is not in this footprint** (Oconee is Tyler PublicSearch), and **Avenu is the Cherokee/Georgetown platform** (`sclandrecords.com`), not a separate vendor.

## 4. RANKING — by lead value and by lead time to sale

**Tier 1 — earliest + actionable**
1. **Substitution of trustee (NC, G.S. 45-10)** — genuinely the earliest free NC mortgage signal, plausibly 60–120 days pre-sale (directional; the statutory floor is 45-21.16 notice-of-hearing 10 days + ~30 to sale + 10-day upset). **But it is not harvestable in this footprint today:** it cannot exist in SC at all, and all 11 NC counties are name-only guest (Buncombe/Polk), login-walled (Rutherford), decommissioned (Cleveland/Burke/Henderson/Lincoln), an unmapped SPA (Gaston), or Logan behind a disclaimer with 2 of 3 robots-excluded. Treat the 60–120 day claim as **true-but-unreachable**, not a build target.
2. **HOA lien (193)** — fires on 60–120 days of unpaid dues, well before any mortgage default, and uniquely ships a **street address inline**. Best Anderson facet by a distance.
3. **MORTMODIFY (189)** — a recorded modification is proof of a completed workout, i.e. proof the borrower *was* delinquent. The only Anderson delinquency proxy.

**Tier 2 — high value, low volume, no timing pressure**
4. **COURT ORDER (195)** — `ORDER ESTABLISHING/DETERMINING HEIRS` is a heir-property lead with the estate already adjudicated; `ORDER QUIET TITLE` flags a title defect. 17 rows in 24 months, near-100% qualified.
5. **POA (020)** — incapacity/absentee proxy, no sale clock.
6. **MH AFF CERT / MH SEV AFF (132/135)** — severance especially: chattel conversion usually precedes a move.

**Tier 3 — enrichment, not leads**
7. **MORT SAT / CANCEL / MORT REL (007/064/110)** — the free-and-clear detector. Per `completeness_deeds.md`, free-and-clear is proven by the *absence* of a satisfaction, so these are a suppression list, not a lead list.
8. **MORT ASI / ASSIGN (045/016)** — transfer to a special servicer is a pre-default tell, but the index does not name the transferee type without opening the image.
9. **MISC HOA SAT (184)** — pure suppression against 193.

## 5. THE STRUCTURAL POINT

`completeness_deeds.md` already states the trap and the live probes confirm it: **in NC, judgments, mechanics liens, HOA liens, federal tax liens and lis pendens are docketed with the Clerk of Superior Court, never the ROD** (G.S. 44A-12, 47F-3-116, 44-68.12, 1-116). **In SC, lis pendens is Clerk of Court** (§15-11-10). So the distress instruments the task set out to mine are, in 17 of 18 counties, *in the wrong building* — and in the 18th (Anderson) most of them have no code. The court lane the engine already runs (NC eCourts Judgment Search JSON) is not a fallback for ROD mining here; it is the correct primary.

The honest net-new yield from this whole avenue is: **Anderson HOA LIEN (193), COURT ORDER (195), MORTMODIFY (189), and the MH pair (132/135)** — pending an operator decision on the `Disallow: /`.

## COMPLIANCE

- No CAPTCHA, WAF, login, or paywall was bypassed. Rutherford (login) and Oconee (registration) were classified and abandoned.
- I did **not** accept the AcclaimWeb or Logan terms disclaimers — accepting terms on your behalf needs your say-so, not a task instruction. `rod/acclaim.py` already handles Pickens if you want it.
- **Six hosts carry `robots.txt Disallow: /`**: Anderson ACPASS, Spartanburg, Laurens, McDowell and Mitchell (Logan), Oconee (Tyler), Union (Cott), Henderson/Lincoln (CCHS `us4`). Flagging, not deciding.
- No SSN, DOB, or comparable sensitive PII was encountered or requested. Fields observed are standard public-record: party names, property descriptions, book/page, instrument numbers.

Scratchpad evidence (raw HTML for every probe): `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/`