"""Stokes County NC - tax foreclosure sales (via the Kania Law Firm statewide table).

FIXED 2026-10-01 (HERMES sec 8 per-source audit). The county's OWN page
(``co.stokes.nc.us/departments/foreclosures.php``) carries no table and no
data at all -- live-read, its full body is one paragraph: 'Stokes County
foreclosures can be found by searching "Stokes" in the search box... Public
auctions are held at the Stokes County Courthouse... For upset bid
information, please contact the Stokes County Clerk of Court's Office...'
followed by a link to ``https://kanialawfirm.com/tax-foreclosures/
foreclosure-listings/``. The old scraper pointed its `<tr>` regex at this
dead-end page and always got 0 rows -- a clean-looking but WRONG zero, not a
real "no foreclosures this week" result (the county's own page footer text
even explains the sale venue, which only makes sense if sales are actually
happening).

Kania Law Firm's listings page renders its table with a WordPress "Ninja
Tables" plugin: the static HTML carries no rows at all, only a ``<div
data-footable_id="...">`` placeholder loaded client-side via
``/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id
=<id>&target_action=get-all-data&...&ninja_table_public_nonce=<nonce>``. Both
``table_id`` and the nonce are embedded in the page's own inline JS
(``data_request_url`` inside the table's init JSON) and read fresh every run
-- WordPress nonces rotate, so a hard-coded one would eventually 403/bad-token.
No login, no CAPTCHA, no WAF: a plain GET of the page, then a plain GET of
the AJAX action with the nonce it just handed us.

THE TABLE IS STATEWIDE, NOT STOKES-ONLY. Verified live 2026-10-01: 190 rows
across 24 NC counties (Alexander, Alleghany, Anson, Ashe, Burke, Caldwell,
Catawba, Cherokee, Clay, Cleveland, Davidson, Davie, Harnett, Lincoln,
Mecklenburg, Montgomery, New Hanover, Person, Polk, Rowan, Rutherford,
Stokes, Surry, Union) -- Kania is apparently the trustee/attorney for tax
foreclosure sales across a big swath of the state, Cherokee County's own page
points at the SAME firm (see counties_nc.nc_civicplus_tax_sale's
``_parse_case_table_blocks``, a different page/format for the same firm).
This module filters to county == "Stokes" only, matching its slug/footprint;
Burke/Cleveland/Lincoln/Polk/Rutherford also appear in the table but already
have dedicated scrapers and are deliberately left to those (cross-checking
this statewide table against them is a separate, bigger job, not in scope
here -- see docs/HANDOFF.md).

A ROW'S FIELDS (JSON, one dict per sale): county, address, parcel,
saledatetime, openingbid, currentbid, closedate, propertytype, courtfile
(the court file / case number), ourfile (Kania's own internal file number,
kept as provenance, not shown to the user), salestatus. address/parcel can
each carry MULTIPLE ``<br />``-joined values when one sale covers more than
one combined parcel (Rutherford's "SALE INCLUDES BOTH PARCELS" pattern, see
nc_county_tax_foreclosure.py) -- every value is kept in raw, and the first
value that looks like a real street address (starts with a house number)
is used for street_address; a value like "(0000041) NC 90 HWY E, Stony
Point" (a bare parcel-in-parens + a road name, no house number -- a vacant
lot) falls back to legal_description instead of a fabricated street_address.
``saledatetime`` is sometimes the literal HTML
``<span class='red'>Sale date not yet set</span>`` -- NOT a date, parsed to
None rather than fed to dateutil (which would otherwise raise or, worse,
silently extract today's date from the span's absence of digits).

Free, public, no login, no CAPTCHA.
Slug: counties_nc.stokes_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

LISTINGS_PAGE = "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/"
AJAX_BASE = "https://kanialawfirm.com/wp-admin/admin-ajax.php"
TARGET_COUNTY = "Stokes"

# The table's init JSON embeds the live request URL verbatim, e.g.:
#   "data_request_url":"https:\/\/kanialawfirm.com\/wp-admin\/admin-ajax.php?
#    action=wp_ajax_ninja_tables_public_action&table_id=216745&target_action=
#    get-all-data&default_sorting=old_first&skip_rows=0&limit_rows=0&
#    ninja_table_public_nonce=51009e94c7"
# Escaped forward slashes (\/) are JSON-valid but re won't see them as such
# inside a plain string match, so unescape before searching.
_DATA_REQUEST_URL_RE = re.compile(
    r'"data_request_url"\s*:\s*"([^"]+)"'
)

_HOUSE_NUM_RE = re.compile(r"^\s*\d")


def _clean(s: Any) -> Optional[str]:
    if s is None:
        return None
    s = _html.unescape(re.sub(r"<[^>]+>", " ", str(s)))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _split_br(raw: Any) -> list[str]:
    """Split a Ninja Tables cell on its literal '<br />' joins into clean
    values, dropping empties. Used for address/parcel, which carry more than
    one value on a combined-parcel sale."""
    if not raw:
        return []
    parts = re.split(r"<br\s*/?>", str(raw))
    return [v for v in (_clean(p) for p in parts) if v]


def _money(s: Any) -> Optional[float]:
    s = _clean(s)
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        return None
    try:
        v = float(digits)
    except ValueError:
        return None
    return v or None


def _date(s: Any) -> Optional[datetime]:
    s = _clean(s)
    if not s or "not yet set" in s.lower():
        return None
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(s)
    except (ValueError, TypeError, OverflowError):
        return None


async def _find_ajax_url(page_html: str) -> Optional[str]:
    m = _DATA_REQUEST_URL_RE.search(page_html)
    if not m:
        return None
    url = m.group(1).replace("\\/", "/")
    return _html.unescape(url)


def parse_rows(data: list[dict], county: str, page_url: str) -> list[Listing]:
    out: list[Listing] = []
    now = datetime.utcnow()
    for entry in data:
        v = entry.get("value") or {}
        if (v.get("county") or "").strip().lower() != county.lower():
            continue

        addresses = _split_br(v.get("address"))
        parcels = _split_br(v.get("parcel"))
        # A real street address starts with a house number; "(12345) Road
        # Name, Town" and "Multiple Parcels" don't, and fall back to the
        # legal description instead of a fabricated street_address.
        street = next((a for a in addresses if _HOUSE_NUM_RE.match(a)), None)
        legal = None if street else (addresses[0] if addresses else None)
        # City is the text after the last comma in whichever address we kept.
        city = None
        src_addr = street or legal
        if src_addr and "," in src_addr:
            city = src_addr.rsplit(",", 1)[-1].strip() or None

        case_number = _clean(v.get("courtfile"))
        parcel_id = parcels[0] if parcels else None
        sale_date = _date(v.get("saledatetime"))
        opening_bid = _money(v.get("openingbid"))
        current_bid = _money(v.get("currentbid"))
        close_date = _date(v.get("closedate"))
        property_type = _clean(v.get("propertytype")) or ""
        status = _clean(v.get("salestatus"))

        kind = PropertyKind.UNKNOWN
        pt = property_type.lower()
        if "vacant" in pt or "land" in pt:
            kind = PropertyKind.LAND
        elif "home" in pt or "residential" in pt:
            kind = PropertyKind.SINGLE_FAMILY
        elif "commercial" in pt:
            kind = PropertyKind.COMMERCIAL

        desc_bits = [property_type] if property_type else []
        if len(addresses) > 1:
            desc_bits.append(f"{len(addresses)} combined parcels")
        if status:
            desc_bits.append(f"status: {status}")
        description = f"{county} County NC tax foreclosure" + (
            f" — {' — '.join(desc_bits)}" if desc_bits else "")

        out.append(Listing(
            source="counties_nc.stokes_delinquent_tax",
            source_url=page_url,
            listing_type=ListingType.TAX_SALE,
            property_kind=kind,
            state="NC",
            county=county,
            street_address=street,
            city=city,
            legal_description=legal,
            parcel_id=parcel_id,
            case_number=case_number,
            sale_date=sale_date,
            opening_bid=opening_bid,
            description=description[:400],
            first_seen=now,
            last_seen=now,
            raw={
                "stokes_delinquent_tax": {
                    "addresses": addresses,
                    "parcels": parcels,
                    "property_type": property_type or None,
                    "sale_status": status,
                    "current_bid": current_bid,
                    "close_date": close_date.date().isoformat() if close_date else None,
                    "kania_file": _clean(v.get("ourfile")),
                    "kania_row_id": v.get("___id___"),
                }
            },
        ))
    return out


class StokesDelinquentTax(BaseScraper):
    slug = "counties_nc.stokes_delinquent_tax"
    name = "Stokes County NC Tax Foreclosures (Kania Law Firm statewide table)"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        try:
            page_html = await get_text(LISTINGS_PAGE, impersonate=True, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("stokes_tax.page_fail", error=str(exc)[:160])
            return []
        if not page_html or len(page_html) < 500:
            log.warning("stokes_tax.page_empty")
            return []

        ajax_url = await _find_ajax_url(page_html)
        if not ajax_url:
            log.warning("stokes_tax.ajax_url_not_found",
                        note="Ninja Tables data_request_url not found -- page layout may have changed")
            return []

        try:
            payload = await get_text(ajax_url, impersonate=True, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("stokes_tax.ajax_fail", error=str(exc)[:160])
            return []
        if not payload:
            return []
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("stokes_tax.ajax_bad_json", error=str(exc)[:160],
                        note="nonce may have expired or table_id moved")
            return []
        if not isinstance(data, list):
            log.warning("stokes_tax.ajax_unexpected_shape", shape=type(data).__name__)
            return []

        out = parse_rows(data, TARGET_COUNTY, LISTINGS_PAGE)
        log.info("stokes_tax.done", count=len(out), total_statewide_rows=len(data))
        return out
