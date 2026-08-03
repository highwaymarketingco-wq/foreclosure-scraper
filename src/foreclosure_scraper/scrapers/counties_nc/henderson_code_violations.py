"""Henderson County NC open ordinance violations — a PIN-keyed distress source.

The county's Ordinance Violations Tracking layer (the public code-enforcement
dashboard's data source) is one of the few in-footprint code-enforcement feeds
that is free, anonymous, AND fully keyed: every case carries the parcel PIN, the
parcel owner's name, the situs address, the received date, and the violation
type (Nuisance, Solid Waste, Vehicle Graveyard, Junkyard, Manufactured Home
Graveyard, Zoning, Minimum Housing).

An OPEN violation is a direct property-distress signal: the owner has been told
in writing to fix something and hasn't. Stacked on a tax or estate signal at the
same parcel it is one of the strongest tells in the book.

Because it is PIN-keyed it JOINS rather than duplicates — ``parcel_id`` puts every
row on the ``parcel:<state>:<county>:<pin>`` dedupe key, so an open violation
merges onto the tax-foreclosure / heir / delinquent-tax lead already on the board
for that parcel instead of creating a second one, and stands alone as a net-new
lead where nothing else has hit yet.

Two passes:

1. **Open cases** — everything the county has NOT dispositioned as resolved /
   no-further-action / inactive. Written as a NOT-LIKE filter rather than an
   allowlist of open statuses, so a newly-added open status shows up as a lead
   instead of silently vanishing.
2. **Case history at those same parcels** — every case ever filed on the open
   parcels, which yields ``prior_cases`` / ``repeat_offender``. A parcel on its
   fourth nuisance case is a chronically neglected asset, not a one-off.

Cases are grouped so one PROPERTY produces one listing carrying all of its open
violations, not one listing per complaint.

Free, public, anonymous ArcGIS REST (services1.arcgis.com), no auth, no CAPTCHA.
Dateless (a violation has no sale date) -> routed via DATELESS_OK_SOURCES.
Gate with FORECLOSURE_HENDERSON_CODE=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_HENDERSON_CODE"

LAYER = ("https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/"
         "OVT_PublicDashboard_View/FeatureServer/1")

#: Public dashboard the layer backs — the human-readable source link.
DASHBOARD_URL = ("https://www.hendersoncountync.gov/planning/page/"
                 "ordinance-violation-tracking")

_FIELDS = ("OBJECTID", "caseID", "complaintID", "dateReceived", "parcelOwner",
           "address", "violationType", "PIN", "dispositionStatus", "dispositionDate")
_OUT_FIELDS = ",".join(_FIELDS)
_HISTORY_FIELDS = "PIN,caseID,violationType,dispositionStatus,dateReceived"

#: Dispositions that close a case. Expressed as a NEGATIVE filter so a status
#: the county adds later defaults to OPEN (a new lead) rather than to invisible.
#: NULL-status rows drop out by SQL NULL semantics — live sampling shows those
#: are blank placeholder records, not real cases.
_CLOSED_LIKE = (
    "%No Further Action%",   # invalid / duplicate / referred / owner- or county-resolved
    "Resolved%",             # free-text 'Resolved' + 'Resolved - ...'
    "Inactive%",
    "nfa%",
    "Refer%Authority%",      # free-text 'Refer to proper Authority' (the coded
                             # 'Referred to Proper Authority - No Further Action'
                             # is already caught above)
)
_OPEN_WHERE = " AND ".join(f"dispositionStatus NOT LIKE '{p}'" for p in _CLOSED_LIKE)

#: Client-side mirror of the same rule, for classifying history rows.
_CLOSED_RE = re.compile(
    r"(no further action|^resolved|^inactive|^nfa|^refer.*authority)", re.I)

#: Violation types that imply physical deterioration/dumping rather than
#: paperwork. Used only to label severity in raw — everything open is kept.
_SEVERE = re.compile(
    r"(junk\s*yard|junkyard|vehicle graveyard|manufactured home graveyard|"
    r"solid waste|minimum housing|nuisance)", re.I)

_PAGE = 1000


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _norm_pin(v: Any) -> str | None:
    """County data carries at least one tab-prefixed PIN; strip all whitespace."""
    if v in (None, ""):
        return None
    s = re.sub(r"\s+", "", str(v)).strip()
    return s or None


def _epoch_to_dt(v: Any) -> datetime | None:
    """ArcGIS dates are epoch milliseconds (UTC)."""
    if v in (None, "", " "):
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso(v: Any) -> str | None:
    dt = _epoch_to_dt(v)
    return dt.date().isoformat() if dt else None


def is_closed(status: Any) -> bool:
    return bool(_CLOSED_RE.search(str(status or "").strip()))


def _group_key(attrs: dict) -> tuple[str, str] | None:
    """One listing per PROPERTY: PIN when present, else the situs address."""
    pin = _norm_pin(attrs.get("PIN"))
    if pin:
        return ("pin", pin)
    addr = _clean(attrs.get("address"))
    if addr:
        return ("addr", addr.upper())
    return None


def build_listing(feats: list[dict], history: dict[str, dict] | None = None,
                  now: datetime | None = None) -> Listing | None:
    """Fold every open case at one property into a single Listing."""
    now = now or datetime.utcnow()
    history = history or {}
    if not feats:
        return None

    # Newest case first — it drives the headline fields.
    feats = sorted(feats, key=lambda f: ((f.get("attributes") or {}).get("dateReceived") or 0),
                   reverse=True)
    attrs = [(f.get("attributes") or {}) for f in feats]
    head = attrs[0]

    def _first(field: str) -> str | None:
        """Newest non-blank value across the group — a later case can be filed
        with a blank owner/address that an earlier one at the same parcel has."""
        for a in attrs:
            v = _clean(a.get(field))
            if v:
                return v
        return None

    pin = _norm_pin(head.get("PIN")) or next(
        (p for p in (_norm_pin(a.get("PIN")) for a in attrs) if p), None)
    address = _first("address")
    owner = _first("parcelOwner")
    if not pin and not address:
        return None

    lat = lng = None
    for f in feats:
        g = f.get("geometry") or {}
        if g.get("y") is not None and g.get("x") is not None:
            lat, lng = float(g["y"]), float(g["x"])
            break

    violations = [{
        "violation": _clean(a.get("violationType")) or "unknown",
        "status": _clean(a.get("dispositionStatus")) or "unknown",
        "date": _iso(a.get("dateReceived")),
        "case_id": _clean(a.get("caseID")),
    } for a in attrs]

    hist = history.get(pin or "", {})
    total_cases = max(int(hist.get("total") or 0), len(violations))
    prior_cases = max(total_cases - len(violations), 0)
    types = sorted({v["violation"] for v in violations if v["violation"] != "unknown"})
    severe = any(_SEVERE.search(t) for t in types)
    opened = _epoch_to_dt(head.get("dateReceived"))

    raw: dict[str, Any] = {
        # Same shape enrichment_code_enforcement writes, so every downstream
        # reader (distress_score PROPERTY signal, dashboard popout) works as-is.
        "code_enforcement": {
            "county": "Henderson",
            "open_violations": len(violations),
            "total_violations": total_cases,
            "prior_cases": prior_cases,
            "repeat_offender": prior_cases >= 2,
            "violation_types": types,
            "severe": severe,
            "violations": violations[:8],
            "has_open": True,
            "opened": opened.date().isoformat() if opened else None,
            "source": "henderson_ordinance_violations_tracking",
        },
    }
    if severe:
        # Dumping / junk / minimum-housing cases describe physical condition.
        raw["distressed"] = True

    headline = types[0] if types else "ordinance violation"
    desc = (f"Open code violation ({headline}) in Henderson County, NC"
            + (f" — owner {owner}" if owner else "")
            + (f"; {prior_cases} prior case(s) at this parcel" if prior_cases else ""))

    return Listing(
        source=HendersonCodeViolations.slug,
        source_url=DASHBOARD_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Henderson",
        street_address=address,
        parcel_id=pin,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        case_number=_clean(head.get("caseID")),
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


async def fetch_history(http, pins: list[str]) -> dict[str, dict]:
    """Total case count per parcel, for the repeat-offender signal.

    Queried with the RAW PIN strings the open rows carry (one of them is
    tab-prefixed in the county's own data) and indexed on the normalized value.
    Best effort: a failure here costs the counter, not the leads.
    """
    if not pins:
        return {}
    quoted = ",".join("'" + p.replace("'", "''") + "'" for p in sorted(set(pins)))
    try:
        rows = await agw.query_attributes(
            http, LAYER, where=f"PIN IN ({quoted})", out_fields=_HISTORY_FIELDS,
            page=_PAGE, max_records=20000)
    except Exception as exc:  # noqa: BLE001
        log.warning("henderson_code.history_fail", error=str(exc)[:200])
        return {}
    idx: dict[str, dict] = {}
    for a in rows:
        key = _norm_pin(a.get("PIN"))
        if not key:
            continue
        rec = idx.setdefault(key, {"total": 0, "closed": 0})
        rec["total"] += 1
        if is_closed(a.get("dispositionStatus")):
            rec["closed"] += 1
    log.info("henderson_code.history", parcels=len(idx), cases=len(rows))
    return idx


class HendersonCodeViolations(BaseScraper):
    slug = "counties_nc.henderson_code_violations"
    name = "Henderson County NC Open Ordinance/Code Violations (PIN-keyed)"
    category = "motivated_seller"
    expected_min_count = 25
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("henderson_code.disabled")
            return []
        async with client(timeout=45.0) as http:
            feats = await agw.query_features(
                http, LAYER, where=_OPEN_WHERE, out_fields=_OUT_FIELDS,
                return_geometry=True, out_sr=4326, order_by="OBJECTID ASC",
                page=_PAGE, max_records=20000)

            groups: dict[tuple[str, str], list[dict]] = {}
            for ft in feats:
                key = _group_key(ft.get("attributes") or {})
                if key:
                    groups.setdefault(key, []).append(ft)

            raw_pins = [str((f.get("attributes") or {}).get("PIN"))
                        for f in feats if (f.get("attributes") or {}).get("PIN")]
            history = await fetch_history(http, raw_pins)

        now = datetime.utcnow()
        out: list[Listing] = []
        for feat_group in groups.values():
            li = build_listing(feat_group, history=history, now=now)
            if li:
                out.append(li)
        log.info("henderson_code.parsed", open_cases=len(feats), parcels=len(groups),
                 listings=len(out),
                 repeat=sum(1 for li in out
                            if (li.raw or {})["code_enforcement"]["repeat_offender"]))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = HendersonCodeViolations()
        rows = await s.safe_run()
        rep = sum(1 for li in rows if (li.raw or {})["code_enforcement"]["repeat_offender"])
        print(f"outcome={s.last_outcome} count={len(rows)} repeat_offenders={rep}")
        for li in rows[:15]:
            ce = li.raw["code_enforcement"]
            print(f"  {(li.defendant or '')[:28]:28} pin={li.parcel_id or '-':11} "
                  f"open={ce['open_violations']} prior={ce['prior_cases']} "
                  f"{','.join(ce['violation_types'])[:26]:26} {(li.street_address or '')[:30]}")

    asyncio.run(_main())
