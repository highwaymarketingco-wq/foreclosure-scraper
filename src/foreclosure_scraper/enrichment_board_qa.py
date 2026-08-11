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
  gis_row_shared     This lead's (assessed_value, acreage, market_value, owner_name)
                     tuple is shared with a DIFFERENT parcel_id in the same county —
                     one assessor row fanned out across several leads. The durable
                     detector for the point-in-polygon fan-out.
  anchor_shared_across_parcels
                     The county 100%-basis figure this lead's ARV rests on is ONE
                     number stamped across more than _SHARED_ANCHOR_MIN_PARCELS
                     distinct parcels in the same county. Unlike gis_row_shared this
                     needs no owner or acreage agreement — it catches a value-only
                     stamp, which is the shape the fan-out actually takes when the
                     rest of the assessor row never arrives. Retracts the money and
                     the verdict; see the block above `shared_anchor_stamps`.
  owner_record_mismatch
                     `raw['gis']['owner']` and `owner_name` name two parties with NO
                     name token in common — not a spelling, suffix, spouse or
                     lender-vs-borrower difference, two different people. The assessor
                     row joined to this lead may describe a different property.
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
import statistics
from collections import defaultdict

import structlog

from .dedupe import _canon_street
from .distress_score import retract_equity_rank
from .enrichment_equity import withhold_equity
from .valuation.grading import (
    ARV_DERIVED_MONEY_FIELDS,
    ARV_FLAGS_CONTRADICTED,
    ARV_VERDICT_FIELDS,
    gate_calc_dict,
)

log = structlog.get_logger()

# ===========================================================================
# FLAG STRINGS INTRODUCED HERE (interface — name them, never re-spell them).
# Four silent failures in this project have been reader/writer name mismatches.
#
#   SHARED_ANCHOR_FLAG  written to BOTH raw['qa_flags'] and
#                       raw['calc']['arv_flags']. The calc entry is the one that
#                       matters: it is the vocabulary the trust gate, the CSV
#                       and docs/dashboard.js all already speak. It is spelled
#                       to be legible to dashboard.js:1506 as it stands — that
#                       reader marks a flag "bad" when the name contains "arv"
#                       and a word from its verdict list, and this name contains
#                       NEITHER, so it renders as a neutral flag until the
#                       dashboard adds a caption. It must be added to
#                       valuation.grading.ARV_FLAGS_CONTRADICTED by that file's
#                       owner; until then this module does the withholding
#                       itself and the classification is belt-and-braces.
#   OWNER_MISMATCH_FLAG raw['qa_flags'] only. Display-only, deliberately: see
#                       the block above `owner_records_disagree`.
# ===========================================================================
#   SALE_PASSED_FLAG    raw['qa_flags']. `enrichment_board_quality` is what
#                       DETECTS the passed sale (it owns auction_status) and it
#                       writes raw['sale_date_passed'] — but web_artifact.py's
#                       RAW_KEEP is a WHITELIST, that key is not on it, and the
#                       whitelist's own comment says "forgetting to whitelist
#                       this would gather them and throw them away at publish".
#                       `qa_flags` IS whitelisted (web_artifact.py:431, :675),
#                       so mirroring the signal here is what makes it reach the
#                       board at all until RAW_KEEP is updated. Same string as
#                       the raw key and as the normalized `auction_status`
#                       value, so there is one word for one fact.
SHARED_ANCHOR_FLAG = "anchor_shared_across_parcels"
OWNER_MISMATCH_FLAG = "owner_record_mismatch"
SALE_PASSED_FLAG = "sale_date_passed"


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


