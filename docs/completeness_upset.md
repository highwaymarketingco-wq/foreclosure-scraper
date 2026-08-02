## 1. THE NC UPSET-BID MECHANISM (verified against statute text)

**Statute:** N.C.G.S. § 45-21.27 "Upset bid on real property; compliance bonds" (fetched from ncleg.gov HTML text). Tax foreclosures reach the same clock via § 105-374 (mortgage-style) and § 105-375 (in rem).

**Amount.** An upset bid must exceed "the reported sale price or last upset bid by a minimum of five percent (5%) thereof, but in any event with a minimum increase of seven hundred fifty dollars ($750.00)."

**Deposit.** Cash, certified check, or cashier's check "in an amount greater than or equal to five percent (5%) of the amount of the upset bid but in no event less than seven hundred fifty dollars ($750.00)." Practical effect (Gaston publishes this correctly): bid ≤ $15,000 → deposit $750; bid > $15,000 → deposit 5%.

**Who holds the file.** The **Clerk of Superior Court** of the county, "with whom the report of sale or last notice of upset bid was filed." Not the trustee, not the tax office, not the sheriff. The trustee/substitute trustee or foreclosure firm files the *report of sale*; that filing starts the clock. The county tax office and the law-firm websites are courtesy mirrors only. Buncombe states this explicitly: "The foreclosure list is provided as a courtesy only. All official bids are held at the Clerk of Courts Office."

**The clock.** 10 days, running from the **filing of the report of sale or the last notice of upset bid** (not from the auction itself; the gap between hammer and filing is why "sale date + 10" is a bad estimator). Deposit must be filed "by the close of normal business hours on the tenth day." If day 10 falls on a Sunday, a legal holiday, or any day the clerk's office is not open for regular business, it rolls to the next day the office is open.

**Each new upset.** "Subject to the provisions of G.S. 45-21.30, there shall be no resales; rather, there may be successive upset bids each of which shall be followed by a period of 10 days for a further upset bid." Each upset resets a fresh 10 days. The prior bidder "shall be released from any further obligation on account of the bid and any deposit or bond provided by him shall be released" (§ 45-21.27(f)). The clerk notifies the trustee/mortgagee, who must mail written notice of the upset bid by first-class mail to the last prior bidder and the current record owner(s) (§ 45-21.27(e1)).

**Finality.** "When an upset bid is not filed following a sale, resale, or prior upset bid within the time specified, the rights of the parties to the sale or resale become fixed."

**How a buyer actually files one** (§ 45-21.27(a) and (e)): go in person to the Clerk of Superior Court civil division in the county holding the file, give the file/SP number, deliver the deposit in cash or certified/cashier's check (Rutherford, Gaston, Catawba all confirm no personal checks), and **simultaneously file a written Notice of Upset Bid** stating (1) name, address, telephone of the upset bidder, (2) the amount of the upset bid, (3) that the sale remains open 10 days after the date the notice is filed, and (4) signed by the bidder or their attorney/agent. AOC form: "Notice of Upset Bid in Judicial Sale or Execution Sale." The clerk may additionally require a **compliance bond** (cash or surety, § 45-21.27(b)), in an amount the clerk deems adequate but no greater than the bid less the deposit. The upset bidder is bound by the terms of the original notice of sale (§ 45-21.27(g)).

**Operational consequence for the engine:** a `sale_date + 10 days` computation (what `nc_upset_bids.py` does today) is wrong in both directions. The clock starts at report-of-sale filing, and it restarts on every upset. Only a published `closedate` / "upset period ends" column is trustworthy.

---

## 2. PER-COUNTY: WHERE UPSET BIDS ARE ACTUALLY PUBLISHED TODAY

All statuses probed live on 2026-08-02. "Current bid" means the feed carries the running bid, not just an opening bid.

### The two lanes (this is the thing the current scraper misses)

NC has **two separate upset-bid universes** and they have different publishers:
- **Mortgage / power-of-sale** foreclosures → substitute-trustee firms publish. Best: **Hutchens**.
- **Tax** foreclosures (§105-374 / §105-375) → county tax offices and tax-foreclosure firms publish. Best: **Kania**, then **ZLS**.

No county in the footprint publishes a combined list. Four counties publish nothing usable at all.

### County table

