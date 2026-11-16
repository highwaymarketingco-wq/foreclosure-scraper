"""code_enforcement, every scrapers/counties_generic/arcgis_distress_layers.py Layer whose
process=="code_enforcement" (plus Lincoln County's own standalone archive scraper, which reads
the identical county layer under a second source tag): does the matched case still read OPEN
on a freshly, fully reloaded copy of that exact county/city layer today?

WHY THIS EXISTS (2026-11-16 gap-matrix sweep of code_enforcement's `built-not-verified` cells,
same investigation as code_enforcement_city_open_data.py -- see that module's docstring for the
full context). This module closes the second-largest slice: the arcgis_distress_layers.py
Layer entries whose own `process` field is "code_enforcement" (Lincoln, Durham, Richland,
York's rockhill_code_housing/rockhill_code_exterior_major sub-layers) plus Lincoln's second,
dedicated scraper (counties_nc/lincoln_code_violations.py) that reads the SAME physical service
under its own "lincoln_county_code_violations_archive" source tag.

WHICH ROWS (applies): raw['code_enforcement'] is a dict whose 'source' is one of `_SLUGS()`
below -- built FRESH from arcgis_distress_layers.LAYERS's own process=="code_enforcement"
entries every call, never a hardcoded per-county duplicate a future Layer addition could
silently outgrow (the exact bug class this verifier exists to close -- see
gap_matrix.py's own `_arcgis_distress_layers_credit()` comment, which already applies this same
"read the registry, never a name-match duplicate" fix on the `built` side of this column).
code_enforcement_henderson.py's own OVT slug is deliberately excluded (it already has a more
specific, dedicated verifier; registry.py's own contract requires non-overlapping applies()
within one shared SIGNAL).

MATCHING. None of this family's rows carry a parcel id in the written block --
arcgis_distress_layers.py's own `_to_listing()` sets every one of these rows' claimed
`case_id` to `parcel or situs`, and not one current process=="code_enforcement" Layer sets
`parcel=` -- so the claimed case_id IS just the situs address today, and the normalized,
house-numbered street address is the only real key, built the SAME way `_to_listing()` builds
it (the Layer's own `situs` field, else its `situs_parts` joined with the leading-part
no-address sentinel dropped -- Durham's `AddressNum`, the only situs_parts layer here).

OPEN/CLOSED, per slug, live-verified 2026-11-16 (an outStatistics groupBy against each real
service; the counts below are that day's):
  lincoln_code_violations / lincoln_county_code_violations_archive: `STATUS` is exactly "Open"
    or "Closed" (66 open of 3,465 total) -- the scraper's own `where="STATUS='Open'"` value.
  columbia_code_vacant_boarded: `CaseStatus` has 10 distinct values; "In Violation"/"Open" are
    the scraper's own candidate-pulling `where=` values (8,457 of 9,776 total); everything else
    ("Resolved - Abated by Owner/City", "No Violation", "Under Investigation", ...) is
    closed-equivalent by the SAME `_CLOSED_STATUS_PREFIXES` convention
    enrichment_code_enforcement.py already uses project-wide for exactly this ambiguity
    ("closed"/"resolved"/"void" prefix), plus the one exact "no violation"/"not in violation"
    phrasing that prefix match alone would miss.
  durham_open_code_violations: the service's own COMPLETE field list (live metadata) carries NO
    status column at all -- "Open Landuse Code Violation Cases" is the dataset's own published
    name, i.e. Durham's own portal drops a case from this feed once it closes rather than
    flagging it closed in place. Found on a COMPLETE fresh reload is itself the openness test
    here, the same principle Henderson's own "no_case_on_layer" -> refuted already rests on when
    a feed simply no longer carries a case at all.
  rockhill_code_housing / rockhill_code_exterior_major: `Status` is free text ("In Violation"
    the admitted-open value, matching the Layer's own `detail="Status"` re-use of this same
    column; "Closed - Interior"/"Not In Violation" closed) -- the same prefix convention, plus
    the two literal Rock Hill phrasings live-checked today.
A slug this module does not recognize in `_STATUS` (a future Layer addition before this file is
updated) falls back to "found == still open": the conservative direction (a false `confirmed`
costs nothing beyond "run the sweep again later"; a false `refuted`/`stale` would wrongly end a
real signal).

VERDICTS: confirmed/stale/refuted/unconfirmed, the same meanings core.py documents and
code_enforcement_henderson.py already uses for this identical signal.

TTL 14 days (same cadence as code_enforcement_henderson.py for this identical signal).

GOVERNS is per-record (`governs_for`), never a flat tuple: this module answers for several
DISTINCT sources sharing the one SIGNAL, and a refuted/stale verdict must end only the ONE
source's block the matched row actually carries -- never, say, end a charlotte_open_data or
gastonia_cityview_locator block on a merged row, the same discipline
code_enforcement_henderson.py's own docstring states for its single source.

EVIDENCE: the matched slug, the layer's own fetch/health evidence, and per matched case (at
most 8) the detail text, raw status string and open flag -- no field beyond what each Layer's
own, already-privacy-reviewed `fields` tuple requests (none of these layers request an owner,
complainant, phone or e-mail column; see each Layer's own comment in arcgis_distress_layers.py).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _arcgis_layer as agl

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
SOURCE = "arcgis_distress_layers.py code_enforcement family (per-county/city ArcGIS)"
MAX_CASES_IN_EVIDENCE = 8
_NAME = __name__.rsplit(".", 1)[-1]

#: code_enforcement_henderson.py already owns this one; applies() must never overlap it.
_HENDERSON_SLUG = "henderson_ordinance_violations_tracking"

#: Lincoln County's own standalone scraper (counties_nc/lincoln_code_violations.py) reads the
#: identical arcgisserver.lincolncountync.gov .../MapServer/15 layer the generic Layer entry
#: below also names, under its own second source tag -- not a LAYERS entry, so it cannot be
#: discovered the generic way and is named explicitly, pointed at the same Layer object.
_LINCOLN_ARCHIVE_SLUG = "lincoln_county_code_violations_archive"
_LINCOLN_LAYER_SLUG = "lincoln_code_violations"

#: slug -> the ArcGIS status field to read, or None when the layer's own publisher convention
#: is "a closed case is dropped from the feed, never flagged closed in place" (Durham) -- see
#: the module docstring's live-verified breakdown.
_STATUS: dict[str, Optional[str]] = {
    _LINCOLN_LAYER_SLUG: "STATUS",
    _LINCOLN_ARCHIVE_SLUG: "STATUS",
    "columbia_code_vacant_boarded": "CaseStatus",
    "durham_open_code_violations": None,
    "rockhill_code_housing": "Status",
    "rockhill_code_exterior_major": "Status",
}

_CLOSED_PREFIXES = ("closed", "resolved", "void")
_CLOSED_EXACT = ("no violation", "not in violation")


def _is_closed(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s.startswith(_CLOSED_PREFIXES) or s in _CLOSED_EXACT


def _adl():
    """arcgis_distress_layers.py, imported on first use (the registry imports every verifier;
    the full scraper stack must not load in just to answer applies())."""
    from ...scrapers.counties_generic import arcgis_distress_layers as m
    return m


def _layers() -> dict[str, Any]:
    """slug -> Layer: every live process=='code_enforcement' entry, plus the Lincoln archive
    scraper's own tag pointed at the identical Lincoln Layer object (see _LINCOLN_ARCHIVE_SLUG).
    Rebuilt from the registry every call (cheap: a tuple of ~30 NamedTuples) so a Layer the
    scraper adds tomorrow is covered the next time this is called, never a duplicate list here
    to fall out of date."""
    m = _adl()
    out = {lay.slug: lay for lay in m.LAYERS
          if lay.process == "code_enforcement" and lay.slug != _HENDERSON_SLUG}
    if _LINCOLN_LAYER_SLUG in out:
        out[_LINCOLN_ARCHIVE_SLUG] = out[_LINCOLN_LAYER_SLUG]
    return out


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) else None


def applies(row: dict) -> bool:
    ce = _block(row)
    if not ce or not ce.get("has_open"):
        return False
    return str(ce.get("source") or "") in _layers()


# ---------------------------------------------------------------------------
# address matching -- the exact shape _to_listing() builds, never a duplicate rule
# ---------------------------------------------------------------------------

def _addr(v: Any) -> Optional[str]:
    from ...models import _normalize_addr
    from ..core import _house_numbered
    a = _normalize_addr(str(v)) if v not in (None, "") else None
    return a if a and _house_numbered(a) else None


def _situs(a: dict, lay) -> Optional[str]:
    if lay.situs:
        return _addr(a.get(lay.situs))
    if not lay.situs_parts:
        return None
    sentinel = _adl()._HOUSE_NUM_SENTINEL_RE
    bits = []
    for i, p in enumerate(lay.situs_parts):
        v = a.get(p)
        v = str(v).strip() if v not in (None, "") else None
        if i == 0 and v and sentinel.match(v):
            v = None
        bits.append(v)
    joined = " ".join(b for b in bits if b) or None
    return _addr(joined)


def _index(snap, lay) -> dict:
    idx = snap.cache.get("by_addr")
    if idx is None:
        by_addr: dict = defaultdict(list)
        for a in snap.rows:
            s = _situs(a, lay)
            if s:
                by_addr[s].append(a)
        idx = snap.cache["by_addr"] = by_addr
    return idx


def _case_view(a: dict, lay, status_field: Optional[str]) -> dict:
    status = a.get(status_field) if status_field else None
    status = str(status) if status not in (None, "") else None
    is_open = True if status is None else not _is_closed(status)
    detail = a.get(lay.detail) if lay.detail else None
    out = {"violation": str(detail)[:200] if detail not in (None, "") else None,
          "status": status, "open": is_open}
    return {k: v for k, v in out.items() if v is not None or k == "open"}


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ce = _block(row) or {}
    slug = str(ce.get("source") or "")
    lay = _layers().get(slug)
    ev: dict[str, Any] = {"matched_slug": slug or None}
    if lay is None:
        ev["reason"] = "unknown_source"
        return _res("unconfirmed", ev)

    addr = _addr(row.get("street_address"))
    if not addr:
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    snap = await agl.layer_for(client, lay.url, out_fields=",".join(lay.fields),
                               order_by=lay.fields[0])
    ev.update(snap.evidence())
    if not snap.complete:
        ev["reason"] = snap.health
        return _res("unconfirmed", ev)

    rows = _index(snap, lay).get(addr, [])
    if not rows:
        ev["reason"] = "no_case_on_layer"
        return _res("refuted", ev)

    cases = [_case_view(a, lay, _STATUS.get(slug)) for a in rows]
    ev["cases"] = cases[:MAX_CASES_IN_EVIDENCE]
    ev["cases_matched"] = len(cases)
    if any(c["open"] for c in cases):
        return _res("confirmed", ev)
    ev["reason"] = "case_closed"
    return _res("stale", ev)


def governs_for(record: dict) -> tuple[str, ...]:
    slug = (record.get("evidence") or {}).get("matched_slug") if isinstance(record, dict) else None
    return (f"code_enforcement:{slug}",) if slug else ()
