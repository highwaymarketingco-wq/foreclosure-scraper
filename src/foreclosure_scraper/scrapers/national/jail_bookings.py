"""County jail booking scraper — current in-custody inmate rosters.

Queries public county jail booking systems across our NC/SC footprint and
extracts inmate name, booking date, charges, and DOB (where available).
Returns Listing objects with listing_type=UNKNOWN (these are lead-discovery
signals, not property listings — the orchestrator cross-references inmate
names against property owner records downstream).

Supported systems (all free, public, no auth):
  - CentralSquare P2C (policetocitizen.com) — Buncombe NC (modern SPA variant
    with XSRF token handshake, ~540 in custody)
  - CentralSquare P2C jqGrid — Cleveland NC (classic ASP.NET jqGrid)
  - Zuercher Portal — Cherokee SC, Anderson SC (JSON API)
  - Southern Software Citizen Connect — Henderson NC (PHP AJAX "current
    confinements" roster; publishes FULL DOB on every record)
  - Tyler New World InmateInquiry — Gaston NC (plain GET form + HTML grid;
    publishes FULL DOB on every record)

NOT AN OWNER MATCH (checked 2026-10-05). Unlike enrichment_jail_bookings, this
scraper never compares an inmate to a property owner: each Listing IS the
inmate (defendant = the roster name, no address), and its raw['jail_booking']
describes that person's own booking. It sets no raw['incarceration'], so
distress_score's incarceration signal never fires off these rows, and it
carries no matched_name/confidence, so the enricher's same-county middle-name
gate and re-evaluation (which only touch the enricher's own stamps) leave these
rows alone by design.

Each system returns current in-custody inmates. We extract:
  - Inmate name (last, first, and the middle name where the vendor prints one)
  - DOB (if exposed — Buncombe redacts; Cleveland/Cherokee/Henderson/Gaston
    publish it in full, which is the point: DOB is the single biggest lift to
    downstream skip-trace match rates)
  - Booking/arrest date
  - Primary charge description
  - Release status (in-custody flag + scheduled release date where published)

FIXED 2026-10-14 (source-completeness audit, "mugshot inconsistency across
vendors" flag). Before this fix, 2 of 5 vendors (Zuercher's inline base64, the
modern P2C/Buncombe ImageId URL) carried a real mugshot through to
raw['jail_booking']['mugshot'], and the other 3 silently carried none, even
though 2 of those 3 genuinely publish one:
  - Citizen Connect (Henderson NC): every booking card's HTML already embeds
    a per-inmate `<img class='booking-mugshot' src='https://ssmugshots.blob.
    core.windows.net/images/<agency>-<nameid>-<bookingid>-...-Mugshot-1.jpg'>`
    -- live-verified 179/180 real photo URLs across the full roster (1 row
    fell back to the vendor's own literal "NoMugshot.jpg", which is filtered
    out rather than kept as if it were a photo). Free: the URL is already in
    the fetched HTML, no extra request.
  - Tyler New World (Gaston NC): the grid's own "Photo" column (previously
    discarded -- `_strip_tags` on an `<img>`-only cell strips it to "") is a
    real, directly-fetchable `/Inmate/Photo/<id>?type=Search` path -- live-
    verified on 2 ids returning distinct real JPEGs (25,879 / 32,308 bytes),
    no session or auth needed. Free: also just a URL, no extra request.
  - CentralSquare P2C jqGrid (Cleveland NC): THE ONE REAL EXCEPTION. This
    legacy ASP.NET WebForms system has no direct per-row image URL at all --
    live-verified the only way to reach a mugshot is to replay the grid's own
    "select row" postback (GET page for __VIEWSTATE, POST the grid query to
    seed server-side session state, POST the postback with the row's `invid`,
    then GET the now-session-scoped `Mug.aspx`) and that produces a real,
    distinct JPEG per row (confirmed on 5 rows, 5 different byte counts).
    That is 2+ extra requests PER INMATE against one small county host for
    ~300 rows every run -- the same "rude and slow" math the Tyler detail
    page already solved below by deferring to on-demand hydration. The fetch
    helper (`_fetch_p2c_jqgrid_mugshot`) is built and exposed for that same
    selective-hydration pattern (only rows that actually matched an owner),
    not called eagerly from `_fetch_p2c_jqgrid`.

RESOLVED 2026-11-05 — Spartanburg SC: the legacy PHP roster this note used to
describe (host dead since before 2026-03-08) has been superseded. The Sheriff's
Office quietly migrated onto a new static-HTML gallery at
mugshots.spartanburgsheriff.org/bookings/, confirmed live and covered below
(vendor "spartanburg_mugshots") — this was the single biggest jail_booking gap
on the board (~13,854 estimated affected rows) before this fix.

The scraper follows the BaseScraper pattern with async fetch() returning
Iterable[Listing]. Uses curl_cffi (chrome impersonation) for systems that
fingerprint-block plain httpx, and the shared http_client for rate limiting.

Robots.txt: These are public-records APIs, not crawlable web pages. The
endpoints are the same JSON XHRs the public search UIs use. We check
robots.txt on the host anyway and fail-closed if disallowed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# County roster configurations
# ---------------------------------------------------------------------------
# (state, county, vendor, target)
# vendor: "p2c_centralsquare" | "p2c_jqgrid" | "zuercher" | "citizen_connect"
#         | "tyler_inmate_inquiry"
# target: Zuercher subdomain, P2C base URL, "host|listId" for modern P2C,
#         "AgencyID|JMSAgencyID" for Citizen Connect, or the app base URL for
#         Tyler New World InmateInquiry.

ROSTERS: list[tuple[str, str, str, str]] = [
    # Buncombe NC — CentralSquare P2C modern (policetocitizen.com SPA)
    # Verified live 2026-07-01: 542 in custody. XSRF token handshake.
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),

    # Cleveland NC — CentralSquare P2C jqGrid (classic ASP.NET)
    # Verified live: jqGrid JSON endpoint at /jqHandler.ashx?op=s
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),

    # Cherokee SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),

    # Anderson SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),

    # Laurens SC, Zuercher Portal (build queue J-03, 2026-09-20)
    # Verified live 2026-09-20: 181 in custody; DOB blank on this tenant.
    ("SC", "Laurens", "zuercher", "laurens-911-sc"),

    # Oconee SC, Zuercher Portal (build queue J-04, 2026-09-20)
    # The sheriff's inmate-search page links straight to this tenant.
    # Verified live 2026-09-20: 183 in custody, DOB on every row.
    ("SC", "Oconee", "zuercher", "oconee-so-sc"),

    # Pickens SC, Zuercher Portal (found 2026-10-22: subdomain-pattern discovery sweep
    # against the project's own 18-county footprint, following the jail_bookings identity
    # fix). Verified live: 339 in custody. DOB is blank on this tenant (same as Laurens).
    ("SC", "Pickens", "zuercher", "pickens-so-sc"),

    # Union SC, Zuercher Portal (same discovery sweep). Verified live: 102 in custody. This
    # tenant redacts DOB and substitutes Age in the same JSON key -- handled by the int/str
    # type check in _fetch_zuercher (see that function's own 2026-10-22 comment).
    ("SC", "Union", "zuercher", "union-so-sc"),

    # Henderson NC — Southern Software Citizen Connect
    # Verified live 2026-07-31: 182 in custody, full DOB on 182/182.
    ("NC", "Henderson", "citizen_connect", "HendersonCoNC|NC0450000"),

    # Polk NC — Southern Software Citizen Connect, same tenant family as Henderson (found
    # 2026-10-22: this exact adapter was already live in enrichment_jail_bookings.py's OWN
    # roster list since 2026-08-06 for the owner-cross-match signal -- just never ported to
    # THIS scraper, which is what actually creates jail_booking lead Listings. Re-verified
    # live 2026-10-22: 46 in custody.
    ("NC", "Polk", "citizen_connect", "PolkCoNC|NC0750000"),

    # Transylvania NC — same tenant family. Re-verified live 2026-10-22: 71 in custody.
    ("NC", "Transylvania", "citizen_connect", "TransylvaniaCoNC|NC0880000"),

    # Burke NC — CentralSquare P2C modern, same vendor as Buncombe (found/re-verified same
    # pass). Re-verified live 2026-10-22: 193 in custody.
    ("NC", "Burke", "p2c_centralsquare",
     "https://morgantonpdnc.policetocitizen.com|342"),

    # Lincoln NC — CentralSquare P2C jqGrid, same vendor as Cleveland (found/re-verified same
    # pass; the vendor itself typos its own agency as "Lncoln County" -- matched on host, not
    # agency string, same note as the enrichment module that found this first). Re-verified
    # live 2026-10-22: 168 in custody.
    ("NC", "Lincoln", "p2c_jqgrid", "http://p2c.lincolnsheriff.org"),

    # Rutherford NC — Southern Software Citizen Connect, same tenant family as Henderson/Polk/
    # Transylvania (found 2026-10-22: the county's own official site, rutherfordcountync.gov,
    # links "Current Inmates" straight at this exact vendor URL -- real site research, not
    # guessing, after Spartanburg/McDowell/Mitchell came up genuinely empty the same pass).
    # Verified live: 195 in custody, full DOB on 195/195. No JMSAgencyID needed -- the vendor
    # accepts a blank value; its ORI shows up in the response as NC0810000.
    ("NC", "Rutherford", "citizen_connect", "RutherfordCoNC|NC0810000"),

    # Gaston NC — Tyler New World InmateInquiry (replaces the retired
    # newworld.aegis.webportal InmateInquiry.aspx, which now 302s away).
    # Verified live 2026-07-31: 695 in custody, full DOB on 695/695.
    ("NC", "Gaston", "tyler_inmate_inquiry",
     "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),

    # York SC — standalone ASP.NET WebForms DataGrid (no vendor-product match; a county-built
    # system, not one of the 4 vendors above). No source existed for York at all before this
    # (gap_matrix: jail_booking/jail_booking_new/atty_obituary_match all "no source known").
    # Verified live 2026-10-22: 432 in custody total; this fetcher covers the first ~150
    # (10 pages) -- see _fetch_york_webforms's own docstring for the pagination-depth scope.
    ("SC", "York", "york_webforms",
     "https://inmatesinjail.yorkcountygov.com/detentioncenter/inmatesinjail.aspx"),

    # Sumter SC — CentralSquare Zuercher/P2C cloud host variant (found via live web research
    # 2026-11-05, verified real inmate data loads). SAME underlying API family as this file's
    # "zuercher" vendor (api/portal/inmates/load) but hosted on CentralSquare's newer
    # "centralsquarecloudgov.com" cloud domain ("Public Safety Suite Pro") instead of the legacy
    # zuercherportal.com domain every other zuercher entry above uses. Verified live via browser
    # network capture: POST to /api/portal/inmates/load returned 483 total records, arrest dates
    # as recent as 11/04/2026, e.g. ATKINSON, DEMARCUS (shared Sumter-Lee Regional Detention
    # Center -- carries both Sumter and Lee County SC warrants). Found via sumtersheriff.org's
    # Detention Center page -> "Police to Citizens Portal" link.
    # PARTIALLY FIXED 2026-11-05: the full-base-URL problem is resolved -- _fetch_zuercher() now
    # accepts a string starting with http(s):// as-is instead of forcing zuercherportal.com -- but
    # this tenant turned out to ALSO need a CSRF handshake the legacy zuercherportal.com tenants
    # never do, so this entry still returns 0 rows until that's built. What's confirmed so far
    # (live-debugged via real browser + manual fetch() calls against the live site, not guessed):
    #   - a GET to /api/portal/inmates/init (same host) must happen first -- it both seeds the
    #     session AND returns the page's jail_agencies list
    #   - the CSRF token itself is NOT delivered as a normal Set-Cookie header (checked -- only
    #     AWSALB/AWSALBCORS come back that way); it shows up in document.cookie as XSRF-TOKEN
    #     regardless, so something in the app's own JS sets it client-side -- a real browser
    #     session (not curl_cffi) may be unavoidable here, or there's a specific prior request that
    #     triggers the Set-Cookie that a plain GET /, GET /home, GET init alone didn't trigger in
    #     testing
    #   - the header name is X-CSRFToken (Flask-WTF's default, NOT Angular's default X-XSRF-TOKEN
    #     -- this backend is Flask/gunicorn, confirmed via response headers, unlike the legacy
    #     tenants' stack) -- sending X-XSRF-TOKEN gets "CSRF token is missing" (400); X-CSRFToken
    #     with a real token gets PAST that check but then 500s with no error detail, even replayed
    #     from inside the live page's own JS context (same-origin, real cookies, fresh token each
    #     time) -- so the remaining bug is NOT a client-replication mismatch, it's either a
    #     body-shape difference this host's backend is stricter about, or a second undiscovered
    #     requirement. Next step: capture the app's OWN actual request body (its own code never
    #     hit this error) via a script-injected fetch/XHR intercept from page load, not a
    #     reload-and-guess loop.
    ("SC", "Sumter", "zuercher", "https://portal-sc-sumter-pd.centralsquarecloudgov.com"),

    # Duplin NC — Southern Software Citizen Connect, same tenant family as Henderson/Polk/
    # Transylvania/Rutherford above (found via live web research 2026-11-05, verified real inmate
    # data loads). AgencyID=DuplinCoNC, JMSAgencyID=NC0310000 (matches Duplin's real NC county-31
    # ORI). Verified with the real 2-step handshake and cross-checked against Henderson
    # (known-good) and a bogus AgencyID (known-bad): Duplin's response shape matched Henderson's,
    # not the bogus-ID shape. Sample: HANNAH ELIZABETH BARNETTE, charges BREAKING AND OR ENTERING
    # / LARCENY AFTER BREAK/ENTER, Arresting Agency DUPLIN - NC0310000, Arrest Date 09/14/2026,
    # Bond $75,000.
    ("NC", "Duplin", "citizen_connect", "DuplinCoNC|NC0310000"),

    # Rowan NC — CentralSquare P2C modern (policetocitizen.com SPA), same vendor as Buncombe/Burke
    # above (found via live web research 2026-11-05, verified real inmate data loads). Host
    # rowancountync.policetocitizen.com, listId 465 -- confirmed by driving a real browser session
    # (Home -> Inmates -> Inmates/Catalog) and capturing its own calls to /api/Agency/465,
    # /api/Module/465, /api/Inmates/SearchCriteria/465 and POST /api/Inmates/465, all consistently
    # using listId 465. Verified live: {"Total":318,...}, e.g. LAQUERIUS MARKESE MARTIN (arrested
    # 11/5/2026, ASSAULT BY POINTING A GUN, $30,000 bond, docket 26CR403105-790).
    ("NC", "Rowan", "p2c_centralsquare",
     "https://rowancountync.policetocitizen.com|465"),

    # New Hanover NC — CentralSquare P2C jqGrid (classic ASP.NET WebForms), same vendor as
    # Cleveland/Lincoln above (found via live web research 2026-11-05, verified real inmate data
    # loads). Base http://p2c.nhcgov.com/p2c (https also works identically). Verified with this
    # file's own _fetch_p2c_jqgrid handshake: GET /jailinmates.aspx seeds the session, POST
    # /jqHandler.ashx?op=s returns real paginated JSON, 482 total in custody. Sample: ELIAS GABY
    # ACHI (booked 10/06/2026, DOMESTIC VIOLENCE PROTECTIVE ORDER VIOLATION), COLOGENO KOBIA ALLEN
    # (booked 11/04/2026, POSSESSION OF STOLEN GOODS/PROPERTY) -- full DOB on every row, same as
    # this vendor elsewhere.
    ("NC", "New Hanover", "p2c_jqgrid", "http://p2c.nhcgov.com/p2c"),

    # Colleton SC — Zuercher Portal, {county}-so-{state} subdomain pattern (found via live web
    # research 2026-11-05, verified real inmate data loads). Verified by loading the live Inmates
    # page itself: "Viewing 1-51 of 86 results", e.g. AIKEN, JERRY JERMAINE - FTP Bench Warrant,
    # Arrest Date 12/23/2024. Root page is the standard Zuercher Angular SPA shell ("PUBLIC SAFETY
    # SUITE PRO", CentralSquare branding). CAVEAT: a cold, cookie-less POST straight to
    # api/portal/inmates/load returned {"status":500} during verification -- this tenant's SPA
    # appears to seed session state via prior GETs first. The already-live zuercher counties
    # above all succeed with this file's current direct-POST _fetch_zuercher, so this may just
    # work too, but if Colleton ever comes back empty/500 in the logs, this is the first thing to
    # check (replicate an init-GET sequence before the POST).
    ("SC", "Colleton", "zuercher", "colleton-so-sc"),

    # Hoke NC — Zuercher Portal, {county}-so-{state} subdomain pattern (found via live web
    # research 2026-11-05, verified real inmate data loads). Verified live: "Viewing 1-51 of 130
    # results", e.g. ABARCA-PEREZ, FORTINO - DWI, Arrest Date 09/25/2026; BAKER, JERMAINE
    # MONTREAL - Sentenced, Serving 82 days. Landing page labeled "Zuercher Portal" with the
    # identical CentralSquare shell/nav seen on Colleton, confirming same vendor/product.
    ("NC", "Hoke", "zuercher", "hoke-so-nc"),

    # Berkeley SC — Southern Software Citizen Connect, same tenant family as Henderson/Duplin
    # above (found via live web research 2026-11-05, verified real inmate data loads). AgencyID
    # is exactly "BerkelyCoSC" -- note the real-world misspelling (missing the second "e" in
    # Berkeley), confirmed in two separate link instances on sheriff.berkeleycountysc.gov's own
    # "Inmate Lookup" link (that .gov domain 403s a plain curl/WebFetch WAF check -- verify with a
    # real browser instead). Verified live: 451 real inmates in a rendered DataTables page, e.g.
    # Jonathan Colby Adkins, Daniel Filippone Agold, with arresting-agency ORI codes BERKELEY -
    # SC0080000, GOOSE CREEK - SC0080300, SUMMERVILLE - SC0180200.
    ("SC", "Berkeley", "citizen_connect", "BerkelyCoSC|SC0080000"),

    # Lexington SC — CentralSquare P2C modern (policetocitizen.com SPA), same vendor as
    # Buncombe/Burke/Rowan above (found via live web research 2026-11-05, verified real inmate
    # data loads). Host lexingtonsheriffsc.policetocitizen.com, found via lex-co.sc.gov ->
    # Sheriff's Department -> lexingtonscsheriff.com -> "Inmate Search". Verified live by clicking
    # "Inmate Inquiry": catalog reported "511 Found", real current inmates with arrest dates of
    # 11/04/2026-11/05/2026, e.g. STROTHER, JUNE arrested 11/05/2026. An older domain,
    # jail.lexingtonsheriff.net, carries a valid cert for this same sheriff's office but currently
    # 503s/fails to load -- looks deprecated, not the live tenant.
    # RESOLVED 2026-11-05: real listId is 576, confirmed live via a real browser session's own
    # network calls after clicking through Home -> "Inmate Inquiry" (the SPA's actual route is
    # /Inmates, not the locale-prefixed /en/Inmates -- that 404s here, same gotcha as Buncombe)
    # -- captured /api/Agency/576 calls, then cross-checked by hitting the tenant's own
    # host-relative, no-auth /api/Agency/InitialSettings, which answers {"AgencyId":576,...}
    # directly. _fetch_p2c_centralsquare now also auto-discovers via that same endpoint whenever
    # a target carries no explicit listId, instead of silently defaulting to Buncombe's "23".
    ("SC", "Lexington", "p2c_centralsquare",
     "https://lexingtonsheriffsc.policetocitizen.com|576"),

    # Harnett NC — Southern Software Citizen Connect, same tenant family as Henderson/Duplin
    # above (found via live web research 2026-11-05, verified real inmate data loads). AgencyID=
    # HarnettCoNC, linked from harnettsheriff.com's Detention Center page as "Inmate Population
    # Search". Verified live via real browser render: Total Inmates 295, e.g. Lisa Ann Acevedo
    # (48/W/F), Booked 06/27/2026, charge MURDER, Arresting Agency HARNETT - NC0430000.
    # CAVEAT: a plain curl/script GET to this URL hits an "Access Denied -- Automated traffic
    # detected" reCAPTCHA-style wall (confirmed -- curl blocked, real browser did not; no CAPTCHA
    # was solved or clicked through to get this result). This file's existing
    # _fetch_citizen_connect already uses curl_cffi chrome impersonation, which may or may not be
    # enough to pass -- if Harnett comes back empty, this bot-detection layer is why.
    ("NC", "Harnett", "citizen_connect", "HarnettCoNC|NC0430000"),

    # Anson NC — Southern Software Citizen Connect, same tenant family as Henderson/Duplin/
    # Harnett above (found via live web research 2026-11-05, verified real inmate data loads).
    # AgencyID=AnsonCoNC, linked from the county's own Jail page (co.anson.nc.us/303/Jail) as
    # "Anson County Jail Booking Information". Verified live: Total Inmates 69, e.g. Emilio
    # Francisco Alston (DOB 12/11/1990) Booked 07/25/2025, Brandon Lamont Bennett (DOB 12/28/1988)
    # Booked 10/22/2026, Arresting Agency ANSON - NC0040000. NOTE this tenant does NOT show up in
    # Southern Software's own public agency-search directory ("No agency matches that search") --
    # it is nonetheless live and real at this exact county-linked URL; don't rely on that vendor
    # directory alone to rule a county out.
    ("NC", "Anson", "citizen_connect", "AnsonCoNC|NC0040000"),

    # Pasquotank NC — Zuercher Portal, {county}-911-{state} subdomain pattern (the {county}-so-
    # {state} variant is NXDOMAIN here) (found via live web research 2026-11-05, verified real
    # inmate data loads). Page title "Zuercher Portal -- Joint Pasquotank and Camden County and
    # Elizabeth City PD Portal" (serves Albemarle District Jail). Verified live, no login: 177
    # total records, e.g. "Allen, Ladir Amarion," Booked 06/29/2026, charge 14-87 ROBBERY-ARMED,
    # bond $250,000 secured. The live page's own XHR payload (captured via network interception)
    # matches this file's existing _fetch_zuercher body shape exactly (flat JSON: name/race/sex/
    # cell_block/held_for_agency/in_custody/paging/sorting) -- confirms that shape is current and
    # correct, not the bracket-notation guess that 500s on this backend. Bonus: this portal is
    # joint, so it likely also covers Camden County NC bookings if that's ever useful.
    ("NC", "Pasquotank", "zuercher", "pasquotank-911-nc"),

    # Cabarrus NC — CentralSquare P2C jqGrid (classic ASP.NET/jqGrid; this instance's own footer
    # still reads "powered by Superion's P2C engine", Superion being the pre-merger predecessor
    # brand of CentralSquare -- same engine lineage as Cleveland/Lincoln above) (found via live
    # web research 2026-11-05, verified real inmate data loads). Base
    # onlineservices.cabarruscounty.us/p2c, found via cabarruscounty.us/Services/Inmate-Lookup,
    # which 302-redirects straight there. Loads a full roster immediately, no search/login: "1 -
    # 10 of 510 Results" at check time, e.g. Abreu, Reinaldo (W/M/37), TRAFFIC IN AMPHETAM/METHAM,
    # Arrest Date 05/27/2026; Adams, Gaines D Marion (B/M/21), MURDER-1ST DEGREE.
    ("NC", "Cabarrus", "p2c_jqgrid", "https://onlineservices.cabarruscounty.us/p2c"),

    # Iredell NC — CentralSquare P2C jqGrid (classic ASP.NET/jqGrid; this instance's footer
    # explicitly reads "powered by CentralSquare's P2C engine") (found via live web research
    # 2026-11-05, verified real inmate data loads). County hosts its own instance at
    # p2c.iredellcountync.gov (Sheriff Darren E. Campbell branding). Loads a full live roster
    # immediately, no search/login: e.g. Adams, Roy Lee (B/M/64), FAIL TO REGISTER-SEX OFFENDER,
    # Arrest Date 11/04/2026; Alexander, Noel Ethan (B/M/26), ASSAULT INFLICT SERIOUS INJURY TO
    # LEO/PROBATION/ETC, Arrest Date 10/05/2025.
    ("NC", "Iredell", "p2c_jqgrid", "https://p2c.iredellcountync.gov"),

    # Kershaw SC — Zuercher Portal, same subdomain pattern as Cherokee/Anderson/Laurens/Oconee/
    # Pickens/Union above (found via live web research 2026-11-05, verified real inmate data
    # loads). Verified by direct POST (identical request shape to this file's live
    # _fetch_zuercher) to kershaw-so-sc.zuercherportal.com/api/portal/inmates/load: HTTP 200,
    # total_record_count=133, e.g. name="ALTMAN, TERRY JAMES".
    ("SC", "Kershaw", "zuercher", "kershaw-so-sc"),

    # Alamance NC — CentralSquare P2C jqGrid (classic ASP.NET build), same vendor as Cleveland/
    # Lincoln/Cabarrus above (found via live web research 2026-11-05, verified real inmate data
    # loads). Base apps.alamance-nc.com/p2c, linked directly as "Inmate List" from
    # sheriff.alamancecountync.gov -> alamancecountync.gov/public_safety/sheriffs_office. Verified
    # with this file's own _fetch_p2c_jqgrid handshake: GET /jailinmates.aspx seeds the session,
    # POST /jqHandler.ashx?op=s returned 339 real rows, e.g. ADAMS/MARTY/LEE, DOB 12/17/1964,
    # ASSAULT WITH DEADLY WEAPON, arrest date 08/11/2026; AGUALO/JUSTIN/CRUZ.
    ("NC", "Alamance", "p2c_jqgrid", "https://apps.alamance-nc.com/p2c"),

    # Randolph NC — standalone ASP.NET WebForms system (no vendor-product match; a county-built
    # system, same category as York SC above). Found via the task brief, confirmed live 2026-11-05:
    # the sheriff's own confinedinmatesbydate.aspx answers a plain GET with no params, no auth, no
    # CAPTCHA, and no postback needed -- the WHOLE roster is already in that one response (unlike
    # York, which needs 10 __doPostBack page-turns for partial coverage). Verified live across 3
    # separate fresh fetches this session: 343 in custody every time, e.g. BROWN, JEFFREY WADE,
    # Incarceration Date/Time 11/05/26 09:44:44, charge BREAK/ENTER MOTOR VEH, docket 26CR446687-750,
    # $15,000 bond, Arrest Agency ASHEBORO POLICE, Jail POD Location "L-Pod CLOSE SECURITY (MALE)".
    # Every record carries a real vendor-issued numeric id (the page's own client-side toggle()
    # argument, also reused as VineLink's offenderID query param) -- captured as detail_id, same role
    # Tyler New World's detail_id plays for _booking_identity()'s preference order. No DOB is
    # published, but Incarceration Date/Time is, on 343/343 rows (reformatted to a pattern
    # _parse_date() already accepts -- see _randolph_dt's docstring).
    ("NC", "Randolph", "randolph_webforms",
     "https://legacyweb.randolphcountync.gov/sheriff/confinedinmatesbydate.aspx"),

    # Davidson NC -- standalone dhtmlxGrid AJAX handler (county-built, no vendor match; found via
    # live web research 2026-11-05, verified real inmate data loads). The bare "?dynamic=100" param
    # from the earlier research caps the response at 100 rows despite the XML root misleadingly
    # still reporting the true total_count -- this target is the no-query-string form, which
    # returns the full roster (311 live-verified). Also hydrates every row's per-inmate detail page
    # for charge/arrest_date/court_date/race/bond/agency (confirmed cheap: full roster + all detail
    # pages in 2.4-4.1s live). Sample: STEWARD-APONTE, ASHLEY, book_id 26-003404, POSSESS STOLEN
    # MOTOR VEHICLE, court 11/16/2026.
    ("NC", "Davidson", "davidson_dhtmlx",
     "http://www2.co.davidson.nc.us/DCInmates/handler/inmate_data.ashx"),

    # Cumberland NC -- standalone ASP.NET WebForms search (no vendor-product match; a
    # county-built system, same class as York SC above). Confirmed live 2026-11-05:
    # https://cumberlandsheriffnc.gov:8000/active_inmates/Inmates.aspx (non-standard port
    # 8000), title "Active Inmate Search". No full-roster GET exists -- swept the alphabet
    # (LastName starts-with A-Z) instead, same "iterate a few queries" shape as this
    # project's Greenville SC precedent. Verified live: two independent full A-Z sweeps
    # both returned 757 current in-custody records, 757/757 with a real vendor book_id
    # (zero synthesized-hash rows needed), e.g. book_id 301938 -> SHAW, JOSEPH, arrested
    # 2026-10-30.
    ("NC", "Cumberland", "cumberland_webforms",
     "https://cumberlandsheriffnc.gov:8000/active_inmates/Inmates.aspx"),

    # Pitt County NC -- standalone ASP.NET WebForms DataGrid (county-built, no vendor-
    # product match; same family as York SC above). Found via live web research
    # 2026-11-05, confirmed live: apps.pittcountync.gov/apps/detention/detainee/, the
    # page's own UI text says "Leave fields blank to retrieve all active detainees."
    # Verified live: 479 active detainees, full DOB and a real booking number on
    # 479/479 rows (zero dedupe collisions), e.g. DONNIE DEVON ADAMS JR, DOB
    # 04/24/1984, booking #249219.
    ("NC", "Pitt", "pitt_webforms",
     "https://apps.pittcountync.gov/apps/detention/detainee/"),

    # Florence SC -- standalone "TheSheriffApp.com" / OCV platform build (Next.js app; no
    # vendor-product match in this file, same "bespoke, county-built" situation as York SC's
    # york_webforms). Found via live browser network-trace capture 2026-11-05: the public
    # page's own POST to /api/internal/guest-session 401s under curl_cffi and turned out
    # unneeded -- GETting /inmatesearchfeed with header RSC:1 (plus a dummy _rsc query value
    # and limit=250) returns the roster directly as a Next.js RSC "flight" stream instead of
    # the full 3MB HTML page. Verified live: 627 in custody, 3 pages (250+250+127), 100%
    # resolved to a real per-booking Inmate ID (0 synth-hash fallback), 0 arrest_date values
    # _parse_date() failed to parse. Sample: CANNON, TEYON RAJAE DEQUAN, Inmate ID 49272,
    # Booking Date 11/05/2026 10:31:00, DISCHARGING FIREARM IN THE CITY LIMITS / BREACH OF
    # PEACE AGGRAVATED IN NATURE, Arresting Agency FLORENCE City - SC0210100.
    ("SC", "Florence", "sheriffapp_ocv", "https://www.fcso.org/inmatesearchfeed"),

    # Durham NC -- standalone ASP.NET WebForms "Inmate Population Search" (IPS), no
    # vendor-product match (county-built system, same category as York SC above) (found
    # via live web research 2026-11-05, verified real inmate data loads). IMPORTANT: a
    # bare GET only shows the page's "Last 24 Hours" default filter (30 records at check
    # time) -- _fetch_durham_webforms explicitly replays the page's own
    # ddlDateListing postback with value "0" ("Incarcerated") to get the true current
    # population. Verified live: 531 in custody, stable across 3 separate fresh runs,
    # 510/531 with a unique real court-docket number (used for dedupe identity per this
    # build's brief); the remaining 21 are federal-detainer/no-court-case holds with a
    # vendor "[N/A]" docket, which fall back to this file's standard name+date hash. No
    # DOB/age/race/sex published on this system. e.g. ADAMS, ZION ANTHONY, confined
    # 10/14/2026, BREAK/ENTER TERRORIZE/INJURE (+ 1 other charge), docket 26CR427267.
    ("NC", "Durham", "durham_webforms", "https://www2.dconc.gov/sheriff/ips"),

    # Lee County NC — Southern Software DCN (Detention Center Network), a self-hosted DevExpress
    # ASPxGridView WebForms product -- a DIFFERENT Southern Software product from this file's own
    # Citizen Connect vendor (no AgencyID/JMSAgencyID params, hosted on the county's own domain,
    # confirmed via /DXR.axd resource handler + the grid's own "inmates_aspx_gvInmates" cookie
    # name). Found via live web research 2026-11-05. Verified live 2026-11-05: 136/136 in custody
    # fetched via the grid's own "Export" postback (plain WebForm_DoPostBackWithOptions, NOT the
    # grid's fragile ASPxCallback paging protocol -- see _fetch_dcn_export's own docstring for why),
    # e.g. ABRAMS, MESSIAH RYSHAUN (21/B/M), admitted 08/21/2026, docket 26CR387713-520,
    # POSSESSION OF FIREARM BY FELON; confirmed repeatable across 3 separate live runs same day.
    ("NC", "Lee", "dcn_export", "https://dcn.leecountync.gov/DCN/Inmates"),

    # Darlington SC — DCN (county-built DevExpress ASPxGridView system, not a vendor-product
    # match among this file's other 6 fetchers; same product family as other DCN-branded county
    # jail sites). Found via live web research 2026-11-05, verified real inmate data loads. Base
    # http://bookings.darlingtonsheriff.org/dcn, entry at /dcn/ ("W.Glenn Campbell Detention
    # Center"). The on-screen grid at /dcn/inmates paginates 100/page via an opaque DevExpress AJAX
    # callback; rather than reverse-engineer that, this fetcher replays the grid's own "Export"
    # button as a classic ASP.NET WebForms postback (confirmed via a real browser's own
    # HTMLFormElement.submit() call, see _fetch_darlington_dcn's own docstring) and parses the
    # resulting .xlsx attachment directly -- no pagination needed at all. Verified live 2026-11-05:
    # 206 total in custody (matches the page's own "Page 1 of 3 (206 items)" pager), e.g. ACRES,
    # MELISSA LYNN (age 37, W/F, admitted 11/03/2026, FAIL TO APPEAR SHOPLIFTING*); AGBO, ADRON
    # LASHAWN (age 23, B/M, MURDER). 100/206 rows additionally carry a real vendor-issued booking
    # id (see docstring); the rest fall through to the name+arrest_date hash fallback, safe here
    # since Admit Date is on 206/206 rows and a live check found zero (last, first, arrest_date)
    # collisions across the full roster.
    ("SC", "Darlington", "darlington_dcn", "http://bookings.darlingtonsheriff.org/dcn"),

    # Orange NC -- bespoke Wix-embedded periodically-republished PDF (no vendor-product
    # match; no live searchable roster database exists for this county at all). Found
    # via live web research 2026-11-05: the Sheriff's "current detainees" page embeds a
    # "Daily In Custody Report by Facility" PDF through a Wix pdf-flipbook viewer whose
    # underlying file URL changes on every republish, so the target here is the STABLE
    # detainees page, not a PDF url -- _fetch_orange_pdf_viewer discovers the live PDF
    # url itself from that page's own markup on every run, and verifies it against the
    # report's own in-content generation timestamp before trusting it. Verified live:
    # 105 in-custody records, e.g. ALEJANDRO-MILIAN, SERGIO JOSUE (booked 08/06/2026,
    # Robbery / Armed, docket 26CR369643, bond $1,000).
    ("NC", "Orange", "orange_pdf_viewer", "https://www.ocsonc.com/detention/current-detainees"),

    # Richland SC — standalone ASP.NET MVC + Kendo UI grid "ASGDC Public Web Jail Viewer"
    # (no vendor-product match; footer-credited "Executive Information Services, Inc.")
    # (found via live web research 2026-11-05, verified real inmate data loads). No bulk
    # query exists -- per-surname search only, exact-match LastName LIKE with '%' accepted
    # as a real wildcard (live-verified: LastName='A' returns 0, LastName='A%' returns 23).
    # One request per letter (A%..Z%) sweeps the FULL current roster, not a sample: live
    # sweep totalled 1055 unique bookings, zero duplicates, zero letters near the observed
    # 200-row server cap (busiest M% at 106). Sample: SMITH, ANTHONY, BookingNumber
    # 1752112, booked 05/22/2025; HALLMAN, MICHAEL, BookingNumber 202601758, booked
    # 11/2026 (most recent at verification time). BookingNumber is a real per-booking id,
    # present on 1055/1055 rows checked -- carried as book_id.
    ("SC", "Richland", "richland_kendo", "https://jail.richlandcountysc.gov"),

    # Jasper SC — Esri ArcGIS Online Hosted Feature Service ("PrisonerDataTable", layer index 3 on
    # Map2/FeatureServer; layer 0 "Test" is an unrelated empty placeholder) -- a bespoke, county-
    # built system, not a match for any of the 6 vendors above. No auth, plain REST+JSON: GET
    # .../FeatureServer/3/query?where=1=1&outFields=*&f=json returns the whole 112-row table in
    # one request (maxRecordCount=2000, confirmed via returnCountOnly that 112 is the TRUE total,
    # not a truncated page; x-cache:TCP_MISS confirmed this is a live, non-cached round trip).
    # CAVEAT -- STALE FEED, re-confirmed live 2026-11-05 (corrects an earlier 2026-08-22 finding
    # that was itself off by exactly one year): every one of the 112 rows carries
    # InmateInJail='Y', including rows whose own ReleaseDate is more than a year in the past
    # (e.g. BOLES, RODRICK ANTON -- ReleaseDate 2025-04-10, still flagged 'Y'), and the newest
    # CapturedWhen in the WHOLE table is 2025-08-22 10:16:44 -- this feed has not advanced in
    # roughly 440 days. Treat every record from this source as a POSSIBLY STALE in-custody claim,
    # not a live one, until CapturedWhen starts moving again (same spirit as this file's Sumter/
    # Lexington caveat comments above). No DOB/age/charge data exists in this table at all
    # (OffenseCode/CrimeClass/OffenseType/Counts/PhotoPath are null on every live row) -- this
    # source's only real value today is name + demographics + a real per-row dedupe id
    # (OBJECTID, 100% populated/unique across all 112 rows, used as book_id).
    ("SC", "Jasper", "jasper_arcgis",
     "https://services3.arcgis.com/oJaBluQKw5aLHpzj/arcgis/rest/services/Map2/FeatureServer/3/query"),

    # Spartanburg SC -- bespoke static-HTML booking gallery (county-built, no vendor match;
    # found via live web research 2026-11-05). This was the single biggest jail_booking gap
    # on the board (~13,854 estimated affected rows) -- the module docstring previously said
    # this county's portal was offline; the Sheriff's Office has since migrated onto this new
    # static-HTML gallery, confirmed genuinely live (page changed between two runs 15 minutes
    # apart: 92 then 91 rows). 100% DOB coverage, 100% unique real vendor booking-number ids.
    # Sample: Michael Vladimir Anderson, DOB 01/05/92, TRESPASS INTO ENCLOSED PLACE, booking
    # 26-09607, arrested 11/03/2026 09:52.
    ("SC", "Spartanburg", "spartanburg_mugshots", "https://mugshots.spartanburgsheriff.org/bookings/"),
]

# Southern Software hosts every Citizen Connect tenant off one origin; the
# AgencyID query param selects the agency and seeds the PHP session.
CITIZEN_CONNECT_BASE = "https://cc.southernsoftware.com"

# Charge-string cap. Was 300, which truncated multi-charge rosters mid-charge
# (a booking can list 10+ counts). 2000 keeps the full charge list.
_CHARGE_CAP = 2000

# Generational suffixes to drop before deciding which token is the surname.
_NAME_SUFFIXES = frozenset(
    {"JR", "SR", "II", "III", "IV", "V", "JUNIOR", "SENIOR"})

# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------

def _norm_alpha(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _split_comma_name(name: str) -> tuple[str, str] | None:
    """'Smith, John Michael' -> ('SMITH', 'JOHN')."""
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    return last.strip().upper(), toks[0].strip().upper()


def _comma_middle(name: str) -> str:
    """'Smith, John Michael' -> 'MICHAEL'; '' when only one given name.

    Kept separate from `_split_comma_name` so that function's 2-tuple contract
    is unchanged. The middle is what enrichment_jail_bookings' same-county
    middle-name gate (2026-10-05) compares against the owner's middle initial;
    the 2026-10-02 live validation found 12.9% of same-county matches that had
    a middle on both sides were a different person.
    """
    if not name or "," not in name:
        return ""
    toks = name.partition(",")[2].strip().split()
    return toks[1].strip().upper() if len(toks) > 1 else ""


def _space_middle(name: str) -> str:
    """'MICHAEL LEE ABSHER' -> 'LEE' (the token after the given name, once
    trailing suffixes are dropped the same way `_split_space_name` does)."""
    toks = [t for t in re.split(r"\s+", (name or "").strip().upper()) if t]
    while len(toks) > 2 and _norm_alpha(toks[-1]) in _NAME_SUFFIXES:
        toks.pop()
    return toks[1] if len(toks) > 2 else ""


def _split_space_name(name: str) -> tuple[str, str] | None:
    """'MICHAEL LEE ABSHER' -> ('ABSHER', 'MICHAEL').

    Citizen Connect prints one flat "first middle last" string. The first token
    is the given name and the last the surname; trailing generational suffixes
    are dropped first so 'BOBBY DEAN ABEE JR' still yields ('ABEE', 'BOBBY').
    Compound surnames collapse to their final word, which is what the owner-name
    normalizer downstream does too.
    """
    toks = [t for t in re.split(r"\s+", (name or "").strip().upper()) if t]
    while len(toks) > 2 and _norm_alpha(toks[-1]) in _NAME_SUFFIXES:
        toks.pop()
    if len(toks) < 2:
        return None
    return toks[-1], toks[0]


def _strip_tags(fragment: str) -> str:
    """Flatten an HTML fragment to collapsed, entity-decoded plain text."""
    txt = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def _parse_date(s: str | None) -> datetime | None:
    """Parse common date formats from jail rosters."""
    if not s:
        return None
    s = str(s).strip()
    # ISO format (Zuercher/ArrestDate)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 5], fmt) if "T" in fmt else datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    # US format — bare dates, 24h stamps (Citizen Connect) and 12h stamps
    # (Tyler New World).
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Vendor fetchers — each returns a list of inmate dicts
# ---------------------------------------------------------------------------

async def _fetch_zuercher(subdomain: str) -> list[dict]:
    """Fetch current in-custody roster from a Zuercher Portal instance.

    API: POST https://{subdomain}.zuercherportal.com/api/portal/inmates/load
    Returns JSON with 'records' array. Each record has name, dob, charges,
    arrest_date.

    `subdomain` is normally a bare subdomain on the legacy zuercherportal.com
    domain (the original and still-majority case). FIXED 2026-11-05 (Sumter SC
    build): some tenants are migrated to CentralSquare's newer cloud host
    ("centralsquarecloudgov.com", branded "Public Safety Suite Pro") under a
    FULL base URL instead -- accept either: a string starting with http(s)://
    is used as-is (just appending the API path), anything else still gets the
    original {subdomain}.zuercherportal.com treatment. Request/response shape
    is identical across both hosts -- only the base URL differs.
    """
    from curl_cffi.requests import AsyncSession

    base = subdomain.rstrip("/") if subdomain.startswith(("http://", "https://")) \
        else f"https://{subdomain}.zuercherportal.com"
    url = f"{base}/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "name": "", "race": "all", "sex": "all", "cell_block": "all",
        "held_for_agency": "any", "in_custody": now,
        "paging": {"count": 2000, "start": 0},
        "sorting": {"sort_by_column_tag": "name", "sort_descending": False},
    }
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.zuercher_fail", subdomain=subdomain,
                    error=str(exc)[:120])
        return []

    for rec in recs:
        parts = _split_comma_name(rec.get("name") or "")
        if not parts:
            continue
        last, first = parts
        charges = rec.get("hold_reasons") or rec.get("charges") or ""
        if isinstance(charges, list):
            charges = "; ".join(str(x) for x in charges)[:_CHARGE_CAP]
        else:
            # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch
            # 17): hold_reasons is a vendor-formatted HTML string with
            # embedded `<br />` tags between multiple charges (live-sampled
            # 4 counties: 200/291 Cherokee, 361/538 Anderson, 113/193
            # Laurens, 161/203 Oconee rows carry literal "<br" in the raw
            # string) -- was never stripped, so most charge descriptions
            # shipped with literal HTML markup instead of a clean separator.
            charges = _strip_tags(str(charges))
        # Extra Zuercher fields (live-verified present): race/sex/cell_block,
        # a release date, and a mugshot ref. Carry them through for skip-trace.
        cell_block = rec.get("cell_block")
        release_date = (rec.get("release_date")
                        or rec.get("actual_release_date")
                        or rec.get("projected_release_date"))
        # Refine the otherwise-hardcoded in_custody flag from cell_block/release.
        if release_date:
            release_status = f"release_scheduled {release_date}"
        elif cell_block:
            release_status = f"in_custody cell_block={cell_block}"
        else:
            release_status = "in_custody"
        # FOUND 2026-10-04: `mugshot` (and its `image`/`photo` aliases) is
        # raw base64 JPEG bytes embedded directly in the JSON response (the
        # `/9j/...` prefix is the base64 encoding of a JPEG's SOI marker,
        # confirmed live across all 4 Zuercher counties) -- NOT a URL, and
        # nothing downstream decodes or renders it (grepped the whole repo:
        # no other reference to "mugshot" exists). Storing the bare base64
        # string made it unusable to any consumer expecting an <img src=...>
        # value; wrapping it as a proper data: URI makes it actually
        # renderable without changing where it's stored (still namespaced
        # under raw.jail_booking, not raw.images, since this is a photo of
        # a PERSON, not the property, and the dashboard's images.real
        # channel is documented as the property-photo channel).
        mugshot_b64 = rec.get("mugshot") or rec.get("image") or rec.get("photo")
        mugshot_uri = (
            f"data:image/jpeg;base64,{mugshot_b64}"
            if isinstance(mugshot_b64, str) and mugshot_b64
            else None
        )
        # FOUND 2026-10-22 (Pickens/Union SC discovery): Union's tenant redacts the real DOB
        # and substitutes the subject's AGE in the same `dob` JSON key -- but as a bare integer
        # (`"dob": 42`), never the "YYYY-MM-DD" string every other live Zuercher county sends.
        # Type is a clean, vendor-provided signal: pass a real date straight through; route an
        # int into `age` instead of storing an age value under a dob key (same redaction
        # precedent as Buncombe's p2c_centralsquare feed, which also substitutes Age for DOB).
        dob_raw = rec.get("dob")
        out.append({
            "last": last, "first": first,
            "middle": _comma_middle(rec.get("name") or "") or None,
            "dob": dob_raw if isinstance(dob_raw, str) else None,
            "age": dob_raw if isinstance(dob_raw, (int, float)) else None,
            "arrest_date": rec.get("arrest_date"),
            "charge": str(charges)[:_CHARGE_CAP],
            "race": rec.get("race"),
            "sex": rec.get("sex"),
            "cell_block": cell_block,
            "release_date": release_date,
            "mugshot": mugshot_uri,
            "release_status": release_status,
            # Rarely true (3/291 live on Cherokee, 0 elsewhere) but a real,
            # free field -- flagged rather than silently dropped so a
            # downstream owner-cross-reference pass can choose to exclude
            # minors rather than never knowing the flag existed.
            "is_juvenile": bool(rec.get("is_juvenile")),
        })
    log.info("jail_scraper.zuercher_ok", subdomain=subdomain, count=len(out))
    return out


async def _fetch_p2c_jqgrid(base: str) -> list[dict]:
    """Fetch current in-custody roster from a CentralSquare P2C jqGrid system.

    Handshake: GET /jailinmates.aspx to seed session cookie, then POST to
    /jqHandler.ashx?op=s with jqGrid parameters. Returns JSON with 'rows'
    array.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(f"{base}/jailinmates.aspx", timeout=20)
            r = await s.post(
                f"{base}/jqHandler.ashx?op=s",
                data={
                    "t": "ii", "_search": "false", "rows": "2000",
                    "page": "1", "sidx": "disp_name", "sord": "asc",
                },
                timeout=30,
            )
            rows = (r.json() or {}).get("rows") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_jqgrid_fail", base=base,
                    error=str(exc)[:120])
        return []

    for rw in rows:
        last = (rw.get("lastname") or "").strip().upper()
        first = (rw.get("firstname") or "").strip().upper()
        if not last or not first:
            continue
        out.append({
            "last": last, "first": first,
            "dob": rw.get("dob"),
            "arrest_date": rw.get("disp_arrest_date"),
            "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:_CHARGE_CAP],
            # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch
            # 17): live-verified every one of these is already on the same
            # jqGrid row this code already fetches, never read before.
            # book_id is a stable per-booking vendor id (better dedupe key
            # than name+county); middlename/age/race/sex are real skip-trace
            # identity signals.
            "middle": (rw.get("middlename") or "").strip().upper() or None,
            "age": rw.get("age"),
            "race": rw.get("race"),
            "sex": rw.get("sex"),
            "book_id": rw.get("book_id"),
            "agency": rw.get("disp_agency") or rw.get("agency"),
        })
    log.info("jail_scraper.p2c_jqgrid_ok", base=base, count=len(out))
    return out


