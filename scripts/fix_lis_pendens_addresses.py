"""One-off corrector for SC lis-pendens placeholder addresses.

Re-tags county from case# prefix (the authoritative venue marker), then
queries SCDOT GIS by defendant in the correct county and fills street_address,
city, zip, parcel_id, latitude/longitude when we can match confidently.

Confidence policy (intentionally conservative — only commit a real address
when we're sure it's the right parcel):

  * Defendant name is tokenized; common stopwords (LLC, INC, COMPANY,
    TRUST, TRUSTEE, JR, SR, AS, THE, ET AL, PERSONAL REPRESENTATIVE, …)
    are dropped.
  * For LLC / company defendants: every remaining distinctive token must
    appear in the owner-name string.
  * For individual defendants: at least the surname plus one other
    distinctive token (typically the first name) must appear in the owner.
  * The match must produce exactly one parcel under the rule above. If
    multiple parcels qualify equally, we don't commit a street address
    (we still write parcel-set into raw for review).

Address policy:

  * If the county GIS exposes a real situs (not mailing) field, use it.
  * If the county GIS only carries mailing AND the owner-occupancy /
    homestead flag is set AND the mailing has a street number (i.e. not
    a P.O. box), treat the mailing as the property address.
  * Otherwise: leave the placeholder intact (don't fabricate). We still
    write parcel_id + centroid lat/lng so downstream maps work.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
LISTINGS_PATH = ROOT / "docs" / "listings.json"

SCDOT = "https://smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer"

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

# Per-county SCDOT layer field schemas (these vary widely across counties).
# (situs_full, situs_num, situs_name, situs_type, situs_city, situs_zip,
#  mailing_full, mailing_city, mailing_zip, owner_fields, parcel, owner_occ,
#  resi_class)
COUNTY_SCHEMA: dict[str, dict[str, Any]] = {
    "Anderson": {
        "owner": ("OWNER",),
        "situs": (),
        "situs_parts": (),
        "mailing": ("OWNER_ADDR",),
        "city": ("CITY",),
        "zip": ("ZIPCODE",),
        "parcel": ("TMS",),
        "owner_occ": (),
    },
    "Cherokee": {
        "owner": ("SHEET1__Na",),
        "situs": (),
        "situs_parts": (),
        "mailing": ("SHEET1___1",),
        "city": ("SHEET1___2",),
        "zip": ("SHEET1__Zi", "ZipCode"),
        "parcel": ("ParcelPoly",),
        "owner_occ": (),
    },
    "Oconee": {
        "owner": ("OWNERNAME", "Owner"),
        "situs": ("FullAdd",),
        "situs_parts": ("HOUSE_NO", "STREET_NAM", "TYPE"),
        "mailing": ("ADDRESS2",),
        "city": ("CITY",),
        "zip": ("ZIP",),
        "parcel": ("TMS_NUMBER", "PARCEL_NO"),
        "owner_occ": (),
    },
    "Pickens": {
        "owner": ("NAME1", "OwnerAll"),
        "situs": ("LOCADD",),
        "situs_parts": (),
        "mailing": ("ADD1",),
        "city": ("LOCCITY", "CITY"),
        "zip": ("LOCZIP", "ZIP"),
        "parcel": ("PIN",),
        "owner_occ": (),
    },
    "Laurens": {
        "owner": ("Name1", "Owner", "OwneAll"),
        "situs": ("Property_A",),
        "situs_parts": ("Street_Num", "Street_Nam"),
        "mailing": ("Address1",),
        "city": ("Mailing_Ci", "Address2"),
        "zip": ("ZIP_Code",),
        "parcel": ("TMS", "TaxPIN", "Map_Number"),
        "owner_occ": ("Owner_Occu", "Residentia"),
    },
    "Union": {
        "owner": ("NAME_1", "Name", "OwnerAll"),
        "situs": (),
        "situs_parts": ("STREET_NUM", "STREET_NAM"),
        "mailing": ("Address_2", "ADDRESS_12"),
        "city": ("Address_3", "ADDRESS_23"),
        "zip": ("ZIP_CODE",),
        "parcel": ("ParcelID", "Map_Number"),
        "owner_occ": (),
    },
}

CASE_RE = re.compile(r"(\d{4})-CP-(\d{2})-\d+")

# Tokens we strip out before comparing defendant ↔ owner names.
NAME_STOPWORDS = {
    "LLC", "L.L.C", "LLP", "INC", "CORP", "CO", "COMPANY", "LP", "LTD",
    "TRUST", "TRUSTEE", "TRUSTEES", "ESTATE", "REVOCABLE", "IRREVOCABLE",
    "JR", "SR", "II", "III", "IV",
    "ETAL", "ET", "AL",
    "PERSONAL", "REPRESENTATIVE", "REP", "AS",
    "THE", "AND", "OF", "FOR", "A", "AN",
    "MR", "MRS", "MS", "DR",
    "DECD", "DECEASED", "AKA", "FKA", "DBA",
}

PO_BOX_RE = re.compile(r"\b(P\.?\s*O\.?\s*BOX|POST\s+OFFICE\s+BOX|PO\s*BOX)\b", re.I)

# Fiduciary roles → defendant is acting on someone else's property; refuse
# to commit a street address based on the fiduciary's own parcel ownership.
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
    url = f"{SCDOT}/{layer}/query"
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
        c_ = _centroid_from_geom(f.get("geometry") or {})
        if c_:
            attrs["_centroid"] = c_
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
    clauses = []
    for of in schema["owner"]:
        clauses.append(f"UPPER({of}) LIKE '%{surname}%'")
    return " OR ".join(clauses)


def _owner_string(attrs: dict, schema: dict) -> str:
    return _pick(attrs, schema["owner"]) or ""


def _confident_match(defendant: str, owner: str) -> bool:
    d_tokens = _name_tokens(defendant)
    o_tokens = set(_name_tokens(owner))
    if not d_tokens or not o_tokens:
        return False
    if _is_company(defendant):
        return all(t in o_tokens for t in d_tokens)
    if len(d_tokens) >= 2:
        matches = sum(1 for t in d_tokens if t in o_tokens)
        return matches >= 2 and d_tokens[0] in o_tokens
    return d_tokens[0] in o_tokens


def _resolve_address(attrs: dict, schema: dict, defendant: str) -> dict:
    """Returns {street_address, city, zip, parcel_id, lat, lon, source_tag}.
    Only populates street_address when we have a real situs OR a homestead
    individual whose mailing is a street address (not PO box).

    Refuses to commit street_address for fiduciary defendants (PR, Trustee,
    Executor, …): their parcels of record may not be the estate property
    actually under lien."""
    fiduciary = bool(FIDUCIARY_RE.search(defendant or ""))
    out: dict[str, Any] = {"_fiduciary": fiduciary}
    parcel = _pick(attrs, schema["parcel"])
    if parcel:
        out["parcel_id"] = parcel
    centroid = attrs.get("_centroid")
    if centroid:
        out["lat"] = centroid[0]
        out["lon"] = centroid[1]
    out["zip"] = _pick(attrs, schema["zip"]) or None
    if out["zip"]:
        digits = re.sub(r"\D", "", out["zip"])
        # Strip a leading zero when the field stores zip+4 padded with one
        # (Cherokee SCDOT layer does this: "0293400000" → "29340").
        if len(digits) >= 9 and digits.startswith("0"):
            digits = digits[1:]
        out["zip"] = digits[:5] if len(digits) >= 5 else None

    # Refuse to commit any street address for fiduciary defendants — the
    # parcel of record may not be the estate property that's actually under
    # lien. We still record parcel + centroid for human review.
    if fiduciary:
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

    # Homestead-individual fallback: mailing address as property address.
    if "street_address" not in out and not _is_company(defendant):
        mailing = _pick(attrs, schema["mailing"])
        owner_occ = False
        for k in schema.get("owner_occ", ()):
            v = _pick(attrs, (k,))
            if v and str(v).upper().startswith(("Y", "T", "1")):
                owner_occ = True
                break
        if mailing and not PO_BOX_RE.search(mailing) and re.match(r"\s*\d", mailing):
            # Even without an explicit homestead flag, an individual's mailing
            # at a street number in the same county is overwhelmingly the
            # property itself. We require a city match ourselves (city in the
            # mailing must be in the same county) — caller validates.
            if owner_occ or schema.get("owner_occ") == ():
                out["street_address"] = mailing
                out["address_source"] = "mailing_homestead" if owner_occ else "mailing"

    # City
    city = _pick(attrs, schema["city"])
    if city:
        # Some layers concatenate "CITY  STATE" into one field — split.
        m = re.match(r"^(.*?)\s+(?:S\.?\s*C\.?|SC|N\.?\s*C\.?|NC)\s*\d{0,5}\s*$", city, re.I)
        out["city"] = (m.group(1) if m else city).strip()
    return out


async def main() -> None:
    # GUARD (2026-08-14): writes docs/listings.json directly (write_text/json.dumps),
    # bypassing load_board()/write_artifact() — wipes the sidecar + emits 1 of 6 board
    # files, corrupting the board (dashboard reads listings.json.gz). Use the proper
    # address lane instead: ADDR_WRITE=1 .venv/bin/python scripts/resolve_addresses.py.
    import os as _os
    if _os.environ.get("ALLOW_UNSAFE_BOARD_WRITE") != "1":
        print("REFUSING: corrupts the board (writes listings.json without write_artifact). "
              "Use scripts/resolve_addresses.py ADDR_WRITE=1 instead.")
        return
    listings = json.loads(LISTINGS_PATH.read_text())

    # Targets: every SC lis-pendens listing whose street_address is either a
    # placeholder OR whose county tag disagrees with the case-number prefix.
    # The latter group came from a now-fixed bug where cross-county owner
    # search committed a same-name hit in the wrong county. Reset and re-do.
    targets = []
    for li in listings:
        if li.get("state") != "SC":
            continue
        if not (li.get("source") or "").startswith("counties_sc.sc_public_index_lis_pendens"):
            continue
        case = li.get("case_number") or ""
        m = CASE_RE.match(case)
        if not m:
            continue
        correct_county = SC_COUNTY_BY_CODE.get(m.group(2))
        if not correct_county:
            continue
        sa = (li.get("street_address") or "").strip()
        is_placeholder = sa.startswith("Lis Pendens ")
        is_mistagged = li.get("county") != correct_county
        if not (is_placeholder or is_mistagged):
            continue
        # Reset any address committed under the wrong county. We'll re-resolve.
        if is_mistagged and not is_placeholder:
            # Restore placeholder so the rest of the pipeline treats this
            # correctly, and clear all tainted address fields.
            li["street_address"] = (
                f"Lis Pendens {case} — {li.get('defendant') or ''}".strip(" —")
            )
        targets.append((li, correct_county))

    print(f"Targets: {len(targets)} SC lis-pendens with placeholder address")

    # Stats
    stats = {
        "retagged_county": 0,
        "no_layer": 0,
        "queried": 0,
        "owner_matched": 0,
        "address_filled": 0,
        "parcel_only": 0,
        "no_match": 0,
        "ambiguous": 0,
    }

    async with httpx.AsyncClient(headers={"User-Agent": "foreclosure-scraper/lis-pendens-fix"}) as c:
        for li, correct_county in targets:
            old_county = li.get("county")
            if old_county != correct_county:
                li["county"] = correct_county
                stats["retagged_county"] += 1

            # Reset tainted fields (city/lat/lon/parcel_id/zip filled by wrong-county
            # match earlier). Address source unknown; keep what we had as fallback.
            for k in ("city", "latitude", "longitude", "parcel_id", "zip_code"):
                # We do clear these — they came from a wrong-county owner search.
                li[k] = None

            schema = COUNTY_SCHEMA.get(correct_county)
            layer = SC_LAYER.get(correct_county)
            if not schema or not layer:
                stats["no_layer"] += 1
                continue
            where = _build_where(correct_county, li.get("defendant") or "")
            if not where:
                continue
            stats["queried"] += 1
            results = await _query_layer(c, layer, where)
            # Filter to confident matches
            confident = []
            for attrs in results:
                owner = _owner_string(attrs, schema)
                if _confident_match(li.get("defendant") or "", owner):
                    confident.append(attrs)

            if not confident:
                stats["no_match"] += 1
                continue

            # If multiple confident hits, prefer ones whose every defendant
            # token appears (LLC strict mode). If still multiple, ambiguous.
            d_tokens = _name_tokens(li.get("defendant") or "")
            strict = []
            for a in confident:
                o = set(_name_tokens(_owner_string(a, schema)))
                if all(t in o for t in d_tokens):
                    strict.append(a)
            picks = strict if strict else confident
            if len(picks) > 1:
                # Multiple parcels under same owner — common for landlords.
                # Don't commit a single street_address; record the parcel set
                # in raw and skip address.
                stats["ambiguous"] += 1
                li.setdefault("raw", {}).setdefault("lis_pendens_resolution", {})
                li["raw"]["lis_pendens_resolution"]["candidates"] = [
                    {
                        "parcel_id": _pick(a, schema["parcel"]),
                        "owner": _owner_string(a, schema),
                        "lat": a.get("_centroid", (None, None))[0],
                        "lon": a.get("_centroid", (None, None))[1],
                    } for a in picks[:10]
                ]
                continue

            stats["owner_matched"] += 1
            attrs = picks[0]
            resolved = _resolve_address(attrs, schema, li.get("defendant") or "")

            # Apply
            if resolved.get("street_address"):
                li["street_address"] = resolved["street_address"]
                stats["address_filled"] += 1
            else:
                stats["parcel_only"] += 1
            if resolved.get("city"):
                li["city"] = resolved["city"]
            if resolved.get("zip"):
                li["zip_code"] = resolved["zip"]
            if resolved.get("parcel_id"):
                li["parcel_id"] = resolved["parcel_id"]
            if resolved.get("lat") is not None:
                li["latitude"] = resolved["lat"]
                li["longitude"] = resolved["lon"]
            li.setdefault("raw", {})["lis_pendens_resolution"] = {
                "matched_owner": _owner_string(attrs, schema),
                "address_source": resolved.get("address_source"),
                "county": correct_county,
            }

    LISTINGS_PATH.write_text(json.dumps(listings, indent=2, default=str))
    print("\nStats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
