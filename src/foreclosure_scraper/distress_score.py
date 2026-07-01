"""Stacked-distress score — the HOT/WARM operator board.

Turns the signals we already collect into a ranked motivated-seller score, the
way the paid lead desks do. Core idea (roadmap §6): a property hit by MULTIPLE
*distinct distress categories* is a far hotter lead than one with a single
signal. We:

  1. Group listings by parcel (so the same property in foreclosure AND tax sale
     stacks; cross-listing).
  2. Collect distress signals across the group, bucketed into 5 CATEGORIES.
     STACKED-2+ counts distinct *categories* (two liens = one FINANCIAL, not
     two) so a single default event can't fake a stack.
  3. Score = weighted signals (recency-aware) + equity band + contactability.
  4. Tier: HOT = stacked 2+ AND equity>=med AND contactable; WARM = stacked 2+
     OR a single high-weight signal with equity OR absentee+distress; else COLD.

Contactability (a mailable owner) is a HARD GATE for HOT — a hot lead you can't
reach isn't actionable. Already-sold properties (sold_confirmed) are excluded.
Pure computation over the board; no scraping.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .models import Listing

# ATC-45 Helene placard severity -> honest PROPERTY-signal weight. Calibrated
# against the existing scale (generic distressed=10, code_enforcement=14,
# bankruptcy=18, probate=20): a Restricted placard (limited entry, real damage)
# sits just above generic distressed; an Unsafe red-tag (do-not-occupy, facing
# major repair/teardown) sits above code enforcement. Helene leads have only the
# PROPERTY category (stack=1) so they can never reach HOT on this alone — they
# only tier up to WARM when combined with absentee ownership + severity.
_HELENE_PLACARD_BASE = {"restricted": 12, "unsafe": 16, "destroyed": 20}


def _helene_signal(li: Listing) -> Optional[tuple[str, str, int]]:
    """Scaled distress signal for a Hurricane-Helene ATC-45 placard lead.

    Replaces the flat generic 'distressed' (10) with a weight graded by placard
    severity + damage % + how many structures on the parcel are damaged. Reads
    the raw['helene'] meta set by the dedup pass, else parses the description.
    Returns None for non-Helene leads.
    """
    if li.source != "counties_nc.asheville_helene":
        return None
    r = li.raw if isinstance(li.raw, dict) else {}
    meta = r.get("helene") if isinstance(r.get("helene"), dict) else {}
    desc = li.description or ""
    placard = str(meta.get("worst_placard") or "").lower()
    if not placard:
        m = re.search(r"Helene damage:\s*([A-Za-z]+)\s+placard", desc)
        placard = m.group(1).lower() if m else ""
    base = _HELENE_PLACARD_BASE.get(placard)
    if base is None:
        return None
    pct = meta.get("worst_damage_pct")
    if pct is None:
        p = re.search(r"placard\s*-\s*([0-9]+)%", desc)
        pct = float(p.group(1)) if p else 0.0
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 0.0
    buildings = meta.get("damaged_buildings") or 1
    w = base
    if placard == "restricted" and pct >= 50:
        w += 2
    elif placard in ("unsafe", "destroyed") and pct >= 75:
        w += 3
    if isinstance(buildings, int) and buildings >= 3:
        w += 2  # a multi-structure damaged complex is a larger repair burden
    return (f"helene_{placard}", "PROPERTY", w)

# MLS lifecycle statuses that signal a seller who couldn't (or stopped trying
# to) move the property on the open market — a strong, fresh motivated-seller
# tell that often precedes a price drop or a quiet pre-foreclosure sale.
_DEAD_MLS_STATUSES = {"expired", "withdrawn", "cancelled", "canceled"}

# A listing sitting on-market past ~2x the local market-velocity months-of-
# inventory (MOI) is genuinely stale — buyers have passed on it at the current
# price for twice as long as the typical sell-through. We read MOI from the
# per-listing market_velocity block (enrichment_comps); fall back to a sane
# default when velocity could not be computed for the parcel's market.
_STALE_MOI_FALLBACK_MONTHS = 6.0
_STALE_MOI_MULTIPLIER = 2.0
# A price cut is only meaningful past noise (rounding, list re-keys). Require a
# real markdown vs the prior snapshot before it counts as a distress signal.
_PRICE_CUT_MIN_PCT = 0.04   # >=4% off the prior list price
_PRICE_CUT_MIN_ABS = 2500.0  # and at least $2.5k absolute


def _mls_fields(li: Listing) -> dict:
    """Pull the raw MLS lifecycle fields HomeHarvest persists, regardless of
    which scraper wrote them. homeharvest.py writes raw['homeharvest'];
    homeharvest_distressed.py writes raw['distressed']. Both carry the same
    mls_status / list_date / days_on_mls trio."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    for sub in ("homeharvest", "distressed"):
        block = raw.get(sub)
        if isinstance(block, dict) and (
            block.get("mls_status") is not None
            or block.get("days_on_mls") is not None
        ):
            return block
    return {}


