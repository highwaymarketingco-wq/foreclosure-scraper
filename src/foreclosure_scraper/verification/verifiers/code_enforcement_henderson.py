"""code_enforcement, Henderson County NC: does the parcel have an OPEN code-enforcement case of a
category that is genuinely property distress, on the county's own Ordinance Violations Tracking
layer today?

Evolved from docs/validation_2026-10-02/scripts/validate_code_enforcement.py (FINDINGS.md
section 3, Finding A: of 49 sampled county-dashboard rows only 46.9% were vacancy-adjacent, the
majority a different category, mostly Zoning, riding the same flag; 12.2% already closed). The
layer, the open/closed rule, the PIN clean-up and the category rule are the scraper's own
(counties_nc.henderson_code_violations: LAYER, is_closed, _norm_pin, _SEVERE), so the verifier
and the pipeline cannot read a case differently.

THE SOURCE (live-checked 2026-10-06): OVT_PublicDashboard_View/FeatureServer/1, anonymous ArcGIS
Online, no login, no CAPTCHA. A renewing feed (editingInfo.dataLastEditDate 2026-10-05), history
back to 2001: 3,301 cases, maxRecordCount 2000. The whole layer is loaded ONCE per sweep run
(_arcgis_layer.layer_for: metadata, count, two pages), never per row. Columns read: OBJECTID,
caseID, dateReceived, violationType, PIN, dispositionStatus, dispositionDate, address. The
layer's parcelOwner column is never requested (the ledger is published in a PUBLIC repo); the
view has no complainant, inspector, phone or email column.

CATEGORY TAXONOMY (live-verified 2026-10-06, the layer's own coded domain and every value in the
data). Distress, the scraper's _SEVERE: Nuisance, Solid Waste, Junk yard / Junkyard, Vehicle
Graveyard, Manufactured Home Graveyard, Minimum Housing Complaint (/Rental Complaint). Not
distress: Zoning, the free-text "General", blank, and the one truncated "olid" row. The 181 open
cases that day: Nuisance 93, Zoning 38, Solid Waste 32, Junkyard 7, Vehicle Graveyard 5,
General 3, Manufactured Home Graveyard 2, Minimum Housing 1 (item 48 counted 182 on 2026-10-02
with the same shape). Open = a non-blank dispositionStatus the scraper's is_closed() does not
close (No Further Action, Resolved, Inactive, nfa, Refer...Authority); a blank status is a
placeholder record the scraper's own query drops, so it decides nothing here either.

WHICH ROWS (applies). NC Henderson rows whose raw['code_enforcement'] is the OVT block
(source "henderson_ordinance_violations_tracking") claiming an open case, whatever row source
carries it (the block also rides on merged flood-zone / UST rows).

MATCHING. The cases at the row's PIN (digits only; the county has tab-prefixed PINs), plus the
case ids the board block names (caseID is not unique: 132 blanks and a few repeats, so a claimed
id counts only at the row's own PIN, or when either side has no PIN), else the cases at the
row's house-numbered address (models._normalize_addr).

VERDICTS (core.py's meanings):
  confirmed    an open case of a distress category at the parcel today.
  stale        no open distress case, but a distress case there has been CLOSED, and the board
               claimed a distress category (or did not say which): the case resolved.
  refuted      the parcel's open (or closed) cases are all a non-distress category (Zoning,
               General): the claim never was distress ("category_not_distress"); or the claimed
               case is on a DIFFERENT parcel and this parcel has none ("case_on_other_parcel":
               the 2026-10-06 board carries such blocks on merged rows); or the whole, complete
               layer has no case for the parcel, the claimed ids or the address
               ("no_case_on_layer").
  unconfirmed  the layer failed, came back empty or incomplete; the row has no PIN, case id or
               numbered address; or only blank-status placeholder records match.

GOVERNS "code_enforcement:henderson_ordinance_violations_tracking", a partial rule read in both
distress_score._collect and enrichment_lead_signals._facet_signals (core.qualifiers): a refuted
or stale verdict ends the code_enforcement credit only where the row's code_enforcement block is
THIS source's. The ledger is keyed by property and two rows of one parcel share a verdict, so a
plain "code_enforcement" would also end another source's block on the same parcel (the
Hendersonville register, a Spartanburg condemnation). raw['distressed'] (the scraper sets it
with a distress category) is a bare flag with no provenance and is NOT governed: on a merged row
it may be another source's.

TTL 14 days, retry 3: cases move weekly (a 15-day notice, an owner resolving it).

EVIDENCE (whitelisted fields only, no names): the layer URL, fetched_at, layer count and last
data edit, the board's PIN and claimed case ids / categories, how it matched, and per matched
case (newest open first, at most 8): case id, category, distress, status, open, opened date and
closed date; for case_on_other_parcel the claimed case ids with the parcel (PIN) they are on.
ROW_SUMMARY_EXCLUDE drops owner_name from the ledger row summary: on these rows it IS the
layer's parcelOwner.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _arcgis_layer as agl

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
CE_SOURCE = "henderson_ordinance_violations_tracking"
SOURCE = "Henderson County OVT dashboard (services1.arcgis.com)"
GOVERNS = (f"code_enforcement:{CE_SOURCE}",)
ROW_SUMMARY_EXCLUDE = ("owner_name",)

#: The only columns requested (never parcelOwner).
OUT_FIELDS = ("OBJECTID,caseID,dateReceived,violationType,PIN,dispositionStatus,"
              "dispositionDate,address")
ORDER_BY = "OBJECTID ASC"
MAX_CASES_IN_EVIDENCE = 8

_NAME = __name__.rsplit(".", 1)[-1]


def _scraper():
    """counties_nc.henderson_code_violations, imported on first use (the registry imports every
    verifier; the scorer must not pull the scraper stack in)."""
    from ...scrapers.counties_nc import henderson_code_violations
    return henderson_code_violations


def layer() -> str:
    return _scraper().LAYER


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) and ce.get("source") == CE_SOURCE else None


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    if str(row.get("county") or "").strip().lower() != "henderson":
        return False
    ce = _block(row)
    return bool(ce and ce.get("has_open"))


# ---------------------------------------------------------------------------
# the layer, indexed once per snapshot
# ---------------------------------------------------------------------------

def _pin(v: Any) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _addr(v: Any) -> Optional[str]:
    from ...models import _normalize_addr
    from ..core import _house_numbered
    a = _normalize_addr(v) if v else None
    return a if a and _house_numbered(a) else None


def _index(snap: agl.LayerSnapshot) -> dict:
    idx = snap.cache.get("ovt")
    if idx is None:
        by_pin, by_case, by_addr = defaultdict(list), defaultdict(list), defaultdict(list)
        for a in snap.rows:
            if _pin(a.get("PIN")):
                by_pin[_pin(a.get("PIN"))].append(a)
            cid = str(a.get("caseID") or "").strip()
            if cid:
                by_case[cid].append(a)
            ad = _addr(a.get("address"))
            if ad:
                by_addr[ad].append(a)
        idx = snap.cache["ovt"] = {"pin": by_pin, "case": by_case, "addr": by_addr}
    return idx


def is_distress(category: Any) -> bool:
    return bool(_scraper()._SEVERE.search(str(category or "")))


def case_view(a: dict) -> dict:
    s = _scraper()
    status = str(a.get("dispositionStatus") or "").strip()
    is_open = bool(status) and not s.is_closed(status)
    out = {"case_id": str(a.get("caseID") or "").strip() or None,
           "category": str(a.get("violationType") or "").strip() or None,
           "distress": is_distress(a.get("violationType")),
           "status": status or None, "open": is_open,
           "opened": agl.epoch_date(a.get("dateReceived"))}
    if status and not is_open:
        out["closed"] = agl.epoch_date(a.get("dispositionDate"))
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ce = _block(row) or {}
    pin = _pin(row.get("parcel_id"))
    addr = _addr(row.get("street_address"))
    claimed_ids = []
    for v in ce.get("violations") or []:
        cid = str((v or {}).get("case_id") or "").strip() if isinstance(v, dict) else ""
        if cid and cid not in claimed_ids:
            claimed_ids.append(cid)
    claimed_types = [str(t) for t in ce.get("violation_types") or [] if t]
    ev: dict[str, Any] = {"board_pin": pin or None, "claimed_case_ids": claimed_ids,
                          "claimed_categories": claimed_types}

    snap = await agl.layer_for(client, layer(), out_fields=OUT_FIELDS, order_by=ORDER_BY)
    ev.update(snap.evidence())
    if not snap.complete:
        ev["reason"] = snap.health
        return _res("unconfirmed", ev)
    if not (pin or claimed_ids or addr):
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    idx = _index(snap)
    found: dict[Any, dict] = {}
    matched_by: list[str] = []
    elsewhere: list[dict] = []
    for a in idx["pin"].get(pin, []) if pin else []:
        found[a.get("OBJECTID")] = a
    if found:
        matched_by.append("pin")
    for cid in claimed_ids:
        for a in idx["case"].get(cid, []):
            ap = _pin(a.get("PIN"))
            if not pin or not ap or ap == pin:
                if a.get("OBJECTID") not in found:
                    found[a.get("OBJECTID")] = a
                    if "case_id" not in matched_by:
                        matched_by.append("case_id")
            else:
                elsewhere.append({"case_id": cid, "at_pin": ap})
    if not found and addr:
        for a in idx["addr"].get(addr, []):
            found[a.get("OBJECTID")] = a
        if found:
            matched_by.append("address")
    ev["matched_by"] = matched_by

    if not found:
        if elsewhere:
            ev["claimed_cases_elsewhere"] = elsewhere[:MAX_CASES_IN_EVIDENCE]
            ev["reason"] = "case_on_other_parcel"
        else:
            ev["reason"] = "no_case_on_layer"
        return _res("refuted", ev)

    views = [case_view(a) for a in found.values()]
    blank = sum(1 for v in views if not v.get("status"))
    cases = [v for v in views if v.get("status")]
    cases.sort(key=lambda v: v.get("opened") or "", reverse=True)
    cases.sort(key=lambda v: not v["open"])                     # open first, then newest first
    open_d = [c for c in cases if c["open"] and c["distress"]]
    open_o = [c for c in cases if c["open"] and not c["distress"]]
    closed_d = [c for c in cases if not c["open"] and c["distress"]]
    ev.update(cases=cases[:MAX_CASES_IN_EVIDENCE], cases_matched=len(cases),
              open_distress=len(open_d), open_other=len(open_o), closed_distress=len(closed_d))
    if blank:
        ev["blank_status_records"] = blank
    if elsewhere:
        ev["claimed_cases_elsewhere"] = elsewhere[:MAX_CASES_IN_EVIDENCE]

    if not cases:
        ev["reason"] = "status_blank"
        return _res("unconfirmed", ev)
    if open_d:
        return _res("confirmed", ev)
    claimed_distress = (not claimed_types) or any(is_distress(t) for t in claimed_types)
    if closed_d and claimed_distress:
        ev["reason"] = "case_closed"
        return _res("stale", ev)
    ev["reason"] = "category_not_distress"
    return _res("refuted", ev)
