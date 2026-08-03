"""Lincoln County NC — FREE bulk assessor dumps, cached locally.

Lincoln publishes its whole tax roll as flat files. Reading the cached extract
is an exact-key join, offline, and ~1000x cheaper than a per-lead ArcGIS LIKE —
and it carries columns the live parcel layer does not expose at all (bed/bath,
finished area, full sales history, the assessor photo filename).

INDEX (the human page — the /ftp/ directory itself is 403, browsing is disabled,
but every file under it is public and fetches 200; that is a missing index, not
a wall, and nothing here defeats any protection):
    https://www.lincolncountync.gov/470/GIS-Download-Page
    base: https://arcgisserver.lincolncountync.gov/ftp/<name>.zip

VERIFIED LIVE 2026-08-03 (HEAD, real Content-Length / Last-Modified). Ten of the
twelve published files carry Last-Modified "Sat, 01 Aug 2026 09:02-09:03 GMT";
contour.zip (2020) and StreamsAndWaterBodies.zip (2021) are static terrain/hydro
layers that do not change. The six ASSESSOR dumps total 67,223,854 bytes:

    parcels.zip       26,976,368   shapefile, 56,976 rows (geometry + same attrs)
    zoning.zip        17,567,937   zoning polygons
    sales.zip          8,566,103   sales.csv        272,176 rows
    parceldata.zip     5,217,705   parceldata.csv    56,977 rows
    address.zip        5,010,768   address points
    improvements.zip   3,884,973   improvements.csv 107,291 rows

Only the three CSVs are parsed here — they hold everything the board needs and
cost 17.7 MB compressed instead of 67 MB.

MEASURED CONTENT (all 56,977 parceldata rows, 2026-08-03):
    PIN / AKPAR_ 100%   NAME1 99.6%   ADDRESS1+CITY+STATE+ZIP 99.6%
    PHYSICALADDR 99.7%  TOTALVALUE 99.4%   ZONING 94.8%   ACRE 100%
    VACANT 100% (YES=14,885 / NO=42,092)   out-of-state owners 2,359

PRIVACY: the columns read are enumerated in the _*_COLS tuples below and nothing
else is retained. Lincoln has historically exposed TCSSN1/TCSSN2 on a public
layer; all three CSVs, the Parcels.dbf shapefile attribute table, and every layer
of Server_TaxParcelViewerSP / Server_Tables / MainSalesImprovmentLand /
RevalLayers / LandReport were scanned on 2026-08-03 and NONE carries an SSN, DOB
or licence column today. The explicit column allow-list is the standing guard
against one appearing later.

Join keys: `AKPAR_` (the internal 5-6 char account key, e.g. "50901"/"M04201")
and `PIN` (the 10-digit map PIN). Board Lincoln leads carry BOTH shapes, so the
index is keyed on both.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger(__name__)

INDEX_PAGE = "https://www.lincolncountync.gov/470/GIS-Download-Page"
FTP_BASE = "https://arcgisserver.lincolncountync.gov/ftp"

# name -> (zip member csv, join-key column)
BULK_FILES = {
    "parceldata": "parceldata.csv",
    "improvements": "improvements.csv",
    "sales": "sales.csv",
}

# Explicit column allow-lists. Never read a whole row into the board.
_PARCEL_COLS = ("AKPAR_", "PIN", "NAME1", "NAME2", "ADDRESS1", "ADDRESS2",
                "CITY", "STATE", "ZIP", "PHYSICALADDR", "IMPROVALUE",
                "LANDVALUE", "TOTALVALUE", "DEEDBK", "DEEDPG", "DEEDYR",
                "VACANT", "ZONING", "ACRE", "TAXYEAR")
_IMPROV_COLS = ("AHPAR_", "AHACYR", "AHBED_", "AHBTH_", "AHHBTH", "AHFNAR",
                "PRIMARYIMA")
_SALES_COLS = ("AKPAR_", "PIN", "AMDTSL", "AMSLAM", "AMDBOK", "AMDPGE", "AMYEAR")

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "lincoln_bulk"
_INDEX_PATH = _CACHE_DIR / "lincoln_index.json.gz"
_META_PATH = _CACHE_DIR / "lincoln_meta.json"

_DEF_TTL_DAYS = 7.0
_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36")}

_MAX_PLAUSIBLE_SALE = 50_000_000.0


# ------------------------------------------------------------- pure helpers --

def norm_key(s: Any) -> str:
    """Index key: strip non-alphanumerics, uppercase. Handles both the
    alphanumeric AKPAR_ ('M04201') and the dashed PIN ('2694-21-3729')."""
    return re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()


def _num(v: Any) -> Optional[float]:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f else None


def _txt(v: Any) -> str:
    s = str(v or "").strip()
    return "" if s in ("<Null>", "NULL", "None") else s


def _zip5(v: Any) -> str:
    """Lincoln zero-pads ZIP to 9 ('280920000'); keep ZIP5 unless ZIP+4 is real."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) >= 9 and d[5:] != "0000":
        return f"{d[:5]}-{d[5:9]}"
    return d[:5]


