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
import re
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
from .name_normalize import (
    is_entity,
    like_patterns,
    match_owner,
    middle_conflict,
    person_orderings,
)

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


# ---------------------------------------------------------------------------
# NC OneMap — statewide owner-name index (verified live 2026-08-03)
# ---------------------------------------------------------------------------
# 5,938,639 parcels across all 100 NC counties, free, public, no auth, no robots
# Disallow (the host serves no robots.txt at all). It is the ONLY NC owner-name
# surface that covers counties enrichment_arcgis.NC_GIS never wired (NC_GIS has
# 18 of 100), and a second chance for the 18 it did.
#
# GOTCHA 1 — cntyname is stored Title Case with INTERNAL capitals. `cntyname =
#   'BUNCOMBE'` returns 0, and Python's `.title()` (which _county_clean applies)
#   turns "McDowell" into "Mcdowell", which ALSO returns 0. That is exactly why a
#   prior pass measured McDowell as absent; it is present with 33,449 parcels.
#   Always compare with `UPPER(cntyname) = 'MCDOWELL'`, never a literal.
# GOTCHA 2 — the county predicate is MANDATORY. Without it an owner LIKE runs
#   against 5.9M statewide rows and returns same-named strangers from the far
#   side of the state, which the strict matcher would happily accept.
# GOTCHA 3 — ownname joins co-owners with ';' ('MANLY DAVID T;DILLON MARGARET'),
#   handled by the ';' branch in name_normalize._JOINT_SPLIT_RE plus
#   _owner_segments below, so a lead who is the SECOND owner still matches.
# GOTCHA 4 — ownlast/ownfrst exist in the schema but are EMPTY statewide
#   (measured 0 populated rows in Buncombe/Henderson/McDowell/Brunswick/Pender/
#   Transylvania/Cleveland). Do not build a structured search on them.
NC_ONEMAP_URL = (
    "https://services.nconemap.gov/secure/rest/services/"
    "NC1Map_Parcels/FeatureServer/1/query"
)
# Enumerated, never '*'. Deliberately EXCLUDES every owner-mailing column
# (mailadd/munit/mcity/mstate/mzip/maddr*) — the resolver's job is name -> parcel,
# and not requesting them is a stronger guarantee than stripping them after.
NC_ONEMAP_FIELDS = (
    "parno,ownname,ownname2,siteadd,scity,szip,parval,landval,improvval,"
    "gisacres,structyear,cntyname,saledatetx,parusedesc"
)

# ---------------------------------------------------------------------------
# Buncombe owner index — structured LastName/FirstName spine (live 2026-08-03)
# ---------------------------------------------------------------------------
# Buncombe publishes its appraisal roll as two normalized tables, which together
# beat a LIKE against a single concatenated owner string:
#   Owner Lookup 2025   544,665 rows  ID, LastName, FirstName, ThirdName, SuffixName
#   Parcel Owners 2025  196,836 rows  Pin, OwnerId, Primary_
# Chain: (LastName=, FirstName LIKE) -> ID -> OwnerId -> Pin -> NC OneMap parno.
#
# WHY IT BEATS THE LIKE PATH: every co-owner is her OWN row. 'MARGARET DILLON'
# on parcel 060502683700000 is invisible to an ownname search (primary_party
# reads only 'MANLY DAVID T') but is a first-class row here. And surname/given
# are separate columns, so 'SMITH JOHN' cannot collide with 'SMITHIES JOHN W'
# the way '%SMITH%JOHN%' does.
#
# PRIVACY: only ID + name columns are requested. The lookup also carries owner
# mailing Address1/Address2/City/State/Zip; those are NEVER in outFields.
_BUNCOMBE_BASE = "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/ArcGIS/rest/services"
BUNCOMBE_OWNER_LOOKUP_URL = (
    f"{_BUNCOMBE_BASE}/Real%20Estate%20Appraisal%20Owner%20Lookup%202025/FeatureServer/0/query"
)
BUNCOMBE_PARCEL_OWNERS_URL = (
    f"{_BUNCOMBE_BASE}/Real%20Estate%20Appraisal%20Parcel%20Owners%202025/FeatureServer/0/query"
)
BUNCOMBE_OWNER_FIELDS = "ID,LastName,FirstName,ThirdName,SuffixName"
# Owner rows to consider per surname/given probe, and parcels per matched owner.
# 544,665 owner rows means a common surname alone would page forever; the strict
# matcher only ever commits a unique parcel, so a bounded window is sufficient.
_BUNCOMBE_OWNER_ROWS = 200
_BUNCOMBE_PARCEL_ROWS = 60


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

