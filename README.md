# Foreclosure Scraper

Comprehensive weekly aggregator of foreclosure, lis-pendens (pre-foreclosure),
tax sale, tax lien, probate, and REO listings across upstate SC + western NC.

**Output:** Google Sheet + a live web dashboard, auto-emailed every Tuesday
morning to greghhigh@gmail.com and cashrandolphhigh@gmail.com.

**Runs:** Locally on the Mac via a `launchd` schedule (see below). **100% free
— no Apify, no paid proxies, no paid data.**

> **Why local, not GitHub Actions?** The anti-bot sources (Zillow, Tyler
> courts, law-firm trustee sites, etc.) require a real stealth browser
> (Scrapling/camoufox). That works on a real Mac but gets fingerprinted and
> blocked on GitHub's headless cloud runners — and the full pipeline exceeds
> GitHub's 4-hour job cap. The GitHub Actions workflow is therefore retired
> (disabled); `scripts/run_local.sh` is the canonical runner.

---

## What it covers

**Scope: 18 counties** (this README used to say 25; the deny-list in
`config.py` is authoritative).

- **SC (7):** Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens
- **NC (11):** Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe,
  Transylvania, McDowell, Lincoln, Mitchell, Burke

> Denied per owner direction: SC Greenville/Greenwood/Abbeville/Newberry;
> NC Mecklenburg/Madison/Yancey + all eastern/coastal NC. Anything in those
> counties is filtered out by `_in_scope` even if a scraper returns it.

**~59 source scrapers**, auto-discovered. Highlights:

| Category | Sources |
|---|---|
| **Pre-foreclosure (lis pendens)** | NC eCourts (Tyler), SC Public Index, CourtListener bankruptcy/civil |
| **Foreclosure sales** | County Master-in-Equity rosters (Spartanburg, Anderson, + Oconee/Cherokee/Laurens/Union via publicindex.sccourts.org), substitute-trustee law firms (Hutchens, Brock & Scott, Bell Carrington, Finkel, McMichael, Kania, The Ingle Firm) |
| **National auction / aggregator** | Auction.com, Bid4Assets, Hubzu, Xome, Zillow, Trulia, Realtor, Propwire |
| **Federal REO** | HUD HomeStore, Fannie HomePath, Freddie HomeSteps, VA (VRM) |
| **Public notices / newspapers** | ncnotices.com, local legal-notice papers |
| **SC tax** | Forfeited Land Commission, tax-delinquent |

**Listing types:** foreclosure sale, sheriff sale, tax sale, tax lien, lis
pendens, REO/bank-owned, auction, probate notice.

**Per-listing fields:** address, county, state, ZIP, parcel/TMS, sale date/
time/location, opening bid, **amount owed** (cross-sourced + labeled), plaintiff,
defendant, trustee, case number, beds/baths/sqft/year/acreage, tax/market value,
**condition tier**, **est. rehab**, **est. ARV**, **suggested max bid (70%
rule)**, **deal verdict**, **owner name + mailing address (free skip trace)**,
**absentee-owner flag**, flags (fire/vacant/foundation), **NEW-this-run flag**,
source, source URL, first seen, last seen.

---

## Running it

### Secrets (local)
Stored as files in `.secrets/` (gitignored), loaded by `scripts/run_local.sh`:

| File | Purpose |
|---|---|
| `service_account.json` | Google service account (Sheets + Drive) |
| `sheet_id.txt` | Destination Google Sheet ID |
| `gmail_app_password.txt` | Gmail SMTP app password (greghhigh@gmail.com) |
| `anthropic_api_key.txt` | Claude Vision (condition analysis) |
| `courtlistener_token.txt` | CourtListener bankruptcy/civil |
| `nc_ecourts_username.txt` / `nc_ecourts_password.txt` | *(optional)* NC eCourts auth; falls back to anonymous |

### One-time: install the weekly schedule
```bash
bash scripts/install_local_schedule.sh        # launchd, Tuesdays 9am local
launchctl list | grep foreclosure             # verify
```

### Run manually any time
```bash
bash scripts/run_local.sh                      # full pipeline → Sheet + email
tail -f logs/local-run-*.log                   # watch it
```

`run_local.sh` exits non-zero and prints a loud line if listings drop sharply
or the total is suspiciously low (fail-loud guard). The weekly email shows a
red banner on a count drop and a 🆕 banner with the count of new properties
(and fresh pre-foreclosures) since the last run.

---

## Enrichment knobs (env, optional)

| Env | Default | Effect |
|---|---|---|
| `VISION_PROVIDER` | `anthropic` | Condition analysis provider (avoid `gemini` — quota walls) |
| `VISION_MAX_LISTINGS` | `250` (local) | Cap on Vision API calls per run |
| `SKIP_TRACE_PROVIDER` | `free` | `free` = tax-records owner/mailing + best-effort people-search phone |
| `ROD_ENRICH_ON` | unset (off) | ROD deed enrichment — off because the vendor portals migrated and match 0 |

---

## Property assessment

Each listing gets heuristic + data-driven estimates:

- **Condition tier** — Claude Vision on photos/aerials, else keyword scan + age
- **Est. Rehab** — per-sqft tier from the condition tier
- **Est. ARV** — geographically-filtered HomeHarvest comps (within 10 mi of the
  subject; county-wide "kind-only" comps are flagged low-confidence and excluded
  from ARV so far-away sales never inflate it)
- **Suggested Max Bid** — `0.70 × ARV − rehab − fees`
- **Amount owed** — cross-sourced waterfall: explicit judgment → opening bid
  (≈ debt, labeled) → assessed value (labeled "not debt"); never misrepresented

These are a first-pass screen, not a substitute for an inspection / BPO.

---

## Adding a source

1. Drop a file in `src/foreclosure_scraper/scrapers/<category>/<name>.py`.
2. Subclass `BaseScraper`; set `slug`/`name`/`category`; implement
   `async def fetch()` returning `Listing` objects.
3. Check the county is in scope (`config.in_scope`) — denied-county data is
   filtered out downstream, so don't scrape what gets dropped.
4. The registry auto-discovers it on next run.

For JS-rendered / anti-bot sites, use `from ..render import fetch_rendered`
(free local stealth browser) — see `scrapers/law_firms/aldridge_pite.py`.

---

## File structure

```
src/foreclosure_scraper/
├── main.py                  # orchestrator (scrape → dedupe → scope → enrich → value → write)
├── models.py                # Listing schema + dedupe_key
├── base_scraper.py          # BaseScraper interface
├── config.py                # county lists + SCOPE_DENY_COUNTIES (authoritative scope)
├── render.py                # FREE stealth-browser fetcher (replaces old Apify path)
├── http_client.py           # shared httpx client
├── enrichment*.py           # GIS, comps, vision, amount_owed, skip_trace, judgment, …
├── new_listings.py          # new-this-run / early-access detection
├── valuation/               # ARV / rehab / max-bid / deal verdict
├── dedupe.py · carryover.py · validation.py · link_validator.py
├── sheets.py · email_sender.py · web_artifact.py
└── scrapers/                # all source modules, auto-discovered
scripts/
├── run_local.sh             # canonical local runner (loads .secrets/, runs pipeline)
└── install_local_schedule.sh# launchd weekly schedule installer
```
