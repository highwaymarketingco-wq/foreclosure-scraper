"""Bid4Assets — county tax-deed-sale auction notices (free JSON API).

RE-ENABLED 2026-10-01 (national-auction-tier audit, batch 4). This scraper
was DISABLED 2026-09-15 after the old `index.cfm?searchstate=...` ColdFusion
URL was confirmed to render only site-navigation links, not real results.
Re-verified live per HERMES rule 4 ("DEAD means dead the day it was probed,
not forever") and found the SITE HAS BEEN REDESIGNED since: the old
`index.cfm` URL now serves a literal "Storefront not found or is currently
inactive" page (confirmed dead), but the CURRENT site has a working public
JSON search API behind `/v5/search` that the old scraper never knew about.

Access path (free, no login required to browse):
  1. GET https://www.bid4assets.com/v5/search -- a plain server-rendered
     page (the actual results grid is populated client-side; the server
     response itself never contains listing data regardless of querystring
     params, because the real app reads filter state from the URL HASH
     fragment, which browsers never send to the server -- a dead end if you
     try to scrape *this* page directly). What this GET is actually for:
     it mints a fresh ASP.NET anti-forgery token
     (`<input name="__RequestVerificationToken" value="...">`) tied to the
     session cookies the response sets (including Akamai Bot Manager
     cookies `ak_bmsc`/`bm_mi`/`bm_sv` -- curl_cffi's Chrome impersonation
     satisfies these with no CAPTCHA/challenge, confirmed live, so this is
     NOT a wall).
  2. POST https://www.bid4assets.com/api/search/process?take=&skip=&page=&pageSize=
     with that token in an `X-CSRF-Header-Token` header, the same session's
     cookies, and a JSON body. REVERSE-ENGINEERED THE REAL BODY SHAPE from
     the site's own `/js/client/search_functions.js` (2026-10-01) because
     naive/empty bodies all 200 with `{"data": [], "total": 0}` -- a classic
     silent-zero, not an error:
       - `channel: "22"` scopes to the "Real Estate" channel (IDs pulled
         live from `POST /api/search/channels`).
       - `locatedstate: "NC"` / `"SC"` (verified against `POST
         /api/search/states`, which returns 2-letter `state_abv` codes).
       - `assetstatus` must be the EXPANDED string `"Live"` (not the short
         code `"l"` the client-side JS uses internally before expanding it)
         or the filter silently matches nothing.
       - `type: "powersearch"` and `searchtype: "ps"` must both be set (the
         site's own `buildSearchString()` sets `param_type = 'powersearch'`
         specifically when `searchType == 'ps'`) -- omitting `type` is
         itself enough to silently zero the result set.

Result shape (verified live 2026-10-01): EVERY NC/SC "Real Estate" result
right now is a county-level "NOTICE OF SALE" batch tax-deed auction, e.g.
"NOTICE OF SALE: Cleveland County, North Carolina - Live Tax Deed Sale, 3
Deeds" -- ONE listing covers 1 to ~2,000 individual parcels sold at one
county's tax sale. Confirmed via the detail page's own iframe
(`/auction/iframedescription/{id}`) that Bid4Assets itself carries NO
per-parcel address/amount data for these -- it is explicitly "providing
this notice of sale strictly as a courtesy" and points bidders to the
COUNTY'S own tax-sale page (via a third party, Tax Sale Resources). So we
emit ONE Listing per notice (never fabricate N fake per-parcel rows out of
a "13 Deeds" count with no real per-deed data -- that would be exactly the
kind of fabricated-row bug this project has been bitten by before) with
county/state/sale-date/deed-count, and leave street_address/opening_bid
null rather than invent them. `currentBid: 0` / `bidCount: -1` are present
on every single row with no exceptions -- clearly sentinel placeholders
(same shape as HiBid's `123.45` fake bid), not real data, so they are never
surfaced as `opening_bid`.

Free, no login, no CAPTCHA.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SEARCH_PAGE_URL = "https://www.bid4assets.com/v5/search"
API_URL = "https://www.bid4assets.com/api/search/process"
REAL_ESTATE_CHANNEL = "22"  # "Real Estate" -- verified live via POST /api/search/channels
STATES = ("NC", "SC")
PAGE_SIZE = 100
PAGES_CAP = 5  # current NC/SC real-estate volume is ~10-25 notices total

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_COUNTY_RE = re.compile(
    r"NOTICE OF SALE:\s*([A-Za-z.' ]+?)\s+County,\s*(?:North Carolina|South Carolina)",
    re.I,
)
_DEEDS_RE = re.compile(r"([\d,]+)\s+(?:Redeemable\s+)?Deeds?", re.I)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": SEARCH_PAGE_URL,
    "Origin": "https://www.bid4assets.com",
}


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except ValueError:
        return None


def _build_body(state: str, page: int) -> dict:
    skip = (page - 1) * PAGE_SIZE
    return {
        "sort": None, "sortorder": None, "searchtrackingid": "", "datehistory": None,
        # Both of these must be set together -- see module docstring; an
        # empty/default body 200s with a silently-zeroed result set.
        "type": "powersearch", "criteria": None, "keywordtype": "allWords",
        "searchfield": None,
        "channel": REAL_ESTATE_CHANNEL, "category": None, "subcategory": None,
        # The EXPANDED string, not the short code -- see module docstring.
        "assetstatus": "Live",
        "locatedstate": state, "zip": None, "zipradius": None,
        "sellerid": "", "searchtype": "ps", "currentsearchquerystring": "",
        "page": page, "pageSize": PAGE_SIZE, "pageTake": PAGE_SIZE, "skip": skip,
    }


def _to_listing(row: dict, state: str, slug: str) -> Listing | None:
    title = (row.get("assetTitle") or "").strip()
    aid = row.get("auctionId")
    if not aid or not title:
        return None

    m = _COUNTY_RE.search(title)
    county = (m.group(1).strip() + " County") if m else None

    dm = _DEEDS_RE.search(title)
    num_deeds = None
    if dm:
        try:
            num_deeds = int(dm.group(1).replace(",", ""))
        except ValueError:
            pass

    sale_date = _parse_dt(row.get("bidCloseTime")) or _parse_dt(row.get("actualCloseTime"))

    link = (row.get("linkUrl") or "").strip()
    if link.startswith("/"):
        link = "https://www.bid4assets.com" + link
    elif not link:
        link = f"https://www.bid4assets.com/auction/{aid}"

    return Listing(
        source=slug,
        source_url=link,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        sale_date=sale_date,
        case_number=f"bid4assets-{aid}",
        description=title,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"bid4assets": {
            "auction_id": aid,
            "title": title,
            "num_deeds": num_deeds,
            "bid_close_time": row.get("bidCloseTime"),
            "actual_close_time": row.get("actualCloseTime"),
        }},
    )


async def _get_session_and_token():
    """GET the search page to mint a fresh anti-forgery token tied to the
    session's cookies (incl. the Akamai Bot Manager cookies -- satisfied by
    curl_cffi's Chrome impersonation with no challenge, confirmed live).
    Returns (session, token) or (session, None) on failure -- caller must
    close the session either way."""
    from curl_cffi.requests import AsyncSession

    s = AsyncSession(impersonate="chrome")
    try:
        r = await s.get(SEARCH_PAGE_URL, timeout=30)
    except Exception as exc:
        log.warning("bid4assets.token_page_fail", error=str(exc)[:200])
        return s, None
    if r.status_code != 200 or not r.text:
        log.warning("bid4assets.token_page_bad_status", status=r.status_code)
        return s, None
    m = _TOKEN_RE.search(r.text)
    return s, (m.group(1) if m else None)


async def _fetch_state(s, token: str, state: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    headers = {**_HEADERS, "X-CSRF-Header-Token": token}

    for page in range(1, PAGES_CAP + 1):
        skip = (page - 1) * PAGE_SIZE
        body = _build_body(state, page)
        url = f"{API_URL}?take={PAGE_SIZE}&skip={skip}&page={page}&pageSize={PAGE_SIZE}"
        try:
            r = await s.post(url, json=body, headers=headers, timeout=30)
        except Exception as exc:
            log.warning("bid4assets.fetch_failed", state=state, page=page, error=str(exc)[:200])
            break
        if r.status_code != 200:
            log.warning("bid4assets.bad_status", state=state, page=page, code=r.status_code)
            break
        try:
            data = r.json()
        except Exception:
            log.warning("bid4assets.bad_json", state=state, page=page)
            break

        rows = data.get("data") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            li = _to_listing(row, state, slug)
            if li is not None:
                out.append(li)

        total = data.get("total") or 0
        log.info("bid4assets.page_done", state=state, page=page,
                 rows=len(rows), running=len(out), total=total)
        if len(rows) < PAGE_SIZE or len(out) >= total:
            break

    return out


class Bid4Assets(BaseScraper):
    slug = "national.bid4assets"
    name = "Bid4Assets (county tax-deed-sale notices)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            s, token = await _get_session_and_token()
        except Exception as exc:
            log.warning("bid4assets.session_fail", error=str(exc)[:200])
            return out

        if not token:
            log.warning("bid4assets.no_token")
            try:
                await s.close()
            except Exception:
                pass
            return out

        try:
            for state in STATES:
                try:
                    rows = await _fetch_state(s, token, state, self.slug)
                    out.extend(rows)
                    log.info("bid4assets.state_done", state=state, count=len(rows))
                except Exception as exc:
                    log.warning("bid4assets.state_failed", state=state, error=str(exc)[:200])
        finally:
            try:
                await s.close()
            except Exception:
                pass

        log.info("bid4assets.done", count=len(out))
        return out