# House numbers that are a county's "this parcel has no address" sentinel, not a
# real number. Buncombe writes '99999 PEARSON  LN' on 17,788 of its 134,741 NC
# OneMap rows (13%, and every such row statewide is Buncombe's) — raw land, ROW,
# easements. Committing one would put a nonexistent street number in front of
# outreach, so the situs is rejected and the lead keeps its parcel id only.
_PLACEHOLDER_HOUSE_NOS = {"99999", "9999", "00000", "0"}


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
    if toks[0] in _PLACEHOLDER_HOUSE_NOS:
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


#: Column names never worth sampling, whatever a layer offers. This probe is the
#: ONE wildcard query left in the codebase, so it is also the one place a county
#: could hand us an SSN/DOB/contact column we never asked for. Two counties in
#: this footprint already publish such columns.
_SAMPLE_FORBIDDEN = re.compile(
    r"ssn|social_?sec|drivers?_?lic|dl_?num|tcdlc|date_?of_?birth|\bdob\b|birth"
    r"|poc_?phone|poc_?email|e_?mail|phone|account_?(no|num)|acct_?(no|num)",
    re.I,
)


async def _sample_row(c: httpx.AsyncClient, base: str) -> Optional[dict[str, Any]]:
    """One-row schema probe for layers whose metadata exposes no field list.

    outFields="*" is unavoidable HERE and only here: the whole reason this
    fallback exists is that the layer's own metadata returns an empty ``fields``
    array (SCDOT-class layers), so there is no way to name the columns in
    advance. _detect_from_sample needs the VALUES too, not just the keys, because
    it picks the owner/situs columns by value shape as well as name.

    It is bounded instead: ONE row, ONE layer, cached per base URL, and every
    column whose name looks like an identifier or personal contact detail is
    dropped before any caller sees it. Nothing from this probe is written to a
    Listing - it is used solely to learn which two column names to query later.
    """
    try:
        r = await c.get(base, params={
            "where": "1=1", "outFields": "*", "returnGeometry": "false",
            "resultRecordCount": "1", "f": "json",
        }, timeout=20.0)
        if r.status_code != 200:
            return None
        feats = r.json().get("features") or []
        if feats and feats[0].get("attributes"):
            return {k: v for k, v in feats[0]["attributes"].items()
                    if not _SAMPLE_FORBIDDEN.search(str(k))}
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


def _county_upper(li: Listing) -> str:
    """County for a SQL literal, WITHOUT .title().

    _county_clean applies .title(), which maps 'McDowell' -> 'Mcdowell'. NC OneMap
    stores 'McDowell', so a Title-Cased literal silently returns 0 rows — the
    documented reason a prior pass concluded McDowell was missing. Everything
    downstream compares with UPPER(cntyname), so casing never matters again.
    """
    c = (li.county or "").replace(" County", "").strip()
    for sfx in (", NC", ", SC", ",NC", ",SC"):
        if c.upper().endswith(sfx):
            c = c[: -len(sfx)].strip()
    return " ".join(c.split(",")[0].split()).upper()


def _nc_onemap_cfg(li: Listing) -> dict[str, Any]:
    """Statewide NC OneMap cfg, county-scoped. Always safe to append to a plan."""
    return {
        "kind": "gis_like",
        "base": NC_ONEMAP_URL,
        "owner_field": "ownname",
        "situs_field": "siteadd",
        "parcel_field": "parno",
        "mail_fields": (),          # mailing columns are never requested at all
        "out_fields": NC_ONEMAP_FIELDS,
        "where_prefix": f"UPPER(cntyname) = '{_county_upper(li).replace(chr(39), chr(39) * 2)}'",
        "pinned": True,
        "county": _county_clean(li),
        "label": "nc_onemap",
    }


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
                "kind": "gis_like",
                "base": pinned["url"], "owner_field": pinned["owner"],
                "situs_field": pinned["situs"], "parcel_field": pinned["parcel"],
                "mail_fields": pinned["mail"], "pinned": True, "county": county,
                "label": f"sc_pinned_{county.lower()}",
            }
    base = _endpoint_for(li)
    if not base:
        return None
    return {
        "kind": "gis_like",
        "base": base, "owner_field": None, "situs_field": None,
        "parcel_field": None, "mail_fields": (), "pinned": False,
        "county": county, "label": "county_layer",
    }


