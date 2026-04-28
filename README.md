# Foreclosure Scraper

Comprehensive weekly aggregator of foreclosure, tax sale, tax lien, and REO listings across upstate SC + nearby NC.

**Output:** Google Sheet, auto-emailed every Monday morning to greghhigh@gmail.com and cashrandolphhigh@gmail.com.

**Runs:** GitHub Actions cron, no laptop required.

---

## What it covers

**Counties (25 total)**
- SC (11): Greenville, Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens, Abbeville, Greenwood, Newberry
- NC (14): Rutherford, Cleveland, Henderson, Polk, Gaston, Mecklenburg, Buncombe, Transylvania, McDowell, Lincoln, Madison, Yancey, Mitchell, Burke

**Sources** (~30 active scrapers)

| Category | Sources |
|---|---|
| **National auction / aggregator** | Auction.com, Foreclosure.com, Hubzu, Xome, Bid4Assets, Zillow Foreclosures |
| **Federal REO** | HUD HomeStore, Fannie Mae HomePath, Freddie Mac HomeSteps |
| **Public notices** | publicnoticesc.com (SCPA), ncpublicnotices.com (NCPA) |
| **Substitute trustee law firms** | Brock & Scott, Hutchens, Shapiro & Ingle (logs.com), Aldridge Pite, Rogers Townsend, Finkel, Riley Pope & Laney, Korn, Padgett, McMichael Taylor Gray, Bell Carrington |
| **SC court / tax** | SC Judicial Public Index (all 11 counties), SC Forfeited Land Commission (all 11 county tax collectors), Greenville / Spartanburg / Anderson / Pickens Master in Equity |
| **NC court / tax** | NC Clerk of Court foreclosure postings (all 14 counties), Mecklenburg Tax Foreclosure (Kania Law), Buncombe Tax, Zacchaeus Legal Group statewide |
| **Open-data leads** | jungle_synthesizer probate/foreclosure/sheriff/tax-sale national feed |

**Listing types tracked**
Foreclosure sale, sheriff sale, tax sale, tax lien, lis pendens, HOA sale, REO/bank-owned, auction.

**Property kinds tracked**
Single family, condo, townhouse, multi-family, mobile/manufactured, commercial, raw land, mixed.

**Per-listing fields**
Address, county, state, ZIP, parcel ID, sale date, sale time, sale location, opening bid, judgment amount, plaintiff, defendant, trustee, case number, beds, baths, living sqft, year built, acreage, zoning, tax/market value, **condition score**, **estimated rehab cost**, **estimated ARV**, **suggested max bid (70% rule)**, **flags** (fire damage, vacant, foundation, etc.), source, source URL, first seen, last seen.

---

## Setup (one-time, ~15 minutes)

You do these three things on your phone or laptop. After that the weekly run is fully automated.

