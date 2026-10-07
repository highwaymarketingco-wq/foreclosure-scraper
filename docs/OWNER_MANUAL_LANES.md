# What you can do by hand: every walled source, and exactly how

Owner's manual. Built 2026-10-07. Plain words. This lists every source we meet that has a CAPTCHA, a login, a paywall, a bot check, or terms that restrict robots, and for each one: where to start, the clicks, what to pull, how to save it, where to put the file so the engine loads it, how long it takes, what you gain, and who else could do it.

**The rule we keep:** our code never gets past a CAPTCHA, a login, a paywall or a bot check, and never logs in with anyone's password. You do these steps yourself in a normal browser. Our tools only read the files you save.

## Contents

- [How to read this](#how-to-read-this)
- [Before anything else](#before-anything-else)
- [What I need from you, in order](#what-i-need-from-you-in-order)
- [How saving and loading works](#how-saving-and-loading-works)
- [Nationwide](#nationwide)
- [Statewide sources: North Carolina](#statewide-sources-north-carolina)
- [Statewide sources: South Carolina](#statewide-sources-south-carolina)
- [Per county (walled items with a how-to card)](#per-county-walled-items-with-a-how-to-card)
- [Per city](#per-city)
- [The UNKNOWN-county rows](#the-unknown-county-rows)
- [Every county at a glance (145 counties)](#every-county-at-a-glance-145-counties)
- [Paid or attorney-only (type B): prices](#paid-or-attorney-only-type-b-prices)
- [Appendix C: terms-only restrictions (allowed, built or buildable)](#appendix-c-terms-only-restrictions-allowed-built-or-buildable)
- [Data that does not exist anywhere](#data-that-does-not-exist-anywhere)
- [Stop doing these (already automatic or useless)](#stop-doing-these-already-automatic-or-useless)
- [Gaps and disagreements in our notes](#gaps-and-disagreements-in-our-notes)
- [Where this came from](#where-this-came-from)

## How to read this

Every walled source is one of three kinds:

- **A: a person can pass it in a browser.** A CAPTCHA (click pictures or tick 'I'm not a robot'), a Cloudflare or similar bot check ('Just a moment...', 'Verify you are human'), a guest sign-in button, or a free account you make yourself.
- **B: paid or attorney-only.** A per-page fee, a subscription, a license (MLS), or an agency-only sign-in.
- **C: terms only.** No technical barrier, just terms of use or a robots.txt line. The owner's attorney has cleared these, so they are **not walls**. They are listed at the end as allowed, built or buildable.

**Counts in this document:** 28 how-to cards of type A, 4 of type B, 1 of type C (the SC court fallback); plus 21 paid items in the price table and 16 terms-only items in appendix C. In the county matrix (145 counties x deeds, probate, tax) there are 161 county-system cells that need a person (CAPTCHA, bot check or login) and 3 that need payment; the county table lists them all.

**How the ranking works.** Your coverage sheet (`county_signal_coverage_FINAL.csv`, 73 signals x 146 counties) shows, for each county and signal, the share of rows that carry it. A cell is **thin** when it is under 1%. For each card we count the thin cells the task would fill in the counties it covers (a county with under 1,000 rows counts as a fraction), divide by your minutes per month, and sort by that. A cell counts as filled once some rows in that county get the signal; it does not mean every row.

## Before anything else

1. **Never let a tool log in for you.** Any pull from a site that needs your password (LiensNC, PACER, PropWire, ACPASS) is done by you, by hand. If a script anywhere still logs in with a stored password, it must be switched off and the password changed. (Details are in your private copy.)
2. **Settled by the attorney (2026-10-07), nothing to do:** (a) the SC Judicial Branch Public Index (Rule 610 and the administrative order against automated, repetitive queries) is cleared for our use, so SC foreclosure, partition, quiet-title, lis pendens and judgment case lists are being made automatic in all 46 counties (if that reader meets a CAPTCHA, login or bot check it stops, and those lanes stay manual); (b) SC Code 30-2-50 does not stop our SC mailings.

## What I need from you, in order

Ordered by value for your time: thin cells filled per minute (from your coverage sheet), then leads. 'Thin cells' = empty or under-1% county-signal cells on your sheet the task fills. 'Small loader first' means the engineer needs about an hour to add a loader before your saved files reach the dashboard; ask for those loaders first.

| # | Task | Minutes | How often | Thin cells | Loads? | What it brings |
|---|---|---|---|---|---|---|
| 1 | Save NC estate lists (search 26E*) for the 11 core counties ([card](#card-nc-est)) | 25 | weekly | 74 | Loads today | 50 to 100 estates a week (estimate) |
| 2 | Search the SC probate site for 15 lead surnames, save the estate pages ([card](#card-sc-probate-net)) | 20 | weekly | 62 | Small loader first | 10 to 30 estates a week (estimate) |
| 3 | Download the Spartanburg and York county PDFs (sale roster, forfeited land, tax lists) ([card](#card-spartanburg-site)) | 10 | monthly | 6 | Small loader first | Every Spartanburg foreclosure set for sale (25 to 30 a month) plus forfeited land; York delinquent and overage lists |
| 4 | Look up phones for 20 SC HOT leads on a people-search site, save a CSV ([card](#card-people-search)) | 45 | weekly | 33 | Loads today | 20 leads a week with phones |
| 5 | Save NC foreclosure lists (search 26SP*) for the 11 core counties ([card](#card-nc-sp)) | 30 | weekly | 22 | Loads today | 15 to 40 cases a week (estimate) |
| 6 | Read 10 SC property cards on qPublic, save a CSV ([card](#card-sc-qpublic)) | 20 | weekly | 59 | Small loader first | 10 parcels a week |
| 7 | Open 10 estate notices (NC and SC), copy the executor's name and address ([card](#card-nc-notice-body)) | 20 | weekly | 35 | Small loader first | 10 named executors with mailing addresses a week |
| 8 | Look up 10 SC company owners on the SC Secretary of State site ([card](#card-sc-sos)) | 20 | monthly | 14 | Small loader first | 10 company owners a month |
| 9 | Tax status for HOT leads in Polk, Cleveland, Caldwell, Ashe, Cherokee NC, Halifax, Union NC ([card](#card-nc-tax-walled)) | 15 | monthly | 21 | Small loader first | Unpaid years and amount due where no list reaches us; about 10 parcels a month |
| 10 | Make free accounts on Anderson ACPASS and the Horry portal, pull new estates ([card](#card-anderson-probate)) | 20 | monthly | 7 | Small loader first | A few estates a month in two counties with no probate signal today |
| 11 | Fix 20 bankruptcy rows with no county (free CourtListener first, then PACER page 1) ([card](#card-pacer)) | 60 | twice a month | n/a | Small loader first | 40 rows fixed a month |
| 12 | Send the monthly records requests (judgment amounts, SC evictions) ([card](#card-foia)) | 15 | monthly | not in sheet | No loader yet | Judgment dollar amounts and SC evictions, which are not online anywhere. |
| 13 | Check the Morganton and Union SC city sites once for code-enforcement lists ([card](#card-morganton)) | 20 | once | 4 | Small loader first | Either the first code-enforcement list in Burke and Union SC, or a closed question |
| 14 | Check 5 NC HOT leads' court cases with the lead checker ([card](#card-nc-verify)) | 30 | weekly | n/a | Loads today | 5 leads a week checked |
| 15 | Deed and loan check for 5 HOT leads in counties whose deed search needs a person (Gaston, Rutherford, Wake, Durham, Beaufort SC and others) ([card](#card-gaston-rod)) | 25 | weekly | 0 | CRM notes | Equity and title checked before you offer: open loans without a satisfaction, a clean chain |

Weekly items add up to about 215 minutes a week. Do them in order; stop when your time runs out.

## How saving and loading works

There is one ready-made lane, for court result lists:

1. Save the results page with **Cmd + S**, Format **Web Page, HTML Only**.
2. Name it `<county>_nc_<what>_<date>.html` for NC (the `_nc_` part is required; the loader reads the county from the text before it) or `<county>_sc_<what>_<date>.html` for SC.
3. Put it in the Desktop folder **Court Pages (drop here)**.
4. Double-click **Ingest Saved Court Pages** on the Desktop. It loads NC eCourts and SC Public Index lists, matches owner names to parcels, never makes duplicates, refuses to run while the weekly engine run is writing, and then moves the files into a dated 'Ingested' subfolder.

Watch out: that app moves **every** .html, .htm and .csv file out of the drop folder, whether or not it could read it. So save anything that is not a court list (contact sheets, probate pages, LiensNC pages, PDFs) into **~/Downloads** instead and tell Claude what you saved.

Other lanes that exist but run from the terminal (ask Claude):

- **Contact sheets** (phones and emails from people-search sites, PropWire exports): a CSV with columns such as parcel_id, property_address, owner_name, phone1, phone2, email. Matched by parcel number, else property address. Every phone is flagged for a Do Not Call scrub.
- **Lead checker** for one NC court case: Claude starts it, you pass the CAPTCHA and save the case page, Claude reads it.
- **LiensNC loader** for saved LiensNC result pages or CSV files.

Everything else (saved probate pages, notice pages, property-card sheets, county PDFs, bankruptcy address sheets, records-request replies) has **no loader yet**. Each card says what small loader would be needed; most are about an hour of engineering because the reader for the live page already exists.

## Nationwide

<a id="card-people-search"></a>

### Phone numbers for HOT leads from people-search sites (TruePeopleSearch, FastPeopleSearch and similar)

- **Place:** Nationwide people-search sites (most useful for SC, where we have no free phone source)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare checks (and some CAPTCHAs) stop scripts. Their terms bar automated use; the attorney has cleared the terms question for hand lookups. Full numbers on some sites are behind a paywall.
- **Start here:** https://www.truepeoplesearch.com/
- **What it is, and what we lose without it:** SC has no free phone source: the SC voter list is paid, purpose-limited and has no phone column. In NC our free voter-file match only finds owners who live in the house. A person can look up a few top leads by hand.

**Step by step**

1. Open `https://www.truepeoplesearch.com/` (or `https://www.fastpeoplesearch.com/`) in Chrome. Pass the Cloudflare check if shown.
2. Search the owner's full name and the city and state of the **mailing** address on the lead (not the property, if the owner is absentee).
3. Open the result whose current or past address matches the mailing address or the property. Check the age if the lead has one.
4. Copy up to three phone numbers (wireless first) and any email address.
5. Add a row to a sheet with columns: **parcel_id, property_address, owner_name, phone1, phone2, phone3, email**. Save as `contacts_people_search_<date>.csv` in ~/Downloads.
6. Ask Claude to load it. Every number is marked 'needs Do Not Call scrub' and must be checked against the national Do Not Call list before anyone calls or texts.

- **What to pull:** SC HOT and WARM leads first, then NC absentee owners. Phone numbers, email, the matched address. 20 leads per sitting. Never guess between two people with the same name: skip the lead.
- **How to save it:** CSV into ~/Downloads (not the court drop folder).
- **How it gets loaded:** Existing, terminal step by Claude: the contact loader matches each row by parcel number (best) or property address and attaches the phones with the Do Not Call flag. For the engineer: scripts/ingest_contacts.py, src/foreclosure_scraper/contact_ingest.py.
- **Time:** About 2 to 3 minutes per lead. **How often:** Weekly.
- **What we gain:** Callable SC leads. Your sheet shows phone at zero in 36 of 46 SC counties and email at zero in 39.
- **Reaches the dashboard?** Loads today
- **Thin cells on your sheet this fills:** 33 (in 20 counties; value score 33.0 for about 170 minutes a month)
- **Who else could do it:** Paid skip tracing on a CSV upload: Tracerfy about $0.02 a record, DataZapp $0.02 to $0.03 ($125 minimum), BatchData $0.07 to $0.18, REISkip $0.15 to $0.22 per hit. A full-board run of 30,000 leads was estimated at $600 to $900. Prices from our 2026-07 notes; confirm before buying. Calls and texts need TCPA and Do Not Call compliance either way.

<a id="card-unclaimed"></a>

### Unclaimed property searches (money held for a decedent or an owner)

- **Place:** NC, SC and the national search (missingmoney.com)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare Turnstile 'Verify you are human' box on every search (all three sites run the same vendor's software).
- **Start here:** https://unclaimed.nccash.gov/
- **What it is, and what we lose without it:** Money the state holds for a person can be an opening line with heirs. Low value for finding leads; it does not add property signals.

**Step by step**

1. Open `https://unclaimed.nccash.gov/` (NC), `https://southcarolina.findyourunclaimedproperty.com/` (SC) or `https://www.missingmoney.com/`.
2. Type the decedent's last name (first name optional). Tick 'Verify you are human'.
3. Note any match with the same name and a matching city: holder, amount range, property type.

- **What to pull:** Decedent names on top estate leads only.
- **How to save it:** Type into the CRM.
- **How it gets loaded:** None (not needed).
- **Time:** About 1 minute per name. **How often:** Only when working a specific estate.
- **What we gain:** A conversation opener with heirs. No sheet cells.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Who else could do it:** None.

<a id="card-propwire"></a>

### PropWire export from your own free account

- **Place:** Nationwide (PropWire)
- **Kind:** A: a person can pass it in a browser
- **The wall:** DataDome bot shield on every page (scripts get a 403 and a CAPTCHA), plus account login. Its skip-trace tier is paid.
- **Start here:** https://propwire.com/
- **What it is, and what we lose without it:** PropWire lists pre-foreclosures and owner data and lets a logged-in user export a CSV. Our loader attaches what it can to leads we already have (by parcel or address). It does not create new leads.

**Step by step**

1. Log in at `https://propwire.com/` with your own account.
2. Search a core county. Filter to pre-foreclosure / foreclosure (and absentee owner if offered).
3. Use **Export** to CSV (data tier only; do not buy the skip-trace tier unless you decide to).
4. Save as `propwire_<county>_<date>.csv` in ~/Downloads and ask Claude to load it as a PropWire export.

- **What to pull:** Parcel number, property address, owner name, owner mailing address, and phone or email only if your plan includes them.
- **How to save it:** CSV into ~/Downloads.
- **How it gets loaded:** Existing (contact loader, same as the people-search CSV). It only attaches to leads already on the dashboard.
- **Time:** About 10 minutes a month. **How often:** Monthly.
- **What we gain:** Mailing addresses and, if paid, phones on leads we already have. Low new value without the paid tier.
- **Reaches the dashboard?** Loads today
- **Who else could do it:** PropStream ($99 to $699 a month; Pro $199), PropertyRadar ($99 to $119 a month solo). Prices from our 2026-07 notes.

<a id="card-mls"></a>

### MLS data: closed sale prices, expired and withdrawn listings

- **Place:** NC and SC multiple listing services (Canopy, Upstate SC boards)
- **Kind:** B: paid or attorney-only
- **The wall:** License wall. Only a licensed agent or broker who belongs to the board can get MLS data. Feed access (CoreLogic Trestle) runs about $100 to $250 a month plus per-MLS license fees; a broker feed about $30 a month (2026-07 notes, unverified).
- **Start here:** (no public page: only through a licensed agent)
- **What it is, and what we lose without it:** The best comparable sales, and the expired or withdrawn listings that signal a seller who tried and failed. Not published anywhere else.

**Step by step**

1. There is no way to do this yourself without a license.
2. Ask a licensed agent you work with to run, monthly, for your core counties: closed sales in the last 6 months near your HOT leads, and expired or withdrawn residential listings in the last 90 days.
3. Ask for the export as CSV with address, parcel number if available, list price, sale price, sale date, square feet, beds and baths.
4. Save as `mls_<county>_<date>.csv` in ~/Downloads and ask Claude what can be loaded (no loader exists yet).

- **What to pull:** Closed sales near HOT leads; expired and withdrawn listings.
- **How to save it:** CSV into ~/Downloads.
- **How it gets loaded:** None. A comps loader would be needed.
- **Time:** Your time: a monthly email to the agent. **How often:** Monthly, if you have an agent partner.
- **What we gain:** Tighter comparable sales. Your sheet shows 'comps' at zero in 84 NC and 36 SC counties.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 5.
- **Who else could do it:** A licensed agent partner; PropStream or ATTOM for closed sales (see the paid table).

<a id="card-pacer"></a>

### PACER bankruptcy petitions: fix the bankruptcy rows that have no county

- **Place:** Nationwide (federal bankruptcy courts for Western, Middle and Eastern NC and for SC)
- **Kind:** B: paid or attorney-only
- **The wall:** PACER needs your own free PACER account and charges $0.10 a page, capped at $3.00 per document. Fees are waived if you stay under $30 a quarter (from 1 Jan 2027: $0.12 a page and a $40 waiver). CourtListener's RECAP archive is free and has many of the same documents.
- **Start here:** https://pacer.uscourts.gov/
- **What it is, and what we lose without it:** Bankruptcy rows come from the free CourtListener feed with the debtor's name and case number but often no address. Your coverage sheet counts about 5,000 such rows under 'UNKNOWN' county (about 3,060 in NC and 1,950 in SC); today's dashboard file shows 737. Page 1 of the bankruptcy petition lists the debtor's street address and county.

**Step by step**

1. First ask Claude to pull every petition that is already free in CourtListener's RECAP archive. That needs no person and no money, and may fix many rows at once.
2. For the rest: go to `https://www.courtlistener.com/`, search the case number, open the docket. If document 1 (the Voluntary Petition) shows 'Download PDF' (free), open it.
3. If it shows 'Buy on PACER': log in to PACER with your own account, open the case in that court (Western District of NC: `https://ecf.ncwb.uscourts.gov`; Middle NC: `https://ecf.ncmb.uscourts.gov`; Eastern NC: `https://ecf.nceb.uscourts.gov`; SC: `https://ecf.scb.uscourts.gov`), and view document 1, page 1 only (10 cents).
4. On page 1, Part 1, item 5 ('Where you live'), copy the street address, city, county, state and ZIP.
5. Add a row to a sheet with columns: **case_number, court, street, city, county, state, zip**. Save it as `bankruptcy_addresses_<date>.csv` in ~/Downloads and ask Claude to load it.

- **What to pull:** Page 1 of the petition only. Address, city, county, ZIP. Chapter 13 cases first (people trying to keep a house), then Chapter 7. 20 cases per sitting.
- **How to save it:** One CSV per sitting, columns above, into ~/Downloads.
- **How it gets loaded:** None yet. A small loader is needed (match on case number, write address and county). About an hour for the engineer, and the free RECAP pull should be done first.
- **Time:** About 3 minutes per case. 20 cases is an hour and about $2 to $6, which stays inside the free quarterly waiver. **How often:** Twice a month until the backlog is small.
- **What we gain:** Turns UNKNOWN-county bankruptcy rows into mailable, county-sorted leads and lets the bankruptcy-stay check match them to foreclosures.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Who else could do it:** CourtListener (free; RECAP has many petitions). The attorney's PACER account (same price). Paid court-data services (price not on file).

## Statewide sources: North Carolina

NC court case numbers end with a county code. Codes for the core counties: Buncombe -100, Henderson -440, Cleveland -220, Gaston -350, Rutherford -800, Polk -740, Transylvania -870, McDowell -580, Lincoln -540, Mitchell -600, Burke -110. Check one result against the Location column the first time.

<a id="card-nc-est"></a>

### NC estate files (probate) on the NC eCourts portal

- **Place:** North Carolina, every county (start with the 11 core counties)
- **Kind:** A: a person can pass it in a browser
- **The wall:** The same picture CAPTCHA as above.
- **Start here:** https://portal-nc.tylertech.cloud/Portal/
- **What it is, and what we lose without it:** Every NC estate is opened with the Clerk of Superior Court and indexed on eCourts (case numbers like 26E000123-100). Newspaper notices to creditors reach us for many estates, but only after the executor publishes, and only the ones that publish where we read. The estate index shows the decedent and the date the estate opened, weeks earlier.

**Step by step**

1. Open Chrome (a normal window) and go to `https://portal-nc.tylertech.cloud/Portal/`. Use that exact address; the bare site name shows an error page. Do not sign in. The public search needs no account.
2. Click **Smart Search**.
3. In the search box type **26E*** (all 2026 estate files).
4. Click **Advanced Filtering Options**. Set **Location** to the county and the **File Date** range (first time: last 6 months; after that: since your last pull). If a **Case Category** or **Case Type** filter is offered, pick **Estate**.
5. Click **Submit**. A box that says **"Let's confirm you are human"** with a grid of pictures may appear. Click the pictures it asks for, then press **Confirm**. It can ask two or three times in a row; that is normal. Do not use any add-on or service that solves it for you.
6. At the bottom of the results, set **items per page** to the largest number offered (200). If the list looks short (about 23 rows), the site is sampling: narrow the dates and search again.
7. Press **Cmd + S**. Set **Format** to **Web Page, HTML Only** (not Complete, not PDF).
8. Name the file `<county>_nc_estates_<date>.html`, for example `henderson_nc_estates_2026-10-07.html`. Save it into **Court Pages (drop here)** on the Desktop.
9. Repeat per county, then double-click **Ingest Saved Court Pages**.

- **What to pull:** All estate rows (decedent estates). Skip guardianship, incompetency, minor and other rows that describe a living person's health or capacity; they are not property leads and should not be saved. Columns: case number, case name (the decedent), file date, location, status. Same county plan as the foreclosure search: core 11 weekly, next 14 monthly.
- **How to save it:** Web Page, HTML Only, filename with **_nc_**, into **Court Pages (drop here)**, then the Desktop app.
- **How it gets loaded:** Existing (same app and reader as the foreclosure search). The reader recognizes estate captions ('Estate of ...', 'In re ...') and scores these rows as estate leads. First time you do this, ask Claude to check that the decedent names came through correctly.
- **Time:** About 2 minutes per county: 25 minutes for the core 11. **How often:** Weekly (core 11); monthly (next 14).
- **What we gain:** The decedent's name and the estate's opening date, weeks before any newspaper notice. Your sheet shows estate and probate signals at zero or under 1% in most NC counties. Our estimate (not measured): 50 to 100 new estates a week across the core 11; many will not own land.
- **Reaches the dashboard?** Loads today
- **Thin cells on your sheet this fills:** 74 (in 22 counties; value score 72.5 for about 130 minutes a month)
- **Who else could do it:** The Clerk's Estates Division (public terminal or a phone call, free). The attorney's research subscription if it covers NC estate dockets (price not on file). Paid court-data vendors (UniCourt, Trellis; price not on file).

<a id="card-nc-notice-body"></a>

### Full text of NC estate and foreclosure notices on ncnotices.com

- **Place:** North Carolina, newspaper legal notices (statewide site)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Each notice's full text sits behind an 'I Agree, View Notice' button plus a Google checkbox CAPTCHA ('I'm not a robot').
- **Start here:** https://www.ncnotices.com/
- **What it is, and what we lose without it:** We already read the notice list (name, county, date). The full text holds the executor's name and mailing address, the attorney, and sometimes the date of death. That is the best free contact path for an estate.

**Step by step**

1. Open `https://www.ncnotices.com/` in Chrome.
2. Search the decedent's name from the lead (or browse 'Notice to Creditors' for the county).
3. Click the notice. Tick the box **I'm not a robot**, pass any picture check, and click **I Agree, View Notice**.
4. Copy the executor (personal representative) name and mailing address, the attorney's name, and the date of death if shown.
5. Paste them into the lead's notes in your CRM. If you prefer, save the notice page (Cmd + S, HTML Only) into ~/Downloads as `<parcel>_notice.html`, but no reader picks these up yet.

- **What to pull:** For estate leads you will actually mail or call: executor name, executor mailing address, attorney, date of death. 10 per sitting.
- **How to save it:** Type into the CRM. Saved pages are not loaded by anything yet.
- **How it gets loaded:** None. A small reader would be needed: the notice-body reader we already have for the ungated notices could read a saved page. About an hour for the engineer.
- **Time:** About 2 minutes per notice. **How often:** Weekly, top estate leads only.
- **What we gain:** A named, mailable executor for the estate (the person who can sign). Your sheet shows 'heir naming publication' at zero in every NC county.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 25 (in 25 counties; value score 23.7 for about 85 minutes a month)
- **Who else could do it:** The executor's attorney is named in the notice; the attorney's office is a legitimate contact route.

<a id="card-nc-sp"></a>

### NC court foreclosure cases (special proceedings) on the NC eCourts portal

- **Place:** North Carolina, every county (start with the 11 core counties)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Picture CAPTCHA ("Let's confirm you are human") in front of every search. Scripts get an HTTP 405 'Human Verification' page.
- **Start here:** https://portal-nc.tylertech.cloud/Portal/
- **What it is, and what we lose without it:** Every power-of-sale foreclosure in NC is a court 'special proceeding' (case numbers like 26SP000500-100). The law-firm sale calendars and newspaper notices we already read cover many of them, but not all, and not the case status (hearing held, sale held, upset bid filed). Without this we miss foreclosures no law firm posts, and we cannot tell which sales are still open.

**Step by step**

1. Open Chrome (a normal window) and go to `https://portal-nc.tylertech.cloud/Portal/`. Use that exact address; the bare site name shows an error page. Do not sign in. The public search needs no account.
2. Click **Smart Search**.
3. In the search box type **26SP*** (all 2026 special proceedings). Use **25SP*** for last year if you are backfilling.
4. Click **Advanced Filtering Options**. Set **Location** to the county (for example 'Buncombe County'). Set the **File Date** range: first time, the last 6 months; after that, from your last pull to today. (Labels can differ slightly; pick the closest match.)
5. Click **Submit**. A box that says **"Let's confirm you are human"** with a grid of pictures may appear. Click the pictures it asks for, then press **Confirm**. It can ask two or three times in a row; that is normal. Do not use any add-on or service that solves it for you.
6. At the bottom of the results, set **items per page** to the largest number offered (200). If the list looks short (about 23 rows), the site is sampling: narrow the dates and search again.
7. Press **Cmd + S**. Set **Format** to **Web Page, HTML Only** (not Complete, not PDF).
8. Name the file `<county>_nc_sp_<date>.html`, for example `buncombe_nc_sp_2026-10-07.html` (two-word counties: `new_hanover_nc_sp_2026-10-07.html`). Save it into the Desktop folder **Court Pages (drop here)**.
9. Repeat for the next county. The CAPTCHA usually does not come back for a few minutes.
10. When all counties are saved, double-click **Ingest Saved Court Pages** on the Desktop. A notice tells you how many NC court records it found.

- **What to pull:** Only rows whose case type reads **Foreclosure (Special Proceeding)**. Keep the columns the grid shows: case number, case style (the parties, which names the owner), file date, location, status. One results page per county per pull. Weekly: the 11 core counties (Buncombe, Henderson, Cleveland, Gaston, Rutherford, Polk, Transylvania, McDowell, Lincoln, Mitchell, Burke). Monthly: the next 14 by lead count (Mecklenburg, Wake, Forsyth, Guilford, Catawba, New Hanover, Brunswick, Durham, Pitt, Orange, Johnston, Union, Onslow, Harnett). Check: the number after the dash in each case number is the county code (Buncombe ends in -100).
- **How to save it:** Web Page, HTML Only. Filename must contain **_nc_** (the loader reads the county from the text before it). Folder: `~/Desktop/Court Pages (drop here)/`. Then run the Desktop app **Ingest Saved Court Pages**.
- **How it gets loaded:** Existing. The app runs the saved-page reader for NC court pages, which is tested on this exact results grid (verified 2026-08-13), turns each row into a lead, and tries to match the owner name to a parcel. The app refuses to run while the weekly engine run is writing, and never makes duplicates. For the engineer: scripts/ingest_saved.sh, scripts/parse_nc_ecourts_export.py, scripts/ingest_fresh_court_leads.py.
- **Time:** About 2 to 3 minutes per county once past the CAPTCHA: 30 minutes for the 11 core counties, 35 more for the monthly 14. **How often:** Weekly (core 11); monthly (next 14).
- **What we gain:** New NC foreclosure cases the law firms do not post, with the owner's name and case number; earlier warning on cases still in the hearing stage. Our estimate (not measured): 15 to 40 new cases a week across the 11 core counties. Name-to-parcel matching runs about 30% automatically, so expect roughly a third to land on a property without your help.
- **Reaches the dashboard?** Loads today
- **Thin cells on your sheet this fills:** 22 (in 22 counties; value score 20.7 for about 160 minutes a month)
- **Who else could do it:** The Clerk of Superior Court's public terminal in each courthouse (free, in person). A title abstractor or a title company's foreclosure report (an O&E report runs about $85 to $95 per property, per our notes). The attorney's own research subscription (Westlaw or Lexis docket search, if his plan includes NC dockets; price not on file).

<a id="card-nc-liensnc"></a>

### LiensNC lien-agent filings (builders and contractors)

- **Place:** North Carolina, LiensNC (lien agent filings)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Login (your own LiensNC account) and terms that bar automated searching.
- **Start here:** https://apps.liensnc.com
- **What it is, and what we lose without it:** Contractors file a 'notice to lien agent' when a project starts. A cluster of these on one property can mean a builder in trouble. Our own check (2026-10-02) found the signal as built is wrong: 0 of 50 sampled were real distress, because a single notice is routine. The board already holds about 45,000 LiensNC rows.

**Step by step**

1. Do not pull more until the signal is redefined (cluster plus stalled project). If and when it is:
2. Log in at `https://apps.liensnc.com` with your own account. Go to **Advanced Search**.
3. Pick one county, a filing-date range of the last 90 days, newest first, maximum rows per page.
4. Look at the column **Active Related Filings?**. For a 'Yes' project, open **Related Filings Report** from the Action menu and use **Download, CSV**.
5. Save results pages (HTML Only) or the CSV into `~/Downloads` as `<county>_liensnc_<date>.html`, then ask Claude to load the LiensNC files.

- **What to pull:** Projects with 'Active Related Filings = Yes' only, per county, last 90 days.
- **How to save it:** HTML Only or CSV into ~/Downloads (not the court drop folder: the court app moves every .html and .csv out of that folder whether it read it or not).
- **How it gets loaded:** Existing but terminal-only: Claude runs the LiensNC loader on your saved files. For the engineer: scripts/ingest_liensnc.py.
- **Time:** About 15 minutes a month for the core counties. **How often:** Monthly, only after the signal is fixed.
- **What we gain:** Builder distress, once defined right. Today: low; the column is already filled in nearly every NC county.
- **Reaches the dashboard?** Loads today
- **Thin cells on your sheet this fills:** 0 (these cells are already filled in the counties it covers)
- **Who else could do it:** None needed.

<a id="card-nc-sos-liens"></a>

### NC Secretary of State: federal tax lien and UCC lien searches

- **Place:** North Carolina, Secretary of State
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare check ('Just a moment...' or a 'Verify you are human' box) that our stealth browser could not pass. The federal tax lien page also says scripted searches are not permitted and bulk access is a paid data subscription (price not on file).
- **Start here:** https://www.sosnc.gov/online_services/search/by_title/_Federal_Tax_Lien
- **What it is, and what we lose without it:** IRS liens and UCC filings against companies (LLCs, builders) that own our leads. A narrow signal: it only covers company owners.

**Step by step**

1. Open the page in Chrome. If the Cloudflare box shows, tick it.
2. Type the company name exactly as the county shows the owner (for example 'ABC HOLDINGS LLC'). Search.
3. Open each hit and note: filing date, lien amount if shown, the IRS office, and whether it is released.
4. For UCC filings use `https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code` the same way.

- **What to pull:** Company-owned HOT leads only. Filing date, amount, status (open or released). 10 names per sitting.
- **How to save it:** Type into the CRM. No reader exists.
- **How it gets loaded:** None. A two-column file (owner name, lien note) could be loaded later if this proves useful.
- **Time:** About 2 minutes per name. **How often:** Monthly, company-owned HOT leads.
- **What we gain:** Proof of tax trouble for company owners. Your sheet's 'liens' column is zero in every NC county, but this source fills only the company-owned slice.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 11.
- **Who else could do it:** The NC SoS paid data subscription for bulk (price not on file). The attorney's lien search vendor.

<a id="card-nc-verify"></a>

### Check one NC lead's court case (status, parties, heirs) with the human-assisted checker

- **Place:** North Carolina, one lead at a time
- **Kind:** A: a person can pass it in a browser
- **The wall:** The same picture CAPTCHA, plus the NC Secretary of State's bot check when the owner is a company.
- **Start here:** https://portal-nc.tylertech.cloud/Portal/
- **What it is, and what we lose without it:** For a HOT lead (lis pendens, foreclosure, divorce or estate), the one fact that decides whether to call is on the case page: is the case still open, who are the parties, are there heirs we do not know about. We have a tool that sets this up and reads the saved page.

**Step by step**

1. Tell Claude: `"verify lead <parcel number> in <county>"` (or give the case number). The tool prints which search to run and opens the eCourts page in your browser. If the owner is a company, a second tab opens on the NC Secretary of State business search.
2. On eCourts: pass the picture CAPTCHA yourself, search the case number (best) or the name it printed, and click into the matching case so the full case page shows (parties, events, hearings).
3. Press **Cmd + S**, Web Page, HTML Only, and save it as `<parcel>_case.html` in your Downloads folder.
4. If the company tab opened: search the company name, open its profile page, save it the same way as `<parcel>_sos.html`.
5. Tell Claude the file names. The tool reads them and reports confirmed, refuted or unconfirmed. For an estate, any new name on the page is checked against the free NC voter list to see if that person is alive and where they vote.

- **What to pull:** One case page per lead: the parties list, the events list (hearing, order of sale, upset bid, dismissal) and the status line. Do HOT leads only, 5 per sitting.
- **How to save it:** HTML Only, in ~/Downloads, filename with the parcel number. Do not put these in the court drop folder (they are single cases, not lists).
- **How it gets loaded:** Existing, run by Claude in the terminal: the tool queues the check, opens the page, and parses what you saved into a verdict. It does not write back to the dashboard yet; the verdict is a report. For the engineer: scripts/verify_lead_human_assisted.py, src/foreclosure_scraper/verification_human_lane.py.
- **Time:** About 5 to 6 minutes per lead. **How often:** Weekly, HOT leads only.
- **What we gain:** A checked yes or no on the lead's case, and the heirs list on estate leads. This adds no new cells to your sheet; it makes the leads you call right.
- **Reaches the dashboard?** Loads today
- **Who else could do it:** The attorney (his eCourts access is the same public search; his staff can run it). A title abstractor for heirs on a specific property.

## Statewide sources: South Carolina

<a id="card-sc-probate-net"></a>

### SC probate court estate index on southcarolinaprobate.net

- **Place:** South Carolina: Aiken, Bamberg, Barnwell, Charleston, Cherokee, Chester, Colleton, Dorchester, Florence, Georgetown, Kershaw, Lancaster, Marlboro, Oconee, Orangeburg, Sumter, York
- **Kind:** A: a person can pass it in a browser
- **The wall:** The site refuses scripts with a 403 'Forbidden' page from its load balancer (checked 2026-10-07, also with a normal browser identity). A person in a normal browser should get the search page. If you also get 403 in your own browser, the site is down; call the probate court.
- **Start here:** https://www.southcarolinaprobate.net/search/
- **What it is, and what we lose without it:** 17 SC probate courts post their estate index here. Each estate row shows the decedent, the filing date, the case status, the creditor-claim deadline and, in a sub-table, the personal representative's full name and mailing address. Our reader for this site works only when the site answers it, and today it does not.

**Step by step**

1. Open `https://www.southcarolinaprobate.net/search/` in Chrome. (Charleston also has `/charlestonprobatesearch/`.)
2. Pick the county in the **County** drop-down. Wait for the page to refresh.
3. Type a last name in the name box and press **Search**. The site searches by name only, not by date. Use the surnames of your SC obituary, estate and tax-delinquent leads in that county.
4. Click the plus sign on each matching case to open the parties list (the personal representative's name and address) and the docket list.
5. Press **Cmd + S**, Web Page, HTML Only. Name: `<county>_sc_probate_<surname>_<date>.html`.

- **What to pull:** Estate cases only (skip marriage records). Case number, decedent, filing date, status, creditor-claim date, personal representative name and mailing address. 15 surnames per sitting, biggest counties first (Charleston, Sumter, Oconee, Cherokee, Florence, Colleton).
- **How to save it:** HTML Only into ~/Downloads (not the court drop folder, which would move the files without reading them).
- **How it gets loaded:** None for saved pages yet. The live reader already parses this exact page (it is how the 373 Charleston rows on the board were built), so pointing it at saved files is a small job, about an hour. Until then, ask Claude to load them by hand. For the engineer: src/foreclosure_scraper/scrapers/counties_sc/sc_probate_net.py.
- **Time:** About 1 minute per surname search plus 1 minute per case opened. **How often:** Weekly.
- **What we gain:** SC estates with a named personal representative and a mailing address, which is the person who can sell. Your sheet shows SC probate and estate signals at zero or under 1% in about 35 to 45 of 46 SC counties.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 62 (in 17 counties; value score 43.9 for about 85 minutes a month)
- **Who else could do it:** The probate court clerk by phone (free). The attorney's probate subscription where a county sells document access (Greenville). An SC abstractor.

<a id="card-sc-sos"></a>

### SC Secretary of State business entity search (company owners)

- **Place:** South Carolina, Secretary of State
- **Kind:** A: a person can pass it in a browser
- **The wall:** Google checkbox CAPTCHA ('I'm not a robot') on every search (re-checked 2026-10-04).
- **Start here:** https://businessfilings.sc.gov/BusinessFiling/Entity/Search
- **What it is, and what we lose without it:** When an SC lead is owned by an LLC or corporation, the entity record shows whether it is in good standing or dissolved, the registered agent's name and address, and sometimes the principal office. NC company owners we already look up for free; SC we cannot.

**Step by step**

1. Open the page in Chrome.
2. Type the company name as the county shows it. Tick **I'm not a robot** and pass any picture check. Press **Search**.
3. Open the matching entity. Note: status (Good Standing, Forfeited, Dissolved), date of status, registered agent name and address.
4. Type these into the lead's notes in the CRM.

- **What to pull:** SC HOT and WARM leads whose owner name contains LLC, INC, CORP, TRUST or LP. Status, status date, registered agent name and address. 10 per sitting.
- **How to save it:** Type into the CRM. No reader exists (an older instruction to save 'sc_sos_<entity>.html' files led nowhere: nothing reads them).
- **How it gets loaded:** None. A small reader for a saved entity page, or a simple CSV (owner name, status, agent, agent address), would be needed.
- **Time:** About 2 minutes per company. **How often:** Monthly.
- **What we gain:** A contact route (the registered agent) and a distress flag (forfeited or dissolved company still holding land). Your sheet's 'SoS dissolution' column is zero in all 46 SC counties.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 14 (in 14 counties; value score 14.0 for about 30 minutes a month)
- **Who else could do it:** The SC SoS UCC lien search is a separate, paid service ($5 per search). The attorney's corporate search vendor.

<a id="card-sc-qpublic"></a>

### SC assessor property cards (heated square feet, beds, baths, sales) on qPublic

- **Place:** South Carolina, county property cards on qPublic: Allendale, Bamberg, Barnwell, Cherokee, Chester, Clarendon, Colleton, Darlington, Edgefield, Fairfield, Florence, Georgetown, Hampton, Jasper, Kershaw, Lancaster, Laurens, Lee, Marlboro, Newberry, Oconee, Orangeburg, Pickens, Spartanburg, Union, York
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare 'Verify you are human' check on searches, plus a terms page (the terms part is cleared by the attorney; the Cloudflare check is not something we pass with code).
- **Start here:** https://qpublic.schneidercorp.com/Application.aspx?App=CherokeeCountySC&Layer=Parcels&PageType=Search
- **What it is, and what we lose without it:** Free SC map layers leave heated square feet and sale price blank. The county property card on qPublic has them as plain text. Without them our value estimates for SC lean on guesses.

**Step by step**

1. Open the qPublic link for the county (replace **Cherokee** in the address with the county name, for example **App=PickensCountySC**).
2. Accept the terms box. If a Cloudflare 'Verify you are human' box shows, tick it.
3. Search by **Parcel ID** (the lead's TMS number) or by owner name.
4. On the card, find **Heated Sq Ft** (or Living Area), **Bedrooms**, **Full Baths**, **Year Built**, **Acres**, and the **Sales** table (date, price, deed book and page).
5. Type these into the CRM, or into a simple sheet with columns: parcel_id, heated_sqft, beds, baths, year_built, last_sale_date, last_sale_price.

- **What to pull:** SC HOT leads with no square footage on the dashboard. The 7 fields above. 10 parcels per sitting.
- **How to save it:** A CSV with the columns above, saved as `sc_cards_<date>.csv` in ~/Downloads, then ask Claude to load it. Saved card pages are not read by anything.
- **How it gets loaded:** None for a hand-made CSV. A small loader (parcel_id plus the 7 fields) is about an hour of work. Note for the engineer: the code that renders these cards automatically has a setting that ticks the Cloudflare box unless FORECLOSURE_NO_CF_SOLVE=1 is set, and no run script sets it. That should be checked against the owner's rule.
- **Time:** About 2 minutes per parcel. **How often:** Weekly, HOT SC leads.
- **What we gain:** Real square footage and sale history, which make the value estimate and the offer price trustworthy. Your sheet shows square feet zero in 26 SC counties and beds and baths zero in 31.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 59 (in 20 counties; value score 35.6 for about 85 minutes a month)
- **Who else could do it:** The county assessor's office (call with the TMS number). Paid property data: ATTOM (entry about $95 to $500 a month; bulk backfill $1,500 to $5,000 one time), Realie ($50 to $350 a month), PropStream Pro ($199 a month). Prices from our 2026-07 notes; confirm before buying.

<a id="card-sc-notice-body"></a>

### Full text of SC notices to creditors and foreclosure notices (scpublicnotices.com, publicnoticesc.com)

- **Place:** South Carolina, newspaper legal notices
- **Kind:** A: a person can pass it in a browser
- **The wall:** scpublicnotices.com: the notice page ('Details') shows a Cloudflare 'Verify you are human' box and a Google CAPTCHA. publicnoticesc.com: Cloudflare check on every page.
- **Start here:** https://www.scpublicnotices.com/
- **What it is, and what we lose without it:** We read the notice list and the short preview. The full notice holds the personal representative's name and address, or for a foreclosure the sale date, the property and the plaintiff.

**Step by step**

1. Open `https://www.scpublicnotices.com/` in Chrome.
2. Search the decedent's or owner's last name, or filter by county and category (Notice to Creditors, Foreclosure).
3. Click the notice. Pass the 'Verify you are human' box and the picture check if shown.
4. Copy the personal representative's name and address (estates) or sale date, address and plaintiff (foreclosures) into the CRM.
5. Same steps on `https://www.publicnoticesc.com/` for notices that only appear there.

- **What to pull:** Top SC estate and foreclosure leads only: representative name, mailing address, attorney; or sale date and address. 10 per sitting.
- **How to save it:** Type into the CRM. Nothing reads saved notice pages yet.
- **How it gets loaded:** None. Same small reader job as the NC notice bodies.
- **Time:** About 2 minutes per notice. **How often:** Weekly, top leads.
- **What we gain:** Named contacts on SC estates. Your sheet's 'heir naming publication' column is zero in 45 of 46 SC counties.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 10 (in 10 counties; value score 10.0 for about 40 minutes a month)
- **Who else could do it:** The attorney named in the notice.

<a id="card-sc-publicindex-fallback"></a>

### SC Judicial Public Index: hand-save fallback, only if the automatic reader meets a technical barrier

- **Place:** South Carolina, every county court (Common Pleas, Master in Equity)
- **Kind:** C: terms only (allowed)
- **The wall:** None today. The attorney cleared the court's Rule 610 and the administrative order against automated, repetitive queries for our use (2026-10-07), and 58 live searches in 8 counties (2026-10-04) met no CAPTCHA. The automatic lanes are being built now. This card is only for the day the reader meets a CAPTCHA, a login or a bot check: it then stops by design, and those lanes go back to hand saves.
- **Start here:** https://publicindex.sccourts.org/Anderson/PublicIndex/
- **What it is, and what we lose without it:** SC foreclosure, partition, quiet-title, lis pendens and judgment case lists in all 46 counties, which are becoming automatic. Nothing to do unless the build reports it was stopped.

**Step by step**

1. Only if Claude or the run report says the Public Index reader stopped on a CAPTCHA, login or bot check: open `https://publicindex.sccourts.org/<County>/PublicIndex/` (for example Anderson) and accept the disclaimer.
2. Leave **Last Name** blank. Set **Date Type** to **Case Filed**, the begin date to the last date the automatic lane covered, the end date to today.
3. Run each stopped lane and save each results page: **Foreclosure** (Circuit Court, Common Pleas, sub-type Foreclosure 420); **Partition** (sub-type Partition 440); **Quiet title** (the quiet-title sub-type in the Common Pleas list); **Lis Pendens** (Index Search radio, Lis Pendens); **Judgments** (Index Search radio, Judgments). Skip Possession/eviction (it names the tenant, not the owner).
4. If it says 'maximum records exceeded', shorten the date range to about 2 months.
5. If you meet a CAPTCHA, pass it yourself. Press Cmd + S, HTML Only, name `<county>_sc_<lane>_<date>.html` (for example `anderson_sc_foreclosure_2026-10-07.html`), into **Court Pages (drop here)**, then run the Desktop app.

- **What to pull:** Only the lanes and counties the automatic reader could not finish. Case number, caption, filed date, status.
- **How to save it:** HTML Only into **Court Pages (drop here)**, then **Ingest Saved Court Pages**.
- **How it gets loaded:** Existing: the app runs the SC Public Index reader automatically on any saved Public Index page. The list page has no judgment dollar column (an older bug that read the case-number year as a '$2026' judgment was fixed on 2026-09-29). For the engineer: scripts/ingest_publicindex_files.py; src/foreclosure_scraper/ingest_sc_publicindex_export.py.
- **Time:** About 3 minutes per county per lane, only when needed. **How often:** Only if the automatic lanes stop on a technical barrier.
- **What we gain:** Keeps SC court lists flowing if the automatic reader is ever blocked.
- **Reaches the dashboard?** Loads today
- **Who else could do it:** The Clerk of Court (records request). Paid court data (UniCourt, Trellis; prices not on file).

<a id="card-foia"></a>

### Records requests (FOIA)

Send the batch of written requests in docs/foia_court_records.md: NC Clerks of Superior Court (foreclosure special proceedings and civil judgments with the judgment amount), SC Clerks of Court copying the Master in Equity (foreclosures, sale rosters, judgment amounts), SC Chief Magistrates (ejectment and eviction filings, the only case-level eviction route). Ask for CSV or Excel by email. When files come back, put them in ~/Downloads and tell Claude; no automatic reader exists for them yet. This is not a wall: the data is simply not published online.

Time: 15 minutes a month, then wait 1 to 4 weeks. Kind: not a wall (the data is not online).

## Per county (walled items with a how-to card)

Cards are grouped by state and, inside each state, sorted by value for your time. Every county also appears in the county table further down, with links back to its cards.

### North Carolina counties

<a id="card-nc-tax-walled"></a>

#### NC tax lookups behind a check or a login

- **Place:** Ashe, Cherokee (NC), Halifax and Union (NC) Counties
- **Kind:** A: a person can pass it in a browser
- **The wall:** Ashe and Halifax: Cloudflare check on qPublic. Cherokee NC: tax statements behind an account login with a registration ID. Union NC: county tax pages answered 'Access Denied' to scripts.
- **Start here:** https://qpublic.schneidercorp.com/Application.aspx?App=AsheCountyNC&Layer=Parcels&PageType=Search
- **What it is, and what we lose without it:** Tax-bill status for leads in these counties.

**Step by step**

1. Open the county's tax site (county table below). Pass the check.
2. Search the parcel. Note unpaid years and amount due. For Cherokee NC, call the tax office if the site wants a registration ID you do not have.

- **What to pull:** HOT leads only.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 1 to 2 minutes per parcel. **How often:** Monthly.
- **What we gain:** Delinquency status where we have none.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 12 (in 4 counties; value score 4.5 for about 5 minutes a month)
- **Who else could do it:** County tax office by phone.

<a id="card-avalon-tax"></a>

#### Cleveland and Caldwell tax bill sites (Avalon)

- **Place:** Cleveland and Caldwell Counties, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Google CAPTCHA loaded by the tax site (the search sits behind it).
- **Start here:** https://www.clevelandcountytaxes.com/taxes.html
- **What it is, and what we lose without it:** Taxpayer and bill status per parcel. Cleveland's current deed book and page is also not in any free map layer, so it comes from the deed index or this site.

**Step by step**

1. Open `https://www.clevelandcountytaxes.com/taxes.html` (Caldwell: `https://www.caldwellcountynctax.com/taxes.html`).
2. Pass the CAPTCHA if shown. Search by owner name or parcel number.
3. Note unpaid years and amount due for each lead.

- **What to pull:** HOT and WARM leads: unpaid years, amount due, taxpayer name. 10 per sitting.
- **How to save it:** Notes in the CRM, or a CSV (parcel_id, unpaid_years, amount_due) in ~/Downloads.
- **How it gets loaded:** None.
- **Time:** About 1 minute per parcel. **How often:** Monthly.
- **What we gain:** Delinquent-tax status where the county does not publish a list we read.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 6 (in 2 counties; value score 3.8 for about 10 minutes a month)
- **Who else could do it:** County tax office by phone.

<a id="card-polk-tax"></a>

#### Polk tax bill search

- **Place:** Polk County, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare 'you have been blocked' page to scripts (2026-10-07). Our Polk tax reader has returned nothing for 5 runs in a row.
- **Start here:** https://www.polknc.gov/tax_search/
- **What it is, and what we lose without it:** Whether a Polk parcel's taxes are paid, and for which years. Note: the Polk map layer's 'tax owed' field is the yearly bill, not a delinquent balance.

**Step by step**

1. Open the address in Chrome (a normal window). If 'you have been blocked' shows in your browser too, try your phone on cellular data.
2. Search by owner name or parcel number.
3. Open the bill list. Note each unpaid year and the amount due.

- **What to pull:** HOT and WARM Polk leads: unpaid years and amount due. 10 per sitting.
- **How to save it:** Notes in the CRM, or a CSV with parcel_id, unpaid_years, amount_due in ~/Downloads (no loader yet).
- **How it gets loaded:** None.
- **Time:** About 1 minute per parcel. **How often:** Monthly.
- **What we gain:** Real delinquent-tax status for Polk leads.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 3 (in 1 counties; value score 1.3 for about 10 minutes a month)
- **Who else could do it:** Polk County tax office by phone.

<a id="card-nc-cchs-cf"></a>

#### NC deed searches hosted by Courthouse Computer Systems behind a Cloudflare check

- **Place:** Alleghany, Pasquotank, Pender, Perquimans, Person, Richmond, Rockingham, Tyrrell and Washington Counties, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare check that scripts do not pass. A person opening the same site in a normal browser normally passes it.
- **Start here:** https://alleghanync.courthousecomputersystems.com/
- **What it is, and what we lose without it:** Deed index and images for these smaller counties (Pender is the largest; about 1,000 rows or fewer each).

**Step by step**

1. Open the county's site (the county table below has each address). Wait for the check or tick the box.
2. Accept the disclaimer, search the owner's name, note instruments as above.

- **What to pull:** HOT leads only.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 4 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Deed-chain checks in counties we cannot read at all today.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 52.
- **Who else could do it:** County office; abstractor; O&E report about $85 to $95.

<a id="card-nc-paid-images"></a>

#### NC deed images that cost money (the index is free)

- **Place:** Buncombe, Polk, Gaston, Mecklenburg, Davidson and others, NC
- **Kind:** B: paid or attorney-only
- **The wall:** Pay per page or a subscription for the scanned deed. Buncombe: pay-per-view images on the register's site. Mecklenburg: deeds after Feb 1990 are paid copies. Davidson: pre-1984 records on a paid portal (davidsonportal.com). Polk and Gaston: images through a paid cart. Exact prices are not in our notes.
- **Start here:** https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/SrchName.aspx
- **What it is, and what we lose without it:** The full legal description and the loan amount on a deed of trust are only on the image, not in the index.

**Step by step**

1. Find the instrument in the free index (book and page).
2. Either buy that one image through the site's cart, or read it free on the public terminal in the register of deeds office, or ask the attorney to pull it on his title account.
3. Note the loan amount ('principal sum of $...') and the legal description.

- **What to pull:** Only the deed of trust and the vesting deed for leads you are about to offer on.
- **How to save it:** Save the PDF as `<parcel>_dot.pdf` in ~/Downloads; tell Claude, who can read the loan amount from it.
- **How it gets loaded:** None as a drop folder; the document reader can read a single PDF on request.
- **Time:** About 5 minutes per document. **How often:** Per offer.
- **What we gain:** A real loan amount for the equity estimate. Spartanburg SC images are free and already read this way.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Who else could do it:** The attorney's title account; abstractor; O&E about $85 to $95.

<a id="card-rutherford-rod"></a>

#### Rutherford register of deeds (guest sign-in)

- **Place:** Rutherford County, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** A sign-in page with a **Sign in as a Guest** button (no password). Our code treats it as a login wall and does not use it; a person clicks the guest button. Image viewing is not confirmed free.
- **Start here:** https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4/SrchName.aspx
- **What it is, and what we lose without it:** The deed index for Rutherford (about 8,700 rows on your sheet). Docs disagree: a 2026-10-03 note calls it a permanent login wall; the 2026-10-07 county check found the guest button. Treat it as open to a person.

**Step by step**

1. Open the address. On 'Account Sign In', click **Sign in as a Guest**.
2. Choose the name search. Type the owner's last and first name. Search.
3. Note date, instrument type, book and page, other party for each row. Click an image only if it says free.

- **What to pull:** HOT Rutherford leads: last deed in, deeds of trust and satisfactions, lis pendens. 5 per sitting.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 4 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Equity and chain checks for Rutherford leads.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 5.
- **Who else could do it:** Rutherford register of deeds office in Rutherfordton (free terminals); abstractor; O&E report about $85 to $95.

<a id="card-nc-rod-captcha"></a>

#### NC deed searches behind a CAPTCHA or a math question

- **Place:** Wake, Durham, Brunswick, Iredell, Craven, Greene, Harnett, Randolph and Stokes Counties, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Wake and Durham: Google CAPTCHA on the entry disclaimer. Brunswick: a math question on the public sign-in. Iredell, Craven, Greene, Harnett, Randolph, Stokes: a CAPTCHA on the deed search.
- **Start here:** https://rodrecords.wake.gov/web
- **What it is, and what we lose without it:** Deed chains, deeds of trust and (in Wake and Durham) marriage licenses for leads in these counties. Wake (about 7,100 rows) and Durham (about 3,000) are big on your sheet.

**Step by step**

1. Open the county's deed search: Wake `https://rodrecords.wake.gov/web`; Durham `https://rodweb.dconc.gov/web`; others from the county table below.
2. Tick the CAPTCHA (or answer the math question in Brunswick) and accept the disclaimer.
3. Search the owner's name as grantor and grantee. Note date, instrument type, book and page, other party.
4. In Wake and Durham, for a divorce lead, search the marriage license index for the couple's names if needed.

- **What to pull:** HOT leads in these counties only. 5 per sitting.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 4 to 5 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Equity and chain checks; marriage records for divorce leads. Deed-chain and marriage cells are zero or thin for most of these counties (Wake and Durham are zero across the board).
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 61.
- **Who else could do it:** The county register of deeds office; an abstractor; O&E report about $85 to $95; the attorney's title account.

<a id="card-gaston-rod"></a>

#### Gaston register of deeds index and deed images

- **Place:** Gaston County, NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare 'Just a moment...' check in front of the deed search (a 403 to scripts on 2026-10-07). Deed images are a paid order.
- **Start here:** https://gastonnc.courthousecomputersystems.com/
- **What it is, and what we lose without it:** Deeds, deeds of trust, lis pendens and satisfactions for a Gaston owner. Gaston is our third-biggest NC county (about 9,300 rows on your sheet), and our free reader for this index now meets the check.

**Step by step**

1. Open the address in Chrome. Wait for 'Just a moment...' to finish or tick the box.
2. Accept the disclaimer. Choose the name search.
3. Type the owner's last name and first name. Search grantor and grantee.
4. Note each instrument: date, kind (deed, deed of trust, satisfaction, lis pendens), book and page, the other party.
5. Type the list into the lead's notes, or save the results page (HTML Only) as `gaston_rod_<parcel>.html` in ~/Downloads for the quiet-title sheet.

- **What to pull:** For HOT Gaston leads: the last deed into the owner, every deed of trust and its satisfaction, any lis pendens. 5 leads per sitting.
- **How to save it:** Notes in the CRM, or HTML into ~/Downloads (no loader reads it).
- **How it gets loaded:** None for saved pages. The quiet-title sheet prints this site as 'a person needed'.
- **Time:** About 5 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Whether there is equity (open loans without satisfactions) and a clean chain. On your sheet Gaston's deed-break, quiet-title and lien cells are zero.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 5.
- **Who else could do it:** The attorney's own title search account, a title abstractor, or an O&E report (about $85 to $95). The public terminals in the Gaston register of deeds office (free).

### South Carolina counties

<a id="card-spartanburg-site"></a>

#### Spartanburg County website documents: Master in Equity sale roster, forfeited land list, tax sale list, deficiency and sale results

- **Place:** Spartanburg County, SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare 'Attention Required!' block page to scripts (2026-10-07). Four of our readers got 403 in today's run. If your own browser on the same network shows the same page, the block is on your internet address: use your phone on cellular data or wait a day.
- **Start here:** https://www.spartanburgcounty.gov/DocumentCenter/View/3392
- **What it is, and what we lose without it:** Spartanburg is our biggest county (about 18,000 rows). The monthly Master in Equity roster lists every foreclosure set for sale (25 to 30 a month, with case number, lender, owner and address). The forfeited land list and the yearly tax sale list (about 2,170 parcels) come from the same site. Your sheet shows Spartanburg's foreclosure-sale signal at 0.6%.

**Step by step**

1. Open each address in Chrome: Master in Equity roster `https://www.spartanburgcounty.gov/DocumentCenter/View/3392`; deficiency sales `https://www.spartanburgcounty.gov/DocumentCenter/View/11824`; forfeited land list `https://www.spartanburgcounty.gov/DocumentCenter/View/104130`; tax sale list `https://www.spartanburgcounty.gov/DocumentCenter/View/11161`.
2. Each opens a PDF. Use **File, Save** (or the download arrow).
3. Name them `spartanburg_sc_mie_<date>.pdf`, `spartanburg_sc_deficiency_<date>.pdf`, `spartanburg_sc_flc_<date>.pdf`, `spartanburg_sc_taxsale_<date>.pdf`.
4. Put them in ~/Downloads and tell Claude 'load the Spartanburg PDFs'.

- **What to pull:** The whole PDF each time. The Master in Equity roster monthly; the forfeited land list monthly; the tax sale list once a year when it is posted (autumn).
- **How to save it:** PDF into ~/Downloads. Do not put PDFs in the court drop folder (the app ignores PDFs).
- **How it gets loaded:** None as a drop folder. The readers that fetch these PDFs today can read the same PDF from disk with a small change (about an hour). For the engineer: counties_sc/spartanburg_master_in_equity.py, spartanburg_flc.py, spartanburg_delinquent_tax.py.
- **Time:** About 5 minutes a month. **How often:** Monthly (tax sale list yearly).
- **What we gain:** Every Spartanburg foreclosure set for sale, with owner and address, plus forfeited land.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 3 (in 1 counties; value score 3.0 for about 5 minutes a month)
- **Who else could do it:** Spartanburg Master in Equity's office or Clerk of Court (records request).

<a id="card-horry-probate"></a>

#### Horry probate records portal (free account login)

- **Place:** Horry County, SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Account login with a free Register link (the county publishes how to create one).
- **Start here:** https://scportal.hostedbyspartan.com/HorryACMSPortal/
- **What it is, and what we lose without it:** Horry estate filings. Horry has about 4,900 rows on your sheet and thin probate signals.

**Step by step**

1. Open the address, click **Register**, create a free account, log in.
2. Search estates by filing date (or by your Horry lead surnames).
3. Save the results page as `horry_sc_probate_<date>.html` in ~/Downloads, or type estates into the CRM.

- **What to pull:** Estates opened in the last 30 days: case number, decedent, date, representative.
- **How to save it:** HTML into ~/Downloads.
- **How it gets loaded:** None; small reader needed.
- **Time:** About 10 minutes. **How often:** Monthly.
- **What we gain:** Horry probate leads.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 4 (in 1 counties; value score 4.0 for about 10 minutes a month)
- **Who else could do it:** Horry probate court.

<a id="card-anderson-probate"></a>

#### Anderson probate index on ACPASS (free account login)

- **Place:** Anderson County, SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** A free account login (Register Here). Scripts must not log in, so a person does it.
- **Start here:** https://acpass.andersoncountysc.org/courts.htm
- **What it is, and what we lose without it:** Anderson estate filings (decedent, filing date, representative). Anderson has no probate signal on your sheet. Note: Anderson's tax search on the same site is open (no login, despite what older notes say); the engineer can build that one.

**Step by step**

1. Open the address. Click **Register Here** once and make a free account with your own email.
2. Log in. Open the probate or estate search.
3. Search by filing date if offered, otherwise by the surnames of your Anderson leads.
4. Save the results page (Cmd + S, HTML Only) as `anderson_sc_probate_<date>.html` in ~/Downloads, or type the estates into the CRM.

- **What to pull:** Estates opened in the last 30 days (or matches for your Anderson lead surnames): case number, decedent, date, representative.
- **How to save it:** HTML into ~/Downloads.
- **How it gets loaded:** None; a small reader would be needed once you send one saved page.
- **Time:** About 10 minutes. **How often:** Monthly.
- **What we gain:** Anderson probate leads where there are none today.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 3 (in 1 counties; value score 3.0 for about 10 minutes a month)
- **Who else could do it:** Anderson probate court by phone; abstractor.

<a id="card-york-site"></a>

#### York County tax collection pages and overage list

- **Place:** York County, SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Cloudflare 'Attention Required!' block page to scripts (2026-10-07); our York delinquent-tax reader got 403.
- **Start here:** https://www.yorkcountysc.gov/216/Tax-Collection
- **What it is, and what we lose without it:** York's delinquent-tax list and tax-sale overage claims (owners owed surplus money after a tax sale).

**Step by step**

1. Open `https://www.yorkcountysc.gov/216/Tax-Collection` in Chrome.
2. Click the current delinquent or tax sale list link and save the file (PDF or spreadsheet).
3. Open `https://www.yorkcountysc.gov/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST` and save the PDF.
4. Name them `york_sc_delinquent_<date>.pdf` and `york_sc_overage_<date>.pdf`, put them in ~/Downloads, and tell Claude.

- **What to pull:** The whole list each time.
- **How to save it:** PDF into ~/Downloads.
- **How it gets loaded:** None as a drop folder; the existing York readers can read a saved copy with a small change.
- **Time:** About 5 minutes. **How often:** Monthly.
- **What we gain:** York delinquent-tax and overage leads.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 3 (in 1 counties; value score 0.5 for about 5 minutes a month)
- **Who else could do it:** York County treasurer's office.

<a id="card-avenu"></a>

#### SC deed portal run by Avenu / Neumo (unclear access)

- **Place:** Bamberg, Chester, Chesterfield, Dillon, Edgefield, Fairfield Counties, SC (and Cherokee, see appendix C)
- **Kind:** A: a person can pass it in a browser
- **The wall:** Not confirmed. The county check (2026-10-07) left these to a person in a browser; Cherokee's copy of the same portal has terms that bar automation (terms only, cleared). Some county sites in this group also block scripts.
- **Start here:** https://cherokeesc.avenuinsights.com/
- **What it is, and what we lose without it:** Deed index and, from about 2002, free images, for smaller SC counties.

**Step by step**

1. From the county's register of deeds page, open its Avenu deed search in Chrome.
2. Accept the terms. Search the owner as grantor and grantee and note the instruments.
3. Write down whether the site asked for an account or payment, so the table can be corrected.

- **What to pull:** HOT leads only.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 4 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Deed checks; also settles what these portals require.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 36.
- **Who else could do it:** County ROD office; abstractor.

<a id="card-sc-rod-walled"></a>

#### SC deed searches behind a CAPTCHA, a Cloudflare check or a free account

- **Place:** Beaufort, Aiken, Jasper, Clarendon, Kershaw, Hampton, Lexington and Orangeburg Counties, SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** Beaufort: CAPTCHA on every search. Aiken: Cloudflare check on the county site. Jasper: CAPTCHA on the deed search. Clarendon: blocks automated reads (a person searches free). Kershaw and Hampton: free Neumo account login (Kershaw's terms also bar robots). Lexington: free CountyFusion guest account. Orangeburg: free county ROD account.
- **Start here:** https://rod.beaufortcountysc.gov/searchng/
- **What it is, and what we lose without it:** Deed chains and mortgages for SC leads in these counties.

**Step by step**

1. Open the county's deed search (addresses in the county table below).
2. Pass the CAPTCHA or Cloudflare box, or sign in with a free account you create yourself.
3. Search the owner as grantor and grantee; note date, instrument, book and page, other party.

- **What to pull:** HOT leads only, 5 per sitting.
- **How to save it:** Notes in the CRM.
- **How it gets loaded:** None.
- **Time:** About 4 to 5 minutes per lead. **How often:** Per HOT lead.
- **What we gain:** Deed-chain checks where we have none.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 45.
- **Who else could do it:** SC abstractor (the attorney's usual abstractor); county ROD office.

<a id="card-sc-rod-paid"></a>

#### SC deed records that cost money

- **Place:** Lee, Newberry, Williamsburg, Calhoun, Richland, Darlington Counties, SC
- **Kind:** B: paid or attorney-only
- **The wall:** Lee: Neumo subscription, $5 a day, and terms bar robots. Newberry: free index, deed images $5 a day. Williamsburg: free registration, every image $1 a page, terms bar robots. Calhoun: deeds only on paid TitleSearcher or at the Clerk. Richland: paid county subscription for deeds and probate documents. Darlington: Cott RECORDhub account or subscription.
- **Start here:** https://www.titlesearcher.com/index.php
- **What it is, and what we lose without it:** Deed chains for leads in these counties. Williamsburg (about 2,300 rows) and Darlington (about 2,500) are the largest.

**Step by step**

1. For a single HOT lead: buy one day ($5) in Lee or Newberry, or the needed pages in Williamsburg ($1 each), and search the owner name.
2. Or ask the attorney's abstractor, who already has these subscriptions.

- **What to pull:** Only leads you are about to offer on.
- **How to save it:** Notes in the CRM; PDFs into ~/Downloads.
- **How it gets loaded:** None.
- **Time:** About 10 minutes per lead. **How often:** Per offer.
- **What we gain:** Title checks in paid counties.
- **Reaches the dashboard?** Goes into your CRM notes only; does not reach the dashboard
- **Thin cells on your sheet this fills:** 0 as things stand (notes only). If a loader were built: 33.
- **Who else could do it:** The attorney's abstractor (price not on file).

## Per city

<a id="card-morganton"></a>

### Morganton city website (code enforcement, condemned and vacant structures)

- **Place:** City of Morganton (Burke County), NC
- **Kind:** A: a person can pass it in a browser
- **The wall:** The whole city website sits behind a Cloudflare Turnstile check (403, 'Just a moment...') on every page (2026-09-30).
- **Start here:** https://www.morgantonnc.gov/
- **What it is, and what we lose without it:** Burke's largest city. If the city posts code-enforcement or condemned-structure lists, they would be the only code signal in Burke (Burke has none today).

**Step by step**

1. Open `https://www.morgantonnc.gov/` in Chrome and pass the check.
2. Look under Development and Design Services or Code Enforcement for a list of condemned, unsafe or vacant structures, or minimum housing cases.
3. If a list exists, save it (PDF or HTML Only) as `morganton_nc_code_<date>.pdf` in ~/Downloads and tell Claude. If none exists, tell Claude so the note is closed.

- **What to pull:** Any list of condemned, unsafe, minimum-housing or vacant structures with addresses.
- **How to save it:** File into ~/Downloads.
- **How it gets loaded:** None; a reader would be built only if a list exists.
- **Time:** About 10 minutes, once. **How often:** Once, then quarterly if a list exists.
- **What we gain:** Code-enforcement signal for Burke, which is zero today.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 2 (in 1 counties; value score 2.0 for about 3 minutes a month)
- **Who else could do it:** Call the city's code enforcement office and ask for the list (public record).

<a id="card-city-union"></a>

### City of Union website

- **Place:** City of Union (Union County), SC
- **Kind:** A: a person can pass it in a browser
- **The wall:** A JavaScript 'Client Challenge' page on every address (2026-09-30), a bot shield.
- **Start here:** https://www.cityofunion.net/
- **What it is, and what we lose without it:** The one possible code-enforcement source for Union County SC (the county site has narrative only).

**Step by step**

1. Open the site in Chrome; the challenge clears on its own in a normal browser.
2. Look for code enforcement, condemned or unsafe structure lists.
3. Save any list into ~/Downloads as `union_sc_code_<date>.pdf` and tell Claude, or tell Claude there is none.

- **What to pull:** Any list of code cases or condemned structures.
- **How to save it:** File into ~/Downloads.
- **How it gets loaded:** None.
- **Time:** About 10 minutes, once. **How often:** Once.
- **What we gain:** Possibly the first Union SC code signal.
- **Reaches the dashboard?** Needs a small loader first (about an hour of engineering)
- **Thin cells on your sheet this fills:** 2 (in 1 counties; value score 2.0 for about 3 minutes a month)
- **Who else could do it:** Call the city.

## The UNKNOWN-county rows

Your sheet has 5,121 NC rows and 1,982 SC rows with no county. In NC about 3,062 are bankruptcy cases and about 1,858 are LiensNC lien-agent filings (tagged as tax liens); in SC about 1,952 are bankruptcy cases. Your sheet is from 2026-10-01. On today's board (2026-10-07) the count is down to 2,648 (NC 2,188, SC 460, matching the new gap matrix in docs/gap_matrix/): 1,848 LiensNC filings, 737 bankruptcy cases, 62 SC brownfield sites and 1 SC state tax lien.

- **Bankruptcy rows: a manual step fixes them.** Page 1 of the bankruptcy petition gives the debtor's street address and county. Ask Claude to pull the free copies from CourtListener first; then do the rest by hand, 20 per sitting, with the PACER card above. Save a CSV (case_number, court, street, city, county, state, zip) to ~/Downloads. A small loader is needed.
- **LiensNC rows: no manual step.** The county can be read from the project address and ZIP already on the row; that is an engineering fix. Do not spend time here: the LiensNC signal itself is being redefined.
- **SC brownfield rows (62): no manual step.** These are state environmental sites; the county comes from the site address (engineering).

## Every county at a glance (145 counties)

From the county records matrix (built 2026-10-07 by reading each county's own sites without passing any wall). McCormick SC is missing from the matrix. 'Rows' is from your coverage sheet. Probate for every NC county is the statewide eCourts estate search (see the NC estates card).

### North Carolina

| County | Rows | Deeds | Estates | Tax bills | What a person does | Cards |
|---|---|---|---|---|---|---|
| Alamance | 944 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | Nothing needed beyond the free sites. |  |
| Alexander | 90 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Alleghany | 56 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person opens alleghanync.courthousecomputersystems.com in a normal browser (passes the Cloudflare check) to pull deeds; deed book/page for the current deed is already free in NC OneMap and the BT property card. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Anson | 62 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Ashe | 165 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Bot check: a person in a normal browser | Taxpayer and tax-bill status need a person on qPublic in a browser; NC OneMap gives owner and deed book/page free. | [NC tax lookups](#card-nc-tax-walled) |
| Avery | 115 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Beaufort | 151 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Bertie | 1,106 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | CAPTCHA: a person passes it | Tax-bill status needs a person on the webtaxpay site (human check); deeds, legal and chain are free in the Lookup. |  |
| Bladen | 92 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Did not answer | Tax bill status and taxpayer need a person to call or visit the Bladen tax office (online tax site not reached); NC OneMap has owner and deed book/page free. |  |
| Brunswick | 3,987 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person passes the math question on the Inttek public login to pull deeds and the chain; legal description and deed book/page are free in NC OneMap first. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [Deeds behind CAPTCHA](#card-nc-rod-captcha), [NC foreclosure lists](#card-nc-sp) |
| Buncombe | 10,450 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | Deed images (needed for the full legal description) are pay-per-view on the ROD site; a person buys the few pages needed or reads them on the public terminals in the Buncombe ROD office. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Burke | 1,538 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. | [MLS](#card-mls), [Morganton city](#card-morganton), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Cabarrus | 1,127 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Caldwell | 281 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | CAPTCHA: a person passes it | Tax bill status needs a person on the Caldwell tax site in a browser. | [Cleveland/Caldwell tax](#card-avalon-tax) |
| Camden | 82 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Login (account) | Deeds before May 1999 need a person at the Camden ROD (or a paid abstractor); tax bill status needs a call to the Camden tax office or the county GIS popup. |  |
| Carteret | 456 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Caswell | 80 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Catawba | 5,129 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Chatham | 553 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Bot check: a person in a normal browser | Taxpayer and bill status need a person on the Chatham tax site in a browser (county site blocks scripts); NC OneMap gives owner, short legal and deed book/page free. |  |
| Cherokee | 220 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Login (account) | Tax bill status needs a call to the Cherokee County NC tax office or a person on the GIS viewer; pre-1993 grantor/grantee lookups need the index books in Murphy, though deed images themselves are online by book/page. | [NC tax lookups](#card-nc-tax-walled) |
| Chowan | 78 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Clay | 80 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Cleveland | 1,142 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | CAPTCHA: a person passes it | Taxpayer/bill status needs a person on the Avalon tax site (reCAPTCHA). Current deed book/page is not in any free GIS layer here, so it comes from the ROD grantee search on the owner's name. | [Cleveland/Caldwell tax](#card-avalon-tax), [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Columbus | 167 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | CAPTCHA: a person passes it | Tax-due status needs a person on webtaxpay (human check) or a call to the Columbus tax office. |  |
| Craven | 508 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Deeds, legal descriptions and chain need a person to pass the reCAPTCHA on the CCHS site (or visit the New Bern ROD); NC OneMap gives owner, short legal and deed book/page free first. | [Deeds behind CAPTCHA](#card-nc-rod-captcha) |
| Cumberland | 1,260 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Currituck | 337 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Nothing needed beyond the free sites. |  |
| Dare | 374 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Deeds before 1976 need the books at the Manteo ROD or an abstractor. |  |
| Davidson | 792 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | For deeds before 1984 (or images, if not free on the public site) a person uses the paid davidsonportal.com subscription, the attorney's own access, or the Lexington ROD office. |  |
| Davie | 135 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Duplin | 205 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. |  |
| Durham | 3,019 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Taxpayer and bill status need a person on the Durham tax site (lookup not located by script). | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [Deeds behind CAPTCHA](#card-nc-rod-captcha), [NC foreclosure lists](#card-nc-sp) |
| Edgecombe | 157 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | Nothing needed beyond the free sites. |  |
| Forsyth | 6,355 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Nothing needed beyond the free sites. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Franklin | 519 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | If the CCHS window is challenged, a person opens the Franklin ROD site in a browser, accepts the disclaimer, searches by owner name and views deed images on screen; deeds before 1950 or below Book 650 may need the office or an abstractor. |  |
| Gaston | 9,347 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person opens gastonnc.courthousecomputersystems.com in a browser to search the index; the deed image (for the full legal) is a paid copy, so the attorney's own subscription or a copy order is needed for the deed text. | [Gaston deeds](#card-gaston-rod), [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Gates | 461 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Index and images reachable free in a browser; records before the pre-1995 index start need the office or an abstractor. |  |
| Graham | 528 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | If images need purchase, a person or the attorney's account buys the most recent deed copy from the Cott cart or the office. |  |
| Granville | 300 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | If deed images are not free, a person buys the most recent deed copy (or the attorney uses his account); pre-1746/early books and anything not imaged go to the office or an abstractor. |  |
| Greene | 40 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person opens the Greene ROD site, ticks the reCAPTCHA, then searches by name and views the deed; the legal description must come from the deed image because no free GIS legal exists for Greene. | [Deeds behind CAPTCHA](#card-nc-rod-captcha) |
| Guilford | 5,664 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person accepts the Guilford ROD disclaimer in a browser and searches by name; if images are not free, the attorney's account or a copy order supplies the deed text. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Halifax | 109 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Bot check: a person in a normal browser | Tax bills and assessor cards need a person in a browser (Cloudflare-gated tax site, qPublic terms bar automation); the ROD index is free as a guest, deed images may need the Cott cart or the attorney's account. | [NC tax lookups](#card-nc-tax-walled) |
| Harnett | 1,530 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person ticks the reCAPTCHA on the Harnett ROD site, searches by name, and views/prints deed images free; pre-1973 chains use the scanned old index books, and older gaps go to an abstractor. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [Deeds behind CAPTCHA](#card-nc-rod-captcha), [NC foreclosure lists](#card-nc-sp) |
| Haywood | 641 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Pre-1986 chains need the office's older books or an abstractor; if image links turn out to cost, a person orders the deed copy. |  |
| Henderson | 3,291 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Deeds before book 200 / 1966 need the office's older books or an abstractor; otherwise free online. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Hertford | 35 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Little needed: index and images from 1901 are free online; pre-1901 chains go to an abstractor. |  |
| Hoke | 353 | No online index found: call or visit | NC eCourts: picture CAPTCHA, a person passes it | Not checked | A person must open hokencrod.org in a browser to find the vesting deed (no free legal or deed reference exists in the statewide GIS for Hoke); if that portal will not serve images, the attorney's subscription or the office supplies the deed. |  |
| Hyde | 50 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | The legal description must come from the deed image (statewide GIS legal is mostly blank for Hyde); pre-1991 index gaps need book-by-book browsing or an abstractor. |  |
| Iredell | 1,130 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person passes the CAPTCHA on the new Iredell ROD site and also checks the old Cott guest site for pre-1964 records; image cost unverified, so the attorney's account may be needed for deed copies. | [Deeds behind CAPTCHA](#card-nc-rod-captcha) |
| Jackson | 257 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Did not answer | Index from 1851 is free as guest; if images need purchase, the attorney's account or a copy order supplies the deed; a person finds the current tax bill on the county site. |  |
| Johnston | 1,692 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person acknowledges the EagleWeb disclaimer as guest and reads the deed; the legal description must come from the deed image (no free GIS legal for Johnston). | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Jones | 151 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Pre-1978 deeds need the CCHS site when it is up, otherwise the office or an abstractor; the legal must come from the deed image (no free GIS legal for Jones). |  |
| Lee | 385 | No online index found: call or visit | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | A person opens leencrod.org in a browser to search the index and view the deed; the assessor's legal fields and the statewide GIS give a short legal and the deed reference for free. |  |
| Lenoir | 157 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Guest index search is free; if images cost, the attorney's account or a copy order supplies the deed text. |  |
| Lincoln | 3,612 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Rarely needed: index and deed images are free; very old books are imaged but the verified index start is unclear, so pre-1990s chains may need book-by-book browsing or an abstractor. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Macon | 147 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | A person accepts the Macon disclaimer and searches by name; if images cost or are missing, a copy order or the attorney's account supplies the deed. |  |
| Madison | 901 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Pre-1987 links in the chain require reading the imaged deed books by book/page (free) or an abstractor when the reference is missing. |  |
| Martin | 41 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | A person acknowledges the Martin disclaimer in a browser and reads the deed for the legal (no free GIS legal for Martin). |  |
| Mcdowell | 2,741 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Rarely needed; older gaps go to an abstractor. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Mecklenburg | 11,041 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | For deeds after Feb 1990 the image is a paid copy: the attorney's account or a copy order supplies the legal; the GIS legal and deed book/page are free. Older chains use the free historic image site by book/page. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Mitchell | 253 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Legal description must be read off the free deed image (no GIS legal text for Mitchell). | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Montgomery | 132 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | Little needed: free index from 1792 and free images; a person only steps in when a book is missing from the image list. |  |
| Moore | 715 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | For pre-1988 chain links a person checks the index books at the office (online back-fill incomplete) or uses an abstractor. |  |
| Nash | 523 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Guest index search is free; if images cost, the attorney's account or a copy order supplies the deed text. |  |
| New Hanover | 4,841 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | Little needed: index, property-description search and images appear free; older chains beyond the online index go to an abstractor. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Northampton | 54 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Pre-1991 chain links are found by browsing scanned index books online (free) or by an abstractor; the tax bill needs a person in a browser. |  |
| Onslow | 1,561 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | If deed images need the paid subscription, the attorney's account or a copy order supplies the deed; GIS legal and book/page are free. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Orange | 1,941 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Pre-1932 chain links need the office's older books or an abstractor. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Pamlico | 79 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Free, open | If a deed image will not open or is illegible, or the chain runs before 1872, a person must view the books at the Bayboro register of deeds office or use an abstractor. |  |
| Pasquotank | 126 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must open the CCS deed search in a normal browser (it shows a Cloudflare check to scripts) or visit the Elizabeth City register of deeds office to pull deeds and the legal description. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Pender | 729 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free after an 'I accept' click | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Burgaw register of deeds office to pull the deed chain and full legal description. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Perquimans | 72 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Hertford register of deeds office for deeds, chain and legal description. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Person | 179 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Roxboro register of deeds office for deeds, chain and legal description. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Pitt | 2,390 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free by guest sign-in; a person should check the Certified Dates page for the index start and visit the Greenville office for anything older or for illegible images. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp) |
| Polk | 448 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Bot check: a person in a normal browser | Free index works; a person must view or buy the deed images (or visit the Columbus office) to read the full legal description, and look up the tax bill in a normal browser. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp), [Polk tax](#card-polk-tax) |
| Randolph | 559 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must pass the CAPTCHA on the CCS deed search (or visit the Asheboro office) to pull deeds, old index books and the legal description. | [Deeds behind CAPTCHA](#card-nc-rod-captcha) |
| Richmond | 102 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Did not answer | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or visit the Rockingham (Richmond Co.) register of deeds office for deeds, chain and legal description. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Robeson | 263 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Pre-1974 searches mean paging through scanned old index books online; anything older than the books or illegible needs a visit to the Lumberton register of deeds office or an abstractor. |  |
| Rockingham | 616 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must open the e-Vault in a normal browser (scripts get a Cloudflare check) and, for 1787-1995, page through the scanned old index books, or visit the Wentworth register of deeds office. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Rowan | 813 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Sign in as guest for the index; if images or older books need a paid subscription, a person must view them at the Salisbury register of deeds office. |  |
| Rutherford | 8,720 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Sign in as guest for the index; images and older books not confirmed free, so a person may need the Rutherfordton office for deed images and full legal descriptions. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp), [Rutherford deeds](#card-rutherford-rod) |
| Sampson | 155 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers the whole chain; a person is needed only for illegible images or to confirm the scanned pre-1988 index against the paper books in Clinton. |  |
| Scotland | 108 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | For deeds before 1978 a person must open the pre-1978 site in a normal browser (scripts get a Cloudflare check) or visit the Laurinburg office. |  |
| Stanly | 433 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Free online view covers 1985 forward plus scanned old index books; to print copies or check deed books 396-482 a person must visit the Albemarle register of deeds office. |  |
| Stokes | 230 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must pass the CAPTCHA on the CCS deed search (or visit the Danbury office) to pull deeds, old index books and legal descriptions. | [Deeds behind CAPTCHA](#card-nc-rod-captcha) |
| Surry | 211 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Search and view online for free; to print certified or plain copies a person needs a print login or a visit to the Dobson office. |  |
| Swain | 80 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers deed images back to 1871; a person must visit the Bryson City office only for deed of trust books 1-85 or illegible pages. |  |
| Transylvania | 6,328 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | For deeds recorded before 1973 a person must use the books at the Brevard register of deeds office or an abstractor. | [MLS](#card-mls), [NC estate lists](#card-nc-est), [LiensNC](#card-nc-liensnc), [NC notice text](#card-nc-notice-body), [NC SoS liens](#card-nc-sos-liens), [NC foreclosure lists](#card-nc-sp) |
| Tyrrell | 278 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Not checked | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check) or call/visit the Columbia register of deeds office; tax bills by phone or in person. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Union | 1,564 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Deeds are free online, but deeds of trust and other security instruments are withheld online, so a person must check liens at the Monroe register of deeds office. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [NC foreclosure lists](#card-nc-sp), [NC tax lookups](#card-nc-tax-walled) |
| Vance | 115 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Free online covers the full deed chain back to 1881; a person is needed only for illegible images or certified copies (office hours currently reduced). |  |
| Wake | 7,090 | CAPTCHA: a person passes it | NC eCourts: picture CAPTCHA, a person passes it | Free, open | A person must tick the reCAPTCHA on the Wake deed search to read deeds and legal descriptions (or visit the Raleigh office); scripts cannot. | [NC estate lists](#card-nc-est), [NC notice text](#card-nc-notice-body), [Deeds behind CAPTCHA](#card-nc-rod-captcha), [NC foreclosure lists](#card-nc-sp) |
| Warren | 140 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers the whole chain; a person is needed only for illegible images or certified copies at the Warrenton office. |  |
| Washington | 18 | Bot check: a person in a normal browser | NC eCourts: picture CAPTCHA, a person passes it | Not checked | A person must open the CCS deed search in a normal browser (scripts get a Cloudflare check); for any deed before mid-1996 the paper index books in the Plymouth office (or an abstractor) are needed. | [Deeds behind Cloudflare](#card-nc-cchs-cf) |
| Watauga | 319 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers the index back to 1889; a person must visit the Boone office for record books 2046-2405 (not imaged online) or illegible pages. |  |
| Wayne | 456 | Free, open | NC eCourts: picture CAPTCHA, a person passes it | Not checked | Free index via guest access; a person may need the Goldsboro office for deed images if online viewing is paid, and for anything older than the online index. |  |
| Wilkes | 191 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | For deeds before 1970 (Book 511 and earlier) or index entries before 1927 a person must use the Wilkesboro register of deeds office or an abstractor; the Tax Office deed-copy archive needs its shared login, which a person would have to use. |  |
| Wilson | 324 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Bot check: a person in a normal browser | Sign in as guest for the index; for pre-1974 deeds or images not yet scanned, a person must use the Wilson register of deeds office. |  |
| Yadkin | 182 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers the chain back past 1907; a person is needed only for illegible pages, certified copies, or deed of trust books outside 76-122 that are not imaged. |  |
| Yancey | 120 | Free after an 'I accept' click | NC eCourts: picture CAPTCHA, a person passes it | Free, open | Free online covers index books back to 1833; anything older, missing years, or illegible pages need the Burnsville register of deeds office or an abstractor. |  |

### South Carolina

| County | Rows | Deeds | Estates | Tax bills | What a person does | Cards |
|---|---|---|---|---|---|---|
| Abbeville | 597 | Free after an 'I accept' click | No online index found: call or visit | Did not answer | Index and deed PDFs are free online from about 1978, so a person is needed only for older chain links (abstractor or the book indexes at the office), the qPublic parcel card (open in a normal browser), and probate, which has no online index (call or visit the Probate Court). |  |
| Aiken | 28 | Bot check: a person in a normal browser | Bot check: a person in a normal browser | Free, open | The ROD search sits behind the county's Cloudflare wall, so a person must open aikencountysc.gov/RMC in a browser (or ask the abstractor) for the deed chain; county GIS already gives the assessor legal description, last sale book/page and plat book/page for free. | [SC probate site](#card-sc-probate-net), [SC deeds behind a check](#card-sc-rod-walled) |
| Allendale | 509 | No online index found: call or visit | No online index found: call or visit | Free, open | No online deed index: a person or the abstractor must search the deed books at the Allendale Clerk of Court; the parcel card is qPublic in a normal browser; tax bills are free on qPayBill. | [SC property cards](#card-sc-qpublic) |
| Anderson | 2,681 | Free, open | Login (account) | Login (account) | Deeds recorded since 2/21/2026 must be looked up by a person in the new Ingenuity system (its terms forbid automation); tax bills and probate need a free ACPASS login a person can use, or a call to the offices; pre-1948 deeds need the abstractor. | [Anderson probate](#card-anderson-probate), [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC SoS companies](#card-sc-sos) |
| Bamberg | 474 | No online index found: call or visit | No online index found: call or visit | Free, open | Deed searches go through the Avenu/Neumo portal, which we leave to a person in a browser (or the abstractor) because the same vendor's terms forbid automation; probate is office-only. | [Avenu deed portal](#card-avenu), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Barnwell | 810 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | ROD index and deed PDFs are free; a person is needed only for chain links older than the online index (start year not published) and for probate, which has no working online index. | [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Beaufort | 901 | CAPTCHA: a person passes it | No online index found: call or visit | Free, open | The ROD search is behind a CAPTCHA on every search, so a person must run deed-chain searches in a browser (or the abstractor); county GIS gives the assessor legal description and last deed book/page free. | [SC deeds behind a check](#card-sc-rod-walled) |
| Berkeley | 2,327 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Deed index and PDFs are free online from about 1983; a person or abstractor is needed for older chain links, and probate (county site behind Cloudflare) must be checked by phone or visit. | [Phone lookups](#card-people-search), [SC SoS companies](#card-sc-sos) |
| Calhoun | 497 | Paid | Free, open | Free, open | Deeds are only on paid TitleSearcher or at the Clerk of Court office, so the attorney's abstractor (or a subscription) is needed for the chain and legal description; the free probate party search can be checked by a person. | [SC paid deeds](#card-sc-rod-paid) |
| Charleston | 6,572 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Index from 1978 and images from the mid-1990s are free; earlier chain links need the Archival Room (partly online) or the abstractor/microfilm at the ROD. | [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC probate site](#card-sc-probate-net), [SC SoS companies](#card-sc-sos) |
| Cherokee | 2,756 | No online index found: call or visit | No online index found: call or visit | Free, open | The deed index (1995+) and free images (2002+) are on the Avenu portal, whose terms forbid automation, so a person searches it in a browser; anything before 1995 needs the abstractor or the office books; probate is office-only. | [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos) |
| Chester | 17 | No online index found: call or visit | Bot check: a person in a normal browser | Free, open | Deed searches must be done by a person in the Avenu portal (or by the abstractor); the county site itself blocks automated reads, so probate and ROD coverage questions go by phone. | [Avenu deed portal](#card-avenu), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Chesterfield | 654 | No online index found: call or visit | No online index found: call or visit | Free, open | Deed searches must be done by a person in the Avenu portal (or by the abstractor); parcel details come from the WTH map viewer by hand; probate is office-only. | [Avenu deed portal](#card-avenu) |
| Clarendon | 1,221 | Bot check: a person in a normal browser | No online index found: call or visit | Free, open | A person can search the free AcclaimWeb index and view deed images back to 1988 in a browser (automated reads are blocked); older links need the abstractor. | [Phone lookups](#card-people-search), [SC property cards](#card-sc-qpublic), [SC deeds behind a check](#card-sc-rod-walled) |
| Colleton | 1,317 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Index and deed PDFs are free online from about 1986; older links need the abstractor; probate is office-only. | [Phone lookups](#card-people-search), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Darlington | 2,520 | Login (account) | No online index found: call or visit | Free, open | The deed index is on Cott RECORDhub (account/subscription, no automation allowed), so the chain must come from the abstractor or a person with a RECORDhub account; county GIS gives the assessor legal, deed book/page and plat book/page free. | [Phone lookups](#card-people-search), [SC property cards](#card-sc-qpublic), [SC paid deeds](#card-sc-rod-paid), [SC SoS companies](#card-sc-sos) |
| Dillon | 823 | No online index found: call or visit | No online index found: call or visit | Free, open | Deed searches by a person in the Avenu portal or by the abstractor; parcel facts from the WTH viewer by hand; probate is office-only. | [Avenu deed portal](#card-avenu) |
| Dorchester | 905 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Deed index and PDFs are free on the Online Record System; older links (start year not published) need the abstractor; current tax bills and probate documents need a person (county site blocks automated reads, probate images are paid). | [SC probate site](#card-sc-probate-net) |
| Edgefield | 799 | No online index found: call or visit | No online index found: call or visit | Free, open | Deed searches by a person in the Avenu portal (digital from 1996) and by the abstractor before that; parcel card in qPublic by hand; probate is office-only. | [Avenu deed portal](#card-avenu), [SC property cards](#card-sc-qpublic) |
| Fairfield | 6 | No online index found: call or visit | No online index found: call or visit | Free, open | Deed searches by a person in the Avenu portal or by the abstractor; parcel card on Beacon in a normal browser; probate is office-only. | [Avenu deed portal](#card-avenu), [SC property cards](#card-sc-qpublic) |
| Florence | 1,678 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Free typed index, deed PDFs and scanned index books back to 1889 cover most chains; a person is needed to page through the scanned index books and for probate (statewide probate site blocks us). | [Phone lookups](#card-people-search), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Georgetown | 577 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Index from 1977 and deed PDFs are free; earlier links need the abstractor; probate and current tax bills need a person (probate site blocks us, tax site is a JS app). | [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Greenville | 3,268 | Free, open | Free, open | Free after an 'I accept' click | Everything back to 1787 is indexed and imaged online, so a person can pull the full chain in a browser; probate documents beyond the free index come by copy request or the attorney's subscription. | [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC SoS companies](#card-sc-sos) |
| Greenwood | 6 | Free after an 'I accept' click | Free, open | Did not answer | Free route covers deed chain, legal description and plats back to 1897; a person (or the abstractor) is only needed for mortgage images before April 2001, anything not indexed, and judgments/lis pendens on the SC Public Index. |  |
| Hampton | 2 | Login (account) | No online index found: call or visit | Free, open | A person signs up for a free Neumo account (or the abstractor searches) to read the ROD index and images from 2000 on; records before 2000 and probate need an office visit, call, or the abstractor. GIS gives the current deed book/page free. | [SC property cards](#card-sc-qpublic), [SC deeds behind a check](#card-sc-rod-walled) |
| Horry | 4,891 | Free after an 'I accept' click | Login (account) | Free, open | Deed chain and legal description are free after the disclaimer click; a person may need to buy a copy if a clean image is needed, and probate needs a free portal account (person) or a call to the court. | [Horry probate](#card-horry-probate), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC SoS companies](#card-sc-sos) |
| Jasper | 824 | CAPTCHA: a person passes it | No online index found: call or visit | Free, open | A person must open the CCHS ROD site and pass its CAPTCHA by hand (or the abstractor searches); records before 2007, probate, and the qPublic parcel card all need a person. | [SC property cards](#card-sc-qpublic), [SC deeds behind a check](#card-sc-rod-walled) |
| Kershaw | 1,699 | Login (account) | Bot check: a person in a normal browser | Free, open | A person (not a script: the site's terms forbid robots) logs in with a free Neumo account to read the 1990+ index; pre-1990 records, probate, and the parcel card need a person or the abstractor. | [Phone lookups](#card-people-search), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic), [SC deeds behind a check](#card-sc-rod-walled) |
| Lancaster | 896 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Index, deed chain and lot/subdivision legal are free after a plain disclaimer GET; a person is needed only if images turn out to be paid, for probate (call the court), and for anything older than the online index. | [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Laurens | 2,838 | Free after an 'I accept' click | No online index found: call or visit | Free, open | Free route gives deed chain, property-description legal and images; a person is needed to confirm/check probate and for anything older than the online index. | [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos) |
| Lee | 460 | Paid | No online index found: call or visit | Free, open | ROD search needs a paid subscription ($5/day) and the terms forbid robots, so a person (or the attorney's abstractor) must search it; probate and the qPublic parcel card also need a person. | [SC property cards](#card-sc-qpublic), [SC paid deeds](#card-sc-rod-paid) |
| Lexington | 2,231 | Login (account) | Free after an 'I accept' click | Free, open | GIS gives the legal and current deed book/page free; walking the deed chain needs a person with a free CountyFusion account (or the abstractor); pre-1984 needs the office or an abstractor. | [Phone lookups](#card-people-search), [SC deeds behind a check](#card-sc-rod-walled), [SC SoS companies](#card-sc-sos) |
| Marion | 54 | Did not answer | No online index found: call or visit | Free, open | Everything is manual: a person or the abstractor searches the deed books at the Clerk of Court in Marion, probate by call or visit; the Catalis tax widget may give taxpayer and bills by hand. |  |
| Marlboro | 1,067 | Free, open | Bot check: a person in a normal browser | Free, open | The deed index can be read free as a guest; a person (or the abstractor) must buy copies of the deeds to read legal descriptions, and probate needs a call to the court. | [Phone lookups](#card-people-search), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic) |
| Newberry | 722 | Login (account) | Free, open | Free, open | A person with a free Neumo account reads the 1983+ index; deed images (2003+) cost $5/day, so the legal description needs a paid day or the abstractor; pre-1983 needs the office. | [SC property cards](#card-sc-qpublic), [SC paid deeds](#card-sc-rod-paid) |
| Oconee | 3,210 | Free, open | Bot check: a person in a normal browser | Free, open | GIS gives legal and current deed book/page free and the index is open; a person may need to buy clean copies, and probate is a manual look-up on southcarolinaprobate.net (blocked to scripts today). | [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos) |
| Orangeburg | 133 | Login (account) | No online index found: call or visit | Free, open | A person with a free ROD account reads the index and PDF deeds; probate needs a call or visit; GIS was down today. | [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic), [SC deeds behind a check](#card-sc-rod-walled) |
| Pickens | 4,741 | Free after an 'I accept' click | No online index found: call or visit | Free, open | Index, TMS search and legal descriptions are free after the disclaimer click; a person may need to buy images, and probate is call/visit. | [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos) |
| Richland | 860 | Paid | Free, open | Bot check: a person in a normal browser | ROD and probate documents need a paid county subscription (the attorney's or abstractor's); a person can use the free Estate Inquiry for post-1983 estates; tax and parcel lookups are by hand on the county site. | [SC paid deeds](#card-sc-rod-paid) |
| Saluda | 460 | Did not answer | No online index found: call or visit | Free, open | GIS gives legal, current deed and the prior deed reference free; deeper chain needs a person on Cott RecordHub (unreachable today) or the abstractor; probate is call/visit. |  |
| Spartanburg | 18,020 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | Free route covers deed chain, legal and plats; a person browses the scanned old index books (1785-1992) by hand to trace pre-computer chains, and probate is by notice or call. | [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos), [Spartanburg PDFs](#card-spartanburg-site) |
| Sumter | 3,095 | Free after an 'I accept' click | Bot check: a person in a normal browser | Free, open | GIS gives legal and current deed book/page free; walking the chain is a guest-click CountyFusion search (a person, or a script if terms allow once read); probate is call/visit. | [Phone lookups](#card-people-search), [SC probate site](#card-sc-probate-net), [SC SoS companies](#card-sc-sos) |
| Union | 1,297 | Free, open | No online index found: call or visit | Free, open | Index and deed chain are free as a guest; a person may need to buy images to read full legal descriptions; probate is call/visit. | [City of Union](#card-city-union), [MLS](#card-mls), [Phone lookups](#card-people-search), [SC notice text](#card-sc-notice-body), [SC property cards](#card-sc-qpublic), [SC SoS companies](#card-sc-sos) |
| Williamsburg | 2,272 | Login (account) | No online index found: call or visit | Free, open | A person registers (free) to search the index, but terms forbid robots and every deed image costs $1/page, so legal descriptions and the chain come from a person or the abstractor; probate is call/visit. | [Phone lookups](#card-people-search), [SC paid deeds](#card-sc-rod-paid) |
| York | 174 | Free after an 'I accept' click | Bot check: a person in a normal browser | Bot check: a person in a normal browser | Free route covers deed chain and property legal; a person may need to buy images, read probate documents (paid viewer) and look up tax bills on the county site by hand. | [SC probate site](#card-sc-probate-net), [SC property cards](#card-sc-qpublic), [York PDFs](#card-york-site) |

## Paid or attorney-only (type B): prices

Prices come from our notes (mostly 2026-07 and 2026-08) and are not re-checked; confirm before buying. 'Not on file' means we never recorded a price.

| What | Price | What it gets | Free alternative |
|---|---|---|---|
| PACER (federal court documents) | $0.10 a page, max $3.00 a document; waived under $30 a quarter. 2027: $0.12 and $40. | Bankruptcy petitions for UNKNOWN-county rows; any federal docket. | CourtListener RECAP (free) first. |
| SC Secretary of State UCC search | $5 a search | UCC liens against SC companies | Low value |
| NC Secretary of State bulk data subscription | Not on file | Bulk federal tax liens and entity data | Per-name hand lookups are free |
| Neumo (Lee SC) | $5 a day | Deed index and images | Abstractor |
| Neumo images (Newberry SC) | $5 a day | Deed images 2003 on | Free index |
| Neumo images (Williamsburg SC) | $1 a page | Deed images | Free registration for the index |
| TitleSearcher (Calhoun SC) | Not on file | Deeds | Clerk of Court office |
| Richland SC online data | Not on file | Deeds and probate documents | Attorney's or abstractor's subscription |
| Cott RECORDhub (Darlington SC) | Not on file | Deed index | Abstractor |
| Deed images: Buncombe, Polk, Gaston, Mecklenburg (post-1990), Davidson (pre-1984) | Not on file | Full legal description, loan amount | Public terminal in the office (free); attorney's title account |
| Oconee SC deed copies (Kofile) | $2 to $4 a document | Clean deed copies | Free index |
| Title O&E report (any county) | About $85 to $95 a property | Owner, liens, loans of record | Abstractor |
| MLS feed (license required) | Trestle about $100 to $250 a month plus per-MLS fees; broker feed about $30 a month | Closed sales, expired and withdrawn listings | A licensed agent partner |
| Skip tracing | Tracerfy ~$0.02/record; DataZapp $0.02 to $0.03 ($125 min); BatchData $0.07 to $0.18; REISkip $0.15 to $0.22/hit; BatchData Growth $1,000/mo | Owner phones and emails | Hand lookups (above) |
| Property data platforms | PropStream $99 to $699/mo (Pro $199); PropertyRadar $99 to $119/mo solo; ATTOM ~$95 to $500/mo, bulk backfill $1,500 to $5,000; Realie $50 to $350/mo; RentCast $199 or $449/mo; HouseCanary ~$5 a valuation report | Square feet, sales, liens, comps | qPublic cards by hand; county layers |
| Lien data | CoreLogic involuntary lien API $11.50 a call; ATTOM ~$500/mo | Open liens (never the live payoff) | Deed-of-trust images |
| Court data vendors (UniCourt, Trellis) | Not on file | SC Family Court and other dockets | Records requests |
| NCOALink (USPS change of address) | $15,000+ a year | Forwarding addresses | None |
| Westlaw or Lexis (the attorney's subscription) | Not on file | Court dockets where his plan covers NC or SC state courts | The public portals by hand |
| SCDOT statewide SC parcel layer | No price: agency-only sign-in, no public account | SC owner and address lookups | County map layers (in use for 8 of 11 core SC counties) |
| USPS vacancy data (via HUD) | Not for sale to us: government and nonprofit licensees only | Vacancy flags | Land-use vacancy proxy (built) |

## Appendix C: terms-only restrictions (allowed, built or buildable)

No technical barrier. The attorney has cleared terms-only restrictions, and a robots.txt line is not a wall by the owner's rule (2026-09-20). If a CAPTCHA, login or bot check ever appears on one of these, it moves to type A.

| Source | The restriction | Status |
|---|---|---|
| SC Judicial Public Index (all SC counties) | Disclaimer bars automated, repetitive querying (court Rule 610 and an administrative order). No CAPTCHA seen in 58 searches (2026-10-04). A JavaScript check that a real browser passes on its own. | Cleared by the attorney for our use (2026-10-07). Being built now: foreclosure, partition, quiet-title, lis pendens and judgment case lists in all 46 SC counties. If the reader meets a CAPTCHA, login or bot check it stops, and those lanes stay manual (see the fallback card). Evictions are skipped (they name the tenant). |
| Anderson SC tax search (ACPASS) | robots.txt says Disallow, and every page prints the SC notice that public-access data may not be used for commercial solicitation. Not behind the login (re-checked 2026-09-10). | Buildable: owner, mailing address, balance due by year. The attorney confirmed SC Code 30-2-50 does not stop our SC mailings (2026-10-07). |
| Anderson SC deeds since 21 Feb 2026 (Ingenuity system) | Terms forbid automation. | Buildable after the switch to the new system is mapped; older deeds are on ACPASS. |
| Cherokee SC deeds (Avenu) | Terms forbid data mining, robots, spiders. | Buildable: index 1995 on, free images 2002 on. |
| Kershaw, Lee, Williamsburg SC (Neumo terms) | Terms forbid robots. | Still need an account or payment (see the paid table), so they stay walled in practice. |
| Oconee SC deeds (Kofile PublicSearch) | robots.txt Disallow: / (not a wall by the owner's rule). The 2026-09-10 recheck found an open data path. | Buildable. |
| qPublic property cards (Schneider), many SC counties | Terms prohibit robots and scraping. | The terms part is cleared; the Cloudflare check on searches still makes bulk reads a wall. Per-parcel reads by a person: see the qPublic card above. |
| Spatialest / Schneider tax cards (for example Alamance NC) | Disclaimer links terms that prohibit robots. | Buildable where no other check stands in front. |
| SC Family Court divorce name search | Terms ban automated use; the full divorce record is a restricted court system, not on the public index. | Name search buildable, but our test found 0% real hits; low value. |
| Zillow, Redfin, Realtor.com, Trulia, Xome, Hubzu | Terms ban scraping. Zillow also shows a 'press and hold' bot check on some runs; Hubzu and Xome are JavaScript apps behind Cloudflare that our browser renders. | Built where they run (Zillow 88, Hubzu 17, Trulia 9, Xome 9 rows on the board). Redfin Data Center ZIP statistics: buildable (a known fix in the build queue). Low value: these list the same bank-owned and auction homes we get elsewhere. |
| LoopNet, LandWatch, Land and Farm, Lands of America | Akamai bot shield; terms. | LandWatch and Land and Farm run (551 and 426 rows). LoopNet is a hard block and only matters for multifamily; Crexi is the free multifamily source. |
| Auction.com | Imperva bot shield on listing pages; terms. | Buildable through the site's public sitemap (2026-09-10 recheck); 21 rows on the board today. |
| Sites whose robots.txt names AI crawlers (SeeClickFix, Transylvania Times) | robots.txt only. | Allowed by the owner's rule (2026-09-20). SeeClickFix runs but fell 97% in today's run (an engineering issue). |
| Lexington SC probate search | Disclaimer cites the SC Family Privacy Protection Act (no commercial solicitation use). | Buildable. The attorney confirmed SC Code 30-2-50 does not stop our SC mailings (2026-10-07). |
| Click-through disclaimers on most register of deeds sites (82 of 145 counties) | An 'I accept' click with accuracy-only text. | Allowed; most are built or buildable (see the county table). |
| CourtListener / RECAP (federal courts) | None for search; docket alerts need a free account. | Built (bankruptcy feed). Optional by hand: set free docket alerts on HOT bankruptcy-stayed foreclosures. |

## Data that does not exist anywhere

No browser, payment or subscription gets these. Stop looking.

- **Live mortgage payoff balance.** Only the loan servicer has it, and releases it only to the borrower or someone the borrower authorizes in writing.
- **SC sale price on foreclosure, deed-in-lieu and other exempt deeds.** SC Code 12-24-70: exempt deeds state no value.
- **Debt amount in an NC foreclosure notice of sale.** NC law requires only sale terms, deposit and upset-bid rules. The number is in the clerk's paper file (records request) or an O&E report.
- **SC magistrate eviction list in bulk.** No online roster exists. Records request to the Chief Magistrate, or the Legal Services Corporation data program (civilcourtdata@lsc.gov).
- **A structured investor buy-box feed.** Does not exist; the curated buyer list is the answer (built).
- **Owner email addresses in public records.** Not in any public record. Paid only.
- **SC voter phone numbers.** The SC voter file has no phone column, and its use is restricted.
- **Utility shutoff lists (NC).** NC G.S. 132-1.1 removes utility billing records from the public-records law.

## Stop doing these (already automatic or useless)

- **NC eCourts divorce saves.** The open NC judgment search already gives granted divorces statewide, with no CAPTCHA (5,777 rows on the board).
- **NC eCourts lis pendens saves.** Same open judgment search (10,761 rows).
- **NC eCourts hearing calendar saves.** Low value; foreclosure dates come from the law-firm calendars.
- **All routine SC Public Index saves (foreclosure, partition, quiet title, lis pendens, judgments, state tax lien).** Cleared by the attorney and becoming automatic in all 46 counties; state tax liens come from the state registry. Hand-save only if the automatic reader reports a CAPTCHA, login or bot check.
- **SC Public Index eviction (Possession 450) saves.** The case names the tenant, not the owner. Every saved row adds a wrong name.
- **Saving Anderson or Pickens tax pages, SC company pages, SC contractor roster pages, SC case detail pages.** Nothing reads those files. Read the number and type it into the CRM instead.

## Gaps and disagreements in our notes

- Rutherford NC deeds: a 2026-10-03 note calls the Cott site a permanent login wall; the 2026-10-07 county check found a 'Sign in as a Guest' button with no password. This document treats it as type A (a person clicks the guest button). Our code still treats it as walled.
- Anderson SC tax: the county matrix (2026-10-07) says the tax page redirects to a login; the 2026-09-10 recheck found the tax search itself open (the redirect page still carries the content). This document follows the recheck (type C, buildable; the attorney cleared SC Code 30-2-50 for our mailings on 2026-10-07).
- CCHS deed sites for Burke, Lincoln, Cleveland and Henderson: the old master list says 'decommissioned'; our reader and the 2026-10-07 check found them live. The old line is stale.
- NC eCourts search labels: the exact filter names on the Tyler portal ('Advanced Filtering Options', 'File Date', 'Location') are from our notes, not re-read today. If a label differs, pick the closest match.
- Whether a saved NC estate list keeps the executor's name: not yet confirmed on a real save. Check the first one.
- southcarolinaprobate.net refused our plain request with a 403 today, even with a normal browser identity. We did not open it in a real browser. If your browser also gets 403, the site is down for everyone.
- Spartanburg and York county websites answered our single polite request with Cloudflare 'Attention Required!' today. This may be a block on this Mac's internet address after our readers' runs, in which case your own browser on the same network could see it too.
- Rutherford, Edgecombe and Avery county websites gave our readers 403 in today's run but answered a single polite request normally an hour later; treated as temporary, no card.
- The 'UNKNOWN' counts: your coverage sheet (2026-10-01) has 7,103 rows; today's board and the new gap matrix (2026-10-07) have 2,648. The steps are the same.
- The new gap matrix (docs/gap_matrix/README.md, written today by another session) counts 1,031 'walled' county-column cells. Most are the attorney title-check columns (deed reference, register lien check, probate case, heir candidates, tax confirmation) in counties whose deed, probate or tax site needs a person; the deed, probate and tax cards here are how a person fills them. Its other walled reasons are each covered above: SC company search CAPTCHA, SC voter list sold without phones, HUD vacancy data, SC family-court terms; and SC Public Index terms, which the attorney has since cleared (2026-10-07), so those cells move to 'being built'.
- Lead estimates marked 'estimate' are ours, not measured. Name-to-parcel matching was measured at about 29% automatic (2026-07).
- Avenu portal counties (Bamberg, Chester, Chesterfield, Dillon, Edgefield, Fairfield): access is 'unclear' in the matrix. The card asks you to note what the site requires.
- Prices for deed images in Buncombe, Polk, Gaston, Mecklenburg, Davidson, and for TitleSearcher, Richland and Cott RECORDhub, are not in our notes.
- No document named docs/new_sources_2026-10-07_*.md existed when this was finished, so nothing from that work is included.

## Where this came from

- docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md, docs/walls_register.md, docs/blocked_sources_forensic.md, docs/manual_source_inventory.md, docs/manual_playbook_and_limits.md, docs/honest_operator_manual.md, docs/operator_manual_manual_steps_and_paywalls_2026-10-04.md
- docs/source_reverification_2026-09-10.md, docs/source_unblock_plan.md, docs/COUNTY_SYSTEMS_REGISTRY.md, docs/ROD_PORTAL_ACCESS.md, docs/foia_court_records.md, docs/operator_playbook_liensnc_and_bankruptcy.md, docs/gather_steps.md, docs/HANDOFF.md
- docs/county_records/README.md and county_records_matrix.json (145 counties, 2026-10-07)
- Live run_meta.json on the dashboard (run of 2026-10-07 17:09 UTC): source status, alarms and dormant reasons
- Scraper and enricher docstrings under src/foreclosure_scraper that describe a CAPTCHA, Cloudflare, DataDome, Akamai, Imperva, PerimeterX, AWS-WAF, token or login wall
- The manual lanes in code: scripts/ingest_saved.sh, scripts/parse_nc_ecourts_export.py, scripts/ingest_publicindex_files.py, scripts/ingest_contacts.py, scripts/ingest_liensnc.py, scripts/verify_lead_human_assisted.py
- The owner's coverage sheet county_signal_coverage_FINAL.csv (73 signals x 146 counties, plus 2 UNKNOWN rows), and the new docs/gap_matrix/README.md (2026-10-07) for the walled-cell cross-check
- One polite request (ordinary browser identity, 2 seconds apart) on 2026-10-07 to each of: southcarolinaprobate.net, spartanburgcounty.gov, rutherfordcountync.gov, yorkcountysc.gov, edgecombecountync.gov, averycountync.gov, foreclosure.com, publicnoticesc.com, redfin.com, xome.com, hubzu.com, auction.com. No wall was passed.

