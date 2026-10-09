"""Xome auctions — now plain server-rendered HTML, no browser needed.

REWRITTEN 2026-10-01 (national-auction-tier audit, batch 4). The site was
redesigned since this scraper was last built:

  * The old URLs (`/auctions/bank-owned`, `/auctions/foreclosure-homes`)
    301-redirect to a single `/auctions?bank-owned` / `/auctions?foreclosure-
    homes` query-flag form (confirmed live: the flag genuinely filters —
    `?bank-owned` returns only "Bank Owned" cards, `?foreclosure-homes`
    only "Foreclosure Homes" cards). The third old URL,
    `/auctions/foreclosuresales`, is now a dead/empty category (200 OK,
    zero property cards) — replaced with the real `?non-bank-owned` flag.
  * Pagination is now a plain `&page=N` query param (confirmed live through
    page 164) instead of the old JS "click next, cards accumulate in the
    DOM" control — no more `#newPaginationHolder`/`#right-navigation`.
  * Card markup is a completely different (Next.js/SSR) structure:
    `[data-testid="auction-property-card-container"]` per card, with
    `[class*="addressLine1"]` / `[class*="addressLine2"]` text nodes, not
    the old `#streetAddress-{id}` id-per-field spans.
  * MOST IMPORTANTLY: confirmed live that a PLAIN httpx/curl_cffi GET (NO
    Scrapling, no headless browser, no page-click loop) already returns
    every card's full text content — address, price, beds/baths/sqft,
    transaction type, auction date, status, and flags (Cash Only/Reported
    Vacant/No Buyers Premium) are all in the raw server HTML. The old
    Scrapling StealthyFetcher + click-pagination approach is no longer
    needed at all, which also drops this source's runtime from a
    `timeout_s=600` full-browser multi-page-click session to a handful of
    fast plain GETs.

AUDITED, NOT WIRED on the CARD (search-results) page specifically, correctly
documented at the time: real listing photos DO exist on this site, but are
NOT present inside any card's own HTML on the search-results page (0 of 96
cards on a sampled page had an image URL inside their own card boundary) --
the card only ships an "animate-pulse" skeleton placeholder server-side.

FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5),
confirmed live, extending the above rather than contradicting it: each
listing's own DETAIL page (already captured as source_url, never fetched)
DOES carry a real, server-rendered JSON state blob -- the prior audit's "no
embedded __NEXT_DATA__/JSON state blob" finding was true of the classic
`<script id="__NEXT_DATA__">` tag specifically, but this Next.js app-router
site streams its data instead via `self.__next_f.push([n, "<escaped-json>"])`
chunks, confirmed live on 2 real current detail pages (plain curl-cffi
impersonation, no stealth browser) to carry, double-JSON-escaped but
reliably regex-extractable: the FULL `photos` array (2 real
xomeauction.propertiescdn.com URLs on both samples, vs. 0 on the card), a
`documents` array (empty on both live samples but wired defensively -- a
real field on this payload, not invented), `publicRemarks` (the actual
property description -- "This property will be sold through the applicable
foreclosure auction process...", vs. the card's bare transaction-type text),
`buildingAreaTotal` (a real sqft figure, e.g. 2528 / 1524 on the 2 samples),
`auctionStartDate` (a precise ISO datetime, e.g.
"2026-10-05T10:00:00+00:00", vs. the card's loosely-parsed "Oct 03 - 06"
text), `liveAuctionLocationDescription` (the full in-person courthouse
address + alternate location), and -- the HERMES sec 9 #1 priority --
`fclrtName`/`fclrtPhone`/`fclrtAddress`/`fclrtCity`/`fclrtState`/`fclrtZip`,
the REAL foreclosure law firm/trustee conducting the sale with a direct
phone number (confirmed live: "Bell Carrington Price & Gregg, LLC",
"803-555-0714", a real NC/SC foreclosure firm this codebase's own
`law_firms.bell_carrington` scraper already tracks independently -- this is
free, zero-cost corroboration/contactability on every xome row). Wired as a
best-effort per-row detail fetch, capped at `DETAIL_FETCH_CAP` total across
the whole run (this site's real NC+SC volume across 3 categories x up to 20
pages is far too large to detail-fetch exhaustively every run -- same
"bounded, polite runtime" posture `PAGES_CAP` already uses).

Free, no login, no CAPTCHA/WAF challenge encountered.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.xome.com/auctions"
# Real, currently-live category flags (verified live 2026-10-01 -- each
# genuinely filters server-side to its own transaction type). The old third
# URL (`/auctions/foreclosuresales`) is now a dead/empty category.
CATEGORY_URLS = (
    f"{BASE}?bank-owned",
    f"{BASE}?foreclosure-homes",
    f"{BASE}?non-bank-owned",
)
_CORE_STATES = {"NC", "SC"}
PAGES_CAP = 20  # breadth cap, same posture as this batch's other national
                # sources (auction_dot_com PAGES_CAP=25, hibid PAGES_CAP=10)
                # -- ~15.7k listings site-wide across ~164 pages is too much
                # to exhaustively crawl every run; this trades completeness
                # for a bounded, polite runtime.
CARDS_PER_PAGE = 96  # observed live; used only to detect the last page

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_ADDR2_RE = re.compile(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$")
_ID_RE = re.compile(r"-(\d+)$")

# FOUND 2026-10-04 (batch 5, see module docstring): the detail page's Next.js
# RSC stream embeds a double-JSON-escaped state blob -- every field of
# interest appears as the literal text `\"key\":\"value\"` (string) or
# `\"key\":NNN` (number) inside the raw server HTML. Matched directly
# against the raw text (no need to locate/parse the enclosing `self.
# __next_f.push([...])` chunk) since every key name here is specific enough
# not to collide elsewhere on the page.
DETAIL_FETCH_CAP = 30  # total across the whole run -- same "bounded, polite
                       # runtime" posture PAGES_CAP already uses; real NC+SC
                       # volume across 3 categories x up to 20 pages is far
                       # too large to detail-fetch exhaustively every run.
_DETAIL_STR_FIELDS = (
    "fclrtName", "fclrtPhone", "fclrtAddress", "fclrtCity", "fclrtState",
    "fclrtZip", "liveAuctionLocationDescription", "liveAuctionStartTime",
    "auctionStartDate", "publicRemarks", "eventName", "bidType",
)
_DETAIL_NUM_FIELDS = ("buildingAreaTotal",)


def _detail_str_field(html: str, name: str) -> str | None:
    m = re.search(r'\\"' + re.escape(name) + r'\\":\\"(.*?)\\"', html)
    if not m:
        return None
    try:
        return m.group(1).encode().decode("unicode_escape").strip() or None
    except (UnicodeDecodeError, UnicodeError):
        return m.group(1).strip() or None


def _detail_num_field(html: str, name: str) -> float | None:
    m = re.search(r'\\"' + re.escape(name) + r'\\":\s*(-?[\d.]+)', html)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _detail_array_field(html: str, name: str) -> list[str]:
    m = re.search(r'\\"' + re.escape(name) + r'\\":\[(.*?)\]', html)
    if not m or not m.group(1):
        return []
    out = []
    for item in re.findall(r'\\"(.*?)\\"', m.group(1)):
        try:
            out.append(item.encode().decode("unicode_escape"))
        except (UnicodeDecodeError, UnicodeError):
            out.append(item)
    return out


async def _fetch_detail(detail_url: str) -> dict:
    """Best-effort enrichment from a xome.com listing's own detail page.
    Returns {} on any failure -- callers must treat this as optional."""
    out: dict = {}
    try:
        html = await get_text(detail_url, impersonate=True, timeout=20.0)
    except Exception as exc:
        log.warning("xome.detail_fetch_fail", url=detail_url, error=str(exc)[:160])
        return out
    if not html or len(html) < 5000:
        return out
    try:
        for name in _DETAIL_STR_FIELDS:
            val = _detail_str_field(html, name)
            if val is not None:
                out[name] = val
        for name in _DETAIL_NUM_FIELDS:
            val = _detail_num_field(html, name)
            if val is not None:
                out[name] = val
        photos = _detail_array_field(html, "photos")
        if photos:
            out["photos"] = [p.split("?")[0] for p in photos]
        documents = _detail_array_field(html, "documents")
        if documents:
            out["documents"] = documents
    except Exception as exc:  # noqa: BLE001
        log.warning("xome.detail_parse_fail", url=detail_url, error=str(exc)[:160])
    return out


def _ltype(text: str) -> ListingType:
    s = (text or "").lower()
    if "bank owned" in s or "reo" in s:
        return ListingType.REO
    if "foreclosure" in s and "pre" not in s:
        return ListingType.FORECLOSURE_SALE
    if "pre-foreclosure" in s or "pre foreclosure" in s:
        return ListingType.LIS_PENDENS
    return ListingType.AUCTION  # default — Xome is auction-first


def _parse_card(card, slug: str) -> Listing | None:
    link_el = card.css_first('a[href^="/auctions/"]')
    href = (link_el.attributes.get("href") or "").strip() if link_el else ""
    if not href:
        return None

    addr1_el = card.css_first('[class*="addressLine1"]')
    addr2_el = card.css_first('[class*="addressLine2"]')
    street = addr1_el.text(strip=True) if addr1_el else None
    addr2 = addr2_el.text(strip=True) if addr2_el else ""
    if not street or not addr2:
        return None

    m = _ADDR2_RE.match(addr2)
    if not m:
        return None
    city, state, zip_code = m.group(1).strip(), m.group(2).upper(), m.group(3)
    if state not in _CORE_STATES:
        return None

    amt_el = card.css_first('[data-testid="property-card-amt"] p')
    amt_text = amt_el.text(strip=True) if amt_el else ""
    price = None
    pm = _PRICE_RE.search(amt_text)
    if pm:
        try:
            price = float(pm.group(1).replace(",", ""))
        except ValueError:
            price = None

    type_el = card.css_first('[class*="transactionText"]')
    type_text = type_el.text(strip=True) if type_el else ""

    bb_el = card.css_first('[data-testid="property-card-beds-and-bath"]')
    beds = baths = sqft = None
    if bb_el is not None:
        bolds = [b.text(strip=True) for b in bb_el.css('[class*="detailBold"]')]
        bb_text = bb_el.text(separator=" ").lower()
        if "bed" in bb_text and bolds:
            try:
                beds = float(bolds[0])
            except (ValueError, IndexError):
                pass
        if "bath" in bb_text and len(bolds) > 1:
            try:
                baths = float(bolds[1])
            except ValueError:
                pass
        if "sq" in bb_text and len(bolds) > 2:
            try:
                sqft = float(bolds[2].replace(",", ""))
            except ValueError:
                pass

    date_el = card.css_first('[class*="timelineDate"]')
    auction_date_text = date_el.text(strip=True) if date_el else None
    status_el = card.css_first('[class*="primaryBoldText"]')
    status_text = status_el.text(strip=True) if status_el else None
    bidtype_el = card.css_first('[data-testid="property-card-bid-type"]')
    bid_type = bidtype_el.text(strip=True) if bidtype_el else None
    flags = [f.text(strip=True) for f in card.css('[class*="flagChipContent"]')]
    # The flag chip list repeats itself (an overflow "+1 More" duplicate
    # rendering) in the live markup -- de-dupe while preserving order.
    seen_flags: list[str] = []
    for fl in flags:
        if fl and fl not in seen_flags:
            seen_flags.append(fl)

    idm = _ID_RE.search(href)
    case_number = f"xome-{idm.group(1)}" if idm else f"xome-{href.strip('/').split('/')[-1]}"

    county = None
    try:
        from ..._upstate_city_to_county import upstate_county_for
        county = upstate_county_for(city, state)
    except Exception:  # noqa: BLE001
        pass

    def _flt(v):
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    return Listing(
        source=slug,
        source_url=f"https://www.xome.com{href}",
        listing_type=_ltype(type_text),
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        city=city,
        zip_code=zip_code,
        county=county,
        street_address=street,
        case_number=case_number,
        opening_bid=price,
        bedrooms=_flt(beds),
        bathrooms=_flt(baths),
        living_sqft=_flt(sqft),
        description=(type_text or "Xome auction").strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "xome": {
                "transaction_type": type_text or None,
                "auction_date_text": auction_date_text,
                "status_text": status_text,
                "bid_type": bid_type,
                "flags": seen_flags or None,
            },
        },
    )


async def _fetch_category(category_url: str, slug: str, pages_cap: int) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    for page in range(1, pages_cap + 1):
        url = category_url if page == 1 else f"{category_url}&page={page}"
        try:
            html = await get_text(url, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("xome.page_failed", url=url, error=str(exc)[:200])
            break
        if not html or len(html) < 5000:
            break

        tree = HTMLParser(html)
        cards = tree.css('[data-testid="auction-property-card-container"]')
        if not cards:
            break

        kept = 0
        for card in cards:
            try:
                li = _parse_card(card, slug)
            except Exception:
                continue
            if li is None:
                continue
            if li.source_url in seen:
                continue
            seen.add(li.source_url)
            out.append(li)
            kept += 1

        log.info("xome.page_done", url=category_url, page=page,
                 cards=len(cards), kept=kept, running=len(out))
        if len(cards) < CARDS_PER_PAGE:
            break  # last page

    return out


class Xome(BaseScraper):
    slug = "national.xome"
    name = "Xome (REO + foreclosure auctions, NC + SC)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    requires_render = False  # FIXED 2026-10-01: plain HTML now, no browser needed
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        seen: set[str] = set()
        for category_url in CATEGORY_URLS:
            try:
                rows = await _fetch_category(category_url, self.slug, PAGES_CAP)
            except Exception as exc:
                log.warning("xome.category_failed", url=category_url, error=str(exc)[:200])
                continue
            kept = 0
            for li in rows:
                k = li.source_url or li.case_number
                if k in seen:
                    continue
                seen.add(k)
                out.append(li)
                kept += 1
            log.info("xome.category_done", url=category_url, found=len(rows), kept=kept)

        # FOUND 2026-10-04 (batch 5, see module docstring): each row's own
        # detail page carries a free photo gallery, a real description,
        # precise auction timing, and the foreclosure firm's name + direct
        # phone -- capped at DETAIL_FETCH_CAP total (not per-category) since
        # this source's real NC+SC volume is far larger than that cap.
        detail_fetches = 0
        for li in out:
            if detail_fetches >= DETAIL_FETCH_CAP:
                break
            detail_fetches += 1
            try:
                detail = await _fetch_detail(li.source_url)
            except Exception as exc:  # noqa: BLE001
                log.warning("xome.detail_enrich_failed", url=li.source_url, error=str(exc)[:160])
                continue
            if not detail:
                continue
            photos = detail.get("photos")
            if photos:
                li.raw.setdefault("images", {})["real"] = photos
            remarks = detail.get("publicRemarks")
            if remarks:
                li.description = remarks
            area = detail.get("buildingAreaTotal")
            if area and not li.living_sqft:
                li.living_sqft = area
            xome_ns = li.raw.setdefault("xome", {})
            xome_ns["trustee_name"] = detail.get("fclrtName")
            xome_ns["trustee_phone"] = detail.get("fclrtPhone")
            xome_ns["trustee_address"] = ", ".join(
                p for p in (detail.get("fclrtAddress"), detail.get("fclrtCity"),
                            detail.get("fclrtState"), detail.get("fclrtZip")) if p
            ) or None
            xome_ns["live_auction_location"] = detail.get("liveAuctionLocationDescription")
            xome_ns["live_auction_start_time"] = detail.get("liveAuctionStartTime")
            xome_ns["auction_start_date_iso"] = detail.get("auctionStartDate")
            xome_ns["event_name"] = detail.get("eventName")
            if detail.get("documents"):
                xome_ns["documents"] = detail["documents"]
        log.info("xome.detail_enrichment_done", attempted=detail_fetches, total_rows=len(out))
        return out