async def _fetch_p2c_jqgrid_mugshot(base: str, book_id: str) -> str | None:
    """Fetch ONE inmate's mugshot from a classic CentralSquare P2C jqGrid system.

    Unlike every other vendor in this file, this system has no direct per-row
    image URL -- the photo is revealed only by replaying the live grid's own
    "select row" ASP.NET WebForms postback in a session that has already
    loaded that row, then GETting the now session-scoped Mug.aspx. Confirmed
    live 2026-10-14 on Cleveland NC: 5 different rows produced 5 real,
    differently-sized JPEGs this way.

    That is a GET (fresh __VIEWSTATE) + a POST (seed the session with the
    same full, sorted grid query `_fetch_p2c_jqgrid` already runs, so this
    book_id's position in it is reproducible) + a POST (the postback,
    selecting that position) + a GET (the photo) -- 4 requests for ONE photo.
    Doing that for an entire ~300-row roster every run would multiply this
    scraper's request volume against one small county host by ~300x, the
    same "rude and slow" math Tyler's `_fetch_tyler_detail` below already
    exists to avoid. So this is NOT called from `_fetch_p2c_jqgrid` --
    it is exposed standalone for selective, matched-row-only hydration
    (same pattern as `_hydrate_tyler_hits` in enrichment_jail_bookings.py).

    Returns a `data:image/jpeg;base64,...` URI (consistent with how the
    Zuercher vendor's own inline base64 mugshot is stored), or None.
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/jailinmates.aspx", timeout=20)
            body = r.text or ""

            def _hidden(name: str) -> str:
                m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', body)
                return m.group(1) if m else ""

            viewstate = _hidden("__VIEWSTATE")
            viewstategen = _hidden("__VIEWSTATEGENERATOR")
            eventvalidation = _hidden("__EVENTVALIDATION")
            if not viewstate:
                return None

            gr = await s.post(
                f"{base}/jqHandler.ashx?op=s",
                data={
                    "t": "ii", "_search": "false", "rows": "2000",
                    "page": "1", "sidx": "disp_name", "sord": "asc",
                },
                timeout=30,
            )
            rows = (gr.json() or {}).get("rows") or []
            invid = next(
                (rw.get("invid") for rw in rows
                 if str(rw.get("book_id") or "") == str(book_id)),
                None,
            )
            if not invid:
                return None

            data = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategen,
                "__EVENTVALIDATION": eventvalidation,
                "ctl00$MasterPage$mainContent$CenterColumnContent$hfRecordIndex": str(invid),
                "ctl00$MasterPage$mainContent$CenterColumnContent$btnInmateDetail": "",
            }
            await s.post(f"{base}/jailinmates.aspx", data=data, timeout=30)
            mug = await s.get(f"{base}/Mug.aspx", timeout=20)
            if mug.status_code != 200 or not mug.content:
                return None
            return "data:image/jpeg;base64," + base64.b64encode(mug.content).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_jqgrid_mugshot_fail", base=base,
                    book_id=book_id, error=str(exc)[:120])
        return None


async def _fetch_p2c_centralsquare(target: str) -> list[dict]:
    """Fetch current in-custody roster from modern CentralSquare P2C (policetocitizen.com).

    Handshake: GET an app route (/en/Inmates) to obtain the XSRF-TOKEN
    cookie, then echo it as X-XSRF-TOKEN header on the JSON search POST to
    /api/Inmates/<listId>. Page in blocks of 200 until a short page.
    DOB is redacted on the public feed; Age + ArrestDate survive.

    FIXED 2026-11-05 (Lexington SC build): `target` not carrying a `|listId`
    used to silently default to "23" (Buncombe's own id) -- wrong for any
    other tenant, and nothing surfaced the mistake (the API still returns
    200s, just for the wrong agency's roster or an empty one). A listId
    doesn't need manual browser-click-through discovery: every tenant's own
    host-relative `/api/Agency/InitialSettings` (no auth, no id required)
    answers with its own `AgencyId` directly -- confirmed live for Lexington
    (AgencyId=576) by comparing a real browser session's own network calls
    against this endpoint's response. Auto-discover it here whenever
    `target` doesn't already carry an explicit listId, instead of guessing.
    """
    from curl_cffi.requests import AsyncSession

    host, _, list_id = target.partition("|")

    async def _discover_list_id(s: "AsyncSession") -> str:
        try:
            r = await s.get(f"{host}/api/Agency/InitialSettings", timeout=20)
            agency_id = (r.json() or {}).get("AgencyId")
            if agency_id:
                return str(agency_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("jail_scraper.p2c_cs_discover_fail", host=host, error=str(exc)[:120])
        return "23"  # last-resort fallback: Buncombe's own id, same as pre-fix behavior

    page_size = 200
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            if not list_id:
                list_id = await _discover_list_id(s)
            api = f"{host}/api/Inmates/{list_id}"
            # 1) Establish XSRF-TOKEN cookie via app-route GET
            await s.get(f"{host}/en/Inmates", timeout=25)
            token = s.cookies.get("XSRF-TOKEN")
            if not token:
                log.warning("jail_scraper.p2c_cs_no_token", host=host)
                return []
            hdr = {
                "X-XSRF-TOKEN": token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{host}/en/Inmates",
                "Origin": host,
            }
            skip = 0
            while True:
                body = {
                    "FilterOptionsParameters": {
                        "IntersectionSearch": True, "SearchText": "",
                        "Parameters": [],
                    },
                    "IncludeCount": True,
                    "PagingOptions": {
                        "SortOptions": [{
                            "Name": "ArrestDate",
                            "SortDirection": "Descending",
                            "Sequence": 1,
                        }],
                        "Take": page_size, "Skip": skip,
                    },
                }
                r = await s.post(api, headers=hdr, json=body, timeout=60)
                recs = (r.json() or {}).get("Inmates") or []
                if not recs:
                    break
                for rec in recs:
                    last = (rec.get("LastName") or "").strip().upper()
                    first = (rec.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    # FOUND 2026-10-04 (HERMES extraction-completeness audit,
                    # batch 17): live-verified this record already carries
                    # all of the below (same /api/Inmates/<listId> response
                    # this code already parses), none previously read.
                    # ScarsMarksTattoos populated on 174/200 (87%) of a live
                    # sample -- a strong identity-confirmation signal for
                    # skip-trace. Charges (the full list) carries a SECOND+
                    # charge on 158/200 (79%) of bookings -- the old code
                    # kept only PrimaryChargeDescription. ImageId maps to a
                    # real, directly fetchable mugshot at
                    # /api/Inmates/Image/<listId>/<ImageId> (confirmed live,
                    # 200 OK, real JPEG bytes) -- a photo source this vendor
                    # has never had wired at all. HomeAddress exists in the
                    # schema but was 0/200 populated live (this agency
                    # evidently redacts it, same policy as DateOfBirth) --
                    # captured anyway in case that policy ever changes, at
                    # zero marginal cost.
                    charges_list = rec.get("Charges") or []
                    extra_charges = [
                        c.get("Description") for c in charges_list
                        if isinstance(c, dict) and c.get("Description")
                        and c.get("Description") != rec.get("PrimaryChargeDescription")
                    ]
                    tattoos = rec.get("ScarsMarksTattoos") or []
                    tattoo_desc = "; ".join(
                        f"{t.get('Type', '')} {t.get('Location', '')} "
                        f"{t.get('BodyPart', '')}: {t.get('Description', '')}".strip()
                        for t in tattoos if isinstance(t, dict)
                    ) or None
                    image_id = rec.get("ImageId")
                    # FOUND 2026-10-22 (jail_bookings dedupe-collision audit): every charge in
                    # `Charges` already carries a real court docket number (live-verified e.g.
                    # "26CR 434460"), never read before. Booking-level, not charge-level, but one
                    # booking's docket is stable and unique enough to serve as a real per-record
                    # id -- the same role book_id plays for the jqGrid vendor.
                    docket = next((c.get("DocketNumber") for c in charges_list
                                   if isinstance(c, dict) and c.get("DocketNumber")), None)
                    out.append({
                        "last": last, "first": first,
                        "middle": (rec.get("MiddleName") or "").strip().upper() or None,
                        "dob": rec.get("DateOfBirth"),
                        "age": rec.get("Age"),
                        "arrest_date": rec.get("ArrestDate"),
                        "docket_number": docket,
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:_CHARGE_CAP],
                        "other_charges": "; ".join(extra_charges)[:_CHARGE_CAP] or None,
                        "race": rec.get("Race"),
                        "sex": rec.get("Sex"),
                        "height": rec.get("Height"),
                        "weight": rec.get("Weight"),
                        "scars_marks_tattoos": tattoo_desc,
                        "holding_facility": rec.get("HoldingFacility"),
                        "booking_agency": rec.get("BookingAgency"),
                        "court_date": rec.get("CourtDate") or None,
                        "release_date_raw": rec.get("ReleaseDate") or None,
                        "total_bond_amount": rec.get("TotalBondAmount"),
                        "home_address": rec.get("HomeAddress") or None,
                        "mugshot_url": (
                            f"{host}/api/Inmates/Image/{list_id}/{image_id}"
                            if image_id else None
                        ),
                    })
                if len(recs) < page_size:
                    break
                skip += page_size
                if skip > 5000:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_cs_fail", host=host,
                    error=str(exc)[:120])
        return []

    log.info("jail_scraper.p2c_cs_ok", host=host, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Southern Software Citizen Connect (Henderson NC)
# ---------------------------------------------------------------------------

_CC_CARD_SPLIT = '<div class="card booking-card">'
_CC_NAME_RE = re.compile(r'<h5 class="mb-0">([^<]+)</h5>')
_CC_ROW_RE = re.compile(
    r'<span class="detail-label">([^<]*)</span>\s*'
    r'<span class="detail-value[^"]*">([^<]*)</span>')
_CC_CHARGE_RE = re.compile(
    r'<div class="charge-details"><div>(.*?)<span class="charge-agency"', re.S)
_CC_TOTAL_RE = re.compile(r"Total Inmates:.*?>(\d+)<", re.S)
_CC_SHOWING_RE = re.compile(r"Showing\s+\d+-(\d+)\s+of\s+(\d+)\s+inmates")
_CC_PAGE_SIZE = 20
# FOUND 2026-10-14: every card already embeds a real per-inmate mugshot
# <img>, previously never read (see module docstring). The vendor's own
# fallback for a booking with no uploaded photo is a literal, shared
# "NoMugshot.jpg" asset -- NOT per-row data, so it's detected and dropped
# rather than kept as if it were a real photo (live-verified 179 real /
# 1 fallback across Henderson's full roster).
_CC_MUGSHOT_RE = re.compile(r"""class=['"]booking-mugshot[^'"]*['"]\s*\n?\s*src=['"]([^'"]+)['"]""")


def _parse_citizen_connect_cards(html_text: str) -> list[dict]:
    """Parse the booking cards out of one fetch_current_confinements.php page."""
    out: list[dict] = []
    for card in (html_text or "").split(_CC_CARD_SPLIT)[1:]:
        nm = _CC_NAME_RE.search(card)
        if not nm:
            continue
        flat_name = html.unescape(nm.group(1))
        parts = _split_space_name(flat_name)
        if not parts:
            continue
        last, first = parts
        fields = {k.strip().rstrip(":"): html.unescape(v).strip()
                  for k, v in _CC_ROW_RE.findall(card)}
        charges = [_strip_tags(c) for c in _CC_CHARGE_RE.findall(card)]
        charges = [c for c in charges if c]
        # "36 years / W / M" -> "36"
        age = (fields.get("Demographics", "").split(" years")[0].strip()
               or None)
        mm = _CC_MUGSHOT_RE.search(card)
        mugshot_src = mm.group(1) if mm else None
        if mugshot_src and "nomugshot" in mugshot_src.lower():
            mugshot_src = None
        out.append({
            "last": last, "first": first,
            "middle": _space_middle(flat_name) or None,
            "dob": fields.get("Date of Birth") or None,
            "age": age,
            "arrest_date": (fields.get("Booked")
                            or fields.get("Arrest Date/Time") or None),
            "charge": "; ".join(charges)[:_CHARGE_CAP],
            # This feed is the CURRENT-confinements list, so every row is a
            # person still in custody; the vendor publishes no release column.
            "release_status": "in_custody",
            "mugshot_url": mugshot_src,
            # Forward the full label:value card dict (Demographics, Booked,
            # Facility, etc.) — the parser reads few of these but they carry
            # extra skip-trace signal.
            "fields": fields,
        })
    return out


async def _fetch_citizen_connect(target: str) -> list[dict]:
    """Southern Software Citizen Connect current-confinements roster.

    target is "<AgencyID>|<JMSAgencyID>", e.g. "HendersonCoNC|NC0450000".

    Handshake: the AJAX endpoint answers 500 "Session AgencyID not set" unless a
    PHP session has already been seeded, so GET the booking-search page once
    (?AgencyID=...) and reuse the session cookie. Page 1 posts JMSAgencyID; the
    vendor's own pager then posts IDX=<1-based page> against the same session.
    Full DOB is published on every card. Free + compliant: this is the page's
    own XHR, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    agency, _, jms = target.partition("|")
    page_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID={agency}"
    api = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/fetchesforajax/"
           "fetch_current_confinements.php")
    hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": page_url}
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(page_url, timeout=30)
            r = await s.post(api, headers=hdr, timeout=60, data={
                "JMSAgencyID": jms, "search": "", "agency": "", "sort": "name"})
            body = r.text or ""
            if "booking-card" not in body:
                log.warning("jail_scraper.citizen_connect_empty", agency=agency)
                return []
            out.extend(_parse_citizen_connect_cards(body))

            tm = _CC_TOTAL_RE.search(body)
            sm = _CC_SHOWING_RE.search(body)
            total = int(tm.group(1)) if tm else (
                int(sm.group(2)) if sm else len(out))
            pages = min(math.ceil(total / _CC_PAGE_SIZE) if total else 1, 60)
            for page in range(2, pages + 1):
                await asyncio.sleep(0.3)  # polite pacing
                pr = await s.post(api, headers=hdr, timeout=60, data={
                    "IDX": page, "search": "", "agency": "", "sort": "name"})
                recs = _parse_citizen_connect_cards(pr.text or "")
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.citizen_connect_fail", agency=agency,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.citizen_connect_ok", agency=agency, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Tyler New World InmateInquiry (Gaston NC)
# ---------------------------------------------------------------------------

_TNW_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TNW_CELL_RE = re.compile(r'<td class="([A-Za-z]+)">(.*?)</td>', re.S)
_TNW_DETAIL_RE = re.compile(r"Inmate/Detail/(\d+)")
_TNW_SHOWING_RE = re.compile(
    r"Showing\s*(\d+)\s*to\s*(\d+)\s*of\s*(\d+)", re.S)
_TNW_FIELD_RE = re.compile(r'<span id=([A-Za-z]+)>(.*?)</span>', re.S)
_TNW_MAX_PAGES = 30
# FOUND 2026-10-14: the grid's own "Photo" column was always discarded --
# `_TNW_CELL_RE` matches `class="Photo"` same as any other cell, but
# `_strip_tags` on a cell that is ONLY an `<img>` (no text) strips it to ""
# before this regex ever runs, so the field quietly became useless. This
# captures the real `src` directly off the row, live-verified on 2 ids as
# distinct, directly-fetchable real JPEGs (25,879 / 32,308 bytes), no
# session or auth needed -- unlike the jqGrid vendor below, this is a plain
# URL with zero extra request cost.
_TNW_PHOTO_RE = re.compile(r'<td class="Photo"><img src="([^"]+)"', re.S)


def _parse_tyler_rows(html_text: str, base: str = "") -> list[dict]:
    """Parse the in-custody grid of a Tyler New World InmateInquiry page."""
    out: list[dict] = []
    for rowm in _TNW_ROW_RE.finditer(html_text or ""):
        row = rowm.group(1)
        cells = {k: _strip_tags(v) for k, v in _TNW_CELL_RE.findall(row)}
        if not cells.get("Name"):
            continue
        parts = _split_comma_name(html.unescape(cells["Name"]))
        if not parts:
            continue
        last, first = parts
        in_custody = cells.get("InCustody", "").upper() == "YES"
        if not in_custody:
            continue
        det = _TNW_DETAIL_RE.search(row)
        photo_m = _TNW_PHOTO_RE.search(row)
        mugshot_url = (
            urljoin(base, html.unescape(photo_m.group(1))) if photo_m and base
            else (html.unescape(photo_m.group(1)) if photo_m else None)
        )
        sched = cells.get("ScheduledReleaseDate") or None
        out.append({
            "last": last, "first": first,
            "middle": _comma_middle(html.unescape(cells["Name"])) or None,
            "dob": cells.get("DateOfBirth") or None,
            "mugshot_url": mugshot_url,
            "arrest_date": None,   # booking date lives on the detail page
            "charge": "",          # charges live on the detail page
            "release_status": (f"scheduled_release {sched}" if sched
                               else "in_custody"),
            "scheduled_release": sched,
            "facility": cells.get("HousingFacility") or None,
            "detail_id": det.group(1) if det else None,
            # Forward the full parsed grid-cell dict (Name/DateOfBirth/
            # InCustody/HousingFacility/ScheduledReleaseDate/...).
            "cells": cells,
        })
    return out


def _parse_tyler_detail(html_text: str) -> dict:
    """Pull booking date + charge list off one Inmate/Detail page.

    The page lists the subject's whole booking history newest-first; the open
    booking is the first one with an empty Release Date.
    """
    body = html_text or ""
    charges = [_strip_tags(v) for _, v in
               re.findall(r'<td class="(ChargeDescription)">(.*?)</td>', body, re.S)]
    charges = [c for c in charges if c]
    booking_date = None
    for block in body.split('<div class="Booking">')[1:]:
        fields = {k: _strip_tags(v) for k, v in _TNW_FIELD_RE.findall(block)}
        if fields.get("ReleaseDate"):
            continue
        booking_date = fields.get("BookingDate") or None
        break
    return {"arrest_date": booking_date, "charge": "; ".join(charges)[:_CHARGE_CAP]}


async def _fetch_tyler_detail(base: str, detail_id: str) -> dict:
    """Fetch one Tyler Inmate/Detail page and return {arrest_date, charge}.

    Kept standalone so the enricher can hydrate only the rows it actually
    matched to an owner (one GET each) instead of the whole 700-row roster.
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/Inmate/Detail/{detail_id}", timeout=45)
        return _parse_tyler_detail(r.text or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_detail_fail", detail_id=detail_id,
                    error=str(exc)[:120])
        return {}


async def _fetch_tyler_inmate_inquiry(base: str, detail_limit: int = 0) -> list[dict]:
    """Tyler New World InmateInquiry current in-custody roster.

    The search form is a plain GET, so `?InCustody=True&Page=<n>` returns the
    whole roster 100 rows at a time. The grid carries FULL DOB, the in-custody
    flag and the scheduled release date. Booking date and charges are only on
    the per-inmate detail page, so they are fetched for at most `detail_limit`
    records (0 = grid only) to keep one run to a handful of requests.

    Free + compliant: a public GET form, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            page = 1
            while page <= _TNW_MAX_PAGES:
                r = await s.get(f"{base}?InCustody=True&Page={page}", timeout=60)
                body = r.text or ""
                recs = _parse_tyler_rows(body, base=base)
                if not recs:
                    break
                out.extend(recs)
                sm = _TNW_SHOWING_RE.search(body)
                if not sm or int(sm.group(2)) >= int(sm.group(3)):
                    break
                page += 1
                await asyncio.sleep(0.3)  # polite pacing

            for rec in out[:max(detail_limit, 0)]:
                if not rec.get("detail_id"):
                    continue
                await asyncio.sleep(0.3)
                dr = await s.get(f"{base}/Inmate/Detail/{rec['detail_id']}",
                                 timeout=45)
                rec.update(_parse_tyler_detail(dr.text or ""))
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_fail", base=base, error=str(exc)[:120])
        return out

    log.info("jail_scraper.tyler_ok", base=base, count=len(out))
    return out


def _york_clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_YORK_PAGE_SIZE = 15
#: Numeric page-link postback targets 2-10 (page 1 is the initial GET). The pager's own "..."
#: control advances to the NEXT page-GROUP (11-20, 21-30, ...) rather than a single page -- full
#: coverage of the ~29-page/432-row roster would need to walk those groups too. Scoped to the
#: first 10 pages (~150 most-recent bookings) for now: jail_booking_new specifically cares about
#: RECENT activity, and this directly-addressable range covers that without the added complexity
#: of re-deriving the group-advance target from each page's own pager state. Revisit if full
#: historical coverage is ever needed.
_YORK_PAGE_TARGETS = [f"dgJackets$ctl01$ctl0{n}" for n in range(1, 10)]


def _parse_york_page(body: str) -> list[dict]:
    """Pure: one page's inmate records from York County SC's inmatesinjail.aspx (classic
    ASP.NET WebForms DataGrid, no JSON API -- live-verified 2026-10-22, 15 records/page)."""
    out: list[dict] = []
    chunks = body.split('<td colspan="2" class="cell1">')[1:]
    for chunk in chunks:
        name_m = re.match(r"([^<]*)</td>", chunk)
        if not name_m:
            continue
        name_parts = _york_clean(name_m.group(1)).split(" ", 1)
        last = name_parts[0].rstrip(",")
        rest = name_parts[1].split(" ", 1) if len(name_parts) > 1 else []
        first = rest[0] if rest else ""
        middle = rest[1] if len(rest) > 1 else None
        if not (last and first):
            continue

        def field(label: str) -> str | None:
            m = re.search(
                rf'class="text1">{label}:?\s*</td>\s*<td class="medBoldBlack">([^<]*)</td>', chunk)
            return _york_clean(m.group(1)) if m else None

        booking_date = field("Booking Date")
        city = field("City")
        state_zip = (field("State/Zip") or "").split(" ", 1)
        race_sex = (field("Race/Sex") or "").split(" ")
        age = field("Age")

        photo_m = re.search(r'href="(/photos/[^"]+)"', chunk)
        photo = urljoin("https://inmatesinjail.yorkcountygov.com", photo_m.group(1)) if photo_m else None

        booking_m = re.search(
            r'class="medBlackText">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackTexta">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackTexta">([^<]*?)\s*</td>\s*'
            r'<td class="medBlackTexta2">\s*([^<]+?)\s*</td>',
            chunk,
        )
        charges = re.findall(
            r'class="medBlackText3">\s*(\d+)\s*</td>\s*'
            r'<td class="medBlackText3">\s*([^<]+?)\s*</td>\s*'
            r'<td class="medBlackText3">\s*([^<]+?)\s*</td>',
            chunk,
        )
        # Worst/first charge as the headline (same "one charge field" contract every other
        # vendor fetcher here returns); the full list is kept too for anyone who wants it.
        charge_list = [{"seq": c[0], "desc": _york_clean(c[1]), "agency": _york_clean(c[2])}
                       for c in charges]
        out.append({
            "last": last.upper(), "first": first.upper(),
            "middle": middle.upper() if middle else None,
            "age": age, "race": race_sex[0] if race_sex else None,
            "sex": race_sex[1] if len(race_sex) > 1 else None,
            "arrest_date": booking_date,
            "book_id": _york_clean(booking_m.group(1)) if booking_m else None,
            "charge": (charge_list[0]["desc"] if charge_list else "")[:_CHARGE_CAP],
            "agency": charge_list[0]["agency"] if charge_list else None,
            "charges": charge_list,
            "release_status": _york_clean(booking_m.group(3)) if booking_m else None,
            "bond": _york_clean(booking_m.group(4)) if booking_m else None,
            "city": city, "state": state_zip[0] if state_zip else None,
            "zip": state_zip[1] if len(state_zip) > 1 else None,
            "photo_url": photo,
        })
    return out


async def _fetch_york_webforms(target: str) -> list[dict]:
    """Fetch current in-custody roster from York County SC's inmatesinjail.aspx (classic ASP.NET
    WebForms DataGrid -- no vendor product match in this file, a county-built/standalone system).

    No source existed for York SC at all before this (gap_matrix: jail_booking/jail_booking_new/
    atty_obituary_match all "no source known", "ran": False). Live-verified 2026-10-22: 432 in
    custody total, this fetches the first ~150 (10 pages, see _YORK_PAGE_TARGETS' own docstring
    for why not the full roster yet). Pagination is a classic ASP.NET DataGrid postback
    (__EVENTTARGET=dgJackets$ctl01$ctlNN + the page's own __VIEWSTATE/__VIEWSTATEGENERATOR/
    __EVENTVALIDATION resubmitted each time), same technique this file's own
    _fetch_p2c_jqgrid_mugshot() already uses for a different vendor's postback.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=20)
            body = r.text or ""
            out.extend(_parse_york_page(body))

            def _hidden(html_body: str, name: str) -> str:
                m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html_body)
                return m.group(1) if m else ""

            for page_target in _YORK_PAGE_TARGETS:
                vs = _hidden(body, "__VIEWSTATE")
                vsg = _hidden(body, "__VIEWSTATEGENERATOR")
                ev = _hidden(body, "__EVENTVALIDATION")
                if not vs:
                    break
                data = {
                    "__EVENTTARGET": page_target, "__EVENTARGUMENT": "",
                    "__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vsg, "__EVENTVALIDATION": ev,
                }
                r = await s.post(target, data=data, timeout=20)
                body = r.text or ""
                recs = _parse_york_page(body)
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.york_webforms_fail", target=target, error=str(exc)[:120])
        return out

    log.info("jail_scraper.york_webforms_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Randolph County NC -- standalone ASP.NET WebForms (county-built, no vendor match)
# ---------------------------------------------------------------------------

_RANDOLPH_CHUNK_ID_RE = re.compile(r"^(\d+)','\d+Name'")
_RANDOLPH_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
#: The address/jail-info block's label cell nests `<b>` directly in `<td>`
#: (`<td width="160" nowrap><b>LABEL:</b></td>`), so `</b>` is followed
#: (mod whitespace) straight by `</td>`. The arrest-info block below nests
#: `<b>` INSIDE a `<font color=...>` instead, so its `</b>` is followed by an
#: extra `</font>` first -- that structural difference is what keeps this
#: pattern from also matching arrest-info rows (confirmed live: it doesn't).
_RANDOLPH_LABEL_VALUE_RE = re.compile(
    r"<b>\s*([^<:]*?):?\s*</b>\s*</td>\s*<td[^>]*>\s*<font[^>]*>(.*?)</font>",
    re.S,
)
#: Charge DATA rows and the charge-table HEADER row share one spacer cell --
#: `<td background="white" nowrap width="10">` -- that appears NOWHERE else on
#: the page (the address block's spacer is `<td width="160" nowrap>`, the
#: arrest-info block's is `<td nowrap width="20" bgcolor="#ffffee">`).
#: Anchoring on it is required: without it, a first draft of this pattern
#: matched 6 consecutive "looks like a charge cell" cells wherever they
#: happened to fall, including walking OUT of the charges table and across
#: unrelated rows in the arrest-info block above it (which reuses the exact
#: same `<td nowrap><font style="...">VALUE</font></td>` shape for ITS single
#: value cell) -- live-caught producing charge="11/05/26 09:45:37 Arrest
#: Type :", i.e. it had silently walked into the next row's own label text.
_RANDOLPH_CHARGE_ROW_RE = re.compile(
    r'<td background="white" nowrap width="10">\s*</td>\s*'
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>\s*</td>\s*'      # Offense Date/Time
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>\s*</td>\s*'      # Offense Description
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>\s*</td>\s*'      # Related Incident
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>\s*</td>\s*'      # Court Reference
    r'<td nowrap align="Right">\s*<font style="[^"]*">(.*?)</font>\s*</td>\s*'  # Bail Amount
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>\s*</td>',        # Bail Type
    re.S,
)
#: The arrest-info block's own label:value shape (see _RANDOLPH_LABEL_VALUE_RE's
#: comment above) -- used only to pull Arrest Agency -> booking_agency.
_RANDOLPH_ARREST_INFO_RE = re.compile(
    r"<b>\s*([^<:]*?)\s*:\s*</b>\s*</font>\s*</td>\s*"
    r'<td nowrap>\s*<font style="[^"]*">(.*?)</font>',
    re.S,
)
_RANDOLPH_MUGSHOT_RE = re.compile(r'href="([^"]*MugImages[^"]*)"\s+rel="lightbox"', re.S)


def _randolph_dt(s: str | None) -> str | None:
    """'11/05/26 09:44:44' -> '2026-11-05 09:44:44'.

    The vendor's own Incarceration Date/Time stamp is a 2-digit-year, 24-hour,
    with-seconds format that has no match in _parse_date()'s own format list
    above (its 4-digit-year ISO loop wants "%Y-%m-%d %H:%M:%S"; its US-format
    loop only pairs %H:%M/%I:%M(:%S)%p with a 4-digit %Y). Reformatting here
    to a pattern _parse_date() already accepts is simpler and safer than
    teaching that shared function a new one-county format.
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%m/%d/%y %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(s, "%m/%d/%y")
        except ValueError:
            return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_randolph_page(body: str, base: str = "") -> list[dict]:
    """Pure: every confined-inmate record on Randolph County NC's
    confinedinmatesbydate.aspx (classic ASP.NET WebForms, inline client-side
    toggle() JS show/hide -- no JSON API, no vendor-product match in this
    file's roster above, a standalone county-built system same category as
    York SC's inmatesinjail.aspx). Live-verified 2026-11-05: 343 records in
    ONE plain GET response (no params, no auth, no CAPTCHA, no postback
    needed for the roster itself -- unlike York, the whole thing is already
    in this one response).

    Each record is a (summary row, detail row) pair sharing one numeric id
    (the page's own `toggle('<id>','<id>Name',...)` argument, also reused as
    that id's VineLink `offenderID` query param) -- carried through as
    `detail_id`, same role Tyler New World's detail_id plays for _booking_
    identity()'s preference order. The summary row's 8 <td> cells carry Last/
    First/Middle/Suffix/Age/Race/Gender/DateConfined; the detail row (present
    server-side already, just CSS-hidden until clicked) carries address, jail
    facility/POD location, Incarceration Date/Time, 2 mugshot links, and one
    or more incident sub-blocks (Arrest Date/Type/Agency/Officer/Location +
    a per-incident charges table: Offense Date/Time | Offense Description |
    Related Incident | Court Reference | Bail Amount | Bail Type). Live
    distribution: 239/343 records have exactly 1 incident sub-block, 104/343
    have 2-5 (re-arrested while already confined, or multiple warrants
    processed as separate incidents) -- charges from EVERY sub-block are
    collected (not just the first), so a real charge is never dropped.

    `base` is the page's own URL, used only to resolve the two relative
    mugshot `<a href="../sheriff/MugImages/...">` links to absolute URLs.
    """
    out: list[dict] = []
    for chunk in body.split("OnClick=\"toggle('")[1:]:
        id_m = _RANDOLPH_CHUNK_ID_RE.match(chunk)
        detail_id = id_m.group(1) if id_m else None

        summary, _, detail = chunk.partition('colspan="10"')
        cells = [_strip_tags(html.unescape(c)) for c in _RANDOLPH_TD_RE.findall(summary)]
        if len(cells) < 8:
            continue
        last, first, middle, suffix, age, race, sex, _date_confined = cells[:8]
        last, first, middle, suffix = (
            last.upper(), first.upper(), middle.upper(), suffix.upper())
        if not (last and first):
            continue
        if suffix:
            last = f"{last} {suffix}"

        fields = {
            _strip_tags(html.unescape(k)): _strip_tags(html.unescape(v))
            for k, v in _RANDOLPH_LABEL_VALUE_RE.findall(detail)
        }
        arrest_info = {
            _strip_tags(html.unescape(k)): _strip_tags(html.unescape(v))
            for k, v in _RANDOLPH_ARREST_INFO_RE.findall(detail)
        }

        height = weight = None
        hw = fields.get("Height / Weight") or ""
        if "/" in hw:
            h, _, w = hw.partition("/")
            height, weight = h.strip() or None, w.strip() or None

        street = fields.get("Street Address") or ""
        city_zip = fields.get("City/State/Zip") or ""
        home_address = ", ".join(p for p in (street, city_zip) if p) or None

        charge_rows = _RANDOLPH_CHARGE_ROW_RE.findall(detail)
        descs = [_strip_tags(html.unescape(c[1])) for c in charge_rows
                 if _strip_tags(html.unescape(c[1]))]
        dockets = [_strip_tags(html.unescape(c[3])) for c in charge_rows
                   if _strip_tags(html.unescape(c[3]))]
        bond_total, bond_seen = 0.0, False
        for c in charge_rows:
            raw_bail = _strip_tags(html.unescape(c[4]))
            if raw_bail:
                try:
                    bond_total += float(re.sub(r"[^0-9.]", "", raw_bail) or 0)
                    bond_seen = True
                except ValueError:
                    pass

        mugs = _RANDOLPH_MUGSHOT_RE.findall(detail)
        mugshot_url = urljoin(base, html.unescape(mugs[0])) if mugs and base else None

        out.append({
            "last": last, "first": first,
            "middle": middle or None,
            "age": age or None,
            "race": race or None,
            "sex": sex or None,
            "arrest_date": _randolph_dt(fields.get("Incarceration Date/Time")),
            "facility": fields.get("Jail Facility Location") or None,
            "cell_block": fields.get("Jail POD Location") or None,
            "home_address": home_address,
            "height": height,
            "weight": weight,
            "charge": (descs[0] if descs else "")[:_CHARGE_CAP],
            "other_charges": "; ".join(descs[1:])[:_CHARGE_CAP] or None,
            "docket_number": dockets[0] if dockets else None,
            "total_bond_amount": bond_total if bond_seen else None,
            "booking_agency": arrest_info.get("Arrest Agency") or None,
            # Current-confinement roster, same as Citizen Connect/York: every
            # row present IS in custody right now; the vendor publishes no
            # separate release column.
            "release_status": "in_custody",
            "mugshot_url": mugshot_url,
            "detail_id": detail_id,
            # Forward the full address/jail-info label:value dict -- same
            # "extra skip-trace signal" convention _to_listing already reads
            # generically via rec.get("fields") for Citizen Connect.
            "fields": fields,
        })
    return out


async def _fetch_randolph_webforms(target: str) -> list[dict]:
    """Fetch current in-custody roster from Randolph County NC's standalone
    ASP.NET WebForms confinedinmatesbydate.aspx (no vendor-product match in
    this file -- a county-built system, same category as _fetch_york_webforms
    above but simpler: live-verified 2026-11-05, the WHOLE ~343-row roster is
    already on one plain GET, no postback/pagination needed for the roster
    itself, no params, no auth, no CAPTCHA).
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=60)
            out = _parse_randolph_page(r.text or "", base=target)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.randolph_webforms_fail", target=target,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.randolph_webforms_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Davidson County NC -- standalone dhtmlxGrid AJAX handler (county-built, no vendor match)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Davidson NC — standalone dhtmlxGrid AJAX handler (county-built, no vendor match)
# ---------------------------------------------------------------------------

_DAVIDSON_FIELD_RE = re.compile(
    r"Incarceration Date:\s*([^<]*?)<br\s*/?>\s*"
    r"Arrest Date:\s*([^<]*?)<br\s*/?>\s*"
    r"Arrest Agency:\s*([^<]*?)<br\s*/?>\s*"
    r"Arrest Location:\s*([^<]*?)<br\s*/?>",
    re.IGNORECASE,
)
_DAVIDSON_OFFENSE_ROW_RE = re.compile(
    r'<td class="gradlt txtmd"[^>]*>([^<]*)</td>\s*'
    r'<td class="gradlt txtmd"[^>]*>([^<]*)</td>\s*'
    r'<td class="gradlt txtmd"[^>]*>([^<]*)</td>\s*'
    r'<td class="gradlt txtmd"[^>]*>([^<]*)</td>\s*'
    r'<td class="gradlt txtmd"[^>]*>([^<]*)</td>',
)
_DAVIDSON_COURT_DATE_RE = re.compile(
    r"Next Scheduled Court Date<br\s*/?>\s*([^<]*)", re.IGNORECASE)
_DAVIDSON_RACE_RE = re.compile(r"Race:\s*([A-Za-z]+)\s*<br", re.IGNORECASE)
_DAVIDSON_BOND_TOTAL_RE = re.compile(
    r"Totals:</td>\s*<td[^>]*>\s*\$([\d,]+\.\d{2})</td>\s*<td[^>]*>\s*\$([\d,]+\.\d{2})</td>",
)


def _parse_davidson_list(xml_bytes: bytes, target: str) -> list[dict]:
    """Pure: parse Davidson County NC's dhtmlxGrid XML roster (handler/inmate_data.ashx) into
    base inmate dicts. No vendor-product match -- a county-built ASP.NET handler serving a
    dhtmlxGrid-format XML document (root <rows total_count="N">, one <row> per inmate, 13
    CDATA <cell> children each: last, first, middle, a doVw(...) link, address, city, state,
    sex, age, height, weight, booking number, internal id). mugshot_url is built from the
    internal id with zero extra requests -- live-verified: /DCInmates/images/<id>.jpeg
    resolves to a real, distinct JPEG for every id format seen (plain numeric and
    'R'-prefixed alike)."""
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for row in root.findall("row"):
        cells = [c.text or "" for c in row.findall("cell")]
        if len(cells) < 13:
            continue
        last, first, middle = cells[0].strip(), cells[1].strip(), cells[2].strip()
        if not (last and first):
            continue
        address, city, state_abbr = cells[4].strip(), cells[5].strip(), cells[6].strip()
        booking_number, internal_id = cells[11].strip(), cells[12].strip()
        home_address = ", ".join(
            p for p in (address, f"{city} {state_abbr}".strip()) if p) or None
        out.append({
            "last": last.upper(), "first": first.upper(),
            "middle": middle.upper() if middle else None,
            "sex": cells[7].strip() or None,
            "age": cells[8].strip() or None,
            "height": cells[9].strip() or None,
            "weight": cells[10].strip() or None,
            "home_address": home_address,
            "book_id": booking_number or None,
            "mugshot_url": (urljoin(target, f"../images/{internal_id}.jpeg")
                            if internal_id else None),
            "_internal_id": internal_id,
            "_booking_number": booking_number,
        })
    return out


def _parse_davidson_detail(body: str) -> dict:
    """Pure: pull race / next-court-date / bond total / most-recent charge+arrest info out of
    one inmate's detail-view HTML fragment (handler/inmate_details.ashx?number=&curbook=).

    A person can carry MULTIPLE "incarceration event" blocks on this page (one per booking on
    file, not just the current one) -- live-verified the FIRST block is always the one
    matching the booking_number this detail call was made for; trailing blocks are older,
    unrelated bookings for the same person and are intentionally ignored (slicing the body at
    the second "Incarceration Date:" marker before scanning for offense rows, so an older
    booking's charges never leak into the current one's)."""
    out: dict = {}
    court_m = _DAVIDSON_COURT_DATE_RE.search(body)
    if court_m:
        out["court_date"] = _strip_tags(court_m.group(1)) or None
    race_m = _DAVIDSON_RACE_RE.search(body)
    if race_m:
        out["race"] = race_m.group(1).strip()
    bond_m = _DAVIDSON_BOND_TOTAL_RE.search(body)
    if bond_m:
        out["total_bond_amount"] = bond_m.group(2).strip()

    field_m = _DAVIDSON_FIELD_RE.search(body)
    if field_m:
        incarceration_date, arrest_date, agency, _location = (
            g.strip() for g in field_m.groups())
        out["arrest_date"] = arrest_date or incarceration_date or None
        out["booking_agency"] = agency or None

    first_marker = body.find("Incarceration Date:")
    second_block = (body.find("Incarceration Date:", first_marker + 1)
                     if first_marker != -1 else -1)
    scope = body[:second_block] if second_block != -1 else body
    offense_rows = _DAVIDSON_OFFENSE_ROW_RE.findall(scope)
    if offense_rows:
        descs = [_strip_tags(r[2]) for r in offense_rows if r[2].strip()]
        dockets = [r[4].strip() for r in offense_rows if r[4].strip()]
        if descs:
            out["charge"] = descs[0][:_CHARGE_CAP]
            if len(descs) > 1:
                out["other_charges"] = "; ".join(descs[1:])[:_CHARGE_CAP]
        if dockets:
            out["docket_number"] = dockets[0]
    return out


async def _fetch_davidson_detail_one(session, sem, detail_url: str,
                                      internal_id: str, booking_number: str) -> dict:
    async with sem:
        try:
            r = await session.get(
                detail_url, params={"number": internal_id, "curbook": booking_number},
                timeout=15,
            )
            return _parse_davidson_detail(r.text or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("jail_scraper.davidson_detail_fail", internal_id=internal_id,
                        error=str(exc)[:120])
            return {}


async def _fetch_davidson_dhtmlx(target: str) -> list[dict]:
    """Fetch current in-custody roster from Davidson County NC's inmate lookup (county-built
    ASP.NET handler, no vendor-product match -- a dhtmlxGrid-format XML list endpoint plus a
    per-inmate AJAX detail endpoint, same two-endpoint shape as this file's Tyler/York
    fetchers).

    Live-verified 2026-11-05: `target` (handler/inmate_data.ashx) with NO query string at all
    returns the FULL un-paginated roster (310/310 rows) in one request -- the "?dynamic=100"
    query param from this fetcher's original build brief actually CAPS the response at 100
    rows (confirmed by direct A/B test against the live host: with it, 100 rows and a
    misleadingly unchanged total_count="310" attribute; without any query string, all 310).
    If a future run ever sees fewer <row> elements than the root's own total_count attribute,
    that is logged loudly rather than silently truncated -- the fix then is to re-add paging
    via this same host's confirmed dynamic=100&posStart=<offset> scheme (live-verified: offsets
    0/100/200/300 tile the 310 rows with no overlap/gaps), deliberately not pre-built here
    since the bare endpoint already returns everything today.

    Also hydrates EVERY row's detail page (handler/inmate_details.ashx) for charge/
    arrest_date/court_date/race/total_bond_amount/booking_agency, unlike this file's Tyler
    fetcher (which defers per-row detail to the separate enricher because Tyler's own
    0.3s-paced sequential fetches would take minutes for a 700-row roster). Davidson is cheap
    enough to always do this eagerly: live-verified full 310-row roster + all 310 detail pages
    in ~2.4-4.1s wall-clock (two separate live runs) at semaphore(10) concurrency, no
    throttling/blocking observed -- without it every row would carry zero charge/arrest_date/
    court_date/bond data, which defeats the point of this scraper. mugshot_url needs no extra
    request at all (built straight off the list row's own internal id, see
    _parse_davidson_list).
    """
    from curl_cffi.requests import AsyncSession

    detail_url = urljoin(target, "inmate_details.ashx")
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=20)
            recs = _parse_davidson_list(r.content, target)

            try:
                total_count = int(ET.fromstring(r.content).get("total_count") or len(recs))
            except (ET.ParseError, ValueError, TypeError):
                total_count = len(recs)
            if recs and len(recs) < total_count:
                log.warning("jail_scraper.davidson_dhtmlx_short_page", target=target,
                            got=len(recs), total_count=total_count)

            if recs:
                sem = asyncio.Semaphore(10)
                tasks = [
                    _fetch_davidson_detail_one(s, sem, detail_url,
                                                rec["_internal_id"], rec["_booking_number"])
                    for rec in recs
                ]
                details = await asyncio.gather(*tasks)
                for rec, detail in zip(recs, details):
                    rec.update(detail)
                    rec.pop("_internal_id", None)
                    rec.pop("_booking_number", None)
                    out.append(rec)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.davidson_dhtmlx_fail", target=target, error=str(exc)[:120])
        return out

    log.info("jail_scraper.davidson_dhtmlx_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Cumberland County NC -- standalone ASP.NET WebForms search (county-built, no vendor match)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cumberland County NC -- standalone ASP.NET WebForms search (no vendor-product
# match; a county-built system, same class as _fetch_york_webforms above but a
# different concrete site/markup).
# ---------------------------------------------------------------------------

_CUMBERLAND_LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
_CUMBERLAND_INPUT_RE = re.compile(r"<input\b([^>]*)/?>", re.S)
_CUMBERLAND_PAGE_LINK_RE = re.compile(
    r"__doPostBack\(&#39;Incident_GV&#39;,&#39;(Page\$\d+)&#39;\)")
_CUMBERLAND_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CUMBERLAND_NAME_RE = re.compile(r'<span id="Incident_GV_full_name_\d+">([^<]*)</span>')
_CUMBERLAND_DATE_RE = re.compile(r"<td>([A-Za-z]+ \d{1,2}, \d{4})</td>")
_CUMBERLAND_BOOKID_RE = re.compile(r'\$book_id"[^>]*value="([^"]*)"')
_CUMBERLAND_NAMEID_RE = re.compile(r'\$name_id"[^>]*value="([^"]*)"')
_CUMBERLAND_MIL_RE = re.compile(r'\$isMilitary"[^>]*value="([^"]*)"')
#: Safety valve on the per-letter pager walk -- real max observed live was ~10 pages
#: (100 rows, letter "M"); this guards against an unexpected runaway loop, it is not
#: a real coverage limit (the pager always lists every page directly up to that size).
_CUMBERLAND_MAX_PAGES_PER_LETTER = 60


def _cumberland_hidden_fields(body: str) -> dict:
    """Every <input name=... value=...> on the page (hidden + text) -- a full-fidelity
    postback replay, the same full field set a real browser resubmits on every
    __doPostBack. Classic ASP.NET WebForms needs this (not just the __VIEWSTATE/
    __EVENTVALIDATION trio) because the grid's own per-row hidden inputs
    (name_id/book_id/isMilitary for every currently-rendered row) must round-trip on
    every postback too, or the server-side grid state desyncs."""
    fields: dict = {}
    for m in _CUMBERLAND_INPUT_RE.finditer(body or ""):
        tag = m.group(1)
        name_m = re.search(r'name="([^"]*)"', tag)
        if not name_m:
            continue
        type_m = re.search(r'type="([^"]*)"', tag)
        itype = type_m.group(1) if type_m else "text"
        if itype in ("submit", "button"):
            continue
        val_m = re.search(r'value="([^"]*)"', tag)
        fields[name_m.group(1)] = html.unescape(val_m.group(1)) if val_m else ""
    return fields


def _cumberland_iso_date(s: str | None) -> str | None:
    """'October 30, 2026' -> '2026-10-30'. The vendor's native 'Month D, YYYY' string
    is not one of this file's _parse_date() recognized formats (confirmed:
    _parse_date('October 30, 2026') returns None), so it is normalized to ISO here, at
    scrape time, rather than teaching the shared _parse_date() a new format."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_cumberland_page(body: str) -> list[dict]:
    """Pure: one page's rows from Cumberland County NC's Incident_GV results grid.
    Row-at-a-time (same style as _parse_york_page above) -- the <thead> header row
    shares the grid's "reg_row" CSS class with real data rows, so it is filtered out
    implicitly: it has no Incident_GV_full_name_N span, the one thing every real data
    row carries."""
    out: list[dict] = []
    for row_m in _CUMBERLAND_ROW_RE.finditer(body or ""):
        row = row_m.group(1)
        name_m = _CUMBERLAND_NAME_RE.search(row)
        if not name_m:
            continue
        flat_name = html.unescape(name_m.group(1)).strip()
        parts = _split_comma_name(flat_name)
        if not parts:
            continue
        last, first = parts
        date_m = _CUMBERLAND_DATE_RE.search(row)
        bid_m = _CUMBERLAND_BOOKID_RE.search(row)
        nid_m = _CUMBERLAND_NAMEID_RE.search(row)
        mil_m = _CUMBERLAND_MIL_RE.search(row)
        out.append({
            "last": last, "first": first,
            "middle": _comma_middle(flat_name) or None,
            "arrest_date": _cumberland_iso_date(date_m.group(1) if date_m else None),
            # Real vendor-issued per-booking id, already on this row -- routes every
            # record through _booking_identity()'s preferred real-id branch, same role
            # p2c_jqgrid's book_id plays elsewhere in this file.
            "book_id": bid_m.group(1) if bid_m else None,
            "fields": {
                "name_id": nid_m.group(1) if nid_m else None,
                "is_military": mil_m.group(1) if mil_m else None,
            },
        })
    return out


