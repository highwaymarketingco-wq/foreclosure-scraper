"""Beaufort County SC — Forfeited Land Commission (FLC) parcels via Meares Property
Advisors / Proxibid.

Beaufort County's own site (beaufortcountysc.gov) and its Zendesk-hosted treasurer
help-center (treasurerhelp.zendesk.com) both describe the FLC bid process but link to
no property list, and beaufortcountysc.gov 403s to a plain fetch (verified 2026-09-28,
both plain httpx and curl_cffi impersonate=chrome). Beaufort instead contracts a
third-party licensed auctioneer, Meares Property Advisors (MPA-SC.com, Pelzer SC), to
run its FLC inventory through Proxibid — the SAME "administrator serves the FLC auction
for multiple counties" shape already proven by counties_sc.terry_howe_flc, just a
different administrator/platform. Meares also runs Greenville and Orangeburg County FLC
auctions on Proxibid (both already show tax_sale rows from other sources in the board,
so only Beaufort needed a new scraper here).

Live-verified 2026-09-28: the catalog URL below returns 200 to a plain HTTP GET (no
login, no CAPTCHA; curl_cffi impersonate is enough, plain httpx also worked) and is
server-rendered — no JS execution needed to see the data. Each lot repeats the same
block:

    <h2 class="lotListTitle"><a href="/lotinformation/<lot_id>/<slug>">TITLE</a></h2>
    ...
    <div class="lotMetaData"><span><span>Lot Size: </span>1.29 acres</span>
      <span><span>Property Location - County: </span>Beaufort</span>
      <span><span>APN/Parcel ID: </span>R100 016 000 0037 0000</span>
      <span><span>Street: </span>Stuart Point Road</span>
      <span><span>City: </span>Seabrook</span></div>
    ...
    <input type="hidden" id="highBidOpenBid<lot_id>" ... value="2050" />

46 parcel rows were present on first probe, all "Property Location - County: Beaufort",
all titled "<OWNER NAME> (FLC)" — a live-verified real parcel feed, not page chrome.

Proxibid has no stable per-county search API the way Terry Howe's WordPress REST
endpoint does (a Proxibid site search for "Meares Property Advisors" returned 0 hits as
of 2026-09-28), so — like sc_flc.py's COUNTY_FLC_DOCS — this curates the direct catalog
URL rather than discovering it fresh each run. Beaufort's FLC cycles to a new auction
periodically; when this URL 404s/redirects, it needs updating to the new event-catalog
id (the same maintenance shape sc_flc.py's own docstring already calls out for its doc
links: "a 404 here means check for a new year's filename, not a bug").

FLC holdings are a STANDING condition (the county/FLC owns the parcel until someone
bids), not a scheduled event, so this scraper never sets sale_date — it must stay in
main.DATELESS_OK_SOURCES or _active_only() silently deletes every row.

Free, public HTTP. No login, no paywall, no CAPTCHA, no WAF bypass.

DISABLED 2026-10-03 (extraction-completeness re-audit, batch 8): CATALOG_URL
is a DEAD, CLOSED auction, not a live feed, and the scraper had no way to
tell the difference. Live-verified three independent ways:

  1. The catalog page ITSELF says so: fetching event-catalog/131010 live
     today renders "Auction closed." at the top, and every one of its 73
     lots is labelled either "PASSED / This lot was not sold" or
     "Sold for: USD <amount> to <masked bidder>" — e.g. lot #1 (37459633,
     Stuart Point Road, Seabrook) shows "Sold for: USD 2,050.00 to s****s".
     Opening a single lot's own detail page (lot #2, 37459634, "SOUTH
     CAROLINA REALTY (FLC) - Adams Way") in a real browser shows
     "AUGUST 10, 2017 / Lot Closed" — this catalog is a NINE-YEAR-OLD
     frozen snapshot, not current inventory. `_parse_lots` never read the
     PASSED/Sold status at all, so the old code was publishing 2017
     already-resolved lots (including ones already SOLD to a real bidder
     nine years ago) as if they were live, biddable TAX_SALE listings
     today, with the 2017 sale price mislabeled as a current `opening_bid`.
  2. No newer Beaufort FLC Proxibid catalog exists to repoint to: a
     Proxibid site search and a general web search for "Beaufort County
     Forfeited Land Commission" (site:proxibid.com) turn up only this 2017
     catalog (131010) and a 2016 one (111679, "...-2016/event-catalog/
     111679") — nothing current. Meares' own site (mpa-sc.com) has since
     moved its active sales to its own bid.mpa-sc.com platform, and its
     live Real Estate Auctions page (fetched 2026-10-03) lists no Beaufort
     listing at all.
  3. Beaufort County's OWN current, authoritative page confirms zero FLC
     inventory right now: treasurerhelp.zendesk.com's "List of Forfeited
     Land Commission Properties" article (part of the same Zendesk help
     center the module docstring above already cites, last updated ~6
     months ago, i.e. maintained) states plainly: "There are currently no
     properties available for bidding at this time." This is the real,
     current, free source of truth for this source's own stated purpose —
     not a scrape target today (support-article prose, not a table, and
     correctly reports 0), but the place a future session should check
     first before trusting any Proxibid catalog ID again, and the place to
     build a real scraper against once/if the county starts posting live
     FLC inventory there (URL below).

No fix was possible that keeps this scraper useful: filtering out "Sold
for" rows would still leave "PASSED" rows from a 9-year-old auction with no
evidence they reflect Beaufort's FLC holdings today, and the county's own
page says the true current count is zero. Disabled rather than patched —
matches this same session's treatment of chester_delinquent_tax.py /
clarendon_tax_auction.py / darlington_delinquent_tax.py (superseded /
dead sources, documented not forced).  Do not re-enable without either a
genuinely current Proxibid catalog id, or a real scraper against
AUTHORITATIVE_SOURCE_URL below once it carries real rows.

Slug: counties_sc.beaufort_flc
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

#: Curated, live-verified direct catalog URL (see module docstring for why this can't
#: be discovered fresh each run). Update the event-catalog id when this 404s.
#: CONFIRMED CLOSED/STALE 2026-10-03 -- this is a 2017 auction, not live inventory.
#: See the module docstring's 2026-10-03 note before reusing this URL.
CATALOG_URL = (
    "https://www.proxibid.com/Meares-Property-Advisors-Inc/"
    "Beaufort-County-Forfeited-Land-Commission/event-catalog/131010"
)

#: Beaufort County's own current/authoritative FLC inventory page (part of its
#: treasurer help center). Live 2026-10-03: "There are currently no properties
#: available for bidding at this time." Check here, not Proxibid, before any
#: future rebuild of this source.
AUTHORITATIVE_SOURCE_URL = (
    "https://treasurerhelp.zendesk.com/hc/en-us/articles/"
    "4409066520973-List-of-Forfeited-Land-Commission-Properties"
)

_LOT_TITLE_RE = re.compile(
    r'<h2 class="lotListTitle"><a[^>]*href="/lotinformation/(\d+)/[^"]*"[^>]*>'
    r'([^<]*)</a></h2>',
)
_META_BLOCK_RE = re.compile(
    r'<div class="lotMetaData">(.*?)</div>\s*<div id="lotDesc"', re.S,
)
_META_FIELD_RE = re.compile(r'<span>([^<:]+):\s*</span>([^<]*)</span>')
_BID_RE = re.compile(r'id="highBidOpenBid(\d+)"[^>]*value="([\d.]+)"')


def _parse_lots(page_html: str) -> list[dict]:
    """One dict per lot: {lot_id, title, county, parcel_id, street, city, size,
    opening_bid}. Bounded per-lot by splitting on each lotListTitle anchor so a
    malformed block can't bleed metadata into its neighbor."""
    titles = list(_LOT_TITLE_RE.finditer(page_html))
    bids = {m.group(1): m.group(2) for m in _BID_RE.finditer(page_html)}
    rows: list[dict] = []
    for i, tm in enumerate(titles):
        lot_id, title = tm.group(1), tm.group(2).strip()
        start = tm.end()
        end = titles[i + 1].start() if i + 1 < len(titles) else len(page_html)
        chunk = page_html[start:end]
        meta_m = _META_BLOCK_RE.search(chunk)
        fields: dict[str, str] = {}
        if meta_m:
            for fm in _META_FIELD_RE.finditer(meta_m.group(1)):
                fields[fm.group(1).strip().lower()] = html.unescape(fm.group(2).strip())
        amt: Optional[float] = None
        raw_amt = bids.get(lot_id)
        if raw_amt:
            try:
                amt = float(raw_amt)
            except ValueError:
                amt = None
        rows.append({
            "lot_id": lot_id,
            "title": title,
            "county": fields.get("property location - county"),
            "parcel_id": fields.get("apn/parcel id"),
            "street": fields.get("street"),
            "city": fields.get("city"),
            "size": fields.get("lot size"),
            "opening_bid": amt,
        })
    return rows


