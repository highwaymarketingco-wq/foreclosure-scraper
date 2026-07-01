# Public-Records Request Templates — Court Case Data (NC + SC)

The one free route to the case-level data the online portals gate (captcha/ToS):
**foreclosure filings at complaint stage + judgment/debt dollar amounts + evictions.**
You (or a VA) send these; the clerk returns a list/report; drop the file in
`~/foreclosure-scraper/` and I parse it into leads (owner → GIS → equity → board).

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
