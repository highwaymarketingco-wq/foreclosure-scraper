"""Asheville lapsed short-term-rental (homestay) permits — motivated-landlord signal.

The City of Asheville publishes its homestay (STR) permit register as a free,
public ArcGIS layer. A permit in status Expired or Revoked CAN flag a property
whose owner just LOST the ability to legally short-term-rent it — a direct
income shock and a common reason to sell (especially where whole-house STRs
are banned, so the income can't simply be replaced). Each row carries the
situs address, the owner (record_name), and the parcel number — property-keyed
out of the box.

IS THIS A REAL SIGNAL? CHECKED, NOT ASSUMED (2026-10-01 per-source audit)
    `record_comments` (the city's own case notes, free text) was never
    captured, and reading it live across all 690 current Expired/Revoked rows
    shows the "lost income" framing above does not hold for every row:
      * 8 rows read "...permit was never actually issued" / "never inspected,
        so permit was never actually issued" -- the homestay never earned a
        dollar, so there is no income to have lost. Excluded outright
        (`_NEVER_ISSUED_RE`): counting these as a financial-distress signal
        would be fabricating one from a paperwork non-event.
      * 252 of 690 (36%) read "failed to renew" with no further action noted
        -- a genuine administrative lapse, consistent with the module's
        "common reason to sell" framing but not dramatic proof of it. Kept
        (not a false positive, just a softer one), and now the actual comment
        text rides along in `raw` so any future scoring refinement, or a
        human reviewing a lead, has the real reason instead of a bare status.
      * 29 of 690 carry a nonzero `balance_due` (recorded live, typically
        $208, an unpaid renewal fee) -- a small but real financial fact,
        now captured.
    Net: this source is a real (if sometimes administrative) signal, kept, and
    its extraction gap is fixed by wiring the fields below.

Free + compliant: public ArcGIS REST, no login/CAPTCHA/pay. Buncombe County
(Asheville + Arden). Dateless standing status -> DATELESS_OK_SOURCES.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

LAYER = ("https://gis.ashevillenc.gov/server/rest/services/Permits/"
         "HomestayPermitsView/MapServer/5/query")

_LAPSED = ("Expired", "Revoked")

#: Live-confirmed 2026-10-01: a handful of "Revoked" rows are for a homestay
#: that was never actually issued / never inspected -- no STR income was ever
#: earned, so there is no income shock to flag. Not a real lapsed-permit lead.
_NEVER_ISSUED_RE = re.compile(r"never\s+(?:actually\s+)?(?:issued|inspected)", re.I)


def _epoch_ms_to_iso(v) -> str | None:
    """ArcGIS date fields are epoch-milliseconds (or None); several here
    (date_opened, record_status_date) were being dropped entirely."""
    if not v:
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _point(geom) -> tuple[float | None, float | None]:
    """(lat, lon) of a WGS84 point geometry, or (None, None)."""
    if not isinstance(geom, dict):
        return None, None
    try:
        lon, lat = float(geom.get("x")), float(geom.get("y"))
    except (TypeError, ValueError):
        return None, None
    if not (33.0 < lat < 37.5 and -85.0 < lon < -75.0):   # NC; drops 0/0 and NaN-like nulls
        return None, None
    return lat, lon


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
                             "record_status_date,business_name,record_type,"
                             "record_id,license_number,balance_due,date_opened,"
                             "record_comments",
                # The permit's own point: `apn`/`parcel_number` on this layer is the city's
                # 4-6 digit permit-system parcel key, not Buncombe's PIN (it matches neither
                # pin, pinnum nor AccountNumber on the county parcel layer; checked 2026-10-08),
                # and validation nulls it (620 rows on the 2026-10-08 run). The point is what
                # lets the geo parcel enricher find the PIN, owner and value.
                "returnGeometry": "true", "outSR": "4326",
                "resultRecordCount": "1500", "f": "json",
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
                comments = (a.get("record_comments") or "").strip() or None
                if not (street or parcel):
                    continue
                if comments and _NEVER_ISSUED_RE.search(comments):
                    # No STR income was ever earned on this parcel -- not an
                    # income-shock lead (live-confirmed: 8/690 current rows).
                    continue
                key = (street or "", parcel or "", (owner or "").upper())
                if key in seen:
                    continue
                seen.add(key)
                balance_due = a.get("balance_due")
                record_id = (a.get("record_id") or "").strip() or None
                license_number = (str(a.get("license_number") or "").strip() or None)
                lat, lon = _point(f.get("geometry"))
                li = Listing(
                    source=self.slug,
                    source_url="https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5",
                    latitude=lat, longitude=lon,
                    listing_type=ListingType.UNKNOWN,
                    property_kind=PropertyKind.SINGLE_FAMILY,
                    state="NC",
                    county="Buncombe",
                    city=city or "Asheville",
                    street_address=street,
                    parcel_id=parcel,
                    case_number=record_id,
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
                            "status_date_iso": _epoch_ms_to_iso(a.get("record_status_date")),
                            "date_opened_iso": _epoch_ms_to_iso(a.get("date_opened")),
                            "business_name": (a.get("business_name") or "").strip() or None,
                            "record_id": record_id,
                            "license_number": license_number,
                            # the city's own reason text -- "failed to renew" is an
                            # administrative lapse, not proof of financial distress;
                            # keeping the real text lets a reviewer (or a future
                            # scoring refinement) tell the difference.
                            "comments": comments,
                            **({"balance_due": balance_due} if balance_due else {}),
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
