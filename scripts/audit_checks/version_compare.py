"""Version-compare invariants (audit 2026-10-09, area version_compare): what must hold on any board
that could replace the live one, checkable on ONE board in one pass (the two-board comparison itself
is scripts/compare_boards.py).

  version-heir-publishing-rule   a published row whose heir data breaks the owner's 2026-10-07 rule:
                                 an heir_candidates entry outside PUBLISHABLE_HEIR_RELATIONS, with a
                                 field outside PUBLISHED_FIELDS, a phone / e-mail / age / birth date,
                                 a minor, a name carrying digits or '@'; a phone or e-mail in any heir
                                 name list (obituary survivors, heir_naming_publication.named_heirs,
                                 heir_estate.heir_names); raw.obituary_match published. The rule is
                                 compare_boards.heir_findings (one definition for the gate and the
                                 compare). max 0: one row is one too many on a public dashboard.
  version-join-identity          a row whose only identity is its as-scraped fingerprint (no parcel
                                 id, no numbered street address, no case number): such a row cannot
                                 be followed from one board version to the next once any scraped
                                 field changes, so a comparison sees it leave and a stranger arrive.
                                 Reported with a generous ceiling (the share measured on the 10/7
                                 board plus headroom, see MAX_FINGERPRINT_ONLY_SHARE); a jump past it
                                 means a source stopped emitting parcels or addresses.
Memory: two counters and at most SAMPLE row references (parcel ids or opaque hashes).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SAMPLE = 8
#: Rows identified only by their fingerprint, as a share of all rows: 13.6% on the 10/7 board
#: (47,460 of 350,013 rows, measured by this check inside scripts/compare_boards.py's self-compare
#: of the published board, 2026-10-08); the ceiling is that plus about a third, so ordinary drift
#: passes and a source that stops emitting identity does not.
MAX_FINGERPRINT_ONLY_SHARE = 0.18


class _HeirRule:
    name = "version-heir-publishing-rule"

    def __init__(self):
        from compare_boards import heir_findings, row_ref
        self._findings, self._ref = heir_findings, row_ref
        self.checked = 0
        self.bad_rows = 0
        self.kinds: dict = {}
        self.sample: list = []

    def feed(self, row: dict) -> None:
        self.checked += 1
        bad, _note = self._findings(row)
        if bad:
            self.bad_rows += 1
            for k, v in bad.items():
                self.kinds[k] = self.kinds.get(k, 0) + v
            if len(self.sample) < SAMPLE:
                self.sample.append(self._ref(row))

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad_rows, "max_violations": 0,
                "ok": self.bad_rows == 0,
                "detail": (f"by kind {self.kinds}; sample {self.sample}" if self.bad_rows else "")}


class _JoinIdentity:
    name = "version-join-identity"

    def __init__(self):
        from compare_boards import join_keys
        self._keys = join_keys
        self.checked = 0
        self.fp_only = 0

    def feed(self, row: dict) -> None:
        self.checked += 1
        ks = self._keys(row)
        if all(k.startswith("fp:") for k in ks):
            self.fp_only += 1

    def finish(self) -> dict:
        mx = int(self.checked * MAX_FINGERPRINT_ONLY_SHARE)
        return {"name": self.name, "checked": self.checked, "violations": self.fp_only, "max_violations": mx,
                "ok": self.fp_only <= mx,
                "detail": f"{self.fp_only} rows have no parcel id, numbered address or case number"}


def make_checks() -> list:
    return [_HeirRule(), _JoinIdentity()]
