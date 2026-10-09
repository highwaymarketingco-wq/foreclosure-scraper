"""Second-lien / HOA-lien / hidden-estate signal read straight out of co_defendants.

WHY THIS EXISTS
    `sc_public_index.py` and `sc_public_index_lis_pendens.py` already collect every
    defendant-party row on a SC judicial-foreclosure case into
    `raw["court"]["co_defendants"]` / `raw["sc_public_index"]["co_defendants"]`
    (comment on both: "co-owners / heirs ... each is a resolvable owner lead
    downstream"). SC foreclosure is judicial, so S.C. R. Civ. P. 19 / the
    mortgage-priority rule forces the plaintiff to join every OTHER party with a
    recorded interest as a defendant, not just the homeowner -- a second
    mortgagee, a judgment-credit-card creditor, a HOA with a recorded assessment
    lien, or an estate standing in for a dead co-owner. That makes the
    co_defendants list a second, free distress signal riding on data already on
    the board, with zero new scraping.

    Nothing in this repo has ever read `co_defendants` back out again (grep for
    the key outside the two scrapers that WRITE it returns nothing). It is
    captured and then never looked at.

MEASURED ON THE LIVE BOARD, 2026-10-01 (`docs/listings.json`, raw string scan)
    1,879 listings carry a non-null co_defendants array (407 more carry an
    explicit null -- a case with no co-defendants, already checked). Of those
    1,879:
      - 67  (3.6%) name an entity that reads as a private junior lienholder --
            real live examples: "Arthur State Bank, Mortgagee And Assignee" +
            "B4M Investments, Llc, Mortgagee" on the same case, "Onemain
            Financial Group Llc", "Capital One Na", "Discover Bank", "Synchrony
            Bank", "Mortgage Electronic Registration Systems, Inc.,", "Portfolio
            Recovery Associates Llc" (a judgment-debt buyer, not a mortgagee, but
            the same "another creditor already has a claim on this owner" fact).
      - a visible further slice names a FEDERAL junior lien --  "Secretary Of
            Housing And Urban Development", "Rural Housing Service" (a HUD/USDA
            second mortgage behind the first) -- and a SC state tax lien --
            "Department Of Revenue South Carolina" -- both real, both currently
            unclassified text sitting next to the private-lender hits.
      - a visible slice names an HOA -- "Anderson Grant Homeowners Association
            Inc", "The Cliffs At Keowee Vineyards Community Association Inc" --
            confirming a RECORDED ASSESSMENT LIEN the HOA's own filings are
            walled (ROD-indexed, not independently scraped; see
            docs/walls_register.md) but this caption admits it for free.
      - 17  (0.9%) carry an ESTATE/HEIRS token ("Sampleton Estate Of, Ray Douglas",
            "Austin, Estate Of Alice") that `enrichment_owner_name_signal.classify()`
            would grade STRONG if it ran on this string -- but that enricher only
            ever reads `li.owner_name`, never `co_defendants`, so these probate
            leads are invisible to it today. (A bare trailing "... Estate" with
            no "OF" -- e.g. "Amanda W Cooper Estate" -- is correctly left
            unclassified: `classify()` requires "ESTATE OF" by design, exactly
            to avoid reading "ACME REAL ESTATE HOLDINGS LLC" as a death. This
            module inherits that same, already-proven judgment call rather than
            loosening it.)

    These counts are a FLOOR, not a ceiling: the regex below is deliberately
    conservative (named entity suffixes only) and a second pass over the same
    1,879 rows by a human would likely find more loosely-worded hits.

SCOPE AND WHAT THIS DOES NOT CLAIM
    Pure computation over a raw field already on the board. No network, no new
    scrape, no board write here -- `enrich_co_defendant_signal` only stamps
    `raw["co_defendant_signal"]` on listings already in memory; a future run
    picks it up for free the next time the court scrapers land these cases.
    This module does NOT decide outreach priority or scoring weight -- that is
    a `distress_score.py` / `lead_signals.py` wiring decision for later, flagged
    in the module docstring on purpose rather than rushed in here.
"""
from __future__ import annotations

import re

import structlog

from .enrichment_owner_name_signal import classify as _classify_owner_token
from .models import Listing

log = structlog.get_logger()

