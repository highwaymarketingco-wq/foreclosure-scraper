# Register-of-deeds portals — access recipe

Register of deeds is where **deeds of trust, lis pendens, satisfactions and
substitutions of trustee** are recorded. It is the primary distress record, and
until 2026-08-12 this project read none of the county-run ones.

Six were found in the core footprint by
`scripts/build_county_registry.py`. This file records exactly how far each was
opened, so a build starts from evidence rather than from scratch.

## Legal position — checked, not assumed

The Haywood and Yancey disclaimers were fetched and read in full. Both are pure
accuracy-and-liability text. Neither contains **any** of: automated, robot,
spider, scrape, data mining, bulk, commercial, redistribute.

That is the opposite of the walled systems and the distinction matters:

| system | position |
|---|---|
| `cherokeesc.avenuinsights.com` | terms forbid "data mining, robots, spiders, data harvesting" |
| `publicindex.sccourts.org` | disclaimer forbids automated / repetitive querying |
| `portal-nc.tylertech.cloud` | AWS-WAF escalating image CAPTCHA |
| **Haywood / Yancey ROD** | **no restriction language at all** |

## The gate is a GET parameter, not a POST

The disclaimer renders a `<form method="post" action="index.php">` with a single
`Accept` submit button — but POSTing `Accept=Accept` returns the disclaimer
again. What actually works is the GET form:

    http://search.haywooddeeds.com/index.php?Accept=Accept

That returns 41 KB — "The Lookup" — and sets a `PHPSESSID` cookie which the rest
of the session needs. Same shape as Colleton, whose own link is published as
`search.colletondeeds.com/NameSearch.php?Accept=Accept`.

Use one session, accept once, reuse the cookie.

## The search surface

Everything posts to `content.php?<nonce>` — the nonce is embedded in the page
and changes per session, so it must be read from the accepted page, never
hardcoded. Eight forms share that action, distinguished by `searchType`:

| form | purpose | fields |
|---|---|---|
| `name_form` | party name | `search_type`, `sort_type`, `party_type`, `entity_type`, `last_name`, `first_name`, `start_date`, `end_date`, `exact_match` |
| `received_form` | **recording date range** | `received_from`, `rf_start_date`, `rf_end_date`, `instType[ALL]` |
| `bookpage_form` | book/page | `bookcode`, `booknum`, `pagenum` |
| `instrument_form` | instrument number | `inst_num` |
| `property_form` | legal description | `lot`, `parlot` |
| `browse_form` | index browse | `browse_others`, `excludeVoids` |

`received_form` is the one worth building: a date-range query over recently
recorded instruments needs no name and is exactly the "what was filed this week"
shape a foreclosure engine wants.

Instrument types are enumerated in the page's `instType[...]` checkboxes; the
distress-relevant one confirmed present is `DT ~ DEED OF TRUST BOOK`.

## WHERE THIS STOPS, and what the next person must solve

Posting `received_form` with the correct field names — `searchType=received`,
`rf_start_date`, `rf_end_date`, `instType[ALL]=ALL`, in `MM/DD/YYYY` — returns
HTTP 200 and a **2,065-byte tab shell containing only the Home tab**. No rows.

The page loads `jquery.dataTables.js` and the forms `target="content_frame"`, so
results are almost certainly fetched by a **separate DataTables AJAX call** that
the plain POST never triggers. Finding that endpoint is the remaining work:
watch the network panel on a real search, or read `js/functions.js` for the
handler behind `submitSearch()`.

Do not mistake the 200 for success — that shell is what a rejected or
un-triggered search returns, and a scraper that reads it as "no records" would
silently report an empty county forever.

## The six, and their state

| county | entry | gate | opened to |
|---|---|---|---|
| Haywood NC | `search.haywooddeeds.com/index.php?Accept=Accept` | click-through | full search UI, forms mapped |
| Yancey NC | `search.yanceydeeds.com/` | click-through, same platform | disclaimer read, same shape |
| Anderson SC | `americanlandrecords.com/land-record?countyId=2429` | none | not yet mapped |
| Henderson NC | `hendersondeeds.com` | disclaimer | not yet read |
| Lincoln NC | `lincolnrod.com` | disclaimer | not yet read |
| Avery NC | `averydeeds.com` | **reCAPTCHA** | out of scope by policy |

Haywood and Yancey run the same platform ("The Lookup"), so one reader should
serve both, and probably more — the widened pattern sweep in
`build_county_registry.py` looks for `search.<county>deeds.com` precisely
because that shape was invisible to the first run.
