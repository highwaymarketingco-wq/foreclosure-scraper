"""Strategy-fit tagger — label each lead with the exit strategies it actually
fits, so the operator can filter the board by how they'd work it (LOCAL, no network).

Reads the signals the pipeline already computed (equity, tenure, condition,
listing type, property kind, tax status, distress stack) and sets
raw['strategy_fit'] = {"tags": [...], "reasons": {...}}. Tags:

  WHOLESALE       improved residential + real equity + a distress signal — an
                  assignable cash deal with spread (offer < ARV, assign the contract).
  LAND_WHOLESALE  vacant land + a motivation (delinquent tax / long-held / probate)
                  — the construction-company "buy box" play: tie it up, assign to a
                  builder who wants land in that area.
  SUBJECT_TO      residential foreclosure/lis-pendens with LOW equity — take over the
                  existing mortgage instead of buying the (thin) equity.
  FIX_FLIP        residential in rough condition (major/gut) with equity to renovate.
  BUY_HOLD        residential, livable, not severely distressed — rental hold.
  GATOR           any assignable deal (WHOLESALE/LAND_WHOLESALE) — a transactional /
                  EMD funding fit, not a property type.

Heuristic + transparent; every tag carries a one-line reason. Gate STRATEGY_FIT=0.
"""
from __future__ import annotations

import os
from typing import Iterable

from .models import Listing

_ENABLED = os.environ.get("STRATEGY_FIT") != "0"

_LAND_KINDS = {"land", "vacant_land", "vacant", "lot", "acreage"}
_ROUGH_CONDITION = {"major", "gut"}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_land(li: Listing) -> bool:
    pk = (li.property_kind.value if hasattr(li.property_kind, "value") else str(li.property_kind or "")).lower()
    if any(k in pk for k in _LAND_KINDS):
        return True
    desc = (li.description or "").lower()
    return "vacant lot" in desc or "vacant land" in desc or "vacant parcel" in desc


def _equity_pct(raw: dict):
    eq = raw.get("equity") or {}
    p = _f(eq.get("pct"))
    if p is not None and p > 1:   # stored as 0-100 in some paths
        p = p / 100.0
    return p


def enrich_strategy_fit(listings: Iterable[Listing]) -> dict:
    stats = {"tagged": 0}
    if not _ENABLED:
        return stats
    counts: dict[str, int] = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        lt = (li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type or "")).lower()
        ds = raw.get("distress_stack") or {}
        has_distress = bool(ds.get("tier") in ("HOT", "WARM")) or bool(ds.get("signals"))
        tax_owed = bool((raw.get("tax_owed") or {}).get("balance"))
        tenure = raw.get("tenure") or {}
        long_tenure = bool(tenure.get("long_tenure"))
        probate = "probate" in lt or lt in ("estate_lead",) or bool(raw.get("life_events"))
        eq = _equity_pct(raw)
        cond = (raw.get("condition_tier") or "").lower()
        is_land = _is_land(li)
        is_foreclosure = lt in ("foreclosure_sale", "lis_pendens", "notice_of_sale", "sheriff_sale")

        tags: list[str] = []
        reasons: dict[str, str] = {}

        # High equity is the wholesale/flip prerequisite. We only have a computed
        # equity % on some leads; when it's unknown, LONG TENURE (held 7+ yrs) is a
        # solid proxy for real equity, so we accept that in its place — but never
        # tag on a blank (that's what made the first pass fire on everything).
        high_equity = (eq is not None and eq >= 0.40) or (eq is None and long_tenure)
        some_equity = (eq is not None and eq >= 0.25) or (eq is None and long_tenure)
        low_equity = eq is not None and eq < 0.20

        if is_land and (tax_owed or long_tenure or probate or has_distress):
            tags.append("LAND_WHOLESALE")
            reasons["LAND_WHOLESALE"] = "vacant land + " + (
                "delinquent tax" if tax_owed else "long-held (equity)" if long_tenure else
                "probate/estate" if probate else "distress signal")

        if (not is_land) and high_equity and has_distress:
            tags.append("WHOLESALE")
            reasons["WHOLESALE"] = ("residential + "
                + (f"~{int(eq*100)}% equity" if eq is not None else "long-held (equity proxy)")
                + " + distress")

        if (not is_land) and is_foreclosure and low_equity:
            tags.append("SUBJECT_TO")
            reasons["SUBJECT_TO"] = f"foreclosure w/ low equity (~{int(eq*100)}%) — take over payments"

        if (not is_land) and cond in _ROUGH_CONDITION and some_equity:
            tags.append("FIX_FLIP")
            reasons["FIX_FLIP"] = f"rough condition ({cond}) + equity to renovate"

        if "WHOLESALE" in tags or "LAND_WHOLESALE" in tags:
            tags.append("GATOR")
            reasons["GATOR"] = "assignable deal — transactional/EMD funding fit"

        if tags:
            raw["strategy_fit"] = {"tags": tags, "reasons": reasons}
            li.raw = raw
            stats["tagged"] += 1
            for t in tags:
                counts[t] = counts.get(t, 0) + 1
    stats["by_tag"] = counts
    return stats
