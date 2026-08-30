#!/usr/bin/env python3
"""PROOF-OF-CONCEPT: bulk-download a county parcel layer once -> local SQLite ->
enrich board leads by an in-memory JOIN instead of per-lead live GIS queries.

Demonstrates the speedup that would turn the multi-hour GIS/resolver phase into
minutes. Buncombe NC (open ArcGIS, ~135k parcels). Read-only; touches no board.
"""
from __future__ import annotations
import asyncio, json, re, sqlite3, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.http_client import get_text  # noqa: E402

LAYER = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
FIELDS = "pin,pinnum,owner,Address,TotalMarketValue,TaxValue,AppraisedValue,Acreage"
DB = Path(__file__).resolve().parent.parent / "data" / "parcel_cache" / "buncombe.sqlite"
PAGE = 2000


def _norm(pin) -> str:
    return re.sub(r"[^0-9a-z]", "", str(pin or "").lower())


async def download() -> list[dict]:
    rows, offset = [], 0
    while True:
        url = (f"{LAYER}?where=1=1&outFields={FIELDS}&returnGeometry=false"
               f"&resultOffset={offset}&resultRecordCount={PAGE}&f=json")
        data = json.loads(await get_text(url, timeout=40, impersonate=True))
        feats = data.get("features") or []
        rows.extend(a["attributes"] for a in feats)
        if len(feats) < PAGE and not data.get("exceededTransferLimit"):
            break
        offset += PAGE
        if offset > 500_000:  # safety
            break
    return rows


def build_db(rows: list[dict]) -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE parcels(pin TEXT, owner TEXT, address TEXT,
                   market_value REAL, tax_value REAL, acreage REAL)""")
    con.executemany(
        "INSERT INTO parcels VALUES(?,?,?,?,?,?)",
        [(_norm(r.get("pin") or r.get("pinnum")), r.get("owner"), r.get("Address"),
          r.get("TotalMarketValue") or r.get("AppraisedValue"), r.get("TaxValue"),
          r.get("Acreage")) for r in rows])
    con.execute("CREATE INDEX idx_pin ON parcels(pin)")
    con.commit(); con.close()


def demo_join():
    # board Buncombe leads (current pre-run board), join locally by parcel_id
    board = json.load(open(Path(__file__).resolve().parent.parent / "docs" / "listings_slim.json"))
    R = board if isinstance(board, list) else board.get("listings", board)
    bunc = [r for r in R if r.get("county") == "Buncombe" and (r.get("parcel_id") or "").strip()]
    con = sqlite3.connect(DB)
    t0 = time.time()
    filled = miss = 0
    for r in bunc:
        row = con.execute("SELECT owner,address,market_value,tax_value FROM parcels WHERE pin=?",
                          (_norm(r.get("parcel_id")),)).fetchone()
        if row and row[0]:
            filled += 1
        else:
            miss += 1
    dt = time.time() - t0
    con.close()
    return len(bunc), filled, miss, dt


async def main():
    print(f"Downloading Buncombe parcel layer (~135k rows, {PAGE}/page)...")
    t0 = time.time()
    rows = await download()
    dl = time.time() - t0
    print(f"  downloaded {len(rows):,} parcels in {dl:.1f}s")
    t0 = time.time()
    build_db(rows)
    print(f"  built local SQLite ({DB.stat().st_size/1e6:.1f} MB) + pin index in {time.time()-t0:.1f}s")
    n, filled, miss, dt = demo_join()
    print(f"\nJOIN {n:,} board Buncombe leads against the local table:")
    print(f"  matched+owner-filled: {filled:,} | no-match: {miss:,}")
    print(f"  LOCAL JOIN TIME: {dt*1000:.0f} ms  ({1000*dt/max(1,n):.2f} ms/lead)")
    print(f"\n=== speedup vs live per-lead GIS ===")
    print(f"  live: {n:,} leads x ~1.5s/query = ~{n*1.5/60:.0f} min of runtime, EVERY run")
    print(f"  cached: ~{dl:.0f}s one-time download + {dt*1000:.0f}ms join = seconds, reused across runs")

if __name__ == "__main__":
    asyncio.run(main())
