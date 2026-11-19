"""Yancey County NC's own live GIS parcel layer -- hosted by the regional High Country Council
of Governments (HCCOG), NOT the county's own domain -- -> raw['rollback_exposure'] from its
own AG_LAND_VA field (present-use agricultural/forestry land-value deferral).

WHY THIS EXISTS (round 65 of the gap_matrix sweep, 2026-11-19). gap_matrix's sourced-not-built
list flagged Yancey/rollback_exposure at 380 rows. Round 63/64 found the shortcut (a literal
deferred-value-ish field on the county's own GIS) works for Pender/Durham; this round checked
whether the same shortcut exists for other NC counties before assuming a harder derivation for
Yancey specifically. It does, but the HOST is different from every prior county in this family:
Yancey (like neighbouring Mitchell/Avery/Wilkes/Ashe) has no GIS of its own at all -- its
parcels are published by the High Country COG's shared ArcGIS Online organization instead
(confirmed live: no arcgis.com/.../services host resolves under any yanceycountync.gov /
gis.yanceycountync.gov guess; docs/enumeration_r3/r3_Mitchell.md already mapped this same HCCOG
host for the neighbouring county, which is how this one was found instead of guessed).

SOURCE. services1.arcgis.com/vj28eVZMB2OMIUh5 (org id, owner HCCOGGIS) hosts
"YanceyCountyBaseData" FeatureServer, whose layer 1 ("Parcels_20250501") carries a LITERAL
`AG_LAND_VA` field (the 10-char-truncated ArcGIS/Shapefile-era name for AG_LAND_VALUE)
alongside `CURRENT_LA` (current land value, full market), `CURRENT_BL` (current building
value) and `CURRENT_TO` (current total -- already present-use-REDUCED). Live-confirmed
2026-11-19 on real sampled parcels, both directions of the arithmetic hold exactly to the
dollar on every one of 20 real AG_LAND_VA>0 rows sampled (only LAND gets the present-use
reduction; buildings stay fully assessed):
  * CURRENT_TO == AG_LAND_VA + CURRENT_BL exactly (e.g. PIN 080400683856000: AG_LAND_VA
    $90,024 + CURRENT_BL $276,400 = $366,424 == CURRENT_TO $366,424).
  * so the real deferred amount is CURRENT_LA - AG_LAND_VA (the land-only reduction), and
    full_value = CURRENT_LA + CURRENT_BL = deferred_value + taxable_value always, algebraically.
  * On a non-deferred parcel AG_LAND_VA reads the literal string "0" (not blank, not null) and
    CURRENT_TO == CURRENT_LA + CURRENT_BL exactly -- confirmed on dozens of CLASS='R'/'E' rows
    sampled alongside the real CLASS='A' (STATE_CLAS 100/101/140, agricultural/forestry) hits.
County-wide: 17,242 total parcels, 1,316-1,333 with a real AG_LAND_VA > 0 (string-field compare,
`<> '0' AND <> ''`, live-counted; the layer's own maxRecordCount is 2,000 so this needs no
pagination discipline beyond a defensive offset loop).

PARCEL JOIN -- the easy case, same shape as Pender's. Yancey's board `parcel_id` is a bare
15-digit zero-padded numeric string (e.g. "081002651917000", live-sampled from real board rows)
which is the EXACT SAME shape and value as this layer's own `PIN` field (e.g. GIS PIN
"081500079541000"). One real board row carries a dashed variant ("0800-0147-8924-000"), so
`_compact_pid()` strips punctuation defensively on both sides, same convention every sibling in
this family uses -- no zero-padding or translation needed for the common case.

REAL YIELD, measured before building (not guessed): of Yancey's 203 board rows with a
resolvable parcel_id and no existing `rollback_exposure`, 18 have a real, live AG_LAND_VA > 0
on this layer today (live dry-run join, 2026-11-19) -- a genuine, verified population, the
same modest-but-real shape Durham's (11) and Pender's (23) own rollback modules found.

NO RATE TOP-UP (deliberate, same reasoning as Durham's/Macon's own simpler siblings, not
Pender's richer one). This layer carries no billed-tax-amount field, and this project has no
proven live tax-bill-portal reader registered for Yancey's own tax office -- so
`annual_deferred_tax`/`estimated_rollback` are left unset rather than guessed from an unverified
rate. `deferred_value`/`taxable_value`/`full_value` alone already close the gap_matrix column
for this county.

WHAT THIS DOES NOT COVER. This layer carries no balance-due/tax-year history field at all (only
CAMA value fields), so multi_year_delinquent_tax/two_year_delinquent/tax_aging_surfaced have no
source here -- a genuinely separate research question, not touched by this module.

Gate off entirely with FORECLOSURE_YANCEY_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_yancey_rollback_exposure"
STATE, COUNTY = "NC", "Yancey"
LAYER_URL = ("https://services1.arcgis.com/vj28eVZMB2OMIUh5/arcgis/rest/services/"
             "YanceyCountyBaseData/FeatureServer/1/query")
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's own module docstring.
ROLLBACK_YEARS_NC = 4

MAX_PAGES = int(os.getenv("YANCEY_ROLLBACK_MAX_PAGES", "10"))
PAGE_SIZE = 1000
ENABLED = os.environ.get("FORECLOSURE_YANCEY_ROLLBACK") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "")).upper()


def _is_yancey_nc(li: Listing) -> bool:
    return (li.state or "").strip().upper() == STATE and \
        (li.county or "").replace(" County", "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    rb = raw.get("rollback_exposure") if isinstance(raw, dict) else None
    return isinstance(rb, dict) and rb.get("deferred_value") is not None


# ---------------------------------------------------------------------------
# pure
# ---------------------------------------------------------------------------

def build_rollback_block(rec: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] block from one GIS parcel record, or None when the
    record doesn't actually carry a real deferral (defensive -- the bulk fetch already filters
    server-side on AG_LAND_VA not in ('0', ''), but a record reaching here with a bad/zero
    value is never trusted blindly)."""
    deferred = rec.get("deferred_value")
    full = rec.get("full_value")
    if not deferred or deferred <= 0 or not full or full <= 0:
        return None
    taxable = round(full - deferred, 2)
    if taxable < 0:
        return None
    out: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "taxable_value": taxable,
        "full_value": round(full, 2),
        "basis": "present_use_deferral",
        "county": COUNTY, "state": STATE,
        "source": "HCCOG YanceyCountyBaseData Parcels layer (AG_LAND_VA field)",
        "source_key": SLUG,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,
        "match_method": "parcel_id",
    }
    land_class = rec.get("land_class")
    if land_class:
        out["land_class"] = land_class
    return out