def _anchor_field(li, raw: dict) -> tuple[str | None, float | None]:
    """(which field supplied the county 100%-basis value, that value).

    Mirrors valuation.calc._anchor_value. `assessed_value` is excluded on
    purpose: North Carolina publishes assessed == market (97.2% of rows, never
    with cents) but South Carolina publishes a statutory RATIO value — 4% legal
    residence / 6% other — so SC's median market/assessed is 18.86 and 4,366 of
    7,162 SC rows carry cents. A ratio like arv/assessed is therefore a units
    error in SC, not a signal.

    The FIELD is returned as well as the value because `shared_anchor_stamps`
    corroborates a suspected stamp against the lead's own tax_value, and that
    only counts as independent evidence when tax_value is not itself the field
    carrying the anchor.
    """
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    for name, v in (("market_value", getattr(li, "market_value", None)),
                    ("cama.appraised_value", cama.get("appraised_value")),
                    ("tax_value", getattr(li, "tax_value", None))):
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            continue
        if f and f > 1000:
            return name, f
    return None, None


def _anchor_100pct(li, raw: dict) -> float | None:
    """County valuation on a FULL-MARKET basis, or None. See `_anchor_field`."""
    return _anchor_field(li, raw)[1]


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


# ===========================================================================
# ONE COUNTY APPRAISAL STAMPED ACROSS A WHOLE COUNTY'S WORTH OF LEADS
#
# THE DEFECT, measured on the live board. `market_value == 299453.0` appears on
# 1,433 leads spanning 1,354 distinct parcel_ids, 1,432 of them Lincoln County
# NC. 1,429 publish a max bid — $320,145,300 of them — and ~1,119 publish equity
# summing ~$155M. It is ONE parcel's appraisal: 308 S Academy St, Lincolnton, a
# COMMERCIAL building (PIN 3623836662, AMERO PROPERTIES LLC, TOTALVALUE
# 299,453). Every Lincoln lead from the delinquent-tax PDF is address-less, so
# it inherits the county-centroid fallback coordinate (35.470, -81.255) from
# enrichment_geocode; the GIS enricher queries BY POINT before it queries by
# parcel, that point falls inside 308 S Academy St, and the same row comes back
# for all of them. The leads' own records say otherwise: of the 138 carrying
# their own tax_value the median is $124,527 and 82 differ by more than 2x, and
# the 58 with their own assessed_value span $3,582 to $1,491,777 — a 416x spread
# under a constant "market value".
#
# WHY gis_row_shared FIRED ON NONE OF THEM. It gated on
# `if av and ac and own and cty and pid`; assessed_value is null on 1,373 of
# these and acreage on 1,344, so the conjunction never evaluated. It also keyed
# on assessed_value and never on market_value, which is the field carrying the
# stamp. Both are fixed below — but relaxing that detector is not sufficient,
# because it also keys on OWNER, and these 1,433 leads carry 1,113 DISTINCT
# owner names. Only the value fanned out; the rest of the assessor row never
# arrived. A value-only detector is therefore a different detector, not a looser
# one, and this is it.
#
# THE RULE. A (county, state, anchor-value) group is a STAMP when it covers more
# than _SHARED_ANCHOR_MIN_PARCELS distinct parcels AND either
#
#   (a) the value carries sub-$100 precision, or
#   (b) the group's members that hold an INDEPENDENT tax_value disagree with it
#       by more than _SHARED_ANCHOR_RATIO at the median, over at least
#       _SHARED_ANCHOR_MIN_CORROB such records.
#
# Clause (a) is what does the work and it is the reason this is surgical rather
# than a dragnet. Measured over every (county, state, anchor) group on the live
# board, the NON-ROUND groups run 1,352 parcels (Lincoln $299,453) and then 7,
# 7, 5, 5, 5 — a gap of two orders of magnitude, because an assessor's per-parcel
# figure repeating hundreds of times at dollar precision is not something that
# happens by chance, while seven identical spec-built houses in one subdivision
# is. The ROUND groups are the opposite and must NOT fire: McDowell $3,000 x 214
# parcels, Spartanburg $17,500 x 203, $15,000 x 167, $18,000 x 145 are a
# delinquent-tax roll's genuine floor valuations for near-worthless slivers, and
# blanking their economics would be gutting the normal case for nothing —
# $3,000 anchors produce $1,700 max bids, not $320M of them. Clause (b) is the
# safety net for a future stamp that happens to land on a round number; it fires
# on nothing today, by design. It reads tax_value only and only when tax_value
# is not itself the anchor, because SC `assessed_value` is a 4%/6% statutory
# ratio and comparing it to market value manufactures a 16.7x "disagreement" on
# every SC row (the same units error `_anchor_field` documents).
#
# WHAT IS WITHHELD, and the ORDERING PROBLEM THIS RESOLVES.
#
# gis_row_shared was in no Python trust set — display-only, and by construction
# unable to gate money, because board QA runs LAST (calc/grade -> gis_derived ->
# equity -> distress -> derived_signals -> data_quality -> board_quality ->
# board_qa -> write). That ordering is not an accident to be worked around: a
# shared value is a CROSS-ROW fact. No single lead contains the evidence, and
# the evidence does not exist until every lead is in memory — which is exactly
# the position board QA occupies and no earlier pass does.
#
# So the resolution is not to move the detection earlier. It is to make this
# pass RETRACT rather than merely annotate. Retraction is safe to run last
# precisely because it only ever narrows: it deletes calc fields, replaces the
# equity figure with the existing `withheld` marker, and re-derives a distress
# tier from which the equity term has been removed. Nothing between here and the
# writer reads any of it. This is the same job `grading.gate_calc_dict` was
# built for ("a board carried over from a run that predates this gate").
#
# The withholding follows the CONTRADICTED contract exactly, not a fourth rule
# of its own: the verdict and every ARV-derived dollar go, the ARV itself stays
# (grading: "the gate withholds what is DERIVED from the ARV, not the ARV"), and
# equity goes because equity is the largest ARV-derived dollar on the card.
# `gate_calc_dict` is called as well as the explicit strip, so that the moment
# SHARED_ANCHOR_FLAG is added to `grading.ARV_FLAGS_CONTRADICTED` the normal
# path does this work and the code here becomes a no-op that agrees with it.
#
# ONLY leads whose ARV actually DESCENDS from the stamped figure are retracted —
# calc says so itself with `anchor_not_independent` ("this ARV was computed FROM
# the county market value, so comparing the two only restates the multiplier").
# A lead that merely carries a stamped market_value while its ARV came from real
# comps keeps its money and is flagged. On the live board that is 1,341 of the
# 1,352 detected rows; the other 11 are comp-grounded and keep everything.
# ===========================================================================
_SHARED_ANCHOR_MIN_PARCELS = 20     # 1,352 vs a 7-parcel noise floor: any 8..1,300 works
_SHARED_ANCHOR_MIN_CORROB = 3       # independent tax_values needed for clause (b)
_SHARED_ANCHOR_RATIO = 2.0          # median |disagreement| that convicts a round value
# calc's own name for "this ARV IS the county figure restated". Spelled out
# rather than imported because grading.py exports the SETS, not the members.
_ANCHOR_DERIVED_FLAG = "anchor_not_independent"


