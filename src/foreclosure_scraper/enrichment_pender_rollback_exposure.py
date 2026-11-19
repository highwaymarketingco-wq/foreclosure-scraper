"""Pender County NC's own live GIS parcel layer -> raw['rollback_exposure'] from its own
DEFERRED_VALUE field (present-use/agricultural/forestry deferral).

WHY THIS EXISTS (round 63 of the gap_matrix sweep, 2026-11-19). gap_matrix's sourced-not-built
list flagged Pender/rollback_exposure at 1,543 rows -- the ONLY one of Pender's four tax columns
still unbuilt (multi_year_delinquent_tax/two_year_delinquent are already covered by
enrichment_pender_multiyear_tax.py's live Tyler Munis walk; tax_aging_surfaced rides the same
generic tax_owed/aging claim those write). Pender's own qPublic-style parcel search was never
checked for a deferral field because the other three columns' fix already satisfied gap_matrix
for this county -- this module closes the fourth.

SOURCE. gis.pendercountync.gov publishes a "LayersMapIASLink" MapServer (iasWorld -- the
county's own CAMA/tax-assessment vendor -- linked layers, live-synced, not a stale export) whose
layer 4 ("Parcels") carries a LITERAL `DEFERRED_VALUE` field alongside `LAND_VALUE`,
`BUILDING_VALUE` and `TOTAL_VALUE` -- no derivation needed at all, the cleanest shape this
project's rollback_exposure producers have found (better than Currituck's AA502 XLSX workaround,
better than Mecklenburg's land-minus-total derivation): live-confirmed 2026-11-19 on 5 real
sampled parcels, `DEFERRED_VALUE == (LAND_VALUE + BUILDING_VALUE) - TOTAL_VALUE` to the dollar on
every one (e.g. PIN 2223-78-7833-0000, LAND $65,477 / BUILDING $0 / TOTAL $7,744 / DEFERRED
$57,733 -- 65,477 - 7,744 = 57,733, exact). `TAX_CODES` on every deferred parcel sampled carries a
`Fxx` program code (forestry) or similar present-use class, confirming the field's real meaning,
not a coincidence of arithmetic. County-wide: 52,748 total parcels, 2,547 with a real
DEFERRED_VALUE > 0 (live-counted via paginated `resultOffset`, NOT the naive single-page read a
first pass took -- the service's own `exceededTransferLimit` flag fires at ~1,000 full-geometry
rows per page well under its stated maxRecordCount of 2000, so a page short of 2000 is NOT
necessarily the last one; `returnGeometry=false` plus checking that flag, not just a row-count
guess, is the only correct stop condition -- confirmed live: a first, naive pass that broke on
"page < 2000 rows" silently missed 1,563 of the 2,547 real deferred rows).

PARCEL JOIN -- the easy case, unlike Currituck's. Pender's board `parcel_id`
("4214-33-9190-0000", 4-2-4-4 dashed digits) is the EXACT SAME shape and value as this layer's own
`PIN` field (confirmed live: 5/5 real Pender board parcel_ids queried by `PIN IN (...)` matched
exactly, e.g. board row "4203-52-3440-0000" == GIS PIN "4203-52-3440-0000", owner "TRIPLE 7
HOLDINGS LLC"). No dash-stripping, no `munis.search_id()`-style translation needed for THIS join
-- that translation is specific to the Munis tax-bill portal's own PARID format, a different
system this module does not query for the bulk match.

REAL YIELD, measured before building (not guessed): of Pender's 882 board rows with a resolvable
parcel_id and no existing `rollback_exposure`, 23 have a real, live DEFERRED_VALUE > 0 on this
layer today (live dry-run, 2026-11-19) -- a modest, genuinely verified population, overwhelmingly
HEIRS/ESTATE-named owners (Zibelin HEIRS, Eakins HEIRS, Barnhill HEIRS, Kelly HEIRS, Newkirk
HEIRS, Keith HEIRS, Lanier HEIRS, Ramsey HEIRS, Strickland HEIRS, Raynor HEIRS, Jones HEIRS) --
exactly this project's heir/probate distressed-property population, not a coincidence: present-use
ag/forestry deferral passes down through inherited land far more than it does through an active
owner-occupant's residence.

RATE TOP-UP (optional, capped, never hard-coded). The GIS layer carries no billed-tax-amount
field, so `annual_deferred_tax`/`estimated_rollback` need a real ad-valorem rate from somewhere --
same "never assume a millage" discipline enrichment_rollback_deferral.py's Buncombe/Mecklenburg/
Wake producers already established. Pender already has a PROVEN, live, working Tyler Munis
Citizen Self Service reader for exactly this county
(verification.verifiers.tax_lien_munis, reused unchanged here, same PORTAL entry
enrichment_pender_multiyear_tax.py already uses) -- this module reuses `search()`/`view()`
to read ONE real, current bill's own gross `amount` per matched parcel (capped at
PENDER_ROLLBACK_LIVE_CAP, default 50; today's real matched set is 23, so the cap is a safety
ceiling, not an expected-volume guess, exactly the Mecklenburg/Wake convention). rate =
amount / taxable_value (TOTAL_VALUE, the parcel's own reduced/deferred tax base already paying
that bill) is sanity-bounded to [_RATE_MIN, _RATE_MAX] (0.30%-1.60%, the same band Buncombe's and
Wake's own derived rates land in) before being trusted. CONCURRENCY for this top-up MUST stay 1,
same constraint enrichment_pender_multiyear_tax.py's own docstring already documents (Munis
caches one shared ASP.NET session PER PORTAL). A parcel whose top-up fails, times out, or derives
an out-of-band rate still keeps its real bulk `deferred_value` -- just without
`annual_deferred_tax`/`estimated_rollback`, never a guessed rate standing in for a missing one.

Gate off entirely with FORECLOSURE_PENDER_ROLLBACK=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing
from .verification.fetch import Fetcher
from .verification.verifiers import tax_lien_munis as munis

log = structlog.get_logger()

SLUG = "enrichment_pender_rollback_exposure"
STATE, COUNTY = "NC", "Pender"
LAYER_URL = ("https://gis.pendercountync.gov/arcgis/rest/services/"
             "LayersMapIASLink/MapServer/4/query")
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's own module docstring.
ROLLBACK_YEARS_NC = 4
#: Same sane-rate band Buncombe's/Wake's own derived rates land in
#: (enrichment_rollback_deferral.py's _RATE_MIN/_RATE_MAX) -- kept local rather than imported
#: to not couple this module to that one's internals for two constants.
_RATE_MIN, _RATE_MAX = 0.0030, 0.0160

ENABLED = os.environ.get("FORECLOSURE_PENDER_ROLLBACK") != "0"
_FETCH_TIMEOUT = float(os.getenv("PENDER_ROLLBACK_TIMEOUT", "60.0"))
#: Safety ceiling on the live Munis rate top-up, not an expected-volume guess -- see module
#: docstring's RATE TOP-UP section (today's real matched set is 23).
LIVE_CAP = int(os.environ.get("PENDER_ROLLBACK_LIVE_CAP", "50"))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

PORTAL = munis.PORTALS["Pender"]


# ---------------------------------------------------------------------------
# pure
# ---------------------------------------------------------------------------

def _is_pender_nc(li: Listing) -> bool:
    return (li.state or "").strip().upper() == STATE and \
        (li.county or "").replace(" County", "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    rb = raw.get("rollback_exposure") if isinstance(raw, dict) else None
    return isinstance(rb, dict) and rb.get("deferred_value") is not None


def build_rollback_block(rec: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] block from one GIS parcel record, or None when the
    record doesn't actually carry a real deferral (defensive -- the bulk fetch already filters
    server-side on DEFERRED_VALUE > 0, but a record reaching here with a bad/zero value is never
    trusted blindly)."""
    deferred = rec.get("deferred_value")
    taxable = rec.get("taxable_value")
    if not deferred or deferred <= 0 or not taxable or taxable <= 0:
        return None
    out: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "taxable_value": round(taxable, 2),
        "full_value": round(taxable + deferred, 2),
        "basis": "present_use_deferral",
        "county": COUNTY, "state": STATE,
        "source": "gis.pendercountync.gov LayersMapIASLink Parcels layer (DEFERRED_VALUE field)",
        "source_key": SLUG,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,
        "match_method": "parcel_id",
    }
    codes = rec.get("tax_codes")
    if codes:
        out["tax_codes"] = codes
    rate = rec.get("_rate")
    if rate is not None:
        annual = round(deferred * rate, 2)
        out["annual_deferred_tax"] = annual
        out["estimated_rollback"] = round(annual * ROLLBACK_YEARS_NC, 2)
        out["rate_basis"] = "live_munis_bill"
    return out


