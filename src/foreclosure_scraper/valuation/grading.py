"""A-F grades across investment dimensions, plus an overall grade.

Grades are computed from data we already have (or that the calc produces).
Each dimension is a 0-100 score, then mapped:
  90+: A   80-89: B   65-79: C   50-64: D   <50: F

This module ALSO owns the ARV TRUST GATE (see the block below): the single
decision about whether a valuation is solid enough to publish a verdict and a
bid off. It lives here because the letter grade and the deal verdict are the
same claim at two resolutions, and splitting that decision across two files is
exactly how the board came to withhold the letter while still printing
"GREAT — max bid $1,271,200" on the same row.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

from ..models import Listing, PropertyKind
from . import calc as _calc


# ===========================================================================
# ARV TRUST GATE
#
# THE DEFECT. valuation/calc.py withholds an ARV outright when a hard guard
# trips, and that path is already clean: measured by replaying the live board
# (38,500 leads, 25,004 with an ARV), all 531 arv_withheld rows publish no max
# bid, no ROI, no profit and no verdict, because every one of those blocks is
# written `if out.arv_expected`. The hole is the SOFT case — the ARV survives
# but calc has named a reason to distrust it. Measured on the same replay
# (every count below is reproducible by running compute() over docs/listings
# and reading arv_flags; they move as calc's guards are tuned, so re-measure
# rather than trusting the digits):
#
#   19,359 leads keep an ARV carrying at least one calc arv_flag. All of them
#   published max_bid_70 and wholesale_mao; 1,440 published roi_pct,
#   estimated_profit, cash_on_cash_pct, bid_to_arv_pct and total_investment;
#   502 published a deal_status verdict, 126 of them "GREAT".
#
#   3646 Summer Rd, Henderson NC: arv_above_anchor (the ARV is 7.4x the county
#   appraisal), and the board said GREAT, ROI 192.6%, max bid $1,271,200 —
#   while the LETTER grade on the same row was withheld for the same flag.
#   938 bid-proxy leads published an ROI that is a fixed function of the
#   opening bid divided by 2.4x itself.
#
# THE RULE, in one sentence, so there is one definition and not two:
#
#   ANY calc arv_flag removes the VERDICT.
#   A CONTRADICTING arv_flag also removes every DOLLAR derived from the ARV.
#
# Why the verdict goes first and always. deal_status is a categorical call on a
# knife edge (`bid <= max_bid * 0.95` -> GREAT). A 2x ARV error flips GREAT to
# PASS, and there is no way to render a verdict at half strength — "GREAT
# (unverified)" still reads GREAT. It is also the cheapest thing to withhold:
# 502 of 25,004 ARV-bearing leads lose it (a verdict also needs an opening bid,
# which most leads do not have), and they keep every underlying number, so
# nothing an investor can check for themselves disappears.
#
# Why the dollars only go on the CONTRADICTED tier. max_bid_70 / roi_pct /
# estimated_profit are the board's ranking keys, so on a contradicted ARV they
# sort the least trustworthy leads to the top of the page — the worst possible
# ordering. But they are also the board's entire usefulness, and the weak tier
# is 16,310 leads, most of them ARVs that simply ARE the county's own appraisal
# times a constant. Blanking two thirds of the board's economics because the
# county's number cannot be checked against itself would be gutting the normal
# case, which this work is explicitly not allowed to do. So the weak tier keeps
# its dollars and is captioned instead (enrichment_data_quality writes
# `arv_no_independent_check`; this module appends the reason to `calc.notes`,
# which the detail panel renders in full).
#
# An unrecognised future flag therefore fails SAFE — it lands in neither set,
# so it removes the verdict (via the "any flag" rule) without silently blanking
# money the flag may not be about. V1 owns calc.py and adds flags there; three
# arrived mid-change (anchor_not_independent, land_comps_rejected,
# land_ppa_ceiling) and were classified explicitly below rather than left to
# the default.
# ===========================================================================

# CONTRADICTED — another record, or the arithmetic itself, disputes the number
# that shipped. Board counts are leads that KEEP an arv_expected.
ARV_FLAGS_CONTRADICTED = frozenset({
    # ARV is opening_bid x 2.4 (or x 1.5 on land), so bid/ARV is the constant
    # 0.4167 and every figure below is the bid restated. 938 leads.
    "bid_proxy_arv",
    # ARV runs 4-10x (improved) / 6-20x (land) the county's own 100%-basis
    # appraisal. calc's own note says "verify the parcel before bidding". 894.
    "arv_above_anchor",
    # --- the two ANOMALY verdicts, see _anomaly_flags() below ---------------
    # ARV > $2M in these rural counties. `grade()` has refused to letter-grade
    # these since 2026-06-19 and docs/dashboard.js:1536 has drawn the red
    # warning off the same test — but calc emitted no flag, so the VERDICT and
    # the max bid sailed through the trust gate untouched. Contradicted because
    # the reason the grader distrusts it is that the number itself is not a
    # price any comparable property here has fetched. 27 leads.
    "arv_above_plausible_max",
    # ROI > 400%. Same story: dashboard.js:1540 already calls this "implausible,
    # so the ARV behind it is not trustworthy" while Python published the deal.
    # ROI is (ARV - bid - rehab - fees) / cash in, so a 400%+ result means the
    # ARV and the bid are describing different properties — the arithmetic
    # disputing itself, which is the definition of this set. 83 leads.
    "arv_implies_implausible_roi",
    # Past the hard multiple — calc withholds the ARV, so these already publish
    # nothing. Listed so the set is complete and stays correct if that changes.
    "arv_above_anchor_extreme",
    "ppsf_ceiling",
    # The county/sale floor multiplied the comp ARV by >2.5x. calc honoured it
    # but says "confirm the assessor record belongs to this property". 374.
    "floor_raise_large",
    # The floor disagreed with the comps by >6x and was rejected. calc kept the
    # comp number, but the two records differ by 6x and only one is right. 283.
    "floor_rejected_extreme",
    # Manufactured housing priced off site-built comps. calc: "a manufactured
    # home does not sell at site-built $/sqft". This is the reported bug — and
    # note it still fires on 725 Bryant Rd after the ARV was repaired from
    # $780,300 to $121,100, because $121,100 is itself a site-built comp read on
    # a manufactured home. Right magnitude, wrong evidence: worth publishing,
    # not worth bidding off. 517 leads.
    "comp_kind_mismatch",
    # The assessor row joined to this lead describes a commercial building, so
    # the parcel join is known-wrong and nothing sourced from that record can be
    # relied on. calc's _cross_check_anchor now measures the ARV against it
    # anyway and returns trusted=False — which is the right call for DISCLOSURE
    # (a 47.9x disagreement is a fact the reader is owed: 616 N Church St,
    # $643,200 against $13,435) but is not verification. Agreement with a record
    # we already know is describing another building proves nothing. 173 leads
    # keep an ARV here; they keep it, and lose the bid built on it.
    "cama_class_mismatch",
})

# WEAK EVIDENCE — the inputs do not describe this exact property, or the best
# evidence was refused and a weaker tier carried the lead. Nothing contradicts
# the number itself. Verdict withheld, dollars kept + caveated.
ARV_FLAGS_WEAK_EVIDENCE = frozenset({
    # Comps were selected by radius from a shared city-centroid coordinate, so
    # they are a coarse county-level read rather than this property's
    # neighbourhood. calc caps confidence at MEDIUM. 5,829 leads keep an ARV —
    # far too many to blank, and the magnitude is not disputed, only the
    # precision.
    "geo_imprecise_comps",
    # A recorded sale was refused as a floor for being undated or >10y old. The
    # published ARV is the other tier's number and is not itself impugned, but
    # we chose between two disagreeing value records and the verdict rests on
    # that choice. 1,495 leads.
    "stale_sale_floor",
    # The ARV IS the county's own figure times a constant, so dividing one by
    # the other only restates the multiplier — calc's words: "Nothing here
    # confirms the county's number describes this property." 15,988 leads, 64%
    # of every ARV on the board. Unverified is not the same as wrong: a county
    # appraisal is an official valuation, just an unchecked one. Blanking the
    # economics on two ARVs in three would delete the board, so these keep their
    # dollars and lose only the knife-edge verdict — of which they had 352 at
    # most, because a verdict also needs an opening bid.
    "anchor_not_independent",
    # Land comps existed but none were within 5x the subject's acreage, so they
    # were refused and a lower tier carried the lead. The refusal is the guard
    # WORKING; what it leaves behind is a county/bid proxy, which is weaker
    # evidence but not a contradicted one. (Those proxies pick up their own
    # flags — anchor_not_independent or bid_proxy_arv — and are judged on them.)
    "land_comps_rejected",
    # The county's value implied a $/acre this dirt cannot support, so calc
    # refused to build an ARV from it. Same shape: a rejected input, and the 9
    # leads that still carry an ARV got it from an independent tier.
    "land_ppa_ceiling",
    # A 2-comp land pool spanned >=8x, so calc refused to average it and the ARV
    # came from a later tier (see calc.LAND_COMP_SPREAD_MAX). Classified exactly
    # like `land_comps_rejected` above and for the same reason: the refusal is
    # the guard WORKING, and the number that survived is a different tier's, to
    # be judged on ITS flags (an anchor proxy picks up anchor_not_independent, a
    # bid proxy picks up bid_proxy_arv and is CONTRADICTED on that). What this
    # flag says is "the comps you can see on this card did not produce this
    # number" — a disclosure, not a contradiction of the number that shipped.
    "land_comps_disagree",
    # A 3+-comp land pool spanned >=8x and its MEDIAN shipped. Weak, not
    # contradicted: a median of 3+ is an actual comp, robust to one mis-typed
    # sale, so nothing disputes the published figure — but the pool is
    # heterogeneous enough that the point estimate should be read as a band.
    # Blanking the money here would delete a defensible answer; the verdict
    # (a 5%-margin GREAT/PASS call) is the part this pool cannot support.
    "land_comp_spread",
    # The opening bid is under 5% of the ARV — an upset/placeholder figure, not
    # the real acquisition cost (see _anomaly_flags). WEAK, not contradicted,
    # because nothing here impugns the ARV: `max_bid_70` is 0.70 x ARV - rehab
    # and never touches the bid, so blanking it would be punishing a good number
    # for a bad neighbour. What the placeholder DOES destroy is the verdict —
    # `deal_status` is literally `bid <= max_bid * 0.95`, so a $1,000 placeholder
    # makes GREAT unconditional. 71 leads, 44 of them carrying no other flag.
    "placeholder_opening_bid",
})

# Everything downstream of arv_expected that is money or a ratio of money.
# `total_investment` is included because its selling-cost term is 7% of ARV, so
# a 10x-wrong ARV makes it wrong too, and leaving it while removing
# estimated_profit would just invite the reader to subtract it back out.
ARV_DERIVED_MONEY_FIELDS = (
    "max_bid_70", "wholesale_mao", "wholesale_spread", "total_investment",
    "estimated_profit", "roi_pct", "cash_on_cash_pct", "bid_to_arv_pct",
)
# The verdict and its trimmings.
ARV_VERDICT_FIELDS = ("deal_status", "deal_message", "haircut_needed")

# CONSIDERED AND DELIBERATELY NOT GATED. Keep this list exhaustive: the reason
# `raw['equity']` went ungated for so long is that it was never written down as
# a decision, so nobody could tell "we thought about it" from "we forgot".
#
#   `hold_status` / `cap_rate_pct` / `monthly_cashflow_est` — the buy-and-hold
#     lens is computed from rent comps, the bid and rehab. It never reads
#     arv_expected, so an ARV problem is not a reason to blank it.
#   `arv_low` / `arv_high` — publishing the band alongside a flagged point
#     estimate is MORE honest than publishing the point alone, not less.
#   `arv_expected` itself — the gate withholds what is DERIVED from the ARV, not
#     the ARV. calc decides whether the number may be published at all
#     (arv_withheld); this module decides what may be built on top of it.
#   `arv_vs_assessed` — a ratio between two published records, i.e. the
#     disagreement itself. It is the evidence for the flag; hiding it would hide
#     the reader's best chance of spotting which record is wrong.
#
# GATED ELSEWHERE, because it is neither a Calc field nor computed here:
#   `raw['equity']` (value / pct) and its `distress_stack.equity_band` —
#     equity is `arv - payoff - senior_liens`, so on a CONTRADICTED ARV it is as
#     unsupported as max_bid was, and it is the largest number on the card.
#     Measured on the live board: 1,252 leads published an equity figure on a
#     contradicted ARV and 113 more on a WITHHELD one — leads whose max bid,
#     ROI, profit, verdict and letter were all withheld, still showing
#     "Equity $1,920,000 (97%)" in green. It cannot be gated here because
#     enrichment_equity.py runs at main.py:2329, AFTER valuation at :2287, and
#     writes raw['equity'] itself — at grade() time there is nothing to blank.
#     The gate therefore lives at the writer: enrichment_equity.enrich_equity()
#     calls arv_trust() and publishes a `withheld` marker instead of a figure on
#     contradicted/withheld, and distress_score._equity_band() makes the SAME
#     call (not a test of the marker) so a board carried over from a run that
#     predates this cannot rank on a stale one either. Same rule, same function,
#     three call sites, one shared constant: ARV_TRUST_BLOCKS_DERIVED below.
#
#   `distress_stack.tier` — not gated directly, and deliberately. Withholding
#     the equity band already removes the only ARV-derived term in the tier
#     rule, so a contradicted lead can no longer reach HOT. The distress
#     evidence itself (probate, tax delinquency, code enforcement, divorce) is
#     independent of the valuation and is not impugned by a bad comp set, so
#     `stack >= 2` still earns WARM. Blanking the tier as well would delete
#     records that are true.

_TRUST_WITHHELD = "withheld"
_TRUST_CONTRADICTED = "contradicted"
_TRUST_WEAK = "weak"
_TRUST_OK = "ok"

# The trust levels on which an ARV-DERIVED figure must not be published. This is
# the same pair `apply_arv_trust_gate` blanks ARV_DERIVED_MONEY_FIELDS on, named
# once and exported so the gate's out-of-module call sites (enrichment_equity,
# distress_score — see "GATED ELSEWHERE" above) cannot answer the question
# differently from the one inside this file. Import the name, never re-spell the
# pair: `("contradicted", "withheld")` written out by hand in a second module is
# how a reader and a writer come to disagree.
ARV_TRUST_BLOCKS_DERIVED = frozenset({_TRUST_CONTRADICTED, _TRUST_WITHHELD})


def arv_trust(arv_flags, arv_expected, arv_withheld=None) -> str:
    """Classify a valuation: 'withheld' | 'contradicted' | 'weak' | 'ok'.

    Pure function over the three fields calc publishes, so the enrichment
    layers can reach the same verdict from the serialized `raw['calc']` dict
    without re-running the valuation.
    """
    flags = set(arv_flags or ())
    if arv_expected is None:
        # calc already refused to publish. Nothing derived should exist either.
        return _TRUST_WITHHELD if (arv_withheld is not None or flags) else _TRUST_OK
    if flags & ARV_FLAGS_CONTRADICTED:
        return _TRUST_CONTRADICTED
    if flags:
        # Named weak flags AND anything unrecognised — fail safe (verdict only).
        return _TRUST_WEAK
    return _TRUST_OK


# ---------------------------------------------------------------------------
# ANOMALY FLAGS — the second path into the same contradiction.
#
# THE DEFECT. `grade()` has had its own sanity test since 2026-06-19: an ROI
# over 400%, an ARV over $2M in these counties, or an opening bid under 5% of
# the ARV means garbage went in, so it returns Unrated and withholds the LETTER.
# It withheld nothing else. The trust gate keys on `arv_flags`, calc emits no
# flag for any of these three, so the VERDICT, the max bid and the ROI walked
# straight past it. Measured on the live board: 50 leads where the letter is
# withheld and a deal verdict publishes anyway.
#
#   Lot 11 Silver Maple Trail, Brevard NC rendered, in badge order: a green
#   "GREAT deal", then "ARV flagged — do not bid off it", then "Max bid (70%)
#   $1,491,800 — from a flagged ARV", then "ROI 829%". The warning and the
#   recommendation were both correct about their own inputs and were reading
#   different files: docs/dashboard.js:1536-1542 draws the red mark off exactly
#   these ROI/ARV thresholds, while Python had no flag to gate on.
#
# THE FIX is not a fourth withholding rule. It is to say the anomaly in the ONE
# vocabulary the gate already speaks — a flag string — and let the existing
# machinery do what it already does correctly. Emitting these into `arv_flags`
# also means they serialize into raw['calc'], so the dashboard, the CSV and
# `gate_calc_dict` all see the same three words the grader saw.
#
# The strings are chosen to be legible to docs/dashboard.js:1506 as it stands
# today: that reader marks a flag "bad" when the name contains "arv" AND a word
# from its verdict list, so `arv_above_plausible_max` ("above") and
# `arv_implies_implausible_roi` ("implausib") light up with no dashboard change.
# `placeholder_opening_bid` deliberately does not — it is a WEAK flag and a
# red "do not bid off this ARV" mark would be a lie about which number is bad.
# (It is therefore invisible on the board today; that is the E5/E6 caption gap,
# which belongs to the dashboard, not here.)
ANOMALY_ARV_MAX = 2_000_000     # ARV plausibility ceiling for these counties
ANOMALY_ROI_MAX = 400.0         # ROI % above which the inputs cannot both be right
ANOMALY_BID_FLOOR_PCT = 0.05    # bid under 5% of ARV = an upset/placeholder figure


def anomaly_flags(arv_expected, roi_pct, opening_bid=None) -> list[str]:
    """The three garbage-in tests `grade()` already ran, expressed as flags.

    Pure and side-effect free so `grade()` (which has the Listing, hence the
    opening bid) and `gate_calc_dict()` (which has only the serialized dict)
    reach the same answer from whatever they hold. Thresholds are the ones that
    were already in `grade()`; this moves nothing, it only names the result.
    """
    out: list[str] = []
    try:
        if arv_expected is not None and float(arv_expected) > ANOMALY_ARV_MAX:
            out.append("arv_above_plausible_max")
        if roi_pct is not None and float(roi_pct) > ANOMALY_ROI_MAX:
            out.append("arv_implies_implausible_roi")
        if (opening_bid and arv_expected
                and float(opening_bid) < ANOMALY_BID_FLOOR_PCT * float(arv_expected)):
            out.append("placeholder_opening_bid")
    except (TypeError, ValueError):
        pass
    return out


def _merge_flags(existing, new) -> list[str]:
    """Append `new` to `existing` without duplicating — order-stable, idempotent."""
    out = list(existing or [])
    for f in new:
        if f not in out:
            out.append(f)
    return out


def _gate_note(level: str, flags) -> str:
    named = ", ".join(sorted(flags)) or "an unnamed sanity flag"
    if level == _TRUST_WITHHELD:
        return (
            "No max bid, ROI, profit or deal verdict published: there is no ARV "
            "to derive them from."
        )
    if level == _TRUST_CONTRADICTED:
        return (
            f"No max bid, ROI, profit or deal verdict published: this ARV is "
            f"flagged {named}, which means another record (or the arithmetic "
            f"itself) contradicts it. Every one of those figures is the ARV "
            f"restated, so publishing them would dress an unverified number up "
            f"as a bidding instruction. The ARV and its range are still shown "
            f"so the disagreement is visible — verify the parcel, then re-run "
            f"the math yourself."
        )
    return (
        f"No deal verdict published: this ARV is flagged {named}, so the "
        f"evidence behind it does not describe this exact property. Max bid "
        f"and ROI are still shown because the magnitude is not disputed, but "
        f"treat them as a band, not a number — a GREAT/PASS call turns on a "
        f"5% margin and this ARV is not that precise."
    )


def apply_arv_trust_gate(c: "_calc.Calc", opening_bid=None) -> str:
    """Withhold whatever `c`'s ARV cannot support. Mutates `c`; idempotent.

    Called at the top of `grade()`, which is the ONE seam every producer of
    `raw['calc']` shares: all 13 call sites in this repo run
    `c = calc.compute(li)` -> `g = grading.grade(li, c)` -> `to_dict(c)`, so
    gating here reaches the board no matter which script wrote it. It is not
    in valuation/calc.py because that module's contract is "compute the
    numbers"; this is the separate decision about which of them may be shown,
    and it needs the same flag vocabulary the letter grade uses.

    calc.to_dict() drops None values, so a withheld field simply does not
    appear in raw['calc'] — the dashboard, the CSV export and the sheet all
    render nothing rather than a zero.

    Returns the trust level so callers can log or branch on it.

    `opening_bid` is optional and only feeds the placeholder-bid anomaly test;
    pass it whenever the Listing is at hand (grade() does). Anomaly flags are
    derived and merged into `c.arv_flags` FIRST, so the gate below sees them —
    that is the whole of the E3 fix, and it is why the anomalous branch in
    `grade()` no longer needs a withholding rule of its own.
    """
    _anom = anomaly_flags(getattr(c, "arv_expected", None),
                          getattr(c, "roi_pct", None), opening_bid)
    if _anom:
        c.arv_flags = _merge_flags(getattr(c, "arv_flags", None), _anom)
    flags = set(getattr(c, "arv_flags", None) or ())
    level = arv_trust(flags, getattr(c, "arv_expected", None),
                      getattr(c, "arv_withheld", None))
    if level == _TRUST_OK:
        return level

    fields = ARV_VERDICT_FIELDS
    # WITHHELD is included on purpose even though calc already produces nothing
    # here (measured: 0 of 531 withheld board rows carry a derived figure).
    # That cleanliness is a side effect of every downstream block being written
    # `if out.arv_expected` — an implicit coupling in a file this module does
    # not own. Enforcing it explicitly costs one comparison and means a future
    # refactor of calc.py cannot quietly reopen the worst version of this bug:
    # a confident bid beside an ARV the engine refused to print.
    if level in (_TRUST_CONTRADICTED, _TRUST_WITHHELD):
        fields = fields + ARV_DERIVED_MONEY_FIELDS
    touched = False
    for f in fields:
        if getattr(c, f, None) is not None:
            setattr(c, f, None)
            touched = True
    if touched:
        note = _gate_note(level, flags)
        if c.notes is None:
            c.notes = []
        if note not in c.notes:
            c.notes.append(note)
    return level


def gate_calc_dict(calc: dict) -> str:
    """The same gate applied to an already-serialized `raw['calc']` block.

    Belt and braces for two real cases: a board carried over from a run that
    predates this gate, and any future writer that serializes a Calc without
    going through `grade()`. Shares the flag sets and the field lists with
    `apply_arv_trust_gate` above, so the two can never drift — a reader/writer
    split is what let `geo_imprecise_comps` and `bid_proxy_arv` go unwarned in
    the dashboard for months.

    Deletes rather than nulls, to match calc.to_dict()'s own shape.
    """
    if not isinstance(calc, dict):
        return _TRUST_OK
    # Same anomaly derivation as apply_arv_trust_gate. No opening bid is
    # available here (it lives on the Listing, not in raw['calc']), so the
    # placeholder-bid test simply does not fire on this path — the two ARV/ROI
    # tests do, which is what a legacy board most needs.
    _anom = anomaly_flags(calc.get("arv_expected"), calc.get("roi_pct"))
    if _anom:
        calc["arv_flags"] = _merge_flags(calc.get("arv_flags"), _anom)
    level = arv_trust(calc.get("arv_flags"), calc.get("arv_expected"),
                      calc.get("arv_withheld"))
    if level == _TRUST_OK:
        return level
    fields = ARV_VERDICT_FIELDS
    if level in (_TRUST_CONTRADICTED, _TRUST_WITHHELD):
        fields = fields + ARV_DERIVED_MONEY_FIELDS
    touched = False
    for f in fields:
        if calc.pop(f, None) is not None:
            touched = True
    if touched:
        note = _gate_note(level, set(calc.get("arv_flags") or ()))
        notes = calc.setdefault("notes", [])
        if isinstance(notes, list) and note not in notes:
            notes.append(note)
    return level


@dataclass
class Grade:
    overall: str
    overall_score: int
    financial: str
    financial_score: int
    property: str
    property_score: int
    location: str
    location_score: int
    risk: str
    risk_score: int
    rationale: list[str]


def _letter(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _financial_score(li: Listing, c: _calc.Calc) -> tuple[int, str]:
    """Bid relative to (max_bid_70, ARV, rehab). 70% rule sits at score 80."""
    if not (li.opening_bid and c.arv_expected):
        return 50, "no bid or ARV — neutral"
    # A bid-derived ARV makes bid_to_arv a CONSTANT (bid / (bid × 2.4) is always
    # 0.4167), so this function would be scoring its own arithmetic. Measured:
    # 316 of the board's 405 bid-proxy leads graded exactly C and 33 graded B,
    # purely from where that constant lands on the ladder below. Neutral is the
    # honest score — we have no independent read on this deal's economics.
    #
    # Widened from bid_proxy_arv alone to the whole CONTRADICTED set. The
    # overall letter is already withheld on these (see `grade` below), but the
    # per-dimension `financial` letter still publishes, and it is 100% a
    # function of bid/ARV — so a contradicted ARV was still emitting a
    # confident financial grade on 3,025 board leads through the side door.
    _bad = set(getattr(c, "arv_flags", None) or ()) & ARV_FLAGS_CONTRADICTED
    if _bad:
        return 50, ("ARV is contradicted (" + ", ".join(sorted(_bad))
                    + ") — no independent price signal")
    bid = li.opening_bid
    bid_to_arv = bid / c.arv_expected
    rehab = c.rehab_expected or 0
    fees = c.arv_expected * 0.07
    spread = c.arv_expected - bid - rehab - fees   # rough profit if bought at bid
    spread_pct = spread / c.arv_expected if c.arv_expected else 0

    if bid_to_arv <= 0.30:
        s, why = 98, f"Bid is {bid_to_arv*100:.0f}% of ARV — exceptional"
    elif bid_to_arv <= 0.40:
        s, why = 92, f"Bid {bid_to_arv*100:.0f}% of ARV — strong upside"
    elif bid_to_arv <= 0.55:
        s, why = 85, f"Bid {bid_to_arv*100:.0f}% of ARV — within 70% rule"
    elif bid_to_arv <= 0.70:
        s, why = 70, f"Bid {bid_to_arv*100:.0f}% of ARV — at 70% rule"
    elif bid_to_arv <= 0.85:
        s, why = 55, f"Bid {bid_to_arv*100:.0f}% of ARV — thin margin"
    elif bid_to_arv <= 1.0:
        s, why = 35, f"Bid {bid_to_arv*100:.0f}% of ARV — almost retail"
    else:
        s, why = 15, f"Bid {bid_to_arv*100:.0f}% of ARV — overpriced"

    # ROI bonus / penalty
    if c.roi_pct is not None:
        if c.roi_pct >= 30:
            s += 3
        elif c.roi_pct < 10:
            s -= 5
    return max(0, min(100, s)), why


def _property_score(li: Listing) -> tuple[int, str]:
    """Year built + sqft data + flags."""
    score = 70  # neutral baseline
    notes = []

    if li.year_built:
        age = datetime.utcnow().year - li.year_built
        if age <= 15:
            score += 12
            notes.append(f"newer construction ({li.year_built})")
        elif age <= 35:
            score += 6
        elif age <= 60:
            pass
        elif age <= 100:
            score -= 8
            notes.append(f"older home ({age} yrs)")
        else:
            score -= 18
            notes.append(f"very old ({age} yrs)")

    if li.bedrooms and li.bathrooms and li.living_sqft:
        score += 8
    elif li.living_sqft:
        score += 3

    flags = (li.raw or {}).get("flags", []) if isinstance(li.raw, dict) else []
    fb = " ".join(flags).lower()
    bad = ["fire damage", "tear down", "uninhabitable", "condemned", "foundation", "gutted",
           "structural", "termite", "no power", "no water", "boarded", "hoarder", "vacant"]
    good = ["renovated", "remodeled", "updated", "move-in", "turnkey", "new roof", "new hvac"]
    bad_hits = sum(1 for k in bad if k in fb)
    good_hits = sum(1 for k in good if k in fb)
    score -= bad_hits * 6
    score += good_hits * 4
    if bad_hits:
        notes.append(f"{bad_hits} negative condition flag(s)")
    if good_hits:
        notes.append(f"{good_hits} positive condition flag(s)")

    if li.property_kind == PropertyKind.LAND:
        score = max(score, 60)
        notes.append("vacant land — minimal physical condition risk")

    return max(0, min(100, score)), "; ".join(notes) or "limited property data"


def _location_score(li: Listing) -> tuple[int, str]:
    """Rough location score from county tier + ZIP + state economy.

    Tier-1 counties have stronger demand (Mecklenburg, Buncombe, Greenville).
    Tier-2 are smaller but still active. Tier-3 are rural / slow.
    A future enhancement is Census API integration for true median income +
    population trend per ZIP.
    """
    if not li.county or not li.state:
        return 60, "location data missing"

    county = li.county.lower().strip()
    state = li.state.upper()

    tier_1 = {"mecklenburg", "buncombe", "greenville"}
    tier_2 = {"spartanburg", "anderson", "henderson", "gaston", "rutherford"}
    tier_3 = {"cleveland", "polk", "transylvania", "mcdowell", "lincoln",
              "pickens", "oconee", "cherokee", "union", "laurens", "abbeville",
              "greenwood", "newberry", "madison", "yancey", "mitchell", "burke"}

    if county in tier_1:
        s = 88
        why = f"{county.title()} County, {state} — high-demand metro"
    elif county in tier_2:
        s = 78
        why = f"{county.title()} County, {state} — established market"
    elif county in tier_3:
        s = 65
        why = f"{county.title()} County, {state} — smaller market"
    else:
        s = 60
        why = f"{county.title()} County, {state}"

    # Pull location enrichment from raw if present (Census API filled later)
    loc = (li.raw or {}).get("location") if isinstance(li.raw, dict) else None
    if isinstance(loc, dict):
        income = loc.get("median_household_income")
        if income:
            if income > 80000:
                s += 6
                why += f" · median HH income ${income:,.0f}"
            elif income < 40000:
                s -= 8
                why += f" · low median HH income ${income:,.0f}"
            else:
                why += f" · median HH income ${income:,.0f}"
    return max(0, min(100, s)), why


def _risk_score(li: Listing, c: "_calc.Calc | None" = None) -> tuple[int, str]:
    """Risk grade from auction status + flag count + listing type."""
    score = 75
    notes = []
    flags = (li.raw or {}).get("flags", []) if isinstance(li.raw, dict) else []
    fb = " ".join(flags).lower()

    if any(k in fb for k in ("fire damage", "tear down", "condemned", "uninhabitable")):
        score -= 30
        notes.append("severe condition risk")
    elif "foundation" in fb or "structural" in fb:
        score -= 18
        notes.append("structural risk")
    elif "vacant" in fb:
        score -= 5
        notes.append("vacant (vandalism risk)")

    # Listing type risk
    lt = (li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type)).lower()
    if "tax_sale" in lt or "tax_lien" in lt:
        score -= 10
        notes.append("tax sale — buyer takes subject to other liens")
    elif "auction" in lt:
        score -= 5
        notes.append("auction — non-refundable deposit risk")
    elif "reo" in lt:
        score += 8
        notes.append("REO — clean title typical")

    # Foreclosure process: NC power-of-sale is fast + clean; SC judicial is a
    # slow lawsuit (Master-in-Equity, court confirmation) = more timing risk;
    # SC tax sale carries a ~12-mo redemption window before title is takeable.
    proc = getattr(li, "foreclosure_process", None)
    if proc == "judicial":
        score -= 5
        notes.append("SC judicial foreclosure — slower (court confirmation), higher timing risk")
    elif proc == "power_of_sale":
        score += 3
        notes.append("NC power-of-sale — fast, clean title (10-day upset-bid window)")
    if getattr(li, "redemption_deadline", None):
        score -= 6
        notes.append("SC tax sale — ~12-mo owner redemption period before title is takeable")

    # Equity: PREFER the real equity engine (ARV − payoff − liens) over the
    # legacy purchase-price-vs-zestimate flags, which can contradict it. Fall
    # back to the flags only when the engine produced nothing (Pass-2 reconcile).
    flag_set = set(flags)
    eq = (li.raw or {}).get("equity") if isinstance(li.raw, dict) else None
    eq_pct = (eq or {}).get("pct")
    if eq_pct is not None:
        if eq.get("is_underwater"):
            score -= 12
            notes.append(f"underwater — real equity {eq_pct * 100:.0f}% (after payoff + liens)")
        elif eq_pct >= 0.40:
            score += 6
            notes.append(f"high real equity ({eq_pct * 100:.0f}%)")
    else:
        if "high_equity" in flag_set:
            score += 6
            notes.append("high equity (likely 1st-mortgage foreclosure)")
        if "negative_equity" in flag_set:
            score -= 12
            notes.append("negative equity (short-sale territory)")

    # Underwater on the foreclosing lien: court-tested judgment debt >= ARV.
    # Mortgage/sheriff foreclosures ONLY — a tax sale's opening figure is taxes
    # owed, not debt, and the ARV must be real (HIGH/MEDIUM), never a bid proxy.
    # Soft downgrade, never a hard veto: lien position is unverified, so a
    # senior-lien foreclosure that wipes junior liens can still be a real deal.
    # Don't double-count with the negative_equity flag — cap this concern at -15.
    if c is not None:
        lt_uw = (li.listing_type.value if hasattr(li.listing_type, "value")
                 else str(li.listing_type)).lower()
        jud = li.judgment_amount or 0
        arv = getattr(c, "arv_expected", None)
        conf = (getattr(c, "arv_confidence", "") or "").upper()
        if (("foreclosure_sale" in lt_uw or "sheriff_sale" in lt_uw)
                and jud > 0 and arv and conf in ("HIGH", "MEDIUM")
                and jud >= arv):
            # negative_equity flag (if set) already took -12; top up to -15 total
            score -= 3 if "negative_equity" in flag_set else 15
            notes.append(
                f"judgment (${jud:,.0f}) >= ARV (${arv:,.0f}) — likely underwater "
                "on foreclosing lien (lien position unverified)")

    return max(0, min(100, score)), "; ".join(notes) or "no major flags"


def grade(li: Listing, c: _calc.Calc | None = None) -> Grade:
    if c is None:
        c = _calc.compute(li)

    # MUTATES `c`. Deliberate, and it must happen before the scores below read
    # roi_pct: this is the only function every producer of raw['calc'] calls
    # between compute() and to_dict(), so it is the only place a gate can cover
    # main.py, rentcast.py and the eleven refresh scripts at once. See
    # apply_arv_trust_gate's docstring.
    #
    # The gate NULLS roi_pct on the tier it blanks, and the anomalous branch
    # below is defined on the ROI. So capture the pre-gate figures first: read
    # them afterwards and a lead whose ROI was 829% looks like a lead with no
    # ROI, which would quietly stop unrating exactly the rows this is about.
    _pre_roi = getattr(c, "roi_pct", None)
    _pre_arv = getattr(c, "arv_expected", None)
    apply_arv_trust_gate(c, opening_bid=li.opening_bid)

    fs, fn = _financial_score(li, c)
    ps, pn = _property_score(li)
    ls, ln = _location_score(li)
    rs, rn = _risk_score(li, c)

    # Weighted overall: financial 40 / property 25 / location 20 / risk 15
    overall = round(fs * 0.40 + ps * 0.25 + ls * 0.20 + rs * 0.15)
    # 2026-06-19: WITHHOLD the overall letter when there's no real financial
    # basis. A data-less listing got financial=50 ("neutral" C) and the
    # property/location baselines floated the overall to a confident C/D — a
    # misleading grade on a row we know nothing about. Rate it only when we have
    # an opening bid OR a non-proxy (HIGH/MEDIUM-confidence) ARV.
    arv_conf = getattr(c, "arv_confidence", None)
    assessable = bool(li.opening_bid) or bool(c.arv_expected and arv_conf in ("HIGH", "MEDIUM"))
    if not assessable:
        return Grade(
            overall=None, overall_score=0,
            financial=_letter(fs), financial_score=fs,
            property=_letter(ps), property_score=ps,
            location=_letter(ls), location_score=ls,
            risk=_letter(rs), risk_score=rs,
            rationale=["Unrated — insufficient valuation data (no bid / only proxy ARV)", pn, ln, rn],
        )
    # 2026-06-19: also WITHHOLD when the deal-math is anomalous (garbage-in). A
    # tiny placeholder opening bid (<5% of ARV — an upset/opening figure, not the
    # real acquisition cost) or an implausible ARV (>$2M in these rural counties =
    # a comp error) produces an absurd ROI (e.g. 1300%). Presenting that as a
    # confident 'B' misrepresents it — rate it 'unrated' instead.
    #
    # 2026-08-10: this branch is no longer the ONLY consequence of an anomaly.
    # apply_arv_trust_gate above has already turned the same three tests into
    # `arv_above_plausible_max` / `arv_implies_implausible_roi` /
    # `placeholder_opening_bid` and withheld the verdict (and, for the first
    # two, the money) off them — so the letter and the verdict can no longer
    # disagree about the same row. What is left here is the letter, computed
    # from the PRE-gate figures so the test still fires after the gate has
    # nulled them.
    roi = _pre_roi
    # A letter grade is 40% financial, and the financial score is entirely a
    # function of ARV. When calc's own sanity band says the ARV is not
    # trustworthy, a confident letter launders that doubt into a recommendation.
    #
    # This reads ARV_FLAGS_CONTRADICTED — the SAME set that withholds the max
    # bid and the deal verdict — rather than a second hand-maintained list. The
    # letter and the verdict are the same claim at two resolutions; when they
    # were defined separately the board withheld the letter and printed
    # "GREAT, max bid $1,271,200" on the identical row. One definition, or the
    # two drift again.
    #
    # `cama_class_mismatch` joined the set (+173 leads unrated): the assessor row
    # joined to those leads is a commercial building, so the parcel join is
    # known-wrong and the cross-check that does run against it is explicitly
    # `trusted=False`.
    #
    # Still deliberately excluded: `geo_imprecise_comps` and `stale_sale_floor`
    # (ARV_FLAGS_WEAK_EVIDENCE). Real problems, but 6,086 leads, already handled
    # by a capped confidence and a data-quality caveat — unrating a quarter of
    # the board for a coordinate-precision problem is the "do not gut the normal
    # case" line. They lose the verdict (above), not the letter.
    suspect_arv = set(getattr(c, "arv_flags", None) or []) & ARV_FLAGS_CONTRADICTED
    anomalous = (
        (roi is not None and roi > ANOMALY_ROI_MAX)
        or (_pre_arv and _pre_arv > ANOMALY_ARV_MAX)
        or (li.opening_bid and _pre_arv
            and li.opening_bid < ANOMALY_BID_FLOOR_PCT * _pre_arv)
        or bool(suspect_arv)
    )
    if anomalous:
        why = ("Unrated — ARV failed a sanity check ("
               + ", ".join(sorted(suspect_arv)) + ")") if suspect_arv else \
              "Unrated — anomalous valuation (placeholder bid or implausible ARV)"
        return Grade(
            overall=None, overall_score=0,
            financial=_letter(fs), financial_score=fs,
            property=_letter(ps), property_score=ps,
            location=_letter(ls), location_score=ls,
            risk=_letter(rs), risk_score=rs,
            rationale=[why, pn, ln, rn],
        )
    return Grade(
        overall=_letter(overall),
        overall_score=overall,
        financial=_letter(fs), financial_score=fs,
        property=_letter(ps), property_score=ps,
        location=_letter(ls), location_score=ls,
        risk=_letter(rs), risk_score=rs,
        rationale=[fn, pn, ln, rn],
    )


def to_dict(g: Grade) -> dict:
    return asdict(g)
