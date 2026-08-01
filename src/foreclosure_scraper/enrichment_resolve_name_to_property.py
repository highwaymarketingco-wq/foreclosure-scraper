"""NAME -> PROPERTY -> EQUITY -> CONTACT resolver (the backbone).

Turns NAME-INDEXED leads — SC Public Index civil/criminal, SC divorce, NC court
ingest, probate notices, future inmate rosters — into real PROPERTY leads. Many
such leads carry only an owner/party name (owner_name or defendant) with NO
street_address, NO parcel_id, NO value. Outreach and grading are impossible
until that name is tied to a parcel.

WHAT IT DOES (per qualifying lead, free / pure-HTTP / no auth / no login):
  1. Resolve the lead's county GIS owner-name layer: a PINNED county-owned SC
     layer (SC_OWNER_LAYERS below) first, else the audited NC FeatureServers in
     enrichment_arcgis. SCDOT SC_Parcels is now token-secured — see the wall
     note on SC_OWNER_LAYERS.
  2. Run an owner-name LIKE search in BOTH name orderings and keep only a STRICT
     match (name_normalize.match_owner: exact normalized token set, or surname +
     first name in their GIS positions). Several parcels for one owner are kept
     and flagged as ambiguous — never resolved to a guess.
  3. Backfill parcel_id / street_address / market_value / living_sqft (+ owner_name,
     year_built, acreage) onto the Listing, and record provenance in
     raw['resolved_from_name'] = {county, strategy, confidence, matched_owner}.

This is ADDITIVE and self-contained. It REUSES the investor-grade conservative
matching engine already proven in enrichment_address_owner_v2 (_parse_individual,
_is_company, _company_tokens, _split_joint, _like_patterns, _query_owner,
_best_unique) and the value/sqft backfill in enrichment_gis_attrs.apply_gis_attrs.
It does NOT modify those modules.

WHY A SEPARATE MODULE (vs enrich_addresses_from_owner_v2):
  * v2 only fires on li.defendant; the largest name-indexed cohort
    (sc_public_index, sc_fccms divorce, hud owner-name) lives in owner_name OR
    defendant. This resolver handles BOTH.
  * v2's owner-field detection reads the layer's `fields` metadata. Several SCDOT
    county layers (e.g. Cherokee) return EMPTY metadata yet expose cryptic owner
    columns ('SHEET1__Na' = surname-first owner, 'SHEET1___1' = situs street) on
    a real row. This resolver adds a sample-row field detector so those counties
    resolve instead of silently no-op'ing (no_owner_field).
  * v2 only backfills the address fields. This resolver also runs apply_gis_attrs
    so the matched parcel's VALUE + sqft land on first-class Listing fields that
    grading/equity read — so a resolved name immediately becomes a gradable lead.

MATCHING POLICY (tightened over v2 — this data drives outreach):
  * Individuals: EITHER the normalized token sets are equal, OR the surname sits
    in the GIS owner's surname position (token 0) and the first name in the
    first-name position (token 1). v2's "surname + >=1 given token appears
    anywhere" rule committed roughly one wrong person per three matches
    ('Michael Duane Crowe' -> 'CROWE KEVIN MICHAEL').
  * Companies: exact normalized token-set equality after entity suffixes
    (LLC/INC/CORP/TRUST/...) and connectives are stripped.
  * Multiple matching parcels: kept as candidates on the lead and flagged
    ambiguous. Nothing is committed and no address is invented.

GATING / COST (it hits county GIS per lead):
  * FORECLOSURE_NAME_RESOLVE (default "1"; set "0" to disable).
  * FORECLOSURE_NAME_RESOLVE_MAX  per-run cap on leads attempted (default 400).
  * FORECLOSURE_NAME_RESOLVE_BUDGET_S wall-clock budget seconds (default 900).
  * Scoped to Western-NC + Upstate-SC core counties only.
  * Idempotent: a lead already attempted (raw['resolved_from_name']['queried'])
    is skipped on re-runs unless FORECLOSURE_NAME_RESOLVE_FORCE=1.

WIRING (orchestrator owns the call; see main.py): runs AFTER the court/divorce
enrichers (so the name-indexed leads exist) and BEFORE the calc/grade/equity pass
(so the resolved parcel's value feeds them).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional

import httpx
import structlog

from .enrichment_address_backfill import _populate_from_attrs
from .enrichment_address_owner_v2 import (
    _endpoint_for,
    _inject_site_alias,
    _looks_like_mailing,
    _query_owner,
    _split_joint,
    _detect_owner_field_v2,
    _detect_site_field,
)
from .enrichment_gis_attrs import apply_gis_attrs
from .http_client import client
from .models import Listing
from .name_normalize import like_patterns, match_owner, middle_conflict

log = structlog.get_logger()


# Western-NC + Upstate-SC core (the only counties new-avenue work targets).
_CORE_NC = {
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford", "Polk",
    "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke", "Madison",
    "Haywood", "Yancey", "Caldwell",
}
_CORE_SC = {
    "Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee",
    "Laurens", "Union", "Greenwood", "Abbeville",
}

# ---------------------------------------------------------------------------
# SC per-county owner-name endpoints (WALL WORKAROUND, verified live 2026-07-31)
# ---------------------------------------------------------------------------
# WALL: the SCDOT SC_Parcels MapServer (enrichment_arcgis.SCDOT_BASE) — the only
# SC endpoint this resolver knew — is now TOKEN-SECURED. It answers HTTP 200 with
# {"error":{"code":499,"message":"Token Required"}} on every layer, and the
# service is no longer listed in the public GISMapping folder. That is a
# server-side permission change by SCDOT, not bot detection, and there is no
# compliant free path back in. Do not engineer around it.
#
# These five county-owned layers ARE free, public, and answer owner-name LIKE
# queries. Fields are PINNED, never auto-detected: the auto-detector picks
# Spartanburg 'StreetAddr' and Union 'Address_1' as the situs, but both of those
# are the owner MAILING street — committing them would write out-of-state
# mailing addresses as property addresses. `mail` lists the columns stripped
# before the standard writer runs so no mailing artifact can leak into
# street_address / city / zip.
SC_OWNER_LAYERS: dict[str, dict[str, Any]] = {
    "Spartanburg": {
        "url": "https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/Parcel_and_CAMA_Feb_1_2021/FeatureServer/0/query",
        "owner": "OwnerName", "situs": "PropertyLo", "parcel": "TAXPIN",
        "mail": ("StreetAddr", "City", "State", "Zip", "TaxpayerNa"),
    },
    "Pickens": {
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "owner": "NAME1", "situs": "LOCADD", "parcel": "PIN",
        "mail": ("ADD1", "CITY", "STATE", "ZIP", "NAME2"),
    },
    "Laurens": {
        # Owner is pinned to 'Owner'; the auto-detector picks 'Name1' instead.
        "url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5/query",
        "owner": "Owner", "situs": "Property_Address", "parcel": "TMS",
        "mail": ("Mailing_Address", "Mailing_City_State_ZIP"),
    },
    # Oconee + Union expose NO situs column — parcel id + centroid only. We never
    # invent a street for them; the parcel is still a real, actionable lead.
    "Oconee": {
        "url": "https://arcserver2.oconeesc.com/arcgis/rest/services/PARCELDATA_owner_Assr/MapServer/1/query",
        "owner": "current_owner", "situs": None, "parcel": "TMS_NUMBER",
        "mail": ("owner_street", "owner_citystate", "owner_zip"),
    },
    "Union": {
        "url": "https://services6.arcgis.com/xQgypOVdY84tFTiW/arcgis/rest/services/UNION_SC_PARCELS_WFL1/FeatureServer/2/query",
        "owner": "Name", "situs": None, "parcel": "ParcelID",
        "mail": ("Address_1", "Address_2", "Address_3"),
    },
}

# WALL: no free owner-name search exists for these two, so their leads are not
# targeted at all rather than burning budget on a guaranteed miss.
#   Anderson  — propertyviewer.andersoncountysc.org MapServer/5 is public but has
#               NO owner column at all (TAXOWNSTR holds tax-district codes like
#               '100'); ACPASS is login-walled.
#   Cherokee  — qPublic/Schneider only: parcel-keyed ASP.NET viewstate postback,
#               no address/owner GET surface.
SC_NO_FREE_OWNER_SEARCH = {"Anderson", "Cherokee"}

# Name-indexed lead surfaces we most want to resolve. A lead from one of these
# sources / listing_types is PRIORITIZED; others still qualify if name-only.
_PRIORITY_SOURCES = (
    "sc_public_index", "sc_fccms", "fccms", "ecourts", "ncnotices",
    "column_legal_notices", "courtlistener", "divorce", "probate", "inmate",
    "incarcer",
)
_PRIORITY_TYPES = {
    "divorce_notice", "probate_notice", "lis_pendens", "bankruptcy", "tax_lien",
}

# Env gating / budget.
_ENABLED = os.environ.get("FORECLOSURE_NAME_RESOLVE", "1") != "0"
_FORCE = bool(os.environ.get("FORECLOSURE_NAME_RESOLVE_FORCE"))
# 400 was never enough to reach past the first few sources; combined with the
# old stable priority sort it meant whole cohorts got zero slots forever. The
# cap is now a fair round-robin share (see _fair_order) and the wall-clock
# budget below is the real ceiling, so a larger cap costs nothing when the
# queue is short and unblocks starved cohorts when it is long.
_CAP = int(os.environ.get("FORECLOSURE_NAME_RESOLVE_MAX", "1200"))
_BUDGET_S = float(os.environ.get("FORECLOSURE_NAME_RESOLVE_BUDGET_S", "900"))
_CONCURRENCY = int(os.environ.get("FORECLOSURE_NAME_RESOLVE_CONCURRENCY", "6"))


# ---------------------------------------------------------------------------
# Sample-row owner/situs field detection (for layers with empty metadata)
# ---------------------------------------------------------------------------

# Owner column-name fragments (incl. SCDOT's cryptic 'SHEET1__Na').
_OWNER_NAME_HINTS = ("owner", "ownername", "ownr", "name", "_na", "taxpayer")
# Things that look like a name field but are mailing/legal -> reject as owner.
_OWNER_NAME_NEG = ("mail", "addr", "city", "zip", "state", "legal", "desc",
                   "agent", "care", "deed", "book", "page", "date", "phone",
                   "subname", "nbhd", "cityname", "township")
# Situs column-name fragments (incl. SCDOT's 'SHEET1___1').
_SITUS_HINTS = ("situs", "siteadd", "site_add", "propaddr", "prop_addr",
                "property_address", "locaddr", "loc_addr", "street", "___1")
_SITUS_NEG = ("mail", "owner", "zip", "city", "state", "legal")

# Cache keyed by base url: (owner_field, situs_field) discovered from a sample row.
_SAMPLE_FIELD_CACHE: dict[str, tuple[Optional[str], Optional[str]]] = {}


def _looks_like_name(v: Any) -> bool:
    """Heuristic: a cell that reads like a person/company name (letters + space,
    not a number, not an address line that starts with a digit)."""
    s = str(v or "").strip()
    if len(s) < 4 or len(s) > 80:
        return False
    if s[0].isdigit():
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= max(3, len(s) // 2) and " " in s


def _looks_like_street(v: Any) -> bool:
    """Heuristic: a cell that reads like a street line (leading house number)."""
    s = str(v or "").strip()
    if len(s) < 4:
        return False
    head = s.split()[0] if s.split() else ""
    return head.isdigit() and len(s) > len(head) + 1


# Common street-type tokens — used to validate a written situs that has no
# leading house number isn't just a bare "CITY ST" placeholder.
_STREET_WORDS = {
    "ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "CT", "COURT",
    "AVE", "AVENUE", "BLVD", "CIR", "CIRCLE", "WAY", "TRL", "TRAIL", "PL",
    "PLACE", "HWY", "HIGHWAY", "PKWY", "TER", "TERRACE", "LOOP", "RUN", "PT",
    "COVE", "CV", "XING", "PASS", "BND",
}
# US state-abbrev tail that marks a value as a city/state line, not a street.
_STATE_TAILS = {"NC", "SC", "GA", "TN", "VA", "FL"}


def _valid_situs(s: Optional[str]) -> bool:
    """A resolved street_address is trustworthy only if it carries a house number
    OR a recognizable street-type word. The cryptic SCDOT layers (Cherokee) put a
    bare 'GAFFNEY SC' city/state line in the situs cell when the street is blank —
    reject those so we never write a city as the property address."""
    t = (s or "").strip().upper()
    if len(t) < 5:
        return False
    toks = t.replace(",", " ").split()
    if not toks:
        return False
    if toks[0].isdigit() and len(toks) >= 2:
        return True
    if any(w in _STREET_WORDS for w in toks):
        return True
    # Bare "CITY ST" (2-3 tokens ending in a state tail, no street word) -> reject.
    return False


def _valid_parcel(p: Optional[str]) -> bool:
    """Reject a parcel_id that is actually a decimal acreage / value the cryptic
    SCDOT layers expose (e.g. '38.06', '41.05'). A real PIN is an all-digit /
    dash-segmented id, never a small 2-decimal float."""
    t = (p or "").strip()
    if not t:
        return False
    import re as _re
    if _re.fullmatch(r"\d{1,4}\.\d{1,2}", t):  # acreage/value-shaped
        return False
    digits = _re.sub(r"\D", "", t)
    return len(digits) >= 5


async def _sample_row(c: httpx.AsyncClient, base: str) -> Optional[dict[str, Any]]:
    try:
        r = await c.get(base, params={
            "where": "1=1", "outFields": "*", "returnGeometry": "false",
            "resultRecordCount": "1", "f": "json",
        }, timeout=20.0)
        if r.status_code != 200:
            return None
        feats = r.json().get("features") or []
        if feats and feats[0].get("attributes"):
            return dict(feats[0]["attributes"])
    except (httpx.HTTPError, ValueError):
        return None
    return None


def _detect_from_sample(attrs: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Pick (owner_field, situs_field) from one real attribute row by name-hint
    AND value-shape. Used when the layer metadata exposes no field list."""
    owner_field = situs_field = None
    # Owner: prefer a hinted column whose value reads like a name.
    owner_cands = []
    for k, v in attrs.items():
        kl = k.lower()
        if any(h in kl for h in _OWNER_NAME_HINTS) and not any(n in kl for n in _OWNER_NAME_NEG):
            owner_cands.append((k, v))
    for k, v in owner_cands:
        if _looks_like_name(v):
            owner_field = k
            break
    if owner_field is None and owner_cands:
        owner_field = owner_cands[0][0]
    # Situs: prefer a hinted column whose value reads like a street.
    situs_cands = []
    for k, v in attrs.items():
        kl = k.lower()
        if any(h in kl for h in _SITUS_HINTS) and not any(n in kl for n in _SITUS_NEG):
            situs_cands.append((k, v))
    for k, v in situs_cands:
        if _looks_like_street(v):
            situs_field = k
            break
    if situs_field is None and situs_cands:
        situs_field = situs_cands[0][0]
    return owner_field, situs_field


