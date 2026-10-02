"""Split a divorce case caption string into structured plaintiff/defendant names.

GAP: raw['divorce']['cases'][] (built by enrichment_sc_divorce.py and
enrichment_nc_divorce.py) has always stored both spouses as ONE combined
caption string in the 'parties' key — e.g. 'JIMMIE LEE GLENN vs. JAMES L
GLENN' — never as two separate fields. This module is the one place that
splits it, the same way name_normalize.py is the one place that reconciles
owner-name conventions.

REAL FORMAT, confirmed 2026-10-02 against the live board via
board_stream.iter_board_rows() (read-only; never load_board() on this Mac):
every one of the 5,052 SC raw['divorce'] rows / 14,741 case 'parties' strings
currently on the board uses 'vs.' or 'vs' (case-insensitive, period
optional) as the separator — zero use a bare 'v.' or no separator at all.
(enrichment_nc_divorce.py's own caption-building path is reachable in code
but gated off by default (FORECLOSURE_NC_DIVORCE=0, blocked on an AWS-WAF
CAPTCHA per that module's docstring) and has never produced a live row, so
it is untested by the live sample — this module supports its parse window's
looser text-cut shape defensively, including a bare 'v.' separator, rather
than assuming SC's clean API field shape generalizes.)

CAPTION ORDER = Plaintiff vs. Defendant, filer first (the universal US
court-caption convention, not a guess): verified against the SAME live
sample by cross-checking each case's own `role` field (SC's
ParticipantRole, already on the case dict, independent of this parser) —
of 9,923 cases where the board row's owner_name's tokens overlapped
unambiguously with exactly one side of the caption, 9,887 (99.6%) agreed
that the first-named party's role was 'Plaintiff' and the second-named
party's was 'Defendant'. All 36 disagreements were short/bare-surname
owner_name rows ('JONES', 'SMITH') matched to an unnamed 'et al.'
participant that never appears in the two-name caption at all — a question
of which hidden party the lead's OWNER matched, not a wrong split of the
caption itself (and, per the signal-depth audit, genuinely unanswerable
from source data — not something this module tries to solve; see
docs/HANDOFF.md).

OTHER REAL VARIATIONS FOUND, both handled:
  * '"et al."' on either side ('TERESA COLLINS STILWELL, et al. vs. WILLIAM
    PATRICK STILWELL, et al.') marks a side that names more people than the
    one person printed. The named person is still returned (not discarded),
    with `additional_parties=True` so a consumer knows the string is not a
    complete party list.
  * A bare ' AND ' joining a second name onto one side with no further
    delimiter ('WALTER L NIX vs. PEARL T AND ROGER NIX' — two defendants
    sharing the NIX surname folded into one caption slot). The whole side
    text is kept as-is (not guessed apart) and `additional_parties=True` is
    set, for the same reason as 'et al.'.
  * Mixed casing: ALL-CAPS ('JIMMIE LEE GLENN') and Title Case ('Irina
    Popov vs. Zhenia Popov') both appear live; nothing here assumes one.

This module does NOT attempt to say which spouse keeps the property — the
signal-depth audit confirmed that is genuinely absent from every source feeding
this board, not a parsing gap, and forcing a guess at it is explicitly out of
scope (see docs/HANDOFF.md).
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict

# 'vs' or 'vs.' surrounded by whitespace, case-insensitive — the separator on
# every live caption. Tried first. Anchored on SURROUNDING WHITESPACE rather
# than \b: \b does not fire between the optional trailing '.' and the space
# after it (neither is a word character), so 'vs.' would otherwise leave a
# stray '. ' on the right-hand half after the split.
_VS_RE = re.compile(r"\s+vs\.?\s+", re.I)
# 'v.' REQUIRES the trailing period: a bare 'v' with no period is how this
# board's own name conventions write a middle initial ('MARY V SMITH'), so
# an unpunctuated lone 'v' is never treated as a separator — only tried as a
# fallback when no 'vs' is present at all.
_V_RE = re.compile(r"\s+v\.\s+", re.I)

_ET_AL_RE = re.compile(r",?\s*et\s*\.?\s*al\.?\s*$", re.I)
_AND_RE = re.compile(r"\bAND\b", re.I)


class DivorceParties(TypedDict):
    plaintiff: str
    defendant: str
    additional_parties: bool


def _clean_side(side: str) -> tuple[str, bool]:
    """Strip a trailing 'et al.' (flagging it); detect a bare ' AND '
    second-name join on this side (flagging it, text kept whole)."""
    side = side.strip().strip(",").strip()
    additional = False
    if _ET_AL_RE.search(side):
        additional = True
        side = _ET_AL_RE.sub("", side).strip().strip(",").strip()
    if _AND_RE.search(side):
        additional = True
    return side, additional


def split_divorce_caption(parties: Optional[str]) -> Optional[DivorceParties]:
    """'PLAINTIFF vs. DEFENDANT' -> {plaintiff, defendant, additional_parties}.

    Returns None when `parties` is empty or carries no recognized separator
    (defensive — every live caption observed has one; see module docstring).
    """
    text = (parties or "").strip()
    if not text:
        return None

    halves = _VS_RE.split(text, maxsplit=1)
    if len(halves) != 2:
        halves = _V_RE.split(text, maxsplit=1)
    if len(halves) != 2:
        return None

    left, left_extra = _clean_side(halves[0])
    right, right_extra = _clean_side(halves[1])
    if not left or not right:
        return None

    return {
        "plaintiff": left,
        "defendant": right,
        "additional_parties": left_extra or right_extra,
    }
