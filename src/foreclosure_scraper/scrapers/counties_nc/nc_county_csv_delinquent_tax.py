"""NC county delinquent-tax rolls published as free .gov CSV downloads — the
full NCGS 105-369 roll for counties that self-host a machine-readable list
(FREE, no login).

CSV sibling of nc_county_pdf_delinquent_tax.py (PDF advertisements) and
nc_ptscloud_delinquent_tax.py (the API counties). Each county here posts its
delinquent-taxpayer report as a plain CSV; one config dict per county maps the
CSV's column headers to our roles, because headers vary by county.

New Hanover's CSV carries the property LOCATION (situs), so these leads land
with a real street address and skip the name->parcel resolver entirely. The CSV
has one row per (parcel, bill year); we aggregate to one lead per parcel with the
SUMMED back-tax owed across years. Amount is tax OWED -> raw['tax_owed'] (via
enrichment_tax_owed), NOT tax_value. Gate off with FORECLOSURE_NC_CSV_TAX=0.
When a county rotates its DocumentCenter file id, update the URL here.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...layer_guard import LayerHarvest
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

COUNTIES: dict[str, dict] = {
    "New Hanover": {
        "url": "https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV",
        "cols": {
            "owner": "Customer Name",
            "parcel": "Property ID",
            "situs": "Property Location",
            "amount": "Total Receivable",
            "year": "Bill Year",
        },
    },
}


def _money(s: str | None) -> float | None:
    try:
        f = float((s or "").replace(",", "").replace("$", "").strip() or 0)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _clean(s: str | None) -> str | None:
    return " ".join((s or "").split()).strip() or None


def _parse_csv(text: str, cols: dict) -> list[dict]:
    """Aggregate the (parcel, bill-year) rows into one dict per parcel with the
    summed owed amount and the year span."""
    agg: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(text))
    # DictReader keys can carry a BOM on the first header; normalize.
    for raw_row in reader:
        row = { (k or "").lstrip("﻿").strip(): v for k, v in raw_row.items() }
        parcel = _clean(row.get(cols["parcel"]))
        amt = _money(row.get(cols["amount"]))
        if not parcel or amt is None:
            continue
        rec = agg.setdefault(parcel, {
            "owner": _clean(row.get(cols["owner"])),
            "situs": _clean(row.get(cols.get("situs", ""))),
            "amount": 0.0,
            "years": set(),
        })
        rec["amount"] += amt
        yr = _clean(row.get(cols.get("year", "")))
        if yr:
            rec["years"].add(yr)
    return [dict(parcel=p, **v) for p, v in agg.items()]


def _to_listing(rec: dict, county: str, url: str) -> Listing:
    now = datetime.utcnow()
    owner = rec.get("owner")
    situs = rec.get("situs")
    amt = round(rec["amount"], 2)
    years = sorted(rec.get("years") or [])
    yr_span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (years[0] if years else "")
    return Listing(
        source="counties_nc.nc_county_csv_delinquent_tax",
        source_url=url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        owner_name=owner,
        defendant=owner,
        street_address=situs,          # county-provided situs — no resolver needed
        parcel_id=rec["parcel"],
        foreclosure_process="tax",
        description=(f"{owner or ''} — {county} NC delinquent tax "
                     f"${amt:,.0f} owed ({rec['parcel']})")[:300],
        first_seen=now,
        last_seen=now,
        raw={
            "nc_county_csv_delinquent_tax": {
                "county": county,
                "county_id": rec["parcel"],
                "id_is_parcel": True,
                "principal_tax_due": amt,   # OWED, not value
                "bill_years": years,
                "year_span": yr_span,
                "owner": owner,
                "situs": situs,
            }
        },
    )


class NCCountyCsvDelinquentTax(BaseScraper):
    slug = "counties_nc.nc_county_csv_delinquent_tax"
    name = "NC County Delinquent-Tax CSV Rolls (New Hanover)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_NC_CSV_TAX") == "0":
            return []
        out: list[Listing] = []
        # Each county is a big block of leads behind ONE annual CSV. A file that
        # 404s or silently changes shape leaves a hole that passes for normal
        # shrinkage — LayerHarvest declares the set and fails loud instead.
        guard = LayerHarvest(self.slug, list(COUNTIES))
        async with client(timeout=60.0) as c:
            with guard:
                for county, cfg in COUNTIES.items():
                    out.extend(await guard.harvest(
                        county, self._county_fetcher(c, county, cfg)))
        return out

    @staticmethod
    def _county_fetcher(c, county: str, cfg: dict):
        async def _one() -> list[Listing]:
            r = await c.get(cfg["url"], headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                raise RuntimeError(f"{county}: HTTP {r.status_code}")
            head = r.content[:16].lstrip(b"\xef\xbb\xbf").lstrip()
            if head[:4] == b"%PDF" or head[:1] == b"<":
                raise RuntimeError(
                    f"{county}: response is not a CSV (starts {r.content[:16]!r}) "
                    "— the county most likely moved the document")
            text = r.content.decode("utf-8-sig", errors="replace")
            recs = _parse_csv(text, cfg["cols"])
            leads = [_to_listing(rec, county, cfg["url"]) for rec in recs]
            log.info("nc_csv_tax.county_done", county=county, leads=len(leads))
            return leads

        return _one
