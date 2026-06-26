"""SC DEW lien CROSS-REFERENCE (UI-tax + benefit-overpayment liens).

The SC DEW registries list tens of thousands of statewide liens, addressed only
to the debtor's *employer* mailing address — name + balance, NOT a foreclosure
property. Dumping them on the board as standalone rows bloated it (~8k) and
dragged the whole enrichment pass. So we use them purely as a NAME cross-reference:
fetch the in-footprint debtors once, index by (county, name-token-set), and attach
the lien to any PROPERTY lead whose owner matches (same conservative 3+-token,
same-county rule as enrichment_lien_stack). No standalone board rows are emitted —
the sc_dew scraper itself is disabled() on the board; this enricher owns the data.
"""
from __future__ import annotations

import structlog

from .models import Listing, ListingType
from .enrichment_lien_stack import _name_tokens, _owner_tokens, _is_business

log = structlog.get_logger(__name__)


async def enrich_dew_liens(listings: list[Listing]) -> dict:
    """Attach SC DEW liens to matching property leads by owner name (no new rows)."""
    from .scrapers.counties_sc.sc_dew_lien_registry import SCDEWLienRegistry

    try:
        rows = list(await SCDEWLienRegistry().fetch())
    except Exception as e:  # noqa: BLE001
        log.warning("dew_liens.fetch_failed", err=str(e)[:140])
        return {"fetched": 0, "indexed": 0, "matched": 0}

    # 1) Index in-footprint DEW debtors by (county, name-tokens) -> max balance.
    index: dict[tuple[str, frozenset[str]], float] = {}
    for r in rows:
        d = (r.raw or {}).get("sc_dew_lien_registry") or {}
        toks = _name_tokens(r.defendant)
        if len(toks) < 3 or _is_business(toks):
            continue
        amt = d.get("balance") or r.judgment_amount
        if not amt:
            continue
        key = ((r.county or "").upper(), toks)
        index[key] = max(index.get(key, 0.0), float(amt))
    if not index:
        return {"fetched": len(rows), "indexed": 0, "matched": 0}

    # 2) Attach to matching property leads (skip lien rows themselves).
    matched = 0
    for li in listings:
        if li.listing_type is ListingType.TAX_LIEN:
            continue
        toks = _owner_tokens(li)
        if len(toks) < 3:
            continue
        amt = index.get(((li.county or "").upper(), toks))
        if not amt:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        liens = list(raw.get("liens") or [])
        if any(x.get("source") == "sc_dew_lien_registry" for x in liens):
            continue
        liens.append({
            "type": "dew_lien", "amount": round(float(amt), 2),
            "source": "sc_dew_lien_registry",
            "holder": "SC Dept of Employment & Workforce", "super_priority": True,
        })
        raw["liens"] = liens
        li.raw = raw
        matched += 1

    log.info("dew_liens.done", fetched=len(rows), indexed=len(index), matched=matched)
    return {"fetched": len(rows), "indexed": len(index), "matched": matched}
