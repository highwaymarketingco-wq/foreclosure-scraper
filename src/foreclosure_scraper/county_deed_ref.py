"""The county parcel record's own latest-deed reference for one parcel: raw['county_deed_ref'].

WHY (audit 2026-10-09, lawyer_lane). A register chain is found by the OWNER'S NAME; it is tied to
the row's parcel only through the county parcel record (enrichment_rod_chain.bind_chain). On the
10/9 checkpoint 60% of quiet-title candidates in the register counties had no county last-sale
date on the row and almost none a deed book/page, so their chains could never be bound and no
latest deed could be handed to the attorney. The county's parcel record names the deed it was
last conveyed by; this module reads it for one parcel.

SOURCE (NC): NC OneMap statewide parcels (services.nconemap.gov ... NC1Map_Parcels/FeatureServer/1;
free, open, no key; the layer quiet_title/adapters/nc_onemap.py documents). Fields asked for by
name: parno, altparno, cntyname, sourceref (the assessor's 'Deed Book/Page 001234/00567'),
sourcedatx (its date as written), saledatetx. Nothing personal is requested.
SC: no statewide layer (SCDOT is token-walled since 2026-08-12). The county's own parcel layer
for the SC counties whose register a platform adapter reads (SC_LAYERS: the layer URL and id
fields are parcel_cache.PARCEL_LAYERS'; the deed fields were read off each layer's field list
2026-10-09): Greenville CUBOOK/CUPAGE/DEEDDATE, Greenwood Deed ('1612-2907')/PurchaseDate,
Spartanburg and Horry DeedBook/DeedPage/SaleDate, Oconee deed_book/deed_page, Pickens SALEDT.
Union and Marlboro publish no free parcel layer (Union answers 403): not read.

POLITENESS: one request per parcel, one at a time (a module lock), at least MIN_GAP_S (2 s) apart,
with the register adapters' ordinary browser headers (rod/nc_polite.HEADERS).

raw['county_deed_ref'] = {source: 'nc_onemap', parno, book, page, date, fetched_at}
(book/page without zero padding; date ISO as precise as the layer writes it; None when blank).
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

ONEMAP_QUERY = "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1/query"
FIELDS = "parno,altparno,cntyname,sourceref,sourcedatx,saledatetx"
#: at least this many seconds between two requests to the layer's host
MIN_GAP_S = 2.0
_lock = threading.Lock()
_last = [0.0]


_BARE = re.compile(r"^\s*(?:[A-Za-z ]*Book\s*/?\s*Page:?\s*)?([0-9]{1,6}[A-Z]?|[A-Z]{1,3}[0-9]{1,5})\s*/\s*([0-9]{1,6})\s*$", re.I)


def _date(*texts: Optional[str]) -> Optional[str]:
    """The first usable date among the layer's date texts, ISO as precise as written; the layers'
    placeholders (12/30/1899, 1/1/1900, 0/0, a time alone) are not dates."""
    from .quiet_title.adapters.nc_onemap import layer_date
    for t in texts:
        s = (t or "").strip()
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        d = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
        m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
        d = d or (f"{m.group(2)}-{int(m.group(1)):02d}" if m else None) or layer_date(s)
        if d and d[:4].isdigit() and int(d[:4]) > 1900:
            return d
    return None


def parse_feature(pin: str, feats: list[dict]) -> Optional[dict]:
    """{parno, book, page, date} from the layer's attribute bags for one PIN, or None (pure).
    The deed reference as the assessors write it: 'Deed Book/Page 001234/00567', 'Sale Book/Page
    ...', or a bare '26972/906' / '2021E/127'; a plat reference or a blank one is not a deed."""
    from .quiet_title.adapters.nc_onemap import parse_ref, pick_feature
    a, _ = pick_feature(pin, feats)
    if not a:
        return None
    ref = str(a.get("sourceref") or "")
    word, book, page = parse_ref(ref)
    if word and word.lower() not in ("deed", "sale"):
        book = page = None
    if not (book and page):
        m = _BARE.match(ref)
        if m and not re.search(r"plat|map", ref, re.I):
            book, page = m.group(1).upper().lstrip("0") or None, m.group(2).lstrip("0") or None
    return {"parno": a.get("parno"), "book": book if page else None, "page": page if book else None,
            "date": _date(a.get("sourcedatx"), a.get("saledatetx"))}


#: county -> {book, page, date, combined}: the parcel layer's deed fields (None when the layer has none)
SC_LAYERS = {
    "Greenville": {"book": "CUBOOK", "page": "CUPAGE", "date": "DEEDDATE"},
    "Greenwood": {"combined": "Deed", "date": "PurchaseDate"},
    "Spartanburg": {"book": "DeedBook", "page": "DeedPage", "date": "SaleDate"},
    "Horry": {"book": "DeedBook", "page": "DeedPage", "date": "SaleDate"},
    "Oconee": {"book": "deed_book", "page": "deed_page"},
    "Pickens": {"date": "SALEDT"},
}