def build_mailing(rec: dict) -> str:
    """One-line mailing address from the parceldata columns."""
    street = " ".join(p for p in (rec.get("ADDRESS1"), rec.get("ADDRESS2")) if p)
    tail = " ".join(p for p in (rec.get("CITY"), rec.get("STATE"),
                                _zip5(rec.get("ZIP"))) if p)
    return ", ".join(p for p in (street.strip(), tail.strip()) if p)


def is_absentee(rec: dict) -> Optional[bool]:
    """Owner mails from outside NC. Blank state = unknown, NOT absentee."""
    st = _txt(rec.get("STATE")).upper()
    if not st:
        return None
    return st != "NC"


def parse_sale_date(v: Any) -> str:
    """Lincoln stores sale dates as YYYYMMDD-ish ints ('19000600' = June 1900,
    day unknown). Return ISO where the parts are real, else ''."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) < 6:
        return ""
    y, m, day = d[:4], d[4:6], d[6:8] or "01"
    if not ("1700" < y <= "2100") or not ("01" <= m <= "12"):
        return ""
    if not ("01" <= day <= "31"):
        day = "01"
    return f"{y}-{m}-{day}"


# ------------------------------------------------------------------ fetching --

def _http_get(url: str, timeout: float = 300.0) -> tuple[bytes, dict]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), {k.lower(): v for k, v in r.headers.items()}


def _head(url: str, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(url, headers=_UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            h = {k.lower(): v for k, v in r.headers.items()}
            return {"last_modified": h.get("last-modified", ""),
                    "length": h.get("content-length", "")}
    except Exception:  # noqa: BLE001
        return {}


def _read_csv(raw: bytes, member: str, cols: tuple[str, ...]) -> list[dict]:
    """Unzip in memory and keep ONLY the allow-listed columns."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = member
        if name not in zf.namelist():
            cand = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not cand:
                return []
            name = cand[0]
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace",
                                    newline="")
            rd = csv.DictReader(text)
            keep = [c for c in cols if c in (rd.fieldnames or [])]
            return [{c: _txt(row.get(c)) for c in keep} for row in rd]


# ------------------------------------------------------------------- indexing --

def _build_index(parcels: list[dict], improvements: list[dict],
                 sales: list[dict]) -> dict[str, dict]:
    """Join the three extracts into one record per parcel, keyed by BOTH
    AKPAR_ and PIN so either shape of board parcel_id resolves."""
    # best improvement per account: the one with the largest finished area
    imp_by_key: dict[str, dict] = {}
    for row in improvements:
        k = norm_key(row.get("AHPAR_"))
        if not k:
            continue
        area = _num(row.get("AHFNAR")) or 0.0
        prev = imp_by_key.get(k)
        if prev is None or area > (prev.get("_area") or 0.0):
            imp_by_key[k] = {
                "_area": area,
                "year_built": int(y) if (y := re.sub(r"\D", "", row.get("AHACYR") or ""))[:4].isdigit()
                and 1700 < int(y[:4]) < 2100 else None,
                "living_sqft": area or None,
                "bedrooms": _num(row.get("AHBED_")),
                "bathrooms": _num(row.get("AHBTH_")),
                "half_baths": _num(row.get("AHHBTH")),
                "photo_file": row.get("PRIMARYIMA") or None,
            }

    # latest qualified sale per account
    sale_by_key: dict[str, dict] = {}
    for row in sales:
        k = norm_key(row.get("AKPAR_")) or norm_key(row.get("PIN"))
        if not k:
            continue
        iso = parse_sale_date(row.get("AMDTSL"))
        amt = _num(row.get("AMSLAM"))
        if amt is not None and not (0 < amt <= _MAX_PLAUSIBLE_SALE):
            amt = None
        cand = {"date": iso, "amount": amt,
                "book": row.get("AMDBOK") or None,
                "page": row.get("AMDPGE") or None}
        prev = sale_by_key.get(k)
        if prev is None or (iso and iso > (prev.get("date") or "")):
            sale_by_key[k] = cand

    # PIN is NOT a unique key on this roll. Measured over all 56,977 rows
    # (2026-08-03): AKPAR_ is unique (56,977 distinct, 0 duplicates) but PIN has
    # 54,004 distinct values with 2,003 PINs shared by 4,976 rows (8.7%) — one
    # PIN covers 92 separate accounts (a condo building). Indexing every PIN
    # last-write-wins silently hands 8.7% of parcels a NEIGHBOUR'S owner,
    # mailing address and value. So: AKPAR_ always, PIN only when it maps to
    # exactly one account. An ambiguous PIN resolves to nothing, because a wrong
    # owner/mailing is worse for an operator than an empty one.
    pin_counts: dict[str, int] = {}
    for row in parcels:
        p = norm_key(row.get("PIN"))
        if p:
            pin_counts[p] = pin_counts.get(p, 0) + 1

    index: dict[str, dict] = {}
    for row in parcels:
        ak = norm_key(row.get("AKPAR_"))
        pin = norm_key(row.get("PIN"))
        rec = {
            "parcel_id": row.get("PIN") or row.get("AKPAR_") or "",
            "akpar": row.get("AKPAR_") or "",
            "owner": " ".join(p for p in (row.get("NAME1"), row.get("NAME2")) if p),
            "mailing": build_mailing(row),
            "mail_state": _txt(row.get("STATE")).upper(),
            "absentee": is_absentee(row),
            "situs": row.get("PHYSICALADDR") or "",
            "vacant": (_txt(row.get("VACANT")).upper() == "YES"
                       if _txt(row.get("VACANT")) else None),
            "zoning": row.get("ZONING") or None,
            "acreage": _num(row.get("ACRE")),
            "land_value": _num(row.get("LANDVALUE")),
            "improvement_value": _num(row.get("IMPROVALUE")),
            "tax_value": _num(row.get("TOTALVALUE")),
            "deed_book": row.get("DEEDBK") or None,
            "deed_page": row.get("DEEDPG") or None,
        }
        imp = imp_by_key.get(ak) or {}
        for f in ("year_built", "living_sqft", "bedrooms", "bathrooms"):
            if imp.get(f):
                rec[f] = imp[f]
        sale = sale_by_key.get(ak) or sale_by_key.get(pin)
        if sale and (sale.get("date") or sale.get("amount")):
            rec["last_sale"] = sale
        if ak:
            index[ak] = rec
        if pin and pin_counts.get(pin) == 1 and pin not in index:
            index[pin] = rec
    return index


