#!/usr/bin/env python3
"""The pre-run gate: refuse to start an 18-hour run that is outdated or broken on arrival.

WHY (audit 2026-10-09, pipeline_gate)
    The owner kept finding the next defect after each long run had started: the run pinned a
    commit older than the fixes it was meant to carry (the 10/8 run, pinned d42058b3, has none
    of the tax_binding scrub, the verified-tax restore or the 10/8 ledgers), two full runs were
    killed by the memory watchdog 36 minutes in by a whole-board json.loads, enrichers sat built
    and never wired, flags drifted. Each of those is checkable BEFORE launch, in minutes. This
    checks them all and exits non-zero unless every one passes.

THE CHECKS (each PASS / WARN / FAIL / SKIP, one line why)
    git          tracked tree clean (an uncommitted ledger means the sweep is mid-write or did not
                 commit); untracked files are a warning
    pin          --pin / RUN_PIN_COMMIT equals HEAD: every commit meant for the run is on the pin
    pushed       the pin is on origin/main as of the last fetch (the VM can only check out what
                 was pushed); ahead/behind reported. Never fetches.
    tests        data/test_results/latest.json (scripts/run_test_suite.py) is a FULL run, green,
                 and no code path changed between its commit and HEAD
    ci           GitHub's Tests workflow (suite on a fresh checkout + repo size) is green on the pin
                 (gh CLI; a failed run fails, no gh / no run / still running warns)
    ledgers      docs/handoff/verification committed within ledgers.max_age_h, no ledger modified
                 in the working tree, no verification sweep running
    handoff      the Mac's stealth hand-off committed within handoff.max_age_h (warning only)
    repo-size    scripts/repo_size_check.py on HEAD: no tracked file over 90 MiB (the commit gate
                 refuses 95 MiB, GitHub 100 MiB) and the Pages site (tracked docs/ minus the
                 _config.yml excludes) under 900 MB (pages.yml stops at 950, Pages refuses 1 GB)
    manual       scripts/build_owner_manual.py --check (walls register + owner manual current)
    memory       projected peak = max measured MB-per-row x prior board rows x growth_factor, under
                 the watchdog kill line (deploy/oracle/run_profile.json "memory"); warning above
                 warn_fraction. Prints the row count at which the run would be killed.
    board-loads  no whole-file json.load of a board-scale file in the run path that is not
                 reviewed in run_profile.json board_load_allowlist (the carryover kill)
    unwired      no enrichment / scraper module that no run path reaches, unless listed with a
                 reason in run_profile.json unwired_allowlist (listed ones print as a warning)
    frozen-keys  no published raw key whose only writers are unwired modules, unless listed in
                 run_profile.json frozen_keys_known (a warning: values frozen since a script ran)
    flags        deploy/oracle/vm_lib.sh exports exactly the run_profile.json flags; none of
                 must_not_set is exported by vm_lib.sh or set in this environment (prints the
                 profile)
    registry     every scraper module imports (scrapers/_registry.discover() drops a module that
                 fails to import and says so only in the log: 27 sources vanished once)
    suite        scripts/audit_suite.py passes on the last checkpoint (data/checkpoint, or
                 --checkpoint DIR); with no checkpoint, on the published board (said so)

USAGE
    uv run python scripts/prerun_gate.py --pin <sha>            # all checks
    uv run python scripts/prerun_gate.py --pin <sha> --skip suite,registry   # faster; exit 2
    uv run python scripts/prerun_gate.py --json
Exit 0 every check passed (warnings allowed), 1 any FAILED, 2 none failed but some were skipped.
Writes data/prerun_gate/last.json (counts and verdicts only).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "deploy" / "oracle" / "run_profile.json"
sys.path.insert(0, str(REPO / "scripts"))

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


def _git(repo: Path, *args, check: bool = False) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return r.returncode, (r.stdout or "").rstrip()


def load_profile(path: Path = PROFILE) -> dict:
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------------------------------ checks
def check_git(repo: Path, profile: dict) -> tuple[str, str]:
    rc, out = _git(repo, "status", "--porcelain")
    if rc:
        return FAIL, f"git status failed: {out[:120]}"
    tracked = [ln for ln in out.splitlines() if ln and not ln.startswith("??")]
    untracked = [ln for ln in out.splitlines() if ln.startswith("??")]
    if tracked:
        ledger = [ln for ln in tracked if (profile.get("ledgers") or {}).get("dir", "docs/handoff/verification") in ln]
        why = f"{len(tracked)} tracked file(s) modified or staged (e.g. {tracked[0][3:][:80]})"
        if ledger:
            why += f"; {len(ledger)} verification ledger(s) uncommitted: a sweep is mid-write or did not commit"
        return FAIL, why
    if untracked:
        return WARN, f"clean; {len(untracked)} untracked file(s) (not part of the run)"
    return PASS, "clean"


def check_pin(repo: Path, pin: str | None) -> tuple[str, str]:
    if not pin:
        return FAIL, "no pin given (--pin or RUN_PIN_COMMIT): a gated run must run one reviewed commit"
    rc, want = _git(repo, "rev-parse", "--verify", "--quiet", f"{pin}^{{commit}}")
    if rc or not want:
        return FAIL, f"pin {pin} is not a commit in this checkout"
    _, head = _git(repo, "rev-parse", "HEAD")
    if want != head:
        rc2, n = _git(repo, "rev-list", "--count", f"{want}..{head}")
        extra = f"; HEAD has {n} commit(s) the pin lacks" if rc2 == 0 and n not in ("", "0") else ""
        return FAIL, f"pin {want[:10]} is not HEAD {head[:10]}{extra}: commits meant for the run are not on it"
    return PASS, f"pin == HEAD {head[:10]}"


def check_pushed(repo: Path, ref: str = "origin/main") -> tuple[str, str]:
    rc, _ = _git(repo, "rev-parse", "--verify", "--quiet", ref)
    if rc:
        return WARN, f"no {ref} ref in this checkout: cannot tell whether HEAD was pushed"
    rc, _ = _git(repo, "merge-base", "--is-ancestor", "HEAD", ref)
    _, counts = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
    ahead, behind = (counts.split() + ["?", "?"])[:2]
    if rc == 0:
        return PASS, f"HEAD is on {ref} (as of the last fetch; {behind} commit(s) behind it)"
    return FAIL, (f"HEAD is {ahead} commit(s) ahead of {ref} (as of the last fetch): the VM cannot "
                  f"check out an unpushed pin")


def check_tests(repo: Path, profile: dict) -> tuple[str, str]:
    p = repo / profile.get("test_results", "data/test_results/latest.json")
    if not p.exists():
        return FAIL, f"no test results ({p.relative_to(repo)}): run scripts/run_test_suite.py"
    try:
        res = json.loads(p.read_text())
    except ValueError:
        return FAIL, "test results file is unreadable"
    if res.get("kind") != "full":
        return FAIL, f"the last recorded run was {res.get('kind')!r}, not the full suite"
    if not res.get("green"):
        return FAIL, (f"last full suite NOT green: {res.get('failed')} failed, {res.get('errors')} errors "
                      f"at {str(res.get('commit'))[:10]}")
    if res.get("tree_dirty"):
        return FAIL, "the last full suite ran on a dirty tree: re-run it on the committed code"
    commit = str(res.get("commit") or "")
    if not commit:
        return FAIL, "test results name no commit"
    paths = profile.get("code_paths") or ["src", "scripts", "deploy", "tests"]
    rc, diff = _git(repo, "diff", "--name-only", commit, "HEAD", "--", *paths)
    if rc:
        return FAIL, f"tested commit {commit[:10]} is not in this checkout"
    if diff:
        files = diff.splitlines()
        return FAIL, (f"{len(files)} code file(s) changed since the green suite at {commit[:10]} "
                      f"(e.g. {files[0]}): re-run scripts/run_test_suite.py")
    return PASS, f"{res.get('passed')} passed, 0 failed at {commit[:10]} ({res.get('finished_at')}); no code change since"


def _commit_age_h(repo: Path, path: str) -> float | None:
    rc, ts = _git(repo, "log", "-1", "--format=%ct", "--", path)
    if rc or not ts:
        return None
    return (time.time() - int(ts)) / 3600.0


def _sweep_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "verification_sweep\\.py"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _gh(repo: Path, args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return r.returncode, ((r.stdout or "") if r.returncode == 0 else (r.stderr or r.stdout or "")).strip()


def check_ci(repo: Path, pin: str | None,
             gh: Callable[[Path, list[str]], tuple[int, str]] = _gh) -> tuple[str, str]:
    """GitHub's Tests workflow (.github/workflows/tests.yml: the suite on a fresh checkout, and the
    repo size limits) on the pinned commit. The 'tests' check runs the suite on THIS machine, which
    holds gitignored data a fresh checkout lacks (data/sc_parcel_mailing.db): CI failed on every push
    from 2026-10-07 to 10-09 on a test that read that roll, while every local run was green. A
    failed workflow on the pin is refused; no gh, no network, no run yet or a run in progress is a
    warning."""
    if not pin:
        return WARN, "no pin: GitHub CI not checked"
    rc, sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{pin}^{{commit}}")
    if rc or not sha:
        return WARN, f"pin {pin} is not a commit in this checkout: GitHub CI not checked"
    rc, out = gh(repo, ["run", "list", "--workflow", "Tests", "--commit", sha, "--limit", "10",
                        "--json", "databaseId,status,conclusion,createdAt"])
    if rc != 0:
        return WARN, f"could not read GitHub CI for {sha[:10]} (gh): {out[:160]}"
    try:
        runs = sorted(json.loads(out or "[]"), key=lambda r: r.get("createdAt") or "", reverse=True)
    except ValueError:
        return WARN, "could not parse gh run list output"
    if not runs:
        return WARN, f"no Tests workflow run on GitHub for {sha[:10]} yet (pushed?)"
    done = [r for r in runs if r.get("status") == "completed"
            and r.get("conclusion") not in ("cancelled", "skipped")]
    if not done:
        return WARN, f"the Tests workflow on {sha[:10]} has not finished (run {runs[0].get('databaseId')})"
    last = done[0]
    if last.get("conclusion") == "success":
        return PASS, f"Tests workflow green on {sha[:10]} (run {last.get('databaseId')})"
    return FAIL, (f"Tests workflow {last.get('conclusion')} on {sha[:10]} (run {last.get('databaseId')}): "
                  f"gh run view {last.get('databaseId')} --log-failed")


def check_ledgers(repo: Path, profile: dict, sweep_running: Callable[[], bool] = _sweep_running) -> tuple[str, str]:
    cfg = profile.get("ledgers") or {}
    d = cfg.get("dir", "docs/handoff/verification")
    max_h = float(cfg.get("max_age_h", 36))
    if not (repo / d).is_dir():
        return FAIL, f"no ledger directory {d}"
    _, dirty = _git(repo, "status", "--porcelain", "--", d)
    if dirty:
        return FAIL, f"{len(dirty.splitlines())} ledger(s) modified in the working tree: the sweep is mid-write or did not commit"
    if sweep_running():
        return FAIL, "a verification sweep is running: wait for it to commit, then re-pin"
    ages = {}
    # either layout (verification.ledger LAYOUTS): <signal>.json, or <signal>/ (manifest + shards)
    for p in sorted([*(repo / d).glob("*.json"), *(repo / d).glob("*/manifest.json")]):
        q = p.parent if p.name == "manifest.json" else p
        a = _commit_age_h(repo, str(q.relative_to(repo)))
        name = q.name if q.is_dir() else q.stem
        if a is not None and (name not in ages or a < ages[name]):
            ages[name] = a
    if not ages:
        return FAIL, "no committed ledgers"
    newest = min(ages.values())
    if newest > max_h:
        return FAIL, f"newest ledger commit is {newest:.0f} h old (> {max_h:.0f} h)"
    old = [k for k, a in ages.items() if a > max_h * 4]
    msg = f"{len(ages)} ledgers, newest commit {newest:.1f} h old"
    if old:
        return WARN, msg + f"; not updated in {max_h * 4:.0f} h: {', '.join(old)}"
    return PASS, msg


def check_handoff(repo: Path, profile: dict) -> tuple[str, str]:
    """Age of the newest commit that touched the hand-off: the sharded directory (since
    2026-10-09, stealth_handoff_store) or the legacy single file, whichever is newer."""
    cfg = profile.get("handoff") or {}
    paths = [cfg.get("dir", "docs/handoff/stealth_leads"),
             cfg.get("file", "docs/handoff/stealth_leads.json")]
    ages = [a for a in (_commit_age_h(repo, p) for p in paths) if a is not None]
    if not ages:
        return WARN, f"no committed {' or '.join(paths)}"
    a = min(ages)
    if a > float(cfg.get("max_age_h", 36)):
        return WARN, f"the Mac's stealth hand-off is {a:.0f} h old: the run ingests stale stealth leads"
    return PASS, f"stealth hand-off {a:.1f} h old"


def check_repo_size(repo: Path, profile: dict) -> tuple[str, str]:
    """scripts/repo_size_check.py on HEAD: no tracked file over max_file_mib (the pre-commit gate
    refuses 95 MiB, GitHub 100 MiB) and the Pages site under max_pages_mb (pages.yml stops a
    deploy at 950 MB, Pages refuses 1 GB). Limits from run_profile.json "repo_size"."""
    import repo_size_check as rsc
    cfg = profile.get("repo_size") or {}
    r = rsc.measure(repo, "HEAD",
                    max_file_mib=float(cfg.get("max_file_mib", rsc.MAX_FILE_MIB)),
                    warn_file_mib=float(cfg.get("warn_file_mib", rsc.WARN_FILE_MIB)),
                    max_pages_mb=float(cfg.get("max_pages_mb", rsc.MAX_PAGES_MB)),
                    warn_pages_mb=float(cfg.get("warn_pages_mb", rsc.WARN_PAGES_MB)))
    if not r["ok"]:
        return FAIL, rsc.summary(r)
    if r["warnings"]:
        return WARN, rsc.summary(r) + "; " + "; ".join(r["warnings"][:3])
    return PASS, rsc.summary(r)


def check_manual(repo: Path, offline: bool = False) -> tuple[str, str]:
    script = repo / "scripts" / "build_owner_manual.py"
    if not script.exists():
        return FAIL, "scripts/build_owner_manual.py is missing"
    if not (repo / "docs" / "walls_register.json").exists():
        return FAIL, "docs/walls_register.json is missing"
    cmd = [sys.executable, str(script), "--check"] + (["--offline"] if offline else [])
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return FAIL, "build_owner_manual.py --check timed out"
    last = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-1:] or [""]
    return (PASS if r.returncode == 0 else FAIL), last[0][:200]


# ---- memory
def prior_board_rows(repo: Path) -> tuple[int | None, int, str]:
    """(rows, bytes, how) of the board the next run merges: the parts manifest's count, else a
    streamed count of the plain docs/listings.json (never loaded)."""
    docs = repo / "docs"
    man = docs / "board.manifest.json"
    if man.exists():
        try:
            m = json.loads(man.read_text())
            if isinstance(m.get("count"), int):
                size = sum(p.stat().st_size for p in docs.glob("listings_part_*.json.gz"))
                plain = docs / "listings.json"
                if plain.exists() and plain.stat().st_mtime >= man.stat().st_mtime - 3600:
                    size = plain.stat().st_size      # the VM keeps the plain board beside the parts
                return m["count"], size, "docs/board.manifest.json count"
        except (ValueError, OSError):
            pass
    plain = docs / "listings.json"
    if plain.exists():
        sys.path.insert(0, str(repo / "src"))
        from foreclosure_scraper.web_artifact import plain_board_row_count
        return plain_board_row_count(plain), plain.stat().st_size, "streamed count of docs/listings.json"
    return None, 0, "no prior board found"


def memory_projection(rows: int, mem: dict) -> dict:
    cal = [c for c in (mem.get("calibration") or []) if c.get("rows_out") and c.get("peak_mb")]
    if not cal:
        return {"ok": False, "why": "no calibration points"}
    per_row = max(c["peak_mb"] / c["rows_out"] for c in cal)       # MB per row, worst measured
    growth = float(mem.get("growth_factor", 1.15))
    kill = float(mem.get("kill_mb", 25600))
    proj_rows = int(rows * growth)
    peak = per_row * proj_rows
    return {"ok": peak < kill, "warn": peak >= kill * float(mem.get("warn_fraction", 0.9)),
            "per_row_kb": round(per_row * 1024, 1), "projected_rows": proj_rows,
            "projected_peak_mb": round(peak), "kill_mb": kill,
            "max_rows_before_kill": int(kill / per_row),
            "basis": max(cal, key=lambda c: c["peak_mb"] / c["rows_out"]).get("run")}


def check_memory(repo: Path, profile: dict) -> tuple[str, str]:
    rows, size, how = prior_board_rows(repo)
    if not rows:
        return FAIL, f"cannot size the prior board ({how})"
    p = memory_projection(rows, profile.get("memory") or {})
    if "projected_peak_mb" not in p:
        return FAIL, p.get("why", "no projection")
    msg = (f"prior {rows:,} rows ({size / 2**30:.1f} GiB, {how}) x{(profile.get('memory') or {}).get('growth_factor', 1.15)}"
           f" -> {p['projected_rows']:,} rows x {p['per_row_kb']} KB/row (worst measured, {p['basis']}) = "
           f"{p['projected_peak_mb']:,} MB vs kill {p['kill_mb']:.0f} MB; killed above ~{p['max_rows_before_kill']:,} rows")
    if not p["ok"]:
        return FAIL, msg
    return (WARN if p["warn"] else PASS), msg


# ---- static: board loads, unwired modules, flags
def check_board_loads(repo: Path, profile: dict) -> tuple[str, str]:
    import pipeline_wiring as W
    allow = profile.get("board_load_allowlist") or {}
    hits = W.whole_file_json_loads(repo)
    new = sorted({h["site"] for h in hits} - set(allow))
    if new:
        first = next(h for h in hits if h["site"] == new[0])
        return FAIL, (f"{len(new)} unreviewed whole-file json load(s) of a board-scale file in the run "
                      f"path: {', '.join(new[:5])} (e.g. line {first['line']}: {first['call']})")
    return PASS, f"{len(hits)} whole-file loads in the run path, all reviewed (small files or gated off)"


def check_unwired(repo: Path, profile: dict) -> tuple[str, str]:
    import pipeline_wiring as W
    allow = profile.get("unwired_allowlist") or {}
    rows = W.unwired(repo)
    new = [r for r in rows if r["module"] not in allow]
    stale = sorted(set(allow) - {r["module"] for r in rows})
    if new:
        return FAIL, (f"{len(new)} module(s) no run path reaches and no reason recorded: "
                      + ", ".join(f"{r['module']} ({r['status']})" for r in new[:8]))
    msg = f"{len(rows)} unwired module(s), each with a recorded reason"
    if stale:
        msg += f"; allowlist names {len(stale)} now wired or gone: {', '.join(stale[:5])} (tidy the profile)"
    return (WARN if rows or stale else PASS), msg


def check_frozen_keys(repo: Path, profile: dict) -> tuple[str, str]:
    """Published raw keys whose only writers are modules no run path reaches: their values on the
    board are whatever a script last wrote, never refreshed. A warning (each needs a wire-or-retire
    decision), a failure only for a key not listed in run_profile.json frozen_keys_known."""
    import pipeline_wiring as W
    sys.path.insert(0, str(repo / "src"))
    from foreclosure_scraper.web_artifact import RAW_KEEP
    prod = W.raw_key_producers(sorted(RAW_KEEP), repo)
    frozen = sorted(k for k, v in prod.items() if v["writers"] and not v["in_run"])
    known = set(profile.get("frozen_keys_known") or [])
    new = [k for k in frozen if k not in known]
    if new:
        return FAIL, (f"{len(new)} published key(s) only an unwired module writes (frozen on the board): "
                      + ", ".join(f"{k} <- {'/'.join(prod[k]['writers'][:2])}" for k in new[:8]))
    return (WARN if frozen else PASS), (f"{len(frozen)} published keys are frozen (written only by "
                                        f"script-only modules), all recorded in the profile")


def check_flags(repo: Path, profile: dict, env: dict | None = None) -> tuple[str, str]:
    import pipeline_wiring as W
    env = os.environ if env is None else env
    want = profile.get("flags") or {}
    have = W.vm_lib_flags(repo / "deploy" / "oracle" / "vm_lib.sh")
    have = {k: v for k, v in have.items() if "@" not in v}
    diff = [f"{k}: vm_lib {have.get(k, '<unset>')} != profile {want.get(k, '<undeclared>')}"
            for k in sorted(set(want) | set(have)) if have.get(k) != want.get(k)]
    bad = []
    for name, rule in (profile.get("must_not_set") or {}).items():
        vals = [str(v).lower() for v in (rule.get("values") or [])]
        for where, val in (("vm_lib.sh", have.get(name)), ("this environment", env.get(name))):
            if val is None:
                continue
            if "*" in vals or str(val).lower() in vals:
                bad.append(f"{name}={val} in {where} ({rule.get('why', '')[:80]})")
    over = [f"{k}={env[k]}" for k in sorted(want) if k in env and str(env[k]) != str(want[k])]
    if diff or bad:
        return FAIL, "; ".join((diff + bad)[:6])
    msg = f"vm_lib.sh matches profile {profile.get('profile')!r} ({len(want)} flags)"
    if over:
        return WARN, msg + f"; this environment overrides {len(over)}: {', '.join(over[:5])}"
    return PASS, msg


def check_registry(repo: Path) -> tuple[str, str]:
    import pipeline_wiring as W
    expected = {m for m in W.discovered_scraper_modules(repo / "src")
                if W._has_scraper_class(repo / "src" / Path(*m.split(".")).with_suffix(".py"))}
    code = ("import json,sys,logging\n"
            "logging.disable(logging.CRITICAL)\n"
            f"sys.path.insert(0, {str(repo / 'src')!r})\n"
            "from foreclosure_scraper.scrapers import _registry as R\n"
            "mods=sorted({c.__module__ for c in R.discover()})\n"
            "print(json.dumps(mods))\n")
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return FAIL, "importing the scraper registry timed out"
    try:
        got = set(json.loads((r.stdout or "").strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return FAIL, f"registry import failed: {(r.stderr or '').strip().splitlines()[-1:]}"
    missing = sorted(expected - got)
    if missing:
        return FAIL, (f"{len(missing)} scraper module(s) did not import (the run would silently lose "
                      f"them): {', '.join(m.split('scrapers.')[-1] for m in missing[:8])}")
    return PASS, f"{len(got)} scraper modules import ({len(expected)} expected)"


def check_suite(repo: Path, checkpoint: Path | None) -> tuple[str, str]:
    ck = checkpoint if checkpoint is not None else repo / "data" / "checkpoint"
    out = repo / "data" / "prerun_gate" / "suite_result.json"
    cmd = [sys.executable, str(repo / "scripts" / "audit_suite.py"), "--out", str(out)]
    board_man = repo / "docs" / "board.manifest.json"
    ck_board = Path(ck) / "board.json.gz"
    stale_ck = (checkpoint is None and ck_board.exists() and board_man.exists()
                and ck_board.stat().st_mtime < board_man.stat().st_mtime)
    if ck_board.exists() and not stale_ck:
        cmd += ["--checkpoint", str(ck)]
        try:
            m = json.loads((Path(ck) / "manifest.json").read_text())
            what = f"checkpoint {ck} (phase {m.get('phase')}, saved {m.get('saved_at')})"
        except (OSError, ValueError):
            what = f"checkpoint {ck}"
    else:
        what = ("the published board (the checkpoint here is older than it)" if stale_ck
                else "the published board (no checkpoint here)")
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        return FAIL, f"audit suite on {what} timed out"
    if r.returncode == 2:
        return FAIL, f"audit suite could not read {what}"
    try:
        doc = json.loads(out.read_text())
        bad = doc.get("not_ok") or []
        msg = f"{len(doc.get('checks') or [])} checks on {what}, {doc.get('rows'):,} rows"
    except (OSError, ValueError):
        bad, msg = ["?"], f"audit suite on {what}: no result file"
    if r.returncode != 0:
        return FAIL, msg + f"; NOT ok: {', '.join(bad[:8])}"
    return PASS, msg


# --------------------------------------------------------------------------------------- driver
CHECK_ORDER = ("git", "pin", "pushed", "tests", "ci", "ledgers", "handoff", "repo-size", "manual",
               "memory", "board-loads", "unwired", "frozen-keys", "flags", "registry", "suite")


def run_gate(repo: Path, profile: dict, *, pin: str | None, skip: set[str], checkpoint: Path | None,
             offline: bool = False) -> list[dict]:
    fns: dict[str, Callable[[], tuple[str, str]]] = {
        "git": lambda: check_git(repo, profile),
        "pin": lambda: check_pin(repo, pin),
        "pushed": lambda: check_pushed(repo),
        "tests": lambda: check_tests(repo, profile),
        "ci": lambda: check_ci(repo, pin),
        "ledgers": lambda: check_ledgers(repo, profile),
        "handoff": lambda: check_handoff(repo, profile),
        "repo-size": lambda: check_repo_size(repo, profile),
        "manual": lambda: check_manual(repo, offline),
        "memory": lambda: check_memory(repo, profile),
        "board-loads": lambda: check_board_loads(repo, profile),
        "unwired": lambda: check_unwired(repo, profile),
        "frozen-keys": lambda: check_frozen_keys(repo, profile),
        "flags": lambda: check_flags(repo, profile),
        "registry": lambda: check_registry(repo),
        "suite": lambda: check_suite(repo, checkpoint),
    }
    out = []
    for name in CHECK_ORDER:
        t0 = time.monotonic()
        if name in skip:
            st, why = SKIP, "skipped by --skip"
        else:
            try:
                st, why = fns[name]()
            except Exception as exc:  # noqa: BLE001 - a check that crashes is a failed check
                st, why = FAIL, f"check crashed: {type(exc).__name__}: {exc}"
        out.append({"check": name, "status": st, "why": why, "seconds": round(time.monotonic() - t0, 1)})
        print(f"{st:<5} {name:<12} {why}", flush=True)
    return out


def exit_code(results: list[dict]) -> int:
    if any(r["status"] == FAIL for r in results):
        return 1
    if any(r["status"] == SKIP for r in results):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse a run that is outdated or broken on arrival.")
    ap.add_argument("--pin", default=os.environ.get("RUN_PIN_COMMIT"))
    ap.add_argument("--profile", default=str(PROFILE))
    ap.add_argument("--skip", default="", help=f"comma-separated: {','.join(CHECK_ORDER)}")
    ap.add_argument("--checkpoint", default=None, help="checkpoint dir for the audit suite")
    ap.add_argument("--offline", action="store_true", help="build_owner_manual --check --offline")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    profile = load_profile(Path(a.profile))
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    unknown = skip - set(CHECK_ORDER)
    if unknown:
        print(f"unknown check(s) in --skip: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 64
    print(f"pre-run gate: profile {profile.get('profile')!r} on {platform.node()}, repo {REPO}")
    print("  profile flags: " + " ".join(f"{k}={v}" for k, v in (profile.get("flags") or {}).items()))
    results = run_gate(REPO, profile, pin=a.pin, skip=skip,
                       checkpoint=Path(a.checkpoint) if a.checkpoint else None, offline=a.offline)
    rc = exit_code(results)
    doc = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pin": a.pin,
           "profile": profile.get("profile"), "exit": rc, "results": results}
    out = REPO / "data" / "prerun_gate" / "last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n")
    if a.json:
        print(json.dumps(doc, indent=1))
    print({0: "GATE PASSED", 1: "GATE FAILED: do not start the run", 2: "GATE INCOMPLETE (skipped checks)"}[rc])
    return rc


if __name__ == "__main__":
    sys.exit(main())
