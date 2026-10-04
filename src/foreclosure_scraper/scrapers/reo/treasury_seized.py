"""Treasury seized real-property auctions — federal REO source.

US Treasury seizes real property in tax/criminal forfeiture cases and
publishes upcoming auctions at:

  https://www.treasury.gov/auctions/treasury/rp/realprop.shtml

Volume is small (~20 properties nationwide at any time) but they're
zero-competition — the public doesn't know to look here.

Free, no auth, plain HTML. Refresh cadence is irregular (case-driven).

EXTRACTION-COMPLETENESS AUDIT (2026-10-04, final batch). Three confirmed
live findings:

1. **A real, currently-live NC listing was completely invisible.** ADDR_RE
   required a plain whitespace right after the house-number digits
   (``\\d{1,5}\\s+``). A real live listing's address is
   "139-B Farless Road, Merry Hill, North Carolina 27957" -- the "-B" unit
   suffix sits between the digits and the whitespace, so the regex never
   matched at all. Fixed with an optional ``(?:-[A-Za-z])?`` after the
   digit run; live-confirmed both this address and every ordinary
   ("2721 Briar Ridge Drive, ...") shape still match correctly.
2. **``opening_bid`` was dead code -- always None on every real listing.**
   The list page (``realprop.shtml``) never shows a dollar price at all
   (confirmed live: every ``$`` on that page is from a jQuery CDN URL in a
   ``<script>`` tag, not a listing). The real "Starting Bid: $X" lives ONLY
   on each property's own per-listing detail page, which this scraper never
   fetched.
3. **Each listing's own detail page (linked right from the list page,
   e.g. "...click on the photo or CLICK HERE" -> ``2721briar.shtml``) carries
   a large amount of structured data never captured at all**: a real PDF
   auction flyer (route through ``harvest_document_links``/
   ``stamp_documents``), the parcel number, the county name (the list page
   has NO county field at all today), the exact lot size ("Site Area"),
   year built, zoning, the auctioneer's name/license, and the real photo
   thumbnail (the list page's ``<img>`` was never captured either). Federal
   nationwide volume is tiny (~15 properties site-wide, 2-3 in NC/SC), so a
   per-matched-row detail fetch is cheap. Wired via a regex-free
   label/line-pairing over the detail page's own newline-separated text
   (each field renders as "Label:" on its own line, the value on the next --
   live-confirmed stable across 2 real detail pages).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
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
# The house number sometimes carries a unit-letter suffix with no space
# before it ("139-B Farless Road") -- live-confirmed 2026-10-04 this made a
# real current NC listing invisible (the old pattern required whitespace
# immediately after the digit run). `(?:-[A-Za-z])?` optionally absorbs it.
ADDR_RE = re.compile(
    r"\b(\d{1,5}(?:-[A-Za-z])?\s+[A-Z][\w .'\-]+?)\s*,?\s*"
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

# Each real listing block wraps its own thumbnail + "click on the photo"
# anchor around an <img> whose `alt` repeats the full address text, e.g.
# `<a href="2721briar.shtml"><img src="images/2721briar01.gif"
# alt="2721 Briar Ridge Drive, Charlotte, North Carolina 28270" ...></a>`.
# Live-confirmed 2026-10-04 this is the only reliable join key back to a
# specific ADDR_RE match (the list page's own text is stripped of all
# markup before ADDR_RE ever runs). A property whose detail page isn't
# ready yet omits the <a> wrapper entirely ("...coming soon...", no link) --
# that case naturally produces no dict entry, handled gracefully below.
_DETAIL_LINK_RE = re.compile(
    r'<a href="([a-z0-9]+\.shtml)">\s*<img src="(images/[^"]+)"\s+alt="([^"]*)"',
    re.I,
)
# Cap on per-run detail-page fetches -- defensive only; real NC/SC volume at
# any time is a small handful (confirmed live: 2-3), nowhere near this.
_DETAIL_FETCH_CAP = 20

# The detail page renders every "Label:" / value pair as two consecutive
# plain-text lines once HTML is stripped with a newline separator -- live-
# confirmed stable across 2 real detail pages (2721briar.shtml, a single-
# family home; the pattern is the site's own shared template, not
# per-listing markup). Maps the stripped, colon-less, lowercased label to
# the Listing/raw field it fills.
_DETAIL_LABELS = {
    "starting bid": "opening_bid",
    "living space": "living_sqft",
    "site area": "lot_size_sqft",
    "year built": "year_built",
    "parcel no": "parcel_id",
    "parcel number": "parcel_id",
    "zoning": "zoning",
    "cws nc auction license": "auction_license",
    "auctioneer": "auctioneer",
}
# "2025 Mecklenburg County Taxes:" -- the ONLY place the county name appears
# anywhere on either the list or detail page; the list page has no county
# field at all today.
_COUNTY_TAX_LINE_RE = re.compile(
    r"^\s*(?:\d{4}\s+)?([A-Z][A-Za-z]+)\s+County\s+Taxes:?\s*$", re.I
)
_MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")
_NUM_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
_YEAR_RE = re.compile(r"(\d{4})")
# The detail page's own "Auction Flyer:" link, specifically -- live-confirmed
# 2026-10-04 harvest_document_links()'s generic scan also picks up an
# UNRELATED property's flyer cached elsewhere on the same page (a "similar
# properties" sidebar) ahead of this one's own, so the generic harvester's
# FIRST url is not reliably this listing's own document. This targeted
# match is used to force the right one primary.
_FLYER_HREF_RE = re.compile(r'Auction\s*Flyer:.*?href="([^"]+)"', re.I | re.S)


def _detail_link_map(list_html: str) -> dict[str, tuple[str, str]]:
    """street-address-lowercased -> (detail_href, photo_src), read straight
    off the list page's raw HTML (see _DETAIL_LINK_RE)."""
    out: dict[str, tuple[str, str]] = {}
    for href, photo_src, alt in _DETAIL_LINK_RE.findall(list_html):
        street = alt.split(",", 1)[0].strip().lower()
        if street:
            out[street] = (href, photo_src)
    return out


