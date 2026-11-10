"""A-F grades across investment dimensions, plus an overall grade.

Grades are computed from data we already have (or that the calc produces).
Each dimension is a 0-100 score, then mapped:
  90+: A   80-89: B   65-79: C   50-64: D   <50: F

THE PRIMARY VERDICT IS AS-IS ANCHORED, NOT ARV ANCHORED (re-pointed
2026-11-10). The coaching program this pipeline is built for (Distressed
Property Advisors / DPA) has one repeated rule: never price or grade off ARV,
as-is value only. `deal_status` (calc.py) and the `financial`/`overall`
letter (this file) are now driven by calc.py's AS-IS offer band
(`as_is_value` / `offer_low` / `offer_target` / `offer_max`, built from the
county's own 100%-basis appraisal via `_anchor_value`) — see
`_financial_score` and `as_is_trust` below. `bid_to_arv_pct` / `max_bid_70` /
`roi_pct` remain a clearly SECONDARY, clearly-labeled flip-upside figure: DPA
operators doing a flip still want it, so it is still computed and still shown,
but it no longer anchors the trust/grade verdict.

This module owns TWO trust gates, not one, and they protect different
things:
  `arv_trust` / `apply_arv_trust_gate`  — protects the SECONDARY, ARV-derived
      money (`ARV_DERIVED_MONEY_FIELDS`) from a bad or missing ARV. Unchanged.
  `as_is_trust` (new)                   — protects the PRIMARY, as-is-anchored
      verdict (`ARV_VERDICT_FIELDS`: deal_status/deal_message/haircut_needed)
      from a bad or missing AS-IS ANCHOR. This is the re-pointing: before this
      change, ANY `arv_flags` entry withheld the verdict even when the flag
      said nothing about the anchor the as-is verdict would have used -- which
      is exactly backwards once the verdict stops being ARV-derived. See
      `as_is_trust`'s own comment for which flags actually earned a seat in
      its (deliberately narrow) sets.
Both gates still run from the one shared seam (`apply_arv_trust_gate`, called
from `grade()`), so every one of the 13 producers of `raw['calc']` gets both
for free, same as before.

THE INCIDENT THAT PROVED THE OLD DESIGN WRONG, preserved because the numbers
are still the ground truth for why either gate exists: 3646 Summer Rd,
Henderson NC -- an ARV 7.4x the county's own $230,200 appraisal -- published
"GREAT, ROI 192.6%, max bid $1,271,200" while a separate guard correctly
withheld the LETTER grade on that same row. Splitting the decision across two
files is how that happened. Under the new design the verdict is built from
the $230,200 anchor directly and `arv_above_anchor` (an ARV-vs-anchor
disagreement, not a defect IN the anchor) no longer has any say over it --
see the Henderson trace in the fix's own report / commit message for the
worked-through before/after.
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
    # The county figure this ARV is anchored to is stamped on MANY parcels, so
    # it is not an appraisal of this property. enrichment_board_qa emits it
    # (SHARED_ANCHOR_FLAG). One Lincoln County value, 299,453.0, sits on 1,433
    # leads across 1,354 distinct parcel_ids and drove $320,145,300 of max bids;
    # the 58 of those leads carrying their own assessed_value span $3,582 to
    # $1,491,777, a 416x spread under a constant "market value".
    #
    # Contradicted, not weak: the anchor is not merely unverified, it is
    # demonstrably describing something else. Wired here during integration
    # review — board_qa was emitting it and NOTHING classified it, so the
    # detection worked and no money was gated by it. That is the same
    # writer-with-no-reader failure that has produced five separate silent
    # defects in this system; the flag is only worth what reads it.
    "anchor_shared_across_parcels",
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
    # calc.ARV_FLAG_UNEXPLAINED_OUTLIER (audit 2026-10-09): an ARV over $1M, 8x the county
    # value or 5x the highest cited comp with no county value or comp to support it; calc
    # withholds it like the two above.
    "arv_unexplained_outlier",
    # calc.ARV_FLAG_PROXY_CEILING. A proxy tier (bid x2.4, bid x1.5, tax x1.25,
    # market-value-as-Zestimate, sale-to-assessed) produced a number above
    # calc.MAX_PROXY_ARV and calc REFUSED it, so no ARV is published — same
    # shape as the two above. It is in this set for the reason those are: the
    # refusal used to emit nothing at all, `arv_trust` scored it "ok", and 21
    # leads went on to publish $40,194,700 of equity off the exact figures calc
    # had just rejected (enrichment_equity falls back to market_value as its own
    # ARV when calc published none). The leak went AROUND this gate; naming the
    # refusal in the gate's own vocabulary is what closes it.
    "arv_proxy_above_ceiling",
    # calc.ARV_FLAG_ABOVE_ASK. The ARV is more than 1.6x the price the seller is
    # publicly asking on a RETAIL land listing (calc.SELLER_ASK_SOURCES).
    # Contradicted, not weak, and the distinction is the source: on an auction
    # row a 7x gap between opening bid and ARV is the flip thesis, but here the
    # parcel is on the open market at that price, so an ARV several times it is
    # the comps disagreeing with an actual transactable price. 83 leads carry an
    # ARV >= 1.6x their ask; 48 published a max bid ABOVE the asking price,
    # $13,844,500 of them — including Lot 28 Big Hill Road, Transylvania NC:
    # listed $120,000, board ARV $834,700, max bid $626,000, ROI 342.5%, GREAT.
    "arv_above_list_price",
    # calc.ARV_FLAG_LAND_SQFT. The county classes the parcel LAND and the record
    # also carries a dwelling-sized living_sqft, off which this ARV was priced.
    # Two records about one parcel that cannot both be right — the definition of
    # this set. 315 leads; 227 published a max bid ($56,935,000), 89 of them
    # with no other flag at all.
    "arv_land_sqft_mismatch",
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
    # calc.ARV_FLAG_TIER_CEILING. One ARV TIER produced a number above
    # calc.MAX_PROXY_ARV and was refused; a LATER tier carried the lead. Exactly
    # the shape of `land_comps_rejected` above and classified the same way: the
    # refusal is the guard WORKING, and the number that shipped belongs to a
    # different tier and is judged on ITS flags. What this flag says is "the
    # evidence you might expect behind this figure was thrown away", which is a
    # disclosure, not a contradiction of the figure. (Before it existed the two
    # LAND versions of this refusal wrote nothing at all — not even a note — and
    # simply fell through to the next tier in silence.)
    "arv_tier_refused_ceiling",
    # calc.ARV_FLAG_COUNTY_DISAGREE. Two of the county's own 100%-basis figures
    # (market_value / assessor appraised / tax_value) disagree past the threshold
    # measured for THAT PAIR — 3x where an assessor appraisal is involved (those
    # agree exactly on ~95% of leads), 10x for market-value-vs-tax-roll (which
    # breaks 3x on 11% of leads by field semantics alone, tax_value often being
    # land-only). 315 leads. Weak, deliberately: nothing here impugns the
    # ARV, it says the record the ARV was CROSS-CHECKED against is one of two
    # that cannot both describe this parcel, and that `_anchor_value` picked
    # between them by field order rather than by evidence. Blanking the money on
    # 1,282 leads over a disagreement between two records neither of which is
    # the ARV would be gutting the normal case; what it costs is the verdict,
    # which turns on a 5% margin and cannot survive a 3x ambiguity in its own
    # reference point.
    "county_values_disagree",
    # calc.MAX_BID_NO_REHAB_FLAG. The lead has no living_sqft, so no rehab tier
    # could be applied, so `rehab_buy` was 0 and `max_bid_70` collapsed to a flat
    # 0.75 x ARV with nothing taken out for the work. 9,190 published bids;
    # 1,833 of them clear $250,000 and total $740,267,300.
    #
    # THIS FLAG IS NOT A CLAIM ABOUT THE ARV. It lives in `arv_flags` because
    # that is one of the three lists docs/dashboard.js's `rehabTrust()` reads for
    # this literal, and a flag the client cannot see is not a flag. Classified
    # WEAK explicitly, and the classification is doing real work in both
    # directions: it must never reach ARV_FLAGS_CONTRADICTED (that would blank
    # the max bid on 9,190 leads — the bid IS the thing being captioned, and
    # deleting it would remove most of the board's economics over a term that is
    # genuinely unknowable without a building size), and it must not be left
    # unclassified either, because the "unrecognised flags fail safe to weak"
    # default would reach the same place by accident rather than on purpose.
    # What it costs is the deal verdict, on 15 leads — a GREAT/PASS call turns on
    # a 5% margin and cannot survive an undeducted repair bill.
    "rehab_not_deducted",
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
#     "Equity $1,920,000 (97%)" in green. It cannot be COMPUTED here because
#     enrichment_equity.py runs at main.py:2329, AFTER valuation at :2287, and
#     writes raw['equity'] itself — on a lead's FIRST pass through grade()
#     there is no equity figure yet to blank. The gate therefore lives
#     primarily at the writer: enrichment_equity.enrich_equity() calls
#     arv_trust() and publishes a `withheld` marker instead of a figure on
#     contradicted/withheld, and distress_score._equity_band() makes the SAME
#     call (not a test of the marker) so a board carried over from a run that
#     predates this cannot rank on a stale one either.
#
#     But a SECOND pass through grade() is exactly what a targeted recompute
#     is (lrcpwa_refresh.py, sqft_backfill.py, and ~20 other scripts all run
#     compute()+grade() over some subset of an already-equity-bearing board),
#     and on that pass raw['equity'] already exists and can go stale: calc's
#     own money fields get re-gated for free (this function runs every time),
#     but nothing told the SEPARATE equity pass to re-run too. Measured twice
#     on the live board, 2026-10-01: 9 rows, then 671, publishing equity off
#     an ARV that had just been re-graded CONTRADICTED. grade() now calls
#     `_regate_equity_after_grade` right after this function returns, which
#     re-derives trust from THIS call's own `c` and strips (never computes) a
#     stale figure the same way `models._regate_merged_valuation` already does
#     for the merge path. Same rule, same shared function
#     (`enrichment_equity.withhold_equity`), one more caller:
#     ARV_TRUST_BLOCKS_DERIVED below is still the one constant all of them
#     share.
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


# ===========================================================================
# AS-IS TRUST GATE (added 2026-11-10) — protects the now-PRIMARY, as-is-
# anchored verdict (`ARV_VERDICT_FIELDS`) from a bad or missing AS-IS ANCHOR.
# This is the re-pointed half of the ARV trust gate's mechanism: same shape
# (withheld/contradicted/weak/ok classify into the same field-nulling idiom
# in `apply_arv_trust_gate` / `gate_calc_dict`), different question.
#
# DELIBERATELY NARROW, and that narrowness is the whole fix. Most of
# ARV_FLAGS_CONTRADICTED / ARV_FLAGS_WEAK_EVIDENCE are about the ARV's OWN
# construction (a comp pool, a $/sqft tier, a bid-proxy multiple) or about the
# ARV disagreeing WITH the county anchor (`arv_above_anchor` and friends) --
# neither claim says the anchor itself (`calc._anchor_value`: county market
# value / assessor appraised value / tax value) is wrong. Gating the as-is
# verdict on those would reproduce the exact Henderson defect one layer down:
# withholding a verdict that was never built from the thing that is flagged.
# Only two flags actually impugn the anchor `as_is_value` is built from:
AS_IS_FLAGS_CONTRADICTED = frozenset({
    # The SAME county figure is stamped on many parcels -- see
    # ARV_FLAGS_CONTRADICTED's own comment (SHARED_ANCHOR_FLAG,
    # enrichment_board_qa._retract_shared_anchor). It is not an appraisal of
    # THIS property, so it cannot anchor an as-is offer on this property
    # either -- the same fact that disqualifies it as an ARV anchor.
    "anchor_shared_across_parcels",
    # The assessor row is a mis-joined commercial parcel. In practice
    # `_anchor_value` already vetoes this before `as_is_value` is ever set
    # (`_commercial_building_type`), so WITHHELD (missing input, below) fires
    # first on the live path. Listed anyway, not for redundancy's own sake,
    # but so a future caller that reads `as_is_value` off an OLDER/legacy
    # serialized dict (built before that veto existed, or by some other
    # writer) still fails safe instead of silently trusting a known-bad join.
    "cama_class_mismatch",
})
# Both of the above are also in ARV_FLAGS_CONTRADICTED -- enforced, not just
# commented, so the two vocabularies cannot quietly drift apart.
assert AS_IS_FLAGS_CONTRADICTED <= ARV_FLAGS_CONTRADICTED

AS_IS_FLAGS_WEAK = frozenset({
    # `_anchor_value` took the FIRST of (market_value, appraised_value,
    # tax_value) without asking whether the other two agree -- see
    # COUNTY_VALUE_DISAGREE_MULT in calc.py. The figure `as_is_value` ended up
    # holding was picked by field order, not by evidence, which is exactly
    # the "knife-edge verdict cannot survive this ambiguity" case the WEAK
    # tier exists for everywhere else in this file. The dollars (offer bands)
    # stay -- same rule as every other WEAK flag -- because the magnitude is
    # not disputed, only which of two agreeing-adjacent records was chosen.
    "county_values_disagree",
})
assert AS_IS_FLAGS_WEAK <= ARV_FLAGS_WEAK_EVIDENCE

# Deliberately NOT "any unrecognised flag fails safe to weak" the way
# `arv_trust` does. `arv_trust`'s fail-safe default is correct there because
# EVERY flag in calc.py's vocabulary is about the ARV, so an unknown one is
# presumed to be too. Here most of that same vocabulary is explicitly NOT
# about the anchor (`bid_proxy_arv`, `comp_kind_mismatch`, every land-comp
# flag, ...) -- defaulting an unrecognised flag to WEAK here would silently
# re-couple the as-is verdict to ARV-only noise, i.e. undo this fix by
# default the next time V1 adds a flag to calc.py. A future flag that SHOULD
# gate the as-is verdict has to be named in one of the two sets above, same
# as `anchor_shared_across_parcels` / `cama_class_mismatch` were.
def as_is_trust(arv_flags, as_is_value) -> str:
    """Classify the AS-IS anchor's trust: 'withheld' | 'contradicted' | 'weak' | 'ok'.

    Pure function, same contract as `arv_trust` (reads the serialized dict's
    fields, no re-computation), and reads the SAME `arv_flags` list calc.py
    already emits -- one flag vocabulary, not two -- but only the AS_IS_*
    subsets above change the answer.
    """
    flags = set(arv_flags or ())
    if as_is_value is None:
        # No county market/appraised/tax figure at all (or a legacy dict from
        # before this field existed): nothing to verify a verdict against, so
        # any verdict sitting in the dict is unsupported and must not survive.
        return _TRUST_WITHHELD
    if flags & AS_IS_FLAGS_CONTRADICTED:
        return _TRUST_CONTRADICTED
    if flags & AS_IS_FLAGS_WEAK:
        return _TRUST_WEAK
    return _TRUST_OK


def _asis_gate_note(level: str) -> str:
    if level == _TRUST_WITHHELD:
        return (
            "No deal verdict published: there is no as-is anchor (county "
            "market/appraised/tax value) to measure the bid against. The "
            "flip-side ARV figures below, if present, are a SECONDARY upside "
            "estimate only -- this operator does not price off ARV."
        )
    return (
        "No deal verdict published: the as-is anchor this verdict is built "
        "from is flagged -- the county record the offer band rests on does "
        "not reliably describe this exact property. The as-is offer band is "
        "still shown because the magnitude is not disputed, only which "
        "record was used."
    )


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
    """Note text for the SECONDARY (ARV-derived money) gate only -- WITHHELD or
    CONTRADICTED. Since the re-pointing, WEAK no longer makes this gate touch
    anything (it only ever acted on money for CONTRADICTED/WITHHELD; see
    as_is_trust for what now happens to the verdict on a WEAK anchor), so this
    function no longer has a third branch to speak for.
    """
    named = ", ".join(sorted(flags)) or "an unnamed sanity flag"
    if level == _TRUST_WITHHELD:
        return (
            "No max bid, ROI, profit, wholesale MAO/spread or total investment "
            "published: there is no ARV to derive them from. (This operator's "
            "as-is deal verdict, if any, is unaffected — it is not built from "
            "the ARV; see as_is_trust.)"
        )
    return (
        f"No max bid, ROI, profit, wholesale MAO/spread or total investment "
        f"published: this ARV is flagged {named}, which means another record "
        f"(or the arithmetic itself) contradicts it. Every one of those "
        f"figures is the ARV restated, so publishing them would dress an "
        f"unverified number up as a flip-upside estimate. The ARV and its "
        f"range are still shown so the disagreement is visible — verify the "
        f"parcel, then re-run the math yourself. (The as-is deal verdict, if "
        f"any, is unaffected by this flag unless it ALSO trips as_is_trust.)"
    )


def _null_fields(c: "_calc.Calc", fields) -> bool:
    """setattr(c, f, None) for every field in `fields` that is currently set.
    Returns whether anything actually changed, so callers only log/note on a
    real transition (idempotence: a second pass over an already-gated `c`
    costs one `getattr` per field and appends nothing)."""
    touched = False
    for f in fields:
        if getattr(c, f, None) is not None:
            setattr(c, f, None)
            touched = True
    return touched


def _append_note(c: "_calc.Calc", note: str) -> None:
    if c.notes is None:
        c.notes = []
    if note not in c.notes:
        c.notes.append(note)


def _pop_fields(calc: dict, fields) -> bool:
    """Dict-mirror of `_null_fields`: delete (not null) each field, matching
    calc.to_dict()'s own shape. Returns whether anything was actually popped."""
    touched = False
    for f in fields:
        if calc.pop(f, None) is not None:
            touched = True
    return touched


