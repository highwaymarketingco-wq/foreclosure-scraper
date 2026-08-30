"""Lincoln County NC open code violations — an address-keyed distress source.

The county's TRACKiT "Code Violations Archive" layer (a free, anonymous ArcGIS
REST endpoint, no auth and no CAPTCHA) carries every code-enforcement case the
county has ever filed: the violation ID, the situs address, a location/parcel
reference, the violation type/description, the received date, the violator/owner
name, and — for a handful of rows — a phone/email.

An OPEN violation is a direct property-distress signal: the owner has been told
in writing to fix something and hasn't. Stacked on a tax, estate, or foreclosure
signal at the same property it is one of the strongest tells in the book.

Because it is situs-keyed it JOINS rather than duplicates — ``street_address``
puts every row on the same address the tax-foreclosure / heir / delinquent-tax
lead already carries, so an open violation merges onto the existing board lead
for that property instead of creating a second one, and stands alone as a net-new
lead where nothing else has hit yet.

Cases are grouped so one PROPERTY produces one listing carrying all of its open
violations, not one listing per complaint.

Status is written as a NOT-LIKE exclusion of closed/resolved/inactive/void
dispositions rather than an allowlist of open statuses, so a newly-added open
status shows up as a lead instead of silently vanishing.

Dateless (a violation has no sale date) -> routed via DATELESS_OK_SOURCES.
Gate with FORECLOSURE_LINCOLN_CODE=0.
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

ENV_OFF = "FORECLOSURE_LINCOLN_CODE"

LAYER = ("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
         "TRACKiT/MapServer/8")

#: Human-readable source link — the county GIS map service the layer backs.
SOURCE_URL = ("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
              "TRACKiT/MapServer")

_FIELDS = ("OBJECTID", "VIOLATIONID", "FULLADDR", "LOCDESC", "VIOLATETYPE",
           "VIOLATEDESC", "CODE", "SUBMITDT", "NAME", "PHONE", "EMAIL", "STATUS")
_OUT_FIELDS = ",".join(_FIELDS)

#: Statuses that close/retire a case. Expressed as a NEGATIVE filter so a status
#: the county adds later defaults to OPEN (a new lead) rather than to invisible.
#: NULL-status rows drop out by SQL NULL semantics.
_CLOSED_LIKE = (
    "Closed%",
    "Resolved%",
    "Inactive%",
    "Void%",
    "%No Further Action%",
    "%Compl%",          # Complete / Completed / Compliance
    "Withdrawn%",
    "Dismiss%",
)
_OPEN_WHERE = " AND ".join(f"STATUS NOT LIKE '{p}'" for p in _CLOSED_LIKE)

#: Business/entity markers — when NAME matches one of these it is a contractor or
#: company, NOT the individual owner, so it is kept in raw but NOT promoted to
#: owner_name (which downstream treats as an outreachable individual).
_ENTITY_RE = re.compile(
    r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|co\.|company|"
    r"ltd|llp|l\.p|lp|builders?|construction|contractors?|properties|"
    r"property|holdings?|enterprises?|investments?|associates?|assoc|"
    r"group|services?|management|rentals?|realty|homes?|trust|bank|"
    r"church|ministries|hoa|partners?|development|dev\b)\b", re.I)

_PAGE = 1000


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
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


def _is_person(name: str | None) -> bool:
    """A person-owner name (kept for owner_name) vs a contractor/company (raw only)."""
    if not name:
        return False
    return not _ENTITY_RE.search(name)


def _group_key(attrs: dict) -> str | None:
    """One listing per PROPERTY: the situs address (upper-cased, whitespace-normalized)."""
    addr = _clean(attrs.get("FULLADDR"))
    if addr:
        return addr.upper()
    # No address — fall back to the location/parcel reference so nothing is lost.
    loc = _clean(attrs.get("LOCDESC"))
    return f"LOC:{loc}" if loc else None


def build_listing(feats: list[dict], now: datetime | None = None) -> Listing | None:
    """Fold every open case at one property into a single Listing."""
    now = now or datetime.utcnow()
    if not feats:
        return None

    # Newest case first — it drives the headline fields.
    feats = sorted(feats, key=lambda f: ((f.get("attributes") or {}).get("SUBMITDT") or 0),
                   reverse=True)
    attrs = [(f.get("attributes") or {}) for f in feats]
    head = attrs[0]

    def _first(field: str) -> str | None:
        """Newest non-blank value across the group — a later case can be filed
        with a blank owner/address that an earlier one at the same property has."""
        for a in attrs:
            v = _clean(a.get(field))
            if v:
                return v
        return None

    address = _first("FULLADDR")
    name_raw = _first("NAME")
    loc = _first("LOCDESC")
    if not address and not loc:
        return None

    owner = name_raw if _is_person(name_raw) else None

    lat = lng = None
    for f in feats:
        g = f.get("geometry") or {}
        if g.get("y") is not None and g.get("x") is not None:
            lat, lng = float(g["y"]), float(g["x"])
            break

    violations = [{
        "violation_id": _clean(a.get("VIOLATIONID")),
        "type": _clean(a.get("VIOLATETYPE")),
        "description": _clean(a.get("VIOLATEDESC")),
        "code": _clean(a.get("CODE")),
        "status": _clean(a.get("STATUS")),
        "date": _iso(a.get("SUBMITDT")),
    } for a in attrs]

    # description = the code-enforcement distress note (type + free-text desc).
    notes = []
    for v in violations:
        part = v["type"] or ""
        if v["description"]:
            part = f"{part}: {v['description']}" if part else v["description"]
        if part:
            notes.append(part)
    seen: set[str] = set()
    notes = [n for n in notes if not (n.lower() in seen or seen.add(n.lower()))]
    headline = notes[0] if notes else "code violation"
    opened = _epoch_to_dt(head.get("SUBMITDT"))
    desc = (f"Open code violation ({headline}) in Lincoln County, NC"
            + (f" — owner {owner}" if owner
               else (f" — party {name_raw}" if name_raw else ""))
            + (f"; {len(violations)} open cases at this property" if len(violations) > 1 else ""))

    # Phone/email are county-published, NOT owner-consented — DNC/TCPA gated so
    # the outreach layer scrubs before anything is dialed (same shape as the
    # county_published enrichers use).
    contacts: list[dict[str, Any]] = []
    for a in attrs:
        ph = _clean(a.get("PHONE"))
        em = _clean(a.get("EMAIL"))
        if ph or em:
            contacts.append({
                "phone": ph,
                "email": em,
                "source": LincolnCodeViolations.slug,
                "county_published": True,
                "consent": "none",
                "needs_dnc_scrub": True,
            })

    raw: dict[str, Any] = {
        "lincoln_code": {
            "county": "Lincoln",
            "open_violations": len(violations),
            "violations": violations[:12],
            "violation_id": _clean(head.get("VIOLATIONID")),
            "status": _clean(head.get("STATUS")),
            "code": _clean(head.get("CODE")),
            "locdesc": loc,
            "name_raw": name_raw,
            "has_open": True,
            "opened": opened.date().isoformat() if opened else None,
            "source": "lincoln_county_code_violations_archive",
        },
    }
    if contacts:
        raw["lincoln_code"]["contacts"] = contacts

    return Listing(
        source=LincolnCodeViolations.slug,
        source_url=SOURCE_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Lincoln",
        street_address=address,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        case_number=_clean(head.get("VIOLATIONID")),
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class LincolnCodeViolations(BaseScraper):
    slug = "counties_nc.lincoln_code_violations"
    name = "Lincoln County NC Open Code Violations (address-keyed)"
    category = "motivated_seller"
    expected_min_count = 0
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("lincoln_code.disabled")
            return []
        async with client(timeout=45.0) as http:
            feats = await agw.query_features(
                http, LAYER, where=_OPEN_WHERE, out_fields=_OUT_FIELDS,
                return_geometry=True, out_sr=4326, order_by="OBJECTID ASC",
                page=_PAGE, max_records=20000)

        groups: dict[str, list[dict]] = {}
        for ft in feats:
            key = _group_key(ft.get("attributes") or {})
            if key:
                groups.setdefault(key, []).append(ft)

        now = datetime.utcnow()
        out: list[Listing] = []
        for feat_group in groups.values():
            li = build_listing(feat_group, now=now)
            if li:
                out.append(li)
        log.info("lincoln_code.parsed", open_cases=len(feats), properties=len(groups),
                 listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = LincolnCodeViolations()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        for li in rows[:15]:
            lc = li.raw["lincoln_code"]
            print(f"  {(li.owner_name or lc['name_raw'] or '')[:26]:26} "
                  f"open={lc['open_violations']} {(li.street_address or '')[:28]:28} "
                  f"{(li.description or '')[:40]}")

    asyncio.run(_main())
