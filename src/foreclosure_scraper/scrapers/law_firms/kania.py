"""Kania Law Firm — NC tax foreclosure sales (Ninja Tables JSON feed).

The Kania Law Firm (Asheville, NC) prosecutes in-rem / mortgage-style tax
foreclosures for ~25 NC counties and publishes every active parcel on one
page:

    https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/

VERIFIED LIVE 2026-07-31. The page itself contains NO rows — the visible
grid is a WordPress "Ninja Tables" widget whose markup is an empty
``<table>`` plus a ``<colgroup>``. Every row arrives from a separate
public admin-ajax endpoint that the page embeds as ``data_request_url``:

    /wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action
        &table_id=<id>&target_action=get-all-data
        &default_sorting=old_first&skip_rows=0&limit_rows=0

That endpoint is free, public, unauthenticated JSON — plain httpx gets a
200 (no Cloudflare challenge, no login, no CAPTCHA, and the
``ninja_table_public_nonce`` query arg is not enforced). We still read the
listings page first so the table id and request URL are discovered from
the live page rather than pinned, then GET the JSON.

WHY THE REWRITE: the previous version tried to regex property rows out of
the page HTML across six speculative parser paths. Against the live page
that yields exactly ONE "listing" — the firm's own office address, scraped
out of the LocalBusiness JSON-LD block in the footer. Real yield was zero
and the board got a junk row. The per-county sub-page URLs it crawled
(``/tax-foreclosures/<county>/``) are 404 or redirect back to a table-less
marketing page; there is exactly one Ninja Table on the whole site.

Row schema (column keys as published):
    county  address  parcel  saledatetime  openingbid  currentbid
    closedate  propertytype  courtfile  ourfile  salestatus

Notes on the data:
  * ``county`` is an authoritative column — never regex the county out of
    free text.
  * ``address`` / ``parcel`` are ``<br />``-joined when one court file
    covers several parcels. We split them into one Listing per parcel so
    each property is its own lead.
  * ``saledatetime`` is either "M/D/YYYY h:mm:ss AM" or the literal
    ``<span class='red'>Sale date not yet set</span>``. ~60% of rows are
    not yet scheduled — those are the EARLIEST leads, so the scraper keeps
    them (``law_firms.kania`` must be in main.DATELESS_OK_SOURCES or
    _active_only drops them all).
  * ``closedate`` is the upset-bid close date.
  * ``courtfile`` is the county court file number (e.g. 25CV003791-220).
  * There is NO owner / taxpayer name column — Kania does not publish it.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._footprint import in_footprint, is_coastal

LISTINGS_URL = "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/"

#: Fallback table id, used only when the live page stops exposing one.
DEFAULT_TABLE_ID = "216745"

#: Built from the table id when the page's own ``data_request_url`` can't be
#: read. ``limit_rows=0`` means "no limit" in Ninja Tables.
_AJAX_TEMPLATE = (
    "https://kanialawfirm.com/wp-admin/admin-ajax.php"
    "?action=wp_ajax_ninja_tables_public_action&table_id={table_id}"
    "&target_action=get-all-data&default_sorting=old_first"
    "&skip_rows=0&limit_rows=0"
)

_DATA_REQUEST_RE = re.compile(r'"data_request_url"\s*:\s*"([^"]+)"')
_FOOTABLE_ID_RE = re.compile(r'data-footable_id="(\d+)"')

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d{1,2})?)")
#: Some addresses are prefixed with their own parcel id in parens, e.g.
#: "(0000041) NC 90 HWY E, Stony Point".
_LEADING_PARCEL_RE = re.compile(r"^\(\s*([A-Za-z0-9\-\.]+)\s*\)\s*")
#: "578 E. Settings Blvd. NW, Valdese" -> street / city. Trailing comma with
#: no city ("2092 Brent Street,") leaves city None.
_ADDR_SPLIT_RE = re.compile(r"^(.*?),\s*([A-Za-z][A-Za-z .'-]*)$")

#: Placeholder text Kania uses when a filing covers too many parcels to list.
_PLACEHOLDER_VALUES = {"", "multiple", "multiple parcels", "n/a", "na", "-", "tbd"}

#: propertytype column -> PropertyKind.
_KIND_BY_TYPE = {
    "residential home": PropertyKind.SINGLE_FAMILY,
    "residential vacant lot": PropertyKind.LAND,
    "acreage": PropertyKind.LAND,
    "commercial improved": PropertyKind.COMMERCIAL,
    "commercial vacant lot": PropertyKind.LAND,
    "mixed": PropertyKind.MIXED,
}

#: Set KANIA_ALL_COUNTIES=1 to emit every county Kania publishes (used for
#: coverage audits). Default applies the same parse-time geo gate the other
#: statewide trustee-firm calendars use (footprint ∪ coastal), so the run
#: doesn't drag ~170 out-of-scope properties through dedupe and every
#: enrichment just to have main._in_scope drop them at the end.
_ALL_COUNTIES_ENV = "KANIA_ALL_COUNTIES"


def _emit_all_counties() -> bool:
    return os.getenv(_ALL_COUNTIES_ENV, "").strip().lower() in ("1", "true", "yes")


def _strip_tags(raw: str | None) -> str:
    """'<span class=\\'red\\'>Sale date not yet set</span>' -> plain text."""
    if not raw:
        return ""
    return _TAG_RE.sub(" ", raw).replace("&nbsp;", " ").strip()


def _split_cell(raw: str | None) -> list[str]:
    """Split a ``<br />``-joined cell into its parts, tags stripped."""
    if not raw:
        return []
    return [p for p in (_strip_tags(x) for x in _BR_RE.split(raw)) if p]


def _is_placeholder(value: str | None) -> bool:
    return (value or "").strip().lower() in _PLACEHOLDER_VALUES


def _clean_money(raw: str | None) -> Optional[float]:
    """'$12,500.00' -> 12500.0. Blank / unparseable / absurd -> None."""
    text = _strip_tags(raw)
    if not text:
        return None
    m = _MONEY_RE.search(text.replace("$", ""))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # Tax-sale opening bids are the delinquency + costs; anything under $10
    # is a stray fee and anything over $5M isn't a NC tax parcel.
    return value if 10.0 <= value <= 5_000_000.0 else None


def _parse_date(raw: str | None) -> Optional[datetime]:
    """'5/5/2026 11:00:00 AM' -> datetime. 'Sale date not yet set' -> None."""
    text = _strip_tags(raw)
    if not text or not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", text):
        return None
    try:
        return dateparser.parse(text)
    except (ValueError, TypeError, OverflowError):
        return None


def _sale_time(raw: str | None) -> Optional[str]:
    """Pull the clock time out of '5/5/2026 11:00:00 AM'."""
    text = _strip_tags(raw)
    m = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))\b", text, re.I)
    return m.group(1).upper() if m else None


def _clean_county(raw: str | None) -> Optional[str]:
    c = re.sub(r"\s+county\s*$", "", (raw or "").strip(), flags=re.I).strip()
    return c or None


def _split_address(raw: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'(0000041) NC 90 HWY E, Stony Point' -> (street, city, inline_parcel)."""
    text = (raw or "").strip()
    if not text or _is_placeholder(text):
        return None, None, None
    inline_parcel = None
    m = _LEADING_PARCEL_RE.match(text)
    if m:
        inline_parcel = m.group(1)
        text = text[m.end():].strip()
    text = text.rstrip(",").strip()
    if not text:
        return None, None, inline_parcel
    m = _ADDR_SPLIT_RE.match(text)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None, inline_parcel
    return text, None, inline_parcel


