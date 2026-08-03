"""SC bulk assessor ROLLS -> local owner + MAILING + SITUS backfill (cached).

The #0 contactability spine (enrichment_owner_mailing) resolves owner/mailing by
firing one ArcGIS `LIKE` query per lead. That path is slow, network-bound, and —
for the two biggest SC mailing gaps — it was pointed at the WRONG data:

  * Spartanburg  the COUNTY_GIS entry used the AGOL `Parcel_and_CAMA_Feb_1_2021`
                 layer, which is a 29,402-row MUNICIPAL extract, not the county
                 roll. 8,919 board leads sit in Spartanburg; a 29k layer can
                 physically only answer ~16% of them.
  * Anderson     had NO county-wide owner layer at all (round 1 found only the
                 ~14k city layer), so every Anderson lead fell through to the
                 statewide SCDOT layer, which is now token-walled.

Both counties publish their FULL roll for free, with owner + taxpayer + previous
owner + MAILING address + situs, and this module ingests them ONCE into a local
SQLite table that the resolver and the owner_mailing enricher read offline:

  * Spartanburg  weekly ``Assessor_Extract.csv`` (ArcGIS Online item
                 1f190ebd48c1402a918c3bc315431a1b, ~123 MB, 97 cols, 181,369
                 card-level rows). Live fallback + confirmation source is the
                 county CAMA FeatureServer
                 maps.spartanburgcounty.org/.../GIS/CAMA_Parcels/FeatureServer/0
                 (same 181,369 rows; CardNumber=1 -> 163,059 primary cards).
  * Anderson     gis.cityofandersonsc.com/.../WaterUtilities/County_Parcels/
                 FeatureServer/0 — 114,516 COUNTY-wide rows (not the city 14k),
                 OWNER_ADDR populated on 113,699.

CACHING (the 123 MB must not move on every run):
  ``build_mailing_table`` first probes the source with a 1-byte ranged GET and
  compares ETag / Last-Modified / Content-Length against ``sc_bulk_meta``. If the
  validator is unchanged, or the row set is younger than the TTL
  (FORECLOSURE_SC_ROLL_TTL_DAYS, default 7), it returns immediately and NOTHING is
  downloaded. The parsed table is the cache — the raw CSV is streamed and
  discarded, so the on-disk cost is the SQLite file, not 123 MB of CSV.

PRIVACY: every query lists explicit ``outFields`` — never ``*`` — so no
sensitive owner field can be pulled in by accident.
FREE + PUBLIC: plain ArcGIS REST / a public ArcGIS Online item. No key, no login,
no CAPTCHA or WAF handling of any kind.

Run via ``scripts/build_sc_parcel_mailing.py`` (weekly is plenty).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

import structlog

from .sc_assessor_cama import norm_addr

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sc_parcel_mailing.db"

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126"}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_POOR_CONDITION = {"PR", "VP", "DL", "UN", "POOR", "VERY POOR", "DILAPIDATED", "UNSOUND", "PF"}

# Spartanburg CSV/FeatureServer columns we actually read. Listed explicitly (never
# `*`) so no unexpected field can be pulled from the layer.
_SPART_FIELDS = [
    "OBJECTID", "MAPNUMBER", "GISParcelNumber", "AccountNumber", "CardNumber",
    "OwnerName", "TaxpayerName", "PreviousOwnerName",
    "StreetAddress", "City", "State", "Zip",
    "PropertyLocation", "StreetNumber", "StreetDirection", "StreetName",
    "StreetCommunity", "StreetZip",
    "CurrentAppraisedLandValue", "CurrentAppraisedBuildingValue",
    "YearBuilt", "LivingArea", "Acreage", "BedRooms", "FullBaths", "HalfBaths",
    "SaleDate", "SaleAmount", "DeedBook", "DeedPage", "LandUse", "ConditionFactor",
]

# Anderson County_Parcels fields. No SSN/DOB-class field exists on this layer and
# none is requested — outFields is explicit by design.
_ANDERSON_FIELDS = [
    "OBJECTID", "TMS", "OWNER", "OWNER_ADDR", "CITY", "ZIPCODE", "PHYS_ADDR",
    "PREV_OWNER", "MRKT_VALUE", "SALE_PRICE", "SALE_YEAR", "DBOOK", "DPAGE",
    "IMPRV", "RATIO",
]

SC_ROLLS: dict[tuple[str, str], dict] = {
    ("SC", "Spartanburg"): {
        "kind": "csv",
        # Weekly county Assessor_Extract (ArcGIS Online item data endpoint).
        "url": "https://www.arcgis.com/sharing/rest/content/items/1f190ebd48c1402a918c3bc315431a1b/data",
        # Live county CAMA FeatureServer — same 181,369 card rows. Used when the
        # CSV item is unreachable, and as the confirmation source.
        "layer_url": "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0",
        "layer_where": "CardNumber=1",
        "fields": _SPART_FIELDS,
        "page": 2000,   # layer maxRecordCount = 2000
    },
    ("SC", "Anderson"): {
        "kind": "arcgis",
        # COUNTY-wide parcels (114,516) — NOT the ~14k city layer.
        "layer_url": "https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/FeatureServer/0",
        "layer_where": "OWNER_ADDR IS NOT NULL AND OWNER_ADDR <> ''",
        "fields": _ANDERSON_FIELDS,
        "page": 1000,   # layer maxRecordCount = 1000
    },
}


# --------------------------------------------------------------------------- utils

def norm_key(s) -> str:
    """Digits-only parcel key. Board parcel_ids arrive dashed OR stripped
    ('7-17-02-041.00' and '7171702041' and '713320362391'), so every join goes
    through the digits form on BOTH sides instead of a LIKE wildcard."""
    return re.sub(r"\D", "", str(s or ""))


def _num(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    return f


def _txt(v) -> str:
    s = str(v).strip() if v is not None else ""
    return "" if s.lower() in ("none", "null", "<null>") else s


_MULTISPACE = re.compile(r"\s{2,}")
_LEADS_WITH_NUM = re.compile(r"^\d")


def clean_situs(raw: str) -> str:
    """Strip the fixed-width SUBDIVISION prefix Anderson pads into PHYS_ADDR.

    Anderson stores 'SPRINGSIDE        300 SPRINGSIDE CIR       ' — subdivision,
    padding, then the real address. Split on the 2+-space gutter and keep the
    last chunk that starts with a house number; if nothing does, keep the whole
    collapsed string (rural/undeveloped parcels carry only a road name).
    """
    s = _txt(raw)
    if not s:
        return ""
    parts = [p.strip() for p in _MULTISPACE.split(s) if p.strip()]
    if not parts:
        return ""
    for p in reversed(parts):
        if _LEADS_WITH_NUM.match(p):
            return p
    return " ".join(parts)


def strip_city_tail(situs: str, city: str) -> str:
    """'1101 PARTRIDGE RD SPARTANBURG' + city 'SPARTANBURG' -> '1101 PARTRIDGE RD'.

    Spartanburg's PropertyLocation appends the StreetCommunity, but board leads
    carry street-only addresses, so the community must come off before the
    address index is built or nothing ever joins."""
    s = _txt(situs)
    c = _txt(city).upper()
    if s and c and s.upper().endswith(c):
        s = s[: len(s) - len(c)].strip()
    return s


def _condition_flag(code: str) -> int:
    return 1 if (code or "").strip().upper() in _POOR_CONDITION else 0


def _split_city_state(v: str) -> tuple[str, str]:
    """Anderson packs 'ANDERSON  SC' into one CITY column."""
    s = _txt(v)
    m = re.match(r"^(.*?)[\s,]+([A-Za-z]{2})$", s)
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return s, ""


def owner_key(name: str) -> str:
    """Loose owner index key: uppercase alphanumerics + single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", _txt(name).upper())).strip()


