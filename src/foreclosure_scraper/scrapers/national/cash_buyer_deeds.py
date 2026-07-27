"""Identify cash buyers from NC Register of Deeds recordings.

A "cash purchase" is a warranty deed recorded with NO simultaneous deed of
trust (mortgage). When someone buys a property with cash, there's no lender
requiring a deed of trust to be recorded alongside the warranty deed. So:
if a warranty deed appears in the index with the same grantee + date but no
matching deed of trust, that grantee is a cash buyer.

We query free NC ROD search portals via the existing rod/ vendor adapters
(Aumentum, CCHS, Cott, Logan), which handle the complex session/POST flows
each vendor requires. The adapters return RodDoc objects with grantor,
grantee, book/page, recorded_date, and doc_type — everything we need.

Counties in footprint and their ROD vendor:
  - Buncombe      — Aumentum  (registerofdeeds.buncombenc.gov)
  - Gaston        — Aumentum  (deeds.gastongov.com)
  - Henderson     — CCHS      (us4.courthousecomputersystems.com/HendersonNCNW)
  - Cleveland     — CCHS      (us5.courthousecomputersystems.com/ClevelandNCNW)
  - Burke         — CCHS      (us5.courthousecomputersystems.com/BurkeNCNW)
  - Lincoln       — CCHS      (us4.courthousecomputersystems.com/LincolnNCNW)
  - McDowell      — Logan     (search.mcdowelldeeds.com)
  - Polk          — Cott      (cotthosting.com/ncpolkexternal)
  - Rutherford    — Cott      (cotthosting.com/NCRUTHERFORDEXTERNAL)
  - Transylvania  — Logan     (search.transylvaniadeeds.com)
  - Mitchell      — Logan     (search.mitchelldeeds.com)

All 11 counties have FREE, no-login online ROD search (index only; document
images may be pay-per-view but we only need index metadata).

Extract: grantee (buyer) name, property address (from legal description),
deed date, book/page, sale price if available. We flag cash buyers by
checking for the absence of a simultaneous deed of trust.

Listing type: UNKNOWN (cash buyer identification is a lead signal, not a
property listing per se — the enrichment pipeline later determines if
these buyers are investors worth tracking).
source: "national.cash_buyer_deeds"
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import aumentum, cchs, cott, logan
from ...rod.models import RodDoc, normalize_doc_type, DOC_BUCKETS

log = structlog.get_logger()

# Look back this many days for recent recordings
LOOKBACK_DAYS = 30


# --------------------------------------------------------------------------- #
# Vendor dispatch                                                              #
# --------------------------------------------------------------------------- #
# Each entry: (county, vendor_module, discover_callable).
# The discover callables sweep recent recordings (all doc types) and return
# RodDoc lists. We then post-filter for warranty deeds + deeds of trust.

async def _aumentum_recent(state: str, county: str, days: int) -> list[RodDoc]:
    """Aumentum date-range sweep returns all doc types; we filter downstream."""
    return await aumentum._date_swept_docs(state, county, days, max_docs=500)


async def _cchs_recent(state: str, county: str, days: int) -> list[RodDoc]:
    """CCHS date-range sweep for ALL instrument types (empty instrumenttypes
    param returns everything in the date window)."""
    today = datetime.now()
    from_date = today - timedelta(days=max(1, days))
    # Use empty instrument types to get ALL recordings, not just NOD/sold.
    return await cchs._cchs_fetch(state, county, "", from_date, today,
                                  max_docs=500, sold=True)


async def _cott_recent(state: str, county: str, days: int) -> list[RodDoc]:
    """Cott/Manatron: use the NOD sweep which returns all docs in the date
    window (the grid shows everything; doc-type filtering is post-parse).
    We call discover_recent_nods which internally filters, but also
    discover_recent_sold_recordings for deeds. To get ALL recent docs we
    need to hit the date-range form directly."""
    # Cott's discover_recent_nods filters to NOD types only. For cash-buyer
    # detection we need warranty deeds + deeds of trust. Use search_by_name
    # is name-required. Instead, use the internal grid parser by fetching
    # the SrchDocType form with a wide date range and no type filter.
    if (state, county) not in cott.COTT_COUNTIES:
        return []
    base = cott.COTT_COUNTIES[(state, county)]
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days))
    from ...http_client import client as _client
    from ...rod.aumentum import _extract_hidden, _parse_grid
    try:
        async with _client(timeout=30.0) as c:
            r = await c.get(f"{base}/SrchName.aspx")
            if r.status_code != 200:
                return []
            html = r.text
            viewstate = _extract_hidden(html, "__VIEWSTATE")
            generator = _extract_hidden(html, "__VIEWSTATEGENERATOR")
            event_val = _extract_hidden(html, "__EVENTVALIDATION")
            if not viewstate:
                return []
            # Post a date-range search with no name and no type filter
            data = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": generator,
                "__EVENTVALIDATION": event_val,
                "ctl00$cphMain$txtFromDate": from_date.strftime("%m/%d/%Y"),
                "ctl00$cphMain$txtThroughDate": today.strftime("%m/%d/%Y"),
                "ctl00$cphMain$txtFromRecordDate": from_date.strftime("%m/%d/%Y"),
                "ctl00$cphMain$txtThroughRecordDate": today.strftime("%m/%d/%Y"),
                "ctl00$cphMain$btnSearch": "Search",
            }
            r2 = await c.post(f"{base}/SrchName.aspx", data=data,
                              headers={"Referer": f"{base}/SrchName.aspx"})
            if r2.status_code != 200:
                return []
            return _parse_grid(r2.text, county, state)
    except Exception:
        return []


async def _logan_recent(state: str, county: str, days: int) -> list[RodDoc]:
    """Logan 'The Lookup' — sweep recent recordings for ALL distress codes
    plus deed codes. Logan's date-range search requires specific instrument
    codes; we include deed-type codes to capture warranty deeds + DOTs."""
    host = logan.LOGAN_COUNTIES.get((state, county))
    if not host:
        return []
    # Include deed-related codes alongside distress codes
    all_codes = logan.DISTRESS_CODES + (
        "DEED", "WD", "D/T", "MORT", "MORTGAGE", "SAT", "REL",
        "ASSIGN", "QC", "QCD",
    )
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days))
    fmt = lambda d: f"{d.month:02d}/{d.day:02d}/{d.year}"  # noqa: E731
    codes = "&".join(f"instType[InstCodes][{c}]={c}" for c in all_codes)
    body = f"searchType=it&start_date={fmt(frm)}&end_date={fmt(today)}&{codes}"
    try:
        from ...http_client import client as _client
        async with _client(timeout=60.0) as c:
            await c.get(f"{host}/index.php")
            acc = await c.post(f"{host}/index.php", data={"Accept": "Accept"})
            m = logan._TOKEN_RE.search(acc.text)
            if not m:
                return []
            token = m.group(1)
            r = await c.post(f"{host}/content.php?{token}", content=body,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code != 200:
                return []
            return logan._parse_records(r.text, state, county)
    except Exception:
        return []


VENDOR_DISPATCH: tuple[tuple[str, str, callable], ...] = (
    ("Buncombe", "NC", _aumentum_recent),
    ("Gaston", "NC", _aumentum_recent),
    ("Henderson", "NC", _cchs_recent),
    ("Cleveland", "NC", _cchs_recent),
    ("Burke", "NC", _cchs_recent),
    ("Lincoln", "NC", _cchs_recent),
    ("McDowell", "NC", _logan_recent),
    ("Polk", "NC", _cott_recent),
    ("Rutherford", "NC", _cott_recent),
    ("Transylvania", "NC", _logan_recent),
    ("Mitchell", "NC", _logan_recent),
)


# --------------------------------------------------------------------------- #
# Doc-type classification for cash-buyer detection                             #
# --------------------------------------------------------------------------- #
# Warranty deed = property conveyance (buyer takes title).
# Deed of trust = mortgage equivalent in NC (lender holds title as security).
# A warranty deed with NO simultaneous deed of trust = cash purchase.

_WARRANTY_DEED_KEYWORDS = (
    "WARRANTY DEED", "WD", "GENERAL WARRANTY", "SPECIAL WARRANTY",
    "DEED",  # bare "DEED" is often a warranty deed in NC CCHS systems
)
_DEED_OF_TRUST_KEYWORDS = (
    "DEED OF TRUST", "D/T", "DT", "DOT", "TRUST DEED", "MORTGAGE",
    "MORT", "DEED OF TR",
)
# Exclude these from "DEED" generic match — they're NOT warranty deeds
_NON_WARRANTY_DEED_TYPES = (
    "TRUSTEE", "TRUSTEES", "COMMISSIONER", "EXECUTOR", "ADMINISTRATOR",
    "QUITCLAIM", "QUIT CLAIM", "QC", "TAX DEED", "SHERIFF", "FORECLOSURE",
    "DISTRIBUTION", "DEVISE", "PERSONAL REPRESENTATIVE", "GIFT",
)


def _is_warranty_deed(doc_type: str | None) -> bool:
    """True if the doc type looks like a warranty deed (property conveyance)."""
    if not doc_type:
        return False
    s = doc_type.upper().strip()
    # Check non-warranty exclusions first
    if any(kw in s for kw in _NON_WARRANTY_DEED_TYPES):
        return False
    # Explicit warranty deed keywords
    if any(kw in s for kw in ("WARRANTY", "WD", "GENERAL WARRANTY", "SPECIAL WARRANTY")):
        return True
    # CCHS uses bare "DEED" for warranty deeds
    if s == "DEED":
        return True
    return False


def _is_deed_of_trust(doc_type: str | None) -> bool:
    """True if the doc type is a deed of trust (NC mortgage equivalent)."""
    if not doc_type:
        return False
    s = doc_type.upper().strip()
    return any(kw in s for kw in _DEED_OF_TRUST_KEYWORDS)


# --------------------------------------------------------------------------- #
# Address extraction                                                           #
# --------------------------------------------------------------------------- #
_ADDR_RE = re.compile(
    r"\d+\s+[A-Z][\w .'#-]+"
    r"(?:\s+(?:St|Street|Rd|Road|Dr|Drive|Ave|Avenue|Ln|Lane|Ct|Court|"
    r"Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Cir|Circle|Trl|Trail|"
    r"Pkwy|Parkway|Ter|Terrace))\b\.?",
    re.I,
)


def _extract_address(text: str | None) -> str | None:
    if not text:
        return None
    m = _ADDR_RE.search(text)
    return m.group().strip().rstrip(".") if m else None


def _addr_match(a: str, b: str) -> bool:
    """Fuzzy address match — normalize and compare."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())
    return norm(a) == norm(b)


