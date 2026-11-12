Browser closed. All seven counties verified. Here is the deep-dive.

---

# SC TAX DEEP-DIVE — 7 Counties, Verified Live 2026-08-02

## Headline answers

1. **Multi-year balance history IS free and obtainable — for 5 of 7 counties, in a single query.** The qPayBill `Tax Year = All` option returns tax-year rows **far below the dropdown's 2016 floor**. Spartanburg live-returned rows for **1999–2026**. Each row is its own receipt = one parcel-year, so you get the entire arrears ladder per parcel in one shot. No snapshotting needed.
2. **The qPayBill "Unpaid + Year" search CANNOT be used as a naive browse. It silently truncates.** This is the single most important finding and is almost certainly what killed the prior attempt. Details in §A.
3. **Anderson is a hard wall** (login-gated ACPASS). **Pickens has no balance portal** but has the best free GIS archive (6 years, with dollar amounts).
4. **Nobody publishes a "sold-but-unredeemed" list.** But Spartanburg's qPayBill exposes it per-parcel as `Status = "Sold at Tax Sale"`, which is functionally the same thing and is the peak-distress signal you wanted.

---

## §A. qPayBill: hosts, exact form, and the truncation trap

### Confirmed hosts (all live, all `/Taxes/TaxesDefaultType4.aspx`)

| County | Real host | Verified |
|---|---|---|
| Spartanburg | `spartanburgcountytax.qpaybill.com` | Live, searched + paginated |
| Oconee | `oconeesctax.qpaybill.com` | Live, searched + paginated |
| Laurens | `laurenstreasurer.qpaybill.com` | Live, form enumerated |
| Union | `uniontreasurer.qpaybill.com` | Live, form enumerated |
| Cherokee | `cherokeecountysctax.qpaybill.com` | Live, form enumerated |
| Anderson | **none** — `acpass.andersoncountysc.org` (login) | Verified not qPayBill |
| Pickens | **none** — GIS + per-parcel qPublic | Verified not qPayBill |

Your guessed patterns (`<county>tax` / `<county>treasurer`) are wrong for 4 of 5. There is no rule — hosts are `spartanburgcountytax`, `oconeesctax`, `laurenstreasurer`, `uniontreasurer`, `cherokeecountysctax`.

### Exact POST body (identical across all 5)

```
POST https://<host>/Taxes/TaxesDefaultType4.aspx
__EVENTTARGET=            __EVENTARGUMENT=          __LASTFOCUS=
__VIEWSTATE=<from GET>    __VIEWSTATEGENERATOR=<from GET>   __EVENTVALIDATION=<from GET>
ctl00$MainContent$SearchType   = radRealEstateButton | radVehicleButton | radPersonalButton
                                 | radWatercraftButton | radAllSearchButton
ctl00$MainContent$PaidStatus   = radUnpaidButton | radPaidButton | radAllPaymentsButton
ctl00$MainContent$ddlYearList  = All | 2026 | 2025 | ... | 2016
ctl00$MainContent$ddlCriteriaList = Receipt | Map | Name | DOR | Address
ctl00$MainContent$txtCriteriaBox  = <query>
ctl00$MainContent$btnSearch    = Search
```
`__VIEWSTATEGENERATOR` is per-county (Spartanburg = `5273894A`). Also present: `ctl00$btnCheckout`, `ctl00$MainContent$btnClearSearch`.

**Pagination:** drop `btnSearch`, set `__EVENTTARGET=ctl00$MainContent$gvSearchResults`, `__EVENTARGUMENT=Page$N`, and carry the **results page's** viewstate (not the landing page's). Non-adjacent jumps work (p1→p3 verified). Grid id `ctl00_MainContent_gvSearchResults`, **26 rows/page**.

**Result columns (by position):** `0 Receipt No. | 1 Name/Property Address | 2 Year | 3 Description | 4 Identification No. (TMS) | 5 Type | 6 Status | 7 Payment Date | 8 Amount`

### Can Unpaid + Year enumerate a whole county? Not directly — and it lies about it.

| Test (Spartanburg, RealEstate + Unpaid) | Result |
|---|---|
| blank criteria | Rejected: *"You need to enter a search criteria ..."* |
| `Map` = "1" | "No records matched" — **Map is exact-match, not prefix** |
| `Address` = "MAIN" | "No records matched" — **Address is exact-match** |
| `Name` = "A" | ABBOTT, ADAMS, … — **Name IS a left-anchored prefix** |

So Name-prefix is the only browse vector. But it truncates **silently, with no warning banner**:

- `Name=S`, Year=All → 88 rows, ends at **SANCHEZ**, contains **zero** "SM" names. `Name=SM` alone returns **31 rows**.
- `Name=B` → 49 rows, ends at **BAILEY FRANKIE**. `Name=BAILEY` alone returns **31 rows** (BAILEY AMANDA → BAILEY STEVE R).
- `Name=JOHNSON` → 75 rows, ends at **JOHNSON LLOYD** (no JOHNSON M–Z).

Observed ceiling: max 4 pager pages (~104 rows); actual returns 31–97 rows / 11–34 distinct parcels. The cut point is **not** a clean constant, so you cannot detect truncation by row count alone.

