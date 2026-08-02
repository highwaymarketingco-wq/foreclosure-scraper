# THE COMPLETENESS DOCUMENT
## Free, public, distressed-property data in Western North Carolina and Upstate South Carolina
### Verified 2026-08-02. Every URL below was fetched live unless explicitly marked otherwise.

---

# HOW TO READ THIS

Seven sections. Sections 1 through 3 are the three data lanes you asked about, each with per-county URLs and a straight verdict. Section 4 is every field a distressed-property operator could want, 112 of them, each with its best free source and a classification. Section 5 is what cannot be had, separated into what the law seals and what nobody ever wrote down, plus the one path that opens part of it. Section 6 is the honest arithmetic. Section 7 is what to build, in order.

**Classification key, defined once, used throughout:**

| Label | Meaning |
|---|---|
| FREE-AUTOMATED | A public, keyless, no-login endpoint (or a compliant browser fetch) fills it unattended |
| FREE-MANUAL | Free to obtain, but a person must click, save, request, or read a per-parcel card |
| PAID | A vendor sells it lawfully; the free routes fail or are barred by terms of service |
| REQUIRES-CONSENT | Only the owner or a party to the transaction can furnish it |
| REQUIRES-PHYSICAL-VISIT | Obtainable only by going to the property |
| LEGALLY-SEALED | A statute or court rule bars disclosure |
| PHYSICALLY-UNRECORDED | No record is ever created; the fact exists only in the world |

**Footprint used throughout.** North Carolina, 11 counties: Buncombe, Henderson, Gaston, Cleveland, Rutherford, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell. South Carolina, 7 counties: Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens.

---

# SECTION 1: UPSET BIDS

## 1.1 The North Carolina mechanism, from the statute text

**Authority:** N.C.G.S. 45-21.27, "Upset bid on real property; compliance bonds."
https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-21.27.html

Tax foreclosures reach the same clock through G.S. 105-374 (mortgage-style) and G.S. 105-375 (in rem).

**Amount.** An upset bid must exceed the reported sale price or last upset bid by a minimum of five percent, but in any event with a minimum increase of $750.

**Deposit.** Cash, certified check, or cashier's check equal to at least five percent of the upset bid, but never less than $750. Practical effect: a bid of $15,000 or less needs a $750 deposit; above $15,000 the deposit is five percent. Rutherford, Gaston, and Catawba all publish confirmations that personal checks are not accepted.

**Who holds the file.** The Clerk of Superior Court of the county where the report of sale or the last notice of upset bid was filed. Not the trustee. Not the tax office. Not the sheriff. The trustee, substitute trustee, or foreclosure firm files the report of sale, and that filing starts the clock. County tax office pages and law firm websites are courtesy mirrors. Buncombe states this outright: the foreclosure list is provided as a courtesy only, and all official bids are held at the Clerk of Court's office.

**The clock.** Ten days, running from the filing of the report of sale or the last notice of upset bid, not from the auction. The deposit must be filed by the close of normal business hours on the tenth day. If day ten falls on a Sunday, a legal holiday, or any day the clerk's office is not open for regular business, the deadline rolls to the next day the office is open.

**Each new upset resets the clock.** The statute provides that there shall be no resales, but rather successive upset bids, each followed by a fresh ten-day period. The prior bidder is released from further obligation and the prior deposit or bond is released. The clerk notifies the trustee or mortgagee, who must mail written notice of the upset bid by first-class mail to the last prior bidder and to the current record owners.

**Finality.** When an upset bid is not filed within the time specified, the rights of the parties to the sale become fixed.

**How a buyer actually files one.** Go in person to the Clerk of Superior Court, civil division, in the county holding the file. Give the file or special proceeding number. Deliver the deposit in cash or by certified or cashier's check. Simultaneously file a written Notice of Upset Bid stating the bidder's name, address, and telephone number, the amount of the upset bid, that the sale remains open for ten days after the date the notice is filed, and signed by the bidder or the bidder's attorney or agent. The Administrative Office of the Courts form is "Notice of Upset Bid in Judicial Sale or Execution Sale." The clerk may additionally require a compliance bond, in cash or surety, in an amount the clerk deems adequate but no greater than the bid less the deposit. The upset bidder is bound by the terms of the original notice of sale.

Reference on process for the layperson: https://www.nccourts.gov/help-topics/housing/foreclosures

**The operational consequence.** Any computation of "sale date plus ten days" is wrong in both directions. The clock starts at report-of-sale filing, which lags the hammer by an unknown number of days, and it restarts on every upset. The only trustworthy deadline is a published close date or "upset period ends" value. Live proof: a Rutherford County property at 207 McArthur Street sold on 4/28/2026 and its published close date is 8/6/2026, one hundred days after the sale, because it has been upset repeatedly, from a $10,700 opening to a $28,000 current bid. A plus-ten rule would have expired that lead in early May and missed a still-open buying window three months later.

## 1.2 The two lanes nobody merges

North Carolina has two separate upset-bid universes with different publishers:

- **Mortgage and power-of-sale foreclosures.** Substitute trustee firms publish. The best is Hutchens.
- **Tax foreclosures** under 105-374 and 105-375. County tax offices and tax-foreclosure counsel publish. The best is Kania, then Zacchaeus.

**No county in the footprint publishes a combined list.** Four counties publish nothing usable at all.

## 1.3 Per-county publication, North Carolina, with URLs

| County | Source and URL | Current bid? | Upset deadline? | Live count 8/2/2026 | Access |
|---|---|---|---|---|---|
| Buncombe (tax) | https://taxforeclosures.buncombenc.gov/ | Yes, "Opening/Current Bid" | Yes, event end is the bid window close | 58 items, 5 dated 2026 | Open, but the HTML is empty. The page renders through a Trumba calendar widget. The real feed is https://www.trumba.com/calendars/tax-foreclosures-details.rss?filterview=&startdate=1%2F1%2F2020 (96 KB, 58 items). Without the `filterview=` parameter the feed returns zero items. Atom and iCal variants also exist. Trumba's robots.txt allows all. |
| Buncombe (mortgage) | Hutchens, https://sales.hutchenslawfirm.com/NCfcSalesList.aspx | Yes | Implied by the "Bid upset MM/DD" text | 9 rows | Open |
| Henderson (tax) | https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales | No | No | List with clerk file number and estimated opening bid | Open but useless for upset. The page states that current bid amounts during the upset period must be obtained from the Henderson County Clerk of Court at (828) 694-4100. Phone only. |
| Henderson (mortgage) | Hutchens | Yes | Yes | 1 row | Open |
| Gaston (tax) | https://www.gastongov.com/668/Tax-Foreclosures and https://www.gastongov.com/669/Tax-Foreclosure-Sales | No | No | Owner, parcel, address only | Open, correct upset rules published, no bid data. Sales run by the Sheriff's Office. Note that gastoncountync.gov now redirects to gastongov.com. |
| Gaston (archive, and this one matters) | https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales | **Yes** | **Yes** | Archive back to mid-2024 | Open. This is the cleanest county-hosted upset table in the state: Current Bid, Minimum of Next Upset Bid, Last Day to Upset, File Number, plus terminal status such as "Sale Closed, Property Sold" and "Settled, Property Redeemed." It is on a different page number than the current-sales page, which is why it gets missed. |
| Gaston (mortgage) | Hutchens 8 rows, Brock and Scott 5 rows | Hutchens yes | Hutchens yes | 13 | Open |
| Cleveland | https://www.clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php | Column exists, blank | Yes, close-date column | 3 table rows plus a free-text list of properties in the ten-day window | Open. This page is a stale mirror of the Kania table with the same eleven-column schema. Prefer Kania directly: Kania shows Cleveland current bids of $25,000, $13,000, and $84,000 where the county page shows blank. Cleveland also notes upset bids cannot be e-filed there; it must be in person at the Clerk. |
| Rutherford | https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php | No | No | Process text | Open, no bid data. The page directs bidders to the Clerk of Court at (828) 288-6100 and states it is the bidder's responsibility to track whether a bid has been upset. Counsel is Kania, 15 rows. |
| Burke | County publishes nothing. https://www.burkenc.org/165/Tax-Foreclosures returns 404. Surplus goes to GovDeals. | n/a | n/a | n/a | County dead. Kania 12 rows, three in an active upset window with a current bid. Hutchens 2, Brock and Scott 2. |
| Lincoln | https://www.lincolncountync.gov/2368/Foreclosures | No | No | Says "no tax foreclosures at this time" | Open, process text only, and **stale**. The county page shows nothing while Kania shows 7 live Lincoln files. Trust Kania, not the county. |
| McDowell | https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales | **Yes**, "Highest Bid Recorded" | **Yes**, "10-Day Upset Bid Period Ends" | 1 active row (sale 6/12/2026, ends 8/6/2026, $42,000, file 26-CVD-178-580) | **Open, plain HTML, the best county-published upset page in the footprint.** Self-declares that upset bid information is updated once daily. |
| Polk | https://www.polknc.gov/upcoming_auction.php | No | No | n/a | Open, no bid data. Kania 1 row, Brock and Scott 1. GovDeals for surplus. |
| Transylvania | https://www.transylvaniacounty.org/departments/tax-administration and https://www.transylvaniacounty.org/news/notice-public-foreclosure-sale | No | No | 0 | No upset data anywhere. Zero rows in Kania, Hutchens, and Brock and Scott today. The newest foreclosure news item is a December 2017 sale. Zacchaeus is the likely vendor on a weak signal only and is unverified. |
| Mitchell | https://www.mitchellcountync.gov/departments/tax/ (note mitchellcounty.org returns a Cloudflare 522) | No | No | 0 | Nothing published. The only footprint source carrying any Mitchell row is Brock and Scott, one sale notice, no bid. Weakest county in the footprint. |

## 1.4 Statewide and multi-county feeds, classified

| Source | URL | Fields carried | Footprint volume | Access |
|---|---|---|---|---|
| **Kania Law Firm** (tax) | Listings page: https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/ JSON: `https://kanialawfirm.com/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id=216745&target_action=get-all-data&default_sorting=old_first&skip_rows=0&limit_rows=0&ninja_table_public_nonce=<nonce scraped from the page>` | county, address, parcel, saledatetime, openingbid, **currentbid**, **closedate**, propertytype, **courtfile**, ourfile, salestatus | 187 rows statewide across 25 counties. **42 in footprint**: Rutherford 15, Burke 12, Cleveland 7, Lincoln 7, Polk 1. **11 currently in an open upset window with a live current bid.** 74 of 187 rows statewide carry a close date. | **Fully open JSON, no auth.** robots.txt explicitly allows /wp-admin/admin-ajax.php. Gotcha: the action parameter is `wp_ajax_ninja_tables_public_action`; the short form `ninja_tables_public_action` returns HTTP 400 with body `0`. |
| **Hutchens Law Firm** (mortgage, substitute trustee) | https://sales.hutchenslawfirm.com/ then https://sales.hutchenslawfirm.com/NCfcSalesList.aspx | Case No., SP#, County, Sale Date, Property Address, Property CSZ, Deed of Trust Book/Page, **Bid Amount** | 231 rows statewide, **27 in footprint** across 8 of 11 counties: Buncombe 9, Gaston 8, Lincoln 4, Burke 2, Henderson 1, Rutherford 1, McDowell 1, Cleveland 1. 57 statewide rows carry a real dollar bid. | **Fully open**, robots.txt returns 404 so no restriction. Telerik grid, rows are `GridRow_WebBlue` and `GridAltRow_WebBlue`, eight cells each, whole list on one page, no paging. The upset state is encoded as literal text in the Bid Amount cell: `Bid upset 07/23/2026, increasing bid to $116,400.00`. That string is the single richest upset signal available for mortgage foreclosures anywhere. |
| **Brock and Scott** | https://www.brockandscott.com/foreclosure-sales/ with county filter, JSON at `?sfid=1202&sf_action=get_data&sf_data=all` | County, Sale Date, State, Court SP#, Case#, Address, Opening Bid, Book Page | 22 in footprint: Gaston 5, Cleveland 4, Rutherford 4, McDowell 3, Burke 2, Buncombe 1, Lincoln 1, Mitchell 1, Polk 1 | Open, robots.txt sets a one-second crawl delay and does not disallow the path. **No upset data at all.** Zero occurrences of the word "upset," opening bid only, many zeros. This is a sale-notice feed, not an upset feed. |
| **Zacchaeus Legal Services** | https://www.zls-nc.com/listings and /property-for-sale | Documented to carry upset status and end dates | Unknown | **Blocked, architecturally.** Blazor Server single-page app. Every route returns the same 7.3 KB shell that renders an error to a non-browser client. No `blazor.boot.json`, so it is Server not WebAssembly, meaning data flows over a SignalR WebSocket circuit and no JSON endpoint exists. robots.txt is permissive. This is a rendering wall, not a policy wall: reachable with a real browser, not with a plain HTTP client. |
| **NC eCourts Portal, Foreclosure Sales dashboard** | https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29 | n/a | n/a | **Blocked by CAPTCHA.** A live probe returns HTTP 405 from an AWS load balancer with the header `x-amzn-waf-action: captcha` and a human-verification body. Same wall as the known Smart Search block. **Do not build. Do not add a human-in-the-loop solve step.** |
| Shapiro, Bell Carrington, Aldridge Pite | All reachable, HTTP 200 | n/a | n/a | Not worth a scraper until Kania and Hutchens are live. They add little footprint coverage. |

## 1.5 South Carolina: yes, there is an equivalent, and it is more generous but far less visible

**Authority:** S.C. Code 15-39-720 through 15-39-760, Title 15 Chapter 39.
https://www.scstatehouse.gov/code/t15c039.php

- **Window: 30 days, not 10.** In all judicial sales of real estate for foreclosure of mortgages and sales in execution, the bidding shall not be closed on the day of sale but shall remain open until the thirtieth day after the sale, exclusive of the day of sale.
- **Deposit: 15-39-740.** Five percent of the bid or some lesser percentage. No deposit may be required before the bidding concludes.
- **Who may bid:** any person other than the highest bidder at the sale or a representative thereof. **The foreclosing mortgagee is locked out.** It must enter its bid at the sale and is precluded from entering any other bid at any other time.
- **No rolling reset.** Unlike NC, SC does not restart a window on each raise. Bids accumulate during the single 30-day window, then the bidding is reopened by the officer making the sale on the thirtieth day at 11:00 a.m. and continues until the property is knocked down. **It ends in a live, in-person re-auction on day 30.** If day 30 is a Sunday, it closes the following Monday.
- **Prior bidder released:** 15-39-750, deposit returned with written notice within two days.
- **The carve-out that changes everything: 15-39-760.** Sections 15-39-720 through 15-39-750 do not apply to any foreclosure suit if the complaint states that no personal or deficiency judgment is demanded and that any right to such judgment is expressly waived. In practice most SC lenders waive deficiency, so **most SC foreclosure sales close the day of sale with no upset period at all.** Only deficiency sales carry the 30-day window. SC upset bids are a minority of sales, not the default.
- 15-39-730: non-foreclosure judicial sales close on the sale date unless a party objects.

Process is judicial, run by the county Master-in-Equity or a referee, typically monthly. Greenville sits the first Monday at 11:00 a.m. Spartanburg sits in Courtroom 4-A.

**Is there a comparable feed? No.**

| SC source | URL | Verdict |
|---|---|---|
| Greenville Master-in-Equity sale advertisements | https://mie.greenvillejournal.com/ and /search-results/ | Open and searchable, sale-date dropdown back to 2023, plaintiff, address, defendant search. But these are **advertisements**: plaintiff, address, judgment amount, sale date. No current bid, no upset tracker. Closest SC analogue to Hutchens, and it covers one county. |
| Spartanburg Master-in-Equity | https://www.spartanburgcounty.gov/151/Master-In-Equity and https://www.spartanburgcounty.gov/313/Foreclosure-Sale, cancellations at /315/ | Open. Deficiency sale results published as a batch PDF at https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale. Note /314/Deficiency-Sale-Results is a 404; the live path is /316/. A batch PDF, not a live bid feed. |
| Spartan Weekly News legal notices | http://www.spartanweeklyonline.com/id11.html | Open statutory notice repository. Sale notices only. |
| Anderson, Pickens, Oconee Master-in-Equity | https://www.andersoncountysc.org/master-in-equity/ , https://www.pickenscountysc.gov/master-equity , https://oconeesc.com/master-in-equity (returned HTTP 500 at probe) | Office pages only. No roster feed. |
| SC Public Index | https://publicindex.sccourts.org | Terms-of-service wall. Unchanged. |

**Blunt SC answer.** No free public source at any Upstate county publishes a running current bid plus an upset-period expiry the way Kania and McDowell do in NC. During the 30-day window the bidding state lives in the Master-in-Equity's counter records and is resolved by a live in-person re-auction. **This cannot be obtained as a feed by anyone at any price.** The buildable SC ceiling is sale notices, from which you can infer a 30-day window may be open if the notice did not waive deficiency, but you cannot know the current bid.

## 1.6 Why our upset-bid lane returns zero

