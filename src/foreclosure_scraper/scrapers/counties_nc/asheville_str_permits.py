"""Asheville lapsed short-term-rental (homestay) permits — motivated-landlord signal.

The City of Asheville publishes its homestay (STR) permit register as a free,
public ArcGIS layer. A permit in status Expired or Revoked flags a property whose
owner just LOST the ability to legally short-term-rent it — a direct income shock
and a common reason to sell (especially where whole-house STRs are banned, so the
income can't simply be replaced). Each row carries the situs address, the owner
(record_name), and the parcel number — property-keyed out of the box.

Free + compliant: public ArcGIS REST, no login/CAPTCHA/pay. Buncombe County
(Asheville + Arden). Dateless standing status -> DATELESS_OK_SOURCES.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

LAYER = ("https://gis.ashevillenc.gov/server/rest/services/Permits/"
         "HomestayPermitsView/MapServer/5/query")

_LAPSED = ("Expired", "Revoked")


def _split_addr(full: str) -> tuple[str | None, str | None]:
    """'85 MILLS GAP RD, ASHEVILLE, NC 28803' -> ('85 MILLS GAP RD', 'ASHEVILLE')."""
    if not full:
        return None, None
    parts = [p.strip() for p in full.split(",")]
    street = parts[0] or None
    city = parts[1] if len(parts) > 1 else None
    return street, city


class AshevilleSTRPermits(BaseScraper):
    slug = "counties_nc.asheville_str_permits"
    name = "Asheville Lapsed STR / Homestay Permits (motivated landlord)"
    category = "motivated_seller"
    expected_min_count = 20
    timeout_s = 120.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        where = "record_status IN ('" + "','".join(_LAPSED) + "')"
        async with client(timeout=40.0) as c:
            params = {
                "where": where,
                "outFields": "record_name,address,parcel_number,apn,record_status,"
                             "record_status_date,business_name,record_type",
                "returnGeometry": "false", "resultRecordCount": "1500", "f": "json",
            }
            try:
                r = await c.get(LAYER, params=params)
                feats = (r.json() or {}).get("features") or []
            except Exception as exc:  # noqa: BLE001
                log.warning("asheville_str.fetch_fail", error=str(exc)[:150])
                return []
            seen: set[tuple] = set()
            for f in feats:
                a = f.get("attributes") or {}
                owner = (a.get("record_name") or "").strip() or None
                street, city = _split_addr((a.get("address") or "").strip())
                parcel = (str(a.get("parcel_number") or a.get("apn") or "").strip() or None)
                status = (a.get("record_status") or "").strip()
                if not (street or parcel):
                    continue
                key = (street or "", parcel or "", (owner or "").upper())
                if key in seen:
                    continue
                seen.add(key)
                li = Listing(
                    source=self.slug,
                    source_url="https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5",
                    listing_type=ListingType.UNKNOWN,
                    property_kind=PropertyKind.SINGLE_FAMILY,
                    state="NC",
                    county="Buncombe",
                    city=city or "Asheville",
                    street_address=street,
                    parcel_id=parcel,
                    defendant=owner,
                    sale_date=None,
                    description=f"{status} short-term-rental permit (Asheville homestay) — {owner or 'owner'}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        # scored by distress_score FINANCIAL "str_permit_lapsed"
                        "str_permit_lapsed": {
                            "status": status,
                            "status_date": a.get("record_status_date"),
                            "business_name": (a.get("business_name") or "").strip() or None,
                        },
                    },
                )
                out.append(li)
        log.info("asheville_str.parsed", listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = AshevilleSTRPermits()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        for li in rows[:10]:
            print(f"  {(li.defendant or '')[:26]:26} {(li.street_address or '')[:34]:34} "
                  f"{(li.raw or {}).get('str_permit_lapsed', {}).get('status')}")

    asyncio.run(_main())
