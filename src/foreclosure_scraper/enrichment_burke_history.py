"""Burke County NC parcel-history diff enrichment.

Burke County publishes 11 annual parcel snapshot layers (2025 back to 2015)
on its ArcGIS FeatureServer. By diffing consecutive years we can detect:
  - Ownership changes (owner name changed year-over-year)
  - Structure loss (improvement value dropped to 0 or dwelling disappeared)
  - New construction (improvement value appeared where it was 0)

This is an ENRICHMENT, not a lead scraper. It adds ownership-change and
structure-loss flags to existing Burke listings on the board.

FREE, no login. Endpoint verified live 2026-08-18:
  https://gis.burkenc.org/arcgis/rest/services/Hosted/Burke_Parcel_History_v3/FeatureServer
  Layers 0-10: 2025 Parcels, 2024 Parcels, ..., 2015 Parcels
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

log = structlog.get_logger()

FEATURE_SERVER = (
    "https://gis.burkenc.org/arcgis/rest/services/Hosted/"
    "Burke_Parcel_History_v3/FeatureServer"
)

# Layer IDs: 0=2025, 1=2024, ..., 10=2015
LAYER_IDS = {2025: 0, 2024: 1, 2023: 2, 2022: 3, 2021: 4,
             2020: 5, 2019: 6, 2018: 7, 2017: 8, 2016: 9, 2015: 10}

# Fields to compare across years (verified from live sample 2026-08-19)
# NOTE: The service was re-hosted on ArcGIS Hub; field names changed from the
# original Tyler/Eagle schema. These are the actual field names as of 2026-08-19.
PIN_FIELD = "parno"           # 10-digit parcel number (matches board parcel_id w/o dashes)
OWNER_FIELD = "ownname"       # full owner name "WATTS, L W;WATTS, P"
VALUE_FIELD = "parval"        # total parcel value
IMPRV_FIELD = "improvval"     # improvement value (0 = no structure)
ACRE_FIELD = "gisacres"       # GIS-computed acres


def _norm_owner(s: str | None) -> str:
    """Normalize owner name for comparison."""
    if not s:
        return ""
    s = re.sub(r"[^a-zA-Z0-9 ]", "", s.upper()).strip()
    return re.sub(r"\s+", " ", s)


async def fetch_parcel_history(pin: str) -> dict[str, Any]:
    """Fetch ownership history for a single Burke County parcel by PIN.

    Returns dict with:
      - ownership_changes: list of (year, prev_owner, new_owner)
      - structure_loss: bool (improvement value dropped to 0)
      - new_construction: bool (improvement appeared where absent)
      - years_owned: int (years current owner has held the property)
    """
    # Normalize PIN: strip dashes/spaces so "2717-80-3032" -> "2717803032"
    pin = re.sub(r"[^0-9]", "", str(pin).strip())
    if not pin or len(pin) < 6:
        return {"ownership_changes": [], "structure_loss": False,
                "new_construction": False, "years_owned": 0}

    import asyncio
    from .http_client import get_text

    async def _fetch_one(year: int, layer_id: int) -> dict | None:
        url = (
            f"{FEATURE_SERVER}/{layer_id}/query"
            f"?where={PIN_FIELD}%3D'{pin}'"
            f"&outFields={OWNER_FIELD},{VALUE_FIELD},{IMPRV_FIELD},{ACRE_FIELD}"
            f"&returnGeometry=false&f=json"
        )
        try:
            data = json.loads(await get_text(url, timeout=15))
            feats = data.get("features") or []
            if feats:
                attrs = feats[0]["attributes"]
                return {
                    "year": year,
                    "owner": attrs.get(OWNER_FIELD),
                    "value": attrs.get(VALUE_FIELD),
                    "heated_area": attrs.get(IMPRV_FIELD),
                }
        except Exception:
            return None
        return None

    # Fetch all 11 years concurrently
    results = await asyncio.gather(
        *[_fetch_one(year, lid) for year, lid in LAYER_IDS.items()]
    )
    history = [r for r in results if r is not None]
    history.sort(key=lambda h: h["year"], reverse=True)

    if len(history) < 2:
        return {"ownership_changes": [], "structure_loss": False,
                "new_construction": False, "years_owned": 0}

    # Diff consecutive years
    ownership_changes: list[dict] = []
    structure_loss = False
    new_construction = False

    for i in range(1, len(history)):
        prev = history[i - 1]
        curr = history[i]
        prev_owner = _norm_owner(prev.get("owner"))
        curr_owner = _norm_owner(curr.get("owner"))

        if prev_owner and curr_owner and prev_owner != curr_owner:
            ownership_changes.append({
                "year": curr["year"],
                "prev_owner": prev.get("owner"),
                "new_owner": curr.get("owner"),
            })

        prev_area = prev.get("heated_area") or 0
        curr_area = curr.get("heated_area") or 0
        if prev_area and prev_area > 0 and (not curr_area or curr_area == 0):
            structure_loss = True
        if (not prev_area or prev_area == 0) and curr_area and curr_area > 0:
            new_construction = True

    # Years current owner has held
    years_owned = 0
    if history:
        current_owner = _norm_owner(history[0].get("owner"))
        for h in history:
            if _norm_owner(h.get("owner")) == current_owner:
                years_owned += 1
            else:
                break

    return {
        "ownership_changes": ownership_changes,
        "structure_loss": structure_loss,
        "new_construction": new_construction,
        "years_owned": years_owned,
    }


async def enrich_burke_parcel_history(listings: list) -> int:
    """Enrich Burke County listings with parcel-history flags.

    Adds to listing.raw['burke_history']:
      - ownership_change: bool (at least one ownership change detected)
      - structure_loss: bool
      - new_construction: bool
      - years_owned: int
    """
    import asyncio

    burke_listings = [li for li in listings
                      if getattr(li, "county", "") == "Burke"
                      and getattr(li, "parcel_id", None)]
    if not burke_listings:
        return 0

    log.info("burke_parcel_history.start", count=len(burke_listings))
    enriched = 0
    done = 0

    async def _do_one(li):
        nonlocal enriched, done
        pin = str(li.parcel_id).strip()
        if not pin:
            return
        try:
            result = await fetch_parcel_history(pin)
            if result["years_owned"] or result["ownership_changes"]:
                enriched += 1
            li.raw.setdefault("burke_history", result)
        except Exception as e:
            log.debug("burke_parcel_history.error",
                      pin=pin, error=str(e)[:80])
        finally:
            done += 1
            if done % 20 == 0:
                log.info("burke_parcel_history.progress",
                         done=done, total=len(burke_listings), enriched=enriched)

    # Run all parcels concurrently with a limit of 10 at a time
    sem = asyncio.Semaphore(10)

    async def _guarded(li):
        async with sem:
            await _do_one(li)

    await asyncio.gather(*[_guarded(li) for li in burke_listings])

    log.info("burke_parcel_history.done", enriched=enriched, total=len(burke_listings))
    return enriched
