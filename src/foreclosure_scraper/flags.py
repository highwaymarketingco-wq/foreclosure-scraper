"""Compute investor-relevant flags from enriched listing data.

Each flag is a simple boolean we can show in the Sheet. Sources:
  * absentee_owner — parcel address ≠ owner mailing address (county GIS)
  * high_equity / low_equity / negative_equity: read from raw['equity'], the equity engine's
    figure, which has already passed the ARV trust gate. NOT computed here any more: the
    legacy version subtracted the LAST SALE PRICE from a Zestimate (or tax_value x 1.25) and
    called the difference equity, which ignores years of paydown, sits outside the ARV trust
    gate, and rendered as a green chip on a card whose equity the board had withheld (audit
    2026-09-21, F19). `high_equity` is only stamped when the payoff behind the figure is a
    recorded fact (`equity.evidenced`); an equity assumed off the assessed value does not
    earn the chip.
  * vacant — keyword scan + (future) USPS vacancy API
  * fixer / as-is / fire / etc. — keyword scan of description
  * preforeclosure / auction / reo — listing_type
"""
from __future__ import annotations

import re
from typing import Iterable

from .models import Listing

NEGATIVE_KEYWORDS = (
    "fire damage", "burned", "smoke damage", "water damage", "flood",
    "mold", "foundation", "structural", "tear down", "vacant", "abandoned",
    "boarded", "hoarder", "as-is", "as is", "needs work", "fixer", "tlc",
    "investor special", "rehab", "gutted", "no power", "no water",
    "termite", "uninhabitable", "condemned",
)
POSITIVE_KEYWORDS = (
    "renovated", "remodeled", "updated", "move-in ready", "turnkey",
    "new roof", "new hvac", "new kitchen", "granite", "hardwood",
    "well maintained", "pristine",
)


_EQUITY_FLAGS = ("high_equity", "low_equity", "negative_equity")


def _norm_addr(a: str | None) -> str:
    if not a:
        return ""
    a = re.sub(r"[^A-Za-z0-9 ]", " ", a).lower()
    return " ".join(a.split())


def _flag_keywords(text: str) -> list[str]:
    if not text:
        return []
    low = text.lower()
    out: list[str] = []
    for kw in NEGATIVE_KEYWORDS + POSITIVE_KEYWORDS:
        if kw in low:
            out.append(kw)
    return out


def _flag_one(li: Listing) -> list[str]:
    flags: list[str] = list(li.raw.get("flags", []) if isinstance(li.raw, dict) else [])

    # Absentee owner: county GIS gave us owner mailing addr; compare to property addr
    gis = li.raw.get("gis") if isinstance(li.raw, dict) else None
    if isinstance(gis, dict):
        owner_mail = _norm_addr(gis.get("mailing"))
        prop_addr = _norm_addr(li.street_address)
        if owner_mail and prop_addr and prop_addr.split()[0:2] != owner_mail.split()[0:2]:
            flags.append("absentee_owner")

    # Equity flags come from the equity engine, never from a re-derivation here. A withheld
    # or missing figure (no `pct`) earns no flag. Legacy flags that were stamped by an older run
    # and are still in raw['flags'] are dropped, so a stale `high_equity` cannot survive.
    flags = [f for f in flags if f not in _EQUITY_FLAGS]
    eq = li.raw.get("equity") if isinstance(li.raw, dict) else None
    pct = eq.get("pct") if isinstance(eq, dict) else None
    if isinstance(pct, (int, float)):
        if eq.get("is_underwater") or pct <= 0:
            flags.append("negative_equity")
        elif pct >= 0.50 and eq.get("evidenced") is True:
            flags.append("high_equity")
        elif pct < 0.20:
            flags.append("low_equity")

    # Vacant / fire / fixer keywords from description
    flags += _flag_keywords(" ".join(filter(None, (li.description, li.legal_description))))

    # listing_type derived flags
    if li.listing_type:
        lt = li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type)
        if "lis_pendens" in lt or "preforeclosure" in lt:
            flags.append("preforeclosure")
        elif "auction" in lt:
            flags.append("auction")
        elif "reo" in lt:
            flags.append("bank_owned")

    # Dedupe + cap
    seen: list[str] = []
    for f in flags:
        if f not in seen:
            seen.append(f)
    return seen[:10]


def compute_flags(listings: Iterable[Listing]) -> None:
    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["flags"] = _flag_one(li)