# --------------------------------------------------------------------------- storage

_COLS = (
    "parcel_key", "alt_key", "parcel_raw", "account", "owner", "taxpayer", "prev_owner",
    "mail_addr", "mail_city", "mail_state", "mail_zip",
    "situs", "situs_street", "situs_norm", "situs_city", "situs_zip",
    "market_value", "year_built", "beds", "baths", "living_sqft", "acreage",
    "sale_date", "sale_amount", "deed_ref", "land_use",
    "condition_code", "condition_distressed", "owner_norm",
)

# Fields lookup() hands back to callers.
_OUT = (
    "parcel_key", "alt_key", "parcel_raw", "owner", "taxpayer", "prev_owner",
    "mail_addr", "mail_city", "mail_state", "mail_zip",
    "situs", "situs_street", "situs_city", "situs_zip",
    "market_value", "year_built", "beds", "baths", "living_sqft", "acreage",
    "sale_date", "sale_amount", "deed_ref", "land_use",
    "condition_code", "condition_distressed",
)


# Column affinities. Getting these wrong is not cosmetic: a 0 written into a TEXT
# column comes back as the string "0", and bool("0") is True — which silently
# flagged EVERY parcel as condition-distressed until this was caught in a live
# smoke (2026-08-03).
_REAL_COLS = {"market_value", "beds", "baths", "living_sqft", "acreage", "sale_amount"}
_INT_COLS = {"year_built", "condition_distressed"}


