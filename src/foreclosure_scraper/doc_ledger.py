"""The processed-documents ledger: what every document and image read came to, so a run resumes
the backlog instead of redoing the first N, and never re-reads an unchanged document.

One file per lane, docs/handoff/documents/<lane>.json, in the verification ledger's style
(verification/ledger.py): schema 1, one entry per line, keys sorted, atomic write, and a
MERGE-SAFE save (the file on disk is re-read and merged in first, so the VM run, a Mac backfill
and another copy of the same file never lose each other's entries).

Lanes: doc_ocr (notice / roster / deed documents by URL), dot_ocr (one owner's recorded
deed-of-trust search in one county), vision (one image set graded as a whole).

PUBLIC-SAFE. The repo is public. An entry is keyed by a HASH of the document URL (or the image
set, or the owner search) and carries only: category, host, file extension, source slug, county,
timestamps, attempts, outcome, a short reason, the content hash (16 hex), size, page count, the
extractor version, the NAMES of the fields extracted and of the row columns filled, and the
values in PUBLIC_VALUE_KEYS (amounts, dates, case numbers, document type, condition grade).
Never the URL, never notice text, owner names, addresses or phone numbers: those go to the
git-ignored PRIVATE store data/doc_ledger/<lane>.private.json (the data/heirs/ pattern), which
only the machine that read the document has, and which is used to re-apply a result to a row
that lost it without reading the document again.

ENTRY (all optional except outcome/processed_at/extractor_version; the lane is the file's):
  {"category", "host", "ext", "source", "county", "first_seen_at", "processed_at",
   "attempts", "outcome", "reason", "content_sha256", "bytes", "pages", "extractor_version",
   "provider", "fields": [...], "landed": [...], "values": {...}, "rows", "retry_after"}

OUTCOMES. Terminal for an extractor version (never re-read until the version changes):
  extracted, no_fields, aggregate_read, graded, loan_found, not_note, unsupported_format.
Retryable (due again at retry_after; the wait doubles with each attempt, capped at 30 days):
  fetch_failed (2 d), provider_failed (1 d), timeout (1 d), ungraded (30 d), no_document (30 d),
  too_large (30 d).

is_due(): no entry; another extractor version; a retryable outcome past retry_after.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = 1
KIND = "document_ledger"
REPO = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO / "docs" / "handoff" / "documents"
PRIVATE_DIR = REPO / "data" / "doc_ledger"
LANES = ("doc_ocr", "dot_ocr", "vision")

TERMINAL = frozenset({"extracted", "no_fields", "aggregate_read", "graded", "loan_found",
                      "not_note", "unsupported_format"})
RETRY_DAYS = {"fetch_failed": 2.0, "provider_failed": 1.0, "timeout": 1.0, "ungraded": 30.0,
              "no_document": 30.0, "too_large": 30.0}
OUTCOMES = TERMINAL | frozenset(RETRY_DAYS)
MAX_RETRY_DAYS = 30.0

#: the only values the PUBLIC ledger may carry (everything else is dropped by _public_values)
PUBLIC_VALUE_KEYS = frozenset({
    "amount", "sale_date", "case_number", "doc_type", "loan_amount", "recorded_date",
    "book", "page", "instrument_no", "condition_tier", "confidence", "rehab_psf_low",
    "rehab_psf_high", "n_photos", "rows_matched", "rows_filled", "rows_tried",
    "estimated_balance",
})
#: values that go ONLY to the private store
PRIVATE_VALUE_KEYS = frozenset({
    "owner_name", "co_owner_name", "property_address", "city", "state", "zip",
    "ocr_owner", "ocr_property_address", "grantor", "grantee",
})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9 ._:/#()$,\-]{0,48}$")
_PHONE = re.compile(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def enabled() -> bool:
    return os.environ.get("FORECLOSURE_DOC_LEDGER", "1") != "0"


def ledger_dir() -> Path:
    return Path(os.environ.get("DOC_LEDGER_DIR") or LEDGER_DIR)


def private_dir() -> Path:
    return Path(os.environ.get("DOC_LEDGER_PRIVATE_DIR") or PRIVATE_DIR)


def _persistent() -> bool:
    """False under pytest unless a test points DOC_LEDGER_DIR somewhere: a test must never
    write the repo's real ledger."""
    if os.environ.get("DOC_LEDGER_DIR"):
        return True
    return not os.environ.get("PYTEST_CURRENT_TEST")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()[:16]


def _public_values(values: Optional[dict]) -> dict:
    """Keep only PUBLIC_VALUE_KEYS with short, name-free scalar values."""
    out: dict = {}
    for k, v in (values or {}).items():
        if k not in PUBLIC_VALUE_KEYS or v in (None, "", [], {}):
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = round(float(v), 2) if isinstance(v, float) else v
        else:
            s = str(v).strip()
            if _PHONE.search(s) or not _SAFE_TOKEN.match(s):
                continue
            out[k] = s
    return out


