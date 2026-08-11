"""Investor financial calculator.

Outputs (per listing):
  arv_low / arv_expected / arv_high       — After-repair value range
  rehab_low / rehab_expected / rehab_high — Rehab cost range
  max_bid_70                              — 70% rule (real-estate-investor standard)
  total_investment                        — bid + rehab + closing + holding + selling
  estimated_profit                        — arv - total_investment
  roi_pct                                 — profit / total_investment * 100
  cash_on_cash_pct                        — profit / cash_down (if 25% down + 75% loan)
  confidence                              — HIGH / MEDIUM / LOW based on data quality
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

from ..models import Listing, PropertyKind


# Per-square-foot rehab cost tiers (Carolina market, 2026 dollars)
# tier letter -> (low $/sqft, expected $/sqft, high $/sqft)
REHAB_TIERS = {
    "cosmetic":  (5,  10,  20),   # paint, fixtures, maybe carpet
    "light":     (15, 30,  45),   # paint, floors, kitchen counters, baths
    "moderate":  (35, 55,  80),   # kitchens, baths, HVAC, some plumbing
    "heavy":     (65, 95,  130),  # roof, systems, structural minor
    "gut":       (110, 160, 220), # near-tear-down
}

# Manufactured / mobile homes are far cheaper to rehab per sqft than stick-built:
# vinyl skirting, single-pane windows, cosmetic-grade fixtures throughout.
MOBILE_REHAB_TIERS = {
    "cosmetic": (3,   8,   15),
    "light":    (10,  20,  30),
    "moderate": (20,  35,  55),
    "heavy":    (40,  60,  80),
    "gut":      (70,  100, 140),
}

CLOSING_PCT = 0.04        # buyer-side closing (title, recording, attorney)
SELLING_PCT = 0.07        # 6% commission + 1% misc
HOLDING_RATE_MONTH = 0.005  # ~6% APR / 12 mo of bid value
HOLDING_MONTHS = 6
DOWN_PCT = 0.25           # cash down for cash-on-cash
LOAN_RATE_MONTH = 0.008   # 9.5% APR (hard money) / 12
REHAB_CONTINGENCY_PCT = 0.125  # every pro pads the repair estimate 10-15% for surprises
ASSIGNMENT_FEE = 10000    # typical residential wholesale assignment fee

# ---- A max bid that deducted NO repairs ------------------------------------
# THE STRING IS AN INTERFACE, AND IT IS NOT A FREE CHOICE. docs/dashboard.js's
# `rehabTrust()` already recognises exactly three literals — `rehab_not_deducted`,
# `rehab_unknown_zeroed`, `max_bid_no_rehab` (docs/dashboard.js:1366) — in
# `calc.arv_flags`, `raw.qa_flags` or `data_quality.flags`, and renders the same
# "this bid deducted $0 of repairs" treatment on the bid in three places. Any
# other spelling renders NOTHING, silently. This file emits the first of the
# three.
#
# It goes in `arv_flags` rather than a field of its own for the same reason: that
# is the list the client reads. The cost is that `grading.arv_trust` sees it and
# withholds the deal VERDICT — measured, that is 15 leads of the 9,190, because a
# verdict also needs an opening bid — and `grading.ARV_FLAGS_WEAK_EVIDENCE`
# classifies it explicitly so it can never blank the money. The full reasoning
# and the measured counts are at the write site in compute(), beside the
# `0.75 * arv - rehab_buy` line this is about.
MAX_BID_NO_REHAB_FLAG = "rehab_not_deducted"

# Living-sqft plausibility band for $/sqft ARV. A handful of real records
# legitimately sit in [8000,10000) (large estates), so only HARD-reject clearly
# bad values: below this floor is a data-entry/parse error (sqft-as-acres, a lot
# dimension, a zero), above the ceiling is almost always garbage. Outside the
# band, living_sqft is treated as missing FOR ARV PURPOSES (the $/sqft tiers are
# skipped) rather than producing a nonsense headline ARV.
LIVING_SQFT_MIN = 300
LIVING_SQFT_MAX = 10000

# Rural land sanity ceiling: a land-comp $/acre median above this is almost
# always a parse error (a per-sqft figure leaking through, or a 0.01-ac lot
# dividing a full sale price) and would emit a multi-million phantom land ARV.
MAX_LAND_PPA = 2_000_000  # $/acre

# Proxy-ARV ceiling. The bid×2.4 / bid×1.5 / tax×1.25 fallbacks fire on rows
# with no comps, and on those rows opening_bid is often a money-JUDGMENT or
# total-debt figure (not a property bid), which multiplied out emits a multi-
# million phantom ARV. Above this ceiling the proxy is not trustworthy, so we
# return ARV-unavailable (honest) instead of a fabricated number.
MAX_PROXY_ARV = 2_000_000

# ===========================================================================
# EVERY REFUSAL MUST SPEAK, NOT MERELY TAKE NOTES
#
# THE DEFECT. `MAX_PROXY_ARV` above is a REFUSAL: the engine computed a number,
# decided it was a judgment/debt figure rather than a property value, and
# declined to publish it. Six code paths do that, and every one of them wrote a
# `notes` line and NOTHING ELSE — no `arv_flags` entry, no `arv_withheld`. So
# `grading.arv_trust()` read "no flags, no withheld" as level "ok", every
# downstream gate passed, and `enrichment_equity` — which falls back to
# `market_value` as its own ARV when calc published none — went on to publish an
# equity figure off the very number calc had just thrown away.
#
# Measured by replaying compute()+grade() over the live 38,500-lead board: 21
# leads whose ARV had been refused here still published equity totalling
# $40,194,700, the largest $7,934,600. Index 781, 200 Miracle Mile Dr, Anderson
# SC, carried calc's own sentence — "Proxy ARV ($12,480,200) exceeds the
# $2,000,000 plausibility ceiling ... ARV withheld" — beside "Equity $7,934,600"
# derived from arv_used 12,480,200, the exact figure that sentence rejected,
# with arv_flags None and arv_withheld None.
#
# This was a leak AROUND the withholding gate, not through it: the gate itself
# is airtight (0 of 531 arv_withheld rows published a derived figure). The fix
# is therefore NOT another withholding rule. It is to say the refusal in the ONE
# vocabulary the gate already speaks — a flag string — exactly the way
# grading.anomaly_flags() handles the ROI/$2M case.
#
# TWO verdicts, because a refusal has two very different outcomes:
#
#   ARV_FLAG_PROXY_CEILING — nothing survived it. The lead publishes no ARV at
#       all, and `arv_withheld` now carries the number that was refused, so the
#       row is auditable instead of merely blank. CONTRADICTED in grading.py,
#       classified alongside `arv_above_anchor_extreme` / `ppsf_ceiling` for the
#       same reason: calc already publishes nothing, and the set is kept
#       complete so it stays correct if that ever changes.
#
#   ARV_FLAG_TIER_CEILING — one TIER's number blew the ceiling and was refused;
#       a LATER tier carried the lead. The number on screen is a different
#       tier's and is judged on ITS flags, so this is a disclosure ("the tier
#       you might expect to have produced this did not"), not a contradiction of
#       what shipped. WEAK in grading.py — the same classification, and for the
#       same reason, as `land_comps_rejected`.
#
# Both strings are read by grading.py. They are deliberately `arv_`-prefixed and
# contain a word from docs/dashboard.js's `_ARV_BAD_WORDS` / weak default, so a
# board published before dashboard.js learns them still renders a warning rather
# than silence.
ARV_FLAG_PROXY_CEILING = "arv_proxy_above_ceiling"
ARV_FLAG_TIER_CEILING = "arv_tier_refused_ceiling"


# ===========================================================================
# ARV SANITY BAND — every threshold below was measured on the live 38,500-lead
# board (docs/listings.json + listings_detail.json), not chosen by feel. The
# measurement script is scratch-only; the numbers it produced are quoted inline
# so the next reader can re-derive them.
#
# WHY THIS SECTION EXISTS: `MAX_LAND_PPA` (:64) bounds an individual land COMP
# and `MAX_PROXY_ARV` (:71) bounds the proxy tiers, but nothing bounded the
# $/sqft path, nothing bounded the ARV FLOOR (the only code path that RAISES an
# ARV), and the arv-vs-assessed cross-check ran BEFORE the floor so it published
# a ratio that contradicted its own headline number. The result was a 1,400-sqft
# manufactured home published at $780,300 because a general-warehouse CAMA row
# had been joined onto it and the floor adopted that appraisal verbatim.
# ===========================================================================

# ---- $/sqft ceiling --------------------------------------------------------
# Measured implied $/sqft (arv_expected / living_sqft) over the 3,568 board rows
# carrying both: p50 $126, p75 $213, p90 $323, p95 $406, p99 $1,155, max $36,725.
# These are rural/small-metro Carolina markets, so the far tail is not a hot
# submarket — it is a bad comp or a bad sqft. Per-county medians (measured, rows
# with n>=15) vary 4x across the footprint, so a single absolute ceiling would
# either miss Spartanburg garbage or eat legitimate Henderson/Charleston value.
COUNTY_MEDIAN_PPSF = {
    ("SC", "spartanburg"): 83, ("NC", "buncombe"): 283, ("NC", "lincoln"): 215,
    ("NC", "gaston"): 175, ("NC", "transylvania"): 200, ("SC", "anderson"): 176,
    ("NC", "henderson"): 338, ("NC", "rutherford"): 146, ("NC", "cleveland"): 160,
    ("SC", "pickens"): 183, ("NC", "onslow"): 214, ("NC", "burke"): 105,
    ("SC", "laurens"): 196, ("SC", "charleston"): 352, ("SC", "cherokee"): 128,
    ("NC", "mcdowell"): 196, ("SC", "union"): 125, ("SC", "oconee"): 172,
    ("NC", "polk"): 251,
}
BOARD_MEDIAN_PPSF = 126.0     # board-wide p50, used for counties not in the table
# 8x the county median. Measured trip counts on the live board: 4x -> 71 rows,
# 6x -> 59, 8x -> 53, 10x -> 38, 12x -> 30. The curve flattens after 8x, i.e.
# below 8x the ceiling starts cutting into the real spread instead of the tail.
MAX_ARV_PPSF_MULT = 8.0
# Absolute floor under the ceiling so a cheap county's ceiling can never land
# somewhere a genuine renovated house could reach. 8 x Spartanburg's $83 median
# is $664, already above this; it binds only for counties poorer still.
MIN_ARV_PPSF_CEILING = 600.0
# A parcel carrying real acreage has most of its value in DIRT, which inflates
# $/sqft legitimately (a 590-sqft cabin on 8.5 acres is not a $370/sqft house).
# Above this the $/sqft test is meaningless, so it is skipped.
PPSF_CEILING_MAX_ACRES = 2.0
# Manufactured housing: measured on the only county with enough of both classes
# to compare (Spartanburg, n=145 manufactured vs n=1,792 site-built), the COUNTY'S
# OWN appraisal per sqft is $24 vs $48 — a 0.50 ratio. Manufactured county
# appraisals board-wide: p50 $24, p90 $128, p95 $160. The factor only ever
# TIGHTENS a ceiling; it never rewrites a value, so a thin sample cannot inflate
# anything.
MANUFACTURED_PPSF_FACTOR = 0.5

# ---- ARV floor bounds ------------------------------------------------------
# 7,118 board rows (30% of all ARVs) were raised by the floor, and it is the
# only code path in this file that RAISES an ARV.
#
# The obvious guard — "reject any floor that raises the ARV more than Nx" — was
# TESTED AND LARGELY REFUTED. Measuring how many floored rows carry an
# INDEPENDENT reason to distrust the county/sale figure (commercial CAMA class,
# stale/undated deed, shared-centroid coordinate, cross-kind comps), the rate is
# essentially flat with magnitude: 79.7% of raises <=2.5x, 80.5% of 2.5-5x, and
# 83.8% of >5x. A big disagreement is NOT more likely to be a defect than a small
# one, so magnitude is the wrong discriminator and the specific defects below are
# the right ones. This constant survives only as a far backstop, deliberately set
# above the 5.25x raise that tests/test_data_quality.py asserts is legitimate
# behaviour. Rejection is cheap: we keep the comp-grounded ARV at LOW confidence
# rather than blank the lead.
MAX_FLOOR_RAISE_MULT = 6.0
# Above this the floor is honoured but confidence drops and the row is flagged —
# 20.3% of raises this size have no other detectable defect, so silently
# publishing the raised number at MEDIUM overstates what we know.
FLOOR_RAISE_NOTABLE_MULT = 2.5
# A recorded sale may only floor an ARV while it still describes today's market.
# Measured on the 1,393 rows floored by gis.last_sale: 764 have an absent or
# unparseable date, and of the 629 that parse the years run from 1935 to 2026 —
# 269 are pre-2016. The $5.6M "sale" on 933 S Liberty St is a 1992 deed for a
# whole apartment complex. No date == no floor.
FLOOR_SALE_MAX_AGE_YEARS = 10
# A CAMA row whose building_type is commercial cannot floor a residential or
# land lead: that is a mis-joined parcel, not a valuation. 249 board rows carry a
# commercial building_type on a residential/land property_kind, and on 163 of
# them arv_expected already equals market_value exactly — the join has already
# become the headline number.
COMMERCIAL_BUILDING_TYPE_RE = re.compile(
    r"WHSE|WAREHOUS|RETAIL|OFFICE|INDUSTR|BANK|STORE|REST|MOTEL|HOTEL|EXT\s*CARE|"
    r"SHOP|GARAGE|SERVICE|MARKET|CHURCH|SCHOOL|CLINIC|MEDICAL|THEAT|CLUB|PLANT",
    re.I,
)

# ---- ARV vs the county's 100%-basis appraisal ------------------------------
# NOT `assessed_value`. Measured: NC publishes assessed == market on 97.2% of
# rows (7,067/7,270) and never with cents (0/7,276). SC publishes a STATUTORY
# RATIO value — 4% legal residence / 6% everything else — so SC's median
# market/assessed is 18.86 and 4,366 of 7,162 carry cents. Dividing an ARV by an
# SC assessed_value therefore produces a meaningless 800x. Only market_value,
# cama.appraised_value and tax_value are on a 100% basis; 21,552 of the 23,722
# ARV-bearing rows have at least one of them, so nothing is lost by refusing to
# fall back to assessed_value (60 rows).
#
# Thresholds are split by property kind because the two behave differently
# against a county appraisal. Measured ARV/anchor: improved (single_family,
# n=11,795) p50 1.00, p90 2.10, p95 3.98, p99 17.76 — land (n=8,041) p50 1.10,
# p90 7.61, p95 14.22, p99 86.46. Land assessments genuinely lag market far
# harder, so one threshold for both would either miss houses or gut land.
ARV_ANCHOR_SOFT_MULT_IMPROVED = 4.0   # ~p95 for improved
ARV_ANCHOR_HARD_MULT_IMPROVED = 10.0  # between p95 and p99
ARV_ANCHOR_SOFT_MULT_LAND = 6.0       # just under p90 for land; see note
ARV_ANCHOR_HARD_MULT_LAND = 20.0      # just under p99
# ---- When the county disagrees with ITSELF ---------------------------------
# `_anchor_value` takes the FIRST non-null of (market_value, cama.appraised_value,
# tax_value) and never asks whether the other two agree with it. Measured on the
# live board, 1,282 leads carry two or more of those figures disagreeing by >= 3x
# — [23421] holds $148,600 and $1,153,700 for one parcel. At least one of them is
# describing something else, and which one happens to be FIRST is an accident of
# which scraper populated which field.
#
# TWO consequences, and they need different treatments.
#
# (1) THE HARD WITHHOLD. `_arv_sanity`'s anchor test deletes an ARV outright at
#     10x (improved) / 20x (land) the anchor. Measured: 27 leads were withheld
#     against the FIRST figure and would have survived against the LARGEST,
#     deleting $12,980,900 of ARV purely by field order. A withhold is the
#     engine's strongest claim — "no county record can support this number" — so
#     it now has to be true of EVERY county record, not of whichever one sorted
#     first. The SOFT flag still fires off the primary anchor, so those 27 come
#     back as `arv_above_anchor` (CONTRADICTED: published, loudly flagged, no
#     money on it) rather than as a blank row. Publishing the number and the
#     disagreement beats deleting both.
# (2) THE DISAGREEMENT ITSELF is a fact about the lead. WEAK, not contradicted:
#     it does not dispute the ARV, it says the record the ARV was measured
#     against is one of two that cannot both be this parcel.
#
# THE THRESHOLD IS PER-PAIR, because the three fields are not three readings of
# one quantity. Measured over the live board, ratio of the larger to the smaller:
#
#   market_value vs cama.appraised_value   n=6,901   p50 1.00  p90 1.00  p95 1.00
#   cama.appraised_value vs tax_value      n=2,179   p50 1.00  p90 1.00  p95 1.00
#   market_value vs tax_value             n=11,128   p50 1.00  p90 3.44  p95 6.17
#
# Any pair involving the assessor's own appraised value AGREES, exactly, on
# ~95% of leads — 1.00% break 3x. So a 3x break there really is two records
# describing two parcels.
#
# market_value vs tax_value does not behave that way at all: 11.11% break 3x.
# That is not 1,236 broken joins, it is this file's own documented field
# semantics — `li.tax_value` "is a different, often land-only figure" (see the
# tier-1b comment in `_arv_signals`), so a full-market appraisal running several
# times a land-only tax figure is the EXPECTED relationship. A flag that fires
# on one lead in nine for a known difference is wallpaper, and wallpaper is how
# the real warnings came to be ignored. Its curve flattens at ~10x (>=8x 3.02%,
# >=10x 2.17%, >=12x 1.68%), which is where it stops describing the tax roll and
# starts describing a different parcel: 241 leads, the same order as the other
# pairs' natural tail.
COUNTY_VALUE_DISAGREE_MULT = 3.0        # two appraisal-basis figures
COUNTY_VALUE_DISAGREE_MULT_TAX = 10.0   # market value vs the tax roll
ARV_FLAG_COUNTY_DISAGREE = "county_values_disagree"

# The land SOFT multiple deliberately sits BELOW the measured p90 (7.61) rather
# than at it, because that percentile is itself contaminated: it was computed on
# the broken board, where mismatched small-lot comps had already inflated
# thousands of land ARVs. Using it as-is would bless the very distribution being
# repaired. 6.0 catches the 20-acre Henderson lead that otherwise re-emerged as a
# confident 'B' with a $1.27M max bid against a $230,200 county appraisal.

# ---- Land comps: acreage band ---------------------------------------------
# $/acre is strongly size-dependent — the board's own medians decay 0-1ac
# $153,523/ac, 1-5ac $84,091, 5-20ac $35,164, 20-50ac $22,744. Valuing an
# 86.7-acre tract off 0.63-acre building lots (which is exactly what produced a
# $2,769,500 ARV) is not a comp, it is a category error. enrichment_comps has a
# +-50% band at its stage 3 but it is written `if lot_filt:` — when NOTHING falls
# in band it silently keeps the out-of-band pool. Measured: of 4,385 land rows
# with >=2 usable comps, only 615 have >=2 comps within +-50%, 1,539 within a 3x
# ratio and 2,759 within 5x. So the band is applied here (which also repairs the
# already-published board) and WIDENS rather than being all-or-nothing: a 5x
# ratio band still excludes the 0.63-acre-vs-86.7-acre case by 27x.
LAND_COMP_BANDS = (("tight", 2.0), ("wide", 3.0), ("loose", 5.0))

# ---- Do the surviving comps AGREE with each other? -------------------------
# The size band above asks "is this comp the right SIZE". Nothing asked "do the
# comps that passed actually agree", so a pool could pass the band and still be
# two numbers an order of magnitude apart — which the code then AVERAGED.
#
# [29184] 215 N Fork River Road, McDowell NC, 1.09 ac: two in-band comps at
# $23,962/ac and $984,835/ac (the second is an improved sale carrying
# kind:land). Mean $504,398/ac -> ARV $549,800, deal GREAT, max bid $412,400 —
# and `arv_flags` was EMPTY, so no gate downstream could see it. The pair set
# confidence to LOW (the >=3x rule below) and stopped there; a confidence label
# nothing reads is not a guard. This is the reported "trailer on a half acre
# says $700k" bug re-created in the land path.
#
# THRESHOLD, derived from this board's own comp-spread distribution (replay of
# compute() over docs/listings.json, 38,500 leads; 14,737 land leads; 2,889 with
# >=2 in-band comps). Two independent readings of the same data:
#
#  (1) The spread distribution itself. Measured over DISTINCT comp pools
#      (n=521), not per lead (n=2,889): thousands of leads share one
#      city-centroid comp set, so a per-lead histogram is a histogram of which
#      pools got replicated most — its p60 through p92 are all the same single
#      6.45x pool. Distinct-pool percentiles: p50 2.38x, p75 5.05x, p85 8.14x,
#      p90 11.74x, p95 21.64x. The body of the distribution ends at ~8x.
#
#  (2) What real land $/acre variation LOOKS like here, from the same comps:
#      p90/p10 of in-band $/acre within a size band is 10.6x (<=2 ac), 11.0x
#      (<=5 ac), 8.0x (<=10 ac), 9.1x (>10 ac). (The 22-36x readings in the
#      sub-1-acre bands are driven by the single $1,061,016/ac observation this
#      guard exists to catch, so they are not evidence of natural spread.) So
#      ~8-11x IS ordinary $/acre variation in these counties — which is why the
#      threshold is a REFUSAL to average, not a claim that a comp is wrong.
#
# 8.0x is the low end of (2) and p85 of (1). At 8x the mean of a PAIR sits 4.5x
# above its own lower comp — no comp in the pool supports the number being
# published. That is the whole test: not "the comps disagree" (they always do)
# but "the answer is not supported by any of its own evidence".
#
# WHAT HAPPENS, and why it differs by pool size:
#   n == 2  -> REFUSE the pair. There is no central tendency between two numbers
#              that far apart; the mean is an artifact of having exactly two.
#              Fall through to the next tier (recorded-ratio / county anchor),
#              which carries its own guards and its own flags. Marker ->
#              flag `land_comps_disagree`.
#   n >= 3  -> KEEP the median and flag it. A median of 3+ is supported by an
#              actual comp and is robust to one mis-typed sale, so refusing it
#              would delete a defensible answer. Marker -> flag
#              `land_comp_spread`.
# Both flags are WEAK_EVIDENCE in grading.py (verdict withheld, dollars kept and
# captioned) — see the reasoning at ARV_FLAGS_WEAK_EVIDENCE.
#
# NOT this test: the reported $780,300-vs-$121,100 warehouse case (6.4x). That
# is a disagreement between two DIFFERENT RECORDS (comp ARV vs CAMA floor), not
# within one comp pool, and it is caught by floor_rejected_extreme /
# floor_raise_large. Setting this threshold to 6.4 to "cover" it would refuse
# 1,268 leads over ordinary $/acre variation and gut the land board.
LAND_COMP_SPREAD_MAX = 8.0

# ---- Is the county's number a LAND value at all? ---------------------------
# Rejecting mismatched land comps promoted 1,624 leads into the county-anchor
# fallback below, and 144 of them came out WORTH MORE than before — 104 with no
# flag at all. 1030 US 70 TRL (Burke NC, 1.21 ac, asking $29,900) went from
# $4,400 to $713,600 and from NEGOTIATE to GREAT with a $535,200 max bid,
# because the tax record joined to it says $648,710 — $536,567 an acre. That is
# not a land value; it is a house, or another parcel entirely. Refusing bad
# comps must not become a licence to publish an unexamined county number in
# their place, so the anchor now has to survive the same size-vs-price logic the
# comps just failed.
#
# TWO BOUNDS, in preference order:
#
# (1) THE LEAD'S OWN COMPS. $/acre falls as parcels get bigger, so a comp NO
#     BIGGER than the subject caps the subject's $/acre. Measured over all 1,496
#     ordered (smaller, bigger) land-comp pairs on the board: the smaller parcel
#     carries the higher $/acre on 70.2% of pairs overall, and the relationship
#     tightens exactly where this test is used — 89.5% at a >=5x size gap, 94.1%
#     at 10-50x, 100% beyond 50x. (LAND_COMP_BANDS' widest band is 5x, so a
#     "rejected" pool always sits outside it.) The tolerance below is the price
#     of the remaining noise: at a >=5x gap a bigger parcel out-prices a smaller
#     one by more than 3x on 6 of 390 pairs (1.54%), vs 3.59% at 2x and 10.51%
#     at 1x. So 3x is where the curve flattens.
LAND_ANCHOR_PPA_TOL = 3.0
# (2) THE MARKET, when no comp is small enough to bound anything. p99 of the
#     $/acre of every REAL land sale on the board in the subject's size band
#     (n=66/73/116/86/72/35/35 per band; bands merged until each held >=25
#     sales, and the curve forced monotone because $/acre must fall with size).
#     Deliberately the 99th percentile of ACTUAL SALES, not of county anchors:
#     the anchor distribution is contaminated by improved parcels mis-typed as
#     land (its 0-0.25ac median is $1.7M/acre against $234k for real sales), so
#     calibrating on it would bless the very records being tested.
LAND_SALE_PPA_CEILING = (
    (0.25, 1_886_000),   # p99 $1,886,182  (max observed $2,000,000)
    (0.5,  1_342_000),   # p99 $1,342,323
    (1.0,    966_000),   # p99 $  966,678
    (2.0,    536_000),   # p99 $  536,158
    (5.0,    349_000),   # p99 $  349,360
    (10.0,   144_000),   # p99 $  144,556
    (float("inf"), 64_000),  # p99 $   64,543
)
# Note markers. `_land_arv` can only speak in notes (its return signature is
# fixed by four other tests), so compute() reads these back to raise the flags.
LAND_ANCHOR_REFUSED_MARKER = "not usable as a land value"
LAND_COMPS_REJECTED_MARKER = "Land comps rejected"
# Kept textually distinct from LAND_COMPS_REJECTED_MARKER: the read-back below
# is a substring test, so a marker that contains another marker would raise two
# flags off one note. "rejected" (wrong size) / "refused" (disagree) / "span".
LAND_COMPS_DISAGREE_MARKER = "Land comp pair refused"
LAND_COMP_SPREAD_MARKER = "Land comps span"
# An ARV that IS the county's number times a constant cannot be checked AGAINST
# the county's number. Every tier that does that says so, and compute() reads it
# back to skip the cross-check and mark the lead instead of passing it.
COUNTY_ANCHOR_MARKER = "derived from the county's own valuation"

# ---- Bid-derived ARV is circular ------------------------------------------
# When ARV is `opening_bid × 2.4` (or `× 1.5` on land), every downstream metric
# that divides the bid by the ARV is dividing a number by a fixed multiple of
# itself. Measured on the board: of the 405 leads whose ARV is a bid proxy, 316
# are graded exactly C and 297 read deal_status GREAT — not because 297 bargains
# were found, but because bid / (bid × 2.4) is always 0.4167 and bid / (bid ×
# 1.5) is always 0.667, which land on fixed rungs of the financial-score ladder.
# The ARV itself is a legitimate last-resort estimate; the VERDICTS derived from
# it are not, so they are suppressed and the reason is stated.
BID_PROXY_MARKER = "proxy from bid"


# ---- Per-county ARV calibration --------------------------------------------
# The comp-$/sqft ARV carries a measured, systematic per-county bias (backtest:
# some counties over-value ~+80-90%, others under-value ~-30%). A one-time
# calibration multiplier per county (factor = 1 / (1 + median_bias), generated
# by `scripts/backtest_arv.py --emit-calibration`) corrects it. Missing file or
# an unknown county -> factor 1.0 (fully inert), so the engine is unchanged
# until a calibration table is generated. Factors outside [0.4, 2.5] are
# ignored as a safety guard against a bad table swinging ARV wildly.
_CALIB_PATH = Path(__file__).resolve().parents[3] / "data" / "arv_calibration.json"
_CALIB_CACHE: dict[str, float] | None = None


def _load_arv_calibration() -> dict[str, float]:
    """Load {normalized_county: factor}, cached. Safe if the file is absent."""
    global _CALIB_CACHE
    if _CALIB_CACHE is None:
        try:
            raw = json.loads(_CALIB_PATH.read_text())
            factors = raw.get("factors", raw) if isinstance(raw, dict) else {}
            _CALIB_CACHE = {
                str(k).strip().lower(): float(v)
                for k, v in factors.items()
                if isinstance(v, (int, float))
            }
        except Exception:
            _CALIB_CACHE = {}
    return _CALIB_CACHE


def _arv_calibration_factor(li: Listing) -> float:
    county = (getattr(li, "county", None) or "").strip().lower()
    if not county:
        return 1.0
    f = _load_arv_calibration().get(county, 1.0)
    return f if 0.4 <= f <= 2.5 else 1.0


def _refuse(sink: list | None, flag: str, value: float | None = None) -> None:
    """Record a REFUSAL so compute() can raise a flag for it.

    The ARV tiers can only speak in `notes` — `_arv_signals` and `_land_arv`
    both return a fixed 5-tuple that seven tests unpack positionally — and a
    note is not a flag: nothing downstream gates on prose. The existing idiom
    for this is a marker string read back out of the notes (see
    LAND_COMPS_REJECTED_MARKER and friends), which works for a verdict but
    cannot carry the NUMBER that was refused, and `arv_withheld` is exactly that
    number.

    So refusals go into an optional sink list instead: `sink.append((flag,
    value))`. The parameter defaults to None, so every existing caller —
    including the three tests that call `_arv_signals(li)` with one argument —
    is untouched, and a caller that wants the verdicts passes a list.
    """
    if sink is not None:
        sink.append((flag, value))


def _plausible_living_sqft(li: Listing) -> float | None:
    """Subject living_sqft usable for a $/sqft ARV, or None if implausible.

    Defensive: anything outside [LIVING_SQFT_MIN, LIVING_SQFT_MAX] is treated as
    missing so a bad parse can't fabricate an ARV. Non-positive / non-numeric
    values also return None.
    """
    sqft = li.living_sqft
    try:
        sqft = float(sqft) if sqft is not None else None
    except (TypeError, ValueError):
        return None
    if not sqft or sqft <= 0:
        return None
    if sqft < LIVING_SQFT_MIN or sqft > LIVING_SQFT_MAX:
        return None
    return sqft

# ---- The seller's own asking price ----------------------------------------
# THE DEFECT. `RETAIL_PRICE_SOURCES` named only the two house portals, so the
# ARV-vs-list cross-check below never ran on the two LAND portals — where
# `opening_bid` is not an auction floor at all but a price the owner is publicly
# asking. Measured on the live board (597 leads across the two, 555 carrying
# both an ARV and an ask), the blind spot bit in BOTH directions:
#
#   OVER  — 83 leads carry an ARV >= 1.6x the ask, 31 at >= 3x (median 4.5x).
#           48 publish a max bid that EXCEEDS the asking price, $13,844,500 of
#           them. [1073] Lot 28 Big Hill Road, Transylvania NC is listed at
#           $120,000 and the board answered ARV $834,700, max bid $626,000, ROI
#           342.5%, GREAT, arv_flags None. On an AUCTION row a 7x gap is the flip
#           thesis and clamping it would kill every real deal — which is why the
#           check only ever fired downward. On a RETAIL row it is not a thesis,
#           it is a contradiction: anyone may buy the parcel at the ask, so an
#           ARV several times the ask says the comps, not the seller, are wrong.
#   UNDER — 113 leads where the ask is more than 3x the ARV (median 6.0x, worst
#           301x). Cause: the land tier order puts the county anchor ahead of any
#           listing price, and an NC present-use / forestry deferment value
#           (G.S. 105-277.2) is legally 5-20% of market. [33422] 3465 Yancey Road
#           carries a $6,290,000 ask against a $20,900 ARV and a $15,700 max bid.
#
# Adding the two sources to RETAIL_PRICE_SOURCES fixes UNDER with code that
# already exists and is already tested: the `ratio < 0.6` branch anchors the ARV
# to the listing price, i.e. it makes a published asking price OUTRANK a
# present-use assessment, which is the correct precedence — one is a price
# somebody is actually asking, the other is a statutory fraction of one.
#
# OVER needs the new half, because that direction was deliberately silent:
# `ARV_VS_ASK_MAX` below. Kept as its own set so the downward anchor and the
# upward flag can never be applied to an auction source by accident.
SELLER_ASK_SOURCES = {
    "national.landwatch",
    "national.landandfarm",
}

# Sources where opening_bid is a retail asking price (and therefore a useful
# ARV sanity-check). For everything else (auctions, lis pendens, REO floors,
# law-firm foreclosure sales) the bid is a discount-to-ARV floor — clamping
# ARV to bid would silently kill the entire flip thesis.
RETAIL_PRICE_SOURCES = {
    "national.homeharvest",
    "national.realtor_foreclosures",
} | SELLER_ASK_SOURCES

# The same 1.6x the "high-discount signal" branch has always used, now given a
# name because on a SELLER-ASK source it stops being a signal and becomes a
# verdict. CONTRADICTED in grading.py: the ask is a price the whole market can
# transact at today, so an ARV 60%+ above it is not upside, it is two records
# describing different dirt.
ARV_VS_ASK_MAX = 1.6
ARV_FLAG_ABOVE_ASK = "arv_above_list_price"

# ---- A land parcel carrying a house's square footage -----------------------
# 315 board leads are typed `land` and carry a living_sqft inside the plausible
# [300, 10000] dwelling band. `_arv_signals` reads that as "mis-typed house" and
# routes them to the $/sqft path (see its comment) — a defensible reading, but
# only one of the two available: the other is that the sqft came off a different
# parcel. Nothing on the record says which, and both cannot be true.
#
# Measured after the trust gate: 227 of the 315 publish a max bid, $56,935,000
# in total, and 89 of those carried NO arv_flag at all. [1073] Lot 28 Big Hill
# Road is a numbered LOT priced as a 3,420-sqft house.
#
# So this is flagged, not resolved. CONTRADICTED, because "another record
# disputes the number that shipped" is exactly what a kind/sqft conflict is, and
# because the cost of being wrong runs one way: withholding a bid on a real
# house loses a lead, publishing one on a bare lot loses an auction deposit.
ARV_FLAG_LAND_SQFT = "arv_land_sqft_mismatch"


@dataclass
class Calc:
    arv_low: float | None = None
    arv_expected: float | None = None
    arv_high: float | None = None
    rehab_low: float | None = None
    rehab_expected: float | None = None
    rehab_high: float | None = None
    rehab_tier: str | None = None
    rehab_with_contingency: float | None = None   # rehab_expected + 12.5% surprise buffer
    max_bid_70: float | None = None
    wholesale_mao: float | None = None            # max_bid − assignment fee (wholesale lens)
    wholesale_spread: float | None = None         # max_bid − opening_bid (assignable margin)
    total_investment: float | None = None
    estimated_profit: float | None = None
    roi_pct: float | None = None
    cash_on_cash_pct: float | None = None
    bid_to_arv_pct: float | None = None
    confidence: str = "LOW"
    # ARV-METHOD confidence (distinct from `confidence`, which scores overall
    # data completeness): HIGH = sold-comp grounded, MEDIUM = zestimate or
    # county tax/appraised value, LOW = opening-bid guess. grading.py reads this
    # to decide whether a listing is assessable enough to rate.
    arv_confidence: str | None = None
    arv_vs_assessed: float | None = None   # ARV / county 100%-basis appraisal (accuracy anchor)
    # Sanity-band telemetry (see the ARV SANITY BAND block above). `arv_flags`
    # names every guard that fired; `arv_withheld` carries the number we computed
    # but refused to publish, so the reason is auditable instead of the lead just
    # going blank. Both stay None on a clean lead, so `to_dict` omits them and the
    # board's shape is unchanged for the ~87% of ARVs that trip nothing.
    arv_flags: list[str] | None = None
    arv_withheld: float | None = None
    notes: list[str] | None = None
    # Flip framing — what's the deal status at the listed/asking price?
    deal_status: str | None = None         # GREAT / OK / NEGOTIATE / PASS
    deal_message: str | None = None        # human-readable explanation
    haircut_needed: float | None = None    # $ user needs to negotiate down to flip
    # Buy-and-hold framing — for investors who'd rent rather than flip.
    # Computed when rent comp data is available (raw.rent_median_ppsf).
    monthly_rent_est: float | None = None
    annual_gross_rent: float | None = None
    noi_annual: float | None = None        # NOI = 50% of gross (industry rule)
    cap_rate_pct: float | None = None      # NOI / acquisition cost
    monthly_cashflow_est: float | None = None  # after PITI debt service
    hold_status: str | None = None         # GREAT / OK / NEGOTIATE / PASS
    hold_message: str | None = None
    one_pct_rule: bool | None = None       # rent ≥ 1% of total acq cost


def _condition_to_tier(li: Listing) -> str:
    """Pick rehab tier from condition_tier (set by enrichment_comps), flags, year built.

    Maps the four-tier condition (move_in_ready / cosmetic / major / gut)
    to the five-tier rehab cost table (cosmetic / light / moderate / heavy / gut).
    Reads condition_tier from raw.vision.condition_tier first (Vision-grounded,
    most accurate), then raw.condition_tier (legacy enrichment_comps mirror).
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    cond = (raw.get("vision") or {}).get("condition_tier") or raw.get("condition_tier")
    cond_map = {
        "move_in_ready": "cosmetic",
        "cosmetic": "light",
        "major": "moderate",
        "gut": "gut",
    }
    if cond and cond in cond_map:
        return cond_map[cond]

    # Fallback: legacy flags-based detection
    flags = raw.get("flags", []) if isinstance(raw, dict) else []
    flag_blob = " ".join(flags).lower() if isinstance(flags, list) else ""

    if any(k in flag_blob for k in ("tear down", "fire damage", "uninhabitable", "condemned", "gutted")):
        return "gut"
    if any(k in flag_blob for k in ("foundation", "structural", "termite", "no power", "no water")):
        return "heavy"
    if any(k in flag_blob for k in ("vacant", "abandoned", "boarded", "hoarder", "as-is", "as is", "investor special")):
        return "moderate"
    if any(k in flag_blob for k in ("fixer", "rehab", "needs work", "tlc", "water damage", "mold")):
        return "moderate"
    if any(k in flag_blob for k in ("renovated", "remodeled", "move-in", "turnkey", "new roof", "new hvac")):
        return "cosmetic"

    yb = li.year_built
    if yb:
        age = datetime.utcnow().year - yb
        if age >= 80:
            return "heavy"
        if age >= 50:
            return "moderate"
        if age >= 25:
            return "light"
        return "cosmetic"
    return "moderate"


