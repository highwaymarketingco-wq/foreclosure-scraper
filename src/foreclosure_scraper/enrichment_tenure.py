"""Owner-tenure enrichment — long-held property = high-equity proxy (FREE, local).

The pre-foreclosure operators' filter (from the market threads): target owners who
have HELD 7+ YEARS, usually 50+. Long tenure + a distress signal (delinquency,
probate, foreclosure) = an owner with real equity AND real pressure — the opposite
of someone underwater with no options. "Someone delinquent with 40% equity and an
out-of-state address is a completely different conversation."

Computed LOCALLY from the GIS/CAMA last-sale year already on the lead — no network.
Flags raw['tenure'] = {years_held, long_tenure}. Feeds the grade + the outbound
segmentation (long-tenure + absentee = the top of the call list).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

from .models import Listing

LONG_TENURE_YEARS = 7


def _last_sale_year(li: Listing) -> Optional[int]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    gis = raw.get("gis") or {}
    ls = gis.get("last_sale") or {}
    cama = raw.get("cama") or {}
    cand = [
        ls.get("date"), ls.get("year"), gis.get("last_sale_date"),
        cama.get("last_sale_date"), cama.get("sale_date"),
        getattr(li, "last_sale_date", None),
    ]
    for v in cand:
        if v:
            m = re.search(r"(19|20)\d{2}", str(v))
            if m:
                return int(m.group(0))
    return None


def enrich_tenure(listings: Iterable[Listing], now_year: Optional[int] = None) -> dict:
    now_year = now_year or datetime.utcnow().year
    stats = {"computed": 0, "long_tenure": 0}
    for li in listings:
        y = _last_sale_year(li)
        if not y or y > now_year:
            continue
        years = now_year - y
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["tenure"] = {"years_held": years, "long_tenure": years >= LONG_TENURE_YEARS}
        stats["computed"] += 1
        if years >= LONG_TENURE_YEARS:
            stats["long_tenure"] += 1
    return stats
