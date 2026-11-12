Verification complete across all 19 counties. Compiling.

## Newspaper / legal-notice API sweep — 18 footprint counties + Greenville SC

**Headline: the task's premise was right but pointed at the wrong county.** Laurens is real, and Pickens is bigger. Everything below was fetched live 2026-08-03; nothing is inferred.

| Source | Exact query-ready URL | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| **Pickens County Courier** (Pickens) | `https://www.yourpickenscounty.com/wp-json/wp/v2/posts?categories=8&per_page=50&page=N&_fields=date,link,title,content` | cat 8 = **2,666 posts, archive to 2010-11-26**. In newest 200: **49 "Notice to Creditors" + 41 "Legal Notice"** posts. Newest NTC = **17 estates**, each with Estate, Date of Death, Case Number, Personal Representative, **PR mailing address**. Legal Notices carry summons (incl. foreclosure), wills-filed, towing liens | OPEN, no auth, robots clean | **NEW** |
| **Laurens County Advertiser** (Laurens) | `https://www.laurenscountyadvertiser.net/wp-json/wp/v2/posts?categories=7486&per_page=100&_fields=date,link,title,content` | **1 rolling post, 79,859 chars = 330 estates**: 333 Date of Death, 330 Case Number, 332 Personal Representative, 426 Address, 97 Attorney. Cumulative (entries back to Apr 2025 still present) | OPEN — but **robots.txt disallows `anthropic-ai`/`Claude-Web`** (ClaudeBot not listed) | SCRAPED (documented in gap_ledger; count was unmeasured) |
| Laurens Advertiser obituaries | `https://www.laurenscountyadvertiser.net/wp-json/wp/v2/categories` → id 17 | **2,344 posts** | OPEN, same robots caveat | SCRAPED |
| **Tryon Daily Bulletin** (Polk) | `https://tryondailybulletin.com/wp-json/wp/v2/posts?categories=263&per_page=50` | Slug **confirmed `public-notices`, id 263 — but only 3 posts (2015–2017): a police report, a wastewater notice, a hearing notice. Zero legals.** Obituaries cat 35 = **5,677** | OPEN, robots clean | SCRAPED |
| **Gaffney Ledger** (Cherokee) | `https://www.gaffneyledger.com/wp-json/wp/v2/media?search=tax+sale&per_page=50&_fields=date,title,source_url` | `/wp/v2/posts` returns **`[]` even unfiltered** (REST-gated). categories = **463 readable**; media `search=tax sale` → **6** | OPEN-but-gated; media lane only | SCRAPED (documented) |
| **The Journal Online** (Anderson/Williamston) | `https://thejournalonline.com/wp-json/wp/v2/posts?search=<term>&per_page=50` | REST **open**, but `notice to creditors` = **0**. `tax sale` total 373 = **editorial false positives** (school-board articles). Obituaries cat 27 = 680 | OPEN, no legals | **NEW** (docs wrongly list it under "no API") |
| **Greenville Journal** (Greenville) | `https://greenvillejournal.com/wp-json/wp/v2/categories?search=legal` | REST open; **zero legal/notice categories**. `tax sale` total 171 = penny-tax editorial | OPEN, no legals | **NEW**, nil |
| SC Press Assn aggregator | `https://www.scpublicnotices.com/Search.aspx` (session URL `(S(...))`, POST `ctl00$ContentPlaceHolder1$as1$lstCounty$N` + `dateRange` + `ddlPopularSearches`) | 200, 224KB. Covers **all 8 SC counties incl. Greenville**; only route for the 6 SC papers with no API | OPEN, **no query-string GET** — session + VIEWSTATE POST | Documented, not wired |
| NC Press Assn aggregator | `https://www.ncnotices.com/Search.aspx` (same ASP.NET SmartSearch engine) | 200, 360KB. Only route for the 10 NC papers with no API | OPEN, session/POST | SCRAPED (`public_notices/ncpublicnotices.py`) |

### Walls — classified, not defeated

| Wall | Papers | Evidence |
|---|---|---|
| **Gannett Presto WAF** | Asheville Citizen-Times (Buncombe), Times-News/blueridgenow (Henderson), Gaston Gazette, Shelby Star (Cleveland), Herald-Journal/goupstate (Spartanburg), Independent Mail (Anderson), Greenville News | Uniform **403 on every path including `/robots.txt`** — edge block, not WordPress. 7 papers, 7 counties |
| **Not WordPress (TownNews/BLOX/other)** | Morganton News Herald (Burke), McDowell News, Mitchell News-Journal, Union Daily Times, Union County News, Hendersonville Lightning | `/wp-json/` → 404; no legal RSS |
| **robots.txt disallows ClaudeBot** | Daily Courier/thedigitalcourier (Rutherford), Transylvania Times, Lincoln Times-News, upstatetoday/The Journal (Oconee), Anderson Observer, Mountain Xpress | Compliance wall, not technical. **Do not crawl** — route via ncnotices/scpublicnotices |
| **DNS/connection failure** | easleyprogress.com, keoweecourier.com, tribunepapers.com, ashevillewatchdog.org | No response |

### Three corrections to the prior pass

1. **The Tryon slug fix is worthless.** The real slug *is* `public-notices` (id 263), as suspected — but the category holds 3 stale posts from 2015–2017 and **zero legal notices**. Renaming the slug in `tryon_bulletin.py` gains nothing; Polk legals are not on the WP side.
2. **`X-WP-Total` from `search=` is not a notice count.** WordPress core search is a fuzzy OR-match across title/content. `thejournalonline.com?search=tax+sale` → 373 is school-board coverage; `tryondailybulletin.com?search=estate` → 1,624 is real-estate columns and long-term-care advice. **Every count in the table above was validated by fetching post bodies, not by trusting the header.** Any scraper built on `search=` totals will ingest editorial articles as notices.
3. **The docs' "12 papers with no API" list is wrong twice.** `yourpickenscounty.com` is in the repo only as a static delinquent-tax HTML page — its 2,666-post legal archive was missed entirely, and it is the single largest free probate/legal vein found in the footprint. `thejournalonline.com` also has open REST (though nil for legals).

### Compliance and privacy notes

- **No CAPTCHA or WAF was bypassed.** Gannett's 403 and the six ClaudeBot-disallowing sites are reported as walls and left alone.
- **Crawler-identity decision is now blocking two live sources.** Laurens disallows `anthropic-ai`/`Claude-Web` but not `ClaudeBot`; the six TownNews sites disallow `ClaudeBot` specifically. There is no single UA that satisfies both. This needs a policy call before wiring, not a code fix.
- **No sensitive PII encountered.** The Notice-to-Creditors records carry decedent name, date of death, probate case number, and adult personal-representative name and mailing address — all statutorily published public notice under SCPC 62-3-801. **No SSNs, no minor DOBs, no exposed sensitive PII on any endpoint tested.**

### Highest-value build

`yourpickenscounty.com` category 8, paged at 50. One scraper, no auth, clean JSON, ~15 years deep, and the NTC posts alone yield roughly 800+ decedents with personal-representative mailing addresses across the newest 200 posts — which is the name-to-contact spine the resolver has been starved for. Parse by title prefix (`Notice to Creditors` / `Legal Notice`), then split the body on `Estate:` and read the labeled fields; do not filter with `search=`.

Probe harness saved at `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/probe.py` (plus `sample.py`, `verify.py`, `yield.py`) if you want to re-run the sweep. No repo files were written and the engine was not run.