"""Top-80 Logan Systems / Harris Recorder group invariants (2026-10-09): the county-wide AcclaimWeb
lien sweep (Horry, Pickens) and the browser-only Logan platforms that stay OFF.

Each check would have caught a defect this group measured or guards a claim it makes:
  top80-lien-sweep-shape         raw['rod_lien_sweep'] that is not what enrichment_register_lien_sweep
                                 writes: a status outside found / possible / none_found, a missing or
                                 impossible date (window_from after window_to, window_to after
                                 checked_at), 'none_found' beside any counted instrument, 'found'
                                 with no parcel- or exact-name instrument. A 'screened, none found'
                                 without its window would claim every year back to 1984.
  top80-lien-sweep-county-only   the stamp on a row outside Horry / Pickens SC, or one whose county
                                 differs from the row's: the sweep read one register and matched the
                                 wrong board rows.
  top80-lien-sweep-name-fit      a 'found' stamp none of whose instruments names the row's owner (the
                                 surname and first name must fit one of the instrument's parties).
  top80-lien-sweep-coverage      rows of the two swept counties with an owner name and no stamp.
                                 Ratchet: the 2026-10-09 board had 11,566 such rows (the sweep had
                                 not run); the count may only fall.
  top80-logan-harris-config      repo configuration, not rows: the sweep flag is ON and equal in
                                 run_profile.json and vm_lib.sh, the browser-only Logan / Harris flags
                                 are OFF (measured 20 to 47 s and 250 to 290 MB a lookup, 900 s fits
                                 about 26 lookups against 10,292 rows), the matrix carries the
                                 marriage_license 'none' verdict for the eight register counties of the
                                 group and Moore stays blocked.

Memory: counters and at most SAMPLE parcel ids (public record) per check.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
SWEEP_COUNTIES = {("SC", "horry"), ("SC", "pickens")}
STATUSES = {"found", "possible", "none_found"}
#: raw['rod_lien_sweep'] is also written by enrichment_county_lien_sweep (other registers, its own checks);
#: these checks look only at the stamps of the AcclaimWeb sweep
PLATFORM = "harris_acclaimweb_lien_sweep"
#: owner rows of Horry + Pickens on the 2026-10-09 published board (350,013 rows), before any sweep
COVERAGE_BASELINE = 11566
BROWSER_FLAGS = ("FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "FORECLOSURE_NC_HARRIS_ROD")
MARRIAGE_NONE = [("NC", "cabarrus"), ("NC", "catawba"), ("NC", "chatham"), ("NC", "cumberland"),
                 ("NC", "transylvania"), ("SC", "spartanburg"), ("SC", "horry"), ("SC", "pickens")]


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _county(row: dict) -> str:
    return str(row.get("county") or "").replace(" County", "").strip().lower()


def _owner(row: dict) -> str:
    raw = _raw(row)
    return str(row.get("owner_name") or (raw.get("gis") or {}).get("owner") or "").strip()


def _mine(row: dict) -> Optional[dict]:
    s = _raw(row).get("rod_lien_sweep")
    if s is None or (isinstance(s, dict) and s.get("platform") not in (None, PLATFORM)):
        return None
    return s if s is not None else None


def _day(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _result(name: str, checked: int, violations: int, max_v: int, detail: str) -> dict:
    return {"name": name, "checked": checked, "violations": violations, "max_violations": max_v,
            "ok": violations <= max_v, "detail": detail}


class _Shape:
    name = "top80-lien-sweep-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        s = _mine(row)
        if s is None:
            return
        self.checked += 1
        ok = isinstance(s, dict) and s.get("status") in STATUSES
        if ok:
            a, b, c = _day(s.get("window_from")), _day(s.get("window_to")), _day(s.get("checked_at"))
            ok = bool(a and b and c and a <= b <= c)
            insts = s.get("instruments") if isinstance(s.get("instruments"), list) else []
            strong = [i for i in insts if isinstance(i, dict) and i.get("fit") in ("parcel", "exact")]
            if ok and s["status"] == "none_found":
                ok = not insts and not s.get("adverse_count") and not s.get("possible_count")
            if ok and s["status"] == "found":
                ok = bool(strong) and (s.get("adverse_count") or 0) >= 1
            if ok and s["status"] == "possible":
                ok = bool(insts) and not strong
        if not ok:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(str(row.get("parcel_id") or row.get("id") or "?"))

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.bad} of {self.checked} stamps malformed; e.g. {self.sample}" if self.bad
                       else f"{self.checked} stamps well formed")


class _CountyOnly:
    name = "top80-lien-sweep-county-only"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        s = _mine(row)
        if s is None:
            return
        self.checked += 1
        st = str(row.get("state") or "").upper()
        c = _county(row)
        if (st, c) not in SWEEP_COUNTIES or str((s or {}).get("county") or "").strip().lower() != c:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(str(row.get("parcel_id") or row.get("id") or "?"))

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.bad} stamps on rows outside their register's county; e.g. {self.sample}" if self.bad
                       else f"{self.checked} stamps all on their own county")


class _NameFit:
    name = "top80-lien-sweep-name-fit"

    def __init__(self) -> None:
        from foreclosure_scraper.rod.sc_chain import name_fit, owner_query
        self._fit, self._q = name_fit, owner_query
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        s = _mine(row)
        if not isinstance(s, dict) or s.get("status") != "found":
            return
        q = self._q(_owner(row))
        if q is None:
            return
        self.checked += 1
        hit = any(self._fit(q, p) for i in (s.get("instruments") or []) if isinstance(i, dict)
                  for p in (i.get("f"), i.get("g")) if p)
        if not hit:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(str(row.get("parcel_id") or row.get("id") or "?"))

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.bad} 'found' stamps no instrument of which names the owner; e.g. {self.sample}"
                       if self.bad else f"{self.checked} 'found' stamps all name the owner")


class _Coverage:
    name = "top80-lien-sweep-coverage"

    def __init__(self) -> None:
        self.rows = self.unstamped = 0

    def feed(self, row: dict) -> None:
        if (str(row.get("state") or "").upper(), _county(row)) not in SWEEP_COUNTIES or not _owner(row):
            return
        self.rows += 1
        if not isinstance(_raw(row).get("rod_lien_sweep"), dict):
            self.unstamped += 1

    def finish(self) -> dict:
        return _result(self.name, self.rows, self.unstamped, COVERAGE_BASELINE,
                       f"{self.unstamped} of {self.rows} Horry/Pickens owner rows carry no sweep stamp "
                       f"(baseline {COVERAGE_BASELINE}: may only fall)")


class _Config:
    name = "top80-logan-harris-config"

    def feed(self, row: dict) -> None:  # configuration only
        return

    def finish(self) -> dict:
        problems: list[str] = []
        n = 0
        try:
            prof = json.loads((_REPO / "deploy/oracle/run_profile.json").read_text())
            env = prof.get("flags") or {}
            lib = (_REPO / "deploy/oracle/vm_lib.sh").read_text()
            for flag, want in [("FORECLOSURE_SC_LIEN_SWEEP", "1")] + [(f, "0") for f in BROWSER_FLAGS]:
                n += 1
                m = re.search(rf'{flag}="\$\{{{flag}:-(\d)\}}"', lib)
                if str(env.get(flag)) != want or m is None or m.group(1) != want:
                    problems.append(f"{flag}: profile {env.get(flag)!r}, vm_lib {m.group(1) if m else None!r}, want {want}")
        except Exception as exc:  # noqa: BLE001 - an unreadable file is itself the finding
            problems.append(f"profile/vm_lib unreadable: {type(exc).__name__}")
        try:
            mx = {(c["state"], c["county"].lower()): c for c in json.loads(
                (_REPO / "docs/county_records/county_records_matrix.json").read_text())["counties"]}
            for key in MARRIAGE_NONE:
                n += 1
                have = ((mx.get(key) or {}).get("rod") or {}).get("column_access", {}).get("marriage_license")
                if have != "none":
                    problems.append(f"matrix {key[1]} marriage_license: {have!r} != 'none'")
            n += 1
            if ((mx.get(("NC", "moore")) or {}).get("rod") or {}).get("access") != "blocked":
                problems.append("matrix moore access is not 'blocked'")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"matrix unreadable: {type(exc).__name__}")
        try:
            from foreclosure_scraper.rod import lien_sweep
            n += 1
            if set(lien_sweep.SWEEP_COUNTIES) != {("SC", "horry"), ("SC", "pickens")}:
                problems.append("lien_sweep.SWEEP_COUNTIES changed")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"lien_sweep import failed: {type(exc).__name__}")
        return _result(self.name, n, len(problems), 0, "; ".join(problems) or f"{n} configuration items agree")


def make_checks() -> list:
    return [_Shape(), _CountyOnly(), _NameFit(), _Coverage(), _Config()]