def _endpoint_plan(li: Listing) -> list[dict[str, Any]]:
    """Ordered chain of owner-search backends to try for one lead, best first.

    A single endpoint was the real shape of the ~28.7% ceiling: when the county
    layer had no row for a name, the lead was done. The chain gives every NC lead
    a statewide second look, and Buncombe a structured index that finds owners the
    concatenated-string search cannot see at all.

    Ordering is deliberate — most authoritative and most specific first, so the
    cheap local answer wins and the statewide scan is only paid for on a miss:
      Buncombe NC : structured owner index -> county layer -> NC OneMap
      other NC    : county layer (if wired) -> NC OneMap
      SC          : unchanged (pinned county layer, or nothing)
    """
    plan: list[dict[str, Any]] = []
    county = _county_clean(li)

    if li.state == "NC" and county == "Buncombe":
        plan.append({
            "kind": "owner_index",
            "base": BUNCOMBE_OWNER_LOOKUP_URL,
            "owner_field": "ownname",     # adjudicated on the OneMap parcel row
            "situs_field": "siteadd",
            "parcel_field": "parno",
            "mail_fields": (),
            "pinned": True,
            "county": county,
            "label": "buncombe_owner_index",
        })

    first = _endpoint_cfg(li)
    if first:
        plan.append(first)

    if li.state == "NC" and _county_upper(li):
        onemap = _nc_onemap_cfg(li)
        if not any(p["base"] == onemap["base"] for p in plan):
            plan.append(onemap)

    return plan


def _in_core(li: Listing) -> bool:
    # Resolvable = SOME wired owner-search backend covers the lead's county. For
    # SC that is still the pinned county layer (or nothing). For NC it is now
    # every county, because NC OneMap carries all 100 — the 82 counties
    # enrichment_arcgis.NC_GIS never wired stop falling out as no_endpoint.
    return bool(_endpoint_plan(li))


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


def _owner_segments(owner: str) -> list[str]:
    """Co-owner strings inside one GIS owner cell, first party first.

    NC OneMap packs every owner of a parcel into `ownname` separated by ';'
    ('MANLY DAVID T;DILLON MARGARET'). match_owner only ever reads the FIRST
    party, so without this a lead who is the second-listed owner — routinely a
    spouse, and exactly the person a divorce or probate lead names — can never
    match her own parcel. Cells with no ';' yield a single segment, so every
    existing county layer behaves identically.
    """
    raw = str(owner or "")
    if ";" not in raw:
        return [raw] if raw.strip() else []
    return [seg.strip() for seg in raw.split(";") if seg.strip()]


def _strict_matches(
    rows: list[dict[str, Any]], owner_field: str, name: str,
) -> list[tuple[str, dict[str, Any]]]:
    """(match_kind, row) for every row whose owner STRICTLY matches `name`.

    Strictness lives in name_normalize.match_owner: exact normalized token-set
    equality, or surname-in-surname-position + first-name-in-first-name-position.
    A bag-of-tokens rule accepted roughly one wrong person per three "unique"
    matches on this cohort; positional matching removes them.

    Each ';'-delimited co-owner in the cell is adjudicated separately, at full
    strictness. Widening WHICH strings are compared is not the same as loosening
    the comparison — every segment still has to clear match_owner outright.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        for segment in _owner_segments(str(row.get(owner_field) or "")):
            kind = match_owner(name, segment)
            if kind:
                out.append((kind, row))
                break
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
# Query providers
# ---------------------------------------------------------------------------

def _sql_quote(s: str) -> str:
    return str(s or "").replace("'", "''")


async def _arcgis_rows(
    c: httpx.AsyncClient,
    base: str,
    where: str,
    out_fields: str,
    *,
    page: int,
    max_rows: int,
    order_by: str,
) -> list[dict[str, Any]]:
    """Paged ArcGIS attribute fetch. Enumerated outFields — never '*'.

    Pages with resultOffset + resultRecordCount and an explicit orderByFields, so
    the window is stable across pages instead of silently re-serving page 1.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < max_rows:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "false",
            "orderByFields": order_by,
            "resultOffset": str(offset),
            "resultRecordCount": str(min(page, max_rows - offset)),
            "f": "json",
        }
        try:
            r = await c.get(base, params=params, timeout=30.0)
            if r.status_code != 200:
                break
            data = r.json()
        except (httpx.HTTPError, ValueError):
            break
        if not isinstance(data, dict) or "error" in data:
            break
        feats = data.get("features") or []
        if not feats:
            break
        rows.extend(dict(f.get("attributes") or {}) for f in feats)
        if len(feats) < int(params["resultRecordCount"]) and not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return rows


