"""Deal analysis for the Porsche board — cost-to-fix, all-in, max bid, feasibility.

WHAT THIS ANSWERS
    "Bid under $50k" is the wrong test for a salvage car: a $30k Copart bid plus
    Porsche repairs plus auction fees can land well over $50k all-in. This layer
    computes what a car actually costs to own driveable, and whether that pencils.

    Per car it produces:
      est_clean_value  retail value of a CLEAN example (year + model), from the
                       dealer listings on the board, falling back to a model table
      est_recon        rough repair/recondition cost (title/severity based)
      est_fees         auction buyer fees or dealer doc/transport
      all_in           (price or current bid) + est_fees + est_recon
      resale_value     what it's worth once fixed (title stigma discounts salvage)
      est_margin       resale_value - all_in  (the actual room)
      max_bid_target   highest bid that keeps all_in <= target (default $50k)
      feasible         all_in <= target AND est_margin > MIN_MARGIN
      note             one-line reason

HONESTY ABOUT THE REPAIR NUMBER
    Copart/IAA do not expose per-car damage detail in the data we capture, so
    est_recon is a TITLE-BASED PLANNING ESTIMATE (a fraction of clean value), not
    a quote off a photo inspection. It is deliberately conservative. A light-hit
    salvage will cost less; a structural or flood car will cost more or be a
    write-off. The constants below are in one place so they can be calibrated as
    real outcomes come in.
"""
from __future__ import annotations

import statistics
from typing import Iterable

from .models import Listing

# --- calibratable assumptions (one place) ----------------------------------

#: Repair as a fraction of a clean example's value, by title status. Porsche
#: parts + labor are expensive, so salvage recon runs high. Used only when the
#: source gives NO damage detail; Copart/IAA cars use DAMAGE_RECON below.
RECON_FRACTION = {
    "clean": 0.02,       # detail / minor reconditioning
    "unknown": 0.02,     # dealer retail cars land here; treated as clean
    "rebuilt": 0.0,      # already repaired; the stigma is priced in resale
    "salvage": 0.33,     # a planning number — light hits less, structural more
    "flood": 0.55,       # usually a write-off; shown so it reads as one
    "parts": 1.0,        # not a runner
}

#: Repair as a fraction of clean value, keyed on Copart/IAA PRIMARY DAMAGE. This
#: is the real per-car signal: a front-end hit and an all-over wreck are not the
#: same repair. Porsche panels/electronics/radiators run high, so these are not
#: economy-car fractions. Matched as a substring, most-specific first.
DAMAGE_RECON = [
    ("water/flood", 0.75), ("flood", 0.75), ("burn", 0.92), ("fire", 0.92),
    ("rollover", 0.55), ("all over", 0.45), ("undercarriage", 0.32),
    ("front end", 0.30), ("front", 0.28), ("rear end", 0.24), ("rear", 0.22),
    ("side", 0.26), ("mechanical", 0.18), ("suspension", 0.20),
    ("vandalism", 0.18), ("stripped", 0.60), ("biohazard", 0.70),
    ("minor dent", 0.08), ("dent/scratches", 0.08), ("normal wear", 0.06),
    ("hail", 0.15), ("theft", 0.20), ("unknown", 0.33),
]
_SECONDARY_BUMP = 0.06  # a real secondary hit adds cost, unless it's cosmetic


def _damage_recon_fraction(primary: str, secondary: str) -> float:
    p = (primary or "").lower()
    frac = next((f for key, f in DAMAGE_RECON if key in p), 0.33)
    s = (secondary or "").lower()
    if s and not any(m in s for m in ("minor", "scratch", "normal", "none")):
        frac += _SECONDARY_BUMP
    return frac

#: Buyer-side fees. Auctions add a premium on top of the bid; dealers add doc +
#: transport.
def _fees(listing: Listing, bid: float) -> float:
    st = (listing.seller_type or "").lower()
    if "salvage" in st or listing.source in ("copart", "iaai"):
        return round(bid * 0.12 + 1000)      # Copart/IAA buyer fee + gate/flat
    if st == "auction" or listing.source in ("bring_a_trailer", "cars_and_bids"):
        return round(bid * 0.05)             # buyer premium
    return 1000                              # dealer doc + transport

#: Resale haircut once fixed — a rebuilt/salvage title sells for less than clean.
RESALE_TITLE_FACTOR = {
    "clean": 1.0, "unknown": 1.0, "rebuilt": 0.72, "salvage": 0.72,
    "flood": 0.55, "parts": 0.0,
}

#: Minimum room to call a deal feasible.
MIN_MARGIN = 3000.0
DEFAULT_TARGET = 50000.0

