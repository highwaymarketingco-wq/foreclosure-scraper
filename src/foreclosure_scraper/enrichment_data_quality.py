"""Data-quality flag enrichment.

Adds an explicit `raw.data_quality` block to each listing so the
dashboard, sheet, and email can surface investor-facing caveats:

  * synthetic_address — street_address is a "Lis Pendens X — Y" or
    "Vacant parcel" placeholder, not a real situs. User should
    verify before relying.
  * approximate_address — street_address came from a parcel-centroid
    reverse-geo (not a confident situs match).
  * low_arv_confidence — calc ARV is a proxy (a multiplier on an anchor
    figure) rather than a comp-grounded valuation. The multiplier is NOT
    fixed — improved rows use bid × 2.4, land rows bid × 1.5, and the
    assessed-value tiers use × 1.25 / × 1.10 — so the caption reads the
    real factor back out of the calc note instead of naming one.
  * no_sqft — refused to compute rehab because living_sqft is missing.
  * synthetic_county — county was set by the resolver retag (we trust
    case# but want the dashboard to know it's derived).
  * cross_state_county_nulled — validation gate cleared a wrong-state
    county; investor should know the geographic certainty is reduced.
  * arv_unreliable / arv_bid_and_roi_withheld / arv_no_independent_check
    — the ARV trust gate's verdict, see the block below.
  * arv_not_computed — there is no raw['calc'] on this lead at all, so
    nothing was valued. Distinct from arv_withheld (calc ran and refused
    to publish) and from a clean run (calc ran and published).

This is the single place an investor / dashboard reader should look
to understand "how sure are we about this listing?". Pure-Python,
runs after every other enrichment.

ORDERING — THIS MUST RUN AFTER THE VALUATION
--------------------------------------------
Everything this module says about an ARV is read out of `raw['calc']`, so it
has to run after the LAST thing that writes that block: the calc/grade loop,
any assessor-card or RentCast re-grade after it. Run earlier and it captions
the board off the previous run's valuation — measured on the live 38,500-lead
board, main.py's old position emitted arv_unreliable / arv_bid_and_roi_withheld
/ arv_sanity_flag / arv_no_independent_check 0/0/0/0 times against
3,049/3,049/20,443/16,310 from the correct position. A stale caveat is worse
than no caveat: it is a clean bill of health signed for a number that has since
been flagged. tests/test_enrichment_order.py fails any publisher that runs this
before its valuation.

ARV TRUST — TWO JOBS HERE
-------------------------
1. ENFORCE. `valuation.grading.gate_calc_dict` is re-applied to the serialized
   `raw['calc']`. On a normal run this is a no-op: `grading.grade()` already
   gated the Calc object before it was serialized. It earns its place on the
   cases where that did not happen — a board carried over from a run that
   predates the gate, and any future writer that serializes a Calc without
   calling grade(). Both flag sets and both field lists are imported from
   grading, never re-listed here: a reader/writer name split is precisely what
   let `geo_imprecise_comps` and `bid_proxy_arv` reach the dashboard unwarned.

2. CAPTION. Turn that verdict into words the operator actually sees:
     arv_unreliable            contradicted — dollars AND verdict withheld
     arv_bid_and_roi_withheld  names the consequence in the flag itself
     arv_no_independent_check  weak evidence — dollars kept, verdict withheld

   The two CONTRADICTED names are deliberately ones the dashboard's existing
   arvTrust() already escalates (`arv_unreliable` is a literal member of its
   `_ARV_BAD_FLAGS`; `arv_bid_and_roi_withheld` matches its "arv"+verdict-word
   shape rule), so the loud warning renders with no front-end change. They cover
   ~7.5% of the board.

   The WEAK name deliberately does NOT escalate. It covers ~50% of the board
   once `anchor_not_independent` is counted, and dashboard.js's own note is
   right that "a red flag on two rows in three is wallpaper, which is part of
   how the real one stayed invisible" — drowning the 7.5% would be a net loss of
   safety. That tier is captioned three quieter ways instead: this flag, the
   `data_quality.summary` prose below, and the sentence
   valuation.grading.apply_arv_trust_gate appends to `calc.notes` (which the
   detail panel renders in full). Its verdict is also simply GONE, which is a
   visible absence rather than a silent claim.

   `data_quality.summary` is the CSV's `data_quality_note` column and is in the
   slim allowlist, so it reaches every surface including the phone.
"""
from __future__ import annotations

