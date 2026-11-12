"""Identity invariants (audit 2026-10-09, area identity): every row is exactly one property, its own
source record's, with an owner the county roll does not contradict unexplained.
docs/audit_2026-10-09/identity.md has the measurements; src/foreclosure_scraper/identity.py the
rules (the same functions the pipeline's identity pass applies).

  identity-no-duplicate-properties  rows that are the same property as another row (identity.
                                    duplicate_groups: one valid parcel or one numbered address,
                                    partitioned by property address; an owner-mailing address
                                    and an aged copy of the same source record are not a second
                                    property). max 0.
  identity-fused-own-record         rows whose own source record names a parcel of the row's
                                    numbering system that is not the row's (identity.
                                    fused_record). max 0 once the identity pass is wired.
  identity-owner-conflict-stamped   rows whose owner every county-roll owner on the row
                                    contradicts (identity.owner_verdict) without
                                    raw['owner_conflict']. max 0 once the identity pass is wired.
  identity-multi-address-parcels    informational: identity groups that hold 2+ properties (an
                                    apartment complex's units, a parcel's two structures, a master
                                    PIN's lots). Reported, not a defect (max unbounded).

Memory: one small record per identified row (hashes of its key, property address, mailing and
own-record streets, record key), grouped at finish; capped samples of parcel ids.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from foreclosure_scraper import identity as idn  # noqa: E402

SAMPLE = 8


def _ref(row: dict) -> str:
    return f"{row.get('state')}:{row.get('county')}:{row.get('parcel_id') or '-'}"


class _Check:
    name = ""
    max_violations = 0

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.by: Counter = Counter()
        self.samples: list[str] = []

    def _bad(self, ref: str, what: str, n: int = 1) -> None:
        self.violations += n
        self.by[what] += n
        if len(self.samples) < SAMPLE:
            self.samples.append(f"{ref}:{what}")

    def finish(self) -> dict:
        top = ", ".join(f"{k} {v}" for k, v in self.by.most_common(6))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": f"{top}; e.g. {'; '.join(self.samples)}" if self.violations else "none"}


class Duplicates(_Check):
    name = "identity-no-duplicate-properties"

    def __init__(self, multi: "MultiAddress") -> None:
        super().__init__()
        self.groups: dict[int, list] = defaultdict(list)
        self.refs: dict[int, str] = {}
        self.multi = multi
        self.n = 0

    def feed(self, row: dict) -> None:
        i = self.n
        self.n += 1
        if idn.fused_record(row):
            return
        k = idn.ident_key(row)
        if not k:
            return
        self.checked += 1
        hk = hash(k)
        self.groups[hk].append(idn.view(i, row, hash))
        if hk not in self.refs and len(self.refs) < 400_000:
            self.refs[hk] = _ref(row)

    def finish(self) -> dict:
        for hk, views in self.groups.items():
            if len(views) < 2:
                continue
            if len({v["tag"] for v in views if v["tag"]}) >= idn.FUSED_KEY_ADDRESSES:
                self.multi.fused_keys += 1
                continue
            parts = idn.partition(views)
            if len(parts) > 1:
                self.multi.found(self.refs.get(hk, "?"), len(parts))
            for p in parts:
                if len(p) > 1:
                    aged = sum(views[x]["aged"] for x in p)
                    what = "aged_copy" if aged else "live_twin"
                    self._bad(self.refs.get(hk, "?"), what, len(p) - 1)
        self.groups.clear()
        return super().finish()


class MultiAddress(_Check):
    name = "identity-multi-address-parcels"
    max_violations = 10 ** 9

    def __init__(self) -> None:
        super().__init__()
        self.fused_keys = 0

    def feed(self, row: dict) -> None:  # filled by Duplicates.finish (one grouping pass)
        return None

    def found(self, ref: str, parts: int) -> None:
        self.checked += 1
        self._bad(ref, f"{parts}_properties")

    def finish(self) -> dict:
        res = super().finish()
        res["detail"] = f"{res['detail']}; keys of {idn.FUSED_KEY_ADDRESSES}+ addresses (master/placeholder ids) {self.fused_keys}"
        return res


class FusedOwnRecord(_Check):
    name = "identity-fused-own-record"

    def feed(self, row: dict) -> None:
        if not idn.own_blocks(row):
            return
        self.checked += 1
        other = idn.fused_record(row)
        if other:
            self._bad(_ref(row), "own_record_names_other_parcel")


class OwnerConflictStamped(_Check):
    name = "identity-owner-conflict-stamped"

    def feed(self, row: dict) -> None:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        if not raw:
            return
        self.checked += 1
        v = idn.owner_verdict(row)
        if v is None:
            return
        if not isinstance(raw.get("owner_conflict"), dict):
            self._bad(_ref(row), f"unstamped_{v['decision']}")


def make_checks() -> list:
    multi = MultiAddress()
    # MultiAddress is listed after Duplicates so its finish() runs after Duplicates filled it
    return [Duplicates(multi), multi, FusedOwnRecord(), OwnerConflictStamped()]