The health log records the source as returning zero rows with status "empty, verified," and the history shows a single count of zero. It has never returned a row. There are six independent defects.

**Defect 1, Henderson, dead URL.** The configured source is `https://www.hendersoncountync.gov/clerk`, which returns 404 (282 bytes). That path never existed. The tax foreclosure page is `/tax/page/tax-foreclosure-sales`. The fetch raises, the exception is swallowed by a broad catch, and the county returns an empty list.

**Defect 2, Gaston, dead URL plus host migration.** The configured source is `https://www.gastoncountync.gov/government/county_departments/clerk_of_court`, which 307-redirects to gastongov.com and then 404s. The county moved to CivicPlus numeric page IDs. Same swallow, same empty list.

**Defect 3, Cleveland, a real code bug and the only one worth fixing in place.** `https://www.clevelandcounty.com/` 301-redirects to `/main/`. The HTTP client follows redirects, so the parse operates on the correct `/main/` homepage. The homepage link is relative: `href="departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php"`. The link-resolution step is handed the **pre-redirect base URL from the configuration tuple**, not the response's final URL. So the join produces `https://www.clevelandcounty.com/departments/find_tax_foreclosures.../index.php`, which is a verified 404, instead of `https://www.clevelandcounty.com/main/departments/find_tax_foreclosures.../index.php`, which is a verified 200 with a three-row table. The `/main/` segment is silently dropped. The crawl logic is fine, the link is found and ranks fourth of five inside the eight-link cap. Only the URL construction is wrong. Confirmed the parser would otherwise work: run against the real Cleveland page it extracts case numbers 25CV003091, 25CV003791, 25CV003450 and addresses 124 Afton Dr, 126 Brunet Dr, 124 Galilee Church Rd. Fix is one line: join against the response's final URL.

**Defect 4, Buncombe, wrong extraction strategy.** `https://taxforeclosures.buncombenc.gov/` returns 200 and 19,258 bytes containing zero table elements, zero rows, and zero listing text. Listings are injected client-side by Trumba widgets loading `//www.trumba.com/scripts/spuds.js`. Both the table branch and the text branch of the parser find nothing because there is nothing in the HTML. The HTML parser does not execute JavaScript.

**Defect 5, the meta-cause that hid all four.** The shared HTTP client's set of blocked status codes is 401, 403, 406, 409, 429. **404 is not in it.** Every one of the four failures produced a 404 or an empty parse, never a block code, so the runner classified a fully dead scraper as "empty, verified." Any scraper whose entire source list 404s will report as healthy forever.

**Defect 6, the board cannot show an upset-bid lead even if scraping worked.** The listing-type enumeration has no upset-bid member. Its members are foreclosure sale, tax sale, tax lien, lis pendens, bankruptcy, REO, auction, sheriff sale, HOA sale, distressed, divorce notice, probate notice, estate lead, elderly or disabled, and unknown. The scraper hard-codes sheriff sale. So "zero leads of type upset_bid" is structurally guaranteed independent of the fetch bugs. The scraper's own category string is a scraper-level label, not a listing type. Either add an upset-bid member, or accept that upset state lives in the upset-bid deadline field plus the raw payload (which the upset enrichment, the distress score at 22 points, the lead-signal enrichment, and the board writer already consume) and filter on that instead.

**Defect 7, a correctness bug that survives all of the above.** The deadline is synthesized as sale date plus ten days, which contradicts the statute in both directions. See the Rutherford hundred-day example in 1.1.

## 1.7 What to build, upset bids

**There is no single feed covering both lanes. Anyone claiming otherwise is wrong.**

**Build 1, Kania JSON.** The only free source in existence carrying current bid, close date, court file, and parcel per property in structured JSON. 187 rows, 42 in footprint, 11 with a live current bid and an open close date right now. Zero auth, no observed rate limit, robots.txt explicitly permits the endpoint. Covers five of eleven counties and makes the Cleveland county-page scrape redundant. Implementation notes: use the long action parameter; scrape the nonce fresh from the listings page each run rather than hard-coding it; the address and parcel fields can contain HTML line breaks joining multiple parcels; the sale date field may be the literal HTML `<span class='red'>Sale date not yet set</span>`; the sale status field is empty on all 187 rows today, so derive "in upset window" from a non-empty current bid and a close date at or after today.

**Build 2, Hutchens sales list.** Same sprint. The only mortgage-lane source with upset data, covering eight of eleven counties in 27 rows, one flat page, no paging. Parse the two row classes, eight cells, split the county cell on the comma. Distinguish three Bid Amount states: "Bid not available yet" (pre-sale, 174 of 231 rows), a bare dollar figure (sold, window presumed open), and the "Bid upset MM/DD/YYYY, increasing bid to $N" form, which tells you the window restarted on that date. Only in that third case should you compute a deadline, and only from the stated date.

**Build 3, McDowell county page.** One cheap plain-HTML scrape. The only county in the footprint publishing its own upset table with a recorded highest bid and a stated period end, refreshed daily.

**Build 4, Gaston previous-sales archive** at /671/. Current bid, minimum next upset, last day to upset, file number, terminal status. Cleanest county-hosted upset table in the state and currently unread.

**Build 5, Buncombe Trumba feed.** Cheap. Remember the `filterview=` and `startdate=` parameters or the feed returns empty. The JSON variant `https://www.trumba.com/calendars/tax-foreclosures-all.json?startdate=1%2F1%2F2015&days=5000` returns 58 events spanning January 2022 to April 2026, with custom fields for Opening/Current Bid, Redeemed (33 no, 25 yes), Case Number, a PIN lookup carrying the 15-digit PIN, Property Type, and Fire District. It has no upset deadline field.

**Do not build:** the eCourts dashboard (CAPTCHA), Zacchaeus (no HTTP surface), Brock and Scott for upset purposes (opening bid only, zero upset data; keep it in mind later as a sale-notice source).

**Retire the current county-clerk-level upset scraper entirely.** All four of its sources are dead, its deadline math contradicts the statute, and its output type can never surface. The correct sources are firm-level and statewide, not county-clerk-level. Patching four URLs is the wrong move.

**Three changes needed regardless of which feed lands:**
1. Add an upset-bid listing type, or document explicitly that upset leads carry a tax-sale or foreclosure-sale type plus a populated upset deadline.
2. Add 404 and 410 to the blocked-status set, or add a distinct dead-URL health status, so an all-404 scraper stops reporting as verified-empty.
3. Never synthesize a deadline. Leave it null unless the source publishes one.

---

# SECTION 2: DEED RECORDS

## 2.1 The straight answer

A deed search tells you **who owns it, how they got it, and what secured debt was recorded against it.** It tells you essentially nothing about **how much is owed today, whether the borrower is behind, who is living in it, what condition it is in, or what non-recorded claims are attached.**

And in North Carolina specifically, several of the liens investors care most about are **not at the Register of Deeds at all.** Judgments, mechanics liens, HOA liens, federal tax liens, and lis pendens are docketed with the Clerk of Superior Court. **A North Carolina Register of Deeds sweep with no court-lane companion is a materially incomplete lien picture.**

## 2.2 What IS in a Register of Deeds index

| Instrument | What it proves | Investor-useful fact |
|---|---|---|
| Deed (warranty, special warranty, quitclaim) | Chain of title | Current record owner, acquisition date, grantor and grantee, and in NC the sale price via the excise stamp. Long tenure plus old low basis equals equity. Quitclaim between relatives suggests a probate or divorce event. |
| Deed of trust (NC) or mortgage (SC) | A secured loan existed | Original principal, origination date, lender, trustee. The base for an amortization estimate. Multiple open instruments mean stacked liens. A private or hard-money lender named is a distress signal. |
| Assignment | The loan was sold | Who to actually call. A transfer to a special servicer or debt fund is a strong pre-default signal. |
| Satisfaction or cancellation | The loan was paid off | The single most valuable field. An instrument with no satisfaction is presumptively still open. **Free-and-clear detection is done by the absence of a satisfaction, not the presence of anything.** |
| Substitution of trustee (NC, G.S. 45-10) | The lender swapped in a foreclosure trustee | A classic 30-to-90-day pre-foreclosure tripwire, often the earliest recorded distress artifact in NC. |
| Notice of hearing, notice of sale | Foreclosure is running | Sale date, trustee, file number. See the caveat in 2.3: the statutory home is the Clerk; recording at the Register of Deeds is county practice. |
| Trustee's, commissioner's, or foreclosure deed | Sale completed | Hammer price via the NC excise stamp, new owner, and whether the lender credit-bid it back into REO. |
| Tax deed | Tax sale completed | Post-sale ownership, tax-sale investor identity. |
| Lis pendens | Litigation affecting title | In SC this is the judicial-foreclosure starting gun, but it lives at the Clerk of Court, not the Register of Deeds. |
| Claim of lien, mechanics lien | Unpaid contractor | **SC only** at the Register of Deeds (29-5-90 permits Register of Deeds or Clerk of Court). **NC files with the Clerk of Superior Court** under G.S. 44A-12. |
| HOA or condo assessment lien | Delinquent dues | **SC only** at the Register of Deeds. **NC files with the Clerk of Superior Court** under G.S. 47F-3-116. The amount stated is as of filing, not current. |
| UCC fixture filing | Financed fixtures (solar, HVAC, manufactured home) | NC G.S. 25-9-501 sends fixture filings to the Register of Deeds. A solar UCC can blow up a deal at closing. |
| Plat, subdivision map | Legal boundaries | Lot dimensions, easements, setbacks, whether a parcel is legally subdividable. |
| Easement | Third-party rights | Access, utility, right of way. Landlocked-parcel detection. |
| Restrictive covenants, declaration | Use limits | Whether an HOA exists at all, rental restrictions, minimum square footage, mobile home bans. |
| Power of attorney | Someone signs for the owner | Strong proxy for incapacity, an elderly owner, or an out-of-state owner delegating. High-motivation signal. |
| Death certificate (recorded in some NC counties) | Owner died | Inherited-property lead. |
| Deed of distribution (SC) | An estate transferred realty | SC probate transfers surface here, with heir names and addresses. |
| Affidavit of heirship or survivorship | Who inherited | Occasionally recorded, frequently absent. |
| Separation agreement (commonly recorded in NC) | A marriage is dissolving | Pre-divorce distress before any court decree exists. |
| Federal tax lien | IRS claim | **SC: Register of Deeds** under the SC Uniform Federal Tax Lien Registration Act, 12-57-30. **NC: Clerk of Superior Court** for real property under G.S. 44-68.12. |

## 2.3 What is NOT in the deed record, and where it actually lives

| Invisible in the deed record | Why | Where it actually lives | Obtainable free? |
|---|---|---|---|
| **Current loan balance** | Only the original principal is recorded and nothing updates it | Servicer and borrower only | **No. Not by anyone at any price** without borrower authorization. Estimate only: amortize the original principal from the origination date at an assumed rate. |
| **Delinquency, forbearance, loss mitigation, modification status** | Nothing requires recording; modifications are sometimes recorded, usually not | Servicer, and credit bureaus under FCRA restriction | **No.** Proxies only: substitution of trustee, notice of hearing, or an SC lis pendens. That is the earliest you can see it, and by then it is late. |
| **Escrow advances, default interest, attorney fees, force-placed insurance** | Accrues entirely off-record | Servicer payoff statement | **No.** This systematically causes payoff to exceed any amortization estimate. Budget a cushion. |
| **Property tax delinquency and amount** | The NC tax lien attaches automatically on January 1 under G.S. 105-355 with **no recording requirement**. SC operates the same first-lien-by-operation-of-law structure. | County tax collector, delinquent tax office | **Yes, but separately.** See Section 3. It will never come out of a deed sweep. |
| **NC judgment liens** | Docketed, not recorded. G.S. 1-234, ten-year lien from entry. | Clerk of Superior Court judgment docket | Yes, via the NC eCourts Judgment Search JSON. Not in the Register of Deeds. |
| **NC mechanics liens** | G.S. 44A-12 files them with the clerk of superior court and notes them on the judgment docket | Clerk of Superior Court | Yes, same court lane. **Never** in the NC Register of Deeds. |
| **NC HOA and condo liens** | G.S. 47F-3-116 files the claim of lien in the office of the clerk of superior court | Clerk of Superior Court | Yes, same court lane. **Never** in the NC Register of Deeds. A real gap if you were relying on deed sweeps for NC HOA distress. |
| **NC federal tax liens on real property** | G.S. 44-68.12 | Clerk of Superior Court | Yes, court lane. SC is the opposite. |
| **NC lis pendens** | G.S. 1-116 and 1-117 have the clerk cross-index a Record of Lis Pendens | Clerk of Superior Court | Yes. Some NC deed vendors still carry a lis-pendens instrument code, so you may see both. Do not assume deed coverage is complete. |
| **NC notice of foreclosure sale** | G.S. 45-21.17 requires posting in the area designated by the clerk plus newspaper publication. The statute does not require recording. | Clerk of Superior Court special proceeding file, newspaper legals | Yes. Many NC counties do also record a notice of sale, which is why deed adapters find foreclosure and notice-of-sale codes, but that is county practice, not statute. **Newspaper legals remain the more reliable NC pre-sale feed.** |
| **Unrecorded utility, water and sewer, demolition, nuisance abatement, and code enforcement charges** | Municipal, often no recorded instrument until very late | City or town utility billing and code enforcement | Partially. Asheville's code enforcement feed is the model; most towns have no feed. |
| **Occupancy and tenancy** | Nothing to record | Nowhere public | **No.** Physical drive-by, licensed USPS vacancy data, or utility shutoff data (which is legally closed, see Section 5). |
| **Leases** | NC G.S. 47-18 requires recording only for leases over three years. Every ordinary twelve-month residential lease is invisible. SC 30-7-10 requires recording only over twelve months, and SC law provides that possession does not give constructive notice of an unrecorded instrument. | Landlord and tenant only | **No.** A tenant in place is a post-close surprise. |
| **Condition, deferred maintenance, interior, roof, systems** | Not a recordable fact | Nowhere | **No.** Street View, listing photos, permits, and inspection. Exterior proxy only. |
| **Probate transfers with no recorded deed** | **NC G.S. 28A-15-2(b): title vests in the heirs at the moment of death.** No deed is required and none is recorded. The deed index still shows the decedent as owner. | Clerk of Superior Court estates division in NC, Probate Court in SC | Yes, via the estates lane. **This is the single biggest blind spot of a pure deed search.** A deed-only view of an heir-owned property looks like a normal owner who has not sold in thirty years. |
| **Divorce equitable-distribution interests before judgment** | An unadjudicated claim is not a recorded interest | District Court civil file in NC, Family Court in SC | Partially. The NC judgment search surfaces divorce; pre-judgment claims are effectively invisible. NC separation agreements are sometimes recorded and are the only deed-visible artifact. |
| **Contracts for deed, land contracts, unrecorded options, rights of first refusal** | NC G.S. 47-18 means an unrecorded one does not bind a purchaser for value, but it very much binds the seller and complicates the deal | Parties only | **No.** The silver lining is that under 47-18 an unrecorded option generally cannot defeat a bona fide purchaser, so the exposure is deal friction, not title loss. |
| **True sale price on most SC deeds** | See 2.4 | Assessor property card (Pickens, Oconee) | Partially. |
| **Beneficial ownership behind an LLC** | Deeds name the entity | NC Secretary of State registered agent and officers (free); SC Secretary of State is CAPTCHA-walled | NC yes, SC no. |

## 2.4 Deed stamps: backing out sale price

### North Carolina, works with caveats

**G.S. 105-228.30:** excise tax of $1.00 per $500 or fractional part thereof of the consideration or value of the interest conveyed, paid to the Register of Deeds before recording.
https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.30.html

```
sale_price is approximately excise_stamp x 500
true price lies in the interval ((stamp - 1) x 500, stamp x 500]
```

**Failure modes, in order of how often they bite:**

1. **It always rounds up.** "Fractional part thereof" makes stamp times 500 an upper bound, overstating by up to $499.99. Noise on a $400,000 sale, material on a $15,000 lot.
2. **Zero stamp on exempt transfers.** G.S. 105-228.29 exempts transfers by operation of law, by lease for a term of years, by will, by intestacy, by gift, where no consideration is due or paid, by merger or conversion or consolidation, and by an instrument securing indebtedness. Every deed of trust therefore has no stamp, and every inherited, gifted, or entity roll-up deed reads as $0. **A zero stamp usually means an exempt transfer, not a zero-dollar sale.** Treat it as null, never as a comp.
   https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.29.html
3. **Governmental grantors are out of scope entirely** under G.S. 105-228.28, so tax-foreclosure and municipal deeds carry no stamp.
   https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-228.28.html
4. **Multi-parcel deeds.** One stamp covers every parcel in the instrument. Allocating the whole stamp to your subject parcel inflates its price, sometimes tenfold on a portfolio deed.
5. **Multi-county parcels.** 105-228.30 sends the entire tax to the county holding the greater value, so a stamp recorded in county A can cover land in county B. Cross-county comps are unreliable.
6. **Encumbrance treatment is ambiguous.** The statutory base is "the consideration or value of the interest conveyed." Whether existing debt taken subject-to is included varies by closing practice and county. That is a variance source, not a parser bug.
7. **Trustee's deeds on a lender credit bid.** The stamp may reflect the credit bid rather than market value, or be omitted. Credit-bid REO transfers are the noisiest single class.
8. **Index-level omission.** Many deed search grids do not expose the excise field at all. You must open the detail page or the document image. That is the real throughput limiter.

