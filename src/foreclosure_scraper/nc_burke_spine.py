"""Burke County NC — FREE cached WPCOG parcel spine (vacant land, big tracts,
government-owned surplus) joined into one PIN-keyed index.

Burke publishes nothing like Lincoln's flat-file tax roll, but the Western
Piedmont Council of Governments (WPCOG) hosts the county's parcel extracts as
open ArcGIS FeatureServers. Four of them together carry everything the board
needs, and none of them costs more than a couple of dozen paged requests:

  Undeveloped_Burke_Parcels_20Acres/FeatureServer/2  "Vacant_BurkeCo"   21,879
      the vacant/undeveloped roll (TABLE, no geometry) — PIN, REID, township,
      land class, zoning, situs.
  Undeveloped_Burke_Parcels_20Acres/FeatureServer/0  ">20 acres"           580
      the big tracts, WITH full owner + mailing + deed book/page/date.
  parcel_pwa/FeatureServer/0                                            59,120
      the whole Burke roll — owner, mailing, situs, assessed value, acreage,
      deed AND, critically, the PIN -> REID mapping (see below).
  LocalGovtOwnedProperties/FeatureServer/0                               1,963
      city/county/school-board owned parcels across Burke (488), Catawba (938),
      Caldwell (399), Alexander (131). A buy-direct / surplus-disposal channel,
      and a lead-quality flag: a "distressed" lead sitting on a parcel the city
      owns is not a motivated seller.

WHY THE REID MATTERS (the actual unlock). lrcpwa.ncptscloud.com resolves a Burke
parcel to its LIVE 2026 record (owner, mailing, assessed value, land class,
acreage, deed images) — but its `searchValue` is the REID account number, not the
10-digit map PIN. Every Burke lead on the board carries a PIN (measured
2026-08-03: 170/170 parcel-bearing Burke leads are 10-digit PINs), so lrcpwa has
been returning HTTP 500 for Burke and sits at 0.6% coverage against Henderson's
78.3%. parcel_pwa supplies PIN -> REID for 56,831 unambiguous Burke parcels,
which is the bridge that makes that enricher work for this county.

VERIFIED LIVE 2026-08-03. Row counts above are `returnCountOnly` results, not
estimates. Vintages differ and are recorded per-record so nothing here is passed
off as current:
  * Vacant_BurkeCo / >20ac  — AUT_SNAPSH spans 2015-01-02..2017-01-10. The
    vacancy flag is therefore a 2017 SNAPSHOT and is stored as `vacant_land`
    with `vacant_land_as_of`, never as raw['vacant'] (which downstream reads as
    a vacant STRUCTURE distress signal). "VACANT" here is the assessor's land
    class for unimproved land — a bare lot, not an empty house.
  * parcel_pwa            — layer lastEditDate 2018-04-18.
  * LocalGovtOwnedProperties — layer lastEditDate 2020-11-04.
Corroboration against the board (2026-08-03): of the 44 Burke leads the vacant
roll matches, 40 were already typed `land` and only 2 carry a structure, so the
2017 flag still agrees with today's board 95% of the time.

PRIVACY: every field read is enumerated in the _*_FIELDS tuples below; there is
no `outFields=*` anywhere in this module. All four layers were field-listed on
2026-08-03 and NONE carries an SSN, DOB, driver's-licence or personal-contact
column — the closest thing to PII is the owner name + mailing address that the
assessment record exists to publish. _SENSITIVE_RE is the standing guard: any
field whose name ever starts matching it is dropped at parse time and logged.

Join key: the 10-digit map PIN, normalised. PIN is NOT unique on this roll —
755 PINs map to more than one REID (condos / splits), so an ambiguous PIN
resolves to nothing rather than handing a lead its neighbour's owner.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger(__name__)

ORG = "https://services1.arcgis.com/HFXT3ZVvUhhNGNnw/arcgis/rest/services"
VACANT_URL = f"{ORG}/Undeveloped_Burke_Parcels_20Acres/FeatureServer/2"
BIG_URL = f"{ORG}/Undeveloped_Burke_Parcels_20Acres/FeatureServer/0"
ROLL_URL = f"{ORG}/parcel_pwa/FeatureServer/0"
GOVT_URL = f"{ORG}/LocalGovtOwnedProperties/FeatureServer/0"

# The vacancy snapshot the two Undeveloped_* layers were cut from (max AUT_SNAPSH).
VACANT_AS_OF = "2017-01-10"

# Explicit field allow-lists — never outFields=*.
_VACANT_FIELDS = ("PARCEL_PK", "REID", "PIN1", "PIN_EXT", "LOCATION_A",
                  "TOWNSHIP", "LAND_CLASS", "ZONING")
_BIG_FIELDS = ("PARCEL_PK", "REID", "PIN", "ACREAGE", "PROPERTY_O",
               "OWNER_MAIL", "OWNER_MA_1", "OWNER_MA_2", "OWNER_MA_3",
               "OWNER_MA_4", "OWNER_MA_5", "LOCATION_A", "TOTAL_PROP",
               "DEED_BOOK", "DEED_PAGE", "DEED_DATE", "TOWNSHIP",
               "LAND_CLASS", "ZONING")
_ROLL_FIELDS = ("REID", "PIN", "PIN_EXT", "ACREAGE", "PROPERTY_O",
                "OWNER_MAIL", "OWNER_MA_1", "OWNER_MA_2", "OWNER_MA_3",
                "OWNER_MA_4", "OWNER_MA_5", "LOCATION_A", "PHYADDR_CI",
                "PHYADDR_ZI", "TOTAL_PROP", "DEED_BOOK", "DEED_PAGE",
                "DEED_DATE")
_GOVT_FIELDS = ("ALTPARNO", "CNTYNAME", "GISACRES", "OWNNAME", "OWNNAME2",
                "PARNO", "PARUSEDESC", "SITEADD", "GOVERNMENT", "LANDUSE",
                "FACNAME")

# Standing privacy guard. None of these layers carries such a column today; if
# one ever appears, drop it at parse time rather than letting it reach the board.
_SENSITIVE_RE = re.compile(r"ssn|social|driver?s?_?lic|dl_?num|dob|birth",
                           re.IGNORECASE)

# name -> (url, fields, orderByFields, page size, where)
_DATASETS: dict[str, tuple[str, tuple[str, ...], str, int, str]] = {
    "vacant": (VACANT_URL, _VACANT_FIELDS, "OID", 1000, "1=1"),
    "big": (BIG_URL, _BIG_FIELDS, "OBJECTID", 1000, "1=1"),
    "roll": (ROLL_URL, _ROLL_FIELDS, "FID", 2000, "1=1"),
    "govt": (GOVT_URL, _GOVT_FIELDS, "OBJECTID", 1000, "1=1"),
}

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "burke_spine"
_INDEX_PATH = _CACHE_DIR / "burke_index.json.gz"
_META_PATH = _CACHE_DIR / "burke_meta.json"

_DEF_TTL_DAYS = 14.0
_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36")}

_MAX_PLAUSIBLE_VALUE = 500_000_000.0


# ------------------------------------------------------------- pure helpers --

def norm_pin(s: Any) -> str:
    """Index key: strip non-alphanumerics, uppercase. Board Burke parcel_ids
    arrive both bare ('2703905385') and dashed ('2647-50-6616')."""
    return re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()


def _txt(v: Any) -> str:
    s = str(v or "").strip()
    return "" if s in ("<Null>", "NULL", "None", "-") else s


def _num(v: Any) -> Optional[float]:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f else None


def _money(v: Any) -> Optional[float]:
    f = _num(v)
    return f if f is not None and 0 < f <= _MAX_PLAUSIBLE_VALUE else None


def _epoch_ms_to_iso(v: Any) -> str:
    """ArcGIS dates are epoch-milliseconds.

    0 is this stack's null-date sentinel, and it is exactly the value that turns
    an unrecorded deed into a confident-looking "1970-01-01" on the board — so
    it is rejected outright, not merely range-checked. Anything outside
    1900..2100 goes the same way.
    """
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return ""
    if not ms:
        return ""
    secs = ms / 1000.0
    if not (-2208988800 < secs < 4102444800):
        return ""
    return time.strftime("%Y-%m-%d", time.gmtime(secs))


def squash(v: Any) -> str:
    """WPCOG pads unused text columns with single spaces, so ' ' means empty and
    '  MORGANTON   NC' means 'MORGANTON NC'."""
    return re.sub(r"\s+", " ", str(v or "")).strip()


def build_mailing(rec: dict) -> str:
    """One-line owner mailing address from the OWNER_MA_* ladder.

    Layout is street / unit / unit2 / city / state / zip; the middle two are
    almost always the space-filler, so squash-and-drop-empties is the whole
    rule. City+state+zip get comma-separated from the street the way the rest
    of the board formats a mailing address.
    """
    street = " ".join(p for p in (squash(rec.get("OWNER_MAIL")),
                                  squash(rec.get("OWNER_MA_1")),
                                  squash(rec.get("OWNER_MA_2"))) if p)
    tail = " ".join(p for p in (squash(rec.get("OWNER_MA_3")),
                                squash(rec.get("OWNER_MA_4")),
                                squash(rec.get("OWNER_MA_5"))) if p)
    return ", ".join(p for p in (street, tail) if p)


def clean_owner(v: Any) -> str:
    """PROPERTY_O arrives with a leading space and ';' between co-owners."""
    return "; ".join(p.strip() for p in squash(v).split(";") if p.strip())


def is_absentee(rec: dict) -> Optional[bool]:
    """Owner mails from outside NC. Blank state = unknown, NOT absentee."""
    st = squash(rec.get("OWNER_MA_4")).upper()
    if not st or len(st) != 2:
        return None
    return st != "NC"


def clean_situs(v: Any) -> str:
    """LOCATION_A / SITEADD use '0' as the house number for an unaddressed
    parcel ('0   WATTS DR'). A street with no number is not an address — return
    '' rather than seeding the board with a fake one."""
    s = squash(v)
    if not s or re.match(r"^0(\s|$)", s):
        return ""
    return s


def _county_of(li: Listing) -> str:
    return re.sub(r"\s+county\s*$", "", (li.county or "").strip(),
                  flags=re.I).strip().title()


# ------------------------------------------------------------------ fetching --

def _get_json(url: str, params: dict, timeout: float = 120.0) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _drop_sensitive(fields: tuple[str, ...]) -> tuple[str, ...]:
    keep = tuple(f for f in fields if not _SENSITIVE_RE.search(f))
    if len(keep) != len(fields):
        log.warning("burke_spine.sensitive_field_dropped",
                    dropped=[f for f in fields if _SENSITIVE_RE.search(f)])
    return keep


def fetch_layer(url: str, fields: tuple[str, ...], order: str,
                size: int = 1000, where: str = "1=1") -> list[dict]:
    """Page a FeatureServer with resultOffset/resultRecordCount.

    orderByFields is mandatory, not decorative: without a stable sort the server
    is free to return overlapping pages and the offsets silently duplicate and
    drop rows. Layer 2 is a table whose objectIdField is OID, layer 0s use
    OBJECTID, parcel_pwa uses FID — hence the per-dataset order key.
    """
    fields = _drop_sensitive(fields)
    out: list[dict] = []
    offset = 0
    while True:
        d = _get_json(f"{url}/query", {
            "where": where,
            "outFields": ",".join(fields),
            "returnGeometry": "false",
            "orderByFields": order,
            "resultOffset": offset,
            "resultRecordCount": size,
            "f": "json",
        })
        if d.get("error"):
            raise RuntimeError(f"arcgis error {d['error']}")
        feats = d.get("features") or []
        for f in feats:
            attrs = f.get("attributes") or {}
            out.append({k: v for k, v in attrs.items()
                        if not _SENSITIVE_RE.search(str(k))})
        if len(feats) < size:
            return out
        offset += size


def layer_signature(url: str) -> dict:
    """Cheap change-token: row count + the layer's own lastEditDate.

    Two requests per layer instead of re-downloading 80k rows. Some WPCOG layers
    report lastEditDate=None, so the count carries the signature on its own
    there — a re-publish that changes no rows at all is the one case this
    misses, and the TTL covers it.
    """
    sig: dict[str, Any] = {}
    try:
        c = _get_json(f"{url}/query", {"where": "1=1", "returnCountOnly": "true",
                                       "f": "json"}, timeout=60)
        sig["count"] = c.get("count")
    except Exception as exc:  # noqa: BLE001
        log.warning("burke_spine.count_failed", url=url, error=str(exc)[:120])
        return {}
    try:
        meta = _get_json(url, {"f": "json"}, timeout=60)
        sig["last_edit"] = (meta.get("editingInfo") or {}).get("lastEditDate")
    except Exception:  # noqa: BLE001
        sig["last_edit"] = None
    return sig


# ------------------------------------------------------------------- indexing --

def _unique_by_pin(rows: Iterable[dict], pin_field: str,
                   discriminator: Optional[str] = None) -> dict[str, dict]:
    """PIN -> row, but ONLY where the PIN is unambiguous.

    Measured 2026-08-03: parcel_pwa holds 59,120 rows over 57,586 distinct PINs,
    and 755 of those PINs carry more than one REID — condo stacks and post-split
    parcels. Last-write-wins would hand ~1.3% of Burke leads a different
    property's owner, mailing address and value, so an ambiguous PIN resolves to
    nothing instead. Repeated rows that agree on the discriminator (the same
    parcel drawn as several polygons) are not ambiguous and are kept.
    """
    first: dict[str, dict] = {}
    seen: dict[str, set] = {}
    for row in rows:
        pin = norm_pin(row.get(pin_field))
        if not pin:
            continue
        tag = _txt(row.get(discriminator)) if discriminator else ""
        seen.setdefault(pin, set()).add(tag)
        first.setdefault(pin, row)
    return {p: r for p, r in first.items() if len(seen[p]) <= 1}


def _build_index(vacant: list[dict], big: list[dict], roll: list[dict],
                 govt: list[dict]) -> dict[str, dict]:
    """Merge the four extracts into one record per PIN."""
    vac_by = _unique_by_pin(vacant, "PIN1", "REID")
    big_by = _unique_by_pin(big, "PIN", "REID")
    roll_by = _unique_by_pin(roll, "PIN", "REID")
    govt_by = _unique_by_pin(govt, "PARNO", "ALTPARNO")

    index: dict[str, dict] = {}

    def rec(pin: str) -> dict:
        return index.setdefault(pin, {"pin": pin})

    # 1. whole-county roll — owner / mailing / value / acreage / deed / REID
    for pin, row in roll_by.items():
        r = rec(pin)
        r["reid"] = _txt(row.get("REID")) or None
        r["owner"] = clean_owner(row.get("PROPERTY_O")) or None
        r["mailing"] = build_mailing(row) or None
        r["mail_state"] = squash(row.get("OWNER_MA_4")).upper() or None
        r["absentee"] = is_absentee(row)
        r["situs"] = clean_situs(row.get("LOCATION_A")) or None
        r["city"] = squash(row.get("PHYADDR_CI")).title() or None
        r["zip"] = re.sub(r"\D", "", str(row.get("PHYADDR_ZI") or ""))[:5] or None
        r["acreage"] = _num(row.get("ACREAGE"))
        r["tax_value"] = _money(row.get("TOTAL_PROP"))
        r["deed_book"] = _txt(row.get("DEED_BOOK")) or None
        r["deed_page"] = _txt(row.get("DEED_PAGE")) or None
        r["deed_date"] = _epoch_ms_to_iso(row.get("DEED_DATE")) or None

    # 2. >20-acre tracts — same shape, plus township/land class/zoning
    for pin, row in big_by.items():
        r = rec(pin)
        r.setdefault("reid", _txt(row.get("REID")) or None)
        for key, val in (("owner", clean_owner(row.get("PROPERTY_O"))),
                         ("mailing", build_mailing(row)),
                         ("situs", clean_situs(row.get("LOCATION_A")))):
            if val and not r.get(key):
                r[key] = val
        if r.get("absentee") is None:
            r["absentee"] = is_absentee(row)
        for key, val in (("acreage", _num(row.get("ACREAGE"))),
                         ("tax_value", _money(row.get("TOTAL_PROP")))):
            if val and not r.get(key):
                r[key] = val
        for key, val in (("deed_book", _txt(row.get("DEED_BOOK"))),
                         ("deed_page", _txt(row.get("DEED_PAGE"))),
                         ("deed_date", _epoch_ms_to_iso(row.get("DEED_DATE"))),
                         ("township", squash(row.get("TOWNSHIP")).title()),
                         ("land_class", squash(row.get("LAND_CLASS")).title()),
                         ("zoning", squash(row.get("ZONING")).title())):
            if val and not r.get(key):
                r[key] = val
        r["over_20_acres"] = True

    # 3. vacant/undeveloped roll — the dated land-class flag
    for pin, row in vac_by.items():
        r = rec(pin)
        r.setdefault("reid", _txt(row.get("REID")) or None)
        lc = squash(row.get("LAND_CLASS")).title()
        # A blank land class (47 of 21,879 rows) is not evidence of vacancy.
        if lc:
            r["land_class"] = lc
            r["vacant_land"] = lc.upper() == "VACANT"
            r["vacant_land_as_of"] = VACANT_AS_OF
        for key, val in (("township", squash(row.get("TOWNSHIP")).title()),
                         ("zoning", squash(row.get("ZONING")).title()),
                         ("situs", clean_situs(row.get("LOCATION_A")))):
            if val and not r.get(key):
                r[key] = val

    # 4. government-owned — buy-direct channel + lead-quality flag
    for pin, row in govt_by.items():
        r = rec(pin)
        r["govt_owned"] = {
            "county": squash(row.get("CNTYNAME")) or None,
            "owner": squash(row.get("OWNNAME")) or None,
            "government": squash(row.get("GOVERNMENT")) or None,
            "use": squash(row.get("PARUSEDESC")) or None,
            "facility": squash(row.get("FACNAME")) or None,
            "acres": _num(row.get("GISACRES")),
            "reid": _txt(row.get("ALTPARNO")) or None,
            "situs": clean_situs(row.get("SITEADD")) or None,
        }
        r.setdefault("reid", _txt(row.get("ALTPARNO")) or None)

    return {p: r for p, r in index.items() if len(r) > 1}


# ------------------------------------------------------------------- caching --

def cache_meta() -> dict:
    try:
        return json.loads(_META_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _fresh(meta: dict, ttl_days: float) -> bool:
    ts = meta.get("built_at") or 0
    return bool(ts) and (time.time() - ts) < ttl_days * 86400


def _write_index(index: dict[str, dict]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(_INDEX_PATH, "wb", compresslevel=6) as fh:
        fh.write(json.dumps(index).encode())


def _read_index() -> dict[str, dict]:
    with gzip.open(_INDEX_PATH, "rb") as fh:
        return json.loads(fh.read().decode())


def _write_meta(meta: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _META_PATH.write_text(json.dumps(meta))


def refresh(force: bool = False, ttl_days: float = _DEF_TTL_DAYS) -> dict:
    """Rebuild the cached index when stale. Returns the meta dict.

    Skips the ~80k-row pull entirely when the cache is fresh, and — even once
    the TTL expires — when every layer's (count, lastEditDate) signature is
    unchanged from the last build. These are annual-ish county extracts, so an
    unchanged signature means there is nothing to re-parse.
    """
    meta = cache_meta()
    if not force and _fresh(meta, ttl_days) and _INDEX_PATH.exists():
        return meta

    remote = {name: layer_signature(spec[0]) for name, spec in _DATASETS.items()}
    if (not force and _INDEX_PATH.exists() and meta.get("remote")
            and meta["remote"] == remote and all(remote.values())):
        meta["built_at"] = time.time()      # nothing changed upstream
        _write_meta(meta)
        return meta

    payloads: dict[str, list[dict]] = {}
    for name, (url, fields, order, size, where) in _DATASETS.items():
        payloads[name] = fetch_layer(url, fields, order, size, where)
        log.info("burke_spine.fetched", layer=name, rows=len(payloads[name]))

    index = _build_index(payloads.get("vacant", []), payloads.get("big", []),
                         payloads.get("roll", []), payloads.get("govt", []))
    _write_index(index)
    meta = {
        "built_at": time.time(),
        "remote": remote,
        "rows": {k: len(v) for k, v in payloads.items()},
        "keys": len(index),
        "vacant_as_of": VACANT_AS_OF,
        "source": ORG,
    }
    _write_meta(meta)
    log.info("burke_spine.built", keys=meta["keys"], rows=meta["rows"])
    return meta


_INDEX: Optional[dict[str, dict]] = None


def _index() -> dict[str, dict]:
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = _read_index()
        except (OSError, ValueError):
            _INDEX = {}
    return _INDEX


def has_data() -> bool:
    return bool(_index())


def lookup(parcel_id: Optional[str]) -> Optional[dict]:
    """Exact-key lookup on the 10-digit map PIN."""
    pin = norm_pin(parcel_id)
    if not pin:
        return None
    idx = _index()
    if pin in idx:
        return idx[pin]
    # some exports zero-pad the PIN out past 10 with the PIN_EXT
    if len(pin) > 10 and set(pin[10:]) <= {"0"} and pin[:10] in idx:
        return idx[pin[:10]]
    return None


def reid_for(parcel_id: Optional[str]) -> Optional[str]:
    """PIN -> Burke REID, the account key lrcpwa.ncptscloud.com searches on."""
    rec = lookup(parcel_id) or {}
    return rec.get("reid")


def govt_records(county: Optional[str] = None) -> list[dict]:
    """Government-owned parcels as flat dicts — the buy-direct / surplus lane.

    Board writes are the orchestrator's job; this only hands back the rows.
    """
    want = (county or "").strip().title() or None
    out = []
    for pin, rec in _index().items():
        g = rec.get("govt_owned")
        if not g:
            continue
        if want and (g.get("county") or "") != want:
            continue
        out.append({"pin": pin, **g})
    return out


# -------------------------------------------------------------------- enrich --

def is_eligible(li: Listing) -> bool:
    return ((li.state or "").upper() == "NC"
            and _county_of(li) == "Burke"
            and bool((li.parcel_id or "").strip()))


def enrich(listings: Iterable[Listing], auto_refresh: bool = True) -> dict:
    """Backfill Burke leads from the cached spine.

    Never overwrites a value the board already has. Owner/mailing go into
    raw['gis'] to match enrichment_arcgis + nc_lincoln_bulk; the REID, the dated
    vacancy flag and the government-owner block go into raw['burke_spine'].
    """
    stats = {"eligible": 0, "matched": 0, "fields_filled": 0, "reid": 0,
             "vacant_land": 0, "govt_owned": 0, "absentee": 0}
    if os.environ.get("FORECLOSURE_BURKE_SPINE") == "0":
        return stats
    leads = [li for li in listings if is_eligible(li)]
    stats["eligible"] = len(leads)
    if not leads:
        return stats
    if auto_refresh and not has_data():
        try:
            refresh()
            global _INDEX
            _INDEX = None
        except Exception as exc:  # noqa: BLE001 — offline: leave the board alone
            log.warning("burke_spine.refresh_failed", error=str(exc)[:160])
            return stats

    for li in leads:
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
        _maybe("city", rec.get("city"))
        _maybe("zip_code", rec.get("zip"))
        _maybe("acreage", rec.get("acreage"))
        _maybe("zoning", rec.get("zoning"))
        _maybe("tax_value", rec.get("tax_value"))
        _maybe("owner_name", rec.get("owner"))

        if not isinstance(li.raw, dict):
            li.raw = {}
        gis = li.raw.setdefault("gis", {})
        for key in ("owner", "mailing"):
            if rec.get(key) and not gis.get(key):
                gis[key] = rec[key]
                filled += 1
        if rec.get("absentee") is not None and "absentee" not in gis:
            gis["absentee"] = rec["absentee"]
            filled += 1
            if rec["absentee"]:
                stats["absentee"] += 1

        # Deliberately NOT raw['vacant'] / gis['vacant']: this is the assessor's
        # land class for UNIMPROVED LAND off a 2017 snapshot, and downstream
        # lead-signal code reads a bare "vacant" as an empty STRUCTURE.
        block = {"pin": rec.get("pin"), "source": ORG}
        for key in ("reid", "township", "land_class", "vacant_land",
                    "vacant_land_as_of", "over_20_acres", "deed_book",
                    "deed_page", "deed_date"):
            if rec.get(key) is not None:
                block[key] = rec[key]
        if rec.get("govt_owned"):
            block["govt_owned"] = rec["govt_owned"]
            stats["govt_owned"] += 1
        prev = li.raw.get("burke_spine")
        if not isinstance(prev, dict) or prev != block:
            li.raw["burke_spine"] = block
            filled += 1
        if block.get("reid"):
            stats["reid"] += 1
        if block.get("vacant_land"):
            stats["vacant_land"] += 1
        stats["fields_filled"] += filled

    log.info("burke_spine.done", **stats)
    return stats
