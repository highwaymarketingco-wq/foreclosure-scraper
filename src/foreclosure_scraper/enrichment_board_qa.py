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
  arv_above_asis     The MIRROR of arv_below_asis, and the reason the trailer-at-$780,300
                     bug ran unwatched: this file tripwired the floor working (ARV pushed
                     too LOW) but nothing watched the floor OVER-shooting. Fires when
                     arv_expected exceeds the county's 100%-basis value by more than
                     _ARV_ABOVE_MULT. NEVER computed against SC `assessed_value` — that is
                     a 4%/6% statutory ratio number, so arv/assessed there is a unit error
                     that would fire on 58.8% of SC rows and 1.4% of NC ones.
  arv_sanity_flag    calc raised one or more entries in calc.arv_flags (ppsf ceiling,
                     comp/property-kind mismatch, rejected ARV floor, shared-centroid
                     comps). Per-flag counts also land in the run summary as
                     arv_flag:<name> so a regression in any single guard is visible.
  arv_withheld       calc computed an ARV and then refused to publish it. Expected to be
                     small and non-zero; a sudden jump means an upstream join broke.
  verdict_on_flagged_arv
                     A deal_status verdict is published on a lead whose ARV carries any
                     calc arv_flag. MUST BE ZERO. This is the tripwire for the defect
                     where the board withheld the LETTER grade on 3646 Summer Rd and
                     still printed "GREAT · ROI 192.6% · max bid $1,271,200" beside it:
                     the letter and the verdict were two separate decisions, so fixing
                     one left the other lying. Now both read
                     valuation.grading.ARV_FLAGS_CONTRADICTED / _WEAK_EVIDENCE.
  bid_on_contradicted_arv
                     max_bid_70 / roi_pct / estimated_profit / wholesale_mao published on
                     an ARV that another record contradicts. MUST BE ZERO — these are the
                     board's ranking keys, so leaving them on a contradicted ARV sorts the
                     least trustworthy leads to the top of the page.
  derived_without_arv
                     Any of those figures published with NO arv_expected at all. MUST BE
                     ZERO; a non-zero count means a writer serialized a stale calc block.
  gis_row_shared     This lead's (assessed_value, acreage, owner_name) triple is shared
                     with a DIFFERENT parcel_id in the same county — one assessor row
                     fanned out across several leads. The durable detector for the
                     point-in-polygon fan-out.
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
from .valuation.grading import (
    ARV_DERIVED_MONEY_FIELDS,
    ARV_FLAGS_CONTRADICTED,
    ARV_VERDICT_FIELDS,
)

log = structlog.get_logger()


# Condition tiers that mean the house is in good shape (little/no rehab expected).
_GOOD_CONDITION = {"move_in_ready", "cosmetic"}
# Rehab tiers that mean a heavy/expensive rehab — contradicts a good-condition house.
_HEAVY_REHAB = {"moderate", "major", "heavy", "gut"}

# arv_above_asis threshold. Measured on the live board, ARV / county 100%-basis
# value runs p50 1.00 / p90 2.10 / p95 3.98 for improved property and p50 1.10 /
# p90 7.61 for land (land assessments lag market much harder). 8x is above both
# p95s, so this is a tripwire for breakage, not a style critique of the tail —
# valuation/calc.py owns the graduated 4x/6x/10x/20x response.
_ARV_ABOVE_MULT = 8.0


