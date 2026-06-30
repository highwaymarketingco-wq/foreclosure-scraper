"""Normalize per-source delinquent-tax amounts into one raw['tax_owed'] field and
cross-reference it onto matching parcels.

The tax-distress scrapers each capture the owed amount under their own raw key —
Buncombe `principal_tax_due`, SC state liens `balance`, Oconee FLC `fll_bid` — and
nothing on the board reads a unified figure. The assessor/GIS feed only ever gives
assessed/market VALUE, never the delinquent BALANCE, so this is the only place a
real taxes-OWED number lands.

Two passes, both free + pure-Python + idempotent:
  1. Normalize: each tax lead's own amount -> raw['tax_owed'] =
     {balance, kind, source, year, basis:'own_record'}.
  2. Cross-reference: build a (state, county, parcel) -> tax_owed index from those,
     then stamp it onto ANY lead (court/probate/foreclosure) resolved to the same
     parcel that doesn't already carry one (basis:'parcel_cross_ref'). A court lead
     the resolver just pinned to a parcel that is ALSO on a delinquent-tax list
     inherits the owed balance — a strong, free motivated-seller signal.

Gate off with FORECLOSURE_TAX_OWED=0.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# source-substring -> (raw subkey, amount field, kind)
_SOURCES = {
    "buncombe_delinquent_tax": ("buncombe_delinquent_tax", "principal_tax_due", "delinquent_tax"),
    "sc_state_tax_lien": ("sc_state_tax_lien", "balance", "state_tax_lien"),
    "oconee_forfeited_land": ("oconee_forfeited_land", "fll_bid", "flc_opening_bid"),
}

# generic amount keys scanned for any other tax/FLC/lien source subdict
_GENERIC_KEYS = (
    "principal_tax_due", "tax_due", "taxes_owed", "amount_owed", "total_due",
    "balance", "lien_amount", "fll_bid", "flc_bid", "opening_bid",
)
_TAXISH = ("tax", "flc", "forfeited", "delinquent", "lien")


def _money(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s or s == ".":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _pkey(pid: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", pid or "").upper()


def _county_county_key(li: Listing) -> tuple:
    return (li.state, (li.county or "").replace(" County", "").strip().title(),
            _pkey(li.parcel_id))


def _extract(li: Listing) -> tuple[Optional[float], Optional[str], object]:
    """(balance, kind, year) from a lead's OWN source record, else (None, None, None)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    src = li.source or ""
    for sub, (key, fld, kind) in _SOURCES.items():
        if sub in src:
            blk = raw.get(key) or {}
            bal = _money(blk.get(fld))
            if bal:
                return bal, kind, blk.get("year")
    # generic scan for any other tax-ish source
    if any(k in src for k in _TAXISH):
        for blk in raw.values():
            if isinstance(blk, dict):
                for gk in _GENERIC_KEYS:
                    bal = _money(blk.get(gk))
                    if bal:
                        return bal, "delinquent_tax", blk.get("year")
    return None, None, None


def enrich_tax_owed(listings: Iterable[Listing]) -> dict:
    if os.environ.get("FORECLOSURE_TAX_OWED", "1") == "0":
        return {"stamped": 0, "skipped": "disabled"}

    listings = list(listings)
    stamped = 0
    index: dict[tuple, dict] = {}

    # Pass 1 — normalize each tax lead's own amount.
    for li in listings:
        bal, kind, year = _extract(li)
        if bal is None:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["tax_owed"] = {
            "balance": bal, "kind": kind, "source": li.source,
            "year": year, "basis": "own_record",
        }
        stamped += 1
        if (li.parcel_id or "").strip():
            index.setdefault(_county_county_key(li),
                             {"balance": bal, "kind": kind, "source": li.source, "year": year})

    # Pass 2 — cross-reference onto same-parcel leads from other sources.
    xref = 0
    for li in listings:
        if not isinstance(li.raw, dict) or li.raw.get("tax_owed"):
            continue
        if not (li.parcel_id or "").strip():
            continue
        hit = index.get(_county_county_key(li))
        if hit:
            li.raw["tax_owed"] = {**hit, "basis": "parcel_cross_ref"}
            xref += 1

    log.info("tax_owed.done", stamped=stamped, cross_referenced=xref,
             parcels_indexed=len(index))
    return {"stamped": stamped, "cross_referenced": xref, "parcels_indexed": len(index)}
