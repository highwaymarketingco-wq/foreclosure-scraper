"""Correct bad data the prior published board carries into a full run (docs/HANDOFF.md item 71).

WHY THIS EXISTS. merge_prior_board() folds the prior board into the fresh scrape: a re-scraped row
keeps the fresh fields and backfills the rest from its prior copy, and a prior-only row is kept
as it was, aged. The fixes of 2026-10-06 (420bbc94 fallback-point parcels, 969c6987 owner mailing
shown as the property address) stop NEW bad data, but nothing re-derives a value a carried row
already has. main.run() calls correct_prior_rows() once, right after merge_prior_board and before
any enricher and dedupe2, so the fixed enrichers refill what is withdrawn here and dedupe2 never
merges on a withdrawn parcel or address. Every change keeps the old values under a raw audit key.

1. FALLBACK-POINT PARCELS (item 70). enrichment_parcel_from_geo used to resolve a parcel at the
   geocoder's fallback point of an address-less row, i.e. whichever parcel lies under a county
   seat or town centre (Lincoln 3633940779 on 1,618 board rows, Anderson 1233003020 on 817, a
   Rutherford church on 619), and the enrichers copied that parcel's owner, values and situs.
   A row is corrected when ALL hold:
     a. its parcel_id was attached from a POINT: raw['parcel_from_geo'] records lat/lng. The two
        stamps without coordinates ('ptscloud_pts_to_pin', 'burke_cache_situs_address') are an
        id swap and an address match, not a point attachment (281 board rows, one parcel each);
     b. that recorded point is a fallback: an enrichment_geocode county-seat centroid, or a point
        _CENTROID_MIN_COLLISIONS (8) or more rows of the board being corrected stand on
        (rounded to 5 decimals, the resolver's and board_quality's own shared-point test).
        A stale geo_imprecise flag alone is not enough: on the 10/6 board the 127 rows flagged
        imprecise whose recorded point is neither sit on unique points with 6-14 decimals
        (113 of 119), i.e. measured locations, and the flag outlived the point it described;
     c. the parcel is not the source's own: no value of the row's own source block names it
        (nc_dam_safety's NID id, the tax rolls' account numbers, ...);
     d. the row's own street (not one written from a parcel record) does not agree with the
        parcel's situs (same real house number and street name). A condo unit at its master
        parcel's address, or a property that really sits at a shared point, keeps its parcel.
   What goes: parcel_id; raw['parcel_from_geo'] (into the audit, so placeholder_twins'
   resolver_parcel / fallback_point_parcel tests stop applying to a later, honest parcel); raw blocks that name the parcel (gis_attrs_full,
   owner_mailing, situs_road_only, lrcpwa, other parcel-id keys) or show its assessor photo;
   raw['gis'] entries equal to the parcel's record; top-level owner/value/size/zoning fields
   equal to the parcel's record (its gis_attrs_full bag, owner_mailing block and parcel_cache
   row) and absent from the source's own block; street/city/ZIP only when the street was written
   from a parcel record (raw['situs_address_source']) and is that parcel's situs. Audit:
   raw['parcel_withdrawn_fallback_point'].

2. OWNER MAILING SHOWN AS THE PROPERTY ADDRESS (item 69). Several county layers publish the
   owner's mailing block under generic names, and the old pickers and three sources published it
   as the property. The classifier is item 69's: the row's street is compared with its parcel's
   situs and owner mailing in parcel_cache (the county's layer, or NC OneMap's for Buncombe,
   Lincoln and Transylvania). A street matching the situs
   is left alone (owner-occupied included). A street matching the mailing and not the situs is
   DEFINITE when the mailing is out of state or a PO box or the situs is on another street, and
   LIKELY when the situs is on the same street with another house number; both are corrected: the
   street becomes the cache situs (raw['situs_address_source'] 'parcel_cache:<tier>'), or None
   when the parcel has no situs or no real house number; city/ZIP become the situs city/ZIP of a
   bag of the same parcel on the row, else None (they came with the mailing block). A street
   equal to the mailing of a parcel whose county publishes no situs is unverifiable and left, and
   so is a row whose parcel was found from its own street or point (parcel_found_from_street:
   there the parcel, not the street, is the suspect).
   This also covers the ~100 rows whose address an enricher wrote onto an address-less source row
   (asheville_helene, Lincoln PDF rows via the name resolver, Spartanburg lis pendens): same test,
   same correction. Audit: raw['address_was_owner_mailing']. Needs data/parcel_cache: a county
   without a cache is skipped and logged (never guessed).
   THE POINT (map pin). Nothing records where a row's lat/lng came from except two tags, so it
   was measured (docs/HANDOFF.md item 71, pins): on the 1,254 rows this corrects on the 10/6
   board only 458 points lie inside the row's own parcel. 'census_geocode' points
   (resolver_backfill_geocode / geocode_catchup geocoding the street, i.e. the mailing) sit
   within 100 m of the mailing's own geocode on 326 of 383; the untagged ones (the run's
   enrichment_geocode writes no tag) are half and half; centroid_snap / county_centroid ones are
   shared fallbacks. Only raw['geo_source'] 'parcel_polygon_centroid' (a scraper's own parcel
   polygon centroid, spartanburg_vacant) proves the point is the parcel's: 97 of 115 inside it.
   So with a corrected street the point is KEPT only when it is the parcel's polygon centroid;
   else REPLACED by the parcel's own point when the run already holds one (a same-parcel bag's
   '_centroid', or another row of the same parcel whose point is that parcel's polygon centroid
   or a precise resolver point of it, parcel_points()); else CLEARED. The tags that described the
   old point go with it. Old point and tags: raw['address_was_owner_mailing']['point'].
   A cleared row (or one that had no point) is 'awaiting_parcel_point': enrichment_geocode first
   asks the county parcel layer for that parcel's polygon (place_parcel_points), then geocodes
   the corrected street only when the row has a city or ZIP, and never puts it on a city or
   county-seat centroid (its Tier 3/4): a corrected row has no city/ZIP, so Tier 4 would have
   put it on the county seat, the shared fallback point of item 70. Unplaced, it waits for a
   later run. Replayed on the 10/6 board: 115 kept, 19 replaced, 1,113 cleared and 7 without a
   point; the layer placed 1,016 (115 s), 104 stay unplaced (Oconee's layer has no geometry: 70);
   1,138 of the 1,254 pins end inside the row's own parcel polygon.

3. SUPERSEDED MAILING COPIES. A prior copy whose street was the owner's mailing has a different
   house number from its fresh situs row, so merge_prior_board's house-number guard keeps it
   beside that row as presumed_withdrawn (item 69: all 255 pre-9/29 buncombe_unpaid_bills rows,
   the buncombe_elderly rows). Once corrected it duplicates the fresh row, and dedupe2 would fold
   its enrichment (images, vision, comps of the mailing address) into the fresh row. So an aged
   row (raw['pulled_sale'], set only on prior-only rows by merge_prior_board) corrected by 2 is
   DROPPED when a re-scraped row of the same parcel shares a source with it; the live row keeps
   the earlier first_seen and a short record in raw['superseded_mailing_copies']. Without such
   a live row (the bill was paid) the corrected copy stays and ages as before.

MEMORY. Three light passes and one correcting pass over the in-memory list; the lookup tables
are the recorded resolver points (2,331 on the 10/6 board), their row counts, the parcel points
of rows that carry one (parcel_points: polygon centroids and precise resolver points, a few
thousand), and the parcel keys of the corrected aged rows. No row is copied. County caches are read through CacheReader, which caps
SQLite's page cache and closes what it opened. main.run() wraps the call: it never fails a run.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Iterable, Optional

import structlog

from .models import Listing, _normalize_parcel

log = structlog.get_logger()

FALLBACK_KEY = "parcel_withdrawn_fallback_point"
MAILING_KEY = "address_was_owner_mailing"
SUPERSEDED_KEY = "superseded_mailing_copies"

#: raw['parcel_from_geo']['source'] values that record an id swap or an address match, not a point.
NON_POINT_STAMPS = frozenset({"ptscloud_pts_to_pin", "burke_cache_situs_address"})

#: raw['geo_source'] values that say the row's point is its own parcel's polygon centroid.
PARCEL_POINT_SOURCES = frozenset({"parcel_polygon_centroid"})
#: raw tags that describe the row's current point: they leave with a replaced or cleared point.
POINT_TAGS = ("geo_imprecise", "geocoded_by_name", "geo_missing", "geo_source")
#: Where a replacement point came from -> the raw['geo_source'] it is published with.
_POINT_GEO_SOURCE = {"row_parcel_bag": "parcel_polygon_centroid",
                     "sibling_parcel_centroid": "parcel_polygon_centroid",
                     "sibling_resolver_point": "parcel_resolver_point",
                     "parcel_layer": "parcel_polygon_centroid"}
#: NC + SC, generously: a parcel point outside it is a projection or id mix-up, never used.
_AREA = (32.0, 37.5, -85.0, -75.0)
#: Two points of one parcel farther apart than this are not trusted as "the parcel's point".
_SAME_PARCEL_M = 150.0

#: Keys (lower case) under which a raw block names a parcel id.
_PARCEL_ID_KEYS = frozenset({
    "parcel_id", "parcelid", "parcel", "parno", "altparno", "nparno", "pin", "pinnum", "tms",
    "taxpin", "pid", "parcel_number", "parcelnumber", "resolved_parcel_id", "parcel_ids",
})
#: Raw blocks a correction never touches: provenance, aging and the audit records themselves.
_PROTECTED_RAW = frozenset({
    "also_seen_in", "pulled_sale", "parcel_id_nulled", FALLBACK_KEY, MAILING_KEY, SUPERSEDED_KEY,
})
#: Blocks that are a parcel's own record: removed whole when they name the withdrawn parcel.
_PARCEL_BLOCKS = frozenset({"gis_attrs_full", "situs_road_only", "lrcpwa"})
#: Blocks that show the parcel's assessor photo (raw['images'] and its aliases).
_PHOTO_BLOCKS = ("images", "zillow", "vision", "vision_fetch_failed")
#: owner_mailing.source values that mean "read from a parcel layer" (repair_parcel_from_address).
_PARCEL_MAILING_SOURCES = frozenset({None, "", "county_gis", "nc_onemap", "scdot_sc", "sc_assessor_roll",
                                     "county_tax_roll", "henderson_county_gis"})

#: top-level field -> (substrings of the record key it may equal, minimum value). '' = any key.
_NUMERIC_FIELDS = {
    "market_value": ("", 1000.0), "tax_value": ("", 1000.0), "assessed_value": ("", 1000.0),
    "acreage": ("acre", 0.0), "living_sqft": ("sqft|sq_ft|area|heated|living|bldg", 200.0),
    "lot_size_sqft": ("lot|sqft", 200.0), "year_built": ("year|yr|built", 1700.0),
    "bedrooms": ("bed", 0.0), "bathrooms": ("bath", 0.0),
}
_STRING_FIELDS = {"zoning": "zon", "land_use": "use|class|luc"}


# ------------------------------------------------------------------------------------- helpers
def _get(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _nz(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _naive(dt: Any) -> Any:
    return dt.replace(tzinfo=None) if isinstance(dt, datetime) and dt.tzinfo is not None else dt


def _point(lat: Any, lng: Any) -> Optional[tuple]:
    try:
        return (round(float(lat), 5), round(float(lng), 5))
    except (TypeError, ValueError):
        return None


def _in_area(lat: Any, lng: Any) -> bool:
    try:
        la, lo = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    return _AREA[0] <= la <= _AREA[1] and _AREA[2] <= lo <= _AREA[3]


def _dist_m(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def county_name(county: Any) -> str:
    """'Buncombe County' / 'NEW HANOVER' -> 'Buncombe' / 'New Hanover' (parcel_cache's naming)."""
    c = " ".join(str(county or "").split())
    if c.lower().endswith(" county"):
        c = c[:-7]
    return " ".join(w.capitalize() for w in c.split())


def source_blocks(row: Any) -> list[dict]:
    """The row's own source data in raw: blocks named after a segment of its source slug
    ('counties_generic.state_contamination.nc_dam_safety' -> raw['state_contamination'],
    raw['nc_dam_safety'])."""
    raw = _raw(row)
    out = []
    for seg in str(_get(row, "source") or "").split("."):
        blk = raw.get(seg)
        if seg and isinstance(blk, dict):
            out.append(blk)
    return out


def _scalars(d: Any, depth: int = 2):
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)) and depth > 1:
                yield from _scalars(v, depth - 1)
            elif not isinstance(v, (dict, list)):
                yield k, v
    elif isinstance(d, list):
        for v in d:
            if isinstance(v, (dict, list)) and depth > 1:
                yield from _scalars(v, depth - 1)
            elif not isinstance(v, (dict, list)):
                yield None, v


