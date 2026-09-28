"""LiensNC filing-date vs. owner-death-date mismatch (Dirty Deeds Tier B #24).

docs/dirty_deeds_synthesis_2026-09-10.md, source #24: "NC lien-agent (LiensNC)
filing date vs record owner's date of death (048) -- Reuses the 56K liensnc
rows already classified as non-distress. The filing is not the signal, the
mismatch is: a permit or notice of commencement dated after the owner's
death, or filed by a non-owner. Ep 048's $254k deal came off a re-roof NOC
'signed by the dead guy' two years post-mortem." liensnc rows are already on
the board (counties_generic.liensnc, raw['liensnc'], RAW_KEEP'd) as
"construction lien-agent filings, NOT distress" on their own -- this module is
the derived JOIN the synthesis calls for, not a new scrape.

TWO MECHANISMS, not one, because live-checking this against the board
(2026-09-28) found the synthesis's second half is not a usable signal here:

  1. date_mismatch (the synthesis's primary claim). Cross-listing join against
     every OTHER board row that carries a REAL, parsed date of death --
     raw['probate']['date_of_death'] or raw['sc_probate_notice']['date_of_death']
     (both already RAW_KEEP'd; see enrichment_repeat_tax_loss.py /
     enrichment_owner_cluster.py for the same shape of cross-parcel join).
     Matched by name_normalize.match_owner (exact/strong only -- this drives
     outreach, so a weak match is worse than no match), scoped by STATE only:
     liensnc.py's _to_listing() never sets `county` on a LiensNC row, so
     county-scoping (what every other cross-listing join here uses) is not
     available. Common-surname collisions are a real risk as a result; expect
     this to need a second key (mailing address) if it ever produces volume.

     LIVE-VERIFIED 2026-09-28 (docs/listings.json via read-only jq, no
     load_board): every listing that carries a raw['probate'] or
     raw['sc_probate_notice'] block WITH a parsed date_of_death is state=SC
     (71 + 866 rows respectively; the SC public-index/public-notices/probate-
     notices lanes are the only sources on this board that currently attach a
     real death date to a decedent). Every liensnc row is state=NC (46,801
     rows) and none carry a county. So this mechanism is CORRECT but scores
     ZERO matches on the live board today -- there is no state-scoped
     candidate to join against. It will start producing hits the day an NC
     source attaches a real date_of_death (ncpublicnotices.py's
     _enrich_probate_details() already extracts one per-decedent, into the
     same raw['probate']['date_of_death'] key, but that lane produced no
     dated rows on this run). Kept rather than dropped: the join is free,
     correct, and wired for a signal source this board does not have YET.

  2. owner_name_token (the mechanism that actually fires today). No
     cross-listing join at all -- the liensnc row's OWN owner_name (the deed
     owner LiensNC's Appointment-of-Lien-Agent filing names) already carries a
     death-shaped token ("HEIRS OF", "ESTATE OF", "DECEASED", a life estate)
     per enrichment_owner_name_signal.classify(), the SAME grader
     fullmer_rank.py already reads. The construction/renovation activity that
     an Appointment of Lien Agent implies, landing on a parcel whose owner of
     record is ALREADY an estate or heir group, is the live version of "the
     filing is not the signal, the mismatch is": someone is doing work on a
     dead owner's property. LIVE-VERIFIED 2026-09-28: 22 of 46,801 liensnc
     rows carry a STRONG token on a real person's name (HEIRS/DECEASED --
     e.g. 'KISER JASON LEE HEIRS', 'PACKER GEORGE (DECEASED)'), after
     excluding one company-name collision (see _COMPANY_NOISE below).

VERIFIED DEAD END: the synthesis's OTHER stated trigger -- "filed by a
non-owner" -- is not buildable off this board's liensnc data. Every one of
the 46,801 rows' raw['liensnc']['filing_type'] is literally "Appointment of
Lien Agent" (there is no Notice of Commencement or Claim of Lien filing type
present at all), and raw['liensnc']['filed_by'] on every row is a LiensNC
PORTAL LOGIN/contact string for the lien agent -- a username ('ddavis5',
'zetterholmj') or a contractor's ops email ('permits@sugarhollowsolar.com'),
never a person's deed-owner-shaped name. Comparing filed_by to owner_name
would flag 100% of rows, which is not a signal, it is the shape of every row
on this board. Not implemented; documented here so nobody rebuilds it and
gets the same 100% "hit" rate.

No network. Reads the board rows in hand.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from .enrichment_owner_name_signal import classify
from .models import Listing
from .name_normalize import match_owner

log = structlog.get_logger()

# The only two raw blocks on this board that carry a per-decedent
# date_of_death (both already in web_artifact.RAW_KEEP).
_DEATH_RAW_KEYS = ("probate", "sc_probate_notice")

# "Sterling Real Estate of NC" matches the 'estate_of' token in
# enrichment_owner_name_signal._TOKENS (a bare "EST(ATE) OF") but is a
# business name, not a decedent -- and classify()'s own _INSTITUTIONAL guard
# does not catch it (no COUNTY/CITY OF/BANK/CHURCH-style marker). Only a
# construction-lien-agent context makes "real estate" this likely to collide,
# so the exclusion lives here rather than in the shared classifier.
_COMPANY_NOISE = re.compile(
    r"\bREAL\s+ESTATE\b|\bREALTY\b|\bCONSTRUCTION\b|\bBUILDERS?\b|\bHOMES\b",
    re.I,
)


def _parse_date(value) -> Optional[datetime]:
    """Best-effort parse of the mixed date formats already on the board:
    'MM/DD/YYYY' (liensnc.filing_date), 'M/D/YYYY' or 'Month D, YYYY'
    (probate/sc_probate_notice date_of_death), or an already-parsed datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    from dateutil import parser as dp
    try:
        return dp.parse(str(value), fuzzy=True)
    except (ValueError, TypeError, OverflowError):
        return None


