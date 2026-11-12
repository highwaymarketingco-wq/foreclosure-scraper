"""Top-80 register group invariants, Cott eSearch / BIS / Tyler registers (2026-10-09, group
register_other): Forsyth and Davidson (BIS Online Record System), Durham and Johnston (Tyler), the
Cott eSearch v4 counties (Onslow, Pitt, Alamance, Alexander, Pamlico, Polk, Edgecombe, Rutherford,
Graham, Nash) and Marlboro SC (older Cott eSearch). Rowan (a challenge page) is a recorded wall.

Each check would have caught a defect this group measured:
  top80-other-none-found-shape      a raw['rod'] stamped screened_none_found by one of the group's
                                    platforms that is not a clean negative (instrument_count != 0, a
                                    mortgage/lien flag, instruments listed, no fetched_at). Before the
                                    group's modules reported a status, a clean empty answer and a failed
                                    fetch both left the row unstamped: 16 counties read 0% 'checked' on the
                                    10/9 checkpoint although every adapter answered live (75 of 75 lookups).
  top80-other-county-silent         a county of the group with at least MIN_OWNERS owner rows on the board
                                    and not one row carrying raw['rod'] or raw['rod_chain']: the platform
                                    flag is ON in the run profile yet the county produced nothing.
  top80-other-marriage-bound        a raw['marriage_license'] written by register_checks outside the six
                                    counties whose guest search has a MARRIAGES index, a no_match without
                                    checked_at, or a match without a spouse and a book/date: a stamp where the
                                    register cannot answer is a false 'checked'.
  top80-other-sweep-shape           a raw['rod_lien_sweep'] from the Cott county-wide sweep outside its ten
                                    counties, without a window (window_from <= window_to) or a checked_at,
                                    'found'/'possible' with no instrument or 'none_found' with one: the stamp
                                    claims a window the sweep actually read, adverse kinds only.
  top80-other-config-consistent     repo configuration, not rows: every county of the group has a module
                                    reporting a status (search_by_name_status), the profile and vm_lib carry
                                    the same value for the group's flags (all ON), the matrix keeps the
                                    group's marriage verdicts (index / none / login / blocked), Rowan stays
                                    out of the registry, and the marriage enricher is wired in main.py or
                                    declared wire-pending with its line.

Memory: a few counters per county and at most SAMPLE examples (county names only).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
MIN_OWNERS = 20

#: counties the next run must produce register stamps for (platform flag ON in run_profile.json)
REQUIRED = frozenset({
    ("NC", "Forsyth"), ("NC", "Davidson"), ("NC", "Durham"), ("NC", "Johnston"), ("NC", "Onslow"),
    ("NC", "Pitt"), ("NC", "Alamance"), ("NC", "Alexander"), ("NC", "Pamlico"), ("NC", "Polk"),
    ("NC", "Edgecombe"), ("NC", "Rutherford"), ("NC", "Graham"), ("NC", "Nash"), ("SC", "Marlboro"),
})
#: platforms (the `platform` the generic pass stamps) that belong to this group
GROUP_PLATFORMS = frozenset({"nc_cott_v4", "nc_tyler", "cott", "sc_cott_esearch", "nc_ors"})
GROUP_FLAGS = ("FORECLOSURE_NC_COTT_ROD", "FORECLOSURE_NC_TYLER_ROD", "FORECLOSURE_NC_ORS_ROD",
               "FORECLOSURE_SC_COTT_ESEARCH_ROD", "FORECLOSURE_REGISTER_CHECKS", "FORECLOSURE_REGISTER_SWEEP")
SWEEP_COUNTIES = frozenset({"Onslow", "Pitt", "Alamance", "Alexander", "Pamlico", "Polk", "Edgecombe", "Rutherford",
                            "Graham", "Nash"})
MARRIAGE_SOURCES = {"register_checks": False, "cott_v4_marriage_sweep": True}     # source -> carries a window
MARRIAGE_INDEX_COUNTIES = frozenset({"Onslow", "Alamance", "Alexander", "Pamlico", "Edgecombe", "Rutherford"})
#: the matrix verdict each county's marriage_license must keep (rod.column_access)
MARRIAGE_MATRIX = {"onslow": "index", "alamance": "index", "alexander": "index", "pamlico": "index",
                   "edgecombe": "index", "rutherford": "index", "pitt": "none", "polk": "none",
                   "graham": "none", "nash": "none", "forsyth": "login", "davidson": "none", "rowan": "blocked"}


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _result(name: str, checked: int, violations: int, max_v: int, detail: str) -> dict:
    return {"name": name, "checked": checked, "violations": violations, "max_violations": max_v,
            "ok": violations <= max_v, "detail": detail}


def _county(row: dict) -> tuple[str, str]:
    return ((row.get("state") or "").strip().upper(), (row.get("county") or "").replace(" County", "").strip())


class _NoneFoundShape:
    name = "top80-other-none-found-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        rod = _raw(row).get("rod")
        if not isinstance(rod, dict) or not rod.get("screened_none_found"):
            return
        if rod.get("platform") not in GROUP_PLATFORMS:
            return
        self.checked += 1
        clean = (rod.get("instrument_count") == 0 and not rod.get("instruments") and not rod.get("has_mortgage")
                 and not rod.get("has_adverse_lien") and rod.get("fetched_at"))
        if not clean:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append("/".join(_county(row)))

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked:,} none-found stamps from the group's platforms; {self.bad} not clean"
                       + (f" (e.g. {', '.join(self.sample)})" if self.sample else ""))


class _CountySilent:
    name = "top80-other-county-silent"

    def __init__(self) -> None:
        self.owners: Counter = Counter()
        self.stamped: Counter = Counter()

    def feed(self, row: dict) -> None:
        k = _county(row)
        if k not in REQUIRED or not row.get("owner_name"):
            return
        self.owners[k] += 1
        raw = _raw(row)
        if isinstance(raw.get("rod"), dict) or isinstance(raw.get("rod_chain"), dict) \
                or isinstance(raw.get("rod_lien_sweep"), dict):
            self.stamped[k] += 1

    def finish(self) -> dict:
        judged = [k for k in REQUIRED if self.owners[k] >= MIN_OWNERS]
        silent = sorted(f"{k[0]}/{k[1]}" for k in judged if self.stamped[k] == 0)
        return _result(self.name, len(judged), len(silent), 0,
                       f"{len(judged)} group counties with >= {MIN_OWNERS} owner rows; "
                       f"{len(silent)} with no register stamp" + (f": {', '.join(silent)}" if silent else ""))


class _MarriageBound:
    name = "top80-other-marriage-bound"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        ml = _raw(row).get("marriage_license")
        if not isinstance(ml, dict) or ml.get("source") not in MARRIAGE_SOURCES:
            return
        self.checked += 1
        st, co = _county(row)
        ok = st == "NC" and co in MARRIAGE_INDEX_COUNTIES and bool(ml.get("checked_at"))
        if ok and MARRIAGE_SOURCES[ml.get("source")]:                     # the sweep states its window
            ok = bool(ml.get("window_from")) and bool(ml.get("window_to")) and ml["window_from"] <= ml["window_to"]
        if ok and ml.get("status") != "no_match":
            ok = bool(ml.get("spouse_name")) and bool(ml.get("book") or ml.get("license_date")
                                                      or ml.get("license_no") or ml.get("marriage_date"))
        if not ok:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(f"{st}/{co}")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked:,} register marriage blocks; {self.bad} outside an index county "
                       "or malformed" + (f" (e.g. {', '.join(self.sample)})" if self.sample else ""))


class _SweepShape:
    name = "top80-other-sweep-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        sw = _raw(row).get("rod_lien_sweep")
        if not isinstance(sw, dict) or sw.get("platform") != "cott_v4_lien_sweep":
            return
        self.checked += 1
        st, co = _county(row)
        n = len(sw.get("instruments") or [])
        status = sw.get("status")
        ok = (st == "NC" and co in SWEEP_COUNTIES and bool(sw.get("checked_at")) and bool(sw.get("window_from"))
              and bool(sw.get("window_to")) and sw["window_from"] <= sw["window_to"]
              and status in ("found", "possible", "none_found")
              and ((status == "none_found") == (n == 0)))
        if not ok:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(f"{st}/{co}")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked:,} Cott county-sweep lien stamps; {self.bad} malformed or outside the "
                       "swept counties" + (f" (e.g. {', '.join(self.sample)})" if self.sample else ""))


class _ConfigConsistent:
    name = "top80-other-config-consistent"

    def __init__(self, repo: Path = _REPO) -> None:
        self.repo = repo
        self.problems: list[str] = []

    def feed(self, row: dict) -> None:       # static check: rows are irrelevant
        return

    def _profile(self) -> dict:
        try:
            return json.loads((self.repo / "deploy" / "oracle" / "run_profile.json").read_text())
        except (OSError, ValueError):
            self.problems.append("run_profile.json unreadable")
            return {}

    def finish(self) -> dict:
        prof = self._profile()
        flags = prof.get("flags") or {}
        try:
            vm = (self.repo / "deploy" / "oracle" / "vm_lib.sh").read_text()
        except OSError:
            vm = ""
            self.problems.append("vm_lib.sh unreadable")
        for f in GROUP_FLAGS:
            if str(flags.get(f)) != "1":
                self.problems.append(f"{f} not 1 in run_profile.json")
            m = re.search(rf'export {f}="\$\{{{f}:-([^}}]*)\}}"', vm)
            if not m or m.group(1) != "1":
                self.problems.append(f"{f} not exported as 1 in vm_lib.sh")
        try:
            from foreclosure_scraper import enrichment_generic_rod as G
            from foreclosure_scraper.rod import register_checks as RC
            import importlib
            have = {k for k, v in G.ROD_CONFIG.items() if v[0] in ("nc_cott_v4", "nc_tyler", "nc_ors", "cott",
                                                                 "sc_cott_esearch")}
            for k in sorted(REQUIRED):
                if k not in have:
                    self.problems.append(f"{k[0]}/{k[1]} missing from ROD_CONFIG")
                    continue
                mod = importlib.import_module("foreclosure_scraper.rod." + G.ROD_CONFIG[k][0])
                if not hasattr(mod, "search_by_name_status"):
                    self.problems.append(f"{G.ROD_CONFIG[k][0]} has no search_by_name_status")
            if ("NC", "Rowan") in have:
                self.problems.append("Rowan (a challenge page) is in ROD_CONFIG")
            if sorted(RC.MARRIAGE_ADAPTER.counties) != sorted(MARRIAGE_INDEX_COUNTIES):
                self.problems.append("marriage adapter counties differ from the index counties")
        except Exception as exc:  # noqa: BLE001
            self.problems.append(f"register modules unimportable: {type(exc).__name__}")
        try:
            matrix = json.loads((self.repo / "docs" / "county_records" / "county_records_matrix.json").read_text())
            by = {c.get("county", "").lower(): c for c in matrix.get("counties", []) if c.get("state") == "NC"}
            for co, want in MARRIAGE_MATRIX.items():
                got = ((by.get(co) or {}).get("rod") or {}).get("column_access", {}).get("marriage_license")
                if got != want:
                    self.problems.append(f"matrix {co} marriage_license={got!r}, want {want!r}")
            if ((by.get("rowan") or {}).get("rod") or {}).get("column_access", {}).get("liens") != "blocked":
                self.problems.append("matrix rowan liens verdict missing")
        except (OSError, ValueError):
            self.problems.append("county_records_matrix.json unreadable")
        wired = False
        try:
            wired = "enrichment_register_checks" in (self.repo / "src" / "foreclosure_scraper" / "main.py").read_text()
        except OSError:
            pass
        if not wired and "enrichment_register_checks" not in (prof.get("unwired_wire_pending") or {}):
            self.problems.append("enrichment_register_checks neither wired in main.py nor wire-pending")
        return _result(self.name, len(REQUIRED) + len(MARRIAGE_MATRIX), len(self.problems), 0,
                       "group configuration consistent" if not self.problems else "; ".join(self.problems[:6]))


def make_checks() -> list:
    return [_NoneFoundShape(), _CountySilent(), _MarriageBound(), _SweepShape(), _ConfigConsistent()]
