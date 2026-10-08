"""Documents and images invariants (audit 2026-10-09, area documents_images): every notice PDF,
deed image, scanned page and listing photo the board holds a URL for is read, or has a recorded
reason it is not. docs/audit_2026-10-09/documents_images.md has the measurements.

The processed-documents ledger (src/foreclosure_scraper/doc_ledger.py, docs/handoff/documents/)
is loaded once by make_checks(); run the checks where the run's ledger lives (the VM after a
run, or the Mac after `scripts/doc_ledger_tool.py merge`).

  docs-processed-has-ledger-entry   a row carrying a document or image read (raw.doc_ocr,
                                    raw.dot_ocr, raw.vision) whose document / owner search /
                                    image set has no ledger entry: a reader that bypassed the
                                    ledger. 0 allowed.
  docs-per-lead-doc-outcome         a row whose own notice document (doc_inventory.ocr_doc_urls,
                                    not a shared roster) has neither a read on the row nor any
                                    ledger outcome. At most 2% of such rows (a run reads them all
                                    unless its budget ends; the 10/7 board had 178 of 205).
  docs-roster-rows-read             a row with no street address whose roster PDF (a document
                                    more than 3 rows share) has no ledger outcome: the aggregate
                                    pass never reached it (10/7: 6,522 rows, 18 rosters). 0 allowed.
  docs-dot-county-attempted         a county in rod.doc_images.DOC_IMAGE_COUNTIES with eligible
                                    rows and no dot_ocr ledger entry at all (10/7: 9 of 11
                                    counties never searched; the first two took the whole cap).
                                    0 allowed.
  images-hot-warm-graded            a HOT or WARM row with a gradable image (listing / assessor /
                                    street / aerial) and neither a vision report nor a vision
                                    ledger outcome. At most 5% (the pass grades HOT and WARM first;
                                    10/7: 2,770 of 4,996 such rows).
  images-relative-photo-present     a row whose image is a dashboard-hosted relative path
                                    (parcel_photos/...) with no file under docs/ on this machine:
                                    the dashboard shows a broken image and vision cannot read it.
                                    0 allowed (run where the board's docs/ lives).
  docs-ocr-no-shared-stamp          one document read (same owner + address) stamped on more than
                                    3 rows of different parcels: a roster read as one lead's
                                    notice. 0 allowed.
  docs-ocr-binds-to-row             a document read on a row whose case number (else house number)
                                    contradicts the row's own: a sale list read as its first entry
                                    (10/7: 5 rows, 2 with another lead's owner or defendant in a
                                    column). 0 allowed.
  docs-ocr-tax-not-judgment         a document whose figure is a tax balance (amount_kind
                                    tax_owed, or a tax doc_type) copied into judgment_amount (the
                                    1947db81 HOT-gate class). 0 allowed.
  docs-inventory                    counts only, always ok: rows holding each document and image
                                    category, and the backlog with no reader (deed/plat images,
                                    environmental search links, unparsed assessor cards, the
                                    BillTrax JS viewer).
Memory: counters, the per-row doc keys of rows that hold a notice (small: about 13,700 on 10/7),
and at most SAMPLE parcel ids / source slugs per check.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
#: the vision report lives in the lazy-detail sidecar; scripts/audit_suite.py merges it into raw
DETAIL_KEYS = ("vision",)
_MAX_TRACKED = 300_000        # rows with a notice document held for the two-phase checks
SHARE_MAX = 3                 # enrichment_doc_ocr.DOC_OCR_MAX_SHARE


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _pid(row: dict) -> str:
    return f"{row.get('county') or '?'}:{row.get('parcel_id') or row.get('source') or '?'}"


class _Row:
    def __init__(self, row: dict) -> None:
        self.raw = _raw(row)
        self.source_url = row.get("source_url")


class _Check:
    name = "docs-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: Counter = Counter()
        self.extra: list[str] = []

    def _bad(self, why: str, sample: str = "", n: int = 1) -> None:
        self.violations += n
        self.by[why] += n
        if sample and len(self.samples) < SAMPLE:
            self.samples.append(sample)

    def finish(self) -> dict:
        parts = [self.describe]
        if self.by:
            parts.append("by: " + ", ".join(f"{k} {v}" for k, v in self.by.most_common(12)))
        parts += self.extra
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations,
                "detail": " | ".join(p for p in parts if p)}


class _Ledgers:
    """The three lanes, loaded once (empty when a file is missing or unreadable)."""

    def __init__(self) -> None:
        from foreclosure_scraper import doc_ledger as dl
        self.lanes: dict = {}
        self.errors: list[str] = []
        for lane in dl.LANES:
            try:
                self.lanes[lane] = dl.DocLedger.load(lane).rows
            except Exception as exc:  # noqa: BLE001
                self.lanes[lane] = {}
                self.errors.append(f"{lane}: {type(exc).__name__}")
        self.dot_counties = Counter(str(e.get("county") or "?")
                                    for e in self.lanes.get("dot_ocr", {}).values())

    def has(self, lane: str, key: Optional[str]) -> bool:
        return bool(key) and key in self.lanes.get(lane, {})


_LEDGERS: Optional[_Ledgers] = None


def _ledgers() -> _Ledgers:
    global _LEDGERS
    if _LEDGERS is None:
        _LEDGERS = _Ledgers()
    return _LEDGERS


def _vision_keys(row: dict) -> list[str]:
    """The image-set keys a vision read of this row may be recorded under: the row's current
    selection and the set the report says it graded."""
    from foreclosure_scraper import doc_inventory as inv
    from foreclosure_scraper.enrichment_vision import _select_image_urls
    out = []
    urls = _select_image_urls(_Row(row))
    if urls:
        out.append(inv.image_set_key(urls))
    v = _raw(row).get("vision")
    if isinstance(v, dict) and isinstance(v.get("_image_urls"), list) and v["_image_urls"]:
        out.append(inv.image_set_key(v["_image_urls"]))
    return out


class ProcessedHasLedgerEntry(_Check):
    name = "docs-processed-has-ledger-entry"
    describe = "every document / image read on a row has a processed-documents ledger entry"

    def __init__(self) -> None:
        super().__init__()
        self.untraceable = 0

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import doc_inventory as inv
        raw = _raw(row)
        led = _ledgers()
        d = raw.get("doc_ocr")
        if isinstance(d, dict) and d.get("_source") != "ledger":
            self.checked += 1
            urls = list(dict.fromkeys(inv.legacy_ocr_doc_urls(row) + inv.ocr_doc_urls(row)))
            if not urls:
                # the row no longer names the document its read came from (a merge replaced
                # the field): nothing to key a ledger entry by; counted, not a violation
                self.untraceable += 1
            elif not any(led.has("doc_ocr", inv.doc_key(u)) for u in urls):
                self._bad("doc_ocr:" + str(d.get("_source")), f"{row.get('source')}|{_pid(row)}")
        dd = raw.get("dot_ocr")
        if isinstance(dd, dict) and str(row.get("owner_name") or "").strip():
            self.checked += 1
            k = inv.owner_search_key(str(row.get("state") or ""), str(row.get("county") or ""),
                                     str(row.get("owner_name") or ""))
            if not led.has("dot_ocr", k):
                self._bad("dot_ocr", f"{row.get('source')}|{_pid(row)}")
        v = raw.get("vision")
        if isinstance(v, dict) and not v.get("_from_ledger"):
            self.checked += 1
            if not any(led.has("vision", k) for k in _vision_keys(row)):
                self._bad("vision:" + str(row.get("source")), _pid(row))

    def finish(self) -> dict:
        if _ledgers().errors:
            self.extra.append("ledger load errors: " + ", ".join(_ledgers().errors))
        if self.untraceable:
            self.extra.append(f"{self.untraceable} doc_ocr reads on rows that no longer name "
                              f"their document")
        return super().finish()


class _DocRows:
    """Shared two-phase state: for every row holding an OCR document, its primary normalized
    URL hash, ledger key, and whether it was read / has an address."""

    def __init__(self) -> None:
        self.share: Counter = Counter()
        self.rows: list[tuple] = []
        self.dropped = 0
        self._last: Any = None

    def feed(self, row: dict) -> None:
        # both two-phase checks feed this; a row is taken once (the same object, fed twice)
        if row is self._last:
            return
        self._last = row
        from foreclosure_scraper import doc_inventory as inv
        urls = inv.ocr_doc_urls(row)
        if not urls:
            return
        n = hashlib.sha1(inv.normalize_url(urls[0]).encode()).hexdigest()[:16]
        self.share[n] += 1
        if len(self.rows) >= _MAX_TRACKED:
            self.dropped += 1
            return
        raw = _raw(row)
        tier = str((raw.get("distress_stack") or {}).get("tier") or "") \
            if isinstance(raw.get("distress_stack"), dict) else ""
        self.rows.append((n, tuple(inv.doc_key(u) for u in urls), isinstance(raw.get("doc_ocr"), dict),
                          bool(str(row.get("street_address") or "").strip()),
                          str(row.get("source") or "?"), _pid(row), tier))


_DOCROWS: Optional[_DocRows] = None


def _docrows() -> _DocRows:
    global _DOCROWS
    if _DOCROWS is None:
        _DOCROWS = _DocRows()
    return _DOCROWS


class PerLeadDocOutcome(_Check):
    name = "docs-per-lead-doc-outcome"
    describe = "a row's own notice document is read or has a recorded outcome"
    RATE = 0.02

    def feed(self, row: dict) -> None:
        _docrows().feed(row)

    def finish(self) -> dict:
        dr, led = _docrows(), _ledgers()
        for n, keys, read, _addr, src, pid, tier in dr.rows:
            if dr.share[n] > SHARE_MAX:
                continue
            self.checked += 1
            if read or any(led.has("doc_ocr", k) for k in keys):
                continue
            self._bad(src, f"{src}|{pid}|{tier or 'COLD'}")
        self.max_violations = int(self.RATE * self.checked)
        if dr.dropped:
            self.extra.append(f"{dr.dropped} rows past the tracking cap not checked")
        return super().finish()


class RosterRowsRead(_Check):
    name = "docs-roster-rows-read"
    describe = "a row lacking an address whose roster PDF the aggregate pass has a ledger outcome for"

    def feed(self, row: dict) -> None:
        _docrows().feed(row)

    def finish(self) -> dict:
        dr, led = _docrows(), _ledgers()
        rosters_missing: set = set()
        for n, keys, read, addr, src, pid, _tier in dr.rows:
            if dr.share[n] <= SHARE_MAX or addr or read:
                continue
            self.checked += 1
            if led.has("doc_ocr", keys[0]):
                continue
            rosters_missing.add(n)
            self._bad(src, f"{src}|{pid}")
        if rosters_missing:
            self.extra.append(f"{len(rosters_missing)} rosters never read")
        return super().finish()


class DotCountyAttempted(_Check):
    name = "docs-dot-county-attempted"
    describe = "every free deed-image county with eligible rows has dot_ocr ledger entries"

    def __init__(self) -> None:
        super().__init__()
        try:
            from foreclosure_scraper.rod.doc_images import DOC_IMAGE_COUNTIES
            self._counties = set(DOC_IMAGE_COUNTIES)
        except Exception:  # noqa: BLE001
            self._counties = set()
        self.eligible: Counter = Counter()

    def feed(self, row: dict) -> None:
        key = (str(row.get("state") or "").strip(), str(row.get("county") or "").strip())
        if key not in self._counties or not str(row.get("owner_name") or "").strip():
            return
        rod = _raw(row).get("rod")
        if isinstance(rod, dict) and "has_mortgage" in rod and not rod.get("has_mortgage"):
            return
        self.eligible[f"{key[0]}:{key[1]}"] += 1

    def finish(self) -> dict:
        led = _ledgers()
        for county, n in sorted(self.eligible.items()):
            self.checked += 1
            if led.dot_counties.get(county, 0) == 0:
                self._bad(county, f"{county} ({n} eligible)")
        self.extra.append("ledger entries by county: " + ", ".join(
            f"{c} {n}" for c, n in led.dot_counties.most_common(12)))
        return super().finish()


class HotWarmGraded(_Check):
    name = "images-hot-warm-graded"
    describe = "HOT/WARM rows with a gradable image carry a vision report or a vision ledger outcome"
    RATE = 0.05

    def __init__(self) -> None:
        super().__init__()
        self.cold_backlog = 0
        self.cold = 0

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import doc_inventory as inv
        raw = _raw(row)
        cats = {c for c, _ in inv.image_refs(row)}
        if not cats & inv.GRADABLE_IMAGE_CATEGORIES:
            return
        ds = raw.get("distress_stack")
        tier = str(ds.get("tier") or "").upper() if isinstance(ds, dict) else ""
        has = isinstance(raw.get("vision"), dict)
        if tier not in ("HOT", "WARM"):
            self.cold += 1
            if not has:
                self.cold_backlog += 1
            return
        self.checked += 1
        if has or any(_ledgers().has("vision", k) for k in _vision_keys(row)):
            return
        best = ("listing_photo" if "listing_photo" in cats else
                "assessor_photo" if "assessor_photo" in cats else
                "street" if "street" in cats else "aerial")
        self._bad(f"{tier}:{best}", f"{row.get('source')}|{_pid(row)}")

    def finish(self) -> dict:
        self.max_violations = int(self.RATE * self.checked)
        self.extra.append(f"other tiers: {self.cold_backlog} of {self.cold} gradable rows unread "
                          f"(VISION_MAX_LISTINGS bounds a run)")
        return super().finish()


class RelativePhotoPresent(_Check):
    name = "images-relative-photo-present"
    describe = "every dashboard-hosted photo path a row names exists under docs/"

    def __init__(self) -> None:
        super().__init__()
        self._docs = Path(os.environ.get("AUDIT_DOCS_DIR") or (_REPO / "docs"))
        self._seen: dict[str, bool] = {}

    def set_source(self, kind: str, path: Any) -> None:
        """A published board's photos sit in its own docs dir; a checkpoint's in the checkout's."""
        if kind == "board" and not os.environ.get("AUDIT_DOCS_DIR"):
            p = Path(path)
            self._docs = p if p.is_dir() else p.parent

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import doc_inventory as inv
        rel = [u for _c, u in inv.image_refs(row) if not u.startswith(("http://", "https://"))]
        if not rel:
            return
        self.checked += 1
        for u in rel:
            p = u.split("?", 1)[0].lstrip("/")
            ok = self._seen.get(p)
            if ok is None:
                ok = (self._docs / p).is_file() if ".." not in p.split("/") else False
                if len(self._seen) < 200_000:
                    self._seen[p] = ok
            if not ok:
                folder = p.split("/")[1] if p.count("/") > 1 else "parcel_photos"
                self._bad(f"{row.get('source')}:{folder}", p.rsplit("/", 1)[-1][:40])
                break


