"""NC county delinquent-tax advertisements published as free .gov PDFs — the
full NCGS 105-369 roll for counties that self-host the list (FREE, no login).

Sibling of buncombe_delinquent_tax.py (also a PDF) and nc_ptscloud_delinquent_tax.py
(the API counties). Each county here posts its annual "Advertisement of Tax Liens
on Real Property" as a plain .gov PDF; this parses them with pypdf. One config
dict per county with a layout tag, because the three current counties render
three different line formats:

  * name_id_amt   -> "<OWNER NAME>   <ID>   <AMOUNT>"  (one row per line)
        Lincoln (ID = 4-6-digit GIS PIN), Catawba (ID = tax ACCOUNT #, not a PIN)
  * parcel_amt_owner -> a "<PARCEL>  $<AMOUNT>" line, then the owner/description
        on the NEXT line.  McDowell.

Amount is back-tax OWED -> raw (normalized to raw['tax_owed'] by
enrichment_tax_owed), NOT tax_value. Situs isn't in these lists; parcel_id
backfills the address via NC OneMap/GIS. Gate off with FORECLOSURE_NC_PDF_TAX=0.
URLs carry a tax year; when a county rolls to a new year, update the URL here.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

COUNTIES: dict[str, dict] = {
    "Lincoln": {
        "url": "https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice",
        "layout": "name_id_amt", "id_digits": (4, 6), "id_is_parcel": True,
    },
    "Catawba": {
        "url": "https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf",
        "layout": "name_id_amt", "id_digits": (1, 7), "id_is_parcel": False,  # ID = account #, not GIS PIN
    },
    "McDowell": {
        "url": "https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf",
        "layout": "parcel_amt_owner", "id_is_parcel": True,
    },
}

_PARCEL_AMT_RE = re.compile(r"^([0-9A-Z]{9,15})\s+\$([\d,]+\.\d{2})$")


def _money(s: str) -> float | None:
    try:
        f = float(s.replace(",", "").replace("$", "").strip() or 0)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _clean_owner(s: str | None) -> str | None:
    s = re.sub(r"\s+", " ", (s or "")).strip().strip(";,").strip()
    return s or None


def _parse_name_id_amt(text: str, id_digits: tuple[int, int]) -> list[tuple]:
    """Rows of "<owner> <id> <amount>". Returns [(owner, id, amount)]."""
    lo, hi = id_digits
    rx = re.compile(rf"^(.+?)\s+(\d{{{lo},{hi}}})\s+([\d,]*\.?\d{{1,2}})$")
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or "Column" in s:
            continue
        m = rx.match(s)
        if not m:
            continue
        amt = _money(m.group(3))
        owner = _clean_owner(m.group(1))
        if amt and owner:
            out.append((owner, m.group(2), amt))
    return out


def _parse_parcel_amt_owner(text: str) -> list[tuple]:
    """A "<parcel> $<amount>" line followed by the owner/description line."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    for i, ln in enumerate(lines[:-1]):
        m = _PARCEL_AMT_RE.match(ln)
        if not m:
            continue
        amt = _money(m.group(2))
        owner = _clean_owner(lines[i + 1])
        if amt:
            out.append((owner, m.group(1), amt))
    return out


def _to_listing(owner, ident, amt, county, cfg) -> Listing:
    now = datetime.utcnow()
    return Listing(
        source="counties_nc.nc_county_pdf_delinquent_tax",
        source_url=cfg["url"],
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        owner_name=owner,
        defendant=owner,
        # Always set parcel_id — it's the county's unique identifier and the
        # dedup key. For Catawba it's a tax ACCOUNT # (not a GIS PIN), flagged
        # id_is_parcel=False in raw so GIS-by-parcel knows to skip it; without a
        # parcel_id every Catawba row would collapse to the shared source_url.
        parcel_id=ident,
        foreclosure_process="tax",
        description=(f"{owner or ''} — {county} NC delinquent tax "
                     f"${amt:,.0f} owed ({ident})")[:300],
        first_seen=now,
        last_seen=now,
        raw={
            "nc_county_pdf_delinquent_tax": {
                "county": county,
                "county_id": ident,      # PIN (Lincoln/McDowell) or account # (Catawba)
                "id_is_parcel": cfg.get("id_is_parcel", False),
                "principal_tax_due": round(amt, 2),  # OWED, not value
                "owner": owner,
            }
        },
    )


class NCCountyPdfDelinquentTax(BaseScraper):
    slug = "counties_nc.nc_county_pdf_delinquent_tax"
    name = "NC County Delinquent-Tax PDF Advertisements (Lincoln/Catawba/McDowell)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_NC_PDF_TAX") == "0":
            return []
        out: list[Listing] = []
        async with client(timeout=40.0) as c:
            for county, cfg in COUNTIES.items():
                try:
                    r = await c.get(cfg["url"], headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code != 200 or r.content[:4] != b"%PDF":
                        log.warning("nc_pdf_tax.bad_pdf", county=county, status=r.status_code)
                        continue
                    from pypdf import PdfReader
                    text = "\n".join((p.extract_text() or "")
                                     for p in PdfReader(io.BytesIO(r.content)).pages)
                except Exception as exc:  # noqa: BLE001
                    log.warning("nc_pdf_tax.fetch_fail", county=county, error=str(exc)[:120])
                    continue
                if cfg["layout"] == "name_id_amt":
                    rows = _parse_name_id_amt(text, cfg["id_digits"])
                else:
                    rows = _parse_parcel_amt_owner(text)
                # dedupe by id within county (Catawba repeats a parcel per bill)
                seen: set[str] = set()
                n = 0
                for owner, ident, amt in rows:
                    if ident in seen:
                        continue
                    seen.add(ident)
                    out.append(_to_listing(owner, ident, amt, county, cfg))
                    n += 1
                log.info("nc_pdf_tax.county_done", county=county, leads=n)
        return out