# --------------------------------------------------------------------------- #
# Cash-buyer identification                                                    #
# --------------------------------------------------------------------------- #
def _identify_cash_buyers(deeds: list[RodDoc]) -> list[RodDoc]:
    """Given a list of RodDoc records, identify warranty deeds that have no
    matching deed of trust (cash purchases).

    A warranty deed is a "cash purchase" if:
    1. It's classified as a warranty deed
    2. No deed of trust exists with the same grantee + similar date
       (within 3 days) for the same property
    """
    # Index deeds of trust by grantee for quick lookup
    dots_by_grantee: dict[str, list[RodDoc]] = {}
    for d in deeds:
        if _is_deed_of_trust(d.doc_type) and d.grantee:
            key = d.grantee.lower().strip()
            dots_by_grantee.setdefault(key, []).append(d)

    cash_deeds: list[RodDoc] = []
    for d in deeds:
        if not _is_warranty_deed(d.doc_type):
            continue
        grantee = (d.grantee or "").lower().strip()
        if not grantee:
            continue

        # Check if there's a matching deed of trust
        matching_dots = dots_by_grantee.get(grantee, [])
        has_dot = False
        for dot in matching_dots:
            # Same grantee, within 3 days
            if d.recorded_date and dot.recorded_date:
                date_diff = abs(
                    (d.recorded_date - dot.recorded_date).total_seconds()
                )
                if date_diff <= 3 * 86400:  # 3 days
                    has_dot = True
                    break
            elif not d.recorded_date or not dot.recorded_date:
                # No date to compare — can't confirm DOT match, be conservative
                # and skip (don't flag as cash buyer)
                has_dot = True
                break

        if not has_dot:
            cash_deeds.append(d)

    return cash_deeds