async def _resolve_fields(
    c: httpx.AsyncClient, base: str,
) -> tuple[Optional[str], Optional[str]]:
    """(owner_field, situs_field) — metadata detectors first, sample-row fallback."""
    owner_field = await _detect_owner_field_v2(c, base)
    situs_field = await _detect_site_field(c, base)
    if owner_field and situs_field:
        return owner_field, situs_field
    # Fill the gap(s) from a sampled row (handles empty-metadata SCDOT layers).
    if base not in _SAMPLE_FIELD_CACHE:
        attrs = await _sample_row(c, base)
        _SAMPLE_FIELD_CACHE[base] = _detect_from_sample(attrs or {})
    s_owner, s_situs = _SAMPLE_FIELD_CACHE[base]
    return owner_field or s_owner, situs_field or s_situs


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------

def _county_clean(li: Listing) -> str:
    c = (li.county or "").replace(" County", "").strip()
    for sfx in (", NC", ", SC", ",NC", ",SC"):
        if c.upper().endswith(sfx):
            c = c[: -len(sfx)].strip()
    return c.split(",")[0].strip().title()


def _endpoint_cfg(li: Listing) -> Optional[dict[str, Any]]:
    """Endpoint + field plan for a lead's county, or None when nothing is wired.

    Prefers a PINNED county-owned SC layer (audited fields, situs guaranteed to
    be the property address and not the owner's mailing street). Everything else
    falls back to the shared auto-detecting path — which for SC now means the
    token-walled SCDOT service, handled by the dead-endpoint detector below.
    """
    county = _county_clean(li)
    if li.state == "SC":
        if county in SC_NO_FREE_OWNER_SEARCH:
            return None
        pinned = SC_OWNER_LAYERS.get(county)
        if pinned:
            return {
                "base": pinned["url"], "owner_field": pinned["owner"],
                "situs_field": pinned["situs"], "parcel_field": pinned["parcel"],
                "mail_fields": pinned["mail"], "pinned": True, "county": county,
            }
    base = _endpoint_for(li)
    if not base:
        return None
    return {
        "base": base, "owner_field": None, "situs_field": None,
        "parcel_field": None, "mail_fields": (), "pinned": False,
        "county": county,
    }