def _append_note_dict(calc: dict, note: str) -> None:
    notes = calc.setdefault("notes", [])
    if isinstance(notes, list) and note not in notes:
        notes.append(note)


def apply_arv_trust_gate(c: "_calc.Calc", opening_bid=None) -> str:
    """Withhold whatever `c`'s ARV, or separately its AS-IS anchor, cannot
    support. Mutates `c`; idempotent.

    Runs BOTH trust gates from the one shared seam (see the module
    docstring's "TWO trust gates" section):
      - `arv_trust`   gates the SECONDARY, ARV-derived money
        (`ARV_DERIVED_MONEY_FIELDS`: max_bid_70, roi_pct, ...) — unchanged.
      - `as_is_trust` gates the PRIMARY, as-is-anchored verdict
        (`ARV_VERDICT_FIELDS`: deal_status, deal_message, haircut_needed) —
        the 2026-11-10 re-pointing. An ARV-only defect (`arv_above_anchor`,
        `bid_proxy_arv`, a bad comp pool, ...) no longer withholds this: the
        verdict was never built from the ARV, so a flaw IN the ARV is not a
        reason to distrust it. Only a flaw in the county anchor itself does
        (`as_is_trust`'s own AS_IS_FLAGS_* sets).
    The two answers are independent and may disagree — a lead can keep a real
    deal_status while its flip-side ARV figures are withheld (the Henderson
    shape this fixes), or the reverse (a clean comp-built ARV but no county
    anchor at all to build an as-is offer from).

    Called at the top of `grade()`, which is the ONE seam every producer of
    `raw['calc']` shares: all 13 call sites in this repo run
    `c = calc.compute(li)` -> `g = grading.grade(li, c)` -> `to_dict(c)`, so
    gating here reaches the board no matter which script wrote it. It is not
    in valuation/calc.py because that module's contract is "compute the
    numbers"; this is the separate decision about which of them may be shown,
    and it needs the same flag vocabulary both the verdict and the letter use.

    calc.to_dict() drops None values, so a withheld field simply does not
    appear in raw['calc'] — the dashboard, the CSV export and the sheet all
    render nothing rather than a zero.

    Returns the ARV trust level (not the as-is one) — unchanged contract:
    `_regate_equity_after_grade` keys off this return value because
    `raw['equity']` is ARV-derived (`arv - payoff - liens`), never
    as-is-derived, so it must keep following the ARV gate specifically.

    `opening_bid` is optional and only feeds the placeholder-bid anomaly test;
    pass it whenever the Listing is at hand (grade() does). Anomaly flags are
    derived and merged into `c.arv_flags` FIRST, so both gates below see them —
    that is the whole of the E3 fix, and it is why the anomalous branch in
    `grade()` no longer needs a withholding rule of its own.
    """
    _anom = anomaly_flags(getattr(c, "arv_expected", None),
                          getattr(c, "roi_pct", None), opening_bid)
    if _anom:
        c.arv_flags = _merge_flags(getattr(c, "arv_flags", None), _anom)
    flags = set(getattr(c, "arv_flags", None) or ())

    # ---- SECONDARY: the ARV-derived flip-upside money -----------------------
    level = arv_trust(flags, getattr(c, "arv_expected", None),
                      getattr(c, "arv_withheld", None))
    # WITHHELD is included on purpose even though calc already produces
    # nothing here (measured: 0 of 531 withheld board rows carry a derived
    # figure). That cleanliness is a side effect of every downstream block
    # being written `if out.arv_expected` — an implicit coupling in a file
    # this module does not own. Enforcing it explicitly costs one comparison
    # and means a future refactor of calc.py cannot quietly reopen the worst
    # version of this bug: a confident bid beside an ARV the engine refused
    # to print. (WEAK deliberately takes no action here any more — it used
    # to also null the verdict; that is now as_is_trust's call, below, and
    # ARV-WEAK alone says nothing about the as-is anchor.)
    if level in (_TRUST_CONTRADICTED, _TRUST_WITHHELD):
        if _null_fields(c, ARV_DERIVED_MONEY_FIELDS):
            _append_note(c, _gate_note(level, flags))

    # ---- PRIMARY: the as-is-anchored verdict --------------------------------
    asis_level = as_is_trust(flags, getattr(c, "as_is_value", None))
    if asis_level != _TRUST_OK:
        if _null_fields(c, ARV_VERDICT_FIELDS):
            _append_note(c, _asis_gate_note(asis_level))

    return level


