# Operator Playbook — LiensNC (builder distress) + Bankruptcy-Stay tracking

Two distress lanes that need YOU in the loop (login / judgment call), with the pipeline doing the
analysis. Step-by-step, do-it-yourself.

---

## LANE 1 — LiensNC: over-leveraged flipper / stalled-construction distress

**What it catches (and why it's different):** When a flip or new build starts in NC, contractors and
suppliers file a "Notice to Lien Agent" on LiensNC to protect their right to get paid. The signal is
NOT a single notice — it's a **CLUSTER of notices on one parcel**, or notices on a project where
construction has **visibly stalled**. That pattern = the investor/builder ran out of capital,
contractors are lining up to file formal mechanic's liens, and the owner is in real trouble — a
motivated seller *before* any bank foreclosure. This is the ONE clean way to catch investor/builder
distress statewide, and it bypasses scraping scanned deed PDFs from the county ROD.

**Compliance (read once):** LiensNC's search is behind a login and its terms bar automated querying.
So there is NO bot. YOU pull it manually as the account holder (that's fine for your own use); the
pipeline only PARSES what you saved. Do not share/redistribute the raw files.

### Step-by-step — how to pull it (do this monthly, ~15 min)
1. Log in at `https://apps.liensnc.com` (you have an account).
2. Go to **Advanced Search** (`/scr/filing/advancedSearch.html`).
3. Search by **county** (run one per target NC county: Buncombe, Henderson, Rutherford, Gaston,
   Lincoln, Cleveland, Burke, McDowell, Polk, Transylvania, Mitchell) with a **filing-date range**
   of the last ~90 days. Sort by Filing Date, newest first.
4. Set results to show the max per page. **Save each results page**: Ctrl-S → "Webpage, HTML only" →
   into a folder like `~/Desktop/liensnc_pulls/<county>_<date>.html`. (Or use an Export button if the
   page offers one — CSV is even better.)
5. Tell me the folder path (or drop the files in the repo's inbound folder). That's it — your part is done.

### What the pipeline does with it (I build this once you give me one saved page)
- `scripts/ingest_liensnc.py` — offline parser: reads your saved files → parcel/address/owner/lien-agent/
  filing-date rows, joined onto the board by address/parcel (so it merges onto an existing lead, or stands
  alone as net-new).
- **Cluster + stall detection (the value):** groups filings by property, flags parcels with **≥2 notices**
  or notices **spanning a long unresolved window** (the stalled-project tell), and ranks by intensity.
- **Board cross-reference:** a clustered-lien-agent parcel that ALSO hits a tax / absentee / GIS signal =
  top-tier. Surfaces as a distinct `builder_distress` signal in the distress stack.

### How to act on it
Target the clustered/stalled parcels first. The pitch is different from a normal foreclosure lead:
the owner is an over-extended investor who needs to offload a half-finished project for cash — a
subject-to, cash, or take-over-the-project offer, fast, before the mechanic's liens and bank foreclosure land.

---

## LANE 2 — Bankruptcy-Stay foreclosure tracking (BUILT + how to watch re-emergence)

**What's already built (2026-08-17):** `enrichment_bankruptcy_stay.py` cross-references our CourtListener
bankruptcy feed against the foreclosure board and flags every foreclosure whose owner filed BK as
**"stayed"** (the §362 automatic stay pauses the sale). On the last board that's **55 stayed foreclosures**
(36 Chapter 13 = curing arrears, 18 Chapter 7 = liquidation), each with a `resume_risk` and a note. Read
them on the board via the `bankruptcy_stay` signal / `raw.bankruptcy_stay`.

**Why it matters:** a stayed foreclosure is NOT gone — it's a highly motivated seller whose sale is
paused and *will* resume. The money is in catching the **exact moment it resumes** (stay dismissed or
lifted) — before it's re-advertised to everyone else.

### The re-emergence watch — step-by-step (free, no PACER charges)
The stay lifts in one of two ways, both visible for FREE on CourtListener:
1. **Case DISMISSED** (Ch13 plan defaulted — happens often) → foreclosure resumes.
2. **Motion for Relief from Stay GRANTED** (lender got permission) → foreclosure resumes.

To watch these without paying PACER:
1. For each stayed lead, note its BK **docket number + court** (in `raw.bankruptcy_stay.docket/court`).
2. On **CourtListener** (free account), open the case docket and click **"Get Alerts"** — CourtListener
   emails you when new docket entries post (dismissal orders, relief-from-stay motions/orders). Free tier
   allows a limited number of alerts — put them on the HOT ones (high equity, imminent-when-filed).
3. When you get an alert for "Order Dismissing Case" or "Order Granting Relief from Stay" → that property
   is about to hit the auction block again. Act immediately.

**Buildable enhancement (I can do this):** instead of manual alerts, extend `enrichment_bankruptcy_stay`
to periodically **re-query each stayed case's docket status via the free CourtListener API** and auto-flip
`raw.bankruptcy_stay.status` to `"resuming"` when it sees a dismissal / relief-from-stay entry. That turns
the manual watch into an automatic board flag. Say the word.

### Cost mechanics — how to keep it FREE
- **CourtListener:** free tier = basic API access + limited alerts + the full RECAP archive (already-uploaded
  federal docs, free forever). Use this FIRST for everything — it covers dockets, filings, and most orders.
- **PACER** (the paid federal source, only if CourtListener lacks a specific document):
  - **$0.10 per page**, capped at **$3.00 per document**.
  - **Fees are WAIVED entirely if your charges stay under $30 per quarter.** So a light, targeted user pays $0.
  - **Jan 1, 2027 change:** per-page rises to **$0.12**, but the quarterly waiver threshold rises to **$40**.
- **The rule to stay free:** pull dockets/orders from CourtListener/RECAP (free); only touch PACER for a
  document CourtListener doesn't have yet, and keep total quarterly PACER charges under $30 (→ $40 in 2027).
  Never bulk-download; grab a single order for a single top lead at a time. At that rate PACER is effectively free.

---

## Quick reference

| Lane | Your manual step | Pipeline does | Cost |
|---|---|---|---|
| LiensNC | Monthly: log in → per-county 90-day search → save HTML pages | Parse + cluster/stall detect + board cross-ref → `builder_distress` | $0 (your account) |
| Bankruptcy-stay | Set CourtListener docket alerts on HOT stayed leads | Flags stayed foreclosures + resume-risk now; auto-"resuming" flip if you greenlight the enhancement | $0 (stay under PACER $30/qtr waiver) |
