"""Enforce case-pinned county on lis-pendens / foreclosure listings.

NC and SC both have venue rules requiring foreclosure proceedings to
be filed in the county where the property is located:
  * NC: NCGS §45-21.2 — sale held in the county where the property
    is located; the case is heard there too.
  * SC: SC Code §15-11-10 — venue follows situs of real property.

Both states encode the venue county directly in the case number:
  * NC eCourts (Tyler Odyssey): suffix 3-digit court ID — e.g.
    "26M000113-640" where 640 = New Hanover.
  * SC Common Pleas: middle 2-digit prefix — e.g. "2024-CP-30-12345"
    where 30 = Laurens.

Why this enrichment exists:

The address-finding chain (enrich_addresses_from_owner,
enrich_with_parcel_lookup, enrich_with_aggressive_address) queries
county GIS endpoints across multiple counties for the same defendant
name. When a defendant has the same name as a property owner in a
DIFFERENT county, those enrichments will cheerfully overwrite
``li.county`` and ``li.street_address`` with the wrong-county data —
treating the cross-county match as if it were the right property.

Run #16 forensics: 15 NC eCourts listings had county overwritten this
way (case#=Wake but county tagged Polk, etc.). SC was protected by
``enrich_lis_pendens_addresses`` which already re-tags from case#;
this module generalizes that protection to NC and runs as the LAST
step in the address chain so any later enrichment that overwrites
gets corrected.

Policy:
  * If case# decodes to a venue county and ``li.county`` disagrees,
    re-tag county to the case-pinned value.
  * If we re-tag, NULL out ``li.street_address`` — it was almost
    certainly filled from the wrong-county GIS.  An address synthesis
    pass can re-fill with a placeholder.  Wrong address is worse than
    no address.
  * Record the correction in ``li.raw.county_pin = {original_county,
    pinned_to, statute, source}`` so the dashboard / patch reviewers
    can see what got fixed.
  * Idempotent — running this twice on the same data is a no-op
    after the first pass.

Pure-Python, no I/O.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


# SC Common Pleas case#: YYYY-CP-NN-XXXXXX (NN = 2-digit county code).
# Authoritative for venue under SC Code §15-11-10.
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
SC_CASE_RE = re.compile(r"(\d{4})-CP-(\d{2})-\d+")

# NC eCourts (Tyler Odyssey) case#: NNXXXXNNNNNN-CCC where CCC = 3-digit
# court location ID. Mapping observed in actual NC eCourts data — the
# Tyler portal exposes one court ID per county, and the location field
# in each hit confirms which county each ID corresponds to.
# NCGS §45-21.2 makes this venue authoritative for foreclosure cases.
NC_COURT_ID_BY_CODE = {
    "000": "Alamance",
    "010": "Alexander",
    "020": "Alleghany",
    "030": "Anson",
    "040": "Ashe",
    "050": "Avery",
    "060": "Beaufort",
    "070": "Bertie",
    "080": "Bladen",
    "090": "Brunswick",
    "100": "Buncombe",
    "110": "Burke",
    "120": "Cabarrus",
    "130": "Caldwell",
    "140": "Camden",
    "150": "Carteret",
    "160": "Caswell",
    "170": "Catawba",
    "180": "Chatham",
    "190": "Cherokee",
    "200": "Chowan",
    "210": "Clay",
    "220": "Cleveland",
    "230": "Columbus",
    "240": "Craven",
    "250": "Cumberland",
    "260": "Currituck",
    "270": "Dare",
    "280": "Davidson",
    "290": "Davie",
    "300": "Duplin",
    "310": "Durham",
    "320": "Edgecombe",
    "330": "Forsyth",
    "340": "Franklin",
    "350": "Gaston",
    "360": "Gates",
    "370": "Graham",
    "380": "Granville",
    "390": "Greene",
    "400": "Guilford",
    "410": "Halifax",
    "420": "Harnett",
    "430": "Haywood",
    "440": "Henderson",
    "450": "Hertford",
    "460": "Hoke",
    "470": "Hyde",
    "480": "Iredell",
    "490": "Jackson",
    "500": "Johnston",
    "510": "Jones",
    "520": "Lee",
    "530": "Lenoir",
    "540": "Lincoln",
    "550": "Macon",
    "560": "Madison",
    "570": "Martin",
    "580": "McDowell",
    "590": "Mecklenburg",
    "600": "Mitchell",
    "610": "Montgomery",
    "620": "Moore",
    "630": "Nash",
    "640": "New Hanover",
    "650": "Northampton",
    "660": "Onslow",
    "670": "Orange",
    "680": "Pamlico",
    "690": "Pasquotank",
    "700": "Pender",
    "710": "Perquimans",
    "720": "Person",
    "730": "Pitt",
    "740": "Polk",
    "750": "Randolph",
    "760": "Richmond",
    "770": "Robeson",
    "780": "Rockingham",
    "790": "Rowan",
    "800": "Rutherford",
    "810": "Sampson",
    "820": "Scotland",
    "830": "Stanly",
    "840": "Stokes",
    "850": "Surry",
    "860": "Swain",
    "870": "Transylvania",
    "880": "Tyrrell",
    "890": "Union",
    "900": "Vance",
    "910": "Wake",
    "920": "Warren",
    "930": "Washington",
    "940": "Watauga",
    "950": "Wayne",
    "960": "Wilkes",
    "970": "Wilson",
    "980": "Yadkin",
    "990": "Yancey",
}
NC_CASE_RE = re.compile(r"-(\d{3})$")


def decode_case_pinned_county(case_number: Optional[str], state: Optional[str]) -> Optional[str]:
    """Return the venue county encoded in the case number, or None when
    the case# format is unknown / not authoritative.

    SC: any "YYYY-CP-NN-XXXXXX" Common Pleas case → SC Code §15-11-10.
    NC: any "...-CCC" suffix where CCC matches a known court location
        → NCGS §45-21.2.
    """
    if not case_number or not state:
        return None
    cn = case_number.strip()
    if state == "SC":
        m = SC_CASE_RE.match(cn)
        if m:
            return SC_COUNTY_BY_CODE.get(m.group(2))
    if state == "NC":
        m = NC_CASE_RE.search(cn)
        if m:
            return NC_COURT_ID_BY_CODE.get(m.group(1))
    return None


def _is_synthesized_address(addr: Optional[str]) -> bool:
    """Heuristic: is street_address a synthesized placeholder rather
    than a real lookup result?"""
    if not addr:
        return True
    a = addr.strip()
    if not a:
        return True
    # Common synthesized prefixes from enrichment_address_final
    for marker in ("Lis Pendens ", "Vacant parcel ", "Cv Lien ", "(address pending)"):
        if a.startswith(marker) or marker in a:
            return True
    return False


def enforce_case_pinned_county(listings: list[Listing]) -> dict:
    """Re-tag county from case# for any listing where the case#-encoded
    county disagrees with li.county.

    Only operates on listings whose case_number authoritatively encodes
    a venue county (SC CP / NC eCourts formats). Fiduciary defendants
    are still touched — venue follows the case, not the defendant's
    capacity.

    When we re-tag, we also null out street_address IF that address
    looks like it came from a real-property GIS lookup (not a
    synthesized placeholder), because a real-looking address from the
    wrong county is worse than no address at all. Synthesized
    placeholders are kept since they're already labeled as not-real.
    """
    stats = {
        "scanned": 0,
        "case_pinned": 0,
        "already_correct": 0,
        "retagged_county": 0,
        "address_nulled": 0,
        "no_case_decode": 0,
    }
    for li in listings:
        stats["scanned"] += 1
        pinned = decode_case_pinned_county(li.case_number, li.state)
        if pinned is None:
            stats["no_case_decode"] += 1
            continue
        stats["case_pinned"] += 1
        if li.county == pinned:
            stats["already_correct"] += 1
            continue

        original_county = li.county
        original_address = li.street_address
        li.county = pinned
        stats["retagged_county"] += 1

        # If the address looks real (not a synthesized placeholder), it
        # was almost certainly filled by a wrong-county GIS match.
        # Wrong-county street_address shown to investors is dangerous —
        # they could drive to the wrong property. Null it out.
        nulled = False
        if not _is_synthesized_address(original_address):
            li.street_address = None
            li.city = None
            li.zip_code = None
            li.parcel_id = None
            li.latitude = None
            li.longitude = None
            stats["address_nulled"] += 1
            nulled = True

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["county_pin"] = {
            "original_county": original_county,
            "pinned_to": pinned,
            "case_number": li.case_number,
            "statute": "NCGS §45-21.2" if li.state == "NC" else "SC Code §15-11-10",
            "address_nulled": nulled,
            "original_address_was": (original_address or "")[:200] if nulled else None,
        }

    log.info("county_pin.done", **stats)
    return stats
