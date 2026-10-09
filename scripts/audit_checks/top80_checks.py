"""Top-80 'check' group invariants (2026-10-09): the tax-roll family (ITSPublic portals), the NC OneMap
heir_estate and present-use sweeps, and the verdicts that close the rest of the group.

Each check would have caught a defect this group measured or closes a cell the cube reported:
  top80-its-roll-shape         a raw['nc_its_public_tax'] block that contradicts itself: is_two_year_plus
                               not equal to "two or more distinct delinquent years", years not ascending,
                               a county that is not a configured portal, a row with neither a parcel id nor
                               a street address (an unplaceable lead), a tax_owed balance that is not the
                               block's total. The 10 counties of the newer ITS build print their bills in
                               three different cell layouts; a parser that mis-reads one shows up here.
  top80-its-county-silent      a configured ITSPublic county with no row on the board while the board holds
                               ITS rows at all: the portal answered the probe on 2026-10-09 (400 bills in
                               10 counties) so a silent county is a parser or session regression. Needs
                               MIN_TOTAL ITS rows before it judges (a tail run without the roll is not it).
  top80-onemap-heir-shape      raw['heir_estate'] stamped by the OneMap sweep (source nc_onemap_sweep) whose
                               owner_of_record carries neither HEIR nor ESTATE, or names a LIFE ESTATE /
                               REAL ESTATE / ESTATES holder (the exclusions the scraper applies).
  top80-onemap-flag-shape      raw['rollback_exposure'] stamped from the present-use flag (basis
                               present_use_flag) that carries a dollar figure it cannot know, a state other
                               than NC, or a missing source_key.
  top80-onemap-flag-share      in a county with at least MIN_COUNTY_ROWS NC rows with parcels, the share of
                               rows stamped from the present-use flag above MAX_SHARE: the layer's flag is
                               on nearly every parcel there (Johnston 99%, Rowan 99%, Wayne 97% on
                               2026-10-09) and the sweep's reliability rule failed to drop the county.
  top80-probate-match-shape    raw['probate_index_match'] (the Spartan decedent-index name fits of Greenwood,
                               Newberry and Calhoun) that is malformed: more than 3 entries, an entry without
                               a case number / a known level / one of the three counties, or a row outside
                               SC; and a raw['probate'] with source spartan_public_probate that names no case,
                               differs between case_number and es_case_number, or sits on a row with no
                               death signal (a name match alone must never write raw['probate']).
  top80-vacant-lot-shape       raw['vacant_lot'] stamped from the parcel cache whose land_use text names no
                               vacant / undeveloped parcel (the stamp is the VACANT / UNDEVELOPED regex of
                               enrichment_vacant_landuse; the county's class code alone is not a vacant lot).
  top80-checks-config          repo configuration, not rows: the ITS portals and the unreadable-portal
                               verdicts are disjoint and cover the 15 counties probed, the tax_lien
                               verifier (tax_lien_itspublic) holds the six parcel-bearing newer-build
                               counties, the screen ledger knows the ITS source and the OneMap
                               enrichment, the sweep's reliability threshold is at most 0.25, and the
                               run profile lists the group's enrichment.

Memory: a few counters and county-name samples.
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
MIN_TOTAL = 500
MIN_COUNTY_ROWS = 40
MAX_SHARE = 0.60
_HEIR = re.compile(r"\bHEIRS?\b|\bESTATE\b", re.I)
_EXCLUDED = re.compile(r"LIFE ESTATE|REAL ESTATE|ESTATES", re.I)

#: the ten counties of the newer ITS build plus the two the first build read
ITS_COUNTIES = ("Onslow", "Graham", "Alleghany", "Anson", "Caswell", "Duplin", "Granville", "Harnett",
                "Jones", "Person", "Scotland", "Yadkin")
#: counties on the vendor probed on 2026-10-09 that cannot be read, with the reason in the module
UNREADABLE = ("Clay", "Swain", "Surry", "Warren", "Gates")


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _result(name: str, checked: int, violations: int, max_v: int, detail: str) -> dict:
    return {"name": name, "checked": checked, "violations": violations, "max_violations": max_v,
            "ok": violations <= max_v, "detail": detail}


class _ItsShape:
    name = "top80-its-roll-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.why: Counter = Counter()
        self.sample: list[str] = []
        try:
            from foreclosure_scraper.scrapers.counties_nc import nc_its_public_tax as M
            self.portals = set(M.PORTALS)
        except Exception:  # noqa: BLE001 - the config check reports an unimportable module
            self.portals = set(ITS_COUNTIES)

    def _flag(self, row: dict, why: str) -> None:
        self.bad += 1
        self.why[why] += 1
        if len(self.sample) < SAMPLE:
            self.sample.append(f"{row.get('county')}:{why}")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        blk = raw.get("nc_its_public_tax")
        if not isinstance(blk, dict):
            return
        self.checked += 1
        years = blk.get("years") or []
        two = raw.get("two_year_delinquent") or {}
        if blk.get("county") not in self.portals:
            self._flag(row, "county_not_a_portal")
        if list(years) != sorted(set(years)):
            self._flag(row, "years_not_ascending_distinct")
        if bool(blk.get("is_two_year_plus")) != (len(set(years)) >= 2):
            self._flag(row, "two_year_flag_contradicts_years")
        if isinstance(two, dict) and two and bool(two.get("is_two_year_plus")) != bool(blk.get("is_two_year_plus")):
            self._flag(row, "published_flag_differs_from_block")
        if not (row.get("parcel_id") or row.get("street_address")):
            self._flag(row, "no_parcel_and_no_street")
        owed = raw.get("tax_owed")
        if isinstance(owed, dict) and blk.get("total_due") and owed.get("source") == "counties_nc.nc_its_public_tax":
            if abs(float(owed.get("balance") or 0) - float(blk["total_due"])) > 0.01:
                self._flag(row, "tax_owed_differs_from_total_due")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} ITS roll blocks; {self.bad} contradictions {dict(self.why)}; sample {self.sample}")


class _ItsSilent:
    name = "top80-its-county-silent"

    def __init__(self) -> None:
        self.rows: Counter = Counter()

    def feed(self, row: dict) -> None:
        blk = _raw(row).get("nc_its_public_tax")
        if isinstance(blk, dict) and blk.get("county"):
            self.rows[blk["county"]] += 1

    def finish(self) -> dict:
        total = sum(self.rows.values())
        if total < MIN_TOTAL:
            return _result(self.name, total, 0, 0, f"{total} ITS rows (< {MIN_TOTAL}): the roll was not part of this board")
        silent = sorted(c for c in ITS_COUNTIES if self.rows[c] == 0)
        return _result(self.name, len(ITS_COUNTIES), len(silent), 0,
                       f"{total} ITS rows; counties with none: {silent}; per county {dict(sorted(self.rows.items()))}")


class _HeirShape:
    name = "top80-onemap-heir-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        he = _raw(row).get("heir_estate")
        if not isinstance(he, dict) or he.get("source") != "nc_onemap_sweep":
            return
        self.checked += 1
        owner = str(he.get("owner_of_record") or "")
        if not _HEIR.search(owner) or _EXCLUDED.search(owner):
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(f"{row.get('county')}")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} sweep-stamped heir_estate rows; {self.bad} not decedent-titled; sample {self.sample}")


class _FlagShape:
    name = "top80-onemap-flag-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def feed(self, row: dict) -> None:
        rb = _raw(row).get("rollback_exposure")
        if not isinstance(rb, dict) or rb.get("basis") != "present_use_flag":
            return
        self.checked += 1
        ok = (rb.get("deferred_value") is None and rb.get("estimated_rollback") is None
              and rb.get("state") == "NC" and rb.get("source_key") == "nc_onemap_presentval"
              and str(row.get("state") or "").upper() == "NC")
        if not ok:
            self.bad += 1
            if len(self.sample) < SAMPLE:
                self.sample.append(f"{row.get('state')}|{row.get('county')}")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} present-use-flag rows; {self.bad} malformed (a flag carries no dollar figure); sample {self.sample}")


class _FlagShare:
    name = "top80-onemap-flag-share"

    def __init__(self) -> None:
        self.rows: Counter = Counter()
        self.flagged: Counter = Counter()

    def feed(self, row: dict) -> None:
        if str(row.get("state") or "").upper() != "NC" or not row.get("parcel_id"):
            return
        county = str(row.get("county") or "").strip()
        self.rows[county] += 1
        rb = _raw(row).get("rollback_exposure")
        if isinstance(rb, dict) and rb.get("basis") == "present_use_flag":
            self.flagged[county] += 1

    def finish(self) -> dict:
        judged = [c for c, n in self.rows.items() if n >= MIN_COUNTY_ROWS]
        bad = sorted(f"{c} {self.flagged[c]}/{self.rows[c]}" for c in judged if self.flagged[c] / self.rows[c] > MAX_SHARE)
        return _result(self.name, len(judged), len(bad), 0,
                       f"{len(judged)} NC counties with >= {MIN_COUNTY_ROWS} parcel rows; flag on more than "
                       f"{MAX_SHARE:.0%} of them: {bad}; flagged rows {sum(self.flagged.values())}")


_DEATH = re.compile(r"\bHEIRS?\b|\bESTATE\b|\bDECEASED\b|\bDEC'?D\b", re.I)
_LEVELS = ("full", "middle_initial", "given_surname")
SPARTAN_COUNTIES = ("Greenwood", "Newberry", "Calhoun")


class _ProbateShape:
    name = "top80-probate-match-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0
        self.sample: list[str] = []

    def _flag(self, row: dict, why: str) -> None:
        self.bad += 1
        if len(self.sample) < SAMPLE:
            self.sample.append(f"{row.get('county')}:{why}")

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        m = raw.get("probate_index_match")
        pr = raw.get("probate")
        spartan_pr = isinstance(pr, dict) and pr.get("source") == "spartan_public_probate"
        if m is None and not spartan_pr:
            return
        self.checked += 1
        if m is not None:
            if not isinstance(m, list) or not m or len(m) > 3:
                self._flag(row, "match_list_shape")
            else:
                for e in m:
                    if not (isinstance(e, dict) and e.get("case_number") and e.get("level") in _LEVELS
                            and e.get("county") in SPARTAN_COUNTIES):
                        self._flag(row, "match_entry_shape")
                        break
            if str(row.get("state") or "").upper() != "SC":
                self._flag(row, "not_sc")
        if spartan_pr:
            if not pr.get("case_number") or pr.get("case_number") != pr.get("es_case_number"):
                self._flag(row, "probate_case_number")
            owners = " ".join(str(x) for x in (row.get("owner_name"), (raw.get("gis") or {}).get("owner")
                                               if isinstance(raw.get("gis"), dict) else "") if x)
            corroborated = (_DEATH.search(owners) or raw.get("heir_estate") or raw.get("sc_probate_notice")
                            or raw.get("heir_naming_publication") or raw.get("sc_probate_net")
                            or str(row.get("listing_type") or "").endswith("probate_notice"))
            if not corroborated:
                self._flag(row, "probate_without_death_signal")

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} Spartan probate rows; {self.bad} malformed or uncorroborated; sample {self.sample}")


_VACANT = re.compile(r"\b(VACANT|UNDEVELOPED)\b", re.I)


class _VacantShape:
    name = "top80-vacant-lot-shape"

    def __init__(self) -> None:
        self.checked = self.bad = 0

    def feed(self, row: dict) -> None:
        vl = _raw(row).get("vacant_lot")
        if not isinstance(vl, dict) or vl.get("source") != "parcel_cache_landuse":
            return
        self.checked += 1
        if not _VACANT.search(str(vl.get("land_use") or "")):
            self.bad += 1

    def finish(self) -> dict:
        return _result(self.name, self.checked, self.bad, 0,
                       f"{self.checked} parcel-cache vacant_lot stamps; {self.bad} whose land use is not vacant/undeveloped")


class _Config:
    name = "top80-checks-config"

    def feed(self, row: dict) -> None:
        return

    def finish(self) -> dict:
        bad: list[str] = []
        try:
            from foreclosure_scraper import enrichment_onemap_sweeps as S
            from foreclosure_scraper import screen_ledger as SL
            from foreclosure_scraper.scrapers.counties_nc import nc_its_public_tax as M
            if set(M.PORTALS) & set(M.UNREADABLE_PORTALS):
                bad.append("a portal is also listed unreadable")
            if set(M.UNREADABLE_PORTALS) != set(UNREADABLE):
                bad.append("unreadable portal set changed")
            for c in ITS_COUNTIES:
                if c not in M.PORTALS:
                    bad.append(f"portal {c} missing")
            from foreclosure_scraper.verification.verifiers import tax_lien_itspublic as V
            for c in ("anson", "granville", "harnett", "yadkin", "alleghany", "scotland"):
                pt = V._BY_COUNTY.get(c)
                if pt is None or not pt.full_model:
                    bad.append(f"tax_lien_itspublic has no full-model portal for {c}")
            for c in ("caswell", "jones", "person"):
                if c in V._BY_COUNTY:
                    bad.append(f"tax_lien_itspublic must not bind {c} (no parcel id on its bills)")
            from foreclosure_scraper import enrichment_probate_spartan as PS
            if set(PS.PORTALS) != set(SPARTAN_COUNTIES):
                bad.append("Spartan probate portals changed")
            if SL.ENRICHMENT_SCREENS.get("probate_spartan") != ("probate",):
                bad.append("screen ledger does not know the Spartan probate screen")
            if S.MAX_FLAG_SHARE > 0.25:
                bad.append("present-use reliability threshold above 0.25")
            if set(SL.ENRICHMENT_SCREENS.get("onemap_sweeps", ())) != {"heir_estate", "rollback_exposure"}:
                bad.append("screen ledger does not know the OneMap sweeps")
            if not any(s.slug == "counties_nc.nc_its_public_tax" for s in SL.DECLARED):
                bad.append("screen ledger does not know the ITS source")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"import failed: {type(exc).__name__}: {str(exc)[:80]}")
        try:
            prof = json.loads((_REPO / "deploy" / "oracle" / "run_profile.json").read_text())
            pend = (prof.get("unwired_wire_pending") or {})
            for mod in ("enrichment_onemap_sweeps", "enrichment_probate_spartan"):
                if mod not in pend and mod not in json.dumps(prof):
                    bad.append(f"run_profile.json does not list {mod}")
            if (prof.get("flags") or {}).get("FORECLOSURE_PROBATE_SPARTAN") != "1":
                bad.append("run_profile flag FORECLOSURE_PROBATE_SPARTAN is not 1")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"run_profile unreadable: {str(exc)[:60]}")
        return _result(self.name, 1, len(bad), 0, "ok" if not bad else "; ".join(bad))


def make_checks() -> list:
    return [_ItsShape(), _ItsSilent(), _HeirShape(), _FlagShape(), _FlagShare(), _ProbateShape(), _VacantShape(), _Config()]
