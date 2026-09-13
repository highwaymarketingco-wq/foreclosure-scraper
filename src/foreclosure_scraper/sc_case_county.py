"""Recover the SC county from a Master-in-Equity / Common Pleas case number.

SC case numbers are `YYYY-CP-NN-NNNNN`, where the middle pair is the COUNTY CODE — the
counties numbered 01-46 in alphabetical order. So 2025-CP-38-01441 is Orangeburg, and
2024-CP-42-00123 is Spartanburg, with no lookup or geocoding required.

WHY THIS MATTERS HERE
    Column files SC legal notices under the NEWSPAPER'S coverage region, not the county:
    58 of 98 recent SC foreclosure notices carry the county value
    'Orangeburg, Bamberg and Calhoun'. That routes nothing. The notice body usually says
    "COUNTY OF ORANGEBURG", but not always -- 11 of 37 parsed rows had no such line while
    every one of them had a case number.

    The code is a better key than the prose: it is present whenever the case number is,
    and it cannot be ambiguous.
"""
from __future__ import annotations

import re

#: SC counties numbered 01-46 alphabetically — the official Common Pleas county codes.
SC_COUNTY_BY_CODE: dict[str, str] = {
    "01": "Abbeville", "02": "Aiken", "03": "Allendale", "04": "Anderson",
    "05": "Bamberg", "06": "Barnwell", "07": "Beaufort", "08": "Berkeley",
    "09": "Calhoun", "10": "Charleston", "11": "Cherokee", "12": "Chester",
    "13": "Chesterfield", "14": "Clarendon", "15": "Colleton", "16": "Darlington",
    "17": "Dillon", "18": "Dorchester", "19": "Edgefield", "20": "Fairfield",
    "21": "Florence", "22": "Georgetown", "23": "Greenville", "24": "Greenwood",
    "25": "Hampton", "26": "Horry", "27": "Jasper", "28": "Kershaw",
    "29": "Lancaster", "30": "Laurens", "31": "Lee", "32": "Lexington",
    "33": "McCormick", "34": "Marion", "35": "Marlboro", "36": "Newberry",
    "37": "Oconee", "38": "Orangeburg", "39": "Pickens", "40": "Richland",
    "41": "Saluda", "42": "Spartanburg", "43": "Sumter", "44": "Union",
    "45": "Williamsburg", "46": "York",
}

#: Accepts 2025-CP-38-01441, 2025CP3801441 and 2025 CP 38 01441.
_CASE_RE = re.compile(r"\b(20\d\d)[- ]?CP[- ]?(\d{2})[- ]?(\d{3,6})\b", re.I)


def county_from_sc_case(case_number: str | None) -> str | None:
    """The county named by an SC case number's county code, or None."""
    m = _CASE_RE.search(case_number or "")
    if not m:
        return None
    return SC_COUNTY_BY_CODE.get(m.group(2))


def normalize_sc_case(case_number: str | None) -> str | None:
    """Canonical `YYYY-CP-NN-NNNNN` form, so the same case from two sources matches."""
    m = _CASE_RE.search(case_number or "")
    if not m:
        return None
    return f"{m.group(1)}-CP-{m.group(2)}-{m.group(3)}"