def _regate_equity_after_grade(li: Listing, level: str, c: "_calc.Calc") -> None:
    """Strip a stale raw['equity'] the moment THIS grade() call's own trust
    level lands on a tier the gate blocks derived money on.

    Called from `grade()` only, right after `apply_arv_trust_gate` -- see the
    comment at that call site for the incident this closes (two separate
    2026-10-01 backfills, 9 rows then 671, both needed because a targeted
    calc/grade recompute left raw['equity'] computed under the OLD,
    not-yet-contradicted arv_flags). This is the equity-side twin of
    `models._regate_merged_valuation`, which already does the same thing for
    the merge path (fixed a40f3689) -- same rule, same shared function, now
    reached from the OTHER place arv_flags changes.

    Deliberately reads `c` (the Calc object `apply_arv_trust_gate` just
    mutated), not `li.raw['calc']`: the caller has not necessarily written
    `to_dict(c)` into `li.raw['calc']` yet (main.py does that one line after
    `grade()` returns), so re-deriving trust from the stale serialized dict
    here could disagree with the `level` this very call just computed. `level`
    is passed in directly for exactly that reason -- one trust decision, not
    two independent ones that happen to usually agree.

    Scoped to a no-op everywhere this does not apply, by construction:
      - `level` not in ARV_TRUST_BLOCKS_DERIVED (the common case -- ok/weak)
        -> return before touching anything. The vast majority of grade()
        calls never reach the import below.
      - `li.raw` not a dict (no enrichment has run yet, or a bare/synthetic
        Listing) -> return. Mirrors `_regate_merged_valuation`'s own guard;
        grade() must not be the first thing to turn `li.raw` into a dict.
      - `li.raw['equity']` absent or already withheld (no `value`) ->
        `withhold_equity` itself no-ops (one isinstance check + one dict
        .get()) and returns False. Covers both "never had equity" (the
        overwhelming majority of CONTRADICTED rows on a normal run, since
        calc and equity are usually computed in the same pass) and "already
        withheld by an earlier call" (idempotent: calling this twice on the
        same contradicted row costs one no-op dict read the second time).

    Local import: valuation.grading is imported BY enrichment_equity (for
    ARV_TRUST_BLOCKS_DERIVED / arv_trust), so a module-level import the other
    way would be circular. Safe here because it only executes once grade() is
    actually called, by which point both modules have finished loading --
    same pattern models.py uses for this exact pair of imports.
    """
    if level not in ARV_TRUST_BLOCKS_DERIVED:
        return
    if not isinstance(li.raw, dict):
        return
    from ..enrichment_equity import withhold_equity
    withhold_equity(li, level, sorted(getattr(c, "arv_flags", None) or []))