def _pair_up(addresses: list[str], parcels: list[str]) -> list[tuple[str, str]]:
    """Zip the <br />-joined address + parcel cells into per-property pairs.

    They are normally the same length. When they aren't (one address, three
    parcels, or vice versa) we pad with "" rather than dropping data — a
    parcel with no address is still a resolvable lead, and an address with
    no parcel still geocodes.
    """
    n = max(len(addresses), len(parcels))
    if n == 0:
        return []
    if len(addresses) == 1 and len(parcels) > 1:
        addresses = addresses * n  # one street, several tax parcels
    return [
        (addresses[i] if i < len(addresses) else "",
         parcels[i] if i < len(parcels) else "")
        for i in range(n)
    ]


def _row_to_listings(value: dict, slug: str) -> list[Listing]:
    """Expand one Ninja Tables row into one Listing per parcel."""
    county = _clean_county(value.get("county"))
    if not county:
        return []
    if not _emit_all_counties() and not (
        in_footprint(county, "NC") or is_coastal(county, "NC")
    ):
        return []

    addresses = _split_cell(value.get("address"))
    parcels = _split_cell(value.get("parcel"))
    # "Multiple Parcels" / "Multiple" carry no per-property detail — keep the
    # filing as a single county-level lead rather than dropping it.
    addresses = [a for a in addresses if not _is_placeholder(a)]
    parcels = [p for p in parcels if not _is_placeholder(p)]

    sale_date = _parse_date(value.get("saledatetime"))
    sale_time = _sale_time(value.get("saledatetime"))
    upset_deadline = _parse_date(value.get("closedate"))
    opening_bid = _clean_money(value.get("openingbid"))
    current_bid = _clean_money(value.get("currentbid"))
    case_number = (_strip_tags(value.get("courtfile")) or None)
    prop_type = _strip_tags(value.get("propertytype"))
    kind = _KIND_BY_TYPE.get(prop_type.lower(), PropertyKind.UNKNOWN)
    status = _strip_tags(value.get("salestatus")) or None
    if not status:
        status = "upset_bidding" if upset_deadline else (
            "scheduled" if sale_date else "pending_sale_date"
        )

    raw_common = {
        "kania": {
            "our_file": _strip_tags(value.get("ourfile")) or None,
            "court_file": case_number,
            "property_type": prop_type or None,
            "current_bid": current_bid,
            "sale_status": _strip_tags(value.get("salestatus")) or None,
            "row_id": value.get("___id___"),
        }
    }

    out: list[Listing] = []
    for addr_text, parcel_text in _pair_up(addresses, parcels) or [("", "")]:
        street, city, inline_parcel = _split_address(addr_text)
        parcel = (parcel_text or inline_parcel or "").strip() or None
        if not street and not parcel and not case_number:
            continue
        out.append(
            Listing(
                source=slug,
                source_url=LISTINGS_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=kind,
                state="NC",
                county=county,
                street_address=street,
                city=city,
                parcel_id=parcel,
                sale_date=sale_date,
                sale_time=sale_time,
                upset_bid_deadline=upset_deadline,
                opening_bid=opening_bid,
                auction_status=status,
                foreclosure_process="tax",
                case_number=case_number,
                land_use=prop_type or None,
                description=(
                    f"Kania Law Firm NC tax foreclosure — {county} County"
                    f"{' parcel ' + parcel if parcel else ''}"
                    f"{' (' + prop_type + ')' if prop_type else ''}"
                ),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw=dict(raw_common),
            )
        )
    return out