def _in_core(li: Listing) -> bool:
    # Resolvable = the county has a wired GIS owner-search endpoint. This now
    # covers coastal NC/SC (Charleston, Georgetown, Horry, Beaufort, Brunswick,
    # New Hanover, Pender, Onslow, Carteret, ...) which are real targets, not the
    # old inland-only _CORE_* sets. Unwired counties fall out via _endpoint_cfg.
    return _endpoint_cfg(li) is not None


# Government/agency parties that show up as the plaintiff on tax-foreclosure
# notices — never a resolvable property owner, so skip them entirely.
_GOV_PREFIXES = (
    "COUNTY OF ", "CITY OF ", "TOWN OF ", "STATE OF ", "DEPARTMENT OF ",
    "DEPT OF ", "US ", "UNITED STATES", "INTERNAL REVENUE", "SC DEPARTMENT",
    "NC DEPARTMENT",
)


def _is_gov_entity(name: str) -> bool:
    u = name.upper().strip()
    return any(u.startswith(p) for p in _GOV_PREFIXES)


def _lead_name(li: Listing) -> Optional[str]:
    """Best person/party name to resolve. Prefer owner_name (record owner) but
    fall back to defendant (court party)."""
    for cand in (li.owner_name, li.defendant):
        s = (cand or "").strip()
        if len(s) >= 4 and not s.replace(" ", "").isdigit() and not _is_gov_entity(s):
            return s
    return None