def _source_values(row: Any) -> tuple[set, list, set]:
    """(normalized strings, numbers, parcel-normalized ids) of the row's own source blocks."""
    strs, nums, ids = set(), [], set()
    for blk in source_blocks(row):
        for _k, v in _scalars(blk):
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                p = _normalize_parcel(str(v))
                if p:
                    ids.add(p)
            if isinstance(v, str) and _nz(v):
                strs.add(_nz(v))
            n = _num(v)
            if n is not None:
                nums.append(n)
    return strs, nums, ids


def names_parcel(block: Any, pid_norm: str) -> bool:
    """A raw block names the parcel under one of _PARCEL_ID_KEYS (depth <= 2)."""
    if not pid_norm or not isinstance(block, dict):
        return False
    for k, v in block.items():
        kl = str(k).lower()
        if kl in _PARCEL_ID_KEYS:
            vals = v if isinstance(v, list) else [v]
            if any(isinstance(x, (str, int)) and _normalize_parcel(str(x)) == pid_norm for x in vals):
                return True
        elif isinstance(v, dict) and names_parcel(v, pid_norm):
            return True
    return False


# ---------------------------------------------- address normalization (docs/HANDOFF.md item 69)
_SUF = {"ROAD": "RD", "STREET": "ST", "DRIVE": "DR", "AVENUE": "AVE", "LANE": "LN", "COURT": "CT",
        "CIRCLE": "CIR", "PLACE": "PL", "TRAIL": "TRL", "HIGHWAY": "HWY", "PARKWAY": "PKWY",
        "BOULEVARD": "BLVD", "TERRACE": "TER", "EXTENSION": "EXT", "MOUNTAIN": "MTN", "COVE": "CV",
        "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "POINT": "PT", "LOOP": "LOOP",
        "RIDGE": "RDG", "VIEW": "VW", "SQUARE": "SQ", "CROSSING": "XING", "HOLLOW": "HOLW", "BRANCH": "BR"}
