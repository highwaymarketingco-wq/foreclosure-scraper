"""Top-80 register group invariants (2026-10-09): Courthouse Computer Systems (classic ASP and LRSearch),
GovOS CountyFusion and GovOS/Kofile PublicSearch, read by the county-wide sweeps
(rod/county_sweeps.py, enrichment_county_lien_sweep.py) and the Sumter / Beaufort name adapters.

Each check would have caught a defect this group measured:
  top80-sweep-stamp-shape       a raw['rod_lien_sweep'] from this group's sweeps that is not a well-formed
                                dated stamp: status found | possible | none_found, a checked_at and a
                                window_from <= window_to; 'none_found' with instruments or an adverse count,
                                'found' with no exact-name instrument. A "screened, none found" claim
                                without its window would read as "no lien ever", which the sweep never
                                establishes (adverse instrument types only, the window it read only).
  top80-sweep-county-silent     a swept county with at least MIN_OWNERS owner rows on the checkpoint and
                                not one stamp, once the sweep has run at all: the platform answered 200
                                and the page was read as a wall (the shared wall detector reads
                                Cloudflare's passive jsd beacon, "challenge-platform", as a challenge page:
                                that made Beaufort and 15 vendor-hosted CCS tenants look walled on 10/7),
                                or a parser missed a layout. While no row anywhere carries this group's
                                stamp (a checkpoint older than the sweep) the check reports "not run yet".
  top80-marriage-sweep-shape    raw['marriage_license'] from the Beaufort Marriages sweep that is not well
                                formed: found/possible need spouse_name and license_date, no_match needs
                                checked_at and the swept window.
  top80-sweep-config-consistent repository configuration, not rows: every county of SWEEP_COUNTIES has a
                                reader that exists, the HOSTED_CCHS tenants all sit on a vendor server, the
                                name adapters (Sumter, Beaufort) are in the generic registry and report a
                                status, the profile and vm_lib carry the same value for this group's flags,
                                the wiring line for the pass is recorded in the profile (or the pass is in
                                main.py), and the matrix keeps this group's marriage verdicts.

Memory: a few counters per county and at most SAMPLE examples (county names only).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
MIN_OWNERS = 20

#: the platform labels this group's sweeps write (rod/county_sweeps.Reader.label)
LIEN_LABELS = frozenset({"ccs_classic_asp_sweep", "ccs_lrsearch_sweep", "govos_countyfusion_sweep",
                         "govos_publicsearch_sweep"})
MARRIAGE_LABEL = "ccs_lrsearch_marriage_sweep"

GROUP_FLAGS = ("FORECLOSURE_COUNTY_LIEN_SWEEP", "FORECLOSURE_COUNTY_MARRIAGE_SWEEP",
               "FORECLOSURE_SC_COUNTYFUSION_ROD", "FORECLOSURE_NC_LRSEARCH_ROD")

#: marriage verdicts this group put in the matrix (state, county, column) -> value
MARRIAGE_VERDICTS = {("SC", "greenville"): "none", ("NC", "lincoln"): "none", ("NC", "henderson"): "none",
                     ("NC", "madison"): "none", ("NC", "orange"): "none", ("NC", "franklin"): "none",
                     ("NC", "gates"): "none", ("NC", "hertford"): "none", ("NC", "hyde"): "none",
                     ("NC", "montgomery"): "none", ("NC", "caldwell"): "none", ("NC", "camden"): "none",
                     ("NC", "caswell"): "none", ("NC", "chowan"): "none", ("NC", "currituck"): "none"}


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _result(name: str, checked: int, violations: int, max_v: int, detail: str) -> dict:
    return {"name": name, "checked": checked, "violations": violations, "max_violations": max_v,
            "ok": violations <= max_v, "detail": detail}


def _county_key(row: dict) -> tuple[str, str]:
    return ((row.get("state") or "").upper(), (row.get("county") or "").replace(" County", "").strip().title())


class _StampShape:
    name = "top80-sweep-stamp-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        s = _raw(row).get("rod_lien_sweep")
        if not isinstance(s, dict) or s.get("platform") not in LIEN_LABELS:
            return
        self.checked += 1
        status = s.get("status")
        wf, wt = s.get("window_from"), s.get("window_to")
        ok = (status in ("found", "possible", "none_found") and bool(s.get("checked_at")) and bool(wf and wt)
              and str(wf) <= str(wt))
        if ok and status == "none_found":
            ok = not s.get("instruments") and not s.get("adverse_count") and not s.get("possible_count")
        if ok and status == "found":
            ok = (s.get("adverse_count") or 0) >= 1 and any(
                i.get("fit") == "exact" for i in (s.get("instruments") or []) if isinstance(i, dict))
        if ok and status == "possible":
            ok = (s.get("possible_count") or 0) >= 1 and (s.get("adverse_count") or 0) == 0
        if not ok:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append("%s|%s" % _county_key(row))

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} sweep stamps; {self.bad} malformed; sample {self.sample}")


class _CountySilent:
    name = "top80-sweep-county-silent"

    def __init__(self) -> None:
        self.owners: Counter = Counter()
        self.stamped: Counter = Counter()
        self.any_stamp = 0
        try:
            from foreclosure_scraper.enrichment_county_lien_sweep import SWEEP_COUNTIES
            self.required = {k for k, jobs in SWEEP_COUNTIES.items() if any(j.kind == "lien" for j in jobs)}
        except Exception:  # noqa: BLE001 - reported by the config check
            self.required = set()

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        s = raw.get("rod_lien_sweep")
        if isinstance(s, dict) and s.get("platform") in LIEN_LABELS:
            self.any_stamp += 1
        key = _county_key(row)
        if key not in self.required or not (row.get("owner_name") or "").strip():
            return
        self.owners[key] += 1
        if isinstance(s, dict) and s.get("platform") in LIEN_LABELS:
            self.stamped[key] += 1

    def finish(self) -> dict:
        judged = sorted(k for k in self.required if self.owners[k] >= MIN_OWNERS)
        if not self.any_stamp:
            return _result(self.name, len(judged), 0, 0,
                           f"not run yet: no row carries this group's sweep stamp ({len(judged)} counties will be judged)")
        silent = sorted(f"{s} {c}" for s, c in judged if self.stamped[(s, c)] == 0)
        return _result(self.name, len(judged), len(silent), 0,
                       f"{len(judged)} swept counties with >= {MIN_OWNERS} owner rows; none stamped: {silent}; "
                       f"stamped rows {sum(self.stamped.values())}")


class _MarriageShape:
    name = "top80-marriage-sweep-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0

    def feed(self, row: dict) -> None:
        ml = _raw(row).get("marriage_license")
        if not isinstance(ml, dict) or ml.get("source") != MARRIAGE_LABEL:
            return
        self.checked += 1
        if ml.get("status") == "no_match":
            ok = bool(ml.get("checked_at") and ml.get("window_from") and ml.get("window_to"))
        else:
            ok = bool(ml.get("status") in ("found", "possible") and ml.get("spouse_name") and ml.get("license_date"))
        self.bad += 0 if ok else 1

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} Beaufort marriage-sweep rows; {self.bad} malformed")


class _ConfigConsistent:
    name = "top80-sweep-config-consistent"

    def feed(self, row: dict) -> None:   # configuration check: rows are not needed
        return

    def finish(self) -> dict:
        problems: list[str] = []
        n = 0
        try:
            from foreclosure_scraper import enrichment_county_lien_sweep as E
            from foreclosure_scraper import enrichment_generic_rod as g
            from foreclosure_scraper.rod import county_sweeps as CS
            for key, jobs in E.SWEEP_COUNTIES.items():
                n += 1
                if not jobs or any(j.kind not in ("lien", "marriage") for j in jobs):
                    problems.append(f"{key}: bad job list")
            for county, (host, slug) in CS.HOSTED_CCHS.items():
                n += 1
                if host not in ("us3", "us4", "us5") or not slug.endswith("NCNW"):
                    problems.append(f"hosted {county}: {host}/{slug}")
            for key in (("SC", "Sumter"), ("NC", "Beaufort")):
                n += 1
                entry = g.ROD_CONFIG.get(key)
                mod = g._get_module(entry[0]) if entry else None
                if mod is None or not hasattr(mod, "search_by_name_status"):
                    problems.append(f"{key[1]}: not in the generic registry with a status-reporting module")
        except Exception as exc:  # noqa: BLE001 - a broken import is itself the finding
            problems.append(f"import failed: {type(exc).__name__}: {str(exc)[:80]}")
        try:
            prof = json.loads((_REPO / "deploy/oracle/run_profile.json").read_text())
            env = prof.get("flags") or {}
            lib = (_REPO / "deploy/oracle/vm_lib.sh").read_text()
            for flag in GROUP_FLAGS:
                n += 1
                m = re.search(rf'{flag}="\$\{{{flag}:-(\d)\}}"', lib)
                if flag not in env or m is None or str(env[flag]) != m.group(1):
                    problems.append(f"{flag}: profile {env.get(flag)!r} vs vm_lib {m.group(1) if m else None!r}")
            n += 1
            main_src = (_REPO / "src/foreclosure_scraper/main.py").read_text()
            if "enrichment_county_lien_sweep" not in main_src and "enrichment_county_lien_sweep" not in (
                    prof.get("unwired_wire_pending") or {}):
                problems.append("enrichment_county_lien_sweep is neither in main.py nor in unwired_wire_pending")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"profile/vm_lib/main unreadable: {type(exc).__name__}")
        try:
            mx = {(c["state"], c["county"]): c for c in json.loads(
                (_REPO / "docs/county_records/county_records_matrix.json").read_text())["counties"]}
            for (st, co), val in MARRIAGE_VERDICTS.items():
                n += 1
                have = ((mx.get((st, co)) or {}).get("rod") or {}).get("column_access", {}).get("marriage_license")
                if have != val:
                    problems.append(f"matrix {co} marriage_license: {have!r} != {val!r}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"matrix unreadable: {type(exc).__name__}")
        return _result(self.name, n, len(problems), 0, "; ".join(problems) or f"{n} configuration items agree")


def make_checks() -> list:
    return [_StampShape(), _CountySilent(), _MarriageShape(), _ConfigConsistent()]
