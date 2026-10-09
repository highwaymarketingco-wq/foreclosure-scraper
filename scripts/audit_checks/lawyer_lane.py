"""Lawyer-lane invariants (audit 2026-10-09, area lawyer_lane). docs/audit_2026-10-09/lawyer_lane.md has the
measurements; src/foreclosure_scraper/lawyer_lane.py the items, raw['deed_latest'] and the candidate classes.

  lawyer-lane-c-ready-sourced   no lane C row at a ready tier (A-C) unless every item of the attorney's list
                                is sourced AND dated: the published block holds an ISO date for each, and
                                lawyer_lane.items recomputed from the row agrees. max 0.
  lawyer-deed-latest-bound      every raw['deed_latest'] is bound to the row's own parcel ('book_page' or
                                'sale_date'), names its parcel (equal to the row's), a recording date, a
                                document id, the source URL and when it was read, and is not older than the
                                parcel's last sale on the county record (stale). max 0.
  lawyer-rod-chain-bound        every raw['rod_chain'] with status ok / partial carries a parcel binding (a
                                chain stamped before the binding existed is taken as the lead's chain by
                                anything reading status 'ok'). lawyer_lane.stamp_deed_latest re-binds them
                                with no network; a board that still fails was not passed through it. max 0.
  lawyer-chain-book-page        no chain bound to the parcel whose last deed's book/page differs from the
                                book/page the county parcel record on the row cites (another parcel's
                                deed recorded the same day). max 0.
  lawyer-list-shape             every lane B / C row publishes the nine items, each an ISO date, 'missing',
                                'walled' or 'n/a' (a block from before the 10/9 rule says 'ok': re-stamp).
                                max 0.

Memory: counters and at most SAMPLE parcel references per check.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ref(row: dict) -> str:
    return f"{row.get('state')}:{row.get('county')}:{row.get('parcel_id') or '?'}"


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


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


class LaneCReadySourced(_Check):
    name = "lawyer-lane-c-ready-sourced"

    def __init__(self):
        super().__init__()
        self.ready = 0

    def feed(self, row: dict) -> None:
        blk = _raw(row).get("call_ready")
        if not isinstance(blk, dict) or blk.get("lane") != "C" or blk.get("tier") not in ("A", "B", "C"):
            return
        from foreclosure_scraper import lawyer_lane as LL
        self.checked += 1
        ll = blk.get("lawyer") if isinstance(blk.get("lawyer"), dict) else {}
        undated = [k for k in LL.ITEMS if not _ISO.match(str(ll.get(k) or ""))]
        if undated:
            self.bad(row, "published_item_undated:" + undated[0])
            return
        its = LL.items(row)
        if not LL.complete(its):
            self.bad(row, "recomputed_item_not_sourced:" + next(k for k in LL.ITEMS if its[k]["status"] != "sourced"))
            return
        self.ready += 1

    def extra(self) -> str:
        return f"{self.ready} lane C rows ready, every item sourced and dated"


class DeedLatestBound(_Check):
    name = "lawyer-deed-latest-bound"

    def feed(self, row: dict) -> None:
        dl = _raw(row).get("deed_latest")
        if dl is None:
            return
        from foreclosure_scraper import lawyer_lane as LL
        from foreclosure_scraper.tax_binding import norm_id
        self.checked += 1
        if not isinstance(dl, dict):
            self.bad(row, "not_a_dict")
        elif dl.get("bound") not in LL.BOUND:
            self.bad(row, "not_bound")
        elif norm_id(dl.get("parcel_id")) != norm_id(row.get("parcel_id")):
            self.bad(row, "another_parcel")
        elif not (dl.get("recorded") and dl.get("doc_id") and dl.get("source_url") and dl.get("fetched_at")):
            self.bad(row, "missing_reference")
        elif LL.deed_latest_stale(row, dl):
            self.bad(row, "stale")


class RodChainBound(_Check):
    name = "lawyer-rod-chain-bound"

    def feed(self, row: dict) -> None:
        rc = _raw(row).get("rod_chain")
        if not isinstance(rc, dict) or rc.get("status") not in ("ok", "partial"):
            return
        self.checked += 1
        if rc.get("status") == "ok" and not isinstance(rc.get("binding"), dict):
            self.bad(row, "no_binding")


class ChainBookPage(_Check):
    name = "lawyer-chain-book-page"

    def feed(self, row: dict) -> None:
        rc = _raw(row).get("rod_chain")
        if not isinstance(rc, dict) or (rc.get("binding") or {}).get("status") not in ("book_page", "sale_date"):
            return
        from foreclosure_scraper import lawyer_lane as LL
        ref = LL.county_deed_ref(row)
        ld = rc.get("last_deed") if isinstance(rc.get("last_deed"), dict) else {}
        same = LL.same_book_page(ld.get("book"), ld.get("page"), ref.get("book"), ref.get("page"))
        if same is None:
            return
        self.checked += 1
        if same is False:
            self.bad(row, "bound_to_other_book_page")


class ListShape(_Check):
    name = "lawyer-list-shape"

    def feed(self, row: dict) -> None:
        blk = _raw(row).get("call_ready")
        if not isinstance(blk, dict) or blk.get("lane") not in ("B", "C"):
            return
        from foreclosure_scraper import lawyer_lane as LL
        self.checked += 1
        ll = blk.get("lawyer")
        if not isinstance(ll, dict):
            self.bad(row, "no_lawyer_block")
            return
        for k in LL.ITEMS:
            v = str(ll.get(k) or "")
            if not (_ISO.match(v) or v in ("missing", "walled", "n/a")):
                self.bad(row, f"{k}={v[:12] or 'absent'}")
                return


def make_checks() -> list:
    return [LaneCReadySourced(), DeedLatestBound(), RodChainBound(), ChainBookPage(), ListShape()]
