"""Compute investor-relevant flags from enriched listing data.

Each flag is a simple boolean we can show in the Sheet. Sources:
  * absentee_owner — parcel address ≠ owner mailing address (county GIS)
  * high_equity / low_equity / negative_equity — Zestimate vs recorded mortgage
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

    # Equity flags: zestimate (or tax_value × 1.25 fallback) vs recorded sale_amount
    zest = (li.raw.get("zillow") or {}).get("zestimate") if isinstance(li.raw, dict) else None
    arv_proxy = zest or (li.tax_value * 1.25 if li.tax_value else None) or li.market_value
    last_sale = (gis or {}).get("last_sale", {}) if isinstance(gis, dict) else {}
    last_sale_amount = last_sale.get("amount") or li.judgment_amount

    if arv_proxy and last_sale_amount:
        equity_pct = (arv_proxy - last_sale_amount) / arv_proxy
        if equity_pct >= 0.50:
            flags.append("high_equity")
        elif equity_pct <= 0:
            flags.append("negative_equity")
        elif equity_pct < 0.20:
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
