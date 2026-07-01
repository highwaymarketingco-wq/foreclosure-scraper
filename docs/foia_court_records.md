# Court Case Data Playbook (NC + SC) — Manual Export + FOIA

Two compliant ways to pull the case-level court data the online portals gate. Both
are things YOU do (a human is allowed to search public records); I only parse what
you save. **Option A (live export) is faster; Option B (FOIA) is the fallback for
data the portal won't show (e.g. judgment $ amounts).**

---

## OPTION A — Live portal export (fastest, ~do this 2x/week)

### You do NOT pick a judge. You pick: County (Location) + Court + Case type + dates.
- **NC eCourts** (portal-nc.tylertech.cloud): Smart Search → set **Location = [county]**,
  **Case Category/Type** (below), a recent **date range** → Search → **File ▸ Save Page
  As ▸ "Web Page, HTML Only"**. (Only some NC counties are live on eCourts yet — check yours.)
- **SC PublicIndex** (publicindex.sccourts.org): accept disclaimer → pick **County** →
  **Court Agency** (Common Pleas / Family / Probate / Magistrate) → search → save the page.

### Case types to grab (each is a different motivated-seller trigger)
| Lane | Why it's a lead | NC (eCourts) | SC (PublicIndex — "Court Agency" dropdown) |
|---|---|---|---|
| **Foreclosure** | owner losing the property | Special Proceeding (power of sale) | **Common Pleas** + **Master In Equity** (foreclosures are filed in Common Pleas and referred to the MIE — MIE also carries the sale + judgment $) |
| **Eviction** | distressed landlord/tenant | (small claims / magistrate) | **[County] Magistrate** + **Magistrate Region #1/#2/#3** (grab all regions) |
| **Probate / Estate** | heirs inherit a house they'll sell | **Estates** (Clerk of Superior Court, E-files) | NOT on PublicIndex — SC estates are in the separate county **Probate Court** (we already pull these another way) |
| **Divorce** | forced sale / buy-out on split | Civil ▸ District ▸ Domestic | NOT on PublicIndex — SC **Family Court** is separate + largely access-restricted |
| **Criminal** | owner incarcerated → vacant (low hit-rate, do last) | Criminal | General Sessions (felony) — skip unless time |

**SC "Court Agency" dropdown — pick these:** Common Pleas, Master In Equity, and the
county Magistrate + its Region #1/#2/#3. **Skip:** Bond Court, all Municipal courts
(Cowpens/Duncan/Pacolet/City), Transfer Court, and (usually) General Sessions.

### SC PublicIndex — exact search settings (the date trick unlocks bulk pulls)
The form REQUIRES a Last Name, Case #, **Date**, or Tax Map # (per its own JS). So
for a bulk list you **search by DATE, not name**: set **Date Type = `Case Filed`**,
**Beginning** = your last-pull date, **Ending** = today (`mm/dd/yyyy`), leave Last Name
blank. That returns every case filed in the window (filtered by agency/subtype).

