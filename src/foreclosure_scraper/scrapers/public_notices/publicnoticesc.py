"""scpublicnotices.com (SC Press Association) -- BUILT 2026-10-02.

PRIOR STATE: this module returned ``[]`` unconditionally. Its own docstring
(written 2026-10-01) already recorded that the Cloudflare wall that used to
block ``publicnoticesc.com`` is gone -- a plain ``curl`` gets a clean 200 and a
301 redirect to ``https://www.scpublicnotices.com/(S(...))/default.aspx``, the
South Carolina Press Association's notice portal, built on "LRS Web
Solutions" -- the SAME vendor platform as ``ncnotices.com`` (see
``public_notices/_press_assoc.py``, which already documented this site by
name before any SC-specific driving code existed). Re-verified live again
today: still a clean 200, no WAF/CAPTCHA on the search path (see below).

WHAT WAS ACTUALLY BUILT (verified live 2026-10-02)
---------------------------------------------------
``Search.aspx`` is a classic ASP.NET WebForms postback UI, not a GET query
string or JSON API. Unlike ``ncnotices.com`` (whose county checkboxes sit
behind a collapsed accordion that needs a real browser), this is driveable
with plain ``httpx`` -- no Scrapling/Playwright, no stealth, no fingerprint
impersonation:

  1. GET ``Search.aspx`` -> collect every hidden input (``__VIEWSTATE``,
     ``__EVENTVALIDATION``, etc.) and the session-in-path URL
     (``/(S(id))/Search.aspx``) httpx was redirected to. Every subsequent
     POST must target THAT url (not the bare path), or the server mints a
     brand-new session per request and the postback doesn't register.
  2. POST a ``ddlPopularSearches`` change postback with value ``"4"`` --
     the site's OWN "Foreclosures" quick-search preset. This is the real
     keyword/notice-type filter asked for: live-verified, it expands to the
     canned OR-keyword set "real estate / foreclosure / foreclosed /
     foreclose / judicial sale / judgment / notice of sale / forfeiture /
     forfeit / magistrate sale" run against the FULL notice body, over the
     site's default 60-day lookback.
  3. POST a ``ddlPerPage`` change postback (value ``"50"``, the grid's max)
     to cut the page count ~5x, then walk ``GridView1_ctl01_btnNext`` --
     a full-page ImageButton postback (``btnNext.x``/``.y``, no AJAX/
     UpdatePanel, confirmed by the response always starting with a fresh
     ``<!DOCTYPE html>``) -- accumulating every page's rows.

COUNTY SCOPING: THE CHECKBOX FILTER IS SERVER-BUGGY, DON'T USE IT
------------------------------------------------------------------
The task as briefed called for ticking the ``lstCounty$N`` checkboxes for the
7 footprint counties (Spartanburg=41, Anderson=3, Pickens=38, Oconee=36,
Cherokee=10, Union=43, Laurens=29 -- confirmed live against the page's own
``<label for=...>`` text, not guessed). Two real problems ruled that out:

  1. **Checking more than one county in a single POST throws a server-side
     500.** Live-verified: submitting several ``lstCounty$N=on`` fields in
     one shot raises ``System.FormatException: Input string was not in a
     correct format`` inside ``UserControls_AdvancedSearchForm.
     lstCounty_SelectedIndexChanged`` -- the control's postback handler is
     written for ONE changed checkbox per postback (exactly how a browser
     driving one click at a time behaves), not a bulk multi-select. Doing it
     "the slow way" (one county-toggle postback per county, like
     ``sc_probate_net.py``'s county-change step) avoids the crash.
  2. **Even a single checked county does not filter keyword-search results.**
     Live-verified: with ONLY Anderson ticked and keyword "foreclosure", the
     results page's own breadcrumb read "County(s): Anderson" but 3 of the
     first 10 rows were Charleston County -- the checkbox is not a hard
     filter on this search path (browse-by-county may differ; keyword search
     does not honor it). Chasing a working checkbox sequence for a filter
     that doesn't filter would have been exactly the kind of time sink this
     audit is supposed to avoid.

The fix: run the "Foreclosures" preset STATEWIDE (no county ticked at all --
sidesteps the crash entirely) and filter to the footprint CLIENT-SIDE on each
row's own ``County:`` metadata field. Unlike ``ncnotices.com`` (whose grid
leaves ``County:`` blank on an unscoped search -- see
``nc_notices_counties.py``), this SC instance populates ``County:`` on every
row regardless of any checkbox state (live-verified across 50 statewide
rows) -- so the client-side gate is just as precise as a working server-side
one would have been, with none of the crash risk.

THE WALL THAT *IS* REAL: Details.aspx (confirmed, not bypassed)
-----------------------------------------------------------------
``Details.aspx`` -- the full notice body -- is gated behind an explicit
click-through Terms of Use ("I agree... I may not engage in any unauthorized
screen scraping, database scraping, or spidering... or use of any other
automated means to collect information from the site") AND a Cloudflare
Turnstile CAPTCHA ("You must complete the challenge in order to continue"),
live-confirmed on a real notice ID fetched moments earlier in the same
session. Per ``CLAUDE.md``'s compliance rule this is a real wall (CAPTCHA +
click-through ToS), not a ``robots.txt`` non-wall -- so per that rule we do
NOT fetch past it, agree to the ToS, or solve the challenge. This mirrors the
identical gate already documented and respected on ncnotices.com's
``Details.aspx`` (see ``_press_assoc.py`` and ``ncpublicnotices.py``'s
``_DETAIL_GATE_TOKENS``) -- same vendor, same gate, same answer. We still
link to it (``source_url``): it is a real, reachable public URL a human can
open and pass the CAPTCHA themselves; we just never fetch past it ourselves.

CONSEQUENCE FOR FIELD COVERAGE: the search-results grid only ever shows a
~300-400 char TRUNCATED preview of each notice (ending "...click 'view' to
open the full text."). That preview reliably carries the newspaper, publish
date, city/county, and -- for most rows -- a parseable SC Court of Common
Pleas case number (``YYYY-CP-CC-NNNNN``) and the plaintiff/defendant caption.
The property street address and the actual sale date nearly always sit past
the truncation point and come back ``None`` -- these are name+case leads for
the resolver to turn into properties, the same documented trade-off as the
NC sibling (``nc_notices_counties.py``) on the same vendor platform.

RELEVANCE GATE: a notice is only emitted if a SC case number
(``\\d{4}-?CP-?\\d{1,2}-?\\d{3,6}``) is found in the preview. The
"Foreclosures" preset's OR-keyword match happens server-side against the
FULL body (which we can't see), so a few non-case matches slip into the
result set -- a bulk delinquent-tax roster ("Sales# Map Number Owner..."),
an unrelated public-hearing/ordinance notice that happens to contain
"judgment" or "forfeiture". None of those carry a real court case number, so
requiring one is what keeps this scraper precise instead of reporting a tax
roster line as a foreclosure case.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED
from ...config import RuntimeConfig, SC_COUNTIES
from ...models import Listing, ListingType, PropertyKind
from . import _press_assoc as pa

log = structlog.get_logger()

BASE_URL = "https://www.scpublicnotices.com/Search.aspx"
# No SID -- the server mints a fresh session on an unscoped GET regardless of
# session state (live-verified), so this stays a stable, reachable link long
# after our own fetch session has expired. Same convention as the NC sibling.
_DETAIL_URL = "https://www.scpublicnotices.com/Details.aspx?ID={}"

PRE = "ctl00$ContentPlaceHolder1$as1$"
GRID = "ctl00$ContentPlaceHolder1$WSExtendedGridNP1$GridView1"
_NEXT_BTN_RENDERED_ID = (
    "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext"
)

# ddlPopularSearches option value for the site's own "Foreclosures" category
# (read live off the <select>'s <option value="4">Foreclosures</option>).
FORECLOSURES_CATEGORY = "4"
PER_PAGE = "50"  # the grid's own max option

# Safety cap on pages walked per run. Live-verified 2026-10-02: the
# "Foreclosures" preset over the site's default 60-day lookback returns ~20
# pages at 50/page statewide. Overridable for tuning without a code change.
MAX_PAGES = int(os.environ.get("PUBLICNOTICESC_MAX_PAGES", "25"))

#: The 7-county Upstate SC footprint (config.py SC_COUNTIES), in the
#: platform's own label spelling.
FOOTPRINT: tuple[str, ...] = tuple(c.name for c in SC_COUNTIES)
_FOOTPRINT_LOWER = {c.lower(): c for c in FOOTPRINT}

# ---- parsing ----------------------------------------------------------------

# SC Court of Common Pleas case number, e.g. "2025-CP-10-02044",
# "2026CP2301197" (no separators), "2026-CP-04-01837". Required gate: see
# module docstring "RELEVANCE GATE". The trailing boundary is a negative
# digit lookahead rather than \b: some publications run the case number
# straight into the plaintiff name with no separator at all
# ("DOCKETNO.2026CP1004189PennyMacLoanServices,LLC" -- live-verified
# 2026-10-02), and digit-into-letter is not a \b boundary.
_CASE_RE = re.compile(r"\b(\d{4}-?CP-?\d{1,2}-?\d{3,6})(?!\d)", re.I)

# Foreclosure/judicial-sale signal words. Not used as a relevance gate (the
# case-number gate does that job -- see docstring) but recorded in raw for
# anyone downstream who wants to know WHY a row matched.
_FORECLOSURE_RE = re.compile(
    r"foreclosure|deed of trust|mortgage|deficiency judgment|"
    r"master[- ]in[- ]equity|judicial sale|decree of foreclosure|"
    r"order of foreclosure", re.I)
# Explicit sale/auction language -> a sale has been scheduled or decreed
# (FORECLOSURE_SALE). Its absence -> a summons/complaint has been filed but
# no sale is announced yet (LIS_PENDENS), same split as the NC sibling.
_SALE_RE = re.compile(
    r"notice of sale|will sell|offer(?:ed)? for sale|public auction|"
    r"highest bidder|by virtue of a decree", re.I)

# The case caption's own venue declaration, e.g. "STATE OF SOUTH CAROLINA
# COUNTY OF FAIRFIELD IN THE COURT OF COMMON PLEAS" -- see _to_listing's
# county-selection comment for why this is preferred over county_meta when
# both are available. Restricted to the caption zone (first 300 chars of the
# preview) so a stray "county of" phrase deep in the body (unseen here since
# the preview truncates early, but defensive) can't be mistaken for the venue.
_CASE_COUNTY_RE = re.compile(r"\bCOUNTY\s+OF\s+([A-Z][A-Za-z]+)\b", re.I)

_PLAINTIFF_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.,'/\- ]{2,90}?),?\s+Plaintiffs?\b", re.I)
_DEFENDANT_RE = re.compile(
    r"Plaintiffs?,?\s*v[s.]{0,3}\.?\s+([A-Z][A-Za-z0-9 .,'/\-;&]{2,160}?)"
    r"(?:,?\s*Defendants?\b|$)", re.I)
# Both captures above routinely swallow the caption preamble that precedes
# the real party name ("CASE NO. 2026CP4204581 FIRST PIEDMONT FEDERAL..." --
# live-verified 2026-10-02) because nothing in the preceding "STATE OF SOUTH
# CAROLINA, COUNTY OF X; IN THE COURT OF..." text is disallowed by the
# capture's own character class. Strip it in _tidy_party instead of trying to
# make the capture regex itself case-number-aware.
_LEADING_CASE_NO_RE = re.compile(
    r"^.*?\b(?:CASE\s*(?:NO\.?|NUMBER)|C\.?/?A\.?\s*NO\.?|DOCKET\s*NO\.?)\s*"
    r"[:#.]?\s*[\dA-Z\-]{4,20}\s+", re.I)

# Word-boundaried street suffixes so "St" inside "Estate" can't match. Same
# shape as the NC sibling's _ADDR_RE -- almost never fires (the address sits
# past the preview truncation), but free when a shorter notice fits whole.
# (?<![-\d]) keeps the leading digit run from matching the tail of a case
# number ("...CP-37-00543" -- see _ADDR_BOILERPLATE_RE below for the second
# layer of defense against the same false positive).
_ADDR_RE = re.compile(
    r"(?<![-\d])\b(\d{1,6}\s+[A-Z0-9][\w .'\-]{2,40}?\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|"
    r"Avenue|Ave|Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|"
    r"Trail|Trl|Parkway|Pkwy)\b\.?)", re.I)
# A real _ADDR_RE match is always short. Confirmed live 2026-10-02: without
# this guard, "C/A No: 2025-CP-37-00543 BY VIRTUE OF A DECREE of the Court"
# parsed as street_address "00543 BY VIRTUE OF A DECREE of the Court" -- a
# wrong value in a real listing, the exact "silent success" failure mode
# this codebase is built to catch. Same defense-in-depth the NC sibling
# (nc_notices_counties.py) uses against the identical failure mode.
_ADDR_MAX_LEN = 60
_ADDR_BOILERPLATE_RE = re.compile(
    r"\b(?:BY\s+VIRTUE|DECREE|NOTICE\s+OF|COURT\s+OF\s+COMMON\s+PLEAS|"
    r"DEED\s+OF\s+TRUST|FORECLOSURE|MASTER\s+IN\s+EQUITY|CASE\s+NO|"
    r"C/?A\s+NO|DOCKET\s+NO|SOUTH\s+CAROLINA)\b", re.I)


def _plausible_address(candidate: str | None) -> bool:
    return (bool(candidate) and len(candidate) <= _ADDR_MAX_LEN
            and not _ADDR_BOILERPLATE_RE.search(candidate))

_MONTHS = (r"January|February|March|April|May|June|July|August|September|"
           r"October|November|December")
_SALE_DATE_RE = re.compile(
    rf"(?:will sell|offer(?:ed)? for sale|public auction|highest bidder)"
    rf"\b[^.]{{0,160}}?\b((?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}})", re.I)
# SC Master-in-Equity sales favor the ordinal form: "will on the 17th day of
# July, 2026, offer for sale...".
_ORDINAL_SALE_DATE_RE = re.compile(
    rf"\bon\s+the\s+(\d{{1,2}})(?:st|nd|rd|th)\s+day\s+of\s+"
    rf"((?:{_MONTHS}))\,?\s+(\d{{4}})", re.I)


def _hidden_fields(html: str) -> dict[str, str]:
    """Collect every hidden input (VIEWSTATE, EVENTVALIDATION, etc.)."""
    tree = HTMLParser(html)
    out: dict[str, str] = {}
    for inp in tree.css("input[type=hidden]"):
        name = inp.attributes.get("name")
        if name:
            out[name] = inp.attributes.get("value") or ""
    return out


def _tidy_party(value: str | None, max_len: int = 160) -> str | None:
    """Trim a captured party name/list of trailing connectives + punctuation.

    ``max_len`` is higher than the NC sibling's ``_tidy_name`` (80) because a
    SC defendant caption often names every heir/co-defendant in a list
    ("JOHN DOE, JANE ROE, and the Unknown Heirs of...") -- real signal, not
    noise, so it isn't truncated away.
    """
    if not value:
        return None
    s = pa.clean_text(value).strip(" ,.;:-")
    s = _LEADING_CASE_NO_RE.sub("", s, count=1).strip(" ,.;:-")
    s = re.sub(r"\s+(?:and|to|of|the)$", "", s, flags=re.I).strip(" ,.;:-")
    if len(s) < 3 or len(s) > max_len:
        return None
    if not re.search(r"[A-Za-z]{2}", s):
        return None
    return s


def _sale_date(text: str) -> datetime | None:
    """Best-effort sale date. Usually None -- it sits past the preview cut."""
    m = _SALE_DATE_RE.search(text)
    if m:
        parts = re.split(r"[,\s]+", m.group(1).strip())
        if len(parts) >= 3:
            month, day, year = parts[:3]
            d = pa.parse_date(f"{month} {day}, {year}")
            if d:
                return d
    m2 = _ORDINAL_SALE_DATE_RE.search(text)
    if m2:
        day, month, year = m2.group(1), m2.group(2), m2.group(3)
        return pa.parse_date(f"{month} {day}, {year}")
    return None


def _classify(text: str, case_number: str | None) -> tuple[ListingType, str] | None:
    """Map a notice preview to (ListingType, kind). None = not a usable lead.

    See module docstring "RELEVANCE GATE": requiring a real SC case number is
    what separates a single-property foreclosure case from the tax-roster /
    public-hearing rows that slip into the "Foreclosures" preset's full-body
    OR-keyword match without one.
    """
    if not case_number:
        return None
    if _SALE_RE.search(text):
        return ListingType.FORECLOSURE_SALE, "sale"
    return ListingType.LIS_PENDENS, "filed"


def _to_listing(notice: dict, slug: str) -> Listing | None:
    """Turn one parsed grid row (from ``_press_assoc.parse_grid``) into a
    Listing, or None if out of footprint / not a usable lead."""
    text = notice.get("text") or ""
    if not text:
        return None

    county_meta = (notice.get("county_meta") or "").strip()
    # ``county_meta`` is the grid's "County:" field -- live-verified
    # 2026-10-04 (150-row statewide sample across the real "Foreclosures"
    # preset) this is NOT reliably the CASE's own county: it reads back the
    # PUBLICATION's county on real rows whose own caption names a different
    # one (confirmed 3 of 55 checked rows, e.g. notice 649899: county_meta
    # "Richland" but the case's own text reads "STATE OF SOUTH CAROLINA
    # COUNTY OF FAIRFIELD IN THE COURT OF COMMON PLEAS" -- the shared
    # _press_assoc.py parse_grid() docstring already carried this exact
    # caveat generically; this is the live confirmation it holds for this
    # site too, not just the NC sibling). The case caption's own "COUNTY OF
    # X" is the court VENUE, which for a SC judicial foreclosure (this
    # module's foreclosure_process) is the authoritative subject county, so
    # prefer it whenever it names a real footprint county; county_meta is
    # the fallback for the (common) case where the preview truncates before
    # reaching a caption, or the caption uses other phrasing.
    case_county_m = _CASE_COUNTY_RE.search(text[:300])
    if case_county_m:
        # The caption names a real venue -- it governs outright, in or out
        # of footprint. Falling back to county_meta here (instead of
        # rejecting on a non-footprint caption county) would reopen the
        # exact mislabel risk this fix closes: a footprint-publication case
        # whose own caption names a DIFFERENT, non-footprint county.
        county = _FOOTPRINT_LOWER.get(case_county_m.group(1).lower())
        county_source = "caption"
    else:
        county = _FOOTPRINT_LOWER.get(county_meta.lower())
        county_source = "publication_meta"
    if not county:
        # Out of the 7-county footprint. The server-side county checkbox
        # filter does not reliably restrict keyword-search results (see
        # module docstring), so this client-side gate on the grid's own
        # (reliably-populated, live-verified) County: field IS the filter.
        return None

    case_m = _CASE_RE.search(text)
    case_number = case_m.group(1).upper() if case_m else None
    classified = _classify(text, case_number)
    if not classified:
        return None
    listing_type, kind = classified

    plaintiff_m = _PLAINTIFF_RE.search(text)
    defendant_m = _DEFENDANT_RE.search(text)
    addr_m = _ADDR_RE.search(text)
    street_address = pa.clean_text(addr_m.group(1)) if addr_m else None
    if street_address and not _plausible_address(street_address):
        street_address = None

    plaintiff = _tidy_party(plaintiff_m.group(1)) if plaintiff_m else None
    defendant = _tidy_party(defendant_m.group(1)) if defendant_m else None
    published = notice.get("published_at")
    notice_id = notice.get("notice_id")

    raw: dict = {
        "public_notice": {
            "site": "scpublicnotices.com",
            "notice_id": notice_id,
            "publication": notice.get("publication") or None,
            "publication_county": county_meta or None,
            # "caption" when the case's own "COUNTY OF X" venue text drove
            # the county (preferred -- see _to_listing), "publication_meta"
            # when it fell back to the grid's County: field.
            "county_source": county_source,
            "publication_city": notice.get("city_meta") or None,
            "publication_date": notice.get("date_text") or None,
            "published_at": published.isoformat() if published else None,
            "kind": kind,
            "foreclosure_signal": bool(_FORECLOSURE_RE.search(text)),
            "preview_text": text[:2000],
            "preview_truncated": True,
        }
    }

    return Listing(
        source=slug,
        source_url=_DETAIL_URL.format(notice_id) if notice_id else BASE_URL,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=county,
        city=(notice.get("city_meta") or "").strip().title() or None,
        street_address=street_address,
        sale_date=_sale_date(text),
        foreclosure_process="judicial",  # SC foreclosures run through the courts, unlike NC's power-of-sale
        plaintiff=plaintiff,
        defendant=defendant,
        # Mirrored onto owner_name too -- same convention documented at
        # length in ncpublicnotices.py: ~20 enrichers read li.owner_name with
        # no defendant fallback of their own.
        owner_name=defendant,
        case_number=case_number,
        description=text[:400],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


# ---- fetch -------------------------------------------------------------


class PublicNoticeSC(BaseScraper):
    slug = "public_notices.publicnoticesc"
    name = "Public Notice SC (SCPA)"
    category = "public_notice"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        cfg = RuntimeConfig.from_env()
        out: list[Listing] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(
            headers={"User-Agent": cfg.user_agent},
            follow_redirects=True,
            timeout=cfg.request_timeout_s + 30.0,
        ) as client:
            r0 = await client.get(BASE_URL)
            r0.raise_for_status()
            # The session id is in the URL PATH, not a cookie -- every
            # subsequent POST must target this exact redirected URL, or the
            # server mints a brand-new session per request and the postback
            # (and the VIEWSTATE we just read) is silently discarded.
            session_url = str(r0.url)
            fields = _hidden_fields(r0.text)

            form = dict(fields)
            form["__EVENTTARGET"] = PRE + "ddlPopularSearches"
            form["__EVENTARGUMENT"] = ""
            form[PRE + "ddlPopularSearches"] = FORECLOSURES_CATEGORY
            try:
                r1 = await client.post(session_url, data=form)
                r1.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("publicnoticesc.category_select_failed", error=str(exc)[:200])
                self.last_outcome = OUTCOME_BLOCKED
                return []
            html = r1.text
            fields = _hidden_fields(html)

            form = dict(fields)
            form["__EVENTTARGET"] = f"{GRID}$ctl01$ddlPerPage"
            form["__EVENTARGUMENT"] = ""
            form[f"{GRID}$ctl01$ddlPerPage"] = PER_PAGE
            try:
                r2 = await client.post(session_url, data=form)
                r2.raise_for_status()
                html = r2.text
                fields = _hidden_fields(html)
            except httpx.HTTPError as exc:
                # Non-fatal -- fall through and page at the default 10/page.
                log.warning("publicnoticesc.perpage_bump_failed", error=str(exc)[:200])

            pages_walked = 0
            seen_page_labels: set[str] = set()
            in_footprint = 0
            while True:
                notices = pa.parse_grid(html)
                for n in notices:
                    li = _to_listing(n, self.slug)
                    if li is None:
                        continue
                    key = (li.raw.get("public_notice") or {}).get("notice_id") or li.source_url
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(li)
                    self.partial.append(li)
                    in_footprint += 1

                pages_walked += 1
                cur = pa.current_page(html)
                total = pa.total_pages(html)
                if cur is not None:
                    seen_page_labels.add(str(cur))
                if pages_walked >= MAX_PAGES:
                    break
                if cur is not None and total is not None and cur >= total:
                    break
                if _NEXT_BTN_RENDERED_ID not in html:
                    break  # no pager at all -- a single page of results
                if f'id="{_NEXT_BTN_RENDERED_ID}" disabled="disabled"' in html:
                    break  # last page

                form = dict(fields)
                form["__EVENTTARGET"] = ""
                form["__EVENTARGUMENT"] = ""
                form[f"{GRID}$ctl01$btnNext.x"] = "5"
                form[f"{GRID}$ctl01$btnNext.y"] = "5"
                try:
                    await asyncio.sleep(0.5)  # polite pacing between full-page postbacks
                    r = await client.post(session_url, data=form)
                    r.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning(
                        "publicnoticesc.page_fetch_failed",
                        page=pages_walked, error=str(exc)[:200],
                    )
                    break
                html = r.text
                new_cur = pa.current_page(html)
                if new_cur is not None and str(new_cur) in seen_page_labels:
                    break  # didn't advance -- stuck / last page
                fields = _hidden_fields(html)

            log.info(
                "publicnoticesc.fetch_done",
                pages=pages_walked, in_footprint=in_footprint,
            )
        return out
