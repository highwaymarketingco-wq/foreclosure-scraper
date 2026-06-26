"""Brunswick County (NC) tax-foreclosure notices of sale — Legal-Notices page.

Built 2026-06-26. This is the COUNTY in-rem property-TAX foreclosure stream for
Brunswick, distinct from the mortgage / deed-of-trust power-of-sale track that
flows through ``nc_ecourts_lis_pendens`` and the substitute-trustee law firms
(Hutchens et al.). The Brunswick County Attorney posts each notice of sale as a
per-parcel PDF on the public Legal-Notices page:

    https://www.brunswickcountync.gov/912/Legal-Notices   (verified live, free,
    no login, no CAPTCHA — 2026-06-26)

The page renders a run-on HTML list of "Parcel # <PARCEL> <Month DD, YYYY>"
pairs, each parcel anchored to a per-parcel PDF notice at
/DocumentCenter/View/NNNN. Live 2026-06-26 (5 notices, matching the prompt):

    156LA00502  Apr 10, 2026   /DocumentCenter/View/7205
    037CC019    Apr 10, 2026   /DocumentCenter/View/7206
    22900053    May  8, 2026   /DocumentCenter/View/7290
    173BC001    Jun 26, 2026   /DocumentCenter/View/7536
    156NE015    Jun 26, 2026   /DocumentCenter/View/7537

What lives where (verified live 2026-06-26):
  * Parcel # and the sale DATE are in the HTML list text — reliable.
  * The street address / opening bid live ONLY inside the per-parcel PDF, and
    those PDFs are single-page SCANNED IMAGES with NO text layer (pdfplumber:
    0 chars, 1 image). So we still follow + open each PDF with pdfplumber and
    parse anything a future text-layer PDF would yield (address / parcel /
    sale-date / opening-bid via shared regexes), but on today's image-only
    notices the PDF pass contributes nothing and we fall back to the HTML
    parcel + date. The notice PDF URL is always recorded for the analyst.
  * Because a Brunswick row arrives parcel-only (no address, no coordinates),
    we resolve parcel -> lat/lng/owner/situs/value via NC OneMap at scrape time
    so the OCEANFRONT scope gate in ``main._in_scope`` can place the point
    (Brunswick is an OCEANFRONT_COASTAL_COUNTIES county admitted only through
    that gate). coastal_counties=True.

This module is intentionally Brunswick-only and standalone. The broader
``nc_coastal_tax_foreclosure`` module also covers Brunswick at the list level;
this file adds the explicit per-parcel-PDF follow + pdfplumber parse the
Brunswick tax stream calls for, and stands on its own slug so a Brunswick-only
regression is attributable.

Free + compliant: plain HTTP GET of public county pages + public PDFs +
NC OneMap (the same statewide parcel FeatureService the owner-mailing / coastal
enrichers already use). curl-cffi impersonation tier only (real Chrome TLS
fingerprint, no browser process) — no login, no CAPTCHA/WAF defeat.
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

SLUG = "counties_nc.brunswick_legal_notices"

BRUNSWICK_HOST = "https://www.brunswickcountync.gov"
BRUNSWICK_LEGAL_NOTICES = "https://www.brunswickcountync.gov/912/Legal-Notices"

# NC OneMap statewide parcel FeatureService — one query covers all 100 NC
# counties. Used to resolve a tax-foreclosure PARCEL to lat/lng (+ owner +
# situs address + value) so a parcel-only Brunswick row reaches the oceanfront
# scope gate already carrying a point. Lowercase field names (verified live):
# parno (parcel), siteadd/scity (situs), ownname (owner), cntyname (county),
# parval/presentval (value). Parcel numbers are NOT unique statewide, so every
# query is scoped by cntyname='Brunswick'.
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
# Address-shaped line inside a (hypothetical) text-layer PDF: a leading street
# number then words. Conservative — only used to harvest an address from a PDF
# that actually has a text layer; today's image notices yield nothing here.
_ADDR_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Za-z0-9.\-' ]{3,60}?"
    r"(?:St|Street|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Ave|Avenue|Blvd|Boulevard"
    r"|Hwy|Highway|Way|Cir|Circle|Pl|Place|Trl|Trail|Pkwy|Parkway|Loop|Run|Pt|Point)\b)",
    re.I,
)
_BRUNSWICK_PARCEL_RE = re.compile(r"Parcel\s*#\s*([A-Za-z0-9]+)")


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


def parse_legal_notices(
    html: str, page_url: str = BRUNSWICK_LEGAL_NOTICES
) -> list[tuple[str, str, Optional[datetime]]]:
    """Parse the Legal-Notices list into (parcel, pdf_url, sale_date) tuples.

    Each row is "Parcel # <PARCEL> <Month DD, YYYY>" with an <a> on the parcel
    text pointing at the per-parcel PDF notice. The parcel + sale date are in
    the HTML; the address is not (it's inside the PDF). We pair each anchor's
    parcel with the first date token that follows it in document order — robust
    to the CivicPlus zero-width-space markup.
    """
    tree = HTMLParser(html)
    text = tree.text(separator=" ").replace("​", " ")
    text = re.sub(r"\s+", " ", text)

    out: list[tuple[str, str, Optional[datetime]]] = []
    seen: set[str] = set()
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if "DocumentCenter/View" not in href:
            continue
        m = _BRUNSWICK_PARCEL_RE.search(a.text() or "")
        if not m:
            continue
        parcel = m.group(1).strip()
        if not parcel or parcel in seen:
            continue
        seen.add(parcel)
        pdf_url = href if href.startswith("http") else BRUNSWICK_HOST + href

        sale_date = None
        idx = text.find(f"Parcel # {parcel}")
        if idx == -1:
            idx = text.find(parcel)
        if idx != -1:
            # Window from just after the parcel to (before) the next "Parcel #".
            after = text[idx + len(parcel): idx + len(parcel) + 80]
            nxt = after.find("Parcel #")
            if nxt != -1:
                after = after[:nxt]
            sale_date = _parse_date(after)
        out.append((parcel, pdf_url, sale_date))
    return out


def parse_notice_pdf_text(text: str) -> dict[str, Any]:
    """Best-effort harvest of address / parcel / sale-date / opening-bid from a
    per-parcel notice PDF's TEXT LAYER.

    Brunswick's current notices are scanned images with no text layer, so this
    returns an empty dict for them. It is written so that the day a notice ships
    with a real text layer (or the county switches to generated PDFs), the
    address + opening bid are picked up automatically with no code change.
    """
    found: dict[str, Any] = {}
    if not text or not text.strip():
        return found

    flat = re.sub(r"\s+", " ", text)

    pm = _BRUNSWICK_PARCEL_RE.search(flat)
    if pm:
        found["parcel_id"] = pm.group(1).strip()

    sd = _parse_date(flat)
    if sd:
        found["sale_date"] = sd

    bid = _money(flat)
    if bid:
        found["opening_bid"] = bid

    am = _ADDR_RE.search(flat)
    if am:
        addr = re.sub(r"\s+", " ", am.group(1)).strip().rstrip(",")
        # Avoid grabbing a courthouse/sale-location street as the property.
        if "courthouse" not in addr.lower():
            found["street_address"] = addr
    return found


async def _resolve_onemap(
    c: httpx.AsyncClient, parcel: str, county: str = "Brunswick"
) -> Optional[dict[str, Any]]:
    """Resolve a Brunswick parcel to attributes + a centroid via NC OneMap,
    county-scoped (parcels aren't unique statewide). Tries the raw parcel
    against both ``parno`` and ``altparno``. Returns attrs incl. ``_centroid``
    (lat, lng) on success, else None."""
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
            attrs = dict(feats[0].get("attributes") or {})
            geom = feats[0].get("geometry") or {}
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
    """Resolve parcel -> coordinates (+ owner/address/value) for rows lacking
    lat/lng, in place, so the oceanfront scope gate can place them at ingest.
    Returns the count newly resolved."""
    targets = [
        li for li in listings
        if li.parcel_id and (li.latitude is None or li.longitude is None)
    ]
    if not targets:
        return 0
    resolved = 0
    async with client(timeout=25.0) as c:
        for li in targets:
            attrs = await _resolve_onemap(c, li.parcel_id or "", li.county or "Brunswick")
            if attrs:
                had = li.latitude is not None
                _apply_onemap(li, attrs)
                if not had and li.latitude is not None:
                    resolved += 1
    return resolved


async def _fetch_pdf_fields(pdf_url: str) -> dict[str, Any]:
    """Follow a per-parcel notice PDF link and pdfplumber-parse its text layer.

    Returns harvested fields (empty for the current image-only notices). Never
    raises — a bad/blocked/scanned PDF just contributes nothing.
    """
    try:
        pdf_bytes = await get_bytes(pdf_url, timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("brunswick.pdf_fetch_failed", url=pdf_url, error=str(exc))
        return {}
    try:
        import pdfplumber  # local import keeps module import cheap

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        return parse_notice_pdf_text(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("brunswick.pdf_parse_failed", url=pdf_url, error=str(exc))
        return {}


class BrunswickLegalNotices(BaseScraper):
    slug = SLUG
    name = "Brunswick County NC Tax-Foreclosure Notices (Legal Notices)"
    category = "county_tax"
    coastal_counties = True
    # Brunswick tax sales are episodic — the County Attorney can have 0 active
    # notices posted in a given month.
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        try:
            html = await get_text(
                BRUNSWICK_LEGAL_NOTICES,
                headers={"User-Agent": "Mozilla/5.0"},
                impersonate=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("brunswick.list_failed", error=str(exc))
            return out

        rows = parse_legal_notices(html)
        log.info("brunswick.list", rows=len(rows))

        for parcel, pdf_url, sale_date in rows:
            pdf_fields = await _fetch_pdf_fields(pdf_url)

            li = Listing(
                source=SLUG,
                source_url=pdf_url or BRUNSWICK_LEGAL_NOTICES,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Brunswick",
                parcel_id=pdf_fields.get("parcel_id") or parcel,
                street_address=pdf_fields.get("street_address"),
                opening_bid=pdf_fields.get("opening_bid"),
                # HTML date is authoritative; the PDF date (if any) only fills.
                sale_date=sale_date or pdf_fields.get("sale_date"),
                foreclosure_process="tax",
                auction_status="active",
                description=f"Brunswick County tax-foreclosure notice of sale (parcel {parcel})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "brunswick_legal_notices": {
                        "county": "Brunswick",
                        "notice_pdf": pdf_url,
                        "pdf_text_layer": bool(pdf_fields),
                    }
                },
            )
            out.append(li)

        # Geo-resolve parcel-only rows so the oceanfront gate can place them at
        # ingest (Brunswick notices carry no address; the gate needs a point).
        try:
            n = await _geo_enrich(out)
            log.info("brunswick.geo", rows=len(out), resolved=n)
        except Exception:  # noqa: BLE001
            log.error("brunswick.geo_failed", exc_info=True)

        return out


# Allow running this module directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.brunswick_legal_notices
if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        scraper = BrunswickLegalNotices()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}  outcome={scraper.last_outcome} "
              f"reason={scraper.last_reason!r}")
        for x in results:
            print(f"  parcel={x.parcel_id} date={x.sale_date} "
                  f"addr={x.street_address!r} bid={x.opening_bid} "
                  f"lat={x.latitude} lng={x.longitude} owner={x.owner_name!r} "
                  f"pdf={x.raw.get('brunswick_legal_notices', {}).get('notice_pdf')}")

    asyncio.run(_main())
