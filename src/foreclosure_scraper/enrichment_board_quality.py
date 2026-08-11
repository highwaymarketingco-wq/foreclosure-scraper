"""Idempotent board data-quality corrections — runs late in the pipeline / regenerate.

Fixes verified 2026-06-30 against the live board:
  * out-of-footprint geocodes: 3 leads landed in CT/KY/AL (geocoder fell back to a wrong state).
    Null lat/lon + flag so the map and geo-comps don't trust them.
  * centroid/town-center snaps: 319 leads share an identical 5-decimal coordinate (42 on one point)
    = a county-centroid or town-center fallback, not a real rooftop. Flag raw['geo_imprecise'] so
    the map/comps can down-weight; keep the coord (county-level locate is still useful).
  * auction_status casing/empties: 'none'/'' vs None fragmented every status filter. Normalize.
  * presumed_withdrawn stale cases (1,647, incl most of the HOT tier): the case stopped appearing
    in the lis-pendens feed = likely resolved/withdrawn. Flag raw['stale_case'] and down-rank a
    stale HOT to WARM so the operator's HOT queue isn't dominated by dead leads (non-destructive —
    the lead stays on the board, just not prioritized).
  * sales that already happened, still advertised as upcoming (2026-08-11): 258 leads carry a
    sale_date in the PAST. 32 still say auction_status 'active' (plus 5 'status: active', 2
    'status: active - outbid period', 1 'upset_bid_period', 2 'reopen') and 23 still publish a
    deal verdict, 8 of them GREAT. `sold_confirmed` is set on NONE of them. This is the
    "drove to a sale that already happened" case, and one of them sits at #3 on the default
    sort. Flag raw['sale_date_passed'], withhold the VERDICT, and normalize a stale
    still-open status — see the block above `_SALE_PASSED_GRACE_DAYS`.
"""
from __future__ import annotations

import collections
from datetime import date, datetime

from .valuation.grading import ARV_VERDICT_FIELDS

# NC + SC bounding box (generous): lat 32.0–36.8, lon −84.5 to −75.3.
_LAT_MIN, _LAT_MAX, _LON_MIN, _LON_MAX = 32.0, 36.8, -84.5, -75.3
_CENTROID_MIN_COLLISIONS = 8   # >=8 leads on the exact same ~1m point = geocoder fallback

# ===========================================================================
# A SALE DATE THAT HAS PASSED IS A FACT. AN "ACTIVE" STATUS AFTER IT IS A CLAIM.
#
# Three different things are wrong on these leads and they deserve three
# different responses, because they are wrong for different lengths of time.
#
# THE VERDICT goes immediately, with no grace period. `deal_status` /
# `deal_message` are the board telling the operator to bid a specific number at
# a specific auction ("List $187,000 is below max viable bid $204,800"). Once
# the auction date is behind us that sentence is not a stale estimate, it is an
# instruction to attend an event that is over. 23 leads publish one, 8 of them
# GREAT. Nothing else on the card is impugned — the ARV, the max bid and the
# equity are still a valuation of a real property that may now be REO or in an
# upset-bid window, both of which are live opportunities — so the dollars stay.
#
# THE STATUS gets a grace window, and the window is not arbitrary: in North
# Carolina the upset-bid period runs TEN DAYS from the report of sale, and a
# lead that says "active" three days after its sale date is telling the truth —
# an upset bid can still be filed, which is one of the better opportunities on
# this board. Overwriting that on day one would delete a real lead to fix a
# cosmetic one. Past ten days the claim is no longer defensible, so the status
# is normalized to `sale_date_passed` and the source's own wording is preserved
# verbatim in raw['auction_status_reported'] — provenance is never destroyed,
# only superseded.
#
# `sold_confirmed` IS NOT SET, and that is deliberate. It is an existing
# board-wide interface meaning COURT-CONFIRMED sale, and six readers treat it as
# "hide this lead entirely" (dashboard.js:1164/1223/2481, distress_score:390,
# board_persist:82). A sale DATE that has passed is not confirmation that a sale
# occurred: foreclosure sales are continued, postponed and cancelled constantly,
# and 151 of these 258 leads already carry `presumed_withdrawn`. Setting it
# would silently delete leads to fix a label — the opposite error, and the more
# expensive one.
#
# FLAG STRINGS INTRODUCED HERE (interface):
#   raw['sale_date_passed']        bool, True when sale_date < today
#   raw['sale_date_passed_days']   int, days elapsed since that date
#   raw['auction_status_reported'] the source's original wording, kept whenever
#                                  auction_status is overwritten below
#   li.auction_status == "sale_date_passed"   the normalized value
# The dashboard must read `raw['sale_date_passed']` to mark these; it does not
# today, and the status-filter chips will gain a `sale_date_passed` value.
# ===========================================================================
_SALE_PASSED_GRACE_DAYS = 10   # NC upset-bid period; an "active" claim survives it

