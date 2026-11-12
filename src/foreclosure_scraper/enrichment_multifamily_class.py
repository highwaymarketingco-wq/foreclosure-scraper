"""Multifamily foreclosure classifier — reclassify mislabeled apartment /
multi-unit distressed properties to property_kind=MULTI_FAMILY.

WHY THIS EXISTS
---------------
Apartment complexes, duplexes, and small unit-buildings DO get foreclosed and
they already flow through our existing sources (county master-in-equity sales,
nc_rod_substitute_trustee, nc_ecourts_lis_pendens, sc_tax_delinquent,
auction_dot_com, the national.distressed Realtor feed, Fannie HomePath REO,
etc.). But the generic property_kind backfill (enrichment_property_kind) only
catches a handful of description keywords and then defaults *everything* else
to single_family. As a result high-value multifamily distress gets buried as
single_family / unknown and never surfaces as the apartment-complex angle.

This enricher scans EVERY listing and promotes it to MULTI_FAMILY when a
strong, precise multifamily signal is present. It deliberately runs BEFORE
enrichment_property_kind in the chain so its decisions survive (property_kind
runs last and would otherwise have already forced UNKNOWN -> SINGLE_FAMILY,
which this enricher is still allowed to override — see _is_overridable).

PRECISION OVER RECALL
---------------------
A wrong MULTI_FAMILY tag pollutes the apartment angle, so we are conservative.
Signals are tiered by where they appear and what they say:

  TIER A (party / title / legal) — the *named foreclosed party* or legal
    description is a multifamily entity:
      "<Name> Apartments LLC", "Oakwood Apartment Homes LP",
      "<Name> Housing Partners", "Cedar Villas LLC", "<N> Unit Complex",
      "Townhomes LLC", "Multifamily ...".
    These are high-confidence: a business entity named "Apartments"/"Villas"/
    "Housing Partners" that is losing property is almost always a complex.

  TIER B (description) — the subject-property writeup states an actual
    multi-unit dwelling type or unit count:
      "duplex" / "triplex" / "fourplex" / "<N>-plex" (as the property, not a
        speculative "could be a duplex"),
      "<N> units" / "<N>-unit" with N>=2 (digit or spelled two..twelve),
      "apartment complex" / "apartment building" / "<N> unit building".

  TIER C (structure) — units field present (raw.units / raw.gis.units >= 2),
    OR multifamily zoning / land-use code (RM / RMF / R-6+ density / "multi"),
    OR very large living_sqft with no single-family confirmation.

FALSE-POSITIVE GUARDS (learned from the live data, see module tests)
  - "AC unit", "window units", "END UNIT", "new unit" -> appliance/condo,
    NOT dwelling units. We only count "unit(s)" when preceded by a count or
    "unit complex/building".
  - "separate apartment", "garage apartment", "in-law apartment",
    "basement apartment", "apartment over", "mother-in-law" -> accessory
    dwelling on an SFR, NOT multifamily.
  - "could be a duplex", "convert to a duplex", "additional duplex",
    "not ... a duplex", "potential duplex", zoning "allows a duplex",
    "townhomes/duplexes" in a land-development pitch -> speculative, NOT
    an actual multifamily structure.
  - "Apartment Complex across the street" / "near apartments" -> a neighbor
    landmark, NOT the subject. Guarded by a proximity/landmark negative.
  - Street name containing "Apartments" (e.g. "Hickory Creek Apartments") in
    an address -> place name; address text is NOT used as a party signal.
  - "<Name> Apartments ... Owners Association VS <Person>" -> the plaintiff is
    an apartment-CONDO HOA suing an individual unit owner; the subject is a
    single condo. Guarded by an HOA/association negative on the plaintiff and
    by never demoting an existing CONDO.

The enricher mutates listings in place, is idempotent, and records the winning
signal on raw["mf_signal"] = {"tier","matched","field","value"}.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()


# --------------------------------------------------------------------------
# Spelled-out small counts (apartment buildings are usually small N here).
# --------------------------------------------------------------------------
_NUMWORD = (
    r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"[2-9]|1[0-9]|[1-9][0-9]{1,2})"
)

# --------------------------------------------------------------------------
# TIER A — party / title / legal-description entity signals.
# These run against defendant, owner, title, case_name, legal_description.
# NOT against street_address (place names like "Hickory Creek Apartments").
# --------------------------------------------------------------------------
_PARTY_SIGNALS = (
    # "<...> Apartments" / "Apartment Homes" as an entity name (word, not
    # possessive landmark). Allow trailing LLC/LP/Inc/Ltd/Partners but don't
    # require it.
    (re.compile(r"\bapartment\s+homes\b", re.I), "apartment homes"),
    (re.compile(r"\bapartments?\b(?!\s+(?:condominium|condo)\b)", re.I), "apartments"),
    (re.compile(r"\bapartment\s+complex\b", re.I), "apartment complex"),
    (re.compile(r"\b" + _NUMWORD + r"\s*[-\s]?unit\s+complex\b", re.I), "unit complex"),
    (re.compile(r"\bunit\s+complex\b", re.I), "unit complex"),
    (re.compile(r"\bvillas?\b", re.I), "villas"),
    (re.compile(r"\bmanor\s+(?:apartments?|homes?)\b", re.I), "manor apartments"),
    (re.compile(r"\btownhomes?\s+(?:llc|lp|l\.?l\.?c\.?|partners)\b", re.I), "townhomes llc"),
    (re.compile(r"\bhousing\s+partners\b", re.I), "housing partners"),
    (re.compile(r"\bmulti[\s-]?family\b|\bmultifamily\b", re.I), "multifamily"),
)

# Plaintiff-side HOA/association negative: "<X> Apartments ... Owners
# Association" suing somebody is an HOA action on a single condo unit.
_HOA_ASSOC_RE = re.compile(
    r"\b(?:owners?\s+association|condominium|homeowners|h\.?o\.?a\.?|"
    r"property\s+owners|regime)\b",
    re.I,
)

# --------------------------------------------------------------------------
# TIER B — description: actual multi-unit DWELLING type / unit count.
# --------------------------------------------------------------------------
# Positive: plex types and explicit unit counts.
_DESC_PLEX_RE = re.compile(
    r"\b(?:duplex|triplex|tri-?plex|fourplex|four-?plex|quadplex|quad-?plex|"
    r"fiveplex|five-?plex|six-?plex|multiplex|" + _NUMWORD + r"-?plex)\b",
    re.I,
)
# "<N> units" / "<N>-unit" / "<N> unit building" — N>=2.
_DESC_UNITS_RE = re.compile(
    r"\b" + _NUMWORD + r"\s*(?:total\s+|residential\s+|rental\s+|income\s+)?"
    r"[-\s]?units?\b",
    re.I,
)
_DESC_UNIT_BLDG_RE = re.compile(
    r"\b(?:apartment\s+(?:complex|building)|" + _NUMWORD +
    r"\s*[-\s]?unit\s+(?:building|complex|apartment))\b",
    re.I,
)
# "income-producing / income generating ... duplex/units" reinforces actual.
# (handled implicitly — plex/units already match)

# Negative guards on description (speculative, accessory, appliance, landmark).
_DESC_NEGATIVES = (
    # appliance / HVAC "unit"
    re.compile(r"\b(?:a/?c|ac|hvac|heat\s*pump|window|wall|condenser|"
               r"furnace|new|separate|single)\s+units?\b", re.I),
    re.compile(r"\bunits?\s+(?:installed|downstairs|upstairs|replaced|"
               r"is\s+installed)\b", re.I),
    re.compile(r"\bend\s+unit\b", re.I),
)
# Speculative duplex/plex pitch — "could be / convert / potential / allows /
# accommodate / not ... a duplex" and land-development lists.
_SPEC_PLEX_RE = re.compile(
    r"(?:could\s+be|convert(?:ed|s)?\s+(?:to|into)|potential(?:ly)?|"
    r"possibilit|allows?|accommodate|additional|"
    r"not\s+(?:legally\s+)?(?:classified\s+as\s+)?"
    r"(?:a\s+)?|zoned?\s+for|build\s+a|add\s+a|future|ideal\s+for|"
    r"perfect\s+for|development[,:]?|townhomes?,?\s+duplex)"
    r"[^.!?]{0,60}?\b(?:duplex|triplex|fourplex|" + _NUMWORD + r"-?plex|units?)\b",
    re.I,
)
# "...duplex, etc." or "duplex etc" — an open-ended use-possibility list, not a
# statement that the property IS a duplex.
_SPEC_ETC_RE = re.compile(
    r"\b(?:duplex|triplex|fourplex|" + _NUMWORD + r"-?plex)\b[,\s]+etc\b", re.I
)
# A plex appearing inside a use-possibility list alongside other "could be"
# uses (single-family / vacation rental / guest quarters / Airbnb / office).
_SPEC_USELIST_RE = re.compile(
    r"\b(?:single[\s-]?family|vacation\s+rental|guest\s+quarters?|air\s?bnb|"
    r"short[\s-]?term\s+rental|home\s+office|in-?law)\b[^.!?]{0,40}?"
    r"\b(?:duplex|triplex|fourplex|" + _NUMWORD + r"-?plex)\b"
    r"|\b(?:duplex|triplex|fourplex|" + _NUMWORD + r"-?plex)\b[^.!?]{0,40}?"
    r"\b(?:single[\s-]?family|vacation\s+rental|guest\s+quarters?|air\s?bnb|"
    r"short[\s-]?term\s+rental)\b",
    re.I,
)
# Accessory-dwelling "apartment" on an SFR.
_ACCESSORY_APT_RE = re.compile(
    r"\b(?:separate|garage|basement|in-?law|mother-?in-?law|guest|"
    r"attached|above\s+the\s+garage|over\s+the\s+garage|bonus|finished)\s+"
    r"apartments?\b|\bapartments?\s+(?:over|above)\b",
    re.I,
)
# Landmark "apartment(s)" — a neighboring complex, not the subject.
_LANDMARK_APT_RE = re.compile(
    r"\bapartment\s+complex\s+across\b|\b(?:near|next\s+to|adjacent\s+to|"
    r"close\s+to|walk(?:able)?\s+to|beside)\s+(?:the\s+)?apartments?\b|"
    r"\bnew\s+apartment\s+complex\b",
    re.I,
)
# Bare "apartment" (singular, not "apartments"/"apartment complex/building")
# in a description is almost always accessory/landmark — require the complex/
# building/plural form there. Handled by only matching _DESC_UNIT_BLDG_RE /
# plurals below.
_DESC_APT_POSITIVE_RE = re.compile(
    r"\bapartment\s+(?:complex|building|homes)\b|\bapartments\b", re.I
)

# --------------------------------------------------------------------------
# TIER C — structure / zoning / units field.
# --------------------------------------------------------------------------
# Multifamily zoning codes. Conservative: RM/RMF/MF/MR/"multi", or high-density
# residential R-6..R-99 (R-1..R-5 are single-family/low density -> excluded).
_MF_ZONING_RE = re.compile(
    r"^(?:rm\b|rmf\b|mf\b|mr\b|r-?m\b|r-?6\b|r-?[6-9]\b|r-?[1-9][0-9]\b|"
    r"hdr\b|mdr\b)|multi", re.I
)
# But many R-8/R-10/R-25 in this dataset are SFR min-lot codes, so zoning alone
# is treated as WEAK and only used to corroborate (never sole signal) — see
# _classify_structure.

_LARGE_SQFT_THRESHOLD = 9000.0  # luxury mountain SFRs run 6-9k here; bar set high


def _gather_party_text(li: Listing) -> str:
    """Concatenate the party/title/legal fields (NOT address)."""
    parts: list[str] = []
    for f in ("defendant", "legal_description"):
        v = getattr(li, f, None)
        if v:
            parts.append(str(v))
    raw = li.raw if isinstance(li.raw, dict) else {}
    for k in ("owner", "title", "case_name", "case_title", "name", "owner_name"):
        v = raw.get(k)
        if v:
            parts.append(str(v))
    return " || ".join(parts)


def _plaintiff_text(li: Listing) -> str:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return " ".join(
        str(x) for x in (getattr(li, "plaintiff", None), raw.get("plaintiff")) if x
    )


def _classify_party(li: Listing) -> Optional[tuple[str, str, str, str]]:
    """TIER A. Return (tier, matched, field, value) or None."""
    text = _gather_party_text(li)
    if not text:
        return None
    plaintiff = _plaintiff_text(li)
    for rx, label in _PARTY_SIGNALS:
        m = rx.search(text)
        if not m:
            continue
        # Guard: apartment-as-place-name inside an address that leaked into the
        # legal/defendant blob ("... Hickory Creek Apartments, Shelby, ...").
        # If the only signal is bare "apartments" and the surrounding text is a
        # comma-delimited postal-style address, skip.
        if label == "apartments":
            window = text[max(0, m.start() - 30): m.end() + 30]
            if re.search(r",\s*[\w\s]+,\s*(?:north|south)\s+carolina|"
                         r"\b\d{5}\b", window, re.I):
                continue
            # HOA / condo-association apartment plaintiff suing an owner ->
            # single condo, not a complex.
            if _HOA_ASSOC_RE.search(text) or _HOA_ASSOC_RE.search(plaintiff):
                continue
        return ("party", m.group(0).strip(), "defendant/owner/title", label)
    return None


def _classify_description(li: Listing) -> Optional[tuple[str, str, str, str]]:
    """TIER B. Return (tier, matched, field, value) or None."""
    desc = " ".join(
        str(x) for x in (
            getattr(li, "description", None),
            (li.raw or {}).get("zillow", {}).get("description")
            if isinstance(li.raw, dict) and isinstance(li.raw.get("zillow"), dict)
            else None,
        ) if x
    )
    if not desc:
        return None

    # plex / unit-building positive
    plex = _DESC_PLEX_RE.search(desc)
    unit_bldg = _DESC_UNIT_BLDG_RE.search(desc)
    apt_pos = _DESC_APT_POSITIVE_RE.search(desc)
    units = _DESC_UNITS_RE.search(desc)

    candidate = plex or unit_bldg or apt_pos or units
    if not candidate:
        return None

    # Landmark / accessory guard for apartment evidence. If the ONLY apartment
    # signal is a landmark ("New Apartment Complex across the Street", "close to
    # apartments") or an accessory dwelling ("garage apartment", "separate
    # apartment"), drop the apartment evidence entirely. This must run even when
    # _DESC_UNIT_BLDG_RE / _DESC_APT_POSITIVE_RE matched the SAME landmark
    # phrase ("apartment complex" inside "New Apartment Complex across the
    # Street"), so we neutralize apt_pos/unit_bldg before deciding.
    apt_is_landmark_or_accessory = (
        (apt_pos or unit_bldg)
        and (_LANDMARK_APT_RE.search(desc) or _ACCESSORY_APT_RE.search(desc))
    )
    if apt_is_landmark_or_accessory:
        # Is there an apartment positive that is NOT the landmark/accessory one?
        # Cheap check: a real "apartment complex/building" that isn't preceded
        # by "new" and isn't "across/near/next to". If none, neutralize.
        real_apt = re.search(
            r"(?<!new\s)\bapartment\s+(?:building|complex)\b(?!\s+(?:across|near|"
            r"next|beside|adjacent))",
            desc, re.I,
        )
        if not real_apt:
            apt_pos = None
            unit_bldg = None

    # Re-derive candidate after neutralizing landmark/accessory apartment ev.
    candidate = plex or unit_bldg or apt_pos or units
    if not candidate:
        return None

    # Speculative guard for plex/units candidates. Covers "could be a duplex",
    # "duplex, etc.", and use-possibility lists ("single family ... or a
    # duplex"). Skip only if there's no independent strong positive (a real
    # apartment complex/building or unit building).
    if plex or units:
        speculative = (
            _SPEC_PLEX_RE.search(desc)
            or _SPEC_ETC_RE.search(desc)
            or _SPEC_USELIST_RE.search(desc)
        )
        if speculative and not (unit_bldg or apt_pos):
            return None

    # Appliance/HVAC "unit(s)" guard for unit candidates.
    if units and not (plex or unit_bldg or apt_pos):
        # Re-check: is the unit match an appliance/end-unit hit rather than a
        # dwelling-count? Verify the matched number is >= 2 AND the immediate
        # context isn't an appliance negative.
        for neg in _DESC_NEGATIVES:
            if neg.search(desc):
                # If an appliance negative exists, require an independent
                # dwelling-count match elsewhere (count word directly before
                # "units" not preceded by appliance keywords).
                strict = re.search(
                    r"(?<!a/c )(?<!ac )(?<!hvac )(?<!window )(?<!new )"
                    r"\b" + _NUMWORD + r"\s+(?:total\s+|residential\s+|rental\s+|"
                    r"income\s+)?units?\b",
                    desc, re.I,
                )
                if not strict:
                    return None
                break

    matched = (candidate.group(0)).strip()
    return ("description", matched, "description", matched.lower())


def _classify_structure(li: Listing) -> Optional[tuple[str, str, str, str]]:
    """TIER C. units field, MF zoning (corroborated), or very-large sqft."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Explicit units field (raw.units or raw.gis.units), >= 2.
    for path, val in (
        ("raw.units", raw.get("units")),
        ("raw.gis.units", (raw.get("gis") or {}).get("units")
            if isinstance(raw.get("gis"), dict) else None),
        ("raw.num_units", raw.get("num_units")),
    ):
        try:
            n = int(float(val)) if val is not None and str(val).strip() else 0
        except (TypeError, ValueError):
            n = 0
        if n >= 2:
            return ("structure", f"{n} units", path, str(n))

    # MF zoning — WEAK; only accept when corroborated by a multi-ish hint or
    # large sqft, since R-8/R-10/R-25 here are SFR min-lot codes.
    z = (li.zoning or "").strip()
    if z and _MF_ZONING_RE.match(z):
        # require "multi"/RM/RMF/MF/MR explicitly; bare high-density R-N is too
        # noisy in this footprint -> skip unless it's an explicit MF token.
        if re.match(r"^(?:rm\b|rmf\b|mf\b|mr\b|r-?m\b|hdr\b|mdr\b)|multi", z, re.I):
            return ("structure", z, "zoning", z)

    # Very large living_sqft with NO single-family confirmation. Deliberately
    # strict: large luxury SFRs (6-9k sqft mountain homes) are common in this
    # footprint, so bare sqft is a weak signal. We only fire when the listing
    # reads like a non-house: a real (non-estimated) sqft over the high bar AND
    # no bedroom/bathroom data AND no house-like description AND not land/comm  -
    # ercial/condo/townhouse. In practice this almost never triggers (by design)
    # — the durable MF signals are party-name and description.
    sqft = li.living_sqft or 0
    desc = (li.description or "").lower()
    house_words = re.search(
        r"\b(?:home|house|residence|bedroom|cottage|cabin|ranch|"
        r"bungalow|estate)\b", desc
    )
    if (sqft and sqft >= _LARGE_SQFT_THRESHOLD
            and not li.living_sqft_estimated
            and not li.bedrooms and not li.bathrooms
            and not house_words
            and li.property_kind not in (
                PropertyKind.LAND, PropertyKind.COMMERCIAL,
                PropertyKind.CONDO, PropertyKind.TOWNHOUSE)):
        return ("structure", f"{int(sqft)} sqft", "living_sqft", str(int(sqft)))

    return None