async def _fetch_cumberland_webforms(target: str) -> list[dict]:
    """Fetch current in-custody roster from Cumberland County NC's Active Inmate
    Search (classic ASP.NET WebForms __VIEWSTATE postback search -- no vendor-product
    match in this file, a county-built/standalone system, same class as
    _fetch_york_webforms above but a different concrete site/markup).

    The search form requires a LastName and publishes no full-roster/blank-search view
    (live-confirmed: a blank LastName POST returns zero rows), so this sweeps the
    alphabet -- one "starts with <letter>" search per A-Z -- and merges results,
    deduping on book_id. Same "iterate a few queries, not full-text search" shape
    already used elsewhere in this project for a system with no single full-roster
    endpoint. Despite the UI's "(*)" hint, no wildcard syntax is needed: a bare single
    letter already does a starts-with match (live-confirmed: LastName=S returns
    Shaw/Smith/Stellabotte/Saunders/... not a literal name "S").

    Each letter's result set paginates via a classic ASP.NET GridView postback
    (__EVENTTARGET=Incident_GV, __EVENTARGUMENT=Page$N, full form-field replay), walked
    here the same way _fetch_york_webforms() above walks York SC's DataGrid pager --
    except this grid's own pager always lists every page directly (no York-style "next
    group of 10" link was ever observed, even for the heaviest letter), so no
    group-advance logic is needed.

    The grid already carries a real per-booking id (book_id) and the booking date on
    every row, so (unlike Tyler's detail-page split, or the jqGrid mugshot helper
    above) no per-record detail fetch is needed just to get a usable identity key.
    Charge/bond/age/race/sex ARE real fields this vendor publishes, confirmed live by
    replaying the grid's own "More Details" postback (__EVENTARGUMENT=Select$N) for one
    row -- e.g. book_id 301938 -> SHAW, JOSEPH, Charge "CANCEL/REVOKE/SUSP CERTIF/TAG",
    Bond $0.00, Age 63, Race Black, Sex Male -- but that is ONE EXTRA POST PER INMATE
    (not per page), the same "rude and slow" math _fetch_p2c_jqgrid_mugshot's docstring
    above already works through for a different vendor: at ~750+ in-custody rows here,
    hydrating every row would add hundreds of sequential requests against one small
    county host, well past this scraper's shared timeout_s budget across every
    concurrently-gathered county. So, same resolution as Tyler's detail_limit=0 default:
    this stays a single-phase, grid-only fetch, and charge/bond/age/race/sex are left
    for a future selective-hydration pass (only rows that actually matched an owner)
    rather than fetched eagerly here. This vendor does not publish DOB at all, even on
    the Select-postback detail view (confirmed: that view's full field list is Name /
    Booking ID / Date Arrested / Charge / Bond / Age / Race / Sex only, no DOB field
    anywhere) -- not a gap in this fetcher, the source simply never exposes it.

    Verified live 2026-11-05: two independent full A-Z sweeps both returned exactly 757
    current in-custody records, 757/757 with a real book_id (zero fallback-hash rows
    needed) and 757/757 with a usable arrest_date, byte-identical after sorting by
    book_id. Arrest dates ranged 2024-02-19 to 2026-10-30 (pretrial detention on serious
    charges can run years; this is an "active/still in custody" roster, not a
    recent-activity log). Sample: book_id 301936 -> AVERY, SPEIGHTS SHAUNQUEZ, arrested
    2026-10-30; book_id 299799 -> ARANT, BRANDY LEIGH, arrested 2026-10-29. Whole run
    took ~40-50s end to end (26 letter-searches + their own pagination, 0.3s polite
    pacing between requests).
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    seen_book_ids: set[str] = set()

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            for letter in _CUMBERLAND_LETTERS:
                r = await s.get(target, timeout=25)
                body = r.text or ""
                fields = _cumberland_hidden_fields(body)
                fields["FirstName"] = ""
                fields["LastName"] = letter
                fields["SubmitBtn"] = "Submit"
                r2 = await s.post(target, data=fields, timeout=30)
                body2 = r2.text or ""
                recs = _parse_cumberland_page(body2)
                for rec in recs:
                    bid = rec.get("book_id")
                    if bid and bid in seen_book_ids:
                        continue
                    if bid:
                        seen_book_ids.add(bid)
                    out.append(rec)

                # Walk this letter's own result pager (Page$2, Page$3, ...).
                cur_body = body2
                visited_pages = {"Page$1"}
                for _ in range(_CUMBERLAND_MAX_PAGES_PER_LETTER):
                    remaining = sorted(
                        set(_CUMBERLAND_PAGE_LINK_RE.findall(cur_body)) - visited_pages,
                        key=lambda p: int(p.split("$")[1]),
                    )
                    if not remaining:
                        break
                    nxt = remaining[0]
                    pf = _cumberland_hidden_fields(cur_body)
                    pf["__EVENTTARGET"] = "Incident_GV"
                    pf["__EVENTARGUMENT"] = nxt
                    await asyncio.sleep(0.3)  # polite pacing
                    rp = await s.post(target, data=pf, timeout=30)
                    cur_body = rp.text or ""
                    precs = _parse_cumberland_page(cur_body)
                    if not precs:
                        break
                    for rec in precs:
                        bid = rec.get("book_id")
                        if bid and bid in seen_book_ids:
                            continue
                        if bid:
                            seen_book_ids.add(bid)
                        out.append(rec)
                    visited_pages.add(nxt)
                await asyncio.sleep(0.3)  # polite pacing between letters
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.cumberland_webforms_fail", target=target,
                    error=str(exc)[:160])
        return out

    log.info("jail_scraper.cumberland_webforms_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Pitt County NC -- standalone ASP.NET WebForms DataGrid (no vendor-product
# match; a county-built system, like York SC's inmatesinjail.aspx above).
# ---------------------------------------------------------------------------

def _pitt_form_fields(html_text: str) -> dict:
    """Extract every current form control's name/value from a Pitt County
    detainee-search WebForms response, so the next postback carries the
    page's FULL form state forward.

    Unlike York SC's DataGrid (where resubmitting just the 4 hidden
    __VIEWSTATE-family fields is enough), this app throws an unhandled
    server exception -- a generic "the Web Application has encountered an
    error" Error.aspx -- on ANY postback that omits a control it expects in
    Request.Form, not only the control actually being changed. Live-confirmed
    two ways: a plain GridView `Page$2` postback 500'd until a second,
    undocumented sibling control -- `ctl00$mainContent$ddlPageResults2`,
    never rendered as visibly linked to anything -- was carried through
    too; it was *also* the entire cause of the page-size postback failing.
    Carrying the whole form forward (the way a real browser always does)
    sidesteps having to enumerate every such hidden sibling by hand.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text or "", "html.parser")
    form = soup.find("form")
    fields: dict = {}
    if not form:
        return fields
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                fields[name] = inp.get("value", "on")
            continue
        if itype in ("submit", "button", "image", "reset"):
            continue  # never auto-click a button; the caller sets one explicitly
        fields[name] = inp.get("value", "")
    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        fields[name] = (opt.get("value", opt.get_text()) if opt else "")
    for ta in form.find_all("textarea"):
        name = ta.get("name")
        if name:
            fields[name] = ta.get_text()
    return fields


