"""Schneider qPublic SC assessor cards — DISABLED 2026-10-14 (source-completeness audit).

Original premise: 26 SC counties' property cards live on qpublic.schneidercorp.com
behind Cloudflare, and ``http_client.get_text(wall_bypass=True)`` would clear the
wall and let us submit a real owner/address/parcel search per county. The audit
flagged this file as "worth confirming the search form even works at all — the
code never submits a query." That flag is correct, and live-reverifying it
(2026-10-14, not assumed) found a bigger problem than a missing query string:

1. ``_COUNTY_PAGES``'s URL scheme was simply wrong. Every entry used
   ``Application.aspx?App={County}SC&Page=search`` (e.g. ``App=BerkeleySC``).
   Live-fetched via ``get_text(wall_bypass=True)``: this returns a generic
   Schneider "qPublic - An error has occurred / Something went wrong while
   generating your web page" response for EVERY county tried (Berkeley,
   Beaufort, Colleton) and both with/without ``&Page=search`` — a backend
   application error, not a Cloudflare block (no "challenge"/"cf-" markers;
   pydoll renders real content, it's just the error page). ``Page=search`` is
   not a real Schneider query param at all; the platform addresses pages by
   numeric ``PageTypeID``/``PageID``, not a string.

2. Cross-checking the sibling ``counties_sc.kershaw_flc`` docstring's own
   ``App=KershawCountySC`` reference (note the ``County`` infix the
   ``_COUNTY_PAGES`` aliases were missing) against a KNOWN-good app
   (``assessor_cards/qpublic_render.py``'s Oconee, ``AppID=1030``) confirmed the
   real alias shape: ``App={County}CountySC``. Live-verified 2026-10-14:
   ``App=KershawCountySC``, ``App=OconeeCountySC`` and ``App=ColletonCountySC``
   ALL load a real per-county landing page via ``get_text(wall_bypass=True)``
   (pydoll/nodriver clear Cloudflare cleanly, no challenge page, real Schneider
   app chrome — "Map Search Sales Search Sales List Home" nav). So the
   Cloudflare-clears-fine half of the old docstring was directionally true.
   BUT ``App=BerkeleyCountySC`` and ``App=BeaufortCountySC`` (and the
   un-corrected ``BerkeleySC``/``BeaufortSC``) still 100% return the same
   generic error — so the ``{County}CountySC`` formula is NOT a reliable
   fix across the other 25 counties in this dict; at least 2 of the 3 tested
   here need a real per-county alias (or numeric AppID) that would have to be
   independently discovered, county by county, exactly as
   ``assessor_cards/qpublic_render.py`` had to for its 4 counties.

3. Even on the apps that DO resolve (Kershaw AppID=1249/LayerID=40593,
   Oconee AppID=1030/LayerID=21692, Colleton), BOTH real query mechanisms —
   the owner/address/parcel "Search" page (PageTypeID=2) and the "Sales
   Search" page (date/price/acreage range, also PageTypeID=2) — are classic
   stateful ASP.NET WebForms pages: live-fetched raw HTML (Kershaw PageID=15084
   and PageID=15087) shows ``<form method="post" ...>`` with
   ``__VIEWSTATE``/``__VIEWSTATEGENERATOR``/``__EVENTTARGET`` hidden fields and
   an ``onkeypress``-bound postback search button. A plain GET — all that
   ``http_client.get_text()`` and every ``wall_bypass.py`` tier can do
   (``tab.go_to(url)`` navigation only; no form-fill, no click, no
   cookie/session reuse across separate ``get_text()`` calls) — cannot submit
   this form. The obvious GET shortcut was tried too:
   ``...&PageTypeID=3&PageID=15085&KeyValue=smith`` lands on the real
   "Results" ROUTE (confirmed by its own analytics tag,
   ``.../KershawCountySC/Parcels/Results/Results?KeyValue=smith``) but the
   results grid is populated client-side only after a REAL postback — the
   fetched HTML has zero ``<table>`` tags and zero occurrences of "smith"
   anywhere in the body; the grid containers
   (``ctlBodyPane_ctl01_mSection``/``txtResultCount``) are present but empty.
   ``KeyValue=`` on the URL does not, by itself, run a query.

So "the code never submits a query" is true and is NOT a one-line fix: qPublic's
search (both basic and sales-by-date-range) is a session-bound POST form with a
JS-rendered results grid, architecturally incompatible with this project's
``get_text(wall_bypass=True)`` GET-only convention. The sibling
``assessor_cards/qpublic_render.py`` already solves the underlying problem
correctly, but only for the ENRICHMENT shape it was built for — resolving ONE
already-known address/parcel to a property card via a real StealthyFetcher
browser session with a custom ``page_action`` that drives the typeahead (type,
wait, click a suggestion) — for 4 counties (Spartanburg, Oconee, Pickens, Union)
whose numeric AppID/LayerID/PageID were individually reverse-engineered. Porting
that same browser-driven approach to a blind DISCOVERY scraper (this file's
shape: ``fetch()`` takes no input) across the other 22+ counties would still hit
a deeper ceiling: qPublic has no query that surfaces NEW leads without already
knowing an owner/address/parcel to look up. The closest candidate (Sales Search,
by date range) is just as POST-bound, and even solved it would only yield
general recent-sales/comps data, not a distress signal — a materially different,
much larger project than "wire in the missing query string."

Disabled rather than shipped as a scraper whose ``fetch()`` either 500s on a bad
URL or lands on a real-but-query-less search form and silently returns ``[]``
forever (which reads as a clean zero in run reports, not the dead end it is).
"""
from __future__ import annotations

from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing


class ScQpublicScraper(BaseScraper):
    """SC qPublic assessor cards — DISABLED, see module docstring."""

    slug = "counties_sc.sc_qpublic"
    name = "SC qPublic Assessor Cards"
    category = "assessor"
    disabled = True
    disabled_reason = (
        "_COUNTY_PAGES used an invalid URL scheme (App={County}SC&Page=search -> a generic "
        "Schneider backend error for every county tried, not a Cloudflare block) and even the "
        "corrected App={County}CountySC alias only resolves for some counties (Kershaw/Oconee/"
        "Colleton confirmed live 2026-10-14; Berkeley/Beaufort still error). Where the app DOES "
        "resolve, both real search paths (owner/address/parcel Search, Sales Search) are "
        "session-bound ASP.NET WebForms POST forms with a JS-rendered results grid -- confirmed "
        "live via raw HTML (__VIEWSTATE/__EVENTTARGET + postback button; a GET KeyValue= shortcut "
        "to the Results route loads the page but the grid stays empty, zero <table> rows). Not "
        "submittable via this project's get_text(wall_bypass=True) GET-only convention. The "
        "legitimate use of this data source (resolve ONE already-known address/parcel to a "
        "property card) is already covered by assessor_cards/qpublic_render.py for 4 counties via "
        "a real driven browser session; extending that to blind discovery across the rest of this "
        "county list is a separate, much larger project, not a missing query string."
    )
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