async def _query_owner_scoped(
    c: httpx.AsyncClient, cfg: dict[str, Any], patterns: list[str],
) -> list[dict[str, Any]]:
    """Owner LIKE search that can carry a mandatory extra predicate.

    The shared _query_owner in enrichment_address_owner_v2 builds a bare
    `UPPER(owner) LIKE '...'` and asks for outFields=*. Neither is usable against
    NC OneMap: the county predicate is REQUIRED there (without it '%SMITH%JOHN%'
    scans 5.9M statewide rows and hands the strict matcher a same-named stranger
    from three hundred miles away), and '*' is barred. Layers with no
    `where_prefix` fall through to the original helper, unchanged.
    """
    prefix = cfg.get("where_prefix")
    if not prefix:
        return await _query_owner(c, cfg["base"], cfg["owner_field"], patterns)

    owner_field = cfg["owner_field"]
    out_fields = cfg.get("out_fields") or owner_field
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for pat in patterns:
        where = f"{prefix} AND UPPER({owner_field}) LIKE '{pat}'"
        rows = await _arcgis_rows(
            c, cfg["base"], where, out_fields,
            page=25, max_rows=25, order_by=cfg.get("parcel_field") or owner_field,
        )
        for attrs in rows:
            key = attrs.get(cfg.get("parcel_field") or "") or str(sorted(attrs.items()))
            if key in seen:
                continue
            seen.add(key)
            out.append(attrs)
        if out:
            break   # most-specific pattern that returns rows wins
    return out


def _drop_middle_name_conflicts(
    rows: list[dict[str, Any]], person: Any,
) -> list[dict[str, Any]]:
    """Remove owner rows whose spelled-out middle name contradicts the lead's.

    WHY THIS BACKEND NEEDS IT AND THE LIKE PATH DOES NOT: the structured probe
    asks for EVERY 'MCCURRY, JAMES%' in the county on purpose. If only one of
    those men happens to own a parcel today, the chain hands the matcher exactly
    one candidate and it commits as a unique 'strong' hit — but the uniqueness
    came from who owns property, not from the name being distinctive. Measured on
    the live board, 2 of the first 6 Buncombe resolutions were this shape
    ('James Rodney Mccurry' -> 'MCCURRY JAMES BRUCE').

    ThirdName is the structured middle name the concatenated ownname string does
    not reliably expose, so the contradiction can be caught BEFORE a candidate is
    generated — and a different, genuinely-matching James McCurry can still win.

    Same evidentiary bar as name_normalize.middle_conflict: only a spelled-out
    middle on BOTH sides can contradict. A blank ThirdName or a bare initial
    ('R') cannot disagree with anything and is always kept.
    """
    lead_middles = {t for t in getattr(person, "given", ())[1:] if len(t) > 1}
    if not lead_middles:
        return rows
    kept: list[dict[str, Any]] = []
    for r in rows:
        third = str(r.get("ThirdName") or "").strip().upper()
        if len(third) > 1 and third.isalpha() and third not in lead_middles:
            continue
        kept.append(r)
    return kept