### South Carolina, and the correction that matters

SC does have a price-bearing fee: **12-24-10**, a deed recording fee of $1.85 per $500 of realty value ($1.30 state plus $0.55 county). Mathematically, value equals fee divided by 1.85 times 500. The mechanism exists.

**The problem is 12-24-70 combined with 12-24-40.**
https://www.scstatehouse.gov/code/t12c024.php

- **12-24-70** requires an affidavit stating value, **but for deeds exempt from the chapter the value is not required to be stated**; the affidavit need only state the reason for the exemption. The clerk or Register of Deeds may waive the affidavit entirely. No affidavit at all is required for a 62-3-907 deed of distribution.
- **12-24-40** exempts fifteen categories, and the ones that matter to a distressed-property operator are exactly the ones you want priced:
  - **(13) deeds in lieu of foreclosure and deeds executed pursuant to foreclosure proceedings**
  - (12) corrective and quitclaim deeds confirming existing title
  - (8) and (9) transfers to and from corporations, partnerships, and family trusts
  - (5) partition deeds
  - (4) IRC 1041 transfers, which is the divorce transfer category
  - (2) transfers to government
  - (10) and (11) mergers and consolidations

Net: **in South Carolina the foreclosure deed, the divorce deed, the family-trust deed, and the partition deed all legally recite no value.** That is a statutory wall, not a scraping problem. Combined with the separate finding that the Acclaim search grid omits consideration from its results JSON, SC recorded sale price is not recoverable at scale from the deed record.

Reference: SC Department of Revenue Deed Recording Fee Manual,
https://dor.sc.gov/sites/dor/files/Documents/Policy%20Manuals/Deed%20Recording%20Fee%20Manual%202024.pdf

**The free SC workaround is the assessor, not the deed record:** the per-parcel qPublic property card for Pickens and Oconee carries square footage plus sales history. That is the SC price lane.

## 2.5 Per-county Register of Deeds search URLs and access status

All verified live 2026-08-02 by direct request. **No CAPTCHA was encountered on any of the 18.** Nothing below requires defeating a bot wall.

### South Carolina, 7 counties

| County | Search URL | Vendor | Status |
|---|---|---|---|
| Spartanburg | https://search.spartanburgdeeds.com/index.php | Logan "The Lookup," newer AJAX build | **Open, no login (HTTP 200).** Caveat: as of the 2026-06-22 verification the deployment returned zero rows for every search type, a county-side index condition. Mechanics are reverse-engineered and ready; data is not flowing. |
| Anderson | Menu: https://acpass.andersoncountysc.org/deed.cgi then https://acpass.andersoncountysc.org/deeda.cgi?SearchType=L | County-built CGI | **Open, no login** (18.9 KB and 39.7 KB responses). The ACPASS **root** presents a login form; the deed module is publicly reachable without auth. Do not classify Anderson as login-walled from the homepage. |
| Pickens | https://www.pickensscrod.us/AcclaimWeb | Harris Acclaim Web | **Open, no login.** |
| Oconee | https://oconee.sc.publicsearch.us/ | Tyler PublicSearch | **Login required, free account.** The county states users must sign up for a free account before accessing records. Deed index from 1957, mortgage index from 1992, images only from 1/1/2002. Copies $5.00 for up to four pages. County page: https://oconeesc.com/departments/register-of-deeds |
| Cherokee | https://www.sclandrecords.com/sclr/ , county code sc021 | SC Land Records multi-county portal | **Open for search;** an account is needed only for fraud alerts. Index from 1/3/1995, images from 9/25/2002, copies free. Caveat: it is a session-based JSP app, so a cold POST returns zero bytes and the session must be bootstrapped first. County page: https://cherokeecountysc.gov/register-of-deeds/ |
| Union | https://recordroom.cottsystems.com/unionsc/guest/Search/records | Cott RecordRoom | **Open via the /guest/ path (HTTP 200).** The bare /unionsc path redirects to a login route, which is what makes this look walled if you probe the wrong URL. Index metadata free, document images pay-per-view. |
| Laurens | https://search.laurensdeeds.com/NameSearch.php | Logan, older name-search build | **Open, no login.** Hard limitation: standard search type only, meaning **a name is required**. There is no name-less instrument-type date sweep. Distress labels are full text ("FORECLOSURE DEED," "DEED OF DISTRIBUTION," "TAX DEED," "HOMEOWNERS ASSOCIATION LIEN," "ORDER BY JUDGE"), not short codes. Cannot be swept, only name-queried. |

### North Carolina, 11 counties

| County | Search URL | Vendor | Status |
|---|---|---|---|
| Buncombe | https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/SrchName.aspx | Aumentum / Cott eSearch v4 | **Open as Guest User.** Gotcha: a cookieless request redirect-loops to the login page. With a cookie jar it lands on the full search menu (Quick Name, Advanced Name, Property, Book-Page, File Number, Date Range) showing "Guest User." **Do not classify as login-walled based on the redirect.** County landing: https://www.buncombenc.gov/457/Register-of-Deeds |
| Henderson | https://us4.courthousecomputersystems.com/hendersonnc/ | Courthouse Computer Systems | Open, no login. |
| Gaston | https://gastonnc.courthousecomputersystems.com/ | Courthouse Computer Systems | Open, no login (132 KB app). **Changed:** Gaston switched vendors on 2026-05-28. County page: https://www.gastongov.com/730/Register-of-Deeds |
| Cleveland | https://us5.courthousecomputersystems.com/clevelandnc/ | Courthouse Computer Systems | Open, no login. County landing https://www.clevelandcounty.com/rod/ also returns 200. |
| Rutherford | https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4/SrchName.aspx | Cott / Aumentum v4 | **Open as guest.** Note that /onlinedeeds on the county site returns a soft 404 that still serves HTTP 200; the live link is at https://www.rutherfordcountync.gov/departments/register_of_deeds/index.php |
| Burke | https://us5.courthousecomputersystems.com/burkenc/ | Courthouse Computer Systems | Open, no login. |
| Lincoln | https://us4.courthousecomputersystems.com/lincolnnc/ | Courthouse Computer Systems | Open, no login. |
| Polk | https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/SrchName.aspx | Cott / Aumentum v4 | **Open as guest**, confirmed "Guest User" in the page. Same cookieless redirect artifact as Buncombe. County landing: https://www.polknc.gov/register_of_deeds.php |
| McDowell | https://search.mcdowelldeeds.com/ | Logan "The Lookup" | **Down.** HTTP 500, empty body. |
| Transylvania | https://search.transylvaniadeeds.com/ | Logan "The Lookup" | **Down.** HTTP 500, empty body. |
| Mitchell | https://search.mitchelldeeds.com/ | Logan "The Lookup" | **Down.** HTTP 500, empty body. |

## 2.6 Live status deltas worth acting on

1. **The Gaston deed adapter points at a dead host.** The configured target `https://deeds.gastongov.com/external/LandRecords/protected/v4` now times out entirely with no response at all. Gaston migrated to Courthouse Computer Systems on 2026-05-28. The correct target is `https://gastonnc.courthousecomputersystems.com/`, which means Gaston must move from the Aumentum adapter to the Courthouse adapter. Note that the Gaston install is on its own hostname, not the shared us4 or us5 clusters: `https://us4.courthousecomputersystems.com/gastonnc/` returns 404, so the shared-cluster URL pattern does not apply.

2. **All three Logan-hosted NC counties are simultaneously returning HTTP 500** with zero content length while the web server still issues a session cookie. That is a server-side fault on one shared vendor deployment, not a block, not a rate limit, and not a bug on our side. Three counties failing identically points at one vendor incident. It will either self-heal or needs a call to the vendor. Do not spend engineering time on it.

3. **Four counties are misclassifiable as walled and are not.** Buncombe and Polk both redirect to a login page on a cookieless probe and resolve to a full guest session with cookies. Union SC looks walled at /unionsc and is open at /unionsc/guest/Search/records. Anderson SC looks walled at the ACPASS root and is open at deed.cgi. Any uptime check that does not carry cookies and does not use the exact guest path will produce four false negatives.

4. **Only one of the eighteen is genuinely login-gated: Oconee SC**, and that is a free registration wall, not a bot wall. Registering is a user decision, not something to automate around.

---

# SECTION 3: TAX

## 3.1 South Carolina, seven counties

### The payment-portal lane, and the trap that killed the last attempt

Five of the seven counties run the same hosted tax payment portal at `/Taxes/TaxesDefaultType4.aspx`. **The host names follow no rule.** Four of five do not match the obvious pattern.

| County | Verified host |
|---|---|
| Spartanburg | https://spartanburgcountytax.qpaybill.com/Taxes/TaxesDefaultType4.aspx |
| Oconee | https://oconeesctax.qpaybill.com/Taxes/TaxesDefaultType4.aspx |
| Laurens | https://laurenstreasurer.qpaybill.com/Taxes/TaxesDefaultType4.aspx |
| Union | https://uniontreasurer.qpaybill.com/Taxes/TaxesDefaultType4.aspx |
| Cherokee | https://cherokeecountysctax.qpaybill.com/Taxes/TaxesDefaultType4.aspx |
| Anderson | None. ACPASS, login-gated. |
| Pickens | None. GIS plus per-parcel qPublic card. |

**The exact form (identical across all five).** POST to the page with the standard ASP.NET viewstate, viewstate generator, and event validation carried from a prior GET, plus:

- search type: real estate, vehicle, personal, watercraft, or all
- paid status: unpaid, paid, or all payments
- year list: `All`, or 2026 down to 2016
- criteria list: Receipt, Map, Name, DOR, or Address
- criteria box: the query
- the search button

The viewstate generator is per-county. Pagination drops the search button, sets the event target to the results grid and the event argument to `Page$N`, and must carry the **results page's** viewstate, not the landing page's. Non-adjacent page jumps work. Twenty-six rows per page. Result columns in order: Receipt No., Name and Property Address, Year, Description, Identification No. (the tax map number), Type, Status, Payment Date, Amount.

**The trap.** An unpaid-plus-year search cannot be used as a naive browse, and it lies about it.

- Blank criteria is rejected outright.
- Map number is exact match, not prefix. A "1" returns nothing.
- Address is exact match. "MAIN" returns nothing.
- **Name is a left-anchored prefix, and it is the only browse vector.**

But it truncates silently, with no warning banner:

- Name `S`, year All, returns 88 rows, ends at SANCHEZ, and contains zero names beginning SM. Name `SM` alone returns 31 rows.
- Name `B` returns 49 rows, ending at BAILEY FRANKIE. Name `BAILEY` alone returns 31 rows running BAILEY AMANDA to BAILEY STEVE R.
- Name `JOHNSON` returns 75 rows, ending at JOHNSON LLOYD. No JOHNSON M through Z.

Observed ceiling is four pager pages, roughly 104 rows, with actual returns of 31 to 97 rows and 11 to 34 distinct parcels. **The cut point is not a clean constant, so truncation cannot be detected by row count.** A 26-letter A-to-Z sweep would silently miss the large majority of every county. Enumeration requires recursive prefix deepening: deepen any prefix whose last returned name does not sort past the first name of the next sibling prefix. Budget roughly 700 to 3,000 queries per county, rate-limited, because these are small county servers.

### The real prize: multi-year history is free and already on the server

The year dropdown's floor of 2016 is a display artifact. **Setting the year to `All` returns rows far below it.**

- **Spartanburg: 1999 to 2026 verified.** A `B` prefix returned rows spanning 1999 to 2025; `JOHNSON` returned 2000 to 2026.
- **Oconee: 2016 to 2025 only.** Older years purged.
- Cherokee, Union, and Laurens return their full portal retention through the same mechanism.

Each row is one parcel-year receipt, so a single query returns the entire arrears ladder for a parcel. **No snapshotting is needed for these counties.** The server holds the history.

Statuses observed: `Unpaid`, and in Spartanburg also **`Sold at Tax Sale`**. See 3.3.

### GIS delinquency layers

**Oconee**, ArcGIS organization `services1.arcgis.com/UOvRn2Rvzysthh3i`, 56 services enumerated:

| Service | Rows | Notes |
|---|---|---|
| DT2023 | 440 | Total tax field is typed as a string |
| DT2024 | 476 | Has a redeemed column, **0 of 476 populated, a dead column** |
| DT2025 | 645 | Owner field renamed, generic Field6 and Field7 appear, no redeemed column |
| DelqTaxSale_2015 | one-off | |
| Assignment_FLC | 189 | TMS, Owner, Description, Acres, FLC bid, redeem/assign status, date, comment |
| Delinquent_Tax_Properties | 2 | Field-collection scratch layer, useless |

**DT2019 through DT2022 and DT2026 do not exist**, confirmed absent from the full service directory. **The schema drifts every year, so write the parser per year, not generically.**

One warning: the two-row scratch layer is misconfigured to allow anonymous update and delete. Query only, never write. Worth reporting to the county.

**Pickens**, ArcGIS organization `services1.arcgis.com/59960rq18IxUcAVI`, 154 services. **The best free multi-year archive of the seven:**

| Service | Rows | Notes |
|---|---|---|
| delinquent_2020 | 436 | |
| del_2021 | | |
| dqnt_2022 | | |
| dqnt_2023 | 362 | |
| dqnt_2024 | 954 | Richest schema |
| DelParces_October2025NewsAd | 412 | The 2025 newspaper advertisement, **with amount due** |
| DelqParcels_Ad_paperlisting2, Posting3 | | Advertisement variants |
| FLC_2022 | | PIN, owner, sale price, year, mixing 2017 to 2022 |

The 2024 layer carries PIN, two name fields, **owner mailing address with city, state, and ZIP**, situs address, acres, buildings, status, tax year, sale date, sale price, and maximum amount due. Live sample: BARNES RICHARD W, 157 Robert P Jeanes Rd, $278.50. Caveat: status is uniformly "A," sale date is null, and sale price is zero, so the sale and redemption fields are **not populated**. The 2025 advertisement layer does carry real amounts, for example MOSCATI, PAUL and SARA MOSCATI at $5,137.53.

Public entry point: https://www.co.pickens.sc.us/departments/delinquent_tax/index.php

**Spartanburg, Anderson, Cherokee, Union, and Laurens have no delinquency GIS layer.** A search across ArcGIS Online for all five returned nothing in South Carolina, only a decoy Union County **North Carolina** map. That is a real absence, not a search failure.

### Per-county SC table

| County | Per-parcel balance | Multi-year history | GIS layer | Advertised sale list | Forfeited Land Commission (buy direct) | Sold but unredeemed |
|---|---|---|---|---|---|---|
| **Spartanburg** | Payment portal | **Yes, 1999 to 2026, one query** | None | https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info states the final 2025 list is unavailable; newspaper is goupstate.com | **Yes, two live text PDFs:** https://www.spartanburgcounty.gov/DocumentCenter/View/102066 (real estate: item number, address, defaulting taxpayer, map number, total tax due, only six properties currently) and https://www.spartanburgcounty.gov/DocumentCenter/View/104129 (mobile homes). Pre-2023 sales only via the outside auctioneer. | **Best in the state.** Status "Sold at Tax Sale" appears under an unpaid search, per parcel, with amount and year. |
| **Oconee** | Payment portal | 2016 to 2025 only | DT2023, DT2024, DT2025, plus the FLC assignment layer | **Public Google Sheet**, 651 rows: item number, owner name, map number, description, total tax due, plus a GIS map. 2026 sale November 9, list posts October 21. | FLC assignment layer, 189 rows with bid and assignment status, plus two web maps. **Maps go dark roughly October to January.** | Redeemed column exists but is empty on all 476 rows. The assignment field tracks FLC assignment, not owner redemption. |
| **Pickens** | **None. No bulk portal.** Per-parcel qPublic card only. | Via six annual GIS snapshots, not a live ledger | **2020 through 2025, richest schema** | https://www.co.pickens.sc.us/departments/delinquent_tax/index.php carries an unofficial tax sale list and sale-results PDFs 2014 to 2025. Sale October 13, 2026. | FLC_2022 layer plus an FLC list link | Status uniformly "A," sale date and sale price empty |
| **Cherokee** | Payment portal | Yes, via year All | None | PDFs under https://cherokeecountysc.gov/wp-content/uploads/ , for example `2023-Delinquent-Tax-List.pdf`, ten pages, roughly 2,260 items, columns item number, name, map number, description. **No dollar amounts.** Includes "NEW OWNER" heir and transfer rows. | None published, office contact only | Portal status only |
| **Union** | Payment portal | Yes, via year All | None | **Newspaper only** (Union County News, three weeks pre-sale). Nothing online. | **In person only** at the Auditor's Office. The 2025 sale list was available from January 14, 2026. | Portal status only |
| **Laurens** | Payment portal | Yes, via year All | None | E-edition newspaper replica at http://1543.newstogo.us plus https://www.laurenscountysc.gov/departments/treasurer/delinquent_taxes.php | "Current FLC List" appears in the navigation but the **link 404s**; the overage list and claim form links are also broken | Portal status only |
| **Anderson** | **Wall.** ACPASS requires registration. | None free | None | https://anderson.postingpro.net sits behind an agreement and cookie gate and is **seasonal only**: listings go live September 30, 2026 for the October 19, 2026 sale | Third-party auctioneer, 90-plus properties with parcel and address only, no owner or bid, contract package PDF, bidding starts at $100 | Nothing |