# auction_status values that assert the sale has NOT happened yet / is still
# open. Matched on a normalized form, so 'status: active - outbid period' and
# 'Active' both land here. Everything else (cancelled, disposed, final,
# presumed_withdrawn, deficiency, ...) already says something truthful about a
# past sale and is left exactly as the source wrote it.
_STATUS_CLAIMS_OPEN = ("active", "upset", "outbid", "pending", "reopen",
                       "scheduled", "upcoming", "postponed", "hearing")


def _raw(li) -> dict:
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li.raw


def _as_date(v) -> "date | None":
    """A date out of whatever the sources put in `sale_date`."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def enrich_board_quality(listings) -> dict:
    stats: collections.Counter = collections.Counter()
    today = date.today()

    # Pre-pass: find centroid-collision coordinates (shared by many leads).
    coord = collections.Counter(
        (round(li.latitude, 5), round(li.longitude, 5))
        for li in listings
        if getattr(li, "latitude", None) and getattr(li, "longitude", None)
    )
    centroids = {c for c, n in coord.items() if n >= _CENTROID_MIN_COLLISIONS}

    for li in listings:
        raw = _raw(li)

        # 1. geo bbox guard — null clearly-wrong out-of-state coordinates.
        lat, lon = getattr(li, "latitude", None), getattr(li, "longitude", None)
        if lat is not None and lon is not None:
            if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
                li.latitude = None
                li.longitude = None
                raw["geo_imprecise"] = "out_of_bbox"
                # a geo-anchored ARV built on wrong-location comps is untrustworthy
                if isinstance(raw.get("calc"), dict):
                    raw["calc"]["arv_geo_suspect"] = True
                stats["bbox_nulled"] += 1
            elif (round(lat, 5), round(lon, 5)) in centroids:
                raw["geo_imprecise"] = "centroid_snap"
                stats["centroid_flagged"] += 1

        # 2. auction_status normalization.
        st = getattr(li, "auction_status", None)
        if isinstance(st, str):
            norm = st.strip().lower()
            if norm in ("", "none", "null", "n/a"):
                li.auction_status = None
                stats["status_nulled"] += 1
            elif norm != st:
                li.auction_status = norm
                stats["status_normalized"] += 1

        # 2b. the sale already happened — see the block at the top of this file.
        sd = _as_date(getattr(li, "sale_date", None))
        if sd and sd < today:
            elapsed = (today - sd).days
            raw["sale_date_passed"] = True
            raw["sale_date_passed_days"] = elapsed
            stats["sale_date_passed"] += 1
            calc = raw.get("calc")
            if isinstance(calc, dict):
                pulled = False
                for f in ARV_VERDICT_FIELDS:
                    if calc.pop(f, None) is not None:
                        pulled = True
                if pulled:
                    stats["past_sale_verdict_withheld"] += 1
                    note = ("Deal verdict withheld: this sale date "
                            f"({sd.isoformat()}) is {elapsed} days in the past. "
                            "A verdict is advice about what to bid at an auction "
                            "that has already been held. The valuation itself is "
                            "unchanged — the property may now be REO or inside an "
                            "upset-bid window.")
                    notes = calc.setdefault("notes", [])
                    if isinstance(notes, list) and note not in notes:
                        notes.append(note)
            st_now = (getattr(li, "auction_status", None) or "").strip().lower()
            if (elapsed > _SALE_PASSED_GRACE_DAYS and st_now
                    and any(k in st_now for k in _STATUS_CLAIMS_OPEN)):
                raw.setdefault("auction_status_reported", li.auction_status)
                li.auction_status = "sale_date_passed"
                stats["past_sale_status_normalized"] += 1

        # 3. stale presumed-withdrawn cases — flag + down-rank a stale HOT.
        if (getattr(li, "auction_status", None) or "") == "presumed_withdrawn":
            raw["stale_case"] = True
            stats["stale_flagged"] += 1
            ds = raw.get("distress_stack")
            if isinstance(ds, dict) and ds.get("tier") == "HOT":
                ds["tier"] = "WARM"
                ds["downranked_stale"] = True
                stats["hot_downranked"] += 1

    return dict(stats)