### 1. Create a Google service account + share the Sheet

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Create a new project called `foreclosure-scraper` if you don't have one.
3. Click **Create Service Account** → name it `foreclosure-scraper` → **Done**.
4. Click the new service account → **Keys** tab → **Add Key** → **JSON** → download the file.
5. Open the downloaded JSON in a text editor and copy the **entire contents** (it's a one-line JSON blob).
6. Enable the **Google Sheets API** and **Google Drive API** in the project: https://console.cloud.google.com/apis/library
7. Run the bootstrap script locally to create the destination Sheet and share it with both recipients:

   ```bash
   uv sync
   GOOGLE_SERVICE_ACCOUNT_JSON='<paste the full JSON here>' uv run python scripts/bootstrap_sheet.py
   ```

   It prints a `SHEET_ID = <long string>` — copy that.

### 2. Get a Gmail app password

1. Go to https://myaccount.google.com/apppasswords (signed in as **greghhigh@gmail.com**).
2. Type `Foreclosure Scraper` as the app name → **Create**.
3. Copy the 16-character password (no spaces).

### 3. Get the Apify API token

1. Go to https://console.apify.com/account/integrations.
2. Copy the **Personal API token**.

---

## Add the 6 secrets to GitHub Actions

Go to https://github.com/highwaymarketingco-wq/foreclosure-scraper/settings/secrets/actions and add:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The full one-line JSON blob from step 1.5 |
| `SHEET_ID` | The Sheet ID from `bootstrap_sheet.py` output |
| `GMAIL_SENDER` | `greghhigh@gmail.com` |
| `GMAIL_APP_PASSWORD` | The 16-character password from step 2 |
| `EMAIL_RECIPIENTS` | `greghhigh@gmail.com,cashrandolphhigh@gmail.com` |
| `APIFY_TOKEN` | Token from step 3 |

That's it. The workflow at `.github/workflows/weekly.yml` runs every Monday at 9 AM UTC. To test sooner, go to **Actions → Weekly Foreclosure Scrape → Run workflow**.

---

## Apify cost on the free tier

Apify free plan = $5 in platform credits per month. Per-run targets:

| Source | Cost model | Cap | Cost / run |
|---|---|---|---|
| Auction.com (`memo23/auction-com-scraper`) | $0.009 + $0.001/result | 400 | ~$0.41 |
| Probate / foreclosure leads (`jungle_synthesizer/...`) | $0.10 + $0.001/result | 250 | ~$0.35 |
| Zillow enrichment (`maxcopell/zillow-detail-scraper`) | $0.0036/result | 60 | ~$0.22 |
| HUD (`martc03/hud-foreclosures`) | $0.00005 + $0.00001/result | 5,000 | ~$0.05 |
| Hubzu / Xome / Foreclosure.com | rag-web-browser (free) | n/a | $0.00 |
| **Total per weekly run** | | | **~$1.05** |
| **Monthly (4 runs)** | | | **~$4.20** |

That fits inside the $5/month free tier. Caps live in `src/foreclosure_scraper/budget.py`. Override individual caps with env vars like `CAP_AUCTION_DOT_COM=600` if you upgrade Apify and want more.

---

## Running locally (optional)

```bash
cp .env.example .env
# Fill in .env with the same values as your GitHub secrets
uv sync
uv run python -m foreclosure_scraper
```

---

## Property assessment

Each listing gets four estimated values based on heuristics + the data we can pull:

- **Condition Score (0-100)** — keyword scan of description for "fire damage / vacant / renovated / move-in ready" plus age penalty
- **Est. Rehab** — per-square-foot tier based on the score: $10/sqft cosmetic up to $160/sqft gut rehab
- **Est. ARV** — Zillow zestimate when we got it, else tax value × 1.25, else opening bid × 2.4
- **Suggested Max Bid (70% rule)** — `0.70 × ARV - rehab - 5% fees`

These are rough. Treat them as a first-pass screen, not a substitute for an inspection / BPO.

---

## Adding a new source

1. Drop a file in `src/foreclosure_scraper/scrapers/<category>/<name>.py`.
2. Subclass `BaseScraper`. Set `slug`, `name`, `category`. Implement `async def fetch()` returning `Listing` objects.
3. The registry auto-discovers it on next run.

See `src/foreclosure_scraper/scrapers/law_firms/brock_scott.py` for a minimal example.

---

## File structure

```
src/foreclosure_scraper/
├── main.py              # orchestrator
├── models.py            # Listing schema
├── base_scraper.py      # BaseScraper interface
├── config.py            # county lists, scope filters
├── budget.py            # Apify free-tier cost governor
├── http_client.py       # shared httpx client
├── apify_helper.py      # Apify SDK wrapper
├── enrichment.py        # Zillow detail + heuristic fills
├── assessment.py        # condition / ARV / rehab / max bid
├── dedupe.py            # cross-source dedupe (parcel + fuzzy address)
├── link_validator.py    # drops 404 / dead listings every run
├── sheets.py            # Google Sheets writer
├── email_sender.py      # Gmail SMTP digest
└── scrapers/            # all source modules, auto-discovered
    ├── national/        # 10 nationwide aggregators
    ├── public_notices/  # SCPA + NCPA legal notice search
    ├── law_firms/       # 11 substitute trustee firms
    ├── counties_sc/     # SC court + tax
    ├── counties_nc/     # NC court + tax
    └── newspapers/      # newspaper legal-notice direct (mostly covered by public_notices)
```
