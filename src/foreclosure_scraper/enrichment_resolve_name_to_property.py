"""NAME -> PROPERTY -> EQUITY -> CONTACT resolver (the backbone).

Turns NAME-INDEXED leads — SC Public Index civil/criminal, SC divorce, NC court
ingest, probate notices, future inmate rosters — into real PROPERTY leads. Many
such leads carry only an owner/party name (owner_name or defendant) with NO
street_address, NO parcel_id, NO value. Outreach and grading are impossible
until that name is tied to a parcel.

WHAT IT DOES (per qualifying lead, free / pure-HTTP / no auth / no login):
  1. Resolve the lead's county GIS owner-name layer (SCDOT SC_Parcels per-county
     or the audited NC FeatureServers in enrichment_arcgis).
  2. Run an owner-name LIKE search (surname-first, the order GIS stores it) and
     take the single best UNIQUE match — never guess on ambiguity.
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

MATCHING POLICY (unchanged from v2 — this data drives outreach):
  * Individuals: surname + >=1 given token must both appear in the GIS owner.
  * Companies: every distinctive company token must appear.
  * Multiple GIS rows: pick the single best by token score ONLY if it is a clear,
    unique winner; ties / ambiguity -> commit nothing.

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
    _company_tokens,
    _endpoint_for,
    _inject_site_alias,
    _is_company,
    _like_patterns,
    _looks_like_mailing,
    _parse_individual,
    _query_owner,
    _split_joint,
    _best_unique,
    _detect_owner_field_v2,
    _detect_site_field,
)
from .enrichment_gis_attrs import apply_gis_attrs
from .http_client import client
from .models import Listing

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
_CAP = int(os.environ.get("FORECLOSURE_NAME_RESOLVE_MAX", "400"))
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


def _in_core(li: Listing) -> bool:
    cty = _county_clean(li)
    return (li.state == "NC" and cty in _CORE_NC) or (li.state == "SC" and cty in _CORE_SC)


def _lead_name(li: Listing) -> Optional[str]:
    """Best person/party name to resolve. Prefer owner_name (record owner) but
    fall back to defendant (court party)."""
    for cand in (li.owner_name, li.defendant):
        s = (cand or "").strip()
        if len(s) >= 4 and not s.replace(" ", "").isdigit():
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
    # Idempotency: skip already-attempted unless forced.
    if not _FORCE and isinstance(li.raw, dict):
        if (li.raw.get("resolved_from_name") or {}).get("queried"):
            return False
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def enrich_resolve_name_to_property(
    listings: list[Listing], concurrency: int = _CONCURRENCY,
) -> dict[str, int]:
    """Resolve name-indexed leads (owner_name/defendant, no address/parcel) to a
    real parcel via the county GIS owner-name index. Conservative: writes only on
    a unique confident match. Returns a stats dict for the orchestrator log."""
    stats = {
        "enabled": 1 if _ENABLED else 0, "targets": 0, "attempted": 0,
        "no_endpoint": 0, "no_owner_field": 0, "no_rows": 0, "ambiguous": 0,
        "resolved": 0, "address_filled": 0, "parcel_filled": 0,
        "value_filled": 0, "sqft_filled": 0, "budget_hit": 0, "cap_hit": 0,
    }
    if not _ENABLED:
        log.info("name_resolve.disabled")
        return stats

    targets = [li for li in listings if _is_target(li)]
    stats["targets"] = len(targets)
    if not targets:
        log.info("name_resolve.no_targets")
        return stats

    # Prioritize the strongest name-indexed surfaces, then cap.
    targets.sort(key=_priority, reverse=True)
    if len(targets) > _CAP:
        stats["cap_hit"] = 1
        targets = targets[:_CAP]

    log.info("name_resolve.start", target_count=len(targets), of_total=len(listings),
             cap=_CAP, budget_s=_BUDGET_S)

    sem = asyncio.Semaphore(concurrency)
    field_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}
    t0 = time.monotonic()
    stop = asyncio.Event()

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        if stop.is_set():
            return
        if time.monotonic() - t0 > _BUDGET_S:
            stop.set()
            stats["budget_hit"] = 1
            return

        base = _endpoint_for(li)
        if not base:
            stats["no_endpoint"] += 1
            return

        if base not in field_cache:
            field_cache[base] = await _resolve_fields(c, base)
        owner_field, situs_field = field_cache[base]
        if not owner_field:
            stats["no_owner_field"] += 1
            return

        name = _lead_name(li)
        # Mark attempted (idempotency) the moment we commit to querying GIS.
        if not isinstance(li.raw, dict):
            li.raw = {}

        matched = False
        for party in _split_joint(name):
            if _is_company(party):
                parsed_ind, comp_tokens = None, _company_tokens(party)
            else:
                parsed_ind, comp_tokens = _parse_individual(party), []
            patterns = _like_patterns(parsed_ind, comp_tokens)
            if not patterns:
                continue

            async with sem:
                stats["attempted"] += 1
                rows = await _query_owner(c, base, owner_field, patterns)
            if not rows:
                continue

            best = _best_unique(rows, owner_field, parsed_ind, comp_tokens)
            if best is None:
                if len(rows) > 1:
                    stats["ambiguous"] += 1
                else:
                    stats["no_rows"] += 1
                continue

            # --- commit the unique match ---
            matched_owner = str(best.get(owner_field) or "").strip()
            _inject_site_alias(best, situs_field)
            had_addr = bool((li.street_address or "").strip())
            had_parcel = bool((li.parcel_id or "").strip())
            had_value = bool(li.market_value)
            had_sqft = bool(li.living_sqft)

            _populate_from_attrs(li, best)
            # Sanity-reject artifacts the cryptic SCDOT layers can write:
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
            apply_gis_attrs(li, best)

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
                li.raw["resolved_from_name"] = {
                    "queried": True,
                    "county": _county_clean(li),
                    "state": li.state,
                    "strategy": "gis_owner_name_search",
                    "confidence": "unique_match",
                    "matched_owner": matched_owner,
                    "from_field": "owner_name" if li.owner_name == name else "defendant",
                    "query_name": name,
                }
                matched = True
                return

        # Reached GIS, no confident match -> mark attempted so re-runs skip it.
        li.raw.setdefault("resolved_from_name", {"queried": True,
                                                 "strategy": "gis_owner_name_search",
                                                 "confidence": "no_match"})

    async with client(timeout=25.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("name_resolve.done", **stats)
    return stats