async def _query_buncombe_owner_index(
    c: httpx.AsyncClient, cfg: dict[str, Any], party: str,
) -> list[dict[str, Any]]:
    """Buncombe structured spine: (LastName, FirstName) -> ID -> Pin -> parcel row.

    Returns NC OneMap parcel rows so the SAME strict matcher and the SAME
    ambiguity rule adjudicate the result — this is a candidate GENERATOR, not a
    second matching policy. It never decides anything on its own.

    Both name orderings from person_orderings are probed, because a court
    defendant string is genuinely ambiguous ('CASEY WILLIAM' is either).
    Companies are skipped: the lookup is a person table (LastName/FirstName), and
    an entity's name does not decompose into surname + given.
    """
    if is_entity(party):
        return []
    ids: list[int] = []
    for person in person_orderings(party)[:2]:
        if not person.given:
            continue
        where = (
            f"UPPER(LastName) = '{_sql_quote(person.surname)}' "
            f"AND UPPER(FirstName) LIKE '{_sql_quote(person.given[0])}%'"
        )
        rows = await _arcgis_rows(
            c, BUNCOMBE_OWNER_LOOKUP_URL, where, BUNCOMBE_OWNER_FIELDS,
            page=200, max_rows=_BUNCOMBE_OWNER_ROWS, order_by="ID",
        )
        rows = _drop_middle_name_conflicts(rows, person)
        for r in rows:
            oid = r.get("ID")
            if isinstance(oid, (int, float)) and int(oid) not in ids:
                ids.append(int(oid))
        if ids:
            break
    if not ids:
        return []

    # ID -> Pin. Most of the 544,665 owner rows are historical and own nothing
    # today, so an empty result here is a real answer ("this person holds no
    # Buncombe parcel"), not a failure.
    pins: list[str] = []
    for chunk in (ids[i:i + 100] for i in range(0, len(ids), 100)):
        rows = await _arcgis_rows(
            c, BUNCOMBE_PARCEL_OWNERS_URL,
            f"OwnerId IN ({','.join(str(i) for i in chunk)})",
            "Pin,OwnerId,Primary_",
            page=200, max_rows=_BUNCOMBE_PARCEL_ROWS, order_by="Pin",
        )
        for r in rows:
            pin = str(r.get("Pin") or "").strip()
            if pin and pin not in pins:
                pins.append(pin)
        if len(pins) >= _BUNCOMBE_PARCEL_ROWS:
            break
    if not pins:
        return []

    # Pin -> the parcel row that actually carries situs/value. County-scoped so a
    # Pin collision with another county's parno cannot resolve to the wrong state.
    quoted = ",".join(f"'{_sql_quote(p)}'" for p in pins[:_BUNCOMBE_PARCEL_ROWS])
    return await _arcgis_rows(
        c, NC_ONEMAP_URL,
        f"UPPER(cntyname) = 'BUNCOMBE' AND parno IN ({quoted})",
        NC_ONEMAP_FIELDS,
        page=100, max_rows=_BUNCOMBE_PARCEL_ROWS, order_by="parno",
    )


# cfg label -> the stats key that counts a resolution from that backend.
_BACKEND_STAT = {
    "buncombe_owner_index": "resolved_buncombe_index",
    "nc_onemap": "resolved_nc_onemap",
    "county_layer": "resolved_county_layer",
}


def _backend_stat_key(label: str) -> str:
    if label in _BACKEND_STAT:
        return _BACKEND_STAT[label]
    if label.startswith("sc_pinned_"):
        return "resolved_sc_pinned"
    return "resolved_other"


