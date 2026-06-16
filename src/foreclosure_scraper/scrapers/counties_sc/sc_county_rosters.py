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
from typing import Iterable

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
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_roster(html: str, roster_url: str, county: str, base: str) -> list[Listing]:
    """Parse one RosterDetails page into foreclosure Listings. County-
    parameterized version of the Greenville MIE parser."""
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
        tms_raw = _clean(cells[9].html or "")
        tms = tms_raw if _TMS_RE.match(tms_raw) else ""
        notes = _clean(cells[12].html or "") if len(cells) > 12 else ""

        m = re.search(r">(\d{4}CP\d{4,8})</a>", case_cell_html)
        case_number = m.group(1) if m else None
        caption_match = re.search(r"</a>\s*<br\s*/?>\s*(.+)", case_cell_html, re.S)
        caption = _clean(caption_match.group(1)) if caption_match else ""

        plaintiff = filing_party.replace("-PLT", "").strip() or None
        def_m = re.search(r"\bvs\.?\s+(.+?)(?:,?\s*defendant|,?\s*et al|$)", caption, re.I)
        defendant = def_m.group(1).strip() if def_m else None

        detail_m = re.search(r'href="([^"]+CaseDetails[^"]+)"', case_cell_html)
        source_url = detail_m.group(1) if detail_m else roster_url
        if source_url.startswith(".."):
            source_url = f"{base}/" + source_url.lstrip("./")
        source_url = source_url.replace("&amp;", "&")

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