def _raw(li) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _anchor_100pct(li, raw: dict) -> float | None:
    """County valuation on a FULL-MARKET basis, or None.

    Mirrors valuation.calc._anchor_value. `assessed_value` is excluded on
    purpose: North Carolina publishes assessed == market (97.2% of rows, never
    with cents) but South Carolina publishes a statutory RATIO value — 4% legal
    residence / 6% other — so SC's median market/assessed is 18.86 and 4,366 of
    7,162 SC rows carry cents. A ratio like arv/assessed is therefore a units
    error in SC, not a signal.
    """
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    for v in (getattr(li, "market_value", None), cama.get("appraised_value"),
              getattr(li, "tax_value", None)):
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            continue
        if f and f > 1000:
            return f
    return None


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

    # ---- gis_row_shared: one assessor row fanned out across many parcels ----
    # The mechanism behind seven different Spartanburg addresses all carrying
    # ARV $770,400 / assessed $3,227.12 / acreage 5.02: the GIS enricher queries
    # by lat/lng, thousands of leads share a geocoder city-centroid coordinate,
    # and one point-in-polygon hit gets stamped on every one of them. The fix
    # belongs upstream (query by parcel_id first); THIS is the detector that
    # makes a relapse visible on the very next run instead of on the next
    # complaint. Keyed on the assessor values themselves, so it catches the
    # fan-out no matter which enricher caused it.
    gis_buckets: dict[tuple, set] = defaultdict(set)
    gis_members: dict[tuple, list] = defaultdict(list)
    for li in listings:
        av = getattr(li, "assessed_value", None)
        ac = getattr(li, "acreage", None)
        own = (getattr(li, "owner_name", "") or "").strip().lower()
        cty = re.sub(r"[^a-z0-9]", "", (getattr(li, "county", "") or "").lower())
        pid = re.sub(r"[^a-z0-9]", "", (getattr(li, "parcel_id", "") or "").lower())
        if av and ac and own and cty and pid:
            key = (cty, getattr(li, "state", ""), round(float(av), 2), round(float(ac), 4), own)
            gis_buckets[key].add(pid)
            gis_members[key].append(li)
    shared_members: set[int] = set()
    shared_groups = 0
    for key, pids in gis_buckets.items():
        if len(pids) > 1:          # same assessor row, DIFFERENT parcels
            shared_groups += 1
            for li in gis_members[key]:
                shared_members.add(id(li))

    # ---- per-lead flags -----------------------------------------------------
    for li in listings:
        raw = _raw(li)
        flags: list[str] = []

        # dup_address (membership computed above)
        if id(li) in dup_members:
            flags.append("dup_address")

        # gis_row_shared — one assessor row stamped onto several distinct parcels
        if id(li) in shared_members:
            flags.append("gis_row_shared")

        # arv_below_asis — comp ARV under the as-is county value (floor regression)
        calc = raw.get("calc") if isinstance(raw.get("calc"), dict) else {}
        arv = calc.get("arv_expected")
        mv = getattr(li, "market_value", None)
        try:
            if arv is not None and mv and float(mv) > 0 and float(arv) < float(mv) * 0.97:
                flags.append("arv_below_asis")
        except (TypeError, ValueError):
            pass

        # arv_above_asis — the missing mirror of the check above
        anchor = _anchor_100pct(li, raw)
        try:
            if arv is not None and anchor and float(arv) > anchor * _ARV_ABOVE_MULT:
                flags.append("arv_above_asis")
        except (TypeError, ValueError):
            pass

        # arv_sanity_flag / arv_withheld — surface valuation/calc.py's own verdict
        sanity = calc.get("arv_flags")
        if isinstance(sanity, list) and sanity:
            flags.append("arv_sanity_flag")
            for f in sanity:
                summary[f"arv_flag:{f}"] += 1
        if calc.get("arv_withheld") is not None:
            flags.append("arv_withheld")

        # ---- ARV trust tripwires (all three must read ZERO) -----------------
        # valuation.grading.apply_arv_trust_gate strips these fields before the
        # calc block is serialized. This does not re-do that work — it checks
        # that it happened, on the artifact as published, using the same two
        # flag sets. A regression here is silent everywhere else: the numbers
        # look completely normal, they are just derived from an ARV the engine
        # itself said not to trust.
        sanity_set = set(sanity) if isinstance(sanity, list) else set()
        _has_money = any(calc.get(f) is not None for f in ARV_DERIVED_MONEY_FIELDS)
        _has_verdict = any(calc.get(f) is not None for f in ARV_VERDICT_FIELDS)
        if sanity_set and _has_verdict:
            flags.append("verdict_on_flagged_arv")
        if (sanity_set & ARV_FLAGS_CONTRADICTED) and _has_money:
            flags.append("bid_on_contradicted_arv")
        if calc.get("arv_expected") is None and (_has_money or _has_verdict):
            flags.append("derived_without_arv")

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
                # dup_address / gis_row_shared counted by GROUP below, not per-row.
                if f not in ("dup_address", "gis_row_shared"):
                    summary[f] += 1

    if dup_groups:
        summary["dup_address"] = dup_groups
    if shared_groups:
        summary["gis_row_shared"] = shared_groups
        summary["gis_row_shared_rows"] = len(shared_members)

    out = dict(summary)
    if out:
        log.info("board_qa.summary", **out)
    return out
