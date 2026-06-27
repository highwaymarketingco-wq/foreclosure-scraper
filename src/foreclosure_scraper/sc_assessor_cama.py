"""SC CAMA value + specs from each county's FREE bulk Assessor source.

The live SCDOT statewide parcel layer carries NO value/sqft for these counties,
so the parcel inventory is value-less there. This module ingests each county's
own free bulk assessor export into a local table keyed by TMS and by normalized
address, so enrichment_sc_cama can backfill a real value + specs + condition.

Two ingest modes (the spec's "kind" picks the path):
  * "csv"    — Open Data Hub Assessor Extract CSV (Spartanburg). Carries CLEAN
               appraised value (land + building), beds/baths/year, condition.
  * "arcgis" — county ArcGIS REST parcel layer paged via /query (Anderson).
               Carries appraised MRKT_VALUE + TMS + address + sale, but NO
               heated sqft (no county GIS layer exposes it) → VALUE only.

NEITHER source carries heated sqft for these counties — that lives only on the
per-parcel qPublic CARD (see project_sc_data_landscape memory), so this powers
VALUE + SPECS + CONDITION, not $/sqft comps.

NOT VIABLE for bulk value (audited 2026-06, see notes in SC_CAMA below):
  Oconee, Pickens, Laurens — every free GIS parcel layer is cadastral only
  (TMS/acres/deed) or carries sale price but no appraised value or sqft. Their
  value+sqft is locked behind per-parcel qPublic cards, handled on-demand by the
  assessor_card enricher, not here.

Run monthly via scripts/build_sc_assessor_cama.py.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import ssl
import urllib.parse
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
        "kind": "csv",
        "csv_url": "https://www.arcgis.com/sharing/rest/content/items/1f190ebd48c1402a918c3bc315431a1b/data",
        "tms_col": "GISParcelNumber", "map_col": "MAPNUMBER", "addr_col": "StreetAddress",
        "land_val_col": "CurrentAppraisedLandValue", "bldg_val_col": "CurrentAppraisedBuildingValue",
        "year_col": "YearBuilt", "beds_col": "BedRooms", "fullbath_col": "FullBaths",
        "halfbath_col": "HalfBaths", "cond_col": "ConditionFactor", "grade_col": "BuildingGrade",
        "btype_col": "BuildingType", "saledate_col": "SaleDate", "story_col": "StoryHeight",
    },
    # Anderson County free ArcGIS REST parcel layer (county property viewer).
    # Live-verified 2026-06: 117,435 parcels with MRKT_VALUE>0; TMS is the 10-char
    # board parcel_id (zero-padded). MRKT_VALUE = total appraised market value.
    # No heated-sqft field exists on ANY Anderson GIS layer → market_value only.
    # The total-value-bearing market field (vs land-only) is MRKT_VALUE itself, so
    # bldg_val_col is unused and land_val_col carries the whole figure.
    ("SC", "Anderson"): {
        "kind": "arcgis",
        "layer_url": "https://propertyviewer.andersoncountysc.org/arcgis/rest/services/NewPropertyViewer/MapServer/5",
        "tms_field": "TMS", "addr_field": "PHYS_ADDR", "value_field": "MRKT_VALUE",
        "saleyear_field": "SALE_YEAR", "tms_width": 10,
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
        building_type TEXT, sale_date TEXT, street_address TEXT, story_height REAL, updated_at TEXT,
        PRIMARY KEY (state, county, tms))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cama_map ON sc_cama(state, county, map_digits)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cama_addr ON sc_cama(state, county, address_norm)")
    return con


def _blank_rec() -> dict:
    """A record with every stored field defaulted, so each ingest path only has
    to fill the fields its source actually carries."""
    return {"tms": "", "map_digits": "", "address_norm": "", "street_address": "",
            "market_value": 0.0, "year_built": None, "beds": None, "baths": None,
            "condition_code": None, "condition_distressed": 0, "grade": None,
            "building_type": None, "sale_date": None, "story_height": None}


def _store_records(state: str, county: str, best: dict[str, dict]) -> int:
    ts = datetime.utcnow().isoformat()
    con = _connect()
    try:
        con.execute("DELETE FROM sc_cama WHERE state=? AND county=?", (state, county))
        con.executemany(
            "INSERT OR REPLACE INTO sc_cama VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(state, county, r["tms"], r["map_digits"], r["address_norm"], r["market_value"],
              r["year_built"], r["beds"], r["baths"], r["condition_code"],
              r["condition_distressed"], r["grade"], r["building_type"], r["sale_date"],
              r["street_address"], r["story_height"], ts) for r in best.values()])
        con.commit()
    finally:
        con.close()
    log.info("sc_cama.stored", county=county, stored=len(best))
    return len(best)


def _build_from_csv(state: str, county: str, spec: dict, *, max_rows: int | None) -> int:
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
        rec = _blank_rec()
        rec.update({
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
            "story_height": _num(row.get(spec["story_col"])),
        })
        # Keep the card with the highest building value per parcel (main structure).
        prev = best.get(tms)
        if prev is None or rec["market_value"] > prev["market_value"]:
            best[tms] = rec
    log.info("sc_cama.parsed", county=county, rows=n, parcels=len(best))
    return _store_records(state, county, best)


def _arcgis_fetch(url: str, *, retries: int = 4) -> dict:
    """GET one ArcGIS /query page as JSON, retrying transient disconnects /
    5xx / timeouts with linear backoff. The county server is reliable on small
    pages but occasionally drops a connection mid-pull."""
    import json as _json
    import time as _time
    last = None
    for attempt in range(retries):
        try:
            resp = urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                          context=_CTX, timeout=120)
            return _json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001 — transient network/server hiccups
            last = e
            _time.sleep(2 * (attempt + 1))
    raise last


def _arcgis_pages(layer_url: str, where: str, fields: list[str], *, page: int = 2000):
    """Yield attribute dicts from an ArcGIS REST feature layer, paging via
    resultOffset until the server stops returning a full page. FREE + public —
    no key, no login, standard /query interface."""
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "where": where, "outFields": ",".join(fields), "returnGeometry": "false",
            "resultOffset": offset, "resultRecordCount": page, "orderByFields": "OBJECTID",
            "f": "json",
        })
        url = f"{layer_url}/query?{params}"
        data = _arcgis_fetch(url)
        feats = data.get("features", [])
        if not feats:
            break
        for f in feats:
            yield f.get("attributes", {})
        if len(feats) < page or not data.get("exceededTransferLimit"):
            break
        offset += page


def _build_from_arcgis(state: str, county: str, spec: dict, *, max_rows: int | None) -> int:
    vf, tf = spec["value_field"], spec["tms_field"]
    af = spec.get("addr_field")
    syf = spec.get("saleyear_field")
    width = int(spec.get("tms_width") or 0)
    fields = ["OBJECTID", tf, vf] + [c for c in (af, syf) if c]
    best: dict[str, dict] = {}
    n = 0
    for attrs in _arcgis_pages(spec["layer_url"], f"{vf} > 0", fields):
        n += 1
        if max_rows and n > max_rows:
            break
        raw_tms = _norm_tms(attrs.get(tf))
        if not raw_tms:
            continue
        # Board parcel_ids drop leading zeros inconsistently, so store BOTH the
        # zero-padded form as the PK tms and the unpadded digits as map_digits.
        # lookup() tries tms then map_digits, so a 9- or 10-digit board id resolves
        # either way.
        tms = raw_tms.zfill(width) if width else raw_tms
        market = _num(attrs.get(vf)) or 0
        if market <= 0:
            continue
        addr = (attrs.get(af) or "").strip() if af else ""
        sale_year = attrs.get(syf) if syf else None
        rec = _blank_rec()
        rec.update({
            "tms": tms, "map_digits": raw_tms.lstrip("0") or raw_tms,
            "address_norm": norm_addr(addr), "street_address": addr,
            "market_value": round(market, 2),
            "sale_date": (f"{int(sale_year)}-01-01" if sale_year else None),
        })
        prev = best.get(tms)
        if prev is None or rec["market_value"] > prev["market_value"]:
            best[tms] = rec
    log.info("sc_cama.parsed", county=county, rows=n, parcels=len(best), source="arcgis")
    return _store_records(state, county, best)


def build_cama_table(state: str, county: str, *, max_rows: int | None = None) -> int:
    spec = SC_CAMA.get((state, county))
    if not spec:
        return 0
    kind = spec.get("kind", "csv")
    if kind == "arcgis":
        return _build_from_arcgis(state, county, spec, max_rows=max_rows)
    return _build_from_csv(state, county, spec, max_rows=max_rows)


_FIELDS = ("market_value", "year_built", "beds", "baths", "condition_code",
           "condition_distressed", "grade", "building_type", "sale_date", "street_address",
           "story_height")


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
            # Try the digits as-is, the leading-zero-stripped form (map_digits),
            # and common zero-padded widths, so 9- vs 10-digit board ids resolve
            # regardless of how leading zeros were preserved upstream.
            stripped = pid.lstrip("0") or pid
            variants = [pid, stripped, pid.zfill(10), pid.zfill(11)]
            seen = set()
            for v in variants:
                if v in seen:
                    continue
                seen.add(v)
                row = con.execute(
                    f"SELECT {cols} FROM sc_cama WHERE state=? AND county=? AND (tms=? OR map_digits=?)",
                    (state, county, v, v)).fetchone()
                if row:
                    break
        if not row and street_address:
            an = norm_addr(street_address)
            if an:
                row = con.execute(f"SELECT {cols} FROM sc_cama WHERE state=? AND county=? AND address_norm=?",
                                  (state, county, an)).fetchone()
        return dict(zip(_FIELDS, row)) if row else None
    finally:
        con.close()
