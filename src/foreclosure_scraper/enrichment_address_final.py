"""Final-pass address synthesis — guarantees every listing has a meaningful
identifier in street_address. For listings still null after parcel + owner
lookups, synthesize from the best-available signal:

  - SC Public Index lis pendens: "Lis Pendens 2026-CP-04-00921 - Defendant Name"
  - NC eCourts lis pendens: "Lis Pendens [case#] - Defendant Name"
  - Henderson tax (no parcel match): "[Description text]"
  - national.distressed: try to extract from description; fallback to first
    address-shaped tokens
  - Newspapers: extract first address pattern from article text

The point: the dashboard should NEVER show "(address pending)" for a real
listing. Even when we can't get a physical address, we display the most
useful identifier — case#, parcel description, defendant name — so the
listing remains actionable.
"""
from __future__ import annotations

import re

import structlog

from .models import Listing

log = structlog.get_logger()


# The suffix must be a WHOLE word (fixed 2026-10-06). Without the word boundaries the greedy
# body ran to the last "st"/"dr"/"ct" inside any word, so notice text became a street address:
# "120 Having qualified as Executor of the Est(ate ...)" and "500 THE UNDERSIGNED having
# qualified as Executor for the est(ate)" on Column probate notices, "2026 Tax Sale Li(st)" on
# 397 Florence tax-sale rows. Every notice of one county then carried the same "address" with
# the same house number, and dedupe() (even with the 2026-10-06 identity rule) merged them: 76
# different Cabarrus decedents in one row, 121 in Johnston, on a replay of the 10/5 board.
# The street name between the number and the suffix is at most _MAX_STREET_NAME characters (also
# 2026-10-06): unbounded, the lazy body still ran from a file number to the first real suffix,
# "26SP000132-110 Under the power of sale in a Deed of Trust by ... located at 77 Hill St" became
# "110 Under the power ... 77 Hill St", and five different trustee notices whose text read alike
# merged under one such string. On the published board 99.3% of numbered street names are under
# 20 characters; the ones over 35 are notice text.
_MAX_STREET_NAME = 40
ADDR_RE = re.compile(
    r"(\b\d+\s+[A-Z][\w .'\-]{0,%d}?\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|" % _MAX_STREET_NAME +
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\b\.?)",
    re.I,
)


# OFFICE ADDRESSES (2026-10-06). A legal notice names other addresses than the property's: the
# court that holds the estate ("... file their claims ... with the Probate Court of FLORENCE
# County, The Honorable ..., the address of which is 181 N IRBY ST, STE 1300 FLORENCE SC 29501"),
# a clerk, the attorney or the personal representative claims go to. Taking the first address in
# the text, every Florence probate notice became '181 N IRBY ST'; the Florence parcel cache then
# resolved that to the county's own building, and dedupe() merged 11 different estates on it (the
# 10/5 checkpoint replay). An address is not the property's when either holds:
#   * the notice itself names it as an office: an office cue (_OFFICE_CUE: courthouse, clerk,
#     attorney, law firm, the undersigned, the executor / administrator / personal
#     representative, "the address of which is") stands in the same sentence or field within
#     _OFFICE_WINDOW characters before it, with no property cue (_PROPERTY_CUE) in between, or a
#     suite number follows it;
#   * it appears in the notices of _REPEAT_MIN or more different people (or cases) in one county
#     (_repeated_notice_addresses): a property is not in three unrelated estates' notices; a
#     courthouse or a law office is.
# enrich_with_address_synthesis() skips such an address, and removes it from a row that already
# carries it (with the parcel and the point that were derived from it), so the row is matched on
# its case number like any address-less notice.
# Deliberately NOT cues, each measured on the 10/5 replay rows: a bare "court" (an SC caption "IN
# THE COURT OF COMMON PLEAS" precedes a property-named LLC, "Gray Court" is a town, "Lamar Court" a
# complex) and "c/o" (a county roll's owner field, "SMITH JOHN C/O 14 HOLLYWOOD ST", is followed by
# the address the county has, 29 Spartanburg tax rows).
_OFFICE_CUE = re.compile(
    r"address\s+of\s+which\s+is|\bcourthouse\b|\bclerk\b|\battorneys?\b"
    r"|\blaw\s+(?:firm|offices?|group)\b|\bp\.?\s?l\.?\s?l\.?\s?c\b\.?|\bl\.?\s?l\.?\s?p\b\.?"
    r"|\besq(?:uire)?\b\.?|\bundersigned\b"
    r"|\b(?:co-?)?(?:executor|executrix|administrator|administratrix)s?\b"
    r"|\bpersonal\s+representatives?\b",
    re.I)
