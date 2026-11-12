"""County-published owner PHONE + mailing enrichment — parcel-keyed, config-driven.

Some NC counties publish the taxpayer/owner contact record that sits behind their permitting
and tax systems on an open ArcGIS REST table. Buncombe's Accela ParcelOwner table is the big
one: 135,079 owner rows, 73,965 of them carrying a phone, keyed on ParcelNumber (live-verified
2026-08-03). Our board already resolves a parcel_id for most Buncombe leads, so this is a
straight parcel join — no name guessing, no skip-trace vendor, no cost.

Why this beats the voter-file lane for absentee owners: the NCSBE file only holds registered
INDIVIDUALS at their residence, so LLC/trust/estate owners and out-of-state absentees never
match. The county owner record is the taxpayer of record for the parcel — exactly the party a
foreclosure letter goes to — and it carries LLCs, trusts and out-of-state mailing addresses.

COMPLIANCE, non-negotiable: these numbers are COUNTY-PUBLISHED, not consented. Every record is
tagged source=<county slug>, county_published=True, consent='none', needs_dnc_scrub=True so the
outreach layer can scrub before anything is dialed (National DNC re-scrub >=31 days, 8am-9pm
local, TCPA wireless rules via enrichment_line_type). Nothing here dials, texts, or queues an
outbound anything — it is enrichment only.

PRIVACY: every request enumerates outFields explicitly. `outFields=*` is FORBIDDEN in this
module — Lincoln County's taxpayer table (Server_Tables/MapServer/10) exposes TCSSN1/TCSSN2 on
the public layer, and a wildcard would pull SSNs into our board. `_out_fields()` hard-rejects
any field name that looks like an SSN/driver's-licence identifier even if a config asks for it.

NON-CLOBBER: an existing raw['owner_phone'] (e.g. an NCSBE voter name+address hit) is never
overwritten. A county number for a lead that already has one is appended to
owner_phone['alternates'] with full provenance, so the operator sees both lanes.

Adding a county is a CONFIG entry, not a new module — see COUNTY_PHONE_SOURCES below.
Gate off with FORECLOSURE_COUNTY_PHONE=0.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "county_phone"
_CACHE_TTL_DAYS = float(os.environ.get("FORECLOSURE_COUNTY_PHONE_TTL_DAYS", "30"))

# Field names we refuse to request, whatever a config says. Belt-and-braces against the
# Lincoln TCSSN1/TCSSN2 exposure (and any future layer that leaks the same class of field).
_FORBIDDEN_FIELD = re.compile(r"ssn|social_?sec|drivers?_?lic|dl_?num|tcdlc", re.I)


# --------------------------------------------------------------------------------------
# Per-county config. Two fetch modes:
#   mode="bulk"      one paginated pull of the whole table, cached on disk, keyed on parcel.
#                    Right when the table is parcel-keyed and the county is a big share of
#                    the board (Buncombe: 5,902 leads).
#   mode="targeted"  query only the parcel ids actually on the board, chunked IN clauses.
#                    Right when the phone table is keyed on something else and needs a
#                    bridge hop, or when the table dwarfs our lead count (Lincoln: a
#                    291,480-row taxpayer table for 335 leads).
#
# `bridge` (targeted only) maps board parcel -> the phone table's key via a second layer.
# `phone_fields` are whole-number string columns; `phone_parts` are split columns
# (area/exchange/line) that get zero-padded and concatenated.
# --------------------------------------------------------------------------------------
COUNTY_PHONE_SOURCES: dict[str, dict] = {
    "NC:Buncombe": {
        "source": "buncombe_accela",
        "mode": "bulk",
        "url": "https://gis.buncombenc.gov/arcgis/rest/services/Accela/MapServer/6",
        # Layer has NO objectIdField -> ArcGIS paging REQUIRES orderByFields or every page
        # returns the same rows. ID is the table's own integer sequence.
        "order_by": "ID",
        "page_size": 2000,          # layer maxRecordCount
        "where": "Phone IS NOT NULL AND Phone <> ''",
        "key_field": "ParcelNumber",
        "phone_fields": ["Phone", "Phone2"],
        "name_field": "OwnerFullName",
        "mail_fields": ["MailAddress1", "MailAddress2", "MailCity", "MailState", "MailZip"],
        "status_field": "OwnerStatus",
        "active_status": ("A",),
        "updated_field": "LastUpdateDate",
        "out_fields": [
            "ID", "ParcelNumber", "OwnerStatus", "OwnerFullName", "Phone", "Phone2",
            "MailAddress1", "MailAddress2", "MailCity", "MailState", "MailZip",
            "LastUpdateDate",
        ],
    },
    "NC:Lincoln": {
        "source": "lincoln_taxpayer",
        "mode": "targeted",
        "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_Tables/MapServer/10",
        "key_field": "TCTXID",
        # Phone is split across three integer columns: area code / exchange / line number.
        # TCPHON alone maxes at 9999 (live-checked) — it is the 4-digit line, not the number.
        "phone_parts": [
            [("TCACDE", 3), ("TCPEXT", 3), ("TCPHON", 4)],
            [("TCACD2", 3), ("TCPEX2", 3), ("TCPHN2", 4)],
        ],
        "name_field": "TCNAM1",
        "mail_fields": ["TCADR1", "TCADR2", "TCCITY", "TCSTA", "TCZIPA"],
        # EXPLICIT and SSN-free. TCSSN1/TCSSN2 and TCDLC1/TCDLC2 live on this layer and are
        # deliberately absent; never replace this list with "*".
        "out_fields": [
            "TCTXID", "TCNAM1", "TCADR1", "TCADR2", "TCCITY", "TCSTA", "TCZIPA",
            "TCACDE", "TCPEXT", "TCPHON", "TCACD2", "TCPEX2", "TCPHN2",
        ],
        "bridge": {
            "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_Tables/MapServer/1",
            "parcel_field": "PIN",
            "link_fields": ["OWNERID", "COOWNERID"],
            "out_fields": ["PIN", "OWNERID", "COOWNERID"],
        },
        "match_label": "parcel_id+ownerid",
    },
}


# --------------------------------------------------------------------------------------
# normalization helpers
# --------------------------------------------------------------------------------------
def _pkey(value: Any) -> str:
    """Normalized parcel/owner key: uppercase alphanumerics only."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _key_variants(value: Any) -> list[str]:
    """Ordered match candidates for a board parcel_id.

    Buncombe writes the parcel two ways on our board — the bare 10-digit PIN
    ('9744480675') and the Accela 15-digit card form ('971370653100000' = PIN + a 5-digit
    card suffix). Try the exact key first, then the 10-digit base, then the padded card
    form, so either direction of that mismatch resolves.
    """
    k = _pkey(value)
    if not k or len(k) < 6:
        return []
    out = [k]
    if len(k) == 15 and k.isdigit() and k[10:] == "00000":
        out.append(k[:10])
    elif len(k) == 10 and k.isdigit():
        out.append(k + "00000")
    return out