def _parse_pitt_grid(html_text: str) -> list[dict]:
    """Parse one page of Pitt County's GridView1 active-detainee grid.

    Columns (already split by the vendor, no name-string parsing needed):
    Select-link, Last Name, Suffix, First Name, Middle Name, Date of Birth,
    Booking Number, Gender, Race, Print-checkbox.

    `recursive=False` is required on BOTH the <tr> and <td> lookups: the
    GridView's own pager row renders as `<td colspan="10"><table>...pager
    links...</table></td>`, and a plain (recursive) `find_all('tr')` on the
    outer grid table walks straight into that NESTED table's own <tr> too --
    live-confirmed this produces one bogus extra "row" per page whose
    "cells" are just the pager's own digit links ("1", "2", "3", ...), which
    otherwise passes the last/first non-empty check below and silently adds
    a fake record (e.g. last="2", first="4") to the roster.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text or "", "html.parser")
    table = soup.find("table", id="ctl00_mainContent_GridView1")
    if not table:
        return []
    out: list[dict] = []
    for tr in table.find_all("tr", recursive=False):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 9:
            continue  # header row (all <th>, 0 <td>) or the pager row (1 wrapper <td>)
        last = cells[1].get_text(strip=True)
        first = cells[3].get_text(strip=True)
        if not last or not first:
            continue
        # Suffix (cells[2]: JR/SR/II/...) is already its own grid column here
        # (no name-string split needed) but is dropped rather than kept, same
        # as every other vendor in this file that strips generational
        # suffixes outright (_NAME_SUFFIXES) instead of carrying them as a
        # field no Listing schema key exists for.
        middle = cells[4].get_text(strip=True)
        dob = cells[5].get_text(strip=True)
        booking_num = cells[6].get_text(strip=True)
        sex = cells[7].get_text(strip=True)
        race = cells[8].get_text(strip=True)
        out.append({
            "last": last.upper(), "first": first.upper(),
            "middle": middle.upper() or None,
            "dob": dob or None,
            # Real vendor-issued booking number -- _booking_identity() takes
            # this over any synthesized hash, and live-verified 479/479
            # rows carry a unique one (zero dedupe collisions).
            "book_id": booking_num or None,
            "sex": sex or None, "race": race or None,
            # This endpoint IS the active-detainee roster (the page's own
            # UI text: "Leave fields blank to retrieve all active
            # detainees"), so every row returned is, by definition,
            # currently in custody -- same convention as Citizen Connect's
            # current-confinements feed elsewhere in this file. The grid
            # exposes no booking/arrest date or charge at the list level
            # (only reachable via a per-row "Select" postback, i.e. one
            # extra request PER inmate for ~479 rows -- not fetched here,
            # same restraint this file already applies to Tyler's detail
            # page and the P2C-jqGrid mugshot).
            "release_status": "in_custody",
        })
    return out


_PITT_MAX_PAGES = 100  # hard safety cap; the live roster needs ~5 pages at size 100


async def _fetch_pitt_webforms(target: str) -> list[dict]:
    """Fetch Pitt County NC's active-detainee roster (classic ASP.NET
    WebForms DataGrid at apps.pittcountync.gov/apps/detention/detainee/ --
    no vendor-product match in this file, a county-built/standalone system,
    same family as York SC's inmatesinjail.aspx above).

    No source existed for Pitt County at all before this. Verified live
    2026-11-05: 479 active detainees, full DOB and a real per-booking number
    on 479/479 rows (zero dedupe collisions) -- e.g. DONNIE DEVON ADAMS JR,
    DOB 04/24/1984, booking #249219, matching this county's own "Detainee
    Search" page exactly.

    Flow (one __doPostBack-driven ASP.NET event per request, so each step
    below is its own round trip -- 7 requests total for the full roster):
      1. GET the search page for a fresh __VIEWSTATE/__EVENTVALIDATION.
      2. Leave Book#/Last/First blank and click "Get  Detainee" (the
         button's own value has a vendor-typo double space) -- the page's
         own UI text: "Leave fields blank to retrieve all active detainees."
      3. Switch the "Results per page" dropdown (ddlPageResults) to its
         largest option, 100, cutting the page-walk from ~48 requests
         (default size 10) down to ~5.
      4. Walk GridView1's own __doPostBack pager ("Page$2", "Page$3", ...)
         up to the total-page count read straight off the pager's own links
         (stable and always fully visible here -- PageButtonCount=10,
         the live roster needs only ~5, so the "..." group-advance case
         York's own pager comment describes never triggers).

    See `_pitt_form_fields`'s own docstring for why every postback below
    resubmits the FULL previous form (not just the 4 __VIEWSTATE-family
    fields York's simpler pager gets away with) -- this app 500s on any
    postback that omits a control it expects in Request.Form.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=30)
            body = r.text or ""

            fields = _pitt_form_fields(body)
            fields["__EVENTTARGET"] = ""
            fields["__EVENTARGUMENT"] = ""
            fields["ctl00$mainContent$Button3"] = "Get  Detainee"
            r = await s.post(target, data=fields, timeout=30)
            body = r.text or ""
            if "encountered an error during processing" in body:
                log.warning("jail_scraper.pitt_webforms_search_error", target=target)
                return []

            fields = _pitt_form_fields(body)
            fields["__EVENTTARGET"] = "ctl00$mainContent$ddlPageResults"
            fields["__EVENTARGUMENT"] = ""
            for k in list(fields):
                if k.startswith("ctl00$mainContent$ddlPageResults"):
                    fields[k] = "100"
            r = await s.post(target, data=fields, timeout=30)
            body = r.text or ""
            if "encountered an error during processing" in body:
                log.warning("jail_scraper.pitt_webforms_resize_error", target=target)
                return []
            out.extend(_parse_pitt_grid(body))

            page_nums = [int(m) for m in re.findall(r"Page\$(\d+)", body)]
            total_pages = min(max(page_nums) if page_nums else 1, _PITT_MAX_PAGES)

            for page_num in range(2, total_pages + 1):
                await asyncio.sleep(0.3)  # polite pacing
                fields = _pitt_form_fields(body)
                fields["__EVENTTARGET"] = "ctl00$mainContent$GridView1"
                fields["__EVENTARGUMENT"] = f"Page${page_num}"
                r = await s.post(target, data=fields, timeout=30)
                body = r.text or ""
                if "encountered an error during processing" in body:
                    log.warning("jail_scraper.pitt_webforms_page_error",
                                target=target, page=page_num)
                    break
                recs = _parse_pitt_grid(body)
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.pitt_webforms_fail", target=target,
                    error=str(exc)[:160])
        return out

    log.info("jail_scraper.pitt_webforms_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# "TheSheriffApp.com" / OCV platform (Florence SC)
# ---------------------------------------------------------------------------

def _sheriffapp_ocv_resolve_ref(value, chunk_map: dict[str, str]):
    """Resolve one Next.js RSC-protocol 'outlined' string reference (e.g. "$66")
    to its real value via chunk_map, or return value unchanged if it isn't a ref."""
    if isinstance(value, str) and re.match(r"^\$[0-9a-fA-F]+$", value):
        return chunk_map.get(value[1:])
    return value


def _sheriffapp_ocv_extract_rsc_chunks(raw_bytes: bytes) -> dict[str, str]:
    """Parse a Next.js RSC 'flight' stream response (content-type text/x-component)
    into {chunk_id: decoded_payload}.

    Live-verified 2026-11-05 against fcso.org/inmatesearchfeed: a naive split on
    b"\\n" corrupts this feed, because the page's own boilerplate disclaimer text
    (a length-prefixed "T" chunk) contains literal embedded newlines -- that
    swallows the START of the very next chunk (the one actually holding the
    roster's entries) onto the same bogus "line". T-type chunks are explicitly
    length-prefixed in hex BYTE count for exactly this reason
    ("<id>:T<hexlen>,<payload>"); every other row (a plain JSON value, or an
    "<id>:I[...]" module-import reference) is safe to newline-terminate, since a
    valid JSON string value can never contain a raw unescaped newline byte.
    Operates on bytes because the length prefix counts bytes, not str characters.
    """
    chunk_map: dict[str, str] = {}
    pos, n = 0, len(raw_bytes)
    id_re = re.compile(rb"([0-9a-fA-F]+):")
    t_re = re.compile(rb"T([0-9a-fA-F]+),")
    while pos < n:
        m = id_re.match(raw_bytes, pos)
        if not m:
            nl = raw_bytes.find(b"\n", pos)
            pos = (nl + 1) if nl != -1 else n
            continue
        cid = m.group(1).decode()
        pos = m.end()
        tm = t_re.match(raw_bytes, pos)
        if tm:
            length = int(tm.group(1), 16)
            pos = tm.end()
            chunk_map[cid] = raw_bytes[pos:pos + length].decode("utf-8", "replace")
            pos += length
            if pos < n and raw_bytes[pos:pos + 1] == b"\n":
                pos += 1
        else:
            nl = raw_bytes.find(b"\n", pos)
            end = nl if nl != -1 else n
            chunk_map[cid] = raw_bytes[pos:end].decode("utf-8", "replace")
            pos = end + 1
    return chunk_map


def _sheriffapp_ocv_find_entries(chunk_map: dict[str, str]) -> tuple[list[dict], dict]:
    """Locate the chunk holding blogData.entries/.pagination and parse it as JSON.

    Each non-"T" chunk row is independently valid JSON on its own (a React Server
    Components element tuple produced by the server's own JSON.stringify), so once
    isolated by _sheriffapp_ocv_extract_rsc_chunks it can be json.loads()'d
    directly -- no manual Flight-protocol object-graph reconstruction needed.
    """
    import json
    for payload in chunk_map.values():
        if '"entries"' in payload and '"pagination"' in payload:
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            stack = [parsed]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if "entries" in node and "pagination" in node:
                        return node["entries"], node["pagination"]
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    return [], {}


def _sheriffapp_ocv_booking_date_iso(raw: str | None) -> str | None:
    """'11/05/2026 10:31:00' -> '2026-11-05 10:31:00'.

    This vendor's own Booking Date string is MM/DD/YYYY HH:MM:SS (24h, WITH
    seconds) -- a shape this module's shared _parse_date() cannot match as-is (its
    US-format branch has no 24h+seconds pattern, only a bare-date, a 24h-no-seconds,
    and two 12h-with-AM/PM patterns). Reordering into 'YYYY-MM-DD HH:MM:SS' routes
    it through _parse_date()'s FIRST (ISO) format instead, which does take that
    exact shape -- full seconds precision kept, and _parse_date itself stays
    untouched.
    """
    if not raw:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})$", raw.strip())
    if not m:
        return raw
    mo, d, y, h, mi, s = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}:{s}"