# ---------------------------------------------------------------------------
# bulk fetch (one paginated read, filtered server-side)
# ---------------------------------------------------------------------------

async def fetch_deferrals(client: httpx.AsyncClient) -> dict[str, dict]:
    """Every PIN with a real DEFERRED_VALUE > 0 on Pender's own live GIS parcels layer, keyed by
    the SAME dashed PIN format the board's own parcel_id already uses (no translation -- see
    module docstring's PARCEL JOIN section). MUST check `exceededTransferLimit`, not just
    `len(features) < requested`, to paginate correctly (module docstring's SOURCE note -- a
    short page is not necessarily the last one once geometry-driven byte limits are in play;
    `returnGeometry=false` here avoids that class of truncation but the check stays defensive)."""
    by_pin: dict[str, dict] = {}
    offset = 0
    while True:
        r = await client.get(LAYER_URL, params={
            "where": "DEFERRED_VALUE > 0",
            "outFields": "PIN,LAND_VALUE,BUILDING_VALUE,TOTAL_VALUE,DEFERRED_VALUE,TAX_CODES",
            "returnGeometry": "false",
            "resultOffset": offset, "resultRecordCount": 1000, "f": "json",
        })
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        feats = d.get("features", [])
        for f in feats:
            a = f.get("attributes", {})
            pin = (a.get("PIN") or "").strip()
            deferred = a.get("DEFERRED_VALUE")
            taxable = a.get("TOTAL_VALUE")
            if pin and deferred and deferred > 0:
                by_pin[pin] = {"deferred_value": deferred, "taxable_value": taxable,
                               "tax_codes": a.get("TAX_CODES")}
        exceeded = bool(d.get("exceededTransferLimit"))
        if not feats or (not exceeded and len(feats) < 1000):
            break
        offset += len(feats)
    return by_pin