| County | Publisher / URL | Carries current bid? | Carries upset deadline? | Live count today | Access class |
|---|---|---|---|---|---|
| **Buncombe** | `https://taxforeclosures.buncombenc.gov/` (tax) | Yes ("Opening/Current Bid") | Yes (event END = bid window close) | 58 items in feed, 5 dated 2026 | **OPEN but JS-only in HTML.** Page renders via Trumba spuds. Real feed: `https://www.trumba.com/calendars/tax-foreclosures-details.rss?filterview=&startdate=1%2F1%2F2020` (96 KB, 58 `<item>`). Without `filterview=` the feed returns **zero items** (790 bytes). Trumba robots.txt = `Disallow:` (allow all). Also `.xml` (Atom) and `.ics`. |
| **Buncombe** | Hutchens (mortgage) | Yes | Implied by "Bid upset MM/DD" | 9 rows | OPEN |
| **Henderson** | `https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales` | **No** | **No** | list present w/ Clerk file # + Estimated Opening Bid | OPEN but useless for upset. Page states outright: "Current bid amounts during the upset period may be obtained from: Henderson County Clerk of Court (828) 694-4100." Phone-only. |
| **Henderson** | Hutchens (mortgage) | Yes | Yes | 1 row | OPEN |
| **Gaston** | `https://www.gastongov.com/668/Tax-Foreclosures` (process) + `/669/Tax-Foreclosure-Sales` (list) | **No** | **No** | list has owner/parcel/address only | OPEN, no bid data. Correct upset rules published; data not. Sales run by **Gaston County Sheriff's Office**. Note: `gastoncountync.gov` 307-redirects to `gastongov.com`. |
| **Gaston** | Hutchens 8 rows / Brock & Scott 5 rows | Hutchens yes | Hutchens yes | 13 | OPEN |
| **Cleveland** | `https://www.clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php` | Column exists, **blank in the county mirror** | Yes (close-date column) | 3 rows in `<table>` + free-text "currently in the 10-day upset bid period" list | OPEN. This page is a **stale mirror of the Kania table** (same 11-column schema). Prefer Kania direct: Kania shows Cleveland current bids of $25,000 / $13,000 / $84,000 where the county page shows blank. |
| **Rutherford** | `https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php` | **No** | **No** | — | OPEN, no bid data. Page explicitly punts: "PLEASE CONTACT THE RUTHERFORD COUNTY CLERK OF COURT ... 1-828-288-6100" and "it is YOUR responsibility to keep track if your bid has been upset." Firm = **Kania** (15 rows). |
| **Burke** | County: nothing. `burkenc.org/165/Tax-Foreclosures` = **404**. Surplus goes to **GovDeals**. | — | — | — | County = DEAD. Firms: **Kania 12 rows** (3 in active upset window w/ current bid), Hutchens 2, Brock & Scott 2. |
| **Lincoln** | `https://www.lincolncountync.gov/2368/Foreclosures` | **No** | **No** | — | OPEN, process text only. States "Lincoln County Tax Foreclosures are performed by The Kania Law Firm." Firms: **Kania 7**, Hutchens 4, Brock & Scott 1. |
| **McDowell** | `https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales` | **YES** ("HIGHEST BID RECORDED") | **YES** ("10-DAY UPSET BID PERIOD ENDS") | 1 active row (orig sale 06/12/2026, ends 08/06/2026, $42,000, file 26-CVD-178-580) | **OPEN, plain HTML, best county-published page in the footprint.** Self-declares "UPSET BID INFORMATION UPDATED ONCE DAILY." |
| **Polk** | `https://www.polknc.gov/upcoming_auction.php` | **No** | **No** | — | OPEN, no bid data. Kania + GovDeals. Kania 1 row, Brock & Scott 1. |
| **Transylvania** | `https://www.transylvaniacounty.org/departments/tax-administration` + `/news/notice-public-foreclosure-sale` | **No** | **No** | 0 | No upset data anywhere. **Zero rows in Kania, Hutchens, and Brock & Scott today.** ZLS is the likely vendor (weak signal: string "zls" appears twice on the tax page) but **UNVERIFIED** — I could not confirm the vendor. |
| **Mitchell** | `https://www.mitchellcountync.gov/departments/tax/` (note: `mitchellcounty.org` returns Cloudflare **522**) | **No** | **No** | 0 | Nothing published. Only source with any Mitchell row is Brock & Scott (1, sale notice only, no bid). Weakest county in the footprint. |

### Statewide / multi-county feeds, classified