def _parse_sheriffapp_ocv_entry(entry: dict, chunk_map: dict[str, str]) -> dict | None:
    """One blogData.entries[] item -> this module's inmate-record dict shape."""
    title = entry.get("title") or ""
    parts = _split_comma_name(title)
    if not parts:
        return None
    last, first = parts

    content = _sheriffapp_ocv_resolve_ref(entry.get("content"), chunk_map) or ""
    lines = [_strip_tags(x) for x in re.split(r"<br\s*/?>", content)]
    lines = [x for x in lines if x]

    singles: dict[str, str] = {}
    charges: list[dict] = []
    cur: dict = {}
    for line in lines:
        if ":" not in line:
            continue
        label, _, val = line.partition(":")
        label, val = label.strip(), val.strip()
        if label == "Description":
            if cur:
                charges.append(cur)
            cur = {"desc": val}
        elif label == "Charge Status":
            cur["status"] = val
        elif label == "Arresting Agency":
            cur["agency"] = val
        elif label not in singles:
            singles[label] = val
    if cur:
        charges.append(cur)

    mugshot_url = None
    images = entry.get("images") or []
    if images:
        ref = images[0].get("large") or images[0].get("small")
        mugshot_url = _sheriffapp_ocv_resolve_ref(ref, chunk_map)

    charge_descs = [c.get("desc", "") for c in charges if c.get("desc")]
    status = (singles.get("Status") or "").strip()

    return {
        "book_id": singles.get("Inmate ID") or None,
        "last": last, "first": first,
        "middle": _comma_middle(title) or None,
        "age": singles.get("Age") or None,
        "race": singles.get("Race") or None,
        "sex": singles.get("Sex") or None,
        "arrest_date": _sheriffapp_ocv_booking_date_iso(singles.get("Booking Date")),
        "charge": (charge_descs[0] if charge_descs else "")[:_CHARGE_CAP],
        "other_charges": ("; ".join(charge_descs[1:])[:_CHARGE_CAP] or None)
                         if len(charge_descs) > 1 else None,
        "release_status": ("in_custody" if status.lower() == "in custody"
                           else (status or "in_custody")),
        "booking_agency": charges[0].get("agency") if charges else None,
        "mugshot_url": mugshot_url,
    }