# --------------------------------------------------------------------------- #
# RodDoc -> Listing conversion                                                 #
# --------------------------------------------------------------------------- #
def _deed_to_listing(deed: RodDoc, source_url: str) -> Listing | None:
    """Convert a cash-buyer deed record to a Listing."""
    grantee = deed.grantee
    if not grantee:
        return None

    recorded = deed.recorded_date
    book = deed.book
    page = deed.page
    county = deed.county
    price = deed.consideration_amount

    address = _extract_address(deed.notes)

    description_parts = []
    if grantee:
        description_parts.append(f"Grantee: {grantee}")
    if deed.grantor:
        description_parts.append(f"Grantor: {deed.grantor}")
    if book and page:
        description_parts.append(f"Book {book} Page {page}")
    if price:
        description_parts.append(f"Sale price: ${price:,.0f}")
    description_parts.append("Cash purchase (no deed of trust)")

    return Listing(
        source="national.cash_buyer_deeds",
        source_url=source_url,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        street_address=address,
        county=county,
        state=deed.state,
        case_number=f"{county}:{book or '???'}/{page or '???'}" if book or page else None,
        owner_name=grantee,
        plaintiff=None,
        defendant=None,
        trustee=None,
        sale_date=recorded,
        judgment_amount=price,
        description=" | ".join(description_parts),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "cash_buyer_deeds": {
                "county": county,
                "doc_type": deed.doc_type,
                "book": book,
                "page": page,
                "grantor": deed.grantor,
                "grantee": grantee,
                "price": price,
                "recorded_date": recorded.isoformat() if recorded else None,
                "is_cash_buyer": True,
                "instrument_no": deed.instrument_no,
                "parcel_id": deed.parcel_id,
            },
        },
    )


