"""Buncombe County NC septic-permit status — a land-buildability distress signal.

WHY THIS EXISTS
    In Buncombe County almost nothing outside the Asheville sewer district can be
    built or re-occupied without an on-site wastewater (septic) permit. The permit
    file is therefore a buildability record: it says whether the county has agreed
    that this dirt can carry a drainfield. No competitor in this market reads it.

    Two things it tells us that no other source on the board does:

    * A lot whose septic application was **terminated** (revoked / suspended /
      cancelled / cited) cannot be built on as the owner planned. On raw land that
      is close to a total loss of the owner's thesis — they bought to build, the
      soil said no, and they are now sitting on a carrying cost with no exit.
    * A lot whose application has been **sitting unissued for years** is the same
      story told more quietly: the file was opened, the evaluation never closed,
      and nothing was ever permitted.

    Both are the *reason* a piece of land becomes a motivated-seller lead. We tag
    it so a land offer can be priced against a known buildability problem instead
    of guessing.

SOURCE
    https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/
        Buncombe%20County%20Septic%20Data/FeatureServer/0
    Anonymous ArcGIS REST, no key, no login, no CAPTCHA/WAF, no robots Disallow
    (the host serves no robots.txt). 80,370 rows measured 2026-08-03, one row per
    permit CASE — a parcel can hold many cases across 20+ years.

STATUS SEMANTICS (measured, not assumed)
    The layer's ``LatestStatus`` vocabulary is 40 values. There is **no** literal
    "FAILED", "EXPIRED" or "DENIED" status in this dataset — Buncombe expresses
    those outcomes with the terms below. Measured counts over all 80,370 rows:

    TERMINAL / ADVERSE — the county ended the file against the applicant (76 rows):
        Cancelled (31), Revoked (26), Permit Suspended (15),
        Notice of Violation (2), S15 - Notice of Violation (1),
        S-30B NOI Deemed Incomplete (1)

    OPEN / UNRESOLVED — a file exists but nothing has been permitted (5,067 rows):
        Received (4,484), Completeness Review Approved (376), Hold (110),
        Awaiting Payment (89), OPC (5), ATC (2), Open (1)
        Of these, 4,098 have not moved in 3+ years.

    FAVOURABLE — the county said yes; these CLEAR a prior adverse/open state:
        every "* Issued" (OP/IP/AC/CA/COC/COCIP), "Authorization to Operate",
        "Finaled", "* Approved", "NOI Complete", "Ex System Approved".

    SUPERSESSION IS THE WHOLE GAME. A 2003 "Cancelled" on a parcel that got an
    "OP Issued" in 2019 is not distress — it is a permit that was refiled and
    granted. So the classifier works on the parcel's **latest-dated record**,
    not on "has this parcel ever had a bad status". Ignoring that would have
    called 100+ perfectly good parcels distressed.

    ``SubType`` carries a second, softer signal: REPAIR / SEPTIC REPAIR / REPAIR
    AUTHORIZATION (7,895 rows) means an EXISTING system failed and had to be
    rebuilt. That is a real deferred-maintenance tell on an improved property,
    but it is common and often long-resolved, so it is recorded as history only
    and never on its own marks a listing distressed.

JOIN
    On ``ParcelNum``, through :func:`models._normalize_parcel` — the layer stores
    the 10-digit Buncombe PIN zero-padded to 15 ("961879632600000"), which is
    exactly the pad the shared normalizer collapses. 48,948 of 80,370 rows carry
    a ParcelNum (31,422 do not and are unusable); those resolve to 34,678 distinct
    parcels.

COUNTY-WIDE, after supersession (34,678 parcels, measured 2026-08-04)
        27 parcels whose LATEST status is terminal/adverse
     3,109 parcels whose LATEST status is an unresolved open file
     2,338 of those have not moved in 3+ years  -> septic_stalled
     6,180 parcels carry a REPAIR in their history
    31,542 parcels are in a favourable final state

MEASURED AGAINST THE LIVE BOARD (docs/listings.json, 25,552 rows, 2026-08-04)
    Buncombe rows 5,902, of which 5,170 carry a parcel_id.
        770 board parcels have any septic history at all
          1 board parcel's LATEST septic status is terminal/adverse
         86 board parcels sit in an aged-unresolved application
        249 board parcels have a septic REPAIR in their history
         87 board parcels get raw['land_distress'] (adverse OR stalled)
    The adverse count is deliberately reported as 1. County-wide only 27 parcels
    are currently in a terminal state, and the board covers a small slice of the
    county; this is a precise low-volume flag, not a volume source. The stalled
    lane is where the volume is, and it lands overwhelmingly on vacant land —
    situs values like "0 SHELTON BRANCH RD" and "99999 OLD RHYMER DR" are the
    county's own unaddressed-lot fillers.

PRIVACY
    Fields are enumerated explicitly — never ``outFields=*``. Everything taken
    (case number, parcel, owner of record, situs, status, dates, permit type) is
    a property/permit record field. This layer carries no phone, email, SSN, DL
    or DOB column, and none is requested.

Kill switch: ``FORECLOSURE_SEPTIC_STATUS_OFF=1``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog

from . import arcgis_webmap as agw
from .http_client import client
from .models import Listing, _normalize_parcel

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_SEPTIC_STATUS_OFF"

LAYER_URL = (
    "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
    "Buncombe%20County%20Septic%20Data/FeatureServer/0"
)

#: Human-readable landing page for the permit office (used for source_url notes).
PAGE_URL = "https://www.buncombecounty.org/governing/depts/environmental-health/"

#: Explicit field list — never '*'. See PRIVACY in the module docstring.
OUT_FIELDS = (
    "OBJECTID,CaseNumber,ParcelNum,ApplicationName,SitusAddress,SitusCity,"
    "SitusZip,OwnerName,ReceivedDate,LatestStatus,LatestStatusDate,"
    "PermitType,SubType"
)

_PAGE = 2000          # layer maxRecordCount
_MAX_RECORDS = 200000

#: The county ended the file against the applicant. This is the hard signal.
ADVERSE_STATUSES: frozenset[str] = frozenset({
    "Cancelled",
    "Revoked",
    "Permit Suspended",
    "Notice of Violation",
    "S15 - Notice of Violation",
    "S-30B NOI Deemed Incomplete",
})

#: A file is open but nothing has been permitted. Only counts as a signal once
#: it has gone stale (see STALE_DAYS) — a fresh "Received" is just a live
#: application, not distress.
OPEN_STATUSES: frozenset[str] = frozenset({
    "Received",
    "Completeness Review Approved",
    "Hold",
    "Awaiting Payment",
    "Open",
    "OPC",
    "ATC",
})

#: Substrings that mark a FAVOURABLE outcome. Matched case-insensitively against
#: the status text so the county's numbered variants ("S19A - OP Issued",
#: "W10 - COC Issued", "S-31 Authorization to Operate") are all covered without
#: enumerating 40 strings that drift every time they renumber their workflow.
_FAVOURABLE_MARKERS: tuple[str, ...] = (
    "issued", "authorization to operate", "finaled",
    "approved", "noi complete", "system approved",
)

#: An open file older than this is treated as abandoned rather than pending.
STALE_DAYS = 1095      # 3 years

#: SubType values that mean an EXISTING system failed and was rebuilt.
_REPAIR_RE = re.compile(r"\bREPAIR\b", re.I)


def classify_status(status: str | None) -> str:
    """One of 'adverse' | 'open' | 'favourable' | 'unknown'.

    Favourable is tested FIRST because several favourable statuses would
    otherwise be swallowed by a naive substring check, and because a status the
    county adds later that contains "Issued" should default to favourable rather
    than silently becoming 'unknown' and dropping a parcel out of the model.
    """
    s = (status or "").strip()
    if not s:
        return "unknown"
    # Explicit membership is authoritative. It must be tested BEFORE the
    # substring markers, because "Completeness Review Approved" contains
    # "approved" but is a mid-workflow acceptance of the paperwork — no permit
    # has been issued, the file is still open, and 3+ years of it is stalled.
    if s in ADVERSE_STATUSES:
        return "adverse"
    if s in OPEN_STATUSES:
        return "open"
    low = s.lower()
    if any(m in low for m in _FAVOURABLE_MARKERS):
        return "favourable"
    return "unknown"


def _epoch_ms_to_dt(v: Any) -> datetime | None:
    """ArcGIS esriFieldTypeDate -> aware UTC datetime. Rejects the 0/None nulls
    the county uses and anything outside a sane permit-era range."""
    if v in (None, "", 0):
        return None
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    if not (1950 <= dt.year <= 2100):
        return None
    return dt


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


#: Case numbers are ``SEP<yyyy>-<seq>`` / ``WEL<yyyy>-<seq>``.
_CASE_YEAR_RE = re.compile(r"^[A-Z]{2,4}(\d{4})-", re.I)


def _case_year(case_number: Any) -> int | None:
    """Year encoded in the case number, e.g. 'SEP1995-37781' -> 1995."""
    m = _CASE_YEAR_RE.match(str(case_number or "").strip())
    if not m:
        return None
    y = int(m.group(1))
    return y if 1950 <= y <= 2100 else None


def _record_date(attrs: dict) -> datetime | None:
    """Effective date of a permit record: the latest status move, else intake.

    5,250 of 80,370 rows carry the legacy AS400 null-date sentinel (1900-01-01),
    which :func:`_epoch_ms_to_dt` rejects. Those records are undated, not
    recent — see :func:`summarize_parcel` for how staleness falls back to the
    year in the case number so a 1995 file cannot masquerade as a live one.
    """
    return (_epoch_ms_to_dt(attrs.get("LatestStatusDate"))
            or _epoch_ms_to_dt(attrs.get("ReceivedDate")))


def index_by_parcel(features: Iterable[dict]) -> dict[str, list[dict]]:
    """Group raw ArcGIS features into {normalized parcel: [attributes, ...]}.

    Rows without a usable ParcelNum are dropped — 31,422 of 80,370 measured. They
    cannot be joined to a listing, and guessing a join off SitusAddress would
    attach a neighbour's failed septic to the wrong lead.
    """
    out: dict[str, list[dict]] = {}
    for f in features:
        a = f.get("attributes") if isinstance(f, dict) else None
        if not isinstance(a, dict):
            continue
        pid = _normalize_parcel(_clean(a.get("ParcelNum")))
        if not pid:
            continue
        out.setdefault(pid, []).append(a)
    return out


def summarize_parcel(records: list[dict], now: datetime | None = None) -> dict | None:
    """Fold every septic case at one parcel into a single signal dict.

    The parcel's state is the state of its NEWEST-dated record. A favourable
    record dated after an adverse one clears the adverse one — see SUPERSESSION
    in the module docstring.
    """
    if not records:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    dated = [(_record_date(a), a) for a in records]
    # Undated records sort oldest so they can never masquerade as the latest
    # state of the parcel; they still count toward history.
    dated.sort(key=lambda p: (p[0] is not None, p[0] or datetime.min.replace(tzinfo=timezone.utc)))
    latest_dt, latest = dated[-1]
    latest_status = _clean(latest.get("LatestStatus"))
    verdict = classify_status(latest_status)

    stale_days: int | None = None
    if latest_dt is not None:
        stale_days = max((now - latest_dt).days, 0)

    if verdict == "open" and stale_days is not None:
        aged_open = stale_days >= STALE_DAYS
    elif verdict == "open":
        # Undated open file (the 1900-01-01 AS400 sentinel). Fall back to the
        # year in the case number: an open application the county cannot even
        # date is abandoned, not pending. Only if the case number ALSO gives no
        # year do we decline to call it — never guess.
        cy = _case_year(latest.get("CaseNumber"))
        aged_open = bool(cy is not None and (now.year - cy) * 365 >= STALE_DAYS)
    else:
        aged_open = False

    repair_history = sum(1 for a in records if _REPAIR_RE.search(str(a.get("SubType") or "")))

    # An adverse record that has NOT been superseded — the headline signal.
    adverse_now = verdict == "adverse"
    # Any adverse in history, even if later cleared. Useful context on a lot that
    # needed three tries to perc; never on its own a distress call.
    adverse_ever = sum(1 for a in records if classify_status(_clean(a.get("LatestStatus"))) == "adverse")

    out: dict[str, Any] = {
        "county": "Buncombe",
        "source": "buncombe_county_septic_data",
        "cases": len(records),
        "latest_case": _clean(latest.get("CaseNumber")),
        "latest_status": latest_status,
        "latest_status_class": verdict,
        "latest_status_date": latest_dt.date().isoformat() if latest_dt else None,
        "days_since_last_action": stale_days,
        "permit_type": _clean(latest.get("PermitType")),
        "sub_type": _clean(latest.get("SubType")),
        "situs_address": _clean(latest.get("SitusAddress")),
        "situs_city": _clean(latest.get("SitusCity")),
        "owner_of_record": _clean(latest.get("OwnerName")),
        "adverse_records_ever": adverse_ever,
        "repair_records": repair_history,
        # --- the three flags callers actually read -------------------------
        # Terminal: the county revoked/suspended/cancelled/cited and nothing
        # favourable came after. The lot cannot be built as planned.
        "septic_adverse": adverse_now,
        # Aged-open: a file opened 3+ years ago that never produced a permit.
        "septic_stalled": aged_open,
        # An existing system has failed and been repaired at least once.
        "septic_repair_history": repair_history > 0,
    }
    # One rolled-up boolean so scoring code does not have to know the taxonomy.
    out["land_distress"] = bool(adverse_now or aged_open)
    return out


def _is_buncombe(li: Listing) -> bool:
    return (
        (li.state or "").upper() == "NC"
        and (li.county or "").replace(" County", "").strip().lower() == "buncombe"
    )


async def fetch_septic_records(http) -> list[dict]:
    """The whole layer, paginated. Field list is enumerated; geometry is not
    requested (the join is by parcel, and the layer has no geometry anyway)."""
    return await agw.query_features(
        http, LAYER_URL,
        where="1=1",
        out_fields=OUT_FIELDS,
        return_geometry=False,
        page=_PAGE,
        max_records=_MAX_RECORDS,
        order_by="OBJECTID ASC",
        timeout=60.0,
    )


async def enrich_with_septic_status(listings: list[Listing]) -> dict | None:
    """Attach ``raw['septic']`` to Buncombe listings with a parcel id.

    Returns a stats dict for the run report, or None when there was nothing to
    do. Never raises — a dead layer costs the signal, never the run.
    """
    if os.environ.get(ENV_OFF) == "1":
        log.info("septic.disabled")
        return None

    targets = [li for li in listings if _is_buncombe(li) and (li.parcel_id or "").strip()]
    if not targets:
        log.info("septic.no_targets")
        return None

    try:
        async with client(timeout=90.0) as http:
            feats = await fetch_septic_records(http)
    except Exception as exc:  # noqa: BLE001
        log.warning("septic.fetch_failed", error=str(exc)[:200])
        return None

    by_parcel = index_by_parcel(feats)
    if not by_parcel:
        log.warning("septic.empty_index", features=len(feats))
        return None

    now = datetime.now(timezone.utc)
    stats = {
        "targets": len(targets),
        "records": len(feats),
        "parcels_indexed": len(by_parcel),
        "matched": 0,
        "adverse": 0,
        "stalled": 0,
        "repair_history": 0,
    }

    for li in targets:
        pid = _normalize_parcel(li.parcel_id)
        recs = by_parcel.get(pid) if pid else None
        if not recs:
            continue
        summary = summarize_parcel(recs, now=now)
        if not summary:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["septic"] = summary
        stats["matched"] += 1
        if summary["septic_adverse"]:
            stats["adverse"] += 1
        if summary["septic_stalled"]:
            stats["stalled"] += 1
        if summary["septic_repair_history"]:
            stats["repair_history"] += 1
        # Only the hard, unsuperseded signals are allowed to set the shared
        # distress flag. Repair history alone is history, not distress.
        if summary["land_distress"]:
            li.raw["land_distress"] = True

    log.info("septic.done", **stats)
    return stats


if __name__ == "__main__":
    import asyncio
    import collections

    async def _main() -> None:
        async with client(timeout=90.0) as http:
            feats = await fetch_septic_records(http)
        idx = index_by_parcel(feats)
        print(f"records={len(feats)} parcels={len(idx)}")
        c: collections.Counter = collections.Counter()
        for pid, recs in idx.items():
            s = summarize_parcel(recs)
            c[s["latest_status_class"]] += 1
            if s["septic_adverse"]:
                c["FLAG_adverse"] += 1
            if s["septic_stalled"]:
                c["FLAG_stalled"] += 1
            if s["septic_repair_history"]:
                c["FLAG_repair"] += 1
        for k, v in c.most_common():
            print(f"  {v:>7}  {k}")

    asyncio.run(_main())