async def _fetch_sheriffapp_ocv(target: str) -> list[dict]:
    """Fetch current in-custody roster from a 'TheSheriffApp.com' / OCV platform
    site (Next.js app; footer reads 'v6.2.0 ... COPYRIGHT (c) 2026 OCV, LLC').

    target is the feed page's full URL, e.g. "https://www.fcso.org/inmatesearchfeed".

    No vendor-product match elsewhere in this file -- a standalone platform build
    (same "bespoke, not one of the vendor families above" situation as
    york_webforms), found+verified live 2026-11-05 for Florence County SC. The
    public page itself calls no plain JSON API; it server-renders the roster as a
    Next.js React Server Component and hands the client a 'flight' stream
    (self.__next_f.push(...) chunks embedded in the full HTML by default -- a
    3MB page at this county's roster size). Live network-trace discovery found a
    much cheaper path: requesting the SAME route with header `RSC: 1` makes the
    server return just the raw flight stream directly (content-type
    text/x-component, 1-1.3MB instead of 3MB+, and far simpler to parse -- no
    double-JSON-escaping to undo). Confirmed this needs no real `_rsc`
    cache-busting query value (any string works, it is not validated server-side)
    and no prior session: the page's own /api/internal/guest-session POST that a
    real browser fires on page load 401s under curl_cffi chrome impersonation and
    turned out to be unnecessary anyway -- the feed itself returns full real data
    without it, so this fetcher skips that call rather than carry a guaranteed
    failure forward. `limit` is honored server-side up to a cap of 250 per page
    (requesting more, e.g. 1000, is silently clamped back to 250). Verified live:
    627 total in-custody records, 3 pages (250+250+127) exactly matching the
    vendor's own reported totalEntries on every page, 100% resolved to a real
    per-booking Inmate ID (used below as book_id), 0 arrest_date values this
    module's own _parse_date() failed to parse, 0 case_number collisions through
    _booking_identity(). Sample cross-checked against live site: CANNON, TEYON
    RAJAE DEQUAN, Inmate ID 49272, Booking Date 11/05/2026 10:31:00, Status In
    Custody, charges DISCHARGING FIREARM IN THE CITY LIMITS / BREACH OF PEACE
    AGGRAVATED IN NATURE.

    Each entry's `content` (the HTML "Inmate Information" block) and `images`
    fields are sometimes inlined and sometimes "outlined" by Next's Flight
    protocol -- hoisted into a separate chunk and left as a "$<id>" back-reference
    once the string is long enough (found live: 166/627, 26%, of this feed's
    `content` blobs were refs, not inline text -- silently losing an entry's ENTIRE
    Inmate ID/age/race/sex/charges without the resolve step in
    _sheriffapp_ocv_resolve_ref -- first pass of this fetcher shipped without that
    resolve and silently dropped book_id on exactly those 166 rows before this was
    caught by checking book_id coverage against the full roster rather than just a
    front-page sample). mugshot_url is a 1-hour presigned S3 URL: real and directly
    fetchable at scrape time, but will 403 if stored and opened much later --
    same "don't treat as a permanent URL" caveat as this module's existing
    p2c_centralsquare ImageId-mugshot field, just expiring instead of needing auth.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            page = 1
            while True:
                r = await s.get(
                    target,
                    params={"page": page, "limit": 250, "_rsc": "x"},
                    headers={"RSC": "1"},
                    timeout=30,
                )
                if r.status_code != 200 or "text/x-component" not in (
                        r.headers.get("content-type") or ""):
                    break
                chunk_map = _sheriffapp_ocv_extract_rsc_chunks(r.content)
                entries, pagination = _sheriffapp_ocv_find_entries(chunk_map)
                if not entries:
                    break
                for entry in entries:
                    rec = _parse_sheriffapp_ocv_entry(entry, chunk_map)
                    if rec:
                        out.append(rec)
                if not pagination.get("next"):
                    break
                page += 1
                if page > 20:  # safety cap; ~627/250 = 3 pages at time of writing
                    break
                await asyncio.sleep(0.3)  # polite pacing
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.sheriffapp_ocv_fail", target=target,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.sheriffapp_ocv_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Durham County NC -- standalone ASP.NET WebForms "Inmate Population Search" (county-built)
# ---------------------------------------------------------------------------

def _durham_clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def _split_durham_name(raw: str) -> tuple[str, str, str | None] | None:
    """'ANTHONY, JOHNNY, EARL' -> ('ANTHONY', 'JOHNNY', 'EARL'); 'ARMANI, KEVIN' ->
    ('ARMANI', 'KEVIN', None). Durham's own format is comma-separated on EVERY part
    (last, first, middle), unlike every other vendor in this file -- `_split_comma_name`
    assumes only ONE comma (space-separated rest), which would leave a trailing comma
    glued onto the first name here (e.g. 'JOHNNY,'), so this needs its own splitter.
    """
    toks = [t.strip() for t in (raw or "").split(",") if t.strip()]
    if len(toks) < 2:
        return None
    last, first = toks[0].upper(), toks[1].upper()
    middle = toks[2].upper() if len(toks) > 2 else None
    return last, first, middle


_DURHAM_NAME_HEADER = '<td class="rvsnavy" colspan="8">'
_DURHAM_NAME_RE = re.compile(
    r'^&nbsp;<a class="rvsnavy-bold" target="_blank" href="([^"]+)">([^<]+)</a></td>'
)
_DURHAM_OFFENDER_ID_RE = re.compile(r'offenderID=([A-Za-z0-9]+)')
_DURHAM_ROW_RE = re.compile(
    r'<tr>\s*<td[^>]*>(.*?)</td><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td>'
    r'<td[^>]*>(.*?)</td><td[^>]*>(.*?)</td><td[^>]*>(.*?)</td>'
    r'<td[^>]*>(.*?)</td><td[^>]*>(.*?)</td>\s*</tr>',
    re.S,
)


def _parse_durham_page(body: str) -> list[dict]:
    """Parse Durham County NC's Inmate Population Search (IPS) results table -- a
    classic ASP.NET WebForms page, no JSON API, one <table id="Table1"> holding a flat
    sequence of per-inmate blocks: a name/VINE-link header row, a column-header row, then
    1+ charge rows (one jail stay can carry several pending charges/dockets at once).
    Live-verified 2026-11-05 on the "Incarcerated" filter: 531 blocks, 531 unique
    offenderIDs, 510 unique real court dockets (21 records carry the vendor's own
    '[N/A]' sentinel instead -- federal detainers / holds with no court case yet).

    Row-parsing note: the vendor's own markup is malformed on short stays -- the "Days
    In Jail/Charge" cell sometimes reads literally `<td ...><1</td>` (an unescaped bare
    "<" inside the cell, not a tag). `_DURHAM_ROW_RE`'s non-greedy `(.*?)` still finds
    the correct cell boundary because it scans for the next LITERAL "</td>" substring
    rather than the next "<" -- confirmed live, this does not misalign later columns.
    """
    out: list[dict] = []
    for chunk in (body or "").split(_DURHAM_NAME_HEADER)[1:]:
        nm = _DURHAM_NAME_RE.match(chunk)
        if not nm:
            continue
        href, raw_name = nm.group(1), html.unescape(nm.group(2))
        parts = _split_durham_name(raw_name)
        if not parts:
            continue
        last, first, middle = parts

        charges = []
        for rowm in _DURHAM_ROW_RE.finditer(chunk):
            cells = [_durham_clean(c) for c in rowm.groups()]
            if cells[0] == "Date Confined":
                continue  # the repeated column-header row matches the same 8-<td> shape
            charges.append(cells)
        if not charges:
            continue

        confined, _charged, _released, statute, bond_type, bond_amt, docket, days = charges[0]
        docket = docket if docket and docket != "[N/A]" else None
        other = [c[3] for c in charges[1:] if c[3]]

        oid_m = _DURHAM_OFFENDER_ID_RE.search(href)
        out.append({
            "last": last, "first": first, "middle": middle,
            "arrest_date": confined or None,
            "charge": (statute or "")[:_CHARGE_CAP],
            "other_charges": ("; ".join(other)[:_CHARGE_CAP]) or None,
            "docket_number": docket,
            "release_status": "in_custody",
            # Not in the Listing schema today (ignored by _to_listing, same as York's
            # own extra "bond"/"city"/"state"/"zip"/"charges" fields) -- kept on the raw
            # dict anyway since it's real page data at zero extra request cost. Durham's
            # bond amount is PER CHARGE, not a vendor-reported aggregate, so this is
            # deliberately NOT mapped onto the canonical "total_bond_amount" key (that
            # would misrepresent a single charge's bond as a booking-wide total).
            "bond_type": bond_type or None,
            "bond_amount": bond_amt or None,
            "days_in_jail": days or None,
            "offender_id": oid_m.group(1) if oid_m else None,
            "charges": [
                {"date_confined": c[0], "date_charged": c[1], "date_released": c[2],
                 "statute": c[3], "bond_type": c[4], "bond_amount": c[5],
                 "docket": c[6] if c[6] != "[N/A]" else None, "days_in_jail": c[7]}
                for c in charges
            ],
        })
    return out


async def _fetch_durham_webforms(target: str) -> list[dict]:
    """Durham County NC Sheriff's Office Inmate Population Search (IPS) -- a standalone
    ASP.NET WebForms page (no vendor-product match in this file; a county-built system,
    same category as York SC's own _fetch_york_webforms above). target is the page URL,
    e.g. "https://www2.dconc.gov/sheriff/ips".

    FOUND 2026-11-05 (live verification): a bare GET renders the WHOLE roster in one
    response (no paging needed, unlike York) -- but the page's own "Date Listing" filter
    (<select id="ddlDateListing">) defaults to "Last 24 Hours" (value "1"), NOT the full
    current population. Live-verified: a bare GET returned only 30 records ("Records
    Found: 30"); this matches this scraper file's OWN module docstring ("current
    in-custody inmates") only by coincidence of how many people happened to be booked in
    the last day, so it is the wrong default to ship -- the research pass that scoped
    this build (which saw 27 records on a bare GET) was almost certainly looking at this
    same "Last 24 Hours" default, not the true current population. This fetcher
    explicitly replays the page's own __doPostBack('ddlDateListing', '') postback with
    ddlDateListing=0 ("Incarcerated") to get the TRUE current population --
    live-verified 531 records that way (vs 30 on the untouched default, 475 on the
    "Last 30 Days" alternative), stable across 3 separate fresh-session runs. The
    postback's form target is NOT the visited URL itself (POSTing back to the bare
    "/sheriff/ips" 405s -- "HTTP verb ... not allowed") but the page's own
    <form action="default.aspx">, i.e. "/sheriff/ips/default.aspx" -- resolved here
    relative to `target` rather than hardcoded, in case a future roster entry on this
    same vendor ever points at a different virtual directory.

    No DOB/age/race/sex anywhere on this page (unlike most other vendors in this file) --
    genuinely not published, not a parsing gap. Each inmate's name links out to
    vinelink.com (VINE victim-notification signup); that offenderID is real and
    person-stable but is NOT used for dedupe identity here (an inmate's lifetime VINE
    offenderID could get reused on a FUTURE, unrelated booking of the same person, which
    is exactly the false-collision failure mode _booking_identity's own docstring warns
    about) -- the court docket number is used instead, matching this build's brief;
    510/531 live-verified unique across the full roster. offender_id is still carried
    through as a plain field for anyone who wants it later.
    """
    from curl_cffi.requests import AsyncSession

    def _hidden(body: str, name: str) -> str:
        m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', body)
        return m.group(1) if m else ""

    base = target if target.endswith("/") else target + "/"
    post_url = urljoin(base, "default.aspx")

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=30)
            body = r.text or ""
            vs = _hidden(body, "__VIEWSTATE")
            vsg = _hidden(body, "__VIEWSTATEGENERATOR")
            ev = _hidden(body, "__EVENTVALIDATION")
            if not vs:
                log.warning("jail_scraper.durham_no_viewstate", target=target)
                return []

            data = {
                "__EVENTTARGET": "ddlDateListing", "__EVENTARGUMENT": "",
                "__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vsg, "__EVENTVALIDATION": ev,
                "ddlDateListing": "0", "ddlNameIndex": "All",
            }
            r2 = await s.post(post_url, data=data, timeout=45,
                               headers={"Referer": target})
            out = _parse_durham_page(r2.text or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.durham_fail", target=target, error=str(exc)[:120])
        return []

    log.info("jail_scraper.durham_ok", target=target, count=len(out))
    return out


# --- _fetch_roster dispatcher: add this elif branch (dispatch table, ~line 1234) ---
#     elif vendor == "durham_webforms":
#         return await _fetch_durham_webforms(target)


# ---------------------------------------------------------------------------
# Lee County NC -- Southern Software DCN (Detention Center Network), self-hosted DevExpress grid
# ---------------------------------------------------------------------------

_XLSX_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Maps the export's own column headers (read fresh off row 1 every run, not
# hardcoded by column letter -- DevExpress lets column order/visibility be
# end-user-customized via the grid's own "Column Chooser" and the export
# honors that, so trusting fixed letters would be fragile) to this file's
# rec-dict field names.
_DCN_HEADER_MAP = {
    "Full Name": "full_name",
    "First Name": "first",
    "Middle Name": "middle",
    "Last Name": "last",
    "Age": "age",
    "Race": "race",
    "Sex": "sex",
    "Admit Date": "admit_date",
    "Primary Charge Court Type": "court_type",
    "Primary Charge": "charge",
    "Arresting Agency": "booking_agency",
}

# A real docket/case number embedded at the start of (or inside) the charge
# text, e.g. "26CR387713-520 MAG ORDR-F-POSSESSION OF FIREARM BY FELON" ->
# "26CR387713-520". Live-sampled 2026-11-05 on Lee County's own export:
# 112/120 charge strings carry one; the rest ("PAROLE VIOLATION", a bare
# "SMCP", etc.) genuinely have none and fall through to _booking_identity's
# own name+arrest_date hash fallback (which this vendor's arrest_date -- see
# below -- is populated on 100% of rows to support).
_DOCKET_RE = re.compile(r"\b(\d{2}[A-Z]{1,3}0*\d{3,}-?\d{0,4})\b")

# Excel's day-0 epoch (1899-12-30, NOT 1900-01-01 -- this already bakes in
# the standard correction for Excel's fictitious 1900-02-29 leap-day bug).
# Confirmed correct live by decoding real serials against the on-screen
# grid's own Admit Date column for the same inmates: 46255 -> 2026-08-21,
# 46232 -> 2026-07-29, 46327 -> 2026-11-01, all exact matches.
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _xlsx_rows(xlsx_bytes: bytes) -> list[dict]:
    """Parse a DevExpress ASPxGridView XLSX export into row dicts keyed by
    this file's field names (via _DCN_HEADER_MAP), stdlib-only (no openpyxl/
    pandas -- neither is a project dependency; zipfile + xml.etree is).

    Column-letter-POSITIONAL parsing was tried first and is UNSAFE: live-
    verified rows that skip a blank cell (e.g. no Middle Name, or no Primary
    Charge Court Type) genuinely omit that <c> element entirely instead of
    emitting an empty one, which shifts every later column left by one if
    read positionally -- confirmed live, e.g. a real row's cells were
    ['A','B','D','E','F','G','H'] (skipping 'C', the blank Middle Name).
    Reads each cell's own `r="C7"` reference and keys off the column LETTER
    instead, which is immune to this.
    """
    z = zipfile.ZipFile(BytesIO(xlsx_bytes))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        sst_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in sst_root.findall("m:si", _XLSX_NS):
            shared.append("".join((t.text or "") for t in si.findall(".//m:t", _XLSX_NS)))

    sheet_name = next((n for n in z.namelist() if n.startswith("xl/worksheets/sheet")), None)
    if not sheet_name:
        return []
    root = ET.fromstring(z.read(sheet_name))
    sheet_rows = root.findall(".//m:sheetData/m:row", _XLSX_NS)
    if not sheet_rows:
        return []

    def cell_value(c):
        v = c.find("m:v", _XLSX_NS)
        if v is None or v.text is None:
            return None
        return shared[int(v.text)] if c.get("t") == "s" else v.text

    def row_by_column_letter(row) -> dict[str, str]:
        out: dict[str, str] = {}
        for c in row.findall("m:c", _XLSX_NS):
            ref = c.get("r") or ""
            m = re.match(r"([A-Z]+)", ref)
            if not m:
                continue
            val = cell_value(c)
            if val is not None:
                out[m.group(1)] = val
        return out

    header_cells = row_by_column_letter(sheet_rows[0])
    col_to_field = {
        col: _DCN_HEADER_MAP[text]
        for col, text in header_cells.items()
        if text in _DCN_HEADER_MAP
    }

    out_rows: list[dict] = []
    for row in sheet_rows[1:]:
        cells = row_by_column_letter(row)
        rec = {field: cells[col] for col, field in col_to_field.items() if col in cells}
        if rec:
            out_rows.append(rec)
    return out_rows


async def _fetch_dcn_export(target: str) -> list[dict]:
    """Fetch current in-custody roster from Southern Software's DCN
    (Detention Center Network) product via its ASPxGridView's built-in
    "Export" button -- NOT by scraping the rendered grid HTML.

    DCN is a self-hosted, DevExpress ASPxGridView WebForms product -- a
    DIFFERENT Southern Software product from this file's own Citizen Connect
    vendor (different URL shape, no AgencyID/JMSAgencyID query params,
    hosted on the county's own domain instead of cc.southernsoftware.com).

    Why export instead of paging the grid: the grid's own pagination (Next/
    page-size) runs through DevExpress's ASPxCallback/WebForm_DoCallback
    protocol, whose __CALLBACKPARAM embeds an opaque "KV|<n>" counter and a
    per-client-instance sequence number alongside the full list of the
    current page's row keys -- live-tested exhaustively 2026-11-05 (byte-
    identical replay of a real captured callback, same session, a freshly
    re-paired __VIEWSTATE/__VIEWSTATEGENERATOR, identical row-key list): the
    server still throws "Callback request failed due to an internal server
    error" unless those opaque counters were generated by a real JS runtime
    for that exact VIEWSTATE. Not safely reproducible without one. (Also
    checked per the brief: /DCN/WebServices/InmateWebService.asmx and
    ChargeWebService.asmx are real, live SOAP endpoints -- but each exposes
    exactly one operation, GetInmateNames / GetChargeDescriptions, returning
    a bare ArrayOfString for autocomplete boxes, not full booking records.
    Not useful here.)

    The grid's "Export" button is a PLAIN ASP.NET WebForms postback instead
    (WebForm_DoPostBackWithOptions, confirmed straight from this page's own
    inline script -- not the callback path) -- __EVENTTARGET=
    "gvInmates$footer0$export" + a freshly-paired __VIEWSTATE/
    __VIEWSTATEGENERATOR is the whole request; no event-validation field
    exists on this page (EnableEventValidation is off) and no opaque
    counters are involved. Live-verified 2026-11-05 (3 separate runs):
    returns a real Content-Disposition: attachment .xlsx
    (ConfinedInmates-<date>.xlsx) with ALL 136/136 current inmates in one
    response -- the grid's own on-screen pagination (page size 100) would
    have needed the fragile callback dance above just to see the other 36.
    The export also carries columns the on-screen grid never shows at all
    (full charge text with an embedded docket number, arresting agency) --
    richer than the 5-column grid (Name/Age/Race/Sex/Admit Date) the brief
    described. No DOB column exists on this vendor's export; arrest_date
    (Admit Date) is populated on 100% of rows instead, which is what
    _booking_identity's hash fallback needs when a row has no docket number.

    `target` is the DCN Inmates page URL itself, e.g.
    "https://dcn.leecountync.gov/DCN/Inmates" -- the export POSTs back to
    this exact same URL.
    """
    from curl_cffi.requests import AsyncSession

    def _hidden(html_body: str, name: str) -> str:
        m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html_body)
        return m.group(1) if m else ""

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=30)
            body = r.text or ""
            vs = _hidden(body, "__VIEWSTATE")
            vsg = _hidden(body, "__VIEWSTATEGENERATOR")
            if not vs:
                log.warning("jail_scraper.dcn_export_no_viewstate", target=target)
                return []

            data = {
                "__EVENTTARGET": "gvInmates$footer0$export",
                "__EVENTARGUMENT": "",
                "__VIEWSTATE": vs,
                "__VIEWSTATEGENERATOR": vsg,
            }
            er = await s.post(
                target, data=data, timeout=45,
                headers={
                    "Referer": target,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            content = er.content or b""
            if not content.startswith(b"PK"):
                log.warning("jail_scraper.dcn_export_not_xlsx", target=target,
                            status=er.status_code, content_type=er.headers.get("content-type"))
                return []
            rows = _xlsx_rows(content)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.dcn_export_fail", target=target, error=str(exc)[:160])
        return []

    for row in rows:
        last = (row.get("last") or "").strip().upper()
        first = (row.get("first") or "").strip().upper()
        if not last or not first:
            continue
        charge = (row.get("charge") or "").strip()
        docket = None
        if charge:
            dm = _DOCKET_RE.search(charge)
            if dm:
                docket = dm.group(1)

        admit_raw = row.get("admit_date")
        admit_date_str = None
        if admit_raw:
            try:
                admit_date_str = (_EXCEL_EPOCH + timedelta(days=int(float(admit_raw)))).strftime("%m/%d/%Y")
            except (ValueError, TypeError):
                admit_date_str = None

        out.append({
            "last": last,
            "first": first,
            "middle": (row.get("middle") or "").strip().upper() or None,
            "age": row.get("age"),
            "race": row.get("race"),
            "sex": row.get("sex"),
            "arrest_date": admit_date_str,
            "charge": charge[:_CHARGE_CAP],
            "docket_number": docket,
            "booking_agency": row.get("booking_agency"),
            # This export is literally named "Confined Inmates" -- every row
            # on it is, by construction, a person currently in custody.
            "release_status": "in_custody",
        })
    log.info("jail_scraper.dcn_export_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Darlington County SC -- Southern Software DCN (same product family as Lee County NC)
# ---------------------------------------------------------------------------

async def _fetch_darlington_dcn(base: str) -> list[dict]:
    """Darlington County SC -- DCN (county-built, DevExpress ASPxGridView) current in-custody
    roster (W.Glenn Campbell Detention Center). Same underlying product family as other
    DCN-branded county jail sites (ASPxGridView grid, /DCN/WebResource.axd + /DCN/DXR.axd static
    handlers, ASP.NET_SessionId cookie, noindex meta tag). No vendor-product match among this
    file's existing 6 fetchers -- a standalone county-built system, same class as York SC.

    Checked the DCN WebServices .asmx endpoints first, per this build's own brief: index.js calls
    WebServices/InmateWebService.asmx/GetInmateNames and WebServices/ChargeWebService.asmx/
    GetChargeDescriptions, but live-verified both are autocomplete-only (free-text name/charge
    typeahead for the search boxes), not a bulk-roster method -- a dead end for a full fetch.

    The on-screen grid at /dcn/inmates only renders 5 visible columns (Full Name, Age, Race, Sex,
    Admit Date) and paginates at 100/page (206 total in custody, live-verified 2026-11-05) through
    a DevExpress AJAX callback whose argument is an opaque encoded blob, not a plain postback
    target -- not worth reverse-engineering. Instead this calls the grid's own "Export" button
    server-side: confirmed live by hooking HTMLFormElement.submit() in a real browser tab on this
    exact page and reading back the field set a real Export click serializes. That reduced to a
    classic ASP.NET WebForms postback -- __EVENTTARGET=gvInmates$footer0$export,
    __EVENTARGUMENT=Click, plus the page's own __VIEWSTATE/__VIEWSTATEGENERATOR (EnableEventValidation
    is confirmed off -- no __EVENTVALIDATION field exists anywhere on the page) -- every other
    field the browser's FormData included is a client-only UI-state blob (filter row, pager
    page-size popup, calendar widget) that is NEVER rendered as an actual HTML input on a fresh
    GET, only synthesized by the grid's own init JS; replaying just the 4 real fields above is
    confirmed sufficient. The server answers with a real .xlsx attachment -- live-verified
    2026-11-05: "ConfinedInmates-2026-11-05.xlsx", 20,807 bytes, ALL 206 rows in one shot, no grid
    pagination needed at all.

    Bonus: the export's own columns are richer than the on-screen grid -- First/Middle/Last split
    out, Primary Charge, and Arresting Agency are all included even though none of those three are
    visible on-screen (confirmed via the exported sharedStrings.xml, e.g. row 1: "FAIL TO APPEAR
    SHOPLIFTING*" / "DARLINGTON City - SC0160100"). No per-inmate detail-page hydration needed --
    unlike Tyler/p2c_jqgrid's mugshot-only detail pattern elsewhere in this file, this vendor's
    bulk export already carries charge data directly.

    Parsed with stdlib zipfile + a light regex reader (xlsx is just a zip of small XML parts) --
    no openpyxl dependency needed for the 2 worksheet parts this uses. Admit Date arrives as a raw
    Excel 1900-system date serial (e.g. 46329); converted via the standard datetime(1899,12,30)+
    timedelta(days=serial) formula, live cross-checked against the on-screen grid's own rendering
    of the same 4 rows (46329->11/03/2026, 45700->02/12/2025, 46295->09/30/2026, 46199->06/26/2026,
    all exact matches).

    book_id: the SAME initial GET that seeds VIEWSTATE for the export postback is also the grid's
    own first HTML page (first 100 of 206, alphabetical by name -- the same default order the
    export uses). Its rows already carry a real per-booking `bid` querystring token on each
    inmate's detail link (e.g. '/DCN/inmate-details?id=X0Yq0vb5q6Q%253d&bid=5kwMFQ6LWKM%253d'),
    live-confirmed distinct per row. Harvested for free from the one request already being made
    and merged onto the xlsx rows by exact full-name match -- live-verified covering exactly 100
    of 206 rows with a real vendor id; the remaining 106 (only reachable via grid pages 2-3, not
    separately fetched here) fall through to _booking_identity()'s name+arrest_date hash fallback,
    which is safe here because Admit Date is populated on all 206/206 rows and a live check found
    zero (last, first, arrest_date) collisions across the full roster.
    """
    import io
    import zipfile
    from datetime import timedelta

    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/inmates", timeout=30)
            body = r.text or ""

            def _hidden(name: str) -> str:
                m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', body)
                return m.group(1) if m else ""

            viewstate = _hidden("__VIEWSTATE")
            viewstategen = _hidden("__VIEWSTATEGENERATOR")
            if not viewstate:
                log.warning("jail_scraper.darlington_dcn_no_viewstate", base=base)
                return []

            # Harvest real per-booking ids from the grid's own page-1 rows (see docstring).
            bid_by_name: dict[str, str] = {}
            for m in re.finditer(
                    r"<a href='/DCN/inmate-details\?id=[^&]*&bid=([^']*)'>\s*([^<]+?)\s*</a>", body):
                bid_token, flat_name = m.group(1), html.unescape(m.group(2)).strip().upper()
                if flat_name:
                    bid_by_name[flat_name] = bid_token

            # Replay the grid's own "Export" button as a classic ASP.NET postback (see docstring
            # for how this field set was derived and confirmed sufficient).
            data = {
                "__EVENTTARGET": "gvInmates$footer0$export",
                "__EVENTARGUMENT": "Click",
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategen,
            }
            xr = await s.post(f"{base}/inmates", data=data, timeout=45)
            content = xr.content or b""
            if content[:2] != b"PK":
                log.warning("jail_scraper.darlington_dcn_bad_export", base=base,
                            status=xr.status_code, length=len(content))
                return []

            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                shared = zf.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")

            strings = [html.unescape(s) for s in
                       re.findall(r"<si><t[^>]*>(.*?)</t></si>", shared, re.S)]

            rows: list[dict[str, str]] = []
            for row_m in re.finditer(r"<row[^>]*>(.*?)</row>", sheet, re.S):
                cells: dict[str, str] = {}
                for cell_m in re.finditer(r"<c ([^>]*)>(?:<v>([^<]*)</v>)?</c>", row_m.group(1)):
                    attrs, val = cell_m.groups()
                    if val is None:
                        continue
                    ref_m = re.search(r'r="([A-K])\d+"', attrs)
                    if not ref_m:
                        continue
                    col = ref_m.group(1)
                    type_m = re.search(r't="(\w*)"', attrs)
                    if type_m and type_m.group(1) == "s":
                        idx = int(val)
                        val = strings[idx] if 0 <= idx < len(strings) else ""
                    cells[col] = val
                if cells:
                    rows.append(cells)

            # Columns A-K: FullName,FirstName,MiddleName,LastName,Age,Race,Sex,AdmitDate,
            # PrimaryChargeCourtType(unused),PrimaryCharge,ArrestingAgency.
            if not rows or rows[0].get("A") != "Full Name":
                log.warning("jail_scraper.darlington_dcn_header_mismatch", base=base,
                            first_row=rows[0] if rows else None)
                return []

            for cells in rows[1:]:
                full_name = (cells.get("A") or "").strip()
                last = (cells.get("D") or "").strip().upper()
                first = (cells.get("B") or "").strip().upper()
                if not (last and first):
                    parts = _split_comma_name(full_name)
                    if not parts:
                        continue
                    last, first = parts
                middle = (cells.get("C") or "").strip().upper() or None
                admit_serial = cells.get("H")
                admit_date = None
                if admit_serial:
                    try:
                        admit_date = (datetime(1899, 12, 30)
                                      + timedelta(days=float(admit_serial))).strftime("%m/%d/%Y")
                    except (ValueError, TypeError):
                        admit_date = None
                out.append({
                    "last": last, "first": first, "middle": middle,
                    "age": cells.get("E") or None,
                    "race": cells.get("F") or None,
                    "sex": cells.get("G") or None,
                    "arrest_date": admit_date,
                    "charge": (cells.get("J") or "")[:_CHARGE_CAP],
                    "booking_agency": cells.get("K") or None,
                    "facility": "W.Glenn Campbell Detention Center",
                    "book_id": bid_by_name.get(full_name.strip().upper()),
                    # This export is specifically the CURRENT-confinements roster (the file is
                    # literally named "ConfinedInmates-<date>.xlsx"), so every row is in custody.
                    "release_status": "in_custody",
                })
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.darlington_dcn_fail", base=base, error=str(exc)[:160])
        return []

    log.info("jail_scraper.darlington_dcn_ok", base=base, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Orange County NC -- Wix-embedded periodically-republished PDF
# ---------------------------------------------------------------------------
# No vendor-product match (bespoke, one-off): there is no live searchable roster
# database for Orange NC at all. The only public source is the Sheriff's "Daily In
# Custody Report by Facility" -- a PDF that gets regenerated and re-uploaded to a NEW
# url every time it's republished, embedded on the detainees page via a Wix
# pdf-flipbook viewer widget. Verified live 2026-11-05: 105 in-custody records,
# facility "NEW JAIL", confinement reason "PRETRIAL/ARREST".

_ORANGE_FLIPBOOK_RE = re.compile(r'<pdf-flipbook\s+widget-data="([^"]*)"')
_ORANGE_DOWNLOAD_BTN_RE = re.compile(
    r'href="(https?://[^"]+?\.pdf)"[^>]*aria-label="Download PDF"')
_ORANGE_REPORT_TS_RE = re.compile(
    r"User:.*?(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})")
_ORANGE_DOCKET_RE = re.compile(r"\b\d{2}[A-Z]{2,4}[A-Z0-9\-]{2,}\b")
_ORANGE_BOND_RE = re.compile(r"\$[\d,]+")
_ORANGE_MAX_STALE_DAYS = 3

# Column x0 boundaries in the PDF's fixed-position text layout (no real table
# structure -- pdfplumber's own find_tables() returns zero; derived from the header
# row + many sampled data rows, live-verified 2026-11-05).
_ORANGE_COL_BOUNDS = [
    ("name", 0, 150),
    ("aj", 150, 165),
    ("race", 165, 173),
    ("sex", 173, 193),
    ("bk", 193, 222),
    ("attorney", 222, 300),   # public defender / attorney name -- discarded, not in schema
    ("charge", 300, 628),
    ("booked_date", 628, 685),
    ("booked_time", 685, 715),
    ("days", 715, 10_000),
]

_ORANGE_BANNER_RES = [
    re.compile(r"^User:"),
    re.compile(r"^Daily In Custody Report by Facility"),
    re.compile(r"^Confinement Reason:"),
    re.compile(r"^Facility:"),
    re.compile(r"^Days\s*In\s*$"),
    re.compile(r"^Name\s+A/J\s+R/S\s+Bk"),
    # Page footer: usually "Daily In Custody Report by Facility Page N" (caught by
    # the title prefix above), but live-observed page 1 of the 2026-11-05 run instead
    # printed the report's internal template code with no title prefix ("jincst3 Page
    # 1") -- match the "Page N" suffix alone so either form is caught regardless of
    # what precedes it.
    re.compile(r"Page\s+\d+\s*$"),
]


def _orange_col_for(x0: float) -> str:
    for name, lo, hi in _ORANGE_COL_BOUNDS:
        if lo <= x0 < hi:
            return name
    return "charge"


def _orange_group_lines(words: list[dict], tol: float = 3.0) -> list[list[dict]]:
    """Cluster pdfplumber words into visual rows by vertical position.

    Intra-row 'top' jitter observed live is <1pt; inter-row gaps are ~9-10pt, so a
    3pt tolerance cleanly separates rows without merging adjacent ones.
    """
    ws = sorted(words, key=lambda w: w["top"])
    lines: list[list[dict]] = []
    cur: list[dict] = []
    last_top = None
    for w in ws:
        if last_top is not None and (w["top"] - last_top) > tol:
            lines.append(cur)
            cur = []
        cur.append(w)
        last_top = w["top"]
    if cur:
        lines.append(cur)
    return lines


def _orange_line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))


def _orange_bucket(line: list[dict]) -> dict[str, str]:
    buckets: dict[str, list[dict]] = {}
    for w in line:
        buckets.setdefault(_orange_col_for(w["x0"]), []).append(w)
    return {
        col: " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))
        for col, ws in buckets.items()
    }


def _parse_orange_pdf(pdf_bytes: bytes) -> tuple[list[dict], datetime | None]:
    """Pure: parse the 'Daily In Custody Report by Facility' PDF into inmate dicts.

    This PDF has NO underlying table structure -- the grid is laid out purely by
    fixed x-coordinate text columns: Name | A/J | R/S | Bk # | Attorney | Charge(s)
    (itself a '/'-joined sub-record: desc/agency/judstatus/docket/bond/status/type[/
    crt/crtdate]) | Booked Date | Booked Time | Days In Custody. A booking's charges,
    and occasionally its own name, wrap onto continuation rows with no Bk # of their
    own -- a row is a NEW record iff its 'bk' column is a bare 3-8 digit number (the
    only thing ever found in that narrow x-range); every row that isn't is folded into
    the current record's name continuation / extra charge line. This correctly spans
    page breaks (live-verified: a 4th charge line for one inmate and the next inmate's
    new record both land correctly across a page boundary) because `current` is never
    reset per page.

    Returns (records, report_ts) -- report_ts is parsed from the PDF's own
    "User: <name> MM/DD/YYYY HH:MM:SS" banner on page 1 (the county's own generation
    timestamp for the report), which the caller uses to verify this isn't a stale
    cached PDF before trusting it as "current detainees".
    """
    import io

    import pdfplumber

    records: list[dict] = []
    current: dict | None = None
    facility: str | None = None
    confinement_reason: str | None = None
    report_ts: datetime | None = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if not words:
                continue
            for line in _orange_group_lines(words):
                full_text = _orange_line_text(line)
                if any(r.search(full_text) for r in _ORANGE_BANNER_RES):
                    if page_no == 0 and report_ts is None:
                        tm = _ORANGE_REPORT_TS_RE.search(full_text)
                        if tm:
                            # Not routed through the shared _parse_date(): its format
                            # list has no 24h-with-seconds pattern (only %H:%M for
                            # 24h, %I:%M:%S %p for 12h), and this is an internal
                            # freshness check, not the arrest_date field, so it
                            # doesn't need to share that helper's exact format set.
                            try:
                                report_ts = datetime.strptime(
                                    f"{tm.group(1)} {tm.group(2)}", "%m/%d/%Y %H:%M:%S")
                            except ValueError:
                                report_ts = None
                    fm = re.match(r"^Facility:\s*(.+)$", full_text)
                    if fm:
                        facility = fm.group(1).strip()
                    cm = re.match(r"^Confinement Reason:\s*(.+)$", full_text)
                    if cm:
                        confinement_reason = cm.group(1).strip()
                    continue

                cols = _orange_bucket(line)
                bk = (cols.get("bk") or "").strip()
                if re.fullmatch(r"\d{3,8}", bk):
                    if current is not None:
                        records.append(current)
                    current = {
                        "name_parts": [cols.get("name", "").strip()],
                        "aj": cols.get("aj", "").strip(),
                        "race": cols.get("race", "").strip() or None,
                        "sex": cols.get("sex", "").strip() or None,
                        "book_id": bk,
                        "charges": [cols.get("charge", "").strip()] if cols.get("charge") else [],
                        "booked_date": re.sub(r"^[/\s]+", "", cols.get("booked_date", "")).strip(),
                        "booked_time": cols.get("booked_time", "").strip(),
                        "facility": facility,
                        "confinement_reason": confinement_reason,
                    }
                elif current is not None:
                    nm = cols.get("name", "").strip()
                    if nm:
                        current["name_parts"].append(nm)
                    ch = cols.get("charge", "").strip()
                    if ch:
                        current["charges"].append(ch)
        if current is not None:
            records.append(current)

    for rec in records:
        parts = rec.pop("name_parts")
        first_line = parts[0] if parts else ""
        rest = " ".join(p for p in parts[1:] if p)
        rec["raw_name"] = f"{first_line} {rest}".strip() if rest else first_line

    return records, report_ts


def _orange_record_to_dict(rec: dict) -> dict | None:
    """Convert one parsed PDF row into this scraper's common inmate-dict schema."""
    parts = _split_comma_name(rec["raw_name"])
    if not parts:
        return None
    last, first = parts
    middle = _comma_middle(rec["raw_name"]) or None

    charges = [c for c in rec.get("charges", []) if c]
    charge = (charges[0] if charges else "")[:_CHARGE_CAP]
    other_charges = "; ".join(charges[1:])[:_CHARGE_CAP] if len(charges) > 1 else None

    docket_m = _ORANGE_DOCKET_RE.search(charge)
    bond_m = None
    for c in charges:
        bond_m = _ORANGE_BOND_RE.search(c)
        if bond_m:
            break

    booked_date = rec.get("booked_date") or ""
    booked_time = rec.get("booked_time") or ""
    arrest_date = booked_date
    if re.fullmatch(r"\d{4}", booked_time):
        arrest_date = f"{booked_date} {booked_time[:2]}:{booked_time[2:]}".strip()

    return {
        "last": last, "first": first, "middle": middle,
        "book_id": rec.get("book_id"),
        "arrest_date": arrest_date or None,
        "charge": charge,
        "other_charges": other_charges,
        "docket_number": docket_m.group(0) if docket_m else None,
        "total_bond_amount": bond_m.group(0) if bond_m else None,
        "race": rec.get("race"),
        "sex": rec.get("sex"),
        "is_juvenile": (rec.get("aj") or "").strip().upper() == "J",
        "facility": rec.get("facility"),
        "release_status": "in_custody",
    }


async def _fetch_orange_pdf_viewer(target: str) -> list[dict]:
    """Orange County NC -- Sheriff's 'Daily In Custody Report by Facility' PDF,
    embedded via a Wix pdf-flipbook viewer whose underlying file URL changes on
    every republish (a bespoke, one-off system -- no vendor-product match in this
    file; no live searchable roster database exists for Orange NC at all).

    Handshake: GET the detainees page, parse the live file URL straight out of the
    page's own rendered markup -- the <pdf-flipbook widget-data="..."> custom
    element's JSON-encoded fileUrl, NOT the page's separate "Download PDF" button.
    Live-verified 2026-11-05 those two links point at DIFFERENT files: the button's
    is long-stale (Last-Modified Mon, 23 Mar 2026) while the flipbook's is
    same-day-fresh (Last-Modified Thu, 05 Nov 2026) -- same page, same fetch, 7+
    months apart. The flipbook is the actual embedded viewer this report is
    published through and is what gets freshly republished; the download button
    apparently lags behind.

    GET that PDF, then verify freshness against the report's OWN "User: ...
    MM/DD/YYYY HH:MM:SS" generation timestamp printed on page 1 -- more trustworthy
    than any HTTP header, which a CDN could cache -- before trusting it as "current
    detainees". More than _ORANGE_MAX_STALE_DAYS old fails closed (empty list + a
    warning) rather than silently shipping a stale roster.

    Verified live 2026-11-05: 105 in-custody records, facility "NEW JAIL",
    confinement reason "PRETRIAL/ARREST", report timestamp same-day (08:03:08).
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(target, timeout=30)
            body = r.text or ""

            pdf_url = None
            fm = _ORANGE_FLIPBOOK_RE.search(body)
            if fm:
                import json
                try:
                    widget_data = json.loads(html.unescape(fm.group(1)))
                    pdf_url = widget_data.get("fileUrl")
                except (ValueError, TypeError):
                    pdf_url = None
            if not pdf_url:
                # Primary viewer element not found (page structure changed) -- fall
                # back to the "Download PDF" button link. Live-verified this
                # specific link can itself be stale, so the freshness gate below
                # still applies regardless of which path found the URL.
                dm = _ORANGE_DOWNLOAD_BTN_RE.search(body)
                pdf_url = html.unescape(dm.group(1)) if dm else None
            if not pdf_url:
                log.warning("jail_scraper.orange_nc_no_pdf_url", target=target)
                return []

            pr = await s.get(pdf_url, timeout=45)
            if pr.status_code != 200 or not pr.content:
                log.warning("jail_scraper.orange_nc_pdf_fetch_fail", url=pdf_url,
                            status=pr.status_code)
                return []

            records, report_ts = _parse_orange_pdf(pr.content)

            if report_ts is not None:
                age_days = (datetime.utcnow() - report_ts).days
                if age_days > _ORANGE_MAX_STALE_DAYS:
                    log.warning("jail_scraper.orange_nc_stale_pdf", url=pdf_url,
                                report_ts=report_ts.isoformat(), age_days=age_days)
                    return []
            else:
                log.warning("jail_scraper.orange_nc_no_timestamp", url=pdf_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.orange_nc_fail", target=target, error=str(exc)[:160])
        return []

    out = [d for d in (_orange_record_to_dict(rec) for rec in records) if d]
    log.info("jail_scraper.orange_nc_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Richland County SC — standalone ASP.NET MVC + Kendo UI grid (Executive
# Information Services, Inc. "ASGDC Public Web Jail Viewer") -- a bespoke,
# county-built system with no vendor-product match among this file's existing
# 6 fetchers.
# ---------------------------------------------------------------------------

#: Exact-match-only surname search (confirmed live 2026-11-05: LastName='A' and
#: LastName='SM' both return 0 rows, while LastName='SMITH' returns 19 real
#: bookings -- the vendor runs the typed value straight into a server-side SQL
#: LIKE with NO wildcard auto-added). That LIKE semantics means a literal '%'
#: IS accepted as a wildcard: LastName='%' alone returns exactly 200 rows (a
#: server-side cap, not the true ~1055-person population), but one '%' per
#: first LETTER (e.g. 'M%') stays well under that cap and partitions the
#: roster cleanly -- live-verified full sweep 2026-11-05: A%..Z% == 1055
#: unique BookingNumbers, 1055 summed across all 26 buckets individually
#: (zero cap hits anywhere, zero cross-bucket overlap, busiest letter M% at
#: 106). This is a COMPLETE current roster, not an approximation, despite the
#: build brief's "small set of common last-name letters/prefixes" framing --
#: the live site supports true prefix wildcarding via '%', so the full
#: alphabet is both cheap (26 requests/run) and exhaustive today. If the jail
#: population ever grows enough that one letter bucket hits the 200-row cap,
#: this logs a warning naming that letter so a future maintainer knows to
#: split it further (e.g. 'MA%'..'MZ%').
_RICHLAND_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: Server-side cap observed on an unqualified '%' search (200 exactly, while
#: the true population is 1000+) -- used only to flag a letter bucket that may
#: itself be truncated.
_RICHLAND_PAGE_CAP = 200

_RICHLAND_NET_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _richland_net_date(s: str | None) -> str | None:
    """'/Date(1747886400000)/' (ASP.NET's JSON date encoding, ms since the
    Unix epoch) -> '05/22/2025', a format this file's existing _parse_date()
    already parses. Returns None for anything else (blank/null on this vendor
    for every field but BookingDate -- live-verified across the full
    1055-row sweep)."""
    m = _RICHLAND_NET_DATE_RE.match(s or "")
    if not m:
        return None
    try:
        dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.strftime("%m/%d/%Y")


def _parse_richland_rows(body: str) -> list[dict]:
    """Pure: one search response's inmate records from Richland SC's Kendo UI
    grid (ASP.NET MVC, Executive Information Services, Inc.).

    The visible <table> only holds the current PAGE (pageSize=10) of results,
    but the Kendo grid is bootstrapped by a `kendo.syncReady(...)` script block
    that embeds the FULL matching result set as JSON
    (`"data":{"Data":[...]}`) regardless of page size -- this reads that blob
    directly instead of the truncated HTML table, so no pagination handling is
    needed per search. Live-verified: a 19-row match (LastName=SMITH%) embeds
    all 19, not just the first page's 10; a 106-row match (LastName=M%) embeds
    all 106.

    Uses json.JSONDecoder().raw_decode() from the found offset rather than a
    naive bracket-counter, so a stray '[' or ']' inside a string value (none
    observed, but not guaranteed) can't truncate the parse early. `json` is
    imported locally here (this file has no top-level `import json`) -- same
    lazy-import convention this file already uses for curl_cffi in every
    other vendor fetcher.
    """
    import json

    m = re.search(r'"data":\{"Data":', body)
    if not m:
        return []
    try:
        rows, _ = json.JSONDecoder().raw_decode(body, m.end())
    except (ValueError, json.JSONDecodeError):
        return []

    out: list[dict] = []
    for rw in rows:
        last = (rw.get("LastName") or "").strip().upper()
        first = (rw.get("FirstName") or "").strip().upper()
        if not last or not first:
            continue
        rec: dict = {
            "last": last,
            "first": first,
            "book_id": rw.get("BookingNumber"),
            "arrest_date": _richland_net_date(rw.get("BookingDate")),
        }
        middle = (rw.get("MiddleName") or "").strip().upper()
        if middle:
            rec["middle"] = middle
        dob = _richland_net_date(rw.get("DOB"))
        if dob:
            rec["dob"] = dob
        if rw.get("Race"):
            rec["race"] = rw["Race"]
        if rw.get("Sex"):
            rec["sex"] = rw["Sex"]
        rel = _richland_net_date(rw.get("ReleaseDate"))
        if rel:
            rec["release_date"] = rel
        sched = _richland_net_date(rw.get("ScheduleDate"))
        if sched:
            rec["scheduled_release"] = sched
        # The vendor's own "Location" field is blank on every row checked but
        # would be a sub-facility/housing-unit label, not a different jail --
        # this site serves exactly one facility.
        rec["facility"] = rw.get("Location") or "Alvin S. Glenn Detention Center"
        out.append(rec)
    return out


async def _fetch_richland_kendo(target: str) -> list[dict]:
    """Fetch current in-custody roster from Richland County SC's "ASGDC Public
    Web Jail Viewer" (jail.richlandcountysc.gov) -- a bespoke ASP.NET MVC app
    (footer-credited "Executive Information Services, Inc."), no vendor-
    product match among this file's existing 6 fetchers.

    `target` is the site origin, e.g. "https://jail.richlandcountysc.gov"
    (no trailing slash, no path -- this function appends the two fixed MVC
    routes itself, same base+suffix convention as _fetch_p2c_jqgrid above).

    No bulk/"show all" query exists -- the only search action is per-surname
    (GET /Home/BookingSearchQuery to load the form, POST
    /Home/BookingSearchResult_ASGDCSC with LastName/FirstName/BookingFrom/
    BookingTo). Live-verified 2026-11-05 the LastName value is passed straight
    into a server-side SQL LIKE with no wildcard auto-added (LastName='A'
    returns 0 rows -- NOT a prefix match on its own -- while LastName='A%'
    returns 23 real rows), so one request per letter (A%..Z%) sweeps the FULL
    current roster rather than a sample: the live sweep totalled 1055 unique
    bookings across all 26 letters, zero duplicates, zero letters anywhere
    near the observed 200-row server cap (busiest was M% at 106). The site's
    own home page states this view "provides access to information related
    to individuals who are currently detained at the Alvin S. Glenn Detention
    Center" -- i.e. this endpoint IS the live roster, even though some
    individuals' BookingDate goes back years (long pretrial holds), not a
    historical/archival booking log.

    No anti-forgery token or session cookie guards the form (checked live:
    the GET sets no cookies and the form has no __RequestVerificationToken
    hidden field) but the GET is still issued first, defensively, in case that
    ever changes -- same GET-then-POST posture as every other fetcher in this
    file that drives a classic WebForms/MVC form.

    BookingNumber is a real vendor-issued id (purely numeric on every one of
    the 1055 live rows checked) -- carried as book_id, which _booking_identity
    already prefers over the name/dob/arrest_date hash fallback (see that
    function's own docstring). DOB/MiddleName/Race/Sex/ReleaseDate/
    ScheduleDate/Location all exist in the vendor's own JSON schema but came
    back null on every one of the 1055 rows live-checked; the code above still
    carries each through whenever a future row does have one.
    """
    from curl_cffi.requests import AsyncSession

    seen: dict[str, dict] = {}
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            form_url = f"{target}/Home/BookingSearchQuery"
            post_url = f"{target}/Home/BookingSearchResult_ASGDCSC"

            r = await s.get(form_url, timeout=20)
            body = r.text or ""
            # Defensive only -- live-verified this form carries none today, but
            # carry one through if a future deploy adds anti-forgery protection.
            token_m = re.search(
                r'name="__RequestVerificationToken"[^>]*value="([^"]*)"', body)

            for letter in _RICHLAND_LETTERS:
                data = {
                    "LastName": f"{letter}%", "FirstName": "",
                    "BookingFrom": "", "BookingTo": "",
                }
                if token_m:
                    data["__RequestVerificationToken"] = token_m.group(1)
                r = await s.post(post_url, data=data, timeout=30)
                resp_body = r.text or ""
                recs = _parse_richland_rows(resp_body)

                total_m = re.search(r'"total":(\d+)', resp_body)
                if total_m and int(total_m.group(1)) >= _RICHLAND_PAGE_CAP:
                    log.warning("jail_scraper.richland_letter_capped",
                                letter=letter, total=total_m.group(1))

                for rec in recs:
                    key = str(rec.get("book_id") or
                              f"{rec['last']}|{rec['first']}|{rec.get('arrest_date')}")
                    seen[key] = rec
                await asyncio.sleep(0.3)  # polite pacing
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.richland_kendo_fail", target=target,
                    error=str(exc)[:120])
        return list(seen.values())

    out = list(seen.values())
    log.info("jail_scraper.richland_kendo_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Jasper County SC -- Esri ArcGIS Online Hosted Feature Service (county-built, STALE FEED)
# ---------------------------------------------------------------------------

async def _fetch_jasper_arcgis(target: str) -> list[dict]:
    """Jasper County SC jail roster -- Esri ArcGIS Online Hosted Feature Service, no vendor-
    product match in this file (a bespoke county-run ArcGIS "PrisonerDataTable" layer, not one of
    the 6 vendors above). `target` is the full FeatureServer layer query URL, e.g.
    "https://services3.arcgis.com/oJaBluQKw5aLHpzj/arcgis/rest/services/Map2/FeatureServer/3/
    query" (layer index 3 on that service is "PrisonerDataTable"; layer 0 "Test" is an unrelated
    empty placeholder). No auth, no handshake -- a plain GET with where=1=1&outFields=*&f=json
    returns the whole table as JSON (confirmed live 2026-11-05: returnCountOnly=112,
    maxRecordCount=2000, so one request is the whole table -- paging below is defensive only).

    STALE FEED, re-confirmed live 2026-11-05 (this corrects the prior 2026-08-22 finding this
    fetcher was built from -- that date was off by exactly one year): every one of the 112 rows
    carries InmateInJail='Y', including rows whose own ReleaseDate is more than a year in the
    past (e.g. BOLES, RODRICK ANTON -- ReleaseDate 2025-04-10, still flagged 'Y'), and the newest
    CapturedWhen in the ENTIRE table is 2025-08-22 10:16:44, not 2026-08-22. This table has not
    been refreshed by the county in roughly 440 days as of today. Treat every record this
    returns as a POSSIBLY STALE in-custody claim, not a live one, until CapturedWhen starts
    advancing again.

    SCHEMA CORRECTION vs. the original research: CapturedWhen and ReleaseDate are NOT epoch-ms
    integers -- confirmed live they are plain 'HH:MM:SS MM/DD/YYYY' strings (e.g.
    '15:00:42 09/02/2021'), converted below to a format _parse_date() already handles.
    OffenseCode/CrimeClass/OffenseType/Counts/PhotoPath/SuffixName are null on all 112 live
    rows -- the schema carries those columns but the county has never populated them, so no
    charge or mugshot data exists on this source at all; `charge` is always "". No DOB/age field
    exists in this table either.

    OBJECTID is Esri's own per-row integer id on this hosted table -- confirmed live 100%
    populated AND 100% unique across all 112 rows -- used as `book_id` so this source gets a
    real per-booking dedupe key like every other vendor here with one (see _booking_identity's
    own docstring for why that matters), never the name+date hash fallback.
    """
    from curl_cffi.requests import AsyncSession

    def _ts(s: str | None) -> str | None:
        """'15:00:42 09/02/2021' -> '2021-09-02 15:00:42' (a format _parse_date already
        handles); this vendor's own timestamp fields are plain 'HH:MM:SS MM/DD/YYYY' strings,
        not epoch ms -- confirmed live 2026-11-05."""
        if not s:
            return None
        try:
            return datetime.strptime(s.strip(), "%H:%M:%S %m/%d/%Y").strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None

    out: list[dict] = []
    offset = 0
    page_size = 2000
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            while True:
                params = {
                    "where": "1=1", "outFields": "*", "f": "json",
                    "resultRecordCount": page_size, "resultOffset": offset,
                }
                r = await s.get(target, params=params, timeout=30)
                data = r.json() or {}
                if data.get("error"):
                    log.warning("jail_scraper.jasper_arcgis_error",
                                error=str(data["error"])[:160])
                    break
                feats = data.get("features") or []
                if not feats:
                    break
                for feat in feats:
                    a = feat.get("attributes") or {}
                    if (a.get("InmateInJail") or "").strip().upper() != "Y":
                        continue
                    last = (a.get("LastName") or "").strip().upper()
                    first = (a.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    out.append({
                        "last": last, "first": first,
                        "middle": (a.get("MiddleName") or "").strip().upper() or None,
                        "arrest_date": _ts(a.get("CapturedWhen")),
                        "release_date": _ts(a.get("ReleaseDate")),
                        "charge": "",
                        "race": a.get("RaceCategory"),
                        "sex": a.get("Sex"),
                        "height": a.get("Height"),
                        "weight": a.get("Weight"),
                        "booking_agency": a.get("Agency"),
                        "release_status": "in_custody",
                        "book_id": a.get("OBJECTID"),
                    })
                if not data.get("exceededTransferLimit") or len(feats) < page_size:
                    break
                offset += page_size
                if offset > 20000:  # sanity cap -- this table is ~112 rows today
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.jasper_arcgis_fail", target=target,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.jasper_arcgis_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Spartanburg SC -- bespoke static-HTML booking gallery (county-built, no
# vendor-product match: not Zuercher / P2C / Citizen Connect / Tyler)
# ---------------------------------------------------------------------------

_SPB_CARD_RE = re.compile(
    r'<a class="card" href="([^"]+)">.*?<img src="([^"]*)"[^>]*alt="Mugshot of ([^"]*)".*?'
    r'<div class="bnstrip">([^<]*)</div>',
    re.S,
)
_SPB_FIELD_RE = re.compile(r'<strong[^>]*>([^<]+?):?\s*</strong>\s*<span>([^<]*)</span>')
_SPB_OFFENSE_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_SPB_OFFENSE_CELL_RE = re.compile(r'<span class="value">(.*?)</span>', re.S)


def _parse_spartanburg_index(body: str) -> list[dict]:
    """One page's booking cards from Spartanburg SC's bookings/ gallery (bespoke static-HTML
    county system -- IIS-served, regenerated on a timer, no JS/JSON API at all; confirmed live
    2026-11-05: the page's own Last-Modified header updates every few minutes)."""
    out: list[dict] = []
    for m in _SPB_CARD_RE.finditer(body or ""):
        href, mugshot, name_attr, booking_no = m.groups()
        out.append({
            "href": href,
            "mugshot_index": mugshot,
            "name": html.unescape(name_attr),
            "book_id": booking_no.strip(),
        })
    return out


def _parse_spartanburg_detail(body: str) -> tuple[dict, list[dict]]:
    """One booking's detail fields + offense-table rows from its own <book_id>.html page.

    _SPB_FIELD_RE matches BOTH the plain `.row` fields (D.O.B., Race/Gender, Arresting
    Agency, ...) and the two `.pair`-wrapped ones (Height/Weight, Arrested/Released) -- same
    <strong>label</strong><span>value</span> shape either way, so one regex covers both."""
    fields = {k.strip(): html.unescape(v).strip()
              for k, v in _SPB_FIELD_RE.findall(body or "")}
    offenses: list[dict] = []
    tbody_m = re.search(r"<tbody>(.*?)</tbody>", body or "", re.S)
    if tbody_m:
        for row in _SPB_OFFENSE_ROW_RE.findall(tbody_m.group(1)):
            cells = _SPB_OFFENSE_CELL_RE.findall(row)
            if len(cells) == 5:
                statute, offense, court, warrant, bond = (
                    html.unescape(c).strip() for c in cells)
                offenses.append({"statute": statute, "offense": offense,
                                  "court": court, "warrant": warrant, "bond": bond})
    return fields, offenses


async def _fetch_spartanburg_mugshots(target: str) -> list[dict]:
    """Spartanburg County SC current/recent bookings -- bespoke static-HTML gallery.

    FOUND 2026-11-05. This was the single biggest unresolved jail_booking gap on the board
    (~13,854 estimated affected rows) -- no source had ever been wired, and this module's own
    docstring previously said the Sheriff's Office portal was offline (last Internet Archive
    capture 2026-03-08, both :80 and :443 closed on the legacy mugshot host). THAT NOTE IS NOW
    STALE -- re-checked live today: spartanburgsheriff.org/258/Bookings-Search embeds a live
    iframe at https://mugshots.spartanburgsheriff.org/bookings, and the vendor has since
    migrated off the dead legacy `/myscripts/mugshot_card.php?number=<id>` PHP path (what the
    old note found) onto a brand-new static-HTML generator at this same hostname -- confirmed
    genuinely live, not an archived mirror: the page's own Last-Modified header is today's date
    and the roster count itself changed between two live test runs taken ~15 minutes apart
    (92 then 91 rows). Checked every known vendor pattern first, per the brief, with definitive
    negative evidence for each: Zuercher subdomains spartanburg-so-sc / spartanburg-911-sc /
    spartanburgso-sc.zuercherportal.com all NXDOMAIN; CentralSquare P2C guesses
    spartanburgcountysc / spartanburgsheriffsc.policetocitizen.com both resolve (shared Angular
    shell) but their own /api/Agency/InitialSettings answers 404 "Agency ... does not exist";
    Southern Software Citizen Connect's bookingsearch/index.php?AgencyID=SpartanburgCoSC
    redirects away to the vendor's generic index2.php homepage (the behavior invalid AgencyIDs
    get, vs. valid tenants like Henderson/Duplin which stay on the bookingsearch page). None
    apply -- this is genuinely bespoke: a plain IIS host serving pre-rendered HTML on a timer,
    no JS, no JSON API, no login/CAPTCHA/WAF, no robots.txt even present on this subdomain
    (checked: 404).

    Two-step fetch, same shape as `_fetch_york_webforms` above: GET the index gallery (every
    current booking is on the one page -- no pager exists; the page carries no form or script of
    any kind), then GET each booking's own `<book_id>.html` detail page for DOB / race / sex /
    height / weight / arrest+release timestamps / the offense table. Live-verified 2026-11-05 in
    three separate full live runs (including one that exec'd this exact code into the real,
    unmodified module's own namespace and fed its output through the real, unmodified
    `_booking_identity()` and `_to_listing()`): 91-92 real bookings per run, 100% carrying a
    UNIQUE booking number straight off the card's own "bnstrip" div (e.g. "26-09607") -- a REAL
    vendor-issued per-booking id, used below as `book_id` (same dedupe-safety role book_id
    already plays for the p2c_jqgrid vendor -- see `_booking_identity`'s own docstring for why
    that matters) -- and 100% carrying a full DOB. Sample real row: Michael Vladimir Anderson,
    DOB 01/05/92, White/Male, 5'09"/145, TRESPASS INTO ENCLOSED PLACE, arrested 11/03/2026 09:52,
    released 11/03/2026 19:15, Spartanburg Police Department. ~1/3 of bookings carry 2+ offenses
    (first -> `charge`, the rest -> `other_charges`); a few carry none ("No offenses on record."
    -- handled as charge="", not a crash or a guessed value). Every `arrest_date`/`dob` string
    this vendor prints parses cleanly with this file's own `_parse_date` (checked live against
    every row across all three runs: 0 unparseable).

    Small roster (~90 rows) on one small-county IIS host -- fetched sequentially with this
    file's own polite per-request pacing (same convention as Citizen Connect's pager and Tyler's
    detail hydration below), not eager full-roster concurrency. Whole run (index + ~90 detail
    pages) completed in ~32s live both times measured.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    base = target if target.endswith("/") else target + "/"
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(base, timeout=30)
            cards = _parse_spartanburg_index(r.text or "")

            for card in cards:
                try:
                    dr = await s.get(urljoin(base, card["href"]), timeout=25)
                    fields, offenses = _parse_spartanburg_detail(dr.text or "")
                except Exception as exc:  # noqa: BLE001
                    log.warning("jail_scraper.spartanburg_detail_fail",
                                book_id=card["book_id"], error=str(exc)[:120])
                    fields, offenses = {}, []
                await asyncio.sleep(0.3)  # polite pacing

                parts = _split_space_name(card["name"])
                if not parts:
                    continue
                last, first = parts

                race_gender = (fields.get("Race/Gender") or "").split(" / ")
                race = (race_gender[0].strip() or None) if race_gender else None
                sex = race_gender[1].strip() if len(race_gender) > 1 else None

                released = fields.get("Released") or ""
                in_custody = released.strip().lower() == "in custody"
                release_status = ("in_custody" if in_custody
                                   else (f"released {released}" if released else None))

                charge = offenses[0]["offense"] if offenses else ""
                other_charges = ("; ".join(o["offense"] for o in offenses[1:])
                                  if len(offenses) > 1 else None)
                bond_total = None
                if offenses:
                    total, seen = 0.0, False
                    for o in offenses:
                        try:
                            total += float(re.sub(r"[^0-9.]", "", o["bond"]) or 0)
                            seen = True
                        except ValueError:
                            pass
                    bond_total = total if seen else None

                out.append({
                    "last": last, "first": first,
                    "middle": _space_middle(card["name"]) or None,
                    "dob": fields.get("D.O.B.") or None,
                    "arrest_date": fields.get("Arrested") or None,
                    "charge": charge[:_CHARGE_CAP],
                    "other_charges": (other_charges[:_CHARGE_CAP] if other_charges else None),
                    "release_status": release_status,
                    "release_date": None if in_custody else (released or None),
                    "race": race, "sex": sex,
                    "height": fields.get("Height") or None,
                    "weight": fields.get("Weight") or None,
                    "booking_agency": fields.get("Arresting Agency") or None,
                    "total_bond_amount": bond_total,
                    "mugshot_url": (urljoin(base, card["mugshot_index"])
                                     if card["mugshot_index"] else None),
                    "book_id": card["book_id"],
                })
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.spartanburg_fail", target=target, error=str(exc)[:120])
        return out

    log.info("jail_scraper.spartanburg_ok", target=target, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Vendor dispatcher
# ---------------------------------------------------------------------------

async def _fetch_roster(state: str, county: str, vendor: str, target: str) -> list[dict]:
    """Dispatch to the correct vendor fetcher."""
    try:
        if vendor == "zuercher":
            return await _fetch_zuercher(target)
        elif vendor == "p2c_jqgrid":
            return await _fetch_p2c_jqgrid(target)
        elif vendor == "p2c_centralsquare":
            return await _fetch_p2c_centralsquare(target)
        elif vendor == "citizen_connect":
            return await _fetch_citizen_connect(target)
        elif vendor == "tyler_inmate_inquiry":
            return await _fetch_tyler_inmate_inquiry(target)
        elif vendor == "york_webforms":
            return await _fetch_york_webforms(target)
        elif vendor == "randolph_webforms":
            return await _fetch_randolph_webforms(target)
        elif vendor == "davidson_dhtmlx":
            return await _fetch_davidson_dhtmlx(target)
        elif vendor == "cumberland_webforms":
            return await _fetch_cumberland_webforms(target)
        elif vendor == "pitt_webforms":
            return await _fetch_pitt_webforms(target)
        elif vendor == "sheriffapp_ocv":
            return await _fetch_sheriffapp_ocv(target)
        elif vendor == "durham_webforms":
            return await _fetch_durham_webforms(target)
        elif vendor == "dcn_export":
            return await _fetch_dcn_export(target)
        elif vendor == "darlington_dcn":
            return await _fetch_darlington_dcn(target)
        elif vendor == "orange_pdf_viewer":
            return await _fetch_orange_pdf_viewer(target)
        elif vendor == "richland_kendo":
            return await _fetch_richland_kendo(target)
        elif vendor == "jasper_arcgis":
            return await _fetch_jasper_arcgis(target)
        elif vendor == "spartanburg_mugshots":
            return await _fetch_spartanburg_mugshots(target)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.fetch_error", county=county, vendor=vendor,
                    error=str(exc)[:160])
    return []


# ---------------------------------------------------------------------------
# Listing builder
# ---------------------------------------------------------------------------

def _booking_identity(rec: dict, last: str, first: str) -> Optional[str]:
    """A stable per-booking identifier for dedupe_key()'s case_number branch.

    FOUND 2026-10-22 (jail_bookings dedupe-collision audit, following the York SC build):
    every county's booking Listings fell through to dedupe_key()'s `url:{source_url}` branch
    (source_url is the same fixed per-county search-page URL for every booking at that county),
    the exact collision class fixed for Cleveland/York via book_id/case_number -- confirmed LIVE
    on the published board: Gaston's 673 jail_booking rows (pre-fix) all shared ONE dedupe key,
    meaning every booking past the first was silently rejected as "already on board".

    Preference order: a real vendor-issued id (p2c_jqgrid's book_id, Tyler's detail_id, now
    p2c_centralsquare's docket_number -- each already carried on `rec` by its own fetcher) wins.
    Zuercher and Citizen-Connect publish no id of any kind (live-verified: neither vendor's own
    JSON/HTML exposes anything beyond name/dob/demographics/charges) -- for those, synthesize a
    stable key from (name, dob, arrest_date). A hash, not a literal join: dedupe_key()'s own
    case_number normalization strips every non-alnum character, so an unhashed join could let two
    different (name, dob, date) tuples collapse onto the same stripped string at a field boundary;
    hashing the delimited tuple removes that ambiguity. Two bookings of the SAME person on
    DIFFERENT dates correctly get different keys (a new incident, not a dup)."""
    real_id = rec.get("book_id") or rec.get("detail_id") or rec.get("docket_number")
    if real_id:
        return str(real_id)
    dob = (rec.get("dob") or "").strip()
    adate = (rec.get("arrest_date") or "").strip()
    if not (last or first) or not (dob or adate):
        return None
    basis = f"{last.strip().upper()}|{first.strip().upper()}|{dob}|{adate}"
    return "synth" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _to_listing(rec: dict, state: str, county: str) -> Listing:
    """Convert an inmate record to a Listing object."""
    last = rec.get("last", "")
    first = rec.get("first", "")
    full_name = f"{last}, {first}" if last and first else (last or first)

    booking_date = _parse_date(rec.get("arrest_date"))

    # Build a source URL — link to the county's public search page
    if state == "NC" and county == "Buncombe":
        # FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17):
        # /en/Inmates returns HTTP 200 (so the scraper's own XSRF-token
        # handshake still works) but the Angular SPA's client-side router
        # has no route for that locale-prefixed path and renders its own
        # "404 - Not Found" page to a human visitor (confirmed live via
        # browser render). The real, working nav target (confirmed live by
        # clicking the site's own "Inmates" menu link) is /Inmates/Catalog.
        source_url = "https://buncombecountyso.policetocitizen.com/Inmates/Catalog"
    elif state == "NC" and county == "Cleveland":
        source_url = "http://74.218.167.200/p2c/jailinmates.aspx"
    elif state == "SC" and county == "Cherokee":
        source_url = "https://cherokee-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Anderson":
        source_url = "https://anderson-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Laurens":
        source_url = "https://laurens-911-sc.zuercherportal.com/"
    elif state == "SC" and county == "Oconee":
        source_url = "https://oconee-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Pickens":
        source_url = "https://pickens-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Union":
        source_url = "https://union-so-sc.zuercherportal.com/"
    elif state == "NC" and county == "Henderson":
        source_url = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/"
                      "index.php?AgencyID=HendersonCoNC")
    elif state == "NC" and county == "Polk":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=PolkCoNC"
    elif state == "NC" and county == "Transylvania":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=TransylvaniaCoNC"
    elif state == "NC" and county == "Burke":
        source_url = "https://morgantonpdnc.policetocitizen.com/en/Inmates"
    elif state == "NC" and county == "Lincoln":
        source_url = "http://p2c.lincolnsheriff.org/jailinmates.aspx"
    elif state == "NC" and county == "Rutherford":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=RutherfordCoNC"
    elif state == "NC" and county == "Gaston":
        source_url = ("https://tepsweb.cityofgastonia.com/"
                      "NewWorld.InmateInquiry/GastonCounty?InCustody=True")
    # BACKFILL 2026-11-05: the 16 counties below (York through Alamance) were added to
    # ROSTERS across several earlier 2026-11-05 builds but never got a branch here --
    # flagged independently by multiple concurrent build agents the same day. Filling the
    # gap now so these don't silently fall through to the catch-all `else: source_url = ""`.
    elif state == "SC" and county == "York":
        source_url = "https://inmatesinjail.yorkcountygov.com/detentioncenter/inmatesinjail.aspx"
    elif state == "SC" and county == "Sumter":
        source_url = "https://portal-sc-sumter-pd.centralsquarecloudgov.com/"
    elif state == "NC" and county == "Duplin":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=DuplinCoNC"
    elif state == "NC" and county == "Rowan":
        source_url = "https://rowancountync.policetocitizen.com/Inmates/Catalog"
    elif state == "NC" and county == "New Hanover":
        source_url = "http://p2c.nhcgov.com/p2c/jailinmates.aspx"
    elif state == "SC" and county == "Colleton":
        source_url = "https://colleton-so-sc.zuercherportal.com/"
    elif state == "NC" and county == "Hoke":
        source_url = "https://hoke-so-nc.zuercherportal.com/"
    elif state == "SC" and county == "Berkeley":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=BerkelyCoSC"
    elif state == "SC" and county == "Lexington":
        # Same locale-prefix gotcha as Buncombe above -- /en/Inmates 404s on this tenant;
        # the real working route (confirmed live 2026-11-05) is /Inmates with no prefix.
        source_url = "https://lexingtonsheriffsc.policetocitizen.com/Inmates"
    elif state == "NC" and county == "Harnett":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=HarnettCoNC"
    elif state == "NC" and county == "Anson":
        source_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID=AnsonCoNC"
    elif state == "NC" and county == "Pasquotank":
        source_url = "https://pasquotank-911-nc.zuercherportal.com/"
    elif state == "NC" and county == "Cabarrus":
        source_url = "https://onlineservices.cabarruscounty.us/p2c/jailinmates.aspx"
    elif state == "NC" and county == "Iredell":
        source_url = "https://p2c.iredellcountync.gov/jailinmates.aspx"
    elif state == "SC" and county == "Kershaw":
        source_url = "https://kershaw-so-sc.zuercherportal.com/"
    elif state == "NC" and county == "Alamance":
        source_url = "https://apps.alamance-nc.com/p2c/jailinmates.aspx"
    # 2026-11-05 bespoke-systems build (13 counties researched+built this same day).
    elif state == "NC" and county == "Randolph":
        source_url = "https://legacyweb.randolphcountync.gov/sheriff/confinedinmatesbydate.aspx"
    elif state == "NC" and county == "Davidson":
        source_url = "http://www2.co.davidson.nc.us/DCInmates/"
    elif state == "NC" and county == "Cumberland":
        source_url = "https://cumberlandsheriffnc.gov:8000/active_inmates/Inmates.aspx"
    elif state == "NC" and county == "Pitt":
        source_url = "https://apps.pittcountync.gov/apps/detention/detainee/"
    elif state == "SC" and county == "Florence":
        source_url = "https://www.fcso.org/inmatesearch"
    elif state == "NC" and county == "Durham":
        source_url = "https://www2.dconc.gov/sheriff/ips"
    elif state == "NC" and county == "Lee":
        source_url = "https://dcn.leecountync.gov/DCN/Inmates"
    elif state == "SC" and county == "Darlington":
        source_url = "http://bookings.darlingtonsheriff.org/dcn/inmates"
    elif state == "NC" and county == "Orange":
        source_url = "https://www.ocsonc.com/detention/current-detainees"
    elif state == "SC" and county == "Richland":
        source_url = "https://jail.richlandcountysc.gov/"
    elif state == "SC" and county == "Jasper":
        source_url = ("https://experience.arcgis.com/experience/"
                      "4dbd3f63e56c492f9b408ebff12155f3/")
    elif state == "SC" and county == "Spartanburg":
        source_url = "https://mugshots.spartanburgsheriff.org/bookings/"
    else:
        source_url = ""

    charge = rec.get("charge") or ""

    return Listing(
        source="national.jail_bookings",
        source_url=source_url,
        # See _booking_identity()'s own docstring: routes every vendor (real id where one
        # exists, a stable name+dob+arrest_date hash where none does) through dedupe_key()'s
        # (case_number, county) branch instead of the shared-per-county url: fallback.
        case_number=_booking_identity(rec, last, first),
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        defendant=full_name,
        county=county,
        state=state,
        sale_date=booking_date,  # re-purposed as booking date
        description=charge or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "jail_booking": {
                "county": county,
                "state": state,
                "inmate_name": full_name,
                "last_name": last,
                "first_name": first,
                "dob": rec.get("dob"),
                "age": rec.get("age"),
                "booking_date": booking_date.isoformat() if booking_date else None,
                "charge": charge,
                "release_status": rec.get("release_status") or "in_custody",
                "scheduled_release": rec.get("scheduled_release"),
                "facility": rec.get("facility"),
                # Zuercher demographics + release detail (dropped before).
                "race": rec.get("race"),
                "sex": rec.get("sex"),
                "cell_block": rec.get("cell_block"),
                "release_date": rec.get("release_date"),
                "mugshot": rec.get("mugshot") or rec.get("mugshot_url"),
                "is_juvenile": rec.get("is_juvenile"),
                # Full vendor field/cell dicts (Citizen-Connect / Tyler).
                "fields": rec.get("fields"),
                "cells": rec.get("cells"),
                "vendor": "jail_bookings_scraper",
                # FOUND 2026-10-04 (HERMES extraction-completeness audit,
                # batch 17): the below were all already on the vendor row
                # this scraper already fetches (p2c_jqgrid Cleveland /
                # p2c_centralsquare Buncombe) but never read or carried
                # through to the Listing. See the two vendor fetchers'
                # inline comments for live-sample evidence.
                "middle_name": rec.get("middle"),
                "book_id": rec.get("book_id"),
                "agency": rec.get("agency"),
                "other_charges": rec.get("other_charges"),
                "height": rec.get("height"),
                "weight": rec.get("weight"),
                "scars_marks_tattoos": rec.get("scars_marks_tattoos"),
                "holding_facility": rec.get("holding_facility"),
                "booking_agency": rec.get("booking_agency"),
                "court_date": rec.get("court_date"),
                "total_bond_amount": rec.get("total_bond_amount"),
                "home_address": rec.get("home_address"),
            },
        },
    )


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class JailBookingsScraper(BaseScraper):
    """Scrape current in-custody jail rosters across NC/SC counties.

    Returns Listing objects with listing_type=UNKNOWN — these are name-only
    lead signals for cross-referencing against property owner records.
    """

    slug = "national.jail_bookings"
    name = "County Jail Bookings (NC/SC)"
    category = "jail_bookings"
    expected_min_count = 0
    timeout_s = 120.0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        # Fetch all rosters concurrently
        tasks = [
            _fetch_roster(state, county, vendor, target)
            for state, county, vendor, target in ROSTERS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (state, county, vendor, target), inmates in zip(ROSTERS, results):
            if isinstance(inmates, Exception):
                log.warning("jail_scraper.county_error",
                            county=county, error=str(inmates)[:160])
                continue
            if not inmates:
                continue
            for rec in inmates:
                out.append(_to_listing(rec, state, county))

        log.info("jail_scraper.done", total=len(out),
                 counties=sum(1 for r in results if isinstance(r, list) and r))
        return out
