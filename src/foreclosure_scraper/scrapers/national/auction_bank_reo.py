"""Williams & Williams auctions + Founders FCU bank-owned — the thin REO lane.

WHY BOTHER WITH A SOURCE THAT RETURNS SINGLE DIGITS
    REO and auction are the two thinnest lanes on the board (311 and 69 rows).
    A bank or credit union selling its own foreclosed collateral is an
    owner-direct lead with no intermediary, which is worth more per row than
    volume sources. Inventory here also turns over: a reader that returns 4
    today returns a different 4 next quarter, and nothing is captured unless
    something is watching.

MEASURED 2026-08-06 — do not expect volume
    Williams & Williams  4 active in NC, 0 in SC. One in footprint (Shelby,
                         Cleveland County). The other three are Hubert,
                         Raeford and Randleman.
    Founders FCU         1 property, Wadesboro NC 28170, which is Anson County
                         and OUTSIDE the 18-county footprint. It is read anyway
                         because the page is the credit union's whole REO
                         inventory and will change.

WILLIAMS & WILLIAMS IS NOT williamsauction.com
    That domain is a Wix marketing shell whose markup carries no inventory. The
    auctions live on the bid.auctionnetwork.com backend the shell embeds.

    Its ?state= parameter is IGNORED — NC and SC both return byte-identical
    235,273-byte responses, i.e. the full active list. So the state filter is
    applied CLIENT-side here. Do not add ?state and assume it worked.

    robots.txt allows this. It disallows /aspnet_client/, /bin/,
    /App_GlobalResources/, /signalr/, /Account/, /RealTime/ and four specific
    /Listing/ ACTIONS (CreateListingPage1, AddWatch, History, Action) — none of
    which is the auction index this reads.

THE THREE THAT ARE NOT HERE, and why
    Bank of America REO (realestatecenter.bankofamerica.com) — robots.txt is a
        blanket "User-agent: * / Disallow: /". Not built, by policy.
    United Community Bank (ucbi.com) — 403 at the edge for robots.txt AND the
        homepage. No free path.
    RealtyBid — the site is an Angular SPA whose API base, resolved out of its
        own bundle, is https://apiweb.realtybid.com/rest/RBIAPI/. That host
        resolves to 172.31.211.215 and 172.31.220.39, both RFC1918 PRIVATE
        addresses, so it is unreachable from the public internet and the site's
        own search sits on "Searching..." forever. Nothing to build against.
    First Bank (localfirstbank.com) — publishes ARTICLES about buying bank-owned
        homes and no actual inventory. Nothing to read.
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

WW_URL = "https://bid.auctionnetwork.com/Auctions"
WW_PARAMS = {"listingTypes": "Auction", "searchStatus": "Active"}
WW_PAGE = "https://www.williamsauction.com/"
FOUNDERS_URL = "https://www.foundersfcu.com/foreclosures"

#: "CITY, ST ZIP" — the only reliably structured locator on either page.
_CITY_ST_ZIP = re.compile(
    r"([A-Z][A-Za-z .'\-]{2,30}),\s*(NC|SC)\s+(\d{5})(?:-\d{4})?")
#: A street line, used to pair an address with the city line that follows it.
#
# The separator after the house number is a SPACE CLASS, never \s+, and the
# match is anchored to a line start. Both matter: Williams & Williams renders
# each row as "<street>\n<city>, ST ZIP\n Foreclosure Auction\n Aug 12", so an
# \s+ that spans newlines reads the PREVIOUS row's "Aug 12" as the house number
# and produces "12 2005 ROBYN AVE".
#
# The trailing group captures route numbers and directionals that follow the
# street type, so "2755 US Hwy 74 E" does not truncate to "2755 US Hwy".
_STREET = re.compile(
    r"^[ \t]*(\d{1,6}[ \t]+[A-Za-z0-9 .'\-]{3,44}?\b(?:St|Street|Rd|Road|Dr|Drive"
    r"|Ln|Lane|Ave|Avenue|Ct|Court|Way|Cir|Circle|Blvd|Hwy|Highway|Pl|Place|Ter"
    r"|Trl|Pkwy)\b\.?(?:[ \t]+\d{1,4})?(?:[ \t]+[NSEW]{1,2}\b)?)",
    re.I | re.M)
#: Only a LABELLED price is trusted. The Williams index carries no per-property
#: price at all, and an unlabelled dollar figure near a row was picking up an
#: unrelated $1,500,000 from elsewhere on the page for two different properties.
_PRICE = re.compile(r"Price\s*:?\s*\$\s?([\d,]{4,12})", re.I)


def body_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?i)<(?:br\s*/?|/p|/div|/li|/tr|/td|/h\d)>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def _price_in(block: str) -> Optional[float]:
    """Price for ONE property, from that property's own block of text only.

    Scanning forward from the city line was wrong in both directions. Williams
    renders the NC rows immediately above a "Featured Properties" section, so
    the last NC row inherited a $1,500,000 belonging to a featured listing.
    Founders puts "Price: $160,000" ABOVE the address line, so a forward-only
    scan missed the only real price on the page.
    """
    m = _PRICE.search(block)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v > 1000 else None


def parse_properties(text: str, source: str, source_url: str,
                     listing_type: ListingType,
                     want_price: bool = False) -> list[Listing]:
    """Pull (street, city, state, zip) tuples out of a rendered page.

    Anchored on the "CITY, ST ZIP" match and looking BACKWARD for the nearest
    street line, because both pages put the street above the city line and
    neither wraps a property in a stable container class.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    now = datetime.utcnow()
    matches = list(_CITY_ST_ZIP.finditer(text))
    for i, m in enumerate(matches):
        city, state, zc = m.group(1).strip(), m.group(2), m.group(3)
        window = text[max(0, m.start() - 220):m.start()]
        streets = _STREET.findall(window)
        street = streets[-1].strip() if streets else None
        # This property's own block: from the previous property's city line to
        # the next one, capped so a lone property cannot absorb a whole page.
        lo = max(matches[i - 1].end() if i else 0, m.start() - 300)
        hi = min(matches[i + 1].start() if i + 1 < len(matches) else len(text),
                 m.end() + 300)
        block = text[lo:hi]
        key = f"{(street or '').upper()}|{city.upper()}|{zc}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Listing(
            source=source, source_url=source_url,
            listing_type=listing_type,
            property_kind=PropertyKind.UNKNOWN,
            state=state, county=None,          # resolved downstream from the address
            street_address=street, city=city, zip_code=zc,
            foreclosure_process="reo",
            description=f"{listing_type.value} — "
                        f"{' '.join(x for x in (street, f'{city}, {state} {zc}') if x)}"[:300],
            first_seen=now, last_seen=now,
            raw={"auction_bank_reo": {
                "seller": source.rsplit(".", 1)[-1],
                "city": city, "state": state, "zip": zc,
                "street": street,
                # want_price is False for the Williams index because it
                # publishes NO per-property price. Any dollar figure near a row
                # there belongs to something else on the page — the last NC row
                # sits just above "Featured Properties" and was inheriting its
                # $1,500,000. A wrong price is worse than no price.
                "price": _price_in(block) if want_price else None,
            }},
        ))
    return out


