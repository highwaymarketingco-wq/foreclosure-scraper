"""Hertford County NC's own live GIS parcel layer -> raw['rollback_exposure'] from its own
TOTAL_DEFERRED_VALUE field (present-use/agricultural/forestry + historic-property deferral).

WHY THIS EXISTS (round 66 of the gap_matrix sweep, 2026-11-19). gap_matrix's no-source-known
list flagged Hertford/rollback_exposure at 720 est_rows_affected. Checked for the same
literal-field shortcut rounds 63-65 found for Pender/Durham/Yancey before assuming a harder
derivation was needed (per this registry's own standing instruction to check remaining NC
counties for the same pattern) -- it was there, same vendor-template field names as Durham's.

SOURCE DISCOVERY. The county has no public ArcGIS Server REST root of its own at a guessable
path -- found instead via its public-facing app: the county's "GIS / Land Records" page links
an ArcGIS StoryMap/app org (owner `HertfordCountyGIS` on www.arcgis.com) whose "Tax Parcel
Viewer" Web Mapping Application (item 26b28f8a51164fc89431eedd61072339) embeds webmap
ad839383a07a4c6a94d1f2b5e93c1f4e, whose "Parcel Information" group layer carries a "Parcels"
sub-layer at gis.hertfordcounty.org/server/rest/services/TaxParcels/MapServer/2 -- the county's
own ArcGIS Server, a separate host from the hosted webmap. Live-verified 2026-11-19.

FIELDS. Among 100+ fields: a literal `TOTAL_DEFERRED_VALUE`, split into its two component
programs `USE_VALUE_DEFERRED` (present-use ag/horticultural/forestry) and
`HISTORIC_VALUE_DEFERRED` (NC G.S. 105-278 historic deferral) -- same three field names Durham's
own layer uses. Also `TOTAL_LAND_ASSESSED`, `TOTAL_BLDG_ASSESSED` (the FULL, not-yet-reduced
land/building values), `LAND_USE_VALUE` (the present-use-REDUCED land value) and
`TOTAL_PROP_VALUE`.

ORIENTATION -- the OPPOSITE of Durham's layer, confirmed live on 10 independently sampled
present-use rows before writing any code (every one matched to the dollar):
  * full_value   = TOTAL_LAND_ASSESSED + TOTAL_BLDG_ASSESSED            (NOT yet reduced)
  * taxable_value = TOTAL_PROP_VALUE                                     (ALREADY reduced --
    confirmed == LAND_USE_VALUE + TOTAL_BLDG_ASSESSED exactly, e.g. PIN 6941164705:
    land $72,092 + bldg $214,881 = full $286,973; LAND_USE_VALUE $32,472 + bldg $214,881 =
    TOTAL_PROP_VALUE $247,353; TOTAL_DEFERRED_VALUE $39,620 == $286,973 - $247,353 exactly).
  * deferred_value = TOTAL_DEFERRED_VALUE                                 (own literal field,
    no derivation at all -- unlike Durham, which must subtract two fields to GET taxable_value;
    here TOTAL_PROP_VALUE already IS taxable_value, so the only arithmetic this module does is
    full_value, which this layer doesn't carry as its own single field).
Do not copy Durham's "TOTAL_PROP_VALUE = full market value" assumption onto this county -- the
two vendors name the same concept with the same field name but opposite semantics; this was
checked live, not assumed, before building (see test file for the exact sampled-row numbers).

County-wide: 16,113 total parcels, 1,905 with a real TOTAL_DEFERRED_VALUE > 0 (11.8% -- a rural
present-use-heavy county, live-counted via paginated `resultOffset` + `exceededTransferLimit`,
same pagination discipline every sibling module in this family uses).

PARCEL JOIN -- NOT the easy bare-PIN case. Hertford board rows' own `parcel_id` is the 13-digit
REID (e.g. "6941164705000", "6904641238000" -- live-sampled from real board rows), NOT the
bare 10-digit PIN this layer also carries (PIN "6941164705" for the same parcel). The join key
is this layer's own `REID` field (exact string match, both 13-digit). Confirmed live by running
the actual join below, not assumed: 2 of 4 sampled board parcel_ids matched a real REID on this
layer exactly; the other 2 are genuine not-founds (empty `features`, no error -- a retired/
renumbered parcel, not a format mismatch).

REAL YIELD, measured before building (not guessed): of Hertford's 720 NC board rows, 448 carry
a resolvable parcel_id and no existing `rollback_exposure`; 46 of those have a real, live
TOTAL_DEFERRED_VALUE > 0 on this layer today (live dry-run, 2026-11-19) -- the largest single
real match count of this module family to date (Pender 23, Durham 11, Yancey 18).

NO RATE TOP-UP (deliberate, same reasoning as Durham's/Yancey's own simpler siblings, not
Pender's richer one). This layer carries no billed-tax-amount field, and this project has no
proven live tax-bill-portal reader registered for Hertford's own tax office -- so
`annual_deferred_tax`/`estimated_rollback` are left unset rather than guessed from an unverified
rate. `deferred_value`/`taxable_value`/`full_value` alone already close the gap_matrix column
for this county; a rate top-up can be added later IF a real Hertford tax-bill source is ever
wired, never invented here.

Gate off entirely with FORECLOSURE_HERTFORD_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_hertford_rollback_exposure"
STATE, COUNTY = "NC", "Hertford"
LAYER_URL = ("https://gis.hertfordcounty.org/server/rest/services/"
             "TaxParcels/MapServer/2/query")
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's own module docstring. Same
#: 4-year present-use window convention every sibling in this family applies uniformly.
ROLLBACK_YEARS_NC = 4

MAX_PAGES = int(os.getenv("HERTFORD_ROLLBACK_MAX_PAGES", "20"))
PAGE_SIZE = 1000
ENABLED = os.environ.get("FORECLOSURE_HERTFORD_ROLLBACK") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "")).upper()


def _is_hertford_nc(li: Listing) -> bool:
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
    taxable = rec.get("taxable_value")
    if taxable is None:
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
        "taxable_value": round(taxable, 2),
        "full_value": round(full, 2),
        "basis": basis,
        "county": COUNTY, "state": STATE,
        "source": "gis.hertfordcounty.org TaxParcels Parcels layer "
                   "(TOTAL_DEFERRED_VALUE field)",
        "source_key": SLUG,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,
        "match_method": "reid",
    }
    return out


# ---------------------------------------------------------------------------
# bulk fetch (one paginated read, filtered server-side)
# ---------------------------------------------------------------------------

async def fetch_deferrals(client: httpx.AsyncClient) -> dict[str, dict]:
    """Every REID with a real TOTAL_DEFERRED_VALUE > 0 on Hertford's own live GIS parcels
    layer, keyed by the SAME 13-digit REID format the board's own parcel_id already uses (no
    translation -- see module docstring's PARCEL JOIN section). MUST check
    `exceededTransferLimit`, not just `len(features) < requested`, to paginate correctly (same
    discipline every sibling module in this family documents)."""
    by_reid: dict[str, dict] = {}
    offset = 0
    for _ in range(MAX_PAGES):
        r = await client.get(LAYER_URL, params={
            "where": "TOTAL_DEFERRED_VALUE > 0",
            "outFields": "REID,TOTAL_LAND_ASSESSED,TOTAL_BLDG_ASSESSED,"
                         "USE_VALUE_DEFERRED,HISTORIC_VALUE_DEFERRED,TOTAL_DEFERRED_VALUE,"
                         "TOTAL_PROP_VALUE",
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
            reid = _compact_pid(a.get("REID"))
            deferred = a.get("TOTAL_DEFERRED_VALUE")
            land = a.get("TOTAL_LAND_ASSESSED") or 0
            bldg = a.get("TOTAL_BLDG_ASSESSED") or 0
            full = land + bldg
            if reid and isinstance(deferred, (int, float)) and deferred > 0 and full > 0:
                by_reid[reid] = {
                    "deferred_value": deferred,
                    "full_value": full,
                    "taxable_value": a.get("TOTAL_PROP_VALUE"),
                    "use_value_deferred": a.get("USE_VALUE_DEFERRED"),
                    "historic_value_deferred": a.get("HISTORIC_VALUE_DEFERRED"),
                }
        exceeded = bool(d.get("exceededTransferLimit"))
        if not feats or (not exceeded and len(feats) < PAGE_SIZE):
            break
        offset += len(feats)
    return by_reid


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

async def enrich_hertford_rollback_exposure(listings: Iterable[Listing], *,
                                            client: Optional[Any] = None) -> dict[str, Any]:
    """Bulk-fetch the GIS deferral set ONCE, join locally against every eligible Hertford NC
    board row by parcel_id (the 13-digit REID). No per-match network calls (unlike Pender's
    optional rate top-up) -- see module docstring's NO RATE TOP-UP section."""
    stats = {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings
              if _is_hertford_nc(li) and str(li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats["eligible"] = len(targets)
    if not targets:
        return stats

    own_client = client is None
    cli = client or httpx.AsyncClient(timeout=60.0, headers={"User-Agent": _UA})
    try:
        try:
            by_reid = await fetch_deferrals(cli)
        except Exception:  # noqa: BLE001 - a failed bulk fetch must not crash the run
            stats["fetch_errors"] += 1
            log.warning("hertford_rollback.bulk_fetch_failed")
            return stats
        stats["deferred_pins"] = len(by_reid)

        for li in targets:
            hit = by_reid.get(_compact_pid(li.parcel_id))
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

    log.info("hertford_rollback.done", **stats)
    return stats