def _is_round_hundred(v: float) -> bool:
    return abs(v - round(v / 100.0) * 100.0) < 0.005


def shared_anchor_stamps(listings) -> dict[int, dict]:
    """``id(li) -> {value, field, parcels, rows, basis}`` for stamped anchors.

    Pure and side-effect free so the retraction below and the tests can both
    reach the same verdict, and so a future pipeline that gains an earlier
    whole-board pass can call it from there instead. See the block above.
    """
    buckets: dict[tuple, list] = defaultdict(list)
    for li in listings:
        raw = _raw(li)
        field, val = _anchor_field(li, raw)
        cty = re.sub(r"[^a-z0-9]", "", (getattr(li, "county", "") or "").lower())
        pid = re.sub(r"[^a-z0-9]", "", (getattr(li, "parcel_id", "") or "").lower())
        if val and cty and pid:
            buckets[(cty, getattr(li, "state", ""), round(val, 2))].append((li, field, pid))

    out: dict[int, dict] = {}
    for (cty, st, val), members in buckets.items():
        if len({pid for _, _, pid in members}) <= _SHARED_ANCHOR_MIN_PARCELS:
            continue
        basis = "sub_hundred_precision" if not _is_round_hundred(val) else None
        if basis is None:
            ratios = []
            for li, field, _ in members:
                if field == "tax_value":
                    continue            # not independent — it IS the anchor
                try:
                    tv = float(getattr(li, "tax_value", None) or 0)
                except (TypeError, ValueError):
                    continue
                if tv > 0 and abs(tv - val) > 1.0:
                    ratios.append(max(tv / val, val / tv))
            if len(ratios) < _SHARED_ANCHOR_MIN_CORROB:
                continue
            if statistics.median(ratios) <= _SHARED_ANCHOR_RATIO:
                continue
            basis = "own_records_disagree"
        info = {"value": val, "county": cty, "state": st, "basis": basis,
                "parcels": len({pid for _, _, pid in members}), "rows": len(members)}
        for li, field, _ in members:
            out[id(li)] = dict(info, field=field)
    return out


