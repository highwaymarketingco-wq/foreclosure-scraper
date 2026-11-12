"""Valuation invariants (audit 2026-10-09, area valuation; docs/audit_2026-10-09/valuation.md).

  valuation-outlier-explained   a published ARV over $1M, over 8x the parcel's largest 100%-basis
                                county value (market value, assessor appraisal, tax value), or over
                                5x the highest sale price among the comps cited on the row, that
                                does not carry calc.arv_basis_check {"verdict": "explained"} with a
                                basis. valuation.calc withholds the unexplained ones (flag
                                arv_unexplained_outlier); this recomputes the three tests from the
                                published fields, so a writer that bypasses calc is caught too.
                                The 2026-10-08 gated checkpoint as stored: 4,508 (no basis check
                                existed); re-priced by the guarded calc: 0 (3,705 explained, 803
                                withheld). max 0.
  valuation-hot-arv-supported   a HOT row whose published ARV has no support: no cited comp sold
                                within 2x of it, no recorded-sales basket (>= 3 sales) it was
                                priced from, and no county value it sits within 0.4x-3.5x of.
                                HOT is the call list; an ARV nothing on the row backs is not a
                                reason to call. max 0 (0 of 46 on the 10/7 board, 0 of 67 on the
                                10/8 checkpoint).
  valuation-comps-kind-fits     a row whose cited comps are all of a kind that does not fit the
                                subject (validation._validate_comps' rule: townhouse and single
                                family trade together, nothing else crosses). 120 on the 10/7 board
                                (sfr comps on lots), 0 on the 10/8 checkpoint. max 0.
  valuation-comps-age           a row citing a comp that sold more than COMPS_CARRY_MAX_AGE_DAYS
                                (365) before today, or a carried comp that does not show its age.
                                enrichment_comps.age_comps() prunes and labels them after every
                                comps phase. max 0.
DETAIL_KEYS: comps and cama live in the lazy-detail sidecar of a published board.
Memory: counters and at most SAMPLE row references per check.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DETAIL_KEYS = ("comps", "cama")
SAMPLE = 8
HOT_SUPPORT_COUNTY_BAND = (0.4, 3.5)   # 3.5 = calc.ARV_ANCHOR_HARD_MULT_IMPROVED
HOT_SUPPORT_COMP_MULT = 2.0


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _calc(row: dict) -> dict:
    c = _raw(row).get("calc")
    return c if isinstance(c, dict) else {}


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def county_values(row: dict) -> list[float]:
    """calc._county_values on a published row: market value, assessor appraisal, tax value
    (100% basis; assessed_value is left out, in SC it is a 4%/6% ratio value)."""
    cama = _raw(row).get("cama") if isinstance(_raw(row).get("cama"), dict) else {}
    out = []
    for v in (row.get("market_value"), cama.get("appraised_value"), row.get("tax_value")):
        v = _f(v)
        if v and v > 1000:
            out.append(v)
    return out


def comp_prices(row: dict) -> list[float]:
    out = []
    for c in _raw(row).get("comps") or []:
        if isinstance(c, dict):
            p = _f(c.get("sold_price"))
            if p and p > 0:
                out.append(p)
    return out


def _ref(row: dict) -> str:
    try:
        from compare_boards import row_ref
        return row_ref(row)
    except Exception:  # noqa: BLE001
        return f"{row.get('state')}|{row.get('county')}|{row.get('parcel_id') or '?'}"


class _Base:
    name = ""
    max_violations = 0

    def __init__(self):
        self.checked = 0
        self.violations = 0
        self.sample: list = []
        self.kinds: dict = {}

    def _bad(self, row: dict, kind: str = "") -> None:
        self.violations += 1
        if kind:
            self.kinds[kind] = self.kinds.get(kind, 0) + 1
        if len(self.sample) < SAMPLE:
            self.sample.append(_ref(row))

    def finish(self) -> dict:
        detail = ""
        if self.violations:
            detail = (f"by kind {self.kinds}; " if self.kinds else "") + f"sample {self.sample}"
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations, "detail": detail}


class OutlierExplained(_Base):
    name = "valuation-outlier-explained"

    def __init__(self):
        super().__init__()
        from foreclosure_scraper.valuation.calc import outlier_triggers
        self._triggers = outlier_triggers

    def feed(self, row: dict) -> None:
        calc = _calc(row)
        arv = _f(calc.get("arv_expected"))
        if not arv:
            return
        self.checked += 1
        cv, cp = county_values(row), comp_prices(row)
        trig = self._triggers(arv, max(cv) if cv else None, max(cp) if cp else None)
        if not trig:
            return
        chk = calc.get("arv_basis_check")
        if not (isinstance(chk, dict) and chk.get("verdict") == "explained" and chk.get("basis")):
            self._bad(row, trig[0].split(" the ")[0].replace("$", ""))


class HotArvSupported(_Base):
    name = "valuation-hot-arv-supported"

    def feed(self, row: dict) -> None:
        ds = _raw(row).get("distress_stack")
        if not (isinstance(ds, dict) and ds.get("tier") == "HOT"):
            return
        arv = _f(_calc(row).get("arv_expected"))
        if not arv:
            return
        self.checked += 1
        raw = _raw(row)
        lo, hi = HOT_SUPPORT_COUNTY_BAND
        if any(lo <= arv / v <= hi for v in county_values(row)):
            return
        if any(arv / HOT_SUPPORT_COMP_MULT <= p <= arv * HOT_SUPPORT_COMP_MULT for p in comp_prices(row)):
            return
        for k in ("recorded_comps", "recorded_ratio_comps"):
            b = raw.get(k)
            if isinstance(b, dict) and (_f(b.get("count")) or 0) >= 3:
                return
        self._bad(row)


class CompsKindFits(_Base):
    name = "valuation-comps-kind-fits"

    def __init__(self):
        super().__init__()
        from foreclosure_scraper.validation import _canonical_kind
        self._canon = _canonical_kind

    def feed(self, row: dict) -> None:
        comps = _raw(row).get("comps")
        if not isinstance(comps, list) or not comps:
            return
        self.checked += 1
        subj = self._canon(str(row.get("property_kind") or ""))
        if not subj or subj == "unknown":
            return
        kinds = {self._canon(c.get("kind")) for c in comps if isinstance(c, dict) and c.get("kind")}
        kinds.discard("")
        ok_pairs = {("single_family", "townhouse"), ("townhouse", "single_family")}
        if kinds and all(k != subj and (subj, k) not in ok_pairs for k in kinds):
            self._bad(row, f"{subj}<-{','.join(sorted(kinds))}")


class CompsAge(_Base):
    name = "valuation-comps-age"

    def __init__(self, today: date | None = None):
        super().__init__()
        from foreclosure_scraper.enrichment_comps import COMPS_CARRY_MAX_AGE_DAYS, comp_age_days
        self._max, self._age, self._today = COMPS_CARRY_MAX_AGE_DAYS, comp_age_days, today or date.today()

    def feed(self, row: dict) -> None:
        comps = _raw(row).get("comps")
        if not isinstance(comps, list) or not comps:
            return
        self.checked += 1
        for c in comps:
            if not isinstance(c, dict):
                continue
            if c.get("carried") and c.get("age_days") is None:
                self._bad(row, "carried without age")
                return
            age = self._age(c, self._today)
            if age is not None and age > self._max:
                self._bad(row, f"older than {self._max} days")
                return


def make_checks() -> list:
    return [OutlierExplained(), HotArvSupported(), CompsKindFits(), CompsAge()]
