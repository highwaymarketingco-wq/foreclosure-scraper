"""SC Public Index — bulk name-indexed court-records source (7 Upstate counties).

The state-wide SC Judicial Public Index lives at
``https://publicindex.sccourts.org/<County>/PublicIndex/`` with one ASP.NET
WebForms instance per county. SC's portal exposes a legitimate front-end
**empty-name search**: when a *Filing Date range* is supplied, the Last Name /
First Name fields may be left blank and the server returns every case filed in
that window for the chosen court + case type. That is a designed feature of the
public-records front end (a date-bounded docket browse), not a bypass.

This scraper sweeps the 7 Upstate SC core counties (Spartanburg, Anderson,
Pickens, Oconee, Cherokee, Union, Laurens) over a recent filing window for the
**civil (Common Pleas)** and **criminal (General Sessions / Criminal-Clerk)**
case types. Both are name-indexed distress signals: the Common Pleas defendant
is the debtor/owner being sued (judgments, debt collection, foreclosure,
partition); the General Sessions defendant is an individual with an active
criminal matter (a known motivated-seller correlate). Rows carry the party name
but no address — the downstream owner->property resolver / GIS backfill attaches
the parcel.

WHY A STEALTH BROWSER (not pure httpx) -- recon finding 2026-06-30
-----------------------------------------------------------------
The disclaimer landing page itself loads fine over curl_cffi (status 200,
``__VIEWSTATE`` + ``ButtonAccept`` present). But accepting the disclaimer
redirects to ``PISearch.aspx``, which every one of the 7 counties serves behind
an **F5 Distributed Cloud / Shape "Client Challenge"** (the ``/_fs-ch-.../``
script bundle, ``<title>Client Challenge</title>``). That challenge requires
executing obfuscated browser-fingerprinting JS to mint a clearance cookie before
the search form renders — curl_cffi presents a perfect TLS fingerprint but cannot
run the JS, so the pure-postback path is NOT viable. We do not defeat the
challenge: Scrapling's ``StealthyFetcher`` is a *real* stealth browser that runs
the page's own JS exactly as a human's Chrome would (no solver, no token forgery,
no login). This is the same proven mechanism the sibling
``sc_public_index_lis_pendens`` scraper uses; this module differs by doing the
broad empty-name civil+criminal sweep rather than the CP-Foreclosure-420 filter.

DISCOVERED FORM (live-verified Spartanburg, 2026-06-30)
-------------------------------------------------------
* Disclaimer accept: ``ctl00$ContentPlaceHolder1$ButtonAccept`` (POST -> redirect
  to PISearch.aspx).
* Court Type:  ``ContentPlaceHolder1_DropDownListCourtType``
    ``G``=Circuit Court, ``M``=Masters-In-Equity, ``L``=Summary Court, ``' '``=All.
* Case Type:   ``ContentPlaceHolder1_DropDownListCaseTypes``  (trailing spaces real)
    ``'CP  '``=Common Pleas (civil), ``'GS  '``=Criminal-Clerk / General Sessions,
    ``'CR  '``=Criminal, ``'CV  '``=Civil, ``'LP  '``=Lis Pendens.
* Last / First name: ``ContentPlaceHolder1_TextBoxlastName`` /
  ``ContentPlaceHolder1_TextBoxFirstname`` (both left blank for the sweep).
* Date filter type:  ``ContentPlaceHolder1_DropDownListDateFilter`` = ``Filed``.
* Date range:        ``ContentPlaceHolder1_TextBoxDateFrom`` / ``...DateTo`` (mm/dd/YYYY).
* Submit:            ``ContentPlaceHolder1_ButtonSearch``.
* Results grid:      ``table#ContentPlaceHolder1_SearchResults`` (caps at 250 rows),
  columns: Name, Party Type, Case Number, Filed Date, Case Status, Disposition
  Date, Type, Subtype, Judgment #, Court Agency. The plaintiff/defendant pair is
  also on each case cell's ``title="<plaintiff> VS <defendant>"`` attribute.

If StealthyFetcher / its stealth-browser backend is unavailable, or the challenge
isn't cleared, the per-county fetch logs and returns ``[]`` (best-effort).
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...enrichment_lis_pendens_resolver import SC_COUNTY_BY_CODE
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_sc.sc_public_index"

# The 7 Upstate SC core counties (per agency core-county focus).
COUNTIES = (
    "Spartanburg",
    "Anderson",
    "Pickens",
    "Oconee",
    "Cherokee",
    "Union",
    "Laurens",
)

# (court_type_value, case_type_value, court_system_label) tuples we sweep.
# Trailing spaces in the case-type values are REAL (the <option value> emits them)
# and must be preserved or the dropdown won't match.
SEARCHES = (
    ("G", "CP  ", "Common Pleas"),       # civil — debtor/owner defendants
    ("G", "GS  ", "General Sessions"),   # criminal — individual defendants
)

DATE_FILTER_FILED = "Filed"

# How many days back to sweep. 45 default; env-tunable.
LOOKBACK_DAYS = int(os.environ.get("FORECLOSURE_SC_PI_DAYS", "45"))

# Per-county pause to stay polite to the F5 / Shape edge.
_COUNTY_SLEEP_S = float(os.environ.get("FORECLOSURE_SC_PI_COUNTY_SLEEP_S", "2.5"))

# Case-number shapes:
#   Civil Common Pleas:  2026CP4202870  /  2026-CP-42-02870  (CC = county code)
#   Criminal Gen Sess:   2026A4221200064 / 20262581102689 (formats vary by county)
CASE_RE_CP_CLEAN = re.compile(r"\b(\d{4})CP(\d{2})(\d{4,7})\b")
CASE_RE_CP_DASHED = re.compile(r"\b(\d{4})-CP-(\d{2})-(\d{4,7})\b")

# Plaintiff VS Defendant from the case-cell title attribute.
TITLE_VS_RE = re.compile(r"^\s*(.*?)\s+VS\s+(.*?)\s*$", re.IGNORECASE)

# Generic (non-individual) defendant names we should not treat as an owner lead
# — the State is the nominal plaintiff in criminal matters, never the target.
_NON_OWNER_PARTY = re.compile(
    r"\b(state of south carolina|the state|s\.?c\.?\s+dept|department of|"
    r"county of|city of|town of)\b",
    re.IGNORECASE,
)


def _county_url(county: str) -> str:
    return f"https://publicindex.sccourts.org/{county}/PublicIndex/"


def _format_cp_case(raw: str) -> str:
    """Normalize a Common Pleas case to canonical ``2026-CP-42-02870``;
    leave non-CP (criminal) numbers untouched."""
    raw = (raw or "").strip()
    if CASE_RE_CP_DASHED.search(raw):
        return raw
    m = CASE_RE_CP_CLEAN.search(raw)
    if m:
        yr, cc, idx = m.groups()
        return f"{yr}-CP-{cc}-{idx}"
    return raw


def _county_from_cp_case(case_number: str) -> str | None:
    """Decode venue county from a Common Pleas case-number county code."""
    if not case_number:
        return None
    m = CASE_RE_CP_DASHED.search(case_number) or CASE_RE_CP_CLEAN.search(case_number)
    if not m:
        return None
    return SC_COUNTY_BY_CODE.get(m.group(2))


def _build_page_action(court_type: str, case_type: str):
    """Return an async ``page_action(page)`` that passes the disclaimer and
    drives the empty-name + date-range search for one court/case-type."""
    today = datetime.utcnow()
    date_to = today.strftime("%m/%d/%Y")
    date_from = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%m/%d/%Y")

    async def fill_form(page):  # type: ignore[no-untyped-def]
        # Wait for either the disclaimer Accept button or the search form.
        try:
            await page.wait_for_selector(
                "input#ContentPlaceHolder1_ButtonAccept, "
                "select#ContentPlaceHolder1_DropDownListCourtType",
                timeout=25000,
                state="attached",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi_bulk.wait_landing_failed", error=str(exc)[:200])
            return page

        # Accept the public-records-use disclaimer if present.
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
                log.warning("scpi_bulk.accept_failed", error=str(exc)[:200])

        # The search form (PISearch.aspx) — sits behind the F5/Shape challenge,
        # which the stealth browser clears by running the page JS as a real
        # browser. Wait for the CourtType dropdown to confirm we got through.
        try:
            await page.wait_for_selector(
                "#ContentPlaceHolder1_DropDownListCourtType",
                timeout=25000,
                state="attached",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi_bulk.no_search_form", error=str(exc)[:200])
            return page
        await page.wait_for_timeout(2500)

        # Step 1: Court Type postback.
        await page.add_script_tag(
            content=(
                "(function(){"
                "var el=document.getElementById("
                "'ContentPlaceHolder1_DropDownListCourtType');"
                f"el.value={court_type!r};"
                "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCourtType','');"
                "})();"
            )
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1800)

        # Step 2: Case Type postback.
        await page.add_script_tag(
            content=(
                "(function(){"
                "var el=document.getElementById("
                "'ContentPlaceHolder1_DropDownListCaseTypes');"
                "if(!el)return;"
                f"el.value={case_type!r};"
                "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCaseTypes','');"
                "})();"
            )
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1800)

        # Step 3: date filter type + range. Names left blank = empty-space search.
        await page.add_script_tag(
            content=(
                "(function(){"
                "var d=document.getElementById('ContentPlaceHolder1_DropDownListDateFilter');"
                f"if(d)d.value={DATE_FILTER_FILED!r};"
                "var f=document.getElementById('ContentPlaceHolder1_TextBoxDateFrom');"
                "var t=document.getElementById('ContentPlaceHolder1_TextBoxDateTo');"
                f"if(f)f.value={date_from!r};"
                f"if(t)t.value={date_to!r};"
                "var ln=document.getElementById('ContentPlaceHolder1_TextBoxlastName');"
                "var fn=document.getElementById('ContentPlaceHolder1_TextBoxFirstname');"
                "if(ln)ln.value='';if(fn)fn.value='';"
                "})();"
            )
        )
        await page.wait_for_timeout(400)

        # Step 4: submit. The button's inline jQuery validators (checkDateType /
        # checkRequiredFields) are satisfied by the Filed date-range we set.
        try:
            from playwright.async_api import TimeoutError as PWTimeout

            try:
                async with page.expect_navigation(timeout=60000):
                    await page.add_script_tag(
                        content=(
                            "(function(){"
                            "var b=document.getElementById('ContentPlaceHolder1_ButtonSearch');"
                            "if(b)b.click();})();"
                        )
                    )
            except PWTimeout:
                log.warning("scpi_bulk.search_nav_timeout")
        except Exception as exc:  # noqa: BLE001
            log.warning("scpi_bulk.search_nav_err", error=str(exc)[:200])

        await page.wait_for_timeout(3500)
        return page

    return fill_form


def _parse_results(
    html: str, queried_county: str, court_system: str
) -> list[Listing]:
    """Extract rows from the SearchResults grid into name-indexed Listings."""
    out: list[Listing] = []
    if not html:
        return out

    tree = HTMLParser(html)
    grid = tree.css_first("table#ContentPlaceHolder1_SearchResults")
    if not grid:
        return out

    headers = [h.text(strip=True).lower() for h in grid.css("th")]

    def col_idx(*names: str) -> int | None:
        # Prefer an EXACT header match (so "Type" doesn't grab "Party Type"),
        # then fall back to a substring match.
        for n in names:
            for i, h in enumerate(headers):
                if h == n:
                    return i
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    name_i = col_idx("name")
    party_type_i = col_idx("party type")
    case_i = col_idx("case number")
    filed_i = col_idx("filed date")
    status_i = col_idx("case status")
    type_i = col_idx("type")          # the court "Type" column (e.g. Common Pleas)
    subtype_i = col_idx("subtype")

    seen: set[str] = set()

    for row in grid.css("tr.standardRow, tr.altRow"):
        cells = row.css("td")
        if not cells:
            continue

        def cell(i: int | None) -> str:
            return cells[i].text(strip=True) if i is not None and i < len(cells) else ""

        case_raw = ""
        if case_i is not None and case_i < len(cells):
            anchor = cells[case_i].css_first("a")
            case_raw = anchor.text(strip=True) if anchor else cells[case_i].text(strip=True)
        case_raw = case_raw.strip()
        if not case_raw:
            continue
        case_number = _format_cp_case(case_raw)

        # De-dupe within this county/court on the case number (the grid emits
        # one row per party, so the same case repeats — keep the first).
        dk = f"{queried_county}:{case_number}"
        if dk in seen:
            continue
        seen.add(dk)

        # Plaintiff / Defendant from the case-cell title="A VS B".
        plaintiff = None
        defendant = None
        if case_i is not None and case_i < len(cells):
            title_attr = cells[case_i].attributes.get("title") or ""
            tm = TITLE_VS_RE.match(title_attr)
            if tm:
                plaintiff = (tm.group(1).strip() or None)
                defendant_raw = tm.group(2).strip()
                defendant = re.sub(
                    r",\s*(defendant|plaintiff)(\s*,\s*et\s*al\.?)?\s*$",
                    "",
                    defendant_raw,
                    flags=re.IGNORECASE,
                ).strip() or None

        # Fallback to the row's Name + Party Type cell if title was absent.
        row_name = cell(name_i)
        row_party = cell(party_type_i).lower()
        if not plaintiff and not defendant and row_name:
            if "plaintiff" in row_party:
                plaintiff = row_name
            elif "defendant" in row_party:
                defendant = row_name

        # The motivated-seller target is the DEFENDANT (debtor/owner sued in CP;
        # the charged individual in GS). Skip rows whose defendant is a
        # government/non-owner entity (e.g. nominal State plaintiff rows).
        owner_name = defendant
        if owner_name and _NON_OWNER_PARTY.search(owner_name):
            owner_name = None
        if not owner_name:
            # No usable individual defendant — not a name-indexed lead.
            continue

        filed_date = None
        ftxt = cell(filed_i)
        if ftxt:
            try:
                filed_date = datetime.strptime(ftxt, "%m/%d/%Y")
            except ValueError:
                filed_date = None

        status_txt = cell(status_i)
        type_txt = cell(type_i)
        subtype_txt = cell(subtype_i)

        # Authoritative county: for CP the case-number county code wins (SC
        # §15-11-10 ties venue to property situs); criminal stays as queried.
        cp_county = _county_from_cp_case(case_number)
        listing_county = cp_county or queried_county

        # Best-fit listing type. Common Pleas civil filings are the lis-pendens /
        # judgment / partition class of distress; criminal is a generic distress
        # signal with no property-listing semantics -> UNKNOWN.
        if court_system == "Common Pleas":
            listing_type = ListingType.LIS_PENDENS
        else:
            listing_type = ListingType.UNKNOWN

        now = datetime.utcnow()
        out.append(
            Listing(
                source=SLUG,
                source_url=_county_url(listing_county)
                + f"CaseDetails.aspx?CaseNum={case_number}",
                listing_type=listing_type,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=listing_county,
                owner_name=owner_name,
                defendant=defendant,
                plaintiff=plaintiff,
                case_number=case_number,
                # Name-indexed: no address yet. The owner->property resolver /
                # GIS backfill attaches the parcel downstream.
                street_address=None,
                description=(
                    f"SC Public Index {court_system} case {case_number} "
                    f"({listing_county} County) filed "
                    f"{filed_date.strftime('%Y-%m-%d') if filed_date else 'unknown'}"
                    + (f" - {plaintiff} VS {defendant}" if plaintiff and defendant else "")
                )[:500],
                auction_status=status_txt.lower() or None,
                first_seen=filed_date or now,
                last_seen=now,
                raw={
                    "court": {
                        "case_no": case_number,
                        "case_raw": case_raw,
                        "case_type": type_txt or court_system,
                        "subtype": subtype_txt,
                        "filed_date": filed_date.isoformat() if filed_date else None,
                        "parties": {
                            "plaintiff": plaintiff,
                            "defendant": defendant,
                        },
                        "role": "defendant",
                        "court_system": court_system,
                        "status": status_txt,
                        "queried_county": queried_county,
                    }
                },
            )
        )

    return out


async def _scrape_county(county: str) -> list[Listing]:
    """Fetch + parse one county across all configured court/case-type searches."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("scpi_bulk.scrapling_missing", county=county)
        return []

    url = _county_url(county)
    out: list[Listing] = []
    seen_cases: set[str] = set()

    for court_type, case_type, court_system in SEARCHES:
        try:
            result = await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                timeout=180000,
                page_action=_build_page_action(court_type, case_type),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "scpi_bulk.fetch_failed",
                county=county, court_system=court_system, error=str(exc)[:300],
            )
            continue

        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        if not html:
            log.warning("scpi_bulk.empty_body", county=county, court_system=court_system)
            continue

        rows = _parse_results(html, county, court_system)
        # Cross-search de-dupe on case number (a case shouldn't appear in both
        # civil and criminal sweeps, but guard anyway).
        for lst in rows:
            key = (lst.county or county, lst.case_number or lst.source_url)
            ck = f"{key[0]}:{key[1]}"
            if ck in seen_cases:
                continue
            seen_cases.add(ck)
            out.append(lst)

        log.info(
            "scpi_bulk.search_done",
            county=county, court_system=court_system, rows=len(rows),
        )
        # Small pause between the two searches on the same host.
        await asyncio.sleep(1.0)

    log.info("scpi_bulk.county_done", county=county, count=len(out))
    return out