**Correction worth propagating:** `laurenscounty.us` now redirects to an unrelated commercial domain. The domain lapsed. Use `laurenscountysc.gov`. Anything pointed at the old host is silently dead.

### SC redemption, explicitly

South Carolina gives a twelve-month redemption after tax sale, confirmed on the Pickens, Anderson, Oconee, Union, and Laurens pages. Laurens states the deed issues within 45 business days after the period ends.

**No county in the seven publishes a standalone list of sold-but-unredeemed properties.** Redemption ledgers live in the delinquent tax office as tax sale books; Laurens has a formal public-records procedure for researching them.

The one free systematic substitute, verified live: **Spartanburg's payment portal returns "Sold at Tax Sale" as a status under an unpaid search**, per parcel, with year and amount. A parcel showing that status is sold and not yet redeemed. That is peak distress with a name and a tax map number attached. Every purpose-built redemption field elsewhere is empty.

## 3.2 North Carolina, eleven counties

### The headline: the best multi-year source is Henderson, not Buncombe

**Henderson County publishes a free, public, no-auth, daily-refreshed CSV covering tax years 1993 through 2026 in one file.**

The bill portal is a React app whose API base is the page origin and whose tenant is passed as an HTTP header.

```
GET https://bcpwa.ncptscloud.com/api/GetTaxpayerDownloadList
    header  X-Tenant: Henderson
 -> [{"blobName":"BillPWA/TaxpayerDownloads/Delinquent Export/DelinquentExtract.csv",
      "fileSize":5911849,"fileDate":"2026-08-02T06:02:23"}]

GET https://bcpwa.ncptscloud.com/api/DownloadTaxpayerDownloadBlob?fileName=<url-encoded blobName>
    header  X-Tenant: Henderson
 -> {"downloadUrl":"https://nlgscpsatppstorage.blob.core.windows.net/henderson/...?<signed>","expiresAt":...}
```

Gotcha: the blob name contains a literal space, so the signed URL path must be percent-encoded or the fetch fails.

**Verified contents: 25,450 rows, all unpaid, 34 distinct tax years, 1993 through 2026.** Columns: bill number, bill type, parcel number, tax year, owner name, three mailing address lines, in-care-of, mailing city, state, ZIP, abstract taxable value, description, property size, abstract assessed value, bill status, bill amount, bill due amount, interest due, total due amount, bill due date, flags.

- Bill type splits: individual 18,922, business 4,156, **real estate 2,368**, public 4. Real estate is exactly the set with a populated parcel number. Filter on that.
- **1,152 distinct real-estate parcels. 367 are delinquent in two or more years.** The longest run is parcel 9949845 at 31 consecutive years, 1995 through 2025. Four more parcels sit at 27 years. Total real-estate amount owed: $1,254,878.63.
- Real estate by year: 2020: 50, 2021: 63, 2022: 83, 2023: 167, 2024: 343, **2025: 1,065**, 2026: 34 just-issued.
- The flags column is a free distress enrichment: delinquent, uncollectable (722 rows), **return mail not deliverable (471 rows, a vacancy signal)**, ownership transfer, judgment filed, return mail addressee not known, return mail forward time expired.

The same host also exposes bill search filters (tax years 2016 to 2026, statuses deferred, paid, unpaid), an advanced bill search POST, and a simple bill search GET.

**Tenant enumeration.** The tenant-validation endpoint was tested against 40 NC counties. Only **Henderson, Madison, and Forsyth** return true. Every other footprint county returns false. Madison is in the wider footprint and has the identical CSV, 2.79 MB, refreshed the same morning.

Henderson also runs a companion land-records portal at https://lrcpwa.ncptscloud.com/Henderson/ .

### Buncombe ArcGIS: verified, with three material corrections

Organization `services6.arcgis.com/VLA0ImJ33zhtGEaP`, 591 services, all public, every item modified 2026-07-31, which indicates a nightly refresh. Officially linked from https://www.buncombenc.gov/604/Tax-Collections through https://data.buncombecounty.org/search?tags=Tax . Query capability only, 2,000-record page size.

**Correction 1: the "every year 2009 to 2026" claim is true at the item level, but 2009 through 2012 contain zero rows.** Real coverage with data is 2013 through 2026, fourteen years.

**Correction 2: the service URL names are wrong for 2021 and 2022.** The 2021 service uses underscores in its name, and the service literally named "Unpaid Property Bills from 2021" (with spaces) contains levy year 2022. **Resolve by item ID, never by URL string.**

**Correction 3: most rows are not real estate.** Rows with a blank PIN are personal-property, business-personal, and vehicle bills. Real estate is the subset with a non-empty PIN.

| Year | Total rows | Rows with PIN (real estate) |
|---|---:|---:|
| 2009 to 2012 | 0 | 0 |
| 2013 | 414 | 16 |
| 2014 | 212 | 21 |
| 2015 | 127 | 17 |
| 2016 | 185 | 19 |
| 2017 | 287 | 34 |
| 2018 | 540 | 33 |
| 2019 | 890 | 52 |
| 2020 | 3,123 | 58 |
| 2021 | 3,287 | 77 |
| 2022 | 4,175 | 114 |
| 2023 | 4,847 | 205 |
| 2024 | 6,255 | 376 |
| 2025 | 7,922 | **1,076** |
| 2026 | 125,827 | 103,285 |

Fifty-three fields confirmed, including both owner names, address lines, city, state, postal code, township, city, fire and school codes, subdivision, PIN, sub-lot, full street breakdown, plat book and page, deed book, page, date and instrument, acres, **mortgage company and loan number**, real, personal, deferred, exempt and total value, levy year, original bill amount, and the full due breakdown. **All numerics are strings**, so a numeric comparison in a where clause returns HTTP 400.

**The 2026 table is the early-detection lever.** Those 103,285 real-estate bills are "unpaid" only because 2026 bills were issued 7/8/2026 and are not due until September 1, delinquent January 6, 2027. Poll it monthly. The residual set as January approaches is a pre-delinquency watchlist that precedes the statutory advertisement (published around June) by roughly six months.

A companion series, "All Property Bills from YYYY," covers 2004 through 2026 at 169,000 to 207,000 rows from 2011 onward. That is the full roll, not just unpaid.

**Does any other NC county publish an equivalent? No.** Searched ArcGIS Online four ways. No county matches Buncombe's per-year archive. Two NC counties publish a single current snapshot, and neither is in the eleven:

- **Guilford:** https://services5.arcgis.com/RR1v7NWFfwk98pUn/arcgis/rest/services/Tax_Delinquent_Report_/FeatureServer/0 , 9,749 rows, tax years 2016 to 2025. Its schema is byte-for-byte the same delinquent extract layout Henderson publishes as CSV, which proves the extract is a standard product of the statewide tax software that some counties choose to republish.
- **Pitt:** https://gis.pittcountync.gov/gis/rest/services/PittOpenData/Tables/MapServer/9 , 9,170 rows.

### The G.S. 105-369 annual advertisement, per county

| County | Form | URL | Machine-readable? |
|---|---|---|---|
| **Buncombe** | County PDF plus ArcGIS | https://www.buncombenc.gov/DocumentCenter/View/2171 (stable "latest" URL, 7 pages, 2025 tax year as of 5:00 pm 5/31/2026, board order 2/3/2026, **1,650 unique 15-digit PINs**, owner, PIN, amount, situs). Prior-year copy at https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf (12 pages, 1,163 PINs) | Yes, text layer |
| **McDowell** | County PDF | https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement then the current file `ADVERTISEMENT-LIST-FINAL-2025.pdf`, 49 pages, owner name, parcel, total due. Newspaper mirror at mcdowellnews.com legal print ads. | Yes, text layer |
| **Lincoln** | County PDF | https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice , 33 pages, 2025 taxes unpaid as of 4/21/2026, signed 5/1/2026, parcel ID plus amount | Yes, text layer |
| **Henderson** | Newspaper, free HTML archive | https://www.hendersonvillelightning.com/legal-ads/131-tax-notices.html carries the 2015, 2021 and 2025 advertisements plus municipal ads for Mills River, Hendersonville, Laurel Park and Saluda. Semicolon-delimited: primary owner; additional owners; description; parcel; total. | Yes, semicolon-delimited |
| Gaston, Cleveland, Rutherford, Burke, Polk, Transylvania | Newspaper only, no county-hosted list found | See statewide fallback below | No |
| **Mitchell** | Newspaper only, **and a trap.** The county site's tags for tax-lien advertisement each have a count of one and attach to Board of Commissioners minutes, meaning the order authorizing advertisement, not the list. A media search returns nothing. | | No |

**Statewide fallback:** https://www.ncnotices.com/ , the NC Press Association legal notice site. Confirmed to carry all 100 counties in its county filter with keyword, exact-phrase and date search. It is an ASP.NET WebForms app with the session baked into the URL path and a single postback form, so it requires viewstate replay. No CAPTCHA observed. **This is the only route to the advertisement for the six newspaper-only counties plus Mitchell.**

**A multi-year archive of the advertisements is essentially unavailable.** McDowell prior-year filename probes for 2019 through 2024 and 2026 all 404. Wayback lookups for the McDowell, Lincoln and Buncombe domains filtered on delinquent, advertisement and lien return nothing usable. **The advertisements are current-year-only by design.**

### Per-parcel NC tax balance systems

| County | Vendor and host | Unpaid browse? | Blocker class |
|---|---|---|---|
| **Henderson** | Bill portal https://bcpwa.ncptscloud.com/Henderson | **Yes, bulk CSV, 1993 to 2026, daily** | None. Open JSON API. |
| **Buncombe** | https://tax.buncombenc.gov (ASP.NET form POST to /Search/Results) | **Yes, via the ArcGIS feeds**, which the county itself links as a download-all option | None |
| **Transylvania** | https://tax.transylvaniacounty.org/TaxBillSearch | **Yes in the UI**: an unpaid-bills-only checkbox and a tax year selector offering All Years and 2026 back to 2017 | **No CAPTCHA, no bot wall.** A plain HTTP replay is incomplete: the partial-table POST returns 200 with zero bytes and the data POST then returns 500 with a null-reference message, while the basic and real-estate search controllers respond fine. It is a session and view-model shape issue that a real browser resolves. |
| **Gaston** | https://gastonnc.devnetwedge.com/ (data updated 2026-07-31) | **No.** Every advanced search field was enumerated: owner name, parcel key, property classes, sale date range, total tax range, acreage, year built, and more. **There is no unpaid or delinquent filter.** | Per-parcel only, by design |
| **Burke** | https://burkenctax.com | No | **Google reCAPTCHA on the search pages. Compliance stop.** |
| **Cleveland** | https://clevelandcountytaxes.com | No | **reCAPTCHA. Compliance stop.** |
| **Rutherford** | https://www.rutherfordcountync.gov/tax_search/index.php (embeds a hosted search) | No | Per-parcel only |
| **Lincoln** | https://lincolncountytax.com | No | Per-parcel only |
| **Polk** | https://esearch.polk-tax.com/ , also linked from https://www.polknc.gov/tax_search/ | No | **reCAPTCHA present. Compliance stop.** |
| **Mitchell** | https://mitchellcounty.tax , plus an assessor-only search at https://nc-mitchell.publicaccessnow.com/Assessor/PropertySearch.aspx and a map search at https://propaccess.trueautomation.com/mapSearch/?cid=29 . Note `mitchell.webtaxpay.com` fails TLS hostname verification on a direct HTTPS request. | No | Fragmented, per-parcel only |
| **McDowell** | https://mcdowellnc.gov/departments/tax-collections/online-search-and-or-payment | No | Per-parcel only |

### NC tax foreclosure sale lists

Kania's JSON (see Section 1.4) is the primary. In footprint: Burke 12, Rutherford 15, Cleveland 7, Lincoln 7, Polk 1, for 42 rows. **Kania does not serve Buncombe, Henderson, Gaston, McDowell, Transylvania or Mitchell.**

| County | Foreclosure list source | Notes |
|---|---|---|
| Buncombe | https://taxforeclosures.buncombenc.gov/ , backed by the Trumba calendar feeds | Best structured feed of the eleven. Custom fields include opening/current bid, a redeemed yes/no flag, case number, PIN, property type and fire district. No upset deadline field. |
| Gaston | https://www.gastongov.com/669/Tax-Foreclosure-Sales and https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales | Owner, parcel, physical address, sale date, starting bid, file number, plus the archive with full upset detail |
| Cleveland | https://www.clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php | Parcel, file number, address, map-block-lot; flags properties in the ten-day upset window; also lists county-owned post-foreclosure inventory |
| Rutherford | https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_information/ plus Kania | |
| Lincoln | Kania. The county page at https://www.lincolncountync.gov/2368/Foreclosures says there are none while Kania shows seven live files. **Trust Kania.** | |
| Burke, Polk | Kania only | No county-hosted list |
| McDowell | https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales | Currently one active row |
| Henderson | https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales | No list published, email notification list only |
| Transylvania | https://www.transylvaniacounty.org/news/foreclosure-sale | Dead. Newest item is a December 2017 sale. Email notification via the tax office. |
| Mitchell | None found | |

## 3.3 The straight verdict on multi-year tax history

### South Carolina

| Tier | Counties | What you get |
|---|---|---|
| **Full history, structured, free, one query** | Spartanburg (1999 to 2026), Cherokee, Union, Laurens (portal retention) | The payment portal's year-All option returns every parcel-year receipt on the server. No snapshotting needed. Requires the prefix-deepening crawl. |
| **Partial history, structured, free** | Oconee | Portal covers 2016 to 2025. GIS adds 2023, 2024, 2025 with amounts. **2019 through 2022 were never published and cannot be obtained by anyone at any price from a free source.** Gone unless the county's internal ledger is requested under FOIA. |
| **History only as annual snapshots** | Pickens | No balance portal at all. Six annual GIS layers, 2020 through 2025, with owner mailing address and amounts in the best years. The county has been archiving per year, but nothing guarantees it continues. Mirror each new layer on publication. |
| **No history, seasonal window only** | Anderson | Everything is behind either a registration wall or an agreement gate. The only free window is the posting site from roughly September 30 to sale day each year. Miss it and the year is gone. |

**What must be snapshotted in SC:** Anderson (everything, seasonally), the Oconee Google Sheet (overwritten each cycle, rolls over around October 21), the Oconee FLC maps (explicitly unavailable roughly October to January), the Spartanburg FLC PDFs (republished at the **same** document IDs, so each update destroys the prior list), each new Pickens annual layer, and the Union, Laurens and Cherokee advertised lists (newspaper or e-edition, three-week window).

### North Carolina

| Tier | Counties | What you get |
|---|---|---|
| **Full history, structured, free** | **Henderson** | 34 years, 1993 to 2026, in one daily CSV. 1,152 real-estate parcels, 367 delinquent in two or more years, consecutive runs up to 31 years, plus return-mail and uncollectable flags. One HTTP call. |
| **Deep history, structured, free** | **Buncombe** | 14 years with data, 2013 to 2026, across nightly-refreshed feature services, with full mailing address, situs, deed reference, values, and mortgage company. Real-estate volume in the old years is thin (16 to 114 per year), so the value is the repeat-appearance signal plus the 2025 and 2026 tables. |
| **Current year only, structured** | **McDowell, Lincoln** | One machine-readable PDF per year with owner, parcel and amount. No archive: prior-year filenames 404 and Wayback is empty. Build history only by snapshotting forward from now. |
| **Current year only, browsable but unbuilt** | **Transylvania** | A year-by-year unpaid browse exists in the UI covering 2017 to 2026. Needs a real browser. **The highest-value unbuilt NC target after Henderson.** |
| **Current year only, newspaper** | **Gaston, Cleveland, Rutherford, Burke, Polk, Mitchell** | The statutory advertisement, via ncnotices.com or the local paper. No county-hosted list, no archive. |
| **Blocked by CAPTCHA, do not pursue** | Burke, Cleveland, Rutherford, Polk | Their per-parcel lookups are unreachable compliantly. Their delinquency signal must come from the newspaper advertisement plus the tax-foreclosure counsel feed. |

**The blunt version.** For six of the eleven NC counties, multi-year tax delinquency history **does not exist in any free public form and cannot be obtained by anyone at any price short of a public-records request to the tax office.** The counties do not retain it in published form, and the statutory advertisement is a once-a-year current-year snapshot that nobody archives. The realistic ceiling is two counties with true history, two more with an annual PDF you snapshot forward, one browsable but unbuilt, and six where the only recurring signal is the annual advertisement plus the foreclosure counsel feed.

