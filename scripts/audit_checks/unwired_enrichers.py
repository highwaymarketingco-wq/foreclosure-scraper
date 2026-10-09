"""Unwired-enricher invariants (audit 2026-10-09, area unwired_enrichers): one per module the audit
wired into main.run_enrich_tail, plus one that catches a retired module being run again.

Each would have caught the defect class D11 (pipeline_gate): a key only a script wrote, frozen on
the board at an old value or missing on every row added since.
  unwired-dnc-every-phone-scrubbed   every phone on a row (owner_phone, skip_trace, free_phones,
                                     sc_voter_xref) has a raw['dnc_scrub'] entry (enrichment_dnc)
  unwired-dnc-status-valid           every entry's status is one the scrub writes, 'registered' (the
                                     old name) is gone, and no 'clear' is older than 31 days
  unwired-dnc-call-ready-agrees      no call_ready tier A/B on a row whose owner phone is on the
                                     registry, the company list or blocked
  unwired-flood-zone-mirrors-flood   flood_zone says what raw['flood'] (the run's FEMA read) says
  unwired-hud-fmr-matches-table      the row carries the FMR the cached HUD table gives its county
                                     and bedroom count (skipped when the table is not on this host)
  unwired-septic-current             a Buncombe septic block carries checked_at no older than 14 days;
                                     land_distress only beside a septic block that says so
  unwired-property-category-present  every row has the dashboard's property category
  unwired-property-category-current  a 1-in-50 sample recomputed agrees with the published category
  unwired-source-consistency-flags   the row-local self-contradiction checks that fire carry their
                                     qa_flag (enrich_board_qa reassigns qa_flags; the tail re-adds)
  unwired-bt-card-applied            a parsed appraisal card's heated sqft reached living_sqft
  unwired-wetlands-shape             raw['wetlands'] is the wired shape {has_wetlands, checked_at}
  unwired-retired-keys-not-growing   a retired module's key on no more rows than the 10/7 board had
                                     (a retired script was run by hand)
Memory: counters and at most SAMPLE parcel ids per check (parcel ids are public record).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8
RESCRUB_DAYS = 31            # enrichment_dnc.RESCRUB_DAYS (pinned by tests/test_audit_checks_unwired_enrichers.py)
SEPTIC_MAX_AGE_DAYS = 14     # the weekly layer refresh, plus a missed run
DNC_STATUSES = frozenset({"clear", "on_registry", "on_internal_dnc", "unverified", "do_not_dial",
                          "not_owner_contact"})
DNC_BLOCKED = frozenset({"on_registry", "registered", "on_internal_dnc", "do_not_dial", "not_owner_contact"})
#: (deed and marriage_license left this list 2026-10-09: live writers again, f6ccb681)
#: rows carrying each retired key on the 10/7 board (350,013 rows, docs/audit_2026-10-09/unwired_enrichers.md)
RETIRED_KEY_BASELINE = {
    "ocr_extraction": 2220, "lexington_assessment": 1159, "rod_name_index": 7,
    "bankruptcy_petition": 0, "block_group": 0, "building_value_assessed": 0, "campaign_queue": 0,
    "census_tract": 0, "contact": 0, "crime_stats": 0, "deficiency_amount": 0, "economic": 0,
    "housing_market": 0, "land_value_assessed": 0, "market_stats": 0, "nearby_facilities": 0,
    "standardized_address": 0, "state_fips": 0, "tax_bill_url": 0, "workflow_status": 0,
    "workflow_status_at": 0, "workflow_tags": 0,
}


def _raw(row: dict) -> dict:
    r = row.get("raw") if isinstance(row, dict) else None
    return r if isinstance(r, dict) else {}


def _ident(row: dict) -> str:
    return str(row.get("parcel_id") or row.get("case_number") or row.get("source") or "?")[:40]


def _age_days(iso: Any, now: datetime) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 86400.0


def _phone10(v: Any) -> Optional[str]:
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


def row_phones(raw: dict) -> set[str]:
    """The phones enrichment_dnc._get_phone_records reads, as 10 digits."""
    out: set[str] = set()
    op = raw.get("owner_phone")
    if isinstance(op, dict):
        p = _phone10(op.get("phone"))
        if p and op.get("phone"):
            out.add(p)
    st = raw.get("skip_trace")
    if isinstance(st, dict):
        out |= {p for p in map(_phone10, st.get("phone_numbers") or []) if p}
    fp = raw.get("free_phones")
    if isinstance(fp, list):
        out |= {p for p in (_phone10(e.get("phone")) for e in fp if isinstance(e, dict)) if p}
    sx = raw.get("sc_voter_xref")
    if isinstance(sx, dict):
        p = _phone10(sx.get("phone"))
        if p:
            out.add(p)
    return out


class _Check:
    name = "unwired-base"
    max_violations = 0
    describe = ""

    def __init__(self) -> None:
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: dict[str, int] = {}
        self.now = datetime.now(timezone.utc)
        self.note = ""

    def set_source(self, kind: str, path: Any) -> None:
        """The board's own time (its run_time / the checkpoint's saved_at), so ages are judged as of
        the board, not as of the day the suite runs."""
        p = Path(path)
        man = (p if p.is_dir() else p.parent) / ("board.manifest.json" if kind == "board" else "manifest.json")
        try:
            m = json.loads(man.read_text())
            t = m.get("run_time") or m.get("saved_at") or m.get("written_at")
            if t:
                d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                self.now = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except (OSError, ValueError):
            pass

    def _bad(self, row: dict, why: str = "") -> None:
        self.violations += 1
        if why:
            self.by[why] = self.by.get(why, 0) + 1
        if len(self.samples) < SAMPLE:
            self.samples.append(f"{row.get('county') or '?'}:{_ident(row)}" + (f"({why})" if why else ""))

    def finish(self) -> dict:
        parts = [self.describe, self.note]
        if self.by:
            parts.append("by: " + ", ".join(f"{k} {v}" for k, v in sorted(self.by.items(), key=lambda kv: -kv[1])[:8]))
        if self.samples:
            parts.append("e.g. " + "; ".join(self.samples))
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations,
                "ok": self.violations <= self.max_violations, "detail": " | ".join(p for p in parts if p)}


class DncEveryPhone(_Check):
    name = "unwired-dnc-every-phone-scrubbed"
    describe = "every phone on a row has a dnc_scrub entry (enrichment_dnc in the tail, line UE1)"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        phones = row_phones(raw)
        if not phones:
            return
        self.checked += 1
        have = {_phone10(e.get("phone")) for e in raw.get("dnc_scrub") or [] if isinstance(e, dict)} \
            if isinstance(raw.get("dnc_scrub"), list) else set()
        if not have:
            self._bad(row, "no dnc_scrub")
        elif phones - have:
            self._bad(row, "a phone without an entry")


class DncStatusValid(_Check):
    name = "unwired-dnc-status-valid"
    describe = "dnc_scrub statuses are the scrub's own, no 'registered' (old name), no clear older than 31 days"

    def feed(self, row: dict) -> None:
        sc = _raw(row).get("dnc_scrub")
        if not isinstance(sc, list) or not sc:
            return
        self.checked += 1
        for e in sc:
            if not isinstance(e, dict):
                self._bad(row, "entry not a dict")
                return
            st = e.get("dnc_status")
            if st not in DNC_STATUSES:
                self._bad(row, f"status {st!r}")
                return
            if st == "clear":
                age = _age_days(e.get("scrubbed_at"), self.now)
                if age is None or age > RESCRUB_DAYS:
                    self._bad(row, "clear older than 31 days")
                    return
                if e.get("dnc_registered") is not False:
                    self._bad(row, "clear without a registry answer")
                    return


class DncCallReadyAgrees(_Check):
    name = "unwired-dnc-call-ready-agrees"
    describe = "no call_ready tier A/B on a row whose owner phone is on a do-not-call list or blocked"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        cr = raw.get("call_ready")
        if not isinstance(cr, dict) or cr.get("tier") not in ("A", "B"):
            return
        self.checked += 1
        op = raw.get("owner_phone")
        p = _phone10(op.get("phone")) if isinstance(op, dict) else None
        for e in raw.get("dnc_scrub") or [] if isinstance(raw.get("dnc_scrub"), list) else []:
            if isinstance(e, dict) and p and _phone10(e.get("phone")) == p and e.get("dnc_status") in DNC_BLOCKED:
                self._bad(row, f"tier {cr.get('tier')} with {e.get('dnc_status')}")
                return


class FloodZoneMirror(_Check):
    name = "unwired-flood-zone-mirrors-flood"
    describe = "raw['flood_zone'] says what raw['flood'] says (mirrored in the tail, line UE1)"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        fl = raw.get("flood")
        if not (isinstance(fl, dict) and str(fl.get("zone") or "").strip() not in ("", "?")):
            return
        self.checked += 1
        fz = raw.get("flood_zone")
        if not isinstance(fz, dict):
            self._bad(row, "no flood_zone")
        elif str(fz.get("zone") or "").upper() != str(fl.get("zone")).strip().upper():
            self._bad(row, "zone differs")
        elif bool(fz.get("in_sfha")) != bool(fl.get("in_sfha") or fl.get("sfha_tf")):
            self._bad(row, "in_sfha differs")


class HudFmrMatchesTable(_Check):
    name = "unwired-hud-fmr-matches-table"
    describe = "the row's hud_fmr is what the cached HUD table gives its county and bedrooms (line UE1)"

    def __init__(self) -> None:
        super().__init__()
        self.table = None
        try:
            from foreclosure_scraper.enrichment_tail_extras import load_fmr_table
            self.table = load_fmr_table()
        except Exception as exc:  # noqa: BLE001
            self.note = f"FMR table unreadable here: {type(exc).__name__}"
        if self.table is None and not self.note:
            self.note = "no FMR table on this host (data/fmr_cache/fmr_by_county.json): not checked"

    def feed(self, row: dict) -> None:
        if not self.table:
            return
        from foreclosure_scraper.enrichment_hud_fmr import _pick_fmr
        from foreclosure_scraper.enrichment_tail_extras import fmr_for
        rent = fmr_for(str(row.get("state") or ""), str(row.get("county") or ""), self.table)
        if not rent:
            return
        self.checked += 1
        try:
            beds = int(row.get("bedrooms")) if row.get("bedrooms") else None
        except (TypeError, ValueError):
            beds = None
        want = _pick_fmr(rent, beds)
        got = _raw(row).get("hud_fmr")
        if not isinstance(got, dict):
            self._bad(row, "no hud_fmr")
        elif want and got.get("fmr_monthly") != want.get("fmr_monthly"):
            self._bad(row, "another FMR")


class SepticCurrent(_Check):
    name = "unwired-septic-current"
    describe = "a septic block carries checked_at no older than 14 days; land_distress only beside an adverse block"

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        sp, ld = raw.get("septic"), raw.get("land_distress")
        if sp is None and not ld:
            return
        self.checked += 1
        if ld and not (isinstance(sp, dict) and sp.get("land_distress")):
            self._bad(row, "land_distress without an adverse septic block")
            return
        if isinstance(sp, dict):
            age = _age_days(sp.get("checked_at"), self.now)
            if age is None:
                self._bad(row, "septic without checked_at")
            elif age > SEPTIC_MAX_AGE_DAYS:
                self._bad(row, "septic older than 14 days")


class PropertyCategoryPresent(_Check):
    name = "unwired-property-category-present"
    describe = "every row has raw['property_category'] (the dashboard's category filter; line UE3)"

    def feed(self, row: dict) -> None:
        self.checked += 1
        pc = _raw(row).get("property_category")
        if not (isinstance(pc, dict) and pc.get("category")):
            self._bad(row, "no property_category")


class PropertyCategoryCurrent(_Check):
    name = "unwired-property-category-current"
    describe = "a 1-in-50 sample recomputed (enrichment_property_category) agrees with the published category"
    EVERY = 50

    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def feed(self, row: dict) -> None:
        self.n += 1
        pc = _raw(row).get("property_category")
        if self.n % self.EVERY or not isinstance(pc, dict):
            return
        from foreclosure_scraper.enrichment_property_category import _categorize
        from foreclosure_scraper.models import Listing
        try:
            li = Listing.model_validate(row)
        except Exception:  # noqa: BLE001 - a row the model refuses is another check's business
            return
        self.checked += 1
        want = _categorize(li) or {}
        if (want.get("category"), want.get("subcategory")) != (pc.get("category"), pc.get("subcategory")):
            self._bad(row, f"{pc.get('category')} -> {want.get('category')}"
                      if want.get("category") != pc.get("category") else "subcategory differs")


class SourceConsistencyFlags(_Check):
    name = "unwired-source-consistency-flags"
    describe = "a row-local self-contradiction (URL city vs city, land use vs kind) carries its qa_flag (line UE3)"

    def feed(self, row: dict) -> None:
        from foreclosure_scraper import enrichment_source_consistency as S
        found = []
        if S.url_city_conflict(row.get("source_url"), row.get("city"), row.get("county")):
            found.append(S.URL_CITY_CONFLICT)
        if S.land_use_kind_conflict(row.get("property_kind"), row.get("land_use")):
            found.append(S.LAND_USE_KIND_CONFLICT)
        if not found:
            return
        self.checked += 1
        flags = _raw(row).get("qa_flags")
        flags = set(map(str, flags)) if isinstance(flags, list) else set()
        missing = [f for f in found if f not in flags]
        if missing:
            self._bad(row, missing[0])


class BtCardApplied(_Check):
    name = "unwired-bt-card-applied"
    describe = "a parsed appraisal card's heated sqft reached living_sqft (line UE2)"

    def feed(self, row: dict) -> None:
        bt = _raw(row).get("bt_appraisal_card")
        if not isinstance(bt, dict) or not bt.get("heated_sqft"):
            return
        self.checked += 1
        if not row.get("living_sqft"):
            self._bad(row, "card sqft not on the row")


class WetlandsShape(_Check):
    name = "unwired-wetlands-shape"
    describe = "raw['wetlands'] is the wired block {has_wetlands, features, checked_at} (line UE4)"

    def feed(self, row: dict) -> None:
        w = _raw(row).get("wetlands")
        if w is None:
            return
        self.checked += 1
        if not isinstance(w, dict):
            self._bad(row, "old list shape")
        elif not isinstance(w.get("has_wetlands"), bool) or not w.get("checked_at"):
            self._bad(row, "no has_wetlands / checked_at")


class RetiredKeysNotGrowing(_Check):
    name = "unwired-retired-keys-not-growing"
    describe = "no retired module's key on more rows than the 10/7 board had (a retired script was run)"

    def __init__(self) -> None:
        super().__init__()
        self.counts = {k: 0 for k in RETIRED_KEY_BASELINE}

    def feed(self, row: dict) -> None:
        raw = _raw(row)
        self.checked += 1
        for k in self.counts:
            v = raw.get(k)
            if v not in (None, "", [], {}):
                self.counts[k] += 1

    def finish(self) -> dict:
        grew = {k: (n, RETIRED_KEY_BASELINE[k]) for k, n in self.counts.items() if n > RETIRED_KEY_BASELINE[k]}
        self.violations = len(grew)
        self.by = {f"{k} {n} > {b}": 1 for k, (n, b) in grew.items()}
        return super().finish()


def make_checks() -> list:
    return [DncEveryPhone(), DncStatusValid(), DncCallReadyAgrees(), FloodZoneMirror(), HudFmrMatchesTable(),
            SepticCurrent(), PropertyCategoryPresent(), PropertyCategoryCurrent(), SourceConsistencyFlags(),
            BtCardApplied(), WetlandsShape(), RetiredKeysNotGrowing()]