# Private lender / creditor entity names. Suffix/keyword match, case-insensitive.
# Deliberately named-entity-shaped (BANK, CREDIT UNION, FINANCIAL, MORTGAGE,
# LENDING) rather than a generic word like "CORP" or "CAPITAL" alone, so a bail
# bond surety ("Allegheny Casualty Co.") or an unrelated LLC never matches.
_LIENHOLDER_RE = re.compile(
    r"\b(?:"
    r"MORTGAGEE|MORTGAGE\s+ELECTRONIC\s+REGISTRATION|MERS\b|"
    r"\w*\s?BANK\b|CREDIT\s+UNION|"
    r"FINANCIAL\s+(?:CORP|SERVICES|GROUP)?|FINANCE\s+(?:CO|COMPANY)|"
    r"LENDING\b|MORTGAGE\s+(?:CORP|COMPANY|SERVICES|ASSOC)|"
    r"PORTFOLIO\s+RECOVERY|CAPITAL\s+ONE|DISCOVER\b|SYNCHRONY|"
    r"CREDIT\s+MANAGEMENT|ACCEPTANCE\s+CORP"
    r")\b",
    re.I,
)

# A federally- or state-insured junior lien / tax lien named as a party. Kept
# separate from the private bucket because the remedy differs (these imply a
# HUD/USDA second mortgage or a state tax lien, not a private note).
_GOV_LIENHOLDER_RE = re.compile(
    r"\b(?:"
    r"SECRETARY\s+OF\s+HOUSING|RURAL\s+HOUSING\s+SERVICE|"
    r"DEPARTMENT\s+OF\s+HOUSING\s+AND\s+URBAN|"
    r"DEPARTMENT\s+OF\s+REVENUE|INTERNAL\s+REVENUE"
    r")\b",
    re.I,
)

# A homeowners'/community association named as a party -- an admitted recorded
# assessment lien even though the HOA's own ROD filing is walled (see
# docs/walls_register.md: "Recorded HOA/mechanic/judgment liens -- ROD-walled").
_HOA_RE = re.compile(
    r"\b(?:HOMEOWNERS?\s+ASSOCIATION|PROPERTY\s+OWNERS\s+ASSOCIATION|"
    r"COMMUNITY\s+ASSOCIATION|\bHOA\b)\b",
    re.I,
)


def _party_key(name: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(name or "").lower()).split())


def _co_defendants(li: Listing) -> list[str]:
    """The case's co-defendants, minus the plaintiff itself: a party list that repeats the
    plaintiff (2 of 135 tagged rows on the 10/8 checkpoint listed the suing bank as its own junior
    lienholder; audit 2026-10-09 additions_verify) must not read as another lien."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    plaintiff = _party_key(getattr(li, "plaintiff", None) or "")
    for container in ("court", "sc_public_index"):
        block = raw.get(container)
        if isinstance(block, dict):
            vals = block.get("co_defendants")
            if isinstance(vals, list) and vals:
                return [str(v) for v in vals if v and (not plaintiff or _party_key(v) != plaintiff)]
    return []


def classify_co_defendants(names: list[str]) -> dict | None:
    """Classify a case's co-defendant list. Returns None if nothing matches."""
    lienholders: list[str] = []
    gov_liens: list[str] = []
    hoa: list[str] = []
    estate: list[dict] = []

    for name in names:
        if not name:
            continue
        if _LIENHOLDER_RE.search(name):
            lienholders.append(name)
        if _GOV_LIENHOLDER_RE.search(name):
            gov_liens.append(name)
        if _HOA_RE.search(name):
            hoa.append(name)
        sig = _classify_owner_token(name)
        if sig and sig["grade"] in ("strong", "medium"):
            estate.append({"name": name, **sig})

    if not (lienholders or gov_liens or hoa or estate):
        return None

    return {
        "junior_lienholders": lienholders or None,
        "government_lienholders": gov_liens or None,
        "hoa": hoa or None,
        "estate_co_defendants": estate or None,
        "source": "co_defendants_scan",
    }


def enrich_co_defendant_signal(listings: list[Listing]) -> dict:
    """Stamp `raw['co_defendant_signal']`. Pure computation, drops nothing."""
    before = len(listings)
    stats = {"checked": 0, "tagged": 0, "junior_lienholder": 0,
              "government_lienholder": 0, "hoa": 0, "estate": 0}
    for li in listings:
        names = _co_defendants(li)
        if not names:
            continue
        stats["checked"] += 1
        sig = classify_co_defendants(names)
        if sig is None:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["co_defendant_signal"] = sig
        stats["tagged"] += 1
        if sig["junior_lienholders"]:
            stats["junior_lienholder"] += 1
        if sig["government_lienholders"]:
            stats["government_lienholder"] += 1
        if sig["hoa"]:
            stats["hoa"] += 1
        if sig["estate_co_defendants"]:
            stats["estate"] += 1
    assert len(listings) == before, "co_defendant_signal must never drop a lead"
    if stats["tagged"]:
        log.info("co_defendant_signal.done", **stats)
    return stats
