#!/usr/bin/env python3
"""The canary: the FULL pipeline, with the planned run profile, on four small counties, in a scratch
copy of the repo, in minutes to an hour; then assert that every stage produced what it should.

WHY (audit 2026-10-09, pipeline_gate)
    Every recent defect showed up hours into an 18-hour run or after it: a whole-board json.loads
    that killed two runs 36 minutes in, an enricher that silently failed every row, a step that
    never ran on a resume, a RAW_KEEP key nobody produced. The same code on ~3,300 rows finds the
    same class of defect before the real run is launched.

WHAT IT DOES
    prepare  a scratch workspace (default data/canary/<stamp>/, git-ignored):
             * repo/: `git archive HEAD` of the code (src, scripts, deploy, pyproject.toml, uv.lock,
               docs minus the board files, the photo store and the 98 MB stealth hand-off), so the
               canary runs exactly the committed code, never the working tree;
             * repo/data/: a symlink per entry of the real data/ (parcel cache, footprints, voter
               files: read-only reference data) EXCEPT checkpoint*, heirs, canary, prerun_gate and
               test_results, which the canary keeps to itself;
             * repo/docs/listings.json.gz: the canary PRIOR board, the published board's rows of the
               canary counties (detail sidecar merged in), streamed once from the real docs/;
             * expectations.json: for those prior rows, the share of rows carrying each
               web_artifact.RAW_KEEP key; the enrichment keys >= --key-share of them carry are
               STRIPPED from the prior rows so the run must produce them again (keys only a
               script-only module writes are kept and listed as frozen);
             * .secrets / .env are symlinked (never read here) so keys reach the enrichers.
    run      main.run() in repo/ with the run profile (vm_lib.sh's vm_load_env when its secrets are
             present, else deploy/oracle/run_profile.json flags), FORECLOSURE_ONLY_SOURCES = the
             canary counties' slugs, FULLRUN_STOP_BEFORE_PUBLISH=1 (it never writes a board, only
             repo/data/checkpoint), the memory watchdog on Linux. Log: <ws>/canary.log.
    assert   exit 0 and a pre_publish checkpoint; no step logged <step>.failed (run_failures.py);
             every stripped key is back on >= PRODUCED_RATIO of its baseline share of the output
             rows (an enricher that produced nothing, or far less); every enrichment_stats key
             of --stats-baseline (a full run's resume_state.json) present; scripts/audit_suite.py
             passes on the canary checkpoint. Writes <ws>/canary_result.json; exit 1 on any failure.
    all      prepare + run + assert.

    The real board, docs/ and data/checkpoint of the real repo are never written. Enrichers' own
    caches under the symlinked data/ entries are shared with the real repo (they are caches).

NOTE ON STEALTH PATHS. A canary runs every enricher of the profile, including the existing
    browser paths a full run takes (FORECLOSURE_ROLE=vm drops the residential stealth scrapers, but
    e.g. the case-detail enricher still renders). --no-stealth sets CASE_DETAIL_OFF=1 and
    COURT_RECORDS_OFF=1 for a canary that must not touch them.

USAGE
    uv run python scripts/canary_run.py plan
    uv run python scripts/canary_run.py all [--ws DIR] [--timeout 3600]   # on the VM, after the gate
    uv run python scripts/canary_run.py assert --ws DIR
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

#: 2 NC + 2 SC small counties with a wide source mix on the 10/7 board (Polk 586 rows / 28 sources,
#: Mitchell 330 / 24, Union SC 1,351 / 21, Greenwood 1,040 / 9), all in the core footprint.
COUNTIES = (("NC", "Polk"), ("NC", "Mitchell"), ("SC", "Union"), ("SC", "Greenwood"))
#: FORECLOSURE_ONLY_SOURCES substrings: the scrapers named for those counties
SOURCE_SUBSTRINGS = ("polk", "mitchell", "union", "greenwood")
CODE_PATHS = ("src", "scripts", "deploy", "pyproject.toml", "uv.lock", ".python-version")
DOCS_EXCLUDE = ("docs/listings_part_*", "docs/listings_detail*", "docs/listings_slim*",
                "docs/listings.json*", "docs/board.manifest.json", "docs/parcel_photos",
                "docs/handoff/stealth_leads.json", "docs/handoff/stealth_leads")
DATA_PRIVATE = ("checkpoint", "checkpoint_archive", "heirs", "canary", "prerun_gate", "test_results")
KEY_SHARE = 0.25
#: a strip key must come back on at least this share of its baseline (an enricher that ran but
#: reached far fewer rows than the run that built the prior board is as suspect as a dead one)
PRODUCED_RATIO = 0.3
#: lifecycle markers of rows the run carries, not enrichment products: never stripped or asserted
LIFECYCLE_KEYS = frozenset({"pulled_sale", "stale_case", "is_new", "first_seen_run", "geo_imprecise"})


# ------------------------------------------------------------------------------------- prepare
def export_code(dest: Path, repo: Path = REPO, ref: str = "HEAD") -> int:
    """`git archive <ref>` of the code and the light docs into `dest`; returns files written."""
    specs = list(CODE_PATHS) + ["docs"] + [f":(exclude){p}" for p in DOCS_EXCLUDE]
    present = [p for p in specs if p.startswith(":") or (repo / p).exists()]
    r = subprocess.run(["git", "archive", ref, "--", *present], cwd=repo, capture_output=True, check=True)
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            tf.extract(m, dest, filter="data")
            n += m.isfile()
    return n


def link_data(dest_repo: Path, repo: Path = REPO) -> list[str]:
    """repo/data/<entry> -> the real data/<entry>, for every entry except DATA_PRIVATE."""
    src = repo / "data"
    d = dest_repo / "data"
    d.mkdir(parents=True, exist_ok=True)
    linked = []
    if src.is_dir():
        for e in sorted(src.iterdir()):
            if e.name in DATA_PRIVATE or e.name.startswith("."):
                continue
            t = d / e.name
            if not t.exists():
                t.symlink_to(e.resolve())
                linked.append(e.name)
    for name in (".secrets", ".env"):
        if (repo / name).exists() and not (dest_repo / name).exists():
            (dest_repo / name).symlink_to((repo / name).resolve())
    return linked


def in_canary(row: dict, counties=COUNTIES) -> bool:
    st = str(row.get("state") or "").upper()
    co = str(row.get("county") or "").strip().lower()
    return any(st == s and co == c.lower() for s, c in counties)


def key_shares(rows: Iterable[dict], keys: Iterable[str]) -> tuple[dict, int]:
    keys = list(keys)
    n = 0
    have = dict.fromkeys(keys, 0)
    for r in rows:
        n += 1
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        for k in keys:
            if raw.get(k) not in (None, "", [], {}):
                have[k] += 1
    return ({k: round(v / n, 4) for k, v in have.items() if v} if n else {}), n


def write_prior(rows: Iterable[dict], path: Path) -> int:
    """A single gzipped JSON array (what merge_prior_board reads when no parts board is there)."""
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("[")
        for r in rows:
            if n:
                fh.write(", ")
            fh.write(json.dumps(r))
            n += 1
        fh.write("]")
    return n


def prepare(ws: Path, repo: Path = REPO, board: Path | None = None, key_share: float = KEY_SHARE) -> dict:
    from foreclosure_scraper.board_stream import iter_board_rows_with_detail
    from foreclosure_scraper.web_artifact import LAZY_DETAIL_KEYS, RAW_KEEP
    ws.mkdir(parents=True, exist_ok=True)
    rrepo = ws / "repo"
    files = export_code(rrepo, repo)
    linked = link_data(rrepo, repo)
    src_board = board or (repo / "docs" / "listings.json.gz")
    from foreclosure_scraper.board_stream import iter_board_rows
    try:
        rows = iter_board_rows_with_detail(src_board, LAZY_DETAIL_KEYS)
        first = next(rows, None)
    except FileNotFoundError:                     # no detail sidecar beside this board
        rows, first = iter_board_rows(src_board), None
    kept: list[dict] = []
    for r in ([first] if first is not None else []):
        if in_canary(r):
            kept.append(r)
    for r in rows:
        if in_canary(r):
            kept.append(r)
    shares, n = key_shares(kept, sorted(RAW_KEEP))
    # Every enrichment product the prior rows commonly carry is STRIPPED from them, so the canary's
    # enrichers must produce it again from scratch (an idempotent enricher skips a row that already
    # has its key: presence on a carried row proves nothing). Keys no run step writes (a script-only
    # enricher's, pipeline_wiring.raw_key_producers) are kept as they are and reported as frozen.
    sys.path.insert(0, str(repo / "scripts"))
    import pipeline_wiring as W
    common = sorted(k for k, s in shares.items() if s >= key_share and k not in LIFECYCLE_KEYS)
    prod = W.raw_key_producers(common, repo)
    frozen = sorted(k for k in common if prod[k]["writers"] and not prod[k]["in_run"])
    strip = [k for k in common if k not in frozen]
    for r in kept:
        raw = r.get("raw")
        if isinstance(raw, dict):
            for k in strip:
                raw.pop(k, None)
    prior_n = write_prior(kept, rrepo / "docs" / "listings.json.gz")
    exp = {"prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "stripped_keys": strip, "frozen_keys": frozen, "key_share_threshold": key_share,
           "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                                    text=True).stdout.strip(),
           "counties": [list(c) for c in COUNTIES], "source_substrings": list(SOURCE_SUBSTRINGS),
           "prior_rows": prior_n, "key_share": shares, "files_exported": files, "data_linked": linked}
    (ws / "expectations.json").write_text(json.dumps(exp, indent=1))
    return exp


# ------------------------------------------------------------------------------------------- run
def profile_env(repo: Path = REPO) -> dict:
    """The run's env: vm_lib.sh vm_load_env (secrets from the REAL repo's .secrets) when it loads,
    else the run_profile.json flags (the gate keeps the two equal)."""
    log = "/dev/null"
    cmd = (f'ROOT="{repo}"; cd "$ROOT"; . deploy/oracle/vm_lib.sh; vm_load_env {log} >/dev/null 2>&1 '
           f'&& env -0')
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            env = dict(kv.split("=", 1) for kv in r.stdout.decode("utf-8", "replace").split("\0") if "=" in kv)
            env["CANARY_ENV_FROM"] = "vm_lib.sh"
            return env
    except (OSError, subprocess.SubprocessError):
        pass
    env = dict(os.environ)
    prof = json.loads((repo / "deploy" / "oracle" / "run_profile.json").read_text())
    env.update({k: str(v) for k, v in (prof.get("flags") or {}).items()})
    env["CANARY_ENV_FROM"] = "run_profile.json (vm_lib.sh secrets not loadable here)"
    return env


def canary_env(ws: Path, base: dict, *, no_stealth: bool = False) -> dict:
    rrepo = ws / "repo"
    env = dict(base)
    # the canary proves every enricher runs end to end on a few counties, not that it finishes its
    # real budget: every phase is capped (a 3,237-row canary spent 3 h inside the photo, street-view
    # and geocode phases' own budgets); a caller's value wins
    env.setdefault("ENRICH_PHASE_CAP_ALL", "120")
    env.setdefault("RESOLVER_PHASE_MAX_SECONDS", "120")
    env.update({
        "FORECLOSURE_ONLY_SOURCES": ",".join(SOURCE_SUBSTRINGS),
        "FULLRUN_STOP_BEFORE_PUBLISH": "1",
        "FORECLOSURE_CHECKPOINT_DIR": str(rrepo / "data" / "checkpoint"),
        "SCRAPE_PHASE_MAX_SECONDS": env.get("CANARY_SCRAPE_MAX_SECONDS", "1800"),
        "PYTHONPATH": str(rrepo / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        "PYTHONUNBUFFERED": "1",
    })
    for k in ("GRANDFATHER_CARRIED", "FULLRUN_PERSIST", "ENRICH_PHASE_MAX_SECONDS", "SCORE_BOARD_FAIL_SOFT"):
        env.pop(k, None)
    if no_stealth:
        env["CASE_DETAIL_OFF"] = "1"
        env["COURT_RECORDS_OFF"] = "1"
    return env


def run(ws: Path, *, timeout: int = 3600, no_stealth: bool = False) -> int:
    rrepo = ws / "repo"
    if not (rrepo / "src").is_dir():
        print(f"no prepared workspace at {ws} (run prepare first)", file=sys.stderr)
        return 1
    env = canary_env(ws, profile_env(), no_stealth=no_stealth)
    log = ws / "canary.log"
    cmd = [sys.executable, "-m", "foreclosure_scraper"]
    t0 = time.monotonic()
    with open(log, "ab") as fh:
        fh.write(f"==> canary run in {rrepo} env from {env.get('CANARY_ENV_FROM')}\n".encode())
        p = subprocess.Popen(cmd, cwd=rrepo, env=env, stdout=fh, stderr=subprocess.STDOUT)
        wd = None
        if sys.platform.startswith("linux") and (REPO / "deploy" / "oracle" / "mem_watchdog.py").exists():
            wd = subprocess.Popen([sys.executable, str(REPO / "deploy" / "oracle" / "mem_watchdog.py"),
                                   "--pid", str(p.pid), "--log", str(ws / "canary.mem.log"),
                                   "--kill-total-mb", env.get("CANARY_KILL_TOTAL_MB", "8000")])
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = 124
        if wd is not None:
            wd.wait(timeout=30)
    (ws / "run.json").write_text(json.dumps({"rc": rc, "seconds": round(time.monotonic() - t0),
                                             "env_from": env.get("CANARY_ENV_FROM")}))
    print(f"canary run exit {rc} in {time.monotonic() - t0:.0f}s, log {log}")
    return rc


# ---------------------------------------------------------------------------------------- assert
def fresh_rows(rows: Iterable[dict], since: str) -> Iterator[dict]:
    for r in rows:
        if str(r.get("first_seen") or "") >= since:
            yield r


def evaluate(*, rc: int | None, manifest: dict | None, failures: dict, expectations: dict,
             fresh_shares: dict, fresh_n: int, stats: dict, stats_baseline: Iterable[str],
             suite_rc: int | None, key_share: float = KEY_SHARE) -> dict:
    """The canary's verdict from what the run left (pure; tests feed it made-up inputs)."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("exit", rc == 0, f"main.run exit {rc}")
    add("checkpoint", bool(manifest) and manifest.get("phase") == "pre_publish",
        f"checkpoint phase {(manifest or {}).get('phase')!r}, {(manifest or {}).get('count')} rows")
    nf = sum((failures.get("failed") or {}).values())
    add("no-swallowed-failures", nf == 0,
        "no step logged .failed" if not nf else
        "step failures: " + ", ".join(f"{k} x{v}" for k, v in (failures.get("failed") or {}).items()))
    base = expectations.get("key_share") or {}
    want = expectations.get("stripped_keys")
    if want is None:
        want = sorted(k for k, s in base.items() if s >= key_share and k not in LIFECYCLE_KEYS)
    short = [k for k in want if (fresh_shares.get(k) or 0) < PRODUCED_RATIO * float(base.get(k) or 0)
             or not fresh_shares.get(k)]
    add("raw-keep-produced", fresh_n > 0 and not short,
        f"{len(want) - len(short)}/{len(want)} enrichment keys stripped from the prior rows came back on "
        f">= {PRODUCED_RATIO:.0%} of their baseline share ({fresh_n} rows)"
        + (f"; not produced (share now vs before): "
           + ", ".join(f"{k} {fresh_shares.get(k, 0):.2f}/{float(base.get(k) or 0):.2f}" for k in short[:20])
           if short else "")
        + (f"; frozen (no run step writes them): {', '.join(expectations.get('frozen_keys') or [])}"
           if expectations.get("frozen_keys") else ""))
    base = sorted(set(stats_baseline or ()))
    gone = [k for k in base if k not in (stats or {})]
    add("enrichment-stats", not gone,
        f"{len(base) - len(gone)}/{len(base)} enrichers of the baseline run reported stats"
        + (f"; silent: {', '.join(gone[:20])}" if gone else ""))
    add("audit-suite", suite_rc == 0, f"audit_suite.py exit {suite_rc}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "time_capped": failures.get("time_capped") or {}}


def assert_ws(ws: Path, stats_baseline: Path | None = None, key_share: float = KEY_SHARE) -> int:
    sys.path.insert(0, str(REPO / "deploy" / "oracle"))
    import run_failures  # noqa: E402
    rrepo = ws / "repo"
    ck = rrepo / "data" / "checkpoint"
    exp = json.loads((ws / "expectations.json").read_text())
    runinfo = json.loads((ws / "run.json").read_text()) if (ws / "run.json").exists() else {}
    man = json.loads((ck / "manifest.json").read_text()) if (ck / "manifest.json").exists() else None
    state = json.loads((ck / "resume_state.json").read_text()) if (ck / "resume_state.json").exists() else {}
    with open(ws / "canary.log", encoding="utf-8", errors="replace") as fh:
        failures = run_failures.scan(fh)
    fresh_sh, fresh_n = {}, 0
    if (ck / "board.json.gz").exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("audit_suite", REPO / "scripts" / "audit_suite.py")
        S = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(S)
        from foreclosure_scraper.web_artifact import RAW_KEEP
        # every output row went through the enrichers (the prior rows were stripped of their keys)
        fresh_sh, fresh_n = key_shares(S.checkpoint_rows(ck), sorted(RAW_KEEP))
    base_keys: list = []
    if stats_baseline and Path(stats_baseline).exists():
        base_keys = list((json.loads(Path(stats_baseline).read_text()).get("enrichment_stats") or {}).keys())
    suite_rc = None
    if (ck / "board.json.gz").exists():
        suite_rc = subprocess.run([sys.executable, str(REPO / "scripts" / "audit_suite.py"), "--checkpoint",
                                   str(ck), "--out", str(ws / "suite_result.json")]).returncode
    res = evaluate(rc=runinfo.get("rc"), manifest=man, failures=failures, expectations=exp,
                   fresh_shares=fresh_sh, fresh_n=fresh_n, stats=state.get("enrichment_stats") or {},
                   stats_baseline=base_keys, suite_rc=suite_rc, key_share=key_share)
    (ws / "canary_result.json").write_text(json.dumps(res, indent=1))
    for c in res["checks"]:
        print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']:<22} {c['detail']}")
    if res["time_capped"]:
        print("note: time-capped phases: " + ", ".join(f"{k} x{v}" for k, v in res["time_capped"].items()))
    print("CANARY PASSED" if res["ok"] else "CANARY FAILED")
    return 0 if res["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The canary: the full pipeline on four small counties.")
    ap.add_argument("cmd", choices=("plan", "prepare", "run", "assert", "all"))
    ap.add_argument("--ws", default=str(REPO / "data" / "canary" / datetime.now().strftime("%Y%m%dT%H%M%S")))
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--no-stealth", action="store_true")
    ap.add_argument("--stats-baseline", default=None,
                    help="a full run's resume_state.json: its enrichment_stats keys must all reappear")
    ap.add_argument("--key-share", type=float, default=KEY_SHARE)
    a = ap.parse_args(argv)
    ws = Path(a.ws)
    if a.cmd == "plan":
        print(f"counties: {', '.join(f'{c} {s}' for s, c in COUNTIES)}")
        print(f"FORECLOSURE_ONLY_SOURCES={','.join(SOURCE_SUBSTRINGS)}  FULLRUN_STOP_BEFORE_PUBLISH=1")
        print(f"workspace: {ws}  (code = git archive HEAD; data/ symlinked except {', '.join(DATA_PRIVATE)})")
        print(f"assert: exit 0, pre_publish checkpoint, no <step>.failed, RAW_KEEP keys on >= {a.key_share:.0%} "
              f"of prior rows produced on fresh rows, enrichment_stats vs --stats-baseline, audit suite")
        return 0
    if a.cmd in ("prepare", "all"):
        exp = prepare(ws, key_share=a.key_share)
        print(f"prepared {ws}: {exp['prior_rows']} prior rows, {exp['files_exported']} files, "
              f"{len(exp['stripped_keys'])} enrichment keys stripped to be re-produced, "
              f"frozen (no run step writes them): {', '.join(exp['frozen_keys']) or 'none'}")
    if a.cmd in ("run", "all"):
        rc = run(ws, timeout=a.timeout, no_stealth=a.no_stealth)
        if a.cmd == "run":
            return rc
    if a.cmd in ("assert", "all"):
        return assert_ws(ws, Path(a.stats_baseline) if a.stats_baseline else None, a.key_share)
    return 0


if __name__ == "__main__":
    sys.exit(main())
