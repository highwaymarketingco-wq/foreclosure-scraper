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

---

# PLATFORM FINGERPRINT — 2026-08-12

The widened sweep located **86 of 146** county recorders (up from 42), of which
**71 are not referenced anywhere in src/** and **46 carry no CAPTCHA or login**.
Fingerprinting those 46 by fetching each one:

| platform | counties | usable as a record source? |
|---|---|---|
| **"The Lookup"** | **12** | **YES — index + search, no restriction language** |
| Permitium | 18 | **NO — see below** |
| unknown / bespoke | 15 | needs individual inspection |
| AmericanLandRecords | 1 | not yet mapped (Anderson SC) |

## Permitium is an ordering counter, not an index

18 NC counties link `<county>rod.permitium.com/rod`, which looks like a
register-of-deeds portal and is not one. Fetched: the page offers "order",
"certified copy" and "fee" — it sells certified copies of documents you already
know the reference for. There is no name index and no date-range search behind
it, so it yields no leads.

Counting those 18 as coverage would have inflated the recorder story by 40% with
systems that cannot answer "what was filed last week". Recorded here so the next
sweep does not re-discover them as a win.

## The Lookup — one reader, twelve counties

Same platform, same `?Accept=Accept` entry, same `content.php?<nonce>` search
surface documented above:

    SC   abbeville · barnwell · berkeley · colleton · dorchester ·
         florence · georgetown · york
    NC   bertie · clay · haywood · yancey

Haywood and Yancey were invisible to the fingerprint at first because the
registry holds their LANDING page (`haywooddeeds.com`) while the platform lives
on `search.haywooddeeds.com`. Probing `search.<county>deeds.com` directly
confirmed both. The same probe found no Lookup for henderson, lincoln, guilford
or wilson, so those four are genuinely a different system and still unclassified.

Of these twelve, only Colleton, Georgetown and York sit outside the core
footprint by the core-county rule — but a reader written once serves all of
them, so the marginal cost of the coastal ones is zero.

## SOLVED — the working request (2026-08-12)

There is no DataTables AJAX endpoint. That guess was wrong. `submitSearch()` in
`js/functions.js` does nothing but `$('#'+st+'_form').submit()` — an ordinary
form submit. Three real facts explain the empty shell:

**1. It must be GET, not POST.** POSTing to `content.php?<nonce>` returns a
2,065-byte tab shell for every search type, including a plain name search. The
same parameters as a GET return records.

**2. `embed=1` is required**, and it is not in any form on the page. It was
found by reading the row links inside a working browse result, which are emitted
as:

    content.php?embed=1&display_name=<NAME>&party_type=&entity_type=
               &searchType=name&wildCard=Exact

**3. `received` needs `received_from`.** Omitting it returns 72 bytes:
`<script>alert('Must key in received from text');history.back();</script>` —
a client-side alert, which is why it reads as an empty success to anything that
only checks the status code.

### The two calls that work

Accept once per session, then:

    GET content.php?searchType=browse&last_name=SMITH&first_name=
        &browse_others=&excludeVoids=
      -> 21 KB name index, every party with its document count:
         "SMITH ALAN DALE (58)", "SMITH ALBERT H III (50)"

    GET content.php?embed=1&display_name=SMITH+ALAN+DALE&party_type=
        &entity_type=&searchType=name&wildCard=Exact
      -> 163 KB, 72 rows

Send `Referer: <base>/index.php?Accept=Accept`. Reuse the `PHPSESSID`.

### What a row contains

    Date | Book Info | Doc Type | Property Desc | Search Party Type |
    Searched Party | Reverse Party | XRef | Image?

Verified live, e.g.:

    19860911  DT T296 343  CAN D/T  PD:BK T286 PG 627  GRANTOR
              SMITH ALAN DALE -> ENKA CREDIT UNION      TIFF PDF

Doc types seen include DEED and D/T (deed of trust). Both grantor and grantee
are present, so the grantor/grantee direction is queryable via `party_type`, and
every row carries TIFF/PDF image links.

### Why this matters beyond one county

`browse` gives the complete party index with per-name document counts, which
means the index can be walked without knowing a name in advance — the bulk path.
`received_from` remains unsolved and is the cleaner "what was filed this week"
route; the alert says it wants text, so it is likely a starting instrument or
book reference rather than a date.

All twelve Lookup counties share this, so one reader serves all of them.

---

# CORRECTION — 2026-08-12: the "twelve counties, one platform" claim was wrong

Everything above about The Lookup is accurate for **three** counties. The claim
that twelve counties share it is not. Nine of them run a **different platform**,
and one is still walled. This section is the measured replacement.

## How the error happened, and why nothing caught it

All twelve sit on `<county>deeds.com` and all twelve answered **HTTP 200** to an
accept step, so a reachability check passed for every one. The fingerprint never
asked the only question that mattered: *does a search return rows?*

Pointing the Lookup reader at the other nine returns **404 with a 16-byte body**
— which a status check reads as "this county has no records". The enricher would
have reported nine empty counties forever. Worse, the only county with board
coverage (Georgetown, 409 leads) is one of the nine, so the enricher as shipped
enriched exactly nothing.

## Two platforms, no shared endpoints

| | The Lookup | Online Record System |
|---|---|---|
| entry | `index.php?Accept=Accept` | `NameSearch.php?Accept=Accept` |
| search | `content.php` (GET) | `NamePick.php` → `NameDisplay.php` (POST) |
| amount in index | no | **yes** |
| counties | clay, haywood, yancey (NC) | 8 SC (below) |
| reader | `enrichment_rod_lookup.py` | `enrichment_rod_name_index.py` |

Bertie NC is neither: it serves a 2,617-byte disclaimer loop and is still walled.

## Wrong-state counties — a live trap in the URL pattern

`<county>deeds.com` does not say which state it is, and county names repeat:

- **hendersondeeds.com is Henderson County KENTUCKY** (assets under `/ky/henderson/`)
- **wilsondeeds.com is Wilson County TENNESSEE**

Both were one step from being adopted as NC register-of-deeds sources on pattern
match alone. Every host now in use was confirmed against the county's own site:
`haywoodcountync.gov` links `haywooddeeds.com`; `claydeeds.com` resolves to
`deeds.claync.us`; Yancey is the only Yancey County in the country.
`build_county_registry.py` now carries a `state_confirmed` check so a shared
county name cannot be adopted silently again.

## The Online Record System — working three-step flow

    1. GET  NameSearch.php?Accept=Accept        clears disclaimer, sets PHPSESSID
    2. POST NamePick.php                        -> PARTY index (checkbox per name)
       search_type=Standard sort_type=Date entity_type=Both
       start_date=MM/DD/YYYY end_date=MM/DD/YYYY instType[ALL]=ALL
       tor_last_name=<grantor>  tee_last_name=<grantee>   (both may be blank)
    3. POST NameDisplay.php                     -> the DOCUMENTS
       igheader=ALL  igquerystring=  displaybutton=Display Detail Listing
       entityID[<ID>]=<ID>  for each party

**Step 3 takes only its own fields.** Echoing the step-2 search parameters back
returns a 21-byte rejection. That cost several attempts to find.

A row is: `Date | Code-Book-Page | Type | Description | Amount | Reverse Party |
Cross-Ref | Img?` — verified live, e.g.

    08/10/2026  RECORD BOOK-5057-427  SATISFACTIO  PD:FORECLOSURE BK 4589 PG 312
    08/10/2026  REVOCATION OF RELEASE OF TAX LIEN  PD:21MS22-14 / 105239.55

**`instType` is ignored at step 2.** Sending `instType[LIS PENDENS]`, the paired
`instType[LIS PENDENS][MORT]`, and an `igheader` variant all returned byte-identical
responses to `instType[ALL]`. Filter on the row `Type` at parse time instead.

## Only two of the eight honour the date window

`searchLimit = 2000` is declared in the page. Measured with a one-day window
against a one-month window, fresh session each time:

| county | 1 day | 1 month | date window |
|---|---|---|---|
| barnwell | 24 (7d) | 230 | **honoured** |
| georgetown | 161 | 1374 | **honoured** |
| abbeville | 2000 | 2000 | ignored |
| berkeley | 2000 | 2000 | ignored |
| colleton | 2000 | 2000 | ignored |
| dorchester | 1996 | 1996 | ignored |
| florence | 1973 | 1973 | ignored |
| york | — | — | undetermined (repeated timeouts on a 470 KB page) |

A single day in Colleton (population ~38k) cannot produce 2,000 transacting
parties. Those counties return the head of the whole index for any window.

This is the dangerous case: the response is large, well-formed and HTTP 200.
Publishing it as "last week's filings" would put years-old instruments on the
board as fresh distress. `bulk_by_date()` therefore **refuses** to run unless the
date filter is measured `True`, and refuses a window that comes back at the cap.

## What is actually open, and what it is worth

- **Bulk date-range lead source**: barnwell + georgetown only. Both are outside
  the core Upstate-SC / Western-NC footprint, so the capability is built and
  documented but not wired as a new lead source.
- **Name lookup**: all 8 SC counties, useful as enrichment wherever a lead
  already has an owner name.
- **The real prize is still The Lookup's `browse`**: clay, haywood and yancey are
  core Western NC counties holding **zero** board leads, and `browse` walks the
  party index with no name needed. That is the highest-value unbuilt item here.

## `received_from` — closed as a dead end

The Lookup's `received` date-range search demands `received_from` (label:
"Received From Text"). Omitting it returns 72 bytes of `alert('Must key in
received from text')`. Tested and **all returned 0 bytes**: `%`, `A`, `TRUSTEE`,
`TRUSTEE SERVICES`, `SUBSTITUTE TRUSTEE`, `BROCK`, `HUTCHENS`, `TITLE`; each also
without `embed=1`, against both the nonce action URL and bare `content.php`.

Do not re-attempt without new information. `browse` is the working bulk path.
