"""NC upset-bid capture — properties currently inside the 10-day upset window.

WHAT AN UPSET BID IS. After a NC foreclosure sale (power-of-sale under NCGS
§45-21.27, or a tax foreclosure under §105-374), the high bid is reported to
the clerk of superior court and a 10-day upset period opens. Anyone may raise
the bid by the greater of 5% or $750; every successful upset RESTARTS a fresh
10-day clock. So a property sold in early July can still be open for bidding
in August — the published close date is authoritative and is NOT
``sale_date + 10 days``. This is the single most actionable window an investor
gets: the price is public, the deadline is public, and the property is still
winnable without an auction.

WHY THE OLD VERSION RETURNED ZERO. It crawled four county clerk landing pages
(``taxforeclosures.buncombenc.gov/``, ``hendersoncountync.gov/clerk``,
``clevelandcounty.com/``, ``gastoncountync.gov/.../clerk_of_court``) and
regex-scraped whatever HTML came back. Probed live 2026-08: two of the four
are hard 404 (Henderson ``/clerk``; the Gaston path, which now redirects to
``gastongov.com`` and 404s there), and the two that do return 200 are
JS-driven marketing/portal shells whose landing HTML contains no sale rows at
all — the keyword link-walk then wandered into nav links. Nothing in that set
had ever published a machine-readable upset-bid table, so the source was
structurally incapable of a non-zero count regardless of parser quality. It is
replaced here with feeds that actually carry current bid + close date.

SOURCES (all free, public, unauthenticated, no login and no bot-defence
bypass of any kind):

1. Kania Law Firm's statewide NC tax-foreclosure grid. Kania prosecutes tax
   foreclosures for ~25 NC counties and publishes every active parcel through
   a WordPress Ninja Tables ``admin-ajax.php`` endpoint that its own
   robots.txt explicitly allows (``Allow: /wp-admin/admin-ajax.php``). The
   rows are NESTED — each element is ``{"options": {...}, "value": {...}}``
   and every published column lives under ``value``. Counting counties at the
   top level returns 0, which is the trap that hid this feed.
   Row keys: county address parcel saledatetime openingbid currentbid
   closedate propertytype courtfile ourfile salestatus.

2. County-published upset lists. Rutherford runs two pages under
   ``/foreclosure_information/``: an in-house (county-prosecuted) HTML table,
   and an outside-counsel page whose text blocks carry something no other
   source has — the OWNER NAME of record, alongside current bid, the minimum
   needed to upset, and the last day to bid. Both are plain server-rendered
   HTML. ``COUNTY_UPSET_PAGES`` is the extension point: any footprint county
   publishing either shape is one tuple away, and both parsers run against
   every page so the shape does not have to be declared.

RELATIONSHIP TO ``law_firms.kania``. That scraper reads the same Ninja Tables
feed and emits every in-footprint parcel as a plain TAX_SALE lead. This one is
narrower and deeper: it keeps only the rows in an actual upset posture and
promotes the bid economics to first-class fields. Overlapping rows collapse in
dedupe (same parcel key) and ``Listing.merge`` deep-merges ``raw``, so
``raw["upset_bid"]`` survives the merge and both sources are recorded in
``raw["also_seen_in"]``. Set ``NC_UPSET_ALL_ROWS=1`` to emit every
in-footprint feed row instead of only the upset-posture ones (coverage audits).

LISTING TYPE. ``models.ListingType`` has no ``upset_bid`` member, so these are
typed ``TAX_SALE`` — substantively correct (every row here is a tax
foreclosure) and identical to ``law_firms.kania`` so a dedupe merge cannot
flap the type. The upset posture is carried by ``auction_status`` and by
``raw["upset_bid"]``, which are both queryable and strictly more informative
than an enum member.

Dateless: many rows have a published close date but no scheduled sale date, so
``national.nc_upset_bids`` must stay in ``main.DATELESS_OK_SOURCES`` (it is).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ..law_firms._footprint import in_footprint, normalize_county

log = structlog.get_logger()

SLUG = "national.nc_upset_bids"

# --- source 1: Kania Ninja Tables feed -------------------------------------

KANIA_LISTINGS_URL = "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/"

#: Ninja Tables id for the statewide grid. Only used when the live page stops
#: exposing its own ``data_request_url``.
KANIA_TABLE_ID = "216745"

#: ``limit_rows=0`` means "no limit" in Ninja Tables.
KANIA_AJAX_TEMPLATE = (
    "https://kanialawfirm.com/wp-admin/admin-ajax.php"
    "?action=wp_ajax_ninja_tables_public_action&table_id={table_id}"
    "&target_action=get-all-data&default_sorting=old_first"
    "&skip_rows=0&limit_rows=0"
)

_DATA_REQUEST_RE = re.compile(r'"data_request_url"\s*:\s*"([^"]+)"')
_FOOTABLE_ID_RE = re.compile(r'data-footable_id="(\d+)"')

# --- source 2: county-published upset lists ---------------------------------

_RUTHERFORD_BASE = (
    "https://www.rutherfordcountync.gov/departments/"
    "revenue_department_tax_administrator/foreclosure_information/"
)

#: (county, state, url). Both page parsers run against every entry, so a new
#: county only has to be listed — its shape is detected, not declared.
COUNTY_UPSET_PAGES: tuple[tuple[str, str, str], ...] = (
    (
        "Rutherford", "NC",
        _RUTHERFORD_BASE
        + "in_office_current_and_upcoming_foreclosure_sale_dates.php",
    ),
    (
        "Rutherford", "NC",
        _RUTHERFORD_BASE
        + "outside_law_(kania_law_firm)_current_and_upcoming_foreclosure_sale_dates.php",
    ),
)

# --- shared text helpers ---------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d{1,2})?)")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))\b", re.I)
#: "(0000041) NC 90 HWY E, Stony Point" — some addresses lead with their parcel.
_LEADING_PARCEL_RE = re.compile(r"^\(\s*([A-Za-z0-9\-.]+)\s*\)\s*")
#: "578 E. Settings Blvd. NW, Valdese" -> street / city.
_ADDR_SPLIT_RE = re.compile(r"^(.*?),\s*([A-Za-z][A-Za-z .'-]*)$")

#: Values counties use for "not determined yet". Never becomes a field value.
_PLACEHOLDER = {
    "", "-", "--", "n/a", "na", "tbd", "tba", "pending", "none",
    "multiple", "multiple parcels", "not set", "sale date not yet set",
}

#: propertytype column -> PropertyKind.
_KIND_BY_TYPE = {
    "residential home": PropertyKind.SINGLE_FAMILY,
    "residential vacant lot": PropertyKind.LAND,
    "acreage": PropertyKind.LAND,
    "commercial improved": PropertyKind.COMMERCIAL,
    "commercial vacant lot": PropertyKind.LAND,
    "mixed": PropertyKind.MIXED,
}

#: Emit every in-footprint feed row, not just the upset-posture ones.
_ALL_ROWS_ENV = "NC_UPSET_ALL_ROWS"


def _emit_all_rows() -> bool:
    return os.getenv(_ALL_ROWS_ENV, "").strip().lower() in ("1", "true", "yes")


def _strip_tags(raw: str | None) -> str:
    """"<span class='red'>Sale date not yet set</span>" -> plain text."""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", str(raw))
    text = text.replace("&nbsp;", " ").replace("&ndash;", "-").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _split_cell(raw: str | None) -> list[str]:
    """Split a ``<br />``-joined cell into its parts, tags stripped."""
    if not raw:
        return []
    return [p for p in (_strip_tags(x) for x in _BR_RE.split(str(raw))) if p]


def _is_placeholder(value: str | None) -> bool:
    return (value or "").strip().strip(".").lower() in _PLACEHOLDER


def _money(raw: str | None) -> Optional[float]:
    """"$12,500.00" -> 12500.0. Blank / "tbd" / out-of-range -> None."""
    text = _strip_tags(raw)
    if not text or _is_placeholder(text):
        return None
    m = _MONEY_RE.search(text.replace("$", ""))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # A tax-foreclosure bid is the delinquency + costs: under $10 is a stray
    # fee, over $5M is not a NC tax parcel.
    return value if 10.0 <= value <= 5_000_000.0 else None


def _date(raw: str | None) -> Optional[datetime]:
    """"5/5/2026 11:00:00 AM" / "8/6/2026" -> datetime. "Fall 2026" -> None.

    Only explicit M/D/Y is accepted. Counties write "Summer 2026", "tbd" and
    "Fall 2026" in the same column, and inventing a date for those would put a
    fake deadline in front of the operator.
    """
    text = _strip_tags(raw)
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _sale_time(raw: str | None) -> Optional[str]:
    m = _TIME_RE.search(_strip_tags(raw))
    return m.group(1).upper() if m else None


def _split_address(raw: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """"(0000041) NC 90 HWY E, Stony Point" -> (street, city, inline_parcel)."""
    text = _strip_tags(raw)
    if not text or _is_placeholder(text):
        return None, None, None
    inline_parcel = None
    m = _LEADING_PARCEL_RE.match(text)
    if m:
        inline_parcel = m.group(1)
        text = text[m.end():].strip()
    text = text.rstrip(",").strip()
    # Counties append the state to some rows: "0 US 64 Hwy, Union Mills, NC".
    text = re.sub(r",\s*N\.?C\.?$", "", text, flags=re.I).strip()
    if not text:
        return None, None, inline_parcel
    m = _ADDR_SPLIT_RE.match(text)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None, inline_parcel
    return text, None, inline_parcel


def _split_parcels(raw: str | None) -> list[str]:
    """"615595, 1603783" / "40313<br />39225" -> ["615595", "1603783"]."""
    out: list[str] = []
    for chunk in _split_cell(raw):
        for part in re.split(r"[,;/]| and ", chunk):
            part = part.strip()
            # Counties glue acreage onto the parcel: "1613770; 1.36 acres".
            part = re.sub(r"\s*[-–]?\s*[\d.]+\s*ac(res?)?\.?$", "", part, flags=re.I)
            part = part.strip(" .-")
            if part and not _is_placeholder(part) and re.search(r"\d", part):
                out.append(part)
    return out


def _pair_up(addresses: list[str], parcels: list[str]) -> list[tuple[str, str]]:
    """Zip the multi-valued address + parcel cells into per-property pairs.

    They are usually the same length. When they are not we pad rather than
    drop: a parcel with no address still resolves through GIS, and an address
    with no parcel still geocodes.
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