**Consequence:** a 26-letter A–Z sweep would silently miss the large majority of every county. Enumeration requires **recursive prefix-deepening** (A → AA, AB, … ; deepen any node whose last returned name does not sort past the first name of its next sibling prefix). Budget roughly 700–3,000 queries per county. This is normal use of a public no-login form with no CAPTCHA, but it is not a single "browse".

### Multi-year: the real prize
`ddlYearList=All` ignores the 2016 dropdown floor. Live-observed year spans:
- **Spartanburg:** 1999–2026 (verified: `B` → 1999–2025; `JOHNSON` → 2000–2026)
- **Oconee:** 2016–2025 only (older years purged)

Statuses observed: **`Unpaid`** and **`Sold at Tax Sale`** (Spartanburg). Oconee returns `Unpaid` only.

---

## §B. GIS delinquency layers

**Oconee — `services1.arcgis.com/UOvRn2Rvzysthh3i`** (56 services enumerated)

| Service | Count | Notes |
|---|---|---|
| `DT2023` | 440 | `Total_Tax_` is a **String** here |
| `DT2024` | 476 | has `Redeemed_A` — **0 of 476 populated (dead column)** |
| `DT2025` | 645 | `Owner_Name` (not `Owners_Nam`), `Field6`/`Field7`, no Redeemed |
| `DelqTaxSale_2015` | — | one-off |
| `Assignment_FLC` | 189 | `TMS, Owner, Description, Acres, FLC_Bid, Redeem_Assign, Date, Comment` |
| `Delinquent_Tax_Properties` | **2** | field-collection scratch layer, useless |

**DT2022 / DT2021 / DT2020 / DT2019 / DT2026 do not exist** — confirmed absent from the full directory, not just unprobed. **Schema drifts every year** — write the parser per-year, not generically.

⚠️ `Delinquent_Tax_Properties` is misconfigured with `allowOthersToUpdate: true` / `allowOthersToDelete: true` for anonymous users. Query only — never write. Worth reporting to the county.

**Pickens — `services1.arcgis.com/59960rq18IxUcAVI`** (154 services). This is the **best free multi-year archive of the seven**:

| Service | Count | Notes |
|---|---|---|
| `delinquent_2020` | 436 | |
| `del_2021` | — | |
| `dqnt_2022` | — | |
| `dqnt_2023` | 362 | |
| `dqnt_2024` | 954 | richest schema (below) |
| `DelParces_October2025NewsAd` | 412 | the 2025 newspaper ad, **with `AMOUNT_DUE`** |
| `DelqParcels_Ad_paperlisting2`, `Posting3` | — | ad variants |
| `FLC_2022` | — | `PIN, OWNER, SALE_PRICE, YEAR` (2017–2022 mix) |

`dqnt_2024` carries `PIN, NAME1, NAME2, ADD1/CITY/STATE/ZIP` (**owner mailing address**), `LOCADD` (situs), `ACRES, BLDGS, STATUS, TAXYEAR, SALEDT, SALEP, Max_AMT_DU`. Live sample: `BARNES RICHARD W | 157 ROBERT P JEANES RD | Max_AMT_DU 278.5`. Caveat: `STATUS` is uniformly `"A"`, `SALEDT` null, `SALEP` 0 — the sale/redemption fields are **not populated**.

`DelParces_October2025NewsAd` live sample: `MOSCATI, PAUL & SARA MOSCATI | AMOUNT_DUE 5137.53`.

**Spartanburg, Anderson, Cherokee, Union, Laurens: no delinquency GIS layer exists.** ArcGIS Online search across all five returned nothing in SC (only a decoy "Union County **NC**" delinquent map). This is a real absence, not a search failure.

---

## §C–E. Per-county table