async def _fetch_williams(c) -> list[Listing]:
    # NB: no state param. The server ignores it and returns the full active
    # list either way, so the footprint filter is applied by parse_properties
    # only matching NC/SC city lines.
    r = await c.get(WW_URL, params=WW_PARAMS, timeout=90.0)
    if r.status_code != 200:
        raise RuntimeError(f"williams: HTTP {r.status_code}")
    rows = parse_properties(body_text(r.text),
                            "national.auction_bank_reo.williams_williams",
                            WW_PAGE, ListingType.AUCTION, want_price=False)
    log.info("auction_bank_reo.williams", leads=len(rows))
    return rows


async def _fetch_founders(c) -> list[Listing]:
    r = await c.get(FOUNDERS_URL, timeout=90.0)
    if r.status_code != 200:
        raise RuntimeError(f"founders: HTTP {r.status_code}")
    rows = parse_properties(body_text(r.text),
                            "national.auction_bank_reo.founders_fcu",
                            FOUNDERS_URL, ListingType.REO, want_price=True)
    log.info("auction_bank_reo.founders", leads=len(rows))
    return rows


class AuctionBankReo(BaseScraper):
    slug = "national.auction_bank_reo"
    name = "Williams & Williams auctions + Founders FCU bank-owned (NC/SC)"
    category = "reo"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_AUCTION_BANK_REO") == "0":
            return []
        out: list[Listing] = []
        # Both are tolerated: each is a single small page that legitimately
        # empties out when the seller has nothing listed, and one seller going
        # quiet must not discard the other.
        guard = LayerHarvest(self.slug, ["williams_williams", "founders_fcu"],
                             attempts=2,
                             tolerate=("williams_williams", "founders_fcu"))
        async with client(timeout=90.0) as c:
            with guard:
                out.extend(await guard.harvest(
                    "williams_williams", lambda: _fetch_williams(c)))
                out.extend(await guard.harvest(
                    "founders_fcu", lambda: _fetch_founders(c)))
        return out
