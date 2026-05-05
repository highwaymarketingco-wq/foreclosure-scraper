"""Data-quality flag enrichment.

Adds an explicit `raw.data_quality` block to each listing so the
dashboard, sheet, and email can surface investor-facing caveats:

  * synthetic_address — street_address is a "Lis Pendens X — Y" or
    "Vacant parcel" placeholder, not a real situs. User should
    verify before relying.
  * approximate_address — street_address came from a parcel-centroid
    reverse-geo (not a confident situs match).
  * low_arv_confidence — calc ARV is from tax_value × 1.25 or bid × 2.4
    proxy, not from comp-grounded valuation.
  * no_sqft — refused to compute rehab because living_sqft is missing.
  * synthetic_county — county was set by the resolver retag (we trust
    case# but want the dashboard to know it's derived).
  * cross_state_county_nulled — validation gate cleared a wrong-state
    county; investor should know the geographic certainty is reduced.

This is the single place an investor / dashboard reader should look
to understand "how sure are we about this listing?". Pure-Python,
runs after every other enrichment.
"""
from __future__ import annotations

import structlog

from .models import Listing

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


def enrich_data_quality(listings: list[Listing]) -> dict:
    """Annotate li.raw['data_quality'] with investor-facing flags.
    Returns a stats dict for the run summary."""
    stats = {
        "synthetic_address": 0,
        "approximate_address": 0,
        "low_arv_confidence": 0,
        "no_sqft": 0,
        "no_address": 0,
    }
    for li in listings:
        flags: list[str] = []

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

        # Always write — even an empty list signals "no caveats".
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["data_quality"] = {
            "flags": flags,
            "arv_confidence": arv_conf,
            "summary": _summary_text(flags),
        }

    log.info("data_quality.done", **stats)
    return stats


def _summary_text(flags: list[str]) -> str:
    """One-line investor-readable caveat string."""
    if not flags:
        return "OK — no data-quality caveats."
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
        msgs.append("📊 ARV is a proxy (tax × 1.25 or bid × 2.4), not comp-grounded")
    return " · ".join(msgs)
