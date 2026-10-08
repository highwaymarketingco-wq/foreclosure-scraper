"""Regression invariants (audit 2026-10-09, area regressions): what the gated d42058b3 run lost against
the 10/7 board, checkable on ONE board in one pass against a small baseline of the last accepted board
(docs/audit_2026-10-09/regressions_baseline.json: counts and record hashes).

  regressions-roll-records-kept      a county roll source whose records (the id its own raw block
                                     carries, county-qualified, on any row whatever its primary source)
                                     were on the baseline board, could not have aged out since, and are
                                     gone from this board, beyond ROLL_LOST_MIN / ROLL_LOST_SHARE. Nothing
                                     caught this before: dedupe() fused the 580 situs-less rows of
                                     Rutherford's carryover replay into ONE row (all keyed by the roll
                                     URL; dedupe 'roll URL keys'), and aged PTS Cloud rows of five
                                     counties fused across counties on their shared portal URL.
  regressions-source-held            a source with at least SOURCE_MIN_ROWS baseline rows whose rows on
                                     the board (primary source OR an also_seen_in entry: a row folded
                                     under another source's record is still that source's) fell under
                                     SOURCE_HELD_SHARE of the baseline. Counting the attribution, not
                                     the primary label, is the point: the d42058b3 comparison flagged
                                     buncombe_delinquent_tax (1,182 -> 827), multi_year_delinquent_tax
                                     (1,115 -> 436), kania and sc_catalis as lost when every row was
                                     still there under another merge base (main.run() collected scraper
                                     results from an unordered set).
  regressions-absorbed-life-types    a row whose also_seen_in names an absorbed life-event record
                                     (estate_lead / probate_notice / divorce_notice, Listing.merge since
                                     2026-10-09) that the scorer credits today but the published
                                     distress_stack lacks: the board was scored without the rule (an
                                     estate lead folded under a tax-roll row lost estate_lead on 125
                                     rows of the d42058b3 run). max 0.

Memory: per-source counters, two sets of 64-bit record hashes per roll source (about 55,000 records on
the 10/7 board), at most SAMPLE slugs or parcel ids per check. Baseline: source slugs, counts and
record hashes (no parcel id, name or address can be read back from it).
Rewrite it after an accepted publish:
    uv run python scripts/audit_checks/regressions.py --write-baseline [--board docs/listings.json.gz]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SAMPLE = 8
BASELINE = _REPO / "docs" / "audit_2026-10-09" / "regressions_baseline.json"

#: A county roll's record leaves the board only by aging: board_persist drops a prior row after
#: PULLED_RETENTION_WEEKS (4) misses, so a record the baseline shows with fewer than 3 misses must be on
#: the next board. Gone records beyond this tolerance are a defect (a fusion, a lost key), not churn.
#: Measured on the d42058b3 candidate against the 10/7 board (records the baseline held with < 3
#: misses): rutherford_tax 579 of 7,294 (the URL fusion), nc_ptscloud_delinquent_tax 87 of 18,869 (the
#: cross-county URL fusion of aged rows), rutherford_wildfire_tax 5, lincoln_vacant 2,
#: nc_county_pdf_delinquent_tax 1. The tolerance passes the last three and catches the first two.
AGE_ELIGIBLE_MISSES = 3
ROLL_LOST_MIN = 10
ROLL_LOST_SHARE = 0.002
#: Any source: the owner's 90% rule (scripts/compare_boards.py SOURCE_DROP_RATIO), on sources big
#: enough that a weekly sale list's churn is not the signal (law-firm lists are 6 to 192 rows).
SOURCE_HELD_SHARE = 0.90
SOURCE_MIN_ROWS = 200
#: Sources whose drop the owner accepted, with the reason (compare_boards --accept-source-drop).
ACCEPTED_DROPS = {
    "national.fannie_homepath": "HANDOFF item 78: HomePath read for Fannie Mae REO only (857 -> about 45)",
}


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _roll_fields() -> dict[str, tuple[str, str]]:
    """{source: (raw block, id key)}: board_persist's table of sources whose short ids validation
    nulls plus parcel_alias's short-id sources, the rolls whose rows carry their own id in a block."""
    out: dict[str, tuple[str, str]] = {}
    try:
        from foreclosure_scraper.board_persist import _SOURCE_PARCEL_FIELDS
        out.update(_SOURCE_PARCEL_FIELDS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from foreclosure_scraper.parcel_alias import ALIAS_SOURCES
        out.update(ALIAS_SOURCES)
    except Exception:  # noqa: BLE001
        pass
    return out


_NON_ALNUM = re.compile(r"[^0-9a-z]")


def roll_records(row: dict, fields: dict[str, tuple[str, str]]) -> list[tuple[str, int]]:
    """[(roll source, 64-bit hash of (county, normalized id))] for every roll block on the row."""
    raw = _raw(row)
    co = str(row.get("county") or "").strip().lower()
    out = []
    for src, (blk_name, key) in fields.items():
        blk = raw.get(blk_name)
        if not isinstance(blk, dict) or not blk.get(key):
            continue
        n = _NON_ALNUM.sub("", str(blk[key]).lower())
        if len(n) < 4:
            continue
        h = int.from_bytes(hashlib.blake2b(f"{co}|{n}".encode(), digest_size=8).digest(), "little")
        out.append((src, h))
    return out


def sources_of(row: dict) -> set[str]:
    """The row's primary source and every source in raw['also_seen_in']."""
    out = {str(row.get("source") or "")}
    asi = _raw(row).get("also_seen_in")
    for d in asi if isinstance(asi, list) else ():
        if isinstance(d, dict) and d.get("source"):
            out.add(str(d["source"]))
    out.discard("")
    return out


def _encode(hashes) -> str:
    """Sorted 64-bit record hashes as base64 (8 bytes each): the baseline's ids, never a parcel id."""
    import base64
    return base64.b64encode(b"".join(h.to_bytes(8, "little") for h in sorted(hashes))).decode("ascii")


def _decode(s: str) -> list[int]:
    import base64
    b = base64.b64decode(s)
    return [int.from_bytes(b[i:i + 8], "little") for i in range(0, len(b), 8)]


def load_baseline(path: Path = BASELINE) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


class _RollRecordsKept:
    name = "regressions-roll-records-kept"

    def __init__(self, baseline: dict | None = None):
        self.base = (baseline if baseline is not None else load_baseline()) or {}
        self.fields = _roll_fields()
        self.seen: dict[str, set[int]] = {s: set() for s in self.fields}
        # records that could not age out by the next run (misses < AGE_ELIGIBLE_MISSES), for the baseline
        self.young: dict[str, set[int]] = {s: set() for s in self.fields}
        self.checked = 0

    def feed(self, row: dict) -> None:
        self.checked += 1
        recs = roll_records(row, self.fields)
        if not recs:
            return
        ps = _raw(row).get("pulled_sale")
        try:
            misses = int(ps.get("consecutive_misses") or 0) if isinstance(ps, dict) else 0
        except (TypeError, ValueError):
            misses = 0
        for src, h in recs:
            self.seen[src].add(h)
            if misses < AGE_ELIGIBLE_MISSES:
                self.young[src].add(h)

    def finish(self) -> dict:
        base = self.base.get("roll_records") or {}
        bad = []
        for src, b64 in sorted(base.items()):
            if src in ACCEPTED_DROPS or not b64:
                continue
            want = _decode(b64)
            have = self.seen.get(src, set())
            lost = sum(1 for h in want if h not in have)
            if lost > max(ROLL_LOST_MIN, ROLL_LOST_SHARE * len(want)):
                bad.append(f"{src}: {lost} of {len(want)} records gone ({len(have)} on the board)")
        detail = (f"roll records gone that could not have aged out: {bad[:SAMPLE]}" if bad else
                  ("no baseline: run --write-baseline after an accepted publish" if not base else ""))
        return {"name": self.name, "checked": self.checked, "violations": len(bad), "max_violations": 0,
                "ok": not bad, "detail": detail}


class _SourceHeld:
    name = "regressions-source-held"

    def __init__(self, baseline: dict | None = None):
        self.base = (baseline if baseline is not None else load_baseline()) or {}
        self.counts: dict[str, int] = {}
        self.checked = 0

    def feed(self, row: dict) -> None:
        self.checked += 1
        for s in sources_of(row):
            self.counts[s] = self.counts.get(s, 0) + 1

    def finish(self) -> dict:
        base = self.base.get("source_rows") or {}
        bad = []
        for src, nb in sorted(base.items(), key=lambda kv: -kv[1]):
            if nb < SOURCE_MIN_ROWS or src in ACCEPTED_DROPS:
                continue
            n = self.counts.get(src, 0)
            if n < nb * SOURCE_HELD_SHARE:
                bad.append(f"{src} {nb}->{n} ({n / nb:.0%})")
        detail = (f"sources under {SOURCE_HELD_SHARE:.0%} of their baseline rows (primary or also_seen_in): "
                  f"{bad[:SAMPLE]}" if bad else
                  ("no baseline: run --write-baseline after an accepted publish" if not base else ""))
        return {"name": self.name, "checked": self.checked, "violations": len(bad), "max_violations": 0,
                "ok": not bad, "detail": detail}


class _AbsorbedLifeTypes:
    name = "regressions-absorbed-life-types"

    def __init__(self):
        from foreclosure_scraper import distress_score as DS
        from foreclosure_scraper.models import Listing
        self._ds, self._listing = DS, Listing
        self.checked = 0
        self.rows = 0
        self.bad = 0
        self.errors = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        self.checked += 1
        raw = _raw(row)
        lt = str(row.get("listing_type") or "")
        absorbed = self._ds.absorbed_life_types(raw, lt)
        if not absorbed:
            return
        self.rows += 1
        ds = raw.get("distress_stack")
        have = set(ds.get("signals") or []) if isinstance(ds, dict) else set()
        try:
            now = {n for n, _c, _w in self._ds._signals_for(self._listing.model_validate(row))}
        except Exception:  # noqa: BLE001 - a row the model refuses is another check's finding
            self.errors += 1
            return
        missing = [t for t, _s in absorbed if t in now and t not in have]
        if missing:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(str(row.get("parcel_id") or row.get("source") or "?"))

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.bad, "max_violations": 0,
                "ok": self.bad == 0,
                "detail": (f"{self.rows} rows carry an absorbed life-event record; {self.bad} lack the signal the "
                           f"scorer gives it today (sample {self.sample}); {self.errors} rows did not validate")}


