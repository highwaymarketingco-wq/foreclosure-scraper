"""Coastal-NC county tax-foreclosure sale pages (Brunswick / Onslow / Carteret).

Built 2026-06-25 for the NEW COASTAL NC FORECLOSURE SOURCES track. The user
explicitly wants Brunswick, Pender, Onslow, Carteret, and Dare coastal NC
foreclosure-sale coverage. These five counties are OUT of the 18-county
footprint and only re-enter scope through the oceanfront gate in
``main._in_scope`` (``OCEANFRONT_COASTAL_COUNTIES`` admits a row provisionally
when it carries an address or parcel, then the post-geocode re-pass keeps only
the near-beach ones).

NC runs TWO foreclosure tracks per county:
  * mortgage / deed-of-trust power-of-sale  -> Clerk of Superior Court SP cases
    (captured by ``nc_ecourts_lis_pendens`` + the substitute-trustee law firms
    like Hutchens, which already carry all five coastal counties).
  * in-rem property-tax foreclosure         -> the COUNTY posts its own list.

This module is the COUNTY tax-foreclosure half for the coast. Each county
publishes a current sale list in a different shape (all verified live
2026-06-25):

  Brunswick  -> /912/Legal-Notices : an HTML list of "Parcel # <PARCEL>
                <Month DD, YYYY>" pairs, each an <a> to a per-parcel PDF
                notice of sale (/DocumentCenter/View/NNNN). Parcel + sale date
                are in the HTML; the street address lives only inside the PDF
                (often a scanned image with no text layer), so we resolve
                parcel -> lat/lng/owner/address via NC OneMap at scrape time so
                the oceanfront gate can place it. 5 live notices 2026-06-25.
  Onslow     -> /289/Foreclosures links a generated PDF
                (/DocumentCenter/View/6521/FORECLOSURE-SALES) with a clean text
                layer: a "Foreclosure Sales <DATE> at <time> at the Courthouse
                Door" header, then rows "Parcel <NNNNNN> <address> $<bid>".
                1 live row 2026-06-25 (036764, 1363 Kinston Hwy, Richlands).
  Carteret   -> /1149/Tax-Foreclosure-Sales : a fixed-header HTML table
                (Name | Parcel ID | Minimum Opening Bid | Owner | Legal
                Description | Address | Date of Sale | Deed Link | Deed Book |
                Deed Page). Updated monthly; empty between sale cycles.

Dare + Pender are deliberately NOT here: Dare posts upcoming sales only on the
courthouse bulletin board (no online list — verified 2026-06-25, the county
clerk page 403s/has no machine-readable list), and Pender has no dedicated
county tax-foreclosure list page. Both counties' mortgage foreclosures still
flow through ``nc_ecourts_lis_pendens`` (coastal counties added 2026-06-25) and
the Hutchens substitute-trustee roster, so they are covered there.

Free + compliant: plain HTTP GET of public county pages + a public PDF +
NC OneMap (the same statewide parcel FeatureService the bankruptcy / owner-
mailing enrichers already use). No login / CAPTCHA / WAF defeat.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Iterable, Optional

import httpx
import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client, get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.nc_coastal_tax_foreclosure"

BRUNSWICK_LEGAL_NOTICES = "https://www.brunswickcountync.gov/912/Legal-Notices"
BRUNSWICK_HOST = "https://www.brunswickcountync.gov"
ONSLOW_FORECLOSURE_PDF = (
    "https://www.onslowcountync.gov/DocumentCenter/View/6521/FORECLOSURE-SALES"
)
ONSLOW_PAGE = "https://www.onslowcountync.gov/289/Foreclosures"
CARTERET_TAX_FORECLOSURE = (
    "https://www.carteretcountync.gov/1149/Tax-Foreclosure-Sales"
)

# NC OneMap statewide parcel FeatureService — one query covers all 100 NC
# counties. Used to resolve a county tax-foreclosure PARCEL to lat/lng (+ owner
# + situs address + value) so a parcel-only Brunswick row arrives at the scope
# gate already carrying coordinates (the oceanfront gate needs a point, and the
# enrichment chain runs AFTER ingest). Lowercase field names (verified live):
# parno (parcel), siteadd/scity (situs), ownname (owner), cntyname (county),
# parval/presentval (value). Parcel numbers are NOT unique statewide
# (Brunswick 036764 also exists in Nash), so every query is scoped by cntyname.
ONEMAP_QUERY = (
    "https://services.nconemap.gov/secure/rest/services/"
    "NC1Map_Parcels/FeatureServer/1/query"
)

_DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
)
_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")


def _parse_date(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return dateparser.parse(m.group(1))
    except (ValueError, TypeError, OverflowError):
        return None


def _money(s: str | None) -> Optional[float]:
    if not s:
        return None
    m = _MONEY_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Brunswick — HTML list of "Parcel # <PARCEL> <date>" + per-parcel PDF link.
# ---------------------------------------------------------------------------
# The parcel# is the <a> text; the sale date is the run-on text that follows the
# link (e.g. "Parcel # 156NE015 June 26, 2026"). We pair each anchor with the
# date token nearest after it in document order.
_BRUNSWICK_PARCEL_RE = re.compile(r"Parcel\s*#\s*([A-Za-z0-9]+)")


def parse_brunswick(html: str, page_url: str = BRUNSWICK_LEGAL_NOTICES) -> list[Listing]:
    """Parse the Brunswick County Legal-Notices list into parcel-only listings.

    Each row is "Parcel # <PARCEL> <Month DD, YYYY>" with an <a> on the parcel
    text pointing at the PDF notice. Address is not in the HTML (it's inside the
    PDF, often image-only), so we emit parcel + sale_date + PDF url and let the
    OneMap geo step (and the standard enrichment chain) fill the rest.
    """
    out: list[Listing] = []
    tree = HTMLParser(html)
    seen: set[str] = set()

    # Build a flat text with anchor hrefs interleaved isn't reliable across the
    # CivicPlus zero-width-space markup, so instead: collect (parcel, href) from
    # anchors, then find each parcel's trailing date in the page text.
    text = tree.text(separator=" ")
    text = text.replace("​", " ")
    text = re.sub(r"\s+", " ", text)

    href_by_parcel: dict[str, str] = {}
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if "DocumentCenter/View" not in href:
            continue
        m = _BRUNSWICK_PARCEL_RE.search(a.text() or "")
        if not m:
            continue
        parcel = m.group(1).strip()
        if parcel and parcel not in href_by_parcel:
            href_by_parcel[parcel] = (
                href if href.startswith("http") else BRUNSWICK_HOST + href
            )

    if not href_by_parcel:
        return out

    # For each parcel, the sale date is the first date token AFTER "Parcel # X".
    for parcel, href in href_by_parcel.items():
        if parcel in seen:
            continue
        seen.add(parcel)
        sale_date = None
        idx = text.find(f"Parcel # {parcel}")
        if idx == -1:
            idx = text.find(parcel)
        if idx != -1:
            # window from just after the parcel to the next "Parcel #" marker
            after = text[idx + len(parcel): idx + len(parcel) + 80]
            sale_date = _parse_date(after)

        out.append(
            Listing(
                source=SLUG,
                source_url=href or page_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Brunswick",
                parcel_id=parcel,
                sale_date=sale_date,
                foreclosure_process="tax",
                auction_status="active",
                description=f"Brunswick County tax-foreclosure notice of sale (parcel {parcel})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"nc_coastal_tax_foreclosure": {"county": "Brunswick",
                                                    "notice_pdf": href}},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Onslow — generated PDF with a clean text layer.
# ---------------------------------------------------------------------------
# Header line: "Foreclosure Sales June 30, 2026 at 12:00pm at the Courthouse Door"
# Row lines:   "Parcel 036764 1363 Kinston Hwy, Richlands $44,423.34"
_ONSLOW_ROW_RE = re.compile(
    r"Parcel\s+([A-Za-z0-9\-]+)\s+(.+?)\s+\$\s?([\d,]+(?:\.\d{2})?)\s*$"
)
_ONSLOW_SALEHDR_RE = re.compile(
    r"Foreclosure Sales\s+(.+?)\s+at\s+(\d{1,2}:\d{2}\s*[AaPp][Mm])", re.I
)


def parse_onslow_pdf_text(text: str, page_url: str = ONSLOW_PAGE) -> list[Listing]:
    """Parse the Onslow foreclosure-sales PDF text into listings.

    The PDF groups rows under "Foreclosure Sales <DATE> at <TIME>..." headers
    (one header can precede several parcel rows). We track the most-recent
    header's date/time and apply it to each subsequent "Parcel ..." row.
    """
    out: list[Listing] = []
    cur_date: Optional[datetime] = None
    cur_time: Optional[str] = None
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        hdr = _ONSLOW_SALEHDR_RE.search(line)
        if hdr:
            cur_date = _parse_date(hdr.group(1))
            cur_time = hdr.group(2).strip()
            continue
        # Skip the column-title row.
        if re.match(r"^Parcel\s+Property\s+Address\s+Opening\s+Bid", line, re.I):
            continue
        m = _ONSLOW_ROW_RE.match(line)
        if not m:
            continue
        parcel = m.group(1).strip()
        addr = re.sub(r"\s+", " ", m.group(2).strip())
        bid = None
        try:
            bid = float(m.group(3).replace(",", ""))
        except ValueError:
            pass
        if parcel in seen:
            continue
        seen.add(parcel)

        # Split a trailing ", City" off the address if present.
        city = None
        street = addr
        if "," in addr:
            parts = [p.strip() for p in addr.rsplit(",", 1)]
            if len(parts) == 2 and 2 <= len(parts[1]) <= 30:
                street, city = parts[0], parts[1]

        out.append(
            Listing(
                source=SLUG,
                source_url=page_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Onslow",
                street_address=street or None,
                city=city,
                parcel_id=parcel,
                opening_bid=bid,
                sale_date=cur_date,
                sale_time=cur_time,
                foreclosure_process="tax",
                auction_status="active",
                description=f"Onslow County tax-foreclosure sale — {addr}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"nc_coastal_tax_foreclosure": {"county": "Onslow"}},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Carteret — fixed-header HTML table.
# ---------------------------------------------------------------------------
_CARTERET_HEADERS = (
    "name", "parcel id", "minimum opening bid", "owner", "legal description",
    "address", "date of sale", "deed link", "deed book", "deed page",
)


def parse_carteret(html: str, page_url: str = CARTERET_TAX_FORECLOSURE) -> list[Listing]:
    """Parse the Carteret County tax-foreclosure HTML table.

    Columns: Name | Parcel ID | Minimum Opening Bid | Owner | Legal Description
    | Address | Date of Sale | Deed Link | Deed Book | Deed Page. We locate the
    header row by its labels (so a layout shuffle doesn't silently misalign),
    then read each data row by column index. Empty rows (between sale cycles)
    are skipped.
    """
    out: list[Listing] = []
    tree = HTMLParser(html)
    for table in tree.css("table"):
        rows = table.css("tr")
        if not rows:
            continue
        # Find the header row + a column-index map.
        col: dict[str, int] = {}
        header_idx = -1
        for ri, r in enumerate(rows):
            labels = [c.text(strip=True).lower() for c in r.css("th,td")]
            if "parcel id" in labels and "date of sale" in labels:
                for ci, lab in enumerate(labels):
                    col[lab] = ci
                header_idx = ri
                break
        if header_idx < 0:
            continue

        def get(cells: list[str], key: str) -> Optional[str]:
            ci = col.get(key)
            if ci is None or ci >= len(cells):
                return None
            v = cells[ci].strip()
            return v or None

        for r in rows[header_idx + 1:]:
            cells = [c.text(strip=True) for c in r.css("td")]
            if not cells or not any(c.strip() for c in cells):
                continue
            parcel = get(cells, "parcel id")
            addr = get(cells, "address")
            owner = get(cells, "owner")
            if not (parcel or addr):
                continue
            sale_date = _parse_date(get(cells, "date of sale"))
            bid = _money(get(cells, "minimum opening bid"))
            legal = get(cells, "legal description")
            name = get(cells, "name")

            out.append(
                Listing(
                    source=SLUG,
                    source_url=page_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Carteret",
                    street_address=addr,
                    parcel_id=parcel,
                    owner_name=owner,
                    opening_bid=bid,
                    sale_date=sale_date,
                    foreclosure_process="tax",
                    auction_status="active",
                    description=(
                        "Carteret County tax-foreclosure sale"
                        + (f" — {name}" if name else "")
                        + (f" ({legal})" if legal else "")
                    )[:400],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"nc_coastal_tax_foreclosure": {"county": "Carteret",
                                                        "legal": legal}},
                )
            )
    return out


# ---------------------------------------------------------------------------
# NC OneMap parcel -> lat/lng/owner/address resolver (county-scoped).
# ---------------------------------------------------------------------------
async def _resolve_onemap(
    c: httpx.AsyncClient, parcel: str, county: str
) -> Optional[dict[str, Any]]:
    """Resolve a county tax-foreclosure parcel to attributes + a centroid via
    NC OneMap, scoped to the county (parcels aren't unique statewide). Tries the
    raw parcel against both ``parno`` and ``altparno``. Returns a dict with a
    ``_centroid`` (lat, lng) on success, else None."""
    parcel = (parcel or "").strip()
    if not parcel:
        return None
    esc = parcel.replace("'", "''")
    cname = county.replace("'", "''")
    for fld in ("parno", "altparno"):
        where = f"{fld}='{esc}' AND cntyname='{cname}'"
        try:
            r = await c.get(
                ONEMAP_QUERY,
                params={
                    "where": where,
                    "outFields": "parno,siteadd,scity,sstate,szip,ownname,cntyname,parval,presentval,gisacres",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": "1",
                    "f": "json",
                },
                timeout=20.0,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            feats = data.get("features") or []
            if not feats:
                continue
            f0 = feats[0]
            attrs = dict(f0.get("attributes") or {})
            geom = f0.get("geometry") or {}
            if "x" in geom and "y" in geom:
                attrs["_centroid"] = (geom["y"], geom["x"])
            elif geom.get("rings"):
                pts = [p for ring in geom["rings"] for p in ring]
                if pts:
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    attrs["_centroid"] = (cy, cx)
            if attrs.get("_centroid"):
                return attrs
        except (httpx.HTTPError, ValueError):
            continue
    return None


def _apply_onemap(li: Listing, attrs: dict[str, Any]) -> None:
    """Fill lat/lng/owner/address/value on a listing from OneMap attrs without
    clobbering anything already populated by the parser."""
    cen = attrs.get("_centroid")
    if cen and li.latitude is None and li.longitude is None:
        try:
            li.latitude, li.longitude = float(cen[0]), float(cen[1])
        except (ValueError, TypeError):
            pass
    site = (attrs.get("siteadd") or "").strip()
    if site and not (li.street_address or "").strip():
        li.street_address = site
    scity = (attrs.get("scity") or "").strip()
    if scity and not (li.city or "").strip():
        li.city = scity
    szip = (attrs.get("szip") or "").strip()
    if szip and not (li.zip_code or "").strip():
        li.zip_code = szip[:5]
    owner = (attrs.get("ownname") or "").strip()
    if owner and not (li.owner_name or "").strip():
        li.owner_name = owner
    val = attrs.get("parval") or attrs.get("presentval")
    if val and not li.tax_value:
        try:
            li.tax_value = float(val)
        except (ValueError, TypeError):
            pass
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["onemap_resolved"] = True


async def _geo_enrich(listings: list[Listing]) -> int:
    """Resolve parcel -> coordinates for listings lacking lat/lng, in place, so
    the oceanfront scope gate can place them at ingest. Returns count resolved."""
    targets = [
        li for li in listings
        if li.parcel_id and (li.latitude is None or li.longitude is None)
    ]
    if not targets:
        return 0
    resolved = 0
    async with client(timeout=25.0) as c:
        for li in targets:
            attrs = await _resolve_onemap(c, li.parcel_id or "", li.county or "")
            if attrs:
                had = li.latitude is not None
                _apply_onemap(li, attrs)
                if not had and li.latitude is not None:
                    resolved += 1
    return resolved


class NCCoastalTaxForeclosure(BaseScraper):
    slug = SLUG
    name = "NC Coastal County Tax Foreclosure (Brunswick/Onslow/Carteret)"
    category = "county_tax"
    # Coastal county tax sales are episodic — a county can have 0 active sales
    # in a given month, and Carteret's table is empty between cycles.
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        # Brunswick — HTML list + per-parcel PDF links.
        try:
            html = await get_text(
                BRUNSWICK_LEGAL_NOTICES, headers={"User-Agent": "Mozilla/5.0"}
            )
            rows = parse_brunswick(html)
            out.extend(rows)
            log.info("nc_coastal.brunswick", rows=len(rows))
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_coastal.brunswick_failed", error=str(exc))

        # Onslow — generated PDF with a text layer.
        try:
            pdf_bytes = await get_bytes(ONSLOW_FORECLOSURE_PDF, timeout=60.0)
            import pdfplumber  # local import keeps module import cheap

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            rows = parse_onslow_pdf_text(text)
            out.extend(rows)
            log.info("nc_coastal.onslow", rows=len(rows))
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_coastal.onslow_failed", error=str(exc))

        # Carteret — HTML table.
        try:
            html = await get_text(
                CARTERET_TAX_FORECLOSURE, headers={"User-Agent": "Mozilla/5.0"}
            )
            rows = parse_carteret(html)
            out.extend(rows)
            log.info("nc_coastal.carteret", rows=len(rows))
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_coastal.carteret_failed", error=str(exc))

        # Geo-resolve parcel-only rows so the oceanfront gate can place them at
        # ingest (Brunswick rows have no address; the gate needs a point).
        try:
            n = await _geo_enrich(out)
            log.info("nc_coastal.geo", rows=len(out), resolved=n)
        except Exception:  # noqa: BLE001
            log.error("nc_coastal.geo_failed", exc_info=True)

        return out


# Allow running this module directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.nc_coastal_tax_foreclosure
if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        scraper = NCCoastalTaxForeclosure()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}  outcome={scraper.last_outcome}")
        by_county: dict[str, int] = {}
        for x in results:
            by_county[x.county or "?"] = by_county.get(x.county or "?", 0) + 1
        for c, n in sorted(by_county.items()):
            print(f"  {c}: {n}")
        for x in results[:12]:
            print(f"  {x.county} parcel={x.parcel_id} addr={x.street_address!r} "
                  f"date={x.sale_date} bid={x.opening_bid} "
                  f"lat={x.latitude} lng={x.longitude} owner={x.owner_name!r}")

    asyncio.run(_main())
