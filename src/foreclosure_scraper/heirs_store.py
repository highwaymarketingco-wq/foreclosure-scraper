"""Private, local-only files for heir work: names never go into the repo or the published board.

The published board (docs/listings_part_*.json.gz) is in a PUBLIC repository and RAW_KEEP decides
what reaches it. Survivor names, personal representatives and heir candidates are private people's
names, so the board carries only counts and flags (raw['heir_candidates_summary']); the names live
here, under data/heirs/ (gitignored: the repo's .gitignore excludes data/), or wherever
HEIRS_PRIVATE_DIR points.

  obituary_store.jsonl.gz   one record per obituary URL: decedent, county, dates, parsed survivors.
                            Feeds hold 10-50 items, so an obituary seen today is gone from its feed
                            next week; the store is what lets a later run still match it.
  heir_candidates.jsonl.gz  the private board for names: one line per lead that has a death signal,
                            with its heir candidates and obituary match. Rewritten every run.
  lookups.json              lead-driven lookups already run (name search on an obituary site), so a
                            run never repeats a search it made recently.

Every write is atomic (temp file + rename). Nothing here touches the network.
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_REPO = Path(__file__).resolve().parents[2]


def private_dir() -> Path:
    return Path(os.environ.get("HEIRS_PRIVATE_DIR") or (_REPO / "data" / "heirs"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_jsonl_gz(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _write_jsonl_gz(path: Path, rows: Iterable[dict]) -> int:
    n = 0
    buf = []
    for r in rows:
        buf.append(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str))
        n += 1
    _atomic_write(path, gzip.compress(("\n".join(buf) + ("\n" if buf else "")).encode("utf-8")))
    return n


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ObituaryStore:
    """url -> obituary record. A newer record for the same URL replaces the older one field by
    field (a feed item seen again later can only add what it now carries)."""

    NAME = "obituary_store.jsonl.gz"

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.path = Path(directory or private_dir()) / self.NAME
        self.records: dict[str, dict] = {}
        self.dirty = False

    def load(self) -> "ObituaryStore":
        for r in _read_jsonl_gz(self.path):
            if r.get("url"):
                self.records[r["url"]] = r
        return self

    def upsert(self, rec: dict) -> bool:
        url = rec.get("url")
        if not url or not rec.get("decedent"):
            return False
        old = self.records.get(url)
        new = dict(old or {})
        for k, v in rec.items():
            if v not in (None, "", [], {}):
                new[k] = v
        new.setdefault("first_stored_utc", utc_now())
        if new != old:
            self.records[url] = new
            self.dirty = True
            return True
        return False

    def save(self) -> int:
        if not self.dirty and self.path.is_file():
            return len(self.records)
        n = _write_jsonl_gz(self.path, (self.records[k] for k in sorted(self.records)))
        self.dirty = False
        return n

    def __len__(self) -> int:
        return len(self.records)

    def values(self):
        return self.records.values()


def write_heir_candidates(rows: Iterable[dict], directory: Optional[Path] = None) -> tuple[Path, int]:
    path = Path(directory or private_dir()) / "heir_candidates.jsonl.gz"
    n = _write_jsonl_gz(path, rows)
    return path, n


def read_heir_candidates(directory: Optional[Path] = None) -> list[dict]:
    return _read_jsonl_gz(Path(directory or private_dir()) / "heir_candidates.jsonl.gz")


class LookupLog:
    """key -> {'at': utc, 'n': results}. Lets a capped, polite lookup lane skip what it searched
    within the last `ttl_days`."""

    NAME = "lookups.json"

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.path = Path(directory or private_dir()) / self.NAME
        self.data: dict[str, dict] = {}

    def load(self) -> "LookupLog":
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}
        return self

    def recent(self, key: str, ttl_days: float = 30.0) -> bool:
        rec = self.data.get(key)
        if not rec:
            return False
        try:
            at = datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return False
        return (datetime.now(timezone.utc) - at).total_seconds() < ttl_days * 86400

    def mark(self, key: str, **info) -> None:
        self.data[key] = {"at": utc_now(), **info}

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self.data, sort_keys=True).encode("utf-8"))
