"""Bulk per-county PARCEL INVENTORY — download every parcel for each in-scope
county into a local SQLite cache, so any property can be enriched instantly
(owner / mailing / situs / value) and we hold a complete county footprint.

Per-listing GIS enrichment only ever resolves parcels we already found in a
court event. This module pulls the WHOLE county parcel layer via standard
ArcGIS pagination (resultOffset/resultRecordCount), through the shared
rate-limited client (so the bulk sweep is polite per-host). Run monthly.

Coverage: all 18 in-scope counties. 16 use their COUNTY_GIS layer; Anderson +
Cherokee SC (no standalone owner/mailing layer) use the statewide SCDOT
SC_Parcels MapServer layer.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

import structlog

from .enrichment_arcgis import FIELD_ALIASES, SC_LAYER, SCDOT_BASE, _pick
from .enrichment_owner_mailing import COUNTY_GIS, _extract_value, _join
from .http_client import client

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "parcel_inventory.db"
_PAGE = 1000  # ArcGIS commonly caps maxRecordCount at 1000-2000


def _layers() -> dict[tuple[str, str], dict]:
    """(state,county) -> spec {url, parcel, owner, situs, mail, mail_state}."""
    out: dict[tuple[str, str], dict] = {}
    for key, spec in COUNTY_GIS.items():
        state, county = key.split(":", 1)
        out[(state, county)] = dict(spec)
    # Anderson + Cherokee SC: no standalone layer -> statewide SCDOT parcel layer
    for county in ("Anderson", "Cherokee"):
        lid = SC_LAYER.get(county)
        if lid is not None:
            out[("SC", county)] = {
                "url": f"{SCDOT_BASE}/{lid}",
                "parcel": None, "owner": None, "situs": None,  # discover via FIELD_ALIASES
                "scdot": True,
            }
    return out


def _extract(attrs: dict, spec: dict) -> dict:
    """Pull parcel_id / owner / situs / mailing / value from one feature."""
    if spec.get("parcel"):
        parcel = str(attrs.get(spec["parcel"]) or "").strip()
    else:
        parcel = str(_pick(attrs, FIELD_ALIASES["parcel_id"]) or "").strip()
    if spec.get("owner"):
        owner = _join(attrs, spec["owner"])
    else:
        owner = str(_pick(attrs, FIELD_ALIASES["owner_name"]) or "").strip()
    situs = _join(attrs, spec["situs"]) if spec.get("situs") else (
        str(_pick(attrs, FIELD_ALIASES["site_address"]) or "").strip())
    mail = _join(attrs, spec["mail"]) if spec.get("mail") else ""
    return {
        "parcel_id": parcel or None,
        "owner": owner or None,
        "situs": situs or None,
        "mail": mail or None,
        "value": _extract_value(attrs),
    }


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS parcels (
            state TEXT, county TEXT, parcel_id TEXT,
            owner TEXT, situs TEXT, mail TEXT, value REAL,
            updated_at TEXT,
            PRIMARY KEY (state, county, parcel_id)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_owner ON parcels(state, county, owner)")
    return con


async def _pull_page(http, base: str, offset: int, where: str = "1=1") -> tuple[list[dict], bool]:
    url = base.rstrip("/") + "/query"
    params = {"where": where, "outFields": "*", "returnGeometry": "false",
              "resultOffset": str(offset), "resultRecordCount": str(_PAGE), "f": "json"}
    r = await http.get(url, params=params, timeout=60.0)
    if r.status_code != 200:
        return [], False
    j = r.json()
    feats = [f.get("attributes", {}) for f in (j.get("features") or [])]
    return feats, bool(j.get("exceededTransferLimit"))


async def pull_county(state: str, county: str, spec: dict, *,
                      max_pages: int = 400) -> int:
    """Page through one county's parcel layer; upsert all parcels. Returns count."""
    con = _connect()
    ts = _now_iso()
    total = 0
    seen_parcels: set[str] = set()
    # Statewide/shared layers (e.g. Cleveland via NC OneMap) MUST be county-
    # filtered or they pull the whole state mislabeled as this county. Layers
    # that are already per-county (SCDOT per-id, county-specific hosts) have no
    # county_field and use 1=1.
    cf = spec.get("county_field")
    where = f"UPPER({cf})='{county.upper()}'" if cf else "1=1"
    try:
        async with client(timeout=60.0) as http:
            offset, page = 0, 0
            while page < max_pages:
                try:
                    feats, more = await _pull_page(http, spec["url"], offset, where)
                except Exception:
                    log.warning("parcel_inv.page_failed", county=county, offset=offset)
                    break
                if not feats:
                    break
                rows = []
                for a in feats:
                    e = _extract(a, spec)
                    pid = e["parcel_id"]
                    if not pid or pid in seen_parcels:
                        continue
                    seen_parcels.add(pid)
                    rows.append((state, county, pid, e["owner"], e["situs"],
                                 e["mail"], e["value"], ts))
                con.executemany(
                    "INSERT OR REPLACE INTO parcels VALUES (?,?,?,?,?,?,?,?)", rows)
                con.commit()
                total += len(rows)
                page += 1
                if not more:
                    break
                offset += _PAGE
    finally:
        con.close()
    log.info("parcel_inv.county_done", state=state, county=county, parcels=total)
    return total


async def build_inventory(only: Optional[list[tuple[str, str]]] = None) -> dict[str, int]:
    """Pull all in-scope counties (or a subset). Returns {county: parcel_count}."""
    layers = _layers()
    targets = only or list(layers)
    counts: dict[str, int] = {}
    for (state, county) in targets:
        spec = layers.get((state, county))
        if not spec:
            continue
        counts[f"{state}:{county}"] = await pull_county(state, county, spec)
    return counts


# --- lookup API for enrichment to hit the cache first ----------------------
def lookup_parcel(state: str, county: str, parcel_id: str) -> Optional[dict]:
    if not (DB_PATH.exists() and parcel_id):
        return None
    con = _connect()
    try:
        cur = con.execute(
            "SELECT parcel_id, owner, situs, mail, value FROM parcels "
            "WHERE state=? AND county=? AND parcel_id=?", (state, county, parcel_id))
        row = cur.fetchone()
    finally:
        con.close()
    if not row:
        return None
    return {"parcel_id": row[0], "owner": row[1], "situs": row[2],
            "mail": row[3], "value": row[4]}


def inventory_stats() -> dict[str, int]:
    if not DB_PATH.exists():
        return {}
    con = _connect()
    try:
        return {f"{s}:{c}": n for s, c, n in con.execute(
            "SELECT state, county, COUNT(*) FROM parcels GROUP BY state, county")}
    finally:
        con.close()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
