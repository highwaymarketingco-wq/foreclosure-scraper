"""Zacchaeus Legal Services (ZLS) — NC tax foreclosures.

https://www.zls-nc.com/listings is a Blazor Server app. A one-time
"I AGREE" disclaimer button gates the listings (same consent pattern as
aldridge_pite's disclaimer Referer, but here it is a real in-page button).
After the click, a DevExpress Blazor grid renders its rows over WebSocket.

A plain GET (curl/httpx) returns only the Blazor error placeholder
("An error has occurred. This application may no longer respond..."), so
this scraper drives a real stealth browser (Scrapling StealthyFetcher,
the same render tier mcmichael_taylor_gray uses): load -> click I AGREE ->
wait for the grid -> page through every page collecting rows.

Grid columns (verified live 2026-06-26):
  0 Tax Office (county)   1 Parcel #   2 Status   3 Sale Date
  4 Upset Bidding Deadline   5 Opening Bid   6 Current Bid
  7 Notice (link)   8 Address ("⚠️ STREET, CITY, NC ZIP")   9 (empty)

There is NO case-number column. The grid is paginated (~11 rows/page,
~21 pages); we click the "Next page" pager button until it disables.

STATUS FILTER: emit only still-actionable leads. A property whose status
shows it is paid off (Redeemed) or already sold (Sale Confirmed / Deed
Recorded) is not a lead and is dropped. Everything else — upset bidding,
courthouse sale, pending confirmation, scheduled/upcoming — is emitted.
The raw status is always stashed in raw["zls"]["status"].
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

LISTINGS_URL = "https://www.zls-nc.com/listings"

# Pager "Next page" button (DevExpress Blazor). Disabled state adds dxbl-disabled.
_NEXT_SEL = (
    ".dxbl-grid-pager button[aria-label='Next page'], "
    ".dxbl-pager button[aria-label='Next page']"
)

# Status substrings that mark a DEAD lead (paid off or already sold) -> dropped.
# Matched case-insensitively as substrings so the combined grid value
# "Sale Confirmed / Deed Recorded" is caught.
_DEAD_STATUS_MARKERS = ("redeemed", "sale confirmed", "deed recorded")

_ADDR_TAIL_RE = re.compile(
    r"^(.*?),\s*([A-Za-z .'-]+?),?\s+([A-Z]{2}),?\s+(\d{5})(?:-\d{4})?\s*$"
)
_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _clean_money(raw: str | None) -> float | None:
    """'$7,750.00' -> 7750.0 ; 'n/a'/'' -> None."""
    if not raw:
        return None
    m = _BID_RE.search(raw)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v <= 50_000_000 else None


def _parse_date(raw: str | None) -> datetime | None:
    raw = (raw or "").strip()
    if not raw or raw.lower() in ("n/a", "na", "-"):
        return None
    try:
        return dateparser.parse(raw)
    except (ValueError, TypeError, OverflowError):
        return None


def _clean_county(office: str | None) -> str | None:
    """'Onslow County Tax Office' -> 'Onslow'."""
    if not office:
        return None
    s = re.sub(r"\s+tax\s+office\s*$", "", office, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+county\s*$", "", s, flags=re.IGNORECASE).strip()
    return s or None


def _clean_address(raw: str | None) -> str | None:
    """Strip the '⚠️ ' warning prefix the grid prepends to each address."""
    if not raw:
        return None
    s = raw.replace("⚠️", "").replace("⚠", "").strip()
    return s or None


def _is_dead(status: str | None) -> bool:
    s = (status or "").lower()
    return any(m in s for m in _DEAD_STATUS_MARKERS)


def _row_to_listing(row: dict, slug: str) -> Listing | None:
    """Convert one captured grid row dict into a Listing, or None to drop.

    Drops rows that are missing a parcel AND an address (empty/placeholder
    rows) and rows whose status marks them dead (paid off / already sold)."""
    status = (row.get("status") or "").strip() or None
    if _is_dead(status):
        return None

    county = _clean_county(row.get("office"))
    parcel = (row.get("parcel") or "").strip() or None
    addr_full = _clean_address(row.get("addr"))
    if not parcel and not addr_full:
        return None  # empty grid row, nothing to key on

    # Address comes as "STREET, CITY, NC ZIP" (or just a street). Split out
    # city/zip when it parses, else keep the whole thing as the street.
    street = city = zip_code = None
    if addr_full:
        m = _ADDR_TAIL_RE.match(addr_full)
        if m:
            street, city, _st, zip_code = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            street = addr_full

    zls_raw = {
        "status": status,
        "upset_deadline": (row.get("upset") or "").strip() or None,
        "current_bid": (row.get("current_bid") or "").strip() or None,
        "notice_url": (row.get("notice_url") or "").strip() or None,
    }

    return Listing(
        source=slug,
        source_url=LISTINGS_URL,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        parcel_id=parcel,
        street_address=street,
        city=city,
        zip_code=zip_code,
        sale_date=_parse_date(row.get("sale")),
        upset_bid_deadline=_parse_date(row.get("upset")),
        opening_bid=_clean_money(row.get("opening_bid")),
        auction_status=status,
        foreclosure_process="tax",
        description=(
            f"ZLS NC tax foreclosure — {county or ''} parcel {parcel or ''}"
            f" ({status or 'status n/a'})"
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"zls": zls_raw},
    )


# JS run inside the rendered page: read every data row of the current grid
# page into a flat dict (text + the Notice link href).
_GRID_JS = """
() => {
  const rows = [...document.querySelectorAll('table.dxbl-grid-table tbody tr')];
  return rows.map(r => {
    const tds = [...r.querySelectorAll('td')];
    const txt = i => (tds[i] ? tds[i].innerText.trim() : '');
    let notice = '';
    if (tds[7]) {
      const a = tds[7].querySelector('a[href]');
      if (a) notice = a.href;
    }
    return {
      office: txt(0),
      parcel: txt(1),
      status: txt(2),
      sale: txt(3),
      upset: txt(4),
      opening_bid: txt(5),
      current_bid: txt(6),
      notice_url: notice,
      addr: txt(8),
    };
  });
}
"""


async def _fetch_rows() -> list[dict]:
    """Drive the Blazor grid: agree -> wait -> page through all pages.
    Returns raw row dicts (the parser drops dead/empty ones). [] on failure."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    captured: dict[str, list[dict]] = {"rows": []}

    async def page_action(page):
        # Blazor mounts over WebSocket after first paint — give it a beat,
        # then click the "I AGREE" consent button (NOT "I DO NOT AGREE").
        await page.wait_for_timeout(6000)
        await page.evaluate(
            """() => {
                for (const b of document.querySelectorAll('button')) {
                    if ((b.innerText || '').trim().toLowerCase() === 'i agree') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
        # Wait for the DevExpress grid to render its first rows.
        try:
            await page.wait_for_selector(
                "table.dxbl-grid-table tbody tr", timeout=45000
            )
        except Exception:
            return
        await page.wait_for_timeout(2500)

        seen: dict[tuple, dict] = {}
        for _ in range(60):  # hard cap; real grid is ~21 pages
            rows = await page.evaluate(_GRID_JS)
            for r in rows or []:
                key = (r.get("office"), r.get("parcel"), r.get("addr"), r.get("status"))
                if any(key):
                    seen[key] = r
            # Stop when the Next-page button is gone or disabled.
            disabled = await page.evaluate(
                "(s) => { const b = document.querySelector(s);"
                " return b ? b.className.includes('dxbl-disabled') : true; }",
                _NEXT_SEL,
            )
            if disabled:
                break
            await page.evaluate(
                "(s) => { const b = document.querySelector(s); if (b) b.click(); }",
                _NEXT_SEL,
            )
            await page.wait_for_timeout(2200)

        captured["rows"] = list(seen.values())

    try:
        await StealthyFetcher.async_fetch(
            LISTINGS_URL,
            headless=True,
            network_idle=False,
            timeout=300000,
            page_action=page_action,
            solve_cloudflare=False,
        )
    except Exception:
        return []
    return captured["rows"]


class Zacchaeus(BaseScraper):
    slug = "law_firms.zacchaeus"
    name = "Zacchaeus Legal Services (NC tax foreclosure, Blazor grid, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0  # actionable count varies with the sale cycle
    timeout_s = 360.0  # ~21 paged grid loads in a real browser

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for row in await _fetch_rows():
            li = _row_to_listing(row, self.slug)
            if li is not None:
                out.append(li)
        return out