# ------------------------------------------------------------------- public --

def cache_meta() -> dict:
    try:
        return json.loads(_META_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _fresh(meta: dict, ttl_days: float) -> bool:
    ts = meta.get("built_at") or 0
    return bool(ts) and (time.time() - ts) < ttl_days * 86400


def refresh(force: bool = False, ttl_days: float = _DEF_TTL_DAYS) -> dict:
    """Download + rebuild the cached index when stale. Returns the meta dict.

    Skips the download entirely when the cache is fresh, and — even when the
    TTL has expired — when every file's upstream Last-Modified is unchanged
    from the last build. The county refreshes these on a schedule, so an
    unchanged Last-Modified means there is nothing to re-parse.
    """
    meta = cache_meta()
    if not force and _fresh(meta, ttl_days) and _INDEX_PATH.exists():
        return meta

    remote = {name: _head(f"{FTP_BASE}/{name}.zip") for name in BULK_FILES}
    if (not force and _INDEX_PATH.exists() and meta.get("remote")
            and meta["remote"] == remote and all(remote.values())):
        meta["built_at"] = time.time()      # nothing changed upstream
        _write_meta(meta)
        return meta

    payloads: dict[str, list[dict]] = {}
    cols = {"parceldata": _PARCEL_COLS, "improvements": _IMPROV_COLS,
            "sales": _SALES_COLS}
    for name, member in BULK_FILES.items():
        url = f"{FTP_BASE}/{name}.zip"
        raw, _ = _http_get(url)
        payloads[name] = _read_csv(raw, member, cols[name])
        log.info("lincoln_bulk.fetched", file=name, rows=len(payloads[name]),
                 bytes=len(raw))

    index = _build_index(payloads.get("parceldata", []),
                         payloads.get("improvements", []),
                         payloads.get("sales", []))
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _write_index(index)
    meta = {"built_at": time.time(), "remote": remote,
            "parcels": len(payloads.get("parceldata", [])),
            "keys": len(index), "index_page": INDEX_PAGE}
    _write_meta(meta)
    log.info("lincoln_bulk.built", **{k: v for k, v in meta.items() if k != "remote"})
    return meta


def _write_index(index: dict[str, dict]) -> None:
    """Store as {records: [...], keys: {key: record_ordinal}} and gzip it.

    Two keys (AKPAR_ and PIN) point at the SAME record, so serialising the dict
    directly writes every record twice — 58 MB for 57k parcels. Interning the
    records behind an ordinal and gzipping brings that to a few MB and makes the
    load materially faster.
    """
    records: list[dict] = []
    ordinal: dict[int, int] = {}
    keys: dict[str, int] = {}
    for key, rec in index.items():
        rid = ordinal.get(id(rec))
        if rid is None:
            rid = len(records)
            ordinal[id(rec)] = rid
            records.append(rec)
        keys[key] = rid
    payload = json.dumps({"records": records, "keys": keys}).encode()
    with gzip.open(_INDEX_PATH, "wb", compresslevel=6) as fh:
        fh.write(payload)


def _read_index() -> dict[str, dict]:
    with gzip.open(_INDEX_PATH, "rb") as fh:
        blob = json.loads(fh.read().decode())
    records = blob["records"]
    return {k: records[i] for k, i in blob["keys"].items()}


def _write_meta(meta: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _META_PATH.write_text(json.dumps(meta))


_INDEX: Optional[dict[str, dict]] = None


def _index() -> dict[str, dict]:
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = _read_index()
        except (OSError, ValueError, KeyError):
            _INDEX = {}
    return _INDEX


def has_data() -> bool:
    return bool(_index())


def lookup(parcel_id: Optional[str]) -> Optional[dict]:
    """Exact-key lookup on either the AKPAR_ account key or the 10-digit PIN."""
    k = norm_key(parcel_id)
    if not k:
        return None
    idx = _index()
    if k in idx:
        return idx[k]
    # a 10-digit PIN zero-padded out to 12/15 by some exports
    if len(k) > 10 and set(k[10:]) <= {"0"} and k[:10] in idx:
        return idx[k[:10]]
    return None


def _county_of(li: Listing) -> str:
    return re.sub(r"\s+county\s*$", "", (li.county or "").strip(),
                  flags=re.I).strip().title()


def is_eligible(li: Listing) -> bool:
    return ((li.state or "").upper() == "NC"
            and _county_of(li) == "Lincoln"
            and bool((li.parcel_id or "").strip()))


def enrich(listings: Iterable[Listing], auto_refresh: bool = True) -> dict:
    """Backfill Lincoln leads from the cached bulk roll. Never overwrites a
    value the board already has; writes owner/mailing/flags into raw['gis'] to
    match enrichment_arcgis, and raw['lincoln_bulk'] for provenance."""
    stats = {"eligible": 0, "matched": 0, "fields_filled": 0, "absentee": 0,
             "vacant": 0}
    if os.environ.get("FORECLOSURE_LINCOLN_BULK") == "0":
        return stats
    listings = [li for li in listings if is_eligible(li)]
    stats["eligible"] = len(listings)
    if not listings:
        return stats
    if auto_refresh and not has_data():
        try:
            refresh()
            global _INDEX
            _INDEX = None
        except Exception as exc:  # noqa: BLE001 — offline: leave the board alone
            log.warning("lincoln_bulk.refresh_failed", error=str(exc)[:160])
            return stats

    for li in listings:
        rec = lookup(li.parcel_id)
        if not rec:
            continue
        stats["matched"] += 1
        filled = 0

        def _maybe(field: str, val: Any) -> None:
            nonlocal filled
            if val in (None, "", 0):
                return
            if getattr(li, field, None) in (None, "", 0):
                setattr(li, field, val)
                filled += 1

        _maybe("street_address", rec.get("situs"))
        _maybe("tax_value", rec.get("tax_value"))
        _maybe("year_built", rec.get("year_built"))
        _maybe("living_sqft", rec.get("living_sqft"))
        _maybe("bedrooms", rec.get("bedrooms"))
        _maybe("bathrooms", rec.get("bathrooms"))
        _maybe("acreage", rec.get("acreage"))
        _maybe("zoning", rec.get("zoning"))

        if not isinstance(li.raw, dict):
            li.raw = {}
        gis = li.raw.setdefault("gis", {})
        for key, val in (("owner", rec.get("owner")),
                         ("mailing", rec.get("mailing"))):
            if val and not gis.get(key):
                gis[key] = val
                filled += 1
        for key in ("vacant", "absentee"):
            if rec.get(key) is not None and key not in gis:
                gis[key] = rec[key]
                filled += 1
                if rec[key]:
                    stats[key] += 1
        sale = rec.get("last_sale") or {}
        if sale:
            ls = gis.setdefault("last_sale", {})
            for k in ("book", "page", "date", "amount"):
                if sale.get(k) and not ls.get(k):
                    ls[k] = sale[k]
                    filled += 1

        li.raw["lincoln_bulk"] = {"parcel_id": rec.get("parcel_id"),
                                  "akpar": rec.get("akpar"),
                                  "source": INDEX_PAGE}
        stats["fields_filled"] += filled

    log.info("lincoln_bulk.done", **stats)
    return stats
