"""Name logic for the intake sheet. Pure functions, no I/O.

THE FULL-NAME RULE (the attorney's, and the lawyer-package rule). A death-index entry is called a
FIT for the owner of record only when the given name, the middle name and the surname all agree,
word for word. Anything less is a CANDIDATE, listed with the reason it may not fit: a different
or missing middle name, a middle name given only as an initial, a different given name, a
different suffix, a married woman indexed under her husband's name. A fit is still a name fit,
never a finding of identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
#: words on a county roll that say the owner of record is a dead person's heirs or estate
_MARKERS = [
    (re.compile(r"\(\s*HEIRS?\s*\)|\bHEIRS?\b|\bHRS\b"), "HEIRS"),
    (re.compile(r"\bESTATE\s+OF\b|\bEST\s+OF\b"), "ESTATE OF"),
    (re.compile(r"\bESTATE\b"), "ESTATE"),
    (re.compile(r"\bDECEASED\b|\bDEC'?D\b|\bDECD\b"), "DECEASED"),
]
_NOISE = re.compile(r"\(\s*HEIRS?\s*\)|\bHEIRS?\b|\bHRS\b|\bESTATE\s+OF\b|\bEST\s+OF\b|\bESTATE\b|"
                    r"\bDECEASED\b|\bDEC'?D\b|\bDECD\b|\bET\s*AL\b|\bET\s*UX\b|\bET\s*VIR\b|\bLIFE\s+EST(ATE)?\b|"
                    r"\bC/O\b|\bTRUSTEES?\b|\bTR\b")
_ENTITY = re.compile(r"\b(LLC|L\.L\.C|INC|CORP|CORPORATION|COMPANY|CO|LP|LLP|LTD|BANK|TRUST|CHURCH|"
                     r"ASSOCIATION|ASSN|ASSOC|COUNTY|CITY|TOWN|STATE|UNITED STATES|AUTHORITY|PARTNERS|"
                     r"PARTNERSHIP|HOLDINGS|PROPERTIES|INVESTMENTS|MINISTRIES|FELLOWSHIP|SOCIETY|"
                     r"FOUNDATION|DEPARTMENT|DEPT|HOUSING|DEVELOPMENT|ENTERPRISES|GROUP|FUND|CLUB)\b")


def clean(s: Optional[str]) -> str:
    s = (s or "").upper().replace(".", " ").replace(" ", " ")
    s = re.sub(r"[^A-Z0-9,'&;/()\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def roll_markers(owner: Optional[str]) -> list[str]:
    """The heirs / estate words on an owner-of-record string, in the order of _MARKERS."""
    s = clean(owner)
    out: list[str] = []
    for rx, word in _MARKERS:
        if rx.search(s) and word not in out:
            if word == "ESTATE" and "ESTATE OF" in out:
                continue
            out.append(word)
    return out


def is_entity(name: Optional[str]) -> bool:
    return bool(_ENTITY.search(clean(name)))


@dataclass
class PersonName:
    last: str
    given: list[str] = field(default_factory=list)     # first, then middle names
    suffix: Optional[str] = None
    mrs: bool = False
    raw: str = ""
    role: Optional[str] = None       # the register's annotation after '/': EXR, TR, COMR, ...
    deceased: bool = False           # annotated '/ DECD' in the index

    @property
    def first(self) -> str:
        return self.given[0] if self.given else ""

    @property
    def middles(self) -> list[str]:
        return self.given[1:]

    def indexed(self) -> str:
        """LAST, FIRST MIDDLE [SUFFIX]: the register's own way of writing a name."""
        tail = " ".join(self.given + ([self.suffix] if self.suffix else []))
        return f"{self.last}, {tail}".strip().rstrip(",")

    def tokens(self) -> set[str]:
        return {self.last, *self.given}


def _split_suffix(words: list[str]) -> tuple[list[str], Optional[str], bool]:
    suf, mrs, keep = None, False, []
    for w in words:
        if w in SUFFIXES and suf is None:
            suf = w
        elif w in ("MRS", "MRS'"):
            mrs = True
        else:
            keep.append(w)
    return keep, suf, mrs


_DECD = {"DECD", "DEC'D", "DECEASED", "DEC"}


def parse_indexed(name: Optional[str]) -> Optional[PersonName]:
    """'PENDLE, ANNA MARIE' -> PersonName('PENDLE', ['ANNA', 'MARIE']). The register writes an
    annotation after a slash ('PENDLE, ANNA M/ EXRX', 'PENDLE, JOHN/ JR', 'PENDLE, JOHN/ DECD'):
    a generational suffix stays a suffix, DECD sets `deceased`, anything else is the `role`.
    None for an entity or a string without the register's comma."""
    s = clean(name)
    if s.startswith("-") and "," not in s and not is_entity(s):
        # the old index writes some names surname first with a leading '-' and no comma
        # ('-DOE JOHN Q'): read as LAST FIRST MIDDLE
        w = s.lstrip("- ").split(None, 1)
        s = f"{w[0]}, {w[1]}" if len(w) == 2 else ""
    if not s or "," not in s or is_entity(s.split("/")[0]):
        return None
    last, _, rest = s.partition(",")
    main, _, note = rest.partition("/")
    words = [w for w in main.split() if w and w not in ("&",)]
    words, suf, mrs = _split_suffix(words)
    role, dead = [], False
    for w in note.replace("&", " ").split():
        if w in SUFFIXES and suf is None:
            suf = w
        elif w in _DECD:
            dead = True
        else:
            role.append(w)
    last = last.strip()
    if not last or not words:
        return None
    return PersonName(last=last, given=words, suffix=suf, mrs=mrs, raw=name or "",
                      role=" ".join(role) or None, deceased=dead)


