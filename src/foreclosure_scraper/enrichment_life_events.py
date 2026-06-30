"""Life-event / elderly / probate owner-name tagging — the probate+elderly lane.

A distressed owner whose recorded name carries a LIFE ESTATE, HEIRS, ESTATE OF, ET AL, or TRUST
marker is a high-motivation seller: an elderly owner with a life estate, an inherited/probate
property, fractional heirs, or a trust-held asset. These overlay the foreclosure/tax distress with
the 'elderly' and 'probate' situations the board otherwise can't see. Pure-text, no network; runs
on the (post-promotion) owner_name so it benefits from the recovered owners.

Sets raw['life_events'] (list) so the dashboard can filter/badge them, and contributes an
'estate_elderly' distress category when the stack is present.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("life_estate", re.compile(r"\bLIFE\s*EST", re.I)),                       # elderly owner, life estate
    ("estate_probate", re.compile(r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b|\bESTATE\b", re.I)),  # inherited / probate
    ("multiple_heirs", re.compile(r"\bET\s*AL\b", re.I)),                     # fractional owners
    ("trust", re.compile(r"\bTRUST\b|TRUSTEE", re.I)),                       # trust-held
]


def enrich_life_events(listings) -> dict:
    stats: dict[str, int] = {}
    for li in listings:
        o = getattr(li, "owner_name", None) or ""
        flags = [k for k, p in _PATTERNS if p.search(o)]
        if not flags:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["life_events"] = flags
        for f in flags:
            stats[f] = stats.get(f, 0) + 1
        # surface in the distress stack so it's filterable alongside other signals
        ds = li.raw.get("distress_stack")
        if isinstance(ds, dict):
            cats = ds.setdefault("categories", [])
            if isinstance(cats, list) and "estate_elderly" not in cats:
                cats.append("estate_elderly")
    stats["tagged"] = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("life_events"))
    return stats