def _decedent_name_and_dod(li: Listing) -> tuple[Optional[str], Optional[datetime]]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    for key in _DEATH_RAW_KEYS:
        block = raw.get(key)
        if not isinstance(block, dict):
            continue
        dod = _parse_date(block.get("date_of_death"))
        if not dod:
            continue
        name = block.get("decedent") or block.get("estate") or li.defendant or li.owner_name
        if name:
            return name, dod
    return None, None


def build_death_index(listings: list[Listing]) -> dict[str, list[tuple[str, datetime, str]]]:
    """STATE -> [(decedent_name, death_date, source_slug), ...] for every board
    row carrying a real, parsed date of death. State-only (not county+state,
    the usual scoping in this codebase's cross-parcel joins -- see
    enrichment_owner_cluster.py / enrichment_repeat_tax_loss.py) because
    liensnc rows carry no county to join on."""
    idx: dict[str, list[tuple[str, datetime, str]]] = {}
    for li in listings:
        name, dod = _decedent_name_and_dod(li)
        if not name or not dod or not li.state:
            continue
        idx.setdefault(li.state.upper(), []).append((name, dod, li.source))
    return idx


def enrich_liensnc_posthumous(listings: Iterable[Listing]) -> dict:
    """Stamp raw['liensnc_posthumous_filing'] on a liensnc row whose deed owner
    is (a) matched to a confirmed decedent whose death PRE-DATES the filing, or
    failing that (b) already carries a death-shaped token on its own owner_name.
    Never drops a lead; additive only, same contract as every enricher here."""
    listings = list(listings)
    stats = {
        "liensnc_rows": 0, "date_mismatch": 0, "owner_name_token": 0, "tagged": 0,
    }
    death_index = build_death_index(listings)

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        ln = raw.get("liensnc")
        if not isinstance(ln, dict):
            continue
        stats["liensnc_rows"] += 1
        owner = li.owner_name
        filing_date = _parse_date(ln.get("filing_date"))

        tag: Optional[dict] = None

        # Mechanism 1: someone else on the board is a confirmed decedent whose
        # death pre-dates this filing, name-matched to this row's deed owner.
        if filing_date and owner:
            candidates = death_index.get((li.state or "").upper(), [])
            best = None
            for name, dod, src in candidates:
                if dod >= filing_date:
                    continue                       # died on/after the filing -- not posthumous
                verdict = match_owner(name, owner)
                if verdict and (best is None or dod > best[1]):
                    best = (name, dod, src, verdict)
            if best:
                name, dod, src, verdict = best
                tag = {
                    "mechanism": "date_mismatch",
                    "confidence": "high" if verdict == "exact" else "medium",
                    "decedent": name,
                    "date_of_death": dod.date().isoformat(),
                    "filing_date": filing_date.date().isoformat(),
                    "days_after_death": (filing_date.date() - dod.date()).days,
                    "death_source": src,
                    "match": verdict,
                }
                stats["date_mismatch"] += 1

        # Mechanism 2 (fallback): no dated cross-record match, but the deed
        # owner LiensNC names for THIS filing already reads as a decedent's
        # estate/heirs on its own.
        if tag is None and owner and not _COMPANY_NOISE.search(owner):
            sig = classify(owner)
            if sig and sig["grade"] == "strong" and not sig["institutional_owner"]:
                tag = {
                    "mechanism": "owner_name_token",
                    "confidence": "low",
                    "decedent": owner,
                    "token": sig["primary_token"],
                    "filing_date": (filing_date.date().isoformat() if filing_date
                                     else ln.get("filing_date")),
                }
                stats["owner_name_token"] += 1

        if tag:
            li.raw["liensnc_posthumous_filing"] = tag
            stats["tagged"] += 1

    if stats["tagged"]:
        log.info("liensnc_posthumous_filing.done", **stats)
    return stats
