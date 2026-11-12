"""One canonical spelling for a county name. Use this instead of .title().

WHY THIS MODULE EXISTS
    `.title()` lowercases every letter after the first of each word, so

        "McDowell".title()  -> "Mcdowell"
        "McCormick".title() -> "Mccormick"

    and `.title()` is applied to county names in a dozen places across this codebase
    (enrichment_address_owner_v2, assessor_photo, aggressive_address, buyer_match,
    county_phone, fhfa_value, equity, foreclosure_sold_comps, ...).

    McDowell NC and McCormick SC are the only NC/SC counties with an internal capital, so
    they are the only ones this damages -- but it damages them everywhere. Measured on the
    live board 2026-09-13:

        NC McDowell   1,771 rows SPLIT: 'McDowell' 1,627 / 'Mcdowell' 144
        SC McCormick  written 'Mccormick' consistently -- wrong everywhere, so it never
                      even looked split

    A split county name fragments every per-county count, misses the footprint check when
    the config says "McDowell", and breaks the parcel-cache lookup for the rows on the
    wrong side of the split. config.ALL_COUNTIES spells it "McDowell", so that is canon.

    The fix is one function, not a special case: any name whose first two letters are
    "Mc" or "Mac" capitalises the letter that follows.
"""
from __future__ import annotations

import re

_SUFFIX_RE = re.compile(r"\s+county\s*$", re.I)


def canonical_county(name: str | None) -> str:
    """Canonical spelling: title case, with Mc/Mac prefixes handled.

    >>> canonical_county("mcdowell")
    'McDowell'
    >>> canonical_county("MCCORMICK COUNTY")
    'McCormick'
    >>> canonical_county("new hanover")
    'New Hanover'
    """
    if not name:
        return ""
    s = _SUFFIX_RE.sub("", str(name).strip())
    if not s:
        return ""
    out = []
    for word in s.split():
        w = word.title()
        # "Mcdowell" -> "McDowell", "Macarthur" -> "MacArthur". Guard the length so a
        # bare "Mc" or a word that merely starts with "mac" (Macon!) is not mangled.
        low = w.lower()
        if low.startswith("mc") and len(w) > 2:
            w = "Mc" + w[2].upper() + w[3:]
        elif low.startswith("mac") and len(w) > 4 and low not in ("macon",):
            w = "Mac" + w[3].upper() + w[4:]
        out.append(w)
    return " ".join(out)


def same_county(a: str | None, b: str | None) -> bool:
    """True when two spellings mean the same county."""
    return canonical_county(a).lower() == canonical_county(b).lower()