import re

import structlog

from .models import Listing
from .valuation.grading import gate_calc_dict

log = structlog.get_logger()


_SYNTHETIC_PREFIXES = (
    "Lis Pendens ",
    "Vacant parcel",
    "Bk Property",
    "Tax Sale ",
    "Tax Lien ",
    "Bankruptcy ",
    "Property in ",
)


#: Summary shown when no check raised a caveat.
#:
#: Deliberately NOT "OK". This string used to be dead — it only reached the CSV —
#: and round three of the ARV work put it on screen, which turned it into an
#: affirmative claim sitting beside a max bid on ~1,730 leads, ~640 of them
#: bidding over $250,000. "OK" reads as "this valuation was verified"; nothing
#: in this module verifies a valuation, it only reports that no check raised a
#: caveat. Those are different statements and the difference is someone's money.
#:
#: Tests import this rather than repeating the prose, so rewording it stays a
#: one-line change instead of a red suite.
NO_CAVEATS_SUMMARY = (
    "No caveats raised — the checks found nothing to flag, "
    "which is not the same as verified."
)


def _is_synthetic_address(li: Listing) -> bool:
    sa = (li.street_address or "").strip()
    if not sa:
        return False
    return any(sa.startswith(p) for p in _SYNTHETIC_PREFIXES)


def _is_approximate_address(li: Listing) -> bool:
    """A parcel-only resolution wrote a reverse-geo approximate but did
    NOT overwrite street_address. If street_address is real AND the
    raw blob has parcel_resolution.reverse_geo_approx that DIFFERS from
    street_address, the address might be approximate."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    pr = raw.get("parcel_resolution") or {}
    return bool(pr.get("reverse_geo_approx")) and _is_synthetic_address(li)


def _arv_confidence(li: Listing) -> str | None:
    """Pull out the calc's ARV confidence ('HIGH'/'MEDIUM'/'LOW') if present."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    # Authoritative: the confidence the valuation engine actually assigned.
    conf = calc.get("arv_confidence")
    if conf:
        return str(conf).upper()
    # Fallback heuristic for legacy records that predate persisted confidence.
    notes = calc.get("notes") or []
    # Look at the first note — that's where the ARV-source line goes.
    first = notes[0] if notes else ""
    if "comps × subject sqft" in first or "land comps" in first:
        return "HIGH"
    if "Zestimate" in first:
        return "MEDIUM"
    if "tax-assessed" in first or "× 1.25" in first or "× 1.10" in first:
        return "LOW"
    if "× 2.4" in first or "× 1.5" in first:
        return "LOW"
    return None


# The ARV-source note carries the multiplier that was actually used. Read it
# back rather than restating one, because there is no single proxy factor:
# improved rows are bid × 2.4, land rows bid × 1.5, and the assessed-value
# tiers are × 1.25 / × 1.10. Hard-coding "bid × 2.4" told the reader of a land
# lead the wrong arithmetic on a number they are about to bid against.
_BID_PROXY_MULT_RE = re.compile(
    r"proxy from bid\s*[×x*]\s*([0-9]+(?:\.[0-9]+)?)", re.I
)
# CLOSED vocabulary, deliberately not `ARV from (.+?) × (N)`. The wildcard
# version matched "ARV from 2 land comps × 0.88 ac" and read the ACREAGE as the
# proxy multiplier — captioning 3,948 comp-grounded ARVs as proxies, and
# printing "× 0.88" as if it were the factor. Only these four labels name an
# anchor figure a proxy tier multiplies (see _anchor_value in valuation/calc).
_ANCHOR_MULT_RE = re.compile(
    r"ARV from (county market value|assessor appraised value|tax-assessed value"
    r"|tax-assessed)\s*[×x*]\s*([0-9]+(?:\.[0-9]+)?)",
    re.I,
)
# Tier notes are appended in tier order, so a REFUSED tier's note can sit ahead
# of the tier that actually produced the ARV. Naming the refused arithmetic
# would be the same defect wearing a different number.
_REFUSAL_WORDS = ("WITHHELD", "exceeds the", "refused", "Insufficient")

