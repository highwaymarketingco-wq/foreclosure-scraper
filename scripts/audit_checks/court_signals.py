"""Court and notice signal invariants (audit 2026-10-09, area court_signals).
docs/audit_2026-10-09/court_signals.md has the measurements (2026-10-08 pre_publish checkpoint).

  court-upset-bid-needs-sale      a row scoring upset_bid has a sale date, or a window a feed
                                  published (raw.upset_bid.source "published") or enrich_upset_bid
                                  derived from a sale date (source_signal). Caught: 1,146 rows (12
                                  HOT, 1,111 WARM) whose window the NC eCourts judgment scraper
                                  opened from a judgment ORDER date (claims of lien, transcripts of
                                  judgment, tax liens; never a sale).
  court-ended-record-not-scored   a row built from an NC Judgment Search hit does not score its
                                  listing-type signal when its own block says the judgment ended
                                  (Canceled, Satisfied, Dismissed, Vacated, ...). Caught: 762 rows
                                  (43 WARM), 760 from the legacy nc_ecourts_judgments lane.
  court-bankruptcy-has-property   a bankruptcy filing row that scores has a parcel or a street
                                  address with a house number. Caught: 751 rows whose
                                  street_address was '<debtor name> — <case>'.
  court-hot-has-property          a HOT row scoring a court/notice signal names a property (a parcel
                                  or a house-numbered address): a lead nobody can call about a
                                  property is not HOT. Caught: 14 HOT rows (13 lis_pendens +
                                  upset_bid from the eCourts stamp).
  court-hot-verified              a HOT row scoring a court/notice signal that a registered
                                  verifier covers (it applies and GOVERNS the signal) carries that
                                  verifier's record (any verdict, not expired): "rechecked at its
                                  primary source before it is called". The detail gives the WARM
                                  share too (not counted as violations).
  court-probate-decedent-binds    a row whose estate notice (raw.probate.decedent) names a property
                                  binds to it by name: the decedent agrees with an owner of record
                                  (surname + first name, middles not in conflict), or the personal
                                  representative does on a property that is not the representative's
                                  own printed address (enrichment_court_owner_verify.estate_binding,
                                  the rule the tail applies). Caught (old token-overlap reading): 36
                                  of 111 rows (NC 21, SC 15).
  court-bankruptcy-filing-binds   a bankruptcy filing row that names a property binds to it by name:
                                  a debtor agrees with an owner of record not copied from the case
                                  name (enrichment_court_owner_verify.bankruptcy_binding).
  court-lis-pendens-is-lis-pendens  no row scores lis_pendens (or is typed lis_pendens) on an NC
                                  Judgment Search claim of lien or transcript of judgment: those are
                                  lien_claim and judgment_lien. Caught: 7,937 of 8,795 NC rows.

No names or addresses leave the process: samples are county:parcel or county:case.
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
COURT = frozenset({"lis_pendens", "foreclosure_sale", "sheriff_sale", "court_sale", "upset_bid",
                   "hoa_sale", "divorce", "divorce_notice", "probate", "probate_notice",
                   "estate_lead", "probate_deed", "bankruptcy", "judgment_lien", "partition",
                   "lien_claim"})
_ENDED = re.compile(r"cancel|satisf|dismiss|vacat|withdr|expire|releas|terminat", re.I)
_NUMBERED = re.compile(r"^\s*\d*[1-9]\d*[A-Za-z]?\s+\S")
_DEATH = re.compile(r"\bHEIRS?\b|\bESTATE\b|\bEST\b|\bDECEASED\b", re.I)
_JUDGMENT_TYPES = frozenset({"lis_pendens", "divorce_notice", "tax_lien", "distressed", "lien_claim"})


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _stack(row: dict) -> tuple[set, str]:
    ds = _raw(row).get("distress_stack")
    ds = ds if isinstance(ds, dict) else {}
    return set(ds.get("signals") or []), str(ds.get("tier") or "")


def _has_property(row: dict) -> bool:
    return bool(row.get("parcel_id")) or bool(_NUMBERED.match(str(row.get("street_address") or "")))


def _ident(row: dict) -> str:
    return f"{row.get('county') or '?'}:{str(row.get('parcel_id') or row.get('case_number') or row.get('source') or '?')[:40]}"


class _Check:
    name = "court-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: dict[str, int] = {}

    def _bad(self, row: dict, why: str = "") -> None:
        self.violations += 1
        if why:
            self.by[why] = self.by.get(why, 0) + 1
        if len(self.samples) < SAMPLE:
            self.samples.append(_ident(row) + (f"({why})" if why else ""))

    def extra(self) -> str:
        return ""

    def finish(self) -> dict:
        parts = [self.describe]
        if self.by:
            parts.append("by: " + ", ".join(f"{k} {v}" for k, v in sorted(self.by.items(), key=lambda kv: -kv[1])[:10]))
        e = self.extra()
        if e:
            parts.append(e)
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": " | ".join(p for p in parts if p)}


class UpsetBidNeedsSale(_Check):
    name = "court-upset-bid-needs-sale"
    describe = "rows scoring upset_bid have a sale date or a published / sale-derived window"

    def feed(self, row: dict) -> None:
        sigs, tier = _stack(row)
        if "upset_bid" not in sigs:
            return
        self.checked += 1
        ub = _raw(row).get("upset_bid")
        ub = ub if isinstance(ub, dict) else {}
        if row.get("sale_date") or ub.get("source") == "published" or ub.get("source_signal"):
            return
        self._bad(row, f"{tier}:{row.get('source')}")


class EndedRecordNotScored(_Check):
    name = "court-ended-record-not-scored"
    describe = "an NC Judgment Search row whose own block says the judgment ended does not score it"

    def feed(self, row: dict) -> None:
        b = _raw(row).get("nc_ecourts")
        if not isinstance(b, dict) or "ecourts" not in str(row.get("source") or ""):
            return
        self.checked += 1
        status = str(b.get("civilJudgmentStatus") or b.get("civil_judgment_status") or "")
        if not _ENDED.search(status):
            return
        sigs, tier = _stack(row)
        scored = sigs & {"lis_pendens", "divorce_notice", "tax_lien", "judgment_lien", "upset_bid",
                         "lien_claim"}
        if scored and str(row.get("listing_type") or "") in _JUDGMENT_TYPES:
            self._bad(row, f"{tier}:{row.get('source')}")


class BankruptcyHasProperty(_Check):
    name = "court-bankruptcy-has-property"
    describe = "a bankruptcy filing row that scores names a parcel or a house-numbered address"

    def feed(self, row: dict) -> None:
        if row.get("listing_type") != "bankruptcy":
            return
        sigs, tier = _stack(row)
        if "bankruptcy" not in sigs:
            return
        self.checked += 1
        if not _has_property(row):
            self._bad(row, tier)


class HotHasProperty(_Check):
    name = "court-hot-has-property"
    describe = "a HOT row scoring a court/notice signal names a property"

    def feed(self, row: dict) -> None:
        sigs, tier = _stack(row)
        if tier != "HOT" or not (sigs & COURT):
            return
        self.checked += 1
        if not _has_property(row):
            self._bad(row, "+".join(sorted(sigs & COURT)))


class HotVerified(_Check):
    name = "court-hot-verified"
    describe = ("a HOT row scoring a court/notice signal a verifier covers carries that verifier's "
                "record (not expired)")

    def __init__(self) -> None:
        super().__init__()
        self.verifiers = None
        self.warm_need = 0
        self.warm_have = 0
        self.now = datetime.now(timezone.utc)

    def _vs(self):
        if self.verifiers is None:
            from foreclosure_scraper.verification.registry import discover
            self.verifiers = [v for v in discover() if not v.wall]
        return self.verifiers

    def feed(self, row: dict) -> None:
        sigs, tier = _stack(row)
        court = sigs & COURT
        if tier not in ("HOT", "WARM") or not court:
            return
        need = []
        for v in self._vs():
            gov = {g.split(":", 1)[0] for g in v.governs}
            if gov & court and v.safe_applies(row):
                need.append(v.signal)
        if not need:
            return
        from foreclosure_scraper.verification.core import active_records
        have = {r.get("signal") for r in active_records(_raw(row), self.now)}
        ok = all(s in have for s in need)
        if tier == "WARM":
            self.warm_need += 1
            self.warm_have += ok
            return
        self.checked += 1
        if not ok:
            self._bad(row, "+".join(sorted(set(need) - have)))

    def extra(self) -> str:
        if not self.warm_need:
            return "WARM: no covered rows"
        return f"WARM covered rows with a record: {self.warm_have} of {self.warm_need}"


class ProbateDecedentBinds(_Check):
    name = "court-probate-decedent-binds"
    describe = "an estate notice on a property binds to it by name (decedent, or representative on title)"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.enrichment_court_owner_verify import estate_binding
        b = estate_binding(row)
        if b is None:
            return
        self.checked += 1
        if b[0] != "bound":
            self._bad(row, f"{row.get('state')}:{b[1]}")


class BankruptcyFilingBinds(_Check):
    name = "court-bankruptcy-filing-binds"
    describe = "a bankruptcy filing on a property binds to it by name (a debtor is an owner of record)"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.enrichment_court_owner_verify import bankruptcy_binding
        b = bankruptcy_binding(row)
        if b is None:
            return
        self.checked += 1
        if b[0] != "bound":
            self._bad(row, b[1])


class LisPendensIsLisPendens(_Check):
    name = "court-lis-pendens-is-lis-pendens"
    describe = "no NC claim of lien or transcript of judgment is typed or scored as a lis pendens"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.enrichment_court_owner_verify import court_lien_kind
        kind = court_lien_kind(row)
        if kind is None:
            return
        self.checked += 1
        sigs, tier = _stack(row)
        if row.get("listing_type") == "lis_pendens" or "lis_pendens" in sigs:
            self._bad(row, f"{kind}:{tier}")


def make_checks() -> list:
    return [UpsetBidNeedsSale(), EndedRecordNotScored(), BankruptcyHasProperty(), HotHasProperty(),
            HotVerified(), ProbateDecedentBinds(), BankruptcyFilingBinds(), LisPendensIsLisPendens()]