def _parse_detail_page(html: str) -> dict:
    """Label/value pairs off one property's own detail page. Best-effort --
    any field the page doesn't have is simply absent; never raises."""
    tree = HTMLParser(html)
    body_text = tree.body.text(separator="\n") if tree.body else html
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body_text.split("\n")]
    lines = [ln for ln in lines if ln]
    out: dict = {}
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        key = line.rstrip(":").strip().lower()
        if key in _DETAIL_LABELS and nxt:
            out[_DETAIL_LABELS[key]] = nxt
            continue
        cm = _COUNTY_TAX_LINE_RE.match(line)
        if cm and nxt:
            out["county"] = cm.group(1).strip()
            out["tax_amount_text"] = nxt
    return out


def _f(text: str | None) -> float | None:
    if not text:
        return None
    m = _NUM_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    if not m:
        return None
    try:
        y = int(m.group(1))
        return y if 1700 <= y <= 2100 else None
    except ValueError:
        return None


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
        link_map = _detail_link_map(r.text)
        out: list[Listing] = []
        seen: set[str] = set()
        detail_fetched = 0

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

            li = Listing(
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
            )

            detail_href, photo_src = link_map.get(street.strip().lower(), (None, None))
            if photo_src:
                li.raw["images"] = {"real": [urljoin(URL, photo_src)]}
            if detail_href and detail_fetched < _DETAIL_FETCH_CAP:
                detail_fetched += 1
                detail_url = urljoin(URL, detail_href)
                li.source_url = detail_url
                await self._enrich_from_detail(li, detail_url)

            out.append(li)
        log.info("treasury_seized.done", count=len(out), detail_fetched=detail_fetched)
        return out

    async def _enrich_from_detail(self, li: Listing, detail_url: str) -> None:
        """Best-effort per-listing detail-page pull: real opening_bid (the
        list page never shows a price at all -- see module docstring finding
        #2), parcel/county/zoning/lot-size/year-built/auctioneer (finding
        #3), and the PDF auction flyer via the shared document harvester.
        Never raises -- a failure here must not cost the list-only lead this
        scraper already had."""
        try:
            async with client(timeout=20.0) as c:
                r = await c.get(detail_url, headers=HEADERS)
                if r.status_code != 200 or len(r.text) < 500:
                    return
                html_text = r.text
        except Exception as exc:  # noqa: BLE001
            log.info("treasury_seized.detail_failed", url=detail_url, error=str(exc)[:160])
            return

        fields = _parse_detail_page(html_text)
        if not fields:
            return

        bid = _f(fields.get("opening_bid"))
        if bid is not None:
            li.opening_bid = bid  # the ONLY place a real price exists
        living = _f(fields.get("living_sqft"))
        if living is not None:
            li.living_sqft = living  # detail is more precise than the free-text fallback
        lot = _f(fields.get("lot_size_sqft"))
        if lot is not None:
            li.lot_size_sqft = lot
        year = _year(fields.get("year_built"))
        if year is not None:
            li.year_built = year
        if fields.get("parcel_id"):
            li.parcel_id = fields["parcel_id"]
        if fields.get("county"):
            li.county = fields["county"]  # the list page has NO county field at all
        if fields.get("zoning"):
            li.zoning = fields["zoning"]

        extra = li.raw.setdefault("treasury_seized", {})
        for k in ("auctioneer", "auction_license", "tax_amount_text"):
            if fields.get(k):
                extra[k] = fields[k]
        tax = _f(fields.get("tax_amount_text"))
        if tax is not None:
            extra["annual_tax"] = tax

        # The PDF flyer -- route through the shared harvester so
        # enrich_doc_ocr reads it, same convention every other document-
        # wired scraper in this repo uses. The generic harvest can surface
        # an unrelated property's flyer ahead of this one's (see
        # _FLYER_HREF_RE's comment), so this listing's OWN "Auction Flyer:"
        # link is forced primary when found.
        doc_urls = harvest_document_links(html_text, base_url=detail_url)
        flyer_m = _FLYER_HREF_RE.search(html_text)
        if flyer_m:
            own_flyer = urljoin(detail_url, flyer_m.group(1))
            doc_urls = [own_flyer] + [u for u in doc_urls if u != own_flyer]
        if doc_urls:
            stamp_documents(li, doc_urls)
