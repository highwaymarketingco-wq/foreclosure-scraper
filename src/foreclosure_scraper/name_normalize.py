"""Reusable owner-name normalization + strict matching for name->property work.

County GIS parcel layers store owners UPPERCASE, SURNAME-FIRST, with no comma
("BYRD SANDRA D", "SMITH JOHN C & MELINDA P", "SAR 6 LLC"). Court/probate feeds
emit the opposite ("Sandra L Byrd", "Byrd, Sandra L") with title case, double
spaces, stray punctuation and entity suffixes ("Allied Of Spartanburg, Llc").

This module is the ONE place that reconciles the two. It is intentionally
dependency-free and side-effect-free so both the resolver and any offline
dry-run/QA script use identical logic.

MATCH POLICY (this data drives outreach, so it errs toward committing nothing):

  * ``exact``  — the two names carry the SAME set of core tokens once titles,
    generational suffixes, entity suffixes and boilerplate are dropped.
    'Sandra L Byrd' == 'BYRD SANDRA D'  (the lone 'L'/'D' initials are noise).

  * ``strong`` — the parsed surname sits in the GIS owner's SURNAME position
    (token 0) AND the parsed first name sits in the FIRST-NAME position
    (token 1). These layers are strictly surname-first, so position carries
    real signal. This is what kills the false positives a bag-of-tokens rule
    accepts:
        'Michael Duane Crowe'       vs 'CROWE KEVIN MICHAEL'   -> REJECT
        'Mario Roberto Cruz Montes' vs 'MONTES HEMRY CRUZ'     -> REJECT
        'Robert Lewis Grant Jr'     vs 'STEPP ROBERT GRANT'    -> REJECT
    while keeping the true positives:
        'Angela Dawn Alexander'     vs 'ALEXANDER ANGELA FAYE' -> accept
        'John Mathis Anthony'       vs 'ANTHONY JOHN MATHIS'   -> accept

  * anything else -> no match.

ORDERING: a bare 'A B C' string is ambiguous — it can be read FIRST MIDDLE LAST
or LAST FIRST MIDDLE (SC Public Index emits both). ``person_orderings`` returns
BOTH readings; a comma ('LAST, FIRST') is unambiguous and returns one.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

# Corporate / fiduciary markers. Presence of any of these makes the name an
# ENTITY (matched by exact token-set equality, never by surname position).
_ENTITY_MARKERS = {
    "LLC", "LLP", "LP", "PLLC", "PA", "INC", "INCORPORATED", "CORP",
    "CORPORATION", "COMPANY", "CO", "LTD", "FUND", "ENTERPRISES", "HOLDINGS",
    "GROUP", "PROPERTIES", "PROPERTY", "INVESTMENTS", "PARTNERS",
    "PARTNERSHIP", "ASSOCIATION", "ASSOC", "TRUST", "BANK", "CHURCH",
    "MINISTRIES", "FOUNDATION", "AUTHORITY", "DISTRICT",
}

# Generational / professional suffixes and honorifics — noise for matching.
_PERSON_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "DDS", "DVM", "ESQ", "PHD"}
_TITLES = {"MR", "MRS", "MS", "DR", "REV"}

# Filing boilerplate and connectives that carry no identity.
_NOISE = {
    "ET", "AL", "ETAL", "AKA", "FKA", "DBA", "DECD", "DECEASED", "LIFE",
    "ESTATE", "THE", "AND", "OR", "OF", "FOR", "A", "AN", "AS", "TRUSTEE",
    "TRUSTEES", "REVOCABLE", "IRREVOCABLE", "PERSONAL", "REPRESENTATIVE",
    "REP", "UNKNOWN", "SPOUSE", "HEIRS", "DEVISEES", "CURRENT", "OCCUPANT",
    "OCCUPANTS", "TENANT", "TENANTS", "IF", "ANY", "CO", "C",
}

# Tokens too generic to anchor a broad entity LIKE query. Picking the LONGEST
# token (the old rule) turns 'Allied Of Spartanburg, Llc' into '%SPARTANBURG%',
# which returns ten civic parcels and matches none of them. Rank by
# distinctiveness instead: drop these, keep what's left in original order.
_GENERIC_ENTITY_TOKENS = {
    # SC/NC place names that appear in hundreds of civic parcel owners
    "SPARTANBURG", "GREENVILLE", "ANDERSON", "PICKENS", "OCONEE", "LAURENS",
    "UNION", "CHEROKEE", "GREENWOOD", "ABBEVILLE", "CHARLESTON", "COLUMBIA",
    "CAROLINA", "CAROLINAS", "SOUTH", "NORTH", "EAST", "WEST", "AMERICAN",
    "AMERICA", "UNITED", "STATES", "NATIONAL", "STATE", "COUNTY", "CITY",
    "TOWN", "USA", "US",
    # corporate filler
    "SERVICES", "SERVICE", "SOLUTIONS", "MANAGEMENT", "DEVELOPMENT", "REALTY",
    "REAL", "HOMES", "HOME", "HOUSING", "LAND", "CAPITAL", "VENTURES",
}

_TAG_RE = re.compile(r"<[^>]*>")
# Apostrophes collapse to NOTHING (not to a space) because assessor indexes store
# "OBRIEN SEAN P", never "O BRIEN": mapping ' to a space split O'Brien into
# ["O","BRIEN"] so the name could never match.
# Hyphens deliberately stay in _NONWORD_RE (-> space). normalize_name runs on BOTH
# sides, so hyphen->space makes "SMITH-LEE" and "SMITH LEE" converge on "SMITH LEE"
# and match either storage form; collapsing them would break the spaced variant.
_APOSTROPHE_RE = re.compile(r"['’ʼ`]")
_NONWORD_RE = re.compile(r"[^A-Z0-9]+")
# ';' joins co-owners on NC OneMap ('MANLY DAVID T;DILLON MARGARET') exactly the
# way '&' does on the county layers. Without it normalize_name turns the
# semicolon into a space and primary_party fuses two people into one four-token
# name, so neither owner can ever match. Strings without a ';' are unaffected.
_JOINT_SPLIT_RE = re.compile(r"\s*(?:&|;|\bAND\b)\s*")


class PersonName(NamedTuple):
    """A parsed individual: surname plus ordered given-name tokens."""

    surname: str
    given: tuple[str, ...]


def normalize_name(name: Optional[str]) -> str:
    """Uppercase, strip markup/punctuation, collapse repeated whitespace.

    'Allied Of Spartanburg, Llc' -> 'ALLIED OF SPARTANBURG LLC'
    'Chante  Fleming'            -> 'CHANTE FLEMING'
    "Sean O'Brien"               -> 'SEAN OBRIEN'   (matches GIS 'OBRIEN SEAN P')
    'Smith-Lee'                  -> 'SMITH LEE'     (matches either GIS spelling)
    """
    s = _TAG_RE.sub(" ", str(name or "")).upper()
    s = _APOSTROPHE_RE.sub("", s)
    s = _NONWORD_RE.sub(" ", s)
    return " ".join(s.split())


def _raw_tokens(name: Optional[str]) -> list[str]:
    n = normalize_name(name)
    return n.split() if n else []


def is_entity(name: Optional[str]) -> bool:
    """True when the name reads as a company/trust/agency rather than a person."""
    return bool(_ENTITY_MARKERS & set(_raw_tokens(name)))


def core_tokens(name: Optional[str], *, keep_initials: bool = False) -> list[str]:
    """Identity-bearing tokens: no titles, generational/entity suffixes,
    boilerplate, or bare initials. Order preserved, duplicates dropped."""
    out: list[str] = []
    for t in _raw_tokens(name):
        if t in _TITLES or t in _PERSON_SUFFIXES or t in _NOISE:
            continue
        if t in _ENTITY_MARKERS:
            continue
        if not keep_initials and len(t) < 2:
            continue
        if t.isdigit() and len(t) < 2:
            continue
        if t not in out:
            out.append(t)
    return out


def distinctive_tokens(name: Optional[str]) -> list[str]:
    """Entity tokens ranked by distinctiveness (generic place/filler words last).

    'Allied Of Spartanburg, Llc' -> ['ALLIED', 'SPARTANBURG']
    """
    toks = core_tokens(name)
    strong = [t for t in toks if t not in _GENERIC_ENTITY_TOKENS]
    weak = [t for t in toks if t in _GENERIC_ENTITY_TOKENS]
    return strong + weak


def primary_party(owner: Optional[str]) -> str:
    """First party of a joint GIS owner string.

    'SMITH JOHN C & MELINDA P' -> 'SMITH JOHN C'
    """
    # Split BEFORE normalizing — normalize_name turns '&' into a space, which
    # would silently fuse 'SMITH JOHN C & MELINDA P' into one four-token name.
    raw = _TAG_RE.sub(" ", str(owner or "")).upper()
    if not raw.strip():
        return ""
    return normalize_name(_JOINT_SPLIT_RE.split(raw)[0])


def person_orderings(name: Optional[str]) -> list[PersonName]:
    """Every plausible (surname, given...) reading of an individual's name.

    A comma is authoritative ('BYRD, SANDRA L' -> surname BYRD). Without one the
    string is genuinely ambiguous, so BOTH 'FIRST MIDDLE LAST' and
    'LAST FIRST MIDDLE' are returned, most-likely first.
    """
    raw = str(name or "")
    if "," in raw:
        left, right = raw.split(",", 1)
        sur = core_tokens(left)
        giv = core_tokens(right)
        if sur:
            return [PersonName(sur[0], tuple(giv))]
        return []

    toks = core_tokens(raw)
    if not toks:
        return []
    if len(toks) == 1:
        return [PersonName(toks[0], ())]

    out: list[PersonName] = [
        PersonName(toks[-1], tuple(toks[:-1])),   # FIRST MIDDLE LAST
        PersonName(toks[0], tuple(toks[1:])),     # LAST FIRST MIDDLE
    ]
    # De-dup a palindromic 2-token name read both ways.
    seen: set[PersonName] = set()
    uniq: list[PersonName] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def like_patterns(name: Optional[str]) -> list[str]:
    """ArcGIS LIKE patterns for an owner-field search, most-specific first.

    Individuals get one two-token pattern per ordering. The old surname-only
    broad fallback ('%SMITH%') is deliberately NOT emitted: capped at 25 rows it
    returns arbitrary strangers, never satisfies the strict matcher, and costs a
    request per lead.
    """
    pats: list[str] = []

    def _add(p: str) -> None:
        if p not in pats:
            pats.append(p)

    if is_entity(name):
        toks = [t.replace("'", "''") for t in distinctive_tokens(name)]
        if not toks:
            return []
        if len(toks) >= 2:
            _add(f"%{toks[0]}%{toks[1]}%")
            _add(f"%{toks[1]}%{toks[0]}%")
        _add(f"%{toks[0]}%")
        return pats

    for p in person_orderings(name):
        s = p.surname.replace("'", "''")
        if p.given:
            g = p.given[0].replace("'", "''")
            _add(f"%{s}%{g}%")
        else:
            _add(f"%{s}%")
    return pats


def _exact_token_match(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = set(core_tokens(a)), set(core_tokens(b))
    return bool(ta) and ta == tb


def strong_person_match(
    person: PersonName, gis_owner: Optional[str], *, require_all_given: bool = False,
) -> bool:
    """Surname in surname position AND first name in first-name position.

    `require_all_given` additionally demands that every one of the lead's given
    tokens appear somewhere in the GIS owner. It is applied to the SPECULATIVE
    'LAST FIRST MIDDLE' reading of an un-comma'd name, which is otherwise a
    false-positive factory: 'Casey William Gillespie' read as surname CASEY
    matches the unrelated 'CASEY WILLIAM MICHAEL' on position alone, but fails
    containment because GILLESPIE is nowhere in that owner string.
    """
    if not person.given:
        return False
    toks = core_tokens(primary_party(gis_owner))
    if len(toks) < 2:
        return False
    if toks[0] != person.surname or toks[1] != person.given[0]:
        return False
    if require_all_given:
        owner_set = set(toks)
        return all(g in owner_set for g in person.given)
    return True


def middle_conflict(lead_name: Optional[str], gis_owner: Optional[str]) -> bool:
    """True when BOTH names carry a spelled-out middle name and they disagree.

    'James Quentin Kirby' vs 'KIRBY JAMES A' -> False (GIS middle is an initial,
    which we cannot contradict). 'James Quentin Kirby' vs 'KIRBY JAMES HUNTER'
    -> True: same surname and first name, provably different middle names, so
    this is likely a different James Kirby. The match is still returned (a
    surname+firstname hit is real signal) but the flag rides along in the
    provenance so a human reviewing outreach can see the doubt.
    """
    gis = core_tokens(primary_party(gis_owner))
    if len(gis) < 3:
        return False
    gis_middles = {t for t in gis[2:] if len(t) > 1}
    if not gis_middles:
        return False
    for person in person_orderings(lead_name):
        if not strong_person_match(person, gis_owner):
            continue
        lead_middles = {t for t in person.given[1:] if len(t) > 1}
        if lead_middles and not (lead_middles & gis_middles):
            return True
    return False


def match_owner(lead_name: Optional[str], gis_owner: Optional[str]) -> Optional[str]:
    """Strict comparison. Returns 'exact', 'strong', or None (no match).

    Only these two verdicts are ever committed to a Listing — anything weaker
    would put the wrong person's address in front of outreach.
    """
    if not normalize_name(lead_name) or not normalize_name(gis_owner):
        return None

    primary = primary_party(gis_owner)
    if _exact_token_match(lead_name, primary) or _exact_token_match(lead_name, gis_owner):
        return "exact"

    if is_entity(lead_name) or is_entity(gis_owner):
        # Entities never get the positional rule — exact token-set equality only.
        return None

    for idx, person in enumerate(person_orderings(lead_name)):
        # idx 0 is the likely reading; anything after it is speculative and must
        # additionally contain every given token.
        if strong_person_match(person, gis_owner, require_all_given=idx > 0):
            return "strong"
    return None
