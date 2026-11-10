"""NC Medicaid Estate Recovery Program (MERP) claim detector — Logan "The
Lookup" counties only (Transylvania, McDowell, Mitchell).

THE SIGNAL. N.C.G.S. 108A-70.5(b1) requires the NC Division of Health
Benefits (DHB, part of NC DHHS) to record a notice/claim against a deceased
Medicaid long-term-care recipient's real property in the county Register of
Deeds when it seeks estate recovery. A recorded claim = a probate-estate
house the heirs must clear/sell to pass clean title — a property-keyed,
free, on-title motivated-seller signal (docs/path_to_100_deepdive.md,
"Senior-downsizing / assisted-living / reverse-mortgage (HECM)" section,
row "NC Medicaid Estate Recovery", logged there as built: NO).

SCOPE OF THIS MODULE — read before wiring it into a scraper.
    docs/path_to_100_deepdive.md puts MERP in 11 of the project's 18
    counties (every NC county; SC has no equivalent recorded instrument —
    SC recovers only as a probate-estate creditor, never via a recorded
    lien). Of those 11 NC counties, this module reuses `rod/logan.py`'s
    sweep, which only reaches the THREE whose Logan pick-list loads
    browserless (`logan.LOGAN_COUNTIES`): Transylvania, McDowell, Mitchell.
    The other 8 NC counties in the MERP footprint run different vendors
    (CCHS: Burke, Cleveland, Lincoln, Henderson; Aumentum: Buncombe,
    Mecklenburg (paywalled); Cott: Polk, Rutherford (login-walled)) and are
    OUT OF SCOPE here — see the module docstring's "Deliberately not done"
    note below for why they are not a same-sized addition.

WHY THIS REUSES rod/logan.py RATHER THAN rod/lien_sweep.py.
    rod/lien_sweep.py's county-wide instrument-type sweep is architecturally
    the right shape (the MO this module copies), but its ONLY two counties
    (`lien_sweep.SWEEP_COUNTIES`) are Horry and Pickens — both SC, both on
    the Harris AcclaimWeb vendor. MERP is NC-only, so lien_sweep.py's own
    footprint has zero overlap with where a Medicaid estate claim could
    ever be recorded; adding a DHHS text pattern there would sweep two SC
    AcclaimWeb registers that, per the deepdive doc, structurally cannot
    hold this instrument. rod/logan.py's sweep is the same shape (open a
    session, POST a date-windowed instrument-type query, parse party names)
    but it is the one that actually runs in NC counties, so this module
    calls INTO it rather than lien_sweep.py.

HOW THE ADDITION WORKS — reusing 100% of the existing fetch/parse plumbing.
    1. `logan.discover_recent_nods(..., extra_codes=MERP_CANDIDATE_CODES)` —
       the ONE new parameter added to logan.py by this change (purely
       additive; the default `()` leaves every existing caller, including
       `scrapers/counties_nc/nc_rod_logan.py`, byte-for-byte unaffected).
       No new session/auth/parse code at all: same GET index.php -> POST
       Accept -> POST content.php?<token> -> same `_parse_records` row
       shape this module's own docstring already documents variance in
       (Book Info, Doc Type, Legal Desc, Party Type, Searched/Reverse
       Party).
    2. `is_merp_match()` is a pure, offline text classifier over the
       RodDoc fields that sweep already returns (grantor, grantee,
       doc_type, notes) — no new network call, no new document-image
       fetch. It looks for the DHHS/Division of Health Benefits claimant
       name on EITHER party side (Logan's grantor/grantee side convention
       is proven to invert between deployments — see logan.py's
       `grantee_side()` docstring on Spartanburg's "Party 1"/"Party 2" —
       so this does not assume DHHS lands on "grantee" specifically).
    3. `discover_merp_claims()` is the public entry point: sweep, then
       keep + tag only the matches, each carrying `raw['merp_claim']` (a
       stamp dict shaped like `lien_sweep.stamp_for()`'s, for one reader
       convention). It returns a (possibly empty) DISCOVERY list — new
       leads, not a confirmation stamp on existing board owners, matching
       how `scrapers/counties_nc/nc_rod_logan.py` already turns
       `logan.discover_recent_nods()` rows directly into Listings.

WHAT IS NOT CONFIRMED — the one real open question, honestly flagged.
    Neither this repo nor this change has live-verified what instrument-type
    CODE or LABEL Transylvania/McDowell/Mitchell's clerks file a §108A-70.5
    notice under. `MERP_CANDIDATE_CODES` below are reasoned guesses at a
    short code for "notice"/"claim"/"affidavit"-style filings, in the same
    short-code vocabulary `logan.DISTRESS_CODES` already uses for that
    deployment family. Per logan.py's own docstring, "extra codes a county
    doesn't have are harmless (they just don't match)" — a wrong guess
    costs nothing and changes no other code's rows. Separately, "LIEN" /
    "LN" / "LIEN000" are ALREADY in `logan.DISTRESS_CODES`, so if a county
    clerk happens to index this instrument as a plain lien, the EXISTING
    sweep is already fetching it today and `is_merp_match()` alone (no new
    code needed) would surface it the next time any Logan sweep runs. A
    live run against the three counties is the only way to learn which of
    these is true, and is the clear next step before wiring this into a
    scraper — not done here, so a build claiming confirmed yield would be
    the kind of unverified-premise mistake this project's own history
    (feedback_verify_own_premises.md, feedback_silently_broken_or_stale_
    producer_pattern.md) flags.

DELIBERATELY NOT DONE in this change (future, separate work):
    * No wiring into `scrapers/counties_nc/nc_rod_logan.py` or a new
      ListingType — that turns an unverified signal into a published lead
      before its yield is known. `ListingType.LIEN_CLAIM` ("a claim of lien
      docketed... against the owner") is the closest existing bucket if/
      when this is promoted.
    * No doc_images.py-side per-owner CCHS search (Burke/Cleveland/Lincoln/
      Henderson). That vendor's `_cchs_owner_dots` needs a KNOWN owner name
      to search (it is a confirmation call, not a county sweep) and is
      hardcoded to `is_dot_type()` (deed-of-trust only) — reusable with a
      parallel type filter, as a per-existing-probate/estate-lead
      CONFIRMATION step, but that is a second, separate addition, not part
      of this county-wide discovery sweep.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from . import logan
from .models import RodDoc

#: The Logan-vendor subset of the 11 NC counties docs/path_to_100_deepdive.md
#: puts in the MERP footprint — exactly `logan.LOGAN_COUNTIES`' keys, kept as
#: its own name here so a caller never has to know this rides the Logan
#: adapter to find the right counties.
MERP_COUNTIES: dict[tuple[str, str], str] = dict(logan.LOGAN_COUNTIES)

#: UNVERIFIED (see module docstring). Reasoned-guess short codes for a
#: notice/claim/affidavit-style recording, added to the ALREADY-swept
#: `logan.DISTRESS_CODES` (which already includes "LIEN"/"LN"/"LIEN000").
#: Live-check before relying on these specifically; a wrong code costs
#: nothing per logan.py's own documented tolerance for extras.
MERP_CANDIDATE_CODES: tuple[str, ...] = ("NOT/CL", "NOTICE", "CLAIM", "AFFDVT")

#: The DHB/DHHS claimant as it is likely to appear as a recorded party name.
#: Covers the current ("Division of Health Benefits" / "NC Medicaid") and
#: pre-2020 ("Division of Medical Assistance") agency names, since older
#: recordings on-title predate the rebrand.
MERP_GRANTEE_RE = re.compile(
    r"DIVISION\s+OF\s+(?:HEALTH\s+BENEFITS|MEDICAL\s+ASSISTANCE)"
    r"|DEP(?:AR)?T(?:MENT)?\s+OF\s+HEALTH\s+(?:AND|&)\s+HUMAN\s+SERVICES"
    r"|\bN\.?\s*C\.?\s*DHHS\b|\bDHHS\b|\bNC\s*MEDICAID\b"
    r"|MEDICAID\s+ESTATE\s+(?:RECOVERY|CLAIM)|ESTATE\s+RECOVERY\s+(?:PROGRAM|UNIT)",
    re.I,
)

#: Backstop on the DOC TYPE / legal-description text itself, in case a clerk's
#: own instrument-type label or indexed description names the statute or the
#: program directly rather than (or in addition to) the party name matching.
MERP_DOCTYPE_RE = re.compile(r"MEDICAID|ESTATE\s+(?:CLAIM|RECOVERY)|108A-?70", re.I)

PLATFORM = "nc_logan_merp_detector"


def is_merp_match(doc: RodDoc) -> Optional[str]:
    """Which field matched the MERP claimant/statute pattern ('grantor',
    'grantee', 'doc_type' or 'notes'), or None. Checks both party sides —
    rod/logan.py's own docstring documents the grantor/grantee side
    convention inverting between Logan deployments (Spartanburg's "Party 1"/
    "Party 2"), so this does not assume DHHS lands on "grantee" specifically.
    Pure/offline: no network call, just the fields the sweep already parsed.
    """
    for field in ("grantee", "grantor"):
        if MERP_GRANTEE_RE.search(getattr(doc, field) or ""):
            return field
    for field in ("doc_type", "notes"):
        if MERP_DOCTYPE_RE.search(getattr(doc, field) or ""):
            return field
    return None


def merp_stamp(doc: RodDoc, matched_field: str) -> dict:
    """raw['merp_claim'] for one swept document — shaped like
    rod/lien_sweep.py's stamp_for() (status/platform/checked_at) so one
    reader convention can grow to cover both, but this is a per-document
    DISCOVERY tag (this doc IS the match), not a per-board-row confirmation
    search result."""
    return {
        "status": "nc_medicaid_estate_claim",
        "statute": "N.C.G.S. 108A-70.5(b1)",
        "platform": PLATFORM,
        "county": doc.county,
        "matched_field": matched_field,
        "matched_text": (getattr(doc, matched_field) or "")[:160],
        "instrument_no": doc.instrument_no,
        "recorded_date": doc.recorded_date.date().isoformat() if doc.recorded_date else None,
        "checked_at": datetime.now(timezone.utc).date().isoformat(),
    }


def is_merp_county(state: str, county: str) -> bool:
    return (state, county) in MERP_COUNTIES


async def discover_merp_claims(state: str, county: str, *, days_back: int = 180,
                               max_docs: int = 200) -> list[RodDoc]:
    """Sweep this county (Transylvania/McDowell/Mitchell NC only) for
    recently recorded instruments and return ONLY the ones that read as a
    NC Medicaid Estate Recovery claim, each carrying raw['merp_claim'].

    100% reuse: the actual sweep is `logan.discover_recent_nods` (same
    session/token/POST/parse this module's sibling scraper
    `scrapers/counties_nc/nc_rod_logan.py` already runs weekly), widened by
    the one new `extra_codes` parameter; everything after that is a pure
    Python filter over fields the sweep already returns. `days_back`
    defaults wider than the 45-day foreclosure lookback
    (`nc_rod_logan._LOOKBACK_DAYS`) because a MERP claim is not time-
    sensitive the way a sale date is — DHB can file months after death.
    This module has no cache layer of its own (unlike lien_sweep.py's
    per-county data/lien_sweep/*.json), so a wider window costs one extra
    sweep call each run, not repeated work; adding one is natural follow-on
    work once a live run confirms real matches exist to make caching worth
    building.
    """
    if not is_merp_county(state, county):
        return []
    docs = await logan.discover_recent_nods(
        state, county, days_back=days_back, max_docs=max_docs,
        extra_codes=MERP_CANDIDATE_CODES)
    out: list[RodDoc] = []
    for d in docs:
        field = is_merp_match(d)
        if not field:
            continue
        d.raw["merp_claim"] = merp_stamp(d, field)
        out.append(d)
    return out