---

# SECTION 4: THE COMPLETE FIELD TAXONOMY

112 fields, grouped. Each row gives the best free source, a paid fallback with a price where one exists, and a classification.

## 4.A Property, 50 fields

| # | Field | Best free source | Paid fallback | Class |
|---|---|---|---|---|
| A1 | Parcel ID, PIN, tax map number | County GIS; NC OneMap statewide parcels layer (verified keyless) | Regrid, quote only | FREE-AUTOMATED |
| A2 | Situs address | County GIS site-address field; NC OneMap fallback | Regrid, ATTOM from about $90/mo | FREE-AUTOMATED |
| A3 | Latitude and longitude | Parcel polygon centroid; FCC block API (verified 200) | none needed | FREE-AUTOMATED |
| A4 | Legal description | Deed index and image where free | DataTree or TitlePro, roughly $100 to $200/mo | FREE-MANUAL |
| A5 | Acreage, lot size | County GIS acres field or polygon area | Regrid | FREE-AUTOMATED |
| A6 | **Heated square footage** | NC assessor layers carry it. **SC GIS is blank everywhere:** living area is zero on all 29,402 rows of the SC assessor mirror. SC path is the per-parcel qPublic card (Pickens, Oconee). | Paid county assessor extract; ATTOM | FREE-AUTOMATED in NC, FREE-MANUAL in SC |
| A7 | Bedrooms | NC assessor; SC per-parcel card | ATTOM, PropStream $99/mo | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A8 | Bathrooms | Same | Same | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A9 | Year built | County GIS and assessor | ATTOM | FREE-AUTOMATED |
| A10 | Construction type, exterior wall | Assessor card; some GIS layers | Paid assessor extract | FREE-MANUAL |
| A11 | **Roof age** | Material is sometimes on the assessor card. **Age is almost never recorded.** A re-roof permit date is the only proxy. | Insurance and inspection data, not resold | PHYSICALLY-UNRECORDED (age), FREE-MANUAL (material) |
| A12 | **HVAC type and age** | Assessor card lists heat type. **Age is unrecorded.** Mechanical permit is the proxy. | none | PHYSICALLY-UNRECORDED (age) |
| A13 | Septic vs sewer | County health department septic permit layers (several NC counties publish); assessor utility code | Paid assessor extract | FREE-AUTOMATED (partial) / FREE-MANUAL |
| A14 | Well vs public water | Same as A13; utility service-area GIS | Paid assessor extract | FREE-AUTOMATED (partial) |
| A15 | Zoning | County and municipal zoning GIS | Regrid zoning bundle | FREE-AUTOMATED |
| A16 | Land use code | County GIS and assessor | Regrid | FREE-AUTOMATED |
| A17 | **Flood zone** | **FEMA National Flood Hazard Layer, verified 200, keyless:** https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer | none needed | FREE-AUTOMATED |
| A18 | **Soil type and class** | **USDA Soil Data Access, verified 200, POST SQL, keyless:** https://sdmdataaccess.sc.egov.usda.gov/Tabular/SDMTabularService/post.rest | none needed | FREE-AUTOMATED |
| A19 | **Topography and slope** | **USGS point elevation, verified 200, keyless:** https://epqs.nationalmap.gov/v1/json?x=&y=&units=Feet plus the 3DEP elevation model for slope | none needed | FREE-AUTOMATED |
| A20 | Road frontage | Parcel polygon against road centerline geometry (computed); some assessor records carry frontage feet | Paid assessor extract | FREE-AUTOMATED (computed) |
| A21 | Access and easements | Recorded easements by document type; landlocked status computable from geometry | Title search $75 to $200 per parcel | FREE-MANUAL |
| A22 | Utilities available at road | Municipal utility service-area GIS; FCC for broadband | Utility company direct | FREE-AUTOMATED (partial) |
| A23 | School district and assigned schools | **Urban Institute education data API, verified 200, keyless:** https://educationdata.urban.org/api/v1/schools/ccd/directory/ plus NCES district boundary files | GreatSchools API | FREE-AUTOMATED |
| A24 | HOA membership (does one exist) | Recorded declaration of covenants; subdivision plat; NC and SC Secretary of State nonprofit registration for the association entity | PropStream flags it | FREE-MANUAL |
| A25 | **HOA dues amount** | **No public record.** Only the association, the management company, or a resale certificate states it. | Resale certificate $200 to $400, ordered by a party to a transaction | REQUIRES-CONSENT |
| A26 | Deed restrictions and covenants | Recorded declaration (free index; free images in Spartanburg-class counties) | Title search | FREE-MANUAL |
| A27 | Mineral rights severed | Recorded mineral reservation or severance deeds, requires reading the chain | Title or landman search from about $150 | FREE-MANUAL |
| A28 | Timber rights and standing timber value | Timber deeds in the record; aerial and LiDAR canopy as a volume proxy | Forestry cruise from about $500 | FREE-MANUAL (rights) / REQUIRES-PHYSICAL-VISIT (value) |
| A29 | Solar lease or power purchase agreement on the roof | **UCC-1 fixture filing at the NC or SC Secretary of State**, which is the real tell, plus a recorded lease memorandum | none needed | FREE-MANUAL |
| A30 | Cell tower lease | Recorded lease memorandum or easement; FCC antenna structure registration for the structure | Lease-buyout firms hold data they do not sell | FREE-MANUAL |
| A31 | **Environmental contamination** | **EPA Envirofacts REST, verified 200, keyless:** `https://data.epa.gov/efservice/<table>/<column>/<value>/rows/0:1/JSON` covering toxics release, hazardous waste, Superfund, and underground storage tanks; plus state environmental agency brownfield layers | Phase I environmental report, $300 to $600 | FREE-AUTOMATED |
| A32 | Historic designation | **National Park Service historic register map service, verified 200, keyless:** https://mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer plus local historic district GIS | none needed | FREE-AUTOMATED |
| A33 | Radon zone | EPA county radon zone tables, county level only | Home test kit about $15 | FREE-AUTOMATED (county) / REQUIRES-PHYSICAL-VISIT (actual) |
| A34 | Wetlands | US Fish and Wildlife National Wetlands Inventory map service | Delineation from about $2,000 | FREE-AUTOMATED |
| A35 | **Exterior condition** | Street-level imagery plus a vision model. Stale by one to four years, worse in rural areas. | Drive-by service $10 to $25 | FREE-AUTOMATED (proxy) |
| A36 | **Interior condition** | **None. No free source exists.** Old listing photos are the only proxy and portal terms of service bar scraping them. | MLS or IDX access via a licensee; inspection about $400 | REQUIRES-PHYSICAL-VISIT |
| A37 | **Interior photos** | Prior-listing photos on portals (barred); assessor cards occasionally carry one interior shot | MLS access via a licensee | REQUIRES-PHYSICAL-VISIT |
| A38 | Exterior photos | Street-level imagery, county assessor parcel photos, NAIP aerial | none needed | FREE-AUTOMATED |
| A39 | Occupancy status | **Proxies only:** USPS vacancy indicator (licensed, see Section 5), mail return, tall grass in imagery, absentee mailing mismatch | USPS or Melissa vacancy flag inside PropStream $99/mo, or DSF2 through a licensed mail service provider | PAID (clean) / FREE-AUTOMATED (proxy) |
| A40 | Vacancy duration | Compare imagery capture dates | none | PHYSICALLY-UNRECORDED |
| A41 | Rental status | Absentee-owner flag; short-term rental registries where they exist; local rental registration rolls | PropStream, RentCast | FREE-AUTOMATED (proxy) |
| A42 | **Current rent being collected** | **None. Rent is a private contract.** | RentCast or portal rent estimates, roughly $50/mo, and they are estimates not actuals | PHYSICALLY-UNRECORDED (actual) |
| A43 | Building permits | Municipal permit portals; many publish open data | Shovels, BuildZoom | FREE-AUTOMATED (partial) / FREE-MANUAL |
| A44 | Code violations and open cases | Asheville publishes; **most counties have no free feed**; the statewide NC lien registry is login-gated | none reliable | FREE-MANUAL or public-records request |
| A45 | Tax assessed value | County GIS and assessor, tax bill portals | none needed | FREE-AUTOMATED |
| A46 | Tax bill amount | Tax portals; the SC payment portal, the NC bill portal | none needed | FREE-AUTOMATED |
| A47 | Market value estimate | Your own model from assessor plus sold comps | ATTOM AVM, HouseCanary | FREE-AUTOMATED |
| A48 | After-repair value | Computed. Currently unbiased at the median and noisy; trust the confidence score. | HouseCanary, Clear Capital | FREE-AUTOMATED |
| A49 | Sold comparables | **NC: excise stamp times 500 recovers price.** SC: distressed deeds state no value by statute; the per-parcel assessor card is the workaround. | ATTOM, PropStream comps | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| A50 | Days on market and prior listing history | **No compliant free route.** Portal terms bar scraping listing history. | MLS via a licensee; ATTOM listing history | PAID |

## 4.B Owner, 25 fields

| # | Field | Best free source | Paid fallback | Class |
|---|---|---|---|---|
| B1 | Legal name | County GIS owner field; deed grantee index | none needed | FREE-AUTOMATED |
| B2 | All co-owners and vested parties | The deed is authoritative; the GIS second-owner field is often truncated | Title search | FREE-AUTOMATED (partial) / FREE-MANUAL (full) |
| B3 | Entity vs individual | String heuristic on the owner name | none needed | FREE-AUTOMATED |
| B4 | Entity officers | **NC Secretary of State via a real browser.** A plain client gets a Cloudflare 403; it is a JavaScript challenge, not a CAPTCHA. **SC Secretary of State is CAPTCHA-gated**, so SC entities are skipped. | OpenCorporates paid token | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| B5 | Registered agent | Same as B4 | OpenCorporates | FREE-AUTOMATED (NC) |
| B6 | Entity good standing, administrative dissolution | NC Secretary of State profile. Dissolution is itself a distress signal. | none needed | FREE-AUTOMATED (NC) |
| B7 | **Trust beneficiaries** | **Trusts are not registered.** Only the trustee name appears on the deed. | none | PHYSICALLY-UNRECORDED |
| B8 | Mailing address | County tax roll mailing field; probate personal-representative address | none needed | FREE-AUTOMATED |
| B9 | Absentee or out-of-state status | Compare mailing state to situs state | none needed | FREE-AUTOMATED |
| B10 | **Phone** | **NC voter file, verified free bulk download, about 498 MB:** https://dl.ncsbe.gov/data/ncvoter_Statewide.zip , roughly 69% NC coverage. **SC has no free route:** the SC voter list is sold, purpose-restricted, and carries no phone. | Skip trace **$0.07 to $0.25 per record**; TLOxp from about $100/mo; Accurint from about $200/mo with per-trace fees | FREE-AUTOMATED (NC only) / PAID (SC) |
| B11 | **Email** | **None. No free compliant source exists.** | Email append, per hit | PAID |
| B12 | Age or date of birth | **County jail booking rosters carry full DOB.** The NC voter file carries age but **not** date of birth, confirmed against G.S. 163-82.10, so jail DOB is genuinely net-new in NC and not substitutable. | Skip trace | FREE-AUTOMATED once built |
| B13 | **Marital status** | Deed vesting language ("husband and wife," "a single person") is the free tell. Marriage licenses are county-level and patchy online. | Skip trace | FREE-AUTOMATED (proxy) / FREE-MANUAL |
| B14 | Heirs | Heir-parcel GIS sweep for "HEIRS" and "ESTATE OF" owner strings; probate personal-representative name and address; obituary survivor lists | none needed | FREE-AUTOMATED |
| B15 | Death and date of death | Obituaries (newspaper group and funeral-home feeds); probate filings. The federal death index is no longer openly published. | LexisNexis deceased flag | FREE-AUTOMATED |
| B16 | **Federal incarceration** | **Federal Bureau of Prisons inmate locator JSON, verified 200, returns `"Captcha":false`:** https://www.bop.gov/PublicInfo/execute/inmateloc?todo=query&output=json&nameFirst=&nameLast= | none needed | FREE-AUTOMATED |
| B17 | State and county incarceration | SC Department of Corrections wired; NC offender search reachable but JavaScript-heavy; county jail rosters reachable on three vendor platforms and build-ready | none needed | FREE-AUTOMATED |
| B18 | Bankruptcy | **CourtListener RECAP v4, verified keyless, 133 results on the NC Western Bankruptcy court:** https://www.courtlistener.com/api/rest/v4/search/?type=r&court=ncwb&q= | PACER at $0.10 per page | FREE-AUTOMATED |
| B19 | Number of properties owned | Owner-name index across county GIS layers, or a self-join on your own board | PropStream portfolio search $99/mo | FREE-AUTOMATED |
| B20 | Other liens against the person | Deed name index for existence; SC Department of Revenue top-delinquent list | Title search per name | FREE-AUTOMATED (existence) |
| B21 | Civil judgments | **NC eCourts Judgment Search JSON, open and keyless.** SC Public Index is a terms-of-service wall. | UniCourt, Trellis | FREE-AUTOMATED (NC) / FREE-MANUAL (SC) |
| B22 | **Employment** | **None.** An employer appears only in a UCC or unemployment-tax lien edge case or a court filing. | Skip trace or credit header, restricted use | PAID (restricted) |
| B23 | **Income** | None | Credit-header data is FCRA-restricted for this use | LEGALLY-SEALED |
| B24 | **Credit score and payment history** | **None. FCRA bars use for deal sourcing.** | Not lawfully purchasable for this purpose | LEGALLY-SEALED |
| B25 | Relatives and associates | Obituary survivor lists; shared-surname parcel joins | Skip trace relationship graph | FREE-AUTOMATED (partial) / PAID |

## 4.C Distress event, 25 fields

| # | Field | Best free source | Paid fallback | Class |
|---|---|---|---|---|
| C1 | **Mortgage original principal** | **The index carries type, lender, date and book/page but no dollar figure. The number is only on the scanned instrument image.** Free images confirmed in Spartanburg (roughly 280 to 315 KB PDFs, no cart, no login). OCR them. The OCR enricher is built and proven but is hardcoded to one county, capped at 25 documents per run, and gated to hot and warm leads, and has never run at scale. **Recorded loan dollars are 0.0% of the board. This is the single largest unforced gap.** | DataTree or TitlePro, roughly $100 to $200/mo | FREE-AUTOMATED in Spartanburg-class counties / FREE-MANUAL where images are paywalled |
| C2 | **Current loan balance or payoff** | **None. Cannot be obtained by anyone at any price.** Not public, changes mid-month, and is protected customer information. The mortgage registry lookup returns a servicer name only, and it returned a maintenance page at probe time so treat it as unverified today. | No vendor sells the real number. Every paid product models it. | PHYSICALLY-UNRECORDED |
| C3 | Lender and servicer name | Deed index (lender on the instrument); registry lookup for the current servicer | none needed | FREE-AUTOMATED |
| C4 | **Payment status, months delinquent** | **None, free or paid.** A foreclosure filing is the only public proxy and by then it is late. | none | PHYSICALLY-UNRECORDED |
| C5 | Foreclosure stage | NC judgment JSON for lis pendens; county foreclosure feeds; SC Master-in-Equity rosters; SC forfeited land lists | Foreclosure-data vendors | FREE-AUTOMATED |
| C6 | Sale date | Same as C5 plus auction feeds | none needed | FREE-AUTOMATED |
| C7 | Opening bid | Auction and Master-in-Equity rosters; currently populated on 723 leads | none needed | FREE-AUTOMATED |
| C8 | Judgment amount or indebtedness | NC judgment records plus the money field in the Courthouse deed vendor's schema; currently on 187 leads. **NC power-of-sale notices legally state only sale terms, deposit and the upset bid rule, never the debt: zero of 24 sampled notices carried any dollar figure.** | none | FREE-AUTOMATED (partial) / public-records request to the Clerk |
| C9 | Redemption deadline | Statutory, computed from the sale date | none needed | FREE-AUTOMATED (computed) |
| C10 | Upset-bid status | See Section 1. Kania and Hutchens statewide, plus McDowell and the Gaston archive. | none needed | FREE-AUTOMATED once built |
| C11 | Tax delinquency amount | **The strongest lane, currently 39.2% of the board.** See Section 3. | none needed | FREE-AUTOMATED |
| C12 | Tax delinquent years | Same sources, year columns in the roll | none needed | FREE-AUTOMATED |
| C13 | Other liens and priority | Deed index for existence; SC state tax lien list | Title search $75 to $200 | FREE-AUTOMATED (existence) / PAID (full priority) |
| C14 | **IRS federal tax lien** | Free where the index is open. **NC files these with the Clerk of Superior Court, SC with the Register of Deeds.** Not free at scale across walled counties. | Lien vendors | FREE-MANUAL |
| C15 | **HOA arrears** | Only if a lien was filed. In NC that is the Clerk of Superior Court, in SC the Register of Deeds. **Un-liened arrears are invisible.** | none | FREE-MANUAL (liened) / REQUIRES-CONSENT (un-liened) |
| C16 | **Utility shutoff** | **None. Customer billing records are exempt from public records in both states.** See Section 5. | none | LEGALLY-SEALED |
| C17 | Probate stage | Charleston's probate search (case, decedent, **personal representative name and full mailing address**); heir-parcel GIS; published estate creditor notices. **Greenville SC probate is net-new and build-ready** via a plain GET last-name search returning thousands of rows. | UniCourt | FREE-AUTOMATED |
| C18 | Divorce stage | **The NC judgment JSON already returns a family-divorce cause of action with both spouses structured.** The board has one divorce lead only because the filter was never widened. SC's family court case management system forbids automated querying, which is a legal wall, not a technical one. | UniCourt, Trellis | FREE-AUTOMATED (NC, config change) / FREE-MANUAL (SC) |
| C19 | **Eviction filings, seller side** | **Confirmed wall.** The SC portal exposes only circuit-court roster types; there is no magistrate or ejectment roster type at all. NC eviction is walled. | Public-records request to the chief magistrate; research data-sharing agreements | FREE-MANUAL (request only) |
| C20 | Vacancy duration | Imagery capture-date deltas | USPS vacancy flag inside a vendor product | PHYSICALLY-UNRECORDED |
| C21 | Code cases | Asheville publishes; most counties have no free feed | none | FREE-MANUAL |
| C22 | Lis pendens | NC judgment JSON statewide, currently 1,178 leads | none needed | FREE-AUTOMATED |
| C23 | Bankruptcy chapter and 363 sales | CourtListener. A query for motions to sell real property surfaces trustee sales. Fixes needed: add the NC Middle Bankruptcy court, switch to the keyless search endpoint, and read the party array and schedules. | PACER | FREE-AUTOMATED |
| C24 | Mortgage recording date and loan age | Deed index. **The date is in the index even when the dollar is not.** | none needed | FREE-AUTOMATED |
| C25 | Second deed of trust or HELOC, existence and amount | Existence from the index; **amount only from the image**, same free-image ceiling as C1 | Title search | FREE-AUTOMATED (existence) / FREE-MANUAL (amount) |

