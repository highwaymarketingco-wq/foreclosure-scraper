"""SC Public Index — Common Pleas (CP) Foreclosure case search per county.

The state-wide SC Judicial Public Index lives at
``https://publicindex.sccourts.org/<County>/PublicIndex/`` with one ASP.NET
WebForms instance per county. The flow is:

1. GET landing page (disclaimer) — collects ``__VIEWSTATE``, F5/Shape JS-cookies.
2. POST disclaimer accept with hidden form fields → redirects to ``PISearch.aspx``.
3. ``PISearch.aspx`` is gated behind an F5 / Shape "Client Challenge" JS bot
   detector — direct httpx hits an unsolved challenge page. We therefore drive
   it with Scrapling's ``StealthyFetcher`` (camoufox / Playwright stealth) and
   exercise the form via injected ``<script>`` tags so calls land in the page's
   main world (Playwright's ``page.evaluate`` runs in an isolated world where
   ``__doPostBack`` is invisible).
4. Cascading dropdowns force three sequential postbacks:
     - ``DropDownListCourtType`` = ``"G"``         (Circuit Court)
     - ``DropDownListCaseTypes`` = ``"CP  "``      (Common Pleas)
     - ``DropdownlistCaseSubType`` = ``"420   "``  (Foreclosure 420)
   Then we set ``DropDownListDateFilter = "Filed"`` plus a 60-day date range
   on ``TextBoxDateFrom`` / ``TextBoxDateTo`` (the inline ``checkDateType()``
   jQuery validator rejects dates without a corresponding date-type).
5. Click ``ButtonSearch`` → server returns ``SearchResults`` table with up to
   250 rows: party name + type, case number, filed date, status, type, subtype,
   judgment#, court agency. The plaintiff/defendant pair lives in the row's
   ``title="<plaintiff> VS <defendant>"`` attribute.

If StealthyFetcher / camoufox is unavailable or the challenge fails, the
scraper logs the failure and returns ``[]`` for that county (best-effort).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...enrichment_lis_pendens_resolver import SC_COUNTY_BY_CODE
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

COUNTIES = (
    "Spartanburg",
    "Anderson",
    "Pickens",
    "Oconee",
    "Cherokee",
    "Union",
    "Laurens",
)


def _county_from_case(case_number: str) -> str | None:
    """Decode the case-venue county from the SC Common Pleas case-number
    prefix (YYYY-CP-CC-NNNNN). SC Code §15-11-10 ties venue to the
    property's county, so this is authoritative."""
    if not case_number:
        return None
    m = CASE_RE_DASHED.match(case_number)
    if not m:
        return None
    return SC_COUNTY_BY_CODE.get(m.group(2))

# Search filter knobs (encoded in the dropdown option values exactly as the
# page emits them — note the trailing spaces are real and must be preserved).
COURT_TYPE_CIRCUIT = "G"
CASE_TYPE_CP = "CP  "
CASE_SUBTYPE_FORECLOSURE = "420   "
DATE_FILTER_FILED = "Filed"
LOOKBACK_DAYS = 60

# Case# patterns we accept:
#  * "2026CP4201547"  - cleaned form returned in the result anchor
#  * "2026-CP-42-01547" - canonical case number with dashes
CASE_RE_CLEAN = re.compile(r"\b(\d{4})CP(\d{2})(\d{4,6})\b")
CASE_RE_DASHED = re.compile(r"\b(\d{4})-CP-(\d{2})-(\d{4,6})\b")

# Title attribute we extract plaintiff/defendant from:
#   title="  Plaintiff Name VS Defendant Name [, defendant, et al]"
TITLE_VS_RE = re.compile(r"^\s*(.*?)\s+VS\s+(.*?)\s*$", re.IGNORECASE)


def _format_case_number(raw: str) -> str:
    """Normalize ``2026CP4201547`` to ``2026-CP-42-01547`` (canonical SC form)."""
    raw = raw.strip()
    m = CASE_RE_DASHED.search(raw)
    if m:
        return raw
    m = CASE_RE_CLEAN.search(raw)
    if m:
        yr, cnt, idx = m.groups()
        return f"{yr}-CP-{cnt}-{idx}"
    return raw


