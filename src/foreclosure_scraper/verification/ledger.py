"""The cumulative verification ledger: one file per signal, docs/handoff/verification/<signal>.json.

The Mac (scripts/verification_sweep.py, and the human-assisted lane) writes it and pushes it;
the VM's nightly run reads it (verification.apply) and attaches raw['verification'] to rows.
Same Mac -> VM hand-off as docs/handoff/sos_agent_results.json (sos_agent_handoff.py), sharded
per signal so a day's commit is a small diff and two verifiers of different signals never
touch the same file.

FORMAT (schema 1), one entry per line, keys sorted:

    {"schema": 1, "kind": "verification_ledger", "signal": "tax_lien",
     "generated_at": <UTC ISO>, "host": ..., "counts": {"rows", "confirmed", ...},
     "last_run": {...},
     "rows": {
       "parcel:NC:buncombe:877295969900000": {
         "keys": ["parcel:NC:buncombe:877295969900000", "addr:NC:buncombe:98 turner cove rd"],
         "row": {"county", "state", "parcel_id", "street_address", "listing_type", ...},
         "latest": {signal, verdict, evidence, source, checked_at, verifier_version, verifier},
         "history": [{"verdict", "checked_at", "verifier", "verifier_version"}, ...],
         "last_attempt": {"verdict", "checked_at"},
         "checks": 3, "first_checked_at": ...,
         "ttl_days": 30, "governs": [...]     # the verifier's, at check time
       }, ...}}

RULES.
  * Keyed by verification.core.row_key(); `keys` holds every row_keys() value, and a row is
    found by ANY of them (find()), so a re-check of a row whose parcel was backfilled lands on
    its existing entry, which is re-keyed under the new primary key (never duplicated).
  * Entries are never dropped. Writes are atomic (temp file + rename).
  * A decisive answer (confirmed/refuted/stale) always becomes `latest`. A non-decisive one
    (unconfirmed/wall) becomes `latest` only when there is no decisive latest that is still
    within its TTL and of the current verifier version; otherwise it goes to `history` and
    `last_attempt` only. A flaky page never erases a real verdict.
  * `history` keeps the last HISTORY_MAX earlier answers (verdict and stamps, no evidence).
  * is_due(): never checked; checked by another verifier or another VERSION; a decisive or
    wall answer older than TTL_DAYS; an unconfirmed answer older than RETRY_DAYS.
"""
from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .core import (DECISIVE, VERDICTS, VerificationResult, compact, iso_z, parse_ts,
                   row_keys, row_summary, utc_now)

SCHEMA = 1
KIND = "verification_ledger"
REPO = Path(__file__).resolve().parents[3]
LEDGER_DIR = REPO / "docs" / "handoff" / "verification"
HISTORY_MAX = 6


def ledger_dir() -> Path:
    return Path(os.environ.get("VERIFICATION_LEDGER_DIR") or LEDGER_DIR)


def ledger_path(signal: str, directory: Optional[Path] = None) -> Path:
    return Path(directory or ledger_dir()) / f"{signal}.json"


class LedgerUnreadable(RuntimeError):
    """The file exists but is not a ledger. The sweep refuses to overwrite it (that would lose
    every entry); the VM apply logs it and skips that signal."""


def _age_days(ts: Any, now: datetime) -> Optional[float]:
    t = parse_ts(ts)
    return None if t is None else (now - t).total_seconds() / 86400.0


def _hist(rec: dict) -> dict:
    return {k: rec.get(k) for k in ("verdict", "checked_at", "verifier", "verifier_version")}