def _acreage_for(li: Listing) -> float | None:
    """Best-available acreage value for a listing, in acres."""
    if li.acreage and li.acreage > 0:
        return float(li.acreage)
    if li.lot_size_sqft and li.lot_size_sqft > 0:
        return float(li.lot_size_sqft) / 43560.0
    return None


# --- Property-class awareness -----------------------------------------------
# The board carries 791 leads that are identifiably manufactured housing, but
# only 7 of them have `property_kind == MOBILE` (523 are tagged land, 256
# single_family). The signal was already on disk in two fields nothing in the
# valuation path read: `land_use` (the county's own property class) and
# `raw.cama.building_type`. Consequence before this fix: MOBILE_REHAB_TIERS —
# a table this codebase built specifically for manufactured homes — fired on 7
# leads out of 791, and 430 manufactured leads were valued off site-built comps.
_MANUFACTURED_TOKENS = (
    "mobile home", "manufactured", "mfg home", "doublewide", "double wide",
    "singlewide", "single wide", "modular home",
)
# land_use is only trusted to RE-classify a lead whose own kind is unset or
# consistent with a manufactured dwelling. A lead explicitly typed multi_family /
# commercial / condo keeps its kind — a HUD multi-family inspection lead that
# picked up a "Mobile Home Lot" land_use from a bad parcel join must not start
# pricing its rehab off the manufactured table.
_MANUFACTURED_OVERRIDABLE_KINDS = (
    PropertyKind.UNKNOWN, PropertyKind.LAND,
    PropertyKind.SINGLE_FAMILY, PropertyKind.MOBILE,
)