class SCPublicIndexBulk(BaseScraper):
    """SC Public Index bulk court-records sweep (civil + criminal) for the
    7 Upstate SC core counties. Name-indexed motivated-seller leads."""

    slug = SLUG
    name = "SC Public Index — Bulk Court Records (civil + criminal)"
    category = "motivated_seller"
    timeout_s = 900.0
    expected_min_count = 10
    requires_apify = False

    async def fetch(self) -> Iterable[Listing]:
        # Env gate (default ON). Set FORECLOSURE_SC_PUBLIC_INDEX=0 to disable.
        if os.environ.get("FORECLOSURE_SC_PUBLIC_INDEX", "1") == "0":
            log.info("scpi_bulk.disabled_via_env")
            return []

        # Optional single-county slice for fast verification:
        #   FORECLOSURE_SC_PI_ONLY_COUNTY=Spartanburg
        only = os.environ.get("FORECLOSURE_SC_PI_ONLY_COUNTY")
        counties = (
            tuple(c.strip() for c in only.split(",") if c.strip())
            if only
            else COUNTIES
        )

        out: list[Listing] = []
        for county in counties:
            try:
                out.extend(await _scrape_county(county))
            except Exception as exc:  # noqa: BLE001
                log.warning("scpi_bulk.county_error", county=county, error=str(exc)[:300])
                continue
            # Polite pause between counties (per-host F5/Shape edge).
            await asyncio.sleep(_COUNTY_SLEEP_S)
        return out
