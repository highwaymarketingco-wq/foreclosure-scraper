"""County eviction-pressure market signal (LSC Civil Court Data Initiative).

The LSC data is AGGREGATE (county-level eviction filings rate per 100 renter
households) — de-identified, so it is NOT per-case leads. But the county rate is
a real distress-MARKET signal: a high/rising eviction rate means a renter-heavy,
financially-stressed local market (more motivated landlords, more distressed
inventory). We attribute it to every in-footprint lead as market CONTEXT for
prioritization — not as a lead itself.

Offline + free: a static county->rate lookup from data/eviction_pressure.json
(refreshed from civilcourtdata.lsc.gov). Cheap dict lookup, no network, always on.
Writes raw['eviction_market'] = {rate, tier, source}.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from .models import Listing

_DATA = Path(__file__).resolve().parent / "data" / "eviction_pressure.json"
_TABLE: Optional[dict] = None


def _table() -> dict:
    global _TABLE
    if _TABLE is None:
        try:
            _TABLE = json.loads(_DATA.read_text()).get("counties", {})
        except Exception:  # noqa: BLE001
            _TABLE = {}
    return _TABLE


def enrich_eviction_market(listings: Iterable[Listing]) -> dict:
    """Attribute county eviction-pressure (LSC) to each in-footprint lead."""
    tbl = _table()
    stats = {"tagged": 0, "high": 0}
    if not tbl:
        return stats
    for li in listings:
        county = (li.county or "").replace(" County", "").strip()
        key = f"{li.state}:{county}"
        rec = tbl.get(key)
        if not rec:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["eviction_market"] = {
            "rate": rec.get("filings_rate"), "tier": rec.get("tier"),
            "source": "lsc_ccdi", "note": "county eviction filings rate/100 renter HH (market context, not a lead)",
        }
        stats["tagged"] += 1
        if rec.get("tier") == "high":
            stats["high"] += 1
    return stats