# "late of" is the decedent's own residence ("having qualified as Executor of the Estate of JANE
# DOE, late of 48 Oak Drive"), 6 Brunswick estate notices on the published board.
_PROPERTY_CUE = re.compile(
    r"\b(?:property|premises|real\s+estate|land|lot|parcel|located|known\s+as|commonly|residence"
    r"|dwelling|home|late\s+of|resid(?:ing|ed)\s+at)\b", re.I)
# A sentence end, or a field separator of a scraper-built description ("OWNER | ADDRESS | LEGAL").
_SENTENCE_BREAK = re.compile(r"(?:;|\||\.\s+(?=[A-Z][a-z]))")
_SUITE_AFTER = re.compile(r"\s*,?\s*(?:ste|suite)\b\.?\s*\w", re.I)
_OFFICE_WINDOW = 80
_REPEAT_MIN = 3


def office_address_at(text: str, start: int, end: int) -> bool:
    """The address at text[start:end] is an office the notice names, not the property (see OFFICE
    ADDRESSES above)."""
    if _SUITE_AFTER.match(text, end):
        return True
    before = text[max(0, start - _OFFICE_WINDOW):start]
    breaks = list(_SENTENCE_BREAK.finditer(before))
    if breaks:
        before = before[breaks[-1].end():]
    cues = list(_OFFICE_CUE.finditer(before))
    if not cues:
        return False
    return not _PROPERTY_CUE.search(before[cues[-1].end():])


def _norm_a(addr: str | None) -> str:
    return " ".join(str(addr or "").lower().replace(",", " ").split()).rstrip(".")


def _county_key(li: Listing, addr: str) -> tuple:
    return ((li.state or "").strip().upper(),
            (li.county or "").lower().replace(" county", "").strip(), _norm_a(addr))


def _notice_who(li: Listing) -> str | None:
    """Who a notice is about: the person (sorted name tokens, so 'DOE, JANE' = 'Jane Doe'), else its
    case number; None when it names neither (a row without either cannot show that two notices
    are UNRELATED: eight Terry Howe auction rows share one page's text)."""
    name = li.defendant or li.owner_name or ""
    toks = sorted(t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 1)
    if toks:
        return "p:" + " ".join(toks)
    if li.case_number:
        return "c:" + re.sub(r"[^a-z0-9]", "", li.case_number.lower())
    return None


def _repeated_notice_addresses(listings: list[Listing]) -> dict[tuple, int]:
    """(state, county, address) -> number of different people/cases whose notice text names that
    address, for the addresses named by _REPEAT_MIN or more people in as many DIFFERENT texts (one
    auction page listing nine lots is one text, however many rows it gave)."""
    who: dict[tuple, set] = {}
    texts: dict[tuple, set] = {}
    for li in listings:
        desc = li.description or ""
        if not desc:
            continue
        w = _notice_who(li)
        if w is None:
            continue
        t = hash(" ".join(desc.lower().split()))
        for m in ADDR_RE.finditer(desc):
            k = _county_key(li, m.group(1))
            who.setdefault(k, set()).add(w)
            texts.setdefault(k, set()).add(t)
    return {k: len(v) for k, v in who.items()
            if len(v) >= _REPEAT_MIN and len(texts[k]) >= _REPEAT_MIN}


def _property_address_in(li: Listing, desc: str, repeated: dict) -> str | None:
    """The first address in the notice text that is not an office (see OFFICE ADDRESSES)."""
    for m in ADDR_RE.finditer(desc):
        if office_address_at(desc, m.start(1), m.end(1)):
            continue
        if _county_key(li, m.group(1)) in repeated:
            continue
        return m.group(1).strip()
    return None


