"""SC lis-pendens address resolver — confident GIS match by case# + defendant.

Runs every weekly run on SC lis-pendens listings whose ``street_address`` is
still a synthesized placeholder ("Lis Pendens 2026-CP-04-12345 — Smith John").
Decodes the authoritative county from the case-number prefix (SC venue
follows situs by statute), queries SCDOT GIS by defendant in that county,
and commits a real address only when the match is confident.

Confidence policy (intentionally conservative — investors will use this data):

  * Defendant tokenized; common stopwords (LLC, INC, JR, AS, ET AL,
    PERSONAL REPRESENTATIVE, …) dropped.
  * For LLC / company defendants: every distinctive token must appear in
    the owner-name string.
  * For individual defendants: surname + at least one other distinctive
    token (typically first name) must match.
  * Multiple parcels for same owner → ambiguous; commit nothing, record
    candidates in ``raw.lis_pendens_resolution.candidates`` for review.
  * Fiduciary defendants (PR, Trustee, Executor) → never commit address;
    parcel of record may not be the estate property under lien.

Address policy:

  * Real situs field (when available) → commit.
  * Mailing fallback for non-fiduciary individuals when mailing has a
    street number (not P.O. box) AND owner-occupancy flag is set
    (or county GIS exposes no occupancy flag — most don't).
  * Otherwise: leave placeholder; record parcel_id + centroid lat/lng.

Defense-in-depth for the weekly run: also re-tags ``li.county`` from the
case-number prefix when it disagrees with the case venue. This catches
the legacy data where a now-fixed cross-county owner search rewrote the
county to a same-name match in the wrong county.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# SC case-number prefix → county. Authoritative for venue under SC Code §15-11-10.
SC_COUNTY_BY_CODE = {
    "01": "Abbeville", "02": "Aiken", "03": "Allendale", "04": "Anderson",
    "05": "Bamberg", "06": "Barnwell", "07": "Beaufort", "08": "Berkeley",
    "09": "Calhoun", "10": "Charleston", "11": "Cherokee", "12": "Chester",
    "13": "Chesterfield", "14": "Clarendon", "15": "Colleton", "16": "Darlington",
    "17": "Dillon", "18": "Dorchester", "19": "Edgefield", "20": "Fairfield",
    "21": "Florence", "22": "Georgetown", "23": "Greenville", "24": "Greenwood",
    "25": "Hampton", "26": "Horry", "27": "Jasper", "28": "Kershaw",
    "29": "Lancaster", "30": "Laurens", "31": "Lee", "32": "Lexington",
    "33": "Marion", "34": "Marlboro", "35": "McCormick", "36": "Newberry",
    "37": "Oconee", "38": "Orangeburg", "39": "Pickens", "40": "Richland",
    "41": "Saluda", "42": "Spartanburg", "43": "Sumter", "44": "Union",
    "45": "Williamsburg", "46": "York",
}

# SCDOT statewide MapServer + per-county layer ID.
SCDOT_BASE = "https://smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer"
SC_LAYER = {
    "Abbeville": 1, "Aiken": 2, "Allendale": 3, "Anderson": 4, "Bamberg": 5,
    "Barnwell": 6, "Beaufort": 7, "Berkeley": 8, "Calhoun": 9, "Charleston": 10,
    "Cherokee": 11, "Chester": 12, "Chesterfield": 13, "Clarendon": 14, "Colleton": 15,
    "Darlington": 16, "Dillon": 17, "Dorchester": 18, "Edgefield": 19, "Fairfield": 20,
    "Florence": 21, "Georgetown": 22, "Greenville": 23, "Greenwood": 24, "Hampton": 25,
    "Horry": 26, "Jasper": 27, "Kershaw": 28, "Lancaster": 29, "Laurens": 30,
    "Lee": 31, "Lexington": 32, "Marion": 33, "Marlboro": 34, "McCormick": 35,
    "Newberry": 36, "Oconee": 37, "Orangeburg": 38, "Pickens": 39, "Richland": 40,
    "Saluda": 41, "Spartanburg": 42, "Sumter": 43, "Union": 44, "Williamsburg": 45,
    "York": 46,
}

# Per-county SCDOT field schemas (vary widely across counties).
COUNTY_SCHEMA: dict[str, dict[str, Any]] = {
    "Anderson": {
        "owner": ("OWNER",), "situs": (), "situs_parts": (),
        "mailing": ("OWNER_ADDR",), "city": ("CITY",), "zip": ("ZIPCODE",),
        "parcel": ("TMS",), "owner_occ": (),
    },
    "Cherokee": {
        "owner": ("SHEET1__Na",), "situs": (), "situs_parts": (),
        "mailing": ("SHEET1___1",), "city": ("SHEET1___2",),
        "zip": ("SHEET1__Zi", "ZipCode"), "parcel": ("ParcelPoly",), "owner_occ": (),
    },
    "Oconee": {
        "owner": ("OWNERNAME", "Owner"), "situs": ("FullAdd",),
        "situs_parts": ("HOUSE_NO", "STREET_NAM", "TYPE"),
        "mailing": ("ADDRESS2",), "city": ("CITY",), "zip": ("ZIP",),
        "parcel": ("TMS_NUMBER", "PARCEL_NO"), "owner_occ": (),
    },
    "Pickens": {
        "owner": ("NAME1", "OwnerAll"), "situs": ("LOCADD",), "situs_parts": (),
        "mailing": ("ADD1",), "city": ("LOCCITY", "CITY"),
        "zip": ("LOCZIP", "ZIP"), "parcel": ("PIN",), "owner_occ": (),
    },
    "Laurens": {
        "owner": ("Name1", "Owner", "OwneAll"), "situs": ("Property_A",),
        "situs_parts": ("Street_Num", "Street_Nam"),
        "mailing": ("Address1",), "city": ("Mailing_Ci", "Address2"),
        "zip": ("ZIP_Code",), "parcel": ("TMS", "TaxPIN", "Map_Number"),
        "owner_occ": ("Owner_Occu", "Residentia"),
    },
    "Union": {
        "owner": ("NAME_1", "Name", "OwnerAll"), "situs": (),
        "situs_parts": ("STREET_NUM", "STREET_NAM"),
        "mailing": ("Address_2", "ADDRESS_12"),
        "city": ("Address_3", "ADDRESS_23"), "zip": ("ZIP_CODE",),
        "parcel": ("ParcelID", "Map_Number"), "owner_occ": (),
    },
}

CASE_RE = re.compile(r"(\d{4})-CP-(\d{2})-\d+")

NAME_STOPWORDS = {
    "LLC", "L.L.C", "LLP", "INC", "CORP", "CO", "COMPANY", "LP", "LTD",
    "TRUST", "TRUSTEE", "TRUSTEES", "ESTATE", "REVOCABLE", "IRREVOCABLE",
    "JR", "SR", "II", "III", "IV", "ETAL", "ET", "AL",
    "PERSONAL", "REPRESENTATIVE", "REP", "AS",
    "THE", "AND", "OF", "FOR", "A", "AN",
    "MR", "MRS", "MS", "DR",
    "DECD", "DECEASED", "AKA", "FKA", "DBA",
}

PO_BOX_RE = re.compile(
    r"\b(P\.?\s*O\.?\s*BOX|POST\s+OFFICE\s+BOX|PO\s*BOX)\b", re.I
)

# Fiduciary defendant patterns — never commit address based on their parcels.
FIDUCIARY_RE = re.compile(
    r"\b(PERSONAL\s+REPRESENTATIVE|TRUSTEE|EXECUTOR|EXECUTRIX|ADMINISTRATOR|"
    r"ADMINISTRATRIX|GUARDIAN|CONSERVATOR|RECEIVER)\b",
    re.I,
)


def _name_tokens(s: str) -> list[str]:
    if not s:
        return []
    s = re.sub(r"[<>(),.&/]", " ", s.upper())
    s = re.sub(r"\s+(LIFE\s+ESTATE|C\s*/\s*O\s+\S+.*)$", " ", s)
    parts = re.split(r"\W+", s)
    return [p for p in parts if p and len(p) >= 2 and p not in NAME_STOPWORDS]


def _is_company(name: str) -> bool:
    up = (name or "").upper()
    return bool(re.search(r"\b(LLC|L\.L\.C|INC|CORP|COMPANY|CO\.|LP|LTD|LLP|FUND)\b", up))


def _pick(attrs: dict, keys: tuple) -> Optional[str]:
    if not isinstance(attrs, dict):
        return None
    norm = {k.lower(): v for k, v in attrs.items()}
    for k in keys:
        v = norm.get(k.lower())
        if v not in (None, "", " ", 0, "0", "<Null>"):
            return str(v).strip()
    return None


def _centroid_from_geom(geom: dict) -> Optional[tuple[float, float]]:
    if not geom:
        return None
    if "x" in geom and "y" in geom:
        return float(geom["y"]), float(geom["x"])
    rings = geom.get("rings") or []
    pts = [p for ring in rings for p in ring]
    if not pts:
        return None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


async def _query_layer(c: httpx.AsyncClient, layer: int, where: str) -> list[dict]:
    url = f"{SCDOT_BASE}/{layer}/query"
    try:
        r = await c.get(url, params={
            "where": where, "outFields": "*", "returnGeometry": "true",
            "outSR": "4326", "f": "json", "resultRecordCount": 50,
        }, timeout=30.0)
        r.raise_for_status()
        j = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for f in j.get("features", []):
        attrs = f.get("attributes", {})
        ctr = _centroid_from_geom(f.get("geometry") or {})
        if ctr:
            attrs["_centroid"] = ctr
        out.append(attrs)
    return out


def _build_where(county: str, defendant: str) -> Optional[str]:
    schema = COUNTY_SCHEMA.get(county)
    if not schema:
        return None
    tokens = _name_tokens(defendant)
    if not tokens:
        return None
    surname = tokens[0]
    surname_safe = surname.replace("'", "''")
    clauses = [f"UPPER({of}) LIKE '%{surname_safe}%'" for of in schema["owner"]]
    return " OR ".join(clauses)


def _owner_string(attrs: dict, schema: dict) -> str:
    return _pick(attrs, schema["owner"]) or ""


def _confident_match(defendant: str, owner: str) -> bool:
    """Decide whether an owner-name string is the same legal entity as the
    lis-pendens defendant. Investor-grade strict:

    Companies (LLC/Inc/Corp/…):
      Require *set equality* of distinctive tokens. Same-token-overlap
      isn't enough — "THE CLARITY COMPANY LLC" must NOT match
      "OTHER CLARITY LLC" just because they share `{CLARITY}`. Owner
      having ANY extra distinctive token signals a different entity.

    Individuals:
      Require surname plus at least one other distinctive token (typically
      first name). Surname-only is too loose for common surnames.
    """
    d_tokens = _name_tokens(defendant)
    o_tokens_list = _name_tokens(owner)
    o_tokens = set(o_tokens_list)
    d_set = set(d_tokens)
    if not d_tokens or not o_tokens:
        return False
    if _is_company(defendant):
        return d_set == o_tokens
    if len(d_tokens) >= 2:
        matches = sum(1 for t in d_tokens if t in o_tokens)
        return matches >= 2 and d_tokens[0] in o_tokens
    return d_tokens[0] in o_tokens


def _resolve_address(attrs: dict, schema: dict, defendant: str) -> dict:
    """Returns the address fields we feel confident enough to commit. Pure
    function — no I/O — for testability."""
    fiduciary = bool(FIDUCIARY_RE.search(defendant or ""))
    out: dict[str, Any] = {"_fiduciary": fiduciary}

    parcel = _pick(attrs, schema["parcel"])
    if parcel:
        out["parcel_id"] = parcel
    centroid = attrs.get("_centroid")
    if centroid:
        out["lat"] = centroid[0]
        out["lon"] = centroid[1]

    z = _pick(attrs, schema["zip"])
    if z:
        digits = re.sub(r"\D", "", z)
        # Cherokee SCDOT layer pads zip+4 with a leading zero ("0293400000"
        # → real zip 29340) — strip it.
        if len(digits) >= 9 and digits.startswith("0"):
            digits = digits[1:]
        out["zip"] = digits[:5] if len(digits) >= 5 else None

    if fiduciary:
        # Fiduciary defendants (PR, Trustee, Executor) → parcel of record
        # may not be the estate property under lien. Commit nothing.
        return out

    # Real situs path
    situs = _pick(attrs, schema["situs"])
    if not situs and schema["situs_parts"]:
        parts = [_pick(attrs, (p,)) for p in schema["situs_parts"]]
        parts = [p for p in parts if p]
        if parts:
            situs = " ".join(parts)
    if situs:
        situs = re.sub(r"\s+", " ", situs).strip()
        if situs and not re.fullmatch(r"\W*", situs) and not situs.upper().startswith("0 "):
            out["street_address"] = situs
            out["address_source"] = "situs"

    # Mailing fallback for non-fiduciary individuals.
    if "street_address" not in out and not _is_company(defendant):
        mailing = _pick(attrs, schema["mailing"])
        owner_occ = False
        for k in schema.get("owner_occ", ()):
            v = _pick(attrs, (k,))
            if v and str(v).upper().startswith(("Y", "T", "1")):
                owner_occ = True
                break
        if mailing and not PO_BOX_RE.search(mailing) and re.match(r"\s*\d", mailing):
            # If the GIS layer carries an explicit owner-occupancy flag we
            # require it to be Y. If it doesn't (most counties don't),
            # individual mailings with a street number are overwhelmingly
            # the property itself.
            if owner_occ or schema.get("owner_occ") == ():
                out["street_address"] = mailing
                out["address_source"] = "mailing_homestead" if owner_occ else "mailing"

    city = _pick(attrs, schema["city"])
    if city:
        # Some layers concatenate "CITY  STATE" — split.
        m = re.match(r"^(.*?)\s+(?:S\.?\s*C\.?|SC|N\.?\s*C\.?|NC)\s*\d{0,5}\s*$", city, re.I)
        out["city"] = (m.group(1) if m else city).strip()
    return out


def _decode_case_county(case_number: Optional[str]) -> Optional[str]:
    """Return the SC county name encoded by an SC Common Pleas case number,
    or None if the case# isn't an SC CP format or the county code is unknown."""
    if not case_number:
        return None
    m = CASE_RE.match(case_number.strip())
    if not m:
        return None
    return SC_COUNTY_BY_CODE.get(m.group(2))


