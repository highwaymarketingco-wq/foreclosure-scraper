#!/usr/bin/env python3
"""Run every audit invariant (scripts/audit_checks/*.py) over ONE streaming pass of a board.

WHY (audit 2026-10-09, docs/audit_2026-10-09/BRIEF.md)
    Each audit area leaves behind invariants that would have caught its defects. They are only
    worth something if they all run, on every board, before anyone trusts it: after a run (on the
    pre_publish checkpoint), in the pre-run gate (scripts/prerun_gate.py) and on the canary board
    (scripts/canary_run.py). This is the one runner they share.

THE CHECK INTERFACE (BRIEF.md "The invariant interface")
    scripts/audit_checks/<area>.py exposes ``make_checks() -> list``; each item has ``name``
    (kebab-case), ``feed(row: dict) -> None`` (once per row, stream order) and ``finish() -> dict``
    returning {"name", "checked", "violations", "max_violations", "ok", "detail"}. Optional:
    a module-level ``DETAIL_KEYS = ("comps", ...)`` (or the same attribute on a check) names the
    lazy-detail keys (web_artifact.LAZY_DETAIL_KEYS) the check reads; the runner then streams the
    detail sidecar beside a published board in lockstep and merges only those keys into raw.
    A check with ``set_source(kind, path)`` is told, before the pass, whether the rows come from a
    published board ("board", its docs dir) or a checkpoint ("checkpoint", its dir), so it can
    read the run's side files there (run_health.json, resume_state.json).

WHAT A ROW IS
    The PUBLISHED shape: a published board row as board_stream.iter_board_rows() yields it, or a
    checkpoint row validated to a Listing and passed through web_artifact._to_dict (exactly what
    write_artifact would publish; the same transform board_selfcheck.py --checkpoint uses). A
    checkpoint row still carries its lazy-detail keys inline (nothing splits them before publish).

ROBUSTNESS
    One bad check never costs the others: a module that does not import, a make_checks() that
    raises, a feed() that raises (counted per check; the row is skipped for that check only) or a
    finish() that raises or returns the wrong shape is reported as a NOT-OK row of its own.

OUTPUT
    A table (name, checked, violations, max, ok) on stdout, and --out (default
    docs/audit_2026-10-09/suite_result.json): counts only (the "detail" strings are dropped there,
    since a check may put parcel ids or addresses in them; the table prints them).
    Exit 0 when every check is ok, 1 when any is not, 2 when the board could not be read.

USAGE
    uv run python scripts/audit_suite.py                       # the published board (docs/)
    uv run python scripts/audit_suite.py --checkpoint [DIR]    # a checkpoint (default data/checkpoint)
    uv run python scripts/audit_suite.py --board PATH          # a board file or a docs dir
    uv run python scripts/audit_suite.py --list                # the checks, no board pass
    ... [--only a,b] [--limit N] [--out FILE | --no-out] [--checks-dir DIR]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

CHECKS_DIR = REPO / "scripts" / "audit_checks"
DEFAULT_OUT = REPO / "docs" / "audit_2026-10-09" / "suite_result.json"
RESULT_KEYS = ("name", "checked", "violations", "max_violations", "ok", "detail")


# --------------------------------------------------------------------------------------- loading
class _Broken:
    """Stands in for a check module / check that could not be built: always NOT ok."""

    def __init__(self, name: str, why: str):
        self.name = name
        self._why = why

    def feed(self, row: dict) -> None:  # noqa: D401 - never fed
        return None

    def finish(self) -> dict:
        return {"name": self.name, "checked": 0, "violations": 1, "max_violations": 0,
                "ok": False, "detail": self._why}


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"audit_checks_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover(checks_dir: Path = CHECKS_DIR) -> list[tuple[str, Any, tuple]]:
    """[(module stem, check or _Broken, detail keys)] for every scripts/audit_checks/*.py not
    starting with '_', in file-name order."""
    out: list[tuple[str, Any, tuple]] = []
    if not checks_dir.is_dir():
        return out
    for p in sorted(checks_dir.glob("*.py")):
        if p.name.startswith("_"):
            continue
        try:
            mod = _load_module(p)
        except Exception as exc:  # noqa: BLE001
            out.append((p.stem, _Broken(f"{p.stem}:import", f"import failed: {type(exc).__name__}: {exc}"), ()))
            continue
        mk = getattr(mod, "make_checks", None)
        if not callable(mk):
            out.append((p.stem, _Broken(f"{p.stem}:make_checks", "no make_checks()"), ()))
            continue
        try:
            checks = list(mk())
        except Exception as exc:  # noqa: BLE001
            out.append((p.stem, _Broken(f"{p.stem}:make_checks", f"make_checks() raised: {type(exc).__name__}: {exc}"), ()))
            continue
        mod_keys = tuple(getattr(mod, "DETAIL_KEYS", ()) or ())
        for c in checks:
            if not all(hasattr(c, a) for a in ("name", "feed", "finish")):
                out.append((p.stem, _Broken(f"{p.stem}:{getattr(c, 'name', '?')}",
                                            "check lacks name/feed/finish"), ()))
                continue
            keys = tuple(getattr(c, "DETAIL_KEYS", None) or getattr(c, "detail_keys", None) or mod_keys)
            out.append((p.stem, c, keys))
    return out


# --------------------------------------------------------------------------------------- sources
def published_rows(path: Path, detail_keys: Iterable[str] = ()) -> Iterator[dict]:
    """A published board: `path` is a docs dir or a board file (docs/listings.json.gz, a parts
    board beside it, or a single gzipped array)."""
    from foreclosure_scraper.board_stream import iter_board_rows, iter_board_rows_with_detail
    p = Path(path)
    if p.is_dir():
        p = p / "listings.json.gz"
    keys = tuple(k for k in detail_keys if k)
    if keys:
        try:
            yield from iter_board_rows_with_detail(p, keys)
            return
        except FileNotFoundError:
            print(f"note: no detail sidecar beside {p}; checks reading {keys} see none",
                  file=sys.stderr)
    yield from iter_board_rows(p)


def checkpoint_rows(ckpt_dir: Path, bad: list | None = None) -> Iterator[dict]:
    """A checkpoint board (<dir>/board.json.gz), each row in the shape write_artifact would
    publish (Listing.model_validate then web_artifact._to_dict). Rows that do not validate are
    counted in `bad` and skipped (checkpoint.load() drops them too)."""
    from foreclosure_scraper.board_parts import iter_gz_rows
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.web_artifact import _to_dict
    board = Path(ckpt_dir) / "board.json.gz"
    if not board.exists():
        raise FileNotFoundError(f"no checkpoint board at {board}")
    for rec in iter_gz_rows(board):
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001
            if bad is not None:
                bad.append(1)
            continue
        yield _to_dict(li)


# ------------------------------------------------------------------------------------------- run
def _peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def _normalize(res: Any, name: str) -> dict:
    if not isinstance(res, dict):
        return {"name": name, "checked": 0, "violations": 1, "max_violations": 0, "ok": False,
                "detail": f"finish() returned {type(res).__name__}, not a dict"}
    out = {k: res.get(k) for k in RESULT_KEYS}
    out["name"] = out["name"] or name
    for k in ("checked", "violations", "max_violations"):
        if not isinstance(out[k], int) or isinstance(out[k], bool):
            return {"name": out["name"], "checked": 0, "violations": 1, "max_violations": 0,
                    "ok": False, "detail": f"finish() field {k!r} is not an int"}
    # ok is the interface's definition, never the check's opinion of itself
    out["ok"] = out["violations"] <= out["max_violations"]
    if res.get("ok") is not None and bool(res.get("ok")) != out["ok"]:
        out["detail"] = f"{out.get('detail') or ''} [check said ok={res.get('ok')}; recomputed]".strip()
    out["detail"] = str(out.get("detail") or "")
    return out


def run_suite(rows: Iterable[dict], checks: list[tuple[str, Any, tuple]],
              limit: int | None = None, source: tuple[str, Path] | None = None) -> tuple[list[dict], int]:
    """Feed every row to every check (one pass); return ([result], rows fed). `source` is
    ("board", docs dir) or ("checkpoint", dir): a check with set_source(kind, path) is told where
    the rows come from (to read the run's side files there: run_health.json, resume_state.json)."""
    if source is not None:
        for _, c, _ in checks:
            if hasattr(c, "set_source"):
                try:
                    c.set_source(source[0], Path(source[1]))
                except Exception:  # noqa: BLE001 - reported by the check's own finish()
                    pass
    feed_errors = [0] * len(checks)
    first_error: list[str | None] = [None] * len(checks)
    n = 0
    for row in rows:
        if limit is not None and n >= limit:
            break
        n += 1
        for i, (_, c, _) in enumerate(checks):
            try:
                c.feed(row)
            except Exception as exc:  # noqa: BLE001 - one check's bug must not stop the pass
                feed_errors[i] += 1
                if first_error[i] is None:
                    first_error[i] = f"{type(exc).__name__}: {exc}"
    results = []
    for i, (stem, c, _) in enumerate(checks):
        name = str(getattr(c, "name", stem))
        try:
            res = _normalize(c.finish(), name)
        except Exception as exc:  # noqa: BLE001
            res = {"name": name, "checked": 0, "violations": 1, "max_violations": 0, "ok": False,
                   "detail": f"finish() raised {type(exc).__name__}: {exc}"}
        if feed_errors[i]:
            res["ok"] = False
            res["detail"] = (f"feed() raised on {feed_errors[i]} rows (first: {first_error[i]}); "
                             + res["detail"]).strip()
        res["module"] = stem
        results.append(res)
    return results, n


def print_table(results: list[dict], out=sys.stdout) -> None:
    w = max([len(r["name"]) for r in results] + [5])
    print(f"{'check':<{w}}  {'checked':>9}  {'violations':>10}  {'max':>6}  ok", file=out)
    for r in results:
        print(f"{r['name']:<{w}}  {r['checked']:>9,}  {r['violations']:>10,}  {r['max_violations']:>6,}  "
              f"{'yes' if r['ok'] else 'NO'}", file=out)
    for r in results:
        if r.get("detail"):
            print(f"  {r['name']}: {r['detail'][:400]}", file=out)


def result_doc(results: list[dict], source: str, rows: int, seconds: float, extra: dict | None = None) -> dict:
    """The suite_result.json body: counts only (no detail strings)."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source, "rows": rows, "seconds": round(seconds, 1),
        "peak_rss_mb": _peak_rss_mb(),
        "ok": all(r["ok"] for r in results),
        "not_ok": [r["name"] for r in results if not r["ok"]],
        "checks": [{k: r[k] for k in ("name", "module", "checked", "violations", "max_violations", "ok")}
                   for r in results],
        **(extra or {}),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run every scripts/audit_checks invariant over one board pass.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--checkpoint", nargs="?", const=str(REPO / "data" / "checkpoint"), default=None,
                     metavar="DIR", help="a checkpoint dir (default data/checkpoint)")
    src.add_argument("--board", default=None, metavar="PATH", help="a published board file or docs dir")
    ap.add_argument("--only", default=None, help="comma-separated check names (or module stems)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N rows (a sample, not a verdict)")
    ap.add_argument("--checks-dir", default=str(CHECKS_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-out", action="store_true", help="write no result file")
    ap.add_argument("--list", action="store_true", help="list the checks and exit")
    a = ap.parse_args(argv)

    checks = discover(Path(a.checks_dir))
    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        checks = [t for t in checks if t[0] in want or str(getattr(t[1], "name", "")) in want]
    if a.list:
        for stem, c, keys in checks:
            print(f"{stem:<22} {getattr(c, 'name', '?')}" + (f"  detail={','.join(keys)}" if keys else ""))
        return 0
    if not checks:
        print(f"no checks found in {a.checks_dir}", file=sys.stderr)
        return 1

    detail_keys = sorted({k for _, _, ks in checks for k in ks})
    bad: list = []
    if a.checkpoint:
        source = f"checkpoint:{a.checkpoint}"
        src_kind = ("checkpoint", Path(a.checkpoint))
        rows = checkpoint_rows(Path(a.checkpoint), bad)
    else:
        board = a.board or str(REPO / "docs")
        source = f"board:{board}"
        src_kind = ("board", Path(board) if Path(board).is_dir() else Path(board).parent)
        rows = published_rows(Path(board), detail_keys)
    t0 = time.monotonic()
    try:
        results, n = run_suite(rows, checks, limit=a.limit, source=src_kind)
    except Exception as exc:  # noqa: BLE001 - the board itself is unreadable
        print(f"board could not be read ({source}): {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(limit=3)
        return 2
    secs = time.monotonic() - t0
    print(f"{source}: {n:,} rows, {len(results)} checks, {secs:.0f}s, peak RSS {_peak_rss_mb()} MB"
          + (f", {len(bad):,} checkpoint rows did not validate" if bad else "")
          + (f" (LIMITED to {a.limit:,} rows: a sample, not a verdict)" if a.limit else ""))
    print_table(results)
    if not a.no_out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = result_doc(results, source, n, secs,
                         {"limited": a.limit, "invalid_checkpoint_rows": len(bad)})
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1) + "\n")
        os.replace(tmp, out)
        print(f"wrote {out}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