def _epoch_or_text(v: Any) -> Optional[str]:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 10 ** 11:
        return datetime.fromtimestamp(v / 1000, timezone.utc).date().isoformat()
    return _date(str(v)) if v not in (None, "") else None


def parse_sc(county: str, a: dict) -> Optional[dict]:
    """{book, page, date} from one SC county layer attribute bag (pure)."""
    spec = SC_LAYERS.get(county) or {}
    book = page = None
    if spec.get("combined"):
        m = re.match(r"^\s*([0-9A-Z]+)\s*[-/ ]\s*([0-9]+)\s*$", str(a.get(spec["combined"]) or ""), re.I)
        if m:
            book, page = m.group(1).upper().lstrip("0") or None, m.group(2).lstrip("0") or None
    else:
        book = str(a.get(spec.get("book") or "") or "").strip().upper().lstrip("0") or None
        page = str(a.get(spec.get("page") or "") or "").strip().lstrip("0") or None
    d = _epoch_or_text(a.get(spec["date"])) if spec.get("date") else None
    if not (book and page):
        book = page = None
    return {"book": book, "page": page, "date": d} if (book or d) else None


def fetch_sc(county: str, pin: str, client: Any = None) -> Optional[dict]:
    """raw['county_deed_ref'] for one SC parcel from the county's own layer (SC_LAYERS), or None."""
    from .parcel_cache import PARCEL_LAYERS
    c = str(county or "").strip().title()
    spec = PARCEL_LAYERS.get(c)
    fm = SC_LAYERS.get(c)
    if not spec or not fm or not str(pin or "").strip():
        return None
    fields = [f for f in (fm.get("book"), fm.get("page"), fm.get("date"), fm.get("combined")) if f]
    raw = str(pin).strip()
    k = re.sub(r"[^0-9A-Za-z]", "", raw)
    vals = ",".join("'" + v.replace("'", "") + "'" for v in dict.fromkeys([raw, k]))
    for idf in spec.get("id_fields") or []:
        q = {"where": f"{idf} IN ({vals})", "outFields": ",".join(fields + [idf]), "returnGeometry": "false",
             "f": "json"}
        a = _get_feature(spec["url"], q, client)
        if a is None:
            return None                    # the layer did not answer: stop, do not try more forms
        if a:
            out = parse_sc(c, a)
            return {"source": f"{c.lower()}_parcel_layer", "parno": a.get(idf), **out,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")} if out else None
    return None


def _get_feature(url: str, q: dict, client: Any) -> Optional[dict]:
    """The first feature's attributes ({} when none), or None when the layer did not answer."""
    from .rod import nc_polite
    try:
        with _lock:
            wait = MIN_GAP_S - (time.monotonic() - _last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                if client is None:
                    import requests
                    client = requests
                r = client.get(url, params=q, headers=nc_polite.HEADERS, timeout=45)
            finally:
                _last[0] = time.monotonic()
        if int(r.status_code) != 200:
            return None
        j = r.json()
        if "error" in j:
            return None
        feats = j.get("features") or []
        return (feats[0].get("attributes") or {}) if feats else {}
    except Exception:  # noqa: BLE001
        return None


def fetch(state: str, county: str, pin: str, client: Any = None) -> Optional[dict]:
    """raw['county_deed_ref'] for one parcel, NC or SC, or None."""
    st = str(state or "").upper()
    return fetch_nc(county, pin, client) if st == "NC" else fetch_sc(county, pin, client) if st == "SC" else None


def fetch_nc(county: str, pin: str, client: Any = None) -> Optional[dict]:
    """raw['county_deed_ref'] for one NC parcel from NC OneMap, or None (not found, no deed reference,
    or the layer did not answer). Raises nothing."""
    from .quiet_title.adapters.nc_onemap import canonical_county, parcel_where
    from .rod import nc_polite
    cname = canonical_county(county)
    if not cname or not str(pin or "").strip():
        return None
    q = {"where": parcel_where(cname, str(pin)), "outFields": FIELDS, "returnGeometry": "false", "f": "json"}
    try:
        with _lock:
            wait = MIN_GAP_S - (time.monotonic() - _last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                if client is None:
                    import requests
                    client = requests
                r = client.get(ONEMAP_QUERY, params=q, headers=nc_polite.HEADERS, timeout=45)
            finally:
                _last[0] = time.monotonic()
        if int(r.status_code) != 200:
            return None
        feats = [f.get("attributes") or {} for f in (r.json().get("features") or [])]
    except Exception:  # noqa: BLE001 - one parcel never stops a pass
        return None
    out = parse_feature(str(pin), feats)
    if not out or not (out.get("book") or out.get("date")):
        return None
    return {"source": "nc_onemap", **out, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