class Ledger:
    def __init__(self, signal: str, rows: Optional[dict] = None, *, path: Optional[Path] = None,
                 last_run: Optional[dict] = None) -> None:
        self.signal = signal
        self.rows: dict[str, dict] = rows if rows is not None else {}
        self.path = path
        self.last_run = last_run or {}
        self.generated_at: Optional[str] = None
        self._index: Optional[dict[str, str]] = None

    # -- io ---------------------------------------------------------------
    @classmethod
    def load(cls, signal: str, directory: Optional[Path] = None) -> "Ledger":
        p = ledger_path(signal, directory)
        if not p.exists():
            return cls(signal, {}, path=p)
        return cls.load_file(p)

    @classmethod
    def load_file(cls, p: Path) -> "Ledger":
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise LedgerUnreadable(f"{p}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(data, dict) or data.get("kind") != KIND \
                or not isinstance(data.get("rows"), dict) or not data.get("signal"):
            raise LedgerUnreadable(f"{p}: not a {KIND} file")
        led = cls(str(data["signal"]), data["rows"], path=Path(p),
                  last_run=data.get("last_run") or {})
        led.generated_at = data.get("generated_at")
        return led

    def counts(self) -> dict:
        c = {"rows": len(self.rows), **{v: 0 for v in VERDICTS}}
        for e in self.rows.values():
            v = (e.get("latest") or {}).get("verdict")
            if v in c:
                c[v] += 1
        return c

    def save(self, path: Optional[Path] = None, *, host: Optional[str] = None,
             now: Optional[datetime] = None) -> Path:
        """Atomic write, one entry per line, sorted."""
        p = Path(path or self.path or ledger_path(self.signal))
        p.parent.mkdir(parents=True, exist_ok=True)
        head = {"schema": SCHEMA, "kind": KIND, "signal": self.signal,
                "generated_at": iso_z(now or utc_now()), "host": host or socket.gethostname(),
                "counts": self.counts(), "last_run": self.last_run}
        lines = ["{"]
        for k, v in head.items():
            lines.append(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, default=str)},")
        lines.append('"rows": {')
        keys = sorted(self.rows)
        for i, k in enumerate(keys):
            sep = "," if i < len(keys) - 1 else ""
            lines.append(f"{json.dumps(k)}: "
                         f"{json.dumps(self.rows[k], sort_keys=True, separators=(',', ':'), default=str)}{sep}")
        lines.append("}")
        lines.append("}")
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        self.path = p
        self.generated_at = head["generated_at"]
        return p

    # -- lookup -----------------------------------------------------------
    def index(self) -> dict[str, str]:
        """key -> entry key, for every key exactly ONE entry claims (an ambiguous key cannot
        identify a row: web_artifact._unique_key_map's rule)."""
        if self._index is None:
            owners: dict[str, set[str]] = {}
            for ek, e in self.rows.items():
                for k in {ek, *(e.get("keys") or [])}:
                    owners.setdefault(k, set()).add(ek)
            self._index = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}
        return self._index

    def find(self, keys: Iterable[str]) -> tuple[Optional[str], Optional[dict]]:
        """The entry for a row with these row_keys(): the first key exactly one entry claims,
        unless that entry holds a DIFFERENT parcel than the row (two parcels are two
        properties, whatever address or case they share)."""
        keys = list(keys)
        mine = {k for k in keys if k.startswith("parcel:")}
        idx = self.index()
        for k in keys:
            ek = idx.get(k)
            if ek is None:
                continue
            e = self.rows[ek]
            theirs = {x for x in (ek, *(e.get("keys") or [])) if x.startswith("parcel:")}
            if mine and theirs and not (mine & theirs):
                continue
            return ek, e
        return None, None

    def find_row(self, row: Any) -> tuple[Optional[str], Optional[dict]]:
        return self.find(row_keys(row))

    # -- write ------------------------------------------------------------
    def record(self, row: Any, res: VerificationResult, *, ttl_days: Optional[float] = None,
               governs: Iterable[str] = (), now: Optional[datetime] = None,
               keys: Optional[list[str]] = None) -> dict:
        """Merge one answer for `row` (see the module docstring's RULES). Returns the entry."""
        if res.signal != self.signal:
            raise ValueError(f"a {res.signal} result does not belong in the {self.signal} ledger")
        now = now or utc_now()
        keys = list(keys or row_keys(row))
        old_key, entry = self.find(keys)
        if entry is not None and old_key != keys[0] and keys[0] not in self.rows:
            # the row's strongest key changed (e.g. a parcel was backfilled): re-key, keep all
            self.rows[keys[0]] = self.rows.pop(old_key)
            entry = self.rows[keys[0]]
        elif entry is None:
            entry = self.rows.setdefault(keys[0], {})
        self._index = None
        entry["keys"] = sorted(set(entry.get("keys") or []) | set(keys),
                               key=lambda k: (keys.index(k) if k in keys else 99, k))
        entry["row"] = row_summary(row)
        if ttl_days is not None:
            entry["ttl_days"] = float(ttl_days)
        entry["governs"] = list(governs)
        rec = res.to_dict()
        rec["evidence"] = compact(rec.get("evidence") or {})
        entry["checks"] = int(entry.get("checks") or 0) + 1
        entry.setdefault("first_checked_at", rec["checked_at"])
        entry["last_attempt"] = {"verdict": rec["verdict"], "checked_at": rec["checked_at"]}
        cur = entry.get("latest")
        if cur is None:
            entry["latest"] = rec
            entry.setdefault("history", [])
            return entry
        keep = (rec["verdict"] not in DECISIVE and cur.get("verdict") in DECISIVE
                and cur.get("verifier_version") == rec.get("verifier_version")
                and not _expired(cur, entry.get("ttl_days"), now))
        hist = list(entry.get("history") or [])
        if keep:
            hist.insert(0, _hist(rec))
        else:
            hist.insert(0, _hist(cur))
            entry["latest"] = rec
        entry["history"] = _dedupe_hist(hist)[:HISTORY_MAX]
        return entry

    def merge_from(self, other: "Ledger") -> "Ledger":
        """Union with another copy of the same signal's ledger (the file on disk vs. this run's
        copy): no entry is lost; per entry, the newer decisive latest wins under record()'s
        rule, histories are unioned, the larger check count is kept."""
        for k, o in other.rows.items():
            b = self.rows.get(k)
            if b is None:
                _, b = self.find([k, *(o.get("keys") or [])])
                if b is None:
                    self.rows[k] = copy.deepcopy(o)
                    self._index = None
                    continue
            self._merge_entry(b, o)
        self._index = None
        return self

    @staticmethod
    def _merge_entry(b: dict, o: dict) -> None:
        bl, ol = b.get("latest") or {}, o.get("latest") or {}
        hist = list(b.get("history") or []) + list(o.get("history") or [])
        if ol and (not bl or _better(ol, bl)):
            if bl:
                hist.append(_hist(bl))
            b["latest"] = copy.deepcopy(ol)
            for f in ("ttl_days", "governs", "row"):
                if f in o:
                    b[f] = copy.deepcopy(o[f])
        elif ol and ol.get("checked_at") != bl.get("checked_at"):
            hist.append(_hist(ol))
        b["history"] = _dedupe_hist(sorted(hist, key=lambda h: str(h.get("checked_at") or ""),
                                           reverse=True))[:HISTORY_MAX]
        b["keys"] = list(dict.fromkeys([*(b.get("keys") or []), *(o.get("keys") or [])]))
        b["checks"] = max(int(b.get("checks") or 0), int(o.get("checks") or 0))
        firsts = [x for x in (b.get("first_checked_at"), o.get("first_checked_at")) if x]
        if firsts:
            b["first_checked_at"] = min(firsts)
        la, lo = b.get("last_attempt") or {}, o.get("last_attempt") or {}
        if str(lo.get("checked_at") or "") > str(la.get("checked_at") or ""):
            b["last_attempt"] = copy.deepcopy(lo)