def _clean_digits(value: Any) -> str:
    d = re.sub(r"\D", "", str(value or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


def _valid_nanp(digits: str) -> bool:
    """True for a plausible dialable NANP number. Rejects the placeholder junk these
    county tables carry (999-999-9999, 000-000-0000, repdigits, N11 codes)."""
    if len(digits) != 10 or len(set(digits)) == 1:
        return False
    npa, nxx = digits[:3], digits[3:6]
    if npa[0] < "2" or nxx[0] < "2":
        return False
    if npa in ("999", "911") or npa[1:] == "11" or nxx[1:] == "11":
        return False
    if nxx == "555" and digits[6:8] == "01":      # 555-01xx = fictional range
        return False
    return True


def _fmt(digits: str) -> str:
    return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"


def _join(attrs: dict, fields: Iterable[str]) -> str:
    parts = []
    for f in fields:
        v = attrs.get(f)
        if v in (None, "", " "):
            continue
        s = str(v).strip()
        if s and s.lower() != "none":
            parts.append(s)
    return " ".join(parts).strip()


def _out_fields(spec: dict, key: str = "out_fields") -> str:
    """Comma-joined outFields, with a hard SSN/DL guard. Never returns '*'."""
    fields = [f for f in (spec.get(key) or []) if f and f != "*"]
    safe = [f for f in fields if not _FORBIDDEN_FIELD.search(f)]
    dropped = sorted(set(fields) - set(safe))
    if dropped:
        log.warning("county_phone.blocked_sensitive_fields", fields=dropped)
    if not safe:
        raise ValueError("county_phone: outFields must be enumerated explicitly (no '*')")
    return ",".join(safe)


def _phones(attrs: dict, spec: dict) -> list[str]:
    """All valid 10-digit numbers on a county record, primary first, de-duped."""
    out: list[str] = []

    def _add(d: str) -> None:
        if _valid_nanp(d) and d not in out:
            out.append(d)

    for f in spec.get("phone_fields") or []:
        _add(_clean_digits(attrs.get(f)))
    for group in spec.get("phone_parts") or []:
        buf = ""
        for field, width in group:
            v = attrs.get(field)
            try:
                n = int(str(v).strip())
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                buf = ""
                break
            s = str(n)
            if len(s) > width:
                buf = ""
                break
            buf += s.zfill(width)
        if buf:
            _add(buf)
    return out


def _as_of(attrs: dict, spec: dict) -> Optional[str]:
    """County record's own last-update date (ArcGIS epoch-ms) as ISO date."""
    f = spec.get("updated_field")
    if not f:
        return None
    v = attrs.get(f)
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


# --------------------------------------------------------------------------------------
# ArcGIS fetch
# --------------------------------------------------------------------------------------
async def _query(http: httpx.AsyncClient, base: str, params: dict) -> dict:
    """POST an ArcGIS /query and return the parsed payload.

    POST, not GET: the targeted lane builds `... IN ('a','b',...)` WHERE clauses that blow
    past the servers' URL length limit (live 2026-08-03: a 120-key GET to Lincoln came back
    as non-JSON garbage; the same body as POST returns clean features).

    ArcGIS reports failures as HTTP 200 with an {"error": ...} body. Returning that as if it
    were an empty result set is the silent-death pattern that has bitten other sources here,
    so it is raised instead of swallowed.
    """
    url = base.rstrip("/") + "/query"
    body = {"returnGeometry": "false", "f": "json", **params}
    r = await http.post(url, data=body)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError(f"arcgis non-JSON response from {url}") from exc
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        raise RuntimeError(f"arcgis error {err.get('code')}: {err.get('message')}")
    return data


async def _fetch_bulk(http: httpx.AsyncClient, spec: dict) -> list[dict]:
    """Page the whole table. The layer has no OID, so orderByFields is mandatory —
    without it ArcGIS ignores resultOffset and every page repeats page 1. Stop when the
    server says exceededTransferLimit is false (or a short/empty page comes back)."""
    page = int(spec.get("page_size", 1000))
    order = spec.get("order_by") or spec["key_field"]
    fields = _out_fields(spec)
    rows: list[dict] = []
    offset = 0
    while True:
        data = await _query(http, spec["url"], {
            "where": spec.get("where") or "1=1",
            "outFields": fields,
            "orderByFields": order,
            "resultOffset": str(offset),
            "resultRecordCount": str(page),
        })
        feats = data.get("features") or []
        rows.extend(f.get("attributes", {}) or {} for f in feats)
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if offset > 2_000_000:                      # runaway guard
            log.warning("county_phone.paging_guard", source=spec["source"], rows=len(rows))
            break
    return rows


async def _fetch_by_keys(http: httpx.AsyncClient, base: str, field: str, fields: str,
                         keys: list[str], chunk: int = 100, page: int = 1000) -> list[dict]:
    """Targeted IN-clause fetch, chunked and paged.

    orderByFields is passed on every request: these tables have no OID, and ArcGIS rejects
    any request carrying resultOffset/resultRecordCount without an explicit sort
    ("Pagination request requires either orderBy field or the layer/table needs to have OID
    Field", live-confirmed on Lincoln 2026-08-03).
    """
    rows: list[dict] = []
    for i in range(0, len(keys), chunk):
        block = [k.replace("'", "''") for k in keys[i:i + chunk]]
        where = f"{field} IN (" + ",".join(f"'{k}'" for k in block) + ")"
        offset = 0
        while True:
            try:
                data = await _query(http, base, {
                    "where": where, "outFields": fields, "orderByFields": field,
                    "resultOffset": str(offset), "resultRecordCount": str(page),
                })
            except Exception as exc:                                 # noqa: BLE001
                log.warning("county_phone.chunk_failed", base=base, offset=i, error=str(exc))
                break
            feats = data.get("features") or []
            rows.extend(f.get("attributes", {}) or {} for f in feats)
            if not feats or not data.get("exceededTransferLimit"):
                break
            offset += len(feats)
    return rows


# --------------------------------------------------------------------------------------
# index build (+ disk cache for bulk sources)
# --------------------------------------------------------------------------------------
def _index_rows(rows: list[dict], spec: dict) -> dict[str, dict]:
    """parcel key -> compact county contact record.

    Exact keys win. A 10-digit base key is only indexed when it is UNAMBIGUOUS across the
    card suffixes (one distinct phone), so a base-form parcel_id never gets some other
    card's owner — same discipline as the voter-file 'unique in county' rule.
    """
    active = spec.get("active_status")
    status_f = spec.get("status_field")
    exact: dict[str, dict] = {}
    base_seen: dict[str, set[str]] = {}
    base_rec: dict[str, dict] = {}
    for a in rows:
        if status_f and active and str(a.get(status_f) or "").strip().upper() not in active:
            continue
        key = _pkey(a.get(spec["key_field"]))
        if not key:
            continue
        phones = _phones(a, spec)
        if not phones:
            continue
        rec = {
            "phones": phones,
            "owner": (str(a.get(spec.get("name_field") or "") or "").strip() or None),
            "mailing": _join(a, spec.get("mail_fields") or []) or None,
            "as_of": _as_of(a, spec),
        }
        exact.setdefault(key, rec)
        if len(key) == 15 and key.isdigit():
            base = key[:10]
            base_seen.setdefault(base, set()).add(phones[0])
            base_rec.setdefault(base, rec)
    idx = dict(exact)
    for base, phs in base_seen.items():
        if len(phs) == 1 and base not in idx:
            idx[base] = {**base_rec[base], "_base_match": True}
    return idx


def _cache_path(source: str) -> Path:
    return _CACHE_DIR / f"{source}.json"


def _load_cache(source: str) -> Optional[dict]:
    p = _cache_path(source)
    if not p.exists():
        return None
    try:
        if (time.time() - p.stat().st_mtime) > _CACHE_TTL_DAYS * 86400:
            return None
        return json.loads(p.read_text())
    except Exception:                                                # noqa: BLE001
        return None


def _save_cache(source: str, index: dict, fetched: str) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(source).write_text(json.dumps({"fetched": fetched, "index": index}))
    except Exception:                                                # noqa: BLE001
        log.warning("county_phone.cache_write_failed", source=source)


# --------------------------------------------------------------------------------------
# attach
# --------------------------------------------------------------------------------------
def _county_key(li: Listing) -> str:
    cty = (li.county or "").strip().title()
    cty = {"Mcdowell": "McDowell", "Mccormick": "McCormick"}.get(cty, cty)
    return f"{li.state}:{cty}"


def _name_overlap(a: Optional[str], b: Optional[str]) -> bool:
    """Loose token overlap so we can *report* whether the county owner and the listing
    owner look like the same party. Informational only — the parcel is the join."""
    ta = {t for t in re.split(r"[^A-Za-z]+", (a or "").upper()) if len(t) > 2}
    tb = {t for t in re.split(r"[^A-Za-z]+", (b or "").upper()) if len(t) > 2}
    return bool(ta and tb and (ta & tb))


def _record(rec: dict, spec: dict, li: Listing, fetched: str) -> dict:
    """The raw['owner_phone'] payload — same shape enrichment_line_type and the dashboard
    already consume (phone / source / line_type / needs_dnc_scrub / match), plus the
    county-published compliance markers and provenance."""
    phones = rec["phones"]
    return {
        "phone": _fmt(phones[0]),
        "source": spec["source"],
        "line_type": "unknown",                 # enrichment_line_type fills this via LERG
        "needs_dnc_scrub": True,
        "match": ("parcel_id_base" if rec.get("_base_match")
                  else spec.get("match_label", "parcel_id")),
        "confidence": "medium" if rec.get("_base_match") else "high",
        # --- DNC/TCPA hygiene: published by the county, NOT consented by the owner. ---
        "county_published": True,
        "consent": "none",
        "fetched": fetched,
        "as_of": rec.get("as_of"),
        "alt_phones": [_fmt(p) for p in phones[1:]],
        "county_owner": rec.get("owner"),
        "county_mailing": rec.get("mailing"),
        "owner_name_match": _name_overlap(rec.get("owner"), li.owner_name),
    }


def _attach(li: Listing, payload: dict, counts: dict) -> None:
    """Fill an empty owner_phone; otherwise record as an alternate. Never clobbers a
    voter-file (or any prior) match."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    existing = li.raw.get("owner_phone")
    if not isinstance(existing, dict) or not existing.get("phone"):
        li.raw["owner_phone"] = payload
        counts["filled"] += 1
        return
    if _clean_digits(existing.get("phone")) == _clean_digits(payload["phone"]):
        counts["confirmed_existing"] += 1
        existing.setdefault("corroborated_by", []).append(payload["source"])
        return
    alts = existing.setdefault("alternates", [])
    if any(_clean_digits(a.get("phone")) == _clean_digits(payload["phone"]) for a in alts):
        return
    alts.append({k: payload[k] for k in
                 ("phone", "source", "match", "confidence", "county_published",
                  "consent", "needs_dnc_scrub", "fetched", "county_owner",
                  "county_mailing")})
    counts["alternates"] += 1


# --------------------------------------------------------------------------------------
# per-source runners
# --------------------------------------------------------------------------------------
async def _index_bulk(http: httpx.AsyncClient, spec: dict) -> tuple[dict, str]:
    cached = _load_cache(spec["source"])
    if cached and cached.get("index"):
        return cached["index"], cached.get("fetched") or date.today().isoformat()
    rows = await _fetch_bulk(http, spec)
    idx = _index_rows(rows, spec)
    fetched = date.today().isoformat()
    log.info("county_phone.fetched", source=spec["source"], rows=len(rows), keys=len(idx))
    _save_cache(spec["source"], idx, fetched)
    return idx, fetched


async def _index_targeted(http: httpx.AsyncClient, spec: dict,
                          wanted: list[str]) -> tuple[dict, str]:
    """Board-scoped fetch. With a `bridge`, hop board-parcel -> link id -> phone table,
    then re-key the result back onto the board's parcel keys."""
    fetched = date.today().isoformat()
    bridge = spec.get("bridge")
    if not bridge:
        rows = await _fetch_by_keys(http, spec["url"], spec["key_field"],
                                    _out_fields(spec), wanted)
        return _index_rows(rows, spec), fetched

    brows = await _fetch_by_keys(http, bridge["url"], bridge["parcel_field"],
                                 _out_fields(bridge), wanted)
    # One parcel can carry several link ids (owner + co-owner, and the bridge layer may hold
    # more than one row per PIN), so keep every candidate in priority order and take the
    # first that actually resolves to a phone record.
    parcel_to_links: dict[str, list[str]] = {}
    for a in brows:
        pk = _pkey(a.get(bridge["parcel_field"]))
        if not pk:
            continue
        seen = parcel_to_links.setdefault(pk, [])
        for f in bridge["link_fields"]:
            lv = _pkey(a.get(f))
            if lv and lv not in seen:
                seen.append(lv)
    links = sorted({lv for vals in parcel_to_links.values() for lv in vals})
    if not links:
        return {}, fetched
    rows = await _fetch_by_keys(http, spec["url"], spec["key_field"], _out_fields(spec), links)
    by_link = _index_rows(rows, spec)
    idx: dict[str, dict] = {}
    for pk, vals in parcel_to_links.items():
        for lv in vals:
            if lv in by_link:
                idx[pk] = by_link[lv]
                break
    log.info("county_phone.fetched", source=spec["source"], rows=len(rows), keys=len(idx))
    return idx, fetched


# --------------------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------------------
async def enrich_county_phone(listings: list[Listing]) -> dict:
    """Attach county-published owner phone + mailing to every board lead whose parcel_id
    matches a configured county contact table."""
    if os.environ.get("FORECLOSURE_COUNTY_PHONE", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_COUNTY_PHONE=0)"}

    buckets: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.parcel_id:
            continue
        key = _county_key(li)
        if key in COUNTY_PHONE_SOURCES:
            buckets.setdefault(key, []).append(li)
    if not buckets:
        return {"targets": 0}

    stats: dict[str, Any] = {"targets": 0, "filled": 0, "alternates": 0,
                             "confirmed_existing": 0, "by_source": {}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0),
                                 headers={"User-Agent": "foreclosure-scraper/1.0"}) as http:
        for ckey, leads in buckets.items():
            spec = COUNTY_PHONE_SOURCES[ckey]
            counts = {"targets": len(leads), "matched": 0, "filled": 0,
                      "alternates": 0, "confirmed_existing": 0, "base_match": 0}
            try:
                if spec.get("mode") == "targeted":
                    wanted = sorted({v for li in leads for v in _key_variants(li.parcel_id)})
                    idx, fetched = await _index_targeted(http, spec, wanted)
                else:
                    idx, fetched = await _index_bulk(http, spec)
            except Exception as exc:                                 # noqa: BLE001
                log.warning("county_phone.source_failed", source=spec["source"], error=str(exc))
                stats["by_source"][spec["source"]] = {**counts, "error": str(exc)}
                continue
            counts["index_keys"] = len(idx)
            for li in leads:
                rec = None
                for cand in _key_variants(li.parcel_id):
                    rec = idx.get(cand)
                    if rec:
                        break
                if not rec:
                    continue
                counts["matched"] += 1
                if rec.get("_base_match"):
                    counts["base_match"] += 1
                _attach(li, _record(rec, spec, li, fetched), counts)
            stats["by_source"][spec["source"]] = counts
            for k in ("targets", "filled", "alternates", "confirmed_existing"):
                stats[k] += counts[k]
    log.info("county_phone.done", **{k: v for k, v in stats.items() if k != "by_source"})
    return stats


def enrich_county_phone_sync(listings: list[Listing]) -> dict:
    """Blocking wrapper for the non-async board scripts."""
    return asyncio.run(enrich_county_phone(listings))
