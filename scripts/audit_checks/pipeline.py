"""Pipeline invariants (audit 2026-10-09, area pipeline_gate): what must hold on any board the run
publishes, whatever path wrote it (the full run, a checkpoint resume, a reconcile, an offline merge).

Each check would have caught a defect class this pipeline has had:
  pipeline-row-scored            a row published without a HOT/WARM/COLD tier, or with a scorer
                                 error: a path that bypassed scoring (the GRANDFATHER restore runs
                                 after the scorer; offline merges append rows) or a fail-soft score.
  pipeline-row-valued            a row with no raw['calc'] / raw['grade']: the valuation loop never
                                 saw it (same bypasses), so every ARV caveat reads off nothing.
  pipeline-equity-tax-inputs     raw['equity'] computed from tax inputs the row no longer carries:
                                 restore_verified_tax (after verification apply) rewrites
                                 tax_aging_high / amount_owed AFTER enrich_equity ran, so the
                                 assessed-value payoff (0.70 vs 0.60 of assessed) or the
                                 amount_owed-based payoff describe the pre-verification row.
  pipeline-tax-check-binding     a county-site tax check on the row that the displayed balance
                                 contradicts: confirmed but the balance is not the checked one, or
                                 stale/refuted while an unverified balance is still shown (a step
                                 after restore_verified_tax re-added it, or restore never ran).
  pipeline-countyless-national   a national.* / reo.* row with no county: main.run drops these
                                 (orchestrator.drop_countyless_national); one on the board came in
                                 through a path that skips run() (HANDOFF item 77: 4,277 rows).
  pipeline-raw-keep              a raw key outside web_artifact.RAW_KEEP: a writer that bypassed
                                 web_artifact._to_dict (the publish transform).
  pipeline-seen-order            first_seen after last_seen: a merge that kept the wrong copy's
                                 dates.
  pipeline-run-health-counts     the run's per-source report (run_health.json beside a published
                                 board, resume_state.json beside a checkpoint) says "OK (n)" with a
                                 count that is not n: the 10/7 publish showed every source at 0.
Memory: counters and at most SAMPLE parcel ids per check (parcel ids are public record).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
TIERS = frozenset({"HOT", "WARM", "COLD"})
#: tax_binding.VERIFIED_SOURCE (restated so this check runs on a checkout where tax_binding moved;
#: test_audit_checks_pipeline.py pins it to the module's value)
VERIFIED_SOURCE = "county_site_verified"
#: enrichment_equity._payoff path 5: assessed x 0.70 when tax_aging_high, else x 0.60
ASSESSED_RATIO_AGED = 0.70
ASSESSED_RATIO = 0.60


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "")) if v not in (None, "") else None
    except ValueError:
        return None


def _ident(row: dict) -> str:
    return str(row.get("parcel_id") or row.get("case_number") or row.get("source") or "?")[:40]


class _Check:
    name = "pipeline-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: dict[str, int] = {}

    def _bad(self, row: dict, why: str = "") -> None:
        self.violations += 1
        if why:
            self.by[why] = self.by.get(why, 0) + 1
        if len(self.samples) < SAMPLE:
            self.samples.append(f"{row.get('county') or '?'}:{_ident(row)}" + (f"({why})" if why else ""))

    def finish(self) -> dict:
        parts = [self.describe]
        if self.by:
            parts.append("by: " + ", ".join(f"{k} {v}" for k, v in sorted(self.by.items(), key=lambda kv: -kv[1])))
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations, "detail": " | ".join(p for p in parts if p)}


class RowScored(_Check):
    name = "pipeline-row-scored"
    describe = ("every row that is not sold_confirmed carries a HOT/WARM/COLD tier from the scorer, "
                "no score_error")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        if raw.get("sold_confirmed"):
            return      # distress_score.score_board leaves a sold/closed parcel unscored on purpose
        self.checked += 1
        ds = raw.get("distress_stack")
        if not isinstance(ds, dict):
            self._bad(row, "no distress_stack")
        elif ds.get("tier") not in TIERS:
            self._bad(row, f"tier {ds.get('tier')!r}")
        elif ds.get("score_error"):
            self._bad(row, "score_error")


class RowValued(_Check):
    name = "pipeline-row-valued"
    describe = "every row went through the valuation loop (raw calc + grade)"

    def feed(self, row: dict) -> None:
        self.checked += 1
        raw = _raw(row)
        if not isinstance(raw.get("calc"), dict):
            self._bad(row, "no calc")
        elif not isinstance(raw.get("grade"), dict):
            self._bad(row, "no grade")


class EquityTaxInputs(_Check):
    name = "pipeline-equity-tax-inputs"
    describe = ("raw.equity's payoff matches the row's CURRENT tax inputs (assessed-value estimate "
                "vs tax_aging_high; amount_owed-based payoff vs amount_owed)")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        eq = raw.get("equity")
        if not isinstance(eq, dict) or eq.get("withheld") or eq.get("payoff_estimate") is None:
            return
        src = str(eq.get("payoff_source") or "")
        payoff = _num(eq.get("payoff_estimate"))
        if payoff is None:
            return
        if src == "assessed_value_estimate":
            av = _num(row.get("assessed_value"))
            if not av or av <= 0:
                return
            self.checked += 1
            ratio = ASSESSED_RATIO_AGED if raw.get("tax_aging_high") else ASSESSED_RATIO
            want = round(av * ratio, -2)
            if abs(want - payoff) > 100:
                other = round(av * (ASSESSED_RATIO if ratio == ASSESSED_RATIO_AGED else ASSESSED_RATIO_AGED), -2)
                self._bad(row, "aging ratio flipped after equity" if abs(other - payoff) <= 100
                          else "assessed value changed after equity")
        elif src.startswith("amount_owed:"):
            self.checked += 1
            ao = raw.get("amount_owed")
            if not isinstance(ao, dict):
                self._bad(row, "amount_owed gone after equity")
                return
            if str(ao.get("source") or "?") != src[len("amount_owed:"):]:
                self._bad(row, "amount_owed source changed after equity")
                return
            v = _num(ao.get("value"))
            if v is None or abs(round(v, -2) - payoff) > 100:
                self._bad(row, "amount_owed value changed after equity")


class TaxCheckBinding(_Check):
    name = "pipeline-tax-check-binding"
    describe = ("a county-site tax check decides the displayed balance (confirmed: the checked "
                "balance; stale/refuted: no unverified balance)")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        note = raw.get("tax_county_check")
        if not isinstance(note, dict):
            return
        self.checked += 1
        verdict = note.get("verdict")
        to = raw.get("tax_owed")
        src = to.get("source") if isinstance(to, dict) else None
        if verdict == "confirmed":
            if src != VERIFIED_SOURCE:
                self._bad(row, "confirmed, balance not the checked one")
        elif verdict in ("stale", "refuted"):
            if isinstance(to, dict) and src != VERIFIED_SOURCE:
                self._bad(row, f"{verdict}, unverified balance still shown")


class CountylessNational(_Check):
    name = "pipeline-countyless-national"
    describe = "no national.*/reo.* row without a county (main.run drops them)"

    def feed(self, row: dict) -> None:
        src = str(row.get("source") or "")
        if not (src.startswith("national.") or src.startswith("reo.")):
            return
        self.checked += 1
        if not str(row.get("county") or "").strip():
            self._bad(row, src)


class RawKeep(_Check):
    name = "pipeline-raw-keep"
    describe = "every raw key is in web_artifact.RAW_KEEP (the publish transform ran)"

    def __init__(self) -> None:
        super().__init__()
        try:
            from foreclosure_scraper.web_artifact import RAW_KEEP
            self.keep = frozenset(RAW_KEEP)
        except Exception:  # noqa: BLE001 - a check that cannot load its rule says so
            self.keep = None

    def feed(self, row: dict) -> None:
        if self.keep is None:
            return
        self.checked += 1
        extra = [k for k in _raw(row) if k not in self.keep]
        if extra:
            self.violations += 1
            for k in extra[:3]:
                self.by[k] = self.by.get(k, 0) + 1

    def finish(self) -> dict:
        out = super().finish()
        if self.keep is None:
            out.update(violations=1, ok=False, detail="could not import web_artifact.RAW_KEEP")
        return out


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


class SeenOrder(_Check):
    name = "pipeline-seen-order"
    describe = "first_seen is not after last_seen"

    def feed(self, row: dict) -> None:
        a, b = _ts(row.get("first_seen")), _ts(row.get("last_seen"))
        if a is None or b is None:
            return
        self.checked += 1
        if a > b:
            self._bad(row, "first_seen > last_seen")


class RunHealthCounts(_Check):
    """Not a row check: the run's per-source report beside the rows. A published board's
    docs/run_health.json, or a checkpoint's resume_state.json summary, must give every source whose
    status reads "OK (n)" a count of n. The 10/7 publish (a tail re-run carried onto a full run's
    state) showed all 204 sources at count 0 beside "OK (3058)" statuses: carry_publish_state did
    not carry by_source."""
    name = "pipeline-run-health-counts"
    describe = "every 'OK (n)' source in the run's health report has count n"

    def __init__(self) -> None:
        super().__init__()
        self.kind = self.path = None

    def set_source(self, kind: str, path: Path) -> None:
        self.kind, self.path = kind, Path(path)

    def feed(self, row: dict) -> None:
        return None

    def _pairs(self):
        """[(source, count, status)] from the side file, or None when there is none to judge."""
        import json
        if self.kind == "board":
            f = self.path / "run_health.json"
            if not f.exists():
                return None
            doc = json.loads(f.read_text())
            return [(s.get("source"), s.get("count"), str(s.get("status") or ""))
                    for s in (doc.get("sources") or []) if isinstance(s, dict)]
        if self.kind == "checkpoint":
            f = self.path / "resume_state.json"
            if not f.exists():
                return None
            st = json.loads(f.read_text())
            if not (st.get("publish") or {}).get("write_run_health"):
                return None     # this checkpoint's publish writes no run_health
            s = st.get("summary") or {}
            by, status = s.get("by_source") or {}, s.get("source_status") or {}
            return [(k, by.get(k, 0), str(v)) for k, v in status.items()]
        return None

    def finish(self) -> dict:
        import re
        try:
            pairs = self._pairs()
        except Exception as exc:  # noqa: BLE001
            return {"name": self.name, "checked": 0, "violations": 1, "max_violations": 0, "ok": False,
                    "detail": f"could not read the run's health report: {type(exc).__name__}: {exc}"}
        for src, count, status in pairs or []:
            m = re.match(r"OK \((\d+)\)", status)
            if not m:
                continue
            self.checked += 1
            if int(count or 0) != int(m.group(1)):
                self.violations += 1
                if len(self.samples) < SAMPLE:
                    self.samples.append(f"{src}: count {count} vs {status}")
        out = super().finish()
        if pairs is None:
            out["detail"] = "no run health report beside these rows (nothing to judge)"
        return out


def make_checks() -> list:
    return [RowScored(), RowValued(), EquityTaxInputs(), TaxCheckBinding(), CountylessNational(),
            RawKeep(), SeenOrder(), RunHealthCounts()]
