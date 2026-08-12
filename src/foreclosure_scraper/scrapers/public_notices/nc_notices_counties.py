"""NC public notices, county-scoped (ncnotices.com — NC Press Association).

WHY THIS EXISTS ALONGSIDE ``public_notices.ncnotices``
------------------------------------------------------
The older module keyword-searches ncnotices.com STATEWIDE and then tries to
recover the county by regexing "<Name> County" out of the ~300-char preview.
Verified 2026-07-31 against the live grid: on a statewide search the platform
returns each row's ``County:`` metadata field EMPTY (50/50 rows blank), so that
recovery mostly fails and the footprint yield collapses — a full run logged
"foreclosure sale" -> 2 rows, "substitute trustee" -> 1, "tax foreclosure" -> 0,
against a result set of 20 pages x 50 rows.

The unlock is the advanced-search sidebar's COUNTY CHECKBOX LIST. Ticking
counties server-side (a) restricts the result set to our footprint instead of
all 100 NC counties, and (b) makes the platform populate each row's ``County:``
metadata. With all 11 footprint counties ticked, a 30-day "foreclosure" search
returns 5 pages x 50 rows that are already in-footprint.

Mechanism (verified live 2026-07-31)
------------------------------------
ASP.NET WebForms, cookieless session path ``/(S(id))/``. The sidebar filter
groups are collapsed accordions, so the county checkboxes are present but
``display:none`` — Playwright's ``check()`` refuses them. Expand the group by
clicking ``label.header`` first; where the element is still not clickable, fall
back to the site's OWN ``onclick`` handler via ``element.click()`` in page JS
(that handler is what fires ``__doPostBack``). Do NOT pre-set ``.checked``: the
subsequent click would toggle it straight back off.

Each ticked county is one full postback, so the 11 ticks happen ONCE and all
queries then run inside that same page session. Per query: fill ``txtSearch``,
click ``btnGo``, bump ``ddlPerPage`` to its max (50), then walk ``btnNext``
until the page cap. Match mode (``rdoType``: All Words / Any Words / Exact
Phrase) is also a postback, so queries are ordered to toggle it exactly once.

WALL — the full notice body is NOT available
--------------------------------------------
``Details.aspx`` is gated behind an "I Agree" interstitial plus reCAPTCHA
(verified 2026-07-31: the detail HTML contains g-recaptcha). We do not fetch,
solve, or work around it. Everything below parses the ~300-char grid preview
only. Consequence, stated plainly: the preview reliably carries the notice
caption, the case number, the subject county and the party name, but the
property ADDRESS, PARCEL/PIN and SALE DATE nearly always sit past the
truncation point. Those fields are parsed best-effort and are usually None;
these rows are name+case leads for the resolver to turn into properties, not
address-complete listings.

Seasonality note: the NCGS 105-369 tax-lien advertisements ("ADVERTISEMENT OF
TAX LIENS ON REAL PROPERTY") are an annual filing published ~March-June, so the
tax-lien query legitimately returns 0 outside that window. It is kept year-round
because the ad is cheap to check and misses nothing when absent.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from . import _press_assoc as pa

log = structlog.get_logger()

_BASE = "https://www.ncnotices.com/Search.aspx"
_DETAIL_URL = "https://www.ncnotices.com/Details.aspx?ID={}"

# Advanced-search element ids, confirmed against the live DOM (2026-07-31).
_DIV_COUNTY = "#ctl00_ContentPlaceHolder1_as1_divCounty"
_DIV_DATE = "#ctl00_ContentPlaceHolder1_as1_divDateRange"
_LST_COUNTY = "ctl00_ContentPlaceHolder1_as1_lstCounty"
_TXT_DAYS = "#ctl00_ContentPlaceHolder1_as1_txtLastNumDays"
_TXT_SEARCH = "#ctl00_ContentPlaceHolder1_as1_txtSearch"
_BTN_GO = "#ctl00_ContentPlaceHolder1_as1_btnGo"
_DDL_PER_PAGE = "select[id$='_ddlPerPage']"
_BTN_NEXT = "input[id$='_btnNext']"
_PER_PAGE_MAX = "50"          # ddlPerPage tops out at 50 (no 100 option)
_RDO_TYPE = {"AND": "ctl00_ContentPlaceHolder1_as1_rdoType_0",   # All Words
             "OR": "ctl00_ContentPlaceHolder1_as1_rdoType_1",    # Any Words
             "EXACT": "ctl00_ContentPlaceHolder1_as1_rdoType_2"}  # Exact Phrase
_RENDER_TIMEOUT_MS = 600_000

#: The 19 NC footprint counties (11 WNC core + 8 coastal added 2026-08-12),
#: in the platform's own label spelling.
FOOTPRINT: tuple[str, ...] = (
    "Buncombe", "Henderson", "Gaston", "Cleveland", "Rutherford", "Burke",
    "Lincoln", "McDowell", "Polk", "Transylvania", "Mitchell",
    # Coastal NC (brought into scope 2026-08-12):
    "Currituck", "Dare", "Hyde", "Carteret", "Onslow", "Pender",
    "New Hanover", "Brunswick",
)
_FOOTPRINT_LOWER = {c.lower(): c for c in FOOTPRINT}

# Publication window and per-query page cap. The platform's "current search"
# index only reaches back 12 months; older notices need its Archive Search.
_DAYS = os.environ.get("NCNOTICES_COUNTY_DAYS", "30")
_MAX_PAGES = int(os.environ.get("NCNOTICES_COUNTY_MAX_PAGES", "6"))
_YEAR_DAYS = "365"

# (keyword, match mode, page cap, lookback days). AND-mode queries run first so
# the match-mode radio (itself a postback) is toggled exactly once for the
# EXACT block.
#
# The lookback varies by cadence, which matters: recurring court notices are
# fresh weekly and a 30-day window keeps them current, but the NCGS 105-369
# tax-lien advertisement is an ANNUAL filing published ~March-June. On a 30-day
# window it returns 0 for ten months of the year; over 12 months it returns the
# handful that exist (7 across the footprint, 2026-07-31). It is cheap — one
# page — so it gets the full year and lands whenever the run happens.
_QUERIES: tuple[tuple[str, str, int, str], ...] = (
    # Catches substitute-trustee sales, upset bids, notices of default AND the
    # county-as-plaintiff tax-foreclosure suits (NCGS 105-374), which all carry
    # the word "foreclosure" in the caption.
    ("foreclosure", "AND", _MAX_PAGES, _DAYS),
    ("delinquent taxes", "AND", 3, _YEAR_DAYS),
    # NCGS 105-369 annual tax-lien advertisement — exact caption, few hits.
    ("advertisement of tax liens", "EXACT", 2, _YEAR_DAYS),
    # NCGS 28A-14-1 estate notice — exact caption keeps out generic "creditors".
    ("notice to creditors", "EXACT", _MAX_PAGES, _DAYS),
)

# ---- classification -------------------------------------------------------
# A county/municipality suing as plaintiff IS the NC in-rem tax-foreclosure
# caption ("COUNTY OF BUNCOMBE, a Body Politic and Corporate, Plaintiff").
# The word "tax" itself usually sits past the preview truncation, so the
# caption is the signal.
_TAX_AD_RE = re.compile(r"advertisement of tax liens|tax liens on real property|"
                        r"105[-\s]?369|unpaid\s+(?:20\d{2}\s+)?taxes are a lien", re.I)
_TAX_PLAINTIFF_RE = re.compile(
    r"(?:county|city|town|village) of\s+[A-Z][A-Za-z .'-]{2,25}?,?\s*"
    r"(?:a body politic[^,]*,?\s*)?plaintiff", re.I)
_TAX_WORDS_RE = re.compile(r"\b(?:delinquent tax|unpaid tax|tax lien|tax foreclosure|"
                           r"in rem|105-374)\b", re.I)
_PROBATE_RE = re.compile(
    r"notice to creditors|having qualified as (?:the )?"
    r"(?:limited )?(?:executor|executrix|administrator|administratrix|"
    r"collector|personal representative)|estate of[^,]{2,60},?\s*deceased", re.I)
_SALE_RE = re.compile(
    r"notice of (?:default and )?(?:substitute trustee'?s? )?foreclosure sale|"
    r"foreclosure sale of real property|notice of sale of real estate|"
    r"power of sale|will be (?:offered for sale|sold)|public auction|upset bid", re.I)
_FORECLOSURE_RE = re.compile(
    r"foreclosure|substitute trustee|deed of trust", re.I)
_PUBLICATION_SERVICE_RE = re.compile(
    r"notice of service of process by publication|service by publication|"
    r"summons|notice of hearing", re.I)

# ---- field extraction -----------------------------------------------------
# NC case numbers: 26SP000128-440, 22CVD003028-100, 26CV003253-100, 26E001083-100
# plus the older spaced form "24 SP 123".
_CASE_RE = re.compile(r"\b(\d{2}(?:SP|CVD|CVS|CV|E|M)\d{3,9}(?:-\d{2,4})?)\b")
_CASE_SPACED_RE = re.compile(r"\b(\d{2}\s+(?:SP|CVD|CVS|CV|E)\s+\d{3,6})\b", re.I)
_PARCEL_RE = re.compile(
    r"\b(?:PIN|Parcel(?:\s+(?:ID|Number|No\.?))?|Tax\s+Map)\s*[:#]?\s*"
    r"([0-9][0-9A-Za-z.\-]{4,24})", re.I)
# Word-boundaried street suffixes so "St" inside "Estate" can't match.
_ADDR_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Z0-9][\w .'\-]{2,40}?\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|"
    r"Avenue|Ave|Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|"
    r"Trail|Trl|Parkway|Pkwy)\b\.?)", re.I)
_MONTHS = (r"January|February|March|April|May|June|July|August|September|"
           r"October|November|December")
_SALE_DATE_RE = re.compile(
    rf"(?:will be (?:offered for sale|sold)|sale (?:will be held|is scheduled)|"
    rf"public auction|auction)\b[^.]{{0,140}}?\b((?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}})",
    re.I)
_BOOK_PAGE_RE = re.compile(r"Book\s+(?:No\.\s*)?([0-9A-Za-z]{1,8}),?\s+(?:at\s+)?"
                           r"Page\s+([0-9A-Za-z]{1,8})", re.I)
# Grantor of the foreclosed Deed of Trust = the current record owner.
_GRANTOR_RE = re.compile(
    r"(?:deed of trust\s+)?(?:executed(?:\s+and\s+delivered)?|made|given)\s+by\s+"
    r"([A-Z][A-Za-z.'\- ]{2,70}?)(?:\s*\(|,?\s+(?:dated|to\s+[A-Z]|and recorded|"
    r"in favor of|as grantor|Trustee))", re.I)
_RECORD_OWNER_RE = re.compile(
    r"PRESENT RECORD OWNER\(?S?\)?\s*:?\s*([A-Z][A-Za-z.'\- ]{2,70}?)(?:\)|,|\s+to\s+|$)", re.I)
_VS_RE = re.compile(
    r"\bv[s.]{1,3}\.?\s+([A-Z][A-Za-z.'\- ]{2,70}?)"
    r"(?:\s*,|;|\s+et\.?\s*al|\s+defendant|\s+TO\s*:|$)", re.I)
_ESTATE_RE = re.compile(
    r"(?:the\s+)?estate of\s+([A-Z][A-Za-z.'\- ]{2,70}?)"
    r"(?:,|\s+aka\b|\s+a/?k/?a\b|\s+deceased|\s*\()", re.I)
# Plaintiff, deliberately narrow: only the GOVERNMENT entity that brings a tax
# action. A permissive "anything before the word Plaintiff" pattern swallows the
# caption boilerplate that precedes it — "STATE OF NORTH CAROLINA COUNTY OF
# RUTHERFORD RUTHERFORD COUNTY, Plaintiff" came back whole. Matching the entity
# shape instead lets the engine skip the boilerplate and land on the party.
# Private plaintiffs (a bank on a power-of-sale) are simply left None: on this
# source they are rare and the trustee/grantor is the useful name anyway.
_PLAINTIFF_RE = re.compile(
    r"\b((?:CITY|TOWN|VILLAGE|COUNTY) OF [A-Z][A-Za-z]+"
    r"(?:\s+and\s+[A-Z][A-Za-z]+\s+COUNTY)?"
    r"|[A-Z][A-Za-z]+\s+COUNTY)\s*,?\s*"
    r"(?:a body politic[^,]{0,40},?\s*)?Plaintiffs?\b", re.I)
# Subject county named in the notice body, e.g. "HENDERSON COUNTY" / "County of Buncombe".
_BODY_COUNTY_RE = re.compile(
    r"\b(" + "|".join(FOOTPRINT) + r")\s+COUNTY\b", re.I)
_COUNTY_OF_RE = re.compile(
    r"\bCOUNTY OF\s+(" + "|".join(FOOTPRINT) + r")\b", re.I)


def _tidy_name(value: str | None) -> str | None:
    """Trim a captured party name of trailing connectives and stray punctuation."""
    if not value:
        return None
    s = pa.clean_text(value).strip(" ,.;:-")
    s = re.sub(r"\s+(?:and|to|dated|of)$", "", s, flags=re.I).strip(" ,.;:-")
    if len(s) < 3 or len(s) > 80:
        return None
    if not re.search(r"[A-Za-z]{2}", s):
        return None
    return s


def _subject_county(text: str, county_meta: str) -> str | None:
    """Resolve the county the notice is ABOUT.

    The grid's ``County:`` field is the publishing paper's county, which is
    routinely wrong for the notice: a Buncombe paper (Beacon Tribune) carries
    Henderson County foreclosure sales. So read the body first and only fall
    back to the publication county.
    """
    m = _BODY_COUNTY_RE.search(text) or _COUNTY_OF_RE.search(text)
    if m:
        return _FOOTPRINT_LOWER.get(m.group(1).lower())
    return _FOOTPRINT_LOWER.get((county_meta or "").strip().lower())


def _classify(text: str) -> tuple[ListingType, str] | None:
    """Map a notice preview to (ListingType, kind). None = not a lead we want.

    Order matters: the annual tax-lien ad and the county-as-plaintiff tax suits
    must be caught before the generic foreclosure branch, because they also
    carry sale/foreclosure language.
    """
    if _TAX_AD_RE.search(text):
        return ListingType.TAX_LIEN, "tax_lien_ad"
    if _TAX_PLAINTIFF_RE.search(text) or _TAX_WORDS_RE.search(text):
        # A tax action: a scheduled sale is a TAX_SALE, a summons/publication
        # notice is the suit being filed (pre-sale) — that's a lis pendens.
        if _SALE_RE.search(text):
            return ListingType.TAX_SALE, "tax_foreclosure"
        if _PUBLICATION_SERVICE_RE.search(text):
            return ListingType.LIS_PENDENS, "tax_foreclosure"
        return ListingType.TAX_LIEN, "tax_foreclosure"
    if _PROBATE_RE.search(text):
        return ListingType.PROBATE_NOTICE, "estate"
    if _FORECLOSURE_RE.search(text):
        if _SALE_RE.search(text):
            return ListingType.FORECLOSURE_SALE, "foreclosure"
        return ListingType.LIS_PENDENS, "foreclosure"
    return None


def _party(text: str, kind: str) -> str | None:
    """The property owner named in the notice, or None.

    Every branch of this source names the owner, just under a different label:
    an estate notice names the decedent, a power-of-sale notice names the
    grantor of the foreclosed Deed of Trust, and a tax/civil action names the
    defendant. Preference runs most-authoritative first — an explicit
    "PRESENT RECORD OWNER(S)" beats the grantor, which beats the defendant
    caption (which can pick up a co-defendant).
    """
    if kind == "estate":
        m = _ESTATE_RE.search(text)
        return _tidy_name(m.group(1)) if m else None
    for pattern in (_RECORD_OWNER_RE, _GRANTOR_RE, _VS_RE):
        m = pattern.search(text)
        if m:
            name = _tidy_name(m.group(1))
            if name:
                return name
    return None


def _sale_date(text: str) -> datetime | None:
    """Best-effort sale date. Usually None — the date sits past the preview cut."""
    m = _SALE_DATE_RE.search(text)
    if not m:
        return None
    month, day, year = re.split(r"[,\s]+", m.group(1).strip())[:3]
    return pa.parse_date(f"{month} {day}, {year}")


def _to_listing(notice: dict, slug: str) -> Listing | None:
    """Turn one parsed grid row into a Listing, or None if out of scope."""
    text = notice.get("text") or ""
    if not text:
        return None
    classified = _classify(text)
    if not classified:
        return None
    listing_type, kind = classified
    county = _subject_county(text, notice.get("county_meta", ""))
    if not county:
        return None

    owner = _party(text, kind)
    case_m = _CASE_RE.search(text) or _CASE_SPACED_RE.search(text)
    parcel_m = _PARCEL_RE.search(text)
    addr_m = None if kind == "estate" else _ADDR_RE.search(text)
    book_m = _BOOK_PAGE_RE.search(text)
    plaintiff_m = _PLAINTIFF_RE.search(text)
    published = notice.get("published_at")

    raw: dict = {
        "public_notice": {
            "site": "ncnotices.com",
            "notice_id": notice.get("notice_id"),
            "publication": notice.get("publication") or None,
            "publication_county": notice.get("county_meta") or None,
            "publication_date": notice.get("date_text") or None,
            # Machine-readable copy of the same date, for downstream recency.
            "published_at": published.isoformat() if published else None,
            "kind": kind,
            "preview_text": text[:4000],
            "preview_truncated": True,
        }
    }
    if book_m:
        # Deed-of-Trust book/page — the join key for a ROD document pull.
        raw["public_notice"]["deed_of_trust"] = {
            "book": book_m.group(1), "page": book_m.group(2)}
    if kind == "estate":
        raw["relationship_signal"] = {
            "kind": "probate", "keyword": "notice_to_creditors",
            "tagged_at": datetime.utcnow().isoformat() + "Z"}
        raw["probate"] = {"decedent": owner, "es_case_number":
                          case_m.group(1) if case_m else None}

    return Listing(
        source=slug,
        source_url=_DETAIL_URL.format(notice.get("notice_id")),
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        city=(notice.get("city_meta") or "").strip().title() or None,
        street_address=(pa.clean_text(addr_m.group(1)) if addr_m else None),
        parcel_id=(parcel_m.group(1) if parcel_m else None),
        sale_date=_sale_date(text) if kind != "estate" else None,
        foreclosure_process=("tax" if kind in ("tax_lien_ad", "tax_foreclosure")
                             else "power_of_sale" if kind == "foreclosure" else None),
        plaintiff=(_tidy_name(plaintiff_m.group(1)) if plaintiff_m else None),
        defendant=owner,
        owner_name=owner,
        case_number=(case_m.group(1) if case_m else None),
        description=text[:200],
        # first_seen tracks when WE saw the row (sibling-scraper convention);
        # the notice's own publication date rides along in raw.
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


async def _render_queries() -> list[str]:
    """Drive the advanced search once and return every captured results page.

    One browser session: expand the County accordion, tick the 11 footprint
    counties (one postback each), set the publication window, then run each
    query and page through it. Every step is non-fatal — a broken step returns
    whatever was captured so far rather than losing the run.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("nc_notices_counties.scrapling_missing")
        return []

    pages: list[str] = []
    stats: dict[str, int] = {}

    async def _settle(page, ms: int = 1500) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        try:
            await page.wait_for_timeout(ms)
        except Exception:
            pass

    async def _ensure_expanded(page, container: str, probe: str) -> None:
        """Open a sidebar filter group if it is closed.

        The groups are accordions whose inputs are ``display:none`` while
        collapsed, and clicking the header TOGGLES — so this checks a known
        child first and is safe to call repeatedly. It has to be: every btnGo
        is a full postback that re-renders the sidebar collapsed again.
        """
        try:
            if await page.is_visible(probe):
                return
        except Exception:
            pass
        try:
            await page.click(f"{container} label.header", timeout=8000)
            await page.wait_for_timeout(600)
        except Exception:
            pass

    async def _tick_county(page, name: str) -> bool:
        cid = await page.evaluate(
            """(args) => {
                const ul = document.getElementById(args.list);
                if (!ul) return null;
                for (const lb of ul.querySelectorAll('label')) {
                    if ((lb.textContent || '').trim().toLowerCase() === args.name.toLowerCase())
                        return lb.getAttribute('for');
                }
                return null;
            }""",
            {"list": _LST_COUNTY, "name": name},
        )
        if not cid:
            log.warning("nc_notices_counties.county_missing", county=name)
            return False
        # Each tick is a postback that re-collapses the group, so re-open it
        # before the next one — otherwise every check() burns its full timeout
        # against a display:none input before falling through to the JS path.
        await _ensure_expanded(page, _DIV_COUNTY, f"#{cid}")
        try:
            await page.check(f"#{cid}", timeout=6000)
        except Exception:
            # The site's own onclick fires __doPostBack. click() alone both
            # ticks the box and posts back — pre-setting .checked would make
            # this click untick it.
            try:
                await page.evaluate(f"() => document.getElementById({cid!r}).click()")
            except Exception:
                return False
        await _settle(page)
        try:
            return bool(await page.evaluate(
                f"() => {{const e = document.getElementById({cid!r}); return e && e.checked;}}"))
        except Exception:
            return False

    async def _run_query(page, keyword: str, cap: int, days: str) -> int:
        try:
            # The window is form state, so it is re-applied per query — btnGo
            # re-runs the whole search with whatever is in the box. The previous
            # query's postback re-collapsed the group, hence the re-expand.
            await _ensure_expanded(page, _DIV_DATE, _TXT_DAYS)
            await page.fill(_TXT_DAYS, str(days), timeout=6000)
        except Exception as exc:
            log.warning("nc_notices_counties.date_window_fail",
                        keyword=keyword, error=str(exc)[:120])
        try:
            await page.fill(_TXT_SEARCH, keyword, timeout=8000)
            await page.click(_BTN_GO, timeout=10000)
        except Exception as exc:
            log.warning("nc_notices_counties.query_submit_fail",
                        keyword=keyword, error=str(exc)[:160])
            return 0
        await _settle(page, 2500)
        try:
            await page.select_option(_DDL_PER_PAGE, _PER_PAGE_MAX, timeout=8000)
            await _settle(page, 2000)
        except Exception:
            pass  # grid may be unpaged (few results) — page 1 is still valid

        captured = 0
        for _ in range(max(1, cap)):
            try:
                html = await page.content()
            except Exception:
                break
            pages.append(html)
            captured += 1
            total = pa.total_pages(html)
            current = pa.current_page(html)
            if total is not None and current is not None and current >= total:
                break
            try:
                btn = await page.query_selector(_BTN_NEXT)
                if not btn or not await btn.is_enabled():
                    break
                await btn.click(timeout=8000)
            except Exception:
                break
            await _settle(page, 2000)
            try:
                if pa.current_page(await page.content()) == current:
                    break   # pager stuck — stop rather than re-capture page N
            except Exception:
                break
        return captured

    async def page_action(page):
        await _settle(page, 1000)
        await _ensure_expanded(page, _DIV_COUNTY, f"#{_LST_COUNTY}")
        ticked = [c for c in FOOTPRINT if await _tick_county(page, c)]
        stats["counties_ticked"] = len(ticked)
        log.info("nc_notices_counties.counties_selected",
                 ticked=len(ticked), of=len(FOOTPRINT))
        if not ticked:
            # Without the county filter this is the old statewide scrape, whose
            # rows carry no county metadata — bail rather than emit junk.
            log.warning("nc_notices_counties.no_county_filter")
            return

        mode = "AND"   # the form's default (All Words)
        for keyword, want_mode, cap, days in _QUERIES:
            if want_mode != mode:
                try:
                    await page.evaluate(
                        f"() => document.getElementById({_RDO_TYPE[want_mode]!r}).click()")
                    await _settle(page)
                    mode = want_mode
                except Exception as exc:
                    log.warning("nc_notices_counties.mode_switch_fail",
                                mode=want_mode, error=str(exc)[:120])
            captured = await _run_query(page, keyword, cap, days)
            stats[f"pages:{keyword}"] = captured
            log.info("nc_notices_counties.query_done",
                     keyword=keyword, mode=want_mode, days=days, pages=captured)

    try:
        await StealthyFetcher.async_fetch(
            _BASE, headless=True, network_idle=True,
            timeout=_RENDER_TIMEOUT_MS, page_action=page_action,
        )
    except Exception as exc:
        log.warning("nc_notices_counties.fetch_fail", error=str(exc)[:200])
    log.info("nc_notices_counties.render_done", pages=len(pages), **stats)
    return pages


class NCNoticesCounties(BaseScraper):
    slug = "public_notices.nc_notices_counties"
    name = "NC Public Notices, county-scoped (ncnotices.com — foreclosure/tax/estate)"
    category = "public_notices"
    expected_min_count = 0
    # 11 county postbacks + 4 queries x up to 6 paged loads, all in one session.
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        pages = await _render_queries()
        out: list[Listing] = []
        seen: set[str] = set()
        for html in pages:
            for notice in pa.parse_grid(html):
                nid = notice.get("notice_id") or ""
                if not nid or nid in seen:
                    continue
                seen.add(nid)
                try:
                    listing = _to_listing(notice, self.slug)
                except Exception as exc:   # one malformed row must not kill the run
                    log.warning("nc_notices_counties.row_fail",
                                notice_id=nid, error=str(exc)[:160])
                    continue
                if listing:
                    out.append(listing)
        log.info("nc_notices_counties.done",
                 pages=len(pages), notices=len(seen), leads=len(out))
        return out
