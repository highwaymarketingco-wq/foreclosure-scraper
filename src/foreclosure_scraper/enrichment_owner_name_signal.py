"""Death / fractured-ownership signal read straight out of the owner name.

WHY THE OWNER NAME IS A DISTRESS SIGNAL AND NOT JUST A LABEL
    Dirty Deeds eps 036 and 064 make the point that matters: a county assessor does
    not rewrite the owner of record on its own initiative. The name changes to
    "ESTATE OF ...", "HEIRS OF ...", "... ET AL" or "C/O ..." because a survivor
    called the tax office about the bill. So the token implies two things at once --
    a death or a fracture in ownership, AND an engaged survivor who has already made
    contact with a government office. That is a warmer lead than a raw obituary
    match, and it is independent of any delinquency list.

MEASURED ON THE LIVE BOARD 2026-09-10
    2,414 rows carry one of these tokens and are NOT already on a probate or
    obituary source; 1,352 of those are in-footprint. Against 358 rows the probate
    and obituary scrapers surface. So the signal is roughly 7x what the dedicated
    scrapers find, and it costs a regex over a column already stored -- no new
    source, no fetch, no rate limit.

    Spartanburg 366 and Pickens 165 lead the county distribution, which is where
    this matters most: both sit at 13% phone coverage, and SC is mail-only.

THE TOKENS ARE NOT EQUAL, SO THEY ARE GRADED
    Publishing one flat count of 1,352 would overstate it. Graded by what the token
    actually implies about the owner:

      STRONG   heirs 618, life_estate 113, estate_of 44, deceased 13
               A death is implied on the face of the record.
      MEDIUM   et_al 423
               Fractured ownership. May or may not involve a death, but it is the
               multi-owner problem either way, which is the model's core mess.
      WEAK     trust 769, c_o 807, unknown 59
               A living trust is usually ordinary estate planning: a solvent owner
               with a lawyer, which is the OPPOSITE of the target profile. "C/O" is
               as often a property manager or accountant. These are recorded for
               completeness and scored low on purpose -- they must not dilute the
               strong bucket.

Pure computation over the board. No network, no scraping, nothing dropped.
"""
from __future__ import annotations

import re

import structlog

from .models import Listing
from .name_normalize import is_entity

log = structlog.get_logger()

# Ordered most-specific first. `_classify` returns every token that matches, so
# order matters only for the reported primary token.
#
# `\d*` on the heirs pattern catches a GIS fractional-interest concatenation seen
# live on the board (Rutherford NC: "HOFFMAN, CARL V HEIRS1", "ONEAL, O W JR
# HEIRS1") -- the county appends an interest number directly onto the token with
# no separator, which `\bHEIRS?\b` alone cannot see past (no word boundary
# between "S" and "1"). `ALS?` on et_al catches the same no-separator-plural shape
# for "et al." -- live-verified real board rows spell it "ETALS" with no space or
# period at all (84 rows / 10 counties: Dillon SC alone accounts for 16, plus
# Brunswick/Hyde/Pitt NC and Darlington/Lexington SC among others).
_TOKENS: tuple[tuple[str, str, re.Pattern], ...] = (
    ("estate_of", "strong", re.compile(r"\bEST(?:ATE)?\s+OF\b", re.I)),
    ("deceased", "strong", re.compile(r"\b(?:DECEASED|DEC'?D)\b", re.I)),
    ("life_estate", "strong", re.compile(r"\bLIFE\s+EST", re.I)),
    ("heirs", "strong", re.compile(r"\bHEIRS?\d*\b", re.I)),
    ("et_al", "medium", re.compile(r"\bET\.?\s*ALS?\b", re.I)),
    ("unknown_owner", "weak", re.compile(r"\bUNKNOWN\b", re.I)),
    ("trust", "weak", re.compile(r"\bTRUST(?:EE)?\b", re.I)),
    # "C/O" is not the only mailing-contact shorthand on the board. Two more
    # real variants are folded into the SAME "weak" grade (same rationale as
    # plain C/O -- a property manager or caretaker is as common here as an
    # heir, so neither must ever outrank it): a bare "%" used as SC tax-roll
    # shorthand for "care of" (live-verified 202 rows / 10 counties, Dillon
    # SC dominant: "ADAMS EARLINE BETHEA ETAL % EARLINE ADAMS"), and "ATTN"
    # (23 rows / 7 counties: "WATTS JACKSON ATTN. PARTIN CHRIS"). The "%"
    # half is deliberately NOT a bare `%` match: `(?<!\d)` rules out the
    # ownership-INTEREST shape "51% INT" / "1% INT" (3 live rows, a
    # different real meaning -- a fractional ownership share, not a mailing
    # contact) by requiring whitespace before the `%` with no digit before
    # that whitespace; every real ownership-interest row on this board
    # writes the number tight against the `%` ("51%") while every genuine
    # care-of "%" has a space before it ("BETHEA ... % EARLINE ADAMS").
    # Spelled-out "CARE OF" was tested and deliberately EXCLUDED: all 6 live
    # hits ("Home Care of the Upstate LLC", "Autumn Care of Drexel") are
    # real entity names that happen to contain the phrase, not an owner
    # routed to a contact -- adding it would be 100% false positive here.
    ("care_of", "weak", re.compile(r"\bC\s*/\s*O\b|\bC/O\b|\bATTN\b|(?<!\d)\s%\s*[A-Z]", re.I)),
)