class OcrNoSharedStamp(_Check):
    name = "docs-ocr-no-shared-stamp"
    describe = "one document read is not stamped on more than 3 rows of different parcels"

    def __init__(self) -> None:
        super().__init__()
        self._sig: dict[str, set] = {}

    def feed(self, row: dict) -> None:
        d = _raw(row).get("doc_ocr")
        if not isinstance(d, dict) or d.get("_source") in ("aggregate_row_match",):
            return
        name = re.sub(r"\W", "", str(d.get("owner_name") or "").lower())
        addr = re.sub(r"\W", "", str(d.get("property_address") or "").lower())
        if not (name or addr):
            return
        self.checked += 1
        sig = hashlib.sha1(f"{name}|{addr}".encode()).hexdigest()[:16]
        s = self._sig.setdefault(sig, set())
        if len(s) <= SHARE_MAX + 1 and len(self._sig) < 200_000:
            s.add(str(row.get("parcel_id") or row.get("street_address") or id(row)))

    def finish(self) -> dict:
        for sig, parcels in self._sig.items():
            if len(parcels) > SHARE_MAX:
                self._bad("shared_read", sig, n=len(parcels))
        return super().finish()


class OcrBindsToRow(_Check):
    name = "docs-ocr-binds-to-row"
    describe = "a document read on a row does not contradict the row's own case / house number"

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.enrichment_doc_ocr import read_conflicts_with_lead
        self._conflict = read_conflicts_with_lead

    def feed(self, row: dict) -> None:
        from types import SimpleNamespace
        d = _raw(row).get("doc_ocr")
        if not isinstance(d, dict) or d.get("_source") in ("aggregate_row_match", "ledger"):
            return
        self.checked += 1
        why = self._conflict(SimpleNamespace(case_number=row.get("case_number"),
                                             street_address=row.get("street_address")), d)
        if why:
            self._bad(f"{row.get('source')}:{why}", _pid(row))