def _county_url(county: str) -> str:
    return f"https://publicindex.sccourts.org/{county}/PublicIndex/"


def _build_page_action(county: str):
    """Return an async ``page_action(page)`` that drives the search form."""

    today = datetime.utcnow()
    date_to = today.strftime("%m/%d/%Y")
    date_from = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%m/%d/%Y")

    async def fill_form(page):  # type: ignore[no-untyped-def]
        # First we need to get past the disclaimer. The default landing
        # serves the disclaimer page; when we navigate directly to PISearch
        # without accepting we get bounced back. Easiest path: hit the
        # county landing first, click Accept, then the form is at
        # /PublicIndex/PISearch.aspx in the same context.
        try:
            await page.wait_for_selector(
                "input#ContentPlaceHolder1_ButtonAccept, "
                "select#ContentPlaceHolder1_DropDownListCourtType",
                timeout=20000,
                state="attached",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi.wait_landing_failed", county=county, error=str(exc))
            return page

        # If the disclaimer Accept button is present, click it.
        accept_present = await page.evaluate(
            "() => !!document.getElementById('ContentPlaceHolder1_ButtonAccept')"
        )
        if accept_present:
            try:
                from playwright.async_api import TimeoutError as PWTimeout

                try:
                    async with page.expect_navigation(timeout=30000):
                        await page.add_script_tag(
                            content=(
                                "(function(){var b=document.getElementById("
                                "'ContentPlaceHolder1_ButtonAccept');"
                                "if(b)b.click();})();"
                            )
                        )
                except PWTimeout:
                    pass
            except Exception as exc:  # noqa: BLE001
                log.warning("scpi.accept_failed", county=county, error=str(exc))
                return page

        # Now we should be on PISearch.aspx. Wait for the form.
        try:
            await page.wait_for_selector(
                "#ContentPlaceHolder1_DropDownListCourtType",
                timeout=20000,
                state="attached",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi.no_search_form", county=county, error=str(exc))
            return page
        await page.wait_for_timeout(2500)

        # Step 1: CourtType=G (Circuit Court). Postback fires via inline onchange.
        await page.add_script_tag(
            content=(
                "(function(){"
                "var el=document.getElementById("
                "'ContentPlaceHolder1_DropDownListCourtType');"
                f"el.value={COURT_TYPE_CIRCUIT!r};"
                "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCourtType','');"
                "})();"
            )
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1800)

        # Step 2: CaseTypes=CP (Common Pleas).
        await page.add_script_tag(
            content=(
                "(function(){"
                "var el=document.getElementById("
                "'ContentPlaceHolder1_DropDownListCaseTypes');"
                f"el.value={CASE_TYPE_CP!r};"
                "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCaseTypes','');"
                "})();"
            )
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1800)

        # Step 3: SubType=Foreclosure 420 (server-side filter; if dropdown
        # missing or value rejected, we still filter post-hoc on Subtype text).
        await page.add_script_tag(
            content=(
                "(function(){"
                "var el=document.getElementById("
                "'ContentPlaceHolder1_DropdownlistCaseSubType');"
                "if(!el)return;"
                f"el.value={CASE_SUBTYPE_FORECLOSURE!r};"
                "if(el.selectedIndex>=0){"
                "  __doPostBack("
                "    'ctl00$ContentPlaceHolder1$DropdownlistCaseSubType',''"
                "  );"
                "}"
                "})();"
            )
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        # Step 4: Date filter + range.
        await page.add_script_tag(
            content=(
                "(function(){"
                "var d=document.getElementById('ContentPlaceHolder1_DropDownListDateFilter');"
                f"if(d)d.value={DATE_FILTER_FILED!r};"
                "var f=document.getElementById('ContentPlaceHolder1_TextBoxDateFrom');"
                "var t=document.getElementById('ContentPlaceHolder1_TextBoxDateTo');"
                f"if(f)f.value={date_from!r};"
                f"if(t)t.value={date_to!r};"
                "})();"
            )
        )
        await page.wait_for_timeout(300)

        # Step 5: submit. The button has a jQuery click handler doing
        # checkTaxMap / checkDateType / checkRequiredFields; the date-range
        # we just set satisfies all three. We expect a same-URL postback,
        # so listen for navigation.
        from playwright.async_api import TimeoutError as PWTimeout

        try:
            async with page.expect_navigation(timeout=60000):
                await page.add_script_tag(
                    content=(
                        "(function(){"
                        "var b=document.getElementById('ContentPlaceHolder1_ButtonSearch');"
                        "if(b)b.click();"
                        "})();"
                    )
                )
        except PWTimeout:
            log.warning("scpi.search_nav_timeout", county=county)
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi.search_nav_err", county=county, error=str(exc))

        await page.wait_for_timeout(3500)
        return page

    return fill_form


def _parse_results(html: str, county: str) -> list[Listing]:
    """Extract Common Pleas Foreclosure rows from the SearchResults table."""
    out: list[Listing] = []
    if not html:
        return out

    tree = HTMLParser(html)
    grid = tree.css_first("table#ContentPlaceHolder1_SearchResults")
    if not grid:
        return out

    headers = [h.text(strip=True).lower() for h in grid.css("th")]

    def col_idx(*names: str) -> int | None:
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    case_i = col_idx("case number")
    filed_i = col_idx("filed date")
    status_i = col_idx("case status")
    subtype_i = col_idx("subtype")
    party_type_i = col_idx("party type")
    name_i = col_idx("name")

    # Pre-pass: collect EVERY defendant-party row per case. The grid emits one
    # row per party and the main loop keeps only the FIRST — dropping the
    # co-defendants (co-owners / heirs that are themselves resolvable owner
    # leads). Build case_number -> ordered unique list of defendant names.
    defendants_by_case: dict[str, list[str]] = {}
    for prow in grid.css("tr.standardRow, tr.altRow"):
        pcells = prow.css("td")
        if not pcells or case_i is None or case_i >= len(pcells):
            continue
        p_anchor = pcells[case_i].css_first("a")
        p_craw = p_anchor.text(strip=True) if p_anchor else pcells[case_i].text(strip=True)
        p_case = _format_case_number(p_craw)
        if not p_case:
            continue
        p_party = (
            pcells[party_type_i].text(strip=True).lower()
            if party_type_i is not None and party_type_i < len(pcells) else ""
        )
        p_name = (
            pcells[name_i].text(strip=True)
            if name_i is not None and name_i < len(pcells) else ""
        )
        if "defendant" in p_party and p_name:
            lst = defendants_by_case.setdefault(p_case, [])
            if p_name not in lst:
                lst.append(p_name)

    seen: set[str] = set()

    for row in grid.css("tr.standardRow, tr.altRow"):
        cells = row.css("td")
        if not cells:
            continue

        # Subtype filter: only keep Foreclosure (subtype 420). Some cases
        # surface as Common Pleas without subtype filter applied — drop those.
        subtype = cells[subtype_i].text(strip=True) if subtype_i is not None and subtype_i < len(cells) else ""
        if "foreclosure" not in subtype.lower():
            continue

        # Pull the case number from the anchor (text) inside the case cell.
        case_raw = ""
        if case_i is not None and case_i < len(cells):
            anchor = cells[case_i].css_first("a")
            case_raw = anchor.text(strip=True) if anchor else cells[case_i].text(strip=True)
        case_number = _format_case_number(case_raw)
        if not case_number:
            continue

        # Plaintiff / Defendant come from the <td title="..."> on the case cell:
        #   title="  Plaintiff Name VS Defendant Name [, defendant, et al]"
        plaintiff = None
        defendant = None
        if case_i is not None and case_i < len(cells):
            title_attr = cells[case_i].attributes.get("title") or ""
            tm = TITLE_VS_RE.match(title_attr)
            if tm:
                plaintiff = tm.group(1).strip() or None
                defendant_raw = tm.group(2).strip()
                # Strip trailing ", defendant, et al" and similar role tags
                defendant = re.sub(
                    r",\s*(defendant|plaintiff)(\s*,\s*et\s*al\.?)?\s*$",
                    "",
                    defendant_raw,
                    flags=re.IGNORECASE,
                ).strip() or None

        # Fallback: use Name + Party Type cell when title is missing.
        if not plaintiff and not defendant and name_i is not None and party_type_i is not None:
            party_name = cells[name_i].text(strip=True) if name_i < len(cells) else ""
            party_type = cells[party_type_i].text(strip=True).lower() if party_type_i < len(cells) else ""
            if party_name:
                if "plaintiff" in party_type:
                    plaintiff = party_name
                elif "defendant" in party_type:
                    defendant = party_name

        # De-dupe within county on case number (table emits one row per party
        # so the same case can appear multiple times — keep the first only).
        dedupe_key = f"{county}:{case_number}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        filed_date = None
        if filed_i is not None and filed_i < len(cells):
            txt = cells[filed_i].text(strip=True)
            if txt:
                try:
                    filed_date = datetime.strptime(txt, "%m/%d/%Y")
                except ValueError:
                    filed_date = None

        status_txt = (
            cells[status_i].text(strip=True)
            if status_i is not None and status_i < len(cells)
            else ""
        )

        # Authoritative county is what the case-number encodes (SC §15-11-10
        # ties venue to property situs). Belt-and-suspenders: log if the
        # county we queried disagrees with the case#-decoded one.
        case_county = _county_from_case(case_number)
        listing_county = case_county or county
        if case_county and case_county != county:
            log.warning(
                "scpi.county_mismatch",
                queried=county, case_county=case_county,
                case=case_number,
            )

        out.append(
            Listing(
                source="counties_sc.sc_public_index_lis_pendens",
                source_url=_county_url(listing_county) + f"CaseDetails.aspx?CaseNum={case_number}",
                listing_type=ListingType.LIS_PENDENS,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=listing_county,
                case_number=case_number,
                plaintiff=plaintiff,
                defendant=defendant,
                sale_date=None,
                description=(
                    f"SC Public Index Common Pleas foreclosure case "
                    f"{case_number} ({listing_county} County) "
                    f"filed {filed_date.strftime('%Y-%m-%d') if filed_date else 'unknown'}"
                    + (f" - {plaintiff} VS {defendant}" if plaintiff and defendant else "")
                )[:500],
                auction_status=status_txt.lower() or None,
                first_seen=filed_date or datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_public_index": {
                    "filed_date": filed_date.isoformat() if filed_date else None,
                    "status": status_txt,
                    "subtype": subtype,
                    "case_raw": case_raw,
                    # Every defendant-party row for this case (co-owners / heirs)
                    # — each is a resolvable owner lead downstream.
                    "co_defendants": (defendants_by_case.get(case_number) or None),
                }},
            )
        )

    return out


async def _scrape_county(county: str) -> list[Listing]:
    """Fetch + parse one county. Returns [] on any failure (best-effort)."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("scpi.scrapling_missing", county=county)
        return []

    url = _county_url(county)
    try:
        result = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=180000,
            page_action=_build_page_action(county),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("scpi.fetch_failed", county=county, error=str(exc)[:300])
        return []

    body = getattr(result, "body", b"")
    if isinstance(body, bytes):
        html = body.decode("utf-8", errors="replace")
    else:
        html = str(body or "")

    if not html:
        log.warning("scpi.empty_body", county=county)
        return []

    listings = _parse_results(html, county)
    log.info("scpi.county_done", county=county, count=len(listings))
    return listings


class SCPublicIndexLisPendens(BaseScraper):
    """SC state Public Index lis pendens / Common Pleas foreclosure case search."""

    slug = "counties_sc.sc_public_index_lis_pendens"
    name = "SC Public Index — CP Foreclosure (lis pendens)"
    category = "county_court"
    timeout_s = 360.0
    expected_min_count = 5
    requires_apify = False

    async def fetch(self) -> Iterable[Listing]:
        # Sequential per-county to avoid hammering the F5 challenge in parallel.
        out: list[Listing] = []
        for county in COUNTIES:
            try:
                listings = await _scrape_county(county)
                out.extend(listings)
            except Exception as exc:  # noqa: BLE001
                log.warning("scpi.county_error", county=county, error=str(exc)[:300])
                continue
            # Brief pause between counties to be nice to the F5 / Shape edge.
            await asyncio.sleep(2.0)
        return out
