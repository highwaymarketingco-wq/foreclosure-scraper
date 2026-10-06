"""divorce, South Carolina: labelled `wall`, never queried.

The source that could check an SC divorce claim is the SC Public Index
(publicindex.sccourts.org). Its terms restrict bulk and automated querying, so no code here
queries it, ever: this verifier makes no network call and answers `wall` for every SC row that
carries a divorce claim, so the claim reads honestly as "not independently verifiable" rather
than as checked (VERIFICATION_PIPELINE_SPEC.md section 1). A wall verdict changes no score.

The template for any walled source: WALL = True, GOVERNS = (), verify() returns
result(..., "wall", {"reason": ...}) without touching `client`. A per-lead human check of a
specific case is the human lane's job (verification_human_lane.py covers NC eCourts / NC SOS).

FINDINGS.md #7 found 0.0% of sampled SC divorce flags real (n=58/5,052); the scorer already
requires a positive middle-name agreement (distress_score._divorce_signal), which is the
code-side fix. This file only labels what is left.
"""
from __future__ import annotations

from typing import Optional

from ..core import VerificationResult, result

SIGNAL = "divorce"
VERSION = "v1"
TTL_DAYS = 365         # nothing changes until the wall does; re-labelled yearly
SOURCE = "publicindex.sccourts.org"
GOVERNS: tuple[str, ...] = ()
WALL = True

_NAME = __name__.rsplit(".", 1)[-1]
REASON = ("SC Public Index restricts bulk/automated querying in its terms of use; not queried "
          "by code. Check a specific case by hand at publicindex.sccourts.org.")


def _divorce(row: dict) -> Optional[dict]:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    dv = raw.get("divorce")
    return dv if isinstance(dv, dict) else None


def applies(row: dict) -> bool:
    """SC rows that carry a divorce claim: a real-positive raw['divorce'] (case_count, or a
    non-empty cases list: the corrected check, not bare presence) or a divorce_notice row."""
    if str(row.get("state") or "").strip().upper() != "SC":
        return False
    dv = _divorce(row)
    if dv is not None and (dv.get("case_count") or dv.get("cases")):
        return True
    return row.get("listing_type") == "divorce_notice"


async def verify(row: dict, client=None) -> VerificationResult:
    dv = _divorce(row) or {}
    cases = [c.get("case_number") for c in (dv.get("cases") or []) if isinstance(c, dict)]
    return result(SIGNAL, "wall", {"reason": REASON, "case_count": dv.get("case_count"),
                                   "case_numbers": [c for c in cases if c][:5]},
                  source=SOURCE, version=VERSION, verifier=_NAME)
