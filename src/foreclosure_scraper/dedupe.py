"""Listing deduplication. Same property from multiple sources merges into one row."""
from __future__ import annotations

from rapidfuzz import fuzz

from .models import Listing


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

    return final
