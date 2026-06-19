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


ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)


def _synth_for_listing(li: Listing) -> str | None:
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

    # Try to find an actual address pattern in the description first
    if desc:
        m = ADDR_RE.search(desc)
        if m:
            return m.group(1).strip()

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
    """Final synthesis pass. Mutates listings in place."""
    counts = {"already_set": 0, "synthesized": 0, "still_null": 0}
    for li in listings:
        if li.street_address:
            counts["already_set"] += 1
            continue
        synth = _synth_for_listing(li)
        if synth:
            li.street_address = synth
            counts["synthesized"] += 1
        else:
            counts["still_null"] += 1
    log.info("addr_synth.done", **counts)
