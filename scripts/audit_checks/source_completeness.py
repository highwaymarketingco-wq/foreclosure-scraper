"""Source-completeness invariants (audit 2026-10-09, area source_completeness): does every source
keep pulling everything it can, county by county, run after run.

Each check would have caught a defect this audit measured on the 10/7 published board:
  source-county-refreshed     a (source, county) whose rows were mostly NOT re-read by the run: more
                              than STALE_SHARE of its rows missed two or more runs in a row
                              (raw.pulled_sale.consecutive_misses >= 2) or are carryover replays.
                              qPayBill's fixed 900 s timeout cut the same 18 of 29 counties on every
                              run: 25,314 of 33,180 rows unread since mid-September, 2 misses from
                              being dropped (board_persist drops a row after 4).
  source-county-floor         a (source, county) cell of a high-value lead class that holds fewer
                              than FLOOR_SHARE of its rows on the baseline board (the last accepted
                              publish, docs/audit_2026-10-09/source_completeness_baseline.json); a
                              high-value source with no rows at all is a violation too. A county
                              whose fetch broke silently (qPayBill Abbeville: 0 parcels from 36
                              clean queries on the 10/8 run) shows here once its rows age out.
  source-cap-not-hit          a source (or a source's county) whose row count equals a hard cap in
                              its scraper: the cap bound and rows were cut (heir/estate parcels
                              were capped at 80 per county until 2026-10-07; Greenville MIE reads
                              400 of ~773 sitemap adverts).
Exempt from the first two: manual and hand-off lanes whose rows are recorded filings that are not
re-read every run (MANUAL_SOURCES, and any source with a 'liensnc' part, the same rule as
board_persist.AGE_EXEMPT_SOURCES).

Memory: counters keyed by (source, county) (a few thousand cells) and at most SAMPLE examples per
check (source slugs and county names only; no names, no addresses).

Baseline: `uv run python scripts/audit_checks/source_completeness.py --write-baseline [--board P]`
streams a board once and rewrites the baseline file (run it after an accepted publish).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
BASELINE = _REPO / "docs" / "audit_2026-10-09" / "source_completeness_baseline.json"

#: a (source, county) is stale when more than this share of its rows were not re-read
STALE_SHARE = 0.5
#: ... and it has at least this many rows (smaller cells are noise)
MIN_CELL = 20
#: a high-value (source, county) cell must keep at least this share of its baseline rows
FLOOR_SHARE = 0.5

#: Recorded filings / manual lanes: their rows are not re-read every run by design.
MANUAL_SOURCES = frozenset({
    "liensnc", "nc_ecourts_judgments", "counties_sc.sc_public_index_export",
    "courtlistener.recap", "derived.probate_deed", "manual.watchlist",
})
AGE_EXEMPT_PARTS = frozenset({"liensnc"})

HIGH_VALUE = frozenset({"tax", "foreclosure", "lis_pendens", "probate", "divorce", "bankruptcy",
                        "code", "jail", "elderly"})

#: Known hard caps: (source label or prefix, unit, module, constant, literal fallback).
#: unit "county": the count per (source, county) must not equal the cap; "source": the total.
CAPS: tuple[tuple[str, str, str, str, int], ...] = (
    ("counties_nc.nc_heir_estate_parcels", "county",
     "foreclosure_scraper.scrapers.counties_nc.nc_heir_estate_parcels", "_PER_COUNTY_CAP", 400),
    ("counties_sc.greenville_mie_adverts", "source",
     "foreclosure_scraper.scrapers.counties_sc.greenville_mie_adverts", "MAX_ADVERTS", 400),
)


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _exempt(source: str) -> bool:
    return (source in MANUAL_SOURCES or source.startswith("manual.")
            or any(p in AGE_EXEMPT_PARTS for p in source.split(".")))


def _misses(row: dict) -> int:
    ps = _raw(row).get("pulled_sale")
    if not isinstance(ps, dict):
        return 0
    try:
        return int(ps.get("consecutive_misses") or 0)
    except (TypeError, ValueError):
        return 0


def lead_class(source: str, listing_type: str) -> str:
    """The lead class of a row: by listing type, else by the source slug."""
    t = (listing_type or "").lower()
    if t in ("foreclosure_sale", "auction", "sheriff_sale"):
        return "foreclosure"
    if t == "lis_pendens":
        return "lis_pendens"
    if t in ("probate_notice", "estate_lead"):
        return "probate"
    if t in ("tax_lien", "tax_sale", "tax_sale_overage"):
        return "tax"
    if t == "divorce_notice":
        return "divorce"
    if t == "bankruptcy":
        return "bankruptcy"
    if t == "elderly_disabled":
        return "elderly"
    if t == "reo":
        return "reo"
    s = (source or "").lower()
    if "jail" in s or "booking" in s:
        return "jail"
    if re.search(r"ust|contamin|epa|dam_safety|hazard|brownfield|dsca|superfund|sems|acres", s):
        return "env"
    if re.search(r"code|condemn|vacant|demoli|blight|housing|cleanup|damage|storm|flood|helene|"
                 r"landslide|buyout|unsafe|nuisance|fire", s):
        return "code"
    if re.search(r"tax|unpaid|delinq|lien", s):
        return "tax"
    if re.search(r"foreclos|trustee|mie|equity|sheriff|upset", s):
        return "foreclosure"
    if re.search(r"probate|estate|obit|heir", s):
        return "probate"
    return "other"


def _cell(row: dict) -> tuple[str, str]:
    st = str(row.get("state") or "?")
    return str(row.get("source") or "?"), f"{row.get('county') or '?'}|{st}"


class _Check:
    name = "source-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []

    def _bad(self, what: str) -> None:
        self.violations += 1
        if len(self.samples) < SAMPLE:
            self.samples.append(what)

    def _result(self, extra: str = "") -> dict:
        parts = [self.describe, extra]
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations,
                "detail": " | ".join(p for p in parts if p)}


class CountyRefreshed(_Check):
    """(source, county) cells whose rows the last run mostly did not re-read."""
    name = "source-county-refreshed"
    describe = (f"(source, county) cells with >= {MIN_CELL} rows where more than "
                f"{int(STALE_SHARE * 100)}% of rows missed 2+ runs in a row or are carryover replays")

    def __init__(self) -> None:
        super().__init__()
        self.cells: dict[tuple[str, str], list[int]] = {}

    def feed(self, row: dict) -> None:
        src, cty = _cell(row)
        if _exempt(src):
            return
        self.checked += 1
        c = self.cells.get((src, cty))
        if c is None:
            c = self.cells[(src, cty)] = [0, 0]
        c[0] += 1
        if _misses(row) >= 2 or _raw(row).get("carryover"):
            c[1] += 1

    def finish(self) -> dict:
        bad_rows = 0
        worst = sorted(((stale / n, src, cty, n, stale) for (src, cty), (n, stale) in self.cells.items()
                        if n >= MIN_CELL and stale > STALE_SHARE * n), reverse=True)
        for share, src, cty, n, stale in worst:
            bad_rows += stale
            self._bad(f"{src} {cty} {stale}/{n}")
        return self._result(f"stale rows in flagged cells: {bad_rows}")


class CountyFloor(_Check):
    """High-value (source, county) cells must keep FLOOR_SHARE of their baseline rows."""
    name = "source-county-floor"
    describe = (f"high-value (source, county) cells holding < {int(FLOOR_SHARE * 100)}% of their "
                "rows on the baseline board, or high-value sources with no rows")

    def __init__(self, baseline: dict | None = None) -> None:
        super().__init__()
        self.baseline = baseline if baseline is not None else load_baseline()
        self.counts: dict[tuple[str, str], int] = {}
        self.totals: dict[str, int] = {}

    def feed(self, row: dict) -> None:
        src, cty = _cell(row)
        if src not in self.baseline:
            return
        self.checked += 1
        self.totals[src] = self.totals.get(src, 0) + 1
        self.counts[(src, cty)] = self.counts.get((src, cty), 0) + 1

    def finish(self) -> dict:
        if not self.baseline:
            self._bad("no baseline file (run --write-baseline after an accepted publish)")
            return self._result()
        lost = 0
        for src, b in sorted(self.baseline.items()):
            if self.totals.get(src, 0) == 0 and int(b.get("rows") or 0) > 0:
                lost += int(b.get("rows") or 0)
                self._bad(f"{src} 0/{b.get('rows')} rows")
                continue
            for cty, n0 in sorted((b.get("counties") or {}).items()):
                n = self.counts.get((src, cty), 0)
                if n < FLOOR_SHARE * int(n0):
                    lost += int(n0) - n
                    self._bad(f"{src} {cty} {n}/{n0}")
        return self._result(f"baseline rows missing in flagged cells: {lost}")


class CapNotHit(_Check):
    """A source's (or a source county's) row count must not equal a hard cap in its scraper."""
    name = "source-cap-not-hit"
    describe = "row counts equal to a scraper's hard cap (the cap bound: rows were cut)"

    def __init__(self) -> None:
        super().__init__()
        self.by_source: dict[str, int] = {}
        self.by_cell: dict[tuple[str, str], int] = {}

    def feed(self, row: dict) -> None:
        src, cty = _cell(row)
        for label, unit, _m, _c, _d in CAPS:
            if src == label or src.startswith(label + "."):
                self.checked += 1
                if unit == "county":
                    self.by_cell[(label, cty)] = self.by_cell.get((label, cty), 0) + 1
                else:
                    self.by_source[label] = self.by_source.get(label, 0) + 1
                break

    @staticmethod
    def _cap(module: str, const: str, default: int) -> int:
        try:
            import importlib
            return int(getattr(importlib.import_module(module), const))
        except Exception:  # noqa: BLE001 - the literal stands in when the module will not import
            return default

    def finish(self) -> dict:
        caps = []
        for label, unit, module, const, default in CAPS:
            cap = self._cap(module, const, default)
            caps.append(f"{label}={cap}/{unit}")
            if unit == "county":
                for (lab, cty), n in sorted(self.by_cell.items()):
                    if lab == label and n == cap:
                        self._bad(f"{label} {cty} {n}=cap")
            elif self.by_source.get(label, 0) == cap:
                self._bad(f"{label} {cap}=cap")
        return self._result("caps: " + ", ".join(caps))


def load_baseline(path: Path | str = BASELINE) -> dict:
    try:
        return dict(json.loads(Path(path).read_text()).get("sources") or {})
    except Exception:  # noqa: BLE001 - a missing baseline is reported by CountyFloor
        return {}


def make_checks() -> list:
    return [CountyRefreshed(), CountyFloor(), CapNotHit()]


def write_baseline(board: str, out: Path = BASELINE) -> dict:
    """Stream `board` once and write the per-(source, county) baseline of high-value sources."""
    from foreclosure_scraper.board_stream import iter_board_rows
    types: dict[str, dict[str, int]] = {}
    cells: dict[tuple[str, str], int] = {}
    totals: dict[str, int] = {}
    n = 0
    newest = ""
    for row in iter_board_rows(board):
        n += 1
        src, cty = _cell(row)
        newest = max(newest, str(row.get("last_seen") or "")[:16])
        if _exempt(src):
            continue
        t = types.setdefault(src, {})
        lt = str(row.get("listing_type") or "?")
        t[lt] = t.get(lt, 0) + 1
        totals[src] = totals.get(src, 0) + 1
        cells[(src, cty)] = cells.get((src, cty), 0) + 1
    sources = {}
    for src, t in sorted(types.items()):
        top = max(t, key=t.get)
        cls = lead_class(src, top)
        if cls not in HIGH_VALUE:
            continue
        sources[src] = {"class": cls, "rows": totals[src],
                        "counties": {cty: c for (s, cty), c in sorted(cells.items())
                                     if s == src and c >= MIN_CELL and not cty.startswith("?")}}
    doc = {"schema": "source-completeness-baseline-v1", "board_rows": n, "board_newest_last_seen": newest,
           "about": ("Per-source and per-(source, county) row counts of high-value lead classes on the "
                     "last accepted published board; scripts/audit_checks/source_completeness.py "
                     "(source-county-floor) compares a board against it. Rewrite after an accepted "
                     "publish: uv run python scripts/audit_checks/source_completeness.py --write-baseline"),
           "min_cell": MIN_CELL, "sources": sources}
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--board", default=str(_REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--out", default=str(BASELINE))
    a = ap.parse_args(argv)
    if a.write_baseline:
        doc = write_baseline(a.board, Path(a.out))
        print(f"baseline: {len(doc['sources'])} sources, "
              f"{sum(len(v['counties']) for v in doc['sources'].values())} county cells, "
              f"board {doc['board_rows']} rows -> {a.out}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