async def _candidate_rows(
    c: httpx.AsyncClient, cfg: dict[str, Any], party: str, patterns: list[str],
) -> list[dict[str, Any]]:
    """Dispatch one backend in the plan to its rows."""
    if cfg.get("kind") == "owner_index":
        return await _query_buncombe_owner_index(c, cfg, party)
    return await _query_owner_scoped(c, cfg, patterns)


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
        # Which backend in the chain actually produced each resolution, so the
        # next measurement can tell a real gain from a reshuffle.
        "resolved_buncombe_index": 0, "resolved_nc_onemap": 0,
        "resolved_county_layer": 0, "resolved_sc_pinned": 0, "resolved_other": 0,
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

        plan = _endpoint_plan(li)
        if not plan:
            stats["no_endpoint"] += 1
            _mark(li, "no_endpoint", queried=False)
            return

        name = _lead_name(li)
        if not isinstance(li.raw, dict):
            li.raw = {}

        # A lead is only "queried" (and so skipped on re-runs) if at least ONE
        # backend actually answered. If every backend in the chain bailed for an
        # environmental reason, the lead must stay retryable.
        queried_any = False
        last_env: Optional[tuple[str, dict[str, Any]]] = None

        for cfg in plan:
            base = cfg["base"]

            dead = await _health(c, base)
            if dead:
                stats["endpoint_dead"] += 1
                last_env = ("endpoint_dead", {"endpoint": base, "reason": dead})
                continue

            owner_field = cfg["owner_field"]
            situs_field = cfg["situs_field"]
            if not cfg["pinned"]:
                if base not in field_cache:
                    field_cache[base] = await _resolve_fields(c, base)
                owner_field, situs_field = field_cache[base]
            if not owner_field:
                stats["no_owner_field"] += 1
                last_env = ("no_owner_field", {"endpoint": base})
                continue

            for party in _split_joint(name):
                patterns = like_patterns(party)
                if not patterns:
                    continue

                # Re-check the budget HERE, not just at task entry: gather()
                # dispatches every target at once, so without this a long queue of
                # leads serialized behind a slow host would all sail past the entry
                # check and run for far longer than _BUDGET_S.
                if time.monotonic() - t0 > _BUDGET_S:
                    stop.set()
                    stats["budget_hit"] = 1
                    if not queried_any:
                        _mark(li, "budget_bail", queried=False)
                    return

                async with sem:
                    stats["attempted"] += 1
                    rows = await _candidate_rows(c, cfg, party, patterns)
                queried_any = True
                if not rows:
                    continue

                hits = _strict_matches(rows, owner_field, party)
                if not hits:
                    continue

                # Several parcels for one owner: real and common (a landlord
                # holding multiple lots). Keep every candidate on the lead and
                # FLAG it — never pick one at random and present it as the
                # address. Mailing the wrong person is the failure that matters,
                # so an ambiguous hit STOPS the chain: a later backend finding one
                # parcel would not make the several this one found go away.
                parcels = {
                    _row_parcel(r, cfg.get("parcel_field")) or str(r.get("OBJECTID") or i)
                    for i, (_k, r) in enumerate(hits)
                }
                if len(hits) > 1 and len(parcels) > 1:
                    stats["ambiguous"] += 1
                    _mark(
                        li, "ambiguous_multi_parcel", queried=True,
                        query_name=party, match_count=len(hits),
                        backend=cfg.get("label"),
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
                #   * a bare 'CITY ST' line (no house number / street word), or a
                #     '99999 ...' no-address sentinel, as situs,
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
                    stats[_backend_stat_key(cfg.get("label") or "")] += 1
                    if now_addr and not had_addr:
                        stats["address_filled"] += 1
                    if now_parcel and not had_parcel:
                        stats["parcel_filled"] += 1
                    if li.market_value and not had_value:
                        stats["value_filled"] += 1
                    if li.living_sqft and not had_sqft:
                        stats["sqft_filled"] += 1
                    # Same surname + first name but a provably different
                    # spelled-out middle name. Still committed (a surname+firstname
                    # hit in the right county is real signal) but flagged and
                    # counted so review can see the doubt before outreach.
                    conflict = middle_conflict(party, matched_owner)
                    if conflict:
                        stats["middle_conflict"] += 1
                    _mark(
                        li, kind, queried=True, matched_owner=matched_owner,
                        from_field="owner_name" if li.owner_name == name else "defendant",
                        query_name=party, endpoint=base, backend=cfg.get("label"),
                        middle_conflict=conflict,
                    )
                    return
                # Matched the owner but this backend carried no usable situs or
                # parcel. Fall through to the next backend rather than giving up —
                # that is the whole point of the chain.
                stats["no_rows"] += 1
                last_env = ("%s_no_parcel_data" % kind,
                            {"matched_owner": matched_owner, "query_name": party,
                             "backend": cfg.get("label")})

        if queried_any:
            # Reached at least one backend, no strict match anywhere in the chain
            # -> mark queried so re-runs skip it.
            if last_env and last_env[0].endswith("_no_parcel_data"):
                _mark(li, last_env[0], queried=True, **last_env[1])
            else:
                _mark(li, "no_match", queried=True, query_name=name,
                      backends=[c_.get("label") for c_ in plan])
            return
        # Every backend bailed environmentally — stay retryable.
        conf, extra = last_env or ("no_endpoint", {})
        _mark(li, conf, queried=False, **extra)

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
