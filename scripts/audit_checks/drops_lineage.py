"""Drops and column lineage invariants (audit 2026-10-09, area drops_lineage): data the pipeline
removes, nulls or never publishes on purpose must be removed for a right reason, and every column
must count what the scorer acts on. docs/audit_2026-10-09/drops_lineage.md has the measurements.

  drops-short-parcel-county-native  a row published with no parcel id although the id validation
                                    nulled (raw['parcel_id_nulled'], too_short) is the county's own
                                    parcel number (validation.COUNTY_NATIVE_SHORT_PARCEL: Cleveland,
                                    Onslow, Nash, Rowan; 1,704 rows on the 10/8 checkpoint). The
                                    fixed validation keeps and restores these, so 0 after one run.
  drops-situs-road-nulled           an address the SITUS SANITY guard withheld (raw['situs_nulled'])
                                    that is a road location, not a placeholder or an entity name
                                    (situs_sanity.situs_is_junk now False): 82 of 8,606 on 10/8.
  drops-dateless-filtered-source    a dateless row from a source main._active_only drops when dateless
                                    (not in DATELESS_OK_SOURCES, not age-exempt): its re-scrape never
                                    reaches the board, so the published copy only ages until it is
                                    removed (board_persist max misses). A retired source (disabled as a
                                    board source on purpose) is reported in the detail, not counted.
  drops-age-out-imminent            rows at the miss limit (raw.pulled_sale.consecutive_misses >= 4):
                                    the next run removes each one it does not re-scrape. A bound, so a
                                    mass age-out (a source that broke, a key that stopped matching)
                                    stops the gate instead of quietly emptying a county.
  drops-county-blank-source         a row with no county from a source outside the known county-less
                                    feeds (LiensNC filings, CourtListener RECAP, the SC statewide
                                    registries); the detail gives the total and the sources.
  drops-marker-bounds               each drop/withdraw marker's row count stays under its bound
                                    (parcel_id_nulled, situs_nulled, exempt_claim_withdrawn, ...): a
                                    rule that starts removing far more than it did is a rule that broke.
  drops-low-value-parcel            a county value under $5,000 on a non-land row is kept in
                                    raw['tax_value_low'] with raw['low_value_parcel'] (owner decision
                                    2026-10-09), Listing.tax_value stays empty and no single-family
                                    ARV is published on it (1,791 such rows on 10/8).
  lineage-gis-subkeys               raw.gis carries only the sub-keys web_artifact.RAW_KEEP['gis'] keeps
                                    (a writer that bypassed the publish slim).
  lineage-scorer-gated-columns      scripts/gap_matrix.py's second view counts a scorer-gated column
                                    (phone, divorce, code_enforcement, bankruptcy_stay, title_risk,
                                    storm_damage, ...) exactly when the scorer's own predicate does; the
                                    detail gives how far the owner's 10/1 presence rule is from it.
Memory: counters, and at most SAMPLE short ids per check (parcel ids and source slugs only).
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
#: board_persist's prior-only miss limit (enrichment_pulled_sales.PULLED_RETENTION_WEEKS)
MAX_MISSES = 4
#: Sources disabled as board sources on purpose; their published rows age out by design.
RETIRED_BOARD_SOURCES = {
    "counties_sc.sc_dew_lien_registry": "disabled=True: cross-reference only (enrichment_dew_liens)",
}
#: Feeds whose rows have no county by nature (a filing or registry entry with no parcel).
KNOWN_COUNTYLESS = ("liensnc", "courtlistener.recap", "counties_sc.sc_des_brownfields",
                    "counties_sc.sc_state_tax_lien")
#: Row-count bounds per drop/withdraw marker. Measured on the 10/7 published board and the 10/8
#: dot_ocr checkpoint (docs/audit_2026-10-09/drops_lineage.md); a bound is about 1.5x the larger.
MARKER_BOUNDS = {
    "parcel_id_nulled": 50_000,          # 10/7 board 33,807; 10/8 checkpoint 21,250
    "situs_nulled": 13_000,              # 10/8 checkpoint 8,606 (published from this audit on)
    "exempt_claim_withdrawn": 1_500,     # 10/5 replay 392
    "withdrawn_case_type_other": 2_500,  # 10/8 checkpoint 260 (published from this audit on)
    "address_not_property": 1_000,       # 10/7 board 79
    "parcel_withdrawn_fallback_point": 7_000,   # 10/7 board 4,688
    "county_was_name_derived": 500,      # 10/7 board 13
    "address_was_owner_mailing": 1_000,  # 10/7 board 389
}


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


class _Check:
    name = "drops-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: dict[str, int] = {}
        self.extra: list[str] = []

    def _bad(self, why: str, sample: str = "") -> None:
        self.violations += 1
        self.by[why] = self.by.get(why, 0) + 1
        if sample and len(self.samples) < SAMPLE:
            self.samples.append(sample)

    def finish(self) -> dict:
        parts = [self.describe]
        if self.by:
            top = sorted(self.by.items(), key=lambda kv: -kv[1])[:12]
            parts.append("by: " + ", ".join(f"{k} {v}" for k, v in top))
        parts += self.extra
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations, "detail": " | ".join(p for p in parts if p)}


class ShortParcelCountyNative(_Check):
    name = "drops-short-parcel-county-native"
    describe = "no row loses a county-native short parcel id to the 7-character floor"

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.validation import county_native_short_parcel
        self._native = county_native_short_parcel

    def feed(self, row: dict) -> None:
        nulled = _raw(row).get("parcel_id_nulled")
        if not isinstance(nulled, dict) or nulled.get("reason") != "too_short":
            return
        self.checked += 1
        if (row.get("parcel_id") or "").strip():
            return
        val = str(nulled.get("value") or "")
        if self._native(row.get("state"), row.get("county"), val):
            self._bad(f"{row.get('state')}|{row.get('county')}", f"{row.get('county')}:{val}")


class SitusRoadNulled(_Check):
    name = "drops-situs-road-nulled"
    describe = "no road location is withheld as a junk situs"

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.situs_sanity import situs_is_junk
        self._junk = situs_is_junk

    def feed(self, row: dict) -> None:
        v = _raw(row).get("situs_nulled")
        if not isinstance(v, str) or not v.strip():
            return
        self.checked += 1
        if not self._junk(v):
            self._bad(str(row.get("source") or "?"), str(row.get("parcel_id") or row.get("source") or "?")[:40])


class DatelessFilteredSource(_Check):
    name = "drops-dateless-filtered-source"
    max_violations = 25          # 10/7 board: 1 outside the retired DEW registry (8,288)
    describe = ("dateless rows from a source _active_only drops when dateless (their re-scrape is "
                "filtered, the published copy can only age out)")

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.board_persist import AGE_EXEMPT_SOURCES
        from foreclosure_scraper.main import DATELESS_OK_SOURCES
        self._ok = frozenset(DATELESS_OK_SOURCES)
        self._exempt = frozenset(AGE_EXEMPT_SOURCES)
        self.retired: dict[str, int] = {}

    def _dateless_ok(self, src: str) -> bool:
        return src in self._ok or any(src.startswith(b + ".") for b in self._ok)

    def feed(self, row: dict) -> None:
        if row.get("sale_date"):
            return
        src = str(row.get("source") or "")
        self.checked += 1
        if self._dateless_ok(src) or any(p in self._exempt for p in src.split(".")):
            return
        if src in RETIRED_BOARD_SOURCES:
            self.retired[src] = self.retired.get(src, 0) + 1
            return
        self._bad(src, str(row.get("parcel_id") or row.get("case_number") or "?")[:40])

    def finish(self) -> dict:
        if self.retired:
            self.extra.append("retired sources aging out by design: " + ", ".join(
                f"{k} {v} ({RETIRED_BOARD_SOURCES[k]})" for k, v in self.retired.items()))
        return super().finish()


class AgeOutImminent(_Check):
    name = "drops-age-out-imminent"
    max_violations = 2_500       # 10/7 board 467 (PTS Cloud 209, county PDF lists 66, ...)
    describe = f"rows at the prior-only miss limit ({MAX_MISSES}): removed by the next run unless re-scraped"

    def feed(self, row: dict) -> None:
        self.checked += 1
        ps = _raw(row).get("pulled_sale")
        m = ps.get("consecutive_misses") if isinstance(ps, dict) else 0
        if isinstance(m, int) and m >= MAX_MISSES:
            self._bad(str(row.get("source") or "?"))


class CountyBlankSource(_Check):
    name = "drops-county-blank-source"
    max_violations = 25
    describe = "rows with no county come only from feeds that have none by nature"

    def __init__(self) -> None:
        super().__init__()
        self.total = 0

    def feed(self, row: dict) -> None:
        self.checked += 1
        if (row.get("county") or "").strip():
            return
        self.total += 1
        src = str(row.get("source") or "")
        if not any(k == src or k in src.split(".") or src.startswith(k + ".") for k in KNOWN_COUNTYLESS):
            self._bad(f"{row.get('state') or '?'}|{src}", src)

    def finish(self) -> dict:
        self.extra.append(f"blank-county rows in all: {self.total}")
        return super().finish()


class MarkerBounds(_Check):
    name = "drops-marker-bounds"
    describe = "each drop/withdraw marker stays under its row-count bound"

    def __init__(self) -> None:
        super().__init__()
        self.counts = {k: 0 for k in MARKER_BOUNDS}

    def feed(self, row: dict) -> None:
        self.checked += 1
        raw = _raw(row)
        for k in MARKER_BOUNDS:
            if raw.get(k) not in (None, "", [], {}, False):
                self.counts[k] += 1

    def finish(self) -> dict:
        for k, n in self.counts.items():
            if n > MARKER_BOUNDS[k]:
                self._bad(f"{k} {n} > {MARKER_BOUNDS[k]}")
        self.extra.append("counts: " + ", ".join(f"{k} {n}" for k, n in self.counts.items() if n))
        return super().finish()


class LowValueParcel(_Check):
    name = "drops-low-value-parcel"
    describe = ("a low county value is kept beside the low_value_parcel flag, never as tax_value, "
                "and carries no ARV")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        tvl, flag = raw.get("tax_value_low"), raw.get("low_value_parcel")
        if tvl in (None, {}) and not flag:
            return
        self.checked += 1
        ident = str(row.get("parcel_id") or row.get("source") or "?")[:40]
        if not isinstance(tvl, dict) or not isinstance(tvl.get("value"), (int, float)):
            self._bad("flag without its kept value", ident)
        elif flag is not True:
            self._bad("kept value without the flag", ident)
        elif row.get("tax_value"):
            self._bad("tax_value still set", ident)
        elif str(row.get("property_kind") or "") != "land":
            calc = raw.get("calc")
            if isinstance(calc, dict) and calc.get("arv_expected") is not None:
                self._bad("single-family ARV published", ident)


class GisSubkeys(_Check):
    name = "lineage-gis-subkeys"
    describe = "raw.gis holds only the sub-keys RAW_KEEP['gis'] publishes"

    def __init__(self) -> None:
        super().__init__()
        from foreclosure_scraper.web_artifact import RAW_KEEP
        self._keep = frozenset(RAW_KEEP["gis"])

    def feed(self, row: dict) -> None:
        g = _raw(row).get("gis")
        if not isinstance(g, dict):
            return
        self.checked += 1
        extra = [k for k in g if k not in self._keep]
        if extra:
            self._bad(sorted(extra)[0], str(row.get("parcel_id") or "?")[:40])


def _load_gap_matrix():
    path = _REPO / "scripts" / "gap_matrix.py"
    name = "gap_matrix_drops_lineage"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


class ScorerGatedColumns(_Check):
    name = "lineage-scorer-gated-columns"
    describe = ("gap_matrix's second view counts each scorer-gated column exactly when the scorer's "
                "predicate does")

    def __init__(self, today: Optional[date] = None) -> None:
        super().__init__()
        self.gm = _load_gap_matrix()
        self.today = today or date.today()
        self.inflated: dict[str, int] = {}
        self.hits: dict[str, int] = {}

    def feed(self, row: dict) -> None:
        if not isinstance(row, dict):
            return
        self.checked += 1
        gm = self.gm
        raw = _raw(row)
        owner = gm.owner_columns(row)
        pos = gm.positive_columns(row, owner, {}, self.today)
        for col, (_k, gate) in gm.SCORER_GATES.items():
            try:
                want = bool(gate(row, raw, self.today))
            except Exception:  # noqa: BLE001 - the gate itself treats an odd block as no hit
                want = False
            if want:
                self.hits[col] = self.hits.get(col, 0) + 1
            if (col in pos) != want:
                self._bad(col, str(row.get("parcel_id") or "?")[:40])
            if col in owner and not want:
                self.inflated[col] = self.inflated.get(col, 0) + 1

    def finish(self) -> dict:
        if self.inflated:
            self.extra.append("10/1 presence hits the scorer does not count: " + ", ".join(
                f"{k} {v} (scorer {self.hits.get(k, 0)})"
                for k, v in sorted(self.inflated.items(), key=lambda kv: -kv[1])))
        return super().finish()


def make_checks() -> list:
    return [ShortParcelCountyNative(), SitusRoadNulled(), DatelessFilteredSource(), AgeOutImminent(),
            CountyBlankSource(), MarkerBounds(), LowValueParcel(), GisSubkeys(), ScorerGatedColumns()]
