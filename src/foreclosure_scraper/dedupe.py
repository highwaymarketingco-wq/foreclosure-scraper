"""Listing deduplication. Same property from multiple sources merges into one row."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import Listing


_SUFFIX = {
    "avenue": "ave", "ave": "ave", "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln", "boulevard": "blvd", "blvd": "blvd",
    "court": "ct", "ct": "ct", "circle": "cir", "cir": "cir", "place": "pl", "pl": "pl",
    "trail": "trl", "trl": "trl", "way": "way", "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy", "terrace": "ter", "ter": "ter", "loop": "loop", "run": "run",
    "cove": "cv", "cv": "cv", "path": "path", "pike": "pike", "point": "pt", "pt": "pt",
    "crossing": "xing", "square": "sq", "ridge": "rdg",
}


def _canon_street(a: str) -> str:
    """House# + street name through the standardized suffix, dropping any trailing city/unit
    ('19 gosnell avenue inman' -> '19 gosnell ave'). '' if no leading house# or no known suffix."""
    if not a:
        return ""
    toks = a.split()
    if not toks or not re.match(r"^\d", toks[0]):
        return ""
    for i in range(1, len(toks)):
        base = re.sub(r"[^a-z]", "", toks[i])
        if base in _SUFFIX:
            return " ".join(toks[:i] + [_SUFFIX[base]])
    return ""


def _strong_sigs(li: Listing) -> set:
    """Strong same-property signatures for union-merge. Excludes placeholder /
    bankruptcy 'addresses' so name-only rows never collapse together."""
    out: set = set()
    st = (li.state or "")
    z = (li.zip_code or "").strip()
    a = _norm_addr(li.street_address)
    lt = li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    if a.startswith(("lis pendens", "property in", "vacant")) or lt == "bankruptcy":
        a = ""
    pn = re.sub(r"[^a-z0-9]", "", (li.parcel_id or "").lower())
    if pn and len(pn) >= 4 and st:          # guard: whitespace/degenerate parcel -> no sig
        out.add(("p", pn, st))
    cn = (li.case_number or "").strip()
    if cn and a:                            # require a real case# AND a real address
        out.add(("c", cn, (li.county or ""), a))
    if a and z:
        out.add(("a", a, z))
    # Canonical street + county + state — merges the SAME street address across sources even when
    # one copy lacks a zip or jams the city into the street field (the '19 Gosnell Ave' dup class).
    cs = _canon_street(a)
    cty = re.sub(r"[^a-z0-9]", "", (li.county or "").lower())
    if cs and cty and st:
        out.add(("s", cs, cty, st))
    return out


def _norm_addr(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().replace(",", " ").split())


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Merge listings that point to the same property.

    Strategy:
    1. Bucket by primary dedupe_key (parcel/address/case)
    2. Within each bucket, merge using Listing.merge
    3. Cross-bucket fuzzy address match for stragglers
    """
    if not listings:
        return []

    buckets: dict[str, Listing] = {}
    for li in listings:
        k = li.dedupe_key()
        if k in buckets:
            buckets[k] = buckets[k].merge(li)
        else:
            buckets[k] = li

    merged = list(buckets.values())

    # Pass 2: fuzzy address merge (only across listings that have addresses + zip)
    final: list[Listing] = []
    consumed: set[int] = set()
    for i, a in enumerate(merged):
        if i in consumed:
            continue
        addr_a = _norm_addr(a.street_address)
        for j in range(i + 1, len(merged)):
            if j in consumed:
                continue
            b = merged[j]
            if not (addr_a and b.street_address and a.zip_code and b.zip_code):
                continue
            if a.zip_code != b.zip_code:
                continue
            score = fuzz.token_set_ratio(addr_a, _norm_addr(b.street_address))
            if score >= 92:
                a = a.merge(b)
                consumed.add(j)
        final.append(a)

    # Pass 3 (2026-06-19): signature union-merge. dedupe_key is parcel>addr>case>
    # url, so the SAME property with a parcel_id on one copy and only a case# on
    # another splits into two keys and never merges (verified leak: ~19 rows).
    # Union any rows sharing a strong signature, then merge each group.
    parent = list(range(len(final)))
    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    sigmap: dict = {}
    for i, li in enumerate(final):
        for s in _strong_sigs(li):
            if s in sigmap:
                parent[_find(sigmap[s])] = _find(i)
            else:
                sigmap[s] = i
    groups: dict = {}
    for i in range(len(final)):
        groups.setdefault(_find(i), []).append(i)
    out: list[Listing] = []
    for idxs in groups.values():
        m = final[idxs[0]]
        for j in idxs[1:]:
            m = m.merge(final[j])
        out.append(m)
    return out