def make_checks() -> list:
    base = load_baseline()
    return [_RollRecordsKept(base), _SourceHeld(base), _AbsorbedLifeTypes()]


def write_baseline(board: str, out: Path = BASELINE) -> dict:
    """Stream `board` once and write the counts the first two checks compare against."""
    from foreclosure_scraper.board_stream import iter_board_rows
    rk, sh = _RollRecordsKept({}), _SourceHeld({})
    n = 0
    for row in iter_board_rows(board):
        n += 1
        rk.feed(row)
        sh.feed(row)
    doc = {"schema": "regressions-baseline-v1", "board_rows": n,
           "about": ("Counts of the last accepted published board for scripts/audit_checks/regressions.py: "
                     "distinct county-roll records per roll source (roll_records) and rows per source counted "
                     "as primary OR also_seen_in (source_rows). Rewrite after an accepted publish: "
                     "uv run python scripts/audit_checks/regressions.py --write-baseline"),
           "roll_records": {s: _encode(v) for s, v in sorted(rk.young.items()) if v},
           "roll_records_count": {s: len(v) for s, v in sorted(rk.young.items()) if v},
           "source_rows": dict(sorted(sh.counts.items()))}
    Path(out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--board", default=str(_REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--out", default=str(BASELINE))
    a = ap.parse_args(argv)
    if a.write_baseline:
        doc = write_baseline(a.board, Path(a.out))
        print(f"baseline: {len(doc['roll_records'])} rolls, {len(doc['source_rows'])} sources, "
              f"board {doc['board_rows']} rows -> {a.out}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