# Existing kinds we are willing to OVERRIDE with a strong MF signal. We never
# demote a CONDO (a condo apartment-association suit is a single unit), and we
# never touch an existing MULTI_FAMILY (idempotent — already correct).
_OVERRIDABLE = {
    PropertyKind.UNKNOWN,
    PropertyKind.SINGLE_FAMILY,
    PropertyKind.TOWNHOUSE,  # "townhomes LLC" complex can land here
    PropertyKind.MIXED,
    None,
}


def _is_overridable(li: Listing) -> bool:
    return li.property_kind in _OVERRIDABLE


def classify_multifamily(li: Listing) -> Optional[tuple[str, str, str, str]]:
    """Return the winning (tier, matched, field, value) signal, or None.

    Tier order: party (A) > description (B) > structure (C).
    """
    return (
        _classify_party(li)
        or _classify_description(li)
        or _classify_structure(li)
    )


def enrich_multifamily_class(listings: list[Listing]) -> dict:
    """Promote listings with strong multifamily signals to MULTI_FAMILY.

    Mutates in place. Idempotent. Returns a stats dict (also logged).
    """
    stats = {
        "scanned": 0,
        "reclassified": 0,
        "already_mf": 0,
        "by_tier": {"party": 0, "description": 0, "structure": 0},
        "from_kind": {},
        "skipped_not_overridable": 0,
        "examples": [],          # up to 12 caught (defendant/title strings)
        "skipped_examples": [],  # up to 8 deliberately skipped
        "exceptions": 0,
    }
    if not listings:
        return stats

    for li in listings:
        stats["scanned"] += 1
        try:
            if li.property_kind == PropertyKind.MULTI_FAMILY:
                stats["already_mf"] += 1
                continue

            signal = classify_multifamily(li)
            if not signal:
                continue

            tier, matched, field, value = signal

            if not _is_overridable(li):
                stats["skipped_not_overridable"] += 1
                if len(stats["skipped_examples"]) < 8:
                    stats["skipped_examples"].append({
                        "current_kind": getattr(li.property_kind, "value",
                                                str(li.property_kind)),
                        "would_match": matched,
                        "field": field,
                        "source": li.source,
                    })
                continue

            prior = getattr(li.property_kind, "value", str(li.property_kind))
            li.property_kind = PropertyKind.MULTI_FAMILY
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["mf_signal"] = {
                "tier": tier, "matched": matched, "field": field, "value": value,
            }

            stats["reclassified"] += 1
            stats["by_tier"][tier] += 1
            stats["from_kind"][prior] = stats["from_kind"].get(prior, 0) + 1
            if len(stats["examples"]) < 12:
                stats["examples"].append({
                    "tier": tier,
                    "matched": matched,
                    "field": field,
                    "from": prior,
                    "source": li.source,
                    "context": (
                        (li.defendant or _gather_party_text(li) or
                         (li.description or ""))[:90]
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            stats["exceptions"] += 1
            log.warning(
                "multifamily_class.per_listing_failed",
                source=getattr(li, "source", None), error=str(exc),
            )

    log.info(
        "multifamily_class.done",
        scanned=stats["scanned"],
        reclassified=stats["reclassified"],
        by_tier=stats["by_tier"],
        from_kind=stats["from_kind"],
        skipped_not_overridable=stats["skipped_not_overridable"],
        exceptions=stats["exceptions"],
    )
    return stats