# --- upset-bid posture ------------------------------------------------------

def _status_for(deadline: Optional[datetime], sale_date: Optional[datetime],
                now: datetime) -> str:
    if deadline is not None:
        return "upset_bid_period" if deadline.date() >= now.date() else "upset_bid_closed"
    if sale_date is not None:
        return "scheduled"
    return "pending_sale_date"


def _effective_sale_date(
    sale_date: Optional[datetime], deadline: Optional[datetime], now: datetime,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Split the sale datetime into (kept, withheld).

    ``main._active_only`` drops any NC listing whose ``sale_date`` is more than
    14 days past, on the assumption that the upset window is 10 days from the
    sale. That assumption breaks on exactly the rows worth having: each
    successful upset restarts the 10-day clock, so a stacked property sold in
    April can still be open for bidding in August. Measured live 2026-08-02,
    that filter discarded ALL 12 rows carrying a live current bid — 141 Duncan
    (sold 7/7, open to 8/6, bid $46,305) among them.

    So when the sale is already past but the published window is still OPEN, we
    withhold ``sale_date`` and let the row travel the dateless lane
    (``national.nc_upset_bids`` is in ``main.DATELESS_OK_SOURCES``). Nothing is
    lost — the withheld datetime is preserved in
    ``raw["upset_bid"]["sale_datetime_iso"]``. This is the correct framing
    anyway: while the window is open the actionable date is the upset deadline,
    not the sale that opened it.

    A future sale date is kept as-is (it is the actionable date and passes the
    filter), and so is a past sale whose window has already closed (there the
    sale date IS the story and the row should age out normally).
    """
    if sale_date is None or deadline is None:
        return sale_date, None
    if sale_date.date() >= now.date():
        return sale_date, None      # sale still ahead
    if deadline.date() < now.date():
        return sale_date, None      # window closed; let it age out normally
    return None, sale_date          # past sale, window still open


def _min_upset_bid(current_bid: Optional[float]) -> Optional[float]:
    """The number an investor actually has to write, per NCGS §45-21.27(a).

    An upset must raise the last bid by at least 5%, and by at least $750 in
    absolute terms. Kania's grid publishes the current bid but not the raise,
    so we derive it — flagged ``_estimated`` in raw so nobody mistakes it for
    the clerk's own figure.
    """
    if not current_bid:
        return None
    return round(current_bid + max(current_bid * 0.05, 750.0), 2)


def _upset_raw(*, county: str, deadline: Optional[datetime],
               sale_date: Optional[datetime], opening_bid: Optional[float],
               current_bid: Optional[float], minimum_upset: Optional[float],
               court_file: Optional[str], parcel: Optional[str],
               feed: str, page_url: str, now: datetime,
               withheld_sale_date: bool = False,
               extra: dict | None = None) -> dict:
    """Build ``raw["upset_bid"]``.

    ``source: "published"`` is load-bearing: ``enrichment_upset_bid`` derives a
    deadline as ``sale_date + 10 days`` and clears any deadline that falls
    outside that window. Stacked upsets legitimately push a published close
    date weeks past the sale, so the derived rule would delete the real
    deadline. The enrichment skips published rows on that flag.
    """
    days_left = None
    if deadline is not None:
        days_left = (deadline.date() - now.date()).days
    payload = {
        "source": "published",
        "in_window": bool(deadline is not None and days_left is not None
                          and days_left >= 0),
        "deadline_iso": deadline.isoformat() if deadline else None,
        "days_remaining": max(0, days_left) if days_left is not None else None,
        "opening_bid": opening_bid,
        "current_bid": current_bid,
        "minimum_upset_bid": minimum_upset,
        "minimum_upset_bid_estimated": (
            None if minimum_upset else _min_upset_bid(current_bid)
        ),
        "sale_datetime_iso": sale_date.isoformat() if sale_date else None,
        "sale_date_withheld": withheld_sale_date,
        "court_file": court_file,
        "parcel": parcel,
        "county": county,
        "statute": "NCGS §45-21.27 / §105-374",
        "feed": feed,
        "page_url": page_url,
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


# --- source 1 parser: Kania Ninja Tables JSON ------------------------------

def feed_stats(payload: list | str) -> dict:
    """Coverage counts for the run report: total vs in-footprint vs actionable."""
    rows = _decode(payload)
    now = datetime.utcnow()
    stats = {
        "feed_rows_total": len(rows),
        "counties_total": 0,
        "rows_in_footprint": 0,
        "counties_in_footprint": 0,
        "with_current_bid": 0,
        "with_upset_deadline": 0,
        "deadline_in_future": 0,
    }
    counties: set[str] = set()
    fp_counties: set[str] = set()
    for row in rows:
        value = row.get("value") if isinstance(row, dict) else None
        if not isinstance(value, dict):
            continue
        county = normalize_county(_strip_tags(value.get("county")))
        if county:
            counties.add(county)
        if not (county and in_footprint(county, "NC")):
            continue
        fp_counties.add(county)
        stats["rows_in_footprint"] += 1
        if _money(value.get("currentbid")) is not None:
            stats["with_current_bid"] += 1
        deadline = _date(value.get("closedate"))
        if deadline is not None:
            stats["with_upset_deadline"] += 1
            if deadline.date() >= now.date():
                stats["deadline_in_future"] += 1
    stats["counties_total"] = len(counties)
    stats["counties_in_footprint"] = len(fp_counties)
    return stats


def _decode(payload: list | str | bytes) -> list:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    return payload if isinstance(payload, list) else []


def _kania_row_to_listings(value: dict, *, slug: str, now: datetime,
                           all_rows: bool) -> list[Listing]:
    county = normalize_county(_strip_tags(value.get("county")))
    if not county or not in_footprint(county, "NC"):
        return []

    sale_date = _date(value.get("saledatetime"))
    deadline = _date(value.get("closedate"))
    opening_bid = _money(value.get("openingbid"))
    current_bid = _money(value.get("currentbid"))

    # Upset posture = the clerk has a reported bid on file, i.e. a close date
    # or a live current bid. Everything else is pre-sale inventory that
    # `law_firms.kania` already carries.
    if not all_rows and deadline is None and current_bid is None:
        return []

    court_file = _strip_tags(value.get("courtfile")) or None
    our_file = _strip_tags(value.get("ourfile")) or None
    prop_type = _strip_tags(value.get("propertytype"))
    kind = _KIND_BY_TYPE.get(prop_type.lower(), PropertyKind.UNKNOWN)
    status = _status_for(deadline, sale_date, now)
    kept_sale_date, withheld = _effective_sale_date(sale_date, deadline, now)

    addresses = [a for a in _split_cell(value.get("address"))
                 if not _is_placeholder(a)]
    parcels = _split_parcels(value.get("parcel"))

    out: list[Listing] = []
    for addr_text, parcel_text in _pair_up(addresses, parcels) or [("", "")]:
        street, city, inline_parcel = _split_address(addr_text)
        parcel = (parcel_text or inline_parcel or "").strip() or None
        if not street and not parcel and not court_file:
            continue
        out.append(Listing(
            source=slug,
            source_url=KANIA_LISTINGS_URL,
            listing_type=ListingType.TAX_SALE,
            property_kind=kind,
            state="NC",
            county=county,
            street_address=street,
            city=city,
            parcel_id=parcel,
            case_number=court_file,
            sale_date=kept_sale_date,
            sale_time=_sale_time(value.get("saledatetime")) if kept_sale_date else None,
            upset_bid_deadline=deadline,
            opening_bid=opening_bid,
            auction_status=status,
            foreclosure_process="tax",
            sale_location=f"{county} County Courthouse",
            land_use=prop_type or None,
            description=(
                f"NC upset-bid window — {county} County tax foreclosure"
                f"{' parcel ' + parcel if parcel else ''}"
                + (f"; current bid ${current_bid:,.2f}" if current_bid else "")
                + (f"; last day to upset {deadline:%-m/%-d/%Y}" if deadline else "")
            ),
            first_seen=now,
            last_seen=now,
            raw={
                "upset_bid": _upset_raw(
                    county=county, deadline=deadline, sale_date=sale_date,
                    opening_bid=opening_bid, current_bid=current_bid,
                    minimum_upset=None, court_file=court_file, parcel=parcel,
                    feed="kania_ninja_tables", page_url=KANIA_LISTINGS_URL,
                    now=now, withheld_sale_date=withheld is not None,
                    extra={"our_file": our_file,
                           "property_type": prop_type or None,
                           "row_id": value.get("___id___")},
                ),
            },
        ))
    return out


def parse_kania_feed(payload: list | str, *, slug: str = SLUG,
                     all_rows: bool | None = None,
                     now: datetime | None = None) -> list[Listing]:
    """Nested Ninja Tables JSON -> upset-bid Listings, one per parcel."""
    rows = _decode(payload)
    now = now or datetime.utcnow()
    all_rows = _emit_all_rows() if all_rows is None else all_rows
    out: list[Listing] = []
    seen: set[tuple] = set()
    for row in rows:
        value = row.get("value") if isinstance(row, dict) else None
        if not isinstance(value, dict):
            continue
        for li in _kania_row_to_listings(value, slug=slug, now=now,
                                         all_rows=all_rows):
            key = ((li.county or "").upper(), (li.parcel_id or "").upper(),
                   (li.street_address or "").upper(), (li.case_number or "").upper())
            if key in seen:
                continue
            seen.add(key)
            out.append(li)
    return out


# --- source 2 parser A: county HTML table ----------------------------------

#: Header keyword -> canonical column name. Counties order columns freely, so
#: everything is resolved by header text rather than by index.
_COL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("address", ("address", "property", "location", "situs")),
    ("parcel", ("parcel", "pin", "tax id", "map number")),
    ("owner", ("owner", "taxpayer", "defendant", "listing owner")),
    ("legal", ("description", "legal")),
    ("case", ("file", "case", "docket")),
    ("tax_value", ("tax value", "assessed", "appraised")),
    ("sale_date", ("sale date", "date of sale", "auction date")),
    ("opening_bid", ("opening bid", "minimum bid", "starting bid", "upset bid")),
    ("current_bid", ("current bid", "high bid", "last bid")),
    ("deadline", ("last day", "upset deadline", "deadline", "bid expires",
                  "upset period ends")),
    ("notes", ("additional info", "notes", "comments", "remarks")),
)


def _map_headers(cells: list[str]) -> dict[str, int]:
    """Map a header row's text to canonical column indexes.

    Counties build these tables in a WYSIWYG editor, so the header row is
    often ``<td>`` rather than ``<th>`` — callers pass whatever the first row
    contains and we decide whether it looks like a header by the hit count.
    """
    mapping: dict[str, int] = {}
    for i, text in enumerate(cells):
        low = text.strip().lower()
        if not low:
            continue
        for canon, keys in _COL_ALIASES:
            if canon in mapping:
                continue
            if any(k in low for k in keys):
                mapping[canon] = i
                break
    return mapping


def parse_county_table(html: str, page_url: str, county: str, *,
                       slug: str = SLUG, now: datetime | None = None,
                       ) -> list[Listing]:
    """Parse a county's server-rendered upset/foreclosure sale table."""
    now = now or datetime.utcnow()
    out: list[Listing] = []
    for table in HTMLParser(html or "").css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        header_cells = [c.text(strip=True) for c in rows[0].css("th, td")]
        cols = _map_headers(header_cells)
        # Need at least an address or a parcel column to be a listing table.
        if not ({"address", "parcel"} & set(cols)):
            continue
        for tr in rows[1:]:
            # `td, th` on purpose: several county CMS templates (Henderson's,
            # for one) emit <th> for every cell in the table including the data
            # rows, so a td-only read silently returns nothing.
            tds = tr.css("td, th")
            if not tds:
                continue
            cells = [td.text(strip=True) for td in tds]

            def col(name: str) -> str:
                i = cols.get(name)
                return cells[i] if i is not None and i < len(cells) else ""

            addresses = [a for a in _split_cell(col("address"))
                         if not _is_placeholder(a)]
            parcels = _split_parcels(col("parcel"))
            case_number = col("case").strip() or None
            if case_number and _is_placeholder(case_number):
                case_number = None
            if not addresses and not parcels and not case_number:
                continue

            sale_date = _date(col("sale_date"))
            deadline = _date(col("deadline"))
            opening_bid = _money(col("opening_bid"))
            current_bid = _money(col("current_bid"))
            tax_value = _money(col("tax_value"))
            notes = col("notes").strip() or None
            owner = col("owner").strip() or None
            legal = col("legal").strip() or None
            # Counties write "Fall 2026" / "Summer 2026" in the sale-date
            # column; keep the operator-visible phrasing even though it can't
            # become a datetime.
            sale_hint = col("sale_date").strip() or None
            if sale_hint and (_is_placeholder(sale_hint) or sale_date):
                sale_hint = None

            # Parcel detail links (lrcpwa parcel-detail) ride along for the
            # operator and for the parcel enrichers.
            links = [urljoin(page_url, a.attributes.get("href", ""))
                     for a in tr.css("a[href]")
                     if a.attributes.get("href", "").startswith("http")]

            status = _status_for(deadline, sale_date, now)
            kept_sale_date, withheld = _effective_sale_date(sale_date, deadline, now)
            for addr_text, parcel_text in _pair_up(addresses, parcels) or [("", "")]:
                street, city, inline_parcel = _split_address(addr_text)
                parcel = (parcel_text or inline_parcel or "").strip() or None
                if not street and not parcel:
                    continue
                out.append(Listing(
                    source=slug,
                    source_url=page_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county=county,
                    street_address=street,
                    city=city,
                    parcel_id=parcel,
                    case_number=case_number,
                    sale_date=kept_sale_date,
                    upset_bid_deadline=deadline,
                    opening_bid=opening_bid,
                    tax_value=tax_value,
                    owner_name=owner,
                    legal_description=legal,
                    auction_status=status,
                    foreclosure_process="tax",
                    sale_location=f"{county} County Courthouse",
                    description=(
                        f"{county} County in-house tax foreclosure"
                        + (f"; file {case_number}" if case_number else "")
                        + (f"; {notes}" if notes else "")
                        + (f"; sale {sale_hint}" if sale_hint else "")
                    ),
                    first_seen=now,
                    last_seen=now,
                    raw={
                        "upset_bid": _upset_raw(
                            county=county, deadline=deadline, sale_date=sale_date,
                            opening_bid=opening_bid, current_bid=current_bid,
                            minimum_upset=None, court_file=case_number,
                            parcel=parcel, feed="county_table",
                            page_url=page_url, now=now,
                            withheld_sale_date=withheld is not None,
                            extra={"sale_date_hint": sale_hint,
                                   "notes": notes,
                                   "tax_value": tax_value,
                                   "parcel_links": links or None},
                        ),
                    },
                ))
    return out


# --- source 2 parser B: county text blocks ---------------------------------

#: "Abrams, Christeen Logan - (1206540) - 141 Duncan St - File #23516,"
#: Separators are a mix of hyphen and en dash depending on who typed the row.
_BLOCK_HEAD_RE = re.compile(
    r"^(?P<owner>[^()]{3,120}?)\s*[-–—]\s*\(\s*(?P<parcel>[A-Za-z0-9\-.]+)\s*\)\s*"
    r"[-–—]\s*(?P<address>.+?)\s*[-–—]\s*File\s*#?\s*(?P<file>[A-Za-z0-9\-]+)",
    re.I,
)
#: NC court file as the clerk writes it: 25CVD000199-800 / 23 M 258 / 24M236.
_COURT_FILE_RE = re.compile(r"\b(\d{2}\s?[A-Z]{1,4}\s?\d{2,6}(?:-\d{3})?)\b")
_CURRENT_BID_RE = re.compile(r"Current\s+Bid[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)", re.I)
_MIN_UPSET_RE = re.compile(
    r"(?:Amount\s+needed\s+to\s+upset|Minimum\s+(?:amount\s+needed\s+to\s+)?upset)"
    r"[^$]*\$?\s*([\d,]+(?:\.\d{2})?)", re.I,
)
_LAST_DAY_RE = re.compile(
    r"Last\s+day\s+(?:for|to)\s+upset(?:\s+bid)?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})", re.I,
)
_OPENING_BID_RE = re.compile(r"Opening\s+Bid[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)", re.I)


def _page_lines(html: str) -> list[str]:
    """Flatten WYSIWYG HTML to one logical line per <br>/block boundary."""
    if not html:
        return []
    body = re.sub(r"(?s)<(script|style)\b[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?i)<(br\s*/?|/p|/div|/li|/tr|/h[1-6])\s*>", "\n", body)
    body = _TAG_RE.sub(" ", body)
    body = (body.replace("&nbsp;", " ").replace("&ndash;", "-")
                .replace("&mdash;", "-").replace("&amp;", "&")
                .replace("&#8211;", "-").replace("&#039;", "'")
                .replace("&quot;", '"'))
    return [re.sub(r"\s+", " ", ln).strip() for ln in body.split("\n")
            if re.sub(r"\s+", " ", ln).strip()]


def parse_county_text_blocks(html: str, page_url: str, county: str, *,
                             slug: str = SLUG, now: datetime | None = None,
                             ) -> list[Listing]:
    """Parse a county page that lists upset bids as free-text blocks.

    Each entry opens with an owner/parcel/address/file header line and is
    followed by up to a handful of detail lines (court file, current bid,
    minimum upset, last day to bid, or an opening bid for not-yet-sold
    parcels). The block ends at the next header line.
    """
    now = now or datetime.utcnow()
    lines = _page_lines(html)
    heads = [(i, m) for i, ln in enumerate(lines)
             if (m := _BLOCK_HEAD_RE.match(ln))]
    out: list[Listing] = []
    for n, (start, m) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else min(len(lines), start + 10)
        block = " ".join(lines[start:end])

        owner = m.group("owner").strip(" ,;-")
        parcel = m.group("parcel").strip()
        street, city, _ = _split_address(m.group("address"))
        our_file = m.group("file").strip()

        tail = " ".join(lines[start + 1:end])
        court_file = None
        cm = _COURT_FILE_RE.search(tail)
        if cm:
            court_file = cm.group(1).strip()

        current_bid = _money(cm.group(1)) if (cm := _CURRENT_BID_RE.search(block)) else None
        minimum_upset = _money(cm.group(1)) if (cm := _MIN_UPSET_RE.search(block)) else None
        deadline = _date(cm.group(1)) if (cm := _LAST_DAY_RE.search(block)) else None
        opening_bid = _money(cm.group(1)) if (cm := _OPENING_BID_RE.search(block)) else None

        if not street and not parcel:
            continue
        status = _status_for(deadline, None, now)
        out.append(Listing(
            source=slug,
            source_url=page_url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=county,
            street_address=street,
            city=city,
            parcel_id=parcel or None,
            case_number=court_file,
            upset_bid_deadline=deadline,
            opening_bid=opening_bid,
            owner_name=owner or None,
            auction_status=status,
            foreclosure_process="tax",
            sale_location=f"{county} County Courthouse",
            description=(
                f"NC upset-bid window — {county} County tax foreclosure"
                + (f"; owner of record {owner}" if owner else "")
                + (f"; current bid ${current_bid:,.2f}" if current_bid else "")
                + (f"; upset at ${minimum_upset:,.2f}" if minimum_upset else "")
                + (f"; last day to upset {deadline:%-m/%-d/%Y}" if deadline else "")
            ),
            first_seen=now,
            last_seen=now,
            raw={
                "upset_bid": _upset_raw(
                    county=county, deadline=deadline, sale_date=None,
                    opening_bid=opening_bid, current_bid=current_bid,
                    minimum_upset=minimum_upset, court_file=court_file,
                    parcel=parcel or None, feed="county_text_block",
                    page_url=page_url, now=now,
                    extra={"our_file": our_file, "owner_name": owner or None},
                ),
            },
        ))
    return out


_HOUSE_NUMBER_RE = re.compile(r"^\d")


def _fold(base: Listing, other: Listing) -> Listing:
    """Merge a second sighting of the same property into the first.

    ``Listing.merge`` is first-non-null-wins, which is right for almost every
    field but wrong for the street address when the two sources disagree on
    completeness. Kania's grid writes some parcels with no house number
    ("Harris Henrietta"); the county page writes the same parcel as "0 Harris
    Henrietta Rd". Prefer whichever address actually starts with a number so
    the geocoder and the parcel resolver get the usable one.
    """
    merged = base.merge(other)
    a, b = base.street_address, other.street_address
    if a and b and a != b:
        a_num, b_num = bool(_HOUSE_NUMBER_RE.match(a)), bool(_HOUSE_NUMBER_RE.match(b))
        if b_num and not a_num:
            merged.street_address = b
    # Once a county publishes the clerk's own upset figure, our derived one is
    # noise sitting next to it — drop it so the operator sees a single number.
    upset = merged.raw.get("upset_bid")
    if isinstance(upset, dict):
        if upset.get("minimum_upset_bid"):
            upset["minimum_upset_bid_estimated"] = None
        # Recompute rather than let the deep-merge inherit either side's flag:
        # only one of the two rows carried a sale datetime, so whichever wrote
        # last would otherwise decide the answer.
        upset["sale_date_withheld"] = bool(
            merged.sale_date is None and upset.get("sale_datetime_iso")
        )
    return merged


def parse_county_page(html: str, page_url: str, county: str, *,
                      slug: str = SLUG, now: datetime | None = None,
                      ) -> list[Listing]:
    """Run both county-page shapes and union them (shape is detected, not declared)."""
    out = parse_county_table(html, page_url, county, slug=slug, now=now)
    out += parse_county_text_blocks(html, page_url, county, slug=slug, now=now)
    seen: set[tuple] = set()
    deduped: list[Listing] = []
    for li in out:
        key = ((li.parcel_id or "").upper(), (li.street_address or "").upper(),
               (li.case_number or "").upper())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(li)
    return deduped


# --- feed discovery ---------------------------------------------------------

def extract_data_request_url(html: str) -> Optional[str]:
    """Read the Ninja Tables AJAX URL the listings page embeds.

    Falls back to ``data-footable_id`` so a table-id change on Kania's side
    cannot silently zero the source.
    """
    if not html:
        return None
    m = _DATA_REQUEST_RE.search(html)
    if m:
        # The URL sits inside a JSON blob, so its slashes arrive as "\/".
        try:
            url = json.loads(f'"{m.group(1)}"')
        except ValueError:
            url = m.group(1).replace("\\/", "/")
        url = re.sub(r"limit_rows=\d+", "limit_rows=0", url)
        url = re.sub(r"skip_rows=\d+", "skip_rows=0", url)
        return urljoin(KANIA_LISTINGS_URL, url)
    m = _FOOTABLE_ID_RE.search(html)
    if m:
        return KANIA_AJAX_TEMPLATE.format(table_id=m.group(1))
    return None


# --- scraper ----------------------------------------------------------------

class NCUpsetBids(BaseScraper):
    slug = SLUG
    name = "NC Upset Bids (Kania statewide feed + county upset lists)"
    category = "upset_bid"
    expected_min_count = 1
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        now = datetime.utcnow()
        out: list[Listing] = []

        # 1. Kania statewide Ninja Tables feed.
        data_url = KANIA_AJAX_TEMPLATE.format(table_id=KANIA_TABLE_ID)
        try:
            page = await get_text(KANIA_LISTINGS_URL, timeout=45.0, impersonate=True)
        except Exception as exc:  # noqa: BLE001
            log.info("nc_upset_bids.listings_page_fail", error=str(exc)[:160])
            page = ""
        discovered = extract_data_request_url(page)
        if discovered:
            data_url = discovered
        try:
            body = await get_text(data_url, timeout=60.0,
                                  referer=KANIA_LISTINGS_URL, impersonate=True)
            stats = feed_stats(body)
            rows = parse_kania_feed(body, slug=self.slug, now=now)
            log.info("nc_upset_bids.kania_feed", listings=len(rows), **stats)
            out.extend(rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_upset_bids.kania_fail", url=data_url,
                        error=str(exc)[:200])

        # 2. County-published upset lists.
        for county, state, url in COUNTY_UPSET_PAGES:
            if not in_footprint(county, state):
                continue
            try:
                html = await get_text(url, timeout=45.0, impersonate=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("nc_upset_bids.county_fail", county=county, url=url,
                            error=str(exc)[:200])
                continue
            rows = parse_county_page(html, url, county, slug=self.slug, now=now)
            log.info("nc_upset_bids.county_page", county=county, url=url,
                     listings=len(rows))
            out.extend(rows)

        # Cross-source dedupe: the same Rutherford parcel appears in the Kania
        # feed and on the county's outside-counsel page. Keep the first
        # sighting but fold in whatever the later one knows (owner name,
        # minimum upset) instead of dropping it.
        merged: dict[tuple, Listing] = {}
        order: list[tuple] = []
        for li in out:
            key = (li.state or "", (li.county or "").upper(),
                   (li.parcel_id or "").upper() or (li.street_address or "").upper())
            if key in merged:
                merged[key] = _fold(merged[key], li)
            else:
                merged[key] = li
                order.append(key)
        final = [merged[k] for k in order]
        log.info("nc_upset_bids.done", raw_rows=len(out), listings=len(final))
        return final
