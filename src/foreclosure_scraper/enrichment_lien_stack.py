"""Lien-stack join — attach a property owner's OTHER recorded debts to the
subject listing so the equity engine subtracts them.

A flipper's equity math is only right if the full encumbrance stack is counted.
We already pull the SCDOR Top-Delinquent-Taxpayer list each run (sc_state_tax_lien)
as standalone leads, but never connected those debts to the matching property
listings. A state tax lien is SUPER-PRIORITY (it primes a mortgage), so it must
reduce the seller's equity.

Match is conservative — same county AND an EXACT normalized name-token-set match
(so "SMITH, JOHN A" == "JOHN SMITH" but not "JOHN SMITH" vs "JOHN SMITHSON") —
because a false join would wrongly tank a real deal's equity. Writes raw['liens']
(a list of {type, amount, source, holder}); enrichment_equity sums these into
senior liens. Pure-Python, no I/O.
"""
from __future__ import annotations

import re

import structlog

from .models import Listing, ListingType

log = structlog.get_logger()

_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "ESQ"}
_BIZ = {"LLC", "INC", "CORP", "TRUST", "TR", "LP", "LLP", "COMPANY", "CO", "BANK",
        "ASSOCIATION", "ESTATE", "ENTERPRISES", "PROPERTIES", "HOLDINGS"}


def _name_tokens(name: str | None) -> frozenset[str]:
    if not name:
        return frozenset()
    toks = [t for t in re.split(r"[^A-Za-z]+", name.upper()) if len(t) > 1]
    toks = [t for t in toks if t not in _SUFFIXES]
    return frozenset(toks)


def _is_business(tokens: frozenset[str]) -> bool:
    return bool(tokens & _BIZ)


def _owner_tokens(li: Listing) -> frozenset[str]:
    """Best owner name for a subject listing: GIS owner > defendant."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    gis = raw.get("gis") or {}
    for cand in (gis.get("owner"), li.defendant):
        t = _name_tokens(cand)
        if t:
            return t
    return frozenset()


def enrich_lien_stack(listings: list[Listing]) -> dict:
    # 1) Index the state-tax-lien rows by (county, name-token-set).
    lien_index: dict[tuple[str, frozenset[str]], float] = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        stl = raw.get("sc_state_tax_lien")
        if not stl:
            continue
        toks = _name_tokens(stl.get("owner") or li.defendant)
        if len(toks) < 2 or _is_business(toks):   # need a real personal full name
            continue
        amt = stl.get("balance") or li.judgment_amount
        if not amt:
            continue
        key = ((li.county or "").upper(), toks)
        lien_index[key] = max(lien_index.get(key, 0.0), float(amt))
    if not lien_index:
        return {"indexed": 0, "matched": 0}

    # 2) Attach to matching subject listings (don't annotate the lien rows
    #    themselves — they already carry it).
    matched = 0
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("sc_state_tax_lien") or li.listing_type is ListingType.TAX_LIEN:
            continue
        toks = _owner_tokens(li)
        if len(toks) < 2:
            continue
        amt = lien_index.get(((li.county or "").upper(), toks))
        if not amt:
            continue
        liens = list(raw.get("liens") or [])
        if any(x.get("source") == "sc_state_tax_lien" for x in liens):
            continue
        liens.append({"type": "state_tax_lien", "amount": round(float(amt), 2),
                      "source": "sc_state_tax_lien", "holder": "SC Dept of Revenue",
                      "super_priority": True})
        raw["liens"] = liens
        li.raw = raw
        matched += 1
    log.info("lien_stack.done", indexed=len(lien_index), matched=matched)
    return {"indexed": len(lien_index), "matched": matched}
