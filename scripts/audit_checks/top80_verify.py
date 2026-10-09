"""Top-80 build list, verification group (audit 2026-10-09, area top80_verify).
docs/audit_2026-10-09/top80_verify.md has the measurements and the per-item verdicts.

  top80v-cube-ledger-names-registered   every verifier signal a cube column names in Spec.ledger
                                  ('a|b' = either) is a signal some registered verifier module
                                  declares. Caught: lt_divorce_notice / lt_lis_pendens / heir_estate
                                  named 'divorce', 'foreclosure_rod' and 'probate_heir' while the
                                  verifiers that cover their NC rows are nc_ecourts_case and
                                  heir_roll: 93 + 65 + 68 NC cells read as 'sourced-not-built'.
  top80v-cube-names-the-verifier   for a hit row of a feed column (or heir_estate) that a registered
                                  verifier covers, the cube column names that verifier's signal in
                                  Spec.ledger. Caught: the same three columns, whose ledger named a
                                  signal that WAS registered (divorce: the SC wall) but not the one
                                  that covers the NC rows, so the cube never saw their verdicts.
  top80v-court-feed-has-verifier  a row an NC Judgment Search scraper typed lis_pendens or
                                  divorce_notice is covered by a registered verifier (nc_ecourts_case).
  top80v-tax-claim-has-verifier   a tax_lien / tax_sale row of a source this group covered (the
                                  lien registries, Rutherford, Iredell, Chowan, Perquimans, Randolph,
                                  Mecklenburg) has a verifier that applies to it, live or a declared
                                  wall: a source added later without one is a new unverifiable block.
  top80v-nc-heir-notice-shape     a row from public_notices.nc_heir_notices is a probate_notice in an
                                  NC county, names a decedent or a parcel, carries a case number or a
                                  parcel or a hearing date, and has raw.heir_naming_publication.
  top80v-quiet-title-flag-has-text  an NC heir-notice row flagged is_quiet_title has the quiet-title
                                  phrase in the notice text it kept (raw.column.text).

Counts and county:source ids only; no names, addresses or notice text leave the process.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SAMPLE = 8
NC_HEIR_SLUG = "public_notices.nc_heir_notices"
COURT_SLUGS = frozenset({"counties_nc.nc_ecourts_lis_pendens", "counties_nc.nc_ecourts_divorce",
                         "nc_ecourts_judgments"})
COURT_TYPES = frozenset({"lis_pendens", "divorce_notice"})
#: (source slug, county or None for every county) pairs whose tax claims this group put a
#: verifier or wall on
TAX_COVERED = (
    ("counties_generic.liensnc", None), ("liensnc", None),
    ("counties_sc.sc_dew_lien_registry", None), ("counties_sc.sc_state_tax_lien", None),
    ("counties_nc.rutherford_tax", None), ("counties_nc.rutherford_wildfire_tax", None),
    ("counties_nc.iredell_delinquent_tax", "Iredell"),
    ("counties_nc.albemarle_observer_tax_lists", "Chowan"),
    ("counties_nc.albemarle_observer_tax_lists", "Perquimans"),
    ("counties_nc.nc_tax_lien_ads", "Randolph"),
    ("counties_nc.mecklenburg_tax_foreclosure", "Mecklenburg"),
)
TAX_TYPES = frozenset({"tax_lien", "tax_sale"})
_QT = re.compile(r"quiet\s+(?:tax\s+)?title", re.I)


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _ident(row: dict) -> str:
    return f"{row.get('county') or '?'}:{str(row.get('parcel_id') or row.get('case_number') or row.get('source') or '?')[:40]}"


def _registry():
    from foreclosure_scraper.verification import registry
    return registry.discover()


class _Check:
    name = "top80v-base"
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

    def feed(self, row: dict) -> None:  # pragma: no cover - overridden
        return None

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


class CubeLedgerNamesRegistered(_Check):
    name = "top80v-cube-ledger-names-registered"
    describe = "every verifier signal a cube column names is declared by a registered verifier"

    def __init__(self) -> None:
        super().__init__()
        self._done = False

    def finish(self) -> dict:
        if not self._done:
            self._done = True
            import gap_matrix as gm
            have = {v.signal for v in _registry()}
            for col, spec in gm.SPECS.items():
                for sig in gm.ledger_signals(spec):
                    self.checked += 1
                    if sig not in have:
                        self.violations += 1
                        self.by[f"{col}:{sig}"] = 1
        return super().finish()


#: the verifier signals that cover the CLAIM of a feed column's listing type (a row can also carry
#: another claim a different verifier covers: the SC divorce wall on a tax_sale row is not this)
COVERS = {
    "lt_divorce_notice": {"nc_ecourts_case", "divorce"},
    "lt_lis_pendens": {"nc_ecourts_case", "foreclosure_rod", "court_wall"},
    "lt_foreclosure_sale": {"foreclosure_rod", "foreclosure_sale_list", "court_wall"},
    "lt_tax_lien": {"tax_lien", "lien_registry_wall", "nc_ecourts_case"},
    "lt_tax_sale": {"tax_lien", "lien_registry_wall", "foreclosure_sale_list"},
    "lt_probate_notice": {"probate_heir", "court_wall"},
    "lt_estate_lead": {"probate_heir", "heir_roll", "court_wall"},
    "heir_estate": {"probate_heir", "heir_roll"},
}


class CubeNamesTheVerifier(_Check):
    name = "top80v-cube-names-the-verifier"
    describe = "the cube column of a row a verifier covers names that verifier's signal"

    def __init__(self) -> None:
        super().__init__()
        self._vs = None
        self._by_lt = None
        self._gm = None

    def _setup(self) -> None:
        import gap_matrix as gm
        self._gm = gm
        self._vs = _registry()
        self._by_lt = {lt: col for col, lt in gm.LISTING_TYPE_COLS.items()}

    def feed(self, row: dict) -> None:
        if self._vs is None:
            self._setup()
        cols = []
        col = self._by_lt.get(str(row.get("listing_type") or ""))
        if col:
            cols.append(col)
        if "heir_estate" in _raw(row):
            cols.append("heir_estate")
        for col in cols:
            named = set(self._gm.ledger_signals(self._gm.SPECS[col]))
            if not named or col not in COVERS:
                continue
            applying = {v.signal for v in self._vs if _safe_applies(v, row)} & COVERS[col]
            if not applying:
                continue
            self.checked += 1
            if not (applying & named):
                self._bad(row, f"{col}:{'+'.join(sorted(applying))}")


def _safe_applies(v, row: dict) -> bool:
    try:
        return bool(v.applies(row))
    except Exception:  # noqa: BLE001 - a verifier that chokes on a row covers nothing
        return False


class CourtFeedHasVerifier(_Check):
    name = "top80v-court-feed-has-verifier"
    describe = "a row an NC Judgment Search scraper typed lis_pendens / divorce_notice has a verifier"

    def __init__(self) -> None:
        super().__init__()
        self._vs = None

    def feed(self, row: dict) -> None:
        if row.get("source") not in COURT_SLUGS or row.get("listing_type") not in COURT_TYPES:
            return
        if self._vs is None:
            self._vs = [v for v in _registry() if v.signal == "nc_ecourts_case"]
        self.checked += 1
        if not any(v.applies(row) for v in self._vs):
            self._bad(row, f"{row.get('listing_type')}:{row.get('county')}")


class TaxClaimHasVerifier(_Check):
    name = "top80v-tax-claim-has-verifier"
    describe = "a tax_lien / tax_sale row of a source this group covered has a live verifier or a declared wall"

    def __init__(self) -> None:
        super().__init__()
        self._vs = None
        self._scope = {}
        for slug, county in TAX_COVERED:
            self._scope.setdefault(slug, set()).add(county)

    def feed(self, row: dict) -> None:
        counties = self._scope.get(row.get("source"))
        if counties is None or row.get("listing_type") not in TAX_TYPES:
            return
        if None not in counties and row.get("county") not in counties:
            return
        if self._vs is None:
            self._vs = [v for v in _registry() if v.signal in ("tax_lien", "lien_registry_wall")]
        self.checked += 1
        if not any(v.applies(row) for v in self._vs):
            self._bad(row, f"{row.get('source')}:{row.get('county')}")


class NcHeirNoticeShape(_Check):
    name = "top80v-nc-heir-notice-shape"
    describe = "a public_notices.nc_heir_notices row is an NC probate_notice naming a decedent or a parcel"

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.validation import NC_COUNTIES
        self._nc = set(NC_COUNTIES)

    def feed(self, row: dict) -> None:
        if row.get("source") != NC_HEIR_SLUG:
            return
        self.checked += 1
        hp = _raw(row).get("heir_naming_publication")
        if not isinstance(hp, dict):
            return self._bad(row, "no_block")
        if row.get("listing_type") != "probate_notice" or row.get("state") != "NC":
            return self._bad(row, "type_or_state")
        if row.get("county") not in self._nc:
            return self._bad(row, "county")
        if not (hp.get("decedents") or hp.get("parcel_id")):
            return self._bad(row, "no_decedent_or_parcel")
        if not (hp.get("case_number") or hp.get("parcel_id") or hp.get("hearing_date")):
            return self._bad(row, "no_case_parcel_or_hearing")
        if not isinstance(hp.get("is_quiet_title"), bool):
            return self._bad(row, "quiet_title_flag_not_bool")


class QuietTitleFlagHasText(_Check):
    name = "top80v-quiet-title-flag-has-text"
    describe = "an NC heir-notice row flagged is_quiet_title keeps notice text that says so"

    def feed(self, row: dict) -> None:
        if row.get("source") != NC_HEIR_SLUG:
            return
        hp = _raw(row).get("heir_naming_publication")
        if not isinstance(hp, dict) or not hp.get("is_quiet_title"):
            return
        text = (_raw(row).get("column") or {}).get("text")
        if not text:
            return
        self.checked += 1
        if not _QT.search(str(text)):
            self._bad(row, "flag_without_phrase")


def make_checks() -> list:
    return [CubeLedgerNamesRegistered(), CubeNamesTheVerifier(), CourtFeedHasVerifier(), TaxClaimHasVerifier(),
            NcHeirNoticeShape(), QuietTitleFlagHasText()]