def parse_roll(name: Optional[str], order: str) -> Optional[PersonName]:
    """An owner-of-record string without a comma, read in the stated order:
    'last_first' (the county layer's usual 'PENDLE ANNA MARIE') or 'first_last'
    ('ANNA MARIE PENDLE (HEIRS)', the usual way an heirs entry is written)."""
    s = _NOISE.sub(" ", clean(name))
    s = re.sub(r"[(),]", " ", s)
    words = [w for w in s.split() if w]
    words, suf, mrs = _split_suffix(words)
    if len(words) < 2 or is_entity(name):
        return None
    if order == "last_first":
        return PersonName(last=words[0], given=words[1:], suffix=suf, mrs=mrs, raw=name or "")
    return PersonName(last=words[-1], given=words[:-1], suffix=suf, mrs=mrs, raw=name or "")


def roll_tokens(name: Optional[str]) -> set[str]:
    s = _NOISE.sub(" ", clean(name))
    s = re.sub(r"[(),;&]", " ", s)
    return {w for w in s.split() if w and w not in SUFFIXES}


def split_owners(owner: Optional[str]) -> list[str]:
    """'SMITH JOHN;SMITH MARY' / 'SMITH JOHN & MARY' -> the separate owner strings (the second
    of a '&' pair inherits nothing: it is returned as written)."""
    parts = re.split(r";|\s&\s|\sAND\s", clean(owner))
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def _is_initial(w: str) -> bool:
    return len(w) == 1


def middle_relation(a: list[str], b: list[str]) -> tuple[str, str]:
    """Compare two middle-name lists. Returns (relation, words):
    equal | differs | initial_only | missing_record | missing_entry."""
    if not a and not b:
        return "equal", ""
    if not a:
        return "missing_record", ""
    if not b:
        return "missing_entry", ""
    if len(a) != len(b):
        if all(_is_initial(w) for w in a + b):
            return "differs", ""
        return "differs", ""
    initial = False
    for x, y in zip(a, b):
        if x == y:
            continue
        if (_is_initial(x) or _is_initial(y)) and x[0] == y[0]:
            initial = True
            continue
        return "differs", ""
    return ("initial_only", "") if initial else ("equal", "")


@dataclass
class Fit:
    verdict: str                      # fit | candidate | other_person
    reasons: list[str] = field(default_factory=list)


def death_fit(record: PersonName, entry: PersonName) -> Fit:
    """The full-name rule (module docstring) for one indexed decedent name."""
    if record.last != entry.last:
        return Fit("other_person", [f"surname on the entry is {entry.last}, not {record.last}"])
    reasons: list[str] = []
    if record.first != entry.first:
        reasons.append(f"given name differs (entry: {entry.first}; record: {record.first})")
    if entry.mrs:
        reasons.append("the entry indexes a married woman under this name (MRS), not this person")
    if (record.suffix or entry.suffix) and record.suffix != entry.suffix:
        reasons.append(f"suffix differs (entry: {entry.suffix or 'none'}; record: {record.suffix or 'none'})")
    rel, _ = middle_relation(record.middles, entry.middles)
    em, rm = " ".join(entry.middles), " ".join(record.middles)
    if rel == "differs":
        reasons.append(f"middle name differs (entry: {em or 'none'}; record: {rm or 'none'})")
    elif rel == "initial_only":
        reasons.append(f"middle name agrees only as an initial (entry: {em}; record: {rm})")
    elif rel == "missing_record":
        reasons.append(f"the owner-of-record name gives no middle name, so a full-name fit cannot be shown "
                       f"(entry middle name: {em})")
    elif rel == "missing_entry":
        reasons.append(f"the entry gives no middle name (record middle name: {rm})")
    if not record.middles and not entry.middles and not reasons:
        reasons.append("neither name has a middle name, so a full-name fit cannot be shown")
    return Fit("candidate" if reasons else "fit", reasons)


def name_compat(searched: PersonName, indexed: PersonName) -> Optional[str]:
    """For a chain search: 'full' when the indexed name equals the searched name word for word,
    'compatible' when nothing conflicts (an initial, a missing middle name), None otherwise."""
    if searched.last != indexed.last or searched.first != indexed.first:
        return None
    if (searched.suffix or indexed.suffix) and searched.suffix != indexed.suffix:
        return None
    if indexed.mrs != searched.mrs:
        return None
    rel, _ = middle_relation(searched.middles, indexed.middles)
    if rel == "equal":
        return "full"
    if rel in ("initial_only", "missing_record", "missing_entry"):
        return "compatible"
    return None
