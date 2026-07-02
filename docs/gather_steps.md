# Gather Runbook — step-by-step per source

You gather (verified browser / Cowork), I parse. For every source: **save the results page and drop it in `~/foreclosure-scraper/`**, then tell me "parse the new exports." Filenames are your choice but `<county>_<lane>.html` keeps it clean (I also auto-detect county from the case numbers).

Save method everywhere: **File ▸ Save Page As ▸ "Web Page, HTML Only"** (or Cmd/Ctrl-S → HTML Only). Not "Complete", not PDF.

---

## 1. NC eCourts (foreclosure + estates + divorce) — 11 NC counties

**URL: `https://portal-nc.tylertech.cloud/Portal/`  ← use this exact path. The bare `portal-nc.tylertech.cloud/` returns a 403 (no page there). Do NOT sign in — public search needs no account.**

Per county (Buncombe, Gaston, Henderson, Cleveland, Rutherford, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell):

1. Open `https://portal-nc.tylertech.cloud/Portal/` → if an AWS "confirm you are human" box appears, solve it once (human is fine).
2. Click **Smart Search**.
3. In the search box leave the name blank; set **Location = [county]** (if offered) and a **date range** = last 6 months for the first pull, then last 3–4 days each future pull.
4. Run these **3 lanes** (one search + save each):
   - **Foreclosure** → Case Category/Type = **Special Proceeding** (power of sale)
   - **Estates** (heirs) → Case Category = **Estate** / Clerk of Superior Court E-files
   - **Divorce** → Civil ▸ District ▸ **Domestic**
5. When results show → **Save Page As ▸ HTML Only** → `~/foreclosure-scraper/` as e.g. `buncombe_nc_foreclosure.html`, `buncombe_nc_estate.html`, `buncombe_nc_divorce.html`.

If you get a **hard 403 before you can search**: your IP got rate-flagged. Switch networks (phone hotspot) or wait ~30 min, then reopen `/Portal/`.

---

## 2. SC PublicIndex (6 lanes) — 6 SC counties + 2 Spartanburg gaps

**URL: `https://publicindex.sccourts.org/<County>/PublicIndex/`** — replace `<County>` with `Anderson`, `Pickens`, `Oconee`, `Cherokee`, `Union`, `Laurens` (Spartanburg's main lanes are already done). No login.

Per county:

1. Open the county URL → **accept the disclaimer**.
2. On the search form (PISearch.aspx), leave **Last Name blank**, set **Date Type = `Case Filed`**, **Beginning = 01/01/2026, Ending = 07/01/2026** (first pull; then last 3–4 days).
3. Run these lanes (set the dropdowns, Search, save each):

   | Lane | Court Type | Case Type | Case Sub-Type | Date Type |
   |---|---|---|---|---|
   | Foreclosure | Circuit Court | Common Pleas | **Foreclosure (420)** | **Case Filed** |
   | Lis Pendens | Circuit Court | **Lis Pendens** | All | **Case Filed** |
   | Partition | Circuit Court | Common Pleas | **Partition (440)** | **Case Filed** |
   | Eviction | **Summary Court** | All | **Possession (450)** | **Case Filed** |

   **All four lanes use Date Type = `Case Filed`** — do NOT use "Judgment Issued", it returns near-zero.

   **SKIP these two** (learned 2026-07-01):
   - **State Tax Lien (432)** — already pulled directly from the SC DOR lien registry (~8,000 liens). Redundant; don't gather.
   - **Judgment $** — NOT a separate case-type search in this portal (420 lives under Common Pleas, there is no "Judgment" type holding it). Get judgment $ from the per-case **DETAIL** page (step 3) on hot leads only.

4. **Save the results** → `~/foreclosure-scraper/` as e.g. `anderson_sc_foreclosure.html`.
5. **If a lane says "maximum records exceeded"**: narrow the dates to ~2 months and re-run.

**Saving from an automated (Cowork) session:** the native Chrome "Save As" is an OS window the browser tools can't click. Instead, after results render, grab the page HTML directly — evaluate `document.documentElement.outerHTML` and write it to `<county>_<lane>.html`. That's exactly what the parser reads (the `#ContentPlaceHolder1_SearchResults` table) — no Save dialog needed. (Manual browser: plain Ctrl-S → HTML Only still works.)

---

## 3. SC PublicIndex — per-case DETAIL (top leads only)

The list save does NOT capture TMS + judgment $ (those are behind a JavaScript click). For a **hot lead only**:

1. In the live PublicIndex session, click the case number → the detail page opens.
2. **Save Page As ▸ HTML Only** → `~/foreclosure-scraper/` as `detail_<casenumber>.html`.
Only do this for leads you're actually working — not the whole list.

---

## 4. Anderson SC tax balance (per-parcel, top leads)

**URL: `https://acpass.andersoncountysc.org`** (bulk is 403-blocked; per-parcel works).
1. Search the parcel/owner for a top Anderson lead.
2. Open the tax/balance page → **Save Page As ▸ HTML Only** → `anderson_tax_<parcel>.html`.

## 5. Pickens SC tax + sqft (per-parcel, top leads)

Pickens has no bulk tax feed — use the **qPublic per-parcel CARD**:
1. Open qPublic Pickens SC → search the parcel.
2. Save the CARD page (balance + sale history + heated sqft) → `pickens_card_<parcel>.html`.

---

## 6. SC SoS entity owner (LLC-held top leads)

**URL: `https://businessfilings.sc.gov`** (NC entities already pull free; SC is CAPTCHA-gated so it's manual).
1. Search the LLC/entity name from a lead where the owner is a company.
2. Solve the CAPTCHA (human) → open the entity detail (registered agent + officers).
3. **Save Page As ▸ HTML Only** → `sc_sos_<entity>.html`.

---

## 7. PropWire export (your own free account)

1. Log into **your own** free PropWire account (`propwire.com`). (I can't create the account or log in — you do this.)
2. Run the **Foreclosure / Pre-foreclosure** filter for the footprint counties.
3. **Export CSV** → drop the CSV in `~/foreclosure-scraper/`. (Data tier only — skip-trace tier is paid PII.)

---

## 8. SC LLR contractor roster (one-time, real Chrome)

**URL: `https://verify.llronline.com`** (only a real, non-headless browser seats a session).
1. Open in a normal Chrome tab, run the contractor roster search.
2. Export / save the ~1,217-row result → `sc_llr_roster.html` (or CSV) in `~/foreclosure-scraper/`.

---

## 9. FOIA — judgment $ + offline counties (send once, async)

Templates are in **`docs/foia_court_records.md`** — copy verbatim, fill the brackets, email:
- **NC:** Clerk of Superior Court, each county → foreclosure Special Proceedings + civil money judgments **with judgment amount**.
- **SC:** Clerk of Court + Master-in-Equity, each county → Common Pleas foreclosures + MIE sale roster / judgment $.
Ask for **electronic CSV/Excel**. When the file comes back, drop it in `~/foreclosure-scraper/`.

## 10. Spartanburg CAMA extract (one email)

Email **`Assessor@spartanburgcounty.org`** and request the **bulk CAMA extract** (parcel + sale price + heated sqft) in CSV/Excel. Drop the returned file in `~/foreclosure-scraper/`.

---

## Phones (no gathering)

Say **"voter file"** → I run the NC voter-file phone match now (free, ~69% NC). Or buy a licensed skip-trace, export CSV, drop it → I ingest the phone column. I do **not** scrape the people-search sites.

---

### After any drop
Tell me **"parse the new exports"** — I batch-run the offline parsers, dedupe, enrich (owner/GIS/equity), and the leads land on the board with the court-confirmed badge.