class OcrTaxNotJudgment(_Check):
    name = "docs-ocr-tax-not-judgment"
    describe = "a tax balance read off a document never lands in judgment_amount"

    def feed(self, row: dict) -> None:
        d = _raw(row).get("doc_ocr")
        if not isinstance(d, dict) or d.get("amount") in (None, ""):
            return
        kind = d.get("amount_kind")
        if kind is None:
            kind = "tax_owed" if re.search(r"tax", str(d.get("doc_type") or ""), re.I) else "other"
        if kind != "tax_owed":
            return
        self.checked += 1
        try:
            amt = float(re.sub(r"[^0-9.]", "", str(d.get("amount"))) or 0)
        except ValueError:
            return
        ja = row.get("judgment_amount")
        if isinstance(ja, (int, float)) and amt and abs(float(ja) - amt) < 1:
            self._bad(str(row.get("source")), _pid(row))


class Inventory(_Check):
    name = "docs-inventory"
    describe = "rows holding each document / image category (counts only)"
    max_violations = 10 ** 9

    def __init__(self) -> None:
        super().__init__()
        self.c: Counter = Counter()

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import doc_inventory as inv
        self.checked += 1
        for cat in {c for c, _ in inv.document_refs(row)}:
            self.c["doc:" + cat] += 1
        for cat in {c for c, _ in inv.image_refs(row)}:
            self.c["img:" + cat] += 1
        why = inv.unreadable_notice_reason(row)
        if why and not inv.ocr_doc_urls(row):
            self.c["unreadable:" + why] += 1
        ac = _raw(row).get("assessor_card")
        if isinstance(ac, dict) and ac.get("source_url") and not any(
                v not in (None, "", [], {}) for k, v in ac.items() if k != "source_url"):
            self.c["unparsed:assessor_card"] += 1

    def finish(self) -> dict:
        self.extra.append(", ".join(f"{k} {v}" for k, v in sorted(self.c.items())))
        return super().finish()


def make_checks() -> list:
    global _LEDGERS, _DOCROWS
    _LEDGERS = None
    _DOCROWS = None
    return [ProcessedHasLedgerEntry(), PerLeadDocOutcome(), RosterRowsRead(), DotCountyAttempted(),
            HotWarmGraded(), RelativePhotoPresent(), OcrNoSharedStamp(), OcrBindsToRow(),
            OcrTaxNotJudgment(), Inventory()]
