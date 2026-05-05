"""SC Public Index courtrosters scraper — Master in Equity sale rosters.

The SC Judicial Public Index publishes per-county Master in Equity sale
rosters at:

  https://publicindex.sccourts.org/<County>/courtrosters/

Each roster lists upcoming MIE foreclosure sales (date, time, location,
case#, plaintiff/defendant, property reference). Monthly cadence — first
Monday of the month is the standard sale day, posted ~3 weeks prior.

This scraper iterates the 9 counties with active Master in Equity courts
that publish rosters (not all 46 SC counties have an MIE; the ones
without route foreclosures through Common Pleas in their stead).

Per the source-coverage research (May 2026), these are the verified
roster URLs. Counties without an active MIE roster fall back to
the existing SC Public Index lis pendens scraper.

The roster pages sit behind the same F5 / Shape Client Challenge as
the lis-pendens portal, so we use Scrapling stealth (already in deps).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Counties with active SC Master-in-Equity rosters per the source-coverage
# research output. Each URL is the public courtrosters index for that
# county on the SC Judicial Public Index.
COUNTY_ROSTER_URLS = {
    "Greenville": "https://publicindex.sccourts.org/Greenville/courtrosters/",
    "Charleston": "https://publicindex.sccourts.org/Charleston/courtrosters/",
    "Richland":   "https://publicindex.sccourts.org/Richland/courtrosters/",
    "Lexington":  "https://publicindex.sccourts.org/Lexington/courtrosters/",
    "Horry":      "https://publicindex.sccourts.org/Horry/courtrosters/",
    "York":       "https://publicindex.sccourts.org/York/courtrosters/",
    "Berkeley":   "https://publicindex.sccourts.org/Berkeley/courtrosters/",
    "Beaufort":   "https://publicindex.sccourts.org/Beaufort/courtrosters/",
    "Aiken":      "https://publicindex.sccourts.org/Aiken/courtrosters/",
    # The 7 that already have a CP foreclosure scraper (Spartanburg /
    # Anderson / Pickens / Oconee / Cherokee / Union / Laurens) also
    # publish rosters; including them here is redundant since the
    # lis-pendens scraper already covers their volume.
}


# Case# pattern: SC court rosters use the canonical YYYY-CP-CC-NNNNN.
CASE_RE = re.compile(r"\b(\d{4}-CP-\d{2}-\d{4,6})\b")
SALE_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
ADDR_RE = re.compile(
    r"\b(\d{1,5}\s+[A-Z][A-Za-z .'\-]{3,40}?\s+"
    r"(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|"
    r"Parkway|Pkwy|Terrace|Terr)\.?(?:\s*,\s*[A-Z][a-zA-Z .'\-]+)?"
    # \d{0,5} — zip is optional; the previous \d{5}? was a lazy
    # quantifier on EXACTLY 5 digits (the ? doesn't make it optional),
    # which made the whole pattern fail on addresses without a zip.
    r"(?:\s*,?\s*SC)?\s*\d{0,5})",
    re.I,
)


async def _fetch_roster(county: str, url: str) -> str:
    """Render the courtroster index page via Scrapling stealth — the F5
    challenge requires a real browser context."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("sc_courtrosters.scrapling_missing", county=county)
        return ""

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "table, .roster, body", timeout=15000, state="attached",
            )
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        result = await asyncio.wait_for(
            StealthyFetcher.async_fetch(
                url, headless=True, network_idle=True, timeout=60000,
                page_action=page_action,
            ),
            timeout=90.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("sc_courtrosters.fetch_failed", county=county,
                    error=str(exc)[:200])
        return ""

    body = getattr(result, "body", b"")
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")


def _parse_roster(html: str, county: str, url: str) -> list[Listing]:
    """Best-effort parse of a courtrosters page. The exact HTML structure
    varies per county (each MIE clerk publishes their own format), so we
    use text-pattern matching on the rendered page rather than per-county
    selectors."""
    if not html or len(html) < 500:
        return []

    tree = HTMLParser(html)
    text = tree.body.text(separator="\n") if tree.body else ""

    out: list[Listing] = []
    seen: set[str] = set()

    # Strategy: split into per-case blocks anchored on case number, then
    # extract date / address / parties from each block.
    cases = list(CASE_RE.finditer(text))
    for i, m in enumerate(cases):
        case_no = m.group(1)
        if case_no in seen:
            continue
        seen.add(case_no)
        # Block = text from this case# to the next (or end)
        block_start = m.start()
        block_end = cases[i + 1].start() if i + 1 < len(cases) else min(
            len(text), block_start + 1500
        )
        block = text[block_start:block_end]

        # Sale date
        sale_date = None
        dm = SALE_DATE_RE.search(block)
        if dm:
            try:
                sale_date = datetime.strptime(dm.group(1), "%m/%d/%Y")
            except ValueError:
                sale_date = None

        # Property address
        addr_match = ADDR_RE.search(block)
        street = addr_match.group(1).strip() if addr_match else None

        # Plaintiff vs defendant — common roster format is
        # "Plaintiff Bank vs Defendant Smith"
        vs_m = re.search(r"\b([\w\s.&,'-]{3,80}?)\s+(?:vs\.?|v\.)\s+([\w\s.&,'-]{3,80}?)\b",
                         block, re.I)
        plaintiff = vs_m.group(1).strip() if vs_m else None
        defendant = vs_m.group(2).strip() if vs_m else None

        out.append(Listing(
            source="counties_sc.sc_courtrosters",
            source_url=url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county=county,
            case_number=case_no,
            plaintiff=plaintiff,
            defendant=defendant,
            sale_date=sale_date,
            street_address=street,
            description=(
                f"SC Master in Equity sale roster — {county} County · "
                f"case {case_no}"
                + (f" sale {sale_date.strftime('%Y-%m-%d')}" if sale_date else "")
            )[:500],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"sc_courtrosters": {
                "county": county,
                "block_excerpt": re.sub(r"\s+", " ", block)[:400],
            }},
        ))

    return out


class SCCourtRosters(BaseScraper):
    """SC Master-in-Equity sale rosters across the 9 counties not covered
    by the existing CP foreclosure scraper."""

    slug = "counties_sc.sc_courtrosters"
    name = "SC Master in Equity sale rosters (9 counties)"
    category = "county_court"
    expected_min_count = 0  # Monthly cadence; many runs will land between rosters
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # Sequential — each county takes ~30s with Scrapling, and the F5
        # edge dislikes parallel requests from one IP.
        for county, url in COUNTY_ROSTER_URLS.items():
            try:
                html = await _fetch_roster(county, url)
                if html:
                    listings = _parse_roster(html, county, url)
                    out.extend(listings)
                    log.info("sc_courtrosters.county_done",
                             county=county, count=len(listings))
                else:
                    log.info("sc_courtrosters.county_empty", county=county)
            except Exception as exc:
                log.warning("sc_courtrosters.county_failed",
                            county=county, error=str(exc)[:200])
            await asyncio.sleep(2.0)
        log.info("sc_courtrosters.done", total=len(out),
                 counties=len(COUNTY_ROSTER_URLS))
        return out