def _is_target(li: Listing) -> bool:
    """Pick out SC lis-pendens listings whose state/source/case# qualify them
    for resolution. Excludes anything outside our SC + Common-Pleas-foreclosure
    venue assumption."""
    if li.state != "SC":
        return False
    if not li.case_number:
        return False
    src = (li.source or "").lower()
    if "lis_pendens" not in src and "sc_public_index" not in src:
        return False
    return _decode_case_county(li.case_number) is not None


def _is_placeholder(li: Listing) -> bool:
    sa = (li.street_address or "").strip()
    return sa.startswith("Lis Pendens ") or not sa


async def enrich_lis_pendens_addresses(listings: list[Listing]) -> dict:
    """Resolve placeholder + mistagged-county SC lis-pendens listings against
    SCDOT GIS. Returns a stats dict for the run summary."""
    targets = [li for li in listings if _is_target(li)]
    if not targets:
        log.info("lis_pendens_resolver.no_targets")
        return {"queried": 0, "address_filled": 0, "ambiguous": 0,
                "no_match": 0, "retagged_county": 0, "parcel_only": 0}

    log.info("lis_pendens_resolver.start", target_count=len(targets))
    stats = {
        "queried": 0, "address_filled": 0, "parcel_only": 0,
        "ambiguous": 0, "no_match": 0, "retagged_county": 0,
        "no_layer": 0, "fiduciary_skipped": 0,
    }

    # Bound concurrency — SCDOT is shared infrastructure.
    sem = asyncio.Semaphore(4)

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        async with sem:
            correct_county = _decode_case_county(li.case_number)
            if not correct_county:
                return

            # Defense-in-depth: ALWAYS re-tag county from case# even if the
            # listing already has a real address. Stale data + new
            # enrichments downstream should both see the correct county.
            if li.county != correct_county:
                li.county = correct_county
                stats["retagged_county"] += 1
                # Clear address fields that came from a wrong-county hit
                # (only when the address is itself a placeholder — never
                # nuke a real address we're confident about).
                if _is_placeholder(li):
                    li.city = None
                    li.zip_code = None
                    li.parcel_id = None
                    li.latitude = None
                    li.longitude = None

            # Only the placeholder set goes through GIS lookup. A real
            # address (correctly tagged county) doesn't need re-resolution.
            if not _is_placeholder(li):
                return

            schema = COUNTY_SCHEMA.get(correct_county)
            layer = SC_LAYER.get(correct_county)
            if not schema or not layer:
                stats["no_layer"] += 1
                return

            where = _build_where(correct_county, li.defendant or "")
            if not where:
                return
            stats["queried"] += 1

            results = await _query_layer(c, layer, where)
            confident = [
                a for a in results
                if _confident_match(li.defendant or "", _owner_string(a, schema))
            ]
            if not confident:
                stats["no_match"] += 1
                return

            d_tokens = _name_tokens(li.defendant or "")
            strict = [
                a for a in confident
                if all(t in set(_name_tokens(_owner_string(a, schema))) for t in d_tokens)
            ]
            picks = strict if strict else confident

            if len(picks) > 1:
                # Multiple parcels under same owner — common for landlords.
                stats["ambiguous"] += 1
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["lis_pendens_resolution"] = {
                    "ambiguous": True,
                    "county": correct_county,
                    "candidates": [
                        {
                            "parcel_id": _pick(a, schema["parcel"]),
                            "owner": _owner_string(a, schema),
                            "lat": a.get("_centroid", (None, None))[0],
                            "lon": a.get("_centroid", (None, None))[1],
                        } for a in picks[:10]
                    ],
                }
                return

            attrs = picks[0]
            resolved = _resolve_address(attrs, schema, li.defendant or "")

            if resolved.get("_fiduciary"):
                stats["fiduciary_skipped"] += 1

            if resolved.get("street_address"):
                li.street_address = resolved["street_address"]
                stats["address_filled"] += 1
            else:
                stats["parcel_only"] += 1

            if resolved.get("city"):
                li.city = resolved["city"]
            if resolved.get("zip"):
                li.zip_code = resolved["zip"]
            if resolved.get("parcel_id"):
                li.parcel_id = resolved["parcel_id"]
            if resolved.get("lat") is not None:
                li.latitude = resolved["lat"]
                li.longitude = resolved["lon"]

            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["lis_pendens_resolution"] = {
                "matched_owner": _owner_string(attrs, schema),
                "address_source": resolved.get("address_source"),
                "county": correct_county,
                "fiduciary": bool(resolved.get("_fiduciary")),
            }

    headers = {"User-Agent": "foreclosure-scraper/lis-pendens-resolver"}
    async with httpx.AsyncClient(headers=headers) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("lis_pendens_resolver.done", **stats)
    return stats