## 4.D Market context, 12 fields

| # | Field | Best free source | Paid fallback | Class |
|---|---|---|---|---|
| D1 | Recent arms-length sales | **NC: excise stamp times 500.** SC: distressed deeds state no value by statute and the search grid omits consideration. Structural, not a bug. | ATTOM, PropStream $99/mo | FREE-AUTOMATED (NC) / PAID (SC bulk) |
| D2 | Price per square foot | **NC: computable**, price from stamps and square footage from assessor. **SC: not computable free**, because both sale amount and living area are blank across every free SC GIS layer. | Paid county assessor extract | FREE-AUTOMATED (NC) / PAID (SC) |
| D3 | Rent comparables | **HUD Fair Market Rent API returns unauthenticated without a token; the token is free on registration.** **Census American Community Survey median gross rent returns "missing key"; the key is free.** Both are area medians, not unit-level. | RentCast about $50/mo; portal rent estimates | FREE-AUTOMATED with a free key, area level / PAID for unit level |
| D4 | **Capitalization rates** | **None free.** A cap rate requires actual net operating income, which is private. | CBRE, Trepp, CRED-iQ subscriptions | PAID |
| D5 | Absorption rate | No compliant free source | MLS via a licensee; portal research downloads at aggregate level | PAID |
| D6 | Months of inventory | Portal research data centers publish metro and county aggregates free | MLS | FREE-AUTOMATED (aggregate) |
| D7 | List-to-sale ratio | Same as D6, aggregate only | MLS | FREE-AUTOMATED (aggregate) |
| D8 | Price trend and appreciation | FHFA House Price Index, free, county level; portal home value index research files | ATTOM | FREE-AUTOMATED |
| D9 | Buyer activity and cash-buyer counts | **Grantee-name frequency in the deed index.** Count the LLCs buying repeatedly. **This is the best free buyer-intelligence play available and it is underused.** | PropStream buyer search | FREE-AUTOMATED |
| D10 | **Structured investor buy box** | **None. No free, public, scrapeable structured buy box exists.** Land buyers name counties as marketing copy; builders take land by relationship. A curated static registry is the correct answer and it is already built. | Nobody sells this | PHYSICALLY-UNRECORDED |
| D11 | Rental vacancy rate | Census American Community Survey with a free key | none needed | FREE-AUTOMATED |
| D12 | Population, migration, new permits | Census ACS plus the Census Building Permits Survey | none needed | FREE-AUTOMATED |

## 4.E Verified versus unverified in this taxonomy

**Verified live by direct probe, HTTP 200, keyless unless noted:** FEMA flood map service; EPA Envirofacts; USDA Soil Data Access (POST SQL returned real map-unit rows); USGS point elevation (returned 2,084.9 feet); Bureau of Prisons inmate locator (returned real records, CAPTCHA flag false); National Park Service historic register; NC voter file bulk download (about 498 MB); Urban Institute education data; FCC census block API; CourtListener REST v4 (133 results); NC OneMap parcels.

**Verified as gated:** HUD Fair Market Rent returns unauthenticated (free token required); Census returns missing key (free key required); NC Secretary of State returns a Cloudflare 403 to a plain client and clears under a real browser, which was not re-tested this pass.

**Unverified:** the mortgage servicer registry returned a maintenance page at probe time. Pricing figures for PropStream ($99, $199, $699 per month), ATTOM (self-serve from roughly $90 to $95 per month, enterprise into five and six figures per year), and skip tracing ($0.07 to $0.25 per record, TLOxp from about $100/mo, Accurint from about $200/mo) come from vendor and comparison pages, not from a completed checkout, and vendor sales-gated pricing moves. Regrid publishes no per-county rate card and is quote-only.

Sources for pricing: https://www.propstream.com/news/how-much-does-propstream-cost , https://regrid.com/nationwide-parcels , https://batchdata.io/blog/best-skip-tracing-tools-for-bulk-data-processing

---

# SECTION 5: WHAT IS IMPOSSIBLE

## 5.1 Sealed by statute or court rule

Verification key: **[V]** means the statute text was fetched and read. **[K]** means it is cited from knowledge and should be checked before relying on it.

### 5.1.1 The single largest legal exposure in this business

**S.C. Code 30-2-50(A) [V]:** a person or private entity shall not knowingly obtain or use personal information obtained from a state agency, a local government, or other political subdivision of the State for commercial solicitation directed to any person in this State.
https://www.scstatehouse.gov/code/t30c002.php

- Subsection (B) requires every SC agency to notify requestors of this restriction. (C) requires agencies to take reasonable measures to prevent it. (D) makes a knowing violation a misdemeanor punishable by up to $500 and up to one year.
- **30-2-30 [V]** defines "personal information" to include **name, home address, and home telephone number**, plus date of birth, Social Security number, financial status, and employment history. The exclusions are narrow.
- "Commercial solicitation" is defined as contact by telephone, mail, or email for the purpose of selling or marketing a consumer product or service, with exclusions only for credit unions, continuing education, financial institutions covered by federal financial-privacy law, and political contact from voter registration data.

**The counterargument, stated fairly:** an unsolicited offer to *buy* the recipient's house is arguably not selling or marketing a consumer product or service *to* the recipient. That reading is available and is presumably how every SC direct-mail wholesaler operates. It is also not a reading anyone here can validate, there is no case law in hand, and the statute's plain text plus the mandatory agency notice under (B) cut the other way.

**Action: get a written opinion from a South Carolina real estate attorney before the next SC mail drop.** The SC half of the board is built entirely from SC public records. This is the highest-stakes open legal question in the business and it is cheap to answer.

**North Carolina is the mirror image and it is permissive.**

- **NC G.S. 132-6(b) [V]:** no person requesting to inspect and examine public records shall be required to disclose the purpose or motive for the request. Subsection (c): commingled confidential data is not grounds for denial and the agency bears the separation cost.
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-6.html
- There is no general NC commercial-use ban on public records. NC mail from public-records-derived lists is clean at the state-records level. Federal do-not-call still applies to calls.

**The one NC commercial-use restriction that does apply:**

- **NC G.S. 132-10 [V]:** counties and cities may condition electronic copies of GIS databases on a written agreement that the copy will not be resold or otherwise used for trade or commercial purposes. The statutory exceptions to what counts as commercial use are **news media publication, real estate trade association activities, Multiple Listing Service operations, and professional use by licensed practitioners in their practice.**
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-10.html
- Blunt: a real estate investor is not on that list. **A licensed North Carolina real estate broker is.** See 5.3.5.

### 5.1.2 Sealed records, state level

| Category | Authority | What is blocked | Read |
|---|---|---|---|
| Juvenile records | **NC G.S. 7B-3000 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_7B/GS_7B-3000.html | Examination limited to the juvenile, counsel, parent or guardian, prosecutor, court counselor, and probation. Everyone else needs a court order. | Irrelevant to lead generation. Do not build against it. |
| Adoption records | **NC G.S. 48-9-102 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_48/GS_48-9-102.html | All records created or filed in connection with an adoption, except the decree and the special proceedings index entry, are confidential. All indices sealed permanently on finality. | Kills adoption as an heir-discovery route. The index entry survives as a name-only breadcrumb. |
| Mental health and commitment records | **NC G.S. 122C-52 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_122C/GS_122C-52.html | Confidential information acquired in attending or treating a client is not a public record. | Involuntary commitment as a distress signal is permanently closed. Guardianship and incompetency proceedings under Chapter 35A are a separate, partial, public lane. |
| Expunged criminal records, NC | **NC G.S. 15A-153 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_15A/GS_15A-153.html | The person may lawfully deny the arrest. Employers and schools may not require disclosure or inquire. Penalty is a warning then up to $500 per additional violation. No private right of action. | The restriction runs to inquiry and use, not just to the file. Any cached pre-expunction copy becomes a liability. |
| Expunged and dismissed arrests, SC | **SC Code 17-1-40 [V]** https://www.scstatehouse.gov/code/t17c001.php | The arrest and booking record, bench warrants, **mugshots and fingerprints must be destroyed.** Law enforcement may hold under seal for three years and 120 days. **17-1-60 binds private publishers:** removal within 30 days of a documented written request, no fee may be charged, misdemeanor plus civil damages for violation. | This is the one expungement regime with teeth against a private data holder. **Any jail-booking lane must carry a purge path or it is a statutory violation waiting to happen.** |
| Sealed civil files | Inherent judicial authority; SC Rule 41.2 [K] | Whole file or discrete exhibits removed from the index, often the exact settlement or valuation you want | You usually cannot tell a sealed file exists. Silent gap. |
| Criminal investigation records | **NC G.S. 132-1.4 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.4.html | Investigation files are not public records. Mandatory release is narrow: time, date, location and nature of the violation; **name, sex, age, address, employment, and alleged violation of a person arrested or charged**; arrest circumstances; 911 content with carve-outs. | The mandatory-release list is why arrest data works at all. Note that address is in it and date of birth is not. |
| SC public-records exemptions | **SC Code 30-4-40 [V]** https://www.scstatehouse.gov/code/t30c004.php | Exempts trade secrets, unreasonable invasions of personal privacy, law enforcement materials, **medical records, hospital reports, scholastic records, adoption records**, and attorney correspondence and work product. | SC exemptions are broader and more discretionary than NC's. Expect more denials on identical request wording. |

### 5.1.3 Federally restricted, the ones that bite this business

| Category | Authority | Holding | Consequence |
|---|---|---|---|
| **Bank and servicer customer data by pretext** | **15 U.S.C. 6821 [V]** https://www.law.cornell.edu/uscode/text/15/6821 | Prohibits obtaining or attempting to obtain customer information of a financial institution by making a false, fictitious, or fraudulent statement to institution staff **or to customers**. Subsection (b) also bars asking someone else to do it. | **Calling a servicer posing as the borrower to get a payoff is a federal crime, and so is hiring anyone to do it.** This closes the most-wanted field in the business by the most tempting route. The only door is Section 5.4. |
| **Credit reports** | **15 U.S.C. 1681b [V]** https://www.law.cornell.edu/uscode/text/15/1681b | Permissible purposes are a credit transaction, employment, insurance underwriting, a government license, an investor or servicer valuing an **existing** credit obligation, a business transaction **initiated by the consumer**, and account review. Subsection (a)(2) allows use in accordance with the written instructions of the consumer. | **A cash buyer of a house has no permissible purpose.** Pulling credit to estimate a stranger's equity is a violation. Written instruction is the only clean route and it requires the seller at the table. |
| **Federal tax records** | **26 U.S.C. 6103 [V]** https://www.law.cornell.edu/uscode/text/26/6103 | Returns and return information shall be confidential. | Income, rental schedules and installment-sale reporting are permanently out. Nobody sells this. |
| **Driver and motor vehicle records** | **18 U.S.C. 2721 [V]** https://www.law.cornell.edu/uscode/text/18/2721 | A motor vehicle department shall not knowingly disclose. Bulk marketing and solicitation is allowed **only if the state has obtained the express consent of the person.** The research exception allows use only if not published, redisclosed, or used to contact individuals. | DMV address and date of birth are closed for outreach. The research exception is useless because it forbids contact, which is the point. |
| **Health information** | HIPAA Privacy Rule, 45 CFR 164.502 [K] | Binds covered entities and business associates | Health-driven distress is unobtainable except from the seller directly. |
| **Bank records via government process** | **12 U.S.C. 3402 [V]** https://www.law.cornell.edu/uscode/text/12/3402 | No **Government authority** may have access to a customer's financial records except as provided | Blunt correction to a common assumption: this restricts the government, not you. **It is not your obstacle. The financial-privacy pretexting statute is.** Do not cite the wrong one. |
| **Payoff statements** | **15 U.S.C. 1639g [V]** https://www.law.cornell.edu/uscode/text/15/1639g and **12 CFR 1024.36 [V]** https://www.consumerfinance.gov/rules-policy/regulations/1024/36/ | An accurate payoff balance within no more than seven business days of a written request from or on behalf of the borrower. Reg X: borrower or documented representative, acknowledge in five business days, ten business days for owner or assignee identity, thirty business days otherwise, and **the servicer may not charge a fee.** | Restricted, not impossible. **Consent-gated.** See 5.4. |
| **Telephone solicitation** | **NC G.S. 75-102 [V]** https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-102.html | No solicitation to a number on the national do-not-call registry. An existing-business-relationship exemption exists but collapses on request, with a 60-business-day scrub. | The claim that there is no NC or SC do-not-call list is right only in the narrow sense that neither state runs its own. **NC statutorily enforces the federal list.** Cold-calling scraped numbers without scrubbing is exposure in NC. |

### 5.1.4 Other state carve-outs that close specific avenues

- **NC G.S. 132-1.1(c) [V]:** billing information compiled and maintained by a city, county or other public entity providing utility services is not a public record. Exceptions are bond-related, service-integrity, and law-enforcement or judicial. **Utility shutoff and consumption as a vacancy signal is legally closed in North Carolina.** Do not build a scraper against it and do not file a request; it will be denied on the statute.
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.1.html
- **NC G.S. 132-1.10 [V]:** Social Security numbers and identifying information are confidential and not public record, and registers of deeds and courts may proactively redact online images. This is why deed-of-trust OCR yields loan amounts but no borrower identifiers, and it means **OCR yield will degrade over time as redaction coverage grows, not improve.** Plan for that.
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.10.html
- **NC G.S. 132-1.2 [V]:** eleven confidential categories, including voter date of birth, driver license and partial Social Security number, and electronic payment account numbers.
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_132/GS_132-1.2.html
- **NC G.S. 163-82.10 [V]:** voter lists are public with name, residence address, mailing address, sex, race, age, party and precinct, **but not date of birth.** Social Security number, date of birth, email, driver license number and photographs are confidential. Signatures may be viewed but not copied. No commercial-use ban in the statute. **This confirms the NC voter file cannot supply date of birth and that jail booking date of birth is genuinely net-new.**
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-82.10.html
- **SC voter lists** are sold by the State Election Commission on a fee schedule (the base electronic list was reduced to $25 in 2022, with larger tiers into the hundreds up to a cap) and **30-2-50 applies on top.** The political-contact exclusion protects political use only.
  https://scvotes.gov/resources/sale-of-voter-registration-lists/ (search-sourced, not directly fetched)
- **HUD USPS vacancy data** is aggregated at census tract only, and HUD states it may be made accessible only to governmental entities and non-profit organizations registered as users. A for-profit operator is ineligible, and tract-level aggregation would be useless for parcel targeting even if eligible. **Close this avenue.**
  https://www.huduser.gov/portal/datasets/usps.html (search-sourced; a direct fetch returned empty)

### 5.1.5 Privilege and private contract

- **Attorney-client and work product.** SC 30-4-40 [V] expressly exempts correspondence and work products of legal counsel for a public body, and NC has the parallel. Foreclosure firm files, servicer loss-mitigation notes, and internal valuation memoranda are permanently closed. This is why the firm-level feeds yield only public notice content and never the reserve, the broker price opinion, or the client's floor price.
- **Confidential settlements** are enforceable private contracts. The dollar figure in a settled construction-defect or partition action is unobtainable even when the case file is open.
- **Sealed exhibits in open cases.** Appraisals and payoff letters attached to a foreclosure complaint are sometimes sealed or redacted individually while the docket stays public.

