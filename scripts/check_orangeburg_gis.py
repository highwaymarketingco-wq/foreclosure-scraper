#!/usr/bin/env python3
"""Reachability probe for Orangeburg County SC's own GIS server (gis2.orangeburgcounty.org).

2026-10-20: this is NOT a WAF/CAPTCHA case like Dorchester's -- it is a raw TCP
connect failure. From the Mac (residential IP) every request times out with no
TLS handshake at all (curl exit 28, ~15-25s). From the Oracle VM (datacenter IP)
the connection is actively refused in <1s (curl exit 7). Two different failure
modes from two different networks means this is the county's own
firewall/server being down or blocking both IP classes, not a transient
network blip (those self-heal and look the same from both hosts) and not
something curl_cffi's Chrome-TLS impersonation can work around (the TCP layer
never completes, so there is no WAF response to impersonate past). The
`county_records_matrix.json` SC/Orangeburg.gis entry already recorded this
same host as "Connection timed out" on 2026-10-07; this confirms it is STILL
down 13 days later.

Why this host matters and shouldn't be abandoned outright: it is the ONLY
known home for Orangeburg's land-use and CAMA/value layers, discovered
2026-10-20 by reading the AGOL web-map configs behind the county's own
"CompLandUse_map" / "CurrentLandUse_byParcel_map" items (owner wjeffcoat_oc).
Those maps point at:
  - gis2.orangeburgcounty.org/dataportal/rest/services/CurrentLandUse/MapServer
  - gis2.orangeburgcounty.org/dataportal/rest/services/FutureLandUse/MapServer
  - gis2.orangeburgcounty.org/dataportal/rest/services/ComprehensiveLandUse/MapServer
  - gis2.orangeburgcounty.org/dataportal/rest/services/CLU_mtc/MapServer (the
    assessor/CAMA parcel popup -- the most likely home of a real value field)
None of these are mirrored to the county's AGOL hosted account (only the Tax
Parcel Map and Roads layers are, as "_WFL1" replicas) -- they exist ONLY on
this on-prem server, so there is no live workaround today. The sibling host
arcserver2.orangeburgcounty.org (serving scanned old property-card PDFs,
referenced from the AGOL AssessorPropCards_ExportTable) is ALSO unreachable,
confirming this is a whole-server/firewall outage, not one bad hostname.

Run manually or on a schedule; appends one JSON line per run to
logs/orangeburg_gis_health_check.log. When CurrentLandUse or CLU_mtc comes
back (`ok: true`), that is the signal to resume the gap_matrix assessed_value
/ vacant_lot build for Orangeburg (see docs/county_records/county_records_matrix.json
SC/Orangeburg.gis.notes for the full writeup).

    python scripts/check_orangeburg_gis.py
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "logs" / "orangeburg_gis_health_check.log"

TARGETS = {
    "gis2_currentlanduse": (
        "https://gis2.orangeburgcounty.org/dataportal/rest/services/"
        "CurrentLandUse/MapServer?f=json"
    ),
    "gis2_clu_mtc_cama_popup": (
        "https://gis2.orangeburgcounty.org/dataportal/rest/services/"
        "CLU_mtc/MapServer?f=json"
    ),
    "arcserver2_oldpropcard": "https://arcserver2.orangeburgcounty.org/",
}

MAX_ATTEMPTS = 3
BASE_DELAY_S = 4.0
TCP_CONNECT_TIMEOUT_S = 10.0


def _tcp_reachable(host: str, port: int) -> tuple[bool, str | None]:
    """Raw TCP connect, separate from the HTTP attempt, so a dead server at the
    socket layer (this county's failure mode) is distinguished from a live
    server returning an HTTP error."""
    try:
        with socket.create_connection((host, port), timeout=TCP_CONNECT_TIMEOUT_S):
            return True, None
    except Exception as exc:  # noqa: BLE001 - this IS the reachability signal
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def _probe(url: str) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    tcp_ok, tcp_err = _tcp_reachable(host, port)
    if not tcp_ok:
        return {"ok": False, "stage": "tcp_connect", "error": tcp_err}

    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                elapsed = time.monotonic() - t0
                return {"ok": resp.status == 200, "stage": "http",
                        "status": resp.status, "elapsed_s": round(elapsed, 2),
                        "attempts": attempt}
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(BASE_DELAY_S * (2 ** (attempt - 1)))
    return {"ok": False, "stage": "http", "error": last_err, "attempts": MAX_ATTEMPTS}


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
