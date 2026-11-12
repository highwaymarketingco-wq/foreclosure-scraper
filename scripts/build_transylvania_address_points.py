#!/usr/bin/env python3
"""Build data/address_points/transylvania.sqlite from Transylvania County's own E911 address layer.

WHY. Transylvania's parcel cache "address" is LEGAL_ADDR (a subdivision and lot, "COMMON
AREA-WHITEWATER COVE"), so its leads have a street NAME at best and a house number on 10%.
Verified 2026-09-21 on the county's free public server: the Addresses layer
(https://gis.transylvaniacounty.org/server/rest/services/Addresses/MapServer/0, 27,985 points with a
PARCELNUM) carries the numbered address, the postal city and the zip, keyed by the 13-digit undashed
PIN that parcel_cache normalizes board ids to. A 150-parcel sample found an address point for 3% of the
vacant-land leads (land has no house number) and 18% of the other Transylvania leads.

A parcel with more than one distinct address (a duplex, "1575" and "1577 BLUE RIDGE RD") is left out:
choosing one would be a guess. fill_address_from_parcel.py reads the result as its address-point overlay.

    python scripts/build_transylvania_address_points.py          # ~30 polite requests, then writes the sqlite
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
URL = "https://gis.transylvaniacounty.org/server/rest/services/Addresses/MapServer/0/query"
OUT = REPO / "data" / "address_points" / "transylvania.sqlite"
FIELDS = "PARCELNUM,FULLADDR,POSTALCOM,POSTALZIP"
PAGE = 1000


def build_rows(features) -> dict[str, tuple[str, str | None, str | None]]:
    """{parcel id -> (address, city, zip)} for parcels that have exactly ONE distinct address."""
    seen: dict[str, set] = {}
    for f in features:
        a = f.get("attributes", f)
        pid = "".join(ch for ch in str(a.get("PARCELNUM") or "").lower() if ch.isalnum())
        addr = " ".join(str(a.get("FULLADDR") or "").split())
        if not pid or not addr:
            continue
        city = " ".join(str(a.get("POSTALCOM") or "").split()).title() or None
        zc = "".join(ch for ch in str(a.get("POSTALZIP") or "") if ch.isdigit())[:5] or None
        seen.setdefault(pid, set()).add((addr, city, zc))
    return {pid: next(iter(v)) for pid, v in seen.items() if len(v) == 1}


def _get(params: dict) -> dict:
    req = urllib.request.Request(URL, data=urllib.parse.urlencode(params).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main() -> int:
    expected = _get({"where": "PARCELNUM IS NOT NULL AND PARCELNUM<>''", "returnCountOnly": "true", "f": "json"})["count"]
    feats: list = []
    while len(feats) < expected:
        d = _get({"where": "PARCELNUM IS NOT NULL AND PARCELNUM<>''", "outFields": FIELDS, "returnGeometry": "false",
                  "orderByFields": "OBJECTID", "resultOffset": len(feats), "resultRecordCount": PAGE, "f": "json"})
        got = d.get("features") or []
        if not got:
            break
        feats.extend(got)
        time.sleep(0.5)
    if abs(len(feats) - expected) > max(2, int(expected * 0.001)):
        print(f"INCOMPLETE: downloaded {len(feats):,} of {expected:,}; not writing")
        return 1
    rows = build_rows(feats)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE pts(id TEXT, address TEXT, city TEXT, zip TEXT)")
    con.executemany("INSERT INTO pts VALUES(?,?,?,?)", [(k, *v) for k, v in rows.items()])
    con.execute("CREATE INDEX idx_id ON pts(id)")
    con.commit()
    con.close()
    tmp.replace(OUT)
    print(f"wrote {OUT}: {len(rows):,} single-address parcels from {len(feats):,} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