def _priority(li: Listing) -> int:
    """Sort key — prioritized name-indexed surfaces resolve first within the cap."""
    src = (li.source or "").lower()
    lt = (li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type or "")).lower()
    score = 0
    if any(p in src for p in _PRIORITY_SOURCES):
        score += 2
    if lt in _PRIORITY_TYPES:
        score += 1
    return score


def _is_target(li: Listing) -> bool:
    if li.state not in ("NC", "SC"):
        return False
    if (li.street_address or "").strip() or (li.parcel_id or "").strip():
        return False
    if not _lead_name(li):
        return False
    if not _in_core(li):
        return False
    # Idempotency: skip leads we actually QUERIED before. Environmental bails
    # (dead endpoint, budget exhausted) record queried=False so they retry.
    if not _FORCE and isinstance(li.raw, dict):
        if (li.raw.get("resolved_from_name") or {}).get("queried"):
            return False
    return True


def _fair_order(targets: list[Listing]) -> list[Listing]:
    """Round-robin across sources so no cohort is starved by board position.

    ROOT CAUSE this replaces: `sorted(key=_priority)` is STABLE, so within one
    priority tier the order is board order. counties_sc.sc_public_index sits at
    board indices ~17k-21k, so it received ZERO of the 400 cap slots on every
    single run — the cohort was structurally unreachable, not merely slow.
    Interleaving one lead per source per lap means every source gets a share of
    the cap no matter where it landed on the board.
    """
    buckets: dict[str, list[Listing]] = {}
    for li in targets:
        buckets.setdefault(li.source or "?", []).append(li)
    for bucket in buckets.values():
        bucket.sort(key=_priority, reverse=True)
    # Strongest name-indexed surfaces lead each lap; ties broken by name so the
    # order is deterministic run to run.
    order = sorted(buckets, key=lambda s: (-_priority(buckets[s][0]), s))
    out: list[Listing] = []
    lap = 0
    longest = max(len(b) for b in buckets.values())
    while lap < longest:
        for src in order:
            bucket = buckets[src]
            if lap < len(bucket):
                out.append(bucket[lap])
        lap += 1
    return out


