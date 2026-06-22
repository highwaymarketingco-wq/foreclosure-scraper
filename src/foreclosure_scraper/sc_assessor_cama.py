"""SC CAMA value + specs from the county Open Data Hub Assessor CSV.

The live SCDOT numeric fields are corrupt for Spartanburg, so the parcel
inventory's value there is unreliable. This ingests the county's free bulk
Assessor Extract CSV — which carries CLEAN appraised value (land + building),
beds/baths/year, and a condition code — into a local table keyed by TMS and by
normalized address, so enrichment_sc_cama can backfill a real value + specs +
condition onto SC leads. (The CSV has NO sale price and NO heated sqft — verified
by name — so this powers VALUE + SPECS + CONDITION, not $/sqft comps. See
project_sc_data_landscape memory.)

Run monthly via scripts/build_sc_assessor_cama.py.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path

import structlog

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sc_cama.db"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126"}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Condition codes that signal distress (mirrors enrichment_owner_mailing).
_POOR_CONDITION = {"PR", "VP", "DL", "UN", "POOR", "VERY POOR", "DILAPIDATED", "UNSOUND"}

SC_CAMA: dict[tuple[str, str], dict] = {
    ("SC", "Spartanburg"): {
        "csv_url": "https://www.arcgis.com/sharing/rest/content/items/1f190ebd48c1402a918c3bc315431a1b/data",
        "tms_col": "GISParcelNumber", "map_col": "MAPNUMBER", "addr_col": "StreetAddress",
        "land_val_col": "CurrentAppraisedLandValue", "bldg_val_col": "CurrentAppraisedBuildingValue",
        "year_col": "YearBuilt", "beds_col": "BedRooms", "fullbath_col": "FullBaths",
        "halfbath_col": "HalfBaths", "cond_col": "ConditionFactor", "grade_col": "BuildingGrade",
        "btype_col": "BuildingType", "saledate_col": "SaleDate",
    },
}

_SUFFIX = {"ROAD": "RD", "STREET": "ST", "DRIVE": "DR", "AVENUE": "AVE", "LANE": "LN",
           "COURT": "CT", "BOULEVARD": "BLVD", "PLACE": "PL", "CIRCLE": "CIR",
           "HIGHWAY": "HWY", "PARKWAY": "PKWY", "TERRACE": "TER", "TRAIL": "TRL"}


def _norm_tms(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def norm_addr(s) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper())
    return " ".join(_SUFFIX.get(t, t) for t in s.split()).strip()


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS sc_cama (
        state TEXT, county TEXT, tms TEXT, map_digits TEXT, address_norm TEXT,
        market_value REAL, year_built INTEGER, beds REAL, baths REAL,
        condition_code TEXT, condition_distressed INTEGER, grade TEXT,
        building_type TEXT, sale_date TEXT, street_address TEXT, updated_at TEXT,
        PRIMARY KEY (state, county, tms))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cama_map ON sc_cama(state, county, map_digits)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cama_addr ON sc_cama(state, county, address_norm)")
    return con


def build_cama_table(state: str, county: str, *, max_rows: int | None = None) -> int:
    spec = SC_CAMA.get((state, county))
    if not spec:
        return 0
    resp = urllib.request.urlopen(urllib.request.Request(spec["csv_url"], headers=_UA),
                                  context=_CTX, timeout=300)
    reader = csv.DictReader(io.TextIOWrapper(resp, encoding="latin-1", newline=""))
    best: dict[str, dict] = {}
    n = 0
    for row in reader:
        n += 1
        if max_rows and n > max_rows:
            break
        tms = _norm_tms(row.get(spec["tms_col"]))
        if not tms:
            continue
        land = _num(row.get(spec["land_val_col"])) or 0
        bldg = _num(row.get(spec["bldg_val_col"])) or 0
        market = land + bldg
        if market <= 0:
            continue
        cond = (row.get(spec["cond_col"]) or "").strip().upper()
        fb = _num(row.get(spec["fullbath_col"])) or 0
        hb = _num(row.get(spec["halfbath_col"])) or 0
        rec = {
            "tms": tms, "map_digits": _norm_tms(row.get(spec["map_col"])),
            "address_norm": norm_addr(row.get(spec["addr_col"])),
            "street_address": (row.get(spec["addr_col"]) or "").strip(),
            "market_value": round(market, 2),
            "year_built": int(_num(row.get(spec["year_col"])) or 0) or None,
            "beds": _num(row.get(spec["beds_col"])),
            "baths": (fb + 0.5 * hb) or None,
            "condition_code": cond or None,
            "condition_distressed": 1 if cond in _POOR_CONDITION else 0,
            "grade": (row.get(spec["grade_col"]) or "").strip() or None,
            "building_type": (row.get(spec["btype_col"]) or "").strip() or None,
            "sale_date": (row.get(spec["saledate_col"]) or "").strip()[:10] or None,
        }
        # Keep the card with the highest building value per parcel (main structure).
        prev = best.get(tms)
        if prev is None or rec["market_value"] > prev["market_value"]:
            best[tms] = rec
    log.info("sc_cama.parsed", county=county, rows=n, parcels=len(best))
    ts = datetime.utcnow().isoformat()
    con = _connect()
    try:
        con.execute("DELETE FROM sc_cama WHERE state=? AND county=?", (state, county))
        con.executemany(
            "INSERT OR REPLACE INTO sc_cama VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(state, county, r["tms"], r["map_digits"], r["address_norm"], r["market_value"],
              r["year_built"], r["beds"], r["baths"], r["condition_code"],
              r["condition_distressed"], r["grade"], r["building_type"], r["sale_date"],
              r["street_address"], ts) for r in best.values()])
        con.commit()
    finally:
        con.close()
    log.info("sc_cama.stored", county=county, stored=len(best))
    return len(best)


_FIELDS = ("market_value", "year_built", "beds", "baths", "condition_code",
           "condition_distressed", "grade", "building_type", "sale_date", "street_address")


def has_data(state: str, county: str) -> bool:
    if not DB_PATH.exists():
        return False
    con = _connect()
    try:
        return con.execute("SELECT 1 FROM sc_cama WHERE state=? AND county=? LIMIT 1",
                           (state, county)).fetchone() is not None
    finally:
        con.close()


def lookup(state: str, county: str, *, parcel_id: str | None = None,
           street_address: str | None = None) -> dict | None:
    if not DB_PATH.exists():
        return None
    con = _connect()
    try:
        cols = ", ".join(_FIELDS)
        row = None
        pid = _norm_tms(parcel_id)
        if pid:
            row = con.execute(f"SELECT {cols} FROM sc_cama WHERE state=? AND county=? AND tms=?",
                              (state, county, pid)).fetchone()
            if not row:
                row = con.execute(f"SELECT {cols} FROM sc_cama WHERE state=? AND county=? AND map_digits=?",
                                  (state, county, pid)).fetchone()
        if not row and street_address:
            an = norm_addr(street_address)
            if an:
                row = con.execute(f"SELECT {cols} FROM sc_cama WHERE state=? AND county=? AND address_norm=?",
                                  (state, county, an)).fetchone()
        return dict(zip(_FIELDS, row)) if row else None
    finally:
        con.close()