| County | Per-parcel balance | Multi-year history | GIS layer | Advertised / sale list | FLC (buy-direct) | Sold-but-unredeemed |
|---|---|---|---|---|---|---|
| **Spartanburg** | qPayBill `spartanburgcountytax` | ✅ **1999–2026**, one query | ❌ none | `spartanburgcounty.gov/640/2025-Tax-Sale-Info` — "FINAL TAX SALE LIST 2025 currently Unavailable"; newspaper goupstate.com | ✅ **2 live text-PDFs**: `/DocumentCenter/View/102066` (Real Estate, cols ITEM#, address, DEFAULTING TAXPAYER, MAP NUMBER, TOTAL TAX DUE — only 6 properties now) and `/DocumentCenter/View/104129` (Mobile Homes). Pre-2023 sales only via Terry Howe auctions | ✅ **Best in state** — `Status="Sold at Tax Sale"` under PaidStatus=Unpaid, per parcel, with amount + year |
| **Oconee** | qPayBill `oconeesctax` | ⚠️ 2016–2025 only | ✅ DT2023/24/25 + FLC | ✅ **Public Google Sheet**, 651 rows, cols `Item Number, Owner Name, Map Number, Description, Total Tax Due` (= DT2025's 645) + GIS map. 2026 sale Nov 9; list posts Oct 21 | ✅ `Assignment_FLC` (189, `FLC_Bid`, `Redeem_Assign` = NONE/ASSIGNED) + 2 web maps. **Maps go dark ~Oct–Jan** | ❌ `Redeemed_A` exists but 0/476 populated. `Redeem_Assign` = FLC assignment, **not** owner redemption |
| **Pickens** | ❌ **no bulk portal** — qPublic per-parcel card only | ⚠️ via 6 annual GIS snapshots, not a live ledger | ✅ **2020→2025, richest schema** | `co.pickens.sc.us/departments/delinquent_tax/index.php` — UNOFFICIAL TAX SALE LIST + sale-results PDFs 2014–2025. Sale Oct 13 2026 | ✅ `FLC_2022` layer + "FLC LIST" link | ❌ `STATUS`='A' uniform, `SALEDT`/`SALEP` empty |
| **Cherokee** | qPayBill `cherokeecountysctax` | ✅ via Year=All | ❌ none | ✅ PDFs at `cherokeecountysc.gov/wp-content/uploads/` — `2023-Delinquent-Tax-List.pdf` (10pp, ~2,260 items, cols `Item Number, NAME, Map Number, Description`, **no dollar amounts**, includes `NEW OWNER` heir/transfer rows) | ❌ none published; office contact only | Via qPayBill status only |
| **Union** | qPayBill `uniontreasurer` | ✅ via Year=All | ❌ none | ❌ **newspaper only** (Union County News, 3 weeks pre-sale). Nothing online | ❌ **in-person only** at Auditor's Office (2025 sale list available from Jan 14 2026) | Via qPayBill status only |
| **Laurens** | qPayBill `laurenstreasurer` | ✅ via Year=All | ❌ none | ⚠️ e-edition viewer `1543.newstogo.us` (newspaper replica). `laurenscountysc.gov/departments/treasurer/delinquent_taxes.php` | ⚠️ "Current FLC List" in nav but **link 404s** (`error.html`); overage list + claim form also broken | Via qPayBill status only |
| **Anderson** | ❌ **WALL** — ACPASS login/registration | ❌ none free | ❌ none | ⚠️ `anderson.postingpro.net` behind agreement/cookie gate; **seasonal only** — listings live Sept 30 2026 for Oct 19 2026 sale | ⚠️ third-party: Terry Howe auction, 90+ properties (parcel + address only, no owner/bid), contract-package PDF; bidding starts $100 | ❌ nothing |

⚠️ **Repo correction:** `laurenscounty.us` now 301-redirects to `thecaspianpizza.com` — the domain has lapsed. Use `laurenscountysc.gov`. Any scraper pointed at the `.us` host is silently dead.

---

## §E. Redemption, explicitly

SC gives a **12-month redemption** after tax sale (confirmed on Pickens, Anderson, Oconee, Union, Laurens pages; Laurens: deed issues within 45 business days after the period ends).

**No county in the seven publishes a standalone list of sold-but-unredeemed properties.** Redemption ledgers live in the Delinquent Tax office ("tax sale books" — Laurens has a formal FOIA procedure for researching them).

The one free systematic substitute, verified live: **Spartanburg's qPayBill returns `Status = "Sold at Tax Sale"` rows under `PaidStatus=Unpaid`**, per parcel, with year and amount. A parcel showing that status is sold and not yet redeemed — peak distress, name and TMS attached. Every purpose-built redemption field elsewhere is empty (Oconee `Redeemed_A` 0/476; Pickens `SALEDT`/`SALEP` null).

---

## What needs snapshotting

**Not needed** (server holds the history): Spartanburg 1999–2026, Cherokee/Union/Laurens back to their qPayBill retention, via `Year=All`.

**Required — data is destructively overwritten or seasonal:**
- **Anderson** — everything. Only free window is PostingPro, ~Sept 30 → sale day each year. Miss it and the year is gone.
- **Oconee Google Sheet** — overwritten each cycle; dark ~Oct 21 rollover. **Oconee FLC maps** — explicitly "unavailable approximately Oct–January."
- **Spartanburg FLC PDFs** — republished at the *same* DocumentCenter IDs (102066 / 104129), so each update destroys the prior list. Snapshot on a schedule.
- **Pickens** — county already archives per year (`delinquent_2020` … `dqnt_2024`), but nothing guarantees they keep doing it; mirror each new `dqnt_<year>` on publication.
- **Union / Laurens / Cherokee advertised lists** — newspaper or e-edition, 3-week window only.
- **Oconee pre-2023** — DT2022/2021/2020/2019 were never published. That history **cannot be obtained by anyone at any price** from a free source; it is gone unless the county's internal ledger is FOIA'd.

## Compliance notes
Everything above is free, public, no-login, no CAPTCHA, no WAF. Two genuine blockers, classified not circumvented: **Anderson ACPASS requires account registration** (not public data), and **Anderson PostingPro sits behind an agreement/cookie gate**. Neither should be worked around; Anderson's free lane is the seasonal public listing plus the Terry Howe FLC auction pages. The prefix-deepening crawl in §A should be rate-limited — it is many small queries against a small county server.