| Lane | Court Agency | Case SubType | Also set |
|---|---|---|---|
| Foreclosure | Common Pleas | `Foreclosure` (420) | — |
| Foreclosure — earliest signal | Common Pleas | (All) | Index Search radio → **Lis Pendens** |
| Foreclosure sale/orders | **Master In Equity** | (All) | — |
| Judgment $ amounts | Common Pleas | (All) | Index Search radio → **Judgments** |
| Eviction | County **Magistrate** (+ Region #1/#2/#3) | `Possession` (450) | — |
| Partition (forced co-owner sale) | Common Pleas | `Partition` (440) | — |
| Tax-lien distress | Common Pleas | `State Tax Lien` (432) | — |

**Fewest clicks (recommended):** Court Agency = **All Agencies** + Date Type = `Case
Filed` + your date range → Search → Save. Returns everything filed in the window; I
filter foreclosure/eviction/partition/tax-lien on my end. One save per county.
(If it's too many rows to load, use the per-lane rows above.)
**Skip on this portal:** Divorce (104) + Probate (940) — those are Family/Probate
Court, not in this Common Pleas index; they return empty here.

### Time estimate (be realistic)
~2 min per (county × case-type) search+save. Priorities:
- **Lean 2x/week pass (~20-30 min):** the 3 biggest counties (Buncombe, Gaston, Spartanburg)
  × 3 lanes (foreclosure, estate, divorce) = 9 searches. Skip criminal.
- **Full footprint pass (~60-90 min):** all 18 counties × 3 lanes. Better done weekly, or
  split across a VA. Foreclosure + Estate are the highest ROI; divorce second; criminal last.
Drop every saved `.html` in `~/foreclosure-scraper/`; I batch-parse them all at once.

---

## OPTION B — FOIA (for judgment $ + counties not live online)

The one free route to data the portal DOESN'T show — **judgment/debt dollar amounts**,
plus any county not yet on eCourts. You (or a VA) send these; the clerk returns a
list/report; drop the file in `~/foreclosure-scraper/` and I parse it into leads.

**Ask for it electronically** (CSV/Excel/PDF) — cheaper, faster, and I can parse it
directly. NC/SC public-records law lets you inspect for free; copies run ~$0.25/page,
so an electronic report beats paper. Turnaround is typically 7–30 days.

---

## NC — Clerk of Superior Court (foreclosure Special Proceedings + judgments)
NC power-of-sale foreclosures are **Special Proceedings** filed with the Clerk of
Superior Court; money judgments are in the Civil Judgment index. Send per county.

> **To:** Clerk of Superior Court, [COUNTY] County, North Carolina
> **Re:** Public Records Request — Foreclosure Special Proceedings & Civil Judgments
>
> Under the NC Public Records Act (N.C.G.S. §132-1 et seq.), I request the following
> public records for [COUNTY] County, for the period [START DATE] to present, in
> electronic format (CSV or Excel preferred; PDF acceptable):
>
> 1. All **Special Proceedings for foreclosure (power of sale)** filed with the Clerk,
>    including: file/case number, filing date, petitioner/trustee, respondent(s)
>    (property owner) name(s), property address or parcel if recorded, and current
>    status (hearing date, order, upset-bid deadline, sale date).
> 2. All **civil money judgments** entered in [COUNTY] for the same period, including:
>    case number, date, plaintiff, defendant(s), and **judgment amount**.
>
> Please advise of any fee before processing if it exceeds $[LIMIT, e.g. 25].
> Electronic delivery to [YOUR EMAIL] is preferred. Thank you.

**NC footprint counties + Clerk locations** (verify address on nccourts.gov › county):
Buncombe (60 Court Plaza, Asheville 28801), Gaston (325 Dr. M.L.K. Jr. Way, Gastonia
28052), Henderson, Cleveland, Rutherford, Burke, Lincoln, McDowell, Polk, Transylvania,
Mitchell.

---

## SC — Clerk of Court / Master-in-Equity (foreclosure + judgments)
SC foreclosures are **Common Pleas** cases handled by the **Master-in-Equity**;
judgments are in the Clerk's judgment roll. Send per county.

> **To:** Clerk of Court, [COUNTY] County, South Carolina (cc: Master-in-Equity)
> **Re:** FOIA Request — Foreclosure (Common Pleas) & Judgment Records
>
> Under the SC Freedom of Information Act (S.C. Code §30-4-10 et seq.), I request,
> for [COUNTY] County, [START DATE] to present, in electronic format (CSV/Excel
> preferred):
>
> 1. All **Common Pleas foreclosure cases** (case type "Foreclosure"): case number,
>    filing date, plaintiff (lender), defendant(s) (owner), property address/TMS if
>    on file, status, and any scheduled **sale date**.
> 2. The **Master-in-Equity foreclosure sales roster / judgment amounts** for the
>    same period (judgment/debt figure per case).
>
> SC FOIA requires a response within 10 business days. Please advise of any fee over
> $[LIMIT] before processing. Electronic delivery to [YOUR EMAIL] preferred.

**SC footprint MIE/courthouse anchors** (from court-access research):
Spartanburg — Master Shannon Metz Phillips, Judicial Center, 180 Magnolia St,
Spartanburg 29306. Pickens — Master Adam B. Lambert. Anderson & Oconee — Master
Steven C. Kirven. Cherokee/Union/Laurens — Special Referee/Circuit (no standing MIE).

---

## SC — Magistrate Court (EVICTIONS / ejectment) — the only free case-level route
Evictions live only in Magistrate Court and the online index is ToS-blocked, so FOIA
is the sole compliant case-level source.

> **To:** Chief Magistrate, [COUNTY] County, South Carolina
> **Re:** FOIA Request — Ejectment (Landlord-Tenant) Filings
>
> Under S.C. Code §30-4-10 et seq., I request all **ejectment / rule-to-vacate
> (eviction)** cases filed in [COUNTY] Magistrate Court from [START DATE] to present,
> in electronic format: case number, filing date, plaintiff (landlord), defendant
> (tenant), rental property address, and disposition. Please advise of fees over
> $[LIMIT]. Electronic delivery to [YOUR EMAIL] preferred.

---

### After you get a response
Drop the returned file (CSV/Excel/PDF/saved-HTML) in `~/foreclosure-scraper/` and tell
me the path. I run it through the offline parsers (`parse_nc_ecourts_export.py` /
`ingest_nc_court.py`) → leads flow into the board with full owner/GIS/equity enrichment.
Batch a few high-value counties first (Buncombe, Gaston, Spartanburg) to prove the ROI.
