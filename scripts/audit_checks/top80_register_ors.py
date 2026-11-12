"""Top-80 register group invariants (2026-10-09): the name-index registers (Online Record System in NC
and SC, Aumentum/Harris 'ROD Web Access', Charleston) and what the board holds from them.

Each check would have caught a defect this group measured:
  top80-register-negative-shape       a raw['rod'] stamped "screened, none found" (screened_none_found)
                                      that is not a clean negative: instrument_count != 0, a mortgage
                                      flag set, or no fetched_at. generic_rod now stamps this when a name
                                      index answers ok with nothing under the owner's name; before it,
                                      a clean no-hit and a failed fetch both left the row unstamped, so
                                      about half the lookups on the live checks (Davidson 4 of 7, Barnwell
                                      1 of 4, Berkeley 3 of 4, Dorchester 3 of 4) produced no verdict.
  top80-register-county-silent        a register county with at least MIN_OWNERS owner rows on the board
                                      and not one row with raw['rod'] or raw['rod_chain']: the platform
                                      flag is on in run_profile.json yet the county produced nothing (a
                                      silent death, e.g. Mecklenburg's empty result page was read as an
                                      error so its clean negatives never landed). Walled counties
                                      (Charleston reCAPTCHA, Moore HTTP 403) and the browser-only Harris
                                      counties (flag OFF in the profile) are not required.
  top80-marriage-license-shape        raw['marriage_license'] from the Harris Marriage index that is not
                                      well formed: a found licence needs spouse_name and license_date, a
                                      negative needs status no_match, checked_at and the source.
  top80-register-config-consistent    repo configuration, not rows: every county of the register group
                                      has a module that reports status (search_by_name_status), the
                                      profile and vm_lib carry the same value for the group's flags, and
                                      the matrix keeps the group's verdicts (Charleston captcha, Moore
                                      blocked, marriage login/none/blocked per county).

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

#: counties the next run must produce register stamps for (flag ON in deploy/oracle/run_profile.json)
REQUIRED = frozenset({
    ("NC", "Davidson"), ("NC", "Forsyth"), ("NC", "Guilford"),
    ("SC", "Abbeville"), ("SC", "Barnwell"), ("SC", "Berkeley"), ("SC", "Colleton"), ("SC", "Dorchester"),
    ("SC", "Florence"), ("SC", "Georgetown"), ("SC", "Lancaster"), ("SC", "Laurens"), ("SC", "York"),
})
#: documented walls and browser-only counties that may legitimately hold nothing
NOT_REQUIRED = frozenset({("SC", "Charleston"), ("NC", "Moore"), ("NC", "Mecklenburg"), ("NC", "Carteret")})

GROUP_FLAGS = ("FORECLOSURE_NC_ORS_ROD", "FORECLOSURE_SC_ORS_ROD", "FORECLOSURE_NC_HARRIS_ROD",
               "FORECLOSURE_NC_HARRIS_MARRIAGE")


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _result(name: str, checked: int, violations: int, max_v: int, detail: str) -> dict:
    return {"name": name, "checked": checked, "violations": violations, "max_violations": max_v,
            "ok": violations <= max_v, "detail": detail}


class _NegativeShape:
    name = "top80-register-negative-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        rod = _raw(row).get("rod")
        if not isinstance(rod, dict) or not rod.get("screened_none_found"):
            return
        self.checked += 1
        clean = (rod.get("instrument_count") == 0 and not rod.get("has_mortgage") and not rod.get("has_adverse_lien")
                 and not rod.get("open_mortgages_est") and rod.get("fetched_at"))
        if not clean:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(f"{row.get('state')}|{row.get('county')}")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} rows screened-none-found; {self.bad} malformed; sample {self.sample}")


class _CountySilent:
    name = "top80-register-county-silent"

    def __init__(self) -> None:
        self.owners: Counter = Counter()
        self.stamped: Counter = Counter()

    def feed(self, row: dict) -> None:
        key = ((row.get("state") or "").upper(), (row.get("county") or "").strip().title())
        if key not in REQUIRED or not (row.get("owner_name") or "").strip():
            return
        self.owners[key] += 1
        raw = _raw(row)
        if raw.get("rod") or raw.get("rod_chain"):
            self.stamped[key] += 1

    def finish(self) -> dict:
        judged = [k for k in REQUIRED if self.owners[k] >= MIN_OWNERS]
        silent = sorted(f"{s} {c}" for s, c in judged if self.stamped[(s, c)] == 0)
        return _result(self.name, len(judged), len(silent), 0,
                       f"{len(judged)} register counties with >= {MIN_OWNERS} owner rows; none stamped: {silent}; "
                       f"stamped rows {sum(self.stamped.values())}")


class _MarriageShape:
    name = "top80-marriage-license-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0

    def feed(self, row: dict) -> None:
        ml = _raw(row).get("marriage_license")
        if not isinstance(ml, dict) or ml.get("source") != "harris_marriage_index":
            return
        self.checked += 1
        if ml.get("status") == "no_match":
            ok = bool(ml.get("checked_at"))
        else:
            ok = bool(ml.get("spouse_name") and ml.get("license_date"))
        self.bad += 0 if ok else 1

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0, f"{self.checked} Harris marriage-index rows; {self.bad} malformed")


class _ConfigConsistent:
    name = "top80-register-config-consistent"

    def feed(self, row: dict) -> None:   # configuration check: rows are not needed
        return

    def finish(self) -> dict:
        problems: list[str] = []
        n = 0
        try:
            from foreclosure_scraper import enrichment_generic_rod as g
            for key, entry in g.ROD_CONFIG.items():
                if entry[0] in ("sc_online_record_system", "nc_ors"):
                    n += 1
                    mod = g._get_module(entry[0])
                    if mod is None or not hasattr(mod, "search_by_name_status"):
                        problems.append(f"{key[1]}: {entry[0]} has no search_by_name_status")
        except Exception as exc:  # noqa: BLE001 - a broken import is itself the finding
            problems.append(f"registry import failed: {type(exc).__name__}")
        prof_p = _REPO / "deploy/oracle/run_profile.json"
        lib_p = _REPO / "deploy/oracle/vm_lib.sh"
        try:
            prof = json.loads(prof_p.read_text())
            env = prof.get("flags") or {}
            lib = lib_p.read_text()
            for flag in GROUP_FLAGS:
                n += 1
                m = re.search(rf'{flag}="\$\{{{flag}:-(\d)\}}"', lib)
                if flag not in env or m is None or str(env[flag]) != m.group(1):
                    problems.append(f"{flag}: profile {env.get(flag)!r} vs vm_lib {m.group(1) if m else None!r}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"profile/vm_lib unreadable: {type(exc).__name__}")
        try:
            mx = {(c["state"], c["county"]): c for c in json.loads(
                (_REPO / "docs/county_records/county_records_matrix.json").read_text())["counties"]}
            want = [(("SC", "charleston"), None, "captcha"), (("NC", "moore"), None, "blocked"),
                    (("NC", "guilford"), "marriage_license", "login"), (("NC", "forsyth"), "marriage_license", "login"),
                    (("NC", "davidson"), "marriage_license", "none"), (("SC", "barnwell"), "marriage_license", "blocked")]
            for key, col, val in want:
                n += 1
                rod = (mx.get(key) or {}).get("rod") or {}
                have = rod.get("access") if col is None else (rod.get("column_access") or {}).get(col)
                if have != val:
                    problems.append(f"matrix {key[1]} {col or 'access'}: {have!r} != {val!r}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"matrix unreadable: {type(exc).__name__}")
        return _result(self.name, n, len(problems), 0, "; ".join(problems) or f"{n} configuration items agree")


def make_checks() -> list:
    return [_NegativeShape(), _CountySilent(), _MarriageShape(), _ConfigConsistent()]