# signal -> (category, weight). Categories: FINANCIAL / SALES / LEGAL /
# LIFE_EVENT / PROPERTY. Weight ~ motivation strength.
_LISTING_TYPE_SIGNAL = {
    "foreclosure_sale": ("FINANCIAL", 30),
    "lis_pendens": ("FINANCIAL", 28),
    "sheriff_sale": ("SALES", 25),
    "tax_sale": ("FINANCIAL", 30),
    "tax_lien": ("FINANCIAL", 20),
    "auction": ("SALES", 18),
    "reo": ("SALES", 15),
    "distressed": ("PROPERTY", 10),
    "probate_notice": ("LIFE_EVENT", 20),
}


def _mls_signals(li: Listing, prior_price: Optional[float] = None) -> list[tuple[str, str, int]]:
    """SALES-category signals derived from the MLS lifecycle fields HomeHarvest
    persists (mls_status / days_on_mls / list_price). These turn the raw realtor
    feed — which we previously only used for routing — into real distress tells:

      - stale_on_market: days_on_mls past ~2x local months-of-inventory. The
        market has passed on it at this price for twice the typical sell-through.
      - price_cut: current list price meaningfully below the prior snapshot's
        list price (seller capitulating). prior_price comes from score_board's
        cross-run index built off docs/listings.json.
      - withdrawn/expired: mls_status in expired/withdrawn/cancelled — couldn't
        sell on the open market, a classic pre-foreclosure / pre-pocket-sale tell.
    """
    sig: list[tuple[str, str, int]] = []
    mls = _mls_fields(li)

    status = str(mls.get("mls_status") or "").strip().lower()
    if status in _DEAD_MLS_STATUSES:
        sig.append(("mls_withdrawn_expired", "SALES", 18))

    dom = mls.get("days_on_mls")
    try:
        dom = float(dom) if dom is not None else None
    except (TypeError, ValueError):
        dom = None
    if dom is not None:
        raw = li.raw if isinstance(li.raw, dict) else {}
        moi = (raw.get("market_velocity") or {}).get("moi")
        try:
            moi = float(moi) if moi is not None else _STALE_MOI_FALLBACK_MONTHS
        except (TypeError, ValueError):
            moi = _STALE_MOI_FALLBACK_MONTHS
        # moi is months-of-inventory; days threshold = 2x MOI expressed in days.
        stale_days = moi * 30.0 * _STALE_MOI_MULTIPLIER
        if dom >= stale_days:
            sig.append(("stale_on_market", "SALES", 14))

    # price_cut — current list price (opening_bid carries list_price for the
    # realtor feeds) below the prior run's list price by a real margin.
    cur = li.opening_bid
    if prior_price and cur and cur > 0 and prior_price > 0 and cur < prior_price:
        drop = prior_price - cur
        if drop >= _PRICE_CUT_MIN_ABS and (drop / prior_price) >= _PRICE_CUT_MIN_PCT:
            sig.append(("price_cut", "SALES", 16))

    return sig