def _is_manufactured(li: Listing) -> bool:
    """True when this lead is manufactured/mobile housing by ANY reliable signal.

    Order: the lead's own property_kind (authoritative when set), then the
    county's land_use class, then the assessor CAMA building_type.
    """
    if li.property_kind == PropertyKind.MOBILE:
        return True
    if li.property_kind not in _MANUFACTURED_OVERRIDABLE_KINDS:
        return False
    lu = (getattr(li, "land_use", "") or "").lower()
    if any(t in lu for t in _MANUFACTURED_TOKENS):
        return True
    raw = li.raw if isinstance(li.raw, dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    bt = str(cama.get("building_type") or "").lower()
    return any(t in bt for t in _MANUFACTURED_TOKENS)


def _commercial_building_type(li: Listing) -> str | None:
    """The assessor building_type when it is COMMERCIAL and the lead is not.

    A non-None return means the CAMA row joined onto this lead describes a
    different class of building than the lead itself — i.e. a mis-joined parcel,
    which makes every dollar figure that came from that row untrustworthy.
    """
    if li.property_kind in (PropertyKind.COMMERCIAL, PropertyKind.MIXED,
                            PropertyKind.MULTI_FAMILY):
        return None
    raw = li.raw if isinstance(li.raw, dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    bt = str(cama.get("building_type") or "").strip()
    if bt and COMMERCIAL_BUILDING_TYPE_RE.search(bt):
        return bt
    return None


def _anchor_value(li: Listing) -> tuple[float | None, str | None]:
    """The county's valuation of this parcel on a 100% (full-market) basis.

    Deliberately EXCLUDES `assessed_value`: in South Carolina that field is a
    statutory ratio value (4% legal residence / 6% other), so ARV/assessed is a
    unit error, not a signal — it is what produced the "ARV is 800x the assessed
    value" artifact. Returns (value, source_label).
    """
    # A CAMA row describing a commercial building on a residential/land lead is a
    # mis-joined parcel. Every dollar figure that came off that join is suspect,
    # so it is not an anchor either — otherwise the same wrong record that was
    # blocked from flooring the ARV walks straight back in as the thing we
    # measure the ARV against, and as the land fallback value.
    if _commercial_building_type(li):
        return None, None
    raw = li.raw if isinstance(li.raw, dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    for val, label in (
        (li.market_value, "county market value"),
        (cama.get("appraised_value"), "assessor appraised value"),
        (li.tax_value, "tax-assessed value"),
    ):
        try:
            v = float(val) if val is not None else None
        except (TypeError, ValueError):
            continue
        if v and v > 1000:
            return v, label
    return None, None


def _county_values(li: Listing) -> list[tuple[float, str]]:
    """EVERY 100%-basis county figure on this lead, in preference order.

    `_anchor_value` returns the first of these and `_cross_check_anchor` the
    first without the commercial veto; both of those are "which one number do we
    use" questions and their answers are unchanged. This is the different
    question the file never asked: "do the county's own records agree with each
    other?" See COUNTY_VALUE_DISAGREE_MULT for what the answer is worth.

    No commercial veto here on purpose — the same reasoning as
    `_cross_check_anchor`. A mis-joined assessor row still disagreeing 8x with
    the tax roll is a fact about the lead; the flag it raises never upgrades
    anything, it only discloses.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    out: list[tuple[float, str]] = []
    for val, label in (
        (li.market_value, "county market value"),
        (cama.get("appraised_value"), "assessor appraised value"),
        (li.tax_value, "tax-assessed value"),
    ):
        try:
            v = float(val) if val is not None else None
        except (TypeError, ValueError):
            continue
        if v and v > 1000:
            out.append((v, label))
    return out


def _cross_check_anchor(li: Listing) -> tuple[float | None, str | None, bool]:
    """The county figure to MEASURE the ARV against. Returns (value, label, trusted).

    Distinct from `_anchor_value` on purpose. `_anchor_value` answers "may this
    number RAISE the ARV / become the ARV?", and a commercial assessor row joined
    to a house must never do either. But refusing it there also silently deleted
    the guardrail: measured on the board, all 176 mis-joined leads that keep an
    ARV carry `arv_vs_assessed == None`, and five of them publish an ARV more
    than 10x the county figure the code declined to look at — 616 N CHURCH ST at
    $643,200 against $13,435, 47.9x, at MEDIUM confidence with a max bid beside
    it. Whichever of the two records is wrong, a 47.9x disagreement is a fact
    about the lead and the reader is entitled to it.

    So the cross-check reads the same fields WITHOUT the commercial veto, and
    reports `trusted=False` when the join is known-bad — measuring against a
    suspect number is worth doing; treating agreement with it as reassurance is
    not, which is why `trusted` never upgrades anything, only labels.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    trusted = _commercial_building_type(li) is None
    for val, label in (
        (li.market_value, "county market value"),
        (cama.get("appraised_value"), "assessor appraised value"),
        (li.tax_value, "tax-assessed value"),
    ):
        try:
            v = float(val) if val is not None else None
        except (TypeError, ValueError):
            continue
        if v and v > 1000:
            return v, (label if trusted else f"{label} (from a MIS-JOINED assessor record)"), trusted
    return None, None, trusted


def _land_sale_ppa_ceiling(acres: float) -> float:
    """Highest $/acre any REAL land sale on the board reached at this size."""
    for upper, ceiling in LAND_SALE_PPA_CEILING:
        if acres < upper:
            return float(ceiling)
    return float(LAND_SALE_PPA_CEILING[-1][1])


def _land_anchor_supported(subj_ac: float, anchor: float,
                           priced: list[tuple[float, float]]) -> tuple[bool, str]:
    """Can the county's number be read as the value of THIS dirt?

    `priced` is the lead's own land-comp pool as (ppa, comp_acres) — including
    the comps the acreage band refused, because a comp can be the wrong SIZE for
    a $/acre transfer and still be a real sale in the right PLACE.

    Returns (supported, why). See LAND_ANCHOR_PPA_TOL / LAND_SALE_PPA_CEILING
    for where both bounds come from and what they cost.
    """
    ppa = anchor / subj_ac
    # (1) A comp no bigger than the subject caps the subject's $/acre, because
    #     $/acre falls with size. Prefer this: it is the lead's own evidence.
    smaller = [p for p, ac in priced if ac <= subj_ac]
    if smaller:
        bound = max(smaller) * LAND_ANCHOR_PPA_TOL
        if ppa > bound:
            return False, (
                f"${ppa:,.0f}/acre, but land no bigger than this {subj_ac:.2f}-acre "
                f"parcel sold nearby for at most ${max(smaller):,.0f}/acre — and "
                f"smaller parcels price HIGHER per acre, not lower"
            )
        return True, ""
    # (2) Nothing small enough to bound it — fall back to what land at this size
    #     has actually sold for anywhere on the board.
    ceiling = _land_sale_ppa_ceiling(subj_ac)
    if ppa > ceiling:
        return False, (
            f"${ppa:,.0f}/acre, above the ${ceiling:,.0f}/acre that no land sale "
            f"of this size on the board has reached"
        )
    return True, ""


def _arv_ppsf_ceiling(li: Listing, manufactured: bool) -> float:
    """Highest defensible ARV $/sqft for this lead's county."""
    key = ((li.state or "").strip().upper(), (li.county or "").strip().lower())
    med = float(COUNTY_MEDIAN_PPSF.get(key, BOARD_MEDIAN_PPSF))
    ceiling = max(MAX_ARV_PPSF_MULT * med, MIN_ARV_PPSF_CEILING)
    if manufactured:
        ceiling *= MANUFACTURED_PPSF_FACTOR
    return ceiling


_EPOCH = datetime(1970, 1, 1)
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
# Every shape gis.last_sale.date actually arrives in, counted on the board's
# 19,828 sale records: 15,222 ISO `YYYY-MM-DD`; 3,347 absent; 824 a bare epoch
# integer (662 at 13 digits, 121 at 12, 40 negative, 4 at 11); 392 a bare
# `YYYY`; 40 Oracle-style `DD-MON-YY`.
_ISO_RE = re.compile(r"^(1[89]\d{2}|20\d{2})[-/](\d{1,2})[-/](\d{1,2})")
_US_RE = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](1[89]\d{2}|20\d{2})$")
_ORACLE_RE = re.compile(r"^(\d{1,2})-([A-Z]{3})-(\d{2})$", re.I)
_INT_RE = re.compile(r"^-?\d+$")


def _plausible_year(yr: int | None) -> int | None:
    return yr if (yr is not None and 1800 <= yr <= datetime.utcnow().year + 1) else None


def _epoch_year(v: float) -> int | None:
    """Year of an epoch stamp, trying the scale its MAGNITUDE implies first.

    Seconds and milliseconds are not distinguishable from digit count alone —
    the board carries 11-, 12- and 13-digit millisecond stamps and negative ones
    for pre-1970 deeds. Anything at or above 1e11 can only be milliseconds (as
    seconds it would land past the year 5000); below that, seconds is the
    natural reading and milliseconds is the fallback.
    """
    for div in ((1000.0, 1.0) if abs(v) >= 1e11 else (1.0, 1000.0)):
        try:
            yr = (_EPOCH + timedelta(seconds=v / div)).year
        except (OverflowError, OSError, ValueError):
            continue
        if _plausible_year(yr):
            return yr
    return None


def _sale_year(sale: dict | None) -> int | None:
    """Four-digit year of a gis.last_sale record, or None when unusable.

    PARSES the date rather than regexing a year out of it. The old
    `re.search(r"(1[89]\\d{2}|20\\d{2})")` matched any four adjacent digits that
    happened to look like a year, so an epoch-millisecond stamp answered with
    whatever sat in its middle: "165751200000" (2022-07-01) read as 2000,
    "20995200000" (1970) read as 2099, "-441849600000" (1956) read as 1849.
    827 board rows carry a bare epoch date and 474 of them decode to 2016 or
    later — every one of those was being refused as a stale floor on the
    strength of a fabricated year, and 15 published an investor-facing note
    asserting it.

    An absent or genuinely unparseable date still returns None: an undated sale
    amount is not evidence about today's market.
    """
    if not isinstance(sale, dict):
        return None
    s = str(sale.get("date") or "").strip()
    if not s:
        return None

    m = _ISO_RE.match(s)
    if m:
        return _plausible_year(int(m.group(1)))
    m = _US_RE.match(s)
    if m:
        return _plausible_year(int(m.group(3)))
    m = _ORACLE_RE.match(s)
    if m and m.group(2).upper() in _MONTHS:
        yy = int(m.group(3))
        # Two-digit years pivot on today: a deed dated "25" is 2025, "75" is
        # 1975. Recording dates are never in the future.
        cur2 = datetime.utcnow().year % 100
        return _plausible_year(2000 + yy if yy <= cur2 else 1900 + yy)

    if _INT_RE.match(s):
        neg = s.startswith("-")
        digits = s[1:] if neg else s
        # YYYYMMDD (the assessor CAMA style, e.g. "19931014"). As an epoch this
        # would read 1970; as a year-first date it is unambiguous.
        if not neg and len(digits) == 8 and _plausible_year(int(digits[:4])):
            return int(digits[:4])
        if not neg and len(digits) == 4:
            return _plausible_year(int(digits))
        try:
            return _epoch_year(float(s))
        except (TypeError, ValueError):
            return None

    # Free text ("Sold 2019", "recorded 03/2021") — a year token is the best
    # available read once the structured shapes are exhausted. Numeric strings
    # never reach here, so this can no longer mine a year out of an epoch.
    m = re.search(r"(1[89]\d{2}|20\d{2})", s)
    return _plausible_year(int(m.group(1))) if m else None


def _land_arv(li: Listing, refused: list | None = None
              ) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Land-specific ARV path. Comps come pre-filtered by lot acreage band
    (±50% in enrichment_comps), so use sold_price ÷ acreage to get $/acre,
    then apply to the subject's acreage. No living_sqft involvement.

    `refused` is the optional refusal sink — see `_refuse`. Three tiers here can
    blow MAX_PROXY_ARV, and two of them used to do it in complete silence.
    """
    notes: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    comps = raw.get("comps") or []
    subj_ac = _acreage_for(li)

    # The lead's own land-comp pool, priced per acre. Built OUTSIDE the tier-1
    # block on purpose: when the size band refuses these comps, tier 2 still
    # needs them to judge whether the county's number is a plausible land value.
    # They are the wrong size for a $/acre transfer, but they are real sales in
    # the right place, and that is enough to bound an anchor.
    priced: list[tuple[float, float]] = []
    for c in comps:
        sp = c.get("sold_price")
        lot = c.get("lot_sqft")
        if sp and lot and float(lot) > 0:
            comp_ac = float(lot) / 43560.0
            ppa = float(sp) / comp_ac
            # Reject above the rural ceiling — a $/acre this high is almost
            # always a parse error (per-sqft figure or a near-zero lot) and
            # would emit a multi-million phantom land ARV. Skip the bad comp.
            if ppa > MAX_LAND_PPA:
                continue
            priced.append((ppa, comp_ac))

    # Tier 1: $/acre from land comps × subject acreage
    if comps and subj_ac:
        # SIZE BAND (see LAND_COMP_BANDS): $/acre is strongly size-dependent, so a
        # comp is only comparable if its own acreage is in the same league as the
        # subject's. enrichment_comps is supposed to have filtered here, but its
        # `if lot_filt:` silently keeps the unfiltered pool when nothing matches —
        # which is how 0.63-acre building lots came to price an 86.7-acre tract.
        # Re-applied here so the ALREADY-PUBLISHED board is repaired too, and
        # widened progressively so a merely-imperfect pool still produces a value.
        ppa_list: list[float] = []
        band_label = None
        for label, ratio in LAND_COMP_BANDS:
            in_band = [p for p, ac in priced
                       if subj_ac / ratio <= ac <= subj_ac * ratio]
            if len(in_band) >= 2:
                ppa_list, band_label = sorted(in_band), label
                break
        if len(priced) >= 2 and not ppa_list:
            notes.append(
                f"{LAND_COMPS_REJECTED_MARKER}: none within "
                f"{LAND_COMP_BANDS[-1][1]:.0f}x the subject's {subj_ac:.2f} ac (comp lots "
                f"{min(a for _, a in priced):.2f}-{max(a for _, a in priced):.2f} ac). "
                f"$/acre does not transfer across that size gap."
            )
        # AGREEMENT TEST (see LAND_COMP_SPREAD_MAX). Runs after the size band and
        # before anything is averaged, because the failure it catches is the
        # AVERAGING itself, not the selection.
        spread = None
        if len(ppa_list) >= 2 and ppa_list[0] > 0:
            spread = ppa_list[-1] / ppa_list[0]
            if spread >= LAND_COMP_SPREAD_MAX and len(ppa_list) == 2:
                notes.append(
                    f"{LAND_COMPS_DISAGREE_MARKER}: the two in-band land comps disagree "
                    f"by {spread:.0f}x (${ppa_list[0]:,.0f}/ac vs ${ppa_list[-1]:,.0f}/ac). "
                    f"Their mean (${sum(ppa_list) / 2.0:,.0f}/ac) sits "
                    f"{(1 + spread) / 2:.1f}x above the cheaper comp and is supported by "
                    f"neither, so it is not published as a land value. Two numbers this "
                    f"far apart are not a market — at least one is not a land sale."
                )
                ppa_list = []   # fall through to the recorded-ratio / anchor tiers
                # `priced` IS DELIBERATELY LEFT WHOLE for the tiers below, and
                # this is the second thing tried here, not the first.
                #
                # Measured consequence of the refusal, replaying both versions
                # over the live board: 32 of these 118 leads come out worth MORE
                # than the mean they lost, and 27 gain a max bid they did not
                # previously publish. So the obvious next move is to stop the
                # comp we have just called "probably not land" from underwriting
                # the fallback: drop it from `priced`, which tier 2 uses to bound
                # the county anchor (`_land_anchor_supported`).
                #
                # THAT WAS TRIED AND IT IS WRONG. `_land_anchor_supported` bounds
                # on `max(comps no bigger than the subject) x TOL` and only falls
                # back to the board-wide market ceiling when NO comp is small
                # enough. Removing the top comp can therefore delete the only
                # small comp there is and flip the test onto the LOOSER market
                # ceiling. Measured: 5 leads changed, and it went the wrong way
                # on 2 of them — [300] 139 Lone Eagle Ln, Henderson (0.38 ac) is
                # refused today at $219,054/ac (3x its own 0.31-acre comp at
                # $73,018) and would have been ACCEPTED at $969,210/ac against
                # the <=0.5-acre market ceiling, publishing a $565,200 ARV and a
                # $423,900 max bid out of nothing. Pruning evidence to punish a
                # bad comp removed a good bound. Left as a comment because the
                # idea reads as obviously correct and is not.
                #
                # What the 32 up-moves actually are, checked lead by lead: the
                # value comes from a DIFFERENT tier, each with its own guards and
                # its own flag. [1524] 259 Bull Creek Rd goes to tier 1b, priced
                # off 19 recorded arms-length sales at MEDIUM — strictly better
                # evidence than the pair it replaced. [20287] McDowell goes to
                # the county anchor and carries `anchor_not_independent`. None of
                # the 148 ends up flagless (measured: 83 -> 0), none publishes a
                # verdict (17 -> 0), and calc's refusal note — which quotes both
                # $/acre figures — is published in `notes` either way. The
                # disagreement is disclosed; it is just no longer averaged.

        if len(ppa_list) >= 2:
            # With exactly two comps `ppa_list[len//2]` is index 1 — the MAXIMUM,
            # not a median. That alone put a 20-acre Henderson lead at $2,031,800
            # (it published arv_expected == arv_high, the tell). Use the mean of
            # the pair instead; 3+ comps keep the true median.
            mid = (sum(ppa_list) / 2.0) if len(ppa_list) == 2 else ppa_list[len(ppa_list) // 2]
            low_ppa = ppa_list[0]
            high_ppa = ppa_list[-1]
            expected = round(mid * subj_ac, -2)
            low = round(low_ppa * subj_ac, -2)
            high = round(high_ppa * subj_ac, -2)
            notes.append(
                f"ARV from {len(ppa_list)} land comps × {subj_ac:.2f} ac "
                f"(${mid:,.0f}/ac median; range ${low_ppa:,.0f}-${high_ppa:,.0f}/ac; "
                f"comp lots within {band_label} size band)"
            )
            # 2026-06-19: a >=3x low/high spread means the comps disagree wildly
            # ($/acre varies hugely by location) — don't present that as HIGH.
            conf = "LOW" if (low and high and low > 0 and high / low >= 3) else "HIGH"
            # A widened band means the comps are NOT the same size class as the
            # subject; the number is usable but not bankable.
            if band_label != "tight" and conf == "HIGH":
                conf = "MEDIUM"
                notes.append(
                    f"ARV confidence lowered to MEDIUM: land comps only matched at the "
                    f"'{band_label}' acreage band, not like-for-like size."
                )
            # Two comps are not a market. The improved $/sqft path has capped
            # sub-3-comp ARVs at MEDIUM since it was written (:407); the land path
            # never did, so a 20-acre Henderson lead carrying exactly two comps
            # published HIGH confidence — and, with the median-of-two bug above,
            # published its own maximum as the expected value.
            if len(ppa_list) < 3 and conf == "HIGH":
                conf = "MEDIUM"
                notes.append(
                    f"ARV confidence lowered to MEDIUM: only {len(ppa_list)} land comp(s) "
                    f"in the acreage band."
                )
            # A surviving pool (>=3 comps) that still spans LAND_COMP_SPREAD_MAX
            # keeps its MEDIAN — that number is a real comp, not an artifact —
            # but it is stated, LOW, and FLAGGED. The old code set LOW here and
            # emitted nothing, which is precisely how a 41x pool shipped a GREAT.
            if spread is not None and spread >= LAND_COMP_SPREAD_MAX:
                conf = "LOW"
                notes.append(
                    f"{LAND_COMP_SPREAD_MARKER} {spread:.0f}x (${low_ppa:,.0f}-"
                    f"${high_ppa:,.0f}/ac), wider than $/acre varies naturally in this "
                    f"size class on this board (~8-11x between the 10th and 90th "
                    f"percentile). The median is a real comp and is published, but at "
                    f"least one sale in this pool is probably not comparable land — "
                    f"read the ${low:,.0f}-${high:,.0f} range, not the point."
                )
            return expected, low, high, conf, notes

    # Tier 1b: RECORDED sale-to-assessment ratio from nearby vacant-lot sales
    # (enrichment_recorded_sales). Beats the flat ×1.10 below because the
    # multiplier is measured from this submarket's actual recorded sales instead
    # of assumed. Never HIGH — it is a ratio proxy, not a like-for-like comp.
    ratio_c = raw.get("recorded_ratio_comps") or {}
    ratio = ratio_c.get("median_ratio")
    basis = ratio_c.get("assessed_basis")
    if ratio and basis and float(basis) > 0 and int(ratio_c.get("count") or 0) >= 3:
        ratio, basis = float(ratio), float(basis)
        # The ceiling was a bare `and` in the tier's own condition, so blowing it
        # dropped straight through to the county anchor with NOTHING written
        # down — no note, no flag, no trace that a tier had been refused. Say it.
        if ratio * basis > MAX_PROXY_ARV:
            _refuse(refused, ARV_FLAG_TIER_CEILING, round(ratio * basis, -2))
            notes.append(
                f"Land sale-to-assessed ARV (${ratio * basis:,.0f}) exceeds the "
                f"${MAX_PROXY_ARV:,.0f} plausibility ceiling — the assessed basis "
                f"(${basis:,.0f}) is likely a judgment or portfolio figure, so this "
                f"tier was refused and a later one carried the lead."
            )
        else:
            low = round((ratio_c.get("p25_ratio") or ratio * 0.9) * basis, -2)
            high = round((ratio_c.get("p75_ratio") or ratio * 1.1) * basis, -2)
            expected = min(max(round(ratio * basis, -2), low), high)
            notes.append(
                f"Land ARV from {ratio_c['count']} RECORDED nearby sales priced against county "
                f"assessed value ({ratio:.2f}× median sale-to-assessed × ${basis:,.0f})"
            )
            return expected, low, high, ("MEDIUM" if ratio_c.get("confidence") == "MEDIUM" else "LOW"), notes

    # Tier 2: county 100%-basis value × 1.10 (land is assessed closer to market
    # than improved property). `market_value` was missing from this chain, so a
    # land lead whose county DOES publish a full-market appraisal but no
    # tax_value fell all the way through to a bid proxy — or to no ARV at all
    # once the acreage band above starts rejecting mismatched comps. Never
    # `assessed_value`: in SC that is a 4%/6% statutory ratio number.
    #
    # GATED (see LAND_ANCHOR_PPA_TOL / LAND_SALE_PPA_CEILING). This tier is the
    # only place in the land path that can INVENT a large number out of nothing,
    # and tightening the comp band above pushed 1,624 leads into it. On 144 of
    # them the ARV came out HIGHER than the mismatched comps it replaced, 104
    # with no flag — the same "trailer worth $700k" failure, re-created by its
    # own fix. So the anchor now has to be readable as a value for THIS dirt
    # before it may become the headline number.
    anchor_val, anchor_lbl = _anchor_value(li)
    if anchor_val:
        supported, why = (
            _land_anchor_supported(subj_ac, anchor_val, priced) if subj_ac
            else (True, "")     # no acreage: nothing to test $/acre against
        )
        if not supported:
            notes.append(
                f"County value (${anchor_val:,.0f}) {LAND_ANCHOR_REFUSED_MARKER} for "
                f"this parcel: {why}. That record is describing improvements, or a "
                f"different parcel — either way it is not an after-repair value for "
                f"{subj_ac:.2f} acres, so no ARV is published from it."
            )
        else:
            expected = round(anchor_val * 1.10, -2)
            if expected <= MAX_PROXY_ARV:
                notes.append(
                    f"Land ARV from {anchor_lbl} × 1.10 (${anchor_val:,.0f}) — "
                    f"{COUNTY_ANCHOR_MARKER}, so it cannot be cross-checked against it"
                )
                return expected, round(expected * 0.85, -2), round(expected * 1.15, -2), "LOW", notes
            # Same silent drop-through as tier 1b above: the ceiling was an `if`
            # with no `else`, so a county figure north of $1.8M on a bare lot
            # took the lead to the bid proxy with nothing recorded.
            _refuse(refused, ARV_FLAG_TIER_CEILING, expected)
            notes.append(
                f"Land ARV from {anchor_lbl} × 1.10 (${expected:,.0f}) exceeds the "
                f"${MAX_PROXY_ARV:,.0f} plausibility ceiling — a county figure that "
                f"large on this parcel is a judgment or a mis-joined record, so this "
                f"tier was refused."
            )

    # Tier 3: bid × 1.5 (land foreclosures discount less than improved)
    if li.opening_bid and li.opening_bid > 0:
        expected = round(float(li.opening_bid) * 1.5, -2)
        # Reject runaway proxies: opening_bid on a comps-empty land row may be a
        # judgment/debt figure, not a property bid — don't emit a phantom ARV.
        if expected <= MAX_PROXY_ARV:
            # "Land ARV proxy from bid" — the leading word defeated the client's
            # /^ARV proxy from bid/i classifier, so 815 of the 949 bid-proxy
            # leads rendered with no proxy caption at all while the 134 improved
            # ones did. Same marker, same read-back, sentence re-ordered so both
            # tiers start with the same six words.
            notes.append(
                f"ARV {BID_PROXY_MARKER} × 1.5 ({li.opening_bid:,.0f} × 1.5 — land)"
            )
            return expected, round(expected * 0.7, -2), round(expected * 1.3, -2), "LOW", notes
        # The last tier. Nothing survives, so this is a WITHHELD ARV, not a
        # refused tier — and it used to end at the "Insufficient land data"
        # sentence below, which tells the reader we found nothing when in fact we
        # found an opening figure and judged it not to be a property bid.
        _refuse(refused, ARV_FLAG_PROXY_CEILING, expected)
        # WORDED TO AVOID `BID_PROXY_MARKER`. compute() raises `bid_proxy_arv`
        # by substring-matching that marker across the tier notes, and this note
        # says the ×1.5 land proxy was REFUSED — no ARV came from the bid, so
        # letting the phrase leak in here would flag 40 leads as "the ARV is the
        # opening bid × 1.5" on rows that publish no ARV at all.
        return None, None, None, "LOW", notes + [
            f"ARV WITHHELD: the ×1.5 land estimate on this opening figure "
            f"(${expected:,.0f}) exceeds the ${MAX_PROXY_ARV:,.0f} plausibility "
            f"ceiling — an opening figure this large on a bare parcel is a judgment "
            f"or total-debt number, not a property bid."
        ]

    # Carry the accumulated notes through — this used to return a bare
    # ["Insufficient land data for ARV"], silently discarding the explanation of
    # WHY the comps were unusable. On a lead whose land comps were rejected for
    # size mismatch, the reader was told only "insufficient data", which reads as
    # "we found nothing" rather than "we found comps and refused them".
    return None, None, None, "LOW", notes + ["Insufficient land data for ARV"]


def _arv_signals(li: Listing, refused: list | None = None
                 ) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Return (low, expected, high, confidence, notes) for ARV.

    Best signal: 3 zip-matched comps × subject sqft (TRUE comp-based ARV).
    Next:        Zillow zestimate (per-address Zestimate).
    Fallback:    tax_value × 1.25 (assessed values lag market).
    Worst:       opening_bid × 2.4 (foreclosures often run ~40% of ARV at the floor).

    Range = expected ± 15%. Land takes a separate $/acre path (_land_arv).

    `refused` is the optional refusal sink — see `_refuse`. Callers that pass one
    get every MAX_PROXY_ARV verdict back as a (flag, refused_value) pair;
    callers that do not are completely unaffected.
    """
    # 2026-06-19: a listing with living_sqft is an IMPROVED property even if
    # mis-classified as LAND — never value a house off $/acre land comps (that
    # produced nonsense like a 1,808-sqft house at $12,500). Route it to the
    # sqft-comp path below; if no sqft comps exist it returns ARV-unavailable
    # (honest) rather than a fabricated land value.
    if li.property_kind == PropertyKind.LAND and not (li.living_sqft and li.living_sqft > 0):
        return _land_arv(li, refused)

    notes: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    comps = raw.get("comps") or []
    comp_ppsf = raw.get("comp_median_ppsf")

    # Tier 0: RECORDED arms-length sales comps (county GIS, distance-matched).
    # Real recorded transactions beat scraped listings — no list-vs-sold gap,
    # tighter geography. This is the comp-accuracy fix (enrichment_recorded_comps).
    # An ESTIMATED sqft (footprint × stories) is not bankable as TRUE GLA, so any
    # ARV built on it is capped to MEDIUM and labelled, never HIGH (Pass: footprint
    # sqft proxy). enrichment_footprint_sqft sets this flag.
    sqft_est = bool(getattr(li, "living_sqft_estimated", False))
    sqft_lbl = f"{li.living_sqft:,.0f} sqft{' (ESTIMATED: footprint×stories ~2019)' if sqft_est else ''}" if li.living_sqft else ""

    # Plausibility guard: an implausible living_sqft (parse error, lot dimension,
    # zero) is treated as missing FOR ARV — skip the $/sqft paths rather than emit
    # a nonsense headline ARV. A footprint-estimated sqft is allowed but grades
    # down (LOW for scraped comps, capped MEDIUM for recorded comps).
    arv_sqft = _plausible_living_sqft(li)

    rec = raw.get("recorded_comps") or {}
    rec_ppsf = raw.get("comp_median_ppsf_recorded")
    if rec_ppsf and arv_sqft:
        expected = float(rec_ppsf) * arv_sqft
        notes.append(
            f"ARV from {rec.get('count', '?')} RECORDED arms-length sales within "
            f"{rec.get('radius_mi', '?')}mi (${rec_ppsf:,.0f}/sqft × {sqft_lbl})"
        )
        low = round((rec.get("p25_ppsf") or rec_ppsf * 0.9) * arv_sqft, -2)
        high = round((rec.get("p75_ppsf") or rec_ppsf * 1.1) * arv_sqft, -2)
        conf = "HIGH" if rec.get("confidence") == "HIGH" else "MEDIUM"
        if sqft_est:
            conf = "MEDIUM"
            notes.append("ARV confidence capped at MEDIUM: living sqft is a footprint-based ESTIMATE")
        return round(expected, -2), low, high, conf, notes

    # Tier 1: comp-based ARV (HIGHEST confidence)
    if comps and comp_ppsf and arv_sqft:
        # Build the adjusted $/sqft series ONCE and derive both `expected` (median)
        # and low/high (min/max) from it, so the headline ARV can never fall
        # outside its own band (Pass-2 fix: expected used the comp_median_ppsf
        # scalar while the band used this adjusted series — a different base).
        ppsfs = sorted((c.get("adjusted_ppsf") or c["price_per_sqft"])
                       for c in comps if (c.get("adjusted_ppsf") or c.get("price_per_sqft")))
        if ppsfs:
            median_ppsf = ppsfs[len(ppsfs) // 2]
        else:
            # No usable per-comp $/sqft — fall back to the supplied median scalar.
            median_ppsf = float(comp_ppsf)
        expected = median_ppsf * arv_sqft
        notes.append(
            f"ARV from {len(comps)} zip-matched sold comps × subject sqft "
            f"(${median_ppsf:,.0f}/sqft × {sqft_lbl})"
        )
        if len(ppsfs) >= 3:
            low = round(ppsfs[0] * arv_sqft, -2)
            high = round(ppsfs[-1] * arv_sqft, -2)
        else:
            low = round(expected * 0.90, -2)
            high = round(expected * 1.10, -2)
        # Clamp the rounded headline into [low,high] so it always sits inside its
        # own band even if rounding or a fallback base nudges it out.
        expected = min(max(round(expected, -2), low), high)
        # Comp-QUALITY gate: scraped comps are only HIGH-confidence when there
        # are enough of them, they're geographically anchored (not county-wide),
        # and they actually agree. A single far/stale comp is not bankable.
        conf = "HIGH"
        reasons = []
        # A footprint-estimated sqft CAPS ARV at MEDIUM (never HIGH) — a bounded
        # estimate, not bankable GLA. The >8000 footprint reject + plausibility
        # band already drop garbage, so MEDIUM (not LOW) is the right confidence.
        if sqft_est:
            conf, reasons = "MEDIUM", reasons + ["living sqft is a footprint-based ESTIMATE"]
        if len(ppsfs) < 3:
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + [f"only {len(ppsfs)} comp(s)"]
        if comps and not comps[0].get("geo_anchored", True):
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + ["county-wide comps (no local anchor)"]
        if len(ppsfs) >= 2 and ppsfs[0] > 0 and ppsfs[-1] / ppsfs[0] >= 1.6:
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + ["comps disagree (wide $/sqft spread)"]
        if reasons:
            notes.append(f"ARV confidence lowered to {conf}: " + "; ".join(reasons))
        return round(expected, -2), low, high, conf, notes

    # Tier 1b: RECORDED sale-to-assessment RATIO comps (enrichment_recorded_sales).
    # Buncombe/Anderson publish a full sales roll but NO heated sqft anywhere in
    # their public GIS, so no $/sqft tier can ever fire there. What they do give
    # is the ratio real nearby recorded sales fetched against the county's own
    # assessed value — the standard assessment-sales ratio. Applied to the
    # subject's assessed value on the SAME basis (the enricher supplies it; the
    # board's li.tax_value is a different, often land-only figure) it is a real
    # market-grounded ARV. It is a proxy, not a like-for-like comp, so it sits
    # BELOW both $/sqft tiers and is never graded HIGH.
    ratio_c = raw.get("recorded_ratio_comps") or {}
    ratio = ratio_c.get("median_ratio")
    basis = ratio_c.get("assessed_basis")
    if ratio and basis and float(basis) > 0 and int(ratio_c.get("count") or 0) >= 3:
        ratio, basis = float(ratio), float(basis)
        expected = ratio * basis
        # Same plausibility ceiling the other proxy tiers use: an "assessed
        # value" north of $2M on a distressed residential lead is nearly always a
        # judgment/portfolio figure that leaked into the field, and multiplying
        # it by a ratio would launder that into a confident phantom ARV.
        if expected > MAX_PROXY_ARV:
            # A REFUSED TIER, not a withheld ARV: the zestimate / tax tiers below
            # still get their turn. Weak flag, so the reader is told which
            # evidence was thrown away without the money coming off a number
            # this refusal says nothing about.
            _refuse(refused, ARV_FLAG_TIER_CEILING, round(expected, -2))
            notes.append(
                f"Sale-to-assessed ARV (${expected:,.0f}) exceeds the "
                f"${MAX_PROXY_ARV:,.0f} plausibility ceiling — assessed basis "
                f"(${basis:,.0f}) is likely a judgment/aggregate figure; skipped."
            )
        else:
            low = round((ratio_c.get("p25_ratio") or ratio * 0.9) * basis, -2)
            high = round((ratio_c.get("p75_ratio") or ratio * 1.1) * basis, -2)
            expected = min(max(round(expected, -2), low), high)
            notes.append(
                f"ARV from {ratio_c['count']} RECORDED nearby sales priced against county "
                f"assessed value within {ratio_c.get('radius_mi', '?')}mi "
                f"({ratio:.2f}× median sale-to-assessed × ${basis:,.0f} county value)"
            )
            conf = "MEDIUM" if ratio_c.get("confidence") == "MEDIUM" else "LOW"
            if conf == "LOW":
                notes.append("ARV confidence LOW: thin or widely-spread sale-to-assessed ratio")
            return expected, low, high, conf, notes

    # Tier 2: Zillow zestimate
    z = raw.get("zillow", {}) if isinstance(raw, dict) else {}
    _zest_real = z.get("zestimate")
    zest = _zest_real or li.market_value
    _fh = (raw.get("fhfa_value") or {}) if isinstance(raw, dict) else {}
    if zest and zest > 0:
        expected = float(zest)
        if _zest_real:
            notes.append(f"ARV from Zillow Zestimate ({zest:,.0f})")
        else:
            # No Zestimate — this is li.market_value wearing the Zestimate's
            # label, which is both a mis-statement to the reader and the reason
            # the anchor cross-check below was reading 1.00 and calling it a
            # pass. Say what it is, and mark it as not independent of the anchor.
            notes.append(
                f"ARV from county market value ({zest:,.0f}) — {COUNTY_ANCHOR_MARKER}, "
                f"so it cannot be cross-checked against it"
            )
        confidence = "MEDIUM"
    elif _fh.get("est_value") and float(_fh["est_value"]) > 0:
        # Free FHFA-HPI rescale of the property's last recorded sale to today's
        # market (MSA, else statewide). Coarse trend estimate (not comp-grounded)
        # so it ranks below zestimate/tax and is LOW confidence — but it gives the
        # equity engine an ARV basis for comp-thin rural/SC leads that had none.
        expected = float(_fh["est_value"])
        notes.append(f"ARV from FHFA-HPI rescale of last recorded sale "
                     f"({_fh.get('msa_or_state', 'MSA/state')}) — coarse fallback")
        confidence = "LOW"
    elif li.tax_value and li.tax_value > 0:
        expected = float(li.tax_value) * 1.25
        notes.append(
            f"ARV from tax-assessed × 1.25 ({li.tax_value:,.0f} × 1.25) — "
            f"{COUNTY_ANCHOR_MARKER}, so it cannot be cross-checked against it"
        )
        # 2026-06-21: MEDIUM, not LOW. A county tax-assessed / appraised value
        # is an official, authoritative valuation (just conservative/stale),
        # not a guess like opening_bid × 2.4. Treating it as MEDIUM lets the
        # grade engine actually rate the listing instead of withholding; the
        # anomaly guard in grading.py still backstops implausible ARVs.
        confidence = "MEDIUM"
    elif li.opening_bid and li.opening_bid > 0:
        expected = float(li.opening_bid) * 2.4
        # Reject runaway proxies: on a comps-empty row opening_bid is often a
        # money judgment / total debt, not a property bid. Above the ceiling
        # the ×2.4 proxy emits a phantom multi-million ARV — return unavailable.
        if expected > MAX_PROXY_ARV:
            # Prefixed "ARV WITHHELD:" so it joins the family docs/dashboard.js's
            # _ARV_ABSENT_NOTE already recognises — the old wording started with
            # "Opening bid (…)" and matched none of that regex's alternatives, so
            # the one sentence explaining the blank cell was never shown.
            _refuse(refused, ARV_FLAG_PROXY_CEILING, round(expected, -2))
            return None, None, None, "LOW", [
                f"ARV WITHHELD: opening bid (${li.opening_bid:,.0f}) is too large for a "
                f"×2.4 ARV proxy (${expected:,.0f} > ${MAX_PROXY_ARV:,.0f}) — likely a "
                f"judgment/debt figure, not a property bid."
            ]
        notes.append(f"ARV {BID_PROXY_MARKER} × 2.4 ({li.opening_bid:,.0f} × 2.4) — rough")
        confidence = "LOW"
    else:
        return None, None, None, "LOW", notes + ["Insufficient data for ARV"]

    # Final backstop: the tax×1.25 path can also overshoot on a stale/wrong
    # assessment. Any proxy ARV above the ceiling is not trustworthy.
    #
    # THIS IS THE PATH THAT LEAKED. 79 leads reach it, and every one of them used
    # to leave with an empty `arv_flags` and a null `arv_withheld` — a refusal
    # indistinguishable, to every reader downstream, from a lead that was simply
    # never priced. See ARV_FLAG_PROXY_CEILING at the top of this file.
    if expected > MAX_PROXY_ARV:
        _refuse(refused, ARV_FLAG_PROXY_CEILING, round(expected, -2))
        return None, None, None, "LOW", [
            f"Proxy ARV (${expected:,.0f}) exceeds the ${MAX_PROXY_ARV:,.0f} "
            f"plausibility ceiling — input likely a judgment/debt figure; ARV withheld."
        ]

    low = round(expected * 0.85, -2)
    high = round(expected * 1.15, -2)
    return round(expected, -2), low, high, confidence, notes


def _arv_sanity(li: Listing, out: "Calc", arv_conf: str, arv_flags: list[str],
                anchor: float | None, anchor_label: str | None,
                anchor_is_weak_evidence: bool = False) -> str:
    """Final gate: refuse to publish an ARV the evidence does not support.

    Runs once, at the end of the ARV pipeline, so it sees the number that would
    actually ship — every tier, the calibration, the vision adjustment and the
    floor have all already had their say.

    Two severities:

      HARD  → the ARV is withheld entirely (moved to `arv_withheld`), which also
              zeroes max_bid_70 / ROI / profit / deal_status downstream, because
              every one of those is computed `if out.arv_expected`. A blank bid
              beside "ARV unverified — comps imply $1,734/sqft in a $83/sqft
              county" is an actionable lead. A confident $401,400 max bid on the
              same row is a loss at an auction with someone's own money.

      SOFT  → the number is kept but confidence drops to LOW and the reason is
              named, because the alternative (silence) would delete real leads.

    Deliberately does NOT fire on the ordinary case. Measured on the live board,
    the hard guards touch ~2% of ARV-bearing rows; the comp math itself is
    producing defensible numbers for the rest and the board's usefulness depends
    on them.

    `anchor_is_weak_evidence` demotes the anchor HARD withhold to the SOFT flag
    without touching the disclosure. compute() passes it when the published ARV
    IS the seller's asking price (see SELLER_ASK_SOURCES). Deleting a price
    somebody is publicly asking because a county record sits far below it gets
    the evidence backwards: on the land portals that record is routinely a
    present-use / forestry deferment value, legally 5-20% of market, so a 20x
    gap is the EXPECTED relationship and not proof the ask is wrong. Measured
    without this, [33422] 3465 Yancey Road (asking $6,290,000) and [33348] 149
    April Valley Lane (asking $3,199,000) went from a nonsense $20,900 / $88,900
    ARV straight to a blank row — trading one wrong answer for no answer, when
    the honest output is the ask, loudly flagged, with no money built on it.
    The SOFT branch still fires, so these keep `arv_above_anchor` (CONTRADICTED:
    no max bid, no ROI, no verdict, no equity) and the reader sees both numbers.
    """
    if not out.arv_expected:
        if arv_flags:
            out.arv_flags = sorted(set(arv_flags))
        return arv_conf

    raw = li.raw if isinstance(li.raw, dict) else {}
    manufactured = _is_manufactured(li)
    is_land = li.property_kind == PropertyKind.LAND and not (li.living_sqft and li.living_sqft > 0)
    hard: list[str] = []

    # --- HARD 1: $/sqft ceiling ---------------------------------------------
    # The $/sqft path had no ceiling at all, while the two RECORDED-comp
    # producers (enrichment_recorded_comps / enrichment_assessor_comps) have
    # bounded themselves at $20-$800/sqft since they were written. Skipped when
    # the parcel carries real acreage — then most of the value is dirt and $/sqft
    # is not measuring the dwelling.
    acres = _acreage_for(li)
    sqft = _plausible_living_sqft(li)
    if sqft and (acres is None or acres <= PPSF_CEILING_MAX_ACRES):
        ceiling = _arv_ppsf_ceiling(li, manufactured)
        implied = out.arv_expected / sqft
        if implied > ceiling:
            hard.append("ppsf_ceiling")
            out.notes.append(
                f"ARV WITHHELD: ${out.arv_expected:,.0f} on {sqft:,.0f} sqft implies "
                f"${implied:,.0f}/sqft in {li.county or 'this'} County"
                + (" (manufactured housing)" if manufactured else "")
                + f" — above the ${ceiling:,.0f}/sqft ceiling this market supports. "
                f"The comps or the square footage are wrong."
            )

    # --- HARD 2: ARV vs the county's own 100%-basis appraisal ---------------
    soft_mult = ARV_ANCHOR_SOFT_MULT_LAND if is_land else ARV_ANCHOR_SOFT_MULT_IMPROVED
    hard_mult = ARV_ANCHOR_HARD_MULT_LAND if is_land else ARV_ANCHOR_HARD_MULT_IMPROVED
    if anchor and out.arv_vs_assessed:
        ratio = out.arv_vs_assessed
        # THE HARD TEST IS MEASURED AGAINST THE LARGEST COUNTY FIGURE, not the
        # first one. `anchor` is `_cross_check_anchor`'s pick — market_value,
        # else the assessor's appraisal, else tax_value — and 1,282 board leads
        # carry two of those disagreeing by >= 3x. Withholding an ARV is this
        # file's strongest claim ("no county record can support this number"),
        # so it has to be true of every county record; measured, 27 leads were
        # deleted against the first figure and would have survived against the
        # largest, at a cost of $12,980,900 of published ARV, purely because of
        # which scraper happened to fill which field. See
        # COUNTY_VALUE_DISAGREE_MULT. The SOFT test below deliberately keeps
        # using the primary anchor and its published `arv_vs_assessed`, so those
        # 27 land on `arv_above_anchor` — still CONTRADICTED, still no money on
        # them, but the number and the disagreement are both on screen instead
        # of a blank row that explains nothing.
        _cvals = [v for v, _ in _county_values(li)]
        hard_anchor = max(_cvals) if _cvals else anchor
        hard_ratio = out.arv_expected / hard_anchor if hard_anchor else ratio
        if hard_ratio > hard_mult and not anchor_is_weak_evidence:
            hard.append("arv_above_anchor_extreme")
            out.notes.append(
                f"ARV WITHHELD: ${out.arv_expected:,.0f} is {hard_ratio:.0f}× the highest "
                f"county valuation on this parcel (${hard_anchor:,.0f}) — past the "
                f"{hard_mult:.0f}× limit for "
                f"{'land' if is_land else 'improved property'}. After-repair value runs above "
                f"a county appraisal, but not by this much; one of the two records is "
                f"describing a different parcel."
            )
        elif ratio > soft_mult:
            arv_flags.append("arv_above_anchor")
            arv_conf = "LOW"
            out.notes.append(
                f"ARV (${out.arv_expected:,.0f}) is {ratio:.1f}× the {anchor_label} "
                f"(${anchor:,.0f}) — high but not impossible for distressed inventory; "
                f"confidence LOW, verify the parcel before bidding."
            )

    # --- SOFT: manufactured home valued off site-built comps ----------------
    # 430 board leads that are manufactured housing were priced off comps of a
    # different kind (230 pure site-built SFR, 171 land). _classify_kind never
    # read `land_use`, so the subject looked "unknown" and _filter_by_kind
    # coerces unknown to "sfr". Fixed at source in enrichment_comps; flagged here
    # so the ALREADY-PUBLISHED board says so too.
    comps = raw.get("comps") or []
    comp_kinds = {str(c.get("kind")) for c in comps if isinstance(c, dict) and c.get("kind")}
    if manufactured and comp_kinds and "manufactured" not in comp_kinds:
        arv_flags.append("comp_kind_mismatch")
        arv_conf = "LOW"
        out.notes.append(
            f"This is manufactured housing (county class: "
            f"{li.land_use or (raw.get('cama') or {}).get('building_type') or 'mobile home'}) "
            f"but the comps used are {', '.join(sorted(comp_kinds))} — a manufactured home "
            f"does not sell at site-built $/sqft. Confidence LOW."
        )

    # --- SOFT: ARV built on a shared/imprecise coordinate --------------------
    # enrichment_board_quality already labels leads whose lat/lng is a shared
    # city-centroid rather than a real situs (`geo_imprecise`). Nothing in the
    # valuation path read it, yet the comp selector's geographic gate keys on
    # exactly that coordinate — so hundreds of leads share one parcel's comps.
    if raw.get("geo_imprecise") and comps and any(
            isinstance(c, dict) and c.get("geo_anchored") for c in comps):
        arv_flags.append("geo_imprecise_comps")
        if arv_conf == "HIGH":
            arv_conf = "MEDIUM"
        out.notes.append(
            "Comps were selected from an IMPRECISE coordinate "
            f"({raw.get('geo_imprecise')}) — this lead's lat/lng is a shared centroid, "
            "not its own situs, so neighbouring leads may carry identical comps."
        )

    # --- SOFT: the seller is publicly asking LESS than we say it is worth ----
    # The mirror image of the "high-discount signal" branch in compute(), and the
    # reason it cannot live there: that branch runs before the ARV floor, so on a
    # floored lead it would be measuring a number that gets overwritten seconds
    # later. This runs last and sees what ships. Restricted to SELLER_ASK_SOURCES
    # — on an auction row a 7x gap between the opening bid and the ARV is the
    # entire flip thesis and flagging it would gut the board. On a retail land
    # listing there is no thesis: the parcel is on the open market at that price.
    if (li.source in SELLER_ASK_SOURCES and li.opening_bid
            and float(li.opening_bid) > 0
            and out.arv_expected > ARV_VS_ASK_MAX * float(li.opening_bid)):
        arv_flags.append(ARV_FLAG_ABOVE_ASK)
        arv_conf = "LOW"
        out.notes.append(
            f"ARV (${out.arv_expected:,.0f}) is "
            f"{out.arv_expected / float(li.opening_bid):.1f}× the price the seller is "
            f"publicly asking (${float(li.opening_bid):,.0f}) on a retail listing. This "
            f"is not a foreclosure discount — anyone may buy this parcel at the asking "
            f"price today, so an after-repair value this far above it says the comps, "
            f"not the seller, are wrong. No max bid or verdict is published from it."
        )

    # --- SOFT: a LAND parcel carrying a dwelling's square footage ------------
    # See ARV_FLAG_LAND_SQFT. `_arv_signals` reads the sqft as authoritative and
    # routes these to the $/sqft path; that is one of two readings and the record
    # does not say which is right. Flagged here rather than resolved.
    if li.property_kind == PropertyKind.LAND and sqft:
        arv_flags.append(ARV_FLAG_LAND_SQFT)
        arv_conf = "LOW"
        out.notes.append(
            f"The county classes this parcel as LAND, but the record also carries "
            f"{sqft:,.0f} sqft of living area — and this ARV was priced as a building "
            f"off that figure. Both cannot describe the same parcel: either the class "
            f"is stale or the square footage came off a different record. Verify before "
            f"bidding; no max bid or verdict is published from it."
        )

    # --- SOFT: the county disagrees with ITSELF ------------------------------
    # See COUNTY_VALUE_DISAGREE_MULT. Weak, not contradicted — it does not
    # dispute the ARV, it says the record the ARV was measured against is one of
    # two that cannot both be this parcel.
    _cv = _county_values(li)
    _worst = None
    for _ai in range(len(_cv)):
        for _bi in range(_ai + 1, len(_cv)):
            (_av, _al), (_bv, _bl) = _cv[_ai], _cv[_bi]
            if _av <= 0 or _bv <= 0:
                continue
            _r = max(_av, _bv) / min(_av, _bv)
            # The tax roll is only comparable to a full-market appraisal at the
            # far end of its own spread — see COUNTY_VALUE_DISAGREE_MULT_TAX.
            _tax_pair = "tax-assessed" in (_al + _bl) and "appraised" not in (_al + _bl)
            _limit = (COUNTY_VALUE_DISAGREE_MULT_TAX if _tax_pair
                      else COUNTY_VALUE_DISAGREE_MULT)
            if _r >= _limit and (_worst is None or _r > _worst[0]):
                _worst = (_r, _al, _av, _bl, _bv)
    if _worst:
        arv_flags.append(ARV_FLAG_COUNTY_DISAGREE)
        out.notes.append(
            f"The county's own records disagree about this parcel: {_worst[1]} "
            f"${_worst[2]:,.0f} against {_worst[3]} ${_worst[4]:,.0f} — a "
            f"{_worst[0]:.1f}× spread. Whichever is right, the other is describing "
            f"something else, and the cross-check above could only be run against one "
            f"of them."
        )

    if hard:
        out.arv_withheld = out.arv_expected
        out.arv_expected = out.arv_low = out.arv_high = None
        out.arv_vs_assessed = None
        arv_flags.extend(hard)
        arv_conf = "LOW"

    if arv_flags:
        out.arv_flags = sorted(set(arv_flags))
    return arv_conf


def compute(li: Listing) -> Calc:
    """Compute investor financials for a listing. Mutates nothing."""
    out = Calc(notes=[])

    # ---- ARV range ------------------------------------------------------
    # `_refusals` collects every MAX_PROXY_ARV verdict the tiers reached as
    # (flag, refused_value). Before this existed those refusals lived only in
    # prose and `grading.arv_trust` scored them "ok" — see the block at
    # ARV_FLAG_PROXY_CEILING for what that cost.
    _refusals: list[tuple[str, float | None]] = []
    expected, low, high, arv_conf, arv_notes = _arv_signals(li, _refusals)
    # Per-county calibration — the single chokepoint every ARV tier flows
    # through (each _arv_signals tier returns its own band, so apply here, not
    # inside). Inert (factor 1.0) for any county without a calibration entry.
    if expected is not None:
        _cf = _arv_calibration_factor(li)
        if _cf != 1.0:
            expected = round(expected * _cf, -2)
            low = round(low * _cf, -2) if low is not None else low
            high = round(high * _cf, -2) if high is not None else high
            arv_notes = list(arv_notes) + [
                f"County calibration ×{_cf:.2f} (corrects measured {li.county} ARV bias)"
            ]
    out.arv_low, out.arv_expected, out.arv_high = low, expected, high
    out.notes.extend(arv_notes)

    # ---- Vision-based ARV adjustment ------------------------------------
    # Subject's photo-derived condition tier is what the rehab will need to
    # *overcome*. Comps are average retail-sold properties — typically already
    # at "cosmetic-or-better" finish. If subject is gut/major, even after
    # full rehab the result is "renovated SFR" not "premium tear-out-and-
    # rebuild," so it sells at average comp pricing, not above. If subject
    # is move_in_ready, post-rehab is barely-touched-premium and tends to
    # sell *above* comp median.
    raw = li.raw if isinstance(li.raw, dict) else {}
    vision_tier = raw.get("condition_tier")
    vision_conf = (raw.get("condition_source") or "").lower()
    if (out.arv_expected and vision_tier
            and vision_conf.startswith("vision-")
            and arv_conf == "HIGH"):
        # Multipliers calibrated to flipper-Carolina market behavior.
        # Only apply when ARV is comp-grounded (HIGH confidence) AND vision
        # confidence is HIGH/MEDIUM. We don't want to compound noise.
        adj_map = {
            "move_in_ready": 1.05,   # post-rehab premium
            "cosmetic":      1.00,   # neutral, matches comp median
            "major":         0.95,   # slight haircut, full rehab won't equal premium
            "gut":           0.88,   # bigger haircut, structural risks remain
        }
        adj = adj_map.get(vision_tier)
        if adj and adj != 1.0:
            old_expected = out.arv_expected
            out.arv_expected = round(out.arv_expected * adj, -2)
            out.arv_low = round((out.arv_low or 0) * adj, -2) or None
            out.arv_high = round((out.arv_high or 0) * adj, -2) or None
            pct = (adj - 1.0) * 100
            out.notes.append(
                f"Vision-adjusted ARV by {pct:+.0f}% (subject tier='{vision_tier}', "
                f"comp median assumes cosmetic-tier finish): "
                f"${old_expected:,.0f} → ${out.arv_expected:,.0f}"
            )

    # ---- ARV sanity check vs listing price ------------------------------
    # Two failure modes the guard exists to catch:
    #
    #  (a) ratio < 0.6  → comp-implied ARV is *less* than the asking price.
    #      Almost always a bad-comp problem (wrong zip cluster, wrong
    #      property type, bid is the actual market). Anchor to listing.
    #
    #  (b) ratio > 1.6  → comp-implied ARV is way more than the asking
    #      price. For distressed/foreclosure inventory this is exactly
    #      the flip thesis we WANT to see. We do NOT anchor in this
    #      direction — that would silently kill every real deal.
    #
    # Therefore the guard only fires on (a), and only for retail-priced
    # sources where the listing is genuinely an asking price (HomeHarvest
    # active for-sale, Realtor foreclosure REO list price, and — new — the two
    # LAND portals, see SELLER_ASK_SOURCES).
    #
    # (b) IS NO LONGER UNIVERSALLY SILENT. It stays a note on the auction-shaped
    # retail sources, and on a SELLER_ASK source it also raises
    # ARV_FLAG_ABOVE_ASK in `_arv_sanity` — which runs last, on the post-floor
    # number, so it cannot be fooled the way a test here would be.
    _arv_from_listing = False
    if (out.arv_expected and li.opening_bid and li.opening_bid > 0
            and li.source in RETAIL_PRICE_SOURCES):
        ratio = out.arv_expected / li.opening_bid
        if ratio < 0.6:
            out.notes.append(
                f"ARV (${out.arv_expected:,.0f}) was {ratio:.1f}× listing price "
                f"(${li.opening_bid:,.0f}) — comps appear too low; anchoring ARV "
                f"to listing price as a floor."
                + (f" On {li.source} the listing price is the OWNER'S ASK, which "
                   f"outranks a present-use / deferred-value county assessment "
                   f"(NC G.S. 105-277.2 values run 5-20% of market)."
                   if li.source in SELLER_ASK_SOURCES else "")
            )
            out.arv_expected = float(li.opening_bid)
            out.arv_low = round(li.opening_bid * 0.90, -2)
            out.arv_high = round(li.opening_bid * 1.10, -2)
            arv_conf = "MEDIUM"
            # The ARV is now the LISTING price, not the county's figure — so the
            # tier note saying it came from the county is stale, and letting it
            # raise `anchor_not_independent` below would caption the lead with a
            # sentence that is no longer true ("this ARV was computed FROM the
            # county market value"). The cross-check against the county figure is
            # genuinely independent again; that is the point of re-anchoring.
            _arv_from_listing = True
        elif ratio > 1.6:
            # Don't rewrite ARV — but record the wide gap so the dashboard /
            # investor can see it's a high-discount listing (potential flip).
            out.notes.append(
                f"Listing price (${li.opening_bid:,.0f}) is {1/ratio*100:.0f}% of "
                f"comp-grounded ARV (${out.arv_expected:,.0f}) — high-discount "
                f"signal; preserved for investor review."
            )

    # ---- ARV FLOOR at county market value / recent recorded sale --------
    # A comp-grounded ARV BELOW what the county appraises the home at (or below a
    # recent arms-length sale) is almost always a thin/weak-comp artifact — the
    # home's own market appraisal and last sale are stronger signals than 3 stray
    # comps. After-repair value should never sit under the as-is county value.
    # So when comps are NOT high-confidence, FLOOR (raise) the ARV to it.
    #
    # BUT THE FLOOR IS THE ONLY CODE PATH THAT RAISES AN ARV, AND IT WAS THE ONLY
    # ONE WITH NO CEILING. It fired on 7,118 board rows and is the direct cause of
    # the user-reported "$780,300 trailer": a general-warehouse CAMA row joined
    # onto a 1,400-sqft manufactured home, adopted verbatim over a defensible
    # $121,100 comp ARV. Three preconditions now gate it — each measured, each
    # documented at its constant above. When a floor source is rejected we KEEP the
    # comp-grounded number rather than withhold, because on every case inspected
    # the comps were the trustworthy half of the disagreement.
    arv_flags: list[str] = []
    _tier_notes = arv_notes or []
    if any(BID_PROXY_MARKER in n for n in _tier_notes):
        arv_flags.append("bid_proxy_arv")
    # The land path can only report through notes (its return signature is fixed
    # by four other tests), so read its two verdicts back here.
    if any(LAND_COMPS_REJECTED_MARKER in n for n in _tier_notes):
        arv_flags.append("land_comps_rejected")
    # The two AGREEMENT verdicts (LAND_COMP_SPREAD_MAX). `land_comps_disagree`
    # means a 2-comp pool was refused for spanning >=8x and this ARV came from a
    # later tier; `land_comp_spread` means a 3+-comp median SHIPPED off a pool
    # that wide. Without these read-backs the land path can only lower a
    # confidence label, which nothing downstream gates on.
    if any(LAND_COMPS_DISAGREE_MARKER in n for n in _tier_notes):
        arv_flags.append("land_comps_disagree")
    if any(LAND_COMP_SPREAD_MARKER in n for n in _tier_notes):
        arv_flags.append("land_comp_spread")
    if any(LAND_ANCHOR_REFUSED_MARKER in n for n in _tier_notes):
        arv_flags.append("land_ppa_ceiling")
    # The MAX_PROXY_ARV refusals. These arrive through `_refusals` rather than
    # through a note marker because a marker can carry a verdict but not the
    # NUMBER that was refused, and `arv_withheld` is exactly that number.
    for _rflag, _rval in _refusals:
        arv_flags.append(_rflag)
        # Only when nothing survived — a refused TIER still leaves a published
        # ARV, and `arv_withheld` beside a live `arv_expected` would read as
        # "the engine refused the number on screen", which is the opposite of
        # what happened.
        if (_rflag == ARV_FLAG_PROXY_CEILING and _rval
                and out.arv_expected is None and out.arv_withheld is None):
            out.arv_withheld = _rval
    # An ARV that IS a county figure times a constant cannot be validated against
    # that figure — see the cross-check below.
    arv_from_anchor = (not _arv_from_listing) and any(
        COUNTY_ANCHOR_MARKER in n for n in _tier_notes)
    mv = float(li.market_value) if (li.market_value and float(li.market_value) > 10000) else None
    sale_amt = None
    _ls = (raw.get("gis") or {}).get("last_sale") if isinstance(raw, dict) else None
    if isinstance(_ls, dict) and _ls.get("amount"):
        try:
            sale_amt = float(_ls["amount"]) if float(_ls["amount"]) > 10000 else None
        except (TypeError, ValueError):
            sale_amt = None

    # REFUSING A FLOOR MUST NEVER LEAVE A LEAD MORE CONFIDENT THAN ACCEPTING IT.
    # Accepting a floor caps confidence at MEDIUM ("the comps disagreed with the
    # county, so this is not a clean comp read"). Refusing one used to cap
    # nothing, so the disagreement simply vanished and a lead that had been
    # capped at MEDIUM came out HIGH: measured, 297 leads ended MORE confident
    # than before, 83 of them MEDIUM->HIGH and 49 of those purely because a floor
    # source was refused. The disagreement is the same fact either way.
    def _refused_floor_cap(conf: str) -> str:
        return "MEDIUM" if conf == "HIGH" else conf

    # (a) CLASS CONSISTENCY — a commercial CAMA row cannot value a home or a lot.
    commercial_bt = _commercial_building_type(li)
    if commercial_bt:
        # The FLAG used to be gated on `mv is not None`, i.e. on market_value
        # existing and clearing $10,000 — but `_anchor_value` suppresses the
        # anchor for a commercial join regardless of which field carried the
        # number. Measured: 7 leads had the anchor (and therefore the
        # cross-check) removed with no flag at all to say so. Flag on the
        # CONDITION, not on which field happened to be populated.
        _xv, _xl, _ = _cross_check_anchor(li)
        if mv is not None or _xv is not None:
            arv_flags.append("cama_class_mismatch")
        if mv is not None:
            out.notes.append(
                f"County market value (${mv:,.0f}) NOT used as an ARV floor: the assessor "
                f"record joined to this lead is a '{commercial_bt}' — a commercial building, "
                f"not this {li.property_kind.value.replace('_', ' ')}. Parcel join looks wrong."
            )
            if out.arv_expected and mv > out.arv_expected:
                arv_conf = _refused_floor_cap(arv_conf)
            mv = None
        elif _xv is not None:
            out.notes.append(
                f"The assessor record joined to this lead is a '{commercial_bt}' — a "
                f"commercial building, not this "
                f"{li.property_kind.value.replace('_', ' ')} — so its ${_xv:,.0f} is "
                f"refused as an ARV floor. Parcel join looks wrong."
            )

    # (b) SALE RECENCY — an undated or decades-old deed is not today's market.
    # Only reported when rejecting the sale actually CHANGES the outcome (the
    # sale would otherwise have become the floor). Flagging every lead that
    # merely happens to carry an old deed put a scary label on 5,418 rows where
    # 3,570 of them were never going to use it anyway — noise that trains the
    # reader to ignore the flag.
    if sale_amt is not None:
        yr = _sale_year(_ls)
        age = (datetime.utcnow().year - yr) if yr else None
        if age is None or age > FLOOR_SALE_MAX_AGE_YEARS:
            would_have_floored = bool(
                out.arv_expected and sale_amt > out.arv_expected
                and (mv is None or sale_amt > mv)
            )
            if would_have_floored:
                out.notes.append(
                    f"Recorded sale (${sale_amt:,.0f}) NOT used as an ARV floor: "
                    + (f"sale is from {yr} ({age} years old)"
                       if yr else "the deed carries no usable date")
                    + f" — only sales within {FLOOR_SALE_MAX_AGE_YEARS} years describe "
                      f"today's market."
                )
                arv_flags.append("stale_sale_floor")
                arv_conf = _refused_floor_cap(arv_conf)
            sale_amt = None

    floor_val = max([v for v in (mv, sale_amt) if v], default=None)
    if out.arv_expected and floor_val and out.arv_expected < floor_val:
        old_arv = out.arv_expected
        # (c) MAGNITUDE — a floor that multiplies the comp ARV by more than
        # MAX_FLOOR_RAISE_MULT is not "comps sat a little low", it is two records
        # describing two different buildings.
        if floor_val > MAX_FLOOR_RAISE_MULT * old_arv:
            arv_flags.append("floor_rejected_extreme")
            arv_conf = "LOW"
            out.notes.append(
                f"County/sale value (${floor_val:,.0f}) is {floor_val / old_arv:.1f}× the "
                f"comp-grounded ARV (${old_arv:,.0f}) — beyond the "
                f"{MAX_FLOOR_RAISE_MULT:.1f}× floor limit, so the ARV was NOT raised to it. "
                f"The two figures likely describe different parcels; verify the parcel join."
            )
        else:
            if floor_val > FLOOR_RAISE_NOTABLE_MULT * old_arv:
                arv_flags.append("floor_raise_large")
                arv_conf = "LOW"
                out.notes.append(
                    f"ARV was raised {floor_val / old_arv:.1f}× by the county/sale floor — a "
                    f"large disagreement with the comps. The floor was honoured (the county "
                    f"appraises the actual parcel) but confidence is LOW: confirm the "
                    f"assessor record belongs to this property."
                )
            out.arv_expected = round(floor_val, -2)
            # Flooring TO the county value makes the published ARV that value —
            # so the cross-check below would be dividing the county number by
            # itself. Track it the same way the anchor-derived tiers do.
            if mv is not None and floor_val == mv:
                arv_from_anchor = True
            # Keep the band anchored to the number actually published — `min()`
            # here used to leave arv_low far under a raised expected, so the
            # headline sat outside its own range on thousands of rows.
            out.arv_low = round(max(out.arv_low or 0.0, floor_val * 0.95), -2)
            out.arv_high = round(max(out.arv_high or 0.0, floor_val * 1.10), -2)
            # A comp ARV that disagreed with the county/sale value is, by definition, not a
            # clean comp read — cap confidence at MEDIUM so a floored number reads as "verify".
            if arv_conf == "HIGH":
                arv_conf = "MEDIUM"
            out.notes.append(
                f"ARV floored to county market value/recent sale (${floor_val:,.0f}); "
                f"comp ARV (${old_arv:,.0f}) sat below the as-is value (after-repair can't be lower)."
            )

    # ---- Assessed-value anchor (comp accuracy cross-check) --------------
    # A comp-grounded ARV should exceed a distressed property's county
    # appraisal (after-repair > as-is), but an ARV that's WILDLY off the
    # assessor (>2.5x or <0.6x) almost always means bad comps (wrong submarket
    # or property type — the zip-match failure). We don't rewrite the ARV
    # (the assessor isn't ARV), but we flag it and lower confidence so a
    # bad-comp number can't masquerade as HIGH.
    #
    # RUNS AFTER THE FLOOR, deliberately. It used to run before, so on all 7,118
    # floored rows the stored `arv_vs_assessed` described a number that had since
    # been overwritten — 933 S Liberty St published `arv_vs_assessed: 4.12` on an
    # ARV that was actually 289x its anchor. A cross-check that cannot see the
    # published number is decoration.
    #
    # TWO THINGS THE CHECK COULD NOT DO, BOTH FIXED HERE.
    #
    # (1) It could not fire on an ARV that came FROM the county value. 7,000
    #     board ARVs are `anchor × 1.10`, `tax × 1.25`, market_value-as-Zestimate
    #     or the floor set to market_value — every one of them divided by the
    #     same number it was built from, producing a fixed ratio that passes by
    #     construction. That is not a check, it is arithmetic. It is now SKIPPED
    #     on those leads and the lead is MARKED `anchor_not_independent` instead:
    #     "no cross-check was possible" is a true statement, "the cross-check
    #     passed" was not. The ratio itself is still published for transparency.
    #
    # (2) It could not fire when the assessor row was commercial, because
    #     `_anchor_value` returns None there — which deleted the guardrail on
    #     exactly the leads whose parcel join is known-wrong (the 725 Bryant
    #     warehouse case). `_cross_check_anchor` reads those figures anyway and
    #     reports `trusted=False`; see its docstring.
    anchor, anchor_label, anchor_trusted = _cross_check_anchor(li)
    if out.arv_expected and anchor:
        out.arv_vs_assessed = round(out.arv_expected / anchor, 2)
        if arv_from_anchor:
            arv_flags.append("anchor_not_independent")
            out.notes.append(
                f"No independent cross-check: this ARV was computed FROM the "
                f"{anchor_label} (${anchor:,.0f}), so comparing the two only restates "
                f"the multiplier. Nothing here confirms the county's number describes "
                f"this property."
            )
        elif arv_conf == "HIGH" and (out.arv_vs_assessed > 2.5 or out.arv_vs_assessed < 0.6):
            arv_conf = "MEDIUM"
            out.notes.append(
                f"Comp ARV (${out.arv_expected:,.0f}) is {out.arv_vs_assessed:.1f}× the "
                f"county appraisal (${anchor:,.0f}) — comps may be off-market; "
                f"confidence lowered to MEDIUM, verify before bidding."
            )

    # ---- ARV sanity band (hard guards) ----------------------------------
    arv_conf = _arv_sanity(li, out, arv_conf, arv_flags,
                           None if arv_from_anchor else anchor, anchor_label,
                           anchor_is_weak_evidence=_arv_from_listing)

    # ---- Rehab range ----------------------------------------------------
    if li.property_kind == PropertyKind.LAND:
        out.rehab_tier = "land"
        out.rehab_low = out.rehab_expected = out.rehab_high = 0.0
    elif not li.living_sqft and li.property_kind != PropertyKind.MULTI_FAMILY:
        # Refuse to invent a sqft. Without sqft we cannot compute a rehab
        # range that's meaningful, so we don't compute one. The grade
        # pipeline downstream sees rehab_expected == None and treats it as
        # "data missing" rather than as a confident estimate. Multi-family
        # is exempt because their valuation runs per-unit, not per-sqft.
        out.rehab_tier = "unknown"
        out.notes.append(
            "Rehab not estimated: living_sqft missing. Confidence cannot "
            "be assigned without a building size."
        )
    else:
        tier = _condition_to_tier(li)
        out.rehab_tier = tier
        sqft = li.living_sqft or 1000  # multi-family fallback (per-unit avg)

        # Mobile / manufactured homes use a much cheaper rehab tier table
        # (vinyl skirting, single-pane windows, cosmetic-grade fixtures).
        # Generic SFR rehab cost overstates by 30-50% on these.
        #
        # `property_kind == MOBILE` alone identified 7 of the board's 791
        # manufactured leads, so this table was 99% dark. _is_manufactured also
        # reads the county's own land_use class and the CAMA building_type.
        is_mobile = _is_manufactured(li)
        tier_table = MOBILE_REHAB_TIERS if is_mobile else REHAB_TIERS

        # Photo-grounded rehab $/sqft from Vision wins over generic tier ranges
        # when both Vision tier and Vision rehab_psf range are HIGH-confidence.
        # Vision's psf reflects what the photos actually show — boarded windows,
        # missing roof shingles, peeling exterior — which the generic tier
        # buckets can't capture.
        vision = (raw.get("vision") or {}) if isinstance(raw, dict) else {}
        v_psf_low = vision.get("rehab_psf_low")
        v_psf_high = vision.get("rehab_psf_high")
        v_conf = (vision.get("confidence") or "").upper()
        if (v_psf_low and v_psf_high and v_conf in ("HIGH", "MEDIUM")
                and 1 <= v_psf_low <= v_psf_high <= 300):
            v_psf_mid = (v_psf_low + v_psf_high) / 2
            out.rehab_low = round(v_psf_low * sqft, -2)
            out.rehab_expected = round(v_psf_mid * sqft, -2)
            out.rehab_high = round(v_psf_high * sqft, -2)
            out.notes.append(
                f"Rehab from Vision photos: ${v_psf_low}-${v_psf_high}/sqft "
                f"× {sqft:,.0f} sqft (Vision conf={v_conf}, tier='{tier}')"
            )
        else:
            lo_psf, mid_psf, hi_psf = tier_table[tier]
            out.rehab_low = round(lo_psf * sqft, -2)
            out.rehab_expected = round(mid_psf * sqft, -2)
            out.rehab_high = round(hi_psf * sqft, -2)
            kind_tag = "mobile" if is_mobile else "standard"
            out.notes.append(
                f"Rehab tier '{tier}' ({kind_tag}) on {sqft:,.0f} sqft "
                f"= ${lo_psf}-${hi_psf}/sqft"
            )

        # Sanity cap: a per-sqft rehab on a LARGE but modest-$/sqft home balloons out of
        # proportion (a cosmetic-condition 2,770 sqft home showed 31% of ARV in repairs).
        # Cap rehab at a tier-appropriate share of ARV so the per-sqft model can't overstate
        # the repair on big, modest-value houses. Only ever LOWERS an over-estimate.
        _cap_pct = {"cosmetic": 0.08, "light": 0.15, "moderate": 0.27,
                    "heavy": 0.42, "gut": 0.60}.get(tier)
        if _cap_pct and out.arv_expected and out.rehab_expected:
            _cap = out.arv_expected * _cap_pct
            if out.rehab_expected > _cap:
                _scale = _cap / out.rehab_expected
                _old_re = out.rehab_expected
                out.rehab_expected = round(_cap, -2)
                out.rehab_low = round((out.rehab_low or 0) * _scale, -2)
                out.rehab_high = round((out.rehab_high or 0) * _scale, -2)
                out.notes.append(
                    f"Rehab capped at {_cap_pct * 100:.0f}% of ARV for '{tier}' tier "
                    f"(${_old_re:,.0f} → ${out.rehab_expected:,.0f}) — per-sqft estimate was "
                    f"disproportionate to a ${out.arv_expected:,.0f} property."
                )

    # Senior liens reduce what a buyer can pay:
    #  (a) at a JUNIOR-position foreclosure the winner takes title SUBJECT TO all
    #      senior debt (rod/priority.py total_senior_amount), and
    #  (b) SUPER-PRIORITY liens (state tax liens) survive ANY foreclosure, so
    #      they always come off the bid (enrichment_lien_stack -> raw['liens']).
    # Either way the cost must come out of both max bid and total investment,
    # else the deal looks falsely cheap.
    lp = raw.get("lien_priority") or {}
    senior = float(lp.get("total_senior_amount") or 0)
    fpos = lp.get("foreclosure_position")
    junior_senior = senior if (senior > 0 and (fpos is None or fpos > 1)) else 0.0
    superpri = sum(float(x.get("amount") or 0) for x in (raw.get("liens") or [])
                   if isinstance(x, dict) and x.get("super_priority"))
    senior_cost = round(junior_senior + superpri, 2)
    senior_applies = senior_cost > 0

    # Pad the repair estimate with a contingency buffer for the buy math — every
    # seasoned flipper bids on rehab + 10-15% for hidden conditions, never the
    # optimistic mid. (The headline rehab_expected stays un-padded for display.)
    rehab_buy = round((out.rehab_expected or 0) * (1 + REHAB_CONTINGENCY_PCT), -2)
    if out.rehab_expected:
        out.rehab_with_contingency = rehab_buy

    # ---- Max bid (70% rule, expected case) ------------------------------
    if out.arv_expected:
        # The canonical 70%-rule 30% haircut ALREADY embeds selling commission, holding, closing and
        # target profit — subtracting SELLING_PCT again here double-charged ~7% of ARV and made ~half
        # the board's bids un-winnable at real auctions (median bid 57% of resale vs the 60-80% range
        # auctions actually clear). Backtest (n=266 recorded sales): dropping the duplicate fee and
        # using 0.75 moves median bid/resale 57%->69% and cuts the sub-55% (auction-losing) rate
        # 45%->32%. Selling cost is still charged ONCE, below, in total_investment/estimated_profit.
        out.max_bid_70 = max(
            0.0,
            round(0.75 * out.arv_expected - rehab_buy, -2),
        )
        # `rehab_buy` is `(out.rehab_expected or 0) * 1.125`, so a MISSING rehab
        # estimate silently becomes a $0 deduction and the bid collapses to a
        # flat 0.75 x ARV. Measured after the trust gate: 19,250 of 21,843
        # published bids deduct $0 (88.1%) and 17,611 are exactly 0.75 x ARV to
        # the cent. Most of that is legitimate — a LAND lead has rehab_expected
        # 0.0 and rehab_tier "land", and there really is nothing to repair.
        #
        # The 9,190 that matter are the ones where rehab is UNKNOWN, not zero:
        # rehab_tier "unknown", set 500 lines above because living_sqft is
        # missing, so no tier table can be applied. 1,833 of those bids clear
        # $250,000 and they total $740,267,300; every one of the board's largest
        # bids ($1.27M-$1.50M) is in this class, on distressed inventory, at 75%
        # of ARV with nothing taken out for the work.
        #
        # THE TEST IS `is None`, NOT falsiness, and that distinction is the whole
        # of the scoping. `rehab_expected == 0.0` with rehab_tier "land" is a
        # CORRECT zero — 10,063 of the 19,250 — and flagging it would put a
        # warning on ten thousand numbers that are right, which is the "do not
        # gut the normal case" line. Only `None` (tier "unknown") means the
        # engine never established a figure at all.
        #
        # The bid is NOT withheld. It is the standard 70%-rule number computed
        # from the only inputs that exist, blanking 9,190 of them would remove
        # most of the board's economics, and the missing term is genuinely
        # unknowable without a building size. What was wrong is that "no rehab
        # was deducted" appeared ONLY as a notes line 500 lines away from the
        # figure — nothing attached it to the bid. So it becomes a flag, in
        # `arv_flags`, which is one of the three lists docs/dashboard.js's
        # rehabTrust() reads for exactly this literal (see MAX_BID_NO_REHAB_FLAG).
        if out.rehab_expected is None:
            out.arv_flags = sorted(set((out.arv_flags or []) + [MAX_BID_NO_REHAB_FLAG]))
            out.notes.append(
                f"Max bid deducts $0 of repairs: this lead has no living_sqft, so no "
                f"rehab could be estimated at all (rehab_tier '{out.rehab_tier}'). The "
                f"figure is 75% of ARV with nothing taken out for the work — a CEILING, "
                f"not a bid. Subtract your own repair estimate before using it."
            )
        if senior_applies and out.max_bid_70 is not None:
            out.max_bid_70 = max(0.0, round(out.max_bid_70 - senior_cost, -2))
            bits = []
            if junior_senior:
                bits.append(f"${junior_senior:,.0f} junior-position senior lien(s)")
            if superpri:
                bits.append(f"${superpri:,.0f} super-priority lien(s) (e.g. tax)")
            out.notes.append(
                "Subtracted " + " + ".join(bits) + " from max bid (buyer takes "
                "title subject to this debt)."
            )

        # ---- Actual payoff into max bid -------------------------------------
        # A buyer who must ASSUME or CLEAR real debt to take clean title can't bid
        # that money away — surviving debt competes with the bid dollar-for-dollar.
        # The 70%-rule max bid above only nets out senior liens (debt senior to the
        # foreclosing lien); it ignores the FORECLOSED debt itself. Subtract a payoff
        # when we actually know it:
        #   (a) raw.amount_owed.is_actual_debt — a parsed judgment / indebtedness, or
        #   (b) raw.equity.payoff_estimate at MEDIUM+ confidence (the equity engine's
        #       amount_owed-grounded payoff; LOW-confidence opening-bid/last-sale
        #       proxies are excluded — too noisy to bid against).
        #
        # DOUBLE-COUNT GUARD (critical): at a foreclosure auction the *winning bid*
        # already extinguishes the foreclosed debt up to the bid amount — so when the
        # lead carries an opening_bid we only subtract the payoff that SURVIVES it,
        # i.e. max(0, payoff − opening_bid). Subtracting the full payoff on top of an
        # opening-bid-grounded payoff (the common amount_owed:opening_bid case, where
        # payoff == opening_bid) would charge the same dollars twice. When there's no
        # opening_bid (e.g. a bare money judgment), the full payoff competes with the
        # bid. This is also DISTINCT from senior_cost (liens senior to the
        # foreclosure, already netted above), so those are never double-counted; and
        # we never read both an actual-debt value and the equity payoff (prefer the
        # actual-debt figure once).
        if out.max_bid_70 is not None and out.max_bid_70 > 0:
            ao = raw.get("amount_owed") if isinstance(raw, dict) else None
            eq = raw.get("equity") if isinstance(raw, dict) else None
            payoff_amt = None
            payoff_label = None
            if isinstance(ao, dict) and ao.get("is_actual_debt") and ao.get("value"):
                try:
                    v = float(ao["value"])
                    if v > 0:
                        payoff_amt = v
                        payoff_label = f"actual debt ({ao.get('label') or ao.get('source') or 'amount_owed'})"
                except (TypeError, ValueError):
                    pass
            if payoff_amt is None and isinstance(eq, dict) and eq.get("payoff_estimate"):
                conf = str(eq.get("payoff_confidence") or eq.get("confidence") or "").lower()
                if conf in ("medium", "high"):
                    try:
                        v = float(eq["payoff_estimate"])
                        if v > 0:
                            payoff_amt = v
                            payoff_label = f"estimated payoff ({eq.get('payoff_source') or 'equity'}, {conf} conf)"
                    except (TypeError, ValueError):
                        pass
            if payoff_amt is not None:
                # Only the debt that survives the winning bid is assumable on top.
                ob = float(li.opening_bid) if li.opening_bid else 0.0
                surviving = payoff_amt - ob if ob > 0 else payoff_amt
                # A surviving payoff that would dwarf the property (a money judgment
                # leaking in, or a multiple-of-ARV figure) isn't a clean assumable
                # debt — gate on the 3×ARV sanity ceiling rather than let garbage
                # flip the bid; max() already floors the result at 0.
                # Materiality floor: when payoff ≈ opening_bid (the common
                # amount_owed:opening_bid case) the surviving sliver is just
                # rounding noise — don't emit a "$2 subtracted" note.
                if (surviving >= 500 and out.arv_expected
                        and surviving <= 3.0 * out.arv_expected):
                    old_bid = out.max_bid_70
                    out.max_bid_70 = max(0.0, round(out.max_bid_70 - surviving, -2))
                    src_note = (f" beyond the ${ob:,.0f} opening bid the winning bid clears"
                                if ob > 0 else "")
                    out.notes.append(
                        f"Subtracted ${surviving:,.0f} {payoff_label}{src_note} from "
                        f"max bid (buyer must clear/assume this surviving debt for "
                        f"clean title): ${old_bid:,.0f} → ${out.max_bid_70:,.0f}."
                    )

        # ---- A max bid can never exceed a price you could simply pay --------
        # On a SELLER_ASK source the parcel is publicly offered at `opening_bid`,
        # so a "maximum viable bid" above that figure is not a bid at all — the
        # buyer would pay the ask. `ARV_FLAG_ABOVE_ASK` catches the leads where
        # the ARV itself contradicts the ask (>= 1.6x) and blanks their money;
        # this closes the narrow band underneath it, where the ARV passes but the
        # 0.75 rule still lands above the asking price (0.75 x ARV > ask for any
        # ARV over 1.333x the ask).
        #
        # Measured: after the ask flag, 4 leads still published a bid above their
        # own asking price, $266,800 in total — [1157] 01 Taylor Road, Anderson
        # SC, listed at $60,000 with a $62,100 "max viable bid". A CAP rather
        # than a flag because nothing here is uncertain: the ceiling is a
        # published price, not an estimate, and it is exactly as much a hard
        # bound on the bid as the `max(0.0, ...)` floor beside it.
        #
        # DELIBERATELY NOT lowered into a flag threshold instead. The 1.333-1.6
        # band holds 167 ask-source leads, and ~160 of them are `bid_proxy_arv`
        # rows whose ARV IS `ask x 1.5` by construction — so a ratio flag there
        # would fire on the engine's own arithmetic, on leads already CONTRADICTED
        # and already publishing no money. One more red mark saying "the ARV is
        # above the ask" about a number defined as 1.5x the ask is noise, and it
        # would be a false description of what is wrong with them.
        if (out.max_bid_70 is not None and li.source in SELLER_ASK_SOURCES
                and li.opening_bid and float(li.opening_bid) > 0
                and out.max_bid_70 > float(li.opening_bid)):
            _old_mb = out.max_bid_70
            # FLOOR to the hundred, not round. Every money field here rounds to
            # -2, and `round(42_061, -2)` is 42,100 — $39 back above the ceiling
            # it was meant to enforce. [1193] Springview Dr, Oconee SC was the
            # single lead still publishing a bid over its own ask after the cap
            # went in, and that was the entire reason.
            out.max_bid_70 = float(int(float(li.opening_bid) // 100) * 100)
            out.notes.append(
                f"Max bid capped at the ${float(li.opening_bid):,.0f} asking price "
                f"(the 70%-rule figure came out ${_old_mb:,.0f}). This parcel is "
                f"publicly listed at that price, so no bid above it is 'viable' — "
                f"you would simply buy it. Read the gap as the engine's ARV sitting "
                f"above what the seller is asking, not as headroom."
            )

        # Wholesale lens: what an end-investor MAO leaves for an assignment fee.
        if out.max_bid_70 is not None:
            out.wholesale_mao = max(0.0, round(out.max_bid_70 - ASSIGNMENT_FEE, -2))
            if li.opening_bid:
                out.wholesale_spread = round(out.max_bid_70 - float(li.opening_bid), -2)

    # ---- Total investment if bidding at opening bid ---------------------
    # Holding period scales with local market velocity (months-of-inventory from
    # enrichment_comps): fast market -> shorter carry, slow market -> longer.
    holding_months = (raw.get("market_velocity") or {}).get("holding_months_est") or HOLDING_MONTHS
    bid = li.opening_bid
    if bid and out.arv_expected:
        closing = bid * CLOSING_PCT
        holding = bid * HOLDING_RATE_MONTH * holding_months
        selling = out.arv_expected * SELLING_PCT
        # senior_cost (junior-position + super-priority liens) computed above;
        # rehab_buy includes the contingency buffer (same number used for max bid).
        total = bid + senior_cost + rehab_buy + closing + holding + selling
        out.total_investment = round(total, -2)
        out.estimated_profit = round(out.arv_expected - total, -2)
        if total > 0:
            out.roi_pct = round((out.estimated_profit / total) * 100, 1)
        # Cash on cash: 25% down + 75% loan. Use rehab_buy (contingency-padded)
        # and the market-velocity holding_months EVERYWHERE so the cash math is
        # the same deal as the flip math (Pass-2 fix: was using un-padded rehab
        # + the fixed 6-month constant, making CoC optimistic vs ROI).
        cash_down = bid * DOWN_PCT + rehab_buy  # rehab usually cash
        loan_amt = bid * (1 - DOWN_PCT)
        loan_interest = loan_amt * LOAN_RATE_MONTH * holding_months
        cash_profit = out.arv_expected - bid - senior_cost - rehab_buy - closing - holding - selling - loan_interest
        if cash_down > 0:
            out.cash_on_cash_pct = round((cash_profit / cash_down) * 100, 1)
        out.bid_to_arv_pct = round((bid / out.arv_expected) * 100, 1)

    # ---- Confidence -----------------------------------------------------
    score = 0
    if arv_conf == "HIGH":
        score += 3      # comp-grounded ARV — was previously unscored (bug)
    elif arv_conf == "MEDIUM":
        score += 2
    elif arv_conf == "LOW":
        score += 0
    if li.living_sqft:
        score += 1
    if li.year_built:
        score += 1
    if li.bedrooms is not None and li.bathrooms is not None:
        score += 1
    if li.tax_value:
        score += 1
    out.confidence = "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW"
    # Persist the ARV-method confidence so grading.py can read it (it was
    # computed locally but never stored — grade-withhold silently degraded to
    # bid-only). arv_conf is final by here (set in _arv_signals + any MEDIUM
    # upgrade above).
    out.arv_confidence = arv_conf

    # ---- Deal status: investor's actionable verdict ----------------------
    # Frames the listing in terms a flipper actually decides on:
    #   GREAT       — listing price is below the 70% rule max bid (rare, snap-up)
    #   OK          — listing price right at max bid (margin OK, do diligence)
    #   NEGOTIATE   — listing price above max bid; specifies haircut needed
    #   PASS        — math doesn't work even at $0 acquisition
    #
    # SUPPRESSED when the ARV was itself derived from this same opening bid: the
    # comparison "is the bid below the max viable bid?" reduces to "is 1 < 1.8?"
    # and answers GREAT every time. See BID_PROXY_MARKER above.
    if "bid_proxy_arv" in (out.arv_flags or []):
        out.notes.append(
            "No deal verdict: the ARV here is a multiple of the opening bid itself, so "
            "comparing the bid against it would grade the arithmetic rather than the "
            "property. Needs comps or a county value before a buy/pass call is meaningful."
        )
    elif out.max_bid_70 is not None and bid is not None and bid > 0:
        if out.max_bid_70 <= 0:
            out.deal_status = "PASS"
            out.deal_message = (
                f"Math doesn't work — ARV ${out.arv_expected or 0:,.0f} minus "
                f"rehab ${out.rehab_expected or 0:,.0f} leaves no margin even at $0 acquisition."
            )
        elif bid <= out.max_bid_70 * 0.95:
            out.deal_status = "GREAT"
            out.deal_message = (
                f"List ${bid:,.0f} is below max viable bid ${out.max_bid_70:,.0f}. "
                f"Solid margin if specs are accurate — verify."
            )
        elif bid <= out.max_bid_70 * 1.05:
            out.deal_status = "OK"
            out.deal_message = (
                f"List ${bid:,.0f} is right at max viable bid ${out.max_bid_70:,.0f}. "
                f"Tight but workable — do diligence."
            )
        else:
            out.haircut_needed = round(bid - out.max_bid_70, -2)
            out.deal_status = "NEGOTIATE"
            out.deal_message = (
                f"List ${bid:,.0f} is ${out.haircut_needed:,.0f} above max viable "
                f"bid ${out.max_bid_70:,.0f}. Negotiate down or pass."
            )

    # ---- Buy-and-hold (rental) verdict ----------------------------------
    # An investor not interested in flipping wants to know: at this bid,
    # what's the cap rate and monthly cashflow if I held it as a rental?
    # Standard 50% rule: NOI = 50% of gross rent (covers vacancy, property
    # mgmt, insurance, taxes, maintenance, capex reserve).
    rent_psf = raw.get("rent_median_ppsf") if isinstance(raw, dict) else None
    if (rent_psf and li.living_sqft and bid and bid > 0
            and li.property_kind not in (PropertyKind.LAND,)):
        monthly_rent = float(rent_psf) * float(li.living_sqft)
        out.monthly_rent_est = round(monthly_rent, 0)
        out.annual_gross_rent = round(monthly_rent * 12, 0)
        out.noi_annual = round(out.annual_gross_rent * 0.50, 0)
        # Total acquisition for cap rate: bid + rehab + closing fees.
        # Holding/selling fees don't apply to a hold strategy.
        rehab = out.rehab_expected or 0
        acq_total = bid + rehab + bid * CLOSING_PCT
        if acq_total > 0:
            out.cap_rate_pct = round((out.noi_annual / acq_total) * 100, 1)
        # Monthly cashflow vs. PITI on a 25%-down 30-yr mortgage @ 7.5%.
        # (Hard-money holding cost in the flip path is too short-term to
        # use for hold; this is permanent-financing economics.)
        loan_amt = bid * (1 - DOWN_PCT)
        # 30-yr fixed at 7.5% APR → monthly P&I ≈ loan × 0.006992
        piti_monthly = loan_amt * 0.006992
        # Add taxes + insurance estimate: 1.5% of bid annually
        piti_monthly += (bid * 0.015) / 12
        cashflow = (out.noi_annual / 12) - piti_monthly
        out.monthly_cashflow_est = round(cashflow, 0)
        # 1% rule: monthly rent ≥ 1% of PURCHASE PRICE (conventional usage —
        # investors apply this against the offer/bid, not all-in cost).
        out.one_pct_rule = monthly_rent >= bid * 0.01

        # Verdict: cap-rate-driven (NOI / acq).
        # 10%+ cap = exceptional; 8% = good; 6% = market; <5% = thin
        cr = out.cap_rate_pct or 0
        if cr >= 10 and out.monthly_cashflow_est > 0:
            out.hold_status = "GREAT"
            out.hold_message = (
                f"Cap rate {cr:.1f}% with ${out.monthly_cashflow_est:.0f}/mo cashflow. "
                f"Strong rental in this market."
            )
        elif cr >= 7 and out.monthly_cashflow_est > 0:
            out.hold_status = "OK"
            out.hold_message = (
                f"Cap rate {cr:.1f}% — market-rate rental. Cashflow ${out.monthly_cashflow_est:.0f}/mo."
            )
        elif cr >= 5:
            out.hold_status = "NEGOTIATE"
            out.hold_message = (
                f"Cap rate {cr:.1f}% is thin. Monthly cashflow "
                f"${out.monthly_cashflow_est:.0f}/mo at this bid; "
                f"would need a price cut to clear hurdle."
            )
        else:
            out.hold_status = "PASS"
            out.hold_message = (
                f"Cap rate {cr:.1f}% — won't pencil as a rental at this bid."
            )

    return out


def to_dict(c: Calc) -> dict:
    return {k: v for k, v in asdict(c).items() if v is not None}
