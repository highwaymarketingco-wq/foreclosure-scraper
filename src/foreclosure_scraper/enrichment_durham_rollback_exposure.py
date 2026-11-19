"""Durham County NC's own live GIS parcel layer -> raw['rollback_exposure'] from its own
TOTAL_DEFERRED_VALUE field (present-use/agricultural/forestry + historic-property deferral).

WHY THIS EXISTS (round 64 of the gap_matrix sweep, 2026-11-19). gap_matrix's no-source-known
list flagged Durham/rollback_exposure at 5,967 rows -- the single largest rollback_exposure gap
on the whole matrix. Round 63 found Pender's own GIS carries a literal DEFERRED_VALUE field
needing no derivation at all; this round checked whether the same shortcut exists for other NC
counties before assuming a harder Mecklenburg-style (land-minus-total, cross-referenced against
a second tax-bill portal) or Currituck-style (one-off XLSX download) derivation was needed for
Durham. It does.

SOURCE. webgis2.durhamnc.gov publishes a "PublicServices/Property" MapServer (the county's own
public GIS, City of Durham/Durham County's shared ArcGIS Server -- already used by this project
for durham_open_code_violations/durham_unsafe_building) whose layer 4 ("Parcels") carries, among
80 fields, a LITERAL `TOTAL_DEFERRED_VALUE` field, split into its two component programs:
`USE_VALUE_DEFERRED` (present-use ag/horticultural/forestry) and `HISTORIC_VALUE_DEFERRED`
(historic-property deferral under NC G.S. 105-278), alongside `TOTAL_LAND_VALUE_ASSESSED`,
`TOTAL_BLDG_VALUE_ASSESSED`, `LAND_USE_VALUE` (the present-use-REDUCED land value) and
`TOTAL_PROP_VALUE` (full market value = TOTAL_LAND_VALUE_ASSESSED + TOTAL_BLDG_VALUE_ASSESSED,
NOT yet reduced for any deferral -- the opposite orientation from Pender's TOTAL_VALUE, which
WAS already the reduced figure). Live-confirmed 2026-11-19 on real sampled parcels, both
directions of the arithmetic hold exactly to the dollar:
  * USE_VALUE_DEFERRED == TOTAL_LAND_VALUE_ASSESSED - LAND_USE_VALUE on every present-use row
    sampled (e.g. PIN 0830318548: land $1,658,596 - present-use land $5,166 = $1,653,430,
    LAND_CLASS "PRESENT-USE/HORTICUL"; PIN 0801498750: $1,293,553 - $239,353 = $1,054,200,
    LAND_CLASS "PRESENT-USE/AGRICULT").
  * TOTAL_DEFERRED_VALUE == USE_VALUE_DEFERRED + HISTORIC_VALUE_DEFERRED on every sampled row
    (one of the two is 0/null on every single-program parcel seen).
  * TOTAL_PROP_VALUE == TOTAL_LAND_VALUE_ASSESSED + TOTAL_BLDG_VALUE_ASSESSED exactly (confirmed
    == COST_TOTAL_VALUE too), so the value CURRENTLY being taxed (not yet derived as its own
    field anywhere on this layer) is TOTAL_PROP_VALUE - TOTAL_DEFERRED_VALUE -- one subtraction
    of two literal fields, the same single arithmetic step Macon's/Craven's own
    sibling modules already use to fill a companion field this layer doesn't carry directly,
    not a multi-source derivation like Mecklenburg's.
County-wide: 133,905 total parcels, 797 with a real TOTAL_DEFERRED_VALUE > 0 (live-counted via
paginated `resultOffset` + `exceededTransferLimit`, not a naive page-size guess -- same
pagination discipline enrichment_pender_rollback_exposure.py's own docstring documents).

PARCEL JOIN -- the easy case. Durham board rows' own `parcel_id` is a bare 10-digit numeric
string (e.g. "0841364407", "0832809955" -- live-sampled from real board rows) which is the EXACT
SAME shape and value as this layer's own `PIN` field (e.g. GIS PIN "0881666345" == a real board
parcel_id). No dash-stripping, no translation needed -- confirmed live by running the actual
join below, not assumed.

REAL YIELD, measured before building (not guessed): of Durham's 2,657 board rows with a
resolvable parcel_id and no existing `rollback_exposure`, 11 have a real, live
TOTAL_DEFERRED_VALUE > 0 on this layer today (live dry-run, 2026-11-19) -- a modest but genuine,
verified population (this board's Durham mix skews urban/subdivision like Davidson's did, not
the large-acreage present-use shape Macon's/Craven's board populations hit harder; still a real,
non-zero, live-confirmed match, not a wiring gap).

NO RATE TOP-UP (deliberate, same reasoning as Macon's/Craven's own simpler siblings, not
Pender's richer one). This layer carries no billed-tax-amount field, and this project has no
proven live tax-bill-portal reader registered for Durham's own tax office (unlike Pender's
Tyler Munis Citizen Self Service) -- so `annual_deferred_tax`/`estimated_rollback` are left
unset rather than guessed from an unverified rate. `deferred_value`/`taxable_value`/`full_value`
alone already close the gap_matrix column for this county; a rate top-up can be added later IF
a real Durham tax-bill source is ever wired, never invented here.

Gate off entirely with FORECLOSURE_DURHAM_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_durham_rollback_exposure"
STATE, COUNTY = "NC", "Durham"
LAYER_URL = ("https://webgis2.durhamnc.gov/server/rest/services/"
             "PublicServices/Property/MapServer/4/query")
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's own module docstring. The
#: historic-deferral program (G.S. 105-278) has no separate statutory rollback window of its
#: own in this project's existing model; present-use's 4-year window is used uniformly, same
#: convention enrichment_rollback_deferral.py already applies project-wide.
ROLLBACK_YEARS_NC = 4

MAX_PAGES = int(os.getenv("DURHAM_ROLLBACK_MAX_PAGES", "20"))
PAGE_SIZE = 1000
ENABLED = os.environ.get("FORECLOSURE_DURHAM_ROLLBACK") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "")).upper()


def _is_durham_nc(li: Listing) -> bool:
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
    server-side on TOTAL_DEFERRED_VALUE > 0, but a record reaching here with a bad/zero value
    is never trusted blindly)."""
    deferred = rec.get("deferred_value")
    full = rec.get("full_value")
    if not deferred or deferred <= 0 or not full or full <= 0:
        return None
    taxable = round(full - deferred, 2)
    if taxable < 0:
        return None
    use_part = rec.get("use_value_deferred") or 0
    hist_part = rec.get("historic_value_deferred") or 0
    if use_part > 0 and hist_part > 0:
        basis = "present_use+historic_deferral"
    elif hist_part > 0:
        basis = "historic_deferral"
    else:
        basis = "present_use_deferral"
    out: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "taxable_value": taxable,
        "full_value": round(full, 2),
        "basis": basis,
        "county": COUNTY, "state": STATE,
        "source": "webgis2.durhamnc.gov PublicServices/Property Parcels layer "
                   "(TOTAL_DEFERRED_VALUE field)",
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
    """Every PIN with a real TOTAL_DEFERRED_VALUE > 0 on Durham's own live GIS parcels layer,
    keyed by the SAME bare-digit PIN format the board's own parcel_id already uses (no
    translation -- see module docstring's PARCEL JOIN section). MUST check
    `exceededTransferLimit`, not just `len(features) < requested`, to paginate correctly (same
    discipline enrichment_pender_rollback_exposure.py's own docstring documents)."""
    by_pin: dict[str, dict] = {}
    offset = 0
    for _ in range(MAX_PAGES):
        r = await client.get(LAYER_URL, params={
            "where": "TOTAL_DEFERRED_VALUE > 0",
            "outFields": "PIN,TOTAL_LAND_VALUE_ASSESSED,TOTAL_BLDG_VALUE_ASSESSED,"
                         "USE_VALUE_DEFERRED,HISTORIC_VALUE_DEFERRED,TOTAL_DEFERRED_VALUE,"
                         "TOTAL_PROP_VALUE,LAND_CLASS",
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
            deferred = a.get("TOTAL_DEFERRED_VALUE")
            full = a.get("TOTAL_PROP_VALUE")
            if pin and isinstance(deferred, (int, float)) and deferred > 0:
                by_pin[pin] = {
                    "deferred_value": deferred,
                    "full_value": full,
                    "use_value_deferred": a.get("USE_VALUE_DEFERRED"),
                    "historic_value_deferred": a.get("HISTORIC_VALUE_DEFERRED"),
                    "land_class": a.get("LAND_CLASS"),
                }
        exceeded = bool(d.get("exceededTransferLimit"))
        if not feats or (not exceeded and len(feats) < PAGE_SIZE):
            break
        offset += len(feats)
    return by_pin


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

async def enrich_durham_rollback_exposure(listings: Iterable[Listing], *,
                                          client: Optional[Any] = None) -> dict[str, Any]:
    """Bulk-fetch the GIS deferral set ONCE, join locally against every eligible Durham NC board
    row by parcel_id. No per-match network calls (unlike Pender's optional rate top-up) -- see
    module docstring's NO RATE TOP-UP section."""
    stats = {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings
              if _is_durham_nc(li) and str(li.parcel_id or "").strip()
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
            log.warning("durham_rollback.bulk_fetch_failed")
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

    log.info("durham_rollback.done", **stats)
    return stats
