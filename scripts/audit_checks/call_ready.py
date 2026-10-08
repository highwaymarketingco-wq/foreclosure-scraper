"""Call-ready invariants (audit 2026-10-09, area call_ready). docs/call_ready.md has the gate and the
counts; src/foreclosure_scraper/call_ready.py is the gate itself.

  call-ready-present            every row carries raw['call_ready'] of the current VERSION with a lane in
                                call_ready.LANES (or "") and a tier in TIERS. A board published before
                                the gate was wired fails this (that is the point: wire it).
  call-ready-call-evidence      no CALL tier (A or B) without the evidence the lane requires, read off the
                                row itself, not the block: lane A needs a `confirmed` tax_lien record of
                                the row's own parcel checked within CHECK_MAX_AGE_DAYS of the block's
                                as_of, a balance of at least $25 and a late year, an individual owner,
                                no bankruptcy on record, an owner phone that is not blocked (agent,
                                people-search, do-not-dial) or DNC-registered, and tier A only with a
                                phone tied to the record; lane D needs a sale date ahead or an open
                                upset window on as_of; a worked estate / heirs lead (lanes B and C, tiers
                                A-C) needs a property on the row and a county roll owner who is the dead
                                person. max 0.
  call-ready-no-dead-owner-call no lane A row (any tier) whose owner of record is an estate or carries
                                HEIRS / ESTATE / DECEASED wording, or that carries a confirmed death
                                check: a dead person is never the one we call. max 0.
  call-ready-public-safe        the published block holds no phone-like digit run (7+ digits), no '@',
                                and only the keys call_ready writes. max 0 (the dashboard is public).
  call-ready-recompute          the stored lane and tier equal call_ready(row, as_of) recomputed from the
                                published row: a block computed before a later step changed the row
                                (wired too early, or a key the gate reads missing from RAW_KEEP) shows
                                here. Rows without a block are left to call-ready-present. max 0.

Memory: counters and at most SAMPLE row references (parcel ids or opaque keys) per check.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
ALLOWED_KEYS = frozenset({"v", "lane", "tier", "rank", "reason", "unmet", "checks", "phone", "dnc", "mail",
                          "facts", "lawyer", "as_of", "error"})
#: a US phone number in any of the usual spellings (a date 2026-10-06 or an amount $12,345 is not one)
_PHONE_RUN = re.compile(r"(?<![\d$,])(?:\(\d{3}\)\s?|\d{3}[\s.\-]?)\d{3}[\s.\-]?\d{4}(?![\d,])")


def _ref(row: dict) -> str:
    return f"{row.get('state')}:{row.get('county')}:{row.get('parcel_id') or row.get('case_number') or '?'}"


def _blk(row: dict):
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    b = raw.get("call_ready")
    return b if isinstance(b, dict) else None


def _as_of(blk: dict) -> date:
    try:
        return date.fromisoformat(str(blk.get("as_of"))[:10])
    except ValueError:
        from foreclosure_scraper.call_ready import today_utc
        return today_utc()


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


class Present(_Check):
    name = "call-ready-present"

    def __init__(self):
        super().__init__()
        self.by = {}

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.call_ready import LANES, TIERS, VERSION
        self.checked += 1
        b = _blk(row)
        if b is None:
            self.bad(row, "missing")
            return
        if b.get("v") != VERSION:
            self.bad(row, f"version_{b.get('v')}")
        elif (b.get("lane") or "") not in ("", *LANES) or b.get("tier") not in TIERS:
            self.bad(row, "bad_lane_or_tier")
        k = f"{b.get('lane') or '-'}/{b.get('tier')}"
        self.by[k] = self.by.get(k, 0) + 1

    def extra(self) -> str:
        return f"lane/tier {dict(sorted(self.by.items()))}"


class CallEvidence(_Check):
    name = "call-ready-call-evidence"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import call_ready as CR
        from foreclosure_scraper.enrichment_sc_phone import owner_phone_block_reason
        b = _blk(row)
        if b is None:
            return
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        if b.get("lane") in ("B", "C") and b.get("tier") in ("A", "B", "C"):
            # an estate or heirs lead that is worked: a property, and the county roll names the dead owner
            self.checked += 1
            if not CR.has_property(row):
                self.bad(row, "estate_lead_without_property")
            elif CR.death_fact(row).get("tied") is not True:
                self.bad(row, "decedent_not_tied")
            return
        if b.get("tier") not in ("A", "B") or b.get("lane") not in ("A", "D"):
            return
        self.checked += 1
        today = _as_of(b)
        op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
        if not op.get("phone") or owner_phone_block_reason(op):
            self.bad(row, "phone_blocked_or_absent")
            return
        if CR.dnc_status(raw, op.get("phone")) in ("registered", "do_not_dial", "not_owner_contact"):
            self.bad(row, "dnc_registered")
            return
        if b["tier"] == "A" and b.get("phone") != "tied":
            self.bad(row, "tier_a_phone_not_tied")
            return
        if b["lane"] == "A":
            t = CR.tax_fact(row, today)
            if t.get("status") != "confirmed":
                self.bad(row, f"tax_{t.get('status')}")
            elif CR.owner_kind(row) != "individual":
                self.bad(row, "owner_not_individual")
            elif CR.bankruptcy_fact(row, today).get("active"):
                self.bad(row, "bankruptcy")
        else:
            s = CR.sale_fact(row, today)
            if not s or s.get("window") not in ("sale_ahead", "upset_open"):
                self.bad(row, "sale_not_live")


class NoDeadOwnerCall(_Check):
    name = "call-ready-no-dead-owner-call"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import call_ready as CR
        from foreclosure_scraper.quiet_title.names import roll_markers
        b = _blk(row)
        if b is None or b.get("lane") != "A":
            return
        self.checked += 1
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        if CR.owner_kind(row) == "estate" or roll_markers(row.get("owner_name")):
            self.bad(row, "estate_or_heirs_owner")
            return
        ph = CR.record(raw, "probate_heir")
        if ph and ph.get("verdict") == "confirmed":
            self.bad(row, "death_confirmed")


class PublicSafe(_Check):
    name = "call-ready-public-safe"

    def feed(self, row: dict) -> None:
        import json
        b = _blk(row)
        if b is None:
            return
        self.checked += 1
        extra = set(b) - ALLOWED_KEYS
        if extra:
            self.bad(row, "unknown_keys:" + ",".join(sorted(extra))[:40])
            return
        s = json.dumps({k: v for k, v in b.items() if k not in ("checks", "facts", "as_of", "rank", "v")})
        if "@" in s:
            self.bad(row, "at_sign")
        elif _PHONE_RUN.search(s):
            self.bad(row, "digit_run")


class Recompute(_Check):
    name = "call-ready-recompute"

    def feed(self, row: dict) -> None:
        import copy
        from foreclosure_scraper import call_ready as CR
        b = _blk(row)
        if b is None:
            return
        self.checked += 1
        r = dict(row)
        r["raw"] = {k: v for k, v in (row.get("raw") or {}).items() if k != "call_ready"}
        again = CR.call_ready(copy.copy(r), _as_of(b))
        if (again.get("lane") or "", again.get("tier")) != (b.get("lane") or "", b.get("tier")):
            self.bad(row, f"{b.get('lane') or '-'}/{b.get('tier')}->{again.get('lane') or '-'}/{again.get('tier')}")


def make_checks() -> list:
    return [Present(), CallEvidence(), NoDeadOwnerCall(), PublicSafe(), Recompute()]