# ---------------------------------------------------------------------------
# optional live rate top-up -- reuses tax_lien_munis unchanged, same portal
# enrichment_pender_multiyear_tax.py already drives for this county
# ---------------------------------------------------------------------------

async def _derive_rate(munis_client: Fetcher, board_parcel: str,
                       taxable_value: float) -> Optional[float]:
    """One real recent bill's gross `amount` / taxable_value, or None on any failure or an
    out-of-band result -- never a guessed rate (module docstring's RATE TOP-UP section).
    `munis_client` MUST be a verification.fetch.Fetcher (tax_lien_munis._session() calls its
    own `.form_session()`, a bare httpx.AsyncClient has no such method -- live-confirmed
    2026-11-19: passing one in silently produced rate_derived=0 on every one of 23 real
    matches before this was caught)."""
    parid = munis.search_id(board_parcel, COUNTY)
    try:
        rows = await munis.search(munis_client, PORTAL, parid)
    except Exception:  # noqa: BLE001 - every outcome here is "no rate," never a crash
        return None
    rows = [b for b in rows if "REAL ESTATE" in b.get("type", "")]
    if not rows:
        return None
    rows = sorted(rows, key=lambda b: -b["year"])
    try:
        bill = await munis.view(munis_client, PORTAL, parid, rows[0])
    except Exception:  # noqa: BLE001
        return None
    amount = bill.get("amount")
    if not amount or amount <= 0 or not taxable_value or taxable_value <= 0:
        return None
    rate = amount / taxable_value
    return rate if _RATE_MIN <= rate <= _RATE_MAX else None


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

async def enrich_pender_rollback_exposure(listings: Iterable[Listing], *,
                                          client: Optional[Any] = None) -> dict[str, Any]:
    """Bulk-fetch the GIS deferral set ONCE, join locally against every eligible Pender NC board
    row by parcel_id, then (CONCURRENCY=1, capped) try one live Munis rate top-up per real match
    so the block carries a real dollar annual/estimated figure where that top-up succeeds."""
    stats = {"eligible": 0, "deferred_pins": 0, "matched": 0, "rate_derived": 0,
              "rate_skipped_cap": 0, "fetch_errors": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings
              if _is_pender_nc(li) and str(li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats["eligible"] = len(targets)
    if not targets:
        return stats

    own_client = client is None
    cli = client or httpx.AsyncClient(timeout=_FETCH_TIMEOUT, headers={"User-Agent": _UA})
    try:
        try:
            by_pin = await fetch_deferrals(cli)
        except Exception:  # noqa: BLE001 - a failed bulk fetch must not crash the run
            stats["fetch_errors"] += 1
            log.warning("pender_rollback.bulk_fetch_failed")
            return stats
        stats["deferred_pins"] = len(by_pin)

        matched: list[tuple[Listing, dict]] = []
        for li in targets:
            hit = by_pin.get(str(li.parcel_id or "").strip())
            if hit is not None:
                matched.append((li, hit))
        stats["matched"] = len(matched)

        capped = matched[:LIVE_CAP]
        stats["rate_skipped_cap"] = len(matched) - len(capped)
        if capped:
            # Separate client for the Munis portal -- it needs Fetcher.form_session(), not the
            # bare httpx.AsyncClient the GIS bulk fetch above uses. Sequential (CONCURRENCY=1):
            # tax_lien_munis caches one shared ASP.NET session PER PORTAL, same constraint
            # enrichment_pender_multiyear_tax.py's own docstring already documents.
            munis_client = Fetcher(min_interval_s=0.5)
            for li, rec in capped:
                rate = await _derive_rate(munis_client, str(li.parcel_id or "").strip(),
                                           rec.get("taxable_value") or 0.0)
                if rate is not None:
                    rec["_rate"] = rate
                    stats["rate_derived"] += 1

        for li, rec in matched:
            block = build_rollback_block(rec)
            if block is None:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rollback_exposure"] = block
    finally:
        if own_client:
            await cli.aclose()

    log.info("pender_rollback.done", **stats)
    return stats