# ---------------------------------------------------------------------------
# Match + commit helpers
# ---------------------------------------------------------------------------

def _mark(li: Listing, confidence: str, *, queried: bool, **extra: Any) -> None:
    """Record provenance on EVERY exit path.

    Before this, four of six exits returned without writing anything, so
    "attempted and failed" was indistinguishable from "never attempted" — the
    whole cohort looked untouched on the board.

    `queried` is the idempotency switch, and it is deliberately NOT always True:
      * True  -> we actually ran an owner-name query. Re-runs skip this lead.
      * False -> environmental bail (dead endpoint, no owner field, budget
                 exhausted). Visible and countable, but the lead retries next
                 run once the condition clears.
    """
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["resolved_from_name"] = {
        "queried": queried,
        "county": _county_clean(li),
        "state": li.state,
        "strategy": "gis_owner_name_search",
        "confidence": confidence,
        **extra,
    }


def _strict_matches(
    rows: list[dict[str, Any]], owner_field: str, name: str,
) -> list[tuple[str, dict[str, Any]]]:
    """(match_kind, row) for every row whose owner STRICTLY matches `name`.

    Strictness lives in name_normalize.match_owner: exact normalized token-set
    equality, or surname-in-surname-position + first-name-in-first-name-position.
    A bag-of-tokens rule accepted roughly one wrong person per three "unique"
    matches on this cohort; positional matching removes them.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        kind = match_owner(name, str(row.get(owner_field) or ""))
        if kind:
            out.append((kind, row))
    return out


def _row_parcel(row: dict[str, Any], parcel_field: Optional[str]) -> Optional[str]:
    if not parcel_field:
        return None
    for k, v in row.items():
        if k.lower() == parcel_field.lower():
            s = str(v or "").strip()
            return s or None
    return None


def _safe_attrs(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Attribute bag safe to hand to the standard writers.

    Drops the county's owner-MAILING columns (Spartanburg StreetAddr/City/State/
    Zip, Union Address_1, ...) — FIELD_ALIASES['site_address'] contains
    'ADDRESS_1' and the city/zip aliases would otherwise pull the owner's mailing
    city onto the property. Then injects the PINNED situs/parcel under keys the
    standard writer recognizes, so a county with no situs column simply gets no
    street address instead of a guessed one.
    """
    mail = {m.lower() for m in (cfg.get("mail_fields") or ())}
    attrs = {k: v for k, v in row.items() if k.lower() not in mail}
    if not cfg.get("pinned"):
        return attrs

    situs_field = cfg.get("situs_field")
    if situs_field:
        for k, v in row.items():
            if k.lower() == situs_field.lower():
                s = str(v or "").strip()
                if s and s not in ("0", "<Null>"):
                    attrs["SITUS_ADDR"] = s
                break
    parcel = _row_parcel(row, cfg.get("parcel_field"))
    if parcel:
        attrs["PARID"] = parcel   # PARID is in FIELD_ALIASES['parcel_id']
    return attrs