| Source | URL | Fields | Footprint rows | Access class |
|---|---|---|---|---|
| **Kania Law Firm** (tax) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/` → JSON at `https://kanialawfirm.com/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id=216745&target_action=get-all-data&default_sorting=old_first&skip_rows=0&limit_rows=0&ninja_table_public_nonce=<nonce from page>` | county, address, parcel, saledatetime, openingbid, **currentbid**, **closedate**, propertytype, **courtfile**, ourfile, salestatus | **42 of 187**; **11 currently in an active upset window with a live current bid** | **FULLY OPEN JSON, no auth.** robots.txt explicitly `Allow: /wp-admin/admin-ajax.php`. Gotcha: the action param is `wp_ajax_ninja_tables_public_action`, NOT `ninja_tables_public_action` — the short form returns HTTP 400 body `0`. |
| **Hutchens Law Firm** (mortgage/substitute trustee) | `https://sales.hutchenslawfirm.com/` → `inside.aspx` → **`https://sales.hutchenslawfirm.com/NCfcSalesList.aspx`** | Case No., **SP#**, County, Sale Date, Property Address, Property CSZ, DoT Book/Page, **Bid Amount** | **27 of 231** (Buncombe 9, Gaston 8, Lincoln 4, Burke 2, Henderson 1, Rutherford 1, McDowell 1, Cleveland 1) | **FULLY OPEN.** robots.txt 404 = no restriction. Telerik RadGrid, rows are `<tr class="GridRow_WebBlue">` / `GridAltRow_WebBlue`, 8 `<td>`. Whole list on one page, no paging. **57 statewide rows carry a real `$` bid, and the upset state is encoded in that cell as literal text: `Bid upset 07/23/2026, increasing bid to $116,400.00`.** That string is the single richest upset signal available for mortgage foreclosures anywhere in this research. |
| **Brock & Scott** | `https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_county=<slug>` (WP Search & Filter, JSON at `?sfid=1202&sf_action=get_data&sf_data=all`) | County, Sale Date, State, **Court SP #**, Case #, Address, **Opening Bid Amt.**, Book Page | 22 (Gaston 5, Cleveland 4, Rutherford 4, McDowell 3, Burke 2, Buncombe 1, Lincoln 1, Mitchell 1, Polk 1) | **OPEN.** robots.txt `Crawl-delay: 1`, `/foreclosure-sales/` not disallowed. **NO upset data at all** — zero occurrences of "upset", opening bid only, many `0.00`. Sale-notice feed, not an upset feed. |
| **Zacchaeus Legal Services (ZLS)** | `https://zls-nc.com/listings`, `/property-for-sale` | Documented to carry upset-period status and end dates | Unknown | **BLOCKED — Blazor Server SPA.** Every route returns the same ~7.3 KB shell that renders "An error has occurred." to a non-browser client. No `_framework/blazor.boot.json` (so Server, not WASM), meaning data flows over a SignalR WebSocket circuit, not REST. No JSON endpoint exists to hit. robots.txt is permissive (`Allow: /`), so this is a **rendering wall, not a policy wall** — reachable only with the existing local stealth browser, not with httpx. |
| **NC eCourts Portal "Foreclosure Sales" dashboard** | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29` | — | — | **BLOCKED — AWS WAF CAPTCHA.** Live probe returns `HTTP/2 405` with `server: awselb/2.0` and **`x-amzn-waf-action: captcha`**, body = "Human Verification" page with `awsWafCookieDomainList` / `gokuProps`. Same wall as the known Smart Search block. `/Portal/` itself is 200 and links Dashboards 29, 26, 17 plus `/app/NCJudgmentSearch`. **Classification: not obtainable free without defeating a CAPTCHA. Do not build. Do not add a human-in-the-loop solve step.** |
| Shapiro (logs.com), Bell Carrington, Aldridge Pite | all 200 | — | — | Reachable, but Hutchens + Brock & Scott already dominate the footprint. Not worth a scraper until the two primaries are live. |

---

## 3. ROOT CAUSE OF THE ZERO

File: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/national/nc_upset_bids.py`

`docs/run_health.json` records `{"source": "national.nc_upset_bids", "count": 0, "status": "EMPTY (verified)", "severity": 0}` and `docs/source_history.json` has `"counts": [0]`. It has never returned a row.

**Four independent failures, one per county. All four `SOURCES` entries are broken.**

1. **Henderson — dead URL.** `https://www.hendersoncountync.gov/clerk` returns **404** (282 bytes). The clerk page never existed at that path; the tax foreclosure page is `/tax/page/tax-foreclosure-sales`. `_fetch_html` calls `raise_for_status()`, the exception is swallowed by the `except Exception` in `_fetch_county`, returns `[]`.