def _drop_office_address(li: Listing, repeated: dict) -> bool:
    """Remove a street address the row took from its own notice text when that address is an office
    (see OFFICE ADDRESSES), with what was derived from it: the parcel the parcel-cache resolver
    matched to it (raw['parcel_from_address'] gets withdrawn_parcel, so no resolver re-attaches it)
    and the row's point (geocoded from that address; an address-less notice has no point of its
    own). Recorded under raw['address_not_property']. A situs written from a parcel record
    (raw['situs_address_source']) is not from the notice and is left alone."""
    a = li.street_address
    raw = li.raw if isinstance(li.raw, dict) else {}
    if not a or not li.description or raw.get("situs_address_source"):
        return False
    na = _norm_a(a)
    desc = li.description
    for m in ADDR_RE.finditer(desc):
        if _norm_a(m.group(1)) != na:
            continue
        key = _county_key(li, a)
        if office_address_at(desc, m.start(1), m.end(1)):
            reason, n = "office_named_in_notice", None
        elif key in repeated:
            reason, n = "repeated_across_notices", repeated[key]
        else:
            continue
        rec = {"address": a, "reason": reason}
        if n:
            rec["notices"] = n
        pfa = raw.get("parcel_from_address")
        if (li.parcel_id and isinstance(pfa, dict) and pfa.get("matched_situs")
                and _norm_a(pfa["matched_situs"]) == na):
            pfa["withdrawn_parcel"] = li.parcel_id
            pfa["withdrawn_reason"] = "address_not_property"
            li.parcel_id = None
        if li.latitude is not None or li.longitude is not None:
            rec["point"] = [li.latitude, li.longitude]
            li.latitude = li.longitude = None
            if raw.get("geo_imprecise") == "census_geocode":
                raw.pop("geo_imprecise")
        raw["address_not_property"] = rec
        li.raw = raw
        li.street_address = None
        return True
    return False


def _synth_for_listing(li: Listing, repeated: dict | None = None) -> str | None:
    src = (li.source or "").lower()
    desc = li.description or ""
    case = li.case_number or ""
    defendant = (li.defendant or "").strip()

    # 2026-06-19: bankruptcy filings have NO property address. Never synthesize
    # one from the debtor name — doing so faked "Name — case#" into street_address
    # for 1,548 listings (misrepresentation). The debtor name lives in
    # li.defendant; the dashboard renders BK by name. Leave street_address empty.
    if "courtlistener_bankruptcy" in src:
        return None

    # Try to find an actual address pattern in the description first, skipping an office the
    # notice names (a court, an attorney; see OFFICE ADDRESSES)
    if desc:
        found = _property_address_in(li, desc, repeated or {})
        if found:
            return found

    # SC Public Index / NC eCourts lis pendens — synthesize from case#
    if "lis_pendens" in src or "ecourts" in src or "public_index" in src:
        if case and defendant:
            return f"Lis Pendens {case} — {defendant[:60]}"
        if case:
            return f"Lis Pendens {case}"

    # Newspapers / public_notices — use defendant + case if available
    if "newspaper" in src or "public_notices" in src:
        if defendant and case:
            return f"{defendant[:60]} — Case {case}"
        if defendant:
            return f"Notice of Sale — {defendant[:60]}"

    # National.distressed — usually has descriptive text
    if "distressed" in src:
        if defendant:
            return f"Land/Lot — {defendant[:60]}"
        # Use first 60 chars of description
        if desc:
            cleaned = re.sub(r"\s+", " ", desc[:80]).strip()
            return f"Property — {cleaned}"

    # Henderson tax (no GIS hit) — use raw description
    if "henderson_tax" in src or "tax" in src:
        if desc:
            cleaned = re.sub(r"\s+", " ", desc).strip()[:80]
            return f"Parcel — {cleaned}"

    # Generic last resort: defendant + case number
    if defendant and case:
        return f"{defendant[:60]} — {case}"
    if defendant:
        return defendant[:80]
    if case:
        return f"Case {case}"
    # Final-final: use county/state from the record so it's at least
    # geographically locatable
    county = (li.county or "").strip()
    state = (li.state or "").strip()
    if county or state:
        return f"Property in {county}{', ' if county and state else ''}{state}".strip()
    if desc:
        return desc[:80]

    return None


def enrich_with_address_synthesis(listings: list[Listing]) -> None:
    """Final synthesis pass. Mutates listings in place. An office address a row took from its
    notice text is removed first (see OFFICE ADDRESSES), and the row is synthesized again."""
    counts = {"already_set": 0, "synthesized": 0, "still_null": 0, "office_address_removed": 0}
    repeated = _repeated_notice_addresses(listings)
    for li in listings:
        if li.street_address:
            if not _drop_office_address(li, repeated):
                counts["already_set"] += 1
                continue
            counts["office_address_removed"] += 1
        synth = _synth_for_listing(li, repeated)
        if synth:
            li.street_address = synth
            counts["synthesized"] += 1
        else:
            counts["still_null"] += 1
    log.info("addr_synth.done", **counts)