def _private_values(values: Optional[dict]) -> dict:
    return {k: v for k, v in (values or {}).items()
            if k in PRIVATE_VALUE_KEYS and v not in (None, "", [], {})}


class LedgerUnreadable(RuntimeError):
    pass


class DocLedger:
    """One lane's ledger. `rows` maps key -> entry (see the module docstring)."""

    def __init__(self, lane: str, rows: Optional[dict] = None, *, path: Optional[Path] = None,
                 persistent: Optional[bool] = None) -> None:
        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r}")
        self.lane = lane
        self.rows: dict[str, dict] = rows if rows is not None else {}
        self.path = path
        self.persistent = _persistent() if persistent is None else persistent
        self.last_run: dict = {}
        self._by_hash: Optional[dict[str, str]] = None
        self.private = PrivateStore(lane, persistent=self.persistent)

    # -- io ---------------------------------------------------------------
    @classmethod
    def load(cls, lane: str, directory: Optional[Path] = None) -> "DocLedger":
        p = Path(directory or ledger_dir()) / f"{lane}.json"
        if not p.exists():
            return cls(lane, {}, path=p)
        return cls.load_file(p, lane)

    @classmethod
    def load_file(cls, p: Path, lane: Optional[str] = None) -> "DocLedger":
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise LedgerUnreadable(f"{p}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not isinstance(data, dict) or data.get("kind") != KIND \
                or not isinstance(data.get("rows"), dict):
            raise LedgerUnreadable(f"{p}: not a {KIND} file")
        led = cls(str(data.get("lane") or lane), data["rows"], path=Path(p))
        led.last_run = data.get("last_run") or {}
        return led

    def counts(self) -> dict:
        c: dict = {"entries": len(self.rows)}
        for e in self.rows.values():
            o = e.get("outcome") or "?"
            c[o] = c.get(o, 0) + 1
        return c

    def save(self, path: Optional[Path] = None, *, now: Optional[datetime] = None) -> Optional[Path]:
        """Merge the file on disk into this copy, then write atomically (one entry per line,
        sorted). A no-op when not persistent (tests)."""
        if not self.persistent:
            return None
        p = Path(path or self.path or (ledger_dir() / f"{self.lane}.json"))
        if p.exists():
            try:
                self.merge_from(DocLedger.load_file(p, self.lane))
            except LedgerUnreadable:
                pass   # an unreadable file is replaced by this copy (it was never valid)
        p.parent.mkdir(parents=True, exist_ok=True)
        head = {"schema": SCHEMA, "kind": KIND, "lane": self.lane,
                "generated_at": _iso(now or _utc_now()), "host": socket.gethostname(),
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
        self.private.save()
        return p

    def merge_from(self, other: "DocLedger") -> "DocLedger":
        """Union: per key the entry with the later processed_at wins; attempts is the larger,
        first_seen_at the earlier. Nothing is dropped."""
        for k, o in other.rows.items():
            b = self.rows.get(k)
            if b is None:
                self.rows[k] = copy.deepcopy(o)
                continue
            newer = str(o.get("processed_at") or "") > str(b.get("processed_at") or "")
            merged = copy.deepcopy(o) if newer else b
            merged["attempts"] = max(int(b.get("attempts") or 0), int(o.get("attempts") or 0))
            firsts = [x for x in (b.get("first_seen_at"), o.get("first_seen_at")) if x]
            if firsts:
                merged["first_seen_at"] = min(firsts)
            self.rows[k] = merged
        self._by_hash = None
        return self

    # -- lookup / decisions -------------------------------------------------
    def get(self, key: str) -> Optional[dict]:
        return self.rows.get(key)

    def is_due(self, key: str, version: str, now: Optional[datetime] = None) -> bool:
        e = self.rows.get(key)
        if not e:
            return True
        if e.get("extractor_version") != version:
            return True
        if e.get("outcome") in TERMINAL:
            return False
        ra = _parse(e.get("retry_after"))
        return ra is None or (now or _utc_now()) >= ra

    def same_content(self, sha: Optional[str], version: str) -> Optional[tuple[str, dict]]:
        """A terminal entry of this version for the same content hash (another URL that serves
        the same bytes): its result can be reused without reading the document again."""
        if not sha:
            return None
        if self._by_hash is None:
            self._by_hash = {}
            for k, e in self.rows.items():
                h = e.get("content_sha256")
                if h and e.get("outcome") in TERMINAL:
                    self._by_hash.setdefault(h, k)
        k = self._by_hash.get(sha)
        if not k:
            return None
        e = self.rows[k]
        return (k, e) if e.get("extractor_version") == version else None

    # -- writes ---------------------------------------------------------------
    def record(self, key: str, *, outcome: str, version: str, category: Optional[str] = None,
               url: Optional[str] = None, source: Optional[str] = None,
               county: Optional[str] = None, content_sha256: Optional[str] = None,
               nbytes: Optional[int] = None, pages: Optional[int] = None,
               provider: Optional[str] = None, fields: Iterable[str] = (),
               landed: Iterable[str] = (), values: Optional[dict] = None,
               rows: Optional[int] = None, reason: Optional[str] = None,
               now: Optional[datetime] = None) -> dict:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        now = now or _utc_now()
        prev = self.rows.get(key) or {}
        attempts = int(prev.get("attempts") or 0) + 1
        e: dict = {"outcome": outcome, "extractor_version": version,
                   "processed_at": _iso(now), "attempts": attempts}
        first = prev.get("first_seen_at") or prev.get("processed_at")
        if first and first != e["processed_at"]:
            e["first_seen_at"] = first      # omitted when it equals processed_at (file size)
        if url:
            from .doc_inventory import url_ext, url_host
            e["host"] = url_host(url)
            ext = url_ext(url)
            if ext:
                e["ext"] = ext
        for f, v in (("category", category), ("source", source), ("county", county),
                     ("content_sha256", content_sha256), ("bytes", nbytes), ("pages", pages),
                     ("provider", provider), ("rows", rows)):
            if v not in (None, ""):
                e[f] = v
        if reason:
            r = re.sub(r"\s+", " ", str(reason))[:80]
            if not _PHONE.search(r):
                e["reason"] = r
        fl = sorted({str(x) for x in fields if x})
        if fl:
            e["fields"] = fl
        ld = sorted({str(x) for x in landed if x})
        if ld:
            e["landed"] = ld
        pv = _public_values(values)
        if pv:
            e["values"] = pv
        if outcome in RETRY_DAYS:
            days = min(MAX_RETRY_DAYS, RETRY_DAYS[outcome] * (2 ** max(0, attempts - 1)))
            e["retry_after"] = _iso(now + timedelta(days=days))
        # a retryable answer never erases an earlier terminal result of the same version
        if outcome not in TERMINAL and prev.get("outcome") in TERMINAL \
                and prev.get("extractor_version") == version:
            keep = copy.deepcopy(prev)
            keep["attempts"] = attempts
            keep["last_attempt"] = {"at": _iso(now), "outcome": outcome}
            self.rows[key] = keep
            return keep
        self.rows[key] = e
        priv = _private_values(values)
        if priv:
            self.private.put(key, priv)
        if content_sha256 and outcome in TERMINAL and self._by_hash is not None:
            self._by_hash.setdefault(content_sha256, key)
        return e


class PrivateStore:
    """data/doc_ledger/<lane>.private.json (git-ignored): key -> names/addresses read from the
    document, so a result can be re-applied without reading the document again."""

    def __init__(self, lane: str, *, persistent: bool = True) -> None:
        self.lane = lane
        self.persistent = persistent
        self._rows: Optional[dict] = None
        self._dirty = False

    @property
    def path(self) -> Path:
        return private_dir() / f"{self.lane}.private.json"

    def _load(self) -> dict:
        if self._rows is None:
            self._rows = {}
            if self.persistent and self.path.exists():
                try:
                    d = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(d, dict):
                        self._rows = d
                except Exception:  # noqa: BLE001
                    self._rows = {}
        return self._rows

    def get(self, key: str) -> dict:
        return dict(self._load().get(key) or {})

    def put(self, key: str, values: dict) -> None:
        self._load()[key] = dict(values)
        self._dirty = True

    def save(self) -> None:
        if not (self.persistent and self._dirty):
            return
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        disk: dict = {}
        if p.exists():
            try:
                disk = json.loads(p.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                disk = {}
        disk.update(self._load())
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(disk, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        self._rows = disk
        self._dirty = False


_CACHE: dict[str, DocLedger] = {}


def get_ledger(lane: str) -> DocLedger:
    """The process's copy of one lane's ledger (loaded once; an unreadable file starts empty
    rather than failing the run)."""
    if not _persistent():
        # under pytest with no DOC_LEDGER_DIR: a fresh, empty, in-memory ledger per call, so
        # one test's outcomes never leak into another and the repo's file is never read
        return DocLedger(lane, {}, persistent=False)
    led = _CACHE.get(lane)
    if led is None:
        try:
            led = DocLedger.load(lane)
        except LedgerUnreadable:
            led = DocLedger(lane, {}, path=ledger_dir() / f"{lane}.json")
        _CACHE[lane] = led
    return led


def reset_cache() -> None:
    _CACHE.clear()