# ===========================================================================
# TWO DIFFERENT PEOPLE ON THE SAME CARD
#
# `raw['gis']['owner']` is the owner on the assessor row this lead was joined
# to; `owner_name` is the owner the SOURCE named. They differ on 5,308 of the
# 28,320 leads that carry both. Almost all of that is noise, and the reason
# `court_owner_mismatch` fires on only 31 is that a string compare is the wrong
# instrument. The real classes, from the board:
#
#   formatting        "Kendra A Mason" vs "MASON KENDRA A"
#   life estate/suffix"ADKINS GARRY WAYNE (LE)" vs "ADKINS GARRY"
#   status marker     "YOUNG SHERRILL D" vs "YOUNG SHERRILL D (DECEASED)"
#   co-owner subset   "MATHIS, JOSHUA CODY" vs "MATHIS, JOSHUA CODY;MATHIS, SHANA LOUISE"
#   article           "THOMPSON FAMILY LIMITED PARTNERSHIP" vs "THE THOMPSON ..."
#   generation        "Kenneth Wayne Peigler Jr" vs "PEIGLER KENNETH W SR"
#   lender/borrower   "DEPARTMENT OF VETERANS AFFAIRS" vs "OTT WILLIAM B III"
#   TWO DIFFERENT PARTIES  "HINES, KEITH A" vs "HAMILTON, JAMES LEE"
#
# Only the last one means the join may have landed on another property, and it
# has a clean signature: NO name token in common. Every benign class above
# shares at least a surname. Measured: 3,681 leads have zero token overlap
# (2,647 private-vs-private, 1,034 with an institution on one side), against
# 24,635 that overlap and are correctly left alone.
#
# DISPLAY-ONLY, DELIBERATELY, and this is a judgement not an oversight. A
# disagreement here has two readings and they point opposite ways: the assessor
# row belongs to another property (bad join, the valuation is wrong), or the
# assessor row is simply FRESHER than the court record because the property
# sold (good data, the valuation is fine, and the owner change is itself a
# lead). Nothing in the record distinguishes them, 3,681 leads is 9.6% of the
# board, and 3,190 of them publish a max bid. Blanking money on a signal that is
# right half the time would be gutting the normal case to punish an ambiguity —
# so this is surfaced for the operator and gates nothing. Contrast
# SHARED_ANCHOR_FLAG above, which has only one reading.
# ===========================================================================
_NAME_NOISE = frozenset({
    "JR", "SR", "II", "III", "IV", "LE", "ETUX", "ETAL", "ET", "UX", "AL", "THE",
    "AND", "HEIRS", "HEIR", "OF", "DECEASED", "DECD", "ESTATE", "ESTATES",
    "TRUSTEE", "TRUSTEES", "TRUST", "AKA", "FKA", "NKA", "DBA", "MRS", "LIFE",
    "REVOCABLE", "IRREVOCABLE", "LIVING", "FAMILY", "TEN", "WROS", "HUSBAND",
    "WIFE", "SURVIVOR", "SURVIVORSHIP", "ENTIRETY", "TENANTS", "COMMON",
    "UNKNOWN", "OWNER", "OWNERS", "CURRENT", "OCCUPANT", "NONE", "TBD", "SAME",
})
# Owner strings that name nobody. A placeholder is not a disagreement.
_NAME_PLACEHOLDER = re.compile(
    r"^\s*(unknown|unknown owner|owner|current owner|occupant|n/?a|none|tbd|"
    r"not available|no owner|see deed)\s*$", re.I)
