"""SC phone enrichment via NC voter file cross-reference.

SC has no free bulk voter file with phones. But many SC property owners live in NC
(or have NC records). This enricher cross-references SC foreclosure owner names
against the NC voter file (NCSBE) to find phone numbers.

CONSERVATIVE: Only matches on (last, first) when that name is UNIQUE in the NC voter
file (exactly one active NC voter with that name has a phone). Ambiguous names
(multiple voters with different phones) are skipped to avoid false positives.

Every number is tagged source=ncsbe_voter_xref + needs_dnc_scrub=True.
"""
from __future__ import annotations

import re
from pathlib import Path

# Reuse the NC voter index builder
from foreclosure_scraper.enrichment_voter_phone import _build_index, _name_candidates


_NAME_INDEX: dict | None = None


def _build_name_only_index() -> dict:
    """Build a (last, first) -> phone index from NC voter file.
    
    Only includes names where exactly one active NC voter has that name+phone
    (unambiguous = safe). Names with multiple phone numbers are excluded.
    """
    _, name_county, _, _ = _build_index()
    
    name_only: dict = {}
    name_counts: dict = {}
    
    for (cty, last, first), ph in name_county.items():
        key = (last, first)
        if key not in name_counts:
            name_counts[key] = set()
        name_counts[key].add(ph)
    
    # Only keep names with exactly one unique phone
    for key, phones in name_counts.items():
        if len(phones) == 1:
            name_only[key] = next(iter(phones))
    
    return name_only


def _set_phone(li, ph: str, match: str):
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["owner_phone"] = {
        "phone": f"({ph[0:3]}) {ph[3:6]}-{ph[6:]}",
        "source": "ncsbe_voter_xref",
        "line_type": "unknown",
        "needs_dnc_scrub": True,
        "match": match,
    }


def enrich_sc_phone_xref(listings) -> dict:
    """Cross-reference SC owner names against NC voter file for phones."""
    global _NAME_INDEX
    if _NAME_INDEX is None:
        _NAME_INDEX = _build_name_only_index()
    
    stats = {
        "sc_targets": 0,
        "matched": 0,
        "skipped_no_owner": 0,
        "skipped_ambiguous": 0,
    }
    
    for li in listings:
        if li.state != "SC":
            continue
        if not li.owner_name:
            stats["skipped_no_owner"] += 1
            continue
        
        # Skip if already has a phone
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("owner_phone"):
            continue
        
        stats["sc_targets"] += 1
        
        cands = list(_name_candidates(li.owner_name))
        for last, first in cands:
            ph = _NAME_INDEX.get((last, first))
            if ph:
                _set_phone(li, ph, f"nc_xref:{last},{first}")
                stats["matched"] += 1
                break
    
    return stats