def _expired(rec: dict, ttl_days: Optional[float], now: datetime) -> bool:
    age = _age_days(rec.get("checked_at"), now)
    return ttl_days is not None and age is not None and age >= float(ttl_days)


def _better(a: dict, b: dict) -> bool:
    """Should latest `a` replace latest `b`? A decisive answer beats a non-decisive one; among
    the same class the newer wins."""
    ad, bd = a.get("verdict") in DECISIVE, b.get("verdict") in DECISIVE
    if ad != bd:
        return ad
    return str(a.get("checked_at") or "") > str(b.get("checked_at") or "")


def _dedupe_hist(hist: list[dict]) -> list[dict]:
    seen, out = set(), []
    for h in hist:
        k = (h.get("checked_at"), h.get("verdict"), h.get("verifier"))
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def is_due(entry: Optional[dict], verifier: Any, now: Optional[datetime] = None
           ) -> tuple[bool, str]:
    """(due, why) for a row this verifier applies to. `verifier` is a registry.Verifier."""
    if not entry or not entry.get("latest"):
        return True, "new"
    now = now or utc_now()
    lat = entry["latest"]
    if lat.get("verifier") != verifier.name or lat.get("verifier_version") != verifier.version:
        return True, "version"
    age = _age_days(lat.get("checked_at"), now)
    if age is None:
        return True, "undated"
    if lat.get("verdict") == "unconfirmed":
        return (age >= verifier.retry_days), "retry"
    return (age >= verifier.ttl_days), "ttl"


