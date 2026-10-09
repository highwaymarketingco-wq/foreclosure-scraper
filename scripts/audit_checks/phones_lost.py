"""Phones-lost invariants (audit 2026-10-09, area phones_lost; docs/audit_2026-10-09/phones_lost.md).

The reconciled board (pin aa680fba) lost the owner phone on 1,124 rows the live 10/7 board had it
on. Most were removed on purpose (block_binding: another person's phone, a bulk roster's office
number); three defects lost good ones or kept bad ones. One check per defect, each measuring the
property the defect broke on the board itself:

  phones-address-tail-normalizer   a row's address ending in its own city + state (+ zip) with no
                                   comma is not the same house as that address without the tail to
                                   verification.core.address_relation. That conflict made
                                   block_binding remove the row's own LiensNC filing and the
                                   owner's phone with it (other_address).
  phones-filing-line-shared        one LiensNC-filing phone whose filings name 2+ different owners
                                   (none of them on half): the filer's line (a builder, a pool
                                   company), not an owner's (block_binding.filing_line_rows).
  phones-lincoln-akpar-unkeyed     a Lincoln row with no parcel id although the county bulk roll
                                   matched it to a 10-digit PIN (raw['lincoln_bulk']): the row cannot
                                   fold with its PIN copy next run, nor get the PIN-keyed phone
                                   (nc_lincoln_bulk.adopt_pin).
  phones-lincoln-akpar-duplicate   one Lincoln delinquent-tax account (county_id) on a PIN row AND a
                                   parcel-less row: the next run keeps one, and lost the PIN row's
                                   phone with it (parcel_alias.ALIAS_SOURCES).

Memory: counters, a dict of filing phone -> up to 400 (row, owner-token) pairs, two sets of Lincoln
account ids. Samples are parcel ids and counts only.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from foreclosure_scraper import block_binding as bb  # noqa: E402
from foreclosure_scraper.verification.core import address_relation  # noqa: E402

SAMPLE = 8
#: violations allowed. Each is a defect fixed in code (address_key, block_binding, nc_lincoln_bulk +
#: parcel_alias); the 10/7 and aa680fba boards predate the fixes and fail the last three. The
#: normalizer keeps 11 (aa680fba) / 7 (10/7) rows whose street has no suffix ("10 THE SAMPLE
#: CHARLOTTE NC"): the city cannot be told from the street there; 15 leaves room for a few more.
MAX = {
    "phones-address-tail-normalizer": 15,
    "phones-filing-line-shared": 0,
    "phones-lincoln-akpar-unkeyed": 0,
    "phones-lincoln-akpar-duplicate": 0,
}


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _where(row: dict) -> str:
    return f"{row.get('state') or ''}:{row.get('county') or ''}:{row.get('parcel_id') or '-'}"


class _Check:
    name = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.by: Counter = Counter()
        self.samples: list[str] = []

    def _bad(self, where: str, what: str = "", n: int = 1) -> None:
        self.violations += n
        if what:
            self.by[what] += n
        if len(self.samples) < SAMPLE:
            self.samples.append(where)

    def finish(self) -> dict:
        mx = MAX.get(self.name, 0)
        top = ", ".join(f"{k} {v}" for k, v in self.by.most_common(6))
        detail = "none"
        if self.violations:
            detail = (f"{top}; " if top else "") + f"e.g. {'; '.join(self.samples)}"
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": mx, "ok": self.violations <= mx, "detail": detail}


class AddressTailNormalizer(_Check):
    """A row whose street address ends in its own city + state (+ zip) with no comma
    ("900 X RD CHARLOTTE NC 28207", city 'Charlotte'): the address without that tail must be the
    same house to address_relation. It was a conflict, so every record of the row's house written
    without the city (a LiensNC filing, a mailing situs) read as another address."""
    name = "phones-address-tail-normalizer"

    def feed(self, row: dict) -> None:
        addr, city = str(row.get("street_address") or ""), str(row.get("city") or "").strip()
        if not city or "," in addr or not addr[:1].isdigit():
            return
        m = re.search(r"\s" + re.escape(city) + r"\s+(NC|SC)\b[\s\d-]*$", addr, re.I)
        if not m:
            return
        head = addr[:m.start()].strip()
        if len(head.split()) < 3:          # number + street + suffix at least
            return
        self.checked += 1
        if address_relation(addr, head) == "conflict":
            self._bad(_where(row), str(row.get("source") or "-"))


class FilingLineShared(_Check):
    """block_binding.filing_line_rows over the board: the rows the scrub would take a filing phone
    from because the filings carrying it name different owners (the filer's line)."""
    name = "phones-filing-line-shared"
    MAX_MEMBERS = 400

    def __init__(self) -> None:
        super().__init__()
        self.lines: dict[str, list] = {}
        self.where: dict[int, str] = {}
        self.n = 0

    def feed(self, row: dict) -> None:
        i = self.n
        self.n += 1
        op = _raw(row).get("owner_phone")
        v = bb.filing_contact_value("owner_phone", op)
        if not v:
            return
        self.checked += 1
        fo = bb.filing_persons(row, "owner_phone", op)
        e = self.lines.setdefault(v, [])
        if len(e) < self.MAX_MEMBERS:
            e.append((i, bb.name_tokens(fo[0]) if fo else frozenset()))
            if len(self.where) < 20_000:
                self.where[i] = _where(row)

    def finish(self) -> dict:
        for members in self.lines.values():
            if len(members) < 2:
                continue
            for i in sorted(bb.filing_line_rows(members)):
                self._bad(self.where.get(i, "-"), "rows")
        return super().finish()


def _pin(v) -> bool:
    return bool(re.fullmatch(r"\d{10}", re.sub(r"\D", "", str(v or ""))))


class LincolnAkparUnkeyed(_Check):
    name = "phones-lincoln-akpar-unkeyed"

    def feed(self, row: dict) -> None:
        if str(row.get("county") or "").strip().lower() != "lincoln":
            return
        lb = _raw(row).get("lincoln_bulk")
        if not isinstance(lb, dict):
            return
        self.checked += 1
        if not row.get("parcel_id") and _pin(lb.get("parcel_id")):
            self._bad(f"NC:Lincoln:{row.get('source') or '-'}", str(row.get("source") or "-"))


class LincolnAkparDuplicate(_Check):
    name = "phones-lincoln-akpar-duplicate"
    SRC = "counties_nc.nc_county_pdf_delinquent_tax"

    def __init__(self) -> None:
        super().__init__()
        self.with_pin: set[str] = set()
        self.without: set[str] = set()

    def feed(self, row: dict) -> None:
        if row.get("source") != self.SRC or str(row.get("county") or "").strip().lower() != "lincoln":
            return
        blk = _raw(row).get("nc_county_pdf_delinquent_tax")
        cid = str((blk or {}).get("county_id") or "").strip().upper() if isinstance(blk, dict) else ""
        if not cid:
            return
        self.checked += 1
        (self.with_pin if _pin(row.get("parcel_id")) else self.without).add(cid)

    def finish(self) -> dict:
        both = self.with_pin & self.without
        for cid in sorted(both)[:SAMPLE]:
            self.samples.append(f"NC:Lincoln:account {cid}")
        self.violations = len(both)
        return super().finish()


def make_checks() -> list:
    return [AddressTailNormalizer(), FilingLineShared(), LincolnAkparUnkeyed(), LincolnAkparDuplicate()]