# ---------------------------------------------------------------------------
# bulk fetch (one paginated read, filtered server-side)
# ---------------------------------------------------------------------------

async def fetch_deferrals(client: httpx.AsyncClient) -> dict[str, dict]:
    """Every PIN with a real AG_LAND_VA > 0 on Yancey's own live HCCOG-hosted GIS parcels
    layer, keyed by the SAME bare-digit PIN format the board's own parcel_id already uses (no
    translation -- see module docstring's PARCEL JOIN section). AG_LAND_VA is a STRING field
    (ArcGIS/Shapefile legacy), so the server-side filter and the local parse both treat it as
    text first. MUST check `exceededTransferLimit`, not just `len(features) < requested`, to
    paginate correctly (same discipline every sibling in this family documents)."""
    by_pin: dict[str, dict] = {}
    offset = 0
    for _ in range(MAX_PAGES):
        r = await client.get(LAYER_URL, params={
            "where": "AG_LAND_VA <> '0' AND AG_LAND_VA IS NOT NULL AND AG_LAND_VA <> ''",
            "outFields": "PIN,CURRENT_LA,CURRENT_BL,CURRENT_TO,AG_LAND_VA,CLASS,STATE_CLAS",
            "returnGeometry": "false",
            "resultOffset": offset, "resultRecordCount": PAGE_SIZE, "f": "json",
        })
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        feats = d.get("features", [])
        for f in feats:
            a = f.get("attributes", {})
            pin = _compact_pid(a.get("PIN"))
            try:
                ag = float(a.get("AG_LAND_VA") or 0)
            except (TypeError, ValueError):
                continue
            land = a.get("CURRENT_LA")
            if not pin or ag <= 0 or not isinstance(land, (int, float)) or land <= 0:
                continue
            by_pin[pin] = {
                "deferred_value": land - ag,
                "full_value": land + (a.get("CURRENT_BL") or 0),
                "land_class": a.get("CLASS"),
            }
        exceeded = bool(d.get("exceededTransferLimit"))
        if not feats or (not exceeded and len(feats) < PAGE_SIZE):
            break
        offset += len(feats)
    return by_pin


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

async def enrich_yancey_rollback_exposure(listings: Iterable[Listing], *,
                                          client: Optional[Any] = None) -> dict[str, Any]:
    """Bulk-fetch the GIS deferral set ONCE, join locally against every eligible Yancey NC
    board row by parcel_id. No per-match network calls -- see module docstring's NO RATE
    TOP-UP section."""
    stats = {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings
              if _is_yancey_nc(li) and str(li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats["eligible"] = len(targets)
    if not targets:
        return stats

    own_client = client is None
    cli = client or httpx.AsyncClient(timeout=60.0, headers={"User-Agent": _UA})
    try:
        try:
            by_pin = await fetch_deferrals(cli)
        except Exception:  # noqa: BLE001 - a failed bulk fetch must not crash the run
            stats["fetch_errors"] += 1
            log.warning("yancey_rollback.bulk_fetch_failed")
            return stats
        stats["deferred_pins"] = len(by_pin)

        for li in targets:
            hit = by_pin.get(_compact_pid(li.parcel_id))
            if hit is None:
                continue
            block = build_rollback_block(hit)
            if block is None:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rollback_exposure"] = block
            stats["matched"] += 1
    finally:
        if own_client:
            await cli.aclose()

    log.info("yancey_rollback.done", **stats)
    return stats