def load_all(directory: Optional[Path] = None) -> tuple[dict[str, Ledger], dict[str, str]]:
    """Every ledger in the directory: ({signal: Ledger}, {file: error} for unreadable ones)."""
    d = Path(directory or ledger_dir())
    out: dict[str, Ledger] = {}
    bad: dict[str, str] = {}
    if not d.is_dir():
        return out, bad
    for p in sorted(d.glob("*.json")):
        try:
            led = Ledger.load_file(p)
        except LedgerUnreadable as exc:
            bad[p.name] = str(exc)[:300]
            continue
        out[led.signal] = led
    return out, bad


# ---------------------------------------------------------------------------
# git: commit + push ONLY the ledger files (scripts/sos_agent_refresh.py's publish())
# ---------------------------------------------------------------------------

def _git(*args: str, timeout: float = 120, repo: Path = REPO) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} timed out after {int(timeout)}s"


def publish_ledgers(paths: list[Path], message: str, *, repo: Path = REPO) -> tuple[str, str]:
    """Commit the given ledger files (and nothing else) and push. Returns (result, detail),
    result one of pushed | unchanged | push_failed | commit_failed | skipped.

    HANDOFF_PUSH=0 skips git entirely. The commit and the rebase run under the board lock
    (they rewrite the working tree, the reason scripts/publish_helper.sh re-takes it); the
    fetch and the push run outside it. pull --rebase --autostash before every push."""
    if os.environ.get("HANDOFF_PUSH", "1") == "0":
        return "skipped", "HANDOFF_PUSH=0"
    from ..web_artifact import BoardLockBusy, board_lock

    rels = [str(Path(p).resolve().relative_to(repo.resolve())) for p in paths]
    wait = float(os.environ.get("VERIFY_GIT_LOCK_WAIT", "600"))
    committed = False
    try:
        with board_lock(repo, owner="verification_ledger.git", wait=wait, max_runtime=900):
            _git("add", "--", *rels, repo=repo)
            rc, _ = _git("diff", "--cached", "--quiet", "--", *rels, repo=repo)
            if rc != 0:
                rc, out = _git("commit", "-q", "-m", message, "--", *rels, repo=repo)
                if rc != 0:
                    return "commit_failed", out[-400:]
                committed = True
    except BoardLockBusy as exc:
        return "push_failed", f"git step skipped, board lock busy: {str(exc)[:300]}"

    fetch_to = float(os.environ.get("VERIFY_GIT_FETCH_TIMEOUT", "600"))
    _git("fetch", "-q", "origin", "main", timeout=fetch_to, repo=repo)
    rc, ahead = _git("rev-list", "--count", "origin/main..HEAD", repo=repo)
    if not committed and rc == 0 and ahead.strip() == "0":
        return "unchanged", "ledger unchanged and nothing unpushed"
    last = ""
    for attempt in range(3):
        try:
            with board_lock(repo, owner="verification_ledger.rebase", wait=wait, max_runtime=900):
                rc, out = _git("pull", "--rebase", "--autostash", "-q", "origin", "main",
                               timeout=fetch_to, repo=repo)
                if rc != 0:
                    last = f"pull --rebase failed: {out[-300:]}"
                gitdir = repo / ".git"
                if (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists():
                    _git("rebase", "--abort", repo=repo)
        except BoardLockBusy as exc:
            last = f"board lock busy for the rebase: {str(exc)[:200]}"
        rc, out = _git("push", "origin", "main",
                       timeout=float(os.environ.get("VERIFY_GIT_PUSH_TIMEOUT", "300")), repo=repo)
        if rc == 0:
            _, sha = _git("rev-parse", "--short", "HEAD", repo=repo)
            return "pushed", sha
        last = out[-300:]
        time.sleep(float(os.environ.get("VERIFY_GIT_RETRY_SLEEP", "20")) * (attempt + 1))
    return "push_failed", last
