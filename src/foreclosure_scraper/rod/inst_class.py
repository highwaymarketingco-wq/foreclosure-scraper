"""Canonical class for a recorded-deed instrument label.

Recorders label the same instrument many ways. CCHS serves short vendor codes
(TR/D, COM/D, SHF/D) and its dictionary spells them out with or without an
apostrophe (TRUSTEES DEED, COMMISSIONER'S DEED). Aumentum and Logan serve full
text. rod.models.normalize_doc_type keeps the SHORTEST bucket key, so "TAX DEED"
and "SHERIFF DEED" used to collapse to a bare "DEED", and the short vendor codes
matched no keyword list at all (rod.classify._KEEP, the deed-chain rod_docs
filter, repeat_tax_loss's _LOSS_DOC_TYPES).

This module is the one place that maps any of those labels to a canonical
inst_class, so callers compare classes instead of matching substrings. The class
names are the ones in docs/deed_index_scoping_2026-09-20.md, section (d).

classify_instrument() takes SEVERAL labels because a stored row can carry two:
the vendor code in raw["ki"] and the normalized doc_type. The strongest class
wins (loss classes first), so a row whose doc_type was flattened to "DEED" still
classifies from its "TAX DEED" code.
"""
from __future__ import annotations

import re

TRUSTEE_DEED = "TRUSTEE_DEED"
COMMISSIONER_DEED = "COMMISSIONER_DEED"
SHERIFF_DEED = "SHERIFF_DEED"
MASTER_DEED = "MASTER_DEED"
TAX_DEED = "TAX_DEED"
QUITCLAIM = "QUITCLAIM"
DEED = "DEED"
DISTRIBUTION_DEED = "DISTRIBUTION_DEED"
EXECUTOR_DEED = "EXECUTOR_DEED"
DEED_OF_SEPARATION = "DEED_OF_SEPARATION"
OTHER = "OTHER"

#: Instruments that prove an owner lost a parcel to a forced sale.
LOSS_CLASSES = frozenset({TRUSTEE_DEED, COMMISSIONER_DEED, SHERIFF_DEED, MASTER_DEED, TAX_DEED})

_SPECIFIC = frozenset({QUITCLAIM, DISTRIBUTION_DEED, EXECUTOR_DEED, DEED_OF_SEPARATION})

# Exact vendor codes, after _norm(). Full-text labels go through _TEXT_RULES.
_CODES = {
    "TR/D": TRUSTEE_DEED, "TR/DEED": TRUSTEE_DEED,
    "COM/D": COMMISSIONER_DEED, "COMM/D": COMMISSIONER_DEED, "COMM/DEED": COMMISSIONER_DEED,
    "SHF/D": SHERIFF_DEED,
    "QCD": QUITCLAIM, "QC": QUITCLAIM,
    "D/SEP": DEED_OF_SEPARATION, "DEED/SEP": DEED_OF_SEPARATION,
    "DEED-SEP": DEED_OF_SEPARATION, "M/SEP": DEED_OF_SEPARATION,
    "ADM-DEED": EXECUTOR_DEED, "EXRX-DEED": EXECUTOR_DEED, "EXR DEED": EXECUTOR_DEED,
    "EXRS DEED": EXECUTOR_DEED, "GDN DEED": EXECUTOR_DEED, "GDNS DEED": EXECUTOR_DEED,
    "C/D": DEED, "DEED": DEED,
}

# Checked in order, first hit wins. Loss classes come first so "SHERIFFS DEED"
# never falls through to the generic deed rule. A trustee rule needs the word
# DEED (or "UPON SALE"): "SUBSTITUTION OF TRUSTEE" and "SUBSTITUTE TRUSTEE PRE-95"
# are notices that precede a sale, not the conveyance after it.
_TEXT_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (TAX_DEED, re.compile(r"\bTAX (?:SALE )?DEED\b")),
    (SHERIFF_DEED, re.compile(r"\bSHERIFFS? (?:SALE )?DEED\b")),
    (MASTER_DEED, re.compile(r"\bMASTERS? (?:IN EQUITY )?DEED\b|\bMASTER IN EQUITY\b")),
    # A clerk of court's deed after a judicial or tax sale is the same officer's
    # deed as a commissioner's, and takes the same loser rule.
    (COMMISSIONER_DEED, re.compile(r"\bCOMMISSIONERS? DEED\b|\bCLERKS? DEED\b")),
    (TRUSTEE_DEED, re.compile(
        r"\bTRUSTEES? (?:DEED|UPON SALE)\b|\bFORECLOSURE DEED\b|\bDEED UNDER POWER OF SALE\b")),
    (DISTRIBUTION_DEED, re.compile(r"\bDEED OF DISTRIBUTION\b|\bDISTRIBUTION DEED\b")),
    (EXECUTOR_DEED, re.compile(
        r"\b(?:EXECUTORS?|EXECUTRIX|ADMINISTRATORS?|GUARDIANS?|PERSONAL REPRESENTATIVES?)\b.*\bDEED\b")),
    (DEED_OF_SEPARATION, re.compile(r"\bDEED OF SEPARATION\b|\bMEMORANDUM OF SEPARATION\b")),
    (QUITCLAIM, re.compile(r"\bQUIT ?CLAIM\b|\bQC DEED\b")),
)

# A label that says DEED but is not a conveyance of the fee.
_NOT_A_DEED = re.compile(
    r"DEED OF TRUST|\bTRUST\b|RELEASE|SUBORDINATION|TIMBER|CEMET|MORTGAGE|EASEMENT|ESMT|\bPLAT\b")
_HAS_DEED = re.compile(r"\bDEED\b")


def _norm(label) -> str:
    """Upper-case, drop apostrophes ("COMMISSIONER'S" -> "COMMISSIONERS"), fold
    underscores and runs of whitespace."""
    s = str(label or "").upper().replace("’", "'").replace("&APOS;", "'")
    s = s.replace("'", "")
    return re.sub(r"[_\s]+", " ", s).strip()


def _classify_one(label) -> str:
    s = _norm(label)
    if not s:
        return OTHER
    hit = _CODES.get(s)
    if hit:
        return hit
    for cls, rx in _TEXT_RULES:
        if rx.search(s):
            return cls
    if _HAS_DEED.search(s) and not _NOT_A_DEED.search(s):
        return DEED
    return OTHER


def _rank(cls: str) -> int:
    if cls in LOSS_CLASSES:
        return 0
    if cls in _SPECIFIC:
        return 1
    if cls == DEED:
        return 2
    return 3


def classify_instrument(*labels) -> str:
    """Canonical inst_class for a vendor code and/or a full-text label.

    Pass every label the row carries. The strongest class wins, loss classes
    first, so a doc_type that normalize_doc_type flattened to "DEED" still
    classifies from the raw "TAX DEED" beside it. Returns OTHER when nothing
    matches (mortgages, liens, releases, notices).
    """
    best = OTHER
    for label in labels:
        cls = _classify_one(label)
        if _rank(cls) < _rank(best):
            best = cls
    return best


def is_loss_class(inst_class: str | None) -> bool:
    return inst_class in LOSS_CLASSES


def is_deed_class(inst_class: str | None) -> bool:
    """Any conveyance class (loss, quitclaim, executor, distribution, separation, plain)."""
    return bool(inst_class) and inst_class != OTHER
