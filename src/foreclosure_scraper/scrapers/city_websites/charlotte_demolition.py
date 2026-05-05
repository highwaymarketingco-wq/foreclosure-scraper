"""Charlotte (NC) — code enforcement orders to demolish (open data feed).

Charlotte publishes "Orders to Demolish" via its open-data ArcGIS portal.
Each entry is a property the city has ordered demolished — strongest
possible distress signal. Investor opportunity: properties on this list
are typically liquidated by the owner at deep discount to avoid the
demolition + lien.

GeoJSON endpoint (verified May 2026 — direct-download URL exposed by
the open-data dataset page):

  https://data.charlottenc.gov/datasets/charlotte::code-enforcement-orders-to-demolish-1.geojson

Free, no auth, no rate limits. Refresh: city updates as cases progress.
"""
from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


URL = (
    "https://data.charlottenc.gov/datasets/"
    "charlotte::code-enforcement-orders-to-demolish-1.geojson"
)
HEADERS = {
    "User-Agent": "foreclosure-scraper/1.0 (+contact: see repo)",
    "Accept": "application/json",
}


class CharlotteDemolitionOrders(BaseScraper):
    slug = "city_websites.charlotte_demolition"
    name = "Charlotte NC — Orders to Demolish"
    category = "city_open_data"
    expected_min_count = 0  # may be 0 between batches
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=30.0) as c:
            try:
                r = await c.get(URL, headers=HEADERS)
            except Exception as exc:
                log.warning("charlotte_demo.fetch_failed",
                            error=str(exc)[:200])
                return []
        if r.status_code != 200:
            log.warning("charlotte_demo.bad_status", status=r.status_code)
            return []
        try:
            j = r.json()
        except (ValueError, _json.JSONDecodeError):
            log.warning("charlotte_demo.bad_json")
            return []

        out: list[Listing] = []
        seen: set[str] = set()
        for f in j.get("features", []):
            props = (f.get("properties") or {})
            geom = (f.get("geometry") or {})
            case_no = (props.get("CaseNumber") or "").strip()
            if not case_no:
                continue
            if case_no in seen:
                continue
            seen.add(case_no)

            # Charlotte case fields (from probe): CaseType, CaseNumber,
            # CaseStatus + the address columns (Address, City, ZipCode).
            street = (props.get("Address") or props.get("AddressFull") or "").strip()
            city = (props.get("City") or "Charlotte").strip()
            zip_code = (props.get("ZipCode") or props.get("ZIP") or "").strip()
            status = (props.get("CaseStatus") or "").strip()
            case_type = (props.get("CaseType") or "").strip()

            # Centroid → lat/lng
            lat = lng = None
            if geom.get("type") == "Point" and geom.get("coordinates"):
                lng, lat = geom["coordinates"][:2]
            elif geom.get("coordinates"):
                # Polygon / multipolygon — average all points
                pts: list[list[float]] = []
                def _walk(node):
                    if isinstance(node, list):
                        if node and isinstance(node[0], (int, float)) and len(node) >= 2:
                            pts.append(node)
                        else:
                            for child in node:
                                _walk(child)
                _walk(geom["coordinates"])
                if pts:
                    lng = sum(p[0] for p in pts) / len(pts)
                    lat = sum(p[1] for p in pts) / len(pts)

            out.append(Listing(
                source=self.slug,
                source_url=URL,
                listing_type=ListingType.DISTRESSED,  # demolition order
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Mecklenburg",
                city=city,
                zip_code=zip_code or None,
                street_address=street or None,
                latitude=lat,
                longitude=lng,
                case_number=case_no,
                description=(
                    f"Charlotte code enforcement order to demolish "
                    f"({case_type}) · status: {status or 'unknown'}"
                )[:500],
                auction_status=status.lower() or None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"charlotte_demolition": {
                    "case_type": case_type,
                    "case_status": status,
                    "props": {k: v for k, v in props.items()
                              if k in ("CaseType", "CaseNumber", "CaseStatus",
                                       "Address", "City", "ZipCode",
                                       "OrderDate", "ComplianceDate")},
                }},
            ))
        log.info("charlotte_demo.done", count=len(out))
        return out
