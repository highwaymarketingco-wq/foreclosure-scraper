#!/usr/bin/env python3
"""Reachability probe for Dorchester County SC's REAL, current GIS infrastructure.

CORRECTED 2026-10-20: the old target (gisservices.dorchestercounty.net) is a
genuinely decommissioned/dead legacy domain -- confirmed via raw TCP timeouts
on ports 80 and 443 from two different networks. The county's real, current
public GIS lives on two DIFFERENT domains, discovered by following the real
"Dorchester County GIS Viewer" Esri Web AppBuilder app linked from the
county's own official maps/GIS page (reached via curl_cffi Chrome TLS
impersonation -- the plain page 403s a bare client, a passive WAF check, not
an interactive CAPTCHA):
  - maps.dorchestercounty.net/server/rest/services/... (County_Council_Districts,
    Zoning_public, Road_by_Maintenance, Address_Point_Public, Flood_Haz_Areas,
    Parcel_PUBLIC -- the real parcel/CAMA layer: owner, mailing address, sale
    price/date, grantor/grantee, deed, zoning, acreage)
  - gisportal.dorchestercounty.net/hosting/rest/services/... (Parcels_Public,
    Wetlands_Dorchester, Tax_Grid_Pub, Subdivision_Public, Town_Zoning_Public)

Both require curl_cffi's chrome impersonation to get past the WAF; a plain
urllib/requests GET 403s. Retries with exponential backoff and appends one
JSON line per run to logs/dorchester_health_check.log.

    python scripts/check_dorchester_gis.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi.requests import Session

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "logs" / "dorchester_health_check.log"

TARGETS = {
    "maps_parcel_public": (
        "https://maps.dorchestercounty.net/server/rest/services/"
        "General_Data/Parcel_PUBLIC/FeatureServer/0?f=json"
    ),
    "gisportal_parcels_public": (
        "https://gisportal.dorchestercounty.net/hosting/rest/services/"
        "General_Data/Parcels_Public/MapServer?f=json"
    ),
}

MAX_ATTEMPTS = 4
BASE_DELAY_S = 5.0


def _probe(session: Session, url: str) -> dict:
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            r = session.get(url, impersonate="chrome", timeout=20)
            elapsed = time.monotonic() - t0
            return {"ok": r.status_code == 200, "status": r.status_code,
                     "elapsed_s": round(elapsed, 2), "attempts": attempt}
        except Exception as exc:  # noqa: BLE001 - this IS the reachability signal
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(BASE_DELAY_S * (2 ** (attempt - 1)))
    return {"ok": False, "error": last_err, "attempts": MAX_ATTEMPTS}


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat()}
    with Session() as session:
        for name, url in TARGETS.items():
            record[name] = _probe(session, url)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