# "HRS" is a bare abbreviation for "heirs" used live on the board by at least 2
# counties' own systems (NC Orange: 127 rows, SC Georgetown: 24 rows -- e.g.
# "SHERIDAN SAMUEL HRS", "GREEN TOM JR HRS") that the full-word `heirs` pattern
# above cannot see at all ("HRS" shares no substring with "HEIR"). It is handled
# separately, not folded into the `heirs` regex, because 3 letters alone is a real
# collision risk a full word is not: "HRS Property Group, LLC" (NC Yadkin, a real
# board row) is an unrelated company name, not an heir. Gated on `not is_entity()`
# so the abbreviation only ever fires on what reads as a person.
_HRS_ABBR = re.compile(r"\bHRS\b", re.I)

_GRADE_RANK = {"strong": 3, "medium": 2, "weak": 1}

# A government or institutional owner is not a motivated seller. These strings turn
# up inside otherwise-matching names ("COUNTY OF X, TRUSTEE") and would otherwise be
# graded as signal.
_INSTITUTIONAL = re.compile(
    r"\b(?:COUNTY|CITY\s+OF|TOWN\s+OF|STATE\s+OF|COMMISSION|AUTHORITY|"
    r"DEPARTMENT|DEPT|SCHOOL|CHURCH|UNITED\s+STATES|U\.?S\.?A\.?|"
    r"SECRETARY\s+OF|BANK|N\.?A\.?$|FEDERAL|MORTGAGE\s+ASSOC)\b",
    re.I,
)


def classify(owner_name: str | None) -> dict | None:
    """Return the graded signal for one owner name, or None if there is nothing."""
    name = (owner_name or "").strip()
    if not name:
        return None
    matched = [(tok, grade) for tok, grade, rx in _TOKENS if rx.search(name)]
    if not any(tok == "heirs" for tok, _ in matched) and _HRS_ABBR.search(name) and not is_entity(name):
        matched.append(("heirs", "strong"))
    if not matched:
        return None
    institutional = bool(_INSTITUTIONAL.search(name))
    # Best grade present, but an institutional owner can never rate above weak --
    # "COUNTY OF X AS TRUSTEE" is not a seller.
    grades = [g for _, g in matched]
    best = max(grades, key=lambda g: _GRADE_RANK[g])
    if institutional:
        best = "weak"
    primary = next(tok for tok, g in matched if g == best) if not institutional else matched[0][0]
    return {
        "tokens": [t for t, _ in matched],
        "primary_token": primary,
        "grade": best,
        "institutional_owner": institutional,
        "source": "owner_name_token",
    }


def enrich_owner_name_signal(listings: list[Listing]) -> dict:
    """Stamp `raw['owner_name_signal']` from the CURRENT owner_name every run.

    Removes no LEAD; the row count is asserted. It does clear a stale FIELD:
    if a prior run stamped this signal and the owner_name has since changed
    (a sale, an estate closing, `owner_freshness.py`'s parcel-cache refresh)
    so it no longer matches any token, the old stamp must not survive --
    `fullmer_rank.py` reads `raw['owner_name_signal']['grade']` directly
    (not a fresh `classify()` call) and would otherwise keep awarding
    owner_name_death/fracture points for a death signal that no longer holds
    on today's owner of record. Same "missing-only, never revalidated" bug
    shape as the owner_name/bop_federal staleness fixes.
    """
    before = len(listings)
    stats = {"strong": 0, "medium": 0, "weak": 0, "institutional": 0, "tagged": 0, "stale_cleared": 0}
    for li in listings:
        sig = classify(li.owner_name)
        if sig is None:
            if isinstance(li.raw, dict) and li.raw.pop("owner_name_signal", None) is not None:
                stats["stale_cleared"] += 1
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["owner_name_signal"] = sig
        stats["tagged"] += 1
        stats[sig["grade"]] += 1
        if sig["institutional_owner"]:
            stats["institutional"] += 1
    assert len(listings) == before, "owner_name_signal must never drop a lead"
    if stats["tagged"] or stats["stale_cleared"]:
        log.info("owner_name_signal.done", **stats)
    return stats