_NAME_SPLIT = re.compile(r"[^A-Z0-9]+")
_NAME_TAG = re.compile(r"<[^>]*>")
# Institutional / lender words. Only used to LABEL the disagreement in the run
# summary — an institution on one side is the ordinary lender-vs-borrower case
# and is far less likely to be a bad join than two private individuals.
_INSTITUTIONAL = re.compile(
    r"\b(LLC|INC|CORP|CORPORATION|COMPANY|LP|LLP|PLLC|LTD|PARTNERSHIP|BANK|"
    r"MORTGAGE|LOAN|LENDING|FINANCIAL|CREDIT UNION|FEDERAL|NATIONAL ASSOCIATION|"
    r"SERVICING|CAPITAL|FUNDING|FANNIE MAE|FREDDIE MAC|HUD|SECRETARY|"
    r"VETERANS AFFAIRS|HOUSING|AUTHORITY|CHURCH|CITY|COUNTY|TOWN|STATE|SCHOOL|"
    r"ASSOCIATION|ASSN|PROPERTIES|HOLDINGS|INVESTMENTS|REALTY|HOMES|"
    r"DEVELOPMENT|ENTERPRISES|GROUP|MINISTRIES|FOUNDATION)\b")


def _name_tokens(name: str) -> set:
    """Identity-bearing tokens: no punctuation, no suffixes, no role words."""
    s = _NAME_TAG.sub(" ", (name or "").upper())
    return {t for t in _NAME_SPLIT.split(s)
            if len(t) >= 3 and t not in _NAME_NOISE and not t.isdigit()}


def owner_records_disagree(source_owner: str, gis_owner: str) -> bool:
    """True when the two owner strings name parties with NO token in common."""
    if not (source_owner or "").strip() or not (gis_owner or "").strip():
        return False
    if _NAME_PLACEHOLDER.match(source_owner) or _NAME_PLACEHOLDER.match(gis_owner):
        return False
    a, b = _name_tokens(source_owner), _name_tokens(gis_owner)
    if not a or not b:
        return False
    return not (a & b)


def _gis_owner(raw: dict) -> str:
    gis = raw.get("gis")
    return (gis.get("owner") or "") if isinstance(gis, dict) else ""