_UNIT = re.compile(r"\s+(APT|UNIT|STE|SUITE|LOT|#|BLDG|TRLR)\b.*$")
_DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
_SUFS = {"RD", "ST", "DR", "AVE", "AV", "LN", "CT", "CIR", "PL", "TRL", "HWY", "PKWY", "BLVD", "TER", "EXT",
         "WAY", "LOOP", "RDG", "CV", "PT", "XING", "SQ", "VW", "HOLW", "BR", "RUN", "PATH", "PASS", "ROW",
         "ALY", "PIKE", "TRCE", "GRV", "HTS", "HL", "MTN", "VLY", "CRK", "SPGS"}
_REPL = {"SAINT": "ST", "MOUNT": "MT", "MOUNTAIN": "MTN", "FORT": "FT"}
_STATE_ZIP = re.compile(r"\b([A-Z]{2})\s*(\d{5})(?:-?\d{4})?\s*$")
_POBOX = re.compile(r"^(P ?O ?BOX|POST OFFICE BOX|BOX \d|PO BX|P O DRAWER|DRAWER)")


def norm_addr(s: Any) -> str:
    s = str(s or "").upper()
    s = re.sub(r"[.,#]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _UNIT.sub("", s)
    toks = [_SUF.get(t, t) for t in s.split()]
    if toks and re.fullmatch(r"0+\d*", toks[0]):
        toks[0] = toks[0].lstrip("0") or "0"
    return " ".join(toks)


def is_pobox(s: Any) -> bool:
    return bool(_POBOX.match(norm_addr(s)))


def _street_core(s: Any) -> str:
    t = norm_addr(s).split()
    if not t:
        return ""
    return t[0] + " " + t[1] if t[0].isdigit() and len(t) > 1 else t[0]


def _parse(s: Any) -> tuple[str, str]:
    t = [_REPL.get(x, x) for x in norm_addr(s).split()]
    num = t[0] if t and re.fullmatch(r"\d+[A-Z]?", t[0]) else ""
    rest = [x for x in (t[1:] if num else t) if x not in _DIRS]
    name = []
    for x in rest:
        if x in _SUFS and name:
            break
        name.append(x)
    return num.lstrip("0"), "".join(name)


def _same_name(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def classify_street(street: Any, situs: Any, mailing: Any, state: Any) -> str:
    """Item 69's classifier, for a row's street against its parcel's situs and owner mailing.

    'situs' (the parcel's own location; owner-occupied too), 'definite' / 'likely' (the owner's
    mailing shown as the property), 'unverifiable' (equals the mailing, the county has no situs),
    'same_street_no_number' (equals the mailing, the situs is that street without a number), or
    'other' / 'no_street'."""
    a = norm_addr(street)
    if not a:
        return "no_street"
    s, m = norm_addr(situs), norm_addr(mailing)
    s_bad = (not s) or s.startswith("0 ") or s.startswith("99999 ") or "NO ADDRESS" in s
    core = _street_core(a)
    if s and (a == s or s.startswith(a + " ") or a.startswith(s + " ")):
        return "situs"
    if s and core and " " in core and (s.startswith(core + " ") or s == core):
        return "situs"
    a_eq_m = bool(m) and (m == a or m.startswith(a + " "))
    core_m = bool(m) and core and " " in core and (m.startswith(core + " ") or m == core)
    if not (a_eq_m or core_m or (is_pobox(a) and is_pobox(m))):
        return "other"
    an, aname = _parse(street)
    sn, sname = _parse(situs)
    if s and sn in ("0", "99999"):
        sn = ""
    ms = _STATE_ZIP.search(m)
    out_state = bool(ms) and ms.group(1) != str(state or "").upper()
    if out_state or is_pobox(street):
        return "definite"
    if s_bad and not sname:
        return "unverifiable"
    if sname and not _same_name(aname, sname):
        return "definite"
    if sname and sn and an and sn != an:
        return "likely"
    if sname and not sn:
        return "same_street_no_number"
    return "unverifiable" if s_bad else "other"


def mask_street(s: Any) -> str:
    """A street for a log or report: house numbers and unit numbers masked."""
    return re.sub(r"\d", "#", str(s or ""))[:60]


def mask_point(p: Any) -> Optional[str]:
    """A point for a log or report: two decimals (about 1 km), never the house."""
    try:
        return f"{float(p[0]):.2f},{float(p[1]):.2f}"
    except (TypeError, ValueError, IndexError):
        return None


# ------------------------------------------------------------------------------ parcel cache
class CacheReader:
    """parcel_cache lookups with a per-county availability memo; a county without a cache file is
    recorded in `missing` and never looked up (the caller skips that correction).

    MEMORY. parcel_cache.lookup_with_tier() keeps one sqlite connection per county open for the
    life of the process (parcel_cache._CONN), each with SQLite's default page cache (up to 2 MB).
    Touching ~100 county caches that way grew RSS by 221 MB on a 42,807-row sample. A county
    connection this reader has to open is opened first with a 64 KB page cache and closed again by
    close(); one that was already open is used as it is and left open."""

    PAGE_CACHE_KB = 64

    def __init__(self, lookup: Optional[Callable] = None, available: Optional[Callable] = None):
        from . import parcel_cache as pc
        self._own_conns = lookup is None
        self._lookup = lookup or pc.lookup_with_tier
        self._available = available or self._file_exists
        self._memo: dict[tuple, bool] = {}
        self._opened: list[str] = []
        self.missing: Counter = Counter()

    def _ensure_conn(self, county: str, state: str) -> None:
        import sqlite3
        from . import parcel_cache as pc
        try:
            p = pc._db_path(county, state)
        except ValueError:
            return
        if p.name in pc._CONN or not p.exists():
            return
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.execute(f"PRAGMA cache_size=-{int(self.PAGE_CACHE_KB)}")
        pc._CONN[p.name] = con
        self._opened.append(p.name)

    def close(self) -> None:
        """Close the county connections this reader opened."""
        from . import parcel_cache as pc
        for name in self._opened:
            con = pc._CONN.pop(name, None)
            if con is not None:
                try:
                    con.close()
                except Exception:  # noqa: BLE001
                    pass
        self._opened.clear()

    @staticmethod
    def _file_exists(county: str, state: str) -> bool:
        from . import parcel_cache as pc
        try:
            return pc._db_path(county, state).exists()
        except (ValueError, OSError):
            return False

    def available(self, county: str, state: str) -> bool:
        k = (county, state)
        if k not in self._memo:
            self._memo[k] = bool(county) and bool(self._available(county, state))
        return self._memo[k]

    def lookup(self, county: str, state: str, pid: str) -> tuple[Optional[dict], Optional[str]]:
        if not self.available(county, state):
            return None, None
        try:
            if self._own_conns:
                self._ensure_conn(county, state)
            return self._lookup(county, pid, state)
        except Exception:  # noqa: BLE001 - an unreadable cache row is a miss, never a failure
            return None, None


# --------------------------------------------------------------- 1. fallback-point parcels
def recorded_point(raw: Any) -> Optional[tuple]:
    """The point raw['parcel_from_geo'] says the parcel was resolved at; None for the id/address
    stamps that carry no coordinates."""
    g = raw.get("parcel_from_geo") if isinstance(raw, dict) else None
    if not isinstance(g, dict) or g.get("source") in NON_POINT_STAMPS:
        return None
    return _point(g.get("lat"), g.get("lng"))


def candidate_points(rows: Iterable[Any]) -> set:
    """Recorded resolver points of rows that carry a parcel id."""
    out = set()
    for r in rows:
        if _get(r, "parcel_id"):
            p = recorded_point(_raw(r))
            if p is not None:
                out.add(p)
    return out


def count_points(rows: Iterable[Any], keys: set) -> Counter:
    """How many rows currently stand on each point in `keys` (rounded to 5 decimals)."""
    n: Counter = Counter()
    if not keys:
        return n
    for r in rows:
        p = _point(_get(r, "latitude"), _get(r, "longitude"))
        if p is not None and p in keys:
            n[p] += 1
    return n


def fallback_reason(li: Any, point_counts: Counter, min_rows: int) -> Optional[str]:
    """'county_seat_point' / 'shared_point' when li's parcel was resolved at a fallback point."""
    from .enrichment_geocode import is_county_seat_point
    raw = _raw(li)
    p = recorded_point(raw)
    if p is None or not _get(li, "parcel_id"):
        return None
    g = raw["parcel_from_geo"]
    if is_county_seat_point(g.get("lat"), g.get("lng")):
        return "county_seat_point"
    if point_counts.get(p, 0) >= min_rows:
        return "shared_point"
    return None


def parcel_record(li: Any, pid: str, cache: Optional[CacheReader]) -> dict:
    """What the row holds (or the cache knows) about parcel `pid`: its gis_attrs_full bag and
    owner_mailing / situs_road_only blocks when they name it, plus its parcel_cache row."""
    raw = _raw(li)
    pn = _normalize_parcel(pid)
    rec: dict = {"owners": set(), "numbers": [], "strings": [], "situs": [], "city": set(), "zip": set(),
                 "mailing": set(), "sale_amounts": set()}
    bag = raw.get("gis_attrs_full")
    if isinstance(bag, dict) and names_parcel(bag, pn):
        rec["bag"] = True
        from .enrichment_arcgis import situs_city_zip
        try:
            s, c, z = situs_city_zip(bag)
        except Exception:  # noqa: BLE001
            s = c = z = None
        low = {str(k).lower(): v for k, v in bag.items()}
        for cand in (s, low.get("siteadd"), low.get("situs"), low.get("situs_addr"), low.get("physicaladdr"),
                     low.get("phys_addr"), low.get("propertylocation")):
            if cand:
                rec["situs"].append(str(cand))
        for cand in (c, low.get("scity")):
            if cand:
                rec["city"].add(_nz(cand))
        for cand in (z, low.get("szip")):
            if cand:
                rec["zip"].add(_nz(cand)[:5])
        for k, v in bag.items():
            kl = str(k).lower()
            if isinstance(v, str) and ("own" in kl or kl in ("name1", "name2")) and "mail" not in kl:
                if _nz(v):
                    rec["owners"].add(_nz(v))
            n = _num(v)
            if n is not None:
                rec["numbers"].append((kl, n))
            elif isinstance(v, str) and _nz(v):
                rec["strings"].append((kl, _nz(v)))
            if "mail" in kl and isinstance(v, str) and _nz(v):
                rec["mailing"].add(_nz(v))
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and om.get("parcel_id") and _normalize_parcel(str(om["parcel_id"])) == pn:
        if om.get("owner"):
            rec["owners"].add(_nz(om["owner"]))
        if om.get("situs"):
            rec["situs"].append(str(om["situs"]))
        if om.get("mailing"):
            rec["mailing"].add(_nz(om["mailing"]))
    sro = raw.get("situs_road_only")
    if isinstance(sro, dict) and sro.get("parcel_id") and _normalize_parcel(str(sro["parcel_id"])) == pn:
        if sro.get("road"):
            rec["situs"].append(str(sro["road"]))
        if sro.get("city"):
            rec["city"].add(_nz(sro["city"]))
        if sro.get("zip"):
            rec["zip"].add(_nz(sro["zip"])[:5])
    if cache is not None:
        hit, _tier = cache.lookup(county_name(_get(li, "county")), str(_get(li, "state") or "").upper(), pid)
        if hit:
            rec["cache"] = True
            if hit.get("owner"):
                rec["owners"].add(_nz(hit["owner"]))
            if hit.get("address"):
                rec["situs"].append(str(hit["address"]))
            if hit.get("owner_mailing"):
                rec["mailing"].add(_nz(hit["owner_mailing"]))
            for k in ("market_value", "tax_value", "acreage", "living_sqft"):
                n = _num(hit.get(k))
                if n is not None:
                    rec["numbers"].append((k, n))
            if hit.get("land_use"):
                rec["strings"].append(("land_use", _nz(hit["land_use"])))
            amt = _num(hit.get("sale_price"))
            if amt:
                rec["sale_amounts"].add(round(amt, 2))
    return rec


def _num_matches(field: str, value: float, rec: dict) -> bool:
    keys, floor = _NUMERIC_FIELDS[field]
    if value is None or abs(value) < floor or (floor == 0.0 and value == 0):
        return False
    pats = [p for p in keys.split("|") if p]
    tol = 0.001 if field == "acreage" else 0.5
    for k, n in rec["numbers"]:
        if pats and not any(p in k for p in pats):
            continue
        if abs(n - value) <= tol:
            return True
    return False


def _str_matches(field: str, value: Any, rec: dict) -> bool:
    v = _nz(value)
    if not v:
        return False
    pats = _STRING_FIELDS[field].split("|")
    return any(s == v and any(p in k for p in pats) for k, s in rec["strings"])


def _owner_matches(value: Any, rec: dict) -> bool:
    v = _nz(value)
    if len(v) < 4:
        return False
    return any(v == o or (len(v) >= 6 and v in o) for o in rec["owners"])


def _same_numbered_street(a: Any, b: Any) -> bool:
    from .placeholder_twins import real_house_no
    an, aname = _parse(a)
    bn, bname = _parse(b)
    return bool(real_house_no(a) and real_house_no(b) and an == bn and _same_name(aname, bname))


def _photo_token(pid: str) -> str:
    return "_" + re.sub(r"[^A-Za-z0-9]", "", str(pid)) + ".jpg"


def withdraw_fallback_parcel(li: Listing, point_counts: Counter, min_rows: int,
                             cache: Optional[CacheReader]) -> Optional[dict]:
    """Correction 1 on one row. Returns the audit record when the parcel was withdrawn,
    {'exempt': reason} when the parcel was resolved at a fallback point but stays, else None.
    Everything is planned first and applied at the end, so a failure leaves the row untouched."""
    reason = fallback_reason(li, point_counts, min_rows)
    if reason is None:
        return None
    raw = _raw(li)
    pid = str(li.parcel_id)
    pn = _normalize_parcel(pid)
    src_strs, src_nums, src_ids = _source_values(li)
    if pn and pn in src_ids:
        return {"exempt": "source_parcel"}
    rec = parcel_record(li, pid, cache)
    sas = raw.get("situs_address_source")
    street = li.street_address
    if street and not sas and any(_same_numbered_street(street, s) for s in rec["situs"]):
        return {"exempt": "own_street_is_parcel_situs"}

    cleared: dict = {}          # top-level field -> old value
    # values copied from the parcel: equal to its record and absent from the source's own data
    for f in _NUMERIC_FIELDS:
        v = _num(getattr(li, f, None))
        if v is not None and not any(abs(v - n) <= 0.5 for n in src_nums) and _num_matches(f, v, rec):
            cleared[f] = getattr(li, f)
    for f in _STRING_FIELDS:
        v = getattr(li, f, None)
        if v and _nz(v) not in src_strs and _str_matches(f, v, rec):
            cleared[f] = v
    if li.owner_name and _nz(li.owner_name) not in src_strs and _owner_matches(li.owner_name, rec):
        cleared["owner_name"] = li.owner_name
    # the street, when a parcel-record writer copied this parcel's situs onto the row
    drop_sas = False
    if street and sas and any(_nz(norm_addr(street)) == _nz(norm_addr(s)) or _same_numbered_street(street, s)
                              for s in rec["situs"]):
        cleared["street_address"] = street
        drop_sas = True
        if li.city and _nz(li.city) in rec["city"]:
            cleared["city"] = li.city
        if li.zip_code and _nz(li.zip_code)[:5] in rec["zip"]:
            cleared["zip_code"] = li.zip_code
    street_unverified = bool(street and sas and not rec["situs"])  # from a parcel record; this one's situs unknown

    pop_keys: list[str] = []                 # raw blocks removed whole
    gis_drop: list[str] = []                 # raw['gis'] entries equal to the parcel's record
    id_drop: list[tuple[str, str]] = []      # (block, key) naming the parcel inside another block
    token = _photo_token(pid)
    own = source_blocks(li)
    for k, v in raw.items():
        if k in _PROTECTED_RAW or k == "parcel_from_geo" or any(v is b for b in own):
            continue
        if k in _PHOTO_BLOCKS:
            if token in json.dumps(v, default=str):
                pop_keys.append(k)
            continue
        if not isinstance(v, dict):
            continue
        if k == "gis":
            if names_parcel(v, pn):
                pop_keys.append(k)
                continue
            for sk, sv in v.items():
                if sk == "owner":
                    hit = _owner_matches(sv, rec)
                elif sk == "mailing":
                    hit = bool(_nz(sv)) and _nz(sv) in rec["mailing"]
                elif sk == "last_sale" and isinstance(sv, dict):
                    amt = _num(sv.get("amount"))
                    hit = bool(amt) and round(amt, 2) in rec["sale_amounts"]
                elif sk in ("market_value", "tax_value", "assessed_value", "living_sqft", "acreage") \
                        and _num(sv) is not None:
                    hit = any(abs(_num(sv) - n) <= 0.5 for _k, n in rec["numbers"])
                else:
                    hit = False
                if hit:
                    gis_drop.append(sk)
            continue
        if k == "owner_mailing":
            same_mail = bool(_nz(v.get("mailing"))) and _nz(v.get("mailing")) in rec["mailing"]
            if names_parcel(v, pn) or (not v.get("parcel_id") and v.get("source") in _PARCEL_MAILING_SOURCES
                                       and same_mail and rec.get("cache")):
                pop_keys.append(k)
            continue
        if names_parcel(v, pn):
            # a parcel's own record goes whole; any other block that names it (a cluster's
            # parcel list, a notice's resolved parcel) loses that id only
            if k in _PARCEL_BLOCKS:
                pop_keys.append(k)
            else:
                id_drop.extend((k, kk) for kk in v if str(kk).lower() in _PARCEL_ID_KEYS)

    # ---- apply
    for f in cleared:
        setattr(li, f, None)
    if drop_sas:
        cleared["situs_address_source"] = sas
        raw.pop("situs_address_source", None)
    removed = list(pop_keys)
    for k in pop_keys:
        raw.pop(k, None)
    if gis_drop:
        g0 = raw.get("gis")
        for sk in gis_drop:
            g0.pop(sk, None)
            removed.append(f"gis.{sk}")
        if not g0:
            raw.pop("gis", None)
    for k, kk in id_drop:
        blk = raw.get(k)
        val = blk.get(kk) if isinstance(blk, dict) else None
        if isinstance(val, list):
            blk[kk] = [x for x in val if _normalize_parcel(str(x)) != pn]
        elif val is not None and _normalize_parcel(str(val)) == pn:
            blk.pop(kk)
        removed.append(f"{k}.{kk}")
    g = raw.pop("parcel_from_geo", None)
    li.parcel_id = None
    audit = {"parcel_id": pid, "reason": reason, "point": [g.get("lat"), g.get("lng")] if isinstance(g, dict) else None,
             "rows_at_point": point_counts.get(recorded_point({"parcel_from_geo": g}) or (), 0),
             "parcel_from_geo": g, "cleared": cleared, "raw_removed": removed}
    if street_unverified:
        audit["street_unverified"] = True
    raw[FALLBACK_KEY] = audit
    li.raw = raw
    return audit


# --------------------------------------------------------- 2. owner mailing as the address
def parcel_found_from_street(raw: Any) -> bool:
    """The parcel was attached FROM the row's own location: a point resolve (raw['parcel_from_geo']
    with coordinates; a fallback point is correction 1's) or an address match
    (raw['parcel_from_address']). Then a street equal to that parcel's owner mailing and not its
    situs says the parcel is a neighbour's (the owner of the lot next door lives at the row's
    address), not that the street is wrong: the street is left (scripts/repair_parcel_from_address
    is the tool for such parcels). Measured on the 10/6 board: 30 of the 1,283 rows the classifier
    flags (hud_reac_inspection, nc_ust_incidents, asheville_str_permits, liensnc, ...)."""
    if not isinstance(raw, dict):
        return False
    return recorded_point(raw) is not None or isinstance(raw.get("parcel_from_address"), dict)


def situs_street(situs: Any) -> Optional[str]:
    """The cache situs as a street address, or None when it has no real house number ('0 X',
    '99999 X', 'U32 L053 X CT', 'S CHURCH ST EXT') or no street word. Leading zeros dropped
    ('000154 OLD GREENLEE RD' -> '154 OLD GREENLEE RD'), spacing collapsed."""
    from .placeholder_twins import is_sentinel_address
    s = " ".join(str(situs or "").split())
    m = re.match(r"^(\d+)([A-Za-z]?)\s+(.*)$", s)
    if not m or not m.group(1).lstrip("0") or is_sentinel_address(s) or not re.search(r"[A-Za-z]{2,}", m.group(3)):
        return None
    return m.group(1).lstrip("0") + m.group(2) + " " + m.group(3)


def bag_parcel_point(raw: Any, pid_norm: str) -> Optional[tuple]:
    """The '_centroid' (lat, lng) an ArcGIS query left in the row's gis_attrs_full bag, when that
    bag is the record of parcel `pid_norm`; else None."""
    bag = raw.get("gis_attrs_full") if isinstance(raw, dict) else None
    if not (isinstance(bag, dict) and names_parcel(bag, pid_norm)):
        return None
    c = bag.get("_centroid")
    if isinstance(c, (list, tuple)) and len(c) == 2 and _in_area(c[0], c[1]):
        return (float(c[0]), float(c[1]))
    return None


def parcel_points(listings: Iterable[Any], point_counts: Counter, min_rows: int) -> dict:
    """parcel key -> (lat, lng, how) for parcels that some row of `listings` places at a point of
    the parcel itself: its polygon centroid (raw['geo_source'] in PARCEL_POINT_SOURCES), or the
    precise point enrichment_parcel_from_geo resolved this parcel at (not a fallback point, not a
    flagged one). A parcel whose candidate points disagree by more than _SAME_PARCEL_M is left
    out. Light: only rows carrying such a point are looked at."""
    from .enrichment_geocode import imprecise_point_flag
    from .placeholder_twins import parcel_key
    cands: dict = defaultdict(list)
    for li in listings:
        pid = _get(li, "parcel_id")
        if not pid:
            continue
        raw = _raw(li)
        if raw.get("geo_source") in PARCEL_POINT_SOURCES:
            p, how = _point(_get(li, "latitude"), _get(li, "longitude")), "sibling_parcel_centroid"
        else:
            p = recorded_point(raw)
            if p is None or imprecise_point_flag(raw) or fallback_reason(li, point_counts, min_rows):
                continue
            how = "sibling_resolver_point"
        if p is None or not _in_area(*p):
            continue
        k = parcel_key(_get(li, "state"), _get(li, "county"), pid)
        if k:
            cands[k].append((p, how))
    out = {}
    for k, lst in cands.items():
        lst.sort(key=lambda x: x[1] != "sibling_parcel_centroid")       # a polygon centroid first
        p0 = lst[0][0]
        if all(_dist_m(p0, p) <= _SAME_PARCEL_M for p, _how in lst):
            out[k] = (p0[0], p0[1], lst[0][1])
    return out


def plan_point(li: Listing, raw: dict, points: Optional[dict]) -> dict:
    """What happens to the point of a row whose street correction 2 corrects (module docstring,
    THE POINT): 'kept' (it is the parcel's polygon centroid), 'replaced' (by the parcel's own
    point, from the row's bag or `points`), 'cleared', or 'absent' (no point and no replacement).
    Pure: returns the plan, changes nothing."""
    has = li.latitude is not None and li.longitude is not None
    old = [li.latitude, li.longitude] if has else None
    if has and raw.get("geo_source") in PARCEL_POINT_SOURCES:
        return {"action": "kept", "old": old, "why": raw["geo_source"]}
    new, how = bag_parcel_point(raw, _normalize_parcel(str(li.parcel_id))), "row_parcel_bag"
    if new is None and points:
        from .placeholder_twins import parcel_key
        hit = points.get(parcel_key(li.state, li.county, li.parcel_id))
        if hit:
            new, how = (hit[0], hit[1]), hit[2]
    plan: dict = {"action": "replaced" if new else ("cleared" if has else "absent"), "old": old}
    tags = {k: raw[k] for k in POINT_TAGS if k in raw}
    if tags:
        plan["tags"] = tags
    if new:
        plan["new"] = [new[0], new[1]]
        plan["from"] = how
    return plan


def _apply_point(li: Listing, raw: dict, plan: dict) -> None:
    if plan["action"] == "kept":
        return
    for k in plan.get("tags", {}):
        raw.pop(k, None)
    if plan["action"] == "replaced":
        li.latitude, li.longitude = plan["new"]
        raw["geo_source"] = _POINT_GEO_SOURCE[plan["from"]]
    else:
        li.latitude = li.longitude = None


def awaiting_parcel_point(raw: Any) -> bool:
    """Correction 2 left this row without a point (cleared, or it had none) and nothing has
    placed it since: enrichment_geocode asks the parcel layer first and never gives it a city or
    county-seat centroid."""
    a = raw.get(MAILING_KEY) if isinstance(raw, dict) else None
    p = a.get("point") if isinstance(a, dict) else None
    return isinstance(p, dict) and p.get("action") in ("cleared", "absent") and not p.get("placed")


def mark_point_placed(li: Listing, how: str) -> None:
    """Record on the audit that a later step placed the awaiting row (how, where)."""
    raw = _raw(li)
    p = (raw.get(MAILING_KEY) or {}).get("point")
    if isinstance(p, dict):
        p["placed"] = {"by": how, "at": [li.latitude, li.longitude]}


def restore_situs(li: Listing, cache: CacheReader, points: Optional[dict] = None) -> Optional[dict]:
    """Correction 2 on one row. Returns the audit record when the street was replaced or nulled,
    {'skip': reason} when the row could not be checked, else None. `points` is parcel_points()
    of the rows being corrected (a replacement for a point derived from the mailing)."""
    pid, street, state = li.parcel_id, li.street_address, str(li.state or "").upper()
    if not (pid and street and state and li.county):
        return None
    county = county_name(li.county)
    if not cache.available(county, state):
        cache.missing[f"{state}|{county}"] += 1
        return {"skip": "no_cache"}
    hit, tier = cache.lookup(county, state, str(pid))
    if not hit or not hit.get("owner_mailing"):
        return None
    situs = hit.get("address")
    cls = classify_street(street, situs, hit["owner_mailing"], state)
    if cls not in ("definite", "likely"):
        return None
    raw = _raw(li)
    if parcel_found_from_street(raw):
        return {"skip": "parcel_found_from_street"}
    new_street = situs_street(situs)
    new_city = new_zip = None
    bag = raw.get("gis_attrs_full")
    if new_street and isinstance(bag, dict) and names_parcel(bag, _normalize_parcel(str(pid))):
        from .enrichment_arcgis import situs_city_zip
        try:
            s, c, z = situs_city_zip(bag)
        except Exception:  # noqa: BLE001
            s = c = z = None
        low = {str(k).lower(): v for k, v in bag.items()}
        bs = s or low.get("siteadd")
        if bs and _same_numbered_street(bs, new_street):
            new_city = (c or low.get("scity") or None)
            zz = re.sub(r"\D", "", str(z or low.get("szip") or ""))[:5]
            new_zip = zz if len(zz) == 5 else None
    audit = {"class": cls, "street_address": street, "city": li.city, "zip_code": li.zip_code,
             "situs_address_source": raw.get("situs_address_source"), "parcel_id": pid,
             "situs": new_street, "cache_tier": tier}
    audit["point"] = plan_point(li, raw, points)
    _apply_point(li, raw, audit["point"])
    li.street_address = new_street
    li.city = new_city
    li.zip_code = new_zip
    if new_street:
        raw["situs_address_source"] = f"parcel_cache:{tier or 'exact'}"
    else:
        raw.pop("situs_address_source", None)
        audit["nulled"] = "no_situs" if not situs else "situs_without_house_number"
    raw[MAILING_KEY] = audit
    li.raw = raw
    return audit


# ------------------------------------------------------------- 3. superseded mailing copies
def _aged(li: Any) -> bool:
    return bool(_raw(li).get("pulled_sale"))


def drop_superseded(listings: list[Listing], corrected_aged: list[Listing]) -> tuple[list, Counter]:
    """Correction 3. Rows of `corrected_aged` that a re-scraped row of the same parcel and a shared
    source supersedes; the live row keeps the earlier first_seen and a short record."""
    from .placeholder_twins import parcel_key, sources_of
    keys = {}
    for r in corrected_aged:
        k = parcel_key(r.state, r.county, r.parcel_id)
        if k:
            keys.setdefault(k, []).append(r)
    dropped: list = []
    by: Counter = Counter()
    if not keys:
        return dropped, by
    live: dict = defaultdict(list)
    for li in listings:
        if _aged(li) or not li.parcel_id:
            continue
        k = parcel_key(li.state, li.county, li.parcel_id)
        if k in keys:
            live[k].append(li)
    for k, rows in keys.items():
        for r in rows:
            old = _nz(norm_addr(_raw(r).get(MAILING_KEY, {}).get("street_address")))
            twins = [L for L in live.get(k, ()) if L is not r
                     and sources_of(r.source, _raw(r)) & sources_of(L.source, _raw(L))
                     and _nz(norm_addr(L.street_address)) != old]
            if not twins:
                continue
            L = twins[0]
            lr = _raw(L)
            fs_r, fs_l = _naive(r.first_seen), _naive(L.first_seen)
            if fs_r and fs_l and fs_r < fs_l:
                L.first_seen = r.first_seen
            rec = lr.get(SUPERSEDED_KEY) if isinstance(lr.get(SUPERSEDED_KEY), list) else []
            if len(rec) < 5:
                rec.append({"street_address": _raw(r)[MAILING_KEY].get("street_address"),
                            "first_seen": str(r.first_seen)[:19], "source": r.source})
            lr[SUPERSEDED_KEY] = rec
            L.raw = lr
            dropped.append(r)
            by[(r.source, county_name(r.county))] += 1
    return dropped, by


# ------------------------------------------ the parcel's own point, for rows awaiting one
def _dashed(*widths: int) -> Callable:
    """A formatter for a county that stores its PIN dashed while the board keeps the digits."""
    def fmt(d: str) -> Optional[str]:
        if not d.isdigit() or len(d) != sum(widths):
            return None
        out, i = [], 0
        for w in widths:
            out.append(d[i:i + w])
            i += w
        return "-".join(out)
    return fmt


#: Board ids a county layer stores formatted (the board keeps them with punctuation stripped).
_LAYER_ID_FORMATS: dict = {
    # parcel_cache's Spartanburg entry: board 12-digit id = GISParcelNumber (7102-28-3341.88)
    ("SC", "Spartanburg"): (lambda d: f"{d[:4]}-{d[4:6]}-{d[6:10]}.{d[10:]}"
                            if len(d) == 12 and d.isdigit() else None),
    # NC OneMap parno for Transylvania is dashed 4-2-4-3; 136 of the 144 corrected Transylvania
    # rows carry the 13 bare digits (measured 2026-10-06)
    ("NC", "Transylvania"): _dashed(4, 2, 4, 3),
}
#: Wall-clock cap on the parcel-layer queries of one geocode phase. Queries are batched (an IN
#: list per county), so the first run after this shipped (about 1,120 rows) needs a few dozen.
PARCEL_POINT_BUDGET_S = float(os.environ.get("GEOCODE_PARCEL_POINT_BUDGET_S", "300"))
#: Ids per IN (...) query: keeps the GET under ~2 KB.
_IN_CHUNK = 40


def layer_id_forms(pid: Any, county: str, state: str) -> list[str]:
    """The id literals to try against the county layer for board parcel id `pid`: as written,
    parcel_cache's exact and zero-suffix forms (never its zero-padded guesses), and the county's
    own formatting when the board stores it stripped (_LAYER_ID_FORMATS). At most 4."""
    from . import parcel_cache as pcache
    s = " ".join(str(pid or "").split())
    if not s:
        return []
    forms = [s] + [k for k, tier in pcache._lookup_candidates(s) if tier in ("exact", "zero_suffix")]
    fmt = _LAYER_ID_FORMATS.get((state, county))
    if fmt:
        forms.append(fmt(re.sub(r"\D", "", s)))
    out: list[str] = []
    for f in forms:
        if f and f not in out:
            out.append(f)
    return out[:4]


def _ring_area2(ring: list) -> float:
    ox, oy = ring[0]
    a2 = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        a2 += (x0 - ox) * (y1 - oy) - (x1 - ox) * (y0 - oy)
    return a2


def _inside(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def polygon_centroid(geom: Any) -> Optional[tuple]:
    """(lat, lng) of an ArcGIS geometry in WGS84 for a map pin INSIDE the parcel: a point as is;
    for a polygon, the area-weighted centroid of its largest ring (by area), computed relative to
    the ring's first vertex (raw-coordinate cross products lose metres to cancellation); when a
    concave lot puts that centroid outside the ring (9 of the first replay's 880 placed points),
    the middle of the widest stretch of the ring along the centroid's latitude.
    None outside NC/SC."""
    if not isinstance(geom, dict):
        return None
    if "x" in geom and "y" in geom:
        lat, lng = geom.get("y"), geom.get("x")
    else:
        rings = []
        for r in geom.get("rings") or []:
            pts = [(float(p[0]), float(p[1])) for p in r if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(pts) >= 3:
                rings.append(pts)
        if not rings:
            return None
        ring = max(rings, key=lambda r: abs(_ring_area2(r)))
        ox, oy = ring[0]
        rel = [(x - ox, y - oy) for x, y in ring]
        a2 = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(rel, rel[1:] + rel[:1]):
            cross = x0 * y1 - x1 * y0
            a2 += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(a2) < 1e-18:
            lng, lat = sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)
        else:
            lng, lat = ox + cx / (3.0 * a2), oy + cy / (3.0 * a2)
            if not _inside(lng, lat, ring):
                xs = sorted((x0 + (lat - y0) * (x1 - x0) / (y1 - y0))
                            for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]) if (y0 > lat) != (y1 > lat))
                spans = [(xs[i + 1] - xs[i], (xs[i] + xs[i + 1]) / 2) for i in range(0, len(xs) - 1, 2)]
                if spans:
                    lng = max(spans)[1]
    if not _in_area(lat, lng):
        return None
    return round(float(lat), 6), round(float(lng), 6)


def _layer_cfg(county: str, state: str) -> Optional[dict]:
    from . import parcel_cache as pcache
    cfg = pcache.resolve_layer_cfg(county)
    if not cfg or (cfg.get("state") and cfg["state"] != state) \
            or (not cfg.get("state") and county in pcache.DUAL_STATE_COUNTIES):
        return None
    return cfg


def _attr(attrs: dict, field: str) -> Any:
    if field in attrs:
        return attrs[field]
    low = field.lower()
    return next((v for k, v in attrs.items() if str(k).lower() == low), None)


async def parcel_layer_points(c: Any, county: str, state: str, pids: list[str],
                              deadline: Optional[float] = None) -> dict:
    """{pid: (point, outcome)} for board parcel ids of one county: each parcel's pin from its
    polygon on the county layer parcel_cache reads (parcel_cache.resolve_layer_cfg: the county's
    own layer, or NC OneMap restricted to the county), queried as IN (...) lists of the exact id
    forms (layer_id_forms), so a point is that parcel's or nothing. Outcomes: placed, not_found,
    no_geometry (Oconee's assessor table), ambiguous (one id, polygons more than _SAME_PARCEL_M
    apart), no_layer, layer_error, budget_skip (past `deadline`, a time.monotonic() value)."""
    from .enrichment_parcel_from_geo import _arc_query
    cfg = _layer_cfg(county, state)
    if cfg is None:
        return {p: (None, "no_layer") for p in pids}
    base = cfg.get("where")
    out: dict = {}
    remaining = {p: layer_id_forms(p, county, state) for p in dict.fromkeys(pids)}
    errored: set = set()
    for field in list(cfg.get("id_fields") or [])[:2]:
        if not remaining:
            break
        forms = list(dict.fromkeys(f for fs in remaining.values() for f in fs))
        found: dict = defaultdict(list)                 # form (as the layer stores it) -> features
        for i in range(0, len(forms), _IN_CHUNK):
            part = forms[i:i + _IN_CHUNK]
            if deadline is not None and time.monotonic() > deadline:
                for p, fs in remaining.items():
                    if p not in out and set(fs) & set(part):
                        out[p] = (None, "budget_skip")
                continue
            cond = f"{field} IN (" + ",".join("'" + f.replace("'", "''") + "'" for f in part) + ")"
            feats = await _arc_query(c, cfg["url"], {
                "where": f"({base}) AND {cond}" if base else cond, "outFields": field,
                "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6",
                "resultRecordCount": str(3 * len(part) + 10), "f": "json"})
            if feats is None:
                errored.update(p for p, fs in remaining.items() if set(fs) & set(part))
                continue
            for f in feats:
                v = _attr(f.get("attributes") or {}, field)
                if v is not None:
                    found[str(v).strip().upper()].append(f)
        for p, fs in list(remaining.items()):
            if p in out:
                del remaining[p]
                continue
            hit = next((found[f.strip().upper()] for f in fs if found.get(f.strip().upper())), None)
            if hit is None:
                continue
            pts = [q for q in (polygon_centroid(f.get("geometry")) for f in hit) if q]
            if not pts:
                out[p] = (None, "no_geometry")
            elif any(_dist_m(pts[0], q) > _SAME_PARCEL_M for q in pts[1:]):
                out[p] = (None, "ambiguous")
            else:
                out[p] = (pts[0], "placed")
            del remaining[p]
    for p in remaining:
        out.setdefault(p, (None, "layer_error" if p in errored else "not_found"))
    return out


async def parcel_layer_point(c: Any, county: str, state: str, pid: str) -> tuple[Optional[tuple], str]:
    """parcel_layer_points() for one parcel id."""
    return (await parcel_layer_points(c, county, state, [pid]))[pid]


async def place_parcel_points(c: Any, rows: list, budget_s: Optional[float] = None,
                              concurrency: int = 4) -> Counter:
    """Put each row of `rows` (awaiting_parcel_point) on its parcel's pin from the county layer
    (parcel_layer_points, one batch of queries per county); raw['geo_source']
    'parcel_polygon_centroid' and the audit's point.placed record it. A row the layer cannot
    place keeps no point. Never raises; counts by outcome."""
    budget = PARCEL_POINT_BUDGET_S if budget_s is None else budget_s
    deadline = time.monotonic() + budget
    n: Counter = Counter()
    groups: dict = defaultdict(list)
    for li in rows:
        if li.parcel_id and li.county and li.state:
            groups[(county_name(li.county), str(li.state).upper())].append(li)
        else:
            n["no_parcel"] += 1
    sem = asyncio.Semaphore(concurrency)

    async def one(county: str, state: str, lis: list) -> None:
        async with sem:
            try:
                res = await parcel_layer_points(c, county, state, [str(li.parcel_id) for li in lis], deadline)
            except Exception:  # noqa: BLE001 - a layer failure leaves the rows for the next run
                res = {}
        for li in lis:
            p, outcome = res.get(str(li.parcel_id), (None, "error"))
            n[outcome] += 1
            if p and (li.latitude is None or li.longitude is None):
                li.latitude, li.longitude = p
                raw = _raw(li)
                raw["geo_source"] = "parcel_polygon_centroid"
                li.raw = raw
                mark_point_placed(li, "parcel_layer")

    await asyncio.gather(*(one(cty, st, lis) for (cty, st), lis in groups.items()))
    return n


# ------------------------------------------------------------------------------- the step
def correct_prior_rows(listings: list[Listing], cache: Optional[CacheReader] = None,
                       min_rows: Optional[int] = None, sample: int = 6) -> dict:
    """Correct, IN PLACE, the carried data described in the module docstring on the merged board
    `listings` (rows may be removed by correction 3). Returns the stats main.run() logs."""
    from .enrichment_board_quality import _CENTROID_MIN_COLLISIONS
    if min_rows is None:
        min_rows = _CENTROID_MIN_COLLISIONS
    if cache is None:
        cache = CacheReader()
    stats: dict = {"rows": len(listings)}
    c1: Counter = Counter()
    c1_by: Counter = Counter()
    c1_parcels: Counter = Counter()
    c1_fields: Counter = Counter()
    c2: Counter = Counter()
    c2_by: Counter = Counter()
    samples: dict = defaultdict(list)
    errors = 0
    keys = candidate_points(listings)
    point_counts = count_points(listings, keys)
    points = parcel_points(listings, point_counts, min_rows)
    c2_point: Counter = Counter()
    corrected_aged: list = []
    try:
        for li in listings:
            if not isinstance(li.raw, dict):
                continue
            try:
                a1 = withdraw_fallback_parcel(li, point_counts, min_rows, cache)
                if a1 is not None:
                    if "exempt" in a1:
                        c1["exempt_" + a1["exempt"]] += 1
                    else:
                        c1[a1["reason"]] += 1
                        c1_by[(li.source, county_name(li.county))] += 1
                        c1_parcels[f"{li.state}|{county_name(li.county)}|{a1['parcel_id']}"] += 1
                        for f in a1["cleared"]:
                            c1_fields[f] += 1
                        for k in a1["raw_removed"]:
                            c1_fields["raw." + k.split(".")[0]] += 1
                        if len(samples["fallback"]) < sample:
                            samples["fallback"].append((str(li.source).split(".")[-1], county_name(li.county),
                                                        a1["parcel_id"], a1["reason"], sorted(a1["cleared"])))
                a2 = restore_situs(li, cache, points)
                if a2 is not None:
                    if "skip" in a2:
                        c2["skip_" + a2["skip"]] += 1
                    else:
                        c2[a2["class"]] += 1
                        c2["nulled" if a2.get("nulled") else "replaced"] += 1
                        pt = a2.get("point") or {}
                        c2_point[pt.get("action")] += 1
                        if pt.get("from"):
                            c2_point["from_" + pt["from"]] += 1
                        if pt.get("action") in ("replaced", "cleared") and len(samples["point"]) < sample:
                            samples["point"].append((str(li.source).split(".")[-1], county_name(li.county),
                                                     pt["action"], mask_point(pt.get("old")), mask_point(pt.get("new")),
                                                     (pt.get("tags") or {}).get("geo_imprecise")))
                        c2_by[(li.source, county_name(li.county), a2["class"])] += 1
                        if _aged(li):
                            corrected_aged.append(li)
                        if len(samples["mailing"]) < sample:
                            samples["mailing"].append((str(li.source).split(".")[-1], county_name(li.county), a2["class"],
                                                       mask_street(a2["street_address"]), mask_street(a2["situs"])))
            except Exception as exc:  # noqa: BLE001 - one malformed row never stops the step
                errors += 1
                if errors <= 3:
                    log.warning("prior_correction.row_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}",
                                source=getattr(li, "source", None))
    finally:
        cache.close()
    dropped, c3_by = drop_superseded(listings, corrected_aged)
    if dropped:
        gone = {id(r) for r in dropped}
        listings[:] = [li for li in listings if id(li) not in gone]
    stats.update({
        "fallback_withdrawn": sum(v for k, v in c1.items() if not k.startswith("exempt_")),
        "fallback_by_reason": dict(c1),
        "fallback_parcels": len(c1_parcels),
        "fallback_top_parcels": c1_parcels.most_common(8),
        "fallback_fields_cleared": dict(c1_fields.most_common()),
        "fallback_by_source_county": {f"{s}|{c}": n for (s, c), n in c1_by.most_common(15)},
        "mailing_corrected": c2.get("definite", 0) + c2.get("likely", 0),
        "mailing_by_class": dict(c2),
        "mailing_by_source_county": {f"{s}|{c}|{k}": n for (s, c, k), n in c2_by.most_common(20)},
        "mailing_point": dict(c2_point),
        "parcel_points_indexed": len(points),
        "superseded_dropped": len(dropped),
        "superseded_by_source_county": {f"{s}|{c}": n for (s, c), n in c3_by.most_common(10)},
        "cache_missing_counties": dict(cache.missing.most_common(20)),
        "row_errors": errors,
        "samples": {k: v for k, v in samples.items()},
        "rows_after": len(listings),
        "points_indexed": len(keys),
    })
    if cache.missing:
        log.warning("prior_correction.parcel_cache_missing",
                    note="owner-mailing correction skipped for these counties (no data/parcel_cache file)",
                    counties=dict(cache.missing.most_common(30)))
    return stats