#: Fallback clean retail by (model, era) when the board has no dealer comp.
#: Grounded off the dealer listings actually on the board (2026 used market).
_MODEL_BASE = {
    "911": {2010: 45000, 2016: 70000, 2020: 95000},
    "cayman": {2010: 32000, 2016: 48000, 2020: 62000},
    "boxster": {2005: 18000, 2012: 30000, 2018: 45000},
    "cayenne": {2012: 22000, 2017: 32000, 2021: 48000},
    "taycan": {2020: 55000},
    "panamera": {2015: 30000, 2020: 55000},
    "macan": {2016: 28000, 2020: 42000},
}


_MODEL_WORDS = ("taycan", "panamera", "macan", "cayenne", "cayman",
                "boxster", "911", "carrera")


def _model_of(listing: Listing) -> str:
    """Model key, from the model field or parsed from the title. Many listings
    leave `model` blank but say '2014 Porsche Cayenne Platinum' in the title, so
    without this ~170 cars fall through as unvaluable."""
    raw = (listing.model or "").lower()
    if not raw:
        raw = (listing.title or "").lower()
    raw = raw.replace("718 ", "")
    for w in _MODEL_WORDS:
        if w in raw:
            return "911" if w == "carrera" else w
    return ""


def _base_value(model: str, year: int | None) -> float | None:
    tiers = _MODEL_BASE.get(model)
    if not tiers or not year:
        return None
    # nearest era anchor
    era = min(tiers, key=lambda y: abs(y - year))
    v = tiers[era]
    # gently age-adjust off the anchor (~4%/yr, floored)
    return max(8000.0, v * (1 + 0.04 * (year - era)))


def estimate_clean_value(listing: Listing, comps: dict[tuple[str, int], list[float]]) -> float | None:
    """Median price of CLEAN/dealer comps at the same model + year band, else a
    model-table fallback. None only when we truly cannot value it."""
    model = _model_of(listing)
    if model and listing.year:
        for band in (0, 1, 2, 3):
            pool: list[float] = []
            for yr in range(listing.year - band, listing.year + band + 1):
                pool += comps.get((model, yr), [])
            if len(pool) >= 3:
                return round(statistics.median(pool))
    return _base_value(model, listing.year)


def _bid(listing: Listing) -> float | None:
    return listing.price_usd or listing.current_bid_usd


def build_comps(listings: Iterable[Listing]) -> dict[tuple[str, int], list[float]]:
    """Clean-retail comp pools keyed by (model, year), from dealer/clean cars."""
    comps: dict[tuple[str, int], list[float]] = {}
    for li in listings:
        clean = (li.seller_type or "").lower() == "dealer" or li.title_status == "clean"
        price = li.price_usd
        if clean and price and li.year:
            model = _model_of(li)
            if model:
                comps.setdefault((model, li.year), []).append(price)
    return comps