2. **Gaston — dead URL + host migration.** `https://www.gastoncountync.gov/government/county_departments/clerk_of_court` **307-redirects to `gastongov.com` and then 404s.** The county moved to CivicPlus numeric IDs (`gastongov.com/668/Tax-Foreclosures`, `/669/Tax-Foreclosure-Sales`). Same swallow → `[]`.

3. **Cleveland — real bug, not a dead URL.** This is the one worth fixing in code. `https://www.clevelandcounty.com/` 301-redirects to `/main/`. `httpx` follows it (the shared `client()` defaults `follow_redirects=True`), so the parse gets the correct `/main/` homepage. The homepage link is **relative**: `href="departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php"`. But `_find_upset_bid_links(tree, base_url, keywords)` is passed **`base_url` from the `SOURCES` tuple** (`https://www.clevelandcounty.com`), not `r.url` from the response. So `urljoin` produces:
   ```
   https://www.clevelandcounty.com/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php   → 404 (verified)
   ```
   instead of the real page:
   ```
   https://www.clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php   → 200, 3-row <table>
   ```
   **The `/main/` path segment is dropped by joining against the pre-redirect base.** The link IS found (it ranks 4th of 5 matched links, inside the `sub_urls[:8]` cap), so the crawl logic is fine; only the URL construction is wrong. I confirmed the parser would otherwise work: run against the real Cleveland blob, `_CASE_RE` extracts `25CV003091` / `25CV003791` / `25CV003450` and `_ADDR_RE` extracts `124 Afton Dr` / `126 Brunet Dr` / `124 Galilee Church Rd`. Fix = pass the response's final URL as the join base.

4. **Buncombe — wrong extraction strategy.** `https://taxforeclosures.buncombenc.gov/` returns 200 / 19,258 bytes, but contains **zero `<table>`, zero `<tr>`, and zero listing text**. The listings are injected client-side by **Trumba** spuds (`$Trumba.addSpud({webName: "tax-foreclosures-details", spudType: "main"})` loading `//www.trumba.com/scripts/spuds.js`). Both the table branch and the text-block branch of `_parse_upset_bid_page` find nothing because there is nothing in the HTML. selectolax does not execute JS.

**Meta-cause (why this stayed invisible):** `http_client._BLOCK_CODES = {401, 403, 406, 409, 429}`. **404 is not in it.** Every one of the four failures produced a 404 or an empty parse, never a block code, so `safe_run` classified the run as `EMPTY (verified)` — a fully dead scraper that reports as healthy. Any scraper whose entire source list 404s will look "verified empty" forever.

**Fifth, separate defect — the board can never show `upset_bid` regardless of scraping.** `models.py` `ListingType` has no `UPSET_BID` member (`FORECLOSURE_SALE, TAX_SALE, TAX_LIEN, LIS_PENDENS, BANKRUPTCY, REO, AUCTION, SHERIFF_SALE, HOA_SALE, DISTRESSED, DIVORCE_NOTICE, PROBATE_NOTICE, ESTATE_LEAD, ELDERLY_DISABLED, UNKNOWN`). The scraper hard-codes `listing_type=ListingType.SHERIFF_SALE`. So "board has 0 leads of type upset_bid" is **structurally guaranteed, independent of the four fetch bugs.** The scraper's `category = "upset_bid"` is a scraper-level label, not a listing type. Either add `UPSET_BID = "upset_bid"` to the enum or accept that upset state lives in `Listing.upset_bid_deadline` + `raw["upset_bid"]` (which `enrichment_upset_bid.py`, `distress_score.py` at 22 pts, `enrichment_lead_signals.py`, and `web_artifact.py` already consume) and filter on that instead.

**Sixth, correctness defect that survives all the above:** `upset_deadline = sale_date + timedelta(days=10)` is wrong per statute. The clock runs from report-of-sale filing and **restarts on every upset**. Live proof from Kania: Rutherford 207 McArthur Street sold **4/28/2026** and its close date is **8/6/2026** — 100 days after the sale, not 10, because it has been upset repeatedly (opening $10,700 → current $28,000). The `+10` rule would have expired that lead in early May and the engine would have missed a still-open buying window three months later. Only trust a published `closedate` / "period ends" value; leave the deadline null when none is published.

---

## 4. DOES SC HAVE AN EQUIVALENT?

Yes, and it is **more generous than NC's**, but the public data is much worse.

**Statute:** S.C. Code § 15-39-720, "Upset bids within thirty days on foreclosure or execution sale" (fetched from scstatehouse.gov, Title 15 Ch. 39).