# --------------------------------------------------------------------------- #
# Source URL lookup per county                                                 #
# --------------------------------------------------------------------------- #
def _source_url(state: str, county: str) -> str:
    """Return the public ROD search page URL for logging/transparency."""
    if (state, county) in aumentum.AUMENTUM_COUNTIES:
        return f"{aumentum.AUMENTUM_COUNTIES[(state, county)]}/SrchName.aspx"
    if (state, county) in cchs.CCHS_COUNTIES:
        host, app, _ = cchs.CCHS_COUNTIES[(state, county)]
        return f"https://{host}.courthousecomputersystems.com/{app}/realestatesearch.asp"
    if (state, county) in cott.COTT_COUNTIES:
        return f"{cott.COTT_COUNTIES[(state, county)]}/SrchName.aspx"
    if (state, county) in logan.LOGAN_COUNTIES:
        return f"{logan.LOGAN_COUNTIES[(state, county)]}/index.php"
    return ""


# --------------------------------------------------------------------------- #
# Scraper class                                                                #
# --------------------------------------------------------------------------- #
class CashBuyerDeeds(BaseScraper):
    slug = "national.cash_buyer_deeds"
    name = "Cash Buyer Deeds (NC ROD: 11 counties)"
    category = "cash_buyer"
    expected_min_count = 0
    timeout_s = 300.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county, state, vendor_fn in VENDOR_DISPATCH:
            src_url = _source_url(state, county)
            try:
                docs = await vendor_fn(state, county, LOOKBACK_DAYS)
            except Exception as exc:
                log.warning("cash_buyer_deeds.fetch_fail", county=county,
                            error=str(exc)[:200])
                continue

            if not docs:
                log.info("cash_buyer_deeds.no_docs", county=county)
                continue

            log.info("cash_buyer_deeds.fetched", county=county,
                     total_docs=len(docs))

            # Identify cash buyers (warranty deeds without matching DOTs)
            cash_deeds = _identify_cash_buyers(docs)
            log.info("cash_buyer_deeds.identified", county=county,
                     total_deeds=len(docs), cash_buyers=len(cash_deeds))

            for deed in cash_deeds:
                li = _deed_to_listing(deed, src_url)
                if li:
                    out.append(li)

        return out