def _col_decl(c: str) -> str:
    if c in _REAL_COLS:
        return f"{c} REAL"
    if c in _INT_COLS:
        return f"{c} INTEGER"
    return f"{c} TEXT"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(f"""CREATE TABLE IF NOT EXISTS sc_parcel_mailing (
        state TEXT, county TEXT,
        {", ".join(_col_decl(c) for c in _COLS)},
        updated_at TEXT,
        PRIMARY KEY (state, county, parcel_key))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pm_alt ON sc_parcel_mailing(state, county, alt_key)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pm_addr ON sc_parcel_mailing(state, county, situs_norm)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pm_owner ON sc_parcel_mailing(state, county, owner_norm)")
    con.execute("""CREATE TABLE IF NOT EXISTS sc_bulk_meta (
        state TEXT, county TEXT, url TEXT, etag TEXT, last_modified TEXT,
        content_length INTEGER, rows INTEGER, fetched_at TEXT,
        PRIMARY KEY (state, county))""")
    return con


def _blank() -> dict:
    r = {c: None for c in _COLS}
    r.update({"parcel_key": "", "alt_key": "", "situs_norm": "", "owner_norm": "",
              "condition_distressed": 0})
    return r


def _store(state: str, county: str, best: dict[str, dict], meta: dict) -> int:
    ts = datetime.utcnow().isoformat()
    con = _connect()
    try:
        con.execute("DELETE FROM sc_parcel_mailing WHERE state=? AND county=?", (state, county))
        con.executemany(
            f"INSERT OR REPLACE INTO sc_parcel_mailing (state, county, {', '.join(_COLS)}, updated_at) "
            f"VALUES ({', '.join('?' * (len(_COLS) + 3))})",
            [(state, county, *(r[c] for c in _COLS), ts) for r in best.values()])
        con.execute("INSERT OR REPLACE INTO sc_bulk_meta VALUES (?,?,?,?,?,?,?,?)",
                    (state, county, meta.get("url"), meta.get("etag"),
                     meta.get("last_modified"), meta.get("content_length"),
                     len(best), ts))
        con.commit()
    finally:
        con.close()
    log.info("sc_parcel_mailing.stored", county=county, stored=len(best))
    return len(best)


def get_meta(state: str, county: str) -> Optional[dict]:
    if not DB_PATH.exists():
        return None
    con = _connect()
    try:
        row = con.execute(
            "SELECT url, etag, last_modified, content_length, rows, fetched_at "
            "FROM sc_bulk_meta WHERE state=? AND county=?", (state, county)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return dict(zip(("url", "etag", "last_modified", "content_length", "rows", "fetched_at"), row))


def has_data(state: str, county: str) -> bool:
    if not DB_PATH.exists():
        return False
    con = _connect()
    try:
        return con.execute("SELECT 1 FROM sc_parcel_mailing WHERE state=? AND county=? LIMIT 1",
                           (state, county)).fetchone() is not None
    finally:
        con.close()


def covered_counties() -> set[tuple[str, str]]:
    return {k for k in SC_ROLLS if has_data(*k)}


# --------------------------------------------------------------------------- fetching

def _probe(url: str) -> dict:
    """Cheap validator probe: a 1-byte ranged GET. Follows the ArcGIS Online
    302 to storage, whose response carries the real ETag + Last-Modified. Costs
    one byte of body instead of 123 MB."""
    req = urllib.request.Request(url, headers={**_UA, "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=60) as resp:
            h = resp.headers
            cl = h.get("Content-Range", "")
            total = None
            m = re.search(r"/(\d+)$", cl or "")
            if m:
                total = int(m.group(1))
            elif h.get("Content-Length") and resp.status != 206:
                total = int(h["Content-Length"])
            return {"url": url, "etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
                    "content_length": total}
    except Exception as e:  # noqa: BLE001 — probe is best-effort; a miss just means "download"
        log.warning("sc_parcel_mailing.probe_failed", url=url[:80], err=str(e)[:120])
        return {"url": url, "etag": None, "last_modified": None, "content_length": None}


def _unchanged(prev: Optional[dict], probe: dict) -> bool:
    """True when the remote artifact is byte-identical to what we already parsed."""
    if not prev:
        return False
    for field in ("etag", "last_modified", "content_length"):
        p, n = prev.get(field), probe.get(field)
        if p and n:
            return str(p) == str(n)
    return False


def _fresh(prev: Optional[dict], ttl_days: float) -> bool:
    if not prev or not prev.get("fetched_at") or not prev.get("rows"):
        return False
    try:
        age = datetime.utcnow() - datetime.fromisoformat(prev["fetched_at"])
    except (ValueError, TypeError):
        return False
    return age < timedelta(days=ttl_days)


def _fetch_json(url: str, *, retries: int = 4) -> dict:
    import time as _time
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                        context=_CTX, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001 — transient server hiccups
            last = e
            _time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


def arcgis_pages(layer_url: str, where: str, fields: list[str], *, page: int = 1000,
                 max_rows: Optional[int] = None) -> Iterator[dict]:
    """Page an ArcGIS feature layer via resultOffset/resultRecordCount.

    Stops when the server reports exceededTransferLimit=False (or returns a
    short/empty page). outFields is always an explicit list — never `*`."""
    offset = 0
    seen = 0
    while True:
        params = urllib.parse.urlencode({
            "where": where, "outFields": ",".join(fields), "returnGeometry": "false",
            "resultOffset": offset, "resultRecordCount": page,
            "orderByFields": "OBJECTID", "f": "json",
        })
        data = _fetch_json(f"{layer_url.rstrip('/')}/query?{params}")
        feats = data.get("features") or []
        if not feats:
            return
        for f in feats:
            yield f.get("attributes", {})
            seen += 1
            if max_rows and seen >= max_rows:
                return
        if not data.get("exceededTransferLimit"):
            return
        offset += len(feats)


# --------------------------------------------------------------------------- parsers

def _spart_record(row: dict) -> Optional[dict]:
    """One Spartanburg CAMA card (CSV row or FeatureServer attribute dict)."""
    # PK is MAPNUMBER, NOT GISParcelNumber: verified live 2026-08-03, the 163,059
    # primary cards carry 163,047 distinct MAPNUMBERs but only 138,582 distinct
    # GISParcelNumbers — condo/multi-unit parcels share one GIS polygon, so
    # keying on GIS silently collapses ~24k parcels into one row. GIS becomes the
    # (non-unique) alt_key, since board parcel_ids arrive in BOTH formats.
    gis_key = norm_key(row.get("GISParcelNumber"))
    map_key = norm_key(row.get("MAPNUMBER"))
    key = map_key or gis_key
    if not key:
        return None
    city = _txt(row.get("StreetCommunity"))
    situs_full = _txt(row.get("PropertyLocation"))
    # Prefer the discrete street components (clean); fall back to trimming the
    # community off PropertyLocation.
    street = " ".join(p for p in (_txt(row.get("StreetNumber")),
                                  _txt(row.get("StreetDirection")),
                                  _txt(row.get("StreetName"))) if p).strip()
    if not street:
        street = strip_city_tail(situs_full, city)
    land = _num(row.get("CurrentAppraisedLandValue")) or 0.0
    bldg = _num(row.get("CurrentAppraisedBuildingValue")) or 0.0
    fb = _num(row.get("FullBaths")) or 0.0
    hb = _num(row.get("HalfBaths")) or 0.0
    yb = int(_num(row.get("YearBuilt")) or 0) or None
    book, page = _txt(row.get("DeedBook")), _txt(row.get("DeedPage"))
    cond = _txt(row.get("ConditionFactor")).upper()
    owner = _txt(row.get("OwnerName"))
    rec = _blank()
    rec.update({
        "parcel_key": key, "alt_key": (gis_key if key != gis_key else "") or "",
        # RAW dashed MAPNUMBER ('7-17-02-041.00') — the qPublic KeyValue the
        # Spartanburg assessor-card adapter expects (parcel_resolver._SC_KEY_FIELD).
        "parcel_raw": _txt(row.get("MAPNUMBER")) or _txt(row.get("GISParcelNumber")) or key,
        "account": _txt(row.get("AccountNumber")),
        "owner": owner or None, "taxpayer": _txt(row.get("TaxpayerName")) or None,
        "prev_owner": _txt(row.get("PreviousOwnerName")) or None,
        "mail_addr": _txt(row.get("StreetAddress")) or None,
        "mail_city": _txt(row.get("City")) or None,
        "mail_state": (_txt(row.get("State")).upper() or None),
        "mail_zip": _txt(row.get("Zip")) or None,
        "situs": situs_full or street or None, "situs_street": street or None,
        "situs_norm": norm_addr(street), "situs_city": city or None,
        "situs_zip": _txt(row.get("StreetZip")) or None,
        "market_value": round(land + bldg, 2) or None,
        "year_built": yb if yb and 1800 <= yb <= 2035 else None,
        "beds": _num(row.get("BedRooms")) or None,
        "baths": (fb + 0.5 * hb) or None,
        "living_sqft": _num(row.get("LivingArea")) or None,
        "acreage": _num(row.get("Acreage")) or None,
        "sale_date": (_txt(row.get("SaleDate"))[:10] or None),
        "sale_amount": _num(row.get("SaleAmount")) or None,
        "deed_ref": (f"{book}/{page}" if book and page else None),
        "land_use": _txt(row.get("LandUse")) or None,
        "condition_code": cond or None, "condition_distressed": _condition_flag(cond),
        "owner_norm": owner_key(owner),
    })
    rec["_card"] = int(_num(row.get("CardNumber")) or 0)
    rec["_bldg"] = bldg
    return rec


def _anderson_record(row: dict) -> Optional[dict]:
    key = norm_key(row.get("TMS"))
    if not key:
        return None
    city, st = _split_city_state(row.get("CITY"))
    street = clean_situs(row.get("PHYS_ADDR"))
    owner = _txt(row.get("OWNER"))
    book, page = _txt(row.get("DBOOK")), _txt(row.get("DPAGE"))
    sale_year = _num(row.get("SALE_YEAR"))
    rec = _blank()
    rec.update({
        # Board Anderson parcel_ids arrive 9 or 10 digits, so the PK is the
        # zero-padded 10 and alt_key is the unpadded form.
        "parcel_key": key.zfill(10), "alt_key": key.lstrip("0") or key,
        # Anderson's assessor adapter queries `where TMS=<digits>` — raw is the
        # unpadded TMS exactly as the county publishes it.
        "parcel_raw": _txt(row.get("TMS")) or key,
        "owner": owner or None, "prev_owner": _txt(row.get("PREV_OWNER")) or None,
        "mail_addr": _txt(row.get("OWNER_ADDR")) or None,
        "mail_city": city or None, "mail_state": st or None,
        "mail_zip": _txt(row.get("ZIPCODE")) or None,
        "situs": street or None, "situs_street": street or None,
        "situs_norm": norm_addr(street),
        "market_value": _num(row.get("MRKT_VALUE")) or None,
        "sale_amount": _num(row.get("SALE_PRICE")) or None,
        "sale_date": (f"{int(sale_year)}-01-01" if sale_year and sale_year > 1800 else None),
        "deed_ref": (f"{book}/{page}" if book and page else None),
        "land_use": _txt(row.get("RATIO")) or None,
        "owner_norm": owner_key(owner),
    })
    rec["_card"] = 1
    rec["_bldg"] = rec["market_value"] or 0.0
    return rec


_PARSERS = {("SC", "Spartanburg"): _spart_record, ("SC", "Anderson"): _anderson_record}


def _keep(best: dict[str, dict], rec: dict) -> None:
    """Collapse card-level rows to one row per parcel: CardNumber=1 wins, then
    the highest building value (the main structure)."""
    k = rec["parcel_key"]
    prev = best.get(k)
    if prev is None:
        best[k] = rec
        return
    new_rank = (1 if rec.get("_card") == 1 else 0, rec.get("_bldg") or 0.0)
    old_rank = (1 if prev.get("_card") == 1 else 0, prev.get("_bldg") or 0.0)
    if new_rank > old_rank:
        best[k] = rec


def _strip_scratch(best: dict[str, dict]) -> dict[str, dict]:
    for r in best.values():
        r.pop("_card", None)
        r.pop("_bldg", None)
    return best


# --------------------------------------------------------------------------- build

def _build_from_csv(state: str, county: str, spec: dict, *, max_rows: Optional[int]) -> dict[str, dict]:
    parse = _PARSERS[(state, county)]
    best: dict[str, dict] = {}
    n = 0
    resp = urllib.request.urlopen(urllib.request.Request(spec["url"], headers=_UA),
                                  context=_CTX, timeout=600)
    reader = csv.DictReader(io.TextIOWrapper(resp, encoding="latin-1", newline=""))
    for row in reader:
        n += 1
        if max_rows and n > max_rows:
            break
        rec = parse(row)
        if rec:
            _keep(best, rec)
    log.info("sc_parcel_mailing.parsed", county=county, rows=n, parcels=len(best), source="csv")
    return best


def _build_from_arcgis(state: str, county: str, spec: dict, *, max_rows: Optional[int]) -> dict[str, dict]:
    parse = _PARSERS[(state, county)]
    best: dict[str, dict] = {}
    n = 0
    for attrs in arcgis_pages(spec["layer_url"], spec.get("layer_where") or "1=1",
                              spec["fields"], page=int(spec.get("page") or 1000),
                              max_rows=max_rows):
        n += 1
        rec = parse(attrs)
        if rec:
            _keep(best, rec)
    log.info("sc_parcel_mailing.parsed", county=county, rows=n, parcels=len(best), source="arcgis")
    return best


def build_mailing_table(state: str, county: str, *, max_rows: Optional[int] = None,
                        force: bool = False, ttl_days: Optional[float] = None) -> int:
    """Refresh one county's owner/mailing/situs table. Returns rows stored.

    Skips ALL network transfer when the local copy is younger than the TTL, and
    skips the download (but not the cheap probe) when the source's
    ETag/Last-Modified/Content-Length is unchanged."""
    spec = SC_ROLLS.get((state, county))
    if not spec:
        return 0
    if ttl_days is None:
        ttl_days = float(os.environ.get("FORECLOSURE_SC_ROLL_TTL_DAYS", "7"))
    prev = get_meta(state, county)
    if not force and _fresh(prev, ttl_days) and has_data(state, county):
        log.info("sc_parcel_mailing.skip_fresh", county=county, rows=(prev or {}).get("rows"),
                 fetched_at=(prev or {}).get("fetched_at"))
        return int((prev or {}).get("rows") or 0)

    probe = {"url": spec.get("url") or spec.get("layer_url")}
    if spec.get("kind") == "csv" and spec.get("url"):
        probe = _probe(spec["url"])
        if not force and _unchanged(prev, probe) and has_data(state, county):
            log.info("sc_parcel_mailing.skip_unchanged", county=county,
                     etag=probe.get("etag"), rows=(prev or {}).get("rows"))
            # refresh fetched_at so the TTL clock restarts off the validator hit
            con = _connect()
            try:
                con.execute("UPDATE sc_bulk_meta SET fetched_at=? WHERE state=? AND county=?",
                            (datetime.utcnow().isoformat(), state, county))
                con.commit()
            finally:
                con.close()
            return int((prev or {}).get("rows") or 0)

    best: dict[str, dict] = {}
    if spec.get("kind") == "csv":
        try:
            best = _build_from_csv(state, county, spec, max_rows=max_rows)
        except Exception as e:  # noqa: BLE001 — fall back to the live county layer
            log.warning("sc_parcel_mailing.csv_failed", county=county, err=str(e)[:160])
    if not best and spec.get("layer_url"):
        best = _build_from_arcgis(state, county, spec, max_rows=max_rows)
    if not best:
        return 0
    return _store(state, county, _strip_scratch(best), probe)


# --------------------------------------------------------------------------- lookup

def _key_variants(parcel_id: str) -> list[str]:
    d = norm_key(parcel_id)
    if not d:
        return []
    out: list[str] = []
    for v in (d, d.lstrip("0") or d, d.zfill(9), d.zfill(10), d.zfill(11), d.zfill(12)):
        if v and v not in out:
            out.append(v)
    return out


def _truthy_flag(v) -> bool:
    """A stored flag, whatever affinity it came back with. NEVER bool(v): a
    TEXT-affinity "0" is truthy, which is exactly how the all-parcels-distressed
    bug happened."""
    if v in (None, "", 0, 0.0):
        return False
    return str(v).strip().lower() not in ("0", "0.0", "false", "no", "n")


def _row_to_dict(row) -> dict:
    d = dict(zip(_OUT, row))
    d["mailing"] = ", ".join(p for p in (
        d.get("mail_addr"),
        " ".join(x for x in (d.get("mail_city"), d.get("mail_state")) if x),
        d.get("mail_zip")) if p)
    d["condition_distressed"] = _truthy_flag(d.get("condition_distressed"))
    if d.get("year_built") is not None:
        try:
            d["year_built"] = int(float(d["year_built"]))
        except (ValueError, TypeError):
            d["year_built"] = None
    return d


def _disambiguate(rows: list, *, street_address: Optional[str], zip_code: Optional[str]):
    """Pick ONE row from a multi-hit candidate set, or None.

    A wrong mailing address is worse than no mailing address, so a tie is only
    broken by real evidence: a matching situs address, then a matching situs zip,
    then unanimity on the mailing address itself (the same owner mailing across
    every unit of a condo parcel is safe to return)."""
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    an = norm_addr(street_address) if street_address else ""
    if an:
        hit = [r for r in rows if (dict(zip(_OUT, r)).get("situs_street") or "") and
               norm_addr(dict(zip(_OUT, r))["situs_street"]) == an]
        if len(hit) == 1:
            return hit[0]
        if hit:
            rows = hit
    if zip_code:
        z = re.sub(r"\D", "", str(zip_code))[:5]
        hit = [r for r in rows if z and
               re.sub(r"\D", "", str(dict(zip(_OUT, r)).get("situs_zip") or ""))[:5] == z]
        if len(hit) == 1:
            return hit[0]
        if hit:
            rows = hit
    mails = {(dict(zip(_OUT, r)).get("mail_addr") or "").upper() for r in rows}
    return rows[0] if len(mails) == 1 else None


def lookup(state: str, county: str, *, parcel_id: Optional[str] = None,
           street_address: Optional[str] = None, zip_code: Optional[str] = None) -> Optional[dict]:
    """Owner + mailing + situs for one lead, keyed on parcel id then situs address.

    Order: unique parcel_key -> (non-unique) alt_key -> situs address. Ambiguous
    hits are resolved by _disambiguate or dropped."""
    if not DB_PATH.exists():
        return None
    con = _connect()
    try:
        cols = ", ".join(_OUT)
        variants = _key_variants(parcel_id or "")
        for v in variants:
            row = con.execute(
                f"SELECT {cols} FROM sc_parcel_mailing WHERE state=? AND county=? AND parcel_key=?",
                (state, county, v)).fetchone()
            if row:
                return _row_to_dict(row)
        for v in variants:
            rows = con.execute(
                f"SELECT {cols} FROM sc_parcel_mailing "
                f"WHERE state=? AND county=? AND alt_key=? LIMIT 40",
                (state, county, v)).fetchall()
            pick = _disambiguate(rows, street_address=street_address, zip_code=zip_code)
            if pick is not None:
                return _row_to_dict(pick)
        an = norm_addr(street_address) if street_address else ""
        if an:
            rows = con.execute(
                f"SELECT {cols} FROM sc_parcel_mailing "
                f"WHERE state=? AND county=? AND situs_norm=? LIMIT 40",
                (state, county, an)).fetchall()
            pick = _disambiguate(rows, street_address=None, zip_code=zip_code)
            if pick is not None:
                return _row_to_dict(pick)
        return None
    finally:
        con.close()


def resolve_parcel_key(state: str, county: str, *, street_address: Optional[str] = None,
                       zip_code: Optional[str] = None) -> Optional[str]:
    """Situs address -> county parcel key, offline. The resolver's free fallback
    for SC leads with no parcel id and no usable lat/lng.

    Returns the RAW county-published key (Spartanburg's dashed MAPNUMBER, Anderson's
    unpadded TMS) because that is the format the assessor-card adapters query with."""
    rec = lookup(state, county, street_address=street_address, zip_code=zip_code)
    return (rec or {}).get("parcel_raw") or (rec or {}).get("parcel_key") or None


def lookup_by_owner(state: str, county: str, name: str, *, limit: int = 5) -> list[dict]:
    """Owner NAME -> parcels, using the project's strict matcher.

    NET-NEW for Anderson: enrichment_resolve_name_to_property lists Anderson in
    SC_NO_FREE_OWNER_SEARCH because propertyviewer MapServer/5 carries no owner
    column. The County_Parcels roll ingested here DOES carry OWNER on 113,699
    parcels, so Anderson now has a free owner search — offline, zero requests.

    Candidates are pulled by SURNAME prefix off the owner_norm index (the rolls
    are surname-first), then filtered by name_normalize.match_owner, which only
    returns 'exact' or 'strong'. Everything weaker is dropped: a wrong owner here
    would put the wrong person's address in front of outreach.
    """
    if not DB_PATH.exists():
        return []
    from .name_normalize import (  # local import: keeps this module import-light
        distinctive_tokens, is_entity, match_owner, person_orderings,
    )

    prefixes: list[str] = []
    if is_entity(name):
        toks = distinctive_tokens(name)
        if toks:
            prefixes.append(toks[0])
    else:
        for p in person_orderings(name):
            if p.surname and len(p.surname) >= 3 and p.surname not in prefixes:
                prefixes.append(p.surname)
    if not prefixes:
        return []

    con = _connect()
    out: list[dict] = []
    seen: set[str] = set()
    try:
        cols = ", ".join(_OUT)
        for pref in prefixes:
            # Range scan, NOT `LIKE 'PREF %'`: SQLite's default case-insensitive
            # LIKE cannot use a BINARY index, so the LIKE form full-scans 180k
            # rows per lookup (~0.3 s each). '!' is the byte after ' '.
            lo, hi = f"{pref} ", f"{pref}!"
            rows = con.execute(
                f"SELECT {cols} FROM sc_parcel_mailing "
                f"WHERE state=? AND county=? AND owner_norm >= ? AND owner_norm < ? LIMIT 400",
                (state, county, lo, hi)).fetchall()
            for r in rows:
                rec = _row_to_dict(r)
                verdict = match_owner(name, rec.get("owner"))
                if not verdict or rec["parcel_key"] in seen:
                    continue
                seen.add(rec["parcel_key"])
                rec["owner_match"] = verdict
                out.append(rec)
                if len(out) >= limit:
                    return out
        return out
    finally:
        con.close()