async def _layer_health(c: httpx.AsyncClient, base: str) -> Optional[str]:
    """None when the layer is serving; else a short reason string.

    Catches the SILENT-200 class of failure: SCDOT now answers HTTP 200 with
    {"error":{"code":499,"message":"Token Required"}}. Every caller in this repo
    treated that as an empty result, so 617 dead calls per run logged as
    "200 OK" and the word "Token" appeared in zero log lines.
    """
    layer_url = base.rsplit("/query", 1)[0]
    try:
        r = await c.get(layer_url, params={"f": "json"}, timeout=15.0)
        if r.status_code != 200:
            return f"http_{r.status_code}"
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return type(exc).__name__
    err = data.get("error") if isinstance(data, dict) else None
    if err:
        return f"error_{err.get('code')}_{str(err.get('message'))[:40]}"
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def enrich_resolve_name_to_property(
    listings: list[Listing], concurrency: int = _CONCURRENCY,
) -> dict[str, int]:
    """Resolve name-indexed leads (owner_name/defendant, no address/parcel) to a
    real parcel via the county GIS owner-name index. Conservative: writes only on
    a strict match. Returns a stats dict for the orchestrator log."""
    stats = {
        "enabled": 1 if _ENABLED else 0, "targets": 0, "attempted": 0,
        "no_endpoint": 0, "no_owner_field": 0, "endpoint_dead": 0, "no_rows": 0,
        "ambiguous": 0, "resolved": 0, "middle_conflict": 0, "address_filled": 0,
        "parcel_filled": 0, "value_filled": 0, "sqft_filled": 0,
        "budget_hit": 0, "cap_hit": 0,
    }
    if not _ENABLED:
        log.info("name_resolve.disabled")
        return stats

    targets = [li for li in listings if _is_target(li)]
    stats["targets"] = len(targets)
    if not targets:
        log.info("name_resolve.no_targets")
        return stats

    # Fair share of the cap for every source, then cap.
    targets = _fair_order(targets)
    if len(targets) > _CAP:
        stats["cap_hit"] = 1
        targets = targets[:_CAP]

    log.info("name_resolve.start", target_count=len(targets), of_total=len(listings),
             cap=_CAP, budget_s=_BUDGET_S)

    sem = asyncio.Semaphore(concurrency)
    field_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}
    health_cache: dict[str, Optional[str]] = {}
    health_lock = asyncio.Lock()
    t0 = time.monotonic()
    stop = asyncio.Event()

    async def _health(c: httpx.AsyncClient, base: str) -> Optional[str]:
        async with health_lock:
            if base not in health_cache:
                health_cache[base] = await _layer_health(c, base)
                if health_cache[base]:
                    log.warning("source_health.layer_dead", component="name_resolve",
                                base=base, reason=health_cache[base])
        return health_cache[base]

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        if stop.is_set():
            return
        if time.monotonic() - t0 > _BUDGET_S:
            stop.set()
            stats["budget_hit"] = 1
            _mark(li, "budget_bail", queried=False)
            return

        cfg = _endpoint_cfg(li)
        if not cfg:
            stats["no_endpoint"] += 1
            _mark(li, "no_endpoint", queried=False)
            return
        base = cfg["base"]

        dead = await _health(c, base)
        if dead:
            stats["endpoint_dead"] += 1
            _mark(li, "endpoint_dead", queried=False, endpoint=base, reason=dead)
            return

        owner_field = cfg["owner_field"]
        situs_field = cfg["situs_field"]
        if not cfg["pinned"]:
            if base not in field_cache:
                field_cache[base] = await _resolve_fields(c, base)
            owner_field, situs_field = field_cache[base]
        if not owner_field:
            stats["no_owner_field"] += 1
            _mark(li, "no_owner_field", queried=False, endpoint=base)
            return

        name = _lead_name(li)
        if not isinstance(li.raw, dict):
            li.raw = {}

        for party in _split_joint(name):
            patterns = like_patterns(party)
            if not patterns:
                continue

            # Re-check the budget HERE, not just at task entry: gather() dispatches
            # every target at once, so without this a long queue of leads
            # serialized behind a slow host would all sail past the entry check
            # and run for far longer than _BUDGET_S.
            if time.monotonic() - t0 > _BUDGET_S:
                stop.set()
                stats["budget_hit"] = 1
                _mark(li, "budget_bail", queried=False)
                return

            async with sem:
                stats["attempted"] += 1
                rows = await _query_owner(c, base, owner_field, patterns)
            if not rows:
                continue

            hits = _strict_matches(rows, owner_field, party)
            if not hits:
                continue

            # Several parcels for one owner: real and common (a landlord holding
            # multiple lots). Keep every candidate on the lead and FLAG it —
            # never pick one at random and present it as the address.
            parcels = {
                _row_parcel(r, cfg.get("parcel_field")) or str(r.get("OBJECTID") or i)
                for i, (_k, r) in enumerate(hits)
            }
            if len(hits) > 1 and len(parcels) > 1:
                stats["ambiguous"] += 1
                _mark(
                    li, "ambiguous_multi_parcel", queried=True,
                    query_name=party, match_count=len(hits),
                    matched_owner=str(hits[0][1].get(owner_field) or "").strip(),
                    candidates=[
                        {
                            "parcel_id": _row_parcel(r, cfg.get("parcel_field")),
                            "owner": str(r.get(owner_field) or "").strip(),
                            "match": k,
                        }
                        for k, r in hits[:10]
                    ],
                )
                return

            kind, best = hits[0]
            matched_owner = str(best.get(owner_field) or "").strip()
            attrs = _safe_attrs(best, cfg)
            if not cfg["pinned"]:
                _inject_site_alias(attrs, situs_field)

            had_addr = bool((li.street_address or "").strip())
            had_parcel = bool((li.parcel_id or "").strip())
            had_value = bool(li.market_value)
            had_sqft = bool(li.living_sqft)

            _populate_from_attrs(li, attrs)
            # Sanity-reject artifacts a GIS layer can still emit:
            #   * a mailing / PO-box line as situs,
            #   * a bare 'CITY ST' line (no house number / street word) as situs,
            #   * a decimal acreage/value (e.g. '38.06') as parcel_id.
            if not had_addr and li.street_address and (
                _looks_like_mailing(li.street_address)
                or not _valid_situs(li.street_address)
            ):
                li.street_address = None
            if not had_parcel and li.parcel_id and not _valid_parcel(li.parcel_id):
                li.parcel_id = None
            # Value + sqft + owner from the matched parcel attribute bag.
            apply_gis_attrs(li, attrs)

            now_addr = bool((li.street_address or "").strip())
            now_parcel = bool((li.parcel_id or "").strip())
            if (now_addr and not had_addr) or (now_parcel and not had_parcel):
                stats["resolved"] += 1
                if now_addr and not had_addr:
                    stats["address_filled"] += 1
                if now_parcel and not had_parcel:
                    stats["parcel_filled"] += 1
                if li.market_value and not had_value:
                    stats["value_filled"] += 1
                if li.living_sqft and not had_sqft:
                    stats["sqft_filled"] += 1
                # Same surname + first name but a provably different spelled-out
                # middle name. Still committed (a surname+firstname hit in the
                # right county is real signal) but flagged and counted so review
                # can see the doubt before outreach.
                conflict = middle_conflict(party, matched_owner)
                if conflict:
                    stats["middle_conflict"] += 1
                _mark(
                    li, kind, queried=True, matched_owner=matched_owner,
                    from_field="owner_name" if li.owner_name == name else "defendant",
                    query_name=party, endpoint=base, middle_conflict=conflict,
                )
                return
            # Matched the owner but the layer carried no usable situs/parcel.
            stats["no_rows"] += 1
            _mark(li, f"{kind}_no_parcel_data", queried=True,
                  matched_owner=matched_owner, query_name=party)
            return

        # Reached GIS, no strict match -> mark queried so re-runs skip it.
        _mark(li, "no_match", queried=True, query_name=name)

    async with client(timeout=25.0) as c:
        # Hard wall-clock backstop around the whole fan-out. The per-call budget
        # check above stops NEW queries; this guarantees the pass returns even if
        # in-flight requests stall, so the caller always gets to write the board.
        try:
            await asyncio.wait_for(
                asyncio.gather(*(one(c, li) for li in targets)),
                timeout=_BUDGET_S + 30.0,
            )
        except asyncio.TimeoutError:
            stats["budget_hit"] = 1
            log.warning("name_resolve.hard_timeout",
                        elapsed_s=round(time.monotonic() - t0))

    log.info("name_resolve.done", **stats)
    return stats
