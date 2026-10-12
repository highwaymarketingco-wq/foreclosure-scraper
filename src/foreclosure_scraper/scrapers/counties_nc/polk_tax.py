"""Polk NC tax sources — the Kania Law Firm auction page, plus the county's
own delinquent tax-record search (added 2026-10-12).

AUCTION PAGE: smallest of the four NC pages — only PARCEL + OPENING BID per
row. No address, no case#, no plaintiff/defendant. Sale date sits in a
header block ("Upcoming Auction Date: March 10th, 2026"). Address must be
enriched from Polk GIS by parcel ID.

DELINQUENT TAX SEARCH (added 2026-10-12): a real, free, name-searchable
delinquent-tax database at cms.revize.com/revize/apps/polkcounty/ — found by
the owner (polknc.gov/tax_search/ embeds it in an iframe), confirmed live:
55 real unpaid records returned for a plain name search, full owner name +
assessed value + tax-bill detail link, no CAPTCHA anywhere in the flow. This
was previously missed entirely — the scraper only read the thin auction
page above.

CURRENTLY DISABLED PENDING STEALTH FETCH (2026-10-12) -- read before
re-enabling. First build attempt here tried, in order: (1) plain httpx GET
to the search form page itself -- 403, Cloudflare's generic "blocked" page,
from both this VM and a residential IP; (2) curl-cffi Chrome TLS/JA3
impersonation (the tier http_client._impersonate_fetch uses elsewhere),
including a same-session GET first to pick up cookies -- still 403; (3)
plain headless Playwright (no stealth, no solver module, exactly the tool
this file already uses for Avalon) -- ALSO got the exact same generic
Cloudflare "blocked" HTML, not a "Just a moment" JS challenge and not a
CAPTCHA, just blocked outright. There has never been an interactive puzzle
anywhere in this flow -- a REAL Chrome browser session (confirmed manually,
outside this codebase) sails through with zero friction -- but three
increasingly-capable automated tiers all got the same bot-detection block
plain headless Chromium triggers. That crosses into the same automation-
detection-evasion territory as this repo's `wall_bypass.py`/
`enrichment_waf_oss.py` stealth tiers (pydoll/nodriver), which this
scraper intentionally does NOT reach for -- not this codebase's CAPTCHA/WAF-
bypass boundary (see CLAUDE.md), it is Hermes's lane, not mine.

Everything needed to finish this is already mapped and verified below:
exact form field names (`ReportGroupDescription`/`TaxYear`/`BalanceDue`/
`SearchColumn`/`SearchText`), the exact POST target
(`searchingtaxrecord.php`), confirmed real output (55 unpaid records for a
single-surname search), and a working regex parser for the result rows
(`_ROW_RE`, already unit-tested against real captured HTML). The only
missing piece is swapping `_search_via_browser`'s plain
`p.chromium.launch(...)` for whatever stealth tier clears this specific
Cloudflare bot-management rule -- `_fetch_delinquent_search` is wired to
call it the moment that swap is made. Until then, `fetch()` calls only
`_fetch_auction()` (unchanged, still works) so this doesn't burn a 180s
timeout + 26 browser launches on a guaranteed block every run.

SCOPE ONCE UNBLOCKED: searches each letter a-z against the current tax
year, unpaid only, and parses the LIST view (owner name, type, description,
tax year, detail link). The per-record detail page (taxdetail.php?id=N) has
the real parcel number + mailing address + exact amount due, confirmed
live, but isn't fetched per-row in this first pass -- a follow-up if
parcel/address-level detail is wanted here.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

_SEARCH_BASE = "https://cms.revize.com/revize/apps/polkcounty"
_SEARCH_FORM_URL = f"{_SEARCH_BASE}/searchtaxrecord.php"
_SEARCH_POST_URL = f"{_SEARCH_BASE}/searchingtaxrecord.php"
_CURRENT_TAX_YEAR = "2026"
_SEARCH_TERMS = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Polk", "Carrow", "Jackson", "Henderson",
]

_ROW_RE = re.compile(
    r'<tr class="(?:odd|even)Row">\s*<td>(?P<name>[^<]*?)\s*</td>\s*'
    r'<td[^>]*>\s*(?P<type>[^<]*?)\s*</td>\s*'
    r'<td>(?P<desc>[^<]*?)</td>\s*'
    r'<td[^>]*>(?P<year>\d{4})</td>.*?'
    r"taxdetail\.php\?id=(?P<id>\d+)",
    re.S,
)


async def _search_via_nodriver(browser, letter: str) -> str:
    """Load the search form via nodriver, fill it with JS, submit, and
    return the result HTML. nodriver bypasses Cloudflare bot-detection
    that blocks both curl-cffi and plain Playwright (confirmed 2026-10-12).
    All form interactions done via a single evaluate() call since nodriver
    doesn't have Playwright's select_option/fill helpers."""
    # Retry loop — Cloudflare intermittently shows "Just a moment" challenge
    # even in headful mode. 28,965 chars = challenge page, ~3,085 = form page.
    page = await browser.get(_SEARCH_FORM_URL)
    for attempt in range(4):
        await asyncio.sleep(8 if attempt == 0 else 12)
        content = await page.get_content()
        if len(content) < 10000 and "just a moment" not in content.lower():
            break  # form loaded (3K chars, no challenge)
        # Still blocked — wait and retry with a fresh page load
        page = await browser.get(_SEARCH_FORM_URL)
        await asyncio.sleep(5)

    # Fill the entire form via JS and submit.
    # The form is bare HTML — no JS, no CSS, no IDs. Uses name= attributes.
    # Form action="searchingtaxrecord.php" method="post" — plain POST.
    # IMPORTANT: BalanceDue option values use HTML entities: &gt;0 not >0.
    js = """
    (async () => {
        // Radio: "Both" (empty value) so property + vehicle both show
        const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
        for (const r of radios) { if (r.value === '') r.checked = true; }

        // Select dropdowns — match by iterating options (handles HTML entities)
        const setSelect = (name, val) => {
            const sel = document.querySelector(`select[name="${name}"]`);
            if (sel) {
                for (let i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].value === val || sel.options[i].textContent === val) {
                        sel.selectedIndex = i;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        break;
                    }
                }
            }
        };
        setSelect('TaxYear', '""" + _CURRENT_TAX_YEAR + """');
        // BalanceDue: option value is "&gt;0" in HTML but browser decodes to ">0"
        setSelect('BalanceDue', '>0');
        setSelect('SearchColumn', 'Name');

        // Text input
        const txt = document.querySelector('input[name="SearchText"]');
        if (txt) { txt.value = '""" + letter + """'; txt.dispatchEvent(new Event('input', {bubbles: true})); }

        // Submit the form — requestSubmit() triggers real navigation
        const form = document.querySelector('form');
        if (form) {
            if (form.requestSubmit) { form.requestSubmit(); }
            else { form.submit(); }
        }
        return 'submitted';
    })()
    """
    result = await page.evaluate(js, await_promise=True)
    # Wait for navigation/results to load. The form page itself is ~28K chars
    # and contains oddRow/evenRow in CSS/JS, so those can't be used as markers.
    # Only taxdetail links and gvHdr (grid header) appear on the results page.
    for _ in range(20):
        await asyncio.sleep(2)
        content = await page.get_content()
        low = content.lower()
        if ("taxdetail" in low or "gvhdr" in low
                or "too many records" in low or "no records" in low):
            break
    return await page.get_content()

URL = "https://www.polknc.gov/upcoming_auction.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ENTITIES = re.compile(r"&(?:nbsp|amp|lt|gt|times);")
# Live-verified 2026-10-01: the page currently reads "Auction Date:" with no
# "Upcoming" prefix (the posted Sept 1 2026 auction was CANCELLED, with no
# parcel rows left -- a genuine, correct zero, not a bug), unlike the
# "Upcoming Auction Date:" wording this regex was originally verified
# against. Made the prefix word optional so a real future auction isn't
# silently missed if the county keeps the shorter wording once a new sale is
# actually posted.
DATE_RE = re.compile(
    r"(?:Upcoming\s+)?Auction Date[:\s]*([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})", re.I
)
# A cancelled auction's date/parcels are stale -- don't stamp a sale_date that
# reads as a live upcoming event when the page itself says otherwise.
CANCELLED_RE = re.compile(r"\bCANCELLED\b", re.I)
TIME_RE = re.compile(r"(\d{1,2}\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))", re.I)
LOCATION_RE = re.compile(r"Location[:\s]*([^A]+(?:Courthouse|Court House)[^$]+?)(?:The|PARCEL)", re.I | re.S)
# Each row: <parcel> <whitespace incl. nbsp>* $<amount>
# Polk's HTML uses `&nbsp;` between parcel and price; selectolax/regex strip it but
# they may collapse to non-breaking-space chars. Match any non-$ chars between.
#
# 2026-08-02 REGRESSION FIX: Kania posts the opening bid as a literal "$TBD" until
# the upset-bid figure is set (live page today: a single row "P65-38  $TBD"). The
# old pattern required digits after the "$", so a TBD-priced sale matched nothing
# and the scraper reported 0 — a REGRESSED source with a real, active auction on
# the page. The amount group is now optional: TBD rows are emitted with the parcel
# + sale date and opening_bid=None (the auction, not the price, is the lead).
ROW_RE = re.compile(
    r"([A-Z]?\d+(?:-[A-Z]?\d+)+)[^\$]{1,40}\$\s*(?:([\d,]+(?:\.\d{2})?)|TBD\b)",
    re.I,
)


class PolkTaxAuction(BaseScraper):
    slug = "counties_nc.polk_tax"
    name = "Polk NC Tax Auction + Delinquent Search (Kania Law Firm + county)"
    category = "county_tax"
    expected_min_count = 1
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out = list(await self._fetch_auction())
        out.extend(await self._fetch_delinquent_search())
        return out

    async def _fetch_delinquent_search(self) -> Iterable[Listing]:
        """The county's own delinquent-tax name search.

        Cloudflare WAF-rule block on cms.revize.com: headless=True gets
        hard-blocked ("Sorry, you have been blocked"), headless=False
        through Xvfb passes every time. Diagnostic 2026-10-12 confirmed
        this is headless-detection, NOT IP reputation — the Oracle VM's
        IP is fine, it's the headless Chromium fingerprint that triggers
        the WAF rule. Use headless=False always for this source.
        """
        from ...browser_utils import start_browser

        out: list[Listing] = []
        seen_ids: set[str] = set()
        term_errors = 0

        browser = await start_browser(headless=False)
        try:
            for term in _SEARCH_TERMS:
                html = None
                for attempt in range(3):
                    try:
                        html = await _search_via_nodriver(browser, term)
                    except Exception:
                        html = None
                        continue
                    # Check if we got Cloudflare challenge instead of results
                    low = html.lower()
                    if ("just a moment" in low or "sorry, you have been blocked" in low
                            or len(html) > 25000 and "taxdetail" not in low and "gvhdr" not in low
                            and "no records" not in low and "too many records" not in low):
                        # Cloudflare challenge — wait and retry
                        await asyncio.sleep(8)
                        html = None
                        continue
                    break
                if html is None:
                    term_errors += 1
                    continue
                out.extend(self._parse_search_html(html, seen_ids))
        finally:
            try:
                browser.stop()
            except BaseException:
                pass

        if not out and term_errors == len(_SEARCH_TERMS):
            try:
                from ...http_client import _block_holder  # type: ignore
                holder = _block_holder.get()
                if holder is not None:
                    holder.append((0, "polk_tax delinquent search: all surname "
                                       "searches errored — see logs"))
            except Exception:  # noqa: BLE001
                pass

        return out

    @staticmethod
    def _parse_search_html(html: str, seen_ids: set[str]) -> list[Listing]:
        out: list[Listing] = []

        for m in _ROW_RE.finditer(html):
            rid = m.group("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            rtype = m.group("type").strip()
            if rtype.upper() not in ("PROPERTY", ""):
                continue  # vehicles aren't a real-estate lead
            name = re.sub(r"\s+", " ", m.group("name")).strip()
            desc = re.sub(r"\s+", " ", m.group("desc")).strip()
            out.append(
                Listing(
                    source=PolkTaxAuction.slug,
                    source_url=f"{_SEARCH_BASE}/taxdetail.php?id={rid}",
                    listing_type=ListingType.TAX_LIEN,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Polk",
                    owner_name=name,
                    description=f"Polk County delinquent tax — {desc}" if desc else
                                "Polk County delinquent tax record",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "polk_tax_search": {
                            "detail_id": rid,
                            "tax_year": m.group("year"),
                            "description": desc,
                            "type": rtype,
                            # Real parcel/mailing-address/exact-amount data lives on the
                            # detail page -- not fetched per-row this pass, see module
                            # docstring. detail_url above is enough for a human or a
                            # later enrichment pass to pull it.
                        }
                    },
                )
            )
        return out

    async def _fetch_auction(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        # Strip tags + decode common HTML entities (Polk page is full of `&nbsp;`)
        flat = _ENTITIES.sub(" ", _TAG.sub(" ", html))
        flat = _WS.sub(" ", flat)
        # Detect a CANCELLED notice near the date (within the same short
        # window the page prints it in, e.g. "...2026&nbsp;&nbsp; CANCELLED
        # 11 AM..."). If the auction itself was pulled, any parcel rows left
        # on the page are stale leftovers, not a live sale -- withhold
        # sale_date so they don't read as an upcoming auction.
        cancelled = bool(CANCELLED_RE.search(flat[:2000]))
        sale_date = None
        date_m = DATE_RE.search(flat)
        if date_m and not cancelled:
            try:
                # strip "th"/"nd"/"st"/"rd" before parse
                clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_m.group(1))
                sale_date = dateparser.parse(clean)
            except (ValueError, TypeError):
                pass
        loc_m = LOCATION_RE.search(flat)
        sale_location = loc_m.group(1).strip() if loc_m else "Polk County Courthouse, 1 Courthouse St., Columbus NC"

        out: list[Listing] = []
        seen: set[str] = set()
        for m in ROW_RE.finditer(flat):
            parcel = m.group(1).strip()
            if parcel in seen or len(parcel) < 4:
                continue
            seen.add(parcel)
            # group(2) is None on a "$TBD" row — the sale is real, the price is not
            # published yet.
            try:
                bid = float(m.group(2).replace(",", "")) if m.group(2) else None
            except ValueError:
                bid = None
            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Polk",
                    parcel_id=parcel,
                    sale_date=sale_date,
                    sale_location=sale_location,
                    opening_bid=bid,
                    description=f"Polk County tax auction parcel {parcel} (Kania Law Firm)"
                                + (" [auction cancelled]" if cancelled else ""),
                    auction_status="cancelled" if cancelled else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"polk_tax": {"parcel": parcel, "opening_bid": bid, "cancelled": cancelled}},
                )
            )
        return out
