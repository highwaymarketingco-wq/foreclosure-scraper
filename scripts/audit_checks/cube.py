"""Coverage-cube invariants (audit 2026-10-09, area cube_remeasure). The 82-column x 146-county grid
(scripts/gap_matrix.py) is at 100% when every cell carries a verdict: filled / checked, walled,
no source, or not applicable. These checks keep the three defects the remeasure found from
coming back.

  cube-unscreened-county-signal-cells  county-, state- and feed-scope signal cells where code that
                                       covers the county exists (a county-named producer or a
                                       declared statewide source), the column applies, the board
                                       has no hit there and the run's screen ledger
                                       (docs/screen_ledger.json, screen_ledger.py) does not record
                                       the screen. Each is a cell that reads "never checked" though
                                       the run may have checked it ("screened, none found" not
                                       stamped). Ratchet: may not exceed the 2026-10-09 count.
  cube-flip-row-outside-flip-scope     a flip-type row (foreclosure_sale, auction, sheriff_sale,
                                       hoa_sale, reo) whose known county is outside the owner's flip
                                       scope (18 footprint counties + oceanfront beach-drive
                                       counties). The run drops them; the cube treats those cells as
                                       not applicable, so one on the board means the two disagree.
  cube-negative-wrapper-dated          a row-scope negative result (incarceration_check, bop_check,
                                       marriage_license, divorce) without its check date: a
                                       negative that cannot age out counts as checked forever.

Memory: one Counter per (state, county, column) for the scoped columns (146 x 31) and capped
samples of parcel ids. Counts only.
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SAMPLE = 8
#: 2026-10-09 reconciled pre-publish checkpoint (383,378 rows), no screen ledger yet:
#: docs/audit_2026-10-09/cube_remeasure.md. The ledger written beside run_health.json from the
#: next run on is expected to take this down; it may never go up.
UNSCREENED_BASELINE = 652
FLIP_OUTSIDE_BASELINE = 0
#: marriage_license wrappers with neither checked_at nor a license date on the 10/9 checkpoint:
#: leftovers of the retired marriage-license module (unwired_enrichers RETIRED_KEY_BASELINE). The
#: cube no longer counts them as checked (gap_matrix.checked_columns); they may not grow.
UNDATED_NEGATIVE_BASELINE = 5
SCREEN_LEDGER = _REPO / "docs" / "screen_ledger.json"

_GM = None
_CODE = None


def _code() -> dict:
    """gap_matrix.built_in_code(), once per process (it greps every producer file)."""
    global _CODE
    if _CODE is None:
        _CODE = _gm().built_in_code()
    return _CODE


def _gm():
    """scripts/gap_matrix.py, loaded once (it is a script, not a package module)."""
    global _GM
    if _GM is None:
        if "gap_matrix" in sys.modules:
            _GM = sys.modules["gap_matrix"]
        else:
            spec = importlib.util.spec_from_file_location("gap_matrix", _REPO / "scripts" / "gap_matrix.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["gap_matrix"] = mod
            spec.loader.exec_module(mod)
            _GM = mod
    return _GM


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _ident(row: dict) -> str:
    return str(row.get("parcel_id") or row.get("case_number") or row.get("source") or "?")[:40]


class _Check:
    name = ""
    max_violations = 0

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.sample: list[str] = []

    def _bad(self, row: dict) -> None:
        self.violations += 1
        if len(self.sample) < SAMPLE:
            self.sample.append(_ident(row))

    def result(self, detail: str) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": detail}


class UnscreenedCountySignalCells(_Check):
    name = "cube-unscreened-county-signal-cells"
    max_violations = UNSCREENED_BASELINE

    def __init__(self, ledger_path: Path = SCREEN_LEDGER, today: Optional[date] = None) -> None:
        super().__init__()
        gm = _gm()
        self.gm = gm
        self.cols = [c for c, s in gm.SPECS.items() if s.kind == "signal" and s.scope in ("county", "state", "feed")]
        self.app: Counter = Counter()
        self.pos: Counter = Counter()
        self.slug_lt: set = set()
        self.slug_key: set = set()
        self.ledger_path = Path(ledger_path)
        self.today = today or date.today()

    def feed(self, row: dict) -> None:
        gm = self.gm
        self.checked += 1
        raw = _raw(row)
        key = gm.county_key(row)
        if key[1] == gm.UNKNOWN:
            return
        owner = gm.owner_columns(row)
        pos = gm.positive_columns(row, owner, {}, self.today)
        app = gm.applicable_columns(row, gm.row_rules(row, raw, owner))
        for c in self.cols:
            if c in app:
                self.app[(key, c)] += 1
                if c in pos:
                    self.pos[(key, c)] += 1
        src = str(row.get("source") or "")
        self.slug_lt.add((src, str(row.get("listing_type"))))
        self.slug_key.add((src, key))

    def finish(self) -> dict:
        gm = self.gm
        from foreclosure_scraper import screen_ledger as SL
        led = SL.load(self.ledger_path)
        led_note = "no screen ledger"
        if led:
            if SL.fresh(led, self.today):
                led_note = f"screen ledger of {led.get('run_at')} ({led.get('cells_screened', 0)} screens)"
            else:
                led_note = f"screen ledger of {led.get('run_at')} is stale: ignored"
                led = {}
        code = _code()
        lt_slugs: dict = {}
        for slug, lt in self.slug_lt:
            lt_slugs.setdefault(lt, set()).add(slug)
        state_hit: Counter = Counter()
        for (key, c), n in self.pos.items():
            state_hit[(key[0], c)] += n
        by_col: Counter = Counter()
        cells = 0
        for (key, c), n_app in self.app.items():
            if not n_app:
                continue
            cells += 1
            st, co = key
            spec = gm.SPECS[c]
            if spec.scope == "feed":
                ran = any((s, key) in self.slug_key for s in lt_slugs.get(gm.LISTING_TYPE_COLS[c], ()))
            elif spec.scope == "state":
                ran = state_hit[(st, c)] > 0
            else:
                ran = self.pos[(key, c)] > 0
            if ran or (led and SL.screened(led, c, st, co)):
                continue
            covered = bool(dict(spec.statewide).get(st)) or (st, co) in code.get(c, set())
            if covered:
                self.violations += 1
                by_col[c] += 1
                if len(self.sample) < SAMPLE:
                    self.sample.append(f"{st}|{co}|{c}")
        top = ", ".join(f"{c} {n}" for c, n in by_col.most_common(6))
        return self.result(f"{self.violations:,} of {cells:,} applicable county/state/feed signal cells have "
                           f"code covering the county but no hit and no recorded screen ({led_note}); "
                           f"top: {top or 'none'}; sample {self.sample}")


class FlipRowOutsideFlipScope(_Check):
    name = "cube-flip-row-outside-flip-scope"
    max_violations = FLIP_OUTSIDE_BASELINE
    FLIP = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale", "reo"})

    def __init__(self) -> None:
        super().__init__()
        self.gm = _gm()
        self.by: Counter = Counter()

    def feed(self, row: dict) -> None:
        if row.get("listing_type") not in self.FLIP:
            return
        self.checked += 1
        gm = self.gm
        st = (row.get("state") or "").strip().upper()
        co = gm.canonical_county(row.get("county"))
        if co and not gm.in_flip_scope(st, co):
            self._bad(row)
            self.by[f"{st}|{co}"] += 1

    def finish(self) -> dict:
        return self.result(f"{self.violations:,} of {self.checked:,} flip-type rows sit in a county outside the "
                           f"owner's flip scope; by county {self.by.most_common(6)}; sample {self.sample}")


class NegativeWrapperDated(_Check):
    name = "cube-negative-wrapper-dated"
    max_violations = UNDATED_NEGATIVE_BASELINE
    DATE_KEY = {"incarceration_check": ("checked_at",), "bop_check": ("checked_at",),
                "marriage_license": ("checked_at", "license_date"), "divorce": ("fetched_at",)}

    def __init__(self) -> None:
        super().__init__()
        self.by: Counter = Counter()

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        for k, dks in self.DATE_KEY.items():
            v = raw.get(k)
            if not isinstance(v, dict) or not v:
                continue
            self.checked += 1
            if not any(v.get(d) for d in dks):
                self._bad(row)
                self.by[k] += 1

    def finish(self) -> dict:
        return self.result(f"{self.violations:,} of {self.checked:,} negative/screen wrappers carry no check date; "
                           f"by key {dict(self.by)}; sample {self.sample}")


def make_checks() -> list:
    return [UnscreenedCountySignalCells(), FlipRowOutsideFlipScope(), NegativeWrapperDated()]