def analyze(listing: Listing, comps: dict[tuple[str, int], list[float]],
            target: float = DEFAULT_TARGET) -> dict | None:
    """Full deal analysis for one car. None when it can't be valued."""
    bid = _bid(listing)

    # Damage data (Copart/IAA) is the real signal when we have it: their own
    # retail value beats a comp guess, and the primary-damage type gives a
    # per-car repair estimate instead of a flat title fraction.
    dmg = (listing.raw or {}).get("damage") if isinstance(listing.raw, dict) else None

    # Effective status: a car on Copart/IAA is a wreck being auctioned no matter
    # what its title_status parsed to. Treating an auction "unknown" as clean is
    # exactly how you end up bidding $42k on a salvage 911 that needs $21k of
    # work. Only genuine dealer/clean retail cars keep the light recon number.
    status = (listing.title_status or "unknown").lower()
    is_salvage_source = (listing.source in ("copart", "iaai")
                         or "salvage" in (listing.seller_type or "").lower())

    clean_value = None
    damage_note = None
    if dmg:
        try:
            retail = float(str(dmg.get("retail") or "").replace(",", ""))
            if retail > 3000:
                clean_value = retail
        except (TypeError, ValueError):
            pass
    if clean_value is None and not is_salvage_source and listing.price_usd:
        # A retail car's asking price IS its clean value — don't second-guess it
        # with a comp/table estimate that can push it over the cap on rounding.
        clean_value = listing.price_usd
    if clean_value is None:
        clean_value = estimate_clean_value(listing, comps)
    if clean_value is None:
        return None

    if is_salvage_source and status in ("unknown", "clean"):
        status = "salvage"

    if dmg and dmg.get("primary"):
        frac = _damage_recon_fraction(dmg.get("primary"), dmg.get("secondary"))
        recon = round(clean_value * frac)
        damage_note = dmg["primary"].title()
        if dmg.get("secondary") and "none" not in dmg["secondary"].lower():
            damage_note += " + " + dmg["secondary"].title()
    else:
        recon = round(clean_value * RECON_FRACTION.get(status, 0.33))
    resale = round(clean_value * RESALE_TITLE_FACTOR.get(status, 0.72))

    fees_now = _fees(listing, bid or 0)
    all_in = round((bid or 0) + fees_now + recon) if bid is not None else None
    margin = round(resale - all_in) if all_in is not None else None

    # Highest bid B such that B + fees(B) + recon <= target. For auctions the fee
    # scales with the bid, so solve for it.
    st = (listing.seller_type or "").lower()
    fee_rate = 0.12 if ("salvage" in st or listing.source in ("copart", "iaai")) \
        else (0.05 if st == "auction" or listing.source in ("bring_a_trailer", "cars_and_bids") else 0.0)
    flat = 1000 if fee_rate in (0.12, 0.0) else 0
    budget_for_bid = target - recon - flat
    max_bid_target = max(0, round(budget_for_bid / (1 + fee_rate))) if budget_for_bid > 0 else 0

    # A project car (salvage/rebuilt) has to clear a repair-margin bar; a clean
    # retail car just has to be a real car under the budget.
    is_project = status in ("salvage", "rebuilt", "flood", "parts")

    # Hard disqualifiers — cars that are a bad buy regardless of the math:
    #   - a salvage Taycan is a wrecked EV: high-voltage battery/pack damage is
    #     dangerous and ruinously expensive, so skip it outright
    #   - flood/water is a slow-death electrical nightmare on a Porsche
    #   - frame/structural/rollover damage means the car's bones are bent
    dmg_text = " ".join(str(x) for x in (
        (dmg or {}).get("primary"), (dmg or {}).get("secondary"),
        listing.title)).lower()
    disqualified = None
    if is_salvage_source and _model_of(listing) == "taycan":
        disqualified = "salvage Taycan — wrecked EV, HV battery risk, skip"
    elif "flood" in dmg_text or "water" in dmg_text or status == "flood":
        disqualified = "flood/water damage — skip"
    elif any(w in dmg_text for w in ("frame", "structural", "rollover", "pillar", "unibody")):
        disqualified = "frame/structural damage — skip"

    if disqualified:
        return {
            "est_clean_value": round(clean_value), "est_recon": recon,
            "est_fees": fees_now, "all_in": all_in, "resale_value": resale,
            "est_margin": margin, "max_bid_target": 0, "target": int(target),
            "feasible": False, "disqualified": disqualified,
            "damage": damage_note, "note": disqualified,
        }

    if status in ("flood", "parts"):
        note = f"{status} — likely a write-off"
        feasible = False
    elif all_in is None:
        note = f"no price/bid yet — bid up to ${max_bid_target:,} to stay under ${int(target/1000)}k all-in"
        feasible = None
    elif all_in > target:
        note = f"all-in ${all_in:,} over ${int(target/1000)}k — bid must drop below ${max_bid_target:,}"
        feasible = False
    elif is_project and (margin or 0) < MIN_MARGIN:
        note = f"project: all-in ${all_in:,} vs ${resale:,} fixed value — too thin to be worth the work"
        feasible = False
    elif is_project:
        note = f"project: all-in ${all_in:,}, ~${margin:,} under ${resale:,} fixed value"
        feasible = True
    else:
        note = f"clean, all-in ${all_in:,} — ready to drive, under ${int(target/1000)}k"
        feasible = True

    if damage_note:
        note = f"{damage_note} — {note}"

    return {
        "est_clean_value": round(clean_value),
        "est_recon": recon,
        "est_fees": fees_now,
        "all_in": all_in,
        "resale_value": resale,
        "est_margin": margin,
        "max_bid_target": max_bid_target,
        "target": int(target),
        "feasible": feasible,
        "damage": damage_note,
        "note": note,
    }


def enrich_deal_analysis(listings: list[Listing], target: float = DEFAULT_TARGET) -> dict:
    """Attach raw['deal'] to every listing. Returns a summary."""
    comps = build_comps(listings)
    stats = {"analyzed": 0, "feasible": 0, "over_target": 0, "unvaluable": 0}
    for li in listings:
        res = analyze(li, comps, target)
        if res is None:
            stats["unvaluable"] += 1
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["deal"] = res
        stats["analyzed"] += 1
        if res["feasible"]:
            stats["feasible"] += 1
        if res["all_in"] is not None and res["all_in"] > target:
            stats["over_target"] += 1
    return stats
