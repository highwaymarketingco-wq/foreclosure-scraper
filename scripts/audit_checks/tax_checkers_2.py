"""County tax checkers (audit 2026-10-09, area tax_checkers_2; docs/audit_2026-10-09/tax_checkers_2.md).

  tax-claim-has-checker     a row that carries a county property-tax claim the call-ready gate waits
                            on (call_ready.property_tax_claim) is taken by a registered tax_lien
                            verifier, or its county is a recorded wall / no-source county (the tax
                            cards of docs/walls_register.json, NO_SOURCE below). A new county with
                            tax rows and no checker shows here before its leads pile up at
                            tax_check_missing. max MAX_UNCHECKED (the small residue measured on the
                            2026-10-07 board: counties with a handful of rows each, listed in the
                            report).
  tax-claim-gate-verifier-agree
                            in a county a tax verifier covers, every row the gate counts as a tax
                            claim is one that verifier takes (2026-10-09: 382 rows in covered
                            counties carried only a tax_owed balance, which no verifier read, and
                            waited at tax_check_missing for good). max 0.

Memory: counters, a per-county cache of "is this county configured" and at most SAMPLE row refs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
#: walls_register cards whose scope lists the counties whose tax site a script may not read
TAX_WALL_CARDS = ("avalon_tax", "nc_tax_walled", "sc_tax_walled", "polk_tax")
#: counties with no per-year tax source at all (walls_register does_not_exist)
NO_SOURCE = frozenset({("NC", "Gates"), ("NC", "Washington"), ("NC", "Tyrrell"), ("NC", "Perquimans")})
#: rows with a tax claim in counties with neither a checker nor a recorded wall: 1,129 on the
#: 2026-10-07 board after this audit's builds (Chowan 873, Beaufort SC 45, Harnett 27, Chester 25,
#: Rowan 22, Edgecombe 14, Person 14, ... a tail of small counties); the check fails when that grows
MAX_UNCHECKED = 1200


def _ref(row: dict) -> str:
    return f"{row.get('state')}:{row.get('county')}:{row.get('parcel_id') or '?'}"


def _walled() -> frozenset:
    try:
        reg = json.loads((_REPO / "docs" / "walls_register.json").read_text())
    except (OSError, ValueError):
        return NO_SOURCE
    out = set(NO_SOURCE)
    for c in reg.get("cards") or []:
        if c.get("id") in TAX_WALL_CARDS:
            out.update((str(s).upper(), str(c2)) for s, c2 in (c.get("scope") or []))
    return frozenset(out)


class _Base:
    name = ""
    max_violations = 0

    def __init__(self):
        from foreclosure_scraper.verification.registry import discover
        self.verifiers = [v for v in discover() if v.signal == "tax_lien"]
        self.checked = 0
        self.violations = 0
        self.by_county: dict = {}
        self.sample: list = []

    def taken(self, row: dict) -> bool:
        return any(v.safe_applies(row) for v in self.verifiers)

    def bad(self, row: dict) -> None:
        self.violations += 1
        k = f"{row.get('state')}:{row.get('county')}"
        self.by_county[k] = self.by_county.get(k, 0) + 1
        if len(self.sample) < SAMPLE:
            self.sample.append(_ref(row))

    def finish(self) -> dict:
        top = dict(sorted(self.by_county.items(), key=lambda kv: -kv[1])[:12])
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": f"by county {top}; sample {self.sample}" if self.violations else ""}


class ClaimHasChecker(_Base):
    name = "tax-claim-has-checker"
    max_violations = MAX_UNCHECKED

    def __init__(self):
        super().__init__()
        self.walled = _walled()

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.call_ready import property_tax_claim
        if not property_tax_claim(row):
            return
        self.checked += 1
        if self.taken(row):
            return
        if (str(row.get("state") or "").upper(), str(row.get("county") or "")) in self.walled:
            return
        self.bad(row)


class GateVerifierAgree(_Base):
    name = "tax-claim-gate-verifier-agree"

    def __init__(self):
        super().__init__()
        self.configured: dict = {}

    def covered_county(self, state: str, county: str) -> bool:
        k = (state, county)
        if k not in self.configured:
            probe = {"state": state, "county": county, "listing_type": "tax_lien", "source": "audit.probe",
                     "parcel_id": "1234567890", "street_address": "1 PROBE ST",
                     "raw": {"tax_owed": {"balance": 100.0, "year": 2025, "kind": "delinquent_tax"}}}
            self.configured[k] = self.taken(probe)
        return self.configured[k]

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.call_ready import property_tax_claim
        if not property_tax_claim(row):
            return
        if not self.covered_county(str(row.get("state") or ""), str(row.get("county") or "")):
            return
        self.checked += 1
        if not self.taken(row):
            self.bad(row)


def make_checks() -> list:
    return [ClaimHasChecker(), GateVerifierAgree()]
