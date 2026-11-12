"""Unified SC Master-in-Equity sale rosters via publicindex.sccourts.org.

Discovered 2026-06-16: the SC Judicial Branch hosts every county's
court-roster app at `publicindex.sccourts.org/<county>/courtrosters/`,
the same ASP.NET application Greenville runs on its own domain. The
publicindex host is bot-protected (plain httpx gets HTTP 406), so we
drive it with the local Scrapling stealth browser:

  Disclaimer.aspx → click Accept → RosterSelection.aspx → RosterDetails

This single scraper covers the upstate counties that had NO foreclosure
sale source before: Oconee, Cherokee, Laurens, Union, Greenwood,
Abbeville, Newberry. (Greenville, Spartanburg, Anderson, Pickens keep
their own dedicated scrapers; Pickens is legitimately empty when the
county has no active sales.)

RosterCode=MO is the Master-in-Equity sale roster. Sub Type
"Foreclosure 420" rows are the foreclosure sales.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from html import unescape as html_unescape
from typing import Iterable
from urllib.parse import urljoin

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

# county-url-slug -> display name.
# Only in-scope upstate counties. Greenwood/Abbeville/Newberry are in the
# SCOPE_DENY_COUNTIES list (pruned per owner direction), so they're omitted
# here — no point spinning a stealth browser for data that gets filtered out.
COUNTIES: dict[str, str] = {
    "oconee": "Oconee",
    "cherokee": "Cherokee",
    "laurens": "Laurens",
    "union": "Union",
}

HOST = "https://publicindex.sccourts.org"
ACCEPT_BTN = "ctl00$ContentPlaceHolder1$ButtonAccept"
# Most-recent N rosters per county (one per month) to bound run time.
MAX_ROSTERS_PER_COUNTY = 3

_TMS_RE = re.compile(r"^\d[\d.\-\s]{4,}$")
_ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|"
    r"Parkway|Pkwy|Terrace|Ter|Run|Path|Point|Pt|Loop|Crossing|Xing)"
    r"(?:\s*,\s*[A-Z][a-z]+)?)\b",
    re.I,
)


def _clean(s: str) -> str:
    """Strip tags and collapse whitespace. Audited 2026-10-01: this used to skip
    ``html.unescape``, so every owner/plaintiff/description string carried literal
    entities straight off the ASP.NET grid -- "U.S. Bank &amp; Trust Company"
    instead of "U.S. Bank & Trust Company", "&nbsp;" instead of a space. That is
    not cosmetic: it breaks name matching against any other source (voter file,
    county GIS owner, resolver) that normalizes real ampersands, and it ships an
    HTML entity straight onto a lead's description. Unescape BEFORE stripping
    tags so an entity that happens to look like a tag delimiter (none observed,
    but cheap to be safe about) cannot be misread."""
    s = html_unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_roster(html: str, roster_url: str, county: str, base: str) -> list[Listing]:
    """Parse one RosterDetails page into foreclosure Listings. County-
    parameterized version of the Greenville MIE parser.

    AUDITED 2026-10-01. Two layout bugs fixed, both because the original code
    assumed every county's MO roster has the SAME number of columns:

    * Oconee/Cherokee/Union render a 13-column row (seq, date, time, ?,
      description, filing party, date, case, subtype, TMS/Map#, plaintiff
      attorney, defendant attorney, notes). Laurens renders only 12 -- it has
      NO separate TMS column, so the attorney blocks shift one column left and
      land at the old hard-coded notes index (12), which is simply absent
      (``len(cells) > 12`` is False), so every Laurens row's notes -- the ONLY
      place this roster ever carries a street address or dollar amount --
      were silently dropped. Verified live: a Laurens foreclosure row's real
      notes cell ("Continued per email from Mr. Brown") sits at index 11, one
      column left of where Oconee's sits. Fixed by locating the notes cell by
      its CSS class (``td.notesTD``, present and in the same position
      relative to the END of the row on every county checked) instead of a
      fixed index, so it survives a column-count difference instead of
      silently returning "".
    * The TMS/parcel cell was read from a hard-coded index (9) with a regex
      guard that rejects non-numeric text (so Laurens' attorney names in that
      slot were already correctly discarded, not mis-filed as a parcel id --
      that part was fine). Changed to scan the candidate cells for the first
      one matching the TMS shape instead of trusting one fixed index, so a
      future county with yet another column count is read the same way
      rather than by coincidence of where index 9 happens to land.

    ``_clean()`` itself was also fixed (see its docstring) to unescape HTML
    entities, which used to ship literal ``&amp;``/``&nbsp;`` into every
    owner/plaintiff/description string.
    """
    out: list[Listing] = []
    tree = HTMLParser(html)
    for tr in tree.css("tr.standardRow, tr.altRow"):
        cells = tr.css("td")
        if len(cells) < 10:
            continue
        if not _clean(cells[8].html or "").lower().startswith("foreclosure"):
            continue

        scheduled_raw = _clean(cells[1].html or "")
        start_time = _clean(cells[2].html or "")
        description = _clean(cells[4].html or "")
        filing_party = _clean(cells[5].html or "")
        case_cell_html = cells[7].html or ""

        # TMS/Map#: scan rather than trust a fixed index, so a county whose
        # roster has a different column count (Laurens has no TMS column at
        # all) is read correctly instead of by coincidence. Stop before the
        # notes cell so a numeric-looking note never gets mistaken for a TMS.
        notes_node = tr.css_first("td.notesTD")
        notes_idx = cells.index(notes_node) if notes_node in cells else len(cells) - 1
        tms = ""
        for c in cells[9:notes_idx]:
            cand = _clean(c.html or "")
            if _TMS_RE.match(cand):
                tms = cand
                break

        notes = _clean((notes_node or cells[-1]).html or "") if cells else ""

        m = re.search(r">(\d{4}CP\d{4,8})</a>", case_cell_html)
        case_number = m.group(1) if m else None
        caption_match = re.search(r"</a>\s*<br\s*/?>\s*(.+)", case_cell_html, re.S)
        caption = _clean(caption_match.group(1)) if caption_match else ""

        plaintiff = filing_party.replace("-PLT", "").strip() or None
        def_m = re.search(r"\bvs\.?\s+(.+?)(?:,?\s*defendant|,?\s*et al|$)", caption, re.I)
        defendant = def_m.group(1).strip() if def_m else None

        # Resolved against the actual page URL with a real urljoin, not a
        # hand-rolled lstrip. AUDITED 2026-10-01: the live grid's link is
        # "../PublicIndex/CaseDetails.aspx?..." (one directory UP from
        # .../courtrosters/), and the old `f"{base}/" + href.lstrip("./")`
        # dropped the "up one level" and glued it back onto .../courtrosters/,
        # producing a URL that 404s. (This CaseDetails.aspx page itself sits
        # behind the SAME F5/Shape WAF challenge that
        # sc_public_index_lis_pendens.py was disabled over on 2026-10-01 --
        # confirmed live, the page renders blank with no stealth browser
        # driving it -- so it is recorded here only as a correct reference
        # link for a human operator; this scraper does not and must not fetch
        # it automatically.)
        detail_m = re.search(r'href="([^"]+CaseDetails[^"]+)"', case_cell_html)
        if detail_m:
            source_url = urljoin(roster_url, html_unescape(detail_m.group(1)))
        else:
            source_url = roster_url

        auction_status = "completed" if "Completed-" in notes else "active"

        sale_date = None
        try:
            if scheduled_raw:
                sale_date = dateparser.parse(scheduled_raw)
        except (ValueError, TypeError):
            pass

        opening_bid = None
        for amt_m in re.finditer(r"\$([\d,]+\.\d{2})", notes):
            try:
                opening_bid = float(amt_m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

        street_address = None
        addr_m = _ADDR_RE.search(notes)
        if addr_m:
            street_address = addr_m.group(1).strip().rstrip(",")

        out.append(
            Listing(
                source="counties_sc.sc_county_rosters",
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=county,
                street_address=street_address,
                parcel_id=tms.strip().replace("  ", " ") or None,
                sale_date=sale_date,
                sale_time=start_time or None,
                opening_bid=opening_bid,
                plaintiff=plaintiff[:200] if plaintiff else None,
                defendant=defendant[:200] if defendant else None,
                case_number=case_number,
                auction_status=auction_status,
                description=(notes or description)[:500] or None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_county_roster": {"county": county, "roster_url": roster_url}},
            )
        )
    return out


async def _fetch_county(county_slug: str) -> list[str]:
    """Drive the disclaimer→selection→details flow with one stealth browser
    session. Returns the HTML of each recent MO roster page."""
    from scrapling.fetchers import StealthyFetcher

    base = f"{HOST}/{county_slug}/courtrosters"
    roster_html: list[str] = []

    async def action(page):
        await page.goto(f"{base}/Disclaimer.aspx", wait_until="domcontentloaded")
        try:
            await page.click(f'input[name="{ACCEPT_BTN}"]', timeout=8000)
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.goto(f"{base}/RosterSelection.aspx", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=12000)
        selection = await page.content()
        mo = sorted(set(re.findall(r"RosterDetails\.aspx\?[^\"']+RosterCode=MO\s*", selection)))
        mo = [m.replace("&amp;", "&").strip() for m in mo][-MAX_ROSTERS_PER_COUNTY:]
        for path in mo:
            await page.goto(f"{base}/{path}", wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=12000)
            roster_html.append(await page.content())
        return page

    try:
        await StealthyFetcher.async_fetch(
            f"{base}/Disclaimer.aspx", headless=True, timeout=120000, page_action=action
        )
    except Exception:
        return []
    return roster_html


class SCCountyRosters(BaseScraper):
    slug = "counties_sc.sc_county_rosters"
    name = "SC County MIE Rosters (publicindex)"
    category = "county_court"
    expected_min_count = 0  # many small counties have 0 active sales at a time
    requires_render = True
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # The same case can appear in consecutive monthly rosters; dedupe
        # within this scraper by (county, case#) so we don't emit it twice.
        seen: set[tuple] = set()
        # Sequential: each county spins a heavy stealth browser session.
        for slug, county in COUNTIES.items():
            base = f"{HOST}/{slug}/courtrosters"
            try:
                pages = await _fetch_county(slug)
            except Exception:
                continue
            for html in pages:
                for li in parse_roster(html, f"{base}/RosterSelection.aspx", county, base):
                    key = (li.county, li.case_number)
                    if li.case_number and key in seen:
                        continue
                    seen.add(key)
                    out.append(li)
        return out
