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

LAYOUTS (2026-10-09). The single file grew with every sweep (tax_lien: 0.7 MB on 10/7, 23 MB
on the evening of 10/8, about 104 MiB at full coverage, past the repo's 95 MiB commit gate), so
a ledger can also live as a directory of shards:

    docs/handoff/verification/<signal>/manifest.json   the commit point: the head fields above
                                                       plus version, buckets, the hash rule and
                                                       one {file, bucket, rows, bytes, sha256}
                                                       per shard
    docs/handoff/verification/<signal>/NNN.json        plain JSON in the single file's own
                                                       layout (one entry per line, the same
                                                       bytes per entry), header kind/signal/
                                                       bucket/buckets, no timestamps

An entry lives in bucket bucket_of(entry key) = first 8 bytes of sha256(key) mod `buckets`, so
a re-check rewrites the one shard that holds the entry and every other shard stays byte for
byte the same (save() writes only the shards whose bytes changed). `buckets` is a power of two
picked for about SHARD_TARGET_BYTES per shard and doubled (each bucket splits in two) when a
shard would pass SHARD_MAX_BYTES (8 MiB). Ledger.load() reads either layout, and both merged
(merge_from) while a ledger is in transition; a new ledger is written as shards; a single-file
ledger stays one until scripts/ledger_migrate.py converts it or it would pass FILE_MAX_BYTES.
A save that writes one layout removes the other only after merging it in. A shard whose sha256
differs from the manifest, an unlisted shard or a key in two shards is an integrity warning:
writers refuse such a ledger (LedgerUnreadable; scripts/ledger_migrate.py --apply re-seals it)
and read-only callers (load_all: the VM apply) use it and report it. publish_ledgers() commits
both layouts' paths, the removed ones included.

RULES.
  * Keyed by verification.core.row_key(); `keys` holds every row_keys() value, and a row is
    found by ANY of them (find()), so a re-check of a row whose parcel was backfilled lands on
    its existing entry, which is re-keyed under the new primary key (never duplicated).
  * A case-scoped verifier (IDENTITY = "case", registry.py) keys its entries "<case id>@<key>"
    for each property key (core.scoped_keys) and stamps `case`: one entry per case and
    property. find() compares parcels on the property part, so a case is never matched to a row
    of a different parcel. migrate_to_case_scope() re-keys entries written before that; an
    entry it cannot give to one case keeps its verdict in `superseded` (no `latest`) with a
    `recheck` reason.
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
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .core import (DECISIVE, VERDICTS, VerificationResult, address_relation, compact, iso_z,
                   parse_ts, property_part, row_keys, row_summary, scoped_keys, split_key,
                   utc_now)

SCHEMA = 1
KIND = "verification_ledger"
REPO = Path(__file__).resolve().parents[3]
LEDGER_DIR = REPO / "docs" / "handoff" / "verification"
HISTORY_MAX = 6

#: Signals whose claim is a fact about the property AT ONE ADDRESS, in a property-keyed ledger
#: (2026-10-06, tax_lien). Two board rows can share a ledger key (one parcel id, or one lien-agent
#: case) and carry DIFFERENT addresses: Rabbit Hill 16 / 18 and Old Fort Rd 2614 / 2610 are one
#: parcel id with a mailing-style address on one row, Pole Creasman 756 / 586 are two parcels
#: that share one lien-agent filing and one copied county roll block. A verdict is about the
#: parcel AND address its row was verified against, so for these signals an entry whose recorded
#: address conflicts with a row's (different house number or street: core.address_relation) is
#: never that row's entry: find() skips it, record() gives the row its own entry (keyed by its
#: address), the sweep queues both rows, apply attaches the entry to the row it was about only.
#: A row or an entry with no house-numbered address is never in conflict.
ADDRESS_SCOPED_SIGNALS = frozenset({"tax_lien"})
#: suffix of the entry that keeps the answer for a row with no house-numbered address on a parcel
#: whose key several address-scoped entries claim (Ledger._own_keys)
_UNADDRESSED = "#unaddressed"


def _entry_address(entry: Any) -> Optional[str]:
    row = entry.get("row") if isinstance(entry, dict) else None
    return row.get("street_address") if isinstance(row, dict) else None


def address_conflict(a: Any, b: Any) -> bool:
    """True when both are house-numbered addresses of different properties."""
    return bool(a) and bool(b) and address_relation(a, b) == "conflict"


def address_slot(address: Any) -> str:
    """The identity of a row's address for queueing: '<house number>|<street name tokens>', or ''
    for an address with no house number. Two spellings of one address share a slot."""
    from .core import address_key
    number, name, _ = address_key(address)
    return f"{number}|{' '.join(sorted(name))}" if number and name else ""


def ledger_dir() -> Path:
    return Path(os.environ.get("VERIFICATION_LEDGER_DIR") or LEDGER_DIR)


def ledger_path(signal: str, directory: Optional[Path] = None) -> Path:
    """The single-file layout's path (see LAYOUTS; shard_dir() is the other one)."""
    return Path(directory or ledger_dir()) / f"{signal}.json"


# -- the sharded layout (LAYOUTS in the module docstring) ---------------------
SHARD_LAYOUT_VERSION = 1
MANIFEST_KIND = "verification_ledger_manifest"
SHARD_KIND = "verification_ledger_shard"
MANIFEST_NAME = "manifest.json"
#: hard cap per shard file. A shard that would pass it doubles `buckets`.
SHARD_MAX_BYTES = int(os.environ.get("VERIFICATION_SHARD_MAX_BYTES") or 8 * 1024 * 1024)
#: what a new sharded ledger aims for per shard when it picks its bucket count
SHARD_TARGET_BYTES = 2 * 1024 * 1024
MAX_BUCKETS = 4096
#: a single-file ledger that would pass this is written as shards instead (the repo's commit gate
#: refuses 95 MiB, scripts/repo_size_check.py fails at 90 MiB)
FILE_MAX_BYTES = int(os.environ.get("VERIFICATION_LEDGER_FILE_MAX_BYTES") or 48 * 1024 * 1024)
HASH_RULE = "int.from_bytes(sha256(entry_key.encode('utf-8')).digest()[:8], 'big') % buckets"
_SHARD_NAME = re.compile(r"^\d{3,4}\.json$")
#: bytes a shard's header and closing lines take (the cap check counts them)
_SHARD_OVERHEAD = 256


def shard_dir(signal: str, directory: Optional[Path] = None) -> Path:
    """The sharded layout's directory, docs/handoff/verification/<signal>/."""
    return Path(directory or ledger_dir()) / signal


def has_shards(d: Path) -> bool:
    d = Path(d)
    return d.is_dir() and ((d / MANIFEST_NAME).exists()
                           or any(_SHARD_NAME.match(p.name) for p in d.iterdir()))


def ledger_layout(signal: str, directory: Optional[Path] = None) -> str:
    """'file', 'shards', 'mixed' (both, mid-transition) or 'none'."""
    f, s = ledger_path(signal, directory).is_file(), has_shards(shard_dir(signal, directory))
    return "mixed" if f and s else "shards" if s else "file" if f else "none"


def ledger_exists(signal: str, directory: Optional[Path] = None) -> bool:
    return ledger_layout(signal, directory) != "none"


def signals_on_disk(directory: Optional[Path] = None) -> list[str]:
    """Every ledger name in the directory, either layout."""
    d = Path(directory or ledger_dir())
    if not d.is_dir():
        return []
    names = {p.stem for p in d.glob("*.json") if not p.name.startswith(".")}
    names |= {p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")
              and has_shards(p)}
    return sorted(names)


def key_hash(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def bucket_of(key: str, buckets: int) -> int:
    """The shard an entry key lives in (HASH_RULE)."""
    return key_hash(key) % buckets


def shard_name(bucket: int) -> str:
    return f"{bucket:03d}.json"


def row_line(key: str, entry: Any) -> str:
    """One entry exactly as both layouts write it (without the separating comma)."""
    return (f"{json.dumps(key)}: "
            f"{json.dumps(entry, sort_keys=True, separators=(',', ':'), default=str)}")


def render(head: dict, lines: list[str]) -> bytes:
    """A ledger file (the single file or a shard): head fields, then '"rows": {', one entry per
    line, sorted by the caller."""
    out = ["{"]
    for k, v in head.items():
        out.append(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, default=str)},")
    out.append('"rows": {')
    last = len(lines) - 1
    out.extend(line + ("," if i < last else "") for i, line in enumerate(lines))
    out.append("}")
    out.append("}")
    return ("\n".join(out) + "\n").encode("utf-8")


def raw_row_lines(data: bytes) -> Optional[list[str]]:
    """The entry lines of a file render() wrote, as they are on disk (separating comma removed),
    or None when the file is not in that layout. What the migration's byte-for-byte check
    compares."""
    lines = data.decode("utf-8").split("\n")
    try:
        i = lines.index('"rows": {')
    except ValueError:
        return None
    body = lines[i + 1:]
    while body and body[-1] in ("", "}"):
        body.pop()
    out = []
    for ln in body:
        if not ln.startswith('"'):
            return None
        out.append(ln[:-1] if ln.endswith(",") else ln)
    return out


def _valid_buckets(x: Any) -> Optional[int]:
    try:
        n = int(x)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= MAX_BUCKETS and n & (n - 1) == 0 else None


def initial_buckets(total_bytes: int) -> int:
    n = 1
    while n < MAX_BUCKETS and total_bytes / n > SHARD_TARGET_BYTES:
        n *= 2
    return n


def read_manifest(d: Path) -> Optional[dict]:
    """The manifest of a shard directory, or None when it is absent or not one."""
    try:
        m = json.loads((Path(d) / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and m.get("kind") == MANIFEST_KIND else None


def _stat_sig(p: Path) -> Optional[tuple]:
    try:
        st = Path(p).stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _same_bytes(p: Path, data: bytes) -> bool:
    try:
        if p.stat().st_size != len(data):
            return False
        return p.read_bytes() == data
    except OSError:
        return False


class LedgerUnreadable(RuntimeError):
    """The file exists but is not a ledger, or a shard directory is incomplete or fails its
    manifest. The sweep refuses to overwrite it (that would lose every entry); the VM apply
    logs it and skips what it cannot read."""


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
        #: the shard layout's bucket count (from the manifest, or the last save)
        self.buckets: Optional[int] = None
        #: {"<signal>/<file>": why} what a non-strict load could not read: save() refuses
        self.problems: dict[str, str] = {}
        #: {"<signal>/<file>": what} integrity findings a recovering load read anyway
        self.warnings: dict[str, str] = {}
        #: on-disk copies merged into this one: str(path) -> _stat_sig at the time
        self._seen: dict[str, Optional[tuple]] = {}
        #: what the last save wrote: layout, shards written / unchanged / removed
        self.last_write: dict[str, Any] = {}

    # -- io ---------------------------------------------------------------
    @classmethod
    def load(cls, signal: str, directory: Optional[Path] = None, *, strict: bool = True,
             recover: bool = False) -> "Ledger":
        """The signal's ledger in `directory`, either layout, both merged when both are there.
        Nothing on disk: an empty ledger whose first save writes shards.

        strict (writers): anything unreadable, or any integrity warning, raises LedgerUnreadable.
        recover=True (scripts/ledger_migrate.py): integrity warnings are read and merged (a re-seal
        follows); unreadable shards still raise. strict=False (read-only callers): what can be
        read is, the rest is in `problems` (the ledger then refuses to save) and `warnings`."""
        d = Path(directory or ledger_dir())
        f, sd = ledger_path(signal, d), shard_dir(signal, d)
        has_f, has_s = f.is_file(), has_shards(sd)
        if not has_f and not has_s:
            return cls(signal, {}, path=sd)
        led: Optional[Ledger] = None
        problems: dict[str, str] = {}
        if has_s:
            try:
                led = cls.load_shards(sd, strict=strict and not recover)
            except LedgerUnreadable as exc:
                if strict:
                    raise
                problems[f"{signal}/{MANIFEST_NAME}"] = str(exc)[:300]
            if led is not None and strict and led.problems:
                raise LedgerUnreadable(f"{sd}: " + "; ".join(
                    f"{k}: {v}" for k, v in sorted(led.problems.items()))[:600])
        if has_f:
            fl: Optional[Ledger] = None
            try:
                fl = cls.load_file(f)
            except LedgerUnreadable as exc:
                if strict:
                    raise
                problems[f.name] = str(exc)[:300]
            if fl is not None and led is None:
                led = fl
            elif fl is not None and led is not None:
                # both layouts (an older writer mid-transition): both readable, so merged, and a
                # writer may go on; the save that follows keeps the shards and removes the file
                newer = str(fl.generated_at or "") > str(led.generated_at or "")
                led.merge_from(fl)
                if newer:
                    led.last_run, led.generated_at = fl.last_run, fl.generated_at
                led.warnings[f.name] = ("single file and shards both present: merged "
                                        "(the next save keeps the shards)")
        if led is None:
            led = cls(signal, {}, path=sd if has_s else f)
        led.problems.update(problems)
        return led

    @classmethod
    def load_file(cls, p: Path) -> "Ledger":
        """The single-file layout; a shard directory (or its manifest) is read as shards."""
        p = Path(p)
        if p.is_dir() or p.name == MANIFEST_NAME:
            return cls.load_shards(p if p.is_dir() else p.parent)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise LedgerUnreadable(f"{p}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(data, dict) or data.get("kind") != KIND \
                or not isinstance(data.get("rows"), dict) or not data.get("signal"):
            raise LedgerUnreadable(f"{p}: not a {KIND} file")
        led = cls(str(data["signal"]), data["rows"], path=p,
                  last_run=data.get("last_run") or {})
        led.generated_at = data.get("generated_at")
        led._seen[str(p)] = _stat_sig(p)
        return led

    @classmethod
    def load_shards(cls, d: Path, *, strict: bool = True) -> "Ledger":
        """A shard directory. Every shard file there is read, listed or not, and checked against
        the manifest. Unreadable (a listed shard missing, not JSON, not a shard of this signal):
        `problems`. Integrity (sha256 or row count differs from the manifest, a shard the
        manifest does not list, a key in two shards, a shard of another bucket count):
        `warnings`, its rows read and merged (merge_from's rules). strict raises on either."""
        d = Path(d)
        mp = d / MANIFEST_NAME
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise LedgerUnreadable(f"{mp}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(m, dict) or m.get("kind") != MANIFEST_KIND or not m.get("signal") \
                or not isinstance(m.get("shards"), list):
            raise LedgerUnreadable(f"{mp}: not a {MANIFEST_KIND}")
        if not isinstance(m.get("version"), int) or m["version"] > SHARD_LAYOUT_VERSION:
            raise LedgerUnreadable(f"{mp}: layout version {m.get('version')!r}; this code reads "
                                   f"up to {SHARD_LAYOUT_VERSION}")
        signal = str(m["signal"])
        led = cls(signal, {}, path=d, last_run=m.get("last_run") or {})
        led.generated_at = m.get("generated_at")
        led.buckets = _valid_buckets(m.get("buckets"))
        listed: dict[str, dict] = {}
        for ent in m["shards"]:
            name = str((ent or {}).get("file") or "") if isinstance(ent, dict) else ""
            if not _SHARD_NAME.match(name):
                led.problems[f"{signal}/{name or '?'}"] = "the manifest lists a non-shard name"
                continue
            listed[name] = ent
        on_disk = {p.name for p in d.iterdir() if _SHARD_NAME.match(p.name)}
        dups = 0
        for name in sorted(set(listed) | on_disk):
            tag, ent = f"{signal}/{name}", listed.get(name)
            try:
                data = (d / name).read_bytes()
            except FileNotFoundError:
                led.problems[tag] = "listed in the manifest, missing on disk"
                continue
            except OSError as exc:
                led.problems[tag] = f"unreadable: {exc}"
                continue
            try:
                doc = json.loads(data)
            except ValueError as exc:
                led.problems[tag] = f"not JSON: {str(exc)[:160]}"
                continue
            if not isinstance(doc, dict) or doc.get("kind") != SHARD_KIND \
                    or doc.get("signal") != signal or not isinstance(doc.get("rows"), dict):
                led.problems[tag] = f"not a {SHARD_KIND} of {signal}"
                continue
            rows = doc["rows"]
            notes = []
            if ent is None:
                notes.append("not listed in the manifest")
            else:
                sha = hashlib.sha256(data).hexdigest()
                if ent.get("sha256") != sha:
                    notes.append(f"sha256 mismatch (manifest {str(ent.get('sha256'))[:12]}, "
                                 f"file {sha[:12]})")
                if ent.get("rows") != len(rows):
                    notes.append(f"{len(rows)} rows, manifest says {ent.get('rows')}")
            if led.buckets and doc.get("buckets") != led.buckets:
                notes.append(f"a shard of {doc.get('buckets')} buckets, manifest {led.buckets}")
            if notes:
                led.warnings[tag] = "; ".join(notes)
            for k, e in rows.items():
                if not isinstance(e, dict):
                    led.problems[tag] = f"entry {k[:60]} is not an object"
                    continue
                if k in led.rows:
                    dups += 1
                    cls._merge_entry(led.rows[k], e)
                else:
                    led.rows[k] = e
        if dups:
            led.warnings[f"{signal}/*"] = f"{dups} key(s) found in two shards: merged"
        if strict and (led.problems or led.warnings):
            raise LedgerUnreadable(f"{d}: " + "; ".join(
                f"{k}: {v}" for k, v in sorted({**led.warnings, **led.problems}.items()))[:600]
                + " (scripts/ledger_migrate.py --apply re-seals a readable one)")
        led._seen[str(d)] = _stat_sig(mp)
        return led

    @property
    def address_scoped(self) -> bool:
        """See ADDRESS_SCOPED_SIGNALS."""
        return self.signal in ADDRESS_SCOPED_SIGNALS

    def counts(self) -> dict:
        c = {"rows": len(self.rows), **{v: 0 for v in VERDICTS}}
        for e in self.rows.values():
            v = (e.get("latest") or {}).get("verdict")
            if v in c:
                c[v] += 1
        return c

    def scrub_notice_text(self) -> dict:
        """Remove foreclosure-notice text from this ledger: it is public, and such text names
        private people (core._NOTICE_TEXT). An entry whose primary key carries it is dropped (the
        next sweep re-creates it under its case or parcel key); from the others the notice-text
        keys and the notice-text street_address are removed. Returns what it removed."""
        from .core import has_notice_text, looks_like_address
        gone = [k for k in self.rows if has_notice_text(k)]
        for k in gone:
            del self.rows[k]
        keys_dropped = addr_dropped = 0
        for e in self.rows.values():
            ks = e.get("keys")
            if isinstance(ks, list):
                kept = [x for x in ks if not has_notice_text(x)]
                keys_dropped += len(ks) - len(kept)
                e["keys"] = kept
            row = e.get("row")
            if isinstance(row, dict) and "street_address" in row and not looks_like_address(row["street_address"]):
                del row["street_address"]
                addr_dropped += 1
        if gone or keys_dropped or addr_dropped:
            self._index = None
        return {"entries": len(gone), "keys": keys_dropped, "street_addresses": addr_dropped}

    def save(self, path: Optional[Path] = None, *, host: Optional[str] = None,
             now: Optional[datetime] = None, scrub: bool = True,
             max_shard_bytes: Optional[int] = None) -> Path:
        """Write the whole ledger, one entry per line, sorted; returns where (the .json file or
        the shard directory). Every file is replaced atomically (temp file + rename; shards
        first, the manifest last); a shard whose bytes did not change is not rewritten.

        `path` given: exactly that layout (".json": the single file, else a shard directory),
        and the other layout is left alone. Otherwise (the writers): the layout this ledger
        was loaded in, shards for a new one, VERIFICATION_LEDGER_LAYOUT=file|shards to force
        one; a single file that would pass FILE_MAX_BYTES, or that has a shard directory
        beside it, becomes shards. The other layout is then merged in (when this copy has not
        seen it as it is now) and removed, so no entry is lost in the switch.

        scrub=False skips scrub_notice_text() (the migration: a pure format change)."""
        if self.problems:
            raise LedgerUnreadable(f"{self.signal}: refusing to write a partly read ledger "
                                   f"({'; '.join(sorted(self.problems))[:300]})")
        explicit = path is not None
        target = Path(path or self.path or shard_dir(self.signal))
        if target.suffix == ".json":
            f, sd = target, target.with_suffix("")
        else:
            sd, f = target, target.with_name(f"{target.name}.json")
        if scrub:
            self.scrub_notice_text()
        lines: Optional[dict[str, str]] = None
        layout = "file" if target.suffix == ".json" else "shards"
        if not explicit:
            env = (os.environ.get("VERIFICATION_LEDGER_LAYOUT") or "auto").strip().lower()
            if env in ("file", "shards"):
                layout = env
            elif layout == "file":
                if has_shards(sd):
                    layout = "shards"
                else:
                    lines = {k: row_line(k, v) for k, v in self.rows.items()}
                    if sum(len(x) + 2 for x in lines.values()) > FILE_MAX_BYTES:
                        layout = "shards"
        other: Optional[Path] = None
        if not explicit:
            if layout == "shards" and f.is_file():
                other = f
            elif layout == "file" and has_shards(sd):
                other = sd
        if other is not None and self._absorb(other):
            lines = None
            if scrub:
                self.scrub_notice_text()
        if lines is None:
            lines = {k: row_line(k, v) for k, v in self.rows.items()}
        head = {"schema": SCHEMA, "kind": KIND, "signal": self.signal,
                "generated_at": iso_z(now or utc_now()), "host": host or socket.gethostname(),
                "counts": self.counts(), "last_run": self.last_run}
        if layout == "file":
            out = self._write_file(f, head, lines)
        else:
            out = self._write_shards(sd, head, lines, max_shard_bytes or SHARD_MAX_BYTES)
        if other is not None:
            if other.is_dir():
                shutil.rmtree(other)
            else:
                other.unlink(missing_ok=True)
            self._seen.pop(str(other), None)
            self.last_write["removed_layout"] = other.name
        self.path = out
        self.generated_at = head["generated_at"]
        return out

    def _absorb(self, p: Path) -> bool:
        """Merge the other layout's copy at `p` into this one unless this copy has already seen
        it as it is now. Raises LedgerUnreadable for a copy that cannot be read: it is about to
        be removed, and an unread copy is never removed."""
        p = Path(p)
        sig = _stat_sig(p / MANIFEST_NAME if p.is_dir() else p)
        if sig is not None and self._seen.get(str(p)) == sig:
            return False
        other = Ledger.load_shards(p) if p.is_dir() else Ledger.load_file(p)
        self.merge_from(other)
        return True

    def _write_file(self, f: Path, head: dict, lines: dict[str, str]) -> Path:
        f.parent.mkdir(parents=True, exist_ok=True)
        data = render(head, [lines[k] for k in sorted(lines)])
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
        self._seen[str(f)] = _stat_sig(f)
        self.last_write = {"layout": "file", "bytes": len(data)}
        return f

    def plan_shards(self, lines: Optional[dict[str, str]] = None, *,
                    max_shard_bytes: Optional[int] = None,
                    buckets: Optional[int] = None) -> tuple[int, dict[int, list[str]]]:
        """(bucket count, {bucket: sorted entry keys}) for the sharded layout: the given or
        current bucket count (initial_buckets() for a first write), doubled while a shard of
        more than one entry would pass the cap."""
        cap = int(max_shard_bytes or SHARD_MAX_BYTES)
        if lines is None:
            lines = {k: row_line(k, v) for k, v in self.rows.items()}
        size = {k: len(v) + 2 for k, v in lines.items()}
        hashes = {k: key_hash(k) for k in lines}
        n = buckets or self.buckets or initial_buckets(sum(size.values()))
        while True:
            groups: dict[int, list[str]] = {}
            used: dict[int, int] = {}
            for k, h in hashes.items():
                b = h % n
                groups.setdefault(b, []).append(k)
                used[b] = used.get(b, 0) + size[k]
            over = any(used[b] + _SHARD_OVERHEAD > cap and len(groups[b]) > 1 for b in groups)
            if not over or n >= MAX_BUCKETS:
                break
            n *= 2
        return n, {b: sorted(ks) for b, ks in sorted(groups.items())}

    def _write_shards(self, sd: Path, head: dict, lines: dict[str, str], cap: int) -> Path:
        sd.mkdir(parents=True, exist_ok=True)
        for leftover in sd.glob(".*.tmp"):          # an interrupted save's temp files
            leftover.unlink(missing_ok=True)
        disk_n = _valid_buckets((read_manifest(sd) or {}).get("buckets"))
        n, groups = self.plan_shards(lines, max_shard_bytes=cap,
                                     buckets=max(self.buckets or 0, disk_n or 0) or None)
        files: dict[str, bytes] = {}
        shards = []
        for b, keys in groups.items():
            data = render({"kind": SHARD_KIND, "schema": SCHEMA, "signal": self.signal,
                           "bucket": b, "buckets": n}, [lines[k] for k in keys])
            name = shard_name(b)
            files[name] = data
            shards.append({"file": name, "bucket": b, "rows": len(keys), "bytes": len(data),
                           "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"kind": MANIFEST_KIND, "version": SHARD_LAYOUT_VERSION,
                    **{k: v for k, v in head.items() if k != "kind"},
                    "hash": HASH_RULE, "buckets": n, "shard_max_bytes": cap,
                    "rows": len(lines), "shards": shards}
        pid = os.getpid()
        pending, unchanged = [], 0
        for name, data in files.items():
            p = sd / name
            if _same_bytes(p, data):
                unchanged += 1
                continue
            tmp = sd / f".{name}.{pid}.tmp"
            tmp.write_bytes(data)
            pending.append((tmp, p))
        mtmp = sd / f".{MANIFEST_NAME}.{pid}.tmp"
        mtmp.write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str) + "\n",
                        encoding="utf-8")
        for tmp, p in pending:
            os.replace(tmp, p)
        os.replace(mtmp, sd / MANIFEST_NAME)
        removed = []
        for p in sorted(sd.iterdir()):
            if _SHARD_NAME.match(p.name) and p.name not in files:
                p.unlink()
                removed.append(p.name)
        self.buckets = n
        self._seen[str(sd)] = _stat_sig(sd / MANIFEST_NAME)
        self.last_write = {"layout": "shards", "buckets": n,
                           "written": [p.name for _, p in pending], "unchanged": unchanged,
                           "removed": removed}
        return sd

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

    def find(self, keys: Iterable[str], address: Any = None
             ) -> tuple[Optional[str], Optional[dict]]:
        """The entry for a row with these keys (row_keys(), or a case-scoped verifier's
        scoped_keys()): the first key exactly one entry claims, unless that entry holds a
        DIFFERENT parcel than the row (two parcels are two properties, whatever address or case
        they share). The parcel comparison reads the property part of a case-scoped key.

        `address` is the row's street address. In an address-scoped ledger
        (ADDRESS_SCOPED_SIGNALS) an entry whose recorded address is a DIFFERENT house-numbered
        address than the row's is skipped as well: it was verified for another address of the
        shared parcel / case, and is not this row's verdict."""
        keys = list(keys)
        mine = _parcels(keys)
        idx = self.index()
        scoped = self.address_scoped and bool(address)
        for k in keys:
            ek = idx.get(k)
            if ek is None:
                continue
            e = self.rows[ek]
            theirs = _parcels((ek, *(e.get("keys") or [])))
            if mine and theirs and not (mine & theirs):
                continue
            if scoped and address_conflict(address, _entry_address(e)):
                continue
            return ek, e
        if self.address_scoped and keys:
            fb = self.rows.get(f"{keys[0]}{_UNADDRESSED}")
            if fb is not None and not address_slot(address):     # only an unaddressed row
                return f"{keys[0]}{_UNADDRESSED}", fb
        return None, None

    def find_row(self, row: Any) -> tuple[Optional[str], Optional[dict]]:
        return self.find(row_keys(row), address=_row_address(row))

    # -- write ------------------------------------------------------------
    def record(self, row: Any, res: VerificationResult, *, ttl_days: Optional[float] = None,
               governs: Iterable[str] = (), now: Optional[datetime] = None,
               keys: Optional[list[str]] = None) -> dict:
        """Merge one answer for `row` (see the module docstring's RULES). Returns the entry."""
        if res.signal != self.signal:
            raise ValueError(f"a {res.signal} result does not belong in the {self.signal} ledger")
        now = now or utc_now()
        keys = list(keys or row_keys(row))
        old_key, entry = self.find(keys, address=_row_address(row))
        if entry is None and self.address_scoped and keys[0] in self.rows:
            keys = self._own_keys(keys)
        if entry is not None and old_key != keys[0] and keys[0] not in self.rows:
            # the row's strongest key changed (e.g. a parcel was backfilled): re-key, keep all
            self.rows[keys[0]] = self.rows.pop(old_key)
            entry = self.rows[keys[0]]
        elif entry is None:
            entry = self.rows.setdefault(keys[0], {})
        self._index = None
        entry["keys"] = sorted(set(entry.get("keys") or []) | set(keys),
                               key=lambda k: (keys.index(k) if k in keys else 99, k))
        case = split_key(keys[0])[0]
        if case:
            entry["case"] = case
        entry.pop("recheck", None)
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

    def _own_keys(self, keys: list[str]) -> list[str]:
        """`keys` reordered so that the row gets an entry of its own. find() found no entry for
        the row although keys[0] is held: by an entry verified for another address of the same
        parcel, or by a key several entries claim. The row's address key leads (one entry per
        address); a row with no address key is never in conflict, so only an ambiguous key can
        reach here for it, and all such rows of a parcel share one fallback entry
        ("<parcel key>#unaddressed", found again by find()) rather than overwrite the holder."""
        for k in keys[1:]:
            if k.startswith("addr:") and k not in self.rows:
                return [k, *[x for x in keys if x != k]]
        return [f"{keys[0]}{_UNADDRESSED}", *keys[1:]]

    def merge_from(self, other: "Ledger") -> "Ledger":
        """Union with another copy of the same signal's ledger (the file on disk vs. this run's
        copy): no entry is lost; per entry, the newer decisive latest wins under record()'s
        rule, histories are unioned, the larger check count is kept."""
        for k, o in other.rows.items():
            b = self.rows.get(k)
            if b is not None and self.address_scoped and \
                    address_conflict(_entry_address(o), _entry_address(b)):
                b = None        # one key, two addresses: the other copy's entry is another row's
            if b is None:
                _, b = self.find([k, *(o.get("keys") or [])], address=_entry_address(o))
                if b is None:
                    nk = k if k not in self.rows else self._own_keys([k, *(o.get("keys") or [])])[0]
                    self.rows[nk] = copy.deepcopy(o)
                    self._index = None
                    continue
            self._merge_entry(b, o)
        self._index = None
        # the on-disk copies the other one read are now merged into this one too (save() then
        # knows it may replace them), and a bucket count never shrinks
        self._seen.update(getattr(other, "_seen", {}) or {})
        if (getattr(other, "buckets", None) or 0) > (self.buckets or 0):
            self.buckets = other.buckets
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


def migrate_to_case_scope(led: "Ledger", verifier: Any, rows: Iterable[Any], *,
                          now: Optional[datetime] = None) -> dict:
    """Re-key, offline, the property-keyed entries a case-scoped verifier (IDENTITY = "case")
    wrote before case scoping existed. Nothing is fetched; no entry is dropped.

    `rows` are the board rows (board_stream). Each row the verifier can name a case for
    (case_identity) is matched to an entry exactly as the apply step matched it (find() on its
    plain row_keys()): those are the rows that entry's verdict was attached to. Per entry:
      scoped                one case among its rows: the entry is that case's (same verdict,
                            stamps, history), re-keyed "<case>@<key>" with its rows' keys;
      attributed            several cases, and the stored evidence names the one the verdict
                            was about (the module's optional case_identity_of_record(), e.g.
                            bankruptcy confirmed/stale publish court + docket): that case keeps
                            it; the other cases have no entry and are due as new;
      scoped_from_evidence  no board row names a case, the evidence does;
      recheck               several cases and the evidence names none of them
                            (case_collision), the evidence names another case than the only
                            one on the board (evidence_names_another_case), or neither the board
                            nor the evidence names one (no_case_on_board): the verdict cannot be
                            given to any one case, so it is moved to `superseded` (no `latest`:
                            the apply step attaches nothing, ledger counts skip it) and
                            `recheck` says why; every case on that property is checked as new.
    Returns a report: counts per outcome and one line per entry ({key, outcome, reason, cases,
    rows, verdict})."""
    now = now or utc_now()
    from_record = getattr(getattr(verifier, "module", None), "case_identity_of_record", None)
    plain = {ek for ek, e in led.rows.items()
             if split_key(ek)[0] is None and isinstance(e.get("latest"), dict)}
    groups: dict[str, dict[str, list[list[str]]]] = {}
    for row in rows:
        cid = verifier.case_of(row)
        if not cid:
            continue
        base = row_keys(row)
        ek, _ = led.find(base)
        if ek in plain:
            groups.setdefault(ek, {}).setdefault(cid, []).append(scoped_keys(base, cid))
    report: dict[str, Any] = {"entries": len(plain), "scoped": 0, "attributed": 0,
                              "scoped_from_evidence": 0, "recheck": 0, "lines": []}
    out = {ek: e for ek, e in led.rows.items() if ek not in plain}
    stamp = iso_z(now)
    for ek in sorted(plain):
        e = copy.deepcopy(led.rows[ek])
        cases = groups.get(ek, {})
        ev_cid = None
        if callable(from_record):
            try:
                ev_cid = from_record(e["latest"])
            except Exception:  # noqa: BLE001
                ev_cid = None
        decided, outcome, reason = None, "recheck", None
        if len(cases) == 1:
            only = next(iter(cases))
            if ev_cid and ev_cid != only:
                reason = "evidence_names_another_case"
            else:
                decided, outcome = only, "scoped"
        elif len(cases) > 1:
            if ev_cid in cases:
                decided, outcome = ev_cid, "attributed"
            else:
                reason = "case_collision"
        elif ev_cid:
            decided, outcome = ev_cid, "scoped_from_evidence"
        else:
            reason = "no_case_on_board"
        n_rows = sum(len(v) for v in cases.values())
        report[outcome] += 1
        report["lines"].append({"key": ek, "outcome": outcome, "reason": reason,
                                "cases": len(cases), "rows": n_rows,
                                "verdict": e["latest"].get("verdict")})
        if decided:
            keys = scoped_keys([ek, *(e.get("keys") or [])], decided)
            for ks in cases.get(decided, []):
                keys.extend(ks)
            e["keys"] = list(dict.fromkeys(keys))
            e["case"] = decided
            e["migrated"] = {"from": "property_key", "how": outcome, "at": stamp,
                             "rows": len(cases.get(decided, []))}
            nk = e["keys"][0]
            if nk in out:
                Ledger._merge_entry(out[nk], e)
            else:
                out[nk] = e
        else:
            e["superseded"] = e.pop("latest")
            e["recheck"] = {"reason": reason, "cases_on_board": len(cases), "rows": n_rows,
                            "marked_at": stamp}
            out[ek] = e
    led.rows = out
    led._index = None
    return report


def _row_address(row: Any) -> Optional[str]:
    v = row.get("street_address") if isinstance(row, dict) else getattr(row, "street_address", None)
    return str(v) if v else None


def _parcels(keys: Iterable[str]) -> set[str]:
    out = set()
    for k in keys:
        p = property_part(k)
        if p.startswith("parcel:"):
            out.add(p)
    return out


def _expired(rec: dict, ttl_days: Optional[float], now: datetime) -> bool:
    age = _age_days(rec.get("checked_at"), now)
    return ttl_days is not None and age is not None and age >= float(ttl_days)


def _better(a: dict, b: dict) -> bool:
    """Should latest `a` replace latest `b`? A decisive answer beats a non-decisive one OF THE
    SAME verifier and VERSION (record()'s rule); otherwise, and among the same class, the newer
    wins. Without the version condition a VERSION bump could never retract a verdict: _save()
    merges the file on disk back in and the old version's decisive answer beat the new
    version's unconfirmed one (bankruptcy_stay v1 -> v2, 2026-10-06)."""
    ad, bd = a.get("verdict") in DECISIVE, b.get("verdict") in DECISIVE
    if ad != bd and (a.get("verifier"), a.get("verifier_version")) == \
            (b.get("verifier"), b.get("verifier_version")):
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


#: the sweep's own unconfirmed reason for a verifier that crashed or ran past the per-row timeout:
#: about the run, never about the row (registry: TRANSIENT_REASONS)
SWEEP_TRANSIENT_REASONS = frozenset({"verifier_error"})


def is_due(entry: Optional[dict], verifier: Any, now: Optional[datetime] = None
           ) -> tuple[bool, str]:
    """(due, why) for a row this verifier applies to. `verifier` is a registry.Verifier.

    An unconfirmed answer whose reason is about the SOURCE's health (the verifier's
    TRANSIENT_REASONS, e.g. tenant_unhealthy; the sweep's verifier_error) is due again after
    TRANSIENT_RETRY_DAYS, not RETRY_DAYS: on 2026-10-08 a one-minute qPayBill outage answered
    about 1,000 rows tenant_unhealthy, and with the 7-day retry none of them could be re-checked
    for a week (why "retry_transient")."""
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
        transient = getattr(verifier, "is_transient", None)
        if callable(transient) and transient(lat):
            return (age >= float(getattr(verifier, "transient_retry_days", 0.25))), "retry_transient"
        return (age >= verifier.retry_days), "retry"
    return (age >= verifier.ttl_days), "ttl"


def load_all(directory: Optional[Path] = None) -> tuple[dict[str, Ledger], dict[str, str]]:
    """Every ledger in the directory, either layout: ({signal: Ledger}, {file: problem}).
    Read-only (the VM apply, gap_matrix): a shard that cannot be read is reported and the rest
    of its ledger still loads (such a ledger refuses to save); integrity warnings (a sha256
    that differs from the manifest, ...) are reported too, prefixed "read anyway:"."""
    d = Path(directory or ledger_dir())
    out: dict[str, Ledger] = {}
    bad: dict[str, str] = {}
    for name in signals_on_disk(d):
        led = Ledger.load(name, d, strict=False)
        bad.update(led.problems)
        bad.update({k: f"read anyway: {v}" for k, v in led.warnings.items()})
        if led.rows or not led.problems:
            out[led.signal] = led
    return out, bad


def check_layout(directory: Optional[Path] = None, *,
                 max_shard_bytes: Optional[int] = None) -> dict[str, dict]:
    """{ledger: report} of every ledger's files without parsing a row: layout, bytes of the
    single file, shard count / largest shard, `issues` (a single file over FILE_MAX_BYTES, which
    save() never writes, a shard over the cap, a shard that fails its manifest, an unlisted
    shard, a missing manifest) and `advice` (a single file over the shard cap: migrate it).
    The audit check and the migration use it."""
    d = Path(directory or ledger_dir())
    cap = int(max_shard_bytes or SHARD_MAX_BYTES)
    out: dict[str, dict] = {}
    for name in signals_on_disk(d):
        f, sd = ledger_path(name, d), shard_dir(name, d)
        rep: dict[str, Any] = {"layout": ledger_layout(name, d), "issues": [], "advice": []}
        if f.is_file():
            rep["file_bytes"] = f.stat().st_size
            if rep["file_bytes"] > FILE_MAX_BYTES:
                rep["issues"].append(f"single file of {rep['file_bytes']:,} bytes "
                                     f"(> {FILE_MAX_BYTES:,}, heading for the 95 MiB commit gate)")
            elif rep["file_bytes"] > cap:
                rep["advice"].append(f"single file of {rep['file_bytes']:,} bytes (> shard cap "
                                     f"{cap:,}): scripts/ledger_migrate.py --apply shards it")
            if rep["layout"] == "mixed":
                rep["advice"].append("both layouts present: the next save (or the migration) "
                                     "merges the file into the shards")
        if has_shards(sd):
            m = read_manifest(sd)
            if m is None:
                rep["issues"].append("shard directory without a readable manifest")
                out[name] = rep
                continue
            listed = {str(s.get("file")): s for s in m.get("shards") or [] if isinstance(s, dict)}
            sizes = {}
            for p in sorted(sd.iterdir()):
                if not _SHARD_NAME.match(p.name):
                    continue
                data = p.read_bytes()
                sizes[p.name] = len(data)
                ent = listed.get(p.name)
                if ent is None:
                    rep["issues"].append(f"{p.name}: not listed in the manifest")
                elif ent.get("sha256") != hashlib.sha256(data).hexdigest():
                    rep["issues"].append(f"{p.name}: sha256 differs from the manifest")
                if len(data) > cap and int((ent or {}).get("rows") or 2) > 1:
                    rep["issues"].append(f"{p.name}: {len(data):,} bytes (> cap {cap:,})")
            for missing in sorted(set(listed) - set(sizes)):
                rep["issues"].append(f"{missing}: listed in the manifest, missing on disk")
            rep.update({"buckets": m.get("buckets"), "shards": len(sizes),
                        "rows": m.get("rows"), "shard_bytes_max": max(sizes.values(), default=0),
                        "shard_bytes_total": sum(sizes.values())})
        out[name] = rep
    return out


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


def ledger_git_paths(paths: Iterable[Path], *, repo: Path = REPO) -> list[str]:
    """The repo-relative paths a commit of these ledgers covers, in both layouts: for a
    <signal>.json or a <signal>/ shard directory, the single file (present, or tracked and
    removed), the manifest and shard files that exist, and every tracked file under the shard
    directory (a shard or the whole directory removed). Never a temp file, never a directory
    pathspec (a concurrent writer's temp file must not ride along)."""
    root = repo.resolve()
    out: list[str] = []
    for p in paths:
        p = Path(p).resolve()
        if p.suffix == ".json":
            f, sd = p, p.with_suffix("")
        else:
            sd, f = p, p.with_name(f"{p.name}.json")
        rf, rsd = str(f.relative_to(root)), str(sd.relative_to(root))
        rc, listed = _git("ls-files", "--", rf, rsd, repo=repo)
        tracked = [ln for ln in listed.splitlines() if ln.strip()] if rc == 0 else []
        if f.exists() or rf in tracked:
            out.append(rf)
        if sd.is_dir():
            out.extend(str(x.relative_to(root)) for x in sorted(sd.iterdir())
                       if x.name == MANIFEST_NAME or _SHARD_NAME.match(x.name))
        out.extend(t for t in tracked if t != rf)
    return list(dict.fromkeys(out))


def commit_ledgers(paths: list[Path], message: str, *, repo: Path = REPO) -> tuple[str, str]:
    """Commit the given ledgers (ledger_git_paths: both layouts, removals included) and nothing
    else, with a pathspec commit under the board lock. No push. Returns (result, detail),
    result one of committed | unchanged | commit_failed | lock_busy."""
    from ..web_artifact import BoardLockBusy, board_lock

    wait = float(os.environ.get("VERIFY_GIT_LOCK_WAIT", "600"))
    try:
        with board_lock(repo, owner="verification_ledger.git", wait=wait, max_runtime=900):
            rels: list[str] = []
            for _ in range(2):      # a writer can remove a shard between the listing and the add
                rels = ledger_git_paths(paths, repo=repo)
                if not rels:
                    return "unchanged", "no ledger files"
                rc, out = _git("add", "-A", "--", *rels, repo=repo)
                if rc == 0:
                    break
            else:
                return "commit_failed", f"git add: {out[-300:]}"
            rc, _ = _git("diff", "--cached", "--quiet", "--", *rels, repo=repo)
            if rc == 0:
                return "unchanged", "ledger unchanged"
            rc, out = _git("commit", "-q", "-m", message, "--", *rels, repo=repo)
            if rc != 0:
                return "commit_failed", out[-400:]
    except BoardLockBusy as exc:
        return "lock_busy", f"git step skipped, board lock busy: {str(exc)[:300]}"
    _, sha = _git("rev-parse", "--short", "HEAD", repo=repo)
    return "committed", f"{sha} ({len(rels)} path(s))"


def publish_ledgers(paths: list[Path], message: str, *, repo: Path = REPO) -> tuple[str, str]:
    """Commit the given ledgers (commit_ledgers: both layouts, removals included, nothing else)
    and push. Returns (result, detail), result one of pushed | unchanged | push_failed |
    commit_failed | skipped.

    HANDOFF_PUSH=0 skips git entirely. The commit and the rebase run under the board lock
    (they rewrite the working tree, the reason scripts/publish_helper.sh re-takes it); the
    fetch and the push run outside it. pull --rebase --autostash before every push."""
    if os.environ.get("HANDOFF_PUSH", "1") == "0":
        return "skipped", "HANDOFF_PUSH=0"
    from ..web_artifact import BoardLockBusy, board_lock

    wait = float(os.environ.get("VERIFY_GIT_LOCK_WAIT", "600"))
    res, detail = commit_ledgers(paths, message, repo=repo)
    if res == "commit_failed":
        return res, detail
    if res == "lock_busy":
        return "push_failed", detail
    committed = res == "committed"

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