- **Window: 30 days, not 10.** "In all judicial sales of real estate for the foreclosure of mortgages and sales in execution the bidding shall not be closed upon the day of sale but shall remain open until the thirtieth day after such sale, exclusive of the day of sale."
- **Deposit: 5% or less.** § 15-39-740: the deposit "shall be five per cent of the bid or some lesser percentage thereof," and no deposit may be required *before* the bidding concludes.
- **Who may bid:** "any person other than the highest bidder at the sale or any representative thereof." **The foreclosing mortgagee is locked out** — it must enter its bid at the sale and "shall be precluded from entering any other bid in any amount at any other time."
- **No rolling reset.** Unlike NC, SC does not restart a fresh window on each raise. Bids accumulate during the one 30-day window, then "the bidding shall be reopened by the officer making the sale on the thirtieth day after the sale ... at eleven o'clock in the forenoon and the bidding shall be allowed to continue until the property shall be knocked down." **It ends in a live re-auction on day 30 at 11:00 a.m., in person.** If day 30 is a Sunday, it closes the following Monday.
- **Prior bidder released:** § 15-39-750, deposit returned with written notice within two days.
- **THE CRITICAL CARVE-OUT:** § 15-39-760 — §§ 15-39-720 through 15-39-750 "shall not apply to any suit brought for foreclosure if the complaint therein states that no personal or deficiency judgment is demanded and that any right to such judgment is expressly waived." **In practice most SC lenders waive deficiency, so most SC foreclosure sales close the day of sale with NO upset period at all.** Only "deficiency sales" carry the 30-day window. This makes SC upset bids a minority of sales, not the default.
- § 15-39-730: non-foreclosure judicial sales close on the sale date unless a party objects.

**Process:** judicial, run by the county **Master-in-Equity** (or referee/sheriff), typically monthly. Greenville: first Monday, 11:00 a.m. Spartanburg: 4th floor Courtroom 4-A.

**Is there a comparable public feed? No.**

| SC source | URL | Verdict |
|---|---|---|
| Greenville MIE sale ads | `https://mie.greenvillejournal.com/` and `/search-results/` | **OPEN and searchable** (176 KB, sale-date dropdown back to 2023, plaintiff/address/defendant search). But these are **sale advertisements** — plaintiff, address, judgment amount, sale date. **No current bid, no upset-period tracker.** Closest SC analogue to Hutchens, and it is one county only. |
| Spartanburg MIE | `https://www.spartanburgcounty.gov/151/Master-In-Equity`, `/313/Foreclosure-Sale`, cancellations at `/315/...` | Open. Deficiency sale results published as a **PDF** (`/DocumentCenter/View/11824/Deficiency-Sale`). Note `/314/Deficiency-Sale-Results` is a 404; the live path is `/316/...`. Batch PDF, not a per-property live-bid feed. |
| Spartan Weekly News legal notices | `http://www.spartanweeklyonline.com/id11.html` | Open, statutory notice repository. Sale notices only. |
| Anderson / Pickens / Oconee MIE | `andersoncountysc.org/master-in-equity/`, `pickenscountysc.gov/master-equity`, `oconeesc.com/master-in-equity` (**HTTP 500 today**) | Office pages only. No roster feed. |
| SC Public Index | publicindex.sccourts.org | Already classified in prior work as a **ToS wall**. Unchanged. |

**Blunt answer on SC:** there is no free public source, at any county in the Upstate footprint, that publishes a running current bid and an upset-period expiry the way Kania and McDowell do in NC. The bidding state during the SC 30-day window exists only in the Master-in-Equity's paper/counter records and is resolved by a live in-person re-auction. **This cannot be obtained as a feed by anyone at any price.** The buildable SC ceiling is *sale notices* (Greenville MIE + Spartan Weekly), from which you can infer that a 30-day window may be open if the notice does not waive deficiency, but you cannot know the current bid.

---

## 5. BEST SINGLE FEED TO BUILD

**There is no single feed that covers both lanes. Anyone claiming otherwise is wrong.** Ranked:

**#1 — Kania JSON (`kanialawfirm.com` admin-ajax, table_id 216745).** Build this first.
- It is the only free source in existence carrying **`currentbid` + `closedate` + `courtfile` + `parcel` per property** in structured JSON.
- 187 rows statewide, **42 in the 11-county footprint**, **11 with a live current bid and an open close date right now** (Burke 3, Cleveland 3, Rutherford 4, plus Lincoln/Polk).
- Zero auth, zero rate limit observed, explicit robots.txt `Allow: /wp-admin/admin-ajax.php`.
- Covers Rutherford (15), Burke (12), Cleveland (7), Lincoln (7), Polk (1) — **five of the eleven counties**, and it makes the Cleveland county-page scrape redundant (the county mirror shows blank current bids where Kania shows $25,000 / $13,000 / $84,000).
- Implementation notes: use `action=wp_ajax_ninja_tables_public_action` (the short form 400s); scrape `ninja_table_public_nonce` fresh from the listings page each run rather than hard-coding; `address` and `parcel` can contain `<br />` joining multiple parcels; `saledatetime` may be the literal HTML `<span class='red'>Sale date not yet set</span>`; `salestatus` is empty on all 187 rows today, so derive "in upset window" from `currentbid` non-empty AND `closedate >= today`.

**#2 — Hutchens `NCfcSalesList.aspx`.** Build second, same sprint. It is the only mortgage-lane source with upset data, it covers **eight of the eleven counties** (27 rows), it is one flat page with no paging, and its Bid Amount cell literally encodes the upset event: `Bid upset 07/23/2026, increasing bid to $116,400.00`. Parse `<tr class="GridRow_WebBlue">` / `GridAltRow_WebBlue`, 8 tds, county cell is `"Buncombe, NC"` so split on comma. Distinguish the three Bid Amount states: `Bid not available yet` (pre-sale, 174 of 231), a bare `$N` (sold, upset window presumed open), and the `Bid upset <date>, increasing bid to $N` form (window restarted on that date — set the deadline to that date + 10 court days, and only then).

**#3 — McDowell county page**, one cheap plain-HTML scrape, because it is the only county in the footprint publishing its own upset table with HIGHEST BID RECORDED and 10-DAY UPSET BID PERIOD ENDS, refreshed daily.

**#4 — Buncombe Trumba RSS**, cheap, but remember the `?filterview=&startdate=...` parameter or you get an empty feed.

**Do not build:** the eCourts Dashboard/29 (AWS WAF CAPTCHA), ZLS (Blazor SignalR, no HTTP surface), Brock & Scott *for upset purposes* (opening bid only, zero upset data — build it later as a sale-notice source if you want, not for this).

**Retire or rewrite `nc_upset_bids.py` entirely.** All four of its sources are dead, its deadline math contradicts the statute, and its output type can never surface as an upset_bid lead. It is not worth patching four URLs; the correct sources are firm-level and statewide, not county-clerk-level.

**Three code changes needed regardless of which feed lands:**
1. Add `UPSET_BID = "upset_bid"` to `ListingType` in `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/models.py`, or explicitly document that upset leads are `TAX_SALE`/`FORECLOSURE_SALE` carrying `upset_bid_deadline`.
2. Add `404` (and probably `410`) to `_BLOCK_CODES` or add a distinct `DEAD_URL` health status in `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/http_client.py`, so an all-404 scraper stops reporting `EMPTY (verified)`.
3. Never synthesize `sale_date + 10 days`. Leave `upset_bid_deadline` null unless the source publishes it.

**Sources:** [G.S. 45-21.27](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-21.27.html) · [NC Judicial Branch: Foreclosures](https://www.nccourts.gov/help-topics/housing/foreclosures) · [Hutchens NC sales list](https://sales.hutchenslawfirm.com/NCfcSalesList.aspx) · [Kania foreclosure listings](https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/) · [ZLS listings](https://www.zls-nc.com/listings) · [Brock & Scott](https://www.brockandscott.com/foreclosure-sales/) · [NC eCourts Portal](https://portal-nc.tylertech.cloud/Portal/) · [Buncombe tax foreclosures](https://taxforeclosures.buncombenc.gov/) · [Henderson](https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales) · [Gaston](https://www.gastongov.com/668/Tax-Foreclosures) · [Cleveland](https://www.clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php) · [Rutherford](https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php) · [McDowell](https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales) · [Lincoln](https://www.lincolncountync.gov/2368/Foreclosures) · [Polk](https://www.polknc.gov/upcoming_auction.php) · [Transylvania](https://www.transylvaniacounty.org/departments/tax-administration) · [Mitchell](https://www.mitchellcountync.gov/departments/tax/) · [S.C. Code Title 15 Ch. 39](https://www.scstatehouse.gov/code/t15c039.php) · [Greenville MIE sale ads](https://mie.greenvillejournal.com/) · [Spartanburg MIE](https://www.spartanburgcounty.gov/151/Master-In-Equity)