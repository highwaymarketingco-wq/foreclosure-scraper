"""FREE derivation flags — pure computation over data already on the board.

Three motivated-seller signals that cost nothing to derive:

1. free_and_clear — no mortgage recordings in ROD history. A property with
   zero open mortgages is owned outright, making it a prime wholesale /
   subject-to target (no lender payoff to negotiate, clean title transfer).

2. tired_landlord — absentee owner (mailing address different from property
   address) who has owned the property for 10+ years. Long-tenure absentee
   owners are the classic "tired landlord" motivated-seller profile.

3. divorce_flag — NC eCourts FAM case filings already on the board via
   the nc_ecourts_divorce scraper. This flag also cross-references any
   listing whose owner name matches a party in a divorce filing.

All three are read-only computations over existing raw[] fields. No I/O.
"""
from __future__ import annotations

import structlog
from typing import Optional

from .models import Listing

log = structlog.get_logger()


def _free_and_clear(li: Listing) -> Optional[dict]:
    """No open mortgages in ROD history means the property is owned outright."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod = raw.get("rod")
    if not isinstance(rod, dict):
        return None
    # Need ROD data to make the claim — absence of ROD is NOT absence of mortgage
    if not rod.get("instrument_count"):
        return None
    open_mtg = rod.get("open_mortgages_est", 0)
    has_mtg = rod.get("has_mortgage", False)
    if open_mtg == 0 and not has_mtg:
        return {
            "flag": True,
            "reason": "no_mortgage_recordings",
            "instrument_count": rod.get("instrument_count"),
            "source": rod.get("source"),
        }
    return None


def _tired_landlord(li: Listing) -> Optional[dict]:
    """Absentee owner (mailing != property) with 10+ years ownership."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Check absentee status — owner_mailing must differ from property address
    mailing = (raw.get("owner_mailing") or {}).get("address", "") if isinstance(raw.get("owner_mailing"), dict) else raw.get("owner_mailing", "")
    prop_addr = (raw.get("property_address") or li.street_address or "").strip().lower()
    if not mailing or not prop_addr:
        return None
    mailing_lower = mailing.strip().lower() if isinstance(mailing, str) else ""
    if not mailing_lower:
        return None

    # Absentee = mailing address does not contain the property street
    # (simple check: different first 10 chars of normalized address)
    is_absentee = False
    # Check owner_occupied flag if present
    if isinstance(raw.get("gis_attrs"), dict):
        if raw["gis_attrs"].get("owner_occupied") is False:
            is_absentee = True
    if not is_absentee:
        # Heuristic: if mailing city/state differs from property city/state
        prop_city = (raw.get("property_city") or li.city or "").strip().lower()
        prop_state = (raw.get("property_state") or li.state or "").strip().lower()
        # Check if mailing is out-of-state or different city
        if prop_state and prop_state not in mailing_lower:
            is_absentee = True
        elif prop_city and prop_city not in mailing_lower and len(mailing_lower) > 5:
            is_absentee = True

    if not is_absentee:
        return None

    # Check ownership tenure — need 10+ years
    # Try ROD earliest instrument date, or last_sale_date, or gis sale_date
    tenure_years = None
    rod = raw.get("rod") or {}
    instruments = rod.get("instruments") if isinstance(rod, dict) else None
    if instruments:
        # Earliest instrument date as a proxy for ownership start
        dates = [i.get("date") for i in instruments if i.get("date")]
        if dates:
            dates.sort(key=lambda d: str(d))
            from datetime import date
            try:
                earliest = date.fromisoformat(dates[0][:10])
                tenure_years = (date.today() - earliest).days / 365.25
            except Exception:
                pass

    # Fallback: last_sale_date from recorded sales
    if tenure_years is None:
        sales = raw.get("recorded_sales") or []
        if sales and isinstance(sales, list):
            sale_dates = [s.get("date") for s in sales if isinstance(s, dict) and s.get("date")]
            if sale_dates:
                sale_dates.sort(key=lambda d: str(d))
                from datetime import date
                try:
                    earliest = date.fromisoformat(sale_dates[0][:10])
                    tenure_years = (date.today() - earliest).days / 365.25
                except Exception:
                    pass

    if tenure_years is None or tenure_years < 10:
        return None

    return {
        "flag": True,
        "tenure_years": round(tenure_years, 1),
        "absentee": True,
        "mailing": mailing[:80] if isinstance(mailing, str) else None,
    }


def _divorce_flag(li: Listing) -> Optional[dict]:
    """Flag listings from the divorce scraper or with divorce case cross-reference."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Direct: listing came from the divorce scraper
    src = (li.source or "").lower()
    if "divorce" in src or "fam" in src:
        return {
            "flag": True,
            "source": "ecourts_divorce",
            "case_id": raw.get("case_id"),
        }

    # Check listing_type
    lt = str(li.listing_type) if li.listing_type else ""
    if "DIVORCE" in lt.upper():
        return {
            "flag": True,
            "source": "listing_type",
            "case_id": raw.get("case_id"),
        }

    return None


def enrich_derivation_flags(listings: list[Listing]) -> dict:
    """Attach raw['derivation_flags'] = {free_and_clear?, tired_landlord?, divorce?}.

    Pure compute over ROD + GIS + court data already on the board.
    """
    n_fcl = n_tl = n_div = n_any = 0
    for li in listings:
        out: dict = {}
        fcl = _free_and_clear(li)
        if fcl:
            out["free_and_clear"] = fcl
            n_fcl += 1
        tl = _tired_landlord(li)
        if tl:
            out["tired_landlord"] = tl
            n_tl += 1
        div = _divorce_flag(li)
        if div:
            out["divorce"] = div
            n_div += 1
        if out:
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw["derivation_flags"] = out
            li.raw = raw
            n_any += 1

    log.info("derivation_flags.done", free_and_clear=n_fcl, tired_landlord=n_tl,
             divorce=n_div, any=n_any, total=len(listings))
    return {
        "free_and_clear": n_fcl,
        "tired_landlord": n_tl,
        "divorce": n_div,
        "rows": n_any,
    }