class BeaufortFLC(BaseScraper):
    slug = "counties_sc.beaufort_flc"
    name = "Beaufort County SC Forfeited Land Commission (via Meares/Proxibid)"
    disabled = True
    disabled_reason = (
        "CATALOG_URL is a closed 2017 Proxibid auction (page itself says "
        "'Auction closed.'; sampled lots show 'PASSED'/'Sold for: USD ...' "
        "9-year-old outcomes, not live inventory); no newer Beaufort FLC "
        "Proxibid catalog found (Proxibid + web search); county's own "
        "current page (AUTHORITATIVE_SOURCE_URL) states 'There are "
        "currently no properties available for bidding at this time' - "
        "confirmed 2026-10-03"
    )
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            page_html = await get_text(CATALOG_URL, impersonate=True, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("beaufort_flc.fetch_fail", error=str(exc)[:160])
            return out
        if not page_html:
            return out

        seen: set[str] = set()
        for row in _parse_lots(page_html):
            county = (row.get("county") or "").strip()
            if county and county.lower() != "beaufort":
                continue  # a stray non-Beaufort lot in the same catalog
            parcel = row.get("parcel_id")
            if not parcel and not row.get("street"):
                # Announcement/instructions lots ("Information for Bidders", HOA
                # notices) carry no APN and no street -- not a real parcel.
                continue
            key = parcel or f"{row['lot_id']}"
            if key in seen:
                continue
            seen.add(key)
            title = html.unescape(row["title"])
            owner = re.sub(r"\s*\(FLC\).*$", "", title, flags=re.I).strip() or None
            street = row.get("street")
            city = row.get("city")
            desc_bits = [b for b in (row.get("size"), f"Lot #{row['lot_id']}") if b]
            out.append(
                Listing(
                    source=self.slug,
                    source_url=CATALOG_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    foreclosure_process="tax",
                    state="SC",
                    county="Beaufort",
                    parcel_id=parcel,
                    street_address=street or None,
                    city=city or None,
                    opening_bid=row.get("opening_bid"),
                    owner_name=owner,
                    defendant=owner,
                    description=(f"Beaufort County SC FLC parcel {parcel or ''} — "
                                  f"{', '.join(desc_bits)}").strip(" —"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"flc": {
                        "auctioneer": "Meares Property Advisors",
                        "platform": "Proxibid",
                        "lot_id": row["lot_id"],
                        "source": "forfeited_land_commission",
                        "catalog_url": CATALOG_URL,
                    }},
                )
            )

        log.info("beaufort_flc.done", count=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = BeaufortFLC()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:20]:
            print(" -", r.county, "|", r.parcel_id, "|", r.street_address,
                  "|", r.city, "| $", r.opening_bid, "|", r.owner_name)

    asyncio.run(_main())
