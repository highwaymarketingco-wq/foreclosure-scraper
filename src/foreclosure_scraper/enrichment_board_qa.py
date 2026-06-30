"""Automated board data-quality verification — flags the bugs the operator keeps
catching BY HAND so every run surfaces them automatically (no network, pure-Python).

For each lead this writes a short list of QA flag strings to ``li.raw['qa_flags']``
and returns a run-summary ``{flag: count}`` so a run can log the totals. The flags
are regression tripwires for fixes that already landed plus genuine data gaps:

  dup_address        Another lead shares the same canonical street + county + state.
                     The '19 Gosnell Ave' cross-source duplicate class. dedupe.py was
                     fixed to collapse these (_canon_street signature); this flag CATCHES
                     any that slip through again. Counted as dup GROUPS (not rows).
  arv_below_asis     calc.arv_expected sits below market_value*0.97. Should be ~0 after
                     the ARV floor in valuation/calc.py — a non-zero count is a regression.
  rehab_vs_condition condition_tier says the house is great (move_in_ready / cosmetic) but
                     the rehab tier is heavy (moderate / major / heavy / gut) — a contradiction.
  missing_last_sale  A sale DATE exists in cama.last_sale_date or gis.last_sale.date but the
                     surfaced raw.last_sale is empty — assessor sale history not surfaced.
  no_sqft            Resolvable lead (has parcel_id or address) missing living_sqft.
  no_owner           Resolvable lead (has parcel_id or address) missing owner_name.

Counts are GROUP-based for dup_address (number of duplicate clusters) and ROW-based for
everything else (number of leads carrying the flag).
"""
from __future__ import annotations

import re
from collections import defaultdict

import structlog

from .dedupe import _canon_street

log = structlog.get_logger()


# Condition tiers that mean the house is in good shape (little/no rehab expected).
_GOOD_CONDITION = {"move_in_ready", "cosmetic"}
# Rehab tiers that mean a heavy/expensive rehab — contradicts a good-condition house.
_HEAVY_REHAB = {"moderate", "major", "heavy", "gut"}


def _raw(li) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _condition_tier(raw: dict) -> str | None:
    """Photo/CAMA condition tier, Vision-grounded first (mirrors valuation/calc.py)."""
    vt = (raw.get("vision") or {}).get("condition_tier") if isinstance(raw.get("vision"), dict) else None
    return vt or raw.get("condition_tier")


def _has_surfaced_last_sale(raw: dict) -> bool:
    """True if the surfaced raw['last_sale'] holds anything real."""
    ls = raw.get("last_sale")
    if isinstance(ls, dict):
        return any(ls.get(k) for k in ("date", "amount", "price", "last_sale_date", "last_sale_amount"))
    return bool(ls)


def _source_sale_date(raw: dict) -> bool:
    """True if the assessor/GIS layer carries a recorded sale DATE for this lead."""
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    if cama.get("last_sale_date"):
        return True
    gls = (raw.get("gis") or {}).get("last_sale") if isinstance(raw.get("gis"), dict) else None
    if isinstance(gls, dict) and gls.get("date"):
        return True
    return False


def enrich_board_qa(listings) -> dict:
    """Verify the board, write per-lead ``raw['qa_flags']``, return ``{flag: count}``.

    Pure-Python, no network. Counts:
      - dup_address  → number of duplicate GROUPS (clusters of 2+ sharing a key)
      - everything else → number of leads carrying that flag
    """
    summary: dict[str, int] = defaultdict(int)
    if not listings:
        return {}

    # ---- dup_address: canonical street + county + state collision -----------
    # A surviving cross-source duplicate (the '19 Gosnell Ave' class) means dedupe
    # let two rows for the same property through. Group by the same canonical
    # signature dedupe uses, then flag every member of any 2+ group.
    dup_buckets: dict[tuple, list] = defaultdict(list)
    for li in listings:
        cs = _canon_street(" ".join((getattr(li, "street_address", "") or "").lower().replace(",", " ").split()))
        cty = re.sub(r"[^a-z0-9]", "", (getattr(li, "county", "") or "").lower())
        st = (getattr(li, "state", "") or "")
        if cs and cty and st:
            dup_buckets[(cs, cty, st)].append(li)
    dup_members: set[int] = set()
    dup_groups = 0
    for members in dup_buckets.values():
        if len(members) > 1:
            dup_groups += 1
            for li in members:
                dup_members.add(id(li))

    # ---- per-lead flags -----------------------------------------------------
    for li in listings:
        raw = _raw(li)
        flags: list[str] = []

        # dup_address (membership computed above)
        if id(li) in dup_members:
            flags.append("dup_address")

        # arv_below_asis — comp ARV under the as-is county value (floor regression)
        calc = raw.get("calc") if isinstance(raw.get("calc"), dict) else {}
        arv = calc.get("arv_expected")
        mv = getattr(li, "market_value", None)
        try:
            if arv is not None and mv and float(mv) > 0 and float(arv) < float(mv) * 0.97:
                flags.append("arv_below_asis")
        except (TypeError, ValueError):
            pass

        # rehab_vs_condition — good condition but heavy rehab tier (contradiction)
        cond = _condition_tier(raw)
        rehab_tier = calc.get("rehab_tier")
        if cond in _GOOD_CONDITION and rehab_tier in _HEAVY_REHAB:
            flags.append("rehab_vs_condition")

        # missing_last_sale — assessor/GIS has a sale date but it isn't surfaced
        if _source_sale_date(raw) and not _has_surfaced_last_sale(raw):
            flags.append("missing_last_sale")

        # no_sqft / no_owner — resolvable lead missing core specs
        resolvable = bool((getattr(li, "parcel_id", "") or "").strip()
                          or (getattr(li, "street_address", "") or "").strip())
        if resolvable:
            if not getattr(li, "living_sqft", None):
                flags.append("no_sqft")
            if not (getattr(li, "owner_name", "") or "").strip():
                flags.append("no_owner")

        if flags:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["qa_flags"] = flags
            for f in flags:
                # dup_address counted by GROUP below, not per-row.
                if f != "dup_address":
                    summary[f] += 1

    if dup_groups:
        summary["dup_address"] = dup_groups

    out = dict(summary)
    if out:
        log.info("board_qa.summary", **out)
    return out
