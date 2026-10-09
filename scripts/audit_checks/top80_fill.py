"""Top-80 fill-group invariants (audit 2026-10-09, build list items 1, 5, 8, 9, 21, 22, 27, 59):
the county parcel-record fill of src/foreclosure_scraper/gis_fill.py. docs/audit_2026-10-09/top80_fill.md has
the measurements.

  top80-fill-deed-ref-shape       every raw['county_deed_ref'] with a book or a page has BOTH, neither is a
                                  placeholder ('0', 'NA'), neither keeps its zero padding, and it names its source
                                  and when it was read (family: deed book/page, items 1, 5, 8). max 0.
  top80-fill-deed-ref-bound       the parcel number a county_deed_ref / county_legal block names is the row's OWN
                                  parcel (equal letter for letter once separators and a '-00' sub-parcel suffix
                                  are ignored): a fill never lands on another parcel's row. max 0.
  top80-fill-legal-shape          every raw['county_legal'] is the assessor's short legal: text of 4 to 200
                                  characters with a letter, not a deed reference ('BK 12 PG 34'), kind
                                  'assessor_short_legal' (family: legal description, items 9, 21). max 0.
  top80-fill-screen-honest        every raw['gis_fill'] is dated, names its source, and its verdicts agree with the
                                  row: 'found' only with the block it wrote (county_deed_ref / county_legal / a
                                  value / an acreage), a 'none' verdict only for a parcel the layer held (found:
                                  true), never both a verdict 'none' and the value (family: all). max 0.
  top80-fill-values-sane          a market / assessed value or an acreage the fill wrote is plausible (value 100 to
                                  500,000,000; acres over 0 to 100,000) (family: assessed value, lot size, items
                                  22, 27). max 0.
  top80-fill-account-join         every raw['parcel_from_account'] row holds a parcel_id in the county layer's shape
                                  and the qPayBill account number it was joined on (family: parcel id, item 59). max 0.
  top80-fill-unscreened           a RATCHET, not a defect: NC / SC rows with a parcel id in a county the fill reads,
                                  and no screen, no deed reference and no legal on them. The fill runs inside a
                                  wall-clock budget and a row keeps its screen between runs, so the first gated
                                  run leaves some; the check fails above UNSCREENED_MAX_SHARE of the eligible rows.

Memory: counters and at most SAMPLE parcel references per check.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
#: the share of eligible rows the first gated run may leave unscreened (lower it after a run has measured)
UNSCREENED_MAX_SHARE = 0.60
_VERDICTS = {"found", "none", "skip", "unknown"}


def _ref(row: dict) -> str:
    return f"{row.get('state')}:{row.get('county')}:{row.get('parcel_id') or '?'}"


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _future(v) -> bool:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t > datetime.now(timezone.utc)


class _Check:
    name = ""
    max_violations = 0

    def __init__(self):
        self.checked = 0
        self.violations = 0
        self.kinds: dict = {}
        self.sample: list = []

    def bad(self, row: dict, kind: str) -> None:
        self.violations += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1
        if len(self.sample) < SAMPLE:
            self.sample.append(f"{_ref(row)} ({kind})")

    def finish(self) -> dict:
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": (f"by kind {self.kinds}; sample {self.sample}" if self.violations else self.extra())}

    def extra(self) -> str:
        return ""


_PLACEHOLDER = {"", "0", "NA", "N/A", "NONE", "NULL", "UNK", "UNKNOWN"}


def _clean_part(v) -> bool:
    s = str(v if v is not None else "").strip().upper()
    return s not in _PLACEHOLDER and not (len(s) > 1 and s.startswith("0")) and bool(re.fullmatch(r"[A-Z0-9]{1,8}", s))


class DeedRefShape(_Check):
    name = "top80-fill-deed-ref-shape"

    def feed(self, row: dict) -> None:
        c = _raw(row).get("county_deed_ref")
        if c is None:
            return
        self.checked += 1
        if not isinstance(c, dict):
            self.bad(row, "not_a_dict")
            return
        book, page = c.get("book"), c.get("page")
        if (book or page) and not (book and page):
            self.bad(row, "book_or_page_missing")
        elif book and not (_clean_part(book) and _clean_part(page)):
            self.bad(row, "placeholder_or_padded")
        elif not c.get("source") or not c.get("fetched_at") or not _iso(c.get("fetched_at")):
            self.bad(row, "no_source_or_date")
        elif c.get("date") and (not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", str(c["date"])) or _future(c["date"])):
            self.bad(row, "bad_deed_date")


def _aliases(pin) -> set[str]:
    from foreclosure_scraper.gis_fill import pin_aliases
    return set(pin_aliases(pin))


class Bound(_Check):
    name = "top80-fill-deed-ref-bound"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        for key in ("county_deed_ref", "county_legal"):
            c = raw.get(key)
            if not isinstance(c, dict) or not c.get("parno"):
                continue
            src = str(c.get("source") or "")
            if src != "nc_onemap" and not src.endswith("_parcel_layer"):
                continue
            self.checked += 1
            if not (_aliases(c["parno"]) & _aliases(row.get("parcel_id"))):
                self.bad(row, f"{key}_other_parcel")


class LegalShape(_Check):
    name = "top80-fill-legal-shape"

    def feed(self, row: dict) -> None:
        c = _raw(row).get("county_legal")
        if c is None:
            return
        self.checked += 1
        t = c.get("text") if isinstance(c, dict) else None
        if not isinstance(t, str) or not (4 <= len(t) <= 200) or not re.search(r"[A-Za-z]", t):
            self.bad(row, "text_shape")
        elif re.match(r"^\s*(BK|BOOK)\s*\w+\s+(PG|PAGE)\s*\w+", t, re.I):
            self.bad(row, "deed_reference_as_legal")
        elif c.get("kind") != "assessor_short_legal":
            self.bad(row, "kind")


class ScreenHonest(_Check):
    name = "top80-fill-screen-honest"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        g = raw.get("gis_fill")
        if g is None:
            return
        self.checked += 1
        if not isinstance(g, dict) or not g.get("checked_at") or not _iso(g.get("checked_at")) \
                or _future(g.get("checked_at")) or not g.get("source"):
            self.bad(row, "undated_or_unsourced")
            return
        for k in ("deed", "legal", "value", "acres"):
            if g.get(k) not in _VERDICTS:
                self.bad(row, f"verdict_{k}")
                return
        found = bool(g.get("found"))
        if not found and any(g.get(k) in ("found", "none") for k in ("deed", "legal", "value", "acres")):
            self.bad(row, "verdict_without_parcel")
            return
        if g.get("deed") == "found" and not raw.get("county_deed_ref"):
            self.bad(row, "deed_found_no_block")
        elif g.get("legal") == "found" and not raw.get("county_legal"):
            self.bad(row, "legal_found_no_block")
        elif g.get("value") == "found" and not (row.get("assessed_value") or row.get("market_value")
                                                or row.get("tax_value")):
            self.bad(row, "value_found_no_value")
        elif g.get("acres") == "found" and not (row.get("acreage") or row.get("lot_size_sqft")):
            self.bad(row, "acres_found_no_acreage")


class ValuesSane(_Check):
    name = "top80-fill-values-sane"

    def feed(self, row: dict) -> None:
        g = _raw(row).get("gis_fill")
        if not isinstance(g, dict):
            return
        self.checked += 1
        for k in ("assessed_value", "market_value"):
            v = row.get(k)
            if isinstance(v, (int, float)) and v and not (100 <= v <= 5e8):
                self.bad(row, f"{k}_implausible")
                return
        a = row.get("acreage")
        if isinstance(a, (int, float)) and a and not (0 < a <= 100000):
            self.bad(row, "acreage_implausible")


class AccountJoin(_Check):
    name = "top80-fill-account-join"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        p = raw.get("parcel_from_account")
        if p is None:
            return
        self.checked += 1
        q = raw.get("qpaybill_roll")
        if not isinstance(p, dict) or not p.get("source") or not p.get("fetched_at"):
            self.bad(row, "no_provenance")
        elif not row.get("parcel_id"):
            self.bad(row, "no_parcel")
        elif not isinstance(q, dict) or not q.get("identification_no"):
            self.bad(row, "no_roll_account")
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{3}\.\d{3}", str(row["parcel_id"]).strip()):
            self.bad(row, "parcel_shape")


class Unscreened(_Check):
    name = "top80-fill-unscreened"

    def __init__(self):
        super().__init__()
        self.eligible = 0

    def feed(self, row: dict) -> None:
        st = str(row.get("state") or "").upper()
        if st not in ("NC", "SC") or not row.get("parcel_id"):
            return
        from foreclosure_scraper import gis_fill as G
        co = G.county_name(type("L", (), {"county": row.get("county")})())
        if st == "SC" and not G.sc_spec(co):
            return
        raw = _raw(row)
        self.eligible += 1
        self.checked += 1
        if not (raw.get("gis_fill") or raw.get("county_deed_ref") or raw.get("county_legal")):
            self.violations += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(_ref(row))

    def finish(self) -> dict:
        limit = int(self.eligible * UNSCREENED_MAX_SHARE)
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": limit, "ok": self.violations <= limit,
                "detail": (f"{self.violations} of {self.eligible} eligible rows unscreened "
                           f"(ratchet {UNSCREENED_MAX_SHARE:.0%}); sample {self.sample}")}


def make_checks() -> list:
    return [DeedRefShape(), Bound(), LegalShape(), ScreenHonest(), ValuesSane(), AccountJoin(), Unscreened()]