def parse_rows(payload: list | str, slug: str = "law_firms.kania") -> list[Listing]:
    """Turn the admin-ajax JSON body (or already-decoded list) into Listings."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if not isinstance(payload, list):
        return []
    out: list[Listing] = []
    seen: set[tuple] = set()
    for row in payload:
        value = row.get("value") if isinstance(row, dict) else None
        if not isinstance(value, dict):
            continue
        for li in _row_to_listings(value, slug):
            key = (
                (li.county or "").upper(),
                (li.parcel_id or "").upper(),
                (li.street_address or "").upper(),
                (li.case_number or "").upper(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(li)
    return out


def extract_data_request_url(html: str) -> Optional[str]:
    """Read the Ninja Tables AJAX URL the listings page embeds.

    Falls back to building it from ``data-footable_id`` so a table-id change
    on Kania's side doesn't silently zero the source.
    """
    if not html:
        return None
    m = _DATA_REQUEST_RE.search(html)
    if m:
        # The URL is embedded inside a JSON blob, so its slashes arrive as
        # "\/". Re-decoding it as a JSON string is the correct unescape.
        try:
            url = json.loads(f'"{m.group(1)}"')
        except ValueError:
            url = m.group(1).replace("\\/", "/")
        # Force "all rows" regardless of what the page's paging config asked for.
        url = re.sub(r"limit_rows=\d+", "limit_rows=0", url)
        url = re.sub(r"skip_rows=\d+", "skip_rows=0", url)
        return urljoin(LISTINGS_URL, url)
    m = _FOOTABLE_ID_RE.search(html)
    if m:
        return _AJAX_TEMPLATE.format(table_id=m.group(1))
    return None


class KaniaLawFirm(BaseScraper):
    slug = "law_firms.kania"
    name = "Kania Law Firm (NC tax foreclosures)"
    category = "law_firm"
    expected_min_count = 1
    timeout_s = 120.0  # two plain GETs
    requires_render = False  # public JSON endpoint; no browser needed

    async def fetch(self) -> Iterable[Listing]:
        data_url = _AJAX_TEMPLATE.format(table_id=DEFAULT_TABLE_ID)
        try:
            html = await get_text(LISTINGS_URL, timeout=45.0, impersonate=True)
        except Exception:
            html = ""
        discovered = extract_data_request_url(html)
        if discovered:
            data_url = discovered

        body = await get_text(
            data_url, timeout=60.0, referer=LISTINGS_URL, impersonate=True
        )
        return parse_rows(body, self.slug)
