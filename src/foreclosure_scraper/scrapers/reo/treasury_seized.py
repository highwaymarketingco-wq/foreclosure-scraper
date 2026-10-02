"""Treasury seized real-property auctions — federal REO source.

US Treasury seizes real property in tax/criminal forfeiture cases and
publishes upcoming auctions at:

  https://www.treasury.gov/auctions/treasury/rp/realprop.shtml

Volume is small (~20 properties nationwide at any time) but they're
zero-competition — the public doesn't know to look here.

Free, no auth, plain HTML. Refresh cadence is irregular (case-driven).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


URL = "https://www.treasury.gov/auctions/treasury/rp/realprop.shtml"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# Full state name -> 2-letter code. Treasury spells states out in full
# ("Merry Hill, North Carolina 27957"), so we normalize before the
# NC/SC footprint check. Only the states we might encounter need entries;
# anything unmapped falls through and is skipped by the footprint filter.
STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "puerto rico": "PR", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

# Address with state suffix — Treasury format is "City, State ZIP" where
# State is either a 2-letter code OR a full spelled-out name. The state
# group matches a full name (greedy multi-word) or a bare 2-letter code;
# _normalize_state() collapses it to a code before the footprint check.
ADDR_RE = re.compile(
    r"\b(\d{1,5}\s+[A-Z][\w .'\-]+?)\s*,?\s*"
    r"([A-Z][\w .'\-]+?),\s*"
    r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*|[A-Z]{2}),?\s*(\d{5})\b",
)


def _normalize_state(raw: str) -> str | None:
    """Return a 2-letter state code for ``raw`` (code or full name), else None."""
    if not raw:
        return None
    s = raw.strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return STATE_NAME_TO_CODE.get(s.lower())
DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
)
# Found 2026-10-01 (national/reo per-source audit): the live page's real
# auction-date label ("ONLINE AUCTION DATE: Thursday, November 19, 2026")
# is a written-month date, which DATE_RE above (numeric-only, e.g.
# "11/19/2026") never matches -- confirmed live, sale_date came back None
# on every current listing despite the real date sitting a few lines below
# the address, well within the 400-char forward-scan window.
WRITTEN_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b",
    re.I,
)
PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# "Sale # 27-66-109" -- the Treasury's own per-auction case identifier,
# printed on every listing, never captured.
SALE_NUM_RE = re.compile(r"Sale\s*#\s*([\w-]+)", re.I)
# "2,835 ± sq. ft. home with 4 bedrooms, 2.1 baths" -- beds/baths/sqft are
# free text in the description but were never parsed into structured fields.
SQFT_RE = re.compile(r"([\d,]+)\s*±?\s*sq\.?\s*ft", re.I)
BEDS_RE = re.compile(r"(\d+)\s*bed(?:room)?s?\b", re.I)
BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*baths?\b", re.I)


class TreasurySeizedRealProperty(BaseScraper):
    slug = "reo.treasury_seized"
    name = "US Treasury Seized Real Property"
    category = "federal_reo"
    expected_min_count = 0   # Sometimes 0; max ~20 nationwide
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=30.0) as c:
            try:
                r = await c.get(URL, headers=HEADERS)
            except Exception as exc:
                log.warning("treasury_seized.fetch_failed", error=str(exc)[:200])
                return []
        # Lower bound chosen to accept valid small responses while still
        # filtering out error pages / empty responses. Real Treasury page
        # is ~120KB; a 1KB body is essentially "no listings."
        if r.status_code != 200 or len(r.text) < 1000:
            return []

        tree = HTMLParser(r.text)
        # The properties live in a series of div.property or table rows.
        # Without a per-element selector we anchor on the address regex,
        # taking the surrounding 1KB of context as the property block.
        body = tree.body.text(separator="\n") if tree.body else r.text
        out: list[Listing] = []
        seen: set[str] = set()

        for m in ADDR_RE.finditer(body):
            street, city, state_raw, zip_code = m.groups()
            # Normalize "North Carolina"/"SC"/etc. to a 2-letter code.
            state = _normalize_state(state_raw)
            # Only NC + SC for our footprint; Treasury data is national.
            if state not in ("NC", "SC"):
                continue
            key = (street.strip(), city.strip(), state, zip_code)
            if key in seen:
                continue
            seen.add(key)

            # Block of text AFTER the match (for date + price extraction).
            # Looking only forward avoids picking up the prior listing's
            # price/date when listings are stacked in the same page.
            block = body[m.end():m.end() + 400]
            sale_date = None
            # Try the written-month format first ("November 19, 2026") --
            # confirmed live to be the ONLY format the real page uses; the
            # numeric DATE_RE below is kept as a defensive fallback in case
            # a future listing ever uses it instead.
            dm = WRITTEN_DATE_RE.search(block) or DATE_RE.search(block)
            if dm:
                from dateutil import parser as dp
                try:
                    sale_date = dp.parse(dm.group(0), fuzzy=True)
                except (ValueError, TypeError):
                    sale_date = None
            price = None
            pm = PRICE_RE.search(block)
            if pm:
                try:
                    price = float(pm.group(1).replace(",", ""))
                except ValueError:
                    price = None

            # Found 2026-10-01 (national/reo per-source audit): beds/baths/
            # sqft and the Treasury's own "Sale #" case identifier are free
            # text in the same block already fetched -- confirmed live on
            # real listings -- but were never parsed into structured fields.
            case_number = None
            sm = SALE_NUM_RE.search(block)
            if sm:
                case_number = sm.group(1).strip()
            sqft = None
            sqm = SQFT_RE.search(block)
            if sqm:
                try:
                    sqft = float(sqm.group(1).replace(",", ""))
                except ValueError:
                    sqft = None
            beds = None
            bm = BEDS_RE.search(block)
            if bm:
                try:
                    beds = float(bm.group(1))
                except ValueError:
                    beds = None
            baths = None
            bam = BATHS_RE.search(block)
            if bam:
                try:
                    baths = float(bam.group(1))
                except ValueError:
                    baths = None

            out.append(Listing(
                source=self.slug,
                source_url=URL,
                listing_type=ListingType.REO,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                street_address=street.strip(),
                city=city.strip(),
                zip_code=zip_code,
                opening_bid=price,
                sale_date=sale_date,
                case_number=case_number,
                living_sqft=sqft,
                bedrooms=beds,
                bathrooms=baths,
                description=f"US Treasury seized real-property auction ({state})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"treasury_seized": {"forward_excerpt": block[:500]}},
            ))
        log.info("treasury_seized.done", count=len(out))
        return out