## 5.2 Physically unrecorded

Nobody wrote these down. There is no vendor, no records request, no price. Every one is discovered by a conversation or a site visit, which is the actual argument for spending on outreach capacity instead of on more data.

### 5.2.1 Unrecorded interests that legally exist but leave no trace

- **Short leases.** NC G.S. 47-18 [V] requires registration only for leases longer than three years. SC 30-7-10 [K] requires recording only above twelve months, and SC law provides that possession does not give constructive notice of an unrecorded instrument. **A twelve-month or thirty-five-month lease at below-market rent is fully valid, fully invisible, and binds you after closing.**
  https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47/GS_47-18.html
- **Contracts for deed, land contracts, lease-options.** Recordable and routinely unrecorded, especially in the low-equity rural inventory this engine surfaces. The "owner" on the tax roll may have sold the beneficial interest years ago.
- **Handshake family arrangements.** "Mom deeded it to me but my brother lives there and I promised he could stay." No instrument, no consideration, no record. **The most common deal-killer on probate and heir leads and completely undetectable before contact.**
- **Verbal heir agreements and informal partitions.** Six heirs with an oral understanding and no partition action. The deed shows six tenants in common and tells you nothing about who controls the decision.
- **Life estates and occupancy promises made orally.** Sometimes reserved in a deed and findable; often not.
- **Private loan modifications, forbearance plans, and partial claims.** A modification that re-amortizes a note, or a partial claim, can change payoff by tens of thousands. Some partial claims record as a second lien; most modifications never record. **Your recorded-principal proxy is wrong by an unknown amount in an unknown direction.**
- **Oral or unrecorded easements, boundary agreements, and prescriptive claims.** The neighbor has used the driveway for nineteen years and nothing is on the plat.
- **Unfiled mechanic's lien rights.** In NC the lien-agent designation is a partial signal, but an unpaid contractor with time left to file appears on no list.

### 5.2.2 Facts about the physical asset

- **Actual interior condition.** No public source. Assessor condition codes are stale, clerical, and mass-appraisal derived. A vision model on street-level imagery reads the roofline and the yard and nothing else.
- **Deferred maintenance in dollars.** Roof age, HVAC age, foundation, septic function, mold, knob-and-tube wiring, polybutylene plumbing, sagging joists. Permits capture only work someone pulled a permit for, which excludes most of what matters.
- **Whether the well and septic actually work.** Health department permits show the installation, not current function.
- **Contents and hoarding.** A material rehab line item, invisible.
- **Whether it has been rented and to whom.** No registry in either state.

### 5.2.3 Facts about the person

- **Owner intent and motivation.** Whether they want to sell, whether they *would* sell at a number, what number, and by when. **This determines the entire economics of the business and it exists only inside a person's head until asked.**
- **Whether they already have a buyer**, or are already under contract to a wholesaler.
- **Family dynamics and who actually decides.** The signature you need may not be the name on the deed.
- **Financial pressure that has not yet hit a public record.** Job loss, medical debt, a failing business, a divorce being contemplated. Every distress signal the engine detects is distress that already reached a courthouse, which by definition means it is late and competitive.
- **Informal occupancy:** a squatter, a cousin, an ex-spouse, a tenant with no lease.
- **Whether the owner is alive and reachable.** Obituary matching is a good proxy and is built, but it is inference, not fact.

**The structural point.** Everything in 5.2.3 is knowable only through contact, and everything in 5.2.2 is knowable only through access. A perfect data engine stops at exactly the same place. **The board is a contact list, and past a certain point more enrichment does not make it a better contact list.**

## 5.3 The hypothetical perfect world, and the closest legal proxy

### 5.3.1 A live, property-level payoff and lien-balance feed

Perfect version: every parcel carries current unpaid principal, per-diem interest, escrow advances, arrears, servicer and investor, refreshed nightly. It would convert 30,000 undifferentiated leads into a list ranked by real equity. Everything else is a rounding error next to it.

**Does it exist? No, at any price.** Servicer loan tapes trade in bulk between institutions under confidentiality and federal financial-privacy law. They are not sold to acquisition buyers, and pretexting for them is a federal crime under 15 U.S.C. 6821. The registry lookup returns a servicer name and never a balance.

Closest legal proxies, stacked:

| Proxy | Source | Grade | Note |
|---|---|---|---|
| Recorded original principal plus an amortization model | Deed images, free, OCR | **B-minus** for ranking, **F** for exactness | Blind to modifications, HELOC draws, and extra principal. Overstates debt on old loans, understates on cash-out refinances. |
| **Judgment amount in a foreclosure decree** | NC judgment records, SC Master-in-Equity | **A**, as of the judgment date, for that cohort only | Exact and legally certified. Currently on 187 leads. **The priority parse target.** |
| Opening or upset bid floor | Auction and Master-in-Equity notices | **B** | Approximates debt plus costs. Currently on 723 leads. |
| Tax balance | Tax portals and rolls | **A** where it works | Exact, and it is a real lien with priority. |
| Assessed value minus modeled debt | Assessor plus deed | **C** | This is what the board mostly does now. Treat every equity number under this method as an ordering hint, not a figure. |

**Realistic ceiling: a defensible rank ordering of equity. Not a number you would wire money against.** Accept that and stop paying for products that promise otherwise.

### 5.3.2 A real-time "this owner is considering selling" signal

**Does it exist legitimately? No.** Vendors sell predictive seller scores. Those are models, not signals, built on the same public inputs you already have plus consumer marketing data of uncertain provenance, and their published accuracy claims do not survive a holdout test.

Closest legal proxies:
- **Multi-signal recency stacking.** Two or more independent distress events on the same parcel within 90 days is the strongest free intent signal that exists. Probate plus tax delinquency, or divorce plus absentee ownership, beats any single-source score.
- **Listing lifecycle events** (listed then withdrawn or expired, price cut, relisted) are the best real intent signal in existence and they live in the MLS. See 5.3.5.
- **For-sale-by-owner and for-rent-by-owner postings.** Public, self-published, high intent, small volume.
- **Absentee plus age plus long tenure.** Mailing address different from situs, owner over 70, owned twenty-plus years. Free from the tax roll. Grade **B** and it costs nothing.
- **Move detection through address processing.** See 5.3.3.

**Grade: C-plus.** Stacking gets a genuinely better call list. Nothing gets you intent.

### 5.3.3 National skip trace with consent

Identity-graph products (Accurint, TLOxp, IDI) are non-FCRA products gated by certified permissible use under federal financial-privacy and driver-privacy law. "I want to buy this person's house" maps poorly onto the standard permissible-use list, which is why these vendors underwrite accounts and why marginal accounts get shut down. **Do not paper over that with a false use certification.** That is fraud in the certification and it re-opens the pretexting and driver-privacy exposure. Anything FCRA-covered is closed outright.

Closest legal proxies, all free or near free:
- **Tax-roll owner mailing address.** The single highest-value free skip-trace field in existence. It is the owner's self-reported current mailing address, updated by the owner because they want their tax bill. Free and public in both states. Grade **A-minus**.
- **NC Secretary of State registered agent and officers** for entity-owned parcels. Built, free. Grade **A** for entity owners, which is a large slice of the board.
- **Obituaries and funeral-home notices** for heir names. Built. Grade **B-plus**.
- **NC voter file** for name and address confirmation, no date of birth. Grade **B** in NC. SC's equivalent is encumbered by 30-2-50.
- **Move detection through a licensed mail service provider.** You do not license the postal move database yourself. USPS licenses it in tiers and every licensee must hold a processing acknowledgement form per customer. **Your mail house already holds this license.** Running your list through their standard address-standardization and move-update processing is normal, cheap, and fully legal, and it returns move flags and forwarding addresses. **This is an underused legal unlock.** Grade **A-minus** for "did they move," at pennies per record.
  https://postalpro.usps.com/mailing-and-shipping-services/NCOALink

### 5.3.4 Verified occupancy

The HUD vacancy dataset is not it: tract aggregate, and access restricted to governmental and non-profit users. Close it.

Closest legal proxies:
- **Delivery-point vacancy indicator through your licensed mail service provider.** Per-address, derived from carrier reporting. Same access pattern as move updates: the mail house holds the license. Grade **A-minus. This is the correct answer to the vacancy question and it is being missed.**
- **Returned mail as a feedback loop.** You are already mailing. Undeliverable returns are ground-truth vacancy and address-quality data that you generate for free and are probably discarding. Grade **A** on the subset you have mailed, **F** on everything else.
- **Code enforcement and nuisance abatement records.** Grade **B**, high specificity, low recall.
- **Absent homestead or owner-occupancy exemption on the tax roll.** Grade **B** for non-owner-occupied, which is not the same as vacant.
- **Street-level imagery recency plus vision.** Grade **C-plus**, and the imagery is often two to four years stale in rural areas.
- **Utility disconnection: legally closed in NC.** Stop pursuing.

### 5.3.5 Full MLS access

Value: the best comp source, the best condition source (photos and remarks), and the only real intent feed (withdrawn and expired). It would raise valuation confidence more than any other single input.

Legal paths, in order of honesty:
1. **Get licensed.** An NC or SC broker license (prelicensing course, exam, fees, low four figures all in) makes you eligible for MLS participation and, separately, drops you into the G.S. 132-10 licensed-practitioner exception on county GIS commercial-use agreements. **Two structural unlocks for one cost. The highest-return legal move on this entire list.**
2. **Partner with a broker** who provides comps under their license within their MLS's rules. Cheaper, slower, person-dependent.
3. **IDX feed:** display only. IDX rules prohibit data mining and downstream use, and sold data is frequently excluded. Not a database.
4. **Scraping the consumer portals:** terms-of-service violation, and operationally they are behind commercial bot defense. Already correctly classified as a wall.

Note that the national association repealed or amended eighteen MLS policy statements effective January 1, 2026, moving non-member MLS access to **local discretion**. That means the Charlotte-area and Upstate SC MLSs each set their own non-member terms now. **Worth one phone call each; the answer may have changed.**
https://www.nar.realtor/about-nar/policies/mls-policy

**Free proxy grade without a license: C.** Recorded sale prices are the honest substitute, and NC records consideration well while SC exempt deeds state no value.

### 5.3.6 A complete lien-priority engine

It exists, it is called a title search, it is priced per property, and it is produced by humans. There is no bulk version because priority requires legal judgment about chain, indexing errors, name variants, and unrecorded superpriority, not a database join.

- An owner-and-encumbrance report (current-owner search, typically thirty years) runs roughly **$35 to $275** in NC, commonly $75 to $100.
  https://titlesearchdirect.com/north-carolina-title-search/ , https://protitleusa.com/services/products/oe_report
- Free proxy: deed grantor and grantee chains plus the judgment docket plus tax lien status. Gets a **probable** stack. Grade **B-minus** for triage, **F** for anything you would bid on.
- **Correct operating rule: never pay for title work at the lead stage. Order one report after you have a verbal, per deal.** At $75 against a deal-sized spread it is a line item, not a data problem.

### 5.3.7 The honest ranking

If you could have exactly one, take the payoff feed. If two, add MLS, because it is the only one on this list with a legal path you can walk this quarter. **The intent feed and the consented national skip trace do not exist in the form they are sold in**, and the best version of verified occupancy is sitting inside your mail vendor's existing license.

## 5.4 The consent path: what a signature unlocks

Everything below is unobtainable cold and routine once the seller signs. Deal stages: Cold (no contact), Contact (a conversation happened), LOI (verbal or written offer), Contract (executed purchase agreement), DD (due diligence), Closing.

| # | Field unlocked | Instrument the seller signs | Legal hook | Timeline | Cost | Unlocks at |
|---|---|---|---|---|---|---|
| 1 | **Exact mortgage payoff** (unpaid principal, per diem, good-through date) | Borrower's authorization to release information, plus a written payoff request | **15 U.S.C. 1639g [V]:** within seven business days of a written request from or on behalf of the borrower. **NC G.S. 45-36.7 [V]:** ten days, and **45-36.4 [V]** defines an entitled person as the borrower, the landowner, **or a person who has contracted to purchase the property.** | 7 to 10 days | NC: **one free per six-month period**, then $25. Reg X **forbids a fee** for a servicer information request. | **LOI.** Note the NC contracted-to-purchase hook lets **you** request directly once under contract. https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-36.7.html |
| 2 | **Reinstatement figure** (arrears, fees, corporate advances) | Same authorization | **12 CFR 1024.36 [V]** information request | 30 business days, plus 15 with notice | $0 | **Contract.** Essential for any reinstate-and-take-over structure. |
| 3 | **Full loan terms:** rate, maturity, escrow balance, adjustable index, assumability, due-on-sale posture | Same authorization | **12 CFR 1024.36 [V]**; owner or assignee identity in ten business days | 10 to 30 business days | $0 | **DD.** This is the field that makes or breaks a subject-to or wrap. |
| 4 | **Full personal lien and judgment picture** beyond the parcel | A distinct signed written instruction from the consumer | **15 U.S.C. 1681b(a)(2) [V].** You have no independent permissible purpose, so this is the only route. | Same day | roughly $10 to $40 | **Contract.** Do not do this earlier and never without the signature. |
| 5 | **HOA unpaid assessments, fines, violations, special assessments** | Owner's written request to the association, or a contract clause obligating the owner to obtain it | **NC G.S. 47F-3-118(b) [V]:** a statement of unpaid assessments to a lot owner or authorized agent within ten business days, **binding on the association.** | 10 business days | NC: up to $200, plus up to $100 expedite within 48 hours of closing | **Contract.** The binding effect is the whole point. An informal email from a board member is worthless. https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47F/GS_47F-3-118.html |
| 6 | **HOA books, budget, insurance, reserves, litigation** | Owner request as a member | **NC G.S. 47F-3-118(a) [V]:** records reasonably available for examination by any lot owner and the owner's authorized agents | Per bylaws | Copy cost | **DD** |
| 7 | **Condominium resale disclosure** | Owner statement to the purchaser | **NC G.S. 47C-4-109 [V]:** the unit owner shall furnish a prospective purchaser, before conveyance, a statement of the monthly common expense assessment and other fees | Before conveyance | Nominal | **Contract.** Narrower than a full resale certificate; do not assume it covers arrears. https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_47C/GS_47C-4-109.html |
| 8 | **SC HOA arrears** | **Contract clause only** | **No SC statutory estoppel found.** The SC Homeowners Association Act at 27-30-150 [V] addresses access to the budget and membership list and cross-references the nonprofit records statutes. **It does not require a statement of unpaid assessments.** | Whatever you negotiate | Whatever they charge | **Contract. This is a real gap: in South Carolina, if your purchase agreement does not require the seller to produce an association ledger, nobody has to give you one. Fix the template.** https://www.scstatehouse.gov/code/t27c030.php |
| 9 | **Certified lien priority** (owner-and-encumbrance report, then a title commitment) | No seller signature needed for the report; the commitment needs the transaction | Title insurance underwriting | 1 to 5 business days | roughly $35 to $275, commonly $75 to $100 in NC | **Contract.** Never at lead stage. |
| 10 | **Property tax payoff including deferred and rollback taxes** | Owner or agent request | Present-use-value deferred taxes, NC G.S. 105-277.4 [K]; county tax collector payoff | Same day to a few days | $0 to nominal | **DD.** Rollback on farm and forestry parcels is a five-figure surprise if missed. |
| 11 | **Utility account status, arrears, final read, consumption history** | Customer authorization to the utility | **NC G.S. 132-1.1(c) [V]** makes it non-public, so only the customer can release it | Days | $0 | **DD.** Also the only lawful route to consumption data as an occupancy proof. |
| 12 | **Insurance loss history** | Owner requests their own report and shares it | FCRA consumer-access right | Days | Free once per year to the consumer | **DD.** Prior water, fire or roof claims are the cheapest condition intelligence in the deal. |
| 13 | **Interior condition, contents, systems** | Access agreement or inspection contingency | Contract | Immediate | Inspection cost | **Contract. No dataset substitutes. Ever.** |
| 14 | **Actual lease terms, rent, deposits, occupancy** | **Tenant estoppel certificates**, required by your purchase agreement | Contract, not statute | Days | $0 | **DD.** The only mechanism that surfaces the unrecorded short leases from 5.2.1. |
| 15 | **Bank statements, proof of arrears, hardship documentation** | Seller provides voluntarily | **Never request it from the institution: 15 U.S.C. 6821 [V].** | Immediate | $0 | **DD.** Seller-provided only, always. |
| 16 | **Judgment payoff and satisfaction figures** | Debtor authorization to the creditor or creditor's counsel | Creditor payoff letter | Days to weeks | $0 to nominal | **Contract** |
| 17 | **Authority to sell in an estate** (letters testamentary, heirship) | The filing is public; **agreement of all heirs is private** | Probate file is public | Varies | Filing costs | **Contact.** The public file gives you the names; only conversation gives you the consent. |
| 18 | **Capacity and competency questions** | HIPAA authorization or a guardianship order | 45 CFR 164.502 [K] | Slow | Legal cost | **DD.** Rare, and if you need it you probably need counsel more. |

