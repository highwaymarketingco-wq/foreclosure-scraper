"""Owner/defendant-name -> property address resolver (v2).

ROOT CAUSE this module fixes (measured against docs/listings.json on the
672-lead no-address+no-parcel+has-defendant cohort):

  1. OWNER FIELD NOT DETECTED.  enrichment_address_backfill._detect_owner_field
     only recognizes owner columns whose name contains "owner" or sits in a
     fixed candidate list.  The single largest cohort county -- Gaston, NC
     (177 of 599 non-bankruptcy leads) -- stores its owner in CURR_NAME1 /
     CURR_NAME2, which match neither rule, so Gaston was NEVER queried
     (no_owner_field).  Cleveland (GIS_Owner1) and a few others were also
     missed.  -> 53 of a 150-lead sample short-circuited with no_owner_field.

  2. NAME-ORDER MISMATCH.  County GIS stores owners surname-first with no
     comma ("LOUSSEDES HAYDEN", "CROCKETT DEBRA MARIE L").  NC eCourts emits
     defendants comma-first ("Loussedes, Hayden"); SC emits given-first
     ("Michelle J Miller").  The old _defendant_search_terms sorts tokens by
     LENGTH, so it builds %HAYDEN%LOUSSEDES% (given-then-surname) and queries
     that first; _query_by_owner stops on the first pattern that returns ANY
     rows.  The surname-first pattern that would actually match GIS is tried
     second or never.

  3. MULTI-RESULT REJECTION.  When the broad single-token fallback returns
     several rows, the old tie-break requires the owner string to contain ALL
     distinctive defendant tokens.  GIS owner strings carry extra middle
     names, suffixes, "& SPOUSE", "ET AL", "<br>(LIFE ESTATE)" -- the
     defendant tokens are a subset, never a superset, so set-equality and
     all-tokens-present rules reject correct matches.  -> matched_multi=65 vs
     matched_single=19, only 14 addresses actually committed.

  4. ADDRESS FIELD NOT IN ALIASES.  Even on a correct owner match,
     _populate_from_attrs reads the situs via FIELD_ALIASES["site_address"],
     which omits Gaston's CURR_ADDR1, Pickens' LOCADD, Greenville's STREET,
     etc.  So those counties yielded parcel_id + centroid but no street.

This module is ADDITIVE and self-contained.  It does not modify the existing
enrichers or the orchestrator (scripts/merge_today_sources.py /
scripts/regenerate_dashboard.py).  It reuses _populate_from_attrs for the
write so confidence flags, parcel/spec backfill, and placeholder filtering
stay identical to the rest of the pipeline.

Matching policy (investor-grade conservative -- this data drives outreach):

  * Individuals: require surname + at least one given-name token to both
    appear in the owner string.  Surname-only is too loose for common names.
  * Companies (LLC/Inc/Corp/...): require every distinctive company token to
    appear in the owner string.
  * Multiple GIS rows: pick the single best by token score ONLY if it is a
    clear, unique winner (strictly higher score than the runner-up AND meets
    the per-type token threshold).  Ties -> commit nothing.
  * Fiduciary / heirs / unknown-spouse boilerplate stripped before matching.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx
import structlog

from .enrichment_address_backfill import _populate_from_attrs
from .enrichment_arcgis import (
    FIELD_ALIASES,
    NC_GIS,
    SC_LAYER,
    SCDOT_BASE,
    _detect_addr_field,
    _pick,
)
from .http_client import client
from .models import Listing

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Owner-field detection (expanded over enrichment_address_backfill)
# ---------------------------------------------------------------------------

# Ordered by specificity.  Adds the columns the old list missed:
# CURR_NAME1/2 (Gaston), GIS_Owner1 (Cleveland), TaxpayerName, CurrentOwner1,
# OwnerAll, OWNAM1/2 (already), NAME_1, Name1.  Mailing/escrow name fields are
# deliberately excluded.
_OWNER_FIELD_CANDIDATES_V2 = (
    "OwnerName", "OWNERNAME", "CURR_NAME1", "GIS_Owner1", "OWNAM1", "OWNAM2",
    "Owner1", "OwnerAll", "PROPERTY_OWNER", "full_owner_name", "CurrentOwner1",
    "TaxpayerName", "OWNER_NAME", "NAME_1", "NAME1", "Name1", "ownname",
    "owner", "OWNER", "NAMECO", "Name", "CURR_NAME2",
)

# Field-name fragments that look like an owner/name column but are actually a
# mailing/agent/escrow/legal-description field -> never use as owner.
_OWNER_FIELD_NEGATIVE = ("mail", "addr", "city", "zip", "state", "legal",
                         "desc", "agent", "care", "c_o", "co_", "_co",
                         "deed", "book", "page", "date", "phone", "email")

_FIELD_SCHEMA_CACHE: dict[str, list[str]] = {}


async def _layer_fields(c: httpx.AsyncClient, base_url: str) -> list[str]:
    if base_url in _FIELD_SCHEMA_CACHE:
        return _FIELD_SCHEMA_CACHE[base_url]
    layer_url = base_url.rsplit("/query", 1)[0]
    try:
        r = await c.get(layer_url, params={"f": "json"}, timeout=15.0)
        if r.status_code != 200:
            return []
        data = r.json()
        fields = [f["name"] for f in data.get("fields", []) if "name" in f]
    except (httpx.HTTPError, ValueError):
        return []
    _FIELD_SCHEMA_CACHE[base_url] = fields
    return fields


async def _detect_owner_field_v2(c: httpx.AsyncClient, base_url: str) -> Optional[str]:
    fields = await _layer_fields(c, base_url)
    if not fields:
        return None
    field_lower = {f.lower(): f for f in fields}
    for cand in _OWNER_FIELD_CANDIDATES_V2:
        if cand.lower() in field_lower:
            return field_lower[cand.lower()]
    # Generic fallback: a field whose name contains owner/ownr/owmer/name and
    # is not a mailing/agent/legal field.
    for f in fields:
        flow = f.lower()
        looks_owner = ("owner" in flow or "ownr" in flow
                       or flow in ("name", "name1", "name_1", "curr_name1"))
        if looks_owner and not any(neg in flow for neg in _OWNER_FIELD_NEGATIVE):
            return f
    return None


async def _detect_site_field(c: httpx.AsyncClient, base_url: str) -> Optional[str]:
    """Address/situs field, reusing the arcgis detector (covers CURR_ADDR1,
    LOCADD, STREET, etc. via its candidate list + addr/street/situs fallback)."""
    return await _detect_addr_field(c, base_url)


# ---------------------------------------------------------------------------
# Name parsing -- surname-anchored, format-aware
# ---------------------------------------------------------------------------

_NAME_STOPWORDS = {
    "LLC", "L.L.C", "LLP", "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LP",
    "LTD", "FUND", "TRUST", "TRUSTEE", "TRUSTEES", "ESTATE", "REVOCABLE",
    "IRREVOCABLE", "JR", "SR", "II", "III", "IV", "V", "ETAL", "ET", "AL",
    "PERSONAL", "REPRESENTATIVE", "REP", "AS", "THE", "AND", "OR", "OF", "FOR",
    "A", "AN", "MR", "MRS", "MS", "DR", "DECD", "DECEASED", "AKA", "FKA",
    "DBA", "UNKNOWN", "SPOUSE", "HEIRS", "DEVISEES", "ATLAW", "LAW", "ANY",
    "CURRENT", "OCCUPANT", "OCCUPANTS", "TENANT", "IF", "TENANTS",
}

# Boilerplate co-party clauses we want gone before parsing.
_BOILERPLATE_RE = re.compile(
    r"(current\s+occupant\(s\)|current\s+occupant|spouse,?\s+if\s+any.*$|"
    r"unknown\s+spouse\s+of|any\s+heirs[- ]at[- ]law\s+or\s+devisees\s+of|"
    r"heirs[- ]at[- ]law|,?\s*personal\s+representative.*$|,?\s*et\s*al\.?.*$|"
    r"as\s+trustee.*$|c\s*/\s*o\s+\S+.*$)",
    re.I,
)

_COMPANY_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|CORPORATION|COMPANY|CO\.|LP|LTD|LLP|FUND|"
    r"ENTERPRISES|HOLDINGS|GROUP|PROPERTIES|INVESTMENTS|PARTNERS)\b", re.I)


def _is_company(name: str) -> bool:
    return bool(_COMPANY_RE.search(name or ""))


def _split_joint(defendant: str) -> list[str]:
    """Split a joint-defendant string into individual party names.

    NC eCourts joins parties with ';'.  Some sources use ' & ' / ' AND '
    between two full names.  We only split on ';' and clear conjunctions to
    avoid breaking single names that happen to contain 'and'.
    """
    if not defendant:
        return []
    parts = re.split(r";", defendant)
    out: list[str] = []
    for p in parts:
        p = _BOILERPLATE_RE.sub(" ", p).strip(" ,.;")
        if p:
            out.append(p)
    return out or [defendant.strip()]


def _parse_individual(name: str) -> Optional[tuple[str, list[str]]]:
    """Return (surname, [given tokens]) for an individual, or None.

    Handles both 'LAST, FIRST MIDDLE' (comma => surname is left of comma) and
    'FIRST MIDDLE LAST' (no comma => surname is the LAST token).  Drops
    stopwords/suffixes.  Requires a surname of length >= 2.
    """
    raw = _BOILERPLATE_RE.sub(" ", name or "")
    raw = re.sub(r"[<>().&/+]", " ", raw)
    if "," in raw:
        left, right = raw.split(",", 1)
        surname_tokens = [t for t in re.split(r"\W+", left.upper())
                          if t and t not in _NAME_STOPWORDS and len(t) >= 2]
        given_tokens = [t for t in re.split(r"\W+", right.upper())
                        if t and t not in _NAME_STOPWORDS and len(t) >= 2]
        surname = surname_tokens[0] if surname_tokens else None
    else:
        toks = [t for t in re.split(r"\W+", raw.upper())
                if t and t not in _NAME_STOPWORDS and len(t) >= 2]
        if not toks:
            return None
        surname = toks[-1]
        given_tokens = toks[:-1]
    if not surname or len(surname) < 2:
        return None
    return surname, given_tokens


def _company_tokens(name: str) -> list[str]:
    raw = _BOILERPLATE_RE.sub(" ", name or "")
    raw = re.sub(r"[<>().&/+,]", " ", raw)
    return [t for t in re.split(r"\W+", raw.upper())
            if t and t not in _NAME_STOPWORDS and len(t) >= 3]


def _owner_tokens(owner: str) -> set[str]:
    """Distinctive tokens of a GIS owner string (drops noise: ET AL, LIFE
    ESTATE, &, suffixes, single letters)."""
    s = re.sub(r"<[^>]*>", " ", owner or "")          # strip <br> etc.
    s = re.sub(r"[<>().&/+,]", " ", s)
    s = re.sub(r"\bLIFE\s+ESTATE\b", " ", s, flags=re.I)
    return {t for t in re.split(r"\W+", s.upper())
            if t and t not in _NAME_STOPWORDS and len(t) >= 2}


# ---------------------------------------------------------------------------
# GIS query
# ---------------------------------------------------------------------------

def _like_patterns(parsed_individual, company_tokens) -> list[str]:
    """Build owner-field LIKE patterns in the order GIS most-likely stores
    them (surname first for individuals)."""
    pats: list[str] = []
    if parsed_individual:
        surname, given = parsed_individual
        s = surname.replace("'", "''")
        if given:
            g = given[0].replace("'", "''")
            pats.append(f"%{s}%{g}%")   # surname-first (matches GIS)
            pats.append(f"%{g}%{s}%")   # given-first (some layers)
        pats.append(f"%{s}%")            # surname-only broad fallback
    elif company_tokens:
        toks = sorted(company_tokens, key=len, reverse=True)
        t0 = toks[0].replace("'", "''")
        if len(toks) >= 2:
            t1 = toks[1].replace("'", "''")
            pats.append(f"%{t0}%{t1}%")
            pats.append(f"%{t1}%{t0}%")
        pats.append(f"%{t0}%")
    return pats


async def _query_owner(
    c: httpx.AsyncClient, base_url: str, owner_field: str, patterns: list[str],
) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for pat in patterns:
        where = f"UPPER({owner_field}) LIKE '{pat}'"
        try:
            r = await c.get(base_url, params={
                "where": where, "outFields": "*", "returnGeometry": "true",
                "outSR": "4326", "resultRecordCount": "25", "f": "json",
            }, timeout=25.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            for f in data.get("features", []):
                attrs = dict(f.get("attributes", {}) or {})
                oid = attrs.get("OBJECTID") or attrs.get("FID")
                if oid is not None and oid in seen:
                    continue
                if oid is not None:
                    seen.add(oid)
                geom = f.get("geometry") or {}
                cx = cy = None
                if "x" in geom and "y" in geom:
                    cx, cy = geom["x"], geom["y"]
                elif geom.get("rings"):
                    pts = [p for ring in geom["rings"] for p in ring]
                    if pts:
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                if cx is not None and cy is not None:
                    attrs["_centroid"] = (cy, cx)
                out.append(attrs)
            if out:
                break   # most-specific pattern that returns rows wins
        except (httpx.HTTPError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Match scoring -- pick the unique best owner row
# ---------------------------------------------------------------------------

def _score_individual(parsed, owner_set: set[str]) -> int:
    """0 = not a match.  Else surname(2) + given-token hits.  Requires surname
    AND >=1 given token to register any score."""
    surname, given = parsed
    if surname not in owner_set:
        return 0
    given_hits = sum(1 for g in given if g in owner_set)
    if given:
        if given_hits == 0:
            return 0
        return 2 + given_hits
    # No given tokens parsed from defendant (rare): surname-only, weak.
    return 1


def _score_company(tokens: list[str], owner_set: set[str]) -> int:
    if not tokens:
        return 0
    hits = sum(1 for t in tokens if t in owner_set)
    # Require every distinctive company token present.
    return hits if hits == len(tokens) else 0


def _best_unique(
    rows: list[dict[str, Any]], owner_field: str, parsed_ind, comp_tokens,
) -> Optional[dict[str, Any]]:
    """Return the single best-scoring row iff it is a clear, unique winner that
    meets the per-type threshold; else None."""
    scored: list[tuple[int, dict[str, Any]]] = []
    for a in rows:
        owner = str(a.get(owner_field) or "")
        oset = _owner_tokens(owner)
        if parsed_ind:
            sc = _score_individual(parsed_ind, oset)
            threshold = 3      # surname(2)+>=1 given
        else:
            sc = _score_company(comp_tokens, oset)
            threshold = max(1, len(comp_tokens))
        if sc >= threshold:
            scored.append((sc, a))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) == 1:
        return scored[0][1]
    # Unique winner: top score strictly beats runner-up. (Two different rows
    # with the same top score = ambiguous -> commit nothing.)
    if scored[0][0] > scored[1][0]:
        return scored[0][1]
    # Tie at top: only safe if every tied row is the SAME parcel (same owner
    # holding one parcel returned twice) -- detect by identical centroid.
    top = scored[0][0]
    tied = [a for s, a in scored if s == top]
    cents = {a.get("_centroid") for a in tied if a.get("_centroid")}
    if len(cents) == 1 and None not in cents:
        return tied[0]
    return None


# ---------------------------------------------------------------------------
# Address write with detected-field fallback
# ---------------------------------------------------------------------------

def _inject_site_alias(attrs: dict[str, Any], site_field: Optional[str]) -> None:
    """If the detected situs field isn't one _populate_from_attrs knows, copy
    its value into a recognized alias key so the standard writer picks it up."""
    if not site_field:
        return
    # Already covered by an alias?
    if _pick(attrs, FIELD_ALIASES["site_address"]):
        return
    val = attrs.get(site_field)
    if val in (None, "", " ", 0, "0", "<Null>"):
        # case-insensitive lookup
        for k, v in attrs.items():
            if k.lower() == site_field.lower():
                val = v
                break
    if val not in (None, "", " ", 0, "0", "<Null>"):
        attrs["SITUS_ADDR"] = str(val).strip()  # SITUS_ADDR is in the alias set


# ---------------------------------------------------------------------------
# County endpoint resolution
# ---------------------------------------------------------------------------

def _endpoint_for(li: Listing) -> Optional[str]:
    if not li.county or not li.state:
        return None
    county = li.county.replace(" County", "").strip()
    for suffix in (", NC", ", SC", ",NC", ",SC"):
        if county.upper().endswith(suffix):
            county = county[: -len(suffix)].strip()
    county = county.split(",")[0].strip().title()
    if li.state == "SC":
        layer = SC_LAYER.get(county)
        return f"{SCDOT_BASE}/{layer}/query" if layer else None
    if li.state == "NC":
        cfg = NC_GIS.get(county)
        return cfg["url"] if cfg else None
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def enrich_addresses_from_owner_v2(
    listings: list[Listing], concurrency: int = 6,
) -> dict[str, int]:
    """Resolve property addresses by defendant/owner name against the county
    GIS owner field, for listings that still lack a street address.

    Returns a stats dict.  Conservative: writes only on a unique confident
    match; reuses _populate_from_attrs so placeholder filtering / parcel /
    spec backfill behave exactly like the rest of the pipeline.
    """
    targets = [
        li for li in listings
        if li.defendant and li.county and li.state in ("NC", "SC")
        and not (li.street_address or "").strip()
        and li.source != "national.courtlistener_bankruptcy"
    ]
    stats = {
        "targets": len(targets), "queried": 0, "no_endpoint": 0,
        "no_owner_field": 0, "no_rows": 0, "ambiguous": 0,
        "address_filled": 0, "parcel_or_specs_only": 0,
    }
    if not targets:
        log.info("addr_owner_v2.no_targets")
        return stats

    log.info("addr_owner_v2.start", target_count=len(targets), of_total=len(listings))

    sem = asyncio.Semaphore(concurrency)
    owner_field_cache: dict[str, Optional[str]] = {}
    site_field_cache: dict[str, Optional[str]] = {}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        base = _endpoint_for(li)
        if not base:
            stats["no_endpoint"] += 1
            return

        if base not in owner_field_cache:
            owner_field_cache[base] = await _detect_owner_field_v2(c, base)
        owner_field = owner_field_cache[base]
        if not owner_field:
            stats["no_owner_field"] += 1
            return
        if base not in site_field_cache:
            site_field_cache[base] = await _detect_site_field(c, base)
        site_field = site_field_cache[base]

        # Parse every party; try each until one resolves.
        for party in _split_joint(li.defendant):
            if _is_company(party):
                parsed_ind, comp_tokens = None, _company_tokens(party)
            else:
                parsed_ind, comp_tokens = _parse_individual(party), []
            patterns = _like_patterns(parsed_ind, comp_tokens)
            if not patterns:
                continue

            async with sem:
                stats["queried"] += 1
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

            _inject_site_alias(best, site_field)
            had_addr = bool((li.street_address or "").strip())
            filled = _populate_from_attrs(li, best)
            now_addr = bool((li.street_address or "").strip())
            if now_addr and not had_addr:
                stats["address_filled"] += 1
                li.raw.setdefault("addr_owner_v2", {})["matched_owner"] = str(
                    best.get(owner_field) or "")
                return
            if filled:
                stats["parcel_or_specs_only"] += 1
                return

    async with client(timeout=25.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("addr_owner_v2.done", **stats)
    return stats
