# "Distressed Property Source Gaps" audit — live-verification results (2026-08-17)

An external strategic audit (`Distressed Property Source Gaps.docx`) proposed several new
lead sources. Strong research, but I VERIFIED each concrete claim live before building — and
most of the "easy wins" turned out walled or marketing-only on inspection. Record so Hermes
doesn't re-chase the dead ones.

| Audit claim | Live-verification result | Verdict |
|---|---|---|
| **Lincoln Co. "Code Violations Archive" ArcGIS layer (TRACKiT/MapServer/8)** | REAL — Feature Layer, **3,465 records**, fields FULLADDR/VIOLATEDESC/VIOLATETYPE/SUBMITDT/NAME/PHONE/EMAIL/STATUS. | ✅ **BUILT** — `counties_nc.lincoln_code_violations` (modeled on henderson_code_violations). Extend the same layer-hunt to the other 16 counties = the real follow-on. |
| **LiensNC.com — "structured goldmine, bypasses ROD"** | Landing loads, but the actual search (`apps.liensnc.com/scr/filing/advancedSearch.html`) **redirects to a login page** ("Please sign in", user/pass). SEARCH is account-gated, not just filing. | ❌ **LOGIN-WALLED** (WONT). Audit overstated. My prior note was correct. |
| **4 missing default-servicing firms: Padgett, McCalla/MRLP, King Law, Riley Pope & Laney** | All resolve, but their public pages are **marketing, not rosters**: Padgett `/foreclosure` = 226KB, 0 addresses/0 dates/0 tables; King & RPL foreclosure URLs 404; MRLP loads its roster in JS/iframe. No scrapeable public sale list found. `salesweb.civilview.com` (the CivilView vendor some trustees post to) loads but needs per-firm/county navigation. | ❌ **NOT cleanly buildable** — no public rosters. CivilView portal = a maybe for deeper digging. |
| **NC 45-day pre-foreclosure (SHFPP / NCHFA Connect)** | Real program, but borrower PII is restricted; only aggregate/quarterly reports are public. | ~ **MACRO-only** — a volume barometer, not a per-lead source. |
| **Municipal utility arrearages / SC setoff-debt (Spartanburg Water, Gastonia)** | Real collection programs, but the public data trail is thin (board minutes, occasional recorded utility liens); no clean per-property feed. | ~ **LOW-yield / manual.** |
| **Community Land Trusts (CLT) acquisitions** | Real market participants. | ~ **Competitor intel, not a lead source.** |
| **Bankruptcy → foreclosure "Stayed/Suspended" cross-reference** | The name cross-ref ALREADY existed (`enrichment_bankruptcy.py` tags `raw.bankruptcy` on 149 matched foreclosure leads). Built the missing STATUS layer: `enrichment_bankruptcy_stay.py` derives `raw.bankruptcy_stay` {status: stayed, chapter, resume_risk, note} — **55 active-foreclosure leads flagged stayed** (36 Ch13, 18 Ch7, 18 elevated resume-risk). New `bankruptcy_stay` signal + RAW_KEEP; wired into main.py + merge. Tests: test_bankruptcy_stay.py (5). Resume-risk is an age heuristic; full relief-from-stay/dismissal DOCKET tracking is the follow-on. | ✅ **BUILT** |

## Bottom line
Of the audit's headline gaps, exactly **one** (Lincoln code-enforcement) was a clean, verified,
free, in-footprint build — now done, and generalizable to the other counties. The rest were
login-walled (LiensNC), marketing-only (the 4 firms), macro-only (SHFPP), or low-yield (utilities).
The genuinely useful *code-only* idea is the bankruptcy-stay cross-reference. This is the value of
verify-before-build: it saved wiring 4 broken law-firm scrapers + a login-walled LiensNC scraper.
