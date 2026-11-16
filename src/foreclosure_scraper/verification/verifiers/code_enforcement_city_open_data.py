"""code_enforcement, enrichment_code_enforcement.py's own CITY_ENDPOINTS / SEVERE_ENDPOINTS
family (source == "city_open_data"): does the listing's city still carry a matching, open case
on the exact same per-city ArcGIS layer that producer itself queries?

WHY THIS EXISTS (2026-11-16 gap-matrix sweep of code_enforcement's `built-not-verified` cells).
code_enforcement had exactly one registered verifier before this one
(code_enforcement_henderson.py), scoped to a single county's OVT dashboard by a hardcoded
state+county+source-string check. Every row written by any OTHER real producer -- built, ran,
a genuine case on the board -- fell through to `built-not-verified` for want of ANY verifier
whose applies() recognized it: the exact shape that classification's own docstring names ("a
differently-shaped producer of the same raw key the verifier never learned about"). This
module closes the single largest slice of that gap: enrichment_code_enforcement.py's
CITY_ENDPOINTS (Charlotte + the 13 Wake-area cities it loops in) and SEVERE_ENDPOINTS
("orders to demolish"), both stamped with the one shared `source` tag "city_open_data".
Live-sampled 2026-11-16 against the real board: ~9,000+ of the ~13,000-row gap, spanning
Mecklenburg (the majority), Wake, and a handful of rows whose address resolved into a
NEIGHBORING county (Harnett, Johnston, Chatham, Franklin, Forsyth -- Fuquay Varina, Garner and
the other Wake-area cities this producer covers sit near county lines) plus a few rows whose
county never resolved (UNKNOWN).

THE SOURCE: the exact per-city ArcGIS MapServer/0 layers CITY_ENDPOINTS/SEVERE_ENDPOINTS
already name (Charlotte's HNS/CodeEnforcementNewAndOpenCases + HNS/CodeEnforcementOrderstoDemolish;
Wake County's codecases_90days_test, covering the 13 cities the enricher loops in for it).
Anonymous, no login, no CAPTCHA -- the enricher's own module docstring already live-verified
both, 2026-10-28.

WHICH ROWS (applies): raw['code_enforcement'] is a dict whose 'source' is "city_open_data" --
this producer's own stamp -- claiming an open case, and the row's own `city` is still a key of
CITY_ENDPOINTS or SEVERE_ENDPOINTS today (the producer keys off `li.city`, not county, so this
block can carry any city either dict names; a city the enricher has since dropped from both is
left alone -- `verify()`'s own "no_endpoint_for_city" unconfirmed, never refuted).

MATCHING mirrors the producer's OWN `_fetch_violations_for_listing()` exactly -- the identical
`_street_keywords()` keyword, the identical per-`addr_fields` LIKE query, the identical
"`None` = could not be asked, `[]` = asked and empty" meaning -- and reuses its
`_proximity_filter()` (the same 250ft haversine gate), `_pick()` and `_is_closed_status()`
verbatim (pure functions, imported straight from the module, no I/O of their own). Only the
HTTP transport differs: the enricher's own call is a raw httpx-style `c.get(url, params=...)`
against the production pipeline's `http_client.client()`, which the verification sweep's
`Fetcher`/`ReplayFetcher` (get_text/get_json only, no bare `.get()`) cannot serve, so this
module builds the identical query URL (`urlencode`, byte-for-byte the same params dict) and
fetches it with `client.get_json()` instead -- the same adaptation
code_enforcement_adl.py's `_arcgis_layer.py` helper already makes for the Henderson/ADL family.
The decision logic -- what counts as a match, what counts as closed -- is never re-derived.

VERDICTS: confirmed (re-query still finds at least one open, address-matching case), stale
(every previously-matching case is now closed), refuted (the city answered and this address has
none, on every endpoint the city has), unconfirmed (no endpoint could be asked, the row's city
is no longer in either dict, or the row has no street address to query by).

TTL 14 days (the same cadence code_enforcement_henderson.py already uses for this identical
signal).

EVIDENCE: the city, which endpoint kind(s) were checked, the claimed open-violation count, and
per matched case (newest-shaped list, at most 8) violation/status/date/open -- never a field
beyond what CITY_ENDPOINTS/SEVERE_ENDPOINTS themselves request (neither service's own schema
carries an owner, inspector, phone or e-mail column to begin with).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
CE_SOURCE = "city_open_data"
SOURCE = "enrichment_code_enforcement.py CITY_ENDPOINTS/SEVERE_ENDPOINTS (per-city ArcGIS)"
GOVERNS = (f"code_enforcement:{CE_SOURCE}",)
MAX_CASES_IN_EVIDENCE = 8

_NAME = __name__.rsplit(".", 1)[-1]


def _enf():
    """enrichment_code_enforcement.py, imported on first use (the registry imports every
    verifier; the full enrichment stack must not load in just to answer applies())."""
    from ... import enrichment_code_enforcement as m
    return m


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) and ce.get("source") == CE_SOURCE else None


def _city(row: dict, ce: dict) -> str:
    raw_city = row.get("city") or ce.get("city") or ""
    return str(raw_city).strip().title()


def applies(row: dict) -> bool:
    ce = _block(row)
    if not ce or not ce.get("has_open"):
        return False
    m = _enf()
    city = _city(row, ce)
    return bool(city) and (city in m.CITY_ENDPOINTS or city in m.SEVERE_ENDPOINTS)


class _Row:
    """Stands in for the models.Listing _fetch_violations_for_listing()/_proximity_filter()
    read (.street_address/.latitude/.longitude only) -- the sweep hands verify() a plain board
    dict, never a real Listing, and building one would need many more fields than a row may
    carry."""

    def __init__(self, row: dict) -> None:
        self.street_address = row.get("street_address")
        self.latitude = row.get("latitude")
        self.longitude = row.get("longitude")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def _query_one(client, cfg: dict, addr_field: str, keyword: str) -> Optional[list[dict]]:
    """One ArcGIS query attempt: the identical params dict
    `_fetch_violations_for_listing()` builds (where=UPPER(...) LIKE keyword, outFields=*,
    resultRecordCount=10), fetched with the sweep's `client.get_json()` instead of that
    function's own raw-httpx call (see the module docstring's MATCHING section). `None` means
    unreachable/malformed, mirroring that function's own per-attempt meaning exactly."""
    params = {"where": f"UPPER({addr_field}) LIKE '%{keyword.upper()}%'", "outFields": "*",
             "returnGeometry": "true", "outSR": "4326", "resultRecordCount": "10", "f": "json"}
    url = cfg["url"].rstrip("/") + "/query?" + urlencode(params)
    try:
        data = await client.get_json(url)
    except Exception:  # noqa: BLE001 - unreachable this attempt, the caller tries the next field
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    return data.get("features", [])