def _retract_shared_anchor(li, raw: dict, info: dict) -> dict:
    """Withhold everything a stamped county anchor cannot support. Idempotent.

    Returns ``{what: 1}`` counters so the run summary reports the damage that
    was undone rather than the number of leads that merely got a flag.
    """
    counts: dict[str, int] = {}
    calc = raw.get("calc")
    if not isinstance(calc, dict):
        return counts
    flags = list(calc.get("arv_flags") or [])
    if SHARED_ANCHOR_FLAG not in flags:
        flags.append(SHARED_ANCHOR_FLAG)
        calc["arv_flags"] = flags
    # Once grading.ARV_FLAGS_CONTRADICTED knows this string, THIS call does all
    # of the work below and the explicit strip becomes a confirming no-op.
    gate_calc_dict(calc)
    for f in ARV_DERIVED_MONEY_FIELDS + ARV_VERDICT_FIELDS:
        if calc.pop(f, None) is not None:
            counts["fields_stripped"] = counts.get("fields_stripped", 0) + 1
            if f == "max_bid_70":
                counts["max_bid_withheld"] = 1
            if f == "deal_status":
                counts["verdict_withheld"] = 1
    if info["basis"] == "assessor_row_across_parcels":
        note = (
            f"Max bid, ROI, profit and the deal verdict are withheld: the entire "
            f"assessor record this ARV rests on — owner, acreage and value alike "
            f"(${info['value']:,.0f}) — is repeated identically on "
            f"{info['parcels']:,} different parcels in this county. One row has "
            f"been stamped across many properties, so it does not describe this "
            f"one. Verify the parcel record before bidding."
        )
    else:
        note = (
            f"Max bid, ROI, profit and the deal verdict are withheld: the county "
            f"value this ARV rests on (${info['value']:,.0f}) is the SAME figure "
            f"published on {info['parcels']:,} different parcels in this county, so "
            f"it is one property's appraisal stamped across many — not this "
            f"property's. Verify the parcel record before bidding."
        )
    notes = calc.setdefault("notes", [])
    if isinstance(notes, list) and note not in notes:
        notes.append(note)
    if withhold_equity(li, "contradicted", flags):
        counts["equity_withheld"] = 1
    if retract_equity_rank(li):
        counts["distress_reranked"] = 1
    return counts


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
    #
    # THE GATE WAS THE BUG. `if av and ac and own and cty and pid` required BOTH
    # assessed_value and acreage to be present, and on the biggest real fan-out
    # on the board — 1,433 Lincoln County leads carrying one $299,453 appraisal
    # — assessed_value is null on 1,373 and acreage on 1,344, so the conjunction
    # never evaluated and the detector built for this fired on none of them. The
    # key also never included market_value, which is the field the stamp
    # actually rides on. Both fixed: any ONE present value dimension is enough
    # to key on, and market_value is now one of them (230 groups/1,735 rows ->
    # 503 groups/1,742 rows).
    #
    # `own` stays REQUIRED, and that is the whole reason a second detector
    # (`shared_anchor_stamps`) exists rather than a looser version of this one.
    # Dropping the owner requirement as well takes this to 5,449 rows, but 2,215
    # of those come from groups keyed on (county, state, None, None, None,
    # owner) — i.e. "the same person owns two parcels in this county", which is
    # a landlord, not a fanned-out assessor row. This detector's claim is that
    # one ROW was copied; the owner is what makes it a row.
    gis_buckets: dict[tuple, set] = defaultdict(set)
    gis_members: dict[tuple, list] = defaultdict(list)
    for li in listings:
        av = getattr(li, "assessed_value", None)
        ac = getattr(li, "acreage", None)
        mv = getattr(li, "market_value", None)
        own = (getattr(li, "owner_name", "") or "").strip().lower()
        cty = re.sub(r"[^a-z0-9]", "", (getattr(li, "county", "") or "").lower())
        pid = re.sub(r"[^a-z0-9]", "", (getattr(li, "parcel_id", "") or "").lower())
        if own and cty and pid and (av or ac or mv):
            key = (cty, getattr(li, "state", ""),
                   round(float(av), 2) if av else None,
                   round(float(ac), 4) if ac else None,
                   round(float(mv), 2) if mv else None,
                   own)
            gis_buckets[key].add(pid)
            gis_members[key].append(li)
    shared_members: set[int] = set()
    shared_groups = 0
    for key, pids in gis_buckets.items():
        if len(pids) > 1:          # same assessor row, DIFFERENT parcels
            shared_groups += 1
            for li in gis_members[key]:
                shared_members.add(id(li))

    # ---- shared county anchor: DETECT, then RETRACT --------------------------
    # Runs BEFORE the per-lead loop on purpose. The tripwires below
    # (verdict_on_flagged_arv / bid_on_contradicted_arv) must read the board as
    # it will be PUBLISHED, so the withholding has to have already happened when
    # they look. Run it after and they would report a violation this same
    # function was about to fix, then the fix would land and the counts would be
    # a lie in the other direction.
    stamps = shared_anchor_stamps(listings)

    # SCALE turns gis_row_shared from a note into a contradiction. Two parcels
    # sharing an assessor row is ambiguous — adjacent lots under one deed, a
    # duplicated record, a genuine pair of identical spec houses — and is left
    # display-only, which is why this detector has never gated money. 668 is not
    # ambiguous: HALLIDAY Q STANFORD IV, 0.88 acres, assessed $9,781.20, on 668
    # DISTINCT Spartanburg parcels, 656 of them from the vacant registry whose
    # every lead shared one city-centroid coordinate. 264 of them publish a max
    # bid. Past `_SHARED_ANCHOR_MIN_PARCELS` the row cannot be describing all of
    # them, so it joins the same retraction under the same flag — one claim, one
    # vocabulary. It catches what the value-only route cannot: that cluster's
    # market_value ($384,600) is a ROUND number, so `shared_anchor_stamps`
    # correctly declines to convict it on precision alone; the identical owner
    # and acreage are what convict it. 6 groups, 387 rows, 110 max bids,
    # $31,174,300 board-wide.
    for key, pids in gis_buckets.items():
        if len(pids) <= _SHARED_ANCHOR_MIN_PARCELS:
            continue
        for li in gis_members[key]:
            if id(li) in stamps:
                continue
            _f, _v = _anchor_field(li, _raw(li))
            if not _v:
                continue          # no anchor -> no ARV built on it -> nothing to pull
            stamps[id(li)] = {"value": _v, "field": _f, "county": key[0],
                              "state": key[1], "basis": "assessor_row_across_parcels",
                              "parcels": len(pids), "rows": len(gis_members[key])}

    for li in listings:
        info = stamps.get(id(li))
        if not info:
            continue
        raw = _raw(li)
        summary[f"anchor_stamp:{info['basis']}"] += 1
        calc = raw.get("calc") if isinstance(raw.get("calc"), dict) else {}
        if _ANCHOR_DERIVED_FLAG not in set(calc.get("arv_flags") or ()):
            # The stamp is on the lead, but this ARV did not come from it
            # (comp-grounded). Flagged below; nothing to retract.
            summary["anchor_stamp_not_derived"] += 1
            continue
        for k, v in _retract_shared_anchor(li, raw, info).items():
            summary[f"anchor_stamp_{k}"] += v

    # ---- per-lead flags -----------------------------------------------------
    for li in listings:
        raw = _raw(li)
        flags: list[str] = []

        # anchor_shared_across_parcels. Every lead in a stamped cluster gets the
        # QA flag, because sitting in one is a fact about the lead. Only the
        # leads whose ARV descends from the stamp also get it in
        # `calc['arv_flags']`, because that list is the trust gate's vocabulary
        # and there it would be a claim about the valuation. 1,706 leads carry
        # the qa_flag, 1,451 carry the calc flag; the 255-lead difference is
        # comp-grounded ARVs that keep every dollar.
        if id(li) in stamps:
            flags.append(SHARED_ANCHOR_FLAG)

        # sale_date_passed — mirrored from enrichment_board_quality (which runs
        # immediately before this pass in all three publishers) onto the one
        # channel web_artifact actually ships. See the note by SALE_PASSED_FLAG.
        if raw.get("sale_date_passed"):
            flags.append(SALE_PASSED_FLAG)

        # owner_record_mismatch — the assessor row names a different party
        if owner_records_disagree(getattr(li, "owner_name", "") or "",
                                  _gis_owner(raw)):
            flags.append(OWNER_MISMATCH_FLAG)
            _src = getattr(li, "owner_name", "") or ""
            _gis = _gis_owner(raw)
            if _INSTITUTIONAL.search(re.sub(r"[^A-Z0-9 ]", " ", _src.upper())) or \
               _INSTITUTIONAL.search(re.sub(r"[^A-Z0-9 ]", " ", _gis.upper())):
                summary["owner_mismatch_institutional"] += 1
            else:
                summary["owner_mismatch_two_private_parties"] += 1

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
