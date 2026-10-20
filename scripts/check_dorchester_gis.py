#!/usr/bin/env python3
"""Off-peak reachability probe for Dorchester County SC's GIS server.

gisservices.dorchestercounty.net timed out from this Mac's residential IP and
was refused outright from the Oracle VM's datacenter IP on 2026-10-20 during
the day -- two different failure modes from two different networks pointed
to the server itself being down, not a one-sided block. Retries with
exponential backoff against both the real splash page (confirmed URL, via
SC DNR's own parcel-viewer directory) and the ArcGIS REST root, and appends
one JSON line per run to logs/dorchester_health_check.log so a few nights of
cron runs build a real picture of whether it's an off-peak/load issue or a
longer outage, before any scraper is built against it.

    python scripts/check_dorchester_gis.py
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "logs" / "dorchester_health_check.log"

TARGETS = {
    "splash": "https://gisservices.dorchestercounty.net/imap/GISsplash.html",
    "rest_root": "https://gisservices.dorchestercounty.net/arcgis/rest/services?f=json",
}

MAX_ATTEMPTS = 4
BASE_DELAY_S = 5.0


def _probe(url: str) -> dict:
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                elapsed = time.monotonic() - t0
                return {"ok": True, "status": resp.status, "elapsed_s": round(elapsed, 2),
                        "attempts": attempt}
        except Exception as exc:  # noqa: BLE001 - this IS the reachability signal
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(BASE_DELAY_S * (2 ** (attempt - 1)))
    return {"ok": False, "error": last_err, "attempts": MAX_ATTEMPTS}


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat()}
    for name, url in TARGETS.items():
        record[name] = _probe(url)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