def _signals_for(li: Listing, prior_price: Optional[float] = None) -> list[tuple[str, str, int]]:
    """Return (signal_name, category, weight) for one listing's distress signals.

    prior_price (optional) is the same listing's list price from the previous
    run's snapshot, used only for the price_cut MLS signal. Defaults to None so
    single-listing callers (and tests) keep working unchanged."""
    r = li.raw if isinstance(li.raw, dict) else {}
    sig: list[tuple[str, str, int]] = []
    lt = (li.listing_type.value if li.listing_type else "") if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    if lt in _LISTING_TYPE_SIGNAL:
        cat, w = _LISTING_TYPE_SIGNAL[lt]
        # A Helene placard lead gets a severity-graded signal instead of the
        # flat generic 'distressed' (10).
        hel = _helene_signal(li) if lt == "distressed" else None
        sig.append(hel if hel else (lt, cat, w))
    # MLS-distress (stale_on_market / price_cut / withdrawn-expired)
    sig.extend(_mls_signals(li, prior_price=prior_price))
    # court / sale status
    if r.get("court_sale_status") in ("sale_noticed", "sold_unconfirmed"):
        sig.append(("court_sale", "FINANCIAL", 25))
    if r.get("upset_bid"):
        sig.append(("upset_bid", "FINANCIAL", 22))
    if (r.get("amount_owed") or {}).get("value"):
        sig.append(("recorded_debt", "FINANCIAL", 12))
    if r.get("str_permit_lapsed"):
        # revoked/expired short-term-rental permit = lost rental income, a
        # financial motivation to sell (esp. where whole-house STRs are banned).
        sig.append(("str_permit_lapsed", "FINANCIAL", 12))
    tr = r.get("tax_relief")
    if isinstance(tr, dict):
        if tr.get("kind") in ("elderly", "disabled", "blind"):
            # senior/disabled owner-occupant: equity-rich, motivated by health/
            # downsizing/estate transition.
            sig.append(("senior_exemption", "LIFE_EVENT", 8))
        elif tr.get("kind") == "use_value_deferral":
            # present-use deferral = rollback lien due on sale (equity + urgency).
            sig.append(("deferral_rollback", "FINANCIAL", 6))
    # legal
    if r.get("bankruptcy"):
        sig.append(("bankruptcy", "LEGAL", 18))
    if r.get("incarceration"):
        sig.append(("incarceration", "LEGAL", 8))  # low-conf name-only signal
    # life event
    if r.get("probate") or r.get("estate"):
        sig.append(("probate", "LIFE_EVENT", 20))
    # relationship-deed signals (probate / divorce / partition) tagged by
    # enrichment_relationship_deeds. Without this, in-place-tagged active
    # listings and ALL divorce signals never reached the score.
    rs = r.get("relationship_signal")
    if isinstance(rs, dict):
        kind = rs.get("kind")
        if kind == "probate":
            sig.append(("probate_deed", "LIFE_EVENT", 20))
        elif kind == "divorce":
            # zero-consideration quitclaim could be a gift, not a split — weaker
            kw = rs.get("keyword")
            w = 8 if kw == "zero_consideration_quitclaim" else 15
            sig.append(("divorce", "LIFE_EVENT", w))
        elif kind == "partition":
            # forced/judicial sale (usually already sold) — modest SALES signal
            sig.append(("partition", "SALES", 12))
    # property
    if r.get("code_enforcement") or r.get("condemned"):
        sig.append(("code_enforcement", "PROPERTY", 14))
    if r.get("distressed"):
        sig.append(("distressed_condition", "PROPERTY", 8))
    return sig


def _equity_band(li: Listing) -> Optional[str]:
    """Seller's REAL equity (ARV − payoff − liens), from enrichment_equity.
    Falls back to flip-ROI only when equity could not be computed."""
    raw = li.raw or {}
    pct = (raw.get("equity") or {}).get("pct")
    if pct is not None:
        if pct >= 0.40:
            return "high"
        if pct >= 0.15:
            return "med"
        return "low"   # includes underwater (negative pct)
    roi = (raw.get("calc") or {}).get("roi_pct")
    if roi is None:
        return None
    if roi >= 50:
        return "high"
    if roi >= 20:
        return "med"
    return "low"


def _parcel_key(li: Listing) -> str:
    import re
    if li.parcel_id and li.parcel_id.strip():
        return f"p:{li.state}:{re.sub(r'[^A-Za-z0-9]', '', li.parcel_id).lower()}"
    return f"id:{id(li)}"  # ungrouped