def gate_calc_dict(calc: dict) -> str:
    """The same TWO gates (see `apply_arv_trust_gate`) applied to an
    already-serialized `raw['calc']` block.

    Belt and braces for two real cases: a board carried over from a run that
    predates this gate (or predates the 2026-11-10 re-pointing), and any
    future writer that serializes a Calc without going through `grade()` —
    `enrichment_board_qa._retract_shared_anchor` is exactly such a caller,
    and it depends on this function nulling `deal_status` for
    `anchor_shared_across_parcels` via `as_is_trust`, below. Shares the flag
    sets and the field lists with `apply_arv_trust_gate` above, so the two
    can never drift — a reader/writer split is what let `geo_imprecise_comps`
    and `bid_proxy_arv` go unwarned in the dashboard for months.

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
    flags = calc.get("arv_flags")

    # ---- SECONDARY: the ARV-derived flip-upside money -----------------------
    level = arv_trust(flags, calc.get("arv_expected"), calc.get("arv_withheld"))
    if level in (_TRUST_CONTRADICTED, _TRUST_WITHHELD):
        if _pop_fields(calc, ARV_DERIVED_MONEY_FIELDS):
            _append_note_dict(calc, _gate_note(level, set(flags or ())))

    # ---- PRIMARY: the as-is-anchored verdict --------------------------------
    asis_level = as_is_trust(flags, calc.get("as_is_value"))
    if asis_level != _TRUST_OK:
        if _pop_fields(calc, ARV_VERDICT_FIELDS):
            _append_note_dict(calc, _asis_gate_note(asis_level))

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
    """Bid relative to the AS-IS offer band (DPA's 10/30/50% rule). PRIMARY
    financial lens as of 2026-11-10 — see the module docstring. Every
    boundary below is one of calc.py's own named AS_IS_OFFER_* constants, not
    an invented number, so this ladder and the as-is offer band shown on the
    card can never silently disagree about what "target" or "max" means.

    bid_to_arv_pct / max_bid_70 / roi_pct are the SECONDARY flip-upside
    figures (still computed, still shown) and deliberately do NOT feed this
    score any more — not even as the ROI bonus/penalty the old version had.
    Re-introducing any ARV-derived modifier here would put ARV influence back
    into the one score DPA's rule says must never carry it, just one step
    removed from the Henderson defect instead of absent.
    """
    if not (li.opening_bid and c.as_is_value):
        return 50, "no bid or as-is anchor value — neutral"
    # Mirrors the old bid_proxy_arv guard's INTENT (don't score a lead's own
    # circular arithmetic) but keyed on AS_IS_FLAGS_CONTRADICTED, not the full
    # ARV set: `as_is_value` is never built from the bid (see `_anchor_value`
    # and `as_is_trust`'s own comment), so the ARV-side flags that guard
    # against THAT circularity (bid_proxy_arv, comp-pool defects, ...) have
    # nothing to say about this score. Only a flaw in the anchor itself does.
    _bad = set(getattr(c, "arv_flags", None) or ()) & AS_IS_FLAGS_CONTRADICTED
    if _bad:
        return 50, ("the as-is anchor is contradicted (" + ", ".join(sorted(_bad))
                    + ") — no independent price signal")
    bid = li.opening_bid
    bid_to_asis = bid / c.as_is_value

    if bid_to_asis <= _calc.AS_IS_OFFER_LOW_PCT:
        s, why = 95, f"Bid is {bid_to_asis*100:.0f}% of as-is value — at/under DPA's low offer"
    elif bid_to_asis <= _calc.AS_IS_OFFER_TARGET_PCT:
        s, why = 85, f"Bid {bid_to_asis*100:.0f}% of as-is value — at/under DPA's target offer"
    elif bid_to_asis <= _calc.AS_IS_OFFER_MAX_PCT:
        s, why = 65, f"Bid {bid_to_asis*100:.0f}% of as-is value — within DPA's max offer"
    elif bid_to_asis <= _calc.AS_IS_RESALE_PCT:
        s, why = 35, f"Bid {bid_to_asis*100:.0f}% of as-is value — above DPA's max offer"
    else:
        s, why = 15, f"Bid {bid_to_asis*100:.0f}% of as-is value — at/above as-is resale value"
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
    # 2026-11-10: no pre-gate ROI/ARV capture is needed any more. Before the
    # as-is re-pointing, the letter's own anomaly test (below) re-derived the
    # ROI/ARV-magnitude condition directly, because it had to fire AFTER the
    # gate had already nulled roi_pct/arv_expected on the tier it blanks — so
    # it needed the pre-gate figures or it would silently stop unrating the
    # rows this was about. The letter no longer tests ROI/ARV magnitude at
    # all (see `anomalous` below): it tests `arv_flags` membership, and the
    # gate never clears flags, only the money/verdict fields built from them,
    # so there is nothing left to capture ahead of the gate call.
    _trust_level = apply_arv_trust_gate(c, opening_bid=li.opening_bid)
    # Equity incident 2026-10-01 (9 rows, then 671): a targeted recompute (any
    # script that runs compute()+grade() over a SUBSET of the board, e.g.
    # lrcpwa_refresh.py's per-row pass) can flip `c.arv_flags` into
    # ARV_FLAGS_CONTRADICTED on a lead whose raw['equity'] was computed and
    # published by an EARLIER, separate enrich_equity() pass. Nothing about
    # recomputing calc/grade touches raw['equity'] — it is a different pass,
    # over a different field, run by a different script most of the time — so
    # the stale figure survived every call site except Listing.merge() (fixed
    # a40f3689), which is the one place that already happened to re-derive
    # trust after mutating raw. grade() is the other (much larger) half of the
    # same seam: see this function's own comment above for why EVERY compute()
    # caller in the repo already lands here. Closing it here, instead of in
    # each of the ~20+ scripts that call compute()+grade(), means a future
    # script gets this for free the same way it already gets the calc-side
    # gate for free.
    _regate_equity_after_grade(li, _trust_level, c)

    fs, fn = _financial_score(li, c)
    ps, pn = _property_score(li)
    ls, ln = _location_score(li)
    rs, rn = _risk_score(li, c)

    # Weighted overall: financial 40 / property 25 / location 20 / risk 15
    overall = round(fs * 0.40 + ps * 0.25 + ls * 0.20 + rs * 0.15)
    # 2026-06-19: WITHHOLD the overall letter when there's no real financial
    # basis. A data-less listing got financial=50 ("neutral" C) and the
    # property/location baselines floated the overall to a confident C/D — a
    # misleading grade on a row we know nothing about.
    #
    # 2026-11-10: re-pointed from "an opening bid OR a non-proxy ARV" to "an
    # opening bid OR an as-is anchor value" — `_financial_score` above now
    # keys on `as_is_value`, not `arv_expected`/`arv_confidence`, so THAT is
    # the figure that makes a financial basis real. `arv_confidence` (the
    # ARV-method confidence: comp-grounded vs proxy) no longer has anything to
    # do with whether the PRIMARY letter is assessable — it still matters for
    # the secondary ARV figures, gated separately by `arv_trust`.
    assessable = bool(li.opening_bid) or bool(c.as_is_value)
    if not assessable:
        return Grade(
            overall=None, overall_score=0,
            financial=_letter(fs), financial_score=fs,
            property=_letter(ps), property_score=ps,
            location=_letter(ls), location_score=ls,
            risk=_letter(rs), risk_score=rs,
            rationale=["Unrated — insufficient valuation data (no bid / no as-is anchor value)", pn, ln, rn],
        )
    # 2026-06-19 / 2026-08-10: also WITHHOLD when the deal-math is anomalous.
    #
    # 2026-11-10: re-pointed. The original test re-derived "ROI > 400% / ARV >
    # $2M / bid < 5% of ARV" directly from the PRE-gate figures, because those
    # are exactly the three tests `apply_arv_trust_gate` already turns into
    # `arv_above_plausible_max` / `arv_implies_implausible_roi` /
    # `placeholder_opening_bid` — all three ARV-and-ROI-specific, i.e. about
    # the flip lens, not the as-is one. Re-running them here to gate the
    # PRIMARY (as-is) letter was the same conflation this whole fix removes:
    # an ARV/ROI anomaly says nothing about whether the as-is anchor is good.
    # What is left here reads `AS_IS_FLAGS_CONTRADICTED | AS_IS_FLAGS_WEAK` —
    # the SAME narrow sets `as_is_trust` uses to withhold `deal_status` —
    # rather than a second hand-maintained list, for the same reason the old
    # code reused ARV_FLAGS_CONTRADICTED: the letter and the verdict are the
    # same claim at two resolutions, and defining the gate twice is exactly
    # how Henderson shipped "GREAT" beside a withheld letter in the first
    # place. `anomaly_flags()` itself (the ROI/$2M/placeholder-bid tests)
    # keeps running unchanged, in `apply_arv_trust_gate`, and keeps correctly
    # withholding the SECONDARY max_bid_70/roi_pct/deal_status-via-ARV... no —
    # deal_status is no longer ARV's to withhold at all; those three anomaly
    # flags still null the secondary money (they are members of
    # ARV_FLAGS_CONTRADICTED), they simply no longer reach this letter.
    suspect_asis = set(getattr(c, "arv_flags", None) or []) & (
        AS_IS_FLAGS_CONTRADICTED | AS_IS_FLAGS_WEAK)
    anomalous = bool(suspect_asis)
    if anomalous:
        why = ("Unrated — the as-is anchor failed a sanity check ("
               + ", ".join(sorted(suspect_asis)) + ")")
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