**The blunt conclusion on the consent path: every single row unlocks at Contact or later. Not one is available at the ranking stage.** Which means the payoff-data problem is not solvable by buying data, and money aimed at closing the equity gap is aimed at the wrong target. The correct sequence is: rank on free proxies, make contact, let the signature open the vault. The board's job is to decide **who to call**, not **what to pay.** It is already good enough for the first job and it will never be good enough for the second.

---

# SECTION 6: THE HONEST NUMBER

## 6.1 Field-level obtainability

Of the 112 fields in Section 4:

| Tier | Fields | Share | Cumulative | Cost |
|---|---:|---:|---:|---|
| FREE-AUTOMATED at footprint scale today, or with known code fixes | 43 | **38%** | 38% | $0 |
| plus FREE-MANUAL (operator pulls, saved pages, per-parcel cards, records requests) | 25 | **22%** | **60%** | $0 cash, 5 to 40 minutes of human time per lead |
| plus PAID (a vendor sells it lawfully) | 20 | **18%** | **78%** | $100 to $400 per month in tools, plus $0.07 to $0.25 per skip-trace hit |
| REQUIRES-CONSENT or REQUIRES-PHYSICAL-VISIT | 10 | **9%** | 87% | Gated on contact succeeding, not on data acquisition |
| PHYSICALLY-UNRECORDED or LEGALLY-SEALED | 14 | **13%** | 100% | **Unobtainable at any price, by anyone** |

**Read that as: 60 percent of the field list is free if you are willing to do manual work, 78 percent if you also pay, and 22 percent is permanently out of reach.**

## 6.2 The correction that makes those numbers honest

**Those are field-coverage percentages, not lead-coverage percentages.** A field being FREE-AUTOMATED does not mean it is filled on every lead. Current board evidence:

| Field | Classification | Actual fill on the board |
|---|---|---|
| Owner name | FREE-AUTOMATED | 89.9% |
| Situs address | FREE-AUTOMATED | 60.9% |
| Tax delinquency amount | FREE-AUTOMATED | 39.2% |
| After-repair value | FREE-AUTOMATED (derived) | 79% |
| Opening bid | FREE-AUTOMATED | 723 leads |
| Judgment amount | FREE-AUTOMATED (partial) | 187 leads |
| Lis pendens | FREE-AUTOMATED | 1,178 leads |
| Divorce | FREE-AUTOMATED (NC, config change) | 1 lead |
| Upset bid | should be FREE-AUTOMATED | 0 leads |
| **Recorded loan principal** | FREE-AUTOMATED in Spartanburg-class counties | **0.0%** |

Multiply field obtainability by per-lead fill rate and the true "everything, on every lead" number today is roughly **35 to 45 percent**, not 60. The gap between 38 percent field coverage and the actual board is entirely execution, not availability: the loan-principal enricher is built and dormant, the divorce filter was never widened, the upset lane has four dead URLs, and six free federal enrichers are not called at all.

## 6.3 What each incremental tier actually buys

| Move | Field coverage after | Board fill after (estimate) | Cost |
|---|---|---|---|
| Today, as running | 38% of fields wired, most partially filled | ~35 to 45% effective | $0 |
| **Turn on what is already built** (Section 7 Tier 0) | Same 38% of fields, far higher fill | ~50 to 55% effective | $0, a few days of work |
| **Add the free feeds that exist and are unbuilt** (Tier 1 and 2) | ~44% of fields wired | ~60% effective | $0, two to three weeks of work |
| **Add free-manual with an operator** | 60% of fields | Depends entirely on operator hours; realistically applied to the top few hundred leads, not 30,000 | Human time |
| **Add paid tools** (about $200 to $400/mo plus per-hit skip trace) | 78% of fields | ~70% effective on the fields that matter for ranking | $200 to $400/mo plus variable |
| **Add a broker license** | Unlocks MLS eligibility plus the NC GIS licensed-practitioner exception | Materially better comps, condition, and the only true intent signal | Low four figures once, plus MLS dues |

## 6.4 What "100 percent" would actually require

To reach genuine one hundred percent you would need, in order of impossibility:

1. **A statutory change or a servicer's voluntary cooperation** to publish current loan balances and delinquency status. No such feed exists anywhere in the country and federal financial-privacy law criminalizes obtaining it by pretext. Not purchasable.
2. **Repeal or amendment of S.C. Code 12-24-40(13), (4), (8), (9) and 12-24-70** so that foreclosure, deed-in-lieu, divorce, family-trust and partition deeds state consideration. Until then SC recorded sale price on distressed transfers is unavailable by statute, not by scraping failure.
3. **A physical visit to every property** for interior condition, contents, systems, and true occupancy. There is no dataset. This is the field that most determines spread and it is the one you can least obtain remotely.
4. **A signed authorization from every owner** for payoff, reinstatement, loan terms, HOA arrears, utility history, and loss history. That is Section 5.4, and it unlocks only at Contact or later, on the small subset who talk to you.
5. **Repeal of FCRA restrictions** for credit, income and employment, which will not happen and should not.
6. **A vendor that does not exist** for a structured investor buy box, live cap rates, or a genuine seller-intent signal. These are not gated by price; nobody has them.

**Therefore the honest ceiling on a fully automated, fully free basis is about 38 percent of fields at partial fill. With manual effort, roughly 60 percent of fields on the subset of leads a human can touch. With money, roughly 78 percent of fields. The remaining 22 percent is permanently, structurally out of reach, and about half of that 22 percent is the half that would tell you what to bid.**

The corollary, stated plainly: **the board is already good enough to decide who to call and will never be good enough to decide what to pay.** Investment beyond the Section 7 Tier 0 and Tier 1 items should go into contact capacity, not into more enrichment.

---

# SECTION 7: BUILD ORDER

Ranked by field-fill gained per hour of work. Effort is engineering hours for one experienced developer, excluding testing time on live county servers.

## Tier 0: already built, currently dormant. Do these first, this week.

| # | Action | Gain | Effort |
|---|---|---|---|
| 0.1 | **Run the deed-of-trust OCR enricher at scale in Spartanburg.** Raise the per-run cap above 25 and drop the hot/warm grade gate. | Recorded loan principal (C1) goes from 0.0% to something real. That is the single largest unforced gap in the whole system, and it feeds every equity calculation downstream. | **2 to 4 hours.** No new code. |
| 0.2 | **Widen the NC judgment filter to the family-divorce cause of action.** It already returns both spouses structured. | Divorce (C18) goes from 1 lead to a live statewide feed. | **1 hour**, one configuration line, carry the existing exclusion list. |
| 0.3 | **Fix the parcel-query normalization bug.** | Not a new field, but it unlocks roughly 4,054 leads that currently carry no address, which then cascades into every property field A2 through A50. | **4 to 8 hours.** |
| 0.4 | **Add the six free federal enrichers that are verified keyless and not being called at all:** FEMA flood (A17), USDA soil (A18), USGS slope (A19), EPA contamination (A31), NPS historic (A32), federal incarceration (B16). | Six fields of pure additive coverage that do not exist on the board today. All six verified live this pass. | **8 to 12 hours total**, roughly 1 to 2 hours each, all simple REST calls. |
| 0.5 | **Add 404 and 410 to the HTTP client's blocked-status set**, or add a distinct dead-URL health state. | Stops any all-404 scraper from reporting as verified-empty forever. This is the defect that hid the upset-bid failure for its entire life. | **1 hour.** |

**Tier 0 total: roughly two days of work, and it is the highest-return work available.**

## Tier 1: free feeds that exist, are open, and are unbuilt. Two weeks.

| # | Action | Gain | Effort |
|---|---|---|---|
| 1.1 | **Henderson delinquent-tax CSV.** Two HTTP calls with a tenant header. | 34 years of tax history, 1993 to 2026, 25,450 rows, 1,152 real-estate parcels, 367 with multi-year delinquency, plus return-mail vacancy flags. **Delivers more history than everything else in this document combined.** | **4 to 6 hours.** Watch the space in the blob name. |
| 1.2 | **Kania tax-foreclosure JSON.** One URL plus a nonce scraped fresh each run. | 42 in-footprint files with live current bids and close dates, covering five counties, and it makes the Cleveland county-page scrape redundant. **The only free source in existence with current bid plus close date in structured JSON.** | **4 to 6 hours.** |
| 1.3 | **Hutchens mortgage sales list.** One flat page, no paging. | 27 in-footprint rows across eight counties, and the only mortgage-lane upset data anywhere. Parse the three bid-cell states. | **6 to 8 hours**, most of it in the bid-cell text parsing. |
| 1.4 | **Buncombe unpaid-bill feature services**, resolved by item ID with a non-empty PIN filter. | 14 years of NC tax history with mailing address, situs, deed reference, values, and mortgage company. Plus the 2026 table as a six-month-early pre-delinquency watchlist. | **8 to 12 hours.** The 2021/2022 naming drift and the string-typed numerics are the traps. |
| 1.5 | **McDowell upset table** and **Gaston previous-sales archive**, two plain HTML scrapes. | The only two county-published upset tables in the footprint, both with a current bid and a stated deadline. | **3 to 4 hours each.** |
| 1.6 | **Buncombe tax-foreclosure calendar feed** with the required parameters. | 58 events from 2022 to 2026 with opening and current bid, a redeemed flag, case number and PIN. | **2 to 3 hours.** |
| 1.7 | **Retire the county-clerk upset scraper.** Replace it with 1.2, 1.3, 1.5, 1.6. Add an upset-bid listing type, or document the deadline-field alternative. Remove the sale-date-plus-ten synthesis and leave the deadline null when unpublished. | Ends a permanently-zero source and makes upset leads addressable on the board. | **4 hours**, mostly deletion. |
| 1.8 | **Fix the Gaston deed adapter**: move it from the Aumentum family to the Courthouse family at its own hostname. | Restores one of eleven NC counties' deed access, currently timing out entirely. | **2 to 3 hours.** |

**Tier 1 total: roughly two weeks. It closes the tax lane in the two counties where real history exists, and it closes the upset lane entirely.**

## Tier 2: medium effort, real payoff. Three to four weeks after Tier 1.

| # | Action | Gain | Effort |
|---|---|---|---|
| 2.1 | **South Carolina payment portal, five counties, with recursive prefix deepening.** | Multi-year tax balance history for Spartanburg (1999 to 2026), Cherokee, Union and Laurens, plus Oconee 2016 to 2025, and the sold-but-unredeemed status that no county publishes as a list. | **24 to 40 hours.** The prefix-deepening logic and the truncation detection are the whole job. Rate-limit it. |
| 2.2 | **Pickens and Oconee delinquency GIS layers**, written per year because the schema drifts. | Six annual Pickens snapshots with owner mailing addresses and amounts, three Oconee years, plus both forfeited-land layers. Pickens has no balance portal, so this is the only Pickens lane. | **12 to 16 hours.** Do not write a generic parser. |
| 2.3 | **Transylvania tax-bill search via a real browser.** | The last NC county with a year-by-year unpaid browse (2017 to 2026) that is reachable and unbuilt. Highest-value remaining NC tax target after Henderson. | **8 to 12 hours**, browser session handling. |
| 2.4 | **Greenville SC probate search.** Plain last-name GET, thousands of rows on a test query. | Net-new probate lane in the largest Upstate county, with personal representative names. | **6 to 10 hours.** |
| 2.5 | **County jail booking rosters** on the three identified vendor platforms. | Date of birth (B12), which the NC voter file legally cannot supply. **Must include a purge path for SC expungements under 17-1-60, or the lane is a statutory violation.** | **12 to 20 hours** including the purge mechanism. |
| 2.6 | **Bankruptcy search fixes:** add the NC Middle Bankruptcy court, switch to the keyless search endpoint, read the party array and schedules, and query for motions to sell real property. | Surfaces trustee 363 sales, which is a distinct acquisition channel, not just a distress flag. | **6 to 8 hours.** |
| 2.7 | **Grantee-frequency buyer intelligence** off the deed index you already touch. | The best free buyer-side data play available (D9), and it is currently unused. | **8 to 12 hours.** |
| 2.8 | **Annual PDF parsers for McDowell, Lincoln and Buncombe advertisements**, on a yearly schedule, with archival on publication. | Current-year tax delinquency for three counties, and it starts building the history that does not otherwise exist. | **8 to 12 hours** for all three. |
| 2.9 | **Snapshot scheduler for the destructive sources:** Anderson's seasonal listing window, the Oconee sheet and FLC maps before they go dark, the Spartanburg FLC PDFs (which are republished at the same document IDs), each new Pickens annual layer. | Prevents permanent, irrecoverable data loss. Oconee 2019 through 2022 is already gone this way. | **6 to 10 hours** plus a calendar. |

## Tier 3: operational and legal, not engineering. Start these in parallel today.

| # | Action | Gain | Cost |
|---|---|---|---|
| 3.1 | **Get a written opinion from an SC real estate attorney on 30-2-50.** | The SC half of the board is built entirely from SC public records and the statute on its face prohibits commercial solicitation using them. Cheapest, highest-stakes open question in the business. | A few hundred dollars |
| 3.2 | **Call your mail house and ask for move-update flags and delivery-point vacancy indicators on the existing list.** They already hold the license. | Solves the "did they move" question and the occupancy question (A39) legally, at pennies per record, this month. Both are currently classified as paid or proxy-only. | Pennies per record |
| 3.3 | **Start capturing returned mail as structured data.** | Free ground-truth vacancy and address quality on every lead you have already mailed. You are generating this now and discarding it. | $0 |
| 3.4 | **Price an NC broker license, and call the Charlotte-area and Upstate SC MLSs first.** | Simultaneously unlocks MLS eligibility (comps, condition, intent) and the G.S. 132-10 licensed-practitioner exception on county GIS commercial-use agreements. The January 2026 policy shift moved non-member access to local discretion, so the answer may already have changed. | Low four figures, plus dues |
| 3.5 | **Add an association-ledger production clause to the SC purchase agreement template.** | SC has no statutory HOA estoppel. Without the clause, nobody has to give you an arrears figure. This is a contract-drafting fix, not a data fix. | One hour with counsel |
| 3.6 | **Set the operating rule: order one owner-and-encumbrance report per deal, after a verbal, never at lead stage.** | $75 to $100 against a deal-sized spread converts an F-grade lien picture into a certified one, at the only moment it matters. | $75 to $100 per deal |

## Do not build

| Target | Reason |
|---|---|
| NC eCourts foreclosure dashboard | AWS bot wall returning a CAPTCHA action header. Do not add a human-solve step. |
| Zacchaeus listings | Blazor Server over a WebSocket circuit. No JSON endpoint exists. A browser session is the only route and it is low value relative to Kania and Hutchens. |
| Brock and Scott for upset purposes | Zero upset data, opening bid only, many zeros. Keep it in mind later as a sale-notice source only. |
| Burke, Cleveland, Rutherford and Polk per-parcel tax search | reCAPTCHA. Compliance stop. Get their delinquency from the newspaper advertisement and the foreclosure counsel feed. |
| The three Logan-hosted NC deed sites | All three returning identical server errors. One vendor incident, not our bug. Wait or call the vendor. |
| Anderson SC deed and tax | Registration wall and an agreement gate. Neither should be worked around. Anderson's free lane is the seasonal public listing plus the third-party auction pages. |
| HUD vacancy dataset | Tract-level aggregate, restricted to government and non-profit users. Ineligible and useless at parcel level. |
| NC utility consumption or shutoff data | Legally closed under G.S. 132-1.1(c). Do not scrape it and do not file a request. |
| Consumer real estate portals for listing history | Terms of service plus commercial bot defense. The legal route is a license. |
| Any product promising a live payoff balance or a seller-intent score | Neither exists. Both are models sold as signals. |

---

## SUMMARY IN ONE PARAGRAPH

Upset bids are a solved problem you have not built: two firm-level feeds, Kania and Hutchens, cover ten of eleven NC counties with live bids and real deadlines, while your current scraper has four dead URLs, a listing type that cannot exist, and deadline math that contradicts the statute. Deed records give you ownership, chain, and original loan amounts, but in North Carolina half the lien picture lives at the Clerk of Superior Court and in South Carolina the statute exempts your entire foreclosure and divorce comp set from stating a price. Tax delinquency is your strongest lane and it has exactly two counties with real multi-year history, Henderson at 34 years in one CSV and Buncombe at 14 years across nightly feature services, plus five South Carolina counties whose payment portal quietly holds history back to 1999 if you know to ask for all years and know that the name search truncates silently. Of 112 fields, 38 percent are free and automatable, 60 percent are free with manual work, 78 percent with money, and 22 percent cannot be had by anyone at any price, including the two that matter most: what is actually owed today, and what the inside of the house looks like. The realistic effective coverage on the board today is 35 to 45 percent, and the gap between that and the 38 percent free-automated ceiling is execution, not availability. Two days of work on what is already built moves the number more than anything you could buy.