def _prior_price_index(previous_path: Optional[Path]) -> dict[str, float]:
    """Build {dedupe_key: prior list_price} from the previous run's snapshot.

    Reuses the same docs/listings.json snapshot enrichment_pulled_sales.py reads
    (the cross-run diff). We only need each prior listing's identity + list
    price, so this is a lightweight read — no full Listing hydration. Keyed by
    Listing.dedupe_key() so it matches the current run's listings exactly.
    """
    if previous_path is None:
        previous_path = Path("docs/listings.json")
    if not previous_path.exists():
        return {}
    try:
        data = json.loads(previous_path.read_text())
    except (ValueError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}

    from .models import ListingType, PropertyKind
    lt_map = {lt.value: lt for lt in ListingType}
    pk_map = {pk.value: pk for pk in PropertyKind}

    idx: dict[str, float] = {}
    for d in data:
        if not isinstance(d, dict):
            continue
        price = d.get("opening_bid")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        if not price or price <= 0:
            continue
        # Minimal Listing for a stable dedupe_key (same fields the key uses).
        try:
            li = Listing(
                source=d.get("source") or "prior",
                source_url=d.get("source_url") or "prior",
                listing_type=lt_map.get(d.get("listing_type") or "unknown", ListingType.UNKNOWN),
                property_kind=pk_map.get(d.get("property_kind") or "unknown", PropertyKind.UNKNOWN),
                street_address=d.get("street_address"),
                city=d.get("city"),
                state=d.get("state"),
                zip_code=d.get("zip_code"),
                county=d.get("county"),
                parcel_id=d.get("parcel_id"),
                case_number=d.get("case_number"),
            )
        except Exception:
            continue
        key = li.dedupe_key()
        # Keep the highest prior price on key collision — a real markdown should
        # measure against the listing's earlier (higher) ask, not a stale low.
        if key not in idx or price > idx[key]:
            idx[key] = price
    return idx


def score_board(listings: list[Listing], previous_path: Optional[Path] = None) -> dict:
    """Compute and attach raw['distress_stack'] to each listing. Returns a
    tier histogram.

    previous_path points at the prior run's docs/listings.json snapshot (same
    file enrichment_pulled_sales.py diffs). It powers the price_cut MLS signal
    by comparing each listing's list price against its prior-run ask. Defaults
    to docs/listings.json; pass a path (or a non-existent one) to control it."""
    # group by parcel
    groups: dict[str, list[Listing]] = {}
    for li in listings:
        groups.setdefault(_parcel_key(li), []).append(li)

    prior_prices = _prior_price_index(previous_path)

    hist = {"HOT": 0, "WARM": 0, "COLD": 0}
    for key, group in groups.items():
        # exclude sold/closed properties from active scoring
        active = [li for li in group if not (li.raw or {}).get("sold_confirmed")]
        if not active:
            for li in group:
                if isinstance(li.raw, dict):
                    li.raw.pop("distress_stack", None)
            continue
        # union signals across the parcel group
        by_cat: dict[str, list[tuple[str, int]]] = {}
        for li in active:
            prior_price = prior_prices.get(li.dedupe_key()) if prior_prices else None
            for name, cat, w in _signals_for(li, prior_price=prior_price):
                by_cat.setdefault(cat, []).append((name, w))
        categories = sorted(by_cat)
        stack = len(categories)  # distinct categories = the STACKED-N number
        # score: best weight per category (don't let 3 liens triple-count financial)
        score = sum(max(w for _, w in by_cat[c]) for c in by_cat)
        signals = sorted({name for c in by_cat for name, _ in by_cat[c]})

        # equity + contactability (best across the group)
        eq = next((b for li in active for b in [_equity_band(li)] if b in ("high", "med")), None) \
            or next((b for li in active for b in [_equity_band(li)] if b), None)
        absentee = any((li.raw or {}).get("owner_mailing", {}).get("absentee") for li in active)
        oos = any((li.raw or {}).get("owner_mailing", {}).get("out_of_state") for li in active)
        mailable = any((li.raw or {}).get("owner_mailing", {}).get("mailing") for li in active)
        if absentee:
            score += 8
        if oos:
            score += 4
        # Title-wipeout trap: a junior-lien / HOA / credit-union / individual
        # foreclosure where a senior bank mortgage likely SURVIVES the sale is a
        # bidding trap, not a clean acquisition — penalize it and keep it out of HOT.
        senior_survives = any(
            (li.raw or {}).get("title_risk", {}).get("surviving_senior_debt_risk")
            for li in active
        )
        if senior_survives:
            score -= 20

        eq_ok = eq in ("high", "med")
        if stack >= 2 and eq_ok and mailable and not senior_survives:
            tier = "HOT"
        elif stack >= 2 or (score >= 28 and eq_ok) or (absentee and stack >= 1 and score >= 20):
            tier = "WARM"
        else:
            tier = "COLD"

        ds = {"tier": tier, "stack": stack, "categories": categories,
              "signals": signals, "score": round(score),
              "equity_band": eq, "absentee": absentee, "out_of_state": oos,
              "contactable": mailable, "surviving_senior_debt_risk": senior_survives}
        for li in active:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["distress_stack"] = ds
        hist[tier] += 1
    return hist