async def _fetch(client, li: "_Row", cfg: dict) -> Optional[list[dict]]:
    """Mirrors `_fetch_violations_for_listing()` exactly: the same `_street_keywords()` keyword,
    the same per-`addr_fields` loop, the same `None` (could not be asked) vs `[]` (asked, empty)
    meaning -- only the transport (`_query_one`) differs."""
    m = _enf()
    if not li.street_address:
        return None
    keyword = m._street_keywords(li.street_address)
    if not keyword:
        return None
    answered = False
    for addr_field in cfg["addr_fields"]:
        feats = await _query_one(client, cfg, addr_field, keyword)
        if feats is None:
            continue
        answered = True
        if feats:
            return feats
    return [] if answered else None


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    m = _enf()
    ce = _block(row) or {}
    city = _city(row, ce)
    claimed_types = [str(t) for t in ce.get("violation_types") or [] if t][:MAX_CASES_IN_EVIDENCE]
    ev: dict[str, Any] = {"city": city or None,
                          "claimed_open_violations": int(ce.get("open_violations") or 0),
                          "claimed_types": claimed_types}

    cfgs = [("regular", m.CITY_ENDPOINTS.get(city)), ("severe", m.SEVERE_ENDPOINTS.get(city))]
    cfgs = [(kind, c) for kind, c in cfgs if c]
    if not cfgs:
        ev["reason"] = "no_endpoint_for_city"
        return _res("unconfirmed", ev)
    if not row.get("street_address"):
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    li = _Row(row)
    ev["endpoints_checked"] = [kind for kind, _ in cfgs]
    answered_any = False
    found: list[tuple[dict, dict]] = []     # (feature, its own cfg -- field names may differ)
    for _kind, cfg in cfgs:
        feats = await _fetch(client, li, cfg)
        if feats is None:
            continue
        answered_any = True
        for f in (m._proximity_filter(li, feats) if feats else []):
            found.append((f, cfg))

    if not answered_any:
        ev["reason"] = "endpoint_unreachable"
        return _res("unconfirmed", ev)
    if not found:
        ev["reason"] = "no_case_at_address"
        return _res("refuted", ev)

    cases = []
    for f, cfg in found[:MAX_CASES_IN_EVIDENCE]:
        attrs = f.get("attributes", {}) or {}
        v = m._pick(attrs, cfg["violation_fields"]) or "unknown"
        s = m._pick(attrs, cfg["status_fields"]) or "unknown"
        d = m._pick(attrs, cfg["date_fields"])
        cases.append({"violation": v[:200], "status": s,
                     "date": str(d)[:10] if d else None,
                     "open": not m._is_closed_status(s)})
    ev["cases"] = cases
    ev["cases_matched"] = len(found)
    if any(c["open"] for c in cases):
        return _res("confirmed", ev)
    ev["reason"] = "all_cases_closed"
    return _res("stale", ev)