# Flags whose own message already states what happened to the ARV. When one of
# these is present the low-confidence line must not restate it.
_ARV_STATUS_FLAGS = (
    "arv_not_computed",
    "arv_withheld",
    "arv_bid_and_roi_withheld",
    "arv_no_independent_check",
)


def _arv_proxy_basis(li: Listing) -> str | None:
    """Name the arithmetic behind a LOW-confidence proxy ARV, e.g.
    'the opening bid × 1.5' or 'tax-assessed × 1.25'. None when no tier note
    survived, in which case the caller must fall back to multiplier-free
    wording rather than guessing a factor."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    notes = calc.get("notes") or []
    for n in notes:
        if not isinstance(n, str) or any(w in n for w in _REFUSAL_WORDS):
            continue
        m = _BID_PROXY_MULT_RE.search(n)
        if m:
            return f"the opening bid × {m.group(1)}"
        m = _ANCHOR_MULT_RE.search(n)
        if m:
            return f"{m.group(1).strip()} × {m.group(2)}"
    return None


def enrich_data_quality(listings: list[Listing]) -> dict:
    """Annotate li.raw['data_quality'] with investor-facing flags.
    Returns a stats dict for the run summary."""
    stats = {
        "synthetic_address": 0,
        "approximate_address": 0,
        "low_arv_confidence": 0,
        "no_sqft": 0,
        "sqft_estimated": 0,
        "arv_outlier": 0,
        "no_address": 0,
        "exceptions": 0,
    }
    for li in listings:
        try:
            flags: list[str] = []
            raw = li.raw if isinstance(li.raw, dict) else {}

            # ARV trust gate, re-applied to the serialized block. Mutates
            # raw['calc'] in place (deletes the fields the ARV cannot support).
            # Runs FIRST so every read below sees the gated numbers.
            #
            # NOT `gate_calc_dict(calc) if calc else "ok"`. An absent raw['calc']
            # is not an OK valuation, it is a MISSING one, and that short-circuit
            # gave the two cases the same answer: a lead nobody had priced fell
            # through every ARV branch below and `summary` printed "OK — no
            # data-quality caveats." over it. That is what a brand-new lead
            # published on its first appearance, because until this enrichment
            # was moved after the valuation there was no raw['calc'] to read.
            # gate_calc_dict handles a non-dict and an empty dict itself (it
            # returns "ok" — correctly, there is nothing to withhold), so the
            # absence is recorded explicitly as `arv_not_computed` below rather
            # than inferred from a trust level that cannot express it.
            _rc = raw.get("calc")
            calc = _rc if isinstance(_rc, dict) else {}
            calc_missing = not calc
            trust = gate_calc_dict(calc)

            if _is_synthetic_address(li):
                flags.append("synthetic_address")
                stats["synthetic_address"] += 1
            elif not (li.street_address or "").strip():
                flags.append("no_address")
                stats["no_address"] += 1

            if _is_approximate_address(li):
                flags.append("approximate_address")
                stats["approximate_address"] += 1

            if not li.living_sqft and (li.property_kind and li.property_kind.value != "land"):
                flags.append("no_sqft")
                stats["no_sqft"] += 1

            arv_conf = _arv_confidence(li)
            if arv_conf == "LOW":
                flags.append("low_arv_confidence")
                stats["low_arv_confidence"] += 1

            # Footprint-derived sqft is an ESTIMATE — surface it so the comp-based
            # ARV is never mistaken for one built on true GLA.
            fp = raw.get("footprint")
            if isinstance(fp, dict) and fp.get("estimated"):
                flags.append("sqft_estimated")
                stats["sqft_estimated"] += 1

            # Outlier guard: an ARV that is implausibly large or tiny is not
            # bankable — flag it for manual verification.
            #
            # The `not has_comps` gate used to make this structurally blind to the
            # single largest source of bad ARVs on the board. A row raised by the
            # ARV floor HAS comps by definition (that's what the floor overrode),
            # so every one of the 7,118 floored leads — including the $780,300
            # manufactured home — was excluded from the only outlier check an
            # investor ever sees. Comps now lift the threshold rather than skip
            # the test.
            arv = calc.get("arv_expected")
            has_comps = bool(raw.get("comp_median_ppsf") or raw.get("comp_median_ppsf_recorded"))
            if arv and arv_conf in ("LOW", "MEDIUM"):
                big = 2_000_000 if has_comps else 1_500_000
                if arv > big or (arv < 15_000 and li.living_sqft):
                    flags.append("arv_outlier")
                    stats["arv_outlier"] += 1

            # No valuation block at all. On today's board this is 0 leads
            # (measured: 38,500/38,500 carry a calc), so it adds no wallpaper —
            # it exists so the absence can never again be reported as health.
            # Deliberately QUIET at the front end: `arv_not_computed` matches
            # neither dashboard.js's _ARV_BAD_FLAGS nor its "arv"+verdict-word
            # rule, which is right, because a lead with no calc publishes no ARV,
            # no max bid and no ROI — there is no number on screen to distrust,
            # only an absence to name.
            if calc_missing:
                flags.append("arv_not_computed")
                stats["arv_not_computed"] = stats.get("arv_not_computed", 0) + 1

            # valuation/calc.py's own sanity verdict, surfaced verbatim so the
            # caveat a reader sees is the same one the engine reached.
            sanity = calc.get("arv_flags")
            if isinstance(sanity, list) and sanity:
                flags.append("arv_sanity_flag")
                stats["arv_sanity_flag"] = stats.get("arv_sanity_flag", 0) + 1
            if calc.get("arv_withheld") is not None:
                flags.append("arv_withheld")
                stats["arv_withheld"] = stats.get("arv_withheld", 0) + 1

            # The trust verdict, in names the dashboard already understands.
            # `arv_sanity_flag` above says "a flag exists"; these say what it
            # COST — and unlike arv_sanity_flag they trip the front end's
            # existing warning treatment, which is the difference between a
            # caveat and a caveat nobody sees.
            if trust == "contradicted":
                flags.append("arv_unreliable")
                flags.append("arv_bid_and_roi_withheld")
                stats["arv_contradicted"] = stats.get("arv_contradicted", 0) + 1
            elif trust == "weak":
                flags.append("arv_no_independent_check")
                stats["arv_weak_evidence"] = stats.get("arv_weak_evidence", 0) + 1

            # Always write — even an empty list signals "no caveats".
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["data_quality"] = {
                "flags": flags,
                "arv_confidence": arv_conf,
                "summary": _summary_text(
                    flags,
                    sanity if isinstance(sanity, list) else None,
                    _arv_proxy_basis(li) if arv_conf == "LOW" else None,
                    (raw.get("calc") or {}).get("arv_expected") is not None,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            stats["exceptions"] += 1
            log.warning(
                "data_quality.per_listing_failed",
                source=getattr(li, "source", None),
                error=str(exc),
            )

    log.info("data_quality.done", **stats)
    return stats


def _summary_text(
    flags: list[str],
    arv_flags: list[str] | None = None,
    arv_proxy_basis: str | None = None,
    arv_published: bool = True,
) -> str:
    """One-line investor-readable caveat string.

    `arv_flags` is calc's own flag list; when present the ARV caveats name the
    actual reason ("comp_kind_mismatch") instead of only the severity, because
    the operator's next action differs completely between "the assessor row is
    a warehouse" and "the comps came from a city centroid".

    `arv_proxy_basis` is the proxy arithmetic THIS lead actually used, read back
    from the calc note by `_arv_proxy_basis`. None means no proxy tier produced
    this ARV, and the caption must then NOT claim proxy arithmetic at all.

    `arv_published` says whether a value actually reached the board. A LOW
    confidence with no ARV is 12,751 of the LOW cohort; describing the
    arithmetic behind a number that was never published is the same defect as
    describing it with the wrong multiplier.
    """
    if not flags:
        return NO_CAVEATS_SUMMARY
    why = (" [" + ", ".join(sorted(arv_flags)) + "]") if arv_flags else ""
    msgs = []
    if "synthetic_address" in flags:
        msgs.append("⚠️ address is a placeholder (case # / parcel ID, not a real situs)")
    if "approximate_address" in flags:
        msgs.append("📍 address is approximate (parcel-centroid reverse-geo)")
    if "no_address" in flags:
        msgs.append("⚠️ no address resolved")
    if "no_sqft" in flags:
        msgs.append("⚠️ rehab/ARV unreliable — sqft missing")
    if "low_arv_confidence" in flags:
        if arv_proxy_basis:
            msgs.append(f"📊 ARV is a proxy ({arv_proxy_basis}), not comp-grounded")
        elif arv_published:
            # LOW but comp-grounded (3,948 leads) or from a recorded-sales /
            # HPI-rescale tier. "not comp-grounded" was simply false on these.
            msgs.append("📊 ARV confidence is LOW — treat the value as indicative; "
                        "see the valuation notes for how it was derived")
        elif not any(f in flags for f in _ARV_STATUS_FLAGS):
            # No ARV reached the board and nothing else says so. Dropping the
            # (false) proxy sentence here without replacing it left 1,284 leads
            # printing "no caveats" — a harder failure than the wrong
            # multiplier, because it reads as a clean valuation.
            msgs.append("📊 no ARV was derived — the valuation ran and published "
                        "no value, so there is nothing to price against")
        # else: arv_not_computed / arv_withheld / arv_bid_and_roi_withheld /
        # arv_no_independent_check already state the ARV's status in full.
    if "sqft_estimated" in flags:
        msgs.append("📐 living sqft is an ESTIMATE (building footprint × stories, ~2019)")
    if "arv_outlier" in flags:
        msgs.append("⚠️ ARV outlier — implausible magnitude; verify before bidding")
    if "arv_not_computed" in flags:
        msgs.append("⚠️ NOT VALUED — this lead has no valuation block, so there is no ARV, "
                    "max bid, ROI or deal verdict. Absence, not a zero")
    if "arv_withheld" in flags:
        msgs.append("🚫 ARV WITHHELD — the computed value failed a sanity check and is "
                    "not published; max bid / ROI are blank on purpose" + why)
    elif "arv_bid_and_roi_withheld" in flags:
        msgs.append("🚫 ARV CONTRADICTED — another record (or the arithmetic itself) "
                    "disputes this value, so max bid, ROI, profit and the deal verdict "
                    "are withheld on purpose. The ARV is still shown so you can see the "
                    "disagreement; verify the parcel before bidding" + why)
    elif "arv_no_independent_check" in flags:
        msgs.append("⚠️ ARV UNVERIFIED — nothing independent confirms this value describes "
                    "this property, so no deal verdict is published. Max bid and ROI are "
                    "shown as a band, not a number" + why)
    elif "arv_sanity_flag" in flags:
        msgs.append("⚠️ ARV flagged — see calc.arv_flags; treat the value as unverified" + why)
    return " · ".join(msgs)
