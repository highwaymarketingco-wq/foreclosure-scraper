"""Haywood County NC maps.haywoodcountync.gov ArcGIS REST "Land_Records/Public_Access"
MapServer, layer 1 -- raw['rollback_exposure'] from its own Defer_Value field.

WHY THIS EXISTS (round 18 of the tax-cluster gap_matrix sweep, 2026-11-17). Round 17's own note
said Haywood's matrix URL (.../ITSForPublic/TaxBillSearch) 404s and "the real ITSPublic
sub-path wasn't found." Found this round: that specific lead was a dead end for a DIFFERENT
reason than a wrong path -- taxes.haywoodcountync.gov/ITSForPublic is a real, live, OLDER
Bi-Tek deployment that answers 200 to a LOGIN page ("Bi-Tek - Login", a POST-back ASPX form),
not the newer no-login ITSPublic/TaxBillSearch grid family this project reads for Davidson/
Onslow/Graham/etc. -- a genuine wall (login-gated), not a missing path; this module does not
attempt it. The real usable lead found instead: the county's own GIS host,
maps.haywoodcountync.gov, has a live, open, unauthenticated ArcGIS REST directory ->
Land_Records/Public_Access/MapServer/1 ("Parcels"), whose own field list carries Defer_Value, a
present-use-deferred assessment -- the same shape as Davidson/Craven/Macon's own rollback
fields this round. Live-confirmed real, nonzero values 2026-11-17: 2,667 of this layer's
parcels carry Defer_Value > 0, e.g. PIN "8609-42-0939", owner "ROSS, HOBERT DEAN/TR",
Defer_Value $512,639 of $944,600 Mkt_Value (Assd_Value = Mkt_Value - Defer_Value exactly on
every sampled row).

DECLINED, same layer, two OTHER columns (NOT built here). This layer ALSO carries TaxYear1/
TaxYear2/Taxbill1_Amt/Taxbill2_Amt (an apparent 2-years-of-billing mirror) -- but every sampled
row (dozens checked, zero exceptions) reads TaxYear1="2020"/TaxYear2="2019", while this SAME
layer's own Sale_Date field has real sales as recent as "11 13 2026" (today is 2026-11-17) --
proof the parcel dataset overall is actively, currently maintained, which rules out "the whole
layer is a stale export" as the explanation. The tax-bill mirror specifically was abandoned
around 2020 and never updated since (the silently-stale-producer bug class, but on the COUNTY's
own vendor side, not fixable from here): a parcel reading "unpaid 2019+2020" today could have
been paid off years ago with no way to tell from this field. multi_year_delinquent_tax/
two_year_delinquent/tax_aging_surfaced are NOT built off Taxbill1/Taxbill2 for this reason --
see docs/gap_matrix/declined_registry.json.

PARCEL JOIN. `ALPHA` (the layer's own PIN label) uses the SAME dashed PIN format the board
already carries for most Haywood rows ("8609-42-0939"); `_compact_pid()` strips punctuation on
both sides so a board row with (or without) the dashes still matches (live-confirmed against 5
real Haywood board rows, e.g. board parcel_id "8605-90-3984" -> "8605903984").

BULK, not per-row: queried ONCE per run (paginated, resultOffset in steps of 1000, server-side
filtered to Defer_Value > 0 so the real page count stays small -- 2,667 rows, under 2 pages at
this vendor's own maxRecordCount) and joined locally against the board's already-known Haywood
NC rows. Free, public, no login, no CAPTCHA/WAF.

Gate off entirely with FORECLOSURE_HAYWOOD_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_haywood_rollback_exposure"
STATE, COUNTY = "NC", "Haywood"
SERVICE = "https://maps.haywoodcountync.gov/arcgis/rest/services/Land_Records/Public_Access/MapServer"
LAYER = 1
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_PAGES = int(os.getenv("HAYWOOD_ROLLBACK_MAX_PAGES", "10"))
PAGE_SIZE = 2000
ENABLED = os.environ.get("FORECLOSURE_HAYWOOD_ROLLBACK") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    return _NON_ALNUM.sub("", str(pid or "")).upper()


async def fetch_deferred_by_pid(c: httpx.AsyncClient) -> dict[str, dict]:
    """{compact_pid: {"deferred_value", "market_value", "assessed_value"}} from layer 1,
    positive deferrals only."""
    by_pid: dict[str, dict] = {}
    offset = 0
    for _ in range(MAX_PAGES):
        params = {"where": "Defer_Value > 0",
                  "outFields": "ALPHA,Defer_Value,Mkt_Value,Assd_Value", "f": "json",
                  "resultRecordCount": str(PAGE_SIZE), "resultOffset": str(offset)}
        r = await c.get(f"{SERVICE}/{LAYER}/query", params=params)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Haywood Public_Access query error: {data['error']}")
        feats = data.get("features") or []
        for feat in feats:
            attrs = feat.get("attributes", {}) if isinstance(feat, dict) else {}
            pid = _compact_pid(attrs.get("ALPHA"))
            deferred = attrs.get("Defer_Value")
            if not pid or not isinstance(deferred, (int, float)) or deferred <= 0:
                continue
            by_pid[pid] = {"deferred_value": float(deferred), "market_value": attrs.get("Mkt_Value"),
                           "assessed_value": attrs.get("Assd_Value")}
        # exceededTransferLimit, not a row-count comparison, is the reliable "more pages exist"
        # signal -- live-confirmed THIS layer's own maxRecordCount is 1,000, so a naive
        # `len(feats) < PAGE_SIZE` (2,000) check stopped after page 1 and silently dropped
        # ~63% of the real rollback_exposure rows (896 of 2,667) before this fix. See
        # scrapers/counties_nc/craven_tax_table.py's own _query_all() docstring.
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return by_pid


def build_rollback_block(rec: dict) -> Optional[dict]:
    deferred = rec.get("deferred_value")
    if not deferred or deferred <= 0:
        return None
    out: dict[str, Any] = {"deferred_value": round(float(deferred), 2),
                           "basis": "present_use_deferral", "county": COUNTY, "state": STATE,
                           "source": "maps.haywoodcountync.gov Land_Records/Public_Access "
                                      'MapServer ("Defer_Value")',
                           "source_key": SLUG, "rollback_years": ROLLBACK_YEARS_NC,
                           "estimate_is_floor": True, "match_method": "parcel_id"}
    if rec.get("market_value"):
        out["market_value"] = rec["market_value"]
    return out


def _is_haywood_nc(li: Listing) -> bool:
    return li.state == STATE and (li.county or "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    """Only a REAL dollar deferred_value counts as done -- see the identical fix/finding in
    enrichment_macon_rollback_exposure.py's own _already_done() (this module's sibling): a
    flag-only rollback_exposure block from the statewide nc_onemap_presentval sweep must not
    block this producer's own real-dollar Defer_Value join."""
    rb = raw.get("rollback_exposure") if isinstance(raw, dict) else None
    return isinstance(rb, dict) and rb.get("deferred_value") is not None


async def enrich_haywood_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Fetch Haywood's Public_Access Defer_Value field ONCE (bulk, paginated), then join
    locally against every Haywood NC board row by parcel_id. Writes raw['rollback_exposure']
    only when Defer_Value is positive -- never invented."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_HAYWOOD_ROLLBACK=0)"}
    targets = [li for li in listings
              if _is_haywood_nc(li) and (li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats = {"eligible": len(targets), "deferred_pids": 0, "matched": 0, "errors": 0}
    if not targets:
        return stats

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA}) as c:
        try:
            by_pid = await fetch_deferred_by_pid(c)
        except Exception:  # noqa: BLE001 - a failed fetch must not crash the run
            stats["errors"] += 1
            log.warning("haywood_rollback.fetch_failed")
            return stats
    stats["deferred_pids"] = len(by_pid)

    for li in targets:
        hit = by_pid.get(_compact_pid(li.parcel_id))
        if hit is None:
            continue
        block = build_rollback_block(hit)
        if not block:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rollback_exposure"] = block
        stats["matched"] += 1

    log.info("haywood_rollback.done", **stats)
    return stats
