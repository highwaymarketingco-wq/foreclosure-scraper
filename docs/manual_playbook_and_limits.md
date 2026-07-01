# Manual Playbook & Data Limits

Plain-language guide for the operator. Two parts:

- **PART 1 — What CANNOT be pulled** (for free, compliantly). What it is, why, and the workaround if one exists.
- **PART 2 — What YOU do manually, site by site.** Exact click-paths, what a save gives you (and what it doesn't), how often, and where to drop the file.

The scrapers already run on their own. This doc is about the extra data that only a human can legally pull, plus the hard limits so we stop re-chasing dead ends.

---

# PART 1 — What CANNOT be pulled (free + compliant)

## (a) Hard walls — no free path exists

| What | Why it's walled | Workaround |
|---|---|---|
| **Personal phone / cell number** (name+address → mobile) | Every forward-lookup API is paid (~$0.22–0.45/hit); free people-search sites (TruePeopleSearch, FastPeopleSearch, Radaris, Whitepages) 403 / paywall and ban automation. | **Direct mail**, not calls. Absentee/mailing-address mismatch + NC voter file is the compliant scaled channel. Cherry-pick top leads for a paid one-off skip-trace only if you personally authorize it. |
| **Email address** (owner) | Same as phone — third-party PII, paid-only. | None. Mail. |
| **Exact mortgage payoff / current loan balance** | Held only by the servicer. Not public anywhere (it's PII and changes mid-month: principal + interest + arrears + escrow + fees). | Use a **proxy**: the stated judgment/opening-bid $ (from a saved Judgments page), or the original loan amount OCR'd off the recorded deed-of-trust image. Always an estimate and a soft floor. |
| **Divorce cases (SC)** | SC Family Court is a separate, access-restricted system — **not** on the PublicIndex portal at all (see Part 1b). | None free at case level. Skip SC divorce. |
| **Probate / estates (SC)** | SC estates live in separate county **Probate Court**, not PublicIndex. | Already covered another way (obituaries + Gannett Upstate heirs pipeline). Don't chase the portal. |
| **Sale price + heated sqft (SC), from county data** | Both fields are empty across every free SC GIS/assessor source — genuinely withheld behind the paid county CAMA extract. | Per-parcel **assessor CARD** (Pickens/Oconee expose sqft + sale history as text); Microsoft Building Footprints for a sqft estimate; email `Assessor@spartanburgcounty.org` for the extract. Do NOT rebuild $/sqft comps unless a county extract is verified by name to carry both fields. |
| **Recorded lien / loan dollar amount from ROD index** | The ROD name index shows type/lender/date/book-page only. The "$X principal" is only on the scanned image. | The deed-of-trust **image is free** in some counties (e.g. Spartanburg Logan) → OCR it for the loan amount. Sale-price/consideration is NOT recoverable (SC exempt deeds state no value; AcclaimWeb omits consideration in its JSON). |
| **Paid data brokers** (PropStream, ATTOM, Regrid premium, RentCast, NCOALink/USPS) | All paid or trial-only; free tiers too small or blank for SC. | None — record as wall, never buy. Free tools hit the same ~13% explicit-debt ceiling the paid ones do. |

## (b) ToS / bot-gated portals — scrapers stay running, extra lanes are MANUAL

The existing stealth scrapers below are **user-approved and keep running as-is**. We do NOT expand them to new lanes or counties (that would mean writing new bypass code). Any extra data comes from a **manual save** + the offline parsers.

| Portal | What runs automatically | What is MANUAL (see Part 2) |
|---|---|---|
| **SC PublicIndex** (`publicindex.sccourts.org`) | `sc_public_index_lis_pendens` — Foreclosure lis pendens (~233 leads) | Partition, eviction, judgment $, state-tax-lien, MIE roster lanes → **you save the list**, parser ingests it |
| **NC eCourts** (`portal-nc.tylertech.cloud`) | `nc_ecourts_lis_pendens` (~242 leads) | Estates, divorce, SP-foreclosure, any live county → **you save the Smart Search results** |

## (c) Technical dead-ends — verified, do NOT re-chase

| What | Status |
|---|---|
| **Federal auctions** (homesales.gov, US Marshals, irsauctions.gov, GSA realestatesales) | All dead/login-walled as of 2026-06-30. No free no-login federal feed. USMS surplus already covered via Bid4Assets. |
| **SC deed-stamp OCR for sale price** | Not viable — §12-24-70 exempt deeds (foreclosure/deed-in-lieu/spouse) legally state no value. Distressed targets carry no recoverable price. |
| **Specific county tax balances** — Anderson (403), Cherokee (parcel-format mismatch), Pickens (no bulk), Spartanburg tax-sale-list PDF (no $ column) | Per-county walls. Spartanburg's broader tax-$ was solved via qPayBill (+408); the rest need per-parcel portal lookups (not a quick win). |
| **ROD portals** — Cherokee SC (login), CCHS Burke/Lincoln/Cleveland/Henderson (decommissioned), Rutherford Cott (subscriber wall), Kofile/Oconee (SPA, 0 rows), Spartanburg bulk instrument search (server-side SQL broken) | Index only where it works; document images pay-per-view on most. Not fixable from outside. |
| **SC Magistrate evictions — bulk feed** | No free bulk roster exists anywhere (confirmed 2026-06-30). PublicIndex exposes only circuit-court roster types, never magistrate. → manual save per county **or** FOIA. |
| **SC SoS entity owner** | CAPTCHA-walled → SC entities skipped. NC SoS works free via stealth. |
| **Code enforcement / vacant registries / demolition orders** | No free public in-footprint feed confirmed. FOIA/in-person only. |
| **LoopNet / auction.com MF / HUD-MF / Fannie-Freddie MF REO** | All 403 / broker-gated / empty. **Crexi is the only free multifamily source** (~13 in-footprint). |
| **Reddit live search / Apify actors** | Reddit hard-blocks bots (RSS `new` feeds are the only free surface); Apify account is billing-blocked. Use Brave Search `site:reddit.com` for HWM client monitoring. |
| **Column legal-notice API** | Not a wall — a silent-failure trap: returns HTTP 200 + 0 results when its filter format drifts. Re-verify whenever NC counts crater. |

---

# PART 2 — What YOU do manually, site by site

**The golden rule of saved pages:** a saved **results/list** page gives you the case LIST only — case number, plaintiff, defendant (owner name), filing date, sub-type, status. That's enough, because we resolve the **property/TMS/value from the defendant NAME via county GIS**. The **per-case DETAIL** (TMS, judgment $, financials) sits behind `__doPostBack` JavaScript links that are **dead in a saved HTML file** — clicking them in the saved copy does nothing. So: **save the list for volume; only save an individual case's detail page when you need the judgment $ on a top lead.**

Where to drop everything: **`~/foreclosure-scraper/`** (repo root). The parsers scan that folder, auto-detect NC vs SC, and batch-parse every `.html` at once. No network, no config.

---

## SITE 1 — SC PublicIndex (`https://publicindex.sccourts.org`)

**The 6-lane recipe.** The search form requires a Last Name, Case #, **Date**, or Tax Map #. For a bulk pull, **search by DATE with the name blank** — that returns every case filed in the window.

**Click-path (per county, per lane):**
1. Open the county's PublicIndex, **accept the disclaimer**.
2. **Court Type** dropdown — only 4 options exist: **All Courts / Circuit Court / Summary Court / Masters-In-Equity**. (There is **NO Family Court and NO Probate Court** here → SC divorce and SC probate are simply not obtainable from this portal.)
3. Set **Date Type = `Case Filed`**, **Beginning** = your last-pull date, **Ending** = today (`mm/dd/yyyy`).
4. Set the **Case Type / Sub-Type** (or Index Search radio) per the lane below.
5. Search → **Ctrl-S / File ▸ Save Page As ▸ "Web Page, HTML Only"** into `~/foreclosure-scraper/`.

| # | Lane (lead trigger) | Court Type | Case Sub-Type / Index radio |
|---|---|---|---|
| 1 | **Foreclosure** (owner losing property) | All Courts or Circuit Court | Sub-Type `Foreclosure` (420) |
| 2 | **Lis Pendens** (earliest foreclosure signal) | Circuit Court | Index Search radio → **Lis Pendens** |
| 3 | **Foreclosure sale / orders** | **Masters-In-Equity** | (All) |
| 4 | **Partition** (forced co-owner sale) | Circuit Court | Sub-Type `Partition` (440) |
| 5 | **State tax lien** (tax distress) | Circuit Court | Sub-Type `State Tax Lien` (432) |
| 6 | **Eviction** | **Summary Court** (Magistrate) | Sub-Type `Possession` (450) |
| + | **Judgment $ amounts** (per-case only) | Circuit Court | Index Search radio → **Judgments** |

**Result cap — don't just widen dates.** "All Courts" + a wide date range overflows the portal's row cap (it dumps every traffic/criminal case, 95% noise). Two safe options:
- **Recommended:** narrow the **Sub-Type** (e.g. `Foreclosure`) and keep dates wide → a few dozen rows/county, one pull works.
- **Or** keep All Courts but chunk dates to **~1 week per search** (2–3 days in Spartanburg/Buncombe/Gaston), walking backward.

**What a save YIELDS:** the case list (case #, plaintiff/lender, defendant/owner, filed date, sub-type, status). **GIS resolves the property from the owner name — you do NOT need to open each case.**
**What a save does NOT yield:** TMS and the judgment/debt **$ amount** — those are on the per-case detail page behind `__doPostBack` (dead in a static save). **For judgment $, cherry-pick your top leads and save each case's detail page individually** (lane "+").

**Backfill vs cadence:** first pull = last **6 months** (e.g. `01/01/2026 → 07/01/2026`). After that, each run only needs **since your last save (~3–4 days)**.
**Priority counties:** Spartanburg, Buncombe-equivalent Upstate cores first; then widen.

---

## SITE 2 — NC eCourts Smart Search (`https://portal-nc.tylertech.cloud`)

**Click-path (per county, per lane):**
1. Open the portal → **Smart Search**.
2. Set **Location = [county]** (only some NC counties are live on eCourts — check yours).
3. Set the **Case Category / Type** per the lane below + a recent **date range**.
4. Search → **File ▸ Save Page As ▸ "Web Page, HTML Only"** into `~/foreclosure-scraper/`.

| Lane (lead trigger) | Case Category / Type |
|---|---|
| **Foreclosure** (power of sale) | Special Proceeding |
| **Probate / estate** (heirs inherit + sell) | Estates (Clerk of Superior Court, E-files) |
| **Divorce** (forced sale / buy-out) | Civil ▸ District ▸ Domestic |
| **Eviction** (distressed landlord) | Small Claims / Magistrate |
| **Criminal** (owner incarcerated → vacant; low hit-rate, do last) | Criminal |

**What a save YIELDS:** the case list — case #, plaintiff, defendant/party names, case type, filing date, county. GIS resolves the property from the name.
**What a save does NOT yield:** the **dollar debt / indebtedness** figure — NC power-of-sale notices legally state only sale terms/deposit/upset-bid, and the SP file $ lives at the Clerk's office, not online. → use the FOIA fallback (Site 3) for judgment $.
**Cadence:** same as SC — 6-month backfill, then since-last-save.

---

## SITE 3 — FOIA fallbacks (judgment $ + counties not online)

The one free route to data the portals don't show. **You (or a VA) send the letter; the clerk emails back a list/report; drop the file in `~/foreclosure-scraper/`.** Full letter templates are in **`docs/foia_court_records.md`** — copy them verbatim, fill the brackets.

Always ask for **electronic delivery (CSV/Excel/PDF)** — cheaper, faster, directly parseable. Turnaround ~7–30 days (SC FOIA requires a response within 10 business days).

| Route | Who to write | Ask for |
|---|---|---|
| **NC — Clerk of Superior Court** | Clerk, [county] County NC | Foreclosure Special Proceedings + civil money judgments **with judgment amount**. Counties: Buncombe, Gaston, Henderson, Cleveland, Rutherford, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell. |
| **SC — Clerk of Court / Master-in-Equity** | Clerk, [county] County SC (cc: MIE) | Common Pleas foreclosure cases + **MIE sales roster / judgment amounts**. Anchors: Spartanburg (Master S. Metz Phillips), Pickens (Master A. Lambert), Anderson & Oconee (Master S. Kirven). |
| **SC — Magistrate Court** | Chief Magistrate, [county] County SC | Ejectment / rule-to-vacate (eviction) filings. **This is the only free case-level eviction route** — the online index is ToS-blocked and no bulk feed exists. |

---

## SITE 4 — LSC eviction data-sharing (aggregate → case-level)

The **Legal Services Corporation Civil Court Data Initiative** publishes eviction data. The **public** layer is **aggregate county counts only** (no case-level names/addresses) — useful for prioritizing counties, not for leads.

To get **case-level** eviction data, request an **LSC data-sharing agreement**: email **`civilcourtdata@lsc.gov`**, state the counties and the research/business purpose, and ask about their data-use terms. This is a longer institutional route (not a quick save) — pursue it only if evictions become a priority lane; otherwise the SC Magistrate FOIA (Site 3) is the faster case-level path.

---

## Fastest weekly routine (checklist)

Lean pass, ~20–30 min. Everything drops in `~/foreclosure-scraper/`; then tell me to parse.

- [ ] **SC PublicIndex** — 3 biggest counties × 3 core lanes = 9 saves: **Foreclosure (420)**, **Masters-In-Equity (all)**, **Possession/eviction (450)**. Date Type = `Case Filed`, since last save. Name blank.
- [ ] **NC eCourts** — same 3 counties × 2 core lanes: **Special Proceeding (foreclosure)** + **Estates**. Location per county, since last save.
- [ ] **Judgment $ (optional)** — only for your top ~10 leads: open each case, save the **detail** page (list saves won't carry the $).
- [ ] Drop every `.html` in `~/foreclosure-scraper/` → ping me: *"parse the new court exports."* I batch-run `parse_publicindex_export.py` + `parse_nc_ecourts_export.py`, and leads flow into the board with full owner/GIS/equity enrichment.
- [ ] **Monthly, not weekly:** send any outstanding **FOIA** letters (judgment $ + offline counties) and, if evictions matter, the **LSC** data-sharing email.

**Rule of thumb:** save the **list** for volume (GIS does the rest); save a **detail** page only when you need the **dollar amount** on a specific lead.
